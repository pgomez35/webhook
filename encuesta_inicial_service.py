"""
Servicio de lectura de encuesta inicial desde BD (multi-tenant).
"""
from __future__ import annotations

from typing import Any, Dict

from DataBase import get_connection_context
from encuesta_portal_utils import ENCUESTA_INICIAL_ID, normalizar_encuesta_portal


def fetch_encuesta_desde_bd(encuesta_id: int) -> Dict[str, Any]:
    """
    Misma consulta que obtener_encuesta() en main_evaluacion_aspirante.py.
    """
    from psycopg2.extras import RealDictCursor

    with get_connection_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT v.id AS pregunta_id,
                       v.texto,
                       v.tipo_form AS tipo,
                       v.campo_db AS campo,
                       v.encuesta_id,
                       v.orden AS pregunta_orden,
                       o.id AS opcion_id,
                       o.label,
                       o.orden AS opcion_orden
                FROM diagnostico_variable v
                LEFT JOIN diagnostico_variable_valor o
                    ON o.variable_id = v.id
                WHERE v.encuesta_id = %s
                  AND v.activa = true
                ORDER BY v.orden, COALESCE(o.orden, o.id);
                """,
                (encuesta_id,),
            )
            rows = cur.fetchall()

    preguntas: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        pid = row["pregunta_id"]
        if pid not in preguntas:
            preguntas[pid] = {
                "id": pid,
                "orden": row["pregunta_orden"],
                "texto": row["texto"],
                "tipo": row["tipo"],
                "campo": row["campo"],
                "encuesta_id": row.get("encuesta_id") or encuesta_id,
                "opciones": [],
            }
        if row["opcion_id"] is not None:
            preguntas[pid]["opciones"].append(
                {
                    "id": row["opcion_id"],
                    "label": row["label"],
                    "orden": row["opcion_orden"],
                }
            )

    lista = sorted(
        preguntas.values(),
        key=lambda p: (p.get("orden") is None, p.get("orden") or 0, p.get("id") or 0),
    )
    return {
        "success": True,
        "encuesta_id": encuesta_id,
        "preguntas": lista,
    }


def obtener_encuesta_inicial_normalizada(encuesta_id: int = ENCUESTA_INICIAL_ID) -> Dict[str, Any]:
    raw = fetch_encuesta_desde_bd(encuesta_id)
    preguntas = normalizar_encuesta_portal(raw)
    return {
        "encuesta_id": encuesta_id,
        "preguntas": preguntas,
    }
