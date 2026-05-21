"""add_user_role

Revision ID: 20260521_000000
Revises: 2c9b4a1f6e8d
Create Date: 2026-05-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260521_000000"
down_revision = "2c9b4a1f6e8d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in set(inspector.get_table_names()):
        return
    existing_columns = {col["name"] for col in inspector.get_columns("users")}
    if "role" not in existing_columns:
        op.add_column(
            "users",
            sa.Column(
                "role",
                sa.String(length=32),
                nullable=False,
                server_default="user",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in set(inspector.get_table_names()):
        return
    existing_columns = {col["name"] for col in inspector.get_columns("users")}
    if "role" in existing_columns:
        op.drop_column("users", "role")
