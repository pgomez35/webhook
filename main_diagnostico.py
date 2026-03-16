import logging
import json
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from main_auth import obtener_usuario_actual
from tenant import current_tenant, current_business_name
from DataBase import get_connection_context

logger = logging.getLogger(__name__)
router = APIRouter()
from fastapi import APIRouter, HTTPException



class PerfilCualitativoPayload(BaseModel):
    potencial_estimado: int = Field(..., ge=0, le=5)
    apariencia: int = Field(..., ge=0, le=5)
    engagement: int = Field(..., ge=0, le=5)
    calidad_contenido: int = Field(..., ge=0, le=5)
    eval_biografia: int = Field(..., ge=0, le=5)
    metadata_videos: int = Field(..., ge=0, le=5)
    eval_foto: int = Field(..., ge=0, le=5)  # solo perfil_creador

def obtener_modelo_activo(cur):
    cur.execute("""
        SELECT id
        FROM diagnostico_modelo
        WHERE activo = true
        LIMIT 1
    """)
    r = cur.fetchone()
    return r[0] if r else None

import json

def generar_insights_principales(categorias):
    """
    categorias = [
        {
            "nombre_natural": "talento creativo",
            "score": 4.2
        }
    ]
    """

    if not categorias:
        return {
            "insight_principal": None,
            "alerta_principal": None
        }

    def lista_texto(items):
        if len(items) == 1:
            return items[0]
        if len(items) == 2:
            return f"{items[0]} y {items[1]}"
        return ", ".join(items[:-1]) + f" y {items[-1]}"

    categorias_ordenadas = sorted(
        categorias,
        key=lambda x: float(x["score"]),
        reverse=True
    )

    max_score = float(categorias_ordenadas[0]["score"])
    min_score = float(categorias_ordenadas[-1]["score"])

    fortalezas = [
        c for c in categorias
        if float(c["score"]) >= 4.0
    ]

    if not fortalezas:
        margen = 0.20
        fortalezas = [
            c for c in categorias
            if float(c["score"]) >= (max_score - margen)
        ]

    debilidad = min(
        categorias,
        key=lambda x: float(x["score"])
    )

    fortalezas_txt = lista_texto(
        [c["nombre_natural"] for c in fortalezas]
    )

    debilidad_txt = debilidad["nombre_natural"]

    if min_score >= 4.0:

        insight_principal = (
            f"Perfil sólido y equilibrado, con fortalezas en {fortalezas_txt}."
        )

    elif max_score >= 4.0:

        insight_principal = (
            f"El perfil muestra una base favorable, con mejor desempeño en {fortalezas_txt}."
        )

    elif max_score >= 3.0:

        insight_principal = (
            f"El perfil se encuentra en desarrollo, con mejor desempeño en {fortalezas_txt}."
        )

    else:

        insight_principal = (
            "El perfil requiere fortalecimiento general para consolidar una base más competitiva."
        )

    if float(debilidad["score"]) <= 2.5:

        alerta_principal = (
            f"El principal punto de atención está en {debilidad_txt}."
        )

    elif float(debilidad["score"]) < 3.2:

        alerta_principal = (
            f"Conviene seguir fortaleciendo {debilidad_txt}."
        )

    else:

        alerta_principal = None

    return {
        "insight_principal": insight_principal,
        "alerta_principal": alerta_principal
    }

