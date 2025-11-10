from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    TS_TIME_FIELD: str = "time"
    TS_META_FIELD: str | None = "meta"
    MONGO_URI: str | None = None
    MONGO_DB: str = "xerxes"
    MONGO_COLL: str = "measurements"
    PROJECT_API_KEY: str
    TB_HOST: str = "https://tb.meta-mod.com"
    TB_TIMEOUT_S: int = 5
    TB_RETRY_MAX: int = 5
    TB_RETRY_BACKOFF_BASE_MS: int = 200
    TOKEN_MAP_PATH: str = "/data/token_map.json"
    BIND_HOST: str = "0.0.0.0"
    BIND_PORT: int = 8080
    LOG_LEVEL: str = "INFO"
    PROMETHEUS_METRICS: bool = True
    APP_VERSION: str = "v1.0.0-api-key"
    GIT_SHA: str = "unknown"

settings = Settings(_env_file=".env", _env_file_encoding="utf-8")
