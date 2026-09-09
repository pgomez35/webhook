"""Plantillas WhatsApp de clientes chatbot (admin Talentum).

Sincroniza asociaciones en chatbot.whatsapp_plantillas_agencia
desde el catálogo APPROVED de Meta. No crea plantillas en Graph.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from database_chatbot_captacion import obtener_cuenta_whatsapp_principal
from database_whatsapp_plantillas import (
    PlantillaWabaError,
    actualizar_plantilla_waba,
    crear_plantilla_waba,
    listar_plantillas_waba,
    normalizar_finalidad,
    normalizar_nombre_meta,
    sugerir_nombre_visible,
    sugerir_uso_inicial,
    uso_desde_finalidad,
)
from plantillas_whatsapp_mensajes import listar_plantillas_aprobadas_meta

logger = logging.getLogger("uvicorn.error")


class ErrorAdminPlantillas(Exception):
    def __init__(self, http_status: int, detail: Any):
        super().__init__(str(detail))
        self.http_status = int(http_status)
        self.detail = detail


def _cuenta_o_400(agencia_id: int, cuenta_fn=None) -> Dict[str, Any]:
    fn = cuenta_fn or obtener_cuenta_whatsapp_principal
    cuenta = fn(int(agencia_id))
    if not cuenta:
        raise ErrorAdminPlantillas(400, "WhatsApp no está configurado para esta agencia")
    token = str(cuenta.get("access_token") or "").strip()
    phone_id = str(cuenta.get("phone_number_id") or "").strip()
    waba_id = str(cuenta.get("waba_id") or "").strip()
    if not token or not phone_id:
        raise ErrorAdminPlantillas(
            500, "Credenciales de WhatsApp no configuradas para esta agencia"
        )
    if not waba_id:
        raise ErrorAdminPlantillas(400, "La cuenta WhatsApp no tiene WABA ID")
    return cuenta


def _indice_local(filas: List[dict]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for fila in filas or []:
        clave = normalizar_nombre_meta(fila.get("nombre_meta") or "").lower()
        if clave:
            out[clave] = fila
    return out


def serializar_asociacion_admin(fila: dict, meta: Optional[dict] = None) -> dict:
    nombre = normalizar_nombre_meta(fila.get("nombre_meta") or "")
    uso = uso_desde_finalidad(fila.get("finalidad_interna"))
    visible = str(fila.get("nombre_visible") or "").strip() or None
    item = {
        "id": fila.get("id"),
        "agencia_id": fila.get("agencia_id"),
        "phone_number_id": fila.get("phone_number_id"),
        "codigo": nombre,
        "nombre_meta": nombre,
        "nombre_visible": visible,
        "etiqueta": visible or nombre,
        "uso": uso,
        "finalidad_interna": fila.get("finalidad_interna"),
        "activo": bool(fila.get("activo", True)),
        "disponible_meta": bool(fila.get("disponible_meta", True)),
        "idioma": fila.get("idioma") or "es_CO",
        "parametros": list(fila.get("parametros") or []),
        "categoria_meta": None,
        "status": None,
        "descripcion": "",
        "created_at": fila.get("created_at"),
        "updated_at": fila.get("updated_at"),
    }
    if meta:
        item["idioma"] = meta.get("idioma") or item["idioma"]
        item["parametros"] = list(meta.get("parametros") or item["parametros"])
        item["categoria_meta"] = meta.get("categoria_meta")
        item["status"] = meta.get("status")
        item["descripcion"] = meta.get("descripcion") or ""
    return item


def listar_plantillas_admin_agencia(
    agencia_id: int,
    *,
    cuenta_fn=None,
    listar_meta_fn=None,
    listar_local_fn=None,
) -> Dict[str, Any]:
    cuenta = _cuenta_o_400(int(agencia_id), cuenta_fn=cuenta_fn)
    phone_id = str(cuenta["phone_number_id"])
    waba_id = str(cuenta["waba_id"])
    listar_local = listar_local_fn or listar_plantillas_waba
    filas = listar_local(int(agencia_id), phone_id, solo_activas=False)
    meta_fn = listar_meta_fn or listar_plantillas_aprobadas_meta
    try:
        meta_items = meta_fn(
            waba_id,
            str(cuenta.get("access_token") or ""),
            phone_number_id=phone_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ADMIN-PLANTILLA] Meta listar falló agencia_id=%s: %s", agencia_id, exc)
        meta_items = []
    meta_by = {
        normalizar_nombre_meta(m.get("codigo") or m.get("nombre_meta") or "").lower(): m
        for m in (meta_items or [])
        if normalizar_nombre_meta(m.get("codigo") or m.get("nombre_meta") or "")
    }
    plantillas = [serializar_asociacion_admin(f, meta_by.get(normalizar_nombre_meta(f.get("nombre_meta") or "").lower())) for f in filas]
    return {
        "whatsapp": {
            "phone_number": cuenta.get("phone_number"),
            "phone_number_id": phone_id,
            "waba_id": waba_id,
            "status": cuenta.get("status"),
            "business_name": cuenta.get("business_name"),
        },
        "plantillas": plantillas,
        "total": len(plantillas),
        "meta_aprobadas": len(meta_items or []),
    }


def sincronizar_plantillas_agencia(
    agencia_id: int,
    *,
    cuenta_fn=None,
    listar_meta_fn=None,
    listar_local_fn=None,
    crear_fn=None,
    actualizar_fn=None,
) -> Dict[str, Any]:
    """Importa asociaciones desde Meta APPROVED sin habilitarlas.

    Una plantilla recién descubierta nace con activo=False. El resync no
    pisa activo, uso ni nombre_visible de filas ya asociadas.
    """
    cuenta = _cuenta_o_400(int(agencia_id), cuenta_fn=cuenta_fn)
    phone_id = str(cuenta["phone_number_id"])
    waba_id = str(cuenta["waba_id"])
    meta_fn = listar_meta_fn or listar_plantillas_aprobadas_meta
    meta_items = meta_fn(
        waba_id,
        str(cuenta.get("access_token") or ""),
        phone_number_id=phone_id,
    )
    listar_local = listar_local_fn or listar_plantillas_waba
    existentes = listar_local(int(agencia_id), phone_id, solo_activas=False)
    por_nombre = _indice_local(existentes)
    crear = crear_fn or crear_plantilla_waba
    actualizar = actualizar_fn or actualizar_plantilla_waba
    vistos = set()
    creadas = 0
    actualizadas = 0

    for meta in meta_items or []:
        nombre = normalizar_nombre_meta(meta.get("codigo") or meta.get("nombre_meta") or "")
        if not nombre:
            continue
        clave = nombre.lower()
        vistos.add(clave)
        idioma = str(meta.get("idioma") or "es_CO").strip() or "es_CO"
        params = list(meta.get("parametros") or [])
        actual = por_nombre.get(clave)
        if actual:
            actualizar(
                agencia_id=int(agencia_id),
                phone_number_id=phone_id,
                plantilla_id=int(actual["id"]),
                idioma=idioma,
                parametros=params,
                disponible_meta=True,
            )
            actualizadas += 1
        else:
            uso = sugerir_uso_inicial(nombre)
            crear(
                agencia_id=int(agencia_id),
                phone_number_id=phone_id,
                nombre_meta=nombre,
                finalidad_interna=normalizar_finalidad(uso),
                idioma=idioma,
                parametros=params,
                activo=False,
                nombre_visible=sugerir_nombre_visible(nombre),
                disponible_meta=True,
            )
            creadas += 1

    ausentes = 0
    for clave, actual in por_nombre.items():
        if clave in vistos:
            continue
        if actual.get("disponible_meta") is False:
            continue
        actualizar(
            agencia_id=int(agencia_id),
            phone_number_id=phone_id,
            plantilla_id=int(actual["id"]),
            disponible_meta=False,
        )
        ausentes += 1

    logger.info(
        "[ADMIN-PLANTILLA] sync agencia_id=%s waba_id=%s creadas=%s actualizadas=%s ausentes=%s",
        agencia_id,
        waba_id,
        creadas,
        actualizadas,
        ausentes,
    )
    listado = listar_plantillas_admin_agencia(
        int(agencia_id),
        cuenta_fn=lambda *_a, **_k: cuenta,
        listar_meta_fn=lambda *_a, **_k: meta_items,
        listar_local_fn=listar_local,
    )
    listado["sincronizacion"] = {
        "creadas": creadas,
        "actualizadas": actualizadas,
        "marcadas_no_disponibles": ausentes,
    }
    return listado


def actualizar_asociacion_admin(
    agencia_id: int,
    plantilla_id: int,
    *,
    uso: Optional[str] = None,
    activo: Optional[bool] = None,
    nombre_visible: Optional[str] = None,
    cuenta_fn=None,
    actualizar_fn=None,
    obtener_fn: Optional[Callable[..., Optional[dict]]] = None,
) -> dict:
    cuenta = _cuenta_o_400(int(agencia_id), cuenta_fn=cuenta_fn)
    phone_id = str(cuenta["phone_number_id"])
    finalidad = None
    if uso is not None:
        try:
            finalidad = normalizar_finalidad(uso)
        except PlantillaWabaError as exc:
            raise ErrorAdminPlantillas(400, str(exc)) from exc
    actualizar = actualizar_fn or actualizar_plantilla_waba
    fila = actualizar(
        agencia_id=int(agencia_id),
        phone_number_id=phone_id,
        plantilla_id=int(plantilla_id),
        finalidad_interna=finalidad,
        activo=activo,
        nombre_visible=nombre_visible,
    )
    if not fila:
        raise ErrorAdminPlantillas(404, "Plantilla no encontrada")
    return serializar_asociacion_admin(fila)
