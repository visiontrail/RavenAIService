"""add language column to users

Adds a per-user ``language`` preference (``zh``/``en``, default ``zh``) backing
the multi-language support feature. Purely additive and backward compatible:
existing rows default to ``zh``.

Revision ID: 20260605_000000
Revises: 20260604_000000
Create Date: 2026-06-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260605_000000"
down_revision = "20260604_000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = bind.execute(sa.text("PRAGMA table_info('users')")).fetchall()
    has_language = any(row[1] == "language" for row in columns)
    if not has_language:
        op.add_column(
            "users",
            sa.Column(
                "language",
                sa.String(length=8),
                nullable=False,
                server_default="zh",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = bind.execute(sa.text("PRAGMA table_info('users')")).fetchall()
    has_language = any(row[1] == "language" for row in columns)
    if has_language:
        op.drop_column("users", "language")
