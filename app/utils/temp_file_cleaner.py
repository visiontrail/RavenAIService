"""临时文件清理工具
用于T04任务的临时文件管理和清理
"""

import os
import time
import logging
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class TempFileCleaner:
    """临时文件清理器"""
    
    def __init__(self, temp_dir: str = "temp", max_age_hours: int = 24):
        """
        初始化临时文件清理器
        
        Args:
            temp_dir: 临时文件目录
            max_age_hours: 文件最大保留时间（小时）
        """
        self.temp_dir = Path(temp_dir)
        self.max_age_hours = max_age_hours
        self.temp_dir.mkdir(exist_ok=True)
    
    def create_temp_file(self, filename: str) -> Path:
        """创建临时文件路径
        
        Args:
            filename: 文件名
            
        Returns:
            Path: 临时文件路径
        """
        # 确保临时目录存在
        self.temp_dir.mkdir(exist_ok=True)
        
        # 生成带时间戳的临时文件名
        timestamp = int(time.time())
        temp_filename = f"temp_{timestamp}_{filename}"
        
        return self.temp_dir / temp_filename
    
    def cleanup_expired_files(self) -> int:
        """清理过期的临时文件
        
        Returns:
            int: 清理的文件数量
        """
        if not self.temp_dir.exists():
            return 0
        
        cleaned_count = 0
        cutoff_time = time.time() - (self.max_age_hours * 3600)
        
        try:
            for file_path in self.temp_dir.iterdir():
                if file_path.is_file():
                    # 检查文件修改时间
                    if file_path.stat().st_mtime < cutoff_time:
                        try:
                            file_path.unlink()
                            cleaned_count += 1
                            logger.info(f"清理过期临时文件: {file_path}")
                        except Exception as e:
                            logger.error(f"删除临时文件失败 {file_path}: {e}")
                elif file_path.is_dir():
                    # 清理空的临时目录
                    try:
                        if not any(file_path.iterdir()):
                            file_path.rmdir()
                            cleaned_count += 1
                            logger.info(f"清理空临时目录: {file_path}")
                    except Exception as e:
                        logger.error(f"删除临时目录失败 {file_path}: {e}")
        
        except Exception as e:
            logger.error(f"清理临时文件时发生错误: {e}")
        
        return cleaned_count
    
    def cleanup_specific_files(self, file_patterns: List[str]) -> int:
        """清理特定模式的文件
        
        Args:
            file_patterns: 文件名模式列表
            
        Returns:
            int: 清理的文件数量
        """
        if not self.temp_dir.exists():
            return 0
        
        cleaned_count = 0
        
        try:
            for file_path in self.temp_dir.iterdir():
                if file_path.is_file():
                    for pattern in file_patterns:
                        if pattern in file_path.name:
                            try:
                                file_path.unlink()
                                cleaned_count += 1
                                logger.info(f"清理匹配文件: {file_path}")
                                break
                            except Exception as e:
                                logger.error(f"删除文件失败 {file_path}: {e}")
        
        except Exception as e:
            logger.error(f"清理特定文件时发生错误: {e}")
        
        return cleaned_count
    
    def cleanup_all_temp_files(self) -> int:
        """清理所有临时文件
        
        Returns:
            int: 清理的文件数量
        """
        if not self.temp_dir.exists():
            return 0
        
        cleaned_count = 0
        
        try:
            for file_path in self.temp_dir.iterdir():
                try:
                    if file_path.is_file():
                        file_path.unlink()
                        cleaned_count += 1
                    elif file_path.is_dir():
                        import shutil
                        shutil.rmtree(file_path)
                        cleaned_count += 1
                    logger.info(f"清理临时文件/目录: {file_path}")
                except Exception as e:
                    logger.error(f"删除失败 {file_path}: {e}")
        
        except Exception as e:
            logger.error(f"清理所有临时文件时发生错误: {e}")
        
        return cleaned_count
    
    def get_temp_dir_size(self) -> int:
        """获取临时目录大小
        
        Returns:
            int: 目录大小（字节）
        """
        if not self.temp_dir.exists():
            return 0
        
        total_size = 0
        
        try:
            for file_path in self.temp_dir.rglob('*'):
                if file_path.is_file():
                    total_size += file_path.stat().st_size
        except Exception as e:
            logger.error(f"计算临时目录大小时发生错误: {e}")
        
        return total_size
    
    def get_temp_file_count(self) -> int:
        """获取临时文件数量
        
        Returns:
            int: 文件数量
        """
        if not self.temp_dir.exists():
            return 0
        
        file_count = 0
        
        try:
            for file_path in self.temp_dir.iterdir():
                if file_path.is_file():
                    file_count += 1
        except Exception as e:
            logger.error(f"统计临时文件数量时发生错误: {e}")
        
        return file_count
    
    def cleanup_on_upload_failure(self, file_id: str) -> bool:
        """上传失败时清理相关临时文件
        
        Args:
            file_id: 文件ID
            
        Returns:
            bool: 是否成功清理
        """
        try:
            # 清理包含file_id的临时文件
            patterns = [file_id, f"temp_{file_id}", f"{file_id}_"]
            cleaned_count = self.cleanup_specific_files(patterns)
            
            logger.info(f"上传失败清理: 清理了 {cleaned_count} 个相关临时文件")
            return True
            
        except Exception as e:
            logger.error(f"上传失败清理时发生错误: {e}")
            return False


