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

def enviar_plantilla_generica(token: str, phone_number_id: str, numero_destino: str,
                              nombre_plantilla: str, codigo_idioma: str = "es_CO",
                              parametros: list = None):

    def construir_payload(idioma):
        payload = {
            "messaging_product": "whatsapp",
            "to": numero_destino,
            "type": "template",
            "template": {
                "name": nombre_plantilla,
                "language": {
                    "code": idioma
                }
            }
        }

        if parametros:
            payload["template"]["components"] = [
                {
                    "type": "body",
                    "parameters": [
                        {
                            "type": "text",
                            "text": str(p)
                        } for p in parametros
                    ]
                }
            ]

        return payload

    idiomas_fallback = ["es_MX", "es_CO", "es_ES", "en_US"]

    for idioma in idiomas_fallback:
        data = construir_payload(idioma)

        print("📤 Enviando plantilla:", nombre_plantilla)
        print("📨 A:", numero_destino)
        print(f"🌐 Idioma: {idioma}")
        print("📦 Data:", json.dumps(data, indent=2))

        response = requests.post(
            f"https://graph.facebook.com/v19.0/{phone_number_id}/messages",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json=data
        )

        print("✅ Código de estado:", response.status_code)

        try:
            respuesta_json = response.json()
        except json.JSONDecodeError:
            respuesta_json = {
                "error": "Respuesta no válida en formato JSON",
                "contenido": response.text
            }

        print("📡 Respuesta de la API:", respuesta_json)

        if response.status_code == 404 and respuesta_json.get("error", {}).get("code") == 132001:
            print(f"⚠️ La plantilla no existe en el idioma {idioma}. Probando siguiente idioma...")
            continue
        else:
            return response.status_code, respuesta_json

    return 404, {
        "error": f"No se pudo enviar la plantilla '{nombre_plantilla}' en ningún idioma disponible"
    }


