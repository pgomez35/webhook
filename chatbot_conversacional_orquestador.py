"""
Orquestador determinista del chatbot INTELIGENTE.

BACKEND decide estado y accion. La IA interpreta y redacta.
No es un tercer motor: reutiliza perfil, gates, flujo y tools existentes.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from chatbot_conversacional_perfil import (
    consultar_conocimiento_puro,
    extraer_hechos_de_texto,
    leer_perfil,
    mensaje_bloqueo_para_usuario,
    puede_ejecutar_accion,
)

logger = logging.getLogger("uvicorn.error")

HERRAMIENTAS_CONVERSION = frozenset(
    {
        "enviar_enlace_autorizado",
        "crear_tarea_candidato",
        "preparar_prueba_live",
        "solicitar_evidencias",
        "registrar_evidencia_recibida",
        "confirmar_interes",
    }
)

_PASOS_CONVERSION = frozenset(
    {
        "confirmar_interes",
        "enviar_enlace",
        "enviar_solicitud",
        "agendar_live",
        "solicitar_live",
        "solicitar_evidencias",
        "crear_tarea_candidato",
        "avanzar_incorporacion",
        "preparar_prueba_live",
    }
)


@dataclass
class DecisionTurno:
    tipo: str
    accion: Optional[str] = None
    paso_id: Optional[Any] = None
    texto_base: Optional[str] = None
    dato_pendiente: Optional[Dict[str, Any]] = None
    motivo: Optional[str] = None
    intencion: Optional[str] = None
    gate: Optional[Dict[str, Any]] = None
    retomar_pendiente: bool = False
    cancelar_pendiente: bool = False
    hechos: Dict[str, Any] = field(default_factory=dict)
    perfil: Dict[str, Any] = field(default_factory=dict)
    herramientas_bloqueadas: List[str] = field(default_factory=list)


def _normalizar(texto: str) -> str:
    valor = str(texto or "").strip().lower()
    valor = unicodedata.normalize("NFD", valor)
    valor = "".join(ch for ch in valor if unicodedata.category(ch) != "Mn")
    valor = re.sub(r"[^\w\s]", " ", valor, flags=re.UNICODE)
    return re.sub(r"\s+", " ", valor).strip()


def _perfil_bloqueado(perfil: Optional[Dict[str, Any]]) -> bool:
    perfil = perfil or {}
    if perfil.get("puede_incorporarse") is False:
        return True
    return bool(perfil.get("bloqueantes_incumplidos"))


def _pendiente_es_incorporacion(pendiente: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(pendiente, dict):
        return False
    tipo = str(pendiente.get("tipo") or "").strip().lower()
    campo = str(pendiente.get("campo") or "").strip().lower()
    if tipo in _PASOS_CONVERSION or tipo == "confirmar_interes":
        return True
    if "interes" in campo or "confirmar_interes" in campo:
        return True
    texto = _normalizar(str(pendiente.get("texto") or ""))
    return "continuar con el proceso" in texto or "te gustaria continuar" in texto


def _paso_es_conversion(paso: Optional[Dict[str, Any]]) -> bool:
    tipo = str((paso or {}).get("tipo_accion") or "").strip().lower()
    return tipo in _PASOS_CONVERSION


def interpretar_mensaje(
    texto: str,
    *,
    pregunta_pendiente: Optional[Dict[str, Any]] = None,
    perfil: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    n = _normalizar(texto)
    perfil = perfil or {}
    pendiente = pregunta_pendiente or {}
    hechos = extraer_hechos_de_texto(texto)
    out: Dict[str, Any] = {
        "intencion": "desconocida",
        "respuesta_pendiente": None,
        "ambigua_pendiente": False,
        "hechos_extra": dict(hechos),
        "texto_normalizado": n,
    }
    if not n:
        return out

    if re.search(
        r"\b(cumplo\s+18|manana cumplo|en un dia cumplo|en unos dias cumplo|"
        r"casi cumplo|voy a cumplir 18)\b",
        n,
    ):
        out["hechos_extra"]["edad_cumple_pronto"] = True
        out["hechos_extra"]["mayor_edad"] = False

    # Hechos explícitos tienen prioridad alta sobre fallback de flujo.
    if any(
        k in out["hechos_extra"]
        for k in ("edad", "mayor_edad", "horas_disponibles_dia", "dias_disponibles")
    ):
        out["intencion"] = "dato_explicito"

    if re.search(
        r"\b(hermana|hermano|amiga|amigo|prima|primo|referid|otra persona|alguien mas)\b",
        n,
    ) and re.search(r"\b(quiere|pued[eo]|entrar|unirse|proceso|decir|invitar)\b", n):
        out["intencion"] = "referido_tercero"
        logger.info(
            "[CHATBOT_INTERPRETACION] intencion=referido_tercero hechos_extraidos=%s",
            list(out["hechos_extra"].keys()),
        )
        return out

    if (
        re.search(r"\b(fecha|cuando|dia)\b", n)
        and re.search(r"\b(pagan?|pago|cobr\w*)\b", n)
        and re.search(r"\b(bonos?|incentivos?|bienvenida|incorporacion)\b", n)
    ):
        out["intencion"] = "consultar_fecha_pago_bono"
        logger.info("[CHATBOT_INTERPRETACION] intencion=consultar_fecha_pago_bono")
        return out

    if re.search(
        r"\b(diferencia|distingu|mejor que|comparad|otras agencias|otra agencia|vs|versus)\b",
        n,
    ):
        out["intencion"] = "diferenciadores_agencia"
        logger.info("[CHATBOT_INTERPRETACION] intencion=diferenciadores_agencia")
        return out

    # Negativa a continuar / confirmar interés (antes del fallback).
    if re.search(
        r"\b(no quiero|no me interesa|no deseo|ahora no|mejor no|no gracias|"
        r"no continuar|no quiero continuar|no quiero ingresar)\b",
        n,
    ) or (
        pendiente
        and _pendiente_es_incorporacion(pendiente)
        and n in {"no", "nop", "nel", "negativo"}
    ):
        out["intencion"] = "respuesta_no"
        out["respuesta_pendiente"] = "negativa"
        out["hechos_extra"]["interes"] = False
        logger.info("[CHATBOT_INTERPRETACION] intencion=respuesta_no")
        return out

    if re.search(r"\b(bonos?|incentivos?)\b", n):
        out["intencion"] = "bonos"
        return out
    if re.search(r"\b(beneficios?)\b", n):
        out["intencion"] = "beneficios"
        return out
    if re.search(r"\b(requisitos?|que piden)\b", n):
        out["intencion"] = "requisitos"
        return out
    if re.search(
        r"\b(cual es el proceso|como es el proceso|como ingreso|como entro|pasos para)\b",
        n,
    ):
        out["intencion"] = "proceso"
        return out

    # Pregunta informativa (diamantes, regalos, cómo funciona, qué es…).
    if (
        "?" in str(texto or "")
        or "¿" in str(texto or "")
        or re.search(
            r"\b(que son|que es|cuales son|como funciona|como es|"
            r"diamantes|regalos|agencia)\b",
            n,
        )
    ) and not re.search(
        r"\b(quiero ingresar|quiero entrar|agendar|enviame el)\b",
        n,
    ):
        # Evitar clasificar afirmaciones cortas como pregunta.
        if re.search(
            r"\b(que|cual|cuales|como|donde|cuando|por que|para que)\b",
            n,
        ) or re.search(r"\b(diamantes|regalos)\b", n):
            out["intencion"] = "pregunta_informativa"
            logger.info("[CHATBOT_INTERPRETACION] intencion=pregunta_informativa")
            return out

    if re.search(
        r"\b(quiero ingresar|quiero entrar|quiero unirme|si quiero ingresar|"
        r"enviame el (enlace|link)|mandame el (enlace|link)|quiero la solicitud)\b",
        n,
    ):
        out["intencion"] = "quiero_ingresar"
        return out

    if pendiente and n in {
        "mas o menos",
        "masomenos",
        "regular",
        "no se",
        "nose",
        "depende",
        "algunas",
        "algunos",
        "a veces",
    }:
        out["intencion"] = "respuesta_ambigua"
        out["ambigua_pendiente"] = True
        out["respuesta_pendiente"] = "ambigua"
        return out

    if pendiente and n in {
        "si",
        "sip",
        "claro",
        "ok",
        "okay",
        "vale",
        "de acuerdo",
        "bueno",
        "dale",
        "va",
    }:
        out["intencion"] = "respuesta_si"
        out["respuesta_pendiente"] = "afirmativa"
        return out

    if re.search(r"\b(agendar|agenda|quiero agendar|programar prueba)\b", n):
        out["intencion"] = "agendar_live"
        return out

    if out["intencion"] == "dato_explicito":
        logger.info(
            "[CHATBOT_INTERPRETACION] intencion=dato_explicito hechos_extraidos=%s",
            {k: out["hechos_extra"].get(k) for k in ("edad", "mayor_edad") if k in out["hechos_extra"]},
        )
        return out

    if out["hechos_extra"] and out["intencion"] == "desconocida":
        out["intencion"] = "dato_explicito"

    logger.info(
        "[CHATBOT_INTERPRETACION] intencion=%s ambigua_pendiente=%s hechos_extra=%s",
        out["intencion"],
        out["ambigua_pendiente"],
        list((out.get("hechos_extra") or {}).keys()),
    )
    return out


def _texto_fecha_pago_bono(beneficios: Optional[List[Dict[str, Any]]]) -> str:
    fechas: List[str] = []
    for b in beneficios or []:
        if not b or b.get("activo") is False:
            continue
        tipo = str(b.get("tipo") or "").lower()
        nom = str(b.get("nombre") or "")
        if tipo not in {"bono", "incentivo", ""} and "bono" not in nom.lower():
            continue
        for clave in ("fecha_pago", "fecha_de_pago", "dia_pago", "cuando_se_paga"):
            valor = str(b.get(clave) or "").strip()
            if valor:
                fechas.append(f"{nom or 'Bono'}: {valor}")
        desc = str(
            b.get("texto_autorizado")
            or b.get("descripcion_completa")
            or b.get("descripcion")
            or ""
        )
        if re.search(r"(?i)fecha\s+de\s+pago|se\s+paga\s+el|pago\s+el\s+\d", desc):
            fechas.append(f"{nom or 'Bono'}: {desc[:200]}")
    if fechas:
        return "Sobre la fecha de pago:\n\n" + "\n".join(f"- {f}" for f in fechas)
    return (
        "Tengo información sobre los bonos disponibles, pero no tengo una "
        "fecha de pago confirmada. Ese dato debe confirmarlo el equipo."
    )


def _texto_referido() -> str:
    return (
        "Sí, puede comunicarse con la agencia para conocer los requisitos y "
        "comenzar su propio proceso. Si quieres, le puedes compartir este mismo "
        "canal para que inicie su conversación."
    )


def _texto_diferenciadores(
    requisitos: Optional[List[Dict[str, Any]]],
    beneficios: Optional[List[Dict[str, Any]]],
    faqs: Optional[List[Dict[str, Any]]],
) -> str:
    return (
        "Puedo explicarte cómo funciona nuestra agencia y lo que ofrece, "
        "pero no tengo información confirmada para compararla directamente "
        "con otras agencias."
    )


def _texto_pregunta_informativa(
    texto: str,
    *,
    requisitos: Optional[List[Dict[str, Any]]],
    beneficios: Optional[List[Dict[str, Any]]],
    faqs: Optional[List[Dict[str, Any]]],
) -> str:
    n = _normalizar(texto)
    if "beneficio" in n:
        return consultar_conocimiento_puro(
            tipo="beneficios",
            requisitos=requisitos,
            beneficios=beneficios,
            faqs=faqs,
        )
    if "bono" in n or "incentivo" in n:
        return consultar_conocimiento_puro(
            tipo="bonos",
            requisitos=requisitos,
            beneficios=beneficios,
            faqs=faqs,
        )
    if "requisito" in n:
        return consultar_conocimiento_puro(
            tipo="requisitos",
            requisitos=requisitos,
            beneficios=beneficios,
            faqs=faqs,
        )

    tokens = [t for t in n.split() if len(t) >= 4]
    mejor = None
    mejor_score = 0
    for f in faqs or []:
        if not f or f.get("activo") is False:
            continue
        blob = _normalizar(
            " ".join(
                [
                    str(f.get("pregunta") or ""),
                    str(f.get("respuesta_corta") or ""),
                    str(f.get("respuesta_completa") or ""),
                    " ".join(str(x) for x in (f.get("palabras_clave") or []) if x),
                ]
            )
        )
        score = sum(1 for t in tokens if t in blob)
        if score > mejor_score:
            mejor_score = score
            mejor = f
    if mejor and mejor_score > 0:
        resp = str(
            mejor.get("respuesta_completa")
            or mejor.get("respuesta_corta")
            or ""
        ).strip()
        if resp:
            return resp

    if "agencia" in n or "funciona" in n:
        return consultar_conocimiento_puro(
            tipo="agencia",
            requisitos=requisitos,
            beneficios=beneficios,
            faqs=faqs,
        )
    return (
        "Puedo ayudarte con esa consulta con la información confirmada que "
        "tengo. Si me precisas un poco más, te respondo con más detalle."
    )


def _herramientas_bloqueadas_por_gate(
    *,
    conversacion: Dict[str, Any],
    aspirante: Optional[Dict[str, Any]],
    perfil: Dict[str, Any],
    flujo: Optional[Dict[str, Any]],
    paso: Optional[Dict[str, Any]],
    requisitos: Optional[List[Dict[str, Any]]],
) -> List[str]:
    bloqueadas: List[str] = []
    mapa = {
        "enviar_enlace_autorizado": "enviar_solicitud",
        "crear_tarea_candidato": "crear_tarea_candidato",
        "preparar_prueba_live": "agendar_live",
        "solicitar_evidencias": "solicitar_evidencias",
        "registrar_evidencia_recibida": "solicitar_evidencias",
        "confirmar_interes": "enviar_solicitud",
    }
    for tool, accion in mapa.items():
        gate = puede_ejecutar_accion(
            accion=accion,
            conversacion=conversacion,
            aspirante=aspirante,
            perfil=perfil,
            flujo=flujo,
            paso=paso,
            requisitos=requisitos,
        )
        if not gate.get("permitida"):
            bloqueadas.append(tool)
    return bloqueadas


def _decision_bloqueo(
    *,
    perfil: Dict[str, Any],
    intencion: str,
    paso: Optional[Dict[str, Any]] = None,
) -> DecisionTurno:
    bloqueantes = list(perfil.get("bloqueantes_incumplidos") or [])
    gate = {
        "permitida": False,
        "motivo": "requisito_bloqueante",
        "bloqueantes": bloqueantes,
        "accion": "avanzar_incorporacion",
    }
    return DecisionTurno(
        tipo="bloqueado",
        accion="avanzar_incorporacion",
        texto_base=mensaje_bloqueo_para_usuario(gate, perfil=perfil),
        motivo="requisito_bloqueante",
        intencion=intencion,
        gate=gate,
        cancelar_pendiente=_pendiente_es_incorporacion(
            {"tipo": str((paso or {}).get("tipo_accion") or "confirmar_interes")}
        )
        or True,
        paso_id=(paso or {}).get("id"),
    )


def resolver_turno_inteligente(
    *,
    texto: str,
    conversacion: Dict[str, Any],
    aspirante: Optional[Dict[str, Any]] = None,
    perfil: Optional[Dict[str, Any]] = None,
    flujo: Optional[Dict[str, Any]] = None,
    paso: Optional[Dict[str, Any]] = None,
    requisitos: Optional[List[Dict[str, Any]]] = None,
    beneficios: Optional[List[Dict[str, Any]]] = None,
    faqs: Optional[List[Dict[str, Any]]] = None,
    pregunta_pendiente: Optional[Dict[str, Any]] = None,
    nivel_abierto: bool = False,
) -> DecisionTurno:
    perfil = perfil or leer_perfil(conversacion, aspirante)
    pendiente = pregunta_pendiente
    if pendiente is None:
        ctx = conversacion.get("contexto") or {}
        if isinstance(ctx, dict):
            pendiente = ctx.get("pregunta_pendiente")

    interp = interpretar_mensaje(
        texto,
        pregunta_pendiente=pendiente if isinstance(pendiente, dict) else None,
        perfil=perfil,
    )
    intencion = interp.get("intencion") or "desconocida"
    hechos_extra = dict(interp.get("hechos_extra") or {})
    if hechos_extra.get("mayor_edad") is False:
        perfil = dict(perfil)
        perfil["mayor_edad"] = False
        hechos = dict(perfil.get("hechos") or {})
        if hechos_extra.get("edad_cumple_pronto"):
            hechos["edad_cumple_pronto"] = True
        if "edad" in hechos_extra:
            perfil["edad"] = hechos_extra["edad"]
            hechos["edad"] = hechos_extra["edad"]
        perfil["hechos"] = hechos
    if hechos_extra.get("interes") is False:
        perfil = dict(perfil)
        perfil["interes"] = False
    if hechos_extra.get("interes") is True:
        perfil = dict(perfil)
        perfil["interes"] = True

    # Releer bloqueantes del perfil ya actualizado (autoridad).
    bloqueadas = _herramientas_bloqueadas_por_gate(
        conversacion=conversacion,
        aspirante=aspirante,
        perfil=perfil,
        flujo=flujo,
        paso=paso,
        requisitos=requisitos,
    )

    logger.info(
        "[CHATBOT_ESTADO] puede_incorporarse=%s bloqueantes=%s nivel=%s",
        perfil.get("puede_incorporarse"),
        perfil.get("bloqueantes_incumplidos"),
        perfil.get("nivel_experiencia"),
    )

    def _retomar_ok() -> bool:
        if not isinstance(pendiente, dict):
            return False
        if _perfil_bloqueado(perfil) and _pendiente_es_incorporacion(pendiente):
            return False
        if perfil.get("interes") is False and _pendiente_es_incorporacion(pendiente):
            return False
        if (
            str(pendiente.get("campo") or "") == "nivel_experiencia"
            and str(perfil.get("nivel_experiencia") or "")
            in {"principiante", "experimentado"}
        ):
            return False
        return True

    def _fin(d: DecisionTurno) -> DecisionTurno:
        logger.info(
            "[CHATBOT_DECISION] tipo=%s accion=%s paso_id=%s motivo=%s intencion=%s",
            d.tipo,
            d.accion,
            d.paso_id,
            d.motivo,
            d.intencion,
        )
        d.perfil = perfil
        d.hechos = hechos_extra
        d.herramientas_bloqueadas = bloqueadas
        return d

    # PRIORIDAD ABSOLUTA: bloqueantes dominan sobre flujo_activo / confirmar_interes.
    # Salvo intenciones puramente informativas (se resuelven abajo sin conversión).
    intenciones_info = {
        "bonos",
        "beneficios",
        "requisitos",
        "agencia",
        "proceso",
        "pregunta_informativa",
        "consultar_fecha_pago_bono",
        "diferenciadores_agencia",
        "referido_tercero",
    }

    if _perfil_bloqueado(perfil) and intencion not in intenciones_info:
        # dato_explicito / desconocida / respuesta_si → bloqueado
        # (quiero_ingresar / agendar_live tienen handlers propios más abajo)
        if intencion in {
            "dato_explicito",
            "desconocida",
            "respuesta_si",
            "respuesta_pendiente",
            "actualizar_hechos",
        } or (
            intencion == "respuesta_ambigua"
            and _pendiente_es_incorporacion(pendiente if isinstance(pendiente, dict) else None)
        ):
            return _fin(_decision_bloqueo(perfil=perfil, intencion=intencion, paso=paso))

    if interp.get("ambigua_pendiente") and isinstance(pendiente, dict):
        if _perfil_bloqueado(perfil) and _pendiente_es_incorporacion(pendiente):
            return _fin(_decision_bloqueo(perfil=perfil, intencion=intencion, paso=paso))
        preg = _normalizar(str(pendiente.get("texto") or ""))
        if "requisito" in preg or "cumple" in preg:
            texto_q = (
                "Entiendo. ¿Cuál de los requisitos no cumples o no tienes claro?"
            )
        else:
            texto_q = (
                "No hay problema. ¿Puedes precisarme un poco más para continuar "
                "con lo que te pregunté?"
            )
        return _fin(
            DecisionTurno(
                tipo="preguntar",
                texto_base=texto_q,
                dato_pendiente=pendiente,
                motivo="respuesta_ambigua_pendiente",
                intencion=intencion,
                retomar_pendiente=True,
            )
        )

    if intencion == "respuesta_no":
        return _fin(
            DecisionTurno(
                tipo="informar",
                texto_base=(
                    "Entiendo. No avanzaremos con el proceso por ahora. "
                    "Si quieres, puedo seguir respondiendo tus dudas sobre la agencia."
                ),
                motivo="interes_rechazado",
                intencion=intencion,
                cancelar_pendiente=True,
                retomar_pendiente=False,
            )
        )

    if intencion in {"respuesta_si", "respuesta_pendiente"}:
        if _perfil_bloqueado(perfil):
            return _fin(_decision_bloqueo(perfil=perfil, intencion=intencion, paso=paso))
        return _fin(
            DecisionTurno(
                tipo="usar_agente",
                motivo="respuesta_clara_a_pendiente",
                intencion=intencion,
                dato_pendiente=pendiente if isinstance(pendiente, dict) else None,
            )
        )

    if intencion == "referido_tercero":
        return _fin(
            DecisionTurno(
                tipo="informar",
                texto_base=_texto_referido(),
                motivo="referido_tercero",
                intencion=intencion,
                retomar_pendiente=_retomar_ok(),
                cancelar_pendiente=not _retomar_ok() and _pendiente_es_incorporacion(
                    pendiente if isinstance(pendiente, dict) else None
                ),
                dato_pendiente=pendiente if _retomar_ok() and isinstance(pendiente, dict) else None,
            )
        )

    if intencion == "consultar_fecha_pago_bono":
        return _fin(
            DecisionTurno(
                tipo="informar",
                texto_base=_texto_fecha_pago_bono(beneficios),
                motivo="fecha_pago_bono",
                intencion=intencion,
                retomar_pendiente=_retomar_ok(),
                cancelar_pendiente=not _retomar_ok() and _pendiente_es_incorporacion(
                    pendiente if isinstance(pendiente, dict) else None
                ),
                dato_pendiente=pendiente if _retomar_ok() and isinstance(pendiente, dict) else None,
            )
        )

    if intencion == "diferenciadores_agencia":
        return _fin(
            DecisionTurno(
                tipo="informar",
                texto_base=_texto_diferenciadores(requisitos, beneficios, faqs),
                motivo="sin_comparativa_confirmada",
                intencion=intencion,
                retomar_pendiente=_retomar_ok(),
                cancelar_pendiente=not _retomar_ok() and _pendiente_es_incorporacion(
                    pendiente if isinstance(pendiente, dict) else None
                ),
                dato_pendiente=pendiente if _retomar_ok() and isinstance(pendiente, dict) else None,
            )
        )

    if intencion == "pregunta_informativa":
        return _fin(
            DecisionTurno(
                tipo="informar",
                texto_base=_texto_pregunta_informativa(
                    texto,
                    requisitos=requisitos,
                    beneficios=beneficios,
                    faqs=faqs,
                ),
                motivo="pregunta_informativa",
                intencion=intencion,
                retomar_pendiente=_retomar_ok(),
                cancelar_pendiente=not _retomar_ok() and _pendiente_es_incorporacion(
                    pendiente if isinstance(pendiente, dict) else None
                ),
                dato_pendiente=pendiente if _retomar_ok() and isinstance(pendiente, dict) else None,
            )
        )

    if intencion in {"bonos", "beneficios", "requisitos", "agencia"}:
        retomar = _retomar_ok()
        return _fin(
            DecisionTurno(
                tipo="informar",
                texto_base=consultar_conocimiento_puro(
                    tipo=intencion,
                    requisitos=requisitos,
                    beneficios=beneficios,
                    faqs=faqs,
                ),
                motivo=f"info_{intencion}",
                intencion=intencion,
                retomar_pendiente=retomar,
                cancelar_pendiente=not retomar and _pendiente_es_incorporacion(
                    pendiente if isinstance(pendiente, dict) else None
                ),
                dato_pendiente=pendiente if retomar and isinstance(pendiente, dict) else None,
            )
        )

    if intencion == "proceso":
        return _fin(
            DecisionTurno(
                tipo="informar",
                accion="proceso",
                motivo="consultar_proceso",
                intencion=intencion,
                retomar_pendiente=_retomar_ok(),
                cancelar_pendiente=not _retomar_ok() and _pendiente_es_incorporacion(
                    pendiente if isinstance(pendiente, dict) else None
                ),
                dato_pendiente=pendiente if _retomar_ok() and isinstance(pendiente, dict) else None,
            )
        )

    if intencion == "dato_explicito":
        if _perfil_bloqueado(perfil):
            return _fin(_decision_bloqueo(perfil=perfil, intencion=intencion, paso=paso))
        # Hecho nuevo sin bloqueo: no repetir confirmar_interes ciegamente.
        if _pendiente_es_incorporacion(pendiente if isinstance(pendiente, dict) else None):
            return _fin(
                DecisionTurno(
                    tipo="usar_agente",
                    motivo="dato_explicito_con_pendiente",
                    intencion=intencion,
                    dato_pendiente=pendiente if isinstance(pendiente, dict) else None,
                )
            )

    if intencion == "quiero_ingresar":
        gate = puede_ejecutar_accion(
            accion="enviar_solicitud",
            conversacion=conversacion,
            aspirante=aspirante,
            perfil=perfil,
            flujo=flujo,
            paso=paso,
            requisitos=requisitos,
        )
        if not gate.get("permitida"):
            return _fin(
                DecisionTurno(
                    tipo="bloqueado",
                    accion="enviar_solicitud",
                    texto_base=mensaje_bloqueo_para_usuario(gate, perfil=perfil),
                    motivo=str(gate.get("motivo") or "requisito_bloqueante"),
                    intencion=intencion,
                    gate=gate,
                    cancelar_pendiente=True,
                )
            )
        return _fin(
            DecisionTurno(
                tipo="ejecutar_accion",
                accion="enviar_solicitud",
                motivo="interes_y_elegible",
                intencion=intencion,
                gate=gate,
            )
        )

    if intencion == "agendar_live":
        gate = puede_ejecutar_accion(
            accion="agendar_live",
            conversacion=conversacion,
            aspirante=aspirante,
            perfil=perfil,
            flujo=flujo,
            paso=paso,
            requisitos=requisitos,
        )
        if not gate.get("permitida"):
            return _fin(
                DecisionTurno(
                    tipo="bloqueado",
                    accion="agendar_live",
                    texto_base=mensaje_bloqueo_para_usuario(gate, perfil=perfil),
                    motivo=str(gate.get("motivo") or "agendamiento_no_permitido"),
                    intencion=intencion,
                    gate=gate,
                    cancelar_pendiente=_pendiente_es_incorporacion(
                        pendiente if isinstance(pendiente, dict) else None
                    ),
                )
            )
        return _fin(
            DecisionTurno(
                tipo="ejecutar_accion",
                accion="agendar_live",
                motivo="agendamiento_autorizado",
                intencion=intencion,
                gate=gate,
            )
        )

    if nivel_abierto:
        return _fin(
            DecisionTurno(
                tipo="continuar_clasificacion",
                motivo="nivel_abierto",
                intencion=intencion,
            )
        )

    if (flujo or {}).get("id") or conversacion.get("flujo_id"):
        # Bloqueante domina sobre flujo_activo (nunca confirmar_interes).
        if _perfil_bloqueado(perfil):
            return _fin(_decision_bloqueo(perfil=perfil, intencion=intencion, paso=paso))
        if perfil.get("interes") is False and _paso_es_conversion(paso):
            return _fin(
                DecisionTurno(
                    tipo="informar",
                    texto_base=(
                        "Entiendo. No avanzaremos con el proceso por ahora. "
                        "Si quieres, puedo seguir respondiendo tus dudas sobre la agencia."
                    ),
                    motivo="interes_rechazado_flujo",
                    intencion=intencion,
                    cancelar_pendiente=True,
                )
            )

        tipo_paso = str((paso or {}).get("tipo_accion") or "").lower()
        if tipo_paso in {
            "enviar_enlace",
            "agendar_live",
            "solicitar_live",
            "solicitar_evidencias",
            "confirmar_interes",
        }:
            accion_gate = (
                "enviar_solicitud"
                if tipo_paso in {"enviar_enlace", "confirmar_interes"}
                else tipo_paso
            )
            gate = puede_ejecutar_accion(
                accion=accion_gate,
                conversacion=conversacion,
                aspirante=aspirante,
                perfil=perfil,
                flujo=flujo,
                paso=paso,
                requisitos=requisitos,
            )
            if not gate.get("permitida"):
                return _fin(
                    DecisionTurno(
                        tipo="bloqueado",
                        accion=accion_gate,
                        texto_base=mensaje_bloqueo_para_usuario(gate, perfil=perfil),
                        motivo=str(gate.get("motivo") or "paso_bloqueado"),
                        intencion=intencion,
                        gate=gate,
                        paso_id=(paso or {}).get("id"),
                        cancelar_pendiente=True,
                    )
                )
        return _fin(
            DecisionTurno(
                tipo="continuar_flujo",
                motivo="flujo_activo",
                intencion=intencion,
                paso_id=(paso or {}).get("id"),
            )
        )

    return _fin(
        DecisionTurno(
            tipo="usar_agente",
            motivo="requiere_comprension_abierta",
            intencion=intencion,
        )
    )
