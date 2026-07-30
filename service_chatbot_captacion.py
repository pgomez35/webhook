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
    ETAPA_PLATAFORMA,
    ETAPA_PREGUNTAS_FRECUENTES,
    ETAPA_RESULTADO,
    ETAPA_USUARIO,
    ETAPAS_SIN_AUTO_RESPUESTA,
    FAQ_PREFIX,
    MAX_REPLY_BUTTONS,
    enmascarar_telefono,
    extraer_id_config_desde_payload,
    interpretar_si_no,
    normalizar_identificador_plataforma,
    normalizar_telefono_chatbot,
    payload_seleccion_config,
    truncar_titulo_boton,
)
from enviar_msg_wp import (
    enviar_audio_whatsapp,
    enviar_botones_Completa,
    enviar_documento_pdf_via_media_id_desde_url,
    enviar_imagen_whatsapp,
    enviar_lista_interactiva,
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
MOMENTO_SIN_ENVIO = "ninguno"

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
    Sin momento en el JSON legado → ninguno (no envío automático accidental).
    """
    if raw is None:
        return MOMENTO_SIN_ENVIO
    clave = str(raw).strip().lower()
    if not clave:
        return MOMENTO_SIN_ENVIO
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


def _meta_error_resumen(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    err = body.get("error")
    if not isinstance(err, dict):
        return str(body.get("error") or "")[:160]
    code = err.get("code")
    title = err.get("title") or err.get("error_user_title") or ""
    detail = err.get("message") or err.get("error_user_msg") or ""
    return f"code={code} title={title!r} detail={detail!r}"[:240]


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
    Envía recursos activos de la configuración (JSONB recursos_bienvenida)
    para un momento concreto, ordenados por `orden`.

    Errores por recurso no detienen el flujo del chatbot.
    Cada recurso se envía con su `caption` en el mismo mensaje Meta.

    - video: secure_url vía video.link
    - document/PDF: media_id Meta → document.id
    - image: secure_url vía image.link (preparado)
    - audio: secure_url vía audio.link (preparado; sin caption en Meta)

    Nota: `despues_bienvenida` se dispara tras guardar el identificador
    de plataforma del aspirante (no inmediatamente tras el mensaje de bienvenida).
    """
    if recursos is None:
        raw = (config or {}).get("recursos_bienvenida")
        recursos = db.parse_recursos_bienvenida(raw)

    momento = _normalizar_momento_envio(momento_envio)
    cfg_id = (config or {}).get("id")
    logger.info(
        "[CHATBOT-MEDIA] momento solicitado=%s agencia_id=%s aspirante_id=%s "
        "chatbot_configuracion_id=%s",
        momento,
        agencia_id,
        aspirante_id,
        cfg_id,
    )
    seleccion = _filtrar_recursos_por_momento(list(recursos or []), momento)
    logger.info(
        "[CHATBOT-MEDIA] recursos encontrados=%s momento=%s agencia_id=%s "
        "chatbot_configuracion_id=%s",
        len(seleccion),
        momento,
        agencia_id,
        cfg_id,
    )
    if not seleccion:
        return

    for recurso in seleccion:
        tipo = (recurso.get("tipo") or "").strip().lower()
        url = (recurso.get("secure_url") or recurso.get("url") or "").strip()
        caption_raw = (recurso.get("caption") or "").strip()
        caption = caption_raw or None
        public_id = (recurso.get("public_id") or recurso.get("id") or "")[:80]
        rid = recurso.get("id")
        if tipo == "document":
            tipo_log = "PDF"
        elif tipo in ("video", "image", "audio"):
            tipo_log = tipo
        else:
            tipo_log = tipo or "desconocido"

        logger.info(
            "[CHATBOT-MEDIA] enviando recurso id=%s tipo=%s public_id=%s momento=%s "
            "chatbot_configuracion_id=%s",
            rid,
            tipo_log,
            public_id,
            momento,
            cfg_id,
        )

        if not url.startswith("https://"):
            logger.warning(
                "[CHATBOT-MEDIA] URL inválida agencia_id=%s aspirante_id=%s "
                "tipo=%s public_id=%s momento=%s",
                agencia_id,
                aspirante_id,
                tipo_log,
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
                logger.info(
                    "[CHATBOT-PDF] recurso encontrado id=%s public_id=%s momento=%s",
                    rid,
                    public_id,
                    momento,
                )
                # PDF: media_id vía subir_media_whatsapp + enviar_documento_id
                # (no document.link) para evitar Meta 131053
                status, body = enviar_documento_pdf_via_media_id_desde_url(
                    token=access_token,
                    numero_id=phone_number_id,
                    telefono_destino=telefono,
                    documento_url=url,
                    caption=caption,
                    filename=_nombre_archivo_pdf(recurso),
                )
            elif tipo in ("image", "imagen"):
                status, body = enviar_imagen_whatsapp(
                    token=access_token,
                    numero_id=phone_number_id,
                    telefono_destino=telefono,
                    imagen_url=url,
                    caption=caption,
                )
            elif tipo == "audio":
                # Meta no admite caption en audio; si hay caption, se envía texto aparte
                status, body = enviar_audio_whatsapp(
                    token=access_token,
                    numero_id=phone_number_id,
                    telefono_destino=telefono,
                    audio_url=url,
                )
                if caption and status in (200, 201):
                    try:
                        _enviar_texto(access_token, phone_number_id, telefono, caption)
                    except Exception:
                        logger.warning(
                            "[CHATBOT-MEDIA] caption de audio no enviado "
                            "agencia_id=%s public_id=%s",
                            agencia_id,
                            public_id,
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
                tipo_log,
                public_id,
                momento,
                type(e).__name__,
            )
            continue

        meta_mid = _meta_message_id(body)
        if status not in (200, 201):
            logger.warning(
                "[CHATBOT-MEDIA] fallo Meta agencia_id=%s aspirante_id=%s "
                "tipo=%s public_id=%s momento=%s http=%s meta=%s",
                agencia_id,
                aspirante_id,
                tipo_log,
                public_id,
                momento,
                status,
                _meta_error_resumen(body),
            )
            continue

        logger.info(
            "[CHATBOT-MEDIA] ok agencia_id=%s aspirante_id=%s tipo=%s "
            "public_id=%s momento=%s http=%s wamid=%s "
            "chatbot_configuracion_id=%s",
            agencia_id,
            aspirante_id,
            tipo_log,
            public_id,
            momento,
            status,
            meta_mid,
            cfg_id,
        )

        extra = (recurso.get("mensaje_adicional") or "").strip()
        if extra:
            try:
                _enviar_texto(access_token, phone_number_id, telefono, extra)
                logger.info(
                    "[CHATBOT-MEDIA] mensaje_adicional enviado public_id=%s momento=%s",
                    public_id,
                    momento,
                )
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
    """Compatibilidad: recursos con momento despues_bienvenida de la config dada."""
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


def _mensaje_seleccion_agencia(agencia_id: int) -> str:
    agencia = db.obtener_agencia_por_id(agencia_id) or {}
    msg = (agencia.get("mensaje_seleccion_configuracion") or "").strip()
    if msg:
        return msg[:300]
    # Default alineado con chatbot.agencias.mensaje_seleccion_configuracion
    return "¿En qué plataforma deseas iniciar tu proceso?"


def _opciones_seleccion_config(
    configs: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    opciones: List[Dict[str, str]] = []
    for cfg in configs:
        cfg_id = cfg.get("id")
        if cfg_id is None:
            continue
        titulo_raw = (
            cfg.get("texto_opcion")
            or cfg.get("nombre")
            or cfg.get("plataforma_nombre")
            or "Opción"
        )
        try:
            titulo = truncar_titulo_boton(str(titulo_raw), 20)
        except ValueError:
            titulo = str(titulo_raw).strip()[:20] or "Opción"
        opciones.append(
            {
                "id": payload_seleccion_config(int(cfg_id)),
                "title": titulo,
            }
        )
    return opciones


def _enviar_selector_configuraciones(
    *,
    token: str,
    phone_number_id: str,
    wa_id: str,
    agencia_id: int,
    configs: List[Dict[str, Any]],
) -> None:
    cuerpo = _mensaje_seleccion_agencia(agencia_id)
    opciones = _opciones_seleccion_config(configs)
    if not opciones:
        logger.error(
            "[CHATBOT] selector sin opciones agencia_id=%s",
            agencia_id,
        )
        return
    if len(opciones) <= MAX_REPLY_BUTTONS:
        _enviar_botones(token, phone_number_id, wa_id, cuerpo, opciones)
        return
    filas = [{"id": o["id"], "title": o["title"][:24]} for o in opciones]
    enviar_lista_interactiva(
        token,
        phone_number_id,
        wa_id,
        cuerpo,
        filas,
        button_label="Ver opciones",
        section_title="Plataformas",
    )


def _enviar_inicio_config(
    *,
    config: Dict[str, Any],
    aspirante: Dict[str, Any],
    agencia_id: int,
    token: str,
    phone_number_id: str,
    telefono: str,
) -> None:
    """
    Inicio de la config seleccionada:
    bienvenida → pregunta_usuario.
    Los recursos `despues_bienvenida` se envían después de guardar el
    identificador de plataforma (ver etapa usuario).
    """
    logger.info(
        "[CHATBOT] enviando bienvenida agencia_id=%s aspirante_id=%s "
        "chatbot_configuracion_id=%s plataforma_codigo=%s",
        agencia_id,
        aspirante.get("id"),
        config.get("id"),
        config.get("plataforma_codigo"),
    )
    _enviar_texto(token, phone_number_id, telefono, config["mensaje_bienvenida"])
    logger.info(
        "[CHATBOT] enviando pregunta usuario plataforma "
        "chatbot_configuracion_id=%s",
        config.get("id"),
    )
    _enviar_texto(token, phone_number_id, telefono, config["pregunta_usuario"])


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
    elif etapa == ETAPA_PLATAFORMA:
        # El reenvío del selector se hace desde el caller con configs activas
        _enviar_texto(token, phone_number_id, wa_id, error)
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
        configs_activas = db.listar_configuraciones_activas(agencia_id)
        if not configs_activas:
            logger.error(
                "[CHATBOT] sin configuraciones activas agencia_id=%s — mensaje consumido",
                agencia_id,
            )
            print(
                f"[CHATBOT] abort: sin configuraciones activas agencia_id={agencia_id}"
            )
            return True

        logger.info(
            "[CHATBOT] entrada agencia_id=%s whatsapp_account_id=%s "
            "telefono=%s tipo=%s configs_activas=%s",
            agencia_id,
            whatsapp_account_id,
            enmascarar_telefono(telefono),
            tipo,
            len(configs_activas),
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
            "[CHATBOT] aspirante id=%s etapa=%s estado=%s "
            "chatbot_configuracion_id=%s plataforma_codigo=%s",
            aspirante.get("id"),
            aspirante.get("etapa_chatbot"),
            aspirante.get("estado"),
            aspirante.get("chatbot_configuracion_id"),
            aspirante.get("plataforma_codigo"),
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

        config: Optional[Dict[str, Any]] = None
        cfg_id_asignada = aspirante.get("chatbot_configuracion_id")

        # --- Selección de configuración (etapa plataforma, aún sin id asignado) ---
        if not cfg_id_asignada and etapa == ETAPA_PLATAFORMA:
            sel_id = extraer_id_config_desde_payload(payload_id)
            if sel_id is None:
                db.actualizar_aspirante_flujo_commit(
                    aspirante["id"], {"ultimo_message_id_meta": message_id_meta}
                )
                _enviar_selector_configuraciones(
                    token=token,
                    phone_number_id=phone_number_id,
                    wa_id=telefono,
                    agencia_id=agencia_id,
                    configs=configs_activas,
                )
                return True
            try:
                aspirante = db.asignar_configuracion_aspirante(
                    aspirante_id=int(aspirante["id"]),
                    agencia_id=agencia_id,
                    configuracion_id=sel_id,
                    message_id_meta=message_id_meta,
                )
                config = db.obtener_configuracion_por_id(
                    agencia_id, sel_id, solo_activa=True
                )
            except PermissionError:
                logger.warning(
                    "[CHATBOT] selección rechazada (otra agencia) "
                    "agencia_id=%s aspirante_id=%s configuracion_id=%s",
                    agencia_id,
                    aspirante.get("id"),
                    sel_id,
                )
                db.actualizar_aspirante_flujo_commit(
                    aspirante["id"], {"ultimo_message_id_meta": message_id_meta}
                )
                _enviar_selector_configuraciones(
                    token=token,
                    phone_number_id=phone_number_id,
                    wa_id=telefono,
                    agencia_id=agencia_id,
                    configs=configs_activas,
                )
                return True
            except ValueError as e:
                logger.warning(
                    "[CHATBOT] selección inválida agencia_id=%s aspirante_id=%s "
                    "configuracion_id=%s detalle=%s",
                    agencia_id,
                    aspirante.get("id"),
                    sel_id,
                    e,
                )
                db.actualizar_aspirante_flujo_commit(
                    aspirante["id"], {"ultimo_message_id_meta": message_id_meta}
                )
                _enviar_selector_configuraciones(
                    token=token,
                    phone_number_id=phone_number_id,
                    wa_id=telefono,
                    agencia_id=agencia_id,
                    configs=configs_activas,
                )
                return True
            except Exception:
                logger.exception(
                    "[CHATBOT] error al asignar selección aspirante_id=%s cfg=%s",
                    aspirante.get("id"),
                    sel_id,
                )
                traceback.print_exc()
                return True
            if not config:
                return True
            _enviar_inicio_config(
                config=config,
                aspirante=aspirante,
                agencia_id=agencia_id,
                token=token,
                phone_number_id=phone_number_id,
                telefono=telefono,
            )
            etapa_nueva = ETAPA_USUARIO
            return True

        # --- Sin configuración asignada: 1 / N activas ---
        if not cfg_id_asignada:
            if len(configs_activas) == 1:
                unica = configs_activas[0]
                try:
                    aspirante = db.asignar_configuracion_aspirante(
                        aspirante_id=int(aspirante["id"]),
                        agencia_id=agencia_id,
                        configuracion_id=int(unica["id"]),
                        message_id_meta=message_id_meta,
                    )
                    config = db.obtener_configuracion_por_id(
                        agencia_id, int(unica["id"]), solo_activa=True
                    )
                except Exception:
                    logger.exception(
                        "[CHATBOT] no se pudo auto-asignar config agencia_id=%s "
                        "aspirante_id=%s configuracion_id=%s",
                        agencia_id,
                        aspirante.get("id"),
                        unica.get("id"),
                    )
                    traceback.print_exc()
                    return True
                if not config:
                    logger.error(
                        "[CHATBOT] config auto-asignada no legible agencia_id=%s id=%s",
                        agencia_id,
                        unica.get("id"),
                    )
                    return True
                # Tras auto-asignación siempre enviamos inicio de esa config
                _enviar_inicio_config(
                    config=config,
                    aspirante=aspirante,
                    agencia_id=agencia_id,
                    token=token,
                    phone_number_id=phone_number_id,
                    telefono=telefono,
                )
                etapa_nueva = ETAPA_USUARIO
                return True

            # ≥2: selector (nunca interpretar texto como TikTok/BIGO)
            try:
                aspirante = db.actualizar_aspirante_flujo_commit(
                    aspirante["id"],
                    {
                        "etapa_chatbot": ETAPA_PLATAFORMA,
                        "estado": "en_proceso",
                        "whatsapp_account_id": whatsapp_account_id,
                        "ultimo_message_id_meta": message_id_meta,
                    },
                )
            except Exception:
                logger.exception(
                    "[CHATBOT] no se pudo persistir etapa plataforma aspirante_id=%s",
                    aspirante.get("id"),
                )
                traceback.print_exc()
                return True
            logger.info(
                "[CHATBOT] enviando selector configs agencia_id=%s aspirante_id=%s n=%s",
                agencia_id,
                aspirante.get("id"),
                len(configs_activas),
            )
            _enviar_selector_configuraciones(
                token=token,
                phone_number_id=phone_number_id,
                wa_id=telefono,
                agencia_id=agencia_id,
                configs=configs_activas,
            )
            etapa_nueva = ETAPA_PLATAFORMA
            return True

        # --- Configuración ya asignada ---
        config = db.obtener_configuracion_por_id(
            agencia_id, int(cfg_id_asignada), solo_activa=False
        )
        if not config:
            logger.error(
                "[CHATBOT] chatbot_configuracion_id=%s inexistente o de otra agencia "
                "agencia_id=%s aspirante_id=%s",
                cfg_id_asignada,
                agencia_id,
                aspirante.get("id"),
            )
            return True
        if not config.get("activo"):
            logger.warning(
                "[CHATBOT] configuración desactivada chatbot_configuracion_id=%s "
                "agencia_id=%s aspirante_id=%s",
                cfg_id_asignada,
                agencia_id,
                aspirante.get("id"),
            )
            db.actualizar_aspirante_flujo_commit(
                aspirante["id"], {"ultimo_message_id_meta": message_id_meta}
            )
            _enviar_texto(
                token,
                phone_number_id,
                telefono,
                config.get("mensaje_error")
                or "Esta opción ya no está disponible. Contacta a la agencia.",
            )
            return True

        # --- Primer contacto con config ya asignada (p. ej. reinicio parcial) ---
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

            _enviar_inicio_config(
                config=config,
                aspirante=aspirante,
                agencia_id=agencia_id,
                token=token,
                phone_number_id=phone_number_id,
                telefono=telefono,
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

            plataforma_codigo = (
                aspirante.get("plataforma_codigo")
                or config.get("plataforma_codigo")
                or "tiktok"
            )
            usuario = normalizar_identificador_plataforma(plataforma_codigo, texto)
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

            logger.info(
                "[CHATBOT] usuario guardado agencia_id=%s aspirante_id=%s "
                "chatbot_configuracion_id=%s plataforma_codigo=%s",
                agencia_id,
                aspirante.get("id"),
                config.get("id"),
                plataforma_codigo,
            )
            # Orden: usuario guardado → recursos despues_bienvenida → pregunta edad
            try:
                logger.info(
                    "[CHATBOT] enviando recursos despues_bienvenida "
                    "(tras guardar usuario, antes de mayor_edad) "
                    "chatbot_configuracion_id=%s",
                    config.get("id"),
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
            except Exception:
                logger.exception(
                    "[CHATBOT] error enviando recursos despues_bienvenida; "
                    "se continúa con pregunta_mayor_edad"
                )
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
            # Orden obligatorio aprobación:
            # mensaje_aprobado → recursos despues_aprobacion (+ mensaje_adicional) → botones
            try:
                logger.info(
                    "[CHATBOT] enviando recursos despues_aprobacion "
                    "(antes de botones de resultado)"
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
            except Exception:
                logger.exception(
                    "[CHATBOT] error enviando recursos despues_aprobacion; "
                    "se continúa con botones de resultado"
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
