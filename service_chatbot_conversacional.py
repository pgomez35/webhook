"""
Servicio conversacional del chatbot de captación (OpenAI Agents SDK).

Orden del flujo de un mensaje entrante:
1. Interruptor global `CHATBOT_CONVERSACIONAL_ENABLED`.
2. Buscar o crear la conversación del canal.
3. Insertar el mensaje entrante (con deduplicación por `mensaje_externo_id`).
4. Si la conversación está en atención humana, no responde la IA.
5. Resolver modo y campaña.
6. Construir contexto e instrucciones dinámicas.
7. Si la conversación aún no tiene respuesta del asistente y hay
   `presentacion_inicial`, enviarla literalmente (sin modelo ni herramientas).
8. Ejecutar el agente (desde el segundo turno o si no hay presentación).
9. Enviar la respuesta por el canal (callback o adaptador Meta).
10. Guardar el mensaje saliente con modelo y tokens (o marca de bienvenida literal).
11. Actualizar `ultimo_mensaje_at` y `resumen_contexto`.
12. Si el proveedor de IA falla: mensaje de respaldo, evento de error y, tras
    varios fallos seguidos, escalamiento a una persona. El flujo no avanza.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import unicodedata
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
from chatbot_conversacional_tools import (
    ContextoHerramientas,
    RunContextWrapper,
    invocar_herramienta,
    preparar_envio_enlace_autorizado,
)
from chatbot_conversacional_clasificacion import (
    clasificar_mensaje,
    inferir_intencion,
    usar_rutas_adaptativas,
)

logger = logging.getLogger("uvicorn.error")

MENSAJE_RESPALDO = (
    "Estoy teniendo un problema técnico para responderte en este momento. "
    "Ya quedó registrado para que una persona del equipo continúe contigo."
)
MAX_ERRORES_ANTES_ESCALAR = 3
ESTADOS_SIN_RESPUESTA_IA = frozenset({"esperando_humano", "bloqueada"})
CANAL_WHATSAPP = "whatsapp"
CANAL_INSTAGRAM = "instagram"

# Saludos cortos que disparan la presentación literal en conversaciones nuevas.
_SALUDOS_EXACTOS = frozenset(
    {
        "hola",
        "hola hola",
        "holi",
        "holis",
        "holaa",
        "hola!",
        "buenas",
        "buen dia",
        "buenos dias",
        "buenas tardes",
        "buenas noches",
        "buenas buenas",
        "hey",
        "hi",
        "hello",
        "ola",
        "saludos",
        "que tal",
        "qué tal",
        "que hubo",
    }
)
_SALUDOS_INICIO = frozenset(
    {"hola", "holi", "holis", "holaa", "buenas", "hey", "hi", "hello", "ola", "saludos"}
)

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


def _normalizar_texto_saludo(texto: str) -> str:
    """Minúsculas sin acentos ni puntuación; conserva palabras para comparar saludos."""
    valor = str(texto or "").strip().lower()
    if not valor:
        return ""
    valor = unicodedata.normalize("NFD", valor)
    valor = "".join(ch for ch in valor if unicodedata.category(ch) != "Mn")
    valor = re.sub(r"[^\w\s]", " ", valor, flags=re.UNICODE)
    return re.sub(r"\s+", " ", valor).strip()


def es_saludo_inicial(texto: str) -> bool:
    """True si el mensaje es un saludo corto (p. ej. hola, buenas, hi)."""
    normalizado = _normalizar_texto_saludo(texto)
    if not normalizado:
        return False
    if normalizado in _SALUDOS_EXACTOS:
        return True
    partes = normalizado.split()
    if partes and partes[0] in _SALUDOS_INICIO and len(partes) <= 3:
        return True
    return False


def texto_presentacion_inicial(asistente: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Devuelve presentacion_inicial tal cual (conserva saltos de línea y emoji).
    Solo se recortan espacios al inicio/final del bloque completo.
    """
    if not isinstance(asistente, dict):
        return None
    crudo = asistente.get("presentacion_inicial")
    if not isinstance(crudo, str):
        return None
    if not crudo.strip():
        return None
    return crudo.strip("\n\r ")


def _mensajes_previos(
    mensajes: Optional[List[Dict[str, Any]]],
    mensaje_actual_id: Optional[int],
) -> List[Dict[str, Any]]:
    previos: List[Dict[str, Any]] = []
    for item in mensajes or []:
        if not isinstance(item, dict):
            continue
        if mensaje_actual_id is not None and item.get("id") == mensaje_actual_id:
            continue
        previos.append(item)
    return previos


def _tiene_respuesta_asistente(
    mensajes: Optional[List[Dict[str, Any]]],
    mensaje_actual_id: Optional[int] = None,
) -> bool:
    for item in _mensajes_previos(mensajes, mensaje_actual_id):
        if str(item.get("direccion") or "").strip().lower() == "saliente":
            return True
    return False


def _es_primer_mensaje_conversacion(
    mensajes: Optional[List[Dict[str, Any]]],
    mensaje_actual_id: Optional[int] = None,
) -> bool:
    return len(_mensajes_previos(mensajes, mensaje_actual_id)) == 0


def resolver_presentacion_literal(
    *,
    asistente: Optional[Dict[str, Any]],
    mensajes: Optional[List[Dict[str, Any]]],
    texto_usuario: str,
    mensaje_actual_id: Optional[int] = None,
) -> Optional[str]:
    """
    Si corresponde enviar la bienvenida literal, retorna el texto exacto.
    No usa chatbot_configuracion.mensaje_bienvenida.
    """
    presentacion = texto_presentacion_inicial(asistente)
    if not presentacion:
        return None
    if _tiene_respuesta_asistente(mensajes, mensaje_actual_id):
        return None
    if es_saludo_inicial(texto_usuario) or _es_primer_mensaje_conversacion(
        mensajes, mensaje_actual_id
    ):
        return presentacion
    return None


