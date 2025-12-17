import requests

# Función para enviar un mensaje con botones interactivos
def enviar_menu_interactivo(token, recipient, estado):
    """
    Genera y envía un menú interactivo a un usuario dependiendo del estado del aspirante.

    :param token: Token de autenticación de WhatsApp Cloud API.
    :param recipient: Número de teléfono del destinatario (incluyendo el código de país, ej. +57).
    :param estado: Estado del aspirante que define el menú (ej: 'post_encuesta_inicial').
    """
    url = f"https://graph.facebook.com/v19.0/{recipient}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Menús y mensajes dependiendo del estado
    menus = {
        "post_encuesta_inicial": {
            "header": "Explora la información sobre el proceso de Prestige Agency.",
            "buttons": [
                {"id": "proceso_incorporacion", "title": "Proceso de Incorporación en Prestige Agency"},
                {"id": "beneficios_agencia", "title": "Beneficios de pertenecer a nuestra Agencia"},
                {"id": "rol_creador", "title": "Rol de Creador de Contenido"}
            ]
        },
        "solicitud_agendamiento_tiktok": {
            "header": "Consulta tu Diagnóstico Inicial y coordina tu prueba TikTok LIVE.",
            "buttons": [
                {"id": "dx_inicial", "title": "Mi Dx Inicial"},
                {"id": "agenda_tiktok", "title": "Agenda Prueba tikTok LIVE"}
            ]
        },
        "solicitud_agendamiento_entrevista": {
            "header": "Consulta tu Diagnóstico Completo y coordina tu prueba de Entrevista.",
            "buttons": [
                {"id": "dx_completo", "title": "Mi Dx Completo"},
                {"id": "agenda_entrevista", "title": "Agenda Prueba Entrevista"}
            ]
        }
    }

    # Validar si el estado existe en el diccionario de menús
    if estado not in menus:
        print(f"Estado '{estado}' no tiene un menú asociado.")
        return

    # Generar el cuerpo del mensaje
    menu = menus[estado]
    body_text = menu["header"]
    buttons = [{"type": "reply", "reply": {"id": btn["id"], "title": btn["title"]}} for btn in menu["buttons"]]

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": buttons}
        }
    }

    # Realizar la solicitud HTTP POST
    response = requests.post(url, headers=headers, json=payload)
    
    # Manejo de respuesta
    if response.status_code == 200:
        print(f"Menú enviado exitosamente al destinatario: {recipient}")
    else:
        print(f"Error al enviar menú: {response.json()}")


# Ejemplo de ejecución
if __name__ == "__main__":
    # Configurar token y otros datos
    TOKEN = "<ACCESS_TOKEN>"  # Reemplaza con tu token válido de la API
    RECIPIENT = "+573153638069"  # Número de teléfono del destinatario incluyendo código de país
    ESTADO = "post_encuesta_inicial"  # Indica el estado del menú que quieres enviar

    # Enviar el menú interactivo
    enviar_menu_interactivo(TOKEN, RECIPIENT, ESTADO)