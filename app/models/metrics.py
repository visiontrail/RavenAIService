"""Metrics event model and API schemas.

``MetricEvent`` is the persisted, auditable fact source for AI token usage and
selected business activity. One row represents one auditable event; AI calls are
recorded at the granularity of a single invocation/run terminal state.

Privacy contract: this table MUST NOT store prompts, assistant answers, raw tool
input/output, log content, credentials, cookies, or token-bearing URLs. Only the
low-sensitivity ownership identifiers and the allowlisted ``metadata_json`` summary
are persisted (see ``app/services/metrics_service.py``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseResponse
from .database import Base, TimestampMixin


class MetricEvent(Base, TimestampMixin):
    """A single auditable metrics event (AI usage or business activity)."""

    __tablename__ = "metric_events"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="事件ID",
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        comment="幂等键，重复写入只保留一条，例如 ai_usage:chat_run:<run_id>",
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="事件发生时间（独立于 row 创建时间）",
    )
    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="ai_usage / chat_activity / log_activity / package_activity / device_activity",
    )
    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="如 general_agent / device_agent / log_analysis_agent / log_upload",
    )
    # Ownership fields (low sensitivity, used for attribution / audit only).
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        nullable=True,
        comment="登录用户ID；匿名或系统任务为空",
    )
    owner_scope: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
        comment="归属作用域，仅用于审计与匿名聚合，不返回给普通用户",
    )
    session_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, comment="会话ID（审计用）"
    )
    run_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, comment="Run ID（审计用）"
    )
    task_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="Celery/任务ID（审计用）"
    )
    log_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, comment="日志记录ID（审计用）"
    )
    project_repo_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, comment="项目仓库ID（审计用）"
    )
    # AI invocation descriptors.
    agent_kind: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, comment="device / log_analysis / project / package / general / title"
    )
    provider: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="anthropic / deepseek / custom"
    )
    model: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, comment="使用的模型名称"
    )
    status: Mapped[Optional[str]] = mapped_column(
        String(24),
        nullable=True,
        comment="succeeded/failed/cancelled/stale/timeout 等终态",
    )
    error_kind: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="错误归类（低基数）"
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="耗时（毫秒）"
    )
    # Token counters (never NULL; missing usage is normalized to 0).
    input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="输入 Token"
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="输出 Token"
    )
    cache_read_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="缓存读取 Token"
    )
    cache_write_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="缓存写入 Token"
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="总 Token = input+output+cache_read+cache_write"
    )
    cost_microusd: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="按配置估算的百万分之一美元成本；未配置价格时为空",
    )
    # Allowlisted low-sensitivity summary only (see metrics_service sanitization).
    metadata_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="经 allowlist 过滤后的低敏摘要 JSON"
    )

    __table_args__ = (
        Index("idx_metric_events_occurred_at", "occurred_at"),
        Index("idx_metric_events_user_time", "user_id", "occurred_at"),
        Index("idx_metric_events_event_source_time", "event_type", "source", "occurred_at"),
        Index("idx_metric_events_agent_model_time", "agent_kind", "provider", "model", "occurred_at"),
        Index("idx_metric_events_status_time", "status", "occurred_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<MetricEvent id={self.id} type={self.event_type} "
            f"source={self.source} total_tokens={self.total_tokens}>"
        )


# ==================== Pydantic API Schemas ====================


class TokenBreakdown(BaseModel):
    """Token 分解，所有字段缺失视为 0。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0


class TimeSeriesBucket(BaseModel):
    """时间桶聚合点。"""

    bucket_start: datetime = Field(..., description="桶起始时间")
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    invocation_count: int = 0
    success_count: int = 0
    failure_count: int = 0


class GroupCount(BaseModel):
    """按某一维度（source/agent_kind/provider/model/status）的计数与 Token 汇总。"""

    key: Optional[str] = Field(None, description="维度取值，None 表示未知")
    invocation_count: int = 0
    total_tokens: int = 0


class StatusCounts(BaseModel):
    """终态状态计数。"""

    succeeded: int = 0
    failed: int = 0
    cancelled: int = 0
    stale: int = 0
    timeout: int = 0
    other: int = 0


class ChatActivitySummary(BaseModel):
    """聊天/用户活跃度摘要。"""

    total_users: int = 0
    active_users: int = 0
    chat_session_count: int = 0
    chat_message_count: int = 0
    run_counts_by_status: Dict[str, int] = Field(default_factory=dict)


class LogActivitySummary(BaseModel):
    """日志上传与 AI 分析摘要。"""

    upload_count: int = 0
    uploaded_bytes: int = 0
    counts_by_log_type: Dict[str, int] = Field(default_factory=dict)
    counts_by_status: Dict[str, int] = Field(default_factory=dict)
    ai_analysis_counts: Dict[str, int] = Field(default_factory=dict)


class PackageActivitySummary(BaseModel):
    """Raven 包库存与活动摘要。"""

    package_count: int = 0
    total_bytes: int = 0
    counts_by_type: Dict[str, int] = Field(default_factory=dict)
    activity_counts: Dict[str, int] = Field(default_factory=dict)
    search_count: int = 0


