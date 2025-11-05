# ✅ main.py
from fastapi import FastAPI, HTTPException, Path, Body, Request,Response, UploadFile, Form,File
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

from main_mensajeria_whatsapp import router as perfil_creador_router
from mainCargarAspirantes import router as aspirantes_router
# from mainEntrevistas import router as entrevistas_router  # 👈 importa el router de entrevistas

# ⚙️ Inicializar FastAPI
app = FastAPI()


# Incluir las rutas del módulo perfil_creador_whatsapp
app.include_router(perfil_creador_router, tags=["Perfil Creador WhatsApp"])
app.include_router(aspirantes_router, tags=["Cargar Aspirantes"])
# app.include_router(entrevistas_router, tags=["Entrevistas"])  # 👈 lo agregas igual


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

import time
import traceback
from datetime import datetime, timedelta
from typing import List, Dict
from dateutil.parser import isoparse

def obtener_eventos(time_min: datetime = None, time_max: datetime = None, max_results: int = 100) -> List[EventoOut]:
    start_time = time.time()
    try:
        service = get_calendar_service()
    except Exception as e:
        logger.error(f"❌ Error al obtener el servicio de Calendar: {e}")
        raise

    # Rango por defecto: 30 días atrás y 30 adelante
    if time_min is None:
        time_min = datetime.utcnow() - timedelta(days=30)
    if time_max is None:
        time_max = datetime.utcnow() + timedelta(days=30)

    # ✅ Formato ISO correcto (sin microsegundos ni doble zona horaria)
    time_min_iso = time_min.replace(microsecond=0).isoformat() + "Z"
    time_max_iso = time_max.replace(microsecond=0).isoformat() + "Z"

    fields = "items(id,summary,description,start,end,conferenceData),nextPageToken"

    events = []
    page_token = None
    try:
        while True:
            resp = service.events().list(
                calendarId=CALENDAR_ID,
                timeMin=time_min_iso,
                timeMax=time_max_iso,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
                fields=fields,
                pageToken=page_token
            ).execute()
            items = resp.get("items", [])
            events.extend(items)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
    except Exception as e:
        logger.error(f"❌ Error al obtener eventos de Google Calendar API: {e}")
        logger.error(traceback.format_exc())
        raise

    logger.debug(f"[TIMING] Google events fetched: count={len(events)} time={(time.time()-start_time):.2f}s")

    if not events:
        logger.info("✅ No hay eventos en el rango solicitado")
        return []

    event_ids = [e.get("id") for e in events if e.get("id")]
    unique_event_ids = list(set(event_ids))
    participantes_por_evento: Dict[str, List[Dict]] = {}
    responsables_por_evento: Dict[str, int] = {}  # ✅ NUEVO diccionario para responsable_id

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        if unique_event_ids:
            placeholders = ",".join(["%s"] * len(unique_event_ids))
            sql = f"""
                SELECT 
                    a.google_event_id,
                    a.responsable_id,
                    c.id,
                    COALESCE(NULLIF(c.nombre_real, ''), c.nickname) AS nombre,
                    c.nickname
                FROM agendamientos_participantes ap
                JOIN creadores c ON c.id = ap.creador_id
                JOIN agendamientos a ON a.id = ap.agendamiento_id
                WHERE a.google_event_id IN ({placeholders})
            """
            cur.execute(sql, tuple(unique_event_ids))
            rows = cur.fetchall()

            # ✅ Ajuste: recorremos filas y guardamos tanto participantes como responsable
            for google_event_id, responsable_id, creador_id, nombre, nickname in rows:
                # Registrar participantes
                participantes_por_evento.setdefault(google_event_id, []).append({
                    "id": creador_id,
                    "nombre": nombre,
                    "nickname": nickname
                })
                # Registrar responsable (una sola vez por evento)
                if google_event_id not in responsables_por_evento:
                    responsables_por_evento[google_event_id] = responsable_id

        cur.close()
    except Exception as e:
        logger.error(f"❌ Error obteniendo participantes: {e}")
        logger.error(traceback.format_exc())
        participantes_por_evento = {}
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

    # ✅ Construcción final incluyendo responsable_id
    resultado: List[EventoOut] = []
    for event in events:
        try:
            event_id = event.get("id")
            start_dt = (event.get("start") or {}).get("dateTime")
            end_dt = (event.get("end") or {}).get("dateTime")
            if not start_dt or not end_dt:
                continue

            titulo = event.get("summary", "Sin título")
            descripcion = event.get("description", "")
            meet_link = None
            conf = event.get("conferenceData") or {}
            entry_points = conf.get("entryPoints", []) if conf else []
            for ep in entry_points:
                if ep.get("entryPointType") == "video":
                    meet_link = ep.get("uri")
                    break

            part_list = participantes_por_evento.get(event_id, [])
            participantes_ids = [p["id"] for p in part_list]
            responsable_id = responsables_por_evento.get(event_id)  # ✅ NUEVO

            resultado.append(EventoOut(
                id=event_id,
                titulo=titulo,
                inicio=isoparse(start_dt),
                fin=isoparse(end_dt),
                descripcion=descripcion,
                link_meet=meet_link,
                participantes_ids=participantes_ids,
                participantes=part_list,
                responsable_id=responsable_id,  # ✅ Incluido
                origen="google_calendar"
            ))
        except Exception as e:
            logger.warning(f"⚠️ Saltando evento con error: {event.get('id', 'unknown')} - {e}")

    logger.info(f"✅ Se obtuvieron {len(resultado)} eventos de Google Calendar en {(time.time()-start_time):.2f}s")
    return resultado


def obtener_eventosV0() -> List[EventoOut]:
    try:
        service = get_calendar_service()
    except Exception as e:
        logger.error(f"❌ Error al obtener el servicio de Calendar: {str(e)}")
        raise

    # time_min = (datetime.utcnow() - timedelta(days=31)).isoformat() + 'Z'
    time_min = datetime.utcnow().isoformat() + 'Z'
    time_max = (datetime.utcnow() + timedelta(days=31)).isoformat() + 'Z'

    try:
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=time_min,
            timeMax=time_max,
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
def listar_eventos(
    time_min: Optional[datetime] = None,
    time_max: Optional[datetime] = None,
    max_results: Optional[int] = 100
):
    try:
        return obtener_eventos(
            time_min=time_min,
            time_max=time_max,
            max_results=max_results)
    except Exception as e:
        logger.error(f"❌ Error al obtener eventos: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

# @app.get("/api/eventos", response_model=List[EventoOut])
# def listar_eventos():
#     try:
#         return obtener_eventos()
#     except Exception as e:
#         logger.error(f"❌ Error al obtener eventos: {str(e)}")
#         logger.error(traceback.format_exc())
#         raise HTTPException(status_code=500, detail=str(e))

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
            fecha_fin=evento.fin,
            requiere_meet=evento.requiere_meet  # ✅ nuevo parámetro
        )

        link_meet = google_event.get("hangoutLink") if evento.requiere_meet else None
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
        # raise HTTPException(status_code=500, detail="Error creando evento")
        raise HTTPException(status_code=500, detail=f"Error creando evento: {str(e)}")
    finally:
        cur.close()
        conn.close()

# from uuid import uuid4
# from datetime import datetime

def crear_evento_google(resumen, descripcion, fecha_inicio, fecha_fin, requiere_meet=False):
    service = get_calendar_service()

    # 🧱 Estructura base del evento
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
    }

    # ✅ Si requiere Meet, agregamos conferenceData
    if requiere_meet:
        evento['conferenceData'] = {
            'createRequest': {
                'requestId': str(uuid4()),
                'conferenceSolutionKey': {'type': 'hangoutsMeet'},
            }
        }

    # ⚙️ Insertar evento en Google Calendar
    evento_creado = service.events().insert(
        calendarId=CALENDAR_ID,
        body=evento,
        conferenceDataVersion=1 if requiere_meet else 0  # Solo activa el modo Meet si se requiere
    ).execute()

    logger.info(f"✅ Evento creado: {evento_creado.get('htmlLink')}")
    if requiere_meet:
        logger.info(f"🔗 Meet: {evento_creado.get('hangoutLink')}")

    return evento_creado


# def crear_evento_google(resumen, descripcion, fecha_inicio, fecha_fin):
#     service = get_calendar_service()
#
#     # 1️⃣ Construir evento con Meet incluido
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
#         },
#         'conferenceData': {
#             'createRequest': {
#                 'requestId': str(uuid4()),
#                 'conferenceSolutionKey': {'type': 'hangoutsMeet'},
#             }
#         }
#     }
#
#     # 2️⃣ Crear evento en Google Calendar con Meet
#     evento_creado = service.events().insert(
#         calendarId=CALENDAR_ID,
#         body=evento,
#         conferenceDataVersion=1
#     ).execute()
#
#     logger.info(f"✅ Evento creado: {evento_creado.get('htmlLink')}")
#     logger.info(f"🔗 Meet: {evento_creado.get('hangoutLink')}")
#
#     return evento_creado

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

# === LOGIN ===
@app.post("/login", response_model=TokenResponse)
async def login_usuario(credentials: dict = Body(...)):
    username = credentials.get("username", "").strip().lower()
    password = credentials.get("password", "")
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username y password son requeridos")

    # validar usuario
    resultado = autenticar_admin_usuario(username, password)
    if resultado["status"] != "ok":
        raise HTTPException(status_code=401, detail=resultado["mensaje"])

    usuario = resultado["usuario"]

    # generar tokens
    access_token = crear_access_token(usuario)
    refresh_token = crear_refresh_token(usuario)

    return TokenResponse(
        usuario=UsuarioOut(id=usuario["id"], nombre=usuario["nombre"], rol=usuario["rol"]),
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        mensaje="Login exitoso"
    )


