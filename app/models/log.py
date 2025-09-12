"""
日志相关数据模型
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from enum import Enum

from .base import BaseResponse, PaginatedResponse


class LogStatus(str, Enum):
    """日志状态枚举"""
    UPLOADING = "uploading"
    STORED = "stored"
    PROCESSING = "processing"
    DELETED = "deleted"


class LogLevel(str, Enum):
    """日志级别枚举"""
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    FATAL = "fatal"


class LogType(str, Enum):
    """日志类型枚举"""
    APPLICATION = "application"
    ACCESS = "access"
    ERROR = "error"
    SYSTEM = "system"
    AUDIT = "audit"


class LogMetadata(BaseModel):
    """日志元数据"""
    source: Optional[str] = Field(None, description="日志来源")
    environment: Optional[str] = Field(None, description="环境信息")
    service_name: Optional[str] = Field(None, description="服务名称")
    version: Optional[str] = Field(None, description="版本号")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    extra_fields: Dict[str, Any] = Field(default_factory=dict, description="额外字段")


class LogFileInfo(BaseModel):
    """日志文件信息"""
    id: str = Field(..., description="日志文件ID")
    filename: str = Field(..., description="文件名")
    original_filename: str = Field(..., description="原始文件名")
    file_size: int = Field(..., description="文件大小（字节）")
    file_type: str = Field(..., description="文件类型")
    mime_type: str = Field(..., description="MIME类型")
    file_path: str = Field(..., description="文件存储路径")
    checksum: str = Field(..., description="文件校验和")
    status: LogStatus = Field(LogStatus.STORED, description="文件状态")
    log_type: LogType = Field(LogType.APPLICATION, description="日志类型")
    log_level: LogLevel = Field(LogLevel.INFO, description="日志级别")
    metadata: LogMetadata = Field(default_factory=LogMetadata, description="元数据")
    upload_time: datetime = Field(default_factory=datetime.now, description="上传时间")
    last_modified: datetime = Field(default_factory=datetime.now, description="最后修改时间")
    expires_at: Optional[datetime] = Field(None, description="过期时间")
    
    class Config:
        from_attributes = True


class LogUploadRequest(BaseModel):
    """日志上传请求"""
    log_type: LogType = Field(LogType.APPLICATION, description="日志类型")
    log_level: LogLevel = Field(LogLevel.INFO, description="日志级别")
    metadata: Optional[LogMetadata] = Field(default_factory=LogMetadata, description="元数据")
    expires_in_days: Optional[int] = Field(None, ge=1, le=365, description="过期天数")
    
    @validator('expires_in_days')
    def validate_expires_in_days(cls, v):
        if v is not None and (v < 1 or v > 365):
            raise ValueError('过期天数必须在1-365之间')
        return v


class LogListRequest(BaseModel):
    """日志列表查询请求"""
    page: int = Field(1, ge=1, description="页码")
    size: int = Field(10, ge=1, le=100, description="每页大小")
    log_type: Optional[LogType] = Field(None, description="日志类型过滤")
    log_level: Optional[LogLevel] = Field(None, description="日志级别过滤")
    status: Optional[LogStatus] = Field(None, description="状态过滤")
    start_time: Optional[datetime] = Field(None, description="开始时间")
    end_time: Optional[datetime] = Field(None, description="结束时间")
    search: Optional[str] = Field(None, max_length=100, description="搜索关键词")
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


class LogListResponse(PaginatedResponse):
    """日志列表响应"""
    data: List[LogFileInfo]


class BatchOperationResult(BaseModel):
    """批量操作结果"""
    success_count: int = Field(0, description="成功数量")
    failed_count: int = Field(0, description="失败数量")
    success_ids: List[str] = Field(default_factory=list, description="成功的ID列表")
    failed_ids: List[str] = Field(default_factory=list, description="失败的ID列表")
    errors: Dict[str, str] = Field(default_factory=dict, description="错误详情")


class BatchDeleteResponse(BaseResponse):
    """批量删除响应"""
    data: BatchOperationResult


class DownloadInfo(BaseModel):
    """下载信息"""
    download_url: str = Field(..., description="下载链接")
    filename: str = Field(..., description="文件名")
    file_size: int = Field(..., description="文件大小")
    expires_at: datetime = Field(..., description="链接过期时间")


class BatchDownloadResponse(BaseResponse):
    """批量下载响应"""
    data: DownloadInfo


class LogDeleteResponse(BaseResponse):
    """日志删除响应"""
    data: dict = Field(default_factory=lambda: {"deleted": True})
