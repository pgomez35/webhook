"""
Herramientas controladas del asistente conversacional.

Principios:
- El contexto interno (agencia_id, conversacion_id, aspirante_id) se inyecta en
  la fábrica del agente. El modelo NUNCA puede elegir la agencia.
- Toda herramienta devuelve JSON en texto y registra un evento en
  `chatbot.eventos_conversacion`.
- Las escrituras están limitadas por lista blanca: el asistente no puede
  aprobar, descartar ni evaluar a un aspirante.
- En modo simulación (`dry_run`) no se escribe en base de datos.
"""
from __future__ import annotations

import inspect
import json
import logging
import typing
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, create_model

import chatbot_conversacional_db_gateway as gw
from chatbot_conversacional_context_builder import ConversationalContext
from chatbot_conversacional_exceptions import HerramientaNoPermitida

logger = logging.getLogger("uvicorn.error")

TContext = TypeVar("TContext")

# ---------------------------------------------------------------------------
# Integración con OpenAI Agents SDK (con wrappers compatibles de reserva)
# ---------------------------------------------------------------------------

try:  # pragma: no cover - depende del entorno
    from agents import RunContextWrapper, function_tool  # type: ignore

    AGENTS_SDK_DISPONIBLE = True

except ImportError:  # pragma: no cover - entornos sin openai-agents
    AGENTS_SDK_DISPONIBLE = False

    @dataclass
    class RunContextWrapper(Generic[TContext]):  # type: ignore[no-redef]
        """Reemplazo mínimo del wrapper de contexto del SDK."""

        context: TContext

    def _modelo_argumentos(func: Any) -> type[BaseModel]:
        firma = inspect.signature(func)
        anotaciones = typing.get_type_hints(func)

        campos: Dict[str, Any] = {}
        for indice, (nombre, parametro) in enumerate(firma.parameters.items()):
            if indice == 0:  # RunContextWrapper
                continue

            anotacion = anotaciones.get(nombre, Any)
            default = ... if parametro.default is inspect.Parameter.empty else parametro.default
            campos[nombre] = (anotacion, default)

        return create_model(f"Args_{func.__name__}", **campos)

    class _HerramientaCompatible:
        """Expone la misma superficie que `agents.FunctionTool`."""

        def __init__(
            self,
            func: Any,
            *,
            name: Optional[str] = None,
            description: Optional[str] = None,
        ) -> None:
            self._func = func
            self._modelo = _modelo_argumentos(func)
            self.name = name or func.__name__
            self.description = description or (inspect.getdoc(func) or "").strip()
            self.params_json_schema = self._modelo.model_json_schema()

        async def on_invoke_tool(self, ctx: Any, input: str) -> str:  # noqa: A002
            try:
                validado = self._modelo.model_validate(json.loads(input or "{}"))

            except Exception as exc:  # noqa: BLE001 - el modelo recibe el motivo y reintenta
                logger.warning(
                    "chatbot_conversacional: argumentos inválidos para %s: %s", self.name, exc
                )
                return json.dumps(
                    {
                        "ok": False,
                        "error": "Argumentos inválidos o no permitidos para esta herramienta.",
                        "detalle": str(exc)[:400],
                    },
                    ensure_ascii=False,
                )

            argumentos = {
                nombre: getattr(validado, nombre) for nombre in self._modelo.model_fields
            }
            return await self._func(ctx, **argumentos)

        async def __call__(self, ctx: Any, *args: Any, **kwargs: Any) -> Any:
            return await self._func(ctx, *args, **kwargs)

    def function_tool(  # type: ignore[no-redef]
        func: Any = None,
        *,
        name_override: Optional[str] = None,
        description_override: Optional[str] = None,
        **_ignorado: Any,
    ) -> Any:
        def decorar(objetivo: Any) -> _HerramientaCompatible:
            return _HerramientaCompatible(
                objetivo,
                name=name_override,
                description=description_override,
            )

        return decorar if func is None else decorar(func)


# ---------------------------------------------------------------------------
# Contexto interno inyectado
# ---------------------------------------------------------------------------

CAMPOS_ASPIRANTE_PERMITIDOS = frozenset({"usuario_plataforma", "mayor_edad", "disponibilidad"})
ESTADOS_ASPIRANTE_PROHIBIDOS = frozenset({"aprobado", "descartado", "cumple_requisitos", "estado"})

TIPOS_TAREA = (
    "agendar_live",
    "realizar_live",
    "enviar_evidencias",
    "completar_solicitud",
    "hablar_con_manager",
    "confirmar_datos",
    "otro",
)
TIPOS_EVIDENCIA = (
    "inicio_live",
    "durante_live",
    "batalla",
    "estadisticas_finales",
    "perfil_tiktok",
    "solicitud",
    "otro",
)
TIPOS_ARCHIVO = ("imagen", "video", "documento", "url", "texto", "otro")
PRIORIDADES = ("baja", "normal", "alta", "urgente")


