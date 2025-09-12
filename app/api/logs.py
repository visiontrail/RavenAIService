"""
日志管理API路由
实现所有日志相关的API端点
"""

import logging
from typing import List
from fastapi import APIRouter, UploadFile, File, Form, Depends, Query, Path
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer

from app.models.log import (
    LogUploadRequest, LogUploadResponse, LogListRequest, LogListResponse,
    LogDetailResponse, LogDeleteResponse, BatchDeleteRequest, BatchDeleteResponse,
    BatchDownloadRequest, BatchDownloadResponse, LogType, LogLevel, LogStatus,
    LogMetadata
)
from app.services.log_service import log_service
from app.utils.validation import request_validator
from app.exceptions import ValidationError

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBearer(auto_error=False)


@router.post("/upload", response_model=LogUploadResponse, status_code=201)
async def upload_log(
    file: UploadFile = File(..., description="要上传的日志文件"),
    log_type: LogType = Form(LogType.APPLICATION, description="日志类型"),
    log_level: LogLevel = Form(LogLevel.INFO, description="日志级别"),
    source: str = Form(None, description="日志来源"),
    environment: str = Form(None, description="环境信息"),
    service_name: str = Form(None, description="服务名称"),
    version: str = Form(None, description="版本号"),
    expires_in_days: int = Form(None, ge=1, le=365, description="过期天数")
):
    """
    上传日志文件
    
    - **file**: 要上传的日志文件
    - **log_type**: 日志类型 (application, access, error, system, audit)
    - **log_level**: 日志级别 (debug, info, warn, error, fatal)
    - **source**: 日志来源系统
    - **environment**: 运行环境 (dev, test, prod等)
    - **service_name**: 服务名称
    - **version**: 版本号
    - **expires_in_days**: 文件过期天数 (1-365天)
    """
    
    # 构建元数据
    metadata = LogMetadata(
        source=source,
        environment=environment,
        service_name=service_name,
        version=version
    )
    
    # 构建上传请求
    upload_request = LogUploadRequest(
        log_type=log_type,
        log_level=log_level,
        metadata=metadata,
        expires_in_days=expires_in_days
    )
    
    # 执行上传
    log_info = await log_service.upload_log(file, upload_request)
    
    logger.info(f"Log uploaded successfully: {log_info.id}")
    
    return LogUploadResponse(
        message="日志上传成功",
        data=log_info
    )


@router.get("", response_model=LogListResponse)
async def get_logs(
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(10, ge=1, le=100, description="每页大小"),
    log_type: LogType = Query(None, description="日志类型过滤"),
    log_level: LogLevel = Query(None, description="日志级别过滤"),
    status: LogStatus = Query(None, description="状态过滤"),
    start_time: str = Query(None, description="开始时间 (ISO格式)"),
    end_time: str = Query(None, description="结束时间 (ISO格式)"),
    search: str = Query(None, max_length=100, description="搜索关键词"),
    tags: List[str] = Query(None, description="标签过滤")
):
    """
    获取日志列表
    
    支持多种过滤条件：
    - **page**: 页码 (从1开始)
    - **size**: 每页大小 (1-100)
    - **log_type**: 按日志类型过滤
    - **log_level**: 按日志级别过滤
    - **status**: 按状态过滤
    - **start_time**: 开始时间过滤 (ISO格式: 2024-01-01T00:00:00Z)
    - **end_time**: 结束时间过滤
    - **search**: 关键词搜索 (搜索文件名、来源、服务名)
    - **tags**: 标签过滤 (可多选)
    """
    
    # 验证搜索关键词
    if search:
        request_validator.validate_search_keyword(search)
    
    # 构建查询请求
    from datetime import datetime
    list_request = LogListRequest(
        page=page,
        size=size,
        log_type=log_type,
        log_level=log_level,
        status=status,
        start_time=datetime.fromisoformat(start_time.replace('Z', '+00:00')) if start_time else None,
        end_time=datetime.fromisoformat(end_time.replace('Z', '+00:00')) if end_time else None,
        search=search,
        tags=tags
    )
    
    # 获取日志列表
    logs, total = await log_service.get_log_list(list_request)
    
    return LogListResponse(
        message="获取日志列表成功",
        data=logs,
        total=total,
        page=page,
        size=size
    )


