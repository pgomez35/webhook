"""
Servicio conversacional del chatbot de captación (OpenAI Agents SDK).

Orden del flujo de un mensaje entrante:
1. Interruptor global `CHATBOT_CONVERSACIONAL_ENABLED`.
2. Buscar o crear la conversación del canal.
3. Insertar el mensaje entrante (con deduplicación por `mensaje_externo_id`).
4. Si la conversación está en atención humana, no responde la IA.
5. Resolver modo y campaña.
6. Construir contexto e instrucciones dinámicas.
7. Ejecutar el agente.
8. Enviar la respuesta por el canal (callback o adaptador Meta).
9. Guardar el mensaje saliente con modelo y tokens.
10. Actualizar `ultimo_mensaje_at` y `resumen_contexto`.
11. Si el proveedor de IA falla: mensaje de respaldo, evento de error y, tras
    varios fallos seguidos, escalamiento a una persona. El flujo no avanza.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import chatbot_conversacional_db_gateway as gw
from chatbot_conversacional_agent_factory import (
    AgentePreparado,
    crear_agente,
    feature_enabled,
    openai_configurado,
)
from chatbot_conversacional_context_builder import (
    LIMITE_MENSAJES,
    ConversationalContext,
    construir_contexto,
)
from chatbot_conversacional_exceptions import AsistenteInactivo, OpenAIFallido
from chatbot_conversacional_mode_resolver import MODOS_VALIDOS, resolver_modo
from chatbot_conversacional_prompt_builder import construir_resumen_contexto
from chatbot_conversacional_tools import ContextoHerramientas, RunContextWrapper, invocar_herramienta

logger = logging.getLogger("uvicorn.error")

MENSAJE_RESPALDO = (
    "Estoy teniendo un problema técnico para responderte en este momento. "
    "Ya quedó registrado para que una persona del equipo continúe contigo."
)
MAX_ERRORES_ANTES_ESCALAR = 3
ESTADOS_SIN_RESPUESTA_IA = frozenset({"esperando_humano", "bloqueada"})
CANAL_WHATSAPP = "whatsapp"
CANAL_INSTAGRAM = "instagram"

EnviarCallback = Callable[[str], Any]


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


async def _db(nombres: Any, *args: Any, **kwargs: Any) -> Any:
    """Ejecuta una función de DB (psycopg2 es bloqueante) fuera del event loop."""
    return await asyncio.to_thread(gw.call_opcional, nombres, *args, **kwargs)


async def _quizas_await(valor: Any) -> Any:
    if inspect.isawaitable(valor):
        return await valor
    return valor


def _resultado_no_usado(motivo: str, **extra: Any) -> Dict[str, Any]:
    return {"usado": False, "motivo": motivo, "respuesta": None, **extra}


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _normalizar_fila_db(valor: Any) -> Optional[Dict[str, Any]]:
    """Normaliza retornos `(fila, creado)` o solo fila de la capa de datos."""
    if isinstance(valor, tuple):
        valor = valor[0] if valor else None
    return valor if isinstance(valor, dict) else None


def _normalizar_fila_mensaje(valor: Any) -> Optional[Dict[str, Any]]:
    """Alias histórico: `insertar_mensaje` puede devolver `(fila, creado)`."""
    return _normalizar_fila_db(valor)


def debe_responder_ia(conversacion: Optional[Dict[str, Any]]) -> bool:
    """True si la conversación debe recibir respuesta automática del agente."""
    if not conversacion:
        return False
    if conversacion.get("modo_humano"):
        return False
    if conversacion.get("ia_habilitada") is False:
        return False
    estado = str(conversacion.get("estado") or "").strip().lower()
    if estado in ESTADOS_SIN_RESPUESTA_IA or estado == "cerrada":
        return False
    return True


def filtrar_beneficios_vigentes(
    beneficios: List[Dict[str, Any]],
    hoy: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Filtra beneficios activos dentro de vigencia (lógica pura para tests/UI)."""
    from datetime import date as date_cls

    referencia = hoy or date_cls.today()
    if hasattr(referencia, "date") and not isinstance(referencia, date_cls):
        referencia = referencia.date()

    def _a_fecha(valor: Any):
        if isinstance(valor, date_cls):
            return valor
        if hasattr(valor, "date"):
            try:
                return valor.date()
            except Exception:
                return None
        return None

    vigentes: List[Dict[str, Any]] = []
    for bono in beneficios or []:
        if not bono or bono.get("activo") is False:
            continue
        inicio = _a_fecha(bono.get("fecha_inicio"))
        fin = _a_fecha(bono.get("fecha_fin"))
        if inicio and referencia < inicio:
            continue
        if fin and referencia > fin:
            continue
        vigentes.append(bono)
    return vigentes


