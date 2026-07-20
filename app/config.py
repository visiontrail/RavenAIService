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
    serve_frontend: bool = False
    frontend_dist_dir: Optional[str] = None

    # 对话分享公开页（系统首个未鉴权读取面）
    # 公开分享链接 share_url 的站点根地址，如 https://ravenai.example.com。
    # 留空时由 API 回退请求 Origin / Host 拼接，便于本地与多域名部署。
    public_base_url: Optional[str] = None
    # 公开 GET /share/{token} 端点的按 IP 基础限流（抑制 token 空间扫描枚举）。
    share_public_rate_limit: int = 60  # 时间窗内允许的最大请求数
    share_public_rate_window_seconds: int = 60  # 限流时间窗（秒）
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
    upload_dir: str = "data/raven/uploads"
    upload_max_size_mb: int = 500

    # Package search Agent 配置（Claude Agent SDK 驱动的重构包智能检索）
    package_search_max_turns: int = 8
    package_search_default_limit: int = 5
    package_search_max_limit: int = 50
    
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
    anthropic_max_history_turns: int = 10
    anthropic_small_fast_max_tokens: int = 1024
    anthropic_small_fast_request_timeout_seconds: int = 30
    general_agent_max_turns: int = 6
    ai_analysis_max_extract_bytes: int = 2 * 1024 * 1024 * 1024  # 2 GiB

    # OCR / 视觉理解模型（独立于主力 Anthropic 模型，走 OpenAI 兼容端点，默认
    # 对接阿里云百炼 DashScope Qwen-VL）。用户粘贴的图片先由此模型转成文字，再
    # 以 <user_image_ocr> 段合并进用户提示，下游各 Agent 零改动。全部可选、带
    # 安全默认；未配置 OCR_API_KEY 时对图片自动降级。
    ocr_enabled: bool = True                          # 总开关；False 时无条件降级
    ocr_provider: str = "dashscope"                   # 计量/日志标签
    ocr_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ocr_api_key: Optional[str] = None                 # 未设置即视为「未配置」→ 降级
    ocr_model: str = "qwen3.5-ocr"                    # 可设 qwen-vl-ocr-latest / qwen-vl-ocr
    ocr_max_tokens: int = 2048                        # 单次输出上限
    ocr_request_timeout_seconds: int = 30             # 单次请求超时
    ocr_max_images: int = 6                           # 单轮图片数上限
    ocr_max_image_mb: int = 5                         # 单图大小上限（MB）

    # 用户随消息附带图片的原图存储。图片按 <session_id>/<image_id>.<ext> 落盘，
    # chat_messages.images_json 只存元数据，历史回显经鉴权端点回图。目录随会话
    # 删除而清理（见 chat_image_store）。相对路径按 base_dir 解析。
    chat_image_store_dir: str = "temp/chat_images"
    # 是否把原图物化到 Agent 工作区 <workspace>/images/（为后续多模态铺路）。
    # 仅在 provider 的 supports_image_input 为真时生效——非视觉上游若 Read 到
    # 图片文件会导致整个 run 报错。
    chat_image_workspace_materialize: bool = True

    # Bug Fix Coding Agent（分析判定需要代码修复时自动派发的写入型 Agent）
    bug_fix_auto_dispatch: bool = False             # 自动派发总开关，默认关闭，灰度可控
    bug_fix_agent_model: Optional[str] = None       # None 时复用 anthropic_model / provider 默认
    bug_fix_agent_request_timeout_seconds: int = 3600
    bug_fix_agent_max_turns: int = 150              # 写入型任务回合多（定位/编辑/提交/推送/建 MR × 多个修复项）；实测 60 回合不够修完 2 个修复项
    bug_fix_git_provider: Optional[str] = None      # None 时由 repo_url host 推断（gitlab|github）
    bug_fix_git_api_base: Optional[str] = None       # None 时由 repo_url host 推断

    # DeviceAgent 专属（Claude Agent SDK 设备联动对话）
    device_agent_permission_timeout_seconds: int = 120
    device_agent_result_excerpt_bytes: int = 16 * 1024
    device_agent_result_max_bytes: int = 256 * 1024
    device_agent_max_remote_tools: int = 64
    # AskUserQuestion 澄清提问等待时长：代码常量、非用户可改，默认 5 分钟。
    # 超时后的行为（取消本轮 / 基于已知信息继续）由用户偏好决定。
    device_agent_clarification_timeout_seconds: int = 300

    # Agent Skills 数据目录（Claude Agent SDK Skill 包按 agent 隔离存储）
    skills_data_dir: str = "data/agent_skills"

    # Project Skills 数据目录（按 project_code 隔离存储，与 Agent Skills 平行）
    project_skills_data_dir: str = "data/project_skills"

    # Project 系统提示词数据目录（按 project_code 隔离存储；项目级追加提示词，
    # 与 Project Skills 平行，让系统提示词也能像 Skill 一样分级处理）
    project_prompts_data_dir: str = "data/project_prompts"

    # 运行期可由 Admin 调整的轻量级模型设置持久化文件
    runtime_settings_path: str = "data/runtime_settings.json"

    # Metrics 成本估算价格配置（可选）。默认空表示不估价，成本字段返回 null。
    # 格式：{"<provider>": {"<model>": {"input_per_million": 3.0,
    #        "output_per_million": 15.0, "cache_read_per_million": 0.3,
    #        "cache_write_per_million": 3.75}}}
    # 单价单位为“每 100 万 token 的美元价格”。
    ai_metrics_pricing_json: Optional[str] = None

    def get_ai_metrics_pricing(self) -> dict:
        """解析 ai_metrics_pricing_json，返回 provider->model->token_type 价格映射。

        解析失败或未配置时返回空 dict（即不估价）。永不抛出。
        """
        import json

        raw = self.ai_metrics_pricing_json
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:  # noqa: BLE001
            pass
        return {}

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
