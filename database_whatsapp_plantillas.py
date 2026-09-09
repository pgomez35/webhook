"""CRUD de plantillas WhatsApp configuradas por WABA (schema chatbot)."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from psycopg2 import IntegrityError
from psycopg2.extras import Json, RealDictCursor

from DataBase import get_connection_chatbot_context

logger = logging.getLogger("uvicorn.error")

FINALIDADES = ("saludo", "reconexion", "recordatorio", "otro")
PARAMETROS_CONOCIDOS = ("nombre", "agencia")
USO_A_FINALIDAD = {
    "primer_contacto": "saludo",
    "seguimiento": "recordatorio",
    "retomar": "reconexion",
    "general": "otro",
    "saludo": "saludo",
    "reconexion": "reconexion",
    "recordatorio": "recordatorio",
    "otro": "otro",
}
FINALIDAD_A_USO = {
    "saludo": "primer_contacto",
    "reconexion": "retomar",
    "recordatorio": "seguimiento",
    "otro": "general",
}
SUGERENCIA_USO_POR_CODIGO = {
    "invitacion_creador_live_1": "primer_contacto",
    "invitacion_creador_live_2": "primer_contacto",
    "retomar_proceso_agencia": "retomar",
    "seguimiento_interes_agencia": "seguimiento",
}
NOMBRE_VISIBLE_INICIAL = {
    "invitacion_creador_live_1": "Invitación creador LIVE 1",
    "invitacion_creador_live_2": "Invitación creador LIVE 2",
    "retomar_proceso_agencia": "Retomar proceso",
    "seguimiento_interes_agencia": "Seguimiento de interés",
}


class PlantillaWabaError(ValueError):
    """Datos inválidos o conflicto de unicidad."""


def normalizar_nombre_meta(nombre: str) -> str:
    return str(nombre or "").strip()


def normalizar_parametros(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = [raw]
    if not isinstance(raw, (list, tuple)):
        raise PlantillaWabaError("parametros debe ser una lista")
    out: List[str] = []
    vistos = set()
    for item in raw:
        clave = str(item or "").strip().lower()
        if not clave or clave in vistos:
            continue
        vistos.add(clave)
        out.append(clave)
    return out


def normalizar_finalidad(valor: str) -> str:
    clave = str(valor or "").strip().lower()
    if clave in USO_A_FINALIDAD:
        return USO_A_FINALIDAD[clave]
    if clave not in FINALIDADES:
        raise PlantillaWabaError(
            "finalidad_interna debe ser saludo, reconexion, recordatorio u otro"
        )
    return clave


def uso_desde_finalidad(finalidad: Optional[str]) -> str:
    clave = str(finalidad or "").strip().lower()
    return FINALIDAD_A_USO.get(clave, "general")


def sugerir_uso_inicial(nombre_meta: str) -> str:
    clave = normalizar_nombre_meta(nombre_meta).lower()
    return SUGERENCIA_USO_POR_CODIGO.get(clave, "general")


def sugerir_nombre_visible(nombre_meta: str) -> Optional[str]:
    clave = normalizar_nombre_meta(nombre_meta).lower()
    return NOMBRE_VISIBLE_INICIAL.get(clave)


def _fila(row) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    data = dict(row)
    params = data.get("parametros")
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except (TypeError, ValueError):
            params = []
    data["parametros"] = list(params or [])
    if "disponible_meta" not in data or data.get("disponible_meta") is None:
        data["disponible_meta"] = True
    return data


def listar_plantillas_waba(
    agencia_id: int,
    phone_number_id: str,
    *,
    solo_activas: bool = False,
) -> List[Dict[str, Any]]:
    pid = str(phone_number_id or "").strip()
    if not pid:
        return []
    sql = """
        SELECT id, agencia_id, phone_number_id, nombre_meta, finalidad_interna,
               idioma, parametros, activo, nombre_visible, disponible_meta,
               created_at, updated_at
        FROM chatbot.whatsapp_plantillas_agencia
        WHERE agencia_id = %s
          AND phone_number_id = %s
    """
    params: List[Any] = [int(agencia_id), pid]
    if solo_activas:
        sql += " AND activo = TRUE"
    sql += """
        ORDER BY
            CASE finalidad_interna
                WHEN 'saludo' THEN 1
                WHEN 'reconexion' THEN 2
                WHEN 'recordatorio' THEN 3
                ELSE 4
            END,
            nombre_meta ASC
    """
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [_fila(r) for r in (cur.fetchall() or [])]


def obtener_plantilla_waba_por_nombre(
    agencia_id: int,
    phone_number_id: str,
    nombre_meta: str,
    *,
    solo_activa: bool = True,
) -> Optional[Dict[str, Any]]:
    pid = str(phone_number_id or "").strip()
    nombre = normalizar_nombre_meta(nombre_meta)
    if not pid or not nombre:
        return None
    sql = """
        SELECT id, agencia_id, phone_number_id, nombre_meta, finalidad_interna,
               idioma, parametros, activo, nombre_visible, disponible_meta,
               created_at, updated_at
        FROM chatbot.whatsapp_plantillas_agencia
        WHERE agencia_id = %s
          AND phone_number_id = %s
          AND LOWER(BTRIM(nombre_meta)) = LOWER(BTRIM(%s))
    """
    params: List[Any] = [int(agencia_id), pid, nombre]
    if solo_activa:
        sql += " AND activo = TRUE"
    sql += " LIMIT 1"
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return _fila(cur.fetchone())


def obtener_plantilla_waba_por_id(
    agencia_id: int,
    phone_number_id: str,
    plantilla_id: int,
) -> Optional[Dict[str, Any]]:
    pid = str(phone_number_id or "").strip()
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, agencia_id, phone_number_id, nombre_meta, finalidad_interna,
                       idioma, parametros, activo, nombre_visible, disponible_meta,
                       created_at, updated_at
                FROM chatbot.whatsapp_plantillas_agencia
                WHERE id = %s
                  AND agencia_id = %s
                  AND phone_number_id = %s
                LIMIT 1
                """,
                (int(plantilla_id), int(agencia_id), pid),
            )
            return _fila(cur.fetchone())