@dataclass
class ContextoHerramientas:
    """Contexto interno; el modelo no tiene acceso a estos valores."""

    agencia_id: int
    conversacion_id: Optional[int]
    contexto: ConversationalContext
    dry_run: bool = False
    mensaje_id: Optional[int] = None
    acciones: List[Dict[str, Any]] = field(default_factory=list)
    enlaces: List[Dict[str, Any]] = field(default_factory=list)
    escalamiento: Optional[Dict[str, Any]] = None
    cierre: Optional[Dict[str, Any]] = None

    @property
    def aspirante_id(self) -> Optional[int]:
        return self.contexto.aspirante_id


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------


def _ctx(wrapper: Any) -> ContextoHerramientas:
    contexto = getattr(wrapper, "context", None)
    if not isinstance(contexto, ContextoHerramientas):
        raise HerramientaNoPermitida("Contexto interno ausente o inválido en la herramienta.")
    return contexto


def _json(datos: Dict[str, Any]) -> str:
    return json.dumps(datos, ensure_ascii=False, default=str)


def _ok(**datos: Any) -> str:
    return _json({"ok": True, **datos})


def _error(mensaje: str, **datos: Any) -> str:
    return _json({"ok": False, "error": mensaje, **datos})


def _registrar(
    ctxh: ContextoHerramientas,
    *,
    herramienta: str,
    tipo_evento: str = "herramienta_ia",
    detalle: Optional[Dict[str, Any]] = None,
    exitoso: bool = True,
    error_detalle: Optional[str] = None,
    estado_anterior: Optional[str] = None,
    estado_nuevo: Optional[str] = None,
) -> None:
    ctxh.acciones.append(
        {
            "herramienta": herramienta,
            "tipo_evento": tipo_evento,
            "exitoso": exitoso,
            "detalle": detalle or {},
        }
    )

    if ctxh.dry_run or not ctxh.conversacion_id:
        return

    gw.call_opcional(
        "registrar_evento",
        ctxh.agencia_id,
        ctxh.conversacion_id,
        tipo_evento=tipo_evento,
        nombre_evento=herramienta,
        origen="chatbot",
        mensaje_id=ctxh.mensaje_id,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
        exitoso=exitoso,
        detalle=detalle or {},
        error_detalle=error_detalle,
    )


def _vigente(registro: Dict[str, Any], hoy: Optional[date] = None) -> bool:
    if registro.get("activo") is False:
        return False

    referencia = hoy or date.today()

    for clave_desde, clave_hasta in (
        ("vigencia_desde", "vigencia_hasta"),
        ("fecha_inicio", "fecha_fin"),
    ):
        desde = registro.get(clave_desde)
        hasta = registro.get(clave_hasta)

        if isinstance(desde, datetime):
            desde = desde.date()
        if isinstance(hasta, datetime):
            hasta = hasta.date()

        if isinstance(desde, date) and referencia < desde:
            return False
        if isinstance(hasta, date) and referencia > hasta:
            return False

    return True


def _resolver_url(template: str, ctxh: ContextoHerramientas) -> str:
    ctx = ctxh.contexto
    aspirante = ctx.aspirante or {}

    reemplazos = {
        "{telefono}": str(ctx.conversacion.get("telefono") or aspirante.get("telefono") or ""),
        "{usuario_plataforma}": str(aspirante.get("usuario_plataforma") or ""),
        "{aspirante_id}": str(ctx.aspirante_id or ""),
        "{conversacion_id}": str(ctx.conversacion_id or ""),
        "{agencia_codigo}": str(ctx.agencia.get("codigo") or ""),
        "{agencia_id}": str(ctx.agencia_id),
    }

    url = template
    for clave, valor in reemplazos.items():
        url = url.replace(clave, valor)

    return url


def _actualizar_conversacion(ctxh: ContextoHerramientas, campos: Dict[str, Any]) -> None:
    if ctxh.dry_run or not ctxh.conversacion_id or not campos:
        return

    gw.call_opcional(
        "actualizar_conversacion", ctxh.agencia_id, ctxh.conversacion_id, campos
    )


# ---------------------------------------------------------------------------
# Modelos de entrada
# ---------------------------------------------------------------------------


class DatosExplicitosAspiranteIn(BaseModel):
    """Datos declarados de forma explícita por la persona."""

    model_config = ConfigDict(extra="forbid")

    usuario_plataforma: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Usuario declarado por la persona en la plataforma (sin @).",
    )
    mayor_edad: Optional[bool] = Field(
        default=None, description="Solo si la persona afirma o niega ser mayor de edad."
    )
    disponibilidad: Optional[bool] = Field(
        default=None,
        description="Solo si la persona confirma o niega disponibilidad para transmitir.",
    )


class TareaCandidatoIn(BaseModel):
    """Tarea pendiente para la persona."""

    model_config = ConfigDict(extra="forbid")

    tipo_tarea: typing.Literal[TIPOS_TAREA] = Field(  # type: ignore[valid-type]
        description="Tipo de tarea a crear."
    )
    titulo: str = Field(max_length=180, description="Título corto de la tarea.")
    descripcion: Optional[str] = Field(default=None, max_length=1000)
    fecha_limite: Optional[str] = Field(
        default=None, description="Fecha límite ISO 8601 acordada con la persona."
    )


