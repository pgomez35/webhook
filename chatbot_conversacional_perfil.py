"""
Perfil acumulado, memoria factual y action gating del chatbot INTELIGENTE.

Autoridad: el BACKEND decide si una acción de conversión es ejecutable.
La IA solo interpreta, extrae hechos y propone; nunca salta bloqueantes.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("uvicorn.error")

PERFIL_KEY = "perfil_aspirante"

# Acciones de conversión que OBLIGATORIAMENTE pasan por el gate.
ACCIONES_GATEADAS = frozenset(
    {
        "enviar_solicitud",
        "enviar_enlace",
        "enviar_enlace_autorizado",
        "agendar_live",
        "preparar_prueba_live",
        "solicitar_live",
        "solicitar_evidencias",
        "crear_tarea_candidato",
        "avanzar_incorporacion",
    }
)

_ACCIONES_ALIAS = {
    "enviar_enlace_autorizado": "enviar_solicitud",
    "enviar_enlace": "enviar_solicitud",
    "preparar_envio_enlace_autorizado": "enviar_solicitud",
    "agendar_live": "agendar_live",
    "solicitar_live": "agendar_live",
    "preparar_prueba_live": "agendar_live",
    "solicitar_evidencias": "solicitar_evidencias",
    "crear_tarea_candidato": "crear_tarea_candidato",
    "avanzar_incorporacion": "enviar_solicitud",
    "enviar_solicitud": "enviar_solicitud",
}


def _ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalizar(texto: str) -> str:
    valor = str(texto or "").strip().lower()
    valor = unicodedata.normalize("NFD", valor)
    valor = "".join(ch for ch in valor if unicodedata.category(ch) != "Mn")
    valor = re.sub(r"[^\w\s]", " ", valor, flags=re.UNICODE)
    return re.sub(r"\s+", " ", valor).strip()


def _ctx_dict(conversacion: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    conv = conversacion or {}
    ctx = conv.get("contexto") or {}
    if isinstance(ctx, str):
        try:
            import json

            ctx = json.loads(ctx)
        except Exception:  # noqa: BLE001
            ctx = {}
    return dict(ctx) if isinstance(ctx, dict) else {}


def leer_perfil(
    conversacion: Optional[Dict[str, Any]] = None,
    aspirante: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Perfil acumulado: contexto.perfil_aspirante + campos persistentes del aspirante.
    Los campos de chatbot_aspirantes mandan cuando existen.
    """
    ctx = _ctx_dict(conversacion)
    perfil = dict(ctx.get(PERFIL_KEY) or {}) if isinstance(ctx.get(PERFIL_KEY), dict) else {}
    asp = aspirante or {}
    conv = conversacion or {}

    if asp.get("mayor_edad") is not None:
        perfil["mayor_edad"] = bool(asp.get("mayor_edad"))
    if asp.get("disponibilidad_live") is not None:
        perfil["disponibilidad_live"] = bool(asp.get("disponibilidad_live"))
    if asp.get("usuario_plataforma"):
        perfil["usuario_plataforma"] = asp.get("usuario_plataforma")

    nivel = (
        conv.get("nivel_experiencia")
        or asp.get("nivel_experiencia")
        or perfil.get("nivel_experiencia")
        or "desconocido"
    )
    perfil["nivel_experiencia"] = str(nivel).lower()
    if conv.get("nivel_experiencia_confianza") is not None:
        perfil["nivel_experiencia_confianza"] = conv.get("nivel_experiencia_confianza")
    if conv.get("nivel_experiencia_confirmado") is not None:
        perfil["nivel_experiencia_confirmado"] = bool(
            conv.get("nivel_experiencia_confirmado")
        )

    perfil.setdefault("hechos", {})
    if not isinstance(perfil["hechos"], dict):
        perfil["hechos"] = {}
    perfil.setdefault("requisitos_evaluados", {})
    if not isinstance(perfil["requisitos_evaluados"], dict):
        perfil["requisitos_evaluados"] = {}
    perfil.setdefault("interes", None)
    perfil.setdefault("puede_incorporarse", None)
    return perfil


