"""Unified metrics recording and aggregation service.

This is the single chokepoint for persisting :class:`MetricEvent` rows and for
keeping Prometheus collectors in sync. Business code calls the small ``record_*``
helpers; everything about token normalization, total-token math, cost estimation,
metadata sanitization, idempotency and best-effort failure handling lives here.

Design guarantees (see ``openspec/changes/add-system-user-metrics/design.md``):

- Token fields are normalized (missing → 0) and ``total_tokens`` is derived.
- ``cost_microusd`` is computed only from configured pricing; otherwise ``None``.
- ``metadata_json`` only ever holds allowlisted, low-sensitivity keys.
- Inserts are idempotent on ``idempotency_key``; a duplicate is a no-op and does
  NOT double-count Prometheus.
- Recording NEVER raises into the caller; failures are logged and counted via the
  ``raven_metrics_record_failures_total`` Prometheus counter.

Both an async path (FastAPI / asyncio tasks) and a sync path (Celery / scripts)
are provided. Each opens its own short transaction so a metrics failure cannot
poison or roll back the caller's business transaction.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import and_, case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement

from app.config import settings
from app.models.metrics import MetricEvent
from app.utils import metrics as prom

logger = logging.getLogger(__name__)


# ==================== Constants ====================

# Only these keys may ever be persisted into ``metadata_json``. Anything else is
# dropped silently. This is the privacy allowlist (design Decision 7).
METADATA_ALLOWLIST = frozenset(
    {
        "tool_call_count",
        "trace_event_count",
        "log_type",
        "package_type",
        "result_count",
        "project_code",
        "error_kind",
        "historical",
    }
)

_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
)

# Map of common SDK usage aliases → canonical token field names.
_TOKEN_ALIASES = {
    "input_tokens": "input_tokens",
    "prompt_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "completion_tokens": "output_tokens",
    "cache_read_tokens": "cache_read_tokens",
    "cache_read_input_tokens": "cache_read_tokens",
    "cache_write_tokens": "cache_write_tokens",
    "cache_creation_input_tokens": "cache_write_tokens",
}

_PRICE_TOKEN_KEYS = {
    "input_tokens": "input_per_million",
    "output_tokens": "output_per_million",
    "cache_read_tokens": "cache_read_per_million",
    "cache_write_tokens": "cache_write_per_million",
}


# ==================== Pure helpers ====================


def normalize_tokens(usage: Any) -> Dict[str, int]:
    """Normalize an arbitrary SDK ``usage`` payload to canonical token counters.

    ``usage`` may be a dict or an SDK object with token attributes. Unknown keys
    are ignored, missing/invalid values become ``0``, and common aliases
    (``prompt_tokens``, ``cache_creation_input_tokens`` …) are mapped to the
    canonical field names. Negative values are clamped to ``0``.
    """
    result = {field: 0 for field in _TOKEN_FIELDS}
    if not usage:
        return result
    usage_dict = None
    if isinstance(usage, dict):
        usage_dict = {
            key.strip().lower(): value
            for key, value in usage.items()
            if isinstance(key, str)
        }
    seen: set[str] = set()
    for raw_key, canonical in _TOKEN_ALIASES.items():
        if canonical in seen:
            continue
        if usage_dict is not None:
            if raw_key not in usage_dict:
                continue
            value = usage_dict.get(raw_key)
        else:
            if not hasattr(usage, raw_key):
                continue
            value = getattr(usage, raw_key, None)
        try:
            count = int(value)
        except (TypeError, ValueError):
            seen.add(canonical)
            continue
        if count > 0:
            result[canonical] = count
        seen.add(canonical)
    return result


def _is_usage_payload(value: Any) -> bool:
    if isinstance(value, dict):
        return True
    return bool(value) and any(hasattr(value, key) for key in _TOKEN_ALIASES)


def compute_total_tokens(tokens: Dict[str, int]) -> int:
    """Sum the four canonical token counters."""
    return sum(int(tokens.get(field, 0) or 0) for field in _TOKEN_FIELDS)


def estimate_cost_microusd(
    provider: Optional[str],
    model: Optional[str],
    tokens: Dict[str, int],
) -> Optional[int]:
    """Estimate cost in micro-USD (1e-6 USD) from configured pricing.

    Returns ``None`` when no pricing is configured for the provider/model, so
    the API can surface ``cost_estimated=false``. Never raises.
    """
    if not provider or not model:
        return None
    try:
        pricing = settings.get_ai_metrics_pricing()
        model_prices = (pricing.get(provider) or {}).get(model)
        if not isinstance(model_prices, dict):
            return None

        total_usd = 0.0
        matched = False
        for token_field, price_key in _PRICE_TOKEN_KEYS.items():
            per_million = model_prices.get(price_key)
            count = int(tokens.get(token_field, 0) or 0)
            if per_million is None or count <= 0:
                continue
            try:
                total_usd += (count / 1_000_000.0) * float(per_million)
                matched = True
            except (TypeError, ValueError):
                continue
        if not matched:
            return None
        return int(round(total_usd * 1_000_000))
    except Exception as exc:  # noqa: BLE001
        logger.debug("metrics: cost estimation failed: %s", exc)
        return None


def sanitize_metadata(metadata: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Drop everything not on the allowlist; coerce remaining values to scalars.

    Returns ``None`` when nothing survives. This is the last line of defense
    against persisting prompts, answers, tool I/O, headers, cookies, or URLs.
    """
    if not isinstance(metadata, dict):
        return None
    clean: Dict[str, Any] = {}
    for key, value in metadata.items():
        if key not in METADATA_ALLOWLIST:
            continue
        # Only keep low-sensitivity scalar types; never nested blobs.
        if isinstance(value, (str, int, float, bool)) or value is None:
            if isinstance(value, str) and len(value) > 128:
                value = value[:128]
            clean[key] = value
    return clean or None


