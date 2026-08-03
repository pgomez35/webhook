"""Parser de eventos webhook Instagram (Meta Social).

Solo object=instagram. Messenger/page queda fuera de esta fase.
"""
from __future__ import annotations

import logging
from typing import Any, Iterator, Optional

from meta_social_schemas import (
    ParsedSocialEvent,
    SocialAttachmentMeta,
    SocialChannel,
)

logger = logging.getLogger("uvicorn.error")


def _as_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_attachments(message: dict[str, Any]) -> list[SocialAttachmentMeta]:
    raw = message.get("attachments") or []
    result: list[SocialAttachmentMeta] = []
    if not isinstance(raw, list):
        return result
    for item in raw:
        if not isinstance(item, dict):
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else None
        url = payload.get("url") if payload else None
        result.append(
            SocialAttachmentMeta(
                type=item.get("type"),
                url=url,
                payload=payload,
            )
        )
    return result


def _parse_messaging_event(
    *,
    entry_id: Optional[str],
    event: dict[str, Any],
) -> Optional[ParsedSocialEvent]:
    sender = event.get("sender") or {}
    recipient = event.get("recipient") or {}
    sender_id = str(sender.get("id") or "").strip()
    recipient_id = str(recipient.get("id") or "").strip()
    if not sender_id:
        return None

    timestamp = _as_int(event.get("timestamp"))

    if "read" in event:
        return ParsedSocialEvent(
            channel=SocialChannel.INSTAGRAM,
            entry_id=entry_id,
            sender_id=sender_id,
            recipient_id=recipient_id or "",
            timestamp=timestamp,
            is_read=True,
            raw_object="instagram",
            event_type="read",
        )

    if "delivery" in event:
        return ParsedSocialEvent(
            channel=SocialChannel.INSTAGRAM,
            entry_id=entry_id,
            sender_id=sender_id,
            recipient_id=recipient_id or "",
            timestamp=timestamp,
            is_delivery=True,
            raw_object="instagram",
            event_type="delivery",
        )

    postback = event.get("postback")
    if isinstance(postback, dict):
        return ParsedSocialEvent(
            channel=SocialChannel.INSTAGRAM,
            entry_id=entry_id,
            sender_id=sender_id,
            recipient_id=recipient_id or "",
            timestamp=timestamp,
            message_id=str(postback.get("mid") or "").strip() or None,
            postback_payload=str(postback.get("payload") or "").strip() or None,
            postback_title=str(postback.get("title") or "").strip() or None,
            raw_object="instagram",
            event_type="postback",
        )

    message = event.get("message")
    if isinstance(message, dict):
        return ParsedSocialEvent(
            channel=SocialChannel.INSTAGRAM,
            entry_id=entry_id,
            sender_id=sender_id,
            recipient_id=recipient_id or "",
            timestamp=timestamp,
            message_id=str(message.get("mid") or "").strip() or None,
            text=str(message.get("text") or "").strip() or None,
            is_echo=bool(message.get("is_echo")),
            is_self=bool(message.get("is_self")),
            attachments=_parse_attachments(message),
            raw_object="instagram",
            event_type="message",
        )

    return None


def iter_parsed_events(payload: dict[str, Any]) -> Iterator[ParsedSocialEvent]:
    object_name = str(payload.get("object") or "").strip().lower()
    if object_name != "instagram":
        logger.info(
            "[meta_social] Objeto webhook ignorado (solo instagram): %s",
            object_name or "(vacío)",
        )
        return

    entries = payload.get("entry") or []
    if not isinstance(entries, list):
        return

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id") or "").strip() or None
        messaging = entry.get("messaging") or []
        if not isinstance(messaging, list):
            continue
        for event in messaging:
            if not isinstance(event, dict):
                continue
            parsed = _parse_messaging_event(entry_id=entry_id, event=event)
            if parsed is not None:
                yield parsed


def parse_events(payload: dict[str, Any]) -> list[ParsedSocialEvent]:
    return list(iter_parsed_events(payload))
