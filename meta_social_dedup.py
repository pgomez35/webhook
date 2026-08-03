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
DEFAULT_TTL_SECONDS = 24 * 3600

_memory_lock = threading.Lock()
_memory_seen: dict[str, float] = {}
_redis_client = None
_redis_checked = False


def _try_get_redis():
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client
    _redis_checked = True

    redis_url = (os.getenv("REDIS_URL") or os.getenv("META_SOCIAL_REDIS_URL") or "").strip()
    if not redis_url:
        _redis_client = None
        return None

    try:
        import redis  # type: ignore

        client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=1)
        client.ping()
        _redis_client = client
        logger.info("[meta_social] Deduplicación Instagram con Redis activa")
        return _redis_client
    except Exception as exc:
        logger.warning(
            "[meta_social] Redis no disponible para dedup; se usará memoria: %s",
            type(exc).__name__,
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
) -> bool:
    if not message_id:
        return False

    key = f"{DEDUP_PREFIX}{message_id}"
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
