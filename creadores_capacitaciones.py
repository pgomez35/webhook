import traceback
from datetime import date
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Query, Depends
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from DataBase import get_connection_context
from main_auth import obtener_usuario_actual, es_manager, credenciales_manager_para_filtro

# Valor centinela: si un Manager no tiene credenciales útiles, no ve creadores.
_AGENTE_SIN_ASIGNAR = "\x00__sin_agente__"


def _filtro_sql_manager_reporte(
    *,
    col_manager_id: str = "manager_id",
    col_agente: str = "agente",
) -> str:
    """SQL fragment: manager_id preferente + fallback por agente/email."""
    return f"""
        (
            {col_manager_id} = %s
            OR (
                {col_manager_id} IS NULL
                AND (
                    LOWER(TRIM({col_agente})) = LOWER(TRIM(%s))
                    OR LOWER(TRIM({col_agente})) = LOWER(TRIM(%s))
                )
            )
        )
    """


def _params_manager_logueado(creds: Optional[Dict[str, Any]]) -> List[Any]:
    if not creds or not creds.get("id"):
        return [-1, _AGENTE_SIN_ASIGNAR, _AGENTE_SIN_ASIGNAR]
    return [
        creds["id"],
        creds.get("agente") or _AGENTE_SIN_ASIGNAR,
        creds.get("email") or _AGENTE_SIN_ASIGNAR,
    ]


router = APIRouter()


# =========================================================
# SCHEMAS
# =========================================================

class CapacitacionIn(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    categoria: Optional[str] = None
    obligatoria: bool = True
    activa: bool = True
    orden: int = 1


class CapacitacionUpdateIn(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    categoria: Optional[str] = None
    obligatoria: Optional[bool] = None
    activa: Optional[bool] = None
    orden: Optional[int] = None


class SeguimientoCapacitacionIn(BaseModel):
    creador_id: Optional[int] = None
    creador_tiktok_id: str
    usuario_tiktok: Optional[str] = None

    manager: Optional[str] = None
    manager_id: Optional[int] = None
    grupo: Optional[str] = None

    id_capacitacion: int

    estado: str = "pendiente"  # pendiente | realizada | no_aplica
    fecha_realizacion: Optional[date] = None
    observacion: Optional[str] = None

    actualizado_por: Optional[int] = None


# =========================================================
# HELPERS
# =========================================================

def _normalizar_estado_capacitacion(estado: str) -> str:
    estado = (estado or "pendiente").strip().lower()

    if estado not in ["pendiente", "realizada", "no_aplica"]:
        raise HTTPException(
            status_code=400,
            detail="Estado inválido. Usa: pendiente, realizada o no_aplica."
        )

    return estado


def _obtener_capacitaciones_activas(cur):
    cur.execute(
        """
        SELECT
            id_capacitacion,
            nombre,
            descripcion,
            categoria,
            obligatoria,
            activa,
            orden
        FROM creadores_capacitaciones
        WHERE activa = true
        ORDER BY orden ASC, nombre ASC
        """
    )
    return cur.fetchall()


# =========================================================
# ENDPOINT: LISTAR CATÁLOGO
# =========================================================

@router.get("/api/creadores/capacitaciones/catalogo")
def listar_capacitaciones(
    incluir_inactivas: bool = Query(False),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                if incluir_inactivas:
                    cur.execute(
                        """
                        SELECT *
                        FROM creadores_capacitaciones
                        ORDER BY orden ASC, nombre ASC
                        """
                    )
                else:
                    cur.execute(
                        """
                        SELECT *
                        FROM creadores_capacitaciones
                        WHERE activa = true
                        ORDER BY orden ASC, nombre ASC
                        """
                    )

                rows = cur.fetchall()

        return {
            "ok": True,
            "total": len(rows),
            "capacitaciones": rows,
        }

    except Exception as e:
        print("❌ Error listando capacitaciones:", e)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Error listando capacitaciones"
        )


# =========================================================
# ENDPOINT: CREAR CAPACITACIÓN
# =========================================================

@router.post("/api/creadores/capacitaciones/catalogo")
def crear_capacitacion(payload: CapacitacionIn):
    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                cur.execute(
                    """
                    INSERT INTO creadores_capacitaciones (
                        nombre,
                        descripcion,
                        categoria,
                        obligatoria,
                        activa,
                        orden,
                        fecha_creacion,
                        fecha_actualizacion
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (nombre)
                    DO UPDATE SET
                        descripcion = EXCLUDED.descripcion,
                        categoria = EXCLUDED.categoria,
                        obligatoria = EXCLUDED.obligatoria,
                        activa = EXCLUDED.activa,
                        orden = EXCLUDED.orden,
                        fecha_actualizacion = NOW()
                    RETURNING *
                    """,
                    (
                        payload.nombre,
                        payload.descripcion,
                        payload.categoria,
                        payload.obligatoria,
                        payload.activa,
                        payload.orden,
                    ),
                )

                row = cur.fetchone()

        return {
            "ok": True,
            "mensaje": "Capacitación guardada correctamente.",
            "capacitacion": row,
        }

    except Exception as e:
        print("❌ Error creando capacitación:", e)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Error creando capacitación"
        )


# =========================================================
# ENDPOINT: ACTUALIZAR CAPACITACIÓN
# =========================================================

@router.put("/api/creadores/capacitaciones/catalogo/{id_capacitacion}")
def actualizar_capacitacion(
    id_capacitacion: int,
    payload: CapacitacionUpdateIn,
):
    try:
        campos = []
        valores = []

        data = payload.model_dump(exclude_unset=True)

        for campo, valor in data.items():
            campos.append(f"{campo} = %s")
            valores.append(valor)

        if not campos:
            raise HTTPException(
                status_code=400,
                detail="No enviaste campos para actualizar."
            )

        campos.append("fecha_actualizacion = NOW()")
        valores.append(id_capacitacion)

        sql = f"""
            UPDATE creadores_capacitaciones
            SET {", ".join(campos)}
            WHERE id_capacitacion = %s
            RETURNING *
        """

        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                cur.execute(sql, valores)
                row = cur.fetchone()

                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail="Capacitación no encontrada."
                    )

        return {
            "ok": True,
            "mensaje": "Capacitación actualizada correctamente.",
            "capacitacion": row,
        }

    except HTTPException:
        raise

    except Exception as e:
        print("❌ Error actualizando capacitación:", e)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Error actualizando capacitación"
        )


