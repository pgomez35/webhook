"""Cliente Facebook Messenger Send API (Page Messaging).

Usa graph.facebook.com + META_SOCIAL_FACEBOOK_PAGE_ACCESS_TOKEN.
No reutiliza tokens de Instagram ni WhatsApp.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from instagram_messaging_client import MetaSocialApiError, raise_for_meta_response
from meta_social_config import MetaSocialSettings, get_settings

logger = logging.getLogger("uvicorn.error")


def _mask_id(value: str, keep: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return "(vacío)"
    if len(text) <= keep * 2:
        return text[:2] + "***"
    return f"{text[:keep]}…{text[-keep:]}"


def _graph_version(settings: MetaSocialSettings) -> str:
    version = (settings.graph_api_version or "v21.0").strip()
    if not version.startswith("v"):
        version = f"v{version}"
    return version


async def send_messenger_text(
    recipient_psid: str,
    text: str,
    *,
    page_id: Optional[str] = None,
    page_access_token: Optional[str] = None,
    api_version: Optional[str] = None,
    settings: Optional[MetaSocialSettings] = None,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    """
    POST https://graph.facebook.com/{version}/{PAGE_ID}/messages

    recipient.id = PSID (sender.id del webhook), nunca el Page ID.
    """
    cfg = settings or get_settings()
    psid = (recipient_psid or "").strip()
    page = (page_id or cfg.facebook_page_id or "").strip()
    token = (page_access_token or cfg.facebook_page_access_token or "").strip()
    version = (api_version or _graph_version(cfg)).strip()
    if not version.startswith("v"):
        version = f"v{version}"

    if not psid:
        raise MetaSocialApiError("recipient_psid vacío", status_code=400)
    if not page:
        raise MetaSocialApiError(
            "META_SOCIAL_FACEBOOK_PAGE_ID no configurado",
            status_code=503,
        )
    if not token:
        raise MetaSocialApiError(
            "META_SOCIAL_FACEBOOK_PAGE_ACCESS_TOKEN no configurado",
            status_code=503,
        )
    if psid == page:
        raise MetaSocialApiError(
            "recipient_psid no puede ser el Page ID",
            status_code=400,
        )

    endpoint = f"https://graph.facebook.com/{version}/{page}/messages"
    payload = {
        "recipient": {"id": psid},
        "messaging_type": "RESPONSE",
        "message": {"text": text},
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    logger.info(
        "[meta_social] canal=messenger page_id=%s recipient_psid=%s "
        "envío tipo=text endpoint_host=graph.facebook.com",
        _mask_id(page),
        _mask_id(psid),
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds)) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        logger.error(
            "[meta_social] canal=messenger page_id=%s recipient_psid=%s "
            "success=false status_http=504 error=timeout",
            _mask_id(page),
            _mask_id(psid),
        )
        raise MetaSocialApiError(
            "Timeout al contactar Meta Messenger API",
            status_code=504,
        ) from exc
    except httpx.HTTPError as exc:
        logger.error(
            "[meta_social] canal=messenger page_id=%s recipient_psid=%s "
            "success=false status_http=502 error=%s",
            _mask_id(page),
            _mask_id(psid),
            type(exc).__name__,
        )
        raise MetaSocialApiError(
            "Error de red contactando Meta Messenger API",
            status_code=502,
        ) from exc

    try:
        raise_for_meta_response(response)
    except MetaSocialApiError:
        logger.error(
            "[meta_social] canal=messenger page_id=%s recipient_psid=%s "
            "success=false status_http=%s",
            _mask_id(page),
            _mask_id(psid),
            response.status_code,
        )
        raise

    logger.info(
        "[meta_social] canal=messenger page_id=%s recipient_psid=%s "
        "success=true status_http=%s",
        _mask_id(page),
        _mask_id(psid),
        response.status_code,
    )
    try:
        data = response.json()
        return data if isinstance(data, dict) else {"ok": True}
    except Exception:
        return {"ok": True}


class MessengerMessagingClient:
    """Cliente de alto nivel para envíos Messenger."""

    channel_name = "messenger"

    def __init__(self, settings: Optional[MetaSocialSettings] = None) -> None:
        self.settings = settings or get_settings()

    async def send_text(self, recipient_psid: str, text: str) -> dict[str, Any]:
        ready, reason = self.settings.messenger_ready()
        if not ready:
            raise MetaSocialApiError(reason or "Messenger no listo", status_code=503)
        return await send_messenger_text(
            recipient_psid,
            text,
            settings=self.settings,
            timeout_seconds=self.settings.http_timeout_seconds,
        )
