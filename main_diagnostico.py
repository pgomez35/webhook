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
                WHEN score_categoria < 3.25 THEN 3
                WHEN score_categoria < 4.25 THEN 4
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




# def calcular_diagnostico_y_json(cur, creador_id: int, modelo_id: int):
#
#     sql = """
#     WITH variables_calc AS (
#
#         SELECT
#             mc.modelo_id,
#             mc.categoria_id,
#             mc.peso_categoria,
#             mc.orden AS categoria_orden,
#
#             v.id AS variable_id,
#             v.nombre AS variable_nombre,
#             v.peso_variable,
#             v.orden AS variable_orden,
#
#             COALESCE(sv.valor,0) AS score_variable
#
#         FROM diagnostico_modelo_categoria mc
#
#         JOIN diagnostico_variable v
#             ON v.categoria_id = mc.categoria_id
#             AND v.activa = true
#
#         LEFT JOIN diagnostico_score_variable sv
#             ON sv.variable_id = v.id
#             AND sv.creador_id = %(creador_id)s
#
#         WHERE mc.modelo_id = %(modelo_id)s
#     ),
#
#     categorias_calc AS (
#
#         SELECT
#             modelo_id,
#             categoria_id,
#             peso_categoria,
#             categoria_orden,
#
#             jsonb_agg(
#                 jsonb_build_object(
#                     'variable_id', variable_id,
#                     'variable', variable_nombre,
#                     'tipo', 'numerica',
#                     'score', score_variable
#                 )
#                 ORDER BY variable_orden
#             ) AS variables,
#
#             SUM(score_variable * (peso_variable / 100.0)) AS score_categoria
#
#         FROM variables_calc
#
#         GROUP BY
#             modelo_id,
#             categoria_id,
#             peso_categoria,
#             categoria_orden
#     ),
#
#     categorias_nivel AS (
#
#         SELECT
#             *,
#             CASE
#                 WHEN score_categoria >= 3.75 THEN 3
#                 WHEN score_categoria >= 2.75 THEN 2
#                 ELSE 1
#             END AS nivel
#         FROM categorias_calc
#     ),
#
#     guardar_categoria AS (
#
#         INSERT INTO diagnostico_score_categoria
#         (modelo_id, creador_id, categoria_id, score_categoria, nivel)
#
#         SELECT
#             modelo_id,
#             %(creador_id)s,
#             categoria_id,
#             ROUND(score_categoria,2),
#             nivel
#
#         FROM categorias_nivel
#
#         ON CONFLICT (modelo_id, creador_id, categoria_id)
#         DO UPDATE
#         SET
#             score_categoria = EXCLUDED.score_categoria,
#             nivel = EXCLUDED.nivel
#
#         RETURNING categoria_id
#     ),
#
#     categorias_json AS (
#
#         SELECT
#             cn.categoria_id,
#             cn.categoria_orden,
#             cn.variables,
#             cn.score_categoria,
#             cn.peso_categoria,
#             cn.nivel,
#             c.nombre,
#             c.descripcion,
#             s.script
#
#         FROM categorias_nivel cn
#
#         JOIN diagnostico_categoria c
#             ON c.id = cn.categoria_id
#
#         LEFT JOIN diagnostico_interpretacion_categoria s
#             ON s.categoria_id = cn.categoria_id
#             AND s.nivel = cn.nivel
#             AND s.escala = 5
#     ),
#
#     total_calc AS (
#
#         SELECT
#             SUM(score_categoria * (peso_categoria / 100.0)) AS score_total
#         FROM categorias_json
#     ),
#
#     json_final AS (
#
#         SELECT
#             jsonb_build_object(
#
#                 'score_total', ROUND(tc.score_total,2),
#
#                 'categorias',
#
#                 jsonb_agg(
#                     jsonb_build_object(
#                         'categoria_id', categoria_id,
#                         'categoria_nombre', nombre,
#                         'descripcion', descripcion,
#                         'score', ROUND(score_categoria,2),
#                         'nivel', nivel,
#                         'script', script,
#                         'variables', variables
#                     )
#                     ORDER BY categoria_orden
#                 )
#
#             ) AS diagnostico_json,
#
#             tc.score_total
#
#         FROM categorias_json cj
#         CROSS JOIN total_calc tc
#
#         GROUP BY tc.score_total
#     )
#
#     INSERT INTO diagnostico_score_general
#     (creador_id, modelo_id, puntaje_total, nivel, diagnostico_json)
#
#     SELECT
#         %(creador_id)s,
#         %(modelo_id)s,
#         ROUND(score_total,2),
#
#         CASE
#             WHEN score_total >= 3.75 THEN 3
#             WHEN score_total >= 2.75 THEN 2
#             ELSE 1
#         END,
#
#         diagnostico_json
#
#     FROM json_final
#
#     ON CONFLICT (creador_id, modelo_id)
#     DO UPDATE
#     SET
#         puntaje_total = EXCLUDED.puntaje_total,
#         nivel = EXCLUDED.nivel,
#         diagnostico_json = EXCLUDED.diagnostico_json
#     """
#
#     cur.execute(sql, {
#         "creador_id": creador_id,
#         "modelo_id": modelo_id
#     })




# def guardar_scores_desde_perfil(cur, creador_id: int):
#
#     # 1️⃣ obtener variables del sistema
#     cur.execute("""
#         SELECT id, campo_db
#         FROM diagnostico_variable
#         WHERE encuesta_id = 0
#         AND tipo in ('numérica','rango')
#         AND campo_db IS NOT NULL
#     """)
#
#     variables = cur.fetchall()
#
#     if not variables:
#         return
#
#     # construir VALUES dinámico
#     values_sql = ",".join(
#         f"({v[0]}, p.{v[1]})"
#         for v in variables
#     )
#
#     sql = f"""
#     WITH perfil_vars AS (
#
#         SELECT
#             p.creador_id,
#             v.variable_id,
#             v.valor
#         FROM perfil_creador p
#
#         CROSS JOIN LATERAL (
#             VALUES
#             {values_sql}
#         ) AS v(variable_id, valor)
#
#         WHERE p.creador_id = %s
#         AND v.valor IS NOT NULL
#     ),
#
#     valores_resueltos AS (
#
#         SELECT
#             pv.creador_id,
#             pv.variable_id,
#             dvv.id AS valor_id
#
#         FROM perfil_vars pv
#
#         JOIN diagnostico_variable dv
#             ON dv.id = pv.variable_id
#
#         JOIN diagnostico_variable_valor dvv
#             ON dvv.variable_id = pv.variable_id
#             AND (
#                 (dv.categoria_id = 1 AND dvv.score = pv.valor)
#                 OR
#                 (dv.categoria_id = 2 AND pv.valor BETWEEN dvv.min_val AND dvv.max_val)
#             )
#     )
#
#     INSERT INTO diagnostico_score_variable
#     (creador_id, variable_id, valor)
#
#     SELECT
#         creador_id,
#         variable_id,
#         valor_id
#     FROM valores_resueltos
#
#     ON CONFLICT (creador_id, variable_id)
#     DO UPDATE
#     SET valor = EXCLUDED.valor
#     """
#
#     cur.execute(sql, (creador_id,))


# def guardar_scores_desde_perfil(cur, creador_id: int):
#
#     # 1️⃣ obtener variables que vienen del perfil
#     cur.execute("""
#         SELECT id, campo_db
#         FROM diagnostico_variable
#         WHERE encuesta_id = 0
#         AND tipo<>'texto'
#         AND campo_db IS NOT NULL
#     """)
#
#     variables = cur.fetchall()
#
#     if not variables:
#         return
#
#     # 2️⃣ obtener columnas del perfil
#     campos = [v[1] for v in variables]
#
#     sql = f"""
#         SELECT {",".join(campos)}
#         FROM perfil_creador
#         WHERE creador_id = %s
#     """
#
#     cur.execute(sql, (creador_id,))
#     perfil = cur.fetchone()
#
#     if not perfil:
#         return
#
#     # 3️⃣ insertar scores
#     for i, (variable_id, campo_db) in enumerate(variables):
#
#         valor = perfil[i]
#
#         if valor is None:
#             continue
#
#         cur.execute("""
#             INSERT INTO diagnostico_score_variable
#             (creador_id, variable_id, valor)
#             VALUES (%s, %s, %s)
#             ON CONFLICT (creador_id, variable_id)
#             DO UPDATE SET valor = EXCLUDED.valor
#         """, (creador_id, variable_id, valor))


# def obtener_diagnostico_v4(cur, creador_id:int, modelo_id:int):
#
#     sql = """
#     WITH base AS (
#
#     SELECT
#     c.id categoria_id,
#     c.nombre categoria_nombre,
#     c.descripcion,
#     c.peso_categoria,
#
#     v.id variable_id,
#     v.nombre variable_nombre,
#     v.peso_variable,
#     v.orden,
#
#     vv.label,
#     vv.score,
#     vv.nivel
#
#     FROM diagnostico_categoria c
#
#     JOIN diagnostico_variable v
#         ON v.categoria_id = c.id
#         AND v.activa = true
#
#     LEFT JOIN diagnostico_score_variable sv
#         ON sv.variable_id = v.id
#         AND sv.creador_id = %(creador_id)s
#
#     LEFT JOIN diagnostico_variable_valor vv
#         ON vv.id = sv.valor
#
#     WHERE c.modelo_id = %(modelo_id)s
#     ),
#
#     calc AS (
#
#     SELECT
#     categoria_id,
#     categoria_nombre,
#     descripcion,
#     peso_categoria,
#
#     jsonb_agg(
#         jsonb_build_object(
#             'variable_id',variable_id,
#             'label',variable_nombre,
#             'score',COALESCE(score,0),
#             'nivel',nivel
#         )
#         ORDER BY orden
#     ) variables,
#
#     SUM(COALESCE(score,0)*(peso_variable/100.0)) score_categoria
#
#     FROM base
#
#     GROUP BY
#         categoria_id,
#         categoria_nombre,
#         descripcion,
#         peso_categoria
#     ),
#
#     niveles AS (
#
#     SELECT
#     *,
#
#     CASE
#         WHEN score_categoria>=4.2 THEN 5
#         WHEN score_categoria>=3.8 THEN 4
#         WHEN score_categoria>=3.2 THEN 3
#         WHEN score_categoria>=2.5 THEN 2
#         ELSE 1
#     END nivel
#
#     FROM calc
#     )
#
#     SELECT
#     jsonb_agg(
#
#         jsonb_build_object(
#
#             'categoria_id',n.categoria_id,
#             'categoria_nombre',n.categoria_nombre,
#             'descripcion',n.descripcion,
#
#             'score',ROUND(n.score_categoria,2),
#             'nivel',n.nivel,
#
#             'script',
#             (SELECT script
#              FROM diagnostico_interpretacion_categoria s
#              WHERE s.categoria_id=n.categoria_id
#              AND s.escala=5
#              AND s.nivel=n.nivel
#              LIMIT 1),
#
#             'variables',n.variables
#
#         )
#
#         ORDER BY n.categoria_id
#
#     ) categorias,
#
#     SUM(n.score_categoria*(peso_categoria/100.0)) score_total
#
#     FROM niveles n;
#     """
#
#     cur.execute(sql,{
#         "creador_id":creador_id,
#         "modelo_id":modelo_id
#     })
#
#     r = cur.fetchone()
#
#     return {
#         "categorias": r[0] if r[0] else [],
#         "score_total": float(r[1] or 0)
#     }


