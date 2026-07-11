from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.admin import (
    CreateProjectRepoRequest,
    UpdateProjectRepoRequest,
    _repo_to_data,
)
from app.api.project_repos import ProjectRepoOption


def _create_payload(**overrides):
    payload = {
        "project_code": "alpha",
        "project_name": "Alpha",
        "project_card": "Alpha telemetry ingestion and diagnostics",
    }
    payload.update(overrides)
    return payload


def test_admin_create_requires_nonblank_project_card():
    with pytest.raises(ValidationError):
        CreateProjectRepoRequest(**{k: v for k, v in _create_payload().items() if k != "project_card"})
    with pytest.raises(ValidationError):
        CreateProjectRepoRequest(**_create_payload(project_card="   "))


def test_admin_update_rejects_explicit_null_or_blank_project_card():
    with pytest.raises(ValidationError):
        UpdateProjectRepoRequest(project_card=None)
    with pytest.raises(ValidationError):
        UpdateProjectRepoRequest(project_card="   ")
    # Omission is valid and means keep the existing required card.
    assert UpdateProjectRepoRequest(project_name="Renamed").project_card is None


def test_admin_and_public_responses_expose_project_card_not_description():
    repo = SimpleNamespace(
        id=1,
        project_code="alpha",
        project_name="Alpha",
        project_card="Alpha telemetry ingestion and diagnostics",
        repo_url="",
        default_branch="main",
        git_token=None,
        enabled=True,
        created_at=datetime(2026, 7, 10),
        updated_at=datetime(2026, 7, 10),
    )
    admin_data = _repo_to_data(repo)
    public_data = ProjectRepoOption(
        id=repo.id,
        project_code=repo.project_code,
        project_name=repo.project_name,
        project_card=repo.project_card,
        default_branch=repo.default_branch,
    )

    assert admin_data.project_card == repo.project_card
    assert public_data.project_card == repo.project_card
    assert "description" not in admin_data.model_dump()
    assert "description" not in public_data.model_dump()
