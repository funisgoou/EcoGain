# DEPLOY — 腾讯云部署踩坑实录（2026-08-17）

> 一次真实部署的完整踩坑记录，按部署流程时间线排列。每条坑按 **现象（报错原文）→ 原因 → 解决** 组织，
> 报错原文保留原样，便于下次搜索引擎式查档。配套的部署步骤见《DEPLOY-腾讯云部署手册.md》。

## 架构速览（理解坑的前提）

```
浏览器 ── http://<公网IP>/ ──► frontend 容器（nginx :80，唯一公网入口）
                                 ├─ /api/* /auth/* /healthz → backend:8000（仅绑 127.0.0.1）
                                 └─ /authorize             → auth-server:8001（仅绑 127.0.0.1）
backend ──容器内网──► auth-server（/token /userinfo）
backend / auth-server ──► 腾讯云 MySQL（外部库，.env 配置）
DuckDB 嵌在 backend 进程内，文件落在 app-data 卷 /data
```

三条铁律，后面一半的坑都源于违反它们：

1. **公网只走 80**，BASE_URL 一律 `http://<公网IP>` 不带端口；
2. **服务器只维护仓库根目录一个 `~/EcoGain/.env`**（容器靠 compose `environment:` 注入，改后必须 `--force-recreate`）；
3. **数据库里 `auth_clients` 的 redirect_uri/client_secret 是旧值时，改环境变量救不了，必须手动 UPDATE**。

---

## 坑 1：Docker Hub 拉基础镜像超时（构建阶段）

**现象：**

```
ERROR [auth-server internal] load metadata for docker.io/library/python:3.12-slim  30.0s
ERROR [frontend internal] load metadata for docker.io/library/node:20-alpine       30.0s
failed to resolve source metadata for docker.io/library/python:3.12-slim:
failed to do request: Head "https://registry-1.docker.io/v2/library/python/manifests/3.12-slim":
dial tcp 199.59.149.239:443: i/o timeout
```

**原因：** 国内服务器直连 Docker Hub（registry-1.docker.io）基本不通。注意此时尚未执行到任何 Dockerfile 指令，挂在"拉基础镜像"一步——所以改 Dockerfile 加 pypi 镜像没用（那是下一个阶段的事）。

**解决（一次性，配 Docker 守护进程镜像加速）：**

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": ["https://mirror.ccs.tencentyun.com"]
}
EOF
sudo systemctl daemon-reload && sudo systemctl restart docker
docker info | grep -A 2 "Registry Mirrors"   # 验证生效
```

腾讯云内网专用源 `mirror.ccs.tencentyun.com` 只在腾讯云机器上可用；抽风时备选 `https://docker.1ms.run`。

---

## 坑 2：ghcr.io 拉 uv 间歇性 EOF（构建阶段）

**现象：** 坑 1 修好后，docker.io 的 python/node/nginx 全部秒过，但挂在：

```
> [backend internal] load metadata for ghcr.io/astral-sh/uv:latest
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
target backend: failed to solve: failed to fetch anonymous token:
Get "https://ghcr.io/token?...": EOF
```

**原因：** 两个后端 Dockerfile 原本用 `COPY --from=ghcr.io/astral-sh/uv:latest` 从 GitHub 镜像仓拷 uv 二进制。**ghcr.io 国内时通时断**（同一会话里第一次 5.7s 成功、重试就 EOF），且坑 1 配的 `registry-mirrors` 只对 docker.io 生效，帮不到 ghcr.io。

**解决：** 改为从 pypi 安装 uv（配合腾讯 pypi 镜像 = 内网速度），版本锁死与本机开发环境一致：

```dockerfile
ARG PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL} UV_DEFAULT_INDEX=${PIP_INDEX_URL} ...
RUN pip install --no-cache-dir uv==0.11.17
```

---

## 坑 3：概念辨析——三层"加速"配置各管一段

构建一条链路分三段，慢在哪段就配对应的层，互不替代：

| 层 | 慢/挂的表现 | 配置位置 |
|---|---|---|
| ① 容器镜像拉取 | `load metadata for docker.io/...` 超时（坑 1） | `/etc/docker/daemon.json` 的 `registry-mirrors` |
| ② Python 包下载 | 构建卡在 `uv sync` / `pip install`（坑 2 的解决顺带配好） | Dockerfile `ENV PIP_INDEX_URL` / `UV_DEFAULT_INDEX` |
| ③ npm 包下载 | 构建卡在 `npm ci` | Dockerfile `ENV npm_config_registry=...`（本次未用到，npmjs 直连尚可） |

