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
    ETAPA_ASESOR,
    ETAPA_DISPONIBILIDAD,
    ETAPA_FINALIZADO,
    ETAPA_INICIO,
    ETAPA_MAYOR_EDAD,
    ETAPA_PREGUNTAS_FRECUENTES,
    ETAPA_RESULTADO,
    ETAPA_USUARIO,
    ETAPAS_SIN_AUTO_RESPUESTA,
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


# Momentos de envío de recursos (valores usados / compatibles con el JSON guardado).
MOMENTO_DESPUES_BIENVENIDA = "despues_bienvenida"
MOMENTO_DESPUES_APROBACION = "despues_aprobacion"
MOMENTO_SIN_ENVIO = "sin_envio"

_MOMENTO_ALIASES = {
    "despues_bienvenida": MOMENTO_DESPUES_BIENVENIDA,
    "despues_de_bienvenida": MOMENTO_DESPUES_BIENVENIDA,
    "bienvenida": MOMENTO_DESPUES_BIENVENIDA,
    "despues_aprobacion": MOMENTO_DESPUES_APROBACION,
    "despues_de_aprobacion": MOMENTO_DESPUES_APROBACION,
    "aprobacion": MOMENTO_DESPUES_APROBACION,
    "aprobado": MOMENTO_DESPUES_APROBACION,
    "sin_envio": MOMENTO_SIN_ENVIO,
    "ninguno": MOMENTO_SIN_ENVIO,
    "none": MOMENTO_SIN_ENVIO,
    "manual": MOMENTO_SIN_ENVIO,
}


def _normalizar_momento_envio(raw: Any) -> str:
    """
    Sin momento en el JSON legado → despues_bienvenida (comportamiento histórico).
    """
    if raw is None:
        return MOMENTO_DESPUES_BIENVENIDA
    clave = str(raw).strip().lower()
    if not clave:
        return MOMENTO_DESPUES_BIENVENIDA
    return _MOMENTO_ALIASES.get(clave, clave)


def _recurso_esta_activo(recurso: Dict[str, Any]) -> bool:
    activo = recurso.get("activo")
    if activo is False or activo == 0:
        return False
    if isinstance(activo, str) and activo.strip().lower() in ("false", "0", "no"):
        return False
    return True


def _nombre_archivo_pdf(recurso: Dict[str, Any]) -> str:
    nombre = (
        recurso.get("nombre_archivo")
        or recurso.get("nombre_original")
        or "documento.pdf"
    )
    nombre = str(nombre).strip() or "documento.pdf"
    if not nombre.lower().endswith(".pdf"):
        nombre = f"{nombre}.pdf"
    # Nombre seguro básico para Meta
    seguro = "".join(c if c.isalnum() or c in "._- " else "_" for c in nombre).strip()
    return (seguro or "documento.pdf")[:150]


def _meta_message_id(body: Any) -> Optional[str]:
    if not isinstance(body, dict):
        return None
    msgs = body.get("messages")
    if isinstance(msgs, list) and msgs:
        mid = msgs[0].get("id") if isinstance(msgs[0], dict) else None
        return str(mid) if mid else None
    return None


def _filtrar_recursos_por_momento(
    recursos: List[Dict[str, Any]],
    momento_envio: str,
) -> List[Dict[str, Any]]:
    momento = _normalizar_momento_envio(momento_envio)
    if momento == MOMENTO_SIN_ENVIO:
        return []

    filtrados: List[Dict[str, Any]] = []
    for recurso in recursos:
        if not _recurso_esta_activo(recurso):
            continue
        m = _normalizar_momento_envio(recurso.get("momento_envio"))
        if m == MOMENTO_SIN_ENVIO:
            continue
        if m == momento:
            filtrados.append(recurso)

    filtrados.sort(key=lambda x: int(x.get("orden") or 0))
    return filtrados


