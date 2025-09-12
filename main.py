# ✅ main.py
from fastapi import FastAPI, HTTPException, Path, Body, Request, UploadFile, Form,File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import pandas as pd
import io

# Respuestas personalizadas (usa solo si las necesitas)
from fastapi.responses import JSONResponse, PlainTextResponse

from dotenv import load_dotenv  # Solo si usas variables de entorno
import os
import json
import re
import logging
import subprocess
import traceback

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel

# Integración Google Calendar
from dateutil.parser import isoparse

from google.oauth2.credentials import Credentials as UserCredentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import psycopg2
from schemas import *

from googleapiclient.discovery import build
from uuid import uuid4

# Tu propio código/librerías
from enviar_msg_wp import *
from buscador import inicializar_busqueda, responder_pregunta
from DataBase import *
from Excel import *

import cloudinary

cloudinary.config(
    cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
    api_key=os.environ["CLOUDINARY_API_KEY"],
    api_secret=os.environ["CLOUDINARY_API_SECRET"],
    secure=True
)

# 🔄 Cargar variables de entorno
load_dotenv()
API_KEY = os.getenv("OPENAI_API_KEY")
TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "142848PITUFO")
CHROMA_DIR = "./chroma_faq_openai"

# SERVICE_ACCOUNT_FILE = "credentials.json"
SERVICE_ACCOUNT_INFO = os.getenv("GOOGLE_CREDENTIALS_JSON")
# CALENDAR_ID="primary"
# CALENDAR_ID = "atavillamil.prestige@gmail.com"  # ID del calendario Prestige
CALENDAR_ID = os.getenv("CALENDAR_ID")
# CALENDAR_ID = "primary" # para que sea siempre primary, pero tambien puedo configurarlo en variables del backend

from perfil_creador_whatsapp import router as perfil_creador_router

# ⚙️ Inicializar FastAPI
app = FastAPI()


# Incluir las rutas del módulo perfil_creador_whatsapp
app.include_router(perfil_creador_router, tags=["Perfil Creador WhatsApp"])

# ✅ Crear carpeta persistente de audios si no existe
AUDIO_DIR = "audios"
os.makedirs(AUDIO_DIR, exist_ok=True)

# ✅ Montar ruta para servir archivos estáticos desde /audios
app.mount("/audios", StaticFiles(directory=AUDIO_DIR), name="audios")

# Configurar CORS para permitir peticiones del frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🧠 Inicializar búsqueda semántica
client, collection = inicializar_busqueda(API_KEY, persist_dir=CHROMA_DIR)

# ==================== PROYECTO CALENDAR ===========================
# === Configuración ===
SCOPES = ['https://www.googleapis.com/auth/calendar']
DB_URL = os.getenv("INTERNAL_DATABASE_URL")  # Debe estar en tus variables de entorno

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("calendar_sync")


# Middleware para manejo de errores
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"❌ Error no manejado: {str(exc)}")
    logger.error(traceback.format_exc())
    try:
        return JSONResponse(
            status_code=500,
            content={"detail": "Error interno del servidor"}
        )
    except Exception as e:
        # fallback por si JSONResponse se rompe
        return PlainTextResponse(
            str(e),
            status_code=500
        )

# ==================== FUNCIONES DE BD PARA TOKEN ===========================

def guardar_token_en_bd(token_dict, nombre='calendar'):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO google_tokens (nombre, token_json, actualizado)
            VALUES (%s, %s, %s)
            ON CONFLICT (nombre)
            DO UPDATE SET token_json = EXCLUDED.token_json, actualizado = EXCLUDED.actualizado;
        """, (nombre, json.dumps(token_dict), datetime.utcnow()))
        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ Token guardado en la base de datos.")
    except Exception as e:
        logger.error(f"❌ Error al guardar el token en la base de datos: {e}")
        raise

def leer_token_de_bd(nombre='calendar'):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT token_json FROM google_tokens WHERE nombre = %s LIMIT 1;",
            (nombre,)
        )
        fila = cur.fetchone()
        cur.close()
        conn.close()
        if not fila:
            raise Exception(f"⚠️ No se encontró ningún token con nombre '{nombre}' en la base de datos.")
        # Puede salir como str o dict, asegúrate de parsear
        token_info = fila[0]
        if isinstance(token_info, str):
            token_info = json.loads(token_info)
        # Asegura el campo type
        if "type" not in token_info:
            token_info["type"] = "authorized_user"
        return token_info
    except Exception as e:
        logger.error(f"❌ Error al leer el token de la base de datos: {e}")
        raise

# ==================== GOOGLE CALENDAR SERVICE ==============================
from google.oauth2 import service_account
def get_calendar_service():
    try:
        SCOPES = ["https://www.googleapis.com/auth/calendar"]
        creds_dict = json.loads(SERVICE_ACCOUNT_INFO)  # string JSON desde env
        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=SCOPES
        )

        # 👉 Impersonar al usuario de Workspace
        delegated_creds = creds.with_subject(os.getenv("CALENDAR_ID"))

        service = build("calendar", "v3", credentials=delegated_creds)
        logger.info(f"✅ Servicio de Google Calendar inicializado con impersonación como {os.getenv('CALENDAR_ID')}")
        return service

    except Exception as e:
        logger.error("❌ Error al inicializar el servicio de Google Calendar:")
        logger.error(traceback.format_exc())
        raise

# def get_calendar_service():
#     try:
#         SCOPES = ["https://www.googleapis.com/auth/calendar"]
#         # SERVICE_ACCOUNT_FILE = "credentials.json"
#         # CALENDAR_ID = "atavillamil.prestige@gmail.com"  # ID del calendario Prestige
#
#         creds_dict = json.loads(SERVICE_ACCOUNT_INFO)  # convierte string → dict
#         creds = service_account.Credentials.from_service_account_info(
#             creds_dict, scopes=SCOPES
#         )
#
#         service = build("calendar", "v3", credentials=creds)
#         logger.info("✅ Servicio de Google Calendar inicializado con cuenta de servicio.")
#         return service
#     except Exception as e:
#         logger.error("❌ Error al inicializar el servicio de Google Calendar:")
#         logger.error(traceback.format_exc())
#         raise

def get_calendar_service_():
    try:
        token_info = leer_token_de_bd()
        creds = UserCredentials.from_authorized_user_info(token_info, SCOPES)

        if not creds.valid:
            if creds.expired and creds.refresh_token:
                logger.warning("⚠️ Token expirado. Refrescando...")
                creds.refresh(GoogleRequest())
                guardar_token_en_bd(json.loads(creds.to_json()))
                logger.info("✅ Token refrescado y guardado en la base de datos.")
            else:
                raise Exception("❌ Token inválido y no puede ser refrescado (sin refresh_token)")

        service = build("calendar", "v3", credentials=creds)
        logger.info("📅 Servicio de Google Calendar inicializado correctamente.")
        return service

    except Exception as e:
        logger.error("❌ Error al inicializar el servicio de Google Calendar:")
        logger.error(traceback.format_exc())
        raise

def obtener_eventos() -> List[EventoOut]:
    try:
        service = get_calendar_service()
    except Exception as e:
        logger.error(f"❌ Error al obtener el servicio de Calendar: {str(e)}")
        raise

    hace_30_dias = (datetime.utcnow() - timedelta(days=30)).isoformat() + 'Z'
    un_ano_futuro = (datetime.utcnow() + timedelta(days=365)).isoformat() + 'Z'

    try:
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=hace_30_dias,
            timeMax=un_ano_futuro,
            maxResults=100,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
    except Exception as e:
        logger.error(f"❌ Error al obtener eventos de Google Calendar API: {str(e)}")
        logger.error(traceback.format_exc())
        raise

    events = events_result.get('items', [])
    resultado = []

    for event in events:
        try:
            inicio = event['start'].get('dateTime')
            fin = event['end'].get('dateTime')
            titulo = event.get('summary', 'Sin título')
            descripcion = event.get('description', '')
            event_id = event['id']

            meet_link = None
            if 'conferenceData' in event:
                entry_points = event['conferenceData'].get('entryPoints', [])
                for ep in entry_points:
                    if ep.get('entryPointType') == 'video':
                        meet_link = ep.get('uri')
                        break

            # Obtener participantes desde la base de datos
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT c.id, c.nombre_real as nombre, c.nickname
                FROM agendamientos_participantes ap
                JOIN creadores c ON c.id = ap.creador_id
                JOIN agendamientos a ON a.id = ap.agendamiento_id
                WHERE a.google_event_id = %s
            """, (event_id,))
            participantes = cur.fetchall()
            participantes_ids = [p[0] for p in participantes]
            participantes_out = [{"id": p[0], "nombre": p[1], "nickname": p[2]} for p in participantes]
            cur.close()
            conn.close()

            if inicio and fin:
                resultado.append(EventoOut(
                    id=event_id,
                    titulo=titulo,
                    inicio=isoparse(inicio),
                    fin=isoparse(fin),
                    descripcion=descripcion,
                    link_meet=meet_link,
                    participantes_ids=participantes_ids,
                    participantes=participantes_out,
                    origen="google_calendar"
                ))

        except Exception as e:
            logger.warning(f"⚠️ Saltando evento con error: {event.get('id', 'unknown')} - {str(e)}")
            continue

    logger.info(f"✅ Se obtuvieron {len(resultado)} eventos de Google Calendar")
    return resultado


def sync_eventos():
    eventos = obtener_eventos()
    logger.info(f"🔄 Se encontraron {len(eventos)} eventos en Google Calendar")
    for evento in eventos:
        logger.info(f"📅 Evento: {evento.titulo} | 🕐 Inicio: {evento.inicio} | 🕓 Fin: {evento.fin} | 📝 Descripción: {evento.descripcion}")

