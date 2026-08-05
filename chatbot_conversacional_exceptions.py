"""Excepciones del servicio conversacional (OpenAI Agents SDK)."""
from __future__ import annotations

from typing import Any, Dict, Optional


class ConversacionalError(Exception):
    """Error base del servicio conversacional."""

    def __init__(self, mensaje: str, detalle: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.detalle = detalle or {}


class AsistenteInactivo(ConversacionalError):
    """El asistente está inactivo o no tiene ningún modo habilitado."""


class OpenAIFallido(ConversacionalError):
    """Falló la llamada al proveedor de IA (timeout, cuota, error de red, etc.)."""


class HerramientaNoPermitida(ConversacionalError):
    """La herramienta no está autorizada o intenta una acción prohibida."""


class AgenciaMismatch(ConversacionalError):
    """Un registro cargado no pertenece a la agencia del contexto (aislamiento multi-tenant)."""
