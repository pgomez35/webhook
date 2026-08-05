"""Cliente Facebook Messenger Send API (Page Messaging).

Usa graph.facebook.com + META_SOCIAL_FACEBOOK_PAGE_ACCESS_TOKEN.
No reutiliza tokens de Instagram ni WhatsApp.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from instagram_messaging_client import MetaSocialApiError, raise_for_meta_response
from meta_social_config import (
    MESSENGER_CARD_POSTBACK_BUTTON_TITLE,
    MESSENGER_CARD_SUBTITLE,
    MESSENGER_CARD_TITLE,
    MESSENGER_CARD_WEB_BUTTON_TITLE,
    MetaSocialSettings,
    get_settings,
    validate_https_public_url,
)

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


def _resolve_page_auth(
    *,
    recipient_psid: str,
    page_id: Optional[str],
    page_access_token: Optional[str],
    api_version: Optional[str],
    settings: MetaSocialSettings,
) -> tuple[str, str, str, str]:
    psid = (recipient_psid or "").strip()
    page = (page_id or settings.facebook_page_id or "").strip()
    token = (page_access_token or settings.facebook_page_access_token or "").strip()
    version = (api_version or _graph_version(settings)).strip()
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
    return psid, page, token, version


async def _post_messenger_payload(
    *,
    endpoint: str,
    payload: dict[str, Any],
    token: str,
    page: str,
    psid: str,
    envio_tipo: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    logger.info(
        "[meta_social] canal=messenger page_id=%s recipient_psid=%s "
        "envio tipo=%s endpoint_host=graph.facebook.com",
        _mask_id(page),
        _mask_id(psid),
        envio_tipo,
    )
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds)) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        logger.error(
            "[meta_social] canal=messenger page_id=%s recipient_psid=%s "
            "tipo=%s success=false status_http=504 error=timeout",
            _mask_id(page),
            _mask_id(psid),
            envio_tipo,
        )
        raise MetaSocialApiError(
            "Timeout al contactar Meta Messenger API",
            status_code=504,
        ) from exc
    except httpx.HTTPError as exc:
        logger.error(
            "[meta_social] canal=messenger page_id=%s recipient_psid=%s "
            "tipo=%s success=false status_http=502 error=%s",
            _mask_id(page),
            _mask_id(psid),
            envio_tipo,
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
            "tipo=%s success=false status_http=%s",
            _mask_id(page),
            _mask_id(psid),
            envio_tipo,
            response.status_code,
        )
        raise

    logger.info(
        "[meta_social] canal=messenger page_id=%s recipient_psid=%s "
        "tipo=%s success=true status_http=%s",
        _mask_id(page),
        _mask_id(psid),
        envio_tipo,
        response.status_code,
    )
    try:
        data = response.json()
        return data if isinstance(data, dict) else {"ok": True}
    except Exception:
        return {"ok": True}


def build_messenger_generic_template_payload(
    recipient_psid: str,
    *,
    image_url: str,
    web_url: str,
    postback_payload: str,
) -> dict[str, Any]:
    return {
        "recipient": {"id": recipient_psid},
        "messaging_type": "RESPONSE",
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "generic",
                    "elements": [
                        {
                            "title": MESSENGER_CARD_TITLE,
                            "subtitle": MESSENGER_CARD_SUBTITLE,
                            "image_url": image_url,
                            "default_action": {
                                "type": "web_url",
                                "url": web_url,
                            },
                            "buttons": [
                                {
                                    "type": "web_url",
                                    "url": web_url,
                                    "title": MESSENGER_CARD_WEB_BUTTON_TITLE,
                                },
                                {
                                    "type": "postback",
                                    "title": MESSENGER_CARD_POSTBACK_BUTTON_TITLE,
                                    "payload": postback_payload,
                                },
                            ],
                        }
                    ],
                },
            }
        },
    }


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
    """POST messages API; recipient.id = PSID (sender.id), nunca Page ID."""
    cfg = settings or get_settings()
    psid, page, token, version = _resolve_page_auth(
        recipient_psid=recipient_psid,
        page_id=page_id,
        page_access_token=page_access_token,
        api_version=api_version,
        settings=cfg,
    )
    endpoint = f"https://graph.facebook.com/{version}/{page}/messages"
    payload = {
        "recipient": {"id": psid},
        "messaging_type": "RESPONSE",
        "message": {"text": text},
    }
    return await _post_messenger_payload(
        endpoint=endpoint,
        payload=payload,
        token=token,
        page=page,
        psid=psid,
        envio_tipo="text",
        timeout_seconds=timeout_seconds,
    )


async def send_messenger_generic_template(
    recipient_psid: str,
    image_url: str,
    web_url: str,
    postback_payload: str,
    *,
    page_id: Optional[str] = None,
    page_access_token: Optional[str] = None,
    api_version: Optional[str] = None,
    settings: Optional[MetaSocialSettings] = None,
    timeout_seconds: float = 20.0,
) -> bool:
    """Envía Generic Template. True si Meta acepta; False si falla."""
    cfg = settings or get_settings()

    if settings is not None:
        if not cfg.messenger_card_enabled:
            logger.info(
                "[meta_social] canal=messenger tipo=generic_template "
                "success=false motivo=META_SOCIAL_MESSENGER_CARD_ENABLED=false"
            )
            return False
        base_ready, base_reason = cfg.messenger_ready()
        if not base_ready:
            logger.info(
                "[meta_social] canal=messenger tipo=generic_template "
                "success=false motivo=%s",
                base_reason,
            )
            return False
    else:
        ready, reason = cfg.messenger_card_ready()
        if not ready:
            logger.info(
                "[meta_social] canal=messenger tipo=generic_template "
                "success=false motivo=%s",
                reason,
            )
            return False

    ok_img, reason_img = validate_https_public_url(
        image_url, label="META_SOCIAL_MESSENGER_CARD_IMAGE_URL"
    )
    ok_web, reason_web = validate_https_public_url(
        web_url, label="META_SOCIAL_MESSENGER_CARD_WEB_URL"
    )
    if not ok_img:
        logger.info(
            "[meta_social] canal=messenger tipo=generic_template "
            "success=false motivo=%s",
            reason_img,
        )
        return False
    if not ok_web:
        logger.info(
            "[meta_social] canal=messenger tipo=generic_template "
            "success=false motivo=%s",
            reason_web,
        )
        return False
    if not (postback_payload or "").strip():
        logger.info(
            "[meta_social] canal=messenger tipo=generic_template "
            "success=false motivo=postback vacío"
        )
        return False

    try:
        psid, page, token, version = _resolve_page_auth(
            recipient_psid=recipient_psid,
            page_id=page_id,
            page_access_token=page_access_token,
            api_version=api_version,
            settings=cfg,
        )
    except MetaSocialApiError as exc:
        logger.error(
            "[meta_social] canal=messenger tipo=generic_template "
            "success=false status_http=%s error=%s",
            exc.status_code,
            str(exc)[:180],
        )
        return False

    endpoint = f"https://graph.facebook.com/{version}/{page}/messages"
    payload = build_messenger_generic_template_payload(
        psid,
        image_url=image_url.strip(),
        web_url=web_url.strip(),
        postback_payload=postback_payload.strip(),
    )
    try:
        await _post_messenger_payload(
            endpoint=endpoint,
            payload=payload,
            token=token,
            page=page,
            psid=psid,
            envio_tipo="generic_template",
            timeout_seconds=timeout_seconds,
        )
        return True
    except MetaSocialApiError as exc:
        logger.error(
            "[meta_social] canal=messenger tipo=generic_template "
            "success=false status_http=%s error=%s",
            exc.status_code,
            str(exc)[:180],
        )
        return False


class MessengerMessagingClient:
    """Cliente de alto nivel para envios Messenger."""

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

    async def send_generic_template(
        self,
        recipient_psid: str,
        *,
        image_url: Optional[str] = None,
        web_url: Optional[str] = None,
        postback_payload: Optional[str] = None,
    ) -> bool:
        return await send_messenger_generic_template(
            recipient_psid,
            image_url if image_url is not None else self.settings.messenger_card_image_url,
            web_url if web_url is not None else self.settings.messenger_card_web_url,
            postback_payload
            if postback_payload is not None
            else self.settings.normalized_messenger_card_postback(),
            settings=self.settings,
            timeout_seconds=self.settings.http_timeout_seconds,
        )
