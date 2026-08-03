"""Cliente Instagram Messaging API (Instagram Login) en la raíz del backend.

Usa graph.instagram.com + META_SOCIAL_INSTAGRAM_ACCESS_TOKEN.
No usa Page Access Token ni graph.facebook.com.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from meta_social_config import (
    INSTAGRAM_LOGIN_SUPPORTS_WEB_URL_BUTTON,
    WHATSAPP_CTA_BUTTON_TITLE,
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
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.error_type = error_type
        self.retry_after = retry_after


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

    if status == 400:
        raise MetaSocialApiError(
            f"Solicitud inválida (400): {message}",
            status_code=400,
            error_code=error.get("code"),
            error_type=error.get("type"),
        )
    if status == 401:
        raise MetaSocialApiError(
            "No autorizado (401): credenciales Meta Social inválidas o expiradas",
            status_code=401,
            error_code=error.get("code"),
            error_type=error.get("type"),
        )
    if status == 429:
        raise MetaSocialApiError(
            "Límite de tasa excedido (429)",
            status_code=429,
            error_code=error.get("code"),
            error_type=error.get("type"),
            retry_after=retry_after,
        )
    if status >= 500:
        raise MetaSocialApiError(
            f"Error del servidor Meta ({status})",
            status_code=status,
            error_code=error.get("code"),
            error_type=error.get("type"),
            retry_after=retry_after,
        )
    raise MetaSocialApiError(
        f"Error Meta API ({status}): {message}",
        status_code=status,
        error_code=error.get("code"),
        error_type=error.get("type"),
        retry_after=retry_after,
    )


def _mask_recipient(recipient_id: str, keep: int = 4) -> str:
    text = str(recipient_id or "").strip()
    if not text:
        return "(vacío)"
    if len(text) <= keep * 2:
        return text[:2] + "***"
    return f"{text[:keep]}…{text[-keep:]}"


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
        """Payload oficial Instagram Login: attachment type=image + url HTTPS."""
        return {
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": "image",
                    "payload": {"url": image_url},
                }
            },
        }

    def build_whatsapp_cta_text_payload(
        self,
        recipient_id: str,
        whatsapp_url: str,
    ) -> dict[str, Any]:
        text = f"👉 Probar demo por WhatsApp:\n{whatsapp_url}"
        return self.build_text_payload(recipient_id, text)

    def build_whatsapp_cta_button_payload(
        self,
        recipient_id: str,
        whatsapp_url: str,
        *,
        title: str = WHATSAPP_CTA_BUTTON_TITLE,
    ) -> dict[str, Any]:
        """Payload tipo button/web_url (solo si la modalidad lo admite oficialmente)."""
        return {
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "button",
                        "text": "Continúa la demo en WhatsApp:",
                        "buttons": [
                            {
                                "type": "web_url",
                                "url": whatsapp_url,
                                "title": title[:20],
                            }
                        ],
                    },
                }
            },
        }

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
                "[meta_social] envío tipo=%s recipient=%s success=false "
                "error=TimeoutException",
                message_type,
                _mask_recipient(recipient_id),
            )
            raise MetaSocialApiError(
                "Timeout al contactar Instagram Messaging API",
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            logger.error(
                "[meta_social] envío tipo=%s recipient=%s success=false "
                "error=%s",
                message_type,
                _mask_recipient(recipient_id),
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
                "[meta_social] envío tipo=%s recipient=%s http_status=%s "
                "success=false meta_code=%s error=%s",
                message_type,
                _mask_recipient(recipient_id),
                exc.status_code,
                exc.error_code,
                str(exc)[:180],
            )
            raise

        logger.info(
            "[meta_social] envío tipo=%s recipient=%s http_status=%s success=true",
            message_type,
            _mask_recipient(recipient_id),
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

    async def send_whatsapp_cta(
        self,
        recipient_id: str,
        whatsapp_url: str,
    ) -> dict[str, Any]:
        """
        CTA hacia WhatsApp.

        Si Instagram Login no documenta web_url con User Access Token,
        envía enlace en texto (documentado oficialmente como text/link).
        Si se intenta botón y falla, hace fallback a texto.
        """
        url = (whatsapp_url or "").strip()
        if not url:
            raise MetaSocialApiError(
                "META_SOCIAL_WHATSAPP_URL no configurado",
                status_code=503,
            )

        if INSTAGRAM_LOGIN_SUPPORTS_WEB_URL_BUTTON:
            try:
                payload = self.build_whatsapp_cta_button_payload(recipient_id, url)
                return await self._post_message(
                    message_type="whatsapp_cta_button",
                    recipient_id=recipient_id,
                    payload=payload,
                )
            except MetaSocialApiError:
                logger.warning(
                    "[meta_social] CTA botón falló; fallback texto recipient=%s",
                    _mask_recipient(recipient_id),
                )

        payload = self.build_whatsapp_cta_text_payload(recipient_id, url)
        return await self._post_message(
            message_type="whatsapp_cta_text",
            recipient_id=recipient_id,
            payload=payload,
        )