# # =====================================================
# # Utilidades de scoring / niveles
# # =====================================================
# def convertir_score_a_nivel_5(score: float) -> int:
#     """Convierte score (0..5) a nivel 1..5."""
#     if score >= 4.2:
#         return 5
#     elif score >= 3.8:
#         return 4
#     elif score >= 3.2:
#         return 3
#     elif score >= 2.5:
#         return 2
#     return 1
#
#
# def nivel_5_a_3(nivel_5: int) -> int:
#     """Reduce 1..5 a 1..3 para scripts cortos."""
#     if nivel_5 <= 2:
#         return 1
#     if nivel_5 == 3:
#         return 2
#     return 3
#
#
# def grupo_tarjeta(nivel_5: int) -> Dict[str, Any]:
#     """
#     Para front:
#       Fortalezas = 1
#       Desarrollo = 2
#       Riesgos     = 3
#     """
#     if nivel_5 >= 4:
#         return {"grupo_id": 1, "grupo_nombre": "Fortalezas"}
#     if nivel_5 == 3:
#         return {"grupo_id": 2, "grupo_nombre": "Desarrollo"}
#     return {"grupo_id": 3, "grupo_nombre": "Riesgos"}
#
#
# def icono_semaforo(nivel_3: int) -> str:
#     if nivel_3 == 3:
#         return "🟢"
#     if nivel_3 == 2:
#         return "🟡"
#     return "🔴"
#
#
# def icono_badge_5(n: int) -> Dict[str, str]:
#     """
#     Para desglose de variables (1..5):
#     Devuelve icono + texto (puedes ajustar nombres).
#     """
#     mapa = {
#         1: {"icono": "🔴", "nivel_texto": "Muy bajo"},
#         2: {"icono": "🟠", "nivel_texto": "Bajo"},
#         3: {"icono": "🟡", "nivel_texto": "Bueno"},
#         4: {"icono": "🟢", "nivel_texto": "Alto"},
#         5: {"icono": "🟣", "nivel_texto": "Excelente"},
#     }
#     return mapa.get(int(n or 3), {"icono": "🟡", "nivel_texto": "Bueno"})
#
#
# # =====================================================
# # Resumen ejecutivo por filas (sin motor)
# # =====================================================
# def generar_resumen_ejecutivo_filas(categorias: List[Dict[str, Any]]) -> str:
#     """
#     Espera categorias con:
#       - categoria_nombre
#       - nivel_3
#       - script_3
#     Devuelve 4 filas ordenadas:
#       POTENCIAL DE TALENTO
#       CAPACIDAD OPERATIVA
#       POTENCIAL DE MONETIZACIÓN
#       INTENCIÓN Y ALINEACIÓN
#     """
#
#     def linea(nivel_3: int, texto: str) -> str:
#         return f"{icono_semaforo(nivel_3)} {texto}"
#
#     mapa = {
#         "POTENCIAL DE TALENTO": None,
#         "CAPACIDAD OPERATIVA": None,
#         "POTENCIAL DE MONETIZACIÓN": None,
#         "INTENCIÓN Y ALINEACIÓN": None,
#     }
#
#     for c in categorias:
#         nombre = (c.get("categoria_nombre") or "").strip()
#         n3 = int(c.get("nivel_3") or 1)
#         s3 = (c.get("script_3") or "").strip() or "Sin definición estratégica."
#
#         if nombre == "Potencial de Talento":
#             mapa["POTENCIAL DE TALENTO"] = linea(n3, s3)
#         elif nombre == "Capacidad Operativa":
#             mapa["CAPACIDAD OPERATIVA"] = linea(n3, s3)
#         elif nombre in ("Potencial de Mercado", "Potencial de Monetización"):
#             mapa["POTENCIAL DE MONETIZACIÓN"] = linea(n3, s3)
#         elif nombre == "Intención y Alineación":
#             mapa["INTENCIÓN Y ALINEACIÓN"] = linea(n3, s3)
#
#     filas = []
#     if mapa["POTENCIAL DE TALENTO"]:
#         filas.append(f"POTENCIAL DE TALENTO: {mapa['POTENCIAL DE TALENTO']}")
#     if mapa["CAPACIDAD OPERATIVA"]:
#         filas.append(f"CAPACIDAD OPERATIVA: {mapa['CAPACIDAD OPERATIVA']}")
#     if mapa["POTENCIAL DE MONETIZACIÓN"]:
#         filas.append(f"POTENCIAL DE MONETIZACIÓN: {mapa['POTENCIAL DE MONETIZACIÓN']}")
#     if mapa["INTENCIÓN Y ALINEACIÓN"]:
#         filas.append(f"INTENCIÓN Y ALINEACIÓN: {mapa['INTENCIÓN Y ALINEACIÓN']}")
#
#     return "\n\n".join(filas)
#
#
# # =====================================================
# # DB helpers
# # =====================================================
# def obtener_modelo_activo(cur) -> Dict[str, Any]:
#     cur.execute("""
#         SELECT id, nombre
#         FROM diagnostico_modelo
#         WHERE activo = true
#         LIMIT 1
#     """)
#     row = cur.fetchone()
#     if not row:
#         raise HTTPException(status_code=400, detail="No hay modelo activo")
#     return {"modelo_id": row[0], "modelo_nombre": row[1]}
#
#
# def obtener_perfil_creador(cur, creador_id: int) -> Dict[str, Any]:
#     cur.execute("""
#         SELECT nombre, edad, genero, pais, ciudad
#         FROM perfil_creador
#         WHERE creador_id = %s
#         LIMIT 1
#     """, (creador_id,))
#     row = cur.fetchone()
#     if not row:
#         raise HTTPException(status_code=404, detail="Creador no encontrado en perfil_creador")
#     return {
#         "nombre": row[0],
#         "edad": row[1],
#         "genero": row[2],
#         "pais": row[3],
#         "ciudad": row[4],
#     }
#
#
# def obtener_categorias_modelo(cur, modelo_id: int) -> List[Dict[str, Any]]:
#     cur.execute("""
#         SELECT id, nombre, peso_categoria
#         FROM diagnostico_categoria
#         WHERE modelo_id = %s
#         ORDER BY id ASC
#     """, (modelo_id,))
#     rows = cur.fetchall()
#     if not rows:
#         raise HTTPException(status_code=400, detail="El modelo activo no tiene categorías configuradas")
#     return [{"categoria_id": r[0], "categoria_nombre": r[1], "peso_categoria": float(r[2])} for r in rows]
#
#
# def obtener_variables_de_categoria(cur, categoria_id: int) -> List[Dict[str, Any]]:
#     """
#     Devuelve variables configuradas en el modelo (solo por categoría_id):
#       id, nombre, campo_db, peso_variable
#     """
#     cur.execute("""
#         SELECT id, COALESCE(nombre,''), COALESCE(campo_db,''), COALESCE(peso_variable,0)
#         FROM diagnostico_variable
#         WHERE categoria_id = %s
#         ORDER BY id ASC
#     """, (categoria_id,))
#     rows = cur.fetchall()
#     return [{
#         "variable_id": r[0],
#         "variable_nombre": r[1],
#         "campo_db": r[2],
#         "peso_variable": float(r[3]),
#     } for r in rows]
#
#
# def obtener_score_variable_y_raw(cur, creador_id: int, variable_id: int) -> Dict[str, Any]:
#     """
#     Lee de diagnostico_score_variable:
#       score (1..5) y valor raw (text/num)
#     """
#     cur.execute("""
#         SELECT score, valor_raw_text, valor_raw_num
#         FROM diagnostico_score_variable
#         WHERE creador_id = %s
#           AND variable_id = %s
#         ORDER BY created_at DESC
#         LIMIT 1
#     """, (creador_id, variable_id))
#     row = cur.fetchone()
#     if not row:
#         return {"score": 0, "valor_raw_text": None, "valor_raw_num": None}
#     return {"score": int(row[0]), "valor_raw_text": row[1], "valor_raw_num": row[2]}
#
#
# def obtener_script(cur, categoria_id: int, escala: int, nivel: int) -> str:
#     cur.execute("""
#         SELECT script
#         FROM diagnostico_interpretacion_categoria
#         WHERE categoria_id = %s
#           AND escala = %s
#           AND nivel = %s
#         LIMIT 1
#     """, (categoria_id, escala, nivel))
#     row = cur.fetchone()
#     return row[0] if row else "Sin definición estratégica."
#
#
# def sobrescribir_score_categoria(cur, creador_id: int, modelo_id: int, filas: List[Dict[str, Any]]) -> None:
#     cur.execute("""
#         DELETE FROM diagnostico_score_categoria
#         WHERE creador_id = %s AND modelo_id = %s
#     """, (creador_id, modelo_id))
#
#     for f in filas:
#         cur.execute("""
#             INSERT INTO diagnostico_score_categoria (modelo_id, creador_id, categoria_id, score_categoria, nivel)
#             VALUES (%s, %s, %s, %s, %s)
#         """, (modelo_id, creador_id, f["categoria_id"], f["score_categoria"], f["nivel_5"]))
#
#
# def sobrescribir_score_general(
#     cur,
#     creador_id: int,
#     modelo_id: int,
#     puntaje_total: float,
#     nivel_5: int,
#     diagnostico_json: dict,
#     diagnostico_resumen: str
# ) -> None:
#     cur.execute("""
#         DELETE FROM diagnostico_score_general
#         WHERE creador_id = %s AND modelo_id = %s
#     """, (creador_id, modelo_id))
#
#     cur.execute("""
#         INSERT INTO diagnostico_score_general (creador_id, modelo_id, puntaje_total, nivel, diagnostico_json, diagnostico_resumen)
#         VALUES (%s, %s, %s, %s, %s::jsonb, %s)
#     """, (
#         creador_id,
#         modelo_id,
#         puntaje_total,
#         nivel_5,
#         json.dumps(diagnostico_json, ensure_ascii=False),
#         (diagnostico_resumen or "")[:200]
#     ))
#
#
# def actualizar_diagnostico_perfil(cur, creador_id: int, texto: str) -> None:
#     cur.execute("""
#         UPDATE perfil_creador
#         SET diagnostico = %s
#         WHERE creador_id = %s
#     """, (texto, creador_id))
#
#
# # =====================================================
# # Desglose por variables (SIN reglas diagnostico_variable_regla)
# # =====================================================
# def construir_detalle_variables_categoria(cur, creador_id: int, categoria_id: int) -> List[Dict[str, Any]]:
#     """
#     Construye detalle de variables para que el usuario entienda cálculo:
#       - valor raw (texto/num)
#       - score (1..5)
#       - icono + nivel_texto (1..5)
#       - peso_variable
#       - contribucion (score*peso/100)
#     """
#     vars_conf = obtener_variables_de_categoria(cur, categoria_id)
#     detalle: List[Dict[str, Any]] = []
#
#     for v in vars_conf:
#         var_id = v["variable_id"]
#         peso = float(v["peso_variable"] or 0)
#         nombre = (v.get("variable_nombre") or "").strip() or f"Variable {var_id}"
#         campo_db = (v.get("campo_db") or "").strip()
#
#         data = obtener_score_variable_y_raw(cur, creador_id, var_id)
#         score_5 = int(data.get("score") or 0)
#
#         raw_text = data.get("valor_raw_text")
#         raw_num = data.get("valor_raw_num")
#
#         # valor_display: preferimos texto si existe; sino num; sino score
#         if raw_text is not None and str(raw_text).strip() != "":
#             valor_display = str(raw_text).strip()
#         elif raw_num is not None:
#             try:
#                 valor_display = float(raw_num)
#             except Exception:
#                 valor_display = str(raw_num)
#         else:
#             valor_display = None
#
#         badge = icono_badge_5(score_5 if score_5 else 1)
#         contribucion = round((score_5 or 0) * (peso / 100.0), 4)
#
#         detalle.append({
#             "variable_id": var_id,
#             "label": nombre,
#             "campo_db": campo_db,
#             "peso_variable": peso,
#             "valor_raw_text": raw_text,
#             "valor_raw_num": float(raw_num) if raw_num is not None else None,
#             "valor_display": valor_display,          # lo que muestra el front
#             "score_5": score_5,                      # 1..5
#             "icono": badge["icono"],
#             "nivel_texto": badge["nivel_texto"],     # Muy bajo/Bajo/Bueno/Alto/Excelente
#             "contribucion": contribucion
#         })
#
#     return detalle
#
#
# # =====================================================
# # Cálculo principal (con desglose de variables)
# # =====================================================
# def calcular_diagnostico(conn, creador_id: int) -> Dict[str, Any]:
#     cur = conn.cursor()
#
#     # 1) Modelo activo
#     modelo = obtener_modelo_activo(cur)
#     modelo_id = modelo["modelo_id"]
#     modelo_nombre = modelo["modelo_nombre"]
#
#     # 2) Perfil demográfico
#     perfil = obtener_perfil_creador(cur, creador_id)
#
#     # 3) Categorías + pesos
#     categorias = obtener_categorias_modelo(cur, modelo_id)
#
#     resultado_categorias: List[Dict[str, Any]] = []
#     score_total = 0.0
#
#     # 4) Calcular score por categoría (ponderado por variable) y score total (ponderado por categoría)
#     for c in categorias:
#         cat_id = c["categoria_id"]
#         cat_nombre = c["categoria_nombre"]
#         peso_cat = c["peso_categoria"]
#
#         # Variables de esta categoría (con nombre/campo/peso)
#         variables_conf = obtener_variables_de_categoria(cur, cat_id)
#
#         # Detalle para desglose en UI
#         variables_detalle = construir_detalle_variables_categoria(cur, creador_id, cat_id)
#
#         # score_categoria: suma(score_var * peso_var/100)
#         score_categoria = 0.0
#         for v in variables_conf:
#             var_id = v["variable_id"]
#             peso_var = float(v["peso_variable"] or 0)
#
#             data = obtener_score_variable_y_raw(cur, creador_id, var_id)
#             score_var = int(data.get("score") or 0)
#
#             score_categoria += (score_var * (peso_var / 100.0))
#
#         score_categoria = round(score_categoria, 2)
#         nivel_5 = convertir_score_a_nivel_5(score_categoria)
#         nivel_3 = nivel_5_a_3(nivel_5)
#
#         # Scripts:
#         script_5 = obtener_script(cur, cat_id, escala=5, nivel=nivel_5)   # requerido
#         script_3 = obtener_script(cur, cat_id, escala=3, nivel=nivel_3)   # corto (para resumen)
#
#         grupo = grupo_tarjeta(nivel_5)
#
#         resultado_categorias.append({
#             "categoria_id": cat_id,
#             "categoria_nombre": cat_nombre,
#             "peso_categoria": peso_cat,
#             "score_5": score_categoria,
#             "nivel_5": nivel_5,
#             "nivel_3": nivel_3,
#             "grupo_id": grupo["grupo_id"],
#             "grupo_nombre": grupo["grupo_nombre"],
#             "script_5": script_5,
#             "script_3": script_3,
#             "porcentaje": round((score_categoria / 5.0) * 100.0, 2),
#
#             # ✅ NUEVO: desglose de variables para explicar cálculo
#             "variables": variables_detalle
#         })
#
#         score_total += (score_categoria * (peso_cat / 100.0))
#
#     score_total = round(score_total, 2)
#     nivel_total_5 = convertir_score_a_nivel_5(score_total)
#     nivel_total_3 = nivel_5_a_3(nivel_total_5)
#
#     # 5) Texto ejecutivo por filas + semáforo
#     texto_ejecutivo = generar_resumen_ejecutivo_filas(resultado_categorias)
#     resumen_corto = texto_ejecutivo[:200]
#
#     # 6) Guardado (sobrescribir)
#     sobrescribir_score_categoria(cur, creador_id, modelo_id, [
#         {"categoria_id": c["categoria_id"], "score_categoria": c["score_5"], "nivel_5": c["nivel_5"]}
#         for c in resultado_categorias
#     ])
#
#     diagnostico_json = {
#         "creador_id": creador_id,
#         "modelo": {"id": modelo_id, "nombre": modelo_nombre},
#         "score_total": score_total,
#         "nivel_total_5": nivel_total_5,
#         "nivel_total_3": nivel_total_3,
#         "texto_ejecutivo": texto_ejecutivo,
#         "categorias": [
#             {
#                 "categoria_id": c["categoria_id"],
#                 "nombre": c["categoria_nombre"],
#                 "peso_categoria": c["peso_categoria"],
#                 "score_5": c["score_5"],
#                 "nivel_5": c["nivel_5"],
#                 "nivel_3": c["nivel_3"],
#                 "grupo_id": c["grupo_id"],
#                 "grupo_nombre": c["grupo_nombre"],
#                 "script_5": c["script_5"],
#                 "script_3": c["script_3"],
#                 "variables": c["variables"],  # desglose completo
#             }
#             for c in resultado_categorias
#         ],
#         "version_motor": "filas_v2_con_variables"
#     }
#
#     sobrescribir_score_general(
#         cur,
#         creador_id=creador_id,
#         modelo_id=modelo_id,
#         puntaje_total=score_total,
#         nivel_5=nivel_total_5,
#         diagnostico_json=diagnostico_json,
#         diagnostico_resumen=resumen_corto
#     )
#
#     # Actualiza perfil_creador.diagnostico con el texto ejecutivo (filas)
#     actualizar_diagnostico_perfil(cur, creador_id, texto_ejecutivo)
#
#     return {
#         "modelo": {"id": modelo_id, "nombre": modelo_nombre},
#         "perfil": perfil,
#         "score_total": score_total,
#         "nivel_total_5": nivel_total_5,
#         "nivel_total_3": nivel_total_3,
#         "texto_ejecutivo": texto_ejecutivo,
#         "categorias": resultado_categorias,
#     }
#
#
# # =====================================================
# # ENDPOINT
# # =====================================================
# @router.get("/api/creadores/{creador_id}/diagnostico")
# def diagnostico_creador(creador_id: int):
#     TENANT = current_tenant.get() if "current_tenant" in globals() else None
#     if TENANT is None:
#         raise HTTPException(status_code=400, detail="Tenant no disponible")
#
#     with get_connection_context() as conn:
#         try:
#             data = calcular_diagnostico(conn, creador_id)
#             conn.commit()
#         except Exception as e:
#             logger.exception(f"Error generando diagnóstico creador_id={creador_id}: {e}")
#             raise
#
#     nombre_agencia = current_business_name.get() if "current_business_name" in globals() else None
#
#     return {
#         "agencia": {"nombre": nombre_agencia},
#         **data
#     }
# import logging
# import json
# from typing import List, Dict, Any
# from fastapi import APIRouter, HTTPException
#
# from tenant import current_tenant, current_business_name
# from DataBase import get_connection_context
#
# logger = logging.getLogger(__name__)
# router = APIRouter()
#
#
# # =====================================================
# # Utilidades de scoring / niveles
# # =====================================================
# def convertir_score_a_nivel_5(score: float) -> int:
#     """Convierte score (0..5) a nivel 1..5."""
#     if score >= 4.2:
#         return 5
#     elif score >= 3.8:
#         return 4
#     elif score >= 3.2:
#         return 3
#     elif score >= 2.5:
#         return 2
#     return 1
#
#
# def nivel_5_a_3(nivel_5: int) -> int:
#     """Reduce 1..5 a 1..3 para scripts cortos."""
#     if nivel_5 <= 2:
#         return 1
#     if nivel_5 == 3:
#         return 2
#     return 3
#
#
# def grupo_tarjeta(nivel_5: int) -> Dict[str, Any]:
#     """
#     Para front:
#       Fortalezas = 1
#       Desarrollo = 2
#       Riesgos     = 3
#     """
#     if nivel_5 >= 4:
#         return {"grupo_id": 1, "grupo_nombre": "Fortalezas"}
#     if nivel_5 == 3:
#         return {"grupo_id": 2, "grupo_nombre": "Desarrollo"}
#     return {"grupo_id": 3, "grupo_nombre": "Riesgos"}
#
#
# def icono_semaforo(nivel_3: int) -> str:
#     if nivel_3 == 3:
#         return "🟢"
#     if nivel_3 == 2:
#         return "🟡"
#     return "🔴"
#
#
# # =====================================================
# # Resumen ejecutivo por filas (sin motor)
# # =====================================================
# def generar_resumen_ejecutivo_filas(categorias: List[Dict[str, Any]]) -> str:
#     """
#     Espera categorias con:
#       - categoria_nombre
#       - nivel_3
#       - script_3
#     Devuelve 4 filas ordenadas:
#       POTENCIAL DE TALENTO
#       CAPACIDAD OPERATIVA
#       POTENCIAL DE MONETIZACIÓN
#       INTENCIÓN Y ALINEACIÓN
#     """
#
#     def linea(nivel_3: int, texto: str) -> str:
#         return f"{icono_semaforo(nivel_3)} {texto}"
#
#     # Mapeo flexible por nombre (por si en DB "Mercado" y tú lo llamas "Monetización")
#     mapa = {
#         "POTENCIAL DE TALENTO": None,
#         "CAPACIDAD OPERATIVA": None,
#         "POTENCIAL DE MONETIZACIÓN": None,
#         "INTENCIÓN Y ALINEACIÓN": None,
#     }
#
#     for c in categorias:
#         nombre = (c.get("categoria_nombre") or "").strip()
#         n3 = int(c.get("nivel_3") or 1)
#         s3 = (c.get("script_3") or "").strip()
#
#         if not s3:
#             s3 = "Sin definición estratégica."
#
#         if nombre == "Potencial de Talento":
#             mapa["POTENCIAL DE TALENTO"] = linea(n3, s3)
#
#         elif nombre == "Capacidad Operativa":
#             mapa["CAPACIDAD OPERATIVA"] = linea(n3, s3)
#
#         elif nombre in ("Potencial de Mercado", "Potencial de Monetización"):
#             mapa["POTENCIAL DE MONETIZACIÓN"] = linea(n3, s3)
#
#         elif nombre == "Intención y Alineación":
#             mapa["INTENCIÓN Y ALINEACIÓN"] = linea(n3, s3)
#
#     filas = []
#     if mapa["POTENCIAL DE TALENTO"]:
#         filas.append(f"POTENCIAL DE TALENTO: {mapa['POTENCIAL DE TALENTO']}")
#     if mapa["CAPACIDAD OPERATIVA"]:
#         filas.append(f"CAPACIDAD OPERATIVA: {mapa['CAPACIDAD OPERATIVA']}")
#     if mapa["POTENCIAL DE MONETIZACIÓN"]:
#         filas.append(f"POTENCIAL DE MONETIZACIÓN: {mapa['POTENCIAL DE MONETIZACIÓN']}")
#     if mapa["INTENCIÓN Y ALINEACIÓN"]:
#         filas.append(f"INTENCIÓN Y ALINEACIÓN: {mapa['INTENCIÓN Y ALINEACIÓN']}")
#
#     return "\n\n".join(filas)
#
#
# # =====================================================
# # DB helpers
# # =====================================================
# def obtener_modelo_activo(cur) -> Dict[str, Any]:
#     cur.execute("""
#         SELECT id, nombre
#         FROM diagnostico_modelo
#         WHERE activo = true
#         LIMIT 1
#     """)
#     row = cur.fetchone()
#     if not row:
#         raise HTTPException(status_code=400, detail="No hay modelo activo")
#     return {"modelo_id": row[0], "modelo_nombre": row[1]}
#
#
# def obtener_perfil_creador(cur, creador_id: int) -> Dict[str, Any]:
#     cur.execute("""
#         SELECT nombre, edad, genero, pais, ciudad
#         FROM perfil_creador
#         WHERE creador_id = %s
#         LIMIT 1
#     """, (creador_id,))
#     row = cur.fetchone()
#     if not row:
#         raise HTTPException(status_code=404, detail="Creador no encontrado en perfil_creador")
#     return {
#         "nombre": row[0],
#         "edad": row[1],
#         "genero": row[2],
#         "pais": row[3],
#         "ciudad": row[4],
#     }
#
#
# def obtener_categorias_modelo(cur, modelo_id: int) -> List[Dict[str, Any]]:
#     cur.execute("""
#         SELECT id, nombre, peso_categoria
#         FROM diagnostico_categoria
#         WHERE modelo_id = %s
#         ORDER BY id ASC
#     """, (modelo_id,))
#     rows = cur.fetchall()
#     if not rows:
#         raise HTTPException(status_code=400, detail="El modelo activo no tiene categorías configuradas")
#     return [{"categoria_id": r[0], "categoria_nombre": r[1], "peso_categoria": float(r[2])} for r in rows]
#
#
# def obtener_variables_de_categoria(cur, categoria_id: int) -> List[Dict[str, Any]]:
#     cur.execute("""
#         SELECT id, peso_variable
#         FROM diagnostico_variable
#         WHERE categoria_id = %s
#     """, (categoria_id,))
#     rows = cur.fetchall()
#     return [{"variable_id": r[0], "peso_variable": float(r[1])} for r in rows]
#
#
# def obtener_score_variable(cur, creador_id: int, variable_id: int) -> int:
#     cur.execute("""
#         SELECT score
#         FROM diagnostico_score_variable
#         WHERE creador_id = %s
#           AND variable_id = %s
#         LIMIT 1
#     """, (creador_id, variable_id))
#     row = cur.fetchone()
#     return int(row[0]) if row else 0
#
#
# def obtener_script(cur, categoria_id: int, escala: int, nivel: int) -> str:
#     cur.execute("""
#         SELECT script
#         FROM diagnostico_interpretacion_categoria
#         WHERE categoria_id = %s
#           AND escala = %s
#           AND nivel = %s
#         LIMIT 1
#     """, (categoria_id, escala, nivel))
#     row = cur.fetchone()
#     return row[0] if row else "Sin definición estratégica."
#
#
# def sobrescribir_score_categoria(cur, creador_id: int, modelo_id: int, filas: List[Dict[str, Any]]) -> None:
#     cur.execute("""
#         DELETE FROM diagnostico_score_categoria
#         WHERE creador_id = %s AND modelo_id = %s
#     """, (creador_id, modelo_id))
#
#     for f in filas:
#         cur.execute("""
#             INSERT INTO diagnostico_score_categoria (modelo_id, creador_id, categoria_id, score_categoria, nivel)
#             VALUES (%s, %s, %s, %s, %s)
#         """, (modelo_id, creador_id, f["categoria_id"], f["score_categoria"], f["nivel_5"]))
#
#
# def sobrescribir_score_general(
#     cur,
#     creador_id: int,
#     modelo_id: int,
#     puntaje_total: float,
#     nivel_5: int,
#     diagnostico_json: dict,
#     diagnostico_resumen: str
# ) -> None:
#     cur.execute("""
#         DELETE FROM talento_score_general
#         WHERE creador_id = %s AND modelo_id = %s
#     """, (creador_id, modelo_id))
#
#     cur.execute("""
#         INSERT INTO talento_score_general (creador_id, modelo_id, puntaje_total, nivel, diagnostico_json, diagnostico_resumen)
#         VALUES (%s, %s, %s, %s, %s::jsonb, %s)
#     """, (
#         creador_id,
#         modelo_id,
#         puntaje_total,
#         nivel_5,
#         json.dumps(diagnostico_json, ensure_ascii=False),
#         (diagnostico_resumen or "")[:200]
#     ))
#
#
# def actualizar_diagnostico_perfil(cur, creador_id: int, texto: str) -> None:
#     cur.execute("""
#         UPDATE perfil_creador
#         SET diagnostico = %s
#         WHERE creador_id = %s
#     """, (texto, creador_id))
#
#
# # =====================================================
# # Cálculo principal (sin MotorEnsamblajeV4)
# # =====================================================
# def calcular_diagnostico(conn, creador_id: int) -> Dict[str, Any]:
#     cur = conn.cursor()
#
#     # 1) Modelo activo
#     modelo = obtener_modelo_activo(cur)
#     modelo_id = modelo["modelo_id"]
#     modelo_nombre = modelo["modelo_nombre"]
#
#     # 2) Perfil demográfico
#     perfil = obtener_perfil_creador(cur, creador_id)
#
#     # 3) Categorías + pesos
#     categorias = obtener_categorias_modelo(cur, modelo_id)
#
#     resultado_categorias: List[Dict[str, Any]] = []
#     score_total = 0.0
#
#     # 4) Calcular score por categoría (ponderado por variable) y score total (ponderado por categoría)
#     for c in categorias:
#         cat_id = c["categoria_id"]
#         cat_nombre = c["categoria_nombre"]
#         peso_cat = c["peso_categoria"]
#
#         variables = obtener_variables_de_categoria(cur, cat_id)
#
#         score_categoria = 0.0
#         for v in variables:
#             var_id = v["variable_id"]
#             peso_var = v["peso_variable"]
#             score_var = obtener_score_variable(cur, creador_id, var_id)
#             score_categoria += (score_var * (peso_var / 100.0))
#
#         score_categoria = round(score_categoria, 2)
#         nivel_5 = convertir_score_a_nivel_5(score_categoria)
#         nivel_3 = nivel_5_a_3(nivel_5)
#
#         # Scripts:
#         script_5 = obtener_script(cur, cat_id, escala=5, nivel=nivel_5)   # requerido
#         script_3 = obtener_script(cur, cat_id, escala=3, nivel=nivel_3)   # corto (para resumen)
#
#         grupo = grupo_tarjeta(nivel_5)
#
#         resultado_categorias.append({
#             "categoria_id": cat_id,
#             "categoria_nombre": cat_nombre,
#             "peso_categoria": peso_cat,
#             "score_5": score_categoria,
#             "nivel_5": nivel_5,
#             "nivel_3": nivel_3,
#             "grupo_id": grupo["grupo_id"],
#             "grupo_nombre": grupo["grupo_nombre"],
#             "script_5": script_5,
#             "script_3": script_3,
#             "porcentaje": round((score_categoria / 5.0) * 100.0, 2),
#         })
#
#         score_total += (score_categoria * (peso_cat / 100.0))
#
#     score_total = round(score_total, 2)
#     nivel_total_5 = convertir_score_a_nivel_5(score_total)
#     nivel_total_3 = nivel_5_a_3(nivel_total_5)
#
#     # 5) Nuevo texto ejecutivo por filas + semáforo
#     texto_ejecutivo = generar_resumen_ejecutivo_filas(resultado_categorias)
#     resumen_corto = texto_ejecutivo[:200]
#
#     # 6) Guardado (sobrescribir)
#     sobrescribir_score_categoria(cur, creador_id, modelo_id, [
#         {"categoria_id": c["categoria_id"], "score_categoria": c["score_5"], "nivel_5": c["nivel_5"]}
#         for c in resultado_categorias
#     ])
#
#     diagnostico_json = {
#         "creador_id": creador_id,
#         "modelo": {"id": modelo_id, "nombre": modelo_nombre},
#         "score_total": score_total,
#         "nivel_total_5": nivel_total_5,
#         "nivel_total_3": nivel_total_3,
#         "texto_ejecutivo": texto_ejecutivo,
#         "categorias": [
#             {
#                 "categoria_id": c["categoria_id"],
#                 "nombre": c["categoria_nombre"],
#                 "peso_categoria": c["peso_categoria"],
#                 "score_5": c["score_5"],
#                 "nivel_5": c["nivel_5"],
#                 "nivel_3": c["nivel_3"],
#                 "grupo_id": c["grupo_id"],
#                 "grupo_nombre": c["grupo_nombre"],
#                 "script_5": c["script_5"],
#                 "script_3": c["script_3"],
#             }
#             for c in resultado_categorias
#         ],
#         "version_motor": "filas_v1"
#     }
#
#     sobrescribir_score_general(
#         cur,
#         creador_id=creador_id,
#         modelo_id=modelo_id,
#         puntaje_total=score_total,
#         nivel_5=nivel_total_5,
#         diagnostico_json=diagnostico_json,
#         diagnostico_resumen=resumen_corto
#     )
#
#     # Actualiza perfil_creador.diagnostico con el texto ejecutivo (filas)
#     actualizar_diagnostico_perfil(cur, creador_id, texto_ejecutivo)
#
#     return {
#         "modelo": {"id": modelo_id, "nombre": modelo_nombre},
#         "perfil": perfil,
#         "score_total": score_total,
#         "nivel_total_5": nivel_total_5,
#         "nivel_total_3": nivel_total_3,
#         "texto_ejecutivo": texto_ejecutivo,
#         "categorias": resultado_categorias,
#     }
#
#
# # =====================================================
# # ENDPOINT
# # =====================================================
# @router.get("/api/creadores/{creador_id}/diagnostico")
# def diagnostico_creador(creador_id: int):
#     TENANT = current_tenant.get() if "current_tenant" in globals() else None
#     if TENANT is None:
#         raise HTTPException(status_code=400, detail="Tenant no disponible")
#
#     with get_connection_context() as conn:
#         data = calcular_diagnostico(conn, creador_id)
#         conn.commit()
#
#     nombre_agencia = current_business_name.get() if "current_business_name" in globals() else None
#
#     return {
#         "agencia": {"nombre": nombre_agencia},
#         **data
#     }
# import traceback
# import logging
# import pytz
# import secrets
# import string
# import random
# import json
#
# from pydantic import BaseModel, EmailStr
# from psycopg2.extras import RealDictCursor
# from datetime import datetime, timedelta
# from typing import Optional, List, Dict, Any
# from fastapi import APIRouter, HTTPException, Depends
# from schemas import *
# from main_auth import obtener_usuario_actual
#
# from tenant import current_tenant, current_business_name  # si ya los tienes (opcional)
# from DataBase import get_connection_context
#
# logger = logging.getLogger(__name__)
#
# router = APIRouter()   # ← ESTE ES EL ROUTER QUE VAS A IMPORTAR EN main.py
#
# # =====================================================
# # Motor de Ensamblaje (tu versión, sin cambios)
# # =====================================================
# class MotorEnsamblajeV4:
#     def __init__(self):
#         self.inicios = [
#             "Como síntesis ejecutiva, ",
#             "En el análisis estratégico del perfil, ",
#             "Evaluando el desempeño integral, ",
#             "Desde una perspectiva profesional, "
#         ]
#
#         self.conectores_adicion = [" Asimismo, ", " Además, ", " y adicionalmente "]
#         self.conectores_transicion = [
#             ". Por otro lado, ",
#             ". En términos de optimización, ",
#             ". A nivel de evolución estratégica, "
#         ]
#         self.conectores_adversidad = [
#             ". Sin embargo, ",
#             ". No obstante, ",
#             ". Como punto de atención prioritaria, "
#         ]
#
#         self.cierres_modelo = {
#             "Modelo Talento Premium": {
#                 "alto": ["El perfil está alineado con estándares premium de alto rendimiento."],
#                 "medio": ["Con ajustes estratégicos puede consolidarse en entorno premium."],
#                 "bajo": ["Debe reforzar fundamentos antes de aspirar a un posicionamiento premium."]
#             },
#             "Modelo Incubación": {
#                 "alto": ["El acompañamiento potenciará su consolidación acelerada."],
#                 "medio": ["Un plan estructurado permitirá evolución sólida."],
#                 "bajo": ["Requiere fase intensiva de desarrollo antes de avanzar."]
#             },
#             "Modelo Growth": {
#                 "alto": ["Está listo para escalar monetización y expansión."],
#                 "medio": ["Optimizar variables permitirá activar crecimiento sostenido."],
#                 "bajo": ["Debe estabilizar base antes de buscar expansión."]
#             },
#             "Modelo Balanceado": {
#                 "alto": ["Consolidar fortalezas garantizará estabilidad sostenible."],
#                 "medio": ["Nivelar variables permitirá mayor consistencia estratégica."],
#                 "bajo": ["Es fundamental reforzar estructura para equilibrio integral."]
#             }
#         }
#
#     def unir(self, textos: List[str], conectores: List[str]) -> str:
#         if not textos:
#             return ""
#         if len(textos) == 1:
#             return textos[0]
#         resultado = textos[0]
#         for t in textos[1:]:
#             resultado += random.choice(conectores) + t
#         return resultado
#
#     def tono(self, score: float) -> str:
#         if score >= 4.2:
#             return "alto"
#         elif score >= 3.3:
#             return "medio"
#         return "bajo"
#
#     def ensamblar(self, modelo: str, agrupado: Dict, score_total: float) -> str:
#         partes = []
#         inicio = random.choice(self.inicios)
#
#         if agrupado.get("fortalezas"):
#             textos = [c["mensaje"].lower() for c in agrupado["fortalezas"]]
#             partes.append(self.unir(textos, self.conectores_adicion))
#
#         if agrupado.get("desarrollo"):
#             textos = [c["mensaje"].lower() for c in agrupado["desarrollo"]]
#             bloque = self.unir(textos, self.conectores_adicion)
#             partes.append(random.choice(self.conectores_transicion) + bloque)
#
#         if agrupado.get("riesgos"):
#             textos = [c["mensaje"].lower() for c in agrupado["riesgos"]]
#             bloque = self.unir(textos, self.conectores_adicion)
#             partes.append(random.choice(self.conectores_adversidad) + bloque)
#
#         texto = inicio + "".join(partes)
#
#         cierre = random.choice(
#             self.cierres_modelo
#             .get(modelo, {"medio": ["Es necesario fortalecer estas áreas."]})
#             .get(self.tono(score_total), ["Es necesario fortalecer estas áreas."])
#         )
#
#         texto += " " + cierre
#         return texto[0].upper() + texto[1:]
#
#
# # =====================================================
# # Utilidades de scoring / niveles
# # =====================================================
# def convertir_score_a_nivel_5(score: float) -> int:
#     """Convierte score (0..5) a nivel 1..5."""
#     if score >= 4.2:
#         return 5
#     elif score >= 3.8:
#         return 4
#     elif score >= 3.2:
#         return 3
#     elif score >= 2.5:
#         return 2
#     return 1
#
#
# def nivel_5_a_3(nivel_5: int) -> int:
#     """Reduce 1..5 a 1..3 para resumen ejecutivo."""
#     if nivel_5 <= 2:
#         return 1
#     if nivel_5 == 3:
#         return 2
#     return 3
#
#
# def grupo_tarjeta(nivel_5: int) -> Dict[str, Any]:
#     """
#     Para front:
#       Fortalezas = 1
#       Desarrollo = 2
#       Riesgos     = 3
#     """
#     if nivel_5 >= 4:
#         return {"grupo_id": 1, "grupo_nombre": "Fortalezas"}
#     if nivel_5 == 3:
#         return {"grupo_id": 2, "grupo_nombre": "Desarrollo"}
#     return {"grupo_id": 3, "grupo_nombre": "Riesgos"}
#
#
# def agrupar_por_nivel_5(categorias_motor: list) -> dict:
#     fortalezas, desarrollo, riesgos = [], [], []
#     for c in categorias_motor:
#         if c["nivel_5"] >= 4:
#             fortalezas.append(c)
#         elif c["nivel_5"] == 3:
#             desarrollo.append(c)
#         else:
#             riesgos.append(c)
#     return {"fortalezas": fortalezas, "desarrollo": desarrollo, "riesgos": riesgos}
#
#
# # =====================================================
# # DB helpers
# # =====================================================
# def obtener_modelo_activo(cur) -> Dict[str, Any]:
#     cur.execute("""
#         SELECT id, nombre
#         FROM diagnostico_modelo
#         WHERE activo = true
#         LIMIT 1
#     """)
#     row = cur.fetchone()
#     if not row:
#         raise HTTPException(status_code=400, detail="No hay modelo activo")
#     return {"modelo_id": row[0], "modelo_nombre": row[1]}
#
#
# def obtener_perfil_creador(cur, creador_id: int) -> Dict[str, Any]:
#     # Ajusta columnas a tu tabla real:
#     cur.execute("""
#         SELECT nombre, edad, genero, pais, ciudad
#         FROM perfil_creador
#         WHERE creador_id = %s
#         LIMIT 1
#     """, (creador_id,))
#     row = cur.fetchone()
#     if not row:
#         raise HTTPException(status_code=404, detail="Creador no encontrado en perfil_creador")
#
#     return {
#         "nombre": row[0],
#         "edad": row[1],
#         "genero": row[2],
#         "pais": row[3],
#         "ciudad": row[4],
#     }
#
#
# def obtener_categorias_modelo(cur, modelo_id: int) -> List[Dict[str, Any]]:
#     cur.execute("""
#         SELECT id, nombre, peso_categoria
#         FROM diagnostico_categoria
#         WHERE modelo_id = %s
#         ORDER BY id ASC
#     """, (modelo_id,))
#     rows = cur.fetchall()
#     if not rows:
#         raise HTTPException(status_code=400, detail="El modelo activo no tiene categorías configuradas")
#
#     return [{"categoria_id": r[0], "categoria_nombre": r[1], "peso_categoria": float(r[2])} for r in rows]
#
#
# def obtener_variables_de_categoria(cur, categoria_id: int) -> List[Dict[str, Any]]:
#     cur.execute("""
#         SELECT id, peso_variable
#         FROM diagnostico_variable
#         WHERE categoria_id = %s
#     """, (categoria_id,))
#     rows = cur.fetchall()
#     return [{"variable_id": r[0], "peso_variable": float(r[1])} for r in rows]
#
#
# def obtener_score_variable(cur, creador_id: int, variable_id: int) -> int:
#     cur.execute("""
#         SELECT score
#         FROM diagnostico_score_variable
#         WHERE creador_id = %s
#           AND variable_id = %s
#         LIMIT 1
#     """, (creador_id, variable_id))
#     row = cur.fetchone()
#     return int(row[0]) if row else 0
#
#
# def obtener_script(cur, modelo_id: int, categoria_id: int, escala: int, nivel: int) -> str:
#     cur.execute("""
#         SELECT script
#         FROM diagnostico_interpretacion_categoria
#         WHERE modelo_id = %s
#           AND categoria_id = %s
#           AND escala = %s
#           AND nivel = %s
#         LIMIT 1
#     """, (modelo_id, categoria_id, escala, nivel))
#     row = cur.fetchone()
#     return row[0] if row else "Sin definición estratégica."
#
#
# def sobrescribir_score_categoria(cur, creador_id: int, modelo_id: int, filas: List[Dict[str, Any]]) -> None:
#     # sobrescribir = borrar y reinsertar
#     cur.execute("""
#         DELETE FROM diagnostico_score_categoria
#         WHERE creador_id = %s AND modelo_id = %s
#     """, (creador_id, modelo_id))
#
#     for f in filas:
#         cur.execute("""
#             INSERT INTO diagnostico_score_categoria (modelo_id, creador_id, categoria_id, score_categoria, nivel)
#             VALUES (%s, %s, %s, %s, %s)
#         """, (modelo_id, creador_id, f["categoria_id"], f["score_categoria"], f["nivel_5"]))
#
#
# def sobrescribir_score_general(cur, creador_id: int, modelo_id: int, puntaje_total: float,
#                               nivel_5: int, diagnostico_json: dict, diagnostico_resumen: str) -> None:
#     cur.execute("""
#         DELETE FROM talento_score_general
#         WHERE creador_id = %s AND modelo_id = %s
#     """, (creador_id, modelo_id))
#
#     cur.execute("""
#         INSERT INTO talento_score_general (creador_id, modelo_id, puntaje_total, nivel, diagnostico_json, diagnostico_resumen)
#         VALUES (%s, %s, %s, %s, %s::jsonb, %s)
#     """, (
#         creador_id,
#         modelo_id,
#         puntaje_total,
#         nivel_5,
#         json.dumps(diagnostico_json, ensure_ascii=False),
#         diagnostico_resumen[:200]
#     ))
#
#
# def actualizar_diagnostico_perfil(cur, creador_id: int, texto: str) -> None:
#     cur.execute("""
#         UPDATE perfil_creador
#         SET diagnostico = %s
#         WHERE creador_id = %s
#     """, (texto, creador_id))
#
#
# # =====================================================
# # Cálculo principal
# # =====================================================
# def calcular_diagnostico(conn, creador_id: int) -> Dict[str, Any]:
#     cur = conn.cursor()
#
#     # 1) Modelo activo
#     modelo = obtener_modelo_activo(cur)
#     modelo_id = modelo["modelo_id"]
#     modelo_nombre = modelo["modelo_nombre"]
#
#     # 2) Perfil demográfico
#     perfil = obtener_perfil_creador(cur, creador_id)
#
#     # 3) Categorías + pesos
#     categorias = obtener_categorias_modelo(cur, modelo_id)
#
#     resultado_categorias: List[Dict[str, Any]] = []
#     score_total = 0.0
#
#     # 4) Calcular score por categoría (ponderado por variable) y score total (ponderado por categoría)
#     for c in categorias:
#         cat_id = c["categoria_id"]
#         cat_nombre = c["categoria_nombre"]
#         peso_cat = c["peso_categoria"]
#
#         variables = obtener_variables_de_categoria(cur, cat_id)
#         if not variables:
#             score_categoria = 0.0
#         else:
#             # score_categoria: suma(score_var * peso_variable/100)
#             score_categoria = 0.0
#             for v in variables:
#                 var_id = v["variable_id"]
#                 peso_var = v["peso_variable"]
#                 score_var = obtener_score_variable(cur, creador_id, var_id)
#                 score_categoria += (score_var * (peso_var / 100.0))
#
#         score_categoria = round(score_categoria, 2)
#         nivel_5 = convertir_score_a_nivel_5(score_categoria)
#         nivel_3 = nivel_5_a_3(nivel_5)
#
#         # script correspondiente 1-5 (lo que pediste)
#         script_5 = obtener_script(cur, modelo_id, cat_id, escala=5, nivel=nivel_5)
#
#         # para el motor ejecutivo, usamos script 1-3
#         script_3 = obtener_script(cur, modelo_id, cat_id, escala=3, nivel=nivel_3)
#
#         grupo = grupo_tarjeta(nivel_5)
#
#         resultado_categorias.append({
#             "categoria_id": cat_id,
#             "categoria_nombre": cat_nombre,
#             "peso_categoria": peso_cat,
#             "score_5": score_categoria,     # 0..5 con decimales
#             "nivel_5": nivel_5,             # 1..5 (para colorear/segmentar)
#             "nivel_3": nivel_3,             # 1..3 (para resumen)
#             "grupo_id": grupo["grupo_id"],  # 1 fortalezas, 2 desarrollo, 3 riesgos
#             "grupo_nombre": grupo["grupo_nombre"],
#             "script_5": script_5,           # requerido
#             "script_3": script_3,           # útil para motor / opcional en front
#             "porcentaje": round((score_categoria / 5.0) * 100.0, 2),
#         })
#
#         score_total += (score_categoria * (peso_cat / 100.0))
#
#     score_total = round(score_total, 2)
#     nivel_total_5 = convertir_score_a_nivel_5(score_total)
#     nivel_total_3 = nivel_5_a_3(nivel_total_5)
#
#     # 5) Texto ejecutivo (con tu motor)
#     motor = MotorEnsamblajeV4()
#
#     categorias_motor = [
#         {
#             "categoria_id": c["categoria_id"],
#             "nivel_5": c["nivel_5"],
#             "mensaje": c["script_3"],  # resumen ejecutivo por categoría
#         }
#         for c in resultado_categorias
#     ]
#
#     agrupado = agrupar_por_nivel_5(categorias_motor)
#     texto_ejecutivo = motor.ensamblar(modelo_nombre, agrupado, score_total)
#     resumen_corto = texto_ejecutivo[:200]
#
#     # 6) Guardado (sobrescribir)
#     sobrescribir_score_categoria(cur, creador_id, modelo_id, [
#         {"categoria_id": c["categoria_id"], "score_categoria": c["score_5"], "nivel_5": c["nivel_5"]}
#         for c in resultado_categorias
#     ])
#
#     diagnostico_json = {
#         "creador_id": creador_id,
#         "modelo": {"id": modelo_id, "nombre": modelo_nombre},
#         "score_total": score_total,
#         "nivel_total_5": nivel_total_5,
#         "nivel_total_3": nivel_total_3,
#         "texto_ejecutivo": texto_ejecutivo,
#         "categorias": [
#             {
#                 "categoria_id": c["categoria_id"],
#                 "nombre": c["categoria_nombre"],
#                 "peso_categoria": c["peso_categoria"],
#                 "score_5": c["score_5"],
#                 "nivel_5": c["nivel_5"],
#                 "nivel_3": c["nivel_3"],
#                 "grupo_id": c["grupo_id"],
#                 "grupo_nombre": c["grupo_nombre"],
#                 "script_5": c["script_5"],
#             }
#             for c in resultado_categorias
#         ],
#         "version_motor": "v4"
#     }
#
#     sobrescribir_score_general(
#         cur,
#         creador_id=creador_id,
#         modelo_id=modelo_id,
#         puntaje_total=score_total,
#         nivel_5=nivel_total_5,
#         diagnostico_json=diagnostico_json,
#         diagnostico_resumen=resumen_corto
#     )
#
#     actualizar_diagnostico_perfil(cur, creador_id, texto_ejecutivo)
#
#     return {
#         "modelo": {"id": modelo_id, "nombre": modelo_nombre},
#         "perfil": perfil,
#         "score_total": score_total,
#         "nivel_total_5": nivel_total_5,
#         "nivel_total_3": nivel_total_3,
#         "texto_ejecutivo": texto_ejecutivo,
#         "categorias": resultado_categorias,
#     }
#
#
# # =====================================================
# # ENDPOINT
# # =====================================================
# @router.get("/api/creadores/{creador_id}/diagnostico")
# def diagnostico_creador(creador_id: int):
#     TENANT = current_tenant.get() if "current_tenant" in globals() else None
#     if TENANT is None:
#         # si en tu proyecto tenant no es obligatorio, puedes quitar esto
#         raise HTTPException(status_code=400, detail="Tenant no disponible")
#
#     with get_connection_context() as conn:
#         data = calcular_diagnostico(conn, creador_id)
#         conn.commit()
#
#     # Datos de agencia opcionales (si los manejas)
#     nombre_agencia = current_business_name.get() if "current_business_name" in globals() else None
#
#     return {
#         "agencia": {"nombre": nombre_agencia},
#         **data
#     }


