import time
from typing import Any

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.settings import settings
from app.core.logger import logger

from app.api import provision, bot, config

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Log request basic info before processing (optional, keeping minimal for now)
        # response processing
        try:
            response = await call_next(request)
            process_time_ms = (time.time() - start_time) * 1000
            
            # Log at info by default
            logger.info(
                "Request completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(process_time_ms, 2),
                client_ip=request.client.host if request.client else None
            )
            return response
        except Exception as e:
            process_time_ms = (time.time() - start_time) * 1000
            logger.exception(
                "Request failed with exception",
                method=request.method,
                path=request.url.path,
                duration_ms=round(process_time_ms, 2),
                client_ip=request.client.host if request.client else None
            )
            raise e

app.add_middleware(LoggingMiddleware)

app.include_router(provision.router, prefix="/provision", tags=["provision"])
app.include_router(bot.router, prefix="/bot", tags=["bot"])
app.include_router(config.router, prefix="/config", tags=["config"])

@app.get("/health")
def health_check() -> Any:
    return {"status": "ok"}
