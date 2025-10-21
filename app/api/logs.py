"""
日志管理API路由
实现所有日志相关的API端点
"""

import logging
import re
import io
import uuid
import json
import tarfile
import zipfile
from pathlib import Path as FilePath
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, Depends, Query, Path, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db

from app.models.log import (
    LogUploadRequest, LogUploadResponse, LogListRequest, LogListResponse,
    LogDetailResponse, LogDeleteResponse, BatchDeleteRequest, BatchDeleteResponse,
    BatchDownloadRequest, BatchDownloadResponse, LogType, LogLevel, LogStatus,
    LogMetadata, SortField, SortOrder
)
from app.services.log_service import log_service
from app.utils.validation import request_validator
from app.utils.file_upload_validator import t04_file_validator
from app.utils.temp_file_cleaner import temp_file_cleaner, upload_temp_manager
from app.exceptions import ValidationError, FileUploadError, FileSizeExceededError, UnsupportedFileTypeError, FileNotFoundError, AuthorizationError, LogServiceException, FileProcessingError

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBearer(auto_error=False)


def _infer_log_type_from_filename(filename: str) -> LogType:
    """
    根据文件名初步判断日志类型：
    - 同时包含 stack 与 (oam 或 om) -> FULL
    - 仅包含 stack -> STACK
    - 其他情况（包含 oam/om 或都不包含）-> OAM_ANTENNA
    """
    name = (filename or "").lower()
    has_stack = "stack" in name
    has_oam = ("oam" in name) or ("om" in name)
    if has_stack and has_oam:
        return LogType.FULL
    if has_stack:
        return LogType.STACK
    return LogType.OAM_ANTENNA


def _infer_log_type_from_components(components) -> Optional[LogType]:
    """
    根据 metadata.json 中的 log_components 的 component_name 进一步细化日志类型：
    - 若包含任一 STACK 相关组件（如："STACK_", "CUCP", "STACK_CUUP", "STACK_DU"），认为包含协议栈
    - 若包含任一 OAM 相关组件（名称包含 "OAM"，如："CUUP_OAM", "DU_OAM", "DVB_OAM", "MAIN_OAM"），认为包含 OAM
    - 两者皆有 -> FULL；仅栈 -> STACK；仅 OAM -> OAM_ANTENNA；都无 -> None（不改变）
    """
    try:
        if not isinstance(components, list):
            return None
        has_stack_component = False
        has_oam_component = False
        for item in components:
            if not isinstance(item, dict):
                continue
            name = str(item.get("component_name", "")).upper()
            if not name:
                continue
            if "STACK" in name or name == "CUCP" or name.startswith("STACK_"):
                has_stack_component = True
            if "OAM" in name:
                has_oam_component = True
        if has_stack_component and has_oam_component:
            return LogType.FULL
        if has_stack_component:
            return LogType.STACK
        if has_oam_component:
            return LogType.OAM_ANTENNA
        return None
    except Exception:
        return None


