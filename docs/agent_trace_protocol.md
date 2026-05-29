# Agent Trace Protocol

Unified event schema for streaming Claude Agent SDK internal messages
(assistant text, thinking, tool_use, tool_result, system) out to the
frontend. One event type, two transport channels, same TypeScript and
Python definitions on both sides.

- Python source of truth: [app/agents/log_analysis/trace.py](../app/agents/log_analysis/trace.py)
- TypeScript mirror: [frontend/src/types/agentTrace.ts](../frontend/src/types/agentTrace.ts)

## Event shape

Every event is a flat object with at minimum:

| Field        | Type    | Description                                                                 |
| ------------ | ------- | --------------------------------------------------------------------------- |
| `type`       | string  | One of the 12 event types listed below.                                     |
| `task_id`    | string  | Identifies the agent run. Chat uses `session_id`; Celery uses Celery task ID. |
| `seq`        | integer | Monotonic, starts at 1, never repeats within one run. Used for ordering & de-dup. |
| `timestamp`  | float   | Epoch seconds, 6 decimal places.                                            |

Per-type fields are listed in the table below. Optional fields are
omitted from the payload when empty, so consumers must handle missing
keys gracefully.

| `type`            | Per-type fields                                                                                                              | Notes                                                                                  |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `run_start`       | `model`, `provider`                                                                                                          | Emitted once, before any SDK message is processed.                                     |
| `run_complete`    | `trace_summary`, `final_text`                                                                                                | Terminal. Emitted on successful exit.                                                  |
| `cancelled`       | `trace_summary`, `message`                                                                                                   | Terminal. Always preceded by a `system_notice{kind: "cancel_requested"}`.              |
| `error`           | `trace_summary`, `error_kind`, `message`                                                                                     | Terminal. Emitted on unhandled exception.                                              |
| `step_start`      | `step_id`, `tool_name`, `tool_input`                                                                                         | UUIDv4 `step_id` ties the start/delta/end triple together.                             |
| `step_delta`      | `step_id`, `output_chunk`                                                                                                    | One or more per step; `output_chunk` is ≤ 4 KB UTF-8.                                  |
| `step_end`        | `step_id`, `status` (`ok`/`error`), `output_excerpt`, `duration_seconds`                                                     | `output_excerpt` is ≤ 4 KB UTF-8.                                                      |
| `thinking_start`  | `step_id`                                                                                                                    | Thinking blocks share the same `step_id` namespace as tool steps but a different kind. |
| `thinking_delta`  | `step_id`, `text_chunk`                                                                                                      | `text_chunk` is ≤ 4 KB UTF-8.                                                          |
| `thinking_end`    | `step_id`, `text`, `duration_seconds`                                                                                        | `text` is the full thinking text (≤ 4 KB excerpt).                                     |
| `answer_delta`    | `text_chunk`, `step_id` (optional)                                                                                           | Incremental chunk of the assistant's **final answer body** (≤ 4 KB UTF-8). Concatenating every `answer_delta.text_chunk` of a run in `seq` order MUST equal `run_complete.final_text` (under the same masking). Distinct from `thinking_delta` (folded reasoning) and `step_delta` (tool output). |
| `system_notice`   | `kind`, `subtype`, `detail`                                                                                                  | Used for `heartbeat`, `cancel_requested`, SDK system messages, etc.                    |

### Invariants

- `seq` is strictly monotonic within one `task_id`. Consumers MUST
  de-dupe by `seq` and re-order if they receive events out of order.
- Every `step_id` MUST eventually see a `step_end` (or `thinking_end`).
  On cancel/error, the agent emits a synthetic terminating event for
  any in-flight `step_id`.
- Token-bearing URLs (e.g. `https://abc@host/repo.git`) are masked to
  `https://***@host/repo.git` before being placed into any field. The
  Python helper `mask_input` walks tool inputs recursively.
- A terminal event (`run_complete` / `cancelled` / `error`) is always
  emitted exactly once, and is always the last event for that run.
- `answer_delta` events are produced only when the active provider
  supports SDK chunked streaming (`include_partial_messages`). When it
  does not, the run emits **no** `answer_delta` and the client falls
  back to rendering `run_complete.final_text` in one shot. Either way
  `run_complete.final_text` is the authoritative full answer body and
  is used for persistence and reconnect replay correction.

## Trace summary

Every terminal event carries a `trace_summary` object with at minimum:

| Field                       | Type    | Description                                                |
| --------------------------- | ------- | ---------------------------------------------------------- |
| `thought_duration_seconds`  | float   | Wall-clock span between first and last event of the run.    |
| `tool_call_count`           | integer | Number of `step_end` events emitted.                        |
| `thinking_chars`            | integer | Sum of `thinking_delta.text_chunk` lengths (chars, not bytes). |

