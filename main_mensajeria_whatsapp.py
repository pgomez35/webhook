import datetime
import os
import subprocess
from typing import Optional

from fastapi import APIRouter, Form, UploadFile, requests
from starlette.staticfiles import StaticFiles

from DataBase import obtener_usuario_id_por_telefono, paso_limite_24h, guardar_mensaje, guardar_mensaje_nuevo, \
    obtener_mensajes, obtener_contactos_db, obtener_contactos_db_nueva
from enviar_msg_wp import enviar_plantilla_generica, enviar_mensaje_texto_simple, enviar_audio_base64
from tenant import current_token, current_phone_id, current_business_name, current_tenant
from fastapi.responses import JSONResponse, PlainTextResponse

import requests

from utils import AUDIO_DIR, subir_audio_cloudinary
import os

import cloudinary

cloudinary.config(
    cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
    api_key=os.environ["CLOUDINARY_API_KEY"],
    api_secret=os.environ["CLOUDINARY_API_SECRET"],
    secure=True
)

router = APIRouter()

@router.get("/contactos")
def listar_contactos(estado: Optional[int] = None, request: Request = None):
    from tenant import current_tenant
    tenant_actual = current_tenant.get()
    print(f"🔍 [DEBUG /contactos] Tenant actual: {tenant_actual}")
    if request:
        print(f"🔍 [DEBUG /contactos] Request state tenant_name: {getattr(request.state, 'tenant_name', 'N/A')}")
        print(f"🔍 [DEBUG /contactos] Request state agencia: {getattr(request.state, 'agencia', 'N/A')}")
        print(f"🔍 [DEBUG /contactos] Request host: {request.headers.get('host', 'N/A')}")
        print(f"🔍 [DEBUG /contactos] Request X-Tenant-Name: {request.headers.get('x-tenant-name', 'N/A')}")
    return obtener_contactos_db_nueva(estado)

@router.get("/mensajes/{telefono}")
def listar_mensajes(telefono: str):
    return obtener_mensajes(telefono)

@router.post("/mensajes")
async def api_enviar_mensaje(request: Request, data: dict):

    telefono = data.get("telefono")
    mensaje = data.get("mensaje")
    nombre = data.get("nombre", "").strip()

    if not telefono or not mensaje:
        return JSONResponse({"error": "Faltan datos"}, status_code=400)

    # ✅ Credenciales multitenant
    TOKEN = current_token.get()
    PHONE_NUMBER_ID = current_phone_id.get()
    AGENCIA_NOMBRE = current_business_name.get()

    if not TOKEN or not PHONE_NUMBER_ID:
        return JSONResponse(
            {"error": "Credenciales de WhatsApp no configuradas para este tenant"},
            status_code=500
        )

    usuario_id = obtener_usuario_id_por_telefono(telefono)

    # ======================================================
    # FUERA DE VENTANA 24H → PLANTILLA
    # ======================================================

    if usuario_id and paso_limite_24h(usuario_id):

        print("⏱️ Usuario fuera de 24h. Enviando plantilla reconexion_general_corta")

        plantilla = "reconexion_general_corta"

        parametros = [
            nombre if nombre else "Hola",
            AGENCIA_NOMBRE or "Nuestro equipo"
        ]

        codigo, respuesta_api = enviar_plantilla_generica(
            token=TOKEN,
            phone_number_id=PHONE_NUMBER_ID,
            numero_destino=telefono,
            nombre_plantilla=plantilla,
            codigo_idioma="es_CO",
            parametros=parametros
        )

        # ✅ EXTRAER message_id_meta
        message_id_meta = None
        if respuesta_api and "messages" in respuesta_api:
            message_id_meta = respuesta_api["messages"][0].get("id")

        guardar_mensaje_nuevo(
            telefono=telefono,
            contenido="Plantilla de reconexión enviada",
            direccion="enviado",
            tipo="texto",
            message_id_meta=message_id_meta,
            estado="sent"
        )

        return {
            "status": "plantilla_auto",
            "mensaje": "Se envió plantilla por estar fuera de ventana de 24h.",
            "codigo_api": codigo,
            "respuesta_api": respuesta_api
        }

    # ======================================================
    # DENTRO DE VENTANA → MENSAJE NORMAL
    # ======================================================

    codigo, respuesta_api = enviar_mensaje_texto_simple(
        token=TOKEN,
        numero_id=PHONE_NUMBER_ID,
        telefono_destino=telefono,
        texto=mensaje
    )

    # ✅ EXTRAER message_id_meta
    message_id_meta = None
    if respuesta_api and "messages" in respuesta_api:
        message_id_meta = respuesta_api["messages"][0].get("id")

    guardar_mensaje_nuevo(
        telefono=telefono,
        contenido=mensaje,
        direccion="enviado",
        tipo="texto",
        message_id_meta=message_id_meta,
        estado="sent"
    )

    return {
        "status": "ok",
        "mensaje": "Mensaje enviado correctamente",
        "codigo_api": codigo,
        "respuesta_api": respuesta_api
    }

