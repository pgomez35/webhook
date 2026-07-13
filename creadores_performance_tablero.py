import traceback
from datetime import date
from typing import Optional, Any, Dict, List, Tuple

from fastapi import APIRouter, HTTPException, Query, Depends
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field, field_validator

from DataBase import get_connection_context
from main_auth import obtener_usuario_actual, agente_para_filtro, es_manager

# Valor centinela: si un Manager no tiene `agente` asignado, se usa para que
# no coincida con ningún creador (el manager no ve nada en vez de verlo todo).
_AGENTE_SIN_ASIGNAR = "\x00__sin_agente__"


router = APIRouter()


# =========================================================
# SCHEMAS / MODELOS
# =========================================================

class RecalcularTableroIn(BaseModel):
    periodo_corte_fin: Optional[date] = None
    semanas_mostradas: int = Field(default=8, description="Puede ser 4 u 8")
    reemplazar_corte_activo: bool = True

    @field_validator("semanas_mostradas")
    @classmethod
    def validar_semanas_mostradas(cls, value: int) -> int:
        if value not in (4, 8):
            raise ValueError("semanas_mostradas debe ser 4 u 8")
        return value


class ObservacionSemanaIn(BaseModel):
    creador_tiktok_id: str
    creador_id: Optional[int] = None
    usuario_tiktok: Optional[str] = None

    periodo_inicio: date
    periodo_fin: date

    manager: Optional[str] = None
    grupo: Optional[str] = None

    estado_manual: Optional[str] = None
    observacion: Optional[str] = None
    recomendacion: Optional[str] = None

    creada_por: Optional[int] = None


# =========================================================
# HELPERS
# =========================================================

_WHERE_PERIODOS_SEMANALES = "COALESCE(tipo_periodo, 'semanal') = 'semanal'"


def _minutos_a_horas(minutos: Optional[int]) -> float:
    if not minutos:
        return 0.0
    return round(float(minutos) / 60, 2)


def _calcular_variacion_pct(actual: Optional[int], anterior: Optional[int]) -> Optional[float]:
    if anterior is None or anterior == 0:
        return None
    actual = actual or 0
    return round(((actual - anterior) / anterior) * 100, 2)


