# ============================
# IMPORTS - Estándar de Python
# ============================
from datetime import datetime, date
from typing import Optional, List, Dict, Any

# ============================
# IMPORTS - Terceros
# ============================
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

# ============================
# IMPORTS - Locales
# ============================
from DataBase import get_connection_context

router = APIRouter()

# ============================
# CONSTANTES DE NEGOCIO
# ============================
ESTADO_ASPIRANTE_NUEVO = 1
ESTADO_ASPIRANTE_PRESELECCION = 2
ESTADO_ASPIRANTE_EVALUACION = 3
ESTADO_ASPIRANTE_ENTREVISTA = 4
ESTADO_ASPIRANTE_INVITACION = 5
ESTADO_ASPIRANTE_INCORPORADO = 6
ESTADO_ASPIRANTE_RECHAZADO = 7

PARTICIPANTE_TIPO_ASPIRANTE = 1


# ============================
# SCHEMAS
# ============================
class EstadisticaResumenOut(BaseModel):
    total_aspirantes: int
    nuevos: int
    preseleccion: int
    evaluacion: int
    entrevista: int
    invitacion: int
    incorporado: int
    rechazado: int
    encuesta_iniciada: int
    encuesta_completada: int
    encuesta_abandonada: int
    invitaciones_creadas: int
    invitaciones_enviadas: int
    invitaciones_incorporadas: int
    agendamientos_generados: int
    conversion_incorporado_pct: float


class EmbudoItemOut(BaseModel):
    codigo: str
    titulo: str
    total: int
    porcentaje_sobre_total: float


class EmbudoOut(BaseModel):
    total_base: int
    etapas: List[EmbudoItemOut] = Field(default_factory=list)


class EstadoActualItemOut(BaseModel):
    estado_id: int
    estado_nombre: str
    total: int


class EstadosActualesOut(BaseModel):
    estados: List[EstadoActualItemOut] = Field(default_factory=list)


class TiempoEtapaOut(BaseModel):
    desde_estado_id: int
    hasta_estado_id: int
    desde_estado: str
    hasta_estado: str
    casos: int
    promedio_horas: Optional[float] = None
    promedio_dias: Optional[float] = None


class TiemposProcesoOut(BaseModel):
    transiciones: List[TiempoEtapaOut] = Field(default_factory=list)


class EncuestaResumenOut(BaseModel):
    total_registros: int
    iniciadas: int
    completadas: int
    abandonadas: int
    sincronizadas: int
    preguntas_respondidas_promedio: float
    duracion_promedio_minutos: Optional[float] = None


class InvitacionResumenOut(BaseModel):
    total: int
    pendiente_envio: int
    enviadas: int
    aceptadas_aspirante: int
    rechazadas_aspirante: int
    tiktok_aceptadas: int
    tiktok_rechazadas: int
    incorporadas: int


class AgendamientoResumenOut(BaseModel):
    total_agendamientos_aspirantes: int
    aspirantes_con_agendamiento: int
    entrevistas: int
    pruebas: int
    duracion_promedio_minutos: Optional[float] = None


class SerieItemOut(BaseModel):
    fecha: str
    total: int


class SerieTemporalOut(BaseModel):
    serie: List[SerieItemOut] = Field(default_factory=list)


# ============================
# HELPERS
# ============================
def safe_pct(parte: int, total: int) -> float:
    if not total:
        return 0.0
    return round((parte / total) * 100, 2)


def fetch_one_dict(cur, query: str, params: tuple = ()) -> Dict[str, Any]:
    cur.execute(query, params)
    row = cur.fetchone()
    if not row:
        return {}
    columns = [desc[0] for desc in cur.description]
    return dict(zip(columns, row))


def fetch_all_dict(cur, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    cur.execute(query, params)
    rows = cur.fetchall()
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row)) for row in rows]


def construir_filtro_fechas(
    campo_sql: str,
    fecha_desde: Optional[date],
    fecha_hasta: Optional[date],
) -> tuple[str, list]:
    condiciones = []
    valores: list = []

    if fecha_desde:
        condiciones.append(f"{campo_sql} >= %s")
        valores.append(fecha_desde)

    if fecha_hasta:
        condiciones.append(f"{campo_sql} < (%s::date + interval '1 day')")
        valores.append(fecha_hasta)

    if not condiciones:
        return "", valores

    return " AND " + " AND ".join(condiciones), valores


