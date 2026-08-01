"""Webhook mínimo Meta Social (Messenger / Instagram).

Aislado de WhatsApp Cloud API. No envía mensajes ni reutiliza WHATSAPP_*.
"""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

load_dotenv()

logger = logging.getLogger("uvicorn.error")

router = APIRouter(tags=["Meta Social"])


@router.get("/webhook/meta-social")
async def verify_meta_social_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    """Verificación de suscripción webhook Meta (hub.challenge en texto plano)."""
    expected = (os.getenv("META_SOCIAL_VERIFY_TOKEN") or "").strip()
    if (
        hub_mode == "subscribe"
        and expected
        and hub_verify_token == expected
        and hub_challenge is not None
    ):
        return PlainTextResponse(content=str(hub_challenge), status_code=200)
    raise HTTPException(status_code=403, detail="Verificación fallida")


@router.post("/webhook/meta-social")
async def receive_meta_social_webhook(request: Request):
    """Recibe eventos Messenger/Instagram sin procesarlos ni enviar respuestas."""
    try:
        payload = await request.json()
    except Exception:
        payload = None

    if isinstance(payload, dict):
        object_name = payload.get("object")
        entries = payload.get("entry") or []
        entry_count = len(entries) if isinstance(entries, list) else 0
        logger.info(
            "[meta_social] webhook recibido object=%s entries=%s",
            object_name,
            entry_count,
        )
    else:
        logger.info("[meta_social] webhook recibido sin JSON de objeto")

    return PlainTextResponse(content="EVENT_RECEIVED", status_code=200)
