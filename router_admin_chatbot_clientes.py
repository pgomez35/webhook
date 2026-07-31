"""
API administrativa — clientes del producto chatbot.
Solo rol Admin de Talentum Manager.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from DataBase import es_admin
from main_auth import obtener_usuario_actual
import database_admin_chatbot_clientes as db
from schemas_chatbot_captacion import (
    AgenciaChatbotResponse,
    ChatbotConfiguracionResponse,
    ChatbotConfiguracionUpdate,
    PreguntaFrecuente,
    RecursoBienvenida,
)

logger = logging.getLogger("uvicorn.error")

router = APIRouter(
    prefix="/api/admin/chatbot",
    tags=["Admin Chatbot Clientes"],
)


def require_admin(usuario: dict = Depends(obtener_usuario_actual)) -> dict:
    if not es_admin(usuario):
        raise HTTPException(status_code=403, detail="Se requiere rol Admin")
    return usuario


# ---------- Schemas ----------

class AgenciaAdminOut(BaseModel):
    id: int
    nombre: str
    codigo: str
    estado: Optional[str] = None
    usuario_login: Optional[str] = None
    login_activo: Optional[bool] = None
    debe_cambiar_clave: Optional[bool] = None
    diagnostico_habilitado: bool = False
    ultimo_login: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    whatsapp_account_id: Optional[int] = None
    waba_business_name: Optional[str] = None
    waba_phone_number: Optional[str] = None
    waba_phone_number_id: Optional[str] = None
    waba_status: Optional[str] = None
    waba_product_type: Optional[str] = None
    waba_principal: Optional[bool] = None
    waba_relacion_activa: Optional[bool] = None
    total_aspirantes: Optional[int] = 0
    requieren_asesor: Optional[int] = 0


class AgenciaCreateIn(BaseModel):
    model_config = {"extra": "forbid"}
    nombre: str = Field(..., min_length=1, max_length=150)
    codigo: str = Field(..., min_length=2, max_length=80)
    usuario_login: Optional[str] = Field(None, max_length=120)
    password_temporal: Optional[str] = Field(None, min_length=8, max_length=200)
    estado: str = "activa"
    login_activo: bool = True
    debe_cambiar_clave: bool = True
    whatsapp_account_id: Optional[int] = None

    @field_validator("usuario_login")
    @classmethod
    def norm_usuario(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        t = str(v).strip().lower()
        return t or None


class AgenciaUpdateIn(BaseModel):
    model_config = {"extra": "forbid"}
    nombre: Optional[str] = Field(None, min_length=1, max_length=150)
    codigo: Optional[str] = Field(None, min_length=2, max_length=80)
    estado: Optional[str] = None
    usuario_login: Optional[str] = Field(None, max_length=120)
    password_temporal: Optional[str] = Field(None, min_length=8, max_length=200)
    login_activo: Optional[bool] = None
    debe_cambiar_clave: Optional[bool] = None
    diagnostico_habilitado: Optional[bool] = None

    @field_validator("usuario_login")
    @classmethod
    def norm_usuario(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        t = str(v).strip().lower()
        return t or None


class CredencialesIn(BaseModel):
    model_config = {"extra": "forbid"}
    usuario_login: str = Field(..., min_length=1, max_length=120)
    password_temporal: str = Field(..., min_length=8, max_length=200)
    login_activo: bool = True
    debe_cambiar_clave: bool = True

    @field_validator("usuario_login")
    @classmethod
    def norm_usuario(cls, v: str) -> str:
        return str(v or "").strip().lower()


class RestablecerPasswordIn(BaseModel):
    model_config = {"extra": "forbid"}
    password_temporal: str = Field(..., min_length=8, max_length=200)


class LoginActivoIn(BaseModel):
    model_config = {"extra": "forbid"}
    login_activo: bool


class VincularWabaIn(BaseModel):
    model_config = {"extra": "forbid"}
    whatsapp_account_id: int


class WabaDisponibleOut(BaseModel):
    id: int
    business_name: Optional[str] = None
    phone_number: Optional[str] = None
    phone_number_id: Optional[str] = None
    status: Optional[str] = None
    product_type: Optional[str] = None
    vinculada_agencia_id: Optional[int] = None
    vinculada_agencia_nombre: Optional[str] = None
    vinculada_agencia_codigo: Optional[str] = None


def _http_from_value_error(e: ValueError) -> HTTPException:
    msg = str(e)
    code = 409 if ("ya" in msg.lower() or "duplic" in msg.lower() or "vinculad" in msg.lower()) else 400
    return HTTPException(status_code=code, detail=msg)


# ---------- Endpoints ----------

@router.get("/agencias", response_model=List[AgenciaAdminOut])
def listar_agencias(_admin: dict = Depends(require_admin)):
    return db.listar_agencias_admin()


@router.get("/agencias/{agencia_id}", response_model=AgenciaAdminOut)
def obtener_agencia(agencia_id: int, _admin: dict = Depends(require_admin)):
    row = db.obtener_agencia_admin(agencia_id)
    if not row:
        raise HTTPException(status_code=404, detail="Agencia no encontrada")
    return row


@router.get("/agencias/{agencia_id}/resumen")
def resumen_agencia(agencia_id: int, _admin: dict = Depends(require_admin)):
    """Resumen de soporte: estado config + totales aspirantes (sin edición operativa)."""
    row = db.obtener_resumen_agencia_admin(agencia_id)
    if not row:
        raise HTTPException(status_code=404, detail="Agencia no encontrada")
    return row


@router.post("/agencias", response_model=AgenciaAdminOut)
def crear_agencia(payload: AgenciaCreateIn, admin: dict = Depends(require_admin)):
    try:
        row = db.crear_agencia_completa(
            nombre=payload.nombre,
            codigo=payload.codigo,
            usuario_login=payload.usuario_login,
            password_temporal=payload.password_temporal,
            estado=payload.estado,
            login_activo=payload.login_activo,
            debe_cambiar_clave=payload.debe_cambiar_clave,
            whatsapp_account_id=payload.whatsapp_account_id,
        )
    except ValueError as e:
        raise _http_from_value_error(e) from e
    logger.info(
        "[ADMIN-CHATBOT] crear agencia_id=%s admin_id=%s",
        row.get("id"),
        admin.get("id"),
    )
    return row


@router.put("/agencias/{agencia_id}", response_model=AgenciaAdminOut)
def actualizar_agencia(
    agencia_id: int,
    payload: AgenciaUpdateIn,
    admin: dict = Depends(require_admin),
):
    data = payload.model_dump(exclude_unset=True)
    try:
        row = db.actualizar_agencia_admin(agencia_id, **data)
    except ValueError as e:
        raise _http_from_value_error(e) from e
    logger.info(
        "[ADMIN-CHATBOT] actualizar agencia_id=%s admin_id=%s",
        agencia_id,
        admin.get("id"),
    )
    return row


@router.put("/agencias/{agencia_id}/credenciales", response_model=AgenciaAdminOut)
def configurar_credenciales(
    agencia_id: int,
    payload: CredencialesIn,
    admin: dict = Depends(require_admin),
):
    try:
        row = db.actualizar_agencia_admin(
            agencia_id,
            usuario_login=payload.usuario_login,
            password_temporal=payload.password_temporal,
            login_activo=payload.login_activo,
            debe_cambiar_clave=payload.debe_cambiar_clave,
        )
    except ValueError as e:
        raise _http_from_value_error(e) from e
    logger.info(
        "[ADMIN-CHATBOT] credenciales agencia_id=%s admin_id=%s",
        agencia_id,
        admin.get("id"),
    )
    return row


@router.post("/agencias/{agencia_id}/restablecer-password", response_model=AgenciaAdminOut)
def restablecer_password(
    agencia_id: int,
    payload: RestablecerPasswordIn,
    admin: dict = Depends(require_admin),
):
    try:
        db.restablecer_password_admin(agencia_id, payload.password_temporal)
        row = db.obtener_agencia_admin(agencia_id)
    except ValueError as e:
        raise _http_from_value_error(e) from e
    if not row:
        raise HTTPException(status_code=404, detail="Agencia no encontrada")
    logger.info(
        "[ADMIN-CHATBOT] restablecer-password agencia_id=%s admin_id=%s",
        agencia_id,
        admin.get("id"),
    )
    return row


@router.patch("/agencias/{agencia_id}/login-activo", response_model=AgenciaAdminOut)
def toggle_login_activo(
    agencia_id: int,
    payload: LoginActivoIn,
    admin: dict = Depends(require_admin),
):
    try:
        row = db.set_login_activo(agencia_id, payload.login_activo)
    except ValueError as e:
        raise _http_from_value_error(e) from e
    logger.info(
        "[ADMIN-CHATBOT] login_activo=%s agencia_id=%s admin_id=%s",
        payload.login_activo,
        agencia_id,
        admin.get("id"),
    )
    return row


@router.put("/agencias/{agencia_id}/waba", response_model=AgenciaAdminOut)
def vincular_waba(
    agencia_id: int,
    payload: VincularWabaIn,
    admin: dict = Depends(require_admin),
):
    try:
        row = db.vincular_waba_admin(agencia_id, payload.whatsapp_account_id)
    except ValueError as e:
        raise _http_from_value_error(e) from e
    logger.info(
        "[ADMIN-CHATBOT] vincular waba agencia_id=%s whatsapp_account_id=%s admin_id=%s",
        agencia_id,
        payload.whatsapp_account_id,
        admin.get("id"),
    )
    return row


@router.get(
    "/agencias/{agencia_id}/configuracion",
    response_model=ChatbotConfiguracionResponse,
)
def obtener_config(agencia_id: int, _admin: dict = Depends(require_admin)):
    agencia = db.obtener_agencia_admin(agencia_id)
    if not agencia:
        raise HTTPException(status_code=404, detail="Agencia no encontrada")
    try:
        row = db.obtener_configuracion_admin(agencia_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _config_response(row, agencia)


@router.put(
    "/agencias/{agencia_id}/configuracion",
    response_model=ChatbotConfiguracionResponse,
)
def actualizar_config(
    agencia_id: int,
    payload: ChatbotConfiguracionUpdate,
    admin: dict = Depends(require_admin),
):
    agencia = db.obtener_agencia_admin(agencia_id)
    if not agencia:
        raise HTTPException(status_code=404, detail="Agencia no encontrada")
    data = payload.model_dump()
    try:
        row = db.actualizar_configuracion_admin(agencia_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    logger.info(
        "[ADMIN-CHATBOT] config actualizada agencia_id=%s admin_id=%s",
        agencia_id,
        admin.get("id"),
    )
    return _config_response(row, agencia)


@router.get("/wabas-disponibles", response_model=List[WabaDisponibleOut])
def wabas_disponibles(_admin: dict = Depends(require_admin)):
    return db.listar_wabas_chatbot_disponibles()


def _config_response(row: dict, agencia: dict) -> ChatbotConfiguracionResponse:
    faqs_raw = row.get("preguntas_frecuentes") or []
    recursos_raw = row.get("recursos_bienvenida") or []
    if not isinstance(faqs_raw, list):
        faqs_raw = []
    if not isinstance(recursos_raw, list):
        recursos_raw = []
    return ChatbotConfiguracionResponse(
        id=int(row["id"]),
        agencia=AgenciaChatbotResponse(
            id=int(agencia["id"]),
            nombre=agencia.get("nombre") or "",
            codigo=agencia.get("codigo") or "",
            estado=agencia.get("estado") or "activa",
        ),
        mensaje_bienvenida=row.get("mensaje_bienvenida") or "",
        pregunta_usuario=row.get("pregunta_usuario") or "",
        pregunta_mayor_edad=row.get("pregunta_mayor_edad") or "",
        pregunta_disponibilidad=row.get("pregunta_disponibilidad") or "",
        mensaje_aprobado=row.get("mensaje_aprobado") or "",
        mensaje_no_aprobado=row.get("mensaje_no_aprobado") or "",
        texto_boton_continuar=row.get("texto_boton_continuar") or "",
        accion_continuar=row.get("accion_continuar") or "asesor",
        url_continuar=row.get("url_continuar"),
        texto_boton_preguntas=row.get("texto_boton_preguntas") or "",
        preguntas_frecuentes=[
            PreguntaFrecuente(**f) for f in faqs_raw if isinstance(f, dict)
        ],
        recursos_bienvenida=[
            RecursoBienvenida(**r) for r in recursos_raw if isinstance(r, dict)
        ],
        mensaje_error=row.get("mensaje_error") or "",
        activo=bool(row.get("activo", True)),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )
