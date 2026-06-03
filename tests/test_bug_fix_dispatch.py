"""Tests for the bug-fix dispatch hook in run_ai_analysis_task (task 4.4).

The dispatch is a best-effort side effect: it fires only when the structured
signal says so AND a registered project_repo is resolvable, and a failure inside
it must never propagate (the analysis result is already persisted).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tasks import ai_analysis


def _log_record(project_id=7, log_id="log-1"):
    rec = MagicMock()
    rec.id = log_id
    rec.project_id = project_id
    return rec


def _result(**overrides):
    base = {
        "status": "completed",
        "requires_code_fix": True,
        "proposed_fixes": [{"title": "fix"}],
        "summary": "s",
    }
    base.update(overrides)
    return base


def test_dispatch_creates_task_and_delays(monkeypatch):
    monkeypatch.setattr(ai_analysis.settings, "bug_fix_auto_dispatch", True)
    session = MagicMock()
    created = MagicMock(id="bf-1")

    with patch("app.services.bug_fix_service.create_task_from_analysis", return_value=created) as mk, \
         patch("app.tasks.bug_fix.run_bug_fix_task") as run_task:
        ai_analysis._maybe_dispatch_bug_fix(
            session,
            analysis_result=_result(),
            log_record=_log_record(),
            analysis_task_id="celery-1",
            project_repo_id=None,
        )

    mk.assert_called_once()
    # project_repo_id defaulted from log_record.project_id
    assert mk.call_args.kwargs["project_repo_id"] == 7
    run_task.delay.assert_called_once_with("bf-1")


def test_dispatch_skipped_when_flag_off(monkeypatch):
    monkeypatch.setattr(ai_analysis.settings, "bug_fix_auto_dispatch", False)
    session = MagicMock()
    with patch("app.services.bug_fix_service.create_task_from_analysis") as mk:
        ai_analysis._maybe_dispatch_bug_fix(
            session,
            analysis_result=_result(),
            log_record=_log_record(),
            analysis_task_id="celery-1",
            project_repo_id=None,
        )
    mk.assert_not_called()


def test_dispatch_skipped_when_signal_false(monkeypatch):
    monkeypatch.setattr(ai_analysis.settings, "bug_fix_auto_dispatch", True)
    session = MagicMock()
    with patch("app.services.bug_fix_service.create_task_from_analysis") as mk:
        ai_analysis._maybe_dispatch_bug_fix(
            session,
            analysis_result=_result(requires_code_fix=False),
            log_record=_log_record(),
            analysis_task_id="celery-1",
            project_repo_id=None,
        )
    mk.assert_not_called()


def test_dispatch_skipped_when_no_repo(monkeypatch):
    monkeypatch.setattr(ai_analysis.settings, "bug_fix_auto_dispatch", True)
    session = MagicMock()
    with patch("app.services.bug_fix_service.create_task_from_analysis") as mk:
        ai_analysis._maybe_dispatch_bug_fix(
            session,
            analysis_result=_result(),
            log_record=_log_record(project_id=None),
            analysis_task_id="celery-1",
            project_repo_id=None,
        )
    mk.assert_not_called()


def test_dispatch_exception_is_swallowed(monkeypatch):
    monkeypatch.setattr(ai_analysis.settings, "bug_fix_auto_dispatch", True)
    session = MagicMock()
    with patch(
        "app.services.bug_fix_service.create_task_from_analysis",
        side_effect=RuntimeError("boom"),
    ):
        # Must not raise — analysis result persistence is already committed.
        ai_analysis._maybe_dispatch_bug_fix(
            session,
            analysis_result=_result(),
            log_record=_log_record(),
            analysis_task_id="celery-1",
            project_repo_id=None,
        )
    session.rollback.assert_called_once()
