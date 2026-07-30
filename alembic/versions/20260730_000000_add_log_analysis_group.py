"""add AI log analysis attachment group

Revision ID: 20260730_000000
Revises: 20260714_000000
Create Date: 2026-07-30 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "20260730_000000"
down_revision = "20260714_000000"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return False
    return column_name in {
        column["name"] for column in inspector.get_columns(table_name)
    }


def _has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return False
    return index_name in {
        index["name"] for index in inspector.get_indexes(table_name)
    }


def upgrade() -> None:
    if not _has_column("log_records", "analysis_group_id"):
        op.add_column(
            "log_records",
            sa.Column(
                "analysis_group_id",
                sa.String(length=36),
                nullable=True,
                comment="AI日志分析附件分组ID",
            ),
        )
    if not _has_index(
        "log_records", "ix_log_records_analysis_group_id"
    ):
        op.create_index(
            "ix_log_records_analysis_group_id",
            "log_records",
            ["analysis_group_id"],
            unique=False,
        )


def downgrade() -> None:
    if _has_index("log_records", "ix_log_records_analysis_group_id"):
        op.drop_index(
            "ix_log_records_analysis_group_id", table_name="log_records"
        )
    if _has_column("log_records", "analysis_group_id"):
        op.drop_column("log_records", "analysis_group_id")