# =========================================================
# ENDPOINT: MATRIZ DE CAPACITACIONES
# =========================================================

@router.get("/api/creadores/capacitaciones/matriz")
def obtener_matriz_capacitaciones(
    manager: Optional[str] = Query(None),
    grupo: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    usuario: dict = Depends(obtener_usuario_actual),
):
    """
    Devuelve una matriz tipo Excel:
    creador -> capacitaciones -> estado.
    La fuente de creadores es el último registro de creadores_reporte_integral.
    """

    try:
        # Manager (rol_id=2) solo ve sus creadores: filtramos por manager_id
        # (fallback legacy por agente/email) e ignoramos el query param.
        manager_creds = None
        if es_manager(usuario):
            manager_creds = credenciales_manager_para_filtro(usuario)
            manager = None

        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                capacitaciones = _obtener_capacitaciones_activas(cur)

                filtros = []
                params = []

                if manager_creds is not None:
                    filtros.append(_filtro_sql_manager_reporte())
                    params.extend(_params_manager_logueado(manager_creds))
                elif manager:
                    valor = str(manager).strip()
                    if valor.isdigit():
                        filtros.append("manager_id = %s")
                        params.append(int(valor))
                    else:
                        filtros.append("LOWER(TRIM(manager)) = LOWER(TRIM(%s))")
                        params.append(valor)

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

                where_sql = ""
                if filtros:
                    where_sql = "WHERE " + " AND ".join(filtros)

                cur.execute(
                    f"""
                    WITH ultimos AS (
                        SELECT DISTINCT ON (r.creador_tiktok_id)
                            r.creador_tiktok_id,
                            r.creador_id,
                            r.usuario_tiktok,
                            r.manager_id,
                            r.agente,
                            COALESCE(a.nombre_completo, r.agente, 'Sin manager') AS manager,
                            COALESCE(r.grupo, 'Sin grupo') AS grupo,
                            r.periodo_fin
                        FROM creadores_reporte_integral r
                        LEFT JOIN administradores a ON a.id = r.manager_id
                        WHERE r.creador_tiktok_id IS NOT NULL
                        ORDER BY r.creador_tiktok_id, r.periodo_fin DESC
                    )
                    SELECT COUNT(*) AS total
                    FROM ultimos
                    {where_sql}
                    """,
                    params,
                )

                total = cur.fetchone()["total"]

                cur.execute(
                    f"""
                    WITH ultimos AS (
                        SELECT DISTINCT ON (r.creador_tiktok_id)
                            r.creador_tiktok_id,
                            r.creador_id,
                            r.usuario_tiktok,
                            r.manager_id,
                            r.agente,
                            COALESCE(a.nombre_completo, r.agente, 'Sin manager') AS manager,
                            COALESCE(r.grupo, 'Sin grupo') AS grupo,
                            r.periodo_fin
                        FROM creadores_reporte_integral r
                        LEFT JOIN administradores a ON a.id = r.manager_id
                        WHERE r.creador_tiktok_id IS NOT NULL
                        ORDER BY r.creador_tiktok_id, r.periodo_fin DESC
                    )
                    SELECT *
                    FROM ultimos
                    {where_sql}
                    ORDER BY manager ASC, usuario_tiktok ASC
                    LIMIT %s OFFSET %s
                    """,
                    params + [limit, offset],
                )

                creadores = cur.fetchall()

                if not creadores:
                    return {
                        "ok": True,
                        "total": total,
                        "limit": limit,
                        "offset": offset,
                        "capacitaciones": capacitaciones,
                        "creadores": [],
                    }

                creador_ids_tiktok = [c["creador_tiktok_id"] for c in creadores]
                capacitacion_ids = [c["id_capacitacion"] for c in capacitaciones]

                if not capacitacion_ids:
                    return {
                        "ok": True,
                        "total": total,
                        "limit": limit,
                        "offset": offset,
                        "capacitaciones": [],
                        "creadores": creadores,
                    }

                cur.execute(
                    """
                    SELECT *
                    FROM creadores_capacitaciones_seguimiento
                    WHERE creador_tiktok_id = ANY(%s)
                      AND id_capacitacion = ANY(%s)
                    """,
                    (creador_ids_tiktok, capacitacion_ids),
                )

                seguimientos = cur.fetchall()

                seguimiento_map = {
                    (s["creador_tiktok_id"], s["id_capacitacion"]): s
                    for s in seguimientos
                }

                resultado_creadores = []

                for creador in creadores:
                    item = dict(creador)
                    item["capacitaciones"] = []

                    for cap in capacitaciones:
                        key = (
                            creador["creador_tiktok_id"],
                            cap["id_capacitacion"],
                        )

                        seg = seguimiento_map.get(key)

                        item["capacitaciones"].append({
                            "id_capacitacion": cap["id_capacitacion"],
                            "nombre": cap["nombre"],
                            "obligatoria": cap["obligatoria"],
                            "orden": cap["orden"],
                            "estado": seg["estado"] if seg else "pendiente",
                            "fecha_realizacion": seg["fecha_realizacion"] if seg else None,
                            "observacion": seg["observacion"] if seg else None,
                            "id_seguimiento": seg["id_seguimiento"] if seg else None,
                        })

                    resultado_creadores.append(item)

        return {
            "ok": True,
            "total": total,
            "limit": limit,
            "offset": offset,
            "capacitaciones": capacitaciones,
            "creadores": resultado_creadores,
        }

    except Exception as e:
        print("❌ Error obteniendo matriz de capacitaciones:", e)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Error obteniendo matriz de capacitaciones"
        )


