from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Process settings.

    Target values are bootstrap-only. Once the SQLite store exists, changes
    made on the Settings page are the source of truth.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    model_sentinel_data_dir: Path = Path("./data")
    model_sentinel_timezone: str = "Asia/Singapore"

    target_name: str = "银河私有模型集群"
    target_protocol: str = "anthropic"
    target_base_url: str = "http://oneapi.yhroot.com"
    target_model: str = "yinhe-thinking"
    target_interval_seconds: int = 300
    target_timeout_seconds: int = 1800
    target_max_tokens: int = 1024

    @property
    def database_path(self) -> Path:
        return self.model_sentinel_data_dir / "sentinel.db"

    @property
    def secret_key_path(self) -> Path:
        return self.model_sentinel_data_dir / ".secret-key"


config = AppConfig()
