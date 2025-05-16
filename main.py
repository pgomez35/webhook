from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse
import os

app = FastAPI()

# ✅ Token de verificación para Facebook Developers
VERIFY_TOKEN = "142848PITUFO"  # Cámbialo por el que uses en Facebook Developers

@app.get("/webhook")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    hub_mode = params.get("hub.mode")
    hub_verify_token = params.get("hub.verify_token")
    hub_challenge = params.get("hub.challenge")

    print("Modo:", hub_mode)
    print("Token recibido:", hub_verify_token)

    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge or "")

    return PlainTextResponse("Verificación fallida", status_code=403)

@app.post("/webhook")
async def receive_message(request: Request):
    body = await request.json()
    print("📥 Webhook recibido:", body)

    # Aquí podrías manejar los mensajes entrantes, por ejemplo:
    if "entry" in body:
        for entry in body["entry"]:
            for messaging_event in entry.get("messaging", []):
                sender_id = messaging_event["sender"]["id"]
                if "message" in messaging_event:
                    message_text = messaging_event["message"].get("text")
                    print(f"Mensaje de {sender_id}: {message_text}")
                    # Aquí puedes luego enviar respuesta usando la Graph API

    return JSONResponse({"status": "ok"})
