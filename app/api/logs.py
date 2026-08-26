"""
日志管理API路由
实现所有日志相关的API端点
"""

import logging
import re
import io
import time
import uuid
import json
import tarfile
import zipfile
from pathlib import Path as FilePath
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Query, Path, Request, Body, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.models.database import get_db
from app.api.users import get_request_locale, get_optional_user
from app.i18n.messages import t

from app.models.log import (
    LogUploadRequest, LogUploadResponse, LogListRequest, LogListResponse,
    LogDetailResponse, LogDeleteResponse, BatchDeleteRequest, BatchDeleteResponse,
    BatchDownloadRequest, BatchDownloadResponse, LogLevel, LogStatus,
    LogMetadata, SortField, SortOrder, ManualAnalysisRequest, IssueDescriptionUpdateRequest
)
from app.models.project_repo import ProjectRepo
from app.services import project_repo_service
from app.services.log_service import log_service
from app.services.agent_trace_redis import get_buffer
from app.utils.validation import request_validator
from app.utils.file_upload_validator import t04_file_validator
from app.utils.temp_file_cleaner import temp_file_cleaner, upload_temp_manager
from app.exceptions import ValidationError, FileUploadError, FileSizeExceededError, UnsupportedFileTypeError, FileNotFoundError, AuthorizationError, LogServiceException, FileProcessingError

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBearer(auto_error=False)


# 注意：日志的项目归属完全依赖显式 project_id / project_code（前端或调用方按项目选择）。
# 历史上曾根据卫星协议栈/OAM 的文件名或 metadata.json 组件名自动分类为
# stack / oam_antenna / full，该自动分类机制已移除——日志类型现在由项目区分。


async def resolve_project(
    db: AsyncSession,
    *,
    project_id: Optional[int] = None,
    project_code: Optional[str] = None,
    locale: str = "zh",
) -> Optional[ProjectRepo]:
    """
    统一的项目解析：显式 project_id → 显式 project_code → None。
    显式 project_id/project_code 无效时抛出 HTTP 400。
    """
    # 日志（日志分析 Agent 域）对「未关联代码仓库」的项目不可见。
    if project_id is not None:
        repo = await project_repo_service.get_by_id(db, project_id)
        if (
            not repo
            or not repo.enabled
            or not await project_repo_service.supports_agent(db, repo, "log_analysis")
        ):
            raise HTTPException(status_code=400, detail=t("log.project_not_found_id", locale, project_id=project_id))
        return repo
    if project_code:
        repo = await project_repo_service.get_by_project_code(db, project_code, require_repo=True)
        if not repo or not await project_repo_service.supports_agent(
            db, repo, "log_analysis"
        ):
            raise HTTPException(status_code=400, detail=t("log.project_not_found_code", locale, project_code=project_code))
        return repo
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

        # 支持 .zip、.rar 与 tar 家族（.tar, .tgz, .tar.gz, 等）
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

        # RAR
        if metadata_dict is None and suffix_lower == ".rar":
            try:
                import rarfile
                with rarfile.RarFile(file_path, "r") as rf:
                    meta_info = next((i for i in rf.infolist() if not i.isdir() and i.filename.endswith("metadata.json")), None)
                    if meta_info:
                        with rf.open(meta_info) as f:
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

        # 组装需要更新的数据
        update_data = {
            "metadata_json": json.dumps(log_metadata_dict, ensure_ascii=False)
        }

        # 仅当 issue_description 为空时从文件回填
        if issue_desc and is_empty(getattr(record, "issue_description", None)):
            update_data["issue_description"] = issue_desc

        # 项目归属不再根据 metadata.json 中的组件名自动推断；保持上传时显式指定的 project_id。

        # 执行更新并提交
        await log_service.update(db, log_info.id, **update_data)
        await db.commit()
    except Exception as e:
        # 解析失败不影响主流程
        logger.warning(f"metadata.json 解析或回填失败: {e}")

@router.post("/upload-simple", response_model=LogUploadResponse, status_code=201)
async def upload_log_simple(
    file: UploadFile = File(..., description="要上传的日志文件"),
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_request_locale),
):
    """
    简化的日志文件上传接口
    """
    # 不再根据文件名推断项目；该接口未显式指定项目，统一为未分类（NULL）。
    metadata = LogMetadata()
    upload_request = LogUploadRequest(
        project_code=None,
        project_id=None,
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
        message=t("log.upload_success", locale),
        data=log_info
    )