def escribir_perfil_en_contexto(
    conversacion: Dict[str, Any],
    perfil: Dict[str, Any],
) -> Dict[str, Any]:
    ctx = _ctx_dict(conversacion)
    perfil = dict(perfil or {})
    perfil["actualizado_at"] = _ahora_iso()
    ctx[PERFIL_KEY] = perfil
    conversacion["contexto"] = ctx
    return ctx


def extraer_hechos_de_texto(texto: str) -> Dict[str, Any]:
    """Extracción determinística de hechos explícitos del mensaje."""
    n = _normalizar(texto)
    hechos: Dict[str, Any] = {}
    if not n:
        return hechos

    m_edad = re.search(r"\btengo\s+(\d{1,2})\s+anos?\b", n)
    if not m_edad:
        m_edad = re.search(r"\b(\d{1,2})\s+anos?\b", n)
    if m_edad:
        edad = int(m_edad.group(1))
        if 10 <= edad <= 80:
            hechos["edad"] = edad
            hechos["mayor_edad"] = edad >= 18
            hechos["fuente_edad"] = "declaracion_explicita"

    if "menor de edad" in n:
        hechos["mayor_edad"] = False
        hechos["fuente_edad"] = "declaracion_explicita"
    if re.search(r"\b(soy mayor de 18|ya soy mayor|mayor de edad)\b", n):
        hechos.setdefault("mayor_edad", True)
        hechos.setdefault("fuente_edad", "declaracion_explicita")
    if re.search(r"\btengo\s+(1[0-7])\b", n) and "ano" not in n:
        m = re.search(r"\btengo\s+(1[0-7])\b", n)
        if m:
            hechos["edad"] = int(m.group(1))
            hechos["mayor_edad"] = False
            hechos["fuente_edad"] = "declaracion_explicita"

    m_horas = re.search(r"\b(\d{1,2})\s*horas?\b", n)
    if m_horas:
        hechos["horas_disponibles_dia"] = int(m_horas.group(1))

    dias = None
    if re.search(r"lunes\s+a\s+jueves", n):
        dias = 4
    elif re.search(r"lunes\s+a\s+viernes", n):
        dias = 5
    elif re.search(r"todos\s+los\s+dias", n):
        dias = 7
    else:
        m_dias = re.search(r"\b(\d{1,2})\s*dias?\b", n)
        if m_dias:
            dias = int(m_dias.group(1))
    if dias is not None:
        hechos["dias_disponibles"] = dias

    if "horas_disponibles_dia" in hechos or "dias_disponibles" in hechos:
        hechos.setdefault("disponibilidad_live", True)

    # Cumple 18 pronto: se registra, pero sigue siendo menor HOY.
    if re.search(
        r"\b(cumplo\s+18|manana cumplo|en un dia cumplo|en unos dias cumplo|"
        r"casi cumplo|voy a cumplir 18)\b",
        n,
    ):
        hechos["edad_cumple_pronto"] = True
        hechos["mayor_edad"] = False

    if re.search(
        r"\b(si quiero ingresar|quiero ingresar|quiero entrar|quiero unirme|"
        r"me interesa continuar|enviame el (enlace|link)|"
        r"mandame el (enlace|link)|quiero la solicitud|si quiero continuar)\b",
        n,
    ):
        hechos["interes"] = True

    detalle: Dict[str, Any] = {}
    if re.search(
        r"\b(solo|solamente|unicamente|un unico|una sola|un solo)\b.*\blive", n
    ) or re.search(r"\b(un|1)\s+live\b", n):
        detalle["lives_aproximados"] = 1
        detalle["experiencia_limitada"] = True
    if "bigo" in n:
        detalle["plataforma"] = "bigo"
    m_min = re.search(r"\b(\d{1,3})\s*minutos?\b", n)
    if m_min:
        detalle["duracion_minutos"] = int(m_min.group(1))
    if detalle:
        hechos["experiencia_detalle"] = detalle
        hechos["experiencia_requiere_reevaluacion"] = True

    return hechos