def _cargar_reglas(cur, tipo_regla: str, tipos_periodo: List[str]) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT
            codigo_estado,
            nombre_estado,
            valor_min,
            valor_max,
            prioridad
        FROM creadores_performance_reglas_estado
        WHERE activo = true
          AND tipo_regla = %s
          AND tipo_periodo = ANY(%s)
        ORDER BY prioridad DESC, valor_min NULLS FIRST
        """,
        (tipo_regla, tipos_periodo),
    )
    return cur.fetchall()


def _cargar_reglas_horas(cur) -> List[Dict[str, Any]]:
    return _cargar_reglas(cur, "horas_periodo", ["semanal", "todos"])


def _cargar_reglas_dias_incorporacion(cur) -> List[Dict[str, Any]]:
    return _cargar_reglas(cur, "dias_incorporacion", ["todos"])


def _resolver_regla_numerica(
    reglas: List[Dict[str, Any]],
    valor: Optional[float],
    default: Optional[str] = None,
) -> Optional[str]:
    if valor is None:
        return default

    for regla in reglas:
        valor_min = regla.get("valor_min")
        valor_max = regla.get("valor_max")

        cumple_min = valor_min is None or valor >= float(valor_min)
        cumple_max = valor_max is None or valor < float(valor_max)

        if cumple_min and cumple_max:
            return regla["nombre_estado"]

    return default


def _resolver_estado_horas(reglas: List[Dict[str, Any]], horas: float) -> str:
    return _resolver_regla_numerica(reglas, horas, "Sin estado") or "Sin estado"


def _resolver_rango_diamantes(cur, diamantes_mes: Optional[int]) -> Optional[Dict[str, Any]]:
    diamantes = diamantes_mes or 0

    cur.execute(
        """
        SELECT *
        FROM creadores_performance_rangos_diamantes
        WHERE activo = true
          AND %s >= diamantes_min
          AND (
                diamantes_max IS NULL
                OR %s < diamantes_max
              )
        ORDER BY orden ASC, diamantes_min ASC
        LIMIT 1
        """,
        (diamantes, diamantes),
    )

    return cur.fetchone()


def _resolver_objetivo(cur, reporte: Dict[str, Any], rango: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Prioridad:
    1. creador
    2. manager
    3. grupo
    4. rango
    5. agencia
    """

    id_rango = rango["id_rango"] if rango else None

    cur.execute(
        """
        SELECT *
        FROM creadores_performance_objetivos
        WHERE activo = true
          AND fecha_inicio <= %s
          AND (fecha_fin IS NULL OR fecha_fin >= %s)
          AND (
                (
                    nivel_aplicacion = 'creador'
                    AND (
                        creador_id = %s
                        OR creador_tiktok_id = %s
                    )
                )
                OR (
                    nivel_aplicacion = 'manager'
                    AND manager = %s
                )
                OR (
                    nivel_aplicacion = 'grupo'
                    AND grupo = %s
                )
                OR (
                    nivel_aplicacion = 'rango'
                    AND id_rango = %s
                )
                OR nivel_aplicacion = 'agencia'
              )
        ORDER BY
            CASE nivel_aplicacion
                WHEN 'creador' THEN 1
                WHEN 'manager' THEN 2
                WHEN 'grupo' THEN 3
                WHEN 'rango' THEN 4
                WHEN 'agencia' THEN 5
                ELSE 9
            END ASC,
            fecha_inicio DESC
        LIMIT 1
        """,
        (
            reporte["periodo_fin"],
            reporte["periodo_inicio"],
            reporte.get("creador_id"),
            reporte.get("creador_tiktok_id"),
            reporte.get("agente"),
            reporte.get("grupo"),
            id_rango,
        ),
    )

    objetivo = cur.fetchone()

    if objetivo:
        objetivo_mensual = objetivo.get("objetivo_diamantes_mes")
        objetivo_semanal = objetivo.get("objetivo_diamantes_semana")

        if objetivo_mensual and not objetivo_semanal:
            objetivo_semanal = round(objetivo_mensual / 4)

        return {
            "objetivo_mensual": objetivo_mensual,
            "objetivo_semanal": objetivo_semanal,
            "objetivo_horas_mes": objetivo.get("objetivo_horas_mes"),
            "objetivo_horas_semana": objetivo.get("objetivo_horas_semana"),
            "objetivo_dias_mes": objetivo.get("objetivo_dias_mes"),
            "objetivo_dias_semana": objetivo.get("objetivo_dias_semana"),
        }

    if rango:
        objetivo_mensual = rango.get("objetivo_diamantes_mes")
        objetivo_semanal = rango.get("objetivo_diamantes_semana")

        if objetivo_mensual and not objetivo_semanal:
            objetivo_semanal = round(objetivo_mensual / 4)

        return {
            "objetivo_mensual": objetivo_mensual,
            "objetivo_semanal": objetivo_semanal,
            "objetivo_horas_mes": rango.get("objetivo_horas_mes"),
            "objetivo_horas_semana": rango.get("objetivo_horas_semana"),
            "objetivo_dias_mes": rango.get("objetivo_dias_mes"),
            "objetivo_dias_semana": rango.get("objetivo_dias_semana"),
        }

    return {
        "objetivo_mensual": None,
        "objetivo_semanal": None,
        "objetivo_horas_mes": None,
        "objetivo_horas_semana": None,
        "objetivo_dias_mes": None,
        "objetivo_dias_semana": None,
    }


def _calcular_nivel_riesgo(reportes_creador: List[Dict[str, Any]]) -> str:
    if not reportes_creador:
        return "sin_datos"

    ultimos = reportes_creador[-2:]
    ultimo = reportes_creador[-1]

    horas_ultima = _minutos_a_horas(ultimo.get("duracion_live_minutos"))
    variacion = ultimo.get("variacion_diamantes_pct")

    semanas_inactivo = 0

    for r in ultimos:
        horas = _minutos_a_horas(r.get("duracion_live_minutos"))
        if horas < 8:
            semanas_inactivo += 1

    if semanas_inactivo >= 2:
        return "critico"

    if variacion is not None and variacion <= -40:
        return "alto"

    if horas_ultima < 8:
        return "alto"

    if horas_ultima < 18:
        return "medio"

    return "bajo"