@router.post("/upload", response_model=LogUploadResponse, status_code=201)
async def upload_log(
    file: UploadFile = File(..., description="要上传的日志文件"),
    project_code: Optional[str] = Form(None, description="关联项目代号（与 project_id 二选一）"),
    project_id: Optional[int] = Form(None, description="关联项目ID（与 project_code 二选一）"),
    log_level: LogLevel = Form(LogLevel.INFO, description="日志级别"),
    source: Optional[str] = Form(None, description="日志来源"),
    environment: Optional[str] = Form(None, description="环境信息"),
    service_name: Optional[str] = Form(None, description="服务名称"),
    version: Optional[str] = Form(None, description="版本号"),
    expires_in_days: Optional[int] = Form(None, ge=1, le=365, description="过期天数"),
    issue_description: Optional[str] = Form(None, description="问题描述"),
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_request_locale),
):
    """
    上传日志文件

    - **file**: 要上传的日志文件
    - **project_code**: 关联项目代号（可选；与 project_id 二选一）
    - **project_id**: 关联项目ID（可选；与 project_code 二选一）
    - **log_level**: 日志级别 (debug, info, warn, error, fatal)
    - **source**: 日志来源系统
    - **environment**: 运行环境 (dev, test, prod等)
    - **service_name**: 服务名称
    - **version**: 版本号
    - **expires_in_days**: 文件过期天数 (1-365天)
    - **issue_description**: 问题描述，用于描述日志所对应的问题

    项目解析顺序：显式 project_id → 显式 project_code → 未分类(NULL)
    """

    # 构建元数据
    metadata = LogMetadata(
        source=source,
        environment=environment,
        service_name=service_name,
        version=version
    )

    # 解析关联项目（仅按显式 project_id / project_code，不再按文件名推断）
    project = await resolve_project(
        db,
        project_id=project_id,
        project_code=project_code,
        locale=locale,
    )

    # 构建上传请求
    upload_request = LogUploadRequest(
        project_code=project.project_code if project else None,
        project_id=project.id if project else None,
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
        message=t("log.upload_success", locale),
        data=log_info
    )


