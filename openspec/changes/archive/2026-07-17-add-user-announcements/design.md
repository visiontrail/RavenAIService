## Context

The application already has global-admin-only routes, authenticated user profiles, a disk-backed `runtime_settings.json`, and startup-time schema synchronization in addition to formal Alembic migrations. The requested behavior has two different persistence needs: one current global announcement document and one acknowledgement marker per user.

Browser-only acknowledgement would avoid a schema change, but it would repeat after storage is cleared or on another device and therefore cannot guarantee “once per user.” Creating announcement and receipt tables would satisfy the behavior but adds unnecessary data volume and migration surface while the product only needs one current announcement.

## Goals / Non-Goals

**Goals:**

- Let global administrators publish, inspect, replace, and deactivate the single current announcement from a dedicated Admin tab.
- Deliver an active announcement to each authenticated user once, across browsers and devices.
- Check for a pending announcement at authenticated workbench entry/refresh, after login or registration, and whenever a new conversation is started.
- Keep persistence and upgrade impact minimal and additive.
- Prevent an acknowledgement for an older announcement from dismissing a concurrently published newer announcement.
- Let administrators author and preview Markdown, then render the same Markdown safely for users in both light and dark presentation contexts.

**Non-Goals:**

- Announcement history, scheduling, audience segmentation, arbitrary raw HTML, delivery analytics, or read-count reporting.
- Anonymous-user delivery.
- Multiple simultaneously active announcements.

## Decisions

### Store the current announcement in runtime settings

The current announcement is stored as one validated nested object under `system_announcement` in the existing runtime settings JSON. Publishing creates a new UUID, records title, Markdown source, publisher, publication timestamp, and an active flag. Deactivation retains the document but marks it inactive. Markdown remains an ordinary string at the API and persistence layers, so no data migration is required for this presentation enhancement.

This is preferred over an `announcements` table because only the current document is required, runtime settings already provide atomic file replacement and cache invalidation, and no relational query or history is needed. It assumes the same shared/persistent `data` volume already required by other runtime settings in multi-instance deployments.

### Store one nullable last-seen ID on each user

`users.last_seen_announcement_id` stores the ID acknowledged most recently by that user. A user has a pending announcement exactly when a current active announcement exists and its ID differs from this column. Publishing does not update any user rows; only dismissal writes one user row.

This is preferred over browser storage because it is device-independent, and over a receipt table because the single-current-announcement model only needs one marker. The field remains internal and is not added to the general profile response.

### Make acknowledgement compare against the current ID

The dismissal endpoint receives the displayed announcement ID and updates the user only if it still matches the current active announcement. A mismatch returns a conflict so a late dismissal of announcement A cannot acknowledge newly published announcement B. The client closes only after a successful acknowledgement and refreshes pending state on a conflict.

### Use global-admin authorization and safe Markdown presentation

Announcement management uses the existing global-admin dependency; project-member admins cannot publish to all users and do not see the navigation item. User delivery uses the existing authenticated-user dependency. The Admin composer provides explicit edit and preview modes, and both its preview and the user dialog use the same announcement-specific Markdown renderer. Raw HTML and Mermaid execution are disabled, code is escaped, and generated links receive safe external-link attributes. This keeps useful Markdown formatting without introducing an administrator-authored HTML injection surface.

### Follow the active light or dark presentation context

The user dialog is styled through semantic announcement color tokens. Light colors are the default, system `prefers-color-scheme` selects the dark palette, and explicit document theme attributes/classes can override the system preference when the application introduces or supplies a theme selection. Both palettes preserve the same hierarchy, focus states, contrast, and responsive behavior.

### Treat the frontend trigger as an idempotent check

A workbench-level controller performs a guarded pending request after user bootstrap/login/registration and on each new-chat action. Concurrent trigger calls share/skip an in-flight request, and the server remains authoritative. A missing endpoint during a rolling frontend/backend rollout is treated as “no announcement for this check” rather than breaking the workbench.

## Risks / Trade-offs

- **[Runtime settings are file-backed]** → Use the existing persistent runtime settings path and document that horizontally scaled backend replicas must share it, matching current deployment requirements.
- **[Only the current announcement is retained]** → Accept this as an explicit non-goal; publishing a replacement intentionally discards history.
- **[A user can leave the modal open during a replacement]** → Compare the dismissal ID with the current ID and refetch on conflict.
- **[A failed acknowledgement could cause a later repeat]** → Keep the modal open and show an error until the acknowledgement succeeds.
- **[Markdown is rendered through `v-html`]** → Use a dedicated Markdown renderer with raw HTML and executable diagram rendering disabled, and cover escaping behavior with frontend tests.
- **[Rolling deployment temporarily serves an old backend]** → Deploy backend before frontend; the frontend handles missing announcement APIs without disrupting other interactions and retries at the next trigger.

## Migration Plan

1. Add nullable `users.last_seen_announcement_id` through Alembic. Existing rows require no backfill, so PostgreSQL and SQLite preserve data and the migration is fast and additive.
2. Keep the ORM field nullable so the repository's startup schema synchronizer can safely add it for installations that do not run Alembic explicitly.
3. Deploy the backend first. With no `system_announcement` key, behavior is unchanged.
4. Deploy the frontend and publish the first announcement when ready.
5. Rollback can remove the frontend and backend feature while leaving the nullable column and ignored JSON key in place; a later maintenance migration may remove them if desired.

## Open Questions

None. The requested “all users” audience is interpreted as all authenticated application users, including admin-role users when they enter the user workbench.
