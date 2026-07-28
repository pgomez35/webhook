"""
Servicio — máquina de estados del Chatbot de captación.

Orden obligatorio:
1) persistir estado en chatbot.chatbot_aspirantes (commit)
2) enviar mensajes WhatsApp

Así un fallo de Meta o de UPDATE no deja bienvenida enviada sin fila persistida.
"""
from __future__ import annotations

import logging
import traceback
from typing import Any, Dict, List, Optional

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
    normalizar_telefono_chatbot,
    normalizar_usuario_plataforma,
    truncar_titulo_boton,
)
from enviar_msg_wp import (
    enviar_botones_Completa,
    enviar_documento_whatsapp,
    enviar_mensaje_texto_simple,
    enviar_video_whatsapp,
)
import database_chatbot_captacion as db

logger = logging.getLogger("chatbot_captacion")

TIPOS_NO_TEXTO = frozenset(
    {
        "image",
        "audio",
        "video",
        "document",
        "sticker",
        "location",
        "contacts",
        "reaction",
    }
)

ETAPAS_CERRADAS = frozenset(
    {"rechazado", "finalizado", "completado", "pendiente_asesor"}
)


def _es_mensaje_texto_util(tipo: Optional[str], texto: Optional[str]) -> bool:
    if (tipo or "").strip().lower() in TIPOS_NO_TEXTO:
        return False
    if (tipo or "").strip().lower() in ("button", "interactive"):
        return False
    return bool((texto or "").strip())


