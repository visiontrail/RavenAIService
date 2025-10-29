"""
临时目录清理工具
用于清理残留的临时处理目录和文件
"""

import os
import shutil
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List

from app.config import settings

logger = logging.getLogger(__name__)


class TempDirectoryCleaner:
    """临时目录清理器"""
    
    def __init__(self, temp_dir: str = None):
        """
        初始化清理器
        
        Args:
            temp_dir: 临时目录路径，默认使用配置中的路径
        """
        self.temp_dir = Path(temp_dir) if temp_dir else Path(settings.temp_dir)
        
    def cleanup_processing_directories(self, max_age_hours: int = 24) -> Dict[str, any]:
        """
        清理过期的临时处理目录
        
        Args:
            max_age_hours: 最大保留时间（小时），默认24小时
            
        Returns:
            Dict: 清理统计信息
        """
        stats = {
            "total_found": 0,
            "deleted": 0,
            "failed": 0,
            "freed_space_bytes": 0,
            "errors": []
        }
        
        try:
            # 查找所有 processing_* 目录
            processing_dirs = list(self.temp_dir.glob("processing_*"))
            stats["total_found"] = len(processing_dirs)
            
            logger.info(f"发现 {len(processing_dirs)} 个临时处理目录")
            
            for processing_dir in processing_dirs:
                try:
                    if not processing_dir.is_dir():
                        continue
                    
                    # 获取目录修改时间
                    dir_mtime = processing_dir.stat().st_mtime
                    age_hours = (datetime.utcnow().timestamp() - dir_mtime) / 3600
                    
                    # 检查是否应该删除
                    should_delete = False
                    reason = ""
                    
                    # 检查目录是否为空
                    try:
                        is_empty = not any(processing_dir.iterdir())
                        if is_empty:
                            should_delete = True
                            reason = "空目录"
                    except Exception:
                        is_empty = False
                    
                    # 检查是否过期
                    if age_hours > max_age_hours:
                        should_delete = True
                        reason = f"过期 ({age_hours:.1f}小时)"
                    
                    # 执行删除
                    if should_delete:
                        # 计算目录大小
                        dir_size = self._get_directory_size(processing_dir)
                        
                        # 删除目录
                        shutil.rmtree(processing_dir, ignore_errors=True)
                        
                        stats["deleted"] += 1
                        stats["freed_space_bytes"] += dir_size
                        
                        logger.info(
                            f"已清理临时处理目录: {processing_dir.name} "
                            f"(原因: {reason}, 大小: {self._format_size(dir_size)})"
                        )
                        
                except Exception as e:
                    stats["failed"] += 1
                    error_msg = f"清理失败 {processing_dir.name}: {str(e)}"
                    stats["errors"].append(error_msg)
                    logger.warning(error_msg)
            
            logger.info(
                f"临时处理目录清理完成: "
                f"发现 {stats['total_found']} 个, "
                f"已删除 {stats['deleted']} 个, "
                f"失败 {stats['failed']} 个, "
                f"释放空间 {self._format_size(stats['freed_space_bytes'])}"
            )
            
        except Exception as e:
            error_msg = f"清理临时处理目录时发生错误: {str(e)}"
            stats["errors"].append(error_msg)
            logger.error(error_msg)
        
        return stats
    
    def cleanup_old_extracted_files(self, max_age_hours: int = 48) -> Dict[str, any]:
        """
        清理过期的解压文件
        
        Args:
            max_age_hours: 最大保留时间（小时），默认48小时
            
        Returns:
            Dict: 清理统计信息
        """
        stats = {
            "total_found": 0,
            "deleted": 0,
            "failed": 0,
            "freed_space_bytes": 0,
            "errors": []
        }
        
        try:
            # 在临时目录中查找所有 extracted 子目录
            for root, dirs, files in os.walk(self.temp_dir):
                for dir_name in dirs:
                    if dir_name == "extracted":
                        extracted_dir = Path(root) / dir_name
                        stats["total_found"] += 1
                        
                        try:
                            # 获取目录修改时间
                            dir_mtime = extracted_dir.stat().st_mtime
                            age_hours = (datetime.utcnow().timestamp() - dir_mtime) / 3600
                            
                            # 如果过期则删除
                            if age_hours > max_age_hours:
                                dir_size = self._get_directory_size(extracted_dir)
                                shutil.rmtree(extracted_dir, ignore_errors=True)
                                
                                stats["deleted"] += 1
                                stats["freed_space_bytes"] += dir_size
                                
                                logger.info(
                                    f"已清理过期解压目录: {extracted_dir} "
                                    f"(年龄: {age_hours:.1f}小时, 大小: {self._format_size(dir_size)})"
                                )
                        except Exception as e:
                            stats["failed"] += 1
                            error_msg = f"清理失败 {extracted_dir}: {str(e)}"
                            stats["errors"].append(error_msg)
                            logger.warning(error_msg)
            
            logger.info(
                f"解压文件清理完成: "
                f"发现 {stats['total_found']} 个, "
                f"已删除 {stats['deleted']} 个, "
                f"失败 {stats['failed']} 个, "
                f"释放空间 {self._format_size(stats['freed_space_bytes'])}"
            )
            
        except Exception as e:
            error_msg = f"清理解压文件时发生错误: {str(e)}"
            stats["errors"].append(error_msg)
            logger.error(error_msg)
        
        return stats
    
    def cleanup_all(self, processing_max_age: int = 24, extracted_max_age: int = 48) -> Dict[str, any]:
        """
        执行完整清理
        
        Args:
            processing_max_age: 临时处理目录最大保留时间（小时）
            extracted_max_age: 解压文件最大保留时间（小时）
            
        Returns:
            Dict: 综合清理统计信息
        """
        logger.info("开始执行完整临时目录清理...")
        
        # 清理临时处理目录
        processing_stats = self.cleanup_processing_directories(processing_max_age)
        
        # 清理解压文件
        extracted_stats = self.cleanup_old_extracted_files(extracted_max_age)
        
        # 合并统计信息
        combined_stats = {
            "processing_directories": processing_stats,
            "extracted_files": extracted_stats,
            "total_freed_space_bytes": (
                processing_stats["freed_space_bytes"] + 
                extracted_stats["freed_space_bytes"]
            ),
            "total_deleted": (
                processing_stats["deleted"] + 
                extracted_stats["deleted"]
            ),
            "total_failed": (
                processing_stats["failed"] + 
                extracted_stats["failed"]
            )
        }
        
        logger.info(
            f"完整清理完成: "
            f"共删除 {combined_stats['total_deleted']} 个目录/文件, "
            f"释放空间 {self._format_size(combined_stats['total_freed_space_bytes'])}, "
            f"失败 {combined_stats['total_failed']} 个"
        )
        
        return combined_stats
    
    def _get_directory_size(self, directory: Path) -> int:
        """
        计算目录大小
        
        Args:
            directory: 目录路径
            
        Returns:
            int: 目录大小（字节）
        """
        total_size = 0
        try:
            for dirpath, dirnames, filenames in os.walk(directory):
                for filename in filenames:
                    filepath = Path(dirpath) / filename
                    try:
                        total_size += filepath.stat().st_size
                    except Exception:
                        pass
        except Exception:
            pass
        
        return total_size
    
    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """
        格式化文件大小
        
        Args:
            size_bytes: 字节数
            
        Returns:
            str: 格式化后的大小字符串
        """
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.2f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.2f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


# 创建全局实例
temp_directory_cleaner = TempDirectoryCleaner()