def fusionar_hechos_en_perfil(
    perfil: Dict[str, Any],
    hechos: Dict[str, Any],
) -> Dict[str, Any]:
    out = dict(perfil or {})
    hechos_prev = dict(out.get("hechos") or {})
    for k, v in (hechos or {}).items():
        if k == "experiencia_detalle" and isinstance(v, dict):
            prev = dict(hechos_prev.get("experiencia_detalle") or {})
            prev.update(v)
            hechos_prev["experiencia_detalle"] = prev
        elif v is not None:
            hechos_prev[k] = v
    out["hechos"] = hechos_prev

    if "mayor_edad" in hechos:
        out["mayor_edad"] = bool(hechos["mayor_edad"])
        if "edad" in hechos:
            out["edad"] = hechos["edad"]
        logger.info(
            "[CHATBOT_PERFIL] mayor_edad=%s edad=%s",
            out.get("mayor_edad"),
            out.get("edad"),
        )
    if "disponibilidad_live" in hechos:
        out["disponibilidad_live"] = bool(hechos["disponibilidad_live"])
    if "horas_disponibles_dia" in hechos:
        out["horas_disponibles_dia"] = hechos["horas_disponibles_dia"]
    if "dias_disponibles" in hechos:
        out["dias_disponibles"] = hechos["dias_disponibles"]
    if hechos.get("interes") is True:
        out["interes"] = True
    return out


def _requisito_es_bloqueante(req: Dict[str, Any]) -> bool:
    """
    Solo `bloquea_proceso=true` impide avanzar.
    `categoria=obligatorio` indica que debe evaluarse/cumplirse, pero NO
    bloquea por sí solo (pueden coexistir obligatorio + bloquea_proceso=false).
    """
    return req.get("bloquea_proceso") is True


def _requisito_es_deseable(req: Dict[str, Any]) -> bool:
    cat = _normalizar(str(req.get("categoria") or ""))
    return cat in {"deseable", "opcional", "recomendado"}


def _es_requisito_mayor_edad(req: Dict[str, Any]) -> bool:
    blob = _normalizar(
        " ".join(
            [
                str(req.get("codigo") or ""),
                str(req.get("nombre") or ""),
                str(req.get("descripcion") or ""),
            ]
        )
    )
    return any(
        k in blob
        for k in (
            "mayor_edad",
            "mayoria de edad",
            "mayor de 18",
            "18 anos",
            "edad minima",
        )
    )


def _es_requisito_disponibilidad(req: Dict[str, Any]) -> bool:
    blob = _normalizar(
        " ".join(
            [
                str(req.get("codigo") or ""),
                str(req.get("nombre") or ""),
                str(req.get("descripcion") or ""),
            ]
        )
    )
    return any(k in blob for k in ("disponib", "horas", "dias", "transmit"))


