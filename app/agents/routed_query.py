"""Endpoint-aware wrapper around the Claude Agent SDK ``query()`` loop.

Every agent drives the SDK the same way::

    async for message in query(prompt=..., options=build_options(...)):

This module replaces that with a loop that first picks an endpoint, and retries
on the next one if the chosen endpoint fails *before* producing any model
output. It also measures time-to-first-token, which is the signal
:mod:`app.services.model_router` needs to notice a degraded endpoint at all —
the main app records only whole-run wall clock today, and a 20-minute log
analysis says nothing about how fast the gateway is answering.

**Where the retry boundary sits, and why it is safe.** The SDK emits
``SystemMessage(subtype="init")`` first, after the CLI subprocess is up but
*before* any model round trip — so it is not a latency signal and is excluded
from the TTFT clock. The first message that requires the model is a
``StreamEvent`` (partial streaming) or an ``AssistantMessage``. Tools only ever
run in response to a ``tool_use`` block inside an ``AssistantMessage``, so
nothing has executed yet at that point. Abandoning an attempt before that
message is therefore side-effect-free for every agent — including bug_fix,
which otherwise pushes branches and opens merge requests.

Once that message arrives the attempt is **committed**: the rest of the stream
passes through untouched and no further failover happens. Re-running a
committed attempt would replay tool side effects and pay for the tokens twice.

**Nothing is yielded before commit.** Messages received during an attempt are
buffered and released only once it commits. Otherwise an abandoned attempt
would already have leaked trace events to the browser — ``_emit_for_message``
turns ``SystemMessage(init)`` into a visible ``system_notice``.

This phase does **not** preempt a slow-but-alive attempt on a deadline. Doing
that requires cancelling the SDK generator, and ``transport.close()`` takes up
to 10s (5s graceful + 5s SIGTERM) while ``Query.close()`` swallows
``CancelledError`` — so a naive ``asyncio.timeout`` around the loop both fails
to fire and can orphan the ``claude`` subprocess. Failover here is driven by
*raised* exceptions, where the generator has already finalised itself and no
cancellation is involved.
"""

from __future__ import annotations

import logging
import time
from typing import Any, AsyncIterator, Callable, List, Optional, Tuple

from app.services import model_router
from app.services.model_router import (
    AllEndpointsUnavailable,
    EndpointChoice,
    OUTCOME_HARD_FAILURE,
    OUTCOME_OK,
)

logger = logging.getLogger(__name__)

__all__ = ["routed_query", "AllEndpointsUnavailable", "EndpointChoice"]


def _now() -> float:
    """Monotonic clock, indirected so tests can drive TTFT deterministically.

    Patching ``time.monotonic`` itself would also retime the event loop.
    """
    return time.monotonic()

# Exception *names* that mean "never reached the model" rather than "the model
# said no". Matched by name so this module does not import httpx/anyio just to
# classify; substring matching keeps it robust across SDK transport wrappers.
_HARD_FAILURE_MARKERS = (
    "connect",
    "connection",
    "timeout",
    "dns",
    "unauthorized",
    "authentication",
)


def _classify(exc: BaseException) -> str:
    name = f"{type(exc).__name__} {exc}".lower()
    if any(marker in name for marker in _HARD_FAILURE_MARKERS):
        return OUTCOME_HARD_FAILURE
    return OUTCOME_HARD_FAILURE if isinstance(exc, OSError) else "error"


def _is_init_message(message: Any) -> bool:
    """``SystemMessage(subtype='init')`` — CLI is up, model not yet contacted."""
    return (
        getattr(message, "subtype", None) == "init"
        and isinstance(getattr(message, "data", None), dict)
    )


#
# Commit is defined by exclusion — "anything that is not the init notice" —
# rather than by enumerating the message shapes that count as model output
# (StreamEvent / AssistantMessage / …). Enumerating is the fragile direction:
# a shape the list does not recognise stays buffered forever and is silently
# dropped if the run is then cancelled or errors. Getting it wrong the other
# way merely means committing one message early, which costs a failover
# opportunity but never loses output.