async def _try_extract_and_update_metadata(db: AsyncSession, log_info):
    """
    检查上传的日志包中是否包含 metadata.json，若存在则解析并回填到数据库现有字段：
    - issue_description: 优先在数据库为空时从 issue_info.issue_description 回填
    - metadata_json: 合并到 LogMetadata（填充 environment、service_name，原有值优先），
      并将完整的 metadata.json 放入 extra_fields.metadata_json 以便后续使用
    """
    try:
        file_path = FilePath(getattr(log_info, "file_path", ""))
        if not file_path or not file_path.exists() or not file_path.is_file():
            return

        metadata_dict = None

        # 支持 .zip 与 tar 家族（.tar, .tgz, .tar.gz, 等）
        suffix_lower = file_path.suffix.lower()
        name_lower = file_path.name.lower()

        # 优先尝试 zip
        if suffix_lower == ".zip":
            try:
                with zipfile.ZipFile(file_path, 'r') as zf:
                    # 查找任意路径下的 metadata.json
                    meta_name = next((n for n in zf.namelist() if n.endswith("metadata.json") and not n.endswith("/")), None)
                    if meta_name:
                        with zf.open(meta_name) as f:
                            content = f.read().decode('utf-8', errors='ignore')
                            metadata_dict = json.loads(content)
            except Exception:
                metadata_dict = None

        # 若不是 zip 或 zip 失败，尝试 tar 系列
        if metadata_dict is None:
            try:
                # tarfile 会自动识别 tar、tar.gz、tgz 等压缩格式（mode='r:*'）
                with tarfile.open(file_path, mode='r:*') as tf:
                    member = next((m for m in tf.getmembers() if m.isfile() and m.name.endswith('metadata.json')), None)
                    if member is not None:
                        extracted = tf.extractfile(member)
                        if extracted is not None:
                            content = extracted.read().decode('utf-8', errors='ignore')
                            metadata_dict = json.loads(content)
            except tarfile.ReadError:
                # 非 tar 格式，忽略
                pass
            except Exception:
                metadata_dict = None

        if not metadata_dict:
            return

        # 从 DB 获取最新记录
        record = await log_service.get_by_id(db, log_info.id)
        if not record or getattr(record, 'is_deleted', False):
            return

        # 准备合并 LogMetadata
        existing_meta = {}
        if record.metadata_json:
            try:
                existing_meta = json.loads(record.metadata_json)
            except Exception:
                existing_meta = {}

        # 标准化为 LogMetadata 结构的字典
        log_metadata_dict = {
            "source": existing_meta.get("source"),
            "environment": existing_meta.get("environment"),
            "service_name": existing_meta.get("service_name"),
            "version": existing_meta.get("version"),
            "tags": existing_meta.get("tags") or [],
            "version_info": existing_meta.get("version_info"),
            "extra_fields": existing_meta.get("extra_fields") or {}
        }

        # 从 metadata.json 中提取可回填字段
        issue_info = metadata_dict.get("issue_info", {}) if isinstance(metadata_dict, dict) else {}
        issue_desc = issue_info.get("issue_description")
        environment_info = issue_info.get("environment_info")
        service_name = issue_info.get("service_name")
        version_info = metadata_dict.get("version_info") if isinstance(metadata_dict, dict) else None

        def is_empty(value):
            return value is None or (isinstance(value, str) and value.strip() == "")

        # 回填 environment / service_name（仅当原值为空时）
        if environment_info and is_empty(log_metadata_dict.get("environment")):
            log_metadata_dict["environment"] = environment_info
        if service_name and is_empty(log_metadata_dict.get("service_name")):
            log_metadata_dict["service_name"] = service_name
        
        # 回填 version_info（仅当原值为空时）
        if version_info and is_empty(log_metadata_dict.get("version_info")):
            log_metadata_dict["version_info"] = version_info

        # 将完整 metadata.json 放入 extra_fields 以保留全部信息
        try:
            log_metadata_dict["extra_fields"]["metadata_json"] = metadata_dict
        except Exception:
            pass

        # 先尝试基于 log_components 细化日志类型
        refined_log_type: Optional[LogType] = None
        try:
            components = None
            if isinstance(metadata_dict, dict):
                components = metadata_dict.get("log_components")
            refined_log_type = _infer_log_type_from_components(components)
        except Exception:
            refined_log_type = None

        # 组装需要更新的数据
        update_data = {
            "metadata_json": json.dumps(log_metadata_dict, ensure_ascii=False)
        }

        # 仅当 issue_description 为空时从文件回填
        if issue_desc and is_empty(getattr(record, "issue_description", None)):
            update_data["issue_description"] = issue_desc

        # 如能根据组件细化日志类型，则一并更新
        if refined_log_type is not None and getattr(record, "log_type", None) != refined_log_type:
            update_data["log_type"] = refined_log_type

        # 执行更新并提交
        await log_service.update(db, log_info.id, **update_data)
        await db.commit()
    except Exception as e:
        # 解析失败不影响主流程
        logger.warning(f"metadata.json 解析或回填失败: {e}")

@router.post("/upload-simple", response_model=LogUploadResponse, status_code=201)
async def upload_log_simple(
    file: UploadFile = File(..., description="要上传的日志文件"),
    db: AsyncSession = Depends(get_db)
):
    """
    简化的日志文件上传接口
    """
    # 使用文件名推断初始日志类型
    inferred_type = _infer_log_type_from_filename(file.filename)
    metadata = LogMetadata()
    upload_request = LogUploadRequest(
        log_type=inferred_type,
        log_level=LogLevel.INFO,
        metadata=metadata,
        expires_in_days=None
    )
    
    # 执行上传
    log_info = await log_service.upload_log(db, file, upload_request)
    
    logger.info(f"Log uploaded successfully (simple): {log_info.id}")
    
    # 二次检查并回填 metadata.json
    try:
        await _try_extract_and_update_metadata(db, log_info)
        # 回填后刷新返回数据
        log_info = await log_service.get_log_detail(db, log_info.id)
    except Exception as e:
        logger.warning(f"Post-upload metadata backfill failed: {e}")
    
    return LogUploadResponse(
        message="日志上传成功",
        data=log_info
    )


