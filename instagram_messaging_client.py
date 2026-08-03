"""Cliente Instagram Messaging API (Instagram Login) en la raíz del backend.

Usa graph.instagram.com + META_SOCIAL_INSTAGRAM_ACCESS_TOKEN.
No usa Page Access Token ni graph.facebook.com.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from meta_social_config import MetaSocialSettings, get_settings

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

    async def send_text(self, recipient_id: str, text: str) -> dict[str, Any]:
        self._assert_enabled()
        _, token = self._assert_credentials()
        url = self.messages_url()
        payload = self.build_text_payload(recipient_id, text)
        timeout = httpx.Timeout(self.settings.http_timeout_seconds)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            logger.error("[meta_social] Timeout enviando a Instagram Messaging")
            raise MetaSocialApiError(
                "Timeout al contactar Instagram Messaging API",
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            logger.error(
                "[meta_social] Error HTTP de red en Instagram: %s",
                type(exc).__name__,
            )
            raise MetaSocialApiError(
                "Error de red contactando Instagram Messaging API",
                status_code=502,
            ) from exc

        raise_for_meta_response(response)
        try:
            data = response.json()
            return data if isinstance(data, dict) else {"raw": data}
        except Exception:
            return {"ok": True}