def calcular_diagnostico_y_json(cur, creador_id: int, modelo_id: int):

    sql = """

    WITH modelo_info AS (

        SELECT
            id,
            nombre AS modelo_nombre,
            descripcion AS modelo_descripcion
        FROM diagnostico_modelo
        WHERE id = %(modelo_id)s
    ),

    demograficos AS (

        SELECT
            jsonb_object_agg(v.nombre, vv.label) AS data
        FROM diagnostico_score_variable sv
        JOIN diagnostico_variable v
            ON v.id = sv.variable_id
        LEFT JOIN diagnostico_variable_valor vv
            ON vv.id = sv.valor_id
        WHERE sv.creador_id = %(creador_id)s
        AND sv.variable_id IN (1,2,3,12,20)
    ),

    variables_calc AS (

        SELECT
            mc.modelo_id,
            mc.categoria_id,
            mc.peso_categoria,
            mc.orden AS categoria_orden,

            v.id AS variable_id,
            v.nombre AS variable_nombre,
            v.tipo,
            v.peso_variable,
            v.orden AS variable_orden,

            sv.valor,
            vv.score,
            vv.nivel,
            vv.label,

            COALESCE(vv.score,0) AS score_variable

        FROM diagnostico_modelo_categoria mc

        JOIN diagnostico_variable v
            ON v.categoria_id = mc.categoria_id
            AND v.activa = true

        LEFT JOIN diagnostico_score_variable sv
            ON sv.variable_id = v.id
            AND sv.creador_id = %(creador_id)s

        LEFT JOIN diagnostico_variable_valor vv
            ON vv.id = sv.valor_id

        WHERE mc.modelo_id = %(modelo_id)s
    ),

    categorias_calc AS (

        SELECT
            modelo_id,
            categoria_id,
            peso_categoria,
            categoria_orden,

            jsonb_agg(
                jsonb_build_object(
                    'variable_id', variable_id,
                    'variable', variable_nombre,
                    'tipo', tipo,
                    'valor', valor,
                    'score', score_variable,
                    'peso_variable', peso_variable,
                    'nivel', nivel,
                    'label', label
                )
                ORDER BY variable_orden
            ) AS variables,

            SUM(score_variable * (peso_variable / 100.0)) AS score_categoria

        FROM variables_calc

        GROUP BY
            modelo_id,
            categoria_id,
            peso_categoria,
            categoria_orden
    ),

    categorias_nivel AS (

        SELECT
            *,

            CASE
                WHEN score_categoria >= 3.75 THEN 3
                WHEN score_categoria >= 2.75 THEN 2
                ELSE 1
            END AS nivel,

            CASE
                WHEN score_categoria < 1.5 THEN 1
                WHEN score_categoria < 2.5 THEN 2
                WHEN score_categoria < 3.5 THEN 3
                WHEN score_categoria < 4.5 THEN 4
                ELSE 5
            END AS nivel5

        FROM categorias_calc
    ),

    categorias_json AS (

        SELECT
            cn.categoria_id,
            cn.categoria_orden,
            cn.variables,
            cn.score_categoria,
            cn.peso_categoria,
            cn.nivel,
            cn.nivel5,

            c.nombre AS categoria_nombre,
            c.nombre_natural,
            c.descripcion AS categoria_descripcion,

            s.script

        FROM categorias_nivel cn

        JOIN diagnostico_categoria c
            ON c.id = cn.categoria_id

        LEFT JOIN diagnostico_interpretacion_categoria s
            ON s.categoria_id = cn.categoria_id
            AND s.nivel = cn.nivel5
            AND s.escala = 5
    ),

    total_calc AS (

        SELECT
            SUM(score_categoria * (peso_categoria / 100.0)) AS score_total
        FROM categorias_json
    ),

    json_final AS (

        SELECT
            jsonb_build_object(

                'modelo_id', m.id,
                'modelo_nombre', m.modelo_nombre,
                'modelo_descripcion', m.modelo_descripcion,

                'demograficos', d.data,

                'score_total', ROUND(tc.score_total,2),

                'categorias',

                jsonb_agg(
                    jsonb_build_object(
                        'categoria_id', categoria_id,
                        'categoria_nombre', categoria_nombre,
                        'nombre_natural', nombre_natural,
                        'descripcion', categoria_descripcion,
                        'peso_categoria', peso_categoria,
                        'score', ROUND(score_categoria,2),
                        'nivel', nivel,
                        'nivel5', nivel5,
                        'script', script,
                        'variables', variables
                    )
                    ORDER BY categoria_orden
                )

            ) AS diagnostico_json,

            tc.score_total

        FROM categorias_json cj
        CROSS JOIN total_calc tc
        CROSS JOIN modelo_info m
        CROSS JOIN demograficos d

        GROUP BY
            tc.score_total,
            m.id,
            m.modelo_nombre,
            m.modelo_descripcion,
            d.data
    )

    INSERT INTO diagnostico_score_general
    (creador_id, modelo_id, puntaje_total, nivel, diagnostico_json)

    SELECT
        %(creador_id)s,
        %(modelo_id)s,
        ROUND(score_total,2),

        CASE
            WHEN score_total >= 3.75 THEN 3
            WHEN score_total >= 2.75 THEN 2
            ELSE 1
        END,

        diagnostico_json

    FROM json_final

    ON CONFLICT (creador_id, modelo_id)
    DO UPDATE
    SET
        puntaje_total = EXCLUDED.puntaje_total,
        nivel = EXCLUDED.nivel,
        diagnostico_json = EXCLUDED.diagnostico_json

    """

    cur.execute(sql, {
        "creador_id": creador_id,
        "modelo_id": modelo_id
    })

    # -------- obtener json guardado --------

    cur.execute("""
        SELECT diagnostico_json
        FROM diagnostico_score_general
        WHERE creador_id = %s
        AND modelo_id = %s
    """, (creador_id, modelo_id))

    row = cur.fetchone()

    if not row:
        return

    diagnostico = row[0]

    categorias = []

    for c in diagnostico["categorias"]:
        categorias.append({
            "nombre_natural": c["nombre_natural"],
            "score": c["score"]
        })

    insights = generar_insights_principales(categorias)

    diagnostico["insight_principal"] = insights["insight_principal"]
    diagnostico["alerta_principal"] = insights["alerta_principal"]

    cur.execute("""
        UPDATE diagnostico_score_general
        SET diagnostico_json = %s
        WHERE creador_id = %s
        AND modelo_id = %s
    """, (json.dumps(diagnostico), creador_id, modelo_id))

