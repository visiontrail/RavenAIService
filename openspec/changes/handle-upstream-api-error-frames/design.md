## Context

`routed_query()` commits an endpoint attempt when it receives the first non-system SDK message. That boundary protects against replaying tools, but some Anthropic-compatible gateways encode request rejection as an `AssistantMessage` whose only text is `API Error: <status> <detail>`, followed by an error `ResultMessage` and a generic SDK exception. Production logs show the backup DeepSeek endpoint returning `402 Insufficient Balance`; the router committed on the assistant-shaped error, exposed it as answer text, and then re-raised `Claude Code returned an error result: success` instead of reporting the actual billing failure.

The installed SDK now exposes structured `AssistantMessage.error`, `ResultMessage.api_error_status`, `ResultMessage.errors`, and `ResultMessage.is_error` fields, but RavenAIService also needs to remain compatible with gateways and slightly older runtime images that expose only the textual sentinel. The invariant from the existing router remains dominant: failover is allowed only before genuine model output can have caused a tool side effect.

## Goals / Non-Goals

**Goals:**

- Classify upstream request rejection before the endpoint attempt commits.
- Fail over once to each remaining compatible endpoint without emitting provider error frames as assistant output.
- Preserve the specific status, category, and sanitized provider detail in terminal diagnostics.
- Keep TTFT, circuit-breaker outcomes, message order, cancellation, and subprocess cleanup correct.
- Work with both current structured SDK metadata and the observed legacy text sequence.

**Non-Goals:**

- Recharging or changing provider credentials, balances, models, or endpoint configuration.
- Retrying an endpoint after genuine answer, thinking, stream-delta, or tool-use output.
- Interpreting arbitrary prose that happens to mention an API error.
- Adding a third endpoint or changing public HTTP schemas.

## Decisions

### Introduce a typed sanitized upstream error

`routed_query` will create an `UpstreamAPIError` carrying the normalized SDK error category, optional HTTP status, and a bounded single-line detail. `_classify()` will record it as a hard endpoint failure. The typed exception survives inside `AllEndpointsUnavailable.failures`, replacing the SDK's misleading terminal wrapper.

Alternatives considered:

- Re-raise the SDK exception unchanged: rejected because it discards the provider's real 402 reason.
- Match only exception text: rejected because the useful reason appears in preceding messages, not in the exception.

### Prefer structured metadata and narrowly recognize the legacy sentinel

An `AssistantMessage.error` value or `ResultMessage.api_error_status` is authoritative. As a compatibility fallback, a message is a candidate only when its complete assistant/result text matches the anchored form `API Error: <three-digit status> <non-empty detail>` and contains no thinking or tool content. Matching is bounded and sanitized before logging.

Alternatives considered:

- Search every assistant response for words such as `error` or `insufficient balance`: rejected because it would misclassify legitimate diagnostic answers.
- Depend only on SDK 0.2.82 fields: rejected because the provided production runtime is explicitly older and the observed frames did not yield an actionable structured exception.

### Quarantine the candidate frames until confirmed

Candidate API-error frames remain internal and do not cross the commit boundary. A following structured error result, matching terminal result, SDK exception, or clean stream end confirms the endpoint failure. If a subsequent frame disproves the candidate, the router commits at the candidate's original TTFT and releases all quarantined frames in order before continuing.

This quarantine avoids both false user-visible answers and unsafe broad pattern matching. It does not buffer normal model output or SDK bookkeeping.

### Never reopen a committed attempt

If any non-error model/stream/tool frame has already committed the attempt, subsequent failures remain caller-owned and no failover occurs. Error detection is applied only while `committed == false`; this preserves the side-effect and billing invariant.

### Treat confirmed rejection as an ordinary uncommitted endpoint failure

The existing failure loop records a bad router outcome, emits one `EndpointSwitchNotice` when another candidate exists, and tries each remaining candidate at most once. When none succeeds it raises `AllEndpointsUnavailable` containing timeout/connectivity causes plus the typed upstream rejection. A billing failure is therefore handled truthfully but not magically repaired.

## Risks / Trade-offs

- [A model intentionally answers with exactly the legacy sentinel] → Quarantine is released if the terminal result is successful; tests cover the false-positive path.
- [A new gateway uses a different unstructured error format] → Structured SDK fields remain primary; extend only with captured evidence and an anchored test fixture.
- [A gateway stalls after emitting a candidate error] → The existing first-token deadline and attempt cleanup still apply; the router never yields the candidate as answer text.
- [Provider details contain secrets or excessive payloads] → Collapse whitespace, cap detail length, and never inspect or log request credentials.
- [A rejection arrives after partial model/tool output] → The attempt is already committed and is never retried, favoring side-effect safety over availability.

## Migration Plan

1. Deploy the code and tests with no configuration or schema migration.
2. Rebuild the local Docker images and verify container health.
3. Exercise deterministic primary/backup error sequences inside the backend container and verify the UI through the in-app Browser.
4. Roll back by reverting the single commit; no persisted data or settings require restoration.

## Open Questions

None. The production evidence and current SDK message schema are sufficient for the bounded fix.