# === REFRESH ===
@app.post("/refresh", response_model=TokenResponse)
async def refresh_token(data: dict = Body(...)):
    token = data.get("refresh_token")
    if not token:
        raise HTTPException(status_code=400, detail="refresh_token requerido")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("tipo") != "refresh":
            raise HTTPException(status_code=401, detail="Token inválido")

        user_id = payload.get("sub")

        # validar usuario en DB
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, nombre_completo AS nombre, rol, activo FROM admin_usuario WHERE id = %s",
                (user_id,),
            )
            row = cursor.fetchone()

        if not row or not row[3]:
            raise HTTPException(status_code=401, detail="Usuario no encontrado o inactivo")

        usuario = {"id": row[0], "nombre": row[1], "rol": row[2]}
        new_access_token = crear_access_token(usuario)

        return TokenResponse(
            access_token=new_access_token,
            refresh_token=token,  # opcional: devolver el mismo refresh token
            token_type="bearer",
            mensaje="Access token renovado",
            usuario=UsuarioOut(**usuario)
        )

    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="refresh_token expirado")
    except JWTError:
        raise HTTPException(status_code=401, detail="refresh_token inválido")


# === /me ===
@app.get("/me", response_model=UsuarioOut, tags=["Auth"])
async def get_me(usuario_actual: dict = Depends(obtener_usuario_actual)):
    if not usuario_actual:
        raise HTTPException(status_code=401, detail="Usuario no autenticado")

    return UsuarioOut(
        id=usuario_actual["id"],
        nombre=usuario_actual["nombre"],
        rol=usuario_actual["rol"],
    )


# # === LOGIN ===
# @app.post("/login", response_model=TokenResponse)
# async def login_usuario(credentials: dict = Body(...)):
#     username = credentials.get("username", "").strip().lower()
#     password = credentials.get("password", "")
#     if not username or not password:
#         raise HTTPException(status_code=400, detail="Username y password son requeridos")
#
#     # validar usuario
#     resultado = autenticar_admin_usuario(username, password)  # tu función existente
#     if resultado["status"] != "ok":
#         raise HTTPException(status_code=401, detail=resultado["mensaje"])
#
#     usuario = resultado["usuario"]
#
#     # generar tokens
#     access_token = crear_access_token(usuario)
#     refresh_token = crear_refresh_token(usuario)
#
#     return TokenResponse(
#         usuario=UsuarioOut(id=usuario["id"], nombre=usuario["nombre_completo"], rol=usuario["rol"]),
#         access_token=access_token,
#         refresh_token=refresh_token,
#         mensaje="Login exitoso"
#     )
#
#
# # === REFRESH ===
# @app.post("/refresh", response_model=TokenResponse)
# async def refresh_token(data: dict = Body(...)):
#     token = data.get("refresh_token")
#     if not token:
#         raise HTTPException(status_code=400, detail="refresh_token requerido")
#
#     try:
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         if payload.get("tipo") != "refresh":
#             raise HTTPException(status_code=401, detail="Token inválido")
#
#         user_id = payload.get("sub")
#
#         # validar usuario en DB
#         with get_connection() as conn:
#             cursor = conn.cursor()
#             cursor.execute(
#                 "SELECT id, nombre_completo, rol, activo FROM admin_usuario WHERE id = %s",
#                 (user_id,)
#             )
#             row = cursor.fetchone()
#
#         if not row or not row[3]:
#             raise HTTPException(status_code=401, detail="Usuario no encontrado o inactivo")
#
#         usuario = {"id": row[0], "nombre_completo": row[1], "rol": row[2]}
#         new_access_token = crear_access_token(usuario)
#
#         return TokenResponse(
#             usuario=UsuarioOut(id=usuario["id"], nombre=usuario["nombre_completo"], rol=usuario["rol"]),
#             access_token=new_access_token,
#             refresh_token=token,  # puedes devolver el mismo refresh o regenerar
#             mensaje="Token refrescado"
#         )
#
#
#     except ExpiredSignatureError:
#         raise HTTPException(status_code=401, detail="refresh_token expirado")
#     except JWTError:
#         raise HTTPException(status_code=401, detail="refresh_token inválido")

# @app.post("/api/admin-usuario/login")
# async def login_usuario(credentials: dict = Body(...)):
#     username = credentials.get("username", "").strip().lower()
#     password = credentials.get("password", "")
#     if not username or not password:
#         raise HTTPException(status_code=400, detail="Username y password son requeridos")
#
#     # validar usuario
#     resultado = autenticar_admin_usuario(username, password)  # tu función existente
#     if resultado["status"] != "ok":
#         raise HTTPException(status_code=401, detail=resultado["mensaje"])
#
#     usuario = resultado["usuario"]
#
#     # generar tokens
#     access_token = crear_access_token(usuario)
#     refresh_token = crear_refresh_token(usuario)
#
#     return {
#         "usuario": usuario,
#         "access_token": access_token,
#         "refresh_token": refresh_token,
#         "token_type": "bearer",
#         "mensaje": "Login exitoso"
#     }
#
# @app.post("/api/admin-usuario/refresh")
# async def refresh_token(data: dict = Body(...)):
#     token = data.get("refresh_token")
#     if not token:
#         raise HTTPException(status_code=400, detail="refresh_token requerido")
#
#     try:
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         if payload.get("tipo") != "refresh":
#             raise HTTPException(status_code=401, detail="Token inválido")
#
#         user_id = payload.get("sub")
#
#         # validar usuario en DB
#         conn = get_connection()
#         cursor = conn.cursor()
#         cursor.execute(
#             "SELECT id, nombre_completo, rol, activo FROM admin_usuario WHERE id = %s",
#             (user_id,)
#         )
#         row = cursor.fetchone()
#         cursor.close()
#         conn.close()
#
#         if not row or not row[3]:
#             raise HTTPException(status_code=401, detail="Usuario no encontrado o inactivo")
#
#         usuario = {"id": row[0], "nombre_completo": row[1], "rol": row[2]}
#         new_access_token = crear_access_token(usuario)
#
#         return {
#             "access_token": new_access_token,
#             "token_type": "bearer"
#         }
#
#     except JWTError:
#         raise HTTPException(status_code=401, detail="refresh_token inválido")



# @app.post("/api/admin-usuario/refresh")
# def refresh_token(usuario_actual: dict = Depends(obtener_usuario_actual)):
#     # Si el access_token aún no está expirado, se genera uno nuevo con el mismo usuario
#     new_token = crear_token_jwt(usuario_actual)
#     return {
#         "access_token": new_token,
#         "token_type": "bearer"
#     }

# @app.post("/api/admin-usuario/refresh")
# def refresh_token(usuario_actual: dict = Depends(obtener_usuario_actual)):
#     user_id = usuario_actual.get("id")
#     if not user_id:
#         raise HTTPException(status_code=401, detail="Token inválido")
#
#     conn = get_connection()
#     cursor = conn.cursor()
#     cursor.execute(
#         "SELECT id, nombre_completo, rol, activo FROM admin_usuario WHERE id = %s",
#         (user_id,)
#     )
#     row = cursor.fetchone()
#     cursor.close()
#     conn.close()
#
#     # Validar usuario activo
#     if not row or not row[3]:  # row[3] = activo
#         raise HTTPException(status_code=401, detail="Usuario no encontrado o inactivo")
#
#     usuario = {
#         "id": row[0],
#         "nombre_completo": row[1],
#         "rol": row[2]
#     }
#
#     new_token = crear_token_jwt(usuario)
#
#     return {
#         "access_token": new_token,
#         "token_type": "bearer"
#     }


# # Endpoint de login usando tus funciones y devolviendo el JWT
# @app.post("/api/admin-usuario/login")
# async def login_usuario(credentials: dict = Body(...)):
#     username = credentials.get("username", "").strip().lower()
#     password = credentials.get("password", "")
#     if not username or not password:
#         raise HTTPException(status_code=400, detail="Username y password son requeridos")
#
#     resultado = autenticar_admin_usuario(username, password)
#     if resultado["status"] != "ok":
#         raise HTTPException(status_code=401, detail=resultado["mensaje"])
#
#     usuario = resultado["usuario"]
#     token = crear_token_jwt(usuario)
#     return {
#         "usuario": usuario,
#         "access_token": token,
#         "token_type": "bearer",
#         "mensaje": "Login exitoso"
#     }

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

from typing import Optional
from fastapi import Query

