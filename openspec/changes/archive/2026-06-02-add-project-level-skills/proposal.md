## Why

Agent Skills 当前仅按 Agent 维度组织（`data/agent_skills/<agent_key>/`），所有项目共享同一组 Skill。但不同项目的技术栈、架构、调试模式差异巨大——Android 项目需要 logcat 分析 Skill，后端项目需要部署流程 Skill，嵌入式项目需要基带日志解读 Skill。将 Skill 粒度从"Agent 级"细化到"项目 + Agent 级"，可以让 Agent 在运行时获得更精准的领域知识，减少无关 Skill 干扰，提升分析质量。

## What Changes

- 新增 **项目级 Skill 存储维度**：在 `data/project_skills/<project_code>/` 下管理每个项目独有的 Skill，与现有 `data/agent_skills/` 并行存在
- **扩展 `skills_service.py`**：新增 project skill 的安装、列表、启用/禁用、删除、物化等 API，复用现有的 zip 解包、SKILL.md 解析、相关性评分等核心逻辑
- **扩展 Agent 物化流程**：在 `ProjectExpertAgent` 和 `LogAnalysisAgent` 的 skill 物化阶段，除加载 agent-level skill 外，额外加载当前项目的 project-level skill 到同一个 `.claude/skills/` 目录
- 新增 **Admin API 端点**：`/admin/project-repos/{project_code}/skills` 系列，提供项目级 Skill 的 CRUD 管理
- 新增 **前端项目 Skill 管理界面**：在项目详情页增加 Skill 管理 Tab，复用现有 Agent Skill 管理组件的交互模式

## Capabilities

### New Capabilities
- `project-skill-storage`: 项目级 Skill 的磁盘存储布局、注册表管理、安装/删除/启用禁用生命周期
- `project-skill-materialization`: Agent 运行时合并 agent-level 和 project-level skill 的物化逻辑，包括名称冲突处理和合并相关性评分
- `project-skill-admin-api`: 项目级 Skill 管理的 REST API 端点（上传、列表、启用/禁用、删除、文件预览）
- `project-skill-admin-ui`: 前端项目 Skill 管理界面（在项目详情中管理 Skill）

### Modified Capabilities
- `log-analysis-agent`: Agent 运行时除加载自身 skill 外，当存在 project_code 时额外加载项目 skill
- `project-expert-agent`: Agent 运行时除加载自身 skill 外，当存在 project_code 时额外加载项目 skill

## Impact

- **后端代码**：`app/services/skills_service.py`（核心扩展）、`app/agents/log_analysis/agent.py`、`app/agents/project_expert/agent.py`（物化调用点）、`app/api/admin.py`（新端点）
- **前端代码**：新增项目 Skill 管理 Vue 组件，路由注册，Admin 导航扩展
- **存储**：新增 `data/project_skills/` 目录树（纯文件系统，无数据库迁移）
- **API 契约**：新增 `/admin/project-repos/{project_code}/skills` 系列端点，不影响现有 agent skill API
- **向后兼容**：完全向后兼容——无项目 skill 时行为与现在一致；现有 agent skill 管理不受影响
