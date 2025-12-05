import requests

import json

def enviar_mensaje_texto_simple(token: str, numero_id: str, telefono_destino: str, texto: str):
    url = f"https://graph.facebook.com/v19.0/{numero_id}/messages"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    mensaje = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "text",
        "text": {
            "body": texto
        }
    }

    print("📤 Enviando mensaje a:", telefono_destino)
    print("📝 Contenido:", texto)

    response = requests.post(url, headers=headers, json=mensaje)

    print("✅ Código de estado:", response.status_code)

    try:
        respuesta_json = response.json()
    except json.JSONDecodeError:
        respuesta_json = {"error": "Respuesta no válida en formato JSON", "contenido": response.text}

    print("📡 Respuesta de la API:", respuesta_json)

    return response.status_code, respuesta_json

import requests
import base64
import mimetypes

def enviar_audio_base64(token, numero_id, telefono_destino, ruta_audio, mimetype="audio/ogg; codecs=opus"):
    """
    Envía un archivo de audio codificado en base64 a través de la API de WhatsApp.
    """
    import requests
    import os

    # 1. Leer y codificar el archivo
    with open(ruta_audio, "rb") as f:
        audio_bytes = f.read()

    nombre_archivo = os.path.basename(ruta_audio)

    # 2. Subir el archivo a la API de WhatsApp
    url_upload = f"https://graph.facebook.com/v19.0/{numero_id}/media"

    files = {
        'file': (nombre_archivo, audio_bytes, mimetype),
    }
    data = {
        'messaging_product': 'whatsapp',
        'type': 'audio'
    }
    headers = {
        'Authorization': f'Bearer {token}'
    }

    response = requests.post(url_upload, headers=headers, files=files, data=data)

    if response.status_code != 200:
        print("❌ Error al subir el audio:", response.text)
        raise Exception(f"Error al subir el audio: {response.text}")

    media_id = response.json().get("id")
    if not media_id:
        raise Exception("No se recibió media_id tras la subida del audio.")

    # 3. Enviar el audio usando el media_id
    url_send = f"https://graph.facebook.com/v19.0/{numero_id}/messages"

    json_data = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "audio",
        "audio": {
            "id": media_id
        }
    }

    response_send = requests.post(url_send, headers=headers, json=json_data)

    if response_send.status_code != 200:
        print("❌ Error al enviar el audio:", response_send.text)
        raise Exception(f"Error al enviar el audio: {response_send.text}")

    return response_send.status_code, response_send.json()

# def enviar_audio_base64(token, numero_id, telefono_destino, ruta_audio, mimetype="audio/webm"):
#     """
#     Envía un archivo de audio codificado en base64 a través de la API de WhatsApp.
#     """
#     # 1. Leer y codificar el archivo
#     with open(ruta_audio, "rb") as f:
#         audio_bytes = f.read()
#
#     # 2. Subir el archivo a la API de WhatsApp
#     url_upload = f"https://graph.facebook.com/v19.0/{numero_id}/media"
#
#     files = {
#         'file': (ruta_audio.split("/")[-1], audio_bytes, mimetype),
#     }
#     data = {
#         'messaging_product': 'whatsapp',
#         'type': 'audio'
#     }
#     headers = {
#         'Authorization': f'Bearer {token}'
#     }
#
#     response = requests.post(url_upload, headers=headers, files=files, data=data)
#
#     if response.status_code != 200:
#         raise Exception(f"Error al subir el audio: {response.text}")
#
#     media_id = response.json().get("id")
#
#     # 3. Enviar el audio usando el media_id
#     url_send = f"https://graph.facebook.com/v19.0/{numero_id}/messages"
#
#     json_data = {
#         "messaging_product": "whatsapp",
#         "to": telefono_destino,
#         "type": "audio",
#         "audio": {
#             "id": media_id
#         }
#     }
#
#     response_send = requests.post(url_send, headers=headers, json=json_data)
#
#     if response_send.status_code != 200:
#         raise Exception(f"Error al enviar el audio: {response_send.text}")
#
#     return response_send.status_code, response_send.json()