def estado_aspirante_permitido_para_ia(estado: Optional[str]) -> bool:
    """La IA no puede marcar aprobado/descartado ni mutar el campo estado."""
    if not estado:
        return True
    clave = str(estado).strip().lower()
    return clave not in {"aprobado", "descartado", "estado", "cumple_requisitos"}


def _texto_respaldo(contexto: Any = None) -> str:
    configuracion = getattr(contexto, "configuracion", None) or {}
    return str(configuracion.get("mensaje_error") or MENSAJE_RESPALDO)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


async def resolver_motor_conversacional(
    agencia_id: int,
    chatbot_configuracion_id: Optional[int],
) -> Dict[str, Any]:
    """
    Delega al resolver plano ``service_chatbot_motor`` (desplegable sin
    subcarpetas). Se mantiene async por compatibilidad con callers existentes.
    """
    from service_chatbot_motor import resolver_motor_conversacional as _resolver_plano

    return _resolver_plano(agencia_id, chatbot_configuracion_id)


async def debe_usar_conversacional(
    agencia_id: int,
    chatbot_configuracion_id: Optional[int],
) -> bool:
    """True si esta configuración debe atenderse con el motor conversacional."""
    decision = await resolver_motor_conversacional(
        agencia_id, chatbot_configuracion_id
    )
    return bool(decision.get("usar_conversacional"))


