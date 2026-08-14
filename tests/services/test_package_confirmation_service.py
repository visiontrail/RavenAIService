"""Confirmation signatures bind the exact human-approved package plan."""

from __future__ import annotations

import pytest

from app.services.package_confirmation_service import (
    PackageConfirmationError,
    sign_confirmed_plan,
    verify_confirmed_plan,
)


def _plan() -> dict:
    return {
        "plan_hash": "plan-1",
        "confirmation_hash": "answer-1",
        "run_id": "run-1",
        "session_id": "session-1",
        "user_id": "user-1",
        "project_code": "lingxi-10",
        "version": "1.0.0.3",
        "inputs": [
            {
                "upload_id": "input-1",
                "sha256": "abc",
                "selected_components": ["oam"],
                "include": True,
            }
        ],
    }


def test_signed_plan_verifies_in_bound_scope():
    signed = sign_confirmed_plan(_plan(), ttl_seconds=30, now=100)
    verify_confirmed_plan(
        signed,
        expected_run_id="run-1",
        expected_session_id="session-1",
        expected_user_id="user-1",
        now=110,
    )


def test_mapping_change_after_confirmation_is_rejected():
    signed = sign_confirmed_plan(_plan(), ttl_seconds=30, now=100)
    signed["inputs"][0]["selected_components"] = ["cuup"]
    with pytest.raises(PackageConfirmationError) as caught:
        verify_confirmed_plan(signed, now=110)
    assert caught.value.code == "tampered_plan"


def test_expired_or_wrong_run_confirmation_is_rejected():
    signed = sign_confirmed_plan(_plan(), ttl_seconds=30, now=100)
    with pytest.raises(PackageConfirmationError) as expired:
        verify_confirmed_plan(signed, now=131)
    assert expired.value.code == "expired"

    with pytest.raises(PackageConfirmationError) as mismatch:
        verify_confirmed_plan(signed, expected_run_id="run-2", now=110)
    assert mismatch.value.code == "scope_mismatch"


def test_confirmation_uses_independent_secret_and_production_rejects_missing(
    monkeypatch,
):
    from app.config import settings

    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "package_confirmation_secret", "p" * 32)
    monkeypatch.setattr(settings, "secret_key", "login-secret-one")
    signed = sign_confirmed_plan(_plan(), ttl_seconds=30, now=100)

    # Login/session secret rotation does not invalidate package confirmation.
    monkeypatch.setattr(settings, "secret_key", "login-secret-two")
    verify_confirmed_plan(signed, now=110)

    monkeypatch.setattr(settings, "package_confirmation_secret", "q" * 32)
    with pytest.raises(PackageConfirmationError) as changed:
        verify_confirmed_plan(signed, now=110)
    assert changed.value.code == "tampered_plan"

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "package_confirmation_secret", None)
    with pytest.raises(PackageConfirmationError) as missing:
        sign_confirmed_plan(_plan(), ttl_seconds=30, now=100)
    assert missing.value.code == "misconfigured_secret"


def test_production_rejects_confirmation_secret_equal_to_login_secret(monkeypatch):
    from app import config

    shared = "same-secret-must-not-cross-authority-boundaries"
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", shared)
    monkeypatch.setenv("PACKAGE_CONFIRMATION_SECRET", shared)

    with pytest.raises(RuntimeError, match="independent random secret"):
        config.get_settings()
