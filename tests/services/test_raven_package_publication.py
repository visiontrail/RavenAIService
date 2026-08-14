"""Atomic repository publication tests for Configuration Manager artifacts."""

from __future__ import annotations

import json
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.services.raven_package_service import RavenPackageService
from app.services.package_confirmation_service import sign_confirmed_plan


@pytest.fixture
def service(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "raven_data_dir", str(tmp_path / "raven"))
    monkeypatch.setattr(
        settings,
        "raven_metadata_file",
        str(tmp_path / "raven" / "package-metadata.json"),
    )
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "raven" / "uploads"))
    monkeypatch.setattr(settings, "disk_reserve_bytes", 0)
    monkeypatch.setattr(settings, "upload_max_size_mb", 10)
    return RavenPackageService()


def _confirmed(index: int = 1) -> dict:
    return sign_confirmed_plan({
        "confirmation_hash": f"confirm-{index}",
        "plan_hash": f"plan-{index}",
        "run_id": f"run-{index}",
        "project_code": "lingxi-10",
        "version": "1.0.0.3",
        "mode": "full",
        "inputs": [
            {
                "upload_id": f"input-{index}",
                "original_name": f"component-{index}.zip",
                "sha256": f"source-{index}",
                "selected_component": "oam",
                "include": True,
            }
        ],
        "session_id": f"session-{index}",
        "user_id": "user-1",
    })


def _publish_from_process(source: str, confirmed_plan: dict) -> None:
    RavenPackageService().publish_built_package(
        Path(source),
        confirmed_plan=confirmed_plan,
        components=["oam"],
    )


def test_publish_requires_confirmation_and_rolls_back(service, tmp_path):
    source = tmp_path / "whole.tgz"
    source.write_bytes(b"not-a-real-tar-for-repository-boundary-test")

    with pytest.raises(ValueError, match="签名"):
        service.publish_built_package(
            source,
            confirmed_plan={"plan_hash": "plan-only"},
        )

    assert not service.metadata_file.exists()
    assert not service.uploads_dir.exists()


def test_publish_registers_hash_and_confirmation_audit(service, tmp_path):
    source = tmp_path / "GalaxySpace-Lx10-V1003.tgz"
    source.write_bytes(b"full-package")

    package = service.publish_built_package(
        source,
        confirmed_plan=_confirmed(),
        components=[{"name": "oam", "version": "1.0.0.3"}],
    )

    stored = service.get_package(package["id"])
    assert stored is not None
    assert service.package_file(stored).read_bytes() == b"full-package"
    assert stored["projectCode"] == "lingxi-10"
    assert stored["version"] == "1.0.0.3"
    assert stored["metadata"]["sha256"]
    assert (
        stored["metadata"]["customFields"]["packagingConfirmationHash"]
        == "confirm-1"
    )


def test_independent_services_publish_same_name_without_loss_or_collision(
    service, tmp_path
):
    services = [service, RavenPackageService()]
    sources = []
    for index in range(8):
        source_dir = tmp_path / f"source-{index}"
        source_dir.mkdir()
        path = source_dir / "GalaxySpace-Lx10-V1003.tgz"
        path.write_bytes(f"package-{index}".encode())
        sources.append(path)

    def publish(index: int):
        return services[index % len(services)].publish_built_package(
            sources[index],
            confirmed_plan=_confirmed(index),
            components=["oam"],
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        packages = list(pool.map(publish, range(8)))

    raw = json.loads(service.metadata_file.read_text(encoding="utf-8"))
    assert len(raw) == 8
    assert {item["id"] for item in raw} == {item["id"] for item in packages}
    assert len({item["name"] for item in raw}) == 8
    assert len({item["path"] for item in raw}) == 8
    assert all(service.package_file(item).exists() for item in raw)
    assert {
        service.package_file(item).read_bytes() for item in raw
    } == {f"package-{index}".encode() for index in range(8)}


@pytest.mark.skipif(os.name != "posix", reason="flock is a POSIX repository lock")
def test_separate_processes_publish_without_losing_json_entries(service, tmp_path):
    sources: list[Path] = []
    for index in range(4):
        source_dir = tmp_path / f"process-source-{index}"
        source_dir.mkdir()
        source = source_dir / "GalaxySpace-Lx10-V1003.tgz"
        source.write_bytes(f"process-package-{index}".encode())
        sources.append(source)

    context = multiprocessing.get_context("fork")
    processes = [
        context.Process(
            target=_publish_from_process,
            args=(str(source), _confirmed(index)),
        )
        for index, source in enumerate(sources)
    ]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=15)
        assert all(not process.is_alive() for process in processes)
        assert all(process.exitcode == 0 for process in processes)
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    raw = json.loads(service.metadata_file.read_text(encoding="utf-8"))
    assert len(raw) == 4
    assert len({item["name"] for item in raw}) == 4
    assert len({item["path"] for item in raw}) == 4
    assert {
        service.package_file(item).read_bytes() for item in raw
    } == {f"process-package-{index}".encode() for index in range(4)}
