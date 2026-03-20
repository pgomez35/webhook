from datetime import datetime
import os
import subprocess
import traceback
from typing import Optional, Literal

import httpx
import tempfile

from fastapi import APIRouter, Form, UploadFile, requests, HTTPException, Request, Depends
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, AnyUrl, Field
from starlette.staticfiles import StaticFiles

from DataBase import obtener_usuario_id_por_telefono, paso_limite_24h, guardar_mensaje, guardar_mensaje_nuevo, \
    obtener_mensajes, obtener_contactos_db, obtener_contactos_db_nueva, get_connection_context, \
    obtener_cuenta_por_subdominio
from enviar_msg_wp import enviar_plantilla_generica, enviar_mensaje_texto_simple, enviar_audio_base64, \
    enviar_plantilla_generica_parametros
from main_auth import obtener_usuario_actual
from tenant import current_token, current_phone_id, current_business_name, current_tenant
from fastapi.responses import JSONResponse, PlainTextResponse

from typing import Optional, Dict, Any, Tuple

import requests

from utils import AUDIO_DIR, subir_audio_cloudinary
from starlette.responses import StreamingResponse

import cloudinary

from utils_aspirantes import obtener_status_24hrs, intentar_plantilla_reconexion_24h

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

    # ======================================================
    # 1️⃣ Enviar SIEMPRE mensaje normal
    # ======================================================

    codigo, respuesta_api = enviar_mensaje_texto_simple(
        token=TOKEN,
        numero_id=PHONE_NUMBER_ID,
        telefono_destino=telefono,
        texto=mensaje
    )

    # ======================================================
    # 2️⃣ Guardar SIEMPRE
    # ======================================================

    message_id_meta = None
    if respuesta_api and "messages" in respuesta_api:
        message_id_meta = respuesta_api["messages"][0].get("id")

    guardar_mensaje_nuevo(
        telefono=telefono,
        contenido=mensaje,
        direccion="enviado",
        tipo="text",
        message_id_meta=message_id_meta,
        estado="sent"
    )

    # ======================================================
    # 3️⃣ Intentar plantilla SOLO si fue exitoso
    # ======================================================

    intentar_plantilla_reconexion_24h(
        telefono=telefono,
        nombre=nombre,
        token=TOKEN,
        phone_number_id=PHONE_NUMBER_ID,
        agencia_nombre=AGENCIA_NOMBRE
    )

    # ======================================================
    # 4️⃣ Respuesta final
    # ======================================================

    return {
        "status": "ok" if codigo == 200 else "error",
        "mensaje": "Mensaje procesado",
        "codigo_api": codigo,
        "respuesta_api": respuesta_api if codigo != 200 else None
    }

@router.post("/mensajes/audio")
async def api_enviar_audio(
    telefono: str = Form(...),
    nombre: str = Form(""),
    audio: UploadFile = Form(...)
):
    import os, subprocess
    from datetime import datetime

    TOKEN = current_token.get()
    PHONE_NUMBER_ID = current_phone_id.get()
    TENANT = current_tenant.get()
    AGENCIA_NOMBRE = current_business_name.get() or ""

    if not TOKEN or not PHONE_NUMBER_ID:
        return {"status": "error", "mensaje": "Credenciales no disponibles"}

    if not TENANT:
        return {"status": "error", "mensaje": "Tenant no disponible"}

    timestamp = int(datetime.now().timestamp())
    filename_webm = f"{telefono}_{timestamp}.webm"
    filename_ogg = f"{telefono}_{timestamp}.ogg"

    tenant_dir = os.path.join(AUDIO_DIR, TENANT)
    os.makedirs(tenant_dir, exist_ok=True)

    ruta_webm = os.path.join(tenant_dir, filename_webm)
    ruta_ogg = os.path.join(tenant_dir, filename_ogg)

    # --------------------------------------------------
    # 1️⃣ Guardar archivo original
    # --------------------------------------------------
    audio_bytes = await audio.read()
    with open(ruta_webm, "wb") as f:
        f.write(audio_bytes)

    # --------------------------------------------------
    # 2️⃣ Convertir a opus
    # --------------------------------------------------
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", ruta_webm, "-acodec", "libopus", ruta_ogg],
            check=True
        )
    except subprocess.CalledProcessError:
        try: os.remove(ruta_webm)
        except: pass
        return {"status": "error", "mensaje": "Error convirtiendo audio"}

    # --------------------------------------------------
    # 3️⃣ Subir a Cloudinary
    # --------------------------------------------------
    url_cloudinary = subir_audio_cloudinary(
        ruta_ogg,
        public_id=filename_ogg.replace(".ogg", ""),
        carpeta=f"whatsapp/{TENANT}/audios"
    )

    if not url_cloudinary:
        try: os.remove(ruta_webm)
        except: pass
        try: os.remove(ruta_ogg)
        except: pass
        return {"status": "error", "mensaje": "Error subiendo a Cloudinary"}

    # --------------------------------------------------
    # 4️⃣ Enviar SIEMPRE a WhatsApp
    # --------------------------------------------------
    try:
        codigo, respuesta_api = enviar_audio_base64(
            token=TOKEN,
            numero_id=PHONE_NUMBER_ID,
            telefono_destino=telefono,
            ruta_audio=ruta_ogg,
            mimetype="audio/ogg; codecs=opus"
        )
    except Exception as e:
        codigo = 500
        respuesta_api = {"error": str(e)}

    # --------------------------------------------------
    # 5️⃣ Guardar SOLO si fue exitoso
    # --------------------------------------------------
    if codigo == 200:

        message_id_meta = None
        if respuesta_api and "messages" in respuesta_api:
            message_id_meta = respuesta_api["messages"][0].get("id")

        guardar_mensaje_nuevo(
            telefono=telefono,
            contenido=url_cloudinary,
            direccion="enviado",
            tipo="audio",
            media_url=url_cloudinary,
            message_id_meta=message_id_meta,
            estado="sent"
        )

        # --------------------------------------------------
        # 6️⃣ Intentar plantilla SOLO si fue exitoso
        # --------------------------------------------------
        intentar_plantilla_reconexion_24h(
            telefono=telefono,
            nombre=nombre,
            token=TOKEN,
            phone_number_id=PHONE_NUMBER_ID,
            agencia_nombre=AGENCIA_NOMBRE
        )

    # --------------------------------------------------
    # 7️⃣ Limpiar temporales
    # --------------------------------------------------
    try: os.remove(ruta_webm)
    except: pass
    try: os.remove(ruta_ogg)
    except: pass

    return {
        "status": "ok" if codigo == 200 else "error",
        "url_cloudinary": url_cloudinary,
        "codigo_api": codigo,
        "respuesta_api": respuesta_api if codigo != 200 else None
    }


@router.post("/mensajes/audio0")
async def api_enviar_audio0(
    telefono: str = Form(...),
    nombre: str = Form(""),   # ✅ NUEVO PARAMETRO
    audio: UploadFile = Form(...)
):
    import os, subprocess
    from datetime import datetime

    TOKEN = current_token.get()
    PHONE_NUMBER_ID = current_phone_id.get()
    TENANT = current_tenant.get()

    if not TOKEN or not PHONE_NUMBER_ID:
        return {"status": "error", "mensaje": "Credenciales no disponibles"}

    if not TENANT:
        return {"status": "error", "mensaje": "Tenant no disponible"}

    enviada, payload = intentar_plantilla_reconexion_24h(
        telefono=telefono,
        nombre=nombre,  # si no tienes, manda ""
        token=TOKEN,
        phone_number_id=PHONE_NUMBER_ID,
        agencia_nombre=current_business_name.get() or ""
    )
    if enviada:
        return payload


    timestamp = int(datetime.now().timestamp())
    filename_webm = f"{telefono}_{timestamp}.webm"
    filename_ogg = f"{telefono}_{timestamp}.ogg"

    # ✅ opcional: separar temporales por tenant
    tenant_dir = os.path.join(AUDIO_DIR, TENANT)
    os.makedirs(tenant_dir, exist_ok=True)

    ruta_webm = os.path.join(tenant_dir, filename_webm)
    ruta_ogg = os.path.join(tenant_dir, filename_ogg)

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
        try: os.remove(ruta_webm)
        except: pass
        return {"status": "error", "mensaje": "Error convirtiendo audio"}

    # ✅ Subir a Cloudinary usando tenant en carpeta
    url_cloudinary = subir_audio_cloudinary(
        ruta_ogg,
        public_id=filename_ogg.replace(".ogg", ""),
        carpeta=f"whatsapp/{TENANT}/audios"
    )

    if not url_cloudinary:
        try: os.remove(ruta_webm)
        except: pass
        try: os.remove(ruta_ogg)
        except: pass
        return {"status": "error", "mensaje": "Error subiendo a Cloudinary"}

    # Enviar a WhatsApp
    try:
        codigo, respuesta_api = enviar_audio_base64(
            token=TOKEN,
            numero_id=PHONE_NUMBER_ID,
            telefono_destino=telefono,
            ruta_audio=ruta_ogg,
            mimetype="audio/ogg; codecs=opus"
        )
    except Exception as e:
        codigo = 500
        respuesta_api = {"error": str(e)}

    # ✅ Guardar SOLO si fue exitoso (como tu endpoint de imagen)
    if codigo == 200:
        message_id_meta = respuesta_api.get("messages", [{}])[0].get("id")

        guardar_mensaje_nuevo(
            telefono=telefono,
            contenido=url_cloudinary,
            direccion="enviado",
            tipo="audio",
            media_url=url_cloudinary,
            message_id_meta=message_id_meta,
            estado="sent"
        )

    # limpiar temporales
    try: os.remove(ruta_webm)
    except: pass
    try: os.remove(ruta_ogg)
    except: pass

    return {
        "status": "ok" if codigo == 200 else "error",
        "url_cloudinary": url_cloudinary,
        "codigo_api": codigo,
        "respuesta_api": respuesta_api if codigo != 200 else None
    }

