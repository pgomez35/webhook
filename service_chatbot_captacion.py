"""
Servicio — máquina de estados del Chatbot de captación.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from psycopg2.extras import RealDictCursor

from chatbot_captacion_logic import (
    BTN_CONTINUAR,
    BTN_DISP_NO,
    BTN_DISP_SI,
    BTN_EDAD_NO,
    BTN_EDAD_SI,
    BTN_PREGUNTAS,
    FAQ_PREFIX,
    enmascarar_telefono,
    interpretar_si_no,
    normalizar_usuario_plataforma,
    truncar_titulo_boton,
)
from DataBase import get_connection_chatbot_context
from enviar_msg_wp import enviar_botones_Completa, enviar_mensaje_texto_simple
import database_chatbot_captacion as db

logger = logging.getLogger("chatbot_captacion")

# Tipos Meta que no aportan texto útil en etapas que esperan input de texto
TIPOS_NO_TEXTO = frozenset(
    {
        "image",
        "audio",
        "video",
        "document",
        "sticker",
        "location",
        "contacts",
        "contact",
        "reaction",
        "unsupported",
        "order",
        "system",
        "unknown",
    }
)


def _es_mensaje_texto_util(tipo: Optional[str], texto: Optional[str]) -> bool:
    """True solo si el inbound es texto usable (no multimedia / contactos / etc.)."""
    t = (tipo or "").strip().lower()
    if not t or t in TIPOS_NO_TEXTO:
        return False
    if t != "text":
        # button / interactive se manejan por payload en otras etapas;
        # en esperando_usuario solo text.
        return False
    if texto is None:
        return False
    # Placeholders de normalización multimedia: "[image]", "[audio]", ...
    if str(texto).strip().startswith("[") and str(texto).strip().endswith("]"):
        return False
    return True


def faqs_activas(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    faqs = db.parse_faqs(config.get("preguntas_frecuentes"))
    activas = [f for f in faqs if f.get("activo") is True]
    activas.sort(key=lambda x: int(x.get("orden") or 0))
    return activas[:3]


def _enviar_texto(token: str, phone_number_id: str, wa_id: str, texto: str) -> None:
    enviar_mensaje_texto_simple(token, phone_number_id, wa_id, texto)


def _enviar_botones(
    token: str,
    phone_number_id: str,
    wa_id: str,
    texto: str,
    botones: List[Dict[str, str]],
) -> None:
    safe = [
        {"id": b["id"], "title": truncar_titulo_boton(b["title"])}
        for b in botones[:3]
    ]
    enviar_botones_Completa(token, phone_number_id, wa_id, texto, safe)


def _botones_si_no(id_si: str, id_no: str) -> List[Dict[str, str]]:
    return [
        {"id": id_si, "title": "Sí"},
        {"id": id_no, "title": "No"},
    ]


def _botones_menu(config: Dict[str, Any]) -> List[Dict[str, str]]:
    return [
        {
            "id": BTN_CONTINUAR,
            "title": truncar_titulo_boton(config.get("texto_boton_continuar") or "Continuar proceso"),
        },
        {
            "id": BTN_PREGUNTAS,
            "title": truncar_titulo_boton(config.get("texto_boton_preguntas") or "Tengo preguntas"),
        },
    ]


def _botones_faq(config: Dict[str, Any]) -> List[Dict[str, str]]:
    botones = []
    for faq in faqs_activas(config):
        faq_id = str(faq.get("id") or "").strip()
        titulo = truncar_titulo_boton(str(faq.get("titulo") or "FAQ"))
        if not faq_id:
            continue
        botones.append({"id": f"{FAQ_PREFIX}{faq_id}", "title": titulo})
    return botones


def _mensaje_proceso_cerrado(etapa: str) -> str:
    if etapa == "rechazado":
        return "Tu proceso ya fue cerrado. Si necesitas ayuda, contacta a la agencia."
    return "Tu proceso ya fue completado. Si necesitas ayuda, contacta a la agencia."


def _reenviar_pregunta_actual(
    config: Dict[str, Any],
    aspirante: Dict[str, Any],
    token: str,
    phone_number_id: str,
    wa_id: str,
) -> None:
    etapa = aspirante.get("etapa_chatbot")
    error = config.get("mensaje_error") or "No pudimos procesar tu respuesta. Por favor, intenta nuevamente."

    if etapa == "esperando_usuario":
        _enviar_texto(token, phone_number_id, wa_id, error)
        _enviar_texto(token, phone_number_id, wa_id, config["pregunta_usuario"])
    elif etapa == "esperando_mayor_edad":
        _enviar_texto(token, phone_number_id, wa_id, error)
        _enviar_botones(
            token,
            phone_number_id,
            wa_id,
            config["pregunta_mayor_edad"],
            _botones_si_no(BTN_EDAD_SI, BTN_EDAD_NO),
        )
    elif etapa == "esperando_disponibilidad":
        _enviar_texto(token, phone_number_id, wa_id, error)
        _enviar_botones(
            token,
            phone_number_id,
            wa_id,
            config["pregunta_disponibilidad"],
            _botones_si_no(BTN_DISP_SI, BTN_DISP_NO),
        )
    elif etapa in ("menu_principal", "preguntas_frecuentes"):
        _enviar_texto(token, phone_number_id, wa_id, error)
        _enviar_botones(
            token,
            phone_number_id,
            wa_id,
            config["mensaje_aprobado"],
            _botones_menu(config),
        )
    else:
        _enviar_texto(token, phone_number_id, wa_id, error)


def _manejar_continuar(
    cur,
    config: Dict[str, Any],
    aspirante: Dict[str, Any],
    token: str,
    phone_number_id: str,
    wa_id: str,
    message_id_meta: Optional[str],
) -> None:
    accion = (config.get("accion_continuar") or "asesor").strip()
    campos: Dict[str, Any] = {"ultimo_message_id_meta": message_id_meta}

    if accion == "asesor":
        campos.update(
            {
                "requiere_asesor": True,
                "estado": "pendiente_asesor",
                "etapa_chatbot": "pendiente_asesor",
            }
        )
        db.actualizar_aspirante_flujo(cur, aspirante["id"], campos)
        _enviar_texto(
            token,
            phone_number_id,
            wa_id,
            "Gracias. Un asesor continuará tu atención pronto.",
        )
    elif accion == "url":
        campos.update({"estado": "completado", "etapa_chatbot": "completado"})
        db.actualizar_aspirante_flujo(cur, aspirante["id"], campos)
        _enviar_texto(
            token,
            phone_number_id,
            wa_id,
            f"Continúa tu proceso aquí: {config.get('url_continuar')}",
        )
    elif accion == "agendamiento":
        campos.update({"estado": "completado", "etapa_chatbot": "completado"})
        db.actualizar_aspirante_flujo(cur, aspirante["id"], campos)
        _enviar_texto(
            token,
            phone_number_id,
            wa_id,
            f"Agenda tu cita aquí: {config.get('url_continuar')}",
        )
    else:  # finalizar
        campos.update({"estado": "completado", "etapa_chatbot": "finalizado"})
        db.actualizar_aspirante_flujo(cur, aspirante["id"], campos)
        _enviar_texto(
            token,
            phone_number_id,
            wa_id,
            "Proceso finalizado. ¡Gracias por tu interés!",
        )


def _manejar_preguntas(
    config: Dict[str, Any],
    token: str,
    phone_number_id: str,
    wa_id: str,
) -> None:
    botones = _botones_faq(config)
    if not botones:
        _enviar_texto(
            token,
            phone_number_id,
            wa_id,
            "Por ahora no hay preguntas frecuentes activas.",
        )
        _enviar_botones(
            token,
            phone_number_id,
            wa_id,
            config["mensaje_aprobado"],
            _botones_menu(config),
        )
        return

    _enviar_botones(
        token,
        phone_number_id,
        wa_id,
        "Elige una pregunta:",
        botones,
    )


def _manejar_faq_seleccionada(
    config: Dict[str, Any],
    payload_id: str,
    token: str,
    phone_number_id: str,
    wa_id: str,
) -> bool:
    if not payload_id.startswith(FAQ_PREFIX):
        return False
    faq_id = payload_id[len(FAQ_PREFIX):].strip()
    faqs = db.parse_faqs(config.get("preguntas_frecuentes"))
    encontrada = None
    for f in faqs:
        if str(f.get("id") or "").strip() == faq_id and f.get("activo") is True:
            encontrada = f
            break
    if not encontrada:
        return False

    _enviar_texto(token, phone_number_id, wa_id, str(encontrada.get("respuesta") or ""))
    _enviar_botones(
        token,
        phone_number_id,
        wa_id,
        "¿Deseas continuar o ver más preguntas?",
        _botones_menu(config),
    )
    return True


def procesar_chatbot_captacion(
    *,
    agencia_id: Optional[int],
    whatsapp_account_id: Optional[int],
    wa_id: str,
    tipo: Optional[str],
    texto: Optional[str],
    payload_id: Optional[str],
    phone_number_id: str,
    token: str,
    message_id_meta: Optional[str],
) -> bool:
    """
    Procesa un mensaje del chatbot de captación.
    Retorna True si el mensaje fue consumido por el chatbot.
    Retorna False si no hay config activa (continuar flujo Talentum).
    """
    if not agencia_id or not whatsapp_account_id or not wa_id:
        return False

    etapa_anterior = None
    etapa_nueva = None

    try:
        config = db.obtener_configuracion_activa(agencia_id)
        if not config:
            return False

        telefono = str(wa_id).strip()

        with get_connection_chatbot_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                aspirante = db.aspirante_for_update(cur, agencia_id, telefono)

                if not aspirante:
                    aspirante = db.crear_aspirante(
                        cur,
                        agencia_id=agencia_id,
                        whatsapp_account_id=whatsapp_account_id,
                        telefono=telefono,
                        message_id_meta=None,
                    )
                    # Re-lock
                    aspirante = db.aspirante_for_update(cur, agencia_id, telefono)

                etapa_anterior = aspirante.get("etapa_chatbot")

                # Idempotencia por message_id_meta
                if (
                    message_id_meta
                    and aspirante.get("ultimo_message_id_meta")
                    and aspirante["ultimo_message_id_meta"] == message_id_meta
                ):
                    logger.info(
                        "chatbot idempotente agencia=%s wa=%s msg=%s",
                        agencia_id,
                        enmascarar_telefono(telefono),
                        message_id_meta,
                    )
                    return True

                etapa = aspirante.get("etapa_chatbot") or "inicio"

                # Procesos cerrados
                if etapa in ("rechazado", "finalizado", "completado", "pendiente_asesor"):
                    # Permitir menú solo en menu_principal; completado/finalizado/etc. informan
                    if etapa == "completado" and (payload_id in (BTN_CONTINUAR, BTN_PREGUNTAS) or (payload_id or "").startswith(FAQ_PREFIX)):
                        pass  # raro; tratar abajo vía menu si aún estuviera
                    else:
                        _enviar_texto(
                            token,
                            phone_number_id,
                            telefono,
                            _mensaje_proceso_cerrado(etapa),
                        )
                        db.actualizar_aspirante_flujo(
                            cur,
                            aspirante["id"],
                            {"ultimo_message_id_meta": message_id_meta},
                        )
                        etapa_nueva = etapa
                        logger.info(
                            "chatbot cerrado agencia=%s account=%s tel=%s tipo=%s payload=%s etapa=%s",
                            agencia_id,
                            whatsapp_account_id,
                            enmascarar_telefono(telefono),
                            tipo,
                            payload_id,
                            etapa,
                        )
                        return True

                # Primer contacto / inicio
                if etapa in ("inicio", None):
                    _enviar_texto(token, phone_number_id, telefono, config["mensaje_bienvenida"])
                    _enviar_texto(token, phone_number_id, telefono, config["pregunta_usuario"])
                    aspirante = db.actualizar_aspirante_flujo(
                        cur,
                        aspirante["id"],
                        {
                            "estado": "en_proceso",
                            "etapa_chatbot": "esperando_usuario",
                            "whatsapp_account_id": whatsapp_account_id,
                            "ultimo_message_id_meta": message_id_meta,
                        },
                    )
                    etapa_nueva = "esperando_usuario"
                    logger.info(
                        "chatbot inicio agencia=%s account=%s tel=%s %s→%s",
                        agencia_id,
                        whatsapp_account_id,
                        enmascarar_telefono(telefono),
                        etapa_anterior,
                        etapa_nueva,
                    )
                    return True

                if etapa == "esperando_usuario":
                    # Solo texto libre. image/audio/contact/location/etc. → inválida, sin avanzar.
                    if not _es_mensaje_texto_util(tipo, texto):
                        logger.info(
                            "chatbot respuesta inválida (tipo=%s) agencia=%s tel=%s etapa=%s",
                            tipo,
                            agencia_id,
                            enmascarar_telefono(telefono),
                            etapa,
                        )
                        _reenviar_pregunta_actual(config, aspirante, token, phone_number_id, telefono)
                        db.actualizar_aspirante_flujo(
                            cur, aspirante["id"], {"ultimo_message_id_meta": message_id_meta}
                        )
                        return True

                    usuario = normalizar_usuario_plataforma(texto)
                    if not usuario:
                        _reenviar_pregunta_actual(config, aspirante, token, phone_number_id, telefono)
                        db.actualizar_aspirante_flujo(
                            cur, aspirante["id"], {"ultimo_message_id_meta": message_id_meta}
                        )
                        return True

                    db.actualizar_aspirante_flujo(
                        cur,
                        aspirante["id"],
                        {
                            "usuario_plataforma": usuario,
                            "etapa_chatbot": "esperando_mayor_edad",
                            "ultimo_message_id_meta": message_id_meta,
                        },
                    )
                    _enviar_botones(
                        token,
                        phone_number_id,
                        telefono,
                        config["pregunta_mayor_edad"],
                        _botones_si_no(BTN_EDAD_SI, BTN_EDAD_NO),
                    )
                    etapa_nueva = "esperando_mayor_edad"
                    logger.info(
                        "chatbot usuario ok agencia=%s tel=%s %s→%s",
                        agencia_id,
                        enmascarar_telefono(telefono),
                        etapa_anterior,
                        etapa_nueva,
                    )
                    return True

                if etapa == "esperando_mayor_edad":
                    respuesta = interpretar_si_no(payload_id, texto, BTN_EDAD_SI, BTN_EDAD_NO)
                    if respuesta is None:
                        _reenviar_pregunta_actual(config, aspirante, token, phone_number_id, telefono)
                        db.actualizar_aspirante_flujo(
                            cur, aspirante["id"], {"ultimo_message_id_meta": message_id_meta}
                        )
                        return True

                    if respuesta is False:
                        db.actualizar_aspirante_flujo(
                            cur,
                            aspirante["id"],
                            {
                                "mayor_edad": False,
                                "cumple_requisitos": False,
                                "estado": "descartado",
                                "etapa_chatbot": "rechazado",
                                "ultimo_message_id_meta": message_id_meta,
                            },
                        )
                        _enviar_texto(
                            token, phone_number_id, telefono, config["mensaje_no_aprobado"]
                        )
                        etapa_nueva = "rechazado"
                        return True

                    db.actualizar_aspirante_flujo(
                        cur,
                        aspirante["id"],
                        {
                            "mayor_edad": True,
                            "etapa_chatbot": "esperando_disponibilidad",
                            "ultimo_message_id_meta": message_id_meta,
                        },
                    )
                    _enviar_botones(
                        token,
                        phone_number_id,
                        telefono,
                        config["pregunta_disponibilidad"],
                        _botones_si_no(BTN_DISP_SI, BTN_DISP_NO),
                    )
                    etapa_nueva = "esperando_disponibilidad"
                    return True

                if etapa == "esperando_disponibilidad":
                    respuesta = interpretar_si_no(payload_id, texto, BTN_DISP_SI, BTN_DISP_NO)
                    if respuesta is None:
                        _reenviar_pregunta_actual(config, aspirante, token, phone_number_id, telefono)
                        db.actualizar_aspirante_flujo(
                            cur, aspirante["id"], {"ultimo_message_id_meta": message_id_meta}
                        )
                        return True

                    mayor = bool(aspirante.get("mayor_edad"))
                    cumple = bool(mayor and respuesta)

                    if not cumple:
                        db.actualizar_aspirante_flujo(
                            cur,
                            aspirante["id"],
                            {
                                "disponibilidad_live": bool(respuesta),
                                "cumple_requisitos": False,
                                "estado": "descartado",
                                "etapa_chatbot": "rechazado",
                                "ultimo_message_id_meta": message_id_meta,
                            },
                        )
                        _enviar_texto(
                            token, phone_number_id, telefono, config["mensaje_no_aprobado"]
                        )
                        etapa_nueva = "rechazado"
                        return True

                    db.actualizar_aspirante_flujo(
                        cur,
                        aspirante["id"],
                        {
                            "disponibilidad_live": True,
                            "cumple_requisitos": True,
                            "estado": "completado",
                            "etapa_chatbot": "menu_principal",
                            "ultimo_message_id_meta": message_id_meta,
                        },
                    )
                    _enviar_botones(
                        token,
                        phone_number_id,
                        telefono,
                        config["mensaje_aprobado"],
                        _botones_menu(config),
                    )
                    etapa_nueva = "menu_principal"
                    return True

                if etapa in ("menu_principal", "preguntas_frecuentes"):
                    if payload_id == BTN_CONTINUAR:
                        _manejar_continuar(
                            cur, config, aspirante, token, phone_number_id, telefono, message_id_meta
                        )
                        return True

                    if payload_id == BTN_PREGUNTAS:
                        db.actualizar_aspirante_flujo(
                            cur,
                            aspirante["id"],
                            {
                                "etapa_chatbot": "preguntas_frecuentes",
                                "ultimo_message_id_meta": message_id_meta,
                            },
                        )
                        _manejar_preguntas(config, token, phone_number_id, telefono)
                        return True

                    if payload_id and payload_id.startswith(FAQ_PREFIX):
                        ok = _manejar_faq_seleccionada(
                            config, payload_id, token, phone_number_id, telefono
                        )
                        db.actualizar_aspirante_flujo(
                            cur,
                            aspirante["id"],
                            {
                                "etapa_chatbot": "menu_principal",
                                "ultimo_message_id_meta": message_id_meta,
                            },
                        )
                        if not ok:
                            _reenviar_pregunta_actual(
                                config, aspirante, token, phone_number_id, telefono
                            )
                        return True

                    _reenviar_pregunta_actual(config, aspirante, token, phone_number_id, telefono)
                    db.actualizar_aspirante_flujo(
                        cur, aspirante["id"], {"ultimo_message_id_meta": message_id_meta}
                    )
                    return True

                # Etapa desconocida: consumir sin romper webhook
                _enviar_texto(
                    token,
                    phone_number_id,
                    telefono,
                    config.get("mensaje_error")
                    or "No pudimos procesar tu respuesta. Por favor, intenta nuevamente.",
                )
                db.actualizar_aspirante_flujo(
                    cur, aspirante["id"], {"ultimo_message_id_meta": message_id_meta}
                )
                return True

    except Exception as e:
        logger.exception(
            "Error interno chatbot_captacion agencia=%s account=%s tel=%s: %s",
            agencia_id,
            whatsapp_account_id,
            enmascarar_telefono(wa_id),
            e,
        )
        # No destruir el webhook ni forzar flujo Talentum
        return True

    finally:
        if etapa_nueva and etapa_anterior != etapa_nueva:
            logger.info(
                "chatbot resultado agencia=%s account=%s tel=%s tipo=%s payload=%s %s→%s",
                agencia_id,
                whatsapp_account_id,
                enmascarar_telefono(wa_id),
                tipo,
                payload_id,
                etapa_anterior,
                etapa_nueva,
            )
