import os
from fastapi import APIRouter, HTTPException, Depends
import logging

from DataBase import get_connection_context

logger = logging.getLogger("uvicorn.error")

router = APIRouter()   # ← ESTE ES EL ROUTER QUE VAS A IMPORTAR EN main.py

import re
import requests
import json
from datetime import datetime, timedelta


# --- MOCK DE BASE DE DATOS (Reemplaza con tu lógica real SQL) ---
def guardar_estado_eval(creador_id, estado):
    # UPDATE perfil_creador SET estado_evaluacion = estado WHERE creador_id = creador_id
    print(f"💾 BD: Estado actualizado a '{estado}' para ID {creador_id}")


def buscar_estado_creador(creador_id):
    """
    Obtiene el estado actual del creador a partir de perfil_creador
    y trae:
    - codigo_estado
    - mensaje_frontend_simple
    - mensaje_chatbot_simple
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                sql = """
                    SELECT
                        cea.codigo,
                        cea.mensaje_frontend_simple,
                        cea.mensaje_chatbot_simple
                    FROM perfil_creador pc
                    INNER JOIN chatbot_estados_aspirante cea
                        ON pc.id_chatbot_estado = cea.id_chatbot_estado
                    WHERE pc.creador_id = %s
                """
                cur.execute(sql, (creador_id,))
                row = cur.fetchone()

                if row:
                    return {
                        "codigo_estado": row[0],
                        "mensaje_frontend_simple": row[1],
                        "mensaje_chatbot_simple": row[2],
                    }

                return None

    except Exception as e:
        print(f"❌ Error al buscar estado del creador {creador_id}: {e}")
        return None



def obtener_creador_id_por_telefono(telefono):
    # SELECT creador_id FROM perfil_creador WHERE telefono = ...
    return 3236


def guardar_link_tiktok_live(creador_id, url):
    # UPDATE perfil_creador SET link_tiktok = url WHERE ...
    print(f"💾 URL guardada: {url}")


def obtener_status_24hrs(telefono):
    # Consultar last_interaction en BD
    # Si (now - last_interaction) > 24h return False (Fuera de ventana)
    # Si (now - last_interaction) < 24h return True (Dentro de ventana)
    return False  # Simulamos que está dentro para pruebas


# --- FUNCIONES LÓGICAS ---

def validar_url_link_tiktok_live(url):
    """Valida si es un link de TikTok válido."""
    patron = r"(https?://)?(www\.|vm\.|vt\.)?tiktok\.com/.*"
    return bool(re.match(patron, url))


def Enviar_msg_estado(creador_id, estado_evaluacion, phone_id, token, telefono):
    """
    Envía mensaje motivante + Botón 'Opciones' (QuickReply).
    Se usa cuando estamos DENTRO de la ventana de 24h.
    """
    mensajes = {
        "solicitud_agendamiento_tiktok": "¡Vas genial! Es hora de demostrar tu talento en vivo.",
        "documentacion": "Ya casi terminamos, solo faltan tus papeles."
    }

    texto = mensajes.get(estado_evaluacion, "Hola, tenemos novedades de tu proceso.")

    payload = {
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": texto},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {"id": "BTN_ABRIR_MENU_OPCIONES", "title": "Opciones"}
                    }
                ]
            }
        }
    }
    enviar_a_meta(payload, phone_id, token)


def enviar_plantilla_estado_evaluacion(creador_id, estado_evaluacion, phone_id, token, telefono):
    """
    Envía una plantilla aprobada por Meta.
    Se usa cuando estamos FUERA de la ventana de 24h.
    """
    # Mapeo: Estado -> Nombre de Plantilla en Meta
    plantillas = {
        "solicitud_agendamiento_tiktok": "plantilla_solicitud_tiktok",  # Debe existir en Meta
        "documentacion": "plantilla_solicitud_docs"
    }

    nombre_template = plantillas.get(estado_evaluacion, "plantilla_generica_estado")

    payload = {
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "template",
        "template": {
            "name": nombre_template,
            "language": {"code": "es"},
            "components": [
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": "0",
                    "parameters": [{"type": "payload", "payload": "BTN_ABRIR_MENU_OPCIONES"}]
                }
            ]
        }
    }
    enviar_a_meta(payload, phone_id, token)

def Enviar_menu_quickreply(creador_id, estado_evaluacion, phone_id, token, telefono):
    texto_menu = "Elige una opción:"
    botones = []

    MENUS = {

        "post_encuesta_inicial": {
            "texto": "¿Cómo deseas continuar?",
            "botones": [
                ("MENU_PROCESO_INCORPORACION", "Proceso de incorporación a Prestige"),
                ("MENU_PREGUNTAS_FRECUENTES", "Preguntas Frecuentes"),
            ]
        },

        "solicitud_agendamiento_tiktok": {
            "texto": "Es momento de tu prueba en TikTok LIVE 🎥",
            "botones": [
                ("MENU_AGENDAR_PRUEBA_TIKTOK", "Agendar prueba de TikTok LIVE"),
                ("MENU_VER_GUIA_PRUEBA", "Ver guía de la prueba"),
                ("MENU_CHAT_ASESOR", "Hablar con un asesor")
            ]
        },

        "usuario_agendo_prueba_tiktok": {
            "texto": "Gestiona tu prueba de TikTok LIVE",
            "botones": [
                ("MENU_INGRESAR_LINK_TIKTOK", "Ingresar link de TikTok LIVE"),
                ("MENU_MODIFICAR_CITA_PRUEBA", "Modificar cita de la prueba"),
                ("MENU_VER_GUIA_PRUEBA", "Ver guía de la prueba"),
            ]
        },

        "solicitud_agendamiento_entrevista": {
            "texto": "Siguiente paso: entrevista con un asesor",
            "botones": [
                ("MENU_AGENDAR_ENTREVISTA", "Agendar entrevista con un asesor"),
            ]
        },

        "usuario_agendo_entrevista": {
            "texto": "Gestiona tu entrevista",
            "botones": [
                ("MENU_MODIFICAR_CITA_ENTREVISTA", "Modificar cita de entrevista"),
            ]
        },

        "solicitud_agendamiento_tiktok2": {
            "texto": "Continuamos con una segunda prueba 🎥",
            "botones": [
                ("MENU_AGENDAR_PRUEBA_TIKTOK_2", "Agendar prueba #2 de TikTok LIVE"),
                ("MENU_RESULTADO_PRUEBA_1", "Resultado prueba #1"),
            ]
        },

        "usuario_agendo_prueba_tiktok2": {
            "texto": "Gestiona tu prueba #2 de TikTok LIVE",
            "botones": [
                ("MENU_INGRESAR_LINK_TIKTOK_2", "Ingresar link de TikTok LIVE #2"),
                ("MENU_MODIFICAR_CITA_PRUEBA_2", "Modificar cita de la prueba #2"),
                ("MENU_VER_GUIA_PRUEBA_2", "Ver guía de la prueba #2"),
            ]
        },

        "solicitud_agendamiento_entrevista2": {
            "texto": "Agendemos tu entrevista final",
            "botones": [
                ("MENU_AGENDAR_ENTREVISTA", "Agendar entrevista con un asesor"),
            ]
        },

        "usuario_agendo_entrevista2": {
            "texto": "Gestiona tu entrevista",
            "botones": [
                ("MENU_MODIFICAR_CITA_ENTREVISTA", "Modificar cita de la entrevista"),
                ("MENU_TEMAS_ENTREVISTA_2", "Temas a tratar en entrevista #2"),
            ]
        },

        "solicitud_invitacion_tiktok": {
            "texto": "Consulta el estado de tu proceso",
            "botones": [
                ("MENU_ESTADO_PROCESO", "Estado del proceso"),
            ]
        },

        "invitacion_tiktok_aceptada": {
            "texto": "Tu proceso con TikTok está activo ✅",
            "botones": [
                ("MENU_ESTADO_PROCESO", "Estado del proceso"),
            ]
        },

        "solicitud_invitacion_usuario": {
            "texto": "Estás a un paso de unirte a la agencia 🚀",
            "botones": [
                ("MENU_VENTAJAS_AGENCIA", "Ventajas de pertenecer a la agencia"),
                ("MENU_ACEPTAR_INCORPORACION", "Aceptar incorporación a la agencia"),
            ]
        },
    }

    menu = MENUS.get(estado_evaluacion)

    if not menu:
        return  # Estado sin menú

    texto_menu = menu["texto"]
    botones = menu["botones"]

    botones_api = [
        {
            "type": "reply",
            "reply": {
                "id": boton_id,
                "title": titulo
            }
        }
        for boton_id, titulo in botones
    ]

    payload = {
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": texto_menu},
            "action": {"buttons": botones_api}
        }
    }

    enviar_a_meta(payload, phone_id, token)


def Enviar_menu_quickreplyV0(creador_id, estado_evaluacion, phone_id, token, telefono):
    botones = []
    texto_menu = "Elige una opción:"

    if estado_evaluacion == "solicitud_agendamiento_tiktok":
        texto_menu = "¿Listo para tu prueba?"
        botones = [
            {"id": "BTN_ENVIAR_LINK_TIKTOK", "title": "Enviar Link Live"},
            {"id": "BTN_VER_TUTORIAL", "title": "Ver Tutorial"}
        ]

    botones_api = [
        {
            "type": "reply",
            "reply": {
                "id": b["id"],
                "title": b["title"]
            }
        }
        for b in botones
    ]

    payload = {
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": texto_menu},
            "action": {"buttons": botones_api}
        }
    }

    enviar_a_meta(payload, phone_id, token)

def Enviar_menu_quickreplyV1(creador_id, estado_evaluacion, phone_id, token, telefono):
    texto_menu = "Elige una opción:"
    botones = []

    MENUS = {

        "post_encuesta_inicial": {
            "texto": "¿Cómo deseas continuar?",
            "botones": [
                ("MENU_PROCESO_INCORPORACION", "Proceso de incorporación a Prestige"),
            ]
        },

        "solicitud_agendamiento_tiktok": {
            "texto": "Es momento de tu prueba en TikTok LIVE 🎥",
            "botones": [
                ("MENU_AGENDAR_PRUEBA_TIKTOK", "Agendar prueba de TikTok LIVE"),
                ("MENU_VER_GUIA_PRUEBA", "Ver guía de la prueba"),
            ]
        },

        "usuario_agendo_prueba_tiktok": {
            "texto": "Gestiona tu prueba de TikTok LIVE",
            "botones": [
                ("MENU_INGRESAR_LINK_TIKTOK", "Ingresar link de TikTok LIVE"),
                ("MENU_MODIFICAR_CITA_PRUEBA", "Modificar cita de la prueba"),
                ("MENU_VER_GUIA_PRUEBA", "Ver guía de la prueba"),
            ]
        },

        "solicitud_agendamiento_entrevista": {
            "texto": "Siguiente paso: entrevista con un asesor",
            "botones": [
                ("MENU_AGENDAR_ENTREVISTA", "Agendar entrevista con un asesor"),
            ]
        },

        "usuario_agendo_entrevista": {
            "texto": "Gestiona tu entrevista",
            "botones": [
                ("MENU_MODIFICAR_CITA_ENTREVISTA", "Modificar cita de entrevista"),
            ]
        },

        "solicitud_agendamiento_tiktok2": {
            "texto": "Continuamos con una segunda prueba 🎥",
            "botones": [
                ("MENU_AGENDAR_PRUEBA_TIKTOK_2", "Agendar prueba #2 de TikTok LIVE"),
                ("MENU_RESULTADO_PRUEBA_1", "Resultado prueba #1"),
            ]
        },

        "usuario_agendo_prueba_tiktok2": {
            "texto": "Gestiona tu prueba #2 de TikTok LIVE",
            "botones": [
                ("MENU_INGRESAR_LINK_TIKTOK_2", "Ingresar link de TikTok LIVE #2"),
                ("MENU_MODIFICAR_CITA_PRUEBA_2", "Modificar cita de la prueba #2"),
                ("MENU_VER_GUIA_PRUEBA_2", "Ver guía de la prueba #2"),
            ]
        },

        "solicitud_agendamiento_entrevista2": {
            "texto": "Agendemos tu entrevista final",
            "botones": [
                ("MENU_AGENDAR_ENTREVISTA", "Agendar entrevista con un asesor"),
            ]
        },

        "usuario_agendo_entrevista2": {
            "texto": "Gestiona tu entrevista",
            "botones": [
                ("MENU_MODIFICAR_CITA_ENTREVISTA", "Modificar cita de la entrevista"),
                ("MENU_TEMAS_ENTREVISTA_2", "Temas a tratar en entrevista #2"),
            ]
        },

        "solicitud_invitacion_tiktok": {
            "texto": "Consulta el estado de tu proceso",
            "botones": [
                ("MENU_ESTADO_PROCESO", "Estado del proceso"),
            ]
        },

        "invitacion_tiktok_aceptada": {
            "texto": "Tu proceso con TikTok está activo ✅",
            "botones": [
                ("MENU_ESTADO_PROCESO", "Estado del proceso"),
            ]
        },

        "solicitud_invitacion_usuario": {
            "texto": "Estás a un paso de unirte a la agencia 🚀",
            "botones": [
                ("MENU_VENTAJAS_AGENCIA", "Ventajas de pertenecer a la agencia"),
                ("MENU_ACEPTAR_INCORPORACION", "Aceptar incorporación a la agencia"),
            ]
        },
    }

    menu = MENUS.get(estado_evaluacion)

    if not menu:
        return  # Estado sin menú

    texto_menu = menu["texto"]
    botones = menu["botones"]

    botones_api = [
        {
            "type": "reply",
            "reply": {
                "id": boton_id,
                "title": titulo
            }
        }
        for boton_id, titulo in botones
    ]

    payload = {
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": texto_menu},
            "action": {"buttons": botones_api}
        }
    }

    enviar_a_meta(payload, phone_id, token)


def accion_menu_estado_evaluacion(creador_id, button_id, phone_id, token, estado_evaluacion, telefono):
    """
    Ejecuta la acción correspondiente al botón presionado en el menú de opciones.
    """
    print(f"⚡ Ejecutando acción: {button_id} (Estado origen: {estado_evaluacion})")

    # =================================================================
    # GRUPO 1: INGRESO DE DATOS (Cambian estado para esperar texto)
    # =================================================================

    if button_id == "MENU_INGRESAR_LINK_TIKTOK":
        # Cambiamos estado para que el próximo mensaje de texto sea capturado como URL
        guardar_estado_eval(creador_id, "esperando_link_tiktok_live")
        enviar_texto_simple(telefono, "🔗 Por favor, pega aquí el enlace de tu TikTok LIVE:", phone_id, token)

    elif button_id == "MENU_INGRESAR_LINK_TIKTOK_2":
        guardar_estado_eval(creador_id, "esperando_link_tiktok_live_2")
        enviar_texto_simple(telefono, "🔗 Por favor, pega aquí el enlace de tu **segundo** TikTok LIVE:", phone_id,
                            token)

    # =================================================================
    # GRUPO 2: AGENDAMIENTO Y CALENDARIOS (Envío de Links)
    # =================================================================

    elif button_id == "MENU_AGENDAR_PRUEBA_TIKTOK":
        enviar_texto_simple(telefono, "📅 Agenda tu prueba aquí: https://calendly.com/tu-agencia/prueba-tiktok",
                            phone_id, token)

    elif button_id == "MENU_AGENDAR_PRUEBA_TIKTOK_2":
        enviar_texto_simple(telefono,
                            "📅 Agenda tu segunda prueba aquí: https://calendly.com/tu-agencia/prueba-tiktok-2",
                            phone_id, token)

    elif button_id == "MENU_AGENDAR_ENTREVISTA":
        enviar_texto_simple(telefono,
                            "👔 Agenda tu entrevista con un asesor aquí: https://calendly.com/tu-agencia/entrevista",
                            phone_id, token)

    elif button_id in ["MENU_MODIFICAR_CITA_PRUEBA", "MENU_MODIFICAR_CITA_PRUEBA_2", "MENU_MODIFICAR_CITA_ENTREVISTA"]:
        enviar_texto_simple(telefono,
                            "🔄 Puedes reprogramar tu cita usando el mismo enlace que te enviamos al agendar, o contacta a soporte si tienes problemas.",
                            phone_id, token)

    # =================================================================
    # GRUPO 3: INFORMACIÓN Y GUÍAS (Envío de Texto/PDF/Links)
    # =================================================================

    elif button_id == "MENU_VER_GUIA_PRUEBA":
        enviar_texto_simple(telefono, "📘 Aquí tienes la guía para tu prueba: https://tu-agencia.com/guia-tiktok-pdf",
                            phone_id, token)
        # O podrías enviar un documento real usando enviar_documento(...)

    elif button_id == "MENU_VER_GUIA_PRUEBA_2":
        enviar_texto_simple(telefono, "📘 Guía avanzada para la prueba #2: https://tu-agencia.com/guia-tiktok-2-pdf",
                            phone_id, token)

    elif button_id == "MENU_PROCESO_INCORPORACION":
        msg = ("🏢 *Proceso de Incorporación:*\n"
               "1. Evaluación de perfil\n"
               "2. Prueba de transmisión\n"
               "3. Entrevista final\n"
               "4. Firma de contrato")
        enviar_texto_simple(telefono, msg, phone_id, token)

    elif button_id == "MENU_PREGUNTAS_FRECUENTES":
        enviar_texto_simple(telefono, "❓ Revisa nuestras dudas frecuentes aquí: https://tu-agencia.com/faq", phone_id,
                            token)

    elif button_id == "MENU_VENTAJAS_AGENCIA":
        msg = ("🚀 *Ventajas Prestige:*\n"
               "✅ Soporte 24/7\n"
               "✅ Monetización mejorada\n"
               "✅ Eventos exclusivos")
        enviar_texto_simple(telefono, msg, phone_id, token)

    elif button_id == "MENU_TEMAS_ENTREVISTA_2":
        enviar_texto_simple(telefono,
                            "📝 En la entrevista hablaremos de: Disponibilidad, Metas financieras y Reglamento interno.",
                            phone_id, token)

    # =================================================================
    # GRUPO 4: ESTADOS Y RESULTADOS
    # =================================================================

    elif button_id == "MENU_RESULTADO_PRUEBA_1":
        # Aquí podrías consultar la BD real. Por ahora simulamos:
        enviar_texto_simple(telefono, "📊 Tu prueba #1 fue: *APROBADA* (Puntaje: 85/100). ¡Sigue así!", phone_id, token)

    elif button_id == "MENU_ESTADO_PROCESO":
        enviar_texto_simple(telefono, f"📍 Tu estado actual es: *{estado_evaluacion}*.", phone_id, token)

    # =================================================================
    # GRUPO 5: ACCIONES CRÍTICAS (Aceptar oferta / Hablar con Humano)
    # =================================================================

    elif button_id == "MENU_ACEPTAR_INCORPORACION":
        guardar_estado_eval(creador_id, "incorporacion_en_tramite")
        enviar_texto_simple(telefono,
                            "🎉 ¡Bienvenido a la familia! Un administrador te contactará pronto para finalizar el papeleo.",
                            phone_id, token)
        # Opcional: Notificar al admin aquí

    elif button_id == "MENU_CHAT_ASESOR":
        # Aquí podrías cambiar el flujo a "chat_libre" para que intervenga un humano
        # actualizar_flujo(telefono, "chat_libre")
        enviar_texto_simple(telefono, "💬 Hemos notificado a un asesor. Te escribirá en breve.", phone_id, token)

    # =================================================================
    # DEFAULT
    # =================================================================
    else:
        print(f"⚠️ Botón sin acción definida: {button_id}")
        enviar_texto_simple(telefono, "Esta opción está en mantenimiento.", phone_id, token)



def accion_menu_estado_evaluacionV0(creador_id, button_id, phone_id, token, estado_evaluacion, telefono):
    """
    Ejecuta la acción final cuando el usuario selecciona una opción del menú.
    """
    print(f"⚡ Ejecutando acción: {button_id} para estado {estado_evaluacion}")

    if button_id == "BTN_ENVIAR_LINK_TIKTOK" and estado_evaluacion == "solicitud_agendamiento_tiktok":
        # 1. Cambiar estado para esperar texto
        guardar_estado_eval(creador_id, "solicitud_link_enviado")

        # 2. Pedir al usuario que escriba
        enviar_texto_simple(telefono, "Por favor, pega aquí la URL de tu TikTok Live:", phone_id, token)

    elif button_id == "BTN_VER_TUTORIAL":
        enviar_texto_simple(telefono, "Aquí tienes el tutorial: https://youtube.com/...", phone_id, token)

    elif button_id == "BTN_SUBIR_CEDULA":
        enviar_texto_simple(telefono, "Por favor toma una foto a tu cédula y envíala.", phone_id, token)


# --- UTILS API ---
def enviar_a_meta(data, phone_id, token):
    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    res = requests.post(url, headers=headers, json=data)
    print(f"Meta Response: {res.status_code}")


def enviar_texto_simple(telefono, texto, phone_id, token):
    data = {
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "text",
        "text": {"body": texto}
    }
    enviar_a_meta(data, phone_id, token)


import traceback


# Importar tus funciones de lógica de negocio (ajusta los imports según tu estructura)
# from services.aspirant_service import buscar_estado_creador, obtener_creador_id_por_telefono, enviar_plantilla_estado_evaluacion
# from services.db_service import actualizar_mensaje_desde_status

async def _handle_statuses(statuses, tenant_name, phone_number_id, token_access, raw_payload):
    """
    Procesa la lista de estados (sent, delivered, read, failed).
    Detecta errores de ventana de 24h y dispara la recuperación con plantillas.
    """
    for status_obj in statuses:
        try:
            # 1. ACTUALIZAR BD (Siempre se hace, sea éxito o error)
            # Esta función actualiza el estado del mensaje en tu tabla de historial
            actualizar_mensaje_desde_status(
                tenant=tenant_name,
                phone_number_id=phone_number_id,
                display_phone_number=status_obj.get("recipient_id"),
                status_obj=status_obj,
                raw_payload=raw_payload
            )

            # 2. DETECCIÓN DE ERRORES CRÍTICOS
            if status_obj.get("status") == "failed":
                await _procesar_error_envio(status_obj, tenant_name, phone_number_id, token_access)

        except Exception as e:
            print(f"⚠️ Error procesando status individual: {e}")
            traceback.print_exc()

def actualizar_mensaje_desde_status(
    tenant: str,
    phone_number_id: str,
    display_phone_number: str,
    status_obj: dict,
    raw_payload: dict,
) -> None:
    """
    Actualiza el estado de un mensaje en la BD basado en el webhook de status.

    - tenant: tenant/subdominio (ej: 'pruebas', 'prestige')
    - phone_number_id: phone_number_id WABA
    - display_phone_number: número de negocio
    - status_obj: dict del status individual (de value["statuses"][i])
    - raw_payload: el bloque "value" completo o el status_obj
    """
    try:
        message_id = status_obj.get("id")
        status = status_obj.get("status")
        recipient_id = status_obj.get("recipient_id")
        timestamp = status_obj.get("timestamp")

        error = (status_obj.get("errors") or [None])[0]  # primer error o None

        error_code = error.get("code") if error else None
        error_title = error.get("title") if error else None
        error_message = error.get("message") if error else None
        error_details = (error.get("error_data") or {}).get("details") if error else None

        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE whatsapp_messages
                    SET
                        status = %s,
                        error_code = %s,
                        error_title = %s,
                        error_message = %s,
                        error_details = %s,
                        raw_payload = %s,
                        updated_at = NOW(),
                        last_status_at = TO_TIMESTAMP(%s)
                    WHERE message_id = %s
                      AND tenant = %s;
                    """,
                    (
                        status,
                        error_code,
                        error_title,
                        error_message,
                        error_details,
                        json.dumps(raw_payload),
                        int(timestamp) if timestamp else None,
                        message_id,
                        tenant,
                    ),
                )
        print(f"📊 Status actualizado para mensaje {message_id}: {status}")
    except Exception as e:
        print(f"❌ Error al actualizar status del mensaje {status_obj.get('id', 'unknown')}: {e}")
        traceback.print_exc()


