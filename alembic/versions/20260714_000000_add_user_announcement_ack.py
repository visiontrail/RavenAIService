"""add user announcement acknowledgement marker

Revision ID: 20260714_000000
Revises: 20260710_000000
Create Date: 2026-07-14 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260714_000000"
down_revision = "20260710_000000"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return False
    return column_name in {
        column["name"] for column in inspector.get_columns(table_name)
    }


def upgrade() -> None:
    # Some installations let startup-time ORM synchronization add nullable
    # columns before Alembic is run. Keep the formal migration idempotent for
    # that supported deployment path.
    if _has_column("users", "last_seen_announcement_id"):
        return
    op.add_column(
        "users",
        sa.Column(
            "last_seen_announcement_id",
            sa.String(length=36),
            nullable=True,
            comment="最近确认关闭的系统公告ID",
        ),
    )


def downgrade() -> None:
    if not _has_column("users", "last_seen_announcement_id"):
        return
    op.drop_column("users", "last_seen_announcement_id")
