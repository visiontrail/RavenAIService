# Patent — 发明专利申请文档（二）

**发明名称：一种基于动态能力映射与人机协同权限管控的AI智能体远程设备交互方法、系统、电子设备及存储介质**

本目录为基于 RavenAIService 项目实际实现撰写的第二篇中国发明专利申请文档草案，围绕本项目在 **AI 智能体与远程异构设备交互** 方面的核心技术创新：**设备能力的动态映射、工具调用的分级权限管控、设备应答的后置校验净化、协议版本的自适应分发、以及基于结构化选项的主动澄清提问**。

> 本专利与同目录下第一篇专利（"分级技能包与分层提示词编排"）从不同技术维度保护本项目的创新成果，二者互不重叠。

## 文件清单

<table border="1" cellspacing="0" cellpadding="6">
  <thead>
    <tr><th>文件</th><th>对应申请文件</th><th>说明</th></tr>
  </thead>
  <tbody>
    <tr><td><a href="01-说明书摘要.md">01-说明书摘要.md</a></td><td>说明书摘要＋摘要附图</td><td>正文约 280 字（≤300 字要求），摘要附图为图 1 简化版（Mermaid）</td></tr>
    <tr><td><a href="02-权利要求书.md">02-权利要求书.md</a></td><td>权利要求书</td><td>16 项：方法独立权利要求 1 项＋从属 12 项＋系统／电子设备／存储介质各 1 项</td></tr>
    <tr><td><a href="03-说明书.md">03-说明书.md</a></td><td>说明书</td><td>技术领域／背景技术／发明内容／附图说明／具体实施方式（9 个实施例，表格均为 HTML）</td></tr>
    <tr><td><a href="04-说明书附图.md">04-说明书附图.md</a></td><td>说明书附图</td><td>图 1～图 8，全部为可渲染 Mermaid 源码</td></tr>
  </tbody>
</table>

## 技术方案与代码实现的对应关系

专利中每一项技术特征均有本仓库真实代码支撑，便于答复审查意见时举证：

<table border="1" cellspacing="0" cellpadding="6">
  <thead>
    <tr><th>专利技术特征</th><th>对应权利要求</th><th>代码位置</th></tr>
  </thead>
  <tbody>
    <tr>
      <td>动态能力→工具映射（名称净化、模式归一、风险别名归一、上限截断、代理工具闭包工厂）</td>
      <td>1、2、3</td>
      <td><code>app/agents/device_agent/mcp_tools.py</code>（<code>build_device_mcp_server</code>、<code>_sanitize</code>、<code>_normalize_risk</code>、<code>_flatten_tools</code>、<code>_make_proxy</code>）</td>
    </tr>
    <tr>
      <td>三级风险归类（能力声明→规则匹配→默认 write）</td>
      <td>1、3</td>
      <td><code>app/agents/device_agent/permissions.py</code>（<code>classify_risk</code>、<code>_match_glob</code>）</td>
    </tr>
    <tr>
      <td>权限代理器（per-run PermissionBroker、Future 阻塞/恢复、超时拒绝、运行结束关闭）</td>
      <td>1、4、5</td>
      <td><code>app/agents/device_agent/permissions.py</code>（<code>PermissionBroker</code>、<code>make_can_use_tool</code>）</td>
    </tr>
    <tr>
      <td>权限审批请求/裁决事件推送</td>
      <td>1、5</td>
      <td><code>app/agents/device_agent/permissions.py</code>（<code>_emit_resolved</code>、<code>_build_rationale</code>）＋<code>app/agents/device_agent/trace.py</code>（<code>TOOL_PERMISSION_REQUEST</code>/<code>RESOLVED</code>）</td>
    </tr>
    <tr>
      <td>协议版本自适应分发（v2 JSON 信封 / v1 文本信封 / 降级通知去重）</td>
      <td>1、6</td>
      <td><code>app/agents/device_agent/mcp_tools.py</code>（<code>default_dispatcher</code>、<code>_build_legacy_prompt</code>、<code>_extract_protocol_version</code>）</td>
    </tr>
    <tr>
      <td>后置校验钩子（信封解析、模式校验、截断、脱敏、通配拦截、结果替换）</td>
      <td>1、7、8、13</td>
      <td><code>app/agents/device_agent/post_tool_hook.py</code>（<code>build_post_tool_use_hook</code>、<code>_extract_envelope</code>、<code>_normalize_envelope</code>、<code>_validate_against_output_schema</code>、<code>_normalize_evidence</code>、<code>_truncate_text</code>）</td>
    </tr>
    <tr>
      <td>凭证脱敏（mask_tokens URL 正则 + mask_input 递归脱敏）</td>
      <td>8</td>
      <td><code>app/agents/log_analysis/trace.py</code>（<code>mask_tokens</code>、<code>mask_input</code>）被 <code>app/agents/device_agent/trace.py</code> 复用</td>
    </tr>
    <tr>
      <td>主动澄清提问（AskUserQuestion 工具、结构化问题/选项、共享 Broker、上限控制、超时策略）</td>
      <td>9、10</td>
      <td><code>app/agents/device_agent/clarification.py</code>（<code>make_ask_user_question_tool</code>、<code>build_clarification_mcp_server</code>、<code>_normalize_questions</code>、<code>_format_answers</code>）</td>
    </tr>
    <tr>
      <td>设备连接管理与状态持久化（WebSocket 注册/心跳/断线/删除、JSON 持久化/恢复）</td>
      <td>11</td>
      <td><code>app/services/device_link_service.py</code>（<code>DeviceLinkManager</code>、<code>register_device</code>、<code>mark_offline</code>、<code>_persist_devices</code>、<code>_restore_devices</code>）</td>
    </tr>
    <tr>
      <td>请求-响应 Future 匹配（send_prompt→pending→handle_prompt_result→resolve）</td>
      <td>12</td>
      <td><code>app/services/device_link_service.py</code>（<code>send_prompt</code>、<code>handle_prompt_result</code>、<code>_fail_pending_for_device</code>）</td>
    </tr>
    <tr>
      <td>DeviceAgent 主编排（工作区创建、技能物化、MCP server 组装、Broker 注册/注销、run_stream 全流程）</td>
      <td>1、14</td>
      <td><code>app/agents/device_agent/agent.py</code>（<code>DeviceAgent.run_stream</code>）</td>
    </tr>
    <tr>
      <td>WebSocket 消息协议契约（register/prompt/prompt_result/capabilities_update 等消息类型）</td>
      <td>11、12</td>
      <td><code>app/models/device_link.py</code>（<code>RegisterMessage</code>、<code>PromptEnvelope</code>、<code>PromptResultMessage</code>、<code>CapabilitiesUpdateMessage</code> 等 TypedDict/Pydantic 模型）</td>
    </tr>
    <tr>
      <td>用户偏好驱动的澄清工具可用性控制</td>
      <td>10</td>
      <td><code>app/agents/device_agent/agent.py</code>（<code>DeviceAgentContext.clarification_enabled/max_rounds/on_timeout</code>；run_stream 中条件注册澄清工具）</td>
    </tr>
  </tbody>
