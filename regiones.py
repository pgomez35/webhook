"""Catálogo de regiones (LATAM / US+) y resolución desde país."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

CODIGO_LATAM = "latam"
CODIGO_US_PLUS = "us_plus"

REGIONES_SEED = (
    {"codigo": CODIGO_LATAM, "nombre": "LATAM", "orden": 1},
    {"codigo": CODIGO_US_PLUS, "nombre": "US+", "orden": 2},
)

SQL_SELECT_CREADOR_REGION = """
    c.region_id,
    rgn.codigo AS region_codigo,
    rgn.nombre AS region,
"""

SQL_JOIN_CREADOR_REGION = """
    LEFT JOIN regiones rgn ON rgn.id = c.region_id
"""

SQL_SELECT_ASPIRANTE_REGION = """
    ap.region_id,
    rgn.codigo AS region_codigo,
    rgn.nombre AS region,
"""

SQL_JOIN_ASPIRANTE_REGION = """
    LEFT JOIN regiones rgn ON rgn.id = ap.region_id
"""

_US_PLUS_LABELS = frozenset({
    "estados unidos",
    "united states",
    "united states of america",
    "usa",
    "us",
    "eeuu",
    "ee.uu.",
    "ee. uu.",
    "ee uu",
    "canada",
    "canadá",
})

_OTRO_LABELS = frozenset({
    "otro",
    "other",
    "otros",
    "otro pais",
    "otro país",
    "otro pais/region",
    "otro país/región",
})

ISO_PAIS_LABELS = {
    "AR": "Argentina",
    "BO": "Bolivia",
    "CL": "Chile",
    "CO": "Colombia",
    "CR": "Costa Rica",
    "CU": "Cuba",
    "EC": "Ecuador",
    "SV": "El Salvador",
    "GT": "Guatemala",
    "HN": "Honduras",
    "MX": "México",
    "NI": "Nicaragua",
    "PA": "Panamá",
    "PY": "Paraguay",
    "PE": "Perú",
    "PR": "Puerto Rico",
    "DO": "República Dominicana",
    "UY": "Uruguay",
    "VE": "Venezuela",
    "US": "Estados Unidos",
    "CA": "Canadá",
}

ISO_PAIS_ALIASES = {
    "US": ("Estados Unidos", "United States", "USA"),
    "CA": ("Canadá", "Canada"),
}


def normalizar_label_pais(valor: Any) -> str:
    if valor is None:
        return ""
    texto = str(valor).strip().lower()
    texto = texto.replace("á", "a").replace("é", "e").replace("í", "i")
    texto = texto.replace("ó", "o").replace("ú", "u").replace("ü", "u")
    return " ".join(texto.split())


def clasificar_label_pais(label: Any) -> Optional[str]:
    """Devuelve codigo de región, None si es 'Otro'/vacío (no inventar)."""
    norma = normalizar_label_pais(label)
    if not norma:
        return None
    if norma in {normalizar_label_pais(x) for x in _OTRO_LABELS}:
        return None
    if norma in {normalizar_label_pais(x) for x in _US_PLUS_LABELS}:
        return CODIGO_US_PLUS
    return CODIGO_LATAM


def es_pais_otro(label: Any) -> bool:
    return clasificar_label_pais(label) is None and bool(normalizar_label_pais(label))


def _row_get(row: Any, key: str, idx: int = 0) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[idx]
    except (IndexError, TypeError, KeyError):
        return None


def _coerce_int(valor: Any) -> Optional[int]:
    if valor is None or valor == "":
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def listar_regiones(cur) -> List[Dict[str, Any]]:
    try:
        cur.execute(
            """
            SELECT id, codigo, nombre, orden, activo
            FROM regiones
            WHERE COALESCE(activo, true) = true
            ORDER BY COALESCE(orden, 9999), id
            """
        )
    except Exception:
        logger.warning("No se pudo leer catálogo regiones", exc_info=True)
        return []
    out = []
    for row in cur.fetchall() or []:
        out.append(
            {
                "id": _row_get(row, "id", 0),
                "codigo": _row_get(row, "codigo", 1),
                "nombre": _row_get(row, "nombre", 2),
                "orden": _row_get(row, "orden", 3),
                "activo": _row_get(row, "activo", 4),
            }
        )
    return out


def obtener_region_id_por_codigo(cur, codigo: str) -> Optional[int]:
    if not codigo:
        return None
    cur.execute(
        "SELECT id FROM regiones WHERE codigo = %s LIMIT 1",
        (str(codigo).strip(),),
    )
    row = cur.fetchone()
    return _coerce_int(_row_get(row, "id", 0))


def obtener_region_catalogo_pais(cur, pais_id: Any) -> Optional[Dict[str, Any]]:
    """Región ligada al valor de catálogo de país (diagnostico_variable_valor)."""
    valor_id = _coerce_int(pais_id)
    if valor_id is None:
        return None
    cur.execute(
        """
        SELECT
            b.id AS valor_id,
            b.label,
            b.region_id,
            r.codigo AS region_codigo,
            r.nombre AS region
        FROM diagnostico_variable_valor b
        INNER JOIN diagnostico_variable a ON a.id = b.variable_id
        LEFT JOIN regiones r ON r.id = b.region_id
        WHERE b.id = %s AND a.campo_db = 'pais'
        LIMIT 1
        """,
        (valor_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "valor_id": _row_get(row, "valor_id", 0),
        "label": _row_get(row, "label", 1),
        "region_id": _coerce_int(_row_get(row, "region_id", 2)),
        "region_codigo": _row_get(row, "region_codigo", 3),
        "region": _row_get(row, "region", 4),
    }


def obtener_region_catalogo_pais_creador(cur, valor_id: Any) -> Optional[Dict[str, Any]]:
    vid = _coerce_int(valor_id)
    if vid is None:
        return None
    cur.execute(
        """
        SELECT
            b.id AS valor_id,
            b.label,
            b.region_id,
            r.codigo AS region_codigo,
            r.nombre AS region
        FROM creadores_perfil_valor b
        INNER JOIN creadores_perfil_variable a ON a.id = b.variable_id
        LEFT JOIN regiones r ON r.id = b.region_id
        WHERE b.id = %s AND a.campo_db = 'pais'
        LIMIT 1
        """,
        (vid,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "valor_id": _row_get(row, "valor_id", 0),
        "label": _row_get(row, "label", 1),
        "region_id": _coerce_int(_row_get(row, "region_id", 2)),
        "region_codigo": _row_get(row, "region_codigo", 3),
        "region": _row_get(row, "region", 4),
    }


def resolver_region_id_para_guardar(
    cur,
    pais_id: Any,
    region_id_usuario: Any,
    *,
    catalogo: str = "diagnostico",
) -> Optional[int]:
    """
    Si el país del catálogo tiene región, esa gana.
    Si no hay país o es 'Otro', se respeta region_id del usuario (puede ser NULL).
    """
    info = None
    if catalogo == "creador":
        info = obtener_region_catalogo_pais_creador(cur, pais_id)
    else:
        info = obtener_region_catalogo_pais(cur, pais_id)

    if info and info.get("region_id") is not None:
        return info["region_id"]

    if info and es_pais_otro(info.get("label")):
        return _coerce_int(region_id_usuario)

    if info is None and pais_id not in (None, ""):
        codigo = clasificar_label_pais(pais_id)
        if codigo:
            return obtener_region_id_por_codigo(cur, codigo)
        return _coerce_int(region_id_usuario)

    return _coerce_int(region_id_usuario)


def aplicar_region_aspirante_desde_pais(cur, aspirante_id: int) -> Optional[int]:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'aspirantes_perfil'
          AND column_name = 'region_id'
        LIMIT 1
        """
    )
    if not cur.fetchone():
        return None
    cur.execute(
        """
        SELECT pais, region_id
        FROM aspirantes_perfil
        WHERE aspirante_id = %s
        LIMIT 1
        """,
        (aspirante_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    pais_id = _row_get(row, "pais", 0)
    region_actual = _row_get(row, "region_id", 1)
    region_id = resolver_region_id_para_guardar(cur, pais_id, region_actual)
    cur.execute(
        """
        UPDATE aspirantes_perfil
        SET region_id = %s
        WHERE aspirante_id = %s
        """,
        (region_id, aspirante_id),
    )
    return region_id


def obtener_region_id_aspirante(cur, aspirante_id: Any) -> Optional[int]:
    aid = _coerce_int(aspirante_id)
    if aid is None:
        return None
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'aspirantes_perfil'
          AND column_name = 'region_id'
        LIMIT 1
        """
    )
    if not cur.fetchone():
        return None
    cur.execute(
        """
        SELECT region_id
        FROM aspirantes_perfil
        WHERE aspirante_id = %s
        LIMIT 1
        """,
        (aid,),
    )
    row = cur.fetchone()
    return _coerce_int(_row_get(row, "region_id", 0))


def sincronizar_region_creador(
    cur,
    creador_id: int,
    *,
    pais_valor_id: Any = None,
    region_id_usuario: Any = None,
    aspirante_id: Any = None,
) -> Optional[int]:
    """Actualiza creadores.region_id según país de encuesta, payload o aspirante."""
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'creadores'
          AND column_name = 'region_id'
        LIMIT 1
        """
    )
    if not cur.fetchone():
        return _coerce_int(region_id_usuario)
    region_id = resolver_region_id_para_guardar(
        cur, pais_valor_id, region_id_usuario, catalogo="creador"
    )
    if region_id is None and pais_valor_id in (None, ""):
        region_id = resolver_region_id_para_guardar(
            cur, pais_valor_id, region_id_usuario, catalogo="diagnostico"
        )
    if region_id is None and aspirante_id is not None:
        region_id = obtener_region_id_aspirante(cur, aspirante_id)
    if region_id is None and region_id_usuario not in (None, ""):
        region_id = _coerce_int(region_id_usuario)

    cur.execute(
        """
        UPDATE creadores
        SET region_id = %s, updated_at = now()
        WHERE id = %s
        """,
        (region_id, creador_id),
    )
    return region_id


def sincronizar_region_creador_desde_respuestas(cur, creador_id: int) -> Optional[int]:
    cur.execute(
        """
        SELECT r.valor_id
        FROM creadores_perfil_respuesta r
        INNER JOIN creadores_perfil_variable v ON v.id = r.variable_id
        WHERE r.creador_id = %s AND v.campo_db = 'pais'
        LIMIT 1
        """,
        (creador_id,),
    )
    row = cur.fetchone()
    valor_id = _row_get(row, "valor_id", 0) if row else None
    cur.execute(
        "SELECT region_id, aspirante_id FROM creadores WHERE id = %s LIMIT 1",
        (creador_id,),
    )
    creador = cur.fetchone()
    region_actual = _row_get(creador, "region_id", 0) if creador else None
    aspirante_id = _row_get(creador, "aspirante_id", 1) if creador else None
    return sincronizar_region_creador(
        cur,
        creador_id,
        pais_valor_id=valor_id,
        region_id_usuario=region_actual,
        aspirante_id=aspirante_id,
    )


def buscar_id_pais_por_iso(cur, codigo_iso: str) -> Optional[int]:
    iso = (codigo_iso or "").strip().upper()
    if not iso:
        return None
    labels: Tuple[str, ...] = ISO_PAIS_ALIASES.get(iso) or ()
    principal = ISO_PAIS_LABELS.get(iso)
    candidatos = []
    if principal:
        candidatos.append(principal)
    candidatos.extend(labels)
    for label in candidatos:
        cur.execute(
            """
            SELECT b.id
            FROM diagnostico_variable a
            INNER JOIN diagnostico_variable_valor b ON b.variable_id = a.id
            WHERE a.campo_db = 'pais'
              AND lower(trim(b.label)) = lower(trim(%s))
            LIMIT 1
            """,
            (label,),
        )
        row = cur.fetchone()
        if row:
            return _coerce_int(_row_get(row, "id", 0))
    return None


def enriquecer_items_catalogo_pais(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for item in items:
        copia = dict(item)
        if copia.get("region_codigo") is None and copia.get("label"):
            codigo = clasificar_label_pais(copia.get("label"))
            copia["region_codigo"] = codigo
        out.append(copia)
    return out
