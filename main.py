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

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel

# Integración Google Calendar
from dateutil.parser import isoparse
from google.oauth2.credentials import Credentials
import google.oauth2.credentials  # <--- Esto es lo que te falta

import sys
print("==== DEBUG GOOGLE AUTH ====")
print("google.oauth2.credentials path:", google.oauth2.credentials.__file__)
print("sys.path:", sys.path)
print("Credentials class:", google.oauth2.credentials.Credentials)
print("Has from_authorized_user_file:", hasattr(google.oauth2.credentials.Credentials, "from_authorized_user_file"))
print("Has from_authorized_user_info:", hasattr(google.oauth2.credentials.Credentials, "from_authorized_user_info"))
print("===========================")



from googleapiclient.discovery import build
from uuid import uuid4

# Tu propio código/librerías
from enviar_msg_wp import *
from buscador import inicializar_busqueda, responder_pregunta
from DataBase import *
from Excel import *
from schemas import ActualizacionContactoInfo


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
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
CREDENTIALS_PATH = 'google_credentials_temp.json'
TOKEN_PATH = 'google_token_temp.json'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("calendar_sync")

class EventoOut(BaseModel):
    titulo: str
    inicio: datetime
    fin: datetime
    descripcion: Optional[str] = None

def ensure_credentials_file():
    if not os.path.exists(CREDENTIALS_PATH):
        creds_content = os.getenv("GOOGLE_CREDENTIALS_JSON_CALEND")
        if not creds_content:
            raise RuntimeError("No se encontró la variable de entorno GOOGLE_CREDENTIALS_JSON_CALEND.")
        try:
            parsed_json = json.loads(creds_content)
            with open(CREDENTIALS_PATH, 'w') as f:
                json.dump(parsed_json, f)
            logger.info(f"✅ Archivo temporal {CREDENTIALS_PATH} creado desde variable de entorno.")
        except json.JSONDecodeError as e:
            raise ValueError("El contenido de GOOGLE_CREDENTIALS_JSON_CALEND no es un JSON válido.") from e

def ensure_token_file():
    if not os.path.exists(TOKEN_PATH):
        token_content = os.getenv("GOOGLE_TOKEN_JSON")
        if not token_content:
            raise RuntimeError("No se encontró la variable de entorno GOOGLE_TOKEN_JSON.")
        try:
            parsed_token = json.loads(token_content)
            with open(TOKEN_PATH, 'w') as f:
                json.dump(parsed_token, f)
            logger.info(f"✅ Archivo temporal {TOKEN_PATH} creado desde variable de entorno.")
        except json.JSONDecodeError as e:
            raise ValueError("El contenido de GOOGLE_TOKEN_JSON no es un JSON válido.") from e

def get_calendar_service_():
    ensure_credentials_file()
    ensure_token_file()
    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    service = build('calendar', 'v3', credentials=creds)
    return service

# from google.auth.transport.requests import Request
from google.oauth2 import service_account
import google.auth

def get_calendar_service():
    ensure_credentials_file()
    ensure_token_file()

    # Cargar token desde archivo JSON
    with open(TOKEN_PATH, "r") as f:
        token_info = json.load(f)

    creds = Credentials.from_authorized_user_info(token_info, SCOPES)

    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    service = build("calendar", "v3", credentials=creds)
    return service

def obtener_eventos() -> List[EventoOut]:
    service = get_calendar_service()
    now = datetime.utcnow().isoformat() + 'Z'
    events_result = service.events().list(
        calendarId='primary', timeMin=now,
        maxResults=10, singleEvents=True,
        orderBy='startTime'
    ).execute()
    events = events_result.get('items', [])

    resultado = []
    for event in events:
        inicio = event['start'].get('dateTime')
        fin = event['end'].get('dateTime')
        titulo = event.get('summary', 'Sin título')
        descripcion = event.get('description', '')
        if inicio and fin:
            resultado.append(EventoOut(
                titulo=titulo,
                inicio=isoparse(inicio),
                fin=isoparse(fin),
                descripcion=descripcion
            ))
    return resultado

def sync_eventos():
    eventos = obtener_eventos()
    logger.info(f"🔄 Se encontraron {len(eventos)} eventos en Google Calendar")
    for evento in eventos:
        logger.info(f"📅 Evento: {evento.titulo} | 🕐 Inicio: {evento.inicio} | 🕓 Fin: {evento.fin} | 📝 Descripción: {evento.descripcion}")

@app.get("/api/eventos", response_model=List[EventoOut])
def listar_eventos():
    try:
        return obtener_eventos()
    except Exception as e:
        logger.error(f"❌ Error al obtener eventos: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sync")
def sincronizar():
    try:
        sync_eventos()
        return {"status": "ok", "mensaje": "Eventos sincronizados correctamente (logs disponibles)"}
    except Exception as e:
        logger.error(f"❌ Error al sincronizar eventos: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/debug/version")
def get_version():
    import google.auth
    return {"google-auth-version": google.auth.__version__}


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
def cargar_contactos_desde_excel():
    try:
        contactos = obtener_contactos_desde_hoja()
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