def _resolver_rango_display(
    rango: Optional[Dict[str, Any]],
    reporte: Dict[str, Any],
) -> Tuple[Optional[str], Optional[str]]:
    if rango:
        return rango.get("codigo_rango"), rango.get("nombre_rango")

    estado_rango = reporte.get("estado_rango")
    if estado_rango:
        return estado_rango, estado_rango

    return None, None


def _calcular_estado_general(
    reporte: Dict[str, Any],
    estado_horas: str,
    reglas_nuevo: List[Dict[str, Any]],
) -> str:
    dias = reporte.get("dias_desde_incorporacion")
    estado_nuevo = _resolver_regla_numerica(
        reglas_nuevo,
        float(dias) if dias is not None else None,
    )

    if estado_nuevo:
        return estado_nuevo

    return estado_horas or "Sin estado"


def _tiene_texto_observacion(obs: Optional[Dict[str, Any]]) -> bool:
    if not obs:
        return False

    for campo in ("observacion", "recomendacion"):
        texto = obs.get(campo)
        if texto and str(texto).strip():
            return True

    return False


def _obtener_periodos_ventana(cur, semanas_mostradas: int, periodo_corte_fin: Optional[date]):
    if semanas_mostradas not in [4, 8]:
        raise HTTPException(
            status_code=400,
            detail="semanas_mostradas debe ser 4 u 8."
        )

    if periodo_corte_fin:
        cur.execute(
            f"""
            SELECT DISTINCT
                periodo_inicio,
                periodo_fin
            FROM creadores_reporte_integral
            WHERE {_WHERE_PERIODOS_SEMANALES}
              AND periodo_fin <= %s
            ORDER BY periodo_fin DESC
            LIMIT %s
            """,
            (periodo_corte_fin, semanas_mostradas),
        )
    else:
        cur.execute(
            f"""
            SELECT DISTINCT
                periodo_inicio,
                periodo_fin
            FROM creadores_reporte_integral
            WHERE {_WHERE_PERIODOS_SEMANALES}
            ORDER BY periodo_fin DESC
            LIMIT %s
            """,
            (semanas_mostradas,),
        )

    periodos_desc = cur.fetchall()

    if not periodos_desc:
        raise HTTPException(
            status_code=404,
            detail="No hay periodos semanales cargados en creadores_reporte_integral."
        )

    # Los dejamos de antiguo a reciente.
    return list(reversed(periodos_desc))


