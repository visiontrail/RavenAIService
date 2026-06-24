## Context

Raven package metadata is persisted by `RavenPackageService` in the package metadata JSON file. Upload flows already accept `description` and `tags`, and the package detail page renders both fields, but there is no narrow update path for maintaining them after upload.

Project management already stores project membership through `project_repo_member`, managed from the admin project page. The package domain has also moved from the legacy `packageType` enum to `projectCode`, so each package can be mapped back to a `project_repo` row by normalized project code. This change uses that existing membership relationship to authorize lightweight package metadata edits.

## Goals / Non-Goals

**Goals:**

- Let authenticated members of a package's associated project edit only the package description and tags from the package detail page.
- Let global admin-role users edit those fields for any package.
- Keep backend authorization authoritative, independent of whether frontend edit controls are hidden.
- Persist edits through the existing Raven package metadata store and refresh the detail UI with the saved package payload.
- Preserve the existing read-only package detail experience for anonymous users, non-members, and packages without a valid enabled project association.

**Non-Goals:**

- Do not allow this flow to edit package files, paths, checksums, version, project association, patch flag, components, or upload timestamps.
- Do not introduce per-package ACLs or per-field roles beyond global admin and project membership.
- Do not require a database migration for package metadata.
- Do not move Raven package metadata out of the current JSON-backed store.

## Decisions

### Decision 1: Add a narrow package metadata PATCH endpoint

Add `PATCH /raven/api/packages/{package_id}/metadata` with a JSON body containing `description?: string | null` and `tags?: string[]`. The response returns the full saved package using the existing API envelope so the frontend can replace local detail state without a second fetch.

**Why:** A focused endpoint keeps the authorization and validation surface small. It avoids overloading upload or package replacement flows and prevents accidental changes to immutable package asset fields.

**Alternative considered:** Add a generic package update endpoint. Rejected because a generic endpoint would need broader validation and could unintentionally expose project association or file metadata mutation.

### Decision 2: Authorize by package projectCode → enabled project_repo → membership

On update, load the package, read `package.projectCode`, resolve it through `project_repo_service.get_by_project_code`, require the resolved project to be enabled, then allow the request when the current user has `role == "admin"` or `project_repo_member_service.is_member(repo.id, user.id)` is true. Missing auth returns 401. Existing packages with no project code, an unknown project code, or a disabled project return 403 for non-admin users.

**Why:** Project membership is already the administrative source of truth. Resolving through `project_repo` prevents stale or arbitrary package `projectCode` strings from granting permission.

**Alternative considered:** Let any logged-in user edit package metadata. Rejected because package descriptions and tags affect team searchability and should remain project-scoped.

### Decision 3: Normalize and validate metadata server-side

Trim description input, allow clearing it to an empty string, cap it at a practical limit, and store it under `package.metadata.description`. Normalize tags as a unique ordered list of trimmed non-empty strings, cap tag count and tag length, and store them under `package.metadata.tags`.

**Why:** Search and filtering already depend on these fields. Server-side normalization keeps API clients consistent and avoids metadata bloat.

**Alternative considered:** Trust the frontend tag editor and persist the submitted array as-is. Rejected because API clients can bypass frontend controls.

### Decision 4: Frontend asks the backend whether edit controls should be available by attempting authenticated detail context

The package detail page should render edit controls only when it can determine that the user is logged in and authorized. This can be done by returning a capability flag such as `canEditMetadata` in package detail responses, or by a lightweight permission endpoint if the implementation needs to avoid changing the package payload shape. The PATCH endpoint remains the final authority.

**Why:** Showing edit buttons only to eligible users makes the UI calm, while backend enforcement protects direct API calls and stale pages.

**Alternative considered:** Always render edit controls and handle 403 on save. Rejected because it creates a frustrating interaction for most viewers.

## Risks / Trade-offs

- [Risk] Existing packages may have missing or stale `projectCode` values -> Mitigation: keep those packages read-only for project members and allow only global admins to correct them through existing admin or future maintenance flows.
- [Risk] Concurrent edits can overwrite each other because the metadata store is JSON-backed -> Mitigation: keep the editable surface limited to two fields and always return the saved package; a future ETag/version field can be added if collisions become common.
- [Risk] Tags can become noisy and reduce search quality -> Mitigation: trim, deduplicate, and cap tags server-side; keep edit permission project-scoped.
- [Risk] Frontend capability flags can drift from backend authorization -> Mitigation: treat UI flags as presentation only and assert authorization in PATCH tests.

## Migration Plan

1. Add backend request/response models, metadata update service logic, and authorization checks.
2. Add frontend API method, editable description/tags controls, save/cancel/loading/error states, and i18n strings.
3. Update admin project member helper copy to mention package metadata editing.
4. Add targeted backend and frontend tests.
5. Deploy without data migration; existing `project_repo_member` rows immediately grant edit permission for packages whose `projectCode` resolves to their project.

Rollback is code-only: remove the PATCH route and frontend controls. Existing metadata remains compatible because edits write the same `metadata.description` and `metadata.tags` fields already used by upload and display flows.

## Open Questions

- Should package metadata edits be recorded in a dedicated audit trail, or is the current scope limited to latest-state metadata only?
