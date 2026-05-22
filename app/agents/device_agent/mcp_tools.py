"""远端设备 MCP 工具 → in-process Claude Agent SDK 工具 的动态映射。

每次 :class:`DeviceAgent` 处理一次 ``chat`` 请求时，先调用
:func:`build_device_mcp_server` 把 ``device.capabilities.mcp.servers[].tools[]``
全部翻译成 SDK 工具，再用 ``create_sdk_mcp_server`` 注册到 ``ClaudeAgentOptions``
里。工具调用通过 ``dispatcher`` 转发到上位机；上位机回包由 ``PostToolUse`` hook
做结构化审查（详见 ``post_tool_hook.py``）。

设计上拆为三块：

- :func:`build_device_mcp_server`     —— 主入口，组装 server + tool_meta
- :func:`default_dispatcher`          —— 默认实现，把工具调用打包成 v2 envelope
                                         发到 ``device_link_manager``；旧设备走
                                         legacy ``【DEVICE_TASK】`` 文本
- :class:`ToolMeta`                   —— 工具风险/outputSchema/原始字段缓存
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from app.agents.device_agent.trace import (
    AgentTraceEvent,
    SeqCounter,
    build_event,
    safe_emit,
)

logger = logging.getLogger(__name__)


# ─────────────────────── Data Structures ───────────────────────────


@dataclass
class ToolMeta:
    """SDK 工具背后远端设备工具的元信息。

    供 ``permissions.classify_risk`` / ``post_tool_hook.validate`` 使用。
    """

    sdk_name: str                                  # mcp__device__<server>__<tool>
    server: str                                    # 原始 server 名（未 sanitize）
    tool: str                                      # 原始 tool 名（未 sanitize）
    description: str
    input_schema: Dict[str, Any]
    output_schema: Optional[Dict[str, Any]] = None
    risk: Optional[str] = None                     # capability-declared, normalize 后小写
    raw: Dict[str, Any] = field(default_factory=dict)  # 原始 capability 条目，供调试


DispatcherFn = Callable[..., Awaitable[Dict[str, Any]]]

EmitFn = Callable[[AgentTraceEvent], None]


# ─────────────────────── Helpers ───────────────────────────────────


_SANITIZE_RE = re.compile(r"[^A-Za-z0-9_]+")


def _sanitize(name: str) -> str:
    """SDK / MCP 工具名要求 ``[A-Za-z0-9_]``；其余字符替换为下划线。"""
    cleaned = _SANITIZE_RE.sub("_", str(name or "")).strip("_")
    return cleaned or "unknown"


def _extract_servers(device: Any) -> List[Dict[str, Any]]:
    """从 ``DeviceInfo`` 中提取 ``mcp.servers[]`` 列表，缺失时返回空列表。"""
    capabilities = getattr(device, "capabilities", None) or {}
    if not isinstance(capabilities, dict):
        return []
    mcp = capabilities.get("mcp")
    if not isinstance(mcp, dict):
        return []
    servers = mcp.get("servers")
    if not isinstance(servers, list):
        return []
    return [s for s in servers if isinstance(s, dict)]


def _extract_protocol_version(device: Any) -> int:
    """读取 ``device.capabilities.protocol_version``；缺失或非整数时返回 0。"""
    capabilities = getattr(device, "capabilities", None) or {}
    if not isinstance(capabilities, dict):
        return 0
    raw = capabilities.get("protocol_version")
    if isinstance(raw, bool):
        return 0
    if isinstance(raw, (int, float)):
        try:
            return int(raw)
        except (ValueError, TypeError):
            return 0
    if isinstance(raw, str) and raw.strip().isdigit():
        return int(raw.strip())
    return 0


def _normalize_risk(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in {"read", "write", "destructive"}:
        return v
    # 别名兼容：read-only / readonly / safe / mutating ...
    if v in {"readonly", "read-only", "safe", "ro"}:
        return "read"
    if v in {"mutating", "write", "rw"}:
        return "write"
    if v in {"danger", "dangerous", "irreversible"}:
        return "destructive"
    return None


def _flatten_tools(servers: List[Dict[str, Any]]) -> List[Tuple[str, str, Dict[str, Any]]]:
    """展开成 ``(server_name, tool_name, raw_tool_entry)`` 列表，按 (s,t) 排序。"""
    out: List[Tuple[str, str, Dict[str, Any]]] = []
    for server in servers:
        sname = str(server.get("name") or server.get("server") or "").strip()
        if not sname:
            continue
        tools = server.get("tools")
        if not isinstance(tools, list):
            continue
        for entry in tools:
            if not isinstance(entry, dict):
                continue
            tname = str(entry.get("name") or entry.get("tool") or "").strip()
            if not tname:
                continue
            out.append((sname, tname, entry))
    out.sort(key=lambda x: (x[0], x[1]))
    return out


# ─────────────────────── Dispatcher ────────────────────────────────


_LEGACY_NOTICE_SENT_KEY = "_legacy_envelope_sent"


def _build_legacy_prompt(server: str, tool: str, args: Dict[str, Any]) -> str:
    """构造与旧 ChatAgent 等价的 ``【DEVICE_TASK】`` 文本 envelope。"""
    try:
        args_json = json.dumps(args or {}, ensure_ascii=False)
    except Exception:
        args_json = "{}"
    qualified = f"{server}.{tool}" if server else tool
    return "\n".join([
        "【DEVICE_TASK】",
        f"目标: 调用设备 MCP 工具 {qualified}",
        f"工具选择: {qualified}",
        f"参数(JSON): {args_json}",
        "约束:",
        "- 仅执行一次上述工具调用，不要调用其他工具。",
        "- 若缺少必要参数或无法确定值，请返回需要补充的字段清单，不要猜测。",
        "期望返回:",
        "- chosen_tool: <工具名>",
        "- args: <最终使用的参数 JSON>",
        "- result: <关键结果/回执/错误>",
        "- evidence: <可选：关键日志/关键字段，尽量简短>",
        "成功判定:",
        "- 工具调用按参数完成，且返回结构化结果。",
        "【/DEVICE_TASK】",
    ])


def _parse_device_reply(reply: Any) -> Dict[str, Any]:
    """把上位机 ``PromptResultMessage`` 转成 Decision 10 schema 的 dict。

    上位机若已经返回结构化 JSON 字符串，按 JSON 解析；解析失败时回退为
    ``{"status": "ok", "result": {"answer": <raw>}, "topic_id": ..., "raw_messages": ...}``。
    """
    if reply is None:
        return {"status": "error", "error_kind": "internal_error", "error_message": "empty reply"}
    if isinstance(reply, dict):
        # 上位机直接给了 Decision 10 schema
        if {"status", "result"} & set(reply.keys()) or "error_kind" in reply:
            return reply
        answer = reply.get("answer")
        topic_id = reply.get("topic_id")
        # 尝试把 answer 当 JSON 解析
        if isinstance(answer, str):
            try:
                parsed = json.loads(answer)
                if isinstance(parsed, dict):
                    parsed.setdefault("topic_id", topic_id)
                    return parsed
            except (ValueError, TypeError):
                pass
        return {
            "status": "ok",
            "topic_id": topic_id,
            "result": {"answer": answer} if answer is not None else {},
            "raw_messages": reply.get("raw_messages"),
        }
    # 非 dict 应答：包成 ok
    return {"status": "ok", "result": {"answer": str(reply)}}


async def default_dispatcher(
    server: str,
    tool: str,
    args: Dict[str, Any],
    *,
    session_id: str,
    target_device_id: str,
    request_id: str,
    protocol_version: int = 2,
    emit: Optional[EmitFn] = None,
    state: Optional[Dict[str, Any]] = None,
    seq_counter: Optional[SeqCounter] = None,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """默认 dispatcher 实现：构造 envelope → 通过 device_link_manager 投递 → 解析回包。

    异常一律转成 ``{"status":"error","error_kind":"internal_error","error_message":...}``
    返回，避免穿透 SDK loop。
    """
    from app.models.device_link import PromptEnvelope
    from app.services.device_link_service import device_link_manager

    args = args or {}
    use_legacy = protocol_version < 2
    if use_legacy:
        prompt = _build_legacy_prompt(server, tool, args)
        # 一次会话只发一次 legacy_envelope 通知
        if state is not None and seq_counter is not None and emit is not None:
            if not state.get(_LEGACY_NOTICE_SENT_KEY):
                state[_LEGACY_NOTICE_SENT_KEY] = True
                safe_emit(
                    emit,
                    build_event(
                        "system_notice",
                        task_id=task_id or session_id or "",
                        seq_counter=seq_counter,
                        kind="legacy_envelope",
                        detail=(
                            f"Device protocol_version={protocol_version} (<2); "
                            "falling back to legacy 【DEVICE_TASK】 text envelope."
                        ),
                    ),
                )
    else:
        envelope_payload = {
            "protocol_version": 2,
            "action": "mcp_call",
            "server": server,
            "tool": tool,
            "args": args,
            "request_id": request_id,
            "permission_decision": "allow",
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        try:
            prompt = json.dumps(envelope_payload, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            return {
                "status": "error",
                "error_kind": "internal_error",
                "error_message": f"failed to serialize envelope: {exc}",
            }

    envelope = PromptEnvelope(
        request_id=request_id,
        session_id=session_id or "",
        prompt=prompt,
        system_prompt=None,
        target_device_id=target_device_id,
        metadata={
            "source": "device_agent",
            "protocol_version": 2 if not use_legacy else (protocol_version or 1),
            "server": server,
            "tool": tool,
        },
    )

    try:
        reply = await device_link_manager.send_prompt(target_device_id, envelope)
    except Exception as exc:
        logger.warning(
            "DeviceAgent dispatcher failed: device=%s server=%s tool=%s err=%s",
            target_device_id, server, tool, exc,
        )
        return {
            "status": "error",
            "error_kind": "internal_error",
            "error_message": str(exc),
            "request_id": request_id,
        }

    parsed = _parse_device_reply(reply)
    parsed.setdefault("request_id", request_id)
    return parsed


# ─────────────────────── Builder ───────────────────────────────────


def _wrap_result_for_sdk(payload: Dict[str, Any]) -> Dict[str, Any]:
    """SDK 工具必须返回 ``{"content": [{"type":"text","text":...}]}`` 形态。
    我们把 dispatcher 给的结构化 dict 序列化成 JSON 文本。PostToolUse hook 会
    在结果回喂给模型前再次解析、校验、裁剪。"""
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        text = str(payload)
    return {"content": [{"type": "text", "text": text}]}


def build_device_mcp_server(
    device: Any,
    *,
    session_id: str,
    target_device_id: str,
    dispatcher: Optional[DispatcherFn] = None,
    emit: Optional[EmitFn] = None,
    seq_counter: Optional[SeqCounter] = None,
    task_id: Optional[str] = None,
    max_remote_tools: Optional[int] = None,
) -> Tuple[Any, List[str], Dict[str, ToolMeta]]:
    """根据 device.capabilities 构造 in-process MCP server 与工具元数据。

    Args:
        device: ``DeviceInfo`` 对象（或拥有 ``capabilities`` dict 属性的任意结构）。
        session_id: 会话 ID，写入 envelope.session_id。
        target_device_id: 目标设备 ID。
        dispatcher: 工具调用 → 上位机的实际投递函数；为 ``None`` 时使用
            :func:`default_dispatcher`。测试可注入 mock。
        emit: trace 事件 emitter；当工具数被截断或走 legacy envelope 时会发
            ``system_notice``。
        seq_counter: 与 ``emit`` 配套的 SeqCounter；缺失则只能 silent emit。
        task_id: trace event 的 task_id 字段（DeviceAgent 通常用 session_id）。
        max_remote_tools: 最大工具数；缺省使用 ``settings.device_agent_max_remote_tools``。

    Returns:
        ``(server, allowed_tool_names, tool_meta_map)``：
        - server: ``create_sdk_mcp_server`` 返回的 MCP server 对象，传给
          ``ClaudeAgentOptions.mcp_servers={"device": server}``。
        - allowed_tool_names: ``["mcp__device__<server>__<tool>", ...]``，
          调用方再追加 ``"Skill"`` 后塞进 ``allowed_tools``。
        - tool_meta_map: ``{sdk_name: ToolMeta}``，给 permissions / post-tool-hook 用。
    """
    from app.config import settings

    try:
        from claude_agent_sdk import create_sdk_mcp_server, tool
    except ImportError as exc:
        raise RuntimeError(
            "claude-agent-sdk is required. Install with: pip install claude-agent-sdk>=0.1"
        ) from exc

    if max_remote_tools is None:
        max_remote_tools = int(getattr(settings, "device_agent_max_remote_tools", 64))

    protocol_version = _extract_protocol_version(device)

    # 共享状态在 dispatcher 闭包之间传递（如 legacy_envelope 一次性通知标记）。
    shared_state: Dict[str, Any] = {}

    _dispatch = dispatcher or default_dispatcher

    flat = _flatten_tools(_extract_servers(device))
    total = len(flat)
    dropped: List[str] = []
    if total > max_remote_tools:
        kept = flat[:max_remote_tools]
        dropped = [f"{s}.{t}" for s, t, _ in flat[max_remote_tools:]]
        flat = kept

    tool_funcs: List[Any] = []
    tool_meta_map: Dict[str, ToolMeta] = {}
    allowed_names: List[str] = []

    for server_name, tool_name, entry in flat:
        sdk_short = f"{_sanitize(server_name)}__{_sanitize(tool_name)}"
        sdk_full = f"mcp__device__{sdk_short}"

        description = entry.get("description")
        if not isinstance(description, str) or not description.strip():
            description = f"Invoke {server_name}.{tool_name} on the linked device"

        input_schema = entry.get("inputSchema")
        if not isinstance(input_schema, dict):
            input_schema = entry.get("input_schema") if isinstance(entry.get("input_schema"), dict) else None
        if not isinstance(input_schema, dict):
            input_schema = {"type": "object", "additionalProperties": True}

        output_schema = entry.get("outputSchema")
        if not isinstance(output_schema, dict):
            output_schema = entry.get("output_schema") if isinstance(entry.get("output_schema"), dict) else None

        risk = _normalize_risk(entry.get("risk") or entry.get("x-risk"))

        meta = ToolMeta(
            sdk_name=sdk_full,
            server=server_name,
            tool=tool_name,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
            risk=risk,
            raw=dict(entry),
        )
        tool_meta_map[sdk_full] = meta
        allowed_names.append(sdk_full)

        proxy_fn = _make_proxy(
            tool_short=sdk_short,
            description=description,
            input_schema=input_schema,
            server_name=server_name,
            tool_name=tool_name,
            dispatcher=_dispatch,
            session_id=session_id,
            target_device_id=target_device_id,
            protocol_version=protocol_version,
            emit=emit,
            state=shared_state,
            seq_counter=seq_counter,
            task_id=task_id,
            tool_decorator=tool,
        )
        tool_funcs.append(proxy_fn)

    # 即使没有工具，也注册一个空 server，让调用方拿到一致的 (server, [], {}).
    server = create_sdk_mcp_server(
        name="device",
        version="1.0.0",
        tools=tool_funcs,
    )

    if dropped and emit is not None and seq_counter is not None:
        safe_emit(
            emit,
            build_event(
                "system_notice",
                task_id=task_id or session_id or "",
                seq_counter=seq_counter,
                kind="too_many_tools",
                detail=(
                    f"Device reported {total} MCP tools, exceeding cap "
                    f"{max_remote_tools}; dropped {len(dropped)} tools "
                    f"after sorting by (server, tool): {dropped}"
                ),
            ),
        )

    logger.info(
        "DeviceAgent MCP server built: device=%s total_tools=%d kept=%d dropped=%d proto=%s",
        target_device_id,
        total,
        len(allowed_names),
        len(dropped),
        protocol_version or "(none)",
    )

    return server, allowed_names, tool_meta_map


def _make_proxy(
    *,
    tool_short: str,
    description: str,
    input_schema: Dict[str, Any],
    server_name: str,
    tool_name: str,
    dispatcher: DispatcherFn,
    session_id: str,
    target_device_id: str,
    protocol_version: int,
    emit: Optional[EmitFn],
    state: Dict[str, Any],
    seq_counter: Optional[SeqCounter],
    task_id: Optional[str],
    tool_decorator: Callable[..., Any],
) -> Any:
    """为单个 (server, tool) 生成 SDK proxy；闭包捕获 dispatcher 上下文。"""

    @tool_decorator(tool_short, description, input_schema)
    async def _proxy(args):
        try:
            arg_dict = args if isinstance(args, dict) else {"value": args}
        except Exception:
            arg_dict = {}
        request_id = str(uuid.uuid4())
        try:
            result = await dispatcher(
                server_name,
                tool_name,
                arg_dict,
                session_id=session_id,
                target_device_id=target_device_id,
                request_id=request_id,
                protocol_version=protocol_version,
                emit=emit,
                state=state,
                seq_counter=seq_counter,
                task_id=task_id,
            )
        except Exception as exc:
            # dispatcher 自身已经拦截大部分异常；这里是最后一道兜底。
            logger.exception(
                "DeviceAgent proxy unexpected error: server=%s tool=%s",
                server_name, tool_name,
            )
            result = {
                "status": "error",
                "error_kind": "internal_error",
                "error_message": f"proxy crash: {exc}",
                "request_id": request_id,
            }
        if not isinstance(result, dict):
            result = {"status": "ok", "result": {"value": result}}
        return _wrap_result_for_sdk(result)

    return _proxy


__all__ = [
    "ToolMeta",
    "DispatcherFn",
    "EmitFn",
    "build_device_mcp_server",
    "default_dispatcher",
]
