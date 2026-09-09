"""Plantillas WhatsApp del portal chatbot (JWT chatbot, no Talentum)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from router_chatbot_auth import obtener_agencia_chatbot_actual
from service_chatbot_whatsapp_plantillas import (
    ErrorPlantillaChatbot,
    enviar_plantilla_nueva_conversacion,
    listar_plantillas_agencia_chatbot,
)

router = APIRouter(
    prefix="/api/chatbot/whatsapp",
    tags=["Chatbot WhatsApp"],
)


class EnviarPlantillaChatbotIn(BaseModel):
    model_config = {"extra": "forbid"}
    telefono: str = Field(..., min_length=1, max_length=40)
    codigo: str = Field(..., min_length=1, max_length=512)
    nombre: Optional[str] = Field(default=None, max_length=150)
    usuario_plataforma: Optional[str] = Field(default=None, max_length=100)


def _http_desde_error(exc: ErrorPlantillaChatbot) -> HTTPException:
    return HTTPException(status_code=exc.http_status, detail=exc.detail)


@router.get("/plantillas")
def listar_plantillas_whatsapp_chatbot(
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    """Plantillas de la WABA de la agencia autenticada. Sin tokens."""
    try:
        plantillas = listar_plantillas_agencia_chatbot(int(agencia["id"]))
    except ErrorPlantillaChatbot as exc:
        raise _http_desde_error(exc) from exc
    return {"plantillas": plantillas}


@router.post("/plantillas/enviar")
def enviar_plantilla_whatsapp_chatbot(
    data: EnviarPlantillaChatbotIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    """Inicia o reanuda una conversación enviando una plantilla aprobada.

    No clasifica el contacto como aspirante/creador. No acepta tenant ni WABA
    desde el cliente: se resuelven desde el JWT.
    """
    try:
        return enviar_plantilla_nueva_conversacion(
            agencia_id=int(agencia["id"]),
            agencia_nombre=str(agencia.get("nombre") or ""),
            telefono=data.telefono,
            codigo=data.codigo,
            nombre=data.nombre,
            usuario_plataforma=data.usuario_plataforma,
        )
    except ErrorPlantillaChatbot as exc:
        raise _http_desde_error(exc) from exc
