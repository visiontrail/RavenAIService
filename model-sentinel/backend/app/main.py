from __future__ import annotations

import asyncio
import csv
import io
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from .analytics import (
    aggregate,
    bucket_runs,
    calling_windows,
    capacity_signal,
    hourly_heatmap,
    period_window,
)
from .config import config
from .crypto import SecretBox
from .database import Database
from .probe import run_probe
from .worker import MonitorWorker


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)
UTC = timezone.utc

secret_box = SecretBox(config.secret_key_path)
database = Database(config.database_path, secret_box, config)
worker = MonitorWorker(database)


class SettingsUpdate(BaseModel):
    target_name: str = Field(min_length=1, max_length=80)
    protocol: Literal["anthropic", "openai"]
    base_url: str = Field(min_length=4, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=500)
    enabled: bool
    interval_seconds: int = Field(ge=30, le=86400)
    timeout_seconds: int = Field(ge=5, le=3600)
    max_tokens: int = Field(ge=16, le=200000)
    alert_latency_ms: int = Field(ge=1000, le=3600000)
    retention_days: int = Field(ge=7, le=3650)
    timezone: str = Field(min_length=1, max_length=80)
    agent_prompt: str = Field(min_length=10, max_length=10000)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("Base URL 必须以 http:// 或 https:// 开头")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("无效的 IANA 时区") from exc
        return value


class SettingsTest(BaseModel):
    target_name: str = "临时测试"
    protocol: Literal["anthropic", "openai"]
    base_url: str
    model: str
    api_key: str | None = None
    timeout_seconds: int = Field(default=60, ge=5, le=3600)
    max_tokens: int = Field(default=96, ge=16, le=200000)
    alert_latency_ms: int = Field(default=30000, ge=1000, le=3600000)
    agent_prompt: str = Field(min_length=1, max_length=10000)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(database.initialize)
    task = asyncio.create_task(worker.serve(), name="model-sentinel-worker")
    logger.info("Model Sentinel is ready; database=%s", config.database_path)
    try:
        yield
    finally:
        worker.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


app = FastAPI(
    title="Model Sentinel",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "model-sentinel",
        "time": datetime.now(UTC).isoformat(),
    }


@app.get("/api/settings")
async def get_settings() -> dict[str, Any]:
    return {"success": True, "data": await asyncio.to_thread(database.get_settings)}


@app.put("/api/settings")
async def put_settings(payload: SettingsUpdate) -> dict[str, Any]:
    data = payload.model_dump()
    if not data.get("api_key"):
        data.pop("api_key", None)
    settings = await asyncio.to_thread(database.update_settings, data)
    worker.notify_settings_changed()
    return {"success": True, "data": settings}


@app.post("/api/settings/test")
async def test_settings(payload: SettingsTest) -> dict[str, Any]:
    stored = await asyncio.to_thread(database.get_settings, True)
    candidate = {**stored, **payload.model_dump()}
    candidate["api_key"] = payload.api_key.strip() if payload.api_key else stored["api_key"]
    result = await run_probe(candidate, source="settings_test")
    return {"success": result["success"], "data": result}


@app.post("/api/probes/run")
async def trigger_probe() -> dict[str, Any]:
    if worker.probe_lock.locked():
        raise HTTPException(status_code=409, detail="已有探测正在执行")
    result = await worker.run_once("manual")
    return {"success": result["success"], "data": result}