class EvidenciaRecibidaIn(BaseModel):
    """Evidencia enviada por la persona; siempre queda como recibida."""

    model_config = ConfigDict(extra="forbid")

    tipo_evidencia: typing.Literal[TIPOS_EVIDENCIA] = Field(  # type: ignore[valid-type]
        description="Tipo de evidencia enviada."
    )
    tipo_archivo: Optional[typing.Literal[TIPOS_ARCHIVO]] = Field(  # type: ignore[valid-type]
        default=None
    )
    descripcion: Optional[str] = Field(default=None, max_length=1000)
    archivo_url: Optional[str] = Field(default=None, max_length=1000)
    archivo_id_externo: Optional[str] = Field(default=None, max_length=255)
    evidencia_requerida_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Herramientas de consulta
# ---------------------------------------------------------------------------


@function_tool(strict_mode=False)
async def consultar_informacion_agencia(
    ctx: RunContextWrapper[ContextoHerramientas],
) -> str:
    """Devuelve la información institucional autorizada de la agencia y el proceso."""
    ctxh = _ctx(ctx)
    contexto = ctxh.contexto

    datos = {
        "agencia": contexto.agencia.get("nombre"),
        "descripcion": contexto.asistente.get("descripcion_agencia"),
        "presentacion": contexto.asistente.get("presentacion_inicial"),
        "plataforma": contexto.configuracion.get("plataforma_codigo"),
        "configuracion": contexto.configuracion.get("nombre"),
        "modo": contexto.modo,
        "texto_privacidad": contexto.asistente.get("texto_privacidad"),
    }

    _registrar(ctxh, herramienta="consultar_informacion_agencia")
    return _ok(informacion=datos)


@function_tool(strict_mode=False)
async def consultar_requisitos(
    ctx: RunContextWrapper[ContextoHerramientas],
    categoria: Optional[str] = None,
) -> str:
    """
    Lista los requisitos vigentes que se pueden explicar.

    Args:
        categoria: Filtro opcional: obligatorio, deseable o informativo.
    """
    ctxh = _ctx(ctx)

    requisitos = []
    for requisito in ctxh.contexto.requisitos:
        if requisito.get("permitir_mencion_automatica") is False:
            continue
        if categoria and str(requisito.get("categoria") or "").lower() != categoria.lower():
            continue

        requisitos.append(
            {
                "codigo": requisito.get("codigo"),
                "nombre": requisito.get("nombre"),
                "categoria": requisito.get("categoria"),
                "descripcion": requisito.get("descripcion"),
                "valor_texto": requisito.get("valor_texto"),
                "valor_minimo": requisito.get("valor_minimo"),
                "valor_maximo": requisito.get("valor_maximo"),
                "unidad": requisito.get("unidad"),
                "bloquea_proceso": requisito.get("bloquea_proceso"),
                "mensaje_si_no_cumple": requisito.get("mensaje_si_no_cumple"),
            }
        )

    _registrar(
        ctxh,
        herramienta="consultar_requisitos",
        detalle={"categoria": categoria, "total": len(requisitos)},
    )
    return _ok(
        requisitos=requisitos,
        nota="Solo explica requisitos; la evaluación del perfil es humana.",
    )


@function_tool(strict_mode=False)
async def consultar_beneficios_vigentes(
    ctx: RunContextWrapper[ContextoHerramientas],
    tipo: Optional[str] = None,
) -> str:
    """
    Lista beneficios y bonos vigentes con su texto autorizado.

    Args:
        tipo: Filtro opcional: beneficio, bono, incentivo, capacitacion, acompanamiento u otro.
    """
    ctxh = _ctx(ctx)

    beneficios = []
    for beneficio in ctxh.contexto.beneficios:
        if beneficio.get("permitir_mencion_automatica") is False:
            continue
        if not _vigente(beneficio):
            continue
        if tipo and str(beneficio.get("tipo") or "").lower() != tipo.lower():
            continue

        beneficios.append(
            {
                "codigo": beneficio.get("codigo"),
                "nombre": beneficio.get("nombre"),
                "tipo": beneficio.get("tipo"),
                "texto_autorizado": beneficio.get("texto_autorizado")
                or beneficio.get("descripcion_corta"),
                "condiciones": beneficio.get("condiciones"),
                "requiere_validacion_humana": beneficio.get("requiere_validacion_humana"),
            }
        )

    _registrar(
        ctxh,
        herramienta="consultar_beneficios_vigentes",
        detalle={"tipo": tipo, "total": len(beneficios)},
    )
    return _ok(
        beneficios=beneficios,
        nota="No calcules ni proyectes ingresos a partir de estos beneficios.",
    )


