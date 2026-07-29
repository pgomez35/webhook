import requests

import json


def enviar_mensaje_texto_simple(
    token: str,
    numero_id: str,
    telefono_destino: str,
    texto: str
):
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

    # ---------------------------------------------------------
    # LOGS SEGUROS
    # ---------------------------------------------------------
    telefono_safe = (
        telefono_destino[:4] + "****" + telefono_destino[-2:]
        if len(telefono_destino) >= 6
        else telefono_destino
    )

    preview_texto = (
        texto[:120] + "..."
        if len(texto) > 120
        else texto
    )

    print(f"📤 Enviando mensaje a: {telefono_safe}")
    print(f"📝 Preview mensaje: {preview_texto}")

    try:
        response = requests.post(
            url,
            headers=headers,
            json=mensaje,
            timeout=15
        )

        print(f"✅ Código de estado: {response.status_code}")

        try:
            respuesta_json = response.json()

        except json.JSONDecodeError:
            respuesta_json = {
                "error": "Respuesta no válida en formato JSON",
                "contenido": response.text[:300]
            }

        # ---------------------------------------------------------
        # LOG RESPONSE SEGURA
        # ---------------------------------------------------------
        response_preview = str(respuesta_json)

        if len(response_preview) > 500:
            response_preview = response_preview[:500] + "..."

        print(f"📡 Respuesta API: {response_preview}")

        return response.status_code, respuesta_json

    except requests.Timeout:
        print("⏳ Timeout enviando mensaje WhatsApp")

        return 408, {
            "error": "Timeout enviando mensaje"
        }

    except requests.RequestException as e:
        print(f"❌ Error HTTP enviando mensaje: {e}")

        return 500, {
            "error": str(e)
        }


def enviar_mensaje_texto_simpleV0(token: str, numero_id: str, telefono_destino: str, texto: str):
    url = f"https://graph.facebook.com/v19.0/{numero_id}/messages"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    mensaje = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "text",
        "text": {"body": texto}
    }

    print("📤 Enviando mensaje a:", telefono_destino)
    print("📝 Contenido:", texto[:120])

    response = requests.post(url, headers=headers, json=mensaje)

    print("✅ Código de estado:", response.status_code)

    try:
        respuesta_json = response.json()
    except:
        respuesta_json = {"contenido": response.text}

    print("📡 Respuesta API:", respuesta_json)

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

def enviar_mensaje_interactivo(
    token: str,
    numero_id: str,
    telefono_destino: str,
    interactive: dict,
):
    """
    Envía un mensaje interactivo de WhatsApp (button, list, etc.).
  """
    url = f"https://graph.facebook.com/v19.0/{numero_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    mensaje = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "interactive",
        "interactive": interactive,
    }

    telefono_safe = (
        telefono_destino[:4] + "****" + telefono_destino[-2:]
        if len(telefono_destino) >= 6
        else telefono_destino
    )
    print(f"📤 Enviando interactivo a: {telefono_safe}")

    try:
        response = requests.post(url, headers=headers, json=mensaje, timeout=15)
        try:
            respuesta_json = response.json()
        except json.JSONDecodeError:
            respuesta_json = {
                "error": "Respuesta no válida en formato JSON",
                "contenido": response.text[:300],
            }
        return response.status_code, respuesta_json
    except requests.Timeout:
        return 408, {"error": "Timeout enviando mensaje interactivo"}
    except requests.RequestException as e:
        return 500, {"error": str(e)}


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
    """
    Normaliza título de botón reply.
    No trunca: rechaza vacío o > MAX_BUTTON_TITLE.
    """
    t = " ".join(str(title or "").split())
    if not t:
        raise ValueError("El título del botón no puede estar vacío")
    if len(t) > MAX_BUTTON_TITLE:
        raise ValueError(
            f"El título del botón no puede superar {MAX_BUTTON_TITLE} caracteres "
            f"(límite de WhatsApp). Actual: {len(t)}"
        )
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


