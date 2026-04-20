import os

import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
import logging

from DataBase import get_connection_context, guardar_mensaje_nuevo, paso_limite_24h, buscar_usuario_por_telefono, \
    actualizar_phone_info_db
from enviar_msg_wp import enviar_mensaje_texto_simple, enviar_plantilla_generica
from tenant import current_business_name

logger = logging.getLogger("uvicorn.error")

router = APIRouter()   # ← ESTE ES EL ROUTER QUE VAS A IMPORTAR EN main.py

_cloudinary_configured = False


def _ensure_cloudinary_config() -> None:
    global _cloudinary_configured
    if _cloudinary_configured:
        return
    load_dotenv()
    cloudinary.config(
        cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key=os.environ["CLOUDINARY_API_KEY"],
        api_secret=os.environ["CLOUDINARY_API_SECRET"],
        secure=True,
    )
    _cloudinary_configured = True


import re
import requests
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlparse

# -------------------------------------------------------------------
# Validación de enlaces TikTok (p. ej. LIVE)
# -------------------------------------------------------------------
TIKTOK_DOMINIOS_VALIDOS = (
    "tiktok.com",
    "www.tiktok.com",
    "vt.tiktok.com",
)

PATRON_TIKTOK_URL = re.compile(
    r"(https?://[^\s]+tiktok\.com[^\s]*)",
    re.IGNORECASE,
)


def validar_link_tiktok(texto: str) -> bool:
    """
    Valida si el texto contiene un link válido de TikTok (idealmente de LIVE).
    """
    if not texto:
        return False

    match = PATRON_TIKTOK_URL.search(texto)
    if not match:
        return False

    url = match.group(1).strip()

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    dominio = parsed.netloc.lower()
    if dominio not in TIKTOK_DOMINIOS_VALIDOS:
        return False

    path = parsed.path.lower()
    if "live" not in path:
        return False

    return True


# # --- MOCK DE BASE DE DATOS (Reemplaza con tu lógica real SQL) ---
# def guardar_estado_eval(aspirante_id, estado):
#     # UPDATE aspirantes_perfil SET estado_evaluacion = estado WHERE aspirante_id = aspirante_id
#     print(f"💾 BD: Estado actualizado a '{estado}' para ID {aspirante_id}")
# Asegúrate de importar tu conexión
# from .db_config import get_connection_context

def guardar_estado_eval(aspirante_id, codigo_estado):
    """
    Actualiza la tabla aspirantes_perfil con el nuevo estado textual.
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # Guardamos el estado directamente como texto en aspirantes_perfil.estado_evaluacion
                query_update = """
                               UPDATE aspirantes_perfil
                               SET estado_evaluacion = %s
                               WHERE aspirante_id = %s \
                               """
                cur.execute(query_update, (codigo_estado, aspirante_id))
                conn.commit()

                print(f"💾 BD Actualizada: Creador {aspirante_id} -> Estado '{codigo_estado}'")
                return True

    except Exception as e:
        print(f"❌ Error al guardar estado en BD: {e}")
        return False

def buscar_estado_creador(aspirante_id):
    """
    Obtiene el estado actual del creador desde aspirantes_perfil.estado_evaluacion
    y devuelve estructura compatible con el flujo actual.
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                sql = """
                    SELECT
                        pc.estado_evaluacion
                    FROM aspirantes_perfil pc
                    WHERE pc.aspirante_id = %s
                """
                cur.execute(sql, (aspirante_id,))
                row = cur.fetchone()

                if row:
                    codigo_estado = row[0]
                    return {
                        "codigo_estado": codigo_estado,
                        "mensaje_frontend_simple": codigo_estado or "Estado no definido.",
                        "mensaje_chatbot_simple": codigo_estado or "Selecciona una opción:",
                    }

                return None

    except Exception as e:
        print(f"❌ Error al buscar estado del creador {aspirante_id}: {e}")
        return None



def obtener_aspirante_id_por_telefono(telefono):
    # SELECT aspirante_id FROM aspirantes_perfil WHERE telefono = ...
    return 3236


# def guardar_link_tiktok_live(aspirante_id, url):
#     # UPDATE aspirantes_perfil SET link_tiktok = url WHERE ...
#     print(f"💾 URL guardada: {url}")

from datetime import datetime


# Asegúrate de importar tu conexión
# from .db_config import get_connection_context

