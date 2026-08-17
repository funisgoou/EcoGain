# DEPLOY — 腾讯云部署手册（HTTP 版）

> 适用：POC 演示级上线，单机 2C4G，公网 HTTP 直连（暂不上 HTTPS/证书）。
> 拓扑：**frontend(nginx :80) 统一入口** → 同源分流 backend(:8000) / auth-server(:8001)，
> 两服务仅绑定服务器回环地址（公网不可见）；MySQL 用腾讯云外部库；DuckDB 嵌入 backend 进程，落在 `/data` 卷。

```
浏览器 ── http://<公网IP>/ ──► nginx(frontend 容器 :80)
                                 ├─ /、/assets/*      → 静态文件（SPA）
                                 ├─ /api/*            → backend:8000（REST + WebSocket）
                                 ├─ /auth/*           → backend:8000（OAuth 登录/回调/登出）
                                 ├─ /healthz          → backend:8000
                                 └─ /authorize        → auth-server:8001（登录页）
backend ──容器内网──► auth-server:8001（/token /userinfo，走 AUTH_INTERNAL_BASE_URL）
backend/auth-server ──公网/内网──► 腾讯云 MySQL（.env 配置）
```

---

## 0. 本机前置：代码必须先推送

服务器通过 `git clone` 拿代码，**当前 `frontend/` 尚未提交**（连同若干本地改动），先在本机：

```bash
git add -A
git commit -m "feat: 前端容器化与 nginx 统一入口（上线部署）"
git push origin main
```

> `.env` 已被 .gitignore 忽略，不会（也不允许）随代码上去，服务器上单独创建（见 §3）。

## 1. 购买与初始化服务器

1. **规格**：轻量应用服务器或 CVM，2C4G、Ubuntu 22.04、系统盘 40G+，地域**与 MySQL 实例同地域**（内网互通更快且免公网流量费）。
2. **安全组/防火墙**：入站只放行 `22`(SSH) 和 `80`(HTTP)。
3. SSH 登录后装 Docker（Ubuntu 官方源；国内网络慢可用腾讯云镜像）：

```bash
curl -fsSL https://get.docker.com | bash -s docker --mirror Aliyun
# 验证
docker --version && docker compose version
```

## 2. MySQL 侧准备

腾讯云 MySQL 控制台：

1. **白名单/安全组**放行服务器 IP：
   - 服务器与 MySQL 同地域同 VPC → 加服务器**内网 IP**，`MYSQL_HOST` 用内网地址；
   - 跨地域/公网 → 加服务器**公网 IP**，`MYSQL_HOST` 用外网地址。
2. 库无需手工建表：backend 启动时自动跑 `alembic upgrade head`；auth 库账号由 auth-server 启动时幂等 seed。

## 3. 服务器上部署

```bash
git clone https://github.com/funisgoou/EcoGain.git && cd EcoGain
```

创建 `.env`（模板，`<服务器公网IP>` 与 MySQL 内/外网地址按实际替换；两个 SECRET 用 `openssl rand -hex 32` 生成）：

```ini
MYSQL_HOST=<腾讯云MySQL内网或外网地址>
MYSQL_PORT=3306
MYSQL_USER=<沿用现有值>
MYSQL_PASSWORD=<沿用现有值>
MYSQL_DATABASE=<沿用现有值>
MYSQL_AUTH_DATABASE=<沿用现有值>

# 三个 BASE_URL 全部指向 nginx 统一入口（HTTP + 公网 IP；有域名则换域名）
PUBLIC_BASE_URL=http://<服务器公网IP>
FRONTEND_BASE_URL=http://<服务器公网IP>
AUTH_BASE_URL=http://<服务器公网IP>

DATA_DIR=/data
LLM_API_KEY=<沿用现有值>
AUTH_CLIENT_SECRET=<openssl rand -hex 32 生成>
AUTH_JWT_SECRET=<openssl rand -hex 32 生成>
TZ=Asia/Shanghai
```