@function_tool(strict_mode=False)
async def consultar_faq(
    ctx: RunContextWrapper[ContextoHerramientas],
    consulta: str,
    limite: int = 3,
) -> str:
    """
    Busca respuestas autorizadas en las preguntas frecuentes de la agencia.

    Args:
        consulta: Duda de la persona, en sus propias palabras.
        limite: Cantidad máxima de coincidencias a devolver (1 a 5).
    """
    ctxh = _ctx(ctx)
    limite = max(1, min(int(limite or 3), 5))

    encontradas = gw.call_opcional(
        "buscar_faq",
        ctxh.agencia_id,
        ctxh.contexto.chatbot_configuracion_id,
        consulta,
        limite=limite,
        default=None,
    )

    if not encontradas:
        encontradas = _buscar_faq_en_contexto(ctxh.contexto.faqs, consulta, limite)

    resultado = [
        {
            "codigo": faq.get("codigo"),
            "pregunta": faq.get("pregunta"),
            "respuesta": faq.get("respuesta_corta") or faq.get("respuesta_completa"),
            "requiere_humano": faq.get("requiere_humano"),
            "evento_escalamiento": faq.get("evento_escalamiento"),
        }
        for faq in encontradas
        if isinstance(faq, dict)
    ]

    _registrar(
        ctxh,
        herramienta="consultar_faq",
        detalle={"consulta": consulta[:200], "total": len(resultado)},
    )

    if not resultado:
        return _ok(
            faqs=[],
            nota="Sin respuesta autorizada: dilo con honestidad y ofrece apoyo humano.",
        )

    return _ok(faqs=resultado)


def _buscar_faq_en_contexto(
    faqs: List[Dict[str, Any]],
    consulta: str,
    limite: int,
) -> List[Dict[str, Any]]:
    """Coincidencia simple por palabras clave cuando la DB no expone búsqueda."""
    terminos = {palabra for palabra in str(consulta or "").lower().split() if len(palabra) > 3}
    if not terminos:
        return faqs[:limite]

    puntuadas = []
    for faq in faqs:
        texto = " ".join(
            str(faq.get(clave) or "").lower()
            for clave in ("pregunta", "respuesta_corta", "respuesta_completa", "categoria", "intencion")
        )
        claves = faq.get("palabras_clave")
        if isinstance(claves, list):
            texto += " " + " ".join(str(clave).lower() for clave in claves)

        puntaje = sum(1 for termino in terminos if termino in texto)
        if puntaje:
            puntuadas.append((puntaje, int(faq.get("prioridad") or 0), faq))

    puntuadas.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [faq for _, _, faq in puntuadas[:limite]]


@function_tool(strict_mode=False)
async def consultar_recursos_autorizados(
    ctx: RunContextWrapper[ContextoHerramientas],
    tipo: Optional[str] = None,
) -> str:
    """
    Lista los recursos y enlaces autorizados disponibles (sin exponer las URLs).

    Args:
        tipo: Filtro opcional: solicitud, agendamiento, privacidad, terminos, soporte, instructivo u otro.
    """
    ctxh = _ctx(ctx)

    recursos = []
    for recurso in ctxh.contexto.recursos:
        if not _vigente(recurso):
            continue
        if tipo and str(recurso.get("tipo") or "").lower() != tipo.lower():
            continue

        recursos.append(
            {
                "codigo": recurso.get("codigo"),
                "nombre": recurso.get("nombre"),
                "tipo": recurso.get("tipo"),
                "descripcion": recurso.get("descripcion"),
                "texto_boton": recurso.get("texto_boton"),
            }
        )

    _registrar(
        ctxh,
        herramienta="consultar_recursos_autorizados",
        detalle={"tipo": tipo, "total": len(recursos)},
    )
    return _ok(
        recursos=recursos,
        nota="Para compartir uno usa enviar_enlace_autorizado con su código.",
    )


# ---------------------------------------------------------------------------
# Herramientas de escritura acotada
# ---------------------------------------------------------------------------