# =========================================================
# ENDPOINT: GUARDAR ESTADO DE UNA CAPACITACIÓN
# =========================================================

@router.post("/api/creadores/capacitaciones/seguimiento")
def guardar_seguimiento_capacitacion(payload: SeguimientoCapacitacionIn):
    try:
        estado = _normalizar_estado_capacitacion(payload.estado)

        fecha_realizacion = payload.fecha_realizacion

        if estado == "realizada" and fecha_realizacion is None:
            fecha_realizacion = date.today()

        if estado == "pendiente":
            fecha_realizacion = None

        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                cur.execute(
                    """
                    INSERT INTO creadores_capacitaciones_seguimiento (
                        creador_id,
                        creador_tiktok_id,
                        usuario_tiktok,
                        manager,
                        manager_id,
                        grupo,
                        id_capacitacion,
                        estado,
                        fecha_realizacion,
                        observacion,
                        actualizado_por,
                        fecha_creacion,
                        fecha_actualizacion
                    )
                    VALUES (
                        %s, %s, %s,
                        %s, %s, %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        NOW(),
                        NOW()
                    )
                    ON CONFLICT (creador_tiktok_id, id_capacitacion)
                    DO UPDATE SET
                        creador_id = EXCLUDED.creador_id,
                        usuario_tiktok = EXCLUDED.usuario_tiktok,
                        manager = EXCLUDED.manager,
                        manager_id = EXCLUDED.manager_id,
                        grupo = EXCLUDED.grupo,
                        estado = EXCLUDED.estado,
                        fecha_realizacion = EXCLUDED.fecha_realizacion,
                        observacion = EXCLUDED.observacion,
                        actualizado_por = EXCLUDED.actualizado_por,
                        fecha_actualizacion = NOW()
                    RETURNING *
                    """,
                    (
                        payload.creador_id,
                        payload.creador_tiktok_id,
                        payload.usuario_tiktok,
                        payload.manager,
                        payload.manager_id,
                        payload.grupo,
                        payload.id_capacitacion,
                        estado,
                        fecha_realizacion,
                        payload.observacion,
                        payload.actualizado_por,
                    ),
                )

                row = cur.fetchone()

        return {
            "ok": True,
            "mensaje": "Seguimiento de capacitación guardado correctamente.",
            "seguimiento": row,
        }

    except HTTPException:
        raise

    except Exception as e:
        print("❌ Error guardando seguimiento de capacitación:", e)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Error guardando seguimiento de capacitación"
        )


