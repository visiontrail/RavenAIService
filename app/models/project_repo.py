"""
项目仓库注册表 SQLAlchemy 模型。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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


class ProjectRepoMember(Base, TimestampMixin):
    """项目仓库 ↔ 注册用户的成员关系。

    作为 Bug 修复列表可见性的鉴权依据：成员（及管理员）才能看到该项目的
    Bug 修复任务与详情。
    """

    __tablename__ = "project_repo_member"
    __table_args__ = (
        UniqueConstraint(
            "project_repo_id", "user_id", name="uq_project_repo_member"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_repo_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("project_repo.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目仓库（project_repo.id）",
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="成员用户（users.id）",
    )


class ProjectRepoAgent(Base, TimestampMixin):
    """项目仓库 ↔ 可用 Agent 的关系。

    关系存在即表示该项目允许该 Agent 作为后续操作/分析入口使用。
    """

    __tablename__ = "project_repo_agent"
    __table_args__ = (
        UniqueConstraint(
            "project_repo_id", "agent_key", name="uq_project_repo_agent"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_repo_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("project_repo.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目仓库（project_repo.id）",
    )
    agent_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="可操作该项目的 Agent key，如 project_expert/log_analysis/package_search",
    )
