"""add_chat_session_pin

Revision ID: 20260601_000000
Revises: 20260522_000000
Create Date: 2026-06-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260601_000000"
down_revision = "20260522_000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "chat_sessions" not in set(inspector.get_table_names()):
        return

    existing_columns = {col["name"] for col in inspector.get_columns("chat_sessions")}
    if "is_pinned" not in existing_columns:
        op.add_column(
            "chat_sessions",
            sa.Column(
                "is_pinned",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if "pinned_at" not in existing_columns:
        op.add_column(
            "chat_sessions",
            sa.Column("pinned_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "chat_sessions" not in set(inspector.get_table_names()):
        return

    existing_columns = {col["name"] for col in inspector.get_columns("chat_sessions")}
    if "pinned_at" in existing_columns:
        op.drop_column("chat_sessions", "pinned_at")
    if "is_pinned" in existing_columns:
        op.drop_column("chat_sessions", "is_pinned")