async def _procesar_error_envio(status_obj, tenant, phone_id, token):
    """
    Analiza por qué falló el mensaje y toma acciones correctivas.
    """
    errors = status_obj.get("errors", [])
    recipient_id = status_obj.get("recipient_id")  # El teléfono del usuario

    for error in errors:
        code = error.get("code")
        message = error.get("message")

        print(f"❌ Error de entrega a {recipient_id}: Código {code} - {message}")

        # ---------------------------------------------------------
        # ERROR 131047: Re-engagement Message (Ventana 24h cerrada)
        # ---------------------------------------------------------
        if code == 131047:
            print(f"🔄 INTENTO DE RECUPERACIÓN: Enviando plantilla a {recipient_id}...")

            # 1. Identificar al aspirante
            # Nota: Usamos recipient_id como wa_id (teléfono)
            creador_id = obtener_creador_id_por_telefono(recipient_id)

            if creador_id:
                # 2. Buscar en qué estado se quedó para enviar la plantilla correcta
                estado_actual = buscar_estado_creador(creador_id)

                if estado_actual:
                    # 3. Enviar la PLANTILLA correspondiente
                    # Esta función ya la definimos en "Tarea 3" y sabe qué template usar
                    enviar_plantilla_estado_evaluacion(
                        creador_id=creador_id,
                        estado_evaluacion=estado_actual,
                        phone_id=phone_id,
                        token=token,
                        telefono=recipient_id
                    )
                    print(f"✅ Plantilla de recuperación enviada a {recipient_id}")
                else:
                    print(f"⚠️ No se encontró estado para creador {creador_id}, no se pudo enviar plantilla.")
            else:
                print(f"⚠️ El destinatario {recipient_id} no es un aspirante registrado.")

        # ---------------------------------------------------------
        # OTROS ERRORES (Opcional)
        # ---------------------------------------------------------
        elif code == 131026:
            print("⚠️ Mensaje no entregado: Usuario bloqueó al bot o no tiene WhatsApp.")
            # Aquí podrías marcar al usuario como 'inactivo' en tu BD