async def procesar_mensaje_conversacional(
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
) -> Dict[str, Any]:
    """Procesa un mensaje entrante y responde con el agente conversacional."""
    if not feature_enabled():
        return _resultado_no_usado("feature_deshabilitada")

    if not openai_configurado():
        return _resultado_no_usado("openai_no_configurado")

    if not gw.disponible():
        return _resultado_no_usado("db_conversacional_no_disponible")

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
    conversacion = _normalizar_fila_db(conversacion)

    if not conversacion:
        return _resultado_no_usado("conversacion_no_disponible")

    conversacion_id = conversacion.get("id")

    if mensaje_externo_id:
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
                mensaje_entrante_id=existente.get("id"),
            )

    mensaje_entrante = await _db(
        "insertar_mensaje",
        agencia_id,
        conversacion_id,
        canal=canal,
        direccion="entrante",
        remitente_tipo="aspirante",
        tipo_mensaje=tipo_mensaje,
        texto=texto,
        mensaje_externo_id=mensaje_externo_id,
        estado_envio="recibido",
        default=None,
    )
    # insertar_mensaje puede devolver (fila, creado) o solo la fila
    if isinstance(mensaje_entrante, tuple):
        mensaje_entrante = mensaje_entrante[0] if mensaje_entrante else None
    mensaje_entrante_id = (mensaje_entrante or {}).get("id") if isinstance(mensaje_entrante, dict) else None

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
        logger.info("chatbot_conversacional: asistente inactivo (%s)", exc)
        return _resultado_no_usado(
            "asistente_inactivo",
            conversacion_id=conversacion_id,
            mensaje_entrante_id=mensaje_entrante_id,
        )

    await _persistir_modo(contexto, dry_run=dry_run)

    preparado = crear_agente(contexto, dry_run=dry_run, mensaje_id=mensaje_entrante_id)
    entrada = _construir_entrada(contexto, texto, mensaje_entrante_id)

    try:
        ejecucion = await _ejecutar_agente(preparado, entrada)

    except Exception as exc:  # noqa: BLE001 - cualquier fallo del proveedor se degrada
        return await _manejar_fallo_ia(
            exc,
            contexto=contexto,
            preparado=preparado,
            conversacion_id=conversacion_id,
            mensaje_entrante_id=mensaje_entrante_id,
            canal=canal,
            token=token,
            phone_number_id=phone_number_id,
            destino=wa_id or usuario_externo_id,
            enviar_callback=enviar_callback,
            dry_run=dry_run,
        )

    ctxh = preparado.contexto_herramientas
    respuesta = ejecucion.get("texto") or ""
    enlaces = list(ctxh.enlaces)

    envio = await _enviar_respuesta(
        canal=canal,
        texto=respuesta,
        enlaces=enlaces,
        token=token,
        phone_number_id=phone_number_id,
        destino=wa_id or usuario_externo_id,
        enviar_callback=enviar_callback,
        dry_run=dry_run,
    )

    mensaje_saliente = None
    if respuesta and not dry_run:
        mensaje_saliente = await _db(
            "insertar_mensaje",
            agencia_id,
            conversacion_id,
            canal=canal,
            direccion="saliente",
            remitente_tipo="chatbot",
            tipo_mensaje="texto",
            texto=respuesta,
            estado_envio="enviado" if envio.get("enviado") else "error",
            error_detalle=envio.get("error"),
            procesado_por_ia=True,
            modelo_ia=preparado.modelo,
            prompt_version=preparado.prompt_version,
            tokens_entrada=ejecucion.get("tokens_entrada"),
            tokens_salida=ejecucion.get("tokens_salida"),
            metadata={
                "modo": contexto.modo,
                "herramientas": [accion.get("herramienta") for accion in ctxh.acciones],
                "enlaces": [enlace.get("codigo") for enlace in enlaces],
            },
            default=None,
        )
        mensaje_saliente = _normalizar_fila_mensaje(mensaje_saliente)

    await _actualizar_cierre_de_turno(
        contexto,
        respuesta=respuesta,
        mensaje_usuario=texto,
        acciones=ctxh.acciones,
        escalado=bool(ctxh.escalamiento),
        cerrada=bool(ctxh.cierre),
        dry_run=dry_run,
    )

    return {
        "usado": True,
        "motivo": None,
        "conversacion_id": conversacion_id,
        "mensaje_entrante_id": mensaje_entrante_id,
        "mensaje_saliente_id": (_normalizar_fila_mensaje(mensaje_saliente) or {}).get("id"),
        "respuesta": respuesta,
        "modo": contexto.modo,
        "modelo": preparado.modelo,
        "tokens_entrada": ejecucion.get("tokens_entrada"),
        "tokens_salida": ejecucion.get("tokens_salida"),
        "acciones": ctxh.acciones,
        "enlaces": enlaces,
        "escalado": bool(ctxh.escalamiento),
        "cerrada": bool(ctxh.cierre),
        "enviado": envio.get("enviado"),
        "error": envio.get("error"),
        "sdk": "openai-agents" if preparado.sdk_disponible else "chat_completions",
    }