class UploadTempFileManager:
    """上传过程中的临时文件管理器"""
    
    def __init__(self, cleaner: TempFileCleaner):
        self.cleaner = cleaner
        self.active_uploads = {}  # 跟踪活跃的上传
    
    def start_upload(self, file_id: str, filename: str) -> Path:
        """开始上传，创建临时文件
        
        Args:
            file_id: 文件ID
            filename: 文件名
            
        Returns:
            Path: 临时文件路径
        """
        temp_path = self.cleaner.create_temp_file(f"{file_id}_{filename}")
        self.active_uploads[file_id] = {
            "temp_path": temp_path,
            "start_time": time.time(),
            "filename": filename
        }
        return temp_path
    
    def finish_upload(self, file_id: str, final_path: Path) -> bool:
        """完成上传，移动文件到最终位置
        
        Args:
            file_id: 文件ID
            final_path: 最终文件路径
            
        Returns:
            bool: 是否成功
        """
        if file_id not in self.active_uploads:
            return False
        
        try:
            temp_path = self.active_uploads[file_id]["temp_path"]
            
            if temp_path.exists():
                # 移动文件到最终位置
                final_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path.rename(final_path)
                logger.info(f"文件移动成功: {temp_path} -> {final_path}")
            
            # 从活跃上传中移除
            del self.active_uploads[file_id]
            return True
            
        except Exception as e:
            logger.error(f"完成上传时发生错误: {e}")
            self.cancel_upload(file_id)
            return False
    
    def cancel_upload(self, file_id: str) -> bool:
        """取消上传，清理临时文件
        
        Args:
            file_id: 文件ID
            
        Returns:
            bool: 是否成功清理
        """
        if file_id not in self.active_uploads:
            return True
        
        try:
            temp_path = self.active_uploads[file_id]["temp_path"]
            
            if temp_path.exists():
                temp_path.unlink()
                logger.info(f"取消上传，清理临时文件: {temp_path}")
            
            del self.active_uploads[file_id]
            return True
            
        except Exception as e:
            logger.error(f"取消上传时发生错误: {e}")
            return False
    
    def cleanup_stale_uploads(self, max_age_minutes: int = 30) -> int:
        """清理超时的上传
        
        Args:
            max_age_minutes: 最大上传时间（分钟）
            
        Returns:
            int: 清理的上传数量
        """
        current_time = time.time()
        cutoff_time = current_time - (max_age_minutes * 60)
        
        stale_uploads = []
        for file_id, upload_info in self.active_uploads.items():
            if upload_info["start_time"] < cutoff_time:
                stale_uploads.append(file_id)
        
        cleaned_count = 0
        for file_id in stale_uploads:
            if self.cancel_upload(file_id):
                cleaned_count += 1
        
        logger.info(f"清理了 {cleaned_count} 个超时上传")
        return cleaned_count


# 创建全局实例
temp_file_cleaner = TempFileCleaner()
upload_temp_manager = UploadTempFileManager(temp_file_cleaner)