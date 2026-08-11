"""
Clasificación adaptativa de nivel e intención (archivo plano, raíz).

Contrato inteligente (tipo_chatbot=inteligente / rutas adaptativas):
- Si estrategia=adaptativa y nivel desconocido → preguntar experiencia primero.
- Textos ambiguos (live, tiktok, sí…) no confirman nivel ni abren agendamiento.
- Declaraciones explícitas confirman principiante/experimentado y habilitan flujo.
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

# Ortografía / typos frecuentes en mensajes de WhatsApp.
_CORRECCIONES_ORTOGRAFIA = (
    (r"\bdsde\b", "desde"),
    (r"\bdesd\b", "desde"),
    (r"\bceroo\b", "cero"),
    (r"\blvies\b", "lives"),
    (r"\btrasmision(?:es)?\b", "transmision"),
    (r"\btrasmisi(?:on|ones)\b", "transmision"),
)

# Negación / sin experiencia: PRIORIDAD sobre cualquier token "realizo/hago".
_PATRONES_PRINCIPIANTE_NEGACION = (
    r"\bno\s+he\s+(hecho|realizado|iniciado|empezado)\b",
    r"\bno\s+he\s+(hecho|realizado)\b.*\b(live|lives|transmisi)",
    r"\bno\s+he\s+(hecho|realizado)\b.*\blives?\b",
    r"\bnunca\s+he\s+(hecho|realizado|iniciado|transmit)",
    r"\bnunca\s+(hice|realice|realic[eé]|transmit)",
    r"\bnunca\b.*\b(live|lives|transmisi)",
    r"\bno\s+tengo\s+(ninguna\s+)?(clase\s+de\s+)?experiencia",
    r"\bninguna\s+(clase\s+de\s+)?experiencia",
    r"\bsin\s+(ninguna\s+)?experiencia",
    r"\bno\s+tengo\s+ninguna",
    r"\bno\s+realizo\b",
    r"\bno\s+hago\s+(live|lives|transmisi)",
    r"\bno\s+transmit",
    r"\btodavia\s+no\b",
    r"\baun\s+no\b",
    r"\bni\s+(he\s+)?realizado\b",
    r"\bni\s+(he\s+)?hecho\b.*\b(live|lives|transmisi)",
)

_PATRONES_PRINCIPIANTE_INICIO = (
    r"\b(comenzar|empezar|iniciar|arran?car)\s+desde\s+cero\b",
    r"\bquiero\s+(comenzar|empezar|iniciar)\s+desde\s+cero\b",
    r"\bquiero\s+(comenzar|empezar|iniciar)\b",
    r"\bdesde\s+cero\b",
    r"\bsoy\s+nuev[oa]\b",
    r"\bprincipiante\b",
    r"\bquiero\s+aprender\b",
    r"\bno\s+s[eé]\s+(hacer|como\s+hacer)\s+live",
    r"\bno\s+s[eé]\s+c[oó]mo\b",
)

# Experiencia afirmativa (solo si NO hubo negación previa).
_PATRONES_EXPERIMENTADO = (
    r"\bya\s+(hago|realizo|transmito|transmitiendo)\b",
    r"\bya\s+hago\s+lives?\b",
    r"\bya\s+realizo\s+transmisi",
    r"\bhago\s+lives?\b",
    r"\bhago\s+transmisi",
    r"\brealizo\s+transmisi",
    r"\btengo\s+experiencia\b",
    r"\bhago\s+live\s+(desde|hace)\b",
    r"\bllevo\s+.+\s+(mes|meses|ano|anos|semana|semanas)\b",
    r"\bdesde\s+hace\b",
    r"\btransmito\s+(actualmente|ahora|ya|hace|desde)\b",
    r"\bya\s+soy\s+creador\b",
    r"\bsoy\s+creador\s+live\b",
    r"\bya\s+transmit",
    r"\bexperiencia\s+con\s+live\b",
)

_PATRONES_RESPUESTA_CORTA_PRINCIPIANTE = frozenset(
    {
        "no",
        "nop",
        "nel",
        "nao",
        "nunca",
        "para nada",
        "negativo",
        "desde cero",
        "cero",
    }
)
_PATRONES_RESPUESTA_CORTA_EXPERIMENTADO = frozenset(
    {
        "si",
        "sip",
        "sep",
        "claro",
        "afirmativo",
        "exacto",
        "asi es",
        "asi mismo",
    }
)
_PATRONES_YA_RESPONDIDO_NEGATIVO = (
    r"\bya\s+(te\s+)?dije\s+que\s+no\b",
    r"\bte\s+dije\s+que\s+no\b",
    r"\bya\s+(te\s+)?lo\s+dije\b",
    r"\bcomo\s+(ya\s+)?dije\b",
    r"\bya\s+respondi\b",
    r"\blo\s+mismo\b",
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
_TEXTOS_AMBIGUOS_NIVEL = frozenset(
    {
        "live",
        "lives",
        "tiktok",
        "tik tok",
        "transmision",
        "transmisión",
        "transmisiones",
        "si",
        "sí",
        "no",
        "ok",
        "okay",
        "vale",
        "no se",
        "no sé",
        "nose",
        "tal vez",
        "quizas",
        "quizá",
        "quiza",
        "mas o menos",
        "más o menos",
    }
)

TEXTO_ACLARACION_NIVEL = (
    "Para orientarte bien, ¿ya has realizado transmisiones LIVE o quieres "
    "comenzar desde cero?"
)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _normalizar(texto: str) -> str:
    valor = str(texto or "").strip().lower()
    valor = unicodedata.normalize("NFD", valor)
    valor = "".join(ch for ch in valor if unicodedata.category(ch) != "Mn")
    valor = re.sub(r"[^\w\s]", " ", valor, flags=re.UNICODE)
    valor = re.sub(r"\s+", " ", valor).strip()
    for patron, repl in _CORRECCIONES_ORTOGRAFIA:
        valor = re.sub(patron, repl, valor)
    return valor


def _coincide(texto: str, patrones: Tuple[str, ...]) -> bool:
    return any(re.search(p, texto) for p in patrones)


def _pregunta_nivel_pendiente(conversacion: Optional[Dict[str, Any]]) -> bool:
    conv = conversacion or {}
    ctx = conv.get("contexto") or {}
    if isinstance(ctx, str):
        try:
            import json

            ctx = json.loads(ctx)
        except Exception:  # noqa: BLE001
            ctx = {}
    if not isinstance(ctx, dict):
        return False
    pendiente = ctx.get("pregunta_pendiente") or {}
    if not isinstance(pendiente, dict):
        return False
    campo = str(pendiente.get("campo") or "").lower()
    return campo in {"nivel_experiencia", "experiencia", "clasificacion_nivel"}


def _nivel_desde_respuesta_corta(n: str) -> Optional[str]:
    if not n:
        return None
    if _coincide(n, _PATRONES_YA_RESPONDIDO_NEGATIVO):
        return "principiante"
    if n in _PATRONES_RESPUESTA_CORTA_PRINCIPIANTE:
        return "principiante"
    if n in _PATRONES_RESPUESTA_CORTA_EXPERIMENTADO:
        return "experimentado"
    return None


def _es_principiante_deterministico(n: str) -> Tuple[bool, str]:
    if n in {"nunca", "principiante", "desde cero", "cero"}:
        return True, "deterministico_inicio"
    if _coincide(n, _PATRONES_PRINCIPIANTE_NEGACION):
        return True, "deterministico_negacion"
    if _coincide(n, _PATRONES_PRINCIPIANTE_INICIO):
        return True, "deterministico_inicio"
    # “ninguna … lives/experiencia” sin verbos exactos.
    if "ninguna" in n and (
        "experiencia" in n or "live" in n or "transmisi" in n
    ):
        return True, "deterministico_negacion"
    return False, ""


def _es_experimentado_deterministico(n: str) -> Tuple[bool, str]:
    # Seguridad: si hay negación clara, nunca experimentado.
    if _coincide(n, _PATRONES_PRINCIPIANTE_NEGACION):
        return False, ""
    if re.search(r"\bno\s+(tengo|he|hago|realizo|transmit)", n):
        return False, ""
    if _coincide(n, _PATRONES_EXPERIMENTADO):
        return True, "deterministico_experiencia"
    return False, ""


def _clasificar_nivel_con_ia(texto: str) -> Optional[Tuple[str, float, str]]:
    """Fallback semántico: solo nivel + confianza. No genera respuesta."""
    import json
    import os

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not str(api_key).strip():
        return None
    system = (
        "Clasifica la experiencia en transmisiones LIVE / TikTok LIVE del usuario. "
        "Responde SOLO JSON: "
        '{"nivel":"principiante|experimentado|desconocido","confianza":0.0-1.0}. '
        "principiante = sin experiencia o quiere comenzar desde cero. "
        "experimentado = ya transmite o tiene experiencia real. "
        "desconocido = ambiguo. No inventes. No escribas nada más."
    )
    try:
        from openai import OpenAI

        client = OpenAI(api_key=str(api_key).strip())
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": str(texto or "")[:500]},
            ],
            max_tokens=60,
        )
        data = json.loads((resp.choices[0].message.content or "{}").strip() or "{}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CHATBOT_CLASIFICACION] fallback_ia_error=%s", exc)
        return None
    nivel = str(data.get("nivel") or "desconocido").strip().lower()
    if nivel not in {"principiante", "experimentado", "desconocido"}:
        nivel = "desconocido"
    try:
        conf = float(data.get("confianza") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    if nivel == "desconocido" or conf < 0.80:
        return None
    return nivel, conf, "ia_semantica"


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


def es_texto_ambiguo_nivel(texto: str) -> bool:
    """Palabras sueltas que no confirman experiencia LIVE."""
    n = _normalizar(texto)
    if not n:
        return True
    if n in _TEXTOS_AMBIGUOS_NIVEL:
        return True
    # Una sola palabra corta genérica
    tokens = n.split()
    if len(tokens) == 1 and tokens[0] in {
        "live",
        "lives",
        "tiktok",
        "transmision",
        "si",
        "no",
        "ok",
    }:
        return True
    return False


def construir_pregunta_clasificacion(asistente: Optional[Dict[str, Any]]) -> str:
    """Saludo + pregunta de nivel para chatbot INTELIGENTE (sin menú informativo)."""
    a = asistente or {}
    pregunta = str(a.get("pregunta_clasificacion_nivel") or "").strip()
    if not pregunta:
        pregunta = "¿Ya has realizado transmisiones LIVE?"

    presentacion = _presentacion_saludo_inteligente(a)
    if presentacion and pregunta not in presentacion:
        return f"{presentacion}\n\n{pregunta}"
    return pregunta or TEXTO_ACLARACION_NIVEL


def _presentacion_saludo_inteligente(asistente: Dict[str, Any]) -> str:
    """
    Presentación del saludo inteligente: no reutiliza frases de menú informativo
    («elige una opción», «escribe el número», etc.).
    """
    crudo = str(asistente.get("presentacion_inicial") or "").strip()
    if not crudo:
        nombre = str(
            asistente.get("nombre_asistente") or "la agencia"
        ).strip() or "la agencia"
        return (
            f"¡Hola! 👋 Bienvenido(a) a {nombre}.\n"
            "Estoy aquí para orientarte y ayudarte a encontrar el proceso "
            "más adecuado para ti."
        )

    lineas_ok: List[str] = []
    for linea in crudo.splitlines():
        n = _normalizar(linea)
        if not n:
            if lineas_ok and lineas_ok[-1] != "":
                lineas_ok.append("")
            continue
        if any(
            x in n
            for x in (
                "elige una opcion",
                "elegir una opcion",
                "elige un numero",
                "escribe el numero",
                "escribe un numero",
                "volver al menu",
                "ver el menu",
                "opciones del menu",
            )
        ):
            continue
        lineas_ok.append(linea.rstrip())

    texto = "\n".join(lineas_ok).strip()
    if not texto:
        nombre = str(
            asistente.get("nombre_asistente") or "la agencia"
        ).strip() or "la agencia"
        return (
            f"¡Hola! 👋 Bienvenido(a) a {nombre}.\n"
            "Estoy aquí para orientarte y ayudarte a encontrar el proceso "
            "más adecuado para ti."
        )
    return texto


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


def inferir_nivel_desde_texto(
    texto: str,
    *,
    pregunta_nivel_pendiente: bool = False,
    usar_ia: bool = True,
) -> Tuple[str, float, bool, Optional[str]]:
    """
    Retorna (nivel, confianza, declarado_explicitamente, evidencia_breve).

    Orden:
    1) respuesta corta a pregunta de nivel pendiente (sí/no / ya dije que no)
    2) principiante por NEGACIÓN o inicio desde cero (prioridad)
    3) experimentado afirmativo
    4) fallback IA semántico (solo nivel)
    """
    n = _normalizar(texto)
    if not n:
        return "desconocido", 0.1, False, None

    # Ambiguos sueltos solo si NO estamos contestando la pregunta de nivel.
    if not pregunta_nivel_pendiente and es_texto_ambiguo_nivel(texto):
        return "desconocido", 0.1, False, None

    if pregunta_nivel_pendiente:
        corto = _nivel_desde_respuesta_corta(n)
        if corto:
            logger.info(
                "[CHATBOT_CLASIFICACION] texto=%s nivel=%s metodo=respuesta_corta_pendiente confianza=1.0",
                n[:120],
                corto,
            )
            return corto, 1.0, True, n[:180]

    ok_p, metodo_p = _es_principiante_deterministico(n)
    if ok_p:
        logger.info(
            "[CHATBOT_CLASIFICACION] texto=%s nivel=principiante metodo=%s confianza=1.0",
            n[:120],
            metodo_p,
        )
        return "principiante", 1.0, True, n[:180]

    ok_e, metodo_e = _es_experimentado_deterministico(n)
    if ok_e:
        logger.info(
            "[CHATBOT_CLASIFICACION] texto=%s nivel=experimentado metodo=%s confianza=0.95",
            n[:120],
            metodo_e,
        )
        return "experimentado", 0.95, True, n[:180]

    if usar_ia and not es_texto_ambiguo_nivel(texto):
        ia = _clasificar_nivel_con_ia(texto)
        if ia:
            nivel_ia, conf_ia, metodo_ia = ia
            logger.info(
                "[CHATBOT_CLASIFICACION] texto=%s nivel=%s metodo=%s confianza=%.2f",
                n[:120],
                nivel_ia,
                metodo_ia,
                conf_ia,
            )
            return nivel_ia, conf_ia, True, n[:180]

    return "desconocido", 0.2, False, None


def usar_rutas_adaptativas(configuracion: Optional[Dict[str, Any]]) -> bool:
    """
    Clasificación + flujo del chatbot inteligente.

    Fuente principal: tipo_chatbot. Flags legacy solo si el tipo no es válido.
    """
    from chatbot_tipo import TIPO_INTELIGENTE, TIPO_INFORMATIVO, resolver_tipo_chatbot

    cfg = configuracion or {}
    tipo = resolver_tipo_chatbot(cfg)
    if tipo == TIPO_INTELIGENTE:
        return True
    if tipo == TIPO_INFORMATIVO:
        return False
    return bool(cfg.get("usar_asistente_conversacional")) and bool(
        cfg.get("usar_rutas_adaptativas")
    )


def nivel_resuelto(conversacion: Optional[Dict[str, Any]], aspirante: Optional[Dict[str, Any]] = None) -> str:
    conv = conversacion or {}
    asp = aspirante or {}
    for fuente in (conv, asp):
        nivel = str(fuente.get("nivel_experiencia") or "desconocido").lower()
        if nivel in {"principiante", "experimentado"}:
            confirmado = bool(
                fuente.get("nivel_experiencia_confirmado")
                or fuente.get("nivel_experiencia_confirmado_at")
                or str(fuente.get("nivel_experiencia_fuente") or "") in FUENTES_ESTABLES
            )
            conf = 0.0
            try:
                conf = float(fuente.get("nivel_experiencia_confianza") or 0)
            except (TypeError, ValueError):
                conf = 0.0
            if confirmado or conf >= 0.75:
                return nivel
    return "desconocido"


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
    seleccionar_flujo: bool = False


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
    max_preguntas = max(1, int(asistente.get("max_preguntas_clasificacion") or 3))
    preguntar_si_ambiguo = bool(asistente.get("preguntar_nivel_si_ambiguo", True))
    permitir_reclass = bool(asistente.get("permitir_reclasificacion_automatica", True))

    nivel_asp = str(aspirante.get("nivel_experiencia") or "desconocido")
    fuente_asp = str(aspirante.get("nivel_experiencia_fuente") or "") or None
    conf_asp = _float_safe(aspirante.get("nivel_experiencia_confianza"), 0.0)
    confirmado_asp = bool(aspirante.get("nivel_experiencia_confirmado_at"))

    pendiente_nivel = _pregunta_nivel_pendiente(conversacion)
    nivel_txt, conf_txt, declarado, evidencia = inferir_nivel_desde_texto(
        texto,
        pregunta_nivel_pendiente=pendiente_nivel,
        usar_ia=True,
    )
    intencion, conf_int = inferir_intencion(texto)
    ambiguo = es_texto_ambiguo_nivel(texto) and not pendiente_nivel
    # Si hay pregunta de nivel pendiente, "sí/no" ya no son ambiguos sueltos.
    if pendiente_nivel and _nivel_desde_respuesta_corta(_normalizar(texto)):
        ambiguo = False


    # --- Prioridad de nivel ---
    nivel = "desconocido"
    fuente = "inferida"
    confianza = 0.0
    confirmar = False
    persistir_estable = False
    incremento = 0
    respuesta_directa: Optional[str] = None
    accion = "responder_texto"
    seleccionar_flujo = False

    if bloqueado and nivel_conv in NIVELES and nivel_conv != "desconocido":
        nivel, fuente, confianza = nivel_conv, fuente_conv or "manual", max(conf_conv, 0.99)
        confirmar = True
    elif fuente_conv == "manual" and confirmado_conv and nivel_conv != "desconocido":
        nivel, fuente, confianza = nivel_conv, "manual", max(conf_conv, 0.95)
        confirmar = True
    elif fuente_asp in {"formulario_ads", "campana"} and nivel_asp != "desconocido":
        nivel, fuente, confianza = nivel_asp, fuente_asp, max(conf_asp, 0.9)
        confirmar = True
        persistir_estable = False
    elif declarado and nivel_txt in {"principiante", "experimentado"}:
        if estrategia == "nivel_fijo" and not permitir_reclass:
            nivel = str(asistente.get("nivel_fijo") or "desconocido")
            fuente, confianza, confirmar = "configuracion_fija", 1.0, True
        else:
            nivel, fuente, confianza = nivel_txt, "declarada", conf_txt
            confirmar = True
            persistir_estable = True
            seleccionar_flujo = True
            if nivel == "principiante":
                accion = "orientar_principiante"
                respuesta_directa = (
                    str(asistente.get("texto_inicio_principiante") or "").strip()
                    or (
                        "Perfecto. Como estás comenzando, te voy a orientar paso a paso: "
                        "primero te explico cómo funciona TikTok LIVE y qué necesitas, "
                        "sin pedirte todavía una prueba LIVE."
                    )
                )
            else:
                accion = "orientar_experimentado"
                respuesta_directa = (
                    str(asistente.get("texto_inicio_experimentado") or "").strip()
                    or (
                        "Gracias. Como ya tienes experiencia con LIVE, te guío con el "
                        "proceso directo de la agencia."
                    )
                )
    elif confirmado_asp and nivel_asp != "desconocido":
        nivel, fuente, confianza = nivel_asp, fuente_asp or "declarada", max(conf_asp, 0.85)
        confirmar = True
    elif (
        nivel_txt != "desconocido"
        and conf_txt >= umbral
        and declarado
        and (permitir_reclass or estrategia != "nivel_fijo")
        and not bloqueado
    ):
        nivel, fuente, confianza = nivel_txt, "declarada", conf_txt
        confirmar = True
        persistir_estable = True
        seleccionar_flujo = True
    elif estrategia == "nivel_fijo":
        nivel = str(asistente.get("nivel_fijo") or "desconocido")
        fuente, confianza, confirmar = "configuracion_fija", 1.0, True
        if es_saludo_o_info_corta(texto):
            if nivel == "principiante":
                accion = "orientar_principiante"
                respuesta_directa = (
                    str(asistente.get("texto_inicio_principiante") or "").strip()
                    or str(asistente.get("presentacion_inicial") or "").strip()
                    or None
                )
            elif nivel == "experimentado":
                accion = "orientar_experimentado"
                respuesta_directa = (
                    str(asistente.get("texto_inicio_experimentado") or "").strip()
                    or str(asistente.get("presentacion_inicial") or "").strip()
                    or None
                )
            else:
                respuesta_directa = (
                    str(asistente.get("presentacion_inicial") or "").strip() or None
                )
    elif estrategia == "orientada_principiantes":
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
            accion = "orientar_principiante"
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
            accion = "orientar_experimentado"
    else:
        # adaptativa
        if nivel_conv in {"principiante", "experimentado"} and (
            confirmado_conv or conf_conv >= umbral
        ):
            nivel, fuente, confianza = nivel_conv, fuente_conv or "inferida", conf_conv
            confirmar = confirmado_conv or conf_conv >= umbral
        elif es_saludo_o_info_corta(texto):
            accion = "preguntar_nivel"
            incremento = 1 if preguntas < max_preguntas else 0
            respuesta_directa = construir_pregunta_clasificacion(asistente)
        elif ambiguo or (nivel_txt == "desconocido" and not declarado):
            if preguntar_si_ambiguo:
                accion = "aclarar_nivel"
                respuesta_directa = TEXTO_ACLARACION_NIVEL
                # Aclaración no agota el cupo de clasificación.
                incremento = 0
            else:
                pred = str(asistente.get("nivel_predeterminado") or "desconocido")
                if pred in {"principiante", "experimentado"}:
                    nivel, fuente, confianza = pred, "inferida", 0.4
                    confirmar = False

    # Intenciones informativas / asesor: no sustituyen la clasificación pendiente.
    nivel_abierto = nivel in {"desconocido", ""} and not confirmar
    if intencion == "asesor":
        accion = "transferir_humano"
    elif intencion in {"bonos", "requisitos", "beneficios", "categorias"} and (
        nivel_abierto or accion in {"preguntar_nivel", "aclarar_nivel"}
    ):
        # Se responde info + se retoma pregunta (capa superior).
        mapa = {
            "bonos": "mostrar_bonos",
            "requisitos": "mostrar_requisitos",
            "beneficios": "mostrar_beneficios",
            "categorias": "mostrar_categorias",
        }
        accion = mapa[intencion]
    elif nivel_abierto and intencion in {"incorporacion", "solicitud", "evidencias"}:
        # No saltar a solicitud/evidencias/live sin nivel.
        accion = "aclarar_nivel"
        respuesta_directa = TEXTO_ACLARACION_NIVEL
    elif not nivel_abierto:
        if intencion == "bonos":
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
    registrar = (
        nivel_cambio
        or intencion_cambio
        or clasificacion.nivel_declarado_explicitamente
        or accion in {"preguntar_nivel", "aclarar_nivel"}
    )
    detalle = {
        "nivel_anterior": nivel_conv,
        "nivel_nuevo": clasificacion.nivel_experiencia,
        "fuente": clasificacion.fuente_nivel,
        "confianza": clasificacion.confianza_nivel,
        "intencion_anterior": intencion_prev,
        "intencion_nueva": clasificacion.intencion,
        "estrategia": estrategia,
        "ambiguo": ambiguo,
        "reclasificado": bool(
            nivel_cambio and nivel_conv not in {"desconocido", clasificacion.nivel_experiencia}
        ),
    }

    logger.info(
        "[CLASIFICACION] agencia_id=%s aspirante_id=%s conversacion_id=%s "
        "nivel=%s intencion=%s ruta_accion=%s confianza=%.3f fuente=%s ambiguo=%s",
        conversacion.get("agencia_id"),
        conversacion.get("aspirante_id") or aspirante.get("id"),
        conversacion.get("id"),
        clasificacion.nivel_experiencia,
        clasificacion.intencion,
        clasificacion.accion_propuesta,
        clasificacion.confianza_nivel,
        clasificacion.fuente_nivel,
        ambiguo,
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
        seleccionar_flujo=seleccionar_flujo,
    )


def pasos_activos_ordenados(pasos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ordena por flujo_pasos.orden; no hardcodea la ruta experimentada."""
    activos = [p for p in (pasos or []) if p and p.get("activo") is not False]
    return sorted(
        activos,
        key=lambda p: (int(p.get("orden") or 0), int(p.get("id") or 0)),
    )