def range_periods(range_name: str, granularity: str) -> int:
    hours = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}[range_name]
    return hours if granularity == "hourly" else max(1, hours // 24)


@app.get("/api/dashboard")
async def dashboard(
    range_name: Literal["24h", "7d", "30d"] = Query(default="24h", alias="range"),
    granularity: Literal["hourly", "daily"] | None = None,
) -> dict[str, Any]:
    settings = await asyncio.to_thread(database.get_settings)
    default_granularity = "daily" if range_name == "30d" else "hourly"
    selected_granularity = granularity or default_granularity
    start, end = period_window(
        range_periods(range_name, selected_granularity),
        selected_granularity,
        settings["timezone"],
    )
    runs = await asyncio.to_thread(database.list_probes, start, end)
    recent = await asyncio.to_thread(database.list_probes, None, None, 10)
    seven_day_start = end - timedelta(days=7)
    seven_day_runs = await asyncio.to_thread(database.list_probes, seven_day_start, end)
    history_start = end - timedelta(days=min(90, settings["retention_days"]))
    history = await asyncio.to_thread(database.list_probes, history_start, end)
    metrics = aggregate(runs)
    latest = recent[0] if recent else None
    state = _live_state(settings, latest, worker.probe_lock.locked())
    return {
        "success": True,
        "data": {
            "range": range_name,
            "granularity": selected_granularity,
            "generated_at": end.isoformat(),
            "state": state,
            "settings": {
                key: settings[key]
                for key in (
                    "target_name",
                    "protocol",
                    "base_url",
                    "model",
                    "enabled",
                    "interval_seconds",
                    "alert_latency_ms",
                    "timezone",
                    "api_key_set",
                )
            },
            "overview": metrics,
            "series": bucket_runs(
                runs, start, end, selected_granularity, settings["timezone"]
            ),
            "heatmap": hourly_heatmap(
                seven_day_runs, settings["timezone"], days=7
            ),
            "calling_windows": calling_windows(
                history, settings["timezone"], settings["alert_latency_ms"]
            ),
            "capacity_signal": capacity_signal(
                metrics, settings["alert_latency_ms"]
            ),
            "recent": recent,
        },
    }


@app.get("/api/analytics/{granularity}")
async def analytics(
    granularity: Literal["hourly", "daily"],
    periods: int = Query(default=24, ge=1, le=1000),
) -> dict[str, Any]:
    settings = await asyncio.to_thread(database.get_settings)
    start, end = period_window(periods, granularity, settings["timezone"])
    runs = await asyncio.to_thread(database.list_probes, start, end)
    return {
        "success": True,
        "data": bucket_runs(runs, start, end, granularity, settings["timezone"]),
    }


@app.get("/api/export")
async def export_csv(
    granularity: Literal["hourly", "daily"] = "hourly",
    periods: int = Query(default=168, ge=1, le=3650),
) -> StreamingResponse:
    settings = await asyncio.to_thread(database.get_settings)
    start, end = period_window(periods, granularity, settings["timezone"])
    runs = await asyncio.to_thread(database.list_probes, start, end)
    buckets = bucket_runs(runs, start, end, granularity, settings["timezone"])
    output = io.StringIO()
    fields = [
        "local_time",
        "calls",
        "successes",
        "failures",
        "uptime_pct",
        "usable_pct",
        "avg_latency_ms",
        "p95_latency_ms",
        "p95_ttft_ms",
        "rate_limited",
        "server_errors",
        "total_tokens",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for bucket in buckets:
        writer.writerow({field: bucket.get(field) for field in fields})
    filename = f"model-sentinel-{granularity}-{datetime.now(UTC).date()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _live_state(
    settings: dict[str, Any],
    latest: dict[str, Any] | None,
    probe_active: bool = False,
) -> dict[str, Any]:
    if not settings["api_key_set"]:
        return {
            "level": "configuring",
            "label": "等待 API Key",
            "detail": "请前往设置页完成被测模型凭据配置",
        }
    if not settings["enabled"]:
        return {"level": "paused", "label": "监控已暂停", "detail": "定时探测当前关闭"}
    if probe_active:
        return {
            "level": "starting",
            "label": "Agent 探测中",
            "detail": "正在等待目标模型完成真实推理任务",
        }
    if latest is None:
        return {"level": "starting", "label": "准备首轮探测", "detail": "调度器已启动"}
    age = (
        datetime.now(UTC) - datetime.fromisoformat(latest["started_at"]).astimezone(UTC)
    ).total_seconds()
    if age > settings["interval_seconds"] * 2.5:
        return {
            "level": "stale",
            "label": "数据已过期",
            "detail": "最近探测时间超过两个调度周期",
        }
    if not latest["success"]:
        return {
            "level": "down",
            "label": "模型不可用",
            "detail": latest.get("error_message") or "最近一次探测失败",
        }
    if not latest["usable"]:
        return {
            "level": "degraded",
            "label": "响应缓慢",
            "detail": "最近一次调用成功，但超过可用延迟阈值",
        }
    return {"level": "healthy", "label": "运行正常", "detail": "最近一次 Agent 探测成功"}


STATIC_DIR = Path("/app/static")
if not STATIC_DIR.exists():
    STATIC_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@app.get("/{full_path:path}", include_in_schema=False, response_model=None)
async def serve_frontend(full_path: str):
    if not STATIC_DIR.exists():
        return JSONResponse(
            {"detail": "Frontend build not found. Run npm run build in frontend."},
            status_code=404,
        )
    candidate = (STATIC_DIR / full_path).resolve()
    try:
        candidate.relative_to(STATIC_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found") from None
    if full_path and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(STATIC_DIR / "index.html")
