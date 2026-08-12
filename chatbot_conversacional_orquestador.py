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
    hechos: Dict[str, Any] = field(default_factory=dict)
    perfil: Dict[str, Any] = field(default_factory=dict)
    herramientas_bloqueadas: List[str] = field(default_factory=list)


def _normalizar(texto: str) -> str:
    valor = str(texto or "").strip().lower()
    valor = unicodedata.normalize("NFD", valor)
    valor = "".join(ch for ch in valor if unicodedata.category(ch) != "Mn")
    valor = re.sub(r"[^\w\s]", " ", valor, flags=re.UNICODE)
    return re.sub(r"\s+", " ", valor).strip()


def interpretar_mensaje(
    texto: str,
    *,
    pregunta_pendiente: Optional[Dict[str, Any]] = None,
    perfil: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    n = _normalizar(texto)
    perfil = perfil or {}
    pendiente = pregunta_pendiente or {}
    out: Dict[str, Any] = {
        "intencion": "desconocida",
        "respuesta_pendiente": None,
        "ambigua_pendiente": False,
        "hechos_extra": {},
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

    if re.search(
        r"\b(hermana|hermano|amiga|amigo|prima|primo|referid|otra persona|alguien mas)\b",
        n,
    ) and re.search(r"\b(quiere|pued[eo]|entrar|unirse|proceso|decir|invitar)\b", n):
        out["intencion"] = "referido_tercero"
        logger.info("[CHATBOT_INTERPRETACION] intencion=referido_tercero")
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
        out["intencion"] = "respuesta_pendiente"
        out["ambigua_pendiente"] = True
        out["respuesta_pendiente"] = "ambigua"
        return out

    if pendiente and n in {"si", "sip", "claro", "ok", "okay", "vale", "de acuerdo", "no", "nop"}:
        out["intencion"] = "respuesta_pendiente"
        out["respuesta_pendiente"] = (
            "afirmativa"
            if n in {"si", "sip", "claro", "ok", "okay", "vale", "de acuerdo"}
            else "negativa"
        )
        return out

    if re.search(r"\b(agendar|agenda|quiero agendar|programar prueba)\b", n):
        out["intencion"] = "agendar_live"
        return out

    if out["hechos_extra"]:
        out["intencion"] = "actualizar_hechos"

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
        perfil["hechos"] = hechos

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

    if interp.get("ambigua_pendiente") and isinstance(pendiente, dict):
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

    # Sí/no claro a pregunta pendiente: no reinterpretar como nueva intención.
    if intencion == "respuesta_pendiente":
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
                retomar_pendiente=bool(pendiente),
                dato_pendiente=pendiente if isinstance(pendiente, dict) else None,
            )
        )

    if intencion == "consultar_fecha_pago_bono":
        return _fin(
            DecisionTurno(
                tipo="informar",
                texto_base=_texto_fecha_pago_bono(beneficios),
                motivo="fecha_pago_bono",
                intencion=intencion,
                retomar_pendiente=bool(pendiente),
                dato_pendiente=pendiente if isinstance(pendiente, dict) else None,
            )
        )

    if intencion == "diferenciadores_agencia":
        return _fin(
            DecisionTurno(
                tipo="informar",
                texto_base=_texto_diferenciadores(requisitos, beneficios, faqs),
                motivo="sin_comparativa_confirmada",
                intencion=intencion,
                retomar_pendiente=bool(pendiente),
                dato_pendiente=pendiente if isinstance(pendiente, dict) else None,
            )
        )

    if intencion in {"bonos", "beneficios", "requisitos", "agencia"}:
        retomar = bool(pendiente)
        pend_usar = pendiente if isinstance(pendiente, dict) else None
        if (
            isinstance(pendiente, dict)
            and str(pendiente.get("campo") or "") == "nivel_experiencia"
            and str(perfil.get("nivel_experiencia") or "")
            in {"principiante", "experimentado"}
        ):
            retomar = False
            pend_usar = None
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
                dato_pendiente=pend_usar,
            )
        )

    if intencion == "proceso":
        return _fin(
            DecisionTurno(
                tipo="informar",
                accion="proceso",
                motivo="consultar_proceso",
                intencion=intencion,
                retomar_pendiente=bool(pendiente),
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
        tipo_paso = str((paso or {}).get("tipo_accion") or "").lower()
        if tipo_paso in {
            "enviar_enlace",
            "agendar_live",
            "solicitar_live",
            "solicitar_evidencias",
        }:
            accion_gate = (
                "enviar_solicitud" if tipo_paso == "enviar_enlace" else tipo_paso
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