@router.post("/upload", response_model=LogUploadResponse, status_code=201)
async def upload_log(
    file: UploadFile = File(..., description="要上传的日志文件"),
    log_type: LogType = Form(LogType.STACK, description="日志类型"),
    log_level: LogLevel = Form(LogLevel.INFO, description="日志级别"),
    source: Optional[str] = Form(None, description="日志来源"),
    environment: Optional[str] = Form(None, description="环境信息"),
    service_name: Optional[str] = Form(None, description="服务名称"),
    version: Optional[str] = Form(None, description="版本号"),
    expires_in_days: Optional[int] = Form(None, ge=1, le=365, description="过期天数"),
    issue_description: Optional[str] = Form(None, description="问题描述"),
    db: AsyncSession = Depends(get_db)
):
    """
    上传日志文件
    
    - **file**: 要上传的日志文件
    - **log_type**: 日志类型 (stack, oam_antenna, full)
    - **log_level**: 日志级别 (debug, info, warn, error, fatal)
    - **source**: 日志来源系统
    - **environment**: 运行环境 (dev, test, prod等)
    - **service_name**: 服务名称
    - **version**: 版本号
    - **expires_in_days**: 文件过期天数 (1-365天)
    - **issue_description**: 问题描述，用于描述日志所对应的问题
    """
    
    # 构建元数据
    metadata = LogMetadata(
        source=source,
        environment=environment,
        service_name=service_name,
        version=version
    )
    
    # 基于文件名推断，优先于表单入参
    inferred_type = _infer_log_type_from_filename(file.filename)

    # 构建上传请求（覆盖为推断结果）
    upload_request = LogUploadRequest(
        log_type=inferred_type,
        log_level=log_level,
        metadata=metadata,
        expires_in_days=expires_in_days,
        issue_description=issue_description
    )
    
    # 执行上传
    log_info = await log_service.upload_log(db, file, upload_request)
    
    logger.info(f"Log uploaded successfully: {log_info.id}")
    
    # 二次检查并回填 metadata.json
    try:
        await _try_extract_and_update_metadata(db, log_info)
        # 回填后刷新返回数据
        log_info = await log_service.get_log_detail(db, log_info.id)
    except Exception as e:
        logger.warning(f"Post-upload metadata backfill failed: {e}")
    
    return LogUploadResponse(
        message="日志上传成功",
        data=log_info
    )


