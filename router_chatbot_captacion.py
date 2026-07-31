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
    AgenciaChatbotResponse,
    AgenciaMensajeSeleccionUpdate,
    CanalWhatsAppResponse,
    ChatbotAspiranteDetalle,
    ChatbotAspiranteResponse,
    ChatbotAspiranteReiniciarFlujoIn,
    ChatbotAspiranteUpdate,
    ChatbotConfiguracionActivoIn,
    ChatbotConfiguracionCreate,
    ChatbotConfiguracionDuplicarIn,
    ChatbotConfiguracionReordenarIn,
    ChatbotConfiguracionResponse,
    ChatbotConfiguracionResumen,
    ChatbotConfiguracionUpdate,
    ChatbotResumenResponse,
    MediaEliminarRequest,
    MediaEliminarResponse,
    MediaFirmaRequest,
    MediaFirmaResponse,
    PaginatedResponse,
    PlataformaResponse,
    PreguntaFrecuente,
    RecursoBienvenida,
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


def _agencia_response(agencia: dict) -> AgenciaChatbotResponse:
    # Refrescar campos de agencia si no vienen en el dict del JWT
    if (
        "mensaje_seleccion_configuracion" not in agencia
        or "seleccion_por_palabras_activa" not in agencia
        or "diagnostico_habilitado" not in agencia
    ):
        full = db.obtener_agencia_por_id(int(agencia["id"])) or {}
        agencia = {**agencia, **full}
    return AgenciaChatbotResponse(
        id=agencia["id"],
        nombre=agencia["nombre"],
        codigo=agencia["codigo"],
        estado=agencia["estado"],
        mensaje_seleccion_configuracion=agencia.get("mensaje_seleccion_configuracion"),
        seleccion_por_palabras_activa=bool(
            agencia.get("seleccion_por_palabras_activa", False)
        ),
        diagnostico_habilitado=bool(agencia.get("diagnostico_habilitado", False)),
    )