两个易错细节：

- **uv 不认 `PIP_INDEX_URL`**，它自己的变量是 `UV_DEFAULT_INDEX`（旧名 `UV_INDEX_URL`）。网上抄的 `ARG PIP_INDEX_URL=...` 对 uv 项目无效，两个都要设。
- **`uv sync --frozen` 会按 uv.lock 里固化的 pypi.org URL 下载，绕过镜像配置**；改用 `--locked`（同样校验锁文件一致性，但尊重 `UV_DEFAULT_INDEX` 走镜像）。

---

## 坑 4：auth-server 启动即崩——连主机名 'mysql' 解析失败（启动阶段）

**现象：** `ecogain-auth` 容器反复退出，日志：

```
sqlalchemy.exc.OperationalError: (asyncmy.errors.OperationalError)
(2003, "Can't connect to MySQL server on 'mysql' ([Errno -3] Temporary failure in name resolution)")
ERROR:    Application startup failed. Exiting.
```

**原因：** 服务器上**没创建根目录 `.env`**，compose 落到默认值 `${MYSQL_HOST:-mysql}`。`mysql` 这个主机名是给 local-db 模式（同 compose 里的容器 MySQL）用的，而本次部署用腾讯云外部库、没起这个容器，自然解析不了。auth-server 启动第一步就连库 seed 演示账号，连不上直接退出。backend 同病不同症——它的启动脚本在死等循环里，表现为一直 `waiting for MySQL mysql:3306`。

**解决：** 在 `~/EcoGain/` 创建根 `.env`（模板见部署手册 §3），重点 `MYSQL_HOST` 填腾讯云库真实地址，然后：

```bash
docker compose up -d --force-recreate
```

**关联澄清（当时问过的问题）：**

- 服务器上**不需要** `backend/.env`——那是本地直跑（`uv run uvicorn`，Settings 的 `env_file=".env"` 相对 `backend/` 解析）才用的；容器部署全靠 compose 注入环境变量，且 `.dockerignore` 排除了 `**/.env`，镜像里根本没有这个文件。
- `APP_HOST` / `APP_PORT` 这类变量**本项目代码不读**，填了也无效。端口写死在 compose（`"80:80"`、uvicorn 启动命令 8000）和 Dockerfile（`CMD` 8001）里。

---

## 坑 5：点登录跳回 localhost（登录链路）

**现象：** 本机浏览器访问 `http://公网IP/`，点登录后地址栏变成：

```
http://localhost:8001/authorize?client_id=ecogain-web&redirect_uri=http://localhost:8000/auth/callback&...
```

**原因：** `.env` 里三个 BASE_URL 没填（或没生效），compose 注入了默认值
`AUTH_BASE_URL:-http://localhost:8001`、`PUBLIC_BASE_URL:-http://localhost:8000`，backend 原样拼出跳转地址。

**解决：** `.env` 补上，然后重建容器：

```ini
PUBLIC_BASE_URL=http://<公网IP>
FRONTEND_BASE_URL=http://<公网IP>
AUTH_BASE_URL=http://<公网IP>
```

```bash
docker compose up -d --force-recreate
```

**原理：** 环境变量是**容器创建时**一次性注入的，`docker compose restart` 不会重读 `.env`，必须 recreate。`--force-recreate` 会自动停旧容器（SIGTERM 优雅停机）→ 删 → 按新配置建新容器，**不删数据卷**（`down -v` 才删）。

---

## 坑 6：BASE_URL 带了端口号 → 浏览器直连 8001 打不开（登录链路）

**现象：** 坑 5 修完后，跳转地址变成了——

```
http://124.222.134.253:8001/authorize?...&redirect_uri=http://124.222.134.253:8000/auth/callback&...
HTTP ERROR 502 / This page isn't working
```

**原因：** 照本地开发习惯把 BASE_URL 填成了 `http://<IP>:8000`。于是浏览器被指去**直连 8001/8000**，而这两个端口按设计只绑服务器回环（`127.0.0.1:8001:8001`），公网根本不通——这正是收敛端口的目的，但 BASE_URL 必须配合走 80。

**解决：** 三个 BASE_URL 一律**不带端口**（`http://124.222.134.253`），然后 `--force-recreate backend`。

**验证跳转地址已纠正：**

```bash
curl -sI http://127.0.0.1/auth/login | grep -i location
# 期望：http://<公网IP>/authorize?...&redirect_uri=http://<公网IP>/auth/callback&...  （全程无端口）
```

