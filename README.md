# Oliveira

> 记得知识的来龙去脉。
>
> 一个独立实现的、证据优先的知识库与 Agent 工作平台。Oliveira 不只回答“文档里写了什么”，还记录答案来自哪里、在什么时候被系统知道，以及事实后来如何演变。

[![License](https://img.shields.io/badge/license-MIT-111827.svg)](LICENSE)
[![Backend](https://img.shields.io/badge/backend-FastAPI-009688.svg)](backend/pyproject.toml)
[![Frontend](https://img.shields.io/badge/frontend-Vue%203%20%2B%20TypeScript-42b883.svg)](frontend/package.json)
[![Database](https://img.shields.io/badge/database-PostgreSQL%2016%20%2B%20pgvector-336791.svg)](docker-compose.yml)
[![Status](https://img.shields.io/badge/status-active%20development-f59e0b.svg)](docs/architecture.md)

Oliveira 面向需要长期维护知识、核查答案来源、回放事实变化的个人和小型团队。它把文档、检索、事实、对话、审核和运行记录放在同一个可追溯闭环中。

## 目录

- [为什么做 Oliveira](#为什么做-oliveira)
- [核心能力](#核心能力)
- [当前实现状态](#当前实现状态)
- [架构概览](#架构概览)
- [快速开始](#快速开始)
- [第一次使用](#第一次使用)
- [API 入口](#api-入口)
- [配置说明](#配置说明)
- [测试与验证](#测试与验证)
- [下一版本计划：v0.3](#下一版本计划v03)
- [明确不做的事情](#明确不做的事情)
- [独立性边界](#独立性边界)
- [目录结构](#目录结构)
- [许可证](#许可证)

## 为什么做 Oliveira

普通 RAG 系统通常只解决一个问题：

> “相关文档里有什么内容？”

Oliveira 还要回答：

- 这句话来自哪一份文档、哪个版本、哪个段落或页码？
- 这个事实是什么时候在现实世界中生效的？
- Oliveira 是什么时候记录到这个事实的？
- 新事实与旧事实发生冲突时，系统是否保留了两者？
- 一次 Agent 回答调用了哪些检索工具，最终使用了哪些证据？

因此，Oliveira 的核心产品原则是：

```text
证据优先 · 事实可演变 · 回答可核查 · 运行可回放
```

## 核心能力

### 文档与知识库

- 支持 PDF、DOCX、Markdown 和 TXT 文档上传；
- 文档按版本保存，不覆盖历史文件、历史 chunk 或历史证据；
- 原文以相对 `object_key` 保存在本地对象存储适配器中；
- 文档解析、段落切分、页码/段落定位和内容哈希；
- Embedding 按批次处理，默认每批 64 个 chunk；
- 没有 Embedding 配置时自动降级为关键词检索；
- Embedding 不完整时保留关键词结果，不把没有向量的 chunk 静默排除。

### 混合检索

检索同时使用：

```text
pgvector 向量召回
        +
PostgreSQL 关键词/全文召回
        ↓
按 chunk 去重、归一化、加权排序
```

默认权重为：

```text
vector_weight  = 0.7
keyword_weight = 0.3
```

每条结果都可以回链到文档、文档版本、chunk、页码或段落，并保留向量分数、关键词分数、最终分数和检索方式。

### 事实、证据与双时态

Oliveira 将事实作为独立领域对象，而不是把 LLM 输出直接塞进向量库。

每条事实都可以关联：

```text
subject / predicate / object
valid_from / valid_to       # 业务有效时间
recorded_at / retracted_at  # 系统记录时间
status / confidence
evidence_ref / source chunk
```

事实默认进入 `pending` 状态。低置信度事实进入审核队列；新旧事实冲突时不静默覆盖，而是保留历史版本并生成冲突记录。

### 有界 Agent Runtime

Agent 通过 PostgreSQL 任务队列异步执行，运行过程写入 Run 和 RunEvent：

- `search_chunks`：检索原文证据；
- `query_facts`：查询已审核事实；
- 引用校验：模型不能引用本次 Run 未收集的证据编号；
- 最大运行步数、最大运行时间、上下文预算和工具输出大小均有限制；
- Provider 不可用、模型超时、工具错误和引用校验失败都保留为可查询事件；
- 不开放任意 Shell、Python、SQL 或外部系统写入能力。

### 账号、工作空间与 Provider

- 轻量账号注册和登录；
- 工作空间与项目隔离；
- 工作空间成员角色：`owner`、`admin`、`member`、`viewer`；
- Provider 按工作空间隔离；
- 支持 OpenAI-compatible、Ollama 和 vLLM 地址；
- API Key 使用 `OLIVEIRA_MASTER_KEY` 加密保存，API 响应不返回明文密钥。

### Web 工作台

当前工作台包含登录与注册、工作空间和项目选择、对话与异步 Run 轮询、知识库上传、混合检索、事实审核、双时态时间线、运行记录、结构化用户记忆、Provider 配置和证据详情抽屉。

界面采用 Oliveira 自己的实现，视觉上参考了现代知识工作台常见的浅色、紧凑、线性图标交互，不依赖 Yuxi 或 Utopia 的页面源码和运行时。

## 当前实现状态

> 这里区分“代码已经存在”和“已经完成完整生产级验证”。静态构建通过不等于所有真实模型、数据库、Worker 和失败路径都已经验证。

| 能力 | 当前状态 | 说明 |
|---|---|---|
| 账号与工作空间 | 已实现 | 注册、登录、JWT、工作空间成员和项目隔离 |
| 文档版本化 | 已实现 | 旧版本保留，当前版本单独指向 |
| PDF/DOCX/MD/TXT 解析 | 已实现 | 解析、切块、页码/段落定位 |
| 分批 Embedding | 已实现 | 默认批次 64；状态支持 `completed`、`partial`、`unavailable` |
| 混合检索 | 已实现 | pgvector + PostgreSQL 关键词检索 |
| Provider 配置 | 已实现 | OpenAI-compatible/Ollama/vLLM 统一适配 |
| 事实抽取与审核 | 已实现 | 抽取任务、pending 队列、通过/拒绝 |
| 双时态事实查询 | 已实现 | 支持 `valid_at` 和 `recorded_at` 过滤 |
| PostgreSQL 任务队列 | 已实现 | `FOR UPDATE SKIP LOCKED`、租约和重试 |
| 异步对话 Run | 已实现 | 202 接收、轮询、RunEvent、失败记录 |
| 有界 Agent | 已实现基础版本 | 当前以检索证据和已审核事实为核心，通用工具注册表与更完整的多步循环列入 v0.3 |
| 会话摘要 | 已实现基础版本 | 摘要任务和原始消息保留；按预算触发的完整策略列入 v0.3 |
| 结构化用户记忆 | 已实现 | 用户主动保存，删除采用撤回 |
| Web 工作台 | 已实现基础版本 | 核心页面已具备，仍需继续完善加载、空状态、移动端和运行详情 |
| 检索评估数据集 | 已实现基础版 | 已有评估用例、异步评估 Run、用例级结果、Hit@K 和 MRR API；QA 数据集管理和 Web 页面列入后续迭代 |
| 生产级异步文档管道 | 已实现基础版 | 上传后进入 `document_ingest → document_embed` Worker 管道，支持批处理、幂等键、重试和 `partial/failed/unavailable` 状态 |
| 外部写入、Skills、MCP 市场、沙箱 | 明确未做 | 不属于 M0-M3 产品版范围 |

### v0.3 当前进度

本分支已经开始落地 v0.3 P0：

- [x] 检索评估基础模型、异步评估任务、Hit@K/MRR 指标和结果 API；
- [x] 任务 `dedupe_key`，避免评估和文档阶段任务重复入队；
- [x] 文档上传后的真实 `document_ingest → document_embed` Worker 管道；
- [x] 本地对象存储 adapter，领域层只保存相对 `object_key`；
- [x] `search_chunks`、`query_facts`、`get_entity_timeline` 只读 Agent Tool Registry；
- [x] 工具参数 schema 校验、工具名称校验和工具耗时 RunEvent；
- [x] Yuxi 风格的模型供应商维护页：供应商卡片、搜索、默认供应商、连接测试和项目级绑定；
- [x] Ollama、vLLM、本地 OpenAI-compatible 网关快速接入模板，支持容器通过 `host.docker.internal` 访问宿主机模型；
- [ ] 30 条以上真实 QA 数据集和评估基线；
- [ ] 评估数据集和 Run 的 Web 管理页面；
- [ ] 前端文档处理进度轮询与失败阶段展示；
- [ ] 模型驱动的多步 ToolCall 循环和更完整的 Run 恢复测试。

## 架构概览

Oliveira 当前采用模块化单体和单 PostgreSQL 原则：

```text
┌──────────────────────────────────────────────┐
│ Vue 3 + TypeScript Web 工作台                 │
│ 对话 / 知识库 / 检索 / 审核 / 时间线 / Run     │
└──────────────────────┬───────────────────────┘
                       │ HTTP
┌──────────────────────▼───────────────────────┐
│ FastAPI Application                           │
│ auth / workspace / documents / search         │
│ facts / conversations / runs / memories       │
└───────────────┬──────────────────┬────────────┘
                │                  │
       ┌────────▼────────┐ ┌───────▼────────┐
       │ PostgreSQL 16   │ │ Local Storage  │
       │ pgvector + FTS  │ │ backend/data/  │
       │ 事实源/任务/审计 │ │ 原始文件       │
       └────────┬────────┘ └────────────────┘
                │
       ┌────────▼────────┐
       │ PostgreSQL Worker│
       │ SKIP LOCKED      │
       └─────────────────┘
```

核心设计原则：

1. PostgreSQL 是知识、事实、权限、任务、Run 和审计记录的事实源；
2. 向量索引、全文索引和未来的图投影都必须可重建；
3. 事实只版本化，不用新事实覆盖旧事实；
4. Agent 只能通过受限工具访问知识，不直接执行任意代码；
5. 所有未完成的能力必须明确标注，不用静态页面假装运行时完成。

详细架构与 ADR 见：

- [架构设计](docs/architecture.md)
- [ADR 0001：模块化单体与单 PostgreSQL](docs/adr/0001-modular-monolith-single-postgres.md)
- [ADR 0002：产品脊柱优先的里程碑](docs/adr/0002-product-spine-first-milestones.md)

## 快速开始

### 环境要求

- Docker Engine 24+；
- Docker Compose v2；
- 本地开发后端需要 Python 3.12+；
- 本地开发前端需要 Node.js 22+；
- 如果启用对话或 Embedding，需要一个 OpenAI-compatible 模型服务，或者 Ollama/vLLM。

### 1. 获取代码并创建配置

```bash
git clone https://github.com/zoombooy/Oliveira.git
cd Oliveira
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

至少建议修改：

```dotenv
JWT_SECRET=replace-with-a-long-random-secret
OLIVEIRA_MASTER_KEY=replace-with-a-long-random-secret
```

### 2. 启动开发环境

```bash
docker compose up --build -d
```

默认端口：

| 服务 | 地址 |
|---|---|
| Web 工作台 | <http://localhost:5173> |
| API 文档 | <http://localhost:8000/docs> |
| API 健康检查 | <http://localhost:8000/healthz> |
| PostgreSQL | `localhost:5432` |

检查容器：

```bash
docker compose ps
curl http://localhost:8000/healthz
```

预期健康响应：

```json
{"status":"ok"}
```

### 3. 停止环境

```bash
docker compose down
```

默认不会删除 PostgreSQL 数据卷。如果需要重新执行首次初始化 DDL，应先确认数据可以销毁，再执行：

```bash
docker compose down -v
```

## 第一次使用

1. 打开 Web 工作台并注册账号；
2. 进入自动创建的工作空间；
3. 在“设置”中创建项目；
4. 在 Provider 配置中填写模型地址、聊天模型和可选的 Embedding 模型；
5. 进入“知识库”上传 PDF、DOCX、Markdown 或 TXT；
6. 等待文档状态更新后进入“检索”验证结果和来源定位；
7. 新建对话，提问并通过 Run 状态查看执行结果；
8. 如果启用事实抽取，在事实审核页处理 `pending` 事实；
9. 在时间线中查看事实的业务有效时间和系统记录时间。

没有配置 LLM 时：

- 文档解析和关键词检索仍然可以使用；
- 无法生成 Embedding 时，向量检索会降级；
- 对话 Run 会以 Provider 未配置或不可用失败，并保留失败事件；
- 系统不会返回伪造的模型答案。

## API 入口

API 根路径为 `/api/v1`，登录后使用 `Authorization: Bearer <access_token>`。

| 领域 | 主要入口 |
|---|---|
| 认证 | `POST /auth/register`、`POST /auth/login`、`GET /auth/me` |
| 工作空间 | `GET /workspaces`、`POST /workspaces`、`POST /workspaces/{id}/members` |
| Provider | `GET/POST /workspaces/{id}/providers`、`POST /providers/{id}/test` |
| 项目 | `GET /projects`、`POST /projects` |
| 文档 | `POST /projects/{id}/documents`、`POST /documents/{id}/versions`、`GET /documents/{id}/versions` |
| 检索 | `POST /projects/{id}/search` |
| 对话 | `POST /projects/{id}/conversations`、`POST /conversations/{id}/messages` |
| Run | `GET /runs/{id}`、`GET /runs/{id}/events`、`POST /runs/{id}/cancel`、`POST /runs/{id}/resume` |
| 事实 | `POST /projects/{id}/facts/extract`、`GET /projects/{id}/facts` |
| 审核 | `GET /projects/{id}/review-items`、`POST /review-items/{id}/approve` |
| 记忆 | `GET/POST /users/me/memories`、`PATCH/DELETE /users/me/memories/{id}` |

### 最小 API 示例

注册并保存返回的 `access_token`：

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo@example.com","password":"change-me-123","display_name":"Demo"}'
```

创建项目：

```bash
curl -X POST http://localhost:8000/api/v1/projects \
  -H "Authorization: Bearer $OLIVEIRA_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"产品资料"}'
```

上传文档：

```bash
curl -X POST http://localhost:8000/api/v1/projects/<project_id>/documents \
  -H "Authorization: Bearer $OLIVEIRA_TOKEN" \
  -F 'file=@./docs/example.md'
```

执行混合检索：

```bash
curl -X POST http://localhost:8000/api/v1/projects/<project_id>/search \
  -H "Authorization: Bearer $OLIVEIRA_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"query":"项目负责人是谁？","top_k":8}'
```

提交对话消息后，接口返回 `202 Accepted` 和 `run_id`，前端通过 Run 接口轮询，而不是同步等待模型完成：

```bash
curl -X POST http://localhost:8000/api/v1/conversations/<conversation_id>/messages \
  -H "Authorization: Bearer $OLIVEIRA_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"content":"这份资料的主要结论是什么？"}'
```

## 配置说明

所有配置见 [.env.example](.env.example)。常用配置如下：

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `DATABASE_URL` | Compose 注入 | PostgreSQL Async SQLAlchemy 连接串 |
| `LLM_BASE_URL` | 空 | OpenAI-compatible API 地址 |
| `LLM_API_KEY` | 空 | 模型服务密钥；本地模型可以为空 |
| `LLM_MODEL` | 空 | 聊天模型名称 |
| `EMBEDDING_MODEL` | 空 | Embedding 模型名称 |
| `EMBEDDING_DIM` | `1024` | 向量维度，必须和数据库 `vector(N)` 一致 |
| `EMBEDDING_BATCH_SIZE` | `64` | 每批 Embedding 的 chunk 数 |
| `CHUNK_SIZE` | `500` | chunk 目标大小 |
| `CHUNK_OVERLAP` | `50` | chunk overlap 大小 |
| `RETRIEVAL_TOP_K` | `8` | 默认检索结果数 |
| `VECTOR_WEIGHT` | `0.7` | 向量检索权重 |
| `KEYWORD_WEIGHT` | `0.3` | 关键词检索权重 |
| `JWT_SECRET` | 开发默认值 | 生产环境必须替换为随机长密钥 |
| `OLIVEIRA_MASTER_KEY` | 空/开发默认值 | Provider API Key 加密主密钥，生产环境必须设置 |
| `DATA_DIR` | `/app/data` | 原文和本地对象存储目录 |
| `WORKER_ID` | `local-worker` | Worker 实例标识 |
| `TASK_POLL_INTERVAL` | `1.0` | Worker 轮询间隔，单位秒 |

### 向量维度注意事项

当前数据库初始化脚本使用 `vector(1024)`。如果换用其他维度的 Embedding 模型，需要同时修改：

1. `.env` 中的 `EMBEDDING_DIM`；
2. `deploy/postgres/init/001_init.sql` 中的 `vector(1024)`；
3. 对应数据库的向量列或重新初始化数据库。

不能只修改环境变量，否则会出现模型输出维度与数据库列不匹配的问题。

### 数据库初始化与迁移

- 全新 PostgreSQL 数据库由 `deploy/postgres/init/001_init.sql` 初始化；
- `backend/alembic/versions/0001_bootstrap_baseline.py` 将初始化 SQL 标记为 Alembic 基线；
- 后续结构变更必须新增 Alembic revision；
- 不要直接修改已经运行数据库中的表结构；
- 初始化脚本只会在 PostgreSQL 数据卷第一次创建时执行。

## 测试与验证

### 后端单元测试

```bash
cd backend
pip install -e '.[dev]'
pytest
ruff check app tests
```

当前测试覆盖密码哈希、Provider 密钥加密、文档解析/切块、事实抽取结构校验和部分安全边界。需要真实 PostgreSQL、pgvector、模型服务的集成验证仍在补齐。

### 前端构建

```bash
cd frontend
npm install
npm run build
```

`npm run build` 包含 TypeScript 检查和 Vite 生产构建。Vite 的 bundle 体积提示不会被当作功能通过证据，后续会在 v0.3 做代码分包和按页面加载。

### Docker 验证

```bash
docker compose up --build -d
docker compose ps
curl http://localhost:8000/healthz
```

服务器使用 Nginx 静态前端覆盖配置时，先生成 `frontend/dist`，再执行构建；`dist` 是构建产物，不提交到 Git：

```bash
cd frontend
npm install
npm run build
cd ..
docker compose -f docker-compose.yml -f docker-compose.server.yml build api worker frontend
docker compose -f docker-compose.yml -f docker-compose.server.yml run --rm api alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.server.yml up -d api worker frontend
```

正式验收至少应覆盖：

- 注册用户 → 创建工作空间 → 创建项目；
- 上传文档 → 生成版本 → 解析切块 → 查询文档；
- 关键词检索和向量检索降级；
- 创建对话 → 获取 `202` → 查询 Run 和 RunEvent；
- Provider 不可用时 Run 明确失败；
- 不同工作空间之间不能互相读取资源；
- Worker 重启后任务能够重新领取；
- 原文和旧文档版本在容器重启后仍可读取。

## 下一版本计划：v0.3

### 版本主题

```text
从“功能闭环”进入“质量可证明、运行可观察、任务可恢复”
```

v0.3 不扩张到 Skills、MCP 市场或外部系统写入，而是优先把当前 M0-M3 的核心链路做实，尤其是检索质量、异步任务和 Agent 运行时。

### P0：必须完成

#### 1. 检索评估闭环

- 建立至少 30 条带标准答案和标准来源的 QA 数据集；
- 支持按项目/版本固定评估语料；
- 记录 `recall@k`、`hit@k`、MRR 或 nDCG 等指标；
- 对切块大小、overlap、Embedding 模型、向量/关键词权重提供可比较的评估报告；
- 每次改变检索核心参数时，必须能重新运行评估并保存结果；
- 在 Web 页面展示“当前配置 vs 上次基线”的差异。

验收标准：

```text
修改切块或检索权重 → 运行评估 → 指标落库 → 可查看差异 → 才允许作为新基线
```

#### 2. 把文档处理真正移入 Worker

- 将当前上传流程中的解析、切块和 Embedding 拆成可恢复任务；
- `document_ingest` 和 `document_embed` 不再返回 accepted 占位结果；
- 文档页面显示解析进度、Embedding 进度和失败阶段；
- 同一个 document version 使用幂等键，Worker 重试不会重复写入 chunk；
- 失败后支持从最近一个成功阶段继续，而不是重新处理整个文件；
- 为模型超时、解析失败、维度不匹配和数据库错误使用不同错误码。

#### 3. 完成真正的 Agent Tool Registry

- 将 `search_chunks`、`query_facts`、`get_entity_timeline` 统一注册为只读工具；
- 每个工具声明名称、描述、输入 schema、输出 schema、权限和副作用等级；
- 允许 Agent 在 6 步预算内根据模型结果决定是否继续调用工具；
- 每个工具调用保存 arguments、result 摘要、证据引用和耗时；
- 工具参数使用 Pydantic 校验，未知工具和越权 project_id 必须拒绝；
- 没有证据时不得自动补造引用。

验收标准：

- Agent 最多执行 6 步；
- Agent 总运行时间不超过 60 秒；
- 工具错误可以在 RunEvent 中定位；
- Worker 重启后 Run 状态不会卡在 `running`；
- 引用只允许来自本次 Run 实际收集的证据。

### P1：应该完成

#### 4. 文档版本与证据体验

- Web 页面增加文档版本列表和版本对比；
- 证据抽屉显示文件名、版本号、页码、段落、内容哈希和检索分数；
- 支持从事实审核直接打开原文证据；
- 允许按指定 `version_id` 执行检索；
- 对“当前版本”和“历史版本”使用明确视觉标记。

#### 5. 事实冲突与实体候选

- 展示同一 subject + predicate 的冲突事实；
- 展示有效时间重叠但 object 不同的冲突；
- 实体归一只产生候选，不自动合并；
- 增加人工确认、撤销和审计记录；
- 时间线支持按实体筛选，并显示事实版本之间的演变关系。

#### 6. 会话压缩与运行详情

- 按模型 token 预算的 80% 触发摘要，而不是只按消息数量触发；
- 摘要保留关键事实、用户约束、Run ID 和证据引用；
- 原始消息永久保留，摘要只是可重建投影；
- Web 增加 Run 详情页和事件时间线；
- 支持取消、恢复、重试，并明确区分模型失败、工具失败和引用验证失败。

#### 7. Provider 和安全体验

- Web 增加 Provider 连接测试；（已完成基础版本）
- 对聊天模型和 Embedding 模型能力分别检查；
- API Key 只显示掩码；
- 日志、异常堆栈和 RunEvent 不得泄露明文密钥；
- 为跨 workspace 访问、资源越权、无权限审核和无权限 Provider 操作增加集成测试。

本版本的模型接入入口位于“设置 → 模型供应商”。常见配置如下：

| 场景 | Provider 类型 | Base URL 示例 | API Key |
| --- | --- | --- | --- |
| Docker 中的 Oliveira 连接宿主机 Ollama | `ollama` | `http://host.docker.internal:11434/v1` | 可留空 |
| Docker 中的 Oliveira 连接宿主机 vLLM | `vllm` | `http://host.docker.internal:8000/v1` | 按服务配置 |
| 自建 OpenAI-compatible 网关 | `openai_compatible` | `http://host.docker.internal:<port>/v1` 或内网地址 | 按服务配置 |

聊天模型名称必须与对应服务实际暴露的模型 ID 一致。Embedding 模型是可选项；没有 Embedding 服务时，Oliveira 仍保留关键词检索能力，并在后端按可用索引状态降级。

### P2：可以完成

- 完整的 PostgreSQL + pgvector 集成测试环境；
- Playwright 浏览器验收；
- 前端页面级代码分包，降低首屏 JavaScript 体积；
- 文档预览和更多格式支持；
- OCR/MinerU 作为可选解析适配器；
- S3/MinIO 对象存储适配器；
- Prometheus/OpenTelemetry 兼容的基础指标；
- 更细粒度的 workspace 配额和审计查询。

### v0.3 版本完成定义

只有满足以下条件，v0.3 才算完成：

1. 30 条以上 QA 评估集可以重复执行并保存指标；
2. 文档解析和 Embedding 由 Worker 可恢复地执行；
3. 一个 Agent Run 能明确展示每个工具调用和证据来源；
4. Worker 重启、模型超时、解析失败和重复任务都有可验证结果；
5. 历史文档版本、事实版本和证据都可以回放；
6. workspace 越权访问集成测试通过；
7. README、架构文档和部署说明与真实代码一致。

## 明确不做的事情

在 v0.3 之前，Oliveira 不做以下事情：

- 不调用 Yuxi 或 Utopia 的 API、MCP、数据库或运行时；
- 不引入 Milvus、Neo4j、Redis、Celery 或第二套事实数据库；
- 不把项目重构成微服务集合；
- 不开放 Agent 任意 Shell、Python、SQL 或 Docker Socket；
- 不允许模型直接写入外部系统或修改生产数据；
- 不做无限递归、多 Agent 自主协作；
- 不把向量索引当作唯一事实源；
- 不为了“看起来完整”预先实现没有真实需求的 Skills、MCP 市场和沙箱。

## 独立性边界

Oliveira 是独立产品。Yuxi 和 Utopia 只作为公开设计思想和交互模式的参考：

- Oliveira 不在运行时依赖它们；
- 不读取它们的数据库；
- 不以 submodule 或源码目录嵌入它们；
- 不复制它们的内部表结构、Agent Runtime 或前端页面；
- Oliveira 的领域模型、数据库、HTTP API、任务队列和前端代码独立演进。

如果未来引入任何参考代码，必须先进行许可证、版权和派生边界审查。完整边界见 [docs/architecture.md](docs/architecture.md)。

## 目录结构

```text
Oliveira/
├── backend/
│   ├── app/
│   │   ├── api/routes/       # FastAPI HTTP 路由
│   │   ├── core/             # 配置、数据库、安全
│   │   ├── models/           # SQLAlchemy 模型
│   │   ├── schemas/          # Pydantic 请求/响应模型
│   │   └── services/         # ingest / retrieval / llm / agent / facts
│   ├── tests/                # 后端单元测试
│   └── pyproject.toml
├── deploy/postgres/init/     # 新数据库首次启动 DDL
├── docs/
│   ├── architecture.md      # 架构宪章和里程碑
│   └── adr/                  # Architecture Decision Records
├── frontend/                 # Vue 3 + TypeScript + Vite 工作台
├── docker-compose.yml        # 本地开发 Compose
├── docker-compose.server.yml # 离线/服务器覆盖配置
├── .env.example
└── LICENSE
```

## 贡献方式

提交代码前请确认：

1. 没有把参考项目变成 Oliveira 的运行时依赖；
2. 新能力有对应的数据模型、权限边界和失败路径；
3. 事实、证据、Run 和审核记录仍然可追溯；
4. 运行时能力和文档状态保持一致；
5. 通过适用的单元测试、类型检查、构建和集成验证。

建议使用独立分支开发，并在提交说明中说明：变更范围、验证命令、尚未验证的边界和回滚方式。

## 许可证

Oliveira 使用 [MIT License](LICENSE)。

设计思想参考并致谢：

- [Yuxi（语析）](https://github.com/xerrors/Yuxi)：Agent Run、记忆分层和上下文压缩等公开设计思想；
- [Utopia](https://github.com/deeplethe/utopia)：双时态、证据溯源、冲突与审计等公开设计思想。

Oliveira 的运行时、数据库、接口和前端实现独立维护。