# @router.get("/api/creadores/{creador_id}/diagnostico")
# def diagnostico_creador(creador_id:int):
#
#     TENANT=current_tenant.get()
#
#     if TENANT is None:
#         raise HTTPException(400,"Tenant no disponible")
#
#     with get_connection_context() as conn:
#
#         cur=conn.cursor()
#
#         # modelo activo
#         cur.execute("""
#         SELECT id,nombre
#         FROM diagnostico_modelo
#         WHERE activo=true
#         LIMIT 1
#         """)
#
#         modelo=cur.fetchone()
#
#         if not modelo:
#             raise HTTPException(400,"No hay modelo activo")
#
#         modelo_id=modelo[0]
#         modelo_nombre=modelo[1]
#
#         # perfil
#         cur.execute("""
#         SELECT nombre,edad,genero,pais,ciudad
#         FROM perfil_creador
#         WHERE creador_id=%s
#         """,(creador_id,))
#
#         p=cur.fetchone()
#
#         perfil={
#         "nombre":p[0],
#         "edad":p[1],
#         "genero":p[2],
#         "pais":p[3],
#         "ciudad":p[4]
#         }
#
#         diagnostico = obtener_diagnostico_v5(
#             cur,
#             creador_id,
#             modelo_id
#         )
#
#     nombre_agencia=current_business_name.get()
#
#     return{
#         "agencia":{"nombre":nombre_agencia},
#         "modelo":{
#         "id":modelo_id,
#         "nombre":modelo_nombre
#         },
#         "perfil":perfil,
#         "score_total":round(diagnostico["score_total"],2),
#         "categorias":diagnostico["categorias"]
#     }


