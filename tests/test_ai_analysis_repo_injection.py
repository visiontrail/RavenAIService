import json
from pathlib import Path
from unittest.mock import MagicMock

from app.agents.log_analysis.workspace import WorkspaceContext
from app.tasks import ai_analysis


def _make_workspace(tmp_path: Path) -> WorkspaceContext:
    logs_dir = tmp_path / "logs"
    repo_dir = tmp_path / "repo"
    logs_dir.mkdir()
    repo_dir.mkdir()
    task_json_path = tmp_path / "task.json"
    task_json_path.write_text(
        json.dumps({"log_id": 1, "question": "old question", "project_id": None}),
        encoding="utf-8",
    )
    return WorkspaceContext(
        task_id="test-task",
        temp_dir=str(tmp_path),
        logs_dir=str(logs_dir),
        repo_dir=str(repo_dir),
        task_json_path=str(task_json_path),
    )


def test_bind_query_to_workspace_overwrites_task_question(tmp_path):
    ctx = _make_workspace(tmp_path)

    ai_analysis._bind_query_to_workspace(
        ctx,
        query="测试日志提取的metadata.json内容,从中解析出对应代码库地址，克隆后告诉我代码库最新的两次修改是什么",
        project_id=7,
    )

    task_data = json.loads(Path(ctx.task_json_path).read_text(encoding="utf-8"))
    assert task_data["question"].startswith("测试日志提取的metadata.json内容")
    assert task_data["project_id"] == 7
    assert ctx.metadata["question"] == task_data["question"]


def test_inject_repo_info_from_git_context_repository_url(tmp_path, monkeypatch):
    ctx = _make_workspace(tmp_path)
    metadata_path = Path(ctx.logs_dir) / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "git_context": {
                    "repository_url": "https://git.example.com/org/repo.git",
                    "branch_name": "refs/heads/release/v2.3.1",
                    "commit_id": "a1b2c3d4e5f6",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ai_analysis.settings, "code_repo_git_token", "token-123")
    session = MagicMock()

    ai_analysis._inject_repo_info(session, ctx)

    session.query.assert_not_called()
    task_data = json.loads(Path(ctx.task_json_path).read_text(encoding="utf-8"))
    repo_info = task_data["repo_info"]
    assert repo_info["repo_url"] == "https://git.example.com/org/repo.git"
    assert repo_info["clone_url"] == "https://oauth2:token-123@git.example.com/org/repo.git"
    assert repo_info["default_branch"] == "release/v2.3.1"
    assert repo_info["commit_id"] == "a1b2c3d4e5f6"
    assert repo_info["matched_via"] == "git_context.repository_url"


def test_project_code_candidates_include_log_types_before_service_name():
    metadata = {
        "issue_info": {"service_name": "郭亮"},
        "log_types": {
            "oam_antenna": {
                "project_code": "oam_lx10",
                "components": ["MAIN_OAM"],
            }
        },
    }

    candidates = ai_analysis._project_code_candidates_from_metadata(
        metadata,
        log_type="oam_antenna",
    )

    assert candidates == ["oam_lx10", "郭亮"]


def test_inject_repo_info_matches_log_types_project_code(tmp_path, monkeypatch):
    ctx = _make_workspace(tmp_path)
    metadata_path = Path(ctx.logs_dir) / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "issue_info": {"service_name": "郭亮"},
                "log_types": {
                    "oam_antenna": {
                        "project_code": "oam_lx10",
                        "components": ["MAIN_OAM"],
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ai_analysis.settings, "code_repo_git_token", None)

    repo = MagicMock()
    repo.project_code = "oam_lx10"
    repo.project_name = "OAM LX10"
    repo.repo_url = "https://git.example.com/oam/lx10.git"
    repo.default_branch = "main"
    repo.git_token = None

    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = repo

    ai_analysis._inject_repo_info(session, ctx)

    task_data = json.loads(Path(ctx.task_json_path).read_text(encoding="utf-8"))
    repo_info = task_data["repo_info"]
    assert repo_info["project_code"] == "oam_lx10"
    assert repo_info["clone_url"] == "https://git.example.com/oam/lx10.git"
    assert repo_info["matched_via"] == "oam_lx10"
