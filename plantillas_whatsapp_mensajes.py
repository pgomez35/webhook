"""Catálogo legacy + adaptador de plantillas Meta para Mensajes WhatsApp.

El identificador estable (`codigo`) es el nombre exacto de la plantilla en Meta.

Las plantillas por WABA viven en ``chatbot.whatsapp_plantillas_agencia``.
El catálogo Python solo conserva plantillas legacy usadas por otros flujos.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

from chatbot_captacion_logic import normalizar_telefono_chatbot

ParametroPlantilla = Literal["nombre", "agencia"]
FinalidadInterna = Literal["saludo", "reconexion", "recordatorio", "otro"]
CategoriaMeta = Literal["marketing", "utility", "authentication"]
AlcancePlantilla = Literal["global", "waba", "legacy"]

FALLBACK_NOMBRE = "Candidato"
FALLBACK_AGENCIA = "Nuestro equipo"

logger = logging.getLogger("uvicorn.error")


class PlantillaMensajesDesconocida(ValueError):
    """El codigo no está en el catálogo o no es enviable desde Mensajes."""


class ErrorGraphPlantillas(Exception):
    """Graph no respondió de forma válida al listar plantillas."""


@dataclass(frozen=True)
class PlantillaMensajes:
    codigo: str
    nombre_meta: str
    idioma: str
    parametros: Tuple[str, ...]
    body_vars_count: int
    etiqueta: str
    descripcion: str = ""
    visible_en_mensajes: bool = True
    finalidad_interna: Optional[FinalidadInterna] = None
    categoria_meta: Optional[CategoriaMeta] = None
    alcance: AlcancePlantilla = "global"
    # None / vacío = no listar en GET (plantilla waba aún no mapeada).
    phone_number_ids: Optional[Tuple[str, ...]] = None


CATALOGO_PLANTILLAS_MENSAJES: Dict[str, PlantillaMensajes] = {
    "primer_contacto_usuarios": PlantillaMensajes(
        codigo="primer_contacto_usuarios",
        nombre_meta="primer_contacto_usuarios",
        idioma="es_CO",
        parametros=("nombre", "agencia"),
        body_vars_count=2,
        etiqueta="Primer contacto",
        descripcion=(
            "Hola {{1}}, te escribimos de {{2}} para continuar con una gestión "
            "relacionada con tu proceso en la agencia. Pulsa “Continuar” para seguir."
        ),
    ),
    "reconexion_general_corta": PlantillaMensajes(
        codigo="reconexion_general_corta",
        nombre_meta="reconexion_general_corta",
        idioma="es_CO",
        parametros=("nombre", "agencia"),
        body_vars_count=2,
        etiqueta="Reconexión (ventana 24h)",
        descripcion="Plantilla corta para reabrir la conversación fuera de la ventana de 24h.",
    ),
    "solicitar_informacion": PlantillaMensajes(
        codigo="solicitar_informacion",
        nombre_meta="solicitar_informacion",
        idioma="es_CO",
        parametros=("nombre",),
        body_vars_count=1,
        etiqueta="Solicitar información de perfil",
        descripcion="Solicita al contacto completar o actualizar su información de perfil.",
    ),
}

ORDEN_PLANTILLAS_MENSAJES: Tuple[str, ...] = (
    "primer_contacto_usuarios",
    "reconexion_general_corta",
    "solicitar_informacion",
)


def resolver_plantilla_mensajes(codigo: str) -> PlantillaMensajes:
    key = (codigo or "").strip()
    plantilla = CATALOGO_PLANTILLAS_MENSAJES.get(key)
    if not plantilla or not plantilla.visible_en_mensajes:
        raise PlantillaMensajesDesconocida(key)
    return plantilla


def construir_parametros_plantilla(
    plantilla: PlantillaMensajes,
    *,
    nombre: str = "",
    agencia: str = "",
) -> List[str]:
    """Arma el BODY según ``plantilla.parametros``. ``agencia`` solo si la plantilla lo pide."""
    valores = {
        "nombre": (nombre or "").strip() or FALLBACK_NOMBRE,
        "agencia": (agencia or "").strip() or FALLBACK_AGENCIA,
    }
    return [valores.get(campo, "") for campo in plantilla.parametros]


def plantilla_desde_config_waba(row: Dict[str, Any]) -> PlantillaMensajes:
    """Adapta un registro persistido al contrato del sender existente."""
    nombre = str(row.get("nombre_meta") or "").strip()
    params = tuple(str(p).strip().lower() for p in (row.get("parametros") or []) if str(p).strip())
    finalidad = str(row.get("finalidad_interna") or "").strip().lower() or None
    if finalidad not in ("saludo", "reconexion", "recordatorio", "otro"):
        finalidad = None
    return PlantillaMensajes(
        codigo=nombre,
        nombre_meta=nombre,
        idioma=str(row.get("idioma") or "es_CO").strip() or "es_CO",
        parametros=params,
        body_vars_count=len(params),
        etiqueta=nombre,
        descripcion="",
        visible_en_mensajes=bool(row.get("activo", True)),
        finalidad_interna=finalidad,  # type: ignore[arg-type]
        alcance="waba",
    )


def serializar_plantilla_config_waba(row: Dict[str, Any]) -> dict:
    nombre = str(row.get("nombre_meta") or "").strip()
    params = list(row.get("parametros") or [])
    return {
        "id": row.get("id"),
        "codigo": nombre,
        "nombre_meta": nombre,
        "idioma": row.get("idioma") or "es_CO",
        "etiqueta": nombre,
        "descripcion": "",
        "parametros": params,
        "finalidad_interna": row.get("finalidad_interna"),
        "activo": bool(row.get("activo", True)),
        "alcance": "waba",
        "fuente": "waba",
        "agencia_id": row.get("agencia_id"),
        "phone_number_id": row.get("phone_number_id"),
        "created_at": row.get("created_at").isoformat()
        if hasattr(row.get("created_at"), "isoformat")
        else row.get("created_at"),
        "updated_at": row.get("updated_at").isoformat()
        if hasattr(row.get("updated_at"), "isoformat")
        else row.get("updated_at"),
    }


_VARS_BODY_META = re.compile(r"\{\{(\d+)\}\}")
ESTADOS_META_ENVIABLES = frozenset({"APPROVED", "approved"})


def _parametros_desde_componentes_meta(components: Any) -> Tuple[List[str], str]:
    body = {}
    for comp in components or []:
        if str((comp or {}).get("type") or "").upper() == "BODY":
            body = comp or {}
            break
    texto = str(body.get("text") or "")
    nums = [int(n) for n in _VARS_BODY_META.findall(texto)]
    nvars = max(nums) if nums else 0
    if nvars <= 0:
        return [], texto
    if nvars == 1:
        return ["nombre"], texto
    return ["nombre", "agencia"], texto


def serializar_plantilla_meta(tpl: Dict[str, Any], *, phone_number_id: Optional[str] = None) -> dict:
    nombre = str(tpl.get("name") or "").strip()
    parametros, body = _parametros_desde_componentes_meta(tpl.get("components"))
    categoria = str(tpl.get("category") or "").strip().lower() or None
    return {
        "codigo": nombre,
        "nombre_meta": nombre,
        "idioma": str(tpl.get("language") or "es_CO").strip() or "es_CO",
        "etiqueta": nombre,
        "descripcion": body,
        "parametros": parametros,
        "categoria_meta": categoria,
        "status": tpl.get("status"),
        "alcance": "waba",
        "fuente": "waba",
        "phone_number_id": phone_number_id,
        "activo": True,
    }


def listar_plantillas_aprobadas_meta(
    waba_id: str,
    token: str,
    *,
    phone_number_id: Optional[str] = None,
    request_fn: Optional[Callable[..., Any]] = None,
    requerir_exito: bool = False,
) -> List[dict]:
    """Plantillas APPROVED de la WABA en Graph API. No expone el token."""
    wid = str(waba_id or "").strip()
    tok = str(token or "").strip()
    if not wid or not tok:
        if requerir_exito:
            raise ErrorGraphPlantillas("Faltan WABA o token para consultar Meta")
        return []

    from enviar_msg_wp import _graph_api_version

    version = _graph_api_version()
    url = f"https://graph.facebook.com/{version}/{wid}/message_templates"
    params = {
        "fields": "name,status,language,category,components",
        "limit": 100,
    }
    headers = {"Authorization": f"Bearer {tok}"}
    get = request_fn
    if get is None:
        import requests

        def get(u, headers=None, params=None, timeout=30):
            resp = requests.get(u, headers=headers, params=params, timeout=timeout)
            try:
                payload = resp.json()
            except ValueError:
                payload = {}
            return resp.status_code, payload

    visibles: List[dict] = []
    vistos = set()
    siguiente = url
    siguientes_params = params
    paginas_ok = 0
    hubo_error = False
    for _ in range(10):
        if not siguiente:
            break
        try:
            status_code, payload = get(
                siguiente, headers=headers, params=siguientes_params, timeout=30
            )
        except Exception as exc:  # noqa: BLE001
            hubo_error = True
            logger.warning("[PLANTILLA_META] no se pudo listar WABA %s: %s", wid, exc)
            break
        if status_code != 200 or not isinstance(payload, dict):
            hubo_error = True
            err = payload.get("error") if isinstance(payload, dict) else None
            logger.warning(
                "[PLANTILLA_META] Graph status=%s waba_id=%s error=%s",
                status_code,
                wid,
                (err or {}).get("message") if isinstance(err, dict) else err,
            )
            break
        paginas_ok += 1
        for tpl in payload.get("data") or []:
            estado = str((tpl or {}).get("status") or "").strip()
            if estado not in ESTADOS_META_ENVIABLES:
                continue
            item = serializar_plantilla_meta(tpl, phone_number_id=phone_number_id)
            clave = str(item.get("codigo") or "").strip().lower()
            if not clave or clave in vistos:
                continue
            vistos.add(clave)
            visibles.append(item)
        paging = payload.get("paging") or {}
        siguiente = paging.get("next")
        siguientes_params = None
    if requerir_exito and (hubo_error or paginas_ok == 0):
        raise ErrorGraphPlantillas("No se pudieron consultar las plantillas en Meta")
    return visibles


def listar_plantillas_para_envio(
    phone_number_id: Optional[str] = None,
    *,
    agencia_id: Optional[int] = None,
    listar_waba_fn=None,
) -> List[dict]:
    """Plantillas activas de la WABA actual + catálogo Python legacy (sin cruzar WABAs)."""
    visibles: List[dict] = []
    vistos = set()
    pid = str(phone_number_id or "").strip()
    if pid and agencia_id is not None:
        if listar_waba_fn is None:
            from database_whatsapp_plantillas import listar_plantillas_waba

            listar_waba_fn = listar_plantillas_waba
        try:
            filas = listar_waba_fn(int(agencia_id), pid, solo_activas=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PLANTILLA_SAS] no se pudieron listar plantillas WABA: %s", exc)
            filas = []
        for fila in filas or []:
            item = serializar_plantilla_config_waba(fila)
            clave = str(item.get("codigo") or "").strip().lower()
            if not clave or clave in vistos:
                continue
            vistos.add(clave)
            visibles.append(item)
    for legacy in listar_plantillas_mensajes(phone_number_id=pid):
        clave = str(legacy.get("codigo") or "").strip().lower()
        if not clave or clave in vistos:
            continue
        vistos.add(clave)
        item = dict(legacy)
        item.setdefault("fuente", "legacy")
        visibles.append(item)
    return visibles


def serializar_plantilla_mensajes(plantilla: PlantillaMensajes) -> dict:
    return {
        "codigo": plantilla.codigo,
        "nombre_meta": plantilla.nombre_meta,
        "idioma": plantilla.idioma,
        "etiqueta": plantilla.etiqueta,
        "descripcion": plantilla.descripcion,
        "parametros": list(plantilla.parametros),
        "finalidad_interna": plantilla.finalidad_interna,
        "categoria_meta": plantilla.categoria_meta,
        "alcance": plantilla.alcance,
        "fuente": "legacy" if plantilla.alcance == "global" else plantilla.alcance,
    }


def _plantilla_listable_en_waba(
    plantilla: PlantillaMensajes,
    phone_number_id: Optional[str],
) -> bool:
    if plantilla.alcance == "global":
        return True
    permitidas = plantilla.phone_number_ids or ()
    if not permitidas:
        return False
    pid = str(phone_number_id or "").strip()
    return bool(pid) and pid in permitidas


def listar_plantillas_mensajes(
    phone_number_id: Optional[str] = None,
) -> List[dict]:
    """Legacy globales + plantillas waba cuyo phone_number_id está mapeado."""
    visibles: List[dict] = []
    for codigo in ORDEN_PLANTILLAS_MENSAJES:
        plantilla = CATALOGO_PLANTILLAS_MENSAJES.get(codigo)
        if not plantilla or not plantilla.visible_en_mensajes:
            continue
        if not _plantilla_listable_en_waba(plantilla, phone_number_id):
            continue
        visibles.append(serializar_plantilla_mensajes(plantilla))
    return visibles


def metadata_envio_plantilla_panel(plantilla: PlantillaMensajes) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "origen": "panel_sas",
        "tipo_interno": "plantilla",
        "codigo": plantilla.codigo,
    }
    if plantilla.finalidad_interna:
        meta["finalidad_interna"] = plantilla.finalidad_interna
    if plantilla.categoria_meta:
        meta["categoria_meta"] = plantilla.categoria_meta
    return meta


def extraer_outgoing_wamid(respuesta_api: Any) -> Optional[str]:
    from chatbot_envio_whatsapp import extraer_mensaje_externo_id

    return extraer_mensaje_externo_id(respuesta_api)


def enviar_plantilla_catalogo(
    *,
    codigo: str,
    telefono: str,
    nombre: str,
    agencia: str = "",
    token: str,
    phone_number_id: str,
    enviar_fn: Optional[Callable[..., Tuple[int, dict]]] = None,
    plantilla: Optional[PlantillaMensajes] = None,
) -> Tuple[int, dict, PlantillaMensajes, List[str]]:
    """Envía por el sender Meta existente. ``plantilla`` evita el catálogo Python."""
    from enviar_msg_wp import enviar_plantilla_generica_parametros

    if plantilla is None:
        plantilla = resolver_plantilla_mensajes(codigo)
    parametros = construir_parametros_plantilla(
        plantilla,
        nombre=nombre,
        agencia=agencia,
    )
    fn = enviar_fn or enviar_plantilla_generica_parametros
    status_code, respuesta = fn(
        token=token,
        phone_number_id=phone_number_id,
        numero_destino=telefono,
        nombre_plantilla=plantilla.nombre_meta,
        codigo_idioma=plantilla.idioma,
        parametros=parametros,
        body_vars_count=plantilla.body_vars_count,
    )
    return status_code, respuesta, plantilla, parametros


def resolver_plantilla_para_envio(
    codigo: str,
    *,
    phone_number_id: str,
    agencia_id: Optional[int] = None,
    obtener_waba_fn=None,
    token: Optional[str] = None,
    waba_id: Optional[str] = None,
    listar_meta_fn=None,
) -> PlantillaMensajes:
    """WABA configurada, luego Meta APPROVED, luego catálogo Python legacy."""
    nombre = (codigo or "").strip()
    pid = str(phone_number_id or "").strip()
    if agencia_id is not None and pid and nombre:
        if obtener_waba_fn is None:
            from database_whatsapp_plantillas import obtener_plantilla_waba_por_nombre

            obtener_waba_fn = obtener_plantilla_waba_por_nombre
        try:
            fila = obtener_waba_fn(
                int(agencia_id), pid, nombre, solo_activa=True
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PLANTILLA_SAS] lookup WABA falló: %s", exc)
            fila = None
        if fila:
            return plantilla_desde_config_waba(fila)
    clave = nombre.lower()
    if token and waba_id and clave:
        fn = listar_meta_fn or listar_plantillas_aprobadas_meta
        try:
            meta = fn(str(waba_id), str(token), phone_number_id=pid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PLANTILLA_META] lookup falló waba_id=%s: %s", waba_id, exc)
            meta = []
        for item in meta or []:
            if str(item.get("codigo") or "").strip().lower() == clave:
                return plantilla_desde_config_waba({
                    "nombre_meta": item.get("nombre_meta") or item.get("codigo"),
                    "idioma": item.get("idioma") or "es_CO",
                    "parametros": item.get("parametros") or [],
                    "finalidad_interna": item.get("finalidad_interna") or "otro",
                    "activo": True,
                })
    return resolver_plantilla_mensajes(nombre)


def resolver_agencia_id_para_waba(phone_number_id: str) -> Optional[int]:
    """agencia_id de chatbot.agencias a partir del phone_number_id del tenant.

    No crea agencia ni aspirante. Si no hay mapeo, el dual-write chatbot se omite.
    """
    pid = str(phone_number_id or "").strip()
    if not pid:
        return None
    try:
        from database_chatbot_captacion import (
            obtener_agencia_por_codigo,
            obtener_cuenta_conectada_por_phone_id,
            obtener_relacion_agencia_canal,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PLANTILLA_SAS] no se pudo importar captacion: %s", exc)
        return None

    cuenta = obtener_cuenta_conectada_por_phone_id(pid)
    if not cuenta:
        try:
            from DataBase import obtener_cuenta_por_phone_id

            cuenta = obtener_cuenta_por_phone_id(pid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PLANTILLA_SAS] cuenta WABA no resuelta: %s", exc)
            cuenta = None

    if cuenta and cuenta.get("id") is not None:
        try:
            rel = obtener_relacion_agencia_canal(int(cuenta["id"]))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PLANTILLA_SAS] relación agencia-canal falló: %s", exc)
            rel = None
        if rel and rel.get("agencia_id") is not None:
            return int(rel["agencia_id"])
        sub = str(cuenta.get("subdominio") or "").strip()
        if sub:
            ag = obtener_agencia_por_codigo(sub)
            if ag and ag.get("id") is not None:
                return int(ag["id"])

    try:
        from tenant import current_subdominio

        sub_ctx = str(current_subdominio.get() or "").strip()
    except LookupError:
        sub_ctx = ""
    if sub_ctx:
        ag = obtener_agencia_por_codigo(sub_ctx)
        if ag and ag.get("id") is not None:
            return int(ag["id"])
    return None


def persistir_plantilla_en_sas(
    *,
    plantilla: PlantillaMensajes,
    telefono_normalizado: str,
    message_id_meta: Optional[str],
    nombre_contacto: Optional[str] = None,
    guardar_sas_fn: Optional[Callable[..., Any]] = None,
    guardar_nombre_fn: Optional[Callable[..., Any]] = None,
) -> None:
    """Marcador técnico en la bandeja SAS. No inventa el BODY de marketing."""
    tel = normalizar_telefono_chatbot(telefono_normalizado)
    usando_sas_real = guardar_sas_fn is None
    if guardar_sas_fn is None:
        from DataBase import guardar_mensaje_nuevo

        guardar_sas_fn = guardar_mensaje_nuevo
    guardar_sas_fn(
        telefono=tel,
        contenido=f"[Plantilla enviada: {plantilla.nombre_meta}]",
        direccion="enviado",
        tipo="text",
        message_id_meta=str(message_id_meta or "").strip() or None,
        estado="sent",
    )
    nom = (nombre_contacto or "").strip()
    if not nom:
        return
    if guardar_nombre_fn is None and usando_sas_real:
        from DataBase import guardar_nombre_whatsapp_perfil

        guardar_nombre_fn = guardar_nombre_whatsapp_perfil
    if guardar_nombre_fn:
        guardar_nombre_fn(tel, nom)


def persistir_plantilla_en_conversacion_canonica(
    *,
    plantilla: PlantillaMensajes,
    telefono_normalizado: str,
    phone_number_id: str,
    agencia_id: int,
    message_id_meta: Optional[str],
    nombre_contacto: Optional[str] = None,
    usuario_plataforma: Optional[str] = None,
    buscar_o_crear_fn: Optional[Callable[..., Any]] = None,
    insertar_mensaje_fn: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Resuelve conversación canónica e inserta el saliente. No crea aspirante."""
    tel = normalizar_telefono_chatbot(telefono_normalizado)
    pid = str(phone_number_id or "").strip()
    wamid = str(message_id_meta or "").strip() or None
    if not tel or not pid:
        raise ValueError("telefono y phone_number_id son obligatorios para dual-write")

    if buscar_o_crear_fn is None:
        from database_chatbot_conversacional import buscar_o_crear_conversacion

        buscar_o_crear_fn = buscar_o_crear_conversacion
    if insertar_mensaje_fn is None:
        from database_chatbot_conversacional import insertar_mensaje

        insertar_mensaje_fn = insertar_mensaje

    conv_result = buscar_o_crear_fn(
        int(agencia_id),
        canal="whatsapp",
        usuario_externo_id=tel,
        cuenta_externa_id=pid,
        telefono=tel,
        nombre_contacto=(nombre_contacto or "").strip() or None,
        usuario_plataforma=(usuario_plataforma or "").strip() or None,
    )
    if isinstance(conv_result, tuple):
        conversacion, creada = conv_result[0], bool(conv_result[1])
    else:
        conversacion, creada = conv_result, False
    conversacion_id = int((conversacion or {}).get("id"))

    metadata = metadata_envio_plantilla_panel(plantilla)
    insert_result = insertar_mensaje_fn(
        int(agencia_id),
        conversacion_id,
        canal="whatsapp",
        direccion="saliente",
        remitente_tipo="humano",
        tipo_mensaje="texto",
        texto=None,
        estado_envio="enviado",
        mensaje_externo_id=wamid,
        metadata=metadata,
    )
    if isinstance(insert_result, tuple):
        mensaje_chatbot, mensaje_creado = insert_result[0], bool(insert_result[1])
    else:
        mensaje_chatbot, mensaje_creado = insert_result, True

    return {
        "telefono": tel,
        "phone_number_id": pid,
        "agencia_id": int(agencia_id),
        "conversacion_id": conversacion_id,
        "conversacion_creada": creada,
        "mensaje_chatbot_creado": mensaje_creado,
        "mensaje_externo_id": wamid,
        "metadata": metadata,
        "mensaje_chatbot": mensaje_chatbot,
    }


