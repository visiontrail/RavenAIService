"""
健康检查API路由
"""

import os
import psutil
from datetime import datetime
from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings


class HealthResponse(BaseModel):
    """健康检查响应模型"""
    status: str
    timestamp: datetime
    version: str
    environment: str
    system_info: dict


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
