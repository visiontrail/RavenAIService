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
from app.api import ai_chat, device_link
from app.middleware import RequestLoggingMiddleware, FileSizeLimitMiddleware
from app.exceptions import register_exception_handlers
from app.database import init_database, close_database
from app.models.database import db_manager


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
    
    # 初始化数据库
    try:
        await init_database()
        logger.info("数据库初始化成功")
    except Exception as e:
        logger.error(f"数据库初始化失败: {str(e)}")
        raise
    
    # 启动时重试失败的协议栈日志处理
    try:
        from app.services.log_service import log_service
        retriggered = 0
        async for session in db_manager.get_session():
            retriggered = await log_service.retry_failed_protocol_stack_logs(session)
            break
        
        if retriggered > 0:
            logger.info(f"启动检查: 已重新触发 {retriggered} 个失败的协议栈日志处理任务")
        else:
            logger.info("启动检查: 无需重试协议栈日志处理任务")
    except Exception as e:
        logger.error(f"启动检查: 重试失败的协议栈日志处理时出错: {str(e)}")
    
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
    # 注意: 流式响应端点必须排除，因为 BaseHTTPMiddleware 会缓冲整个响应体
    app.add_middleware(RequestLoggingMiddleware, exclude_paths=[
        "/health", "/docs", "/redoc", "/openapi.json",
        "/api/v1/ai-chat/chat/stream"  # 流式响应端点
    ])
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
    app.include_router(ai_chat.router, prefix="/api/v1/ai-chat", tags=["AI Chat"])
    app.include_router(device_link.router, tags=["设备链接"])
    
    # 挂载前端静态站点（若已构建）
    try:
        static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
        if os.path.isdir(static_dir):
            from fastapi.staticfiles import StaticFiles
            from fastapi.responses import FileResponse
            from fastapi import Request, HTTPException
            
            # 挂载静态资源文件
            assets_dir = os.path.join(static_dir, "assets")
            if os.path.isdir(assets_dir):
                app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
            
            # 添加SPA路由处理 - 使用更低优先级的路由
            @app.get("/{full_path:path}", include_in_schema=False)
            async def serve_spa(request: Request, full_path: str):
                # 检查是否是API路径，如果是则跳过（让FastAPI的404处理）
                if (full_path.startswith("api/") or 
                    full_path.startswith("docs") or 
                    full_path.startswith("redoc") or 
                    full_path.startswith("openapi.json") or
                    full_path == "health"):
                    raise HTTPException(status_code=404, detail="Not found")
                
                # 尝试返回静态文件
                file_path = os.path.join(static_dir, full_path)
                if os.path.isfile(file_path):
                    return FileResponse(file_path)
                
                # 对于前端路由，返回index.html
                index_path = os.path.join(static_dir, "index.html")
                if os.path.isfile(index_path):
                    return FileResponse(index_path, media_type="text/html")
                
                # 如果index.html不存在，返回404
                raise HTTPException(status_code=404, detail="Frontend not found")
            
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
