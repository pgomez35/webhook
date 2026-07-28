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
    ETAPA_COMPLETADO,
    ETAPA_DISPONIBILIDAD,
    ETAPA_FAQ,
    ETAPA_FINALIZADO,
    ETAPA_INICIO,
    ETAPA_MAYOR_EDAD,
    ETAPA_MENU,
    ETAPA_PENDIENTE_ASESOR,
    ETAPA_RECHAZADO,
    ETAPA_USUARIO_PLATAFORMA,
    ETAPAS_CERRADAS,
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

# uvicorn.error llega a stdout en Render; chatbot_captacion a menudo no.
logger = logging.getLogger("uvicorn.error")

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
    if etapa == ETAPA_RECHAZADO:
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

    if etapa == ETAPA_USUARIO_PLATAFORMA:
        _enviar_texto(token, phone_number_id, wa_id, error)
        _enviar_texto(token, phone_number_id, wa_id, config["pregunta_usuario"])
    elif etapa == ETAPA_MAYOR_EDAD:
        _enviar_texto(token, phone_number_id, wa_id, error)
        _enviar_botones(
            token,
            phone_number_id,
            wa_id,
            config["pregunta_mayor_edad"],
            _botones_si_no(BTN_EDAD_SI, BTN_EDAD_NO),
        )
    elif etapa == ETAPA_DISPONIBILIDAD:
        _enviar_texto(token, phone_number_id, wa_id, error)
        _enviar_botones(
            token,
            phone_number_id,
            wa_id,
            config["pregunta_disponibilidad"],
            _botones_si_no(BTN_DISP_SI, BTN_DISP_NO),
        )
    elif etapa in (ETAPA_MENU, ETAPA_FAQ):
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
                "etapa_chatbot": ETAPA_PENDIENTE_ASESOR,
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
        campos.update(
            {"estado": "completado", "etapa_chatbot": ETAPA_COMPLETADO}
        )
        db.actualizar_aspirante_flujo_commit(aspirante["id"], campos)
        _enviar_texto(
            token,
            phone_number_id,
            wa_id,
            f"Continúa tu proceso aquí: {config.get('url_continuar')}",
        )
    elif accion == "agendamiento":
        campos.update(
            {"estado": "completado", "etapa_chatbot": ETAPA_COMPLETADO}
        )
        db.actualizar_aspirante_flujo_commit(aspirante["id"], campos)
        _enviar_texto(
            token,
            phone_number_id,
            wa_id,
            f"Agenda tu cita aquí: {config.get('url_continuar')}",
        )
    else:
        campos.update(
            {"estado": "completado", "etapa_chatbot": ETAPA_FINALIZADO}
        )
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
    print(
        f"[CHATBOT] entrada agencia_id={agencia_id} "
        f"whatsapp_account_id={whatsapp_account_id} "
        f"wa_id={enmascarar_telefono(wa_id)} tipo={tipo}"
    )

    if not agencia_id:
        logger.error("[CHATBOT] agencia_id ausente")
        print("[CHATBOT] abort: agencia_id ausente")
        return True
    if not whatsapp_account_id:
        logger.error("[CHATBOT] whatsapp_account_id ausente agencia_id=%s", agencia_id)
        print("[CHATBOT] abort: whatsapp_account_id ausente")
        return True
    if not wa_id:
        logger.error("[CHATBOT] wa_id ausente agencia_id=%s", agencia_id)
        print("[CHATBOT] abort: wa_id ausente")
        return True

    telefono = normalizar_telefono_chatbot(wa_id)
    if not telefono:
        logger.error("[CHATBOT] teléfono vacío tras normalizar wa_id=%s", wa_id)
        print("[CHATBOT] abort: teléfono vacío")
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
            print(
                f"[CHATBOT] abort: sin configuración activa agencia_id={agencia_id}"
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

        etapa_anterior = aspirante.get("etapa_chatbot") or ETAPA_INICIO

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

        etapa = aspirante.get("etapa_chatbot") or ETAPA_INICIO
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
        if etapa in (ETAPA_INICIO, None):
            try:
                aspirante = db.actualizar_aspirante_flujo_commit(
                    aspirante["id"],
                    {
                        "estado": "en_proceso",
                        "etapa_chatbot": ETAPA_USUARIO_PLATAFORMA,
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
                "[CHATBOT] transición %s -> %s",
                ETAPA_INICIO,
                ETAPA_USUARIO_PLATAFORMA,
            )
            logger.info("[CHATBOT] etapa persistida correctamente")
            logger.info("[CHATBOT] enviando bienvenida")
            _enviar_texto(
                token, phone_number_id, telefono, config["mensaje_bienvenida"]
            )
            _enviar_recursos_bienvenida(config, token, phone_number_id, telefono)
            logger.info("[CHATBOT] enviando pregunta usuario plataforma")
            _enviar_texto(
                token, phone_number_id, telefono, config["pregunta_usuario"]
            )
            etapa_nueva = ETAPA_USUARIO_PLATAFORMA
            return True

        # --- Esperando usuario de plataforma (TikTok/BIGO/etc.) ---
        if etapa == ETAPA_USUARIO_PLATAFORMA:
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
                    "etapa_chatbot": ETAPA_MAYOR_EDAD,
                    "ultimo_message_id_meta": message_id_meta,
                },
            )
            logger.info(
                "[CHATBOT] transición %s -> %s usuario=%s",
                ETAPA_USUARIO_PLATAFORMA,
                ETAPA_MAYOR_EDAD,
                usuario,
            )
            logger.info("[CHATBOT] etapa persistida correctamente")
            _enviar_botones(
                token,
                phone_number_id,
                telefono,
                config["pregunta_mayor_edad"],
                _botones_si_no(BTN_EDAD_SI, BTN_EDAD_NO),
            )
            etapa_nueva = ETAPA_MAYOR_EDAD
            return True

        # --- Mayor de edad ---
        if etapa == ETAPA_MAYOR_EDAD:
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
                        "etapa_chatbot": ETAPA_RECHAZADO,
                        "ultimo_message_id_meta": message_id_meta,
                    },
                )
                _enviar_texto(
                    token, phone_number_id, telefono, config["mensaje_no_aprobado"]
                )
                etapa_nueva = ETAPA_RECHAZADO
                return True

            db.actualizar_aspirante_flujo_commit(
                aspirante["id"],
                {
                    "mayor_edad": True,
                    "etapa_chatbot": ETAPA_DISPONIBILIDAD,
                    "ultimo_message_id_meta": message_id_meta,
                },
            )
            logger.info(
                "[CHATBOT] transición %s -> %s",
                ETAPA_MAYOR_EDAD,
                ETAPA_DISPONIBILIDAD,
            )
            _enviar_botones(
                token,
                phone_number_id,
                telefono,
                config["pregunta_disponibilidad"],
                _botones_si_no(BTN_DISP_SI, BTN_DISP_NO),
            )
            etapa_nueva = ETAPA_DISPONIBILIDAD
            return True

        # --- Disponibilidad LIVE ---
        if etapa == ETAPA_DISPONIBILIDAD:
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
                        "etapa_chatbot": ETAPA_RECHAZADO,
                        "ultimo_message_id_meta": message_id_meta,
                    },
                )
                _enviar_texto(
                    token, phone_number_id, telefono, config["mensaje_no_aprobado"]
                )
                etapa_nueva = ETAPA_RECHAZADO
                return True

            db.actualizar_aspirante_flujo_commit(
                aspirante["id"],
                {
                    "disponibilidad_live": True,
                    "cumple_requisitos": True,
                    "estado": "completado",
                    "etapa_chatbot": ETAPA_MENU,
                    "ultimo_message_id_meta": message_id_meta,
                },
            )
            logger.info(
                "[CHATBOT] transición %s -> %s",
                ETAPA_DISPONIBILIDAD,
                ETAPA_MENU,
            )
            _enviar_botones(
                token,
                phone_number_id,
                telefono,
                config["mensaje_aprobado"],
                _botones_menu(config),
            )
            etapa_nueva = ETAPA_MENU
            return True

        # --- Menú / FAQ ---
        if etapa in (ETAPA_MENU, ETAPA_FAQ):
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
                        "etapa_chatbot": ETAPA_FAQ,
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
                        "etapa_chatbot": ETAPA_MENU,
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