def persistir_plantilla_dual_write(
    *,
    plantilla: PlantillaMensajes,
    telefono_normalizado: str,
    phone_number_id: str,
    agencia_id: int,
    message_id_meta: Optional[str],
    nombre_contacto: Optional[str] = None,
    usuario_plataforma: Optional[str] = None,
    guardar_sas_fn: Optional[Callable[..., Any]] = None,
    buscar_o_crear_fn: Optional[Callable[..., Any]] = None,
    insertar_mensaje_fn: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """SAS + conversación canónica. No crea chatbot_aspirantes."""
    persistir_plantilla_en_sas(
        plantilla=plantilla,
        telefono_normalizado=telefono_normalizado,
        message_id_meta=message_id_meta,
        nombre_contacto=nombre_contacto,
        guardar_sas_fn=guardar_sas_fn,
    )
    return persistir_plantilla_en_conversacion_canonica(
        plantilla=plantilla,
        telefono_normalizado=telefono_normalizado,
        phone_number_id=phone_number_id,
        agencia_id=agencia_id,
        message_id_meta=message_id_meta,
        nombre_contacto=nombre_contacto,
        usuario_plataforma=usuario_plataforma,
        buscar_o_crear_fn=buscar_o_crear_fn,
        insertar_mensaje_fn=insertar_mensaje_fn,
    )


def _mensaje_error_meta(respuesta_api: Any) -> str:
    if isinstance(respuesta_api, dict):
        err = respuesta_api.get("error")
        if isinstance(err, dict):
            msg = str(err.get("message") or err.get("error_user_msg") or "").strip()
            code = err.get("code")
            if msg and code is not None:
                return f"{msg} (code {code})"
            if msg:
                return msg
        if isinstance(err, str) and err.strip():
            return err.strip()
    return "Meta rechazó el envío de la plantilla"


def ejecutar_envio_plantilla(
    *,
    telefono: str,
    codigo: str,
    nombre: str = "",
    agencia_nombre: str = "",
    token: str,
    phone_number_id: str,
    agencia_id: Optional[int],
    waba_id: Optional[str] = None,
    usuario_plataforma: Optional[str] = None,
    persistir_sas: bool = True,
    plantilla: Optional[PlantillaMensajes] = None,
    enviar_fn: Optional[Callable[..., Tuple[int, dict]]] = None,
    persistir_sas_fn: Optional[Callable[..., Any]] = None,
    persistir_canonica_fn: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Envía una plantilla por la capa Meta existente y persiste el historial.

    No crea aspirante. ``persistir_sas`` escribe en la bandeja Talentum
    (mensajes_whatsapp); el chatbot independiente debe pasarlo en False.
    """
    tel = normalizar_telefono_chatbot(telefono)
    codigo_norm = (codigo or "").strip()
    pid = str(phone_number_id or "").strip()
    if not tel or not codigo_norm:
        return {
            "ok": False,
            "http_status": 400,
            "detail": "Faltan telefono o codigo de plantilla",
        }
    if not token or not pid:
        return {
            "ok": False,
            "http_status": 500,
            "detail": "Credenciales de WhatsApp no configuradas para este tenant",
        }

    try:
        if plantilla is None:
            plantilla = resolver_plantilla_para_envio(
                codigo_norm,
                phone_number_id=pid,
                agencia_id=agencia_id,
                token=token,
                waba_id=waba_id,
            )
    except PlantillaMensajesDesconocida:
        return {
            "ok": False,
            "http_status": 404,
            "detail": f"Plantilla no permitida: {codigo_norm}",
        }

    try:
        status_code, resp, plantilla, parametros = enviar_plantilla_catalogo(
            codigo=codigo_norm,
            telefono=tel,
            nombre=nombre or "",
            agencia=agencia_nombre or "",
            token=token,
            phone_number_id=pid,
            plantilla=plantilla,
            enviar_fn=enviar_fn,
        )
    except PlantillaMensajesDesconocida:
        return {
            "ok": False,
            "http_status": 404,
            "detail": f"Plantilla no permitida: {codigo_norm}",
        }

    if status_code not in (200, 201):
        logger.warning(
            "[PLANTILLA] meta_failed status=%s phone_number_id=%s codigo=%s",
            status_code,
            pid,
            plantilla.codigo,
        )
        return {
            "ok": False,
            "http_status": 502,
            "detail": _mensaje_error_meta(resp),
        }

    message_id_meta = extraer_outgoing_wamid(resp)
    if persistir_sas:
        try:
            fn_sas = persistir_sas_fn or persistir_plantilla_en_sas
            fn_sas(
                plantilla=plantilla,
                telefono_normalizado=tel,
                message_id_meta=message_id_meta,
                nombre_contacto=nombre or "",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("[PLANTILLA] persistencia SAS falló tras Meta OK: %s", exc)

    dual: Optional[Dict[str, Any]] = None
    if agencia_id is None:
        logger.info(
            "[PLANTILLA] dual-write chatbot omitido: sin agencia_id "
            "phone_number_id=%s",
            pid,
        )
    else:
        try:
            fn_canonica = persistir_canonica_fn or persistir_plantilla_en_conversacion_canonica
            dual = fn_canonica(
                plantilla=plantilla,
                telefono_normalizado=tel,
                phone_number_id=pid,
                agencia_id=int(agencia_id),
                message_id_meta=message_id_meta,
                nombre_contacto=nombre or "",
                usuario_plataforma=usuario_plataforma,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("[PLANTILLA] dual-write chatbot falló tras Meta OK: %s", exc)

    return {
        "ok": True,
        "status": "ok",
        "codigo": plantilla.codigo,
        "nombre_meta": plantilla.nombre_meta,
        "codigo_api": status_code,
        "respuesta_api": resp,
        "message_id_meta": message_id_meta,
        "telefono": tel,
        "conversacion_id": (dual or {}).get("conversacion_id"),
        "conversacion_creada": (dual or {}).get("conversacion_creada"),
        "parametros": parametros,
        "dual": dual,
    }