# ==================== RUTAS FASTAPI ==============================

from googleapiclient.errors import HttpError

@app.get("/api/eventos/{evento_id}", response_model=EventoOut)
def obtener_evento(evento_id: str):
    conn = get_connection()
    cur = conn.cursor()
    try:
        service = get_calendar_service()

        try:
            google_event = service.events().get(calendarId=CALENDAR_ID, eventId=evento_id).execute()
        except HttpError as e:
            if e.resp.status == 404:
                logger.warning(f"📭 Evento {evento_id} no encontrado en Google Calendar.")
                raise HTTPException(status_code=404, detail=f"Evento {evento_id} no existe en Google Calendar.")
            else:
                logger.error(f"❌ Error consultando evento {evento_id} en Google Calendar: {e}")
                raise HTTPException(status_code=500, detail="Error consultando evento en Google Calendar.")

        # 📅 Fechas
        fecha_inicio = isoparse(google_event["start"]["dateTime"])
        fecha_fin = isoparse(google_event["end"]["dateTime"])
        titulo = google_event.get("summary", "Sin título")
        descripcion = google_event.get("description", "")

        # 📹 Link Meet
        meet_link = None
        if 'conferenceData' in google_event:
            for ep in google_event['conferenceData'].get('entryPoints', []):
                if ep.get('entryPointType') == 'video':
                    meet_link = ep.get('uri')
                    break

        # 🔍 Buscar en base de datos
        cur.execute("""SELECT id FROM agendamientos WHERE google_event_id = %s""", (evento_id,))
        agendamiento = cur.fetchone()

        if agendamiento:
            agendamiento_id = agendamiento[0]
        else:
            cur.execute("""
                INSERT INTO agendamientos (
                    titulo, descripcion, fecha_inicio, fecha_fin, google_event_id, link_meet, estado
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                titulo, descripcion, fecha_inicio, fecha_fin, evento_id, meet_link, 'programado'
            ))
            agendamiento_id = cur.fetchone()[0]
            conn.commit()
            logger.info(f"🆕 Evento {evento_id} insertado con ID {agendamiento_id}")

        # 👥 Participantes
        cur.execute("""
            SELECT c.id, c.nombre_real AS nombre, c.nickname
            FROM agendamientos_participantes ap
            JOIN creadores c ON c.id = ap.creador_id
            WHERE ap.agendamiento_id = %s
        """, (agendamiento_id,))
        participantes = cur.fetchall()

        participantes_ids = [p[0] for p in participantes]  # p[0] = id
        participantes_out = [
            {"id": p[0], "nombre": p[1], "nickname": p[2]}
            for p in participantes
        ]

        return EventoOut(
            id=evento_id,
            titulo=titulo,
            descripcion=descripcion,
            inicio=fecha_inicio,
            fin=fecha_fin,
            participantes=participantes_out,
            participantes_ids=participantes_ids,
            link_meet=meet_link,
            origen="google_calendar"
        )

    except HTTPException:
        raise  # Ya lo lanzamos arriba
    except Exception as e:
        logger.error(f"❌ Error al obtener evento {evento_id}: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Error interno al consultar el evento.")
    finally:
        cur.close()
        conn.close()


@app.get("/api/eventos", response_model=List[EventoOut])
def listar_eventos():
    try:
        return obtener_eventos()
    except Exception as e:
        logger.error(f"❌ Error al obtener eventos: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sync")
def sincronizar():
    try:
        sync_eventos()
        return {"status": "ok", "mensaje": "Eventos sincronizados correctamente (logs disponibles)"}
    except Exception as e:
        logger.error(f"❌ Error al sincronizar eventos: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/eventos/{evento_id}", response_model=EventoOut)
def editar_evento(evento_id: str, evento: EventoIn):
    conn = get_connection()
    cur = conn.cursor()
    try:
        if evento.fin <= evento.inicio:
            raise HTTPException(status_code=400, detail="La fecha de fin debe ser posterior a la fecha de inicio.")

        # ✅ Obtener el servicio y el evento actual en Google Calendar
        service = get_calendar_service()
        google_event = service.events().get(calendarId=CALENDAR_ID, eventId=evento_id).execute()

        # ✅ Actualizar campos sin borrar lo existente
        google_event["summary"] = evento.titulo
        google_event["description"] = evento.descripcion or ""
        google_event["start"] = {
            "dateTime": evento.inicio.isoformat(),
            "timeZone": "America/Bogota"
        }
        google_event["end"] = {
            "dateTime": evento.fin.isoformat(),
            "timeZone": "America/Bogota"
        }

        # ⚠️ Solo regenerar Meet si es requerido explícitamente
        if getattr(evento, "regenerar_meet", False):
            google_event["conferenceData"] = {
                "createRequest": {
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                    "requestId": str(uuid4())
                }
            }

        try:
            updated = service.events().update(
                calendarId=CALENDAR_ID,
                eventId=evento_id,
                body=google_event,
                conferenceDataVersion=1 if "conferenceData" in google_event else 0
            ).execute()
        except HttpError as e:
            if e.resp.status == 400 and "Invalid conference type value" in str(e):
                logger.warning(f"⚠️ Evento {evento_id} sin link de Meet válido, reintentando sin conferenceData...")
                # Eliminar conferenceData y reintentar
                google_event.pop("conferenceData", None)
                updated = service.events().update(
                    calendarId=CALENDAR_ID,
                    eventId=evento_id,
                    body=google_event
                ).execute()
            else:
                raise

        # ✅ Obtener link de Meet (si existe)
        meet_link = None
        if 'conferenceData' in updated:
            for ep in updated['conferenceData'].get('entryPoints', []):
                if ep.get('entryPointType') == 'video':
                    meet_link = ep.get('uri')
                    break

        # ✅ Guardar o actualizar en base de datos
        cur.execute("SELECT id FROM agendamientos WHERE google_event_id = %s", (evento_id,))
        agendamiento = cur.fetchone()

        if agendamiento:
            agendamiento_id = agendamiento[0]
            cur.execute("""
                UPDATE agendamientos
                SET fecha_inicio = %s,
                    fecha_fin = %s,
                    titulo = %s,
                    descripcion = %s,
                    link_meet = %s,
                    actualizado_en = NOW()
                WHERE id = %s
            """, (
                evento.inicio,
                evento.fin,
                evento.titulo,
                evento.descripcion,
                meet_link,
                agendamiento_id
            ))
        else:
            cur.execute("""
                INSERT INTO agendamientos (
                    titulo, descripcion, fecha_inicio, fecha_fin,
                    google_event_id, link_meet, estado
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                evento.titulo,
                evento.descripcion,
                evento.inicio,
                evento.fin,
                evento_id,
                meet_link,
                'programado'
            ))
            agendamiento_id = cur.fetchone()[0]
            logger.info(f"🆕 Evento {evento_id} creado en agendamientos con ID {agendamiento_id}")

        # ✅ Actualizar participantes
        cur.execute("DELETE FROM agendamientos_participantes WHERE agendamiento_id = %s", (agendamiento_id,))
        for participante_id in evento.participantes_ids:
            cur.execute("""
                INSERT INTO agendamientos_participantes (agendamiento_id, creador_id)
                VALUES (%s, %s)
            """, (agendamiento_id, participante_id))

        conn.commit()

        # ✅ Consultar datos de participantes
        participantes = []
        if evento.participantes_ids:
            cur.execute("""
                SELECT id, nombre_real as nombre, nickname
                FROM creadores
                WHERE id = ANY(%s)
            """, (evento.participantes_ids,))
            participantes = [{"id": row[0], "nombre": row[1], "nickname": row[2]} for row in cur.fetchall()]

        return EventoOut(
            id=updated['id'],
            titulo=updated['summary'],
            inicio=isoparse(updated['start']['dateTime']),
            fin=isoparse(updated['end']['dateTime']),
            descripcion=updated.get('description'),
            participantes_ids=evento.participantes_ids,
            participantes=participantes,
            link_meet=meet_link,
            origen="google_calendar"
        )

    except Exception as e:
        logger.error(f"❌ Error al editar evento {evento_id}: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()


@app.delete("/api/eventos/{evento_id}")
def eliminar_evento(evento_id: str):
    try:
        service = get_calendar_service()
        service.events().delete(calendarId=CALENDAR_ID, eventId=evento_id).execute()
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM agendamientos WHERE google_event_id = %s", (evento_id,))
        conn.commit()
        cur.close()
        conn.close()

        return {"ok": True, "mensaje": f"Evento {evento_id} eliminado"}
    except Exception as e:
        logger.error(f"❌ Error al eliminar evento {evento_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

from fastapi import Depends,status
from auth import *
from schemas import EventoOut, EventoIn
import traceback, logging
from uuid import uuid4
from dateutil.parser import isoparse

logger = logging.getLogger(__name__)

@app.post("/api/eventos", response_model=EventoOut)
def crear_evento(evento: EventoIn, usuario_actual: dict = Depends(obtener_usuario_actual)):
    conn = get_connection()
    cur = conn.cursor()
    try:
        if evento.fin <= evento.inicio:
            raise HTTPException(status_code=400, detail="La fecha de fin debe ser posterior a la fecha de inicio.")

        # 1. Crear el evento en Google Calendar
        google_event = crear_evento_google(
            resumen=evento.titulo,
            descripcion=evento.descripcion or "",
            fecha_inicio=evento.inicio,
            fecha_fin=evento.fin
        )

        link_meet = google_event.get("hangoutLink")
        google_event_id = google_event.get("id")

        # 2. Insertar agendamiento principal
        cur.execute("""
            INSERT INTO agendamientos (
                titulo, descripcion, fecha_inicio, fecha_fin,
                link_meet, estado, responsable_id, google_event_id
            )
            VALUES (%s, %s, %s, %s, %s, 'programado', %s, %s)
            RETURNING id;
        """, (
            evento.titulo,
            evento.descripcion,
            evento.inicio,
            evento.fin,
            link_meet,
            usuario_actual["id"],
            google_event_id
        ))
        agendamiento_id = cur.fetchone()[0]

        # 3. Insertar participantes
        for participante_id in evento.participantes_ids:
            cur.execute("""
                INSERT INTO agendamientos_participantes (agendamiento_id, creador_id)
                VALUES (%s, %s)
            """, (agendamiento_id, participante_id))

        # 4. Consultar nombres/nicknames
        cur.execute("""
            SELECT id, nombre_real as nombre, nickname
            FROM creadores
            WHERE id = ANY(%s)
        """, (evento.participantes_ids,))
        participantes = [
            {"id": row[0], "nombre": row[1], "nickname": row[2]}
            for row in cur.fetchall()
        ]

        conn.commit()

        return EventoOut(
            id=google_event_id,
            titulo=evento.titulo,
            descripcion=evento.descripcion,
            inicio=evento.inicio,
            fin=evento.fin,
            participantes_ids=evento.participantes_ids,
            participantes=participantes,
            link_meet=link_meet,
            origen="google_calendar"
        )

    except Exception as e:
        conn.rollback()
        print("❌ Error creando evento:", e)
        raise HTTPException(status_code=500, detail="Error creando evento")
    finally:
        cur.close()
        conn.close()

def crear_evento_google(resumen, descripcion, fecha_inicio, fecha_fin):
    service = get_calendar_service()

    # 1️⃣ Construir evento con Meet incluido
    evento = {
        'summary': resumen,
        'description': descripcion,
        'start': {
            'dateTime': fecha_inicio.isoformat(),
            'timeZone': 'America/Bogota',
        },
        'end': {
            'dateTime': fecha_fin.isoformat(),
            'timeZone': 'America/Bogota',
        },
        'conferenceData': {
            'createRequest': {
                'requestId': str(uuid4()),
                'conferenceSolutionKey': {'type': 'hangoutsMeet'},
            }
        }
    }

    # 2️⃣ Crear evento en Google Calendar con Meet
    evento_creado = service.events().insert(
        calendarId=CALENDAR_ID,
        body=evento,
        conferenceDataVersion=1
    ).execute()

    logger.info(f"✅ Evento creado: {evento_creado.get('htmlLink')}")
    logger.info(f"🔗 Meet: {evento_creado.get('hangoutLink')}")

    return evento_creado

# def crear_evento_google(resumen, descripcion, fecha_inicio, fecha_fin):
#     service = get_calendar_service()
#
#     # 1️⃣ Comprobar si el calendario permite crear Meet
#     try:
#         calendar_info = service.calendarList().get(calendarId=CALENDAR_ID).execute()
#         is_workspace = "primary" in calendar_info.get("id", "") or \
#                        "conferenceProperties" in calendar_info
#         allows_meet = False
#
#         if "conferenceProperties" in calendar_info:
#             allowed_types = calendar_info["conferenceProperties"].get("allowedConferenceSolutionTypes", [])
#             allows_meet = "hangoutsMeet" in allowed_types
#
#         logger.info(f"📝 Calendario detectado: {calendar_info.get('summary')}")
#         logger.info(f"Workspace: {is_workspace}, Permite Meet: {allows_meet}")
#
#     except Exception as e:
#         logger.warning(f"⚠️ No se pudo verificar si el calendario permite Meet: {e}")
#         allows_meet = False
#
#     # 2️⃣ Construir evento
#     evento = {
#         'summary': resumen,
#         'description': descripcion,
#         'start': {
#             'dateTime': fecha_inicio.isoformat(),
#             'timeZone': 'America/Bogota',
#         },
#         'end': {
#             'dateTime': fecha_fin.isoformat(),
#             'timeZone': 'America/Bogota',
#         }
#     }
#
#     # Solo añadir conferencia si está permitido
#     if allows_meet:
#         evento['conferenceData'] = {
#             'createRequest': {
#                 'requestId': str(uuid4()),
#                 'conferenceSolutionKey': {'type': 'hangoutsMeet'},
#             }
#         }
#
#     # 3️⃣ Crear evento en Google Calendar
#     evento_creado = service.events().insert(
#         calendarId=CALENDAR_ID,
#         body=evento,
#         conferenceDataVersion=1 if allows_meet else 0
#     ).execute()
#
#     return evento_creado


def crear_evento_google_(resumen, descripcion, fecha_inicio, fecha_fin):
    service = get_calendar_service()

    evento = {
        'summary': resumen,
        'description': descripcion,
        'start': {
            'dateTime': fecha_inicio.isoformat(),
            'timeZone': 'America/Bogota',
        },
        'end': {
            'dateTime': fecha_fin.isoformat(),
            'timeZone': 'America/Bogota',
        },
        'conferenceData': {
            'createRequest': {
                'requestId': str(uuid4()),
                'conferenceSolutionKey': {'type': 'hangoutsMeet'},
            },
        },
    }

    evento_creado = service.events().insert(
        calendarId=CALENDAR_ID,
        body=evento,
        conferenceDataVersion=1
    ).execute()

    return evento_creado

from psycopg2.extras import RealDictCursor

@app.get("/api/agendamientos")
def listar_agendamientos():
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Obtener agendamientos con nombre del responsable
        cur.execute("""
            SELECT 
                a.id, a.titulo, a.descripcion, a.fecha_inicio, a.fecha_fin,
                a.estado, a.link_meet,
                u.nombre_completo AS responsable
            FROM agendamientos a
            LEFT JOIN admin_usuario u ON u.id = a.responsable_id
            ORDER BY a.fecha_inicio DESC;
        """)
        agendamientos = cur.fetchall()

        # Para cada agendamiento, obtener los participantes (nombre, nickname)
        for evento in agendamientos:
            cur.execute("""
                SELECT c.id, c.nombre_real as nombre, c.nickname
                FROM agendamientos_participantes ap
                JOIN creadores c ON c.id = ap.creador_id
                WHERE ap.agendamiento_id = %s
            """, (evento["id"],))
            participantes = cur.fetchall()
            evento["participantes"] = participantes

            # Opcional: convertir fechas a string ISO si FastAPI no lo hace automáticamente
            evento["fecha_inicio"] = evento["fecha_inicio"].isoformat() if isinstance(evento["fecha_inicio"], datetime) else evento["fecha_inicio"]
            evento["fecha_fin"] = evento["fecha_fin"].isoformat() if isinstance(evento["fecha_fin"], datetime) else evento["fecha_fin"]

        cur.close()
        conn.close()
        return agendamientos

    except Exception as e:
        logger.error(f"❌ Error consultando agendamientos: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Error consultando agendamientos")


@app.get("/debug/version")
def get_version():
    import google.auth
    from google.oauth2.credentials import Credentials as UserCredentials
    return {
        "google-auth-version": google.auth.__version__,
        "user_credentials_methods": dir(UserCredentials)
    }
# ==================== FIN PROYECTO CALENDAR =======================

# 🔊 Función para descargar audio desde WhatsApp Cloud API

from googleapiclient.http import MediaFileUpload

# Configuración Google Drive

# SERVICE_ACCOUNT_INFO = os.getenv("GOOGLE_CREDENTIALS_JSON")
# SERVICE_ACCOUNT_INFO_DRIVE = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))
# SCOPES_DRIVE = ["https://www.googleapis.com/auth/drive.file"]
# FOLDER_ID = "1I40G_-UIBL_rGUd5BnxIP76I18B-zxhi"  # carpeta donde guardar audios,  El ID es la parte después de /folders/ y antes del ?:
#
# creds_drive = service_account.Credentials.from_service_account_info(
#     SERVICE_ACCOUNT_INFO_DRIVE,
#     scopes=SCOPES_DRIVE
# )
#
# # 🚀 Crear cliente Google Drive
# drive_service = build("drive", "v3", credentials=creds_drive)

# def subir_a_drive(ruta_archivo):
#     try:
#         nombre_archivo = os.path.basename(ruta_archivo)
#         file_metadata = {
#             "name": nombre_archivo,
#             "parents": [FOLDER_ID]
#         }
#         media = MediaFileUpload(ruta_archivo, mimetype="audio/ogg")
#         file = drive_service.files().create(
#             body=file_metadata,
#             media_body=media,
#             fields="id, webViewLink"
#         ).execute()
#
#         # 🌍 Hacer el archivo público
#         drive_service.permissions().create(
#             fileId=file.get("id"),
#             body={"type": "anyone", "role": "reader"}
#         ).execute()
#
#         url_publica = file.get("webViewLink")
#         print(f"📤 Audio subido a Drive: {url_publica}")
#         return url_publica
#
#     except Exception as e:
#         print("❌ Error subiendo a Drive:", e)
#         return None



# # 🔊 Descargar audio desde WhatsApp Cloud API y subirlo a Drive
# def descargar_audio(audio_id, token, carpeta_destino=AUDIO_DIR):
#     try:
#         # 📥 Obtener URL de descarga
#         url_info = f"https://graph.facebook.com/v19.0/{audio_id}"
#         headers = {"Authorization": f"Bearer {token}"}
#         response_info = requests.get(url_info, headers=headers)
#         response_info.raise_for_status()
#
#         media_url = response_info.json().get("url")
#         if not media_url:
#             print("❌ No se pudo obtener la URL del audio.")
#             return None
#
#         # 📥 Descargar archivo
#         response_audio = requests.get(media_url, headers=headers)
#         response_audio.raise_for_status()
#
#         os.makedirs(carpeta_destino, exist_ok=True)
#         nombre_archivo = f"{audio_id}.ogg"
#         ruta_archivo = os.path.join(carpeta_destino, nombre_archivo)
#
#         with open(ruta_archivo, "wb") as f:
#             f.write(response_audio.content)
#
#         print(f"✅ Audio guardado en local: {ruta_archivo}")
#
#         # ☁ Subir a Google Drive
#         url_drive = subir_a_drive(ruta_archivo)
#         return url_drive or ruta_archivo
#
#     except Exception as e:
#         print("❌ Error al descargar audio:", e)
#         return None


# cloudinary
# cloudinary
import cloudinary
import cloudinary.uploader

# Configuración (puedes usar variables de entorno)
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True
)

def subir_audio_cloudinary(ruta_local, public_id=None, carpeta="audios_whatsapp"):
    try:
        response = cloudinary.uploader.upload(
            ruta_local,
            resource_type="video",  # Cloudinary usa 'video' para audio/ogg/webm
            folder=carpeta,
            public_id=public_id,
            overwrite=True
        )
        url = response.get("secure_url")
        print(f"✅ Audio subido a Cloudinary: {url}")
        return url
    except Exception as e:
        print("❌ Error subiendo audio a Cloudinary:", e)
        return None
# cloudinary
# cloudinary

import requests
import os

def descargar_audio(audio_id, token, carpeta_destino=AUDIO_DIR):
    try:
        url_info = f"https://graph.facebook.com/v19.0/{audio_id}"
        headers = {"Authorization": f"Bearer {token}"}
        response_info = requests.get(url_info, headers=headers)
        response_info.raise_for_status()

        media_url = response_info.json().get("url")
        if not media_url:
            print("❌ No se pudo obtener la URL del audio.")
            return None

        response_audio = requests.get(media_url, headers=headers)
        response_audio.raise_for_status()

        os.makedirs(carpeta_destino, exist_ok=True)
        nombre_archivo = f"{audio_id}.ogg"
        ruta_archivo = os.path.join(carpeta_destino, nombre_archivo)

        with open(ruta_archivo, "wb") as f:
            f.write(response_audio.content)

        print(f"✅ Audio guardado en: {ruta_archivo}")

        # Sube a Cloudinary y elimina el archivo local si quieres
        url_cloudinary = subir_audio_cloudinary(ruta_archivo, public_id=audio_id)
        if url_cloudinary:
            # os.remove(ruta_archivo)  # Descomenta si quieres borrar el archivo local
            return url_cloudinary
        else:
            return None

    except Exception as e:
        print("❌ Error al descargar audio:", e)
        return None

# def descargar_audio(audio_id, token, carpeta_destino=AUDIO_DIR):
#     try:
#         url_info = f"https://graph.facebook.com/v19.0/{audio_id}"
#         headers = {"Authorization": f"Bearer {token}"}
#         response_info = requests.get(url_info, headers=headers)
#         response_info.raise_for_status()
#
#         media_url = response_info.json().get("url")
#         if not media_url:
#             print("❌ No se pudo obtener la URL del audio.")
#             return None
#
#         response_audio = requests.get(media_url, headers=headers)
#         response_audio.raise_for_status()
#
#         os.makedirs(carpeta_destino, exist_ok=True)
#         nombre_archivo = f"{audio_id}.ogg"
#         ruta_archivo = os.path.join(carpeta_destino, nombre_archivo)
#
#         with open(ruta_archivo, "wb") as f:
#             f.write(response_audio.content)
#
#         print(f"✅ Audio guardado en: {ruta_archivo}")
#         return ruta_archivo
#
#     except Exception as e:
#         print("❌ Error al descargar audio:", e)
#         return None

@app.patch("/contacto_info/{telefono}")
def actualizar_contacto_info(telefono: str = Path(...), datos: ActualizacionContactoInfo = Body(...)):
    return actualizar_contacto_info_db(telefono, datos)

@app.get("/contactos")
def listar_contactos(estado: Optional[str] = None):
    return obtener_contactos_db(estado)

@app.post("/cargar_contactos")
def cargar_contactos_desde_excel(nombre_hoja: str = Body(..., embed=True)):
    try:
        contactos = obtener_contactos_desde_hoja(nombre_hoja)
        if not contactos:
            return {"status": "error", "mensaje": "No se encontraron contactos en la hoja"}
        guardar_contactos(contactos)
        return {"status": "ok", "mensaje": f"{len(contactos)} contactos cargados y guardados correctamente"}
    except Exception as e:
        return {"status": "error", "mensaje": f"Error al cargar contactos: {str(e)}"}

# ✅ VERIFICACIÓN DEL WEBHOOK (Facebook Developers)
@app.get("/webhook")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    print("📡 Verificación recibida:", params)
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(challenge or "")
    return PlainTextResponse("Verificación fallida", status_code=403)

@app.post("/webhook_V0")
async def recibir_mensaje(request: Request):
    try:
        datos = await request.json()
        print("📨 Payload recibido:")
        print(json.dumps(datos, indent=2))
        entrada = datos.get("entry", [{}])[0]
        cambio = entrada.get("changes", [{}])[0]
        valor = cambio.get("value", {})
        mensajes = valor.get("messages")
        if not mensajes:
            print("⚠️ No se encontraron mensajes en el payload.")
            return JSONResponse({"status": "ok", "detalle": "Sin mensajes"}, status_code=200)
        mensaje = mensajes[0]
        telefono = mensaje.get("from")
        tipo = mensaje.get("type")
        es_audio = False
        audio_id = None
        mensaje_usuario = None

        if tipo == "text":
            mensaje_usuario = mensaje.get("text", {}).get("body")
        elif tipo == "audio":
            es_audio = True
            audio_info = mensaje.get("audio", {})
            audio_id = audio_info.get("id")
        elif tipo == "button":
            mensaje_usuario = mensaje.get("button", {}).get("text")
            print(f"👆 Botón presionado: {mensaje_usuario}")

        if not telefono or (not mensaje_usuario and not es_audio):
            print("⚠️ Mensaje incompleto.")
            return JSONResponse({"status": "ok", "detalle": "Mensaje incompleto"}, status_code=200)
        print(f"📥 Mensaje recibido de {telefono}: {mensaje_usuario if mensaje_usuario else audio_id}")

        if es_audio:
            url_cloudinary = descargar_audio(audio_id, TOKEN)
            if url_cloudinary:
                guardar_mensaje(telefono, url_cloudinary, tipo="recibido", es_audio=True)
                return JSONResponse({"status": "ok", "detalle": "Audio subido a Cloudinary", "url": url_cloudinary})
            else:
                return JSONResponse({"status": "error", "detalle": "No se pudo subir el audio"}, status_code=500)
        else:
            guardar_mensaje(telefono, mensaje_usuario, tipo="recibido", es_audio=False)

        # ✉️ Enviar respuesta automática
        # respuesta = "Gracias por tu mensaje, te escribiremos una respuesta tan pronto podamos"
        # codigo, respuesta_api = enviar_mensaje_texto_simple(
        #     token=TOKEN,
        #     numero_id=PHONE_NUMBER_ID,
        #     telefono_destino=telefono,
        #     texto=respuesta,
        # )
        # guardar_mensaje(telefono, respuesta, tipo="enviado")
        # print(f"✅ Código de envío: {codigo}")
        # print("🛰️ Respuesta API:", respuesta_api)
        # return JSONResponse({
        #     "status": "ok",
        #     "respuesta": respuesta,
        #     "codigo_envio": codigo,
        #     "respuesta_api": respuesta_api,
        # })
    except Exception as e:
        print("❌ Error procesando mensaje:", e)
        return JSONResponse({"error": str(e)}, status_code=500)

# 📩 PROCESAMIENTO DE MENSAJES ENVIADOS AL WEBHOOK
# @app.post("/webhook")
# async def recibir_mensaje(request: Request):
#     try:
#         datos = await request.json()
#         print("📨 Payload recibido:")
#         print(json.dumps(datos, indent=2))
#         entrada = datos.get("entry", [{}])[0]
#         cambio = entrada.get("changes", [{}])[0]
#         valor = cambio.get("value", {})
#         mensajes = valor.get("messages")
#         if not mensajes:
#             print("⚠️ No se encontraron mensajes en el payload.")
#             return JSONResponse({"status": "ok", "detalle": "Sin mensajes"}, status_code=200)
#         mensaje = mensajes[0]
#         telefono = mensaje.get("from")
#         tipo = mensaje.get("type")
#         mensaje_usuario = None
#         es_audio = False
#         audio_id = None
#         if tipo == "text":
#             mensaje_usuario = mensaje.get("text", {}).get("body")
#         elif tipo == "audio":
#             es_audio = True
#             audio_info = mensaje.get("audio", {})
#             audio_id = audio_info.get("id")
#             mensaje_usuario = f"[Audio recibido: {audio_id}]"
#         elif tipo == "button":
#             mensaje_usuario = mensaje.get("button", {}).get("text")
#             print(f"👆 Botón presionado: {mensaje_usuario}")
#         if not telefono or not mensaje_usuario:
#             print("⚠️ Mensaje incompleto.")
#             return JSONResponse({"status": "ok", "detalle": "Mensaje incompleto"}, status_code=200)
#         print(f"📥 Mensaje recibido de {telefono}: {mensaje_usuario}")
#         guardar_mensaje(telefono, mensaje_usuario, tipo="recibido", es_audio=es_audio)
#         if es_audio:
#             ruta = descargar_audio(audio_id, TOKEN)
#             return JSONResponse({"status": "ok", "detalle": f"Audio guardado en {ruta}"})
#         # ✉️ Enviar respuesta automática
#         respuesta = "Gracias por tu mensaje, te escribiremos una respuesta tan pronto podamos"
#         codigo, respuesta_api = enviar_mensaje_texto_simple(
#             token=TOKEN,
#             numero_id=PHONE_NUMBER_ID,
#             telefono_destino=telefono,
#             texto=respuesta,
#         )
#         guardar_mensaje(telefono, respuesta, tipo="enviado")
#         print(f"✅ Código de envío: {codigo}")
#         print("🛰️ Respuesta API:", respuesta_api)
#         return JSONResponse({
#             "status": "ok",
#             "respuesta": respuesta,
#             "codigo_envio": codigo,
#             "respuesta_api": respuesta_api,
#         })
#     except Exception as e:
#         print("❌ Error procesando mensaje:", e)
#         return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/mensajes/{telefono}")
def listar_mensajes(telefono: str):
    return obtener_mensajes(telefono)

@app.post("/mensajes")
async def api_enviar_mensaje(data: dict):
    telefono = data.get("telefono")
    mensaje = data.get("mensaje")
    nombre = data.get("nombre", "").strip()
    if not telefono or not mensaje:
        return JSONResponse({"error": "Faltan datos"}, status_code=400)
    usuario_id = obtener_usuario_id_por_telefono(telefono)
    if usuario_id and paso_limite_24h(usuario_id):
        print("⏱️ Usuario fuera de la ventana de 24h. Enviando plantilla reengagement.")
        plantilla = "reconectar_usuario_saludo"
        parametros = [nombre] if nombre else []
        codigo, respuesta_api = enviar_plantilla_generica(
            token=TOKEN,
            phone_number_id=PHONE_NUMBER_ID,
            numero_destino=telefono,
            nombre_plantilla=plantilla,
            codigo_idioma="es_CO",
            parametros=parametros
        )
        guardar_mensaje(
            telefono,
            f"[Plantilla enviada por 24h: {plantilla} - {parametros}]",
            tipo="enviado"
        )
        return {
            "status": "plantilla_auto",
            "mensaje": "Se envió plantilla por estar fuera de ventana de 24h.",
            "codigo_api": codigo,
            "respuesta_api": respuesta_api
        }
    codigo, respuesta_api = enviar_mensaje_texto_simple(
        token=TOKEN,
        numero_id=PHONE_NUMBER_ID,
        telefono_destino=telefono,
        texto=mensaje
    )
    guardar_mensaje(telefono, mensaje, tipo="enviado")
    return {
        "status": "ok",
        "mensaje": "Mensaje enviado correctamente",
        "codigo_api": codigo,
        "respuesta_api": respuesta_api
    }


@app.post("/mensajes/audio")
async def api_enviar_audio(telefono: str = Form(...), audio: UploadFile = Form(...)):
    filename_webm = f"{telefono}_{int(datetime.now().timestamp())}.webm"
    ruta_webm = os.path.join(AUDIO_DIR, filename_webm)
    filename_ogg = filename_webm.replace(".webm", ".ogg")
    ruta_ogg = os.path.join(AUDIO_DIR, filename_ogg)
    os.makedirs(AUDIO_DIR, exist_ok=True)
    audio_bytes = await audio.read()
    with open(ruta_webm, "wb") as f:
        f.write(audio_bytes)
    print(f"✅ Audio guardado correctamente en: {ruta_webm}")
    try:
        subprocess.run(["ffmpeg", "-y", "-i", ruta_webm, "-acodec", "libopus", ruta_ogg], check=True)
        print(f"✅ Audio convertido a .ogg: {ruta_ogg}")
    except subprocess.CalledProcessError as e:
        return {"status": "error", "mensaje": "Error al convertir el audio a .ogg", "error": str(e)}
    # Subir a Cloudinary
    url_cloudinary = subir_audio_cloudinary(ruta_ogg, public_id=filename_ogg.replace(".ogg", ""))
    guardar_mensaje(
        telefono,
        url_cloudinary,
        tipo="enviado",
        es_audio=True
    )
    try:
        codigo, respuesta_api = enviar_audio_base64(
            token=TOKEN,
            numero_id=PHONE_NUMBER_ID,
            telefono_destino=telefono,
            ruta_audio=ruta_ogg,
            mimetype="audio/ogg; codecs=opus"
        )
        print(f"📤 Audio enviado a WhatsApp. Código: {codigo}")
    except Exception as e:
        return {
            "status": "error",
            "mensaje": "Audio guardado, pero no enviado por WhatsApp",
            "archivo": filename_ogg,
            "url_cloudinary": url_cloudinary,
            "error": str(e)
        }
    return {
        "status": "ok",
        "mensaje": "Audio recibido, subido y enviado por WhatsApp",
        "archivo": filename_ogg,
        "url_cloudinary": url_cloudinary,
        "codigo_api": codigo,
        "respuesta_api": respuesta_api
    }


# con Drive
# @app.post("/mensajes/audio")
# async def api_enviar_audio(telefono: str = Form(...), audio: UploadFile = Form(...)):
#     # Guardar temporalmente en local
#     filename_webm = f"{telefono}_{int(datetime.now().timestamp())}.webm"
#     ruta_webm = os.path.join(AUDIO_DIR, filename_webm)
#     filename_ogg = filename_webm.replace(".webm", ".ogg")
#     ruta_ogg = os.path.join(AUDIO_DIR, filename_ogg)
#     os.makedirs(AUDIO_DIR, exist_ok=True)
#
#     audio_bytes = await audio.read()
#     with open(ruta_webm, "wb") as f:
#         f.write(audio_bytes)
#     print(f"✅ Audio guardado: {ruta_webm}")
#
#     # Convertir a OGG
#     try:
#         subprocess.run(["ffmpeg", "-y", "-i", ruta_webm, "-acodec", "libopus", ruta_ogg], check=True)
#         print(f"✅ Convertido a: {ruta_ogg}")
#     except subprocess.CalledProcessError as e:
#         return {"status": "error", "mensaje": "Error al convertir audio", "error": str(e)}
#
#     # Subir a Google Drive
#     link_drive = subir_a_drive(ruta_ogg)
#     if not link_drive:
#         return {"status": "error", "mensaje": "Error al subir a Google Drive"}
#
#     # Guardar en base de datos
#     guardar_mensaje(
#         telefono,
#         f"[Audio en Drive: {link_drive}]",
#         tipo="enviado",
#         es_audio=True
#     )
#
#     # Enviar por WhatsApp
#     try:
#         codigo, respuesta_api = enviar_audio_base64(
#             token=TOKEN,
#             numero_id=PHONE_NUMBER_ID,
#             telefono_destino=telefono,
#             ruta_audio=ruta_ogg,
#             mimetype="audio/ogg; codecs=opus"
#         )
#         print(f"📤 Audio enviado a WhatsApp. Código: {codigo}")
#     except Exception as e:
#         return {
#             "status": "error",
#             "mensaje": "Audio guardado en Drive, pero no enviado por WhatsApp",
#             "link_drive": link_drive,
#             "error": str(e)
#         }
#
#     return {
#         "status": "ok",
#         "mensaje": "Audio recibido, subido a Drive y enviado por WhatsApp",
#         "archivo": filename_ogg,
#         "link_drive": link_drive,
#         "codigo_api": codigo,
#         "respuesta_api": respuesta_api
#     }

# @app.post("/mensajes/audio")
# async def api_enviar_audio(telefono: str = Form(...), audio: UploadFile = Form(...)):
#     filename_webm = f"{telefono}_{int(datetime.now().timestamp())}.webm"
#     ruta_webm = os.path.join(AUDIO_DIR, filename_webm)
#     filename_ogg = filename_webm.replace(".webm", ".ogg")
#     ruta_ogg = os.path.join(AUDIO_DIR, filename_ogg)
#     os.makedirs(AUDIO_DIR, exist_ok=True)
#     audio_bytes = await audio.read()
#     with open(ruta_webm, "wb") as f:
#         f.write(audio_bytes)
#     print(f"✅ Audio guardado correctamente en: {ruta_webm}")
#     try:
#         subprocess.run(["ffmpeg", "-y", "-i", ruta_webm, "-acodec", "libopus", ruta_ogg], check=True)
#         print(f"✅ Audio convertido a .ogg: {ruta_ogg}")
#     except subprocess.CalledProcessError as e:
#         return {"status": "error", "mensaje": "Error al convertir el audio a .ogg", "error": str(e)}
#     guardar_mensaje(
#         telefono,
#         f"[Audio guardado: {filename_ogg}]",
#         tipo="enviado",
#         es_audio=True
#     )
#     try:
#         codigo, respuesta_api = enviar_audio_base64(
#             token=TOKEN,
#             numero_id=PHONE_NUMBER_ID,
#             telefono_destino=telefono,
#             ruta_audio=ruta_ogg,
#             mimetype="audio/ogg; codecs=opus"
#         )
#         print(f"📤 Audio enviado a WhatsApp. Código: {codigo}")
#     except Exception as e:
#         return {
#             "status": "error",
#             "mensaje": "Audio guardado, pero no enviado por WhatsApp",
#             "archivo": filename_ogg,
#             "error": str(e)
#         }
#     return {
#         "status": "ok",
#         "mensaje": "Audio recibido y enviado por WhatsApp",
#         "archivo": filename_ogg,
#         "codigo_api": codigo,
#         "respuesta_api": respuesta_api
#     }

@app.post("/contactos/nombre")
async def actualizar_nombre(data: dict):
    telefono = data.get("telefono")
    nombre = data.get("nombre")
    if not telefono or not nombre:
        return JSONResponse({"error": "Faltan parámetros"}, status_code=400)
    actualizado = actualizar_nombre_contacto(telefono, nombre)
    if actualizado:
        return {"status": "ok", "mensaje": "Nombre actualizado"}
    else:
        return JSONResponse({"error": "No se pudo actualizar"}, status_code=500)

@app.delete("/mensajes/{telefono}")
async def borrar_mensajes(telefono: str):
    eliminado = eliminar_mensajes(telefono)
    if eliminado:
        return {"status": "ok", "mensaje": f"Mensajes de {telefono} eliminados"}
    else:
        return JSONResponse({"error": "No se pudieron eliminar los mensajes"}, status_code=500)


# ===============================
# ENDPOINTS PARA ADMIN_USUARIO
# ===============================

@app.get("/api/admin-usuario/test", response_model=dict)
async def test_conexion():
    """Prueba la conexión a la base de datos y la tabla admin_usuario"""
    try:
        import psycopg2
        from dotenv import load_dotenv
        load_dotenv()

        db_url = os.getenv("EXTERNAL_DATABASE_URL")
        print(f"🔗 Probando conexión a: {db_url}")

        conn = psycopg2.connect(db_url)
        cur = conn.cursor()

        # Verificar si la tabla existe
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'admin_usuario'
            )
        """)
        table_exists = cur.fetchone()[0]

        if table_exists:
            # Contar registros
            cur.execute("SELECT COUNT(*) FROM admin_usuario")
            count = cur.fetchone()[0]

            cur.close()
            conn.close()

            return {
                "status": "ok",
                "message": "Conexión exitosa",
                "table_exists": True,
                "record_count": count
            }
        else:
            cur.close()
            conn.close()

            return {
                "status": "warning",
                "message": "Conexión exitosa pero tabla no existe",
                "table_exists": False,
                "record_count": 0
            }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Error de conexión: {str(e)}",
            "table_exists": False,
            "record_count": 0
        }

@app.get("/api/admin-usuario", response_model=List[AdminUsuarioResponse])
async def obtener_usuarios():
    """Obtiene todos los usuarios administradores"""
    usuarios = obtener_todos_admin_usuarios()
    return usuarios

@app.post("/api/admin-usuario", response_model=AdminUsuarioResponse)
async def crear_usuario(usuario: AdminUsuarioCreate):
    """Crea un nuevo usuario administrador"""
    usuario_creado = crear_admin_usuario(usuario)
    return usuario_creado

@app.get("/api/admin-usuario/{usuario_id}", response_model=AdminUsuarioResponse)
async def obtener_usuario(usuario_id: int):
    """Obtiene un usuario administrador por ID"""
    usuario = obtener_admin_usuario_por_id(usuario_id)

    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return usuario


@app.delete("/api/admin-usuario/{usuario_id}")
async def eliminar_usuario(usuario_id: int):
    """Elimina un usuario administrador"""
    eliminar_admin_usuario(usuario_id)
    return {"mensaje": "Usuario eliminado exitosamente"}

@app.patch("/api/admin-usuario/{usuario_id}/activo")
async def cambiar_estado_usuario(usuario_id: int, activo: bool = Body(...)):
    """Cambia el estado activo/inactivo de un usuario administrador"""
    cambiar_estado_admin_usuario(usuario_id, activo)
    return {"mensaje": f"Estado actualizado a {'activo' if activo else 'inactivo'}"}

@app.get("/api/admin-usuario/username/{username}", response_model=AdminUsuarioResponse)
async def obtener_usuario_por_username(username: str):
    """Obtiene un usuario administrador por username (útil para autenticación)"""
    usuario = obtener_admin_usuario_por_username(username)

    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return usuario

# Endpoint de login usando tus funciones y devolviendo el JWT
@app.post("/api/admin-usuario/login")
async def login_usuario(credentials: dict = Body(...)):
    username = credentials.get("username", "").strip().lower()
    password = credentials.get("password", "")
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username y password son requeridos")

    resultado = autenticar_admin_usuario(username, password)
    if resultado["status"] != "ok":
        raise HTTPException(status_code=401, detail=resultado["mensaje"])

    usuario = resultado["usuario"]
    token = crear_token_jwt(usuario)
    return {
        "usuario": usuario,
        "access_token": token,
        "token_type": "bearer",
        "mensaje": "Login exitoso"
    }

@app.put("/api/admin-usuario/cambiar-password")
async def cambiar_password_admin(
    datos: ChangePasswordRequest = Body(...),
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    """
    Permite a cualquier usuario cambiar su propia contraseña, o a un administrador cambiar la de cualquier usuario.
    """
    # Asegura que los IDs se comparen como enteros
    if not es_admin(usuario_actual) and datos.user_id != int(usuario_actual["sub"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes cambiar la contraseña de otro usuario.")

    usuario = obtener_admin_usuario_por_id(datos.user_id)
    if not usuario:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    nuevo_hash = hash_password(datos.new_password)
    actualiza_password_usuario(datos.user_id, nuevo_hash)

    return {"mensaje": "Contraseña actualizada correctamente."}


@app.put("/api/admin-usuario/{usuario_id:int}", response_model=AdminUsuarioResponse)
async def actualizar_usuario(usuario_id: int, usuario: AdminUsuarioUpdate):
    try:
        usuario_actualizado = actualizar_admin_usuario(usuario_id, usuario.dict())
        if not usuario_actualizado:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        return usuario_actualizado
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error interno del servidor")

# Ejemplo de endpoint protegido
@app.get("/api/perfil")
async def perfil(usuario: dict = Depends(obtener_usuario_actual)):
    return {"usuario": usuario}

# @app.post("/api/admin-usuario/login")
# async def login_usuario(credentials: dict = Body(...)):
#     """Autentica un usuario administrador"""
#     username = credentials.get("username")
#     password = credentials.get("password")
#
#     if not username or not password:
#         raise HTTPException(status_code=400, detail="Username y password son requeridos")
#
#     # Verificar credenciales
#     usuario = obtener_admin_usuario_por_username(username)
#     if not usuario or not verify_password(password, usuario["password_hash"]):
#         raise HTTPException(status_code=401, detail="Credenciales inválidas")
#
#     # Retornar datos del usuario sin el password_hash
#     usuario_response = {k: v for k, v in usuario.items() if k != "password_hash"}
#     return {"usuario": usuario_response, "mensaje": "Login exitoso"}

#-------------------------
#-------------------------

# === Listar todos los creadores ===
@app.get("/api/creadores", tags=["Creadores"])
def listar_creadores():
    try:
        return obtener_creadores_db()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# === Listar todos los usuarios ===
@app.get("/api/TodosUsuarios", tags=["TodosUsuarios"])
def listar_TodosUsuarios():
    try:
        return obtener_todos_usuarios_db()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# === Obtener el perfil de un creador por ID ===
@app.get("/api/perfil_creador/{creador_id}", tags=["Perfil"])
def perfil_creador(creador_id: int):
    perfil = obtener_perfil_creador(creador_id)
    if not perfil:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    return perfil


# === Actualizar evaluación inicial (solo algunos campos) ===
@app.put("/api/perfil_creador/{creador_id}/evaluacion", tags=["Evaluación"])
def evaluar_creador(creador_id: int, evaluacion: EvaluacionInicialSchema):
    try:
        actualizar_datos_perfil_creador(creador_id, evaluacion.dict(exclude_unset=True))
        return {"status": "ok", "mensaje": "Evaluación actualizada"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Actualizar el perfil completo del creador ===
@app.put("/api/perfil_creador/{creador_id}", tags=["Perfil"])
def actualizar_perfil_creador_endpoint(creador_id: int, evaluacion: PerfilCreadorSchema):
    try:
        data_dict = evaluacion.dict(exclude_unset=True)
        if not data_dict:
            raise HTTPException(status_code=400, detail="No se enviaron datos para actualizar.")

        actualizar_datos_perfil_creador(creador_id, data_dict)
        return {"status": "ok", "mensaje": "Perfil actualizado correctamente"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from evaluaciones import *

# === Estadísticas globales de evaluación ===
@app.get("/api/estadisticas-evaluacion", tags=["Estadísticas"])
def estadisticas_evaluacion():
    try:
        return obtener_estadisticas_evaluacion()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# === Actualizar datos personales del perfil ===
@app.put("/api/perfil_creador/{creador_id}/datos_personales",
         tags=["Perfil"],
         response_model=DatosPersonalesOutput)
def actualizar_datos_personales(creador_id: int, datos: DatosPersonalesInput):
    try:
        data_dict = datos.dict(exclude_unset=True)

        # ✅ Calcular score con evaluar_datos_generales
        score = evaluar_datos_generales(
            edad=data_dict.get("edad"),
            genero=data_dict.get("genero"),
            idiomas=data_dict.get("idioma"),
            estudios=data_dict.get("estudios"),
            pais=data_dict.get("pais"),
            actividad_actual=data_dict.get("actividad_actual")
        )

        # Guardar puntaje general y categoría
        data_dict["puntaje_general"] = score.get("puntaje_general")
        data_dict["puntaje_general_categoria"] = score.get("puntaje_general_categoria")

        # Actualizar en BD
        actualizar_datos_perfil_creador(creador_id, data_dict)

        return DatosPersonalesOutput(
            status="ok",
            mensaje="Evaluación datos Generales actualizada",
            puntaje_general=score.get("puntaje_general"),
            puntaje_general_categoria=score.get("puntaje_general_categoria"),
        )

    except Exception as e:
        logging.error(f"Error en PUT /api/perfil_creador/{creador_id}/datos_personales: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Error al actualizar datos personales"
        )

from auth import obtener_usuario_actual  # o el nombre correcto del archivo

@app.put(
    "/api/perfil_creador/{creador_id}/evaluacion_cualitativa",
    response_model=EvaluacionCualitativaOutput,
    tags=["Evaluación"]
)
def actualizar_eval_cualitativa(
    creador_id: int,
    datos: EvaluacionCualitativaInput,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    try:
        # Convertir datos a dict y asignar usuario que evalúa
        data_dict = datos.dict(exclude_unset=True)
        data_dict["usuario_evalua"] = usuario_actual["nombre"]

        # Calcular puntaje cualitativo
        resultado = evaluar_cualitativa(
            apariencia=data_dict.get("apariencia", 0),
            engagement=data_dict.get("engagement", 0),
            calidad_contenido=data_dict.get("calidad_contenido", 0),
            foto=data_dict.get("eval_foto", 0),
            biografia=data_dict.get("eval_biografia", 0),
            metadata_videos=data_dict.get("metadata_videos", 0)
        )

        data_dict["puntaje_manual"] = resultado["puntaje_manual"]
        data_dict["puntaje_manual_categoria"] = resultado["puntaje_manual_categoria"]

        potencial_creador=evaluar_potencial_creador(creador_id, resultado["puntaje_manual"])
        nivel_estimado = potencial_creador.get("nivel")

        actualizar_datos_perfil_creador(creador_id, data_dict)

        # === respuesta final ===
        return EvaluacionCualitativaOutput(
            status="ok",
            mensaje="Evaluación cualitativa actualizada",
            puntaje_manual=resultado["puntaje_manual"],
            puntaje_manual_categoria=resultado["puntaje_manual_categoria"],
            potencial_estimado=nivel_estimado
        )

    except Exception as e:
        logging.error(f"Error en PUT /api/perfil_creador/{creador_id}/evaluacion_cualitativa: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Ocurrió un error interno en el servidor al procesar la evaluación. Por favor inténtalo nuevamente o contacta al administrador."
        )


# === Actualizar estadísticas del perfil ===
@app.put(
    "/api/perfil_creador/{creador_id}/estadisticas",
    tags=["Estadísticas"],
    response_model=EstadisticasPerfilOutput
)
def actualizar_estadisticas(creador_id: int, datos: EstadisticasPerfilInput):
    try:
        data_dict = datos.dict(exclude_unset=True)

        # ✅ Calcular score de estadísticas
        score = evaluar_estadisticas(
            seguidores=data_dict.get("seguidores"),
            siguiendo=data_dict.get("siguiendo"),
            videos=data_dict.get("videos"),
            likes=data_dict.get("likes"),
            duracion=data_dict.get("duracion_emisiones")
        )

        # Guardar score en el mismo registro
        data_dict["puntaje_estadistica"] = score["puntaje_estadistica"]
        data_dict["puntaje_estadistica_categoria"] = score["puntaje_estadistica_categoria"]

        # Actualizar en BD
        actualizar_datos_perfil_creador(creador_id, data_dict)

        return EstadisticasPerfilOutput(
            status="ok",
            mensaje="Estadisticas actualizadas",
            puntaje_estadistica=score["puntaje_estadistica"],
            puntaje_estadistica_categoria=score["puntaje_estadistica_categoria"]
        )

    except Exception as e:
        logging.error(f"Error en PUT /api/perfil_creador/{creador_id}/estadisticas: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error al actualizar estadísticas")


# === Actualizar preferencias y hábitos ===
@app.put(
    "/api/perfil_creador/{creador_id}/preferencias",
    tags=["Preferencias"],
    response_model=PreferenciasHabitosOutput
)
def actualizar_preferencias(creador_id: int, datos: PreferenciasHabitosInput):
    try:
        data_dict = datos.dict(exclude_unset=True)

        # Calcular score de preferencias y hábitos
        score = evaluar_preferencias_habitos(
            exp_otras=data_dict.get("experiencia_otras_plataformas") or {},
            intereses=data_dict.get("intereses") or {},
            tipo_contenido=data_dict.get("tipo_contenido") or {},
            tiempo=data_dict.get("tiempo_disponible"),
            freq_lives=data_dict.get("frecuencia_lives"),
            intencion=data_dict.get("intencion_trabajo")
        )

        # Guardar score en el registro
        data_dict["puntaje_habitos"] = score["puntaje_habitos"]
        data_dict["puntaje_habitos_categoria"] = score["puntaje_habitos_categoria"]

        # Actualizar en BD
        actualizar_datos_perfil_creador(creador_id, data_dict)

        return PreferenciasHabitosOutput(
            status="ok",
            mensaje="Preferencias actualizadas",
            puntaje_habitos=score["puntaje_habitos"],
            puntaje_habitos_categoria=score["puntaje_habitos_categoria"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error al actualizar preferencias y hábitos del perfil.")


@app.put("/api/perfil_creador/{creador_id}/resumen",
         tags=["Resumen"],
         response_model=ResumenEvaluacionOutput)
def actualizar_resumen(creador_id: int, datos: ResumenEvaluacionInput):
    try:
        # Depuración: ver datos recibidos
        print("Datos recibidos del frontend:", datos)
        data_dict = datos.dict(exclude_unset=True)
        print("Datos recibidos como dict:", data_dict)

        perfil = obtener_puntajes_perfil_creador(creador_id)
        print("Puntajes del perfil recuperados:", perfil)
        if not perfil:
            raise HTTPException(status_code=404, detail=f"No se encontró el perfil del creador con id {creador_id}.")

        # Calcular puntaje general y categoría
        score = evaluacion_total(
            cualitativa_score=perfil.get("puntaje_manual",0),
            estadistica_score=perfil.get("puntaje_estadistica",0),
            general_score=perfil.get("puntaje_general",0),
            habitos_score=perfil.get("puntaje_habitos",0)
        )
        print("Resultado de evaluacion_total:", score)

        # Generar diagnóstico y mejoras sugeridas, manejando errores
        try:
            diagnostico = diagnostico_perfil_creador(creador_id)
        except Exception as e:
            print(f"Error generando diagnóstico: {e}")
            diagnostico = "-"

        try:
            mejoras = generar_mejoras_sugeridas_total(creador_id)
        except Exception as e:
            print(f"Error generando mejoras: {e}")
            mejoras = "-"

        # Combinar observaciones de manera robusta
        observaciones_totales = (
            f"📊 Evaluación Global:\n"
            f"Puntaje total: {score['puntaje_total']}\n"
            f"Categoría: {score['puntaje_total_categoria']}\n\n"
            f"🩺 Diagnóstico Detallado:\n{diagnostico}\n"
        )

        data_dict["estado"] = "Evaluado"
        data_dict["observaciones"] = observaciones_totales
        data_dict["mejoras_sugeridas"] = mejoras
        data_dict["puntaje_total"] = score["puntaje_total"]
        data_dict["puntaje_total_categoria"] = score["puntaje_total_categoria"]


        actualizar_datos_perfil_creador(creador_id, data_dict)

        return ResumenEvaluacionOutput(
            status="ok",
            mensaje="Evaluación datos Resumen actualizada",
            puntaje_manual = perfil.get("puntaje_manual", 0),
            puntaje_manual_categoria = perfil.get("puntaje_manual_categoria"),
            puntaje_estadistica = perfil.get("puntaje_estadistica", 0),
            puntaje_estadistica_categoria= perfil.get("puntaje_estadistica_categoria"),
            puntaje_general = perfil.get("puntaje_general", 0),
            puntaje_general_categoria = perfil.get("puntaje_general_categoria"),
            puntaje_habitos = perfil.get("puntaje_habitos", 0),
            puntaje_habitos_categoria = perfil.get("puntaje_habitos_categoria"),
            puntaje_total=score["puntaje_total"],
            puntaje_total_categoria=score["puntaje_total_categoria"],
            observaciones = observaciones_totales,
            mejoras_sugeridas = mejoras,
        )

    except Exception as e:
        print("Error al guardar el perfil:", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/perfil_creador/{creador_id}/biografia_ia",
         tags=["Biografía IA"])
def actualizar_biografia_ia(creador_id: int):
    try:
        # 1. Validar que existe el perfil
        bio_texto = obtener_biografia_perfil_creador(creador_id)
        if not bio_texto:
            raise HTTPException(status_code=404, detail="No existe biografía previa para este perfil.")
        # 2. Generar la biografía con IA
        try:
            biografia_sugerida = evaluar_y_mejorar_biografia(bio_texto)

        except Exception as e:
            print(f"Error generando biografía IA: {e}")
            raise HTTPException(status_code=500, detail="Error generando la biografía con IA.")

        # 3. (Opcional) Recortar si tu campo biografía tiene un máximo de caracteres
        MAX_BIO_LEN = 500
        biografia_sugerida = biografia_sugerida[:MAX_BIO_LEN]
        biografia_sugerida =limpiar_biografia_ia(biografia_sugerida)

        # 4. Guardar en base de datos
        try:
            actualizar_datos_perfil_creador(creador_id, {"biografia_sugerida": biografia_sugerida})
        except Exception as e:
            print(f"Error guardando biografía en base: {e}")
            raise HTTPException(status_code=500, detail="Error guardando la biografía en la base de datos.")

        # 5. Responder
        return {
            "status": "ok",
            "mensaje": "Biografía IA generada y guardada exitosamente",
            "biografia": biografia_sugerida
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        print("Error general en biografía IA:", e)
        raise HTTPException(status_code=500, detail=str(e))


# filtrar responsables Agendas
@app.get("/api/responsable-Agenda", response_model=List[AdminUsuarioResponse])
async def obtener_responsables_agenda():
    """Obtiene todos los usuarios administradores"""
    usuarios = obtener_todos_responsables_agendas()
    return usuarios

# if __name__ == "__main__":
#     resultado = diagnostico_perfil_creador(27)  # id de prueba
#     print(resultado)


# CREADORES ACTIVOS

# 1. Listar todos los creadores activos
@app.get("/api/creadores_activos", response_model=List[CreadorActivoDB])
def listar_creadores_activos():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM creadores_activos")
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
        result = [dict(zip(columns, row)) for row in rows]
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()

# 2. Obtener un creador activo por ID
@app.get("/api/creadores_activos/{id}", response_model=CreadorActivoConManager)
def obtener_creador_activo(id: int):
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT ca.*, au.nombre_completo AS manager_nombre
            FROM creadores_activos ca
            LEFT JOIN admin_usuario au ON ca.manager_id = au.id
            WHERE ca.id = %s
        """, (id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Creador no encontrado")
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()

# 3. Agregar un nuevo creador activo
@app.post("/api/creadores_activos", response_model=CreadorActivoDB, status_code=201)
def agregar_creador_activo(creador: CreadorActivoCreate):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO creadores_activos (
                creador_id, nombre, usuario_tiktok, foto, categoria, estado, manager_id,
                horario_lives, tiempo_disponible, fecha_incorporacion, fecha_graduacion,
                seguidores, videos, me_gusta, diamantes, horas_live, numero_partidas, dias_emision
            ) VALUES (
                %(creador_id)s, %(nombre)s, %(usuario_tiktok)s, %(foto)s, %(categoria)s, %(estado)s, %(manager_id)s,
                %(horario_lives)s, %(tiempo_disponible)s, %(fecha_incorporacion)s, %(fecha_graduacion)s,
                %(seguidores)s, %(videos)s, %(me_gusta)s, %(diamantes)s, %(horas_live)s, %(numero_partidas)s, %(dias_emision)s
            ) RETURNING *;
        """, creador.dict())
        row = cur.fetchone()
        conn.commit()
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row))
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()

# 4. Editar un creador activo existente
@app.put("/api/creadores_activos/{id}", response_model=CreadorActivoDB)
def editar_creador_activo(id: int, creador: CreadorActivoUpdate):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE creadores_activos SET
                creador_id=%(creador_id)s,
                nombre=%(nombre)s,
                usuario_tiktok=%(usuario_tiktok)s,
                foto=%(foto)s,
                categoria=%(categoria)s,
                estado=%(estado)s,
                manager_id=%(manager_id)s,
                horario_lives=%(horario_lives)s,
                tiempo_disponible=%(tiempo_disponible)s,
                fecha_incorporacion=%(fecha_incorporacion)s,
                fecha_graduacion=%(fecha_graduacion)s,
                seguidores=%(seguidores)s,
                videos=%(videos)s,
                me_gusta=%(me_gusta)s,
                diamantes=%(diamantes)s,
                horas_live=%(horas_live)s,
                numero_partidas=%(numero_partidas)s,
                dias_emision=%(dias_emision)s
            WHERE id=%(id)s
            RETURNING *;
        """, {**creador.dict(), "id": id})
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Creador no encontrado")
        conn.commit()
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row))
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()


