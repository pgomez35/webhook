"""Router independiente Meta Social — Instagram Messaging (Instagram Login)."""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from meta_social_config import get_settings
from meta_social_webhook_service import (
    process_webhook_payload,
    verify_signature,
)

logger = logging.getLogger("uvicorn.error")

router = APIRouter(tags=["Meta Social"])


@router.get("/webhook/meta-social")
async def verify_meta_social_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    """Verificación de suscripción webhook Meta (Instagram)."""
    settings = get_settings()
    expected = (settings.verify_token or "").strip()
    if (
        hub_mode == "subscribe"
        and expected
        and hub_verify_token == expected
        and hub_challenge is not None
    ):
        return PlainTextResponse(content=str(hub_challenge), status_code=200)
    raise HTTPException(status_code=403, detail="Verificación fallida")


@router.post("/webhook/meta-social")
async def receive_meta_social_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Recibe eventos Instagram (y a futuro Messenger en el mismo path).
    Lee el body en bytes una sola vez, valida firma HMAC y responde
    EVENT_RECEIVED 200 solo si la firma es válida.
    """
    settings = get_settings()
    # Bytes exactos del request — no usar request.json() ni reserializar.
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    check = verify_signature(
        raw_body,
        signature,
        candidates=settings.webhook_signature_candidates(),
        skip_verify=settings.skip_signature_verify,
    )
    logger.info(
        "[meta_social] firma signature_header_present=%s raw_body_length=%s "
        "signature_valid=%s matched_secret=%s",
        "true" if check.signature_header_present else "false",
        check.raw_body_length,
        "true" if check.valid else "false",
        check.matched_secret or "none",
    )
    if not check.valid:
        logger.warning("[meta_social] Firma X-Hub-Signature-256 inválida")
        raise HTTPException(status_code=403, detail="Firma inválida")

    try:
        payload: dict[str, Any] = json.loads(raw_body.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            payload = {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("[meta_social] Payload JSON inválido")
        return PlainTextResponse(content="EVENT_RECEIVED", status_code=200)

    object_name = payload.get("object")
    entries = payload.get("entry") or []
    entry_count = len(entries) if isinstance(entries, list) else 0
    logger.info(
        "[meta_social] webhook recibido object=%s entries=%s",
        object_name,
        entry_count,
    )

    background_tasks.add_task(process_webhook_payload, payload)
    return PlainTextResponse(content="EVENT_RECEIVED", status_code=200)
