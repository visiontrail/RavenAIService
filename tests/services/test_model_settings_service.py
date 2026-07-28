"""Tests for the Admin-editable model settings + the config overlay.

Verifies that runtime overrides persisted through
``model_settings_service`` win over the ``.env`` bootstrap defaults when read
via ``settings.<key>`` (the :meth:`app.config.Settings.__getattribute__`
overlay), that secrets are masked on read, that validation fires, and that
``reset`` reverts everything to the env defaults.
"""

from __future__ import annotations

import json

import pytest

from app.config import OVERRIDABLE_MODEL_KEYS, settings
from app.services import model_settings_service as mss
from app.services import runtime_settings_service


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Point the runtime store at a temp file and clear its module cache."""
    runtime_path = tmp_path / "runtime-settings.json"
    monkeypatch.setattr(settings, "runtime_settings_path", str(runtime_path))
    monkeypatch.setattr(runtime_settings_service, "_CACHE", None)
    monkeypatch.setattr(runtime_settings_service, "_CACHE_MTIME", 0.0)
    monkeypatch.setattr(runtime_settings_service, "_CACHE_PATH", None)
    yield runtime_path


def test_key_lists_are_in_sync():
    assert mss.OVERRIDABLE_KEYS == OVERRIDABLE_MODEL_KEYS


def test_no_override_falls_back_to_env(isolated_store):
    env_provider = object.__getattribute__(settings, "anthropic_provider")
    # With an empty store the overlay must return the raw env/default value.
    assert settings.anthropic_provider == env_provider
    describe = mss.describe()
    assert describe["fields"]["anthropic_provider"]["source"] == "env"


def test_override_wins_via_overlay(isolated_store):
    mss.save(
        {
            "anthropic_provider": "deepseek",
            "anthropic_model": "deepseek-v4-pro",
            "anthropic_max_tokens": 4096,
        }
    )
    # Every consumer reads settings.<key>; those must now see the override.
    assert settings.anthropic_provider == "deepseek"
    assert settings.anthropic_model == "deepseek-v4-pro"
    assert settings.anthropic_max_tokens == 4096

    fields = mss.describe()["fields"]
    assert fields["anthropic_provider"]["source"] == "override"
    assert fields["anthropic_provider"]["value"] == "deepseek"


def test_secret_is_masked_and_persisted(isolated_store):
    mss.save({"anthropic_api_key": "sk-secret-xyz"})
    # The overlay exposes the real key to the app...
    assert settings.anthropic_api_key == "sk-secret-xyz"
    # ...but describe() never returns it, only an is_set flag.
    entry = mss.describe()["fields"]["anthropic_api_key"]
    assert entry["is_set"] is True
    assert "value" not in entry
    assert entry["source"] == "override"


def test_blank_secret_keeps_existing_key(isolated_store):
    mss.save({"anthropic_api_key": "sk-first"})
    # Sending an empty string must not wipe the stored key.
    mss.save({"anthropic_api_key": "", "anthropic_model": "some-model"})
    assert settings.anthropic_api_key == "sk-first"
    assert settings.anthropic_model == "some-model"


def test_custom_provider_requires_base_url_and_model(isolated_store):
    with pytest.raises(ValueError, match="custom"):
        mss.save({"anthropic_provider": "custom", "anthropic_base_url": "", "anthropic_model": ""})


def test_custom_provider_accepts_full_config(isolated_store):
    mss.save(
        {
            "anthropic_provider": "custom",
            "anthropic_base_url": "https://example.test/anthropic",
            "anthropic_model": "my-model",
        }
    )
    assert settings.anthropic_provider == "custom"
    assert settings.anthropic_base_url == "https://example.test/anthropic"


def test_invalid_provider_rejected(isolated_store):
    with pytest.raises(ValueError):
        mss.save({"anthropic_provider": "not-a-provider"})


def test_max_tokens_bounds(isolated_store):
    with pytest.raises(ValueError):
        mss.save({"anthropic_max_tokens": 0})
    with pytest.raises(ValueError):
        mss.save({"anthropic_max_tokens": 10**9})


def test_unknown_key_rejected(isolated_store):
    with pytest.raises(ValueError, match="未知"):
        mss.save({"totally_unknown_key": "x"})


def test_ocr_bool_coercion_and_reset(isolated_store):
    env_ocr = object.__getattribute__(settings, "ocr_enabled")
    mss.save({"ocr_enabled": False})
    assert settings.ocr_enabled is False

    mss.reset()
    # After reset every key reverts to its env/default value.
    assert settings.ocr_enabled == env_ocr
    assert runtime_settings_service.get_all() == {}
    for key in OVERRIDABLE_MODEL_KEYS:
        assert mss.describe()["fields"][key]["source"] in {"env", "unset"}


# ─────────────────────────── Provider catalogue ────────────────────────────


def test_provider_list_matches_profiles():
    """The Admin dropdown and the runtime capability matrix must agree.

    A provider selectable here but missing from ``PROVIDER_PROFILES`` would fall
    into ``build_options``' most-restrictive fallback at the first chat turn.
    """
    from app.agents.anthropic_client import PROVIDER_PROFILES

    assert mss.ANTHROPIC_PROVIDERS == tuple(PROVIDER_PROFILES)


@pytest.mark.parametrize(
    "provider,base_url,model",
    [
        ("aliyun", "cn-beijing.maas.aliyuncs.com/apps/anthropic", "qwen3.7-max"),
        ("zhipu", "https://open.bigmodel.cn/api/anthropic", "glm-5.2"),
        ("moonshot", "https://api.moonshot.cn/anthropic", "kimi-k3"),
        ("minimax", "https://api.minimaxi.com/anthropic", "MiniMax-M3"),
        ("stepfun", "https://api.stepfun.com", "step-3.7-flash"),
        ("mimo", "https://api.xiaomimimo.com/anthropic", "mimo-v2.5-pro"),
        ("hunyuan", "https://api.hunyuan.cloud.tencent.com/anthropic", "hunyuan-2.0-thinking-20251109"),
        ("yinhe", "http://oneapi.yhroot.com", "yinhe-thinking"),
    ],
)
def test_new_provider_defaults(provider, base_url, model):
    from app.agents.anthropic_client import PROVIDER_PROFILES

    profile = PROVIDER_PROFILES[provider]
    assert base_url in profile.default_base_url
    assert profile.default_model == model
    # The flagship must be offered as a preset, and SDK in-process MCP tools
    # work on every Anthropic-compatible gateway.
    assert model in profile.models
    assert profile.supports_mcp_server_tools is True


def test_describe_exposes_presets_for_dropdown(isolated_store):
    profiles = {p["name"]: p for p in mss.describe()["provider_profiles"]}
    assert set(profiles) == set(mss.ANTHROPIC_PROVIDERS)

    aliyun = profiles["aliyun"]
    assert aliyun["label"]
    assert "qwen3.7-flash" in aliyun["models"]
    # 百炼's endpoint is a template — the form must warn before saving it.
    assert aliyun["base_url_needs_input"] is True
    assert profiles["zhipu"]["base_url_needs_input"] is False


def test_new_provider_is_saveable(isolated_store):
    mss.save({"anthropic_provider": "moonshot", "anthropic_model": "kimi-k3"})
    assert settings.anthropic_provider == "moonshot"
    assert settings.anthropic_model == "kimi-k3"


def test_unfilled_base_url_placeholder_rejected(isolated_store):
    # Explicitly typed…
    with pytest.raises(ValueError, match="占位符"):
        mss.save(
            {
                "anthropic_provider": "aliyun",
                "anthropic_base_url": "https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/apps/anthropic",
            }
        )
    # …and left blank, which resolves to the same template at call time.
    with pytest.raises(ValueError, match="占位符"):
        mss.save({"anthropic_provider": "aliyun", "anthropic_base_url": ""})

    # A filled-in workspace id saves fine.
    mss.save(
        {
            "anthropic_provider": "aliyun",
            "anthropic_base_url": "https://ws-123.cn-beijing.maas.aliyuncs.com/apps/anthropic",
        }
    )
    assert settings.anthropic_provider == "aliyun"


# ─────────────────────────── Connectivity test ─────────────────────────────


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


@pytest.fixture
def blank_model_env(monkeypatch):
    """Blank the ``.env`` bootstrap values for the probe tests.

    Without this a developer machine's real ANTHROPIC_* / OCR_* settings leak
    into the fallback chain and the assertions become environment-dependent.
    """
    for key in (
        "anthropic_api_key",
        "anthropic_base_url",
        "anthropic_model",
        "ocr_api_key",
        "ocr_base_url",
        "ocr_model",
    ):
        monkeypatch.setattr(settings, key, "")


@pytest.fixture
def fake_upstream(monkeypatch):
    """Stub httpx so the probe never touches the network.

    Returns ``(box, calls)``: set ``box['response']`` / ``box['exc']`` to shape
    the upstream, and read ``calls`` to assert what was actually sent.
    """
    import httpx

    # Default: a healthy Anthropic-shaped reply, so tests about routing and
    # auth only have to override the interesting cases.
    calls: list = []
    box: dict = {
        "response": _FakeResponse(payload={"content": [{"type": "text", "text": "pong"}]}),
        "exc": None,
    }

    class _Client:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, json=None, headers=None):  # noqa: A002
            calls.append({"url": url, "body": json, "headers": headers})
            if box["exc"] is not None:
                raise box["exc"]
            return box["response"]

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return box, calls


async def test_anthropic_probe_uses_form_values_and_sdk_auth(isolated_store, blank_model_env, fake_upstream):
    box, calls = fake_upstream
    box["response"] = _FakeResponse(
        payload={"content": [{"type": "text", "text": "pong"}], "usage": {"input_tokens": 3}}
    )

    result = await mss.test_connection(
        {
            "target": "anthropic",
            "provider": "moonshot",
            "base_url": "https://api.moonshot.cn/anthropic/",
            "model": "kimi-k3",
            "api_key": "sk-typed",
        }
    )

    assert result["ok"] is True
    assert result["reply"] == "pong"
    assert result["model"] == "kimi-k3"
    assert result["usage"] == {"input_tokens": 3}

    sent = calls[0]
    assert sent["url"] == "https://api.moonshot.cn/anthropic/v1/messages"
    # Must mirror what the Claude Agent SDK sends, or a green test would not
    # imply a working agent run.
    assert sent["headers"]["x-api-key"] == "sk-typed"
    assert sent["headers"]["anthropic-version"] == "2023-06-01"
    assert sent["body"]["model"] == "kimi-k3"


async def test_anthropic_probe_falls_back_to_saved_key_and_provider_defaults(
    isolated_store, blank_model_env, fake_upstream, monkeypatch
):
    _box, calls = fake_upstream
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-stored")

    # Blank base_url / model → the provider profile defaults, exactly as
    # build_options resolves them at call time.
    result = await mss.test_connection(
        {"target": "anthropic", "provider": "zhipu", "base_url": "", "model": ""}
    )

    assert result["ok"] is True
    assert result["model"] == "glm-5.2"
    assert calls[0]["url"] == "https://open.bigmodel.cn/api/anthropic/v1/messages"
    assert calls[0]["headers"]["x-api-key"] == "sk-stored"


async def test_anthropic_probe_reports_upstream_error(isolated_store, blank_model_env, fake_upstream, monkeypatch):
    box, _calls = fake_upstream
    box["response"] = _FakeResponse(
        status_code=401, payload={"error": {"message": "invalid api key"}}
    )
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-bad")

    result = await mss.test_connection({"target": "anthropic", "provider": "zhipu"})

    assert result["ok"] is False
    assert result["error_kind"] == "http_401"
    assert result["status_code"] == 401
    assert "invalid api key" in result["detail"]
    # The key must never be echoed back to the browser.
    assert "sk-bad" not in json.dumps(result)


async def test_anthropic_probe_reports_timeout(isolated_store, blank_model_env, fake_upstream, monkeypatch):
    import httpx

    box, _calls = fake_upstream
    box["exc"] = httpx.TimeoutException("too slow")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-x")

    result = await mss.test_connection({"target": "anthropic", "provider": "zhipu"})
    assert result["ok"] is False
    assert result["error_kind"] == "timeout"


async def test_probe_flags_missing_key_and_placeholder_without_calling_upstream(
    isolated_store, blank_model_env, fake_upstream, monkeypatch
):
    _box, calls = fake_upstream

    no_key = await mss.test_connection({"target": "anthropic", "provider": "zhipu"})
    assert (no_key["ok"], no_key["error_kind"]) == (False, "missing_api_key")

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-x")
    unfilled = await mss.test_connection({"target": "anthropic", "provider": "aliyun"})
    assert (unfilled["ok"], unfilled["error_kind"]) == (False, "placeholder_base_url")

    assert calls == []


async def test_ocr_probe_hits_chat_completions(isolated_store, blank_model_env, fake_upstream):
    box, calls = fake_upstream
    box["response"] = _FakeResponse(
        payload={"choices": [{"message": {"role": "assistant", "content": "pong"}}]}
    )

    result = await mss.test_connection(
        {
            "target": "ocr",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen3.5-ocr",
            "api_key": "sk-ocr",
        }
    )

    assert result["ok"] is True
    assert result["reply"] == "pong"
    assert calls[0]["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-ocr"
    # A text-only ping: no image is ever shipped to the upstream.
    assert calls[0]["body"]["messages"] == [{"role": "user", "content": "ping"}]


async def test_unknown_target_rejected(isolated_store, blank_model_env, fake_upstream):
    with pytest.raises(ValueError, match="target"):
        await mss.test_connection({"target": "nope"})