def _log_bienvenida_literal(
    *,
    agencia_id: int,
    config_id: Optional[int],
    conversacion_id: Optional[int],
) -> None:
    logger.info(
        "[CHATBOT-CONV] bienvenida_literal=true agencia_id=%s config_id=%s "
        "conversacion_id=%s fuente=asistente_configuracion.presentacion_inicial",
        agencia_id,
        config_id,
        conversacion_id,
    )


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

    interrupcion = await _intentar_interrupcion_informativa(
        contexto=contexto,
        conversacion_id=conversacion_id,
        mensaje_entrante_id=mensaje_entrante_id,
        texto_usuario=texto,
        canal=canal,
        token=token,
        phone_number_id=phone_number_id,
        destino=wa_id or usuario_externo_id,
        enviar_callback=enviar_callback,
        dry_run=dry_run,
    )
    if interrupcion:
        return interrupcion

    if usar_rutas_adaptativas(contexto.configuracion):
        resultado_cls = await _aplicar_clasificacion_adaptativa(
            contexto, texto_usuario=texto, dry_run=dry_run
        )
        respuesta_directa = (resultado_cls or {}).get("respuesta_directa")
        accion = ((resultado_cls or {}).get("clasificacion") or {}).get(
            "accion_propuesta"
        )
        nivel_cls = str(
            ((resultado_cls or {}).get("clasificacion") or {}).get("nivel_experiencia")
            or "desconocido"
        )
        # Guardia: adaptativa + nivel abierto nunca cae al agente libre.
        if (
            not respuesta_directa
            and nivel_cls == "desconocido"
            and accion
            not in {
                "mostrar_beneficios",
                "mostrar_requisitos",
                "mostrar_bonos",
                "mostrar_categorias",
                "responder_informacion",
                "transferir_humano",
                "enviar_solicitud",
            }
        ):
            from chatbot_conversacional_clasificacion import (
                TEXTO_ACLARACION_NIVEL,
                construir_pregunta_clasificacion,
            )

            respuesta_directa = construir_pregunta_clasificacion(
                contexto.asistente or {}
            ) or TEXTO_ACLARACION_NIVEL
            accion = "aclarar_nivel"

        if respuesta_directa:
            pendiente_guardar = None
            if accion in {"preguntar_nivel", "aclarar_nivel"}:
                pendiente_guardar = {
                    "paso_id": contexto.conversacion.get("paso_actual_id"),
                    "campo": "nivel_experiencia",
                    "texto": respuesta_directa,
                }
            return await _responder_presentacion_literal(
                contexto=contexto,
                presentacion=respuesta_directa,
                conversacion_id=conversacion_id,
                mensaje_entrante_id=mensaje_entrante_id,
                texto_usuario=texto,
                canal=canal,
                token=token,
                phone_number_id=phone_number_id,
                destino=wa_id or usuario_externo_id,
                enviar_callback=enviar_callback,
                dry_run=dry_run,
                pregunta_pendiente=pendiente_guardar,
            )
        # Duda informativa durante clasificación / inicio: responder info y
        # conservar/retomar la pregunta de experiencia si el nivel sigue abierto.
        if accion in {
            "mostrar_beneficios",
            "mostrar_requisitos",
            "mostrar_bonos",
            "mostrar_categorias",
            "responder_informacion",
        }:
            info_resp = await _responder_info_y_retomar_si_aplica(
                contexto=contexto,
                accion=accion,
                texto_usuario=texto,
                conversacion_id=conversacion_id,
                mensaje_entrante_id=mensaje_entrante_id,
                canal=canal,
                token=token,
                phone_number_id=phone_number_id,
                destino=wa_id or usuario_externo_id,
                enviar_callback=enviar_callback,
                dry_run=dry_run,
            )
            if info_resp:
                return info_resp
        if accion == "enviar_solicitud":
            if nivel_cls == "desconocido":
                from chatbot_conversacional_clasificacion import TEXTO_ACLARACION_NIVEL

                return await _responder_presentacion_literal(
                    contexto=contexto,
                    presentacion=TEXTO_ACLARACION_NIVEL,
                    conversacion_id=conversacion_id,
                    mensaje_entrante_id=mensaje_entrante_id,
                    texto_usuario=texto,
                    canal=canal,
                    token=token,
                    phone_number_id=phone_number_id,
                    destino=wa_id or usuario_externo_id,
                    enviar_callback=enviar_callback,
                    dry_run=dry_run,
                    pregunta_pendiente={
                        "paso_id": contexto.conversacion.get("paso_actual_id"),
                        "campo": "nivel_experiencia",
                        "texto": TEXTO_ACLARACION_NIVEL,
                    },
                )
            return await _responder_envio_solicitud_adaptativo(
                contexto=contexto,
                conversacion_id=conversacion_id,
                mensaje_entrante_id=mensaje_entrante_id,
                texto_usuario=texto,
                canal=canal,
                token=token,
                phone_number_id=phone_number_id,
                destino=wa_id or usuario_externo_id,
                enviar_callback=enviar_callback,
                dry_run=dry_run,
            )
        if accion == "transferir_humano":
            return await _responder_transferencia_adaptativa(
                contexto=contexto,
                conversacion_id=conversacion_id,
                mensaje_entrante_id=mensaje_entrante_id,
                texto_usuario=texto,
                canal=canal,
                token=token,
                phone_number_id=phone_number_id,
                destino=wa_id or usuario_externo_id,
                enviar_callback=enviar_callback,
                dry_run=dry_run,
            )
    else:
        presentacion = resolver_presentacion_literal(
            asistente=contexto.asistente,
            mensajes=contexto.mensajes,
            texto_usuario=texto,
            mensaje_actual_id=mensaje_entrante_id,
        )
        if presentacion:
            return await _responder_presentacion_literal(
                contexto=contexto,
                presentacion=presentacion,
                conversacion_id=conversacion_id,
                mensaje_entrante_id=mensaje_entrante_id,
                texto_usuario=texto,
                canal=canal,
                token=token,
                phone_number_id=phone_number_id,
                destino=wa_id or usuario_externo_id,
                enviar_callback=enviar_callback,
                dry_run=dry_run,
            )

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
            estado_envio="enviado" if envio.get("enviado") is True else "error",
            error_detalle=envio.get("error"),
            mensaje_externo_id=envio.get("mensaje_externo_id"),
            procesado_por_ia=True,
            modelo_ia=preparado.modelo,
            prompt_version=preparado.prompt_version,
            tokens_entrada=ejecucion.get("tokens_entrada"),
            tokens_salida=ejecucion.get("tokens_salida"),
            metadata={
                "modo": contexto.modo,
                "herramientas": [accion.get("herramienta") for accion in ctxh.acciones],
                "enlaces": [enlace.get("codigo") for enlace in enlaces],
                "respuesta_enviada": bool(envio.get("enviado") is True),
                "status_code": envio.get("status_code"),
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
        "respuesta_enviada": bool(envio.get("enviado") is True) or dry_run,
        "requiere_reintento": not (bool(envio.get("enviado") is True) or dry_run),
        "mensaje_externo_id": envio.get("mensaje_externo_id"),
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
    mensaje = str(texto or "").strip()
    if not mensaje:
        logger.info(
            "[SIMULADOR_CONVERSACIONAL] agencia_id=%s chatbot_configuracion_id=%s "
            "resultado=error codigo=mensaje_vacio",
            agencia_id,
            chatbot_configuracion_id,
        )
        return _resultado_no_usado("mensaje_vacio")

    if not openai_configurado():
        logger.info(
            "[SIMULADOR_CONVERSACIONAL] agencia_id=%s chatbot_configuracion_id=%s "
            "resultado=error codigo=openai_no_configurado",
            agencia_id,
            chatbot_configuracion_id,
        )
        return _resultado_no_usado("openai_no_configurado")

    historial_norm = _normalizar_historial_simulacion(historial)

    campania: Optional[Dict[str, Any]] = None
    if campania_id is not None:
        campania = await _db(
            "obtener_campania", agencia_id, int(campania_id), default=None
        )
        if not campania:
            return _resultado_no_usado("campania_no_encontrada")

    # En simulación se permite probar aunque el asistente aún no esté publicado.
    asistente = await _db(
        "obtener_asistente_configuracion",
        agencia_id,
        chatbot_configuracion_id,
        default=None,
    )
    if not asistente:
        return _resultado_no_usado("asistente_inexistente")
    asistente_sim = dict(asistente)
    asistente_sim["activo"] = True

    conversacion: Optional[Dict[str, Any]] = None
    if conversacion_id:
        conversacion = await _db(
            "obtener_conversacion", agencia_id, conversacion_id, default=None
        )
        # En simulación no se reutilizan conversaciones reales salvo dry_run
        # explícito del panel; si aparece una real, se ignora para no mutarla.
        if conversacion and not bool(conversacion.get("_simulacion")):
            conversacion = None

    if conversacion is None:
        conversacion = {
            "id": None,
            "agencia_id": agencia_id,
            "chatbot_configuracion_id": chatbot_configuracion_id,
            "aspirante_id": None,
            "campania_id": campania_id,
            "canal": canal,
            "estado": "abierta",
            "estado_actual": "inicio",
            "modo_humano": False,
            "ia_habilitada": True,
            "_simulacion": True,
        }

    try:
        contexto = await asyncio.to_thread(
            construir_contexto,
            agencia_id=agencia_id,
            conversacion=conversacion,
            asistente=asistente_sim,
            campania=campania,
            dry_run=True,
        )

    except AsistenteInactivo as exc:
        logger.info(
            "[SIMULADOR_CONVERSACIONAL] agencia_id=%s chatbot_configuracion_id=%s "
            "resultado=error codigo=asistente_inactivo",
            agencia_id,
            chatbot_configuracion_id,
        )
        return _resultado_no_usado("asistente_inactivo", detalle=str(exc))

    if modo and modo in MODOS_VALIDOS:
        contexto.modo = modo

    if historial_norm:
        contexto.mensajes = historial_norm[-LIMITE_MENSAJES:]

    # Forzar dry_run: herramientas no escriben ni envían por canales.
    contexto.dry_run = True

    presentacion = resolver_presentacion_literal(
        asistente=contexto.asistente,
        mensajes=contexto.mensajes,
        texto_usuario=mensaje,
        mensaje_actual_id=None,
    )
    if presentacion:
        _log_bienvenida_literal(
            agencia_id=agencia_id,
            config_id=chatbot_configuracion_id or contexto.chatbot_configuracion_id,
            conversacion_id=None,
        )
        return {
            "usado": True,
            "simulacion": True,
            "bienvenida_literal": True,
            "conversacion_id": None,
            "respuesta": presentacion,
            "modo": contexto.modo,
            "modelo_ia": None,
            "modelo": None,
            "tokens_entrada": 0,
            "tokens_salida": 0,
            "acciones": [],
            "herramientas_usadas": [],
            "enlaces": [],
            "escalado": False,
            "requiere_humano": False,
            "cerrada": False,
            "estado_actual": contexto.conversacion.get("estado_actual"),
            "uso": {"modelo": None, "tokens_entrada": 0, "tokens_salida": 0},
        }

    preparado = crear_agente(contexto, dry_run=True)
    entrada = _construir_entrada(contexto, mensaje, None)

    try:
        ejecucion = await _ejecutar_agente(preparado, entrada)

    except Exception as exc:  # noqa: BLE001
        logger.warning("chatbot_conversacional: simulación falló: %s", exc)
        return {
            "usado": False,
            "simulacion": True,
            "motivo": "openai_fallido",
            "respuesta": _texto_respaldo(contexto),
            "error": str(exc),
            "modo": contexto.modo,
            "modelo_ia": preparado.modelo,
            "acciones": [],
            "herramientas_usadas": [],
            "uso": {"modelo": preparado.modelo, "tokens_entrada": 0, "tokens_salida": 0},
        }

    ctxh = preparado.contexto_herramientas
    acciones = list(ctxh.acciones or [])
    herramientas = []
    for accion in acciones:
        if isinstance(accion, dict):
            nombre = accion.get("herramienta") or accion.get("nombre") or accion.get("tool")
            if nombre:
                herramientas.append(str(nombre))
        elif isinstance(accion, str):
            herramientas.append(accion)

    respuesta = str(ejecucion.get("texto") or "").strip() or _texto_respaldo(contexto)

    return {
        "usado": True,
        "simulacion": True,
        "conversacion_id": None,
        "respuesta": respuesta,
        "modo": contexto.modo,
        "modelo_ia": preparado.modelo,
        "modelo": preparado.modelo,
        "tokens_entrada": ejecucion.get("tokens_entrada"),
        "tokens_salida": ejecucion.get("tokens_salida"),
        "acciones": acciones,
        "herramientas_usadas": herramientas,
        "enlaces": list(ctxh.enlaces or []),
        "escalado": bool(ctxh.escalamiento),
        "requiere_humano": bool(ctxh.escalamiento),
        "cerrada": bool(ctxh.cierre),
        "estado_actual": contexto.conversacion.get("estado_actual"),
        "uso": {
            "modelo": preparado.modelo,
            "tokens_entrada": ejecucion.get("tokens_entrada") or 0,
            "tokens_salida": ejecucion.get("tokens_salida") or 0,
        },
    }


def _normalizar_historial_simulacion(
    historial: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Acepta {direccion,texto} o {rol,contenido} y deja el formato del runtime."""
    out: List[Dict[str, Any]] = []
    for idx, item in enumerate(historial or []):
        if not isinstance(item, dict):
            continue
        texto = item.get("texto") or item.get("contenido") or item.get("content")
        if not texto:
            continue
        direccion = str(item.get("direccion") or "").strip().lower()
        if direccion not in {"entrante", "saliente"}:
            rol = str(item.get("rol") or item.get("role") or "").strip().lower()
            if rol in {"usuario", "user"}:
                direccion = "entrante"
            elif rol in {"asistente", "assistant"}:
                direccion = "saliente"
            else:
                continue
        out.append(
            {
                "id": idx + 1,
                "direccion": direccion,
                "texto": str(texto),
            }
        )
    return out[-LIMITE_MENSAJES:]


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


INTERRUPCIONES_INFORMATIVAS = frozenset(
    {"requisitos", "beneficios", "bonos", "agencia", "proceso", "faq"}
)


def _contexto_conversacion_dict(conversacion: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    conv = conversacion or {}
    ctx = conv.get("contexto") or {}
    if isinstance(ctx, str):
        try:
            ctx = json.loads(ctx)
        except (TypeError, ValueError, json.JSONDecodeError):
            ctx = {}
    return dict(ctx) if isinstance(ctx, dict) else {}


def _leer_pregunta_pendiente(conversacion: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    pendiente = _contexto_conversacion_dict(conversacion).get("pregunta_pendiente")
    return pendiente if isinstance(pendiente, dict) else None


async def _guardar_pregunta_pendiente(
    contexto: ConversationalContext,
    pendiente: Dict[str, Any],
    *,
    dry_run: bool,
) -> None:
    ctx = _contexto_conversacion_dict(contexto.conversacion)
    ctx["pregunta_pendiente"] = pendiente
    contexto.conversacion["contexto"] = ctx
    if dry_run or not contexto.conversacion_id:
        return
    await _db(
        "actualizar_conversacion",
        contexto.agencia_id,
        contexto.conversacion_id,
        {"contexto": ctx},
    )


async def _limpiar_pregunta_pendiente(
    contexto: ConversationalContext,
    *,
    dry_run: bool,
) -> None:
    ctx = _contexto_conversacion_dict(contexto.conversacion)
    if "pregunta_pendiente" not in ctx:
        return
    ctx.pop("pregunta_pendiente", None)
    contexto.conversacion["contexto"] = ctx
    if dry_run or not contexto.conversacion_id:
        return
    await _db(
        "actualizar_conversacion",
        contexto.agencia_id,
        contexto.conversacion_id,
        {"contexto": ctx},
    )


def _detectar_intencion_interrupcion_informativa(texto: str) -> Optional[str]:
    """Detecta preguntas informativas durante un paso con pregunta pendiente."""
    intencion, _conf = inferir_intencion(texto)
    if intencion in {"requisitos", "beneficios", "bonos"}:
        return intencion
    if intencion == "informacion":
        return "faq"

    from service_chatbot_informativo import _normalizar as normalizar_informativo

    n = normalizar_informativo(texto)
    if any(k in n for k in ("agencia", "funcionamiento", "como funciona", "funciona")):
        return "agencia"
    if any(k in n for k in ("proceso", "continuar", "solicitud", "unirme", "incorpor")):
        return "proceso"
    return None


def _construir_texto_informativo_inteligente(
    contexto: ConversationalContext,
    intencion: str,
    texto_consulta: str,
) -> str:
    from service_chatbot_informativo import (
        construir_respuesta_por_intencion_informativa,
        presentacion_desde_asistente,
    )
    import database_chatbot_conversacional as db_conv

    presentacion = presentacion_desde_asistente(contexto.asistente)
    texto, _req = construir_respuesta_por_intencion_informativa(
        intencion,
        agencia_id=contexto.agencia_id,
        chatbot_configuracion_id=int(contexto.chatbot_configuracion_id or 0),
        presentacion=presentacion,
        texto_consulta=texto_consulta,
        db_conv=db_conv,
    )
    return str(texto or "").strip()


async def _responder_info_y_retomar_si_aplica(
    *,
    contexto: ConversationalContext,
    accion: str,
    texto_usuario: str,
    conversacion_id: Optional[int],
    mensaje_entrante_id: Optional[int],
    canal: str,
    token: Optional[str],
    phone_number_id: Optional[str],
    destino: Optional[str],
    enviar_callback: Optional[EnviarCallback],
    dry_run: bool,
) -> Optional[Dict[str, Any]]:
    """
    Responde una duda informativa y, si el nivel sigue abierto, retoma la
    pregunta de experiencia sin perder el flujo.
    """
    mapa = {
        "mostrar_beneficios": "beneficios",
        "mostrar_requisitos": "requisitos",
        "mostrar_bonos": "bonos",
        "mostrar_categorias": "agencia",
        "responder_informacion": "faq",
    }
    intencion = mapa.get(accion)
    if not intencion:
        return None

    info = _construir_texto_informativo_inteligente(
        contexto, intencion, texto_usuario
    )
    if not info:
        return None

    asistente = contexto.asistente or {}
    nivel = str(
        (contexto.conversacion or {}).get("nivel_experiencia")
        or (contexto.aspirante or {}).get("nivel_experiencia")
        or "desconocido"
    ).lower()
    pendiente_existente = _leer_pregunta_pendiente(contexto.conversacion)
    pregunta = None
    pendiente_guardar = None

    if nivel in {"", "desconocido", "none", "null"}:
        pregunta = str(
            (pendiente_existente or {}).get("texto")
            or asistente.get("pregunta_clasificacion_nivel")
            or asistente.get("presentacion_inicial")
            or "¿Ya has realizado transmisiones LIVE?"
        ).strip()
        pendiente_guardar = {
            "paso_id": (contexto.conversacion or {}).get("paso_actual_id"),
            "campo": "nivel_experiencia",
            "texto": pregunta,
        }

    if pregunta and pregunta not in info:
        if pregunta.startswith("¿"):
            respuesta = f"{info}\n\nPara orientarte mejor, {pregunta}"
        else:
            respuesta = f"{info}\n\n{pregunta}"
    else:
        respuesta = info

    envio = await _enviar_respuesta(
        canal=canal,
        texto=respuesta,
        enlaces=[],
        token=token,
        phone_number_id=phone_number_id,
        destino=destino,
        enviar_callback=enviar_callback,
        dry_run=dry_run,
    )

    mensaje_saliente = None
    if respuesta and not dry_run and conversacion_id:
        mensaje_saliente = await _db(
            "insertar_mensaje",
            contexto.agencia_id,
            conversacion_id,
            canal=canal,
            direccion="saliente",
            remitente_tipo="chatbot",
            tipo_mensaje="texto",
            texto=respuesta,
            estado_envio="enviado" if envio.get("enviado") else "error",
            error_detalle=envio.get("error"),
            procesado_por_ia=False,
            metadata={
                "info_con_retoma": True,
                "intencion": intencion,
                "modo_humano": False,
            },
            default=None,
        )
        mensaje_saliente = _normalizar_fila_mensaje(mensaje_saliente)

    if pendiente_guardar:
        await _guardar_pregunta_pendiente(
            contexto, pendiente_guardar, dry_run=dry_run
        )

    await _actualizar_cierre_de_turno(
        contexto,
        respuesta=respuesta,
        mensaje_usuario=texto_usuario,
        acciones=[{"tipo": "info_y_retoma", "intencion": intencion}],
        escalado=False,
        cerrada=False,
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
        "acciones": [{"tipo": "info_y_retoma", "intencion": intencion}],
        "enlaces": [],
        "escalado": False,
        "cerrada": False,
        "enviado": envio.get("enviado"),
        "error": envio.get("error"),
        "pregunta_pendiente": pendiente_guardar,
        "tipo_chatbot": "inteligente",
        "modo_humano": False,
    }


async def _intentar_interrupcion_informativa(
    *,
    contexto: ConversationalContext,
    conversacion_id: Optional[int],
    mensaje_entrante_id: Optional[int],
    texto_usuario: str,
    canal: str,
    token: Optional[str],
    phone_number_id: Optional[str],
    destino: Optional[str],
    enviar_callback: Optional[EnviarCallback],
    dry_run: bool,
) -> Optional[Dict[str, Any]]:
    """
    Si hay pregunta o paso pendiente y el usuario pide info, responde primero
    la duda y retoma el punto pendiente una sola vez.
    """
    pendiente = _leer_pregunta_pendiente(contexto.conversacion)
    if not pendiente:
        paso = contexto.paso or {}
        texto_paso = str(
            paso.get("mensaje_usuario")
            or paso.get("descripcion")
            or paso.get("nombre")
            or ""
        ).strip()
        if (contexto.conversacion or {}).get("paso_actual_id") and texto_paso:
            pendiente = {
                "paso_id": (contexto.conversacion or {}).get("paso_actual_id"),
                "campo": paso.get("codigo") or "paso_actual",
                "texto": texto_paso,
            }
        else:
            return None

    intencion = _detectar_intencion_interrupcion_informativa(texto_usuario)
    if not intencion or intencion not in INTERRUPCIONES_INFORMATIVAS:
        return None

    info = _construir_texto_informativo_inteligente(
        contexto, intencion, texto_usuario
    )
    if not info:
        return None

    pregunta = str(pendiente.get("texto") or "").strip()
    if pregunta and pregunta not in info:
        if pregunta.startswith("¿") or pregunta.endswith("?"):
            respuesta = f"{info}\n\nPara continuar, {pregunta}"
        else:
            respuesta = f"{info}\n\nPara continuar: {pregunta}"
    else:
        respuesta = info

    envio = await _enviar_respuesta(
        canal=canal,
        texto=respuesta,
        enlaces=[],
        token=token,
        phone_number_id=phone_number_id,
        destino=destino,
        enviar_callback=enviar_callback,
        dry_run=dry_run,
    )

    mensaje_saliente = None
    if respuesta and not dry_run and conversacion_id:
        mensaje_saliente = await _db(
            "insertar_mensaje",
            contexto.agencia_id,
            conversacion_id,
            canal=canal,
            direccion="saliente",
            remitente_tipo="chatbot",
            tipo_mensaje="texto",
            texto=respuesta,
            estado_envio="enviado" if envio.get("enviado") else "error",
            error_detalle=envio.get("error"),
            procesado_por_ia=False,
            metadata={
                "interrupcion_informativa": True,
                "intencion": intencion,
                "pregunta_pendiente": pendiente,
                "modo_humano": False,
            },
            default=None,
        )
        mensaje_saliente = _normalizar_fila_mensaje(mensaje_saliente)

    await _guardar_pregunta_pendiente(contexto, pendiente, dry_run=dry_run)

    await _actualizar_cierre_de_turno(
        contexto,
        respuesta=respuesta,
        mensaje_usuario=texto_usuario,
        acciones=[{"tipo": "interrupcion_informativa", "intencion": intencion}],
        escalado=False,
        cerrada=False,
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
        "modelo": None,
        "acciones": [{"tipo": "interrupcion_informativa", "intencion": intencion}],
        "enlaces": [],
        "escalado": False,
        "cerrada": False,
        "enviado": envio.get("enviado"),
        "error": envio.get("error"),
        "modo_humano": False,
        "pregunta_pendiente": pendiente,
        "tipo_chatbot": "inteligente",
        "sdk": None,
    }


async def _aplicar_clasificacion_adaptativa(
    contexto: ConversationalContext,
    *,
    texto_usuario: str,
    dry_run: bool,
) -> Dict[str, Any]:
    """Clasifica, persiste estado y opcionalmente responde sin modelo."""
    resultado = clasificar_mensaje(
        texto=texto_usuario,
        asistente=contexto.asistente or {},
        conversacion=contexto.conversacion or {},
        aspirante=contexto.aspirante,
    )

    # Reflejar en memoria para el resto del turno.
    contexto.conversacion.update(resultado.campos_conversacion)
    if contexto.aspirante is not None and resultado.campos_aspirante:
        contexto.aspirante.update(
            {k: v for k, v in resultado.campos_aspirante.items() if v is not None}
        )

    if dry_run or not contexto.conversacion_id:
        return {
            "clasificacion": resultado.clasificacion.model_dump(),
            "respuesta_directa": resultado.texto_respuesta_directa,
        }

    pendiente = _leer_pregunta_pendiente(contexto.conversacion)
    if pendiente and pendiente.get("campo") == "nivel_experiencia":
        if (
            resultado.clasificacion.nivel_declarado_explicitamente
            or (
                resultado.clasificacion.nivel_experiencia != "desconocido"
                and float(resultado.clasificacion.confianza_nivel or 0) >= 0.75
            )
        ):
            await _limpiar_pregunta_pendiente(contexto, dry_run=dry_run)

    if resultado.campos_conversacion:
        await _db(
            "actualizar_conversacion",
            contexto.agencia_id,
            contexto.conversacion_id,
            resultado.campos_conversacion,
        )

    aspirante_id = contexto.aspirante_id
    if resultado.persistir_nivel_estable and aspirante_id and resultado.campos_aspirante:
        await _db(
            "actualizar_nivel_aspirante_estable",
            int(aspirante_id),
            contexto.agencia_id,
            nivel_experiencia=resultado.campos_aspirante.get("nivel_experiencia"),
            nivel_experiencia_fuente=resultado.campos_aspirante.get(
                "nivel_experiencia_fuente"
            ),
            nivel_experiencia_confianza=resultado.campos_aspirante.get(
                "nivel_experiencia_confianza"
            ),
            nivel_experiencia_confirmado_at=resultado.campos_aspirante.get(
                "nivel_experiencia_confirmado_at"
            ),
        )

    if resultado.registrar_evento:
        await _db(
            "registrar_evento",
            contexto.agencia_id,
            contexto.conversacion_id,
            tipo_evento="clasificacion",
            nombre_evento="clasificacion_adaptativa",
            origen="backend",
            exitoso=True,
            detalle=resultado.detalle_evento,
        )

    if getattr(resultado, "seleccionar_flujo", False):
        await _seleccionar_flujo_por_nivel_confirmado(
            contexto,
            nivel=resultado.clasificacion.nivel_experiencia,
            dry_run=dry_run,
        )

    return {
        "clasificacion": resultado.clasificacion.model_dump(),
        "respuesta_directa": resultado.texto_respuesta_directa,
    }


async def _seleccionar_flujo_por_nivel_confirmado(
    contexto: ConversationalContext,
    *,
    nivel: str,
    dry_run: bool,
) -> None:
    """
    Tras confirmar principiante/experimentado, elige flujo conversion
    con nivel_objetivo (fallback general). No elige prueba LIVE por keyword.
    """
    nivel_n = str(nivel or "").strip().lower()
    if nivel_n not in {"principiante", "experimentado"}:
        return
    if dry_run or not contexto.conversacion_id or not contexto.chatbot_configuracion_id:
        return

    flujo = await _db(
        "obtener_flujo_por_nivel",
        contexto.agencia_id,
        contexto.chatbot_configuracion_id,
        nivel=nivel_n,
        tipo_flujo="conversion",
        default=None,
    )
    if not flujo:
        return

    flujo_id = flujo.get("id")
    pasos = (
        await _db(
            "listar_flujo_pasos",
            contexto.agencia_id,
            flujo_id,
            solo_activos=True,
            default=[],
        )
        or []
    )
    pasos_ord = sorted(
        [p for p in pasos if p],
        key=lambda p: (int(p.get("orden") or 0), int(p.get("id") or 0)),
    )
    primer_paso = pasos_ord[0] if pasos_ord else None
    campos = {
        "flujo_id": flujo_id,
        "paso_actual_id": (primer_paso or {}).get("id"),
        "estado_actual": "flujo_seleccionado",
    }
    await _db(
        "actualizar_conversacion",
        contexto.agencia_id,
        contexto.conversacion_id,
        campos,
    )
    contexto.conversacion.update(campos)
    contexto.flujo = flujo
    contexto.paso = primer_paso
    logger.info(
        "[CLASIFICACION] flujo_seleccionado conversacion_id=%s nivel=%s "
        "flujo_id=%s paso_id=%s nivel_objetivo=%s",
        contexto.conversacion_id,
        nivel_n,
        flujo_id,
        campos.get("paso_actual_id"),
        flujo.get("nivel_objetivo"),
    )


async def _responder_presentacion_literal(
    *,
    contexto: ConversationalContext,
    presentacion: str,
    conversacion_id: Optional[int],
    mensaje_entrante_id: Optional[int],
    texto_usuario: str,
    canal: str,
    token: Optional[str],
    phone_number_id: Optional[str],
    destino: Optional[str],
    enviar_callback: Optional[EnviarCallback],
    dry_run: bool,
    pregunta_pendiente: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Envía presentacion_inicial sin modelo ni herramientas.
    No avanza pasos irreversibles del flujo.
    """
    _log_bienvenida_literal(
        agencia_id=contexto.agencia_id,
        config_id=contexto.chatbot_configuracion_id,
        conversacion_id=conversacion_id,
    )

    envio = await _enviar_respuesta(
        canal=canal,
        texto=presentacion,
        enlaces=[],
        token=token,
        phone_number_id=phone_number_id,
        destino=destino,
        enviar_callback=enviar_callback,
        dry_run=dry_run,
    )

    mensaje_saliente = None
    if presentacion and not dry_run and conversacion_id:
        mensaje_saliente = await _db(
            "insertar_mensaje",
            contexto.agencia_id,
            conversacion_id,
            canal=canal,
            direccion="saliente",
            remitente_tipo="chatbot",
            tipo_mensaje="texto",
            texto=presentacion,
            estado_envio="enviado" if envio.get("enviado") else "error",
            error_detalle=envio.get("error"),
            procesado_por_ia=False,
            metadata={
                "bienvenida_literal": True,
                "fuente": "asistente_configuracion.presentacion_inicial",
                "modo": contexto.modo,
            },
            default=None,
        )
        mensaje_saliente = _normalizar_fila_mensaje(mensaje_saliente)

    if pregunta_pendiente:
        await _guardar_pregunta_pendiente(
            contexto, pregunta_pendiente, dry_run=dry_run
        )

    await _actualizar_cierre_de_turno(
        contexto,
        respuesta=presentacion,
        mensaje_usuario=texto_usuario,
        acciones=[],
        escalado=False,
        cerrada=False,
        dry_run=dry_run,
    )

    return {
        "usado": True,
        "motivo": None,
        "bienvenida_literal": True,
        "conversacion_id": conversacion_id,
        "mensaje_entrante_id": mensaje_entrante_id,
        "mensaje_saliente_id": (_normalizar_fila_mensaje(mensaje_saliente) or {}).get("id"),
        "respuesta": presentacion,
        "modo": contexto.modo,
        "modelo": None,
        "tokens_entrada": 0,
        "tokens_salida": 0,
        "acciones": [],
        "enlaces": [],
        "escalado": False,
        "cerrada": False,
        "enviado": envio.get("enviado"),
        "error": envio.get("error"),
        "sdk": None,
    }


def _codigo_recurso_solicitud(contexto: ConversationalContext) -> str:
    paso = contexto.paso or {}
    cfg = paso.get("configuracion") if isinstance(paso.get("configuracion"), dict) else {}
    codigo = str(cfg.get("codigo_recurso") or "").strip()
    if codigo:
        return codigo
    for recurso in contexto.recursos or []:
        tipo = str(recurso.get("tipo") or "").lower()
        cod = str(recurso.get("codigo") or "").strip()
        if tipo == "solicitud" and cod:
            return cod
        if cod.lower() in {"solicitud_principal", "solicitud", "enlace_solicitud"}:
            return cod
    return "solicitud_principal"


async def _responder_envio_solicitud_adaptativo(
    *,
    contexto: ConversationalContext,
    conversacion_id: Optional[int],
    mensaje_entrante_id: Optional[int],
    texto_usuario: str,
    canal: str,
    token: Optional[str],
    phone_number_id: Optional[str],
    destino: Optional[str],
    enviar_callback: Optional[EnviarCallback],
    dry_run: bool,
) -> Dict[str, Any]:
    """Envía el enlace de solicitud con el servicio real; nunca activa modo_humano."""
    ctxh = ContextoHerramientas(
        agencia_id=contexto.agencia_id,
        conversacion_id=conversacion_id,
        contexto=contexto,
        dry_run=dry_run,
        mensaje_id=mensaje_entrante_id,
    )
    codigo = _codigo_recurso_solicitud(contexto)
    resultado = await asyncio.to_thread(
        preparar_envio_enlace_autorizado,
        ctxh,
        codigo,
        "solicitud_adaptativa",
    )
    enlaces = list(ctxh.enlaces)
    if resultado.get("ok") and enlaces:
        texto = (
            "Te envío el enlace para continuar tu solicitud. "
            "Cuando lo completes, avísame si tienes alguna duda."
        )
    else:
        texto = str(
            resultado.get("mensaje_usuario")
            or (
                "No pude generar el enlace en este momento. Dejé la solicitud "
                "pendiente para que el equipo la revise. Mientras tanto, puedo "
                "seguir respondiendo tus preguntas sobre el proceso."
            )
        )

    envio = await _enviar_respuesta(
        canal=canal,
        texto=texto,
        enlaces=enlaces,
        token=token,
        phone_number_id=phone_number_id,
        destino=destino,
        enviar_callback=enviar_callback,
        dry_run=dry_run,
    )

    mensaje_saliente = None
    if texto and not dry_run and conversacion_id:
        mensaje_saliente = await _db(
            "insertar_mensaje",
            contexto.agencia_id,
            conversacion_id,
            canal=canal,
            direccion="saliente",
            remitente_tipo="chatbot",
            tipo_mensaje="texto",
            texto=texto,
            estado_envio="enviado" if envio.get("enviado") else "error",
            error_detalle=envio.get("error"),
            procesado_por_ia=False,
            metadata={
                "accion_adaptativa": "enviar_solicitud",
                "resultado_enlace": "enviado" if resultado.get("ok") else "error",
                "modo_humano": False,
                "requiere_asesor": bool(resultado.get("requiere_asesor")),
            },
            default=None,
        )
        mensaje_saliente = _normalizar_fila_mensaje(mensaje_saliente)

    await _actualizar_cierre_de_turno(
        contexto,
        respuesta=texto,
        mensaje_usuario=texto_usuario,
        acciones=ctxh.acciones,
        escalado=False,
        cerrada=False,
        dry_run=dry_run,
    )

    return {
        "usado": True,
        "motivo": None,
        "conversacion_id": conversacion_id,
        "mensaje_entrante_id": mensaje_entrante_id,
        "mensaje_saliente_id": (_normalizar_fila_mensaje(mensaje_saliente) or {}).get("id"),
        "respuesta": texto,
        "modo": contexto.modo,
        "modelo": None,
        "acciones": ctxh.acciones,
        "enlaces": enlaces,
        "escalado": False,
        "cerrada": False,
        "enviado": envio.get("enviado"),
        "error": envio.get("error"),
        "requiere_asesor": bool(resultado.get("requiere_asesor")),
        "modo_humano": False,
        "sdk": None,
    }


async def _responder_transferencia_adaptativa(
    *,
    contexto: ConversationalContext,
    conversacion_id: Optional[int],
    mensaje_entrante_id: Optional[int],
    texto_usuario: str,
    canal: str,
    token: Optional[str],
    phone_number_id: Optional[str],
    destino: Optional[str],
    enviar_callback: Optional[EnviarCallback],
    dry_run: bool,
) -> Dict[str, Any]:
    """Solicitud de asesor: marca requiere_asesor, NO activa modo_humano."""
    motivo = "solicitud_explicita_asesor"
    texto = (
        "Dejé tu solicitud pendiente para que un asesor te contacte. "
        "Mientras tanto puedo seguir respondiendo tus preguntas."
    )
    if not dry_run and conversacion_id:
        aspirante_id = contexto.aspirante_id
        if aspirante_id:
            try:
                import database_chatbot_captacion as db_cap

                await asyncio.to_thread(
                    db_cap.actualizar_aspirante_admin,
                    contexto.agencia_id,
                    int(aspirante_id),
                    requiere_asesor=True,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[CHATBOT-TRANSFERENCIA] no se pudo marcar requiere_asesor: %s",
                    exc,
                )
        await _db(
            "registrar_evento",
            contexto.agencia_id,
            conversacion_id,
            tipo_evento="escalamiento",
            nombre_evento="solicitud_asesor_adaptativa",
            origen="backend",
            estado_anterior=contexto.conversacion.get("estado"),
            estado_nuevo=contexto.conversacion.get("estado"),
            detalle={
                "requiere_asesor": True,
                "transferencia_solicitada": True,
                "modo_humano": False,
                "motivo_transferencia": motivo,
                "origen_activacion": "clasificacion_adaptativa",
            },
        )
        logger.info(
            "[CHATBOT-TRANSFERENCIA] aspirante_id=%s conversacion_id=%s "
            "modo_humano=false requiere_asesor=true transferencia_solicitada=true "
            "origen=clasificacion_adaptativa",
            contexto.aspirante_id,
            conversacion_id,
        )

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

    mensaje_saliente = None
    if texto and not dry_run and conversacion_id:
        mensaje_saliente = await _db(
            "insertar_mensaje",
            contexto.agencia_id,
            conversacion_id,
            canal=canal,
            direccion="saliente",
            remitente_tipo="chatbot",
            tipo_mensaje="texto",
            texto=texto,
            estado_envio="enviado" if envio.get("enviado") else "error",
            error_detalle=envio.get("error"),
            procesado_por_ia=False,
            metadata={
                "accion_adaptativa": "solicitar_asesor",
                "modo_humano": False,
                "requiere_asesor": True,
                "transferencia_solicitada": True,
            },
            default=None,
        )
        mensaje_saliente = _normalizar_fila_mensaje(mensaje_saliente)

    await _actualizar_cierre_de_turno(
        contexto,
        respuesta=texto,
        mensaje_usuario=texto_usuario,
        acciones=[],
        escalado=False,
        cerrada=False,
        dry_run=dry_run,
    )

    return {
        "usado": True,
        "motivo": None,
        "conversacion_id": conversacion_id,
        "mensaje_entrante_id": mensaje_entrante_id,
        "mensaje_saliente_id": (_normalizar_fila_mensaje(mensaje_saliente) or {}).get("id"),
        "respuesta": texto,
        "modo": contexto.modo,
        "modelo": None,
        "acciones": [],
        "enlaces": [],
        "escalado": False,
        "cerrada": False,
        "enviado": envio.get("enviado"),
        "error": envio.get("error"),
        "requiere_asesor": True,
        "modo_humano": False,
        "sdk": None,
    }


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
        return {
            "enviado": True,
            "motivo": "simulacion",
            "dry_run": True,
            "mensaje_externo_id": None,
            "status_code": None,
            "requiere_reintento": False,
        }

    if not texto:
        return {
            "enviado": False,
            "motivo": "respuesta_vacia",
            "requiere_reintento": False,
        }

    partes = [texto]
    for enlace in enlaces:
        etiqueta = enlace.get("nombre") or enlace.get("codigo") or "Enlace"
        partes.append(f"{etiqueta}: {enlace['url']}")

    from chatbot_envio_whatsapp import normalizar_resultado_envio

    ultimo: Dict[str, Any] = {"enviado": False}
    if enviar_callback is not None:
        try:
            for parte in partes:
                resultado = await _quizas_await(enviar_callback(parte))
                ultimo = normalizar_resultado_envio(resultado)
                if not ultimo.get("enviado"):
                    return ultimo
            return ultimo

        except Exception as exc:  # noqa: BLE001
            logger.error("chatbot_conversacional: callback de envío falló: %s", exc)
            return {
                "enviado": False,
                "error": str(exc)[:400],
                "requiere_reintento": True,
            }

    if canal == CANAL_WHATSAPP:
        return await _enviar_whatsapp(partes, token, phone_number_id, destino)

    if canal == CANAL_INSTAGRAM:
        return await _enviar_instagram(partes, destino)

    return {"enviado": False, "motivo": f"canal_sin_adaptador:{canal}", "requiere_reintento": True}


async def _enviar_whatsapp(
    partes: List[str],
    token: Optional[str],
    phone_number_id: Optional[str],
    destino: Optional[str],
) -> Dict[str, Any]:
    if not token or not phone_number_id or not destino:
        return {
            "enviado": False,
            "motivo": "credenciales_whatsapp_incompletas",
            "requiere_reintento": True,
        }

    from chatbot_envio_whatsapp import enviar_whatsapp_texto_meta

    ultimo: Dict[str, Any] = {"enviado": False}
    for parte in partes:
        ultimo = await enviar_whatsapp_texto_meta(
            token=token,
            phone_number_id=phone_number_id,
            destino=destino,
            texto=parte,
        )
        if not ultimo.get("enviado"):
            return ultimo
    return ultimo


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
                    "motivo_escalamiento": "fallos_consecutivos_ia",
                },
            )
            # No activar modo_humano por error del modelo: solo requiere_asesor.
            aspirante_id = contexto.aspirante_id
            if aspirante_id:
                try:
                    import database_chatbot_captacion as db_cap

                    await asyncio.to_thread(
                        db_cap.actualizar_aspirante_admin,
                        contexto.agencia_id,
                        int(aspirante_id),
                        requiere_asesor=True,
                    )
                except Exception:
                    pass
            await _db(
                "registrar_evento",
                contexto.agencia_id,
                conversacion_id,
                tipo_evento="escalamiento",
                nombre_evento="requiere_asesor_por_errores_ia",
                origen="backend",
                estado_anterior=contexto.conversacion.get("estado"),
                estado_nuevo=contexto.conversacion.get("estado"),
                detalle={
                    "errores_recientes": errores_recientes,
                    "requiere_asesor": True,
                    "modo_humano": False,
                },
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
    "es_saludo_inicial",
    "feature_enabled",
    "procesar_media_como_evidencia",
    "procesar_mensaje_conversacional",
    "resolver_motor_conversacional",
    "resolver_presentacion_literal",
    "simular_mensaje",
    "texto_presentacion_inicial",
]
