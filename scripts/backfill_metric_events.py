#!/usr/bin/env python3
"""Best-effort historical backfill for ``metric_events``.

This is an EXPLICIT, manually-invoked maintenance script. It is never run on
service startup and never auto-runs (see design Decision / Migration Plan in
``openspec/changes/add-system-user-metrics/design.md``).

It derives one ``metric_events`` row per historical AI analysis from the token
usage already persisted in ``log_records.metadata_json.extra_fields
.ai_analysis_result`` and inserts it with the SAME idempotency key the live
Celery path uses (``ai_usage:log_task:<log_id>``). Because inserts are
idempotent on ``idempotency_key``, re-running is safe and rows recorded by the
live path are never duplicated.

Backfilled rows carry ``metadata.historical = true`` so they are
distinguishable from live-recorded events.

Prometheus counters are intentionally NOT bumped here: those counters are
cumulative system totals with no timestamp, and historical backfill should not
retroactively inflate live monitoring dashboards.

Usage:
    # Dry run (default): report what would be inserted, write nothing.
    python scripts/backfill_metric_events.py

    # Apply: actually insert the derived metric events.
    python scripts/backfill_metric_events.py --apply

    # Limit how many log records are scanned (useful for a first pass).
    python scripts/backfill_metric_events.py --apply --limit 500

Rollback: deleting backfilled rows is safe and does not affect any business
table. They can be removed with
``DELETE FROM metric_events WHERE event_type='ai_usage'
  AND metadata_json LIKE '%"historical": true%';`` (review before running).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.services import metrics_service  # noqa: E402


def _parse_metadata(metadata_json: Optional[str]) -> Dict[str, Any]:
    if not metadata_json:
        return {}
    try:
        data = json.loads(metadata_json)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _derive_values(log_id: str, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map a stored ``ai_analysis_result`` onto metric-event insert values.

    Returns ``None`` when the result has no usable token usage so we don't
    create empty historical rows.
    """
    usage = result.get("token_usage")
    if not isinstance(usage, dict):
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else None
    tokens = metrics_service.normalize_tokens(usage)
    if metrics_service.compute_total_tokens(tokens) <= 0:
        return None

    prepared = metrics_service._prepare_agent_run_kwargs(  # noqa: SLF001
        source="log_analysis_agent",
        agent_kind="log_analysis",
        result=result,
        provider=settings.anthropic_provider,
        log_id=str(log_id),
        owner_scope="system:ai_analysis",
        idempotency_key=f"ai_usage:log_task:{log_id}",
        extra_metadata={"historical": True},
    )
    return metrics_service._build_ai_usage_values(  # noqa: SLF001
        agent_kind=prepared["agent_kind"],
        source=prepared["source"],
        provider=prepared["provider"],
        model=prepared["model"],
        status=prepared["status"],
        usage=prepared["usage"],
        user_id=prepared["user_id"],
        owner_scope=prepared["owner_scope"],
        session_id=prepared["session_id"],
        run_id=prepared["run_id"],
        task_id=prepared["task_id"],
        log_id=prepared["log_id"],
        project_repo_id=prepared["project_repo_id"],
        duration_ms=prepared["duration_ms"],
        error_kind=prepared["error_kind"],
        idempotency_key=prepared["idempotency_key"],
        occurred_at=None,
        metadata=prepared["metadata"],
    )


def backfill_log_analysis(apply: bool, limit: Optional[int]) -> Dict[str, int]:
    """Scan log records and backfill AI-usage metric events. Returns a tally."""
    from sqlalchemy import select

    from app.models.log import LogRecord

    factory = metrics_service._get_sync_session_factory()  # noqa: SLF001
    stats = {"scanned": 0, "candidates": 0, "inserted": 0, "skipped_existing": 0}

    with factory() as session:
        stmt = select(LogRecord.id, LogRecord.metadata_json).where(
            LogRecord.metadata_json.is_not(None)
        )
        if limit:
            stmt = stmt.limit(limit)
        rows = session.execute(stmt).all()

    for log_id, metadata_json in rows:
        stats["scanned"] += 1
        meta = _parse_metadata(metadata_json)
        extra = meta.get("extra_fields") if isinstance(meta, dict) else None
        result = extra.get("ai_analysis_result") if isinstance(extra, dict) else None
        if not isinstance(result, dict):
            continue
        values = _derive_values(str(log_id), result)
        if values is None:
            continue
        stats["candidates"] += 1

        if not apply:
            continue

        inserted = metrics_service._sync_insert(values)  # noqa: SLF001
        if inserted:
            stats["inserted"] += 1
        else:
            stats["skipped_existing"] += 1

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually insert metric events. Without this flag the script is a dry run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of log records to scan (default: all).",
    )
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"[backfill_metric_events] mode={mode} limit={args.limit or 'all'}")

    stats = backfill_log_analysis(apply=args.apply, limit=args.limit)

    print(
        "[backfill_metric_events] scanned={scanned} candidates={candidates} "
        "inserted={inserted} skipped_existing={skipped_existing}".format(**stats)
    )
    if not args.apply:
        print("[backfill_metric_events] dry run only — re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
