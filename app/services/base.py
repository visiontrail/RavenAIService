"""
基础服务类和CRUD操作
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List, Type, TypeVar, Generic
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# 定义泛型类型
ModelType = TypeVar("ModelType", bound=DeclarativeBase)


class BaseService(ABC):
    """基础服务抽象类"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.settings = settings
    
    def log_info(self, message: str, extra: Optional[Dict[str, Any]] = None):
        """记录信息日志"""
        self.logger.info(message, extra=extra)
    
    def log_warning(self, message: str, extra: Optional[Dict[str, Any]] = None):
        """记录警告日志"""
        self.logger.warning(message, extra=extra)
    
    def log_error(self, message: str, extra: Optional[Dict[str, Any]] = None):
        """记录错误日志"""
        self.logger.error(message, extra=extra)
    
    def log_debug(self, message: str, extra: Optional[Dict[str, Any]] = None):
        """记录调试日志"""
        self.logger.debug(message, extra=extra)


class BaseCRUDService(Generic[ModelType], BaseService):
    """基础CRUD操作服务类"""
    
    def __init__(self, model: Type[ModelType]):
        super().__init__()
        self.model = model
    
    async def create(self, db: AsyncSession, **kwargs) -> ModelType:
        """创建记录"""
        db_obj = self.model(**kwargs)
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj
    
    async def get_by_id(self, db: AsyncSession, id: Any) -> Optional[ModelType]:
        """根据ID获取记录"""
        result = await db.execute(select(self.model).where(self.model.id == id))
        return result.scalar_one_or_none()
    
    async def get_multi(
        self, 
        db: AsyncSession, 
        offset: int = 0, 
        limit: int = 100,
        **filters
    ) -> List[ModelType]:
        """获取多条记录"""
        query = select(self.model)
        
        # 添加过滤条件
        for field, value in filters.items():
            if hasattr(self.model, field) and value is not None:
                query = query.where(getattr(self.model, field) == value)
        
        query = query.offset(offset).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()
    
    async def count(self, db: AsyncSession, **filters) -> int:
        """计算记录数量"""
        from sqlalchemy import func
        
        query = select(func.count(self.model.id))
        
        # 添加过滤条件
        for field, value in filters.items():
            if hasattr(self.model, field) and value is not None:
                query = query.where(getattr(self.model, field) == value)
        
        result = await db.execute(query)
        return result.scalar()
    
    async def update(
        self, 
        db: AsyncSession, 
        id: Any, 
        **update_data
    ) -> Optional[ModelType]:
        """更新记录"""
        # 过滤掉None值
        update_data = {k: v for k, v in update_data.items() if v is not None}
        
        if not update_data:
            return await self.get_by_id(db, id)
        
        # 更新记录
        await db.execute(
            update(self.model)
            .where(self.model.id == id)
            .values(**update_data)
        )
        
        # 返回更新后的记录
        return await self.get_by_id(db, id)
    
    async def delete(self, db: AsyncSession, id: Any) -> bool:
        """删除记录"""
        result = await db.execute(
            delete(self.model).where(self.model.id == id)
        )
        return result.rowcount > 0
    
    async def delete_multi(self, db: AsyncSession, ids: List[Any]) -> int:
        """批量删除记录"""
        result = await db.execute(
            delete(self.model).where(self.model.id.in_(ids))
        )
        return result.rowcount
