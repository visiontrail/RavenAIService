"""Startup schema sync must drop retired columns that legacy indexes still cover.

Old databases carry indexes created by historical alembic revisions (e.g.
``idx_log_records_log_type``). SQLite refuses to drop a column those indexes
reference, and the whole sync runs in one transaction — so an un-cleaned index
used to take the entire service down on upgrade.
"""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from app.models.database import DatabaseManager


def _index_names(conn, table: str) -> set[str]:
    return {index["name"] for index in inspect(conn).get_indexes(table)}


def _create_legacy_log_records(conn) -> None:
    conn.execute(
        text(
            "CREATE TABLE log_records ("
            "id VARCHAR(36) PRIMARY KEY, "
            "filename VARCHAR(255) NOT NULL, "
            "log_type VARCHAR(32) NOT NULL, "
            "status VARCHAR(32) NOT NULL, "
            "is_deleted BOOLEAN NOT NULL DEFAULT 0, "
            "created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL"
            ")"
        )
    )
    conn.execute(text("CREATE INDEX idx_log_records_log_type ON log_records (log_type)"))
    conn.execute(
        text("CREATE INDEX idx_log_records_type_status ON log_records (log_type, status)")
    )
    conn.execute(text("CREATE INDEX idx_log_records_status ON log_records (status)"))
    conn.execute(
        text(
            "INSERT INTO log_records "
            "(id, filename, log_type, status, created_at, updated_at) "
            "VALUES ('r1', 'a.tar.gz', 'full', 'completed', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    )


def test_sync_drops_retired_column_and_its_legacy_indexes(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")

    with engine.begin() as conn:
        _create_legacy_log_records(conn)

        DatabaseManager._sync_columns_from_models(conn)

        columns = {column["name"] for column in inspect(conn).get_columns("log_records")}
        indexes = _index_names(conn, "log_records")
        rows = conn.execute(text("SELECT id, status FROM log_records")).all()

    assert "log_type" not in columns
    # Indexes covering the retired column cannot survive it; the ones that do
    # not reference it are left alone.
    assert "idx_log_records_log_type" not in indexes
    assert "idx_log_records_type_status" not in indexes
    assert "idx_log_records_status" in indexes
    # Dropping a column must not cost any rows.
    assert rows == [("r1", "completed")]


def test_sync_is_idempotent_on_an_already_migrated_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")

    with engine.begin() as conn:
        _create_legacy_log_records(conn)
        DatabaseManager._sync_columns_from_models(conn)
        DatabaseManager._sync_columns_from_models(conn)

        columns = {column["name"] for column in inspect(conn).get_columns("log_records")}
        indexes = _index_names(conn, "log_records")

    assert "log_type" not in columns
    assert "idx_log_records_status" in indexes


def test_retired_column_under_a_unique_index_is_left_in_place(tmp_path, caplog):
    """An un-droppable leftover column warns instead of aborting the upgrade."""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")

    with engine.begin() as conn:
        _create_legacy_log_records(conn)
        conn.execute(
            text("CREATE UNIQUE INDEX uq_log_records_log_type ON log_records (log_type)")
        )

        with caplog.at_level("WARNING"):
            DatabaseManager._sync_columns_from_models(conn)

        columns = {column["name"] for column in inspect(conn).get_columns("log_records")}
        indexes = _index_names(conn, "log_records")

    assert "log_type" in columns
    assert "uq_log_records_log_type" in indexes
    # The non-unique index is untouched too: nothing is removed when the drop
    # is abandoned.
    assert "idx_log_records_log_type" in indexes
    assert "uq_log_records_log_type" in caplog.text