def _graph_api_version() -> str:
    return (os.getenv("GRAPH_API_VERSION") or GRAPH_API_VERSION or "v19.0").strip()


def _enmascarar_url_media(url: Optional[str]) -> str:
    if not url:
        return ""
    texto = str(url).strip()
    base = texto.split("?", 1)[0]
    if len(base) <= 48:
        return base
    return base[:32] + "..." + base[-12:]


def _enviar_media_whatsapp(
    token: str,
    numero_id: str,
    telefono_destino: str,
    tipo_media: str,
    media_url: Optional[str] = None,
    media_id: Optional[str] = None,
    caption: Optional[str] = None,
    filename: Optional[str] = None,
):
    """
    Envía video o document a WhatsApp Cloud API.
    Exige exactamente uno de: media_url | media_id.
    """
    tipo = (tipo_media or "").strip().lower()
    if tipo not in ("video", "document"):
        raise ValueError("tipo_media debe ser 'video' o 'document'")

    tiene_url = bool(media_url and str(media_url).strip())
    tiene_id = bool(media_id and str(media_id).strip())
    if tiene_url == tiene_id:
        raise ValueError("Debe indicar exactamente uno de: media_url o media_id")

    if tiene_url:
        url_limpia = str(media_url).strip()
        if not url_limpia.startswith("https://"):
            raise ValueError("media_url debe comenzar por https://")

    telefono = _normalize_phone(telefono_destino)
    if not telefono:
        raise ValueError("telefono_destino inválido")

    telefono_safe = (
        telefono[:3] + "****" + telefono[-2:] if len(telefono) >= 6 else "****"
    )

    media_obj: dict = {}
    if tiene_url:
        media_obj["link"] = str(media_url).strip()
    else:
        media_obj["id"] = str(media_id).strip()

    if caption is not None:
        cap = str(caption).strip()
        if cap:
            media_obj["caption"] = cap

    if tipo == "document" and filename:
        media_obj["filename"] = str(filename).strip()

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": telefono,
        "type": tipo,
        tipo: media_obj,
    }

    api_url = f"https://graph.facebook.com/{_graph_api_version()}/{numero_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    print(f"[WA] Enviando {tipo} a: {telefono_safe}")
    if tiene_url:
        print(f"[WA] Media URL: {_enmascarar_url_media(media_url)}")
    else:
        print("[WA] Media ID presente (no se imprime)")

    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=30)
    except requests.Timeout:
        return 504, {"error": "timeout", "detail": "Timeout al enviar media a Meta"}
    except requests.RequestException as e:
        return 500, {"error": "request_error", "detail": str(e)}

    try:
        respuesta_json = response.json()
    except json.JSONDecodeError:
        respuesta_json = {
            "error": "Respuesta no válida en formato JSON",
            "contenido": (response.text or "")[:300],
        }

    ok = response.status_code in (200, 201)
    print(
        f"[WA] Media {tipo} status={response.status_code} ok={ok} tel={telefono_safe}"
    )
    return response.status_code, respuesta_json


def enviar_video_whatsapp(
    token: str,
    numero_id: str,
    telefono_destino: str,
    video_url: Optional[str] = None,
    media_id: Optional[str] = None,
    caption: Optional[str] = None,
):
    """Envía un video normal (type=video). No usa animation."""
    return _enviar_media_whatsapp(
        token=token,
        numero_id=numero_id,
        telefono_destino=telefono_destino,
        tipo_media="video",
        media_url=video_url,
        media_id=media_id,
        caption=caption,
    )


def enviar_documento_whatsapp(
    token: str,
    numero_id: str,
    telefono_destino: str,
    documento_url: Optional[str] = None,
    media_id: Optional[str] = None,
    caption: Optional[str] = None,
    filename: str = "documento.pdf",
):
    """Envía un documento PDF (type=document)."""
    return _enviar_media_whatsapp(
        token=token,
        numero_id=numero_id,
        telefono_destino=telefono_destino,
        tipo_media="document",
        media_url=documento_url,
        media_id=media_id,
        caption=caption,
        filename=filename or "documento.pdf",
    )


