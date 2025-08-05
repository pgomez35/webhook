# ✅ main.py
from fastapi import FastAPI, HTTPException, Path, Body, Request, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
import psycopg2
from schemas import *

from googleapiclient.discovery import build
from uuid import uuid4

# Tu propio código/librerías
from enviar_msg_wp import *
from buscador import inicializar_busqueda, responder_pregunta
from DataBase import *
from Excel import *



# 🔄 Cargar variables de entorno
load_dotenv()
API_KEY = os.getenv("OPENAI_API_KEY")
TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "142848PITUFO")
CHROMA_DIR = "./chroma_faq_openai"

# ⚙️ Inicializar FastAPI
app = FastAPI()

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
    return JSONResponse(
        status_code=500,
        content={"detail": "Error interno del servidor"}
    )
# ==================== FUNCIONES DE BD PARA TOKEN ===========================

def guardar_token_en_bd(token_dict, nombre='calendar'):
    try:
        conn = psycopg2.connect(DB_URL)
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
        conn = psycopg2.connect(DB_URL)
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
def get_calendar_service():
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

# ==================== OBTENER EVENTOS ==============================

# def obtener_eventos() -> List[EventoOut]:
#     try:
#         service = get_calendar_service()
#     except Exception as e:
#         logger.error(f"❌ Error al obtener el servicio de Calendar: {str(e)}")
#         raise
#
#     # Obtener eventos desde hace 30 días hasta 1 año en el futuro
#     hace_30_dias = (datetime.utcnow() - timedelta(days=30)).isoformat() + 'Z'
#     un_ano_futuro = (datetime.utcnow() + timedelta(days=365)).isoformat() + 'Z'
#
#     try:
#         events_result = service.events().list(
#             calendarId='primary',
#             timeMin=hace_30_dias,  # Desde hace 30 días
#             timeMax=un_ano_futuro,  # Hasta 1 año en el futuro
#             maxResults=100, singleEvents=True,
#             orderBy='startTime'
#         ).execute()
#     except Exception as e:
#         logger.error(f"❌ Error al obtener eventos de Google Calendar API: {str(e)}")
#         logger.error(traceback.format_exc())
#         raise
#
#     events = events_result.get('items', [])
#     resultado = []
#     for event in events:
#         inicio = event['start'].get('dateTime')
#         fin = event['end'].get('dateTime')
#         titulo = event.get('summary', 'Sin título')
#         descripcion = event.get('description', '')
#
#         # leer link meet
#         meet_link = None
#         if 'conferenceData' in event:
#             entry_points = event['conferenceData'].get('entryPoints', [])
#             for ep in entry_points:
#                 if ep.get('entryPointType') == 'video':
#                     meet_link = ep.get('uri')
#                     break
#
#         tiktok_user = event.get('extendedProperties', {}).get('private', {}).get('tiktok_user')
#
#         if inicio and fin:
#             resultado.append(EventoOut(
#                 id=event['id'],
#                 titulo=titulo,
#                 inicio=isoparse(inicio),
#                 fin=isoparse(fin),
#                 descripcion=descripcion,
#                 tiktok_user=tiktok_user,
#                 link_meet=meet_link
#             ))
#
#     return resultado

