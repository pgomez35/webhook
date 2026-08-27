"""Clasificación de conversaciones WhatsApp para la bandeja de Mensajes."""
from __future__ import annotations

from typing import Any, Dict, Optional

TIPO_SIN_VINCULAR = "sin_vincular"
TIPOS_CONTACTO = ("aspirante", "creador", "admin", TIPO_SIN_VINCULAR)


def clasificar_tipo_conversacion(
    es_aspirante: bool,
    es_creador: bool,
    es_admin: bool,
) -> str:
    if es_aspirante:
        return "aspirante"
    if es_creador:
        return "creador"
    if es_admin:
        return "admin"
    return TIPO_SIN_VINCULAR


def normalizar_tipo_filtro(tipo: Optional[str]) -> Optional[str]:
    clave = (tipo or "").strip().lower().replace(" ", "_")
    if clave in ("unlinked", "sin_vincular", "sinvincular"):
        return TIPO_SIN_VINCULAR
    if clave in TIPOS_CONTACTO:
        return clave
    return None


def nombres_whatsapp_desde_value(value: Any) -> Dict[str, str]:
    """Lee contacts[].profile.name del payload inbound de Meta."""
    if not isinstance(value, dict):
        return {}
    contacts = value.get("contacts") or []
    out: Dict[str, str] = {}
    if not isinstance(contacts, list):
        return out
    for item in contacts:
        if not isinstance(item, dict):
            continue
        wa_id = str(item.get("wa_id") or "").strip()
        profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
        nombre = str((profile or {}).get("name") or "").strip()
        if wa_id and nombre:
            out[wa_id] = nombre
    return out
