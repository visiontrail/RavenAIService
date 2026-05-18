"""add_archive_path_to_log_records

Revision ID: 20260518_000000
Revises: a1b2c3d4e5f6
Create Date: 2026-05-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260518_000000'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    column_names = {column["name"] for column in inspector.get_columns("log_records")}
    if "archive_path" not in column_names:
        op.add_column(
            "log_records",
            sa.Column("archive_path", sa.String(500), nullable=True, comment="日志归档文件路径（AI分析使用）"),
        )
        # Backfill existing records: archive_path = file_path
        op.execute("UPDATE log_records SET archive_path = file_path WHERE archive_path IS NULL")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    column_names = {column["name"] for column in inspector.get_columns("log_records")}
    if "archive_path" in column_names:
        op.drop_column("log_records", "archive_path")
