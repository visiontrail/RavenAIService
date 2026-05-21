# Package Search Runbook

## Endpoint

`POST /raven/api/packages/agent-search`

Body:

```json
{
  "query": "find latest ka-tx package",
  "session_id": "optional-id",
  "stream": false
}
```

- `stream=false` (default): blocking JSON response with
  `answer / recommended_package_ids / relevant_package_ids /
  tool_trace / model / usage`.
- `stream=true`: `text/event-stream` SSE feed of
  `AgentTraceEvent` frames terminated by a `final` event whose
  `data` is the same payload as the non-stream branch.

See `docs/agent_trace_protocol.md` for the SSE event shape.

## Deprecated artifacts

The legacy "RAG" search (`/raven/api/search/*`) was removed alongside
the in-process vector store. Two operational follow-ups:

1. **`data/raven/vector-store/`** — directory and contents
   (`documents.json`, `*.meta.json`) are no longer read or written.
   They are safe to delete on existing volumes. We deliberately do
   **not** ship an automatic cleanup migration so operators can
   verify and back up first.
2. Environment variables `RAVEN_VECTOR_STORE_PATH`,
   `RAG_EMBEDDING_PROVIDER`, `RAG_EMBEDDING_MODEL` are no longer
   read by the app; they can be removed from `.env` / deployment
   configs.

## Configuration

| Variable                          | Default | Notes                                    |
| --------------------------------- | ------- | ---------------------------------------- |
| `PACKAGE_SEARCH_MAX_TURNS`        | `8`     | Hard cap on SDK agent loop turns.        |
| `PACKAGE_SEARCH_DEFAULT_LIMIT`    | `5`     | Tool default page size.                  |
| `PACKAGE_SEARCH_MAX_LIMIT`        | `50`    | Hard upper bound enforced server-side.   |

The agent reuses the same Anthropic / Claude Agent SDK configuration
as the log-analysis agent (`ANTHROPIC_*` env vars).

## Trace channel

The agent emits the unified `AgentTraceEvent` schema (see
`app/agents/log_analysis/trace.py` and
`docs/agent_trace_protocol.md`). The frontend reuses the existing
trace renderer from `LogDetail.vue` — no separate frontend channel.
