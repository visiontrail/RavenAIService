"""Claude Agent SDK 项目源码答疑智能体包。

与 Log Analysis Agent 同构，但去掉附件日志分析这一环：不上传归档、
不解压 `logs/`、不依赖 `metadata.json`。项目身份由用户显式选择的项目
仓库提供，写入 `task.json.repo_info`。
"""

from app.agents.project_expert.agent import ProjectExpertAgent

__all__ = ["ProjectExpertAgent"]