from datetime import datetime


@router.post("/mensajes/audio")
async def api_enviar_audio(
    telefono: str = Form(...),
    audio: UploadFile = Form(...)
):
    TOKEN = current_token.get()
    PHONE_NUMBER_ID = current_phone_id.get()

    if not TOKEN or not PHONE_NUMBER_ID:
        return {"status": "error", "mensaje": "Credenciales no disponibles"}

    timestamp = int(datetime.now().timestamp())
    filename_webm = f"{telefono}_{timestamp}.webm"
    filename_ogg = f"{telefono}_{timestamp}.ogg"

    ruta_webm = os.path.join(AUDIO_DIR, filename_webm)
    ruta_ogg = os.path.join(AUDIO_DIR, filename_ogg)

    os.makedirs(AUDIO_DIR, exist_ok=True)

    # Guardar archivo original
    audio_bytes = await audio.read()
    with open(ruta_webm, "wb") as f:
        f.write(audio_bytes)

    # Convertir a opus
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", ruta_webm, "-acodec", "libopus", ruta_ogg],
            check=True
        )
    except subprocess.CalledProcessError:
        return {"status": "error", "mensaje": "Error convirtiendo audio"}

    # Subir a Cloudinary
    url_cloudinary = subir_audio_cloudinary(
        ruta_ogg,
        public_id=filename_ogg.replace(".ogg", "")
    )

    if not url_cloudinary:
        return {"status": "error", "mensaje": "Error subiendo a Cloudinary"}

    # 🔥 Enviar primero a WhatsApp
    try:
        codigo, respuesta_api = enviar_audio_base64(
            token=TOKEN,
            numero_id=PHONE_NUMBER_ID,
            telefono_destino=telefono,
            ruta_audio=ruta_ogg,
            mimetype="audio/ogg; codecs=opus"
        )
    except Exception as e:
        return {
            "status": "error",
            "mensaje": "Error enviando a WhatsApp",
            "error": str(e)
        }

    # 🔥 Guardar SOLO si envío fue exitoso
    if codigo == 200:
        message_id_meta = respuesta_api.get("messages", [{}])[0].get("id")
        estado_mensaje = "sent"

    guardar_mensaje_nuevo(
        telefono=telefono,
        contenido=url_cloudinary,
        direccion="enviado",
        tipo="audio",
        media_url=url_cloudinary,
        message_id_meta=respuesta_api.get("messages", [{}])[0].get("id"),
        estado="sent"
    )

    return {
        "status": "ok",
        "url_cloudinary": url_cloudinary,
        "codigo_api": codigo
    }

