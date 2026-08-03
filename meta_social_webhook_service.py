"""Servicio de webhook Instagram Meta Social (respuesta de texto)."""
from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from instagram_messaging_client import InstagramMessagingClient, MetaSocialApiError
from meta_social_config import (
    PRODUCTION_TEST_REPLY,
    PRODUCTION_TEST_TRIGGER,
    MetaSocialSettings,
    get_settings,
)
from meta_social_dedup import already_processed
from meta_social_event_parser import parse_events
from meta_social_schemas import ParsedSocialEvent, SocialChannel

logger = logging.getLogger("uvicorn.error")


@dataclass(frozen=True)
class SignatureCheckResult:
    valid: bool
    signature_header_present: bool
    raw_body_length: int
    matched_secret: Optional[str] = None  # "instagram" | "principal"


def mask_id(value: Optional[str], keep: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return "(vacío)"
    if len(text) <= keep * 2:
        return text[:2] + "***"
    return f"{text[:keep]}…{text[-keep:]}"


def truncate_text(value: Optional[str], limit: int = 100) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _hmac_sha256_hex(secret: str, raw_body: bytes) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()


def verify_signature(
    raw_body: bytes,
    signature_header: Optional[str],
    *,
    candidates: Sequence[tuple[str, str]] = (),
    app_secret: str = "",
    skip_verify: bool = False,
) -> SignatureCheckResult:
    """Valida X-Hub-Signature-256 sobre los bytes exactos del body.

    Acepta si algún secreto candidato produce el mismo HMAC (compare_digest).
    candidates: secuencia de (label, secret), p.ej. ("instagram", …), ("principal", …).
    app_secret: compatibilidad; se usa como candidato "principal" si no hay candidates.
    """
    header_present = bool(signature_header and str(signature_header).strip())
    body_len = len(raw_body) if isinstance(raw_body, (bytes, bytearray)) else 0

    if skip_verify:
        return SignatureCheckResult(
            valid=True,
            signature_header_present=header_present,
            raw_body_length=body_len,
            matched_secret="skipped",
        )

    secret_list: list[tuple[str, str]] = list(candidates)
    if not secret_list and (app_secret or "").strip():
        secret_list = [("principal", app_secret.strip())]

    if not header_present or not secret_list:
        return SignatureCheckResult(
            valid=False,
            signature_header_present=header_present,
            raw_body_length=body_len,
            matched_secret=None,
        )

    header = str(signature_header).strip()
    if not header.startswith("sha256="):
        return SignatureCheckResult(
            valid=False,
            signature_header_present=True,
            raw_body_length=body_len,
            matched_secret=None,
        )

    received = header[len("sha256=") :].strip().lower()
    if not received:
        return SignatureCheckResult(
            valid=False,
            signature_header_present=True,
            raw_body_length=body_len,
            matched_secret=None,
        )

    for label, secret in secret_list:
        secret = (secret or "").strip()
        if not secret:
            continue
        expected = _hmac_sha256_hex(secret, raw_body)
        if len(expected) != len(received):
            continue
        if hmac.compare_digest(expected, received):
            return SignatureCheckResult(
                valid=True,
                signature_header_present=True,
                raw_body_length=body_len,
                matched_secret=label,
            )

    return SignatureCheckResult(
        valid=False,
        signature_header_present=True,
        raw_body_length=body_len,
        matched_secret=None,
    )


def normalize_trigger_text(text: Optional[str]) -> str:
    """Normaliza el texto recibido para comparar con el trigger de prueba."""
    if not text:
        return ""
    return str(text).strip().upper()


def is_production_test_trigger(text: Optional[str]) -> bool:
    """True solo si el texto normalizado es exactamente TALENTUM_DEMO_2026."""
    return normalize_trigger_text(text) == PRODUCTION_TEST_TRIGGER


def is_demo_trigger(text: Optional[str]) -> bool:
    return is_production_test_trigger(text)


def select_instagram_client(
    settings: Optional[MetaSocialSettings] = None,
) -> InstagramMessagingClient:
    cfg = settings or get_settings()
    return InstagramMessagingClient(settings=cfg)


def select_client(
    channel: SocialChannel,
    settings: Optional[MetaSocialSettings] = None,
):
    """Compatibilidad: en esta fase solo Instagram Login."""
    if channel == SocialChannel.INSTAGRAM:
        return select_instagram_client(settings)
    raise MetaSocialApiError(f"Canal no soportado en esta fase: {channel}", status_code=400)


def log_event_safe(event: ParsedSocialEvent) -> None:
    """Log temporal ampliado para validar recepción en producción (sin secretos)."""
    logger.info(
        "[meta_social] evento canal=%s "
        "message.mid=%s sender.id=%s recipient.id=%s "
        "message.text=%r timestamp=%s is_echo=%s is_self=%s",
        event.channel.value,
        event.message_id or "(sin_mid)",
        mask_id(event.sender_id),
        mask_id(event.recipient_id),
        truncate_text(event.text, 100),
        event.timestamp,
        event.is_echo,
        event.is_self,
    )


async def process_event(
    event: ParsedSocialEvent,
    settings: Optional[MetaSocialSettings] = None,
) -> None:
    cfg = settings or get_settings()
    log_event_safe(event)

    if event.is_echo or event.should_ignore:
        logger.info(
            "[meta_social] Evento ignorado canal=%s echo=%s read=%s delivery=%s",
            event.channel.value,
            event.is_echo,
            event.is_read,
            event.is_delivery,
        )
        return

    dedup_id = (event.message_id or "").strip() or event.dedup_key()
    if already_processed(dedup_id, cfg.dedup_ttl_seconds):
        logger.info(
            "[meta_social] Duplicado ignorado message.mid=%s canal=%s",
            dedup_id,
            event.channel.value,
        )
        return

    if event.postback_payload:
        logger.info(
            "[meta_social] Postback canal=%s sender=%s payload=%s",
            event.channel.value,
            mask_id(event.sender_id),
            truncate_text(event.postback_payload, 80),
        )
        return

    if not cfg.enabled:
        logger.info("[meta_social] META_SOCIAL_ENABLED=false; no se envía respuesta")
        return

    if not is_production_test_trigger(event.text):
        logger.info(
            "[meta_social] Sin respuesta automática (texto no es %s) recibido=%r",
            PRODUCTION_TEST_TRIGGER,
            truncate_text(event.text, 100),
        )
        return

    logger.info(
        "[meta_social] Trigger de prueba confirmado texto_normalizado=%r (coincide con %s)",
        normalize_trigger_text(event.text),
        PRODUCTION_TEST_TRIGGER,
    )

    client = select_instagram_client(cfg)
    await client.send_text(event.sender_id, PRODUCTION_TEST_REPLY)
    logger.info(
        "[meta_social] Respuesta texto enviada canal=instagram recipient=%s",
        mask_id(event.sender_id),
    )


async def process_webhook_payload(
    payload: dict[str, Any],
    settings: Optional[MetaSocialSettings] = None,
) -> None:
    cfg = settings or get_settings()
    events = parse_events(payload)
    for event in events:
        try:
            await process_event(event, cfg)
        except MetaSocialApiError as exc:
            logger.error(
                "[meta_social] Error Meta status=%s canal=%s: %s",
                exc.status_code,
                event.channel.value,
                str(exc),
            )
        except Exception:
            logger.exception(
                "[meta_social] Error inesperado procesando evento canal=%s",
                event.channel.value,
            )