@router.post("/mensajes/audio-adjunto")
async def api_enviar_audio_adjunto(
    telefono: str = Form(...),
    nombre: str = Form(""),
    audio: UploadFile = Form(...)
):
    import os
    from datetime import datetime
    from fastapi import HTTPException

    TOKEN = current_token.get()
    PHONE_NUMBER_ID = current_phone_id.get()
    TENANT = current_tenant.get()
    AGENCIA_NOMBRE = current_business_name.get() or ""

    if not TOKEN or not PHONE_NUMBER_ID:
        return {"status": "error", "mensaje": "Credenciales no disponibles"}

    # --------------------------------------------------
    # 1️⃣ Validar tipo
    # --------------------------------------------------
    if not audio.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="Tipo de audio no permitido")

    # --------------------------------------------------
    # 2️⃣ Guardar temporalmente
    # --------------------------------------------------
    timestamp = int(datetime.now().timestamp())
    filename = f"{telefono}_{timestamp}_{audio.filename}"

    AUDIO_DIR = "temp_audios"
    os.makedirs(AUDIO_DIR, exist_ok=True)

    ruta_audio = os.path.join(AUDIO_DIR, filename)

    with open(ruta_audio, "wb") as f:
        f.write(await audio.read())

    # --------------------------------------------------
    # 3️⃣ Subir a Cloudinary
    # --------------------------------------------------
    try:
        url_cloudinary = subir_audio_cloudinary(
            ruta_audio,
            public_id=filename.replace(".ogg", "").replace(".mp3", ""),
            carpeta=f"whatsapp/{TENANT}/audios"
        )
    except Exception as e:
        try:
            os.remove(ruta_audio)
        except:
            pass

        return {
            "status": "error",
            "mensaje": "Error subiendo audio a Cloudinary",
            "error": str(e)
        }

    # --------------------------------------------------
    # 4️⃣ Enviar SIEMPRE a WhatsApp
    # --------------------------------------------------
    try:
        codigo, respuesta_api = enviar_audio_link(
            token=TOKEN,
            numero_id=PHONE_NUMBER_ID,
            telefono_destino=telefono,
            url_audio=url_cloudinary
        )
    except Exception as e:
        codigo = 500
        respuesta_api = {"error": str(e)}

    # --------------------------------------------------
    # 5️⃣ Guardar SOLO si fue exitoso
    # --------------------------------------------------
    if codigo == 200:

        message_id_meta = None
        if respuesta_api and "messages" in respuesta_api:
            message_id_meta = respuesta_api["messages"][0].get("id")

        guardar_mensaje_nuevo(
            telefono=telefono,
            contenido=url_cloudinary,
            direccion="enviado",
            tipo="audio",
            media_url=url_cloudinary,
            message_id_meta=message_id_meta,
            estado="sent"
        )

        # --------------------------------------------------
        # 6️⃣ Intentar plantilla SOLO si fue exitoso
        # --------------------------------------------------
        intentar_plantilla_reconexion_24h(
            telefono=telefono,
            nombre=nombre,
            token=TOKEN,
            phone_number_id=PHONE_NUMBER_ID,
            agencia_nombre=AGENCIA_NOMBRE
        )

    # --------------------------------------------------
    # 7️⃣ Borrar temporal
    # --------------------------------------------------
    try:
        os.remove(ruta_audio)
    except:
        pass

    return {
        "status": "ok" if codigo == 200 else "error",
        "url_cloudinary": url_cloudinary,
        "codigo_api": codigo,
        "respuesta_api": respuesta_api if codigo != 200 else None
    }


@router.post("/mensajes/audio-adjunto0")
async def api_enviar_audio_adjunto0(
    telefono: str = Form(...),
    nombre: str = Form(""),   # ✅ NUEVO PARAMETRO
    audio: UploadFile = Form(...)
):
    import os
    from datetime import datetime
    from fastapi import HTTPException

    TOKEN = current_token.get()
    PHONE_NUMBER_ID = current_phone_id.get()
    TENANT = current_tenant.get()

    if not TOKEN or not PHONE_NUMBER_ID:
        return {"status": "error", "mensaje": "Credenciales no disponibles"}

    enviada, payload = intentar_plantilla_reconexion_24h(
        telefono=telefono,
        nombre=nombre,  # si no tienes, manda ""
        token=TOKEN,
        phone_number_id=PHONE_NUMBER_ID,
        agencia_nombre=current_business_name.get() or ""
    )
    if enviada:
        return payload

    # --------------------------------------------------
    # 1️⃣ Validar tipo
    # --------------------------------------------------
    if not audio.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="Tipo de audio no permitido")

    # --------------------------------------------------
    # 2️⃣ Guardar temporalmente (MISMO PATRÓN QUE IMAGEN)
    # --------------------------------------------------
    timestamp = int(datetime.now().timestamp())
    filename = f"{telefono}_{timestamp}_{audio.filename}"

    AUDIO_DIR = "temp_audios"
    os.makedirs(AUDIO_DIR, exist_ok=True)

    ruta_audio = os.path.join(AUDIO_DIR, filename)

    with open(ruta_audio, "wb") as f:
        f.write(await audio.read())

    # --------------------------------------------------
    # 3️⃣ Subir a Cloudinary usando tenant
    # --------------------------------------------------
    try:
        url_cloudinary = subir_audio_cloudinary(
            ruta_audio,
            public_id=filename.replace(".ogg", "").replace(".mp3", ""),
            carpeta=f"whatsapp/{TENANT}/audios"
        )

    except Exception as e:
        return {
            "status": "error",
            "mensaje": "Error subiendo audio a Cloudinary",
            "error": str(e)
        }

    # --------------------------------------------------
    # 4️⃣ Enviar a WhatsApp por LINK (adjunto real)
    # --------------------------------------------------
    try:
        codigo, respuesta_api = enviar_audio_link(
            token=TOKEN,
            numero_id=PHONE_NUMBER_ID,
            telefono_destino=telefono,
            url_audio=url_cloudinary
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
            tipo="audio",
            media_url=url_cloudinary,
            message_id_meta=message_id_meta,
            estado="sent"
        )

    # --------------------------------------------------
    # 6️⃣ Borrar temporal
    # --------------------------------------------------
    try:
        os.remove(ruta_audio)
    except:
        pass

    return {
        "status": "ok",
        "url_cloudinary": url_cloudinary,
        "codigo_api": codigo
    }


def enviar_audio_link(token, numero_id, telefono_destino, url_audio):
    import requests

    url = f"https://graph.facebook.com/v19.0/{numero_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    data = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "audio",
        "audio": {
            "link": url_audio
        }
    }

    response = requests.post(url, headers=headers, json=data)
    return response.status_code, response.json()



# @router.post("/mensajes/audio")
# async def api_enviar_audio(
#     telefono: str = Form(...),
#     audio: UploadFile = Form(...)
# ):
#     TOKEN = current_token.get()
#     PHONE_NUMBER_ID = current_phone_id.get()
#
#     if not TOKEN or not PHONE_NUMBER_ID:
#         return {"status": "error", "mensaje": "Credenciales no disponibles"}
#
#     timestamp = int(datetime.now().timestamp())
#     filename_webm = f"{telefono}_{timestamp}.webm"
#     filename_ogg = f"{telefono}_{timestamp}.ogg"
#
#     ruta_webm = os.path.join(AUDIO_DIR, filename_webm)
#     ruta_ogg = os.path.join(AUDIO_DIR, filename_ogg)
#
#     os.makedirs(AUDIO_DIR, exist_ok=True)
#
#     # Guardar archivo original
#     audio_bytes = await audio.read()
#     with open(ruta_webm, "wb") as f:
#         f.write(audio_bytes)
#
#     # Convertir a opus
#     try:
#         subprocess.run(
#             ["ffmpeg", "-y", "-i", ruta_webm, "-acodec", "libopus", ruta_ogg],
#             check=True
#         )
#     except subprocess.CalledProcessError:
#         return {"status": "error", "mensaje": "Error convirtiendo audio"}
#
#     # Subir a Cloudinary
#     url_cloudinary = subir_audio_cloudinary(
#         ruta_ogg,
#         public_id=filename_ogg.replace(".ogg", "")
#     )
#
#     if not url_cloudinary:
#         return {"status": "error", "mensaje": "Error subiendo a Cloudinary"}
#
#     # 🔥 Enviar primero a WhatsApp
#     try:
#         codigo, respuesta_api = enviar_audio_base64(
#             token=TOKEN,
#             numero_id=PHONE_NUMBER_ID,
#             telefono_destino=telefono,
#             ruta_audio=ruta_ogg,
#             mimetype="audio/ogg; codecs=opus"
#         )
#     except Exception as e:
#         return {
#             "status": "error",
#             "mensaje": "Error enviando a WhatsApp",
#             "error": str(e)
#         }
#
#     # 🔥 Guardar SOLO si envío fue exitoso
#     if codigo == 200:
#         message_id_meta = respuesta_api.get("messages", [{}])[0].get("id")
#         estado_mensaje = "sent"
#
#     guardar_mensaje_nuevo(
#         telefono=telefono,
#         contenido=url_cloudinary,
#         direccion="enviado",
#         tipo="audio",
#         media_url=url_cloudinary,
#         message_id_meta=respuesta_api.get("messages", [{}])[0].get("id"),
#         estado="sent"
#     )
#
#     return {
#         "status": "ok",
#         "url_cloudinary": url_cloudinary,
#         "codigo_api": codigo
#     }

