# Oliveira 架构设计

> 状态：v0.2（合并版——工程治理宪章 + 产品脊柱优先的路线图）
> 日期：2026-09-24

## 1. 定位

Oliveira 是面向个人与团队的**证据驱动知识与 Agent 工作平台**：

> 记得知识来龙去脉——每条知识都有出处、有时间、可追溯演变；
> Agent 的结论可核查、动作可审批、过程可回放。

差异化只有一个词：**可信**。普通知识库 RAG 回答"文档里说了什么"，
Oliveira 还能回答"这是什么时候被谁确认的、后来有没有改过、
某个历史时点上系统认为什么"。这是 Utopia 的双时态思想与
Yuxi 的 Agent/记忆实践的结合，但由 Oliveira 自己的领域模型实现。

统一链路：

```
文档与数据 → 证据 → 实体与事实 → Agent 检索与推理
           → 可验证结果 → 人工审核 → 知识沉淀 → 可回放的审计记录
```

## 2. 与参考项目的关系（独立性边界）

Yuxi（MIT）与 Utopia（Apache-2.0）只是设计参考，**不是运行时依赖**：

明确禁止（第一阶段）：

- 运行时调用两者的 API / MCP，或读取其数据库；
- 以 submodule / 源码目录嵌入；
- 复制其内部表结构、Agent Runtime 或前端页面；
- 为"兼容"既有接口而反向设计本项目的领域模型。

允许：理解设计后重新实现（领域概念、状态机思想、证据/审计思想、
MCP 等公开协议的设计方式、交互模式）。

未来若需引入参考项目的源代码，必须先做许可证、版权与派生边界审查。
Oliveira 自身未来对外提供 MCP / API 时，协议由本项目定义与版本化。

## 3. 设计原则（宪法条款）

以下原则贯穿所有里程碑，任何功能实现不得违背：

1. **事实源与投影分离**。PostgreSQL（业务事实、知识、Run、审批、审计）
   与对象存储（原始文件、产物）是事实源；pgvector / 全文索引 / 图投影
   是**可重建的投影**。索引损坏不得导致业务事实丢失。
2. **只追加的账本**。事实不删除只版本化；实体合并不删除、可撤销；
   审计日志只追加。历史回答必须永远可解释。
3. **证据先行**。事实、结论与重要 Agent 输出必须关联证据
   （chunk 定位 + 原文引用 + 快照哈希）。无引用的结果不得标记为证据充分。
4. **模型不直接执行不可逆动作**。所有写入经过命令层：
   提案 → 策略检查 → 证据检查 → 审批 → 命令处理 → 事务。
   （该层在 M2′ 起逐步落地，M0′/M1′ 仅涉及用户自己发起的写入。）
5. **有界上下文**。注入 prompt 的任何内容（记忆、检索结果、历史）
   都有显式上限；超限走压缩/截断，不静默膨胀。
6. **治理分期**。治理设施（状态机、审批、沙箱、Skills）在对应里程碑
   按真实需要长出来，不在地基阶段预建空壳。
7. **不以"页面能打开"为完成标准**。每个里程碑有运行时验收标准；
   未验证的链路必须标记为未验证（见 §12 与 §13）。

## 4. 总体架构

模块化单体，不预先拆微服务：

```
┌────────────────────────────────────────────┐
│        Oliveira Web Console (Vue 3, M3)     │
│   知识库 / 会话 / Run / 证据 / 审核队列        │
└──────────────────┬─────────────────────────┘
                   │ HTTP / SSE
┌──────────────────▼─────────────────────────┐
│              FastAPI Application            │
│  projects / documents / conversations /     │
│  runs / facts / review / audit              │
├────────────────────────────────────────────┤
│                Core Services                │
│   ingest(解析/切块) retrieval(检索)          │
│   extraction(事实抽取, M1′) agent(循环, M2′) │
│   memory(记忆, M3′) llm(模型适配)            │
├────────────────────┬───────────────────────┤
│     PostgreSQL      │     Object Storage    │
│  pgvector + FTS     │  原始文件与产物         │
│  (事实源 + 投影)     │  (M0′ 为本地目录占位)   │
└────────────────────┴───────────────────────┘
```

第一版部署单元：`api`、`worker`、`postgres`、`frontend`。
Redis、独立检索服务、独立图数据库、工作流框架均非必需，
由真实瓶颈证据驱动再引入。

## 5. 技术选型