# === Listar todos los creadores (con filtro opcional por estado_id) ===
@app.get("/api/creadores", tags=["Creadores"])
def listar_creadores(estado_id: Optional[int] = Query(None, description="Filtrar por estado_id")):
    try:
        return obtener_creadores_db(estado_id=estado_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# === Endpoint para estados 3, 4 y 5 ===
@app.get("/api/creadores/en_proceso", tags=["Creadores"])
def listar_creadores_en_proceso():
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
        print("❌ Error al actualizar preferencias:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/perfil_creador/{creador_id}/resumen",
         tags=["Resumen"],
         response_model=ResumenEvaluacionOutput)
def obtener_resumen(creador_id: int, usuario_actual: dict = Depends(obtener_usuario_actual)):
    perfil = obtener_puntajes_perfil_creador(creador_id)
    if not perfil:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")

    score = evaluacion_total(
        cualitativa_score=perfil.get("puntaje_manual", 0),
        estadistica_score=perfil.get("puntaje_estadistica", 0),
        general_score=perfil.get("puntaje_general", 0),
        habitos_score=perfil.get("puntaje_habitos", 0)
    )

    diagnostico = "-"
    mejoras = "-"
    try:
        diagnostico = diagnostico_perfil_creador(creador_id)
    except Exception:
        pass
    try:
        mejoras = generar_mejoras_sugeridas_total(creador_id)
    except Exception:
        pass

    # 📝 Observaciones globales (texto descriptivo que combina puntajes y diagnóstico)
    observaciones_totales = (
        f"📊 Evaluación Global:\n"
        f"Puntaje total: {score['puntaje_total']}\n"
        f"Categoría: {score['puntaje_total_categoria']}\n\n"
        f"🩺 Diagnóstico Detallado:\n{diagnostico}\n"
    )

    return ResumenEvaluacionOutput(
        status="ok",
        mensaje="Resumen calculado",
        puntaje_manual=perfil.get("puntaje_manual"),
        puntaje_manual_categoria=perfil.get("puntaje_manual_categoria"),
        puntaje_estadistica=perfil.get("puntaje_estadistica"),
        puntaje_estadistica_categoria=perfil.get("puntaje_estadistica_categoria"),
        puntaje_general=perfil.get("puntaje_general"),
        puntaje_general_categoria=perfil.get("puntaje_general_categoria"),
        puntaje_habitos=perfil.get("puntaje_habitos"),
        puntaje_habitos_categoria=perfil.get("puntaje_habitos_categoria"),
        puntaje_total=score["puntaje_total"],
        puntaje_total_categoria=score["puntaje_total_categoria"],
        diagnostico=observaciones_totales,  # 👈 Se devuelve el texto armado
        mejoras_sugeridas=mejoras
    )

ESTADO_MAP = {
    "Evaluación": 3,
    "Entrevista": 4,
    "Invitación": 5,
    "Rechazado": 7,
}
ESTADO_DEFAULT = 99  # si no coincide

@app.put("/api/perfil_creador/{creador_id}/resumen")
def guardar_resumen_final(creador_id: int, datos: GuardarResumenInput):
    try:
        # 1) Actualiza perfil_creador
        payload = {
            "diagnostico": datos.diagnostico,
            "mejoras_sugeridas": datos.mejoras_sugeridas,
            "observaciones_finales": datos.observaciones_finales,
            "usuario_evalua": datos.usuario_evalua,
            "estado_evaluacion": datos.estado_evaluacion,
        }
        actualizar_datos_perfil_creador(creador_id, payload)

        entrevista_creada = None

        # 2) Si viene un estado, actualiza también creadores.estado_id
        if datos.estado_evaluacion:
            estado_id = ESTADO_MAP.get(datos.estado_evaluacion, ESTADO_DEFAULT)
            actualizar_estado_creador(creador_id, estado_id)

            # 3) Si el estado es "Entrevista" (4), insertamos entrevista mínima
            if estado_id == 4:
                # Crear entrevista mínima
                entrevista_payload = {
                    "creador_id": creador_id,
                    # Campos mínimos
                }
                entrevista_creada = insertar_entrevista(entrevista_payload)

            elif estado_id == 5:
                # Crear invitación mínima
                invitacion_creada = crear_invitacion_minima(creador_id, estado="pendiente_tiktok")

                if invitacion_creada:
                    print(f"✅ Invitación creada correctamente para creador {creador_id}: {invitacion_creada}")
                else:
                    print(f"⚠️ No se pudo crear la invitación para el creador {creador_id}")

        return {
            "status": "ok",
            "mensaje": "Resumen actualizado correctamente",
            "entrevista_creada": entrevista_creada,  # {"id": ..., "creado_en": ...} o None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# @app.put("/api/perfil_creador/{creador_id}/resumen")
# def guardar_resumen_final(creador_id: int, datos: GuardarResumenInput):
#     try:
#         payload = {
#             "diagnostico": datos.diagnostico,
#             "mejoras_sugeridas": datos.mejoras_sugeridas,
#             "observaciones_finales": datos.observaciones_finales,
#             "usuario_evalua": datos.usuario_evalua,
#             "estado_evaluacion": datos.estado_evaluacion,
#         }
#
#         # 1️⃣ Actualiza perfil_creador
#         actualizar_datos_perfil_creador(creador_id, payload)
#
#         # 2️⃣ Si viene un estado, actualiza también creadores.estado_id
#         if datos.estado_evaluacion:
#             estado_id = ESTADO_MAP.get(datos.estado_evaluacion, ESTADO_DEFAULT)
#             actualizar_estado_creador(creador_id, estado_id)
#
#         return {"status": "ok", "mensaje": "Resumen actualizado correctamente"}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @app.put("/api/perfil_creador/{creador_id}/resumen",
#          tags=["Resumen"],
#          response_model=ResumenEvaluacionOutput)
# def actualizar_resumen(
#     creador_id: int,
#     datos: ResumenEvaluacionInput,
#     usuario_actual: dict = Depends(obtener_usuario_actual)
# ):
#     try:
#         # Usuario desde el token
#         usuario_id = usuario_actual.get("id")
#         if not usuario_id:
#             raise HTTPException(status_code=401, detail="Usuario no autorizado")
#
#         # Perfil actual
#         perfil = obtener_puntajes_perfil_creador(creador_id)
#         if not perfil:
#             raise HTTPException(
#                 status_code=404,
#                 detail=f"No se encontró el perfil del creador con id {creador_id}."
#             )
#
#         # Calcular puntaje total y categoría
#         score = evaluacion_total(
#             cualitativa_score=perfil.get("puntaje_manual", 0),
#             estadistica_score=perfil.get("puntaje_estadistica", 0),
#             general_score=perfil.get("puntaje_general", 0),
#             habitos_score=perfil.get("puntaje_habitos", 0)
#         )
#
#         # Diagnóstico y mejoras sugeridas
#         try:
#             diagnostico = diagnostico_perfil_creador(creador_id)
#         except Exception:
#             diagnostico = "-"
#
#         try:
#             mejoras = generar_mejoras_sugeridas_total(creador_id)
#         except Exception:
#             mejoras = "-"
#
#         # Observaciones
#         observaciones_totales = (
#             f"📊 Evaluación Global:\n"
#             f"Puntaje total: {score['puntaje_total']}\n"
#             f"Categoría: {score['puntaje_total_categoria']}\n\n"
#             f"🩺 Diagnóstico Detallado:\n{diagnostico}\n"
#         )
#
#         # 🔹 Solo guardar en BD: estado + puntaje_total + puntaje_total_categoria
#         estado_dict = {
#             "estado_evaluacion": datos.estado or "Evaluado",
#             "puntaje_total": datos.puntaje_total or score["puntaje_total"],
#             "puntaje_total_categoria": datos.puntaje_total_categoria or score["puntaje_total_categoria"],
#             "usuario_evaluador_resumen": usuario_id
#         }
#         result = actualizar_evaluacion_creador(creador_id, estado_dict)
#
#         # 🔹 Retornar toda la info calculada
#         return ResumenEvaluacionOutput(
#             status="ok",
#             mensaje="Resumen generado y estado actualizado",
#             puntaje_manual=perfil.get("puntaje_manual", 0),
#             puntaje_manual_categoria=perfil.get("puntaje_manual_categoria"),
#             puntaje_estadistica=perfil.get("puntaje_estadistica", 0),
#             puntaje_estadistica_categoria=perfil.get("puntaje_estadistica_categoria"),
#             puntaje_general=perfil.get("puntaje_general", 0),
#             puntaje_general_categoria=perfil.get("puntaje_general_categoria"),
#             puntaje_habitos=perfil.get("puntaje_habitos", 0),
#             puntaje_habitos_categoria=perfil.get("puntaje_habitos_categoria"),
#             puntaje_total=score["puntaje_total"],
#             puntaje_total_categoria=score["puntaje_total_categoria"],
#             diagnostico=observaciones_totales,
#             mejoras_sugeridas=mejoras
#         )
#
#     except HTTPException as he:
#         raise he
#     except Exception as e:
#         print(f"❌ Error en actualizar_resumen: {e}")
#         raise HTTPException(status_code=500, detail="Error interno al generar el resumen")


# @app.put("/api/perfil_creador/{creador_id}/resumen",
#          tags=["Resumen"],
#          response_model=ResumenEvaluacionOutput)
# def actualizar_resumen(creador_id: int, datos: ResumenEvaluacionInput):
#     try:
#         # Depuración: ver datos recibidos
#         print("Datos recibidos del frontend:", datos)
#         data_dict = datos.dict(exclude_unset=True)
#         print("Datos recibidos como dict:", data_dict)
#
#         perfil = obtener_puntajes_perfil_creador(creador_id)
#         print("Puntajes del perfil recuperados:", perfil)
#         if not perfil:
#             raise HTTPException(status_code=404, detail=f"No se encontró el perfil del creador con id {creador_id}.")
#
#         # Calcular puntaje general y categoría
#         score = evaluacion_total(
#             cualitativa_score=perfil.get("puntaje_manual",0),
#             estadistica_score=perfil.get("puntaje_estadistica",0),
#             general_score=perfil.get("puntaje_general",0),
#             habitos_score=perfil.get("puntaje_habitos",0)
#         )
#         print("Resultado de evaluacion_total:", score)
#
#         # Generar diagnóstico y mejoras sugeridas, manejando errores
#         try:
#             diagnostico = diagnostico_perfil_creador(creador_id)
#         except Exception as e:
#             print(f"Error generando diagnóstico: {e}")
#             diagnostico = "-"
#
#         try:
#             mejoras = generar_mejoras_sugeridas_total(creador_id)
#         except Exception as e:
#             print(f"Error generando mejoras: {e}")
#             mejoras = "-"
#
#         # Combinar observaciones de manera robusta
#         observaciones_totales = (
#             f"📊 Evaluación Global:\n"
#             f"Puntaje total: {score['puntaje_total']}\n"
#             f"Categoría: {score['puntaje_total_categoria']}\n\n"
#             f"🩺 Diagnóstico Detallado:\n{diagnostico}\n"
#         )
#
#         data_dict["estado"] = "Evaluado"
#         data_dict["observaciones"] = observaciones_totales
#         data_dict["mejoras_sugeridas"] = mejoras
#         data_dict["puntaje_total"] = score["puntaje_total"]
#         data_dict["puntaje_total_categoria"] = score["puntaje_total_categoria"]
#
#
#         actualizar_datos_perfil_creador(creador_id, data_dict)
#
#         return ResumenEvaluacionOutput(
#             status="ok",
#             mensaje="Evaluación datos Resumen actualizada",
#             puntaje_manual = perfil.get("puntaje_manual", 0),
#             puntaje_manual_categoria = perfil.get("puntaje_manual_categoria"),
#             puntaje_estadistica = perfil.get("puntaje_estadistica", 0),
#             puntaje_estadistica_categoria= perfil.get("puntaje_estadistica_categoria"),
#             puntaje_general = perfil.get("puntaje_general", 0),
#             puntaje_general_categoria = perfil.get("puntaje_general_categoria"),
#             puntaje_habitos = perfil.get("puntaje_habitos", 0),
#             puntaje_habitos_categoria = perfil.get("puntaje_habitos_categoria"),
#             puntaje_total=score["puntaje_total"],
#             puntaje_total_categoria=score["puntaje_total_categoria"],
#             observaciones = observaciones_totales,
#             mejoras_sugeridas = mejoras,
#             fecha_entrevista=data_dict.get("fecha_entrevista"),
#             entrevista=data_dict.get("entrevista")
#         )
#
#     except Exception as e:
#         print("Error al guardar el perfil:", e)
#         raise HTTPException(status_code=500, detail=str(e))

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

@app.get("/api/seguimiento_creadores/creador_activo/{creador_activo_id}", response_model=List[SeguimientoCreadorConManager])
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
        # Lee encabezados desde la segunda fila (índice 1)
        df = pd.read_excel(io.BytesIO(contents), header=1)

        # Limpia los encabezados: remueve espacios y dos puntos
        df.columns = [col.strip().replace(":", "") for col in df.columns]

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

@app.get("/estadisticas_creadores/{creador_activo_id}")
def obtener_estadisticas_por_creador(creador_activo_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM estadisticas_creadores WHERE creador_activo_id = %s",
        (creador_activo_id,)
    )
    rows = cur.fetchall()
    columns = [desc[0] for desc in cur.description]
    resultados = [dict(zip(columns, row)) for row in rows]
    cur.close()
    conn.close()
    return resultados

# 1. Subir foto y guardar URL en campo `foto`
@app.post("/creadores_activos/{creador_activo_id}/foto")
async def subir_foto_creador_activo(creador_activo_id: int, foto: UploadFile = File(...)):
    try:
        contents = await foto.read()
        result = cloudinary.uploader.upload(
            contents,
            folder=f"creadores_activos/{creador_activo_id}",
            public_id=f"foto_{creador_activo_id}",
            overwrite=True,
            resource_type="image"
        )
        url_foto = result["secure_url"]
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE creadores_activos SET foto = %s WHERE id = %s",
            (url_foto, creador_activo_id)
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"foto_url": url_foto}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al subir la foto: {e}")

# 2. Consultar la URL de la foto
@app.get("/creadores_activos/{creador_activo_id}/foto")
def obtener_foto_creador_activo(creador_activo_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT foto FROM creadores_activos WHERE id = %s", (creador_activo_id,)
    )
    res = cur.fetchone()
    cur.close()
    conn.close()
    if not res or not res[0]:
        raise HTTPException(status_code=404, detail="Foto no encontrada")
    return {"foto_url": res[0]}

# === Listar todos los aspirantes en proceso de entrevista/invitación ===
@app.get("/api/creadores/invitacion", tags=["Creadores"])
def listar_creadores_invitacion():
    try:
        return obtener_creadores_invitacion()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/perfil_creador/{creador_id}/evaluacion_inicial",
         tags=["Perfil"],
         response_model=EvaluacionOutput)
