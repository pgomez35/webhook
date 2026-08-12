"""
Adaptador de envío WhatsApp para el chatbot (contrato único).

No sustituye enviar_mensaje_texto_simple: lo envuelve y normaliza el resultado.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("uvicorn.error")

_conversacion_id_envio: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "chatbot_conversacion_id_envio", default=None
)


def fijar_conversacion_id_envio(conversacion_id: Optional[int]):
    """Propaga conversacion_id a logs/envíos del turno actual."""
    return _conversacion_id_envio.set(
        int(conversacion_id) if conversacion_id is not None else None
    )


def reset_conversacion_id_envio(token) -> None:
    try:
        _conversacion_id_envio.reset(token)
    except Exception:  # noqa: BLE001
        pass


def conversacion_id_envio_actual(
    explicito: Optional[int] = None,
) -> Optional[int]:
    if explicito is not None:
        try:
            return int(explicito)
        except (TypeError, ValueError):
            return None
    valor = _conversacion_id_envio.get()
    try:
        return int(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None


def extraer_mensaje_externo_id(respuesta_api: Any) -> Optional[str]:
    if not isinstance(respuesta_api, dict):
        return None
    mensajes = respuesta_api.get("messages") or []
    if not mensajes or not isinstance(mensajes, list):
        return None
    primero = mensajes[0] if mensajes else None
    if not isinstance(primero, dict):
        return None
    mid = primero.get("id")
    return str(mid) if mid else None


def normalizar_resultado_envio(
    resultado: Any,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Contrato único:

    {
      "enviado": bool,
      "mensaje_externo_id": str|None,
      "status_code": int|None,
      "error": str|None,
      "requiere_reintento": bool,
    }

    No usar bool(dict): un dict con error también sería truthy.
    """
    if dry_run:
        return {
            "enviado": True,
            "mensaje_externo_id": None,
            "status_code": None,
            "error": None,
            "requiere_reintento": False,
            "dry_run": True,
        }

    if resultado is None:
        return {
            "enviado": False,
            "mensaje_externo_id": None,
            "status_code": None,
            "error": "callback_sin_resultado",
            "requiere_reintento": True,
        }

    if isinstance(resultado, bool):
        # Un booleano no prueba aceptación de Meta.
        return {
            "enviado": False,
            "mensaje_externo_id": None,
            "status_code": None,
            "error": None if not resultado else "resultado_bool_sin_confirmacion_meta",
            "requiere_reintento": True,
        }

    if not isinstance(resultado, dict):
        return {
            "enviado": False,
            "mensaje_externo_id": None,
            "status_code": None,
            "error": f"resultado_callback_invalido:{type(resultado).__name__}",
            "requiere_reintento": True,
        }

    # Ya normalizado
    if "enviado" in resultado and (
        "mensaje_externo_id" in resultado or "status_code" in resultado or resultado.get("dry_run")
    ):
        mid = resultado.get("mensaje_externo_id")
        status = resultado.get("status_code")
        try:
            status_i = int(status) if status is not None else None
        except (TypeError, ValueError):
            status_i = None
        ok_http = status_i is not None and 200 <= status_i < 300
        enviado = bool(resultado.get("enviado") is True and ok_http)
        if resultado.get("dry_run"):
            enviado = True
        return {
            "enviado": enviado,
            "mensaje_externo_id": str(mid) if mid else None,
            "status_code": status_i,
            "error": None if enviado else (resultado.get("error") or "sin_confirmacion_meta"),
            "requiere_reintento": not enviado,
            "dry_run": bool(resultado.get("dry_run")),
        }

    # Compat: status/detalle de enviar_mensaje_whatsapp_texto
    if resultado.get("status") == "ok" or (
        resultado.get("message_id_meta") and resultado.get("codigo_api")
    ):
        mid = resultado.get("message_id_meta") or resultado.get("mensaje_externo_id")
        status = resultado.get("codigo_api") or resultado.get("status_code") or 200
        try:
            status_i = int(status)
        except (TypeError, ValueError):
            status_i = None
        ok = status_i is not None and 200 <= status_i < 300
        return {
            "enviado": ok,
            "mensaje_externo_id": str(mid) if mid else None,
            "status_code": status_i,
            "error": None if ok else (resultado.get("detalle") or resultado.get("error")),
            "requiere_reintento": not ok,
        }

    mid = resultado.get("mensaje_externo_id") or extraer_mensaje_externo_id(resultado)
    status = resultado.get("status_code")
    try:
        status_i = int(status) if status is not None else None
    except (TypeError, ValueError):
        status_i = None
    ok_http = status_i is not None and 200 <= status_i < 300
    enviado = bool(resultado.get("enviado") is True and ok_http)
    return {
        "enviado": enviado,
        "mensaje_externo_id": str(mid) if mid else None,
        "status_code": status_i,
        "error": None if enviado else (resultado.get("error") or "sin_confirmacion_meta"),
        "requiere_reintento": not enviado,
    }


