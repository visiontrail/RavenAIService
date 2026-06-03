"""Tests for run_bug_fix_task terminal states (task 6.3).

Exercises the three terminal states (succeeded / partial / failed) by mocking
the workspace clone and the coding agent, and asserts MR rows land in the DB
without any token leakage.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base
from app.models.bug_fix import BugFixMergeRequest, BugFixTask, BugFixTaskStatus
from app.models.project_repo import ProjectRepo
from app.services import bug_fix_service


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    Base.metadata.drop_all(engine)


def _seed(Session, *, fixes=None):
    s = Session()
    repo = ProjectRepo(
        project_code="foo",
        project_name="Foo",
        repo_url="https://gitlab.example.com/foo/bar.git",
        default_branch="main",
        git_token="secret",
        enabled=True,
    )
    s.add(repo)
    s.flush()
    task = bug_fix_service.create_task_from_analysis(
        s,
        project_repo_id=repo.id,
        analysis_result={
            "status": "completed",
            "requires_code_fix": True,
            "proposed_fixes": fixes or [{"title": "fix"}],
            "summary": "s",
        },
        source_log_id="log-1",
    )
    s.commit()
    task_id = task.id
    s.close()
    return task_id


def _run(monkeypatch, Session, agent_result):
    from app.tasks import bug_fix as bf

    monkeypatch.setattr(bf, "SessionLocal", Session)
    fake_ctx = object()
    monkeypatch.setattr(bf, "prepare", lambda **kw: fake_ctx)
    monkeypatch.setattr(bf, "cleanup", lambda ctx: None)

    class _FakeAgent:
        def run_sync(self, ctx):
            return agent_result

    monkeypatch.setattr(bf, "BugFixCodingAgent", _FakeAgent)
    task_id = _seed(Session)
    # Call the bound task function directly to avoid the eager result backend
    # (redis) which is not available in the test environment.
    result = bf.run_bug_fix_task.run(task_id)
    return task_id, result


def test_run_bug_fix_task_succeeded(monkeypatch, session_factory):
    Session = session_factory
    agent_result = {
        "status": "succeeded",
        "merge_requests": [
            {
                "title": "Fix",
                "branch_name": "bugfix/ai-1-0",
                "base_branch": "main",
                "mr_url": "https://gitlab.example.com/foo/bar/-/merge_requests/1",
                "mr_iid": "1",
                "commit_sha": "abc1234",
            }
        ],
    }
    task_id, result = _run(monkeypatch, Session, agent_result)
    assert result["merge_request_count"] == 1

    s = Session()
    task = s.get(BugFixTask, task_id)
    assert task.status == BugFixTaskStatus.SUCCEEDED
    mrs = s.query(BugFixMergeRequest).filter_by(task_id=task_id).all()
    assert len(mrs) == 1
    assert "@" not in (mrs[0].mr_url or "")
    s.close()


def test_run_bug_fix_task_partial(monkeypatch, session_factory):
    Session = session_factory
    agent_result = {
        "status": "partial",
        "error_kind": "push_failed",
        "merge_requests": [
            {"title": "Fix", "branch_name": "b1", "base_branch": "main",
             "mr_url": "https://gitlab.example.com/foo/bar/-/merge_requests/2"},
        ],
    }
    task_id, _ = _run(monkeypatch, Session, agent_result)
    s = Session()
    task = s.get(BugFixTask, task_id)
    assert task.status == BugFixTaskStatus.PARTIAL
    assert task.error == "push_failed"
    s.close()


def test_run_bug_fix_task_failed_no_output(monkeypatch, session_factory):
    Session = session_factory
    agent_result = {"status": "failed", "error_kind": "no_root_cause_found", "merge_requests": []}
    task_id, _ = _run(monkeypatch, Session, agent_result)
    s = Session()
    task = s.get(BugFixTask, task_id)
    assert task.status == BugFixTaskStatus.FAILED
    assert s.query(BugFixMergeRequest).filter_by(task_id=task_id).count() == 0
    s.close()