@function_tool(strict_mode=False)
async def registrar_dato_explicito_aspirante(
    ctx: RunContextWrapper[ContextoHerramientas],
    datos: DatosExplicitosAspiranteIn,
) -> str:
    """
    Guarda datos que la persona declaró de forma explícita en el chat.

    Solo acepta usuario de plataforma, mayoría de edad y disponibilidad. No
    modifica el estado del proceso ni evalúa el perfil.

    Args:
        datos: Datos declarados textualmente por la persona.
    """
    ctxh = _ctx(ctx)

    entrada = {clave: valor for clave, valor in datos.model_dump().items() if valor is not None}
    if not entrada:
        return _error("No se recibió ningún dato declarado por la persona.")

    prohibidos = set(entrada) - CAMPOS_ASPIRANTE_PERMITIDOS
    if prohibidos or set(entrada) & ESTADOS_ASPIRANTE_PROHIBIDOS:
        _registrar(
            ctxh,
            herramienta="registrar_dato_explicito_aspirante",
            detalle={"campos_rechazados": sorted(prohibidos)},
            exitoso=False,
            error_detalle="Campo no permitido para el asistente.",
        )
        return _error(
            "Esos campos no se pueden modificar desde el chat. El estado del proceso lo define una persona.",
            campos_rechazados=sorted(prohibidos),
        )

    aspirante_id = ctxh.aspirante_id
    if not aspirante_id:
        _registrar(
            ctxh,
            herramienta="registrar_dato_explicito_aspirante",
            detalle={"campos": sorted(entrada)},
            exitoso=False,
            error_detalle="Conversación sin aspirante asociado.",
        )
        return _error(
            "Todavía no hay una ficha para registrar el dato; continúa la conversación con normalidad."
        )

    campos = {}
    if "usuario_plataforma" in entrada:
        campos["usuario_plataforma"] = str(entrada["usuario_plataforma"]).strip().lstrip("@")[:100]
    if "mayor_edad" in entrada:
        campos["mayor_edad"] = bool(entrada["mayor_edad"])
    if "disponibilidad" in entrada:
        campos["disponibilidad_live"] = bool(entrada["disponibilidad"])

    if not ctxh.dry_run:
        # actualizar_datos_explicitos_aspirante(agencia_id, aspirante_id, campos) -> dict
        gw.call_opcional(
            "actualizar_datos_explicitos_aspirante",
            ctxh.agencia_id,
            aspirante_id,
            campos,
        )

    if ctxh.contexto.aspirante is not None:
        ctxh.contexto.aspirante.update(campos)

    _registrar(
        ctxh,
        herramienta="registrar_dato_explicito_aspirante",
        detalle={"campos": sorted(campos)},
    )
    return _ok(registrado=sorted(campos))


@function_tool(strict_mode=False)
async def confirmar_interes(
    ctx: RunContextWrapper[ContextoHerramientas],
    comentario: Optional[str] = None,
) -> str:
    """
    Registra que la persona confirmó su interés en continuar el proceso.

    No aprueba ni selecciona a nadie: solo deja constancia del interés.

    Args:
        comentario: Frase breve con la que la persona confirmó su interés.
    """
    ctxh = _ctx(ctx)

    _actualizar_conversacion(ctxh, {"estado_actual": "interes_confirmado"})
    _registrar(
        ctxh,
        herramienta="confirmar_interes",
        tipo_evento="solicitud",
        detalle={"comentario": (comentario or "")[:300]},
        estado_anterior=ctxh.contexto.conversacion.get("estado_actual"),
        estado_nuevo="interes_confirmado",
    )
    return _ok(
        interes="confirmado",
        nota="Continúa con el siguiente paso del flujo; la decisión final es humana.",
    )


@function_tool(strict_mode=False)
async def crear_tarea_candidato(
    ctx: RunContextWrapper[ContextoHerramientas],
    tarea: TareaCandidatoIn,
) -> str:
    """
    Crea una tarea pendiente para la persona (agendar LIVE, enviar evidencias, etc.).

    Args:
        tarea: Datos de la tarea acordada en el chat.
    """
    ctxh = _ctx(ctx)

    datos = tarea.model_dump()
    creada = None

    if not ctxh.dry_run:
        # crear_tarea_candidato(agencia_id, conversacion_id, **campos) -> dict
        creada = gw.call_opcional(
            "crear_tarea_candidato",
            ctxh.agencia_id,
            ctxh.conversacion_id,
            aspirante_id=ctxh.aspirante_id,
            paso_flujo_id=(ctxh.contexto.paso or {}).get("id"),
            tipo_tarea=datos["tipo_tarea"],
            titulo=datos["titulo"][:180],
            descripcion=datos.get("descripcion"),
            fecha_limite=datos.get("fecha_limite"),
            estado="pendiente",
            creada_por_tipo="chatbot",
        )

    _registrar(
        ctxh,
        herramienta="crear_tarea_candidato",
        tipo_evento="tarea",
        detalle={"tipo_tarea": datos["tipo_tarea"], "titulo": datos["titulo"][:180]},
    )
    return _ok(tarea_id=(creada or {}).get("id"), tipo_tarea=datos["tipo_tarea"])


