## ADDED Requirements

### Requirement: 最终答复正文增量渲染

主对话框（`AIChat.vue` / `conversationRuns.ts`）SHALL 在收到 `answer_delta` 事件时，将其 `text_chunk` 增量追加到当前轮次 assistant 消息气泡的正文中，使最终答复逐字呈现，而非在 `run_complete` 一次性整段渲染。

首条 `answer_delta` 到达时 MUST 清除"正在思考..."占位文案再开始追加。`answer_delta` 必须按 `seq` 升序消费，重复 `seq` MUST 被丢弃。

收到 `run_complete` 时，若 `final_text` 与已累积的增量正文不一致，前端 MUST 以 `final_text` 为权威全文做最终覆盖校正（保证与持久化 / 脱敏结果一致）。当本轮未收到任何 `answer_delta`（例如 provider 降级）时，前端 MUST 回退到以 `run_complete.final_text` 整段渲染，行为与改造前一致。

#### Scenario: 答复逐字呈现

- **WHEN** 某轮对话先后到达 `answer_delta{text_chunk:"根据"}`、`answer_delta{text_chunk:"日志分析，"}`、`answer_delta{text_chunk:"根因是…"}`
- **THEN** 消息气泡正文 MUST 随每条 delta 增量增长（`根据` → `根据日志分析，` → `根据日志分析，根因是…`），首条到达时"正在思考..."占位 MUST 已消失

#### Scenario: run_complete 收尾校正

- **WHEN** 增量累积正文与 `run_complete.final_text` 存在差异（如末尾缺段或脱敏不一致）
- **THEN** 前端 MUST 以 `final_text` 覆盖气泡正文，最终展示与持久化全文一致

#### Scenario: provider 降级回退整段渲染

- **WHEN** 本轮未收到任何 `answer_delta`，仅收到 `run_complete{final_text}`
- **THEN** 消息气泡 MUST 直接以 `final_text` 整段渲染，不出现空白或异常占位

#### Scenario: answer_delta 去重

- **WHEN** 因重连重放，`answer_delta` 以含重复 seq 的顺序到达
- **THEN** 前端 MUST 按 seq 去重，渲染出的答复正文 MUST 无重复字符
