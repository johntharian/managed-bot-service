from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "BotsApp Managed Bot Service"
    API_V1_STR: str = ""

    CORS_ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    @field_validator("CORS_ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    # External DB & Redis
    DATABASE_URL: str
    REDIS_URL: str

    # Integration Configuration
    BOTSAPP_SERVICE_TOKEN: str
    BOTSAPP_SERVER_URL: str
    BASE_URL: str

    # Internal Security
    ENCRYPTION_KEY: str  # 32 bytes AES
    ANTHROPIC_API_KEY: str
    GEMINI_API_KEY: str

    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
