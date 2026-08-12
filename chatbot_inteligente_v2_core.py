"""
Núcleo del chatbot INTELIGENTE V2.

LLM = parser semántico (heurística + opcional structured output).
Backend = máquina de estados / reducer / decisión única.
Sin agente orquestador.
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from chatbot_conversacional_perfil import (
    consultar_conocimiento_puro,
    evaluar_requisitos_bloqueantes,
    mensaje_bloqueo_para_usuario,
    normalizar_json_safe,
    puede_ejecutar_accion,
)

logger = logging.getLogger("uvicorn.error")

V2_CTX_KEY = "v2"

# Macro-estados
ST_ORIENTACION = "ORIENTACION"
ST_EVALUACION = "EVALUACION"
ST_ELEGIBLE = "ELEGIBLE"
ST_BLOQUEADO = "BLOQUEADO"
ST_INCORPORACION = "INCORPORACION"
ST_PAUSADO = "PAUSADO"
ST_HUMANO = "HUMANO"
ST_FINALIZADO = "FINALIZADO"

# Decision types
DEC_ANSWER_INFO = "ANSWER_INFORMATION"
DEC_ACK_FACT = "ACKNOWLEDGE_FACT"
DEC_ASK_DATA = "ASK_REQUIRED_DATA"
DEC_BLOCKED = "BLOCKED"
DEC_CLARIFY = "CLARIFY"
DEC_PAUSED = "PAUSED"
DEC_EXECUTE = "EXECUTE_ACTION"  # fase posterior
DEC_HANDOFF = "HANDOFF"
DEC_FINISHED = "FINISHED"


def v2_enabled() -> bool:
    """Flag interno de rollback. Default ON para tipo inteligente."""
    return os.getenv("CHATBOT_INTELIGENTE_V2", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _norm(texto: str) -> str:
    valor = str(texto or "").strip().lower()
    valor = unicodedata.normalize("NFD", valor)
    valor = "".join(ch for ch in valor if unicodedata.category(ch) != "Mn")
    valor = re.sub(r"[^\w\s]", " ", valor, flags=re.UNICODE)
    return re.sub(r"\s+", " ", valor).strip()


@dataclass
class TurnInterpretation:
    intent: str = "unknown"
    questions: List[Dict[str, Any]] = field(default_factory=list)
    facts: Dict[str, Any] = field(default_factory=dict)
    answer_to_pending: Optional[str] = None  # yes|no|ambiguous|None
    contradiction: Optional[Dict[str, Any]] = None
    subject: str = "self"  # self|third_party
    confidence: float = 0.7
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return normalizar_json_safe(asdict(self))


@dataclass
class DecisionTurno:
    type: str
    intent: Optional[str] = None
    public_content: str = ""
    required_input: Optional[Dict[str, Any]] = None
    action: Optional[str] = None
    reason: str = ""
    cancel_pending: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return normalizar_json_safe(asdict(self))


def estado_vacio() -> Dict[str, Any]:
    return {
        "macro_state": ST_ORIENTACION,
        "profile": {
            "edad": None,
            "mayor_edad": None,
            "live_experience": None,
            "live_count": None,
            "live_duration_minutes": None,
            "live_platform": None,
            "hours_per_day": None,
            "days_per_week": None,
            "disponibilidad_live": None,
            "device_os": None,
            "device_age_years": None,
            "internet_speed_mbps": None,
            "personality_traits": [],
            "interest": None,
            "nivel_experiencia": None,
        },
        "eligibility": {"puede_incorporarse": None},
        "blockers": [],
        "pending_requirement": None,
        "answered_requirements": [],
        "history_facts": [],
        "last_decision_type": None,
    }


def leer_estado_v2(conversacion: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    conv = conversacion or {}
    ctx = conv.get("contexto") or {}
    if isinstance(ctx, str):
        try:
            import json

            ctx = json.loads(ctx)
        except Exception:  # noqa: BLE001
            ctx = {}
    if not isinstance(ctx, dict):
        ctx = {}
    raw = ctx.get(V2_CTX_KEY)
    if not isinstance(raw, dict):
        return estado_vacio()
    base = estado_vacio()
    base.update({k: v for k, v in raw.items() if k != "profile"})
    perfil = dict(base["profile"])
    if isinstance(raw.get("profile"), dict):
        perfil.update(raw["profile"])
    base["profile"] = perfil
    return base


def escribir_estado_v2(
    conversacion: Dict[str, Any],
    estado: Dict[str, Any],
) -> Dict[str, Any]:
    ctx = conversacion.get("contexto") or {}
    if isinstance(ctx, str):
        try:
            import json

            ctx = json.loads(ctx)
        except Exception:  # noqa: BLE001
            ctx = {}
    if not isinstance(ctx, dict):
        ctx = {}
    ctx[V2_CTX_KEY] = normalizar_json_safe(estado)
    conversacion["contexto"] = normalizar_json_safe(ctx)
    return conversacion["contexto"]


# ---------------------------------------------------------------------------
# Interpretación (heurística determinista; LLM opcional encima)
# ---------------------------------------------------------------------------


def interpretar_mensaje_v2(
    texto: str,
    *,
    estado: Optional[Dict[str, Any]] = None,
    pending: Optional[Dict[str, Any]] = None,
) -> TurnInterpretation:
    """Una sola interpretación estructurada por mensaje."""
    n = _norm(texto)
    estado = estado or estado_vacio()
    pending = pending or estado.get("pending_requirement")
    facts: Dict[str, Any] = {}
    questions: List[Dict[str, Any]] = []
    intent = "unknown"
    answer = None
    contradiction = None
    subject = "self"
    confidence = 0.75
    meta: Dict[str, Any] = {}

    if not n:
        return TurnInterpretation(intent="empty", confidence=0.0)

    # --- terceros ---
    if re.search(
        r"\b(hermana|hermano|esposo|esposa|amiga|amigo|prima|primo|referid)\b",
        n,
    ) and re.search(r"\b(quiere|entrar|unirse|proceso|tambien)\b", n):
        return TurnInterpretation(
            intent="third_party",
            subject="third_party",
            questions=[{"intent": "referral"}],
            confidence=0.9,
        )

    # --- queja / meta ---
    if re.search(
        r"\b(ya estamos|para que (vuelves|preguntas)|otra vez|de nuevo|"
        r"ya te dije|hace rato)\b",
        n,
    ) and re.search(r"\b(proceso|pregunt|interes|continuar|quiero)\b", n):
        return TurnInterpretation(
            intent="user_complaint",
            facts={"process_already_active": True},
            confidence=0.85,
            meta={"complaint_about": "repeated_interest"},
        )

    # --- edad / contradicción ---
    m_edad = re.search(r"\btengo\s+(\d{1,2})\s+anos?\b", n)
    if not m_edad and not re.search(
        r"\b(android|iphone|ios|telefono|celular|equipo|internet)\b", n
    ):
        m_edad = re.search(r"\b(\d{1,2})\s+anos?\b", n)
    menti = bool(re.search(r"\b(menti|mentí|la verdad|en realidad|corrijo)\b", n))
    if m_edad:
        edad = int(m_edad.group(1))
        if 10 <= edad <= 80:
            facts["edad"] = edad
            facts["mayor_edad"] = edad >= 18
            prev = (estado.get("profile") or {}).get("edad")
            if prev is not None and int(prev) != edad:
                contradiction = {
                    "field": "edad",
                    "previous": prev,
                    "new": edad,
                    "explicit": menti,
                }
            intent = "provide_fact"

    if re.search(r"\b(menti|mentí).{0,40}\b(tengo\s+)?(\d{1,2})\b", n):
        m2 = re.search(r"\b(\d{1,2})\b", n)
        if m2:
            edad = int(m2.group(1))
            if 10 <= edad <= 80:
                facts["edad"] = edad
                facts["mayor_edad"] = edad >= 18
                contradiction = {
                    "field": "edad",
                    "previous": (estado.get("profile") or {}).get("edad"),
                    "new": edad,
                    "explicit": True,
                }
                intent = "provide_fact"

    # --- interés ---
    if re.search(
        r"\b(no quiero|no me interesa|no deseo|mejor no|no continuar|"
        r"no quiero continuar|no quiero ingresar)\b",
        n,
    ):
        facts["interest"] = False
        intent = "decline_interest"
        answer = "no"
    elif re.search(
        r"\b(quiero ingresar|quiero entrar|quiero unirme|si quiero|"
        r"cambie de opinion|cambié de opinión|ahora si quiero)\b",
        n,
    ):
        facts["interest"] = True
        if "puedo" in n or "ingresar" in n:
            questions.append({"intent": "can_i_join"})
        intent = "express_interest" if "puedo" not in n else "ask_eligibility"
        answer = "yes"
    elif re.search(r"\b(puedo ingresar|puedo entrar|me dejan ingresar)\b", n):
        questions.append({"intent": "can_i_join"})
        intent = "ask_eligibility"

    # --- experiencia LIVE ---
    if re.search(
        r"\b(he hecho|hice|realice|realicé|una transmision|una transmisión|"
        r"un live|una sola|he hecho una)\b",
        n,
    ) or re.search(r"\b(he hecho una|hice una)\b", n):
        facts["live_experience"] = True
        if re.search(r"\b(una|1|un)\b", n) or "he hecho una" in n or "hice una" in n:
            facts["live_count"] = 1
        intent = "provide_fact"
    if re.search(r"\b(ya hago|ya realizo|hago transmisiones|hago live)\b", n):
        facts["live_experience"] = True
        facts.setdefault("live_count", None)
        intent = "provide_fact"
    if re.search(r"\b(nunca|no he|no hice|cero transmisiones|0 transmisiones)\b", n):
        facts["live_experience"] = False
        facts["live_count"] = 0
        intent = "provide_fact"
    m_min = re.search(r"\b(\d{1,3})\s*minutos?\b", n)
    if m_min:
        facts["live_duration_minutes"] = int(m_min.group(1))
        facts.setdefault("live_experience", True)
        facts.setdefault("live_count", 1)
        intent = "provide_fact"
    if "bigo" in n:
        facts["live_platform"] = "bigo"
        facts.setdefault("live_experience", True)
        intent = "provide_fact"

    # "cero" contextual
    if n in {"cero", "0", "nada"}:
        pend_code = str((pending or {}).get("code") or (pending or {}).get("campo") or "")
        if "live" in pend_code or "experiencia" in pend_code or "transm" in pend_code:
            facts["live_experience"] = False
            facts["live_count"] = 0
            intent = "provide_fact"
            answer = "no"
        else:
            intent = "ambiguous"
            answer = "ambiguous"

    # --- disponibilidad ---
    m_horas = re.search(r"\b(\d{1,2})\s*horas?\b", n)
    if m_horas:
        facts["hours_per_day"] = int(m_horas.group(1))
        facts["disponibilidad_live"] = True
        intent = "provide_fact"
    if re.search(r"lunes\s+a\s+jueves", n):
        facts["days_per_week"] = 4
        facts["disponibilidad_live"] = True
        intent = "provide_fact"
    elif re.search(r"lunes\s+a\s+viernes", n):
        facts["days_per_week"] = 5
        facts["disponibilidad_live"] = True
        intent = "provide_fact"
    elif re.search(r"todos\s+los\s+dias", n):
        facts["days_per_week"] = 7
        facts["disponibilidad_live"] = True
        intent = "provide_fact"

    # --- device / internet ---
    if "android" in n:
        facts["device_os"] = "android"
        intent = "provide_fact"
    if "iphone" in n or "ios" in n:
        facts["device_os"] = "ios"
        intent = "provide_fact"
    m_dev_age = re.search(r"\b(\d{1,2})\s*anos?\b", n)
    if m_dev_age and (
        "android" in n or "telefono" in n or "celular" in n or "iphone" in n or "equipo" in n
    ):
        facts["device_age_years"] = int(m_dev_age.group(1))
        intent = "provide_fact"
    m_net = re.search(r"\b(\d{1,4})\s*(megas?|mbps|mb)\b", n)
    if m_net or ("internet" in n and re.search(r"\d+", n)):
        if m_net:
            facts["internet_speed_mbps"] = int(m_net.group(1))
        else:
            m2 = re.search(r"\b(\d{1,4})\b", n)
            if m2:
                facts["internet_speed_mbps"] = int(m2.group(1))
        intent = "provide_fact"

    # --- personalidad ---
    traits = []
    if "introvert" in n:
        traits.append("introvertido")
    if re.search(r"\b(sin energia|poca energia|no tengo energia)\b", n):
        traits.append("baja_energia")
    if traits:
        facts["personality_traits"] = traits
        intent = "provide_fact"

    # --- preguntas informativas (pueden coexistir con hechos) ---
    if re.search(r"\b(bonos?|incentivos?)\b", n) and (
        "?" in str(texto)
        or "¿" in str(texto)
        or re.search(r"\b(que|cual|cuales|como|son)\b", n)
    ):
        if re.search(r"\b(dinero|especie|efectivo|pago)\b", n):
            questions.append({"intent": "bonus_payment_form"})
        else:
            questions.append({"intent": "what_are_bonuses"})
        intent = "ask_information" if not facts else "compound"

    if re.search(r"\b(beneficios?)\b", n) and re.search(
        r"\b(que|cual|cuales|como)\b", n
    ):
        questions.append({"intent": "what_are_benefits"})
        intent = "ask_information" if not facts else "compound"

    if re.search(r"\b(requisitos?)\b", n) and re.search(
        r"\b(que|cual|cuales|como)\b", n
    ):
        questions.append({"intent": "what_are_requirements"})
        intent = "ask_information" if not facts else "compound"

    if re.search(r"\b(diamantes?|regalos?|leon|león)\b", n) and re.search(
        r"\b(que|cual|cuanto|cuántos|vale|son)\b", n
    ):
        questions.append({"intent": "platform_knowledge", "topic": n})
        intent = "ask_information" if not facts else "compound"

    if re.search(
        r"\b(sirve|cuenta|califica|suficiente|experimentado)\b", n
    ) and (
        "transmision" in n
        or "transmisión" in _norm(texto)
        or "live" in n
        or facts.get("live_count")
        or facts.get("live_duration_minutes")
    ):
        questions.append({"intent": "does_my_live_experience_qualify"})
        intent = "compound" if questions or facts else "ask_information"

    # frase compuesta típica
    if "pero" in n and questions and facts:
        intent = "compound"

    # --- respuesta a pendiente ---
    if pending and n in {
        "si",
        "sip",
        "claro",
        "ok",
        "okay",
        "vale",
        "de acuerdo",
        "bueno",
        "dale",
    }:
        answer = "yes"
        if intent == "unknown":
            intent = "answer_pending"
    if pending and n in {"no", "nop", "nel"}:
        answer = "no"
        if intent == "unknown":
            intent = "answer_pending"
    if pending and n in {"mas o menos", "masomenos", "regular", "no se", "nose", "depende"}:
        answer = "ambiguous"
        intent = "ambiguous"

    if intent == "unknown" and facts:
        intent = "provide_fact"
    if intent == "unknown" and questions:
        intent = "ask_information"

    return TurnInterpretation(
        intent=intent,
        questions=questions,
        facts=facts,
        answer_to_pending=answer,
        contradiction=contradiction,
        subject=subject,
        confidence=confidence,
        meta=meta,
    )


# ---------------------------------------------------------------------------
# Reducer de estado
# ---------------------------------------------------------------------------


def reducir_estado(
    estado_anterior: Dict[str, Any],
    interpretacion: TurnInterpretation,
    *,
    requisitos: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    estado = normalizar_json_safe(dict(estado_anterior or estado_vacio()))
    perfil = dict(estado.get("profile") or {})
    hechos = dict(interpretacion.facts or {})
    hist = list(estado.get("history_facts") or [])

    if interpretacion.contradiction:
        hist.append(interpretacion.contradiction)

    # Traits: acumular
    if "personality_traits" in hechos:
        prev = list(perfil.get("personality_traits") or [])
        for t in hechos["personality_traits"]:
            if t not in prev:
                prev.append(t)
        hechos = dict(hechos)
        hechos["personality_traits"] = prev

    for k, v in hechos.items():
        if v is None:
            continue
        perfil[k] = v

    # interest desde answer_to_pending solo si pendiente es interés
    pend = estado.get("pending_requirement")
    if interpretacion.answer_to_pending in {"yes", "no"} and isinstance(pend, dict):
        code = str(pend.get("code") or pend.get("campo") or "").lower()
        if "interes" in code or pend.get("tipo") == "confirmar_interes":
            perfil["interest"] = interpretacion.answer_to_pending == "yes"

    # Nivel tentativo (no definitivo por una sola frase)
    if perfil.get("live_experience") is True:
        count = perfil.get("live_count")
        if count == 0:
            perfil["nivel_experiencia"] = "principiante"
        elif count == 1:
            # Tentativo: experiencia mínima, no forzar experimentado
            perfil.setdefault("nivel_experiencia", "principiante")
            perfil["nivel_experiencia_tentative"] = True
        elif isinstance(count, int) and count >= 3:
            perfil["nivel_experiencia"] = "experimentado"

    # Evaluar bloqueantes con adaptador al evaluador existente
    perfil_gate = {
        "mayor_edad": perfil.get("mayor_edad"),
        "edad": perfil.get("edad"),
        "disponibilidad_live": perfil.get("disponibilidad_live"),
        "horas_disponibles_dia": perfil.get("hours_per_day"),
        "dias_disponibles": perfil.get("days_per_week"),
        "interes": perfil.get("interest"),
        "nivel_experiencia": perfil.get("nivel_experiencia"),
        "hechos": {},
        "requisitos_evaluados": {},
    }
    evaluacion = evaluar_requisitos_bloqueantes(
        requisitos=requisitos,
        perfil=perfil_gate,
        aspirante={"mayor_edad": perfil.get("mayor_edad")},
    )
    blockers = list(evaluacion.get("bloqueantes_incumplidos") or [])
    puede = evaluacion.get("puede_incorporarse")
    # Si no hay requisitos bloqueantes conocidos evaluados, no forzar True
    if perfil.get("mayor_edad") is False and any(
        _req_es_edad(r) for r in (requisitos or []) if r and r.get("activo") is not False
    ):
        if "mayor_edad" not in blockers:
            blockers.append("mayor_edad")
        puede = False

    prev_macro = str(estado.get("macro_state") or ST_ORIENTACION)
    if perfil.get("interest") is False:
        macro = ST_PAUSADO
    elif blockers:
        macro = ST_BLOQUEADO
    elif puede is True and _perfil_minimo_completo(perfil):
        macro = ST_ELEGIBLE
    elif any(perfil.get(k) is not None for k in ("edad", "live_experience", "interest", "hours_per_day")):
        macro = ST_EVALUACION
    else:
        macro = ST_ORIENTACION

    # Transición imposible: BLOQUEADO + quiero ingresar ≠ INCORPORACION
    if prev_macro == ST_BLOQUEADO and macro == ST_INCORPORACION:
        macro = ST_BLOQUEADO
    if blockers and macro == ST_INCORPORACION:
        macro = ST_BLOQUEADO

    # Resolver pending si el dato ya llegó
    new_pending = pend
    if isinstance(pend, dict):
        code = str(pend.get("code") or "").lower()
        if _pending_resuelto(pend, perfil):
            answered = list(estado.get("answered_requirements") or [])
            if code and code not in answered:
                answered.append(code)
            estado["answered_requirements"] = answered
            new_pending = None

    if interpretacion.intent == "user_complaint":
        # Cancelar pending de interés
        if isinstance(new_pending, dict) and "interes" in str(
            new_pending.get("code") or new_pending.get("tipo") or ""
        ):
            new_pending = None
        if perfil.get("interest") is None:
            # Si ya hay proceso activo, asumir interés implícito sin preguntar
            perfil["interest"] = True

    estado["profile"] = perfil
    estado["blockers"] = blockers
    estado["eligibility"] = {"puede_incorporarse": False if blockers else puede}
    estado["macro_state"] = macro
    estado["pending_requirement"] = new_pending
    estado["history_facts"] = hist[-20:]
    return normalizar_json_safe(estado)


def _req_es_edad(req: Dict[str, Any]) -> bool:
    blob = _norm(
        " ".join(
            str(req.get(k) or "")
            for k in ("codigo", "nombre", "descripcion")
        )
    )
    return "edad" in blob or "mayor" in blob


def _perfil_minimo_completo(perfil: Dict[str, Any]) -> bool:
    return (
        perfil.get("mayor_edad") is True
        and perfil.get("interest") is True
        and perfil.get("disponibilidad_live") is True
    )


def _pending_resuelto(pend: Dict[str, Any], perfil: Dict[str, Any]) -> bool:
    code = str(pend.get("code") or pend.get("campo") or "").lower()
    tipo = str(pend.get("tipo") or "").lower()
    if "edad" in code or "mayor" in code:
        return perfil.get("mayor_edad") is not None
    if "disponib" in code or "hora" in code:
        return perfil.get("hours_per_day") is not None or perfil.get(
            "disponibilidad_live"
        ) is not None
    if "live" in code or "experiencia" in code or "transm" in code:
        return perfil.get("live_experience") is not None
    if "telefono" in code or "device" in code or "conexion" in code or "internet" in code:
        if "internet" in code or "conexion" in code:
            return perfil.get("internet_speed_mbps") is not None
        return perfil.get("device_os") is not None
    if "interes" in code or tipo == "confirmar_interes":
        return perfil.get("interest") is not None
    return False


# ---------------------------------------------------------------------------
# Decisión única
# ---------------------------------------------------------------------------


def _siguiente_dato_faltante(
    perfil: Dict[str, Any],
    requisitos: Optional[List[Dict[str, Any]]],
    answered: List[str],
) -> Optional[Dict[str, Any]]:
    """Orden de recolección: experiencia → edad → disponibilidad → device/net → interés."""
    if perfil.get("live_experience") is None:
        return {
            "code": "live_experience",
            "campo": "live_experience",
            "tipo": "hacer_pregunta",
            "texto": "¿Ya has realizado transmisiones LIVE?",
        }
    if perfil.get("mayor_edad") is None:
        # Solo si hay requisito de edad o siempre preguntamos en evaluación
        if any(_req_es_edad(r) for r in (requisitos or []) if r):
            return {
                "code": "mayor_edad",
                "campo": "mayor_edad",
                "tipo": "hacer_pregunta",
                "texto": "Antes de continuar, ¿eres mayor de 18 años?",
            }
    if perfil.get("hours_per_day") is None and perfil.get("days_per_week") is None:
        if perfil.get("disponibilidad_live") is None:
            return {
                "code": "disponibilidad",
                "campo": "disponibilidad",
                "tipo": "hacer_pregunta",
                "texto": (
                    "¿Cuántos días a la semana y aproximadamente cuántas horas "
                    "por día puedes transmitir?"
                ),
            }
    if perfil.get("device_os") is None:
        return {
            "code": "device",
            "campo": "device",
            "tipo": "hacer_pregunta",
            "texto": "¿Qué teléfono usas (Android/iOS) y aproximadamente de qué año es?",
        }
    if perfil.get("device_os") is not None and perfil.get("internet_speed_mbps") is None:
        return {
            "code": "internet",
            "campo": "internet",
            "tipo": "hacer_pregunta",
            "texto": "¿Qué velocidad de internet aproximada tienes (en megas)?",
        }
    if perfil.get("interest") is None:
        # Solo al final, y solo si no está bloqueado
        return {
            "code": "interest",
            "campo": "interest",
            "tipo": "confirmar_interes",
            "texto": "¿Te gustaría continuar con el proceso de ingreso a la agencia?",
        }
    return None


def _buscar_faq_topic(
    topic: str,
    faqs: Optional[List[Dict[str, Any]]],
) -> Optional[str]:
    n = _norm(topic)
    tokens = [t for t in n.split() if len(t) >= 4]
    mejor = None
    score = 0
    for f in faqs or []:
        if not f or f.get("activo") is False:
            continue
        blob = _norm(
            " ".join(
                [
                    str(f.get("pregunta") or ""),
                    str(f.get("respuesta_corta") or ""),
                    str(f.get("respuesta_completa") or ""),
                    " ".join(str(x) for x in (f.get("palabras_clave") or []) if x),
                ]
            )
        )
        s = sum(1 for t in tokens if t in blob)
        if s > score:
            score = s
            mejor = f
    if mejor and score > 0:
        return str(
            mejor.get("respuesta_completa")
            or mejor.get("respuesta_corta")
            or ""
        ).strip() or None
    return None


def _responder_pregunta(
    q: Dict[str, Any],
    *,
    estado: Dict[str, Any],
    requisitos: Optional[List[Dict[str, Any]]],
    beneficios: Optional[List[Dict[str, Any]]],
    faqs: Optional[List[Dict[str, Any]]],
) -> str:
    intent = str(q.get("intent") or "")
    perfil = estado.get("profile") or {}

    if intent == "what_are_bonuses":
        return consultar_conocimiento_puro(
            tipo="bonos", requisitos=requisitos, beneficios=beneficios, faqs=faqs
        ) or "No tengo bonos confirmados para compartir en este momento."

    if intent == "bonus_payment_form":
        # Buscar dato específico; no listar todos los bonos si no hay forma de pago
        for b in beneficios or []:
            desc = str(
                b.get("descripcion")
                or b.get("texto_autorizado")
                or b.get("descripcion_completa")
                or ""
            ).lower()
            if any(k in desc for k in ("dinero", "especie", "efectivo", "transferencia")):
                nombre = b.get("nombre") or "disponible"
                return (
                    f"Sobre la forma de entrega del bono {nombre}: {desc[:300]}"
                )
        faq = _buscar_faq_topic("bonos dinero especie", faqs)
        if faq:
            return faq
        return (
            "No tengo información confirmada sobre si los bonos se entregan "
            "en dinero o en especie. Ese detalle debe confirmarlo el equipo."
        )

    if intent == "what_are_benefits":
        return consultar_conocimiento_puro(
            tipo="beneficios", requisitos=requisitos, beneficios=beneficios, faqs=faqs
        ) or "No tengo beneficios confirmados para compartir ahora."

    if intent == "what_are_requirements":
        return consultar_conocimiento_puro(
            tipo="requisitos", requisitos=requisitos, beneficios=beneficios, faqs=faqs
        ) or "No tengo requisitos confirmados para compartir ahora."

    if intent == "does_my_live_experience_qualify":
        count = perfil.get("live_count")
        mins = perfil.get("live_duration_minutes")
        partes = []
        if count or mins:
            partes.append(
                "Sí cuenta como experiencia previa"
                + (
                    f" ({count} transmisión"
                    + ("es" if (count or 0) != 1 else "")
                    + (f" de {mins} minutos" if mins else "")
                    + ")"
                    if count or mins
                    else ""
                )
                + "."
            )
        partes.append(
            "No tengo una regla configurada que me permita afirmar que eso "
            "baste para clasificarte como experimentado; el equipo lo valida "
            "con el resto del perfil."
        )
        return " ".join(partes)

    if intent == "platform_knowledge":
        topic = str(q.get("topic") or "")
        faq = _buscar_faq_topic(topic, faqs)
        if faq:
            return faq
        return (
            "No tengo ese dato confirmado en la información autorizada. "
            "Puedo ayudarte con requisitos, beneficios o el proceso de ingreso."
        )

    if intent == "can_i_join":
        blockers = estado.get("blockers") or []
        if blockers:
            gate = {
                "permitida": False,
                "motivo": "requisito_bloqueante",
                "bloqueantes": blockers,
            }
            return mensaje_bloqueo_para_usuario(gate, perfil=perfil)
        if estado.get("macro_state") == ST_ELEGIBLE:
            return (
                "Con la información actual podrías avanzar en el proceso. "
                "Cuando conectemos la etapa de incorporación te indico el siguiente paso."
            )
        return (
            "Todavía estamos evaluando algunos datos. Cuando complete lo necesario "
            "te confirmo si puedes avanzar."
        )

    if intent == "referral":
        return (
            "Sí, puede comunicarse con la agencia por este mismo canal para "
            "iniciar su propio proceso. No modifico tu perfil con los datos de esa persona."
        )

    return ""


def resolver_decision_turno(
    *,
    interpretacion: TurnInterpretation,
    estado: Dict[str, Any],
    requisitos: Optional[List[Dict[str, Any]]] = None,
    beneficios: Optional[List[Dict[str, Any]]] = None,
    faqs: Optional[List[Dict[str, Any]]] = None,
) -> DecisionTurno:
    perfil = estado.get("profile") or {}
    blockers = list(estado.get("blockers") or [])
    macro = str(estado.get("macro_state") or ST_ORIENTACION)
    answered = list(estado.get("answered_requirements") or [])

    # 1) Queja meta
    if interpretacion.intent == "user_complaint":
        faltante = _siguiente_dato_faltante(perfil, requisitos, answered)
        # Nunca interés si ya conocido
        if faltante and faltante.get("code") == "interest" and perfil.get("interest") is not None:
            faltante = None
        if faltante and faltante.get("code") == "interest":
            # Buscar otro dato o no preguntar interés tras queja
            faltante = None
            # recompute without interest
            tmp = dict(perfil)
            tmp["interest"] = True
            faltante = _siguiente_dato_faltante(tmp, requisitos, answered)
        texto = (
            "Tienes razón: ya estamos en el proceso y no necesito repetir "
            "esa pregunta de interés."
        )
        if faltante:
            texto = f"{texto} Sigamos con esto: {faltante['texto']}"
            return DecisionTurno(
                type=DEC_ASK_DATA,
                public_content=texto,
                required_input=faltante,
                reason="complaint_skip_interest",
                intent=interpretacion.intent,
            )
        return DecisionTurno(
            type=DEC_ACK_FACT,
            public_content=texto + " ¿En qué más te ayudo?",
            reason="complaint_ack",
            intent=interpretacion.intent,
            cancel_pending=True,
        )

    # 2) Terceros
    if interpretacion.subject == "third_party" or interpretacion.intent == "third_party":
        return DecisionTurno(
            type=DEC_ANSWER_INFO,
            public_content=_responder_pregunta(
                {"intent": "referral"},
                estado=estado,
                requisitos=requisitos,
                beneficios=beneficios,
                faqs=faqs,
            ),
            reason="third_party",
            intent="third_party",
        )

    # 3) Ambigüedad
    if interpretacion.intent == "ambiguous" or interpretacion.answer_to_pending == "ambiguous":
        pend = estado.get("pending_requirement") or {}
        code = str(pend.get("code") or "")
        if "disponib" in code:
            q = (
                "¿Cuántos días a la semana y aproximadamente cuántas horas "
                "por día puedes transmitir?"
            )
        elif "live" in code or "experiencia" in code:
            q = "¿Cuántas transmisiones LIVE has hecho aproximadamente?"
        elif pend.get("texto"):
            q = f"Para precisar: {pend.get('texto')}"
        else:
            q = "¿Puedes precisarme un poco más ese dato?"
        return DecisionTurno(
            type=DEC_CLARIFY,
            public_content=q,
            required_input=pend or {"code": "clarify", "texto": q},
            reason="ambiguous_input",
            intent=interpretacion.intent,
        )

    # 4) Preguntas informativas (prioridad alta; bloqueante NO secuestra)
    if interpretacion.questions:
        # Elegibilidad con bloqueo → decisión BLOCKED explícita
        if any(str(q.get("intent")) == "can_i_join" for q in interpretacion.questions):
            if blockers:
                gate = {
                    "permitida": False,
                    "motivo": "requisito_bloqueante",
                    "bloqueantes": blockers,
                }
                return DecisionTurno(
                    type=DEC_BLOCKED,
                    public_content=mensaje_bloqueo_para_usuario(gate, perfil=perfil),
                    reason="requisito_bloqueante",
                    intent="ask_eligibility",
                    cancel_pending=True,
                )
            return DecisionTurno(
                type=DEC_ANSWER_INFO,
                public_content=_responder_pregunta(
                    {"intent": "can_i_join"},
                    estado=estado,
                    requisitos=requisitos,
                    beneficios=beneficios,
                    faqs=faqs,
                ),
                reason="eligibility_ok",
                intent="ask_eligibility",
            )

        partes: List[str] = []
        for q in interpretacion.questions:
            resp = _responder_pregunta(
                q,
                estado=estado,
                requisitos=requisitos,
                beneficios=beneficios,
                faqs=faqs,
            )
            if resp:
                partes.append(resp)
        # Mencionar bloqueo SOLO si preguntó elegibilidad
        solo_info = all(
            str(q.get("intent"))
            not in {"can_i_join", "ask_eligibility"}
            for q in interpretacion.questions
        )
        # Ack hechos si venían en el mismo mensaje
        if interpretacion.facts and interpretacion.intent == "compound":
            ack = _ack_hechos(interpretacion.facts)
            if ack:
                partes.insert(0, ack)
        content = "\n\n".join(p for p in partes if p).strip()
        if not content:
            content = (
                "No tengo información confirmada para esa consulta en este momento."
            )
        # Tras info: si hay dato faltante y NO hay blockers secuestrando,
        # preguntar siguiente SOLO si no era solo consulta y no hay interés ya
        # Para consultas informativas puras: no empujar confirmar_interes
        next_q = None
        if interpretacion.facts and not solo_info:
            next_q = None
        return DecisionTurno(
            type=DEC_ANSWER_INFO,
            public_content=content,
            reason="answer_questions",
            intent=interpretacion.intent,
            required_input=None,
            cancel_pending=False,
        )

    # 5) Elegibilidad / quiero ingresar con bloqueo
    if interpretacion.intent in {"ask_eligibility", "express_interest"} or (
        interpretacion.facts.get("interest") is True
        and any(k in _norm(str(interpretacion.meta)) for k in ())
    ):
        if "can_i_join" in [
            str(q.get("intent")) for q in interpretacion.questions
        ] or interpretacion.intent == "ask_eligibility":
            pass  # handled above if questions present
        if blockers and (
            interpretacion.intent in {"ask_eligibility", "express_interest"}
            or interpretacion.facts.get("interest") is True
        ):
            # Solo bloquear explícitamente si intenta avanzar
            if interpretacion.intent in {"ask_eligibility", "express_interest"} or (
                interpretacion.facts.get("interest") is True
                and not interpretacion.questions
            ):
                gate = {
                    "permitida": False,
                    "motivo": "requisito_bloqueante",
                    "bloqueantes": blockers,
                }
                # Verificar gate defense
                g2 = puede_ejecutar_accion(
                    accion="enviar_solicitud",
                    perfil={
                        "mayor_edad": perfil.get("mayor_edad"),
                        "bloqueantes_incumplidos": blockers,
                        "puede_incorporarse": False,
                    },
                    requisitos=requisitos,
                )
                return DecisionTurno(
                    type=DEC_BLOCKED,
                    public_content=mensaje_bloqueo_para_usuario(gate, perfil=perfil),
                    reason="requisito_bloqueante",
                    action="enviar_solicitud" if not g2.get("permitida") else None,
                    intent=interpretacion.intent,
                    cancel_pending=True,
                )

    if interpretacion.facts.get("interest") is True and blockers:
        # "quiero ingresar" con bloqueo
        if interpretacion.intent in {"express_interest", "provide_fact", "compound"}:
            # Only if message clearly tries to advance (interest true without pure info)
            if not interpretacion.questions:
                gate = {
                    "permitida": False,
                    "motivo": "requisito_bloqueante",
                    "bloqueantes": blockers,
                }
                return DecisionTurno(
                    type=DEC_BLOCKED,
                    public_content=mensaje_bloqueo_para_usuario(gate, perfil=perfil),
                    reason="requisito_bloqueante",
                    intent=interpretacion.intent,
                    cancel_pending=True,
                )

    # 6) Decline interest
    if interpretacion.facts.get("interest") is False or interpretacion.intent == "decline_interest":
        return DecisionTurno(
            type=DEC_PAUSED,
            public_content=(
                "Entiendo. No avanzaremos con el proceso por ahora. "
                "Si quieres, puedo seguir respondiendo tus dudas sobre la agencia."
            ),
            reason="interest_false",
            intent=interpretacion.intent,
            cancel_pending=True,
        )

    # 7) Hechos nuevos (incl. con bloqueante) → ack + siguiente dato útil
    if interpretacion.facts or interpretacion.intent == "provide_fact":
        ack = _ack_hechos(interpretacion.facts)
        # NO repetir bloqueo de edad aquí
        faltante = _siguiente_dato_faltante(perfil, requisitos, answered)
        # Prohibido confirmar_interes si interest conocido o macro BLOQUEADO
        if faltante and faltante.get("code") == "interest":
            if perfil.get("interest") is not None or blockers or macro == ST_BLOQUEADO:
                faltante = None
        # Si device llegó pero falta modelo y no hay umbral: pedir solo lo faltante
        if interpretacion.facts.get("device_os") and perfil.get("internet_speed_mbps") is None:
            faltante = {
                "code": "internet",
                "campo": "internet",
                "tipo": "hacer_pregunta",
                "texto": "Gracias. ¿Qué velocidad de internet aproximada tienes (en megas)?",
            }
        if interpretacion.facts.get("internet_speed_mbps") is not None:
            # No saltar a interés
            faltante = _siguiente_dato_faltante(perfil, requisitos, answered)
            if faltante and faltante.get("code") == "interest":
                if perfil.get("interest") is not None or blockers:
                    faltante = None

        if faltante:
            texto = f"{ack} {faltante['texto']}".strip() if ack else faltante["texto"]
            return DecisionTurno(
                type=DEC_ASK_DATA,
                public_content=texto,
                required_input=faltante,
                reason="collect_next_required",
                intent=interpretacion.intent,
            )
        if ack:
            return DecisionTurno(
                type=DEC_ACK_FACT,
                public_content=ack + " ¿En qué más te puedo ayudar?",
                reason="fact_ack",
                intent=interpretacion.intent,
            )

    # 8) answer_pending yes/no genérico
    if interpretacion.intent == "answer_pending":
        faltante = _siguiente_dato_faltante(perfil, requisitos, answered)
        if faltante and faltante.get("code") == "interest" and (
            perfil.get("interest") is not None or blockers
        ):
            faltante = None
        if faltante:
            return DecisionTurno(
                type=DEC_ASK_DATA,
                public_content=faltante["texto"],
                required_input=faltante,
                reason="after_pending_answer",
                intent=interpretacion.intent,
            )
        return DecisionTurno(
            type=DEC_ACK_FACT,
            public_content="Perfecto, gracias. ¿En qué más te ayudo?",
            reason="pending_answered",
            intent=interpretacion.intent,
        )

    # 9) Default: siguiente dato — NUNCA confirmar_interes como fallback ciego
    faltante = _siguiente_dato_faltante(perfil, requisitos, answered)
    if faltante and faltante.get("code") == "interest":
        # Solo si realmente desconocido y no bloqueado y hay progreso previo
        if (
            perfil.get("interest") is not None
            or blockers
            or macro in {ST_ORIENTACION}
            or not any(
                perfil.get(k) is not None
                for k in ("live_experience", "mayor_edad", "hours_per_day", "device_os")
            )
        ):
            # En orientación sin datos: preguntar experiencia, no interés
            if perfil.get("live_experience") is None:
                faltante = {
                    "code": "live_experience",
                    "campo": "live_experience",
                    "tipo": "hacer_pregunta",
                    "texto": "¿Ya has realizado transmisiones LIVE?",
                }
            else:
                faltante = None

    if faltante:
        return DecisionTurno(
            type=DEC_ASK_DATA,
            public_content=faltante["texto"],
            required_input=faltante,
            reason="next_required_data",
            intent=interpretacion.intent,
        )

    return DecisionTurno(
        type=DEC_ACK_FACT,
        public_content=(
            "Gracias por la información. Puedo resolver dudas sobre la agencia, "
            "requisitos o beneficios cuando quieras."
        ),
        reason="no_forced_interest",
        intent=interpretacion.intent,
    )


def _ack_hechos(facts: Dict[str, Any]) -> str:
    if not facts:
        return ""
    partes = []
    if "edad" in facts:
        partes.append(f"Registré que tienes {facts['edad']} años.")
    if facts.get("live_count") == 1:
        partes.append("Anoté que has hecho al menos una transmisión.")
    elif facts.get("live_experience") is True:
        partes.append("Anoté que ya tienes experiencia en transmisiones.")
    elif facts.get("live_experience") is False:
        partes.append("Anoté que aún no has transmitido.")
    if facts.get("hours_per_day") is not None or facts.get("days_per_week") is not None:
        h = facts.get("hours_per_day")
        d = facts.get("days_per_week")
        if h is not None and d is not None:
            partes.append(f"Guardé tu disponibilidad: {h} h/día, {d} días.")
        elif h is not None:
            partes.append(f"Guardé que puedes unas {h} horas al día.")
        else:
            partes.append(f"Guardé que puedes unos {d} días a la semana.")
    if facts.get("device_os"):
        extra = ""
        if facts.get("device_age_years") is not None:
            extra = f" de unos {facts['device_age_years']} años"
        partes.append(f"Registré tu equipo ({facts['device_os']}{extra}).")
    if facts.get("internet_speed_mbps") is not None:
        partes.append(
            f"Registré tu conexión (~{facts['internet_speed_mbps']} Mbps)."
        )
    if facts.get("personality_traits"):
        partes.append("Tomé nota de lo que comentas sobre tu estilo/energía.")
    return " ".join(partes)


def sanitizar_respuesta_publica(texto: str) -> str:
    """Único punto de salida pública V2."""
    # Reutilizar sanitizer del servicio legacy sin importar orquestación.
    try:
        from service_chatbot_conversacional import _sanitizar_respuesta_usuario

        return _sanitizar_respuesta_usuario(str(texto or ""))
    except Exception:  # noqa: BLE001
        crudo = str(texto or "").strip()
        lineas = []
        for ln in crudo.splitlines():
            n = _norm(ln)
            if any(
                p in n
                for p in (
                    "informa solo",
                    "mensaje_instrucciones",
                    "presentar la oportunidad",
                    "reconoce que",
                    "usa la herramienta",
                )
            ):
                continue
            lineas.append(ln)
        return "\n".join(lineas).strip()
