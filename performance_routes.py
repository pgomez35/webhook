"""
Endpoints HTTP de performance de creadores.
"""
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query

from performance_core import (
    DEBUG_PERFORMANCE_IA,
    ESTADOS_ACCION_VALIDOS,
    ESTADOS_ALERTA_VALIDOS,
    NIVELES_ALERTA_VALIDOS,
    NIVELES_RENDIMIENTO,
    OPENAI_CONFIG_CLAVE,
    OPENAI_MODEL_DEFAULT,
    PRIORIDADES_VALIDAS,
    TIPOS_ACCION_SUGERIDOS,
    AccionEstadoUpdate,
    AccionPerformanceCreate,
    AccionPerformanceUpdate,
    ActualizarArquetipoCreadorRequest,
    AlertaPerformanceCreate,
    AlertaPerformanceUpdate,
    AplicarRecomendacionRequest,
    DashboardPerformanceResponse,
    GenerarAccionesIARequest,
    GenerarAlertasScoreIARequest,
    GenerarRecomendacionesIARequest,
    GenerarSeguimientoIARequest,
    IARequest,
    RecomendacionPerformanceCreate,
    RecomendacionPerformanceUpdate,
    ResolverAlertaRequest,
    ResumenPerformanceCreate,
    ScorePerformanceCreate,
    SeguimientoConAccionesCreate,
    SeguimientoPerformanceCreate,
    SeguimientoPerformanceUpdate,
    _formatear_lista_seguimientos,
    _formatear_seguimiento_respuesta,
    calcular_score_basico,
    construir_perfil_estrategico,
    construir_resumen_basico,
    detectar_alertas_basicas,
    execute_no_return,
    execute_returning,
    fetch_all,
    fetch_one,
    generar_recomendaciones_basicas,
    insertar_accion,
    insertar_alerta,
    insertar_recomendacion,
    insertar_resumen,
    insertar_score,
    model_to_dict,
    normalizar_lower,
    normalizar_texto_parrafos,
    obtener_arquetipo_creador,
    obtener_arquetipos_activos,
    obtener_categoria_creador,
    obtener_contexto_ia_manager,
    obtener_contexto_performance,
    obtener_creador,
    obtener_contexto_recomendaciones_ia_compacto,
    obtener_datos_tablas_debug_ia,
    obtener_manager_id_por_creador,
    obtener_perfil_respuestas,
    obtener_score_actual,
    openai_api_key_configurada,
    openai_disponible,
    openai_habilitado_en_agencia,
    openai_json_completion,
    update_row_dynamic,
    validar_valor_en_set,
)
from performance_ia import (
    _aplicar_pulido_final_recomendaciones,
    _normalizar_resultado_recomendaciones_ia,
    _reforzar_recomendaciones_metricas_y_perfil_si_falta,
    _pulir_recomendacion_item,
    prompt_acciones_manager,
    prompt_alertas_score_ia,
    prompt_diagnostico_performance,
    prompt_generar_seguimiento,
    prompt_recomendaciones_manager,
    prompt_recomendaciones_manager_v3,
)

load_dotenv()

router = APIRouter()

# =========================================================
# ENDPOINTS — ESTADO OPENAI
# =========================================================

@router.get("/api/creadores/performance/openai/estado")
def estado_openai_performance():
    return {
        "ok": True,
        "clave_config": OPENAI_CONFIG_CLAVE,
        "habilitado_agencia": openai_habilitado_en_agencia(),
        "api_key_configurada": openai_api_key_configurada(),
        "puede_usarse": openai_disponible(),
        "modelo": OPENAI_MODEL_DEFAULT,
    }


# =========================================================
# ENDPOINTS — DASHBOARD / CONTEXTO
# =========================================================

@router.get(
    "/api/creadores/performance/{creador_id}/dashboard",
    response_model=DashboardPerformanceResponse,
)
def dashboard_performance_creador(
    creador_id: int,
    id_reporte: Optional[int] = Query(default=None),
):
    contexto = obtener_contexto_performance(creador_id, id_reporte=id_reporte)
    return {
        "ok": True,
        **contexto,
    }


@router.get("/api/creadores/performance/{creador_id}/contexto")
def contexto_performance_creador(
    creador_id: int,
    id_reporte: Optional[int] = Query(default=None),
    incluir_perfil: bool = Query(default=True),
):
    return {
        "ok": True,
        "contexto": obtener_contexto_performance(
            creador_id,
            id_reporte=id_reporte,
            incluir_perfil=incluir_perfil,
        ),
    }


@router.get("/api/creadores/performance/{creador_id}/metricas")
def metricas_performance_creador(creador_id: int):
    creador = obtener_creador(creador_id)
    if not creador:
        raise HTTPException(status_code=404, detail="Creador no encontrado")

    reportes = fetch_all(
        """
        SELECT *
        FROM creadores_reporte_integral
        WHERE creador_id = %s
        ORDER BY periodo_fin DESC, fecha_carga DESC, id_reporte DESC
        """,
        (creador_id,),
    )

    return {
        "ok": True,
        "creador_id": creador_id,
        "reportes": reportes,
    }


@router.get("/api/creadores/performance/{creador_id}/metas")
def metas_performance_creador(creador_id: int):
    metas = fetch_all(
        """
        SELECT *
        FROM creadores_metas_mensuales
        WHERE creador_id = %s
        ORDER BY periodo_fin DESC, created_at DESC, id DESC
        """,
        (creador_id,),
    )
    return {"ok": True, "creador_id": creador_id, "metas": metas}


@router.get("/api/creadores/performance/{creador_id}/insights")
def insights_performance_creador(creador_id: int):
    insights = fetch_all(
        """
        SELECT *
        FROM creadores_insights_mensuales
        WHERE creador_id = %s
        ORDER BY periodo_fin DESC, created_at DESC, id DESC
        """,
        (creador_id,),
    )
    return {"ok": True, "creador_id": creador_id, "insights": insights}


@router.get("/api/creadores/performance/{creador_id}/perfil-respuestas")
def perfil_respuestas_performance_creador(creador_id: int):
    perfil_respuestas = obtener_perfil_respuestas(creador_id)
    return {
        "ok": True,
        "creador_id": creador_id,
        "perfil_respuestas": perfil_respuestas,
        "perfil_estrategico": construir_perfil_estrategico(
            perfil_respuestas,
            obtener_categoria_creador(creador_id),
            obtener_arquetipo_creador(creador_id),
        ),
    }


# =========================================================
# ENDPOINTS — SEGUIMIENTOS
# =========================================================

