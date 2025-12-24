"""add_user_chat_tables

Revision ID: 2c9b4a1f6e8d
Revises: f1a2b3c4d5e6
Create Date: 2025-02-06 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2c9b4a1f6e8d"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "users" not in existing_tables:
        op.create_table(
            "users",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("username", sa.String(length=128), nullable=False),
            sa.Column("display_name", sa.String(length=128), nullable=True),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("last_login_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("username"),
        )
    existing_indexes = {index["name"] for index in inspector.get_indexes("users")} if "users" in existing_tables else set()
    if "ix_users_username" not in existing_indexes:
        op.create_index("ix_users_username", "users", ["username"])

    if "chat_sessions" not in existing_tables:
        op.create_table(
            "chat_sessions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("last_message_at", sa.DateTime(), nullable=False),
            sa.Column("message_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    existing_indexes = {index["name"] for index in inspector.get_indexes("chat_sessions")} if "chat_sessions" in inspector.get_table_names() else set()
    if "ix_chat_sessions_user_id" not in existing_indexes:
        op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])

    if "chat_messages" not in existing_tables:
        op.create_table(
            "chat_messages",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    existing_indexes = {index["name"] for index in inspector.get_indexes("chat_messages")} if "chat_messages" in inspector.get_table_names() else set()
    if "ix_chat_messages_session_id" not in existing_indexes:
        op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "chat_messages" in existing_tables:
        existing_indexes = {index["name"] for index in inspector.get_indexes("chat_messages")}
        if "ix_chat_messages_session_id" in existing_indexes:
            op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
        op.drop_table("chat_messages")

    if "chat_sessions" in existing_tables:
        existing_indexes = {index["name"] for index in inspector.get_indexes("chat_sessions")}
        if "ix_chat_sessions_user_id" in existing_indexes:
            op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
        op.drop_table("chat_sessions")

    if "users" in existing_tables:
        existing_indexes = {index["name"] for index in inspector.get_indexes("users")}
        if "ix_users_username" in existing_indexes:
            op.drop_index("ix_users_username", table_name="users")
        op.drop_table("users")
