## Context

当前 Skill 系统采用 Agent 维度的单层结构：`data/agent_skills/<agent_key>/store/<skill_name>/`。每个 Agent（log_analysis、project_expert、device_agent）有自己的 Skill 池，通过 `skills_service.py` 管理生命周期。运行时，Agent 根据用户查询的相关性评分选择最多 3 个 Skill，物化到临时 workspace 的 `.claude/skills/` 目录，由 Claude Agent SDK 自动发现。

系统已有完整的项目（ProjectRepo）概念，包含 project_code、repo_url 等字段，与 Agent 在 chat service 层通过 workspace 关联。但 Skill 选择与项目身份完全无关——所有项目共享同一组 Agent Skill。

本设计在现有 Agent Skill 之上增加一个 **项目维度**，使同一个 Agent 面对不同项目时能加载不同的领域知识。

## Goals / Non-Goals

**Goals:**
- 支持按项目管理独立的 Skill 集合，与 Agent Skill 并行存在
- Agent 运行时自动合并 Agent Skill 和当前项目的 Project Skill
- 复用现有 Skill 基础设施（zip 解包、SKILL.md 解析、相关性评分、物化机制）
- 提供 Admin API 和前端界面管理项目 Skill
- 完全向后兼容：未配置项目 Skill 时行为不变

**Non-Goals:**
- 不支持"全局 Skill"（跨所有 Agent + 所有项目共享）——当前 Agent Skill 已满足此需求
- 不修改 Claude Agent SDK 层面的 Skill 发现机制
- 不引入数据库存储 Skill 元数据（保持纯文件系统方案）
- 不支持项目 Skill 的 Agent 维度隔离（项目 Skill 对所有支持项目概念的 Agent 可见）
- 不调整 DeviceAgent 和 GeneralAgent——它们不具备项目上下文

## Decisions

### D1: 项目 Skill 存储与 Agent Skill 平行，使用独立目录树

**选择**：新增 `data/project_skills/<project_code>/` 目录树，与 `data/agent_skills/<agent_key>/` 并行。

**替代方案**：
- (A) 嵌套在 agent_skills 下：`data/agent_skills/<agent_key>/projects/<project_code>/` — 将项目 Skill 绑定到特定 Agent，限制灵活性
- (B) 嵌套在 project 下：`data/projects/<project_code>/skills/<agent_key>/` — 引入新的顶层 data 结构，增加管理复杂度

**理由**：项目 Skill 的核心身份是"属于某个项目"而非"属于某个 Agent"。同一个项目 Skill（如"XX 项目部署流程"）对 log_analysis 和 project_expert 都有价值。平行目录树使两类 Skill 的管理逻辑正交、互不影响，且 `config.py` 只需新增一个 `project_skills_data_dir` 配置项。

### D2: 项目 Skill 不做 Agent 维度隔离

**选择**：项目 Skill 对所有支持项目上下文的 Agent（log_analysis、project_expert）统一可见，不做 per-agent 隔离。

**替代方案**：每个项目 Skill 可配置适用的 Agent 列表。

**理由**：
- 项目级知识（架构、调试模式、部署流程）通常对多个 Agent 都有价值
- 避免管理复杂度（管理员不需要为每个 Skill 选择适用 Agent）
- 已有相关性评分机制会自动过滤无关 Skill，无需人工指定

### D3: 物化阶段合并两类 Skill，Project Skill 优先

**选择**：在 Agent 运行前，依次物化 Agent Skill 和 Project Skill 到同一个 `.claude/skills/` 目录。若同名冲突，Project Skill 覆盖 Agent Skill。

**替代方案**：
- (A) 命名空间前缀（如 `project--<name>`）避免冲突 — 增加命名复杂度，SDK 侧可见前缀噪声
- (B) Agent Skill 优先 — 不合理，项目特定知识应覆盖通用知识

**理由**：Project Skill 更具体（针对特定项目），应覆盖同名的通用 Agent Skill。物化到同一个 `.claude/skills/` 目录确保 SDK 无需任何改动即可发现所有 Skill。

### D4: 合并相关性评分，统一 max_skills 预算

**选择**：将 Agent Skill 和 Project Skill 放入同一个候选池做相关性评分，统一 `max_skills` 上限（默认 3→5，因为候选池更大了）。

**替代方案**：
- (A) 分别评分、分别限额（Agent 3 + Project 3）— 可能物化过多 Skill，增加 SDK 上下文负担
- (B) 分别评分、共享限额 — 两阶段评分之间无法比较分数

**理由**：统一评分池使最相关的 Skill 胜出，不论来源。提升 max_skills 到 5 是因为引入项目维度后有效候选更多，但仍需控制总数避免 context 膨胀。

### D5: skills_service 内部抽取公共 SkillStore 逻辑

**选择**：在 `skills_service.py` 内部将路径计算、注册表 IO、安装/删除等操作抽取为接受 `base_dir` 参数的内部函数，Agent Skill 和 Project Skill 各调用同一套逻辑但传入不同的 base_dir。

**替代方案**：复制一份完整的 project_skills_service.py — 大量重复代码

**理由**：两类 Skill 的生命周期完全相同（zip 解包 → SKILL.md 解析 → 注册表管理 → 物化），差异仅在存储路径。抽取公共逻辑使核心代码只维护一份，减少 bug 面。

### D6: Admin API 挂载在 project-repos 资源下

**选择**：`/admin/project-repos/{project_code}/skills` 系列端点。

**替代方案**：独立的 `/admin/project-skills/{project_code}/skills` — 增加 API surface 但无实际收益

**理由**：项目 Skill 逻辑上从属于项目，挂载在 project-repos 资源下符合 REST 资源建模惯例，前端路由也自然嵌套在项目详情页。

## Risks / Trade-offs

- **Skill 数量膨胀**：N 个项目 × M 个 Skill → 磁盘占用增长。→ 缓解：单 Skill zip ≤ 50MiB 限制不变；管理员可按项目禁用/删除。
- **相关性评分精度**：合并评分池后，评分算法可能在 Agent Skill 和 Project Skill 之间做出次优选择。→ 缓解：Project Skill 的 name/description 天然包含项目标识词，评分自然偏向匹配的项目。
- **project_code 变更**：若管理员修改了项目的 project_code，对应的 `data/project_skills/<old_code>/` 会孤立。→ 缓解：project_code 在现有系统中不可修改（CreateProjectRepoRequest 创建后不出现在 UpdateProjectRepoRequest 中），风险可控。
- **并发物化冲突**：同一项目的多个会话同时物化 Skill 到各自 workspace，由于使用 symlink 且 workspace 隔离，不存在竞争条件。→ 无需额外缓解。