@router.post("/api/creadores/performance/seguimientos")
def crear_seguimiento_performance(seg: SeguimientoPerformanceCreate):
    if not seg.creador_id:
        raise HTTPException(status_code=400, detail="creador_id es requerido")

    creador = obtener_creador(seg.creador_id)
    if not creador:
        raise HTTPException(status_code=404, detail="Creador no encontrado")

    manager_id = obtener_manager_id_por_creador(seg.creador_id)

    if manager_id is None:
        raise HTTPException(
            status_code=404,
            detail="No se encontró manager asociado en creadores_detalle",
        )

    fecha = seg.fecha_seguimiento or date.today()
    observaciones = normalizar_texto_parrafos(seg.observaciones_manager)
    compromisos = normalizar_texto_parrafos(seg.resumen_compromisos)

    fila = execute_returning(
        """
        INSERT INTO creadores_performance_seguimiento (
            creador_id,
            manager_id,
            fecha_seguimiento,
            observaciones_manager,
            resumen_compromisos
        )
        VALUES (
            %(creador_id)s,
            %(manager_id)s,
            %(fecha_seguimiento)s,
            %(observaciones_manager)s,
            %(resumen_compromisos)s
        )
        RETURNING *;
        """,
        {
            "creador_id": seg.creador_id,
            "manager_id": manager_id,
            "fecha_seguimiento": fecha,
            "observaciones_manager": observaciones,
            "resumen_compromisos": compromisos,
        },
    )
    return _formatear_seguimiento_respuesta(fila)


@router.post("/api/creadores/performance/seguimientos-con-acciones")
def crear_seguimiento_con_acciones(data: SeguimientoConAccionesCreate):
    seguimiento = crear_seguimiento_performance(
        SeguimientoPerformanceCreate(
            creador_id=data.creador_id,
            fecha_seguimiento=data.fecha_seguimiento,
            observaciones_manager=data.observaciones_manager,
            resumen_compromisos=data.resumen_compromisos,
        )
    )

    acciones_creadas = []
    for accion in data.acciones:
        accion_dict = model_to_dict(accion)
        acciones_creadas.append(insertar_accion(seguimiento["id"], accion_dict))

    seguimiento["acciones"] = acciones_creadas
    return seguimiento


@router.get("/api/creadores/performance/{creador_id}/seguimientos")
def listar_seguimientos_performance(
    creador_id: int,
    limit: int = Query(default=100, ge=1, le=500),
):
    filas = fetch_all(
        """
        SELECT sc.*, au.nombre_completo AS manager_nombre
        FROM creadores_performance_seguimiento sc
        LEFT JOIN administradores au ON sc.manager_id = au.id
        WHERE sc.creador_id = %s
        ORDER BY sc.fecha_seguimiento DESC, sc.id DESC
        LIMIT %s
        """,
        (creador_id, limit),
    )
    return _formatear_lista_seguimientos(filas)


@router.get("/api/creadores/performance/seguimientos/{seguimiento_id}")
def obtener_seguimiento_performance(seguimiento_id: int):
    seguimiento = fetch_one(
        """
        SELECT sc.*, au.nombre_completo AS manager_nombre
        FROM creadores_performance_seguimiento sc
        LEFT JOIN administradores au ON sc.manager_id = au.id
        WHERE sc.id = %s
        """,
        (seguimiento_id,),
    )

    if not seguimiento:
        raise HTTPException(status_code=404, detail="Seguimiento no encontrado")

    acciones = fetch_all(
        """
        SELECT *
        FROM creadores_performance_acciones
        WHERE seguimiento_id = %s
        ORDER BY created_at DESC, id DESC
        """,
        (seguimiento_id,),
    )

    seguimiento["acciones"] = acciones
    return _formatear_seguimiento_respuesta(seguimiento)