@router.post("/mensajes/imagen")
async def api_enviar_imagen(
    telefono: str = Form(...),
    nombre: str = Form(""),
    imagen: UploadFile = Form(...)
):
    import os
    from datetime import datetime
    from fastapi import HTTPException

    TOKEN = current_token.get()
    PHONE_NUMBER_ID = current_phone_id.get()
    TENANT = current_tenant.get()
    AGENCIA_NOMBRE = current_business_name.get() or ""

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
    # 3️⃣ Subir a Cloudinary
    # --------------------------------------------------
    try:
        result = cloudinary.uploader.upload(
            ruta_imagen,
            folder=f"whatsapp/{TENANT}/images",
            resource_type="image"
        )
        url_cloudinary = result.get("secure_url")

    except Exception as e:
        try:
            os.remove(ruta_imagen)
        except:
            pass

        return {
            "status": "error",
            "mensaje": "Error subiendo imagen a Cloudinary",
            "error": str(e)
        }

    # --------------------------------------------------
    # 4️⃣ Enviar SIEMPRE a WhatsApp
    # --------------------------------------------------
    try:
        codigo, respuesta_api = enviar_imagen_link(
            token=TOKEN,
            numero_id=PHONE_NUMBER_ID,
            telefono_destino=telefono,
            url_imagen=url_cloudinary
        )
    except Exception as e:
        codigo = 500
        respuesta_api = {"error": str(e)}

    # --------------------------------------------------
    # 5️⃣ Guardar SOLO si fue exitoso
    # --------------------------------------------------
    if codigo == 200:

        message_id_meta = None
        if respuesta_api and "messages" in respuesta_api:
            message_id_meta = respuesta_api["messages"][0].get("id")

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
        # 6️⃣ Intentar plantilla SOLO si fue exitoso
        # --------------------------------------------------
        intentar_plantilla_reconexion_24h(
            telefono=telefono,
            nombre=nombre,
            token=TOKEN,
            phone_number_id=PHONE_NUMBER_ID,
            agencia_nombre=AGENCIA_NOMBRE
        )

    # --------------------------------------------------
    # 7️⃣ Borrar temporal
    # --------------------------------------------------
    try:
        os.remove(ruta_imagen)
    except:
        pass

    return {
        "status": "ok" if codigo == 200 else "error",
        "url_cloudinary": url_cloudinary,
        "codigo_api": codigo,
        "respuesta_api": respuesta_api if codigo != 200 else None
    }


@router.post("/mensajes/imagen0")
async def api_enviar_imagen0(
    telefono: str = Form(...),
    nombre: str = Form(""),   # ✅ NUEVO PARAMETRO
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

    enviada, payload = intentar_plantilla_reconexion_24h(
        telefono=telefono,
        nombre=nombre,  # si no tienes, manda ""
        token=TOKEN,
        phone_number_id=PHONE_NUMBER_ID,
        agencia_nombre=current_business_name.get() or ""
    )
    if enviada:
        return payload

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


# --------------------------------------------------
# 🔹 Subir archivo a WhatsApp /media
# --------------------------------------------------
def subir_media_whatsapp(token: str, phone_number_id: str, ruta_archivo: str, mime: str):
    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/media"

    headers = {
        "Authorization": f"Bearer {token}"
    }

    with open(ruta_archivo, "rb") as f:
        files = {
            "file": (os.path.basename(ruta_archivo), f, mime)
        }
        data = {
            "messaging_product": "whatsapp"
        }

        response = requests.post(url, headers=headers, files=files, data=data)

    return response.status_code, response.json()


# --------------------------------------------------
# 🔹 Enviar documento usando media_id
# --------------------------------------------------
def enviar_documento_id(token, numero_id, telefono_destino, media_id, filename, caption=None):
    url = f"https://graph.facebook.com/v19.0/{numero_id}/messages"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "document",
        "document": {
            "id": media_id,
            "filename": filename
        }
    }

    if caption:
        payload["document"]["caption"] = caption

    response = requests.post(url, headers=headers, json=payload)

    return response.status_code, response.json()


# --------------------------------------------------
# 🔹 ENDPOINT PRINCIPAL
# --------------------------------------------------

@router.post("/mensajes/documento")
async def api_enviar_documento(
    telefono: str = Form(...),
    nombre: str = Form(""),
    documento: UploadFile = Form(...),
    caption: str = Form(None)
):
    import os
    from datetime import datetime
    from fastapi import HTTPException

    TOKEN = current_token.get()
    PHONE_NUMBER_ID = current_phone_id.get()
    TENANT = current_tenant.get()
    AGENCIA_NOMBRE = current_business_name.get() or ""

    if not TOKEN or not PHONE_NUMBER_ID:
        return {"status": "error", "mensaje": "Credenciales no disponibles"}
    if not TENANT:
        return {"status": "error", "mensaje": "Tenant no disponible"}

    # --------------------------------------------------
    # 1️⃣ Validar tipo permitido
    # --------------------------------------------------
    allowed_types = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
        "text/plain"
    ]
    if documento.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Tipo de documento no permitido")

    # --------------------------------------------------
    # 2️⃣ Guardar temporalmente
    # --------------------------------------------------
    timestamp = int(datetime.now().timestamp())
    filename_tmp = f"{telefono}_{timestamp}_{documento.filename}"

    MEDIA_DIR = "temp_documents"
    os.makedirs(MEDIA_DIR, exist_ok=True)
    ruta_documento = os.path.join(MEDIA_DIR, filename_tmp)

    with open(ruta_documento, "wb") as f:
        f.write(await documento.read())

    # --------------------------------------------------
    # 3️⃣ Subir a Cloudinary
    # --------------------------------------------------
    url_cloudinary = None
    try:
        result = cloudinary.uploader.upload(
            ruta_documento,
            folder=f"whatsapp/{TENANT}/documents",
            resource_type="raw"
        )
        url_cloudinary = result.get("secure_url")
    except Exception as e:
        print("⚠️ Cloudinary falló:", str(e))

    # --------------------------------------------------
    # 4️⃣ Enviar SIEMPRE a WhatsApp
    # --------------------------------------------------
    metodo_envio = None
    media_id = None

    if documento.content_type == "application/pdf":

        codigo_up, resp_up = subir_media_whatsapp(
            token=TOKEN,
            phone_number_id=PHONE_NUMBER_ID,
            ruta_archivo=ruta_documento,
            mime="application/pdf"
        )

        if codigo_up == 200 and "id" in resp_up:

            media_id = resp_up["id"]
            codigo, respuesta_api = enviar_documento_id(
                token=TOKEN,
                numero_id=PHONE_NUMBER_ID,
                telefono_destino=telefono,
                media_id=media_id,
                filename=documento.filename,
                caption=caption
            )
            metodo_envio = "id"

        else:
            codigo = codigo_up
            respuesta_api = resp_up

    else:

        if url_cloudinary:
            codigo, respuesta_api = enviar_documento_link(
                token=TOKEN,
                numero_id=PHONE_NUMBER_ID,
                telefono_destino=telefono,
                url_documento=url_cloudinary,
                filename=documento.filename
            )
            metodo_envio = "link"
        else:
            codigo = 500
            respuesta_api = {"error": "No hay URL para enviar"}

    # --------------------------------------------------
    # 5️⃣ Guardar SOLO si fue exitoso
    # --------------------------------------------------
    if codigo == 200:

        message_id_meta = None
        if respuesta_api and "messages" in respuesta_api:
            message_id_meta = respuesta_api["messages"][0].get("id")

        if metodo_envio == "id":
            media_url_guardar = f"whatsapp_media_id:{media_id}"
        else:
            media_url_guardar = url_cloudinary

        contenido_guardar = f"{documento.filename}|{media_url_guardar}"

        guardar_mensaje_nuevo(
            telefono=telefono,
            contenido=contenido_guardar,
            direccion="enviado",
            tipo="document",
            media_url=media_url_guardar,
            message_id_meta=message_id_meta,
            estado="sent"
        )

        # --------------------------------------------------
        # 6️⃣ Intentar plantilla SOLO si fue exitoso
        # --------------------------------------------------
        intentar_plantilla_reconexion_24h(
            telefono=telefono,
            nombre=nombre,
            token=TOKEN,
            phone_number_id=PHONE_NUMBER_ID,
            agencia_nombre=AGENCIA_NOMBRE
        )

    # --------------------------------------------------
    # 7️⃣ Borrar temporal
    # --------------------------------------------------
    try:
        os.remove(ruta_documento)
    except:
        pass

    return {
        "status": "ok" if codigo == 200 else "error",
        "metodo_envio": metodo_envio,
        "url_cloudinary": url_cloudinary,
        "media_id": media_id,
        "codigo_api": codigo,
        "respuesta_api": respuesta_api if codigo != 200 else None
    }