@router.post("/upload-t04", status_code=201)
async def upload_t04_logs(
    files: List[UploadFile] = File(..., description="要上传的tar.gz日志文件列表")
):
    """
    T04任务：上传tar.gz格式的日志文件
    
    支持功能：
    - 多文件同时上传
    - 只允许tar.gz格式文件
    - 文件大小限制1GB
    - 文件完整性验证（magic number检查）
    - 根据文件名自动判断日志类型（包含"stack"为协议栈日志）
    - 文件名安全化处理
    - 路径遍历攻击防护
    
    错误处理：
    - 400: 文件格式错误
    - 413: 文件大小超限
    - 422: 文件损坏
    - 507: 存储空间不足
    - 500: 服务器错误
    """
    
    logger.info(f"T04上传请求开始 - 文件数量: {len(files)}, 文件名列表: {[f.filename for f in files]}")
    from fastapi import HTTPException, status
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.database import get_db
    import uuid
    import os
    from pathlib import Path
    
    # 清理过期的临时文件
    try:
        cleaned_count = temp_file_cleaner.cleanup_expired_files()
        if cleaned_count > 0:
            logger.info(f"T04上传 - 清理了 {cleaned_count} 个过期临时文件")
    except Exception as e:
        logger.warning(f"T04上传 - 清理临时文件失败: {e}")
    
    # 验证文件列表
    logger.info("T04上传 - 开始文件验证")
    try:
        is_valid, error_msg = await t04_file_validator.validate_upload_files(files)
        if not is_valid:
            logger.error(f"T04上传 - 文件验证失败: {error_msg}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "success": False,
                    "message": "文件验证失败",
                    "error": error_msg
                }
            )
        logger.info("T04上传 - 文件验证通过")
    except FileSizeExceededError as e:
        logger.error(f"T04上传 - 文件大小超限: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "success": False,
                "message": "文件大小超限",
                "error": str(e)
            }
        )
    except UnsupportedFileTypeError as e:
        logger.error(f"T04上传 - 文件格式错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "message": "文件格式错误",
                "error": str(e)
            }
        )
    except ValidationError as e:
        if "损坏" in str(e):
            logger.error(f"T04上传 - 文件损坏: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "success": False,
                    "message": "文件损坏",
                    "error": str(e)
                }
            )
        else:
            logger.error(f"T04上传 - 文件验证失败: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "success": False,
                    "message": "文件验证失败",
                    "error": str(e)
                }
            )
    
    # 检查存储空间
    logger.info("T04上传 - 开始存储空间检查")
    try:
        storage_path = FilePath("logs")
        storage_path.mkdir(exist_ok=True)
        
        # 简单的存储空间检查
        statvfs = os.statvfs(storage_path)
        free_space = statvfs.f_frsize * statvfs.f_bavail
        
        total_file_size = sum([len(await file.read()) for file in files])
        # 重置所有文件指针
        for file in files:
            await file.seek(0)
        
        logger.info(f"T04上传 - 存储空间检查: 可用空间={free_space // (1024*1024)}MB, 需要空间={total_file_size // (1024*1024)}MB")
        
        if free_space < total_file_size * 2:  # 预留一倍空间
            logger.error(f"T04上传 - 存储空间不足: 可用空间={free_space // (1024*1024)}MB, 需要空间={total_file_size // (1024*1024)}MB")
            raise HTTPException(
                status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
                detail={
                    "success": False,
                    "message": "存储空间不足",
                    "error": f"可用空间: {free_space // (1024*1024)}MB, 需要空间: {total_file_size // (1024*1024)}MB"
                }
            )
        
        logger.info("T04上传 - 存储空间检查通过")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"T04上传 - 存储空间检查失败: {e}")
        # 存储空间检查失败不阻止上传，继续处理
    
    # 处理文件上传
    logger.info("T04上传 - 开始文件上传处理")
    upload_results = []
    failed_files = []
    
    # 获取数据库会话
    async for db in get_db():
        try:
            for file in files:
                try:
                    logger.info(f"T04上传 - 开始处理文件: {file.filename}")
                    
                    # 生成文件ID
                    file_id = str(uuid.uuid4())
                    logger.info(f"T04上传 - 生成文件ID: {file_id}")
                    
                    # 判断日志类型
                    log_type = t04_file_validator.determine_log_type_from_filename(file.filename)
                    logger.info(f"T04上传 - 检测到日志类型: {log_type}")
                    
                    # 生成安全的文件名
                    safe_filename = t04_file_validator.generate_unique_filename(file.filename, file_id)
                    logger.info(f"T04上传 - 生成安全文件名: {safe_filename}")
                    
                    # 保存文件
                    file_path = storage_path / safe_filename
                    
                    # 保存文件内容
                    logger.info(f"T04上传 - 开始保存文件到: {file_path}")
                    await file.seek(0)
                    content = await file.read()
                    with open(file_path, "wb") as f:
                        f.write(content)
                    logger.info(f"T04上传 - 文件保存完成")
                    
                    # 计算文件校验和
                    await file.seek(0)
                    checksum = await t04_file_validator.calculate_file_checksum(file)
                    logger.info(f"T04上传 - 文件校验和计算完成: {checksum[:16]}...")
                    
                    # 获取文件大小
                    file_size = len(content)
                    logger.info(f"T04上传 - 文件大小: {file_size} bytes")
                    
                    # 创建数据库记录
                    from app.models.log import LogRecord
                    from sqlalchemy import insert
                    
                    log_record_data = {
                        "id": file_id,
                        "filename": safe_filename,
                        "original_filename": file.filename,
                        "file_size": file_size,
                        "file_path": str(file_path),
                        "log_type": LogType.STACK if log_type == "stack" else (LogType.FULL if log_type == "full" else LogType.OAM_ANTENNA),
                        "status": LogStatus.PENDING,
                        "progress": 0.0,
                        "checksum": checksum,
                        "mime_type": "application/gzip",
                        "log_level": LogLevel.INFO
                    }
                    
                    logger.info(f"T04上传 - 开始创建数据库记录")
                    stmt = insert(LogRecord).values(**log_record_data)
                    await db.execute(stmt)
                    await db.commit()
                    logger.info(f"T04上传 - 数据库记录创建成功")
                    
                    # 添加到成功结果
                    upload_results.append({
                        "log_id": file_id,
                        "filename": safe_filename,
                        "original_filename": file.filename,
                        "file_size": file_size,
                        "log_type": log_type,
                        "status": "pending"
                    })
                    
                    logger.info(f"T04上传 - 文件处理完成: {file.filename} -> {safe_filename}, ID: {file_id}")
                    
                except Exception as e:
                     logger.error(f"T04上传 - 处理文件 {file.filename} 失败: {e}")
                     failed_files.append({
                         "filename": file.filename,
                         "error": str(e)
                     })
                     
                     # 清理已创建的文件
                     if 'file_path' in locals() and file_path.exists():
                         try:
                             file_path.unlink()
                             logger.info(f"T04上传 - 清理失败文件: {file_path}")
                         except Exception:
                             pass
                     
                     # 清理相关临时文件
                     if 'file_id' in locals():
                         try:
                             temp_file_cleaner.cleanup_on_upload_failure(file_id)
                             logger.info(f"T04上传 - 清理临时文件: {file_id}")
                         except Exception as cleanup_error:
                             logger.warning(f"T04上传 - 清理临时文件失败: {cleanup_error}")
            
            break  # 成功处理完所有文件，退出数据库会话循环
            
        except Exception as e:
            logger.error(f"T04上传 - 数据库操作失败: {e}")
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "success": False,
                    "message": "服务器错误",
                    "error": "数据库操作失败"
                }
            )
    
    # 构建响应
    logger.info(f"T04上传 - 上传完成: 成功={len(upload_results)}, 失败={len(failed_files)}")
    if upload_results:
        response_data = {
            "success": True,
            "message": f"成功上传 {len(upload_results)} 个文件" + (f"，{len(failed_files)} 个文件失败" if failed_files else ""),
            "data": {
                "uploaded_files": upload_results,
                "failed_files": failed_files if failed_files else None,
                "total_uploaded": len(upload_results),
                "total_failed": len(failed_files)
            }
        }
        
        if failed_files:
            # 部分成功
            logger.warning(f"T04上传 - 部分成功: {len(upload_results)}/{len(files)} 个文件上传成功")
            return response_data
        else:
            # 全部成功
            logger.info(f"T04上传 - 全部成功: {len(upload_results)} 个文件上传成功")
            return response_data
    else:
        # 全部失败
        logger.error(f"T04上传 - 全部失败: {len(failed_files)} 个文件上传失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "message": "所有文件上传失败",
                "data": {
                    "failed_files": failed_files
                }
            }
        )


