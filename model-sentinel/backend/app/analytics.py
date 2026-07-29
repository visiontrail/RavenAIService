from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any, Iterable
from zoneinfo import ZoneInfo


UTC = timezone.utc


def period_window(
    periods: int, granularity: str, timezone_name: str
) -> tuple[datetime, datetime]:
    """Return a window containing exactly N local calendar buckets."""
    end = datetime.now(UTC)
    local_end = end.astimezone(ZoneInfo(timezone_name))
    if granularity == "daily":
        local_start = local_end.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=periods - 1)
    else:
        local_start = local_end.replace(
            minute=0, second=0, microsecond=0
        ) - timedelta(hours=periods - 1)
    return local_start.astimezone(UTC), end


def percentile(values: Iterable[int | float | None], quantile: float) -> int | None:
    ordered = sorted(float(value) for value in values if value is not None)
    if not ordered:
        return None
    if len(ordered) == 1:
        return round(ordered[0])
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower])
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    calls = len(runs)
    successes = sum(1 for run in runs if run["success"])
    usable = sum(1 for run in runs if run["usable"])
    rate_limited = sum(1 for run in runs if run.get("error_kind") == "rate_limited")
    server_errors = sum(1 for run in runs if run.get("error_kind") == "server_error")
    success_latencies = [run["latency_ms"] for run in runs if run["success"]]
    ttfts = [run["ttft_ms"] for run in runs if run["success"] and run.get("ttft_ms")]
    return {
        "calls": calls,
        "successes": successes,
        "failures": calls - successes,
        "usable_calls": usable,
        "uptime_pct": round(successes / calls * 100, 2) if calls else None,
        "usable_pct": round(usable / calls * 100, 2) if calls else None,
        "avg_latency_ms": round(mean(success_latencies)) if success_latencies else None,
        "p95_latency_ms": percentile(success_latencies, 0.95),
        "p95_ttft_ms": percentile(ttfts, 0.95),
        "rate_limited": rate_limited,
        "rate_limit_pct": round(rate_limited / calls * 100, 2) if calls else None,
        "server_errors": server_errors,
        "total_tokens": sum(int(run.get("total_tokens") or 0) for run in runs),
    }


def bucket_runs(
    runs: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    granularity: str,
    timezone_name: str,
) -> list[dict[str, Any]]:
    tz = ZoneInfo(timezone_name)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        instant = datetime.fromisoformat(run["started_at"]).astimezone(tz)
        if granularity == "daily":
            key = instant.strftime("%Y-%m-%d")
        else:
            key = instant.strftime("%Y-%m-%dT%H:00:00%z")
        grouped[key].append(run)

    cursor = start.astimezone(tz)
    if granularity == "daily":
        cursor = cursor.replace(hour=0, minute=0, second=0, microsecond=0)
        step = timedelta(days=1)
    else:
        cursor = cursor.replace(minute=0, second=0, microsecond=0)
        step = timedelta(hours=1)

    buckets: list[dict[str, Any]] = []
    while cursor < end.astimezone(tz):
        key = (
            cursor.strftime("%Y-%m-%d")
            if granularity == "daily"
            else cursor.strftime("%Y-%m-%dT%H:00:00%z")
        )
        metrics = aggregate(grouped.get(key, []))
        buckets.append(
            {
                "key": key,
                "label": cursor.strftime("%m/%d")
                if granularity == "daily"
                else cursor.strftime("%H:00"),
                "local_time": cursor.isoformat(),
                **metrics,
            }
        )
        cursor += step
    return buckets


def hourly_heatmap(
    runs: list[dict[str, Any]], timezone_name: str, days: int = 7
) -> list[dict[str, Any]]:
    tz = ZoneInfo(timezone_name)
    today = datetime.now(tz).date()
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        instant = datetime.fromisoformat(run["started_at"]).astimezone(tz)
        grouped[(instant.strftime("%Y-%m-%d"), instant.hour)].append(run)

    output: list[dict[str, Any]] = []
    for day_offset in range(days - 1, -1, -1):
        date = today - timedelta(days=day_offset)
        date_key = date.isoformat()
        for hour in range(24):
            metrics = aggregate(grouped.get((date_key, hour), []))
            output.append(
                {
                    "date": date_key,
                    "date_label": date.strftime("%m/%d"),
                    "hour": hour,
                    "calls": metrics["calls"],
                    "uptime_pct": metrics["uptime_pct"],
                    "p95_latency_ms": metrics["p95_latency_ms"],
                }
            )
    return output


def calling_windows(
    runs: list[dict[str, Any]], timezone_name: str, alert_latency_ms: int
) -> dict[str, Any]:
    tz = ZoneInfo(timezone_name)
    by_hour: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        hour = datetime.fromisoformat(run["started_at"]).astimezone(tz).hour
        by_hour[hour].append(run)

    ranked: list[dict[str, Any]] = []
    for hour, samples in by_hour.items():
        metrics = aggregate(samples)
        uptime = metrics["uptime_pct"] or 0
        latency = metrics["p95_latency_ms"]
        latency_score = (
            max(0.0, 100.0 - (latency / max(1, alert_latency_ms)) * 45)
            if latency is not None
            else 0.0
        )
        confidence = min(1.0, len(samples) / 12)
        score = round((uptime * 0.72 + latency_score * 0.28) * confidence, 1)
        ranked.append(
            {
                "hour": hour,
                "label": f"{hour:02d}:00–{(hour + 1) % 24:02d}:00",
                "score": score,
                "samples": len(samples),
                "uptime_pct": metrics["uptime_pct"],
                "p95_latency_ms": latency,
            }
        )
    ranked.sort(key=lambda item: (item["score"], item["samples"]), reverse=True)
    sample_count = len(runs)
    return {
        "ready": sample_count >= 12 and len(by_hour) >= 2,
        "sample_count": sample_count,
        "minimum_samples": 12,
        "windows": ranked[:3],
    }


def capacity_signal(metrics: dict[str, Any], alert_latency_ms: int) -> dict[str, str]:
    if not metrics["calls"]:
        return {
            "level": "insufficient",
            "title": "等待观测样本",
            "detail": "完成首轮真实 Agent 探测后，将自动给出扩容或负载均衡建议。",
        }
    uptime = metrics["uptime_pct"] or 0
    p95 = metrics["p95_latency_ms"] or 0
    limit_pct = metrics["rate_limit_pct"] or 0
    if uptime < 95 or limit_pct >= 5 or p95 >= alert_latency_ms * 1.5:
        return {
            "level": "critical",
            "title": "建议尽快扩容",
            "detail": "可用率、限流或尾延迟已越过容量红线，现有节点难以稳定承接 Agent 工况。",
        }
    if uptime < 99 or limit_pct >= 1 or p95 >= alert_latency_ms:
        return {
            "level": "warning",
            "title": "建议增加负载均衡",
            "detail": "服务仍可使用，但存在明显波动；建议分流高峰请求并准备弹性节点。",
        }
    return {
        "level": "healthy",
        "title": "当前容量可承载",
        "detail": "观测窗口内可用性与尾延迟均在阈值内，可继续积累数据验证全天稳定性。",
    }