def crear_plantilla_waba(
    *,
    agencia_id: int,
    phone_number_id: str,
    nombre_meta: str,
    finalidad_interna: str,
    idioma: str = "es_CO",
    parametros: Any = None,
    activo: bool = True,
    nombre_visible: Optional[str] = None,
    disponible_meta: bool = True,
) -> Dict[str, Any]:
    pid = str(phone_number_id or "").strip()
    nombre = normalizar_nombre_meta(nombre_meta)
    if not pid or not nombre:
        raise PlantillaWabaError("phone_number_id y nombre_meta son obligatorios")
    finalidad = normalizar_finalidad(finalidad_interna)
    idioma_norm = str(idioma or "es_CO").strip() or "es_CO"
    params = normalizar_parametros(parametros)
    visible = (str(nombre_visible).strip() or None) if nombre_visible is not None else None
    try:
        with get_connection_chatbot_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO chatbot.whatsapp_plantillas_agencia (
                        agencia_id, phone_number_id, nombre_meta, finalidad_interna,
                        idioma, parametros, activo, nombre_visible, disponible_meta
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, agencia_id, phone_number_id, nombre_meta,
                              finalidad_interna, idioma, parametros, activo,
                              nombre_visible, disponible_meta,
                              created_at, updated_at
                    """,
                    (
                        int(agencia_id),
                        pid,
                        nombre,
                        finalidad,
                        idioma_norm,
                        Json(params),
                        bool(activo),
                        visible,
                        bool(disponible_meta),
                    ),
                )
                row = _fila(cur.fetchone())
        if not row:
            raise PlantillaWabaError("No se pudo crear la plantilla")
        return row
    except IntegrityError as exc:
        logger.info("[WA_PLANTILLA] conflicto unicidad phone=%s nombre=%s", pid, nombre)
        raise PlantillaWabaError(
            "Ya existe una plantilla con ese nombre Meta en esta WABA"
        ) from exc


def actualizar_plantilla_waba(
    *,
    agencia_id: int,
    phone_number_id: str,
    plantilla_id: int,
    nombre_meta: Optional[str] = None,
    finalidad_interna: Optional[str] = None,
    idioma: Optional[str] = None,
    parametros: Any = None,
    activo: Optional[bool] = None,
    nombre_visible: Optional[str] = None,
    disponible_meta: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    actual = obtener_plantilla_waba_por_id(agencia_id, phone_number_id, plantilla_id)
    if not actual:
        return None
    nombre = (
        normalizar_nombre_meta(nombre_meta)
        if nombre_meta is not None
        else actual["nombre_meta"]
    )
    if not nombre:
        raise PlantillaWabaError("nombre_meta es obligatorio")
    finalidad = (
        normalizar_finalidad(finalidad_interna)
        if finalidad_interna is not None
        else actual["finalidad_interna"]
    )
    idioma_norm = (
        str(idioma).strip() or "es_CO"
        if idioma is not None
        else actual["idioma"]
    )
    params = (
        normalizar_parametros(parametros)
        if parametros is not None
        else list(actual.get("parametros") or [])
    )
    activo_val = bool(activo) if activo is not None else bool(actual.get("activo"))
    if nombre_visible is not None:
        visible = str(nombre_visible).strip() or None
    else:
        visible = actual.get("nombre_visible")
    disp_meta = (
        bool(disponible_meta)
        if disponible_meta is not None
        else bool(actual.get("disponible_meta", True))
    )
    pid = str(phone_number_id or "").strip()
    try:
        with get_connection_chatbot_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE chatbot.whatsapp_plantillas_agencia
                    SET nombre_meta = %s,
                        finalidad_interna = %s,
                        idioma = %s,
                        parametros = %s,
                        activo = %s,
                        nombre_visible = %s,
                        disponible_meta = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                      AND agencia_id = %s
                      AND phone_number_id = %s
                    RETURNING id, agencia_id, phone_number_id, nombre_meta,
                              finalidad_interna, idioma, parametros, activo,
                              nombre_visible, disponible_meta,
                              created_at, updated_at
                    """,
                    (
                        nombre,
                        finalidad,
                        idioma_norm,
                        Json(params),
                        activo_val,
                        visible,
                        disp_meta,
                        int(plantilla_id),
                        int(agencia_id),
                        pid,
                    ),
                )
                return _fila(cur.fetchone())
    except IntegrityError as exc:
        raise PlantillaWabaError(
            "Ya existe una plantilla con ese nombre Meta en esta WABA"
        ) from exc


def eliminar_plantilla_waba(
    agencia_id: int,
    phone_number_id: str,
    plantilla_id: int,
) -> bool:
    pid = str(phone_number_id or "").strip()
    with get_connection_chatbot_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM chatbot.whatsapp_plantillas_agencia
                WHERE id = %s
                  AND agencia_id = %s
                  AND phone_number_id = %s
                """,
                (int(plantilla_id), int(agencia_id), pid),
            )
            return (cur.rowcount or 0) > 0
