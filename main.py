from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

app = FastAPI()

@app.get("/webhook")
def verify_webhook(hub_mode: str = "", hub_verify_token: str = "", hub_challenge: str = ""):
    if hub_mode == "subscribe":
        return PlainTextResponse(hub_challenge)
    return PlainTextResponse("Modo no válido", status_code=400)
