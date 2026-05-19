"""
应用配置模块
支持环境变量配置和开发/生产环境切换
"""

import os
from pathlib import Path
from typing import List, Literal, Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# 加载环境变量（优先使用容器内挂载的 .env）
load_dotenv(dotenv_path=".env", override=True)


class Settings(BaseSettings):
    """应用配置类"""
    
    # 环境配置
    environment: str = "development"
    base_dir: str = str(Path(__file__).resolve().parent.parent)
    
    # 服务配置
    host: str = "0.0.0.0"
    port: int = 8085
    # 设备长链接配置（仅暴露常量，后续实现 WebSocket 心跳与超时逻辑）
    device_link_heartbeat_sec: int = 30  # 环境变量: DEVICE_LINK_HEARTBEAT_SEC
    device_link_timeout_sec: int = 120  # 环境变量: DEVICE_LINK_TIMEOUT_SEC
    device_link_store_file: str = "data/device_links.json"
    
    # 日志配置
    log_level: str = "INFO"
    log_file_path: str = "logs/app.log"
    debug_log_file_path: str = "logs/debug.log"
    console_log_level: str = "INFO"
    log_file_max_bytes: int = 50 * 1024 * 1024  # 50MB 默认单个日志文件上限
    log_file_backup_count: int = 5  # 保留的滚动日志文件数量
    enable_debug_file_log: bool = False  # 默认关闭单独的debug文件
    
    # 文件配置
    max_file_size: int = 1073741824  # 1GB
    temp_dir: str = "temp"
    logs_dir: str = "logs"
    disk_reserve_bytes: int = 512 * 1024 * 1024  # 默认预留512MB空间，防止磁盘写满

    # Raven 包管理配置（已统一到 FastAPI 后端）
    raven_base_path: str = "/raven"
    raven_enable_legacy_paths: bool = True
    raven_data_dir: str = "data/raven"
    raven_metadata_file: str = "data/raven/package-metadata.json"
    raven_vector_store_path: str = "data/raven/vector-store"
    upload_dir: str = "data/raven/uploads"
    upload_max_size_mb: int = 500
    rag_embedding_provider: str = "local"
    rag_embedding_model: str = "local"
    openai_base_url: Optional[str] = None
    
    # Agent配置（日志分析智能体）
    agent_enabled: bool = True
    agent_root_dir: str = "."  # 允许Agent访问的日志根目录
    agent_max_snippet_bytes: int = 512 * 1024  # 每次提取的最大字节数
    agent_max_matches: int = 50  # grep最大匹配数
    agent_search_backend: str = "regex"  # 可选：regex | elasticsearch
    elasticsearch_url: Optional[str] = None

    # 代码仓库配置（用于代码分析智能体克隆源码）
    code_repo_clone_base_dir: str = "temp/code_repos"
    code_repo_git_token: Optional[str] = None      # 全局 Git Token（私有仓库认证，可被 project_repo 单独 token 覆盖）
    
    # 仅使用本地部署统一入口
    llm_provider: str = "GalaxySpace"
    
    # 本地模型 配置
    deepseek_api_key: Optional[str] = "sk-rebTXHBiV7Nr1PRzaODQOZKztKqpv7bPoQE10dNItF9yIyBh"
    # 使用 OpenAI 兼容客户端的基础URL（不包含 /chat/completions 以避免重复）
    deepseek_base_url: str = "http://oneapi.yhroot.com/v1"
    llm_model_name: str = "glm-4.6"
    llm_reasoning_model: str = "glm-4.6"
    
    llm_temperature: float = 0.0
    
    # 上下文压缩/记忆配置
    agent_compression_strategy: str = "map_reduce_summarize"  # 可选：map_reduce_summarize | extractive | hybrid
    agent_short_term_window: int = 5  # 短时记忆窗口消息条数
    
    # Anthropic 标准 LLM 配置（供 Claude Agent SDK 使用）
    anthropic_provider: str = "deepseek"  # anthropic | deepseek | custom
    anthropic_api_key: Optional[str] = None
    anthropic_base_url: Optional[str] = None        # None 时由 provider profile 提供
    anthropic_model: Optional[str] = None           # None 时由 provider profile 提供
    anthropic_small_fast_model: Optional[str] = None
    anthropic_max_tokens: int = 8192
    anthropic_max_turns: int = 30
    anthropic_permission_mode: str = "acceptEdits"
    anthropic_request_timeout_seconds: int = 3600
    ai_analysis_max_extract_bytes: int = 2 * 1024 * 1024 * 1024  # 2 GiB

    # Agent Skills 数据目录（Claude Agent SDK Skill 包按 agent 隔离存储）
    skills_data_dir: str = "data/agent_skills"

    @field_validator("anthropic_provider")
    @classmethod
    def validate_anthropic_provider(cls, v: str) -> str:
        allowed = {"anthropic", "deepseek", "custom"}
        if v not in allowed:
            raise ValueError(f"anthropic_provider must be one of {sorted(allowed)}, got '{v}'")
        return v

    # Prompt配置（外部化模板路径，可通过环境变量覆盖）
    prompts_config_path: str = "app/prompts/prompts_config.yaml"
    
    # 后台管理配置
    admin_auth_config_path: str = "app/admin_auth.yaml"
    admin_token_ttl_minutes: int = 120
    user_token_ttl_minutes: int = 60 * 24 * 7
    
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
    repackage_use_pigz: bool = True  # 优先使用pigz并行压缩
    repackage_pigz_threads: int = 0  # 0表示自动按CPU核心数选择
    repackage_compress_level: int = 6  # pigz缺失时tarfile的压缩等级(1-9)
    
    # SQLite配置（开发环境）
    # 默认放在 data 目录，避免与代码目录冲突，方便卷持久化
    sqlite_file: str = "data/logs.db"
    
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
