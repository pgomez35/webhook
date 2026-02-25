import os
from fastapi import APIRouter, HTTPException, Depends
import logging

from DataBase import get_connection_context
from enviar_msg_wp import enviar_mensaje_texto_simple

logger = logging.getLogger("uvicorn.error")

router = APIRouter()   # ← ESTE ES EL ROUTER QUE VAS A IMPORTAR EN main.py

import re
import requests
import json
from datetime import datetime, timedelta


# # --- MOCK DE BASE DE DATOS (Reemplaza con tu lógica real SQL) ---
# def guardar_estado_eval(creador_id, estado):
#     # UPDATE perfil_creador SET estado_evaluacion = estado WHERE creador_id = creador_id
#     print(f"💾 BD: Estado actualizado a '{estado}' para ID {creador_id}")
# Asegúrate de importar tu conexión
# from .db_config import get_connection_context

def guardar_estado_eval(creador_id, codigo_estado):
    """
    Actualiza la tabla perfil_creador con el nuevo estado.
    1. Busca el ID numérico del estado en 'chatbot_estados_aspirante' usando el código.
    2. Actualiza 'perfil_creador'.
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # PASO 1: Obtener el ID numérico basado en el texto (ej: 'esperando_link...')
                query_lookup = """
                               SELECT id_chatbot_estado
                               FROM chatbot_estados_aspirante
                               WHERE codigo = %s \
                               """
                cur.execute(query_lookup, (codigo_estado,))
                row = cur.fetchone()

                if not row:
                    print(
                        f"❌ ERROR CRÍTICO: El estado '{codigo_estado}' NO EXISTE en la tabla 'chatbot_estados_aspirante'.")
                    print("💡 Solución: Debes insertar este estado en la tabla de configuración SQL primero.")
                    return False

                id_estado_numerico = row[0]

                # PASO 2: Actualizar el perfil del creador
                query_update = """
                               UPDATE perfil_creador
                               SET id_chatbot_estado = %s
                               WHERE creador_id = %s \
                               """
                cur.execute(query_update, (id_estado_numerico, creador_id))
                conn.commit()

                print(f"💾 BD Actualizada: Creador {creador_id} -> Estado '{codigo_estado}' (ID: {id_estado_numerico})")
                return True

    except Exception as e:
        print(f"❌ Error al guardar estado en BD: {e}")
        return False

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


# def guardar_link_tiktok_live(creador_id, url):
#     # UPDATE perfil_creador SET link_tiktok = url WHERE ...
#     print(f"💾 URL guardada: {url}")

from datetime import datetime


# Asegúrate de importar tu conexión
# from .db_config import get_connection_context

def guardar_link_tiktok_live(creador_id, url_tiktok):
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
                               FROM test.agendamientos
                               WHERE creador_id = %s
                                 AND tipo_agendamiento = 'LIVE'
                               ORDER BY id DESC LIMIT 1 \
                               """
                cur.execute(query_buscar, (creador_id,))
                resultado = cur.fetchone()

                if resultado:
                    # --- ESCENARIO A: ACTUALIZAR EXISTENTE ---
                    agendamiento_id = resultado[0]
                    query_update = """
                                   UPDATE test.agendamientos
                                   SET link_meet      = %s,
                                       actualizado_en = NOW()
                                   WHERE id = %s \
                                   """
                    cur.execute(query_update, (url_tiktok, agendamiento_id))
                    print(f"💾 Agendamiento {agendamiento_id} actualizado con Link TikTok.")

                else:
                    # --- ESCENARIO B: CREAR NUEVO (Si no había cita previa) ---
                    # Creamos un registro base para no perder el link
                    titulo = f"Prueba TikTok Live - Creador {creador_id}"
                    descripcion = "El usuario envió el link manualmente a través del Chatbot."

                    query_insert = """
                                   INSERT INTO test.agendamientos
                                   (creador_id, tipo_agendamiento, link_meet, estado, titulo, descripcion, creado_en)
                                   VALUES (%s, 'LIVE', %s, 'pendiente', %s, %s, NOW()) RETURNING id \
                                   """
                    cur.execute(query_insert, (creador_id, url_tiktok, titulo, descripcion))
                    nuevo_id = cur.fetchone()[0]

                    # Opcional: Registrar también en la tabla de participantes para mantener consistencia
                    query_participante = """
                                         INSERT INTO test.agendamientos_participantes (agendamiento_id, creador_id, estado)
                                         VALUES (%s, %s, 'pendiente') \
                                         """
                    cur.execute(query_participante, (nuevo_id, creador_id))

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


def accion_menu_estado_evaluacion(
    creador_id: int,
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
        # guardar_estado_eval(creador_id, "esperando_link_tiktok_live")
        # enviar_texto_simple(
        #     telefono,
        #     "🔗 Por favor, pega aquí el enlace de tu TikTok LIVE:",
        #     phone_id,
        #     token,
        # )
        # return

    if button_id == "MENU_INGRESAR_LINK_TIKTOK_2":
        guardar_estado_eval(creador_id, "esperando_link_tiktok_live_2")
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
        guardar_estado_eval(creador_id, "incorporacion_en_tramite")
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
    Actualiza el estado de un mensaje en test.mensajes_whatsapp
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
                    codigo_estado = estado_actual.get("codigo_estado")

                    enviar_plantilla_estado_evaluacion(
                        creador_id=creador_id,
                        estado_evaluacion=codigo_estado,  # 👈 SOLO el string,
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



# --------------------------------------------------------
# --------------------------------------------------------
# --------------------------------------------------------
# --------------------------------------------------------
# --------------------------------------------------------
# --------------------------------------------------------
# --------------CODIGO PARA FLUJO DE LINK DE TIKTOK-


# Asegúrate de importar esto al inicio del archivo
from redis_client import actualizar_flujo, obtener_flujo, eliminar_flujo


def manejar_input_link_tiktok(creador_id, wa_id, tipo, texto, payload, token, phone_id):
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
            guardar_link_tiktok_live(creador_id, texto)  # Guardar dato
            # guardar_estado_eval(creador_id, "revision_link_tiktok")  # Avanzar estado negocio
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


def manejar_input_link_tiktokv1(creador_id, wa_id, tipo, texto, payload, token, phone_id):
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
            guardar_link_tiktok_live(creador_id, texto)
            guardar_estado_eval(creador_id, "revision_link_tiktok")  # Avanzamos estado de negocio

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
                query = "SELECT valor FROM test.configuracion_agencia WHERE clave = %s"
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
                # Usamos la tabla 'test.mensajes_whatsapp'
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