def guardar_link_tiktok_live(aspirante_id, url_tiktok):
    """
    Guarda la URL del Live de TikTok en la tabla de agendamientos.
    1. Busca el último agendamiento tipo 'LIVE' del creador.
    2. Si existe, actualiza el campo link_meet.
    3. Si no existe, crea un nuevo agendamiento en estado 'pendiente'.
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                # PASO 1: Buscar si ya existe un agendamiento 'LIVE' reciente (pendiente o programado)
                query_buscar = """
                               SELECT id \
                               FROM agendamientos
                               WHERE aspirante_id = %s
                                 AND tipo_agendamiento = 'LIVE'
                               ORDER BY id DESC LIMIT 1 \
                               """
                cur.execute(query_buscar, (aspirante_id,))
                resultado = cur.fetchone()

                if resultado:
                    # --- ESCENARIO A: ACTUALIZAR EXISTENTE ---
                    agendamiento_id = resultado[0]
                    query_update = """
                                   UPDATE agendamientos
                                   SET link_meet      = %s,
                                       actualizado_en = NOW()
                                   WHERE id = %s \
                                   """
                    cur.execute(query_update, (url_tiktok, agendamiento_id))
                    print(f"💾 Agendamiento {agendamiento_id} actualizado con Link TikTok.")

                else:
                    # --- ESCENARIO B: CREAR NUEVO (Si no había cita previa) ---
                    # Creamos un registro base para no perder el link
                    titulo = f"Prueba TikTok Live - Creador {aspirante_id}"
                    descripcion = "El usuario envió el link manualmente a través del Chatbot."

                    query_insert = """
                                   INSERT INTO agendamientos
                                   (aspirante_id, tipo_agendamiento, link_meet, estado_id, titulo, descripcion, creado_en)
                                   VALUES (%s, 'LIVE', %s, %s, %s, %s, NOW()) RETURNING id \
                                   """
                    cur.execute(query_insert, (aspirante_id, url_tiktok, 1, titulo, descripcion))
                    nuevo_id = cur.fetchone()[0]

                    # Opcional: Registrar también en la tabla de participantes para mantener consistencia
                    query_participante = """
                                         INSERT INTO agendamientos_participantes (
                                             agendamiento_id,
                                             participante_tipo_id,
                                             participante_id,
                                             estado
                                         )
                                         VALUES (%s, 1, %s, 'pendiente')
                                         """
                    cur.execute(query_participante, (nuevo_id, aspirante_id))

                    print(f"🆕 Nuevo agendamiento 'LIVE' creado (ID: {nuevo_id}) con Link TikTok.")

                conn.commit()
                return True

    except Exception as e:
        print(f"❌ Error guardando Link TikTok en agendamientos: {e}")
        return False

# def obtener_status_24hrs(telefono):
#     # Consultar last_interaction en BD
#     # Si (now - last_interaction) > 24h return False (Fuera de ventana)
#     # Si (now - last_interaction) < 24h return True (Dentro de ventana)
#     return False  # Simulamos que está dentro para pruebas

from datetime import datetime, timedelta, timezone
# Asegúrate de importar tu gestor de conexión
# from .db_config import get_connection_context


# --- FUNCIONES LÓGICAS ---

def validar_url_link_tiktok_live(url):
    """Valida si es un link de TikTok válido."""
    patron = r"(https?://)?(www\.|vm\.|vt\.)?tiktok\.com/.*"
    return bool(re.match(patron, url))


def Enviar_msg_estado(aspirante_id, estado_evaluacion, phone_id, token, telefono):
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


def enviar_plantilla_estado_evaluacion(aspirante_id, estado_evaluacion, phone_id, token, telefono):
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

def Enviar_menu_quickreply(aspirante_id, estado_evaluacion, phone_id, token, telefono):
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


def Enviar_menu_quickreplyV0(aspirante_id, estado_evaluacion, phone_id, token, telefono):
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

def Enviar_menu_quickreplyV1(aspirante_id, estado_evaluacion, phone_id, token, telefono):
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


def accion_menu_estado_evaluacion(
    aspirante_id: int,
    button_id: str,
    phone_id: str,
    token: str,
    estado_evaluacion: str,
    telefono: str,
):
    """
    Ejecuta la acción correspondiente al botón presionado en el menú de opciones.

    - button_id: payload/id recibido desde WhatsApp (ej: "MENU_AGENDAR_ENTREVISTA")
    - estado_evaluacion: código de estado actual del aspirante (solo informativo para logs)
    """

    print(f"⚡ Ejecutando acción: {button_id} (Estado origen: {estado_evaluacion})")

    # Normalización defensiva
    button_id = (button_id or "").strip()

    # ==========================================================
    # GRUPO 1: INGRESO DE DATOS (Cambian estado para esperar texto)
    # ==========================================================

    # A. PREGUNTAS FRECUENTES
    if button_id == "MENU_PREGUNTAS_FRECUENTES":
        # Leemos de la BD
        texto_faq = obtener_configuracion_texto(
            clave="faq_texto",
            valor_por_defecto="❓ Estamos actualizando nuestras preguntas frecuentes. Contacta a un asesor."
        )
        enviar_mensaje_texto_simple(token, phone_id, telefono, texto_faq)
        return

    # B. PROCESO DE INCORPORACIÓN
    if button_id == "MENU_PROCESO_INCORPORACION":
        texto_proceso = obtener_configuracion_texto(
            clave="proceso_incorp_texto",
            valor_por_defecto="🏢 *Proceso:*\n1. Registro\n2. Prueba\n3. Contrato"
        )
        enviar_mensaje_texto_simple(token, phone_id, telefono, texto_proceso)
        return



    if button_id == "MENU_INGRESAR_LINK_TIKTOK":
        print(f"🚀 [DB->REDIS] Activando escucha de Link para {telefono}")

        # A. Activamos la bandera en Redis (OJO: El nombre clave debe ser EXACTO)
        actualizar_flujo(telefono, "esperando_input_link_tiktok")

        # B. Enviamos el mensaje
        enviar_mensaje_texto_simple(
            token, phone_id, telefono,
            "🔗 *Ingresa tu Link de Live:*\n\n"
            "Por favor, pega aquí el enlace de tu transmisión (ej: tiktok.com/@usuario/live)."
        )
        return
        # # Cambiamos estado para que el próximo mensaje de texto sea capturado como URL
        # guardar_estado_eval(aspirante_id, "esperando_link_tiktok_live")
        # enviar_texto_simple(
        #     telefono,
        #     "🔗 Por favor, pega aquí el enlace de tu TikTok LIVE:",
        #     phone_id,
        #     token,
        # )
        # return

    if button_id == "MENU_INGRESAR_LINK_TIKTOK_2":
        guardar_estado_eval(aspirante_id, "esperando_link_tiktok_live_2")
        enviar_texto_simple(
            telefono,
            "🔗 Por favor, pega aquí el enlace de tu *segundo* TikTok LIVE:",
            phone_id,
            token,
        )
        return

    # ==========================================================
    # GRUPO 2: AGENDAMIENTO Y CALENDARIOS (Envío de Links)
    # ==========================================================
    if button_id == "MENU_AGENDAR_PRUEBA_TIKTOK":
        enviar_texto_simple(
            telefono,
            "📅 Agenda tu prueba aquí: https://calendly.com/tu-agencia/prueba-tiktok",
            phone_id,
            token,
        )
        return

    if button_id == "MENU_AGENDAR_PRUEBA_TIKTOK_2":
        enviar_texto_simple(
            telefono,
            "📅 Agenda tu segunda prueba aquí: https://calendly.com/tu-agencia/prueba-tiktok-2",
            phone_id,
            token,
        )
        return

    if button_id == "MENU_AGENDAR_ENTREVISTA":
        enviar_texto_simple(
            telefono,
            "👔 Agenda tu entrevista con un asesor aquí: https://calendly.com/tu-agencia/entrevista",
            phone_id,
            token,
        )
        return

    if button_id in {
        "MENU_MODIFICAR_CITA_PRUEBA",
        "MENU_MODIFICAR_CITA_PRUEBA_2",
        "MENU_MODIFICAR_CITA_ENTREVISTA",
    }:
        enviar_texto_simple(
            telefono,
            "🔄 Puedes reprogramar tu cita usando el mismo enlace que te enviamos al agendar, "
            "o contacta a soporte si tienes problemas.",
            phone_id,
            token,
        )
        return

    # ==========================================================
    # GRUPO 3: INFORMACIÓN Y GUÍAS (Envío de Texto/PDF/Links)
    # ==========================================================
    if button_id == "MENU_VER_GUIA_PRUEBA":
        enviar_texto_simple(
            telefono,
            "📘 Aquí tienes la guía para tu prueba: https://tu-agencia.com/guia-tiktok-pdf",
            phone_id,
            token,
        )
        # O podrías enviar un documento real usando enviar_documento(...)
        return

    if button_id == "MENU_VER_GUIA_PRUEBA_2":
        enviar_texto_simple(
            telefono,
            "📘 Guía avanzada para la prueba #2: https://tu-agencia.com/guia-tiktok-2-pdf",
            phone_id,
            token,
        )
        return

    if button_id == "MENU_PROCESO_INCORPORACION":
        msg = (
            "🏢 *Proceso de Incorporación:*\n"
            "1. Evaluación de perfil\n"
            "2. Prueba de transmisión\n"
            "3. Entrevista final\n"
            "4. Firma de contrato"
        )
        enviar_texto_simple(telefono, msg, phone_id, token)
        return

    if button_id == "MENU_PREGUNTAS_FRECUENTES":
        enviar_texto_simple(
            telefono,
            "❓ Revisa nuestras dudas frecuentes aquí: https://tu-agencia.com/faq",
            phone_id,
            token,
        )
        return

    if button_id == "MENU_VENTAJAS_AGENCIA":
        msg = (
            "🚀 *Ventajas Prestige:*\n"
            "✅ Soporte 24/7\n"
            "✅ Monetización mejorada\n"
            "✅ Eventos exclusivos"
        )
        enviar_texto_simple(telefono, msg, phone_id, token)
        return

    if button_id == "MENU_TEMAS_ENTREVISTA_2":
        enviar_texto_simple(
            telefono,
            "📝 En la entrevista hablaremos de: Disponibilidad, Metas financieras y Reglamento interno.",
            phone_id,
            token,
        )
        return

    # ==========================================================
    # GRUPO 4: ESTADOS Y RESULTADOS
    # ==========================================================
    if button_id == "MENU_RESULTADO_PRUEBA_1":
        # Aquí podrías consultar la BD real. Por ahora texto fijo:
        enviar_texto_simple(
            telefono,
            "📊 Tu prueba #1 fue: *APROBADA* (Puntaje: 85/100). ¡Sigue así!",
            phone_id,
            token,
        )
        return

    if button_id == "MENU_ESTADO_PROCESO":
        enviar_texto_simple(
            telefono,
            f"📍 Tu estado actual es: *{estado_evaluacion}*.",
            phone_id,
            token,
        )
        return

    # ==========================================================
    # GRUPO 5: ACCIONES CRÍTICAS (Aceptar oferta / Hablar con Humano)
    # ==========================================================
    if button_id == "MENU_ACEPTAR_INCORPORACION":
        guardar_estado_eval(aspirante_id, "incorporacion_en_tramite")
        enviar_texto_simple(
            telefono,
            "🎉 ¡Bienvenido a la familia! Un administrador te contactará pronto para finalizar el papeleo.",
            phone_id,
            token,
        )
        # Opcional: Notificar al admin aquí
        return

    if button_id == "MENU_CHAT_ASESOR":
        # Aquí podrías cambiar el flujo a "chat_libre" para que intervenga un humano
        # actualizar_flujo(telefono, "chat_libre")
        enviar_texto_simple(
            telefono,
            "💬 Hemos notificado a un asesor. Te escribirá en breve.",
            phone_id,
            token,
        )
        return

    # ==========================================================
    # DEFAULT
    # ==========================================================
    print(f"⚠️ Botón sin acción definida: {button_id}")
    enviar_texto_simple(
        telefono,
        "Esta opción está en mantenimiento.",
        phone_id,
        token,
    )


def accion_menu_estado_evaluacionV0(aspirante_id, button_id, phone_id, token, estado_evaluacion, telefono):
    """
    Ejecuta la acción final cuando el usuario selecciona una opción del menú.
    """
    print(f"⚡ Ejecutando acción: {button_id} para estado {estado_evaluacion}")

    if button_id == "BTN_ENVIAR_LINK_TIKTOK" and estado_evaluacion == "solicitud_agendamiento_tiktok":
        # 1. Cambiar estado para esperar texto
        guardar_estado_eval(aspirante_id, "solicitud_link_enviado")

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
# from services.aspirant_service import buscar_estado_creador, obtener_aspirante_id_por_telefono, enviar_plantilla_estado_evaluacion
# from services.db_service import actualizar_mensaje_desde_status

async def _handle_statuses(
    statuses,
    tenant_name,
    phone_number_id,
    token_access,
    business_name,
    raw_payload
):
    """
    Procesa la lista de estados (sent, delivered, read, failed).
    Detecta errores de ventana de 24h y dispara la recuperación con plantillas.
    """
    for status_obj in statuses:
        try:
            # 1. Actualizar BD siempre
            actualizar_mensaje_desde_status(
                tenant=tenant_name,
                phone_number_id=phone_number_id,
                display_phone_number=status_obj.get("recipient_id"),
                status_obj=status_obj,
                raw_payload=raw_payload
            )

            # 2. Detectar errores críticos
            if status_obj.get("status") == "failed":
                await _procesar_error_envio(
                    status_obj=status_obj,
                    tenant=tenant_name,
                    phone_id=phone_number_id,
                    token=token_access,
                    business_name=business_name
                )

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
    Actualiza el estado de un mensaje en mensajes_whatsapp
    usando message_id_meta.
    """
    try:
        message_id = status_obj.get("id")
        status = status_obj.get("status")
        timestamp = status_obj.get("timestamp")

        if not message_id:
            print("⚠️ Status sin message_id_meta, se ignora.")
            return

        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE mensajes_whatsapp
                    SET
                        estado = %s,
                        fecha = TO_TIMESTAMP(%s)
                    WHERE message_id_meta = %s;
                    """,
                    (
                        status,
                        int(timestamp) if timestamp else None,
                        message_id,
                    ),
                )

        print(f"📊 Status actualizado para mensaje {message_id}: {status}")

    except Exception as e:
        print(f"❌ Error actualizando status {status_obj.get('id', 'unknown')}: {e}")
        traceback.print_exc()

async def _procesar_error_envio(status_obj, tenant, phone_id, token, business_name):
    errors = status_obj.get("errors", [])
    recipient_id = status_obj.get("recipient_id")
    message_id_meta = status_obj.get("id")

    for error in errors:
        code = error.get("code")
        message = error.get("message")

        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE mensajes_whatsapp
                    SET estado  = 'failed',
                        error_codigo  = %s,
                        error_mensaje = %s
                    WHERE message_id_meta = %s
                    """,
                    (None if code is None else str(code), message, message_id_meta)
                )

        if code == 131047:
            print(f"🔄 Ventana cerrada para {recipient_id}. Enviando plantilla reconexion_general_corta")

            usuario = buscar_usuario_por_telefono(recipient_id)

            if isinstance(usuario, dict):
                nombre_creador = (
                    usuario.get("nombre")
                    or usuario.get("nickname")
                    or "Candidato"
                )
            else:
                nombre_creador = usuario or "Candidato"

            await enviar_plantilla_por_ventana_cerrada(
                telefono=recipient_id,
                nombre=nombre_creador,
                token=token,
                phone_number_id=phone_id,
                agencia_nombre=business_name,
                plantilla="reconexion_general_corta"
            )

