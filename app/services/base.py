"""
基础服务类
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from app.config import settings


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