async def enviar_whatsapp_texto_meta(
    *,
    token: str,
    phone_number_id: str,
    destino: str,
    texto: str,
    conversacion_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Llama al servicio real ``enviar_mensaje_texto_simple`` y normaliza el resultado.
    """
    conversacion_id = conversacion_id_envio_actual(conversacion_id)
    cuerpo = str(texto or "").strip()
    if not cuerpo:
        return {
            "enviado": False,
            "mensaje_externo_id": None,
            "status_code": None,
            "error": "texto_vacio",
            "requiere_reintento": False,
        }
    if not token or not phone_number_id or not destino:
        logger.error(
            "[CHATBOT_ENVIO] canal=whatsapp conversacion_id=%s "
            "respuesta_enviada=false error=credenciales_incompletas",
            conversacion_id,
        )
        return {
            "enviado": False,
            "mensaje_externo_id": None,
            "status_code": None,
            "error": "credenciales_whatsapp_incompletas",
            "requiere_reintento": True,
        }

    from enviar_msg_wp import enviar_mensaje_texto_simple

    try:
        codigo, respuesta_api = await asyncio.to_thread(
            enviar_mensaje_texto_simple,
            token=token,
            numero_id=phone_number_id,
            telefono_destino=str(destino),
            texto=cuerpo,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[CHATBOT_ENVIO] canal=whatsapp conversacion_id=%s "
            "respuesta_enviada=false codigo_error=excepcion requiere_reintento=true",
            conversacion_id,
        )
        return {
            "enviado": False,
            "mensaje_externo_id": None,
            "status_code": None,
            "error": str(exc)[:400],
            "requiere_reintento": True,
        }

    try:
        status_i = int(codigo or 0)
    except (TypeError, ValueError):
        status_i = 0
    mid = extraer_mensaje_externo_id(respuesta_api)
    # HTTP 2xx ya implica entrega a Meta. Exigir wamid evitaba marcar éxito y
    # provocaba reenvíos duplicados (garantizar + reintento del dispatcher).
    ok_http = 200 <= status_i < 300
    ok = ok_http
    if ok_http and not mid:
        logger.warning(
            "[CHATBOT_ENVIO] canal=whatsapp conversacion_id=%s status_code=%s "
            "sin wamid; se marca enviado para evitar duplicados",
            conversacion_id,
            status_i,
        )
    error = None
    if not ok:
        if isinstance(respuesta_api, dict):
            err = respuesta_api.get("error")
            if isinstance(err, dict):
                error = str(err.get("message") or err)[:400]
            else:
                error = str(err or respuesta_api)[:400]
        else:
            error = str(respuesta_api)[:400]

    logger.info(
        "[CHATBOT_ENVIO] canal=whatsapp conversacion_id=%s status_code=%s "
        "mensaje_externo_id=%s respuesta_enviada=%s%s",
        conversacion_id,
        status_i,
        mid or "",
        str(ok).lower(),
        "" if ok else " requiere_reintento=true",
    )
    print(
        f"[CHATBOT_ENVIO] canal=whatsapp conversacion_id={conversacion_id} "
        f"status_code={status_i} mensaje_externo_id={mid or ''} "
        f"respuesta_enviada={str(ok).lower()}"
        + ("" if ok else " requiere_reintento=true")
    )

    return {
        "enviado": ok,
        "mensaje_externo_id": mid,
        "status_code": status_i,
        "error": error,
        "requiere_reintento": not ok,
        "respuesta_api": respuesta_api if not ok else None,
    }