async def enviar_plantilla_por_ventana_cerrada(
    *,
    telefono: str,
    nombre: str = "",
    token: str,
    phone_number_id: str,
    agencia_nombre: str = "",
    plantilla: str = "reconexion_general_corta",
    idioma: str = "es_CO",
) -> Tuple[bool, Dict[str, Any]]:

    if not telefono:
        return False, {"status": "skip", "reason": "telefono_vacio"}

    params = [
        (nombre or "").strip() or "Candidato",
        (agencia_nombre or "").strip() or "Nuestro equipo"
    ]

    codigo, respuesta_api = enviar_plantilla_generica(
        token=token,
        phone_number_id=phone_number_id,
        numero_destino=telefono,
        nombre_plantilla=plantilla,
        codigo_idioma=idioma,
        parametros=params
    )

    message_id_meta = None
    if respuesta_api and isinstance(respuesta_api, dict) and "messages" in respuesta_api:
        try:
            message_id_meta = respuesta_api["messages"][0].get("id")
        except Exception:
            pass

    guardar_mensaje_nuevo(
        telefono=telefono,
        contenido=f"Plantilla auto por ventana cerrada: {plantilla}",
        direccion="enviado",
        tipo="template",
        message_id_meta=message_id_meta,
        estado="sent" if codigo == 200 else "failed"
    )

    return True, {
        "status": "plantilla_auto",
        "mensaje": "Se envió plantilla por ventana cerrada detectada desde webhook.",
        "plantilla": plantilla,
        "codigo_api": codigo,
        "respuesta_api": respuesta_api
    }