async def routed_query(
    *,
    prompt: Any,
    make_options: Callable[[Optional[EndpointChoice]], Any],
    agent_kind: str = "",
    require_mcp: bool = False,
    require_image: bool = False,
    require_document: bool = False,
    require_small_fast: bool = False,
    on_endpoint: Optional[Callable[[EndpointChoice], None]] = None,
    sdk_query: Optional[Callable[..., AsyncIterator[Any]]] = None,
    candidates: Optional[List[EndpointChoice]] = None,
) -> AsyncIterator[Any]:
    """Drive ``query()`` against the best available endpoint, failing over on error.

    ``make_options`` is called once per candidate — options must be rebuilt, not
    reused, because capability gating (MCP tools, system prompt selection) is
    baked into them per provider. ``on_endpoint`` fires as soon as a candidate is
    chosen and before any message is yielded, so callers can record which
    endpoint actually served the run in their own telemetry.

    ``candidates`` accepts an already-resolved list from
    :func:`app.services.model_router.candidates`. Agents that emit a ``run_start``
    trace event naming the model must resolve the endpoint *before* that event
    goes out — it is already on the wire to the browser by the time the first
    message arrives — so they select first and hand the result in here.
    """
    if sdk_query is None:
        from claude_agent_sdk import query as sdk_query  # type: ignore[no-redef]

    choices = candidates if candidates is not None else model_router.candidates(
        agent_kind=agent_kind,
        require_mcp=require_mcp,
        require_image=require_image,
        require_document=require_document,
        require_small_fast=require_small_fast,
    )
    if not choices:
        # No routed endpoint is usable (routing off, or nothing configured).
        # Fall through to the legacy path so behaviour is unchanged.
        choices = [None]  # type: ignore[list-item]

    failures: List[Tuple[str, BaseException]] = []

    for index, choice in enumerate(choices):
        slot = choice.slot if choice is not None else "settings"
        options = make_options(choice)
        if choice is not None and on_endpoint is not None:
            on_endpoint(choice)

        started = _now()
        committed = False
        pending: List[Any] = []

        try:
            async for message in sdk_query(prompt=prompt, options=options):
                if not committed:
                    if _is_init_message(message):
                        # CLI startup, not model latency — restart the clock so
                        # TTFT measures the gateway rather than process spawn.
                        started = _now()
                        pending.append(message)
                        continue
                    committed = True
                    ttft_ms = int((_now() - started) * 1000)
                    if choice is not None:
                        model_router.record_outcome(
                            slot, outcome=OUTCOME_OK, ttft_ms=ttft_ms
                        )
                    logger.info(
                        "routed_query: committed slot=%s agent_kind=%s ttft_ms=%d",
                        slot,
                        agent_kind,
                        ttft_ms,
                    )
                    for buffered in pending:
                        yield buffered
                    pending.clear()
                yield message
            if not committed:
                # The stream ended without any assistant output — a refusal or a
                # bare terminal result. The upstream did answer (the generator
                # finished cleanly), so this is not an endpoint failure; release
                # what we buffered rather than dropping it on the floor.
                if choice is not None:
                    model_router.record_outcome(slot, outcome=OUTCOME_OK)
                logger.info(
                    "routed_query: slot=%s produced no assistant message "
                    "(agent_kind=%s, %d buffered)",
                    slot,
                    agent_kind,
                    len(pending),
                )
                for buffered in pending:
                    yield buffered
            return
        except Exception as exc:  # noqa: BLE001
            if committed:
                # Mid-stream failure: the run is already partly done and the
                # caller owns the error. Retrying would replay tool side
                # effects and re-bill the tokens.
                raise
            outcome = _classify(exc)
            if choice is not None:
                model_router.record_outcome(slot, outcome=outcome)
            failures.append((slot, exc))
            remaining = len(choices) - index - 1
            logger.warning(
                "routed_query: slot=%s failed before first token (agent_kind=%s, "
                "outcome=%s): %s%s",
                slot,
                agent_kind,
                outcome,
                exc,
                f" — trying {remaining} more endpoint(s)" if remaining else "",
            )
            continue

    raise AllEndpointsUnavailable(failures)