@router.post("/upload-t04", status_code=201)
async def upload_t04_logs(
    request: Request,
    files: List[UploadFile] = File(..., description="要上传的日志归档文件列表"),
    project_code: Optional[str] = Form(None, description="可选：关联项目代号；未提供时为未分类"),
):
    """
    T04任务：上传日志归档文件
    
    支持功能：
    - 多文件同时上传
    - 允许系统支持的日志归档格式
    - 文件大小限制1GB
    - 文件完整性验证（magic number检查）
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
    
    # 解析请求语言（header → Accept-Language → 默认 zh），用于用户可见的错误信息
    from app.i18n.deps import LOCALE_HEADER, resolve_locale
    locale = resolve_locale(
        header_locale=request.headers.get(LOCALE_HEADER),
        accept_language=request.headers.get("Accept-Language"),
    )

    # 验证文件列表
    logger.info("T04上传 - 开始文件验证")
    try:
        is_valid, error_msg = await t04_file_validator.validate_upload_files(files, locale)
        if not is_valid:
            logger.error(f"T04上传 - 文件验证失败: {error_msg}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "success": False,
                    "message": t("log.file_validation_failed", locale),
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
                "message": t("log.file_size_exceeded", locale),
                "error": str(e)
            }
        )
    except UnsupportedFileTypeError as e:
        logger.error(f"T04上传 - 文件格式错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "message": t("log.file_format_error", locale),
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
                    "message": t("log.file_corrupted", locale),
                    "error": str(e)
                }
            )
        else:
            logger.error(f"T04上传 - 文件验证失败: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "success": False,
                    "message": t("log.file_validation_failed", locale),
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
                    "message": t("log.storage_insufficient", locale),
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
                    
                    # 解析关联项目：仅使用显式传入的 project_code，不再按文件名推断
                    inferred_project = (
                        await project_repo_service.get_by_project_code(
                            db, project_code, require_repo=True
                        )
                        if project_code
                        else None
                    )
                    resolved_project_id = inferred_project.id if inferred_project else None
                    resolved_project_code = inferred_project.project_code if inferred_project else None
                    logger.info(f"T04上传 - 解析项目: code={resolved_project_code} id={resolved_project_id}")
                    
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
                        "archive_path": str(file_path),
                        "project_id": resolved_project_id,
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
                        "project_code": resolved_project_code,
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
                    "message": t("log.server_error", locale),
                    "error": "数据库操作失败"
                }
            )

    # 构建响应
    logger.info(f"T04上传 - 上传完成: 成功={len(upload_results)}, 失败={len(failed_files)}")
    if upload_results:
        if failed_files:
            _msg = t("log.t04_upload_partial", locale, uploaded=len(upload_results), failed=len(failed_files))
        else:
            _msg = t("log.t04_upload_success", locale, count=len(upload_results))
        response_data = {
            "success": True,
            "message": _msg,
            "data": {
                "uploaded_files": upload_results,
                "failed_files": failed_files if failed_files else None,
                "total_uploaded": len(upload_results),
                "total_failed": len(failed_files)
            }
        }

        if failed_files:
            logger.warning(f"T04上传 - 部分成功: {len(upload_results)}/{len(files)} 个文件上传成功")
        else:
            logger.info(f"T04上传 - 全部成功: {len(upload_results)} 个文件上传成功")
        return response_data
    else:
        logger.error(f"T04上传 - 全部失败: {len(failed_files)} 个文件上传失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "message": t("log.t04_upload_all_failed", locale),
                "data": {
                    "failed_files": failed_files
                }
            }
        )


@router.get("", response_model=LogListResponse)
async def get_logs(
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(20, ge=1, le=100, description="每页大小"),
    project_id: Optional[int] = Query(None, description="项目过滤；0 或 none 表示未分类日志"),
    log_level: LogLevel = Query(None, description="日志级别过滤"),
    status: LogStatus = Query(None, description="状态过滤"),
    start_time: str = Query(None, description="开始时间 (ISO格式)"),
    end_time: str = Query(None, description="结束时间 (ISO格式)"),
    search: str = Query(None, max_length=100, description="搜索关键词（按文件名搜索）"),
    sort_by: SortField = Query(SortField.CREATED_AT, description="排序字段"),
    sort_order: SortOrder = Query(SortOrder.DESC, description="排序顺序"),
    tags: List[str] = Query(None, description="标签过滤"),
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_request_locale),
):
    """
    获取日志列表
    
    支持多种过滤条件：
    - **page**: 页码 (从1开始)
    - **per_page**: 每页大小 (1-100)
    - **project_id**: 按项目过滤（0 或 none 表示未分类）
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
        project_id=project_id,
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
        message=t("log.list_success", locale),
        data=log_data
    )


@router.get("/{log_id}", response_model=LogDetailResponse)
async def get_log_detail(
    log_id: str = Path(..., description="日志文件ID"),
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_request_locale),
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
    - project_id / project_code / project_name: 关联项目信息
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
            message=t("log.detail_success", locale),
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
            message=t("log.detail_failed", locale),
            error_code="LOG_DETAIL_ERROR",
            detail=str(e)
        )


@router.delete("/{log_id}", response_model=LogDeleteResponse)
async def delete_log(
    log_id: str = Path(..., description="日志文件ID"),
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_request_locale),
):
    """
    删除日志文件（软删除）
    
    - **log_id**: 要删除的日志文件ID
    """
    
    # 验证日志ID
    request_validator.validate_log_id(log_id)
    
    # A grouped row represents one analysis, so deleting it removes every
    # original attachment instead of exposing orphan rows afterwards.
    group_records = await log_service.get_analysis_group_records(db, log_id)
    for record in group_records:
        await log_service.delete_log(db, record.id)
    
    logger.info(f"Log deleted successfully: {log_id}")
    
    return LogDeleteResponse(
        message=t("log.delete_success", locale)
    )


