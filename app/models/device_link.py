"""
Device link WebSocket contract shared with RavenClient.

Endpoint: ws://<raven_ai_service_host>:8085/ws/device-link

Message types (all frames are JSON text):
- register (client -> server)
  {
      "type": "register",
      "device_id": "...",
      "device_name": "...",
      "client_version": "...",
      "host": "...",
      "models": ["..."],
      "capabilities": {...}  # optional feature flags or metadata
  }
- register_ack (server -> client)
  {
      "type": "register_ack",
      "device_id": "...",
      "heartbeat_interval": <seconds>,
      "server_time": <unix_timestamp_seconds>
  }
- ping / pong (bidirectional): {"type": "ping"} / {"type": "pong"}
- prompt (server -> client)
  {
      "type": "prompt",
      "request_id": "...",
      "session_id": "...",
      "prompt": "...",
      "system_prompt": "...",  # optional system prompt override
      "target_device_id": "...",
      "metadata": {...}  # optional routing/debug info
  }
- prompt_ack (client -> server, optional)
  {
      "type": "prompt_ack",
      "request_id": "...",
      "session_id": "...",
      "topic_id": "..."  # optional Topic id used on the client
  }
- prompt_result (client -> server)
  {
      "type": "prompt_result",
      "request_id": "...",
      "session_id": "...",
      "topic_id": "...",
      "answer": "...",
      "raw_messages": [...]  # optional LLM/raw message history
  }
- capabilities_update (client -> server)
  {
      "type": "capabilities_update",
      "device_id": "...",   # optional; inferred from the websocket session
      "capabilities": {...} # latest capability metadata (e.g., MCP tools/prompts/resources)
  }
- error (bidirectional): {"type": "error", "request_id": "...", "message": "..."} (request_id optional)

Server keeps: device_id -> connection with status/last_seen/metadata, and a pending map request_id -> future.
Client keeps: session_id -> topic_id so prompts within one AIChat session reuse the same Topic.
"""

from datetime import datetime
from typing import Dict, List, Literal, Optional, TypedDict

from pydantic import BaseModel, Field


class RegisterMessage(TypedDict, total=False):
    """Client -> Server registration payload."""

    type: Literal["register"]
    device_id: str
    device_name: str
    client_version: str
    host: str
    models: List[str]
    capabilities: Dict[str, object]


class RegisterAckMessage(TypedDict):
    """Server -> Client registration acknowledgment."""

    type: Literal["register_ack"]
    device_id: str
    heartbeat_interval: int
    server_time: float


class PingMessage(TypedDict):
    """Heartbeat ping."""

    type: Literal["ping"]


class PongMessage(TypedDict):
    """Heartbeat pong."""

    type: Literal["pong"]


class PromptMessage(TypedDict, total=False):
    """Server -> Client prompt payload to request local LLM execution."""

    type: Literal["prompt"]
    request_id: str
    session_id: str
    prompt: str
    system_prompt: Optional[str]
    target_device_id: str
    metadata: Dict[str, object]


class PromptAckMessage(TypedDict, total=False):
    """Optional Client -> Server prompt acknowledgment."""

    type: Literal["prompt_ack"]
    request_id: str
    session_id: str
    topic_id: Optional[str]


class PromptResultMessage(TypedDict, total=False):
    """Client -> Server prompt result payload."""

    type: Literal["prompt_result"]
    request_id: str
    session_id: str
    topic_id: str
    answer: str
    raw_messages: List[object]


class ErrorMessage(TypedDict, total=False):
    """Bidirectional error payload."""

    type: Literal["error"]
    request_id: Optional[str]
    message: str


class CapabilitiesUpdateMessage(TypedDict, total=False):
    """Client -> Server capabilities update payload."""

    type: Literal["capabilities_update"]
    device_id: Optional[str]
    capabilities: Dict[str, object]


DeviceStatus = Literal["online", "offline"]


class DeviceInfo(BaseModel):
    """Snapshot of a connected (or recently connected) device."""

    id: str = Field(..., description="设备唯一ID")
    name: str = Field(..., description="设备名称")
    host: Optional[str] = Field(None, description="设备主机/地址")
    models: List[str] = Field(default_factory=list, description="可用模型列表")
    capabilities: Dict[str, object] = Field(default_factory=dict, description="能力/元数据")
    last_seen: Optional[datetime] = Field(None, description="最近心跳时间")
    status: DeviceStatus = Field("offline", description="设备状态")


class PromptEnvelope(BaseModel):
    """Server-to-device prompt envelope used by DeviceLinkManager."""

    request_id: str = Field(..., description="请求ID")
    session_id: str = Field(..., description="会话ID")
    prompt: str = Field(..., description="用户提示词")
    system_prompt: Optional[str] = Field(None, description="可选系统提示词")
    target_device_id: str = Field(..., description="目标设备ID")
    metadata: Optional[Dict[str, object]] = Field(default=None, description="可选路由元数据")