@function_tool(strict_mode=False)
async def enviar_enlace_autorizado(
    ctx: RunContextWrapper[ContextoHerramientas],
    codigo_recurso: str,
    motivo: Optional[str] = None,
) -> str:
    """
    Prepara el envío de un enlace autorizado a partir de su código de recurso.

    Solo funciona con recursos configurados por la agencia. El sistema envía el
    enlace; no lo escribas tú en el mensaje.

    Args:
        codigo_recurso: Código exacto del recurso autorizado.
        motivo: Razón breve por la que se comparte.
    """
    ctxh = _ctx(ctx)
    codigo = str(codigo_recurso or "").strip()

    recurso = next(
        (
            item
            for item in ctxh.contexto.recursos
            if str(item.get("codigo") or "").lower() == codigo.lower()
        ),
        None,
    )

    if recurso is None:
        recurso = gw.call_opcional("obtener_recurso_por_codigo", ctxh.agencia_id, codigo)

    if not recurso or int(recurso.get("agencia_id") or ctxh.agencia_id) != int(ctxh.agencia_id):
        _registrar(
            ctxh,
            herramienta="enviar_enlace_autorizado",
            tipo_evento="envio_enlace",
            detalle={"codigo": codigo},
            exitoso=False,
            error_detalle="Recurso inexistente o de otra agencia.",
        )
        return _error("No existe un recurso autorizado con ese código.", codigo=codigo)

    if not _vigente(recurso):
        _registrar(
            ctxh,
            herramienta="enviar_enlace_autorizado",
            tipo_evento="envio_enlace",
            detalle={"codigo": codigo},
            exitoso=False,
            error_detalle="Recurso fuera de vigencia.",
        )
        return _error("Ese recurso no está vigente; ofrece apoyo humano.", codigo=codigo)

    if recurso.get("requiere_token"):
        _registrar(
            ctxh,
            herramienta="enviar_enlace_autorizado",
            tipo_evento="envio_enlace",
            detalle={"codigo": codigo, "requiere_token": True},
            exitoso=False,
            error_detalle="El recurso requiere token generado por el backend.",
        )
        return _error(
            "Ese enlace es personalizado y debe generarlo el equipo; transfiere la conversación.",
            codigo=codigo,
        )

    url = _resolver_url(str(recurso.get("url_template") or ""), ctxh)
    if not url:
        return _error("El recurso no tiene URL configurada.", codigo=codigo)

    enlace = {
        "codigo": recurso.get("codigo"),
        "nombre": recurso.get("nombre"),
        "tipo": recurso.get("tipo"),
        "url": url,
        "texto_boton": recurso.get("texto_boton"),
        "motivo": (motivo or "")[:200],
    }
    ctxh.enlaces.append(enlace)

    _registrar(
        ctxh,
        herramienta="enviar_enlace_autorizado",
        tipo_evento="envio_enlace",
        detalle={"codigo": recurso.get("codigo"), "tipo": recurso.get("tipo")},
    )
    return _ok(
        enlace=enlace,
        nota="El sistema enviará el enlace; anuncia su envío en tu mensaje.",
    )


@function_tool(strict_mode=False)
async def preparar_prueba_live(
    ctx: RunContextWrapper[ContextoHerramientas],
) -> str:
    """Devuelve las condiciones e instrucciones vigentes de la prueba LIVE."""
    ctxh = _ctx(ctx)
    prueba = ctxh.contexto.prueba_live

    if not prueba:
        _registrar(
            ctxh,
            herramienta="preparar_prueba_live",
            exitoso=False,
            error_detalle="Sin configuración de prueba LIVE.",
        )
        return _error(
            "No hay una prueba LIVE configurada para este flujo; ofrece apoyo humano."
        )

    datos = {
        "nombre": prueba.get("nombre"),
        "duracion_minima_minutos": prueba.get("duracion_minima_minutos"),
        "cantidad_batallas": prueba.get("cantidad_batallas"),
        "requiere_agendamiento": prueba.get("requiere_agendamiento"),
        "zona_horaria": prueba.get("zona_horaria"),
        "dias_permitidos": prueba.get("dias_permitidos"),
        "horarios_permitidos": prueba.get("horarios_permitidos"),
        "plazo_evidencias_horas": prueba.get("plazo_evidencias_horas"),
        "instrucciones_antes": prueba.get("instrucciones_antes"),
        "instrucciones_durante": prueba.get("instrucciones_durante"),
        "instrucciones_despues": prueba.get("instrucciones_despues"),
    }

    _registrar(
        ctxh,
        herramienta="preparar_prueba_live",
        detalle={"prueba_live_id": prueba.get("id")},
    )
    return _ok(prueba_live=datos)


@function_tool(strict_mode=False)
async def solicitar_evidencias(
    ctx: RunContextWrapper[ContextoHerramientas],
    momento: Optional[str] = None,
) -> str:
    """
    Devuelve las evidencias que la persona debe enviar y deja constancia del pedido.

    Args:
        momento: Filtro opcional: antes_live, inicio_live, durante_live, durante_batalla, final_live o despues_live.
    """
    ctxh = _ctx(ctx)

    requeridas = [
        {
            "id": evidencia.get("id"),
            "codigo": evidencia.get("codigo"),
            "nombre": evidencia.get("nombre"),
            "descripcion": evidencia.get("descripcion"),
            "tipo_evidencia": evidencia.get("tipo_evidencia"),
            "momento_requerido": evidencia.get("momento_requerido"),
            "obligatoria": evidencia.get("obligatoria"),
            "formatos_permitidos": evidencia.get("formatos_permitidos"),
        }
        for evidencia in ctxh.contexto.evidencias_requeridas
        if not momento
        or str(evidencia.get("momento_requerido") or "").lower() == momento.lower()
    ]

    if not requeridas:
        _registrar(
            ctxh,
            herramienta="solicitar_evidencias",
            tipo_evento="solicitud",
            detalle={"momento": momento},
            exitoso=False,
            error_detalle="Sin evidencias configuradas.",
        )
        return _error("No hay evidencias configuradas para ese momento.")

    _registrar(
        ctxh,
        herramienta="solicitar_evidencias",
        tipo_evento="solicitud",
        detalle={"momento": momento, "total": len(requeridas)},
    )
    return _ok(
        evidencias=requeridas,
        nota="Pide las evidencias de a poco y explica cómo enviarlas.",
    )