@router.post("/mensajes/imagen")
async def api_enviar_imagen(
    telefono: str = Form(...),
    imagen: UploadFile = Form(...)
):
    import os
    from datetime import datetime
    from fastapi import HTTPException

    TOKEN = current_token.get()
    PHONE_NUMBER_ID = current_phone_id.get()
    TENANT = current_tenant.get()

    if not TOKEN or not PHONE_NUMBER_ID:
        return {"status": "error", "mensaje": "Credenciales no disponibles"}

    # --------------------------------------------------
    # 1️⃣ Validar tipo
    # --------------------------------------------------
    if imagen.content_type not in ["image/jpeg", "image/png", "image/jpg"]:
        raise HTTPException(status_code=400, detail="Tipo de imagen no permitido")

    # --------------------------------------------------
    # 2️⃣ Guardar temporalmente
    # --------------------------------------------------
    timestamp = int(datetime.now().timestamp())
    filename = f"{telefono}_{timestamp}_{imagen.filename}"

    MEDIA_DIR = "temp_images"
    os.makedirs(MEDIA_DIR, exist_ok=True)

    ruta_imagen = os.path.join(MEDIA_DIR, filename)

    with open(ruta_imagen, "wb") as f:
        f.write(await imagen.read())

    # --------------------------------------------------
    # 3️⃣ Subir a Cloudinary como IMAGE
    # --------------------------------------------------
    try:
        result = cloudinary.uploader.upload(
            ruta_imagen,
            folder=f"whatsapp/{TENANT}/images",
            resource_type="image"
        )

        url_cloudinary = result.get("secure_url")

    except Exception as e:
        return {
            "status": "error",
            "mensaje": "Error subiendo imagen a Cloudinary",
            "error": str(e)
        }

    # --------------------------------------------------
    # 4️⃣ Enviar a WhatsApp
    # --------------------------------------------------
    try:
        codigo, respuesta_api = enviar_imagen_link(
            token=TOKEN,
            numero_id=PHONE_NUMBER_ID,
            telefono_destino=telefono,
            url_imagen=url_cloudinary
        )
    except Exception as e:
        return {
            "status": "error",
            "mensaje": "Error enviando a WhatsApp",
            "error": str(e)
        }

    # --------------------------------------------------
    # 5️⃣ Guardar SOLO si fue exitoso
    # --------------------------------------------------
    if codigo == 200:
        message_id_meta = respuesta_api.get("messages", [{}])[0].get("id")

        guardar_mensaje_nuevo(
            telefono=telefono,
            contenido=url_cloudinary,
            direccion="enviado",
            tipo="image",
            media_url=url_cloudinary,
            message_id_meta=message_id_meta,
            estado="sent"
        )

    # --------------------------------------------------
    # 6️⃣ Borrar temporal
    # --------------------------------------------------
    try:
        os.remove(ruta_imagen)
    except:
        pass

    return {
        "status": "ok",
        "url_cloudinary": url_cloudinary,
        "codigo_api": codigo
    }

def enviar_imagen_link(
    token,
    numero_id,
    telefono_destino,
    url_imagen
):
    url = f"https://graph.facebook.com/v19.0/{numero_id}/messages"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    data = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "image",
        "image": {
            "link": url_imagen
        }
    }

    response = requests.post(url, headers=headers, json=data)

    return response.status_code, response.json()


@router.post("/mensajes/audioV16022026")
async def api_enviar_audioV6022026(
    telefono: str = Form(...),
    audio: UploadFile = Form(...)
):
    # ✅ Obtener credenciales dinámicas (multitenant real)
    TOKEN = current_token.get()
    PHONE_NUMBER_ID = current_phone_id.get()

    # Validación básica
    if not TOKEN or not PHONE_NUMBER_ID:
        return {
            "status": "error",
            "mensaje": "Credenciales no disponibles para este tenant"
        }

    # Generar nombres de archivo
    filename_webm = f"{telefono}_{int(datetime.now().timestamp())}.webm"
    filename_ogg = filename_webm.replace(".webm", ".ogg")

    ruta_webm = os.path.join(AUDIO_DIR, filename_webm)
    ruta_ogg = os.path.join(AUDIO_DIR, filename_ogg)

    # Asegurar carpeta (aunque ya se crea en utils)
    os.makedirs(AUDIO_DIR, exist_ok=True)

    # Guardar audio original
    audio_bytes = await audio.read()
    with open(ruta_webm, "wb") as f:
        f.write(audio_bytes)

    print(f"✅ Audio guardado correctamente en: {ruta_webm}")

    # Convertir a OGG (WhatsApp requiere opus)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", ruta_webm, "-acodec", "libopus", ruta_ogg],
            check=True
        )
        print(f"✅ Audio convertido a .ogg: {ruta_ogg}")

    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "mensaje": "Error al convertir el audio a .ogg",
            "error": str(e)
        }

    # Subir a Cloudinary
    try:
        url_cloudinary = subir_audio_cloudinary(
            ruta_ogg,
            public_id=filename_ogg.replace(".ogg", "")
        )
    except Exception as e:
        return {
            "status": "error",
            "mensaje": "Error subiendo audio a Cloudinary",
            "error": str(e)
        }

    # Guardar en base de datos
    guardar_mensaje(
        telefono=telefono,
        contenido=url_cloudinary,
        tipo="enviado",
        es_audio=True
    )

    # Enviar por WhatsApp
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

