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
from database_whatsapp_plantillas import (
    listar_plantillas_waba,
    obtener_plantilla_waba_por_nombre,
    uso_desde_finalidad,
)
from plantillas_whatsapp_mensajes import ejecutar_envio_plantilla

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


def _serializar_plantilla_chatbot(fila: dict) -> dict:
    nombre = str(fila.get("nombre_meta") or "").strip()
    visible = str(fila.get("nombre_visible") or "").strip() or None
    uso = uso_desde_finalidad(fila.get("finalidad_interna"))
    return {
        "id": fila.get("id"),
        "codigo": nombre,
        "nombre_meta": nombre,
        "nombre_visible": visible,
        "etiqueta": visible or nombre,
        "uso": uso,
        "finalidad_interna": fila.get("finalidad_interna"),
        "idioma": fila.get("idioma") or "es_CO",
        "parametros": list(fila.get("parametros") or []),
        "descripcion": fila.get("descripcion") or "",
        "categoria_meta": fila.get("categoria_meta"),
        "fuente": "waba",
        "alcance": "waba",
        "activo": bool(fila.get("activo", True)),
        "disponible_meta": bool(fila.get("disponible_meta", True)),
    }


def listar_plantillas_agencia_chatbot(agencia_id: int) -> List[dict]:
    """Allowlist local de la agencia JWT. Sin Graph."""
    cuenta = _cuenta_waba_agencia(int(agencia_id))
    phone_id = str(cuenta["phone_number_id"])
    filas = listar_plantillas_waba(
        int(agencia_id),
        phone_id,
        solo_activas=True,
        solo_disponibles=True,
    )
    visibles = [
        _serializar_plantilla_chatbot(fila)
        for fila in filas
        if fila.get("activo", True) and fila.get("disponible_meta", True)
    ]
    logger.info(
        "[CHATBOT-PLANTILLA] listar agencia_id=%s habilitadas=%s",
        agencia_id,
        len(visibles),
    )
    return visibles


def enviar_plantilla_nueva_conversacion(
    *,
    agencia_id: int,
    agencia_nombre: str,
    telefono: str,
    codigo: str,
    nombre: Optional[str] = None,
    usuario_plataforma: Optional[str] = None,
    atencion_manual_inicial: bool = False,
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
    phone_id = str(cuenta["phone_number_id"])
    asociacion = obtener_plantilla_waba_por_nombre(
        int(agencia_id), phone_id, codigo_norm, solo_activa=True
    )
    if not asociacion:
        raise ErrorPlantillaChatbot(404, f"Plantilla no permitida: {codigo_norm}")
    if asociacion.get("disponible_meta") is False:
        raise ErrorPlantillaChatbot(
            409,
            "Esta plantilla ya no está disponible en Meta",
        )
    resultado = ejecutar_envio_plantilla(
        telefono=tel,
        codigo=codigo_norm,
        nombre=nombre or "",
        agencia_nombre=agencia_nombre or cuenta.get("business_name") or "",
        token=str(cuenta["access_token"]),
        phone_number_id=str(cuenta["phone_number_id"]),
        agencia_id=int(agencia_id),
        waba_id=str(cuenta.get("waba_id") or "").strip() or None,
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

    if atencion_manual_inicial:
        try:
            from database_chatbot_conversacional import marcar_atencion_manual_inicial

            marcar_atencion_manual_inicial(int(agencia_id), int(conversacion_id))
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "[CHATBOT-PLANTILLA] no se pudo marcar atención manual "
                "agencia_id=%s conversacion_id=%s: %s",
                agencia_id,
                conversacion_id,
                exc,
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
