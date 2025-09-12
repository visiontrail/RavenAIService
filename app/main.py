"""
日志暂存服务主应用入口
"""

import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.config import settings
from app.api import health, logs
from app.middleware import RequestLoggingMiddleware, FileSizeLimitMiddleware
from app.exceptions import register_exception_handlers


def setup_logging():
    """设置日志配置"""
    # 确保日志目录存在
    os.makedirs(settings.logs_dir, exist_ok=True)
    
    # 配置日志格式
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # 配置根日志记录器
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format=log_format,
        handlers=[
            logging.FileHandler(settings.log_file_path, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    # 设置uvicorn日志级别
    logging.getLogger("uvicorn").setLevel(getattr(logging, settings.log_level))
    logging.getLogger("uvicorn.access").setLevel(getattr(logging, settings.log_level))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    setup_logging()
    
    # 确保必要的目录存在
    os.makedirs(settings.temp_dir, exist_ok=True)
    os.makedirs(settings.logs_dir, exist_ok=True)
    
    logger = logging.getLogger(__name__)
    logger.info(f"应用启动 - 环境: {settings.environment}")
    logger.info(f"日志级别: {settings.log_level}")
    logger.info(f"最大文件大小: {settings.max_file_size / 1024 / 1024 / 1024:.1f}GB")
    
    yield
    
    # 关闭时执行
    logger.info("应用关闭")


def create_app() -> FastAPI:
    """创建FastAPI应用实例"""
    
    app = FastAPI(
        title="日志暂存服务",
        description="一个用于临时存储和管理日志文件的服务",
        version="1.0.0",
        docs_url="/docs" if settings.environment == "development" else None,
        redoc_url="/redoc" if settings.environment == "development" else None,
        lifespan=lifespan
    )
    
    # 注册异常处理器
    register_exception_handlers(app)
    
    # 添加自定义中间件
    app.add_middleware(RequestLoggingMiddleware, exclude_paths=["/health", "/docs", "/redoc", "/openapi.json"])
    app.add_middleware(FileSizeLimitMiddleware, max_file_size=settings.max_file_size)
    
    # 添加CORS中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_credentials,
        allow_methods=settings.cors_methods,
        allow_headers=settings.cors_headers,
    )
    
    # 添加信任主机中间件（生产环境推荐）
    if settings.environment == "production":
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["*"]  # 生产环境应该配置具体的主机
        )
    
    # 注册路由
    app.include_router(health.router, tags=["健康检查"])
    app.include_router(logs.router, prefix="/api/v1/logs", tags=["日志管理"])
    
    return app


# 创建应用实例
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment == "development",
        log_level=settings.log_level.lower()
    )
