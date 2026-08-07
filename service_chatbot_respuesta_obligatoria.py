"""
Garantía central: todo mensaje de usuario produce respuesta saliente visible.

Excluye solo eventos técnicos/duplicados (el caller decide no invocarla).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

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
    No retorna silencio: siempre intenta dejar rastro saliente.
    """
    cuerpo = str(texto or "").strip()
    if not cuerpo:
        cuerpo = (
            "Recibí tu mensaje. En este momento no tengo una respuesta completa, "
            "pero puedo seguir ayudándote con otra consulta."
        )

    if ya_enviado:
        return {"enviado": True, "texto": cuerpo, "duplicado_evitado": True}

    enviado = False
    error = None

    if dry_run:
        return {"enviado": True, "texto": cuerpo, "dry_run": True}

    # Envío por callback (tests / adaptadores) o canal Meta vía service conversacional
    try:
        if enviar_callback:
            resultado = enviar_callback(cuerpo)
            if hasattr(resultado, "__await__"):
                resultado = await resultado  # type: ignore[misc]
            enviado = True if resultado is None else bool(resultado)
        else:
            from service_chatbot_conversacional import _enviar_respuesta

            envio = await _enviar_respuesta(
                canal=canal,
                texto=cuerpo,
                enlaces=[],
                token=token,
                phone_number_id=phone_number_id,
                destino=destino,
                enviar_callback=None,
                dry_run=False,
            )
            enviado = bool((envio or {}).get("enviado"))
            error = (envio or {}).get("error")
    except Exception as exc:  # noqa: BLE001
        error = str(exc)[:400]
        logger.warning(
            "[CHATBOT_FALLBACK] conversacion_id=%s motivo=%s error_envio=%s",
            conversacion_id,
            motivo_fallback,
            error,
        )

    if conversacion_id:
        try:
            import database_chatbot_conversacional as db_conv

            # Idempotencia: si ya hay saliente ligado al mismo externo reciente, no duplicar
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
                mensaje_externo_id=None,
                metadata={
                    "fallback": True,
                    "motivo_fallback": motivo_fallback,
                    "mensaje_externo_origen": mensaje_externo_id,
                },
            )
            db_conv.registrar_evento(
                agencia_id,
                conversacion_id,
                tipo_evento="envio_enlace" if motivo_fallback == "envio_enlace" else "error"
                if not enviado
                else "cambio_estado",
                nombre_evento="fallback_respuesta"
                if motivo_fallback.startswith("fallback") or not enviado
                else "respuesta_garantizada",
                origen="backend",
                exitoso=bool(enviado),
                detalle={
                    "motivo": motivo_fallback,
                    "respuesta_enviada": bool(enviado),
                    "requiere_asesor": False,
                    "modo_humano": False,
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
        "requiere_asesor=false modo_humano=false respuesta_enviada=%s",
        conversacion_id,
        motivo_fallback,
        str(bool(enviado)).lower(),
    )
    return {"enviado": enviado, "texto": cuerpo, "error": error}
