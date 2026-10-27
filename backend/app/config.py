from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    MODEL_API_KEY: str | None = None
    META_BASE_URL: str = "https://api.meta.ai/v1"
    REASONING_PROVIDER: str = "muse-spark"
    MUSE_SPARK_MODEL: str = "muse-spark-1.3"
    SEGMENTATION_PROVIDER: str = "sam-3.1"
    EMBEDDER: str = "siglip2"
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
    # Test-only: comma-separated hostnames exempt from the link SSRF guard (e2e fixture server).
    LINK_ALLOW_PRIVATE_HOSTS: str = ""
    SHAPE_KIND_ENABLED: bool = False
    # Live licensed-source search inside Vary (see app/live); tests force LIVE_SEARCH off
    LIVE_SEARCH: bool = True
    LIVE_SOURCES: str = "commons,openverse,met,aic,smithsonian"
    LIVE_MAX_CANDIDATES: int = 40
    LIVE_TIMEOUT_S: float = 20
    LIVE_PER_SOURCE_LIMIT: int = 15
    LIVE_QUERY_COUNT: int = 4
    EXTENSION_ORIGIN: str | None = None
    PUBLIC_APP_URL: str = "http://localhost:5173"
    JOBS_SYNC: bool = False
    # Public demo guard (see app/demo.py); off by default
    DEMO_MODE: bool = False
    DEMO_PASSCODE: str | None = None
    DEMO_SECRET: str | None = None
    DEMO_RUNS_PER_IP_PER_HOUR: int = 10
    DEMO_RUNS_PER_DAY: int = 150
    # Behind a proxy: take the client IP from X-Forwarded-For, DEMO_PROXY_HOPS entries from the right
    # (the entries trusted proxies appended; the leftmost ones are client-controlled)
    DEMO_TRUST_PROXY: bool = False
    DEMO_PROXY_HOPS: int = 1
    # Built frontend to serve at / (the single-container deploy); unset in development
    FRONTEND_DIST: str | None = None


def get_settings() -> Settings:
    return Settings()


def resolve_repo_path(value: str) -> Path:
    """Relative paths resolve against the repo root, never the current directory."""
    p = Path(value).expanduser()
    return p if p.is_absolute() else (REPO_ROOT / p).resolve()


def data_dir(settings: Settings) -> Path:
    return resolve_repo_path(settings.DATA_DIR)
