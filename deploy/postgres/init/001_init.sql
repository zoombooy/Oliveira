-- Oliveira M0-M3 bootstrap schema. PostgreSQL is the fact source.
-- Later changes are applied through Alembic migrations.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    username text NOT NULL UNIQUE,
    display_name text NOT NULL DEFAULT '',
    password_hash text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE workspaces (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    owner_id uuid NOT NULL REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE workspace_members (
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role text NOT NULL DEFAULT 'member',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, user_id),
    CHECK (role IN ('owner', 'admin', 'member', 'viewer'))
);

CREATE TABLE provider_profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name text NOT NULL,
    provider_type text NOT NULL DEFAULT 'openai_compatible',
    base_url text NOT NULL,
    chat_model text NOT NULL,
    embedding_model text NOT NULL DEFAULT '',
    api_key_ciphertext text NOT NULL DEFAULT '',
    capabilities jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_default boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE projects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id),
    name text NOT NULL,
    description text NOT NULL DEFAULT '',
    owner_id uuid NOT NULL REFERENCES users(id),
    provider_id uuid REFERENCES provider_profiles(id),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_projects_workspace ON projects(workspace_id);

CREATE TABLE documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    title text NOT NULL,
    source_type text NOT NULL DEFAULT 'upload',
    current_version_id uuid,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE document_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_no integer NOT NULL,
    file_name text NOT NULL,
    mime_type text NOT NULL DEFAULT '',
    size_bytes bigint NOT NULL DEFAULT 0,
    content_hash text NOT NULL,
    parse_status text NOT NULL DEFAULT 'pending',
    index_status text NOT NULL DEFAULT 'pending',
    parse_error text,
    object_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(document_id, version_no),
    CHECK (parse_status IN ('pending', 'parsed', 'failed')),
    CHECK (index_status IN ('pending', 'completed', 'partial', 'failed', 'unavailable'))
);

ALTER TABLE documents ADD CONSTRAINT fk_documents_current_version
    FOREIGN KEY(current_version_id) REFERENCES document_versions(id);

CREATE TABLE document_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    chunk_index integer NOT NULL,
    page_number integer,
    paragraph_index integer,
    content text NOT NULL,
    content_hash text NOT NULL,
    token_count integer NOT NULL DEFAULT 0,
    embedding vector(1024),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(document_version_id, chunk_index)
);
CREATE INDEX idx_chunks_embedding ON document_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_chunks_content_trgm ON document_chunks USING gin (content gin_trgm_ops);

CREATE TABLE evidence_refs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    document_id uuid REFERENCES documents(id),
    document_version_id uuid REFERENCES document_versions(id),
    chunk_id uuid REFERENCES document_chunks(id),
    quote text NOT NULL DEFAULT '',
    location jsonb NOT NULL DEFAULT '{}'::jsonb,
    observed_at timestamptz,
    snapshot_hash text NOT NULL DEFAULT '',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_evidence_project ON evidence_refs(project_id);

CREATE TABLE entities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    name text NOT NULL,
    normalized_name text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_entities_project_name ON entities(project_id, normalized_name);

CREATE TABLE facts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    subject_entity_id uuid REFERENCES entities(id),
    subject_text text NOT NULL DEFAULT '',
    predicate text NOT NULL,
    object_entity_id uuid REFERENCES entities(id),
    object_text text NOT NULL DEFAULT '',
    current_version_id uuid,
    status text NOT NULL DEFAULT 'pending',
    confidence numeric(4,3),
    created_by text NOT NULL DEFAULT 'system',
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK(status IN ('pending', 'asserted', 'derived', 'rejected', 'retracted', 'superseded'))
);
CREATE INDEX idx_facts_project_status ON facts(project_id, status);

CREATE TABLE fact_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    fact_id uuid NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    version_no integer NOT NULL,
    subject_text text NOT NULL DEFAULT '',
    predicate text NOT NULL,
    object_text text NOT NULL DEFAULT '',
    valid_from timestamptz,
    valid_to timestamptz,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    retracted_at timestamptz,
    evidence_ref_id uuid REFERENCES evidence_refs(id),
    change_reason text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(fact_id, version_no)
);
ALTER TABLE facts ADD CONSTRAINT fk_facts_current_version
    FOREIGN KEY(current_version_id) REFERENCES fact_versions(id);

CREATE TABLE fact_evidence (
    fact_version_id uuid NOT NULL REFERENCES fact_versions(id) ON DELETE CASCADE,
    evidence_ref_id uuid NOT NULL REFERENCES evidence_refs(id),
    PRIMARY KEY(fact_version_id, evidence_ref_id)
);