@router.get("/{log_id}/download")
async def download_log(
    log_id: str = Path(..., description="日志文件ID"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_request_locale),
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

        group_records = await log_service.get_analysis_group_records(db, log_id)
        if len(group_records) > 1:
            log_info = await log_service.get_log_detail(db, log_id)
            if log_info.status not in [
                LogStatus.COMPLETED,
                LogStatus.PROCESSING,
                LogStatus.PENDING,
            ]:
                raise AuthorizationError(
                    t("log.not_ready_for_download", locale)
                )
            archive_path = await log_service.batch_download(
                db,
                BatchDownloadRequest(
                    log_ids=[record.id for record in group_records],
                    compress=True,
                    include_metadata=False,
                ),
            )
            archive = FilePath(archive_path)
            filename = (
                log_info.download_filename
                or f"log_analysis_{log_id[:8]}.zip"
            )
            logger.info(
                "Grouped log download started: group=%s attachment_count=%d",
                log_info.analysis_group_id or log_id,
                len(group_records),
            )
            return FileResponse(
                path=archive,
                media_type="application/zip",
                filename=filename,
                background=BackgroundTask(archive.unlink, missing_ok=True),
            )
        
        # 获取文件路径和日志信息（包含权限验证）
        file_path = await log_service.get_download_path(db, log_id)
        log_info = await log_service.get_log_detail(db, log_id)
        
        # 检查日志状态是否允许下载（临时允许pending状态用于测试）
        if log_info.status not in [LogStatus.COMPLETED, LogStatus.PROCESSING, LogStatus.PENDING]:
            raise AuthorizationError(t("log.not_ready_for_download", locale))
        
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
            message=t("log.download_failed", locale),
            error_code="DOWNLOAD_ERROR",
            detail=str(e)
        )


@router.post("/{log_id}/download-count")
async def increment_download_count(
    log_id: str = Path(..., description="日志文件ID"),
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_request_locale),
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
            "message": t("log.download_count_updated", locale),
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
            message=t("log.download_count_failed", locale),
            error_code="DOWNLOAD_COUNT_ERROR",
            detail=str(e)
        )


@router.post("/batch/delete", response_model=BatchDeleteResponse)
async def batch_delete_logs(
    request: BatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_request_locale),
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

        expanded_ids = await log_service.expand_analysis_group_ids(
            db, request.log_ids
        )
        expanded_request = BatchDeleteRequest(
            log_ids=expanded_ids,
            force=request.force,
        )
        
        # 执行批量删除
        result = await log_service.batch_delete(db, expanded_request)
        
        logger.info(
            f"Batch delete completed: {result.deleted_count} deleted, {result.failed_count} failed"
        )
        
        return BatchDeleteResponse(
            success=True,
            message=t("log.batch_delete_complete", locale, deleted=result.deleted_count, failed=result.failed_count),
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
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_request_locale),
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
            raise ValidationError(t("log.batch_download_limit", locale))
        
        request_validator.validate_log_ids(request.log_ids)

        expanded_ids = await log_service.expand_analysis_group_ids(
            db, request.log_ids
        )
        if len(expanded_ids) > 50:
            raise ValidationError(
                t("log.batch_download_limit", locale)
            )
        expanded_request = BatchDownloadRequest(
            log_ids=expanded_ids,
            compress=request.compress,
            include_metadata=request.include_metadata,
        )
        
        # 执行批量下载
        zip_path = await log_service.batch_download(db, expanded_request)
        
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
        
        logger.info(f"Batch download prepared: {len(expanded_ids)} files requested, {file_size} bytes")
        
        return BatchDownloadResponse(
            success=True,
            message=t("log.batch_download_ready", locale),
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
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_request_locale),
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
            raise ValidationError(t("log.stream_download_limit", locale))
        
        request_validator.validate_log_ids(request.log_ids)

        expanded_ids = await log_service.expand_analysis_group_ids(
            db, request.log_ids
        )
        if len(expanded_ids) > 20:
            raise ValidationError(
                t("log.stream_download_limit", locale)
            )
        expanded_request = BatchDownloadRequest(
            log_ids=expanded_ids,
            compress=request.compress,
            include_metadata=request.include_metadata,
        )
        
        # 执行流式批量下载
        zip_content = await log_service.batch_download_stream(
            db, expanded_request
        )
        
        # 生成文件名
        download_id = str(uuid.uuid4())[:8]
        filename = f"logs_stream_{download_id}.zip"
        
        logger.info(f"Stream batch download: {len(expanded_ids)} files, {len(zip_content)} bytes")
        
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