---

## 坑 7：`auth_clients` 表旧数据 → redirect_uri 不匹配 / secret 对不上（登录链路）

**现象：** BASE_URL 全部修正后，登录卡在认证中心，报 redirect_uri 不匹配或授权码换 token 失败。

**原因：** MySQL 里 `auth_clients`（client_id=`ecogain-web`）的 `redirect_uri` 和 `client_secret` 是**本机联调时**按当时的 `PUBLIC_BASE_URL`（localhost）灌入的。auth-server 的 seed 逻辑是"记录不存在才插入"——改环境变量**不会更新已有记录**。

**解决（一次性 SQL）：**

```sql
UPDATE auth_clients
SET redirect_uri = 'http://<公网IP>/auth/callback',
    client_secret = '<与服务器 .env 的 AUTH_CLIENT_SECRET 相同>'
WHERE client_id = 'ecogain-web';
```

`client_secret` 必须一并同步：`.env` 里新生成了 SECRET，库里还是旧值的话 backend 换 token 会 401。

---

## 坑 8：502 Bad Gateway 的三种含义（排查思路）

502 = nginx 活着，它背后的 backend 不通。按概率排查：

| 情形 | 特征 | 处理 |
|---|---|---|
| **a) 启动窗口期（最常见）** | 容器刚 `--force-recreate`，backend 在重走"等 MySQL → alembic 迁移 → DuckDB 灌数"，全程约 2 分钟；期间 curl `/healthz` 必 502 | 等 `docker logs -f ecogain-backend` 出现 `app_started`；灌数过程会打印各场景行数统计，属正常输出 |
| **b) nginx 缓存旧容器 IP** | `app_started` 之后仍 502；backend 重建换了内网 IP，nginx 启动时解析过一次不再更新 | `docker compose restart frontend` |
| **c) backend 真挂了** | 容器 Exited/Restarting | `docker logs --tail 50 ecogain-backend` 看报错栈（如坑 4） |

**就绪判定：**

```bash
curl http://127.0.0.1/healthz
# {"status":"ok","mysql":true,"duckdb":true,"llm_config":true}
```

服务器回环测 502 即可排除公网/安全组因素，把问题锁定在容器之间。

---

## 坑 9：安全组与白名单（网络层）

- **服务器安全组只放行 22（SSH）+ 80（HTTP）**。不需要也不应该放 8000/8001（已绑回环，放行也无效）和 3306（MySQL 在腾讯云，不在这台机器）。
- **腾讯云 MySQL 白名单要加这台服务器的公网 IP**。本机联调时白名单放行的是办公网 IP，换服务器部署最容易忘。症状：backend 日志无限 `waiting for MySQL <地址>:3306`（TCP 层探测，认证错误也表现为连不上）。

---

## 附 A：排查命令速查

```bash
docker compose ps                                  # 容器状态（Up/Exited/Restarting）
docker logs --tail 50 ecogain-backend              # 后端日志（灌数/app_started 都在这看）
docker logs --tail 50 ecogain-auth                 # 认证服务日志
docker exec ecogain-backend printenv | grep BASE_URL   # 容器实际拿到的环境变量（验证 .env 是否生效）
curl http://127.0.0.1/healthz                      # 整体就绪探测（绕过公网链路）
curl -sI http://127.0.0.1/auth/login | grep -i location  # 检查 OAuth 跳转地址拼得对不对
docker compose restart frontend                    # 502 且 backend 已就绪时（nginx 刷新容器 IP）
docker compose up -d --force-recreate              # 改 .env 后必用（自动停删建容器，不删卷）
docker exec ecogain-backend python -c "import socket;s=socket.socket();s.settimeout(3);s.connect(('124.222.134.253',3306));print('OK')"  # 容器内测云 MySQL 连通性
```

## 附 B：正确上线顺序（浓缩版，照此走可避开上述大部分坑）

1. 装 Docker + `/etc/docker/daemon.json` 配腾讯镜像源（坑 1）；
2. `git clone` + 创建根 `.env`：BASE_URL 不带端口（坑 5/6）、MYSQL_* 用真实值（坑 4）、两个 SECRET 用 `openssl rand -hex 32` 新生成；
3. `docker compose up -d --build`，**耐心等 2 分钟**灌数，看日志 `app_started`（坑 8a）；
4. 执行 `auth_clients` 的 UPDATE SQL（坑 7）；
5. 验证：`curl http://127.0.0.1/healthz` 全绿 → 浏览器 `http://公网IP/` 走完整登录。
