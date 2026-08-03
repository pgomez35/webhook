"""Schemas / DTOs internos de Meta Social."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class SocialChannel(str, Enum):
    MESSENGER = "messenger"
    INSTAGRAM = "instagram"


class SocialAttachmentMeta(BaseModel):
    type: Optional[str] = None
    url: Optional[str] = None
    payload: Optional[dict[str, Any]] = None


class ParsedSocialEvent(BaseModel):
    channel: SocialChannel
    entry_id: Optional[str] = None
    sender_id: str
    recipient_id: str
    message_id: Optional[str] = None
    text: Optional[str] = None
    timestamp: Optional[int] = None
    is_echo: bool = False
    is_self: bool = False
    is_read: bool = False
    is_delivery: bool = False
    postback_payload: Optional[str] = None
    postback_title: Optional[str] = None
    attachments: list[SocialAttachmentMeta] = Field(default_factory=list)
    raw_object: Optional[str] = None
    event_type: str = "unknown"

    @property
    def should_ignore(self) -> bool:
        if self.is_echo or self.is_read or self.is_delivery:
            return True
        if not self.message_id and not self.postback_payload and not self.text:
            if not self.attachments:
                return True
        return False

    def dedup_key(self) -> str:
        if self.message_id:
            return self.message_id
        return f"{self.sender_id}:{self.timestamp or 0}:{self.event_type}"
