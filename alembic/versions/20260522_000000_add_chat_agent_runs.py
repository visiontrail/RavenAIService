"""add_chat_agent_runs

Revision ID: 20260522_000000
Revises: 20260521_000000
Create Date: 2026-05-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260522_000000"
down_revision = "20260521_000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "chat_agent_runs" not in existing_tables:
        op.create_table(
            "chat_agent_runs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=True),
            sa.Column(
                "owner_scope",
                sa.String(length=128),
                nullable=False,
                server_default="anon:unknown",
            ),
            sa.Column("agent_kind", sa.String(length=32), nullable=False),
            sa.Column(
                "status",
                sa.String(length=24),
                nullable=False,
                server_default="running",
            ),
            sa.Column("user_message", sa.Text(), nullable=False, server_default=""),
            sa.Column("request_json", sa.Text(), nullable=True),
            sa.Column("workspace_path", sa.Text(), nullable=True),
            sa.Column("answer", sa.Text(), nullable=True),
            sa.Column("model", sa.String(length=128), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("trace_events_json", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    existing_indexes = (
        {index["name"] for index in inspector.get_indexes("chat_agent_runs")}
        if "chat_agent_runs" in inspector.get_table_names()
        else set()
    )
    if "ix_chat_agent_runs_session_id" not in existing_indexes:
        op.create_index(
            "ix_chat_agent_runs_session_id",
            "chat_agent_runs",
            ["session_id"],
        )
    if "ix_chat_agent_runs_user_status" not in existing_indexes:
        op.create_index(
            "ix_chat_agent_runs_user_status",
            "chat_agent_runs",
            ["user_id", "status"],
        )
    if "ix_chat_agent_runs_updated_at" not in existing_indexes:
        op.create_index(
            "ix_chat_agent_runs_updated_at",
            "chat_agent_runs",
            ["updated_at"],
        )
    if "ix_chat_agent_runs_owner_scope" not in existing_indexes:
        op.create_index(
            "ix_chat_agent_runs_owner_scope",
            "chat_agent_runs",
            ["owner_scope"],
        )
    if "ix_chat_agent_runs_owner_session_status" not in existing_indexes:
        op.create_index(
            "ix_chat_agent_runs_owner_session_status",
            "chat_agent_runs",
            ["owner_scope", "session_id", "status"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "chat_agent_runs" not in existing_tables:
        return

    existing_indexes = {index["name"] for index in inspector.get_indexes("chat_agent_runs")}
    for ix in (
        "ix_chat_agent_runs_session_id",
        "ix_chat_agent_runs_user_status",
        "ix_chat_agent_runs_updated_at",
        "ix_chat_agent_runs_owner_scope",
        "ix_chat_agent_runs_owner_session_status",
    ):
        if ix in existing_indexes:
            op.drop_index(ix, table_name="chat_agent_runs")

    op.drop_table("chat_agent_runs")