def obtener_eventos() -> List[EventoOut]:
    try:
        service = get_calendar_service()
    except Exception as e:
        logger.error(f"❌ Error al obtener el servicio de Calendar: {str(e)}")
        raise

    # Obtener eventos desde hace 30 días hasta 1 año en el futuro
    hace_30_dias = (datetime.utcnow() - timedelta(days=30)).isoformat() + 'Z'
    un_ano_futuro = (datetime.utcnow() + timedelta(days=365)).isoformat() + 'Z'

    try:
        events_result = service.events().list(
            calendarId='primary',
            timeMin=hace_30_dias,  # Desde hace 30 días
            timeMax=un_ano_futuro,  # Hasta 1 año en el futuro
            maxResults=100, singleEvents=True,
            orderBy='startTime'
        ).execute()
    except Exception as e:
        logger.error(f"❌ Error al obtener eventos de Google Calendar API: {str(e)}")
        logger.error(traceback.format_exc())
        raise

    events = events_result.get('items', [])
    resultado = []

    for event in events:
        try:  # ← AGREGAR manejo de errores por evento individual
            inicio = event['start'].get('dateTime')
            fin = event['end'].get('dateTime')
            titulo = event.get('summary', 'Sin título')
            descripcion = event.get('description', '')

            # leer link meet
            meet_link = None
            if 'conferenceData' in event:
                entry_points = event['conferenceData'].get('entryPoints', [])
                for ep in entry_points:
                    if ep.get('entryPointType') == 'video':
                        meet_link = ep.get('uri')
                        break

            tiktok_user = event.get('extendedProperties', {}).get('private', {}).get('tiktok_user')

            # ← BUSCAR creador_id basado en tiktok_user si existe
            creador_id = None
            if tiktok_user:
                # Buscar en la base de datos el creador_id por usuario
                creador_id = obtener_creador_id_por_usuario(tiktok_user)

            if inicio and fin:
                resultado.append(EventoOut(
                    id=event['id'],
                    titulo=titulo,
                    inicio=isoparse(inicio),
                    fin=isoparse(fin),
                    descripcion=descripcion,
                    tiktok_user=tiktok_user,
                    creador_id=creador_id,  # ← AGREGAR este campo
                    link_meet=meet_link
                ))

        except Exception as e:
            # ← MANEJAR errores de eventos individuales
            logger.warning(f"⚠️ Saltando evento con error: {event.get('id', 'unknown')} - {str(e)}")
            continue  # Continuar con el siguiente evento

    logger.info(f"✅ Se obtuvieron {len(resultado)} eventos de Google Calendar")
    return resultado



def sync_eventos():
    eventos = obtener_eventos()
    logger.info(f"🔄 Se encontraron {len(eventos)} eventos en Google Calendar")
    for evento in eventos:
        logger.info(f"📅 Evento: {evento.titulo} | 🕐 Inicio: {evento.inicio} | 🕓 Fin: {evento.fin} | 📝 Descripción: {evento.descripcion}")

# ==================== RUTAS FASTAPI ==============================

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

# @app.put("/api/eventos/{evento_id}", response_model=EventoOut)
# def editar_evento(evento_id: str, evento: EventoIn):
#     try:
#         # Validar las fechas ANTES de proceder
#         if evento.fin <= evento.inicio:
#             raise HTTPException(
#                 status_code=400,
#                 detail="La fecha de fin debe ser posterior a la fecha de inicio."
#             )
#
#         service = get_calendar_service()
#         google_event = service.events().get(calendarId="primary", eventId=evento_id).execute()
#
#         # Actualizar campos
#         google_event['summary'] = evento.titulo
#         google_event['description'] = evento.descripcion
#         google_event['start']['dateTime'] = evento.inicio.isoformat()
#         google_event['end']['dateTime'] = evento.fin.isoformat()
#
#         # Guardar evento actualizado
#         updated = service.events().update(calendarId="primary", eventId=evento_id, body=google_event).execute()
#
#         return EventoOut(
#             id=updated['id'],
#             titulo=updated['summary'],
#             inicio=isoparse(updated['start']['dateTime']),
#             fin=isoparse(updated['end']['dateTime']),
#             descripcion=updated.get('description')
#         )
#     except Exception as e:
#         logger.error(f"❌ Error al editar evento {evento_id}: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