@router.put("/api/creadores/performance/seguimientos/{seguimiento_id}")
def actualizar_seguimiento_performance(
    seguimiento_id: int,
    data: SeguimientoPerformanceUpdate,
):
    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_seguimiento
        WHERE id = %s
        """,
        (seguimiento_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Seguimiento no encontrado")

    payload = model_to_dict(data, exclude_unset=True)
    if "observaciones_manager" in payload:
        payload["observaciones_manager"] = normalizar_texto_parrafos(
            payload["observaciones_manager"]
        )
    if "resumen_compromisos" in payload:
        payload["resumen_compromisos"] = normalizar_texto_parrafos(
            payload["resumen_compromisos"]
        )

    actualizado = update_row_dynamic(
        table_name="creadores_performance_seguimiento",
        id_column="id",
        id_value=seguimiento_id,
        data=payload,
        allowed_fields={
            "fecha_seguimiento",
            "observaciones_manager",
            "resumen_compromisos",
        },
    )
    return _formatear_seguimiento_respuesta(actualizado)


@router.delete("/api/creadores/performance/seguimientos/{seguimiento_id}")
def eliminar_seguimiento_performance(seguimiento_id: int):
    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_seguimiento
        WHERE id = %s
        """,
        (seguimiento_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Seguimiento no encontrado")

    execute_no_return(
        """
        DELETE FROM creadores_performance_acciones
        WHERE seguimiento_id = %s
        """,
        (seguimiento_id,),
    )
    execute_no_return(
        """
        DELETE FROM creadores_performance_seguimiento
        WHERE id = %s
        """,
        (seguimiento_id,),
    )

    return {"ok": True, "message": "Seguimiento eliminado"}


# Compatibilidad con rutas antiguas
@router.post("/api/seguimiento_creadores/")
def crear_seguimiento_creador_legacy(seg: SeguimientoPerformanceCreate):
    return crear_seguimiento_performance(seg)


@router.get("/api/seguimiento_creadores/creador/{creador_id}")
def listar_seguimientos_por_creador_legacy(creador_id: int):
    return listar_seguimientos_performance(creador_id)


# =========================================================
# ENDPOINTS — ACCIONES
# =========================================================

@router.post("/api/creadores/performance/acciones")
def crear_accion_performance(data: AccionPerformanceCreate):
    seguimiento = fetch_one(
        """
        SELECT *
        FROM creadores_performance_seguimiento
        WHERE id = %s
        """,
        (data.seguimiento_id,),
    )

    if not seguimiento:
        raise HTTPException(status_code=404, detail="Seguimiento no encontrado")

    return insertar_accion(data.seguimiento_id, model_to_dict(data))


@router.get("/api/creadores/performance/{creador_id}/acciones")
def listar_acciones_por_creador(
    creador_id: int,
    estado: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
):
    params: List[Any] = [creador_id]
    filtro_estado = ""

    if estado:
        estado_norm = validar_valor_en_set(estado, ESTADOS_ACCION_VALIDOS, "estado")
        filtro_estado = " AND COALESCE(a.estado, 'pendiente') = %s "
        params.append(estado_norm)

    params.append(limit)

    return fetch_all(
        f"""
        SELECT a.*, s.creador_id, s.fecha_seguimiento
        FROM creadores_performance_acciones a
        INNER JOIN creadores_performance_seguimiento s
            ON a.seguimiento_id = s.id
        WHERE s.creador_id = %s
        {filtro_estado}
        ORDER BY
            CASE a.prioridad
                WHEN 'critica' THEN 1
                WHEN 'alta' THEN 2
                WHEN 'media' THEN 3
                WHEN 'baja' THEN 4
                ELSE 5
            END,
            a.fecha_compromiso ASC NULLS LAST,
            a.created_at DESC,
            a.id DESC
        LIMIT %s
        """,
        tuple(params),
    )


@router.get("/api/creadores/performance/acciones/{accion_id}")
def obtener_accion_performance(accion_id: int):
    accion = fetch_one(
        """
        SELECT a.*, s.creador_id, s.fecha_seguimiento
        FROM creadores_performance_acciones a
        INNER JOIN creadores_performance_seguimiento s
            ON a.seguimiento_id = s.id
        WHERE a.id = %s
        """,
        (accion_id,),
    )

    if not accion:
        raise HTTPException(status_code=404, detail="Acción no encontrada")

    return accion


@router.put("/api/creadores/performance/acciones/{accion_id}")
def actualizar_accion_performance(
    accion_id: int,
    data: AccionPerformanceUpdate,
):
    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_acciones
        WHERE id = %s
        """,
        (accion_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Acción no encontrada")

    payload = model_to_dict(data, exclude_unset=True)

    if "prioridad" in payload:
        payload["prioridad"] = validar_valor_en_set(
            payload.get("prioridad"),
            PRIORIDADES_VALIDAS,
            "prioridad",
        )

    if "estado" in payload:
        payload["estado"] = validar_valor_en_set(
            payload.get("estado"),
            ESTADOS_ACCION_VALIDOS,
            "estado",
        )

    payload["updated_at"] = datetime.now()

    return update_row_dynamic(
        table_name="creadores_performance_acciones",
        id_column="id",
        id_value=accion_id,
        data=payload,
        allowed_fields={
            "tipo_accion",
            "titulo",
            "descripcion",
            "prioridad",
            "estado",
            "fecha_compromiso",
            "fecha_cumplimiento",
            "updated_at",
        },
    )


@router.patch("/api/creadores/performance/acciones/{accion_id}/estado")
def cambiar_estado_accion_performance(
    accion_id: int,
    data: AccionEstadoUpdate,
):
    estado_norm = validar_valor_en_set(
        data.estado,
        ESTADOS_ACCION_VALIDOS,
        "estado",
        requerido=True,
    )

    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_acciones
        WHERE id = %s
        """,
        (accion_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Acción no encontrada")

    fecha_cumplimiento = data.fecha_cumplimiento

    if estado_norm == "cumplido" and not fecha_cumplimiento:
        fecha_cumplimiento = date.today()

    return execute_returning(
        """
        UPDATE creadores_performance_acciones
        SET
            estado = %(estado)s,
            fecha_cumplimiento = %(fecha_cumplimiento)s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %(id)s
        RETURNING *;
        """,
        {
            "id": accion_id,
            "estado": estado_norm,
            "fecha_cumplimiento": fecha_cumplimiento,
        },
    )


@router.delete("/api/creadores/performance/acciones/{accion_id}")
def eliminar_accion_performance(accion_id: int):
    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_acciones
        WHERE id = %s
        """,
        (accion_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Acción no encontrada")

    execute_no_return(
        """
        DELETE FROM creadores_performance_acciones
        WHERE id = %s
        """,
        (accion_id,),
    )

    return {"ok": True, "message": "Acción eliminada"}


# =========================================================
# ENDPOINTS — ALERTAS
# =========================================================

@router.post("/api/creadores/performance/alertas")
def crear_alerta_performance(data: AlertaPerformanceCreate):
    payload = model_to_dict(data)
    return insertar_alerta(payload)


@router.get("/api/creadores/performance/{creador_id}/alertas")
def listar_alertas_performance(
    creador_id: int,
    estado: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    params: List[Any] = [creador_id]
    filtro_estado = ""

    if estado:
        estado_norm = validar_valor_en_set(estado, ESTADOS_ALERTA_VALIDOS, "estado")
        filtro_estado = " AND COALESCE(estado, 'activa') = %s "
        params.append(estado_norm)

    params.append(limit)

    return fetch_all(
        f"""
        SELECT *
        FROM creadores_performance_alertas
        WHERE creador_id = %s
        {filtro_estado}
        ORDER BY
            CASE nivel_alerta
                WHEN 'critica' THEN 1
                WHEN 'alta' THEN 2
                WHEN 'media' THEN 3
                WHEN 'baja' THEN 4
                ELSE 5
            END,
            created_at DESC,
            id DESC
        LIMIT %s
        """,
        tuple(params),
    )


@router.put("/api/creadores/performance/alertas/{alerta_id}")
def actualizar_alerta_performance(
    alerta_id: int,
    data: AlertaPerformanceUpdate,
):
    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_alertas
        WHERE id = %s
        """,
        (alerta_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    payload = model_to_dict(data, exclude_unset=True)

    if "nivel_alerta" in payload:
        payload["nivel_alerta"] = validar_valor_en_set(
            payload.get("nivel_alerta"),
            NIVELES_ALERTA_VALIDOS,
            "nivel_alerta",
        )

    if "estado" in payload:
        payload["estado"] = validar_valor_en_set(
            payload.get("estado"),
            ESTADOS_ALERTA_VALIDOS,
            "estado",
        )

    return update_row_dynamic(
        table_name="creadores_performance_alertas",
        id_column="id",
        id_value=alerta_id,
        data=payload,
        allowed_fields={
            "tipo_alerta",
            "nivel_alerta",
            "titulo",
            "descripcion",
            "origen",
            "estado",
            "resolved_at",
        },
    )


@router.patch("/api/creadores/performance/alertas/{alerta_id}/resolver")
def resolver_alerta_performance(
    alerta_id: int,
    data: ResolverAlertaRequest = ResolverAlertaRequest(),
):
    estado_norm = validar_valor_en_set(
        data.estado or "resuelta",
        ESTADOS_ALERTA_VALIDOS,
        "estado",
    )

    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_alertas
        WHERE id = %s
        """,
        (alerta_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    return execute_returning(
        """
        UPDATE creadores_performance_alertas
        SET
            estado = %(estado)s,
            resolved_at = CURRENT_TIMESTAMP
        WHERE id = %(id)s
        RETURNING *;
        """,
        {
            "id": alerta_id,
            "estado": estado_norm,
        },
    )


@router.delete("/api/creadores/performance/alertas/{alerta_id}")
def eliminar_alerta_performance(alerta_id: int):
    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_alertas
        WHERE id = %s
        """,
        (alerta_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    execute_no_return(
        """
        DELETE FROM creadores_performance_alertas
        WHERE id = %s
        """,
        (alerta_id,),
    )

    return {"ok": True, "message": "Alerta eliminada"}


# =========================================================
# ENDPOINTS — RECOMENDACIONES
# =========================================================

@router.post("/api/creadores/performance/recomendaciones")
def crear_recomendacion_performance(data: RecomendacionPerformanceCreate):
    payload = model_to_dict(data)
    return insertar_recomendacion(payload)


@router.get("/api/creadores/performance/{creador_id}/recomendaciones")
def listar_recomendaciones_performance(
    creador_id: int,
    aplicada: Optional[bool] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    params: List[Any] = [creador_id]
    filtro = ""

    if aplicada is not None:
        filtro = " AND COALESCE(aplicada, false) = %s "
        params.append(aplicada)

    params.append(limit)

    return fetch_all(
        f"""
        SELECT *
        FROM creadores_performance_recomendaciones
        WHERE creador_id = %s
        {filtro}
        ORDER BY
            CASE prioridad
                WHEN 'critica' THEN 1
                WHEN 'alta' THEN 2
                WHEN 'media' THEN 3
                WHEN 'baja' THEN 4
                ELSE 5
            END,
            created_at DESC,
            id DESC
        LIMIT %s
        """,
        tuple(params),
    )


@router.put("/api/creadores/performance/recomendaciones/{recomendacion_id}")
def actualizar_recomendacion_performance(
    recomendacion_id: int,
    data: RecomendacionPerformanceUpdate,
):
    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_recomendaciones
        WHERE id = %s
        """,
        (recomendacion_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Recomendación no encontrada")

    payload = model_to_dict(data, exclude_unset=True)

    if "prioridad" in payload:
        payload["prioridad"] = validar_valor_en_set(
            payload.get("prioridad"),
            PRIORIDADES_VALIDAS,
            "prioridad",
        )

    if payload.get("aplicada") is True and not payload.get("aplicada_at"):
        payload["aplicada_at"] = datetime.now()

    if payload.get("aplicada") is False:
        payload["aplicada_at"] = None

    return update_row_dynamic(
        table_name="creadores_performance_recomendaciones",
        id_column="id",
        id_value=recomendacion_id,
        data=payload,
        allowed_fields={
            "categoria",
            "prioridad",
            "recomendacion",
            "justificacion",
            "aplicada",
            "aplicada_at",
        },
    )


@router.patch("/api/creadores/performance/recomendaciones/{recomendacion_id}/aplicar")
def aplicar_recomendacion_performance(
    recomendacion_id: int,
    data: AplicarRecomendacionRequest = AplicarRecomendacionRequest(),
):
    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_recomendaciones
        WHERE id = %s
        """,
        (recomendacion_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Recomendación no encontrada")

    aplicada_at = datetime.now() if data.aplicada else None

    return execute_returning(
        """
        UPDATE creadores_performance_recomendaciones
        SET
            aplicada = %(aplicada)s,
            aplicada_at = %(aplicada_at)s
        WHERE id = %(id)s
        RETURNING *;
        """,
        {
            "id": recomendacion_id,
            "aplicada": data.aplicada,
            "aplicada_at": aplicada_at,
        },
    )


@router.delete("/api/creadores/performance/recomendaciones/{recomendacion_id}")
def eliminar_recomendacion_performance(recomendacion_id: int):
    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_recomendaciones
        WHERE id = %s
        """,
        (recomendacion_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Recomendación no encontrada")

    execute_no_return(
        """
        DELETE FROM creadores_performance_recomendaciones
        WHERE id = %s
        """,
        (recomendacion_id,),
    )

    return {"ok": True, "message": "Recomendación eliminada"}


# =========================================================
# ENDPOINTS — SCORE / RESUMEN
# =========================================================

@router.get("/api/creadores/performance/{creador_id}/score")
def obtener_score_performance(creador_id: int):
    score = obtener_score_actual(creador_id)
    return {
        "ok": True,
        "creador_id": creador_id,
        "score": score,
    }


@router.get("/api/creadores/performance/{creador_id}/score/historial")
def historial_score_performance(
    creador_id: int,
    limit: int = Query(default=50, ge=1, le=500),
):
    scores = fetch_all(
        """
        SELECT *
        FROM creadores_performance_score
        WHERE creador_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT %s
        """,
        (creador_id, limit),
    )
    return {
        "ok": True,
        "creador_id": creador_id,
        "scores": scores,
    }


@router.post("/api/creadores/performance/score")
def crear_score_performance(data: ScorePerformanceCreate):
    payload = model_to_dict(data)
    return insertar_score(payload)


@router.post("/api/creadores/performance/{creador_id}/score/recalcular")
def recalcular_score_performance(
    creador_id: int,
    guardar: bool = Query(default=True),
):
    contexto = obtener_contexto_performance(creador_id)
    score = calcular_score_basico(contexto)

    if guardar:
        score_guardado = insertar_score(score)
        return {
            "ok": True,
            "guardado": True,
            "score": score_guardado,
        }

    return {
        "ok": True,
        "guardado": False,
        "score": score,
    }


@router.get("/api/creadores/performance/{creador_id}/resumen")
def obtener_resumen_performance(
    creador_id: int,
    limit: int = Query(default=24, ge=1, le=120),
):
    resumen = fetch_all(
        """
        SELECT *
        FROM creadores_performance_resumen
        WHERE creador_id = %s
        ORDER BY periodo_fin DESC, created_at DESC, id DESC
        LIMIT %s
        """,
        (creador_id, limit),
    )
    return {
        "ok": True,
        "creador_id": creador_id,
        "resumen": resumen,
    }


@router.post("/api/creadores/performance/resumen")
def crear_resumen_performance(data: ResumenPerformanceCreate):
    payload = model_to_dict(data)
    return insertar_resumen(payload)


@router.post("/api/creadores/performance/{creador_id}/resumen/recalcular")
def recalcular_resumen_performance(
    creador_id: int,
    guardar: bool = Query(default=True),
):
    contexto = obtener_contexto_performance(creador_id)
    score = calcular_score_basico(contexto)
    resumen = construir_resumen_basico(contexto, score)

    if guardar:
        resumen_guardado = insertar_resumen(resumen)
        return {
            "ok": True,
            "guardado": True,
            "resumen": resumen_guardado,
        }

    return {
        "ok": True,
        "guardado": False,
        "resumen": resumen,
    }


# =========================================================
# ENDPOINTS — ANÁLISIS BÁSICO SIN IA
# =========================================================

@router.post("/api/creadores/performance/{creador_id}/analisis-basico")
def generar_analisis_basico_performance(
    creador_id: int,
    guardar: bool = Query(default=True),
):
    contexto = obtener_contexto_performance(creador_id)

    score = calcular_score_basico(contexto)
    alertas = detectar_alertas_basicas(contexto)
    recomendaciones = generar_recomendaciones_basicas(contexto)
    resumen = construir_resumen_basico(contexto, score)

    resultado: Dict[str, Any] = {
        "ok": True,
        "guardado": guardar,
        "score": score,
        "alertas": alertas,
        "recomendaciones": recomendaciones,
        "resumen": resumen,
    }

    if guardar:
        resultado["score"] = insertar_score(score)
        resultado["alertas"] = [insertar_alerta(a) for a in alertas]
        resultado["recomendaciones"] = [insertar_recomendacion(r) for r in recomendaciones]
        resultado["resumen"] = insertar_resumen(resumen)

    return resultado



# =========================================================
# ENDPOINTS — IA
# =========================================================

def _log_ia_debug_contexto(endpoint: str, creador_id: int, contexto: Dict[str, Any]) -> None:
    """Logs temporales de debug: verificar datos de perfil/categoría/partidas antes del prompt IA."""
    if not DEBUG_PERFORMANCE_IA:
        return

    print(f"🧠 [IA DEBUG] endpoint: {endpoint}", flush=True)
    print(f"🧠 [IA DEBUG] creador_id: {creador_id}", flush=True)
    print(f"🧠 [IA DEBUG] perfil_estrategico: {contexto.get('perfil_estrategico')}", flush=True)
    print(f"🧠 [IA DEBUG] categoria_creador: {contexto.get('categoria_creador')}", flush=True)
    print(f"🧠 [IA DEBUG] performance_partidas: {contexto.get('performance_partidas')}", flush=True)
    print(
        f"🧠 [IA DEBUG] tiene_perfil_estrategico: {bool(contexto.get('perfil_estrategico'))}",
        flush=True,
    )
    print(
        f"🧠 [IA DEBUG] tiene_categoria_creador: {bool(contexto.get('categoria_creador'))}",
        flush=True,
    )
    print(
        f"🧠 [IA DEBUG] tiene_performance_partidas: {bool(contexto.get('performance_partidas'))}",
        flush=True,
    )

    perfil = contexto.get("perfil_estrategico") or {}
    print(f"🧠 [IA DEBUG] arquetipo: {perfil.get('arquetipo_valor')}", flush=True)
    print(f"🧠 [IA DEBUG] intereses: {perfil.get('intereses')}", flush=True)
    print(f"🧠 [IA DEBUG] horario: {perfil.get('horario_preferido')}", flush=True)

    categoria = contexto.get("categoria_creador") or {}
    print(f"🧠 [IA DEBUG] categoria: {categoria.get('nombre')}", flush=True)
    print(
        f"🧠 [IA DEBUG] meta_categoria_diamantes: {categoria.get('meta_diamantes_objetivo')}",
        flush=True,
    )

    partidas = contexto.get("performance_partidas") or {}
    print(f"🧠 [IA DEBUG] partidas: {partidas.get('partidas')}", flush=True)
    print(
        f"🧠 [IA DEBUG] diamantes_de_partidas: {partidas.get('diamantes_de_partidas')}",
        flush=True,
    )
    print(
        "🧠 [IA DEBUG] porcentaje_diamantes_por_partidas: "
        f"{partidas.get('porcentaje_diamantes_por_partidas')}",
        flush=True,
    )
    print(
        f"🧠 [IA DEBUG] diagnostico_partidas: {partidas.get('diagnostico_partidas')}",
        flush=True,
    )


@router.get("/api/creadores/performance/{creador_id}/ia/debug-datos-tablas")
def debug_datos_tablas_ia(
    creador_id: int,
    id_reporte: Optional[int] = Query(default=None),
    anonimizar: bool = Query(default=True),
):
    """
    Exporta un JSON compacto con datos reales de tablas para pruebas externas de IA.

    No llama OpenAI.
    No incluye base_conocimiento.
    No incluye insights.
    No incluye recomendaciones.
    No incluye score.
    No incluye alertas.
    No incluye acciones.
    No incluye seguimientos.
    """
    return obtener_datos_tablas_debug_ia(
        creador_id,
        id_reporte=id_reporte,
        anonimizar=anonimizar,
    )


@router.get(
    "/api/creadores/performance/{creador_id}/ia/debug-contexto-recomendaciones",
)
def debug_contexto_recomendaciones_ia_legacy(
    creador_id: int,
    id_reporte: Optional[int] = Query(default=None),
    anonimizar: bool = Query(default=True),
):
    """Alias legacy: misma salida que debug-datos-tablas (sin base de conocimiento)."""
    return debug_datos_tablas_ia(
        creador_id=creador_id,
        id_reporte=id_reporte,
        anonimizar=anonimizar,
    )


@router.post("/api/creadores/performance/{creador_id}/ia/diagnostico")
def generar_diagnostico_ia(
    creador_id: int,
    data: IARequest = IARequest(),
):
    contexto = obtener_contexto_ia_manager(creador_id, id_reporte=data.id_reporte)
    _log_ia_debug_contexto("diagnostico", creador_id, contexto)
    prompt = prompt_diagnostico_performance(contexto, data.instrucciones_extra)

    resultado = openai_json_completion(
        prompt,
        temperature=0.35,
        system=(
            "Eres experto en performance, coaching y crecimiento de creadores TikTok LIVE. "
            "Responde únicamente JSON válido."
        ),
    )

    return {
        "ok": True,
        "creador_id": creador_id,
        "resultado": resultado,
    }


@router.post("/api/creadores/performance/{creador_id}/ia/generar-seguimiento")
def generar_seguimiento_ia(
    creador_id: int,
    data: GenerarSeguimientoIARequest,
):
    contexto = obtener_contexto_ia_manager(creador_id)
    _log_ia_debug_contexto("generar_seguimiento", creador_id, contexto)
    prompt = prompt_generar_seguimiento(
        contexto,
        data.observaciones_manager or "",
        data.resumen_compromisos or "",
        data.instrucciones_extra,
    )

    resultado = openai_json_completion(
        prompt,
        temperature=0.55,
        system=(
            "Eres asistente de managers de una agencia TikTok LIVE. "
            "Redacta seguimientos accionables en español. Responde únicamente JSON válido."
        ),
    )

    return {
        "ok": True,
        "creador_id": creador_id,
        "resultado": resultado,
    }


@router.post("/api/creadores/performance/{creador_id}/ia/recomendaciones")
def generar_recomendaciones_ia(
    creador_id: int,
    data: GenerarRecomendacionesIARequest = GenerarRecomendacionesIARequest(),
):
    contexto = obtener_contexto_recomendaciones_ia_compacto(
        creador_id,
        id_reporte=data.id_reporte,
        anonimizar=True,
    )
    _log_ia_debug_contexto("recomendaciones", creador_id, contexto)
    prompt = prompt_recomendaciones_manager_v3(
        contexto,
        max_recomendaciones=data.max_recomendaciones,
        instrucciones_extra=data.instrucciones_extra,
    )

    resultado = openai_json_completion(
        prompt,
        temperature=0.45,
        system=(
            "Eres coach senior de creadores TikTok LIVE para managers de agencia. "
            "Responde únicamente con un objeto JSON válido en español."
        ),
    )

    resultado = _normalizar_resultado_recomendaciones_ia(
        contexto, resultado, data.max_recomendaciones
    )
    resultado = _aplicar_pulido_final_recomendaciones(resultado, contexto)
    resultado = _reforzar_recomendaciones_metricas_y_perfil_si_falta(
        resultado,
        contexto,
        max_recomendaciones=data.max_recomendaciones,
    )
    recomendaciones = resultado.get("recomendaciones", []) if isinstance(resultado, dict) else []

    guardadas = []
    if data.guardar:
        reporte = contexto.get("reporte") or {}
        for rec in recomendaciones:
            if not isinstance(rec, dict):
                continue
            rec = _pulir_recomendacion_item(rec)
            payload = {
                "creador_id": creador_id,
                "id_reporte": reporte.get("id_reporte"),
                "categoria": rec.get("categoria"),
                "prioridad": rec.get("prioridad") or "media",
                "recomendacion": rec.get("recomendacion"),
                "justificacion": rec.get("justificacion"),
                "aplicada": False,
            }
            if payload["recomendacion"]:
                guardadas.append(insertar_recomendacion(payload))

    return {
        "ok": True,
        "creador_id": creador_id,
        "guardado": data.guardar,
        "resultado": resultado,
        "guardadas": guardadas,
    }


@router.post("/api/creadores/performance/{creador_id}/ia/acciones")
def generar_acciones_ia(
    creador_id: int,
    data: GenerarAccionesIARequest = GenerarAccionesIARequest(),
):
    contexto = obtener_contexto_ia_manager(creador_id)
    _log_ia_debug_contexto("acciones", creador_id, contexto)
    prompt = prompt_acciones_manager(
        contexto,
        data.max_acciones,
        data.instrucciones_extra,
    )

    resultado = openai_json_completion(
        prompt,
        temperature=0.35,
        system=(
            "Eres coordinador operativo de managers para agencia TikTok LIVE. "
            "Responde únicamente JSON válido."
        ),
    )

    acciones = resultado.get("acciones", []) if isinstance(resultado, dict) else []
    guardadas = []

    if data.guardar:
        seguimiento_id = data.seguimiento_id

        if not seguimiento_id:
            seguimiento = crear_seguimiento_performance(
                SeguimientoPerformanceCreate(
                    creador_id=creador_id,
                    fecha_seguimiento=date.today(),
                    observaciones_manager="Seguimiento generado con apoyo de IA.",
                    resumen_compromisos="Acciones sugeridas por IA para revisión del manager.",
                )
            )
            seguimiento_id = seguimiento["id"]

        seguimiento = fetch_one(
            """
            SELECT *
            FROM creadores_performance_seguimiento
            WHERE id = %s
              AND creador_id = %s
            """,
            (seguimiento_id, creador_id),
        )

        if not seguimiento:
            raise HTTPException(
                status_code=404,
                detail="seguimiento_id no existe o no pertenece al creador",
            )

        for accion in acciones:
            if not isinstance(accion, dict):
                continue

            payload = {
                "tipo_accion": accion.get("tipo_accion") or "META_SEMANAL",
                "titulo": accion.get("titulo"),
                "descripcion": accion.get("descripcion"),
                "prioridad": accion.get("prioridad") or "media",
                "estado": accion.get("estado") or "pendiente",
                "fecha_compromiso": None,
                "creado_por": seguimiento.get("manager_id"),
            }
            guardadas.append(insertar_accion(seguimiento_id, payload))

    return {
        "ok": True,
        "creador_id": creador_id,
        "guardado": data.guardar,
        "resultado": resultado,
        "guardadas": guardadas,
    }


@router.post("/api/creadores/performance/{creador_id}/ia/alertas-score")
def generar_alertas_score_ia(
    creador_id: int,
    data: GenerarAlertasScoreIARequest = GenerarAlertasScoreIARequest(),
):
    contexto = obtener_contexto_ia_manager(creador_id)
    prompt = prompt_alertas_score_ia(contexto, data.instrucciones_extra)

    resultado = openai_json_completion(
        prompt,
        temperature=0.25,
        system=(
            "Eres analista de datos, riesgo y performance de creadores TikTok LIVE. "
            "Responde únicamente JSON válido."
        ),
    )

    reporte = contexto.get("ultimo_reporte") or {}
    guardado_score = None
    guardadas_alertas = []

    if data.guardar and isinstance(resultado, dict):
        score = resultado.get("score") or {}
        if isinstance(score, dict):
            payload_score = {
                "creador_id": creador_id,
                "id_reporte": reporte.get("id_reporte"),
                "score_general": score.get("score_general"),
                "nivel_rendimiento": score.get("nivel_rendimiento"),
                "riesgo_abandono": score.get("riesgo_abandono"),
                "probabilidad_crecimiento": score.get("probabilidad_crecimiento"),
                "consistencia_score": score.get("consistencia_score"),
                "monetizacion_score": score.get("monetizacion_score"),
                "engagement_score": score.get("engagement_score"),
                "observacion_ia": score.get("observacion_ia"),
            }
            guardado_score = insertar_score(payload_score)

        alertas = resultado.get("alertas") or []
        if isinstance(alertas, list):
            for alerta in alertas:
                if not isinstance(alerta, dict):
                    continue
                payload_alerta = {
                    "creador_id": creador_id,
                    "id_reporte": reporte.get("id_reporte"),
                    "tipo_alerta": alerta.get("tipo_alerta"),
                    "nivel_alerta": alerta.get("nivel_alerta") or "media",
                    "titulo": alerta.get("titulo"),
                    "descripcion": alerta.get("descripcion"),
                    "origen": "ia",
                    "estado": "activa",
                }
                guardadas_alertas.append(insertar_alerta(payload_alerta))

    return {
        "ok": True,
        "creador_id": creador_id,
        "guardado": data.guardar,
        "resultado": resultado,
        "score_guardado": guardado_score,
        "alertas_guardadas": guardadas_alertas,
    }


@router.post("/api/creadores/performance/{creador_id}/ia/analisis-completo")
def generar_analisis_completo_ia(
    creador_id: int,
    data: GenerarAlertasScoreIARequest = GenerarAlertasScoreIARequest(),
):
    """
    Endpoint cómodo para el frontend:
    1) Genera diagnóstico IA.
    2) Genera recomendaciones IA.
    3) Genera score + alertas IA.
    Puede guardar recomendaciones, score y alertas.
    """
    contexto = obtener_contexto_ia_manager(creador_id)
    _log_ia_debug_contexto("analisis_completo", creador_id, contexto)

    diagnostico = openai_json_completion(
        prompt_diagnostico_performance(contexto, data.instrucciones_extra),
        temperature=0.35,
        system="Responde únicamente JSON válido en español.",
    )

    recomendaciones_result = openai_json_completion(
        prompt_recomendaciones_manager(contexto, 5, data.instrucciones_extra),
        temperature=0.5,
        system="Responde únicamente con un objeto JSON válido en español.",
    )
    recomendaciones_result = _normalizar_resultado_recomendaciones_ia(
        contexto,
        recomendaciones_result,
        5,
    )
    recomendaciones_result = _aplicar_pulido_final_recomendaciones(
        recomendaciones_result,
        contexto,
    )

    alertas_score_result = openai_json_completion(
        prompt_alertas_score_ia(contexto, data.instrucciones_extra),
        temperature=0.25,
        system="Responde únicamente JSON válido en español.",
    )

    reporte = contexto.get("ultimo_reporte") or {}
    guardado: Dict[str, Any] = {
        "score": None,
        "alertas": [],
        "recomendaciones": [],
    }

    if data.guardar:
        score = alertas_score_result.get("score", {}) if isinstance(alertas_score_result, dict) else {}
        if isinstance(score, dict):
            guardado["score"] = insertar_score({
                "creador_id": creador_id,
                "id_reporte": reporte.get("id_reporte"),
                "score_general": score.get("score_general"),
                "nivel_rendimiento": score.get("nivel_rendimiento"),
                "riesgo_abandono": score.get("riesgo_abandono"),
                "probabilidad_crecimiento": score.get("probabilidad_crecimiento"),
                "consistencia_score": score.get("consistencia_score"),
                "monetizacion_score": score.get("monetizacion_score"),
                "engagement_score": score.get("engagement_score"),
                "observacion_ia": score.get("observacion_ia"),
            })

        alertas = alertas_score_result.get("alertas", []) if isinstance(alertas_score_result, dict) else []
        if isinstance(alertas, list):
            for alerta in alertas:
                if not isinstance(alerta, dict):
                    continue
                guardado["alertas"].append(insertar_alerta({
                    "creador_id": creador_id,
                    "id_reporte": reporte.get("id_reporte"),
                    "tipo_alerta": alerta.get("tipo_alerta"),
                    "nivel_alerta": alerta.get("nivel_alerta") or "media",
                    "titulo": alerta.get("titulo"),
                    "descripcion": alerta.get("descripcion"),
                    "origen": "ia",
                    "estado": "activa",
                }))

        recomendaciones = recomendaciones_result.get("recomendaciones", []) if isinstance(recomendaciones_result, dict) else []
        if isinstance(recomendaciones, list):
            for rec in recomendaciones:
                if not isinstance(rec, dict):
                    continue
                if not rec.get("recomendacion"):
                    continue
                rec = _pulir_recomendacion_item(rec)
                guardado["recomendaciones"].append(insertar_recomendacion({
                    "creador_id": creador_id,
                    "id_reporte": reporte.get("id_reporte"),
                    "categoria": rec.get("categoria"),
                    "prioridad": rec.get("prioridad") or "media",
                    "recomendacion": rec.get("recomendacion"),
                    "justificacion": rec.get("justificacion"),
                    "aplicada": False,
                }))

    return {
        "ok": True,
        "creador_id": creador_id,
        "guardado": data.guardar,
        "diagnostico": diagnostico,
        "recomendaciones": recomendaciones_result,
        "alertas_score": alertas_score_result,
        "guardado_detalle": guardado,
    }


# =========================================================
# ENDPOINTS — RANKINGS / LISTADOS PARA MANAGER
# =========================================================

@router.get("/api/creadores/performance/ranking/score")
def ranking_score_performance(
    limit: int = Query(default=50, ge=1, le=500),
):
    """
    Ranking usando el último score por creador.
    """
    return fetch_all(
        """
        SELECT *
        FROM (
            SELECT DISTINCT ON (s.creador_id)
                s.*,
                c.nombre,
                c.usuario_tiktok,
                cd.manager_id,
                au.nombre_completo AS manager_nombre
            FROM creadores_performance_score s
            INNER JOIN creadores c ON s.creador_id = c.id
            LEFT JOIN creadores_detalle cd ON c.id = cd.creador_id
            LEFT JOIN administradores au ON cd.manager_id = au.id
            ORDER BY s.creador_id, s.created_at DESC, s.id DESC
        ) ultimos
        ORDER BY ultimos.score_general DESC NULLS LAST, ultimos.creador_id ASC
        LIMIT %s
        """,
        (limit,),
    )


@router.get("/api/creadores/performance/riesgo")
def listar_creadores_en_riesgo(
    riesgo: Optional[str] = Query(default="alto"),
    limit: int = Query(default=50, ge=1, le=500),
):
    riesgo_norm = normalizar_lower(riesgo)

    return fetch_all(
        """
        SELECT *
        FROM (
            SELECT DISTINCT ON (s.creador_id)
                s.*,
                c.nombre,
                c.usuario_tiktok,
                cd.manager_id,
                au.nombre_completo AS manager_nombre
            FROM creadores_performance_score s
            INNER JOIN creadores c ON s.creador_id = c.id
            LEFT JOIN creadores_detalle cd ON c.id = cd.creador_id
            LEFT JOIN administradores au ON cd.manager_id = au.id
            ORDER BY s.creador_id, s.created_at DESC, s.id DESC
        ) ultimos
        WHERE riesgo_abandono = %s
        ORDER BY score_general ASC NULLS FIRST
        LIMIT %s
        """,
        (riesgo_norm, limit),
    )


@router.get("/api/creadores/performance/manager/{manager_id}/resumen")
def resumen_performance_manager(
    manager_id: int,
    limit: int = Query(default=100, ge=1, le=500),
):
    """
    Resumen operativo para un manager:
    - creadores asignados
    - último score
    - acciones abiertas
    - alertas activas
    """
    creadores = fetch_all(
        """
        SELECT
            c.id AS creador_id,
            c.nombre,
            c.usuario_tiktok,
            c.foto,
            c.categoria_id,
            COALESCE(cat.nombre, 'Sin categoría') AS categoria,
            c.arquetipo_id,
            COALESCE(arq.nombre, 'Sin arquetipo') AS arquetipo,
            cd.manager_id,
            s.score_general,
            s.nivel_rendimiento,
            s.riesgo_abandono,
            s.probabilidad_crecimiento,
            s.created_at AS score_created_at,
            COALESCE(alertas.alertas_activas, 0) AS alertas_activas,
            COALESCE(acciones.acciones_abiertas, 0) AS acciones_abiertas
        FROM creadores c
        LEFT JOIN creadores_categoria cat ON cat.id = c.categoria_id
        LEFT JOIN creadores_arquetipo arq ON arq.id = c.arquetipo_id
        INNER JOIN creadores_detalle cd ON c.id = cd.creador_id
        LEFT JOIN LATERAL (
            SELECT *
            FROM creadores_performance_score s
            WHERE s.creador_id = c.id
            ORDER BY s.created_at DESC, s.id DESC
            LIMIT 1
        ) s ON true
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS alertas_activas
            FROM creadores_performance_alertas a
            WHERE a.creador_id = c.id
              AND COALESCE(a.estado, 'activa') IN ('activa', 'pendiente')
        ) alertas ON true
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS acciones_abiertas
            FROM creadores_performance_acciones a
            INNER JOIN creadores_performance_seguimiento seg
                ON a.seguimiento_id = seg.id
            WHERE seg.creador_id = c.id
              AND COALESCE(a.estado, 'pendiente') NOT IN ('cumplido', 'cancelado')
        ) acciones ON true
        WHERE cd.manager_id = %s
        ORDER BY
            CASE s.riesgo_abandono
                WHEN 'alto' THEN 1
                WHEN 'medio' THEN 2
                WHEN 'bajo' THEN 3
                ELSE 4
            END,
            s.score_general ASC NULLS LAST,
            c.nombre ASC
        LIMIT %s
        """,
        (manager_id, limit),
    )

    return {
        "ok": True,
        "manager_id": manager_id,
        "creadores": creadores,
    }



# =========================================================
# ENDPOINTS — ARQUETIPOS
# =========================================================

@router.get("/api/creadores/performance/arquetipos")
def listar_arquetipos_performance():
    """
    Catálogo operativo de arquetipos para managers.
    Usa la tabla creadores_arquetipo.
    """
    return {
        "ok": True,
        "arquetipos": obtener_arquetipos_activos(),
    }


@router.get("/api/creadores/performance/{creador_id}/arquetipo")
def obtener_arquetipo_performance_creador(creador_id: int):
    creador = obtener_creador(creador_id)
    if not creador:
        raise HTTPException(status_code=404, detail="Creador no encontrado")

    return {
        "ok": True,
        "creador_id": creador_id,
        "arquetipo": obtener_arquetipo_creador(creador_id),
    }


@router.patch("/api/creadores/performance/{creador_id}/arquetipo")
def actualizar_arquetipo_performance_creador(
    creador_id: int,
    data: ActualizarArquetipoCreadorRequest,
):
    """
    Permite al manager definir o limpiar el arquetipo operativo del creador.
    Si arquetipo_id es null, se limpia el arquetipo y la IA volverá a usar el declarado en encuesta.
    """
    creador = obtener_creador(creador_id)
    if not creador:
        raise HTTPException(status_code=404, detail="Creador no encontrado")

    if data.arquetipo_id is not None:
        arquetipo = fetch_one(
            """
            SELECT id
            FROM creadores_arquetipo
            WHERE id = %s
              AND COALESCE(activo, true) = true
            LIMIT 1
            """,
            (data.arquetipo_id,),
        )
        if not arquetipo:
            raise HTTPException(
                status_code=404,
                detail="Arquetipo no encontrado o inactivo",
            )

    creador_actualizado = execute_returning(
        """
        UPDATE creadores
        SET
            arquetipo_id = %(arquetipo_id)s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %(creador_id)s
        RETURNING *;
        """,
        {
            "creador_id": creador_id,
            "arquetipo_id": data.arquetipo_id,
        },
    )

    return {
        "ok": True,
        "creador": creador_actualizado,
        "arquetipo": obtener_arquetipo_creador(creador_id),
    }


# =========================================================
# ENDPOINTS — CATÁLOGOS FRONTEND
# =========================================================

@router.get("/api/creadores/performance/catalogos")
def catalogos_performance():
    return {
        "ok": True,
        "estados_accion": sorted(ESTADOS_ACCION_VALIDOS),
        "prioridades": sorted(PRIORIDADES_VALIDAS),
        "estados_alerta": sorted(ESTADOS_ALERTA_VALIDOS),
        "niveles_alerta": sorted(NIVELES_ALERTA_VALIDOS),
        "tipos_accion_sugeridos": sorted(TIPOS_ACCION_SUGERIDOS),
        "niveles_rendimiento": sorted(NIVELES_RENDIMIENTO),
        "arquetipos": obtener_arquetipos_activos(),
    }


# =========================================================
# ENDPOINTS — HEALTHCHECK
# =========================================================

@router.get("/api/creadores/performance/health")
def health_performance():
    """
    Healthcheck básico del módulo.
    """
    try:
        db_ok = fetch_one("SELECT 1 AS ok")
        return {
            "ok": True,
            "modulo": "creadores_performance",
            "db": db_ok,
            "openai": {
                "api_key_configurada": openai_api_key_configurada(),
                "habilitado_agencia": openai_habilitado_en_agencia(),
                "puede_usarse": openai_disponible(),
                "modelo": OPENAI_MODEL_DEFAULT,
            },
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error en healthcheck performance: {e}",
        )
