"""
Utilidades puras para normalizar la encuesta inicial del portal (sin BD).
"""
from __future__ import annotations

from typing import Any, Dict, List, Set

ENCUESTA_INICIAL_ID = 1

PORTAL_ENCUESTA_CAMPOS_PERMITIDOS: Set[str] = {
    "nombre",
    "edad",
    "genero",
    "actividad_actual",
    "experiencia_tiktok_live",
    "intencion_trabajo",
    "tiempo_disponible",
    "frecuencia_lives",
}


def _map_tipo_formulario(tipo: str | None) -> str:
    t = str(tipo or "boton").lower()
    if t == "boton_texto":
        return "boton_texto"
    if t in {"text", "texto"}:
        return "text"
    if t == "file":
        return "file"
    return "boton"


def normalizar_encuesta_portal(api_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Equivalente a normalizeEncuestaPreguntas() del frontend React.
    """
    if not api_data.get("success") or not isinstance(api_data.get("preguntas"), list):
        return []

    encuesta_id = api_data.get("encuesta_id") or ENCUESTA_INICIAL_ID
    listado: List[Dict[str, Any]] = []

    for p in api_data["preguntas"]:
        campo = str(p.get("campo") or p.get("campo_db") or "").strip()
        tipo = _map_tipo_formulario(p.get("tipo"))
        opciones_raw = p.get("opciones") or []
        opciones = sorted(
            [
                {
                    "id": o["id"],
                    "label": o.get("label") or "",
                    "orden": o.get("orden"),
                }
                for o in opciones_raw
                if o and o.get("id") is not None
            ],
            key=lambda o: (o.get("orden") is None, o.get("orden") or 0, o.get("id") or 0),
        )

        orden_raw = p.get("orden") if p.get("orden") is not None else p.get("pregunta_orden")
        try:
            orden = int(orden_raw) if orden_raw is not None and str(orden_raw).strip() != "" else 999
        except (TypeError, ValueError):
            orden = 999

        listado.append(
            {
                "id": p.get("id"),
                "encuesta_id": p.get("encuesta_id") or encuesta_id,
                "orden": orden,
                "campo_db": campo,
                "tipo_form": tipo,
                "texto": p.get("texto") if isinstance(p.get("texto"), str) else "",
                "opciones": opciones,
            }
        )

    filtradas = [
        q
        for q in listado
        if q["campo_db"] in PORTAL_ENCUESTA_CAMPOS_PERMITIDOS
        and (
            q["tipo_form"] in {"text", "boton_texto"}
            or len(q["opciones"]) > 0
        )
    ]

    filtradas.sort(key=lambda q: (q["orden"], q["id"] or 0))
    return filtradas