@app.get("/api/admin-usuario_manager", response_model=List[AdminUsuarioManagerResponse])
async def obtener_usuarios_manager():
    """Obtiene todos los usuarios manager"""
    usuarios = obtener_todos_manager()
    return usuarios

@app.post("/api/creadores_activos/auto", response_model=dict)
def crear_creador_activo_automatico(data: CreadorActivoAutoCreate):
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        # 1. Buscar datos del creador en la tabla creadores
        cur.execute("""
            SELECT
                id,
                usuario AS usuario_tiktok,
                foto_url AS foto,
                NULL AS categoria,
                'activo' AS estado,
                nickname AS nombre
            FROM creadores
            WHERE id = %s
        """, (data.creador_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Creador no encontrado")

        creador = dict(zip([desc[0] for desc in cur.description], row))

        # 2. Preparar valores para insertar en creadores_activos
        valores = {
            "creador_id": creador["id"],
            "usuario_tiktok": creador["usuario_tiktok"],
            "foto": creador["foto"],
            "categoria": creador["categoria"],
            "estado": creador["estado"],
            "nombre": creador["nombre"],
            "manager_id": data.manager_id,  # puede ser None
            "fecha_incorporacion": data.fecha_incorporacion or date.today(),
            "horario_lives": None,
            "tiempo_disponible": None,
            "fecha_graduacion": None,
            "seguidores": None,
            "videos": None,
            "me_gusta": None,
            "diamantes": None,
            "horas_live": None,
            "numero_partidas": None,
            "dias_emision": None
        }

        # 3. Insertar en creadores_activos
        cur.execute("""
            INSERT INTO creadores_activos (
                creador_id, usuario_tiktok, foto, categoria, estado, nombre,
                manager_id, horario_lives, tiempo_disponible, fecha_incorporacion, fecha_graduacion,
                seguidores, videos, me_gusta, diamantes, horas_live, numero_partidas, dias_emision
            ) VALUES (
                %(creador_id)s, %(usuario_tiktok)s, %(foto)s, %(categoria)s, %(estado)s, %(nombre)s,
                %(manager_id)s, %(horario_lives)s, %(tiempo_disponible)s, %(fecha_incorporacion)s, %(fecha_graduacion)s,
                %(seguidores)s, %(videos)s, %(me_gusta)s, %(diamantes)s, %(horas_live)s, %(numero_partidas)s, %(dias_emision)s
            )
            RETURNING *;
        """, valores)
        new_row = cur.fetchone()
        conn.commit()
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, new_row))
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error al crear creador activo: {e}")
    finally:
        if conn:
            conn.close()