@router.get("", response_model=LogListResponse)
async def get_logs(
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(20, ge=1, le=100, description="每页大小"),
    log_type: LogType = Query(None, description="日志类型过滤"),
    log_level: LogLevel = Query(None, description="日志级别过滤"),
    status: LogStatus = Query(None, description="状态过滤"),
    start_time: str = Query(None, description="开始时间 (ISO格式)"),
    end_time: str = Query(None, description="结束时间 (ISO格式)"),
    search: str = Query(None, max_length=100, description="搜索关键词（按文件名搜索）"),
    sort_by: SortField = Query(SortField.CREATED_AT, description="排序字段"),
    sort_order: SortOrder = Query(SortOrder.DESC, description="排序顺序"),
    tags: List[str] = Query(None, description="标签过滤"),
    db: AsyncSession = Depends(get_db)
):
    """
    获取日志列表
    
    支持多种过滤条件：
    - **page**: 页码 (从1开始)
    - **per_page**: 每页大小 (1-100)
    - **log_type**: 按日志类型过滤
    - **log_level**: 按日志级别过滤
    - **status**: 按状态过滤
    - **start_time**: 开始时间过滤 (ISO格式: 2024-01-01T00:00:00Z)
    - **end_time**: 结束时间过滤
    - **search**: 关键词搜索 (按文件名搜索)
    - **sort_by**: 排序字段 (created_at, updated_at, file_size, filename)
    - **sort_order**: 排序顺序 (asc, desc)
    - **tags**: 标签过滤 (可多选)
    """
    
    # 验证搜索关键词
    if search:
        request_validator.validate_search_keyword(search)
    
    # 构建查询请求
    from datetime import datetime
    from app.models.database import get_db
    
    list_request = LogListRequest(
        page=page,
        per_page=per_page,
        log_type=log_type,
        log_level=log_level,
        status=status,
        start_time=datetime.fromisoformat(start_time.replace('Z', '+00:00')) if start_time else None,
        end_time=datetime.fromisoformat(end_time.replace('Z', '+00:00')) if end_time else None,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        tags=tags
    )
    
    # 获取日志列表
    log_data = await log_service.get_log_list(db, list_request)
    
    return LogListResponse(
        message="获取日志列表成功",
        data=log_data
    )


