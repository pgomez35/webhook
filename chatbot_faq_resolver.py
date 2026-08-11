"""
Resolución de FAQ para el chatbot informativo.

FAQ = base de conocimiento interna (faq_conversacional).
La IA solo elige entre candidatas autorizadas; no inventa contenido ni navega web.
"""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("uvicorn.error")

UMBRAL_LEXICO = 18
UMBRAL_IA = 0.80
MAX_CANDIDATAS_IA = 8

RESULTADO_ENCONTRADA = "encontrada"
RESULTADO_SIN_CONOCIMIENTO = "sin_conocimiento"
RESULTADO_NO_ENTENDIDO = "no_entendido"

# Sinónimos controlados (no mezclar monetizar con «no puedo iniciar live»).
SINONIMOS: Dict[str, Tuple[str, ...]] = {
    "monetizacion": (
        "monetizar",
        "monetizacion",
        "monetizo",
        "monetiza",
        "ganar dinero",
        "ingresos",
        "ganancias",
        "como gano",
        "cuanto gano",
        "cuanto puedo ganar",
    ),
    "regalos": ("regalo", "regalos", "gift", "gifts"),
    "diamantes": ("diamante", "diamantes", "diamond", "diamonds"),
    "cobro": ("cobra", "cobran", "cobro", "costo", "gratis", "ingresar"),
    "experiencia": ("experiencia", "principiante", "empezar", "sin experiencia"),
}

_STOP = frozenset(
    {
        "como",
        "que",
        "cual",
        "cuales",
        "cuando",
        "donde",
        "porque",
        "para",
        "por",
        "con",
        "sin",
        "una",
        "unos",
        "unas",
        "sobre",
        "esta",
        "este",
        "esto",
        "tiene",
        "tienen",
        "puedo",
        "puede",
        "quiero",
        "saber",
        "dime",
        "explica",
        "explicame",
        "es",
        "la",
        "el",
        "los",
        "las",
        "de",
        "del",
        "se",
        "me",
        "te",
        "mi",
        "tu",
        "su",
        "al",
        "lo",
        "hay",
        "son",
        "mas",
        "muy",
        "hacer",
        "haciendo",
        "hago",
        "hay",
        "the",
        "and",
        "live",
        "lives",
        "tiktok",
    }
)

# Tokens que NO deben empujar FAQs de fallo técnico hacia monetización.
_TEMAS_PROBLEMA_LIVE = frozenset(
    {
        "iniciar",
        "inicio",
        "abre",
        "abrir",
        "error",
        "falla",
        "fallo",
        "bloqueado",
        "bloqueo",
        "permiso",
        "no puedo",
        "no deja",
        "no me deja",
    }
)


def normalizar(texto: str) -> str:
    valor = str(texto or "").strip().lower()
    valor = unicodedata.normalize("NFD", valor)
    valor = "".join(ch for ch in valor if unicodedata.category(ch) != "Mn")
    valor = re.sub(r"[^\w\s]", " ", valor, flags=re.UNICODE)
    return re.sub(r"\s+", " ", valor).strip()


def limpiar_consulta(texto: str) -> str:
    n = normalizar(texto)
    n = re.sub(r"^(pregunta|preguntas|q)\s+", "", n)
    return n.strip()


def tokens_utiles(texto_n: str) -> List[str]:
    return [t for t in str(texto_n or "").split() if len(t) > 3 and t not in _STOP]


def _vigente(registro: Dict[str, Any], hoy: Optional[date] = None) -> bool:
    if registro.get("activo") is False:
        return False
    referencia = hoy or date.today()
    desde = registro.get("vigencia_desde")
    hasta = registro.get("vigencia_hasta")
    try:
        if desde and str(desde)[:10] > referencia.isoformat():
            return False
        if hasta and str(hasta)[:10] < referencia.isoformat():
            return False
    except Exception:
        return True
    return True


def es_ruido_o_ambiguo(texto: str) -> bool:
    """NO_ENTENDIDO: basura o mensajes sin contenido semántico."""
    crudo = str(texto or "").strip()
    if not crudo:
        return True
    n = limpiar_consulta(crudo)
    if not n:
        return True
    if len(n) <= 2:
        return True
    toks = tokens_utiles(n)
    # Solo caracteres repetidos / teclado aleatorio
    if re.fullmatch(r"(.)\1{3,}", n.replace(" ", "")):
        return True
    compact = n.replace(" ", "")
    if re.fullmatch(r"[asdfghjklñ]+", compact) or re.fullmatch(
        r"[qwertyuiop]+", compact
    ) or re.fullmatch(r"[zxcvbnm]+", compact):
        return True
    if len(n) >= 6 and not toks and not any(ch.isalpha() for ch in n):
        return True
    # Tokens sin vocales (qwrtyp, zxcvbn) → basura
    vocales = set("aeiou")
    if toks and all(
        len(t) >= 5 and not any(c in vocales for c in t) for t in toks
    ):
        return True
    # Muy corto sin tokens útiles y sin signos de pregunta
    if len(n.split()) <= 1 and not toks and "?" not in crudo and "¿" not in crudo:
        if n in {"eso", "esto", "lo", "otro", "hola", "ok", "si", "no"}:
            return True
    return False


