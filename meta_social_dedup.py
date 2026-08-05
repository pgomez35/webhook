"""Deduplicación de eventos Instagram Meta Social.

Prefijo exclusivo: meta_social:instagram:event:{message_id}
No reutiliza claves ni helpers de WhatsApp.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger("uvicorn.error")

DEDUP_PREFIX = "meta_social:instagram:event:"
DEDUP_PREFIX_MESSENGER = "meta_social:messenger:event:"
DEDUP_PREFIX_MESSENGER_POSTBACK = "meta_social:messenger:postback:"
DEFAULT_TTL_SECONDS = 24 * 3600


def dedup_prefix_for_channel(channel: str | None = None) -> str:
    ch = (channel or "").strip().lower()
    if ch == "messenger":
        return DEDUP_PREFIX_MESSENGER
    if ch in {"messenger_postback", "messenger:postback"}:
        return DEDUP_PREFIX_MESSENGER_POSTBACK
    return DEDUP_PREFIX

_memory_lock = threading.Lock()
_memory_seen: dict[str, float] = {}
_redis_client = None
_redis_checked = False


def _try_get_redis():
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client
    _redis_checked = True

    # Independiente de WhatsApp: WhatsApp ya no usa Redis (ver redis_client.py).
    redis_url = (os.getenv("REDIS_URL") or os.getenv("META_SOCIAL_REDIS_URL") or "").strip()
    if not redis_url:
        logger.info(
            "[meta_social] Dedup memoria: REDIS_URL/META_SOCIAL_REDIS_URL no configurada"
        )
        _redis_client = None
        return None

    # No loguear la URL (puede contener credenciales). Solo esquema/host enmascarado.
    scheme = "rediss" if redis_url.startswith("rediss://") else (
        "redis" if redis_url.startswith("redis://") else "otro"
    )
    try:
        import redis  # type: ignore

        # timeout corto: no bloquear el webhook si Redis está caído
        client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        client.ping()
        _redis_client = client
        logger.info(
            "[meta_social] Deduplicación Instagram con Redis activa scheme=%s",
            scheme,
        )
        return _redis_client
    except Exception as exc:
        # Causa típica en este proyecto: REDIS_URL apunta a un servicio
        # inaccesible / sin Redis real; WhatsApp ya migró a PostgreSQL.
        logger.warning(
            "[meta_social] Redis no disponible para dedup; se usará memoria: "
            "%s scheme=%s (fallback OK; no bloquea webhook)",
            type(exc).__name__,
            scheme,
        )
        _redis_client = None
        return None


def _purge_memory(now: float) -> None:
    expired = [key for key, exp in _memory_seen.items() if exp <= now]
    for key in expired:
        _memory_seen.pop(key, None)


def already_processed(
    message_id: Optional[str],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    *,
    channel: Optional[str] = None,
) -> bool:
    if not message_id:
        return False

    key = f"{dedup_prefix_for_channel(channel)}{message_id}"
    client = _try_get_redis()
    if client is not None:
        try:
            created = client.set(key, "1", nx=True, ex=max(1, int(ttl_seconds)))
            return not bool(created)
        except Exception as exc:
            logger.warning(
                "[meta_social] Fallo Redis dedup; fallback memoria: %s",
                type(exc).__name__,
            )

    now = time.time()
    with _memory_lock:
        _purge_memory(now)
        if key in _memory_seen and _memory_seen[key] > now:
            return True
        _memory_seen[key] = now + max(1, int(ttl_seconds))
        return False


def reset_dedup_for_tests() -> None:
    global _redis_client, _redis_checked
    with _memory_lock:
        _memory_seen.clear()
    _redis_client = None
    _redis_checked = False
