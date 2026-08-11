## ADDED Requirements

### Requirement: Direct RavenClient Assistant usage is user-attributed without conversation content

RavenAIService SHALL expose an authenticated, idempotent usage endpoint for direct RavenClient Assistant invocations. It MUST derive `user_id` from the bearer token and accept only invocation id, route descriptors, terminal status, bounded token counters, timing fields, and a bounded error category. The endpoint MUST reject extra fields and MUST NOT accept or persist prompts, answers, tool input/output, attachments, headers, cookies, or credentials.

#### Scenario: Successful client invocation records user usage

- **WHEN** an authenticated RavenClient reports a completed Assistant invocation with a new invocation UUID
- **THEN** RavenAIService MUST persist one `ai_usage` metric with source `raven_client_assistant`
- **AND** it MUST include the authenticated `user_id`, provider, model, terminal status, duration, token counters, endpoint slot, and TTFT when provided

#### Scenario: Duplicate client report is idempotent

- **WHEN** RavenClient retries the same usage report with the same user and invocation UUID
- **THEN** RavenAIService MUST return success without creating a second metric row
- **AND** aggregate token and invocation counts MUST increase only once

#### Scenario: Conversation content is rejected

- **WHEN** a client usage payload includes a prompt, answer, messages, tool data, API key, or any unrecognized field
- **THEN** RavenAIService MUST reject the request with HTTP 422
- **AND** it MUST NOT persist any part of that payload

#### Scenario: Client outcome updates route health

- **WHEN** RavenClient reports success, timeout, or a pre-commit hard failure for a valid route slot
- **THEN** RavenAIService MUST feed the corresponding bounded outcome and TTFT into the existing model router
- **AND** failures in metrics or route-health recording MUST NOT change an already completed Assistant result

#### Scenario: Unauthenticated usage report is rejected

- **WHEN** a request without a valid active user bearer token posts client usage
- **THEN** RavenAIService MUST return HTTP 401 or 403
- **AND** it MUST NOT persist a metric event
