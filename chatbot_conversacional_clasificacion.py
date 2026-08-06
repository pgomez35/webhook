"""
Clasificación adaptativa de nivel e intención (archivo plano, raíz).

El modelo propone; este módulo valida prioridades, construye la acción y
prepara campos de persistencia sobre columnas ya existentes.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from schemas_chatbot_conversacional import ClasificacionConversacional

logger = logging.getLogger("uvicorn.error")

NIVELES = frozenset({"desconocido", "principiante", "experimentado"})
FUENTES_ESTABLES = frozenset(
    {"manual", "declarada", "formulario_ads", "campana", "respuesta_opcion"}
)
FUENTES_BLOQUEANTES = frozenset({"manual"})

_PATRONES_EXPERIMENTADO = (
    r"\bya hago\b",
    r"\bya hago live",
    r"\bya hago lives\b",
    r"\bhago lives?\b",
    r"\bhago transmisiones\b",
    r"\btengo experiencia\b",
    r"\bsoy bueno\b",
    r"\bno me gusta dar vueltas\b",
    r"\bm[eé]teme\b",
    r"\bvamos con toda\b",
    r"\bquiero entrar\b",
    r"\bquiero incorpor",
    r"\bingresar\b",
    r"\bunirme\b",
    r"\bsolicitud\b",
    r"\benviar(?:me)? (?:el )?enlace\b",
)
_PATRONES_PRINCIPIANTE = (
    r"\bnunca he hecho\b",
    r"\bnunca he hecho live",
    r"\bno s[eé] c[oó]mo\b",
    r"\bsoy nuevo\b",
    r"\bsoy nueva\b",
    r"\bprincipiante\b",
    r"\bempezar desde cero\b",
    r"\bquiero aprender\b",
    r"\bnunca transmit",
)
_PATRONES_BONOS = (r"\bbono", r"\bincentivo", r"\bbienvenida")
_PATRONES_REQUISITOS = (r"\brequisito", r"\bqu[eé] piden\b", r"\bnecesito para")
_PATRONES_BENEFICIOS = (r"\bbeneficio", r"\bqu[eé] ofrecen\b")
_PATRONES_CATEGORIAS = (r"\bcategor[ií]a", r"\brango")
_PATRONES_ASESOR = (
    r"\bhablo con alguien\b",
    r"\basesor\b",
    r"\bhumano\b",
    r"\bmanager\b",
    r"\bagente\b",
)
_PATRONES_SALUDO = (
    r"^(hola|buenas|hey|hi|hello|holi|holis|saludos|informaci[oó]n|info)(\s.*)?$",
)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _normalizar(texto: str) -> str:
    valor = str(texto or "").strip().lower()
    valor = unicodedata.normalize("NFD", valor)
    valor = "".join(ch for ch in valor if unicodedata.category(ch) != "Mn")
    valor = re.sub(r"[^\w\s]", " ", valor, flags=re.UNICODE)
    return re.sub(r"\s+", " ", valor).strip()


def _coincide(texto: str, patrones: Tuple[str, ...]) -> bool:
    return any(re.search(p, texto) for p in patrones)


def es_saludo_o_info_corta(texto: str) -> bool:
    n = _normalizar(texto)
    if not n:
        return False
    return bool(re.match(_PATRONES_SALUDO[0], n)) or n in {
        "hola",
        "buenas",
        "hey",
        "hi",
        "hello",
        "informacion",
        "info",
    }


def inferir_intencion(texto: str) -> Tuple[str, float]:
    n = _normalizar(texto)
    if _coincide(n, _PATRONES_ASESOR):
        return "asesor", 0.92
    if _coincide(n, _PATRONES_BONOS):
        return "bonos", 0.9
    if _coincide(n, _PATRONES_REQUISITOS):
        return "requisitos", 0.88
    if _coincide(n, _PATRONES_BENEFICIOS):
        return "beneficios", 0.85
    if _coincide(n, _PATRONES_CATEGORIAS):
        return "categorias", 0.85
    if _coincide(n, (r"\bevidencia", r"\bcaptura", r"\bscreenshot", r"\bfoto del live")):
        return "evidencias", 0.85
    if _coincide(n, (r"\bsolicitud\b", r"\benlace\b", r"\bformulario\b")):
        return "solicitud", 0.86
    if _coincide(
        n,
        (
            r"\bquiero entrar\b",
            r"\bingresar\b",
            r"\bunirme\b",
            r"\bm[eé]teme\b",
            r"\bincorpor",
        ),
    ):
        return "incorporacion", 0.9
    if es_saludo_o_info_corta(texto):
        return "informacion", 0.55
    return "desconocida", 0.35


def inferir_nivel_desde_texto(texto: str) -> Tuple[str, float, bool, Optional[str]]:
    """Retorna (nivel, confianza, declarado_explicitamente, evidencia_breve)."""
    n = _normalizar(texto)
    if _coincide(n, _PATRONES_PRINCIPIANTE):
        return "principiante", 0.93, True, n[:180] or None
    if _coincide(n, _PATRONES_EXPERIMENTADO):
        return "experimentado", 0.92, True, n[:180] or None
    return "desconocido", 0.2, False, None


def usar_rutas_adaptativas(configuracion: Optional[Dict[str, Any]]) -> bool:
    cfg = configuracion or {}
    return bool(cfg.get("usar_asistente_conversacional")) and bool(
        cfg.get("usar_rutas_adaptativas")
    )


@dataclass
class ResultadoClasificacion:
    clasificacion: ClasificacionConversacional
    campos_conversacion: Dict[str, Any]
    campos_aspirante: Dict[str, Any]
    registrar_evento: bool
    detalle_evento: Dict[str, Any]
    persistir_nivel_estable: bool
    incremento_preguntas: int
    texto_respuesta_directa: Optional[str]


def _float_safe(valor: Any, default: float = 0.0) -> float:
    try:
        if valor is None:
            return default
        return float(valor)
    except (TypeError, ValueError):
        return default


def _umbral(asistente: Dict[str, Any]) -> float:
    return _float_safe(asistente.get("umbral_confianza_nivel"), 0.75)


def clasificar_mensaje(
    *,
    texto: str,
    asistente: Dict[str, Any],
    conversacion: Dict[str, Any],
    aspirante: Optional[Dict[str, Any]] = None,
) -> ResultadoClasificacion:
    """
    Aplica prioridad de nivel e intención sin persistir.
    Una orientación de estrategia no se confirma como nivel estable.
    """
    aspirante = aspirante or {}
    estrategia = str(
        asistente.get("estrategia_nivel_aspirante") or "adaptativa"
    ).strip().lower()
    umbral = _umbral(asistente)

    nivel_conv = str(conversacion.get("nivel_experiencia") or "desconocido")
    fuente_conv = str(conversacion.get("nivel_experiencia_fuente") or "") or None
    conf_conv = _float_safe(conversacion.get("nivel_experiencia_confianza"), 0.0)
    bloqueado = bool(
        conversacion.get("nivel_experiencia_bloqueado_manual")
        or aspirante.get("nivel_experiencia_bloqueado_manual")
    )
    confirmado_conv = bool(conversacion.get("nivel_experiencia_confirmado"))
    intencion_prev = str(conversacion.get("intencion_actual") or "desconocida")
    preguntas = int(conversacion.get("preguntas_clasificacion_realizadas") or 0)
    max_preguntas = int(asistente.get("max_preguntas_clasificacion") or 1)
    preguntar_si_ambiguo = bool(asistente.get("preguntar_nivel_si_ambiguo", True))
    permitir_reclass = bool(asistente.get("permitir_reclasificacion_automatica", True))

    nivel_asp = str(aspirante.get("nivel_experiencia") or "desconocido")
    fuente_asp = str(aspirante.get("nivel_experiencia_fuente") or "") or None
    conf_asp = _float_safe(aspirante.get("nivel_experiencia_confianza"), 0.0)
    confirmado_asp = bool(aspirante.get("nivel_experiencia_confirmado_at"))

    nivel_txt, conf_txt, declarado, evidencia = inferir_nivel_desde_texto(texto)
    intencion, conf_int = inferir_intencion(texto)

    # --- Prioridad de nivel ---
    nivel = "desconocido"
    fuente = "inferida"
    confianza = 0.0
    confirmar = False
    persistir_estable = False
    incremento = 0
    respuesta_directa: Optional[str] = None
    accion = "responder_texto"

    if bloqueado and nivel_conv in NIVELES and nivel_conv != "desconocido":
        nivel, fuente, confianza = nivel_conv, fuente_conv or "manual", max(conf_conv, 0.99)
        confirmar = True
    elif fuente_conv == "manual" and confirmado_conv and nivel_conv != "desconocido":
        nivel, fuente, confianza = nivel_conv, "manual", max(conf_conv, 0.95)
        confirmar = True
    elif fuente_asp in {"formulario_ads", "campana"} and nivel_asp != "desconocido":
        nivel, fuente, confianza = nivel_asp, fuente_asp, max(conf_asp, 0.9)
        confirmar = True
        persistir_estable = False  # ya estable
    elif declarado and nivel_txt in {"principiante", "experimentado"}:
        if estrategia == "nivel_fijo" and not permitir_reclass:
            nivel = str(asistente.get("nivel_fijo") or "desconocido")
            fuente, confianza, confirmar = "configuracion_fija", 1.0, True
        else:
            nivel, fuente, confianza = nivel_txt, "declarada", conf_txt
            confirmar = True
            persistir_estable = True
    elif confirmado_asp and nivel_asp != "desconocido":
        nivel, fuente, confianza = nivel_asp, fuente_asp or "declarada", max(conf_asp, 0.85)
        confirmar = True
    elif (
        nivel_txt != "desconocido"
        and conf_txt >= umbral
        and (permitir_reclass or estrategia != "nivel_fijo")
        and not bloqueado
    ):
        if estrategia == "nivel_fijo":
            nivel = str(asistente.get("nivel_fijo") or "desconocido")
            fuente, confianza, confirmar = "configuracion_fija", 1.0, True
        else:
            nivel, fuente, confianza = nivel_txt, "inferida", conf_txt
            confirmar = conf_txt >= umbral
            persistir_estable = confirmar
    elif estrategia == "nivel_fijo":
        nivel = str(asistente.get("nivel_fijo") or "desconocido")
        fuente, confianza, confirmar = "configuracion_fija", 1.0, True
    elif estrategia == "orientada_principiantes":
        # Orientación: guía el tono, NO confirma nivel estable.
        nivel = nivel_conv if nivel_conv != "desconocido" else "desconocido"
        fuente = fuente_conv or "inferida"
        confianza = conf_conv
        confirmar = False
        if es_saludo_o_info_corta(texto):
            respuesta_directa = (
                str(asistente.get("texto_inicio_principiante") or "").strip()
                or str(asistente.get("presentacion_inicial") or "").strip()
                or None
            )
            accion = "responder_informacion"
    elif estrategia == "orientada_experimentados":
        nivel = nivel_conv if nivel_conv != "desconocido" else "desconocido"
        fuente = fuente_conv or "inferida"
        confianza = conf_conv
        confirmar = False
        if es_saludo_o_info_corta(texto):
            respuesta_directa = (
                str(asistente.get("texto_inicio_experimentado") or "").strip()
                or str(asistente.get("presentacion_inicial") or "").strip()
                or None
            )
            accion = "continuar_flujo"
    else:
        # adaptativa
        if nivel_conv != "desconocido":
            nivel, fuente, confianza = nivel_conv, fuente_conv or "inferida", conf_conv
            confirmar = confirmado_conv
        elif es_saludo_o_info_corta(texto) or nivel_txt == "desconocido":
            if (
                preguntar_si_ambiguo
                and preguntas < max_preguntas
                and nivel == "desconocido"
            ):
                accion = "preguntar_nivel"
                incremento = 1
                respuesta_directa = (
                    str(asistente.get("presentacion_inicial") or "").strip()
                    or str(asistente.get("pregunta_clasificacion_nivel") or "").strip()
                    or None
                )
            else:
                pred = str(asistente.get("nivel_predeterminado") or "desconocido")
                nivel, fuente, confianza = pred, "inferida", 0.4
                confirmar = False

    # Acciones por intención (no borran nivel)
    if intencion == "asesor":
        accion = "transferir_humano"
    elif intencion == "bonos":
        accion = "mostrar_bonos"
    elif intencion == "requisitos":
        accion = "mostrar_requisitos"
    elif intencion == "beneficios":
        accion = "mostrar_beneficios"
    elif intencion == "categorias":
        accion = "mostrar_categorias"
    elif intencion in {"incorporacion", "solicitud"}:
        accion = "enviar_solicitud"
    elif intencion == "evidencias":
        accion = "solicitar_evidencias"
    elif accion == "responder_texto" and intencion == "informacion":
        accion = "responder_informacion"

    if estrategia == "nivel_fijo" and not declarado:
        # Impedir que una inferencia débil cambie el fijo.
        nivel = str(asistente.get("nivel_fijo") or nivel)
        fuente = "configuracion_fija"
        confianza = 1.0
        confirmar = True
        persistir_estable = False

    clasificacion = ClasificacionConversacional(
        nivel_experiencia=nivel if nivel in NIVELES else "desconocido",  # type: ignore[arg-type]
        confianza_nivel=round(float(confianza), 3),
        fuente_nivel=fuente if fuente else "inferida",  # type: ignore[arg-type]
        nivel_declarado_explicitamente=bool(declarado),
        evidencia_nivel_breve=evidencia,
        intencion=intencion,  # type: ignore[arg-type]
        confianza_intencion=round(float(conf_int), 3),
        accion_propuesta=accion,  # type: ignore[arg-type]
        respuesta_breve=respuesta_directa,
    )

    ahora = _ahora()
    campos_conv: Dict[str, Any] = {
        "intencion_actual": clasificacion.intencion,
        "intencion_confianza": clasificacion.confianza_intencion,
        "intencion_actualizada_at": ahora,
        "estrategia_nivel_aplicada": estrategia,
        "ultima_clasificacion_at": ahora,
    }
    if incremento:
        campos_conv["preguntas_clasificacion_realizadas"] = preguntas + incremento

    nivel_cambio = clasificacion.nivel_experiencia != nivel_conv or (
        clasificacion.fuente_nivel != (fuente_conv or "")
    )
    if nivel_cambio or clasificacion.nivel_declarado_explicitamente:
        campos_conv.update(
            {
                "nivel_experiencia": clasificacion.nivel_experiencia,
                "nivel_experiencia_fuente": clasificacion.fuente_nivel,
                "nivel_experiencia_confianza": clasificacion.confianza_nivel,
                "nivel_experiencia_confirmado": bool(confirmar),
                "nivel_experiencia_actualizado_at": ahora,
            }
        )

    campos_asp: Dict[str, Any] = {}
    if persistir_estable and not bloqueado and clasificacion.nivel_experiencia != "desconocido":
        campos_asp = {
            "nivel_experiencia": clasificacion.nivel_experiencia,
            "nivel_experiencia_fuente": clasificacion.fuente_nivel,
            "nivel_experiencia_confianza": clasificacion.confianza_nivel,
            "nivel_experiencia_confirmado_at": ahora if confirmar else None,
        }

    intencion_cambio = clasificacion.intencion != intencion_prev
    registrar = nivel_cambio or intencion_cambio or clasificacion.nivel_declarado_explicitamente
    detalle = {
        "nivel_anterior": nivel_conv,
        "nivel_nuevo": clasificacion.nivel_experiencia,
        "fuente": clasificacion.fuente_nivel,
        "confianza": clasificacion.confianza_nivel,
        "intencion_anterior": intencion_prev,
        "intencion_nueva": clasificacion.intencion,
        "estrategia": estrategia,
        "reclasificado": bool(
            nivel_cambio and nivel_conv not in {"desconocido", clasificacion.nivel_experiencia}
        ),
    }

    logger.info(
        "[CLASIFICACION] agencia_id=%s aspirante_id=%s conversacion_id=%s "
        "nivel=%s intencion=%s ruta_accion=%s confianza=%.3f fuente=%s",
        conversacion.get("agencia_id"),
        conversacion.get("aspirante_id") or aspirante.get("id"),
        conversacion.get("id"),
        clasificacion.nivel_experiencia,
        clasificacion.intencion,
        clasificacion.accion_propuesta,
        clasificacion.confianza_nivel,
        clasificacion.fuente_nivel,
    )

    return ResultadoClasificacion(
        clasificacion=clasificacion,
        campos_conversacion=campos_conv,
        campos_aspirante=campos_asp,
        registrar_evento=registrar,
        detalle_evento=detalle,
        persistir_nivel_estable=bool(campos_asp),
        incremento_preguntas=incremento,
        texto_respuesta_directa=respuesta_directa,
    )


def pasos_activos_ordenados(pasos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ordena por flujo_pasos.orden; no hardcodea la ruta experimentada."""
    activos = [p for p in (pasos or []) if p and p.get("activo") is not False]
    return sorted(
        activos,
        key=lambda p: (int(p.get("orden") or 0), int(p.get("id") or 0)),
    )
