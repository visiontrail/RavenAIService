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
        """创建所有表，并根据 ORM 模型自动补齐已存在表缺失的列。"""
        if not self.engine:
            raise RuntimeError("数据库引擎未初始化")

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # ``create_all`` 只会创建缺失的“表”，绝不会向已存在的表添加新“列”。
            # 本项目在运行期不执行 alembic 迁移，而是通过 ``create_all`` + 自动列
            # 同步来维护 schema。因此这里根据 ORM 模型自动补齐任何缺失的列，使旧库
            # 与模型保持一致——新增模型字段无需再手工维护补列清单。
            await conn.run_sync(self._sync_columns_from_models)

    # 已从 ORM 模型中移除、需要从旧库里删除的列。这类信息无法从模型推导
    # （属性已不存在），因此显式列出。SQLite 自 3.35.0 起支持 DROP COLUMN，
    # PostgreSQL 一直支持。
    _REMOVED_COLUMNS: dict[str, tuple[str, ...]] = {
        "log_records": ("log_type",),
    }

    @classmethod
    def _sync_columns_from_models(cls, conn) -> None:
        """自动将已存在表的列结构同步到 ORM 模型定义。

        - 为缺失的列执行 ``ALTER TABLE ... ADD COLUMN``；其 DDL（类型 /
          server_default / 可空性）由 Alembic 依据模型列定义渲染，与迁移文件中
          ``op.add_column`` 的行为完全一致，因此字符串默认值等都会被正确转义。
        - 删除 ``_REMOVED_COLUMNS`` 中声明的废弃列。

        幂等且方言无关（SQLite / PostgreSQL）。对于无法安全自动添加的列
        （NOT NULL 且无 server_default，向已有数据的表追加会失败），记录告警并
        跳过，需由人工编写迁移做数据回填。
        """
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        inspector = inspect(conn)
        existing_tables = set(inspector.get_table_names())
        op = Operations(MigrationContext.configure(conn))

        # 1) 依据模型自动补齐缺失列
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # 新表交给 create_all 创建
            present = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                if not column.nullable and column.server_default is None:
                    logger.warning(
                        "表 %s 缺失列 %s（NOT NULL 且无 server_default），"
                        "无法自动补齐，请编写迁移处理",
                        table.name,
                        column.name,
                    )
                    continue
                new_column = column._copy()
                # 附加列不携带外键约束：SQLite 无法通过 ALTER ADD COLUMN 追加外键，
                # 此处只需补齐数据列本身（与历史手工补列的行为一致）。
                new_column.foreign_keys = set()
                op.add_column(table.name, new_column)
                logger.info("已为表 %s 自动补充缺失列: %s", table.name, column.name)

        # 2) 删除已废弃列
        inspector.clear_cache()
        for table_name, columns in cls._REMOVED_COLUMNS.items():
            if table_name not in existing_tables:
                continue
            present = {col["name"] for col in inspector.get_columns(table_name)}
            for column in columns:
                if column not in present:
                    continue
                conn.execute(text(f"ALTER TABLE {table_name} DROP COLUMN {column}"))
                logger.info("已从表 %s 删除废弃列: %s", table_name, column)

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