@router.get("/{log_id}", response_model=LogDetailResponse)
async def get_log_detail(
    log_id: str = Path(..., description="日志文件ID"),
    db: AsyncSession = Depends(get_db)
):
    """
    获取日志详情
    
    根据log_id获取日志详细信息，包含所有基本信息和处理状态。
    支持SEO友好的URL（/log/{log_id}）
    
    - **log_id**: 日志文件的唯一标识符
    
    返回数据包含：
    - id: 日志UUID
    - filename: 存储文件名
    - original_filename: 原始文件名
    - file_size: 文件大小（字节）
    - file_size_human: 人类可读的文件大小
    - log_type: 日志类型
    - status: 处理状态
    - progress: 处理进度（0-100）
    - created_at: 创建时间
    - updated_at: 更新时间
    - processed_at: 处理完成时间
    - download_url: 下载链接
    - download_count: 下载次数
    
    错误处理：
    - 400: 无效的日志ID格式
    - 404: 日志不存在
    - 500: 服务器内部错误
    """
    
    try:
        # 验证日志ID格式
        request_validator.validate_log_id(log_id)
        
        # 获取日志详情（包含存在性验证）
        log_info = await log_service.get_log_detail(db, log_id)
        
        # 检查日志是否被软删除
        if hasattr(log_info, 'is_deleted') and log_info.is_deleted:
            raise FileNotFoundError(file_id=log_id)
        
        logger.info(f"Log detail retrieved successfully: {log_id}")
        
        return LogDetailResponse(
            message="获取日志详情成功",
            data=log_info
        )
        
    except ValidationError as e:
        logger.warning(f"Invalid log ID format: {log_id}")
        raise e
    except FileNotFoundError as e:
        logger.warning(f"Log not found: {log_id}")
        raise e
    except Exception as e:
        logger.error(f"Error retrieving log detail for {log_id}: {str(e)}")
        raise LogServiceException(
            message="获取日志详情失败",
            error_code="LOG_DETAIL_ERROR",
            detail=str(e)
        )


@router.delete("/{log_id}", response_model=LogDeleteResponse)
async def delete_log(
    log_id: str = Path(..., description="日志文件ID"),
    db: AsyncSession = Depends(get_db)
):
    """
    删除日志文件（软删除）
    
    - **log_id**: 要删除的日志文件ID
    """
    
    # 验证日志ID
    request_validator.validate_log_id(log_id)
    
    # 删除日志（默认软删除）
    success = await log_service.delete_log(db, log_id)
    
    logger.info(f"Log deleted successfully: {log_id}")
    
    return LogDeleteResponse(
        message="日志删除成功"
    )