def enviar_confirmacion_interactiva(numero, nickname, phone_id, token):
    """
    Envía un mensaje con dos botones: SÍ y NO.
    """
    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    mensaje_texto = f"Encontramos el usuario: *{nickname}*. ¿Eres tú?"

    payload = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": mensaje_texto},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {"id": "BTN_CONFIRM_YES", "title": "Sí, soy yo"}
                    },
                    {
                        "type": "reply",
                        "reply": {"id": "BTN_CONFIRM_NO", "title": "No, corregir"}
                    }
                ]
            }
        }
    }
    try:
        requests.post(url, headers=headers, json=payload)
    except Exception as e:
        print(f"Error enviando botones: {e}")

# def Enviar_menu_quickreply(creador_id, estado_evaluacion, phone_id, token, telefono):
#     """
#     Envía el menú real de opciones según el estado.
#     Se ejecuta cuando el usuario da clic en "Opciones".
#     """
#     botones = []
#     texto_menu = "Elige una opción:"
#
#     if estado_evaluacion == "solicitud_agendamiento_tiktok":
#         texto_menu = "¿Listo para tu prueba?"
#         botones = [
#             {"id": "BTN_ENVIAR_LINK_TIKTOK", "titulo": "Enviar Link Live"},
#             {"id": "BTN_VER_TUTORIAL", "titulo": "Ver Tutorial"}
#         ]
#     elif estado_evaluacion == "documentacion":
#         botones = [
#             {"id": "BTN_SUBIR_CEDULA", "titulo": "Subir Cédula"},
#             {"id": "BTN_HABLAR_ASESOR", "titulo": "Hablar Asesor"}
#         ]
#
#     # Construir estructura API (Máximo 3 botones para QuickReply interactivo)
#     botones_api = [{"type": "reply", "reply": b} for b in botones]
#
#     payload = {
#         "messaging_product": "whatsapp",
#         "to": telefono,
#         "type": "interactive",
#         "interactive": {
#             "type": "button",
#             "body": {"text": texto_menu},
#             "action": {"buttons": botones_api}
#         }
#     }
#     enviar_a_meta(payload, phone_id, token)
