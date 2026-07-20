"""Tests for the attached-image store (openspec/changes/add-multimodal-image-input).

Covers the persistence path that lets a user's images reappear in the bubble on
a history reload, and the provider-gated workspace materialization that lays the
groundwork for a future multimodal agent path.
"""

from __future__ import annotations

import base64
import json

import pytest

from app.models.chat import ImageAttachment
from app.services import chat_image_store


PNG_BYTES = b"\x89PNG\r\n\x1a\n-fake-payload"


def _img(data: bytes = PNG_BYTES, media_type: str = "image/png") -> ImageAttachment:
    return ImageAttachment(media_type=media_type, data=base64.b64encode(data).decode())


@pytest.fixture
def store_dir(tmp_path, monkeypatch):
    """Point the store at an isolated temp directory."""
    from app.config import settings

    monkeypatch.setattr(settings, "chat_image_store_dir", str(tmp_path), raising=False)
    return tmp_path


# ─────────────────────────── save / load round-trip ───────────────────────────


def test_save_turn_images_writes_bytes_and_returns_metadata(store_dir):
    stored = chat_image_store.save_turn_images([_img(), _img(b"second")], session_id="s1")

    assert len(stored) == 2
    for item in stored:
        assert item.media_type == "image/png"
        assert item.size > 0
    assert stored[0].name == "image-1.png"
    # Bytes land under the session directory and match the input exactly.
    from pathlib import Path

    assert Path(stored[0].path).read_bytes() == PNG_BYTES
    assert Path(stored[1].path).read_bytes() == b"second"


def test_save_turn_images_accepts_data_url_prefixed_payloads(store_dir):
    prefixed = ImageAttachment(
        media_type="image/png",
        data="data:image/png;base64," + base64.b64encode(PNG_BYTES).decode(),
    )
    stored = chat_image_store.save_turn_images([prefixed], session_id="s1")

    from pathlib import Path

    assert Path(stored[0].path).read_bytes() == PNG_BYTES


def test_no_images_stores_nothing(store_dir):
    assert chat_image_store.save_turn_images([], session_id="s1") == []
    assert chat_image_store.save_turn_images(None, session_id="s1") == []
    assert chat_image_store.to_meta_json([]) is None


def test_meta_json_round_trip_drops_local_path(store_dir):
    stored = chat_image_store.save_turn_images([_img()], session_id="s1")
    raw = chat_image_store.to_meta_json(stored)

    parsed = chat_image_store.parse_meta_json(raw)
    assert len(parsed) == 1
    # The on-disk path must never reach the client.
    assert "path" not in parsed[0]
    assert set(parsed[0]) == {"id", "media_type", "name", "size"}


def test_parse_meta_json_tolerates_garbage(store_dir):
    assert chat_image_store.parse_meta_json(None) == []
    assert chat_image_store.parse_meta_json("") == []
    assert chat_image_store.parse_meta_json("not json") == []
    assert chat_image_store.parse_meta_json('{"not": "a list"}') == []


def test_resolve_path_finds_stored_image(store_dir):
    stored = chat_image_store.save_turn_images([_img()], session_id="s1")

    resolved = chat_image_store.resolve_path("s1", stored[0].id)
    assert resolved is not None and resolved.read_bytes() == PNG_BYTES
    # Wrong session must not reach another session's bytes.
    assert chat_image_store.resolve_path("other", stored[0].id) is None


@pytest.mark.parametrize(
    "hostile_id",
    ["../../etc/passwd", "a/b", "..", "abc.png", "abc/../def"],
)
def test_resolve_path_rejects_traversal(store_dir, hostile_id):
    chat_image_store.save_turn_images([_img()], session_id="s1")
    assert chat_image_store.resolve_path("s1", hostile_id) is None


def test_delete_session_images_is_idempotent(store_dir):
    stored = chat_image_store.save_turn_images([_img()], session_id="s1")

    chat_image_store.delete_session_images("s1")
    assert chat_image_store.resolve_path("s1", stored[0].id) is None
    # Deleting again (or a session that never had images) must not raise.
    chat_image_store.delete_session_images("s1")
    chat_image_store.delete_session_images("never-existed")


# ──────────────────── workspace materialization gating ────────────────────


def _set_provider(monkeypatch, provider: str, enabled: bool = True):
    from app.config import settings

    monkeypatch.setattr(settings, "anthropic_provider", provider, raising=False)
    monkeypatch.setattr(
        settings, "chat_image_workspace_materialize", enabled, raising=False
    )


def test_materialize_copies_images_for_vision_capable_provider(
    store_dir, tmp_path, monkeypatch
):
    _set_provider(monkeypatch, "anthropic")
    stored = chat_image_store.save_turn_images([_img(), _img(b"two")], session_id="s1")
    workspace = tmp_path / "ws"
    workspace.mkdir()

    result = chat_image_store.materialize_into_workspace(stored, str(workspace))

    assert result is not None
    images_dir = workspace / "images"
    assert (images_dir / "image_1.png").read_bytes() == PNG_BYTES
    assert (images_dir / "image_2.png").read_bytes() == b"two"
    manifest = json.loads((images_dir / "manifest.json").read_text(encoding="utf-8"))
    assert [entry["file"] for entry in manifest] == ["image_1.png", "image_2.png"]


@pytest.mark.parametrize("provider", ["deepseek", "custom"])
def test_materialize_skipped_for_non_vision_provider(
    store_dir, tmp_path, monkeypatch, provider
):
    """A non-vision upstream fails the whole run if an agent Reads an image, so
    those providers must never get an ``images/`` directory to stumble into."""
    _set_provider(monkeypatch, provider)
    stored = chat_image_store.save_turn_images([_img()], session_id="s1")
    workspace = tmp_path / "ws"
    workspace.mkdir()

    assert chat_image_store.materialize_into_workspace(stored, str(workspace)) is None
    assert not (workspace / "images").exists()


def test_materialize_respects_explicit_disable(store_dir, tmp_path, monkeypatch):
    _set_provider(monkeypatch, "anthropic", enabled=False)
    stored = chat_image_store.save_turn_images([_img()], session_id="s1")
    workspace = tmp_path / "ws"
    workspace.mkdir()

    assert chat_image_store.materialize_into_workspace(stored, str(workspace)) is None
    assert not (workspace / "images").exists()


def test_materialize_no_images_is_noop(store_dir, tmp_path, monkeypatch):
    _set_provider(monkeypatch, "anthropic")
    workspace = tmp_path / "ws"
    workspace.mkdir()

    assert chat_image_store.materialize_into_workspace([], str(workspace)) is None
    assert not (workspace / "images").exists()
