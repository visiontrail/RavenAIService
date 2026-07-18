## Why

Global administrators currently have no reliable in-product channel for notifying all signed-in users about maintenance, policy, or release information. The application needs a dismissible announcement that reaches each user once without creating one database record per user and announcement.

## What Changes

- Add a global-admin-only announcement page as an independent Admin navigation tab.
- Allow a global administrator to publish or replace the single current announcement, with a title and message, and to deactivate it.
- Support Markdown authoring and preview in the Admin announcement editor.
- Show the current announcement to an authenticated user on the first page visit/refresh or new-chat action after publication.
- Render announcement Markdown with a presentation that follows the user's light or dark color preference.
- Record dismissal server-side so the same announcement is shown only once per user across browsers and devices.
- Persist the announcement document in the existing runtime settings JSON and add only one nullable acknowledgement marker to each user.
- Add an additive Alembic migration while retaining compatibility with the repository's startup-time schema synchronization.

## Capabilities

### New Capabilities

- `system-announcement`: Global administrator publication, authenticated-user delivery, one-time dismissal, and upgrade-safe persistence for the current system announcement.

### Modified Capabilities

None.

## Impact

- Backend: a small announcement service, global-admin and authenticated-user APIs, user acknowledgement state, API registration, and migration coverage.
- Frontend: Admin navigation/router/API/types/i18n, a Markdown-aware announcement management view, and a theme-aware workbench announcement dialog triggered at entry and new-chat boundaries.
- Persistence: `data/runtime_settings.json` stores the current announcement; `users.last_seen_announcement_id` is a nullable additive column. No announcement or per-user receipt table is introduced.