> 注意：**AUTH_CLIENT_SECRET 换新值后，MySQL `auth_clients.client_secret` 里还是旧值**，
> 需执行 §5 的 SQL 同步（一条 UPDATE 同时改 redirect_uri 和 secret）。

拉起（首次构建约 3~5 分钟）：

```bash
docker compose up -d --build
docker compose ps          # 三个容器应为 running/healthy
```

backend 容器入口自动完成：等 MySQL 可达 → alembic 迁移 → DuckDB 灌数（幂等）→ 起 uvicorn。
看启动日志：`docker compose logs -f backend`，出现 `app_started` 即就绪。

## 4. 必做一次性修正：OAuth redirect_uri / client_secret

`auth_clients` 记录是**本机联调时**按当时的 `PUBLIC_BASE_URL`（localhost）灌入的，
auth-server 只在记录不存在时才插入，改环境变量不会更新旧记录——不执行此步登录必挂（redirect_uri 不匹配）。

用任意 MySQL 客户端执行：

```sql
UPDATE auth_clients
SET redirect_uri = 'http://<服务器公网IP>/auth/callback',
    client_secret = '<与服务器 .env 中 AUTH_CLIENT_SECRET 相同的值>'
WHERE client_id = 'ecogain-web';
```

## 5. 验证清单

| # | 动作 | 预期 |
|---|------|------|
| 1 | `curl http://127.0.0.1/healthz`（服务器上） | `{"status":"ok","mysql":true,"duckdb":true,"llm_config":true}` |
| 2 | 浏览器开 `http://<公网IP>/` | 登录页正常渲染 |
| 3 | 点登录 → 认证中心账密页 | 地址栏变为 `http://<IP>/authorize?...` |
| 4 | 登录 `analyst / EcoGain@2026` | 302 回 `/workbench`，用户名显示正确 |
| 5 | 新建会话发一个问题 | WS 正常建连，进度推送流畅，出六段报告 |
| 6 | 上传 csv 附件 | 上传成功且能引用分析 |
| 7 | `curl -I http://<公网IP>:8000/`（外部） | **超时/拒绝**（8000/8001 未暴露公网） |

## 6. 日常运维

```bash
docker compose logs -f backend          # 看后端日志（JSON 结构化）
docker compose restart backend          # 重启单个服务
git pull && docker compose up -d --build  # 发版：拉代码重建
docker compose down                     # 全停（/data 卷保留，数据不丢）
```

- **数据落点**：`app-data` 卷（DuckDB、附件、导出）；MySQL 在云上。`docker compose down` 不删卷；
  `down -v` 才会（⚠️ 演示重置才用）。
- **重启影响**：DuckDB 的 4 个演示 schema（s1~s4）每次启动会 DROP 重建（灌数脚本幂等设计）；
  附件动态表在 `attachments` schema，**不受影响**；会话/消息在 MySQL，不受影响。

## 7. 常见问题排查

| 现象 | 原因与处理 |
|------|-----------|
| backend 起不来，日志反复 `waiting for MySQL` | MySQL 白名单没放行服务器 IP，或 MYSQL_HOST 用错内/外网地址 |
| 登录页点登录后报 `redirect_uri` 相关错误 | §4 的 UPDATE 没执行或 IP 填错 |
| 能登录但 WS 连不上/无进度推送 | 浏览器 F12 Network→WS 看握手；确认走的是 `ws://<IP>/api/chat/ws/...`；服务器 `docker compose logs backend` 查 `ws_connected` |
| 登录成功但接口全 401 | 检查浏览器 Cookie 是否有 `ecogain_session`；日期/时区异常会导致会话判定问题（确认 `TZ=Asia/Shanghai`） |
| 上传附件 413 | nginx `client_max_body_size`（当前 30m）不够时调 `docker/nginx.conf` 后重建 frontend |
