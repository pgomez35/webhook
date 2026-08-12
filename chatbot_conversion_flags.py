"""
Feature flag interno del motor inteligente.

CHATBOT_INTELIGENTE_MOTOR:
  - conversion (default) → GPT conversa + gate de acciones
  - v2 → motor determinista V2 (rollback técnico)
  - legacy → service_chatbot_conversacional con orquestador

No es configuración visible de agencia.
"""
from __future__ import annotations

import os


def motor_inteligente() -> str:
    raw = (os.getenv("CHATBOT_INTELIGENTE_MOTOR") or "conversion").strip().lower()
    if raw in {"conversion", "recuperado", "inteligente_conversion"}:
        return "conversion"
    if raw in {"v2", "inteligente_v2"}:
        return "v2"
    if raw in {"legacy", "orquestador", "inteligente_legacy"}:
        return "legacy"
    return "conversion"


def conversion_tools_externas_habilitadas() -> bool:
    """
    Fase 1: conversación + conocimiento + memoria, sin acciones externas.
    Activar con CHATBOT_CONVERSION_TOOLS_EXTERNAS=1 cuando la charla se vea natural.
    """
    return (os.getenv("CHATBOT_CONVERSION_TOOLS_EXTERNAS") or "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


# Tools de avance / irreversibles: fuera del agente en fase 1.
HERRAMIENTAS_EXTERNAS_CONVERSION = frozenset(
    {
        "enviar_enlace_autorizado",
        "confirmar_interes",
        "crear_tarea_candidato",
        "preparar_prueba_live",
        "solicitar_evidencias",
        "registrar_evidencia_recibida",
    }
)
