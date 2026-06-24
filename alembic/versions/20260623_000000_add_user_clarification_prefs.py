"""add user clarification preferences

Revision ID: 20260623_000000
Revises: 20260622_000000
Create Date: 2026-06-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260623_000000"
down_revision = "20260622_000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in set(inspector.get_table_names()):
        return
    existing_columns = {col["name"] for col in inspector.get_columns("users")}
    if "clarification_enabled" not in existing_columns:
        op.add_column(
            "users",
            sa.Column(
                "clarification_enabled",
                sa.Boolean(),
                nullable=False,
                server_default="1",
            ),
        )
    if "clarification_max_rounds" not in existing_columns:
        op.add_column(
            "users",
            sa.Column(
                "clarification_max_rounds",
                sa.Integer(),
                nullable=False,
                server_default="5",
            ),
        )
    if "clarification_on_timeout" not in existing_columns:
        op.add_column(
            "users",
            sa.Column(
                "clarification_on_timeout",
                sa.String(length=16),
                nullable=False,
                server_default="cancel",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in set(inspector.get_table_names()):
        return
    existing_columns = {col["name"] for col in inspector.get_columns("users")}
    for col in (
        "clarification_on_timeout",
        "clarification_max_rounds",
        "clarification_enabled",
    ):
        if col in existing_columns:
            op.drop_column("users", col)