# SEGUIMIENTO DE CREADORES
@app.post("/api/seguimiento_creadores/", response_model=SeguimientoCreadorDB)
def crear_seguimiento_creador(seg: SeguimientoCreadorCreate):
    try:
        conn = get_connection()
        cur = conn.cursor()

        # 1. Obtener manager_id de creadores_activos
        if not seg.creador_activo_id:
            raise HTTPException(status_code=400, detail="creador_activo_id es requerido")

        cur.execute("""
            SELECT manager_id FROM creadores_activos WHERE id = %s
        """, (seg.creador_activo_id,))
        result = cur.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="No se encontró el creador activo")
        manager_id = result[0]

        # 2. Insertar seguimiento usando manager_id obtenido
        cur.execute("""
            INSERT INTO seguimiento_creadores (
                creador_id, creador_activo_id, manager_id, fecha_seguimiento,
                estrategias_mejora, compromisos
            ) VALUES (
                %(creador_id)s, %(creador_activo_id)s, %(manager_id)s, %(fecha_seguimiento)s,
                %(estrategias_mejora)s, %(compromisos)s
            )
            RETURNING *;
        """, {
            **seg.dict(),
            "manager_id": manager_id
        })
        row = cur.fetchone()
        conn.commit()
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row))
    except Exception as e:
        print("ERROR:", e)  # o usa logging
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()




