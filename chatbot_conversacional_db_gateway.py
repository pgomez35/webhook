"""
Puente hacia `database_chatbot_conversacional`.

Ese módulo de acceso a datos se desarrolla en paralelo, por lo que aquí la
importación es tolerante: si todavía no existe, el servicio se degrada
(`disponible() == False`) en lugar de romper el arranque de la app.

Firmas esperadas del módulo de DB (todas reciben `agencia_id` para el
aislamiento multi-tenant sobre el esquema `chatbot`):

Conversaciones
    obtener_o_crear_conversacion(agencia_id, *, canal, usuario_externo_id,
        cuenta_externa_id=None, chatbot_configuracion_id=None, aspirante_id=None,
        telefono=None, nombre_contacto=None, campania_id=None, modo=None,
        conversacion_externa_id=None) -> dict
    obtener_conversacion(agencia_id, conversacion_id) -> dict | None
    actualizar_conversacion(agencia_id, conversacion_id, campos: dict) -> dict

Mensajes
    obtener_mensaje_por_externo_id(agencia_id, conversacion_id, mensaje_externo_id) -> dict | None
    insertar_mensaje(agencia_id, conversacion_id, **campos) -> dict
    listar_ultimos_mensajes(agencia_id, conversacion_id, limite=12) -> list[dict]
    contar_errores_ia_recientes(agencia_id, conversacion_id, limite=10) -> int

Eventos
    registrar_evento(agencia_id, conversacion_id, *, tipo_evento, nombre_evento,
        origen='chatbot', mensaje_id=None, estado_anterior=None, estado_nuevo=None,
        exitoso=True, detalle=None, error_detalle=None) -> dict

Catálogos de configuración
    obtener_agencia(agencia_id) -> dict | None
    obtener_configuracion_chatbot(agencia_id, chatbot_configuracion_id) -> dict | None
    obtener_asistente_configuracion(agencia_id, chatbot_configuracion_id) -> dict | None
    obtener_campania(agencia_id, campania_id) -> dict | None
    obtener_flujo(agencia_id, flujo_id) -> dict | None
    obtener_flujo_activo(agencia_id, chatbot_configuracion_id, tipo_flujo) -> dict | None
    obtener_paso_flujo(agencia_id, paso_id) -> dict | None
    listar_requisitos(agencia_id, chatbot_configuracion_id, limite=20) -> list[dict]
    listar_beneficios_vigentes(agencia_id, chatbot_configuracion_id, campania_id=None, limite=15) -> list[dict]
    listar_faq(agencia_id, chatbot_configuracion_id, limite=12) -> list[dict]
    buscar_faq(agencia_id, chatbot_configuracion_id, consulta, limite=3) -> list[dict]
    listar_recursos_enlaces(agencia_id, chatbot_configuracion_id, campania_id=None, limite=15) -> list[dict]
    obtener_recurso_por_codigo(agencia_id, codigo) -> dict | None
    listar_reglas_escalamiento(agencia_id, chatbot_configuracion_id, flujo_id=None, campania_id=None) -> list[dict]
    obtener_prueba_live(agencia_id, flujo_id, campania_id=None) -> dict | None
    listar_evidencias_requeridas(agencia_id, prueba_live_id, momento=None) -> list[dict]

Aspirante / acciones
    obtener_aspirante(agencia_id, aspirante_id) -> dict | None
    actualizar_datos_explicitos_aspirante(agencia_id, aspirante_id, campos: dict) -> dict
    crear_tarea_candidato(agencia_id, conversacion_id, **campos) -> dict
    registrar_evidencia(agencia_id, conversacion_id, **campos) -> dict
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional, Sequence, Union

from chatbot_conversacional_exceptions import ConversacionalError

logger = logging.getLogger("uvicorn.error")

try:  # el módulo de acceso a datos se crea en paralelo
    import database_chatbot_conversacional as db_conv
except ImportError:  # pragma: no cover - depende del estado del repo
    db_conv = None
    logger.warning(
        "chatbot_conversacional: 'database_chatbot_conversacional' no disponible todavía."
    )

Nombres = Union[str, Sequence[str]]


def disponible() -> bool:
    return db_conv is not None


def modulo() -> Any:
    if db_conv is None:
        raise ConversacionalError(
            "El módulo 'database_chatbot_conversacional' no está disponible."
        )
    return db_conv


def _candidatos(nombres: Nombres) -> Sequence[str]:
    return (nombres,) if isinstance(nombres, str) else tuple(nombres)


def resolver(nombres: Nombres) -> Optional[Callable[..., Any]]:
    """Devuelve la primera función existente entre los alias recibidos."""
    if db_conv is None:
        return None

    for nombre in _candidatos(nombres):
        funcion = getattr(db_conv, nombre, None)
        if callable(funcion):
            return funcion

    return None


def call(nombres: Nombres, *args: Any, **kwargs: Any) -> Any:
    """Invoca la función de DB o falla con un mensaje explícito."""
    funcion = resolver(nombres)
    if funcion is None:
        esperadas = " | ".join(_candidatos(nombres))
        raise ConversacionalError(
            f"database_chatbot_conversacional no expone ninguna de: {esperadas}"
        )

    return funcion(*args, **kwargs)


def call_opcional(nombres: Nombres, *args: Any, default: Any = None, **kwargs: Any) -> Any:
    """
    Igual que `call`, pero tolera funciones aún no implementadas y errores de
    catálogo: devuelve `default` y deja rastro en el log.
    """
    funcion = resolver(nombres)
    if funcion is None:
        logger.debug(
            "chatbot_conversacional: función de DB pendiente (%s); se usa valor por defecto.",
            " | ".join(_candidatos(nombres)),
        )
        return default

    try:
        return funcion(*args, **kwargs)

    except Exception as exc:  # noqa: BLE001 - catálogo opcional no debe romper la respuesta
        logger.warning(
            "chatbot_conversacional: error consultando %s: %s",
            getattr(funcion, "__name__", nombres),
            exc,
        )
        return default
