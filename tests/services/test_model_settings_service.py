"""Tests for the Admin-editable model settings + the config overlay.

Verifies that runtime overrides persisted through
``model_settings_service`` win over the ``.env`` bootstrap defaults when read
via ``settings.<key>`` (the :meth:`app.config.Settings.__getattribute__`
overlay), that secrets are masked on read, that validation fires, and that
``reset`` reverts everything to the env defaults.
"""

from __future__ import annotations

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
