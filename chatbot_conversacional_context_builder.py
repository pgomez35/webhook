"""
Construcción del contexto conversacional.

Carga acotada de configuración y catálogos vigentes de la agencia. Nunca se
consulta histórico completo: los mensajes y los catálogos se limitan para
mantener el prompt corto y el costo de tokens controlado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import chatbot_conversacional_db_gateway as gw
from chatbot_conversacional_exceptions import AgenciaMismatch, ConversacionalError
from chatbot_conversacional_mode_resolver import ResolucionModo, resolver_modo, tipo_flujo_para_modo

LIMITE_MENSAJES = 12
LIMITE_REQUISITOS = 20
LIMITE_BENEFICIOS = 15
LIMITE_FAQ = 12
LIMITE_RECURSOS = 15
LIMITE_EVIDENCIAS = 12
LIMITE_REGLAS = 10


@dataclass
class ConversationalContext:
    agencia_id: int
    conversacion: Dict[str, Any]
    canal: str
    modo: str
    resolucion_modo: ResolucionModo
    agencia: Dict[str, Any] = field(default_factory=dict)
    configuracion: Dict[str, Any] = field(default_factory=dict)
    asistente: Dict[str, Any] = field(default_factory=dict)
    aspirante: Optional[Dict[str, Any]] = None
    campania: Optional[Dict[str, Any]] = None
    flujo: Optional[Dict[str, Any]] = None
    paso: Optional[Dict[str, Any]] = None
    requisitos: List[Dict[str, Any]] = field(default_factory=list)
    beneficios: List[Dict[str, Any]] = field(default_factory=list)
    faqs: List[Dict[str, Any]] = field(default_factory=list)
    recursos: List[Dict[str, Any]] = field(default_factory=list)
    prueba_live: Optional[Dict[str, Any]] = None
    evidencias_requeridas: List[Dict[str, Any]] = field(default_factory=list)
    reglas_escalamiento: List[Dict[str, Any]] = field(default_factory=list)
    mensajes: List[Dict[str, Any]] = field(default_factory=list)
    resumen_contexto: Optional[str] = None
    dry_run: bool = False

    @property
    def conversacion_id(self) -> Optional[int]:
        return self.conversacion.get("id")

    @property
    def aspirante_id(self) -> Optional[int]:
        if self.aspirante and self.aspirante.get("id"):
            return self.aspirante["id"]
        return self.conversacion.get("aspirante_id")

    @property
    def chatbot_configuracion_id(self) -> Optional[int]:
        return self.configuracion.get("id") or self.conversacion.get(
            "chatbot_configuracion_id"
        )

    @property
    def campania_id(self) -> Optional[int]:
        return (self.campania or {}).get("id") or self.conversacion.get("campania_id")

    @property
    def herramientas_permitidas(self) -> List[str]:
        valor = self.asistente.get("herramientas_permitidas") or []
        if isinstance(valor, list):
            return [str(item) for item in valor if item]
        return []


def _verificar_agencia(
    registro: Optional[Dict[str, Any]],
    agencia_id: int,
    etiqueta: str,
) -> Optional[Dict[str, Any]]:
    if not registro:
        return None

    propietaria = registro.get("agencia_id")
    if propietaria is not None and int(propietaria) != int(agencia_id):
        raise AgenciaMismatch(
            f"El registro '{etiqueta}' pertenece a otra agencia.",
            {"esperada": agencia_id, "encontrada": propietaria, "registro": etiqueta},
        )

    return registro


def _lista(valor: Any, limite: int) -> List[Dict[str, Any]]:
    if not isinstance(valor, list):
        return []
    return [item for item in valor if isinstance(item, dict)][:limite]


def construir_contexto(
    *,
    agencia_id: int,
    conversacion: Dict[str, Any],
    asistente: Optional[Dict[str, Any]] = None,
    aspirante: Optional[Dict[str, Any]] = None,
    campania: Optional[Dict[str, Any]] = None,
    configuracion: Optional[Dict[str, Any]] = None,
    agencia: Optional[Dict[str, Any]] = None,
    limite_mensajes: int = LIMITE_MENSAJES,
    dry_run: bool = False,
) -> ConversationalContext:
    """Arma el `ConversationalContext` con lo mínimo necesario para responder."""
    if not conversacion:
        raise ConversacionalError("Se requiere la conversación para construir el contexto.")

    _verificar_agencia(conversacion, agencia_id, "conversacion")

    conversacion_id = conversacion.get("id")
    configuracion_id = conversacion.get("chatbot_configuracion_id")

    if agencia is None:
        agencia = gw.call_opcional("obtener_agencia", agencia_id, default={}) or {}

    if configuracion is None and configuracion_id:
        configuracion = (
            gw.call_opcional(
                "obtener_configuracion_chatbot", agencia_id, configuracion_id, default={}
            )
            or {}
        )
    configuracion = _verificar_agencia(configuracion or {}, agencia_id, "configuracion") or {}

    if asistente is None and configuracion_id:
        asistente = (
            gw.call_opcional(
                "obtener_asistente_configuracion", agencia_id, configuracion_id, default={}
            )
            or {}
        )
    asistente = _verificar_agencia(asistente or {}, agencia_id, "asistente") or {}

    aspirante_id = conversacion.get("aspirante_id")
    if aspirante is None and aspirante_id:
        aspirante = gw.call_opcional("obtener_aspirante", agencia_id, aspirante_id)
    aspirante = _verificar_agencia(aspirante, agencia_id, "aspirante")

    campania_id = conversacion.get("campania_id") or (aspirante or {}).get("campania_id")
    if campania is None and campania_id:
        campania = gw.call_opcional("obtener_campania", agencia_id, campania_id)
    campania = _verificar_agencia(campania, agencia_id, "campania")

    resolucion = resolver_modo(
        asistente=asistente,
        aspirante=aspirante,
        campania=campania,
        conversacion=conversacion,
    )

    flujo = _resolver_flujo(
        agencia_id=agencia_id,
        conversacion=conversacion,
        campania=campania,
        configuracion_id=configuracion_id,
        modo=resolucion.modo,
    )
    flujo = _verificar_agencia(flujo, agencia_id, "flujo")

    paso = None
    if conversacion.get("paso_actual_id"):
        paso = gw.call_opcional(
            "obtener_paso_flujo", agencia_id, conversacion["paso_actual_id"]
        )
        paso = _verificar_agencia(paso, agencia_id, "paso_flujo")

    prueba_live = None
    evidencias = []
    if flujo and flujo.get("id"):
        prueba_live = gw.call_opcional(
            ("obtener_prueba_live_por_flujo", "obtener_prueba_live"),
            agencia_id,
            flujo["id"],
            campania_id=(campania or {}).get("id"),
        )
        prueba_live = _verificar_agencia(prueba_live, agencia_id, "prueba_live")

        if prueba_live and prueba_live.get("id"):
            evidencias = _lista(
                gw.call_opcional(
                    "listar_evidencias_requeridas",
                    agencia_id,
                    prueba_live["id"],
                    default=[],
                ),
                LIMITE_EVIDENCIAS,
            )

    mensajes = _lista(
        gw.call_opcional(
            "listar_ultimos_mensajes",
            agencia_id,
            conversacion_id,
            limite=limite_mensajes,
            default=[],
        ),
        limite_mensajes,
    )

    contexto = ConversationalContext(
        agencia_id=agencia_id,
        conversacion=conversacion,
        canal=str(conversacion.get("canal") or "whatsapp"),
        modo=resolucion.modo,
        resolucion_modo=resolucion,
        agencia=agencia or {},
        configuracion=configuracion,
        asistente=asistente,
        aspirante=aspirante,
        campania=campania,
        flujo=flujo,
        paso=paso,
        requisitos=_lista(
            gw.call_opcional(
                "listar_requisitos",
                agencia_id,
                chatbot_configuracion_id=configuracion_id,
                solo_activos=True,
                default=[],
            ),
            LIMITE_REQUISITOS,
        ),
        beneficios=_lista(
            gw.call_opcional(
                "listar_beneficios_vigentes",
                agencia_id,
                configuracion_id,
                (campania or {}).get("id"),
                default=[],
            ),
            LIMITE_BENEFICIOS,
        ),
        faqs=_lista(
            gw.call_opcional(
                "listar_faq",
                agencia_id,
                chatbot_configuracion_id=configuracion_id,
                solo_activos=True,
                default=[],
            ),
            LIMITE_FAQ,
        ),
        recursos=_lista(
            gw.call_opcional(
                "listar_recursos_enlaces",
                agencia_id,
                chatbot_configuracion_id=configuracion_id,
                campania_id=(campania or {}).get("id"),
                solo_activos=True,
                default=[],
            ),
            LIMITE_RECURSOS,
        ),
        prueba_live=prueba_live,
        evidencias_requeridas=evidencias,
        reglas_escalamiento=_lista(
            gw.call_opcional(
                "listar_reglas_escalamiento",
                agencia_id,
                chatbot_configuracion_id=configuracion_id,
                flujo_id=(flujo or {}).get("id"),
                campania_id=(campania or {}).get("id"),
                default=[],
            ),
            LIMITE_REGLAS,
        ),
        mensajes=mensajes,
        resumen_contexto=conversacion.get("resumen_contexto"),
        dry_run=dry_run,
    )

    return contexto


def _resolver_flujo(
    *,
    agencia_id: int,
    conversacion: Dict[str, Any],
    campania: Optional[Dict[str, Any]],
    configuracion_id: Optional[int],
    modo: str,
) -> Optional[Dict[str, Any]]:
    flujo_id = conversacion.get("flujo_id") or (campania or {}).get("flujo_id")

    if flujo_id:
        return gw.call_opcional("obtener_flujo", agencia_id, flujo_id)

    if not configuracion_id:
        return None

    return gw.call_opcional(
        "obtener_flujo_activo",
        agencia_id,
        configuracion_id,
        tipo_flujo_para_modo(modo),
    )
