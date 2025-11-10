from datetime import datetime
import psycopg2
from dotenv import load_dotenv  # Solo si usas variables de entorno
import os
import re

from fastapi import FastAPI
from starlette.staticfiles import StaticFiles
from enviar_msg_wp import enviar_plantilla_generica, enviar_mensaje_texto_simple

from DataBase import guardar_o_actualizar_waba_db,actualizar_phone_info_db

# Cargar variables de entorno (incluye DATABASE_URL)
load_dotenv()

GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION")

INTERNAL_DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")

import requests
import os

import cloudinary
import cloudinary.uploader

# ✅ Crear carpeta persistente de audios si no existe
AUDIO_DIR = "audios"
os.makedirs(AUDIO_DIR, exist_ok=True)

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

def guardar_mensaje(telefono, texto, tipo="recibido", es_audio=False):
    try:
        # Si es un mensaje de audio, extrae solo el nombre del archivo
        if es_audio and texto.startswith("[Audio guardado:"):
            match = re.search(r"\[Audio guardado: (.+)\]", texto)
            if match:
                texto = match.group(1)  # Ej: "9998555913574750.ogg"

        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        # Buscar si ya existe el usuario
        cur.execute("SELECT id FROM creadores WHERE telefono = %s", (telefono,))
        usuario = cur.fetchone()

        # Insertar usuario si no existe
        if not usuario:
            cur.execute("INSERT INTO creadores (telefono) VALUES (%s) RETURNING id", (telefono,))
            usuario_id = cur.fetchone()[0]
        else:
            usuario_id = usuario[0]

        # Insertar mensaje
        cur.execute("""
            INSERT INTO mensajes (usuario_id, contenido, tipo, es_audio, fecha)
            VALUES (%s, %s, %s, %s, %s)
        """, (usuario_id, texto, tipo, es_audio, datetime.now()))

        conn.commit()
        cur.close()
        conn.close()

        print("✅ Mensaje y usuario guardados correctamente.")
    except Exception as e:
        print("❌ Error al guardar mensaje:", e)

# === Funciones MOCK ===

def enviar_recursos_exclusivos(numero: str):
    print(f"[MOCK] Enviando recursos exclusivos al número {numero}")
    return {"status": "ok", "accion": "recursos_exclusivos", "numero": numero}

def enviar_eventos(numero: str):
    print(f"[MOCK] Enviando información de eventos al número {numero}")
    return {"status": "ok", "accion": "eventos", "numero": numero}

def enviar_estadisticas(numero: str):
    print(f"[MOCK] Enviando estadísticas personalizadas al número {numero}")
    return {"status": "ok", "accion": "estadisticas", "numero": numero}

def solicitar_baja(numero: str):
    print(f"[MOCK] Procesando solicitud de baja para el número {numero}")
    return {"status": "ok", "accion": "solicitud_baja", "numero": numero}

def enviar_panel_control(numero: str):
    print(f"[MOCK] Enviando acceso al panel de control al número {numero}")
    return {"status": "ok", "accion": "panel_control", "numero": numero}

def enviar_perfiles(numero: str):
    print(f"[MOCK] Enviando lista de perfiles disponibles al número {numero}")
    return {"status": "ok", "accion": "perfiles", "numero": numero}

def gestionar_recursos(numero: str):
    print(f"[MOCK] Gestionando recursos para el número {numero}")
    return {"status": "ok", "accion": "gestionar_recursos", "numero": numero}

def enviar_info_general(numero: str):
    print(f"[MOCK] Enviando información general al número {numero}")
    return {"status": "ok", "accion": "info_general", "numero": numero}



# TOKEN Y WABA_ID
# -------------------------------------------------------------------
import logging

tokens_temporales = {"ultimo_token": None, "ultimo_waba_id": None}

def save_temp_access_token(token: str):
    tokens_temporales["ultimo_token"] = token
    print("💾 Token temporal guardado correctamente.")

def get_temp_access_token():
    return tokens_temporales.get("ultimo_token")

def clear_temp_access_token():
    tokens_temporales["ultimo_token"] = None
    print("🧹 Token temporal limpiado.")

def clear_temp_waba_id():
    tokens_temporales.pop("ultimo_waba_id", None)
    print("🧹 WABA temporal limpiado.")

def save_temp_waba_id(waba_id: str):
    tokens_temporales["ultimo_waba_id"] = waba_id
    print("💾 WABA temporal guardado correctamente.")

import json

def obtener_phone_number_info(waba_id: str, access_token: str):
    """Obtiene el número de teléfono asociado a un WABA desde la API de Meta."""
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{waba_id}/phone_numbers"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        print("📞 Respuesta Meta phone_numbers:", json.dumps(data, indent=2))

        phones = data.get("data", [])
        if phones:
            phone = phones[0]
            return {
                "id": phone.get("id"),
                "display_phone_number": phone.get("display_phone_number"),
            }

    except requests.RequestException as e:
        print(f"❌ Error HTTP al obtener phone_number_info: {e}")
    except Exception as e:
        print(f"❌ Error general obteniendo phone_number_info: {e}")

    return None



# --- Función principal ajustada ---
def procesar_evento_partner_instalado(entry, change, value, event):
    """Procesa el evento PARTNER_APP_INSTALLED emitido por Meta."""
    allowed_events = ("PARTNER_APP_INSTALLED", "PARTNER_ADDED")
    if event not in allowed_events:
        return {"status": "ignored", "reason": "no_partner_event"}

    try:
        waba_info = value.get("waba_info", {})
        waba_id = waba_info.get("waba_id")

        if not waba_id:
            return {"status": "error", "reason": "missing_waba_id"}

        print(f"🧩 WABA instalado detectado: {waba_id}")

        session_id = "abc123"
        resultado_waba_id = guardar_o_actualizar_waba_db(session_id, waba_id)

        # ✅ Si existe WABA y TOKEN, completar vínculo y actualizar phone info
        if resultado_waba_id.get("status") == "completado":
            actualizado = actualizar_info_phone(resultado_waba_id)
            print(f"📞 Actualización phone info → {actualizado}")

        return {"status": "ok", "waba_id": waba_id}

    except Exception as e:
        print("❌ Error procesando evento PARTNER_APP_INSTALLED:", e)
        return {"status": "exception", "error": str(e)}



def actualizar_info_phone(resultado_token: dict) -> bool:
    """Actualiza en la base de datos la información del número asociado al WABA."""
    try:
        waba_id = resultado_token.get("waba_id")
        access_token = resultado_token.get("access_token")
        registro_id = resultado_token.get("id")

        if not waba_id or not registro_id:
            print("⚠️ No se encontró waba_id o id para actualizar phone info.")
            return False

        phone_info = obtener_phone_number_info(waba_id, access_token)
        if not phone_info:
            print(f"⚠️ No se pudo obtener información del número para WABA {waba_id}")
            return False

        actualizado = actualizar_phone_info_db(
            id=registro_id,
            phone_number=phone_info.get("display_phone_number"),
            phone_number_id=phone_info.get("id"),
            status="connected"
        )

        if actualizado:
            print(f"✅ Phone info actualizada correctamente para WABA {waba_id}")
        else:
            print(f"⚠️ No se pudo actualizar la info de phone_number en DB (ID: {registro_id})")

        return actualizado

    except Exception as e:
        print(f"❌ Error en actualizar_info_phone: {e}")
        return False