class DeviceActivitySummary(BaseModel):
    """设备连接摘要。"""

    counts_by_state: Dict[str, int] = Field(default_factory=dict)


class SystemOverview(BaseModel):
    """系统级 overview 响应数据。"""

    from_time: datetime
    to_time: datetime
    bucket: str
    tokens: TokenBreakdown = Field(default_factory=TokenBreakdown)
    estimated_cost_usd: Optional[float] = Field(
        None, description="估算成本（美元）；未配置价格时为 null"
    )
    cost_estimated: bool = Field(False, description="是否存在可用价格估算")
    invocation_count: int = 0
    status_counts: StatusCounts = Field(default_factory=StatusCounts)
    error_count: int = 0
    duration_ms_avg: Optional[float] = None
    duration_ms_p95: Optional[float] = None
    invocations_by_source: List[GroupCount] = Field(default_factory=list)
    invocations_by_agent_kind: List[GroupCount] = Field(default_factory=list)
    invocations_by_provider: List[GroupCount] = Field(default_factory=list)
    invocations_by_model: List[GroupCount] = Field(default_factory=list)
    invocations_by_status: List[GroupCount] = Field(default_factory=list)
    time_series: List[TimeSeriesBucket] = Field(default_factory=list)
    chat: ChatActivitySummary = Field(default_factory=ChatActivitySummary)
    logs: LogActivitySummary = Field(default_factory=LogActivitySummary)
    packages: PackageActivitySummary = Field(default_factory=PackageActivitySummary)
    devices: DeviceActivitySummary = Field(default_factory=DeviceActivitySummary)


class SystemOverviewResponse(BaseResponse):
    data: SystemOverview


class UserMetricsRow(BaseModel):
    """用户列表中的一行统计。"""

    user_id: str
    username: Optional[str] = None
    display_name: Optional[str] = None
    role: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: Optional[float] = None
    run_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    message_count: int = 0
    last_active_at: Optional[datetime] = None
    top_agent_kind: Optional[str] = None


class UserMetricsListData(BaseModel):
    from_time: datetime
    to_time: datetime
    page: int
    per_page: int
    total: int
    sort: str
    rows: List[UserMetricsRow] = Field(default_factory=list)


class UserMetricsListResponse(BaseResponse):
    data: UserMetricsListData


class RawMetricEvent(BaseModel):
    """原始事件（已 sanitize），供 admin 审计。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    idempotency_key: str
    occurred_at: datetime
    event_type: str
    source: str
    user_id: Optional[str] = None
    owner_scope: Optional[str] = None
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    task_id: Optional[str] = None
    log_id: Optional[str] = None
    project_repo_id: Optional[str] = None
    agent_kind: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    status: Optional[str] = None
    error_kind: Optional[str] = None
    duration_ms: Optional[int] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    cost_microusd: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


class UserMetricsDetail(BaseModel):
    """单用户详情。"""

    user_id: str
    username: Optional[str] = None
    display_name: Optional[str] = None
    role: Optional[str] = None
    from_time: datetime
    to_time: datetime
    bucket: str
    tokens: TokenBreakdown = Field(default_factory=TokenBreakdown)
    estimated_cost_usd: Optional[float] = None
    cost_estimated: bool = False
    invocation_count: int = 0
    status_counts: StatusCounts = Field(default_factory=StatusCounts)
    message_count: int = 0
    last_active_at: Optional[datetime] = None
    invocations_by_source: List[GroupCount] = Field(default_factory=list)
    invocations_by_agent_kind: List[GroupCount] = Field(default_factory=list)
    invocations_by_provider: List[GroupCount] = Field(default_factory=list)
    invocations_by_model: List[GroupCount] = Field(default_factory=list)
    errors_by_kind: List[GroupCount] = Field(default_factory=list)
    time_series: List[TimeSeriesBucket] = Field(default_factory=list)
    recent_events: List[RawMetricEvent] = Field(default_factory=list)


class UserMetricsDetailResponse(BaseResponse):
    data: UserMetricsDetail


class SelfMetricsSummary(BaseModel):
    """用户自查摘要（仅当前登录用户）。"""

    user_id: str
    from_time: datetime
    to_time: datetime
    bucket: str
    tokens: TokenBreakdown = Field(default_factory=TokenBreakdown)
    estimated_cost_usd: Optional[float] = None
    cost_estimated: bool = False
    invocation_count: int = 0
    status_counts: StatusCounts = Field(default_factory=StatusCounts)
    message_count: int = 0
    last_active_at: Optional[datetime] = None
    invocations_by_agent_kind: List[GroupCount] = Field(default_factory=list)
    time_series: List[TimeSeriesBucket] = Field(default_factory=list)


class SelfMetricsResponse(BaseResponse):
    data: SelfMetricsSummary


class RawMetricEventsData(BaseModel):
    from_time: datetime
    to_time: datetime
    page: int
    per_page: int
    total: int
    events: List[RawMetricEvent] = Field(default_factory=list)


class RawMetricEventsResponse(BaseResponse):
    data: RawMetricEventsData
