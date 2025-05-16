from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

app = FastAPI()


@app.get("/webhook")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    hub_mode = params.get("hub.mode")
    hub_verify_token = params.get("hub.verify_token")
    hub_challenge = params.get("hub.challenge")

    print("Modito:", hub_mode)
    print("Tokencito:", hub_verify_token)
    print("Challenge:", hub_challenge)

    if hub_mode == "subscribe":
        return PlainTextResponse(hub_challenge or "")

    return PlainTextResponse("Modo no válido", status_code=400)
