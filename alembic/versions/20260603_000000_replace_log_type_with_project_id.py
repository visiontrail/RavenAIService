"""replace log_type with project_id on log_records

将 log_records.log_type 枚举列替换为指向 project_repo.id 的可空外键 project_id。

步骤：
1. 在 log_records 添加可空 project_id 整型外键列（ON DELETE SET NULL）
2. 确保 project_repo 中存在 stack / oam_antenna / full 条目（缺失则预置 full）
3. 通过 log_type → project_code 映射回填 project_id
4. 删除 log_type 列以及 logtype 枚举类型

Revision ID: 20260603_000000
Revises: 20260602_000000
Create Date: 2026-06-03 00:00:00.000000

"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "20260603_000000"
down_revision = "20260602_000000"
branch_labels = None
depends_on = None


# log_type 枚举值 → (project_code, project_name) 映射
_LOG_TYPE_PROJECTS = (
    ("stack", "Stack"),
    ("oam_antenna", "OAM Antenna"),
    ("full", "Full Log"),
)


def _ensure_project(conn, project_code: str, project_name: str) -> None:
    """缺失时预置 project_repo 条目（repo_url 为空字符串）。"""
    existing = conn.execute(
        text("SELECT id FROM project_repo WHERE project_code = :code"),
        {"code": project_code},
    ).fetchone()
    if existing:
        return
    now = datetime.utcnow().isoformat()
    conn.execute(
        text(
            "INSERT INTO project_repo "
            "(project_code, project_name, repo_url, default_branch, enabled, created_at, updated_at) "
            "VALUES (:code, :name, '', 'main', 1, :now, :now)"
        ),
        {"code": project_code, "name": project_name, "now": now},
    )


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. 添加可空 project_id 外键列
    with op.batch_alter_table("log_records") as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_log_records_project_id",
            "project_repo",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_log_records_project_id", "log_records", ["project_id"])

    # 2. 确保已知项目条目存在（至少预置 full）
    for project_code, project_name in _LOG_TYPE_PROJECTS:
        _ensure_project(bind, project_code, project_name)

    # 3. 按 log_type → project_code 回填 project_id
    for project_code, _ in _LOG_TYPE_PROJECTS:
        bind.execute(
            text(
                "UPDATE log_records SET project_id = "
                "(SELECT id FROM project_repo WHERE project_code = :code) "
                "WHERE log_type = :code"
            ),
            {"code": project_code},
        )

    # 4. 删除 log_type 列及枚举类型
    with op.batch_alter_table("log_records") as batch_op:
        batch_op.drop_column("log_type")

    if dialect == "postgresql":
        op.execute("DROP TYPE IF EXISTS logtype")


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        logtype_enum = sa.Enum("stack", "oam_antenna", "full", name="logtype")
        logtype_enum.create(bind, checkfirst=True)
        log_type_col = sa.Column(
            "log_type", logtype_enum, nullable=False, server_default="stack"
        )
    else:
        log_type_col = sa.Column(
            "log_type", sa.String(length=32), nullable=False, server_default="stack"
        )

    with op.batch_alter_table("log_records") as batch_op:
        batch_op.add_column(log_type_col)

    # 从 project_id → project_code 回填 log_type
    for project_code, _ in _LOG_TYPE_PROJECTS:
        bind.execute(
            text(
                "UPDATE log_records SET log_type = :code "
                "WHERE project_id = (SELECT id FROM project_repo WHERE project_code = :code)"
            ),
            {"code": project_code},
        )

    op.drop_index("ix_log_records_project_id", table_name="log_records")
    with op.batch_alter_table("log_records") as batch_op:
        batch_op.drop_constraint("fk_log_records_project_id", type_="foreignkey")
        batch_op.drop_column("project_id")