# def obtener_diagnostico(cur, creador_id: int, modelo_id: int):
#
#     sql = """
#     WITH base AS (
#
#         SELECT
#             c.id AS categoria_id,
#             c.nombre AS categoria_nombre,
#             c.descripcion,
#             c.peso_categoria,
#
#             v.id AS variable_id,
#             v.nombre AS variable_nombre,
#             v.peso_variable,
#             v.orden,
#
#             vv.score,
#             vv.nivel
#
#         FROM diagnostico_categoria c
#
#         JOIN diagnostico_variable v
#             ON v.categoria_id = c.id
#             AND v.activa = true
#
#         LEFT JOIN diagnostico_score_variable sv
#             ON sv.variable_id = v.id
#             AND sv.creador_id = %(creador_id)s
#
#         LEFT JOIN diagnostico_variable_valor vv
#             ON vv.id = sv.valor
#
#         WHERE c.modelo_id = %(modelo_id)s
#     ),
#
#     calc AS (
#
#         SELECT
#             categoria_id,
#             categoria_nombre,
#             descripcion,
#             peso_categoria,
#
#             jsonb_agg(
#                 jsonb_build_object(
#                     'variable_id', variable_id,
#                     'variable', variable_nombre,
#                     'score', COALESCE(score,0),
#                     'nivel', nivel
#                 )
#                 ORDER BY orden
#             ) AS variables,
#
#             SUM(COALESCE(score,0) * (peso_variable/100.0)) AS score_categoria
#
#         FROM base
#
#         GROUP BY
#             categoria_id,
#             categoria_nombre,
#             descripcion,
#             peso_categoria
#     ),
#
#     niveles AS (
#
#         SELECT
#             *,
#
#             CASE
#                 WHEN score_categoria >= 3.75 THEN 3
#                 WHEN score_categoria >= 2.75 THEN 2
#                 ELSE 1
#             END AS nivel
#
#         FROM calc
#     )
#
#     SELECT
#
#         jsonb_agg(
#
#             jsonb_build_object(
#
#                 'categoria_id', n.categoria_id,
#                 'categoria_nombre', n.categoria_nombre,
#                 'descripcion', n.descripcion,
#
#                 'score', ROUND(n.score_categoria,2),
#                 'nivel', n.nivel,
#
#                 'script', s.script,
#
#                 'variables', n.variables
#
#             )
#
#             ORDER BY n.categoria_id
#
#         ) AS categorias,
#
#         SUM(n.score_categoria * (n.peso_categoria/100.0)) AS score_total
#
#     FROM niveles n
#
#     LEFT JOIN diagnostico_interpretacion_categoria s
#         ON s.categoria_id = n.categoria_id
#         AND s.nivel = n.nivel
#         AND s.escala = 5
#     """
#
#     cur.execute(sql, {
#         "creador_id": creador_id,
#         "modelo_id": modelo_id
#     })
#
#     r = cur.fetchone()
#
#     if not r:
#         return {
#             "categorias": [],
#             "score_total": 0
#         }
#
#     categorias = r[0] if r[0] else []
#     score_total = float(r[1] or 0)
#
#     return {
#         "categorias": categorias,
#         "score_total": score_total
#     }



