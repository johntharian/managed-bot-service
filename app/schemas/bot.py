from pydantic import BaseModel
from typing import Any

class MessageEnvelope(BaseModel):
    from_: str
    to: str
    intent: str
    thread_id: str
    message_id: str
    timestamp: str
    payload: dict[str, Any]

    class Config:
        populate_by_name = True
        alias_generator = lambda string: "from" if string == "from_" else string