# async def _procesar_error_envio(status_obj, tenant, phone_id, token):
#     errors = status_obj.get("errors", [])
#     recipient_id = status_obj.get("recipient_id")
#     message_id_meta = status_obj.get("id")  # El ID del mensaje que falló
#
#     for error in errors:
#         code = error.get("code")
#         message = error.get("message")
#
#         # 1. Registrar el error en la base de datos para el mensaje específico
#         with get_connection_context() as conn:
#             with conn.cursor() as cur:
#                 cur.execute(
#                     """
#                     UPDATE mensajes_whatsapp
#                     SET estado        = 'failed',
#                         error_codigo  = %s,
#                         error_mensaje = %s
#                     WHERE message_id_meta = %s
#                     """,
#                     (code, message, message_id_meta)
#                 )
#
#         # 2. Si el error es por ventana de 24h (Código 131047)
#         if code == 131047:
#             print(f"🔄 Ventana cerrada para {recipient_id}. Enviando reconexion_general_corta")
#
#             # Buscamos el nombre del creador para personalizar la plantilla
#             nombre_creador = buscar_usuario_por_telefono(recipient_id) or "Candidato"
#
#             # Enviamos la plantilla de reconexión
#             await intentar_plantilla_reconexion_24h(
#                 telefono=recipient_id,
#                 nombre=nombre_creador,
#                 token=token,
#                 phone_number_id=phone_id,
#                 plantilla="reconexion_general_corta"
#             )

