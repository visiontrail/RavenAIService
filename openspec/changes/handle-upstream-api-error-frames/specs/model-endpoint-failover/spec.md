## ADDED Requirements

### Requirement: Upstream API rejection does not commit an endpoint attempt
The routed Claude Agent SDK loop SHALL identify an upstream request rejection before commit when current structured SDK error metadata is present. For compatibility with captured older gateway behavior, it SHALL also recognize an entire assistant or result text matching the anchored `API Error: <three-digit status> <detail>` form when that frame contains no thinking or tool content. It MUST NOT forward a confirmed rejection frame as assistant output.

#### Scenario: Structured assistant billing error
- **WHEN** an uncommitted endpoint emits an assistant frame with `error == "billing_error"` and no earlier model output
- **THEN** the router treats the frame as an endpoint failure and does not expose its text as an answer

#### Scenario: Legacy 402 sequence
- **WHEN** an uncommitted endpoint emits only `API Error: 402 Insufficient Balance`, followed by a matching error result and a generic SDK exception
- **THEN** the router preserves a typed upstream error with status 402 and detail `Insufficient Balance` instead of the generic SDK exception

#### Scenario: Similar legitimate prose is not rejected
- **WHEN** a successful model response discusses an API error but does not consist solely of the anchored legacy sentinel, or a candidate sentinel is followed by a successful terminal result
- **THEN** the router commits the attempt and forwards all response frames exactly once in their original order

### Requirement: Confirmed pre-commit rejection safely fails over
When a confirmed upstream API rejection occurs before commit, the router SHALL record a failed outcome for that endpoint, SHALL try each remaining compatible candidate at most once, and SHALL emit an endpoint-switch notice before frames from the next candidate. Rejection handling MUST preserve the original first-token commit boundary and cleanup guarantees.

#### Scenario: Primary rejection and backup success
- **WHEN** the primary endpoint rejects the request before commit and the backup endpoint returns genuine model output
- **THEN** only the backup answer is forwarded, the primary is recorded as failed, and the run completes successfully

#### Scenario: Rejection after genuine output
- **WHEN** an endpoint has already emitted genuine stream, thinking, answer, or tool-use output before an upstream failure
- **THEN** the router does not retry another endpoint and propagates the mid-stream failure to the caller

#### Scenario: Each candidate fails differently
- **WHEN** one endpoint times out before output and the remaining endpoint returns an upstream API rejection
- **THEN** the router raises `AllEndpointsUnavailable` containing both the timeout cause and the sanitized upstream status/detail

### Requirement: Failure diagnostics are truthful and bounded
The router SHALL preserve a normalized error category, optional HTTP status, and sanitized provider detail for an upstream rejection. Diagnostic detail MUST be collapsed to one line and length-bounded, and MUST NOT include API credentials. Upstream rejection SHALL count as a bad endpoint outcome for circuit-breaker accounting.

#### Scenario: Provider detail is oversized or multiline
- **WHEN** a provider rejection contains multiline or oversized detail
- **THEN** logs and aggregate exceptions contain a bounded single-line representation while retaining the status and normalized category

#### Scenario: Final candidate has insufficient balance
- **WHEN** the only or final candidate returns a 402 insufficient-balance rejection before commit
- **THEN** the caller receives a terminal all-endpoints-unavailable error that names status 402 and insufficient balance rather than `error result: success`
