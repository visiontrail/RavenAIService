"""
日志服务模块
处理所有日志相关的业务逻辑
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

from app.config import settings
from app.models.log import (
    LogFileInfo, LogUploadRequest, LogListRequest, BatchDeleteRequest,
    BatchDownloadRequest, LogStatus, LogType, LogLevel, LogMetadata,
    BatchOperationResult
)
from app.exceptions import (
    FileNotFoundError, FileUploadError, StorageError,
    FileProcessingError, BatchOperationError
)
from app.utils.validation import file_validator


class LogService:
    """日志服务类"""
    
    def __init__(self):
        self.storage_path = Path(settings.temp_dir)
        self.logs_storage_path = self.storage_path / "logs"
        self.downloads_storage_path = self.storage_path / "downloads"
        
        # 确保存储目录存在
        self.logs_storage_path.mkdir(parents=True, exist_ok=True)
        self.downloads_storage_path.mkdir(parents=True, exist_ok=True)
        
        # 模拟数据库存储（实际项目中应该使用真实数据库）
        self.logs_db: Dict[str, LogFileInfo] = {}

    async def upload_log(self, file: UploadFile, request: LogUploadRequest) -> LogFileInfo:
        """
        上传日志文件
        
        Args:
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
            file_type = self._get_file_extension(original_filename)
            
            # 计算过期时间
            expires_at = None
            if request.expires_in_days:
                expires_at = datetime.now() + timedelta(days=request.expires_in_days)
            
            # 创建日志文件信息
            log_info = LogFileInfo(
                id=file_id,
                filename=stored_filename,
                original_filename=original_filename,
                file_size=file_size,
                file_type=file_type,
                mime_type=mime_type,
                file_path=str(file_path),
                checksum=checksum,
                status=LogStatus.STORED,
                log_type=request.log_type,
                log_level=request.log_level,
                metadata=request.metadata or LogMetadata(),
                expires_at=expires_at
            )
            
            # 保存到模拟数据库
            self.logs_db[file_id] = log_info
            
            # 保存元数据到文件
            await self._save_metadata(file_id, log_info)
            
            return log_info
            
        except Exception as e:
            # 清理已创建的文件
            if 'file_path' in locals() and file_path.exists():
                file_path.unlink()
            
            if isinstance(e, (FileUploadError, StorageError)):
                raise e
            else:
                raise FileUploadError(f"上传失败: {str(e)}")

    async def get_log_list(self, request: LogListRequest) -> Tuple[List[LogFileInfo], int]:
        """
        获取日志列表
        
        Args:
            request: 查询请求参数
            
        Returns:
            Tuple[List[LogFileInfo], int]: (日志列表, 总数)
        """
        try:
            # 从模拟数据库获取所有日志
            all_logs = list(self.logs_db.values())
            
            # 过滤逻辑
            filtered_logs = await self._filter_logs(all_logs, request)
            
            # 排序（按上传时间倒序）
            filtered_logs.sort(key=lambda x: x.upload_time, reverse=True)
            
            # 分页
            total = len(filtered_logs)
            start_idx = (request.page - 1) * request.size
            end_idx = start_idx + request.size
            paginated_logs = filtered_logs[start_idx:end_idx]
            
            return paginated_logs, total
            
        except Exception as e:
            raise StorageError(f"获取日志列表失败: {str(e)}")

    async def get_log_detail(self, log_id: str) -> LogFileInfo:
        """
        获取日志详情
        
        Args:
            log_id: 日志ID
            
        Returns:
            LogFileInfo: 日志详情
        """
        if log_id not in self.logs_db:
            raise FileNotFoundError(file_id=log_id)
        
        log_info = self.logs_db[log_id]
        
        # 检查文件是否存在
        if not Path(log_info.file_path).exists():
            # 更新状态为已删除
            log_info.status = LogStatus.DELETED
            raise FileNotFoundError(file_id=log_id)
        
        return log_info

    async def delete_log(self, log_id: str) -> bool:
        """
        删除日志文件
        
        Args:
            log_id: 日志ID
            
        Returns:
            bool: 是否删除成功
        """
        if log_id not in self.logs_db:
            raise FileNotFoundError(file_id=log_id)
        
        try:
            log_info = self.logs_db[log_id]
            
            # 删除文件
            file_path = Path(log_info.file_path)
            if file_path.exists():
                file_path.unlink()
            
            # 删除元数据文件
            metadata_path = self._get_metadata_path(log_id)
            if metadata_path.exists():
                metadata_path.unlink()
            
            # 从数据库删除
            del self.logs_db[log_id]
            
            return True
            
        except Exception as e:
            raise StorageError(f"删除日志失败: {str(e)}")

    async def get_download_path(self, log_id: str) -> str:
        """
        获取日志下载路径
        
        Args:
            log_id: 日志ID
            
        Returns:
            str: 文件路径
        """
        if log_id not in self.logs_db:
            raise FileNotFoundError(file_id=log_id)
        
        log_info = self.logs_db[log_id]
        file_path = Path(log_info.file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(file_id=log_id)
        
        return str(file_path)

    async def batch_delete(self, request: BatchDeleteRequest) -> BatchOperationResult:
        """
        批量删除日志
        
        Args:
            request: 批量删除请求
            
        Returns:
            BatchOperationResult: 操作结果
        """
        result = BatchOperationResult()
        
        for log_id in request.log_ids:
            try:
                await self.delete_log(log_id)
                result.success_count += 1
                result.success_ids.append(log_id)
                
            except Exception as e:
                result.failed_count += 1
                result.failed_ids.append(log_id)
                result.errors[log_id] = str(e)
        
        return result

    async def batch_download(self, request: BatchDownloadRequest) -> str:
        """
        批量下载日志
        
        Args:
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
                    if log_id not in self.logs_db:
                        continue
                    
                    log_info = self.logs_db[log_id]
                    file_path = Path(log_info.file_path)
                    
                    if file_path.exists():
                        # 添加文件到压缩包
                        zipf.write(file_path, log_info.original_filename)
                        
                        # 如果需要包含元数据
                        if request.include_metadata:
                            metadata_content = self._create_metadata_content(log_info)
                            metadata_filename = f"{log_info.original_filename}.metadata.json"
                            zipf.writestr(metadata_filename, metadata_content)
            
            return str(zip_path)
            
        except Exception as e:
            raise FileProcessingError(f"批量下载失败: {str(e)}")

    async def cleanup_expired_logs(self) -> int:
        """
        清理过期日志
        
        Returns:
            int: 清理的文件数量
        """
        cleaned_count = 0
        current_time = datetime.now()
        expired_ids = []
        
        for log_id, log_info in self.logs_db.items():
            if log_info.expires_at and log_info.expires_at <= current_time:
                expired_ids.append(log_id)
        
        for log_id in expired_ids:
            try:
                await self.delete_log(log_id)
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
                content = await file.read()
                buffer.write(content)
        except Exception as e:
            raise StorageError(f"保存文件失败: {str(e)}")

    async def _save_metadata(self, file_id: str, log_info: LogFileInfo):
        """保存文件元数据"""
        try:
            metadata_path = self._get_metadata_path(file_id)
            metadata_content = log_info.model_dump_json(indent=2)
            
            with open(metadata_path, "w", encoding="utf-8") as f:
                f.write(metadata_content)
        except Exception as e:
            raise StorageError(f"保存元数据失败: {str(e)}")

    def _get_metadata_path(self, file_id: str) -> Path:
        """获取元数据文件路径"""
        return self.logs_storage_path / f"{file_id}.metadata.json"

    def _get_file_extension(self, filename: str) -> str:
        """获取文件扩展名"""
        if '.' not in filename:
            return "unknown"
        return filename.split('.')[-1].lower()

    async def _filter_logs(self, logs: List[LogFileInfo], request: LogListRequest) -> List[LogFileInfo]:
        """过滤日志列表"""
        filtered = logs
        
        # 按类型过滤
        if request.log_type:
            filtered = [log for log in filtered if log.log_type == request.log_type]
        
        # 按级别过滤
        if request.log_level:
            filtered = [log for log in filtered if log.log_level == request.log_level]
        
        # 按状态过滤
        if request.status:
            filtered = [log for log in filtered if log.status == request.status]
        
        # 按时间范围过滤
        if request.start_time:
            filtered = [log for log in filtered if log.upload_time >= request.start_time]
        
        if request.end_time:
            filtered = [log for log in filtered if log.upload_time <= request.end_time]
        
        # 按搜索关键词过滤
        if request.search:
            keyword = request.search.lower()
            filtered = [
                log for log in filtered
                if keyword in log.original_filename.lower() or
                   (keyword in log.metadata.source.lower() if log.metadata.source else False) or
                   (keyword in log.metadata.service_name.lower() if log.metadata.service_name else False)
            ]
        
        # 按标签过滤
        if request.tags:
            filtered = [
                log for log in filtered
                if any(tag in log.metadata.tags for tag in request.tags)
            ]
        
        return filtered

    def _create_metadata_content(self, log_info: LogFileInfo) -> str:
        """创建元数据内容"""
        metadata = {
            "id": log_info.id,
            "original_filename": log_info.original_filename,
            "file_size": log_info.file_size,
            "file_type": log_info.file_type,
            "mime_type": log_info.mime_type,
            "checksum": log_info.checksum,
            "status": log_info.status,
            "log_type": log_info.log_type,
            "log_level": log_info.log_level,
            "metadata": log_info.metadata.model_dump(),
            "upload_time": log_info.upload_time.isoformat(),
            "last_modified": log_info.last_modified.isoformat(),
            "expires_at": log_info.expires_at.isoformat() if log_info.expires_at else None
        }
        
        return json.dumps(metadata, indent=2, ensure_ascii=False)


# 创建全局服务实例
log_service = LogService()
