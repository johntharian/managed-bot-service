from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "BotsApp Managed Bot Service"
    API_V1_STR: str = ""

    CORS_ALLOWED_ORIGINS: str = "http://localhost:3000"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]

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