import json
import re
import requests
from typing import List, Tuple, Optional

def _normalize_phone(phone: str) -> str:
    """Devuelve solo dígitos (útil para pasar a Meta o para tu lógica interna)."""
    return re.sub(r'\D', '', phone or "")

def enviar_plantilla_generica_parametros(
    token: str,
    phone_number_id: str,
    numero_destino: str,
    nombre_plantilla: str,
    codigo_idioma: str = "es_CO",
    parametros: Optional[List[str]] = None,
    body_vars_count: Optional[int] = None,
) -> Tuple[int, dict]:

    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    numero_destino_norm = _normalize_phone(numero_destino)
    if not numero_destino_norm:
        raise ValueError("numero_destino inválido o vacío después de normalizar.")

    data = {
        "messaging_product": "whatsapp",
        "to": numero_destino_norm,
        "type": "template",
        "template": {
            "name": nombre_plantilla,
            "language": {"code": codigo_idioma}
        }
    }

    # Construcción de components (si hay parametros)
    if parametros:
        # determinar como dividir parametros entre body y posible url param
        total = len(parametros)
        if body_vars_count is not None:
            if body_vars_count < 0 or body_vars_count > total:
                raise ValueError("body_vars_count fuera de rango.")
            n_body = body_vars_count
        else:
            # por defecto: si hay >=2 parametros -> ultimo es url param; else todo body
            n_body = total - 1 if total >= 2 else total

        body_params = parametros[:n_body]
        extra_params = parametros[n_body:]  # usualmente len(extra_params) == 0 o 1 (url param)

        components = []

        # Componente body
        if body_params:
            components.append({
                "type": "body",
                "parameters": [
                    {"type": "text", "text": str(p)} for p in body_params
                ]
            })

        # Si hay extra_params (p.ej. url param), lo usamos como parámetro del botón URL (index 0)
        if extra_params:
            # solo tomo el primero de extra_params como el que llenará el placeholder del botón
            url_param = extra_params[0]
            components.append({
                "type": "button",
                "sub_type": "url",
                "index": "0",
                "parameters": [
                    {"type": "text", "text": str(url_param)}
                ]
            })

        if components:
            data["template"]["components"] = components

    # Logs
    print("📤 Enviando plantilla:", nombre_plantilla)
    print("📨 A:", numero_destino_norm)
    print(f"🌐 Idioma: {codigo_idioma}")
    print("📦 Data preparada:", json.dumps(data, indent=2, ensure_ascii=False))

    # Petición
    try:
        response = requests.post(url, headers=headers, json=data, timeout=15)
    except requests.RequestException as e:
        print("❌ Error al llamar a la API de Meta:", e)
        return 0, {"error": "request_exception", "detail": str(e)}

    print("✅ Código de estado:", response.status_code)
    try:
        respuesta_json = response.json()
    except json.JSONDecodeError:
        respuesta_json = {"error": "invalid_json", "raw": response.text}

    print("📡 Respuesta de la API:", respuesta_json)
    return response.status_code, respuesta_json




def enviar_plantilla_generica(token: str, phone_number_id: str, numero_destino: str,
                              nombre_plantilla: str, codigo_idioma: str = "es_CO",
                              parametros: list = None):
    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    data = {
        "messaging_product": "whatsapp",
        "to": numero_destino,
        "type": "template",
        "template": {
            "name": nombre_plantilla,
            "language": {
                "code": codigo_idioma
            }
        }
    }

    if parametros:
        data["template"]["components"] = [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": str(p)} for p in parametros
                ]
            }
        ]

    print("📤 Enviando plantilla:", nombre_plantilla)
    print("📨 A:", numero_destino)
    print(f"🌐 Idioma: {codigo_idioma}")
    print("📦 Data:", json.dumps(data, indent=2))

    response = requests.post(url, headers=headers, json=data)

    print("✅ Código de estado:", response.status_code)

    try:
        respuesta_json = response.json()
    except json.JSONDecodeError:
        respuesta_json = {
            "error": "Respuesta no válida en formato JSON",
            "contenido": response.text
        }

    print("📡 Respuesta de la API:", respuesta_json)
    return response.status_code, respuesta_json

