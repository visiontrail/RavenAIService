## Why

RavenClient currently keeps its own model providers, API keys, and model defaults, so the Assistant tab can drift from RavenAIService and users only authenticate when they enter the Agents tab. This duplicates sensitive configuration, bypasses the server's primary/backup routing policy, and prevents per-user accounting for direct desktop AI usage.

## What Changes

- Make RavenAIService user registration and login a global RavenClient startup gate shared by every tab, including Agents.
- Add an authenticated, no-store RavenClient capability API that returns the effective primary/backup Anthropic-compatible routes, credentials, models, capability flags, routing order, revision, and refresh deadline.
- Keep provider credentials in RavenClient memory only; synchronize non-secret provider/model metadata at startup, periodically, when the app regains focus, and after route/auth failures.
- Route Assistant requests directly from RavenClient to the ordered upstream providers, retrying the backup only before the first response is committed.
- Add an authenticated, idempotent client-usage API that records per-user token/latency/outcome metadata and feeds route health without accepting or persisting prompts, answers, tool data, or credentials.
- **BREAKING** Remove RavenClient's Provider and Model configuration entries and ignore persisted local provider/model choices in favor of the service snapshot.
- Replace the Agents-only login/logout lifecycle with the global account session and add client registration.

## Capabilities

### New Capabilities

- `raven-client-auth`: Global RavenClient startup authentication, registration, session restore, logout, and shared use by all tabs.
- `raven-client-ai-runtime`: Authenticated service capability delivery, in-memory credential handling, model synchronization, direct upstream failover, and refresh behavior.

### Modified Capabilities

- `system-user-metrics`: Attribute direct RavenClient Assistant invocations to the authenticated user without storing conversation content.

## Impact

- RavenAIService: new user-authenticated client AI endpoints, route snapshot serialization, usage validation/recording, request-log redaction rules, metrics documentation, and API tests.
- RavenClient: global authentication context/gate, registration UI, shared Agent workbench session, in-memory model runtime, Assistant routing/usage integration, Redux synchronization/redaction, settings/navigation changes, i18n, and unit/component tests.
- Runtime/security: desktop clients receive effective upstream keys over the configured RavenAIService transport; responses are non-cacheable and credentials are never persisted or logged by RavenClient. Production deployments must protect this endpoint with TLS and trusted user accounts.
