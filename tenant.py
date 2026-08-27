# tenant.py
from __future__ import annotations

import re
from contextvars import ContextVar
from typing import Optional

# current_tenant = schema PostgreSQL (agency15_5). Nunca el subdominio web.
current_tenant: ContextVar[Optional[str]] = ContextVar("current_tenant", default="public")
# Subdominio web original (agency15-5), para URLs y lookup WABA.
current_subdominio: ContextVar[Optional[str]] = ContextVar("current_subdominio", default=None)
current_business_name: ContextVar[str] = ContextVar("current_business_name")
current_token: ContextVar[str] = ContextVar("current_token", default=None)
current_phone_id: ContextVar[str] = ContextVar("current_phone_id", default=None)


def build_schema_name(tenant_name: str) -> str:
    """
    Único punto: subdominio web → schema PostgreSQL.

    Ej: "agency15-5" → "agency15_5"; "test" → "test".
    """
    normalized = (tenant_name or "").replace("-", "_").lower().strip()

    if normalized.startswith("agencia_"):
        normalized = normalized[len("agencia_"):]

    if not normalized:
        raise ValueError(
            "Nombre de tenant inválido. Debe contener caracteres alfanuméricos."
        )

    if not re.fullmatch(r"[a-z0-9_]+", normalized):
        raise ValueError(
            "Nombre de tenant inválido. Usa solo letras, números y guiones bajos."
        )

    return normalized
