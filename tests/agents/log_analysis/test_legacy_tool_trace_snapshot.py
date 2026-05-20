"""Snapshot guard for the legacy ``tool_trace`` shape.

The trace work in `stream-agent-trace-to-ui` introduced `trace_events` and
`trace_summary` on `LogAnalysisAgent` result dicts. To stay compatible with
older frontends that still read `ai_analysis_result.tool_trace`, the field
MUST keep its original schema: a list of `{name, input, output_excerpt}`
dicts in step-start order. This snapshot fails if anyone changes the
derived shape without also updating downstream consumers.
"""

from __future__ import annotations

from app.agents.log_analysis.trace import (
    STEP_END,
    STEP_START,
    THINKING_DELTA,
    SeqCounter,
    build_event,
    derive_tool_trace,
)


LEGACY_TOOL_TRACE_KEYS = {"name", "input", "output_excerpt"}


def _make_events():
    counter = SeqCounter()
    events = []
    events.append(
        build_event(
            "run_start",
            task_id="task-snap",
            seq_counter=counter,
            model="claude-opus-4-7",
            provider="anthropic",
        )
    )
    # Tool #1: Bash
    events.append(
        build_event(
            STEP_START,
            task_id="task-snap",
            seq_counter=counter,
            step_id="step-1",
            tool_name="Bash",
            tool_input={"command": "ls -la"},
        )
    )
    events.append(
        build_event(
            STEP_END,
            task_id="task-snap",
            seq_counter=counter,
            step_id="step-1",
            status="ok",
            output_excerpt="total 0\nfile-a\nfile-b",
            duration_seconds=0.42,
        )
    )
    # Thinking block in between — must be ignored by derive_tool_trace.
    events.append(
        build_event(
            "thinking_start",
            task_id="task-snap",
            seq_counter=counter,
            step_id="think-1",
        )
    )
    events.append(
        build_event(
            THINKING_DELTA,
            task_id="task-snap",
            seq_counter=counter,
            step_id="think-1",
            text_chunk="weighing options...",
        )
    )
    events.append(
        build_event(
            "thinking_end",
            task_id="task-snap",
            seq_counter=counter,
            step_id="think-1",
        )
    )
    # Tool #2: Read
    events.append(
        build_event(
            STEP_START,
            task_id="task-snap",
            seq_counter=counter,
            step_id="step-2",
            tool_name="Read",
            tool_input={"file_path": "/var/log/app.log"},
        )
    )
    events.append(
        build_event(
            STEP_END,
            task_id="task-snap",
            seq_counter=counter,
            step_id="step-2",
            status="ok",
            output_excerpt="2026-05-20 ERROR something broke",
        )
    )
    events.append(
        build_event(
            "run_complete",
            task_id="task-snap",
            seq_counter=counter,
            trace_summary={
                "tool_call_count": 2,
                "thought_duration_seconds": 1.0,
                "thinking_chars": 19,
            },
        )
    )
    return events


def test_tool_trace_matches_legacy_snapshot():
    """`derive_tool_trace` MUST keep producing the legacy shape exactly.

    Old frontends key off `name`, `input`, `output_excerpt`. If this
    snapshot diverges, double-check `frontend/src/views/LogDetail.vue`
    and any external consumer of `ai_analysis_result.tool_trace` before
    updating the expected value.
    """
    trace = derive_tool_trace(_make_events())

    assert trace == [
        {
            "name": "Bash",
            "input": '{"command": "ls -la"}',
            "output_excerpt": "total 0\nfile-a\nfile-b",
        },
        {
            "name": "Read",
            "input": '{"file_path": "/var/log/app.log"}',
            "output_excerpt": "2026-05-20 ERROR something broke",
        },
    ]


def test_tool_trace_entries_have_exactly_legacy_keys():
    """No extra/missing keys vs. pre-trace-stream consumers."""
    trace = derive_tool_trace(_make_events())
    assert trace, "expected at least one tool entry"
    for entry in trace:
        assert set(entry.keys()) == LEGACY_TOOL_TRACE_KEYS, (
            f"unexpected keys in tool_trace entry: {set(entry.keys())}"
        )


def test_tool_trace_skips_non_tool_events():
    """Thinking / run_start / run_complete events MUST NOT leak in."""
    counter = SeqCounter()
    events = [
        build_event("run_start", task_id="t", seq_counter=counter),
        build_event(
            "thinking_start", task_id="t", seq_counter=counter, step_id="th1"
        ),
        build_event(
            THINKING_DELTA,
            task_id="t",
            seq_counter=counter,
            step_id="th1",
            text_chunk="hmm",
        ),
        build_event("thinking_end", task_id="t", seq_counter=counter, step_id="th1"),
        build_event("system_notice", task_id="t", seq_counter=counter, kind="heartbeat"),
        build_event("run_complete", task_id="t", seq_counter=counter),
    ]
    assert derive_tool_trace(events) == []
