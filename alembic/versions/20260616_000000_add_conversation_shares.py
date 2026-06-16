"""add_conversation_shares

Revision ID: 20260616_000000
Revises: 20260605_000000
Create Date: 2026-06-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260616_000000"
down_revision = "20260605_000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "conversation_shares" not in existing_tables:
        op.create_table(
            "conversation_shares",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("token", sa.String(length=32), nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("snapshot_json", sa.Text(), nullable=False),
            sa.Column("message_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("shared_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    has_table = "conversation_shares" in inspector.get_table_names()
    existing_indexes = (
        {index["name"] for index in inspector.get_indexes("conversation_shares")}
        if has_table
        else set()
    )
    if "ix_conversation_shares_token" not in existing_indexes:
        op.create_index(
            "ix_conversation_shares_token",
            "conversation_shares",
            ["token"],
            unique=True,
        )
    if "ix_conversation_shares_session_id" not in existing_indexes:
        op.create_index(
            "ix_conversation_shares_session_id",
            "conversation_shares",
            ["session_id"],
        )
    if "ix_conversation_shares_user_id" not in existing_indexes:
        op.create_index(
            "ix_conversation_shares_user_id",
            "conversation_shares",
            ["user_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "conversation_shares" in existing_tables:
        existing_indexes = {
            index["name"] for index in inspector.get_indexes("conversation_shares")
        }
        for index_name in (
            "ix_conversation_shares_user_id",
            "ix_conversation_shares_session_id",
            "ix_conversation_shares_token",
        ):
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name="conversation_shares")
        op.drop_table("conversation_shares")