@router.post("/api/perfil_creador/{creador_id}/talento/actualizar",
    tags=["Categoria talento"]
)
def sync_cualitativo_perfil_y_variables(
    creador_id: int,
    payload: PerfilCualitativoPayload,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):

    try:

        data = payload.model_dump()

        # seguridad extra
        for k, v in data.items():
            try:
                data[k] = int(v)
            except:
                raise HTTPException(status_code=400, detail=f"{k} debe ser entero")

            if not (0 <= data[k] <= 5):
                raise HTTPException(status_code=400, detail=f"{k} debe estar entre 0 y 5")

        with get_connection_context() as conn:
            with conn.cursor() as cur:

                # 1️⃣ actualizar perfil_creador
                cur.execute("""
                    UPDATE perfil_creador
                    SET apariencia = %s,
                        engagement = %s,
                        calidad_contenido = %s,
                        eval_biografia = %s,
                        metadata_videos = %s,
                        eval_foto = %s,
                        potencial_estimado = %s
                    WHERE creador_id = %s
                """, (
                    data["apariencia"],
                    data["engagement"],
                    data["calidad_contenido"],
                    data["eval_biografia"],
                    data["metadata_videos"],
                    data["eval_foto"],
                    data["potencial_estimado"],
                    creador_id
                ))

                perfil_rows = cur.rowcount

                # 2️⃣ pasar valores del perfil al score_variable
                guardar_scores_desde_perfil(cur, creador_id)

                # 3️⃣ obtener modelo activo
                modelo_id = obtener_modelo_activo(cur)

                if not modelo_id:
                    raise HTTPException(
                        status_code=500,
                        detail="No existe modelo de diagnóstico activo"
                    )

                # 4️⃣ recalcular diagnóstico
                calcular_diagnostico_y_json(cur, creador_id, modelo_id)

            conn.commit()

        return {
            "status": "ok",
            "mensaje": "perfil_creador actualizado, scores sincronizados y diagnóstico recalculado",
            "creador_id": creador_id,
            "perfil_creador_filas_afectadas": perfil_rows,
            "payload": data
        }

    except HTTPException:
        raise

    except Exception as e:
        import traceback
        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=f"Error en sync_cualitativo_perfil_y_variables: {str(e)}"
        )

