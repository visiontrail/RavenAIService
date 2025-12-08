"""
日志服务模块
处理所有日志相关的业务逻辑，使用SQLAlchemy数据库操作
"""

import os
import shutil
import zipfile
import tempfile
import uuid
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.config import settings
from app.models.log import (
    LogRecord, LogFileInfo, LogUploadRequest, LogListRequest, BatchDeleteRequest,
    BatchDownloadRequest, LogStatus, LogType, LogLevel, LogMetadata,
    BatchOperationResult, SortField, SortOrder, LogListData, PaginationInfo
)
from app.models.database import get_db
from app.services.base import BaseCRUDService
from app.exceptions import (
    FileNotFoundError, FileUploadError, StorageError,
    FileProcessingError, BatchOperationError
)
from app.utils.validation import file_validator
import glob

logger = logging.getLogger(__name__)


class LogService(BaseCRUDService[LogRecord]):
    """日志服务类"""
    
    def __init__(self):
        super().__init__(LogRecord)
        self.storage_path = Path(settings.temp_dir)
        self.logs_storage_path = self.storage_path / "logs"
        self.downloads_storage_path = self.storage_path / "downloads"
        
        # 确保存储目录存在
        self.logs_storage_path.mkdir(parents=True, exist_ok=True)
        self.downloads_storage_path.mkdir(parents=True, exist_ok=True)

    async def upload_log(
        self, 
        db: AsyncSession, 
        file: UploadFile, 
        request: LogUploadRequest
    ) -> LogFileInfo:
        """
        上传日志文件
        
        Args:
            db: 数据库会话
            file: 上传的文件
            request: 上传请求参数
            
        Returns:
            LogFileInfo: 上传后的文件信息
        """
        logger.info(f"LogService - 开始处理日志上传: {file.filename}")
        try:
            # 验证文件
            logger.info(f"LogService - 开始验证文件: {file.filename}")
            is_valid, error_msg = await file_validator.validate_upload_file(file)
            if not is_valid:
                logger.error(f"LogService - 文件验证失败: {file.filename}, 错误: {error_msg}")
                raise FileUploadError(error_msg)
            logger.info(f"LogService - 文件验证通过: {file.filename}")
            
            # 生成文件ID和存储路径
            file_id = str(uuid.uuid4())
            original_filename = file.filename
            sanitized_filename = file_validator.sanitize_filename(original_filename)
            stored_filename = f"{file_id}_{sanitized_filename}"
            file_path = self.logs_storage_path / stored_filename
            logger.info(f"LogService - 生成文件路径: {file_path}")
            
            # 计算文件校验和
            logger.info(f"LogService - 开始计算文件校验和: {file.filename}")
            checksum = await file_validator.calculate_file_checksum(file)
            logger.info(f"LogService - 文件校验和计算完成: {checksum[:16]}...")
            
            # 保存文件
            logger.info(f"LogService - 开始保存文件: {file_path}")
            await self._save_file(file, file_path)
            logger.info(f"LogService - 文件保存完成")
            
            # 获取文件信息
            file_size = file_path.stat().st_size
            mime_type = file.content_type or "application/octet-stream"
            logger.info(f"LogService - 文件信息: 大小={file_size} bytes, MIME类型={mime_type}")
            
            # 将元数据转换为JSON字符串
            metadata_json = None
            if request.metadata:
                metadata_json = request.metadata.model_dump_json()
            
            # 根据日志类型确定初始状态和进度
            # OAM天线日志上传后直接标记为已完成，其他类型保持待处理状态
            initial_status = LogStatus.COMPLETED if request.log_type == LogType.OAM_ANTENNA else LogStatus.PENDING
            initial_progress = 100.0 if request.log_type == LogType.OAM_ANTENNA else 0.0
            processed_at = datetime.utcnow() if request.log_type == LogType.OAM_ANTENNA else None
            
            logger.info(f"LogService - 日志类型: {request.log_type.value}, 初始状态: {initial_status.value}, 初始进度: {initial_progress}")
            
            # 创建数据库记录
            logger.info(f"LogService - 开始创建数据库记录: ID={file_id}")
            create_data = {
                "id": file_id,
                "filename": stored_filename,
                "original_filename": original_filename,
                "file_size": file_size,
                "file_path": str(file_path),
                "log_type": request.log_type,
                "status": initial_status,
                "progress": initial_progress,
                "checksum": checksum,
                "mime_type": mime_type,
                "log_level": request.log_level,
                "metadata_json": metadata_json,
                "issue_description": request.issue_description
            }
            
            # 如果是OAM天线日志，设置处理完成时间
            if processed_at:
                create_data["processed_at"] = processed_at
            
            log_record = await self.create(db=db, **create_data)
            logger.info(f"LogService - 数据库记录创建成功: ID={file_id}")
            
            # 转换为Pydantic模型
            result = await self._db_to_pydantic(log_record, request.metadata)
            
            # 立即提交事务，确保数据在触发Celery任务前已完全写入数据库
            # 这样可以避免Celery worker无法找到记录的竞态条件
            await db.commit()
            logger.info(f"LogService - 数据库记录已提交: ID={file_id}")
            
            # 检查是否为协议栈日志，如果是则自动触发处理
            # OAM天线日志已经标记为完成，无需额外处理
            if request.log_type != LogType.OAM_ANTENNA:
                logger.info(f"LogService - 检查是否需要触发协议栈处理: {original_filename}")
                await self._check_and_trigger_protocol_stack_processing(log_record)
            else:
                logger.info(f"LogService - OAM天线日志无需额外处理，已标记为完成: {original_filename}")
            
            logger.info(f"LogService - 日志上传完成: ID={file_id}, 文件名={original_filename}")
            return result
            
        except Exception as e:
            logger.error(f"LogService - 日志上传失败: {file.filename}, 错误: {str(e)}")
            # 清理已创建的文件
            if 'file_path' in locals() and file_path.exists():
                file_path.unlink()
                logger.info(f"LogService - 清理失败文件: {file_path}")
            
            if isinstance(e, (FileUploadError, StorageError)):
                raise e
            else:
                raise FileUploadError(f"上传失败: {str(e)}")

    async def get_log_list(
        self, 
        db: AsyncSession, 
        request: LogListRequest
    ) -> LogListData:
        """
        获取日志列表
        
        Args:
            db: 数据库会话
            request: 查询请求参数
            
        Returns:
            LogListData: 包含日志列表和分页信息的数据
        """
        try:
            # 构建查询条件
            query = select(LogRecord)
            
            # 添加过滤条件（默认只查询未删除的记录）
            conditions = [LogRecord.is_deleted == False]
            
            if request.log_type:
                conditions.append(LogRecord.log_type == request.log_type)
            
            if request.log_level:
                conditions.append(LogRecord.log_level == request.log_level)
            
            if request.status:
                conditions.append(LogRecord.status == request.status)
            
            if request.start_time:
                conditions.append(LogRecord.created_at >= request.start_time)
            
            if request.end_time:
                conditions.append(LogRecord.created_at <= request.end_time)
            
            # 按文件名搜索
            if request.search:
                search_pattern = f"%{request.search}%"
                conditions.append(
                    or_(
                        LogRecord.original_filename.ilike(search_pattern),
                        LogRecord.filename.ilike(search_pattern)
                    )
                )
            
            # 应用过滤条件
            if conditions:
                filter_condition = and_(*conditions)
                query = query.where(filter_condition)
            
            # 计算总数
            from sqlalchemy import func
            total_query = select(func.count(LogRecord.id))
            if conditions:
                total_query = total_query.where(and_(*conditions))
            
            total_result = await db.execute(total_query)
            total = total_result.scalar() or 0
            
            # 排序
            sort_column = getattr(LogRecord, request.sort_by.value)
            if request.sort_order == SortOrder.DESC:
                query = query.order_by(sort_column.desc())
            else:
                query = query.order_by(sort_column.asc())
            
            # 分页
            offset = (request.page - 1) * request.per_page
            query = query.offset(offset).limit(request.per_page)
            
            # 执行查询
            result = await db.execute(query)
            log_records = result.scalars().all()
            
            # 转换为Pydantic模型
            log_infos = []
            for record in log_records:
                metadata = None
                if record.metadata_json:
                    try:
                        metadata_dict = json.loads(record.metadata_json)
                        metadata = LogMetadata(**metadata_dict)
                    except:
                        metadata = LogMetadata()
                
                log_info = await self._db_to_pydantic(record, metadata)
                log_infos.append(log_info)
            
            # 计算分页信息
            pages = (total + request.per_page - 1) // request.per_page if total > 0 else 0
            pagination = PaginationInfo(
                page=request.page,
                per_page=request.per_page,
                total=total,
                pages=pages
            )
            
            return LogListData(
                logs=log_infos,
                pagination=pagination
            )
            
        except Exception as e:
            raise StorageError(f"获取日志列表失败: {str(e)}")

    async def get_log_detail(self, db: AsyncSession, log_id: str) -> LogFileInfo:
        """
        获取日志详情
        
        Args:
            db: 数据库会话
            log_id: 日志ID
            
        Returns:
            LogFileInfo: 日志详情
        """
        log_record = await self.get_by_id(db, log_id)
        
        if not log_record or log_record.is_deleted:
            raise FileNotFoundError(file_id=log_id)
        
        # 检查文件是否存在
        if not Path(log_record.file_path).exists():
            # 更新状态为失败
            await self.update(db, log_id, status=LogStatus.FAILED, error_message="文件不存在")
            raise FileNotFoundError(file_id=log_id)
        
        # 解析元数据
        metadata = LogMetadata()
        if log_record.metadata_json:
            try:
                metadata_dict = json.loads(log_record.metadata_json)
                metadata = LogMetadata(**metadata_dict)
            except:
                pass
        
        return await self._db_to_pydantic(log_record, metadata)

    async def save_ai_analysis_result(
        self,
        db: AsyncSession,
        log_id: str,
        analysis_data: Dict[str, Any]
    ) -> LogFileInfo:
        """
        保存AI分析结果到日志元数据中，便于后续读取
        """
        log_record = await self.get_by_id(db, log_id)

        if not log_record or log_record.is_deleted:
            raise FileNotFoundError(file_id=log_id)

        metadata_dict: Dict[str, Any] = {}
        try:
            if log_record.metadata_json:
                metadata_dict = json.loads(log_record.metadata_json) or {}
        except Exception:
            metadata_dict = {}

        # 确保 extra_fields 可用
        extra_fields = metadata_dict.get("extra_fields")
        if not isinstance(extra_fields, dict):
            extra_fields = {}

        # 更新并写回元数据
        extra_fields["ai_analysis_result"] = analysis_data
        metadata_dict["extra_fields"] = extra_fields
        log_record.metadata_json = json.dumps(metadata_dict, ensure_ascii=False, default=str)
        log_record.updated_at = datetime.utcnow()

        db.add(log_record)
        await db.commit()
        await db.refresh(log_record)

        metadata = LogMetadata(**metadata_dict) if metadata_dict else LogMetadata()
        return await self._db_to_pydantic(log_record, metadata)

    async def update_ai_analysis_task(
        self,
        db: AsyncSession,
        log_id: str,
        *,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        query: Optional[str] = None,
        error: Optional[str] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None
    ) -> LogFileInfo:
        """
        更新AI分析任务的元数据（状态/进度/错误）
        """
        log_record = await self.get_by_id(db, log_id)

        if not log_record or log_record.is_deleted:
            raise FileNotFoundError(file_id=log_id)

        metadata_dict: Dict[str, Any] = {}
        try:
            if log_record.metadata_json:
                metadata_dict = json.loads(log_record.metadata_json) or {}
        except Exception:
            metadata_dict = {}

        extra_fields = metadata_dict.get("extra_fields")
        if not isinstance(extra_fields, dict):
            extra_fields = {}

        task_info = extra_fields.get("ai_analysis_task")
        if not isinstance(task_info, dict):
            task_info = {}

        if task_id:
            task_info["task_id"] = task_id
        if status:
            task_info["status"] = status
        if progress is not None:
            task_info["progress"] = float(progress)
        if query:
            task_info["query"] = query
        if error is not None:
            task_info["error"] = error
        if started_at:
            task_info["started_at"] = started_at.isoformat()
        if finished_at:
            task_info["finished_at"] = finished_at.isoformat()

        extra_fields["ai_analysis_task"] = task_info
        metadata_dict["extra_fields"] = extra_fields
        log_record.metadata_json = json.dumps(metadata_dict, ensure_ascii=False, default=str)
        log_record.updated_at = datetime.utcnow()

        db.add(log_record)
        await db.commit()
        await db.refresh(log_record)

        metadata = LogMetadata(**metadata_dict) if metadata_dict else LogMetadata()
        return await self._db_to_pydantic(log_record, metadata)

    async def delete_log(self, db: AsyncSession, log_id: str, hard_delete: bool = False) -> bool:
        """
        删除日志文件（支持软删除和硬删除）
        
        Args:
            db: 数据库会话
            log_id: 日志ID
            hard_delete: 是否硬删除（物理删除文件和数据库记录）
            
        Returns:
            bool: 是否删除成功
        """
        log_record = await self.get_by_id(db, log_id)
        
        if not log_record:
            raise FileNotFoundError(file_id=log_id)
        
        # 检查是否已经被软删除
        if log_record.is_deleted and not hard_delete:
            return True
        
        try:
            if hard_delete:
                # 硬删除：删除文件和数据库记录
                file_path = Path(log_record.file_path)
                if file_path.exists():
                    file_path.unlink()
                    logger.info(f"删除主文件: {file_path}")
                
                # 清理关联的临时处理目录
                self._cleanup_processing_directories(log_record)
                
                # 从数据库删除记录
                await self.delete(db, log_id)
            else:
                # 软删除：只标记为已删除，同时清理物理文件
                # 删除主文件
                file_path = Path(log_record.file_path)
                if file_path.exists():
                    file_path.unlink()
                    logger.info(f"软删除-删除主文件: {file_path}")
                
                # 清理关联的临时处理目录
                self._cleanup_processing_directories(log_record)
                
                # 更新数据库标记
                log_record.is_deleted = True
                log_record.deleted_at = datetime.utcnow()
                db.add(log_record)
                await db.commit()
            
            return True
            
        except Exception as e:
            await db.rollback()
            raise StorageError(f"删除日志失败: {str(e)}")

    async def update_log_status(
        self, 
        db: AsyncSession, 
        log_id: str, 
        status: LogStatus,
        progress: Optional[float] = None,
        error_message: Optional[str] = None
    ) -> LogFileInfo:
        """
        更新日志状态
        
        Args:
            db: 数据库会话
            log_id: 日志ID
            status: 新状态
            progress: 处理进度
            error_message: 错误信息
            
        Returns:
            LogFileInfo: 更新后的日志信息
        """
        logger.info(f"LogService - 更新日志状态: ID={log_id}, 状态={status.value}, 进度={progress}")
        update_data = {"status": status}
        
        if progress is not None:
            update_data["progress"] = progress
        
        if error_message is not None:
            update_data["error_message"] = error_message
        
        if status == LogStatus.COMPLETED:
            update_data["processed_at"] = datetime.utcnow()
            update_data["progress"] = 100.0
        
        log_record = await self.update(db, log_id, **update_data)
        
        if not log_record:
            logger.error(f"LogService - 日志记录不存在: ID={log_id}")
            raise FileNotFoundError(file_id=log_id)
        
        logger.info(f"LogService - 日志状态更新成功: ID={log_id}, 新状态={log_record.status.value}")
        
        # 解析元数据
        metadata = LogMetadata()
        if log_record.metadata_json:
            try:
                metadata_dict = json.loads(log_record.metadata_json)
                metadata = LogMetadata(**metadata_dict)
            except:
                pass
        
        return await self._db_to_pydantic(log_record, metadata)

    async def get_download_path(self, db: AsyncSession, log_id: str) -> str:
        """
        获取文件下载路径
        
        Args:
            db: 数据库会话
            log_id: 日志ID
            
        Returns:
            str: 文件路径
        """
        # 获取日志记录
        record = await self.get_by_id(db, log_id)
        if not record:
            raise FileNotFoundError(filename=log_id)
        
        # 检查文件是否存在
        file_path = Path(record.file_path)
        if not file_path.exists():
            raise FileNotFoundError(filename=record.original_filename)
        
        return str(file_path)

    async def increment_download_count(self, db: AsyncSession, log_id: str) -> LogFileInfo:
        """
        增加下载次数
        
        Args:
            db: 数据库会话
            log_id: 日志ID
            
        Returns:
            LogFileInfo: 更新后的日志信息
        """
        # 获取日志记录
        record = await self.get_by_id(db, log_id)
        if not record:
            raise FileNotFoundError(filename=log_id)
        
        # 增加下载次数
        record.download_count += 1
        record.updated_at = datetime.utcnow()
        
        # 保存到数据库
        await db.commit()
        await db.refresh(record)
        
        # 解析元数据
        metadata = None
        if record.metadata_json:
            try:
                metadata_dict = json.loads(record.metadata_json)
                metadata = LogMetadata(**metadata_dict)
            except (json.JSONDecodeError, TypeError):
                metadata = LogMetadata()
        
        return await self._db_to_pydantic(record, metadata)

    async def batch_delete(
        self, 
        db: AsyncSession, 
        request: BatchDeleteRequest
    ) -> BatchOperationResult:
        """
        批量删除日志 - 改进版本，支持事务处理和详细错误报告
        
        Args:
            db: 数据库会话
            request: 批量删除请求
            
        Returns:
            BatchOperationResult: 操作结果
        """
        result = BatchOperationResult()
        
        # 首先批量查询所有日志记录
        try:
            stmt = select(LogRecord).where(
                LogRecord.id.in_(request.log_ids),
                LogRecord.is_deleted == False
            )
            db_result = await db.execute(stmt)
            log_records = db_result.scalars().all()
            
            # 创建ID到记录的映射
            records_map = {record.id: record for record in log_records}
            
            # 检查哪些ID不存在
            found_ids = set(records_map.keys())
            requested_ids = set(request.log_ids)
            missing_ids = requested_ids - found_ids
            
            # 为不存在的ID添加错误信息
            for missing_id in missing_ids:
                result.failed_count += 1
                result.failed_ids.append(missing_id)
                result.errors[missing_id] = "日志记录不存在"
                result.failed_logs.append({
                    "log_id": missing_id,
                    "reason": "日志记录不存在"
                })
            
        except Exception as e:
            # 如果查询失败，所有操作都失败
            for log_id in request.log_ids:
                result.failed_count += 1
                result.failed_ids.append(log_id)
                result.errors[log_id] = f"数据库查询失败: {str(e)}"
                result.failed_logs.append({
                    "log_id": log_id,
                    "reason": f"数据库查询失败: {str(e)}"
                })
            return result
        
        # 使用事务处理批量删除
        try:
            # 批量处理文件删除和数据库更新
            for log_id in found_ids:
                try:
                    record = records_map[log_id]
                    
                    # 删除物理文件
                    if request.force:
                        # 硬删除：删除物理文件和数据库记录
                        file_path = Path(record.file_path)
                        if file_path.exists():
                            file_path.unlink()
                            logger.info(f"批量删除-硬删除主文件: {file_path}")
                        
                        # 清理关联的临时处理目录
                        self._cleanup_processing_directories(record)
                        
                        # 删除数据库记录
                        await db.delete(record)
                    else:
                        # 软删除：只标记为已删除，同时清理物理文件
                        # 删除主文件
                        file_path = Path(record.file_path)
                        if file_path.exists():
                            file_path.unlink()
                            logger.info(f"批量删除-软删除主文件: {file_path}")
                        
                        # 清理关联的临时处理目录
                        self._cleanup_processing_directories(record)
                        
                        # 更新数据库标记
                        record.is_deleted = True
                        record.deleted_at = datetime.utcnow()
                    
                    result.success_count += 1
                    result.deleted_count += 1
                    result.success_ids.append(log_id)
                    
                except Exception as e:
                    result.failed_count += 1
                    result.failed_ids.append(log_id)
                    error_msg = f"删除失败: {str(e)}"
                    result.errors[log_id] = error_msg
                    result.failed_logs.append({
                        "log_id": log_id,
                        "reason": error_msg
                    })
                    
                    # 如果是硬删除模式下的文件删除失败，回滚事务
                    if request.force:
                        await db.rollback()
                        raise BatchOperationError(f"批量删除失败: {error_msg}")
            
            # 提交事务
            await db.commit()
            
        except Exception as e:
            # 事务回滚
            await db.rollback()
            
            # 如果是事务级别的错误，将所有成功的操作标记为失败
            for log_id in result.success_ids:
                result.failed_count += 1
                result.failed_ids.append(log_id)
                result.errors[log_id] = f"事务回滚: {str(e)}"
                result.failed_logs.append({
                    "log_id": log_id,
                    "reason": f"事务回滚: {str(e)}"
                })
            
            # 重置成功计数
            result.success_count = 0
            result.deleted_count = 0
            result.success_ids = []
        
        return result

    async def batch_download(
        self, 
        db: AsyncSession, 
        request: BatchDownloadRequest
    ) -> str:
        """
        批量下载日志 - 改进版本，支持流式zip文件生成
        
        Args:
            db: 数据库会话
            request: 批量下载请求
            
        Returns:
            str: 压缩文件路径
        """
        try:
            # 批量查询所有日志记录
            stmt = select(LogRecord).where(
                LogRecord.id.in_(request.log_ids),
                LogRecord.is_deleted == False
            )
            db_result = await db.execute(stmt)
            log_records = db_result.scalars().all()
            
            if not log_records:
                raise FileNotFoundError("没有找到有效的日志文件")
            
            # 创建临时压缩文件
            download_id = str(uuid.uuid4())
            zip_filename = f"logs_batch_{download_id}.zip"
            zip_path = self.downloads_storage_path / zip_filename
            
            # 使用流式压缩避免内存溢出
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipf:
                processed_count = 0
                
                for log_record in log_records:
                    try:
                        file_path = Path(log_record.file_path)
                        
                        if not file_path.exists():
                            # 如果文件不存在，创建一个错误信息文件
                            error_filename = f"{log_record.original_filename}.error.txt"
                            error_content = f"错误: 文件 {log_record.original_filename} 不存在\n"
                            error_content += f"原始路径: {log_record.file_path}\n"
                            error_content += f"日志ID: {log_record.id}\n"
                            zipf.writestr(error_filename, error_content)
                            continue
                        
                        # 生成唯一的文件名避免冲突
                        base_name = log_record.original_filename
                        name, ext = os.path.splitext(base_name)
                        unique_filename = f"{name}_{log_record.id[:8]}{ext}"
                        
                        # 流式添加文件到压缩包
                        with open(file_path, 'rb') as f:
                            # 分块读取文件，避免大文件占用过多内存
                            with zipf.open(unique_filename, 'w') as zf:
                                while True:
                                    chunk = f.read(8192)  # 8KB chunks
                                    if not chunk:
                                        break
                                    zf.write(chunk)
                        
                        # 如果需要包含元数据
                        if request.include_metadata:
                            metadata_content = await self._create_metadata_content(log_record)
                            metadata_filename = f"{name}_{log_record.id[:8]}.metadata.json"
                            zipf.writestr(metadata_filename, metadata_content)
                        
                        processed_count += 1
                        
                        # 更新下载计数
                        log_record.download_count += 1
                        
                    except Exception as e:
                        # 为单个文件错误创建错误信息文件
                        error_filename = f"{log_record.original_filename}.error.txt"
                        error_content = f"处理文件时发生错误: {str(e)}\n"
                        error_content += f"文件: {log_record.original_filename}\n"
                        error_content += f"日志ID: {log_record.id}\n"
                        zipf.writestr(error_filename, error_content)
                        continue
                
                # 添加批量下载信息文件
                batch_info = {
                    "download_id": download_id,
                    "requested_files": len(request.log_ids),
                    "processed_files": processed_count,
                    "download_time": datetime.utcnow().isoformat(),
                    "include_metadata": request.include_metadata,
                    "compress": request.compress
                }
                zipf.writestr("batch_download_info.json", json.dumps(batch_info, indent=2))
            
            # 提交数据库更改（下载计数）
            await db.commit()
            
            return str(zip_path)
            
        except Exception as e:
            await db.rollback()
            raise FileProcessingError(f"批量下载失败: {str(e)}")

    async def batch_download_stream(
        self, 
        db: AsyncSession, 
        request: BatchDownloadRequest
    ):
        """
        流式批量下载 - 生成器函数，用于API流式响应
        
        Args:
            db: 数据库会话
            request: 批量下载请求
            
        Yields:
            bytes: zip文件数据块
        """
        import io
        
        try:
            # 批量查询所有日志记录
            stmt = select(LogRecord).where(
                LogRecord.id.in_(request.log_ids),
                LogRecord.is_deleted == False
            )
            db_result = await db.execute(stmt)
            log_records = db_result.scalars().all()
            
            if not log_records:
                raise FileNotFoundError("没有找到有效的日志文件")
            
            # 创建内存中的zip文件
            zip_buffer = io.BytesIO()
            
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipf:
                for log_record in log_records:
                    try:
                        file_path = Path(log_record.file_path)
                        
                        if not file_path.exists():
                            continue
                        
                        # 生成唯一的文件名
                        base_name = log_record.original_filename
                        name, ext = os.path.splitext(base_name)
                        unique_filename = f"{name}_{log_record.id[:8]}{ext}"
                        
                        # 添加文件到zip
                        zipf.write(file_path, unique_filename)
                        
                        # 如果需要包含元数据
                        if request.include_metadata:
                            metadata_content = await self._create_metadata_content(log_record)
                            metadata_filename = f"{name}_{log_record.id[:8]}.metadata.json"
                            zipf.writestr(metadata_filename, metadata_content)
                        
                        # 更新下载计数
                        log_record.download_count += 1
                        
                    except Exception:
                        continue
            
            # 提交数据库更改
            await db.commit()
            
            # 返回zip文件内容
            zip_buffer.seek(0)
            return zip_buffer.getvalue()
            
        except Exception as e:
            await db.rollback()
            raise FileProcessingError(f"流式批量下载失败: {str(e)}")

    async def cleanup_expired_logs(self, db: AsyncSession) -> int:
        """
        清理过期日志（可以基于创建时间或其他条件）
        
        Args:
            db: 数据库会话
            
        Returns:
            int: 清理的文件数量
        """
        # 这里可以实现清理逻辑，比如删除超过30天的日志
        cutoff_date = datetime.utcnow() - timedelta(days=30)
        
        # 查找过期的日志
        query = select(LogRecord).where(LogRecord.created_at < cutoff_date)
        result = await db.execute(query)
        expired_logs = result.scalars().all()
        
        cleaned_count = 0
        for log_record in expired_logs:
            try:
                # 删除文件
                file_path = Path(log_record.file_path)
                if file_path.exists():
                    file_path.unlink()
                
                # 删除数据库记录
                await self.delete(db, log_record.id)
                cleaned_count += 1
            except Exception:
                # 忽略删除错误，继续处理其他文件
                pass
        
        return cleaned_count

    # 私有方法
    async def _save_file(self, file: UploadFile, file_path: Path):
        """保存上传的文件"""
        try:
            with open(file_path, "wb") as buffer:
                # 重置文件指针
                await file.seek(0)
                content = await file.read()
                buffer.write(content)
        except Exception as e:
            raise StorageError(f"保存文件失败: {str(e)}")

    async def _db_to_pydantic(self, record: LogRecord, metadata: Optional[LogMetadata] = None) -> LogFileInfo:
        """将数据库记录转换为Pydantic模型"""
        ai_analysis_result = None
        ai_analysis_task: Dict[str, Any] = {}
        try:
            if metadata and metadata.extra_fields:
                ai_analysis_result = metadata.extra_fields.get("ai_analysis_result")
                raw_task = metadata.extra_fields.get("ai_analysis_task")
                if isinstance(raw_task, dict):
                    ai_analysis_task = raw_task
        except Exception:
            ai_analysis_result = None

        metadata_payload = metadata or LogMetadata()
        try:
            if getattr(metadata_payload, "extra_fields", None) and isinstance(metadata_payload.extra_fields, dict):
                metadata_payload.extra_fields = {
                    k: v for k, v in metadata_payload.extra_fields.items()
                    if k != "ai_analysis_result"
                }
        except Exception:
            pass

        return LogFileInfo(
            id=record.id,
            filename=record.filename,
            original_filename=record.original_filename,
            file_size=record.file_size,
            file_path=record.file_path,
            log_type=record.log_type,
            status=record.status,
            progress=record.progress,
            created_at=record.created_at,
            updated_at=record.updated_at,
            processed_at=record.processed_at,
            checksum=record.checksum,
            mime_type=record.mime_type,
            log_level=record.log_level,
            metadata=metadata_payload,
            error_message=record.error_message,
            download_count=record.download_count,
            issue_description=record.issue_description,
            ai_analysis_result=ai_analysis_result,
            ai_analysis_task_id=ai_analysis_task.get("task_id"),
            ai_analysis_status=ai_analysis_task.get("status"),
            ai_analysis_progress=ai_analysis_task.get("progress"),
            ai_analysis_error=ai_analysis_task.get("error"),
            ai_analysis_query=ai_analysis_task.get("query"),
            ai_analysis_started_at=ai_analysis_task.get("started_at"),
            ai_analysis_finished_at=ai_analysis_task.get("finished_at"),
        )

    async def _create_metadata_content(self, log_record: LogRecord) -> str:
        """创建元数据内容"""
        metadata = {
            "id": log_record.id,
            "original_filename": log_record.original_filename,
            "file_size": log_record.file_size,
            "mime_type": log_record.mime_type,
            "checksum": log_record.checksum,
            "status": log_record.status.value,
            "log_type": log_record.log_type.value,
            "log_level": log_record.log_level.value if log_record.log_level else None,
            "progress": log_record.progress,
            "created_at": log_record.created_at.isoformat(),
            "updated_at": log_record.updated_at.isoformat(),
            "processed_at": log_record.processed_at.isoformat() if log_record.processed_at else None,
            "error_message": log_record.error_message
        }
        
        # 添加解析后的元数据
        if log_record.metadata_json:
            try:
                parsed_metadata = json.loads(log_record.metadata_json)
                metadata["metadata"] = parsed_metadata
            except:
                pass
        
        return json.dumps(metadata, indent=2, ensure_ascii=False)

    def _cleanup_processing_directories(self, log_record: LogRecord):
        """
        清理与日志记录相关的所有临时处理目录
        
        Args:
            log_record: 日志记录
        """
        try:
            # 1. 清理基于 task_id 的临时处理目录
            if log_record.task_id:
                processing_dir = Path(settings.temp_dir) / f"processing_{log_record.task_id}"
                if processing_dir.exists():
                    shutil.rmtree(processing_dir, ignore_errors=True)
                    logger.info(f"清理临时处理目录: {processing_dir}")
            
            # 2. 清理所有可能的 processing_* 目录（针对 task_id 可能变更的情况）
            # 使用 glob 查找所有匹配的目录
            temp_base = Path(settings.temp_dir)
            for processing_dir in temp_base.glob("processing_*"):
                try:
                    # 检查目录中是否有与当前日志ID相关的文件
                    # 这样可以避免误删其他正在处理的日志的临时目录
                    if processing_dir.is_dir():
                        # 简单策略：如果目录存在时间超过24小时，或者为空，则删除
                        dir_mtime = processing_dir.stat().st_mtime
                        age_hours = (datetime.utcnow().timestamp() - dir_mtime) / 3600
                        
                        # 检查目录是否为空或过期
                        is_empty = not any(processing_dir.iterdir())
                        is_old = age_hours > 24
                        
                        if is_empty or is_old:
                            shutil.rmtree(processing_dir, ignore_errors=True)
                            logger.info(f"清理过期/空的临时处理目录: {processing_dir} (年龄: {age_hours:.1f}小时, 空目录: {is_empty})")
                except Exception as e:
                    logger.warning(f"清理临时处理目录失败: {processing_dir}, 错误: {e}")
            
        except Exception as e:
            logger.warning(f"清理临时处理目录时发生错误: {e}")

    async def _check_and_trigger_protocol_stack_processing(self, log_record: LogRecord):
        """
        检查是否为协议栈日志，如果是则自动触发处理
        
        Args:
            log_record: 日志记录
        """
        try:
            # 检查文件名是否包含"stack"关键字，或者日志类型为FULL（全量日志）
            if "stack" in log_record.original_filename.lower() or log_record.log_type == LogType.FULL:
                logger.info(f"LogService - 检测到协议栈日志，准备启动处理任务: {log_record.original_filename}")
                # 动态导入避免循环导入
                from app.tasks.log_processing import process_protocol_stack_log
                
                # 启动异步任务，由于数据库事务已经立即提交，只需要很短的延迟
                task_result = process_protocol_stack_log.apply_async(
                    args=[log_record.id],
                    countdown=1  # 延迟1秒执行，给数据库一点时间确保在所有连接中可见
                )
                logger.info(f"LogService - 协议栈处理任务已启动: 任务ID={task_result.id}, 日志ID={log_record.id}, 延迟执行=1秒")
                    
        except Exception as e:
            # 记录错误但不影响文件上传流程
            logger.error(f"LogService - 触发协议栈处理失败: 日志ID={log_record.id}, 错误: {str(e)}")


# 创建全局服务实例
log_service = LogService()
