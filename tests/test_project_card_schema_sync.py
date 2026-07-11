from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError

from app.models.database import DatabaseManager
from app.models.project_repo import ProjectRepo  # noqa: F401 - registers metadata


def _create_legacy_table(conn) -> None:
    conn.execute(
        text(
            "CREATE TABLE project_repo ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "project_code VARCHAR(128) NOT NULL, "
            "project_name VARCHAR(256) NOT NULL, "
            "repo_url TEXT NOT NULL, "
            "default_branch VARCHAR(128) NOT NULL DEFAULT 'main', "
            "git_token TEXT NULL, "
            "description TEXT NULL, "
            "enabled BOOLEAN NOT NULL DEFAULT 1, "
            "created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL"
            ")"
        )
    )
    conn.execute(
        text(
            "INSERT INTO project_repo "
            "(project_code, project_name, repo_url, description, created_at, updated_at) "
            "VALUES "
            "('alpha', 'Alpha', '', '  Alpha telemetry  ', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "('legacy', 'Legacy', '', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    )


def test_runtime_schema_sync_migrates_legacy_description_to_required_card(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as conn:
        _create_legacy_table(conn)
        conn.execute(
            text(
                "CREATE TABLE project_repo_agent ("
                "id INTEGER PRIMARY KEY, "
                "project_repo_id INTEGER NOT NULL REFERENCES project_repo(id) ON DELETE CASCADE, "
                "agent_key VARCHAR(64) NOT NULL, "
                "created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL"
                ")"
            )
        )
        conn.execute(
            text(
                "INSERT INTO project_repo_agent "
                "(id, project_repo_id, agent_key, created_at, updated_at) "
                "VALUES (1, 1, 'project_expert', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

        DatabaseManager._sync_columns_from_models(conn)

        columns = {column["name"]: column for column in inspect(conn).get_columns("project_repo")}
        rows = conn.execute(
            text("SELECT project_code, project_card FROM project_repo ORDER BY project_code")
        ).all()
        binding_count = conn.execute(text("SELECT COUNT(*) FROM project_repo_agent")).scalar_one()
        triggers = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
            ).all()
        }
        with pytest.raises(IntegrityError, match="project_card is required"):
            conn.execute(
                text(
                    "INSERT INTO project_repo "
                    "(project_code, project_name, repo_url, project_card, created_at, updated_at) "
                    "VALUES ('invalid', 'Invalid', '', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )

    assert "description" not in columns
    assert rows[0] == ("alpha", "Alpha telemetry")
    assert rows[1][0] == "legacy"
    assert "范围尚未补充" in rows[1][1]
    assert binding_count == 1
    assert DatabaseManager._PROJECT_CARD_INSERT_TRIGGER in triggers
    assert DatabaseManager._PROJECT_CARD_UPDATE_TRIGGER in triggers


def test_alembic_revision_upgrades_and_downgrades_project_card(tmp_path):
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260710_000000_require_project_card.py"
    )
    spec = importlib.util.spec_from_file_location("require_project_card_migration", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as conn:
        _create_legacy_table(conn)
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()

        upgraded = {column["name"]: column for column in inspect(conn).get_columns("project_repo")}
        rows = conn.execute(
            text("SELECT project_code, project_card FROM project_repo ORDER BY project_code")
        ).all()
        assert "description" not in upgraded
        assert rows[0] == ("alpha", "Alpha telemetry")
        assert "范围尚未补充" in rows[1][1]
        with pytest.raises(IntegrityError, match="project_card is required"):
            conn.execute(
                text(
                    "UPDATE project_repo SET project_card = '' "
                    "WHERE project_code = 'alpha'"
                )
            )

        migration.downgrade()
        downgraded = {column["name"]: column for column in inspect(conn).get_columns("project_repo")}
        assert "project_card" not in downgraded
        assert downgraded["description"]["nullable"] is True
