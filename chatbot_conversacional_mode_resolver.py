"""
Resolución del modo conversacional (informativo / conversión).

Orden de precedencia:
1. `campania.modo_predeterminado` si la campaña está activa y vigente.
2. `aspirante.modo_conversacional`.
3. `asistente.modo_predeterminado`.
4. Fallback por origen: ads con candidato preseleccionado -> conversión;
   orgánico o desconocido -> informativo.

Sobre el modo resuelto se aplican los interruptores del asistente
(`modo_informativo_activo` / `modo_conversion_activo`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Optional

from chatbot_conversacional_exceptions import AsistenteInactivo

MODO_INFORMATIVO = "informativo"
MODO_CONVERSION = "conversion"
MODOS_VALIDOS = frozenset({MODO_INFORMATIVO, MODO_CONVERSION})

ORIGENES_ADS = frozenset(
    {"instagram_ads", "facebook_ads", "messenger_ads", "tiktok_ads"}
)

ORIGEN_CAMPANIA = "campania"
ORIGEN_ASPIRANTE = "aspirante"
ORIGEN_ASISTENTE = "asistente"
ORIGEN_FALLBACK = "fallback"


@dataclass(frozen=True)
class ResolucionModo:
    modo: str
    origen: str
    campania_id: Optional[int] = None
    ajustado: bool = False
    motivo_ajuste: Optional[str] = None


def _normalizar_modo(valor: Any) -> Optional[str]:
    if not valor:
        return None

    modo = str(valor).strip().lower()
    return modo if modo in MODOS_VALIDOS else None


def _a_fecha(valor: Any) -> Optional[date]:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return None


def campania_vigente(campania: Optional[Dict[str, Any]], hoy: Optional[date] = None) -> bool:
    """La campaña manda solo si está activa y dentro de su ventana de fechas."""
    if not campania:
        return False

    if not campania.get("activo", True):
        return False

    referencia = hoy or date.today()

    inicio = _a_fecha(campania.get("fecha_inicio"))
    if inicio and referencia < inicio:
        return False

    fin = _a_fecha(campania.get("fecha_fin"))
    if fin and referencia > fin:
        return False

    return True


def _modo_por_origen(
    aspirante: Optional[Dict[str, Any]],
    campania: Optional[Dict[str, Any]],
) -> str:
    aspirante = aspirante or {}
    campania = campania or {}

    if aspirante.get("preseleccionado_ads"):
        return MODO_CONVERSION

    origen = str(aspirante.get("origen_captacion") or campania.get("canal_origen") or "").lower()
    if origen in ORIGENES_ADS and campania.get("candidato_preseleccionado", True):
        return MODO_CONVERSION

    return MODO_INFORMATIVO


def _aplicar_interruptores(
    modo: str,
    asistente: Optional[Dict[str, Any]],
) -> tuple[str, bool, Optional[str]]:
    asistente = asistente or {}

    informativo_activo = bool(asistente.get("modo_informativo_activo", True))
    conversion_activo = bool(asistente.get("modo_conversion_activo", False))

    if not informativo_activo and not conversion_activo:
        raise AsistenteInactivo(
            "El asistente no tiene ningún modo conversacional habilitado.",
            {"asistente_id": asistente.get("id")},
        )

    if modo == MODO_CONVERSION and not conversion_activo:
        return MODO_INFORMATIVO, True, "modo_conversion_desactivado"

    if modo == MODO_INFORMATIVO and not informativo_activo:
        return MODO_CONVERSION, True, "modo_informativo_desactivado"

    return modo, False, None


def resolver_modo(
    *,
    asistente: Optional[Dict[str, Any]],
    aspirante: Optional[Dict[str, Any]] = None,
    campania: Optional[Dict[str, Any]] = None,
    conversacion: Optional[Dict[str, Any]] = None,
    hoy: Optional[date] = None,
) -> ResolucionModo:
    asistente = asistente or {}

    if asistente and asistente.get("activo") is False:
        raise AsistenteInactivo(
            "La configuración del asistente está inactiva.",
            {"asistente_id": asistente.get("id")},
        )

    campania_manda = campania_vigente(campania, hoy)
    campania_id = (campania or {}).get("id") if campania_manda else None

    modo = None
    origen = ORIGEN_FALLBACK

    if campania_manda:
        modo = _normalizar_modo((campania or {}).get("modo_predeterminado"))
        if modo:
            origen = ORIGEN_CAMPANIA

    if modo is None:
        modo = _normalizar_modo((aspirante or {}).get("modo_conversacional"))
        if modo:
            origen = ORIGEN_ASPIRANTE

    if modo is None:
        modo = _normalizar_modo(asistente.get("modo_predeterminado"))
        if modo:
            origen = ORIGEN_ASISTENTE

    if modo is None:
        modo = _modo_por_origen(aspirante, campania)
        origen = ORIGEN_FALLBACK

    modo, ajustado, motivo = _aplicar_interruptores(modo, asistente)

    if campania_id is None and conversacion:
        campania_id = conversacion.get("campania_id")

    return ResolucionModo(
        modo=modo,
        origen=origen,
        campania_id=campania_id,
        ajustado=ajustado,
        motivo_ajuste=motivo,
    )


def tipo_flujo_para_modo(modo: str) -> str:
    """`flujos_conversacionales.tipo_flujo` usa los mismos códigos que el modo."""
    return MODO_CONVERSION if modo == MODO_CONVERSION else MODO_INFORMATIVO
