"""
Router administrativo — Chatbot de captación.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

import database_chatbot_captacion as db
from main_auth import obtener_usuario_actual
from schemas_chatbot_captacion import (
    CanalWhatsAppResponse,
    ChatbotAspiranteDetalle,
    ChatbotAspiranteResponse,
    ChatbotAspiranteUpdate,
    ChatbotConfiguracionResponse,
    ChatbotConfiguracionUpdate,
    ChatbotResumenResponse,
    PaginatedResponse,
    PreguntaFrecuente,
    AgenciaChatbotResponse,
)

router = APIRouter(prefix="/api/chatbot-captacion", tags=["Chatbot Captación"])


def _agencia_from_request(request: Request) -> dict:
    tenant_name = (getattr(request.state, "tenant_name", None) or "").strip()
    if not tenant_name:
        raise HTTPException(status_code=400, detail="No se pudo identificar el tenant.")
    return db.resolver_agencia_administrativa(tenant_name)


def _faqs_out(raw) -> list:
    return [PreguntaFrecuente(**f) for f in db.parse_faqs(raw)]


def _config_response(agencia: dict, cfg: dict) -> ChatbotConfiguracionResponse:
    return ChatbotConfiguracionResponse(
        id=cfg["id"],
        agencia=AgenciaChatbotResponse(
            id=agencia["id"],
            nombre=agencia["nombre"],
            codigo=agencia["codigo"],
            estado=agencia["estado"],
        ),
        mensaje_bienvenida=cfg["mensaje_bienvenida"],
        pregunta_usuario=cfg["pregunta_usuario"],
        pregunta_mayor_edad=cfg["pregunta_mayor_edad"],
        pregunta_disponibilidad=cfg["pregunta_disponibilidad"],
        mensaje_aprobado=cfg["mensaje_aprobado"],
        mensaje_no_aprobado=cfg["mensaje_no_aprobado"],
        texto_boton_continuar=cfg["texto_boton_continuar"],
        accion_continuar=cfg["accion_continuar"],
        url_continuar=cfg.get("url_continuar"),
        texto_boton_preguntas=cfg["texto_boton_preguntas"],
        preguntas_frecuentes=_faqs_out(cfg.get("preguntas_frecuentes")),
        mensaje_error=cfg["mensaje_error"],
        activo=bool(cfg.get("activo")),
        created_at=cfg.get("created_at"),
        updated_at=cfg.get("updated_at"),
    )


def _aspirante_response(row: dict) -> ChatbotAspiranteResponse:
    return ChatbotAspiranteResponse(
        id=row["id"],
        telefono=row["telefono"],
        nombre=row.get("nombre"),
        plataforma=row.get("plataforma") or "tiktok",
        usuario_plataforma=row.get("usuario_plataforma"),
        mayor_edad=row.get("mayor_edad"),
        disponibilidad_live=row.get("disponibilidad_live"),
        estado=row.get("estado") or "nuevo",
        etapa_chatbot=row.get("etapa_chatbot") or "inicio",
        cumple_requisitos=row.get("cumple_requisitos"),
        requiere_asesor=bool(row.get("requiere_asesor")),
        observaciones=row.get("observaciones"),
        whatsapp_account_id=row.get("whatsapp_account_id"),
        phone_number_origen=row.get("phone_number_origen"),
        business_name_origen=row.get("business_name_origen"),
        fecha_registro=row.get("fecha_registro"),
        ultima_interaccion=row.get("ultima_interaccion"),
    )


@router.get("/configuracion", response_model=ChatbotConfiguracionResponse)
def get_configuracion(
    request: Request,
    usuario_actual: Any = Depends(obtener_usuario_actual),
):
    agencia = _agencia_from_request(request)
    cfg = db.obtener_configuracion_por_agencia(agencia["id"])
    if not cfg:
        cfg = db.crear_configuracion_default(agencia["id"])
    return _config_response(agencia, cfg)


@router.put("/configuracion", response_model=ChatbotConfiguracionResponse)
def put_configuracion(
    payload: ChatbotConfiguracionUpdate,
    request: Request,
    usuario_actual: Any = Depends(obtener_usuario_actual),
):
    agencia = _agencia_from_request(request)
    existente = db.obtener_configuracion_por_agencia(agencia["id"])
    if not existente:
        db.crear_configuracion_default(agencia["id"])

    data = payload.model_dump()
    cfg = db.actualizar_configuracion(agencia["id"], data)
    return _config_response(agencia, cfg)


@router.get("/canales", response_model=list[CanalWhatsAppResponse])
def get_canales(
    request: Request,
    usuario_actual: Any = Depends(obtener_usuario_actual),
):
    agencia = _agencia_from_request(request)
    rows = db.listar_canales_agencia(agencia["id"])
    return [CanalWhatsAppResponse(**r) for r in rows]


@router.get("/resumen", response_model=ChatbotResumenResponse)
def get_resumen(
    request: Request,
    usuario_actual: Any = Depends(obtener_usuario_actual),
):
    agencia = _agencia_from_request(request)
    return ChatbotResumenResponse(**db.resumen_aspirantes(agencia["id"]))


@router.get("/aspirantes", response_model=PaginatedResponse)
def get_aspirantes(
    request: Request,
    search: Optional[str] = Query(None),
    estado: Optional[str] = Query(None),
    plataforma: Optional[str] = Query(None),
    cumple_requisitos: Optional[bool] = Query(None),
    requiere_asesor: Optional[bool] = Query(None),
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    whatsapp_account_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=10, le=100),
    order: str = Query("fecha_registro_desc"),
    usuario_actual: Any = Depends(obtener_usuario_actual),
):
    agencia = _agencia_from_request(request)

    if whatsapp_account_id is not None:
        if not db.canal_pertenece_agencia(agencia["id"], whatsapp_account_id):
            raise HTTPException(
                status_code=400,
                detail="El canal indicado no pertenece a esta agencia.",
            )

    total, rows = db.listar_aspirantes(
        agencia["id"],
        search=search,
        estado=estado,
        plataforma=plataforma,
        cumple_requisitos=cumple_requisitos,
        requiere_asesor=requiere_asesor,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        whatsapp_account_id=whatsapp_account_id,
        page=page,
        page_size=page_size,
        order=order,
    )
    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        results=[_aspirante_response(r) for r in rows],
    )


@router.get("/aspirantes/{aspirante_id}", response_model=ChatbotAspiranteDetalle)
def get_aspirante_detalle(
    aspirante_id: int,
    request: Request,
    usuario_actual: Any = Depends(obtener_usuario_actual),
):
    agencia = _agencia_from_request(request)
    row = db.obtener_aspirante(agencia["id"], aspirante_id)
    if not row:
        raise HTTPException(status_code=404, detail="Aspirante no encontrado.")
    base = _aspirante_response(row)
    return ChatbotAspiranteDetalle(
        **base.model_dump(),
        agencia_id=row["agencia_id"],
        updated_at=row.get("updated_at"),
    )


@router.patch("/aspirantes/{aspirante_id}", response_model=ChatbotAspiranteDetalle)
def patch_aspirante(
    aspirante_id: int,
    payload: ChatbotAspiranteUpdate,
    request: Request,
    usuario_actual: Any = Depends(obtener_usuario_actual),
):
    agencia = _agencia_from_request(request)
    data = payload.model_dump(exclude_unset=True)
    row = db.actualizar_aspirante_admin(
        agencia["id"],
        aspirante_id,
        estado=data.get("estado"),
        requiere_asesor=data.get("requiere_asesor"),
        observaciones=data.get("observaciones"),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Aspirante no encontrado.")
    base = _aspirante_response(row)
    return ChatbotAspiranteDetalle(
        **base.model_dump(),
        agencia_id=row["agencia_id"],
        updated_at=row.get("updated_at"),
    )
