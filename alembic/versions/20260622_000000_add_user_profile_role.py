"""add user profile role

Revision ID: 20260622_000000
Revises: 20260616_000000
Create Date: 2026-06-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260622_000000"
down_revision = "20260616_000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in set(inspector.get_table_names()):
        return
    existing_columns = {col["name"] for col in inspector.get_columns("users")}
    if "profile_role" not in existing_columns:
        op.add_column(
            "users",
            sa.Column(
                "profile_role",
                sa.String(length=64),
                nullable=False,
                server_default="developer",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in set(inspector.get_table_names()):
        return
    existing_columns = {col["name"] for col in inspector.get_columns("users")}
    if "profile_role" in existing_columns:
        op.drop_column("users", "profile_role")