@router.post("/{log_id}/analyze")
async def analyze_log(
    request: Request,
    log_id: str = Path(..., description="日志文件ID"),
    query: str = Form(..., description="分析查询内容"),
    project_repo_id: Optional[int] = Form(
        None,
        description="可选：指定项目仓库注册表 ID。若提供，则跳过 metadata.json 解析，直接使用该项目的仓库信息。",
    ),
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_request_locale),
    current_user=Depends(get_optional_user),
):
    """
    AI分析日志文件

    触发异步AI分析任务（Celery执行），立即返回任务信息。
    """

    try:
        request_validator.validate_log_id(log_id)
        log_record = await log_service.get_by_id(db, log_id)
        if not log_record or getattr(log_record, "is_deleted", False):
            raise FileNotFoundError(file_id=log_id)

        # 确保文件存在
        file_path = FilePath(getattr(log_record, "file_path", ""))
        if not file_path.exists():
            raise FileNotFoundError(filename=str(file_path))

        # Pre-validate: archive or file must exist before dispatching to Celery
        _archive = getattr(log_record, "archive_path", None) or getattr(log_record, "file_path", None)
        if not _archive:
            raise HTTPException(
                status_code=400,
                detail={
                    "error_kind": "missing_archive",
                    "message": t("log.archive_path_missing", locale),
                },
            )

        # When the user explicitly chose a project repo, validate it exists
        # and is enabled up-front so we fail fast with a clear 400.
        if project_repo_id is not None:
            from app.services import project_repo_service

            repo = await project_repo_service.get_by_id(db, project_repo_id)
            if (
                not repo
                or not repo.enabled
                or not await project_repo_service.supports_agent(
                    db, repo, "log_analysis"
                )
            ):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error_kind": "invalid_project_repo",
                        "message": t("log.invalid_project_repo", locale),
                    },
                )

        logger.info(
            "Queue AI analysis for log %s: query='%s' project_repo_id=%s",
            log_id, query, project_repo_id,
        )

        # 触发Celery异步任务
        try:
            from app.tasks.ai_analysis import run_ai_analysis_task

            task_result = run_ai_analysis_task.delay(
                log_id, query, project_repo_id, locale
            )

            # 记录任务信息，便于前端轮询
            started_at = datetime.utcnow()
            trigger_user = {}
            if current_user is not None:
                trigger_user = {
                    "id": current_user.id,
                    "username": current_user.username,
                    "display_name": current_user.display_name,
                    "email": current_user.email,
                }
            await log_service.update_ai_analysis_task(
                db,
                log_id,
                task_id=task_result.id,
                status="queued",
                progress=0.0,
                query=query,
                started_at=started_at,
                triggered_by={
                    "source": "log_detail",
                    "task_id": task_result.id,
                    "user": {
                        key: value
                        for key, value in trigger_user.items()
                        if value is not None
                    },
                    "started_at": started_at.isoformat(),
                },
            )

            return {
                "success": True,
                "message": t("log.ai_analysis_queued", locale),
                "data": {
                    "task_id": task_result.id,
                    "status": "queued",
                    "log_id": log_id
                }
            }

        except ImportError as e:
            logger.error(f"AI analysis failed: log_agent module not available: {e}")
            raise LogServiceException(
                message=t("log.ai_module_unavailable", locale),
                error_code="AI_MODULE_ERROR",
                detail=str(e)
            )
        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            raise LogServiceException(
                message=t("log.ai_analysis_failed", locale),
                error_code="AI_ANALYSIS_ERROR",
                detail=str(e)
            )

    except ValidationError as e:
        logger.warning(f"Invalid log ID format for AI analysis: {log_id}")
        raise e
    except FileNotFoundError as e:
        logger.warning(f"File not found for AI analysis: {log_id}")
        raise e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during AI analysis {log_id}: {str(e)}")
        raise LogServiceException(
            message=t("log.ai_analysis_error", locale),
            error_code="AI_ANALYSIS_ERROR",
            detail=str(e)
        )


@router.get("/{log_id}/analysis/status")
async def get_ai_analysis_status(
    log_id: str = Path(..., description="日志文件ID"),
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_request_locale),
):
    """
    查询AI分析任务状态（含已完成结果）
    """
    try:
        request_validator.validate_log_id(log_id)
        log_info = await log_service.get_log_detail(db, log_id)

        result_raw = getattr(log_info, "ai_analysis_result", None)
        error_kind = None
        if isinstance(result_raw, dict):
            error_kind = result_raw.get("error_kind")
        elif isinstance(result_raw, str):
            try:
                import json as _json
                parsed = _json.loads(result_raw)
                error_kind = parsed.get("error_kind") if isinstance(parsed, dict) else None
            except Exception:
                pass

        return {
            "success": True,
            "message": t("log.ai_status_success", locale),
            "data": {
                "log_id": log_id,
                "task_id": getattr(log_info, "ai_analysis_task_id", None),
                "status": getattr(log_info, "ai_analysis_status", None),
                "progress": getattr(log_info, "ai_analysis_progress", None),
                "query": getattr(log_info, "ai_analysis_query", None),
                "error": getattr(log_info, "ai_analysis_error", None),
                "error_kind": error_kind,
                "error_kind_message": t(f"log.error_kind.{error_kind}", locale) if error_kind else None,
                "started_at": getattr(log_info, "ai_analysis_started_at", None),
                "finished_at": getattr(log_info, "ai_analysis_finished_at", None),
                "result": result_raw,
            }
        }
    except Exception as e:
        logger.error(f"Failed to fetch AI analysis status for {log_id}: {e}")
        raise LogServiceException(
            message=t("log.ai_status_failed", locale),
            error_code="AI_ANALYSIS_STATUS_ERROR",
            detail=str(e)
        )


