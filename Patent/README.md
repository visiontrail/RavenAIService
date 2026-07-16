# Patent — 发明专利申请文档

本目录为基于 RavenAIService 项目实际实现撰写的中国发明专利申请文档草案集，从不同技术维度保护本项目的核心创新成果。

## 专利清单

<table border="1" cellspacing="0" cellpadding="6">
  <thead>
    <tr><th>序号</th><th>发明名称</th><th>技术维度</th><th>目录</th><th>权利要求数</th><th>附图数</th></tr>
  </thead>
  <tbody>
    <tr>
      <td>一</td>
      <td>一种基于分级技能包与分层提示词编排的多智能体服务方法、系统、电子设备及存储介质</td>
      <td>知识组织与提示词编排</td>
      <td>本目录根（<code>01-</code>~<code>04-</code> 文件）</td>
      <td>15 项</td>
      <td>图 1～图 7</td>
    </tr>
    <tr>
      <td>二</td>
      <td>一种基于动态能力映射与人机协同权限管控的AI智能体远程设备交互方法、系统、电子设备及存储介质</td>
      <td>设备交互与安全管控</td>
      <td><a href="02-动态能力映射与人机协同设备交互/">02-动态能力映射与人机协同设备交互/</a></td>
      <td>16 项</td>
      <td>图 1～图 8</td>
    </tr>
  </tbody>
</table>

两篇专利从不同技术维度保护项目创新——专利一保护多智能体的知识组织（技能包分级注册/物化/按需加载）与提示词编排（分层拼接/播种/热更新），专利二保护AI智能体与远程设备交互中的安全管控（动态能力映射/三级风险归类/人机协同权限管控/后置校验/协议适配/澄清提问）——可分别独立申请，不存在重复保护问题。

---

## 专利一：分级技能包与分层提示词编排

**发明名称：一种基于分级技能包与分层提示词编排的多智能体服务方法、系统、电子设备及存储介质**

围绕本项目最具独创性的两条主线：**分级 Skill（智能体级/项目级技能包的注册、校验、合并物化与按需加载）**与**分层提示词拼接（基础层/项目层/运行时层的确定性编排、差异化播种与热更新）**。

### 文件清单

<table border="1" cellspacing="0" cellpadding="6">
  <thead>
    <tr><th>文件</th><th>对应申请文件</th><th>说明</th></tr>
  </thead>
  <tbody>
    <tr><td><a href="01-说明书摘要.md">01-说明书摘要.md</a></td><td>说明书摘要＋摘要附图</td><td>正文约 290 字（≤300 字要求），摘要附图为图 1 简化版（Mermaid）</td></tr>
    <tr><td><a href="02-权利要求书.md">02-权利要求书.md</a></td><td>权利要求书</td><td>15 项：方法独立权利要求 1 项＋从属 11 项＋系统／电子设备／存储介质各 1 项</td></tr>
    <tr><td><a href="03-说明书.md">03-说明书.md</a></td><td>说明书</td><td>技术领域／背景技术／发明内容／附图说明／具体实施方式（7 个实施例，表格均为 HTML）</td></tr>
    <tr><td><a href="04-说明书附图.md">04-说明书附图.md</a></td><td>说明书附图</td><td>图 1～图 7，全部为可渲染 Mermaid 源码</td></tr>
  </tbody>
</table>

### 技术方案与代码实现的对应关系

专利中每一项技术特征均有本仓库真实代码支撑，便于答复审查意见时举证：

