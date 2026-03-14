from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "BotsApp Managed Bot Service"
    API_V1_STR: str = ""

    # External DB & Redis
    DATABASE_URL: str
    REDIS_URL: str

    # Integration Configuration
    BOTSAPP_SERVICE_TOKEN: str
    BOTSAPP_API_URL: str
    
    # Internal Security
    ENCRYPTION_KEY: str # 32 bytes AES
    ANTHROPIC_API_KEY: str
    GEMINI_API_KEY: str

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
