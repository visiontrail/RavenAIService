"""add project repo agent bindings

Revision ID: 20260708_000000
Revises: 20260623_000000
Create Date: 2026-07-08 00:00:00.000000

"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "20260708_000000"
down_revision = "20260623_000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "project_repo_agent" not in existing_tables:
        op.create_table(
            "project_repo_agent",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_repo_id", sa.Integer(), nullable=False),
            sa.Column("agent_key", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["project_repo_id"], ["project_repo.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "project_repo_id", "agent_key", name="uq_project_repo_agent"
            ),
        )
        op.create_index(
            "ix_project_repo_agent_project_repo_id",
            "project_repo_agent",
            ["project_repo_id"],
        )
        op.create_index(
            "ix_project_repo_agent_agent_key",
            "project_repo_agent",
            ["agent_key"],
        )

    if "project_repo" not in existing_tables:
        return

    now = datetime.utcnow()
    rows = bind.execute(
        text("SELECT id, repo_url FROM project_repo")
    ).fetchall()
    for repo_id, repo_url in rows:
        has_repo = bool(str(repo_url or "").strip())
        keys = ["project_expert"]
        if has_repo:
            keys.extend(["log_analysis", "package_search"])
        for key in keys:
            bind.execute(
                text(
                    "INSERT INTO project_repo_agent "
                    "(project_repo_id, agent_key, created_at, updated_at) "
                    "SELECT :repo_id, :agent_key, :now, :now "
                    "WHERE NOT EXISTS ("
                    "  SELECT 1 FROM project_repo_agent "
                    "  WHERE project_repo_id = :repo_id AND agent_key = :agent_key"
                    ")"
                ),
                {"repo_id": repo_id, "agent_key": key, "now": now},
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "project_repo_agent" not in set(inspector.get_table_names()):
        return
    existing_indexes = {
        index["name"] for index in inspector.get_indexes("project_repo_agent")
    }
    if "ix_project_repo_agent_agent_key" in existing_indexes:
        op.drop_index(
            "ix_project_repo_agent_agent_key", table_name="project_repo_agent"
        )
    if "ix_project_repo_agent_project_repo_id" in existing_indexes:
        op.drop_index(
            "ix_project_repo_agent_project_repo_id",
            table_name="project_repo_agent",
        )
    op.drop_table("project_repo_agent")