| 层 | 选择 | 理由 |
|---|---|---|
| 后端 | Python 3.12+ / FastAPI / Pydantic / SQLAlchemy / Alembic(M1′) | LLM 生态迭代最快，一人可维护 |
| 前端 | Vue 3 + TypeScript + Vite（M1 起） | 与交互原型生态一致 |
| 数据库 | PostgreSQL 16 + pgvector + FTS | **单库原则**：向量、全文、图（边表+递归 CTE）、任务队列全在一个库里；Utopia 已验证此路线可行 |
| 文档解析 | pypdf / python-docx / markdown；MinerU 等 M1′ 后按需 | 解析不是护城河，不让部署拖死 MVP |
| LLM | 任意 OpenAI 兼容端点 | 不绑定供应商 |
| Agent 编排 | 自写有界 ReAct 循环（M2′） | 不引入 LangGraph，避免框架绑架；等真实需要再评估 |

## 6. 数据模型

完整 DDL 见 [deploy/postgres/init/001_init.sql](../deploy/postgres/init/001_init.sql)。
SQLAlchemy 模型仅映射当前里程碑用到的表，其余表随里程碑补模型。

### 6.1 知识层

```
documents → document_versions（版本化，不覆盖）
          → document_chunks（原文定位：page / paragraph / content_hash）
entities / entity_types / entity_aliases / entity_merges（可撤销合并）
relations / relation_types
facts → fact_versions（双时态）→ fact_evidence → evidence_refs
fact_conflicts / fact_derivations
```

### 6.2 双时态语义

每条事实版本保存两类时间：

- `valid_from / valid_to`：事实在现实世界中的有效时间；
- `recorded_at / retracted_at`：系统何时记录、何时撤回。

示例：

```
事实：项目负责人是张三
valid: 2025-01-01 ~ 2025-06-30
recorded_at: 2025-07-02   （系统 7 月才知道）
retracted_at: 无
```

由此可回答：现在负责人是谁 / 2025 年 5 月当时是谁 /
系统在 7 月 1 日前知道什么 / 该事实后来是否被修正。

状态机：`pending → asserted | rejected`；`asserted → superseded | retracted`；
`derived` 为规则推导产物（带 `fact_derivations` 推导路径）。
冲突不静默覆盖：写入时检测冲突，落 `fact_conflicts` 并进审核队列。

### 6.3 会话与记忆（三层）

| 层 | 载体 | 写入方式 | 里程碑 |
|---|---|---|---|
| 会话内上下文 | `conversations` / `messages`，超限后旧消息压缩为摘要 + 原文归档 | 自动 | M3′ |
| 用户显式记忆 | `user_memories`（对齐 Yuxi 的 MEMORY.md 思想：用户可见可改，仅显式"记住"触发写入） | 用户指令 | M3′ |
| 事实级长期记忆 | `facts`（机器从文档自动抽取，带证据与置信度） | 抽取管道 + 审核 | M1′ |

第三层是 Oliveira 相对两个参考项目的独有组合：
Yuxi 的用户记忆是手动画像，Utopia 的图谱是事实账本，这里两者叠加。

## 7. 检索与评估

- 召回：pgvector 向量（余弦）+ PostgreSQL FTS 全文，M1′ 起做融合与 rerank；
  实体/事实作为第二路结构化召回。
- **评估闭环（M1′ 起为硬性要求）**：自建 ≥30 条 QA 集合，
  每次改动切块策略 / 嵌入模型 / 融合权重必须跑评估并记录指标。
  没有评估的检索调优视为盲调，不得合入。
- 切块与嵌入维度是系统级参数（`.env` + DDL 中的 `vector(N)` 联动）。

## 8. Agent Runtime 原则

- M0′：对话入口异步化，Run 由 PostgreSQL 任务队列驱动。
- M2′：有界只读 Agent Runtime（search_chunks / query_facts /
  get_entity_timeline 的领域边界），最多 6 步、60 秒、12k 上下文，
  **对真实行为固化 Run 事件**。
- 工具协议：每个工具声明 `input_schema`、`permission`、`side_effect`
  （none/read/propose/write/external）。第一阶段只开放 none/read。
- 提案与执行分离：模型只能产出 `answer` 或 `proposal`；
  `write` 级动作必须经审批（M3′ 起实现审批面板）。
- Agent 不允许：任意 Shell、Docker Socket、跨项目读文件、
  绕过命令层写库、修改自己的权限或审计记录。

## 9. 权限与安全边界

权限不依赖前端隐藏按钮或 prompt 约束，后端在工具执行时检查
（用户 / 项目 / 工具权限 / 资源可见性 / 副作用等级）。
M0′–M3′ 使用轻量账号、工作空间成员角色与 Provider 隔离；
企业 SSO/OIDC、多租户治理列入 M4+。

