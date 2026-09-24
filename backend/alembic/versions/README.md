The first revision is a no-op baseline because a brand-new PostgreSQL volume is
bootstrapped by `deploy/postgres/init/001_init.sql`. Any schema change after the
baseline must be added as a normal Alembic revision and must not be applied by
editing the bootstrap SQL alone.
