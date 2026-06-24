## Why

重构包详情页的描述和标签目前只能在上传时写入，后续维护需要重新上传或直接改元数据文件，导致项目成员无法及时补充检索关键词、版本说明和交付备注。后台「项目管理」已经有项目成员关系，应允许被加入对应项目的成员在包详情页维护该项目下重构包的描述和标签。

## What Changes

- Add an authenticated metadata update path for Raven package `description` and `tags`.
- Allow users who are members of the package's corresponding project, plus admin users, to edit those fields from the package detail page.
- Keep package files, version, project association, patch flag, components, checksum, and paths unchanged through this edit flow.
- Expose edit affordances only when the current user is authorized, while still enforcing authorization on the backend.
- Update project-member wording in admin project management so members understand this permission in addition to bug-fix visibility.

## Capabilities

### New Capabilities
- `raven-package-metadata-editing`: Editable description and tags for Raven package detail pages, including API contract, authorization, validation, and UI behavior.

### Modified Capabilities
- `project-repo-registry`: Project repository member relationships also authorize editing description and tags for packages associated with the same project.

## Impact

- Backend: `app/api/packages.py`, `app/services/raven_package_service.py`, project membership authorization helpers, i18n messages, and package metadata persistence.
- Frontend: `frontend/src/views/RavenPackageDetail.vue`, `frontend/src/api/raven.ts`, `frontend/src/types/index.ts`, admin project member copy, and zh/en i18n strings.
- Tests: backend API authorization/validation/persistence tests and frontend detail-page edit-state/API interaction tests.