def _resumen_error_meta(body: Optional[dict]) -> str:
    if not isinstance(body, dict):
        return ""
    err = body.get("error")
    if not isinstance(err, dict):
        return str(body.get("error") or "")[:120]
    code = err.get("code")
    title = err.get("title") or err.get("error_user_title") or ""
    msg = err.get("message") or err.get("error_user_msg") or ""
    return f"code={code} title={title!r} detail={msg!r}"[:240]


def subir_media_whatsapp(token: str, phone_number_id: str, ruta_archivo: str, mime: str):
    """
    Sube un archivo a WhatsApp Cloud API (multipart/form-data).
    POST /{version}/{phone_number_id}/media

    Misma estrategia usada en mensajería para PDF (media_id).
    Retorna (status_code, json_body). El media_id viene en body['id'].
    """
    version = _graph_api_version()
    url = f"https://graph.facebook.com/{version}/{phone_number_id}/media"
    headers = {"Authorization": f"Bearer {token}"}

    with open(ruta_archivo, "rb") as f:
        files = {"file": (os.path.basename(ruta_archivo), f, mime)}
        data = {"messaging_product": "whatsapp"}
        try:
            response = requests.post(
                url, headers=headers, files=files, data=data, timeout=60
            )
        except requests.Timeout:
            return 504, {"error": "timeout", "detail": "Timeout al subir media a Meta"}
        except requests.RequestException as e:
            return 500, {"error": "request_error", "detail": str(e)}

    try:
        body = response.json()
    except json.JSONDecodeError:
        body = {
            "error": "Respuesta no válida en formato JSON",
            "contenido": (response.text or "")[:300],
        }
    return response.status_code, body


def enviar_documento_id(
    token,
    numero_id,
    telefono_destino,
    media_id,
    filename,
    caption=None,
):
    """
    Envía un documento usando media_id (document.id).
    Misma estrategia usada en mensajería WhatsApp.
    Omite caption si está vacío; no envía null.
    """
    version = _graph_api_version()
    url = f"https://graph.facebook.com/{version}/{numero_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    telefono = _normalize_phone(telefono_destino)
    document = {
        "id": media_id,
        "filename": filename,
    }
    cap = (caption or "").strip() if caption is not None else ""
    if cap:
        document["caption"] = cap

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": telefono,
        "type": "document",
        "document": document,
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
    except requests.Timeout:
        return 504, {"error": "timeout", "detail": "Timeout al enviar documento a Meta"}
    except requests.RequestException as e:
        return 500, {"error": "request_error", "detail": str(e)}

    try:
        body = response.json()
    except json.JSONDecodeError:
        body = {
            "error": "Respuesta no válida en formato JSON",
            "contenido": (response.text or "")[:300],
        }
    return response.status_code, body


