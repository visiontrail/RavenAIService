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
from app.api import health, logs, tasks
from app.middleware import RequestLoggingMiddleware, FileSizeLimitMiddleware
from app.exceptions import register_exception_handlers
from app.database import init_database, close_database


class HealthCheckFilter(logging.Filter):
    """健康检查日志过滤器 - 仅在失败时记录"""
    
    def filter(self, record):
        # 如果是健康检查请求
        if hasattr(record, 'getMessage'):
            message = record.getMessage()
            if '/health' in message:
                # 只记录非200状态码的健康检查请求
                if '200' not in message:
                    return True
                return False
        return True


class AccessLogFilter(logging.Filter):
    """访问日志过滤器 - 减少详细访问记录"""
    
    def filter(self, record):
        if hasattr(record, 'getMessage'):
            message = record.getMessage()
            
            # 过滤健康检查成功请求
            if '/health' in message and '200' in message:
                return False
                
            # 过滤静态资源请求（如果状态码是200或304）
            static_extensions = ['.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg', '.woff', '.woff2', '.ttf']
            if any(ext in message for ext in static_extensions) and ('200' in message or '304' in message):
                return False
                
            # 过滤vite.svg等开发资源
            if 'vite.svg' in message and ('200' in message or '304' in message):
                return False
                
        return True


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
    
    # 为uvicorn.access添加过滤器
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.setLevel(getattr(logging, settings.log_level))
    access_logger.addFilter(AccessLogFilter())
    
    # 为健康检查添加专门的过滤器
    health_filter = HealthCheckFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(health_filter)


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
    
    # 初始化数据库
    try:
        await init_database()
        logger.info("数据库初始化成功")
    except Exception as e:
        logger.error(f"数据库初始化失败: {str(e)}")
        raise
    
    yield
    
    # 关闭时执行
    logger.info("应用关闭")
    try:
        await close_database()
        logger.info("数据库连接已关闭")
    except Exception as e:
        logger.error(f"关闭数据库连接失败: {str(e)}")


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
    app.include_router(tasks.router, prefix="/api/v1", tags=["任务管理"])
    
    # 挂载前端静态站点（若已构建）
    try:
        static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
        if os.path.isdir(static_dir):
            from fastapi.staticfiles import StaticFiles
            app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
            logging.getLogger(__name__).info(f"Mounted frontend at {static_dir}")
        else:
            logging.getLogger(__name__).warning(f"Frontend build directory not found: {static_dir}")
    except Exception as e:
        logging.getLogger(__name__).error(f"Failed to mount frontend: {e}")
    
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
