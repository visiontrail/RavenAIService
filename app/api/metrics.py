"""Prometheus scrape endpoint.

Exposes ``GET /metrics`` in the standard Prometheus text format. When
``prometheus_client`` is not installed the endpoint returns ``503`` so
the operator notices the gap rather than silently scraping empty data.
"""

from fastapi import APIRouter, Response

from app.utils.metrics import (
    CONTENT_TYPE_LATEST,
    is_prometheus_available,
    render_latest,
)

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    if not is_prometheus_available():
        return Response(
            content="prometheus_client not installed",
            status_code=503,
            media_type="text/plain; charset=utf-8",
        )
    return Response(content=render_latest(), media_type=CONTENT_TYPE_LATEST)
