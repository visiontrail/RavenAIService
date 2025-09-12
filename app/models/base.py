"""
基础数据模型
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class BaseResponse(BaseModel):
    """基础响应模型"""
    success: bool = True
    message: str = "操作成功"
    timestamp: datetime = Field(default_factory=datetime.now)


class ErrorResponse(BaseResponse):
    """错误响应模型"""
    success: bool = False
    error_code: Optional[str] = None
    detail: Optional[str] = None


class PaginationParams(BaseModel):
    """分页参数模型"""
    page: int = Field(1, ge=1, description="页码")
    size: int = Field(10, ge=1, le=100, description="每页大小")
    
    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class PaginatedResponse(BaseResponse):
    """分页响应模型"""
    total: int = 0
    page: int = 1
    size: int = 10
    pages: int = 0
    
    def __init__(self, **data):
        super().__init__(**data)
        if self.total > 0 and self.size > 0:
            self.pages = (self.total + self.size - 1) // self.size
