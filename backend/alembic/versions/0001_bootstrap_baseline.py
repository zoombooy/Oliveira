"""Mark the PostgreSQL bootstrap schema as the Alembic baseline.

Fresh installations still execute deploy/postgres/init/001_init.sql. This no-op
revision gives subsequent schema changes a versioned starting point without
duplicating the large bootstrap DDL.
"""

revision = "0001_bootstrap_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