def _config_response(agencia: dict, cfg: dict) -> ChatbotConfiguracionResponse:
    return ChatbotConfiguracionResponse(
        id=cfg["id"],
        agencia=_agencia_response(agencia),
        codigo=cfg.get("codigo") or "tiktok",
        nombre=cfg.get("nombre") or "Configuración",
        plataforma_codigo=cfg.get("plataforma_codigo") or "tiktok",
        plataforma_nombre=cfg.get("plataforma_nombre"),
        texto_opcion=cfg.get("texto_opcion") or cfg.get("nombre") or "Opción",
        es_predeterminada=bool(cfg.get("es_predeterminada")),
        orden=int(cfg.get("orden") or 1),
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


def _config_resumen(cfg: dict) -> ChatbotConfiguracionResumen:
    return ChatbotConfiguracionResumen(
        id=cfg["id"],
        codigo=cfg.get("codigo") or "",
        nombre=cfg.get("nombre") or "",
        plataforma_codigo=cfg.get("plataforma_codigo") or "",
        plataforma_nombre=cfg.get("plataforma_nombre"),
        texto_opcion=cfg.get("texto_opcion") or "",
        es_predeterminada=bool(cfg.get("es_predeterminada")),
        orden=int(cfg.get("orden") or 1),
        activo=bool(cfg.get("activo")),
        updated_at=cfg.get("updated_at"),
    )


def _aspirante_response(row: dict) -> ChatbotAspiranteResponse:
    estado_diag = row.get("estado_diagnostico")
    if not estado_diag:
        estado_diag = "evaluado" if row.get("evaluado_at") else "pendiente"
    return ChatbotAspiranteResponse(
        id=row["id"],
        telefono=row["telefono"],
        nombre=row.get("nombre"),
        plataforma=row.get("plataforma"),
        plataforma_codigo=row.get("plataforma_codigo"),
        usuario_plataforma=row.get("usuario_plataforma"),
        chatbot_configuracion_id=row.get("chatbot_configuracion_id"),
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
        estado_diagnostico=estado_diag,
        resultado_global=row.get("resultado_global"),
        evaluado_at=row.get("evaluado_at"),
        evaluado_por=row.get("evaluado_por"),
    )


def _http_from_value_error(e: ValueError) -> HTTPException:
    msg = str(e)
    lower = msg.lower()
    if "no encontrada" in lower:
        return HTTPException(status_code=404, detail=msg)
    if "otra agencia" in lower:
        return HTTPException(status_code=403, detail=msg)
    if "desactivada" in lower or "inactiva" in lower:
        return HTTPException(status_code=400, detail=msg)
    if "ya existe" in lower or "código" in lower or "codigo" in lower:
        return HTTPException(status_code=409, detail=msg)
    return HTTPException(status_code=400, detail=msg)


# ---------- Plataformas ----------

@router.get("/plataformas", response_model=list[PlataformaResponse])
def get_plataformas(agencia: dict = Depends(obtener_agencia_chatbot_actual)):
    _ = agencia  # auth only
    return [PlataformaResponse(**r) for r in db.listar_plataformas_activas()]


# ---------- Agencia: mensaje de selección ----------

@router.get("/agencia", response_model=AgenciaChatbotResponse)
def get_agencia(agencia: dict = Depends(obtener_agencia_chatbot_actual)):
    full = db.obtener_agencia_por_id(int(agencia["id"]))
    if not full:
        raise HTTPException(status_code=404, detail="Agencia no encontrada")
    return _agencia_response(full)


@router.put("/agencia/mensaje-seleccion", response_model=AgenciaChatbotResponse)
def put_mensaje_seleccion(
    payload: AgenciaMensajeSeleccionUpdate,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    try:
        full = db.actualizar_mensaje_seleccion_configuracion(
            int(agencia["id"]),
            payload.mensaje_seleccion_configuracion,
            seleccion_por_palabras_activa=payload.seleccion_por_palabras_activa,
        )
    except ValueError as e:
        raise _http_from_value_error(e) from e
    logger.info(
        "[CHATBOT-CONFIG] mensaje_seleccion actualizado agencia_id=%s",
        agencia["id"],
    )
    return _agencia_response(full)


# ---------- Configuraciones (multi) ----------

@router.get("/configuraciones", response_model=list[ChatbotConfiguracionResumen])
def list_configuraciones(agencia: dict = Depends(obtener_agencia_chatbot_actual)):
    """
    Lista configuraciones de la agencia autenticada.
    No crea registros automáticamente: una agencia nueva puede quedar sin configs
    hasta que elija su primera plataforma en el portal.
    """
    rows = db.listar_configuraciones(int(agencia["id"]))
    return [_config_resumen(r) for r in rows]


@router.post("/configuraciones", response_model=ChatbotConfiguracionResponse)
def create_configuracion(
    payload: ChatbotConfiguracionCreate,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    try:
        cfg = db.crear_configuracion(int(agencia["id"]), payload.model_dump(mode="json"))
    except ValueError as e:
        raise _http_from_value_error(e) from e
    return _config_response(agencia, cfg)


@router.put(
    "/configuraciones/reordenar",
    response_model=list[ChatbotConfiguracionResumen],
)
def reordenar_configuraciones(
    payload: ChatbotConfiguracionReordenarIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    ordenes = [item.model_dump() for item in payload.ordenes]
    try:
        rows = db.reordenar_configuraciones(int(agencia["id"]), ordenes)
    except ValueError as e:
        raise _http_from_value_error(e) from e
    return [_config_resumen(r) for r in rows]


@router.get(
    "/configuraciones/{configuracion_id}",
    response_model=ChatbotConfiguracionResponse,
)
def get_configuracion_by_id(
    configuracion_id: int,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg = db.obtener_configuracion_por_id(int(agencia["id"]), configuracion_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Configuración no encontrada")
    return _config_response(agencia, cfg)


@router.put(
    "/configuraciones/{configuracion_id}",
    response_model=ChatbotConfiguracionResponse,
)
def put_configuracion_by_id(
    configuracion_id: int,
    payload: ChatbotConfiguracionUpdate,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    data = payload.model_dump(mode="json", exclude_unset=False)
    n_recibidos = len(data.get("recursos_bienvenida") or [])
    logger.info(
        "[CHATBOT-CONFIG] put agencia_id=%s configuracion_id=%s "
        "recursos_recibidos=%s activo=%s",
        agencia["id"],
        configuracion_id,
        n_recibidos,
        data.get("activo"),
    )
    try:
        # actualizar_configuracion hace UPDATE ... RETURNING (incluye activo)
        # en una sola transacción; agencia_id solo desde JWT (WHERE id + agencia_id).
        cfg = db.actualizar_configuracion(
            int(agencia["id"]),
            data,
            configuracion_id=configuracion_id,
        )
    except ValueError as e:
        raise _http_from_value_error(e) from e

    # Validar solo el valor de RETURNING (ya parseado), nunca una 2ª consulta/sesión.
    n_persistidos = len(cfg.get("recursos_bienvenida") or [])
    if n_recibidos != n_persistidos:
        logger.error(
            "[CHATBOT-CONFIG] mismatch RETURNING agencia_id=%s cfg=%s recibidos=%s persistidos=%s",
            agencia["id"],
            configuracion_id,
            n_recibidos,
            n_persistidos,
        )
        raise HTTPException(
            status_code=500,
            detail="No se pudieron persistir los recursos de bienvenida",
        )
    logger.info(
        "[CHATBOT-CONFIG] put ok agencia_id=%s configuracion_id=%s activo=%s",
        agencia["id"],
        configuracion_id,
        cfg.get("activo"),
    )
    return _config_response(agencia, cfg)


@router.post(
    "/configuraciones/{configuracion_id}/duplicar",
    response_model=ChatbotConfiguracionResponse,
)
def duplicar_configuracion(
    configuracion_id: int,
    payload: ChatbotConfiguracionDuplicarIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    try:
        cfg = db.duplicar_configuracion(
            int(agencia["id"]),
            configuracion_id,
            nuevo_codigo=payload.codigo,
            nuevo_nombre=payload.nombre,
        )
    except ValueError as e:
        raise _http_from_value_error(e) from e
    return _config_response(agencia, cfg)


@router.patch(
    "/configuraciones/{configuracion_id}/activo",
    response_model=ChatbotConfiguracionResponse,
)
def patch_configuracion_activo(
    configuracion_id: int,
    payload: ChatbotConfiguracionActivoIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    try:
        cfg = db.set_configuracion_activo(
            int(agencia["id"]),
            configuracion_id,
            payload.activo,
        )
    except ValueError as e:
        raise _http_from_value_error(e) from e
    return _config_response(agencia, cfg)


# ---------- Compatibilidad: una config (primera / por defecto) ----------

@router.get("/configuracion", response_model=ChatbotConfiguracionResponse)
def get_configuracion(agencia: dict = Depends(obtener_agencia_chatbot_actual)):
    cfg = db.obtener_configuracion_por_agencia(agencia["id"])
    if not cfg:
        cfg = db.crear_configuracion_default(agencia["id"])
        cfg = db.obtener_configuracion_por_id(agencia["id"], int(cfg["id"])) or cfg
    return _config_response(agencia, cfg)


@router.put("/configuracion", response_model=ChatbotConfiguracionResponse)
def put_configuracion(
    payload: ChatbotConfiguracionUpdate,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    existente = db.obtener_configuracion_por_agencia(agencia["id"])
    if not existente:
        creado = db.crear_configuracion_default(agencia["id"])
        configuracion_id = int(creado["id"])
    else:
        configuracion_id = int(existente["id"])

    data = payload.model_dump(mode="json")
    try:
        cfg = db.actualizar_configuracion(
            agencia["id"], data, configuracion_id=configuracion_id
        )
    except ValueError as e:
        raise _http_from_value_error(e) from e
    return _config_response(agencia, cfg)


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
    configuracion_id: Optional[int] = Query(
        None, description="ID de configuración dueña del recurso"
    ),
):
    """
    Elimina un asset de Cloudinary si pertenece a la agencia del JWT.

    No modifica recursos_bienvenida: el JSONB solo cambia con el PUT de
    configuración (evita vaciar el recurso antes de persistir el reemplazo).
    """
    agencia_id = int(agencia["id"])
    public_id = payload.public_id

    if not public_id_pertenece_agencia(public_id, agencia_id):
        raise HTTPException(
            status_code=403,
            detail="El recurso no pertenece a esta agencia",
        )

    # Validación opcional de resource_type si el asset sigue referenciado.
    if configuracion_id is not None:
        cfg = db.obtener_configuracion_por_id(agencia_id, configuracion_id)
    else:
        cfg = db.obtener_configuracion_por_agencia(agencia_id)
    if cfg:
        recursos = db.parse_recursos_bienvenida(cfg.get("recursos_bienvenida"))
        en_config = [r for r in recursos if (r.get("public_id") or "").strip() == public_id]
        if en_config:
            rt_cfg = (en_config[0].get("resource_type") or "").strip().lower()
            if rt_cfg and rt_cfg != payload.resource_type:
                raise HTTPException(
                    status_code=400,
                    detail="resource_type no coincide con el recurso guardado",
                )

    destruir_recurso_cloudinary(
        public_id=public_id,
        resource_type=payload.resource_type,
        invalidate=True,
    )

    return MediaEliminarResponse(
        ok=True,
        public_id=public_id,
        eliminado_cloudinary=True,
        eliminado_config=False,
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
    estado_diagnostico: Optional[str] = Query(
        None, description="pendiente | evaluado"
    ),
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
        estado_diagnostico=estado_diagnostico,
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
    Limpia chatbot_configuracion_id y campos de respuesta.
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
