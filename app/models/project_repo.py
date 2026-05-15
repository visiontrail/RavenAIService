"""
项目仓库注册表 SQLAlchemy 模型。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, TimestampMixin


class ProjectRepo(Base, TimestampMixin):
    """项目代号 → Git 仓库地址映射表。"""

    __tablename__ = "project_repo"
    __table_args__ = (
        UniqueConstraint("project_code", name="uq_project_repo_project_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_code: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True, comment="业务唯一键（小写规范化）"
    )
    project_name: Mapped[str] = mapped_column(String(256), nullable=False, comment="展示用名称")
    repo_url: Mapped[str] = mapped_column(Text, nullable=False, comment="完整 git URL（不含 token）")
    default_branch: Mapped[str] = mapped_column(
        String(128), nullable=False, default="main", server_default="main", comment="默认分支"
    )
    git_token: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="per-repo git token，覆盖全局 code_repo_git_token；NULL 表示走全局"
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="备注说明")
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1", comment="是否启用"
    )
