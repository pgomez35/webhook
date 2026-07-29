"""
Router administrativo — Chatbot de captación.
La agencia se resuelve exclusivamente desde el JWT (scope=chatbot_frontend).
X-Tenant-Name / tenant_name / hostname no autorizan datos.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

import database_chatbot_captacion as db
from chatbot_captacion_logic import ETAPA_INICIO
from router_chatbot_auth import obtener_agencia_chatbot_actual
from schemas_chatbot_captacion import (
    CanalWhatsAppResponse,
    ChatbotAspiranteDetalle,
    ChatbotAspiranteResponse,
    ChatbotAspiranteReiniciarFlujoIn,
    ChatbotAspiranteUpdate,
    ChatbotConfiguracionResponse,
    ChatbotConfiguracionUpdate,
    ChatbotResumenResponse,
    MediaEliminarRequest,
    MediaEliminarResponse,
    MediaFirmaRequest,
    MediaFirmaResponse,
    PaginatedResponse,
    PreguntaFrecuente,
    RecursoBienvenida,
    AgenciaChatbotResponse,
)
from service_cloudinary_chatbot import (
    destruir_recurso_cloudinary,
    generar_firma_carga,
    public_id_pertenece_agencia,
)

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/api/chatbot-captacion", tags=["Chatbot Captación"])


def _faqs_out(raw) -> list:
    return [PreguntaFrecuente(**f) for f in db.parse_faqs(raw)]


def _recursos_out(raw) -> list:
    parsed = db.parse_recursos_bienvenida(raw)
    out = []
    for item in parsed:
        try:
            out.append(RecursoBienvenida(**item))
        except Exception as e:
            # No silenciar: diagnosticar sin exponer URLs completas
            pid = str((item or {}).get("public_id") or "")[:40]
            tipo = (item or {}).get("tipo")
            logger.warning(
                "[CHATBOT-CONFIG] recurso omitido en respuesta tipo=%s public_id_prefix=%s causa=%s",
                tipo,
                pid,
                type(e).__name__,
            )
    if parsed and not out:
        logger.error(
            "[CHATBOT-CONFIG] %s recursos en DB pero 0 válidos al serializar respuesta",
            len(parsed),
        )
    return out


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
        recursos_bienvenida=_recursos_out(cfg.get("recursos_bienvenida")),
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
        etapa_chatbot=row.get("etapa_chatbot") or ETAPA_INICIO,
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
def get_configuracion(agencia: dict = Depends(obtener_agencia_chatbot_actual)):
    cfg = db.obtener_configuracion_por_agencia(agencia["id"])
    if not cfg:
        cfg = db.crear_configuracion_default(agencia["id"])
    n = len(db.parse_recursos_bienvenida(cfg.get("recursos_bienvenida")))
    logger.info(
        "[CHATBOT-CONFIG] get agencia_id=%s recursos_en_db=%s",
        agencia["id"],
        n,
    )
    resp = _config_response(agencia, cfg)
    logger.info(
        "[CHATBOT-CONFIG] get agencia_id=%s recursos_devueltos=%s",
        agencia["id"],
        len(resp.recursos_bienvenida or []),
    )
    return resp


@router.put("/configuracion", response_model=ChatbotConfiguracionResponse)
def put_configuracion(
    payload: ChatbotConfiguracionUpdate,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    existente = db.obtener_configuracion_por_agencia(agencia["id"])
    if not existente:
        db.crear_configuracion_default(agencia["id"])

    data = payload.model_dump(mode="json")
    n_recibidos = len(data.get("recursos_bienvenida") or [])
    logger.info(
        "[CHATBOT-CONFIG] put agencia_id=%s recursos_recibidos=%s",
        agencia["id"],
        n_recibidos,
    )

    try:
        cfg = db.actualizar_configuracion(agencia["id"], data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    n_persistidos = len(db.parse_recursos_bienvenida(cfg.get("recursos_bienvenida")))
    logger.info(
        "[CHATBOT-CONFIG] put agencia_id=%s recursos_persistidos=%s",
        agencia["id"],
        n_persistidos,
    )
    if n_recibidos != n_persistidos:
        logger.error(
            "[CHATBOT-CONFIG] mismatch persistencia agencia_id=%s recibidos=%s persistidos=%s",
            agencia["id"],
            n_recibidos,
            n_persistidos,
        )
        raise HTTPException(
            status_code=500,
            detail="No se pudieron persistir los recursos de bienvenida",
        )

    resp = _config_response(agencia, cfg)
    logger.info(
        "[CHATBOT-CONFIG] put agencia_id=%s recursos_devueltos=%s",
        agencia["id"],
        len(resp.recursos_bienvenida or []),
    )
    return resp


@router.post("/media/firma", response_model=MediaFirmaResponse)
def post_media_firma(
    payload: MediaFirmaRequest,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    """
    Firma temporal Cloudinary. agencia_id solo desde JWT.
    No acepta folder/public_id/resource_type del frontend.
    """
    firma = generar_firma_carga(agencia_id=agencia["id"], tipo=payload.tipo)
    return MediaFirmaResponse(**firma)


@router.delete("/media", response_model=MediaEliminarResponse)
def delete_media(
    payload: MediaEliminarRequest,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    """
    Elimina un asset de Cloudinary si pertenece a la agencia del JWT.
    Si está en recursos_bienvenida, también lo quita del JSONB.
    """
    agencia_id = int(agencia["id"])
    public_id = payload.public_id

    if not public_id_pertenece_agencia(public_id, agencia_id):
        raise HTTPException(
            status_code=403,
            detail="El recurso no pertenece a esta agencia",
        )

    cfg = db.obtener_configuracion_por_agencia(agencia_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Configuración no encontrada")

    recursos = db.parse_recursos_bienvenida(cfg.get("recursos_bienvenida"))
    en_config = [r for r in recursos if (r.get("public_id") or "").strip() == public_id]

    if en_config:
        rt_cfg = (en_config[0].get("resource_type") or "").strip().lower()
        if rt_cfg and rt_cfg != payload.resource_type:
            raise HTTPException(
                status_code=400,
                detail="resource_type no coincide con el recurso guardado",
            )
    else:
        # Limpieza de temporales / post-reemplazo: solo bajo prefijo de la agencia
        # (ya verificado arriba). No permite borrar assets de otra agencia.
        pass

    destruir_recurso_cloudinary(
        public_id=public_id,
        resource_type=payload.resource_type,
        invalidate=True,
    )

    eliminado_config = False
    if en_config:
        nuevos = [r for r in recursos if (r.get("public_id") or "").strip() != public_id]
        db.actualizar_recursos_bienvenida(agencia_id, nuevos)
        eliminado_config = True

    return MediaEliminarResponse(
        ok=True,
        public_id=public_id,
        eliminado_cloudinary=True,
        eliminado_config=eliminado_config,
    )


@router.get("/canales", response_model=list[CanalWhatsAppResponse])
def get_canales(agencia: dict = Depends(obtener_agencia_chatbot_actual)):
    rows = db.listar_canales_agencia(agencia["id"])
    return [CanalWhatsAppResponse(**r) for r in rows]


@router.get("/resumen", response_model=ChatbotResumenResponse)
def get_resumen(agencia: dict = Depends(obtener_agencia_chatbot_actual)):
    return ChatbotResumenResponse(**db.resumen_aspirantes(agencia["id"]))


@router.get("/aspirantes", response_model=PaginatedResponse)
def get_aspirantes(
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
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
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
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
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
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
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


@router.post(
    "/aspirantes/{aspirante_id}/reiniciar-flujo",
    response_model=ChatbotAspiranteDetalle,
)
def reiniciar_flujo_aspirante(
    aspirante_id: int,
    payload: ChatbotAspiranteReiniciarFlujoIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    """
    Reinicia el flujo conversacional (etapa_chatbot=inicio).
    No altera telefono, agencia_id, whatsapp_account_id ni fecha_registro.
    """
    row = db.reiniciar_flujo_aspirante(
        agencia["id"],
        aspirante_id,
        limpiar_respuestas=bool(payload.limpiar_respuestas),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Aspirante no encontrado.")
    base = _aspirante_response(row)
    return ChatbotAspiranteDetalle(
        **base.model_dump(),
        agencia_id=row["agencia_id"],
        updated_at=row.get("updated_at"),
    )
