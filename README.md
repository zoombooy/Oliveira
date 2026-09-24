# Oliveira

> 面向个人与团队的证据驱动知识与 Agent 工作平台。
> 每条知识都有出处、有时间、可追溯演变；Agent 的结论可核查、动作可审计。

Oliveira 是一个完全独立的产品，不是 Yuxi / Utopia 的集成网关。两个项目只作为设计思想的参考
（Yuxi：Agent Run、记忆、上下文压缩；Utopia：双时态事实、证据溯源、审计账本），
领域模型、数据库、运行时、接口与前端均为原创实现。独立性边界见
[docs/architecture.md](docs/architecture.md)。

## 产品闭环

```
文档上传 → 版本化 → 解析切块 → 检索(向量+全文) → Agent 带引用回答
       → 事实抽取(pending) → 人工审核 → 事实版本(双时态) → 按时间回放
```

## 当前状态（代码已实现，Docker 运行链路待在具备 Docker 的环境验证）

里程碑定义见 [docs/architecture.md](docs/architecture.md) 第 12 节。

- [x] M0′ 文档版本、原文持久化、解析切块、分批 Embedding、混合检索
- [x] M1′ 账号、工作空间、Provider 加密配置、事实抽取、pending 审核、双时态查询、冲突记录
- [x] M2′ PostgreSQL 任务队列、Worker、有界只读 Agent、Run 事件、引用校验、取消/恢复 API
- [x] M3′ 会话摘要任务、结构化用户记忆、事实时间线、Vue 工作台与证据抽屉
- [ ] 检索评估闭环（30 条 QA 数据集及指标持久化）
- [ ] M4+ 沙箱 / Skills / MCP Server / 外部副作用

## 快速开始

依赖：Docker（含 compose）。Python ≥ 3.12 仅本地开发需要。

```bash
cp .env.example .env          # 按需填写 LLM 配置，不填也能启动
docker compose up --build -d

curl http://localhost:8000/healthz
# Web 工作台：http://localhost:5173
```

上传文档并对话：

```bash
# 建项目（demo 用户由数据库初始化脚本创建）
curl -X POST http://localhost:8000/api/v1/projects \
  -H 'Content-Type: application/json' -d '{"name": "demo"}'

# 上传文档（支持 pdf / docx / md / txt）
curl -X POST http://localhost:8000/api/v1/projects/<project_id>/documents \
  -F file=@/path/to/doc.pdf

# 建会话并提问
curl -X POST http://localhost:8000/api/v1/projects/<project_id>/conversations
curl -X POST http://localhost:8000/api/v1/conversations/<conversation_id>/messages \
  -H 'Content-Type: application/json' -d '{"content": "这份文档说了什么？"}'
```

未配置 LLM 时，上传与关键词检索仍可工作；对话 Run 会进入 failed，
并在 Run 事件中记录 Provider 未配置，而不是返回伪造答案。

登录页面采用 Oliveira 自己实现的克制、居中登录场景；进入后是侧栏式知识工作台，
包含项目、对话、知识库、任务/Run、事实审核和证据详情。交互结构参考了用户熟悉的产品，
但没有引用 Yuxi 或 Utopia 的运行时代码、页面源码、数据库或接口。

## 配置

环境变量（见 `.env.example`）：

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | PostgreSQL 连接串（容器内自动注入） |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | 任意 OpenAI 兼容端点 |
| `EMBEDDING_MODEL` | 嵌入模型；**维度默认 1024**（bge-m3 / Qwen text-embedding-v3），换其他维度模型需同步修改 `deploy/postgres/init/001_init.sql` 中的 `vector(1024)` 与 `EMBEDDING_DIM` |

## 目录结构

```
Oliveira/
├── backend/              # FastAPI 模块化单体
│   ├── app/
│   │   ├── api/          # HTTP 路由
│   │   ├── core/         # 配置、数据库
│   │   ├── models/       # SQLAlchemy（仅当前里程碑用到的表）
│   │   ├── schemas/      # Pydantic 出入参
│   │   └── services/     # 解析/切块、检索、LLM 适配
│   └── tests/
├── deploy/postgres/init/ # 首次启动的建表 DDL（事实源 schema）
├── docs/                 # architecture.md + ADR
└── docker-compose.yml
```

数据库迁移：全新数据库由 `deploy/postgres/init/001_init.sql` 建立；
`backend/alembic/versions/0001_bootstrap_baseline.py` 作为迁移基线，
后续表结构必须通过 Alembic revision 演进，不能直接修改已运行数据库。

## 许可证与致谢

[MIT](LICENSE)。设计思想参考并致谢：
[Yuxi（语析）](https://github.com/xerrors/Yuxi)（MIT）、
[Utopia](https://github.com/deeplethe/utopia)（Apache-2.0）。
Oliveira 未复制其二进制、表结构或源码；如未来引入任何参考代码，
将先做许可证与派生边界审查。