@router.post("/mensajes/documento0")
async def api_enviar_documento0(
    telefono: str = Form(...),
    nombre: str = Form(""),   # ✅ NUEVO PARAMETRO
    documento: UploadFile = Form(...),
    caption: str = Form(None)
):
    import os
    from datetime import datetime
    from fastapi import HTTPException

    TOKEN = current_token.get()
    PHONE_NUMBER_ID = current_phone_id.get()
    TENANT = current_tenant.get()

    if not TOKEN or not PHONE_NUMBER_ID:
        return {"status": "error", "mensaje": "Credenciales no disponibles"}
    if not TENANT:
        return {"status": "error", "mensaje": "Tenant no disponible"}


    enviada, payload = intentar_plantilla_reconexion_24h(
        telefono=telefono,
        nombre=nombre,  # si no tienes, manda ""
        token=TOKEN,
        phone_number_id=PHONE_NUMBER_ID,
        agencia_nombre=current_business_name.get() or ""
    )
    if enviada:
        return payload

    # --------------------------------------------------
    # 1️⃣ Validar tipo permitido
    # --------------------------------------------------
    allowed_types = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
        "text/plain"
    ]
    if documento.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Tipo de documento no permitido")

    # --------------------------------------------------
    # 2️⃣ Guardar temporalmente
    # --------------------------------------------------
    timestamp = int(datetime.now().timestamp())
    filename_tmp = f"{telefono}_{timestamp}_{documento.filename}"

    MEDIA_DIR = "temp_documents"
    os.makedirs(MEDIA_DIR, exist_ok=True)
    ruta_documento = os.path.join(MEDIA_DIR, filename_tmp)

    with open(ruta_documento, "wb") as f:
        f.write(await documento.read())

    # --------------------------------------------------
    # 3️⃣ Subir SIEMPRE a Cloudinary (para UI/preview) (opcional)
    #    Si NO quieres guardar tanto, puedes comentar este bloque.
    # --------------------------------------------------
    url_cloudinary = None
    try:
        result = cloudinary.uploader.upload(
            ruta_documento,
            folder=f"whatsapp/{TENANT}/documents",
            resource_type="raw"
        )
        url_cloudinary = result.get("secure_url")
    except Exception as e:
        # Si Cloudinary es obligatorio para ti, cambia esto a "return error"
        print("⚠️ Cloudinary falló:", str(e))

    # --------------------------------------------------
    # 4️⃣ Envío anticipado por tipo:
    #    PDF -> WhatsApp media_id
    #    Otros -> link (Cloudinary)
    # --------------------------------------------------
    metodo_envio = None
    media_id = None

    if documento.content_type == "application/pdf":
        # ✅ PDF por media_id (WhatsApp)
        codigo_up, resp_up = subir_media_whatsapp(
            token=TOKEN,
            phone_number_id=PHONE_NUMBER_ID,
            ruta_archivo=ruta_documento,
            mime="application/pdf"
        )

        if codigo_up != 200 or "id" not in resp_up:
            try: os.remove(ruta_documento)
            except: pass
            return {
                "status": "error",
                "mensaje": "Error subiendo PDF a WhatsApp /media",
                "codigo_upload": codigo_up,
                "respuesta_upload": resp_up
            }

        media_id = resp_up["id"]
        codigo, respuesta_api = enviar_documento_id(
            token=TOKEN,
            numero_id=PHONE_NUMBER_ID,
            telefono_destino=telefono,
            media_id=media_id,
            filename=documento.filename,
            caption=caption
        )
        metodo_envio = "id"

    else:
        # ✅ Otros por link (Cloudinary)
        if not url_cloudinary:
            try: os.remove(ruta_documento)
            except: pass
            return {
                "status": "error",
                "mensaje": "No hay URL de Cloudinary para enviar por link"
            }

        codigo, respuesta_api = enviar_documento_link(
            token=TOKEN,
            numero_id=PHONE_NUMBER_ID,
            telefono_destino=telefono,
            url_documento=url_cloudinary,
            filename=documento.filename
        )
        metodo_envio = "link"

        # --------------------------------------------------
        # 5️⃣ Guardar en BD si fue exitoso
        # --------------------------------------------------
    if codigo == 200:
        message_id_meta = respuesta_api.get("messages", [{}])[0].get("id")

        if metodo_envio == "id":
            # ✅ Para PDF guardamos filename en media_url
            media_url_guardar = f"whatsapp_media_id:{media_id}"
        else:
            media_url_guardar = url_cloudinary

        contenido_guardar = f"{documento.filename}|{media_url_guardar}"

        guardar_mensaje_nuevo(
            telefono=telefono,
            contenido=contenido_guardar,
            direccion="enviado",
            tipo="document",
            media_url=media_url_guardar,
            message_id_meta=message_id_meta,
            estado="sent"
        )

    # --------------------------------------------------
    # 6️⃣ Borrar temporal
    # --------------------------------------------------
    try: os.remove(ruta_documento)
    except: pass

    return {
        "status": "ok" if codigo == 200 else "error",
        "metodo_envio": metodo_envio,
        "url_cloudinary": url_cloudinary,
        "media_id": media_id,
        "codigo_api": codigo,
        "respuesta_api": respuesta_api if codigo != 200 else None
    }

def enviar_documento_link(
    token,
    numero_id,
    telefono_destino,
    url_documento,
    filename
):
    url = f"https://graph.facebook.com/v19.0/{numero_id}/messages"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    data = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "document",
        "document": {
            "link": url_documento,
            "filename": filename
        }
    }

    response = requests.post(url, headers=headers, json=data)

    return response.status_code, response.json()



@router.post("/mensajes/documentoV17022026")
async def api_enviar_documentoV17022026(
    telefono: str = Form(...),
    documento: UploadFile = Form(...),
    caption: str = Form(None)
):
    TOKEN = current_token.get()
    PHONE_NUMBER_ID = current_phone_id.get()
    TENANT = current_tenant.get()

    if not TOKEN or not PHONE_NUMBER_ID:
        return {"status": "error", "mensaje": "Credenciales no disponibles"}

    if not TENANT:
        return {"status": "error", "mensaje": "Tenant no disponible"}

    # --------------------------------------------------
    # 1️⃣ Validar tipos permitidos
    # --------------------------------------------------
    allowed_types = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
        "text/plain"
    ]

    if documento.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Tipo de documento no permitido")

    # --------------------------------------------------
    # 2️⃣ Guardar temporalmente
    # --------------------------------------------------
    timestamp = int(datetime.now().timestamp())
    filename = f"{telefono}_{timestamp}_{documento.filename}"

    MEDIA_DIR = "temp_documents"
    os.makedirs(MEDIA_DIR, exist_ok=True)

    ruta_documento = os.path.join(MEDIA_DIR, filename)

    with open(ruta_documento, "wb") as f:
        f.write(await documento.read())

    # --------------------------------------------------
    # 3️⃣ Subir a WhatsApp Media (MÉTODO ESTABLE)
    # --------------------------------------------------
    codigo_upload, respuesta_upload = subir_media_whatsapp(
        token=TOKEN,
        phone_number_id=PHONE_NUMBER_ID,
        ruta_archivo=ruta_documento,
        mime=documento.content_type
    )

    if codigo_upload != 200 or "id" not in respuesta_upload:
        try:
            os.remove(ruta_documento)
        except:
            pass

        return {
            "status": "error",
            "mensaje": "Error subiendo documento a WhatsApp media",
            "codigo_upload": codigo_upload,
            "respuesta_upload": respuesta_upload
        }

    media_id = respuesta_upload["id"]

    # --------------------------------------------------
    # 4️⃣ Enviar documento usando media_id
    # --------------------------------------------------
    codigo_envio, respuesta_api = enviar_documento_id(
        token=TOKEN,
        numero_id=PHONE_NUMBER_ID,
        telefono_destino=telefono,
        media_id=media_id,
        filename=documento.filename,
        caption=caption
    )

    # --------------------------------------------------
    # 5️⃣ Guardar en BD solo si fue exitoso
    # --------------------------------------------------
    if codigo_envio == 200:
        message_id_meta = respuesta_api.get("messages", [{}])[0].get("id")

        guardar_mensaje_nuevo(
            telefono=telefono,
            contenido=f"whatsapp_media_id:{media_id}",
            direccion="enviado",
            tipo="document",
            media_url=None,
            message_id_meta=message_id_meta,
            estado="sent"
        )

    # --------------------------------------------------
    # 6️⃣ Eliminar archivo temporal
    # --------------------------------------------------
    try:
        os.remove(ruta_documento)
    except:
        pass

    return {
        "status": "ok" if codigo_envio == 200 else "error",
        "media_id": media_id,
        "codigo_api": codigo_envio,
        "respuesta_api": respuesta_api if codigo_envio != 200 else None
    }



# @router.post("/mensajes/documento")
# async def api_enviar_documento(
#     telefono: str = Form(...),
#     documento: UploadFile = Form(...)
# ):
#     import os
#     from datetime import datetime
#     from fastapi import HTTPException
#
#     TOKEN = current_token.get()
#     PHONE_NUMBER_ID = current_phone_id.get()
#     TENANT = current_tenant.get()
#
#     if not TOKEN or not PHONE_NUMBER_ID:
#         return {"status": "error", "mensaje": "Credenciales no disponibles"}
#
#     # --------------------------------------------------
#     # 1️⃣ Validar tipo permitido
#     # --------------------------------------------------
#     allowed_types = [
#         "application/pdf",
#         "application/msword",
#         "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
#         "application/vnd.ms-excel",
#         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#         "application/zip",
#         "text/plain"
#     ]
#
#     if documento.content_type not in allowed_types:
#         raise HTTPException(status_code=400, detail="Tipo de documento no permitido")
#
#     # --------------------------------------------------
#     # 2️⃣ Guardar temporalmente
#     # --------------------------------------------------
#     timestamp = int(datetime.now().timestamp())
#     filename = f"{telefono}_{timestamp}_{documento.filename}"
#
#     MEDIA_DIR = "temp_documents"
#     os.makedirs(MEDIA_DIR, exist_ok=True)
#
#     ruta_documento = os.path.join(MEDIA_DIR, filename)
#
#     with open(ruta_documento, "wb") as f:
#         f.write(await documento.read())
#
#     # --------------------------------------------------
#     # 3️⃣ Subir a Cloudinary (RAW para documentos)
#     # --------------------------------------------------
#     try:
#         result = cloudinary.uploader.upload(
#             ruta_documento,
#             folder=f"whatsapp/{TENANT}/documents",
#             resource_type="raw"
#         )
#
#         url_cloudinary = result.get("secure_url")
#
#     except Exception as e:
#         return {
#             "status": "error",
#             "mensaje": "Error subiendo documento a Cloudinary",
#             "error": str(e)
#         }
#
#     # --------------------------------------------------
#     # 4️⃣ Enviar a WhatsApp
#     # --------------------------------------------------
#     try:
#         codigo, respuesta_api = enviar_documento_link(
#             token=TOKEN,
#             numero_id=PHONE_NUMBER_ID,
#             telefono_destino=telefono,
#             url_documento=url_cloudinary,
#             filename=documento.filename
#         )
#     except Exception as e:
#         return {
#             "status": "error",
#             "mensaje": "Error enviando a WhatsApp",
#             "error": str(e)
#         }
#
#     # --------------------------------------------------
#     # 5️⃣ Guardar en BD si fue exitoso
#     # --------------------------------------------------
#     if codigo == 200:
#         message_id_meta = respuesta_api.get("messages", [{}])[0].get("id")
#
#         guardar_mensaje_nuevo(
#             telefono=telefono,
#             contenido=url_cloudinary,
#             direccion="enviado",
#             tipo="document",
#             media_url=url_cloudinary,
#             message_id_meta=message_id_meta,
#             estado="sent"
#         )
#
#     # --------------------------------------------------
#     # 6️⃣ Borrar temporal
#     # --------------------------------------------------
#     try:
#         os.remove(ruta_documento)
#     except:
#         pass
#
#     return {
#         "status": "ok",
#         "url_cloudinary": url_cloudinary,
#         "codigo_api": codigo
#     }


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


