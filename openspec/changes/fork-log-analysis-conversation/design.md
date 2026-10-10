## Context

日志分析轮次位于共享日志 metadata，个人聊天位于 ChatSession/ChatMessage，Agent 上下文注册文件按会话绑定 owner_user_id。日志详情允许阅读共享日志；Fork 必须登录并沿用该读取边界。

## Goals / Non-Goals

**Goals:** 复制详情页已保存轮次，独立个人会话、目录和后续结果；刷新后恢复 Agent 和项目。

**Non-Goals:** 公共分享页 Fork、修改原对话、继承 SDK 运行 ID、生产部署。

## Decisions

- POST /api/v1/logs/{log_id}/analysis/fork 使用 get_current_user；通过既有日志详情及附件组解析获取数据，未知/删除日志返回 404，空分析返回 422。
- 从原附件重新 prepare/prepare_many，创建 UUID 目录和 task.json，项目从日志记录解析。独立 repo/ 首轮由 Agent 正常克隆，避免复制原用户可变目录、凭据或运行状态。
- 按轮复制 user/ai 消息，兼容 answer/summary 和旧 final_result/content 格式；不复制原 owner、trace、运行 ID。
- 注册新上下文含 forked_from_log_id 和当前 owner。Fork 追问只写个人历史，禁止写共享日志及自动 BugFix。
- 消息 API 返回经过所有权校验的 workspace_context，仅含 Agent、项目、是否已有日志上下文；前端刷新恢复选择。
- DB 与文件注册失败时回滚并清理本次目录。耗时附件解压在线程执行。

## Risks / Trade-offs

- [附件丢失/解压失败] → 返回可操作双语错误，清理新目录并回滚；不创建空会话。
- [复制时原分析仍运行] → 只复制调用时已持久化轮次，不接管或等待原任务。
- [磁盘占用增加] → 使用已有解压额度；每次 Fork 获得完整独立副本。

## Migration Plan

无需数据库迁移；新增可选响应字段向后兼容。本地 Docker 重建验证。
