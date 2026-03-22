from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Alter Managed Bot Service"
    API_V1_STR: str = ""

    CORS_ALLOWED_ORIGINS: str = "http://localhost:3000"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]

    # External DB & Redis
    DATABASE_URL: str
    REDIS_URL: str

    # Integration Configuration
    ALTER_SERVICE_TOKEN: str
    ALTER_SERVER_URL: str
    BASE_URL: str

    # Internal Security
    ENCRYPTION_KEY: str  # 32 bytes AES
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str

    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_TOKEN_URI: str = "https://oauth2.googleapis.com/token"

    # Notion OAuth
    NOTION_OAUTH_CLIENT_ID: str = ""
    NOTION_OAUTH_CLIENT_SECRET: str = ""

    # Todoist OAuth
    TODOIST_CLIENT_ID: str = ""
    TODOIST_CLIENT_SECRET: str = ""

    # Slack OAuth
    SLACK_CLIENT_ID: str = ""
    SLACK_CLIENT_SECRET: str = ""

    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
