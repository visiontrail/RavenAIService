"""DeviceAgent —— 基于 Claude Agent SDK 的设备联动对话智能体。

模块布局（详见 openspec design.md Decision 12）：

- ``agent``           : ``DeviceAgent.run`` / ``run_stream`` 入口
- ``mcp_tools``       : 远端设备 MCP 工具 → in-process SDK 工具映射
- ``permissions``     : ``PermissionBroker`` + ``can_use_tool`` 工厂
- ``post_tool_hook``  : ``PostToolUse`` hook，结果 schema 校验/裁剪/脱敏
- ``prompts``         : 从 prompts_config.yaml 读取 system/user 提示词
- ``trace``           : 设备智能体专属 trace 事件常量（复用 log_analysis.trace）
- ``workspace``       : 会话级临时工作目录，Skill 物化与清理
"""

from app.agents.device_agent.agent import AGENT_KEY, DeviceAgent, DeviceAgentContext

__all__ = ["AGENT_KEY", "DeviceAgent", "DeviceAgentContext"]
