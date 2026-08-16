# EcoGain 经营归因分析系统

单 Agent 多轮对话的经营归因分析平台：业务用户围绕一个经营问题，通过自然语言对话完成「查数 → 归因 → 追问 → 六段结构化报告」的完整分析闭环，全过程证据可追溯、结论可导出。

> 当前阶段：**设计文档基线已完成，代码尚未开始**。实现以 `docs/` 为唯一依据。

## 文档索引

| 文档 | 用途 |
| --- | --- |
| [PRD-经营归因分析系统](docs/PRD-经营归因分析系统.md) | 需求基线 v1.1 |
| [SPEC-功能规格说明](docs/SPEC-功能规格说明.md) | ~60 个功能点清单（P0/P1）+ 模块实现设计 |
| [API-接口设计文档](docs/API-接口设计文档.md) | 前后端接口唯一契约源 |
| [DATA-数据设计文档](docs/DATA-数据设计文档.md) | 表结构 DDL、DTO、WS 消息、配置项 |
| [IMPL-实现蓝图-Python方法级](docs/IMPL-实现蓝图-Python方法级.md) | 方法级伪代码核对底稿 |

## 规划技术栈

- **backend**：Python 3.12 · FastAPI · LangGraph · SQLAlchemy(async) · MySQL + DuckDB · uv 包管理
- **auth-server**：FastAPI 独立进程，OAuth2 授权码
- **frontend**：Vue3 · Vite · Pinia
- **部署**：docker-compose 一键拉起（含 4 场景示例数据）

## License

私有项目，保留所有权利。