@router.post("/mensajes/video")
async def api_enviar_video(
    telefono: str = Form(...),
    nombre: str = Form(""),
    video: UploadFile = Form(...)
):
    import os
    from datetime import datetime
    from fastapi import HTTPException

    TOKEN = current_token.get()
    PHONE_NUMBER_ID = current_phone_id.get()
    TENANT = current_tenant.get()
    AGENCIA_NOMBRE = current_business_name.get() or ""

    if not TOKEN or not PHONE_NUMBER_ID:
        return {"status": "error", "mensaje": "Credenciales no disponibles"}

    # --------------------------------------------------
    # 1️⃣ Validar tipo permitido
    # --------------------------------------------------
    allowed_types = [
        "video/mp4",
        "video/quicktime",
        "video/webm"
    ]

    if video.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Tipo de video no permitido")

    # --------------------------------------------------
    # 2️⃣ Validar tamaño
    # --------------------------------------------------
    MAX_SIZE = 16 * 1024 * 1024  # 16MB
    contents = await video.read()

    if len(contents) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="Video demasiado pesado (máx 16MB)")

    # --------------------------------------------------
    # 3️⃣ Guardar temporalmente
    # --------------------------------------------------
    timestamp = int(datetime.now().timestamp())
    filename = f"{telefono}_{timestamp}_{video.filename}"

    MEDIA_DIR = "temp_videos"
    os.makedirs(MEDIA_DIR, exist_ok=True)

    ruta_video = os.path.join(MEDIA_DIR, filename)

    with open(ruta_video, "wb") as f:
        f.write(contents)

    # --------------------------------------------------
    # 4️⃣ Subir a Cloudinary
    # --------------------------------------------------
    try:
        result = cloudinary.uploader.upload(
            ruta_video,
            folder=f"whatsapp/{TENANT}/videos",
            resource_type="video"
        )
        url_cloudinary = result.get("secure_url")

    except Exception as e:
        try:
            os.remove(ruta_video)
        except:
            pass

        return {
            "status": "error",
            "mensaje": "Error subiendo video a Cloudinary",
            "error": str(e)
        }

    # --------------------------------------------------
    # 5️⃣ Enviar SIEMPRE a WhatsApp
    # --------------------------------------------------
    try:
        codigo, respuesta_api = enviar_video_link(
            token=TOKEN,
            numero_id=PHONE_NUMBER_ID,
            telefono_destino=telefono,
            url_video=url_cloudinary
        )
    except Exception as e:
        codigo = 500
        respuesta_api = {"error": str(e)}

    # --------------------------------------------------
    # 6️⃣ Guardar SOLO si fue exitoso
    # --------------------------------------------------
    if codigo == 200:

        message_id_meta = None
        if respuesta_api and "messages" in respuesta_api:
            message_id_meta = respuesta_api["messages"][0].get("id")

        guardar_mensaje_nuevo(
            telefono=telefono,
            contenido=url_cloudinary,
            direccion="enviado",
            tipo="video",
            media_url=url_cloudinary,
            message_id_meta=message_id_meta,
            estado="sent"
        )

        # --------------------------------------------------
        # 7️⃣ Intentar plantilla SOLO si fue exitoso
        # --------------------------------------------------
        intentar_plantilla_reconexion_24h(
            telefono=telefono,
            nombre=nombre,
            token=TOKEN,
            phone_number_id=PHONE_NUMBER_ID,
            agencia_nombre=AGENCIA_NOMBRE
        )

    # --------------------------------------------------
    # 8️⃣ Borrar temporal
    # --------------------------------------------------
    try:
        os.remove(ruta_video)
    except:
        pass

    return {
        "status": "ok" if codigo == 200 else "error",
        "url_cloudinary": url_cloudinary,
        "codigo_api": codigo,
        "respuesta_api": respuesta_api if codigo != 200 else None
    }


@router.post("/mensajes/video0")
async def api_enviar_video0(
    telefono: str = Form(...),
    nombre: str = Form(""),   # ✅ NUEVO PARAMETRO
    video: UploadFile = Form(...)
):
    import os
    from datetime import datetime
    from fastapi import HTTPException

    TOKEN = current_token.get()
    PHONE_NUMBER_ID = current_phone_id.get()
    TENANT = current_tenant.get()

    if not TOKEN or not PHONE_NUMBER_ID:
        return {"status": "error", "mensaje": "Credenciales no disponibles"}

    enviada, payload = intentar_plantilla_reconexion_24h(
        telefono=telefono,
        nombre=nombre,  # si no tienes, manda ""
        token=TOKEN,
        phone_number_id=PHONE_NUMBER_ID,
        agencia_nombre=current_business_name.get() or ""
    )
    if enviada:
        return payload

    # --------------------------------------------------
    # 1️⃣ Validar tipo permitido
    # --------------------------------------------------
    allowed_types = [
        "video/mp4",
        "video/quicktime",
        "video/webm"
    ]

    if video.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Tipo de video no permitido")

    # --------------------------------------------------
    # 2️⃣ Validar tamaño (ejemplo: 16MB recomendado)
    # --------------------------------------------------
    MAX_SIZE = 16 * 1024 * 1024  # 16MB

    contents = await video.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="Video demasiado pesado (máx 16MB)")

    # --------------------------------------------------
    # 3️⃣ Guardar temporalmente
    # --------------------------------------------------
    timestamp = int(datetime.now().timestamp())
    filename = f"{telefono}_{timestamp}_{video.filename}"

    MEDIA_DIR = "temp_videos"
    os.makedirs(MEDIA_DIR, exist_ok=True)

    ruta_video = os.path.join(MEDIA_DIR, filename)

    with open(ruta_video, "wb") as f:
        f.write(contents)

    # --------------------------------------------------
    # 4️⃣ Subir a Cloudinary
    # --------------------------------------------------
    try:
        result = cloudinary.uploader.upload(
            ruta_video,
            folder=f"whatsapp/{TENANT}/videos",
            resource_type="video"
        )

        url_cloudinary = result.get("secure_url")

    except Exception as e:
        return {
            "status": "error",
            "mensaje": "Error subiendo video a Cloudinary",
            "error": str(e)
        }

    # --------------------------------------------------
    # 5️⃣ Enviar a WhatsApp
    # --------------------------------------------------
    try:
        codigo, respuesta_api = enviar_video_link(
            token=TOKEN,
            numero_id=PHONE_NUMBER_ID,
            telefono_destino=telefono,
            url_video=url_cloudinary
        )
    except Exception as e:
        return {
            "status": "error",
            "mensaje": "Error enviando video a WhatsApp",
            "error": str(e)
        }

    # --------------------------------------------------
    # 6️⃣ Guardar en BD si fue exitoso
    # --------------------------------------------------
    if codigo == 200:
        message_id_meta = respuesta_api.get("messages", [{}])[0].get("id")

        guardar_mensaje_nuevo(
            telefono=telefono,
            contenido=url_cloudinary,
            direccion="enviado",
            tipo="video",
            media_url=url_cloudinary,
            message_id_meta=message_id_meta,
            estado="sent"
        )

    # --------------------------------------------------
    # 7️⃣ Borrar temporal
    # --------------------------------------------------
    try:
        os.remove(ruta_video)
    except:
        pass

    return {
        "status": "ok",
        "url_cloudinary": url_cloudinary,
        "codigo_api": codigo
    }

def enviar_video_link(
    token,
    numero_id,
    telefono_destino,
    url_video
):
    import requests

    url = f"https://graph.facebook.com/v19.0/{numero_id}/messages"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    data = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "video",
        "video": {
            "link": url_video
        }
    }

    response = requests.post(url, headers=headers, json=data)

    return response.status_code, response.json()



@router.get("/media/preview/{media_id}")
def preview_media_pdf(media_id: str):
    """
    Preview/stream de un PDF guardado en WhatsApp (Meta) por media_id.
    Ideal para usar en <iframe src="..."> en el frontend.
    Requiere auth + tenant (tu middleware debe setear current_token/current_tenant).
    """

    TOKEN = current_token.get()
    TENANT = current_tenant.get()

    if not TOKEN:
        raise HTTPException(status_code=401, detail="Credenciales no disponibles")
    if not TENANT:
        raise HTTPException(status_code=400, detail="Tenant no disponible")

    # Permitir que el frontend pase "whatsapp_media_id:xxxx"
    if media_id.startswith("whatsapp_media_id:"):
        media_id = media_id.split("whatsapp_media_id:", 1)[1].strip()

    # 1) Pedir a Meta la info del media (incluye URL temporal)
    info_url = f"https://graph.facebook.com/v19.0/{media_id}"
    info_params = {"fields": "url,mime_type,sha256,file_size"}
    info_headers = {"Authorization": f"Bearer {TOKEN}"}

    info_resp = requests.get(info_url, headers=info_headers, params=info_params, timeout=20)
    try:
        info_json = info_resp.json()
    except Exception:
        info_json = {}

    if info_resp.status_code != 200:
        raise HTTPException(
            status_code=info_resp.status_code,
            detail={"mensaje": "Error obteniendo URL de media en Meta", "respuesta": info_json}
        )

    media_download_url = info_json.get("url")
    mime_type = info_json.get("mime_type") or "application/pdf"

    if not media_download_url:
        raise HTTPException(status_code=500, detail="Meta no devolvió URL de descarga")

    # Si quieres forzar SOLO PDF:
    if mime_type != "application/pdf":
        raise HTTPException(status_code=400, detail=f"Este endpoint solo previsualiza PDF. mime_type={mime_type}")

    # 2) Descargar el archivo desde la URL temporal (requiere Bearer token)
    download_headers = {"Authorization": f"Bearer {TOKEN}"}
    download_resp = requests.get(media_download_url, headers=download_headers, stream=True, timeout=30)

    if download_resp.status_code != 200:
        raise HTTPException(
            status_code=download_resp.status_code,
            detail={"mensaje": "Error descargando media desde Meta", "respuesta": download_resp.text[:200]}
        )

    def iter_file():
        # chunks para streaming
        for chunk in download_resp.iter_content(chunk_size=1024 * 256):
            if chunk:
                yield chunk

    # 3) Responder como inline para preview en iframe
    headers = {
        "Content-Disposition": 'inline; filename="documento.pdf"',
        "Cache-Control": "no-store",
    }

    return StreamingResponse(iter_file(), media_type="application/pdf", headers=headers)


import logging
logger = logging.getLogger("whatsapp")

import mimetypes

