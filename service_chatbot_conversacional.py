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

    # PRIORIDAD: extraer hechos y actualizar perfil ANTES de decidir acciones.
    from chatbot_conversacional_perfil import (
        actualizar_perfil_desde_mensaje,
        puede_ejecutar_accion,
        mensaje_bloqueo_para_usuario,
        leer_perfil,
    )

    actualizacion = actualizar_perfil_desde_mensaje(
        conversacion=contexto.conversacion,
        aspirante=contexto.aspirante,
        texto=texto or "",
        requisitos=contexto.requisitos,
    )
    if contexto.aspirante is not None and actualizacion.get("campos_aspirante"):
        contexto.aspirante.update(actualizacion["campos_aspirante"])
    if not dry_run and conversacion_id:
        campos_conv = actualizacion.get("campos_conversacion") or {}
        if campos_conv:
            await _db(
                "actualizar_conversacion",
                agencia_id,
                conversacion_id,
                campos_conv,
            )
        aspirante_id_act = contexto.aspirante_id
        if aspirante_id_act and actualizacion.get("campos_aspirante"):
            await _db(
                "actualizar_datos_explicitos_aspirante",
                agencia_id,
                int(aspirante_id_act),
                actualizacion["campos_aspirante"],
                default=None,
            )

    perfil_act = actualizacion.get("perfil") or leer_perfil(
        contexto.conversacion, contexto.aspirante
    )

    # Orquestador backend: decide ANTES del agente.
    from chatbot_conversacional_orquestador import resolver_turno_inteligente
    from chatbot_conversacional_clasificacion import usar_rutas_adaptativas as _usar_rutas

    nivel_actual = str(
        perfil_act.get("nivel_experiencia")
        or (contexto.conversacion or {}).get("nivel_experiencia")
        or "desconocido"
    ).lower()
    nivel_abierto = nivel_actual in {"desconocido", ""} and not bool(
        (contexto.conversacion or {}).get("nivel_experiencia_confirmado")
    )

    decision = resolver_turno_inteligente(
        texto=texto or "",
        conversacion=contexto.conversacion or {},
        aspirante=contexto.aspirante,
        perfil=perfil_act,
        flujo=contexto.flujo,
        paso=contexto.paso,
        requisitos=contexto.requisitos,
        beneficios=contexto.beneficios,
        faqs=contexto.faqs,
        pregunta_pendiente=_leer_pregunta_pendiente(contexto.conversacion),
        nivel_abierto=nivel_abierto and bool(_usar_rutas(contexto.configuracion)),
    )
    # Persistir hechos extra del orquestador (p.ej. cumplo 18 mañana).
    if decision.hechos:
        from chatbot_conversacional_perfil import (
            fusionar_hechos_en_perfil,
            escribir_perfil_en_contexto,
        )

        perfil_act = fusionar_hechos_en_perfil(perfil_act, decision.hechos)
        escribir_perfil_en_contexto(contexto.conversacion, perfil_act)

    async def _responder_decision_directa(texto_resp: str, *, tipo_log: str, pend=None):
        texto_resp = _sanitizar_respuesta_usuario(str(texto_resp or "").strip())
        if pend and decision.retomar_pendiente:
            preg = str((pend or {}).get("texto") or "").strip()
            if preg and preg not in texto_resp and not _parece_instruccion_interna(preg):
                # No retomar clasificación de nivel si ya está confirmado.
                if str((pend or {}).get("campo") or "") == "nivel_experiencia" and str(
                    perfil_act.get("nivel_experiencia") or ""
                ) in {"principiante", "experimentado"}:
                    pass
                else:
                    texto_resp = f"{texto_resp}\n\nPara continuar, {preg}"
                    texto_resp = _sanitizar_respuesta_usuario(texto_resp)
        logger.info("[CHATBOT_RESPUESTA] tipo=%s", tipo_log)
        envio_d = await _enviar_respuesta(
            canal=canal,
            texto=texto_resp,
            enlaces=[],
            token=token,
            phone_number_id=phone_number_id,
            destino=wa_id or usuario_externo_id,
            enviar_callback=enviar_callback,
            dry_run=dry_run,
        )
        if pend and decision.retomar_pendiente:
            await _guardar_pregunta_pendiente(contexto, pend, dry_run=dry_run)
        await _actualizar_cierre_de_turno(
            contexto,
            respuesta=texto_resp,
            mensaje_usuario=texto,
            acciones=[{"tipo": "decision_turno", "decision": decision.tipo, "motivo": decision.motivo}],
            escalado=False,
            cerrada=False,
            dry_run=dry_run,
        )
        return {
            "usado": True,
            "motivo": decision.motivo,
            "conversacion_id": conversacion_id,
            "mensaje_entrante_id": mensaje_entrante_id,
            "respuesta": texto_resp,
            "modo": contexto.modo,
            "acciones": [{"tipo": "decision_turno", "decision": decision.tipo}],
            "enlaces": [],
            "escalado": False,
            "cerrada": False,
            "enviado": envio_d.get("enviado"),
            "error": envio_d.get("error"),
            "tipo_chatbot": "inteligente",
            "modo_humano": False,
            "perfil": perfil_act,
            "decision": {
                "tipo": decision.tipo,
                "accion": decision.accion,
                "motivo": decision.motivo,
                "intencion": decision.intencion,
            },
            "action_gate": decision.gate,
        }

    if decision.tipo == "bloqueado":
        return await _responder_decision_directa(
            decision.texto_base or mensaje_bloqueo_para_usuario(
                decision.gate or {}, perfil=perfil_act
            ),
            tipo_log="bloqueo",
        )

    if decision.tipo == "preguntar":
        return await _responder_decision_directa(
            decision.texto_base or "",
            tipo_log="pregunta",
            pend=decision.dato_pendiente,
        )

    if decision.tipo == "informar":
        texto_info = decision.texto_base
        if decision.accion == "proceso" or decision.intencion == "proceso":
            texto_info = _construir_texto_informativo_inteligente(
                contexto, "proceso", texto or ""
            )
        return await _responder_decision_directa(
            texto_info or "",
            tipo_log="informacion",
            pend=decision.dato_pendiente,
        )

    if decision.tipo == "ejecutar_accion" and decision.accion == "enviar_solicitud":
        # Gate nivel 1 ya pasó; la tool vuelve a validar (nivel 2).
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

    # agendar_live y otras acciones autorizadas: el agente ejecuta la tool,
    # pero con herramientas_bloqueadas filtradas (defense in depth).
    if decision.tipo == "ejecutar_accion":
        logger.info(
            "[CHATBOT_DECISION] tipo=ejecutar_accion accion=%s via=agente_filtrado",
            decision.accion,
        )

    if decision.tipo == "continuar_flujo":
        return await _resolver_siguiente_paso_pendiente(
            contexto=contexto,
            prefijo=None,
            conversacion_id=conversacion_id,
            mensaje_entrante_id=mensaje_entrante_id,
            texto_usuario=texto,
            canal=canal,
            token=token,
            phone_number_id=phone_number_id,
            destino=wa_id or usuario_externo_id,
            enviar_callback=enviar_callback,
            dry_run=dry_run,
            origen="orquestador",
        )

    # continuar_clasificacion | usar_agente | ejecutar_accion parcial:
    # sigue el pipeline (clasificación / agente) con tools filtradas.
    herramientas_excluidas_turno = list(decision.herramientas_bloqueadas or [])

    # Prioridad residual: respuesta ambigua ya cubierta; interrupción solo si
    # el orquestador no resolvió información.
    interpretacion_pend = _interpretar_respuesta_a_pregunta_pendiente(
        contexto, texto
    )
    if interpretacion_pend and interpretacion_pend.get("tipo") == "aclarar_pendiente":
        return await _responder_aclaracion_pendiente(
            contexto=contexto,
            interpretacion=interpretacion_pend,
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
    # Si es respuesta a la pendiente (sí/no/dato), no la trates como
    # interrupción informativa: deja que el flujo/agente la procese.
    permitir_interrupcion = True
    if interpretacion_pend and interpretacion_pend.get("tipo") == "respuesta_pendiente":
        permitir_interrupcion = False

    interrupcion = None
    if permitir_interrupcion:
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
                from chatbot_conversacional_clasificacion import (
                    TEXTO_ACLARACION_NIVEL,
                    inferir_nivel_desde_texto,
                )

                ctx_loop = _contexto_conversacion_dict(contexto.conversacion)
                intentos = int(ctx_loop.get("intentos_pregunta_nivel") or 0)
                pendiente_prev = _leer_pregunta_pendiente(contexto.conversacion)
                if (
                    pendiente_prev
                    and str(pendiente_prev.get("campo") or "") == "nivel_experiencia"
                    and intentos >= 1
                ):
                    # Loop guard: no repetir la misma pregunta indefinidamente.
                    nivel_g, conf_g, decl_g, _ev = inferir_nivel_desde_texto(
                        texto,
                        pregunta_nivel_pendiente=True,
                        usar_ia=True,
                    )
                    if nivel_g == "desconocido":
                        # Salvamento: señales débiles tras reintento.
                        n_txt = _normalizar_texto_salida(texto)
                        if any(
                            x in n_txt
                            for x in (
                                "no",
                                "nunca",
                                "cero",
                                "nuev",
                                "sin exp",
                                "princip",
                            )
                        ):
                            nivel_g, conf_g, decl_g = "principiante", 0.9, True
                        elif any(
                            x in n_txt
                            for x in (
                                "si",
                                "hago",
                                "realizo",
                                "experiencia",
                                "ano",
                                "mes",
                                "transmit",
                            )
                        ):
                            nivel_g, conf_g, decl_g = "experimentado", 0.9, True

                    if nivel_g in {"principiante", "experimentado"} and decl_g:
                        logger.warning(
                            "[CHATBOT_LOOP_GUARD] conversacion_id=%s "
                            "paso_id=%s motivo=pregunta_ya_resuelta nivel=%s",
                            conversacion_id,
                            (pendiente_prev or {}).get("paso_id"),
                            nivel_g,
                        )
                        # Forzar orientación + flujo sin repreguntar.
                        contexto.conversacion["nivel_experiencia"] = nivel_g
                        contexto.conversacion["nivel_experiencia_confirmado"] = True
                        contexto.conversacion["nivel_experiencia_confianza"] = conf_g
                        contexto.conversacion["nivel_experiencia_fuente"] = "declarada"
                        await _limpiar_pregunta_pendiente(contexto, dry_run=dry_run)
                        await _seleccionar_flujo_por_nivel_confirmado(
                            contexto, nivel=nivel_g, dry_run=dry_run
                        )
                        prefijo = (
                            str(
                                (contexto.asistente or {}).get(
                                    "texto_inicio_principiante"
                                    if nivel_g == "principiante"
                                    else "texto_inicio_experimentado"
                                )
                                or ""
                            ).strip()
                            or (
                                "Perfecto. Como estás comenzando, te oriento paso a paso."
                                if nivel_g == "principiante"
                                else (
                                    "Gracias. Como ya tienes experiencia con LIVE, "
                                    "te guío con el proceso directo de la agencia."
                                )
                            )
                        )
                        return await _resolver_siguiente_paso_pendiente(
                            contexto=contexto,
                            prefijo=prefijo,
                            conversacion_id=conversacion_id,
                            mensaje_entrante_id=mensaje_entrante_id,
                            texto_usuario=texto,
                            canal=canal,
                            token=token,
                            phone_number_id=phone_number_id,
                            destino=wa_id or usuario_externo_id,
                            enviar_callback=enviar_callback,
                            dry_run=dry_run,
                            origen="loop_guard_clasificacion",
                        )

                pendiente_guardar = {
                    "paso_id": contexto.conversacion.get("paso_actual_id"),
                    "campo": "nivel_experiencia",
                    "texto": str(
                        (contexto.asistente or {}).get("pregunta_clasificacion_nivel")
                        or TEXTO_ACLARACION_NIVEL
                        or "¿Ya has realizado transmisiones LIVE?"
                    ).strip(),
                }
                # Contador anti-bucle en contexto JSON existente.
                ctx_loop["intentos_pregunta_nivel"] = intentos + 1
                ctx_loop["pregunta_pendiente"] = pendiente_guardar
                contexto.conversacion["contexto"] = ctx_loop
                if not dry_run and conversacion_id:
                    await _db(
                        "actualizar_conversacion",
                        contexto.agencia_id,
                        conversacion_id,
                        {"contexto": ctx_loop},
                    )
                return await _responder_presentacion_literal(
                    contexto=contexto,
                    presentacion=_sanitizar_respuesta_usuario(respuesta_directa),
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

            # Tras orientar principiante/experimentado: continuar al siguiente paso.
            if accion in {"orientar_experimentado", "orientar_principiante"}:
                logger.info(
                    "[CHATBOT_INTELIGENTE] conversacion_id=%s nivel=%s "
                    "flujo_id=%s paso_actual_id=%s accion=clasificacion_completada",
                    conversacion_id,
                    nivel_cls,
                    (contexto.flujo or {}).get("id")
                    or (contexto.conversacion or {}).get("flujo_id"),
                    (contexto.paso or {}).get("id")
                    or (contexto.conversacion or {}).get("paso_actual_id"),
                )
                return await _resolver_siguiente_paso_pendiente(
                    contexto=contexto,
                    prefijo=respuesta_directa,
                    conversacion_id=conversacion_id,
                    mensaje_entrante_id=mensaje_entrante_id,
                    texto_usuario=texto,
                    canal=canal,
                    token=token,
                    phone_number_id=phone_number_id,
                    destino=wa_id or usuario_externo_id,
                    enviar_callback=enviar_callback,
                    dry_run=dry_run,
                    origen="clasificacion",
                )

            return await _responder_presentacion_literal(
                contexto=contexto,
                presentacion=_sanitizar_respuesta_usuario(respuesta_directa),
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

    preparado = crear_agente(
        contexto,
        dry_run=dry_run,
        mensaje_id=mensaje_entrante_id,
        herramientas_excluidas=herramientas_excluidas_turno
        if "herramientas_excluidas_turno" in locals()
        else None,
    )
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

# Campos / patrones que NUNCA deben enviarse al usuario.
_CAMPOS_PASO_SOLO_INTERNOS = frozenset(
    {
        "mensaje_instrucciones",
        "configuracion",
        "estado_exitoso",
        "estado_fallido",
        "siguiente_paso_id",
        "siguiente_paso_fallo_id",
    }
)
_PATRONES_INSTRUCCION_INTERNA = (
    "reconoce que",
    "explica el proposito",
    "explica el propósito",
    "usa la herramienta",
    "usando la herramienta",
    "transfiere a una persona",
    "transfiere al equipo",
    "no prometas",
    "sin evaluar al candidato",
    "para el asistente",
    "mensaje_instrucciones",
    "tipo_accion",
    "paso_actual_id",
)
_PIES_MENU_INFORMATIVO = (
    "escribe el numero para mas detalle",
    "escribe otro numero",
    "o menu para volver al menu",
    "para volver al menu",
    "escribe menu para volver",
)


def _normalizar_texto_salida(texto: str) -> str:
    valor = str(texto or "").strip().lower()
    valor = unicodedata.normalize("NFD", valor)
    valor = "".join(ch for ch in valor if unicodedata.category(ch) != "Mn")
    valor = re.sub(r"[^\w\s]", " ", valor, flags=re.UNICODE)
    return re.sub(r"\s+", " ", valor).strip()


def _parece_instruccion_interna(texto: str) -> bool:
    """True si el texto parece instrucción para el asistente, no mensaje al usuario."""
    crudo = str(texto or "").strip()
    if not crudo:
        return False
    n = _normalizar_texto_salida(crudo)
    if any(p in n for p in _PATRONES_INSTRUCCION_INTERNA):
        return True
    # Imperativos típicos de prompt sin signo de pregunta.
    if "?" not in crudo and "¿" not in crudo:
        if re.match(
            r"^(reconoce|explica|confirma|solicita|envia|envía|transfiere|"
            r"menciona|responde con base|presentate|preséntate)\b",
            n,
        ):
            return True
    return False


def _quitar_pies_menu_informativo(texto: str) -> str:
    """Elimina pies de navegación del menú informativo en salidas del inteligente."""
    lineas_ok: List[str] = []
    for linea in str(texto or "").splitlines():
        n = _normalizar_texto_salida(linea)
        if any(p in n for p in _PIES_MENU_INFORMATIVO):
            continue
        if "escribe" in n and "numero" in n and ("detalle" in n or "menu" in n):
            continue
        if n.startswith("escribe menu"):
            continue
        lineas_ok.append(linea.rstrip())
    return "\n".join(lineas_ok).strip()


def _sanitizar_respuesta_usuario(texto: str) -> str:
    """
    Frontera de salida: solo texto dirigido al usuario.
    Quita pies de menú informativo y líneas que parecen instrucciones internas.
    """
    limpio = _quitar_pies_menu_informativo(texto)
    lineas_ok: List[str] = []
    filtradas = 0
    for linea in limpio.splitlines():
        if _parece_instruccion_interna(linea):
            filtradas += 1
            continue
        # Evitar prefijos "Para continuar: <instrucción interna>"
        if re.match(r"(?i)^\s*para continuar\s*:\s*", linea):
            resto = re.sub(r"(?i)^\s*para continuar\s*:\s*", "", linea).strip()
            if _parece_instruccion_interna(resto):
                filtradas += 1
                continue
        lineas_ok.append(linea.rstrip())
    if filtradas:
        logger.warning(
            "[CHATBOT_SEGURIDAD_SALIDA] motivo=instruccion_interna_en_respuesta "
            "lineas_filtradas=%s",
            filtradas,
        )
    return "\n".join(lineas_ok).strip()


def _texto_publico_paso(
    paso: Optional[Dict[str, Any]],
    *,
    contexto: Optional[ConversationalContext] = None,
) -> Optional[str]:
    """
    Texto visible para el usuario a partir del paso.
    NUNCA usa mensaje_instrucciones ni nombres internos tipo
    «Continuemos con: Presentar la oportunidad… ¿Seguimos?».
    """
    if not isinstance(paso, dict) or not paso:
        return None

    # Campos explícitamente públicos.
    for clave in ("mensaje_usuario", "pregunta_usuario", "texto_publico"):
        valor = str(paso.get(clave) or "").strip()
        if valor and not _parece_instruccion_interna(valor):
            return valor

    descripcion = str(paso.get("descripcion") or "").strip()
    if descripcion and not _parece_instruccion_interna(descripcion):
        if "?" in descripcion or "¿" in descripcion:
            return descripcion
        if len(descripcion) <= 220 and not _parece_nombre_paso_interno(descripcion):
            return descripcion

    nombre = str(paso.get("nombre") or "").strip()
    if nombre and ("?" in nombre or nombre.startswith("¿")):
        return nombre

    tipo = str(paso.get("tipo_accion") or "").strip().lower()
    codigo = _normalizar_texto_salida(str(paso.get("codigo") or ""))
    nombre_n = _normalizar_texto_salida(nombre)

    if "edad" in codigo or "mayor" in codigo or "mayoria" in nombre_n:
        return "Antes de continuar, ¿eres mayor de 18 años?"
    if "disponib" in codigo or "disponib" in nombre_n:
        return (
            "¿Tienes disponibilidad para realizar transmisiones LIVE "
            "varios días a la semana?"
        )
    if tipo == "confirmar_interes":
        return "¿Te gustaría continuar con el proceso de ingreso a la agencia?"
    if tipo == "hacer_pregunta":
        if nombre and not _parece_nombre_paso_interno(nombre):
            if "?" in nombre or "¿" in nombre:
                return nombre
            return f"Para continuar, ¿me confirmas: {nombre}?"
        return "Para continuar, ¿me confirmas ese dato?"
    if tipo == "enviar_enlace":
        return (
            "Por tu perfil podemos avanzar con la solicitud. "
            "Te compartiré el enlace para continuar."
        )
    if tipo in {"agendar_live", "solicitar_live"}:
        return "Cuando estés listo, te indico cómo continuar con la prueba LIVE."
    if tipo == "solicitar_evidencias":
        return "Cuando corresponda, te pediré las evidencias necesarias."
    if tipo == "confirmar_evidencias":
        return "Cuando envíes las evidencias, las revisaremos para continuar."
    if tipo == "transferir_humano":
        return (
            "Si prefieres, puedo dejar tu caso marcado para que un asesor "
            "del equipo lo revise."
        )
    if tipo == "esperar_respuesta":
        return "Cuando puedas, respóndeme para continuar."
    # informar / explicar_*: no pedir «¿seguimos?» ni mostrar el nombre interno.
    if tipo in {
        "informar",
        "explicar_requisitos",
        "explicar_beneficios",
        "explicar_bonos",
    }:
        return None
    return None


def _parece_nombre_paso_interno(texto: str) -> bool:
    n = _normalizar_texto_salida(texto)
    if not n:
        return True
    # Títulos de paso típicos (infinitivo / gerundio de acción interna).
    if re.match(
        r"^(presentar|confirmar|explicar|solicitar|enviar|agendar|"
        r"transferir|clasificar|orientar|registrar|ejecutar)\b",
        n,
    ):
        return True
    if "oportunidad de la campana" in n:
        return True
    return False


# Pasos que se ejecutan y avanzan sin esperar al usuario.
_TIPOS_PASO_AUTO = frozenset(
    {
        "informar",
        "explicar_requisitos",
        "explicar_beneficios",
        "explicar_bonos",
    }
)
# Pasos que requieren respuesta real del usuario.
_TIPOS_PASO_ESPERAN_USUARIO = frozenset(
    {
        "hacer_pregunta",
        "confirmar_interes",
        "solicitar_evidencias",
        "confirmar_evidencias",
        "esperar_respuesta",
        "agendar_live",
        "solicitar_live",
    }
)


def _contenido_ejecucion_paso_auto(
    contexto: ConversationalContext,
    paso: Dict[str, Any],
) -> Optional[str]:
    """
    Contenido público al ejecutar un paso informativo.
    Usa datos configurados (requisitos/beneficios/campaña/texto público).
    Nunca expone mensaje_instrucciones ni el nombre interno del paso.
    """
    tipo = str(paso.get("tipo_accion") or "").strip().lower()

    for clave in ("mensaje_usuario", "texto_publico", "pregunta_usuario"):
        valor = str(paso.get(clave) or "").strip()
        if valor and not _parece_instruccion_interna(valor):
            return valor

    descripcion = str(paso.get("descripcion") or "").strip()
    if (
        descripcion
        and not _parece_instruccion_interna(descripcion)
        and not _parece_nombre_paso_interno(descripcion)
    ):
        return descripcion

    if tipo == "explicar_requisitos":
        return _construir_texto_informativo_inteligente(
            contexto, "requisitos", "requisitos"
        ) or None
    if tipo == "explicar_beneficios":
        return _construir_texto_informativo_inteligente(
            contexto, "beneficios", "beneficios"
        ) or None
    if tipo == "explicar_bonos":
        return _construir_texto_informativo_inteligente(
            contexto, "bonos", "bonos"
        ) or None

    if tipo == "informar":
        campania = contexto.campania or {}
        for clave in (
            "mensaje_bienvenida",
            "descripcion_publica",
            "descripcion",
            "nombre",
        ):
            valor = str(campania.get(clave) or "").strip()
            if (
                valor
                and not _parece_instruccion_interna(valor)
                and not _parece_nombre_paso_interno(valor)
            ):
                if clave == "nombre":
                    return (
                        f"Esta campaña ({valor}) te ofrece una oportunidad "
                        "para avanzar con la agencia."
                    )
                return valor
        asistente = contexto.asistente or {}
        intro = str(asistente.get("texto_presentacion_oportunidad") or "").strip()
        if intro and not _parece_instruccion_interna(intro):
            return intro
        # Sin contenido público: no inventar ni mostrar el nombre del paso.
        return None

    return None


async def _avanzar_paso_flujo(
    contexto: ConversationalContext,
    *,
    dry_run: bool,
) -> Optional[Dict[str, Any]]:
    """Avanza al siguiente paso activo del flujo actual. None si no hay más."""
    flujo = contexto.flujo or {}
    flujo_id = flujo.get("id") or (contexto.conversacion or {}).get("flujo_id")
    if not flujo_id:
        return None
    pasos = (
        await _db(
            "listar_flujo_pasos",
            contexto.agencia_id,
            int(flujo_id),
            solo_activos=True,
            default=[],
        )
        or []
    )
    pasos_ord = sorted(
        [p for p in pasos if p],
        key=lambda p: (int(p.get("orden") or 0), int(p.get("id") or 0)),
    )
    actual_id = (contexto.conversacion or {}).get("paso_actual_id") or (
        contexto.paso or {}
    ).get("id")
    siguiente = None
    encontrado = False
    for p in pasos_ord:
        if encontrado:
            siguiente = p
            break
        if int(p.get("id") or 0) == int(actual_id or 0):
            encontrado = True
    if not encontrado and pasos_ord:
        # Paso actual no listado: tomar el primero pendiente por orden.
        siguiente = pasos_ord[0]
    if not siguiente:
        return None

    campos = {
        "paso_actual_id": siguiente.get("id"),
        "estado_actual": "paso_avanzado",
    }
    if not dry_run and contexto.conversacion_id:
        await _db(
            "actualizar_conversacion",
            contexto.agencia_id,
            contexto.conversacion_id,
            campos,
        )
    contexto.conversacion.update(campos)
    contexto.paso = siguiente
    return siguiente


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
    texto = str(pendiente.get("texto") or "").strip()
    if _parece_instruccion_interna(texto):
        # Nunca persistir instrucciones internas como pregunta al usuario.
        publico = _texto_publico_paso(contexto.paso)
        if not publico:
            return
        pendiente = dict(pendiente)
        pendiente["texto"] = publico
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


def _interpretar_respuesta_a_pregunta_pendiente(
    contexto: ConversationalContext,
    texto_usuario: str,
) -> Optional[Dict[str, Any]]:
    """
    Prioridad: interpretar la respuesta contra pregunta_pendiente
    ANTES de tratar el texto como nueva intención informativa.
    """
    pendiente = _leer_pregunta_pendiente(contexto.conversacion)
    if not pendiente:
        return None

    campo = str(pendiente.get("campo") or "").lower()
    # La clasificación de nivel se resuelve en clasificar_mensaje.
    if campo in {"nivel_experiencia", "experiencia", "clasificacion_nivel"}:
        return None

    n = _normalizar_texto_salida(texto_usuario)
    if not n:
        return None

    preg = _normalizar_texto_salida(str(pendiente.get("texto") or ""))
    tipo = str(pendiente.get("tipo") or "").lower()

    ambiguos = {
        "mas o menos",
        "más o menos",
        "masomenos",
        "regular",
        "no se",
        "nose",
        "no sé",
        "depende",
        "algunas",
        "algunos",
        "a veces",
        "masomenos",
    }
    if n in ambiguos or n in {"mas o menos", "más o menos"}:
        if (
            "requisito" in preg
            or "cumple" in preg
            or "cumple" in campo
            or "requisito" in campo
            or tipo in {"hacer_pregunta", "confirmar_interes"}
        ):
            return {
                "tipo": "aclarar_pendiente",
                "respuesta": (
                    "Claro. ¿Cuál de estos requisitos no cumples o no tienes claro?"
                    if "requisito" in preg or "requisito" in campo or "cumple" in preg
                    else (
                        "No hay problema. ¿Puedes precisarme un poco más "
                        "para continuar con lo que te pregunté?"
                    )
                ),
                "pendiente": pendiente,
            }

    # Respuestas cortas afirmativas/negativas a la pregunta pendiente:
    # no tratarlas como interrupción informativa.
    if n in {"si", "sip", "claro", "ok", "okay", "vale", "de acuerdo", "no", "nop"}:
        return {"tipo": "respuesta_pendiente", "pendiente": pendiente}

    # Si parece pregunta informativa explícita, dejar que la interrupción actúe.
    if "?" in str(texto_usuario or "") or "¿" in str(texto_usuario or ""):
        return None

    # Texto afirmativo/negativo largo sin marcadores de tema informativo:
    # pertenece a la pregunta pendiente.
    if not any(
        k in n
        for k in (
            "requisito",
            "beneficio",
            "bono",
            "proceso",
            "agencia",
            "como funciona",
        )
    ):
        return {"tipo": "respuesta_pendiente", "pendiente": pendiente}

    return None


async def _responder_aclaracion_pendiente(
    *,
    contexto: ConversationalContext,
    interpretacion: Dict[str, Any],
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
    pendiente = interpretacion.get("pendiente") or _leer_pregunta_pendiente(
        contexto.conversacion
    )
    respuesta = _sanitizar_respuesta_usuario(
        str(interpretacion.get("respuesta") or "").strip()
    )
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
    if pendiente:
        await _guardar_pregunta_pendiente(contexto, pendiente, dry_run=dry_run)
    await _actualizar_cierre_de_turno(
        contexto,
        respuesta=respuesta,
        mensaje_usuario=texto_usuario,
        acciones=[{"tipo": "aclarar_pregunta_pendiente"}],
        escalado=False,
        cerrada=False,
        dry_run=dry_run,
    )
    return {
        "usado": True,
        "motivo": None,
        "conversacion_id": conversacion_id,
        "mensaje_entrante_id": mensaje_entrante_id,
        "respuesta": respuesta,
        "modo": contexto.modo,
        "acciones": [{"tipo": "aclarar_pregunta_pendiente"}],
        "enlaces": [],
        "escalado": False,
        "cerrada": False,
        "enviado": envio.get("enviado"),
        "error": envio.get("error"),
        "pregunta_pendiente": pendiente,
        "tipo_chatbot": "inteligente",
        "modo_humano": False,
    }


def _detectar_intencion_interrupcion_informativa(texto: str) -> Optional[str]:
    """Detecta preguntas informativas durante un paso con pregunta pendiente."""
    intencion, _conf = inferir_intencion(texto)
    if intencion in {"requisitos", "beneficios", "bonos"}:
        return intencion
    if intencion == "informacion":
        # Puede ser saludo corto; solo FAQ si parece pregunta.
        if "?" in str(texto or "") or "¿" in str(texto or ""):
            return "faq"
        return None

    n = _normalizar_texto_salida(texto)
    if any(k in n for k in ("agencia", "funcionamiento", "como funciona", "funciona")):
        return "agencia"
    if any(k in n for k in ("proceso", "continuar", "solicitud", "unirme", "incorpor")):
        return "proceso"
    return None


MENSAJE_SIN_CONOCIMIENTO_PROCESO = (
    "No tengo información confirmada sobre el proceso de ingreso en este momento. "
    "Puedo seguir ayudándote con otras dudas o dejar tu consulta para el equipo."
)

_CODIGO_FLUJO_CONVERSION = "conversion_base"
_CLAVES_FAQ_PROCESO = (
    "proceso",
    "ingreso",
    "ingresar",
    "unirme",
    "entrar",
    "incorpor",
    "pasos",
    "como entro",
    "como ingreso",
    "que sigue",
)


def _listar_pasos_flujo_seguro(
    *,
    agencia_id: int,
    flujo_id: Optional[int],
) -> List[Dict[str, Any]]:
    if not flujo_id:
        return []
    try:
        import database_chatbot_conversacional as db_conv

        return (
            db_conv.listar_flujo_pasos(
                agencia_id,
                int(flujo_id),
                solo_activos=True,
            )
            or []
        )
    except Exception:  # noqa: BLE001
        return []


def _obtener_flujo_proceso_configurado(
    contexto: ConversationalContext,
) -> Optional[Dict[str, Any]]:
    """
    Flujo donde se persiste «Proceso de ingreso» (carga → conversion_base).
    Sin crear tablas nuevas.
    """
    cfg_id = contexto.chatbot_configuracion_id
    if not cfg_id:
        return None
    try:
        import database_chatbot_conversacional as db_conv

        flujos = (
            db_conv.listar_flujos(
                contexto.agencia_id,
                chatbot_configuracion_id=int(cfg_id),
                tipo_flujo="conversion",
                solo_activos=True,
            )
            or []
        )
    except Exception:  # noqa: BLE001
        return None
    if not flujos:
        return None
    por_codigo = next(
        (
            f
            for f in flujos
            if str(f.get("codigo") or "").strip().lower() == _CODIGO_FLUJO_CONVERSION
        ),
        None,
    )
    return por_codigo or flujos[0]


def _pasos_publicos_seguros(
    pasos: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """
    Representación pública sanitizada de pasos.
    Excluye mensaje_instrucciones, configuracion, estados y textos internos.
    """
    out: List[Dict[str, Any]] = []
    for p in sorted(
        [x for x in (pasos or []) if x],
        key=lambda x: (int(x.get("orden") or 0), int(x.get("id") or 0)),
    ):
        nombre = str(p.get("nombre") or "").strip()
        if not nombre or _parece_instruccion_interna(nombre):
            continue
        # Evitar códigos crudos como nombre visible.
        if "_" in nombre and " " not in nombre and len(nombre) < 40:
            continue

        texto_publico = ""
        for clave in ("texto_publico", "mensaje_usuario", "pregunta_usuario"):
            cand = str(p.get(clave) or "").strip()
            if cand and not _parece_instruccion_interna(cand):
                texto_publico = cand
                break
        if not texto_publico:
            desc = str(p.get("descripcion") or "").strip()
            if (
                desc
                and not _parece_instruccion_interna(desc)
                and ("?" in desc or "¿" in desc or len(desc) <= 160)
            ):
                texto_publico = desc

        tipo = str(p.get("tipo_accion") or "").strip().lower()
        out.append(
            {
                "nombre": nombre[:160],
                "tipo_accion": tipo,
                "texto_publico": texto_publico[:400] if texto_publico else "",
            }
        )
        if len(out) >= 12:
            break
    return out


def _texto_proceso_configurado(
    pasos_publicos: List[Dict[str, Any]],
) -> Optional[str]:
    """
    Fuente 1: texto de «Proceso de ingreso» ya persistido como pasos públicos
    (nombres configurados en carga → flujo_pasos).
    """
    utiles = [
        p
        for p in pasos_publicos
        if str(p.get("nombre") or "").strip()
        and str(p.get("tipo_accion") or "") not in {"finalizar"}
    ]
    if len(utiles) < 2:
        return None

    lineas = ["El proceso de ingreso configurado es el siguiente:", ""]
    for i, p in enumerate(utiles[:10], start=1):
        nombre = str(p.get("nombre") or "").strip()
        extra = str(p.get("texto_publico") or "").strip()
        if extra and extra != nombre and not _parece_instruccion_interna(extra):
            # Solo añadir si parece aclaración breve para el usuario.
            if len(extra) <= 120 and ("?" in extra or "¿" in extra):
                lineas.append(f"{i}. {nombre}")
            else:
                lineas.append(f"{i}. {nombre}")
        else:
            lineas.append(f"{i}. {nombre}")
    lineas.append("")
    lineas.append(
        "La revisión final la realiza el equipo de la agencia."
    )
    return "\n".join(lineas).strip()


def _resumen_publico_desde_pasos_publicos(
    pasos_publicos: List[Dict[str, Any]],
) -> Optional[str]:
    """
    Fuente 2: resumen narrativo seguro (sin enumerar pasos técnicos).
    No afirma que los pasos condicionales siempre ocurren.
    """
    if not pasos_publicos:
        return None

    tipos = {
        str(p.get("tipo_accion") or "").strip().lower() for p in pasos_publicos
    }
    base: List[str] = ["una orientación inicial"]
    if tipos & {
        "explicar_requisitos",
        "hacer_pregunta",
        "confirmar_interes",
        "informar",
    }:
        base.append("la confirmación de algunos datos y requisitos")
    if "enviar_enlace" in tipos:
        base.append("completar la solicitud")

    condicionales: List[str] = []
    if tipos & {"agendar_live", "solicitar_live"}:
        condicionales.append("realizar una prueba LIVE")
    if tipos & {"solicitar_evidencias", "confirmar_evidencias"}:
        condicionales.append("enviar evidencias")

    # Evitar resumen vacío/trivial.
    if len(base) <= 1 and not condicionales and len(pasos_publicos) < 2:
        return None

    if len(base) == 1:
        nucleo = base[0]
    elif len(base) == 2:
        nucleo = f"{base[0]} y {base[1]}"
    else:
        nucleo = f"{', '.join(base[:-1])} y {base[-1]}"

    texto = f"El proceso puede incluir {nucleo}"
    if condicionales:
        if len(condicionales) == 1:
            texto += f" y, cuando corresponda, {condicionales[0]}"
        else:
            texto += (
                " y, cuando corresponda, "
                + " o ".join(condicionales)
            )
    texto += (
        ". Finalmente, el equipo revisará la información para continuar contigo."
    )
    return texto


def _faq_es_especifica_de_proceso(faq: Dict[str, Any]) -> bool:
    blob = _normalizar_texto_salida(
        " ".join(
            [
                str(faq.get("pregunta") or ""),
                str(faq.get("intencion") or ""),
                str(faq.get("categoria") or ""),
                str(faq.get("codigo") or ""),
                " ".join(
                    str(x)
                    for x in (faq.get("palabras_clave") or [])
                    if x
                ),
            ]
        )
    )
    return any(k in blob for k in _CLAVES_FAQ_PROCESO)


def _parece_bloque_proceso_mal_cargado(faq: Dict[str, Any]) -> bool:
    """Descarta textos de flujo/pasos pegados como FAQ (no FAQs reales)."""
    pregunta = str(faq.get("pregunta") or "")
    n = _normalizar_texto_salida(pregunta)
    if "presentar la oportunidad" in n and "agendar" in n:
        return True
    if n.count("1.") + n.count("2.") + n.count("3.") >= 3 and len(pregunta) > 200:
        return True
    return False


def _score_faq_proceso(texto_consulta: str, faq: Dict[str, Any]) -> int:
    """Puntuación léxica simple solo para FAQs ya filtradas de proceso."""
    consulta = _normalizar_texto_salida(texto_consulta)
    blob = _normalizar_texto_salida(
        " ".join(
            [
                str(faq.get("pregunta") or ""),
                str(faq.get("respuesta_corta") or ""),
                " ".join(
                    str(x) for x in (faq.get("palabras_clave") or []) if x
                ),
            ]
        )
    )
    score = 0
    for clave in _CLAVES_FAQ_PROCESO:
        if clave in consulta and clave in blob:
            score += 8
        elif clave in blob:
            score += 3
    # Tokens de la consulta presentes en la FAQ.
    tokens = [t for t in consulta.split() if len(t) >= 4]
    for tok in tokens:
        if tok in blob:
            score += 2
    score += min(10, int(faq.get("prioridad") or 0) // 5)
    return score


def _faq_proceso_especifica(
    contexto: ConversationalContext,
    texto_consulta: str,
) -> Optional[str]:
    """
    Fuente 3: solo FAQ realmente de proceso/ingreso.

    No usa resolver_faq genérico: ese excluye FAQs con codigo proceso+ingreso
    (para no mezclar bloques de flujo en Q&A libre). Aquí las seleccionamos
    a propósito, con matching propio.
    """
    try:
        import database_chatbot_conversacional as db_conv
        from chatbot_faq_resolver import texto_respuesta_faq

        faqs = (
            db_conv.listar_faqs(
                contexto.agencia_id,
                chatbot_configuracion_id=int(
                    contexto.chatbot_configuracion_id or 0
                ),
                solo_activos=True,
            )
            or []
        )
    except Exception:  # noqa: BLE001
        return None

    candidatas = [
        f
        for f in faqs
        if _faq_es_especifica_de_proceso(f)
        and not _parece_bloque_proceso_mal_cargado(f)
    ]
    if not candidatas:
        return None

    ranked = sorted(
        ((_score_faq_proceso(texto_consulta, f), f) for f in candidatas),
        key=lambda x: (-x[0], -int(x[1].get("prioridad") or 0)),
    )
    top_score, top_faq = ranked[0]
    # Exigir señal mínima de proceso (no coger cualquier FAQ filtrada al azar).
    if top_score < 8:
        return None

    resp = str(texto_respuesta_faq(top_faq) or "").strip()
    if not resp or _parece_instruccion_interna(resp):
        return None
    return _sanitizar_respuesta_usuario(resp)


def _resolver_consultar_proceso(
    contexto: ConversationalContext,
    texto_consulta: str,
) -> str:
    """
    Prioridad exacta para consultar_proceso:
    1) texto Proceso de ingreso (pasos públicos del flujo conversion_base)
    2) resumen público del flujo activo
    3) FAQ específica de proceso
    4) sin conocimiento
    """
    # 1) Texto configurado (carga → flujo conversion_base / conversion).
    flujo_cfg = _obtener_flujo_proceso_configurado(contexto)
    pasos_cfg = _listar_pasos_flujo_seguro(
        agencia_id=contexto.agencia_id,
        flujo_id=(flujo_cfg or {}).get("id"),
    )
    publicos_cfg = _pasos_publicos_seguros(pasos_cfg)
    texto_cfg = _texto_proceso_configurado(publicos_cfg)
    if texto_cfg:
        logger.info(
            "[CHATBOT_PROCESO] fuente=proceso_ingreso_configurado "
            "flujo_id=%s pasos_publicos=%s",
            (flujo_cfg or {}).get("id"),
            len(publicos_cfg),
        )
        return _sanitizar_respuesta_usuario(texto_cfg)

    # 2) Resumen del flujo activo de la conversación.
    flujo_activo = contexto.flujo or {}
    flujo_activo_id = flujo_activo.get("id") or (
        contexto.conversacion or {}
    ).get("flujo_id")
    pasos_act = _listar_pasos_flujo_seguro(
        agencia_id=contexto.agencia_id,
        flujo_id=int(flujo_activo_id) if flujo_activo_id else None,
    )
    publicos_act = _pasos_publicos_seguros(pasos_act)
    resumen = _resumen_publico_desde_pasos_publicos(publicos_act)
    if resumen:
        logger.info(
            "[CHATBOT_PROCESO] fuente=resumen_flujo_activo "
            "flujo_id=%s pasos_publicos=%s",
            flujo_activo_id,
            len(publicos_act),
        )
        return _sanitizar_respuesta_usuario(resumen)

    # 3) FAQ específica.
    faq = _faq_proceso_especifica(contexto, texto_consulta)
    if faq:
        logger.info("[CHATBOT_PROCESO] fuente=faq_proceso")
        return faq

    # 4) Sin conocimiento (no inventar).
    logger.info("[CHATBOT_PROCESO] fuente=sin_conocimiento")
    return MENSAJE_SIN_CONOCIMIENTO_PROCESO


def _construir_texto_informativo_inteligente(
    contexto: ConversationalContext,
    intencion: str,
    texto_consulta: str,
) -> str:
    """
    Respuesta informativa para el inteligente:
    conocimiento autorizado SIN navegación del menú informativo.
    """
    if intencion == "proceso":
        return _resolver_consultar_proceso(contexto, texto_consulta)

    from chatbot_conversacional_perfil import consultar_conocimiento_puro

    if intencion in {"requisitos", "beneficios", "bonos", "agencia", "faq"}:
        texto = consultar_conocimiento_puro(
            tipo=intencion,
            requisitos=contexto.requisitos,
            beneficios=contexto.beneficios,
            faqs=contexto.faqs,
        )
        return _sanitizar_respuesta_usuario(str(texto or "").strip())

    # Fallback controlado: sin pies de menú.
    from service_chatbot_informativo import (
        construir_respuesta_por_intencion_informativa,
        presentacion_desde_asistente,
    )
    import database_chatbot_conversacional as db_conv

    presentacion = presentacion_desde_asistente(contexto.asistente)
    presentacion = dict(presentacion)
    presentacion["agregar_pregunta_final"] = False

    texto, _req, _lista = construir_respuesta_por_intencion_informativa(
        intencion,
        agencia_id=contexto.agencia_id,
        chatbot_configuracion_id=int(contexto.chatbot_configuracion_id or 0),
        presentacion=presentacion,
        texto_consulta=texto_consulta,
        db_conv=db_conv,
    )
    return _sanitizar_respuesta_usuario(str(texto or "").strip())


def _pendiente_desde_paso(
    contexto: ConversationalContext,
) -> Optional[Dict[str, Any]]:
    """Construye pregunta_pendiente pública a partir del paso actual."""
    paso = contexto.paso or {}
    paso_id = (contexto.conversacion or {}).get("paso_actual_id") or paso.get("id")
    tipo = str(paso.get("tipo_accion") or "").strip().lower()
    # Pasos auto no generan pregunta pendiente.
    if tipo in _TIPOS_PASO_AUTO:
        return None
    texto = _texto_publico_paso(paso, contexto=contexto)
    if not paso_id or not texto:
        return None
    return {
        "paso_id": paso_id,
        "campo": str(paso.get("codigo") or "paso_actual"),
        "tipo": tipo or "hacer_pregunta",
        "texto": texto,
    }


async def _resolver_siguiente_paso_pendiente(
    *,
    contexto: ConversationalContext,
    prefijo: Optional[str] = None,
    conversacion_id: Optional[int],
    mensaje_entrante_id: Optional[int],
    texto_usuario: str,
    canal: str,
    token: Optional[str],
    phone_number_id: Optional[str],
    destino: Optional[str],
    enviar_callback: Optional[EnviarCallback],
    dry_run: bool,
    origen: str = "flujo",
) -> Dict[str, Any]:
    """
    Continuidad proactiva:
    - ejecuta pasos informativos automáticamente;
    - avanza hasta un paso que realmente necesite respuesta del usuario;
    - nunca muestra «Continuemos con: [nombre interno]. ¿Seguimos?».
    """
    bloques: List[str] = []
    pref = _sanitizar_respuesta_usuario(str(prefijo or "").strip())
    if pref:
        bloques.append(pref)

    pendiente: Optional[Dict[str, Any]] = None
    max_hops = 10

    from chatbot_conversacional_perfil import (
        leer_perfil,
        paso_resuelto_por_perfil,
        puede_ejecutar_accion,
        mensaje_bloqueo_para_usuario,
    )

    for _ in range(max_hops):
        paso = contexto.paso or {}
        if not paso:
            break
        tipo = str(paso.get("tipo_accion") or "").strip().lower()
        paso_id = paso.get("id") or (contexto.conversacion or {}).get(
            "paso_actual_id"
        )
        perfil = leer_perfil(contexto.conversacion, contexto.aspirante)

        # Memoria factual: no repreguntar datos ya confirmados.
        if paso_resuelto_por_perfil(paso, perfil):
            logger.info(
                "[CHATBOT_FLUJO] conversacion_id=%s paso_id=%s "
                "tipo_accion=%s accion=omitido_dato_confirmado origen=%s",
                conversacion_id,
                paso_id,
                tipo,
                origen,
            )
            # Si el dato bloquea incorporación, informar y detener avance de conversión.
            if tipo in {"hacer_pregunta", "esperar_respuesta"}:
                codigo = str(paso.get("codigo") or "").lower()
                nombre = str(paso.get("nombre") or "").lower()
                if any(k in codigo or k in nombre for k in ("edad", "mayor")):
                    gate = puede_ejecutar_accion(
                        accion="enviar_solicitud",
                        conversacion=contexto.conversacion,
                        aspirante=contexto.aspirante,
                        perfil=perfil,
                        flujo=contexto.flujo,
                        paso=paso,
                        requisitos=contexto.requisitos,
                    )
                    if not gate.get("permitida"):
                        bloques.append(
                            mensaje_bloqueo_para_usuario(gate, perfil=perfil)
                        )
                        pendiente = None
                        break
            siguiente = await _avanzar_paso_flujo(contexto, dry_run=dry_run)
            if not siguiente:
                break
            continue

        # Action gating antes de pasos de acción de conversión.
        if tipo in {
            "enviar_enlace",
            "agendar_live",
            "solicitar_live",
            "solicitar_evidencias",
        }:
            gate = puede_ejecutar_accion(
                accion=tipo if tipo != "enviar_enlace" else "enviar_solicitud",
                conversacion=contexto.conversacion,
                aspirante=contexto.aspirante,
                perfil=perfil,
                flujo=contexto.flujo,
                paso=paso,
                requisitos=contexto.requisitos,
            )
            if not gate.get("permitida"):
                bloques.append(mensaje_bloqueo_para_usuario(gate, perfil=perfil))
                logger.info(
                    "[CHATBOT_FLUJO] conversacion_id=%s paso_id=%s "
                    "tipo_accion=%s accion=bloqueado_por_gate origen=%s",
                    conversacion_id,
                    paso_id,
                    tipo,
                    origen,
                )
                pendiente = None
                break

        if tipo in _TIPOS_PASO_AUTO:
            contenido = _contenido_ejecucion_paso_auto(contexto, paso)
            if contenido:
                limpio = _sanitizar_respuesta_usuario(contenido)
                if limpio and limpio not in bloques:
                    bloques.append(limpio)
            logger.info(
                "[CHATBOT_FLUJO] conversacion_id=%s paso_id=%s "
                "tipo_accion=%s accion=ejecutado_auto origen=%s",
                conversacion_id,
                paso_id,
                tipo,
                origen,
            )
            siguiente = await _avanzar_paso_flujo(contexto, dry_run=dry_run)
            if not siguiente:
                break
            continue

        # Paso que espera usuario o acción con instrucción clara.
        texto_paso = _texto_publico_paso(paso, contexto=contexto)
        if not texto_paso and tipo in {"enviar_enlace", "transferir_humano", "finalizar"}:
            texto_paso = _texto_publico_paso(
                {**paso, "tipo_accion": tipo}, contexto=contexto
            )
        if not texto_paso:
            # Sin texto público usable: intentar avanzar en lugar de inventar.
            logger.info(
                "[CHATBOT_FLUJO] conversacion_id=%s paso_id=%s "
                "tipo_accion=%s accion=omitido_sin_texto_publico origen=%s",
                conversacion_id,
                paso_id,
                tipo,
                origen,
            )
            siguiente = await _avanzar_paso_flujo(contexto, dry_run=dry_run)
            if not siguiente:
                break
            continue

        logger.info(
            "[CHATBOT_FLUJO] conversacion_id=%s paso_id=%s "
            "tipo_accion=%s accion=esperando_usuario origen=%s",
            conversacion_id,
            paso_id,
            tipo,
            origen,
        )
        if texto_paso not in bloques:
            bloques.append(_sanitizar_respuesta_usuario(texto_paso))
        pendiente = {
            "paso_id": paso_id,
            "campo": str(paso.get("codigo") or "paso_actual"),
            "tipo": tipo or "hacer_pregunta",
            "texto": texto_paso,
        }
        break

    respuesta = _sanitizar_respuesta_usuario("\n\n".join(b for b in bloques if b))
    if not respuesta:
        respuesta = (
            "Continuemos. ¿Me confirmas el siguiente dato para avanzar?"
        )
        pendiente = pendiente or {
            "paso_id": (contexto.conversacion or {}).get("paso_actual_id"),
            "campo": "paso_actual",
            "tipo": "hacer_pregunta",
            "texto": respuesta,
        }

    # Guardia: nunca filtrar a nombres internos residuales.
    if _parece_nombre_paso_interno(respuesta) or "continuemos con:" in _normalizar_texto_salida(
        respuesta
    ):
        logger.warning(
            "[CHATBOT_SEGURIDAD_SALIDA] motivo=nombre_paso_interno_en_respuesta"
        )
        respuesta = pref or (
            "Perfecto. Antes de continuar, ¿eres mayor de 18 años?"
            if (contexto.paso or {}).get("tipo_accion") == "hacer_pregunta"
            else "Perfecto, sigamos con el siguiente dato."
        )
        respuesta = _sanitizar_respuesta_usuario(respuesta)

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
                "continuar_flujo": True,
                "origen": origen,
                "paso_id": (pendiente or {}).get("paso_id"),
                "modo_humano": False,
            },
            default=None,
        )
        mensaje_saliente = _normalizar_fila_mensaje(mensaje_saliente)

    if pendiente:
        await _guardar_pregunta_pendiente(contexto, pendiente, dry_run=dry_run)
    else:
        await _limpiar_pregunta_pendiente(contexto, dry_run=dry_run)

    await _actualizar_cierre_de_turno(
        contexto,
        respuesta=respuesta,
        mensaje_usuario=texto_usuario,
        acciones=[{"tipo": "continuar_flujo", "origen": origen}],
        escalado=False,
        cerrada=False,
        dry_run=dry_run,
    )

    return {
        "usado": True,
        "motivo": None,
        "conversacion_id": conversacion_id,
        "mensaje_entrante_id": mensaje_entrante_id,
        "mensaje_saliente_id": (_normalizar_fila_mensaje(mensaje_saliente) or {}).get(
            "id"
        ),
        "respuesta": respuesta,
        "modo": contexto.modo,
        "acciones": [{"tipo": "continuar_flujo", "origen": origen}],
        "enlaces": [],
        "escalado": False,
        "cerrada": False,
        "enviado": envio.get("enviado"),
        "error": envio.get("error"),
        "pregunta_pendiente": pendiente,
        "tipo_chatbot": "inteligente",
        "modo_humano": False,
    }


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

    if pregunta and pregunta not in info and not _parece_instruccion_interna(pregunta):
        if pregunta.startswith("¿"):
            respuesta = f"{info}\n\nPara orientarte mejor, {pregunta}"
        else:
            respuesta = f"{info}\n\n{pregunta}"
    else:
        respuesta = info
    respuesta = _sanitizar_respuesta_usuario(respuesta)

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
    if pendiente and _parece_instruccion_interna(str(pendiente.get("texto") or "")):
        # Corregir pendientes corruptos con instrucciones internas.
        pendiente = _pendiente_desde_paso(contexto) or pendiente
        if pendiente and _parece_instruccion_interna(str(pendiente.get("texto") or "")):
            publico = _texto_publico_paso(contexto.paso)
            if publico:
                pendiente = dict(pendiente)
                pendiente["texto"] = publico

    if not pendiente:
        pendiente = _pendiente_desde_paso(contexto)
        if not pendiente:
            return None

    intencion = _detectar_intencion_interrupcion_informativa(texto_usuario)
    if not intencion or intencion not in INTERRUPCIONES_INFORMATIVAS:
        return None

    # Interrupción informativa: no ejecuta acciones de conversión.
    logger.info(
        "[CHATBOT_FLUJO] conversacion_id=%s accion=interrupcion_informativa "
        "paso_pendiente_id=%s intencion=%s",
        conversacion_id,
        pendiente.get("paso_id"),
        intencion,
    )

    info = _construir_texto_informativo_inteligente(
        contexto, intencion, texto_usuario
    )
    if not info:
        return None

    pregunta = str(pendiente.get("texto") or "").strip()
    if _parece_instruccion_interna(pregunta):
        pregunta = str(_texto_publico_paso(contexto.paso) or "").strip()
        if pregunta:
            pendiente = dict(pendiente)
            pendiente["texto"] = pregunta

    if pregunta and pregunta not in info and not _parece_instruccion_interna(pregunta):
        if pregunta.startswith("¿") or pregunta.endswith("?"):
            respuesta = f"{info}\n\nPara continuar, {pregunta}"
        else:
            respuesta = f"{info}\n\nPara continuar: {pregunta}"
    else:
        respuesta = info
    respuesta = _sanitizar_respuesta_usuario(respuesta)

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
                "pregunta_pendiente": {
                    "paso_id": pendiente.get("paso_id"),
                    "campo": pendiente.get("campo"),
                },
                "modo_humano": False,
            },
            default=None,
        )
        mensaje_saliente = _normalizar_fila_mensaje(mensaje_saliente)

    await _guardar_pregunta_pendiente(contexto, pendiente, dry_run=dry_run)

    logger.info(
        "[CHATBOT_FLUJO] conversacion_id=%s accion=retomar_paso paso_id=%s",
        conversacion_id,
        pendiente.get("paso_id"),
    )

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
            ctx_ok = _contexto_conversacion_dict(contexto.conversacion)
            if "intentos_pregunta_nivel" in ctx_ok:
                ctx_ok.pop("intentos_pregunta_nivel", None)
                contexto.conversacion["contexto"] = ctx_ok
                if not dry_run and contexto.conversacion_id:
                    await _db(
                        "actualizar_conversacion",
                        contexto.agencia_id,
                        contexto.conversacion_id,
                        {"contexto": ctx_ok},
                    )

    if not dry_run and contexto.conversacion_id:
        if resultado.campos_conversacion:
            await _db(
                "actualizar_conversacion",
                contexto.agencia_id,
                contexto.conversacion_id,
                resultado.campos_conversacion,
            )

        aspirante_id = contexto.aspirante_id
        if (
            resultado.persistir_nivel_estable
            and aspirante_id
            and resultado.campos_aspirante
        ):
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
    if not contexto.chatbot_configuracion_id:
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
    if not dry_run and contexto.conversacion_id:
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
        "[CHATBOT_FLUJO] conversacion_id=%s nivel=%s flujo_id=%s "
        "paso_actual_id=%s accion=flujo_seleccionado",
        contexto.conversacion_id,
        nivel_n,
        flujo_id,
        campos.get("paso_actual_id"),
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
    texto = _sanitizar_respuesta_usuario(texto)
    if dry_run:
        return {
            "enviado": True,
            "motivo": "simulacion",
            "dry_run": True,
            "mensaje_externo_id": None,
            "status_code": None,
            "requiere_reintento": False,
            "texto_sanitizado": texto,
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
