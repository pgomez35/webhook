"""Servicio de webhook Instagram Meta Social (respuesta demo con Generic Template)."""
from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from instagram_messaging_client import InstagramMessagingClient, MetaSocialApiError
from meta_social_config import (
    PRODUCTION_TEST_REPLY,
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
    matched_secret: Optional[str] = None


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
    if not text:
        return ""
    return str(text).strip().upper()


def is_demo_trigger(
    text: Optional[str],
    settings: Optional[MetaSocialSettings] = None,
) -> bool:
    cfg = settings or get_settings()
    return normalize_trigger_text(text) == cfg.normalized_demo_trigger()


def is_production_test_trigger(
    text: Optional[str],
    settings: Optional[MetaSocialSettings] = None,
) -> bool:
    return is_demo_trigger(text, settings)


def select_instagram_client(
    settings: Optional[MetaSocialSettings] = None,
) -> InstagramMessagingClient:
    cfg = settings or get_settings()
    return InstagramMessagingClient(settings=cfg)


def select_client(
    channel: SocialChannel,
    settings: Optional[MetaSocialSettings] = None,
):
    if channel == SocialChannel.INSTAGRAM:
        return select_instagram_client(settings)
    raise MetaSocialApiError(f"Canal no soportado: {channel}", status_code=400)


def log_event_safe(event: ParsedSocialEvent, *, debug: bool = False) -> None:
    if debug:
        logger.info(
            "[meta_social] evento canal=%s "
            "message.mid=%s sender.id=%s recipient.id=%s "
            "message.text=%r timestamp=%s is_echo=%s is_self=%s "
            "entry.id=%s",
            event.channel.value,
            event.message_id or "(sin_mid)",
            mask_id(event.sender_id),
            mask_id(event.recipient_id),
            truncate_text(event.text, 100),
            event.timestamp,
            event.is_echo,
            event.is_self,
            event.entry_id or "(sin_entry)",
        )
        return

    event_type = "echo" if event.is_echo else event.event_type
    logger.info(
        "[meta_social] evento canal=%s mid=%s sender=%s tipo=%s",
        event.channel.value,
        event.message_id or "(sin_mid)",
        mask_id(event.sender_id),
        event_type,
    )


async def send_instagram_demo_card(
    recipient_igsid: str,
    settings: MetaSocialSettings,
    *,
    entry_ig_user_id: Optional[str] = None,
) -> None:
    """
    Una sola Generic Template promocional.
    Reemplaza imagen + texto + enlace largo.
    """
    configured_ig = (settings.instagram_account_id or "").strip()
    if entry_ig_user_id and configured_ig and entry_ig_user_id != configured_ig:
        logger.warning(
            "[meta_social] canal=instagram entry.id=%s distinto de "
            "META_SOCIAL_INSTAGRAM_ACCOUNT_ID=%s; se usa la config del canal",
            mask_id(entry_ig_user_id),
            mask_id(configured_ig),
        )

    client = select_instagram_client(settings)
    await client.send_demo_card(recipient_igsid)


async def process_event(
    event: ParsedSocialEvent,
    settings: Optional[MetaSocialSettings] = None,
) -> None:
    cfg = settings or get_settings()
    log_event_safe(event, debug=cfg.debug)

    if event.is_echo or event.should_ignore:
        logger.info(
            "[meta_social] Evento ignorado canal=%s tipo=%s echo=%s",
            event.channel.value,
            event.event_type,
            event.is_echo,
        )
        return

    dedup_id = (event.message_id or "").strip() or event.dedup_key()
    if already_processed(dedup_id, cfg.dedup_ttl_seconds, channel="instagram"):
        logger.info(
            "[meta_social] Duplicado ignorado mid=%s canal=%s",
            dedup_id,
            event.channel.value,
        )
        return

    if event.postback_payload:
        logger.info(
            "[meta_social] Postback canal=%s sender=%s",
            event.channel.value,
            mask_id(event.sender_id),
        )
        return

    if not cfg.enabled:
        logger.info("[meta_social] META_SOCIAL_ENABLED=false; no se envía respuesta")
        return

    if event.channel != SocialChannel.INSTAGRAM:
        logger.info(
            "[meta_social] Canal no Instagram ignorado en esta fase: %s",
            event.channel.value,
        )
        return

    if not is_demo_trigger(event.text, cfg):
        logger.info(
            "[meta_social] Sin respuesta automática (texto no es trigger) recibido=%r",
            truncate_text(event.text, 80),
        )
        return

    logger.info(
        "[meta_social] Trigger confirmado mid=%s sender=%s (IGSID) entry.id=%s trigger=%s",
        event.message_id or "(sin_mid)",
        mask_id(event.sender_id),
        mask_id(event.entry_id),
        cfg.normalized_demo_trigger(),
    )

    rich_ok, rich_reason = cfg.rich_demo_ready()
    if rich_ok:
        try:
            # recipient = sender.id (IGSID); ig_user_id desde config del canal
            await send_instagram_demo_card(
                event.sender_id,
                cfg,
                entry_ig_user_id=event.entry_id,
            )
            logger.info(
                "[meta_social] Tarjeta demo Instagram enviada recipient_igsid=%s",
                mask_id(event.sender_id),
            )
        except MetaSocialApiError as exc:
            logger.error(
                "[meta_social] Fallo tarjeta/fallback recipient=%s status=%s error=%s",
                mask_id(event.sender_id),
                exc.status_code,
                str(exc)[:180],
            )
        return

    if cfg.rich_demo_enabled:
        logger.warning(
            "[meta_social] Rich demo habilitado pero no listo (%s); "
            "fallback texto simple",
            rich_reason,
        )

    client = select_instagram_client(cfg)
    try:
        await client.send_text(event.sender_id, PRODUCTION_TEST_REPLY)
        logger.info(
            "[meta_social] Respuesta texto enviada canal=instagram recipient=%s",
            mask_id(event.sender_id),
        )
    except MetaSocialApiError as exc:
        logger.error(
            "[meta_social] Fallo envío texto recipient=%s status=%s error=%s",
            mask_id(event.sender_id),
            exc.status_code,
            str(exc)[:180],
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
