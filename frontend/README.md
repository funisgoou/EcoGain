# EcoGain 前端

「EcoGain 经营归因分析系统」前端工程（POC 演示级）。单 Agent 多轮对话：查数 → 归因 → 追问 → 六段结构化报告。

- 接口契约唯一依据：`docs/API-接口设计文档.md`
- 前端模块设计依据：`docs/SPEC-功能规格说明.md` 第 5 节
- 视觉依据：`designs/login.png` / `designs/workspace.png`

## 技术栈

Vue 3 + Vite + TypeScript + Pinia + Vue Router 4 + axios（`withCredentials: true`）+ marked + dompurify。
无 UI 组件库（样式手写还原设计稿），SFC 一律 `<script setup lang="ts">`。

## 快速开始

```bash
npm install

# Mock 模式（无需后端，内置内存实现 + WS 时序回放，用于演示与视觉走查）
VITE_USE_MOCK=true npm run dev        # *nix
$env:VITE_USE_MOCK="true"; npm run dev # PowerShell

# 联调模式（默认）：代理 /api、/auth 到 http://localhost:8000
npm run dev

# 类型检查 / 构建
npm run type-check
npm run build
```

环境变量见 `.env.example`（当前仅 `VITE_USE_MOCK`，默认 `false`）。

## 目录结构

```
src/
├── api/
│   ├── http.ts       # axios 实例：统一响应包解包、40101 跳登录、blob 错误体解析
│   ├── index.ts      # 全部契约接口函数（含类型）
│   ├── mock.ts       # Mock 内存实现：REST + WS 时序回放（API 文档 §8.4）
│   └── runtime.ts    # VITE_USE_MOCK 开关
├── composables/
│   └── useWebSocket.ts  # FE-9 状态机：idle→connecting→open→closed(reconnecting)
├── stores/           # auth / conversation / chat / task / attachment / result / admin
├── views/            # Login / AuthCallback / Workbench / Admin
├── components/       # 会话侧栏、消息、工具块、任务条、输入区、附件抽屉、结果面板等
├── styles/           # tokens.css（设计变量）+ base.css（reset / md-body / 通用按钮）
├── utils/            # 时间、Markdown、下载、错误文案、toast
└── types.ts          # DTO + WS 上下行消息类型（与契约字段一致）
```

## 契约缺口（原待后端补充，v1.1 已收编）

以下两个接口原不在 `docs/API-接口设计文档.md` 中，前端先行按约定调用并做了降级处理；**后端已实现，契约文档已增补（v1.1 §3.4 / §7.3）**，降级逻辑保留作为旧后端兼容：

| 接口 | 用途 | 原降级策略（现仅兜底） |
| --- | --- | --- |
| `GET /api/auth/me` | 获取当前用户 `{user_id, username, display_name, role}`，用于登录态判定与 admin 入口显隐（FE-10） | 40101 → 未登录（跳 /login）；404/网络错误 → 视为「已登录但角色未知」，隐藏 admin 入口，admin 页访问交由后端 40301 兜底 |
| `GET /api/admin/configs` | 配置读取（管理页分组展示 llm/agent/datasource/feature），返回数组 `[{config_group, config_key, config_value, description, updated_at}]` | 404 → 管理页展示占位说明，「重载配置」功能不受影响 |

## 契约要点落实

- 认证：Cookie 会话 `ecogain_session`（HttpOnly），axios `withCredentials: true`；登出走 `POST /auth/logout`（契约 §3.3，非 /api 前缀）。
- 统一响应包 `{code, message, data}` 在 http 拦截器解包，`code !== 0` 抛 `ApiError`；40101 且不在 /login、/auth/callback 时跳登录页。
- 消息上行只走 WS（`user_message`），不走 REST；发送被拒（task_id=0 的 error，如 40901）渲染错误条 + 重试。
- WS 关闭码：4401 → 重新取 token 再连；4408/其他 → 指数退避 1s/2s/4s/8s（上限 30s），连续 10 次失败提示网络异常。
- 附件解析状态：WS `attachment_status` 为主，`GET /api/chat/ls/{cid}` 附件聚合 5s 轮询兜底，ready/failed 即停。
- 时间统一 ISO 8601 毫秒本地时间；界面相对时间（刚刚 / n分钟前 / 昨天 / n天前）。