@app.get("/api/seguimiento_creadores/creador_activo/{creador_activo_id}", response_model=List[SeguimientoCreadorDB])
def listar_seguimientos_por_creador_activo(creador_activo_id: int):
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT sc.*, au.nombre_completo AS manager_nombre
            FROM seguimiento_creadores sc
            LEFT JOIN admin_usuario au ON sc.manager_id = au.id
            WHERE sc.creador_activo_id = %s
            ORDER BY sc.fecha_seguimiento DESC
        """, (creador_activo_id,))
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()

@app.post("/estadisticas_creadores/cargar_excel/")
async def cargar_estadisticas_excel(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents), header=1)

        required_columns = [
            "ID de creador", "Nombre de usuario del creador", "Grupo",
            "Diamantes de los últimos 30 días",
            "Duración de emisiones LIVE en los últimos 30 días",
            "Seguidores", "Vídeos", "Me gusta"
        ]
        for col in required_columns:
            if col not in df.columns:
                raise HTTPException(status_code=400, detail=f"Falta columna: {col}")

        conn = get_connection()
        cur = conn.cursor()
        creados = 0
        actualizados = 0

        for _, row in df.iterrows():
            usuario_tiktok = str(row["Nombre de usuario del creador"]).strip()
            grupo = str(row["Grupo"])
            seguidores = int(row["Seguidores"])
            videos = int(row["Vídeos"])
            me_gusta = int(row["Me gusta"])
            diamantes = int(row["Diamantes de los últimos 30 días"])
            duracion_lives = int(row["Duración de emisiones LIVE en los últimos 30 días"])

            # Buscar el registro en creadores_activos
            cur.execute("""
                SELECT id, creador_id FROM creadores_activos WHERE usuario_tiktok = %s
            """, (usuario_tiktok,))
            res = cur.fetchone()
            if not res:
                continue

            creador_activo_id, creador_id = res

            cur.execute("""
                INSERT INTO estadisticas_creadores (
                    creador_id, creador_activo_id, fecha_reporte, grupo, diamantes_ult_30, duracion_emsiones_live_ult_30
                ) VALUES (%s, %s, CURRENT_DATE, %s, %s, %s)
            """, (
                creador_id,
                creador_activo_id,
                grupo,
                diamantes,
                duracion_lives
            ))
            creados += 1

            cur.execute("""
                UPDATE creadores_activos
                SET seguidores = %s, me_gusta = %s, videos = %s
                WHERE id = %s
            """, (seguidores, me_gusta, videos, creador_activo_id))
            actualizados += 1

        conn.commit()
        return {
            "ok": True,
            "registros_creados": creados,
            "registros_actualizados": actualizados
        }
    except Exception as e:
        if 'conn' in locals() and conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error al procesar el archivo: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

