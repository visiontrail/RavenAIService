"""
健康检查API路由
"""

import os
import psutil
from datetime import datetime
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict, Any

from app.config import settings


class HealthResponse(BaseModel):
    """健康检查响应模型"""
    status: str
    timestamp: datetime
    version: str
    environment: str
    system_info: dict


class CleanupResponse(BaseModel):
    """清理响应模型"""
    success: bool
    message: str
    data: Dict[str, Any]


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    健康检查端点
    返回服务状态、系统信息等
    """
    
    # 检查必要目录是否存在
    directories_status = {
        "logs_dir": os.path.exists(settings.logs_dir),
        "temp_dir": os.path.exists(settings.temp_dir),
    }
    
    # 获取系统信息
    system_info = {
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_usage": {
            "total": psutil.disk_usage('/').total,
            "used": psutil.disk_usage('/').used,
            "free": psutil.disk_usage('/').free,
            "percent": psutil.disk_usage('/').percent
        },
        "directories": directories_status
    }
    
    # 确定整体状态
    status = "healthy" if all(directories_status.values()) else "degraded"
    
    return HealthResponse(
        status=status,
        timestamp=datetime.now(),
        version="1.0.0",
        environment=settings.environment,
        system_info=system_info
    )


@router.post("/cleanup/temp-directories", response_model=CleanupResponse)
async def cleanup_temp_directories(
    processing_max_age: int = 24,
    extracted_max_age: int = 48
):
    """
    手动清理临时目录
    
    清理内容：
    - 过期的临时处理目录 (processing_*)
    - 过期的解压文件目录 (extracted)
    
    Args:
        processing_max_age: 临时处理目录最大保留时间（小时），默认24小时
        extracted_max_age: 解压文件最大保留时间（小时），默认48小时
    
    Returns:
        CleanupResponse: 清理结果统计
    """
    from app.utils.temp_directory_cleaner import temp_directory_cleaner
    
    try:
        # 执行清理
        stats = temp_directory_cleaner.cleanup_all(
            processing_max_age=processing_max_age,
            extracted_max_age=extracted_max_age
        )
        
        # 格式化响应消息
        message = (
            f"清理完成: 共删除 {stats['total_deleted']} 个目录/文件, "
            f"释放空间 {temp_directory_cleaner._format_size(stats['total_freed_space_bytes'])}"
        )
        
        if stats['total_failed'] > 0:
            message += f", {stats['total_failed']} 个失败"
        
        return CleanupResponse(
            success=True,
            message=message,
            data=stats
        )
        
    except Exception as e:
        return CleanupResponse(
            success=False,
            message=f"清理失败: {str(e)}",
            data={"error": str(e)}
        )