@router.get("/api/creadores/{creador_id}/diagnostico")
def diagnostico_creador(creador_id: int):

    with get_connection_context() as conn:
        with conn.cursor() as cur:

            # 1️⃣ obtener modelo activo
            modelo_id = obtener_modelo_activo(cur)

            if not modelo_id:
                return {
                    "success": False,
                    "message": "No hay modelo de diagnóstico activo"
                }

            # 2️⃣ buscar diagnóstico y datos del creador
            cur.execute("""
                SELECT 
                    d.diagnostico_json,
                    c.nickname,
                    c.nombre_real as nombre
                FROM diagnostico_score_general d
                JOIN creadores c
                    ON c.id = d.creador_id
                WHERE d.creador_id = %s
                AND d.modelo_id = %s
            """, (creador_id, modelo_id))

            r = cur.fetchone()

            if not r:
                return {
                    "success": False,
                    "message": "Diagnóstico no calculado"
                }

            diagnostico_json, nickname, nombre = r

            return {
                "success": True,
                "creador": {
                    "nickname": nickname,
                    "nombre": nombre
                },
                **diagnostico_json
            }


def guardar_scores_desde_perfil(cur, creador_id: int):
    # 1️⃣ obtener variables del sistema
    cur.execute("""
        SELECT id, campo_db, tipo
        FROM diagnostico_variable
        WHERE encuesta_id = 0
        AND tipo in ('numérica','rango')
        AND campo_db IS NOT NULL
    """)
    variables = cur.fetchall()

    if not variables:
        return

    # construir VALUES dinámico
    values_sql = ",".join(
        f"({v[0]}, p.{v[1]})"
        for v in variables
    )

    sql = f"""
    WITH perfil_vars AS (
        SELECT
            p.creador_id,
            v.variable_id,
            v.valor
        FROM perfil_creador p
        CROSS JOIN LATERAL (
            VALUES
            {values_sql}
        ) AS v(variable_id, valor)
        WHERE p.creador_id = %s
        AND v.valor IS NOT NULL
    ),
    valores_resueltos AS (
        SELECT
            pv.creador_id,
            pv.variable_id,
            pv.valor AS valor_original,
            dvv.id AS valor_modificado
        FROM perfil_vars pv
        JOIN diagnostico_variable dv
            ON dv.id = pv.variable_id
        JOIN diagnostico_variable_valor dvv
            ON dvv.variable_id = pv.variable_id
            AND (
                (dv.tipo = 'numérica'  AND dvv.score = pv.valor)
                OR
                (dv.tipo = 'rango'    AND pv.valor BETWEEN dvv.min_val AND dvv.max_val)
            )
    )
    INSERT INTO diagnostico_score_variable
    (creador_id, variable_id, valor, valor_id)
    SELECT
        creador_id,
        variable_id,
        valor_original,
        valor_modificado
    FROM valores_resueltos
    ON CONFLICT (creador_id, variable_id)
    DO UPDATE
    SET valor = EXCLUDED.valor,
        valor_id = EXCLUDED.valor_id
    """
    cur.execute(sql, (creador_id,))

ESTADO_MAP_PREEVAL = {
    "No apto": 7,
    "Entrevista": 4,
    "Invitar a TikTok": 5,
}
ESTADO_DEFAULT = 99  # si no coincide

def actualizar_estado_preevaluacion(creador_id: int, payload: dict):

    estado = payload.get("estado_evaluacion")
    estado_id = None

    if estado:
        estado_id = ESTADO_MAP_PREEVAL.get(estado, ESTADO_DEFAULT)

    with get_connection_context() as conn:

        cur = conn.cursor()

        # ------------------------
        # UPDATE perfil_creador
        # ------------------------

        sets = []
        valores = []

        for campo, valor in payload.items():
            if valor is not None:
                sets.append(f"{campo} = %s")
                valores.append(valor)

        if sets:

            valores.append(creador_id)

            query = f"""
                UPDATE perfil_creador
                SET {', '.join(sets)},
                    actualizado_en = NOW()
                WHERE creador_id = %s
            """

            cur.execute(query, valores)

        # ------------------------
        # UPDATE creadores
        # ------------------------

        if estado_id is not None:

            cur.execute("""
                UPDATE creadores
                SET estado_id = %s
                WHERE id = %s
            """, (estado_id, creador_id))

        conn.commit()

    print(
        f"✅ Creador {creador_id} actualizado "
        f"(estado={estado}, estado_id={estado_id})"
    )


