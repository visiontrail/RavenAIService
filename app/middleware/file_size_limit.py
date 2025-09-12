"""
文件大小限制中间件
限制上传文件的大小
"""

import logging
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import settings
from app.exceptions import FileSizeExceededError

logger = logging.getLogger(__name__)


class FileSizeLimitMiddleware(BaseHTTPMiddleware):
    """文件大小限制中间件"""
    
    def __init__(
        self,
        app: ASGIApp,
        max_file_size: int = None,
        upload_paths: list = None
    ):
        super().__init__(app)
        self.max_file_size = max_file_size or settings.max_file_size
        self.upload_paths = upload_paths or ["/api/v1/logs/upload"]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """处理请求"""
        # 只检查上传路径
        if not any(request.url.path.startswith(path) for path in self.upload_paths):
            return await call_next(request)
        
        # 只检查包含文件的请求
        content_type = request.headers.get("content-type", "")
        if not content_type.startswith("multipart/form-data"):
            return await call_next(request)
        
        # 检查Content-Length头
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                content_length = int(content_length)
                if content_length > self.max_file_size:
                    logger.warning(
                        f"File size exceeded: {content_length} bytes > {self.max_file_size} bytes",
                        extra={
                            "url": str(request.url),
                            "content_length": content_length,
                            "max_size": self.max_file_size
                        }
                    )
                    raise FileSizeExceededError(content_length, self.max_file_size)
            except ValueError:
                logger.warning(f"Invalid Content-Length header: {content_length}")
        
        return await call_next(request)
