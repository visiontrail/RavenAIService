import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import mount_frontend_static_site, settings


def test_frontend_static_serving_disabled_by_default(monkeypatch, caplog):
    app = FastAPI()
    monkeypatch.setattr(settings, "serve_frontend", False)

    with caplog.at_level(logging.INFO, logger="app.main"):
        mount_frontend_static_site(app)

    assert "Backend frontend static serving is disabled" in caplog.text
    assert TestClient(app).get("/").status_code == 404


def test_enabled_frontend_static_serving_warns_when_dist_missing(monkeypatch, tmp_path, caplog):
    app = FastAPI()
    missing_dist = tmp_path / "missing-dist"
    monkeypatch.setattr(settings, "serve_frontend", True)
    monkeypatch.setattr(settings, "frontend_dist_dir", str(missing_dist))

    with caplog.at_level(logging.WARNING, logger="app.main"):
        mount_frontend_static_site(app)

    assert f"build directory was not found: {missing_dist}" in caplog.text
    assert TestClient(app).get("/").status_code == 404


def test_enabled_frontend_static_serving_mounts_spa(monkeypatch, tmp_path):
    app = FastAPI()
    dist_dir = tmp_path / "dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<!doctype html><div id=\"app\"></div>", encoding="utf-8")
    (assets_dir / "app.js").write_text("console.log('ok')", encoding="utf-8")
    monkeypatch.setattr(settings, "serve_frontend", True)
    monkeypatch.setattr(settings, "frontend_dist_dir", str(dist_dir))

    mount_frontend_static_site(app)

    client = TestClient(app)
    assert client.get("/assets/app.js").text == "console.log('ok')"
    response = client.get("/raven/packages")
    assert response.status_code == 200
    assert "<div id=\"app\"></div>" in response.text
    assert client.get("/api/unknown").status_code == 404
