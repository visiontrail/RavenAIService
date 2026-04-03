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


def test_pending_keywords_force_log_agent():
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

    assert next_node == "log_agent"
