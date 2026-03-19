import logging
import json
import os
import traceback
from datetime import datetime
from typing import Any, Dict

from app.core.settings import settings

class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "time": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname.lower(),
            "msg": record.getMessage(),
        }

        # Add any extra fields passed in kwargs -> extra
        if hasattr(record, "extra_fields"):
            log_entry.update(record.extra_fields)

        if record.exc_info:
            log_entry["exception"] = "".join(traceback.format_exception(*record.exc_info))

        return json.dumps(log_entry)

class StructuredLogger:
    """Wrapper around python standard logging config designed for JSON files."""
    def __init__(self, name: str = "managed-bot-service"):
        self.logger = logging.getLogger(name)
        
        # Only configure if not already configured to avoid duplicate handlers
        if not self.logger.handlers:
            log_level_str = getattr(settings, "LOG_LEVEL", "INFO").upper()
            self.logger.setLevel(getattr(logging, log_level_str, logging.INFO))
            
            # File handler
            os.makedirs("logs", exist_ok=True)
            file_handler = logging.FileHandler("logs/service.log")
            file_handler.setFormatter(JSONFormatter())
            self.logger.addHandler(file_handler)
            
            # Keep console output for docker/dev
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(JSONFormatter())
            self.logger.addHandler(console_handler)
            
            # Prevent propagating to root logger to avoid double prints
            self.logger.propagate = False

    def debug(self, msg: str, **kwargs: Any) -> None:
        self.logger.debug(msg, extra={"extra_fields": kwargs})

    def info(self, msg: str, **kwargs: Any) -> None:
        self.logger.info(msg, extra={"extra_fields": kwargs})

    def warning(self, msg: str, **kwargs: Any) -> None:
        self.logger.warning(msg, extra={"extra_fields": kwargs})
        
    def error(self, msg: str, **kwargs: Any) -> None:
        self.logger.error(msg, extra={"extra_fields": kwargs})

    def exception(self, msg: str, **kwargs: Any) -> None:
        # Logs an error with the current traceback implicitly
        self.logger.exception(msg, extra={"extra_fields": kwargs})

# Global instance
logger = StructuredLogger()