def _serialize_metadata(metadata: Optional[Dict[str, Any]]) -> Optional[str]:
    clean = sanitize_metadata(metadata)
    if not clean:
        return None
    try:
        return json.dumps(clean, ensure_ascii=False, sort_keys=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("metrics: metadata serialization failed: %s", exc)
        return None


def _build_ai_usage_values(
    *,
    source: str,
    agent_kind: Optional[str],
    provider: Optional[str],
    model: Optional[str],
    status: Optional[str],
    usage: Any,
    user_id: Optional[str],
    owner_scope: Optional[str],
    session_id: Optional[str],
    run_id: Optional[str],
    task_id: Optional[str],
    log_id: Optional[str],
    project_repo_id: Optional[str],
    duration_ms: Optional[int],
    error_kind: Optional[str],
    idempotency_key: str,
    occurred_at: Optional[datetime],
    metadata: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    tokens = normalize_tokens(usage)
    total = compute_total_tokens(tokens)
    cost = estimate_cost_microusd(provider, model, tokens)
    return {
        "id": str(uuid.uuid4()),
        "idempotency_key": idempotency_key,
        "occurred_at": occurred_at or datetime.utcnow(),
        "event_type": "ai_usage",
        "source": source,
        "user_id": user_id,
        "owner_scope": owner_scope,
        "session_id": session_id,
        "run_id": run_id,
        "task_id": task_id,
        "log_id": log_id,
        "project_repo_id": project_repo_id,
        "agent_kind": agent_kind,
        "provider": provider,
        "model": model,
        "status": status,
        "error_kind": error_kind,
        "duration_ms": duration_ms,
        "input_tokens": tokens["input_tokens"],
        "output_tokens": tokens["output_tokens"],
        "cache_read_tokens": tokens["cache_read_tokens"],
        "cache_write_tokens": tokens["cache_write_tokens"],
        "total_tokens": total,
        "cost_microusd": cost,
        "metadata_json": _serialize_metadata(metadata),
    }


def _build_business_values(
    *,
    event_type: str,
    source: str,
    status: Optional[str],
    user_id: Optional[str],
    owner_scope: Optional[str],
    session_id: Optional[str],
    log_id: Optional[str],
    idempotency_key: str,
    occurred_at: Optional[datetime],
    metadata: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "idempotency_key": idempotency_key,
        "occurred_at": occurred_at or datetime.utcnow(),
        "event_type": event_type,
        "source": source,
        "user_id": user_id,
        "owner_scope": owner_scope,
        "session_id": session_id,
        "log_id": log_id,
        "status": status,
        "metadata_json": _serialize_metadata(metadata),
    }


# ==================== Async recording path ====================


async def _async_insert(values: Dict[str, Any]) -> bool:
    """Insert a metric event in its own transaction. Returns True if newly inserted.

    Idempotent on ``idempotency_key``: a duplicate (either a pre-existing row or a
    concurrent insert that trips the unique constraint) returns ``False`` without
    raising. The caller uses the return value to decide whether to bump Prometheus.
    """
    from app.models.database import db_manager

    if not db_manager.session_factory:
        raise RuntimeError("database not initialized")

    key = values["idempotency_key"]
    async with db_manager.session_factory() as session:
        existing = await session.execute(
            select(MetricEvent.id).where(MetricEvent.idempotency_key == key)
        )
        if existing.scalar_one_or_none() is not None:
            return False
        session.add(MetricEvent(**values))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return False
        return True


async def record_ai_usage(
    *,
    source: str,
    idempotency_key: str,
    agent_kind: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    status: Optional[str] = None,
    usage: Any = None,
    user_id: Optional[str] = None,
    owner_scope: Optional[str] = None,
    session_id: Optional[str] = None,
    run_id: Optional[str] = None,
    task_id: Optional[str] = None,
    log_id: Optional[str] = None,
    project_repo_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
    error_kind: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record one AI usage event (best-effort, idempotent). Never raises."""
    try:
        values = _build_ai_usage_values(
            source=source,
            agent_kind=agent_kind,
            provider=provider,
            model=model,
            status=status,
            usage=usage,
            user_id=user_id,
            owner_scope=owner_scope,
            session_id=session_id,
            run_id=run_id,
            task_id=task_id,
            log_id=log_id,
            project_repo_id=project_repo_id,
            duration_ms=duration_ms,
            error_kind=error_kind,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
            metadata=metadata,
        )
        inserted = await _async_insert(values)
        if inserted:
            _bump_ai_prometheus(values)
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics: record_ai_usage failed (source=%s): %s", source, exc)
        prom.record_metrics_failure(source)


async def record_business_event(
    *,
    event_type: str,
    source: str,
    idempotency_key: str,
    status: Optional[str] = None,
    user_id: Optional[str] = None,
    owner_scope: Optional[str] = None,
    session_id: Optional[str] = None,
    log_id: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record one non-AI business event (best-effort, idempotent). Never raises."""
    try:
        values = _build_business_values(
            event_type=event_type,
            source=source,
            status=status,
            user_id=user_id,
            owner_scope=owner_scope,
            session_id=session_id,
            log_id=log_id,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
            metadata=metadata,
        )
        await _async_insert(values)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "metrics: record_business_event failed (source=%s): %s", source, exc
        )
        prom.record_metrics_failure(source)


# ==================== Sync recording path (Celery / scripts) ====================

# Lazy sync engine, mirroring app/tasks/ai_analysis.py. Built on first use so
# importing this module stays cheap and does not require a configured database.
_sync_session_factory = None


def _get_sync_session_factory():
    global _sync_session_factory
    if _sync_session_factory is not None:
        return _sync_session_factory

    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

    from app.models.database import _apply_sqlite_pragmas

    database_url = settings.get_database_url()
    if "sqlite+aiosqlite" in database_url:
        sync_url = database_url.replace("sqlite+aiosqlite", "sqlite")
    elif "postgresql+asyncpg" in database_url:
        sync_url = database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    else:
        sync_url = database_url.replace("+asyncpg", "").replace("+aiosqlite", "")

    is_sqlite = sync_url.startswith("sqlite")
    engine_kwargs: Dict[str, Any] = {"pool_recycle": 3600, "echo": False}
    if not is_sqlite:
        engine_kwargs.update(pool_size=1, max_overflow=0, pool_timeout=30)

    engine = create_engine(sync_url, **engine_kwargs)
    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma_sync(dbapi_connection, _record):  # noqa: ANN001
            _apply_sqlite_pragmas(dbapi_connection)

    _sync_session_factory = sessionmaker(bind=engine)
    return _sync_session_factory


def _sync_insert(values: Dict[str, Any]) -> bool:
    factory = _get_sync_session_factory()
    key = values["idempotency_key"]
    with factory() as session:
        existing = session.execute(
            select(MetricEvent.id).where(MetricEvent.idempotency_key == key)
        ).scalar_one_or_none()
        if existing is not None:
            return False
        session.add(MetricEvent(**values))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return False
        return True


def record_ai_usage_sync(
    *,
    source: str,
    idempotency_key: str,
    agent_kind: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    status: Optional[str] = None,
    usage: Any = None,
    user_id: Optional[str] = None,
    owner_scope: Optional[str] = None,
    session_id: Optional[str] = None,
    run_id: Optional[str] = None,
    task_id: Optional[str] = None,
    log_id: Optional[str] = None,
    project_repo_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
    error_kind: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Synchronous variant of :func:`record_ai_usage` for Celery/script paths."""
    try:
        values = _build_ai_usage_values(
            source=source,
            agent_kind=agent_kind,
            provider=provider,
            model=model,
            status=status,
            usage=usage,
            user_id=user_id,
            owner_scope=owner_scope,
            session_id=session_id,
            run_id=run_id,
            task_id=task_id,
            log_id=log_id,
            project_repo_id=project_repo_id,
            duration_ms=duration_ms,
            error_kind=error_kind,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
            metadata=metadata,
        )
        inserted = _sync_insert(values)
        if inserted:
            _bump_ai_prometheus(values)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "metrics: record_ai_usage_sync failed (source=%s): %s", source, exc
        )
        prom.record_metrics_failure(source)


# ==================== Agent-run convenience recorders ====================
#
# Most AI sources expose the same terminal result shape (``token_usage``/``usage``,
# ``model``, optional ``provider``, ``duration_seconds``, ``status``/``error_kind``,
# ``trace_summary``/``trace_events``). These helpers map that shape onto
# ``record_ai_usage`` so each call site only supplies ownership + an idempotency
# anchor, keeping status/metadata normalization in one place.


def _agent_run_metadata(
    result: Dict[str, Any], extra: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Build allowlisted metadata (tool/trace counts + caller extras) from a result."""
    md: Dict[str, Any] = {}
    trace_summary = result.get("trace_summary")
    if isinstance(trace_summary, dict):
        tool_calls = trace_summary.get("tool_call_count")
        if isinstance(tool_calls, int):
            md["tool_call_count"] = tool_calls
    trace_events = result.get("trace_events")
    if isinstance(trace_events, list):
        md["trace_event_count"] = len(trace_events)
    if extra:
        md.update(extra)
    # sanitize_metadata() runs again at persist time; allowlist-filter early too.
    return md or None


def _agent_run_status(result: Dict[str, Any], terminal_status: Optional[str]) -> str:
    """Resolve a normalized metric status from the run lifecycle + agent result.

    The run-lifecycle ``terminal_status`` (succeeded/failed/cancelled/stale) is
    authoritative when present, but a clean "succeeded" is downgraded when the
    agent result still carries an ``error_kind`` (e.g. timeout/schema_mismatch).
    """
    error_kind = result.get("error_kind")
    error_kind = error_kind if isinstance(error_kind, str) and error_kind else None
    if terminal_status in _KNOWN_STATUSES:
        if terminal_status == "succeeded" and error_kind:
            return "timeout" if error_kind == "timeout" else "failed"
        return terminal_status
    agent_status = str(result.get("status") or "").lower()
    if agent_status in _KNOWN_STATUSES:
        return agent_status
    if error_kind == "timeout":
        return "timeout"
    if error_kind or agent_status in ("error", "schema_mismatch"):
        return "failed"
    return "succeeded"


def _prepare_agent_run_kwargs(
    *,
    source: str,
    agent_kind: str,
    result: Optional[Dict[str, Any]],
    run_id: Optional[str] = None,
    terminal_status: Optional[str] = None,
    provider: Optional[str] = None,
    user_id: Optional[str] = None,
    owner_scope: Optional[str] = None,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    log_id: Optional[str] = None,
    project_repo_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    data = result if isinstance(result, dict) else {}
    usage = data.get("token_usage")
    if not _is_usage_payload(usage):
        candidate = data.get("usage")
        usage = candidate if _is_usage_payload(candidate) else None
    model = data.get("model") if isinstance(data.get("model"), str) else None
    resolved_provider = provider or (
        data.get("provider") if isinstance(data.get("provider"), str) else None
    )
    duration_ms: Optional[int] = None
    duration_seconds = data.get("duration_seconds")
    if isinstance(duration_seconds, (int, float)):
        duration_ms = max(0, int(duration_seconds * 1000))
    status = _agent_run_status(data, terminal_status)
    error_kind = data.get("error_kind")
    error_kind = error_kind if isinstance(error_kind, str) and error_kind else None
    if error_kind is None and status in ("timeout", "cancelled", "stale"):
        error_kind = status
    key = idempotency_key or f"ai_usage:{agent_kind}_run:{run_id}"
    return {
        "source": source,
        "agent_kind": agent_kind,
        "provider": resolved_provider,
        "model": model,
        "status": status,
        "usage": usage,
        "user_id": user_id,
        "owner_scope": owner_scope,
        "session_id": session_id,
        "run_id": run_id,
        "task_id": task_id,
        "log_id": log_id,
        "project_repo_id": project_repo_id,
        "duration_ms": duration_ms,
        "error_kind": error_kind,
        "idempotency_key": key,
        "metadata": _agent_run_metadata(data, extra_metadata),
    }


async def record_agent_run_usage(**kwargs: Any) -> None:
    """Record AI usage from a terminal agent result (async). Never raises."""
    source = kwargs.get("source", "agent_run")
    try:
        prepared = _prepare_agent_run_kwargs(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics: prepare agent run failed (source=%s): %s", source, exc)
        prom.record_metrics_failure(source)
        return
    await record_ai_usage(**prepared)


def record_agent_run_usage_sync(**kwargs: Any) -> None:
    """Synchronous variant of :func:`record_agent_run_usage` (Celery/scripts)."""
    source = kwargs.get("source", "agent_run")
    try:
        prepared = _prepare_agent_run_kwargs(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics: prepare agent run failed (source=%s): %s", source, exc)
        prom.record_metrics_failure(source)
        return
    record_ai_usage_sync(**prepared)


# ==================== Aggregation queries (read path) ====================
#
# These power the admin/self metrics APIs. They aggregate the persisted
# ``metric_events`` fact source ONLY; business-table summaries (chat/log/package/
# device) are composed separately at the API layer (see section 4 of the change).
# All queries are dialect-aware (SQLite / PostgreSQL) for time bucketing and never
# load unbounded row sets except the bounded duration/percentile fetch.

_VALID_BUCKETS = ("hour", "day")

# Terminal statuses surfaced as dedicated counters; anything else folds into "other".
_KNOWN_STATUSES = ("succeeded", "failed", "cancelled", "stale", "timeout")

# Cap for the duration fetch used to compute avg/p95 in Python. API callers already
# bound the time range; this is a defensive ceiling against pathological windows.
_DURATION_FETCH_CAP = 200_000


def _is_sqlite() -> bool:
    try:
        return settings.get_database_url().startswith("sqlite")
    except Exception:  # noqa: BLE001
        return False


def _ai_filters(
    from_time: datetime,
    to_time: datetime,
    extra: Optional[Sequence[ColumnElement]] = None,
) -> List[ColumnElement]:
    """Base WHERE clauses for AI-usage aggregation within a time range."""
    clauses: List[ColumnElement] = [
        MetricEvent.event_type == "ai_usage",
        MetricEvent.occurred_at >= from_time,
        MetricEvent.occurred_at < to_time,
    ]
    if extra:
        clauses.extend(extra)
    return clauses


def _bucket_expr(bucket: str):
    """Dialect-aware SQL expression that truncates ``occurred_at`` to the bucket."""
    column = MetricEvent.occurred_at
    if _is_sqlite():
        fmt = "%Y-%m-%d %H:00:00" if bucket == "hour" else "%Y-%m-%d 00:00:00"
        return func.strftime(fmt, column)
    return func.date_trunc("hour" if bucket == "hour" else "day", column)


def _parse_bucket_key(key: Any) -> Optional[datetime]:
    """Coerce a grouped bucket key (str from SQLite / datetime from PG) to datetime."""
    if isinstance(key, datetime):
        return key
    if isinstance(key, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return datetime.strptime(key, fmt)
            except ValueError:
                continue
    return None


def normalize_bucket(bucket: Optional[str]) -> str:
    """Validate the requested bucket, defaulting to ``day``."""
    return bucket if bucket in _VALID_BUCKETS else "day"


_TOKEN_SUM_LABELS = (
    ("input_tokens", MetricEvent.input_tokens),
    ("output_tokens", MetricEvent.output_tokens),
    ("cache_read_tokens", MetricEvent.cache_read_tokens),
    ("cache_write_tokens", MetricEvent.cache_write_tokens),
    ("total_tokens", MetricEvent.total_tokens),
)


def _cost_usd_from_microusd(micro: Optional[int]) -> Optional[float]:
    if micro is None:
        return None
    return round(micro / 1_000_000.0, 6)


async def _sum_tokens(session, filters: Sequence[ColumnElement]) -> Dict[str, Any]:
    """Sum token columns plus an estimated-cost rollup over the filtered events."""
    cols = [func.coalesce(func.sum(col), 0).label(name) for name, col in _TOKEN_SUM_LABELS]
    cols.append(func.coalesce(func.sum(MetricEvent.cost_microusd), 0).label("cost_microusd"))
    cols.append(func.count(MetricEvent.cost_microusd).label("cost_rows"))
    row = (await session.execute(select(*cols).where(and_(*filters)))).one()
    mapping = row._mapping
    tokens = {name: int(mapping[name] or 0) for name, _ in _TOKEN_SUM_LABELS}
    cost_rows = int(mapping["cost_rows"] or 0)
    tokens["estimated_cost_usd"] = (
        _cost_usd_from_microusd(int(mapping["cost_microusd"] or 0)) if cost_rows else None
    )
    tokens["cost_estimated"] = cost_rows > 0
    return tokens


async def _invocation_count(session, filters: Sequence[ColumnElement]) -> int:
    return int(
        (await session.execute(select(func.count()).where(and_(*filters)))).scalar() or 0
    )


async def _status_counts(session, filters: Sequence[ColumnElement]) -> Dict[str, int]:
    rows = (
        await session.execute(
            select(MetricEvent.status, func.count())
            .where(and_(*filters))
            .group_by(MetricEvent.status)
        )
    ).all()
    counts = {name: 0 for name in _KNOWN_STATUSES}
    counts["other"] = 0
    for status_value, count in rows:
        bucket = status_value if status_value in _KNOWN_STATUSES else "other"
        counts[bucket] += int(count or 0)
    return counts


async def _error_count(session, filters: Sequence[ColumnElement]) -> int:
    return int(
        (
            await session.execute(
                select(func.count()).where(
                    and_(*filters, MetricEvent.error_kind.is_not(None))
                )
            )
        ).scalar()
        or 0
    )


async def _group_counts(
    session, filters: Sequence[ColumnElement], column: ColumnElement
) -> List[Dict[str, Any]]:
    """GROUP BY a single dimension returning invocation count + token sum per key."""
    rows = (
        await session.execute(
            select(
                column,
                func.count().label("invocation_count"),
                func.coalesce(func.sum(MetricEvent.total_tokens), 0).label("total_tokens"),
            )
            .where(and_(*filters))
            .group_by(column)
            .order_by(func.count().desc())
        )
    ).all()
    return [
        {
            "key": key,
            "invocation_count": int(invocation_count or 0),
            "total_tokens": int(total_tokens or 0),
        }
        for key, invocation_count, total_tokens in rows
    ]


async def _errors_by_kind(
    session, filters: Sequence[ColumnElement]
) -> List[Dict[str, Any]]:
    return await _group_counts(
        session,
        list(filters) + [MetricEvent.error_kind.is_not(None)],
        MetricEvent.error_kind,
    )


async def _duration_summary(
    session, filters: Sequence[ColumnElement]
) -> Dict[str, Optional[float]]:
    """Compute avg and p95 duration (ms) from a bounded fetch of non-null values."""
    values = (
        (
            await session.execute(
                select(MetricEvent.duration_ms)
                .where(and_(*filters, MetricEvent.duration_ms.is_not(None)))
                .order_by(MetricEvent.duration_ms.asc())
                .limit(_DURATION_FETCH_CAP)
            )
        )
        .scalars()
        .all()
    )
    if not values:
        return {"duration_ms_avg": None, "duration_ms_p95": None}
    count = len(values)
    avg = sum(values) / count
    # values are already sorted ascending; nearest-rank p95.
    p95_index = min(count - 1, int(round(0.95 * (count - 1))))
    return {
        "duration_ms_avg": round(float(avg), 2),
        "duration_ms_p95": float(values[p95_index]),
    }


async def _time_series(
    session, filters: Sequence[ColumnElement], bucket: str
) -> List[Dict[str, Any]]:
    """Per-bucket token sums and invocation/success/failure counts."""
    bucket_col = _bucket_expr(bucket)
    success = func.sum(case((MetricEvent.status == "succeeded", 1), else_=0))
    failure = func.sum(case((MetricEvent.status == "failed", 1), else_=0))
    rows = (
        await session.execute(
            select(
                bucket_col.label("bucket_key"),
                func.coalesce(func.sum(MetricEvent.input_tokens), 0),
                func.coalesce(func.sum(MetricEvent.output_tokens), 0),
                func.coalesce(func.sum(MetricEvent.cache_read_tokens), 0),
                func.coalesce(func.sum(MetricEvent.cache_write_tokens), 0),
                func.coalesce(func.sum(MetricEvent.total_tokens), 0),
                func.count(),
                success,
                failure,
            )
            .where(and_(*filters))
            .group_by(bucket_col)
            .order_by(bucket_col.asc())
        )
    ).all()
    series: List[Dict[str, Any]] = []
    for row in rows:
        bucket_start = _parse_bucket_key(row[0])
        if bucket_start is None:
            continue
        series.append(
            {
                "bucket_start": bucket_start,
                "input_tokens": int(row[1] or 0),
                "output_tokens": int(row[2] or 0),
                "cache_read_tokens": int(row[3] or 0),
                "cache_write_tokens": int(row[4] or 0),
                "total_tokens": int(row[5] or 0),
                "invocation_count": int(row[6] or 0),
                "success_count": int(row[7] or 0),
                "failure_count": int(row[8] or 0),
            }
        )
    return series


async def _last_active(
    session, filters: Sequence[ColumnElement]
) -> Optional[datetime]:
    return (
        await session.execute(select(func.max(MetricEvent.occurred_at)).where(and_(*filters)))
    ).scalar()


def _event_to_dict(event: MetricEvent) -> Dict[str, Any]:
    """Map a ``MetricEvent`` row to the RawMetricEvent shape (metadata parsed)."""
    metadata: Optional[Dict[str, Any]] = None
    if event.metadata_json:
        try:
            metadata = json.loads(event.metadata_json)
        except Exception:  # noqa: BLE001
            metadata = None
    return {
        "id": event.id,
        "idempotency_key": event.idempotency_key,
        "occurred_at": event.occurred_at,
        "event_type": event.event_type,
        "source": event.source,
        "user_id": event.user_id,
        "owner_scope": event.owner_scope,
        "session_id": event.session_id,
        "run_id": event.run_id,
        "task_id": event.task_id,
        "log_id": event.log_id,
        "project_repo_id": event.project_repo_id,
        "agent_kind": event.agent_kind,
        "provider": event.provider,
        "model": event.model,
        "status": event.status,
        "error_kind": event.error_kind,
        "duration_ms": event.duration_ms,
        "input_tokens": event.input_tokens,
        "output_tokens": event.output_tokens,
        "cache_read_tokens": event.cache_read_tokens,
        "cache_write_tokens": event.cache_write_tokens,
        "total_tokens": event.total_tokens,
        "cost_microusd": event.cost_microusd,
        "metadata": metadata,
    }


def _read_session():
    from app.models.database import db_manager

    if not db_manager.session_factory:
        raise RuntimeError("database not initialized")
    return db_manager.session_factory()


async def aggregate_system_metrics(
    *, from_time: datetime, to_time: datetime, bucket: str = "day"
) -> Dict[str, Any]:
    """Aggregate the AI-usage subset of the system overview.

    Returns a dict whose keys line up with the AI-related fields of
    :class:`app.models.metrics.SystemOverview`; business-table summaries
    (chat/logs/packages/devices) are merged in by the API layer.
    """
    bucket = normalize_bucket(bucket)
    filters = _ai_filters(from_time, to_time)
    async with _read_session() as session:
        tokens = await _sum_tokens(session, filters)
        result: Dict[str, Any] = {
            "tokens": {
                k: tokens[k]
                for k in (
                    "input_tokens",
                    "output_tokens",
                    "cache_read_tokens",
                    "cache_write_tokens",
                    "total_tokens",
                )
            },
            "estimated_cost_usd": tokens["estimated_cost_usd"],
            "cost_estimated": tokens["cost_estimated"],
            "invocation_count": await _invocation_count(session, filters),
            "status_counts": await _status_counts(session, filters),
            "error_count": await _error_count(session, filters),
            "invocations_by_source": await _group_counts(
                session, filters, MetricEvent.source
            ),
            "invocations_by_agent_kind": await _group_counts(
                session, filters, MetricEvent.agent_kind
            ),
            "invocations_by_provider": await _group_counts(
                session, filters, MetricEvent.provider
            ),
            "invocations_by_model": await _group_counts(
                session, filters, MetricEvent.model
            ),
            "invocations_by_status": await _group_counts(
                session, filters, MetricEvent.status
            ),
            "time_series": await _time_series(session, filters, bucket),
        }
        result.update(await _duration_summary(session, filters))
    return result


_USER_SORT_COLUMNS = {
    "total_tokens": "total_tokens",
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "run_count": "run_count",
    "success_count": "success_count",
    "failure_count": "failure_count",
    "last_active_at": "last_active_at",
}


def normalize_user_sort(sort: Optional[str]) -> str:
    return sort if sort in _USER_SORT_COLUMNS else "total_tokens"


async def aggregate_user_metrics_list(
    *,
    from_time: datetime,
    to_time: datetime,
    page: int = 1,
    per_page: int = 20,
    sort: str = "total_tokens",
) -> Dict[str, Any]:
    """Per-user AI-usage rollup with sorting + pagination over ``metric_events``.

    Only the metric_events-derived fields are populated (tokens, run/status counts,
    last_active_at, top_agent_kind). ``username``/``role``/``message_count`` are
    enriched from the users / chat tables by the API layer.
    """
    sort = normalize_user_sort(sort)
    page = max(1, page)
    per_page = max(1, per_page)
    filters = _ai_filters(from_time, to_time, [MetricEvent.user_id.is_not(None)])

    success = func.sum(case((MetricEvent.status == "succeeded", 1), else_=0))
    failure = func.sum(case((MetricEvent.status == "failed", 1), else_=0))
    aggregates = {
        "input_tokens": func.coalesce(func.sum(MetricEvent.input_tokens), 0),
        "output_tokens": func.coalesce(func.sum(MetricEvent.output_tokens), 0),
        "cache_read_tokens": func.coalesce(func.sum(MetricEvent.cache_read_tokens), 0),
        "cache_write_tokens": func.coalesce(func.sum(MetricEvent.cache_write_tokens), 0),
        "total_tokens": func.coalesce(func.sum(MetricEvent.total_tokens), 0),
        "cost_microusd": func.sum(MetricEvent.cost_microusd),
        "run_count": func.count(),
        "success_count": success,
        "failure_count": failure,
        "last_active_at": func.max(MetricEvent.occurred_at),
    }
    order_col = aggregates[sort]
    order_by = (
        order_col.asc() if sort == "last_active_at" else order_col.desc()
    )

    async with _read_session() as session:
        total = int(
            (
                await session.execute(
                    select(func.count(func.distinct(MetricEvent.user_id))).where(
                        and_(*filters)
                    )
                )
            ).scalar()
            or 0
        )

        rows = (
            await session.execute(
                select(MetricEvent.user_id, *aggregates.values())
                .where(and_(*filters))
                .group_by(MetricEvent.user_id)
                .order_by(order_by)
                .limit(per_page)
                .offset((page - 1) * per_page)
            )
        ).all()

        user_ids = [r[0] for r in rows]
        top_agent = await _top_agent_kind_by_user(session, filters, user_ids)

    keys = list(aggregates.keys())
    result_rows: List[Dict[str, Any]] = []
    for row in rows:
        user_id = row[0]
        values = dict(zip(keys, row[1:]))
        result_rows.append(
            {
                "user_id": user_id,
                "input_tokens": int(values["input_tokens"] or 0),
                "output_tokens": int(values["output_tokens"] or 0),
                "cache_read_tokens": int(values["cache_read_tokens"] or 0),
                "cache_write_tokens": int(values["cache_write_tokens"] or 0),
                "total_tokens": int(values["total_tokens"] or 0),
                "estimated_cost_usd": _cost_usd_from_microusd(
                    int(values["cost_microusd"]) if values["cost_microusd"] is not None else None
                ),
                "run_count": int(values["run_count"] or 0),
                "success_count": int(values["success_count"] or 0),
                "failure_count": int(values["failure_count"] or 0),
                "last_active_at": values["last_active_at"],
                "top_agent_kind": top_agent.get(user_id),
            }
        )
    return {"total": total, "page": page, "per_page": per_page, "sort": sort, "rows": result_rows}


async def _top_agent_kind_by_user(
    session, filters: Sequence[ColumnElement], user_ids: Sequence[str]
) -> Dict[str, str]:
    """Most-used agent_kind per user, restricted to the given page of users."""
    if not user_ids:
        return {}
    rows = (
        await session.execute(
            select(MetricEvent.user_id, MetricEvent.agent_kind, func.count().label("c"))
            .where(
                and_(
                    *filters,
                    MetricEvent.user_id.in_(list(user_ids)),
                    MetricEvent.agent_kind.is_not(None),
                )
            )
            .group_by(MetricEvent.user_id, MetricEvent.agent_kind)
            .order_by(func.count().desc())
        )
    ).all()
    top: Dict[str, str] = {}
    for user_id, agent_kind, _count in rows:
        if user_id not in top:  # rows are ordered by count desc
            top[user_id] = agent_kind
    return top


async def aggregate_user_detail(
    *,
    user_id: str,
    from_time: datetime,
    to_time: datetime,
    bucket: str = "day",
    recent_limit: int = 20,
) -> Dict[str, Any]:
    """Single-user detail: token series, distributions, status/error groups, events."""
    bucket = normalize_bucket(bucket)
    filters = _ai_filters(from_time, to_time, [MetricEvent.user_id == user_id])
    async with _read_session() as session:
        tokens = await _sum_tokens(session, filters)
        detail: Dict[str, Any] = {
            "tokens": {
                k: tokens[k]
                for k in (
                    "input_tokens",
                    "output_tokens",
                    "cache_read_tokens",
                    "cache_write_tokens",
                    "total_tokens",
                )
            },
            "estimated_cost_usd": tokens["estimated_cost_usd"],
            "cost_estimated": tokens["cost_estimated"],
            "invocation_count": await _invocation_count(session, filters),
            "status_counts": await _status_counts(session, filters),
            "last_active_at": await _last_active(session, filters),
            "invocations_by_source": await _group_counts(
                session, filters, MetricEvent.source
            ),
            "invocations_by_agent_kind": await _group_counts(
                session, filters, MetricEvent.agent_kind
            ),
            "invocations_by_provider": await _group_counts(
                session, filters, MetricEvent.provider
            ),
            "invocations_by_model": await _group_counts(
                session, filters, MetricEvent.model
            ),
            "errors_by_kind": await _errors_by_kind(session, filters),
            "time_series": await _time_series(session, filters, bucket),
            "recent_events": await _recent_events(session, filters, recent_limit),
        }
    return detail


async def aggregate_self_metrics(
    *, user_id: str, from_time: datetime, to_time: datetime, bucket: str = "day"
) -> Dict[str, Any]:
    """Self-service subset of the per-user detail (no raw events, no owner scope)."""
    bucket = normalize_bucket(bucket)
    filters = _ai_filters(from_time, to_time, [MetricEvent.user_id == user_id])
    async with _read_session() as session:
        tokens = await _sum_tokens(session, filters)
        return {
            "tokens": {
                k: tokens[k]
                for k in (
                    "input_tokens",
                    "output_tokens",
                    "cache_read_tokens",
                    "cache_write_tokens",
                    "total_tokens",
                )
            },
            "estimated_cost_usd": tokens["estimated_cost_usd"],
            "cost_estimated": tokens["cost_estimated"],
            "invocation_count": await _invocation_count(session, filters),
            "status_counts": await _status_counts(session, filters),
            "last_active_at": await _last_active(session, filters),
            "invocations_by_agent_kind": await _group_counts(
                session, filters, MetricEvent.agent_kind
            ),
            "time_series": await _time_series(session, filters, bucket),
        }


async def _recent_events(
    session, filters: Sequence[ColumnElement], limit: int
) -> List[Dict[str, Any]]:
    events = (
        (
            await session.execute(
                select(MetricEvent)
                .where(and_(*filters))
                .order_by(MetricEvent.occurred_at.desc())
                .limit(max(1, limit))
            )
        )
        .scalars()
        .all()
    )
    return [_event_to_dict(e) for e in events]


async def list_metric_events(
    *,
    from_time: datetime,
    to_time: datetime,
    event_type: Optional[str] = None,
    source: Optional[str] = None,
    user_id: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
) -> Dict[str, Any]:
    """Paginated raw (sanitized) event listing for admin audit.

    Log-upload activity events are intentionally excluded: a log upload is not an
    AI/agent invocation, so it is neither counted toward invocation totals nor
    surfaced in this raw-event audit feed.
    """
    page = max(1, page)
    per_page = max(1, per_page)
    filters: List[ColumnElement] = [
        MetricEvent.occurred_at >= from_time,
        MetricEvent.occurred_at < to_time,
        MetricEvent.source != "log_upload",
    ]
    if event_type:
        filters.append(MetricEvent.event_type == event_type)
    if source:
        filters.append(MetricEvent.source == source)
    if user_id:
        filters.append(MetricEvent.user_id == user_id)

    async with _read_session() as session:
        total = int(
            (await session.execute(select(func.count()).where(and_(*filters)))).scalar()
            or 0
        )
        events = (
            (
                await session.execute(
                    select(MetricEvent)
                    .where(and_(*filters))
                    .order_by(MetricEvent.occurred_at.desc())
                    .limit(per_page)
                    .offset((page - 1) * per_page)
                )
            )
            .scalars()
            .all()
        )
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "events": [_event_to_dict(e) for e in events],
    }


# ==================== Business-table aggregation (read path) ====================
#
# The system overview composes the AI-usage fact source with summaries derived
# directly from existing domain tables / in-memory services (design Decision 5).
# These functions are best-effort: any failure returns an empty summary so the
# overview endpoint still renders the AI-usage portion. None of them ever raise.


def _enum_key(value: Any) -> str:
    """Coerce a grouped DB value (enum / str / None) to a stable string key."""
    if value is None:
        return "unknown"
    inner = getattr(value, "value", value)
    text = str(inner).strip()
    return text or "unknown"


async def _count_group(
    session, column: ColumnElement, filters: Sequence[ColumnElement]
) -> Dict[str, int]:
    rows = (
        await session.execute(
            select(column, func.count()).where(and_(*filters)).group_by(column)
        )
    ).all()
    return {_enum_key(key): int(count or 0) for key, count in rows}


async def aggregate_chat_metrics(
    *, from_time: datetime, to_time: datetime
) -> Dict[str, Any]:
    """Chat/user activity summary from users / chat_sessions / chat_messages / runs.

    ``total_users`` is an all-time system stat; everything else is scoped to the
    requested window (active users, sessions/messages created, run terminal mix).
    """
    from app.models.user import ChatAgentRun, ChatMessage, ChatSession, User

    summary: Dict[str, Any] = {
        "total_users": 0,
        "active_users": 0,
        "chat_session_count": 0,
        "chat_message_count": 0,
        "run_counts_by_status": {},
    }
    try:
        async with _read_session() as session:
            summary["total_users"] = int(
                (await session.execute(select(func.count(User.id)))).scalar() or 0
            )
            run_window = [
                ChatAgentRun.started_at >= from_time,
                ChatAgentRun.started_at < to_time,
            ]
            summary["active_users"] = int(
                (
                    await session.execute(
                        select(func.count(func.distinct(ChatAgentRun.user_id))).where(
                            and_(*run_window, ChatAgentRun.user_id.is_not(None))
                        )
                    )
                ).scalar()
                or 0
            )
            summary["chat_session_count"] = int(
                (
                    await session.execute(
                        select(func.count(ChatSession.id)).where(
                            and_(
                                ChatSession.created_at >= from_time,
                                ChatSession.created_at < to_time,
                                ChatSession.is_deleted.is_(False),
                            )
                        )
                    )
                ).scalar()
                or 0
            )
            summary["chat_message_count"] = int(
                (
                    await session.execute(
                        select(func.count(ChatMessage.id)).where(
                            and_(
                                ChatMessage.created_at >= from_time,
                                ChatMessage.created_at < to_time,
                            )
                        )
                    )
                ).scalar()
                or 0
            )
            summary["run_counts_by_status"] = await _count_group(
                session, ChatAgentRun.status, run_window
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics: aggregate_chat_metrics failed: %s", exc)
    return summary


async def aggregate_log_metrics(
    *, from_time: datetime, to_time: datetime
) -> Dict[str, Any]:
    """Log upload + AI-analysis summary from log_records and metric_events."""
    from app.models.log import LogRecord

    summary: Dict[str, Any] = {
        "upload_count": 0,
        "uploaded_bytes": 0,
        "counts_by_log_type": {},
        "counts_by_status": {},
        "ai_analysis_counts": {},
    }
    try:
        async with _read_session() as session:
            log_window = [
                LogRecord.created_at >= from_time,
                LogRecord.created_at < to_time,
                LogRecord.is_deleted.is_(False),
            ]
            row = (
                await session.execute(
                    select(
                        func.count(LogRecord.id),
                        func.coalesce(func.sum(LogRecord.file_size), 0),
                    ).where(and_(*log_window))
                )
            ).one()
            summary["upload_count"] = int(row[0] or 0)
            summary["uploaded_bytes"] = int(row[1] or 0)
            summary["counts_by_log_type"] = await _count_group(
                session, LogRecord.log_type, log_window
            )
            summary["counts_by_status"] = await _count_group(
                session, LogRecord.status, log_window
            )
            # AI-analysis terminal counts derive from the persisted fact source so
            # both the Celery and chat-service log-analysis paths are covered.
            ai_filters = _ai_filters(
                from_time,
                to_time,
                [MetricEvent.agent_kind == "log_analysis"],
            )
            summary["ai_analysis_counts"] = await _count_group(
                session, MetricEvent.status, ai_filters
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics: aggregate_log_metrics failed: %s", exc)
    return summary


async def aggregate_package_metrics(
    *, from_time: datetime, to_time: datetime
) -> Dict[str, Any]:
    """Package inventory (from the package service) + windowed activity/search counts."""
    summary: Dict[str, Any] = {
        "package_count": 0,
        "total_bytes": 0,
        "counts_by_type": {},
        "activity_counts": {},
        "search_count": 0,
    }
    try:
        from app.services.raven_package_service import raven_package_service

        packages = raven_package_service.get_all_packages()
        counts_by_type: Dict[str, int] = {}
        total_bytes = 0
        for pkg in packages:
            ptype = _enum_key(pkg.get("packageType"))
            counts_by_type[ptype] = counts_by_type.get(ptype, 0) + 1
            try:
                total_bytes += int(pkg.get("size") or 0)
            except (TypeError, ValueError):
                continue
        summary["package_count"] = len(packages)
        summary["total_bytes"] = total_bytes
        summary["counts_by_type"] = counts_by_type
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics: package inventory aggregation failed: %s", exc)

    try:
        async with _read_session() as session:
            summary["activity_counts"] = await _count_group(
                session,
                MetricEvent.source,
                [
                    MetricEvent.event_type == "package_activity",
                    MetricEvent.occurred_at >= from_time,
                    MetricEvent.occurred_at < to_time,
                ],
            )
            summary["search_count"] = int(
                (
                    await session.execute(
                        select(func.count()).where(
                            and_(
                                *_ai_filters(
                                    from_time,
                                    to_time,
                                    [MetricEvent.agent_kind == "package"],
                                )
                            )
                        )
                    )
                ).scalar()
                or 0
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics: package activity aggregation failed: %s", exc)
    return summary


def aggregate_device_metrics() -> Dict[str, Any]:
    """Current device connection summary from the in-memory link manager.

    Also refreshes the Prometheus ``raven_device_connections`` gauge so the
    point-in-time state is exported for scraping. Best-effort; never raises.
    """
    counts_by_state: Dict[str, int] = {}
    try:
        from app.services.device_link_service import device_link_manager

        for device in device_link_manager.list_devices():
            state = _enum_key(getattr(device, "status", None))
            counts_by_state[state] = counts_by_state.get(state, 0) + 1
        prom.set_device_connections(counts_by_state)
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics: device aggregation failed: %s", exc)
    return {"counts_by_state": counts_by_state}


# ==================== Prometheus bridge ====================


def _bump_ai_prometheus(values: Dict[str, Any]) -> None:
    """Update Prometheus only after a successful, non-duplicate insert."""
    prom.record_ai_usage_prometheus(
        source=values["source"],
        agent_kind=values.get("agent_kind"),
        provider=values.get("provider"),
        model=values.get("model"),
        status=values.get("status"),
        error_kind=values.get("error_kind"),
        input_tokens=values.get("input_tokens", 0),
        output_tokens=values.get("output_tokens", 0),
        cache_read_tokens=values.get("cache_read_tokens", 0),
        cache_write_tokens=values.get("cache_write_tokens", 0),
        duration_ms=values.get("duration_ms"),
    )


__all__ = [
    "METADATA_ALLOWLIST",
    "normalize_tokens",
    "compute_total_tokens",
    "estimate_cost_microusd",
    "sanitize_metadata",
    "record_ai_usage",
    "record_ai_usage_sync",
    "record_business_event",
    "record_agent_run_usage",
    "record_agent_run_usage_sync",
    "normalize_bucket",
    "normalize_user_sort",
    "aggregate_system_metrics",
    "aggregate_user_metrics_list",
    "aggregate_user_detail",
    "aggregate_self_metrics",
    "aggregate_chat_metrics",
    "aggregate_log_metrics",
    "aggregate_package_metrics",
    "aggregate_device_metrics",
    "list_metric_events",
]