async def simular_mensaje(
    *,
    agencia_id: int,
    chatbot_configuracion_id: Optional[int],
    texto: str,
    conversacion_id: Optional[int] = None,
    aspirante_id: Optional[int] = None,
    campania_id: Optional[int] = None,
    canal: str = CANAL_WHATSAPP,
    modo: Optional[str] = None,
    historial: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Ejecuta el agente en modo simulación (dry-run).

    No envía nada por Meta, no inserta mensajes ni eventos y no modifica
    aspirantes reales: sirve para probar prompts y configuración desde el panel.
    """
    if not openai_configurado():
        return _resultado_no_usado("openai_no_configurado")

    conversacion: Optional[Dict[str, Any]] = None
    if conversacion_id:
        conversacion = await _db(
            "obtener_conversacion", agencia_id, conversacion_id, default=None
        )

    if conversacion is None:
        conversacion = {
            "id": conversacion_id,
            "agencia_id": agencia_id,
            "chatbot_configuracion_id": chatbot_configuracion_id,
            "aspirante_id": aspirante_id,
            "campania_id": campania_id,
            "canal": canal,
            "estado": "abierta",
            "estado_actual": "inicio",
            "modo_humano": False,
            "ia_habilitada": True,
        }

    try:
        contexto = await asyncio.to_thread(
            construir_contexto,
            agencia_id=agencia_id,
            conversacion=conversacion,
            dry_run=True,
        )

    except AsistenteInactivo as exc:
        return _resultado_no_usado("asistente_inactivo", detalle=str(exc))

    if modo and modo in MODOS_VALIDOS:
        contexto.modo = modo

    if historial:
        contexto.mensajes = historial[-LIMITE_MENSAJES:]

    preparado = crear_agente(contexto, dry_run=True)
    entrada = _construir_entrada(contexto, texto, None)

    try:
        ejecucion = await _ejecutar_agente(preparado, entrada)

    except Exception as exc:  # noqa: BLE001
        logger.warning("chatbot_conversacional: simulación falló: %s", exc)
        return {
            "usado": False,
            "motivo": "openai_fallido",
            "respuesta": _texto_respaldo(contexto),
            "error": str(exc),
            "modo": contexto.modo,
            "modelo": preparado.modelo,
        }

    ctxh = preparado.contexto_herramientas

    return {
        "usado": True,
        "simulacion": True,
        "conversacion_id": contexto.conversacion_id,
        "respuesta": ejecucion.get("texto"),
        "modo": contexto.modo,
        "modelo": preparado.modelo,
        "tokens_entrada": ejecucion.get("tokens_entrada"),
        "tokens_salida": ejecucion.get("tokens_salida"),
        "acciones": ctxh.acciones,
        "enlaces": ctxh.enlaces,
        "escalado": bool(ctxh.escalamiento),
        "cerrada": bool(ctxh.cierre),
        "instrucciones": preparado.instrucciones,
    }


async def procesar_media_como_evidencia(
    *,
    agencia_id: int,
    conversacion_id: int,
    tipo_archivo: str,
    archivo_url: Optional[str] = None,
    archivo_id_externo: Optional[str] = None,
    archivo_nombre: Optional[str] = None,
    mime_type: Optional[str] = None,
    tipo_evidencia: Optional[str] = None,
    mensaje_id: Optional[int] = None,
    descripcion: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Registra una imagen, video o documento entrante como evidencia 'recibida'.

    Nunca aprueba la evidencia ni cambia el estado del aspirante.
    """
    if not gw.disponible():
        return _resultado_no_usado("db_conversacional_no_disponible")

    conversacion = await _db(
        "obtener_conversacion", agencia_id, conversacion_id, default=None
    )
    if not conversacion:
        return _resultado_no_usado("conversacion_no_encontrada")

    contexto = await asyncio.to_thread(
        construir_contexto,
        agencia_id=agencia_id,
        conversacion=conversacion,
        dry_run=dry_run,
    )

    ctxh = ContextoHerramientas(
        agencia_id=agencia_id,
        conversacion_id=conversacion_id,
        contexto=contexto,
        dry_run=dry_run,
        mensaje_id=mensaje_id,
    )

    requerida = _evidencia_requerida_para(contexto, tipo_archivo)

    resultado_json = await invocar_herramienta(
        "registrar_evidencia_recibida",
        ctxh,
        {
            "evidencia": {
                "tipo_evidencia": tipo_evidencia
                or _tipo_evidencia_por_momento((requerida or {}).get("momento_requerido")),
                "tipo_archivo": tipo_archivo,
                "archivo_url": archivo_url,
                "archivo_id_externo": archivo_id_externo,
                "descripcion": descripcion or archivo_nombre or mime_type,
                "evidencia_requerida_id": (requerida or {}).get("id"),
            }
        },
    )

    resultado = json.loads(resultado_json)

    return {
        "usado": bool(resultado.get("ok")),
        "motivo": None if resultado.get("ok") else "evidencia_no_registrada",
        "conversacion_id": conversacion_id,
        "evidencia_id": resultado.get("evidencia_id"),
        "estado": resultado.get("estado"),
        "evidencia_requerida": (requerida or {}).get("codigo"),
        "acciones": ctxh.acciones,
    }


# `evidencias_requeridas.momento_requerido` -> `evidencias_candidato.tipo_evidencia`
TIPO_EVIDENCIA_POR_MOMENTO = {
    "inicio_live": "inicio_live",
    "durante_live": "durante_live",
    "durante_batalla": "batalla",
    "final_live": "estadisticas_finales",
    "antes_live": "solicitud",
}


def _tipo_evidencia_por_momento(momento: Optional[str]) -> str:
    return TIPO_EVIDENCIA_POR_MOMENTO.get(str(momento or "").lower(), "otro")


def _evidencia_requerida_para(
    contexto: ConversationalContext,
    tipo_archivo: str,
) -> Optional[Dict[str, Any]]:
    """La evidencia requerida se declara por formato (imagen, video, documento...)."""
    for evidencia in contexto.evidencias_requeridas or []:
        if str(evidencia.get("tipo_evidencia") or "").lower() == str(tipo_archivo).lower():
            return evidencia

    return None


# ---------------------------------------------------------------------------
# Ejecución del agente
# ---------------------------------------------------------------------------


def _construir_entrada(
    contexto: ConversationalContext,
    texto: str,
    mensaje_actual_id: Optional[int],
) -> List[Dict[str, str]]:
    """Historial acotado + mensaje actual, en el formato de entrada del SDK."""
    mensajes = sorted(
        [item for item in (contexto.mensajes or []) if isinstance(item, dict)],
        key=lambda item: item.get("id") or 0,
    )

    entrada: List[Dict[str, str]] = []
    for mensaje in mensajes[-LIMITE_MENSAJES:]:
        if mensaje_actual_id and mensaje.get("id") == mensaje_actual_id:
            continue

        contenido = mensaje.get("texto")
        if not contenido:
            continue

        direccion = str(mensaje.get("direccion") or "")
        if direccion == "entrante":
            entrada.append({"role": "user", "content": str(contenido)})
        elif direccion == "saliente":
            entrada.append({"role": "assistant", "content": str(contenido)})

    entrada.append({"role": "user", "content": texto})
    return entrada


async def _ejecutar_agente(
    preparado: AgentePreparado,
    entrada: List[Dict[str, str]],
) -> Dict[str, Any]:
    if preparado.sdk_disponible and preparado.agente is not None:
        return await _ejecutar_con_sdk(preparado, entrada)

    return await _ejecutar_con_chat_completions(preparado, entrada)


async def _ejecutar_con_sdk(
    preparado: AgentePreparado,
    entrada: List[Dict[str, str]],
) -> Dict[str, Any]:
    from agents import Runner  # type: ignore

    try:
        resultado = await Runner.run(
            preparado.agente,
            entrada,
            context=preparado.contexto_herramientas,
            max_turns=preparado.max_turnos,
        )

    except Exception as exc:  # noqa: BLE001
        raise OpenAIFallido(f"Falló la ejecución del agente: {exc}") from exc

    tokens_entrada = 0
    tokens_salida = 0
    for respuesta in getattr(resultado, "raw_responses", []) or []:
        uso = getattr(respuesta, "usage", None)
        tokens_entrada += int(getattr(uso, "input_tokens", 0) or 0)
        tokens_salida += int(getattr(uso, "output_tokens", 0) or 0)

    salida = getattr(resultado, "final_output", None)

    return {
        "texto": str(salida or "").strip(),
        "tokens_entrada": tokens_entrada or None,
        "tokens_salida": tokens_salida or None,
    }


async def _ejecutar_con_chat_completions(
    preparado: AgentePreparado,
    entrada: List[Dict[str, str]],
) -> Dict[str, Any]:
    """
    Ejecutor de reserva cuando `openai-agents` no está instalado: mismo prompt y
    las mismas herramientas, resueltas con function calling clásico.
    """
    try:
        from openai import AsyncOpenAI

    except ImportError as exc:  # pragma: no cover
        raise OpenAIFallido("El paquete 'openai' no está instalado.") from exc

    cliente = AsyncOpenAI()

    herramientas = [
        {
            "type": "function",
            "function": {
                "name": herramienta.name,
                "description": herramienta.description or herramienta.name,
                "parameters": herramienta.params_json_schema,
            },
        }
        for herramienta in preparado.herramientas
    ]

    mensajes: List[Dict[str, Any]] = [
        {"role": "system", "content": preparado.instrucciones},
        *entrada,
    ]

    wrapper = RunContextWrapper(context=preparado.contexto_herramientas)
    por_nombre = {herramienta.name: herramienta for herramienta in preparado.herramientas}

    tokens_entrada = 0
    tokens_salida = 0

    for _ in range(preparado.max_turnos):
        try:
            respuesta = await cliente.chat.completions.create(
                model=preparado.modelo,
                messages=mensajes,
                tools=herramientas or None,
                max_tokens=preparado.max_tokens,
            )

        except Exception as exc:  # noqa: BLE001
            raise OpenAIFallido(f"Falló la llamada a OpenAI: {exc}") from exc

        uso = getattr(respuesta, "usage", None)
        tokens_entrada += int(getattr(uso, "prompt_tokens", 0) or 0)
        tokens_salida += int(getattr(uso, "completion_tokens", 0) or 0)

        mensaje = respuesta.choices[0].message
        llamadas = getattr(mensaje, "tool_calls", None) or []

        if not llamadas:
            return {
                "texto": str(mensaje.content or "").strip(),
                "tokens_entrada": tokens_entrada or None,
                "tokens_salida": tokens_salida or None,
            }

        mensajes.append(
            {
                "role": "assistant",
                "content": mensaje.content,
                "tool_calls": [
                    {
                        "id": llamada.id,
                        "type": "function",
                        "function": {
                            "name": llamada.function.name,
                            "arguments": llamada.function.arguments,
                        },
                    }
                    for llamada in llamadas
                ],
            }
        )

        for llamada in llamadas:
            herramienta = por_nombre.get(llamada.function.name)
            if herramienta is None:
                contenido = json.dumps({"ok": False, "error": "herramienta_no_disponible"})
            else:
                try:
                    contenido = await herramienta.on_invoke_tool(
                        wrapper, llamada.function.arguments or "{}"
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "chatbot_conversacional: herramienta %s falló: %s",
                        llamada.function.name,
                        exc,
                    )
                    contenido = json.dumps({"ok": False, "error": str(exc)})

            mensajes.append(
                {
                    "role": "tool",
                    "tool_call_id": llamada.id,
                    "content": contenido,
                }
            )

    raise OpenAIFallido("Se alcanzó el máximo de turnos sin respuesta final.")


# ---------------------------------------------------------------------------
# Envío por canal
# ---------------------------------------------------------------------------


async def _enviar_respuesta(
    *,
    canal: str,
    texto: str,
    enlaces: List[Dict[str, Any]],
    token: Optional[str],
    phone_number_id: Optional[str],
    destino: Optional[str],
    enviar_callback: Optional[EnviarCallback],
    dry_run: bool,
) -> Dict[str, Any]:
    if dry_run:
        return {"enviado": False, "motivo": "simulacion"}

    if not texto:
        return {"enviado": False, "motivo": "respuesta_vacia"}

    partes = [texto]
    for enlace in enlaces:
        etiqueta = enlace.get("nombre") or enlace.get("codigo") or "Enlace"
        partes.append(f"{etiqueta}: {enlace['url']}")

    if enviar_callback is not None:
        try:
            for parte in partes:
                await _quizas_await(enviar_callback(parte))
            return {"enviado": True}

        except Exception as exc:  # noqa: BLE001
            logger.error("chatbot_conversacional: callback de envío falló: %s", exc)
            return {"enviado": False, "error": str(exc)}

    if canal == CANAL_WHATSAPP:
        return await _enviar_whatsapp(partes, token, phone_number_id, destino)

    if canal == CANAL_INSTAGRAM:
        return await _enviar_instagram(partes, destino)

    return {"enviado": False, "motivo": f"canal_sin_adaptador:{canal}"}


async def _enviar_whatsapp(
    partes: List[str],
    token: Optional[str],
    phone_number_id: Optional[str],
    destino: Optional[str],
) -> Dict[str, Any]:
    if not token or not phone_number_id or not destino:
        return {"enviado": False, "motivo": "credenciales_whatsapp_incompletas"}

    from enviar_msg_wp import enviar_mensaje_texto_simple  # import lazy: evita ciclos

    for parte in partes:
        try:
            codigo, respuesta = await asyncio.to_thread(
                enviar_mensaje_texto_simple,
                token=token,
                numero_id=phone_number_id,
                telefono_destino=destino,
                texto=parte,
            )

        except Exception as exc:  # noqa: BLE001
            logger.error("chatbot_conversacional: error enviando WhatsApp: %s", exc)
            return {"enviado": False, "error": str(exc)}

        if not 200 <= int(codigo or 0) < 300:
            return {"enviado": False, "error": str(respuesta)[:300]}

    return {"enviado": True}


async def _enviar_instagram(partes: List[str], destino: Optional[str]) -> Dict[str, Any]:
    if not destino:
        return {"enviado": False, "motivo": "destino_instagram_ausente"}

    try:
        from instagram_messaging_client import InstagramMessagingClient

        cliente = InstagramMessagingClient()
        for parte in partes:
            await cliente.send_text(destino, parte)

        return {"enviado": True}

    except Exception as exc:  # noqa: BLE001
        logger.error("chatbot_conversacional: error enviando Instagram: %s", exc)
        return {"enviado": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Persistencia de cierre de turno y manejo de fallos
# ---------------------------------------------------------------------------


async def _persistir_modo(contexto: ConversationalContext, *, dry_run: bool) -> None:
    if dry_run or not contexto.conversacion_id:
        return

    campos: Dict[str, Any] = {}
    if contexto.conversacion.get("modo") != contexto.modo:
        campos["modo"] = contexto.modo

    campania_id = contexto.campania_id
    if campania_id and contexto.conversacion.get("campania_id") != campania_id:
        campos["campania_id"] = campania_id

    flujo_id = (contexto.flujo or {}).get("id")
    if flujo_id and contexto.conversacion.get("flujo_id") != flujo_id:
        campos["flujo_id"] = flujo_id

    if campos:
        await _db("actualizar_conversacion", contexto.agencia_id, contexto.conversacion_id, campos)
        contexto.conversacion.update(campos)


async def _actualizar_cierre_de_turno(
    contexto: ConversationalContext,
    *,
    respuesta: str,
    mensaje_usuario: str,
    acciones: List[Dict[str, Any]],
    escalado: bool,
    cerrada: bool,
    dry_run: bool,
) -> None:
    if dry_run or not contexto.conversacion_id:
        return

    resumen = construir_resumen_contexto(
        contexto,
        mensaje_usuario=mensaje_usuario,
        respuesta=respuesta,
        acciones=acciones,
    )

    campos: Dict[str, Any] = {
        "ultimo_mensaje_at": _ahora(),
        "resumen_contexto": resumen,
    }

    if not escalado and not cerrada:
        campos["estado"] = "esperando_usuario"

    await _db("actualizar_conversacion", contexto.agencia_id, contexto.conversacion_id, campos)


async def _manejar_fallo_ia(
    error: Exception,
    *,
    contexto: ConversationalContext,
    preparado: AgentePreparado,
    conversacion_id: Optional[int],
    mensaje_entrante_id: Optional[int],
    canal: str,
    token: Optional[str],
    phone_number_id: Optional[str],
    destino: Optional[str],
    enviar_callback: Optional[EnviarCallback],
    dry_run: bool,
) -> Dict[str, Any]:
    """
    Fallo del proveedor de IA: mensaje de respaldo, evento de error y
    escalamiento tras varios fallos seguidos. El flujo NO avanza.
    """
    logger.error(
        "chatbot_conversacional: fallo de IA (agencia=%s conversacion=%s): %s",
        contexto.agencia_id,
        conversacion_id,
        error,
    )

    if not dry_run and conversacion_id:
        await _db(
            "registrar_evento",
            contexto.agencia_id,
            conversacion_id,
            tipo_evento="error",
            nombre_evento="openai_fallido",
            origen="backend",
            mensaje_id=mensaje_entrante_id,
            exitoso=False,
            detalle={"modelo": preparado.modelo, "modo": contexto.modo},
            error_detalle=str(error)[:1000],
        )

    errores_recientes = 0
    if not dry_run and conversacion_id:
        errores_recientes = int(
            await _db(
                "contar_errores_ia_recientes",
                contexto.agencia_id,
                conversacion_id,
                default=0,
            )
            or 0
        )

    escalado = errores_recientes >= MAX_ERRORES_ANTES_ESCALAR

    texto = _texto_respaldo(contexto)
    envio = await _enviar_respuesta(
        canal=canal,
        texto=texto,
        enlaces=[],
        token=token,
        phone_number_id=phone_number_id,
        destino=destino,
        enviar_callback=enviar_callback,
        dry_run=dry_run,
    )

    if not dry_run and conversacion_id:
        await _db(
            "insertar_mensaje",
            contexto.agencia_id,
            conversacion_id,
            canal=canal,
            direccion="saliente",
            remitente_tipo="sistema",
            tipo_mensaje="texto",
            texto=texto,
            estado_envio="enviado" if envio.get("enviado") else "error",
            error_detalle=envio.get("error") or str(error)[:500],
            modelo_ia=preparado.modelo,
            metadata={"fallback": True, "escalado": escalado},
        )

        if escalado:
            await _db(
                "actualizar_conversacion",
                contexto.agencia_id,
                conversacion_id,
                {
                    "estado": "esperando_humano",
                    "modo_humano": True,
                    "motivo_escalamiento": "fallos_consecutivos_ia",
                },
            )
            await _db(
                "registrar_evento",
                contexto.agencia_id,
                conversacion_id,
                tipo_evento="escalamiento",
                nombre_evento="escalamiento_por_errores_ia",
                origen="backend",
                estado_anterior=contexto.conversacion.get("estado"),
                estado_nuevo="esperando_humano",
                detalle={"errores_recientes": errores_recientes},
            )

    return {
        "usado": True,
        "motivo": "openai_fallido",
        "conversacion_id": conversacion_id,
        "mensaje_entrante_id": mensaje_entrante_id,
        "respuesta": texto,
        "modo": contexto.modo,
        "modelo": preparado.modelo,
        "acciones": preparado.contexto_herramientas.acciones,
        "enlaces": [],
        "escalado": escalado,
        "errores_recientes": errores_recientes,
        "enviado": envio.get("enviado"),
        "error": str(error)[:500],
    }


__all__ = [
    "debe_usar_conversacional",
    "feature_enabled",
    "procesar_media_como_evidencia",
    "procesar_mensaje_conversacional",
    "resolver_motor_conversacional",
    "simular_mensaje",
]