import requests
import json

def enviar_botones_Completa(token: str, numero_id: str, telefono_destino: str, texto: str, botones: list):
    url = f"https://graph.facebook.com/v19.0/{numero_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    mensaje = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": texto
            },
            "action": {
                "buttons": []
            }
        }
    }

    # Construir los botones dinámicamente
    for boton in botones:
        mensaje["interactive"]["action"]["buttons"].append({
            "type": "reply",
            "reply": {
                "id": boton["id"],
                "title": boton["title"]
            }
        })

    print("📤 Enviando botones a:", telefono_destino)
    print("📝 Contenido:", mensaje)

    response = requests.post(url, headers=headers, json=mensaje)
    print("✅ Código de estado:", response.status_code)

    try:
        respuesta_json = response.json()
    except json.JSONDecodeError:
        respuesta_json = {"error": "Respuesta no válida en formato JSON", "contenido": response.text}

    print("📡 Respuesta de la API:", respuesta_json)
    return response.status_code, respuesta_json



def enviar_boton_iniciar_Completa(token: str, numero_id: str, telefono_destino: str, texto: str):
    url = f"https://graph.facebook.com/v19.0/{numero_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    mensaje = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": texto
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "iniciar_encuesta",
                            "title": "Iniciar"
                        }
                    }
                ]
            }
        }
    }

    print("📤 Enviando botón a:", telefono_destino)
    print("📝 Contenido:", mensaje)

    response = requests.post(url, headers=headers, json=mensaje)
    print("✅ Código de estado:", response.status_code)

    try:
        respuesta_json = response.json()
    except json.JSONDecodeError:
        respuesta_json = {"error": "Respuesta no válida en formato JSON", "contenido": response.text}

    print("📡 Respuesta de la API:", respuesta_json)
    return response.status_code, respuesta_json


import json
import logging
import requests
from typing import List, Dict

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

MAX_BUTTON_TITLE = 20
MAX_BUTTONS = 3

def _sanitize_title(title: str) -> str:
    if title is None:
        return ""
    t = " ".join(str(title).split())
    if len(t) > MAX_BUTTON_TITLE:
        logger.warning("Título de botón demasiado largo (%d). Se truncará a %d: %s", len(t), MAX_BUTTON_TITLE, t)
        t = t[:MAX_BUTTON_TITLE]
    return t

def enviar_botones_con_iconos_minimal(
    token: str,
    phone_number_id: str,
    telefono_destino: str,
    opciones: List[Dict],  # cada opción: {"id": "opt_1", "emoji": "1️⃣", "label": "Actualizar perfil"}
):
    """
    Envía un mensaje interactivo (reply buttons) con emoji/icono + texto en el título.
    El cuerpo del mensaje será mínimo: "Pulsa una opción." (no menú adicional).
    - opciones: lista de dicts con keys 'id'(str), 'emoji'(str opcional), 'label'(str)
    - usa hasta 3 botones (limitación de la API)
    Retorna (status_code, response_json).
    """
    if not isinstance(opciones, list) or len(opciones) == 0:
        raise ValueError("opciones debe ser una lista no vacía")
    if len(opciones) > MAX_BUTTONS:
        opciones = opciones[:MAX_BUTTONS]

    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    action_buttons = []
    for idx, opt in enumerate(opciones, start=1):
        btn_id = str(opt.get("id") or f"opt_{idx}").strip()
        emoji = str(opt.get("emoji") or "").strip()
        label = str(opt.get("label") or "").strip()
        title_raw = f"{emoji} {label}".strip() if emoji else label
        title = _sanitize_title(title_raw)
        if not btn_id or not title:
            raise ValueError("Cada opción necesita 'id' y 'label' válidos")
        action_buttons.append({"type": "reply", "reply": {"id": btn_id, "title": title}})

    # Cuerpo mínimo tal como pediste
    cuerpo = "Pulsa una opción."

    payload = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": cuerpo},
            "action": {"buttons": action_buttons}
        }
    }

    logger.info("Enviando interactivo (minimal) a %s con botones: %s", telefono_destino, [b["reply"]["title"] for b in action_buttons])
    resp = requests.post(url, headers=headers, json=payload)
    try:
        resp_json = resp.json()
    except Exception:
        resp_json = {"error": "no json", "text": resp.text}
    logger.info("Código: %s, respuesta: %s", resp.status_code, resp_json)
    return resp.status_code, resp_json