# @app.put("/api/eventos/{evento_id}", response_model=EventoOut)
# def editar_evento(evento_id: str, evento: EventoIn):
#     try:
#         if evento.fin <= evento.inicio:
#             raise HTTPException(status_code=400, detail="La fecha de fin debe ser posterior a la fecha de inicio.")
#
#         service = get_calendar_service()
#         google_event = service.events().get(calendarId="primary", eventId=evento_id).execute()
#
#         google_event['summary'] = evento.titulo
#         google_event['description'] = evento.descripcion
#         google_event['start']['dateTime'] = evento.inicio.isoformat()
#         google_event['end']['dateTime'] = evento.fin.isoformat()
#
#         if 'extendedProperties' not in google_event:
#             google_event['extendedProperties'] = {'private': {}}
#         google_event['extendedProperties']['private']['tiktok_user'] = evento.tiktok_user or ""
#
#         updated = service.events().update(
#             calendarId="primary",
#             eventId=evento_id,
#             body=google_event,
#             conferenceDataVersion=1
#         ).execute()
#
#         meet_link = None
#         if 'conferenceData' in updated:
#             entry_points = updated['conferenceData'].get('entryPoints', [])
#             for ep in entry_points:
#                 if ep.get('entryPointType') == 'video':
#                     meet_link = ep.get('uri')
#                     break
#
#         return EventoOut(
#             id=updated['id'],
#             titulo=updated['summary'],
#             inicio=isoparse(updated['start']['dateTime']),
#             fin=isoparse(updated['end']['dateTime']),
#             descripcion=updated.get('description'),
#             tiktok_user=evento.tiktok_user,
#             link_meet=meet_link
#         )
#     except Exception as e:
#         logger.error(f"❌ Error al editar evento {evento_id}: {e}")
#         logger.error(traceback.format_exc())
#         raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/eventos/{evento_id}", response_model=EventoOut)
def editar_evento(evento_id: str, evento: EventoIn):
    conn, cur = get_connection()
    try:
        if evento.fin <= evento.inicio:
            raise HTTPException(status_code=400, detail="La fecha de fin debe ser posterior a la fecha de inicio.")

        # Actualizar en Google Calendar
        service = get_calendar_service()
        google_event = service.events().get(calendarId="primary", eventId=evento_id).execute()

        google_event['summary'] = evento.titulo
        google_event['description'] = evento.descripcion
        google_event['start']['dateTime'] = evento.inicio.isoformat()
        google_event['end']['dateTime'] = evento.fin.isoformat()

        if 'extendedProperties' not in google_event:
            google_event['extendedProperties'] = {'private': {}}
        google_event['extendedProperties']['private']['tiktok_user'] = evento.tiktok_user or ""

        updated = service.events().update(
            calendarId="primary",
            eventId=evento_id,
            body=google_event,
            conferenceDataVersion=1
        ).execute()

        # Obtener link de Meet (si existe)
        meet_link = None
        if 'conferenceData' in updated:
            entry_points = updated['conferenceData'].get('entryPoints', [])
            for ep in entry_points:
                if ep.get('entryPointType') == 'video':
                    meet_link = ep.get('uri')
                    break

        # Actualizar también en la base de datos
        cur.execute("""
            UPDATE agendamientos
            SET fecha_inicio = %s,
                fecha_fin = %s,
                titulo = %s,
                descripcion = %s,
                link_meet = %s
            WHERE google_event_id = %s
        """, (
            evento.inicio,
            evento.fin,
            evento.titulo,
            evento.descripcion,
            meet_link,
            evento_id
        ))
        conn.commit()

        return EventoOut(
            id=updated['id'],
            titulo=updated['summary'],
            inicio=isoparse(updated['start']['dateTime']),
            fin=isoparse(updated['end']['dateTime']),
            descripcion=updated.get('description'),
            tiktok_user=evento.tiktok_user,
            link_meet=meet_link
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
        service.events().delete(calendarId="primary", eventId=evento_id).execute()

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("DELETE FROM agendamientos WHERE google_event_id = %s", (evento_id,))
        conn.commit()
        cur.close()
        conn.close()

        return {"ok": True, "mensaje": f"Evento {evento_id} eliminado"}
    except Exception as e:
        logger.error(f"❌ Error al eliminar evento {evento_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

from fastapi import Depends
from Agendamientos import get_connection
from auth import *
from schemas import EventoOut, EventoIn
import traceback, logging
from uuid import uuid4
from dateutil.parser import isoparse

logger = logging.getLogger(__name__)

@app.post("/api/eventos", response_model=EventoOut)
def crear_eventoV0(evento: EventoIn, usuario_actual_id: int = Depends(get_usuario_actual_id)):
    conn, cur = get_connection()
    try:
        if evento.fin <= evento.inicio:
            raise HTTPException(status_code=400, detail="La fecha de fin debe ser posterior a la fecha de inicio.")

        service = get_calendar_service()

        event = {
            "summary": evento.titulo,
            "description": evento.descripcion or "",
            "start": {"dateTime": evento.inicio.isoformat()},
            "end": {"dateTime": evento.fin.isoformat()},
            "conferenceData": {
                "createRequest": {
                    "requestId": str(uuid4())
                }
            },
            "extendedProperties": {
                "private": {
                    "tiktok_user": evento.tiktok_user or ""
                }
            }
        }

        creado = service.events().insert(
            calendarId="primary",
            body=event,
            conferenceDataVersion=1
        ).execute()

        # Link de Meet
        meet_link = None
        if 'conferenceData' in creado:
            for ep in creado['conferenceData'].get('entryPoints', []):
                if ep.get('entryPointType') == 'video':
                    meet_link = ep.get('uri')
                    break

        # Guardar en la base de datos
        cur.execute("""
            INSERT INTO agendamientos (creador_id, fecha_inicio, fecha_fin, titulo, descripcion, link_meet, estado, responsable_id, google_event_id)
            VALUES (%s, %s, %s, %s, %s, %s, 'programado', %s, %s)
        """, (
            evento.creador_id,
            evento.inicio,
            evento.fin,
            evento.titulo,
            evento.descripcion,
            meet_link,
            usuario_actual_id,
            creado["id"]
        ))
        conn.commit()

        return EventoOut(
            id=creado["id"],
            titulo=creado.get("summary"),
            inicio=isoparse(creado["start"]["dateTime"]),
            fin=isoparse(creado["end"]["dateTime"]),
            descripcion=creado.get("description"),
            tiktok_user=evento.tiktok_user,
            link_meet=meet_link
        )

    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error al crear evento: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

# @router.post("/agendamientos/", response_model=AgendamientoOut)


# @app.post("/api/eventos", response_model=EventoOut)
# def crear_evento(agendamiento: EventoIn):
#     try:
#         creds = Credentials.from_authorized_user_file("token.json")  # debes tener tu token guardado
#
#         service = build("calendar", "v3", credentials=creds)
#
#         evento = {
#             "summary": agendamiento.titulo,
#             "description": agendamiento.descripcion,
#             "start": {
#                 "dateTime": agendamiento.inicio.isoformat(),
#                 "timeZone": "America/Bogota"
#             },
#             "end": {
#                 "dateTime": agendamiento.fin.isoformat(),
#                 "timeZone": "America/Bogota"
#             },
#             "location": agendamiento.ubicacion,
#             "conferenceData": {
#                 "createRequest": {
#                     "requestId": str(uuid.uuid4()),
#                     "conferenceSolutionKey": {
#                         "type": "hangoutsMeet"
#                     }
#                 }
#             },
#             "attendees": [{"email": "invitado@ejemplo.com"}],  # opcional
#         }
#
#         evento_creado = service.events().insert(
#             calendarId='primary',
#             body=evento,
#             conferenceDataVersion=1
#         ).execute()
#
#         meet_link = evento_creado['hangoutLink']
#
#         # Guardar agendamiento en la BD con link_meet
#         nuevo_agendamiento = guardar_en_bd(agendamiento, meet_link)
#         return nuevo_agendamiento
#
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/eventos", response_model=EventoOut)
def crear_evento(evento: EventoIn,
    usuario_actual: dict = Depends(obtener_usuario_actual)):
    try:
        # 1. Crear el evento en Google Calendar
        google_event = crear_evento_google(
            resumen=evento.titulo,
            descripcion=evento.descripcion or "",
            fecha_inicio=evento.inicio,
            fecha_fin=evento.fin
        )

        link_meet = google_event["hangoutLink"]
        google_event_id = google_event["id"]

        # 2. Guardar en la base de datos
        if not guardar_en_bd(evento, link_meet, google_event_id, usuario_actual["id"]):
            raise HTTPException(status_code=500, detail="Error al guardar agendamiento")

        return {"status": "ok", "mensaje": "Evento creado exitosamente", "meet_link": link_meet}

    except Exception as e:
        print("Error creando evento:", e)
        raise HTTPException(status_code=500, detail="Error creando evento")

def crear_evento_google(resumen, descripcion, fecha_inicio, fecha_fin):
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
        calendarId='primary',
        body=evento,
        conferenceDataVersion=1
    ).execute()

    return evento_creado


@app.get("/api/agendamientos")
def listar_agendamientos():
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("""
            SELECT a.id, a.titulo, a.descripcion, a.fecha_inicio, a.fecha_fin,
                   a.creador_id, a.responsable_id, a.estado, a.link_meet,
                   c.nickname, u.nombre_completo
            FROM agendamientos a
            LEFT JOIN creadores c ON c.id = a.creador_id
            LEFT JOIN admin_usuario u ON u.id = a.responsable_id
            ORDER BY a.fecha_inicio DESC;
        """)
        filas = cur.fetchall()
        columnas = [desc[0] for desc in cur.description]
        eventos = [dict(zip(columnas, fila)) for fila in filas]
        cur.close()
        conn.close()
        return eventos
    except Exception as e:
        logger.error(f"❌ Error consultando agendamientos: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# @app.post("/api/eventos", response_model=EventoOut)
# def crear_evento(evento: EventoIn):
#     try:
#         if evento.fin <= evento.inicio:
#             raise HTTPException(status_code=400, detail="La fecha de fin debe ser posterior a la fecha de inicio.")
#
#         service = get_calendar_service()
#
#         event = {
#             "summary": evento.titulo,
#             "description": evento.descripcion or "",
#             "start": {"dateTime": evento.inicio.isoformat()},
#             "end": {"dateTime": evento.fin.isoformat()},
#             "conferenceData": {
#                 "createRequest": {
#                     "requestId": str(uuid4())  # genera ID único para que cree link Meet
#                 }
#             },
#             "extendedProperties": {
#                 "private": {
#                     "tiktok_user": evento.tiktok_user or ""
#                 }
#             }
#         }
#
#         creado = service.events().insert(
#             calendarId="primary",
#             body=event,
#             conferenceDataVersion=1
#         ).execute()
#
#         # leer link Meet
#         meet_link = None
#         if 'conferenceData' in creado:
#             entry_points = creado['conferenceData'].get('entryPoints', [])
#             for ep in entry_points:
#                 if ep.get('entryPointType') == 'video':
#                     meet_link = ep.get('uri')
#                     break
#
#         return EventoOut(
#             id=creado["id"],
#             titulo=creado.get("summary"),
#             inicio=isoparse(creado["start"]["dateTime"]),
#             fin=isoparse(creado["end"]["dateTime"]),
#             descripcion=creado.get("description"),
#             tiktok_user=evento.tiktok_user,
#             link_meet=meet_link
#         )
#     except Exception as e:
#         logger.error(f"❌ Error al crear evento: {e}")
#         logger.error(traceback.format_exc())
#         raise HTTPException(status_code=500, detail=str(e))

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
        return ruta_archivo

    except Exception as e:
        print("❌ Error al descargar audio:", e)
        return None

@app.patch("/contacto_info/{telefono}")
def actualizar_contacto_info(telefono: str = Path(...), datos: ActualizacionContactoInfo = Body(...)):
    return actualizar_contacto_info_db(telefono, datos)

@app.get("/contactos")
def listar_contactos(perfil: Optional[str] = None):
    return obtener_contactos_db(perfil)

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

# 📩 PROCESAMIENTO DE MENSAJES ENVIADOS AL WEBHOOK
@app.post("/webhook")
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
        mensaje_usuario = None
        es_audio = False
        audio_id = None
        if tipo == "text":
            mensaje_usuario = mensaje.get("text", {}).get("body")
        elif tipo == "audio":
            es_audio = True
            audio_info = mensaje.get("audio", {})
            audio_id = audio_info.get("id")
            mensaje_usuario = f"[Audio recibido: {audio_id}]"
        elif tipo == "button":
            mensaje_usuario = mensaje.get("button", {}).get("text")
            print(f"👆 Botón presionado: {mensaje_usuario}")
        if not telefono or not mensaje_usuario:
            print("⚠️ Mensaje incompleto.")
            return JSONResponse({"status": "ok", "detalle": "Mensaje incompleto"}, status_code=200)
        print(f"📥 Mensaje recibido de {telefono}: {mensaje_usuario}")
        guardar_mensaje(telefono, mensaje_usuario, tipo="recibido", es_audio=es_audio)
        if es_audio:
            ruta = descargar_audio(audio_id, TOKEN)
            return JSONResponse({"status": "ok", "detalle": f"Audio guardado en {ruta}"})
        # ✉️ Enviar respuesta automática
        respuesta = "Gracias por tu mensaje, te escribiremos una respuesta tan pronto podamos"
        codigo, respuesta_api = enviar_mensaje_texto_simple(
            token=TOKEN,
            numero_id=PHONE_NUMBER_ID,
            telefono_destino=telefono,
            texto=respuesta,
        )
        guardar_mensaje(telefono, respuesta, tipo="enviado")
        print(f"✅ Código de envío: {codigo}")
        print("🛰️ Respuesta API:", respuesta_api)
        return JSONResponse({
            "status": "ok",
            "respuesta": respuesta,
            "codigo_envio": codigo,
            "respuesta_api": respuesta_api,
        })
    except Exception as e:
        print("❌ Error procesando mensaje:", e)
        return JSONResponse({"error": str(e)}, status_code=500)

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
        plantilla = "reconectar_usuario_boton"
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
    guardar_mensaje(
        telefono,
        f"[Audio guardado: {filename_ogg}]",
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
            "error": str(e)
        }
    return {
        "status": "ok",
        "mensaje": "Audio recibido y enviado por WhatsApp",
        "archivo": filename_ogg,
        "codigo_api": codigo,
        "respuesta_api": respuesta_api
    }

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

@app.put("/api/admin-usuario/{usuario_id}", response_model=AdminUsuarioResponse)
async def actualizar_usuario(usuario_id: int, usuario: AdminUsuarioUpdate):
    """Actualiza un usuario administrador"""
    usuario_actualizado = actualizar_admin_usuario(usuario_id, usuario)
    if not usuario_actualizado:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return usuario_actualizado

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

@app.post("/api/admin-usuario/login")
async def login_usuario(credentials: dict = Body(...)):
    """Autentica un usuario administrador"""
    username = credentials.get("username")
    password = credentials.get("password")
    
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username y password son requeridos")
    
    # Verificar credenciales
    usuario = obtener_admin_usuario_por_username(username)
    if not usuario or not verify_password(password, usuario["password_hash"]):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    
    # Retornar datos del usuario sin el password_hash
    usuario_response = {k: v for k, v in usuario.items() if k != "password_hash"}
    return {"usuario": usuario_response, "mensaje": "Login exitoso"}

#-------------------------
#-------------------------

# === Listar todos los creadores ===
@app.get("/api/creadores", tags=["Creadores"])
def listar_creadores():
    try:
        return obtener_creadores()
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


# === Estadísticas globales de evaluación ===
@app.get("/api/estadisticas-evaluacion", tags=["Estadísticas"])
def estadisticas_evaluacion():
    try:
        return obtener_estadisticas_evaluacion()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Actualizar datos personales ===
@app.put("/api/perfil_creador/{creador_id}/datos_personales", tags=["Perfil"])
def actualizar_datos_personales(creador_id: int, datos: DatosPersonalesSchema):
    try:
        actualizar_datos_perfil_creador(creador_id, datos.dict(exclude_unset=True))
        return {"status": "ok", "mensaje": "Datos personales actualizados"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Actualizar evaluación cualitativa ===
@app.put("/api/perfil_creador/{creador_id}/evaluacion_cualitativa", tags=["Evaluación"])
def actualizar_eval_cualitativa(creador_id: int, datos: EvaluacionCualitativaSchema):
    try:
        actualizar_datos_perfil_creador(creador_id, datos.dict(exclude_unset=True))
        return {"status": "ok", "mensaje": "Evaluación cualitativa actualizada"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Actualizar estadísticas del perfil ===
@app.put("/api/perfil_creador/{creador_id}/estadisticas", tags=["Estadísticas"])
def actualizar_estadisticas(creador_id: int, datos: EstadisticasPerfilSchema):
    try:
        actualizar_datos_perfil_creador(creador_id, datos.dict(exclude_unset=True))
        return {"status": "ok", "mensaje": "Estadísticas actualizadas"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Actualizar preferencias y hábitos ===
@app.put("/api/perfil_creador/{creador_id}/preferencias", tags=["Preferencias"])
def actualizar_preferencias(creador_id: int, datos: PreferenciasHabitosSchema):
    try:
        actualizar_datos_perfil_creador(creador_id, datos.dict(exclude_unset=True))
        return {"status": "ok", "mensaje": "Preferencias actualizadas"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Actualizar resumen y estado ===
@app.put("/api/perfil_creador/{creador_id}/resumen", tags=["Resumen"])
def actualizar_resumen(creador_id: int, datos: ResumenEvaluacionSchema):
    try:
        actualizar_datos_perfil_creador(creador_id, datos.dict(exclude_unset=True))
        return {"status": "ok", "mensaje": "Resumen actualizado"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))