# @router.get("/api/creadores/{creador_id}/diagnostico")
# def obtener_diagnostico_creador(creador_id: int):
#
#     try:
#
#         TENANT = current_tenant.get()
#
#         if TENANT is None:
#             raise HTTPException(status_code=400, detail="Tenant no disponible")
#
#         with get_connection_context() as conn:
#
#             cur = conn.cursor()
#
#             # -----------------------------
#             # Modelo activo
#             # -----------------------------
#             cur.execute("""
#                 SELECT id, nombre
#                 FROM diagnostico_modelo
#                 WHERE activo = true
#                 LIMIT 1
#             """)
#
#             modelo = cur.fetchone()
#
#             if not modelo:
#                 raise HTTPException(status_code=404, detail="No hay modelo activo")
#
#             modelo_id = modelo[0]
#             modelo_nombre = modelo[1]
#
#             # -----------------------------
#             # Perfil del creador
#             # -----------------------------
#             cur.execute("""
#                 SELECT nombre, edad, genero, pais, ciudad
#                 FROM perfil_creador
#                 WHERE creador_id = %s
#             """, (creador_id,))
#
#             p = cur.fetchone()
#
#             perfil = None
#
#             if p:
#                 perfil = {
#                     "nombre": p[0],
#                     "edad": p[1],
#                     "genero": p[2],
#                     "pais": p[3],
#                     "ciudad": p[4]
#                 }
#
#             # -----------------------------
#             # Diagnóstico
#             # -----------------------------
#             diagnostico = obtener_diagnostico(
#                 cur,
#                 creador_id,
#                 modelo_id
#             )
#
#         # -----------------------------
#         # Agencia
#         # -----------------------------
#         nombre_agencia = current_business_name.get()
#
#         return {
#             "success": True,
#             "agencia": {
#                 "nombre": nombre_agencia
#             },
#             "modelo": {
#                 "id": modelo_id,
#                 "nombre": modelo_nombre
#             },
#             "perfil": perfil,
#             "score_total": round(diagnostico["score_total"], 2),
#             "categorias": diagnostico["categorias"]
#         }
#
#     except Exception as e:
#
#         print(f"❌ Error generando diagnóstico: {e}")
#
#         return {
#             "success": False,
#             "error": "Error generando diagnóstico"
#         }



# def obtener_diagnostico(cur, creador_id: int, modelo_id: int):
#     sql = """
#           WITH base AS (SELECT c.id          AS categoria_id, \
#                                c.nombre      AS categoria_nombre, \
#                                c.descripcion AS categoria_descripcion, \
#                                c.peso_categoria, \
#
#                                v.id          AS variable_id, \
#                                v.nombre      AS variable_nombre, \
#                                v.tipo, \
#                                v.peso_variable, \
#                                v.orden, \
#
#                                sv.valor      AS valor_rango, \
#                                vv.score      AS score_num, \
#                                vv.label      AS label \
#
#                         FROM diagnostico_modelo_categoria mc \
#                                  JOIN diagnostico_categoria c \
#                                       ON c.id = mc.categoria_id \
#                                  JOIN diagnostico_variable v \
#                                       ON v.categoria_id = c.id \
#                                           AND v.activa = true \
#
#                                  LEFT JOIN diagnostico_score_variable sv \
#                                            ON sv.variable_id = v.id \
#                                                AND sv.creador_id = %(creador_id)s \
#
#                                  LEFT JOIN diagnostico_variable_valor vv \
#                                            ON vv.id = sv.valor_id),
#
#                calc AS (SELECT categoria_id, \
#                                categoria_nombre, \
#                                categoria_descripcion, \
#                                peso_categoria, \
#
#                                jsonb_agg( \
#                                        jsonb_build_object( \
#                                                'variable_id', variable_id, \
#                                                'variable', variable_nombre, \
#                                                'tipo', tipo, \
#                                                'score', CASE \
#                                                             WHEN tipo = 'numérica' THEN COALESCE(score_num, 0) \
#                                                             ELSE COALESCE(valor_rango, 0) \
#                                                    END, \
#                                                'nivel', CASE \
#                                                             WHEN tipo = 'numérica' THEN COALESCE(nivel, NULL) \
#                                                             ELSE NULL \
#                                                    END, \
#                                                'label', label \
#                                        ) ORDER BY orden \
#                                ) AS variables, \
#
#                                SUM( \
#                                        CASE \
#                                            WHEN tipo = 'numérica' THEN COALESCE(score_num, 0) * (peso_variable / 100.0) \
#                                            ELSE COALESCE(valor_rango, 0) * (peso_variable / 100.0) \
#                                            END \
#                                ) AS score_categoria \
#
#                         FROM base \
#                         GROUP BY categoria_id, \
#                                  categoria_nombre, \
#                                  categoria_descripcion, \
#                                  peso_categoria),
#
#                niveles AS (SELECT *, \
#                                   CASE \
#                                       WHEN score_categoria >= 3.75 THEN 3 \
#                                       WHEN score_categoria >= 2.75 THEN 2 \
#                                       ELSE 1 \
#                                       END AS nivel \
#                            FROM calc)
#
#           SELECT jsonb_agg( \
#                          jsonb_build_object( \
#                                  'categoria_id', n.categoria_id, \
#                                  'categoria_nombre', n.categoria_nombre, \
#                                  'descripcion', n.categoria_descripcion, \
#                                  'score', ROUND(n.score_categoria, 2), \
#                                  'nivel', n.nivel, \
#                                  'script', s.script, \
#                                  'variables', n.variables \
#                          ) ORDER BY n.categoria_id \
#                  )                                                   AS categorias, \
#                  SUM(n.score_categoria * (n.peso_categoria / 100.0)) AS score_total
#           FROM niveles n
#                    LEFT JOIN diagnostico_interpretacion_categoria s
#                              ON s.categoria_id = n.categoria_id
#                                  AND s.nivel = n.nivel
#                                  AND s.escala = 5 \
#           """
#
#     cur.execute(sql, {
#         "creador_id": creador_id,
#         "modelo_id": modelo_id
#     })
#
#     r = cur.fetchone()
#
#     categorias = r[0] if r[0] else []
#     score_total = float(r[1] or 0)
#
#     return {
#         "categorias": categorias,
#         "score_total": score_total
#     }

# def obtener_diagnosticoV1(cur, creador_id: int, modelo_id: int):
#
#     sql = """
#     WITH variables_calc AS (
#
#         SELECT
#             mc.categoria_id,
#             mc.peso_categoria,
#             mc.orden AS categoria_orden,
#
#             v.id AS variable_id,
#             v.nombre AS variable_nombre,
#             v.tipo,
#             v.peso_variable,
#             v.orden AS variable_orden,
#
#             sv.valor,
#             vv.score,
#             vv.label,
#             vv.nivel,
#
#             CASE
#                 WHEN v.tipo = 'numérica'
#                 THEN COALESCE(vv.score,0)
#                 ELSE COALESCE(sv.valor,0)
#             END AS score_variable
#
#         FROM diagnostico_modelo_categoria mc
#
#         JOIN diagnostico_variable v
#             ON v.categoria_id = mc.categoria_id
#             AND v.activa = true
#
#         LEFT JOIN diagnostico_score_variable sv
#             ON sv.variable_id = v.id
#             AND sv.creador_id = %(creador_id)s
#
#         LEFT JOIN diagnostico_variable_valor vv
#             ON vv.id = sv.valor_id
#
#         WHERE mc.modelo_id = %(modelo_id)s
#     ),
#
#     categorias_calc AS (
#
#         SELECT
#             categoria_id,
#             peso_categoria,
#             categoria_orden,
#
#             jsonb_agg(
#                 jsonb_build_object(
#                     'variable_id', variable_id,
#                     'variable', variable_nombre,
#                     'tipo', tipo,
#                     'score', score_variable,
#                     'nivel', nivel,
#                     'label', label
#                 )
#                 ORDER BY variable_orden
#             ) AS variables,
#
#             SUM(score_variable * (peso_variable / 100.0)) AS score_categoria
#
#         FROM variables_calc
#
#         GROUP BY
#             categoria_id,
#             peso_categoria,
#             categoria_orden
#     )
#
#     SELECT
#         jsonb_agg(
#             jsonb_build_object(
#                 'categoria_id', c.id,
#                 'categoria_nombre', c.nombre,
#                 'descripcion', c.descripcion,
#                 'score', ROUND(cat.score_categoria,2),
#                 'nivel',
#                     CASE
#                         WHEN cat.score_categoria >= 3.75 THEN 3
#                         WHEN cat.score_categoria >= 2.75 THEN 2
#                         ELSE 1
#                     END,
#                 'script', s.script,
#                 'variables', cat.variables
#             )
#             ORDER BY cat.categoria_orden
#         ) AS categorias,
#
#         SUM(cat.score_categoria * (cat.peso_categoria / 100.0)) AS score_total
#
#     FROM categorias_calc cat
#
#     JOIN diagnostico_categoria c
#         ON c.id = cat.categoria_id
#
#     LEFT JOIN diagnostico_interpretacion_categoria s
#         ON s.categoria_id = cat.categoria_id
#         AND s.nivel =
#             CASE
#                 WHEN cat.score_categoria >= 3.75 THEN 3
#                 WHEN cat.score_categoria >= 2.75 THEN 2
#                 ELSE 1
#             END
#         AND s.escala = 5
#     """
#
#     cur.execute(sql, {
#         "creador_id": creador_id,
#         "modelo_id": modelo_id
#     })
#
#     r = cur.fetchone()
#
#     categorias = r[0] if r[0] else []
#     score_total = float(r[1] or 0)
#
#     return {
#         "categorias": categorias,
#         "score_total": score_total
#     }
#


# @router.get("/api/creadores/{creador_id}/diagnostico")
# def obtener_diagnostico_creador(creador_id: int):
#
#     try:
#         TENANT = current_tenant.get()
#         if TENANT is None:
#             raise HTTPException(status_code=400, detail="Tenant no disponible")
#
#         with get_connection_context() as conn:
#             cur = conn.cursor()
#
#             # -----------------------------
#             # Modelo activo
#             # -----------------------------
#             cur.execute("""
#                 SELECT id, nombre, descripcion
#                 FROM diagnostico_modelo
#                 WHERE activo = true
#                 LIMIT 1
#             """)
#             modelo = cur.fetchone()
#
#             if not modelo:
#                 raise HTTPException(status_code=404, detail="No hay modelo activo")
#
#             modelo_id = modelo[0]
#             modelo_nombre = modelo[1]
#             modelo_descripcion = modelo[2]
#
#             # -----------------------------
#             # Perfil del creador
#             # -----------------------------
#             cur.execute("""
#                 SELECT nombre, edad, genero, pais, ciudad
#                 FROM perfil_creador
#                 WHERE creador_id = %s
#             """, (creador_id,))
#             p = cur.fetchone()
#
#             perfil = None
#             if p:
#                 perfil = {
#                     "nombre": p[0],
#                     "edad": p[1],
#                     "genero": p[2],
#                     "pais": p[3],
#                     "ciudad": p[4]
#                 }
#
#             # -----------------------------
#             # Diagnóstico
#             # -----------------------------
#             diagnostico = obtener_diagnostico(
#                 cur,
#                 creador_id,
#                 modelo_id
#             )
#
#         # -----------------------------
#         # Agencia
#         # -----------------------------
#         nombre_agencia = current_business_name.get()
#
#         return {
#             "success": True,
#             "agencia": {
#                 "nombre": nombre_agencia
#             },
#             "modelo": {
#                 "id": modelo_id,
#                 "nombre": modelo_nombre,
#                 "descripcion": modelo_descripcion   # <-- nueva descripción del modelo
#             },
#             "perfil": perfil,
#             "score_total": round(diagnostico["score_total"], 2),
#             "categorias": diagnostico["categorias"]
#         }
#
#     except Exception as e:
#         print(f"❌ Error generando diagnóstico: {e}")
#         return {
#             "success": False,
#             "error": "Error generando diagnóstico"
#         }


# def obtener_diagnostico(cur, creador_id: int, modelo_id: int):
#
#     sql = """
#     WITH base AS (
#
#         SELECT
#             mc.categoria_id,
#             mc.peso_categoria,
#             mc.orden AS categoria_orden,
#
#                 c.nombre AS categoria_nombre,
#                 c.descripcion AS categoria_descripcion,
#
#             v.id AS variable_id,
#             v.nombre AS variable_nombre,
#             v.tipo,
#             v.peso_variable,
#             v.orden AS variable_orden,
#
#             sv.valor,
#             vv.score,
#             vv.label,
#             vv.nivel
#
#         FROM diagnostico_modelo_categoria mc
#
#         JOIN diagnostico_categoria c
#             ON c.id = mc.categoria_id
#
#         JOIN diagnostico_variable v
#             ON v.categoria_id = c.id
#             AND v.activa = true
#
#         LEFT JOIN diagnostico_score_variable sv
#             ON sv.variable_id = v.id
#             AND sv.creador_id = %(creador_id)s
#
#         LEFT JOIN diagnostico_variable_valor vv
#             ON vv.id = sv.valor_id
#
#         WHERE mc.modelo_id = %(modelo_id)s
#     ),
#
#     variables_calc AS (
#
#         SELECT
#             *,
#             CASE
#                 WHEN tipo = 'numérica' THEN COALESCE(score,0)
#                 ELSE COALESCE(valor,0)
#             END AS score_variable
#         FROM base
#     ),
#
#     categorias_calc AS (
#
#         SELECT
#             categoria_id,
#             categoria_nombre,
#             categoria_descripcion,
#             peso_categoria,
#             categoria_orden,
#
#             jsonb_agg(
#                 jsonb_build_object(
#                     'variable_id', variable_id,
#                     'variable', variable_nombre,
#                     'tipo', tipo,
#                     'score', score_variable,
#                     'nivel', nivel,
#                     'label', label
#                 )
#                 ORDER BY variable_orden
#             ) AS variables,
#
#             SUM(score_variable * (peso_variable / 100.0)) AS score_categoria
#
#         FROM variables_calc
#         GROUP BY
#             categoria_id,
#             categoria_nombre,
#             categoria_descripcion,
#             peso_categoria,
#             categoria_orden
#     ),
#
#     niveles AS (
#
#         SELECT *,
#         CASE
#             WHEN score_categoria >= 3.75 THEN 3
#             WHEN score_categoria >= 2.75 THEN 2
#             ELSE 1
#         END AS nivel
#         FROM categorias_calc
#     )
#
#     SELECT
#         jsonb_agg(
#             jsonb_build_object(
#                 'categoria_id', n.categoria_id,
#                 'categoria_nombre', n.categoria_nombre,
#                 'descripcion', n.categoria_descripcion,
#                 'score', ROUND(n.score_categoria,2),
#                 'nivel', n.nivel,
#                 'script', s.script,
#                 'variables', n.variables
#             )
#             ORDER BY n.categoria_orden
#         ) AS categorias,
#
#         SUM(n.score_categoria * (n.peso_categoria / 100.0)) AS score_total
#
#     FROM niveles n
#
#     LEFT JOIN diagnostico_interpretacion_categoria s
#         ON s.categoria_id = n.categoria_id
#         AND s.nivel = n.nivel
#         AND s.escala = 5
#     """
#
#     cur.execute(sql, {
#         "creador_id": creador_id,
#         "modelo_id": modelo_id
#     })
#
#     r = cur.fetchone()
#
#     categorias = r[0] if r[0] else []
#     score_total = float(r[1] or 0)
#
#     return {
#         "categorias": categorias,
#         "score_total": score_total
#     }


# @router.post("/api/perfil_creador/{creador_id}/talento/actualizar",
#     tags=["Categoria talento"]
# )
# def sync_cualitativo_perfil_y_variables(
#     creador_id: int,
#     payload: PerfilCualitativoPayload,
#     usuario_actual: dict = Depends(obtener_usuario_actual),
# ):
#
#     try:
#
#         data = payload.model_dump()
#
#         # seguridad extra
#         for k, v in data.items():
#             try:
#                 data[k] = int(v)
#             except:
#                 raise HTTPException(status_code=400, detail=f"{k} debe ser entero")
#
#             if not (0 <= data[k] <= 5):
#                 raise HTTPException(status_code=400, detail=f"{k} debe estar entre 0 y 5")
#
#         with get_connection_context() as conn:
#             with conn.cursor() as cur:
#
#                 # 1️⃣ actualizar perfil_creador
#                 cur.execute("""
#                     UPDATE perfil_creador
#                     SET apariencia = %s,
#                         engagement = %s,
#                         calidad_contenido = %s,
#                         eval_biografia = %s,
#                         metadata_videos = %s,
#                         eval_foto = %s,
#                         potencial_estimado = %s
#                     WHERE creador_id = %s
#                 """, (
#                     data["apariencia"],
#                     data["engagement"],
#                     data["calidad_contenido"],
#                     data["eval_biografia"],
#                     data["metadata_videos"],
#                     data["eval_foto"],
#                     data["potencial_estimado"],
#                     creador_id
#                 ))
#
#                 perfil_rows = cur.rowcount
#
#                 # 2️⃣ pasar valores del perfil al score_variable
#                 guardar_scores_desde_perfil(cur, creador_id)
#
#             conn.commit()
#
#         return {
#             "status": "ok",
#             "mensaje": "perfil_creador actualizado y scores sincronizados",
#             "creador_id": creador_id,
#             "perfil_creador_filas_afectadas": perfil_rows,
#             "payload": data
#         }
#
#     except HTTPException:
#         raise
#
#     except Exception as e:
#         import traceback
#         traceback.print_exc()
#
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error en sync_cualitativo_perfil_y_variables: {str(e)}"
#         )