## 10. 仓库结构

```
Oliveira/
├── backend/
│   ├── app/
│   │   ├── api/routes/    # HTTP 层
│   │   ├── core/          # 配置、数据库
│   │   ├── models/        # SQLAlchemy（随里程碑扩展）
│   │   ├── schemas/       # Pydantic 出入参
│   │   └── services/      # ingest / retrieval / llm / (extraction, agent, memory)
│   ├── tests/
│   └── pyproject.toml
├── deploy/postgres/init/  # 首启 DDL（Alembic 自 M1′ 接管演进）
├── docs/                  # architecture.md + adr/
├── frontend/              # Vue 3 + TypeScript + Element Plus 工作台
├── docker-compose.yml
└── .env.example
```

模块间通过 service 层函数通信；跨模块不直接 UPDATE 他模块的表。
单体阶段不做更重的隔离仪式，微服务化留给真实扩展需求。

## 11. 对象存储

M0′ 用本地目录（`backend/data/`，`object_key` 记相对路径），
接口按 S3 语义设计（put/get by key），M4+ 替换为 MinIO/S3 时
只换 adapter，不动领域层。

## 12. 里程碑（产品脊柱优先）

> 排序原则：先让产品立住（检索 + 事实），治理设施在对的位置分期生长。
> 与"治理先行"的替代排序相比，本顺序保证每个里程碑结束时
> 都有可演示、可验证的产品价值。

### M0′ 能用的 RAG（当前）

交付：compose 一键启动；项目/文档/会话/Run API；
上传解析切块入库（带原文定位）；向量检索（未配嵌入模型时关键词降级）；
带引用的对话；LLM 未配置时明确 503。
验收：上传 10 份文档提问，答案引用可回链到 chunk 与原文页码。

### M1′ 灵魂：事实与评估

交付：§6 全量事实模型落库 + SQLAlchemy 模型；
**自动抽取管道**（文档 → LLM 抽取候选事实，带置信度与证据，
低置信度进 pending）；冲突检测（同主体同谓词新值）；
检索评估闭环（≥30 条 QA，指标入库存档）；
简单时间线视图（按主体列出事实版本演变）。
验收：新旧事实冲突不静默覆盖、进审核队列；
改动检索参数必须附评估报告；每个事实可回链证据。

### M2′ Agent 循环与状态机

交付：有界 ReAct 循环；工具注册表（search_chunks / query_facts /
get_entity_timeline）；Run 状态机 + run_events（对真实行为固化）；
超时 / 重试 / 预算 / 取消；认证。
验收：Worker（或进程）重启后 Run 不丢；重复请求无重复副作用；
失败有明确原因码；§13 失败路径用例通过。

### M3′ 记忆、审核与审计

交付：多轮会话上下文压缩（摘要 + 原文归档，参考 Yuxi 思想原创实现）；
user_memories 显式记忆 + 注入上限；审核队列 UI（冲突/低置信度事实）；
审批面板（write 级提案）；审计账本查询。
验收：会话超限自动压缩且原文可回读；审批前写动作不可达；
审计完整记录谁在何时对什么做了什么。

### M4+ 扩展（按需）

沙箱工作区 / Skills 声明式目录 / Oliveira 自己的 MCP Server /
外部副作用（outbox + 幂等提交）/ 多租户 / OIDC / 分布式 worker /
图投影与递归查询优化 / MinerU 深度解析。

## 13. 验收纪律

每个里程碑除功能验收外，失败路径必须验证：
模型不可用、嵌入超时、解析失败、检索为空、
（M2′ 起）worker 崩溃恢复、重复请求、权限不足、审批超时。

静态与单元验证：类型/lint 通过；迁移可重复执行；
状态迁移与幂等键单测；事实时间查询单测。

未验证的链路在 README 状态区显式标记，不以静态构建成功替代运行时证据。

## 14. 第一版明确不做

不接 Yuxi / Utopia 运行时；不做 API Gateway；不复制两者前端；
不引入第二个向量库或图数据库；不做无限递归多 Agent；
不开 Agent 任意 Shell；不允许模型直接改生产数据；
不以"模型说完成"为完成条件；不以日志代替业务审计；
不把索引当事实源。

## 15. 参考资料

- Yuxi（语析）：<https://github.com/xerrors/Yuxi> —— Agent Run / 记忆分层 / 上下文压缩
- Utopia：<https://github.com/deeplethe/utopia> —— 双时态 / 证据 / 冲突 / 审计账本

思想来源已在各章节标注；实现均为本项目原创。
