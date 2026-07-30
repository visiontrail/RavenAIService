from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import AppConfig
from .crypto import SecretBox


UTC = timezone.utc

DEFAULT_AGENT_PROMPT = """你是公司内部的生产级运维分析 Agent。请阅读下面这组模拟告警，完成一次中等强度的推理：

- 10:02，API 网关 P95 延迟由 2.1s 升至 8.6s
- 10:04，模型节点 GPU 利用率 94%，队列深度 37
- 10:06，5 分钟窗口内出现 3 次 429，未出现 5xx
- 10:09，队列深度回落至 12，GPU 利用率仍为 89%

请用中文输出：①最可能根因；②两个验证动作；③是否需要扩容。总计不超过 180 字。"""


class Database:
    def __init__(self, path: Path, secret_box: SecretBox, bootstrap: AppConfig) -> None:
        self.path = path
        self.secret_box = secret_box
        self.bootstrap = bootstrap
        self._write_lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS monitor_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    target_name TEXT NOT NULL,
                    protocol TEXT NOT NULL CHECK (protocol IN ('anthropic', 'openai')),
                    base_url TEXT NOT NULL,
                    model TEXT NOT NULL,
                    api_key_ciphertext TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    interval_seconds INTEGER NOT NULL,
                    timeout_seconds INTEGER NOT NULL,
                    max_tokens INTEGER NOT NULL,
                    alert_latency_ms INTEGER NOT NULL DEFAULT 30000,
                    retention_days INTEGER NOT NULL DEFAULT 365,
                    timezone TEXT NOT NULL,
                    agent_prompt TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS probe_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL DEFAULT 'scheduled',
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    usable INTEGER NOT NULL,
                    status_category TEXT NOT NULL,
                    http_status INTEGER,
                    latency_ms INTEGER NOT NULL,
                    first_byte_ms INTEGER,
                    ttft_ms INTEGER,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    error_kind TEXT,
                    error_message TEXT,
                    response_excerpt TEXT,
                    model TEXT NOT NULL,
                    endpoint TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_probe_runs_started
                    ON probe_runs(started_at);
                CREATE INDEX IF NOT EXISTS idx_probe_runs_success_started
                    ON probe_runs(success, started_at);
                """
            )
            now = datetime.now(UTC).isoformat()
            connection.execute(
                """
                INSERT OR IGNORE INTO monitor_settings (
                    id, target_name, protocol, base_url, model, enabled,
                    interval_seconds, timeout_seconds, max_tokens,
                    alert_latency_ms, retention_days, timezone, agent_prompt,
                    created_at, updated_at
                ) VALUES (1, ?, ?, ?, ?, 1, ?, ?, ?, 30000, 365, ?, ?, ?, ?)
                """,
                (
                    self.bootstrap.target_name,
                    self.bootstrap.target_protocol
                    if self.bootstrap.target_protocol in {"anthropic", "openai"}
                    else "anthropic",
                    self.bootstrap.target_base_url.rstrip("/"),
                    self.bootstrap.target_model,
                    max(30, self.bootstrap.target_interval_seconds),
                    max(5, self.bootstrap.target_timeout_seconds),
                    max(16, self.bootstrap.target_max_tokens),
                    self.bootstrap.model_sentinel_timezone,
                    DEFAULT_AGENT_PROMPT,
                    now,
                    now,
                ),
            )
            # v1.0 initially treated a completed stream with no final text as
            # healthy. For an Agent workload, HTTP 200 without an answer is an
            # unusable result (typically the thinking model exhausted its
            # output budget). Correct any such early rows in place.
            connection.execute(
                """
                UPDATE probe_runs
                SET success = 0,
                    usable = 0,
                    status_category = 'empty_response',
                    error_kind = 'empty_response',
                    error_message = '模型请求已完成，但没有生成最终文本答案'
                WHERE success = 1
                  AND COALESCE(response_excerpt, '') = ''
                  AND ttft_ms IS NULL
                """
            )

    def get_settings(self, include_secret: bool = False) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM monitor_settings WHERE id = 1"
            ).fetchone()
        if row is None:
            raise RuntimeError("monitor settings are not initialized")
        result = dict(row)
        ciphertext = result.pop("api_key_ciphertext", "")
        result["enabled"] = bool(result["enabled"])
        result["api_key_set"] = bool(ciphertext and self.secret_box.decrypt(ciphertext))
        if include_secret:
            result["api_key"] = self.secret_box.decrypt(ciphertext)
        return result

    def update_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "target_name",
            "protocol",
            "base_url",
            "model",
            "enabled",
            "interval_seconds",
            "timeout_seconds",
            "max_tokens",
            "alert_latency_ms",
            "retention_days",
            "timezone",
            "agent_prompt",
        }
        values = {key: value for key, value in updates.items() if key in allowed}
        if "base_url" in values:
            values["base_url"] = str(values["base_url"]).rstrip("/")
        if "enabled" in values:
            values["enabled"] = 1 if values["enabled"] else 0

        api_key = updates.get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            values["api_key_ciphertext"] = self.secret_box.encrypt(api_key.strip())
        values["updated_at"] = datetime.now(UTC).isoformat()

        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._write_lock, self._connect() as connection:
            connection.execute(
                f"UPDATE monitor_settings SET {assignments} WHERE id = 1",
                tuple(values.values()),
            )
        return self.get_settings()

    def insert_probe(self, probe: dict[str, Any]) -> int:
        columns = (
            "source",
            "started_at",
            "finished_at",
            "success",
            "usable",
            "status_category",
            "http_status",
            "latency_ms",
            "first_byte_ms",
            "ttft_ms",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "error_kind",
            "error_message",
            "response_excerpt",
            "model",
            "endpoint",
        )
        values = [probe.get(column) for column in columns]
        values[3] = 1 if values[3] else 0
        values[4] = 1 if values[4] else 0
        placeholders = ", ".join("?" for _ in columns)
        with self._write_lock, self._connect() as connection:
            cursor = connection.execute(
                f"INSERT INTO probe_runs ({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
            return int(cursor.lastrowid)

    def latest_probe(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM probe_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        return self._probe_dict(row) if row else None

    def list_probes(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if start:
            clauses.append("started_at >= ?")
            params.append(start.astimezone(UTC).isoformat())
        if end:
            clauses.append("started_at < ?")
            params.append(end.astimezone(UTC).isoformat())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit_sql = ""
        if limit:
            limit_sql = " LIMIT ?"
            params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM probe_runs {where} ORDER BY started_at DESC{limit_sql}",
                params,
            ).fetchall()
        return [self._probe_dict(row) for row in rows]

    def query_probes(
        self,
        start: datetime | None = None,
        status: str = "all",
        source: str = "all",
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """Filtered, paginated probe history plus the total row count."""
        clauses: list[str] = []
        params: list[Any] = []
        if start:
            clauses.append("started_at >= ?")
            params.append(start.astimezone(UTC).isoformat())
        if status == "usable":
            clauses.append("success = 1 AND usable = 1")
        elif status == "slow":
            clauses.append("success = 1 AND usable = 0")
        elif status == "failed":
            clauses.append("success = 0")
        if source != "all":
            clauses.append("source = ?")
            params.append(source)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM probe_runs {where}", params
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"SELECT * FROM probe_runs {where}"
                " ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return [self._probe_dict(row) for row in rows], total

    def purge_probes(self) -> int:
        """Delete every probe run. Settings and credentials are untouched."""
        with self._write_lock, self._connect() as connection:
            deleted = max(0, connection.execute("DELETE FROM probe_runs").rowcount)
            has_sequence = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'"
            ).fetchone()
            if has_sequence:
                connection.execute(
                    "DELETE FROM sqlite_sequence WHERE name = 'probe_runs'"
                )
        return deleted

    def cleanup(self, retention_days: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=max(1, retention_days))
        with self._write_lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM probe_runs WHERE started_at < ?", (cutoff.isoformat(),)
            )
            return max(0, cursor.rowcount)

    @staticmethod
    def _probe_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["success"] = bool(result["success"])
        result["usable"] = bool(result["usable"])
        return result
