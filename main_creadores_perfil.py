import traceback
from typing import Optional, Any, List

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from psycopg2.extras import RealDictCursor, Json
from pydantic import BaseModel

from DataBase import get_connection_context

router = APIRouter()


# =========================================================
# MODELOS
# =========================================================

class RespuestaPerfilCreadorIn(BaseModel):
    variable_id: int
    valor_integer: Optional[int] = None
    valor_id: Optional[int] = None
    valor_numeric: Optional[float] = None
    valor_texto: Optional[str] = None
    valor_json: Optional[Any] = None


class GuardarPerfilCreadorIn(BaseModel):
    creador_id: int
    respuestas: List[RespuestaPerfilCreadorIn]


# =========================================================
# FORMULARIO PERFIL CREADOR
# =========================================================

@router.get("/api/creadores/perfil-formulario")
def obtener_formulario_perfil_creador(
    encuesta_id: int = Query(2)
):
    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        c.id AS categoria_id,
                        c.nombre AS categoria_nombre,
                        c.nombre_natural,
                        c.descripcion,
                        c.orden AS categoria_orden,

                        v.id AS variable_id,
                        v.nombre AS variable_nombre,
                        v.campo_db,
                        v.peso_variable,
                        v.tipo,
                        v.tipo_form,
                        v.texto,
                        v.orden AS variable_orden,

                        val.id AS valor_id,
                        val.score,
                        val.label,
                        val.nivel,
                        val.orden AS valor_orden

                    FROM creadores_perfil_variable v
                    LEFT JOIN creadores_perfil_categoria c
                        ON c.id = v.categoria_id
                    LEFT JOIN creadores_perfil_valor val
                        ON val.variable_id = v.id
                    WHERE v.encuesta_id = %s
                      AND v.activa = TRUE
                    ORDER BY
                        c.orden ASC NULLS LAST,
                        v.orden ASC NULLS LAST,
                        val.orden ASC NULLS LAST
                """, (encuesta_id,))

                rows = cur.fetchall()

        categorias_map = {}

        for row in rows:
            categoria_id = row["categoria_id"] or 0

            if categoria_id not in categorias_map:
                categorias_map[categoria_id] = {
                    "id": categoria_id,
                    "nombre": row["categoria_nombre"],
                    "nombre_natural": row["nombre_natural"],
                    "descripcion": row["descripcion"],
                    "orden": row["categoria_orden"],
                    "variables": {}
                }

            variable_id = row["variable_id"]

            if variable_id not in categorias_map[categoria_id]["variables"]:
                categorias_map[categoria_id]["variables"][variable_id] = {
                    "id": variable_id,
                    "nombre": row["variable_nombre"],
                    "campo_db": row["campo_db"],
                    "peso_variable": float(row["peso_variable"] or 0),
                    "tipo": row["tipo"],
                    "tipo_form": row["tipo_form"],
                    "texto": row["texto"],
                    "orden": row["variable_orden"],
                    "opciones": []
                }

            if row["valor_id"] is not None:
                categorias_map[categoria_id]["variables"][variable_id]["opciones"].append({
                    "id": row["valor_id"],
                    "score": row["score"],
                    "label": row["label"],
                    "nivel": row["nivel"],
                    "orden": row["valor_orden"]
                })

        categorias = []
        for categoria in categorias_map.values():
            categoria["variables"] = list(categoria["variables"].values())
            categorias.append(categoria)

        return {
            "ok": True,
            "encuesta_id": encuesta_id,
            "categorias": categorias
        }

    except Exception as e:
        print("❌ Error obteniendo formulario perfil creador:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error obteniendo formulario del creador")


# =========================================================
# RESPUESTAS DE UN CREADOR
# =========================================================

@router.get("/api/creadores/{creador_id}/perfil-respuestas")
def obtener_respuestas_perfil_creador(
    creador_id: int,
    encuesta_id: int = Query(2)
):
    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        r.id,
                        r.creador_id,
                        r.variable_id,

                        v.nombre AS variable_nombre,
                        v.campo_db,
                        v.tipo,
                        v.tipo_form,
                        v.texto,
                        v.orden,

                        r.valor_integer,
                        r.valor_id,
                        r.valor_numeric,
                        r.valor_texto,
                        r.valor_json,

                        val.label AS valor_label,
                        val.score AS valor_score,
                        val.nivel AS valor_nivel,

                        r.created_at,
                        r.updated_at

                    FROM creadores_perfil_respuesta r
                    INNER JOIN creadores_perfil_variable v
                        ON v.id = r.variable_id
                    LEFT JOIN creadores_perfil_valor val
                        ON val.id = r.valor_id
                    WHERE r.creador_id = %s
                      AND v.encuesta_id = %s
                    ORDER BY v.orden ASC
                """, (creador_id, encuesta_id))

                rows = cur.fetchall()

        return {
            "ok": True,
            "creador_id": creador_id,
            "respuestas": rows
        }

    except Exception as e:
        print("❌ Error obteniendo respuestas perfil creador:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error obteniendo respuestas del creador")


