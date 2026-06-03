"""add bug fix task / merge request / project repo member tables

新增三张表，支撑 Bug Fix Coding Agent 闭环：

- ``bug_fix_task``：一次 Bug 修复任务（来源日志/分析、状态机、proposed_fixes）。
- ``bug_fix_merge_request``：任务产出的单个 MR 汇总（一对多，不存 token）。
- ``project_repo_member``：项目仓库 ↔ 注册用户成员关系（可见性鉴权依据）。

纯新增、向后兼容。

Revision ID: 20260604_000000
Revises: 20260603_000000
Create Date: 2026-06-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260604_000000"
down_revision = "20260603_000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bug_fix_task",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_repo_id", sa.Integer(), nullable=False),
        sa.Column("source_log_id", sa.String(length=36), nullable=True),
        sa.Column("source_analysis_task_id", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("proposed_fixes_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_repo_id"], ["project_repo.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bug_fix_task_project_repo_id", "bug_fix_task", ["project_repo_id"]
    )
    op.create_index(
        "ix_bug_fix_task_source_log_id", "bug_fix_task", ["source_log_id"]
    )
    op.create_index("ix_bug_fix_task_status", "bug_fix_task", ["status"])

    op.create_table(
        "bug_fix_merge_request",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("branch_name", sa.String(length=256), nullable=False),
        sa.Column("base_branch", sa.String(length=256), nullable=False),
        sa.Column("mr_url", sa.Text(), nullable=True),
        sa.Column("mr_iid", sa.String(length=64), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("changed_files_json", sa.Text(), nullable=True),
        sa.Column("diff_stat_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"], ["bug_fix_task.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bug_fix_merge_request_task_id", "bug_fix_merge_request", ["task_id"]
    )

    op.create_table(
        "project_repo_member",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_repo_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_repo_id"], ["project_repo.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_repo_id", "user_id", name="uq_project_repo_member"
        ),
    )
    op.create_index(
        "ix_project_repo_member_project_repo_id",
        "project_repo_member",
        ["project_repo_id"],
    )
    op.create_index(
        "ix_project_repo_member_user_id", "project_repo_member", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_repo_member_user_id", table_name="project_repo_member"
    )
    op.drop_index(
        "ix_project_repo_member_project_repo_id", table_name="project_repo_member"
    )
    op.drop_table("project_repo_member")

    op.drop_index(
        "ix_bug_fix_merge_request_task_id", table_name="bug_fix_merge_request"
    )
    op.drop_table("bug_fix_merge_request")

    op.drop_index("ix_bug_fix_task_status", table_name="bug_fix_task")
    op.drop_index("ix_bug_fix_task_source_log_id", table_name="bug_fix_task")
    op.drop_index("ix_bug_fix_task_project_repo_id", table_name="bug_fix_task")
    op.drop_table("bug_fix_task")