The Python helper `trace.summarize(events)` computes this from a raw
event list and is also used as the canonical fallback when the agent
exits without a terminal event.

## Example event sequence

A minimal happy path showing one `Bash` call followed by completion:

```jsonc
{"type":"run_start","task_id":"job-7","seq":1,"timestamp":1747700000.000001,"model":"claude-opus-4-7","provider":"anthropic"}
{"type":"step_start","task_id":"job-7","seq":2,"timestamp":1747700000.105,"step_id":"3f...","tool_name":"Bash","tool_input":{"command":"ls -la"}}
{"type":"step_delta","task_id":"job-7","seq":3,"timestamp":1747700000.220,"step_id":"3f...","output_chunk":"total 0\nfile-a\n"}
{"type":"step_delta","task_id":"job-7","seq":4,"timestamp":1747700000.240,"step_id":"3f...","output_chunk":"file-b\n"}
{"type":"step_end","task_id":"job-7","seq":5,"timestamp":1747700000.260,"step_id":"3f...","status":"ok","duration_seconds":0.16,"output_excerpt":"total 0\nfile-a\nfile-b\n"}
{"type":"answer_delta","task_id":"job-7","seq":6,"timestamp":1747700000.300,"text_chunk":"目录下"}
{"type":"answer_delta","task_id":"job-7","seq":7,"timestamp":1747700000.310,"text_chunk":"有两个文件。"}
{"type":"run_complete","task_id":"job-7","seq":8,"timestamp":1747700000.320,"final_text":"目录下有两个文件。","trace_summary":{"thought_duration_seconds":0.32,"tool_call_count":1,"thinking_chars":0}}
```

A cancellation always produces the two-step pattern:

```jsonc
{"type":"system_notice","task_id":"job-7","seq":42,"timestamp":...,"kind":"cancel_requested"}
{"type":"cancelled","task_id":"job-7","seq":43,"timestamp":...,"trace_summary":{...}}
```

## Transport channels

Two SSE channels exist; both carry the same event schema. Pick by
entry point.

### 1. Chat entry — in-process

- Endpoint: `POST /api/v1/ai-chat/log-analysis/stream`
- Frame: each event is sent as an SSE message with `event:` set to
  `agent_trace` and a JSON payload that is the event object itself.
  Existing event types (`log_analysis_status`, `session`, `done`,
  `error`) are unchanged — older clients ignore `agent_trace` frames
  and still receive the final `done`.
- Storage: events live in `AgentJob.trace_events` (in-memory). The
  `_subscribe` loop replays the buffer to a reconnecting client so
  late subscribers still get the full history.
- Heartbeat: if no event has been emitted for ≥ 15s while the run is
  active, the subscriber loop synthesises a
  `system_notice{kind: "heartbeat"}` frame to keep proxies / browsers
  from idling the connection out.

### 2. Log detail entry — Redis-backed

- Endpoint: `GET /api/v1/logs/{log_id}/ai-analysis/trace/stream`
- Frame: same as chat, but the channel is dedicated to trace events
  (no `log_analysis_status` mixed in).
- Storage:
  - In-flight: `app.services.agent_trace_redis.TraceBuffer` writes each
    event to the Redis list `ai_analysis:trace:{task_id}` via a pipeline
    of `RPUSH` + `LTRIM 0 1999` + `EXPIRE 3600`. Read side uses
    `LRANGE` polled every ≤ 250ms; no `BLPOP`/`BRPOP` so events are
    never consumed.
  - Finished: the full event list and summary are written to
    `LogRecord.ai_analysis_result.trace_events` /
    `LogRecord.ai_analysis_result.trace_summary`. The endpoint reads
    from the DB once the Celery task is done.
- Reconnection: the client passes `?from_seq=N` to request only
  events with `seq >= N`. With Redis still warm, this serves an
  incremental replay; once the task is done, it serves the relevant
  slice of the persisted list.
- 404 contract: if `log_id` has no `ai_analysis_task_id` the endpoint
  returns HTTP 404 and does NOT open the SSE stream.

## Backward compatibility

- `LogRecord.ai_analysis_result.tool_trace` is **still produced** by
  the backend, derived from `trace_events` via `derive_tool_trace()`.
  The shape (`[{name, input, output_excerpt}, ...]`) is unchanged and
  guarded by [tests/agents/log_analysis/test_legacy_tool_trace_snapshot.py](../tests/agents/log_analysis/test_legacy_tool_trace_snapshot.py).
- Older frontends without an `agent_trace` handler still see the
  existing SSE events (`log_analysis_status`, `done`, etc.) and still
  read `tool_trace` from the persisted analysis result.
- The TypeScript discriminated union (`AgentTraceEvent`) is the only
  shared schema between the two channels — keep both ends aligned
  when adding new event types or fields.
