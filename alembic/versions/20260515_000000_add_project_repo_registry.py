"""add_project_repo_registry

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-05-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = 'a1b2c3d4e5f6'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'project_repo',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('project_code', sa.String(128), nullable=False),
        sa.Column('project_name', sa.String(256), nullable=False),
        sa.Column('repo_url', sa.Text(), nullable=False),
        sa.Column('default_branch', sa.String(128), nullable=False, server_default='main'),
        sa.Column('git_token', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_unique_constraint('uq_project_repo_project_code', 'project_repo', ['project_code'])
    op.create_index('ix_project_repo_project_code', 'project_repo', ['project_code'])

    # Seed legacy OAM/Stack entries from current settings if they exist
    try:
        from app.config import settings
        from datetime import datetime

        now = datetime.utcnow().isoformat()
        conn = op.get_bind()

        seeds = []
        if settings.code_repo_oam_url:
            seeds.append(("oam_antenna", "OAM Antenna", settings.code_repo_oam_url))
        if settings.code_repo_stack_url:
            seeds.append(("stack", "Stack", settings.code_repo_stack_url))

        for project_code, project_name, repo_url in seeds:
            existing = conn.execute(
                text("SELECT id FROM project_repo WHERE project_code = :code"),
                {"code": project_code},
            ).fetchone()
            if not existing:
                conn.execute(
                    text(
                        "INSERT INTO project_repo "
                        "(project_code, project_name, repo_url, default_branch, enabled, created_at, updated_at) "
                        "VALUES (:code, :name, :url, 'main', 1, :now, :now)"
                    ),
                    {"code": project_code, "name": project_name, "url": repo_url, "now": now},
                )
    except Exception:
        pass  # Seed failure is non-fatal; admin can add entries manually


def downgrade() -> None:
    op.drop_index('ix_project_repo_project_code', 'project_repo')
    op.drop_constraint('uq_project_repo_project_code', 'project_repo', type_='unique')
    op.drop_table('project_repo')