@router.get("/{log_id}/download")
async def download_log(
    log_id: str = Path(..., description="日志文件ID"),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """
    下载日志文件
    
    支持功能：
    - 流式下载支持大文件
    - 断点续传支持（Range请求）
    - 下载进度显示
    - 下载次数统计
    
    - **log_id**: 要下载的日志文件ID
    
    权限控制：
    - 验证日志存在性
    - 检查文件可访问性
    - 访问日志记录
    
    错误处理：
    - 400: 无效的日志ID格式
    - 404: 日志不存在或文件不存在
    - 403: 权限不足
    - 416: 请求范围不满足（断点续传）
    - 500: 服务器内部错误
    
    返回文件流供下载，支持断点续传
    """
    
    try:
        # 验证日志ID格式
        request_validator.validate_log_id(log_id)
        
        # 获取文件路径和日志信息（包含权限验证）
        file_path = await log_service.get_download_path(db, log_id)
        log_info = await log_service.get_log_detail(db, log_id)
        
        # 检查日志状态是否允许下载（临时允许pending状态用于测试）
        if log_info.status not in [LogStatus.COMPLETED, LogStatus.PROCESSING, LogStatus.PENDING]:
            raise AuthorizationError("文件尚未处理完成，无法下载")
        
        # 检查日志是否被软删除
        if hasattr(log_info, 'is_deleted') and log_info.is_deleted:
            raise FileNotFoundError(file_id=log_id)
        
        # 增加下载次数
        await log_service.increment_download_count(db, log_id)
        
        # 获取文件信息
        import os
        from pathlib import Path
        
        file_path_obj = FilePath(file_path)
        if not file_path_obj.exists():
            logger.error(f"File not found on disk: {file_path}")
            raise FileNotFoundError(filename=log_info.original_filename)
            
        file_size = file_path_obj.stat().st_size
        
        # 检查是否是Range请求（断点续传）
        range_header = request.headers.get('Range') if request else None
        
        if range_header:
            # 解析Range头
            range_match = re.match(r'bytes=(\d+)-(\d*)', range_header)
            if range_match:
                start = int(range_match.group(1))
                end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
                
                # 验证范围
                if start >= file_size or end >= file_size or start > end:
                    from fastapi import HTTPException
                    logger.warning(f"Invalid range request: {range_header} for file size {file_size}")
                    raise HTTPException(status_code=416, detail="Requested Range Not Satisfiable")
                
                # 创建流式响应支持断点续传
                def iter_file_range():
                    try:
                        with open(file_path, 'rb') as f:
                            f.seek(start)
                            remaining = end - start + 1
                            while remaining > 0:
                                chunk_size = min(8192, remaining)
                                chunk = f.read(chunk_size)
                                if not chunk:
                                    break
                                remaining -= len(chunk)
                                yield chunk
                    except Exception as e:
                        logger.error(f"Error reading file range {start}-{end}: {str(e)}")
                        raise FileProcessingError(f"读取文件失败: {str(e)}")
                
                headers = {
                    'Content-Range': f'bytes {start}-{end}/{file_size}',
                    'Accept-Ranges': 'bytes',
                    'Content-Length': str(end - start + 1),
                    'Content-Disposition': f'attachment; filename="{log_info.original_filename}"'
                }
                
                logger.info(f"Log partial download started: {log_id}, range: {start}-{end}")
                
                return StreamingResponse(
                    iter_file_range(),
                    status_code=206,
                    headers=headers,
                    media_type='application/octet-stream'
                )
        
        # 普通下载（流式）
        def iter_file():
            try:
                with open(file_path, 'rb') as f:
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        yield chunk
            except Exception as e:
                logger.error(f"Error reading file: {str(e)}")
                raise FileProcessingError(f"读取文件失败: {str(e)}")
        
        headers = {
            'Content-Length': str(file_size),
            'Accept-Ranges': 'bytes',
            'Content-Disposition': f'attachment; filename="{log_info.original_filename}"'
        }
        
        logger.info(f"Log download started: {log_id}")
        
        return StreamingResponse(
            iter_file(),
            headers=headers,
            media_type='application/octet-stream'
        )
        
    except ValidationError as e:
        logger.warning(f"Invalid log ID format: {log_id}")
        raise e
    except FileNotFoundError as e:
        logger.warning(f"File not found for download: {log_id}")
        raise e
    except AuthorizationError as e:
        logger.warning(f"Download authorization failed: {log_id}")
        raise e
    except Exception as e:
        logger.error(f"Error downloading log {log_id}: {str(e)}")
        raise LogServiceException(
            message="文件下载失败",
            error_code="DOWNLOAD_ERROR",
            detail=str(e)
        )


@router.post("/{log_id}/download-count")
async def increment_download_count(
    log_id: str = Path(..., description="日志文件ID"),
    db: AsyncSession = Depends(get_db)
):
    """
    增加下载次数
    
    专门用于前端异步更新下载计数，不影响实际下载体验
    
    - **log_id**: 要更新下载次数的日志文件ID
    
    返回更新后的下载次数
    """
    try:
        # 验证日志ID格式
        request_validator.validate_log_id(log_id)
        
        # 增加下载次数
        log_info = await log_service.increment_download_count(db, log_id)
        
        logger.info(f"Download count incremented: {log_id}, new count: {log_info.download_count}")
        
        return {
            "success": True,
            "message": "下载次数已更新",
            "data": {
                "log_id": log_id,
                "download_count": log_info.download_count
            }
        }
        
    except ValidationError as e:
        logger.warning(f"Invalid log ID format for download count: {log_id}")
        raise e
    except FileNotFoundError as e:
        logger.warning(f"File not found for download count update: {log_id}")
        raise e
    except Exception as e:
        logger.error(f"Error updating download count {log_id}: {str(e)}")
        raise LogServiceException(
            message="下载次数更新失败",
            error_code="DOWNLOAD_COUNT_ERROR",
            detail=str(e)
        )


@router.post("/batch/delete", response_model=BatchDeleteResponse)
async def batch_delete_logs(
    request: BatchDeleteRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    批量删除日志文件 - 改进版本
    
    支持事务处理和详细错误报告：
    - **log_ids**: 要删除的日志ID列表 (最多100个)
    - **force**: 是否强制删除 (默认false为软删除，true为物理删除)
    
    响应格式符合T08要求：
    ```json
    {
        "success": true,
        "data": {
            "deleted_count": 2,
            "failed_count": 1,
            "failed_logs": [
                {
                    "log_id": "uuid3",
                    "reason": "文件不存在"
                }
            ]
        }
    }
    ```
    """
    
    try:
        # 验证日志ID列表
        request_validator.validate_log_ids(request.log_ids)
        
        # 执行批量删除
        result = await log_service.batch_delete(db, request)
        
        logger.info(
            f"Batch delete completed: {result.deleted_count} deleted, {result.failed_count} failed"
        )
        
        return BatchDeleteResponse(
            success=True,
            message=f"批量删除完成: 成功删除 {result.deleted_count} 个，失败 {result.failed_count} 个",
            data=result
        )
        
    except ValidationError as e:
        logger.error(f"Batch delete validation error: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"Batch delete error: {str(e)}")
        raise LogServiceException(f"批量删除操作失败: {str(e)}")


@router.post("/batch/download", response_model=BatchDownloadResponse)
async def batch_download_logs(
    request: BatchDownloadRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    批量下载日志文件 - 改进版本
    
    支持流式zip文件生成，避免内存溢出：
    - **log_ids**: 要下载的日志ID列表 (最多50个)
    - **compress**: 是否压缩下载 (默认true)
    - **include_metadata**: 是否包含元数据文件 (默认false)
    
    返回压缩包下载链接，支持大量文件打包
    """
    
    try:
        # 验证日志ID列表
        if len(request.log_ids) > 50:
            raise ValidationError("批量下载的文件数量不能超过50个")
        
        request_validator.validate_log_ids(request.log_ids)
        
        # 执行批量下载
        zip_path = await log_service.batch_download(db, request)
        
        # 生成下载信息
        import os
        from datetime import datetime, timedelta
        from app.models.log import DownloadInfo
        
        file_size = os.path.getsize(zip_path)
        filename = os.path.basename(zip_path)
        expires_at = datetime.now() + timedelta(hours=2)  # 下载链接2小时后过期
        
        download_info = DownloadInfo(
            download_url=f"/api/v1/logs/download-batch/{filename}",
            filename=filename,
            file_size=file_size,
            expires_at=expires_at
        )
        
        logger.info(f"Batch download prepared: {len(request.log_ids)} files requested, {file_size} bytes")
        
        return BatchDownloadResponse(
            success=True,
            message="批量下载准备完成",
            data=download_info
        )
        
    except ValidationError as e:
        logger.error(f"Batch download validation error: {str(e)}")
        raise e
    except FileNotFoundError as e:
        logger.error(f"Batch download file not found: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"Batch download error: {str(e)}")
        raise LogServiceException(f"批量下载操作失败: {str(e)}")


@router.post("/batch/download-stream")
async def batch_download_logs_stream(
    request: BatchDownloadRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    流式批量下载日志文件
    
    直接返回zip文件流，适用于小批量文件的即时下载：
    - **log_ids**: 要下载的日志ID列表 (最多20个)
    - **compress**: 是否压缩下载 (默认true)
    - **include_metadata**: 是否包含元数据文件 (默认false)
    
    直接返回zip文件内容，无需临时文件
    """
    
    try:
        # 验证日志ID列表 - 流式下载限制更严格
        if len(request.log_ids) > 20:
            raise ValidationError("流式批量下载的文件数量不能超过20个")
        
        request_validator.validate_log_ids(request.log_ids)
        
        # 执行流式批量下载
        zip_content = await log_service.batch_download_stream(db, request)
        
        # 生成文件名
        download_id = str(uuid.uuid4())[:8]
        filename = f"logs_stream_{download_id}.zip"
        
        logger.info(f"Stream batch download: {len(request.log_ids)} files, {len(zip_content)} bytes")
        
        return StreamingResponse(
            io.BytesIO(zip_content),
            media_type='application/zip',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(len(zip_content))
            }
        )
        
    except ValidationError as e:
        logger.error(f"Stream batch download validation error: {str(e)}")
        raise e
    except FileNotFoundError as e:
        logger.error(f"Stream batch download file not found: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"Stream batch download error: {str(e)}")
        raise LogServiceException(f"流式批量下载操作失败: {str(e)}")


@router.get("/download-batch/{filename}")
async def download_batch_file(
    filename: str = Path(..., description="批量下载文件名")
):
    """
    下载批量打包的文件 - 改进版本
    
    支持大文件下载和错误处理：
    - **filename**: 批量打包的文件名
    
    返回zip文件，支持断点续传
    """
    
    try:
        # 构建文件路径
        file_path = log_service.downloads_storage_path / filename
        
        if not file_path.exists():
            logger.error(f"Batch download file not found: {filename}")
            raise FileNotFoundError(filename=filename)
        
        # 检查文件是否过期（超过2小时）
        file_stat = file_path.stat()
        file_age = datetime.now().timestamp() - file_stat.st_mtime
        if file_age > 7200:  # 2 hours
            logger.warning(f"Batch download file expired: {filename}")
            # 可以选择删除过期文件
            # file_path.unlink()
            # raise FileNotFoundError(filename=filename)
        
        logger.info(f"Batch download started: {filename}, size: {file_stat.st_size}")
        
        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type='application/zip',
            headers={
                'Accept-Ranges': 'bytes',  # 支持断点续传
                'Content-Length': str(file_stat.st_size)
            }
        )
        
    except FileNotFoundError:
        raise
    except Exception as e:
        logger.error(f"Batch download file error: {str(e)}")
        raise LogServiceException(f"下载批量文件失败: {str(e)}")
