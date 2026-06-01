## Context

`GeneralAgent` 是一个**无工具、单轮、小/快模型**的对话 Agent，被设计成"未选择任何专门 Agent 时的默认兜底"。它已经能接收会话历史，但只能在"超范围"时被动列模块，无法根据用户最新输入做结构化的 Agent 路由引导。本设计在**不引入工具、不破坏现有事件契约**的前提下，让它输出一个结构化的"建议 Agent"信号，并由前端据此强引导用户选择。

约束：
- 不能给 GeneralAgent 加工具（会触发 max_turns 反复检索的老问题，见 agent.py 顶部注释与 `_DISABLED_TOOLS`）。
- 小/快模型能力有限，结构化输出必须**简单、容错**。
- 现有 SSE 事件契约（`agent-trace-stream`）只能**新增可选字段**，不能改既有字段。

## Goals / Non-Goals

**Goals**
- 用户在已有窗口未选 Agent 续聊时，上下文可靠传入 GeneralAgent（固化为 spec）。
- GeneralAgent 能按用户最新输入判定意图，并对属于专门 Agent 的请求明确要求"必须先选中对应 Agent"。
- 把建议以结构化字段 `suggested_agent_type` 传到前端，支持醒目提示 + 一键切换。

**Non-Goals**
- 不做自动切换/自动代答（仍由用户显式选择 Agent）。
- 不改 GeneralAgent 的"仅限系统使用问题"直答范围。
- 不引入新的意图分类模型或服务；意图判定由 GeneralAgent 的提示词在同一轮内完成。

## Decision 1：用"末行标记"承载结构化建议，而非工具/JSON 模式

让模型在回复**最后一行**单独输出 `[[SUGGESTED_AGENT:<key>]]`，`key ∈ {device, log_analysis, package_search, project_expert, none}`。

- **为什么不用工具/函数调用**：GeneralAgent 明确禁用全部工具（避免 max_turns 崩溃），不能引入工具来返回结构化结果。
- **为什么不用整体 JSON**：小/快模型直接产出严格 JSON 容易破坏正文渲染、易出格式错误。末行标记对模型最友好，且解析容错性强。
- **解析**：`_extract_suggested_agent(text)` 用大小写不敏感正则匹配**最后一个**标记，校验 key 合法性（非法或 `none` → `None`），并从正文中**剥离所有标记**、清理尾随空白后返回 `(clean_text, suggested)`。即便模型把标记写在中间或重复输出，也能正确剥离。
- **兜底**：模型完全没给标记时，`suggested = None`，正文原样展示——退化为现有行为，安全。

## Decision 2：建议 key 与前端 Agent 的映射

| 建议 key (`suggested_agent_type`) | 含义 | 前端动作 |
| --- | --- | --- |
| `device` | 设备指令 / 联动 / 远程操作 | 引导用户使用「设备操作」入口（设备操作走独立下拉，非 AgentOption） |
| `log_analysis` | 日志分析 / 排查报错 | 一键 `setTargetAgent(logAnalysisAgentOption)` |
| `package_search` | 包检索 / 版本 / 依赖 | 一键 `setTargetAgent(packageAgentOption)` |
| `project_expert` | 项目源码答疑 | 一键 `setTargetAgent(projectExpertAgentOption)` |
| `none` / 缺省 | 无需切换 | 不展示提示条 |

设备操作在前端是独立下拉（见 commit `e8742d9`），不属于 `AgentOption` 联合类型，因此 `device` 建议只给文字引导，不做一键 `setTargetAgent`。

## Decision 3：字段在事件链路上的透传点

```
GeneralAgent.run_stream
  └─ run_complete { final_text(已剥离), suggested_agent_type }
        │  （chat_run_service._run_general_job 把 ev 的非 type 键整体拷进 SSE run_complete 帧 → 自动带上）
        ├─ job.suggested_agent_type = ev["suggested_agent_type"]
        └─ done { ..., suggested_agent_type }   ← 手工构造，需显式加字段
ai_chat_service.chat (非流式)
  └─ 从 run_complete 事件读取 → ChatResponse.suggested_agent_type
ai_chat_service.chat_stream (legacy 直推路径)
  └─ done 帧显式加 suggested_agent_type
```

`ChatRunJob` 新增 `suggested_agent_type: Optional[str] = None`，并纳入 `_snapshot_payload`，使断线重连 / `/runs/{run_id}` 快照也能恢复建议。

前端 `conversationRuns.ts`：`ConversationState` 新增 `suggestedAgentType: string | null`；在 `run_complete` 与 `done` 两处读取 `payload.suggested_agent_type`（done 为权威），新 run 开始时重置为 `null`。

## Risks / Trade-offs

- **模型不稳定输出标记**：小/快模型偶发漏标记或写错 key。缓解：解析容错（漏标记=不提示，错 key=按 none 处理），且即使没有结构化提示，正文里仍会有自然语言引导。
- **标记泄漏到用户可见文本**：缓解：剥离逻辑覆盖"末行/中间/重复"多种位置，并有单测固定。
- **误判意图**：可能把"如何使用设备操作功能"误判为 `device` 任务。缓解：提示词区分"询问怎么用"(A 类，直答, none) 与"要求执行任务"(B 类, 给建议)；前端提示条是**非阻塞**的引导而非强制拦截发送，用户仍可继续问。

## Migration / Rollout

纯增量、可灰度：后端字段缺省 `null`，旧前端忽略未知字段照常工作；新前端在字段为空时不展示提示条，行为与今天一致。无数据迁移。
