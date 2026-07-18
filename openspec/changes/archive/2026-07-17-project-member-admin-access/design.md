## Context

The backend currently has two authentication concepts that meet in admin routes:

- Legacy admin credentials from `admin_auth.yaml`, issued by `/admin/auth/login`.
- Normal user tokens, accepted by admin routes only when the corresponding `users.role` is `admin`.

Project membership already exists through `project_repo_member`, and the frontend admin client already falls back from `raven_admin_token` to the normal user token. However, `require_admin` rejects non-admin users before project membership can be considered. Project Skill APIs and project-level system prompt APIs are under `/admin/project-repos/...`, so they inherit global admin-only behavior even though their resources are project-scoped.

This change introduces a constrained "project-member admin" surface: a project member can enter admin UI only to manage projects they belong to and project-level Skills/settings for those projects.

## Goals / Non-Goals

**Goals:**
- Let authenticated project members access the admin console without granting global admin.
- Scope every backend project-admin operation by the current user's project membership.
- Keep global admin behavior unchanged for legacy admin tokens and `role == "admin"` user tokens.
- Hide unavailable admin navigation/routes from project-member admins.
- Allow project-member admins to manage project-level system prompt content and project Skills for their own projects.
- Keep secret handling intact: no raw git token exposure, no access to unrelated global settings.

**Non-Goals:**
- Introduce per-project roles beyond "member".
- Let project members create/delete projects, manage project members, manage global users, prompts, releases, agent Skills, model settings, or metrics.
- Let project members pre-provision Skills for project codes that do not exist in `project_repo`.
- Replace the legacy admin login flow.
- Add in-browser editing of individual Skill files; Skill modification means upload with overwrite, enable/disable, and delete as currently supported.

## Decisions

### Decision 1: Return a structured admin principal instead of a username string

Add a small auth model, for example `AdminPrincipal`, with fields such as `kind`, `username`, `user_id`, `is_global_admin`, and `allowed_project_ids`. Existing `require_admin` can keep returning a global principal for admin-only routes, while new dependencies can admit project-member admins:

- `require_global_admin`: legacy behavior, used by users/prompts/releases/agent Skills/model settings/metrics/member management.
- `require_admin_principal`: accepts global admin or an authenticated user with at least one enabled project membership.
- `require_project_admin_by_repo_id` / `require_project_admin_by_code`: accepts global admin or a member of that exact project.

**Why:** Project scope is an authorization decision, not a frontend-only display decision. Returning a principal keeps the scope available to API handlers and tests.

**Alternative considered:** Treat all members as `role == "admin"` in the user table. Rejected because it would unlock global admin endpoints and make project-specific permissions impossible to reason about.

### Decision 2: Project-member admins use normal user login and `/admin/auth/me`

Do not add a second project-admin password flow. A normal authenticated user token can call `/admin/auth/me`; the response indicates whether the user has `access_level == "global_admin"` or `access_level == "project_member"` and includes allowed admin nav keys and project identifiers. Legacy `/admin/auth/login` remains for `admin_auth.yaml`.

**Why:** The product already has user accounts and project membership. Reusing user login avoids duplicate credentials and matches the current frontend `adminToken.get()` fallback to `userToken.get()`.

**Alternative considered:** Issue a separate project-admin token. Rejected because it adds token lifecycle complexity without adding meaningful isolation.

### Decision 3: Scope project repo APIs by resource, not by route name

For project-member admins:

- `GET /admin/project-repos` returns only enabled projects where the user is a member.
- `GET /admin/project-repos/{id}` returns 404 for non-member projects.
- `PUT /admin/project-repos/{id}` accepts only safe project fields: `project_name`, `description`, `repo_url`, and `default_branch`.
- `POST`, `DELETE`, member management, `enabled`, and `git_token` changes remain global-admin-only.
- `POST /admin/project-repos/{id}/test-connection` is allowed for member projects because it returns a structured success/error and never exposes the raw token.

**Why:** The user asked for project members to configure their own project, but not to administer the whole installation. Separating safe project fields from ownership/security fields limits blast radius.

**Alternative considered:** Make the project repo page read-only and put all editable settings under new member-only endpoints. Rejected because it duplicates project settings semantics and forces two frontend implementations for the same resource.

### Decision 4: Project Skill and system prompt authorization resolves `project_code` through `project_repo`

Global admins keep current behavior, including project Skill pre-provisioning for a project code before a repo row exists. Project-member admins must reference an enabled `project_repo` whose normalized `project_code` matches the route and whose membership row includes the current user.

**Why:** Membership is stored by `project_repo_id`, not arbitrary project code. Requiring a real project prevents a member from writing under unrelated or future project-code directories.

**Alternative considered:** Check only whether the project code appears in any client-visible project list. Rejected because backend authorization must stand alone.

### Decision 5: Frontend filters nav and guards routes from the server-reported principal

The admin shell loads `/admin/auth/me` before rendering admin navigation. For `project_member`, the only visible top-level nav item is project repos, and `/admin` redirects to `/admin/project-repos`. Direct navigation to hidden admin routes shows forbidden/not-found behavior after the backend rejects it. The Project Skills page verifies the project code is in the allowed project set before rendering member controls.

**Why:** Hiding irrelevant settings gives project members a clear workspace, while backend checks remain authoritative.

**Alternative considered:** Keep all nav items visible but show disabled states. Rejected because the requirement says other settings are invisible.

## Risks / Trade-offs

- [Risk] Existing code expects `require_admin` to return `str` -> Mitigation: add new dependencies incrementally and keep a compatibility wrapper where possible; update touched handlers and tests together.
- [Risk] Frontend route hiding could drift from backend authorization -> Mitigation: `/admin/auth/me` returns allowed nav/scope and API tests enforce forbidden access independently of UI.
- [Risk] Project members might change repo settings in a way that affects agents -> Mitigation: limit editable fields, validate URLs/branches using existing schemas, and keep token/member/delete/enabled fields global-admin-only.
- [Risk] Project Skill APIs currently allow unknown project codes for global admin pre-provisioning -> Mitigation: preserve that behavior only for global admins; require DB membership for project-member admins.
- [Risk] 403 vs 404 can leak project existence -> Mitigation: return 404 for non-member project detail and project-code resource access, while returning 403 for clearly global-only endpoints.

## Migration Plan

1. Add structured admin principal and project-scope authorization dependencies.
2. Update project repo, system prompt, and project Skill routes to use project-aware dependencies.
3. Update `/admin/auth/me` to describe access level, allowed nav keys, and allowed projects.
4. Update frontend admin routing/nav/session state to consume the new scope response.
5. Add backend and frontend tests for global admin, project-member admin, non-member, and unauthenticated callers.
6. Deploy without data migration; existing `project_repo_member` rows immediately grant constrained admin access.

Rollback is code-only: reverting the auth and frontend changes restores global admin-only behavior, with no schema changes to unwind.

## Open Questions

- Should future project roles distinguish "viewer", "maintainer", and "owner" for finer-grained Skill and settings permissions?
- Should future audit reporting distinguish project-member admin changes from global admin changes?
