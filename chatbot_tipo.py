"""
Resolución del tipo de chatbot visible
(tradicional | informativo | inteligente).

Fuente principal: chatbot_configuracion.tipo_chatbot.
Compatibilidad: flags usar_asistente_conversacional / usar_rutas_adaptativas
y modos del asistente.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

TIPOS_CHATBOT = frozenset({"tradicional", "informativo", "inteligente"})
TIPO_TRADICIONAL = "tradicional"
TIPO_INFORMATIVO = "informativo"
TIPO_INTELIGENTE = "inteligente"

_ALIAS_TIPO = {
    "clasico": TIPO_TRADICIONAL,
    "clásico": TIPO_TRADICIONAL,
    "classic": TIPO_TRADICIONAL,
    "captacion": TIPO_TRADICIONAL,
    "captación": TIPO_TRADICIONAL,
    "conversion": TIPO_INTELIGENTE,
    "conversacional": TIPO_INTELIGENTE,
}

PUBLICO_DETECTAR = "detectar"
PUBLICO_PRINCIPIANTES = "principiantes"
PUBLICO_EXPERIMENTADOS = "experimentados"


def normalizar_tipo_chatbot(valor: Any) -> Optional[str]:
    if valor is None:
        return None
    texto = str(valor).strip().lower()
    if texto in TIPOS_CHATBOT:
        return texto
    return _ALIAS_TIPO.get(texto)


def flags_desde_tipo(tipo: str) -> Tuple[bool, bool]:
    """
    Sync transitorio de flags en chatbot_configuracion.
    tradicional → asistente=false, rutas=false
    informativo → asistente=true, rutas=false
    inteligente → asistente=true, rutas=true
    """
    tipo_n = normalizar_tipo_chatbot(tipo) or TIPO_INFORMATIVO
    if tipo_n == TIPO_INTELIGENTE:
        return True, True
    if tipo_n == TIPO_INFORMATIVO:
        return True, False
    return False, False


def modos_asistente_desde_tipo(tipo: str) -> Dict[str, Any]:
    """
    Sync interno de modos en asistente_configuracion (no visibles a la agencia).

    Al elegir informativo/inteligente, el backend deja activo=true si el
    asistente existe. En tradicional no se usa el stack conversacional.
    """
    tipo_n = normalizar_tipo_chatbot(tipo) or TIPO_INFORMATIVO
    if tipo_n == TIPO_INTELIGENTE:
        return {
            "modo_informativo_activo": True,
            "modo_conversion_activo": True,
            "modo_predeterminado": "conversion",
        }
    if tipo_n == TIPO_INFORMATIVO:
        return {
            "modo_informativo_activo": True,
            "modo_conversion_activo": False,
            "modo_predeterminado": "informativo",
        }
    return {
        "modo_informativo_activo": False,
        "modo_conversion_activo": False,
        "modo_predeterminado": "informativo",
    }


def sync_completo_desde_tipo(tipo: str) -> Dict[str, Any]:
    """Payload completo de sincronización interna al guardar tipo_chatbot."""
    flag_asistente, flag_rutas = flags_desde_tipo(tipo)
    out = {
        "tipo_chatbot": normalizar_tipo_chatbot(tipo) or TIPO_INFORMATIVO,
        "usar_asistente_conversacional": flag_asistente,
        "usar_rutas_adaptativas": flag_rutas,
    }
    out.update(modos_asistente_desde_tipo(tipo))
    return out


def tipo_desde_flags(
    *,
    usar_asistente_conversacional: bool,
    usar_rutas_adaptativas: bool,
) -> str:
    """Fallback de lectura cuando tipo_chatbot aún no está poblado."""
    if not usar_asistente_conversacional:
        return TIPO_TRADICIONAL
    if usar_rutas_adaptativas:
        return TIPO_INTELIGENTE
    return TIPO_INFORMATIVO


def resolver_tipo_chatbot(configuracion: Optional[Dict[str, Any]]) -> str:
    cfg = configuracion or {}
    tipo = normalizar_tipo_chatbot(cfg.get("tipo_chatbot"))
    if tipo:
        return tipo
    return tipo_desde_flags(
        usar_asistente_conversacional=bool(cfg.get("usar_asistente_conversacional")),
        usar_rutas_adaptativas=bool(cfg.get("usar_rutas_adaptativas")),
    )


def enriquecer_config_con_tipo(configuracion: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = dict(configuracion or {})
    out["tipo_chatbot"] = resolver_tipo_chatbot(out)
    return out


def preparar_payload_tipo(
    data: Dict[str, Any],
    *,
    tipo_explicito: Optional[str] = None,
) -> Dict[str, Any]:
    """Al crear/actualizar config: sincroniza flags si viene tipo_chatbot."""
    out = dict(data or {})
    tipo = normalizar_tipo_chatbot(
        tipo_explicito if tipo_explicito is not None else out.get("tipo_chatbot")
    )
    if tipo:
        sync = sync_completo_desde_tipo(tipo)
        out["tipo_chatbot"] = sync["tipo_chatbot"]
        out["usar_asistente_conversacional"] = sync["usar_asistente_conversacional"]
        out["usar_rutas_adaptativas"] = sync["usar_rutas_adaptativas"]
        return out

    if "usar_asistente_conversacional" in out or "usar_rutas_adaptativas" in out:
        derivado = tipo_desde_flags(
            usar_asistente_conversacional=bool(
                out.get("usar_asistente_conversacional", False)
            ),
            usar_rutas_adaptativas=bool(out.get("usar_rutas_adaptativas", False)),
        )
        out["tipo_chatbot"] = derivado
    return out


def mapear_publico_a_estrategia(
    publico: str,
    *,
    fijo: bool = False,
) -> Dict[str, Any]:
    """
    Público visible → campos internos del asistente.

    Detectar automáticamente → adaptativa
    Principiantes → orientada_principiantes (o nivel_fijo si fijo=True)
    Experimentados → orientada_experimentados (o nivel_fijo si fijo=True)
    """
    valor = str(publico or "").strip().lower()
    if valor in {PUBLICO_PRINCIPIANTES, "principiante"}:
        if fijo:
            return {
                "estrategia_nivel_aspirante": "nivel_fijo",
                "nivel_fijo": "principiante",
                "nivel_predeterminado": "principiante",
                "permitir_reclasificacion_automatica": False,
                "preguntar_nivel_si_ambiguo": False,
                "publico_chatbot": PUBLICO_PRINCIPIANTES,
                "publico_fijo": True,
            }
        return {
            "estrategia_nivel_aspirante": "orientada_principiantes",
            "nivel_fijo": None,
            "nivel_predeterminado": "principiante",
            "permitir_reclasificacion_automatica": True,
            "preguntar_nivel_si_ambiguo": True,
            "publico_chatbot": PUBLICO_PRINCIPIANTES,
            "publico_fijo": False,
        }
    if valor in {PUBLICO_EXPERIMENTADOS, "experimentado"}:
        if fijo:
            return {
                "estrategia_nivel_aspirante": "nivel_fijo",
                "nivel_fijo": "experimentado",
                "nivel_predeterminado": "experimentado",
                "permitir_reclasificacion_automatica": False,
                "preguntar_nivel_si_ambiguo": False,
                "publico_chatbot": PUBLICO_EXPERIMENTADOS,
                "publico_fijo": True,
            }
        return {
            "estrategia_nivel_aspirante": "orientada_experimentados",
            "nivel_fijo": None,
            "nivel_predeterminado": "experimentado",
            "permitir_reclasificacion_automatica": True,
            "preguntar_nivel_si_ambiguo": True,
            "publico_chatbot": PUBLICO_EXPERIMENTADOS,
            "publico_fijo": False,
        }
    return {
        "estrategia_nivel_aspirante": "adaptativa",
        "nivel_fijo": None,
        "permitir_reclasificacion_automatica": True,
        "preguntar_nivel_si_ambiguo": True,
        "publico_chatbot": PUBLICO_DETECTAR,
        "publico_fijo": False,
    }


def mapear_estrategia_a_publico(asistente: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Devuelve {publico, fijo} para la UI."""
    a = asistente or {}
    estrategia = str(a.get("estrategia_nivel_aspirante") or "").strip().lower()
    nivel_fijo = str(a.get("nivel_fijo") or "").strip().lower()
    if estrategia == "nivel_fijo" and nivel_fijo == "principiante":
        return {"publico": PUBLICO_PRINCIPIANTES, "fijo": True}
    if estrategia == "nivel_fijo" and nivel_fijo == "experimentado":
        return {"publico": PUBLICO_EXPERIMENTADOS, "fijo": True}
    if estrategia == "orientada_principiantes":
        return {"publico": PUBLICO_PRINCIPIANTES, "fijo": False}
    if estrategia == "orientada_experimentados":
        return {"publico": PUBLICO_EXPERIMENTADOS, "fijo": False}
    return {"publico": PUBLICO_DETECTAR, "fijo": False}