</table>

## 撰写口径说明

- 文档面向中国发明专利申请（CNIPA），按《专利法》《专利审查指南》对计算机程序类发明的要求，通篇以"技术问题—技术手段—技术效果"闭环表述，避免落入智力活动规则：权利要求锚定的是**动态工具生成机制、名称净化算法、三级风险归类算法、异步等待阻塞/恢复机制、信封解析与模式校验流程、UTF-8 安全截断算法、协议版本检测与分发逻辑、设备状态持久化与恢复机制**等技术特征及其可度量效果（审批请求数、上下文占用、凭证泄露防护、生效延迟）。
- 通篇使用中性技术术语（"大语言模型推理引擎""长连接通道""事件推送通道""外部工具协议"），未绑定任何第三方商业产品名称，避免商标问题并扩大保护范围。
- 所有表格为 HTML `<table>`，所有图为 Mermaid（按任务要求）。

## 提交前待办（需申请人/代理人确认）

1. **著录事项**：申请人、发明人、地址等信息需补填；建议委托专利代理机构做形式审查适配。
2. **附图格式**：Mermaid 需导出为黑白线条图（PNG/TIFF），并按规范标注"图 1"至"图 8"；摘要附图选图 1。
3. **查新检索**：建议就"AI Agent 设备工具调用""动态 MCP 工具映射""人机协同工具审批""LLM Agent IoT"方向做专利与非专利文献查新（重点关注 2023 年后的 AI Agent 框架类申请与物联网管控类申请），必要时收窄独立权利要求。
4. **保密审查**：如计划同时在境外申请，需先行办理向外申请专利保密审查（专利法第 19 条）。
5. **摘要字数**：当前摘要约 280 字，满足不超过 300 字的要求；如代理人调整措辞需复核。
6. **与第一篇专利的关系**：本专利与同目录下"分级技能包与分层提示词编排"专利从不同技术维度保护项目创新——前者保护知识组织与提示词编排，本篇保护设备交互与安全管控——可分别独立申请，不存在重复保护问题。