class ActualizarPreEvaluacionIn(BaseModel):
    estado_evaluacion: Optional[str] = None  # "No apto" | "Entrevista" | "Invitar a TikTok"
    usuario_evalua: Optional[str] = None
    observaciones_finales: Optional[str] = None


@router.put("/api/perfil_creador/{creador_id}/preevaluacion")
def actualizar_preevaluacion(
    creador_id: int,
    datos: ActualizarPreEvaluacionIn,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):

    try:

        payload = {
            "estado_evaluacion": datos.estado_evaluacion,
            "usuario_evalua": datos.usuario_evalua,
            "observaciones_finales": datos.observaciones_finales
        }

        actualizar_estado_preevaluacion(creador_id, payload)

        return {
            "status": "ok",
            "mensaje": "Pre-evaluación actualizada correctamente",
            "creador_id": creador_id,
            "estado_evaluacion": datos.estado_evaluacion,
        }

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------
# -------------------------------------------------
# -------------------------------------------------

@router.get("/api/entrevista-tipos/opciones")
def opciones_entrevista_tipos():

    with get_connection_context() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT 
                    id,
                    nombre
                FROM entrevista_tipo
                WHERE activo = TRUE
                ORDER BY orden, id
            """)

            rows = cur.fetchall()

            columnas = [desc[0] for desc in cur.description]

            data = [dict(zip(columnas, r)) for r in rows]

            return {
                "success": True,
                "data": data
            }

@router.get("/api/entrevista-tipos")
def listar_entrevista_tipos():

    with get_connection_context() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT 
                    id,
                    nombre,
                    descripcion,
                    duracion_default,
                    tipo,
                    activo,
                    orden
                FROM entrevista_tipo
                ORDER BY orden, id
            """)

            rows = cur.fetchall()

            columnas = [desc[0] for desc in cur.description]

            data = [dict(zip(columnas, r)) for r in rows]

            return {
                "success": True,
                "data": data
            }

@router.get("/api/entrevista-tipos/{tipo_id}")
def obtener_entrevista_tipo(tipo_id: int):

    with get_connection_context() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT 
                    id,
                    nombre,
                    descripcion,
                    duracion_default,
                    tipo,
                    activo,
                    orden
                FROM entrevista_tipo
                WHERE id = %s
            """, (tipo_id,))

            r = cur.fetchone()

            if not r:
                return {
                    "success": False,
                    "message": "Tipo de entrevista no encontrado"
                }

            columnas = [desc[0] for desc in cur.description]

            data = dict(zip(columnas, r))

            return {
                "success": True,
                "data": data
            }

@router.post("/api/entrevista-tipos")
def crear_entrevista_tipo(data: dict):

    with get_connection_context() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                INSERT INTO entrevista_tipo (
                    nombre,
                    descripcion,
                    duracion_default,
                    tipo,
                    activo,
                    orden
                )
                VALUES (%s,%s,%s,%s,%s,%s)
                RETURNING id
            """, (
                data.get("nombre"),
                data.get("descripcion"),
                data.get("duracion_default"),
                data.get("tipo"),
                data.get("activo", True),
                data.get("orden", 1)
            ))

            new_id = cur.fetchone()[0]

            conn.commit()

            return {
                "success": True,
                "id": new_id
            }

@router.put("/api/entrevista-tipos/{tipo_id}")
def actualizar_entrevista_tipo(tipo_id: int, data: dict):

    with get_connection_context() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                UPDATE entrevista_tipo
                SET
                    nombre = %s,
                    descripcion = %s,
                    duracion_default = %s,
                    tipo = %s,
                    activo = %s,
                    orden = %s
                WHERE id = %s
            """, (
                data.get("nombre"),
                data.get("descripcion"),
                data.get("duracion_default"),
                data.get("tipo"),
                data.get("activo"),
                data.get("orden"),
                tipo_id
            ))

            conn.commit()

            return {
                "success": True
            }




