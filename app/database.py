"""
数据库初始化模块
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.models.database import Base, db_manager
# 导入所有模型，确保在初始化时注册到元数据
from app import models  # noqa: F401

logger = logging.getLogger(__name__)


async def init_database():
    """初始化数据库"""
    try:
        logger.info("正在初始化数据库...")
        
        # 初始化数据库管理器
        db_manager.initialize()
        
        # 创建所有表
        await db_manager.create_tables()
        
        logger.info("数据库初始化完成")
        
    except Exception as e:
        logger.error(f"数据库初始化失败: {str(e)}")
        raise


async def create_tables():
    """创建所有表"""
    try:
        await db_manager.create_tables()
        logger.info("数据库表创建成功")
    except Exception as e:
        logger.error(f"创建数据库表失败: {str(e)}")
        raise


async def drop_tables():
    """删除所有表"""
    try:
        await db_manager.drop_tables()
        logger.info("数据库表删除成功")
    except Exception as e:
        logger.error(f"删除数据库表失败: {str(e)}")
        raise


async def reset_database():
    """重置数据库（删除并重新创建所有表）"""
    try:
        logger.info("正在重置数据库...")
        await drop_tables()
        await create_tables()
        logger.info("数据库重置完成")
    except Exception as e:
        logger.error(f"数据库重置失败: {str(e)}")
        raise


async def check_database_connection():
    """检查数据库连接"""
    try:
        async for session in db_manager.get_session():
            # 执行一个简单的查询来测试连接
            await session.execute("SELECT 1")
            logger.info("数据库连接正常")
            return True
    except Exception as e:
        logger.error(f"数据库连接失败: {str(e)}")
        return False


@asynccontextmanager
async def get_database_session() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话的上下文管理器"""
    async for session in db_manager.get_session():
        yield session


async def close_database():
    """关闭数据库连接"""
    try:
        await db_manager.close()
        logger.info("数据库连接已关闭")
    except Exception as e:
        logger.error(f"关闭数据库连接失败: {str(e)}")


# 用于FastAPI启动和关闭事件的函数
@asynccontextmanager
async def lifespan_context():
    """应用生命周期上下文管理器"""
    # 启动时
    try:
        await init_database()
        yield
    finally:
        # 关闭时
        await close_database()


if __name__ == "__main__":
    """直接运行此脚本来初始化数据库"""
    
    async def main():
        """主函数"""
        try:
            print("开始初始化数据库...")
            await init_database()
            
            print("检查数据库连接...")
            if await check_database_connection():
                print("数据库初始化成功！")
            else:
                print("数据库连接检查失败！")
                
        except Exception as e:
            print(f"数据库初始化失败: {str(e)}")
        finally:
            await close_database()
    
    # 运行主函数
    asyncio.run(main())
