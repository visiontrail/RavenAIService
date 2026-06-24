## 1. Backend Metadata Update Support

- [ ] 1.1 Add package metadata edit constants and validation helpers for description length, tag count, tag length, trimming, empty filtering, and ordered deduplication.
- [ ] 1.2 Add a `RavenPackageService` method to update only `metadata.description` and `metadata.tags` for an existing package while preserving all non-editable package fields.
- [ ] 1.3 Ensure metadata updates persist to the existing package metadata JSON file and return the saved package object.

## 2. Backend API And Authorization

- [ ] 2.1 Add an authorization helper that allows users with `role == "admin"` or members of the enabled `project_repo` matching the package `projectCode`.
- [ ] 2.2 Add `PATCH /raven/api/packages/{package_id}/metadata` with request validation, 401/403/404 handling, and the existing success envelope response.
- [ ] 2.3 Expose package metadata edit availability to the detail page through a `canEditMetadata` field on package detail responses or an equivalent lightweight permission check.
- [ ] 2.4 Add or update zh/en i18n messages for metadata edit validation, authorization failures, save success, and save failure.

## 3. Frontend Package Detail Editing

- [ ] 3.1 Add a typed `updateRavenPackageMetadata` API client method and extend Raven package types for metadata edit capability if the detail response includes it.
- [ ] 3.2 Add authorized description edit mode with draft state, save, cancel, loading, error notification, and markdown re-render after save.
- [ ] 3.3 Add authorized tag editing with add/remove controls, draft state, duplicate prevention, save, cancel, loading, and error notification.
- [ ] 3.4 Keep anonymous, non-member, and read-only package detail views visually consistent with the existing read-only description and tag sections.

## 4. Project Management Copy

- [ ] 4.1 Update backend project management member hints in zh/en localization to state that project members can edit Raven package descriptions and tags for associated packages.
- [ ] 4.2 Ensure the member-management copy does not imply permission to edit package files, versions, project association, or other package asset fields.

## 5. Tests And Verification

- [ ] 5.1 Add backend tests for metadata normalization, field preservation, successful member/admin updates, and metadata persistence.
- [ ] 5.2 Add backend API authorization tests for anonymous callers, project members, non-members, disabled projects, unknown project codes, unassociated packages, and missing packages.
- [ ] 5.3 Add backend tests that updated descriptions and tags participate in existing package list search and tag filtering.
- [ ] 5.4 Add frontend tests for authorized edit controls, read-only viewers, save success state refresh, and save failure retaining the draft.
- [ ] 5.5 Run targeted backend/frontend tests and `openspec status --change allow-project-members-edit-refactor-package-metadata`.
