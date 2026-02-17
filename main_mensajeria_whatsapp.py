import datetime
import os
import subprocess
from typing import Optional

from fastapi import APIRouter, Form, UploadFile, requests, HTTPException,Request
from starlette.staticfiles import StaticFiles

from DataBase import obtener_usuario_id_por_telefono, paso_limite_24h, guardar_mensaje, guardar_mensaje_nuevo, \
    obtener_mensajes, obtener_contactos_db, obtener_contactos_db_nueva
from enviar_msg_wp import enviar_plantilla_generica, enviar_mensaje_texto_simple, enviar_audio_base64
from tenant import current_token, current_phone_id, current_business_name, current_tenant
from fastapi.responses import JSONResponse, PlainTextResponse


import requests

from utils import AUDIO_DIR, subir_audio_cloudinary
from starlette.responses import StreamingResponse

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
    import os, subprocess
    from datetime import datetime

    TOKEN = current_token.get()
    PHONE_NUMBER_ID = current_phone_id.get()
    TENANT = current_tenant.get()

    if not TOKEN or not PHONE_NUMBER_ID:
        return {"status": "error", "mensaje": "Credenciales no disponibles"}

    if not TENANT:
        return {"status": "error", "mensaje": "Tenant no disponible"}

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
            contenido_guardar = documento.filename
            media_url_guardar = f"whatsapp_media_id:{media_id}"
        else:
            contenido_guardar = documento.filename
            media_url_guardar = url_cloudinary

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
