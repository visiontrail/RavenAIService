## 1. GeneralAgent 提示词与结构化建议

- [x] 1.1 在 [`app/agents/general_agent/agent.py`](../../../app/agents/general_agent/agent.py) 重写 `SYSTEM_PROMPT`：补全四个专门 Agent（device/log_analysis/package_search/project_expert）职责说明；定义 A/B/C 三类判定与回应规则；要求回复最后一行输出 `[[SUGGESTED_AGENT:<key>]]`（key ∈ device|log_analysis|package_search|project_expert|none）
- [x] 1.2 更新 `_FALLBACK_ANSWER`，补全「项目专家」引导
- [x] 1.3 新增常量 `VALID_SUGGESTED_AGENTS` 与解析函数 `_extract_suggested_agent(text) -> (clean_text, suggested|None)`：大小写不敏感匹配最后一个标记、校验 key、剥离全部标记并清理尾随空白、none/非法→None
- [x] 1.4 `run_stream`：对 `answer_text` 调用 `_extract_suggested_agent`，用清理后的文本作为 `final_text`，在 `run_complete` 事件加 `suggested_agent_type`（含兜底/超时分支保持 `None`）
- [x] 1.5 `run()` 保持 `(events, final_text, model)` 返回签名不变（建议从 events 中读取，无需改签名）

## 2. 服务层透传

- [x] 2.1 [`app/services/chat_run_service.py`](../../../app/services/chat_run_service.py)：`ChatRunJob` 新增 `suggested_agent_type: Optional[str] = None`
- [x] 2.2 `_run_general_job`：捕获 `run_complete` 事件的 `suggested_agent_type` 写入 `job`；在手工构造的 `done` 帧加入该字段
- [x] 2.3 `_snapshot_payload` 纳入 `suggested_agent_type`（断线重连/回放可恢复）
- [x] 2.4 [`app/services/ai_chat_service.py`](../../../app/services/ai_chat_service.py)：`chat` 从 run_complete 事件读取并回填 `ChatResponse.suggested_agent_type`；`chat_stream`（legacy 直推）在 `done` 帧加入该字段
- [x] 2.5 [`app/models/chat.py`](../../../app/models/chat.py)：`ChatResponse` 新增 `suggested_agent_type: Optional[str] = None`

## 3. 前端结构化提示与一键切换

- [x] 3.1 [`frontend/src/stores/conversationRuns.ts`](../../../frontend/src/stores/conversationRuns.ts)：`ConversationState` 新增 `suggestedAgentType: string | null`；新 run 开始时重置；在 `run_complete` 与 `done` 处理分支读取 `payload.suggested_agent_type`（done 权威）
- [x] 3.2 [`frontend/src/views/AIChat.vue`](../../../frontend/src/views/AIChat.vue)：当 `suggestedAgentType` 非空时展示醒目提示条（"该请求需使用 XX，请先选择对应 Agent"）；log_analysis/package_search/project_expert 提供一键 `setTargetAgent`，device 给文字引导
- [x] 3.3 key→展示名/动作映射集中定义，未知 key 安全忽略

## 4. 测试与校验

- [x] 4.1 [`tests/agents/general_agent/test_agent.py`](../../../tests/agents/general_agent/test_agent.py)：`_extract_suggested_agent` 单测（末行/中间/重复/缺失/非法/none 各分支，断言正文已剥离）
- [x] 4.2 run_stream 用例：B 类标记 → `run_complete.suggested_agent_type == 对应key` 且 `final_text` 不含标记；A/C 类 → `None`
- [x] 4.3 SYSTEM_PROMPT 断言：包含四个 Agent 关键词（设备操作/日志分析/检索包/项目专家）与标记格式说明
- [x] 4.4 service 透传断言：`done` 帧 / `ChatResponse` 携带 `suggested_agent_type`；快照含该字段
- [x] 4.5 回归：未选 Agent 续聊仍走 general、历史注入不变；`openspec validate general-agent-suggest-specialist` 通过
