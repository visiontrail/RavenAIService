from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .database import Database
from .probe import run_probe


logger = logging.getLogger(__name__)
UTC = timezone.utc


class MonitorWorker:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.stop_event = asyncio.Event()
        self.wake_event = asyncio.Event()
        self.probe_lock = asyncio.Lock()

    async def serve(self) -> None:
        logger.info("monitor worker started")
        while not self.stop_event.is_set():
            try:
                settings = await asyncio.to_thread(self.database.get_settings, True)
                wait_seconds = self._seconds_until_next(settings)
                if wait_seconds <= 0:
                    await self.run_once("scheduled")
                    continue
                self.wake_event.clear()
                try:
                    await asyncio.wait_for(self.wake_event.wait(), timeout=wait_seconds)
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("monitor loop failed; retrying")
                await asyncio.sleep(5)
        logger.info("monitor worker stopped")

    async def run_once(self, source: str = "manual") -> dict:
        async with self.probe_lock:
            settings = await asyncio.to_thread(self.database.get_settings, True)
            result = await run_probe(settings, source=source)
            result["id"] = await asyncio.to_thread(self.database.insert_probe, result)
            await asyncio.to_thread(
                self.database.cleanup, int(settings["retention_days"])
            )
            return result

    def notify_settings_changed(self) -> None:
        self.wake_event.set()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()

    def _seconds_until_next(self, settings: dict) -> float:
        if not settings["enabled"] or not settings.get("api_key"):
            return 10.0
        latest = self.database.latest_probe()
        if not latest:
            return 0.0
        # Measure the interval from completion, not start. A slow/timeout probe
        # must never cause an immediate retry loop that hammers the target.
        last_finished = datetime.fromisoformat(latest["finished_at"]).astimezone(UTC)
        elapsed = (datetime.now(UTC) - last_finished).total_seconds()
        return max(0.0, float(settings["interval_seconds"]) - elapsed)
