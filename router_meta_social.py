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
    Recibe eventos Instagram.
    Lee body en bytes, valida firma, responde 200 EVENT_RECEIVED de inmediato
    y procesa el envío en background.
    """
    settings = get_settings()
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    if not verify_signature(
        raw_body,
        signature,
        settings.app_secret,
        skip_verify=settings.skip_signature_verify,
    ):
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
