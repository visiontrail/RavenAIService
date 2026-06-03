"""
自定义异常类和全局异常处理器
"""

import logging
import traceback
from typing import Union, Dict, Any
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import ValidationError

from app.models.base import ErrorResponse

logger = logging.getLogger(__name__)


class LogServiceException(Exception):
    """日志服务基础异常"""
    def __init__(
        self,
        message: str,
        error_code: str = "LOG_SERVICE_ERROR",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail: str = None
    ):
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.detail = detail
        super().__init__(self.message)


class FileNotFoundError(LogServiceException):
    """文件未找到异常"""
    def __init__(self, file_id: str = None, filename: str = None):
        if file_id:
            message = f"文件未找到: ID={file_id}"
        elif filename:
            message = f"文件未找到: {filename}"
        else:
            message = "请求的文件未找到"
        
        super().__init__(
            message=message,
            error_code="FILE_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND
        )


class FileUploadError(LogServiceException):
    """文件上传异常"""
    def __init__(self, message: str, detail: str = None):
        super().__init__(
            message=f"文件上传失败: {message}",
            error_code="FILE_UPLOAD_ERROR",
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail
        )


class FileSizeExceededError(LogServiceException):
    """文件大小超限异常"""
    def __init__(self, file_size: int, max_size: int, message: str = None):
        super().__init__(
            message=message or f"文件大小超出限制: {file_size / 1024 / 1024:.1f}MB > {max_size / 1024 / 1024:.1f}MB",
            error_code="FILE_SIZE_EXCEEDED",
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        )


class UnsupportedFileTypeError(LogServiceException):
    """不支持的文件类型异常"""
    def __init__(self, file_type: str, supported_types: list, message: str = None):
        super().__init__(
            message=message or f"不支持的文件类型: {file_type}，支持的类型: {', '.join(supported_types)}",
            error_code="UNSUPPORTED_FILE_TYPE",
            status_code=status.HTTP_400_BAD_REQUEST
        )


class FileProcessingError(LogServiceException):
    """文件处理异常"""
    def __init__(self, message: str, detail: str = None):
        super().__init__(
            message=f"文件处理失败: {message}",
            error_code="FILE_PROCESSING_ERROR",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail
        )


class StorageError(LogServiceException):
    """存储异常"""
    def __init__(self, message: str, detail: str = None):
        super().__init__(
            message=f"存储操作失败: {message}",
            error_code="STORAGE_ERROR",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail
        )


class ValidationError(LogServiceException):
    """数据验证异常"""
    def __init__(self, message: str, field: str = None):
        if field:
            message = f"字段 '{field}' 验证失败: {message}"
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
        )


class AuthenticationError(LogServiceException):
    """认证异常"""
    def __init__(self, message: str = "身份验证失败"):
        super().__init__(
            message=message,
            error_code="AUTHENTICATION_ERROR",
            status_code=status.HTTP_401_UNAUTHORIZED
        )


class AuthorizationError(LogServiceException):
    """授权异常"""
    def __init__(self, message: str = "权限不足"):
        super().__init__(
            message=message,
            error_code="AUTHORIZATION_ERROR",
            status_code=status.HTTP_403_FORBIDDEN
        )


class RateLimitError(LogServiceException):
    """频率限制异常"""
    def __init__(self, message: str = "请求频率过高，请稍后重试"):
        super().__init__(
            message=message,
            error_code="RATE_LIMIT_ERROR",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS
        )


class BatchOperationError(LogServiceException):
    """批量操作异常"""
    def __init__(self, message: str, failed_ids: list = None):
        super().__init__(
            message=f"批量操作失败: {message}",
            error_code="BATCH_OPERATION_ERROR",
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"失败的ID: {failed_ids}" if failed_ids else None
        )


def create_error_response(
    message: str,
    error_code: str = "INTERNAL_ERROR",
    detail: str = None,
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
) -> JSONResponse:
    """创建错误响应"""
    error_response = ErrorResponse(
        message=message,
        error_code=error_code,
        detail=detail
    )
    
    return JSONResponse(
        status_code=status_code,
        content=error_response.model_dump(mode='json')
    )


async def log_service_exception_handler(request: Request, exc: LogServiceException) -> JSONResponse:
    """日志服务异常处理器"""
    logger.error(
        f"LogServiceException: {exc.message}",
        extra={
            "error_code": exc.error_code,
            "status_code": exc.status_code,
            "detail": exc.detail,
            "url": str(request.url),
            "method": request.method
        }
    )
    
    return create_error_response(
        message=exc.message,
        error_code=exc.error_code,
        detail=exc.detail,
        status_code=exc.status_code
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """HTTP异常处理器"""
    extra = {
        "status_code": exc.status_code,
        "url": str(request.url),
        "method": request.method
    }
    if exc.headers:
        extra["headers"] = exc.headers

    logger.warning(
        f"HTTPException: {exc.detail}",
        extra=extra
    )
    
    return create_error_response(
        message=exc.detail or "HTTP错误",
        error_code="HTTP_ERROR",
        status_code=exc.status_code
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """请求验证异常处理器"""
    errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"])
        message = error["msg"]
        errors.append(f"{field}: {message}")
    
    error_message = "请求参数验证失败"
    detail = "; ".join(errors)
    
    logger.warning(
        f"ValidationError: {error_message}",
        extra={
            "detail": detail,
            "url": str(request.url),
            "method": request.method
        }
    )
    
    return create_error_response(
        message=error_message,
        error_code="VALIDATION_ERROR",
        detail=detail,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """通用异常处理器"""
    error_id = f"error_{id(exc)}"
    
    logger.error(
        f"Unhandled exception: {str(exc)}",
        extra={
            "error_id": error_id,
            "url": str(request.url),
            "method": request.method,
            "traceback": traceback.format_exc()
        }
    )
    
    return create_error_response(
        message="服务器内部错误",
        error_code="INTERNAL_ERROR",
        detail=f"错误ID: {error_id}",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
    )


def register_exception_handlers(app):
    """注册所有异常处理器"""
    app.add_exception_handler(LogServiceException, log_service_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