def evaluar_requisitos_bloqueantes(
    *,
    requisitos: Optional[List[Dict[str, Any]]],
    perfil: Dict[str, Any],
    aspirante: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Impide avance solo cuando hay requisito configurado con bloquea_proceso=true
    e incumplimiento conocido.

    No inventa bloqueantes globales (p.ej. edad) si no existen en el catálogo.
    No trata categoria=obligatorio como sinónimo de bloquea_proceso.
    """
    asp = aspirante or {}
    mayor = perfil.get("mayor_edad")
    if mayor is None and asp.get("mayor_edad") is not None:
        mayor = bool(asp.get("mayor_edad"))

    incumplidos: List[str] = []
    evaluados: Dict[str, Any] = dict(perfil.get("requisitos_evaluados") or {})

    for req in requisitos or []:
        if not req or req.get("activo") is False:
            continue
        # Solo los que realmente bloquean el proceso.
        if not _requisito_es_bloqueante(req):
            continue

        codigo = str(
            req.get("codigo") or req.get("id") or req.get("nombre") or "requisito"
        )

        if _es_requisito_mayor_edad(req):
            if mayor is False:
                incumplidos.append("mayor_edad")
                evaluados["mayor_edad"] = False
            elif mayor is True:
                evaluados["mayor_edad"] = True
            continue

        if _es_requisito_disponibilidad(req):
            disp = perfil.get("disponibilidad_live")
            if disp is None and asp.get("disponibilidad_live") is not None:
                disp = bool(asp.get("disponibilidad_live"))
            vmin = req.get("valor_minimo")
            horas = perfil.get("horas_disponibles_dia")
            cumple = None
            if disp is False:
                cumple = False
            elif horas is not None and vmin is not None:
                try:
                    cumple = float(horas) >= float(vmin)
                except (TypeError, ValueError):
                    cumple = bool(disp) if disp is not None else None
            elif disp is True:
                cumple = True
            if cumple is False:
                incumplidos.append(str(codigo))
                evaluados[str(codigo)] = False
            elif cumple is True:
                evaluados[str(codigo)] = True

    incumplidos = sorted(set(incumplidos))
    logger.info(
        "[CHATBOT_REQUISITOS] bloqueantes_incumplidos=%s mayor_edad=%s",
        incumplidos,
        mayor,
    )
    return {
        "bloqueantes_incumplidos": incumplidos,
        "requisitos_evaluados": evaluados,
        "puede_incorporarse": len(incumplidos) == 0,
    }


def normalizar_accion(accion: str) -> str:
    a = str(accion or "").strip().lower()
    return _ACCIONES_ALIAS.get(a, a)


def puede_ejecutar_accion(
    *,
    accion: str,
    conversacion: Optional[Dict[str, Any]] = None,
    aspirante: Optional[Dict[str, Any]] = None,
    perfil: Optional[Dict[str, Any]] = None,
    flujo: Optional[Dict[str, Any]] = None,
    paso: Optional[Dict[str, Any]] = None,
    requisitos: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Gate central: el backend decide si la acción de conversión está permitida."""
    accion_n = normalizar_accion(accion)
    perfil = perfil or leer_perfil(conversacion, aspirante)
    evaluacion = evaluar_requisitos_bloqueantes(
        requisitos=requisitos,
        perfil=perfil,
        aspirante=aspirante,
    )
    bloqueantes = list(evaluacion.get("bloqueantes_incumplidos") or [])

    gateadas = ACCIONES_GATEADAS | {
        "enviar_solicitud",
        "agendar_live",
        "solicitar_evidencias",
        "crear_tarea_candidato",
        "enviar_enlace",
        "enviar_enlace_autorizado",
        "preparar_prueba_live",
        "solicitar_live",
        "avanzar_incorporacion",
    }
    if accion_n not in gateadas:
        return {
            "permitida": True,
            "motivo": "accion_no_gateada",
            "bloqueantes": [],
            "accion": accion_n,
        }

    if bloqueantes:
        logger.info(
            "[CHATBOT_ACTION_GATE] accion=%s permitida=false "
            "motivo=requisito_bloqueante bloqueantes=%s",
            accion_n,
            bloqueantes,
        )
        return {
            "permitida": False,
            "motivo": "requisito_bloqueante",
            "bloqueantes": bloqueantes,
            "accion": accion_n,
        }

    if accion_n in {"agendar_live", "preparar_prueba_live", "solicitar_live"}:
        paso = paso or {}
        tipo = str(paso.get("tipo_accion") or "").strip().lower()
        if tipo and tipo not in {"agendar_live", "solicitar_live", "enviar_enlace"}:
            logger.info(
                "[CHATBOT_ACTION_GATE] accion=%s permitida=false motivo=paso_no_autoriza_live",
                accion_n,
            )
            return {
                "permitida": False,
                "motivo": "paso_no_autoriza_live",
                "bloqueantes": [],
                "accion": accion_n,
            }
        if not (flujo or {}).get("id") and not (conversacion or {}).get("flujo_id"):
            logger.info(
                "[CHATBOT_ACTION_GATE] accion=%s permitida=false motivo=sin_flujo",
                accion_n,
            )
            return {
                "permitida": False,
                "motivo": "sin_flujo",
                "bloqueantes": [],
                "accion": accion_n,
            }

    logger.info(
        "[CHATBOT_ACTION_GATE] accion=%s permitida=true motivo=ok",
        accion_n,
    )
    return {
        "permitida": True,
        "motivo": "ok",
        "bloqueantes": [],
        "accion": accion_n,
    }


def mensaje_bloqueo_para_usuario(
    gate: Dict[str, Any],
    *,
    perfil: Optional[Dict[str, Any]] = None,
) -> str:
    bloqueantes = gate.get("bloqueantes") or []
    perfil = perfil or {}
    if "mayor_edad" in bloqueantes:
        edad = perfil.get("edad")
        if edad:
            return (
                f"Me comentaste que tienes {edad} años y la mayoría de edad es un "
                "requisito obligatorio para continuar. Por ahora no puedo avanzar "
                "con la solicitud ni con la incorporación."
            )
        return (
            "Me comentaste que eres menor de 18 años y la mayoría de edad es un "
            "requisito obligatorio para continuar. Por ahora no puedo avanzar "
            "con la solicitud ni con la incorporación."
        )
    if bloqueantes:
        return (
            "Por ahora no puedo avanzar con la incorporación porque hay un "
            "requisito obligatorio que aún no se cumple. Puedo seguir resolviendo "
            "tus dudas sobre la agencia."
        )
    if str(gate.get("motivo") or "") == "paso_no_autoriza_live":
        return (
            "Todavía no corresponde avanzar con la prueba LIVE en este punto "
            "del proceso. Sigamos con el paso actual."
        )
    return (
        "Por ahora no puedo ejecutar esa acción. Puedo seguir ayudándote "
        "con información sobre la agencia."
    )


def dato_ya_confirmado(perfil: Dict[str, Any], campo: str) -> bool:
    if campo in {"mayor_edad", "edad"}:
        return perfil.get("mayor_edad") is not None or perfil.get("edad") is not None
    if campo in {"disponibilidad", "disponibilidad_live"}:
        return perfil.get("disponibilidad_live") is not None or (
            perfil.get("horas_disponibles_dia") is not None
            and perfil.get("dias_disponibles") is not None
        )
    if campo == "nivel_experiencia":
        nivel = str(perfil.get("nivel_experiencia") or "desconocido")
        return nivel in {"principiante", "experimentado"} and bool(
            perfil.get("nivel_experiencia_confirmado")
        )
    return perfil.get(campo) is not None


def paso_resuelto_por_perfil(
    paso: Optional[Dict[str, Any]],
    perfil: Dict[str, Any],
) -> bool:
    """True si el paso pregunta algo ya confirmado en el perfil."""
    if not paso:
        return False
    codigo = _normalizar(str(paso.get("codigo") or ""))
    nombre = _normalizar(str(paso.get("nombre") or ""))
    tipo = str(paso.get("tipo_accion") or "").lower()
    if tipo not in {"hacer_pregunta", "esperar_respuesta"}:
        return False

    if any(k in codigo or k in nombre for k in ("edad", "mayor", "mayoria")):
        if dato_ya_confirmado(perfil, "mayor_edad"):
            logger.info(
                "[CHATBOT_MEMORIA] campo=mayor_edad accion=usar_valor_existente valor=%s",
                perfil.get("mayor_edad"),
            )
            return True

    if "disponib" in codigo or "disponib" in nombre:
        if dato_ya_confirmado(perfil, "disponibilidad_live"):
            logger.info(
                "[CHATBOT_MEMORIA] campo=disponibilidad_live accion=usar_valor_existente"
            )
            return True
    return False


def reevaluar_nivel_si_corresponde(
    *,
    conversacion: Dict[str, Any],
    aspirante: Optional[Dict[str, Any]],
    perfil: Dict[str, Any],
    hechos: Dict[str, Any],
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    conv = conversacion or {}
    asp = aspirante or {}
    if conv.get("nivel_experiencia_bloqueado_manual") or asp.get(
        "nivel_experiencia_bloqueado_manual"
    ):
        return perfil, None

    if not hechos.get("experiencia_requiere_reevaluacion"):
        return perfil, None

    detalle = (
        hechos.get("experiencia_detalle")
        if isinstance(hechos.get("experiencia_detalle"), dict)
        else {}
    ) or {}
    nivel_ant = str(
        perfil.get("nivel_experiencia")
        or conv.get("nivel_experiencia")
        or "desconocido"
    ).lower()

    nivel_nuevo = nivel_ant
    motivo = None
    if detalle.get("experiencia_limitada") or detalle.get("lives_aproximados") == 1:
        nivel_nuevo = "principiante"
        motivo = "informacion_explicita_nueva_experiencia_limitada"
    elif (
        detalle.get("duracion_minutos") is not None
        and int(detalle.get("duracion_minutos") or 0) <= 15
        and int(detalle.get("lives_aproximados") or 1) <= 1
    ):
        nivel_nuevo = "principiante"
        motivo = "informacion_explicita_nueva_experiencia_corta"

    perfil = dict(perfil)
    perfil["experiencia_detalle"] = {
        **dict(perfil.get("experiencia_detalle") or {}),
        **detalle,
    }
    if not motivo or nivel_nuevo == nivel_ant:
        return perfil, None

    perfil["nivel_experiencia"] = nivel_nuevo
    perfil["nivel_experiencia_confianza"] = 0.85
    perfil["nivel_experiencia_confirmado"] = True
    logger.info(
        "[CHATBOT_REEVALUACION] nivel_anterior=%s nivel_nuevo=%s motivo=%s",
        nivel_ant,
        nivel_nuevo,
        motivo,
    )
    return perfil, {
        "nivel_experiencia": nivel_nuevo,
        "nivel_experiencia_fuente": "declarada",
        "nivel_experiencia_confianza": 0.85,
        "nivel_experiencia_confirmado": True,
    }


def consultar_conocimiento_puro(
    *,
    tipo: str,
    requisitos: Optional[List[Dict[str, Any]]] = None,
    beneficios: Optional[List[Dict[str, Any]]] = None,
    faqs: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Conocimiento autorizado SIN navegación del informativo."""
    tipo_n = str(tipo or "").strip().lower()

    def _lineas_items(items: List[Dict[str, Any]], titulo: str) -> str:
        if not items:
            return (
                f"No tengo {titulo.lower()} configurados para compartir "
                "en este momento."
            )
        out = [titulo + ":", ""]
        for i, it in enumerate(items, start=1):
            nombre = str(it.get("nombre") or it.get("titulo") or "").strip()
            desc = str(
                it.get("descripcion")
                or it.get("texto_autorizado")
                or it.get("descripcion_corta")
                or it.get("detalle")
                or ""
            ).strip()
            if not nombre and not desc:
                continue
            if nombre and desc and desc != nombre:
                out.append(f"{i}. {nombre}: {desc}")
            else:
                out.append(f"{i}. {nombre or desc}")
        return "\n".join(out).strip()

    if tipo_n == "requisitos":
        items = [
            r
            for r in (requisitos or [])
            if r
            and r.get("activo") is not False
            and r.get("permitir_mencion_automatica") is not False
            and r.get("visible_publicamente") is not False
        ]
        return _lineas_items(items, "Requisitos")

    if tipo_n in {"beneficios", "bonos"}:
        items = []
        for b in beneficios or []:
            if not b or b.get("activo") is False:
                continue
            if b.get("permitir_mencion_automatica") is False:
                continue
            if b.get("visible_publicamente") is False:
                continue
            tipo_b = str(b.get("tipo") or "").lower()
            if tipo_n == "bonos" and tipo_b not in {"bono", "incentivo"}:
                continue
            if tipo_n == "beneficios" and tipo_b in {"bono", "incentivo"}:
                continue
            items.append(b)
        return _lineas_items(
            items, "Bonos e incentivos" if tipo_n == "bonos" else "Beneficios"
        )

    if tipo_n in {"agencia", "faq"}:
        for f in faqs or []:
            preg = _normalizar(str(f.get("pregunta") or ""))
            if tipo_n == "agencia" and not any(
                k in preg for k in ("agencia", "funcion", "como funciona", "somos")
            ):
                continue
            resp = str(
                f.get("respuesta_completa") or f.get("respuesta_corta") or ""
            ).strip()
            if resp:
                return resp
        if tipo_n == "agencia":
            return (
                "Puedo contarte cómo funciona nuestra agencia y qué ofrece, "
                "pero no tengo información confirmada para compararla "
                "directamente con otras agencias."
            )
        return "No encontré una respuesta confirmada para esa consulta."

    return ""


def actualizar_perfil_desde_mensaje(
    *,
    conversacion: Dict[str, Any],
    aspirante: Optional[Dict[str, Any]],
    texto: str,
    requisitos: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Extraer hechos → fusionar → reevaluar → evaluar bloqueantes."""
    hechos = extraer_hechos_de_texto(texto)
    perfil = leer_perfil(conversacion, aspirante)
    if hechos:
        perfil = fusionar_hechos_en_perfil(perfil, hechos)

    perfil, campos_nivel = reevaluar_nivel_si_corresponde(
        conversacion=conversacion,
        aspirante=aspirante,
        perfil=perfil,
        hechos=hechos,
    )

    if perfil.get("horas_disponibles_dia") is not None or perfil.get(
        "dias_disponibles"
    ) is not None:
        perfil["disponibilidad_live"] = True
        logger.info(
            "[CHATBOT_PERFIL] disponibilidad=true horas=%s dias=%s",
            perfil.get("horas_disponibles_dia"),
            perfil.get("dias_disponibles"),
        )

    evaluacion = evaluar_requisitos_bloqueantes(
        requisitos=requisitos,
        perfil=perfil,
        aspirante=aspirante,
    )
    perfil["requisitos_evaluados"] = evaluacion.get("requisitos_evaluados") or {}
    perfil["puede_incorporarse"] = evaluacion.get("puede_incorporarse")
    perfil["bloqueantes_incumplidos"] = evaluacion.get("bloqueantes_incumplidos") or []

    escribir_perfil_en_contexto(conversacion, perfil)

    campos_asp: Dict[str, Any] = {}
    if "mayor_edad" in hechos and hechos.get("mayor_edad") is not None:
        campos_asp["mayor_edad"] = bool(hechos["mayor_edad"])
    if "disponibilidad_live" in hechos and hechos.get("disponibilidad_live") is not None:
        campos_asp["disponibilidad_live"] = bool(hechos["disponibilidad_live"])
    elif perfil.get("disponibilidad_live") is True and (
        "horas_disponibles_dia" in hechos or "dias_disponibles" in hechos
    ):
        campos_asp["disponibilidad_live"] = True

    campos_conv: Dict[str, Any] = {"contexto": conversacion.get("contexto")}
    if campos_nivel:
        campos_conv.update(campos_nivel)
        conversacion.update(campos_nivel)

    logger.info(
        "[CHATBOT_PERFIL] nivel=%s mayor_edad=%s disponibilidad=%s "
        "puede_incorporarse=%s interes=%s",
        perfil.get("nivel_experiencia"),
        perfil.get("mayor_edad"),
        perfil.get("disponibilidad_live"),
        perfil.get("puede_incorporarse"),
        perfil.get("interes"),
    )
    return {
        "perfil": perfil,
        "hechos": hechos,
        "campos_aspirante": campos_asp,
        "campos_conversacion": campos_conv,
        "evaluacion": evaluacion,
    }
