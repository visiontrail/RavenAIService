"""
数据库配置和连接管理
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, DateTime, Integer, Text, Enum as SQLEnum, UUID
from datetime import datetime
from typing import AsyncGenerator
import uuid

from ..config import settings


class Base(DeclarativeBase):
    """SQLAlchemy基类"""
    pass


class TimestampMixin:
    """时间戳混入类"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
        comment="更新时间"
    )


class DatabaseManager:
    """数据库连接管理器"""
    
    def __init__(self):
        self.engine = None
        self.session_factory = None
        
    def initialize(self):
        """初始化数据库连接"""
        database_url = settings.get_database_url()
        
        # 创建异步引擎
        self.engine = create_async_engine(
            database_url,
            echo=settings.database_echo,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout,
            pool_recycle=settings.database_pool_recycle,
        )
        
        # 创建会话工厂
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """获取数据库会话"""
        if not self.session_factory:
            raise RuntimeError("数据库未初始化，请先调用initialize()方法")
            
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
    
    async def create_tables(self):
        """创建所有表"""
        if not self.engine:
            raise RuntimeError("数据库引擎未初始化")
            
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    async def drop_tables(self):
        """删除所有表"""
        if not self.engine:
            raise RuntimeError("数据库引擎未初始化")
            
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    
    async def close(self):
        """关闭数据库连接"""
        if self.engine:
            await self.engine.dispose()


# 全局数据库管理器实例
db_manager = DatabaseManager()


# 依赖注入函数
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话的依赖注入函数"""
    async for session in db_manager.get_session():
        yield session
