"""
Selección de motor chatbot (informativo | inteligente | clásico legacy).

Fuente principal: chatbot_configuracion.tipo_chatbot.

Decisión central (contrato):

  tipo_chatbot = informativo
  → menú + información + consultas libres
  → no clasificación de aspirante
  → no flujo obligatorio de conversión

  tipo_chatbot = inteligente
  → conversación + clasificación + recopilación + flujo
  → también responde información
  → retoma el punto pendiente

Compatibilidad: usar_asistente_conversacional / usar_rutas_adaptativas
solo como fallback de lectura si tipo_chatbot no es válido.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import database_chatbot_captacion as db_captacion
from chatbot_tipo import (
    TIPO_INFORMATIVO,
    TIPO_INTELIGENTE,
    enriquecer_config_con_tipo,
    resolver_tipo_chatbot,
)

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
    tipo_chatbot: Optional[str],
    usar_asistente_conversacional: Optional[bool],
    usar_rutas_adaptativas: Optional[bool],
    asistente_id: Optional[int],
    asistente_activo: Optional[bool],
    motor_seleccionado: str,
    motivo: str,
) -> None:
    msg = (
        f"[CHATBOT_TIPO] agencia_id={agencia_id} "
        f"chatbot_configuracion_id={chatbot_configuracion_id} "
        f"tipo_chatbot={tipo_chatbot} "
        f"usar_asistente_conversacional={usar_asistente_conversacional} "
        f"usar_rutas_adaptativas={usar_rutas_adaptativas} "
        f"asistente_id={asistente_id} asistente_activo={asistente_activo} "
        f"motor_seleccionado={motor_seleccionado} motivo={motivo}"
    )
    logger.info(msg)
    print(msg)
    print(
        f"[chatbot_router] agencia_id={agencia_id} "
        f"chatbot_configuracion_id={chatbot_configuracion_id} "
        f"usar_asistente_conversacional={usar_asistente_conversacional} "
        f"usar_rutas_adaptativas={usar_rutas_adaptativas} "
        f"asistente_id={asistente_id} asistente_activo={asistente_activo} "
        f"motor_seleccionado={motor_seleccionado} motivo={motivo}"
    )


def resolver_motor_conversacional(
    agencia_id: int,
    chatbot_configuracion_id: Optional[int],
) -> Dict[str, Any]:
    """
    Decide el motor antes de procesar el mensaje.

    Retorna claves:
    - tipo_chatbot: informativo | inteligente
    - motor_seleccionado: informativo | inteligente | clasico
    - usar_conversacional: True si usa el stack conversacional (inteligente)
    - usar_informativo: True si usa el menú informativo
    """
    decision: Dict[str, Any] = {
        "usar_conversacional": False,
        "usar_informativo": False,
        "motor_seleccionado": "clasico",
        "tipo_chatbot": None,
        "motivo": "sin_configuracion",
        "usar_asistente_conversacional": False,
        "usar_rutas_adaptativas": False,
        "asistente_id": None,
        "asistente_activo": None,
        "chatbot_configuracion_id": chatbot_configuracion_id,
        "agencia_id": agencia_id,
        "openai_configurado": _openai_configurado(),
    }

    if not chatbot_configuracion_id:
        decision["motivo"] = "sin_chatbot_configuracion_id"
        _log_router_motor(
            agencia_id=agencia_id,
            chatbot_configuracion_id=None,
            tipo_chatbot=None,
            usar_asistente_conversacional=None,
            usar_rutas_adaptativas=None,
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
        _log_router_motor(
            agencia_id=agencia_id,
            chatbot_configuracion_id=int(chatbot_configuracion_id),
            tipo_chatbot=None,
            usar_asistente_conversacional=None,
            usar_rutas_adaptativas=None,
            asistente_id=None,
            asistente_activo=None,
            motor_seleccionado="clasico",
            motivo=decision["motivo"],
        )
        return decision

    cfg = enriquecer_config_con_tipo(configuracion)
    tipo = resolver_tipo_chatbot(cfg)
    flag_motor = bool(cfg.get("usar_asistente_conversacional"))
    flag_adaptativo = bool(cfg.get("usar_rutas_adaptativas"))
    decision["tipo_chatbot"] = tipo
    decision["usar_asistente_conversacional"] = flag_motor
    decision["usar_rutas_adaptativas"] = flag_adaptativo

    asistente = _obtener_asistente(int(agencia_id), int(chatbot_configuracion_id))
    if asistente:
        decision["asistente_id"] = asistente.get("id")
        decision["asistente_activo"] = bool(asistente.get("activo"))

    # --- Contrato: tipo_chatbot manda ---
    if tipo == TIPO_INFORMATIVO:
        decision["usar_informativo"] = True
        decision["usar_conversacional"] = False
        decision["motor_seleccionado"] = "informativo"
        decision["motivo"] = "tipo_chatbot_informativo"
        _log_router_motor(
            agencia_id=agencia_id,
            chatbot_configuracion_id=int(chatbot_configuracion_id),
            tipo_chatbot=tipo,
            usar_asistente_conversacional=flag_motor,
            usar_rutas_adaptativas=flag_adaptativo,
            asistente_id=decision["asistente_id"],
            asistente_activo=decision["asistente_activo"],
            motor_seleccionado="informativo",
            motivo=decision["motivo"],
        )
        return decision

    # tipo_chatbot = inteligente → siempre motor inteligente (no degradar a menú)
    decision["usar_conversacional"] = True
    decision["usar_informativo"] = False
    decision["motor_seleccionado"] = "inteligente"
    decision["usar_asistente_conversacional"] = True
    decision["usar_rutas_adaptativas"] = True

    avisos = []
    if not asistente:
        avisos.append("asistente_inexistente")
    elif not decision["asistente_activo"]:
        avisos.append("asistente_inactivo")
    if not decision["openai_configurado"]:
        avisos.append("openai_no_configurado")
    decision["motivo"] = (
        "tipo_chatbot_inteligente"
        if not avisos
        else f"tipo_chatbot_inteligente|{','.join(avisos)}"
    )

    _log_router_motor(
        agencia_id=agencia_id,
        chatbot_configuracion_id=int(chatbot_configuracion_id),
        tipo_chatbot=TIPO_INTELIGENTE,
        usar_asistente_conversacional=True,
        usar_rutas_adaptativas=True,
        asistente_id=decision["asistente_id"],
        asistente_activo=decision["asistente_activo"],
        motor_seleccionado="inteligente",
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


def debe_usar_informativo(
    agencia_id: int,
    chatbot_configuracion_id: Optional[int],
) -> bool:
    return bool(
        resolver_motor_conversacional(agencia_id, chatbot_configuracion_id).get(
            "usar_informativo"
        )
    )
