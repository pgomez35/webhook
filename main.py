# ✅ main.py
from fastapi import FastAPI, Request, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import os
import json

from enviar_msg_wp import enviar_mensaje_texto_simple
from buscador import inicializar_busqueda, responder_pregunta
from DataBase import *

# 🔄 Cargar variables de entorno
load_dotenv()
API_KEY = os.getenv("OPENAI_API_KEY")
TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "142848PITUFO")
CHROMA_DIR = "./chroma_faq_openai"

# ⚙️ Inicializar FastAPI
app = FastAPI()

# Configurar CORS para permitir peticiones del frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🧠 Inicializar búsqueda semántica
client, collection = inicializar_busqueda(API_KEY, persist_dir=CHROMA_DIR)

# 📁 Servir archivos de audio
app.mount("/audios", StaticFiles(directory="audios"), name="audios")

# ✅ VERIFICACIÓN DEL WEBHOOK (Facebook Developers)
@app.get("/webhook")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    print("📡 Verificación recibida:", params)

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(challenge or "")
    return PlainTextResponse("Verificación fallida", status_code=403)

# 📩 PROCESAMIENTO DE MENSAJES ENVIADOS AL WEBHOOK
@app.post("/webhook")
async def recibir_mensaje(request: Request):
    try:
        datos = await request.json()
        print("📨 Payload recibido:")
        print(json.dumps(datos, indent=2))

        entrada = datos.get("entry", [{}])[0]
        cambio = entrada.get("changes", [{}])[0]
        valor = cambio.get("value", {})

        mensajes = valor.get("messages")
        if not mensajes:
            print("⚠️ No se encontraron mensajes en el payload.")
            return JSONResponse({"status": "ok", "detalle": "Sin mensajes"}, status_code=200)

        mensaje = mensajes[0]
        telefono = mensaje.get("from")
        mensaje_usuario = mensaje.get("text", {}).get("body")

        if not telefono or not mensaje_usuario:
            print("⚠️ Mensaje incompleto.")
            return JSONResponse({"status": "ok", "detalle": "Mensaje incompleto"}, status_code=200)

        print(f"📥 Mensaje recibido de {telefono}: {mensaje_usuario}")
        guardar_mensaje(telefono, mensaje_usuario, tipo="recibido")

        # 🧠 Buscar respuesta en ChromaDB
        respuesta = responder_pregunta(mensaje_usuario, client, collection)
        print(f"🤖 Respuesta generada: {respuesta}")

        # ✉️ Enviar respuesta por WhatsApp
        codigo, respuesta_api = enviar_mensaje_texto_simple(
            token=TOKEN,
            numero_id=PHONE_NUMBER_ID,
            telefono_destino=telefono,
            texto=respuesta
        )
        guardar_mensaje(telefono, respuesta, tipo="enviado")

        print(f"✅ Código de envío: {codigo}")
        print(f"🛰️ Respuesta API:", respuesta_api)

        return JSONResponse({
            "status": "ok",
            "respuesta": respuesta,
            "codigo_envio": codigo,
            "respuesta_api": respuesta_api
        })

    except Exception as e:
        print("❌ Error procesando mensaje:", e)
        return JSONResponse({"error": str(e)}, status_code=500)

# 📡 API para frontend React
@app.get("/contactos")
def listar_contactos():
    return obtener_contactos()

@app.get("/mensajes/{telefono}")
def listar_mensajes(telefono: str):
    return obtener_mensajes(telefono)

@app.post("/mensajes")
async def api_enviar_mensaje(data: dict):
    telefono = data.get("telefono")
    mensaje = data.get("mensaje")

    # Enviar mensaje por WhatsApp
    codigo, respuesta_api = enviar_mensaje_texto_simple(
        token=TOKEN,
        numero_id=PHONE_NUMBER_ID,
        telefono_destino=telefono,
        texto=mensaje
    )

    # Guardar en base de datos
    guardar_mensaje(telefono, mensaje, tipo="enviado")

    return {
        "status": "ok",
        "mensaje": "Mensaje guardado y enviado",
        "codigo_api": codigo,
        "respuesta_api": respuesta_api
    }

@app.post("/mensajes/audio")
async def api_enviar_audio(telefono: str = Form(...), audio: UploadFile = Form(...)):
    audio_bytes = await audio.read()
    filename = f"{telefono}_{int(datetime.now().timestamp())}.webm"
    ruta = f"audios/{filename}"
    os.makedirs("audios", exist_ok=True)
    with open(ruta, "wb") as f:
        f.write(audio_bytes)
    guardar_mensaje(telefono, f"[Audio guardado: {filename}]", tipo="enviado", es_audio=True)
    return {"status": "ok", "mensaje": "Audio recibido", "archivo": filename}

@app.post("/contactos/nombre")
async def actualizar_nombre(data: dict):
    telefono = data.get("telefono")
    nombre = data.get("nombre")
    if not telefono or not nombre:
        return JSONResponse({"error": "Faltan parámetros"}, status_code=400)

    actualizado = actualizar_nombre_contacto(telefono, nombre)
    if actualizado:
        return {"status": "ok", "mensaje": "Nombre actualizado"}
    else:
        return JSONResponse({"error": "No se pudo actualizar"}, status_code=500)

@app.delete("/mensajes/{telefono}")
async def borrar_mensajes(telefono: str):
    eliminado = eliminar_mensajes(telefono)
    if eliminado:
        return {"status": "ok", "mensaje": f"Mensajes de {telefono} eliminados"}
    else:
        return JSONResponse({"error": "No se pudieron eliminar los mensajes"}, status_code=500)
