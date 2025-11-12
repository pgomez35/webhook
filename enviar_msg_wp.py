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
