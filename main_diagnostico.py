import logging
import json
from typing import List, Dict, Any, Optional, Tuple

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from main_auth import obtener_usuario_actual
from DataBase import get_connection_context

logger = logging.getLogger(__name__)
router = APIRouter()


# =========================================================
# MODELOS
# =========================================================

class PerfilCualitativoPayload(BaseModel):
    potencial_estimado: int = Field(..., ge=0, le=5)
    apariencia: int = Field(..., ge=0, le=5)
    engagement: int = Field(..., ge=0, le=5)
    calidad_contenido: int = Field(..., ge=0, le=5)
    eval_biografia: int = Field(..., ge=0, le=5)
    metadata_videos: int = Field(..., ge=0, le=5)
    eval_foto: int = Field(..., ge=0, le=5)


class ActualizarPreEvaluacionIn(BaseModel):
    estado_id: Optional[int] = None
    usuario_evalua: Optional[str] = None
    observaciones_finales: Optional[str] = None


# =========================================================
# HELPERS GENERALES
# =========================================================

def obtener_modelo_activo(cur) -> Optional[int]:
    cur.execute("""
        SELECT id
        FROM diagnostico_modelo
        WHERE activo = true
        ORDER BY id ASC
        LIMIT 1
    """)
    row = cur.fetchone()
    return row[0] if row else None


def score_a_100(score_5: float) -> int:
    try:
        return round((float(score_5) / 5.0) * 100)
    except Exception:
        return 0


def score_a_clasificacion(score_5: float) -> str:
    try:
        s = float(score_5)
    except Exception:
        s = 0.0

    if s >= 4.2:
        return "Alto potencial"
    if s >= 3.0:
        return "Potencial medio"
    return "Potencial en desarrollo"


