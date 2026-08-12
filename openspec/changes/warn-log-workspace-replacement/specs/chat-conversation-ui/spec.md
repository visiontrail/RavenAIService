## ADDED Requirements

### Requirement: 日志工作区替换前提供明确确认与分流

当前日志分析会话已经成功关联日志附件时，前端 SHALL 在同一 `session_id` 再次提交一个或多个日志附件之前显示确认提示。提示 MUST 明确说明继续操作会替换当前 Agent 日志工作区、AI 后续无法读取此前上传的日志，同时原日志列表记录与下载不受影响。提示 MUST 提供继续替换、新建对话和关闭三种结果；新建对话 MUST 保留本轮待发送附件但 MUST NOT 自动发送。提示还 MUST 说明：独立分析应使用新对话，关联分析多份日志则必须在新对话的同一轮上传全部相关附件。

#### Scenario: 首次上传不显示替换提示

- **WHEN** 当前 session 尚未成功关联任何日志附件
- **AND** 用户在日志分析模式选择一份或多份日志并发送
- **THEN** 前端 MUST 直接创建日志分析 run
- **AND** MUST NOT 显示工作区替换提示

#### Scenario: 同一 session 再次上传时提示

- **WHEN** 当前 session 已经收到一次 `log_analysis_context` 或持久化历史包含日志附件标记
- **AND** 用户再次选择日志附件并发送
- **THEN** 前端 MUST 在创建 run 之前显示工作区替换提示
- **AND** 提示 MUST 说明此前日志不再对 AI 可见但日志列表和下载不受影响

#### Scenario: 用户确认继续替换

- **WHEN** 工作区替换提示已显示
- **AND** 用户选择继续并替换
- **THEN** 前端 SHALL 使用当前 session 和本轮附件创建日志分析 run
- **AND** 后续发送流程保持不变

#### Scenario: 用户关闭提示

- **WHEN** 工作区替换提示已显示
- **AND** 用户关闭提示
- **THEN** 前端 MUST NOT 创建 run
- **AND** MUST 保留输入文本、附件和项目选择

#### Scenario: 用户选择新建对话

- **WHEN** 工作区替换提示已显示
- **AND** 用户选择新建对话
- **THEN** 前端 SHALL 切换到一个尚未发送的新对话
- **AND** SHALL 保留本轮待发送日志附件和项目选择
- **AND** MUST NOT 自动创建 run
- **AND** 提示文字 MUST 指导用户在需要关联分析时补齐全部相关附件后再发送

#### Scenario: 非替换操作不提示

- **WHEN** 用户仅发送日志分析追问而没有选择新日志附件，或使用其他 Agent，或仅附加图片
- **THEN** 前端 MUST NOT 显示日志工作区替换提示

#### Scenario: 会话状态相互隔离

- **WHEN** session A 已经关联日志工作区而 session B 尚未关联
- **AND** 用户在 session B 首次上传日志附件
- **THEN** 前端 MUST NOT 因 session A 的状态对 session B 显示替换提示
