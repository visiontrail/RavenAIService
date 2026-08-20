## Why

Some Anthropic-compatible gateways report request failures as an assistant text frame such as `API Error: 402 Insufficient Balance` before the Claude Agent SDK raises a generic `Claude Code returned an error result: success`. The endpoint router currently treats that text as successful model output, commits the attempt, exposes the provider error as an answer, and suppresses safe failover and the real failure cause across every Agent.

## What Changes

- Recognize narrowly defined, pre-tool upstream API error responses emitted by the Claude Agent SDK as endpoint failures rather than user-visible model answers.
- Keep such attempts uncommitted long enough to fail over to another candidate without replaying tool side effects.
- Preserve the existing hard rule that any attempt which has emitted genuine model output or initiated tool work is never retried.
- Preserve the specific upstream error in router outcomes, logs, and the aggregated all-endpoints-unavailable exception instead of surfacing the misleading SDK wrapper error.
- Cover assistant-plus-result-plus-exception sequences, false positives, final-candidate behavior, and cleanup with regression tests and Docker runtime verification.

## Capabilities

### New Capabilities

- `model-endpoint-failover`: Defines safe endpoint commit boundaries, upstream API error-frame classification, failover behavior, and truthful terminal errors for all Claude Agent SDK callers.

### Modified Capabilities

None.

## Impact

- `app/agents/routed_query.py` and every Agent or auxiliary service that uses it.
- Router regression tests and operational documentation for routed model failures.
- No public HTTP schema, database schema, provider dependency, or configuration key changes.
