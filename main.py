from typing import Any

from fastapi import FastAPI
from app.core.settings import settings

from app.api import provision, bot, config

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

app.include_router(provision.router, prefix="/provision", tags=["provision"])
app.include_router(bot.router, prefix="/bot", tags=["bot"])
app.include_router(config.router, prefix="/config", tags=["config"])

@app.get("/health")
def health_check() -> Any:
    return {"status": "ok"}