_TRACE_STREAM_POLL_INTERVAL_SECONDS = 0.2
_TRACE_STREAM_HEARTBEAT_INTERVAL_SECONDS = 15
_TRACE_STREAM_MAX_DURATION_SECONDS = 30 * 60


@router.get("/{log_id}/ai-analysis/trace/stream")
async def stream_ai_analysis_trace(
    log_id: str = Path(..., description="日志文件ID"),
    from_seq: int = Query(0, ge=0, description="只返回 seq 严格大于该值的事件，用于断线重连增量取回"),
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_request_locale),
):
    """SSE stream of ``AgentTraceEvent`` rows for a log's AI analysis task.

    Three execution modes, transparently chosen from the current task status:

    - ``running`` / ``queued`` — polls the Redis ``TraceBuffer`` every
      ~200ms and emits new events (those with ``seq > from_seq``).
    - ``completed`` / ``failed`` — replays the persisted
      ``ai_analysis_result.trace_events`` slice in one shot, then closes.
    - no task at all — 404.

    Heartbeat: a ``system_notice{kind:"heartbeat"}`` frame is yielded every
    15s of inactivity while the task is still running, so proxies do not
    close the long-running SSE as idle.
    """
    import asyncio as _asyncio

    request_validator.validate_log_id(log_id)
    log_info = await log_service.get_log_detail(db, log_id)
    if log_info is None:
        raise FileNotFoundError(file_id=log_id)

    task_id = getattr(log_info, "ai_analysis_task_id", None)
    initial_status = (getattr(log_info, "ai_analysis_status", None) or "").lower()
    if not task_id and initial_status not in {"completed", "failed"}:
        raise HTTPException(
            status_code=404,
            detail={"error_kind": "no_task", "message": t("log.no_ai_task", locale)},
        )

    def _sse(payload: dict) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

    def _agent_trace_frame(event: dict) -> str:
        return _sse({"event": "agent_trace", **event})

    def _heartbeat_frame() -> str:
        return _sse({
            "event": "agent_trace",
            "type": "system_notice",
            "task_id": task_id,
            "kind": "heartbeat",
            "timestamp": datetime.utcnow().timestamp(),
        })

    def _events_from_result(result: object) -> list:
        if not isinstance(result, dict):
            return []
        events = result.get("trace_events") or []
        return events if isinstance(events, list) else []

    def _replay_completed_events(events: list, last_seq: int):
        frames = []
        new_last = last_seq
        for event in events:
            if not isinstance(event, dict):
                continue
            try:
                seq = int(event.get("seq", 0))
            except (TypeError, ValueError):
                seq = 0
            if seq > last_seq:
                frames.append(_agent_trace_frame(event))
                new_last = max(new_last, seq)
        return frames, new_last

    async def _generate():
        from app.services.agent_trace_redis import get_buffer

        last_seq = int(from_seq or 0)
        started_at = time.monotonic()
        last_activity = started_at
        buffer = get_buffer()

        # Terminal-state shortcut: stream persisted history once and close.
        if initial_status in {"completed", "failed"}:
            persisted = _events_from_result(getattr(log_info, "ai_analysis_result", None))
            frames, _ = _replay_completed_events(persisted, last_seq)
            for frame in frames:
                yield frame
            yield _sse({
                "event": "stream_end",
                "task_id": task_id,
                "reason": initial_status,
            })
            return

        # Running path: replay whatever Redis already has, then poll.
        if task_id:
            buffered = buffer.read_all(task_id)
            frames, last_seq = _replay_completed_events(buffered, last_seq)
            for frame in frames:
                yield frame
            if frames:
                last_activity = time.monotonic()

        # Poll loop. We re-check the DB status every cycle so we can close
        # the stream as soon as the task transitions to a terminal state.
        while True:
            now = time.monotonic()
            if now - started_at > _TRACE_STREAM_MAX_DURATION_SECONDS:
                yield _sse({
                    "event": "stream_end",
                    "task_id": task_id,
                    "reason": "max_duration",
                })
                return

            saw_new = False
            if task_id:
                for event in buffer.read_all(task_id):
                    try:
                        seq = int(event.get("seq", 0))
                    except (TypeError, ValueError):
                        seq = 0
                    if seq > last_seq:
                        yield _agent_trace_frame(event)
                        last_seq = seq
                        saw_new = True
            if saw_new:
                last_activity = time.monotonic()

            # Check whether the task has finished. Use a fresh session so we
            # see writes the Celery worker has committed.
            try:
                refreshed = await log_service.get_log_detail(db, log_id)
            except Exception:
                refreshed = None

            current_status = (
                getattr(refreshed, "ai_analysis_status", None) or ""
            ).lower() if refreshed else ""

            if current_status in {"completed", "failed"}:
                # Flush any events that landed only in the persisted result
                # (and not in Redis), in case the LTRIM truncated history.
                persisted = _events_from_result(getattr(refreshed, "ai_analysis_result", None))
                frames, last_seq = _replay_completed_events(persisted, last_seq)
                for frame in frames:
                    yield frame
                yield _sse({
                    "event": "stream_end",
                    "task_id": task_id,
                    "reason": current_status,
                })
                return

            if time.monotonic() - last_activity >= _TRACE_STREAM_HEARTBEAT_INTERVAL_SECONDS:
                yield _heartbeat_frame()
                last_activity = time.monotonic()

            await _asyncio.sleep(_TRACE_STREAM_POLL_INTERVAL_SECONDS)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.put("/{log_id}/issue-description")