async def reenviar_ultimo_mensaje(telefono: str):
    logger.info(f"🔄 Reenviando último mensaje para teléfono: {telefono}")

    # =====================================================
    # 1️⃣ Buscar el mensaje (Priorizando el error 131047)
    # =====================================================
    with get_connection_context() as conn:
        # Usamos DictCursor para que el acceso sea más legible
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Esta consulta busca el último mensaje enviado.
        # El ORDER BY prioriza mensajes con el error 131047, y luego por fecha.
        cur.execute("""
                    SELECT contenido, media_url, tipo, fecha, error_codigo
                    FROM mensajes_whatsapp
                    WHERE telefono = %s
                      AND direccion = 'enviado'
                      AND tipo IN ('text', 'document', 'audio', 'image', 'video')
                    ORDER BY fecha DESC LIMIT 1
                    """, (telefono,))
        row = cur.fetchone()

    if not row:
        logger.warning(f"⚠ No hay mensajes previos para {telefono}")
        raise HTTPException(status_code=404, detail="No hay mensajes para este teléfono")

    # Extraer datos (ahora como diccionario por RealDictCursor)
    contenido = row['contenido']
    media_url = row['media_url']
    tipo_mensaje = row['tipo']
    fecha = row['fecha']
    error_was_24h = (row['error_codigo'] == 131047)

    logger.info(
        f"📦 Mensaje recuperado | tipo={tipo_mensaje} | fecha={fecha} | "
        f"¿Es error 24h?={error_was_24h} | media_url={media_url}"
    )

    # =====================================================
    # 🔹 TEXTO
    # =====================================================
    if tipo_mensaje == "text":
        logger.info("✉ Reenviando texto")
        # Quitamos el request=None si tu api_enviar_mensaje no lo requiere estrictamente
        return await api_enviar_mensaje(
            request=None,
            data={"telefono": telefono, "mensaje": contenido}
        )

    # =====================================================
    # 🔹 DOCUMENTO CON MEDIA_ID DIRECTO
    # =====================================================
    if media_url and media_url.startswith("whatsapp_media_id:"):
        media_id = media_url.replace("whatsapp_media_id:", "")
        logger.info(f"📎 Reenviando usando media_id directo: {media_id}")

        return await enviar_documento_id(
            token=current_token.get(),
            numero_id=current_phone_id.get(),
            telefono_destino=telefono,
            media_id=media_id,
            filename=contenido.split("|")[0] if contenido and "|" in contenido else "documento",
            caption=None
        )

    # =====================================================
    # 🔹 VALIDACIÓN DE MULTIMEDIA CON URL
    # =====================================================
    if not media_url:
        logger.error(f"❌ El mensaje tipo {tipo_mensaje} no tiene media_url ni media_id")
        raise HTTPException(status_code=400, detail="Mensaje multimedia sin origen de datos")

    # =====================================================
    # ⬇ PROCESAMIENTO DE DESCARGA (Para Audio, Imagen, Video, Doc)
    # =====================================================
    logger.info(f"⬇ Descargando archivo desde URL para reenvío...")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(media_url)
            response.raise_for_status()
            file_content = response.content
    except Exception as e:
        logger.exception(f"❌ Error descargando archivo: {e}")
        raise HTTPException(status_code=500, detail="Error descargando archivo para reenvío")

    # Nombre y MIME type
    filename = media_url.split("/")[-1] or "file"
    content_type = response.headers.get("content-type")
    if not content_type or content_type == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(filename)
        content_type = guessed or "application/octet-stream"

    # Crear UploadFile compatible con tus funciones api_enviar_*
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.write(file_content)
    tmp.seek(0)

    upload_file = UploadFile(
        filename=filename,
        file=tmp,
        headers={"content-type": content_type}
    )

    # Enviar según el tipo
    try:
        if tipo_mensaje == "audio":
            return await api_enviar_audio(telefono=telefono, nombre="", audio=upload_file)

        elif tipo_mensaje == "image":
            return await api_enviar_imagen(telefono=telefono, nombre="", imagen=upload_file)

        elif tipo_mensaje == "video":
            return await api_enviar_video(telefono=telefono, nombre="", video=upload_file)

        elif tipo_mensaje == "document":
            return await api_enviar_documento(telefono=telefono, nombre="", documento=upload_file, caption=None)

    finally:
        # Importante: cerrar y eliminar el archivo temporal después del envío
        tmp.close()
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)

    logger.error(f"❌ Tipo no soportado al final del flujo: {tipo_mensaje}")
    raise HTTPException(status_code=400, detail=f"Tipo no soportado: {tipo_mensaje}")


