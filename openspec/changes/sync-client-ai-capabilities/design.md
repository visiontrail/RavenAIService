## Context

RavenAIService already owns the effective primary/backup Anthropic-compatible endpoint configuration, circuit-breaker routing state, user auth, and privacy-sanitized metrics. RavenClient instead persists a large local provider catalogue (including API keys), selects its own models, and only authenticates inside the Agents workbench. Assistant requests are constructed and streamed in the Electron renderer and go directly to upstream providers.

The requested privacy boundary is that RavenAIService records Assistant usage but no Assistant conversation content. The direct-upstream constraint means an authenticated desktop process must receive an effective upstream key; unlike a server proxy, this cannot prevent a determined authenticated user from extracting that key. RavenClient is therefore treated as a trusted first-party desktop client and production transport must be TLS-protected.

## Goals / Non-Goals

**Goals:**

- Require a valid RavenAIService user session before the RavenClient application shell is usable.
- Share one auth client/session across Assistant, Agents, and the rest of RavenClient, including self-service registration.
- Make RavenAIService the sole source of truth for Assistant provider, key, model, capability, and route order.
- Keep raw upstream keys ephemeral and out of Redux persistence, localStorage, conversation storage, IPC logs, and application logs.
- Refresh capabilities at initialization, on a fixed interval, on window focus/visibility recovery, and after auth/route failures.
- Preserve direct RavenClient-to-upstream streaming and retry only before an upstream attempt commits output.
- Record authenticated per-user usage and route health with an idempotent, content-free payload.

**Non-Goals:**

- Proxying Assistant prompts or responses through RavenAIService.
- Making an upstream vendor key cryptographically non-extractable from a client that must use it directly.
- Changing RavenAIService Agent execution, histories, or Agent content storage.
- Synchronizing OCR, embedding, reranking, image generation, or web-search credentials in this change.
- Providing users with desktop model/provider editing controls.

## Decisions

### 1. Add a user-authenticated capability snapshot API

`GET /api/v1/client-ai/capabilities` resolves `model_router.candidates(agent_kind="raven_client")` and returns ordered routes. Each route contains a stable slot, provider name, Anthropic-compatible base URL, model ids, API key, and non-secret capability flags. The envelope contains a deterministic revision, `issued_at`, `expires_at`, and `refresh_after_seconds`.

The response sets `Cache-Control: no-store, private`, `Pragma: no-cache`, `Expires: 0`, and `Vary: Authorization`. The request-logging middleware must never log bodies or authorization for the endpoint. A missing usable route returns 503; missing/invalid user auth returns 401.

Alternatives considered:

- A RavenAIService completion proxy would keep keys server-side and make metering authoritative, but violates direct upstream traffic and sends content through RavenAIService.
- An encrypted credential blob does not improve the threat model because RavenClient must possess the decryption key and plaintext at request time.
- Reusing the Admin settings API would expose the wrong authorization surface and its deliberate secret-redaction contract prevents use by the desktop.

### 2. Keep secrets in a dedicated non-persisted runtime

RavenClient creates a singleton `RavenClientAIRuntime` after authentication. It owns the capability snapshot and raw keys in module memory. Redux receives only synthetic `Provider` and `Model` metadata with empty `apiKey` fields so existing selectors and UI can render the service models without persisting credentials. Provider resolution overlays the matching in-memory route immediately before an AI client is constructed.

Logout, auth failure, snapshot expiry, and application teardown clear the runtime. A Redux persist transform also strips any API keys from the `llm` slice as defense in depth and migration ignores old local providers.

### 3. Global auth context gates the complete app shell

The existing RavenAIService token remains the shared bearer credential. A top-level React context initializes the API client, validates a stored token with `/auth/me`, and fetches capabilities before rendering routes, sidebar, or webviews. Without a valid session it renders a login/register screen; registration uses the existing `/api/v1/users/auth/register` contract. Agents consumes the same context client and profile instead of maintaining an independent login state.

The global gate exposes `booting`, `authenticating`, `profile`, `client`, `error`, `login`, `register`, `retry`, and `logout`. Logout clears the stored bearer token, capability memory, Agent conversation attachment, and user-scoped UI state.