def enviar_mensaje_animacion_simple(
    token: str,
    numero_id: str,
    telefono_destino: str,
    animation_url: str = None,
    media_id: str = None,
    caption: str = None,
):
    """
    Envía una animación (GIF/MP4) por WhatsApp Cloud API.
    - Proporciona animation_url (link público) *o* media_id (media previamente subido).
    - caption es opcional (texto que acompaña la animación).
    Retorna (status_code, respuesta_json).
    """
    if not (animation_url or media_id):
        raise ValueError("Se requiere animation_url o media_id")

    url = f"https://graph.facebook.com/v19.0/{numero_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    animation_field = {}
    if media_id:
        animation_field["id"] = media_id
    else:
        animation_field["link"] = animation_url

    if caption:
        animation_field["caption"] = caption

    payload = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "animation",
        "animation": animation_field
    }

    print("📤 Enviando animación a:", telefono_destino)
    if animation_url:
        print("🔗 Link:", animation_url)
    if media_id:
        print("🆔 Media ID:", media_id)
    if caption:
        print("📝 Caption:", caption)

    response = requests.post(url, headers=headers, json=payload)
    print("✅ Código de estado:", response.status_code)

    try:
        respuesta_json = response.json()
    except json.JSONDecodeError:
        respuesta_json = {"error": "Respuesta no válida en formato JSON", "contenido": response.text}

    print("📡 Respuesta de la API:", respuesta_json)
    return response.status_code, respuesta_json


import json
import mimetypes
import os
import requests

GRAPH_API_VERSION = "v19.0"


def upload_media(token: str, phone_number_id: str, file_path: str):
    """
    Sube un fichero (GIF/MP4) local al endpoint /<PHONE_NUMBER_ID>/media de WhatsApp Cloud API.
    Retorna media_id (str) si todo OK.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Fichero no encontrado: {file_path}")

    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        raise ValueError("No se pudo detectar el mime type; especifica una extensión válida (.mp4, .gif)")

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}/media"
    headers = {"Authorization": f"Bearer {token}"}

    with open(file_path, "rb") as fh:
        files = {
            "file": (os.path.basename(file_path), fh, mime_type),
        }
        data = {"messaging_product": "whatsapp"}
        resp = requests.post(url, headers=headers, data=data, files=files)

    try:
        resp_json = resp.json()
    except Exception:
        raise RuntimeError(f"Respuesta no JSON al subir media: {resp.status_code} {resp.text}")

    if resp.status_code != 200:
        raise RuntimeError(f"Error subiendo media: {resp.status_code} {resp_json}")

    # resp_json ejemplo: {"id":"<MEDIA_ID>","mime_type":"video/mp4","sha256":"...", ...}
    media_id = resp_json.get("id")
    if not media_id:
        raise RuntimeError(f"No se devolvió media_id: {resp_json}")

    return media_id


def enviar_mensaje_animacion_con_media_id(token: str, phone_number_id: str, telefono_destino: str, media_id: str, caption: str = None):
    """
    Envía un mensaje tipo 'animation' usando un media_id previamente subido.
    """
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    animation = {"id": media_id}
    if caption:
        animation["caption"] = caption

    payload = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "animation",
        "animation": animation
    }

    resp = requests.post(url, headers=headers, json=payload)
    try:
        resp_json = resp.json()
    except Exception:
        resp_json = {"error": "no json", "text": resp.text}

    return resp.status_code, resp_json