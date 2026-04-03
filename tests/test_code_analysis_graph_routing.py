from app.agents.code_analysis_graph import CodeAnalysisGraph


def _make_graph() -> CodeAnalysisGraph:
    graph = CodeAnalysisGraph.__new__(CodeAnalysisGraph)
    graph.max_iterations = 10
    graph.token_limit = 8000
    return graph


def test_supervisor_cannot_jump_to_summary_too_early():
    graph = _make_graph()
    state = {
        "raw_root_cause": "",
        "iteration_count": 1,
        "token_count": 200,
        "repo_cloned": True,
        "workspace_dir": "/tmp/workspace",
        "pending_log_keywords": [],
    }

    next_node = graph._apply_supervisor_constraints(
        state=state, suggested_next="summary_agent", fallback="code_agent"
    )

    assert next_node == "code_agent"


def test_summary_is_forced_after_diagnosis_submission():
    graph = _make_graph()
    state = {
        "raw_root_cause": "定位到空指针",
        "iteration_count": 2,
        "token_count": 300,
        "repo_cloned": True,
        "workspace_dir": "/tmp/workspace",
        "pending_log_keywords": [],
    }

    next_node = graph._apply_supervisor_constraints(
        state=state, suggested_next="code_agent", fallback="code_agent"
    )

    assert next_node == "summary_agent"


def test_pending_keywords_no_longer_force_log_agent():
    graph = _make_graph()
    state = {
        "raw_root_cause": "",
        "iteration_count": 2,
        "token_count": 300,
        "repo_cloned": True,
        "workspace_dir": "/tmp/workspace",
        "pending_log_keywords": ["cpu", "utilization"],
    }

    next_node = graph._apply_supervisor_constraints(
        state=state, suggested_next="code_agent", fallback="code_agent"
    )

    assert next_node == "code_agent"


def test_delegate_subagent_tool_dispatches_explore_runner():
    graph = _make_graph()
    captured = {}

    def fake_run_explore_subagent(**kwargs):
        captured.update(kwargs)
        return "explore-result", {"subagent_type": "explore", "llm_call_count": 9}

    graph._run_explore_subagent = fake_run_explore_subagent  # type: ignore[method-assign]

    result, extra = graph._dispatch_tool(
        tool_name="DelegateSubAgentTool",
        args={
            "subagent_type": "explore",
            "task": "find uplink scheduler",
            "expected_output": "return candidate files",
            "thoroughness": "very thorough",
        },
        workspace_dir="/tmp/workspace",
        log_type="stack",
        repo_url="",
        repo_branch="",
        repo_commit_id="",
        trace_id="trace-1",
        llm_call_count=7,
        query="定位 uplink 调度异常",
        working_memory="old memo",
        purified_logs="latest log",
        log_file_path="",
        log_search_attempts=0,
        supervisor_plan="plan",
        supervisor_reflection="reflection",
    )

    assert result == "explore-result"
    assert extra["subagent_type"] == "explore"
    assert captured["task"] == "find uplink scheduler"
    assert captured["thoroughness"] == "very_thorough"