def obtener_fortaleza_y_debilidad(
    categorias: List[Dict[str, Any]]
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if not categorias:
        return None, None

    fortaleza = max(categorias, key=lambda x: float(x.get("score", 0) or 0))
    debilidad = min(categorias, key=lambda x: float(x.get("score", 0) or 0))
    return fortaleza, debilidad


def top_variables_categoria(cat: Dict[str, Any], top_n: int = 3) -> List[str]:
    variables = cat.get("variables") or []

    variables_ordenadas = sorted(
        variables,
        key=lambda v: (
            float(v.get("score", 0) or 0),
            float(v.get("peso_variable", 0) or 0)
        ),
        reverse=True
    )

    salida: List[str] = []
    for v in variables_ordenadas:
        nombre = v.get("variable")
        if nombre and nombre not in salida:
            salida.append(nombre)
        if len(salida) >= top_n:
            break

    return salida


def cargar_categorias_catalogo(cur) -> Dict[int, Dict[str, Any]]:
    cur.execute("""
        SELECT
            id,
            nombre,
            descripcion,
            activo,
            created_at,
            nombre_natural
        FROM diagnostico_categoria
        WHERE activo = TRUE
    """)
    rows = cur.fetchall()

    catalogo: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        categoria_id, nombre, descripcion, activo, created_at, nombre_natural = row
        catalogo[int(categoria_id)] = {
            "id": categoria_id,
            "nombre": nombre,
            "descripcion": descripcion,
            "activo": activo,
            "created_at": created_at,
            "nombre_natural": nombre_natural
        }
    return catalogo


def resolver_nombre_corto_categoria(
    categoria_id=None,
    categoria_nombre=None,
    nombre_natural=None,
    catalogo_categorias=None
) -> str:
    """
    Función nueva con nombre distinto para evitar colisión
    con cualquier definición vieja de obtener_nombre_corto_categoria.
    No quema categorías.
    """
    catalogo_categorias = catalogo_categorias or {}

    if nombre_natural:
        return str(nombre_natural).strip()

    if categoria_id is not None and categoria_id in catalogo_categorias:
        nombre_natural_db = catalogo_categorias[categoria_id].get("nombre_natural")
        if nombre_natural_db:
            return str(nombre_natural_db).strip()

    if categoria_nombre:
        return str(categoria_nombre).strip()

    if categoria_id is not None and categoria_id in catalogo_categorias:
        nombre_db = catalogo_categorias[categoria_id].get("nombre")
        if nombre_db:
            return str(nombre_db).strip()

    return "Categoría"


def obtener_estado_por_nombre(cur, nombre_estado: str) -> Optional[int]:
    nombre_estado = nombre_estado.strip()

    cur.execute("""
                SELECT id
                FROM aspirantes_estados
                WHERE LOWER(nombre) = LOWER(%s) LIMIT 1
                """, (nombre_estado,))

    row = cur.fetchone()
    return row[0] if row else None


def obtener_estado_aspirante(cur, aspirante_id: int) -> Optional[Dict[str, Any]]:
    cur.execute("""
        SELECT
            a.estado_id,
            ae.nombre
        FROM aspirantes a
        LEFT JOIN aspirantes_estados ae
            ON ae.id = a.estado_id
        WHERE a.id = %s
    """, (aspirante_id,))
    row = cur.fetchone()
    if not row:
        return None

    estado_id, estado_nombre = row
    return {
        "id": estado_id,
        "nombre": estado_nombre
    }


# =========================================================
# INSIGHTS / RESÚMENES
# =========================================================

def generar_insights_principales(categorias: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    if not categorias:
        return {
            "insight_principal": None,
            "alerta_principal": None
        }

    def lista_texto(items: List[str]) -> str:
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        if len(items) == 2:
            return f"{items[0]} y {items[1]}"
        return ", ".join(items[:-1]) + f" y {items[-1]}"

    categorias_ordenadas = sorted(
        categorias,
        key=lambda x: float(x.get("score", 0) or 0),
        reverse=True
    )

    max_score = float(categorias_ordenadas[0].get("score", 0) or 0)
    min_score = float(categorias_ordenadas[-1].get("score", 0) or 0)

    fortalezas = [
        c for c in categorias
        if float(c.get("score", 0) or 0) >= 4.0
    ]

    if not fortalezas:
        margen = 0.20
        fortalezas = [
            c for c in categorias
            if float(c.get("score", 0) or 0) >= (max_score - margen)
        ]

    debilidad = min(
        categorias,
        key=lambda x: float(x.get("score", 0) or 0)
    )

    fortalezas_txt = lista_texto(
        [
            c.get("nombre_natural") or c.get("categoria_nombre")
            for c in fortalezas
            if c.get("nombre_natural") or c.get("categoria_nombre")
        ]
    ) or "áreas destacadas"

    debilidad_txt = (
        debilidad.get("nombre_natural")
        or debilidad.get("categoria_nombre")
        or "un área clave"
    )

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

    if float(debilidad.get("score", 0) or 0) <= 2.5:
        alerta_principal = (
            f"El principal punto de atención está en {debilidad_txt}."
        )
    elif float(debilidad.get("score", 0) or 0) < 3.2:
        alerta_principal = (
            f"Conviene seguir fortaleciendo {debilidad_txt}."
        )
    else:
        alerta_principal = None

    return {
        "insight_principal": insight_principal,
        "alerta_principal": alerta_principal
    }


def generar_resumen_corto_desde_diagnostico(diagnostico: Dict[str, Any]) -> str:
    categorias = diagnostico.get("categorias") or []
    fortaleza, debilidad = obtener_fortaleza_y_debilidad(categorias)

    score_total = float(diagnostico.get("score_total", 0) or 0)
    clasificacion = score_a_clasificacion(score_total)

    fortaleza_txt = (
        fortaleza.get("nombre_natural")
        or fortaleza.get("categoria_nombre")
        or "una categoría destacada"
    ) if fortaleza else "una categoría destacada"

    debilidad_txt = (
        debilidad.get("nombre_natural")
        or debilidad.get("categoria_nombre")
        or "un aspecto por fortalecer"
    ) if debilidad else "un aspecto por fortalecer"

    if clasificacion == "Alto potencial":
        return (
            f"Perfil sólido con alto potencial para avanzar en la agencia. "
            f"Su principal fortaleza está en {fortaleza_txt}, y conviene seguir fortaleciendo {debilidad_txt}."
        )

    if clasificacion == "Potencial medio":
        return (
            f"El perfil muestra una base favorable para crecer en TikTok LIVE. "
            f"Destaca en {fortaleza_txt}, aunque requiere fortalecer {debilidad_txt} para avanzar con mayor solidez."
        )

    return (
        f"El perfil se encuentra en desarrollo. "
        f"Presenta señales positivas en {fortaleza_txt}, pero necesita trabajar {debilidad_txt} antes de avanzar."
    )


# =========================================================
# MEJORAS SUGERIDAS: SOLO DESDE BD
# =========================================================

def _variables_bajas_configuradas_desde_bd(
    cur,
    categoria: Dict[str, Any],
    max_items: int = 2
) -> List[Dict[str, Any]]:
    variables = categoria.get("variables") or []
    if not variables:
        return []

    cfg_por_variable: Dict[int, Dict[str, Any]] = {}

    cur.execute("""
        SELECT
            variable_id,
            score_max,
            prioridad,
            texto
        FROM diagnostico_mejoras_variable
        WHERE activo = TRUE
    """)
    rows = cur.fetchall()

    for row in rows:
        variable_id, score_max, prioridad, texto = row
        cfg_por_variable[int(variable_id)] = {
            "score_max": float(score_max),
            "prioridad": int(prioridad),
            "texto": (texto or "").strip()
        }

    candidatas = []
    for v in variables:
        try:
            variable_id = int(v.get("variable_id"))
            score = float(v.get("score", 0) or 0)
            peso = float(v.get("peso_variable", 0) or 0)
        except Exception:
            continue

        cfg = cfg_por_variable.get(variable_id)
        if not cfg:
            continue

        if score <= cfg["score_max"]:
            candidatas.append({
                "variable_id": variable_id,
                "variable": v.get("variable"),
                "score": score,
                "peso_variable": peso,
                "texto": cfg["texto"],
                "prioridad": cfg["prioridad"]
            })

    candidatas.sort(
        key=lambda x: (
            x["prioridad"],
            x["score"],
            -x["peso_variable"]
        )
    )

    return candidatas[:max_items]


def generar_mejoras_prioritarias(cur, categorias: List[Dict[str, Any]]) -> List[str]:
    if not categorias:
        return []

    def cat_score(cat: Dict[str, Any]) -> float:
        return float(cat.get("score", 0) or 0)

    categorias_ordenadas = sorted(categorias, key=cat_score)
    mejoras: List[str] = []
    vistos = set()

    def agregar_texto(texto: Optional[str]) -> None:
        if not texto:
            return
        texto = texto.strip()
        if texto and texto not in vistos and len(mejoras) < 3:
            vistos.add(texto)
            mejoras.append(texto)

    def traer_mejoras_base_desde_bd(
        categoria_id: Optional[int],
        nivel5: Optional[int],
        limite: int
    ) -> List[str]:
        if categoria_id is None or nivel5 is None or limite <= 0:
            return []

        cur.execute("""
            SELECT texto
            FROM diagnostico_mejoras_sugeridas
            WHERE categoria_id = %s
              AND %s BETWEEN nivel_min AND nivel_max
              AND activo = TRUE
            ORDER BY prioridad ASC, id ASC
            LIMIT %s
        """, (categoria_id, nivel5, limite))

        rows = cur.fetchall()
        return [(r[0] or "").strip() for r in rows if r and r[0]]

    categoria_critica = categorias_ordenadas[0]

    for texto in traer_mejoras_base_desde_bd(
        categoria_id=categoria_critica.get("categoria_id"),
        nivel5=categoria_critica.get("nivel5"),
        limite=2
    ):
        agregar_texto(texto)

    for var in _variables_bajas_configuradas_desde_bd(
        cur=cur,
        categoria=categoria_critica,
        max_items=2
    ):
        agregar_texto(var.get("texto"))
        if len(mejoras) >= 3:
            break

    if len(mejoras) < 3 and len(categorias_ordenadas) > 1:
        categoria_secundaria = categorias_ordenadas[1]
        if cat_score(categoria_secundaria) <= 3.2:
            for texto in traer_mejoras_base_desde_bd(
                categoria_id=categoria_secundaria.get("categoria_id"),
                nivel5=categoria_secundaria.get("nivel5"),
                limite=(3 - len(mejoras))
            ):
                agregar_texto(texto)
                if len(mejoras) >= 3:
                    break

            if len(mejoras) < 3:
                for var in _variables_bajas_configuradas_desde_bd(
                    cur=cur,
                    categoria=categoria_secundaria,
                    max_items=1
                ):
                    agregar_texto(var.get("texto"))
                    if len(mejoras) >= 3:
                        break

    if not mejoras:
        mejoras = [
            "Define acciones concretas para fortalecer tu perfil.",
            "Convierte tu diagnóstico en un plan de mejora progresivo.",
        ]

    return mejoras[:3]


def generar_texto_whatsapp_completo(ui_data: Dict[str, Any]) -> str:
    resultado = ui_data.get("resultado", {})
    resumen_corto = ui_data.get("resumen_corto", "")
    categorias = ui_data.get("categorias", [])
    mejoras_prioritarias = ui_data.get("mejoras_prioritarias", [])

    partes: List[str] = []

    partes.append("📊 *Tu diagnóstico en TikTok LIVE*")
    partes.append("")
    partes.append("Este es tu resultado actual dentro del proceso de evaluación. Guárdalo para revisarlo más adelante.")
    partes.append("")
    partes.append("*Resultado general*")
    partes.append(f"⭐ Puntaje: {resultado.get('score_total')} ({resultado.get('score_total_100')}/100)")
    partes.append(f"📌 Clasificación: {resultado.get('clasificacion')}")
    partes.append("")

    if resumen_corto:
        partes.append("*Resumen*")
        partes.append(resumen_corto)
        partes.append("")

    if resultado.get("fortaleza_principal"):
        partes.append("*Fortaleza principal*")
        partes.append(f"🔥 {resultado.get('fortaleza_principal')}")
        partes.append("")

    if resultado.get("debilidad_principal"):
        partes.append("*Punto de mejora*")
        partes.append(f"⚠️ {resultado.get('debilidad_principal')}")
        partes.append("")

    if categorias:
        partes.append("*Detalle por categorías*")
        partes.append("")

        for cat in categorias:
            partes.append(f"*{cat.get('nombre_corto')}* — {cat.get('nivel5')}/5")

            if cat.get("script"):
                partes.append(str(cat.get("script")).strip())

            if cat.get("script_largo") and cat.get("script_largo") != cat.get("script"):
                partes.append(str(cat.get("script_largo")).strip())

            partes.append("")

    if mejoras_prioritarias:
        partes.append("*Mejoras prioritarias*")
        for mejora in mejoras_prioritarias:
            partes.append(f"• {mejora}")
        partes.append("")

    partes.append("✅ Guarda este mensaje. Este resultado puede no estar disponible más adelante.")

    return "\n".join(partes).strip()


def construir_diagnostico_ui(
    cur,
    diagnostico_json: Dict[str, Any],
    aspirante_id: Optional[int] = None,
    nickname: Optional[str] = None,
    nombre: Optional[str] = None,
    texto_whatsapp: Optional[str] = None
) -> Dict[str, Any]:
    categorias = diagnostico_json.get("categorias") or []
    score_total = float(diagnostico_json.get("score_total", 0) or 0)

    fortaleza, debilidad = obtener_fortaleza_y_debilidad(categorias)
    resumen_corto = diagnostico_json.get("diagnostico_resumen") or generar_resumen_corto_desde_diagnostico(diagnostico_json)
    catalogo_categorias = cargar_categorias_catalogo(cur)

    categorias_ui = []
    for c in categorias:
        categoria_id = c.get("categoria_id")
        estado = "neutral"

        if fortaleza and categoria_id == fortaleza.get("categoria_id"):
            estado = "fortaleza"
        elif debilidad and categoria_id == debilidad.get("categoria_id"):
            estado = "critica"

        categoria_nombre = c.get("categoria_nombre")
        nombre_natural = c.get("nombre_natural")

        categorias_ui.append({
            "categoria_id": categoria_id,
            "nombre": categoria_nombre or catalogo_categorias.get(categoria_id, {}).get("nombre"),
            "nombre_corto": resolver_nombre_corto_categoria(
                categoria_id=categoria_id,
                categoria_nombre=categoria_nombre,
                nombre_natural=nombre_natural,
                catalogo_categorias=catalogo_categorias
            ),
            "nombre_natural": nombre_natural or catalogo_categorias.get(categoria_id, {}).get("nombre_natural"),
            "descripcion": c.get("descripcion") or catalogo_categorias.get(categoria_id, {}).get("descripcion"),
            "peso_categoria": c.get("peso_categoria"),
            "score": c.get("score"),
            "nivel": c.get("nivel"),
            "nivel5": c.get("nivel5"),
            "script": c.get("script"),
            "script_largo": c.get("script_largo"),
            "top_variables": top_variables_categoria(c, top_n=3),
            "estado": estado
        })

    estado_aspirante = obtener_estado_aspirante(cur, aspirante_id) if aspirante_id else None

    ui_data = {
        "success": True,
        "creador": {
            "nickname": nickname,
            "nombre": nombre
        },
        "estado_aspirante": estado_aspirante,
        "resultado": {
            "score_total": round(score_total, 2),
            "score_total_100": score_a_100(score_total),
            "clasificacion": score_a_clasificacion(score_total),
            "insight_principal": diagnostico_json.get("insight_principal"),
            "alerta_principal": diagnostico_json.get("alerta_principal"),
            "fortaleza_principal": (
                fortaleza.get("nombre_natural")
                or fortaleza.get("categoria_nombre")
            ) if fortaleza else None,
            "debilidad_principal": (
                debilidad.get("nombre_natural")
                or debilidad.get("categoria_nombre")
            ) if debilidad else None,
        },
        "resumen_corto": resumen_corto,
        "categorias": categorias_ui,
        "mejoras_prioritarias": generar_mejoras_prioritarias(cur, categorias),
        "demograficos": diagnostico_json.get("demograficos", {}),
        "texto_whatsapp": texto_whatsapp
    }

    if not ui_data["texto_whatsapp"]:
        ui_data["texto_whatsapp"] = generar_texto_whatsapp_completo(ui_data)

    return ui_data


# =========================================================
# PERSISTENCIA DE DIAGNÓSTICO
# =========================================================

def guardar_scores_desde_perfil(cur, aspirante_id: int):
    cur.execute("""
        SELECT id, campo_db, tipo
        FROM diagnostico_variable
        WHERE encuesta_id = 0
          AND tipo IN ('numérica', 'rango')
          AND campo_db IS NOT NULL
    """)
    variables = cur.fetchall()

    if not variables:
        return

    values_sql = ",".join(
        f"({v[0]}, p.{v[1]})"
        for v in variables
    )

    sql = f"""
    WITH perfil_vars AS (
        SELECT
            p.aspirante_id,
            v.variable_id,
            v.valor
        FROM aspirantes_perfil p
        CROSS JOIN LATERAL (
            VALUES
            {values_sql}
        ) AS v(variable_id, valor)
        WHERE p.aspirante_id = %s
          AND v.valor IS NOT NULL
    ),
    valores_resueltos AS (
        SELECT
            pv.aspirante_id,
            pv.variable_id,
            pv.valor AS valor_original,
            dvv.id AS valor_modificado
        FROM perfil_vars pv
        JOIN diagnostico_variable dv
          ON dv.id = pv.variable_id
        JOIN diagnostico_variable_valor dvv
          ON dvv.variable_id = pv.variable_id
         AND (
              (dv.tipo = 'numérica' AND dvv.score = pv.valor)
              OR
              (dv.tipo = 'rango' AND pv.valor BETWEEN dvv.min_val AND dvv.max_val)
         )
    )
    INSERT INTO diagnostico_score_variable
    (aspirante_id, variable_id, valor, valor_id)
    SELECT
        aspirante_id,
        variable_id,
        valor_original,
        valor_modificado
    FROM valores_resueltos
    ON CONFLICT (aspirante_id, variable_id)
    DO UPDATE
    SET valor = EXCLUDED.valor,
        valor_id = EXCLUDED.valor_id
    """
    cur.execute(sql, (aspirante_id,))


def calcular_diagnostico_y_json(cur, aspirante_id: int, modelo_id: int):
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
            COALESCE(jsonb_object_agg(v.nombre, vv.label), '{}'::jsonb) AS data
        FROM diagnostico_score_variable sv
        JOIN diagnostico_variable v
            ON v.id = sv.variable_id
        LEFT JOIN diagnostico_variable_valor vv
            ON vv.id = sv.valor_id
        WHERE sv.aspirante_id = %(aspirante_id)s
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
            COALESCE(v.orden, 9999) AS variable_orden,

            sv.valor,
            vv.score,
            vv.nivel,
            vv.label,

            COALESCE(vv.score, 0) AS score_variable

        FROM diagnostico_modelo_categoria mc
        JOIN diagnostico_variable v
          ON v.categoria_id = mc.categoria_id
         AND v.activa = true

        LEFT JOIN diagnostico_score_variable sv
          ON sv.variable_id = v.id
         AND sv.aspirante_id = %(aspirante_id)s

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

            COALESCE(SUM(score_variable * (peso_variable / 100.0)), 0) AS score_categoria

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

            s.script,
            COALESCE(sl.script, s.script) AS script_largo

        FROM categorias_nivel cn
        JOIN diagnostico_categoria c
          ON c.id = cn.categoria_id

        LEFT JOIN diagnostico_interpretacion_categoria s
          ON s.categoria_id = cn.categoria_id
         AND s.nivel = cn.nivel5
         AND s.escala = 5

        LEFT JOIN diagnostico_interpretacion_categoria sl
          ON sl.categoria_id = cn.categoria_id
         AND sl.nivel = cn.nivel5
         AND sl.escala = 51
    ),

    total_calc AS (
        SELECT
            COALESCE(SUM(score_categoria * (peso_categoria / 100.0)), 0) AS score_total
        FROM categorias_json
    ),

    json_final AS (
        SELECT
            jsonb_build_object(
                'modelo_id', m.id,
                'modelo_nombre', m.modelo_nombre,
                'modelo_descripcion', m.modelo_descripcion,
                'demograficos', d.data,
                'score_total', ROUND(tc.score_total::numeric, 2),
                'categorias',
                COALESCE(
                    jsonb_agg(
                        jsonb_build_object(
                            'categoria_id', categoria_id,
                            'categoria_nombre', categoria_nombre,
                            'nombre_natural', nombre_natural,
                            'descripcion', categoria_descripcion,
                            'peso_categoria', peso_categoria,
                            'score', ROUND(score_categoria::numeric, 2),
                            'nivel', nivel,
                            'nivel5', nivel5,
                            'script', script,
                            'script_largo', script_largo,
                            'variables', variables
                        )
                        ORDER BY categoria_orden
                    ),
                    '[]'::jsonb
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
    (aspirante_id, modelo_id, puntaje_total, nivel, diagnostico_json)

    SELECT
        %(aspirante_id)s,
        %(modelo_id)s,
        ROUND(score_total::numeric, 2),
        CASE
            WHEN score_total >= 3.75 THEN 3
            WHEN score_total >= 2.75 THEN 2
            ELSE 1
        END,
        diagnostico_json
    FROM json_final

    ON CONFLICT (aspirante_id, modelo_id)
    DO UPDATE
    SET
        puntaje_total = EXCLUDED.puntaje_total,
        nivel = EXCLUDED.nivel,
        diagnostico_json = EXCLUDED.diagnostico_json
    """

    cur.execute(sql, {
        "aspirante_id": aspirante_id,
        "modelo_id": modelo_id
    })

    cur.execute("""
        SELECT diagnostico_json
        FROM diagnostico_score_general
        WHERE aspirante_id = %s
          AND modelo_id = %s
    """, (aspirante_id, modelo_id))

    row = cur.fetchone()
    if not row:
        return

    diagnostico = row[0] or {}
    categorias = []

    for c in diagnostico.get("categorias", []):
        categorias.append({
            "categoria_id": c.get("categoria_id"),
            "categoria_nombre": c.get("categoria_nombre"),
            "nombre_natural": c.get("nombre_natural"),
            "score": c.get("score", 0),
            "nivel5": c.get("nivel5"),
            "variables": c.get("variables", [])
        })

    insights = generar_insights_principales(categorias)
    diagnostico["insight_principal"] = insights["insight_principal"]
    diagnostico["alerta_principal"] = insights["alerta_principal"]

    resumen_corto = generar_resumen_corto_desde_diagnostico(diagnostico)

    ui_data = construir_diagnostico_ui(
        cur=cur,
        diagnostico_json={
            **diagnostico,
            "diagnostico_resumen": resumen_corto
        },
        aspirante_id=aspirante_id
    )

    texto_whatsapp = generar_texto_whatsapp_completo(ui_data)

    cur.execute("""
        UPDATE diagnostico_score_general
        SET diagnostico_json = %s,
            diagnostico_resumen = %s,
            texto_whatsapp = %s
        WHERE aspirante_id = %s
          AND modelo_id = %s
    """, (
        json.dumps(diagnostico, ensure_ascii=False),
        resumen_corto[:500],
        texto_whatsapp,
        aspirante_id,
        modelo_id
    ))


# =========================================================
# FLUJO DE TALENTO / PREEVALUACIÓN
# =========================================================

def actualizar_estado_preevaluacion(
    aspirante_id: int,
    payload: Dict[str, Any],
    *,
    usuario_id: Optional[int] = None,
):
    estado_id = payload.get("estado_id")

    with get_connection_context() as conn:
        with conn.cursor() as cur:

            # 🔒 Validar estado_id si viene
            if estado_id is not None:
                cur.execute("SELECT 1 FROM aspirantes_estados WHERE id = %s", (estado_id,))
                if not cur.fetchone():
                    raise ValueError(f"estado_id inválido: {estado_id}")

            # 🧠 Construir UPDATE de perfil (SIN estado_id)
            sets = []
            valores = []

            for campo, valor in payload.items():
                if campo != "estado_id" and valor is not None:
                    sets.append(f"{campo} = %s")
                    valores.append(valor)

            if sets:
                valores.append(aspirante_id)

                query = f"""
                    UPDATE aspirantes_perfil
                    SET {', '.join(sets)},
                        actualizado_en = NOW()
                    WHERE aspirante_id = %s
                """
                cur.execute(query, valores)

            # 🎯 Actualizar estado en tabla principal
            if estado_id is not None:
                cur.execute("""
                    UPDATE aspirantes
                    SET estado_id = %s
                    WHERE id = %s
                """, (estado_id, aspirante_id))

                obs_raw = payload.get("observaciones_finales")
                if obs_raw is not None:
                    obs_strip = str(obs_raw).strip()
                    obs_val = obs_strip[:300] if obs_strip else None
                else:
                    obs_val = None

                cur.execute(
                    """
                    INSERT INTO aspirantes_estado_historial (
                        aspirante_id, estado_id, usuario_id, origen_cambio, observacion
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        aspirante_id,
                        int(estado_id),
                        usuario_id,
                        "preevaluacion",
                        obs_val,
                    ),
                )

        conn.commit()

    logger.info(
        "Aspirante %s actualizado (estado_id=%s)",
        aspirante_id, estado_id
    )

@router.post(
    "/api/aspirantes_perfil/{aspirante_id}/talento/actualizar",
    tags=["Categoria talento"]
)
def sync_cualitativo_perfil_y_variables(
    aspirante_id: int,
    payload: PerfilCualitativoPayload,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    try:
        data = payload.model_dump()

        for k, v in data.items():
            try:
                data[k] = int(v)
            except Exception:
                raise HTTPException(status_code=400, detail=f"{k} debe ser entero")

            if not (0 <= data[k] <= 5):
                raise HTTPException(status_code=400, detail=f"{k} debe estar entre 0 y 5")

        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE aspirantes_perfil
                    SET apariencia = %s,
                        engagement = %s,
                        calidad_contenido = %s,
                        eval_biografia = %s,
                        metadata_videos = %s,
                        eval_foto = %s,
                        potencial_estimado = %s
                    WHERE aspirante_id = %s
                """, (
                    data["apariencia"],
                    data["engagement"],
                    data["calidad_contenido"],
                    data["eval_biografia"],
                    data["metadata_videos"],
                    data["eval_foto"],
                    data["potencial_estimado"],
                    aspirante_id
                ))

                perfil_rows = cur.rowcount

                guardar_scores_desde_perfil(cur, aspirante_id)

                modelo_id = obtener_modelo_activo(cur)
                if not modelo_id:
                    raise HTTPException(
                        status_code=500,
                        detail="No existe modelo de diagnóstico activo"
                    )

                calcular_diagnostico_y_json(cur, aspirante_id, modelo_id)

            conn.commit()

        return {
            "status": "ok",
            "mensaje": "aspirantes_perfil actualizado, scores sincronizados y diagnóstico recalculado",
            "aspirante_id": aspirante_id,
            "aspirantes_perfil_filas_afectadas": perfil_rows,
            "payload": data
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error en sync_cualitativo_perfil_y_variables")
        raise HTTPException(
            status_code=500,
            detail=f"Error en sync_cualitativo_perfil_y_variables: {str(e)}"
        )



# =========================================================
# ENDPOINTS DIAGNÓSTICO
# =========================================================

@router.get("/api/aspirantes/{aspirante_id}/diagnostico")
def diagnostico_creador(aspirante_id: int):
    with get_connection_context() as conn:
        with conn.cursor() as cur:

            modelo_id = obtener_modelo_activo(cur)
            if not modelo_id:
                return {
                    "success": False,
                    "message": "No hay modelo de diagnóstico activo"
                }

            cur.execute("""
                SELECT
                    d.diagnostico_json,
                    a.nickname,
                    COALESCE(NULLIF(TRIM(a.nombre_real), ''), a.nickname) AS nombre,
                    ae.id AS estado_id,
                    ae.nombre AS estado_nombre
                FROM diagnostico_score_general d
                JOIN aspirantes a
                    ON a.id = d.aspirante_id
                LEFT JOIN aspirantes_estados ae
                    ON ae.id = a.estado_id
                WHERE d.aspirante_id = %s
                  AND d.modelo_id = %s
            """, (aspirante_id, modelo_id))

            row = cur.fetchone()
            if not row:
                return {
                    "success": False,
                    "message": "Diagnóstico no calculado"
                }

            diagnostico_json, nickname, nombre, estado_id, estado_nombre = row

            return {
                "success": True,
                "creador": {
                    "nickname": nickname,
                    "nombre": nombre
                },
                "estado_aspirante": {
                    "id": estado_id,
                    "nombre": estado_nombre
                },
                **(diagnostico_json or {})
            }


@router.get("/api/aspirantes/{aspirante_id}/diagnostico-ui")
def diagnostico_aspirante_ui(aspirante_id: int):
    with get_connection_context() as conn:
        with conn.cursor() as cur:

            modelo_id = obtener_modelo_activo(cur)
            if not modelo_id:
                return {
                    "success": False,
                    "message": "No hay modelo de diagnóstico activo"
                }

            cur.execute("""
                SELECT
                    d.diagnostico_json,
                    d.diagnostico_resumen,
                    d.texto_whatsapp,
                    a.nickname,
                    COALESCE(NULLIF(TRIM(a.nombre_real), ''), a.nickname) AS nombre
                FROM diagnostico_score_general d
                JOIN aspirantes a
                    ON a.id = d.aspirante_id
                WHERE d.aspirante_id = %s
                  AND d.modelo_id = %s
            """, (aspirante_id, modelo_id))

            row = cur.fetchone()
            if not row:
                return {
                    "success": False,
                    "message": "Diagnóstico no calculado"
                }

            diagnostico_json, diagnostico_resumen, texto_whatsapp, nickname, nombre = row

            diagnostico_json = diagnostico_json or {}
            if diagnostico_resumen and isinstance(diagnostico_json, dict):
                diagnostico_json["diagnostico_resumen"] = diagnostico_resumen

            return construir_diagnostico_ui(
                cur=cur,
                diagnostico_json=diagnostico_json,
                aspirante_id=aspirante_id,
                nickname=nickname,
                nombre=nombre,
                texto_whatsapp=texto_whatsapp
            )


# =========================================================
# ENTREVISTA TIPOS
# =========================================================

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

            row = cur.fetchone()
            if not row:
                return {
                    "success": False,
                    "message": "Tipo de entrevista no encontrado"
                }

            columnas = [desc[0] for desc in cur.description]
            data = dict(zip(columnas, row))

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
                VALUES (%s, %s, %s, %s, %s, %s)
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

# @router.put("/api/aspirantes_perfil/{aspirante_id}/preevaluacion")
# def actualizar_preevaluacion(
#     aspirante_id: int,
#     datos: ActualizarPreEvaluacionIn,
#     usuario_actual: dict = Depends(obtener_usuario_actual),
# ):
#     try:
#         payload = {
#             "estado_id": datos.estado_id,
#             "usuario_evalua": datos.usuario_evalua,
#             "observaciones_finales": datos.observaciones_finales
#         }
#
#         uid = usuario_actual.get("id")
#         usuario_id = int(uid) if uid is not None else None
#         actualizar_estado_preevaluacion(aspirante_id, payload, usuario_id=usuario_id)
#
#         return {
#             "status": "ok",
#             "mensaje": "Pre-evaluación actualizada correctamente",
#             "aspirante_id": aspirante_id,
#             "estado_id": datos.estado_id,
#         }
#
#     except ValueError as ve:
#         raise HTTPException(status_code=400, detail=str(ve))
#
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))
