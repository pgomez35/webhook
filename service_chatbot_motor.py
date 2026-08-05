"""
Selección de motor chatbot (clásico vs conversacional).

Archivo plano en la raíz del backend (desplegable sin subcarpetas).

Semántica:
- usar_asistente_conversacional=false → clásico
- true + asistente_configuracion.activo=true → conversacional
- true sin asistente activo → clásico con warning explícito
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import database_chatbot_captacion as db_captacion

logger = logging.getLogger("uvicorn.error")


def _openai_configurado() -> bool:
    clave = os.getenv("OPENAI_API_KEY")
    return bool(clave and str(clave).strip())


def _obtener_asistente(
    agencia_id: int, chatbot_configuracion_id: int
) -> Optional[Dict[str, Any]]:
    try:
        import database_chatbot_conversacional as db_conv
    except ImportError:
        return None
    try:
        return db_conv.obtener_asistente_configuracion(
            agencia_id, chatbot_configuracion_id
        )
    except Exception:
        logger.exception(
            "[chatbot_router] error leyendo asistente_configuracion "
            "agencia_id=%s chatbot_configuracion_id=%s",
            agencia_id,
            chatbot_configuracion_id,
        )
        return None


def _log_router_motor(
    *,
    agencia_id: int,
    chatbot_configuracion_id: Optional[int],
    usar_asistente_conversacional: Optional[bool],
    asistente_id: Optional[int],
    asistente_activo: Optional[bool],
    motor_seleccionado: str,
    motivo: str,
) -> None:
    """Log sanitizado (sin tokens ni secretos)."""
    logger.info(
        "[chatbot_router] agencia_id=%s chatbot_configuracion_id=%s "
        "usar_asistente_conversacional=%s asistente_id=%s asistente_activo=%s "
        "motor_seleccionado=%s motivo=%s",
        agencia_id,
        chatbot_configuracion_id,
        usar_asistente_conversacional,
        asistente_id,
        asistente_activo,
        motor_seleccionado,
        motivo,
    )


def resolver_motor_conversacional(
    agencia_id: int,
    chatbot_configuracion_id: Optional[int],
) -> Dict[str, Any]:
    """
    Decide el motor antes de procesar ``etapa_chatbot``.

    Usa solo módulos planos: ``database_chatbot_captacion`` y
    ``database_chatbot_conversacional``.
    """
    decision: Dict[str, Any] = {
        "usar_conversacional": False,
        "motor_seleccionado": "clasico",
        "motivo": "sin_configuracion",
        "usar_asistente_conversacional": False,
        "asistente_id": None,
        "asistente_activo": None,
        "chatbot_configuracion_id": chatbot_configuracion_id,
        "agencia_id": agencia_id,
    }

    if not chatbot_configuracion_id:
        decision["motivo"] = "sin_chatbot_configuracion_id"
        _log_router_motor(
            agencia_id=agencia_id,
            chatbot_configuracion_id=None,
            usar_asistente_conversacional=None,
            asistente_id=None,
            asistente_activo=None,
            motor_seleccionado="clasico",
            motivo=decision["motivo"],
        )
        return decision

    configuracion = db_captacion.obtener_configuracion_por_id(
        int(agencia_id),
        int(chatbot_configuracion_id),
        solo_activa=False,
    )
    if not configuracion:
        decision["motivo"] = "configuracion_inexistente_o_otra_agencia"
        logger.warning(
            "[chatbot_router] configuración inaccesible agencia_id=%s "
            "chatbot_configuracion_id=%s (inexistente o de otra agencia)",
            agencia_id,
            chatbot_configuracion_id,
        )
        _log_router_motor(
            agencia_id=agencia_id,
            chatbot_configuracion_id=int(chatbot_configuracion_id),
            usar_asistente_conversacional=None,
            asistente_id=None,
            asistente_activo=None,
            motor_seleccionado="clasico",
            motivo=decision["motivo"],
        )
        return decision

    flag_motor = bool(configuracion.get("usar_asistente_conversacional"))
    decision["usar_asistente_conversacional"] = flag_motor

    if not flag_motor:
        decision["motivo"] = "selector_plataforma_desactivado"
        _log_router_motor(
            agencia_id=agencia_id,
            chatbot_configuracion_id=int(chatbot_configuracion_id),
            usar_asistente_conversacional=False,
            asistente_id=None,
            asistente_activo=None,
            motor_seleccionado="clasico",
            motivo=decision["motivo"],
        )
        return decision

    asistente = _obtener_asistente(int(agencia_id), int(chatbot_configuracion_id))
    if not asistente:
        decision["motivo"] = "asistente_inexistente"
        logger.warning(
            "[chatbot_router] usar_asistente_conversacional=true pero no hay "
            "asistente_configuracion agencia_id=%s chatbot_configuracion_id=%s; "
            "fallback a flujo clásico",
            agencia_id,
            chatbot_configuracion_id,
        )
        _log_router_motor(
            agencia_id=agencia_id,
            chatbot_configuracion_id=int(chatbot_configuracion_id),
            usar_asistente_conversacional=True,
            asistente_id=None,
            asistente_activo=None,
            motor_seleccionado="clasico",
            motivo=decision["motivo"],
        )
        return decision

    asistente_id = asistente.get("id")
    asistente_activo = bool(asistente.get("activo"))
    decision["asistente_id"] = asistente_id
    decision["asistente_activo"] = asistente_activo

    if not asistente_activo:
        decision["motivo"] = "asistente_inactivo"
        logger.warning(
            "[chatbot_router] usar_asistente_conversacional=true pero "
            "asistente_configuracion.activo=false asistente_id=%s "
            "agencia_id=%s chatbot_configuracion_id=%s; fallback a flujo clásico",
            asistente_id,
            agencia_id,
            chatbot_configuracion_id,
        )
        _log_router_motor(
            agencia_id=agencia_id,
            chatbot_configuracion_id=int(chatbot_configuracion_id),
            usar_asistente_conversacional=True,
            asistente_id=asistente_id,
            asistente_activo=False,
            motor_seleccionado="clasico",
            motivo=decision["motivo"],
        )
        return decision

    if not _openai_configurado():
        decision["motivo"] = "openai_no_configurado"
        logger.warning(
            "[chatbot_router] motor conversacional solicitado pero OPENAI no "
            "está configurado; fallback a flujo clásico agencia_id=%s "
            "chatbot_configuracion_id=%s",
            agencia_id,
            chatbot_configuracion_id,
        )
        _log_router_motor(
            agencia_id=agencia_id,
            chatbot_configuracion_id=int(chatbot_configuracion_id),
            usar_asistente_conversacional=True,
            asistente_id=asistente_id,
            asistente_activo=True,
            motor_seleccionado="clasico",
            motivo=decision["motivo"],
        )
        return decision

    decision["usar_conversacional"] = True
    decision["motor_seleccionado"] = "conversacional"
    decision["motivo"] = "selector_y_asistente_activos"
    _log_router_motor(
        agencia_id=agencia_id,
        chatbot_configuracion_id=int(chatbot_configuracion_id),
        usar_asistente_conversacional=True,
        asistente_id=asistente_id,
        asistente_activo=True,
        motor_seleccionado="conversacional",
        motivo=decision["motivo"],
    )
    return decision


def debe_usar_conversacional(
    agencia_id: int,
    chatbot_configuracion_id: Optional[int],
) -> bool:
    return bool(
        resolver_motor_conversacional(agencia_id, chatbot_configuracion_id).get(
            "usar_conversacional"
        )
    )
