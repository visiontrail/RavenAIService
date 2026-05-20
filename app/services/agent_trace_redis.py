"""Redis-backed buffer for ``AgentTraceEvent`` streams.

Bridges the Celery worker (where the Log Analysis Agent runs in a
separate process) and the FastAPI SSE endpoint
``GET /api/v1/logs/{log_id}/ai-analysis/trace/stream`` that streams
events to the browser.

Design (see openspec/changes/stream-agent-trace-to-ui/design.md §Decision 4):

- Each task owns one bounded Redis list ``ai_analysis:trace:{task_id}``.
- Writes are a pipeline of ``RPUSH + LTRIM + EXPIRE`` so the key is
  trimmed at the source and orphan keys are reaped by TTL.
- Reads are non-destructive ``LRANGE`` polls — clients can reconnect at
  any time and replay from ``from_seq`` (the highest seq they have
  already seen).
- Failures degrade silently: ``write`` logs at WARNING and does NOT
  propagate, so a Redis outage cannot kill the Agent loop. The local
  in-memory trace accumulator (in ``LogAnalysisAgent.run``) is the
  authoritative copy that gets persisted to ``LogRecord``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

# Bounded list — keeps at most N most-recent events. The Agent caps at
# ~200 events per task in practice, so 2000 is comfortably above the
# normal P99 with room for pathological cases.
MAX_TRACE_EVENTS = 2000
# 1 hour — long enough for a user to reload the page after a finished
# task, short enough that orphan keys never accumulate forever.
TRACE_TTL_SECONDS = 3600

_KEY_PREFIX = "ai_analysis:trace:"


def _key(task_id: str) -> str:
    return f"{_KEY_PREFIX}{task_id}"


class TraceBuffer:
    """Synchronous Redis client wrapper.

    Constructed once per Celery task; the underlying redis client is
    lazily built on first use so importing this module does not fail in
    environments where ``redis`` is not installed (e.g. unit tests that
    monkey-patch the buffer).
    """

    def __init__(self, *, redis_client: Optional[Any] = None) -> None:
        # When ``redis_client`` is provided (typically by tests), use it
        # verbatim. Otherwise build one from app.config on demand.
        self._client = redis_client
        self._client_built = redis_client is not None

    @property
    def client(self) -> Optional[Any]:
        """Lazily-built redis client. Returns ``None`` if construction fails."""
        if self._client_built:
            return self._client
        self._client_built = True
        try:
            import redis  # type: ignore[import-not-found]
            from app.config import settings

            self._client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_db,
                password=settings.redis_password,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("TraceBuffer: failed to build redis client: %s", exc)
            self._client = None
        return self._client

    def write(self, task_id: str, event: Dict[str, Any]) -> None:
        """Append one event to ``task_id``'s list. Never raises."""
        client = self.client
        if client is None or not task_id:
            return
        try:
            payload = json.dumps(event, ensure_ascii=False, default=str)
        except Exception as exc:  # noqa: BLE001
            logger.warning("TraceBuffer: failed to serialize event: %s", exc)
            return
        try:
            pipe = client.pipeline()
            pipe.rpush(_key(task_id), payload)
            pipe.ltrim(_key(task_id), -MAX_TRACE_EVENTS, -1)
            pipe.expire(_key(task_id), TRACE_TTL_SECONDS)
            pipe.execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "TraceBuffer: pipeline write failed task_id=%s: %s",
                task_id,
                exc,
            )

    def read_all(self, task_id: str) -> List[Dict[str, Any]]:
        """Return every event currently buffered for ``task_id``.

        Used by the SSE endpoint on initial connect and on every poll
        iteration; returns ``[]`` on missing key, malformed JSON entries
        are skipped (rare and best-effort).
        """
        client = self.client
        if client is None or not task_id:
            return []
        try:
            raw = client.lrange(_key(task_id), 0, -1)
        except Exception as exc:  # noqa: BLE001
            logger.warning("TraceBuffer: read failed task_id=%s: %s", task_id, exc)
            return []
        events: List[Dict[str, Any]] = []
        for entry in raw or []:
            try:
                events.append(json.loads(entry))
            except Exception:
                continue
        return events

    def iter_new_events(
        self,
        task_id: str,
        *,
        from_seq: int = 0,
    ) -> Iterator[Dict[str, Any]]:
        """Yield events whose ``seq`` is strictly greater than ``from_seq``.

        Performs one ``LRANGE`` over the entire current list and filters
        client-side — simple and correct for our list sizes (<= 2000).
        The caller is responsible for polling on a timer; this method
        does not sleep.
        """
        for event in self.read_all(task_id):
            try:
                seq = int(event.get("seq", 0))
            except Exception:
                seq = 0
            if seq > from_seq:
                yield event

    def delete(self, task_id: str) -> None:
        """Drop the task's buffer (test helper / explicit cleanup)."""
        client = self.client
        if client is None or not task_id:
            return
        try:
            client.delete(_key(task_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("TraceBuffer: delete failed task_id=%s: %s", task_id, exc)


# Module-level singleton — the Celery worker constructs an emitter that
# closes over this instance; the SSE endpoint reads through it.
_default_buffer: Optional[TraceBuffer] = None


def get_buffer() -> TraceBuffer:
    global _default_buffer
    if _default_buffer is None:
        _default_buffer = TraceBuffer()
    return _default_buffer


def reset_buffer_for_tests(redis_client: Optional[Any] = None) -> TraceBuffer:
    """Replace the singleton (test fixture helper)."""
    global _default_buffer
    _default_buffer = TraceBuffer(redis_client=redis_client)
    return _default_buffer
