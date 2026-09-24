"""Add v0.3 retrieval evaluation records and task idempotency keys.

The bootstrap SQL also contains these objects for a fresh database. The
upgrade is therefore intentionally idempotent so an operator can run
alembic upgrade head after either a fresh bootstrap or an older database.
"""

from alembic import op


revision = "0002_v03_eval_task_dedupe"
down_revision = "0001_bootstrap_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS dedupe_key text")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_dedupe_key "
        "ON tasks(dedupe_key) WHERE dedupe_key IS NOT NULL"
    )
    op.execute("""CREATE TABLE IF NOT EXISTS evaluation_cases (
       id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
       project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
       question text NOT NULL,
       expected_chunk_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
       expected_document_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
       reference_answer text NOT NULL DEFAULT '',
       metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
       active boolean NOT NULL DEFAULT true,
       created_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_evaluation_cases_project "
        "ON evaluation_cases(project_id, active)"
    )
    op.execute("""CREATE TABLE IF NOT EXISTS evaluation_runs (
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
    )""")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_evaluation_runs_project "
        "ON evaluation_runs(project_id, created_at)"
    )
    op.execute("""CREATE TABLE IF NOT EXISTS evaluation_results (
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
    )""")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_evaluation_results_run "
        "ON evaluation_results(run_id)"
    )


def downgrade() -> None:
    # Fresh databases receive these objects from the bootstrap SQL, so a
    # blind downgrade cannot distinguish migration-owned objects from the
    # baseline schema. Keep the rollback non-destructive; operators must use
    # an explicit, reviewed data migration if they need to remove them.
    pass
