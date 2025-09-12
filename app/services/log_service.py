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
    BatchOperationResult
)
from app.models.database import get_db
from app.services.base import BaseCRUDService
from app.exceptions import (
    FileNotFoundError, FileUploadError, StorageError,
    FileProcessingError, BatchOperationError
)
from app.utils.validation import file_validator


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
        try:
            # 验证文件
            is_valid, error_msg = await file_validator.validate_upload_file(file)
            if not is_valid:
                raise FileUploadError(error_msg)
            
            # 生成文件ID和存储路径
            file_id = str(uuid.uuid4())
            original_filename = file.filename
            sanitized_filename = file_validator.sanitize_filename(original_filename)
            stored_filename = f"{file_id}_{sanitized_filename}"
            file_path = self.logs_storage_path / stored_filename
            
            # 计算文件校验和
            checksum = await file_validator.calculate_file_checksum(file)
            
            # 保存文件
            await self._save_file(file, file_path)
            
            # 获取文件信息
            file_size = file_path.stat().st_size
            mime_type = file.content_type or "application/octet-stream"
            
            # 将元数据转换为JSON字符串
            metadata_json = None
            if request.metadata:
                metadata_json = request.metadata.model_dump_json()
            
            # 创建数据库记录
            log_record = await self.create(
                db=db,
                id=file_id,
                filename=stored_filename,
                original_filename=original_filename,
                file_size=file_size,
                file_path=str(file_path),
                log_type=request.log_type,
                status=LogStatus.PENDING,
                progress=0.0,
                checksum=checksum,
                mime_type=mime_type,
                log_level=request.log_level,
                metadata_json=metadata_json
            )
            
            # 转换为Pydantic模型
            return await self._db_to_pydantic(log_record, request.metadata)
            
        except Exception as e:
            # 清理已创建的文件
            if 'file_path' in locals() and file_path.exists():
                file_path.unlink()
            
            if isinstance(e, (FileUploadError, StorageError)):
                raise e
            else:
                raise FileUploadError(f"上传失败: {str(e)}")

    async def get_log_list(
        self, 
        db: AsyncSession, 
        request: LogListRequest
    ) -> Tuple[List[LogFileInfo], int]:
        """
        获取日志列表
        
        Args:
            db: 数据库会话
            request: 查询请求参数
            
        Returns:
            Tuple[List[LogFileInfo], int]: (日志列表, 总数)
        """
        try:
            # 构建查询条件
            query = select(LogRecord)
            count_query = select(LogRecord)
            
            # 添加过滤条件
            conditions = []
            
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
            
            if request.search:
                search_pattern = f"%{request.search}%"
                conditions.append(
                    or_(
                        LogRecord.original_filename.ilike(search_pattern),
                        LogRecord.metadata_json.ilike(search_pattern)
                    )
                )
            
            # 应用过滤条件
            if conditions:
                filter_condition = and_(*conditions)
                query = query.where(filter_condition)
                count_query = count_query.where(filter_condition)
            
            # 计算总数
            from sqlalchemy import func
            total_query = select(func.count(LogRecord.id))
            if conditions:
                total_query = total_query.where(and_(*conditions))
            
            total_result = await db.execute(total_query)
            total = total_result.scalar()
            
            # 排序和分页
            query = query.order_by(LogRecord.created_at.desc())
            offset = (request.page - 1) * request.size
            query = query.offset(offset).limit(request.size)
            
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
            
            return log_infos, total
            
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
        
        if not log_record:
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

    async def delete_log(self, db: AsyncSession, log_id: str) -> bool:
        """
        删除日志文件
        
        Args:
            db: 数据库会话
            log_id: 日志ID
            
        Returns:
            bool: 是否删除成功
        """
        log_record = await self.get_by_id(db, log_id)
        
        if not log_record:
            raise FileNotFoundError(file_id=log_id)
        
        try:
            # 删除文件
            file_path = Path(log_record.file_path)
            if file_path.exists():
                file_path.unlink()
            
            # 从数据库删除记录
            await self.delete(db, log_id)
            
            return True
            
        except Exception as e:
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

    async def get_download_path(self, db: AsyncSession, log_id: str) -> str:
        """
        获取日志下载路径
        
        Args:
            db: 数据库会话
            log_id: 日志ID
            
        Returns:
            str: 文件路径
        """
        log_record = await self.get_by_id(db, log_id)
        
        if not log_record:
            raise FileNotFoundError(file_id=log_id)
        
        file_path = Path(log_record.file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(file_id=log_id)
        
        return str(file_path)

    async def batch_delete(
        self, 
        db: AsyncSession, 
        request: BatchDeleteRequest
    ) -> BatchOperationResult:
        """
        批量删除日志
        
        Args:
            db: 数据库会话
            request: 批量删除请求
            
        Returns:
            BatchOperationResult: 操作结果
        """
        result = BatchOperationResult()
        
        for log_id in request.log_ids:
            try:
                await self.delete_log(db, log_id)
                result.success_count += 1
                result.success_ids.append(log_id)
                
            except Exception as e:
                result.failed_count += 1
                result.failed_ids.append(log_id)
                result.errors[log_id] = str(e)
        
        return result

    async def batch_download(
        self, 
        db: AsyncSession, 
        request: BatchDownloadRequest
    ) -> str:
        """
        批量下载日志
        
        Args:
            db: 数据库会话
            request: 批量下载请求
            
        Returns:
            str: 压缩文件路径
        """
        try:
            # 创建临时压缩文件
            download_id = str(uuid.uuid4())
            zip_filename = f"logs_batch_{download_id}.zip"
            zip_path = self.downloads_storage_path / zip_filename
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for log_id in request.log_ids:
                    log_record = await self.get_by_id(db, log_id)
                    
                    if not log_record:
                        continue
                    
                    file_path = Path(log_record.file_path)
                    
                    if file_path.exists():
                        # 添加文件到压缩包
                        zipf.write(file_path, log_record.original_filename)
                        
                        # 如果需要包含元数据
                        if request.include_metadata:
                            metadata_content = await self._create_metadata_content(log_record)
                            metadata_filename = f"{log_record.original_filename}.metadata.json"
                            zipf.writestr(metadata_filename, metadata_content)
            
            return str(zip_path)
            
        except Exception as e:
            raise FileProcessingError(f"批量下载失败: {str(e)}")

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
            metadata=metadata or LogMetadata(),
            error_message=record.error_message
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


# 创建全局服务实例
log_service = LogService()