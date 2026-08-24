"""
Dispatcher central: decide el motor según chatbot_configuracion.tipo_chatbot.

Contrato de decisión:

  tipo_chatbot = tradicional
  → no usa este dispatcher; captación clásica continúa

  tipo_chatbot = informativo
  → procesar_mensaje_informativo

  tipo_chatbot = inteligente
  → conversion (default): GPT conversa + action gate
     rollback técnico: CHATBOT_INTELIGENTE_MOTOR=v2|legacy

Entry point único conceptual para WhatsApp, simulador y futuros canales.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from chatbot_tipo import (
    TIPO_INFORMATIVO,
    TIPO_INTELIGENTE,
    TIPO_TRADICIONAL,
    resolver_tipo_chatbot,
)
from service_chatbot_motor import resolver_motor_conversacional

logger = logging.getLogger("uvicorn.error")

EnviarCallback = Callable[[str], Any]


async def procesar_mensaje_segun_tipo_chatbot(
    *,
    agencia_id: int,
    chatbot_configuracion_id: int,
    texto: str,
    canal: str = "whatsapp",
    conversacion_id: Optional[int] = None,
    aspirante_id: Optional[int] = None,
    usuario_externo_id: Optional[str] = None,
    telefono: Optional[str] = None,
    nombre_contacto: Optional[str] = None,
    mensaje_externo_id: Optional[str] = None,
    tipo_mensaje: str = "texto",
    cuenta_externa_id: Optional[str] = None,
    campania_id: Optional[int] = None,
    token: Optional[str] = None,
    phone_number_id: Optional[str] = None,
    wa_id: Optional[str] = None,
    enviar_callback: Optional[EnviarCallback] = None,
    dry_run: bool = False,
    decision: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Enruta exclusivamente por tipo_chatbot.

    Los flags legacy (usar_rutas_adaptativas, modo_predeterminado) no cambian
    el motor cuando tipo_chatbot es válido.

    Si ``decision`` ya viene resuelta (p. ej. desde captación), no se vuelve
    a llamar a ``resolver_motor_conversacional``.
    """
    if decision is None:
        decision = resolver_motor_conversacional(agencia_id, chatbot_configuracion_id)
        log_tag = "CHATBOT_TIPO"
    else:
        log_tag = "CHATBOT_DISPATCH"
    tipo = resolver_tipo_chatbot(
        {"tipo_chatbot": decision.get("tipo_chatbot")}
    ) or decision.get("tipo_chatbot")

    logger.info(
        "[%s] agencia_id=%s chatbot_configuracion_id=%s "
        "tipo_chatbot=%s canal=%s conversacion_id=%s incoming_wamid=%s",
        log_tag,
        agencia_id,
        chatbot_configuracion_id,
        tipo,
        canal,
        conversacion_id,
        mensaje_externo_id,
    )
    print(
        f"[{log_tag}] agencia_id={agencia_id} "
        f"chatbot_configuracion_id={chatbot_configuracion_id} "
        f"tipo_chatbot={tipo} canal={canal} conversacion_id={conversacion_id} "
        f"incoming_wamid={mensaje_externo_id or ''}"
    )

    if tipo == TIPO_TRADICIONAL:
        return {
            "usado": False,
            "motivo": "tipo_tradicional_clasico",
            "motor": "clasico",
            "tipo_chatbot": TIPO_TRADICIONAL,
            "conversacion_id": conversacion_id,
        }

    # --- informativo: menú + info + consultas libres ---
    if tipo == TIPO_INFORMATIVO:
        from service_chatbot_informativo import procesar_mensaje_informativo

        conv_id = conversacion_id
        if not conv_id and usuario_externo_id:
            conv_id = await _asegurar_conversacion(
                agencia_id=agencia_id,
                chatbot_configuracion_id=chatbot_configuracion_id,
                canal=canal,
                usuario_externo_id=usuario_externo_id,
                telefono=telefono or wa_id,
                aspirante_id=aspirante_id,
                dry_run=dry_run,
            )

        resultado = await procesar_mensaje_informativo(
            agencia_id=agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            conversacion_id=conv_id,
            texto=texto or "",
            canal=canal,
            dry_run=dry_run,
            enviar_callback=enviar_callback,
            token=token,
            phone_number_id=phone_number_id,
            destino=wa_id or usuario_externo_id,
            aspirante_id=aspirante_id,
            mensaje_externo_id=mensaje_externo_id,
        )
        resultado = dict(resultado or {})
        resultado.setdefault("tipo_chatbot", TIPO_INFORMATIVO)
        resultado.setdefault("usado", True)
        resultado["motor"] = "informativo"
        return await _garantizar_si_falta(
            resultado,
            agencia_id=agencia_id,
            conversacion_id=conv_id or conversacion_id,
            canal=canal,
            enviar_callback=enviar_callback,
            token=token,
            phone_number_id=phone_number_id,
            destino=wa_id or usuario_externo_id,
            dry_run=dry_run,
            mensaje_externo_id=mensaje_externo_id,
        )

    # --- inteligente ---
    from chatbot_conversion_flags import motor_inteligente

    motor = motor_inteligente()
    kwargs_inteligente = dict(
        agencia_id=agencia_id,
        texto=texto or "",
        usuario_externo_id=str(usuario_externo_id or wa_id or ""),
        chatbot_configuracion_id=int(chatbot_configuracion_id),
        canal=canal,
        cuenta_externa_id=cuenta_externa_id or phone_number_id,
        telefono=telefono or wa_id,
        nombre_contacto=nombre_contacto,
        mensaje_externo_id=mensaje_externo_id,
        aspirante_id=aspirante_id,
        campania_id=campania_id,
        token=token,
        phone_number_id=phone_number_id,
        wa_id=wa_id,
        enviar_callback=enviar_callback,
        dry_run=dry_run,
    )

    if motor == "conversion":
        from service_chatbot_conversion import procesar_mensaje_conversion

        resultado = await procesar_mensaje_conversion(**kwargs_inteligente)
        resultado = dict(resultado or {})
        resultado.setdefault("tipo_chatbot", TIPO_INTELIGENTE)
        resultado.setdefault("motor", "conversion")
    elif motor == "v2":
        from service_chatbot_inteligente_v2 import procesar_mensaje_inteligente_v2

        resultado = await procesar_mensaje_inteligente_v2(**kwargs_inteligente)
        resultado = dict(resultado or {})
        resultado.setdefault("tipo_chatbot", TIPO_INTELIGENTE)
        resultado.setdefault("motor", "inteligente_v2")
    else:
        from service_chatbot_conversacional import procesar_mensaje_conversacional

        resultado = await procesar_mensaje_conversacional(
            **kwargs_inteligente,
            tipo_mensaje=tipo_mensaje,
        )
        resultado = dict(resultado or {})
        resultado.setdefault("tipo_chatbot", TIPO_INTELIGENTE)
        resultado["motor"] = "inteligente_legacy"
    # Normalizar flag de envío: solo True con confirmación Meta (o dry_run).
    if dry_run and resultado.get("usado"):
        resultado["respuesta_enviada"] = True
        resultado["requiere_reintento"] = False
    elif "respuesta_enviada" not in resultado:
        resultado["respuesta_enviada"] = bool(resultado.get("enviado") is True)
        resultado["requiere_reintento"] = not resultado["respuesta_enviada"]

    if not resultado.get("usado") and resultado.get("motivo") in {
        "atencion_humana",
        "ia_deshabilitada",
    }:
        from service_chatbot_respuesta_obligatoria import garantizar_respuesta_saliente

        # Solo confirmación de recepción humana; no simula que un asesor tomó
        # la conversación ni activa modo_humano.
        texto_conf = (
            "Un asesor continuará la conversación contigo. Tu mensaje fue recibido."
            if resultado.get("motivo") == "atencion_humana"
            else "Recibí tu mensaje. En breve te responderemos por aquí."
        )
        motivo_fb = (
            "confirmacion_modo_humano"
            if resultado.get("motivo") == "atencion_humana"
            else "confirmacion_recepcion"
        )
        envio = await garantizar_respuesta_saliente(
            agencia_id=agencia_id,
            conversacion_id=resultado.get("conversacion_id") or conversacion_id,
            canal=canal,
            texto=texto_conf,
            dry_run=dry_run,
            enviar_callback=enviar_callback,
            token=token,
            phone_number_id=phone_number_id,
            destino=wa_id or usuario_externo_id,
            motivo_fallback=motivo_fb,
            mensaje_externo_id=mensaje_externo_id,
        )
        enviado = bool(envio.get("enviado") is True) or dry_run
        return {
            "usado": True,
            "atendido": True,
            "respuesta_generada": True,
            "motivo": resultado.get("motivo"),
            "respuesta": texto_conf,
            "respuesta_enviada": enviado,
            "requiere_reintento": (not enviado) and (not dry_run),
            "modo_humano": resultado.get("motivo") == "atencion_humana",
            "tipo_chatbot": TIPO_INTELIGENTE,
            "motor": "inteligente",
            "conversacion_id": resultado.get("conversacion_id") or conversacion_id,
            "mensaje_externo_id": envio.get("mensaje_externo_id"),
            "error": envio.get("error"),
        }

    if resultado.get("motivo") in {
        "mensaje_duplicado",
        "openai_presupuesto",
        "openai_concurrencia",
    }:
        return resultado

    return await _garantizar_si_falta(
        resultado,
        agencia_id=agencia_id,
        conversacion_id=resultado.get("conversacion_id") or conversacion_id,
        canal=canal,
        enviar_callback=enviar_callback,
        token=token,
        phone_number_id=phone_number_id,
        destino=wa_id or usuario_externo_id,
        dry_run=dry_run,
        mensaje_externo_id=mensaje_externo_id,
    )


