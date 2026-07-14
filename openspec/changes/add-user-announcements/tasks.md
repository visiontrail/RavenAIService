## 1. Persistence and backend domain

- [x] 1.1 Add the nullable user acknowledgement marker and an additive Alembic migration.
- [x] 1.2 Extend runtime settings and implement validated current-announcement publish, read, and deactivate operations.
- [x] 1.3 Add global-admin management and authenticated-user pending/dismiss API endpoints with stale-ID conflict protection.
- [x] 1.4 Register announcement routers and add backend service/API/migration tests.

## 2. Admin announcement management

- [x] 2.1 Add announcement types and Admin API client operations.
- [x] 2.2 Add a global-admin-only announcement navigation item and route.
- [x] 2.3 Build the localized Admin announcement page for inspection, publication/replacement, and deactivation.

## 3. User delivery experience

- [x] 3.1 Add authenticated-user pending and dismissal API client operations.
- [x] 3.2 Implement a localized, accessible announcement dialog with server-confirmed close behavior.
- [x] 3.3 Trigger guarded pending checks on workbench entry/refresh, authentication completion, and new-conversation actions.

## 4. Verification

- [x] 4.1 Add frontend tests for Admin navigation scope and once-per-user dialog state behavior.
- [x] 4.2 Run targeted backend tests, frontend tests, type checking, and production build.
- [x] 4.3 Review the final diff for unrelated changes and document the migration/rollout behavior.

## 5. Markdown and theme-aware presentation refinements

- [x] 5.1 Update the announcement artifacts for safe Markdown authoring/rendering and light/dark presentation.
- [x] 5.2 Add a reusable raw-HTML-disabled announcement Markdown renderer with focused safety tests.
- [x] 5.3 Add localized Markdown edit/preview controls and rendered current-content inspection to the Admin page.
- [x] 5.4 Render user announcement Markdown and provide responsive light/dark dialog palettes.
- [x] 5.5 Run targeted frontend tests, type checking, and a production build.
