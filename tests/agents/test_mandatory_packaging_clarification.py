"""Server-enforced Configuration Manager confirmation gate tests."""

from __future__ import annotations

import asyncio

import pytest

from app.agents.clarification import (
    MandatoryClarificationError,
    request_mandatory_clarification,
)
from app.agents.hitl_broker import PermissionBroker
from app.agents.log_analysis.trace import SeqCounter


QUESTIONS = [
    {
        "question_key": "project",
        "header": "项目",
        "question": "确认目标项目？",
        "options": [
            {"label": "lingxi-10", "description": "Skill 初判"},
            {"label": "取消打包", "description": "不执行"},
        ],
    },
    {
        "question_key": "input:one",
        "header": "文件 1",
        "question": "one.zip 属于哪个组件？",
        "options": [
            {"label": "oam", "description": "Skill 初判"},
            {"label": "排除此文件", "description": "不放入整包"},
        ],
    },
]


async def _resolve_when_open(
    broker: PermissionBroker,
    events: list[dict],
    answers: list[dict],
) -> None:
    for _ in range(100):
        if events and events[0].get("request_id"):
            broker.resolve(events[0]["request_id"], {"answers": answers})
            return
        await asyncio.sleep(0.005)
    raise AssertionError("mandatory clarification request was not emitted")


@pytest.mark.asyncio
async def test_mandatory_gate_requires_project_and_every_file_answer():
    broker = PermissionBroker()
    events: list[dict] = []
    resolver = asyncio.create_task(
        _resolve_when_open(
            broker,
            events,
            [
                {"question_index": 0, "selected_labels": ["lingxi-10"]},
                {"question_index": 1, "selected_labels": ["oam"]},
            ],
        )
    )

    answers = await request_mandatory_clarification(
        QUESTIONS,
        broker=broker,
        emit=events.append,
        seq_counter=SeqCounter(),
        task_id="task-1",
        run_id="run-1",
        session_id="session-1",
        timeout_seconds=1,
        event_fields={"plan_hash": "abc"},
    )
    await resolver

    assert [answer["question_key"] for answer in answers] == [
        "project",
        "input:one",
    ]
    assert [event["type"] for event in events] == [
        "clarification_request",
        "clarification_resolved",
    ]
    assert events[0]["mandatory"] is True
    assert events[0]["plan_hash"] == "abc"
    assert events[0]["questions"][1]["question_key"] == "input:one"
    assert events[1]["outcome"] == "answered"
    assert [event["seq"] for event in events] == [1, 2]


@pytest.mark.asyncio
async def test_mandatory_gate_rejects_partial_answers_without_continuing():
    broker = PermissionBroker()
    events: list[dict] = []
    resolver = asyncio.create_task(
        _resolve_when_open(
            broker,
            events,
            [{"question_index": 0, "selected_labels": ["lingxi-10"]}],
        )
    )

    with pytest.raises(MandatoryClarificationError) as caught:
        await request_mandatory_clarification(
            QUESTIONS,
            broker=broker,
            emit=events.append,
            seq_counter=SeqCounter(),
            task_id="task-1",
            run_id="run-1",
            timeout_seconds=1,
        )
    await resolver

    assert caught.value.code == "missing_answers"
    assert events[-1]["type"] == "clarification_resolved"
    assert events[-1]["outcome"] == "rejected"


@pytest.mark.asyncio
async def test_mandatory_gate_timeout_always_cancels_side_effect_path():
    broker = PermissionBroker()
    events: list[dict] = []
    cancelled: list[bool] = []

    with pytest.raises(MandatoryClarificationError) as caught:
        await request_mandatory_clarification(
            QUESTIONS,
            broker=broker,
            emit=events.append,
            seq_counter=SeqCounter(),
            task_id="task-1",
            run_id="run-1",
            timeout_seconds=0.01,
            cancel_run=lambda: cancelled.append(True),
        )

    assert caught.value.code == "timeout"
    assert cancelled == [True]
    assert events[-1]["outcome"] == "cancelled"