def _obtener_reportes_de_periodos(cur, periodos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    conditions = []
    params = []

    for p in periodos:
        conditions.append("(periodo_inicio = %s AND periodo_fin = %s)")
        params.extend([p["periodo_inicio"], p["periodo_fin"]])

    where_periodos = " OR ".join(conditions)

    query = f"""
        SELECT DISTINCT ON (creador_tiktok_id, periodo_inicio, periodo_fin)
            id_reporte,
            creador_tiktok_id,
            creador_id,
            usuario_tiktok,
            grupo,
            agente,
            periodo_inicio,
            periodo_fin,
            hora_incorporacion,
            dias_desde_incorporacion,
            estado_graduacion,
            estado_rango,
            diamantes_totales,
            duracion_live_minutos,
            dias_validos_emisiones_live,
            nuevos_seguidores,
            emisiones_live,
            diamantes_mes,
            duracion_live_mes_minutos,
            dias_validos_live_mes,
            nuevos_seguidores_mes,
            emisiones_live_mes,
            partidas,
            diamantes_de_partidas
        FROM creadores_reporte_integral
        WHERE ({where_periodos})
          AND {_WHERE_PERIODOS_SEMANALES}
        ORDER BY
            creador_tiktok_id,
            periodo_inicio,
            periodo_fin,
            fecha_carga DESC NULLS LAST,
            id_reporte DESC
    """

    cur.execute(query, params)
    rows = cur.fetchall()

    # Calculamos variación semanal visible por creador.
    agrupados = {}

    for row in rows:
        key = row["creador_tiktok_id"]
        agrupados.setdefault(key, []).append(dict(row))

    resultado = []

    for creador_tiktok_id, reportes in agrupados.items():
        reportes = sorted(reportes, key=lambda r: (r["periodo_inicio"], r["periodo_fin"]))

        anterior = None

        for r in reportes:
            r["variacion_diamantes_pct"] = _calcular_variacion_pct(
                r.get("diamantes_totales"),
                anterior.get("diamantes_totales") if anterior else None
            )
            resultado.append(r)
            anterior = r

    return resultado


def _agrupar_por_creador(reportes: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    agrupados = {}

    for r in reportes:
        agrupados.setdefault(r["creador_tiktok_id"], []).append(r)

    for key in agrupados:
        agrupados[key] = sorted(
            agrupados[key],
            key=lambda r: (r["periodo_inicio"], r["periodo_fin"])
        )

    return agrupados


# =========================================================
# ENDPOINT: RECALCULAR TABLERO
# =========================================================

@router.post("/api/creadores/performance/tablero/recalcular")
def recalcular_tablero_performance(payload: RecalcularTableroIn):
    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                periodos = _obtener_periodos_ventana(
                    cur,
                    payload.semanas_mostradas,
                    payload.periodo_corte_fin
                )

                periodo_corte_inicio = periodos[0]["periodo_inicio"]
                periodo_corte_fin = periodos[-1]["periodo_fin"]

                reportes = _obtener_reportes_de_periodos(cur, periodos)
                reportes_por_creador = _agrupar_por_creador(reportes)

                reglas_horas = _cargar_reglas_horas(cur)
                reglas_nuevo = _cargar_reglas_dias_incorporacion(cur)

                if payload.reemplazar_corte_activo:
                    cur.execute(
                        """
                        UPDATE creadores_performance_tablero_cortes
                        SET estado = 'historico'
                        WHERE estado = 'activo'
                          AND semanas_mostradas = %s
                        """,
                        (payload.semanas_mostradas,),
                    )

                cur.execute(
                    """
                    INSERT INTO creadores_performance_tablero_cortes (
                        periodo_corte_inicio,
                        periodo_corte_fin,
                        semanas_mostradas,
                        estado,
                        fecha_calculo
                    )
                    VALUES (%s, %s, %s, 'activo', NOW())
                    RETURNING id_corte
                    """,
                    (
                        periodo_corte_inicio,
                        periodo_corte_fin,
                        payload.semanas_mostradas,
                    ),
                )

                id_corte = cur.fetchone()["id_corte"]

                total_creadores = 0
                total_semanas = 0

                periodos_por_key = {
                    (p["periodo_inicio"], p["periodo_fin"]): idx + 1
                    for idx, p in enumerate(periodos)
                }

                for creador_tiktok_id, lista_reportes in reportes_por_creador.items():
                    latest = lista_reportes[-1]

                    horas_ultimo_mes = _minutos_a_horas(latest.get("duracion_live_mes_minutos"))

                    rango = _resolver_rango_diamantes(
                        cur,
                        latest.get("diamantes_mes")
                    )

                    objetivo = _resolver_objetivo(cur, latest, rango)

                    horas_ultima_semana = _minutos_a_horas(latest.get("duracion_live_minutos"))
                    estado_horas = _resolver_estado_horas(reglas_horas, horas_ultima_semana)
                    estado_general = _calcular_estado_general(latest, estado_horas, reglas_nuevo)
                    nivel_riesgo = _calcular_nivel_riesgo(lista_reportes)
                    rango_codigo, rango_nombre = _resolver_rango_display(rango, latest)

                    cur.execute(
                        """
                        INSERT INTO creadores_performance_tablero_creadores (
                            id_corte,
                            creador_tiktok_id,
                            creador_id,
                            usuario_tiktok,
                            grupo,
                            manager_actual,
                            dias_desde_incorporacion,
                            rango_codigo,
                            rango_nombre,
                            diamantes_ultimo_mes,
                            horas_ultimo_mes,
                            dias_ultimo_mes,
                            objetivo_mensual,
                            objetivo_semanal,
                            objetivo_horas_mes,
                            objetivo_horas_semana,
                            objetivo_dias_mes,
                            objetivo_dias_semana,
                            variacion_ultima_semana_pct,
                            estado_general,
                            nivel_riesgo,
                            fecha_actualizacion
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s,
                            %s, %s,
                            %s, %s,
                            %s, %s,
                            %s, %s, %s,
                            NOW()
                        )
                        RETURNING id_tablero_creador
                        """,
                        (
                            id_corte,
                            latest.get("creador_tiktok_id"),
                            latest.get("creador_id"),
                            latest.get("usuario_tiktok"),
                            latest.get("grupo"),
                            latest.get("agente"),
                            latest.get("dias_desde_incorporacion"),
                            rango_codigo,
                            rango_nombre,
                            latest.get("diamantes_mes") or 0,
                            horas_ultimo_mes,
                            latest.get("dias_validos_live_mes") or 0,
                            objetivo.get("objetivo_mensual"),
                            objetivo.get("objetivo_semanal"),
                            objetivo.get("objetivo_horas_mes"),
                            objetivo.get("objetivo_horas_semana"),
                            objetivo.get("objetivo_dias_mes"),
                            objetivo.get("objetivo_dias_semana"),
                            latest.get("variacion_diamantes_pct"),
                            estado_general,
                            nivel_riesgo,
                        ),
                    )

                    id_tablero_creador = cur.fetchone()["id_tablero_creador"]
                    total_creadores += 1

                    reportes_por_periodo = {
                        (r["periodo_inicio"], r["periodo_fin"]): r
                        for r in lista_reportes
                    }

                    for p in periodos:
                        periodo_key = (p["periodo_inicio"], p["periodo_fin"])
                        semana_orden = periodos_por_key[periodo_key]
                        r = reportes_por_periodo.get(periodo_key)

                        if r:
                            horas = _minutos_a_horas(r.get("duracion_live_minutos"))
                            estado_auto = _resolver_estado_horas(reglas_horas, horas)
                            diamantes = r.get("diamantes_totales") or 0
                            dias = r.get("dias_validos_emisiones_live") or 0
                            manager_semana = r.get("agente")
                            variacion = r.get("variacion_diamantes_pct")
                        else:
                            horas = 0
                            estado_auto = "Sin dato"
                            diamantes = 0
                            dias = 0
                            manager_semana = latest.get("agente")
                            variacion = None

                        cur.execute(
                            """
                            SELECT
                                estado_manual,
                                observacion,
                                recomendacion
                            FROM creadores_performance_observaciones
                            WHERE creador_tiktok_id = %s
                              AND periodo_inicio = %s
                              AND periodo_fin = %s
                              AND activo = true
                            LIMIT 1
                            """,
                            (
                                creador_tiktok_id,
                                p["periodo_inicio"],
                                p["periodo_fin"],
                            ),
                        )
                        obs = cur.fetchone()

                        cur.execute(
                            """
                            INSERT INTO creadores_performance_tablero_semanas (
                                id_tablero_creador,
                                semana_orden,
                                periodo_inicio,
                                periodo_fin,
                                diamantes,
                                horas,
                                dias,
                                manager_semana,
                                estado_auto,
                                estado_manual,
                                variacion_diamantes_pct,
                                tiene_observacion,
                                fecha_actualizacion
                            )
                            VALUES (
                                %s, %s, %s, %s,
                                %s, %s, %s,
                                %s, %s, %s,
                                %s, %s,
                                NOW()
                            )
                            """,
                            (
                                id_tablero_creador,
                                semana_orden,
                                p["periodo_inicio"],
                                p["periodo_fin"],
                                diamantes,
                                horas,
                                dias,
                                manager_semana,
                                estado_auto,
                                obs.get("estado_manual") if obs else None,
                                variacion,
                                _tiene_texto_observacion(obs),
                            ),
                        )

                        total_semanas += 1

        return {
            "ok": True,
            "mensaje": "Tablero recalculado correctamente.",
            "id_corte": id_corte,
            "periodo_corte_inicio": periodo_corte_inicio,
            "periodo_corte_fin": periodo_corte_fin,
            "semanas_mostradas": payload.semanas_mostradas,
            "total_creadores": total_creadores,
            "total_semanas": total_semanas,
        }

    except HTTPException:
        raise

    except Exception as e:
        print("❌ Error recalculando tablero:", e)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Error recalculando tablero de performance"
        )


# =========================================================
# ENDPOINT: LISTAR CORTES
# =========================================================

@router.get("/api/creadores/performance/tablero/cortes")
def listar_cortes_tablero(
    semanas_mostradas: Optional[int] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                if semanas_mostradas:
                    cur.execute(
                        """
                        SELECT *
                        FROM creadores_performance_tablero_cortes
                        WHERE semanas_mostradas = %s
                        ORDER BY periodo_corte_fin DESC, id_corte DESC
                        LIMIT %s
                        """,
                        (semanas_mostradas, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT *
                        FROM creadores_performance_tablero_cortes
                        ORDER BY periodo_corte_fin DESC, id_corte DESC
                        LIMIT %s
                        """,
                        (limit,),
                    )

                rows = cur.fetchall()

        return {
            "ok": True,
            "total": len(rows),
            "cortes": rows,
        }

    except Exception as e:
        print("❌ Error listando cortes:", e)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Error listando cortes del tablero"
        )


# =========================================================
# ENDPOINT: OBTENER TABLERO ACTUAL
# =========================================================

@router.get("/api/creadores/performance/tablero/actual")
def obtener_tablero_actual(
    semanas_mostradas: int = Query(8),
    semanas_visibles: int = Query(8),
    manager: Optional[str] = Query(None),
    grupo: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        if semanas_mostradas not in [4, 8]:
            raise HTTPException(status_code=400, detail="semanas_mostradas debe ser 4 u 8.")

        if semanas_visibles not in [4, 8]:
            raise HTTPException(status_code=400, detail="semanas_visibles debe ser 4 u 8.")

        if semanas_visibles > semanas_mostradas:
            semanas_visibles = semanas_mostradas

        # Si el usuario es Manager (rol_id=2), forzamos el filtro a su propio
        # agente y se ignora el query param `manager` para que solo vea lo suyo.
        if es_manager(usuario):
            manager = agente_para_filtro(usuario) or _AGENTE_SIN_ASIGNAR

        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                cur.execute(
                    """
                    SELECT *
                    FROM creadores_performance_tablero_cortes
                    WHERE estado = 'activo'
                      AND semanas_mostradas = %s
                    ORDER BY periodo_corte_fin DESC, id_corte DESC
                    LIMIT 1
                    """,
                    (semanas_mostradas,),
                )

                corte = cur.fetchone()

                if not corte:
                    raise HTTPException(
                        status_code=404,
                        detail="No hay tablero activo. Primero recalcula el tablero."
                    )

                filtros = ["id_corte = %s"]
                params = [corte["id_corte"]]

                if manager:
                    filtros.append("LOWER(manager_actual) = LOWER(%s)")
                    params.append(manager)

                if grupo:
                    filtros.append("LOWER(grupo) = LOWER(%s)")
                    params.append(grupo)

                if search:
                    filtros.append(
                        """
                        (
                            LOWER(usuario_tiktok) LIKE LOWER(%s)
                            OR LOWER(creador_tiktok_id) LIKE LOWER(%s)
                        )
                        """
                    )
                    params.extend([f"%{search}%", f"%{search}%"])

                where_sql = " AND ".join(filtros)

                cur.execute(
                    f"""
                    SELECT COUNT(*) AS total
                    FROM creadores_performance_tablero_creadores
                    WHERE {where_sql}
                    """,
                    params,
                )
                total = cur.fetchone()["total"]

                cur.execute(
                    f"""
                    SELECT *
                    FROM creadores_performance_tablero_creadores
                    WHERE {where_sql}
                    ORDER BY
                        CASE nivel_riesgo
                            WHEN 'critico' THEN 1
                            WHEN 'alto' THEN 2
                            WHEN 'medio' THEN 3
                            WHEN 'bajo' THEN 4
                            WHEN 'sin_datos' THEN 5
                            ELSE 6
                        END,
                        manager_actual ASC NULLS LAST,
                        usuario_tiktok ASC NULLS LAST
                    LIMIT %s OFFSET %s
                    """,
                    params + [limit, offset],
                )

                creadores = cur.fetchall()

                if not creadores:
                    return {
                        "ok": True,
                        "corte": corte,
                        "total": total,
                        "creadores": [],
                    }

                ids_tablero = [c["id_tablero_creador"] for c in creadores]

                min_semana = corte["semanas_mostradas"] - semanas_visibles + 1

                placeholders = ",".join(["%s"] * len(ids_tablero))

                cur.execute(
                    f"""
                    SELECT
                        s.*,
                        o.observacion,
                        o.recomendacion,
                        o.estado_manual AS estado_manual_observacion
                    FROM creadores_performance_tablero_semanas s
                    INNER JOIN creadores_performance_tablero_creadores tc
                        ON tc.id_tablero_creador = s.id_tablero_creador
                    LEFT JOIN creadores_performance_observaciones o
                        ON o.creador_tiktok_id = tc.creador_tiktok_id
                       AND o.periodo_inicio = s.periodo_inicio
                       AND o.periodo_fin = s.periodo_fin
                       AND o.activo = true
                    WHERE s.id_tablero_creador IN ({placeholders})
                      AND s.semana_orden >= %s
                    ORDER BY s.id_tablero_creador, s.semana_orden
                    """,
                    ids_tablero + [min_semana],
                )

                semanas = cur.fetchall()

                semanas_por_creador = {}

                for s in semanas:
                    semanas_por_creador.setdefault(
                        s["id_tablero_creador"],
                        []
                    ).append(s)

                resultado = []

                for c in creadores:
                    item = dict(c)
                    item["semanas"] = semanas_por_creador.get(
                        c["id_tablero_creador"],
                        []
                    )
                    resultado.append(item)

        return {
            "ok": True,
            "corte": corte,
            "total": total,
            "limit": limit,
            "offset": offset,
            "semanas_visibles": semanas_visibles,
            "creadores": resultado,
        }

    except HTTPException:
        raise

    except Exception as e:
        print("❌ Error obteniendo tablero actual:", e)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Error obteniendo tablero actual"
        )


# =========================================================
# ENDPOINT: GUARDAR OBSERVACIÓN SEMANAL
# =========================================================

@router.post("/api/creadores/performance/tablero/observacion")
def guardar_observacion_semana(payload: ObservacionSemanaIn):
    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                cur.execute(
                    """
                    INSERT INTO creadores_performance_observaciones (
                        creador_tiktok_id,
                        creador_id,
                        usuario_tiktok,
                        periodo_inicio,
                        periodo_fin,
                        manager,
                        grupo,
                        estado_manual,
                        observacion,
                        recomendacion,
                        creada_por,
                        fecha_creacion,
                        fecha_actualizacion,
                        activo
                    )
                    VALUES (
                        %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s,
                        NOW(),
                        NOW(),
                        true
                    )
                    ON CONFLICT (creador_tiktok_id, periodo_inicio, periodo_fin)
                    DO UPDATE SET
                        creador_id = EXCLUDED.creador_id,
                        usuario_tiktok = EXCLUDED.usuario_tiktok,
                        manager = EXCLUDED.manager,
                        grupo = EXCLUDED.grupo,
                        estado_manual = EXCLUDED.estado_manual,
                        observacion = EXCLUDED.observacion,
                        recomendacion = EXCLUDED.recomendacion,
                        fecha_actualizacion = NOW(),
                        activo = true
                    RETURNING id_observacion
                    """,
                    (
                        payload.creador_tiktok_id,
                        payload.creador_id,
                        payload.usuario_tiktok,
                        payload.periodo_inicio,
                        payload.periodo_fin,
                        payload.manager,
                        payload.grupo,
                        payload.estado_manual,
                        payload.observacion,
                        payload.recomendacion,
                        payload.creada_por,
                    ),
                )

                id_observacion = cur.fetchone()["id_observacion"]

                tiene_observacion = bool(
                    (payload.observacion and str(payload.observacion).strip())
                    or (payload.recomendacion and str(payload.recomendacion).strip())
                )

                # Actualiza el tablero actual si esa semana está visible.
                cur.execute(
                    """
                    UPDATE creadores_performance_tablero_semanas s
                    SET
                        estado_manual = %s,
                        tiene_observacion = %s,
                        fecha_actualizacion = NOW()
                    FROM creadores_performance_tablero_creadores tc
                    INNER JOIN creadores_performance_tablero_cortes co
                        ON co.id_corte = tc.id_corte
                    WHERE s.id_tablero_creador = tc.id_tablero_creador
                      AND co.estado = 'activo'
                      AND tc.creador_tiktok_id = %s
                      AND s.periodo_inicio = %s
                      AND s.periodo_fin = %s
                    """,
                    (
                        payload.estado_manual,
                        tiene_observacion,
                        payload.creador_tiktok_id,
                        payload.periodo_inicio,
                        payload.periodo_fin,
                    ),
                )

        return {
            "ok": True,
            "mensaje": "Observación guardada correctamente.",
            "id_observacion": id_observacion,
        }

    except Exception as e:
        print("❌ Error guardando observación:", e)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Error guardando observación semanal"
        )


# =========================================================
# ENDPOINT: RESUMEN POR MANAGER
# =========================================================

@router.get("/api/creadores/performance/tablero/resumen-managers")
def obtener_resumen_managers_tablero(
    semanas_mostradas: int = Query(8),
    usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        if semanas_mostradas not in [4, 8]:
            raise HTTPException(status_code=400, detail="semanas_mostradas debe ser 4 u 8.")

        # Manager (rol_id=2) solo ve su propia fila de resumen.
        agente_manager = None
        if es_manager(usuario):
            agente_manager = agente_para_filtro(usuario) or _AGENTE_SIN_ASIGNAR

        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                cur.execute(
                    """
                    SELECT *
                    FROM creadores_performance_tablero_cortes
                    WHERE estado = 'activo'
                      AND semanas_mostradas = %s
                    ORDER BY periodo_corte_fin DESC, id_corte DESC
                    LIMIT 1
                    """,
                    (semanas_mostradas,),
                )

                corte = cur.fetchone()

                if not corte:
                    raise HTTPException(
                        status_code=404,
                        detail="No hay tablero activo para resumir."
                    )

                cur.execute(
                    """
                    SELECT
                        COALESCE(manager_actual, 'Sin manager') AS manager,

                        COUNT(*) AS total_creadores,

                        COALESCE(SUM(diamantes_ultimo_mes), 0) AS total_diamantes_ultimo_mes,

                        ROUND(AVG(horas_ultimo_mes), 2) AS promedio_horas_ultimo_mes,

                        ROUND(AVG(dias_ultimo_mes), 2) AS promedio_dias_ultimo_mes,

                        COUNT(*) FILTER (
                            WHERE nivel_riesgo = 'critico'
                        ) AS creadores_riesgo_critico,

                        COUNT(*) FILTER (
                            WHERE nivel_riesgo = 'alto'
                        ) AS creadores_riesgo_alto,

                        COUNT(*) FILTER (
                            WHERE estado_general = 'Nuevo'
                        ) AS creadores_nuevos,

                        COUNT(*) FILTER (
                            WHERE variacion_ultima_semana_pct < 0
                        ) AS creadores_bajando,

                        COUNT(*) FILTER (
                            WHERE variacion_ultima_semana_pct > 0
                        ) AS creadores_subiendo

                    FROM creadores_performance_tablero_creadores
                    WHERE id_corte = %s
                      AND (%s IS NULL OR LOWER(manager_actual) = LOWER(%s))
                    GROUP BY COALESCE(manager_actual, 'Sin manager')
                    ORDER BY total_diamantes_ultimo_mes DESC
                    """,
                    (corte["id_corte"], agente_manager, agente_manager),
                )

                rows = cur.fetchall()

        return {
            "ok": True,
            "corte": corte,
            "total_managers": len(rows),
            "managers": rows,
        }

    except HTTPException:
        raise

    except Exception as e:
        print("❌ Error obteniendo resumen por managers:", e)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Error obteniendo resumen por managers"
        )