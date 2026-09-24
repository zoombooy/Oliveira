# Oliveira

> 面向个人与团队的证据驱动知识与 Agent 工作平台。
> 每条知识都有出处、有时间、可追溯演变；Agent 的结论可核查、动作可审计。

Oliveira 是一个完全独立的产品，不是 Yuxi / Utopia 的集成网关。两个项目只作为设计思想的参考
（Yuxi：Agent Run、记忆、上下文压缩；Utopia：双时态事实、证据溯源、审计账本），
领域模型、数据库、运行时、接口与前端均为原创实现。独立性边界见
[docs/architecture.md](docs/architecture.md)。

## 产品闭环（正在实现）

```
文档上传 → 版本化 → 解析切块 → 检索(向量+全文) → Agent 带引用回答
       → 事实抽取(pending) → 人工审核 → 事实版本(双时态) → 按时间回放
```

## 当前状态

里程碑定义见 [docs/architecture.md](docs/architecture.md) 第 12 节。

- [x] M0′ 仓库与架构基线：README / 架构文档 / DDL / docker-compose / FastAPI 骨架
- [ ] M0′ 文档上传→解析→切块→入库；最简对话（带引用，LLM 可配置）
- [ ] M1′ 事实模型落地 + 自动抽取管道 + 检索评估闭环（30 条自建 QA）
- [ ] M2′ Agent 循环（有界 ReAct）+ 工具注册 + 状态机（对真实行为固化）
- [ ] M3′ 会话与记忆层（多轮 + 压缩 + MEMORY.md）+ 审核队列 + 冲突检测 + 审计
- [ ] M4+ 沙箱 / Skills / MCP Server / 外部副作用

## 快速开始

依赖：Docker（含 compose）。Python ≥ 3.12 仅本地开发需要。

```bash
cp .env.example .env          # 按需填写 LLM 配置，不填也能启动
docker compose up --build -d

curl http://localhost:8000/healthz
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

未配置 LLM 时，上传与检索正常工作，对话接口返回 503 并给出配置提示。

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

数据库迁移：M0′ 阶段 schema 由 `deploy/postgres/init/001_init.sql` 建立；
M1′ 起接入 Alembic 管理演进。

## 许可证与致谢

[MIT](LICENSE)。设计思想参考并致谢：
[Yuxi（语析）](https://github.com/xerrors/Yuxi)（MIT）、
[Utopia](https://github.com/deeplethe/utopia)（Apache-2.0）。
Oliveira 未复制其二进制、表结构或源码；如未来引入任何参考代码，
将先做许可证与派生边界审查。
