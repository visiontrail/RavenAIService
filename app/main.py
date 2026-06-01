"""
日志暂存服务主应用入口
"""

import logging
import logging.config
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.config import settings
from app.api import health, logs, tasks, admin, users, packages
from app.api import ai_chat, device_link, metrics as metrics_api
from app.api import admin_metrics
from app.api import project_repos as project_repos_api
from app.api.releases import admin_router as releases_admin_router, public_router as releases_public_router
from app.middleware import RequestLoggingMiddleware, FileSizeLimitMiddleware
from app.exceptions import register_exception_handlers
from app.database import init_database, close_database
from app.models.database import db_manager


def log_critical_routes(app: FastAPI) -> None:
    """在启动日志中打印关键路由，便于线上排查路由是否已生效。"""
    logger = logging.getLogger(__name__)
    tracked_prefixes = ("/admin/releases", "/api/v1/releases")
    route_lines = []

    for route in app.routes:
        path = getattr(route, "path", "")
        methods = sorted(getattr(route, "methods", []) or [])
        if path.startswith(tracked_prefixes):
            route_lines.append(f"{','.join(methods)} {path}")

    if route_lines:
        logger.info("关键路由已注册:\n%s", "\n".join(route_lines))
    else:
        logger.warning("未发现关键发布路由，请检查 releases 路由是否成功注册")


def setup_logging():
    """配置日志：普通日志、调试日志分别落盘，stdout 仅输出普通日志"""
    os.makedirs(settings.logs_dir, exist_ok=True)
    for path in {settings.log_file_path, settings.debug_log_file_path}:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    app_file_level = log_level if log_level > logging.DEBUG else logging.INFO
    console_level_value = getattr(logging, settings.console_log_level.upper(), logging.INFO)
    console_level = max(app_file_level, console_level_value)

    # 动态构建文件处理器，防止日志无限增长占满磁盘
    file_handlers = {
        "app_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": app_file_level,
            "formatter": "standard",
            "filename": settings.log_file_path,
            "encoding": "utf-8",
            "maxBytes": settings.log_file_max_bytes,
            "backupCount": settings.log_file_backup_count,
        }
    }

    if settings.enable_debug_file_log:
        file_handlers["debug_file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "DEBUG",
            "formatter": "standard",
            "filename": settings.debug_log_file_path,
            "encoding": "utf-8",
            "maxBytes": settings.log_file_max_bytes,
            "backupCount": settings.log_file_backup_count,
        }

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {"format": log_format},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": console_level,
                "formatter": "standard",
            },
            **file_handlers,
        },
        "loggers": {
            "uvicorn": {
                "handlers": ["console", "app_file"],
                "level": log_level,
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["console", "app_file"],
                "level": log_level,
                "propagate": False,
            },
            "app.middleware.request_logging": {
                "level": "DEBUG",
                "propagate": True,
            },
            "uvicorn.access": {
                "handlers": ["app_file"],
                "level": logging.INFO,
                "propagate": False,
            },
        },
        "root": {
            "handlers": ["console", "app_file"],
            "level": logging.DEBUG,
        },
    }

    logging.config.dictConfig(logging_config)


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
    log_critical_routes(app)
    
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

    # 标记上次进程未完成的 chat agent run 为 stale，避免侧边栏无限转圈
    try:
        from datetime import datetime
        from sqlalchemy import update
        from app.models.user import ChatAgentRun

        async for session in db_manager.get_session():
            stmt = (
                update(ChatAgentRun)
                .where(ChatAgentRun.status.in_(("queued", "running")))
                .values(
                    status="stale",
                    error="server restarted before run completed",
                    finished_at=datetime.utcnow(),
                )
            )
            result = await session.execute(stmt)
            stale_count = result.rowcount or 0
            break
        if stale_count:
            logger.info(f"启动检查: 已将 {stale_count} 个未完成的 chat agent run 标记为 stale")
    except Exception as e:
        logger.error(f"启动检查: 处理未完成 chat agent run 时出错: {str(e)}")

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
        "/health", "/metrics", "/docs", "/redoc", "/openapi.json",
        "/api/v1/ai-chat/chat/stream",
        "/api/v1/ai-chat/log-analysis/stream",
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
    app.include_router(metrics_api.router, tags=["Metrics"])
    app.include_router(logs.router, prefix="/api/v1/logs", tags=["日志管理"])
    app.include_router(project_repos_api.router, tags=["项目仓库"])
    app.include_router(tasks.router, prefix="/api/v1", tags=["任务管理"])
    app.include_router(ai_chat.router, prefix="/api/v1/ai-chat", tags=["AI Chat"])
    app.include_router(users.router, tags=["用户管理"])
    app.include_router(device_link.router, tags=["设备链接"])
    app.include_router(admin.router, tags=["Admin"])
    app.include_router(admin_metrics.admin_router, tags=["Metrics"])
    app.include_router(admin_metrics.self_router, tags=["Metrics"])
    app.include_router(releases_admin_router, tags=["Admin"])
    app.include_router(releases_public_router, tags=["Releases"])
    app.include_router(packages.router, prefix="/api", tags=["软件包管理"])
    app.include_router(packages.router, prefix="/raven/api", tags=["Raven 软件包管理"])
    
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
                    full_path.startswith("raven/api/") or
                    full_path == "raven/api" or
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