# =========================================================
# GUARDAR RESPUESTAS
# =========================================================

@router.post("/api/creadores/perfil-respuestas")
def guardar_respuestas_perfil_creador(data: GuardarPerfilCreadorIn):
    if not data.creador_id:
        raise HTTPException(status_code=400, detail="creador_id requerido")

    if not data.respuestas:
        raise HTTPException(status_code=400, detail="No hay respuestas para guardar")

    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                for respuesta in data.respuestas:
                    cur.execute("""
                        INSERT INTO creadores_perfil_respuesta
                        (
                            creador_id,
                            variable_id,
                            valor_integer,
                            valor_id,
                            valor_numeric,
                            valor_texto,
                            valor_json,
                            created_at,
                            updated_at
                        )
                        VALUES
                        (
                            %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                        )
                        ON CONFLICT (creador_id, variable_id)
                        DO UPDATE SET
                            valor_integer = EXCLUDED.valor_integer,
                            valor_id = EXCLUDED.valor_id,
                            valor_numeric = EXCLUDED.valor_numeric,
                            valor_texto = EXCLUDED.valor_texto,
                            valor_json = EXCLUDED.valor_json,
                            updated_at = NOW()
                    """, (
                        data.creador_id,
                        respuesta.variable_id,
                        respuesta.valor_integer,
                        respuesta.valor_id,
                        respuesta.valor_numeric,
                        respuesta.valor_texto,
                        Json(respuesta.valor_json) if respuesta.valor_json is not None else None
                    ))

            conn.commit()

        return {
            "ok": True,
            "mensaje": "Respuestas guardadas correctamente"
        }

    except Exception as e:
        print("❌ Error guardando respuestas perfil creador:", e)
        traceback.print_exc()
        return JSONResponse(
            {"ok": False, "error": "Error guardando respuestas del creador"},
            status_code=500
        )


# =========================================================
# RESUMEN PLANO PARA FRONTEND
# =========================================================

@router.get("/api/creadores/{creador_id}/perfil-resumen")
def obtener_resumen_perfil_creador(
    creador_id: int,
    encuesta_id: int = Query(2)
):
    """
    Devuelve las respuestas en formato plano por campo_db.
    Útil para mostrar ficha/resumen en React.
    """

    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        v.campo_db,
                        v.nombre,
                        v.tipo,
                        v.tipo_form,
                        r.valor_integer,
                        r.valor_numeric,
                        r.valor_texto,
                        r.valor_json,
                        r.valor_id,
                        val.label AS valor_label,
                        val.score AS valor_score
                    FROM creadores_perfil_respuesta r
                    INNER JOIN creadores_perfil_variable v
                        ON v.id = r.variable_id
                    LEFT JOIN creadores_perfil_valor val
                        ON val.id = r.valor_id
                    WHERE r.creador_id = %s
                      AND v.encuesta_id = %s
                    ORDER BY v.orden ASC
                """, (creador_id, encuesta_id))

                rows = cur.fetchall()

        resumen = {}

        for row in rows:
            campo = row["campo_db"]

            if row["valor_json"] is not None:
                valor = row["valor_json"]
            elif row["valor_texto"] is not None:
                valor = row["valor_texto"]
            elif row["valor_numeric"] is not None:
                valor = row["valor_numeric"]
            elif row["valor_label"] is not None:
                valor = {
                    "valor_id": row["valor_id"],
                    "score": row["valor_score"],
                    "label": row["valor_label"]
                }
            else:
                valor = row["valor_integer"]

            resumen[campo] = {
                "nombre": row["nombre"],
                "tipo": row["tipo"],
                "tipo_form": row["tipo_form"],
                "valor": valor
            }

        return {
            "ok": True,
            "creador_id": creador_id,
            "resumen": resumen
        }

    except Exception as e:
        print("❌ Error obteniendo resumen perfil creador:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error obteniendo resumen del creador")