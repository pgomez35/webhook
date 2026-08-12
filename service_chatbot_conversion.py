"""
Motor INTELIGENTE: conversion recuperado.

GPT conversa libremente + conocimiento de agencia + memoria de hechos
+ backend (action gate) + sanitización única de salida.

NO usa el reducer V2 ni el orquestador rígido como controlador conversacional.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional

import chatbot_conversacional_db_gateway as gw
from chatbot_conversacional_agent_factory import (
    feature_enabled,
    openai_configurado,
    resolver_modelo,
    temperatura,
)
from chatbot_conversacional_context_builder import ConversationalContext, construir_contexto
from chatbot_conversacional_exceptions import AsistenteInactivo, OpenAIFallido
from chatbot_conversacional_perfil import leer_perfil, normalizar_json_safe
from chatbot_conversacional_prompt_builder import construir_instrucciones, construir_resumen_contexto
from chatbot_conversion_core import (
    ResultadoTurnoConversion,
    SalidaIAConversion,
    aplicar_turno_backend,
    construir_addendum_conversion,
    json_safe_dumps,
    parsear_salida_ia,
    sanitizar_respuesta_publica,
    schema_salida_conversion,
)
from chatbot_conversion_atajos_numericos import (
    escribir_mapa_atajos,
    mapa_menu_inicial,
    resolver_atajo_numerico,
    texto_bienvenida_con_atajos,
)
from chatbot_conversion_flags import (
    HERRAMIENTAS_EXTERNAS_CONVERSION,
    conversion_tools_externas_habilitadas,
)
from chatbot_envio_whatsapp import fijar_conversacion_id_envio

logger = logging.getLogger("uvicorn.error")


def _nombre_agencia_atajos(contexto: ConversationalContext) -> str:
    agencia = contexto.agencia or {}
    asistente = contexto.asistente or {}
    return (
        str(agencia.get("nombre") or "").strip()
        or str(agencia.get("nombre_comercial") or "").strip()
        or str(asistente.get("nombre_asistente") or "").strip()
        or "la agencia"
    )


def _es_primer_contacto_conversion(
    *,
    mensajes: Optional[List[Dict[str, Any]]],
    mensaje_actual_id: Optional[int],
    texto: str,
) -> bool:
    """Misma idea que presentacion_literal, sin depender de presentacion_inicial."""
    from service_chatbot_conversacional import es_saludo_inicial

    previos: List[Dict[str, Any]] = []
    for item in mensajes or []:
        if not isinstance(item, dict):
            continue
        if mensaje_actual_id is not None and item.get("id") == mensaje_actual_id:
            continue
        previos.append(item)
    if any(str(m.get("direccion") or "").lower() == "saliente" for m in previos):
        return False
    return bool(es_saludo_inicial(texto) or not previos)

MENSAJE_RESPALDO = (
    "Estoy teniendo un problema técnico para responderte en este momento. "
    "Ya quedó registrado para que una persona del equipo continúe contigo."
)
ESTADOS_SIN_RESPUESTA_IA = frozenset({"esperando_humano", "bloqueada"})
CANAL_WHATSAPP = "whatsapp"

EnviarCallback = Callable[[str], Any]


async def _db(nombre: str, *args: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(gw.call_opcional, nombre, *args, **kwargs)


def _normalizar_fila(valor: Any) -> Optional[Dict[str, Any]]:
    if isinstance(valor, tuple):
        valor = valor[0] if valor else None
    return valor if isinstance(valor, dict) else None


def _resultado_no_usado(motivo: str, **extra: Any) -> Dict[str, Any]:
    out = {"usado": False, "motivo": motivo, "motor": "conversion"}
    out.update(extra)
    return out


def _pregunta_pendiente_texto(conversacion: Optional[Dict[str, Any]]) -> Optional[str]:
    ctx = (conversacion or {}).get("contexto") or {}
    if not isinstance(ctx, dict):
        return None
    pend = ctx.get("pregunta_pendiente") or ctx.get("pending_question")
    if isinstance(pend, dict):
        texto = str(pend.get("texto") or "").strip()
        return texto or None
    if isinstance(pend, str) and pend.strip():
        return pend.strip()
    return None


async def _generar_turno_structured(
    *,
    contexto: ConversationalContext,
    texto_usuario: str,
    perfil: Dict[str, Any],
) -> SalidaIAConversion:
    """Llamada principal: GPT conversa + hechos estructurados."""
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:  # pragma: no cover
        raise OpenAIFallido("El paquete 'openai' no está instalado.") from exc

    instrucciones = construir_instrucciones(contexto)
    addendum = construir_addendum_conversion(
        perfil=perfil,
        pregunta_pendiente_texto=_pregunta_pendiente_texto(contexto.conversacion),
    )
    system = f"{instrucciones}\n\n{addendum}"

    historial: List[Dict[str, str]] = []
    for mensaje in (contexto.mensajes or [])[-20:]:
        contenido = str(mensaje.get("texto") or "").strip()
        if not contenido:
            continue
        direccion = str(mensaje.get("direccion") or "").strip().lower()
        if direccion == "entrante":
            historial.append({"role": "user", "content": contenido})
        elif direccion == "saliente":
            historial.append({"role": "assistant", "content": contenido})

    mensajes = [{"role": "system", "content": system}]
    mensajes.extend(historial)
    mensajes.append({"role": "user", "content": texto_usuario})

    modelo = resolver_modelo(contexto.asistente)
    cliente = AsyncOpenAI()
    kwargs: Dict[str, Any] = {
        "model": modelo,
        "messages": mensajes,
        "temperature": temperatura(contexto.asistente),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "salida_conversion",
                "strict": False,
                "schema": schema_salida_conversion(),
            },
        },
    }
    try:
        resp = await cliente.chat.completions.create(**kwargs)
    except Exception:
        # Fallback si el modelo no acepta json_schema estricto.
        kwargs.pop("response_format", None)
        kwargs["response_format"] = {"type": "json_object"}
        kwargs["messages"] = list(mensajes)
        kwargs["messages"][0] = {
            "role": "system",
            "content": system
            + "\nResponde ÚNICAMENTE un objeto JSON válido con las claves "
            "respuesta, hechos_nuevos, correcciones, accion_propuesta, requiere_humano.",
        }
        resp = await cliente.chat.completions.create(**kwargs)

    contenido = ""
    if resp.choices:
        contenido = str(resp.choices[0].message.content or "")
    salida = parsear_salida_ia(contenido)
    logger.info(
        "[CHATBOT_CONVERSION_AI] facts_detected=%s corrections=%s proposed_action=%s",
        json_safe_dumps(salida.hechos_nuevos),
        json_safe_dumps(salida.correcciones),
        salida.accion_propuesta,
    )
    return salida


async def _enviar(
    *,
    texto: str,
    canal: str,
    token: Optional[str],
    phone_number_id: Optional[str],
    destino: Optional[str],
    enviar_callback: Optional[EnviarCallback],
    dry_run: bool,
    conversacion_id: Optional[int],
) -> Dict[str, Any]:
    texto = sanitizar_respuesta_publica(texto)
    if not texto:
        return {"enviado": False, "error": "respuesta_vacia"}
    if dry_run:
        return {"enviado": True, "dry_run": True, "texto": texto}

    fijar_conversacion_id_envio(conversacion_id)
    if enviar_callback is not None:
        try:
            from chatbot_envio_whatsapp import normalizar_resultado_envio

            raw = enviar_callback(texto)
            if asyncio.iscoroutine(raw) or asyncio.isfuture(raw):
                raw = await raw
            return normalizar_resultado_envio(raw)
        except Exception as exc:  # noqa: BLE001
            logger.error("[CHATBOT_CONVERSION_OUTPUT] callback_error=%s", exc)
            return {"enviado": False, "error": str(exc)[:300]}

    if canal == CANAL_WHATSAPP and token and phone_number_id and destino:
        from chatbot_envio_whatsapp import enviar_whatsapp_texto_meta

        return await enviar_whatsapp_texto_meta(
            token=token,
            phone_number_id=phone_number_id,
            destino=destino,
            texto=texto,
            conversacion_id=conversacion_id,
        )
    return {"enviado": False, "error": "sin_canal"}


async def _persistir_campos(
    *,
    agencia_id: int,
    conversacion_id: int,
    campos: Dict[str, Any],
) -> bool:
    try:
        resultado = await asyncio.to_thread(
            gw.call,
            "actualizar_conversacion",
            agencia_id,
            conversacion_id,
            normalizar_json_safe(campos),
        )
        ok = resultado is not None
        logger.info(
            "[CHATBOT_CONVERSION_PERSISTENCIA] conversacion_id=%s resultado=%s",
            conversacion_id,
            "ok" if ok else "error",
        )
        return ok
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[CHATBOT_CONVERSION_PERSISTENCIA] conversacion_id=%s error=%s",
            conversacion_id,
            str(exc)[:300],
        )
        return False


def herramientas_excluidas_fase() -> Optional[List[str]]:
    if conversion_tools_externas_habilitadas():
        return None
    return sorted(HERRAMIENTAS_EXTERNAS_CONVERSION)


async def procesar_turno_conversion_inyectado(
    *,
    salida_ia: SalidaIAConversion | Dict[str, Any] | str,
    conversacion: Dict[str, Any],
    aspirante: Optional[Dict[str, Any]] = None,
    requisitos: Optional[List[Dict[str, Any]]] = None,
    flujo: Optional[Dict[str, Any]] = None,
    paso: Optional[Dict[str, Any]] = None,
) -> ResultadoTurnoConversion:
    """API de prueba: aplica backend sobre una salida IA ya resuelta."""
    salida = parsear_salida_ia(salida_ia)
    return aplicar_turno_backend(
        salida=salida,
        conversacion=conversacion,
        aspirante=aspirante,
        requisitos=requisitos,
        flujo=flujo,
        paso=paso,
    )


async def procesar_mensaje_conversion(
    *,
    agencia_id: int,
    texto: str,
    usuario_externo_id: str,
    chatbot_configuracion_id: Optional[int] = None,
    canal: str = CANAL_WHATSAPP,
    cuenta_externa_id: Optional[str] = None,
    telefono: Optional[str] = None,
    nombre_contacto: Optional[str] = None,
    mensaje_externo_id: Optional[str] = None,
    tipo_mensaje: str = "texto",
    aspirante_id: Optional[int] = None,
    campania_id: Optional[int] = None,
    token: Optional[str] = None,
    phone_number_id: Optional[str] = None,
    wa_id: Optional[str] = None,
    enviar_callback: Optional[EnviarCallback] = None,
    dry_run: bool = False,
    salida_ia_inyectada: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Pipeline:
      mensaje → contexto/perfil/conocimiento → GPT structured → hechos → gate → sanitize → envío
    """
    if not feature_enabled():
        return _resultado_no_usado("feature_deshabilitada")
    if salida_ia_inyectada is None and not openai_configurado():
        return _resultado_no_usado("openai_no_configurado")
    if not gw.disponible() and not dry_run and salida_ia_inyectada is None:
        return _resultado_no_usado("db_conversacional_no_disponible")

    logger.info(
        "[CHATBOT_CONVERSION_INPUT] agencia_id=%s config_id=%s texto=%s",
        agencia_id,
        chatbot_configuracion_id,
        (texto or "")[:200],
    )

    conversacion = await _db(
        "obtener_o_crear_conversacion",
        agencia_id,
        canal=canal,
        usuario_externo_id=usuario_externo_id,
        cuenta_externa_id=cuenta_externa_id,
        chatbot_configuracion_id=chatbot_configuracion_id,
        aspirante_id=aspirante_id,
        telefono=telefono or (wa_id if canal == CANAL_WHATSAPP else None),
        nombre_contacto=nombre_contacto,
        campania_id=campania_id,
        default=None,
    )
    conversacion = _normalizar_fila(conversacion)
    if not conversacion and dry_run:
        conversacion = {
            "id": None,
            "agencia_id": agencia_id,
            "chatbot_configuracion_id": chatbot_configuracion_id,
            "contexto": {},
            "estado": "abierta",
            "ia_habilitada": True,
            "modo_humano": False,
        }
    if not conversacion:
        return _resultado_no_usado("conversacion_no_disponible")

    conversacion_id = conversacion.get("id")
    fijar_conversacion_id_envio(conversacion_id)

    if mensaje_externo_id and conversacion_id and not dry_run:
        existente = await _db(
            "obtener_mensaje_por_externo_id",
            agencia_id,
            conversacion_id,
            mensaje_externo_id,
            default=None,
        )
        if existente:
            return _resultado_no_usado(
                "mensaje_duplicado",
                conversacion_id=conversacion_id,
                mensaje_entrante_id=(existente or {}).get("id"),
            )

    mensaje_entrante_id = None
    if conversacion_id and not dry_run:
        mensaje_entrante = await _db(
            "insertar_mensaje",
            agencia_id,
            conversacion_id,
            canal=canal,
            direccion="entrante",
            remitente_tipo="aspirante",  # chk_mensaje_remitente
            tipo_mensaje=tipo_mensaje,
            texto=texto,
            mensaje_externo_id=mensaje_externo_id,
            estado_envio="recibido",
            default=None,
        )
        mensaje_entrante = _normalizar_fila(mensaje_entrante)
        mensaje_entrante_id = (mensaje_entrante or {}).get("id")

    if conversacion.get("modo_humano") or str(conversacion.get("estado") or "") in ESTADOS_SIN_RESPUESTA_IA:
        return _resultado_no_usado(
            "atencion_humana",
            conversacion_id=conversacion_id,
            mensaje_entrante_id=mensaje_entrante_id,
        )
    if conversacion.get("ia_habilitada") is False:
        return _resultado_no_usado(
            "ia_deshabilitada",
            conversacion_id=conversacion_id,
            mensaje_entrante_id=mensaje_entrante_id,
        )

    try:
        contexto = await asyncio.to_thread(
            construir_contexto,
            agencia_id=agencia_id,
            conversacion=conversacion,
            dry_run=dry_run,
        )
    except AsistenteInactivo as exc:
        return _resultado_no_usado(
            "asistente_inactivo",
            conversacion_id=conversacion_id,
            mensaje_entrante_id=mensaje_entrante_id,
            detalle=str(exc),
        )

    # Bienvenida con atajos numéricos (primer contacto).
    from service_chatbot_conversacional import (
        preservar_formato_whatsapp,
        resolver_presentacion_literal,
    )

    presentacion_cfg = resolver_presentacion_literal(
        asistente=contexto.asistente,
        mensajes=contexto.mensajes,
        texto_usuario=texto,
        mensaje_actual_id=mensaje_entrante_id,
    )
    debe_bienvenida = salida_ia_inyectada is None and (
        bool(presentacion_cfg)
        or _es_primer_contacto_conversion(
            mensajes=contexto.mensajes,
            mensaje_actual_id=mensaje_entrante_id,
            texto=texto or "",
        )
    )

    if debe_bienvenida:
        presentacion = texto_bienvenida_con_atajos(_nombre_agencia_atajos(contexto))
        presentacion = preservar_formato_whatsapp(presentacion)
        presentacion = sanitizar_respuesta_publica(presentacion)
        presentacion = preservar_formato_whatsapp(presentacion)
        ctx_mapa = escribir_mapa_atajos(contexto.conversacion, mapa_menu_inicial())
        if conversacion_id and not dry_run:
            await _persistir_campos(
                agencia_id=agencia_id,
                conversacion_id=int(conversacion_id),
                campos={"contexto": ctx_mapa},
            )
        logger.info(
            "[CHATBOT_CONVERSION_PRESENTACION] chars=%s saltos=%s atajos=1",
            len(presentacion or ""),
            (presentacion or "").count("\n"),
        )
        envio = await _enviar(
            texto=presentacion,
            canal=canal,
            token=token,
            phone_number_id=phone_number_id,
            destino=wa_id or usuario_externo_id,
            enviar_callback=enviar_callback,
            dry_run=dry_run,
            conversacion_id=conversacion_id,
        )
        if conversacion_id and presentacion and not dry_run:
            await _db(
                "insertar_mensaje",
                agencia_id,
                conversacion_id,
                canal=canal,
                direccion="saliente",
                remitente_tipo="chatbot",
                tipo_mensaje="texto",
                texto=presentacion,
                estado_envio="enviado" if envio.get("enviado") is True else "error",
                error_detalle=envio.get("error"),
                procesado_por_ia=False,
                metadata={"origen": "presentacion_inicial_atajos"},
                default=None,
            )
        return {
            "usado": True,
            "motivo": "presentacion_inicial",
            "motor": "conversion",
            "conversacion_id": conversacion_id,
            "mensaje_entrante_id": mensaje_entrante_id,
            "respuesta": presentacion,
            "enviado": envio.get("enviado"),
            "respuesta_enviada": bool(envio.get("enviado") is True) or dry_run,
            "error": envio.get("error"),
        }

    # Atajos numéricos contextuales (antes de la IA).
    atajo = resolver_atajo_numerico(
        texto or "",
        conversacion=contexto.conversacion,
        requisitos=contexto.requisitos,
        beneficios=contexto.beneficios,
    )
    if atajo and atajo.respuesta and salida_ia_inyectada is None:
        from service_chatbot_conversacional import preservar_formato_whatsapp

        respuesta_atajo = preservar_formato_whatsapp(atajo.respuesta)
        respuesta_atajo = sanitizar_respuesta_publica(respuesta_atajo)
        respuesta_atajo = preservar_formato_whatsapp(respuesta_atajo)
        if atajo.limpiar_mapa:
            ctx_mapa = escribir_mapa_atajos(contexto.conversacion, None)
        elif atajo.mapa_nuevo is not None:
            ctx_mapa = escribir_mapa_atajos(
                contexto.conversacion, atajo.mapa_nuevo
            )
        else:
            ctx_mapa = contexto.conversacion.get("contexto") or {}
        if conversacion_id and not dry_run and (
            atajo.limpiar_mapa or atajo.mapa_nuevo is not None
        ):
            await _persistir_campos(
                agencia_id=agencia_id,
                conversacion_id=int(conversacion_id),
                campos={"contexto": ctx_mapa},
            )
        envio = await _enviar(
            texto=respuesta_atajo,
            canal=canal,
            token=token,
            phone_number_id=phone_number_id,
            destino=wa_id or usuario_externo_id,
            enviar_callback=enviar_callback,
            dry_run=dry_run,
            conversacion_id=conversacion_id,
        )
        if conversacion_id and respuesta_atajo and not dry_run:
            await _db(
                "insertar_mensaje",
                agencia_id,
                conversacion_id,
                canal=canal,
                direccion="saliente",
                remitente_tipo="chatbot",
                tipo_mensaje="texto",
                texto=respuesta_atajo,
                estado_envio="enviado" if envio.get("enviado") is True else "error",
                error_detalle=envio.get("error"),
                procesado_por_ia=False,
                metadata={"origen": atajo.motivo},
                default=None,
            )
        return {
            "usado": True,
            "motivo": atajo.motivo,
            "motor": "conversion",
            "conversacion_id": conversacion_id,
            "mensaje_entrante_id": mensaje_entrante_id,
            "respuesta": respuesta_atajo,
            "enviado": envio.get("enviado"),
            "respuesta_enviada": bool(envio.get("enviado") is True) or dry_run,
            "error": envio.get("error"),
        }
    if atajo and atajo.texto_para_ia:
        texto = atajo.texto_para_ia
        logger.info("[CHATBOT_ATAJO] reescritura_continuar texto=%s", (texto or "")[:120])

    perfil = leer_perfil(contexto.conversacion, contexto.aspirante)
    logger.info(
        "[CHATBOT_CONVERSION_CONTEXT] known_facts=%s blockers=%s",
        json_safe_dumps(perfil.get("hechos") or {}),
        json_safe_dumps(perfil.get("bloqueantes_incumplidos") or []),
    )

    try:
        if salida_ia_inyectada is not None:
            salida = parsear_salida_ia(salida_ia_inyectada)
        else:
            salida = await _generar_turno_structured(
                contexto=contexto,
                texto_usuario=texto or "",
                perfil=perfil,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[CHATBOT_CONVERSION_AI] error=%s", exc)
        respuesta = sanitizar_respuesta_publica(MENSAJE_RESPALDO)
        envio = await _enviar(
            texto=respuesta,
            canal=canal,
            token=token,
            phone_number_id=phone_number_id,
            destino=wa_id or usuario_externo_id,
            enviar_callback=enviar_callback,
            dry_run=dry_run,
            conversacion_id=conversacion_id,
        )
        return {
            "usado": True,
            "motivo": "fallo_ia",
            "motor": "conversion",
            "conversacion_id": conversacion_id,
            "respuesta": respuesta,
            "enviado": envio.get("enviado"),
            "respuesta_enviada": bool(envio.get("enviado") is True) or dry_run,
            "error": str(exc)[:300],
        }

    resultado = aplicar_turno_backend(
        salida=salida,
        conversacion=contexto.conversacion,
        aspirante=contexto.aspirante,
        requisitos=contexto.requisitos,
        flujo=contexto.flujo,
        paso=contexto.paso,
    )

    if conversacion_id and not dry_run and resultado.campos_conversacion:
        await _persistir_campos(
            agencia_id=agencia_id,
            conversacion_id=int(conversacion_id),
            campos=resultado.campos_conversacion,
        )
        if contexto.aspirante_id and resultado.campos_aspirante:
            await _db(
                "actualizar_datos_explicitos_aspirante",
                agencia_id,
                int(contexto.aspirante_id),
                resultado.campos_aspirante,
                default=None,
            )

    respuesta = resultado.respuesta_publica
    logger.info(
        "[CHATBOT_CONVERSION_OUTPUT] chars=%s accion_ejecutable=%s",
        len(respuesta or ""),
        resultado.accion_propuesta,
    )

    envio = await _enviar(
        texto=respuesta,
        canal=canal,
        token=token,
        phone_number_id=phone_number_id,
        destino=wa_id or usuario_externo_id,
        enviar_callback=enviar_callback,
        dry_run=dry_run,
        conversacion_id=conversacion_id,
    )

    if conversacion_id and respuesta and not dry_run:
        await _db(
            "insertar_mensaje",
            agencia_id,
            conversacion_id,
            canal=canal,
            direccion="saliente",
            remitente_tipo="chatbot",
            tipo_mensaje="texto",
            texto=respuesta,
            estado_envio="enviado" if envio.get("enviado") is True else "error",
            error_detalle=envio.get("error"),
            mensaje_externo_id=envio.get("mensaje_externo_id"),
            procesado_por_ia=True,
            metadata=normalizar_json_safe(
                {
                    "motor": "conversion",
                    "hechos": resultado.hechos_aplicados,
                    "correcciones": resultado.correcciones,
                    "accion_propuesta": salida.accion_propuesta,
                    "gate": resultado.gate,
                    "tools_externas": conversion_tools_externas_habilitadas(),
                }
            ),
            default=None,
        )

    # Resumen corto para continuidad (sin máquina de estados).
    if conversacion_id and not dry_run:
        try:
            resumen = construir_resumen_contexto(
                contexto,
                mensaje_usuario=texto or "",
                respuesta=respuesta,
                acciones=[],
            )
            if resumen:
                await _persistir_campos(
                    agencia_id=agencia_id,
                    conversacion_id=int(conversacion_id),
                    campos={"resumen_contexto": resumen},
                )
        except Exception:  # noqa: BLE001
            pass

    return {
        "usado": True,
        "motivo": None,
        "motor": "conversion",
        "conversacion_id": conversacion_id,
        "mensaje_entrante_id": mensaje_entrante_id,
        "respuesta": respuesta,
        "hechos": resultado.hechos_aplicados,
        "correcciones": resultado.correcciones,
        "accion_propuesta": salida.accion_propuesta,
        "accion_ejecutada": resultado.accion_propuesta,
        "gate": resultado.gate,
        "perfil": resultado.perfil,
        "enviado": envio.get("enviado"),
        "respuesta_enviada": bool(envio.get("enviado") is True) or dry_run,
        "error": envio.get("error"),
        "requiere_humano": resultado.requiere_humano,
    }
