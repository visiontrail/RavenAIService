from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx


logger = logging.getLogger(__name__)
UTC = timezone.utc


def endpoint_url(base_url: str, protocol: str) -> str:
    base = base_url.rstrip("/")
    if protocol == "openai":
        return f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
    return f"{base}/messages" if base.endswith("/v1") else f"{base}/v1/messages"


def classify_http_error(status: int) -> tuple[str, str]:
    if status in {401, 403}:
        return "auth_error", "认证失败"
    if status == 404:
        return "not_found", "端点或模型不存在"
    if status == 408:
        return "upstream_timeout", "上游请求超时"
    if status == 429:
        return "rate_limited", "模型服务器限流"
    if 400 <= status < 500:
        return "client_error", "请求被上游拒绝"
    if status >= 500:
        return "server_error", "模型服务器异常"
    return "http_error", "HTTP 请求失败"


def excerpt(value: Any, limit: int = 480) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[:limit]}…"


async def run_probe(settings: dict[str, Any], source: str = "scheduled") -> dict[str, Any]:
    started_at = datetime.now(UTC)
    start_clock = time.monotonic()
    url = endpoint_url(settings["base_url"], settings["protocol"])
    result: dict[str, Any] = {
        "source": source,
        "started_at": started_at.isoformat(),
        "finished_at": started_at.isoformat(),
        "success": False,
        "usable": False,
        "status_category": "failed",
        "http_status": None,
        "latency_ms": 0,
        "first_byte_ms": None,
        "ttft_ms": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "error_kind": None,
        "error_message": None,
        "response_excerpt": None,
        "model": settings["model"],
        "endpoint": url,
    }

    if not settings.get("api_key"):
        return _finish_failure(result, start_clock, "missing_api_key", "尚未配置 API Key")

    body, headers = _request_payload(settings)
    timeout = httpx.Timeout(float(settings["timeout_seconds"]), connect=15.0)
    text_parts: list[str] = []
    completed = False

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            async with client.stream("POST", url, headers=headers, json=body) as response:
                result["http_status"] = response.status_code
                if response.status_code < 200 or response.status_code >= 300:
                    error_body = excerpt((await response.aread()).decode("utf-8", "replace"))
                    kind, label = classify_http_error(response.status_code)
                    return _finish_failure(
                        result,
                        start_clock,
                        kind,
                        f"{label}（HTTP {response.status_code}）{': ' + error_body if error_body else ''}",
                    )

                content_type = response.headers.get("content-type", "")
                async for line in response.aiter_lines():
                    elapsed = round((time.monotonic() - start_clock) * 1000)
                    if result["first_byte_ms"] is None and line:
                        result["first_byte_ms"] = elapsed
                    if not line:
                        continue
                    payload = line[5:].strip() if line.startswith("data:") else line.strip()
                    if not payload or payload == "[DONE]":
                        completed = completed or payload == "[DONE]"
                        continue
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        if "text/event-stream" not in content_type:
                            text_parts.append(payload)
                        continue
                    event_completed, event_text = _consume_event(event, result, settings["protocol"])
                    completed = completed or event_completed
                    if event_text:
                        if result["ttft_ms"] is None:
                            result["ttft_ms"] = elapsed
                        text_parts.append(event_text)

        latency_ms = round((time.monotonic() - start_clock) * 1000)
        result.update(
            {
                "finished_at": datetime.now(UTC).isoformat(),
                "success": True,
                "usable": latency_ms <= int(settings["alert_latency_ms"]),
                "status_category": "healthy"
                if latency_ms <= int(settings["alert_latency_ms"])
                else "slow",
                "latency_ms": latency_ms,
                "response_excerpt": excerpt("".join(text_parts), 360),
            }
        )
        if result["first_byte_ms"] is None:
            result["first_byte_ms"] = latency_ms
        if result["ttft_ms"] is None and text_parts:
            result["ttft_ms"] = result["first_byte_ms"]
        if not text_parts:
            result["status_category"] = "empty_response"
            result["success"] = False
            result["usable"] = False
            result["error_kind"] = "empty_response"
            result["error_message"] = (
                "模型请求已完成，但没有生成最终文本答案"
                if completed
                else "上游返回成功状态，但没有可识别的响应内容"
            )
        result["total_tokens"] = result["input_tokens"] + result["output_tokens"]
        return result
    except httpx.TimeoutException:
        return _finish_failure(
            result,
            start_clock,
            "timeout",
            f"超过 {settings['timeout_seconds']} 秒仍未完成",
        )
    except httpx.ConnectError as exc:
        return _finish_failure(result, start_clock, "connect_error", excerpt(exc))
    except httpx.HTTPError as exc:
        return _finish_failure(result, start_clock, "network_error", excerpt(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("unexpected probe failure")
        return _finish_failure(result, start_clock, "probe_error", excerpt(exc))


def _request_payload(settings: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    if settings["protocol"] == "openai":
        return (
            {
                "model": settings["model"],
                "max_tokens": settings["max_tokens"],
                "stream": True,
                "stream_options": {"include_usage": True},
                "messages": [{"role": "user", "content": settings["agent_prompt"]}],
            },
            {
                "Authorization": f"Bearer {settings['api_key']}",
                "Content-Type": "application/json",
            },
        )
    return (
        {
            "model": settings["model"],
            "max_tokens": settings["max_tokens"],
            "stream": True,
            "messages": [{"role": "user", "content": settings["agent_prompt"]}],
        },
        {
            "x-api-key": settings["api_key"],
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )


def _consume_event(
    event: dict[str, Any], result: dict[str, Any], protocol: str
) -> tuple[bool, str]:
    if protocol == "openai":
        usage = event.get("usage") or {}
        result["input_tokens"] = int(usage.get("prompt_tokens") or result["input_tokens"])
        result["output_tokens"] = int(
            usage.get("completion_tokens") or result["output_tokens"]
        )
        choices = event.get("choices") or []
        if choices and isinstance(choices[0], dict):
            delta = choices[0].get("delta") or {}
            message = choices[0].get("message") or {}
            content = delta.get("content") or message.get("content")
            return bool(choices[0].get("finish_reason")), str(content or "")
        return False, ""

    event_type = event.get("type")
    # A few compatible gateways ignore stream=true and return one regular
    # Messages response. Treat that as a valid completed event too.
    if event_type == "message" and isinstance(event.get("content"), list):
        usage = event.get("usage") or {}
        result["input_tokens"] = int(usage.get("input_tokens") or 0)
        result["output_tokens"] = int(usage.get("output_tokens") or 0)
        text = "".join(
            str(block.get("text") or "")
            for block in event["content"]
            if isinstance(block, dict) and block.get("type") == "text"
        )
        return True, text
    if event_type == "message_start":
        usage = (event.get("message") or {}).get("usage") or {}
        result["input_tokens"] = int(usage.get("input_tokens") or 0)
    elif event_type == "message_delta":
        usage = event.get("usage") or {}
        result["output_tokens"] = int(
            usage.get("output_tokens") or result["output_tokens"]
        )
    elif event_type == "content_block_delta":
        delta = event.get("delta") or {}
        if delta.get("type") == "text_delta":
            return False, str(delta.get("text") or "")
    return event_type == "message_stop", ""


def _finish_failure(
    result: dict[str, Any], start_clock: float, kind: str, message: str
) -> dict[str, Any]:
    result.update(
        {
            "finished_at": datetime.now(UTC).isoformat(),
            "latency_ms": round((time.monotonic() - start_clock) * 1000),
            "status_category": "failed",
            "error_kind": kind,
            "error_message": excerpt(message),
        }
    )
    return result
