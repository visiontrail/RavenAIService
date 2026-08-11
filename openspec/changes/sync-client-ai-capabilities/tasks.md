## 1. RavenAIService Client AI Contract

- [x] 1.1 Add authenticated capability response schemas and serialize ordered model-router choices with no-store headers, revision, refresh, expiry, and no usable-route handling
- [x] 1.2 Add strict authenticated client usage schema/endpoint with idempotent per-user metric recording and model-router outcome feedback
- [x] 1.3 Register the client AI router and update metrics/request-logging documentation for the content-free privacy contract

## 2. RavenAIService Verification

- [x] 2.1 Add API tests for authentication, route order and per-slot credentials, cache headers, revision changes, and missing configuration
- [x] 2.2 Add API/database tests for usage attribution, token normalization, idempotency, extra-field rejection, and route-health feedback

## 3. RavenClient Global Account

- [x] 3.1 Extend the RavenAIService client with registration, capability, and usage APIs and typed contracts
- [x] 3.2 Add a top-level shared auth context/gate with token restore, login, registration, capability initialization, retry, and logout
- [x] 3.3 Refactor the Agents workbench and application account chrome to consume the global session instead of an Agents-only login lifecycle
- [x] 3.4 Add bilingual global authentication and synchronization UI strings with validation and connection/configuration errors

## 4. RavenClient Service Model Runtime

- [x] 4.1 Implement the memory-only capability runtime with coalesced startup/interval/focus/failure refresh, expiry enforcement, and secret clearing
- [x] 4.2 Synchronize non-secret service providers/models/defaults and assistant model references while preventing API keys from Redux persistence
- [x] 4.3 Route Assistant completions over ordered service routes with pre-commit-only failover, abort protection, and content-free idempotent usage reporting
- [x] 4.4 Remove local Provider/Model settings navigation and redirect legacy settings paths to a supported page

## 5. RavenClient and End-to-End Verification

- [x] 5.1 Add RavenClient unit/component tests for auth registration/restore/logout, runtime refresh/expiry/redaction, model synchronization, failover commit boundary, usage payload privacy, and settings removal
- [x] 5.2 Run targeted and full relevant RavenAIService pytest suites plus RavenClient tests, typechecks, lint/build checks and fix all regressions
- [x] 5.3 Start RavenAIService and RavenClient, then use Computer to verify registration/login gate, shared Agents session, synchronized service model, direct Assistant response/failover, removed model settings, logout, and recorded content-free user usage
- [x] 5.4 Review scoped diffs and create required commits in RavenAIService, RavenClient, and the parent repository without including unrelated changes