def intentar_plantilla_reconexion_24h(
    *,
    telefono: str,
    nombre: str = "",
    token: str,
    phone_number_id: str,
    agencia_nombre: str = "",
    plantilla: str = "reconexion_general_corta",
    idioma: str = "es_CO",
) -> Tuple[bool, Dict[str, Any]]:

    if not telefono:
        return False, {"status": "skip", "reason": "telefono_vacio"}

    if not paso_limite_24h(telefono):
        return False, {"status": "skip", "reason": "dentro_24h"}

    # ✅ Fuera de 24h → plantilla
    params = [
        (nombre or "").strip() or "",
        agencia_nombre or "Nuestro equipo"
    ]

    codigo, respuesta_api = enviar_plantilla_generica(
        token=token,
        phone_number_id=phone_number_id,
        numero_destino=telefono,
        nombre_plantilla=plantilla,
        codigo_idioma=idioma,
        parametros=params
    )

    # message_id_meta
    message_id_meta = None
    if respuesta_api and isinstance(respuesta_api, dict) and "messages" in respuesta_api:
        try:
            message_id_meta = respuesta_api["messages"][0].get("id")
        except Exception:
            pass

    # Guardar en BD
    guardar_mensaje_nuevo(
        telefono=telefono,
        contenido=f"Plantilla auto 24h: {plantilla}",
        direccion="enviado",
        tipo="template",
        message_id_meta=message_id_meta,
        estado="sent" if codigo == 200 else "failed"
    )

    return True, {
        "status": "plantilla_auto",
        "mensaje": "Se envió plantilla por estar fuera de ventana de 24h.",
        "plantilla": plantilla,
        "codigo_api": codigo,
        "respuesta_api": respuesta_api
    }