def detectar_categoria_estructurada(texto: str) -> Optional[str]:
    """requisitos | beneficios | bonos antes de FAQ genérica."""
    n = limpiar_consulta(texto)
    if not n:
        return None
    # Preguntas específicas no deben abrir listados
    if any(
        x in n
        for x in (
            "monetiz",
            "regalo",
            "gift",
            "diamant",
            "cobra",
            "experiencia",
            "ganar dinero",
        )
    ):
        return None
    if any(x in n for x in ("requisito", "requisitos", "necesito para", "edad minima")):
        return "requisitos"
    if any(x in n for x in ("bono", "bonos", "incentivo", "incentivos")):
        return "bonos"
    if any(x in n for x in ("beneficio", "beneficios", "ventaja", "ventajas")):
        return "beneficios"
    return None


def _expande_sinonimos(consulta_n: str) -> List[str]:
    extra: List[str] = []
    for _grupo, variantes in SINONIMOS.items():
        if any(v in consulta_n for v in variantes):
            extra.extend(variantes)
    return list(dict.fromkeys(extra))


def _tokens_compatibles(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 5 and len(b) >= 5 and (a.startswith(b[:5]) or b.startswith(a[:5])):
        return True
    return False


def _tema_problema_live(texto_n: str) -> bool:
    return any(t in texto_n for t in _TEMAS_PROBLEMA_LIVE)


def _tema_monetizacion(texto_n: str) -> bool:
    return any(
        v in texto_n
        for v in SINONIMOS["monetizacion"]
    ) or "monetiz" in texto_n


def score_faq_lexico(consulta: str, faq: Dict[str, Any]) -> int:
    """Score léxico estricto; evita cruzar monetizar con fallos de LIVE."""
    consulta_n = limpiar_consulta(consulta)
    pregunta = limpiar_consulta(str(faq.get("pregunta") or ""))
    if not consulta_n:
        return 0

    # Penalización dura: monetización vs problema al iniciar LIVE
    faq_n = f"{pregunta} {normalizar(str(faq.get('codigo') or ''))} {normalizar(str(faq.get('intencion') or ''))}"
    if _tema_monetizacion(consulta_n) and _tema_problema_live(faq_n) and not _tema_monetizacion(faq_n):
        return 0
    if _tema_problema_live(consulta_n) and _tema_monetizacion(faq_n) and not _tema_problema_live(faq_n):
        return 0

    score = 0
    if pregunta:
        if pregunta == consulta_n:
            score += 50
        elif pregunta in consulta_n or consulta_n in pregunta:
            # Contención total solo si hay solape de tokens útiles
            toks_c = set(tokens_utiles(consulta_n))
            toks_p = set(tokens_utiles(pregunta))
            if toks_c & toks_p:
                score += 22

        toks_c = tokens_utiles(consulta_n)
        toks_p = tokens_utiles(pregunta)
        usados = set()
        for tc in toks_c:
            for tp in toks_p:
                if tp in usados:
                    continue
                if _tokens_compatibles(tc, tp):
                    score += 14 if tc == tp and len(tc) >= 6 else (10 if min(len(tc), len(tp)) >= 6 else 4)
                    usados.add(tp)
                    break
        if len(usados) >= 2:
            score += 8
        if len(usados) >= 3:
            score += 6

    # Sinónimos controlados
    for variante in _expande_sinonimos(consulta_n):
        vn = normalizar(variante)
        if len(vn) < 4:
            continue
        if vn in pregunta or any(_tokens_compatibles(vn, t) for t in tokens_utiles(pregunta)):
            score += 8
        claves = faq.get("palabras_clave") or []
        if isinstance(claves, str):
            claves = [c.strip() for c in claves.split(",") if c.strip()]
        for c in claves:
            cn = normalizar(str(c))
            if cn and (vn == cn or _tokens_compatibles(vn, cn) or vn in cn or cn in vn):
                score += 6

    # palabras_clave explícitas
    claves = faq.get("palabras_clave") or []
    if isinstance(claves, str):
        claves = [c.strip() for c in claves.split(",") if c.strip()]
    for c in claves:
        cn = normalizar(str(c))
        if not cn or cn in _STOP:
            continue
        if cn in consulta_n:
            score += 10 if len(cn) >= 5 else 4
        else:
            for tc in tokens_utiles(consulta_n):
                if _tokens_compatibles(tc, cn):
                    score += 7
                    break

    # intencion / categoria / codigo
    for campo in ("intencion", "categoria", "codigo"):
        val = normalizar(str(faq.get(campo) or "").replace("_", " "))
        if val and len(val) >= 4 and (val in consulta_n or any(t in val for t in tokens_utiles(consulta_n))):
            score += 5

    return score


def rankear_faqs(consulta: str, faqs: List[Dict[str, Any]]) -> List[Tuple[int, Dict[str, Any]]]:
    ranked: List[Tuple[int, Dict[str, Any]]] = []
    for faq in faqs or []:
        if not _vigente(faq):
            continue
        # Evitar tratar bloques de proceso como FAQ de conocimiento
        pregunta = str(faq.get("pregunta") or "")
        if _parece_bloque_proceso(pregunta, faq):
            continue
        sc = score_faq_lexico(consulta, faq)
        if sc > 0:
            ranked.append((sc, faq))
    ranked.sort(key=lambda x: (-x[0], -int((x[1].get("prioridad") or 0))))
    return ranked


def _parece_bloque_proceso(pregunta: str, faq: Dict[str, Any]) -> bool:
    """Detecta textos de flujo/pasos mal cargados como FAQ."""
    p = str(pregunta or "")
    n = normalizar(p)
    if "presentar la oportunidad" in n and "agendar" in n:
        return True
    if n.count("1.") + n.count("2.") + n.count("3.") >= 3 and len(p) > 200:
        return True
    codigo = normalizar(str(faq.get("codigo") or ""))
    if "proceso" in codigo and "ingreso" in codigo:
        return True
    return False


def seleccionar_faq_con_ia(
    consulta: str,
    candidatas: List[Dict[str, Any]],
    *,
    modelo: Optional[str] = None,
) -> Dict[str, Any]:
    """
    La IA solo elige id entre candidatas. No genera respuesta libre.
    Retorna {faq_id, confianza, motivo}.
    """
    vacio = {"faq_id": None, "confianza": 0.0, "motivo": "sin_candidatas"}
    if not candidatas:
        return vacio
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not str(api_key).strip():
        return {"faq_id": None, "confianza": 0.0, "motivo": "openai_no_configurado"}

    items = []
    for faq in candidatas[:MAX_CANDIDATAS_IA]:
        items.append(
            {
                "faq_id": faq.get("id"),
                "pregunta": str(faq.get("pregunta") or "")[:300],
                "codigo": faq.get("codigo"),
                "categoria": faq.get("categoria"),
                "intencion": faq.get("intencion"),
            }
        )
    system = (
        "Eres un selector de FAQ para un chatbot informativo. "
        "Debes elegir SOLO entre las candidatas dadas. "
        "Si ninguna responde realmente la pregunta del usuario, faq_id=null. "
        "NO inventes información. NO uses conocimiento externo. "
        "Responde SOLO JSON: "
        '{"faq_id": <int|null>, "confianza": <0..1>, "motivo": "<texto corto>"}.'
    )
    user = json.dumps(
        {"pregunta_usuario": consulta, "candidatas": items},
        ensure_ascii=False,
    )[:8000]
    try:
        from openai import OpenAI

        client = OpenAI(api_key=str(api_key).strip())
        resp = client.chat.completions.create(
            model=modelo or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=200,
        )
        data = json.loads((resp.choices[0].message.content or "{}").strip() or "{}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CHATBOT_FAQ] seleccion IA falló: %s", exc)
        return {"faq_id": None, "confianza": 0.0, "motivo": f"error_ia:{exc}"}

    ids_ok = {int(f["id"]) for f in candidatas if f.get("id") is not None}
    faq_id = data.get("faq_id")
    try:
        faq_id_int = int(faq_id) if faq_id is not None else None
    except (TypeError, ValueError):
        faq_id_int = None
    if faq_id_int is not None and faq_id_int not in ids_ok:
        faq_id_int = None
    try:
        confianza = float(data.get("confianza") or 0.0)
    except (TypeError, ValueError):
        confianza = 0.0
    confianza = max(0.0, min(1.0, confianza))
    return {
        "faq_id": faq_id_int,
        "confianza": confianza,
        "motivo": str(data.get("motivo") or "")[:240],
    }


def texto_respuesta_faq(faq: Dict[str, Any], *, preferir_corta: bool = False) -> str:
    corta = str(faq.get("respuesta_corta") or "").strip()
    completa = str(faq.get("respuesta_completa") or "").strip()
    if preferir_corta and corta:
        return corta
    return completa or corta


def resolver_faq(
    texto: str,
    faqs: List[Dict[str, Any]],
    *,
    usar_ia: bool = True,
    umbral_lexico: int = UMBRAL_LEXICO,
    umbral_ia: float = UMBRAL_IA,
) -> Dict[str, Any]:
    """
    Resuelve una consulta libre contra faq_conversacional.

    resultado ∈ {encontrada, sin_conocimiento, no_entendido}
    """
    consulta = str(texto or "").strip()
    norma = limpiar_consulta(consulta)
    base = {
        "resultado": RESULTADO_SIN_CONOCIMIENTO,
        "faq": None,
        "faq_id": None,
        "confianza": 0.0,
        "metodo": None,
        "motivo": None,
        "texto_normalizado": norma,
        "intencion_detectada": detectar_intencion_tema(consulta),
        "candidatas": 0,
        "requiere_humano": False,
        "respuesta": None,
    }

    if es_ruido_o_ambiguo(consulta):
        base["resultado"] = RESULTADO_NO_ENTENDIDO
        base["metodo"] = "ruido"
        base["motivo"] = "mensaje_ambiguo"
        _log_faq(base)
        return base

    ranked = rankear_faqs(consulta, faqs)
    base["candidatas"] = len(ranked)

    # Match léxico claro
    if ranked and ranked[0][0] >= umbral_lexico:
        # Exigir margen si hay empate cercano con otra temática
        top_score, top_faq = ranked[0]
        segundo = ranked[1][0] if len(ranked) > 1 else 0
        if top_score >= umbral_lexico and (top_score - segundo) >= 4:
            base.update(
                {
                    "resultado": RESULTADO_ENCONTRADA,
                    "faq": top_faq,
                    "faq_id": top_faq.get("id"),
                    "confianza": min(1.0, top_score / 40.0),
                    "metodo": "lexico",
                    "motivo": f"score={top_score}",
                    "requiere_humano": bool(top_faq.get("requiere_humano")),
                    "respuesta": texto_respuesta_faq(top_faq),
                }
            )
            _log_faq(base)
            return base

    # Segunda etapa: IA sobre top candidatas (aunque score bajo, para semántica)
    candidatas_ia = [f for _s, f in ranked[:MAX_CANDIDATAS_IA]]
    if not candidatas_ia:
        # Sin scores: pasar un subconjunto acotado por prioridad
        candidatas_ia = [
            f for f in (faqs or []) if _vigente(f) and not _parece_bloque_proceso(str(f.get("pregunta") or ""), f)
        ]
        candidatas_ia = sorted(
            candidatas_ia, key=lambda f: -int(f.get("prioridad") or 0)
        )[:MAX_CANDIDATAS_IA]

    if usar_ia and candidatas_ia:
        sel = seleccionar_faq_con_ia(consulta, candidatas_ia)
        base["metodo"] = "semantico_ia"
        base["motivo"] = sel.get("motivo")
        base["confianza"] = float(sel.get("confianza") or 0.0)
        faq_id = sel.get("faq_id")
        if faq_id is not None and base["confianza"] >= umbral_ia:
            faq = next((f for f in candidatas_ia if int(f.get("id") or 0) == int(faq_id)), None)
            if faq:
                base.update(
                    {
                        "resultado": RESULTADO_ENCONTRADA,
                        "faq": faq,
                        "faq_id": faq.get("id"),
                        "requiere_humano": bool(faq.get("requiere_humano")),
                        "respuesta": texto_respuesta_faq(faq),
                    }
                )
                _log_faq(base)
                return base
        # IA rechazó o confianza baja
        base["resultado"] = RESULTADO_SIN_CONOCIMIENTO
        base["faq_id"] = None
        _log_faq(base)
        return base

    # Sin IA / sin candidatas
    base["metodo"] = "lexico_insuficiente" if ranked else "sin_candidatas"
    base["resultado"] = RESULTADO_SIN_CONOCIMIENTO
    _log_faq(base)
    return base


def detectar_intencion_tema(texto: str) -> Optional[str]:
    """Tema semántico controlado (monetizacion, regalos, …) para logs/UX."""
    n = limpiar_consulta(texto)
    if not n:
        return None
    if _tema_problema_live(n) and not _tema_monetizacion(n):
        return "problema_iniciar_live"
    for grupo, variantes in SINONIMOS.items():
        if any(v in n for v in variantes):
            return grupo
    return None


def _log_faq(data: Dict[str, Any]) -> None:
    logger.info(
        "[CHATBOT_FAQ] texto_normalizado=%r intencion=%s candidatas=%s "
        "faq_seleccionada=%s confianza=%s metodo=%s resultado=%s",
        (data.get("texto_normalizado") or "")[:120],
        data.get("intencion_detectada"),
        data.get("candidatas"),
        data.get("faq_id"),
        data.get("confianza"),
        data.get("metodo"),
        data.get("resultado"),
    )