# def calcular_diagnostico_y_json(cur, creador_id: int, modelo_id: int):
#
#     sql = """
#     WITH variables_calc AS (
#
#         SELECT
#             mc.modelo_id,
#             mc.categoria_id,
#             mc.peso_categoria,
#             mc.orden AS categoria_orden,
#
#             v.id AS variable_id,
#             v.nombre AS variable_nombre,
#             v.tipo,
#             v.peso_variable,
#             v.orden AS variable_orden,
#
#             sv.valor,
#             vv.score,
#             vv.label,
#             vv.nivel,
#
#             CASE
#                 WHEN v.tipo = 'numérica'
#                 THEN COALESCE(vv.score,0)
#                 ELSE COALESCE(sv.valor,0)
#             END AS score_variable
#
#         FROM diagnostico_modelo_categoria mc
#
#         JOIN diagnostico_variable v
#             ON v.categoria_id = mc.categoria_id
#             AND v.activa = true
#
#         LEFT JOIN diagnostico_score_variable sv
#             ON sv.variable_id = v.id
#             AND sv.creador_id = %(creador_id)s
#
#         LEFT JOIN diagnostico_variable_valor vv
#             ON vv.id = sv.valor_id
#
#         WHERE mc.modelo_id = %(modelo_id)s
#     ),
#
#     categorias_calc AS (
#
#         SELECT
#             modelo_id,
#             categoria_id,
#             peso_categoria,
#             categoria_orden,
#
#             jsonb_agg(
#                 jsonb_build_object(
#                     'variable_id', variable_id,
#                     'variable', variable_nombre,
#                     'tipo', tipo,
#                     'score', score_variable,
#                     'nivel', nivel,
#                     'label', label
#                 )
#                 ORDER BY variable_orden
#             ) AS variables,
#
#             SUM(score_variable * (peso_variable / 100.0)) AS score_categoria
#
#         FROM variables_calc
#
#         GROUP BY
#             modelo_id,
#             categoria_id,
#             peso_categoria,
#             categoria_orden
#     ),
#
#     categorias_nivel AS (
#
#         SELECT
#             *,
#             CASE
#                 WHEN score_categoria >= 3.75 THEN 3
#                 WHEN score_categoria >= 2.75 THEN 2
#                 ELSE 1
#             END AS nivel
#         FROM categorias_calc
#     ),
#
#     guardar_categoria AS (
#
#         INSERT INTO diagnostico_score_categoria
#         (modelo_id, creador_id, categoria_id, score_categoria, nivel)
#
#         SELECT
#             modelo_id,
#             %(creador_id)s,
#             categoria_id,
#             ROUND(score_categoria,2),
#             nivel
#
#         FROM categorias_nivel
#
#         ON CONFLICT (modelo_id, creador_id, categoria_id)
#         DO UPDATE
#         SET
#             score_categoria = EXCLUDED.score_categoria,
#             nivel = EXCLUDED.nivel
#
#         RETURNING categoria_id
#     ),
#
#     categorias_json AS (
#
#         SELECT
#             cn.categoria_id,
#             cn.categoria_orden,
#             cn.variables,
#             cn.score_categoria,
#             cn.nivel,
#             c.nombre,
#             c.descripcion,
#             s.script
#
#         FROM categorias_nivel cn
#
#         JOIN diagnostico_categoria c
#             ON c.id = cn.categoria_id
#
#         LEFT JOIN diagnostico_interpretacion_categoria s
#             ON s.categoria_id = cn.categoria_id
#             AND s.nivel = cn.nivel
#             AND s.escala = 5
#     ),
#
#     json_final AS (
#
#         SELECT
#             jsonb_build_object(
#
#                 'score_total', ROUND(SUM(score_categoria * (peso_categoria / 100.0)),2),
#
#                 'categorias',
#
#                 jsonb_agg(
#                     jsonb_build_object(
#                         'categoria_id', categoria_id,
#                         'categoria_nombre', nombre,
#                         'descripcion', descripcion,
#                         'score', ROUND(score_categoria,2),
#                         'nivel', nivel,
#                         'script', script,
#                         'variables', variables
#                     )
#                     ORDER BY categoria_orden
#                 )
#
#             ) AS diagnostico_json
#
#         FROM categorias_json
#     )
#
#     INSERT INTO diagnostico_score_general
#     (creador_id, modelo_id, puntaje_total, nivel, diagnostico_json)
#
#     SELECT
#         %(creador_id)s,
#         %(modelo_id)s,
#
#         (diagnostico_json->>'score_total')::numeric,
#
#         CASE
#             WHEN (diagnostico_json->>'score_total')::numeric >= 3.75 THEN 3
#             WHEN (diagnostico_json->>'score_total')::numeric >= 2.75 THEN 2
#             ELSE 1
#         END,
#
#         diagnostico_json
#
#     FROM json_final
#
#     ON CONFLICT (creador_id, modelo_id)
#     DO UPDATE
#     SET
#         puntaje_total = EXCLUDED.puntaje_total,
#         nivel = EXCLUDED.nivel,
#         diagnostico_json = EXCLUDED.diagnostico_json
#     """
#
#     cur.execute(sql, {
#         "creador_id": creador_id,
#         "modelo_id": modelo_id
#     })



# @router.get("/api/creadores/{creador_id}/diagnostico")
# def diagnostico_creador(creador_id: int):
#
#     modelo_id = 1
#
#     with get_connection_context() as conn:
#
#         cur = conn.cursor()
#
#         cur.execute("""
#             SELECT diagnostico_json
#             FROM diagnostico_score_general
#             WHERE creador_id = %s
#             AND modelo_id = %s
#         """,(creador_id,modelo_id))
#
#         r = cur.fetchone()
#
#         if not r:
#             return {
#                 "success": False,
#                 "message": "Diagnóstico no calculado"
#             }
#
#         return {
#             "success": True,
#             **r[0]
#         }


# @router.post(
#     "/api/perfil_creador/{creador_id}/talento/actualizar",
#     tags=["Categoria talento"]
# )
# def sync_cualitativo_perfil_y_variables(
#     creador_id: int,
#     payload: PerfilCualitativoPayload,
#     usuario_actual: dict = Depends(obtener_usuario_actual),
# ):
#
#     try:
#
#         data = payload.model_dump()
#
#         # seguridad extra
#         for k, v in data.items():
#             try:
#                 data[k] = int(v)
#             except:
#                 raise HTTPException(status_code=400, detail=f"{k} debe ser entero")
#
#             if not (0 <= data[k] <= 5):
#                 raise HTTPException(status_code=400, detail=f"{k} debe estar entre 0 y 5")
#
#         with get_connection_context() as conn:
#             with conn.cursor() as cur:
#
#                 # 1️⃣ actualizar perfil_creador
#                 cur.execute("""
#                     UPDATE perfil_creador
#                     SET apariencia = %s,
#                         engagement = %s,
#                         calidad_contenido = %s,
#                         eval_biografia = %s,
#                         metadata_videos = %s,
#                         eval_foto = %s,
#                         potencial_estimado = %s
#                     WHERE creador_id = %s
#                 """, (
#                     data["apariencia"],
#                     data["engagement"],
#                     data["calidad_contenido"],
#                     data["eval_biografia"],
#                     data["metadata_videos"],
#                     data["eval_foto"],
#                     data["potencial_estimado"],
#                     creador_id
#                 ))
#
#                 perfil_rows = cur.rowcount
#
#                 # 2️⃣ pasar valores del perfil al score_variable
#                 guardar_scores_desde_perfil(cur, creador_id)
#
#                 # 3️⃣ recalcular diagnóstico completo
#                 modelo_id = 1
#                 calcular_diagnostico_y_json(cur, creador_id, modelo_id)
#
#             conn.commit()
#
#         return {
#             "status": "ok",
#             "mensaje": "perfil_creador actualizado, scores sincronizados y diagnóstico recalculado",
#             "creador_id": creador_id,
#             "perfil_creador_filas_afectadas": perfil_rows,
#             "payload": data
#         }
#
#     except HTTPException:
#         raise
#
#     except Exception as e:
#         import traceback
#         traceback.print_exc()
#
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error en sync_cualitativo_perfil_y_variables: {str(e)}"
#         )


# @router.post("/api/perfil_creador/{creador_id}/talento/actualizar",
#     tags=["Categoria talento"]
# )
# def sync_cualitativo_perfil_y_variables(
#     creador_id: int,
#     payload: PerfilCualitativoPayload,
#     usuario_actual: dict = Depends(obtener_usuario_actual),
# ):
#
#     try:
#
#         data = payload.model_dump()
#
#         # seguridad extra
#         for k, v in data.items():
#             try:
#                 data[k] = int(v)
#             except:
#                 raise HTTPException(status_code=400, detail=f"{k} debe ser entero")
#
#             if not (0 <= data[k] <= 5):
#                 raise HTTPException(status_code=400, detail=f"{k} debe estar entre 0 y 5")
#
#         with get_connection_context() as conn:
#             with conn.cursor() as cur:
#
#                 # 1️⃣ actualizar perfil_creador
#                 cur.execute("""
#                     UPDATE perfil_creador
#                     SET apariencia = %s,
#                         engagement = %s,
#                         calidad_contenido = %s,
#                         eval_biografia = %s,
#                         metadata_videos = %s,
#                         eval_foto = %s,
#                         potencial_estimado = %s
#                     WHERE creador_id = %s
#                 """, (
#                     data["apariencia"],
#                     data["engagement"],
#                     data["calidad_contenido"],
#                     data["eval_biografia"],
#                     data["metadata_videos"],
#                     data["eval_foto"],
#                     data["potencial_estimado"],
#                     creador_id
#                 ))
#
#                 perfil_rows = cur.rowcount
#
#                 # 2️⃣ pasar valores del perfil al score_variable
#                 guardar_scores_desde_perfil(cur, creador_id)
#
#                 # 3️⃣ obtener modelo activo
#                 cur.execute("""
#                     SELECT id
#                     FROM diagnostico_modelo
#                     WHERE activo = true
#                     LIMIT 1
#                 """)
#
#                 r_modelo = cur.fetchone()
#
#                 if not r_modelo:
#                     raise HTTPException(
#                         status_code=500,
#                         detail="No existe modelo de diagnóstico activo"
#                     )
#
#                 modelo_id = r_modelo[0]
#
#                 # 4️⃣ recalcular diagnóstico
#                 calcular_diagnostico_y_json(cur, creador_id, modelo_id)
#
#             conn.commit()
#
#         return {
#             "status": "ok",
#             "mensaje": "perfil_creador actualizado, scores sincronizados y diagnóstico recalculado",
#             "creador_id": creador_id,
#             "perfil_creador_filas_afectadas": perfil_rows,
#             "payload": data
#         }
#
#     except HTTPException:
#         raise
#
#     except Exception as e:
#         import traceback
#         traceback.print_exc()
#
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error en sync_cualitativo_perfil_y_variables: {str(e)}"
#         )


#
# @router.get("/api/creadores/{creador_id}/diagnostico")
# def diagnostico_creador(creador_id: int):
#
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         # 1️⃣ obtener modelo activo
#         cur.execute("""
#             SELECT id
#             FROM diagnostico_modelo
#             WHERE activo = true
#             LIMIT 1
#         """)
#
#         r_modelo = cur.fetchone()
#
#         if not r_modelo:
#             return {
#                 "success": False,
#                 "message": "No hay modelo de diagnóstico activo"
#             }
#
#         modelo_id = r_modelo[0]
#
#         # 2️⃣ buscar diagnóstico ya calculado
#         cur.execute("""
#             SELECT diagnostico_json
#             FROM diagnostico_score_general
#             WHERE creador_id = %s
#             AND modelo_id = %s
#         """, (creador_id, modelo_id))
#
#         r = cur.fetchone()
#
#         if not r:
#             return {
#                 "success": False,
#                 "message": "Diagnóstico no calculado"
#             }
#
#         return {
#             "success": True,
#             **r[0]
#         }



# def calcular_diagnostico_y_json(cur, creador_id: int, modelo_id: int):
#
#     sql = """
#     WITH modelo_info AS (
#
#         SELECT
#             id,
#             nombre,
#             descripcion
#         FROM diagnostico_modelo
#         WHERE id = %(modelo_id)s
#     ),
#
#     variables_calc AS (
#
#         SELECT
#             mc.modelo_id,
#             mc.categoria_id,
#             mc.peso_categoria,
#             mc.orden AS categoria_orden,
#
#             v.id AS variable_id,
#             v.nombre AS variable_nombre,
#             v.tipo,
#             v.peso_variable,
#             v.orden AS variable_orden,
#
#             sv.valor,
#             vv.score,
#             vv.nivel,
#             vv.label,
#
#             COALESCE(vv.score,0) AS score_variable
#
#         FROM diagnostico_modelo_categoria mc
#
#         JOIN diagnostico_variable v
#             ON v.categoria_id = mc.categoria_id
#             AND v.activa = true
#
#         LEFT JOIN diagnostico_score_variable sv
#             ON sv.variable_id = v.id
#             AND sv.creador_id = %(creador_id)s
#
#         LEFT JOIN diagnostico_variable_valor vv
#             ON vv.id = sv.valor_id
#
#         WHERE mc.modelo_id = %(modelo_id)s
#     ),
#
#     categorias_calc AS (
#
#         SELECT
#             modelo_id,
#             categoria_id,
#             peso_categoria,
#             categoria_orden,
#
#             jsonb_agg(
#                 jsonb_build_object(
#                     'variable_id', variable_id,
#                     'variable', variable_nombre,
#                     'tipo', tipo,
#                     'valor', valor,
#                     'score', score_variable,
#                     'peso_variable', peso_variable,
#                     'nivel', nivel,
#                     'label', label
#                 )
#                 ORDER BY variable_orden
#             ) AS variables,
#
#             SUM(score_variable * (peso_variable / 100.0)) AS score_categoria
#
#         FROM variables_calc
#
#         GROUP BY
#             modelo_id,
#             categoria_id,
#             peso_categoria,
#             categoria_orden
#     ),
#
#     categorias_nivel AS (
#
#         SELECT
#             *,
#             CASE
#                 WHEN score_categoria >= 3.75 THEN 3
#                 WHEN score_categoria >= 2.75 THEN 2
#                 ELSE 1
#             END AS nivel
#         FROM categorias_calc
#     ),
#
#     guardar_categoria AS (
#
#         INSERT INTO diagnostico_score_categoria
#         (modelo_id, creador_id, categoria_id, score_categoria, nivel)
#
#         SELECT
#             modelo_id,
#             %(creador_id)s,
#             categoria_id,
#             ROUND(score_categoria,2),
#             nivel
#
#         FROM categorias_nivel
#
#         ON CONFLICT (modelo_id, creador_id, categoria_id)
#         DO UPDATE
#         SET
#             score_categoria = EXCLUDED.score_categoria,
#             nivel = EXCLUDED.nivel
#
#         RETURNING categoria_id
#     ),
#
#     categorias_json AS (
#
#         SELECT
#             cn.categoria_id,
#             cn.categoria_orden,
#             cn.variables,
#             cn.score_categoria,
#             cn.peso_categoria,
#             cn.nivel,
#             c.nombre,
#             c.descripcion,
#             s.script
#
#         FROM categorias_nivel cn
#
#         JOIN diagnostico_categoria c
#             ON c.id = cn.categoria_id
#
#         LEFT JOIN diagnostico_interpretacion_categoria s
#             ON s.categoria_id = cn.categoria_id
#             AND s.nivel = cn.nivel
#             AND s.escala = 3
#     ),
#
#     total_calc AS (
#
#         SELECT
#             SUM(score_categoria * (peso_categoria / 100.0)) AS score_total
#         FROM categorias_json
#     ),
#
#     json_final AS (
#
#         SELECT
#             jsonb_build_object(
#
#                 'modelo_id', m.id,
#                 'modelo_nombre', m.nombre,
#                 'modelo_descripcion', m.descripcion,
#
#                 'score_total', ROUND(tc.score_total,2),
#
#                 'categorias',
#
#                 jsonb_agg(
#                     jsonb_build_object(
#                         'categoria_id', categoria_id,
#                         'categoria_nombre', nombre,
#                         'descripcion', descripcion,
#                         'peso_categoria', peso_categoria,
#                         'score', ROUND(score_categoria,2),
#                         'nivel', nivel,
#                         'script', script,
#                         'variables', variables
#                     )
#                     ORDER BY categoria_orden
#                 )
#
#             ) AS diagnostico_json,
#
#             tc.score_total
#
#         FROM categorias_json cj
#         CROSS JOIN total_calc tc
#         CROSS JOIN modelo_info m
#
#         GROUP BY
#             tc.score_total,
#             m.id,
#             m.nombre,
#             m.descripcion
#     )
#
#     INSERT INTO diagnostico_score_general
#     (creador_id, modelo_id, puntaje_total, nivel, diagnostico_json)
#
#     SELECT
#         %(creador_id)s,
#         %(modelo_id)s,
#         ROUND(score_total,2),
#
#         CASE
#             WHEN score_total >= 3.75 THEN 3
#             WHEN score_total >= 2.75 THEN 2
#             ELSE 1
#         END,
#
#         diagnostico_json
#
#     FROM json_final
#
#     ON CONFLICT (creador_id, modelo_id)
#     DO UPDATE
#     SET
#         puntaje_total = EXCLUDED.puntaje_total,
#         nivel = EXCLUDED.nivel,
#         diagnostico_json = EXCLUDED.diagnostico_json
#     """
#
#     cur.execute(sql, {
#         "creador_id": creador_id,
#         "modelo_id": modelo_id
#     })

