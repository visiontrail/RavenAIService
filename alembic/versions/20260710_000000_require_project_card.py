"""require project card and rename description

Revision ID: 20260710_000000
Revises: 20260708_000000
Create Date: 2026-07-10 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "20260710_000000"
down_revision = "20260708_000000"
branch_labels = None
depends_on = None

_INSERT_TRIGGER = "trg_project_repo_project_card_required_insert"
_UPDATE_TRIGGER = "trg_project_repo_project_card_required_update"


def _create_sqlite_required_triggers(bind) -> None:
    bind.execute(
        text(
            f"CREATE TRIGGER IF NOT EXISTS {_INSERT_TRIGGER} "
            "BEFORE INSERT ON project_repo "
            "FOR EACH ROW WHEN NEW.project_card IS NULL OR TRIM(NEW.project_card) = '' "
            "BEGIN SELECT RAISE(ABORT, 'project_card is required'); END"
        )
    )
    bind.execute(
        text(
            f"CREATE TRIGGER IF NOT EXISTS {_UPDATE_TRIGGER} "
            "BEFORE UPDATE OF project_card ON project_repo "
            "FOR EACH ROW WHEN NEW.project_card IS NULL OR TRIM(NEW.project_card) = '' "
            "BEGIN SELECT RAISE(ABORT, 'project_card is required'); END"
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text(
            "UPDATE project_repo "
            "SET description = "
            "'历史项目「' || project_name || '」（' || project_code || "
            "'）的项目范围尚未补充，请管理员完善项目卡片后再据此匹配问题。' "
            "WHERE description IS NULL OR TRIM(description) = ''"
        )
    )
    bind.execute(
        text(
            "UPDATE project_repo SET description = TRIM(description) "
            "WHERE description IS NOT NULL"
        )
    )
    if bind.dialect.name == "sqlite":
        bind.execute(
            text(
                "ALTER TABLE project_repo "
                "RENAME COLUMN description TO project_card"
            )
        )
        _create_sqlite_required_triggers(bind)
    else:
        with op.batch_alter_table("project_repo") as batch_op:
            batch_op.alter_column(
                "description",
                new_column_name="project_card",
                existing_type=sa.Text(),
                existing_nullable=True,
                nullable=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.execute(text(f"DROP TRIGGER IF EXISTS {_INSERT_TRIGGER}"))
        bind.execute(text(f"DROP TRIGGER IF EXISTS {_UPDATE_TRIGGER}"))
        bind.execute(
            text(
                "ALTER TABLE project_repo "
                "RENAME COLUMN project_card TO description"
            )
        )
    else:
        with op.batch_alter_table("project_repo") as batch_op:
            batch_op.alter_column(
                "project_card",
                new_column_name="description",
                existing_type=sa.Text(),
                existing_nullable=False,
                nullable=True,
            )