# =========================================================
# ENDPOINT: RESUMEN POR MANAGER
# =========================================================

@router.get("/api/creadores/capacitaciones/resumen-managers")
def obtener_resumen_capacitaciones_managers(
    usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        # Manager (rol_id=2) solo ve su propia fila de resumen.
        manager_creds = None
        if es_manager(usuario):
            manager_creds = credenciales_manager_para_filtro(usuario)

        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                filtro_manager_sql = "TRUE"
                filtro_params: List[Any] = []
                if manager_creds is not None:
                    filtro_manager_sql = _filtro_sql_manager_reporte(
                        col_manager_id="r.manager_id",
                        col_agente="r.agente",
                    )
                    filtro_params = _params_manager_logueado(manager_creds)

                cur.execute(
                    f"""
                    WITH creadores_base AS (
                        SELECT DISTINCT ON (r.creador_tiktok_id)
                            r.creador_tiktok_id,
                            r.creador_id,
                            r.usuario_tiktok,
                            r.manager_id,
                            COALESCE(a.nombre_completo, r.agente, 'Sin manager') AS manager,
                            COALESCE(r.grupo, 'Sin grupo') AS grupo
                        FROM creadores_reporte_integral r
                        LEFT JOIN administradores a ON a.id = r.manager_id
                        WHERE r.creador_tiktok_id IS NOT NULL
                          AND ({filtro_manager_sql})
                        ORDER BY r.creador_tiktok_id, r.periodo_fin DESC
                    ),
                    caps AS (
                        SELECT *
                        FROM creadores_capacitaciones
                        WHERE activa = true
                    ),
                    base AS (
                        SELECT
                            cb.manager,
                            cb.manager_id,
                            cb.creador_tiktok_id,
                            caps.id_capacitacion,
                            caps.obligatoria
                        FROM creadores_base cb
                        CROSS JOIN caps
                    ),
                    data AS (
                        SELECT
                            b.manager,
                            b.manager_id,
                            b.creador_tiktok_id,
                            b.id_capacitacion,
                            b.obligatoria,
                            COALESCE(s.estado, 'pendiente') AS estado
                        FROM base b
                        LEFT JOIN creadores_capacitaciones_seguimiento s
                            ON s.creador_tiktok_id = b.creador_tiktok_id
                           AND s.id_capacitacion = b.id_capacitacion
                    )
                    SELECT
                        manager,
                        manager_id,

                        COUNT(DISTINCT creador_tiktok_id) AS total_creadores,

                        COUNT(*) AS total_items,

                        COUNT(*) FILTER (
                            WHERE obligatoria = true
                        ) AS total_obligatorias,

                        COUNT(*) FILTER (
                            WHERE estado = 'realizada'
                        ) AS total_realizadas,


                        COUNT(*) FILTER (
                            WHERE estado = 'pendiente'
                        ) AS total_pendientes,

                        COUNT(*) FILTER (
                            WHERE estado = 'no_aplica'
                        ) AS total_no_aplica,

                        ROUND(
                            (
                                COUNT(*) FILTER (WHERE estado = 'realizada')::numeric
                                / NULLIF(COUNT(*) FILTER (WHERE estado <> 'no_aplica'), 0)
                            ) * 100,
                            2
                        ) AS porcentaje_avance

                    FROM data
                    GROUP BY manager, manager_id
                    ORDER BY porcentaje_avance DESC NULLS LAST, manager ASC
                    """,
                    filtro_params,
                )

                rows = cur.fetchall()

        return {
            "ok": True,
            "total_managers": len(rows),
            "managers": rows,
        }

    except Exception as e:
        print("❌ Error obteniendo resumen por managers:", e)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Error obteniendo resumen de capacitaciones por manager"
        )