async def _procesar_error_envioV0(status_obj, tenant, phone_id, token):
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
            aspirante_id = obtener_aspirante_id_por_telefono(recipient_id)

            if aspirante_id:
                # 2. Buscar en qué estado se quedó para enviar la plantilla correcta
                estado_actual = buscar_estado_creador(aspirante_id)

                if estado_actual:
                    # 3. Enviar la PLANTILLA correspondiente
                    # Esta función ya la definimos en "Tarea 3" y sabe qué template usar
                    codigo_estado = estado_actual.get("codigo_estado")

                    enviar_plantilla_estado_evaluacion(
                        aspirante_id=aspirante_id,
                        estado_evaluacion=codigo_estado,  # 👈 SOLO el string,
                        phone_id=phone_id,
                        token=token,
                        telefono=recipient_id
                    )
                    print(f"✅ Plantilla de recuperación enviada a {recipient_id}")
                else:
                    print(f"⚠️ No se encontró estado para creador {aspirante_id}, no se pudo enviar plantilla.")
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



# --------------------------------------------------------
# --------------------------------------------------------
# --------------------------------------------------------
# --------------------------------------------------------
# --------------------------------------------------------
# --------------------------------------------------------
# --------------CODIGO PARA FLUJO DE LINK DE TIKTOK-


# Asegúrate de importar esto al inicio del archivo
from redis_client import actualizar_flujo, obtener_flujo, eliminar_flujo


def manejar_input_link_tiktok(aspirante_id, wa_id, tipo, texto, payload, token, phone_id):
    """
    PROCESADOR: Solo actúa si el usuario ya tiene la bandera de Redis activa.
    No maneja el clic inicial (eso lo hace accion_menu_estado_evaluacion).
    """
    # Consultar Redis
    paso_actual = obtener_flujo(wa_id)

    # [LOG DE DIAGNÓSTICO CRÍTICO] 🔍
    print(f"🛑 [DEBUG REDIS] Usuario: '{wa_id}' | Paso en Redis: '{paso_actual}'")
    print(f"🧐 [DEBUG CHECK] ¿Coincide? '{paso_actual}' == 'esperando_input_link_tiktok'")


    # Solo entramos si Redis dice que estamos esperando el link
    # (La clave "esperando_input_link_tiktok" debe coincidir con la de accion_menu)
    if paso_actual == "esperando_input_link_tiktok":

        # 🛡️ SALIDA DE EMERGENCIA:
        # Si el usuario presiona CUALQUIER botón, cancelamos la espera.
        if payload:
            print(f"⚠️ [REDIS] Usuario presionó botón '{payload}'. Cancelando espera de Link.")
            eliminar_flujo(wa_id)
            return False  # Dejamos pasar para que el Router maneje el botón

        # Validación de tipo de mensaje (debe ser texto)
        if tipo != "text":
            enviar_mensaje_texto_simple(token, phone_id, wa_id, "✍️ Por favor envía el enlace en formato texto.")
            return True

        print(f"🔍 [REDIS] Validando URL recibida: {texto}")

        # Lógica de Validación
        if validar_url_link_tiktok_live(texto):
            # ✅ ÉXITO
            guardar_link_tiktok_live(aspirante_id, texto)  # Guardar dato
            # guardar_estado_eval(aspirante_id, "revision_link_tiktok")  # Avanzar estado negocio
            eliminar_flujo(wa_id)  # Limpiar memoria

            enviar_mensaje_texto_simple(
                token, phone_id, wa_id,
                "✅ ¡Link guardado! Lo hemos enviado a revisión."
            )
        else:
            # ❌ ERROR (Damos otra oportunidad sin borrar Redis)
            enviar_mensaje_texto_simple(
                token, phone_id, wa_id,
                "❌ Enlace no válido. Asegúrate de copiar la URL completa (tiktok.com/...) y pégala nuevamente."
            )

        return True  # Mensaje consumido

    # Si no estamos esperando nada, ignoramos.
    return False