def actualizar_evaluacion_inicial(
    creador_id: int,
    datos: EvaluacionInput = Body(...),
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    try:
        # Usuario desde el token
        usuario_id = usuario_actual.get("id")
        if not usuario_id:
            raise HTTPException(status_code=401, detail="Usuario no autorizado")

        # Preparar datos a actualizar
        data_dict = datos.dict()
        data_dict["usuario_evaluador_inicial"] = usuario_id

        # Actualizar en DB
        result = actualizar_evaluacion_creador(creador_id, data_dict)

        return EvaluacionOutput(
            status="ok",
            mensaje="Evaluación inicial actualizada correctamente",
            **result
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        logging.error(f"❌ Error al actualizar evaluación inicial del creador {creador_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno al actualizar la evaluación")



# temporal

@app.post("/api/entrevistas/debug")
async def debug_entrevista(request: Request):
    """Endpoint temporal para debuggear headers y token"""
    # Headers completos
    headers = dict(request.headers)
    print("🔍 DEBUG: Headers recibidos:", headers)

    # Obtener token directamente
    token = headers.get("authorization")
    print("🔑 DEBUG: Authorization header:", token)

    # Body de la petición
    try:
        body = await request.json()
        print("📦 DEBUG: Body recibado:", body)
    except Exception as e:
        print("❌ DEBUG: Error al leer body:", str(e))
        body = None

    # Información adicional útil
    print("🌐 DEBUG: Method:", request.method)
    print("🛣️ DEBUG: URL:", str(request.url))
    print("🖥️ DEBUG: Client:", request.client)

    return {
        "message": "Debug recibido, revisa logs del backend",
        "headers_count": len(headers),
        "has_auth": "authorization" in headers,
        "token_preview": token[:20] + "..." if token else None
    }


# # POST crear
# @app.post("/api/entrevistas/{creador_id}", response_model=EntrevistaOut, tags=["Entrevistas"])
# def crear_entrevista(
#     creador_id: int,
#     datos: EntrevistaCreate,
#     usuario_actual: dict = Depends(obtener_usuario_actual)
# ):
#     usuario_id = usuario_actual.get("id")
#     if not usuario_id:
#         raise HTTPException(status_code=401, detail="Usuario no autorizado")
#
#     payload = datos.dict(exclude_unset=True)
#     payload["creador_id"] = creador_id
#     payload["usuario_programa"] = usuario_id
#     payload.setdefault("realizada", False)
#     payload.setdefault("resultado", "sin evaluar")
#
#     if not payload.get("realizada"):
#         payload["fecha_realizada"] = None
#         payload["usuario_evalua"] = None
#
#     resultado = insertar_entrevista(payload)
#     if not resultado:
#         raise HTTPException(status_code=500, detail="Error al crear la entrevista")
#
#     return EntrevistaOut.model_validate({**payload, **resultado})


from datetime import timedelta
from fastapi import Depends, HTTPException

# # Endpoint GET por creador
# @app.get("/api/entrevistas/{creador_id}", response_model=EntrevistaOut, tags=["Entrevistas"])
# def obtener_entrevista(creador_id: int):
#     entrevista = obtener_entrevista_por_creador(creador_id)
#     if not entrevista:
#         raise HTTPException(status_code=404, detail="No existe entrevista para este creador")
#     return entrevista
#
# # POST crear entrevista + evento
# @app.post("/api/entrevistas/{creador_id}", response_model=EntrevistaOut, tags=["Entrevistas"])
# def crear_entrevista(
#     creador_id: int,
#     datos: EntrevistaCreate,
#     usuario_actual: dict = Depends(obtener_usuario_actual)
# ):
#     usuario_id = usuario_actual.get("id")
#     if not usuario_id:
#         raise HTTPException(status_code=401, detail="Usuario no autorizado")
#
#     payload = datos.dict(exclude_unset=True)
#     payload["creador_id"] = creador_id
#     payload["usuario_programa"] = usuario_id
#     payload.setdefault("realizada", False)
#     payload.setdefault("resultado", "sin evaluar")
#
#     if not payload.get("realizada"):
#         payload["fecha_realizada"] = None
#         payload["usuario_evalua"] = None
#
#     # === Crear evento en calendario ===
#     try:
#         fecha_inicio = payload["fecha_programada"]
#         fecha_fin = fecha_inicio + timedelta(hours=1)  # duración por defecto = 1h
#
#         evento_payload = EventoIn(
#             titulo="Entrevista",
#             descripcion=payload.get("observaciones") or "Entrevista programada",
#             inicio=fecha_inicio,
#             fin=fecha_fin,
#             participantes_ids=[creador_id],
#         )
#         evento_creado = crear_evento(evento_payload, usuario_actual)
#         payload["evento_id"] = evento_creado.id  # <-- guardar evento_id
#     except Exception as e:
#         print(f"⚠️ Error al crear evento: {e}")
#         payload["evento_id"] = None
#
#     # === Insertar entrevista en DB ===
#     resultado = insertar_entrevista(payload)
#     if not resultado:
#         raise HTTPException(status_code=500, detail="Error al crear la entrevista")
#
#     return EntrevistaOut.model_validate({**payload, **resultado})
#
#
# from datetime import timedelta
# from fastapi import Path, Depends, HTTPException
#
# @app.put("/api/entrevistas/reprogramar/{creador_id}", response_model=EntrevistaOut, tags=["Entrevistas"])
# def reprogramar_entrevista(
#     creador_id: int = Path(..., description="ID del creador cuya entrevista se reprograma"),
#     datos: EntrevistaUpdate = None,
#     usuario_actual: dict = Depends(obtener_usuario_actual)
# ):
#     usuario_id = usuario_actual.get("id")
#     if not usuario_id:
#         raise HTTPException(status_code=401, detail="Usuario no autorizado")
#
#     # Obtener entrevista actual
#     entrevista = obtener_entrevista_por_creador(creador_id)
#     if not entrevista:
#         raise HTTPException(status_code=404, detail="Entrevista no encontrada")
#
#     # Actualizar datos en DB
#     payload = datos.dict(exclude_unset=True)
#     entrevista_actualizada = actualizar_entrevista_por_creador(creador_id, payload)
#     if not entrevista_actualizada:
#         raise HTTPException(status_code=500, detail="Error al actualizar la entrevista")
#
#     # Actualizar evento en calendario si existe evento_id
#     if payload.get("fecha_programada") and entrevista.get("evento_id"):
#         try:
#             fecha_inicio = payload["fecha_programada"]
#             fecha_fin = fecha_inicio + timedelta(hours=1)  # duración fija 1h
#
#             evento_payload = EventoIn(
#                 titulo="Entrevista",
#                 descripcion=payload.get("observaciones") or entrevista.get("observaciones") or "Entrevista programada",
#                 inicio=fecha_inicio,
#                 fin=fecha_fin,
#                 participantes_ids=[creador_id],
#             )
#             editar_evento(entrevista["evento_id"], evento_payload)
#         except Exception as e:
#             print(f"⚠️ Error al actualizar evento de calendario: {e}")
#
#     return EntrevistaOut.model_validate({**entrevista, **entrevista_actualizada})
#
#
# import unicodedata
#
# # Mapa de estado_id según el resultado de la entrevista
# # Ajusta los IDs si en tu catálogo son distintos
# RESULTADO_TO_ESTADO_ID = {
#     "PROGRAMADA": 4,
#     "ENTREVISTA": 4,
#     "INVITACION": 5,  # "Invitación"
#     "RECHAZADO": 7,
# }
#
# def _normalize_text(s: Optional[str]) -> Optional[str]:
#     if s is None:
#         return None
#     # quita acentos, pasa a mayúsculas y trimea
#     s = unicodedata.normalize("NFD", s)
#     s = "".join(ch for ch in s if not unicodedata.combining(ch))
#     return s.strip().upper()
#
# @app.put("/api/entrevistas/{creador_id}", response_model=EntrevistaOut, tags=["Entrevistas"])
# def actualizar_entrevista(
#     creador_id: int,
#     datos: EntrevistaUpdate,
#     usuario_actual: dict = Depends(obtener_usuario_actual),
# ):
#     usuario_id = usuario_actual.get("id")
#     if not usuario_id:
#         raise HTTPException(status_code=401, detail="Usuario no autorizado")
#
#     data_dict = datos.dict(exclude_unset=True)
#
#     # Si se marca como realizada, completa evaluador/fecha si no vienen
#     if data_dict.get("realizada"):
#         data_dict.setdefault("usuario_evalua", usuario_id)
#         data_dict.setdefault("fecha_realizada", datetime.utcnow())
#
#     # 1) Actualiza la entrevista
#     actualizado = actualizar_entrevista_por_creador(creador_id, data_dict)
#     if not actualizado:
#         raise HTTPException(status_code=404, detail="No existe entrevista para este creador")
#
#     # 2) Derivar estado_id a partir de `resultado`
#     #    - usa el que vino en el payload si está, si no el que quedó en DB
#     resultado_raw = data_dict.get("resultado") or actualizado.get("resultado")
#     resultado_norm = _normalize_text(resultado_raw)  # ENTREVISTA | INVITACION | RECHAZADO
#
#     estado_id = RESULTADO_TO_ESTADO_ID.get(resultado_norm)
#     if estado_id is not None:
#         try:
#             actualizar_estado_creador(creador_id, estado_id)
#         except Exception:
#             # Opcional: loggear si quieres, pero no romper la respuesta.
#             pass
#
#     # 3) Responder
#     return EntrevistaOut.model_validate(actualizado)


# GET por creador

@app.get("/api/invitaciones/{creador_id}", response_model=InvitacionOut, tags=["Invitaciones"])
def obtener_invitacion(creador_id: int):
    invitacion = obtener_invitacion_por_creador(creador_id)
    if not invitacion:
        raise HTTPException(status_code=404, detail="No existe invitación para este creador")
    return invitacion

# POST crear
@app.post("/api/invitaciones/{creador_id}", response_model=InvitacionOut, tags=["Invitaciones"])
def crear_invitacion(
    creador_id: int,
    datos: InvitacionCreate,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    usuario_id = usuario_actual.get("id")
    if not usuario_id:
        raise HTTPException(status_code=401, detail="Usuario no autorizado")

    payload = datos.dict(exclude_unset=True)
    payload["creador_id"] = creador_id
    payload["usuario_invita"] = usuario_id

    resultado = insertar_invitacion(payload)
    if not resultado:
        raise HTTPException(status_code=500, detail="Error al crear la invitación")

    return InvitacionOut.model_validate({**payload, **resultado})

# # PUT actualizar (por creador_id)
# @app.put("/api/invitaciones/{creador_id}", response_model=InvitacionOut, tags=["Invitaciones"])
# def actualizar_invitacion(
#     creador_id: int,
#     datos: InvitacionUpdate,
#     usuario_actual: dict = Depends(obtener_usuario_actual)
# ):
#     usuario_id = usuario_actual.get("id")
#     if not usuario_id:
#         raise HTTPException(status_code=401, detail="Usuario no autorizado")
#
#     # Tomamos solo los campos enviados, pero forzamos usuario_invita = usuario actual
#     update_data = datos.dict(exclude_unset=True)
#     update_data["usuario_invita"] = usuario_id
#
#     actualizado = actualizar_invitacion_por_creador(creador_id, update_data)
#     if not actualizado:
#         raise HTTPException(status_code=404, detail="No existe invitación para este creador")
#
#     return InvitacionOut.model_validate(actualizado)

# PUT actualizar invitación (por creador_id)
@app.put("/api/invitaciones/{creador_id}", response_model=InvitacionOut, tags=["Invitaciones"])
def actualizar_invitacion(
    creador_id: int,
    datos: InvitacionUpdate,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    usuario_id = usuario_actual.get("id")
    if not usuario_id:
        raise HTTPException(status_code=401, detail="Usuario no autorizado")

    # Tomamos solo los campos enviados, pero forzamos usuario_invita = usuario actual
    update_data = datos.dict(exclude_unset=True)
    update_data["usuario_invita"] = usuario_id

    # Actualizar invitación
    invitacion_actualizada = actualizar_invitacion_por_creador(creador_id, update_data)
    if not invitacion_actualizada:
        raise HTTPException(status_code=404, detail="No existe invitación para este creador")

    # ✅ Lógica adicional: actualizar estado_id en creadores
    estado = update_data.get("estado")
    if estado:
        try:
            if estado == "Aceptada por Aspirante":
                actualizar_estado_creador(creador_id, 6)
                print(f"🔄 Estado del creador {creador_id} actualizado a 6 (Aceptada por Aspirante)")
            elif estado == "Rechazada":
                actualizar_estado_creador(creador_id, 7)
                print(f"🔄 Estado del creador {creador_id} actualizado a 7 (Rechazada)")
        except Exception as e:
            print(f"⚠️ Error al actualizar estado del creador {creador_id}: {e}")

    return InvitacionOut.model_validate(invitacion_actualizada)



@app.put("/api/creadores/{creador_id}/estado",
         tags=["Creadores"],
         response_model=EstadoCreadorOut)
def actualizar_estado_creador_endpoint(
    creador_id: int,
    datos: EstadoCreadorIn = Body(...),
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    # Auth básica
    if not usuario_actual or not usuario_actual.get("id"):
        raise HTTPException(status_code=401, detail="Usuario no autorizado")

    # Resolver estado_id
    estado_id: Optional[int] = None

    if datos.estado_id is not None:
        estado_id = int(datos.estado_id)

    elif datos.estado_evaluacion:
        estado_id = ESTADO_MAP.get(datos.estado_evaluacion, ESTADO_DEFAULT)

    else:
        # nada enviado
        raise HTTPException(
            status_code=400,
            detail="Debes enviar 'estado_id' o 'estado_evaluacion'."
        )

    # Actualizar en DB
    res = actualizar_estado_creador(creador_id, estado_id)
    if not res:
        raise HTTPException(status_code=404, detail="Creador no encontrado")

    return EstadoCreadorOut(
        **res,
        mensaje="Estado del creador actualizado correctamente"
    )


# =====================
# 🎯 ENTREVISTAS Y AGENDAMIENTOS
# 🎯 ENTREVISTAS Y AGENDAMIENTOS
# =====================


class AgendamientoBase(BaseModel):
    entrevista_id: int
    creador_id: int
    fecha_programada: datetime
    duracion_minutos: Optional[int] = 30  # Agregar este campo
    usuario_programa: Optional[int] = None
    evento_id: Optional[str] = None

class AgendamientoCreate(AgendamientoBase):
    pass

class AgendamientoOut(BaseModel):
    id: int
    entrevista_id: int
    creador_id: int
    fecha_programada: datetime
    duracion_minutos: Optional[int]
    realizada: bool
    fecha_realizada: Optional[datetime]
    usuario_programa: Optional[int]
    evento_id: Optional[str]
    creado_en: datetime

# =====================
# 🎯 ENTREVISTAS
# =====================

class EntrevistaBase(BaseModel):
    creador_id: int
    usuario_evalua: Optional[int] = None
    resultado: Optional[str] = None
    observaciones: Optional[str] = None
    aspecto_tecnico: Optional[int] = None
    presencia_carisma: Optional[int] = None
    interaccion_audiencia: Optional[int] = None
    profesionalismo_normas: Optional[int] = None
    evaluacion_global: Optional[int] = None

class EntrevistaCreate(EntrevistaBase):
    pass

class EntrevistaUpdate(BaseModel):
    resultado: Optional[str] = None
    observaciones: Optional[str] = None
    usuario_evalua: Optional[int] = None
    aspecto_tecnico: Optional[int] = None
    presencia_carisma: Optional[int] = None
    interaccion_audiencia: Optional[int] = None
    profesionalismo_normas: Optional[int] = None
    evaluacion_global: Optional[int] = None

class EntrevistaOut(EntrevistaBase):
    id: int
    creado_en: datetime

class EntrevistaDetalleOut(EntrevistaOut):
    # 🔧 Importante: evitar mutable default
    agendamientos: List[AgendamientoOut] = Field(default_factory=list)



# =====================
# 🎯 EVENTOS
# =====================
from schemas import EventoIn,EventoOut

def insertar_entrevista(datos: dict):
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            columnas = ', '.join(datos.keys())
            placeholders = ', '.join(['%s'] * len(datos))
            sql = f"""
                INSERT INTO entrevistas ({columnas})
                VALUES ({placeholders})
                RETURNING id, creado_en
            """
            cur.execute(sql, tuple(datos.values()))
            row = cur.fetchone()
            conn.commit()
            return {"id": row[0], "creado_en": row[1]}
    except Exception as e:
        print("❌ Error al insertar entrevista:", e)
        return None
    finally:
        conn.close()

from typing import Optional

def insertar_agendamiento(datos: dict) -> Optional[dict]:
    """
    Inserta un agendamiento en entrevista_agendamiento y retorna
    un dict con todos los campos que AgendamientoOut espera.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Campos permitidos en la tabla
            allowed_cols = {
                "entrevista_id",
                "creador_id",
                "fecha_programada",
                "duracion_minutos",
                "usuario_programa",
                "evento_id",
                "realizada",
                "fecha_realizada",
            }

            # Filtra datos inesperados y aplica defaults
            payload = {k: v for k, v in datos.items() if k in allowed_cols}
            payload.setdefault("duracion_minutos", 60)
            payload.setdefault("realizada", False)

            cols = ", ".join(payload.keys())
            placeholders = ", ".join(["%s"] * len(payload))

            sql = f"""
                INSERT INTO entrevista_agendamiento ({cols})
                VALUES ({placeholders})
                RETURNING
                    id,
                    entrevista_id,
                    creador_id,
                    fecha_programada,
                    duracion_minutos,
                    realizada,
                    fecha_realizada,
                    usuario_programa,
                    evento_id,
                    creado_en
            """

            cur.execute(sql, tuple(payload.values()))
            row = cur.fetchone()
            conn.commit()

            if not row:
                return None

            # Orden debe coincidir con el RETURNING
            (
                _id,
                _entrevista_id,
                _creador_id,
                _fecha_programada,
                _duracion_minutos,
                _realizada,
                _fecha_realizada,
                _usuario_programa,
                _evento_id,
                _creado_en,
            ) = row

            return {
                "id": _id,
                "entrevista_id": _entrevista_id,
                "creador_id": _creador_id,
                "fecha_programada": _fecha_programada,
                "duracion_minutos": _duracion_minutos,
                "realizada": _realizada,
                "fecha_realizada": _fecha_realizada,
                "usuario_programa": _usuario_programa,
                "evento_id": _evento_id,
                "creado_en": _creado_en,
            }
    except Exception as e:
        # usa tu logger si ya lo tienes
        print("❌ Error al insertar agendamiento:", e)
        return None
    finally:
        conn.close()

def obtener_entrevista_con_agendamientos(creador_id: int):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            # 1) Entrevista más reciente del creador
            cur.execute("""
                SELECT id, creador_id, usuario_evalua, resultado, observaciones,
                       aspecto_tecnico, presencia_carisma, interaccion_audiencia,
                       profesionalismo_normas, evaluacion_global, creado_en
                FROM entrevistas
                WHERE creador_id = %s
                ORDER BY creado_en DESC
                LIMIT 1
            """, (creador_id,))
            e = cur.fetchone()
            if not e:
                return None

            entrevista_dict = {
                "id": e[0],
                "creador_id": e[1],
                "usuario_evalua": e[2],
                "resultado": e[3],
                "observaciones": e[4],
                "aspecto_tecnico": e[5],
                "presencia_carisma": e[6],
                "interaccion_audiencia": e[7],
                "profesionalismo_normas": e[8],
                "evaluacion_global": e[9],
                "creado_en": e[10],
                "agendamientos": []
            }

            # 2) Agendamientos relacionados (tabla: entrevista_agendamiento)
            cur.execute("""
                SELECT id, entrevista_id, creador_id, fecha_programada, duracion_minutos,
                       realizada, fecha_realizada, usuario_programa, evento_id, creado_en
                FROM entrevista_agendamiento
                WHERE entrevista_id = %s
                ORDER BY fecha_programada ASC
            """, (e[0],))
            rows = cur.fetchall()

            for r in rows:
                entrevista_dict["agendamientos"].append({
                    "id": r[0],
                    "entrevista_id": r[1],
                    "creador_id": r[2],
                    "fecha_programada": r[3],
                    "duracion_minutos": r[4],
                    "realizada": r[5],
                    "fecha_realizada": r[6],
                    "usuario_programa": r[7],
                    "evento_id": r[8],     # <- string/nullable
                    "creado_en": r[9],
                })

            return entrevista_dict
    except Exception as e:
        print(f"❌ Error al obtener entrevista con agendamientos: {e}")
        return None
    finally:
        if conn:
            conn.close()

def actualizar_entrevista(entrevista_id: int, datos: dict):
    if not datos:
        return None

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                set_clauses = [f"{key} = %s" for key in datos.keys()]
                values = list(datos.values())

                sql = f"""
                    UPDATE entrevistas
                    SET {', '.join(set_clauses)}
                    WHERE id = %s
                    RETURNING id, creador_id, resultado, observaciones, evaluacion_global, creado_en
                """
                values.append(entrevista_id)
                cur.execute(sql, tuple(values))
                row = cur.fetchone()
                conn.commit()
                if not row:
                    return None

                return {
                    "id": row[0],
                    "creador_id": row[1],
                    "resultado": row[2],
                    "observaciones": row[3],
                    "evaluacion_global": row[4],
                    "creado_en": row[5]
                }
    except Exception as e:
        print("❌ Error al actualizar entrevista:", e)
        return None

# ================================
# 📌 CREAR ENTREVISTA
# ================================
@app.post("/api/entrevistas/{creador_id}", response_model=EntrevistaOut)
def crear_entrevista(creador_id: int, datos: EntrevistaCreate, usuario_actual: dict = Depends(obtener_usuario_actual)):
    try:
        datos["creador_id"] = datos.get("creador_id")
        if not datos["creador_id"]:
            raise HTTPException(status_code=400, detail="El campo creador_id es obligatorio")

        datos["usuario_evalua"] = usuario_actual.get("id")  # si aplica
        resultado = insertar_entrevista(datos)
        if not resultado:
            raise HTTPException(status_code=500, detail="Error al insertar entrevista")
        return {"status": "ok", "entrevista": resultado}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al crear entrevista: {e}")

import logging
logger = logging.getLogger("uvicorn.error")

from datetime import datetime, timedelta
from fastapi import HTTPException, Depends

@app.post("/api/entrevistas/{entrevista_id}/agendamientos", response_model=AgendamientoOut)
def crear_agendamiento(
    entrevista_id: int,
    datos: AgendamientoCreate,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    try:
        if not usuario_actual:
            raise HTTPException(status_code=401, detail="Usuario no autorizado")

        # ✅ Pydantic model → dict (solo campos presentes)
        body = datos.dict(exclude_unset=True)

        # Validaciones mínimas (usando atributos del modelo)
        if datos.creador_id is None:
            raise HTTPException(status_code=400, detail="El campo creador_id es obligatorio")
        if datos.fecha_programada is None:
            raise HTTPException(status_code=400, detail="El campo fecha_programada es obligatorio")

        creador_id = datos.creador_id
        fecha_inicio: datetime = datos.fecha_programada

        # ✅ Duración: usar la del body o default 60 minutos
        duracion_minutos = datos.duracion_minutos if datos.duracion_minutos is not None else 60
        fecha_fin = fecha_inicio + timedelta(minutes=duracion_minutos)

        # === Crear evento en calendario (opcional) ===
        evento_id = None
        try:
            # Si tienes un modelo EventoIn diferente, ajusta estos campos
            evento_payload = EventoIn(
                titulo="Entrevista",
                descripcion="Entrevista programada",
                inicio=fecha_inicio,
                fin=fecha_fin,
                participantes_ids=[creador_id],
            )
            evento_creado = crear_evento(evento_payload, usuario_actual)
            evento_id = getattr(evento_creado, "id", None)
        except Exception as e:
            logger.warning(f"⚠️ Error al crear evento en calendario: {e}")
            evento_id = None

        # === Insertar agendamiento en DB ===
        # Importante: siempre usar el entrevista_id del path
        payload_ag = {
            "entrevista_id": entrevista_id,
            "creador_id": creador_id,
            "fecha_programada": fecha_inicio,
            "duracion_minutos": duracion_minutos,
            "usuario_programa": usuario_actual.get("id"),
            "evento_id": evento_id,
        }

        resultado = insertar_agendamiento(payload_ag)
        if not resultado:
            raise HTTPException(status_code=500, detail="Error al insertar agendamiento")

        # ✅ Devolver exactamente AgendamientoOut
        return AgendamientoOut(
            id=resultado["id"],
            entrevista_id=resultado["entrevista_id"],
            creador_id=resultado["creador_id"],
            fecha_programada=resultado["fecha_programada"],
            duracion_minutos=resultado.get("duracion_minutos"),
            realizada=resultado.get("realizada", False),
            fecha_realizada=resultado.get("fecha_realizada"),
            usuario_programa=resultado.get("usuario_programa"),
            evento_id=resultado.get("evento_id"),
            creado_en=resultado["creado_en"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("❌ Error al crear agendamiento")
        raise HTTPException(status_code=500, detail=f"Error al crear agendamiento: {e}")

@app.delete("/api/entrevistas/agendamientos/{agendamiento_id}", response_model=dict)
def eliminar_agendamiento(
    agendamiento_id: int,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    if not usuario_actual:
        raise HTTPException(status_code=401, detail="Usuario no autorizado")

    conn = get_connection()
    cur = conn.cursor()
    try:
        # 1. Buscar el evento_id asociado al agendamiento
        cur.execute("""
            SELECT evento_id
            FROM entrevista_agendamiento
            WHERE id = %s
        """, (agendamiento_id,))
        row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Agendamiento {agendamiento_id} no encontrado")

        evento_id = row[0]

        # 2. Eliminar el agendamiento
        cur.execute("DELETE FROM entrevista_agendamiento WHERE id = %s", (agendamiento_id,))
        conn.commit()

        # 3. Si tenía evento asociado, borrarlo de Google Calendar
        if evento_id:
            try:
                eliminar_evento(evento_id)
            except Exception as e:
                # No hacemos rollback del DELETE si falla el Calendar
                logger.warning(f"⚠️ No se pudo eliminar el evento {evento_id} en Calendar: {e}")

        return {
            "ok": True,
            "mensaje": f"Agendamiento {agendamiento_id} eliminado"
                      + (f" y evento {evento_id} eliminado" if evento_id else "")
        }

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error al eliminar agendamiento {agendamiento_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()


# ================================
# 📌 OBTENER ENTREVISTA + AGENDAMIENTOS
# ================================
@app.get("/api/entrevistas/{creador_id}", response_model=EntrevistaDetalleOut)
def obtener_entrevista(creador_id: int):
    try:
        entrevista = obtener_entrevista_con_agendamientos(creador_id)
        if not entrevista:
            # ❗ Si prefieres auto-crear entrevista en vez de 404,
            # llama a crear_entrevista_base(creador_id) y retorna esa.
            raise HTTPException(status_code=404, detail="Entrevista no encontrada")
        return entrevista
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener entrevista: {e}")

# Mapa de estado_id según el resultado de la entrevista
# Ajusta los IDs si en tu catálogo son distintos
RESULTADO_TO_ESTADO_ID = {
    "PROGRAMADA": 4,
    "ENTREVISTA": 4,
    "INVITACION": 5,  # "Invitación"
    "RECHAZADO": 7,
}

def _normalize_text(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    # quita acentos, pasa a mayúsculas y trimea
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.strip().upper()

import unicodedata
from typing import Optional
from fastapi import HTTPException, Depends
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from datetime import date

@app.put("/api/entrevistas/{creador_id}", response_model=EntrevistaOut, tags=["Entrevistas"])
def actualizar_entrevista(
    creador_id: int,
    datos: EntrevistaUpdate,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    usuario_id = usuario_actual.get("id")
    if not usuario_id:
        raise HTTPException(status_code=401, detail="Usuario no autorizado")

    # Solo campos presentes en el body
    payload = datos.dict(exclude_unset=True)

    # Si hay calificaciones pero no usuario_evalua, setear el evaluador actual
    if any(k in payload for k in (
        "aspecto_tecnico", "presencia_carisma",
        "interaccion_audiencia", "profesionalismo_normas",
        "evaluacion_global"
    )):
        payload.setdefault("usuario_evalua", usuario_id)

    # 1️⃣ Actualiza entrevista por creador
    actualizado = actualizar_entrevista_por_creador(creador_id, payload)
    if not actualizado:
        raise HTTPException(status_code=404, detail="No existe entrevista para este creador")

    # 2️⃣ Actualizar estado_id según `resultado`
    try:
        resultado_raw = payload.get("resultado") or actualizado.get("resultado")
        resultado_norm = _normalize_text(resultado_raw) if resultado_raw else None

        print(f"🧩 Resultado bruto recibido: {resultado_raw}")
        print(f"🧩 Resultado normalizado: {resultado_norm}")

        if resultado_norm:
            estado_id = RESULTADO_TO_ESTADO_ID.get(resultado_norm)

            if estado_id is None:
                print(
                    f"⚠️ Resultado '{resultado_norm}' no reconocido en RESULTADO_TO_ESTADO_ID, no se actualizará estado.")
            else:
                print(f"🔄 Estado asignado: {estado_id} (según resultado '{resultado_norm}')")

                # Actualiza el estado del creador
                actualizar_estado_creador(creador_id, estado_id)
                print(f"✅ Estado del creador {creador_id} actualizado correctamente a {estado_id}")

                # 3️⃣ Crear invitación automática si el resultado implica una invitación
                if estado_id == 5:  # 5 = INVITACIÓN
                    try:
                        print(f"📩 Intentando crear invitación automática para creador {creador_id}...")

                        # Llamamos directamente con parámetros, no con dict
                        invitacion_creada = crear_invitacion_minima(
                            creador_id=creador_id,
                            usuario_invita=usuario_id,
                            manager_id=None,
                            estado="sin programar"
                        )

                        if invitacion_creada:
                            print(f"✅ Invitación creada automáticamente para creador {creador_id}")
                        else:
                            print(
                                f"⚠️ No se pudo crear la invitación para creador {creador_id} (posiblemente ya existe).")

                    except Exception as e:
                        print(f"❌ Error al crear invitación automática para creador {creador_id}: {e}")

    except Exception as e:
        print(f"⚠️ Error general al actualizar estado o crear invitación: {e}")
        # No interrumpe la respuesta si algo falla


    # 4️⃣ Retorna respuesta normalizada
    return EntrevistaOut(
        id=actualizado["id"],
        creado_en=actualizado["creado_en"],
        creador_id=actualizado["creador_id"],
        usuario_evalua=actualizado.get("usuario_evalua"),
        resultado=actualizado.get("resultado"),
        observaciones=actualizado.get("observaciones"),
        aspecto_tecnico=actualizado.get("aspecto_tecnico"),
        presencia_carisma=actualizado.get("presencia_carisma"),
        interaccion_audiencia=actualizado.get("interaccion_audiencia"),
        profesionalismo_normas=actualizado.get("profesionalismo_normas"),
        evaluacion_global=actualizado.get("evaluacion_global"),
    )

from fastapi.responses import StreamingResponse

@app.middleware("http")
async def disable_partial_content(request: Request, call_next):
    response = await call_next(request)

    # Solo actuar si la respuesta es 206
    if response.status_code == 206:
        # Si es un StreamingResponse, debemos consumir el contenido
        if isinstance(response, StreamingResponse):
            body = b"".join([chunk async for chunk in response.body_iterator])
            headers = dict(response.headers)
            headers.pop("content-range", None)
            headers.pop("accept-ranges", None)
            return Response(content=body, status_code=200, headers=headers)

        # Si es respuesta normal
        body = getattr(response, "body", None)
        if body:
            headers = dict(response.headers)
            headers.pop("content-range", None)
            headers.pop("accept-ranges", None)
            return Response(content=body, status_code=200, headers=headers)

    return response

META_APP_ID = os.getenv("META_APP_ID")
META_APP_SECRET = os.getenv("META_APP_SECRET")
META_REDIRECT_URL = os.getenv("META_REDIRECT_URL")
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION")

# @app.post("/meta/exchange_code")
# async def exchange_code(payload: dict):
#     code = payload.get("code")
#
#     token_exchange_url = "https://graph.facebook.com/v21.0/oauth/access_token"
#
#     params = {
#         "code": code,
#         "client_id": META_APP_ID,
#         "client_secret": META_APP_SECRET,
#         "redirect_uri": META_REDIRECT_URL,
#     }
#
#     r = requests.get(token_exchange_url, params=params)
#     data = r.json()
#
#     access_token = data["access_token"]
#     whatsapp_business_account_id = data["whatsapp_business_account"]["id"]
#
#     # Guarda en DB (cuenta WABA, token, teléfono, etc.)
#     save_whatsapp_business_account(access_token, whatsapp_business_account_id)
#
#     return {"status": "ok"}

# @app.post("/meta/exchange_code")
# async def exchange_code(payload: dict):
#     logging.info(f"📥 Recibido payload: {payload}")
#     code = payload.get("code")
#
#     if not code:
#         logging.error("❌ No se recibió 'code'")
#         return {"error": "missing_code"}
#
#     token_exchange_url = "https://graph.facebook.com/v21.0/oauth/access_token"
#     params = {
#         "code": code,
#         "client_id": META_APP_ID,
#         "client_secret": META_APP_SECRET,
#         "redirect_uri": META_REDIRECT_URL,
#     }
#
#     try:
#         r = requests.get(token_exchange_url, params=params)
#         data = r.json()
#         logging.info(f"🔁 Respuesta Meta: {data}")
#     except Exception as e:
#         logging.exception("❌ Error al hacer request a Meta")
#         return {"error": str(e)}
#
#     access_token = data.get("access_token")
#     if not access_token:
#         logging.error("❌ No se recibió access_token de Meta")
#         return {"error": "no_access_token", "meta_response": data}
#
#     # 🔹 Consultar información del WABA
#     try:
#         url = f"https://graph.facebook.com/v21.0/me?fields=id,name,whatsapp_business_account&access_token={access_token}"
#         r = requests.get(url)
#         info = r.json()
#         logging.info(f"📦 Info de cuenta: {info}")
#
#         waba_id = info.get("whatsapp_business_account", {}).get("id")
#         business_id = info.get("id")
#
#         if not waba_id:
#             logging.warning("⚠️ No se encontró whatsapp_business_account en la respuesta.")
#             return {"warning": "no_waba_found", "info": info}
#
#         # ✅ Guardar en DB
#         save_whatsapp_business_account(access_token, waba_id, business_id)
#
#         return {"status": "ok", "waba_id": waba_id}
#
#     except Exception as e:
#         logging.exception("❌ Error al consultar WABA info")
#         return {"error": str(e)}

# @app.api_route("/meta/exchange_code", methods=["GET", "POST"])
# async def exchange_code(request: Request):
#     try:
#         # --- 1️⃣ Leer parámetros ---
#         params = dict(request.query_params)
#         body = await request.json() if request.method == "POST" else {}
#         code = params.get("code") or body.get("code")
#         state = params.get("state") or body.get("state")
#
#         if not code:
#             logging.error("❌ No se recibió ningún 'code'")
#             return {"error": "Falta parámetro code"}
#
#         logging.info(f"📥 Recibido code: {code}")
#
#         # --- 2️⃣ Intercambiar code por access_token ---
#         token_url = "https://graph.facebook.com/v20.0/oauth/access_token"
#         token_params = {
#             "client_id": META_APP_ID,
#             "client_secret": META_APP_SECRET,
#             "redirect_uri": META_REDIRECT_URL,
#             "code": code,
#         }
#
#         token_resp = requests.get(token_url, params=token_params)
#         token_data = token_resp.json()
#         logging.info(f"📤 Respuesta Meta: {token_data}")
#
#         if "access_token" not in token_data:
#             return {"error": "No se recibió access_token", "details": token_data}
#
#         access_token = token_data["access_token"]
#
#         # --- 3️⃣ Obtener WABA ID ---
#         waba_info_url = "https://graph.facebook.com/v20.0/me"
#         waba_params = {
#             "fields": "id,whatsapp_business_accounts{name}",
#             "access_token": access_token,
#         }
#         waba_info = requests.get(waba_info_url, params=waba_params).json()
#         logging.info(f"📦 WABA info: {waba_info}")
#
#         waba_id = None
#         if "whatsapp_business_accounts" in waba_info:
#             wabas = waba_info["whatsapp_business_accounts"].get("data", [])
#             if len(wabas) > 0:
#                 waba_id = wabas[0]["id"]
#
#         if not waba_id:
#             logging.error("❌ No se pudo obtener el WABA ID")
#             return {"error": "No se pudo obtener el WABA ID", "info": waba_info}
#
#         logging.info(f"✅ WABA ID obtenido: {waba_id}")
#
#         # --- 4️⃣ Guardar en base de datos (ejemplo genérico) ---
#         # Aquí iría tu código para insertar o actualizar en DB
#         # db.execute("INSERT INTO whatsapp_business_accounts ...")
#         logging.info("💾 Guardado en base de datos con éxito")
#
#         # --- 5️⃣ Responder al navegador ---
#         return {
#             "status": "success",
#             "waba_id": waba_id,
#             "access_token": access_token,
#             "state": state,
#             "timestamp": datetime.utcnow().isoformat(),
#         }
#
#     except Exception as e:
#         logging.exception("❌ Error en exchange_code")
#         return {"error": str(e)}

# @app.post("/meta/exchange_code")
# async def exchange_code(request: Request):
#     data = await request.json()
#     code = data.get("code")
#
#     if not code:
#         return {"error": "No llegó code desde Meta"}
#
#     logging.info(f"📥 Code recibido desde onboarding: {code}")
#
#     # Por ahora solo regresamos confirmación
#     return {
#         "status": "received",
#         "code": code
#     }

@app.api_route("/meta/exchange_code", methods=["GET", "POST", "OPTIONS"])
async def exchange_code(request: Request):
    # Manejar preflight CORS
    if request.method == "OPTIONS":
        return JSONResponse(
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )

    try:
        # Extraer parámetros según el método
        if request.method == "GET":
            code = request.query_params.get("code")
            waba_id = request.query_params.get("waba_id")
            phone_id = request.query_params.get("phone_id")  # phone_number_id del frontend
        else:
            payload = await request.json()
            code = payload.get("code")
            waba_id = payload.get("waba_id")
            phone_id = payload.get("phone_id")  # phone_number_id del frontend

        # Logging mejorado (enmascarar código parcialmente)
        code_masked = f"{code[:6]}...{code[-6:]}" if code and len(code) > 12 else "***"
        logging.info(f"📥 Code recibido desde onboarding: {code_masked}")
        if waba_id:
            logging.info(f"📱 WABA ID recibido: {waba_id}")
        if phone_id:
            logging.info(f"📞 Phone ID recibido: {phone_id}")

        # Validar que existe code
        if not code:
            logging.error("❌ No se recibió 'code'")
            return JSONResponse(
                status_code=400,
                content={"error": "missing_code", "message": "El parámetro 'code' es requerido"}
            )

        # Intercambiar code por access_token
        token_exchange_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/oauth/access_token"
        params = {
            "code": code,
            "client_id": META_APP_ID,
            "client_secret": META_APP_SECRET,
            "redirect_uri": META_REDIRECT_URL,
        }

        try:
            r = requests.get(token_exchange_url, params=params, timeout=30)
            r.raise_for_status()
        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Error en request a Meta API: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": "meta_api_error", "message": f"Error al comunicarse con Meta: {str(e)}"}
            )

        # Validar respuesta JSON
        try:
            data = r.json()
        except ValueError as e:
            logging.error(f"❌ Error parseando respuesta JSON de Meta: {str(e)}")
            logging.error(f"📄 Respuesta recibida: {r.text[:500]}")
            return JSONResponse(
                status_code=500,
                content={"error": "invalid_json_response", "message": "La respuesta de Meta no es JSON válido"}
            )

        logging.info(f"📤 Respuesta Meta: {json.dumps(data, indent=2)}")

        # Verificar errores en la respuesta de Meta
        if "error" in data:
            error_code = data.get("error", {}).get("code", "unknown")
            error_message = data.get("error", {}).get("message", "Error desconocido")
            logging.error(f"❌ Error de Meta API: {error_code} - {error_message}")
            return JSONResponse(
                status_code=400,
                content={"error": "meta_api_error", "code": error_code, "message": error_message}
            )

        # Extraer access_token
        access_token = data.get("access_token")
        if not access_token:
            logging.error("❌ No se recibió access_token en la respuesta")
            logging.error(f"📄 Respuesta completa: {json.dumps(data, indent=2)}")
            return JSONResponse(
                status_code=400,
                content={"error": "no_access_token", "message": "No se recibió access_token en la respuesta de Meta"}
            )

        # Extraer información de WABA de la respuesta de Meta
        waba_info = data.get("whatsapp_business_account", {})
        waba_id_from_response = waba_info.get("id") or waba_id

        # Intentar obtener información adicional del WABA usando el access_token
        # (opcional: para obtener business_name, phone_number, etc.)
        business_name = None
        phone_number = None

        if access_token and waba_id_from_response:
            try:
                # Obtener información del WABA desde Graph API
                waba_info_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{waba_id_from_response}"
                waba_params = {
                    "fields": "name,timezone_id",
                    "access_token": access_token
                }
                waba_response = requests.get(waba_info_url, params=waba_params, timeout=10)
                if waba_response.status_code == 200:
                    waba_data = waba_response.json()
                    business_name = waba_data.get("name")
                    logging.info(f"📋 Business Name obtenido: {business_name}")
            except Exception as e:
                logging.warning(f"⚠️ No se pudo obtener información adicional del WABA: {str(e)}")

        # Logging de éxito
        logging.info(f"✅ Access token obtenido exitosamente")
        logging.info(f"✅ WABA ID: {waba_id_from_response}")

        # Guardar información en la BD
        success = save_whatsapp_business_account(
            access_token=access_token,
            waba_id=waba_id_from_response,
            phone_number_id=phone_id,  # ✅ Mapear phone_id del frontend a phone_number_id
            phone_number=phone_number,  # Se puede obtener más adelante si es necesario
            business_name=business_name
        )

        if not success:
            logging.warning("⚠️ WABA no se pudo guardar en BD, pero el access_token fue obtenido")

        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "waba_id": waba_id_from_response,
                "phone_id": phone_id,
            },
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            }
        )

    except Exception as e:
        logging.exception(f"❌ Error inesperado en exchange_code: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": f"Error interno del servidor: {str(e)}"}
        )