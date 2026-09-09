"""Envío de plantillas WhatsApp desde el portal independiente del chatbot.

Reutiliza la capa Meta / catálogo WABA de Mensajes WhatsApp.
No usa JWT Talentum ni el tenant del header X-Tenant-Name.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from chatbot_captacion_logic import (
    normalizar_telefono_chatbot,
    normalizar_usuario_plataforma,
)
from database_chatbot_captacion import obtener_cuenta_whatsapp_principal
from plantillas_whatsapp_mensajes import (
    ejecutar_envio_plantilla,
    listar_plantillas_para_envio,
)

logger = logging.getLogger("uvicorn.error")

MIN_DIGITOS_TELEFONO = 10


class ErrorPlantillaChatbot(Exception):
    def __init__(self, http_status: int, detail: Any):
        super().__init__(str(detail))
        self.http_status = int(http_status)
        self.detail = detail


def _cuenta_waba_agencia(agencia_id: int) -> Dict[str, Any]:
    cuenta = obtener_cuenta_whatsapp_principal(int(agencia_id))
    if not cuenta:
        raise ErrorPlantillaChatbot(
            400,
            "WhatsApp no está configurado para esta agencia",
        )
    token = str(cuenta.get("access_token") or "").strip()
    phone_id = str(cuenta.get("phone_number_id") or "").strip()
    if not token or not phone_id:
        raise ErrorPlantillaChatbot(
            500,
            "Credenciales de WhatsApp no configuradas para esta agencia",
        )
    return cuenta


def listar_plantillas_agencia_chatbot(agencia_id: int) -> List[dict]:
    """Plantillas de la WABA de la agencia autenticada. Sin access token."""
    cuenta = _cuenta_waba_agencia(int(agencia_id))
    return listar_plantillas_para_envio(
        phone_number_id=str(cuenta["phone_number_id"]),
        agencia_id=int(agencia_id),
    )


def enviar_plantilla_nueva_conversacion(
    *,
    agencia_id: int,
    agencia_nombre: str,
    telefono: str,
    codigo: str,
    nombre: Optional[str] = None,
    usuario_plataforma: Optional[str] = None,
) -> Dict[str, Any]:
    """Envía plantilla, reutiliza o crea conversación canónica. No crea aspirante.

    Unicidad: ``buscar_o_crear_conversacion`` reutiliza la conversación no cerrada
    de (agencia, whatsapp, phone_number_id, teléfono). Si está cerrada, crea otra.
    """
    tel = normalizar_telefono_chatbot(telefono)
    codigo_norm = (codigo or "").strip()
    if not tel:
        raise ErrorPlantillaChatbot(400, "Teléfono inválido")
    if len(tel) < MIN_DIGITOS_TELEFONO:
        raise ErrorPlantillaChatbot(400, "Teléfono inválido")
    if not codigo_norm:
        raise ErrorPlantillaChatbot(400, "Falta el código de plantilla")

    usuario_norm = normalizar_usuario_plataforma(usuario_plataforma)
    cuenta = _cuenta_waba_agencia(int(agencia_id))
    resultado = ejecutar_envio_plantilla(
        telefono=tel,
        codigo=codigo_norm,
        nombre=nombre or "",
        agencia_nombre=agencia_nombre or cuenta.get("business_name") or "",
        token=str(cuenta["access_token"]),
        phone_number_id=str(cuenta["phone_number_id"]),
        agencia_id=int(agencia_id),
        usuario_plataforma=usuario_norm,
        persistir_sas=False,
    )
    if not resultado.get("ok"):
        raise ErrorPlantillaChatbot(
            int(resultado.get("http_status") or 500),
            resultado.get("detail") or "No se pudo enviar la plantilla",
        )

    conversacion_id = resultado.get("conversacion_id")
    if not conversacion_id:
        logger.error(
            "[CHATBOT-PLANTILLA] Meta OK pero sin conversacion_id agencia_id=%s",
            agencia_id,
        )
        raise ErrorPlantillaChatbot(
            500,
            "La plantilla se envió pero no se pudo registrar la conversación",
        )

    return {
        "success": True,
        "status": "ok",
        "conversacion_id": int(conversacion_id),
        "conversacion_creada": bool(resultado.get("conversacion_creada")),
        "telefono": resultado.get("telefono"),
        "codigo": resultado.get("codigo"),
        "nombre_meta": resultado.get("nombre_meta"),
        "message_id_meta": resultado.get("message_id_meta"),
    }
