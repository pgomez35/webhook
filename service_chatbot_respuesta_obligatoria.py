"""
Garantía central: todo mensaje de usuario produce respuesta saliente visible.

Excluye solo eventos técnicos/duplicados (el caller decide no invocarla).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from chatbot_envio_whatsapp import normalizar_resultado_envio

logger = logging.getLogger("uvicorn.error")

EnviarCallback = Callable[[str], Any]


async def garantizar_respuesta_saliente(
    *,
    agencia_id: int,
    conversacion_id: Optional[int],
    canal: str,
    texto: str,
    dry_run: bool = False,
    enviar_callback: Optional[EnviarCallback] = None,
    token: Optional[str] = None,
    phone_number_id: Optional[str] = None,
    destino: Optional[str] = None,
    motivo_fallback: str = "fallback",
    mensaje_externo_id: Optional[str] = None,
    ya_enviado: bool = False,
) -> Dict[str, Any]:
    """
    Envía y/o persiste una respuesta. Si falla el envío, aún registra el intento.

    respuesta_enviada / enviado = true solo con confirmación real de Meta
    (o dry_run).
    """
    cuerpo = str(texto or "").strip()
    if not cuerpo:
        cuerpo = (
            "Recibí tu mensaje. En este momento no tengo una respuesta completa, "
            "pero puedo seguir ayudándote con otra consulta."
        )

    if ya_enviado:
        return {
            "enviado": True,
            "texto": cuerpo,
            "duplicado_evitado": True,
            "mensaje_externo_id": None,
            "status_code": None,
            "requiere_reintento": False,
        }

    if dry_run:
        return {
            "enviado": True,
            "texto": cuerpo,
            "dry_run": True,
            "mensaje_externo_id": None,
            "status_code": None,
            "requiere_reintento": False,
        }

    enviado = False
    error = None
    mid = None
    status_code = None
    meta_error_code = None
    requiere_reintento = True

    try:
        if enviar_callback is None and canal == "whatsapp" and token and phone_number_id and destino:
            from chatbot_envio_whatsapp import enviar_whatsapp_texto_meta

            envio = await enviar_whatsapp_texto_meta(
                token=token,
                phone_number_id=phone_number_id,
                destino=destino,
                texto=cuerpo,
                conversacion_id=conversacion_id,
            )
            norm = normalizar_resultado_envio(envio)
        elif enviar_callback is not None:
            resultado = enviar_callback(cuerpo)
            if hasattr(resultado, "__await__"):
                resultado = await resultado  # type: ignore[misc]
            norm = normalizar_resultado_envio(resultado)
        else:
            logger.error(
                "[CHATBOT_ENVIO] canal=%s conversacion_id=%s "
                "respuesta_enviada=false error=sin_callback_ni_credenciales "
                "requiere_reintento=true",
                canal,
                conversacion_id,
            )
            norm = {
                "enviado": False,
                "mensaje_externo_id": None,
                "status_code": None,
                "error": "sin_callback_ni_credenciales",
                "requiere_reintento": True,
            }

        enviado = bool(norm.get("enviado") is True)
        mid = norm.get("mensaje_externo_id")
        status_code = norm.get("status_code")
        error = norm.get("error")
        meta_error_code = norm.get("meta_error_code")
        requiere_reintento = bool(norm.get("requiere_reintento", not enviado))
        if meta_error_code == 131056 or (error and "131056" in str(error)):
            requiere_reintento = False
    except Exception as exc:  # noqa: BLE001
        error = str(exc)[:400]
        enviado = False
        requiere_reintento = True
        meta_error_code = None
        logger.warning(
            "[CHATBOT_FALLBACK] conversacion_id=%s motivo=%s error_envio=%s",
            conversacion_id,
            motivo_fallback,
            error,
        )

    if conversacion_id:
        try:
            import database_chatbot_conversacional as db_conv

            db_conv.insertar_mensaje(
                agencia_id,
                conversacion_id,
                canal=canal,
                direccion="saliente",
                remitente_tipo="chatbot",
                tipo_mensaje="texto",
                texto=cuerpo,
                estado_envio="enviado" if enviado else "error",
                error_detalle=error,
                mensaje_externo_id=mid,
                metadata={
                    "fallback": True,
                    "motivo_fallback": motivo_fallback,
                    "mensaje_externo_origen": mensaje_externo_id,
                    "status_code": status_code,
                    "respuesta_enviada": enviado,
                },
            )
            db_conv.registrar_evento(
                agencia_id,
                conversacion_id,
                tipo_evento="error" if not enviado else "cambio_estado",
                nombre_evento="fallback_respuesta"
                if not enviado
                else "respuesta_garantizada",
                origen="backend",
                exitoso=bool(enviado),
                detalle={
                    "motivo": motivo_fallback,
                    "respuesta_enviada": bool(enviado),
                    "requiere_reintento": requiere_reintento,
                    "requiere_asesor": False,
                    "modo_humano": motivo_fallback == "confirmacion_modo_humano",
                    "mensaje_externo_id": mid,
                    "status_code": status_code,
                },
                error_detalle=error,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[CHATBOT_FALLBACK] no se pudo persistir saliente conversacion_id=%s: %s",
                conversacion_id,
                exc,
            )

    logger.info(
        "[CHATBOT_FALLBACK] conversacion_id=%s motivo=%s "
        "respuesta_enviada=%s requiere_reintento=%s",
        conversacion_id,
        motivo_fallback,
        str(bool(enviado)).lower(),
        str(requiere_reintento).lower(),
    )
    return {
        "enviado": enviado,
        "texto": cuerpo,
        "error": error,
        "mensaje_externo_id": mid,
        "status_code": status_code,
        "meta_error_code": meta_error_code,
        "requiere_reintento": requiere_reintento,
        "respuesta_enviada": enviado,
    }