@function_tool(strict_mode=False)
async def registrar_evidencia_recibida(
    ctx: RunContextWrapper[ContextoHerramientas],
    evidencia: EvidenciaRecibidaIn,
) -> str:
    """
    Registra una evidencia enviada por la persona con estado 'recibida'.

    Nunca la apruebas ni la calificas: la revisión es humana.

    Args:
        evidencia: Datos de la evidencia recibida en el chat.
    """
    ctxh = _ctx(ctx)
    datos = evidencia.model_dump()
    creada = None

    if not ctxh.dry_run:
        # registrar_evidencia(agencia_id, conversacion_id, **campos) -> dict
        creada = gw.call_opcional(
            "registrar_evidencia",
            ctxh.agencia_id,
            ctxh.conversacion_id,
            aspirante_id=ctxh.aspirante_id,
            mensaje_id=ctxh.mensaje_id,
            evidencia_requerida_id=datos.get("evidencia_requerida_id"),
            tipo_evidencia=datos["tipo_evidencia"],
            tipo_archivo=datos.get("tipo_archivo"),
            archivo_url=datos.get("archivo_url"),
            archivo_id_externo=datos.get("archivo_id_externo"),
            valor_texto=datos.get("descripcion"),
            estado_revision="recibida",
        )

    _registrar(
        ctxh,
        herramienta="registrar_evidencia_recibida",
        tipo_evento="evidencia",
        detalle={
            "tipo_evidencia": datos["tipo_evidencia"],
            "tipo_archivo": datos.get("tipo_archivo"),
        },
    )
    return _ok(
        evidencia_id=(creada or {}).get("id"),
        estado="recibida",
        nota="Agradece el envío y aclara que el equipo la revisará.",
    )


@function_tool(strict_mode=False)
async def transferir_a_humano(
    ctx: RunContextWrapper[ContextoHerramientas],
    motivo: str,
    prioridad: str = "normal",
) -> str:
    """
    Transfiere la conversación a una persona del equipo y detiene las respuestas automáticas.

    Args:
        motivo: Razón concreta del escalamiento.
        prioridad: baja, normal, alta o urgente.
    """
    ctxh = _ctx(ctx)

    prioridad_normalizada = prioridad if prioridad in PRIORIDADES else "normal"
    motivo_limpio = str(motivo or "").strip()[:500] or "Solicitud de atención humana"

    regla = next(
        (
            item
            for item in ctxh.contexto.reglas_escalamiento
            if str(item.get("evento") or "").lower() in motivo_limpio.lower()
        ),
        None,
    )

    # El estado 'esperando_humano' bloquea la IA hasta que un humano libere la conversación.
    _actualizar_conversacion(
        ctxh,
        {
            "estado": "esperando_humano",
            "modo_humano": True,
            "motivo_escalamiento": motivo_limpio,
        },
    )

    ctxh.escalamiento = {
        "motivo": motivo_limpio,
        "prioridad": prioridad_normalizada,
        "regla": (regla or {}).get("evento"),
        "mensaje_usuario": (regla or {}).get("mensaje_usuario"),
    }

    _registrar(
        ctxh,
        herramienta="transferir_a_humano",
        tipo_evento="escalamiento",
        detalle=ctxh.escalamiento,
        estado_anterior=ctxh.contexto.conversacion.get("estado"),
        estado_nuevo="esperando_humano",
    )
    return _ok(
        transferido=True,
        mensaje_sugerido=(regla or {}).get("mensaje_usuario"),
        nota="Despídete con calidez, sin prometer tiempos exactos de respuesta.",
    )


@function_tool(strict_mode=False)
async def cerrar_conversacion(
    ctx: RunContextWrapper[ContextoHerramientas],
    motivo: Optional[str] = None,
) -> str:
    """
    Cierra la conversación cuando la persona se despide o pide no continuar.

    Args:
        motivo: Motivo breve del cierre.
    """
    ctxh = _ctx(ctx)
    motivo_limpio = str(motivo or "").strip()[:300] or "cierre_por_usuario"

    _actualizar_conversacion(ctxh, {"estado": "cerrada", "estado_actual": "finalizado"})

    ctxh.cierre = {"motivo": motivo_limpio}
    _registrar(
        ctxh,
        herramienta="cerrar_conversacion",
        tipo_evento="cierre",
        detalle=ctxh.cierre,
        estado_anterior=ctxh.contexto.conversacion.get("estado"),
        estado_nuevo="cerrada",
    )
    return _ok(cerrada=True, nota="Despídete con amabilidad y deja la puerta abierta.")


# ---------------------------------------------------------------------------
# Registro de herramientas
# ---------------------------------------------------------------------------

