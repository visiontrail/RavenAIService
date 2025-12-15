"""
LangChain tool to route prompts to a linked device via DeviceLinkManager.
"""

import json
import logging
import uuid
from contextvars import ContextVar
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.models.device_link import PromptEnvelope
from app.services.device_link_service import device_link_manager

logger = logging.getLogger(__name__)

_session_id_ctx: ContextVar[Optional[str]] = ContextVar("device_prompt_session_id", default=None)
_target_device_id_ctx: ContextVar[Optional[str]] = ContextVar("device_prompt_target_device_id", default=None)
_system_prompt_ctx: ContextVar[Optional[str]] = ContextVar("device_prompt_system_prompt", default=None)


def set_device_prompt_context(
    session_id: Optional[str],
    target_device_id: Optional[str],
    system_prompt: Optional[str],
) -> None:
    """Set per-request defaults that the tool can fall back to."""
    _session_id_ctx.set(session_id)
    _target_device_id_ctx.set(target_device_id)
    _system_prompt_ctx.set(system_prompt)


def clear_device_prompt_context() -> None:
    """Reset context vars to avoid leaking values across requests."""
    _session_id_ctx.set(None)
    _target_device_id_ctx.set(None)
    _system_prompt_ctx.set(None)


class DevicePromptInput(BaseModel):
    """Tool input schema for forwarding a prompt to a device."""

    prompt: str = Field(..., description="Prompt content that should run on the target device")
    session_id: Optional[str] = Field(
        None, description="AIChat session id, so multiple prompts stay in one topic (default from context)"
    )
    target_device_id: Optional[str] = Field(
        None, description="Target device id registered via device-link (default from context)"
    )
    system_prompt: Optional[str] = Field(None, description="Optional system prompt passed to the device")


@tool("device_prompt", args_schema=DevicePromptInput)
async def device_prompt_tool(
    prompt: str,
    session_id: str,
    target_device_id: str,
    system_prompt: Optional[str] = None,
) -> str:
    """Send a prompt to a linked device and return its answer plus topic_id."""
    session_id = session_id or _session_id_ctx.get()
    target_device_id = target_device_id or _target_device_id_ctx.get()
    system_prompt = system_prompt if system_prompt is not None else _system_prompt_ctx.get()

    if not session_id:
        raise ValueError("session_id is required to call device_prompt_tool")
    if not target_device_id:
        raise ValueError("target_device_id is required to call device_prompt_tool")

    request_id = str(uuid.uuid4())
    envelope = PromptEnvelope(
        request_id=request_id,
        session_id=session_id,
        prompt=prompt,
        system_prompt=system_prompt,
        target_device_id=target_device_id,
    )

    logger.info(
        "device_prompt_tool: dispatching prompt to device",
        extra={"target_device_id": target_device_id, "session_id": session_id, "request_id": request_id},
    )
    try:
        result = await device_link_manager.send_prompt(device_id=target_device_id, payload=envelope)
    except Exception as exc:  # noqa: BLE001
        logger.error("device_prompt_tool: failed to send prompt: %s", exc, exc_info=True)
        raise

    answer = result.get("answer") if isinstance(result, dict) else getattr(result, "answer", "")
    topic_id = result.get("topic_id") if isinstance(result, dict) else getattr(result, "topic_id", None)
    logger.info(
        "device_prompt_tool: received device result",
        extra={"target_device_id": target_device_id, "request_id": request_id, "has_answer": bool(answer)},
    )
    payload = {"answer": answer or "", "topic_id": topic_id}
    return json.dumps(payload, ensure_ascii=False)