def faqs_activas(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    faqs = db.parse_faqs(config.get("preguntas_frecuentes"))
    activas = [f for f in faqs if f.get("activo") is True]
    activas.sort(key=lambda x: int(x.get("orden") or 0))
    return activas[:3]


def _enviar_texto(token: str, phone_number_id: str, wa_id: str, texto: str) -> None:
    enviar_mensaje_texto_simple(token, phone_number_id, wa_id, texto)


def _recursos_activos_ordenados(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    recursos = db.parse_recursos_bienvenida(config.get("recursos_bienvenida"))
    activos = [r for r in recursos if r.get("activo") is True]
    activos.sort(key=lambda x: int(x.get("orden") or 0))
    return activos[:2]


def _enviar_recursos_bienvenida(
    config: Dict[str, Any],
    token: str,
    phone_number_id: str,
    wa_id: str,
) -> None:
    for recurso in _recursos_activos_ordenados(config):
        tipo = (recurso.get("tipo") or "").strip().lower()
        url = (recurso.get("secure_url") or recurso.get("url") or "").strip()
        caption = (recurso.get("caption") or "").strip() or None
        rid = recurso.get("id")

        if not url.startswith("https://"):
            logger.warning(
                "chatbot recurso inválido id=%s tipo=%s (URL no https)",
                rid,
                tipo,
            )
            continue

        try:
            if tipo == "video":
                status, body = enviar_video_whatsapp(
                    token=token,
                    numero_id=phone_number_id,
                    telefono_destino=wa_id,
                    video_url=url,
                    caption=caption,
                )
            elif tipo == "document":
                filename = (recurso.get("nombre_archivo") or "documento.pdf").strip()
                status, body = enviar_documento_whatsapp(
                    token=token,
                    numero_id=phone_number_id,
                    telefono_destino=wa_id,
                    documento_url=url,
                    caption=caption,
                    filename=filename,
                )
            else:
                continue

            if status not in (200, 201):
                partes = [p for p in (caption, url) if p]
                if partes:
                    _enviar_texto(token, phone_number_id, wa_id, "\n\n".join(partes))
        except Exception as e:
            logger.warning(
                "chatbot excepción media id=%s tipo=%s: %s",
                rid,
                tipo,
                e,
            )


def _enviar_botones(
    token: str,
    phone_number_id: str,
    wa_id: str,
    cuerpo: str,
    botones: List[Dict[str, str]],
) -> None:
    if not botones:
        _enviar_texto(token, phone_number_id, wa_id, cuerpo)
        return
    enviar_botones_Completa(
        token,
        phone_number_id,
        wa_id,
        cuerpo,
        botones,
    )


def _botones_si_no(id_si: str, id_no: str) -> List[Dict[str, str]]:
    return [
        {"id": id_si, "title": truncar_titulo_boton("Sí")},
        {"id": id_no, "title": truncar_titulo_boton("No")},
    ]


def _botones_menu(config: Dict[str, Any]) -> List[Dict[str, str]]:
    botones = [
        {
            "id": BTN_CONTINUAR,
            "title": truncar_titulo_boton(
                str(config.get("texto_boton_continuar") or "Continuar")
            ),
        },
        {
            "id": BTN_PREGUNTAS,
            "title": truncar_titulo_boton(
                str(config.get("texto_boton_preguntas") or "Preguntas")
            ),
        },
    ]
    return botones


def _botones_faqs(config: Dict[str, Any]) -> List[Dict[str, str]]:
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
    error = config.get("mensaje_error") or (
        "No pudimos procesar tu respuesta. Por favor, intenta nuevamente."
    )

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
        db.actualizar_aspirante_flujo_commit(aspirante["id"], campos)
        _enviar_texto(
            token,
            phone_number_id,
            wa_id,
            "Gracias. Un asesor continuará tu atención pronto.",
        )
    elif accion == "url":
        campos.update({"estado": "completado", "etapa_chatbot": "completado"})
        db.actualizar_aspirante_flujo_commit(aspirante["id"], campos)
        _enviar_texto(
            token,
            phone_number_id,
            wa_id,
            f"Continúa tu proceso aquí: {config.get('url_continuar')}",
        )
    elif accion == "agendamiento":
        campos.update({"estado": "completado", "etapa_chatbot": "completado"})
        db.actualizar_aspirante_flujo_commit(aspirante["id"], campos)
        _enviar_texto(
            token,
            phone_number_id,
            wa_id,
            f"Agenda tu cita aquí: {config.get('url_continuar')}",
        )
    else:
        campos.update({"estado": "completado", "etapa_chatbot": "finalizado"})
        db.actualizar_aspirante_flujo_commit(aspirante["id"], campos)
        _enviar_texto(
            token,
            phone_number_id,
            wa_id,
            "Gracias por completar el proceso.",
        )


def _manejar_preguntas(
    config: Dict[str, Any],
    token: str,
    phone_number_id: str,
    wa_id: str,
) -> None:
    faqs = faqs_activas(config)
    if not faqs:
        _enviar_texto(
            token,
            phone_number_id,
            wa_id,
            "Por ahora no hay preguntas frecuentes disponibles.",
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
        _botones_faqs(config),
    )


def _manejar_faq_seleccionada(
    config: Dict[str, Any],
    payload_id: str,
    token: str,
    phone_number_id: str,
    wa_id: str,
) -> bool:
    faq_id = payload_id[len(FAQ_PREFIX) :].strip()
    encontrada = None
    for f in faqs_activas(config):
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

    Siempre retorna True cuando el producto chatbot atendió el mensaje
    (éxito o error controlado), para no caer a Talentum Manager.
    """
    if not agencia_id:
        logger.error("[CHATBOT] agencia_id ausente")
        return True
    if not whatsapp_account_id:
        logger.error("[CHATBOT] whatsapp_account_id ausente agencia_id=%s", agencia_id)
        return True
    if not wa_id:
        logger.error("[CHATBOT] wa_id ausente agencia_id=%s", agencia_id)
        return True

    telefono = normalizar_telefono_chatbot(wa_id)
    if not telefono:
        logger.error("[CHATBOT] teléfono vacío tras normalizar wa_id=%s", wa_id)
        return True

    etapa_anterior = None
    etapa_nueva = None

    try:
        config = db.obtener_configuracion_activa(agencia_id)
        if not config:
            logger.warning(
                "[CHATBOT] sin configuración activa agencia_id=%s — mensaje consumido",
                agencia_id,
            )
            return True

        logger.info(
            "[CHATBOT] entrada agencia_id=%s whatsapp_account_id=%s "
            "telefono=%s tipo=%s",
            agencia_id,
            whatsapp_account_id,
            enmascarar_telefono(telefono),
            tipo,
        )

        # --- Persistencia previa (commit) ---
        try:
            aspirante = db.crear_o_obtener_aspirante(
                agencia_id=agencia_id,
                whatsapp_account_id=whatsapp_account_id,
                telefono=telefono,
            )
        except Exception:
            logger.exception(
                "[CHATBOT] fallo al crear/obtener aspirante agencia_id=%s tel=%s",
                agencia_id,
                enmascarar_telefono(telefono),
            )
            traceback.print_exc()
            return True

        logger.info(
            "[CHATBOT] aspirante id=%s etapa=%s estado=%s",
            aspirante.get("id"),
            aspirante.get("etapa_chatbot"),
            aspirante.get("estado"),
        )

        etapa_anterior = aspirante.get("etapa_chatbot") or "inicio"

        if (
            message_id_meta
            and aspirante.get("ultimo_message_id_meta")
            and aspirante["ultimo_message_id_meta"] == message_id_meta
        ):
            logger.info(
                "[CHATBOT] idempotente agencia=%s tel=%s msg=%s",
                agencia_id,
                enmascarar_telefono(telefono),
                message_id_meta,
            )
            return True

        etapa = aspirante.get("etapa_chatbot") or "inicio"
        logger.info("[CHATBOT] pregunta_actual/etapa=%s", etapa)

        # --- Procesos cerrados ---
        if etapa in ETAPAS_CERRADAS:
            try:
                db.actualizar_aspirante_flujo_commit(
                    aspirante["id"],
                    {"ultimo_message_id_meta": message_id_meta},
                )
            except Exception:
                traceback.print_exc()
            _enviar_texto(
                token,
                phone_number_id,
                telefono,
                _mensaje_proceso_cerrado(etapa),
            )
            return True

        # --- Primer contacto: persistir avance ANTES de enviar ---
        if etapa in ("inicio", None):
            try:
                aspirante = db.actualizar_aspirante_flujo_commit(
                    aspirante["id"],
                    {
                        "estado": "en_proceso",
                        "etapa_chatbot": "esperando_usuario",
                        "whatsapp_account_id": whatsapp_account_id,
                        "ultimo_message_id_meta": message_id_meta,
                    },
                )
            except Exception:
                logger.exception(
                    "[CHATBOT] no se pudo persistir inicio; no se envía bienvenida"
                )
                traceback.print_exc()
                return True

            logger.info(
                "[CHATBOT] aspirante creado/actualizado id=%s etapa→esperando_usuario",
                aspirante.get("id"),
            )
            _enviar_texto(
                token, phone_number_id, telefono, config["mensaje_bienvenida"]
            )
            _enviar_recursos_bienvenida(config, token, phone_number_id, telefono)
            _enviar_texto(
                token, phone_number_id, telefono, config["pregunta_usuario"]
            )
            etapa_nueva = "esperando_usuario"
            return True

        # --- Esperando usuario (TikTok/BIGO/etc.) ---
        if etapa == "esperando_usuario":
            if not _es_mensaje_texto_util(tipo, texto):
                db.actualizar_aspirante_flujo_commit(
                    aspirante["id"], {"ultimo_message_id_meta": message_id_meta}
                )
                _reenviar_pregunta_actual(
                    config, aspirante, token, phone_number_id, telefono
                )
                return True

            usuario = normalizar_usuario_plataforma(texto)
            if not usuario:
                db.actualizar_aspirante_flujo_commit(
                    aspirante["id"], {"ultimo_message_id_meta": message_id_meta}
                )
                _reenviar_pregunta_actual(
                    config, aspirante, token, phone_number_id, telefono
                )
                return True

            aspirante = db.actualizar_aspirante_flujo_commit(
                aspirante["id"],
                {
                    "usuario_plataforma": usuario,
                    "etapa_chatbot": "esperando_mayor_edad",
                    "ultimo_message_id_meta": message_id_meta,
                },
            )
            logger.info(
                "[CHATBOT] respuesta guardada usuario=%s siguiente=esperando_mayor_edad",
                usuario,
            )
            _enviar_botones(
                token,
                phone_number_id,
                telefono,
                config["pregunta_mayor_edad"],
                _botones_si_no(BTN_EDAD_SI, BTN_EDAD_NO),
            )
            etapa_nueva = "esperando_mayor_edad"
            return True

        # --- Mayor de edad ---
        if etapa == "esperando_mayor_edad":
            respuesta = interpretar_si_no(payload_id, texto, BTN_EDAD_SI, BTN_EDAD_NO)
            if respuesta is None:
                db.actualizar_aspirante_flujo_commit(
                    aspirante["id"], {"ultimo_message_id_meta": message_id_meta}
                )
                _reenviar_pregunta_actual(
                    config, aspirante, token, phone_number_id, telefono
                )
                return True

            if respuesta is False:
                db.actualizar_aspirante_flujo_commit(
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

            db.actualizar_aspirante_flujo_commit(
                aspirante["id"],
                {
                    "mayor_edad": True,
                    "etapa_chatbot": "esperando_disponibilidad",
                    "ultimo_message_id_meta": message_id_meta,
                },
            )
            logger.info("[CHATBOT] siguiente pregunta=esperando_disponibilidad")
            _enviar_botones(
                token,
                phone_number_id,
                telefono,
                config["pregunta_disponibilidad"],
                _botones_si_no(BTN_DISP_SI, BTN_DISP_NO),
            )
            etapa_nueva = "esperando_disponibilidad"
            return True

        # --- Disponibilidad LIVE ---
        if etapa == "esperando_disponibilidad":
            respuesta = interpretar_si_no(payload_id, texto, BTN_DISP_SI, BTN_DISP_NO)
            if respuesta is None:
                db.actualizar_aspirante_flujo_commit(
                    aspirante["id"], {"ultimo_message_id_meta": message_id_meta}
                )
                _reenviar_pregunta_actual(
                    config, aspirante, token, phone_number_id, telefono
                )
                return True

            mayor = bool(aspirante.get("mayor_edad"))
            cumple = bool(mayor and respuesta)

            if not cumple:
                db.actualizar_aspirante_flujo_commit(
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

            db.actualizar_aspirante_flujo_commit(
                aspirante["id"],
                {
                    "disponibilidad_live": True,
                    "cumple_requisitos": True,
                    "estado": "completado",
                    "etapa_chatbot": "menu_principal",
                    "ultimo_message_id_meta": message_id_meta,
                },
            )
            logger.info("[CHATBOT] flujo aprobado → menu_principal")
            _enviar_botones(
                token,
                phone_number_id,
                telefono,
                config["mensaje_aprobado"],
                _botones_menu(config),
            )
            etapa_nueva = "menu_principal"
            return True

        # --- Menú / FAQ ---
        if etapa in ("menu_principal", "preguntas_frecuentes"):
            if payload_id == BTN_CONTINUAR:
                _manejar_continuar(
                    config,
                    aspirante,
                    token,
                    phone_number_id,
                    telefono,
                    message_id_meta,
                )
                return True

            if payload_id == BTN_PREGUNTAS:
                db.actualizar_aspirante_flujo_commit(
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
                db.actualizar_aspirante_flujo_commit(
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

            db.actualizar_aspirante_flujo_commit(
                aspirante["id"], {"ultimo_message_id_meta": message_id_meta}
            )
            _reenviar_pregunta_actual(
                config, aspirante, token, phone_number_id, telefono
            )
            return True

        # Etapa desconocida
        db.actualizar_aspirante_flujo_commit(
            aspirante["id"], {"ultimo_message_id_meta": message_id_meta}
        )
        _enviar_texto(
            token,
            phone_number_id,
            telefono,
            config.get("mensaje_error")
            or "No pudimos procesar tu respuesta. Por favor, intenta nuevamente.",
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
        traceback.print_exc()
        return True

    finally:
        if etapa_nueva and etapa_anterior != etapa_nueva:
            logger.info(
                "[CHATBOT] resultado agencia=%s account=%s tel=%s %s→%s",
                agencia_id,
                whatsapp_account_id,
                enmascarar_telefono(telefono),
                etapa_anterior,
                etapa_nueva,
            )