HERRAMIENTAS: Dict[str, Any] = {
    "consultar_informacion_agencia": consultar_informacion_agencia,
    "consultar_requisitos": consultar_requisitos,
    "consultar_beneficios_vigentes": consultar_beneficios_vigentes,
    "consultar_faq": consultar_faq,
    "consultar_recursos_autorizados": consultar_recursos_autorizados,
    "registrar_dato_explicito_aspirante": registrar_dato_explicito_aspirante,
    "confirmar_interes": confirmar_interes,
    "crear_tarea_candidato": crear_tarea_candidato,
    "enviar_enlace_autorizado": enviar_enlace_autorizado,
    "preparar_prueba_live": preparar_prueba_live,
    "solicitar_evidencias": solicitar_evidencias,
    "registrar_evidencia_recibida": registrar_evidencia_recibida,
    "transferir_a_humano": transferir_a_humano,
    "cerrar_conversacion": cerrar_conversacion,
}

# Nombres legacy del panel (campos.js) → nombre real del runtime.
ALIAS_HERRAMIENTAS: Dict[str, str] = {
    "listar_requisitos": "consultar_requisitos",
    "listar_beneficios": "consultar_beneficios_vigentes",
    "buscar_faq": "consultar_faq",
    "enviar_enlace": "enviar_enlace_autorizado",
    "agendar_live": "preparar_prueba_live",
    "registrar_dato_aspirante": "registrar_dato_explicito_aspirante",
    "avanzar_paso_flujo": "confirmar_interes",
}

NOMBRES_HERRAMIENTAS = tuple(HERRAMIENTAS)

# Herramientas que solo tienen sentido cuando se busca avanzar el proceso.
HERRAMIENTAS_SOLO_CONVERSION = frozenset(
    {
        "confirmar_interes",
        "crear_tarea_candidato",
        "preparar_prueba_live",
        "solicitar_evidencias",
        "registrar_evidencia_recibida",
    }
)


def _normalizar_nombre_herramienta(nombre: str) -> str:
    clave = str(nombre or "").strip()
    return ALIAS_HERRAMIENTAS.get(clave, clave)


def obtener_herramientas(
    permitidas: Optional[List[str]] = None,
    *,
    modo: Optional[str] = None,
) -> List[Any]:
    """
    Devuelve los objetos de herramienta habilitados.

    `permitidas` proviene de `asistente_configuracion.herramientas_permitidas`;
    si viene vacío se habilitan todas las del modo.
    """
    seleccion = list(NOMBRES_HERRAMIENTAS)

    if permitidas:
        normalizadas: List[str] = []
        desconocidas: List[str] = []
        vistos = set()
        for nombre in permitidas:
            canonico = _normalizar_nombre_herramienta(nombre)
            if canonico not in HERRAMIENTAS:
                desconocidas.append(str(nombre))
                continue
            if canonico not in vistos:
                vistos.add(canonico)
                normalizadas.append(canonico)

        if desconocidas:
            logger.warning(
                "chatbot_conversacional: herramientas desconocidas ignoradas: %s",
                desconocidas,
            )

        if normalizadas:
            seleccion = [nombre for nombre in seleccion if nombre in set(normalizadas)]
        else:
            logger.warning(
                "chatbot_conversacional: ninguna herramienta permitida es válida; "
                "se usan todas las del modo."
            )

    if modo and modo != "conversion":
        seleccion = [
            nombre for nombre in seleccion if nombre not in HERRAMIENTAS_SOLO_CONVERSION
        ]

    return [HERRAMIENTAS[nombre] for nombre in seleccion]


async def invocar_herramienta(
    nombre: str,
    contexto: ContextoHerramientas,
    argumentos: Optional[Dict[str, Any]] = None,
) -> str:
    """Ejecuta una herramienta desde el backend (sin pasar por el modelo)."""
    herramienta = HERRAMIENTAS.get(nombre)
    if herramienta is None:
        raise HerramientaNoPermitida(f"Herramienta desconocida: {nombre}")

    args = argumentos or {}
    payload = json.dumps(args, ensure_ascii=False)

    # Preferir ToolContext del SDK (requiere tool_name/run_config).
    try:
        from agents.tool_context import ToolContext

        wrapper: Any = ToolContext(
            context=contexto,
            tool_name=nombre,
            tool_call_id=f"local-{nombre}",
            tool_arguments=payload,
            run_config=None,
        )
    except Exception:
        wrapper = RunContextWrapper(context=contexto)

    # Función Python original si el wrapper local la expone.
    raw = getattr(herramienta, "fn", None) or getattr(herramienta, "_fn", None)
    if callable(raw):
        resultado = raw(wrapper, **args)
        if inspect.isawaitable(resultado):
            resultado = await resultado
        return resultado if isinstance(resultado, str) else json.dumps(resultado, ensure_ascii=False)

    on_invoke = getattr(herramienta, "on_invoke_tool", None)
    if callable(on_invoke):
        return await on_invoke(wrapper, payload)

    raise HerramientaNoPermitida(f"No se pudo invocar la herramienta: {nombre}")
