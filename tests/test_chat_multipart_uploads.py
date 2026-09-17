"""Exercise actual multipart parsing through all chat routes, without running agents."""

import base64
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import ai_chat, chat_uploads
from app.config import settings
from app.exceptions import register_exception_handlers

MIB = 1024 * 1024
ENDPOINTS = ["log-analysis", "project-expert", "package-search"]


@pytest.fixture
def upload_api(monkeypatch):
    captured = []

    async def stream(**kwargs):
        # Consume files inside the stream, matching production's file lifecycle.
        kwargs["file_bytes"] = [await f.read() for f in kwargs.get("files") or []]
        captured.append(kwargs)
        yield 'data: {"event":"done","answer":"ok"}\n\n'

    for name in ["log_analysis", "project_expert", "package_search"]:
        monkeypatch.setattr(ai_chat, f"{name}_chat_service", SimpleNamespace(
            stream=stream,
            session_has_workspace=lambda _: False,
            assert_session_access=lambda *args, **kwargs: None,
        ))
    monkeypatch.setattr(settings, "ocr_max_images", 6)
    monkeypatch.setattr(settings, "ocr_max_image_mb", 5)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(ai_chat.router, prefix="/ai-chat")
    app.dependency_overrides[ai_chat.get_db] = lambda: None
    app.dependency_overrides[ai_chat.get_current_user] = lambda: SimpleNamespace(id="upload-test", language="zh")
    with TestClient(app) as client:
        yield client, captured


def image_json(*images):
    return json.dumps([{"media_type": "image/png", "data": base64.b64encode(b).decode()} for b in images])


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("legacy", [False, True])
def test_images_larger_than_default_field_limit_reach_service_unchanged(upload_api, endpoint, legacy):
    client, captured = upload_api
    images = [b"a" * (1400 * 1024), b"b" * (700 * 1024)]
    files = [("files", ("lrun_oam4.log", b"frequency=2080000", "text/plain"))]
    if legacy:
        files.append(("images", (None, image_json(*images))))
    else:
        files.extend(("image_files", (f"shot-{i}.png", data, "image/png")) for i, data in enumerate(images))
    response = client.post(f"/ai-chat/{endpoint}/stream", data={"message": "分析频点", "project_repo_id": "1"}, files=files)
    assert response.status_code == 200, response.text
    assert '"event":"done"' in response.text
    assert len(captured) == 1
    assert [base64.b64decode(img.data) for img in captured[0]["images"]] == images
    if endpoint != "project-expert":
        assert captured[0]["file_bytes"] == [b"frequency=2080000"]


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("excess", [0, 1])
@pytest.mark.parametrize("locale", ["zh", "en"])
def test_image_size_boundary_uses_configured_limit(upload_api, monkeypatch, legacy, excess, locale):
    client, captured = upload_api
    monkeypatch.setattr(settings, "ocr_max_image_mb", 1)
    payload = b"x" * (MIB + excess)
    files = [("images", (None, image_json(payload)))] if legacy else [
        ("image_files", ("boundary.png", payload, "image/png")),
    ]
    response = client.post("/ai-chat/log-analysis/stream", headers={"X-App-Locale": locale}, files=files)
    if not excess:
        assert response.status_code == 200, response.text
        assert len(base64.b64decode(captured[0]["images"][0].data)) == MIB
    else:
        assert response.status_code == 413
        error = response.json()
        assert error["reason"] == "image_too_large"
        assert str(MIB + 1) in error["message"]
        assert "1 MiB" in error["message"]
        assert ("第 1 张" if locale == "zh" else "Image 1") in error["message"]
        assert ("压缩" if locale == "zh" else "Compress") in error["message"]
        assert not captured


def test_legacy_capacity_tracks_larger_configured_image_budget(upload_api, monkeypatch):
    client, captured = upload_api
    monkeypatch.setattr(settings, "ocr_max_images", 1)
    monkeypatch.setattr(settings, "ocr_max_image_mb", 13)
    payload = b"x" * (13 * MIB)
    response = client.post("/ai-chat/log-analysis/stream", files=[("images", (None, image_json(payload)))])
    assert response.status_code == 200, response.text
    assert len(base64.b64decode(captured[0]["images"][0].data)) == len(payload)


@pytest.mark.parametrize("locale", ["zh", "en"])
def test_mixed_image_inputs_count_together(upload_api, monkeypatch, locale):
    client, captured = upload_api
    monkeypatch.setattr(settings, "ocr_max_images", 1)
    response = client.post("/ai-chat/log-analysis/stream", headers={"X-App-Locale": locale}, files=[
        ("images", (None, image_json(b"a"))),
        ("image_files", ("b.png", b"b", "image/png")),
    ])
    assert response.status_code == 400
    error = response.json()
    assert error["reason"] == "too_many_images"
    assert "2" in error["message"] and "1" in error["message"]
    assert ("分批" if locale == "zh" else "separate turns") in error["message"]
    assert not captured


@pytest.mark.parametrize("locale", ["zh", "en"])
@pytest.mark.parametrize("field", ["history", "images"])
def test_form_overflow_is_explicit_and_prevents_agent_start(upload_api, monkeypatch, locale, field):
    client, captured = upload_api
    monkeypatch.setattr(chat_uploads, "multipart_field_limit", lambda: 2 * MIB)
    response = client.post("/ai-chat/log-analysis/stream", headers={"X-App-Locale": locale}, files=[
        (field, (None, "x" * (2 * MIB + 1))),
    ])
    assert response.status_code == 413
    error = response.json()
    assert error["reason"] == "multipart_field_too_large"
    assert error["max_bytes"] == 2 * MIB
    assert "2 MiB" in error["message"]
    assert ("刷新页面" if locale == "zh" else "Refresh") in error["message"]
    assert not captured


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_invalid_binary_type_is_actionable(upload_api, endpoint):
    client, captured = upload_api
    response = client.post(f"/ai-chat/{endpoint}/stream", headers={"X-App-Locale": "en"},
        data={"project_repo_id": "1"}, files=[("image_files", ("image.svg", b"<svg/>", "image/svg+xml"))])
    assert response.status_code == 400
    assert response.json()["reason"] == "unsupported_type"
    assert "PNG" in response.json()["message"]
    assert not captured


def test_malformed_legacy_images_are_localized(upload_api):
    client, captured = upload_api
    response = client.post("/ai-chat/log-analysis/stream", headers={"X-App-Locale": "en"},
        files=[("images", (None, "{bad-json"))])
    assert response.status_code == 400
    assert response.json()["reason"] == "invalid_images_payload"
    assert "Select the images again" in response.json()["message"]
    assert not captured
