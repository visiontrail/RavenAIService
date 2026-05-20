"""Load test for the agent trace pipeline.

Spec target: pushing 1500 AgentTraceEvents through both transports
(chat in-process buffer + Celery / Redis buffer) should keep end-to-end
P99 latency under 500ms per event.

Usage:
    # In-process chat path only (no external dependencies):
    python scripts/loadtest_agent_trace.py --events 1500 --no-redis

    # Both paths (requires REDIS_HOST etc. or a running local Redis):
    python scripts/loadtest_agent_trace.py --events 1500

The script measures per-event latency in two segments:

  emit_ms     time from emitter call → buffer write returned
  consume_ms  time from emitter call → reader observed the event

For the chat path "the reader" is a thread that polls
``AgentJob.events`` (mirrors what ``_subscribe`` does). For the Redis
path the reader is a thread that polls ``TraceBuffer.read_all``.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Sequence

# Make `app.*` importable when running this script from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.log_analysis.trace import (  # noqa: E402
    SeqCounter,
    build_event,
    safe_emit,
)


def _generate_events(n: int, task_id: str) -> List[Dict]:
    """Synthetic event stream representing a typical agent run."""
    counter = SeqCounter()
    out: List[Dict] = []
    out.append(build_event("run_start", task_id=task_id, seq_counter=counter))
    # Alternate thinking deltas and step lifecycle events; one tool call
    # every 10 events.
    for i in range(n - 2):
        if i % 10 == 0:
            out.append(
                build_event(
                    "step_start",
                    task_id=task_id,
                    seq_counter=counter,
                    step_id=f"s{i}",
                    tool_name="Bash",
                    tool_input={"command": f"echo {i}"},
                )
            )
        elif i % 10 == 9:
            out.append(
                build_event(
                    "step_end",
                    task_id=task_id,
                    seq_counter=counter,
                    step_id=f"s{i - 9}",
                    status="ok",
                    output_excerpt="ok",
                    duration_seconds=0.1,
                )
            )
        else:
            out.append(
                build_event(
                    "thinking_delta",
                    task_id=task_id,
                    seq_counter=counter,
                    step_id=f"think-{i // 10}",
                    text_chunk=f"段 {i} ",
                )
            )
    out.append(build_event("run_complete", task_id=task_id, seq_counter=counter))
    return out


def _percentiles(samples: Sequence[float], ps: Sequence[float]) -> Dict[float, float]:
    if not samples:
        return {p: 0.0 for p in ps}
    s = sorted(samples)
    out: Dict[float, float] = {}
    for p in ps:
        # Nearest-rank percentile (no interpolation; deterministic).
        rank = max(1, int(round(p / 100.0 * len(s))))
        out[p] = s[rank - 1]
    return out


def _print_report(label: str, emit_ms: List[float], consume_ms: List[float]) -> None:
    print(f"\n=== {label} ({len(emit_ms)} events) ===")
    for name, samples in (("emit", emit_ms), ("consume", consume_ms)):
        ps = _percentiles(samples, [50, 95, 99, 100])
        mean = statistics.mean(samples) if samples else 0.0
        print(
            f"  {name:8s}  mean={mean:7.3f}ms  "
            f"p50={ps[50]:7.3f}ms  p95={ps[95]:7.3f}ms  "
            f"p99={ps[99]:7.3f}ms  max={ps[100]:7.3f}ms"
        )
    p99 = _percentiles(consume_ms, [99])[99]
    target = 500.0
    status = "PASS" if p99 <= target else "FAIL"
    print(f"  → consume P99 = {p99:.3f}ms (target ≤ {target}ms): {status}")


# ─────────────────────────── chat / in-process ─────────────────────────────


def run_chat_path(events: List[Dict]) -> None:
    """Push events into a plain list (mirrors ``AgentJob.events``) and
    measure how quickly a polling reader observes them."""
    buffer: List[Dict] = []
    emit_at: Dict[int, float] = {}
    consume_at: Dict[int, float] = {}
    stop = threading.Event()

    def reader() -> None:
        seen = 0
        while not stop.is_set():
            while seen < len(buffer):
                now = time.perf_counter()
                ev = buffer[seen]
                consume_at[ev["seq"]] = now
                seen += 1
            if seen >= len(events):
                return
            time.sleep(0.001)

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    emit_ms: List[float] = []

    def emitter(ev: Dict) -> None:
        buffer.append(ev)

    for ev in events:
        t0 = time.perf_counter()
        emit_at[ev["seq"]] = t0
        safe_emit(emitter, ev)
        t1 = time.perf_counter()
        emit_ms.append((t1 - t0) * 1000.0)

    # Wait for reader to drain.
    deadline = time.perf_counter() + 5.0
    while len(consume_at) < len(events) and time.perf_counter() < deadline:
        time.sleep(0.005)
    stop.set()
    t.join(timeout=1.0)

    consume_ms = [
        (consume_at[s] - emit_at[s]) * 1000.0 for s in emit_at if s in consume_at
    ]
    _print_report("chat path (in-process buffer)", emit_ms, consume_ms)


# ─────────────────────────── celery / Redis path ───────────────────────────


def run_redis_path(events: List[Dict], task_id: str) -> None:
    try:
        import redis  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        print(f"[skip] redis client not importable: {exc}")
        return

    host = os.getenv("REDIS_HOST", "localhost")
    port = int(os.getenv("REDIS_PORT", "6379"))
    db = int(os.getenv("REDIS_DB", "0"))
    password = os.getenv("REDIS_PASSWORD") or None
    try:
        client = redis.Redis(
            host=host, port=port, db=db, password=password,
            decode_responses=True, socket_connect_timeout=2, socket_timeout=2,
        )
        client.ping()
    except Exception as exc:  # noqa: BLE001
        print(f"[skip] redis unreachable at {host}:{port}: {exc}")
        return

    from app.services.agent_trace_redis import TraceBuffer

    buf = TraceBuffer(redis_client=client)
    # Clean previous run.
    buf.delete(task_id)

    emit_at: Dict[int, float] = {}
    consume_at: Dict[int, float] = {}
    stop = threading.Event()

    def reader() -> None:
        last_seen = 0
        while not stop.is_set():
            for ev in buf.iter_new_events(task_id, from_seq=last_seen):
                seq = int(ev.get("seq") or 0)
                consume_at[seq] = time.perf_counter()
                if seq > last_seen:
                    last_seen = seq
            if last_seen >= events[-1]["seq"]:
                return
            time.sleep(0.005)

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    emit_ms: List[float] = []

    def emitter(ev: Dict) -> None:
        buf.write(task_id, ev)

    for ev in events:
        t0 = time.perf_counter()
        emit_at[ev["seq"]] = t0
        safe_emit(emitter, ev)
        emit_ms.append((time.perf_counter() - t0) * 1000.0)

    deadline = time.perf_counter() + 10.0
    while len(consume_at) < len(events) and time.perf_counter() < deadline:
        time.sleep(0.005)
    stop.set()
    t.join(timeout=2.0)

    consume_ms = [
        (consume_at[s] - emit_at[s]) * 1000.0 for s in emit_at if s in consume_at
    ]
    _print_report("celery path (Redis TraceBuffer)", emit_ms, consume_ms)
    buf.delete(task_id)


# ─────────────────────────────── entry point ───────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events", type=int, default=1500, help="event count")
    ap.add_argument("--task-id", default="loadtest-task", help="redis key task_id")
    ap.add_argument(
        "--no-redis", action="store_true", help="skip the Celery / Redis path"
    )
    args = ap.parse_args()

    events = _generate_events(args.events, args.task_id)
    print(f"Generated {len(events)} events for task_id={args.task_id}")

    run_chat_path(events)
    if not args.no_redis:
        run_redis_path(events, args.task_id)


if __name__ == "__main__":
    main()