# def calcular_diagnostico_y_json(cur, creador_id: int, modelo_id: int):
#
#     sql = """
#     WITH variables_calc AS (
#
#         SELECT
#             mc.modelo_id,
#             mc.categoria_id,
#             mc.peso_categoria,
#             mc.orden AS categoria_orden,
#
#             v.id AS variable_id,
#             v.nombre AS variable_nombre,
#             v.tipo,
#             v.peso_variable,
#             v.orden AS variable_orden,
#
#             sv.valor,
#             vv.score,
#             vv.nivel,
#             vv.label,
#
#             COALESCE(vv.score,0) AS score_variable
#
#         FROM diagnostico_modelo_categoria mc
#
#         JOIN diagnostico_variable v
#             ON v.categoria_id = mc.categoria_id
#             AND v.activa = true
#
#         LEFT JOIN diagnostico_score_variable sv
#             ON sv.variable_id = v.id
#             AND sv.creador_id = %(creador_id)s
#
#         LEFT JOIN diagnostico_variable_valor vv
#             ON vv.id = sv.valor_id
#
#         WHERE mc.modelo_id = %(modelo_id)s
#     ),
#
#     categorias_calc AS (
#
#         SELECT
#             modelo_id,
#             categoria_id,
#             peso_categoria,
#             categoria_orden,
#
#             jsonb_agg(
#                 jsonb_build_object(
#                     'variable_id', variable_id,
#                     'variable', variable_nombre,
#                     'tipo', tipo,
#                     'valor', valor,
#                     'score', score_variable,
#                     'nivel', nivel,
#                     'label', label
#                 )
#                 ORDER BY variable_orden
#             ) AS variables,
#
#             SUM(score_variable * (peso_variable / 100.0)) AS score_categoria
#
#         FROM variables_calc
#
#         GROUP BY
#             modelo_id,
#             categoria_id,
#             peso_categoria,
#             categoria_orden
#     ),
#
#     categorias_nivel AS (
#
#         SELECT
#             *,
#             CASE
#                 WHEN score_categoria >= 3.75 THEN 3
#                 WHEN score_categoria >= 2.75 THEN 2
#                 ELSE 1
#             END AS nivel
#         FROM categorias_calc
#     ),
#
#     guardar_categoria AS (
#
#         INSERT INTO diagnostico_score_categoria
#         (modelo_id, creador_id, categoria_id, score_categoria, nivel)
#
#         SELECT
#             modelo_id,
#             %(creador_id)s,
#             categoria_id,
#             ROUND(score_categoria,2),
#             nivel
#
#         FROM categorias_nivel
#
#         ON CONFLICT (modelo_id, creador_id, categoria_id)
#         DO UPDATE
#         SET
#             score_categoria = EXCLUDED.score_categoria,
#             nivel = EXCLUDED.nivel
#
#         RETURNING categoria_id
#     ),
#
#     categorias_json AS (
#
#         SELECT
#             cn.categoria_id,
#             cn.categoria_orden,
#             cn.variables,
#             cn.score_categoria,
#             cn.peso_categoria,
#             cn.nivel,
#             c.nombre,
#             c.descripcion,
#             s.script
#
#         FROM categorias_nivel cn
#
#         JOIN diagnostico_categoria c
#             ON c.id = cn.categoria_id
#
#         LEFT JOIN diagnostico_interpretacion_categoria s
#             ON s.categoria_id = cn.categoria_id
#             AND s.nivel = cn.nivel
#             AND s.escala = 3
#     ),
#
#     total_calc AS (
#
#         SELECT
#             SUM(score_categoria * (peso_categoria / 100.0)) AS score_total
#         FROM categorias_json
#     ),
#
#     json_final AS (
#
#         SELECT
#             jsonb_build_object(
#
#                 'score_total', ROUND(tc.score_total,2),
#
#                 'categorias',
#
#                 jsonb_agg(
#                     jsonb_build_object(
#                         'categoria_id', categoria_id,
#                         'categoria_nombre', nombre,
#                         'descripcion', descripcion,
#                         'score', ROUND(score_categoria,2),
#                         'nivel', nivel,
#                         'script', script,
#                         'variables', variables
#                     )
#                     ORDER BY categoria_orden
#                 )
#
#             ) AS diagnostico_json,
#
#             tc.score_total
#
#         FROM categorias_json cj
#         CROSS JOIN total_calc tc
#
#         GROUP BY tc.score_total
#     )
#
#     INSERT INTO diagnostico_score_general
#     (creador_id, modelo_id, puntaje_total, nivel, diagnostico_json)
#
#     SELECT
#         %(creador_id)s,
#         %(modelo_id)s,
#         ROUND(score_total,2),
#
#         CASE
#             WHEN score_total >= 3.75 THEN 3
#             WHEN score_total >= 2.75 THEN 2
#             ELSE 1
#         END,
#
#         diagnostico_json
#
#     FROM json_final
#
#     ON CONFLICT (creador_id, modelo_id)
#     DO UPDATE
#     SET
#         puntaje_total = EXCLUDED.puntaje_total,
#         nivel = EXCLUDED.nivel,
#         diagnostico_json = EXCLUDED.diagnostico_json
#     """
#
#     cur.execute(sql, {
#         "creador_id": creador_id,
#         "modelo_id": modelo_id
#     })

# def calcular_diagnostico_y_json(cur, creador_id: int, modelo_id: int):
#
#     sql = """
#     WITH modelo_info AS (
#
#         SELECT
#             id,
#             nombre,
#             descripcion
#         FROM diagnostico_modelo
#         WHERE id = %(modelo_id)s
#     ),
#
#     demograficos AS (
#
#         SELECT
#             jsonb_object_agg(v.nombre, vv.label) AS data
#         FROM diagnostico_score_variable sv
#
#         JOIN diagnostico_variable v
#             ON v.id = sv.variable_id
#
#         LEFT JOIN diagnostico_variable_valor vv
#             ON vv.id = sv.valor_id
#
#         WHERE sv.creador_id = %(creador_id)s
#         AND sv.variable_id IN (1,2,3,12,20)
#     ),
#
#     variables_calc AS (
#
#         SELECT
#             mc.modelo_id,
#             mc.categoria_id,
#             mc.peso_categoria,
#             mc.orden AS categoria_orden,
#
#             v.id AS variable_id,
#             v.nombre AS variable_nombre,
#             v.tipo,
#             v.peso_variable,
#             v.orden AS variable_orden,
#
#             sv.valor,
#             vv.score,
#             vv.nivel,
#             vv.label,
#
#             COALESCE(vv.score,0) AS score_variable
#
#         FROM diagnostico_modelo_categoria mc
#
#         JOIN diagnostico_variable v
#             ON v.categoria_id = mc.categoria_id
#             AND v.activa = true
#
#         LEFT JOIN diagnostico_score_variable sv
#             ON sv.variable_id = v.id
#             AND sv.creador_id = %(creador_id)s
#
#         LEFT JOIN diagnostico_variable_valor vv
#             ON vv.id = sv.valor_id
#
#         WHERE mc.modelo_id = %(modelo_id)s
#     ),
#
#     categorias_calc AS (
#
#         SELECT
#             modelo_id,
#             categoria_id,
#             peso_categoria,
#             categoria_orden,
#
#             jsonb_agg(
#                 jsonb_build_object(
#                     'variable_id', variable_id,
#                     'variable', variable_nombre,
#                     'tipo', tipo,
#                     'valor', valor,
#                     'score', score_variable,
#                     'peso_variable', peso_variable,
#                     'nivel', nivel,
#                     'label', label
#                 )
#                 ORDER BY variable_orden
#             ) AS variables,
#
#             SUM(score_variable * (peso_variable / 100.0)) AS score_categoria
#
#         FROM variables_calc
#
#         GROUP BY
#             modelo_id,
#             categoria_id,
#             peso_categoria,
#             categoria_orden
#     ),
#
#     categorias_nivel AS (
#
#         SELECT
#             *,
#             CASE
#                 WHEN score_categoria >= 3.75 THEN 3
#                 WHEN score_categoria >= 2.75 THEN 2
#                 ELSE 1
#             END AS nivel
#         FROM categorias_calc
#     ),
#
#     guardar_categoria AS (
#
#         INSERT INTO diagnostico_score_categoria
#         (modelo_id, creador_id, categoria_id, score_categoria, nivel)
#
#         SELECT
#             modelo_id,
#             %(creador_id)s,
#             categoria_id,
#             ROUND(score_categoria,2),
#             nivel
#
#         FROM categorias_nivel
#
#         ON CONFLICT (modelo_id, creador_id, categoria_id)
#         DO UPDATE
#         SET
#             score_categoria = EXCLUDED.score_categoria,
#             nivel = EXCLUDED.nivel
#
#         RETURNING categoria_id
#     ),
#
#     categorias_json AS (
#
#         SELECT
#             cn.categoria_id,
#             cn.categoria_orden,
#             cn.variables,
#             cn.score_categoria,
#             cn.peso_categoria,
#             cn.nivel,
#             c.nombre,
#             c.descripcion,
#             s.script
#
#         FROM categorias_nivel cn
#
#         JOIN diagnostico_categoria c
#             ON c.id = cn.categoria_id
#
#         LEFT JOIN diagnostico_interpretacion_categoria s
#             ON s.categoria_id = cn.categoria_id
#             AND s.nivel = cn.nivel
#             AND s.escala = 3
#     ),
#
#     total_calc AS (
#
#         SELECT
#             SUM(score_categoria * (peso_categoria / 100.0)) AS score_total
#         FROM categorias_json
#     ),
#
#     json_final AS (
#
#         SELECT
#             jsonb_build_object(
#
#                 'modelo_id', m.id,
#                 'modelo_nombre', m.nombre,
#                 'modelo_descripcion', m.descripcion,
#
#                 'demograficos', d.data,
#
#                 'score_total', ROUND(tc.score_total,2),
#
#                 'categorias',
#
#                 jsonb_agg(
#                     jsonb_build_object(
#                         'categoria_id', categoria_id,
#                         'categoria_nombre', nombre,
#                         'descripcion', descripcion,
#                         'peso_categoria', peso_categoria,
#                         'score', ROUND(score_categoria,2),
#                         'nivel', nivel,
#                         'script', script,
#                         'variables', variables
#                     )
#                     ORDER BY categoria_orden
#                 )
#
#             ) AS diagnostico_json,
#
#             tc.score_total
#
#         FROM categorias_json cj
#         CROSS JOIN total_calc tc
#         CROSS JOIN modelo_info m
#         CROSS JOIN demograficos d
#
#         GROUP BY
#             tc.score_total,
#             m.id,
#             m.nombre,
#             m.descripcion,
#             d.data
#     )
#
#     INSERT INTO diagnostico_score_general
#     (creador_id, modelo_id, puntaje_total, nivel, diagnostico_json)
#
#     SELECT
#         %(creador_id)s,
#         %(modelo_id)s,
#         ROUND(score_total,2),
#
#         CASE
#             WHEN score_total >= 3.75 THEN 3
#             WHEN score_total >= 2.75 THEN 2
#             ELSE 1
#         END,
#
#         diagnostico_json
#
#     FROM json_final
#
#     ON CONFLICT (creador_id, modelo_id)
#     DO UPDATE
#     SET
#         puntaje_total = EXCLUDED.puntaje_total,
#         nivel = EXCLUDED.nivel,
#         diagnostico_json = EXCLUDED.diagnostico_json
#     """
#
#     cur.execute(sql, {
#         "creador_id": creador_id,
#         "modelo_id": modelo_id
#     })
#

# def calcular_diagnostico_y_json(cur, creador_id: int, modelo_id: int):
#
#     sql = """
#     WITH modelo_info AS (
#
#         SELECT
#             id,
#             nombre AS modelo_nombre,
#             descripcion AS modelo_descripcion
#         FROM diagnostico_modelo
#         WHERE id = %(modelo_id)s
#     ),
#
#     demograficos AS (
#
#         SELECT
#             jsonb_object_agg(v.nombre, vv.label) AS data
#         FROM diagnostico_score_variable sv
#
#         JOIN diagnostico_variable v
#             ON v.id = sv.variable_id
#
#         LEFT JOIN diagnostico_variable_valor vv
#             ON vv.id = sv.valor_id
#
#         WHERE sv.creador_id = %(creador_id)s
#         AND sv.variable_id IN (1,2,3,12,20)
#     ),
#
#     variables_calc AS (
#
#         SELECT
#             mc.modelo_id,
#             mc.categoria_id,
#             mc.peso_categoria,
#             mc.orden AS categoria_orden,
#
#             v.id AS variable_id,
#             v.nombre AS variable_nombre,
#             v.tipo,
#             v.peso_variable,
#             v.orden AS variable_orden,
#
#             sv.valor,
#             vv.score,
#             vv.nivel,
#             vv.label,
#
#             COALESCE(vv.score,0) AS score_variable
#
#         FROM diagnostico_modelo_categoria mc
#
#         JOIN diagnostico_variable v
#             ON v.categoria_id = mc.categoria_id
#             AND v.activa = true
#
#         LEFT JOIN diagnostico_score_variable sv
#             ON sv.variable_id = v.id
#             AND sv.creador_id = %(creador_id)s
#
#         LEFT JOIN diagnostico_variable_valor vv
#             ON vv.id = sv.valor_id
#
#         WHERE mc.modelo_id = %(modelo_id)s
#     ),
#
#     categorias_calc AS (
#
#         SELECT
#             modelo_id,
#             categoria_id,
#             peso_categoria,
#             categoria_orden,
#
#             jsonb_agg(
#                 jsonb_build_object(
#                     'variable_id', variable_id,
#                     'variable', variable_nombre,
#                     'tipo', tipo,
#                     'valor', valor,
#                     'score', score_variable,
#                     'peso_variable', peso_variable,
#                     'nivel', nivel,
#                     'label', label
#                 )
#                 ORDER BY variable_orden
#             ) AS variables,
#
#             SUM(score_variable * (peso_variable / 100.0)) AS score_categoria
#
#         FROM variables_calc
#
#         GROUP BY
#             modelo_id,
#             categoria_id,
#             peso_categoria,
#             categoria_orden
#     ),
#
#     categorias_nivel AS (
#
#         SELECT
#             *,
#             CASE
#                 WHEN score_categoria >= 3.75 THEN 3
#                 WHEN score_categoria >= 2.75 THEN 2
#                 ELSE 1
#             END AS nivel
#         FROM categorias_calc
#     ),
#
#     guardar_categoria AS (
#
#         INSERT INTO diagnostico_score_categoria
#         (modelo_id, creador_id, categoria_id, score_categoria, nivel)
#
#         SELECT
#             modelo_id,
#             %(creador_id)s,
#             categoria_id,
#             ROUND(score_categoria,2),
#             nivel
#
#         FROM categorias_nivel
#
#         ON CONFLICT (modelo_id, creador_id, categoria_id)
#         DO UPDATE
#         SET
#             score_categoria = EXCLUDED.score_categoria,
#             nivel = EXCLUDED.nivel
#
#         RETURNING categoria_id
#     ),
#
#     categorias_json AS (
#
#         SELECT
#             cn.categoria_id,
#             cn.categoria_orden,
#             cn.variables,
#             cn.score_categoria,
#             cn.peso_categoria,
#             cn.nivel,
#             c.nombre AS categoria_nombre,
#             c.descripcion AS categoria_descripcion,
#             s.script
#
#         FROM categorias_nivel cn
#
#         JOIN diagnostico_categoria c
#             ON c.id = cn.categoria_id
#
#         LEFT JOIN diagnostico_interpretacion_categoria s
#             ON s.categoria_id = cn.categoria_id
#             AND s.nivel = cn.nivel
#             AND s.escala = 3
#     ),
#
#     total_calc AS (
#
#         SELECT
#             SUM(score_categoria * (peso_categoria / 100.0)) AS score_total
#         FROM categorias_json
#     ),
#
#     json_final AS (
#
#         SELECT
#             jsonb_build_object(
#
#                 'modelo_id', m.id,
#                 'modelo_nombre', m.modelo_nombre,
#                 'modelo_descripcion', m.modelo_descripcion,
#
#                 'demograficos', d.data,
#
#                 'score_total', ROUND(tc.score_total,2),
#
#                 'categorias',
#
#                 jsonb_agg(
#                     jsonb_build_object(
#                         'categoria_id', categoria_id,
#                         'categoria_nombre', categoria_nombre,
#                         'descripcion', categoria_descripcion,
#                         'peso_categoria', peso_categoria,
#                         'score', ROUND(score_categoria,2),
#                         'nivel', nivel,
#                         'script', script,
#                         'variables', variables
#                     )
#                     ORDER BY categoria_orden
#                 )
#
#             ) AS diagnostico_json,
#
#             tc.score_total
#
#         FROM categorias_json cj
#         CROSS JOIN total_calc tc
#         CROSS JOIN modelo_info m
#         CROSS JOIN demograficos d
#
#         GROUP BY
#             tc.score_total,
#             m.id,
#             m.modelo_nombre,
#             m.modelo_descripcion,
#             d.data
#     )
#
#     INSERT INTO diagnostico_score_general
#     (creador_id, modelo_id, puntaje_total, nivel, diagnostico_json)
#
#     SELECT
#         %(creador_id)s,
#         %(modelo_id)s,
#         ROUND(score_total,2),
#
#         CASE
#             WHEN score_total >= 3.75 THEN 3
#             WHEN score_total >= 2.75 THEN 2
#             ELSE 1
#         END,
#
#         diagnostico_json
#
#     FROM json_final
#
#     ON CONFLICT (creador_id, modelo_id)
#     DO UPDATE
#     SET
#         puntaje_total = EXCLUDED.puntaje_total,
#         nivel = EXCLUDED.nivel,
#         diagnostico_json = EXCLUDED.diagnostico_json
#     """
#
#     cur.execute(sql, {
#         "creador_id": creador_id,
#         "modelo_id": modelo_id
#     })


