## Why

Project members can already be associated with project repositories, but they cannot use the admin console unless they are global admins. This blocks project owners from maintaining their own project settings and project-level Skills, while giving them global admin would expose unrelated system configuration.

## What Changes

- Allow authenticated project members to enter a constrained admin console using their normal user token.
- Scope project-member admin access to only projects where the current user is a member; global admins continue to see and manage all projects and settings.
- Hide all non-project admin navigation and routes for project-member admins, including users, prompts, releases, agent Skills, model settings, and metrics.
- Permit project-member admins to view and update allowed settings for their own projects, including project-level system prompt content and project Skills.
- Enforce the same scope in backend admin APIs so hidden frontend routes cannot be bypassed with direct requests.
- Preserve existing full-admin behavior for legacy admin bearer tokens and users with `role == "admin"`.

## Capabilities

### New Capabilities
- `project-member-admin-access`: Defines how project members authenticate into the admin console, which projects and menus they can see, and how backend authorization scopes project-admin operations.

### Modified Capabilities
- `project-repo-registry`: Project repo list/read/update behavior changes for project-member admins so responses are membership-scoped and write access is limited to safe project settings.
- `project-skill-admin-api`: Project Skill endpoints accept either global admins or project members for the matching project, while rejecting access to other projects.
- `project-skill-admin-ui`: Project Skill management UI becomes available to project-member admins for their own projects and hidden for non-member projects.

## Impact

- **Backend auth**: Extend admin authorization to return a richer principal that distinguishes global admin from project-member admin.
- **Backend APIs**: Update `/admin/auth/me`, `/admin/project-repos*`, `/admin/project-repos/{project_code}/system-prompt`, and `/admin/project-repos/{project_code}/skills*` authorization and response behavior.
- **Frontend**: Update admin token/session handling, route guards, admin navigation, project repo list/detail actions, and Project Skills pages to respect project-member scope.
- **Tests**: Add API and frontend coverage for project-member login, scoped project visibility, hidden/forbidden settings, and allowed project Skill operations.
