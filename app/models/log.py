"""
日志相关数据模型
包含SQLAlchemy数据库模型和Pydantic数据验证模型
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator, computed_field
from enum import Enum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, Integer, Text, Enum as SQLEnum, UUID, Float, Boolean
import uuid

from .base import BaseResponse, PaginatedResponse
from .database import Base, TimestampMixin


class LogStatus(str, Enum):
    """日志处理状态枚举"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class LogLevel(str, Enum):
    """日志级别枚举"""
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    FATAL = "fatal"


class LogType(str, Enum):
    """日志类型枚举"""
    STACK = "stack"
    OAM_ANTENNA = "oam_antenna"
    FULL = "full"  # 全量日志（包含协议栈和OAM/天线日志）


# ==================== SQLAlchemy 数据库模型 ====================

class LogRecord(Base, TimestampMixin):
    """日志记录数据库模型"""
    __tablename__ = "log_records"
    
    # 主键字段
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="日志记录主键UUID"
    )
    
    # 文件相关字段
    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="文件名"
    )
    original_filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="原始文件名"
    )
    file_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="文件大小（字节）"
    )
    file_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="文件存储路径"
    )
    
    # 日志类型和状态
    log_type: Mapped[LogType] = mapped_column(
        SQLEnum(LogType),
        nullable=False,
        default=LogType.STACK,
        comment="日志类型"
    )
    status: Mapped[LogStatus] = mapped_column(
        SQLEnum(LogStatus),
        nullable=False,
        default=LogStatus.PENDING,
        comment="处理状态"
    )
    
    # 处理进度
    progress: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="处理进度（0-100）"
    )
    
    # 下载次数
    download_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="下载次数"
    )
    
    # 任务相关字段
    task_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Celery任务ID"
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="重试次数"
    )
    processing_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="处理开始时间"
    )
    
    # 时间字段
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="处理完成时间"
    )
    
    # 可选字段
    checksum: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="文件校验和"
    )
    mime_type: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="MIME类型"
    )
    log_level: Mapped[Optional[LogLevel]] = mapped_column(
        SQLEnum(LogLevel),
        nullable=True,
        default=LogLevel.INFO,
        comment="日志级别"
    )
    
    # 元数据（JSON格式存储）
    metadata_json: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="元数据JSON字符串"
    )
    
    # 错误信息
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="错误信息"
    )
    
    # 问题描述
    issue_description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="问题描述"
    )
    
    # 软删除字段
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否已删除（软删除）"
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="删除时间"
    )
    
    def __repr__(self) -> str:
        return f"<LogRecord(id={self.id}, filename={self.filename}, status={self.status})>"


# ==================== Pydantic 数据验证模型 ====================

class LogMetadata(BaseModel):
    """日志元数据模型"""
    source: Optional[str] = Field(None, description="日志来源")
    environment: Optional[str] = Field(None, description="环境信息")
    service_name: Optional[str] = Field(None, description="服务名称")
    version: Optional[str] = Field(None, description="版本号")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    version_info: Optional[Dict[str, Any]] = Field(None, description="版本信息")
    extra_fields: Dict[str, Any] = Field(default_factory=dict, description="额外字段")


class LogFileInfo(BaseModel):
    """日志文件信息"""
    id: str = Field(..., description="日志文件ID")
    filename: str = Field(..., description="文件名")
    original_filename: str = Field(..., description="原始文件名")
    file_size: int = Field(..., description="文件大小（字节）")
    file_path: str = Field(..., description="文件存储路径")
    log_type: LogType = Field(LogType.STACK, description="日志类型")
    status: LogStatus = Field(LogStatus.PENDING, description="处理状态")
    progress: float = Field(0.0, ge=0.0, le=100.0, description="处理进度（0-100）")
    task_id: Optional[str] = Field(None, description="Celery任务ID")
    retry_count: int = Field(0, description="重试次数")
    processing_started_at: Optional[datetime] = Field(None, description="处理开始时间")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")
    processed_at: Optional[datetime] = Field(None, description="处理完成时间")
    checksum: Optional[str] = Field(None, description="文件校验和")
    mime_type: Optional[str] = Field(None, description="MIME类型")
    log_level: Optional[LogLevel] = Field(LogLevel.INFO, description="日志级别")
    metadata: Optional[LogMetadata] = Field(default_factory=LogMetadata, description="元数据")
    error_message: Optional[str] = Field(None, description="错误信息")
    issue_description: Optional[str] = Field(None, description="问题描述")
    download_count: int = Field(0, description="下载次数")
    ai_analysis_result: Optional[Dict[str, Any]] = Field(
        None,
        description="最近一次AI分析结果（完整数据结构）"
    )
    ai_analysis_task_id: Optional[str] = Field(
        None,
        description="AI分析任务ID"
    )
    ai_analysis_status: Optional[str] = Field(
        None,
        description="AI分析任务状态"
    )
    ai_analysis_progress: Optional[float] = Field(
        None,
        description="AI分析进度（0-100）"
    )
    ai_analysis_error: Optional[str] = Field(
        None,
        description="AI分析错误信息"
    )
    ai_analysis_query: Optional[str] = Field(
        None,
        description="本次AI分析的查询内容"
    )
    ai_analysis_started_at: Optional[datetime] = Field(
        None,
        description="AI分析开始时间"
    )
    ai_analysis_finished_at: Optional[datetime] = Field(
        None,
        description="AI分析结束时间"
    )
    
    @computed_field
    @property
    def download_url(self) -> str:
        """生成下载URL"""
        return f"/api/v1/logs/{self.id}/download"
    
    @computed_field
    @property
    def file_size_human(self) -> str:
        """人类可读的文件大小格式"""
        from app.utils.file_utils import format_file_size
        return format_file_size(self.file_size)
    
    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class LogUploadRequest(BaseModel):
    """日志上传请求"""
    log_type: LogType = Field(LogType.STACK, description="日志类型")
    log_level: Optional[LogLevel] = Field(LogLevel.INFO, description="日志级别")
    metadata: Optional[LogMetadata] = Field(default_factory=LogMetadata, description="元数据")
    expires_in_days: Optional[int] = Field(None, ge=1, le=365, description="过期天数")
    issue_description: Optional[str] = Field(None, description="问题描述")


