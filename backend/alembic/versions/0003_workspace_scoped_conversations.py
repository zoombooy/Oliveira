"""Allow conversations and Agent Runs without a selected project.

Existing rows are backfilled from their project workspace. Project-scoped
conversations continue to work unchanged; a NULL project_id now represents a
workspace-level conversation that uses the workspace default Provider and does
not search project documents unless a project scope is selected.
"""

from alembic import op


revision = "0003_workspace_scoped_conversations"
down_revision = "0002_v03_eval_task_dedupe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS "
        "workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE"
    )
    op.execute(
        "UPDATE conversations c SET workspace_id = p.workspace_id "
        "FROM projects p WHERE c.workspace_id IS NULL AND c.project_id = p.id"
    )
    op.execute(
        "ALTER TABLE conversations ALTER COLUMN project_id DROP NOT NULL"
    )
    op.execute(
        "ALTER TABLE conversations ALTER COLUMN workspace_id SET NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_workspace "
        "ON conversations(workspace_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_project "
        "ON conversations(project_id, created_at)"
    )

    op.execute(
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS "
        "workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE"
    )
    op.execute(
        "UPDATE runs r SET workspace_id = p.workspace_id "
        "FROM projects p WHERE r.workspace_id IS NULL AND r.project_id = p.id"
    )
    op.execute("ALTER TABLE runs ALTER COLUMN project_id DROP NOT NULL")
    op.execute("ALTER TABLE runs ALTER COLUMN workspace_id SET NOT NULL")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_runs_workspace "
        "ON runs(workspace_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_runs_project "
        "ON runs(project_id, created_at)"
    )


def downgrade() -> None:
    # Existing workspace-scoped rows cannot be safely assigned to a project;
    # keep this migration non-destructive and require an explicit data policy
    # before attempting a rollback.
    pass