def enviar_documento_pdf_via_media_id_desde_url(
    token: str,
    numero_id: str,
    telefono_destino: str,
    documento_url: str,
    filename: str = "documento.pdf",
    caption: Optional[str] = None,
):
    """
    PDF desde Cloudinary (secure_url) → temp → subir_media_whatsapp →
    media_id → enviar_documento_id (document.id).

    Reutiliza la estrategia de mensajería (no document.link).
    El archivo temporal se elimina siempre en finally.
    """
    import tempfile

    url = (documento_url or "").strip()
    if not url.startswith("https://"):
        return 400, {"error": "url_invalida", "detail": "documento_url debe ser https"}

    nombre = (filename or "documento.pdf").strip() or "documento.pdf"
    if not nombre.lower().endswith(".pdf"):
        nombre = f"{nombre}.pdf"

    caption_envio = (caption or "").strip() or None
    tmp_path = None
    try:
        try:
            with requests.get(url, stream=True, timeout=(10, 60)) as resp:
                http_dl = resp.status_code
                ctype_raw = (resp.headers.get("Content-Type") or "").strip()
                ctype = ctype_raw.split(";")[0].strip().lower()
                if http_dl != 200:
                    print(
                        f"[CHATBOT-PDF] descarga Cloudinary fallida "
                        f"HTTP={http_dl} content_type={ctype_raw!r}"
                    )
                    return http_dl, {
                        "error": "cloudinary_download_failed",
                        "detail": f"HTTP {http_dl}",
                        "content_type": ctype_raw,
                    }

                fd, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix="wa_pdf_")
                os.close(fd)
                size = 0
                with open(tmp_path, "wb") as out:
                    for chunk in resp.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        out.write(chunk)
                        size += len(chunk)

                if size <= 0:
                    print("[CHATBOT-PDF] descarga Cloudinary vacía")
                    return 400, {
                        "error": "cloudinary_empty",
                        "detail": "Contenido vacío",
                        "content_type": ctype_raw,
                    }

                es_pdf = "application/pdf" in ctype
                if not es_pdf:
                    with open(tmp_path, "rb") as chk:
                        magic = chk.read(5)
                    if magic.startswith(b"%PDF") and ctype in (
                        "",
                        "application/octet-stream",
                        "binary/octet-stream",
                    ):
                        es_pdf = True
                        ctype_raw = "application/pdf"
                    else:
                        print(
                            f"[CHATBOT-PDF] content_type inválido={ctype_raw!r} "
                            f"size={size}"
                        )
                        return 415, {
                            "error": "content_type_invalido",
                            "detail": ctype_raw or "(vacío)",
                            "size": size,
                        }

                print(
                    f"[CHATBOT-PDF] descarga Cloudinary HTTP=200 "
                    f"content_type={ctype_raw or 'application/pdf'} size={size}"
                )
        except requests.Timeout:
            print("[CHATBOT-PDF] timeout descarga Cloudinary")
            return 504, {"error": "timeout", "detail": "Timeout descarga Cloudinary"}
        except requests.RequestException as e:
            print(f"[CHATBOT-PDF] error descarga Cloudinary: {type(e).__name__}")
            return 500, {"error": "download_error", "detail": type(e).__name__}

        print("[CHATBOT-PDF] subida a Meta iniciada")
        status_up, body_up = subir_media_whatsapp(
            token=token,
            phone_number_id=numero_id,
            ruta_archivo=tmp_path,
            mime="application/pdf",
        )
        if status_up not in (200, 201):
            print(
                f"[CHATBOT-PDF] subida Meta falló HTTP={status_up} "
                f"meta={_resumen_error_meta(body_up)}"
            )
            return status_up, body_up if isinstance(body_up, dict) else {
                "error": "upload_failed",
                "body": body_up,
            }

        media_id = body_up.get("id") if isinstance(body_up, dict) else None
        if not media_id:
            print(f"[CHATBOT-PDF] subida sin media_id HTTP={status_up}")
            return 502, {"error": "media_id_ausente", "detail": "sin id"}

        mid = str(media_id)
        mid_safe = mid[:6] + "..." + mid[-4:] if len(mid) > 12 else mid[:4] + "..."
        print(f"[CHATBOT-PDF] media_id obtenido={mid_safe}")

        status_send, body_send = enviar_documento_id(
            token=token,
            numero_id=numero_id,
            telefono_destino=telefono_destino,
            media_id=str(media_id),
            filename=nombre,
            caption=caption_envio,
        )
        wamid = None
        if isinstance(body_send, dict):
            msgs = body_send.get("messages")
            if isinstance(msgs, list) and msgs and isinstance(msgs[0], dict):
                wamid = msgs[0].get("id")
        if status_send in (200, 201):
            print(f"[CHATBOT-PDF] documento enviado wamid={wamid}")
        else:
            print(
                f"[CHATBOT-PDF] envío falló HTTP={status_send} "
                f"meta={_resumen_error_meta(body_send)}"
            )
        return status_send, body_send
    finally:
        if tmp_path:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError as e:
                print(f"[CHATBOT-PDF] no se pudo borrar temp: {type(e).__name__}")