def manejar_input_link_tiktokv1(aspirante_id, wa_id, tipo, texto, payload, token, phone_id):
    """
    Gestiona el micro-flujo para capturar el Link de TikTok usando Redis.
    Retorna True si el mensaje fue procesado (consumido).
    Retorna False si el router principal debe seguir buscando qué hacer.
    """

    # 1. Consultar en qué paso temporal está el usuario
    paso_actual = obtener_flujo(wa_id)

    # ------------------------------------------------------------------
    # ESCENARIO A: DETONANTE (El usuario hace clic en el botón "Ingresar Link")
    # ------------------------------------------------------------------
    if payload == "MENU_INGRESAR_LINK_TIKTOK":
        print(f"🚀 [REDIS] Iniciando captura de Link para {wa_id}")

        # Guardamos en Redis que estamos esperando el link (TTL 10 min)
        actualizar_flujo(wa_id, "esperando_input_link_tiktok")

        enviar_mensaje_texto_simple(
            token, phone_id, wa_id,
            "🔗 *Ingresa tu Link de Live:*\n\n"
            "Pega aquí el enlace (ej: tiktok.com/@usuario/live). "
            "El sistema lo validará automáticamente."
        )
        return True  # ✅ Mensaje consumido, no sigue al router

    # ------------------------------------------------------------------
    # ESCENARIO B: PROCESAMIENTO (El usuario ya estaba esperando y envía texto)
    # ------------------------------------------------------------------
    if paso_actual == "esperando_input_link_tiktok":

        # 🛡️ SALIDA DE EMERGENCIA:
        # Si el usuario se arrepiente y presiona OTRO botón del menú (ej: Ver Guía)
        if payload and payload.startswith("MENU_"):
            print(f"⚠️ [REDIS] Usuario cambió de opción. Cancelando espera de Link.")
            eliminar_flujo(wa_id)
            return False  # ❌ Devolvemos False para que el router ejecute el nuevo botón

        # Validación de tipo de mensaje
        if tipo != "text":
            enviar_mensaje_texto_simple(token, phone_id, wa_id, "✍️ Por favor envía el enlace en formato texto.")
            return True

        print(f"🔍 [REDIS] Validando URL recibida: {texto}")

        if validar_url_link_tiktok_live(texto):
            # ✅ ÉXITO
            # 1. Persistencia Permanente (Postgres)
            guardar_link_tiktok_live(aspirante_id, texto)
            guardar_estado_eval(aspirante_id, "revision_link_tiktok")  # Avanzamos estado de negocio

            # 2. Limpieza Temporal (Redis) - Ya no necesitamos esperar
            eliminar_flujo(wa_id)

            # 3. Respuesta
            enviar_mensaje_texto_simple(
                token, phone_id, wa_id,
                "✅ ¡Link guardado! Lo hemos enviado a revisión."
            )
        else:
            # ❌ ERROR (No borramos el flujo en Redis, le damos otra oportunidad)
            enviar_mensaje_texto_simple(
                token, phone_id, wa_id,
                "❌ Enlace no válido.\nVerifica que empiece por 'tiktok.com' y pégalo de nuevo."
            )

        return True  # ✅ Mensaje consumido

    # Si no es el botón ni estamos esperando nada, ignoramos.
    return False


# services/db_service.py

def obtener_configuracion_texto(clave, valor_por_defecto="Información no disponible."):
    """
    Busca un texto configurado en la tabla 'configuracion_agencia'.
    Si no existe, retorna el valor_por_defecto.
    INCLUYE: Corrección automática de saltos de línea.
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                query = "SELECT valor FROM configuracion_agencia WHERE clave = %s"
                cur.execute(query, (clave,))
                resultado = cur.fetchone()

                if resultado:
                    texto_bd = resultado[0]

                    # 🪄 LA MAGIA: Convertimos el literal "\n" en un salto de línea real
                    if texto_bd:
                        return texto_bd.replace('\\n', '\n')

                    return texto_bd
                else:
                    return valor_por_defecto
    except Exception as e:
        print(f"❌ Error leyendo configuración ({clave}): {e}")
        return valor_por_defecto

def obtener_status_24hrs(telefono):
    """
    Verifica si el número tiene una sesión de 24h activa (Ventana de Atención).
    Retorna True si la ventana está ABIERTA.
    Retorna False si la ventana está CERRADA.
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # 1. Buscamos el último mensaje ENTRANTE (inbound) de ese teléfono
                # Usamos la tabla 'mensajes_whatsapp'
                query = """
                    SELECT fecha
                    FROM mensajes_whatsapp
                    WHERE telefono = %s
                      AND direccion = 'recibido'
                    ORDER BY fecha DESC
                    LIMIT 1
                """
                cur.execute(query, (telefono,))
                row = cur.fetchone()

                # CASO A: El usuario nunca ha escrito
                if not row:
                    return False

                # CASO B: Calcular diferencia de tiempo
                ultima_interaccion = row[0]  # TIMESTAMPTZ

                # Obtenemos la hora actual en UTC
                ahora = datetime.now(timezone.utc)

                diferencia = ahora - ultima_interaccion

                # Verificamos si pasaron menos de 24 horas
                return diferencia < timedelta(hours=24)

    except Exception as e:
        print(f"❌ Error consultando status 24hrs: {e}")
        # Por seguridad, si falla la BD, asumimos ventana CERRADA para evitar bloqueos de Meta
        return False

