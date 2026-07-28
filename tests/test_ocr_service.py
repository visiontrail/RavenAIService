"""Unit tests for ``app/services/ocr_service.py`` and the image validation helpers.

Covers openspec/changes/add-multimodal-image-input tasks 6.2 and 6.3:

- ``is_configured()`` across the enabled/key/disabled branches.
- ``extract_text`` success, timeout degrade, non-2xx degrade, and unconfigured,
  plus that AI-usage metering fires on the success/failure paths (mock httpx)
  and NOT on the unconfigured path.
- ``validate_images`` MIME/size/count enforcement.
- ``enrich_message`` merge format and the no-images / unconfigured / failed
  degradation branches.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from app.models.chat import (
    ImageAttachment,
    ImageValidationError,
    validate_images,
)
from app.services import ocr_service


# ──────────────────────────── helpers ────────────────────────────


def _img(media_type: str = "image/png", raw: bytes = b"hello") -> ImageAttachment:
    return ImageAttachment(media_type=media_type, data=base64.b64encode(raw).decode())


def _configure_ocr(monkeypatch, *, enabled=True, key="k", model="qwen-vl-max", base="http://ocr.test/v1"):
    monkeypatch.setattr("app.config.settings.ocr_enabled", enabled)
    monkeypatch.setattr("app.config.settings.ocr_api_key", key)
    monkeypatch.setattr("app.config.settings.ocr_model", model)
    monkeypatch.setattr("app.config.settings.ocr_base_url", base)
    monkeypatch.setattr("app.config.settings.ocr_request_timeout_seconds", 5)
    monkeypatch.setattr("app.config.settings.ocr_max_tokens", 256)


class _FakeResponse:
    def __init__(self, *, json_data=None, raise_status=None, error_json=None):
        self._json = json_data or {}
        self._error_json = error_json
        self._raise_status = raise_status
        self.status_code = 200 if raise_status is None else raise_status

    def raise_for_status(self):
        if self._raise_status is not None:
            request = httpx.Request("POST", "http://ocr.test/v1/chat/completions")
            response = httpx.Response(
                self._raise_status,
                request=request,
                json=self._error_json or {},
            )
            raise httpx.HTTPStatusError("err", request=request, response=response)

    def json(self):
        if self._error_json is not None:
            return self._error_json
        return self._json


def _patch_httpx(monkeypatch, *, post):
    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            return await post(url, json, headers)

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)


def _capture_metrics(monkeypatch):
    calls = []

    async def _fake_record(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("app.services.metrics_service.record_ai_usage", _fake_record)
    return calls


# ──────────────────────── is_configured ────────────────────────


def test_is_configured_true_when_all_present(monkeypatch):
    _configure_ocr(monkeypatch)
    assert ocr_service.is_configured() is True


def test_is_configured_false_when_key_missing(monkeypatch):
    _configure_ocr(monkeypatch, key=None)
    assert ocr_service.is_configured() is False


def test_is_configured_false_when_disabled(monkeypatch):
    _configure_ocr(monkeypatch, enabled=False)
    assert ocr_service.is_configured() is False


# ──────────────────────── extract_text ────────────────────────


async def test_extract_text_success_returns_text_and_meters(monkeypatch):
    _configure_ocr(monkeypatch)
    metrics = _capture_metrics(monkeypatch)

    async def _post(url, json, headers):
        assert url == "http://ocr.test/v1/chat/completions"
        assert headers["Authorization"] == "Bearer k"
        # one text block + one image_url block per image
        content = json["messages"][0]["content"]
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
        return _FakeResponse(
            json_data={
                "choices": [{"message": {"content": "[图片 1]\nERROR 500"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        )

    _patch_httpx(monkeypatch, post=_post)

    result = await ocr_service.extract_text([_img()], user_text="what is this?")
    assert result.status == "succeeded"
    assert "ERROR 500" in result.text
    assert result.image_count == 1
    assert len(metrics) == 1
    assert metrics[0]["source"] == "ocr"
    assert metrics[0]["status"] == "succeeded"
    assert metrics[0]["agent_kind"] == "ocr"


async def test_extract_text_timeout_degrades_and_meters(monkeypatch):
    _configure_ocr(monkeypatch)
    metrics = _capture_metrics(monkeypatch)

    async def _post(url, json, headers):
        raise httpx.TimeoutException("timed out")

    _patch_httpx(monkeypatch, post=_post)

    result = await ocr_service.extract_text([_img()], user_text="q")
    assert result.status == "failed"
    assert result.error_kind == "timeout"
    assert result.text == ""
    assert len(metrics) == 1
    assert metrics[0]["status"] == "failed"
    assert metrics[0]["error_kind"] == "timeout"


async def test_extract_text_non_2xx_degrades_and_meters(monkeypatch):
    _configure_ocr(monkeypatch)
    metrics = _capture_metrics(monkeypatch)

    async def _post(url, json, headers):
        return _FakeResponse(raise_status=500)

    _patch_httpx(monkeypatch, post=_post)

    result = await ocr_service.extract_text([_img()], user_text="q")
    assert result.status == "failed"
    assert result.error_kind == "http_500"
    assert len(metrics) == 1
    assert metrics[0]["status"] == "failed"


async def test_extract_text_preserves_safe_upstream_error_code(monkeypatch):
    _configure_ocr(monkeypatch)
    metrics = _capture_metrics(monkeypatch)

    async def _post(url, json, headers):
        return _FakeResponse(
            raise_status=404,
            error_json={"error": {"code": "model_not_found", "message": "secret detail"}},
        )

    _patch_httpx(monkeypatch, post=_post)

    result = await ocr_service.extract_text([_img()], user_text="q")
    assert result.status == "failed"
    assert result.error_kind == "model_not_found"
    assert metrics[0]["error_kind"] == "model_not_found"


async def test_extract_text_unconfigured_returns_without_metering(monkeypatch):
    _configure_ocr(monkeypatch, key=None)
    metrics = _capture_metrics(monkeypatch)

    result = await ocr_service.extract_text([_img()], user_text="q")
    assert result.status == "unconfigured"
    assert result.text == ""
    assert metrics == []


# ──────────────────────── validate_images ────────────────────────


def test_validate_images_rejects_unsupported_type():
    with pytest.raises(ImageValidationError) as exc:
        validate_images([_img(media_type="application/pdf")])
    assert exc.value.reason == "unsupported_type"


def test_validate_images_rejects_oversize(monkeypatch):
    monkeypatch.setattr("app.config.settings.ocr_max_image_mb", 1)
    big = ImageAttachment(media_type="image/png", data=base64.b64encode(b"x" * (2 * 1024 * 1024)).decode())
    with pytest.raises(ImageValidationError) as exc:
        validate_images([big])
    assert exc.value.reason == "image_too_large"


def test_validate_images_rejects_too_many(monkeypatch):
    monkeypatch.setattr("app.config.settings.ocr_max_images", 2)
    with pytest.raises(ImageValidationError) as exc:
        validate_images([_img(), _img(), _img()])
    assert exc.value.reason == "too_many_images"


def test_validate_images_accepts_valid():
    # None and a valid small list both pass.
    validate_images(None)
    validate_images([_img(media_type="image/jpeg"), _img(media_type="image/webp")])


# ──────────────────────── enrich_message ────────────────────────


async def test_enrich_message_merges_ocr_block_on_success(monkeypatch):
    _configure_ocr(monkeypatch)

    async def _fake_extract(images, **kwargs):
        return ocr_service.OcrResult(
            text="[图片 1]\nCODE 42", status="succeeded", image_count=len(images)
        )

    monkeypatch.setattr(ocr_service, "extract_text", _fake_extract)

    merged, meta = await ocr_service.enrich_message("原始问题", [_img()])
    assert meta.status == "succeeded"
    assert meta.image_count == 1
    assert meta.text == "[图片 1]\nCODE 42"
    assert merged.startswith("原始问题")
    assert "<user_image_ocr" in merged
    assert 'note="' in merged
    assert "CODE 42" in merged
    assert merged.rstrip().endswith("</user_image_ocr>")


async def test_enrich_message_no_images_is_skipped():
    merged, meta = await ocr_service.enrich_message("只有文字", [])
    assert merged == "只有文字"
    assert meta.status == "skipped"
    assert meta.image_count == 0


async def test_enrich_message_unconfigured_degrades(monkeypatch):
    _configure_ocr(monkeypatch, key=None)
    merged, meta = await ocr_service.enrich_message("问题", [_img()])
    assert merged == "问题"
    assert meta.status == "unconfigured"
    assert meta.image_count == 1


async def test_enrich_message_failed_degrades(monkeypatch):
    _configure_ocr(monkeypatch)

    async def _fake_extract(images, **kwargs):
        return ocr_service.OcrResult(
            text="", status="failed", error_kind="timeout", image_count=len(images)
        )

    monkeypatch.setattr(ocr_service, "extract_text", _fake_extract)

    merged, meta = await ocr_service.enrich_message("问题", [_img()])
    assert merged == "问题"
    assert meta.status == "failed"
    assert meta.error_kind == "timeout"


# ──────────────── run correlation (admin audit merging) ────────────────


async def test_ocr_usage_carries_the_callers_run_id(monkeypatch):
    """The OCR event is metered under the run it preprocesses for.

    Sharing ``run_id`` with the agent event is what lets the admin audit feed
    fold the two into one row instead of showing OCR as its own invocation.
    """
    _configure_ocr(monkeypatch)
    metrics = _capture_metrics(monkeypatch)

    async def _post(url, json, headers):
        return _FakeResponse(
            json_data={
                "choices": [{"message": {"content": "[图片 1]\nERROR 500"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        )

    _patch_httpx(monkeypatch, post=_post)

    merged, meta = await ocr_service.enrich_message(
        "看看这个报错", [_img()], run_id="run-abc", session_id="sess-1"
    )
    assert meta.status == "succeeded"
    assert "ERROR 500" in merged
    assert metrics[0]["run_id"] == "run-abc"
    assert metrics[0]["metadata"] == {"image_count": 1}


async def test_ocr_failure_still_carries_run_id_and_image_count(monkeypatch):
    """A failed OCR call must stay attached to its run, not orphan itself."""
    _configure_ocr(monkeypatch)
    metrics = _capture_metrics(monkeypatch)

    async def _post(url, json, headers):
        raise httpx.TimeoutException("timed out")

    _patch_httpx(monkeypatch, post=_post)

    result = await ocr_service.extract_text(
        [_img(), _img()], user_text="q", run_id="run-xyz"
    )
    assert result.status == "failed"
    assert metrics[0]["run_id"] == "run-xyz"
    assert metrics[0]["metadata"] == {"image_count": 2}


async def test_ocr_usage_without_a_run_id_is_unattached(monkeypatch):
    """Callers with no run to attach to still meter, with a null run_id."""
    _configure_ocr(monkeypatch)
    metrics = _capture_metrics(monkeypatch)

    async def _post(url, json, headers):
        return _FakeResponse(
            json_data={"choices": [{"message": {"content": "text"}}], "usage": {}}
        )

    _patch_httpx(monkeypatch, post=_post)

    await ocr_service.extract_text([_img()], user_text="q")
    assert metrics[0]["run_id"] is None