async def _asegurar_conversacion(
    *,
    agencia_id: int,
    chatbot_configuracion_id: int,
    canal: str,
    usuario_externo_id: str,
    telefono: Optional[str],
    aspirante_id: Optional[int],
    dry_run: bool,
) -> Optional[int]:
    if dry_run:
        return None
    try:
        import database_chatbot_conversacional as db_conv

        conv = db_conv.buscar_o_crear_conversacion(
            agencia_id,
            canal=canal,
            usuario_externo_id=str(usuario_externo_id),
            chatbot_configuracion_id=int(chatbot_configuracion_id),
            telefono=telefono,
            aspirante_id=aspirante_id,
        )
        if isinstance(conv, tuple):
            conv = conv[0]
        return (conv or {}).get("id") if isinstance(conv, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CHATBOT_TIPO] no se pudo asegurar conversación: %s", exc)
        return None


async def _garantizar_si_falta(
    resultado: Dict[str, Any],
    *,
    agencia_id: int,
    conversacion_id: Optional[int],
    canal: str,
    enviar_callback: Optional[EnviarCallback],
    token: Optional[str],
    phone_number_id: Optional[str],
    destino: Optional[str],
    dry_run: bool,
    mensaje_externo_id: Optional[str],
) -> Dict[str, Any]:
    """Si el motor no dejó respuesta visible, fuerza fallback."""
    if resultado.get("motivo") == "mensaje_duplicado":
        return resultado

    tiene_respuesta_enviada = bool(resultado.get("respuesta_enviada") is True) or (
        dry_run and bool(str(resultado.get("respuesta") or "").strip())
    )
    if tiene_respuesta_enviada:
        resultado.setdefault("atendido", True)
        resultado.setdefault("respuesta_generada", True)
        resultado.setdefault("requiere_reintento", False)
        return resultado

    # Rate limit Meta: no reenviar en la misma petición.
    err = str(resultado.get("error") or "")
    meta_code = resultado.get("meta_error_code")
    if meta_code == 131056 or "131056" in err:
        logger.warning(
            "[CHATBOT_FALLBACK] meta_error_code=131056 conversacion_id=%s "
            "accion=no_reintentar",
            conversacion_id,
        )
        resultado = dict(resultado)
        resultado["requiere_reintento"] = False
        resultado.setdefault("atendido", True)
        return resultado

    # Hay texto generado pero sin confirmación Meta → reintentar envío una vez.
    texto_existente = str(resultado.get("respuesta") or "").strip()
    if texto_existente:
        from service_chatbot_respuesta_obligatoria import garantizar_respuesta_saliente

        envio = await garantizar_respuesta_saliente(
            agencia_id=agencia_id,
            conversacion_id=conversacion_id,
            canal=canal,
            texto=texto_existente,
            dry_run=dry_run,
            enviar_callback=enviar_callback,
            token=token,
            phone_number_id=phone_number_id,
            destino=destino,
            motivo_fallback="reintento_envio",
            mensaje_externo_id=mensaje_externo_id,
        )
        enviado = bool(envio.get("enviado") is True) or dry_run
        resultado = dict(resultado)
        resultado.update(
            {
                "atendido": True,
                "respuesta_generada": True,
                "respuesta_enviada": enviado,
                "requiere_reintento": (not enviado) and (not dry_run),
                "mensaje_externo_id": envio.get("mensaje_externo_id"),
                "error": envio.get("error") or resultado.get("error"),
            }
        )
        return resultado

    from service_chatbot_respuesta_obligatoria import garantizar_respuesta_saliente

    texto = (
        "No estoy seguro de haber entendido. ¿Podrías explicármelo de otra manera? "
        "También puedes preguntarme por requisitos, beneficios, bonos o el proceso "
        "de ingreso."
    )
    envio = await garantizar_respuesta_saliente(
        agencia_id=agencia_id,
        conversacion_id=conversacion_id,
        canal=canal,
        texto=texto,
        dry_run=dry_run,
        enviar_callback=enviar_callback,
        token=token,
        phone_number_id=phone_number_id,
        destino=destino,
        motivo_fallback="mensaje_consumido_sin_respuesta",
        mensaje_externo_id=mensaje_externo_id,
    )
    enviado = bool(envio.get("enviado") is True) or dry_run
    if not enviado:
        logger.error(
            "[CHATBOT_FALLBACK] ERROR mensaje_consumido_sin_respuesta "
            "conversacion_id=%s envio_fallido respuesta_enviada=false",
            conversacion_id,
        )
    resultado = dict(resultado)
    resultado.update(
        {
            "usado": True,
            "atendido": True,
            "respuesta_generada": True,
            "respuesta": texto,
            "respuesta_enviada": enviado,
            "requiere_reintento": (not enviado) and (not dry_run),
            "motivo_fallback": "mensaje_consumido_sin_respuesta",
            "mensaje_externo_id": envio.get("mensaje_externo_id"),
            "error": envio.get("error"),
        }
    )
    return resultado
