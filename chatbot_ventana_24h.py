"""Ventana WhatsApp 24h para conversaciones del chatbot canónico.

Fuente de verdad: último mensaje INBOUND en chatbot.mensajes_conversacion.
Un outbound (humano, IA o plantilla) no abre ni extiende la ventana.

Reutiliza calcular_estado_ventana_24h de la bandeja Talentum (timezone-aware).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import HTTPException

from utils_aspirantes import calcular_estado_ventana_24h, serializar_estado_ventana_24h

logger = logging.getLogger("uvicorn.error")

REMITENTES_INBOUND = ("aspirante", "creador")
MSG_VENTANA_CERRADA = (
    "La ventana de atención de 24 horas está cerrada. "
    "Envía una plantilla de WhatsApp."
)
MSG_VENTANA_NUNCA_ABIERTA = (
    "Esta conversación aún no tiene mensajes del contacto. "
    "Solo se puede enviar una plantilla de WhatsApp."
)


def consultar_ultimo_inbound_at(
    agencia_id: int,
    conversacion_id: int,
    *,
    cur=None,
    consultar_fn=None,
) -> Optional[datetime]:
    """Último created_at inbound del contacto. Ignora salientes y sistema."""
    if consultar_fn is not None:
        return consultar_fn(agencia_id, conversacion_id)
    from database_chatbot_conversacional import consultar_ultimo_inbound_conversacion

    return consultar_ultimo_inbound_conversacion(
        int(agencia_id), int(conversacion_id), cur=cur
    )


def estado_ventana_conversacion(
    agencia_id: int,
    conversacion_id: int,
    *,
    ahora: Optional[datetime] = None,
    consultar_fn=None,
    cur=None,
) -> Dict[str, Any]:
    ultima = consultar_ultimo_inbound_at(
        int(agencia_id),
        int(conversacion_id),
        cur=cur,
        consultar_fn=consultar_fn,
    )
    raw = serializar_estado_ventana_24h(
        calcular_estado_ventana_24h(ultima, ahora=ahora)
    )
    return {
        "ultimo_mensaje_usuario_at": raw.get("ultima_entrada_usuario_at"),
        "ventana_24h_abierta": bool(raw.get("ventana_abierta")),
        "ventana_24h_hasta": raw.get("ventana_24h_hasta"),
        "ventana_24h_estado": raw.get("estado"),
        "texto_libre_permitido": bool(raw.get("texto_libre_permitido")),
    }


def adjuntar_ventana_24h(conversacion: Optional[Dict[str, Any]], **kwargs) -> Optional[Dict[str, Any]]:
    if not conversacion:
        return conversacion
    agencia_id = conversacion.get("agencia_id")
    conversacion_id = conversacion.get("id")
    if agencia_id is None or conversacion_id is None:
        return conversacion
    out = dict(conversacion)
    out.update(
        estado_ventana_conversacion(int(agencia_id), int(conversacion_id), **kwargs)
    )
    return out


def mensaje_bloqueo_ventana(estado: Dict[str, Any]) -> str:
    if estado.get("ventana_24h_estado") == "nunca_abierta":
        return MSG_VENTANA_NUNCA_ABIERTA
    return MSG_VENTANA_CERRADA


def exigir_texto_libre_whatsapp(
    agencia_id: int,
    conversacion_id: int,
    *,
    canal: Optional[str] = "whatsapp",
    ahora: Optional[datetime] = None,
    consultar_fn=None,
) -> Dict[str, Any]:
    """409 si el canal es WhatsApp y la ventana no está abierta. Plantillas no usan esto."""
    if str(canal or "whatsapp").strip().lower() != "whatsapp":
        return {"texto_libre_permitido": True, "ventana_24h_abierta": True}
    estado = estado_ventana_conversacion(
        int(agencia_id),
        int(conversacion_id),
        ahora=ahora,
        consultar_fn=consultar_fn,
    )
    if estado.get("texto_libre_permitido"):
        return estado
    logger.info(
        "[CHATBOT-24H] texto libre bloqueado conversacion_id=%s estado=%s",
        conversacion_id,
        estado.get("ventana_24h_estado"),
    )
    raise HTTPException(status_code=409, detail=mensaje_bloqueo_ventana(estado))


def texto_libre_permitido_por_conversacion_id(
    conversacion_id: int,
    *,
    ahora: Optional[datetime] = None,
    consultar_fn=None,
) -> bool:
    """Para el adaptador de envío IA. False = no llamar a Meta."""
    try:
        from database_chatbot_conversacional import obtener_conversacion_por_id

        row = obtener_conversacion_por_id(int(conversacion_id))
    except Exception:  # noqa: BLE001
        row = None
    if not row:
        return True
    if str(row.get("canal") or "").strip().lower() != "whatsapp":
        return True
    estado = estado_ventana_conversacion(
        int(row["agencia_id"]),
        int(conversacion_id),
        ahora=ahora,
        consultar_fn=consultar_fn,
    )
    return bool(estado.get("texto_libre_permitido"))
