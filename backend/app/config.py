from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    MODEL_API_KEY: str | None = None
    META_BASE_URL: str = "https://api.meta.ai/v1"
    REASONING_PROVIDER: str = "mock"
    MUSE_SPARK_MODEL: str = "muse-spark-1.3"
    SEGMENTATION_PROVIDER: str = "mock"
    EMBEDDER: str = "mock"
    BASETEN_API_KEY: str | None = None
    BASETEN_MODEL: str = "meta-models/muse-spark-open"
    PEXELS_API_KEY: str | None = None
    PEXELS_ENABLED: bool = False
    OPENVERSE_CLIENT_ID: str | None = None
    OPENVERSE_CLIENT_SECRET: str | None = None
    SMITHSONIAN_API_KEY: str | None = None
    CONTACT_EMAIL: str | None = None
    MODEL_TIMEOUT_S: float = 60
    MODEL_MAX_RETRIES: int = 2
    DATABASE_URL: str = "sqlite:///./data/dle.sqlite"
    DATA_DIR: str = "./data"
    MAX_UPLOAD_BYTES: int = 10485760
    MAX_VIDEO_BYTES: int = 104857600
    MAX_VIDEO_SECONDS: int = 90
    LINK_FETCH_TIMEOUT_S: float = 5
    SHAPE_KIND_ENABLED: bool = False
    EXTENSION_ORIGIN: str | None = None
    PUBLIC_APP_URL: str = "http://localhost:5173"


def get_settings() -> Settings:
    return Settings()