### 4. Synchronize on lifecycle events with one coalesced fetch

After login/restore the first capability fetch is mandatory. Subsequent refreshes run at the server-provided interval (bounded to 30 seconds through 15 minutes), when the document becomes visible, when the window gains focus, and after a pre-commit upstream failure. Concurrent refresh requests share one promise. Stale snapshots are never used after `expires_at`; a refresh failure before expiry preserves the current snapshot and surfaces degraded sync status, while an expired snapshot blocks new AI calls.

On each new revision RavenClient replaces non-secret provider metadata, default/translate models, and assistant model references with the current first route. The quick model uses that route's server-configured `small_fast_model` when present and otherwise falls back to its main model. Provider and Model settings navigation entries are removed and legacy URLs redirect to General settings.

### 5. Retry at the same commit boundary as server routing

Assistant completion attempts follow the ordered snapshot. Each attempt clones the Assistant with that route's model/provider. A route may be retried only when the attempt throws before any answer/thinking/tool/result chunk is emitted. Once output commits, RavenClient never replays the request because replay could duplicate tool side effects, mix responses, and double bill tokens. An abort is never retried.

The route order is authoritative for new calls. A usage outcome updates RavenAIService's router window; the next refresh can therefore change the serving order. Client fallback is bounded to each route once.

### 6. Report content-free, idempotent usage

`POST /api/v1/client-ai/usage` accepts a UUID `invocation_id`, slot, provider, model, terminal status, canonical token counters, duration, TTFT, and a bounded error category. Pydantic forbids extra fields, so prompts/answers cannot be accidentally accepted. RavenAIService derives `user_id` from the bearer token and writes `ai_usage:raven_client:<user_id>:<invocation_id>` through `metrics_service.record_ai_usage` with source `raven_client_assistant` and sanitized metadata.

The endpoint also maps success/timeout/hard-failure outcomes into `model_router.record_outcome`. Duplicate invocation ids return success without double-counting due to the metric idempotency key. Usage delivery is best effort and does not fail an already completed Assistant response.

### 7. Treat the service provider as Anthropic-compatible

All current server provider profiles expose the Anthropic Messages protocol used by RavenAIService. RavenClient maps each route to its existing `anthropic` client type and uses the returned base URL verbatim. Provider labels remain the actual server provider names while synthetic ids are slot-stable (`raven-service-primary`, `raven-service-backup`).

## Risks / Trade-offs

- [Authenticated desktop users can extract a raw upstream key] → Restrict the endpoint to authenticated first-party clients, require TLS in production, return no-store responses, keep keys memory-only, rotate upstream keys when a user is revoked, and document that a proxy is required for stronger isolation.
- [Client-reported token usage can be suppressed or falsified] → Mark source as client-reported, apply strict bounds and idempotency, and retain server-side Agent metrics as authoritative. A proxy is required for tamper-proof billing.
- [A route changes during a stream] → Pin each invocation to its starting route list; refresh affects only new invocations.
- [Provider fails after partial output] → Do not retry after commit; surface the partial failure and report its usage/outcome.
- [Persisted assistants reference removed local models] → Atomically rewrite assistant/default model references when capabilities load and provide a guarded default resolver during migration.
- [RavenAIService is offline at startup] → Keep the app at the global auth/capability gate with a retry action and clear connection diagnostics; do not silently fall back to local keys.

## Migration Plan

1. Deploy RavenAIService endpoints and tests first; existing clients remain unaffected.
2. Release RavenClient with the global gate and capability runtime. On first successful sync, replace local model metadata and stop reading local credentials.
3. Remove Provider/Model settings navigation and redirect old settings paths.
4. Observe `raven_client_assistant` metrics and router samples before relying on client-originated route health.
5. Roll back RavenClient independently if necessary; the additive service endpoints can remain. Roll back the service only after no new RavenClient versions depend on it.

## Open Questions

- A future deployment that requires non-extractable credentials must replace direct upstream calls with a no-retention RavenAIService proxy or upstream-issued per-user ephemeral tokens.
