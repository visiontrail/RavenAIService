"""
Device link manager: tracks connected devices and routes prompts over WebSocket.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Tuple

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from app.config import settings
from app.models.device_link import (
    DeviceInfo,
    PromptEnvelope,
    PromptResultMessage,
    RegisterMessage,
)
from app.services.base import BaseService

logger = logging.getLogger(__name__)


@dataclass
class _DeviceState:
    websocket: Optional[WebSocket]
    info: DeviceInfo
    client_version: Optional[str] = None
    metadata: Dict[str, object] = field(default_factory=dict)


class DeviceLinkManager(BaseService):
    """Manage connected device WebSocket links and prompt routing."""

    def __init__(self):
        super().__init__()
        self._devices: Dict[str, _DeviceState] = {}
        self._pending_prompts: Dict[str, Tuple[asyncio.Future, str]] = {}
        self._lock = asyncio.Lock()

    async def register_device(self, websocket: WebSocket, payload: RegisterMessage) -> DeviceInfo:
        """Record a device registration and keep its WebSocket reference."""
        device_id = payload.get("device_id")
        if not device_id:
            raise ValueError("device_id is required for registration")

        info = DeviceInfo(
            id=device_id,
            name=payload.get("device_name") or device_id,
            host=payload.get("host"),
            models=payload.get("models") or [],
            capabilities=payload.get("capabilities") or {},
            last_seen=datetime.utcnow(),
            status="online",
        )
        state = _DeviceState(
            websocket=websocket,
            info=info,
            client_version=payload.get("client_version"),
            metadata={"capabilities": payload.get("capabilities") or {}},
        )

        async with self._lock:
            previous = self._devices.get(device_id)
            if previous and previous.websocket and previous.websocket.application_state == WebSocketState.CONNECTED:
                try:
                    await previous.websocket.close()
                except Exception:  # noqa: BLE001
                    logger.debug("Failed to close previous websocket for %s", device_id, exc_info=True)
            self._devices[device_id] = state
        self.log_info("Device registered", extra={"device_id": device_id, "host": info.host})
        return info

    async def update_heartbeat(self, device_id: str) -> Optional[DeviceInfo]:
        """Mark device as alive."""
        async with self._lock:
            state = self._devices.get(device_id)
            if not state:
                return None
            state.info.last_seen = datetime.utcnow()
            state.info.status = "online"
            return state.info

    async def mark_offline(self, device_id: str) -> None:
        """Mark device offline and fail pending prompts."""
        async with self._lock:
            state = self._devices.get(device_id)
            if not state:
                return
            state.info.status = "offline"
            state.info.last_seen = datetime.utcnow()
            state.websocket = None
        self._fail_pending_for_device(device_id, RuntimeError(f"Device {device_id} disconnected"))
        self.log_info("Device disconnected", extra={"device_id": device_id})

    def list_devices(self) -> list[DeviceInfo]:
        """Return a snapshot list of devices."""
        return [DeviceInfo(**device.info.model_dump()) for device in self._devices.values()]

    async def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        """Fetch a single device snapshot."""
        async with self._lock:
            state = self._devices.get(device_id)
            if not state:
                return None
            return DeviceInfo(**state.info.model_dump())

    async def send_prompt(self, device_id: str, payload: PromptEnvelope) -> PromptResultMessage:
        """
        Send a prompt to the device and wait for its prompt_result reply.

        Raises:
            RuntimeError: when device is offline or no response before timeout.
        """
        state = await self._get_active_state(device_id)
        message = {"type": "prompt", **payload.model_dump(exclude_none=True)}

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        async with self._lock:
            self._pending_prompts[payload.request_id] = (future, device_id)
            state.info.last_seen = datetime.utcnow()

        timeout = getattr(settings, "device_link_timeout_sec", 120)
        try:
            await state.websocket.send_text(json.dumps(message))
            self.log_info("Prompt dispatched to device", extra={"device_id": device_id, "request_id": payload.request_id})
            result = await asyncio.wait_for(future, timeout=timeout)
            await self.update_heartbeat(device_id)
            return result  # type: ignore[return-value]
        except asyncio.TimeoutError as exc:
            self.log_warning(
                "Device prompt timed out",
                extra={"device_id": device_id, "request_id": payload.request_id, "timeout": timeout},
            )
            raise RuntimeError(f"Device {device_id} did not respond within {timeout} seconds") from exc
        except Exception:
            self.log_error("Failed to send prompt to device", extra={"device_id": device_id})
            raise
        finally:
            self._pending_prompts.pop(payload.request_id, None)

    async def handle_prompt_result(self, device_id: str, payload: PromptResultMessage) -> None:
        """Resolve the waiting future for a prompt result."""
        await self.update_heartbeat(device_id)
        request_id = payload.get("request_id")
        if not request_id:
            self.log_warning("Received prompt_result without request_id", extra={"device_id": device_id})
            return

        entry = self._pending_prompts.get(request_id)
        if not entry:
            self.log_warning("No pending prompt for result", extra={"device_id": device_id, "request_id": request_id})
            return

        future, owner = entry
        if owner != device_id:
            self.log_warning(
                "Prompt result device mismatch",
                extra={"expected_device": owner, "device_id": device_id, "request_id": request_id},
            )
        if not future.done():
            future.set_result(payload)
        self._pending_prompts.pop(request_id, None)

    async def ping_device(self, device_id: str) -> DeviceInfo:
        """Send a ping frame to a device to confirm liveness."""
        state = await self._get_active_state(device_id)
        await state.websocket.send_text(json.dumps({"type": "ping"}))
        await self.update_heartbeat(device_id)
        return DeviceInfo(**state.info.model_dump())

    async def _get_active_state(self, device_id: str) -> _DeviceState:
        async with self._lock:
            state = self._devices.get(device_id)
            if not state:
                raise RuntimeError(f"Device {device_id} not registered")
            websocket = state.websocket
            if websocket is None or websocket.application_state != WebSocketState.CONNECTED:
                raise RuntimeError(f"Device {device_id} is offline")
            if state.info.status != "online":
                raise RuntimeError(f"Device {device_id} is offline")
            return state

    def _fail_pending_for_device(self, device_id: str, exc: Exception) -> None:
        for request_id, (future, owner) in list(self._pending_prompts.items()):
            if owner != device_id:
                continue
            if not future.done():
                future.set_exception(exc)
            self._pending_prompts.pop(request_id, None)


device_link_manager = DeviceLinkManager()