import re
import logging
from datetime import datetime
from psycopg2 import DatabaseError

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------
# ------------------------------------------------------------------------
# ----------------------FUNCION OBSOLETA 20-03-2026 OJO!!!!!--------------------
# ------------------------------------------------------------------------
# ------------------------------------------------------------------------


# def Enviar_menu_quickreply(aspirante_id, estado_evaluacion, phone_id, token, telefono):
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


# ------------------------------------------------
# ------------------------------------------------
# ------------REVISAR SI SE QUITAN LAS SIGUIENTES-
# ------------------------------------------------


@router.post("/creadores_activos/{creador_activo_id}/foto")
async def subir_foto_creador_activo(creador_activo_id: int, foto: UploadFile = File(...)):
    try:
        _ensure_cloudinary_config()
        contents = await foto.read()
        result = cloudinary.uploader.upload(
            contents,
            folder=f"creadores_activos/{creador_activo_id}",
            public_id=f"foto_{creador_activo_id}",
            overwrite=True,
            resource_type="image",
        )
        url_foto = result["secure_url"]
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE creadores_activos SET foto = %s WHERE id = %s",
                    (url_foto, creador_activo_id),
                )
                conn.commit()
        return {"foto_url": url_foto}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al subir la foto: {e}")


import secrets
import string

ALFABETO_TOKEN = string.ascii_letters + string.digits


def generar_token_aleatorio(longitud: int = 10) -> str:
    return ''.join(secrets.choice(ALFABETO_TOKEN) for _ in range(longitud))


def crear_link_agendamiento_token(
    cur,
    aspirante_id: int,
    responsable_id: int,
    duracion_minutos: int = 60,
    tipo_agendamiento: str = "ENTREVISTA",
    horas_expiracion: int = 48,
    longitud_token: int = 10,
    max_intentos: int = 5,
):
    """
    Genera un token único, lo guarda en la tabla agendamientos_link_tokens
    y retorna token + expiración.
    """
    expiracion = datetime.now() + timedelta(hours=horas_expiracion)

    for _ in range(max_intentos):
        token = generar_token_aleatorio(longitud_token)

        cur.execute(
            """
            SELECT 1
            FROM agendamientos_link_tokens
            WHERE token = %s
            """,
            (token,)
        )
        existe = cur.fetchone()

        if existe:
            continue

        cur.execute(
            """
            INSERT INTO agendamientos_link_tokens (
                token,
                aspirante_id,
                responsable_id,
                expiracion,
                usado,
                duracion_minutos,
                tipo_agendamiento
            )
            VALUES (%s, %s, %s, %s, false, %s, %s)
            """,
            (
                token,
                aspirante_id,
                responsable_id,
                expiracion,
                duracion_minutos,
                tipo_agendamiento,
            )
        )

        return {
            "token": token,
            "expiracion": expiracion,
        }

    raise HTTPException(
        status_code=500,
        detail="No fue posible generar un token único de agendamiento."
    )


def registrar_cambio_estado(
    aspirante_id: int,
    nuevo_estado_id: int,
    usuario_id: int = None,
    origen_cambio: str = None,
    observacion: str = None
) -> bool:
    """
    Cambia el estado del aspirante y registra el historial.

    Retorna:
        True si hubo cambio
        False si ya estaba en ese estado
    """
    try:
        with get_connection_context() as conn:
            cur = conn.cursor()

            # Obtener estado actual
            cur.execute("""
                SELECT estado_id
                FROM aspirantes
                WHERE id = %s
            """, (aspirante_id,))
            row = cur.fetchone()

            if not row:
                return False

            estado_actual = row[0]

            # Si ya está en ese estado, no hacer nada
            if estado_actual == nuevo_estado_id:
                return False

            # Actualizar estado
            cur.execute("""
                UPDATE aspirantes
                SET estado_id = %s,
                    actualizado_en = now()
                WHERE id = %s
            """, (nuevo_estado_id, aspirante_id))

            # Insertar historial
            cur.execute("""
                INSERT INTO aspirantes_estado_historial (
                    aspirante_id,
                    estado_id,
                    fecha_cambio,
                    usuario_id,
                    origen_cambio,
                    observacion,
                    created_at
                )
                VALUES (%s, %s, now(), %s, %s, %s, now())
            """, (
                aspirante_id,
                nuevo_estado_id,
                usuario_id,
                origen_cambio,
                observacion
            ))

            conn.commit()
            return True

    except Exception as e:
        print(f"❌ Error en registrar_cambio_estado: {e}")
        return False