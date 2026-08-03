"""Cliente Instagram Messaging API (Instagram Login) en la raíz del backend.

Usa graph.instagram.com + META_SOCIAL_INSTAGRAM_ACCESS_TOKEN.
No usa Page Access Token ni graph.facebook.com.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from meta_social_config import (
    INSTAGRAM_BUTTON_TITLE,
    INSTAGRAM_CARD_SUBTITLE,
    INSTAGRAM_CARD_TITLE,
    INSTAGRAM_FALLBACK_TEXT,
    MetaSocialSettings,
    get_settings,
)

logger = logging.getLogger("uvicorn.error")


class MetaSocialApiError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        error_code: Optional[int] = None,
        error_type: Optional[str] = None,
        retry_after: Optional[str] = None,
        error_body: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.error_type = error_type
        self.retry_after = retry_after
        self.error_body = error_body or {}


def raise_for_meta_response(response: httpx.Response) -> None:
    if response.is_success:
        return

    try:
        body = response.json()
        body = body if isinstance(body, dict) else {}
    except Exception:
        body = {}

    error = body.get("error") if isinstance(body.get("error"), dict) else {}
    message = str(error.get("message") or response.reason_phrase or "Meta API error")
    lowered = message.lower()
    if "token" in lowered or "secret" in lowered:
        message = "Error de autenticación o autorización con Meta API"

    status = response.status_code
    retry_after = response.headers.get("Retry-After")
    common = dict(
        error_code=error.get("code"),
        error_type=error.get("type"),
        error_body=body,
    )

    if status == 400:
        raise MetaSocialApiError(
            f"Solicitud inválida (400): {message}",
            status_code=400,
            retry_after=retry_after,
            **common,
        )
    if status == 401:
        raise MetaSocialApiError(
            "No autorizado (401): credenciales Meta Social inválidas o expiradas",
            status_code=401,
            retry_after=retry_after,
            **common,
        )
    if status == 429:
        raise MetaSocialApiError(
            "Límite de tasa excedido (429)",
            status_code=429,
            retry_after=retry_after,
            **common,
        )
    if status >= 500:
        raise MetaSocialApiError(
            f"Error del servidor Meta ({status})",
            status_code=status,
            retry_after=retry_after,
            **common,
        )
    raise MetaSocialApiError(
        f"Error Meta API ({status}): {message}",
        status_code=status,
        retry_after=retry_after,
        **common,
    )


def _mask_id(value: str, keep: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return "(vacío)"
    if len(text) <= keep * 2:
        return text[:2] + "***"
    return f"{text[:keep]}…{text[-keep:]}"


def build_instagram_demo_card_payload(
    recipient_igsid: str,
    image_url: str,
    whatsapp_url: str,
) -> dict[str, Any]:
    """Generic template Instagram Login (sin messaging_type)."""
    return {
        "recipient": {"id": recipient_igsid},
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "generic",
                    "elements": [
                        {
                            "title": INSTAGRAM_CARD_TITLE,
                            "subtitle": INSTAGRAM_CARD_SUBTITLE,
                            "image_url": image_url,
                            "buttons": [
                                {
                                    "type": "web_url",
                                    "url": whatsapp_url,
                                    "title": INSTAGRAM_BUTTON_TITLE,
                                }
                            ],
                        }
                    ],
                },
            }
        },
    }


async def enviar_tarjeta_demo_instagram(
    recipient_igsid: str,
    ig_user_id: str,
    instagram_access_token: str,
    image_url: str,
    whatsapp_url: str,
    api_version: str,
    *,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    """
    POST https://graph.instagram.com/{api_version}/{ig_user_id}/messages
    Generic Template promocional. No registra el access token.
    """
    version = (api_version or "v21.0").strip()
    if not version.startswith("v"):
        version = f"v{version}"
    ig_id = (ig_user_id or "").strip()
    token = (instagram_access_token or "").strip()
    igsid = (recipient_igsid or "").strip()
    if not ig_id or not token or not igsid:
        raise MetaSocialApiError(
            "ig_user_id, access token o recipient_igsid ausente",
            status_code=503,
        )

    endpoint = f"https://graph.instagram.com/{version}/{ig_id}/messages"
    payload = build_instagram_demo_card_payload(igsid, image_url, whatsapp_url)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    logger.info(
        "[meta_social] canal=instagram ig_user_id=%s recipient_igsid=%s "
        "tipo_mensaje=generic_template endpoint=%s enviado=pending",
        _mask_id(ig_id),
        _mask_id(igsid),
        endpoint,
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds)) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        logger.error(
            "[meta_social] canal=instagram ig_user_id=%s recipient_igsid=%s "
            "tipo_mensaje=generic_template endpoint=%s enviado=false error=Timeout",
            _mask_id(ig_id),
            _mask_id(igsid),
            endpoint,
        )
        raise MetaSocialApiError(
            "Timeout Instagram Messaging API",
            status_code=504,
        ) from exc
    except httpx.HTTPError as exc:
        logger.error(
            "[meta_social] canal=instagram ig_user_id=%s recipient_igsid=%s "
            "tipo_mensaje=generic_template endpoint=%s enviado=false error=%s",
            _mask_id(ig_id),
            _mask_id(igsid),
            endpoint,
            type(exc).__name__,
        )
        raise MetaSocialApiError(
            "Error de red Instagram Messaging API",
            status_code=502,
        ) from exc

    try:
        raise_for_meta_response(response)
    except MetaSocialApiError as exc:
        logger.error(
            "[meta_social] canal=instagram ig_user_id=%s recipient_igsid=%s "
            "tipo_mensaje=generic_template endpoint=%s enviado=false "
            "status_code=%s error_json=%s",
            _mask_id(ig_id),
            _mask_id(igsid),
            endpoint,
            exc.status_code,
            exc.error_body,
        )
        raise

    logger.info(
        "[meta_social] canal=instagram ig_user_id=%s recipient_igsid=%s "
        "tipo_mensaje=generic_template endpoint=%s enviado=true status_code=%s",
        _mask_id(ig_id),
        _mask_id(igsid),
        endpoint,
        response.status_code,
    )
    try:
        data = response.json()
        return data if isinstance(data, dict) else {"raw": data}
    except Exception:
        return {"ok": True}


class InstagramMessagingClient:
    channel_name = "instagram"

    def __init__(self, settings: Optional[MetaSocialSettings] = None) -> None:
        self.settings = settings or get_settings()

    def _assert_enabled(self) -> None:
        if not self.settings.enabled:
            raise MetaSocialApiError(
                "META_SOCIAL_ENABLED=false: envíos deshabilitados",
                status_code=503,
            )

    def _assert_credentials(self) -> tuple[str, str]:
        account_id = (self.settings.instagram_account_id or "").strip()
        token = (self.settings.instagram_access_token or "").strip()
        if not account_id:
            raise MetaSocialApiError(
                "META_SOCIAL_INSTAGRAM_ACCOUNT_ID no configurado",
                status_code=503,
            )
        if not token:
            raise MetaSocialApiError(
                "META_SOCIAL_INSTAGRAM_ACCESS_TOKEN no configurado",
                status_code=503,
            )
        return account_id, token

    def messages_url(self) -> str:
        account_id, _ = self._assert_credentials()
        return f"{self.settings.instagram_graph_base_url}/{account_id}/messages"

    def build_text_payload(self, recipient_id: str, text: str) -> dict[str, Any]:
        return {
            "recipient": {"id": recipient_id},
            "message": {"text": text},
        }

    def build_image_payload(self, recipient_id: str, image_url: str) -> dict[str, Any]:
        return {
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": "image",
                    "payload": {"url": image_url},
                }
            },
        }

    def build_demo_card_payload(
        self,
        recipient_igsid: str,
        image_url: str,
        whatsapp_url: str,
    ) -> dict[str, Any]:
        return build_instagram_demo_card_payload(
            recipient_igsid, image_url, whatsapp_url
        )

    async def _post_message(
        self,
        *,
        message_type: str,
        recipient_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self._assert_enabled()
        _, token = self._assert_credentials()
        url = self.messages_url()
        timeout = httpx.Timeout(self.settings.http_timeout_seconds)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            logger.error(
                "[meta_social] canal=instagram envío tipo=%s recipient=%s "
                "success=false error=TimeoutException",
                message_type,
                _mask_id(recipient_id),
            )
            raise MetaSocialApiError(
                "Timeout al contactar Instagram Messaging API",
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            logger.error(
                "[meta_social] canal=instagram envío tipo=%s recipient=%s "
                "success=false error=%s",
                message_type,
                _mask_id(recipient_id),
                type(exc).__name__,
            )
            raise MetaSocialApiError(
                "Error de red contactando Instagram Messaging API",
                status_code=502,
            ) from exc

        try:
            raise_for_meta_response(response)
        except MetaSocialApiError as exc:
            logger.error(
                "[meta_social] canal=instagram envío tipo=%s recipient=%s "
                "http_status=%s success=false meta_code=%s error=%s",
                message_type,
                _mask_id(recipient_id),
                exc.status_code,
                exc.error_code,
                str(exc)[:180],
            )
            raise

        logger.info(
            "[meta_social] canal=instagram envío tipo=%s recipient=%s "
            "http_status=%s success=true",
            message_type,
            _mask_id(recipient_id),
            response.status_code,
        )
        try:
            data = response.json()
            return data if isinstance(data, dict) else {"raw": data}
        except Exception:
            return {"ok": True}

    async def send_text(self, recipient_id: str, text: str) -> dict[str, Any]:
        payload = self.build_text_payload(recipient_id, text)
        return await self._post_message(
            message_type="text",
            recipient_id=recipient_id,
            payload=payload,
        )

    async def send_image(self, recipient_id: str, image_url: str) -> dict[str, Any]:
        payload = self.build_image_payload(recipient_id, image_url)
        return await self._post_message(
            message_type="image",
            recipient_id=recipient_id,
            payload=payload,
        )

    async def send_demo_card(self, recipient_igsid: str) -> dict[str, Any]:
        """
        Envía una sola Generic Template promocional.
        Si Meta la rechaza, un único fallback de texto corto (sin URL larga).
        """
        self._assert_enabled()
        ig_user_id, token = self._assert_credentials()
        image_url = (self.settings.demo_image_url or "").strip()
        whatsapp_url = (self.settings.whatsapp_url or "").strip()

        try:
            return await enviar_tarjeta_demo_instagram(
                recipient_igsid=recipient_igsid,
                ig_user_id=ig_user_id,
                instagram_access_token=token,
                image_url=image_url,
                whatsapp_url=whatsapp_url,
                api_version=self.settings.graph_api_version,
                timeout_seconds=self.settings.http_timeout_seconds,
            )
        except MetaSocialApiError:
            logger.warning(
                "[meta_social] canal=instagram generic_template rechazada; "
                "fallback único recipient_igsid=%s",
                _mask_id(recipient_igsid),
            )
            try:
                return await self.send_text(recipient_igsid, INSTAGRAM_FALLBACK_TEXT)
            except MetaSocialApiError as fb_exc:
                logger.error(
                    "[meta_social] canal=instagram fallback falló "
                    "recipient_igsid=%s status=%s error=%s",
                    _mask_id(recipient_igsid),
                    fb_exc.status_code,
                    str(fb_exc)[:180],
                )
                raise
