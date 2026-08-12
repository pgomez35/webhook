"""
Motor INTELIGENTE V2 — entrada pública.

Pipeline:
  mensaje → interpretación → reducir estado → decisión única → respuesta

Feature flag interno:
  CHATBOT_INTELIGENTE_V2=0  → rollback a legacy (dispatcher)
  default = 1 (activo)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, Optional

import chatbot_conversacional_db_gateway as gw
from chatbot_conversacional_perfil import normalizar_json_safe
from chatbot_envio_whatsapp import fijar_conversacion_id_envio
from chatbot_inteligente_v2_core import DEC_ASK_DATA, DEC_BLOCKED

logger = logging.getLogger("uvicorn.error")

EnviarCallback = Callable[[str], Any]


async def _db(nombre: str, *args: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(gw.call_opcional, nombre, *args, **kwargs)


async def _persistir_contexto(
    *,
    agencia_id: int,
    conversacion_id: int,
    conversacion: Dict[str, Any],
) -> bool:
    from chatbot_inteligente_v2_core import escribir_estado_v2

    # estado already written into conversacion by caller
    ctx = normalizar_json_safe(conversacion.get("contexto") or {})
    conversacion["contexto"] = ctx
    try:
        resultado = await asyncio.to_thread(
            gw.call,
            "actualizar_conversacion",
            agencia_id,
            conversacion_id,
            {"contexto": ctx},
        )
        ok = resultado is not None
        logger.info(
            "[CHATBOT_V2_PERSISTENCIA] conversacion_id=%s resultado=%s",
            conversacion_id,
            "ok" if ok else "error",
        )
        return ok
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[CHATBOT_V2_PERSISTENCIA] conversacion_id=%s resultado=error detalle=%s",
            conversacion_id,
            str(exc)[:300],
        )
        return False


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
    from chatbot_inteligente_v2_core import sanitizar_respuesta_publica

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
            logger.error("[CHATBOT_V2_OUTPUT] callback_error=%s", exc)
            return {"enviado": False, "error": str(exc)[:300]}

    if canal == "whatsapp" and token and phone_number_id and destino:
        from chatbot_envio_whatsapp import enviar_whatsapp_texto_meta

        return await enviar_whatsapp_texto_meta(
            token=token,
            phone_number_id=phone_number_id,
            destino=destino,
            texto=texto,
            conversacion_id=conversacion_id,
        )
    return {"enviado": False, "error": "sin_canal"}


async def procesar_mensaje_inteligente_v2(
    *,
    agencia_id: int,
    texto: str,
    usuario_externo_id: str,
    chatbot_configuracion_id: int,
    canal: str = "whatsapp",
    cuenta_externa_id: Optional[str] = None,
    telefono: Optional[str] = None,
    nombre_contacto: Optional[str] = None,
    mensaje_externo_id: Optional[str] = None,
    aspirante_id: Optional[int] = None,
    campania_id: Optional[int] = None,
    token: Optional[str] = None,
    phone_number_id: Optional[str] = None,
    wa_id: Optional[str] = None,
    enviar_callback: Optional[EnviarCallback] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    from chatbot_inteligente_v2_core import (
        escribir_estado_v2,
        interpretar_mensaje_v2,
        leer_estado_v2,
        reducir_estado,
        resolver_decision_turno,
        sanitizar_respuesta_publica,
    )

    logger.info(
        "[CHATBOT_V2_INPUT] agencia_id=%s cfg=%s canal=%s texto_len=%s",
        agencia_id,
        chatbot_configuracion_id,
        canal,
        len(texto or ""),
    )

    if not gw.disponible():
        return {"usado": False, "motivo": "db_no_disponible", "motor": "inteligente_v2"}

    conversacion = await _db(
        "obtener_o_crear_conversacion",
        agencia_id,
        canal=canal,
        usuario_externo_id=usuario_externo_id,
        cuenta_externa_id=cuenta_externa_id,
        chatbot_configuracion_id=chatbot_configuracion_id,
        aspirante_id=aspirante_id,
        telefono=telefono or wa_id,
        nombre_contacto=nombre_contacto,
        campania_id=campania_id,
        default=None,
    )
    if isinstance(conversacion, tuple):
        conversacion = conversacion[0] if conversacion else None
    if not isinstance(conversacion, dict):
        return {"usado": False, "motivo": "conversacion_no_disponible", "motor": "inteligente_v2"}

    conversacion_id = conversacion.get("id")
    fijar_conversacion_id_envio(conversacion_id)
    logger.info("[CHATBOT_V2_INPUT] conversacion_id=%s", conversacion_id)

    # Idempotencia básica
    if mensaje_externo_id and conversacion_id:
        existente = await _db(
            "obtener_mensaje_por_externo_id",
            agencia_id,
            conversacion_id,
            mensaje_externo_id,
            default=None,
        )
        if existente:
            return {
                "usado": False,
                "motivo": "mensaje_duplicado",
                "conversacion_id": conversacion_id,
                "motor": "inteligente_v2",
            }

    if not dry_run and conversacion_id:
        await _db(
            "insertar_mensaje",
            agencia_id,
            conversacion_id,
            canal=canal,
            direccion="entrante",
            remitente_tipo="aspirante",
            tipo_mensaje="texto",
            texto=texto or "",
            mensaje_externo_id=mensaje_externo_id,
            default=None,
        )

    # Catálogos (firmas reales: sin `limite=` incompatible)
    requisitos = await _db(
        "listar_requisitos",
        agencia_id,
        chatbot_configuracion_id=chatbot_configuracion_id,
        default=[],
    ) or []
    beneficios = await _db(
        "listar_beneficios_vigentes",
        agencia_id,
        chatbot_configuracion_id,
        campania_id,
        default=[],
    ) or []
    faqs = await _db(
        "listar_faq",
        agencia_id,
        chatbot_configuracion_id=chatbot_configuracion_id,
        default=[],
    ) or []

    aspirante = None
    if aspirante_id:
        aspirante = await _db("obtener_aspirante", agencia_id, aspirante_id, default=None)

    # Modo humano → no responder IA
    if conversacion.get("modo_humano") or conversacion.get("ia_habilitada") is False:
        return {
            "usado": False,
            "motivo": "atencion_humana" if conversacion.get("modo_humano") else "ia_deshabilitada",
            "conversacion_id": conversacion_id,
            "motor": "inteligente_v2",
        }

    estado_prev = leer_estado_v2(conversacion)
    # Hidratar edad/mayor desde aspirante si existe
    if isinstance(aspirante, dict):
        if aspirante.get("mayor_edad") is not None and estado_prev["profile"].get("mayor_edad") is None:
            estado_prev["profile"]["mayor_edad"] = bool(aspirante.get("mayor_edad"))

    interp = interpretar_mensaje_v2(
        texto or "",
        estado=estado_prev,
        pending=estado_prev.get("pending_requirement"),
    )
    logger.info(
        "[CHATBOT_V2_INTERPRETATION] intent=%s questions=%s facts=%s "
        "answer_to_pending=%s subject=%s contradiction=%s",
        interp.intent,
        [q.get("intent") for q in interp.questions],
        list((interp.facts or {}).keys()),
        interp.answer_to_pending,
        interp.subject,
        bool(interp.contradiction),
    )

    estado = reducir_estado(estado_prev, interp, requisitos=requisitos)
    logger.info(
        "[CHATBOT_V2_PROFILE] edad=%s mayor_edad=%s live_count=%s hours=%s days=%s "
        "device=%s internet=%s interest=%s traits=%s",
        estado["profile"].get("edad"),
        estado["profile"].get("mayor_edad"),
        estado["profile"].get("live_count"),
        estado["profile"].get("hours_per_day"),
        estado["profile"].get("days_per_week"),
        estado["profile"].get("device_os"),
        estado["profile"].get("internet_speed_mbps"),
        estado["profile"].get("interest"),
        estado["profile"].get("personality_traits"),
    )
    logger.info(
        "[CHATBOT_V2_REQUIREMENTS] blockers=%s puede_incorporarse=%s",
        estado.get("blockers"),
        (estado.get("eligibility") or {}).get("puede_incorporarse"),
    )
    logger.info(
        "[CHATBOT_V2_STATE] previous=%s current=%s blockers=%s pending=%s",
        estado_prev.get("macro_state"),
        estado.get("macro_state"),
        estado.get("blockers"),
        (estado.get("pending_requirement") or {}).get("code"),
    )

    decision = resolver_decision_turno(
        interpretacion=interp,
        estado=estado,
        requisitos=requisitos,
        beneficios=beneficios,
        faqs=faqs,
    )

    # Aplicar pending de la decisión
    if decision.cancel_pending:
        estado["pending_requirement"] = None
    if decision.type == DEC_ASK_DATA and decision.required_input:
        estado["pending_requirement"] = decision.required_input
    estado["last_decision_type"] = decision.type

    escribir_estado_v2(conversacion, estado)
    if not dry_run and conversacion_id:
        await _persistir_contexto(
            agencia_id=agencia_id,
            conversacion_id=int(conversacion_id),
            conversacion=conversacion,
        )
        # Sync mayor_edad a aspirante si cambió
        if aspirante_id and "mayor_edad" in (interp.facts or {}):
            await _db(
                "actualizar_datos_explicitos_aspirante",
                agencia_id,
                int(aspirante_id),
                {"mayor_edad": bool(interp.facts.get("mayor_edad"))},
                default=None,
            )

    logger.info(
        "[CHATBOT_V2_DECISION] type=%s reason=%s required_input=%s action=%s",
        decision.type,
        decision.reason,
        (decision.required_input or {}).get("code"),
        decision.action,
    )
    # Tools de incorporación: fase posterior (no en núcleo inicial)
    logger.info("[CHATBOT_V2_TOOL] skipped=phase1_evaluation_only")

    respuesta = sanitizar_respuesta_publica(decision.public_content)
    logger.info(
        "[CHATBOT_V2_OUTPUT] type=%s len=%s conversacion_id=%s",
        decision.type,
        len(respuesta or ""),
        conversacion_id,
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

    if not dry_run and conversacion_id and respuesta:
        await _db(
            "insertar_mensaje",
            agencia_id,
            conversacion_id,
            canal=canal,
            direccion="saliente",
            remitente_tipo="chatbot",
            tipo_mensaje="texto",
            texto=respuesta,
            default=None,
        )

    return {
        "usado": True,
        "motivo": decision.reason,
        "conversacion_id": conversacion_id,
        "respuesta": respuesta,
        "enviado": envio.get("enviado"),
        "error": envio.get("error"),
        "tipo_chatbot": "inteligente",
        "motor": "inteligente_v2",
        "decision": decision.to_dict(),
        "interpretation": interp.to_dict(),
        "state": {
            "macro_state": estado.get("macro_state"),
            "blockers": estado.get("blockers"),
            "profile": estado.get("profile"),
        },
        "action_gate": {
            "action": decision.action,
            "blocked": decision.type == DEC_BLOCKED,
        },
    }