async def update_issue_description(
    log_id: str = Path(..., description="日志文件ID"),
    payload: IssueDescriptionUpdateRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_request_locale),
):
    """
    更新日志问题描述
    """
    try:
        request_validator.validate_log_id(log_id)
        result = await log_service.update_issue_description(db, log_id, payload.issue_description)
        return {
            "success": True,
            "message": t("log.issue_description_updated", locale),
            "data": {
                "log_id": log_id,
                "issue_description": result.issue_description,
                "updated_at": result.updated_at
            }
        }
    except ValidationError as e:
        logger.warning(f"Invalid log ID format for issue description: {log_id}")
        raise e
    except FileNotFoundError as e:
        logger.warning(f"File not found for issue description update: {log_id}")
        raise e
    except Exception as e:
        logger.error(f"Failed to update issue description for {log_id}: {e}")
        raise LogServiceException(
            message=t("log.issue_description_failed", locale),
            error_code="ISSUE_DESCRIPTION_UPDATE_ERROR",
            detail=str(e)
        )


@router.post("/{log_id}/manual-analysis")
async def save_manual_analysis(
    log_id: str = Path(..., description="日志文件ID"),
    payload: ManualAnalysisRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_request_locale),
    current_user=Depends(get_optional_user),
):
    """
    保存人工分析结果
    """
    try:
        request_validator.validate_log_id(log_id)
        author = None
        if current_user is not None:
            author = {
                "id": current_user.id,
                "username": current_user.username,
                "display_name": current_user.display_name,
                "email": current_user.email,
            }
        result = await log_service.save_manual_analysis(db, log_id, payload.content, author=author)
        return {
            "success": True,
            "message": t("log.manual_analysis_saved", locale),
            "data": {
                "log_id": log_id,
                "manual_analysis": result.manual_analysis,
                "manual_analysis_updated_at": result.manual_analysis_updated_at,
                "manual_analysis_author": result.manual_analysis_author
            }
        }
    except ValidationError as e:
        logger.warning(f"Invalid log ID format for manual analysis: {log_id}")
        raise e
    except FileNotFoundError as e:
        logger.warning(f"File not found for manual analysis: {log_id}")
        raise e
    except Exception as e:
        logger.error(f"Failed to save manual analysis for {log_id}: {e}")
        raise LogServiceException(
            message=t("log.manual_analysis_failed", locale),
            error_code="MANUAL_ANALYSIS_SAVE_ERROR",
            detail=str(e)
        )
