from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def _load_migration():
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260714_000000_add_user_announcement_ack.py"
    )
    spec = importlib.util.spec_from_file_location(
        "add_user_announcement_ack_migration", migration_path
    )
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _create_legacy_users(conn) -> None:
    conn.execute(
        text(
            "CREATE TABLE users ("
            "id VARCHAR(36) PRIMARY KEY, "
            "username VARCHAR(128) NOT NULL, "
            "password_hash VARCHAR(255) NOT NULL"
            ")"
        )
    )
    conn.execute(
        text(
            "INSERT INTO users (id, username, password_hash) "
            "VALUES ('user-1', 'alice', 'hash')"
        )
    )


def test_announcement_ack_migration_is_additive_and_idempotent(tmp_path) -> None:
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'announcement-migration.db'}")

    with engine.begin() as conn:
        _create_legacy_users(conn)
        migration.op = Operations(MigrationContext.configure(conn))

        migration.upgrade()
        migration.upgrade()

        columns = {column["name"]: column for column in inspect(conn).get_columns("users")}
        assert columns["last_seen_announcement_id"]["nullable"] is True
        assert conn.execute(text("SELECT username FROM users")).scalar_one() == "alice"

        migration.downgrade()
        migration.downgrade()
        columns = {column["name"] for column in inspect(conn).get_columns("users")}
        assert "last_seen_announcement_id" not in columns
        assert conn.execute(text("SELECT username FROM users")).scalar_one() == "alice"
