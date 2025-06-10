import requests

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
    print("📡 Respuesta de la API:", response.text)

    return response.status_code, response.json()



def enviar_plantilla_generica(token: str, phone_number_id: str, numero_destino: str,
                              nombre_plantilla: str, codigo_idioma: str = "es_CO",
                              parametros: list = None):
    """

    """
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
                "parameters": [{"type": "text", "text": str(p)} for p in parametros]
            }
        ]

    response = requests.post(url, headers=headers, json=data)
    return response.status_code, response.json()
