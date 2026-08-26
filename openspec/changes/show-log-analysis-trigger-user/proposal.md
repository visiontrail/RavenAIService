## Why

The log list shows analysis status but not who initiated the AI analysis, so operators cannot attribute work without opening individual records or consulting run history. The list needs a stable, bilingual attribution field that also handles historical and anonymous runs honestly.

## What Changes

- Expose the latest AI-analysis trigger attribution on each log-list item, including a safe user snapshot when available.
- Capture the current user when analysis is initiated from the log-detail API.
- Backfill attribution for older AI Chat analyses from persisted chat-agent runs when possible.
- Add a desktop table column and a mobile metadata row showing the triggering user, with explicit anonymous and unavailable states.
- Add backend and frontend regression coverage for attribution and bilingual catalog parity.

## Capabilities

### New Capabilities

- `log-analysis-attribution`: Defines how AI-analysis trigger identity is captured, returned by the log API, and displayed in the log list.

### Modified Capabilities


## Impact

- Backend log response model, log service conversion/backfill, and direct analysis endpoint.
- Frontend log record type, bilingual catalogs, and responsive log-list presentation.
- Existing database schema is unchanged because attribution is stored in the existing log metadata JSON and historical chat-run table.
