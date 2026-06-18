"""Unit tests for AI 分析多轮对话历史的累积逻辑。

覆盖 ``app.services.log_service.append_analysis_conversation_turn``：
- 按顺序累积每一轮结果；
- 注入本轮提问 ``query``；
- 剔除体积较大的 ``trace_events``；
- 超过上限时仅保留最近若干轮。
"""

from app.services.log_service import (
    append_analysis_conversation_turn,
    seed_conversation_from_legacy_result,
    _MAX_ANALYSIS_TURNS,
)


def test_appends_turns_in_order():
    extra = {}
    append_analysis_conversation_turn(extra, {"answer": "first"}, query="Q1")
    append_analysis_conversation_turn(extra, {"answer": "second"}, query="Q2")

    conversation = extra["ai_analysis_conversation"]
    assert [t["answer"] for t in conversation] == ["first", "second"]
    assert [t["query"] for t in conversation] == ["Q1", "Q2"]
    # 每轮自动带上时间戳
    assert all(t.get("created_at") for t in conversation)


def test_strips_trace_events_but_keeps_other_fields():
    extra = {}
    append_analysis_conversation_turn(
        extra,
        {"answer": "a", "raw": "{}", "trace_events": [{"seq": 1}, {"seq": 2}]},
        query="Q",
    )
    turn = extra["ai_analysis_conversation"][0]
    assert "trace_events" not in turn
    assert turn["raw"] == "{}"
    assert turn["answer"] == "a"


def test_does_not_overwrite_existing_query():
    extra = {}
    append_analysis_conversation_turn(extra, {"answer": "a", "query": "own"}, query="other")
    assert extra["ai_analysis_conversation"][0]["query"] == "own"


def test_caps_history_length():
    extra = {}
    for i in range(_MAX_ANALYSIS_TURNS + 10):
        append_analysis_conversation_turn(extra, {"answer": f"turn-{i}"}, query=f"Q{i}")

    conversation = extra["ai_analysis_conversation"]
    assert len(conversation) == _MAX_ANALYSIS_TURNS
    # 仅保留最近的若干轮
    assert conversation[0]["answer"] == f"turn-{10}"
    assert conversation[-1]["answer"] == f"turn-{_MAX_ANALYSIS_TURNS + 9}"


def test_seed_recovers_legacy_result_before_new_turn():
    """升级场景：旧版本只存了最近一次结果、无历史；升级后首次再分析时，
    应先把旧结果补种为第一轮，再追加本轮，得到 [上一轮, 本轮]。"""
    extra = {"ai_analysis_result": {"answer": "round1", "query": "Q1"}}

    # 模拟 save_ai_analysis_result 的顺序：先补种旧结果，再覆盖并追加本轮
    seed_conversation_from_legacy_result(extra)
    extra["ai_analysis_result"] = {"answer": "round2", "query": "Q2"}
    append_analysis_conversation_turn(extra, extra["ai_analysis_result"], query="Q2")

    conversation = extra["ai_analysis_conversation"]
    assert [t["answer"] for t in conversation] == ["round1", "round2"]
    assert [t["query"] for t in conversation] == ["Q1", "Q2"]


def test_seed_is_noop_when_history_present():
    """已有历史时不再补种，避免把最近一次结果重复写入。"""
    extra = {
        "ai_analysis_result": {"answer": "latest"},
        "ai_analysis_conversation": [{"answer": "latest", "query": "Q1"}],
    }
    seed_conversation_from_legacy_result(extra)
    assert len(extra["ai_analysis_conversation"]) == 1


def test_seed_is_noop_for_fresh_log():
    """全新日志（无旧结果）时补种为无操作。"""
    extra = {}
    seed_conversation_from_legacy_result(extra)
    assert "ai_analysis_conversation" not in extra


def test_does_not_mutate_source_result():
    extra = {}
    source = {"answer": "a", "trace_events": [{"seq": 1}]}
    append_analysis_conversation_turn(extra, source, query="Q")
    # 原始 result 不应被修改（trace_events 仍在，未被注入 query）
    assert source == {"answer": "a", "trace_events": [{"seq": 1}]}
