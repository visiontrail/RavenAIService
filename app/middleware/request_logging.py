"""
请求日志中间件
记录所有API请求的详细信息
"""

import time
import json
import logging
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """请求日志中间件"""
    
    def __init__(
        self,
        app: ASGIApp,
        exclude_paths: list = None,
        include_body: bool = False,
        max_body_size: int = 1024,
        log_level: str = "INFO"
    ):
        super().__init__(app)
        self.exclude_paths = exclude_paths or ["/health", "/docs", "/redoc", "/openapi.json", "/vite.svg"]
        self.include_body = include_body
        self.max_body_size = max_body_size
        self.log_level = log_level.upper()

    def _should_log_detailed(self, request: Request) -> bool:
        """判断是否需要记录详细日志"""
        # 静态资源请求不记录详细日志
        static_extensions = ['.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg', '.woff', '.woff2', '.ttf']
        if any(request.url.path.endswith(ext) for ext in static_extensions):
            return False
            
        # GET请求到根路径不记录详细日志
        if request.method == "GET" and request.url.path == "/":
            return False
            
        # API请求记录详细日志
        if request.url.path.startswith("/api/"):
            return True
            
        return False

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """处理请求"""
        # 生成请求ID
        request_id = str(uuid.uuid4())
        
        # 跳过不需要记录的路径
        if any(request.url.path.startswith(path) for path in self.exclude_paths):
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        
        # 记录请求开始时间
        start_time = time.time()
        
        # 判断是否需要详细日志
        detailed_logging = self._should_log_detailed(request)
        
        if detailed_logging:
            # 获取详细请求信息
            request_info = await self._get_detailed_request_info(request, request_id)
            # 记录请求开始日志
            logger.info(f"Request started: {json.dumps(request_info, ensure_ascii=False)}")
        else:
            # 记录简化的请求信息
            simple_info = self._get_simple_request_info(request, request_id)
            logger.debug(f"Request: {json.dumps(simple_info, ensure_ascii=False)}")
        
        # 处理请求
        try:
            response = await call_next(request)
            
            # 计算处理时间
            process_time = time.time() - start_time
            
            if detailed_logging:
                # 记录详细响应信息
                response_info = self._get_detailed_response_info(response, process_time, request_id)
                logger.info(f"Request completed: {json.dumps(response_info, ensure_ascii=False)}")
            else:
                # 记录简化的响应信息
                simple_response = self._get_simple_response_info(response, process_time, request_id)
                logger.debug(f"Response: {json.dumps(simple_response, ensure_ascii=False)}")
            
            # 添加响应头
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time"] = str(process_time)
            
            return response
            
        except Exception as e:
            # 计算处理时间
            process_time = time.time() - start_time
            
            # 记录错误信息（错误总是记录详细信息）
            error_info = {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "error": str(e),
                "error_type": type(e).__name__,
                "process_time": process_time,
                "client_ip": self._get_client_ip(request)
            }
            
            logger.error(f"Request failed: {json.dumps(error_info, ensure_ascii=False)}")
            
            # 重新抛出异常
            raise e

    def _get_simple_request_info(self, request: Request, request_id: str) -> dict:
        """获取简化的请求信息"""
        return {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "client_ip": self._get_client_ip(request),
            "timestamp": time.time()
        }

    def _get_simple_response_info(self, response: Response, process_time: float, request_id: str) -> dict:
        """获取简化的响应信息"""
        return {
            "request_id": request_id,
            "status_code": response.status_code,
            "process_time": process_time
        }

    async def _get_detailed_request_info(self, request: Request, request_id: str) -> dict:
        """获取详细的请求信息"""
        # 基础信息
        request_info = {
            "request_id": request_id,
            "method": request.method,
            "url": str(request.url),
            "path": request.url.path,
            "query_params": dict(request.query_params),
            "client_ip": self._get_client_ip(request),
            "user_agent": request.headers.get("user-agent", ""),
            "timestamp": time.time()
        }
        
        # 只记录关键请求头，不记录所有头信息
        important_headers = {}
        header_keys = ["content-type", "content-length", "authorization", "x-forwarded-for", "x-real-ip"]
        for key in header_keys:
            if key in request.headers:
                important_headers[key] = request.headers[key]
        
        if important_headers:
            request_info["headers"] = important_headers
        
        # 获取请求体（如果启用且不是文件上传）
        if self.include_body and request.method in ["POST", "PUT", "PATCH"]:
            content_type = request.headers.get("content-type", "")
            
            # 不记录文件上传请求的body
            if not content_type.startswith("multipart/form-data"):
                try:
                    body = await request.body()
                    if len(body) <= self.max_body_size:
                        if content_type.startswith("application/json"):
                            request_info["body"] = json.loads(body.decode("utf-8"))
                        else:
                            request_info["body"] = body.decode("utf-8", errors="ignore")
                    else:
                        request_info["body"] = f"<body too large: {len(body)} bytes>"
                except Exception as e:
                    request_info["body"] = f"<failed to read body: {str(e)}>"
        
        return request_info

    def _get_detailed_response_info(self, response: Response, process_time: float, request_id: str) -> dict:
        """获取详细的响应信息"""
        # 只记录关键响应头
        important_headers = {}
        header_keys = ["content-type", "content-length", "location", "set-cookie"]
        for key in header_keys:
            if key in response.headers:
                important_headers[key] = response.headers[key]
        
        response_info = {
            "request_id": request_id,
            "status_code": response.status_code,
            "process_time": process_time,
            "timestamp": time.time()
        }
        
        if important_headers:
            response_info["headers"] = important_headers
            
        return response_info

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端IP地址"""
        # 优先从代理头获取真实IP
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        
        # 获取远程地址
        if hasattr(request.client, "host"):
            return request.client.host
        
        return "unknown"
