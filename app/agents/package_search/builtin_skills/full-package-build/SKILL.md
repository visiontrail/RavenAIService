---
name: full-package-build
description: Classify uploaded software components and build a confirmed whole-package TGZ. Use whenever the user uploads component files or archives and asks to assemble, package, upgrade, release, or create an LX10/whole software package.
---

# 整包打包

本 Skill 负责“证据初判 → 全量人工确认 → 确定性构建”。项目、组件、FileAttr、识别证据、提取方式和输出名全部来自 `references/package-projects.json`；同名 Agent/项目 Skill 可以用新版 JSON 覆盖内置规则。

## 不可绕过的门禁

- 分类结论只是建议，不是授权。
- 每次打包都必须使用服务端强制反问卡；用户关闭普通反问偏好也不例外。
- 卡片必须确认项目、整包版本、整包类型，并逐一确认每个 `upload_id` 的组件映射或“排除此文件”。一个文件可以多选多个组件。
- Patch/预制包、recognition-only 和未知文件也必须显示并由用户明确排除；不得静默忽略。
- 缺答、取消、超时、catalog 改变、文件路径/大小/SHA-256 改变或确认签名失效时，禁止构建和上传。
- 不使用 Bash、Write、Edit 或仓库写工具替代专用 builder。

## 工作流

1. 向用户说明初判的项目、每个文件的候选组件、置信度及关键证据。文件名与归档成员冲突时同时展示两边证据。
2. 等待服务端强制反问完成。不要声称“已确认”，除非当前 workspace 已存在服务端签名的 confirmed plan。
3. 仅在确认完成后调用 `mcp__package_builder__BuildConfirmedFullPackage`。该工具无参数；不得传入自选路径、项目或映射。
4. 工具拒绝时，准确说明需要重新确认的原因，不要尝试其它写文件方式。
5. 工具成功后，汇总项目、版本、组件、SHA-256；仓库发布及对话下载链接由服务端基于权威 build result 补充。

## LX10 默认规则边界

- 支持 FileAttr 301/302/303/307/308/313/315/401/403/404/405/406，以及 Satellite MCP Server 的 801。
- S-GNB ZIP 可同时提供 CUCP、CUUP、DU；构建时只安全解压一次。
- BPO master 同时命中 313 与 315，必须让用户选择，不能自动消歧。
- 已含 `si.ini` 的 Satellite Patch 是预制包，不能再次嵌套。
- `sct_sf2`、`bpo_sf2`、`sct_m3` 仅识别；在 catalog 未补齐正式 FileAttr/输出格式前不能发布。

## 扩展 catalog

新增项目或组件优先编辑 JSON，不改分类器代码。仅使用已有 vocabulary：recognition rule（filename、relative_path、extension、magic、archive_member）、version rule、`copy`、`direct_include`、`extract_match`。所有正则、属性、输出名和冲突会在反问前校验；配置无效时停止并报告 catalog 错误。