async def reenviar_ultimo_mensajeV0(telefono: str):

    logger.info(f"🔄 Reenviando último mensaje para teléfono: {telefono}")

    # =====================================================
    # 1️⃣ Buscar último mensaje
    # =====================================================
    with get_connection_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT contenido, media_url, tipo, fecha
            FROM mensajes_whatsapp
            WHERE telefono = %s
              AND direccion = 'enviado'
              AND tipo in ('text','document','audio','image','video')
            ORDER BY fecha DESC
            LIMIT 1
        """, (telefono,))
        row = cur.fetchone()

    if not row:
        logger.warning(f"⚠ No hay mensajes para {telefono}")
        raise HTTPException(status_code=404, detail="No hay mensajes para este teléfono")

    contenido, media_url, tipo_mensaje, fecha = row

    logger.info(
        f"📦 Último mensaje | tipo={tipo_mensaje} | fecha={fecha} | media_url={media_url}"
    )

    # =====================================================
    # 🔹 TEXTO
    # =====================================================
    if tipo_mensaje == "text":
        logger.info("✉ Reenviando texto")
        return await api_enviar_mensaje(
            request=None,
            data={"telefono": telefono, "mensaje": contenido}
        )

    # =====================================================
    # 🔹 DOCUMENTO CON MEDIA_ID (NO descargar)
    # =====================================================
    if media_url and media_url.startswith("whatsapp_media_id:"):

        media_id = media_url.replace("whatsapp_media_id:", "")
        logger.info(f"📎 Reenviando usando media_id directo: {media_id}")

        return await enviar_documento_id(
            token=current_token.get(),
            numero_id=current_phone_id.get(),
            telefono_destino=telefono,
            media_id=media_id,
            filename=contenido.split("|")[0] if "|" in contenido else "documento",
            caption=None
        )

    # =====================================================
    # 🔹 MULTIMEDIA CON URL
    # =====================================================
    if not media_url:
        logger.error("❌ Multimedia sin media_url")
        raise HTTPException(status_code=400, detail="Mensaje multimedia sin media_url")

    logger.info(f"⬇ Descargando desde: {media_url}")

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(media_url)
            response.raise_for_status()
    except Exception as e:
        logger.exception(f"❌ Error descargando archivo: {e}")
        raise HTTPException(status_code=500, detail="Error descargando archivo")

    filename = media_url.split("/")[-1]

    # Detectar MIME real
    content_type = response.headers.get("content-type")

    if not content_type or content_type == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(filename)
        content_type = guessed or "application/octet-stream"

    logger.info(
        f"📄 Archivo descargado | filename={filename} | "
        f"content_type={content_type} | size={len(response.content)} bytes"
    )

    # Crear archivo temporal
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.write(response.content)
    tmp.seek(0)

    upload_file = UploadFile(
        filename=filename,
        file=tmp,
        headers={"content-type": content_type}
    )

    # =====================================================
    # 🔹 AUDIO
    # =====================================================
    if tipo_mensaje == "audio":
        logger.info("🎧 Reenviando audio")
        return await api_enviar_audio(
            telefono=telefono,
            nombre="",
            audio=upload_file
        )

    # =====================================================
    # 🔹 IMAGEN
    # =====================================================
    elif tipo_mensaje == "image":
        logger.info("🖼 Reenviando imagen")
        return await api_enviar_imagen(
            telefono=telefono,
            nombre="",
            imagen=upload_file
        )

    # =====================================================
    # 🔹 VIDEO
    # =====================================================
    elif tipo_mensaje == "video":
        logger.info("🎥 Reenviando video")
        return await api_enviar_video(
            telefono=telefono,
            nombre="",
            video=upload_file
        )

    # =====================================================
    # 🔹 DOCUMENTO
    # =====================================================
    elif tipo_mensaje == "document":
        logger.info("📎 Reenviando documento")

        return await api_enviar_documento(
            telefono=telefono,
            nombre="",
            documento=upload_file,
            caption=None
        )

    else:
        logger.error(f"❌ Tipo no soportado: {tipo_mensaje}")
        raise HTTPException(
            status_code=400,
            detail=f"Tipo no soportado: {tipo_mensaje}"
        )




async def reenviar_ultimo_mensaje1(telefono: str):

    logger.info(f"🔄 Reenviando último mensaje para teléfono: {telefono}")

    # 1️⃣ Buscar último mensaje
    with get_connection_context() as conn:
        cur = conn.cursor()
        cur.execute("""
                SELECT contenido, media_url, tipo, fecha
                FROM mensajes_whatsapp
                WHERE telefono = %s
                  AND direccion = 'enviado'
                  AND tipo in ('text','document','audio','image','video')
                ORDER BY fecha DESC
                LIMIT 1
        """, (telefono,))

        row = cur.fetchone()

    if not row:
        logger.warning(f"⚠ No hay mensajes para el teléfono {telefono}")
        raise HTTPException(status_code=404, detail="No hay mensajes para este teléfono")

    contenido, media_url, tipo_mensaje, fecha = row

    logger.info(
        f"📦 Último mensaje encontrado | "
        f"tipo={tipo_mensaje} | "
        f"fecha={fecha} | "
        f"media_url={media_url}"
    )

    # =====================================================
    # 🔹 CASO TEXTO
    # =====================================================
    if tipo_mensaje == "text":
        logger.info("✉ Reenviando mensaje de texto")
        return await api_enviar_mensaje(
            request=None,
            data={
                "telefono": telefono,
                "mensaje": contenido
            }
        )

    # =====================================================
    # 🔹 MULTIMEDIA
    # =====================================================
    if not media_url:
        logger.error("❌ Mensaje multimedia sin media_url")
        raise HTTPException(status_code=400, detail="Mensaje multimedia sin media_url")

    logger.info(f"⬇ Descargando archivo desde: {media_url}")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(media_url)
            response.raise_for_status()
    except Exception as e:
        logger.exception(f"❌ Error descargando archivo: {e}")
        raise

    logger.info(
        f"✅ Archivo descargado | "
        f"status={response.status_code} | "
        f"content_type={response.headers.get('content-type')} | "
        f"size={len(response.content)} bytes"
    )

    # Crear archivo temporal
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.write(response.content)
    tmp.seek(0)

    filename = media_url.split("/")[-1]

    logger.info(f"📄 Archivo temporal creado: {filename}")

    upload_file = UploadFile(
        filename=filename,
        file=tmp
    )

    # =====================================================
    # 🔹 AUDIO
    # =====================================================
    if tipo_mensaje == "audio":
        logger.info("🎧 Reenviando audio")
        return await api_enviar_audio(
            telefono=telefono,
            nombre="",
            audio=upload_file
        )

    # =====================================================
    # 🔹 IMAGEN
    # =====================================================
    elif tipo_mensaje == "image":
        logger.info("🖼 Reenviando imagen")
        return await api_enviar_imagen(
            telefono=telefono,
            nombre="",
            imagen=upload_file
        )

    # =====================================================
    # 🔹 VIDEO
    # =====================================================
    elif tipo_mensaje == "video":
        logger.info("🎥 Reenviando video")
        return await api_enviar_video(
            telefono=telefono,
            nombre="",
            video=upload_file
        )

    # =====================================================
    # 🔹 DOCUMENTO
    # =====================================================
    elif tipo_mensaje == "document":
        logger.info("📎 Reenviando documento")
        return await api_enviar_documento(
            telefono=telefono,
            nombre="",
            documento=upload_file,
            caption=None
        )

    else:
        logger.error(f"❌ Tipo no soportado: {tipo_mensaje}")
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de mensaje no soportado: {tipo_mensaje}"
        )

async def reenviar_ultimo_mensaje0(telefono: str):
    # 1️⃣ Buscar último mensaje
    with get_connection_context() as conn:
        cur = conn.cursor()
        cur.execute("""
                SELECT contenido, media_url, tipo
                FROM mensajes_whatsapp
                WHERE telefono = %s
                  AND direccion = 'enviado'
                  AND (
                        tipo in ('text','document','audio','image','video')
                      )
                ORDER BY fecha DESC
                LIMIT 1
                    """, (telefono,))

        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="No hay mensajes para este teléfono")

    contenido, media_url, tipo_mensaje = row

    # =====================================================
    # 🔹 CASO TEXTO
    # =====================================================
    if tipo_mensaje == "text":
        return await api_enviar_mensaje(
            request=None,
            data={
                "telefono": telefono,
                "mensaje": contenido
            }
        )

    # =====================================================
    # 🔹 CASO MULTIMEDIA
    # =====================================================
    if not media_url:
        raise HTTPException(status_code=400, detail="Mensaje multimedia sin media_url")

    # Descargar archivo desde Cloudinary
    async with httpx.AsyncClient() as client:
        response = await client.get(media_url)
        response.raise_for_status()

    # Crear archivo temporal
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.write(response.content)
    tmp.seek(0)

    filename = media_url.split("/")[-1]

    upload_file = UploadFile(
        filename=filename,
        file=tmp
    )

    # =====================================================
    # 🔹 AUDIO
    # =====================================================
    if tipo_mensaje == "audio":
        return await api_enviar_audio(
            telefono=telefono,
            nombre="",
            audio=upload_file
        )

    # =====================================================
    # 🔹 IMAGEN
    # =====================================================
    elif tipo_mensaje == "image":
        return await api_enviar_imagen(
            telefono=telefono,
            nombre="",
            imagen=upload_file
        )

    # =====================================================
    # 🔹 VIDEO
    # =====================================================
    elif tipo_mensaje == "video":
        return await api_enviar_video(
            telefono=telefono,
            nombre="",
            video=upload_file
        )

    # =====================================================
    # 🔹 DOCUMENTO
    # =====================================================
    elif tipo_mensaje == "document":
        return await api_enviar_documento(
            telefono=telefono,
            nombre="",
            documento=upload_file,
            caption=None
        )

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de mensaje no soportado: {tipo_mensaje}"
        )


async def enviar_mensaje_con_credenciales(
    telefono: str,
    mensaje: str,
    token_cliente: str,
    phone_id_cliente: str,
    Agencia_nombre: str,
    nombre: str
):
    """
    Envía mensaje normal.
    La detección de ventana 24h se maneja en el webhook.
    """

    if not telefono or not mensaje:
        return {"error": "Faltan datos"}

    if not token_cliente or not phone_id_cliente:
        return {"error": "Credenciales inválidas"}

    codigo, respuesta_api = enviar_mensaje_texto_simple(
        token=token_cliente,
        numero_id=phone_id_cliente,
        telefono_destino=telefono,
        texto=mensaje
    )

    message_id_meta = None

    if respuesta_api and "messages" in respuesta_api:
        message_id_meta = respuesta_api["messages"][0].get("id")

    # Guardamos como enviado (pendiente de status real)
    guardar_mensaje_nuevo(
        telefono=telefono,
        contenido=mensaje,
        direccion="enviado",
        tipo="text",
        message_id_meta=message_id_meta,
        estado="sent" if codigo == 200 else "error"
    )

    intentar_plantilla_reconexion_24h(
        telefono=telefono,
        nombre=nombre,
        token=token_cliente,
        phone_number_id=phone_id_cliente,
        agencia_nombre=Agencia_nombre
    )

    return {
        "status": "ok" if codigo == 200 else "error",
        "codigo_api": codigo
    }

class EnviarNoAptoIn(BaseModel):
    creador_id: int

def mensaje_invitacion_simple(nombre: Optional[str], business_name: str) -> str:

    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT valor
                    FROM configuracion_agencia
                    WHERE clave = %s
                    LIMIT 1
                """, ("mensaje_invitacion",))

                row = cur.fetchone()

                if not row or not row[0]:
                    raise ValueError("La clave 'mensaje_invitacion' no existe en configuracion_agencia")

                template_text = row[0]

    except Exception as e:
        print("❌ Error obteniendo mensaje_invitacion:", e)
        traceback.print_exc()
        raise  # 🔥 Aquí forzamos a que falle si no existe

    nombre_final = nombre.strip() if nombre and nombre.strip() else "Hola"

    try:
        return template_text.format(
            nombre=nombre_final,
            business_name=business_name
        )
    except KeyError as e:
        print(f"⚠️ Placeholder incorrecto en mensaje_invitacion: {e}")
        return template_text  # lo envía sin reemplazar si hay error