CREATE TABLE fact_conflicts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    fact_id uuid NOT NULL REFERENCES facts(id),
    conflicting_fact_id uuid NOT NULL REFERENCES facts(id),
    conflict_type text NOT NULL DEFAULT 'contradiction',
    status text NOT NULL DEFAULT 'open',
    resolution text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    resolved_by text
);

CREATE TABLE conversations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    user_id uuid REFERENCES users(id),
    title text NOT NULL DEFAULT '新对话',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role text NOT NULL,
    content text NOT NULL,
    token_count integer NOT NULL DEFAULT 0,
    run_id uuid,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_messages_conversation ON messages(conversation_id, created_at);

CREATE TABLE conversation_summaries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    covered_until_message_id uuid,
    content text NOT NULL,
    token_estimate integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE user_memories (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key text NOT NULL,
    value text NOT NULL,
    source_message_id uuid,
    source_run_id uuid,
    status text NOT NULL DEFAULT 'active',
    confidence numeric(4,3) NOT NULL DEFAULT 1.0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    retracted_at timestamptz
);
CREATE INDEX idx_user_memories_active ON user_memories(user_id, status);

CREATE TABLE runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    conversation_id uuid REFERENCES conversations(id),
    kind text NOT NULL DEFAULT 'chat',
    agent_key text NOT NULL DEFAULT 'basic',
    status text NOT NULL DEFAULT 'created',
    input jsonb NOT NULL DEFAULT '{}'::jsonb,
    output jsonb NOT NULL DEFAULT '{}'::jsonb,
    error text,
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_runs_project ON runs(project_id, created_at);

CREATE TABLE run_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq integer NOT NULL,
    event_type text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(run_id, seq)
);

CREATE TABLE tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id),
    project_id uuid REFERENCES projects(id),
    kind text NOT NULL,
    dedupe_key text,
    status text NOT NULL DEFAULT 'queued',
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    result jsonb NOT NULL DEFAULT '{}'::jsonb,
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 3,
    available_at timestamptz NOT NULL DEFAULT now(),
    locked_by text,
    locked_at timestamptz,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz
);
CREATE INDEX idx_tasks_claim ON tasks(status, available_at, created_at);
CREATE UNIQUE INDEX uq_tasks_dedupe_key ON tasks(dedupe_key) WHERE dedupe_key IS NOT NULL;

CREATE TABLE evaluation_cases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    question text NOT NULL,
    expected_chunk_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    expected_document_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    reference_answer text NOT NULL DEFAULT '',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_evaluation_cases_project ON evaluation_cases(project_id, active);

CREATE TABLE evaluation_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'queued',
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
    total_cases integer NOT NULL DEFAULT 0,
    completed_cases integer NOT NULL DEFAULT 0,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz
);
CREATE INDEX idx_evaluation_runs_project ON evaluation_runs(project_id, created_at);

CREATE TABLE evaluation_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES evaluation_runs(id) ON DELETE CASCADE,
    case_id uuid NOT NULL REFERENCES evaluation_cases(id) ON DELETE CASCADE,
    retrieved_chunk_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    first_hit_rank integer,
    hit_at_k boolean NOT NULL DEFAULT false,
    reciprocal_rank double precision NOT NULL DEFAULT 0,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(run_id, case_id)
);
CREATE INDEX idx_evaluation_results_run ON evaluation_results(run_id);

CREATE TABLE review_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    item_type text NOT NULL,
    ref_id uuid NOT NULL,
    reason text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'open',
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    resolved_by text,
    resolution text NOT NULL DEFAULT ''
);
CREATE INDEX idx_review_open ON review_items(project_id, status);

CREATE TABLE audit_log (
    id bigserial PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    actor text NOT NULL,
    action text NOT NULL,
    object_type text NOT NULL,
    object_id text NOT NULL,
    before jsonb NOT NULL DEFAULT '{}'::jsonb,
    after jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

INSERT INTO users(username, display_name)
VALUES ('demo', 'Demo User')
ON CONFLICT(username) DO NOTHING;

INSERT INTO workspaces(name, owner_id)
SELECT 'Demo Workspace', id FROM users WHERE username = 'demo'
AND NOT EXISTS (SELECT 1 FROM workspaces WHERE name = 'Demo Workspace');

INSERT INTO workspace_members(workspace_id, user_id, role)
SELECT w.id, u.id, 'owner'
FROM workspaces w CROSS JOIN users u
WHERE w.name = 'Demo Workspace' AND u.username = 'demo'
ON CONFLICT DO NOTHING;
