## Why

重构包详情的组件区只有展示，上传后无法补录或修正组件名称和版本。

## What Changes

- 在组件区增加编辑、添加、删除、保存和取消，复用元数据编辑权限。
- 扩展 metadata PATCH 接口，校验并持久化 components，允许空数组清空。
- 保持其他元数据和包文件不变，补充中英文文案与回归验证。

## Capabilities

### New Capabilities
- `package-component-editing`: 已上传重构包的组件元数据编辑。

### Modified Capabilities

无。现有元数据编辑规范仍位于在途变更中；本变更扩展其 description/tags 编辑范围。

## Impact

RavenPackageDetail、useRavenMetadataEditor、metadata PATCH API、RavenPackageService 和中英文文案；无需数据库迁移或新依赖。
