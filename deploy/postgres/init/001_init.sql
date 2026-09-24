-- Oliveira 事实源 schema（首启建表；M1′ 起由 Alembic 接管演进）
-- 约定：主键 uuid；时间戳一律 timestamptz；事实源表只增不改语义（见 docs/architecture.md §3）
-- 嵌入维度默认 1024（bge-m3 / Qwen text-embedding-v3）。
-- 更换维度模型时：修改本文件中全部 vector(1024) 并重建数据库，同时同步 EMBEDDING_DIM。

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- platform
-- ============================================================

CREATE TABLE users (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    username     text NOT NULL UNIQUE,
    display_name text NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE projects (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    description text NOT NULL DEFAULT '',
    owner_id    uuid NOT NULL REFERENCES users(id),
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- knowledge: documents（版本化，不覆盖）
-- ============================================================

CREATE TABLE documents (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id         uuid NOT NULL REFERENCES projects(id),
    title              text NOT NULL,
    source_type        text NOT NULL DEFAULT 'upload',   -- upload | import
    current_version_id uuid,                             -- FK 在 document_versions 之后添加
    created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE document_versions (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id    uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_no     integer NOT NULL,
    file_name      text NOT NULL,
    mime_type      text NOT NULL DEFAULT '',
    size_bytes     bigint NOT NULL DEFAULT 0,
    content_hash   text NOT NULL,                        -- 解析后正文的 sha256
    parse_status   text NOT NULL DEFAULT 'pending',      -- pending | parsed | failed
    parse_error    text,
    object_key     text NOT NULL,                        -- 对象存储键（M0′ 为本地相对路径）
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, version_no)
);

ALTER TABLE documents
    ADD CONSTRAINT fk_documents_current_version
    FOREIGN KEY (current_version_id) REFERENCES document_versions(id);

-- 原文定位（page / paragraph / content_hash）是证据链的锚点，任何情况下不得丢弃
CREATE TABLE document_chunks (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    chunk_index         integer NOT NULL,
    page_number         integer,
    paragraph_index     integer,
    content             text NOT NULL,
    content_hash        text NOT NULL,
    token_count         integer NOT NULL DEFAULT 0,
    embedding           vector(1024),                    -- 可重建投影，允许为 NULL
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_version_id, chunk_index)
);

CREATE INDEX idx_chunks_embedding
    ON document_chunks USING hnsw (embedding vector_cosine_ops);

-- ============================================================
-- evidence（证据锚点）
-- ============================================================

CREATE TABLE evidence_refs (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          uuid NOT NULL REFERENCES projects(id),
    document_id         uuid REFERENCES documents(id),
    document_version_id uuid REFERENCES document_versions(id),
    chunk_id            uuid REFERENCES document_chunks(id),
    quote               text NOT NULL DEFAULT '',
    location            jsonb NOT NULL DEFAULT '{}'::jsonb,
    observed_at         timestamptz,
    snapshot_hash       text NOT NULL DEFAULT '',
    metadata            jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_evidence_project ON evidence_refs (project_id);

-- ============================================================
-- knowledge: entities（合并可撤销，不物理删除）
-- ============================================================

CREATE TABLE entity_types (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    key        text NOT NULL,
    name       text NOT NULL,
    UNIQUE (project_id, key)
);

CREATE TABLE entities (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      uuid NOT NULL REFERENCES projects(id),
    type_id         uuid REFERENCES entity_types(id),
    name            text NOT NULL,
    normalized_name text NOT NULL,
    embedding       vector(1024),
    status          text NOT NULL DEFAULT 'active',      -- active | merged
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_entities_project_name ON entities (project_id, normalized_name);

CREATE TABLE entity_aliases (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id  uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    alias      text NOT NULL,
    source     text NOT NULL DEFAULT 'system',           -- system | user | extraction
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (entity_id, alias)
);

CREATE TABLE entity_merges (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_entity_id  uuid NOT NULL REFERENCES entities(id),
    target_entity_id  uuid NOT NULL REFERENCES entities(id),
    reason            text NOT NULL DEFAULT '',
    evidence_ref_id   uuid REFERENCES evidence_refs(id),
    actor             text NOT NULL DEFAULT 'system',    -- user:<id> | agent:<run> | system
    reversible        boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now(),
    reverted_at       timestamptz
);

-- ============================================================
-- knowledge: relations
-- ============================================================

CREATE TABLE relation_types (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    key        text NOT NULL,
    name       text NOT NULL,
    UNIQUE (project_id, key)
);

CREATE TABLE relations (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id        uuid NOT NULL REFERENCES projects(id),
    subject_entity_id uuid NOT NULL REFERENCES entities(id),
    object_entity_id  uuid NOT NULL REFERENCES entities(id),
    relation_type_id  uuid NOT NULL REFERENCES relation_types(id),
    evidence_ref_id   uuid REFERENCES evidence_refs(id),
    status            text NOT NULL DEFAULT 'active',    -- active | retracted
    recorded_at       timestamptz NOT NULL DEFAULT now(),
    retracted_at      timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- knowledge: facts（双时态；只版本化，不覆盖）
-- ============================================================

CREATE TABLE facts (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id         uuid NOT NULL REFERENCES projects(id),
    subject_entity_id  uuid REFERENCES entities(id),     -- 实体未归一时允许仅文本
    subject_text       text NOT NULL DEFAULT '',
    predicate          text NOT NULL,
    object_entity_id   uuid REFERENCES entities(id),
    object_text        text NOT NULL DEFAULT '',
    current_version_id uuid,                             -- FK 在 fact_versions 之后添加
    status             text NOT NULL DEFAULT 'pending',
    -- pending | asserted | derived | rejected | retracted | superseded
    confidence         numeric(4, 3),
    created_by         text NOT NULL DEFAULT 'system',   -- user:<id> | agent:<run> | system
    created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_facts_project_status ON facts (project_id, status);
CREATE INDEX idx_facts_subject ON facts (subject_entity_id);

CREATE TABLE fact_versions (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    fact_id           uuid NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    version_no        integer NOT NULL,
    subject_entity_id uuid REFERENCES entities(id),
    subject_text      text NOT NULL DEFAULT '',
    predicate         text NOT NULL,
    object_entity_id  uuid REFERENCES entities(id),
    object_text       text NOT NULL DEFAULT '',
    -- 双时态：业务有效时间 + 系统记录时间
    valid_from        timestamptz,
    valid_to          timestamptz,
    recorded_at       timestamptz NOT NULL DEFAULT now(),
    retracted_at      timestamptz,
    evidence_ref_id   uuid REFERENCES evidence_refs(id),
    change_reason     text NOT NULL DEFAULT '',
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (fact_id, version_no)
);

ALTER TABLE facts
    ADD CONSTRAINT fk_facts_current_version
    FOREIGN KEY (current_version_id) REFERENCES fact_versions(id);

CREATE TABLE fact_evidence (
    fact_version_id uuid NOT NULL REFERENCES fact_versions(id) ON DELETE CASCADE,
    evidence_ref_id uuid NOT NULL REFERENCES evidence_refs(id),
    PRIMARY KEY (fact_version_id, evidence_ref_id)
);

CREATE TABLE fact_conflicts (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          uuid NOT NULL REFERENCES projects(id),
    fact_id             uuid NOT NULL REFERENCES facts(id),
    conflicting_fact_id uuid NOT NULL REFERENCES facts(id),
    conflict_type       text NOT NULL DEFAULT 'contradiction', -- contradiction | stale | axiom_violation
    status              text NOT NULL DEFAULT 'open',          -- open | resolved | ignored
    resolution          text NOT NULL DEFAULT '',
    created_at          timestamptz NOT NULL DEFAULT now(),
    resolved_at         timestamptz,
    resolved_by         text
);

CREATE TABLE fact_derivations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    fact_version_id uuid NOT NULL REFERENCES fact_versions(id) ON DELETE CASCADE,
    run_id          uuid,
    derivation      text NOT NULL DEFAULT '',              -- 规则/推导说明
    inputs          jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- conversations（多轮对话）
-- ============================================================

CREATE TABLE conversations (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES projects(id),
    user_id     uuid REFERENCES users(id),
    title       text NOT NULL DEFAULT '新对话',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE messages (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            text NOT NULL,                        -- user | assistant | system
    content         text NOT NULL,
    token_count     integer NOT NULL DEFAULT 0,
    run_id          uuid,                                 -- assistant 消息关联的 Run
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_messages_conversation ON messages (conversation_id, created_at);

-- 用户显式记忆（Yuxi MEMORY.md 思想：用户可见可改，仅显式指令触发写入）
CREATE TABLE user_memories (
    user_id    uuid PRIMARY KEY REFERENCES users(id),
    content    text NOT NULL DEFAULT '',
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- runs（M0′ 极简形态：status 字符串，无状态机——见 ADR 0002）
-- M2′ 固化状态机时迁移为状态机语义并补 run_events 严格约束
-- ============================================================

CREATE TABLE runs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      uuid NOT NULL REFERENCES projects(id),
    conversation_id uuid REFERENCES conversations(id),
    kind            text NOT NULL DEFAULT 'chat',         -- chat | ingest | extraction | agent
    agent_key       text NOT NULL DEFAULT 'basic',
    status          text NOT NULL DEFAULT 'created',
    -- created | running | completed | failed | cancelled
    input           jsonb NOT NULL DEFAULT '{}'::jsonb,
    output          jsonb NOT NULL DEFAULT '{}'::jsonb,
    error           text,
    started_at      timestamptz,
    finished_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_runs_project ON runs (project_id, created_at);

CREATE TABLE run_events (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      uuid NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq         integer NOT NULL,
    event_type  text NOT NULL,
    payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, seq)
);

-- ============================================================
-- review（审核队列：冲突 / 低置信度事实 / 实体合并）
-- ============================================================

CREATE TABLE review_items (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES projects(id),
    item_type   text NOT NULL,                           -- fact_pending | fact_conflict | entity_merge
    ref_id      uuid NOT NULL,
    reason      text NOT NULL DEFAULT '',
    status      text NOT NULL DEFAULT 'open',            -- open | resolved | ignored
    created_at  timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    resolved_by text,
    resolution  text NOT NULL DEFAULT ''
);

CREATE INDEX idx_review_open ON review_items (project_id, status);

-- ============================================================
-- audit（append-only 账本；应用层禁止 UPDATE/DELETE）
-- ============================================================

CREATE TABLE audit_log (
    id          bigserial PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    actor       text NOT NULL,                           -- user:<id> | agent:<run> | system
    action      text NOT NULL,
    object_type text NOT NULL,
    object_id   text NOT NULL,
    before      jsonb NOT NULL DEFAULT '{}'::jsonb,
    after       jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata    jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- ============================================================
-- seed
-- ============================================================

INSERT INTO users (username, display_name)
VALUES ('demo', 'Demo User')
ON CONFLICT (username) DO NOTHING;
