"""Application configuration loaded from environment variables."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mbus_base_url: str = "https://mbus.ltp.umich.edu"
    mbus_api_key: str = ""

    database_url: str = "sqlite:///./data/transit.db"

    prediction_poll_seconds: int = 30
    arrival_poll_seconds: int = 15

    arrival_enter_meters: float = 30.0
    arrival_exit_meters: float = 50.0

    reliability_lookback_seconds: int = 300

    log_level: str = "INFO"

    @property
    def sqlite_path(self) -> Path | None:
        """Return the SQLite file path if the URL is SQLite, else None."""
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            return Path(self.database_url[len(prefix):])
        return None


settings = Settings()
