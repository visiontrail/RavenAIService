"""
数据库配置和连接管理
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, DateTime, Integer, Text, Enum as SQLEnum, UUID, event, inspect, text
from datetime import datetime
from typing import AsyncGenerator
import logging
import uuid

from ..config import settings

logger = logging.getLogger(__name__)


def _apply_sqlite_pragmas(dbapi_connection) -> None:
    """启用 WAL + 较大的 busy_timeout，避免并发写时 'database is locked'。

    SQLite 默认 journal_mode=DELETE：任何写事务都会阻塞其他读/写，
    且 busy_timeout 接近 0，遇锁立刻抛错。本项目存在 async (aiosqlite) 与
    sync (sqlite3，见 app/tasks/ai_analysis.py) 两个引擎同时访问同一文件，
    再加上 SSE 长连接会长时间持有事务，必须打开 WAL 才能允许 reader 与 writer
    并发，并通过 busy_timeout 让冲突写做合理等待而不是立即失败。
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


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
        is_sqlite = database_url.startswith("sqlite")

        engine_kwargs: dict = {
            "echo": settings.database_echo,
            "pool_recycle": settings.database_pool_recycle,
        }
        # SQLite (aiosqlite) 使用单 writer 模型，连接池参数会被驱动忽略，
        # 设置反而触发 SQLAlchemy 警告。生产环境 PostgreSQL 才需要 pool 调优。
        if not is_sqlite:
            engine_kwargs.update(
                pool_size=settings.database_pool_size,
                max_overflow=settings.database_max_overflow,
                pool_timeout=settings.database_pool_timeout,
            )

        self.engine = create_async_engine(database_url, **engine_kwargs)

        if is_sqlite:
            @event.listens_for(self.engine.sync_engine, "connect")
            def _set_sqlite_pragma(dbapi_connection, _connection_record):
                _apply_sqlite_pragmas(dbapi_connection)

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
            # ``create_all`` only creates missing *tables*; it never adds new
            # columns to tables that already exist. Since this project manages
            # schema via ``create_all`` at startup (alembic migrations are not
            # run at runtime), additive columns must be backfilled here so an
            # existing database stays in sync with the ORM models.
            await conn.run_sync(self._ensure_additive_columns)

    @staticmethod
    def _ensure_additive_columns(conn) -> None:
        """Backfill columns that were added to existing tables over time.

        Idempotent and dialect-aware (SQLite / PostgreSQL). Each entry maps a
        table to the columns that may be missing on older databases, with the
        ``ALTER TABLE ADD COLUMN`` type clause per dialect.
        """
        dialect = conn.dialect.name
        is_sqlite = dialect == "sqlite"

        # column_name -> {"sqlite": <ddl>, "default": <ddl for others>}
        additive: dict[str, dict[str, dict[str, str]]] = {
            "chat_sessions": {
                "is_pinned": {
                    "sqlite": "BOOLEAN NOT NULL DEFAULT 0",
                    "default": "BOOLEAN NOT NULL DEFAULT FALSE",
                },
                "pinned_at": {
                    "sqlite": "DATETIME",
                    "default": "TIMESTAMP",
                },
            },
            "users": {
                "language": {
                    "sqlite": "VARCHAR(8) NOT NULL DEFAULT 'zh'",
                    "default": "VARCHAR(8) NOT NULL DEFAULT 'zh'",
                },
                "profile_role": {
                    "sqlite": "VARCHAR(64) NOT NULL DEFAULT 'developer'",
                    "default": "VARCHAR(64) NOT NULL DEFAULT 'developer'",
                },
            },
            "log_records": {
                "project_id": {
                    "sqlite": "INTEGER",
                    "default": "INTEGER REFERENCES project_repo(id) ON DELETE SET NULL",
                },
            },
        }

        # Columns that were removed from ORM models and must be dropped from
        # existing databases. SQLite supports DROP COLUMN since 3.35.0;
        # PostgreSQL has always supported it.
        removed: dict[str, list[str]] = {
            "log_records": ["log_type"],
        }

        inspector = inspect(conn)
        existing_tables = set(inspector.get_table_names())
        for table, columns in additive.items():
            if table not in existing_tables:
                continue
            present = {col["name"] for col in inspector.get_columns(table)}
            for column, ddl in columns.items():
                if column in present:
                    continue
                type_clause = ddl["sqlite"] if is_sqlite else ddl["default"]
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} {type_clause}")
                )
                logger.info("已为表 %s 补充缺失列: %s", table, column)

        for table, columns in removed.items():
            if table not in existing_tables:
                continue
            present = {col["name"] for col in inspector.get_columns(table)}
            for column in columns:
                if column not in present:
                    continue
                conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
                logger.info("已从表 %s 删除废弃列: %s", table, column)

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