# def calcular_diagnostico_y_json(cur, creador_id: int, modelo_id: int):
#
#     sql = """
#     WITH modelo_info AS (
#
#         SELECT
#             id,
#             nombre AS modelo_nombre,
#             descripcion AS modelo_descripcion
#         FROM diagnostico_modelo
#         WHERE id = %(modelo_id)s
#     ),
#
#     demograficos AS (
#
#         SELECT
#             jsonb_object_agg(v.nombre, vv.label) AS data
#         FROM diagnostico_score_variable sv
#
#         JOIN diagnostico_variable v
#             ON v.id = sv.variable_id
#
#         LEFT JOIN diagnostico_variable_valor vv
#             ON vv.id = sv.valor_id
#
#         WHERE sv.creador_id = %(creador_id)s
#         AND sv.variable_id IN (1,2,3,12,20)
#     ),
#
#     variables_calc AS (
#
#         SELECT
#             mc.modelo_id,
#             mc.categoria_id,
#             mc.peso_categoria,
#             mc.orden AS categoria_orden,
#
#             v.id AS variable_id,
#             v.nombre AS variable_nombre,
#             v.tipo,
#             v.peso_variable,
#             v.orden AS variable_orden,
#
#             sv.valor,
#             vv.score,
#             vv.nivel,
#             vv.label,
#
#             COALESCE(vv.score,0) AS score_variable
#
#         FROM diagnostico_modelo_categoria mc
#
#         JOIN diagnostico_variable v
#             ON v.categoria_id = mc.categoria_id
#             AND v.activa = true
#
#         LEFT JOIN diagnostico_score_variable sv
#             ON sv.variable_id = v.id
#             AND sv.creador_id = %(creador_id)s
#
#         LEFT JOIN diagnostico_variable_valor vv
#             ON vv.id = sv.valor_id
#
#         WHERE mc.modelo_id = %(modelo_id)s
#     ),
#
#     categorias_calc AS (
#
#         SELECT
#             modelo_id,
#             categoria_id,
#             peso_categoria,
#             categoria_orden,
#
#             jsonb_agg(
#                 jsonb_build_object(
#                     'variable_id', variable_id,
#                     'variable', variable_nombre,
#                     'tipo', tipo,
#                     'valor', valor,
#                     'score', score_variable,
#                     'peso_variable', peso_variable,
#                     'nivel', nivel,
#                     'label', label
#                 )
#                 ORDER BY variable_orden
#             ) AS variables,
#
#             SUM(score_variable * (peso_variable / 100.0)) AS score_categoria
#
#         FROM variables_calc
#
#         GROUP BY
#             modelo_id,
#             categoria_id,
#             peso_categoria,
#             categoria_orden
#     ),
#
#     categorias_nivel AS (
#
#         SELECT
#             *,
#             CASE
#                 WHEN score_categoria >= 3.75 THEN 3
#                 WHEN score_categoria >= 2.75 THEN 2
#                 ELSE 1
#             END AS nivel
#         FROM categorias_calc
#     ),
#
#     guardar_categoria AS (
#
#         INSERT INTO diagnostico_score_categoria
#         (modelo_id, creador_id, categoria_id, score_categoria, nivel)
#
#         SELECT
#             modelo_id,
#             %(creador_id)s,
#             categoria_id,
#             ROUND(score_categoria,2),
#             nivel
#
#         FROM categorias_nivel
#
#         ON CONFLICT (modelo_id, creador_id, categoria_id)
#         DO UPDATE
#         SET
#             score_categoria = EXCLUDED.score_categoria,
#             nivel = EXCLUDED.nivel
#
#         RETURNING categoria_id
#     ),
#
#     categorias_json AS (
#
#         SELECT
#             cn.categoria_id,
#             cn.categoria_orden,
#             cn.variables,
#             cn.score_categoria,
#             cn.peso_categoria,
#             cn.nivel,
#             c.nombre AS categoria_nombre,
#             c.descripcion AS categoria_descripcion,
#             s.script
#
#         FROM categorias_nivel cn
#
#         JOIN diagnostico_categoria c
#             ON c.id = cn.categoria_id
#
#         LEFT JOIN diagnostico_interpretacion_categoria s
#             ON s.categoria_id = cn.categoria_id
#             AND s.nivel = cn.nivel
#             AND s.escala = 3
#     ),
#
#     total_calc AS (
#
#         SELECT
#             SUM(score_categoria * (peso_categoria / 100.0)) AS score_total
#         FROM categorias_json
#     ),
#
#     json_final AS (
#
#         SELECT
#             jsonb_build_object(
#
#                 'modelo_id', m.id,
#                 'modelo_nombre', m.modelo_nombre,
#                 'modelo_descripcion', m.modelo_descripcion,
#
#                 'demograficos', d.data,
#
#                 'score_total', ROUND(tc.score_total,2),
#
#                 'nivel_detalle',
#                 jsonb_build_object(
#                     'nivel',
#                     CASE
#                         WHEN tc.score_total < 1.5 THEN 1
#                         WHEN tc.score_total < 2.5 THEN 2
#                         WHEN tc.score_total < 3.25 THEN 3
#                         WHEN tc.score_total < 4.25 THEN 4
#                         ELSE 5
#                     END,
#                     'label',
#                     CASE
#                         WHEN tc.score_total < 1.5 THEN 'Muy bajo'
#                         WHEN tc.score_total < 2.5 THEN 'Bajo'
#                         WHEN tc.score_total < 3.25 THEN 'Medio'
#                         WHEN tc.score_total < 4.25 THEN 'Alto'
#                         ELSE 'Excelente'
#                     END
#                 ),
#
#                 'nivel_grupo',
#                 jsonb_build_object(
#                     'nivel',
#                     CASE
#                         WHEN tc.score_total < 2.5 THEN 1
#                         WHEN tc.score_total < 3.75 THEN 2
#                         ELSE 3
#                     END,
#                     'label',
#                     CASE
#                         WHEN tc.score_total < 2.5 THEN 'Bajo'
#                         WHEN tc.score_total < 3.75 THEN 'En desarrollo'
#                         ELSE 'Alto'
#                     END
#                 ),
#
#                 'categorias',
#
#                 jsonb_agg(
#                     jsonb_build_object(
#                         'categoria_id', categoria_id,
#                         'categoria_nombre', categoria_nombre,
#                         'descripcion', categoria_descripcion,
#                         'peso_categoria', peso_categoria,
#                         'score', ROUND(score_categoria,2),
#                         'nivel', nivel,
#                         'script', script,
#                         'variables', variables
#                     )
#                     ORDER BY categoria_orden
#                 )
#
#             ) AS diagnostico_json,
#
#             tc.score_total
#
#         FROM categorias_json cj
#         CROSS JOIN total_calc tc
#         CROSS JOIN modelo_info m
#         CROSS JOIN demograficos d
#
#         GROUP BY
#             tc.score_total,
#             m.id,
#             m.modelo_nombre,
#             m.modelo_descripcion,
#             d.data
#     )
#
#     INSERT INTO diagnostico_score_general
#     (creador_id, modelo_id, puntaje_total, nivel, diagnostico_json)
#
#     SELECT
#         %(creador_id)s,
#         %(modelo_id)s,
#         ROUND(score_total,2),
#
#         CASE
#             WHEN score_total >= 3.75 THEN 3
#             WHEN score_total >= 2.75 THEN 2
#             ELSE 1
#         END,
#
#         diagnostico_json
#
#     FROM json_final
#
#     ON CONFLICT (creador_id, modelo_id)
#     DO UPDATE
#     SET
#         puntaje_total = EXCLUDED.puntaje_total,
#         nivel = EXCLUDED.nivel,
#         diagnostico_json = EXCLUDED.diagnostico_json
#     """
#
#     cur.execute(sql, {
#         "creador_id": creador_id,
#         "modelo_id": modelo_id
#     })


# def calcular_diagnostico_y_json(cur, creador_id: int, modelo_id: int):
#
#     sql = """
#     WITH modelo_info AS (
#
#         SELECT
#             id,
#             nombre AS modelo_nombre,
#             descripcion AS modelo_descripcion
#         FROM diagnostico_modelo
#         WHERE id = %(modelo_id)s
#     ),
#
#     demograficos AS (
#
#         SELECT
#             jsonb_object_agg(v.nombre, vv.label) AS data
#         FROM diagnostico_score_variable sv
#         JOIN diagnostico_variable v
#             ON v.id = sv.variable_id
#         LEFT JOIN diagnostico_variable_valor vv
#             ON vv.id = sv.valor_id
#         WHERE sv.creador_id = %(creador_id)s
#         AND sv.variable_id IN (1,2,3,12,20)
#     ),
#
#     variables_calc AS (
#
#         SELECT
#             mc.modelo_id,
#             mc.categoria_id,
#             mc.peso_categoria,
#             mc.orden AS categoria_orden,
#
#             v.id AS variable_id,
#             v.nombre AS variable_nombre,
#             v.tipo,
#             v.peso_variable,
#             v.orden AS variable_orden,
#
#             sv.valor,
#             vv.score,
#             vv.nivel,
#             vv.label,
#
#             COALESCE(vv.score,0) AS score_variable
#
#         FROM diagnostico_modelo_categoria mc
#
#         JOIN diagnostico_variable v
#             ON v.categoria_id = mc.categoria_id
#             AND v.activa = true
#
#         LEFT JOIN diagnostico_score_variable sv
#             ON sv.variable_id = v.id
#             AND sv.creador_id = %(creador_id)s
#
#         LEFT JOIN diagnostico_variable_valor vv
#             ON vv.id = sv.valor_id
#
#         WHERE mc.modelo_id = %(modelo_id)s
#     ),
#
#     categorias_calc AS (
#
#         SELECT
#             modelo_id,
#             categoria_id,
#             peso_categoria,
#             categoria_orden,
#
#             jsonb_agg(
#                 jsonb_build_object(
#                     'variable_id', variable_id,
#                     'variable', variable_nombre,
#                     'tipo', tipo,
#                     'valor', valor,
#                     'score', score_variable,
#                     'peso_variable', peso_variable,
#                     'nivel', nivel,
#                     'label', label
#                 )
#                 ORDER BY variable_orden
#             ) AS variables,
#
#             SUM(score_variable * (peso_variable / 100.0)) AS score_categoria
#
#         FROM variables_calc
#
#         GROUP BY
#             modelo_id,
#             categoria_id,
#             peso_categoria,
#             categoria_orden
#     ),
#
#     categorias_nivel AS (
#
#         SELECT
#             *,
#             CASE
#                 WHEN score_categoria >= 3.75 THEN 3
#                 WHEN score_categoria >= 2.75 THEN 2
#                 ELSE 1
#             END AS nivel,
#
#             CASE
#                 WHEN score_categoria < 1.5 THEN 1
#                 WHEN score_categoria < 2.5 THEN 2
#                 WHEN score_categoria < 3.25 THEN 3
#                 WHEN score_categoria < 4.25 THEN 4
#                 ELSE 5
#             END AS nivel5
#
#         FROM categorias_calc
#     ),
#
#     guardar_categoria AS (
#
#         INSERT INTO diagnostico_score_categoria
#         (modelo_id, creador_id, categoria_id, score_categoria, nivel)
#
#         SELECT
#             modelo_id,
#             %(creador_id)s,
#             categoria_id,
#             ROUND(score_categoria,2),
#             nivel
#
#         FROM categorias_nivel
#
#         ON CONFLICT (modelo_id, creador_id, categoria_id)
#         DO UPDATE
#         SET
#             score_categoria = EXCLUDED.score_categoria,
#             nivel = EXCLUDED.nivel
#
#         RETURNING categoria_id
#     ),
#
#     categorias_json AS (
#
#         SELECT
#             cn.categoria_id,
#             cn.categoria_orden,
#             cn.variables,
#             cn.score_categoria,
#             cn.peso_categoria,
#             cn.nivel,
#             cn.nivel5,
#
#             c.nombre AS categoria_nombre,
#             c.descripcion AS categoria_descripcion,
#
#             s.script
#
#         FROM categorias_nivel cn
#
#         JOIN diagnostico_categoria c
#             ON c.id = cn.categoria_id
#
#         LEFT JOIN diagnostico_interpretacion_categoria s
#             ON s.categoria_id = cn.categoria_id
#             AND s.nivel = cn.nivel5
#             AND s.escala = 5
#     ),
#
#     total_calc AS (
#
#         SELECT
#             SUM(score_categoria * (peso_categoria / 100.0)) AS score_total
#         FROM categorias_json
#     ),
#
#     json_final AS (
#
#         SELECT
#             jsonb_build_object(
#
#                 'modelo_id', m.id,
#                 'modelo_nombre', m.modelo_nombre,
#                 'modelo_descripcion', m.modelo_descripcion,
#
#                 'demograficos', d.data,
#
#                 'score_total', ROUND(tc.score_total,2),
#
#                 'categorias',
#
#                 jsonb_agg(
#                     jsonb_build_object(
#                         'categoria_id', categoria_id,
#                         'categoria_nombre', categoria_nombre,
#                         'descripcion', categoria_descripcion,
#                         'peso_categoria', peso_categoria,
#                         'score', ROUND(score_categoria,2),
#                         'nivel', nivel,
#                         'nivel5', nivel5,
#                         'script', script,
#                         'variables', variables
#                     )
#                     ORDER BY categoria_orden
#                 )
#
#             ) AS diagnostico_json,
#
#             tc.score_total
#
#         FROM categorias_json cj
#         CROSS JOIN total_calc tc
#         CROSS JOIN modelo_info m
#         CROSS JOIN demograficos d
#
#         GROUP BY
#             tc.score_total,
#             m.id,
#             m.modelo_nombre,
#             m.modelo_descripcion,
#             d.data
#     )
#
#     INSERT INTO diagnostico_score_general
#     (creador_id, modelo_id, puntaje_total, nivel, diagnostico_json)
#
#     SELECT
#         %(creador_id)s,
#         %(modelo_id)s,
#         ROUND(score_total,2),
#
#         CASE
#             WHEN score_total >= 3.75 THEN 3
#             WHEN score_total >= 2.75 THEN 2
#             ELSE 1
#         END,
#
#         diagnostico_json
#
#     FROM json_final
#
#     ON CONFLICT (creador_id, modelo_id)
#     DO UPDATE
#     SET
#         puntaje_total = EXCLUDED.puntaje_total,
#         nivel = EXCLUDED.nivel,
#         diagnostico_json = EXCLUDED.diagnostico_json
#     """
#
#     cur.execute(sql, {
#         "creador_id": creador_id,
#         "modelo_id": modelo_id
#     })