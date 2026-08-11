## ADDED Requirements

### Requirement: Authenticated clients receive the effective ordered AI routes

RavenAIService SHALL expose `GET /api/v1/client-ai/capabilities` to authenticated active users. The response MUST contain the currently ordered usable primary/backup routes with slot, provider, Anthropic-compatible base URL, API key, model, optional small-fast model, and capability flags, plus a revision and bounded refresh/expiry timestamps.

#### Scenario: Healthy primary is returned first

- **WHEN** an authenticated user requests capabilities while the primary route is healthy and a backup is configured
- **THEN** the response MUST list primary before backup
- **AND** each route MUST contain its own provider, key, base URL, and model without mixing credentials between slots

#### Scenario: Open primary breaker changes route order

- **WHEN** the server model router selects backup first for new traffic
- **THEN** the capability response MUST preserve that candidate order
- **AND** RavenClient MUST use that order for new Assistant invocations

#### Scenario: Capability response is not cacheable

- **WHEN** RavenAIService returns a capability snapshot
- **THEN** it MUST set `Cache-Control` to private/no-store and include equivalent legacy no-cache headers
- **AND** API keys and Authorization headers MUST NOT be written to request logs

#### Scenario: No route is usable

- **WHEN** no configured route has a provider, key, base URL, and model
- **THEN** the capability endpoint MUST return HTTP 503 without returning a partial credential payload

### Requirement: RavenClient stores credentials only in runtime memory

RavenClient MUST keep capability API keys in a dedicated in-memory runtime and MUST NOT persist them in Redux persistence, localStorage, IndexedDB, conversation databases, logs, telemetry, or model configuration files. Redux MAY contain synchronized non-secret model metadata only.

#### Scenario: Capability snapshot synchronizes model metadata

- **WHEN** RavenClient loads a new capability revision
- **THEN** it MUST replace its visible provider/model metadata and default model references with the service routes
- **AND** every Redux provider `apiKey` field MUST remain empty

#### Scenario: Persisted local model data exists during upgrade

- **WHEN** an upgraded RavenClient contains previously persisted local providers, keys, or model selections
- **THEN** the authenticated capability snapshot MUST replace those providers and model selections
- **AND** no local key may be used as a fallback

#### Scenario: Runtime state is cleared

- **WHEN** the user logs out, authentication becomes invalid, or the snapshot expires without refresh
- **THEN** RavenClient MUST erase the in-memory routes
- **AND** new Assistant requests MUST be blocked until a fresh authenticated snapshot is available

### Requirement: RavenClient refreshes routes across application lifecycle events

RavenClient SHALL fetch capabilities after authentication, at the server-provided periodic interval, when the window regains focus or document visibility, and after a pre-commit route failure. Concurrent refresh triggers MUST be coalesced into one request.

#### Scenario: Periodic configuration change is applied

- **WHEN** an administrator changes provider, key, model, or route state and the refresh interval elapses
- **THEN** RavenClient MUST fetch the new revision
- **AND** new Assistant invocations MUST use the updated route while active invocations remain pinned

#### Scenario: Focus refresh catches a sleeping client up

- **WHEN** RavenClient regains focus after being suspended beyond the refresh interval
- **THEN** it MUST refresh capabilities before starting the next Assistant request

#### Scenario: Refresh fails before expiry

- **WHEN** a periodic refresh fails while the current snapshot has not expired
- **THEN** RavenClient MAY continue new invocations with the current snapshot
- **AND** it MUST expose degraded synchronization state and retry later

### Requirement: Assistant failover never replays committed work

RavenClient SHALL call upstream providers directly in the order supplied by RavenAIService. It MUST retry the next route only if the current attempt fails before emitting any answer, thinking, tool, or result content. It MUST NOT retry an aborted request or an attempt that has committed output.

#### Scenario: Primary fails before first content

- **WHEN** the first route fails before any response content commits
- **THEN** RavenClient MUST report the failed route outcome
- **AND** it MUST try the next capability route once using that route's own key, base URL, and model

#### Scenario: Primary fails after partial content

- **WHEN** the first route emits response content and then fails
- **THEN** RavenClient MUST surface the failure without retrying another route
- **AND** it MUST NOT replay user messages or tool calls

#### Scenario: User aborts an invocation

- **WHEN** a user aborts an active Assistant request
- **THEN** RavenClient MUST stop the active route
- **AND** it MUST NOT fail over to another route

### Requirement: Local provider and model configuration is removed

RavenClient SHALL remove Provider and Model settings entries and SHALL prevent legacy `/settings/provider` and `/settings/model` navigation from exposing local credential or model controls. Assistant model presentation MUST reflect service-synchronized metadata.

#### Scenario: User opens Settings

- **WHEN** an authenticated user opens RavenClient Settings
- **THEN** Provider and Model configuration menu entries MUST be absent
- **AND** no UI control may accept an upstream LLM API key

#### Scenario: Legacy settings URL is opened

- **WHEN** RavenClient navigates to a legacy provider or model settings URL
- **THEN** it MUST redirect to a supported non-model settings page
