"""
Fábrica del agente conversacional.

Variables de entorno:
- OPENAI_API_KEY: credencial del proveedor.
- OPENAI_MODEL_CHATBOT_CONVERSACIONAL: modelo por defecto del servicio.
- CHATBOT_CONVERSACIONAL_ENABLED: interruptor global (default true).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from chatbot_conversacional_context_builder import ConversationalContext
from chatbot_conversacional_exceptions import ConversacionalError
from chatbot_conversacional_prompt_builder import construir_instrucciones
from chatbot_conversacional_tools import (
    AGENTS_SDK_DISPONIBLE,
    ContextoHerramientas,
    obtener_herramientas,
)

logger = logging.getLogger("uvicorn.error")

MODELO_DEFAULT = "gpt-4.1-mini"
MAX_TOKENS_DEFAULT = 600
TEMPERATURA_DEFAULT = 0.4
MAX_TURNOS_DEFAULT = 6

_sdk_configurado = False


def feature_enabled() -> bool:
    return os.getenv("CHATBOT_CONVERSACIONAL_ENABLED", "true").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def openai_api_key() -> Optional[str]:
    clave = os.getenv("OPENAI_API_KEY")
    return clave.strip() if clave and clave.strip() else None


def openai_configurado() -> bool:
    return openai_api_key() is not None


def resolver_modelo(asistente: Optional[Dict[str, Any]] = None) -> str:
    """Prioridad: variable de entorno > modelo del asistente > default."""
    desde_entorno = os.getenv("OPENAI_MODEL_CHATBOT_CONVERSACIONAL")
    if desde_entorno and desde_entorno.strip():
        return desde_entorno.strip()

    desde_asistente = (asistente or {}).get("modelo_ia")
    if desde_asistente and str(desde_asistente).strip():
        return str(desde_asistente).strip()

    return MODELO_DEFAULT


def max_tokens_salida(asistente: Optional[Dict[str, Any]] = None) -> int:
    valor = (asistente or {}).get("max_tokens_salida")
    try:
        return max(100, min(int(valor), 4000))
    except (TypeError, ValueError):
        return MAX_TOKENS_DEFAULT


def temperatura(asistente: Optional[Dict[str, Any]] = None) -> float:
    reglas = (asistente or {}).get("reglas_adicionales")
    if isinstance(reglas, dict):
        try:
            return max(0.0, min(float(reglas["temperatura"]), 1.5))
        except (KeyError, TypeError, ValueError):
            pass

    return TEMPERATURA_DEFAULT


@dataclass
class AgentePreparado:
    instrucciones: str
    modelo: str
    max_tokens: int
    herramientas: List[Any]
    contexto_herramientas: ContextoHerramientas
    agente: Any = None
    sdk_disponible: bool = False
    prompt_version: Optional[str] = None
    max_turnos: int = MAX_TURNOS_DEFAULT
    metadata: Dict[str, Any] = field(default_factory=dict)


def _configurar_sdk() -> None:
    global _sdk_configurado
    if _sdk_configurado or not AGENTS_SDK_DISPONIBLE:
        return

    clave = openai_api_key()
    if not clave:
        return

    try:  # pragma: no cover - depende del entorno
        from agents import set_default_openai_key  # type: ignore

        set_default_openai_key(clave)
        _sdk_configurado = True

    except Exception as exc:  # noqa: BLE001
        logger.warning("chatbot_conversacional: no se pudo configurar el SDK de agents: %s", exc)


def crear_agente(
    contexto: ConversationalContext,
    *,
    dry_run: bool = False,
    mensaje_id: Optional[int] = None,
) -> AgentePreparado:
    """Construye el agente con instrucciones, modelo y herramientas del tenant."""
    if not openai_configurado():
        raise ConversacionalError(
            "OpenAI no configurado: define OPENAI_API_KEY en el entorno."
        )

    instrucciones = construir_instrucciones(contexto)
    modelo = resolver_modelo(contexto.asistente)
    tokens = max_tokens_salida(contexto.asistente)

    herramientas = obtener_herramientas(
        contexto.herramientas_permitidas or None,
        modo=contexto.modo,
    )

    contexto_herramientas = ContextoHerramientas(
        agencia_id=contexto.agencia_id,
        conversacion_id=contexto.conversacion_id,
        contexto=contexto,
        dry_run=dry_run or contexto.dry_run,
        mensaje_id=mensaje_id,
    )

    preparado = AgentePreparado(
        instrucciones=instrucciones,
        modelo=modelo,
        max_tokens=tokens,
        herramientas=herramientas,
        contexto_herramientas=contexto_herramientas,
        sdk_disponible=AGENTS_SDK_DISPONIBLE,
        prompt_version=contexto.asistente.get("prompt_version"),
        metadata={
            "modo": contexto.modo,
            "origen_modo": contexto.resolucion_modo.origen,
            "agencia_id": contexto.agencia_id,
            "conversacion_id": contexto.conversacion_id,
        },
    )

    if not AGENTS_SDK_DISPONIBLE:
        logger.info(
            "chatbot_conversacional: 'openai-agents' no instalado; se usa el ejecutor de reserva."
        )
        return preparado

    _configurar_sdk()

    from agents import Agent, ModelSettings  # type: ignore

    preparado.agente = Agent[ContextoHerramientas](
        name=str(contexto.asistente.get("nombre_asistente") or "Asistente de captación"),
        instructions=instrucciones,
        model=modelo,
        tools=herramientas,
        model_settings=ModelSettings(
            max_tokens=tokens,
            temperature=temperatura(contexto.asistente),
        ),
    )

    return preparado