# ============================
# ENDPOINT 1 - RESUMEN GENERAL
# ============================
@router.get("/api/stats/aspirantes/resumen", response_model=EstadisticaResumenOut)
def obtener_resumen_estadistico(
    fecha_desde: Optional[date] = Query(default=None),
    fecha_hasta: Optional[date] = Query(default=None),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                filtro_asp, vals_asp = construir_filtro_fechas(
                    "a.creado_en",
                    fecha_desde,
                    fecha_hasta,
                )

                resumen = fetch_one_dict(
                    cur,
                    f"""
                    SELECT
                        COUNT(*) AS total_aspirantes,
                        COUNT(*) FILTER (WHERE a.estado_id = {ESTADO_ASPIRANTE_NUEVO}) AS nuevos,
                        COUNT(*) FILTER (WHERE a.estado_id = {ESTADO_ASPIRANTE_PRESELECCION}) AS preseleccion,
                        COUNT(*) FILTER (WHERE a.estado_id = {ESTADO_ASPIRANTE_EVALUACION}) AS evaluacion,
                        COUNT(*) FILTER (WHERE a.estado_id = {ESTADO_ASPIRANTE_ENTREVISTA}) AS entrevista,
                        COUNT(*) FILTER (WHERE a.estado_id = {ESTADO_ASPIRANTE_INVITACION}) AS invitacion,
                        COUNT(*) FILTER (WHERE a.estado_id = {ESTADO_ASPIRANTE_INCORPORADO}) AS incorporado,
                        COUNT(*) FILTER (WHERE a.estado_id = {ESTADO_ASPIRANTE_RECHAZADO}) AS rechazado
                    FROM aspirantes a
                    WHERE 1=1
                    {filtro_asp}
                    """,
                    tuple(vals_asp),
                )

                filtro_enc, vals_enc = construir_filtro_fechas(
                    "ei.created_at",
                    fecha_desde,
                    fecha_hasta,
                )

                encuesta = fetch_one_dict(
                    cur,
                    f"""
                    SELECT
                        COUNT(*) AS total_registros,
                        COUNT(*) FILTER (WHERE ei.fecha_inicio IS NOT NULL) AS encuesta_iniciada,
                        COUNT(*) FILTER (WHERE ei.completada = true) AS encuesta_completada,
                        COUNT(*) FILTER (WHERE ei.abandonada = true) AS encuesta_abandonada
                    FROM aspirantes_encuesta_inicial ei
                    WHERE 1=1
                    {filtro_enc}
                    """,
                    tuple(vals_enc),
                )

                filtro_inv, vals_inv = construir_filtro_fechas(
                    "i.creado_en",
                    fecha_desde,
                    fecha_hasta,
                )

                invitacion = fetch_one_dict(
                    cur,
                    f"""
                    SELECT
                        COUNT(*) AS invitaciones_creadas,
                        COUNT(*) FILTER (WHERE i.mensaje_enviado = true) AS invitaciones_enviadas,
                        COUNT(*) FILTER (WHERE i.fecha_incorporacion IS NOT NULL) AS invitaciones_incorporadas
                    FROM invitaciones i
                    WHERE 1=1
                    {filtro_inv}
                    """,
                    tuple(vals_inv),
                )

                filtro_age, vals_age = construir_filtro_fechas(
                    "a.creado_en",
                    fecha_desde,
                    fecha_hasta,
                )

                agendamientos = fetch_one_dict(
                    cur,
                    f"""
                    SELECT COUNT(DISTINCT a.id) AS agendamientos_generados
                    FROM agendamientos a
                    INNER JOIN agendamientos_participantes ap
                        ON ap.agendamiento_id = a.id
                    WHERE ap.participante_tipo_id = %s
                    {filtro_age}
                    """,
                    tuple([PARTICIPANTE_TIPO_ASPIRANTE] + vals_age),
                )

                total_asp = int(resumen.get("total_aspirantes", 0) or 0)
                total_incorp = int(resumen.get("incorporado", 0) or 0)

                return EstadisticaResumenOut(
                    total_aspirantes=total_asp,
                    nuevos=int(resumen.get("nuevos", 0) or 0),
                    preseleccion=int(resumen.get("preseleccion", 0) or 0),
                    evaluacion=int(resumen.get("evaluacion", 0) or 0),
                    entrevista=int(resumen.get("entrevista", 0) or 0),
                    invitacion=int(resumen.get("invitacion", 0) or 0),
                    incorporado=total_incorp,
                    rechazado=int(resumen.get("rechazado", 0) or 0),
                    encuesta_iniciada=int(encuesta.get("encuesta_iniciada", 0) or 0),
                    encuesta_completada=int(encuesta.get("encuesta_completada", 0) or 0),
                    encuesta_abandonada=int(encuesta.get("encuesta_abandonada", 0) or 0),
                    invitaciones_creadas=int(invitacion.get("invitaciones_creadas", 0) or 0),
                    invitaciones_enviadas=int(invitacion.get("invitaciones_enviadas", 0) or 0),
                    invitaciones_incorporadas=int(invitacion.get("invitaciones_incorporadas", 0) or 0),
                    agendamientos_generados=int(agendamientos.get("agendamientos_generados", 0) or 0),
                    conversion_incorporado_pct=safe_pct(total_incorp, total_asp),
                )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo resumen estadístico: {str(e)}")


# ============================
# ENDPOINT 2 - EMBUDO
# ============================
@router.get("/api/stats/aspirantes/embudo", response_model=EmbudoOut)
def obtener_embudo_aspirantes(
    fecha_desde: Optional[date] = Query(default=None),
    fecha_hasta: Optional[date] = Query(default=None),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                filtro_asp, vals_asp = construir_filtro_fechas(
                    "a.creado_en",
                    fecha_desde,
                    fecha_hasta,
                )

                total_base_row = fetch_one_dict(
                    cur,
                    f"""
                    SELECT COUNT(*) AS total
                    FROM aspirantes a
                    WHERE 1=1
                    {filtro_asp}
                    """,
                    tuple(vals_asp),
                )
                total_base = int(total_base_row.get("total", 0) or 0)

                filtro_enc, vals_enc = construir_filtro_fechas(
                    "ei.created_at",
                    fecha_desde,
                    fecha_hasta,
                )

                encuesta_row = fetch_one_dict(
                    cur,
                    f"""
                    SELECT
                        COUNT(DISTINCT ei.aspirante_id) FILTER (WHERE ei.fecha_inicio IS NOT NULL) AS iniciada,
                        COUNT(DISTINCT ei.aspirante_id) FILTER (WHERE ei.completada = true) AS completada
                    FROM aspirantes_encuesta_inicial ei
                    WHERE 1=1
                    {filtro_enc}
                    """,
                    tuple(vals_enc),
                )

                filtro_hist, vals_hist = construir_filtro_fechas(
                    "h.fecha_cambio",
                    fecha_desde,
                    fecha_hasta,
                )

                historial = fetch_all_dict(
                    cur,
                    f"""
                    SELECT
                        h.estado_id,
                        COUNT(DISTINCT h.aspirante_id) AS total
                    FROM aspirantes_estado_historial h
                    WHERE 1=1
                    {filtro_hist}
                    GROUP BY h.estado_id
                    ORDER BY h.estado_id
                    """,
                    tuple(vals_hist),
                )

                hist_map = {int(r["estado_id"]): int(r["total"]) for r in historial}

                etapas_raw = [
                    ("base", "Registrados", total_base),
                    ("encuesta_iniciada", "Encuesta iniciada", int(encuesta_row.get("iniciada", 0) or 0)),
                    ("encuesta_completada", "Encuesta completada", int(encuesta_row.get("completada", 0) or 0)),
                    ("evaluacion", "Pasaron a evaluación", hist_map.get(ESTADO_ASPIRANTE_EVALUACION, 0)),
                    ("entrevista", "Pasaron a entrevista", hist_map.get(ESTADO_ASPIRANTE_ENTREVISTA, 0)),
                    ("invitacion", "Pasaron a invitación", hist_map.get(ESTADO_ASPIRANTE_INVITACION, 0)),
                    ("incorporado", "Incorporados", hist_map.get(ESTADO_ASPIRANTE_INCORPORADO, 0)),
                ]

                etapas = [
                    EmbudoItemOut(
                        codigo=codigo,
                        titulo=titulo,
                        total=total,
                        porcentaje_sobre_total=safe_pct(total, total_base),
                    )
                    for codigo, titulo, total in etapas_raw
                ]

                return EmbudoOut(
                    total_base=total_base,
                    etapas=etapas,
                )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo embudo: {str(e)}")


# ============================
# ENDPOINT 3 - ESTADOS ACTUALES
# ============================
@router.get("/api/stats/aspirantes/estados-actuales", response_model=EstadosActualesOut)
def obtener_estados_actuales():
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                rows = fetch_all_dict(
                    cur,
                    """
                    SELECT
                        ae.id AS estado_id,
                        ae.nombre AS estado_nombre,
                        COUNT(a.id) AS total
                    FROM aspirantes_estados ae
                    LEFT JOIN aspirantes a
                        ON a.estado_id = ae.id
                    GROUP BY ae.id, ae.nombre
                    ORDER BY ae.id
                    """
                )

                return EstadosActualesOut(
                    estados=[
                        EstadoActualItemOut(
                            estado_id=int(r["estado_id"]),
                            estado_nombre=r["estado_nombre"],
                            total=int(r["total"] or 0),
                        )
                        for r in rows
                    ]
                )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo estados actuales: {str(e)}")


# ============================
# ENDPOINT 4 - TIEMPOS ENTRE ETAPAS
# ============================
@router.get("/api/stats/aspirantes/tiempos", response_model=TiemposProcesoOut)
def obtener_tiempos_proceso():
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                rows = fetch_all_dict(
                    cur,
                    """
                    WITH historial_ordenado AS (
                        SELECT
                            h.aspirante_id,
                            h.estado_id,
                            ae.nombre AS estado_nombre,
                            h.fecha_cambio,
                            LEAD(h.estado_id) OVER (
                                PARTITION BY h.aspirante_id
                                ORDER BY h.fecha_cambio, h.id
                            ) AS siguiente_estado_id,
                            LEAD(ae.nombre) OVER (
                                PARTITION BY h.aspirante_id
                                ORDER BY h.fecha_cambio, h.id
                            ) AS siguiente_estado_nombre,
                            LEAD(h.fecha_cambio) OVER (
                                PARTITION BY h.aspirante_id
                                ORDER BY h.fecha_cambio, h.id
                            ) AS siguiente_fecha
                        FROM aspirantes_estado_historial h
                        INNER JOIN aspirantes_estados ae
                            ON ae.id = h.estado_id
                    )
                    SELECT
                        estado_id AS desde_estado_id,
                        siguiente_estado_id AS hasta_estado_id,
                        estado_nombre AS desde_estado,
                        siguiente_estado_nombre AS hasta_estado,
                        COUNT(*) AS casos,
                        ROUND(AVG(EXTRACT(EPOCH FROM (siguiente_fecha - fecha_cambio)) / 3600.0)::numeric, 2) AS promedio_horas,
                        ROUND(AVG(EXTRACT(EPOCH FROM (siguiente_fecha - fecha_cambio)) / 86400.0)::numeric, 2) AS promedio_dias
                    FROM historial_ordenado
                    WHERE siguiente_estado_id IS NOT NULL
                    GROUP BY
                        estado_id,
                        siguiente_estado_id,
                        estado_nombre,
                        siguiente_estado_nombre
                    ORDER BY estado_id, siguiente_estado_id
                    """
                )

                return TiemposProcesoOut(
                    transiciones=[
                        TiempoEtapaOut(
                            desde_estado_id=int(r["desde_estado_id"]),
                            hasta_estado_id=int(r["hasta_estado_id"]),
                            desde_estado=r["desde_estado"],
                            hasta_estado=r["hasta_estado"],
                            casos=int(r["casos"]),
                            promedio_horas=float(r["promedio_horas"]) if r["promedio_horas"] is not None else None,
                            promedio_dias=float(r["promedio_dias"]) if r["promedio_dias"] is not None else None,
                        )
                        for r in rows
                    ]
                )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo tiempos de proceso: {str(e)}")


# ============================
# ENDPOINT 5 - ENCUESTAS
# ============================
@router.get("/api/stats/aspirantes/encuestas", response_model=EncuestaResumenOut)
def obtener_resumen_encuestas(
    fecha_desde: Optional[date] = Query(default=None),
    fecha_hasta: Optional[date] = Query(default=None),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                filtro, vals = construir_filtro_fechas(
                    "ei.created_at",
                    fecha_desde,
                    fecha_hasta,
                )

                row = fetch_one_dict(
                    cur,
                    f"""
                    SELECT
                        COUNT(*) AS total_registros,
                        COUNT(*) FILTER (WHERE ei.fecha_inicio IS NOT NULL) AS iniciadas,
                        COUNT(*) FILTER (WHERE ei.completada = true) AS completadas,
                        COUNT(*) FILTER (WHERE ei.abandonada = true) AS abandonadas,
                        COUNT(*) FILTER (WHERE ei.sincronizado = true) AS sincronizadas,
                        ROUND(AVG(COALESCE(ei.preguntas_respondidas, 0))::numeric, 2) AS preguntas_respondidas_promedio,
                        ROUND(
                            AVG(
                                CASE
                                    WHEN ei.fecha_inicio IS NOT NULL
                                     AND ei.fecha_fin IS NOT NULL
                                    THEN EXTRACT(EPOCH FROM (ei.fecha_fin - ei.fecha_inicio)) / 60.0
                                    ELSE NULL
                                END
                            )::numeric,
                            2
                        ) AS duracion_promedio_minutos
                    FROM aspirantes_encuesta_inicial ei
                    WHERE 1=1
                    {filtro}
                    """,
                    tuple(vals),
                )

                return EncuestaResumenOut(
                    total_registros=int(row.get("total_registros", 0) or 0),
                    iniciadas=int(row.get("iniciadas", 0) or 0),
                    completadas=int(row.get("completadas", 0) or 0),
                    abandonadas=int(row.get("abandonadas", 0) or 0),
                    sincronizadas=int(row.get("sincronizadas", 0) or 0),
                    preguntas_respondidas_promedio=float(row.get("preguntas_respondidas_promedio", 0) or 0),
                    duracion_promedio_minutos=float(row.get("duracion_promedio_minutos")) if row.get("duracion_promedio_minutos") is not None else None,
                )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo resumen de encuestas: {str(e)}")


# ============================
# ENDPOINT 6 - INVITACIONES
# ============================
@router.get("/api/stats/aspirantes/invitaciones", response_model=InvitacionResumenOut)
def obtener_resumen_invitaciones(
    fecha_desde: Optional[date] = Query(default=None),
    fecha_hasta: Optional[date] = Query(default=None),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                filtro, vals = construir_filtro_fechas(
                    "i.creado_en",
                    fecha_desde,
                    fecha_hasta,
                )

                row = fetch_one_dict(
                    cur,
                    f"""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE i.estado_invitacion = 'pendiente_envio') AS pendiente_envio,
                        COUNT(*) FILTER (WHERE i.estado_invitacion = 'enviada') AS enviadas,
                        COUNT(*) FILTER (WHERE LOWER(COALESCE(i.estado_invitacion, '')) IN ('aceptada', 'aceptado')) AS aceptadas_aspirante,
                        COUNT(*) FILTER (WHERE LOWER(COALESCE(i.estado_invitacion, '')) IN ('rechazada', 'rechazado')) AS rechazadas_aspirante,
                        COUNT(*) FILTER (WHERE LOWER(COALESCE(i.estado_tiktok, '')) IN ('aceptada', 'aceptado')) AS tiktok_aceptadas,
                        COUNT(*) FILTER (WHERE LOWER(COALESCE(i.estado_tiktok, '')) IN ('rechazada', 'rechazado')) AS tiktok_rechazadas,
                        COUNT(*) FILTER (WHERE i.fecha_incorporacion IS NOT NULL) AS incorporadas
                    FROM invitaciones i
                    WHERE 1=1
                    {filtro}
                    """,
                    tuple(vals),
                )

                return InvitacionResumenOut(
                    total=int(row.get("total", 0) or 0),
                    pendiente_envio=int(row.get("pendiente_envio", 0) or 0),
                    enviadas=int(row.get("enviadas", 0) or 0),
                    aceptadas_aspirante=int(row.get("aceptadas_aspirante", 0) or 0),
                    rechazadas_aspirante=int(row.get("rechazadas_aspirante", 0) or 0),
                    tiktok_aceptadas=int(row.get("tiktok_aceptadas", 0) or 0),
                    tiktok_rechazadas=int(row.get("tiktok_rechazadas", 0) or 0),
                    incorporadas=int(row.get("incorporadas", 0) or 0),
                )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo resumen de invitaciones: {str(e)}")


# ============================
# ENDPOINT 7 - AGENDAMIENTOS
# ============================
@router.get("/api/stats/aspirantes/agendamientos", response_model=AgendamientoResumenOut)
def obtener_resumen_agendamientos(
    fecha_desde: Optional[date] = Query(default=None),
    fecha_hasta: Optional[date] = Query(default=None),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                filtro, vals = construir_filtro_fechas(
                    "a.creado_en",
                    fecha_desde,
                    fecha_hasta,
                )

                row = fetch_one_dict(
                    cur,
                    f"""
                    SELECT
                        COUNT(DISTINCT a.id) AS total_agendamientos_aspirantes,
                        COUNT(DISTINCT ap.participante_id) AS aspirantes_con_agendamiento,
                        COUNT(DISTINCT a.id) FILTER (WHERE a.tipo_agendamiento = 2) AS entrevistas,
                        COUNT(DISTINCT a.id) FILTER (WHERE a.tipo_agendamiento = 1) AS pruebas,
                        ROUND(
                            AVG(
                                EXTRACT(EPOCH FROM (a.fecha_fin - a.fecha_inicio)) / 60.0
                            )::numeric,
                            2
                        ) AS duracion_promedio_minutos
                    FROM agendamientos a
                    INNER JOIN agendamientos_participantes ap
                        ON ap.agendamiento_id = a.id
                    WHERE ap.participante_tipo_id = %s
                    {filtro}
                    """,
                    tuple([PARTICIPANTE_TIPO_ASPIRANTE] + vals),
                )

                return AgendamientoResumenOut(
                    total_agendamientos_aspirantes=int(row.get("total_agendamientos_aspirantes", 0) or 0),
                    aspirantes_con_agendamiento=int(row.get("aspirantes_con_agendamiento", 0) or 0),
                    entrevistas=int(row.get("entrevistas", 0) or 0),
                    pruebas=int(row.get("pruebas", 0) or 0),
                    duracion_promedio_minutos=float(row.get("duracion_promedio_minutos")) if row.get("duracion_promedio_minutos") is not None else None,
                )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo resumen de agendamientos: {str(e)}")


# ============================
# ENDPOINT 8 - SERIE TEMPORAL
# ============================
@router.get("/api/stats/aspirantes/serie-ingresos", response_model=SerieTemporalOut)
def obtener_serie_ingresos(
    fecha_desde: Optional[date] = Query(default=None),
    fecha_hasta: Optional[date] = Query(default=None),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                filtro, vals = construir_filtro_fechas(
                    "a.creado_en",
                    fecha_desde,
                    fecha_hasta,
                )

                rows = fetch_all_dict(
                    cur,
                    f"""
                    SELECT
                        DATE(a.creado_en) AS fecha,
                        COUNT(*) AS total
                    FROM aspirantes a
                    WHERE 1=1
                    {filtro}
                    GROUP BY DATE(a.creado_en)
                    ORDER BY DATE(a.creado_en)
                    """,
                    tuple(vals),
                )

                return SerieTemporalOut(
                    serie=[
                        SerieItemOut(
                            fecha=str(r["fecha"]),
                            total=int(r["total"]),
                        )
                        for r in rows
                    ]
                )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo serie de ingresos: {str(e)}")