def mensaje_no_apto_simple(nombre: Optional[str], business_name: str) -> str:

    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT valor
                    FROM configuracion_agencia_keys
                    WHERE clave = %s
                    LIMIT 1
                """, ("mensaje_rechazado",))

                row = cur.fetchone()
                template_text = row[0] if row and row[0] else None

    except Exception as e:
        print("❌ Error obteniendo mensaje_rechazado:", e)
        traceback.print_exc()
        template_text = None

    # 🔹 Si existe en DB → usarlo tal cual pero formateado
    if template_text:
        return template_text.format(
            nombre=nombre.strip() if nombre and nombre.strip() else "Hola",
            business_name=business_name
        )

    # 🔹 Fallback original (exactamente tu mensaje)
    if nombre:
        saludo = f"Hola {nombre} 👋\n\n"
    else:
        saludo = "Hola 👋\n\n"

    cuerpo = (
        f"Gracias por tu interés en *{business_name}* y por el tiempo que dedicaste a completar tu información.\n\n"
        "Después de revisar tu preevaluación, en este momento no cumples con los requisitos "
        "para continuar en el proceso de selección de creadores de TikTok LIVE.\n\n"
        "Esto no refleja tu talento ni tu potencial. Te invitamos a seguir fortaleciendo tu contenido "
        "y métricas, y a postular nuevamente más adelante si lo deseas.\n\n"
        "Puedes consultar el diagnóstico completo en el portal que te compartimos anteriormente.\n\n"
        "Te deseamos muchos éxitos en tus próximos proyectos 🙌"
    )

    return saludo + cuerpo

def enviar_mensaje(numero: str, texto: str):
    try:
        # Validar entrada
        if not numero or not numero.strip():
            raise ValueError("Número de teléfono no puede estar vacío")
        if not texto or not texto.strip():
            raise ValueError("Texto del mensaje no puede estar vacío")

        # Obtener contexto del tenant
        try:
            token = current_token.get()
            phone_id = current_phone_id.get()

            # Seguros: solo últimos 6 chars visibles
            token_safe = f"...{token[-6:]}" if token else "None"
            phone_id_safe = f"...{phone_id[-6:]}" if phone_id else "None"

            print(f"🔐 Token usado: {token_safe}")
            print(f"📱 Phone ID usado: {phone_id_safe}")


        except LookupError as e:
            print(f"❌ Contexto de tenant no disponible al enviar mensaje a {numero}: {e}")
            raise LookupError(f"Contexto de tenant no disponible: {e}") from e

        return enviar_mensaje_texto_simple(
            token=token,
            numero_id=phone_id,
            telefono_destino=numero.strip(),
            texto=texto.strip()
        )
    except (LookupError, ValueError) as e:
        # Re-raise errores de validación y contexto
        raise
    except Exception as e:
        print(f"❌ Error enviando mensaje a {numero}: {e}")
        traceback.print_exc()
        raise


@router.post("/api/aspirantes/invitacion/enviar")
def enviar_mensaje_invitacion(
    data: EnviarNoAptoIn,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    telefono = None
    nombre = None
    creador_id = None
    tipo_envio = None
    contenido_guardado = None
    codigo = None
    respuesta = None
    message_id_meta = None

    try:
        # ======================================================
        # 1️⃣ Obtener aspirante
        # ======================================================
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id,
                           COALESCE(nickname, nombre_real) AS nombre,
                           telefono
                    FROM creadores
                    WHERE id = %s;
                """, (data.creador_id,))
                row = cur.fetchone()

                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail="Aspirante no encontrado."
                    )

                creador_id, nombre, telefono = row

        if not telefono:
            raise HTTPException(
                status_code=400,
                detail="El aspirante no tiene número registrado."
            )

        # ======================================================
        # 2️⃣ Obtener credenciales WABA
        # ======================================================
        subdominio = current_tenant.get()
        cuenta = obtener_cuenta_por_subdominio(subdominio)

        if not cuenta:
            raise HTTPException(
                status_code=500,
                detail=f"No hay credenciales WABA para '{subdominio}'."
            )

        token = cuenta["access_token"]
        phone_id = cuenta["phone_number_id"]
        business_name = (
            cuenta.get("business_name")
            or cuenta.get("nombre")
            or "nuestra agencia"
        )

        # ======================================================
        # 3️⃣ Validar ventana 24h
        # True = abierta
        # False = cerrada
        # ======================================================
        ventana_abierta = obtener_status_24hrs(telefono)

        if ventana_abierta:
            # 👉 MENSAJE LIBRE
            tipo_envio = "mensaje_simple"
            contenido_guardado = mensaje_invitacion_simple(nombre, business_name)

            codigo, respuesta = enviar_mensaje_texto_simple(
                token=token,
                numero_id=phone_id,
                telefono_destino=telefono,
                texto=contenido_guardado
            )
        else:
            # 👉 PLANTILLA
            tipo_envio = "plantilla"
            parametros = [nombre or "amigo(a)", business_name, "t/ZMAqjPPCK/"]

            codigo, respuesta = enviar_plantilla_generica_parametros(
                token=token,
                phone_number_id=phone_id,
                numero_destino=telefono,
                nombre_plantilla="invitacion_unirse_agencia",
                codigo_idioma="es_CO",
                parametros=parametros,
                body_vars_count=2
            )

            contenido_guardado = (
                f"PLANTILLA: invitacion_unirse_agencia | parametros={parametros}"
            )

        # ======================================================
        # 4️⃣ Extraer message_id_meta
        # ======================================================
        if isinstance(respuesta, dict) and respuesta.get("messages"):
            try:
                message_id_meta = respuesta["messages"][0].get("id")
            except Exception:
                message_id_meta = None

        # ======================================================
        # 5️⃣ Guardar SIEMPRE en mensajes_whatsapp
        # ======================================================
        guardar_mensaje_nuevo(
            telefono=telefono,
            contenido=contenido_guardado,
            direccion="enviado",
            tipo="template" if tipo_envio == "plantilla" else "texto",
            message_id_meta=message_id_meta,
            estado="sent" if codigo and codigo < 300 else "error"
        )

        # ======================================================
        # 6️⃣ Respuesta final
        # ======================================================
        return {
            "status": "ok" if codigo and codigo < 300 else "error",
            "tipo_envio": tipo_envio,
            "codigo_meta": codigo,
            "respuesta_api": respuesta if not (codigo and codigo < 300) else None,
            "telefono": telefono,
            "message_id_meta": message_id_meta,
            "ventana_24h_abierta": ventana_abierta
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(
            f"Error enviando invitación para creador_id={data.creador_id}"
        )

        # ======================================================
        # 7️⃣ Guardar trazabilidad del error si es posible
        # ======================================================
        try:
            if telefono:
                guardar_mensaje_nuevo(
                    telefono=telefono,
                    contenido=contenido_guardado or f"ERROR EN ENVÍO DE INVITACIÓN: {str(e)}",
                    direccion="enviado",
                    tipo="template" if tipo_envio == "plantilla" else "texto",
                    message_id_meta=None,
                    estado="error"
                )
        except Exception as e2:
            logger.exception(
                f"No se pudo guardar el error en mensajes_whatsapp: {e2}"
            )

        raise HTTPException(
            status_code=500,
            detail=f"Error enviando mensaje de invitación: {str(e)}"
        )

class AgendamientoUpdateIn(BaseModel):
    inicio: datetime
    fin: Optional[datetime] = None
    timezone: Optional[str] = None

class LinkAgendamientoOut(BaseModel):
    token: str
    url: AnyUrl
    expiracion: datetime

class CrearLinkAgendamientoIn(BaseModel):
    creador_id: int
    responsable_id: int
    minutos_validez: int = 60          # vigencia del token
    duracion_minutos: int = 60         # duración estimada de la cita
    tipo_agendamiento: Literal["LIVE", "ENTREVISTA"] = Field(
        default="ENTREVISTA",
        description="Tipo de cita: 'LIVE' para prueba TikTok LIVE o 'ENTREVISTA' con asesor."
    )

@router.post("/api/agendamientos/aspirante/enviar", response_model=LinkAgendamientoOut)
def enviar_link_agendamiento_aspirante(
    data: CrearLinkAgendamientoIn,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    """
    Envía un link de agendamiento al aspirante.
    - Mensaje simple si ventana 24h abierta
    - Template si ventana cerrada
    """

    with get_connection_context() as conn:
        cur = conn.cursor()

        # 1️⃣ Obtener datos del aspirante
        cur.execute(
            """
            SELECT COALESCE(nickname, nombre_real) AS nombre, telefono
            FROM creadores
            WHERE id = %s
            """,
            (data.creador_id,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "El aspirante no existe.")

        nombre_creador, telefono = row
        if not telefono:
            raise HTTPException(400, "El aspirante no tiene teléfono registrado.")

        # 2️⃣ Actualizar estado según tipo_agendamiento
        nuevo_estado_id = None
        if data.tipo_agendamiento == "ENTREVISTA":
            nuevo_estado_id = 8
        elif data.tipo_agendamiento == "LIVE":
            nuevo_estado_id = 5

        if nuevo_estado_id:
            cur.execute(
                """
                UPDATE perfil_creador
                SET id_chatbot_estado = %s,
                    actualizado_en = NOW()
                WHERE creador_id = %s
                """,
                (nuevo_estado_id, data.creador_id)
            )

        conn.commit()

    # 3️⃣ Construir URL del agendador
    tenant_key = current_tenant.get() or "test"
    subdominio = tenant_key if tenant_key != "public" else "test"

    url = (
        f"https://{subdominio}.talentum-manager.com/agendar"
        f"?creador_id={data.creador_id}"
        f"&tipo={data.tipo_agendamiento}"
        f"&duracion={data.duracion_minutos}"
        f"&responsable_id={data.responsable_id}"
    )

    # 4️⃣ Datos comunes
    cuenta = obtener_cuenta_por_subdominio(tenant_key)
    business_name = cuenta.get("business_name", "la agencia")

    titulo_cita = (
        "tu prueba TikTok LIVE"
        if data.tipo_agendamiento == "LIVE"
        else "tu entrevista con un asesor"
    )

    # 5️⃣ Detectar ventana 24h
    ventana_abierta = obtener_status_24hrs(telefono)

    # 6️⃣ Enviar WhatsApp
    try:
        if not ventana_abierta:
            mensaje = (
                f"Hola {nombre_creador} 👋\n\n"
                f"Queremos continuar tu proceso con *{business_name}*.\n\n"
                f"📅 Agenda {titulo_cita} aquí:\n"
                f"{url}\n\n"
                f"⏱️ Duración estimada: {data.duracion_minutos} minutos.\n"
                "Selecciona el horario que prefieras. Si necesitas cambiar la cita, contáctanos."
            )

            enviar_mensaje(telefono, mensaje)

        else:
            enviar_plantilla_generica_parametros(
                token=cuenta["access_token"],
                phone_number_id=cuenta["phone_number_id"],
                numero_destino=telefono,
                nombre_plantilla="agendar_cita_general",
                codigo_idioma="es_CO",
                parametros=[
                    nombre_creador or "creador",
                    business_name,
                    titulo_cita,
                    url,
                    str(data.duracion_minutos),
                ],
                body_vars_count=5
            )

    except Exception as e:
        logger.exception(
            "❌ Error enviando link de agendamiento (creador_id=%s): %s",
            data.creador_id, e
        )

    # 7️⃣ Respuesta API
    return LinkAgendamientoOut(
        token=None,
        url=url,
        expiracion=None,
    )


@router.post("/api/aspirantes/no_apto/enviar")
def enviar_mensaje_no_apto(
    data: EnviarNoAptoIn,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    with get_connection_context() as conn:
        cur = conn.cursor()

        # 1️⃣ Obtener aspirante
        cur.execute("""
            SELECT id,
                   COALESCE(nickname, nombre_real) AS nombre,
                   telefono
            FROM creadores
            WHERE id = %s;
        """, (data.creador_id,))
        row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Aspirante no encontrado.")

        creador_id, nombre, telefono = row

        if not telefono:
            raise HTTPException(status_code=400, detail="El aspirante no tiene número registrado.")

        # 2️⃣ Marcar estado NO APTO
        cur.execute("""
            UPDATE perfil_creador
            SET id_chatbot_estado = 4
            WHERE creador_id = %s;
        """, (creador_id,))
        conn.commit()

    # 3️⃣ Obtener credenciales WABA
    subdominio = current_tenant.get()
    cuenta = obtener_cuenta_por_subdominio(subdominio)

    if not cuenta:
        raise HTTPException(500, f"No hay credenciales WABA para '{subdominio}'.")

    token = cuenta["access_token"]
    phone_id = cuenta["phone_number_id"]
    business_name = (
        cuenta.get("business_name")
        or cuenta.get("nombre")
        or "nuestra agencia"
    )

    # 4️⃣ Verificar ventana de 24h
    ventana_abierta = obtener_status_24hrs(telefono)

    # ==============================
    # 5️⃣ ENVÍO CONDICIONAL
    # ==============================
    try:
        if not ventana_abierta:
            # 👉 MENSAJE SIMPLE
            mensaje = mensaje_no_apto_simple(nombre, business_name)
            codigo, respuesta = enviar_mensaje(telefono, mensaje)

            return {
                "status": "ok" if codigo < 300 else "error",
                "tipo_envio": "mensaje_simple",
                "codigo_meta": codigo,
                "respuesta_api": respuesta,
                "telefono": telefono
            }

        else:
            # 👉 PLANTILLA
            parametros = [
                nombre or "creador",
                business_name
            ]

            codigo, respuesta = enviar_plantilla_generica_parametros(
                token=token,
                phone_number_id=phone_id,
                numero_destino=telefono,
                nombre_plantilla="no_apto_proceso_v3",
                codigo_idioma="es_CO",
                parametros=parametros,
                body_vars_count=2
            )

            return {
                "status": "ok" if codigo < 300 else "error",
                "tipo_envio": "plantilla",
                "codigo_meta": codigo,
                "respuesta_api": respuesta,
                "telefono": telefono
            }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error enviando mensaje NO APTO: {str(e)}"
        )
