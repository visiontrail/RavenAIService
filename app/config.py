"""
应用配置模块
支持环境变量配置和开发/生产环境切换
"""

import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class Settings(BaseSettings):
    """应用配置类"""
    
    # 环境配置
    environment: str = "development"
    
    # 服务配置
    host: str = "0.0.0.0"
    port: int = 8085
    
    # 日志配置
    log_level: str = "INFO"
    log_file_path: str = "logs/app.log"
    
    # 文件配置
    max_file_size: int = 1073741824  # 1GB
    temp_dir: str = "temp"
    logs_dir: str = "logs"
    
    # CORS配置
    cors_origins: List[str] = ["*"]
    cors_credentials: bool = True
    cors_methods: List[str] = ["*"]
    cors_headers: List[str] = ["*"]
    
    # 安全配置
    secret_key: str = "your-secret-key-here"
    
    # 数据库配置
    database_url: Optional[str] = None
    database_echo: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 10
    database_pool_timeout: int = 30
    database_pool_recycle: int = 3600
    
    # SQLite配置（开发环境）
    sqlite_file: str = "logs.db"
    
    # PostgreSQL配置（生产环境）
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "log_staging"
    postgres_user: str = "postgres"
    postgres_password: str = "password"
    
    def get_database_url(self) -> str:
        """获取数据库连接URL"""
        if self.database_url:
            return self.database_url
            
        if self.environment == "production":
            return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        else:
            return f"sqlite+aiosqlite:///{self.sqlite_file}"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


class DevelopmentSettings(Settings):
    """开发环境配置"""
    environment: str = "development"
    log_level: str = "DEBUG"


class ProductionSettings(Settings):
    """生产环境配置"""
    environment: str = "production"
    log_level: str = "WARNING"
    cors_origins: List[str] = []  # 生产环境需要配置具体的域名


def get_settings() -> Settings:
    """获取配置实例"""
    env = os.getenv("ENVIRONMENT", "development").lower()
    
    if env == "production":
        return ProductionSettings()
    else:
        return DevelopmentSettings()


# 全局配置实例
settings = get_settings()
