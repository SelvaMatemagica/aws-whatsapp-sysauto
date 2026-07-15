import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PG_HOST: str = "postgres"
    PG_PORT: int = 5432
    PG_USER: str = "postgres"
    PG_PASS: str = "postgres"
    PG_DB: str = "symas"

    VERIFY_TOKEN: str = ""

    REDIS_URL: str = "redis://redis:6379/0"

    META_API_VERSION: str = "v17.0"
    META_BUSINESS_ID: str = ""
    META_TOKEN: str = ""
    PHONE_NUMBER_ID: str = ""
    WABA_ID: str = ""

    RATE_LIMIT_PER_MIN: int = 30
    WORKER_SLEEP_MIN_MS: int = 300
    WORKER_SLEEP_MAX_MS: int = 1500

    JWT_SECRET: str = ""
    JWT_AUDIENCE: str = ""

    EMAIL: str = ""
    HOST_EMAIL: str = ""
    PASSWORD_EMAIL: str = ""

    AUTOMATION_EVENTS_QUEUE: str = "events:pending"
    AUTOMATION_LOCK_TTL_SEC: int = 30
    AUTOMATION_MAX_EVENT_ATTEMPTS: int = 5
    AUTOMATION_AUTO_RESUME_MINUTES: int = 60

    # Configuración para cargar automáticamente el archivo .env
    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()