import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6380/0")

# Initialize Celery pointing to the managed bot's standalone Redis
celery_app = Celery(
    "managed_bot",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.approvals.tasks", "app.persona.tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