def enviar_recursos_chatbot_whatsapp(
    *,
    agencia_id: int,
    aspirante_id: Optional[int],
    telefono: str,
    phone_number_id: str,
    access_token: str,
    momento_envio: str,
    config: Optional[Dict[str, Any]] = None,
    recursos: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """
    Envía PDF/video activos de la agencia para un momento concreto.
    Errores por recurso no detienen el flujo del chatbot.
    No reenvía URL de Cloudinary como texto.
    """
    if recursos is None:
        raw = (config or {}).get("recursos_bienvenida")
        recursos = db.parse_recursos_bienvenida(raw)

    momento = _normalizar_momento_envio(momento_envio)
    seleccion = _filtrar_recursos_por_momento(list(recursos or []), momento)
    if not seleccion:
        logger.info(
            "[CHATBOT-MEDIA] sin recursos agencia_id=%s aspirante_id=%s momento=%s",
            agencia_id,
            aspirante_id,
            momento,
        )
        return

    for recurso in seleccion:
        tipo = (recurso.get("tipo") or "").strip().lower()
        url = (recurso.get("secure_url") or recurso.get("url") or "").strip()
        caption_raw = (recurso.get("caption") or "").strip()
        caption = caption_raw or None
        public_id = (recurso.get("public_id") or recurso.get("id") or "")[:80]
        rid = recurso.get("id")

        if not url.startswith("https://"):
            logger.warning(
                "[CHATBOT-MEDIA] URL inválida agencia_id=%s aspirante_id=%s "
                "tipo=%s public_id=%s momento=%s",
                agencia_id,
                aspirante_id,
                tipo,
                public_id,
                momento,
            )
            continue

        status = None
        body: Any = None
        try:
            if tipo == "video":
                status, body = enviar_video_whatsapp(
                    token=access_token,
                    numero_id=phone_number_id,
                    telefono_destino=telefono,
                    video_url=url,
                    caption=caption,
                )
            elif tipo == "document":
                status, body = enviar_documento_whatsapp(
                    token=access_token,
                    numero_id=phone_number_id,
                    telefono_destino=telefono,
                    documento_url=url,
                    caption=caption,
                    filename=_nombre_archivo_pdf(recurso),
                )
            else:
                logger.warning(
                    "[CHATBOT-MEDIA] tipo no soportado agencia_id=%s tipo=%s id=%s",
                    agencia_id,
                    tipo,
                    rid,
                )
                continue
        except Exception as e:
            logger.warning(
                "[CHATBOT-MEDIA] excepción agencia_id=%s aspirante_id=%s "
                "tipo=%s public_id=%s momento=%s causa=%s",
                agencia_id,
                aspirante_id,
                tipo,
                public_id,
                momento,
                type(e).__name__,
            )
            continue

        meta_mid = _meta_message_id(body)
        if status not in (200, 201):
            logger.warning(
                "[CHATBOT-MEDIA] fallo Meta agencia_id=%s aspirante_id=%s "
                "tipo=%s public_id=%s momento=%s http=%s",
                agencia_id,
                aspirante_id,
                tipo,
                public_id,
                momento,
                status,
            )
            continue

        logger.info(
            "[CHATBOT-MEDIA] ok agencia_id=%s aspirante_id=%s tipo=%s "
            "public_id=%s momento=%s http=%s message_id=%s",
            agencia_id,
            aspirante_id,
            tipo,
            public_id,
            momento,
            status,
            meta_mid,
        )

        extra = (recurso.get("mensaje_adicional") or "").strip()
        if extra:
            try:
                _enviar_texto(access_token, phone_number_id, telefono, extra)
            except Exception:
                logger.warning(
                    "[CHATBOT-MEDIA] fallo mensaje_adicional agencia_id=%s "
                    "aspirante_id=%s public_id=%s",
                    agencia_id,
                    aspirante_id,
                    public_id,
                )


def _enviar_recursos_bienvenida(
    config: Dict[str, Any],
    token: str,
    phone_number_id: str,
    wa_id: str,
    *,
    agencia_id: Optional[int] = None,
    aspirante_id: Optional[int] = None,
) -> None:
    """Compatibilidad: recursos con momento despues_bienvenida."""
    enviar_recursos_chatbot_whatsapp(
        agencia_id=int(agencia_id or 0),
        aspirante_id=aspirante_id,
        telefono=wa_id,
        phone_number_id=phone_number_id,
        access_token=token,
        momento_envio=MOMENTO_DESPUES_BIENVENIDA,
        config=config,
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


MSG_TRANSFERENCIA_ASESOR = (
    "Gracias. Tu información fue enviada al equipo de la agencia. "
    "Puedes escribir aquí cualquier pregunta o información adicional "
    "y un asesor continuará la conversación."
)


def _persistir_transicion(
    aspirante_id: int,
    etapa_actual: str,
    etapa_nueva: str,
    campos: Dict[str, Any],
) -> Dict[str, Any]:
    """Persiste etapa y campos; loguea transición. Lanza si falla el commit."""
    payload = dict(campos)
    payload["etapa_chatbot"] = etapa_nueva
    if etapa_nueva == ETAPA_ASESOR:
        logger.info(
            "[CHATBOT] transición %s -> asesor aspirante_id=%s",
            etapa_actual,
            aspirante_id,
        )
    else:
        logger.info(
            "[CHATBOT] transición etapa %s -> %s",
            etapa_actual,
            etapa_nueva,
        )
    actualizado = db.actualizar_aspirante_flujo_commit(aspirante_id, payload)
    logger.info(
        "[CHATBOT] etapa persistida correctamente: %s",
        etapa_nueva,
    )
    if etapa_nueva == ETAPA_ASESOR:
        logger.info(
            "[CHATBOT] conversación transferida a asesor aspirante_id=%s",
            aspirante_id,
        )
    return actualizado


def _actualizar_trazabilidad_sin_respuesta(
    aspirante: Dict[str, Any],
    message_id_meta: Optional[str],
) -> None:
    """Chat libre / finalizado: solo marca interacción, sin auto-respuesta."""
    db.actualizar_aspirante_flujo_commit(
        aspirante["id"],
        {"ultimo_message_id_meta": message_id_meta},
    )


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

    if etapa == ETAPA_USUARIO:
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
    elif etapa in (ETAPA_RESULTADO, ETAPA_PREGUNTAS_FRECUENTES):
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
    etapa_actual = aspirante.get("etapa_chatbot") or ETAPA_RESULTADO
    campos: Dict[str, Any] = {"ultimo_message_id_meta": message_id_meta}

    if accion == "asesor":
        campos.update(
            {
                "requiere_asesor": True,
                "estado": "en_proceso",
            }
        )
        try:
            _persistir_transicion(
                aspirante["id"], etapa_actual, ETAPA_ASESOR, campos
            )
        except Exception:
            logger.exception(
                "[CHATBOT] no se pudo transferir a asesor aspirante_id=%s",
                aspirante.get("id"),
            )
            traceback.print_exc()
            return
        _enviar_texto(
            token,
            phone_number_id,
            wa_id,
            MSG_TRANSFERENCIA_ASESOR,
        )
    elif accion == "url":
        campos.update({"estado": "completado"})
        try:
            _persistir_transicion(
                aspirante["id"], etapa_actual, ETAPA_FINALIZADO, campos
            )
        except Exception:
            logger.exception("[CHATBOT] no se pudo finalizar (url)")
            traceback.print_exc()
            return
        _enviar_texto(
            token,
            phone_number_id,
            wa_id,
            f"Continúa tu proceso aquí: {config.get('url_continuar')}",
        )
    elif accion == "agendamiento":
        campos.update({"estado": "completado"})
        try:
            _persistir_transicion(
                aspirante["id"], etapa_actual, ETAPA_FINALIZADO, campos
            )
        except Exception:
            logger.exception("[CHATBOT] no se pudo finalizar (agendamiento)")
            traceback.print_exc()
            return
        _enviar_texto(
            token,
            phone_number_id,
            wa_id,
            f"Agenda tu cita aquí: {config.get('url_continuar')}",
        )
    else:
        campos.update({"estado": "completado"})
        try:
            _persistir_transicion(
                aspirante["id"], etapa_actual, ETAPA_FINALIZADO, campos
            )
        except Exception:
            logger.exception("[CHATBOT] no se pudo finalizar")
            traceback.print_exc()
            return
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

        # --- Chat libre (asesor) o cierre real (finalizado): sin auto-respuesta ---
        if etapa in ETAPAS_SIN_AUTO_RESPUESTA:
            try:
                _actualizar_trazabilidad_sin_respuesta(aspirante, message_id_meta)
            except Exception:
                logger.exception(
                    "[CHATBOT] no se pudo actualizar trazabilidad aspirante_id=%s",
                    aspirante.get("id"),
                )
                traceback.print_exc()
            if etapa == ETAPA_ASESOR:
                logger.info(
                    "[CHATBOT] mensaje recibido en chat libre/asesor aspirante_id=%s",
                    aspirante.get("id"),
                )
            else:
                logger.info(
                    "[CHATBOT] mensaje en finalizado (sin auto-respuesta) aspirante_id=%s",
                    aspirante.get("id"),
                )
            return True

        # --- Primer contacto: persistir avance ANTES de enviar ---
        if etapa in (ETAPA_INICIO, None):
            try:
                aspirante = _persistir_transicion(
                    aspirante["id"],
                    ETAPA_INICIO,
                    ETAPA_USUARIO,
                    {
                        "estado": "en_proceso",
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

            logger.info("[CHATBOT] enviando bienvenida")
            _enviar_texto(
                token, phone_number_id, telefono, config["mensaje_bienvenida"]
            )
            enviar_recursos_chatbot_whatsapp(
                agencia_id=agencia_id,
                aspirante_id=aspirante.get("id"),
                telefono=telefono,
                phone_number_id=phone_number_id,
                access_token=token,
                momento_envio=MOMENTO_DESPUES_BIENVENIDA,
                config=config,
            )
            logger.info("[CHATBOT] enviando pregunta usuario plataforma")
            _enviar_texto(
                token, phone_number_id, telefono, config["pregunta_usuario"]
            )
            etapa_nueva = ETAPA_USUARIO
            return True

        # --- Usuario de plataforma (TikTok/BIGO/etc.) ---
        if etapa == ETAPA_USUARIO:
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

            try:
                aspirante = _persistir_transicion(
                    aspirante["id"],
                    ETAPA_USUARIO,
                    ETAPA_MAYOR_EDAD,
                    {
                        "usuario_plataforma": usuario,
                        "ultimo_message_id_meta": message_id_meta,
                    },
                )
            except Exception:
                logger.exception(
                    "[CHATBOT] no se pudo persistir usuario; no se envía siguiente pregunta"
                )
                traceback.print_exc()
                return True

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
                try:
                    _persistir_transicion(
                        aspirante["id"],
                        ETAPA_MAYOR_EDAD,
                        ETAPA_FINALIZADO,
                        {
                            "mayor_edad": False,
                            "cumple_requisitos": False,
                            "estado": "descartado",
                            "ultimo_message_id_meta": message_id_meta,
                        },
                    )
                except Exception:
                    logger.exception(
                        "[CHATBOT] no se pudo persistir rechazo por edad"
                    )
                    traceback.print_exc()
                    return True
                _enviar_texto(
                    token, phone_number_id, telefono, config["mensaje_no_aprobado"]
                )
                etapa_nueva = ETAPA_FINALIZADO
                return True

            try:
                _persistir_transicion(
                    aspirante["id"],
                    ETAPA_MAYOR_EDAD,
                    ETAPA_DISPONIBILIDAD,
                    {
                        "mayor_edad": True,
                        "ultimo_message_id_meta": message_id_meta,
                    },
                )
            except Exception:
                logger.exception(
                    "[CHATBOT] no se pudo persistir mayor_edad; no se envía pregunta"
                )
                traceback.print_exc()
                return True

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
                try:
                    _persistir_transicion(
                        aspirante["id"],
                        ETAPA_DISPONIBILIDAD,
                        ETAPA_FINALIZADO,
                        {
                            "disponibilidad_live": bool(respuesta),
                            "cumple_requisitos": False,
                            "estado": "descartado",
                            "ultimo_message_id_meta": message_id_meta,
                        },
                    )
                except Exception:
                    logger.exception(
                        "[CHATBOT] no se pudo persistir rechazo por disponibilidad"
                    )
                    traceback.print_exc()
                    return True
                _enviar_texto(
                    token, phone_number_id, telefono, config["mensaje_no_aprobado"]
                )
                etapa_nueva = ETAPA_FINALIZADO
                return True

            try:
                _persistir_transicion(
                    aspirante["id"],
                    ETAPA_DISPONIBILIDAD,
                    ETAPA_RESULTADO,
                    {
                        "disponibilidad_live": True,
                        "cumple_requisitos": True,
                        "estado": "completado",
                        "ultimo_message_id_meta": message_id_meta,
                    },
                )
            except Exception:
                logger.exception(
                    "[CHATBOT] no se pudo persistir resultado; no se envía menú"
                )
                traceback.print_exc()
                return True

            _enviar_texto(
                token, phone_number_id, telefono, config["mensaje_aprobado"]
            )
            enviar_recursos_chatbot_whatsapp(
                agencia_id=agencia_id,
                aspirante_id=aspirante.get("id"),
                telefono=telefono,
                phone_number_id=phone_number_id,
                access_token=token,
                momento_envio=MOMENTO_DESPUES_APROBACION,
                config=config,
            )
            _enviar_botones(
                token,
                phone_number_id,
                telefono,
                "Selecciona una opción:",
                _botones_menu(config),
            )
            etapa_nueva = ETAPA_RESULTADO
            return True

        # --- Resultado / FAQ ---
        if etapa in (ETAPA_RESULTADO, ETAPA_PREGUNTAS_FRECUENTES):
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
                try:
                    _persistir_transicion(
                        aspirante["id"],
                        etapa,
                        ETAPA_PREGUNTAS_FRECUENTES,
                        {"ultimo_message_id_meta": message_id_meta},
                    )
                except Exception:
                    logger.exception("[CHATBOT] no se pudo persistir FAQ")
                    traceback.print_exc()
                    return True
                _manejar_preguntas(config, token, phone_number_id, telefono)
                return True

            if payload_id and payload_id.startswith(FAQ_PREFIX):
                ok = _manejar_faq_seleccionada(
                    config, payload_id, token, phone_number_id, telefono
                )
                try:
                    _persistir_transicion(
                        aspirante["id"],
                        etapa,
                        ETAPA_RESULTADO,
                        {"ultimo_message_id_meta": message_id_meta},
                    )
                except Exception:
                    logger.exception(
                        "[CHATBOT] no se pudo volver a etapa resultado"
                    )
                    traceback.print_exc()
                    return True
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
