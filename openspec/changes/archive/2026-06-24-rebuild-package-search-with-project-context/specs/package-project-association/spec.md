## ADDED Requirements

### Requirement: 包元数据携带项目关联字段 projectCode
包元数据 SHALL 包含 `projectCode` 字段，其取值为项目仓库注册表（`project_repo`）中某条记录的 `project_code`，或空字符串表示"未关联项目"。`RavenPackageService.PACKAGE_TYPES` 硬编码枚举 MUST 被移除，系统 MUST NOT 在任何新写入路径中生成 `packageType` 的新值。`PackageBrief` 投影 MUST 以 `projectCode` 取代 `packageType` 字段。

#### Scenario: 新上传的包记录项目关联
- **WHEN** 客户端上传一个包并指定 `projectCode="demo-proj"`（该项目已注册且启用）
- **THEN** 持久化后的包元数据 MUST 包含 `projectCode="demo-proj"`，且 MUST NOT 依据文件名推断生成任何包类型值

#### Scenario: PackageBrief 字段最小化（项目化后）
- **WHEN** 任何检索工具或 API 返回 `PackageBrief` 形式的 items
- **THEN** 每个对象 MUST 仅包含 `id, name, version, projectCode, isPatch, createdAt, components, tags, size` 字段（不含 sha256、不含磁盘 path）

### Requirement: 存量包元数据惰性迁移
`RavenPackageService` 读取包元数据时 SHALL 对缺少 `projectCode` 的旧记录做幂等规范化：`projectCode` 取旧 `packageType` 的值（缺失则为空字符串），原始 `packageType` 键 MUST 保留不删除（保障旧版本服务回滚后仍可读取同一份元数据文件）。规范化结果在下一次写操作时随元数据文件一并落盘；读取路径 MUST NOT 仅为迁移而主动写文件。

#### Scenario: 旧记录读取时自动获得 projectCode
- **WHEN** 元数据文件中存在一条仅含 `packageType="lingxi-10"`、无 `projectCode` 的旧记录被读取
- **THEN** 服务返回的包对象 MUST 含 `projectCode="lingxi-10"`，且原 `packageType` 键仍存在于元数据中

#### Scenario: 未匹配注册项目的包标记为未关联
- **WHEN** 某包的 `projectCode` 在项目仓库注册表中不存在对应 `project_code`
- **THEN** 包管理列表 API 与前端 MUST 将其呈现为"未关联项目"状态，且该包 MUST 可通过"未关联"筛选条件被检出

#### Scenario: 回滚兼容
- **WHEN** 部署回滚到本变更之前的版本并读取已被新版本写过的元数据文件
- **THEN** 旧版本服务 MUST 仍能按原 `packageType` 键正常加载全部包记录

### Requirement: 上传 API 以已注册项目为必填关联
`POST /upload` 与 `POST /upload/batch` SHALL 以 `projectCode` 表单字段取代 `packageType` 字段。服务端 MUST 校验 `projectCode` 对应的项目在注册表中存在且 `enabled=true`，校验失败 MUST 返回 HTTP 400 并说明原因；`POST /packages/scan` 扫描出的孤儿文件 MUST 以空 `projectCode`（未关联）入库，MUST NOT 凭文件名猜测项目。

#### Scenario: 上传时指定合法项目
- **WHEN** 客户端 `POST /upload` 携带合法 `.tgz` 文件与 `projectCode="demo-proj"`（已注册且启用）
- **THEN** 上传成功，返回的包对象 `projectCode="demo-proj"`

#### Scenario: 上传时项目不存在或被禁用
- **WHEN** 客户端 `POST /upload` 携带的 `projectCode` 未注册、或对应项目 `enabled=false`
- **THEN** API MUST 返回 HTTP 400，错误信息说明项目无效，且 MUST NOT 残留已写入的上传文件

#### Scenario: 上传时缺失 projectCode
- **WHEN** 客户端 `POST /upload` 未携带 `projectCode` 字段
- **THEN** API MUST 返回 HTTP 400，提示该字段必填

#### Scenario: 目录扫描不猜测项目
- **WHEN** 管理员触发 `POST /packages/scan` 且 uploads 目录存在未登记的包文件
- **THEN** 新登记的包记录 `projectCode` MUST 为空字符串（未关联）

### Requirement: 包查询与统计 API 以项目为维度
`GET /packages` SHALL 支持 `projectCode` 查询参数按项目筛选（含 `projectCode=__unassociated__` 特殊值筛选未关联包）；旧 `type` 查询参数 SHALL 作为 deprecated 别名按 `projectCode` 语义解释（仅查询参数层兼容）。`GET /packages/stats/overview` 的按类型分布 SHALL 改为按项目分布（`packagesByProject`，未关联包归入 `unassociated` 桶）。`GET /download/type/{package_type}` MUST 移除，由 `GET /download/project/{project_code}` 取代。

#### Scenario: 按项目筛选包列表
- **WHEN** 客户端 `GET /packages?projectCode=demo-proj`
- **THEN** 返回的 packages MUST 全部满足 `projectCode="demo-proj"`

#### Scenario: 旧 type 参数兼容
- **WHEN** 客户端 `GET /packages?type=lingxi-10`
- **THEN** API MUST 按 `projectCode="lingxi-10"` 语义执行筛选并正常返回（不报错）

#### Scenario: 统计返回项目分布
- **WHEN** 客户端 `GET /packages/stats/overview`
- **THEN** 响应 MUST 包含 `packagesByProject` 映射，未关联包计入 `unassociated` 键；响应 MUST NOT 再包含 `packagesByType`

#### Scenario: 按项目批量下载
- **WHEN** 客户端 `GET /download/project/demo-proj`
- **THEN** API MUST 返回该项目全部包（单包直接返回文件，多包打 zip）；`GET /download/type/{package_type}` 路由 MUST 不再注册

### Requirement: 包管理前端以项目为维度展示与录入
`RavenManager.vue` 的上传表单与列表筛选 SHALL 以项目下拉取代包类型下拉，选项来自已启用项目注册表（`projectRepoApi.listEnabled()`），上传时项目为必选；列表筛选 SHALL 额外提供"未关联"选项。包列表、包详情（`RavenPackageDetail.vue`）、智能检索结果卡片 SHALL 展示项目名称（按 `projectCode` 反查注册表，查不到时显示"未关联"与原始 code）。相关文案 MUST 提供 zh / en 两种语言。

#### Scenario: 上传表单必选项目
- **WHEN** 用户在"上传新包"面板未选择项目就尝试提交
- **THEN** 前端 MUST 阻止提交并提示必须选择项目；项目下拉 MUST 仅列出已启用项目

#### Scenario: 列表按项目筛选
- **WHEN** 用户在包列表筛选栏选择某个项目或"未关联"
- **THEN** 列表 MUST 仅显示对应 `projectCode`（或未关联）的包

#### Scenario: 包详情展示项目
- **WHEN** 用户打开一个已关联项目的包详情
- **THEN** 详情页 MUST 展示项目名称；若包未关联则 MUST 显示"未关联项目"占位
