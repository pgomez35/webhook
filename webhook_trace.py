"""Trazabilidad de un POST /webhook (request_id en logs)."""
from __future__ import annotations

import contextvars
import hashlib
import uuid
from typing import Any, Optional

_webhook_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "webhook_request_id", default="-"
)


def new_webhook_request_id() -> str:
    rid = uuid.uuid4().hex[:12]
    _webhook_request_id.set(rid)
    return rid


def webhook_request_id() -> str:
    return _webhook_request_id.get() or "-"


def set_webhook_request_id(rid: str) -> None:
    _webhook_request_id.set(str(rid or "-"))


def preview_texto(texto: Optional[str], *, max_len: int = 40) -> str:
    crudo = str(texto or "").strip().replace("\n", " ")
    if not crudo:
        return ""
    if len(crudo) <= max_len:
        return crudo
    return crudo[: max_len - 1] + "…"


def hash_texto(texto: Optional[str]) -> str:
    crudo = str(texto or "").strip().encode("utf-8")
    if not crudo:
        return ""
    return hashlib.sha256(crudo).hexdigest()[:12]


def log_prefix(**extra: Any) -> str:
    parts = [f"request_id={webhook_request_id()}"]
    for k, v in extra.items():
        if v is None or v == "":
            continue
        parts.append(f"{k}={v}")
    return " ".join(parts)
