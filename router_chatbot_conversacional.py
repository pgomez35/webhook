"""
Router administrativo — Chatbot conversacional (asistente IA).

La agencia se resuelve exclusivamente desde el JWT (scope=chatbot_frontend).
Ningún identificador del path autoriza por sí solo: antes de leer o escribir se
comprueba que la configuración, el flujo, la prueba LIVE o la conversación
pertenezcan a la agencia autenticada; si no, 404.

Las respuestas devuelven las filas tal como las entrega
`database_chatbot_conversacional`, que incluye campos derivados de los JOIN
(nombre de campaña, de flujo, contadores de pendientes, etc.).

El módulo de servicio se importa de forma perezosa: sólo dos endpoints
(enviar mensaje manual y simular) necesitan orquestación con Meta u OpenAI, así
que el resto del panel sigue funcionando aunque el asistente no esté instalado.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

import database_chatbot_captacion as db_captacion
import database_chatbot_conversacional as db
from router_chatbot_auth import obtener_agencia_chatbot_actual
from schemas_chatbot_conversacional import (
    AsistenteConfiguracionUpsert,
    AsistenteInicializarIn,
    BeneficioIn,
    CampaniaIn,
    ConversacionAsignarCampaniaIn,
    ConversacionCerrarIn,
    ConversacionEnviarMensajeIn,
    ConversacionEscalarIn,
    ConversacionTomarIn,
    EvidenciaRequeridaIn,
    EvidenciaRevisionIn,
    FaqConversacionalIn,
    FaqImportarIn,
    FlujoIn,
    FlujoPasoIn,
    FlujoPasoMoverIn,
    PruebaLiveIn,
    RecursoEnlaceIn,
    ReglaEscalamientoIn,
    RequisitoIn,
    SimulacionIn,
    TareaCandidatoUpdate,
)

logger = logging.getLogger("uvicorn.error")

router = APIRouter(
    prefix="/api/chatbot/conversacional",
    tags=["Chatbot Conversacional"],
)

_DIRECCIONES_PASO = {
    "up": "subir",
    "subir": "subir",
    "arriba": "subir",
    "down": "bajar",
    "bajar": "bajar",
    "abajo": "bajar",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _agencia_id(agencia: dict) -> int:
    return int(agencia["id"])


def _servicio():
    """Servicio conversacional (import perezoso: puede no estar desplegado)."""
    try:
        from services.chatbot_conversacional import service
    except Exception as e:  # pragma: no cover - depende del despliegue
        logger.error("[CHATBOT-CONV] servicio conversacional no disponible: %s", e)
        raise HTTPException(
            status_code=503,
            detail="El asistente conversacional no está disponible en este despliegue",
        ) from e
    return service


def _validar_configuracion(agencia: dict, chatbot_configuracion_id: int) -> int:
    cfg = db_captacion.obtener_configuracion_por_id(
        _agencia_id(agencia), int(chatbot_configuracion_id), solo_activa=False
    )
    if not cfg:
        raise HTTPException(status_code=404, detail="Configuración no encontrada")
    return int(chatbot_configuracion_id)


def _configuracion_rigida(agencia: dict, chatbot_configuracion_id: int) -> dict:
    cfg = db_captacion.obtener_configuracion_por_id(
        _agencia_id(agencia), int(chatbot_configuracion_id), solo_activa=False
    )
    if not cfg:
        raise HTTPException(status_code=404, detail="Configuración no encontrada")
    return cfg


def _validar_flujo(agencia: dict, flujo_id: int) -> int:
    if not db.obtener_flujo(_agencia_id(agencia), int(flujo_id)):
        raise HTTPException(status_code=404, detail="Flujo no encontrado")
    return int(flujo_id)


def _validar_prueba_live(agencia: dict, prueba_live_id: int) -> int:
    if not db.obtener_prueba_live(_agencia_id(agencia), int(prueba_live_id)):
        raise HTTPException(status_code=404, detail="Prueba LIVE no encontrada")
    return int(prueba_live_id)


def _validar_conversacion(agencia: dict, conversacion_id: int) -> int:
    if not db.obtener_conversacion(_agencia_id(agencia), int(conversacion_id)):
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    return int(conversacion_id)


def _exigir_en_configuracion(
    agencia: dict,
    obtener: Callable[..., Optional[dict]],
    entidad_id: int,
    chatbot_configuracion_id: int,
    entidad: str,
) -> dict:
    """
    Carga un registro del catálogo y exige que sea de la agencia y del alcance
    de la configuración indicada (los registros globales se aceptan).
    """
    row = obtener(_agencia_id(agencia), int(entidad_id))
    if not row:
        raise HTTPException(status_code=404, detail=f"{entidad} no encontrado")
    propio = row.get("chatbot_configuracion_id")
    if propio is not None and int(propio) != int(chatbot_configuracion_id):
        raise HTTPException(status_code=404, detail=f"{entidad} no encontrado")
    return row


def _exigir_en_padre(
    agencia: dict,
    obtener: Callable[..., Optional[dict]],
    entidad_id: int,
    padre_campo: str,
    padre_id: int,
    entidad: str,
) -> dict:
    row = obtener(_agencia_id(agencia), int(entidad_id))
    if not row or int(row.get(padre_campo) or 0) != int(padre_id):
        raise HTTPException(status_code=404, detail=f"{entidad} no encontrado")
    return row


def _o_404(row: Optional[dict], entidad: str) -> dict:
    if not row:
        raise HTTPException(status_code=404, detail=f"{entidad} no encontrado")
    return row


def _campos(payload: Any) -> Dict[str, Any]:
    """Cuerpo Pydantic → dict con sólo los campos enviados."""
    if payload is None:
        return {}
    return payload.model_dump(mode="json", exclude_unset=True)


def _http_error(e: Exception) -> HTTPException:
    msg = str(e)
    lower = msg.lower()
    if "no existe" in lower or "no pertenece" in lower or "no encontrad" in lower:
        return HTTPException(status_code=404, detail=msg)
    if "ya existe" in lower or "duplicad" in lower:
        return HTTPException(status_code=409, detail=msg)
    return HTTPException(status_code=400, detail=msg)


_ERRORES_DATOS = (db.ErrorDatosConversacional, ValueError)


async def _enviar_por_canal(conversacion: dict, texto: str) -> Dict[str, Any]:
    """Entrega un texto del manager por el mismo canal de la conversación."""
    canal = str(conversacion.get("canal") or "whatsapp").strip().lower()
    destino = conversacion.get("telefono") or conversacion.get("usuario_externo_id")
    if not destino:
        return {"enviado": False, "motivo": "destino_desconocido"}

    if canal == "instagram":
        try:
            from instagram_messaging_client import InstagramMessagingClient

            await InstagramMessagingClient().send_text(str(destino), texto)
            return {"enviado": True}
        except Exception as e:  # noqa: BLE001 - el mensaje igual queda registrado
            logger.error("[CHATBOT-CONV] error enviando por Instagram: %s", e)
            return {"enviado": False, "error": str(e)}

    from DataBase import obtener_cuenta_por_phone_id
    from enviar_msg_wp import enviar_mensaje_texto_simple

    cuenta = obtener_cuenta_por_phone_id(str(conversacion.get("cuenta_externa_id") or ""))
    if not cuenta or not cuenta.get("access_token"):
        return {"enviado": False, "motivo": "credenciales_whatsapp_no_disponibles"}

    try:
        codigo, respuesta = await asyncio.to_thread(
            enviar_mensaje_texto_simple,
            token=cuenta["access_token"],
            numero_id=cuenta.get("phone_number_id"),
            telefono_destino=str(destino),
            texto=texto,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("[CHATBOT-CONV] error enviando por WhatsApp: %s", e)
        return {"enviado": False, "error": str(e)}

    if 200 <= int(codigo or 0) < 300:
        return {"enviado": True}
    return {"enviado": False, "error": str(respuesta)[:500]}


# ---------------------------------------------------------------------------
# Asistente
# ---------------------------------------------------------------------------

@router.get("/configuraciones/{chatbot_configuracion_id}/asistente")
def get_asistente(
    chatbot_configuracion_id: int,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    return _o_404(
        db.obtener_asistente_por_config(_agencia_id(agencia), cfg_id),
        "Asistente",
    )


@router.put("/configuraciones/{chatbot_configuracion_id}/asistente")
def put_asistente(
    chatbot_configuracion_id: int,
    payload: AsistenteConfiguracionUpsert,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    try:
        asistente = db.upsert_asistente(_agencia_id(agencia), cfg_id, _campos(payload))
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    logger.info(
        "[CHATBOT-CONV] asistente guardado agencia_id=%s configuracion_id=%s activo=%s",
        agencia["id"],
        cfg_id,
        asistente.get("activo"),
    )
    return asistente


@router.post("/configuraciones/{chatbot_configuracion_id}/asistente/inicializar")
def inicializar_asistente(
    chatbot_configuracion_id: int,
    payload: Optional[AsistenteInicializarIn] = None,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    """
    Prepara el modo conversacional desde la configuración rígida: asistente
    (inactivo), FAQ importadas, requisitos base y flujo informativo.
    Es idempotente.
    """
    cfg = _configuracion_rigida(agencia, chatbot_configuracion_id)
    _ = _campos(payload)
    try:
        return db.inicializar_asistente_desde_config(
            _agencia_id(agencia),
            int(chatbot_configuracion_id),
            cfg,
            db_captacion.obtener_agencia_por_id(_agencia_id(agencia)),
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e


@router.post("/configuraciones/{chatbot_configuracion_id}/faq/importar")
def importar_faq(
    chatbot_configuracion_id: int,
    payload: Optional[FaqImportarIn] = None,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    """
    Importa `preguntas_frecuentes` (JSONB de la configuración rígida) a
    chatbot.faq_conversacional. Idempotente por `codigo`.
    """
    cfg = _configuracion_rigida(agencia, chatbot_configuracion_id)
    datos = _campos(payload)
    faqs = datos.get("faqs")
    if faqs is None:
        faqs = cfg.get("preguntas_frecuentes")
    try:
        importadas = db.importar_faqs_desde_json(
            _agencia_id(agencia), int(chatbot_configuracion_id), faqs
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return {
        "chatbot_configuracion_id": int(chatbot_configuracion_id),
        "importadas": int(importadas),
    }


# ---------------------------------------------------------------------------
# Requisitos
# ---------------------------------------------------------------------------

@router.get("/configuraciones/{chatbot_configuracion_id}/requisitos")
def listar_requisitos(
    chatbot_configuracion_id: int,
    categoria: Optional[str] = Query(None),
    incluir_globales: bool = Query(True),
    solo_activos: bool = Query(False),
    solo_vigentes: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    return db.listar_requisitos(
        _agencia_id(agencia),
        chatbot_configuracion_id=cfg_id,
        incluir_globales=incluir_globales,
        categoria=categoria,
        solo_activos=solo_activos,
        solo_vigentes=solo_vigentes,
    )


@router.post("/configuraciones/{chatbot_configuracion_id}/requisitos", status_code=201)
def crear_requisito(
    chatbot_configuracion_id: int,
    payload: RequisitoIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    try:
        return db.crear_requisito(
            _agencia_id(agencia),
            {**_campos(payload), "chatbot_configuracion_id": cfg_id},
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e


@router.put("/configuraciones/{chatbot_configuracion_id}/requisitos/{requisito_id}")
def actualizar_requisito(
    chatbot_configuracion_id: int,
    requisito_id: int,
    payload: RequisitoIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    _exigir_en_configuracion(
        agencia, db.obtener_requisito, requisito_id, cfg_id, "Requisito"
    )
    try:
        row = db.actualizar_requisito(
            _agencia_id(agencia), int(requisito_id), _campos(payload)
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return _o_404(row, "Requisito")


@router.delete("/configuraciones/{chatbot_configuracion_id}/requisitos/{requisito_id}")
def eliminar_requisito(
    chatbot_configuracion_id: int,
    requisito_id: int,
    hard: bool = Query(False, description="Borrado físico en vez de lógico"),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    _exigir_en_configuracion(
        agencia, db.obtener_requisito, requisito_id, cfg_id, "Requisito"
    )
    db.eliminar_requisito(_agencia_id(agencia), int(requisito_id), hard=hard)
    return {"ok": True, "id": int(requisito_id)}


# ---------------------------------------------------------------------------
# Beneficios y bonos
# ---------------------------------------------------------------------------

@router.get("/configuraciones/{chatbot_configuracion_id}/beneficios")
def listar_beneficios(
    chatbot_configuracion_id: int,
    tipo: Optional[str] = Query(None),
    campania_id: Optional[int] = Query(None),
    incluir_globales: bool = Query(True),
    solo_activos: bool = Query(False),
    solo_vigentes: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    return db.listar_beneficios(
        _agencia_id(agencia),
        chatbot_configuracion_id=cfg_id,
        incluir_globales=incluir_globales,
        campania_id=campania_id,
        tipo=tipo,
        solo_activos=solo_activos,
        solo_vigentes=solo_vigentes,
    )


@router.post("/configuraciones/{chatbot_configuracion_id}/beneficios", status_code=201)
def crear_beneficio(
    chatbot_configuracion_id: int,
    payload: BeneficioIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    try:
        return db.crear_beneficio(
            _agencia_id(agencia),
            {**_campos(payload), "chatbot_configuracion_id": cfg_id},
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e


@router.put("/configuraciones/{chatbot_configuracion_id}/beneficios/{beneficio_id}")
def actualizar_beneficio(
    chatbot_configuracion_id: int,
    beneficio_id: int,
    payload: BeneficioIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    _exigir_en_configuracion(
        agencia, db.obtener_beneficio, beneficio_id, cfg_id, "Beneficio"
    )
    try:
        row = db.actualizar_beneficio(
            _agencia_id(agencia), int(beneficio_id), _campos(payload)
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return _o_404(row, "Beneficio")


@router.delete("/configuraciones/{chatbot_configuracion_id}/beneficios/{beneficio_id}")
def eliminar_beneficio(
    chatbot_configuracion_id: int,
    beneficio_id: int,
    hard: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    _exigir_en_configuracion(
        agencia, db.obtener_beneficio, beneficio_id, cfg_id, "Beneficio"
    )
    db.eliminar_beneficio(_agencia_id(agencia), int(beneficio_id), hard=hard)
    return {"ok": True, "id": int(beneficio_id)}


# ---------------------------------------------------------------------------
# FAQ conversacional
# ---------------------------------------------------------------------------

@router.get("/configuraciones/{chatbot_configuracion_id}/faq")
def listar_faq(
    chatbot_configuracion_id: int,
    categoria: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    incluir_globales: bool = Query(True),
    solo_activos: bool = Query(False),
    solo_vigentes: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    return db.listar_faqs(
        _agencia_id(agencia),
        chatbot_configuracion_id=cfg_id,
        incluir_globales=incluir_globales,
        categoria=categoria,
        search=search,
        solo_activos=solo_activos,
        solo_vigentes=solo_vigentes,
    )


@router.post("/configuraciones/{chatbot_configuracion_id}/faq", status_code=201)
def crear_faq(
    chatbot_configuracion_id: int,
    payload: FaqConversacionalIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    try:
        return db.crear_faq(
            _agencia_id(agencia),
            {**_campos(payload), "chatbot_configuracion_id": cfg_id},
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e


@router.put("/configuraciones/{chatbot_configuracion_id}/faq/{faq_id}")
def actualizar_faq(
    chatbot_configuracion_id: int,
    faq_id: int,
    payload: FaqConversacionalIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    _exigir_en_configuracion(agencia, db.obtener_faq, faq_id, cfg_id, "FAQ")
    try:
        row = db.actualizar_faq(_agencia_id(agencia), int(faq_id), _campos(payload))
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return _o_404(row, "FAQ")


@router.delete("/configuraciones/{chatbot_configuracion_id}/faq/{faq_id}")
def eliminar_faq(
    chatbot_configuracion_id: int,
    faq_id: int,
    hard: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    _exigir_en_configuracion(agencia, db.obtener_faq, faq_id, cfg_id, "FAQ")
    db.eliminar_faq(_agencia_id(agencia), int(faq_id), hard=hard)
    return {"ok": True, "id": int(faq_id)}


# ---------------------------------------------------------------------------
# Flujos conversacionales
# ---------------------------------------------------------------------------

@router.get("/configuraciones/{chatbot_configuracion_id}/flujos")
def listar_flujos(
    chatbot_configuracion_id: int,
    tipo_flujo: Optional[str] = Query(None, description="informativo | conversion"),
    solo_activos: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    return db.listar_flujos(
        _agencia_id(agencia),
        chatbot_configuracion_id=cfg_id,
        tipo_flujo=tipo_flujo,
        solo_activos=solo_activos,
    )


@router.post("/configuraciones/{chatbot_configuracion_id}/flujos", status_code=201)
def crear_flujo(
    chatbot_configuracion_id: int,
    payload: FlujoIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    try:
        return db.crear_flujo(
            _agencia_id(agencia),
            {**_campos(payload), "chatbot_configuracion_id": cfg_id},
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e


@router.put("/configuraciones/{chatbot_configuracion_id}/flujos/{flujo_id}")
def actualizar_flujo(
    chatbot_configuracion_id: int,
    flujo_id: int,
    payload: FlujoIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    _exigir_en_configuracion(agencia, db.obtener_flujo, flujo_id, cfg_id, "Flujo")
    try:
        row = db.actualizar_flujo(_agencia_id(agencia), int(flujo_id), _campos(payload))
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return _o_404(row, "Flujo")


@router.delete("/configuraciones/{chatbot_configuracion_id}/flujos/{flujo_id}")
def eliminar_flujo(
    chatbot_configuracion_id: int,
    flujo_id: int,
    hard: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    _exigir_en_configuracion(agencia, db.obtener_flujo, flujo_id, cfg_id, "Flujo")
    db.eliminar_flujo(_agencia_id(agencia), int(flujo_id), hard=hard)
    return {"ok": True, "id": int(flujo_id)}


# ---------------------------------------------------------------------------
# Pasos de flujo
# ---------------------------------------------------------------------------

@router.get("/flujos/{flujo_id}/pasos")
def listar_pasos(
    flujo_id: int,
    solo_activos: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    fid = _validar_flujo(agencia, flujo_id)
    return db.listar_flujo_pasos(_agencia_id(agencia), fid, solo_activos=solo_activos)


@router.post("/flujos/{flujo_id}/pasos", status_code=201)
def crear_paso(
    flujo_id: int,
    payload: FlujoPasoIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    fid = _validar_flujo(agencia, flujo_id)
    try:
        return db.crear_flujo_paso(
            _agencia_id(agencia), {**_campos(payload), "flujo_id": fid}
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e


@router.put("/flujos/{flujo_id}/pasos/{paso_id}")
def actualizar_paso(
    flujo_id: int,
    paso_id: int,
    payload: FlujoPasoIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    fid = _validar_flujo(agencia, flujo_id)
    _exigir_en_padre(
        agencia, db.obtener_flujo_paso, paso_id, "flujo_id", fid, "Paso"
    )
    try:
        row = db.actualizar_flujo_paso(
            _agencia_id(agencia), int(paso_id), _campos(payload)
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return _o_404(row, "Paso")


@router.delete("/flujos/{flujo_id}/pasos/{paso_id}")
def eliminar_paso(
    flujo_id: int,
    paso_id: int,
    hard: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    fid = _validar_flujo(agencia, flujo_id)
    _exigir_en_padre(
        agencia, db.obtener_flujo_paso, paso_id, "flujo_id", fid, "Paso"
    )
    db.eliminar_flujo_paso(_agencia_id(agencia), int(paso_id), hard=hard)
    return {"ok": True, "id": int(paso_id)}


@router.post("/flujos/{flujo_id}/pasos/{paso_id}/mover")
def mover_paso(
    flujo_id: int,
    paso_id: int,
    payload: FlujoPasoMoverIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    """Intercambia el paso con su vecino; devuelve el flujo reordenado."""
    fid = _validar_flujo(agencia, flujo_id)
    _exigir_en_padre(
        agencia, db.obtener_flujo_paso, paso_id, "flujo_id", fid, "Paso"
    )
    direccion = _DIRECCIONES_PASO.get(str(payload.direccion or "").strip().lower())
    if not direccion:
        raise HTTPException(
            status_code=400, detail="direccion debe ser 'up'/'subir' o 'down'/'bajar'"
        )
    try:
        return db.mover_flujo_paso(
            _agencia_id(agencia), fid, int(paso_id), direccion
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e


# ---------------------------------------------------------------------------
# Campañas de captación
# ---------------------------------------------------------------------------

@router.get("/configuraciones/{chatbot_configuracion_id}/campanias")
def listar_campanias(
    chatbot_configuracion_id: int,
    canal_origen: Optional[str] = Query(None),
    plataforma_codigo: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    solo_activas: bool = Query(False),
    solo_vigentes: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    return db.listar_campanias(
        _agencia_id(agencia),
        chatbot_configuracion_id=cfg_id,
        canal_origen=canal_origen,
        plataforma_codigo=plataforma_codigo,
        search=search,
        solo_activas=solo_activas,
        solo_vigentes=solo_vigentes,
    )


@router.post("/configuraciones/{chatbot_configuracion_id}/campanias", status_code=201)
def crear_campania(
    chatbot_configuracion_id: int,
    payload: CampaniaIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    try:
        return db.crear_campania(
            _agencia_id(agencia),
            {**_campos(payload), "chatbot_configuracion_id": cfg_id},
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e


@router.put("/configuraciones/{chatbot_configuracion_id}/campanias/{campania_id}")
def actualizar_campania(
    chatbot_configuracion_id: int,
    campania_id: int,
    payload: CampaniaIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    _exigir_en_configuracion(
        agencia, db.obtener_campania, campania_id, cfg_id, "Campaña"
    )
    try:
        row = db.actualizar_campania(
            _agencia_id(agencia), int(campania_id), _campos(payload)
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return _o_404(row, "Campaña")


@router.delete("/configuraciones/{chatbot_configuracion_id}/campanias/{campania_id}")
def eliminar_campania(
    chatbot_configuracion_id: int,
    campania_id: int,
    hard: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    _exigir_en_configuracion(
        agencia, db.obtener_campania, campania_id, cfg_id, "Campaña"
    )
    db.eliminar_campania(_agencia_id(agencia), int(campania_id), hard=hard)
    return {"ok": True, "id": int(campania_id)}


# ---------------------------------------------------------------------------
# Recursos y enlaces
# ---------------------------------------------------------------------------

@router.get("/configuraciones/{chatbot_configuracion_id}/recursos")
def listar_recursos(
    chatbot_configuracion_id: int,
    tipo: Optional[str] = Query(None),
    campania_id: Optional[int] = Query(None),
    incluir_globales: bool = Query(True),
    solo_activos: bool = Query(False),
    solo_vigentes: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    return db.listar_recursos(
        _agencia_id(agencia),
        chatbot_configuracion_id=cfg_id,
        incluir_globales=incluir_globales,
        campania_id=campania_id,
        tipo=tipo,
        solo_activos=solo_activos,
        solo_vigentes=solo_vigentes,
    )


@router.post("/configuraciones/{chatbot_configuracion_id}/recursos", status_code=201)
def crear_recurso(
    chatbot_configuracion_id: int,
    payload: RecursoEnlaceIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    try:
        return db.crear_recurso(
            _agencia_id(agencia),
            {**_campos(payload), "chatbot_configuracion_id": cfg_id},
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e


@router.put("/configuraciones/{chatbot_configuracion_id}/recursos/{recurso_id}")
def actualizar_recurso(
    chatbot_configuracion_id: int,
    recurso_id: int,
    payload: RecursoEnlaceIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    _exigir_en_configuracion(agencia, db.obtener_recurso, recurso_id, cfg_id, "Recurso")
    try:
        row = db.actualizar_recurso(
            _agencia_id(agencia), int(recurso_id), _campos(payload)
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return _o_404(row, "Recurso")


@router.delete("/configuraciones/{chatbot_configuracion_id}/recursos/{recurso_id}")
def eliminar_recurso(
    chatbot_configuracion_id: int,
    recurso_id: int,
    hard: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    _exigir_en_configuracion(agencia, db.obtener_recurso, recurso_id, cfg_id, "Recurso")
    db.eliminar_recurso(_agencia_id(agencia), int(recurso_id), hard=hard)
    return {"ok": True, "id": int(recurso_id)}


# ---------------------------------------------------------------------------
# Reglas de escalamiento
# ---------------------------------------------------------------------------

@router.get("/configuraciones/{chatbot_configuracion_id}/escalamientos")
def listar_escalamientos(
    chatbot_configuracion_id: int,
    evento: Optional[str] = Query(None),
    flujo_id: Optional[int] = Query(None),
    campania_id: Optional[int] = Query(None),
    incluir_globales: bool = Query(True),
    solo_activas: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    return db.listar_reglas_escalamiento(
        _agencia_id(agencia),
        chatbot_configuracion_id=cfg_id,
        incluir_globales=incluir_globales,
        flujo_id=flujo_id,
        campania_id=campania_id,
        evento=evento,
        solo_activas=solo_activas,
    )


@router.post(
    "/configuraciones/{chatbot_configuracion_id}/escalamientos", status_code=201
)
def crear_escalamiento(
    chatbot_configuracion_id: int,
    payload: ReglaEscalamientoIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    try:
        return db.crear_regla_escalamiento(
            _agencia_id(agencia),
            {**_campos(payload), "chatbot_configuracion_id": cfg_id},
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e


@router.put(
    "/configuraciones/{chatbot_configuracion_id}/escalamientos/{escalamiento_id}"
)
def actualizar_escalamiento(
    chatbot_configuracion_id: int,
    escalamiento_id: int,
    payload: ReglaEscalamientoIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    _exigir_en_configuracion(
        agencia,
        db.obtener_regla_escalamiento,
        escalamiento_id,
        cfg_id,
        "Regla de escalamiento",
    )
    try:
        row = db.actualizar_regla_escalamiento(
            _agencia_id(agencia), int(escalamiento_id), _campos(payload)
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return _o_404(row, "Regla de escalamiento")


@router.delete(
    "/configuraciones/{chatbot_configuracion_id}/escalamientos/{escalamiento_id}"
)
def eliminar_escalamiento(
    chatbot_configuracion_id: int,
    escalamiento_id: int,
    hard: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    _exigir_en_configuracion(
        agencia,
        db.obtener_regla_escalamiento,
        escalamiento_id,
        cfg_id,
        "Regla de escalamiento",
    )
    db.eliminar_regla_escalamiento(
        _agencia_id(agencia), int(escalamiento_id), hard=hard
    )
    return {"ok": True, "id": int(escalamiento_id)}


# ---------------------------------------------------------------------------
# Pruebas LIVE por configuración (alias usado por el panel del frontend)
# ---------------------------------------------------------------------------

@router.get("/configuraciones/{chatbot_configuracion_id}/pruebas-live")
def listar_pruebas_live_por_config(
    chatbot_configuracion_id: int,
    solo_activas: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    return db.listar_pruebas_live_por_config(
        _agencia_id(agencia), cfg_id, solo_activas=solo_activas
    )


@router.post("/configuraciones/{chatbot_configuracion_id}/pruebas-live", status_code=201)
def crear_prueba_live_por_config(
    chatbot_configuracion_id: int,
    payload: PruebaLiveIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    campos = _campos(payload)
    flujo_id = campos.get("flujo_id")
    if not flujo_id:
        raise HTTPException(status_code=422, detail="flujo_id es obligatorio")
    flujo = db.obtener_flujo(_agencia_id(agencia), int(flujo_id))
    if not flujo or int(flujo.get("chatbot_configuracion_id") or 0) != cfg_id:
        raise HTTPException(status_code=404, detail="Flujo no encontrado")
    try:
        return db.crear_prueba_live(_agencia_id(agencia), campos)
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e


@router.put("/configuraciones/{chatbot_configuracion_id}/pruebas-live/{prueba_live_id}")
def actualizar_prueba_live_por_config(
    chatbot_configuracion_id: int,
    prueba_live_id: int,
    payload: PruebaLiveIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    prueba = _o_404(
        db.obtener_prueba_live(_agencia_id(agencia), int(prueba_live_id)),
        "Prueba LIVE",
    )
    flujo = db.obtener_flujo(_agencia_id(agencia), int(prueba["flujo_id"]))
    if not flujo or int(flujo.get("chatbot_configuracion_id") or 0) != cfg_id:
        raise HTTPException(status_code=404, detail="Prueba LIVE no encontrada")
    try:
        row = db.actualizar_prueba_live(
            _agencia_id(agencia), int(prueba_live_id), _campos(payload)
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return _o_404(row, "Prueba LIVE")


@router.delete("/configuraciones/{chatbot_configuracion_id}/pruebas-live/{prueba_live_id}")
def eliminar_prueba_live_por_config(
    chatbot_configuracion_id: int,
    prueba_live_id: int,
    hard: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    prueba = _o_404(
        db.obtener_prueba_live(_agencia_id(agencia), int(prueba_live_id)),
        "Prueba LIVE",
    )
    flujo = db.obtener_flujo(_agencia_id(agencia), int(prueba["flujo_id"]))
    if not flujo or int(flujo.get("chatbot_configuracion_id") or 0) != cfg_id:
        raise HTTPException(status_code=404, detail="Prueba LIVE no encontrada")
    db.eliminar_prueba_live(_agencia_id(agencia), int(prueba_live_id), hard=hard)
    return {"ok": True, "id": int(prueba_live_id)}


# ---------------------------------------------------------------------------
# Pruebas LIVE (cuelgan del flujo, como en el modelo de datos)
# ---------------------------------------------------------------------------

@router.get("/flujos/{flujo_id}/pruebas-live")
def listar_pruebas_live(
    flujo_id: int,
    campania_id: Optional[int] = Query(None),
    solo_activas: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    fid = _validar_flujo(agencia, flujo_id)
    return db.listar_pruebas_live(
        _agencia_id(agencia),
        flujo_id=fid,
        campania_id=campania_id,
        solo_activas=solo_activas,
    )


@router.post("/flujos/{flujo_id}/pruebas-live", status_code=201)
def crear_prueba_live(
    flujo_id: int,
    payload: PruebaLiveIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    fid = _validar_flujo(agencia, flujo_id)
    try:
        return db.crear_prueba_live(
            _agencia_id(agencia), {**_campos(payload), "flujo_id": fid}
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e


@router.put("/flujos/{flujo_id}/pruebas-live/{prueba_live_id}")
def actualizar_prueba_live(
    flujo_id: int,
    prueba_live_id: int,
    payload: PruebaLiveIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    fid = _validar_flujo(agencia, flujo_id)
    _exigir_en_padre(
        agencia, db.obtener_prueba_live, prueba_live_id, "flujo_id", fid, "Prueba LIVE"
    )
    try:
        row = db.actualizar_prueba_live(
            _agencia_id(agencia), int(prueba_live_id), _campos(payload)
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return _o_404(row, "Prueba LIVE")


@router.delete("/flujos/{flujo_id}/pruebas-live/{prueba_live_id}")
def eliminar_prueba_live(
    flujo_id: int,
    prueba_live_id: int,
    hard: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    fid = _validar_flujo(agencia, flujo_id)
    _exigir_en_padre(
        agencia, db.obtener_prueba_live, prueba_live_id, "flujo_id", fid, "Prueba LIVE"
    )
    db.eliminar_prueba_live(_agencia_id(agencia), int(prueba_live_id), hard=hard)
    return {"ok": True, "id": int(prueba_live_id)}


# ---------------------------------------------------------------------------
# Evidencias requeridas (cuelgan de la prueba LIVE)
# ---------------------------------------------------------------------------

@router.get("/pruebas-live/{prueba_live_id}/evidencias-requeridas")
def listar_evidencias_requeridas(
    prueba_live_id: int,
    solo_activas: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    pid = _validar_prueba_live(agencia, prueba_live_id)
    return db.listar_evidencias_requeridas(
        _agencia_id(agencia), pid, solo_activas=solo_activas
    )


@router.post("/pruebas-live/{prueba_live_id}/evidencias-requeridas", status_code=201)
def crear_evidencia_requerida(
    prueba_live_id: int,
    payload: EvidenciaRequeridaIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    pid = _validar_prueba_live(agencia, prueba_live_id)
    try:
        return db.crear_evidencia_requerida(
            _agencia_id(agencia), {**_campos(payload), "prueba_live_id": pid}
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e


@router.put(
    "/pruebas-live/{prueba_live_id}/evidencias-requeridas/{evidencia_requerida_id}"
)
def actualizar_evidencia_requerida(
    prueba_live_id: int,
    evidencia_requerida_id: int,
    payload: EvidenciaRequeridaIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    pid = _validar_prueba_live(agencia, prueba_live_id)
    _exigir_en_padre(
        agencia,
        db.obtener_evidencia_requerida,
        evidencia_requerida_id,
        "prueba_live_id",
        pid,
        "Evidencia requerida",
    )
    try:
        row = db.actualizar_evidencia_requerida(
            _agencia_id(agencia), int(evidencia_requerida_id), _campos(payload)
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return _o_404(row, "Evidencia requerida")


@router.delete(
    "/pruebas-live/{prueba_live_id}/evidencias-requeridas/{evidencia_requerida_id}"
)
def eliminar_evidencia_requerida(
    prueba_live_id: int,
    evidencia_requerida_id: int,
    hard: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    pid = _validar_prueba_live(agencia, prueba_live_id)
    _exigir_en_padre(
        agencia,
        db.obtener_evidencia_requerida,
        evidencia_requerida_id,
        "prueba_live_id",
        pid,
        "Evidencia requerida",
    )
    db.eliminar_evidencia_requerida(
        _agencia_id(agencia), int(evidencia_requerida_id), hard=hard
    )
    return {"ok": True, "id": int(evidencia_requerida_id)}


# ---------------------------------------------------------------------------
# Conversaciones — lectura
# ---------------------------------------------------------------------------

@router.get("/conversaciones")
def listar_conversaciones(
    q: Optional[str] = Query(None, description="Nombre, teléfono o usuario"),
    estado: Optional[str] = Query(None),
    modo: Optional[str] = Query(None, description="informativo | conversion"),
    canal: Optional[str] = Query(None),
    plataforma: Optional[str] = Query(None, description="plataforma_codigo"),
    chatbot_configuracion_id: Optional[int] = Query(None),
    campania_id: Optional[int] = Query(None),
    manager_id: Optional[int] = Query(None),
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    solo_evidencias_pendientes: bool = Query(False),
    order: str = Query("ultimo_mensaje_desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    items, total = db.listar_conversaciones(
        _agencia_id(agencia),
        estado=estado,
        canal=canal,
        modo=modo,
        plataforma_codigo=plataforma,
        chatbot_configuracion_id=chatbot_configuracion_id,
        campania_id=campania_id,
        manager_id=manager_id,
        con_evidencias_pendientes=solo_evidencias_pendientes or None,
        search=q,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        order=order,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "results": items,
    }


@router.get("/conversaciones/resumen")
def resumen_conversaciones(
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    return db.resumen_conversaciones(_agencia_id(agencia))


@router.get("/conversaciones/{conversacion_id}")
def obtener_conversacion(
    conversacion_id: int,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    return _o_404(
        db.obtener_conversacion_detalle(_agencia_id(agencia), int(conversacion_id)),
        "Conversación",
    )


@router.get("/conversaciones/{conversacion_id}/mensajes")
def listar_mensajes(
    conversacion_id: int,
    limit: int = Query(50, ge=1, le=200),
    antes_de_id: Optional[int] = Query(None),
    desde_id: Optional[int] = Query(None),
    orden: str = Query("asc", description="asc | desc"),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cid = _validar_conversacion(agencia, conversacion_id)
    return db.listar_mensajes(
        _agencia_id(agencia),
        cid,
        limit=limit,
        antes_de_id=antes_de_id,
        desde_id=desde_id,
        orden=orden,
    )


@router.get("/conversaciones/{conversacion_id}/tareas")
def listar_tareas(
    conversacion_id: int,
    estado: Optional[str] = Query(None),
    solo_pendientes: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cid = _validar_conversacion(agencia, conversacion_id)
    return db.listar_tareas(
        _agencia_id(agencia),
        conversacion_id=cid,
        estado=estado,
        solo_pendientes=solo_pendientes,
    )


@router.get("/conversaciones/{conversacion_id}/evidencias")
def listar_evidencias(
    conversacion_id: int,
    estado_revision: Optional[str] = Query(None),
    solo_pendientes: bool = Query(False),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cid = _validar_conversacion(agencia, conversacion_id)
    return db.listar_evidencias(
        _agencia_id(agencia),
        conversacion_id=cid,
        estado_revision=estado_revision,
        solo_pendientes=solo_pendientes,
    )


@router.get("/conversaciones/{conversacion_id}/eventos")
def listar_eventos(
    conversacion_id: int,
    tipo_evento: Optional[str] = Query(None),
    solo_errores: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cid = _validar_conversacion(agencia, conversacion_id)
    return db.listar_eventos(
        _agencia_id(agencia),
        cid,
        tipo_evento=tipo_evento,
        solo_errores=solo_errores,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Conversaciones — acciones del manager
# ---------------------------------------------------------------------------

@router.post("/conversaciones/{conversacion_id}/tomar")
def tomar_conversacion(
    conversacion_id: int,
    payload: Optional[ConversacionTomarIn] = None,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    """El humano toma el control: la IA deja de responder."""
    cid = _validar_conversacion(agencia, conversacion_id)
    datos = _campos(payload)
    try:
        row = db.tomar_conversacion(
            _agencia_id(agencia),
            cid,
            datos.get("manager_id"),
            motivo=datos.get("motivo"),
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return _o_404(row, "Conversación")


@router.post("/conversaciones/{conversacion_id}/devolver-a-ia")
def devolver_a_ia(
    conversacion_id: int,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cid = _validar_conversacion(agencia, conversacion_id)
    try:
        row = db.devolver_a_ia(_agencia_id(agencia), cid)
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return _o_404(row, "Conversación")


@router.post("/conversaciones/{conversacion_id}/enviar-mensaje")
async def enviar_mensaje(
    conversacion_id: int,
    payload: ConversacionEnviarMensajeIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    """
    Mensaje manual del manager por el canal de la conversación.

    Se guarda siempre en el historial (aunque Meta rechace el envío) para que el
    panel y el contexto del asistente vean lo mismo que el candidato.
    """
    conversacion = _o_404(
        db.obtener_conversacion(_agencia_id(agencia), int(conversacion_id)),
        "Conversación",
    )
    texto = (payload.texto or "").strip()
    if not texto:
        raise HTTPException(status_code=400, detail="El texto no puede estar vacío")

    envio = await _enviar_por_canal(conversacion, texto)
    try:
        mensaje, _ = db.insertar_mensaje(
            _agencia_id(agencia),
            int(conversacion_id),
            canal=str(conversacion.get("canal") or "whatsapp"),
            direccion="saliente",
            remitente_tipo="humano",
            tipo_mensaje="texto",
            texto=texto,
            estado_envio="enviado" if envio.get("enviado") else "error",
            error_detalle=envio.get("error") or envio.get("motivo"),
            metadata={"manager_id": _campos(payload).get("manager_id")},
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return {"mensaje": mensaje, **envio}


@router.post("/conversaciones/{conversacion_id}/escalar")
def escalar_conversacion(
    conversacion_id: int,
    payload: ConversacionEscalarIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cid = _validar_conversacion(agencia, conversacion_id)
    datos = _campos(payload)
    try:
        row = db.escalar_conversacion(
            _agencia_id(agencia),
            cid,
            motivo=payload.motivo,
            manager_id=datos.get("manager_id"),
            estado_destino=datos.get("estado_destino"),
            origen="humano",
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return _o_404(row, "Conversación")


@router.post("/conversaciones/{conversacion_id}/cerrar")
def cerrar_conversacion(
    conversacion_id: int,
    payload: Optional[ConversacionCerrarIn] = None,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cid = _validar_conversacion(agencia, conversacion_id)
    datos = _campos(payload)
    try:
        row = db.cerrar_conversacion(
            _agencia_id(agencia),
            cid,
            motivo=datos.get("motivo"),
            estado_actual=datos.get("estado_actual"),
            origen="humano",
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return _o_404(row, "Conversación")


@router.post("/conversaciones/{conversacion_id}/asignar-campania")
def asignar_campania(
    conversacion_id: int,
    payload: ConversacionAsignarCampaniaIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cid = _validar_conversacion(agencia, conversacion_id)
    try:
        row = db.asignar_campania_conversacion(
            _agencia_id(agencia), cid, int(payload.campania_id)
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return _o_404(row, "Conversación")


@router.put("/tareas/{tarea_id}")
def actualizar_tarea(
    tarea_id: int,
    payload: TareaCandidatoUpdate,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    if not db.obtener_tarea(_agencia_id(agencia), int(tarea_id)):
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    try:
        row = db.actualizar_tarea(_agencia_id(agencia), int(tarea_id), _campos(payload))
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return _o_404(row, "Tarea")


@router.put("/evidencias/{evidencia_id}/revision")
def revisar_evidencia(
    evidencia_id: int,
    payload: EvidenciaRevisionIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    if not db.obtener_evidencia(_agencia_id(agencia), int(evidencia_id)):
        raise HTTPException(status_code=404, detail="Evidencia no encontrada")
    datos = _campos(payload)
    try:
        row = db.revisar_evidencia(
            _agencia_id(agencia),
            int(evidencia_id),
            estado_revision=payload.estado_revision,
            revisado_por=datos.get("revisado_por"),
            observaciones_revision=datos.get("observaciones_revision"),
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
    return _o_404(row, "Evidencia")


# ---------------------------------------------------------------------------
# Simulación (probador del asistente, sin enviar por WhatsApp)
# ---------------------------------------------------------------------------

@router.post("/configuraciones/{chatbot_configuracion_id}/simular")
async def simular_conversacion(
    chatbot_configuracion_id: int,
    payload: SimulacionIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
):
    cfg_id = _validar_configuracion(agencia, chatbot_configuracion_id)
    datos = _campos(payload)
    if not datos.get("texto"):
        raise HTTPException(status_code=400, detail="texto es obligatorio")
    try:
        return await _servicio().simular_mensaje(
            agencia_id=_agencia_id(agencia),
            chatbot_configuracion_id=cfg_id,
            texto=datos["texto"],
            conversacion_id=datos.get("conversacion_id"),
            aspirante_id=datos.get("aspirante_id"),
            campania_id=datos.get("campania_id"),
            canal=datos.get("canal") or "whatsapp",
            modo=datos.get("modo"),
            historial=datos.get("historial"),
        )
    except _ERRORES_DATOS as e:
        raise _http_error(e) from e
