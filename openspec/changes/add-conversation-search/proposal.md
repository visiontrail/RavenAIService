## Why

The workbench already displays a search icon, but clicking it does not search or reveal any UI. Users need to find and reopen past conversations by title or message content with a familiar ChatGPT-style search dialog.

## What Changes

- Connect the existing sidebar icon and Cmd/Ctrl+K to a centered, keyboard-accessible search dialog.
- Search authenticated users' persisted conversation titles and messages, with safe highlighted excerpts, recent conversations, and paginated results.
- Support debounced input, IME composition, loading/empty/error states, keyboard navigation, and conversation selection in both locales and themes.
- Verify tests and a real browser against the rebuilt local Docker stack.

## Capabilities

### New Capabilities
- `conversation-search`: Private conversation retrieval and the workbench search dialog.

### Modified Capabilities

None.

## Impact

FastAPI user chat-session routes, chat history service, Vue workbench and search component, user API types, and zh/en catalogs. No new dependencies or database migration required. Existing conversation selection and agent-run lifecycle remain the integration points.
