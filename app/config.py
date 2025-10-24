"""
应用配置模块
支持环境变量配置和开发/生产环境切换
"""

import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# 加载环境变量（优先使用容器内挂载的 .env）
load_dotenv(dotenv_path=".env", override=True)


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
    
    # Agent配置（日志分析智能体）
    agent_enabled: bool = True
    agent_root_dir: str = "uploads"  # 允许Agent访问的日志根目录
    agent_max_snippet_bytes: int = 512 * 1024  # 每次提取的最大字节数
    agent_max_matches: int = 50  # grep最大匹配数
    agent_search_backend: str = "regex"  # 可选：regex | elasticsearch
    elasticsearch_url: Optional[str] = None
    
    # LLM配置
    # llm_provider: str = "deepseek"
    # deepseek_api_key: Optional[str] = "sk-rebTXHBiV7Nr1PRzaODQOZKztKqpv7bPoQE10dNItF9yIyBh"
    # deepseek_base_url: str = "http://oneapi.yhroot.com/v1/chat/completions"
    # llm_model_name: str = "deepseek-v3.1-chat"
    # llm_reasoning_model: str = "deepseek-v3.1"  # 推理模型
    # llm_temperature: float = 0.0
    
    
    llm_provider: str = "auto"  # deepseek 优先，不可用时回退到 qwen
    
    # DeepSeek 配置
    deepseek_api_key: Optional[str] = "sk-rebTXHBiV7Nr1PRzaODQOZKztKqpv7bPoQE10dNItF9yIyBh"
    # 使用 OpenAI 兼容客户端的基础URL（不包含 /chat/completions 以避免重复）
    deepseek_base_url: str = "http://oneapi.yhroot.com/v1"
    llm_model_name: str = "deepseek-v3.1"
    llm_reasoning_model: str = "deepseek-v3.1"
    
    # Qwen 配置（OpenAI 兼容模式）
    qwen_api_key: Optional[str] = "sk-700b5dceea294f099b30f097718b854d"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model_name: str = "qwen-plus-2025-09-11"
    
    llm_temperature: float = 0.0
    
    # 上下文压缩/记忆配置
    agent_compression_strategy: str = "map_reduce_summarize"  # 可选：map_reduce_summarize | extractive | hybrid
    agent_short_term_window: int = 5  # 短时记忆窗口消息条数
    
    # Prompt配置（外部化模板路径，可通过环境变量覆盖）
    prompts_config_path: str = "app/prompts/prompts_config.yaml"
    
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
    
    # Celery配置
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"
    celery_task_serializer: str = "json"
    celery_result_serializer: str = "json"
    celery_accept_content: List[str] = ["json"]
    celery_timezone: str = "UTC"
    celery_enable_utc: bool = True
    
    # Redis配置
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    
    # 协议栈日志处理配置
    log_processing_speed_mb_per_sec: int = 100  # 假设处理速度100MB/s
    max_retry_attempts: int = 3
    task_timeout: int = 3600  # 1小时超时
    thread_num_for_decompress: int = 4  # 默认线程数
    
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
        extra = "ignore"  # 忽略额外的环境变量


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