@router.get("/{log_id}", response_model=LogDetailResponse)
async def get_log_detail(
    log_id: str = Path(..., description="日志文件ID")
):
    """
    获取日志详情
    
    - **log_id**: 日志文件的唯一标识符
    """
    
    # 验证日志ID
    request_validator.validate_log_id(log_id)
    
    # 获取日志详情
    log_info = await log_service.get_log_detail(log_id)
    
    return LogDetailResponse(
        message="获取日志详情成功",
        data=log_info
    )


@router.delete("/{log_id}", response_model=LogDeleteResponse)
async def delete_log(
    log_id: str = Path(..., description="日志文件ID")
):
    """
    删除日志文件
    
    - **log_id**: 要删除的日志文件ID
    """
    
    # 验证日志ID
    request_validator.validate_log_id(log_id)
    
    # 删除日志
    success = await log_service.delete_log(log_id)
    
    logger.info(f"Log deleted successfully: {log_id}")
    
    return LogDeleteResponse(
        message="日志删除成功"
    )


@router.get("/{log_id}/download")
async def download_log(
    log_id: str = Path(..., description="日志文件ID")
):
    """
    下载日志文件
    
    - **log_id**: 要下载的日志文件ID
    
    返回文件流供下载
    """
    
    # 验证日志ID
    request_validator.validate_log_id(log_id)
    
    # 获取文件路径
    file_path = await log_service.get_download_path(log_id)
    
    # 获取日志信息用于设置文件名
    log_info = await log_service.get_log_detail(log_id)
    
    logger.info(f"Log download started: {log_id}")
    
    return FileResponse(
        path=file_path,
        filename=log_info.original_filename,
        media_type='application/octet-stream'
    )


@router.post("/batch/delete", response_model=BatchDeleteResponse)
async def batch_delete_logs(
    request: BatchDeleteRequest
):
    """
    批量删除日志文件
    
    - **log_ids**: 要删除的日志ID列表 (最多100个)
    - **force**: 是否强制删除 (默认false)
    """
    
    # 验证日志ID列表
    request_validator.validate_log_ids(request.log_ids)
    
    # 执行批量删除
    result = await log_service.batch_delete(request)
    
    logger.info(
        f"Batch delete completed: {result.success_count} success, {result.failed_count} failed"
    )
    
    return BatchDeleteResponse(
        message=f"批量删除完成: 成功 {result.success_count} 个，失败 {result.failed_count} 个",
        data=result
    )


@router.post("/batch/download", response_model=BatchDownloadResponse)
async def batch_download_logs(
    request: BatchDownloadRequest
):
    """
    批量下载日志文件
    
    - **log_ids**: 要下载的日志ID列表 (最多50个)
    - **compress**: 是否压缩下载 (默认true)
    - **include_metadata**: 是否包含元数据文件 (默认false)
    
    返回压缩包下载链接
    """
    
    # 验证日志ID列表
    if len(request.log_ids) > 50:
        raise ValidationError("批量下载的文件数量不能超过50个")
    
    request_validator.validate_log_ids(request.log_ids)
    
    # 执行批量下载
    zip_path = await log_service.batch_download(request)
    
    # 生成下载信息
    import os
    from datetime import datetime, timedelta
    
    file_size = os.path.getsize(zip_path)
    filename = os.path.basename(zip_path)
    expires_at = datetime.now() + timedelta(hours=1)  # 下载链接1小时后过期
    
    download_info = {
        "download_url": f"/api/v1/logs/download-batch/{filename}",
        "filename": filename,
        "file_size": file_size,
        "expires_at": expires_at
    }
    
    logger.info(f"Batch download prepared: {len(request.log_ids)} files, {file_size} bytes")
    
    return BatchDownloadResponse(
        message="批量下载准备完成",
        data=download_info
    )


@router.get("/download-batch/{filename}")
async def download_batch_file(
    filename: str = Path(..., description="批量下载文件名")
):
    """
    下载批量打包的文件
    
    - **filename**: 批量打包的文件名
    """
    
    # 构建文件路径
    file_path = log_service.downloads_storage_path / filename
    
    if not file_path.exists():
        raise FileNotFoundError(filename=filename)
    
    logger.info(f"Batch download started: {filename}")
    
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type='application/zip'
    )