<table border="1" cellspacing="0" cellpadding="6">
  <thead>
    <tr><th>专利技术特征</th><th>对应权利要求</th><th>代码位置</th></tr>
  </thead>
  <tbody>
    <tr><td>两级技能注册表＋安全校验（zip 三重阈值、目录穿越防护、frontmatter 校验）</td><td>1、6</td><td><code>app/services/skills_service.py</code>（<code>_safe_extract_zip</code>、<code>_parse_skill_frontmatter</code>、agent/project 双路径 API）</td></tr>
    <tr><td>合并物化（智能体级在先、项目级同名覆盖；符号链接优先、复制回退）</td><td>1、5</td><td><code>skills_service.materialize_enabled_skills</code>、<code>enabled_skill_overviews</code></td></tr>
    <tr><td>技能可用性菜单段（名称＋描述菜单、按需加载规则、事实校验规则、输出契约重申）</td><td>1、7、12</td><td><code>app/agents/skill_prompting.py</code>（<code>build_skill_availability_prompt</code>、<code>build_plain_text_skill_answer_fields</code>）</td></tr>
    <tr><td>项目级附加段（专属层→共享层合并、优先级声明、路径白名单）</td><td>2</td><td><code>app/services/project_prompt_service.py</code>（<code>build_project_prompt_addendum</code>、<code>validate_agent_key</code>）</td></tr>
    <tr><td>差异化幂等播种（code_workflow / no_repo_workflow 双变体、变体切换换轨、人工定制保护）</td><td>3、4</td><td><code>project_prompt_service.seed_default_project_prompt</code>、<code>seed_project_default_prompts</code></td></tr>
    <tr><td>多语言基础层与默认语言回退、回复语言指令段末位拼接</td><td>8</td><td><code>app/i18n/prompts.py</code>（<code>select_localized_body</code>、<code>response_language_directive</code>）＋各 agent <code>prompts.py</code></td></tr>
    <tr><td>热更新（校验和乐观并发、原子写、缓存失效）与条目级编辑白名单</td><td>9</td><td><code>app/services/prompts_config_service.py</code>（<code>update_prompts_config</code>、<code>update_prompt_entries</code>、<code>_invalidate_prompt_caches</code>）</td></tr>
    <tr><td>拼接预览（基础层＋项目附加段、逐层元数据、排除运行时动态段）</td><td>10</td><td><code>project_prompt_service.build_project_system_prompt_preview</code></td></tr>
    <tr><td>运行时适配（无仓库约束段、MCP 能力探测与工具过滤）</td><td>11</td><td><code>app/agents/project_expert/agent.py</code>（run 流程 142–294 行）、<code>log_analysis/agent.py</code>、<code>package_search/agent.py</code></td></tr>
    <tr><td>七层段确定性拼接全流程</td><td>1、13</td><td><code>app/agents/project_expert/agent.py</code>（基础层→工作区段→约束段→项目附加段→技能菜单段→语言指令段→<code>build_options</code>）</td></tr>
  </tbody>
</table>

### 撰写口径说明

- 文档面向中国发明专利申请（CNIPA），按《专利法》《专利审查指南》对计算机程序类发明的要求，通篇以"技术问题—技术手段—技术效果"闭环表述，避免落入智力活动规则：权利要求锚定的是**存储结构、物化机制、拼接顺序、并发控制、缓存失效、路径安全校验**等技术特征及其可度量效果（上下文占用、I/O 开销、生效延迟）。
- 通篇使用中性技术术语（"大语言模型推理引擎""技能加载工具""外部工具协议"），未绑定任何第三方商业产品名称，避免商标问题并扩大保护范围。
- 所有表格为 HTML `<table>`，所有图为 Mermaid（按任务要求）。

### 提交前待办（需申请人/代理人确认）

1. **著录事项**：申请人、发明人、地址等信息需补填；建议委托专利代理机构做形式审查适配。
2. **附图格式**：Mermaid 需导出为黑白线条图（PNG/TIFF），并按规范标注"图 1"至"图 7"；摘要附图选图 1。
3. **查新检索**：建议就"分层提示词拼接""技能包按需加载/物化""LLM Agent Skill"方向做专利与非专利文献查新（重点关注 2023 年后的 Agent 框架类申请），必要时收窄独立权利要求。
4. **保密审查**：如计划同时在境外申请，需先行办理向外申请专利保密审查（专利法第 19 条）。
5. **摘要字数**：当前摘要约 290 字，满足不超过 300 字的要求；如代理人调整措辞需复核。

---

## 专利二：动态能力映射与人机协同设备交互

详见 [02-动态能力映射与人机协同设备交互/README.md](02-动态能力映射与人机协同设备交互/README.md)。