class SortField(str, Enum):
    """排序字段枚举"""
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    FILE_SIZE = "file_size"
    FILENAME = "filename"


class SortOrder(str, Enum):
    """排序顺序枚举"""
    ASC = "asc"
    DESC = "desc"


class LogListRequest(BaseModel):
    """日志列表查询请求模型"""
    page: int = Field(1, ge=1, description="页码")
    per_page: int = Field(20, ge=1, le=100, description="每页大小")
    log_type: Optional[LogType] = Field(None, description="日志类型过滤")
    log_level: Optional[LogLevel] = Field(None, description="日志级别过滤")
    status: Optional[LogStatus] = Field(None, description="状态过滤")
    start_time: Optional[datetime] = Field(None, description="开始时间")
    end_time: Optional[datetime] = Field(None, description="结束时间")
    search: Optional[str] = Field(None, max_length=100, description="搜索关键词（按文件名搜索）")
    sort_by: SortField = Field(SortField.CREATED_AT, description="排序字段")
    sort_order: SortOrder = Field(SortOrder.DESC, description="排序顺序")
    tags: Optional[List[str]] = Field(None, description="标签过滤")
    
    @validator('end_time')
    def validate_time_range(cls, v, values):
        if v and 'start_time' in values and values['start_time'] and v <= values['start_time']:
            raise ValueError('结束时间必须大于开始时间')
        return v


class BatchDeleteRequest(BaseModel):
    """批量删除请求"""
    log_ids: List[str] = Field(..., min_items=1, max_items=100, description="日志ID列表")
    force: bool = Field(False, description="是否强制删除")
    
    @validator('log_ids')
    def validate_log_ids(cls, v):
        if len(v) == 0:
            raise ValueError('至少需要提供一个日志ID')
        if len(set(v)) != len(v):
            raise ValueError('日志ID列表中不能有重复项')
        return v


class BatchDownloadRequest(BaseModel):
    """批量下载请求"""
    log_ids: List[str] = Field(..., min_items=1, max_items=50, description="日志ID列表")
    compress: bool = Field(True, description="是否压缩下载")
    include_metadata: bool = Field(False, description="是否包含元数据文件")
    
    @validator('log_ids')
    def validate_log_ids(cls, v):
        if len(v) == 0:
            raise ValueError('至少需要提供一个日志ID')
        if len(set(v)) != len(v):
            raise ValueError('日志ID列表中不能有重复项')
        return v


# 响应模型
class LogUploadResponse(BaseResponse):
    """日志上传响应"""
    data: LogFileInfo


class LogDetailResponse(BaseResponse):
    """日志详情响应"""
    data: LogFileInfo


class PaginationInfo(BaseModel):
    """分页信息模型"""
    page: int = Field(..., description="当前页码")
    per_page: int = Field(..., description="每页大小")
    total: int = Field(..., description="总记录数")
    pages: int = Field(..., description="总页数")


class LogListData(BaseModel):
    """日志列表数据模型"""
    logs: List[LogFileInfo] = Field(..., description="日志列表")
    pagination: PaginationInfo = Field(..., description="分页信息")


class LogListResponse(BaseResponse):
    """日志列表响应模型"""
    data: LogListData


class BatchOperationResult(BaseModel):
    """批量操作结果"""
    deleted_count: int = Field(0, description="删除成功数量")
    failed_count: int = Field(0, description="失败数量")
    failed_logs: List[Dict[str, str]] = Field(default_factory=list, description="失败的日志详情")
    
    # 保持向后兼容性
    success_count: int = Field(0, description="成功数量")
    success_ids: List[str] = Field(default_factory=list, description="成功的ID列表")
    failed_ids: List[str] = Field(default_factory=list, description="失败的ID列表")
    errors: Dict[str, str] = Field(default_factory=dict, description="错误详情")


class BatchDeleteResponse(BaseResponse):
    """批量删除响应"""
    data: BatchOperationResult


class DownloadInfo(BaseModel):
    """下载信息模型"""
    download_url: str = Field(..., description="下载链接")
    filename: str = Field(..., description="文件名")
    file_size: int = Field(..., description="文件大小")
    expires_at: datetime = Field(..., description="链接过期时间")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class BatchDownloadResponse(BaseResponse):
    """批量下载响应"""
    data: DownloadInfo


class LogDeleteResponse(BaseResponse):
    """日志删除响应"""
    data: dict = Field(default_factory=lambda: {"deleted": True})
