"""
Modelos Pydantic v2 — Chatbot conversacional.

Los ``Literal`` replican los CHECK del esquema ``chatbot`` para que una entrada
inválida se rechace en el borde de la API y nunca llegue a la base de datos.
Los schemas ``*Update`` tienen todos sus campos opcionales: los routers deben
usar ``model_dump(exclude_unset=True)`` para aplicar sólo lo enviado.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Literales alineados con los CHECK de la base de datos
# ---------------------------------------------------------------------------

Tono = Literal["cercano", "profesional", "juvenil", "energico", "formal", "personalizado"]
Modo = Literal["informativo", "conversion"]
EstrategiaNivelAspirante = Literal[
    "adaptativa",
    "orientada_principiantes",
    "orientada_experimentados",
    "nivel_fijo",
]
NivelExperiencia = Literal["desconocido", "principiante", "experimentado"]
FuenteNivelExperiencia = Literal[
    "inferida",
    "declarada",
    "formulario_ads",
    "campana",
    "manual",
    "respuesta_opcion",
    "configuracion_fija",
]
IntencionConversacional = Literal[
    "desconocida",
    "informacion",
    "requisitos",
    "beneficios",
    "bonos",
    "categorias",
    "incorporacion",
    "solicitud",
    "evidencias",
    "revision",
    "asesor",
]
AccionPropuestaClasificacion = Literal[
    "preguntar_nivel",
    "aclarar_nivel",
    "responder_informacion",
    "mostrar_requisitos",
    "mostrar_beneficios",
    "mostrar_bonos",
    "mostrar_categorias",
    "enviar_solicitud",
    "solicitar_evidencias",
    "confirmar_recepcion",
    "continuar_flujo",
    "orientar_principiante",
    "orientar_experimentado",
    "transferir_humano",
    "responder_texto",
    "ninguna",
]
CategoriaRequisito = Literal["obligatorio", "deseable", "informativo"]
TipoDatoRequisito = Literal["booleano", "entero", "decimal", "texto", "lista", "json"]
OperadorRequisito = Literal[
    "igual", "diferente", "mayor", "mayor_igual", "menor", "menor_igual", "contiene", "en_lista"
]
TipoBeneficio = Literal[
    "beneficio", "bono", "incentivo", "capacitacion", "acompanamiento", "otro"
]
TipoFlujo = Literal["informativo", "conversion"]
TipoAccionPaso = Literal[
    "informar",
    "hacer_pregunta",
    "confirmar_interes",
    "explicar_requisitos",
    "explicar_beneficios",
    "explicar_bonos",
    "enviar_enlace",
    "agendar_live",
    "solicitar_live",
    "solicitar_evidencias",
    "confirmar_evidencias",
    "transferir_humano",
    "esperar_respuesta",
    "finalizar",
]
CanalOrigen = Literal[
    "instagram_ads",
    "facebook_ads",
    "messenger_ads",
    "tiktok_ads",
    "whatsapp",
    "organico",
    "referido",
    "web",
    "otro",
]
TipoRecurso = Literal[
    "solicitud",
    "agendamiento",
    "privacidad",
    "terminos",
    "soporte",
    "whatsapp",
    "red_social",
    "instructivo",
    "otro",
]
TipoEvidenciaRequerida = Literal["imagen", "video", "documento", "url", "texto", "otro"]
MomentoEvidencia = Literal[
    "antes_live",
    "inicio_live",
    "durante_live",
    "durante_batalla",
    "final_live",
    "despues_live",
    "otro",
]
PrioridadEscalamiento = Literal["baja", "normal", "alta", "urgente"]
CanalDestinoEscalamiento = Literal[
    "whatsapp", "instagram", "messenger", "panel", "email", "otro"
]
CanalConversacion = Literal["whatsapp", "instagram", "messenger", "tiktok", "web", "otro"]
EstadoConversacion = Literal[
    "abierta", "esperando_usuario", "esperando_humano", "cerrada", "bloqueada"
]
DireccionMensaje = Literal["entrante", "saliente", "sistema"]
RemitenteMensaje = Literal["aspirante", "creador", "chatbot", "humano", "sistema"]
TipoMensaje = Literal[
    "texto", "imagen", "audio", "video", "documento", "ubicacion", "boton", "postback", "otro"
]
EstadoEnvioMensaje = Literal[
    "recibido", "procesando", "procesado", "enviado", "entregado", "leido", "error"
]
TipoTarea = Literal[
    "agendar_live",
    "realizar_live",
    "enviar_evidencias",
    "completar_solicitud",
    "hablar_con_manager",
    "confirmar_datos",
    "otro",
]
EstadoTarea = Literal["pendiente", "en_progreso", "completada", "vencida", "cancelada"]
CreadaPorTipo = Literal["chatbot", "humano", "sistema"]
TipoEvidenciaCandidato = Literal[
    "inicio_live",
    "durante_live",
    "batalla",
    "estadisticas_finales",
    "perfil_tiktok",
    "solicitud",
    "otro",
]
TipoArchivoEvidencia = Literal["imagen", "video", "documento", "url", "texto", "otro"]
EstadoRevisionEvidencia = Literal[
    "recibida", "pendiente", "en_revision", "aprobada", "rechazada", "solicitar_nuevamente"
]
TipoEvento = Literal[
    "inicio_conversacion",
    "cambio_estado",
    "cambio_flujo",
    "herramienta_ia",
    "escalamiento",
    "agendamiento",
    "tarea",
    "evidencia",
    "envio_enlace",
    "solicitud",
    "error",
    "cierre",
]
OrigenEvento = Literal["usuario", "chatbot", "humano", "backend", "meta", "sistema"]
DireccionOrden = Literal["subir", "bajar"]


CODIGO_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,99}$")


# ---------------------------------------------------------------------------
# Utilidades de validación
# ---------------------------------------------------------------------------


def _texto_obligatorio(valor: Any, campo: str) -> str:
    texto = str(valor or "").strip()
    if not texto:
        raise ValueError(f"{campo} no puede estar vacío")
    return texto


def _texto_opcional(valor: Any) -> Optional[str]:
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _normalizar_codigo(valor: Any, campo: str = "codigo") -> str:
    texto = _texto_obligatorio(valor, campo).lower()
    if not CODIGO_RE.match(texto):
        raise ValueError(
            f"{campo} sólo admite minúsculas, números, guion, guion bajo y punto"
        )
    return texto


def _validar_https(valor: Any, campo: str = "url") -> Optional[str]:
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    if not texto.lower().startswith("https://"):
        raise ValueError(f"{campo} debe ser una URL https")
    return texto


class _Entrada(BaseModel):
    """Base de los payloads: rechaza campos desconocidos."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Salida(BaseModel):
    """Base de las respuestas: acepta filas de RealDictCursor."""

    model_config = ConfigDict(from_attributes=True)


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Envoltura paginada reutilizable para los listados conversacionales."""

    total: int = 0
    page: int = 1
    page_size: int = 20
    results: List[T] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Asistente configurable
# ---------------------------------------------------------------------------


class AsistenteConfiguracionOut(_Salida):
    id: int
    agencia_id: int
    chatbot_configuracion_id: int
    nombre_asistente: str
    descripcion_agencia: Optional[str] = None
    presentacion_inicial: Optional[str] = None
    tono: Tono = "cercano"
    idioma: str = "es-CO"
    zona_horaria: str = "America/Bogota"
    declarar_asistente_virtual: bool = True
    modo_informativo_activo: bool = True
    modo_conversion_activo: bool = False
    modo_predeterminado: Modo = "informativo"
    proveedor_ia: str = "openai"
    modelo_ia: Optional[str] = None
    instrucciones_sistema: Optional[str] = None
    prompt_version: str = "1.0"
    max_tokens_salida: int = 600
    max_preguntas_seguidas: int = 2
    max_intentos_aclaracion: int = 2
    horario_atencion_humana: Dict[str, Any] = Field(default_factory=dict)
    mensaje_fuera_horario: Optional[str] = None
    herramientas_permitidas: List[Any] = Field(default_factory=list)
    contenido_prohibido: List[Any] = Field(default_factory=list)
    reglas_adicionales: Dict[str, Any] = Field(default_factory=dict)
    texto_privacidad: Optional[str] = None
    activo: bool = True
    estrategia_nivel_aspirante: EstrategiaNivelAspirante = "adaptativa"
    nivel_predeterminado: NivelExperiencia = "desconocido"
    nivel_fijo: Optional[Literal["principiante", "experimentado"]] = None
    permitir_reclasificacion_automatica: bool = True
    preguntar_nivel_si_ambiguo: bool = True
    umbral_confianza_nivel: float = 0.75
    max_preguntas_clasificacion: int = 1
    pregunta_clasificacion_nivel: str = (
        "¿Ya has realizado transmisiones LIVE?"
    )
    texto_inicio_principiante: Optional[str] = None
    texto_inicio_experimentado: Optional[str] = None
    formato_respuestas_informativas: Literal[
        "lista", "texto_breve", "automatico"
    ] = "lista"
    creado_por: Optional[int] = None
    actualizado_por: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AsistenteConfiguracionUpdate(_Entrada):
    """PUT del asistente: sólo se aplican los campos enviados."""

    nombre_asistente: Optional[str] = Field(None, max_length=120)
    descripcion_agencia: Optional[str] = Field(None, max_length=4000)
    presentacion_inicial: Optional[str] = Field(None, max_length=4000)
    tono: Optional[Tono] = None
    idioma: Optional[str] = Field(None, max_length=10)
    zona_horaria: Optional[str] = Field(None, max_length=60)
    declarar_asistente_virtual: Optional[bool] = None
    modo_informativo_activo: Optional[bool] = None
    modo_conversion_activo: Optional[bool] = None
    modo_predeterminado: Optional[Modo] = None
    proveedor_ia: Optional[str] = Field(None, max_length=30)
    modelo_ia: Optional[str] = Field(None, max_length=100)
    instrucciones_sistema: Optional[str] = Field(None, max_length=20000)
    prompt_version: Optional[str] = Field(None, max_length=40)
    max_tokens_salida: Optional[int] = Field(None, ge=100, le=4000)
    max_preguntas_seguidas: Optional[int] = Field(None, ge=1, le=10)
    max_intentos_aclaracion: Optional[int] = Field(None, ge=0, le=10)
    horario_atencion_humana: Optional[Dict[str, Any]] = None
    mensaje_fuera_horario: Optional[str] = Field(None, max_length=2000)
    herramientas_permitidas: Optional[List[str]] = None
    contenido_prohibido: Optional[List[str]] = None
    reglas_adicionales: Optional[Dict[str, Any]] = None
    texto_privacidad: Optional[str] = Field(None, max_length=8000)
    activo: Optional[bool] = None
    estrategia_nivel_aspirante: Optional[EstrategiaNivelAspirante] = None
    nivel_predeterminado: Optional[NivelExperiencia] = None
    nivel_fijo: Optional[Literal["principiante", "experimentado"]] = None
    permitir_reclasificacion_automatica: Optional[bool] = None
    preguntar_nivel_si_ambiguo: Optional[bool] = None
    umbral_confianza_nivel: Optional[float] = Field(None, ge=0, le=1)
    max_preguntas_clasificacion: Optional[int] = Field(None, ge=0, le=3)
    pregunta_clasificacion_nivel: Optional[str] = Field(None, max_length=2000)
    texto_inicio_principiante: Optional[str] = Field(None, max_length=4000)
    texto_inicio_experimentado: Optional[str] = Field(None, max_length=4000)
    formato_respuestas_informativas: Optional[
        Literal["lista", "texto_breve", "automatico"]
    ] = None

    @field_validator("nombre_asistente")
    @classmethod
    def _val_nombre(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _texto_obligatorio(v, "nombre_asistente")

    @field_validator(
        "descripcion_agencia",
        "presentacion_inicial",
        "instrucciones_sistema",
        "mensaje_fuera_horario",
        "texto_privacidad",
        "modelo_ia",
        "texto_inicio_principiante",
        "texto_inicio_experimentado",
    )
    @classmethod
    def _val_textos(cls, v: Optional[str]) -> Optional[str]:
        return _texto_opcional(v)

    @field_validator("pregunta_clasificacion_nivel")
    @classmethod
    def _val_pregunta_nivel(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return _texto_obligatorio(v, "pregunta_clasificacion_nivel")

    @model_validator(mode="after")
    def _val_modos_y_nivel(self) -> "AsistenteConfiguracionUpdate":
        if (
            self.modo_predeterminado == "conversion"
            and self.modo_conversion_activo is False
        ):
            raise ValueError(
                "No se puede fijar el modo conversión como predeterminado si está desactivado"
            )
        if (
            self.modo_predeterminado == "informativo"
            and self.modo_informativo_activo is False
        ):
            raise ValueError(
                "No se puede fijar el modo informativo como predeterminado si está desactivado"
            )

        estrategia = self.estrategia_nivel_aspirante
        if estrategia == "nivel_fijo":
            if self.nivel_fijo is None:
                raise ValueError(
                    "nivel_fijo es obligatorio cuando estrategia_nivel_aspirante=nivel_fijo"
                )
            if self.permitir_reclasificacion_automatica is True:
                raise ValueError(
                    "permitir_reclasificacion_automatica debe ser false con nivel_fijo"
                )
        elif estrategia is not None and self.nivel_fijo is not None:
            raise ValueError(
                "nivel_fijo debe ser null cuando la estrategia no es nivel_fijo"
            )
        return self


class ClasificacionConversacional(_Entrada):
    """Propuesta estructurada de clasificación; el backend valida y ejecuta."""

    nivel_experiencia: NivelExperiencia
    confianza_nivel: float = Field(..., ge=0, le=1)
    fuente_nivel: FuenteNivelExperiencia
    nivel_declarado_explicitamente: bool = False
    evidencia_nivel_breve: Optional[str] = Field(None, max_length=500)
    intencion: IntencionConversacional = "desconocida"
    confianza_intencion: float = Field(0.0, ge=0, le=1)
    accion_propuesta: AccionPropuestaClasificacion = "ninguna"
    respuesta_breve: Optional[str] = Field(None, max_length=2000)


class InicializarAsistenteIn(_Entrada):
    """
    Opciones del POST .../asistente/inicializar.

    El ``chatbot_configuracion_id`` NO va en el body: se toma de la ruta.
    El body puede ser ``{}`` o ausente; todos los flags tienen default True.
    """

    copiar_faq: bool = True
    crear_requisitos_base: bool = True
    crear_flujo_informativo: bool = True

    # Alias legados (por si algún cliente aún envía nombres anteriores).
    importar_faqs: Optional[bool] = Field(default=None, exclude=True)
    crear_flujo_base: Optional[bool] = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _aplicar_alias_legados(self):
        if self.importar_faqs is not None:
            self.copiar_faq = bool(self.importar_faqs)
        if self.crear_flujo_base is not None:
            self.crear_flujo_informativo = bool(self.crear_flujo_base)
        return self


class InicializarAsistenteOut(_Salida):
    asistente: Optional[AsistenteConfiguracionOut] = None
    asistente_creado: bool = False
    faqs_importadas: int = 0
    requisitos_creados: int = 0
    flujo_id: Optional[int] = None
    flujo_creado: bool = False
    pasos_creados: int = 0


# ---------------------------------------------------------------------------
# Configuración rápida
# ---------------------------------------------------------------------------


class ConfigRapidaItemRequisito(_Entrada):
    id: Optional[int] = Field(None, gt=0)
    nombre: str = Field(..., max_length=160)
    descripcion: Optional[str] = Field(None, max_length=4000)
    obligatorio: bool = True
    activo: bool = True
    codigo: Optional[str] = Field(None, max_length=80)


class ConfigRapidaItemBeneficio(_Entrada):
    id: Optional[int] = Field(None, gt=0)
    nombre: str = Field(..., max_length=160)
    descripcion: Optional[str] = Field(None, max_length=4000)
    valor: Optional[Any] = None
    moneda: Optional[str] = Field(None, max_length=10)
    requiere_confirmacion_humana: bool = False
    activo: bool = True
    codigo: Optional[str] = Field(None, max_length=80)
    tipo: Optional[str] = Field(None, max_length=40)


class ConfigRapidaItemFaq(_Entrada):
    id: Optional[int] = Field(None, gt=0)
    pregunta: str = Field(..., max_length=2000)
    respuesta: str = Field(..., max_length=8000)
    activo: bool = True
    codigo: Optional[str] = Field(None, max_length=100)


class ConfigRapidaGeneralIn(_Entrada):
    nombre_asistente: Optional[str] = Field(None, max_length=120)
    descripcion_agencia: Optional[str] = Field(None, max_length=4000)
    presentacion_inicial: Optional[str] = Field(None, max_length=4000)
    tono: Optional[Tono] = None
    modo_informativo_activo: Optional[bool] = None
    modo_conversion_activo: Optional[bool] = None


class ConfigRapidaSolicitudIn(_Entrada):
    url: Optional[str] = Field(None, max_length=2000)
    texto_boton: Optional[str] = Field(None, max_length=120)


class ConfigRapidaContactoIn(_Entrada):
    activo: Optional[bool] = None
    equipo_destino: Optional[str] = Field(None, max_length=120)
    mensaje_usuario: Optional[str] = Field(None, max_length=2000)


class ConfigRapidaEvidenciasIn(_Entrada):
    activo: Optional[bool] = None
    pedir_batalla: Optional[bool] = None
    pedir_mejores_momentos: Optional[bool] = None
    cantidad: Optional[int] = Field(None, ge=0, le=20)
    instrucciones: Optional[str] = Field(None, max_length=4000)


class ConfigRapidaContenidoIn(_Entrada):
    requisitos: Optional[List[ConfigRapidaItemRequisito]] = None
    beneficios: Optional[List[ConfigRapidaItemBeneficio]] = None
    bonos: Optional[List[ConfigRapidaItemBeneficio]] = None
    faq: Optional[List[ConfigRapidaItemFaq]] = None


class ConfigRapidaPutIn(_Entrada):
    general: Optional[ConfigRapidaGeneralIn] = None
    solicitud: Optional[ConfigRapidaSolicitudIn] = None
    contacto_humano: Optional[ConfigRapidaContactoIn] = None
    contenido: Optional[ConfigRapidaContenidoIn] = None
    evidencias: Optional[ConfigRapidaEvidenciasIn] = None


class AplicarPlantillaIn(_Entrada):
    plantilla_codigo: str = "agencia_live_estandar"
    completar_solo_faltantes: bool = True
    activar_asistente: bool = False


class CorregirHerramientasIn(_Entrada):
    confirmar: bool = False


class PublicarAsistenteIn(_Entrada):
    forzar: bool = False


# ---------------------------------------------------------------------------
# Carga de información (textos / Excel)
# ---------------------------------------------------------------------------


class AnalizarInformacionIn(_Entrada):
    nombre_asistente: Optional[str] = Field(None, max_length=120)
    presentacion_inicial: Optional[str] = Field(None, max_length=4000)
    tono: Optional[Literal["profesional", "cercano", "juvenil"]] = "cercano"
    requisitos_texto: Optional[str] = Field(None, max_length=20000)
    beneficios_texto: Optional[str] = Field(None, max_length=20000)
    bonos_texto: Optional[str] = Field(None, max_length=20000)
    faq_texto: Optional[str] = Field(None, max_length=40000)
    proceso_ingreso_texto: Optional[str] = Field(None, max_length=20000)
    enlaces_contacto_texto: Optional[str] = Field(None, max_length=20000)
    # False = solo analizador local (rápido). True = también OpenAI (más lento).
    usar_ia: bool = True


class PropuestaItemRequisito(_Entrada):
    id: Optional[int] = Field(None, gt=0)
    codigo: Optional[str] = None
    nombre: str = Field(..., max_length=160)
    descripcion: Optional[str] = Field(None, max_length=4000)
    categoria: Optional[str] = "obligatorio"
    bloquea_proceso: bool = True
    mensaje_si_no_cumple: Optional[str] = None
    orden: Optional[int] = None


class PropuestaItemBeneficio(_Entrada):
    id: Optional[int] = Field(None, gt=0)
    codigo: Optional[str] = None
    nombre: str = Field(..., max_length=160)
    descripcion: Optional[str] = Field(None, max_length=4000)
    tipo: Optional[str] = "beneficio"
    valor: Optional[Any] = None
    moneda: Optional[str] = None
    requiere_validacion_humana: bool = False
    requiere_confirmacion_humana: Optional[bool] = None
    orden: Optional[int] = None


class PropuestaItemFaq(_Entrada):
    id: Optional[int] = Field(None, gt=0)
    codigo: Optional[str] = None
    pregunta: str = Field(..., max_length=2000)
    respuesta: str = Field(..., max_length=8000)
    categoria: Optional[str] = "general"


class PropuestaItemPaso(_Entrada):
    orden: Optional[int] = None
    nombre: str = Field(..., max_length=160)
    descripcion: Optional[str] = None
    accion: Optional[str] = "informar"
    mensaje: Optional[str] = None
    requiere_humano: bool = False


class PropuestaItemRecurso(_Entrada):
    id: Optional[int] = Field(None, gt=0)
    codigo: Optional[str] = None
    tipo: Optional[str] = "solicitud"
    nombre: str = Field(..., max_length=160)
    url: str = Field(..., max_length=2000)
    texto_boton: Optional[str] = Field(None, max_length=120)


class GuardarInformacionOrganizadaIn(_Entrada):
    general: Optional[Dict[str, Any]] = None
    requisitos: Optional[List[PropuestaItemRequisito]] = None
    beneficios: Optional[List[PropuestaItemBeneficio]] = None
    bonos: Optional[List[PropuestaItemBeneficio]] = None
    faq: Optional[List[PropuestaItemFaq]] = None
    proceso_ingreso: Optional[List[PropuestaItemPaso]] = None
    recursos: Optional[List[PropuestaItemRecurso]] = None
    contacto_humano: Optional[Dict[str, Any]] = None
    advertencias: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Requisitos conversacionales
# ---------------------------------------------------------------------------


class RequisitoCreate(_Entrada):
    chatbot_configuracion_id: Optional[int] = Field(None, gt=0)
    codigo: str = Field(..., max_length=80)
    nombre: str = Field(..., max_length=160)
    descripcion: Optional[str] = Field(None, max_length=4000)
    categoria: CategoriaRequisito = "obligatorio"
    tipo_dato: TipoDatoRequisito = "texto"
    operador: Optional[OperadorRequisito] = None
    valor_minimo: Optional[Decimal] = None
    valor_maximo: Optional[Decimal] = None
    valor_texto: Optional[str] = Field(None, max_length=2000)
    valor_json: Dict[str, Any] = Field(default_factory=dict)
    unidad: Optional[str] = Field(None, max_length=40)
    bloquea_proceso: bool = False
    permitir_mencion_automatica: bool = True
    mensaje_si_no_cumple: Optional[str] = Field(None, max_length=2000)
    orden: int = Field(0, ge=0)
    version: int = Field(1, ge=1)
    vigencia_desde: Optional[date] = None
    vigencia_hasta: Optional[date] = None
    activo: bool = True

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: str) -> str:
        return _normalizar_codigo(v)

    @field_validator("nombre")
    @classmethod
    def _val_nombre(cls, v: str) -> str:
        return _texto_obligatorio(v, "nombre")

    @field_validator("descripcion", "valor_texto", "unidad", "mensaje_si_no_cumple")
    @classmethod
    def _val_opcionales(cls, v: Optional[str]) -> Optional[str]:
        return _texto_opcional(v)

    @model_validator(mode="after")
    def _val_rangos(self) -> "RequisitoCreate":
        if (
            self.valor_minimo is not None
            and self.valor_maximo is not None
            and self.valor_maximo < self.valor_minimo
        ):
            raise ValueError("valor_maximo debe ser mayor o igual que valor_minimo")
        if (
            self.vigencia_desde
            and self.vigencia_hasta
            and self.vigencia_hasta < self.vigencia_desde
        ):
            raise ValueError("vigencia_hasta debe ser posterior o igual a vigencia_desde")
        return self


class RequisitoUpdate(_Entrada):
    codigo: Optional[str] = Field(None, max_length=80)
    nombre: Optional[str] = Field(None, max_length=160)
    descripcion: Optional[str] = Field(None, max_length=4000)
    categoria: Optional[CategoriaRequisito] = None
    tipo_dato: Optional[TipoDatoRequisito] = None
    operador: Optional[OperadorRequisito] = None
    valor_minimo: Optional[Decimal] = None
    valor_maximo: Optional[Decimal] = None
    valor_texto: Optional[str] = Field(None, max_length=2000)
    valor_json: Optional[Dict[str, Any]] = None
    unidad: Optional[str] = Field(None, max_length=40)
    bloquea_proceso: Optional[bool] = None
    permitir_mencion_automatica: Optional[bool] = None
    mensaje_si_no_cumple: Optional[str] = Field(None, max_length=2000)
    orden: Optional[int] = Field(None, ge=0)
    version: Optional[int] = Field(None, ge=1)
    vigencia_desde: Optional[date] = None
    vigencia_hasta: Optional[date] = None
    activo: Optional[bool] = None

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _normalizar_codigo(v)

    @field_validator("nombre")
    @classmethod
    def _val_nombre(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _texto_obligatorio(v, "nombre")


class RequisitoOut(_Salida):
    id: int
    agencia_id: int
    chatbot_configuracion_id: Optional[int] = None
    codigo: str
    nombre: str
    descripcion: Optional[str] = None
    categoria: CategoriaRequisito
    tipo_dato: TipoDatoRequisito
    operador: Optional[OperadorRequisito] = None
    valor_minimo: Optional[Decimal] = None
    valor_maximo: Optional[Decimal] = None
    valor_texto: Optional[str] = None
    valor_json: Dict[str, Any] = Field(default_factory=dict)
    unidad: Optional[str] = None
    bloquea_proceso: bool = False
    permitir_mencion_automatica: bool = True
    mensaje_si_no_cumple: Optional[str] = None
    orden: int = 0
    version: int = 1
    vigencia_desde: Optional[date] = None
    vigencia_hasta: Optional[date] = None
    activo: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Beneficios y bonos
# ---------------------------------------------------------------------------


class BeneficioCreate(_Entrada):
    chatbot_configuracion_id: Optional[int] = Field(None, gt=0)
    campania_id: Optional[int] = Field(None, gt=0)
    codigo: str = Field(..., max_length=100)
    nombre: str = Field(..., max_length=180)
    tipo: TipoBeneficio = "beneficio"
    descripcion_corta: Optional[str] = Field(None, max_length=600)
    descripcion_completa: Optional[str] = Field(None, max_length=8000)
    texto_autorizado: Optional[str] = Field(None, max_length=4000)
    valor: Optional[Decimal] = Field(None, ge=0)
    moneda: Optional[str] = Field(None, min_length=3, max_length=3)
    formula_calculo: Optional[str] = Field(None, max_length=2000)
    condiciones: Dict[str, Any] = Field(default_factory=dict)
    paises_aplica: List[str] = Field(default_factory=list)
    perfiles_aplica: List[str] = Field(default_factory=list)
    requiere_validacion_humana: bool = False
    permitir_mencion_automatica: bool = True
    visible_publicamente: bool = True
    version: int = Field(1, ge=1)
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    activo: bool = True

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: str) -> str:
        return _normalizar_codigo(v)

    @field_validator("nombre")
    @classmethod
    def _val_nombre(cls, v: str) -> str:
        return _texto_obligatorio(v, "nombre")

    @field_validator("moneda")
    @classmethod
    def _val_moneda(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        texto = str(v).strip().upper()
        if len(texto) != 3 or not texto.isalpha():
            raise ValueError("moneda debe ser un código ISO de 3 letras (ej. COP)")
        return texto

    @model_validator(mode="after")
    def _val_coherencia(self) -> "BeneficioCreate":
        if self.valor is not None and not self.moneda:
            raise ValueError("Si el beneficio tiene valor debe indicar la moneda")
        if self.fecha_inicio and self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValueError("fecha_fin debe ser posterior o igual a fecha_inicio")
        if self.permitir_mencion_automatica and not (
            self.texto_autorizado or self.descripcion_corta
        ):
            raise ValueError(
                "Un beneficio de mención automática requiere texto_autorizado "
                "o descripcion_corta"
            )
        return self


class BeneficioUpdate(_Entrada):
    chatbot_configuracion_id: Optional[int] = Field(None, gt=0)
    campania_id: Optional[int] = Field(None, gt=0)
    codigo: Optional[str] = Field(None, max_length=100)
    nombre: Optional[str] = Field(None, max_length=180)
    tipo: Optional[TipoBeneficio] = None
    descripcion_corta: Optional[str] = Field(None, max_length=600)
    descripcion_completa: Optional[str] = Field(None, max_length=8000)
    texto_autorizado: Optional[str] = Field(None, max_length=4000)
    valor: Optional[Decimal] = Field(None, ge=0)
    moneda: Optional[str] = Field(None, min_length=3, max_length=3)
    formula_calculo: Optional[str] = Field(None, max_length=2000)
    condiciones: Optional[Dict[str, Any]] = None
    paises_aplica: Optional[List[str]] = None
    perfiles_aplica: Optional[List[str]] = None
    requiere_validacion_humana: Optional[bool] = None
    permitir_mencion_automatica: Optional[bool] = None
    visible_publicamente: Optional[bool] = None
    version: Optional[int] = Field(None, ge=1)
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    activo: Optional[bool] = None

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _normalizar_codigo(v)

    @field_validator("nombre")
    @classmethod
    def _val_nombre(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _texto_obligatorio(v, "nombre")

    @field_validator("moneda")
    @classmethod
    def _val_moneda(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        texto = str(v).strip().upper()
        if len(texto) != 3 or not texto.isalpha():
            raise ValueError("moneda debe ser un código ISO de 3 letras (ej. COP)")
        return texto


class BeneficioOut(_Salida):
    id: int
    agencia_id: int
    chatbot_configuracion_id: Optional[int] = None
    campania_id: Optional[int] = None
    codigo: str
    nombre: str
    tipo: TipoBeneficio
    descripcion_corta: Optional[str] = None
    descripcion_completa: Optional[str] = None
    texto_autorizado: Optional[str] = None
    valor: Optional[Decimal] = None
    moneda: Optional[str] = None
    formula_calculo: Optional[str] = None
    condiciones: Dict[str, Any] = Field(default_factory=dict)
    paises_aplica: List[Any] = Field(default_factory=list)
    perfiles_aplica: List[Any] = Field(default_factory=list)
    requiere_validacion_humana: bool = False
    permitir_mencion_automatica: bool = True
    visible_publicamente: bool = True
    version: int = 1
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    activo: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# FAQ conversacional
# ---------------------------------------------------------------------------


class FaqCreate(_Entrada):
    chatbot_configuracion_id: Optional[int] = Field(None, gt=0)
    codigo: str = Field(..., max_length=100)
    categoria: Optional[str] = Field(None, max_length=100)
    intencion: Optional[str] = Field(None, max_length=100)
    pregunta: str = Field(..., max_length=2000)
    respuesta_corta: Optional[str] = Field(None, max_length=600)
    respuesta_completa: str = Field(..., max_length=8000)
    palabras_clave: List[str] = Field(default_factory=list)
    requiere_humano: bool = False
    evento_escalamiento: Optional[str] = Field(None, max_length=100)
    prioridad: int = Field(0, ge=0, le=100)
    fuente: Optional[str] = Field(None, max_length=500)
    version: int = Field(1, ge=1)
    vigencia_desde: Optional[date] = None
    vigencia_hasta: Optional[date] = None
    activo: bool = True

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: str) -> str:
        return _normalizar_codigo(v)

    @field_validator("pregunta")
    @classmethod
    def _val_pregunta(cls, v: str) -> str:
        return _texto_obligatorio(v, "pregunta")

    @field_validator("respuesta_completa")
    @classmethod
    def _val_respuesta(cls, v: str) -> str:
        return _texto_obligatorio(v, "respuesta_completa")

    @field_validator("palabras_clave")
    @classmethod
    def _val_palabras(cls, v: List[str]) -> List[str]:
        limpias: List[str] = []
        for palabra in v or []:
            texto = str(palabra).strip().lower()
            if texto and texto not in limpias:
                limpias.append(texto[:80])
        return limpias

    @model_validator(mode="after")
    def _val_vigencia(self) -> "FaqCreate":
        if (
            self.vigencia_desde
            and self.vigencia_hasta
            and self.vigencia_hasta < self.vigencia_desde
        ):
            raise ValueError("vigencia_hasta debe ser posterior o igual a vigencia_desde")
        if self.requiere_humano and not self.evento_escalamiento:
            raise ValueError(
                "Una FAQ que requiere humano debe indicar evento_escalamiento"
            )
        return self


class FaqUpdate(_Entrada):
    codigo: Optional[str] = Field(None, max_length=100)
    categoria: Optional[str] = Field(None, max_length=100)
    intencion: Optional[str] = Field(None, max_length=100)
    pregunta: Optional[str] = Field(None, max_length=2000)
    respuesta_corta: Optional[str] = Field(None, max_length=600)
    respuesta_completa: Optional[str] = Field(None, max_length=8000)
    palabras_clave: Optional[List[str]] = None
    requiere_humano: Optional[bool] = None
    evento_escalamiento: Optional[str] = Field(None, max_length=100)
    prioridad: Optional[int] = Field(None, ge=0, le=100)
    fuente: Optional[str] = Field(None, max_length=500)
    version: Optional[int] = Field(None, ge=1)
    vigencia_desde: Optional[date] = None
    vigencia_hasta: Optional[date] = None
    activo: Optional[bool] = None

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _normalizar_codigo(v)

    @field_validator("pregunta", "respuesta_completa")
    @classmethod
    def _val_textos(cls, v: Optional[str], info) -> Optional[str]:
        return None if v is None else _texto_obligatorio(v, info.field_name)


class FaqOut(_Salida):
    id: int
    agencia_id: int
    chatbot_configuracion_id: Optional[int] = None
    codigo: str
    categoria: Optional[str] = None
    intencion: Optional[str] = None
    pregunta: str
    respuesta_corta: Optional[str] = None
    respuesta_completa: str
    palabras_clave: List[str] = Field(default_factory=list)
    requiere_humano: bool = False
    evento_escalamiento: Optional[str] = None
    prioridad: int = 0
    fuente: Optional[str] = None
    version: int = 1
    vigencia_desde: Optional[date] = None
    vigencia_hasta: Optional[date] = None
    activo: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ImportarFaqsIn(_Entrada):
    chatbot_configuracion_id: Optional[int] = Field(None, gt=0)
    faqs: List[Dict[str, Any]] = Field(default_factory=list)


class ImportarFaqsOut(_Salida):
    importadas: int = 0
    total_enviadas: int = 0


# ---------------------------------------------------------------------------
# Flujos y pasos
# ---------------------------------------------------------------------------


class FlujoCreate(_Entrada):
    chatbot_configuracion_id: int = Field(..., gt=0)
    codigo: str = Field(..., max_length=80)
    nombre: str = Field(..., max_length=160)
    tipo_flujo: TipoFlujo
    descripcion: Optional[str] = Field(None, max_length=4000)
    evento_inicio: Optional[str] = Field(None, max_length=100)
    estado_inicial: str = Field("inicio", max_length=80)
    estado_final: str = Field("finalizado", max_length=80)
    configuracion: Dict[str, Any] = Field(default_factory=dict)
    activo: bool = True

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: str) -> str:
        return _normalizar_codigo(v)

    @field_validator("nombre", "estado_inicial", "estado_final")
    @classmethod
    def _val_textos(cls, v: str, info) -> str:
        return _texto_obligatorio(v, info.field_name)


class FlujoUpdate(_Entrada):
    codigo: Optional[str] = Field(None, max_length=80)
    nombre: Optional[str] = Field(None, max_length=160)
    tipo_flujo: Optional[TipoFlujo] = None
    descripcion: Optional[str] = Field(None, max_length=4000)
    evento_inicio: Optional[str] = Field(None, max_length=100)
    estado_inicial: Optional[str] = Field(None, max_length=80)
    estado_final: Optional[str] = Field(None, max_length=80)
    configuracion: Optional[Dict[str, Any]] = None
    activo: Optional[bool] = None

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _normalizar_codigo(v)

    @field_validator("nombre", "estado_inicial", "estado_final")
    @classmethod
    def _val_textos(cls, v: Optional[str], info) -> Optional[str]:
        return None if v is None else _texto_obligatorio(v, info.field_name)


class FlujoPasoCreate(_Entrada):
    flujo_id: Optional[int] = Field(None, gt=0)
    codigo: str = Field(..., max_length=100)
    nombre: str = Field(..., max_length=180)
    descripcion: Optional[str] = Field(None, max_length=4000)
    orden: Optional[int] = Field(None, ge=0)
    tipo_accion: TipoAccionPaso
    obligatorio: bool = True
    permite_omitir: bool = False
    requiere_humano: bool = False
    mensaje_instrucciones: Optional[str] = Field(None, max_length=4000)
    estado_exitoso: Optional[str] = Field(None, max_length=100)
    estado_fallido: Optional[str] = Field(None, max_length=100)
    siguiente_paso_id: Optional[int] = Field(None, gt=0)
    siguiente_paso_fallo_id: Optional[int] = Field(None, gt=0)
    configuracion: Dict[str, Any] = Field(default_factory=dict)
    activo: bool = True

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: str) -> str:
        return _normalizar_codigo(v)

    @field_validator("nombre")
    @classmethod
    def _val_nombre(cls, v: str) -> str:
        return _texto_obligatorio(v, "nombre")

    @model_validator(mode="after")
    def _val_obligatoriedad(self) -> "FlujoPasoCreate":
        if self.obligatorio and self.permite_omitir:
            raise ValueError("Un paso obligatorio no puede permitir omitirse")
        return self


class FlujoPasoUpdate(_Entrada):
    codigo: Optional[str] = Field(None, max_length=100)
    nombre: Optional[str] = Field(None, max_length=180)
    descripcion: Optional[str] = Field(None, max_length=4000)
    orden: Optional[int] = Field(None, ge=0)
    tipo_accion: Optional[TipoAccionPaso] = None
    obligatorio: Optional[bool] = None
    permite_omitir: Optional[bool] = None
    requiere_humano: Optional[bool] = None
    mensaje_instrucciones: Optional[str] = Field(None, max_length=4000)
    estado_exitoso: Optional[str] = Field(None, max_length=100)
    estado_fallido: Optional[str] = Field(None, max_length=100)
    siguiente_paso_id: Optional[int] = Field(None, gt=0)
    siguiente_paso_fallo_id: Optional[int] = Field(None, gt=0)
    configuracion: Optional[Dict[str, Any]] = None
    activo: Optional[bool] = None

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _normalizar_codigo(v)

    @field_validator("nombre")
    @classmethod
    def _val_nombre(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _texto_obligatorio(v, "nombre")


class FlujoPasoOut(_Salida):
    id: int
    agencia_id: int
    flujo_id: int
    codigo: str
    nombre: str
    descripcion: Optional[str] = None
    orden: int = 0
    tipo_accion: TipoAccionPaso
    obligatorio: bool = True
    permite_omitir: bool = False
    requiere_humano: bool = False
    mensaje_instrucciones: Optional[str] = None
    estado_exitoso: Optional[str] = None
    estado_fallido: Optional[str] = None
    siguiente_paso_id: Optional[int] = None
    siguiente_paso_fallo_id: Optional[int] = None
    configuracion: Dict[str, Any] = Field(default_factory=dict)
    activo: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class FlujoOut(_Salida):
    id: int
    agencia_id: int
    chatbot_configuracion_id: int
    codigo: str
    nombre: str
    tipo_flujo: TipoFlujo
    descripcion: Optional[str] = None
    evento_inicio: Optional[str] = None
    estado_inicial: str = "inicio"
    estado_final: str = "finalizado"
    configuracion: Dict[str, Any] = Field(default_factory=dict)
    activo: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class FlujoDetalleOut(FlujoOut):
    pasos: List[FlujoPasoOut] = Field(default_factory=list)


class FlujoPasoMoverIn(_Entrada):
    direccion: DireccionOrden


class FlujoPasosReordenarIn(_Entrada):
    orden_ids: List[int] = Field(..., min_length=1)

    @field_validator("orden_ids")
    @classmethod
    def _val_ids(cls, v: List[int]) -> List[int]:
        if len(set(v)) != len(v):
            raise ValueError("orden_ids no puede contener identificadores repetidos")
        if any(int(x) <= 0 for x in v):
            raise ValueError("orden_ids sólo admite identificadores positivos")
        return [int(x) for x in v]


# ---------------------------------------------------------------------------
# Campañas de captación
# ---------------------------------------------------------------------------


class CampaniaCreate(_Entrada):
    chatbot_configuracion_id: int = Field(..., gt=0)
    flujo_id: Optional[int] = Field(None, gt=0)
    codigo: str = Field(..., max_length=100)
    nombre: str = Field(..., max_length=180)
    plataforma_codigo: str = Field(..., max_length=30)
    canal_origen: CanalOrigen
    identificador_externo: Optional[str] = Field(None, max_length=180)
    utm_source: Optional[str] = Field(None, max_length=150)
    utm_medium: Optional[str] = Field(None, max_length=150)
    utm_campaign: Optional[str] = Field(None, max_length=150)
    utm_content: Optional[str] = Field(None, max_length=150)
    modo_predeterminado: Modo = "conversion"
    candidato_preseleccionado: bool = True
    mensaje_inicial: Optional[str] = Field(None, max_length=4000)
    beneficio_principal: Optional[str] = Field(None, max_length=2000)
    publico_objetivo: Optional[str] = Field(None, max_length=2000)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    activo: bool = True

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: str) -> str:
        return _normalizar_codigo(v)

    @field_validator("plataforma_codigo")
    @classmethod
    def _val_plataforma(cls, v: str) -> str:
        return _texto_obligatorio(v, "plataforma_codigo").lower()

    @field_validator("nombre")
    @classmethod
    def _val_nombre(cls, v: str) -> str:
        return _texto_obligatorio(v, "nombre")

    @field_validator("identificador_externo")
    @classmethod
    def _val_identificador(cls, v: Optional[str]) -> Optional[str]:
        return _texto_opcional(v)

    @model_validator(mode="after")
    def _val_fechas(self) -> "CampaniaCreate":
        if self.fecha_inicio and self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValueError("fecha_fin debe ser posterior o igual a fecha_inicio")
        return self


class CampaniaUpdate(_Entrada):
    flujo_id: Optional[int] = Field(None, gt=0)
    codigo: Optional[str] = Field(None, max_length=100)
    nombre: Optional[str] = Field(None, max_length=180)
    plataforma_codigo: Optional[str] = Field(None, max_length=30)
    canal_origen: Optional[CanalOrigen] = None
    identificador_externo: Optional[str] = Field(None, max_length=180)
    utm_source: Optional[str] = Field(None, max_length=150)
    utm_medium: Optional[str] = Field(None, max_length=150)
    utm_campaign: Optional[str] = Field(None, max_length=150)
    utm_content: Optional[str] = Field(None, max_length=150)
    modo_predeterminado: Optional[Modo] = None
    candidato_preseleccionado: Optional[bool] = None
    mensaje_inicial: Optional[str] = Field(None, max_length=4000)
    beneficio_principal: Optional[str] = Field(None, max_length=2000)
    publico_objetivo: Optional[str] = Field(None, max_length=2000)
    metadata: Optional[Dict[str, Any]] = None
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    activo: Optional[bool] = None

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _normalizar_codigo(v)

    @field_validator("plataforma_codigo")
    @classmethod
    def _val_plataforma(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _texto_obligatorio(v, "plataforma_codigo").lower()

    @field_validator("nombre")
    @classmethod
    def _val_nombre(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _texto_obligatorio(v, "nombre")


class CampaniaOut(_Salida):
    id: int
    agencia_id: int
    chatbot_configuracion_id: int
    flujo_id: Optional[int] = None
    codigo: str
    nombre: str
    plataforma_codigo: str
    canal_origen: CanalOrigen
    identificador_externo: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_content: Optional[str] = None
    modo_predeterminado: Modo = "conversion"
    candidato_preseleccionado: bool = True
    mensaje_inicial: Optional[str] = None
    beneficio_principal: Optional[str] = None
    publico_objetivo: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    activo: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Recursos y enlaces
# ---------------------------------------------------------------------------


class RecursoCreate(_Entrada):
    chatbot_configuracion_id: Optional[int] = Field(None, gt=0)
    campania_id: Optional[int] = Field(None, gt=0)
    codigo: str = Field(..., max_length=100)
    nombre: str = Field(..., max_length=180)
    tipo: TipoRecurso
    url_template: str = Field(..., max_length=2000)
    descripcion: Optional[str] = Field(None, max_length=2000)
    texto_boton: Optional[str] = Field(None, max_length=100)
    requiere_token: bool = False
    tipo_token: Optional[str] = Field(None, max_length=40)
    abrir_externo: bool = True
    version: int = Field(1, ge=1)
    vigencia_desde: Optional[date] = None
    vigencia_hasta: Optional[date] = None
    activo: bool = True

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: str) -> str:
        return _normalizar_codigo(v)

    @field_validator("nombre")
    @classmethod
    def _val_nombre(cls, v: str) -> str:
        return _texto_obligatorio(v, "nombre")

    @field_validator("url_template")
    @classmethod
    def _val_url(cls, v: str) -> str:
        url = _validar_https(v, "url_template")
        if not url:
            raise ValueError("url_template es obligatorio")
        return url

    @model_validator(mode="after")
    def _val_token(self) -> "RecursoCreate":
        if self.requiere_token and not self.tipo_token:
            raise ValueError("tipo_token es obligatorio cuando requiere_token es true")
        if (
            self.vigencia_desde
            and self.vigencia_hasta
            and self.vigencia_hasta < self.vigencia_desde
        ):
            raise ValueError("vigencia_hasta debe ser posterior o igual a vigencia_desde")
        return self


class RecursoUpdate(_Entrada):
    chatbot_configuracion_id: Optional[int] = Field(None, gt=0)
    campania_id: Optional[int] = Field(None, gt=0)
    codigo: Optional[str] = Field(None, max_length=100)
    nombre: Optional[str] = Field(None, max_length=180)
    tipo: Optional[TipoRecurso] = None
    url_template: Optional[str] = Field(None, max_length=2000)
    descripcion: Optional[str] = Field(None, max_length=2000)
    texto_boton: Optional[str] = Field(None, max_length=100)
    requiere_token: Optional[bool] = None
    tipo_token: Optional[str] = Field(None, max_length=40)
    abrir_externo: Optional[bool] = None
    version: Optional[int] = Field(None, ge=1)
    vigencia_desde: Optional[date] = None
    vigencia_hasta: Optional[date] = None
    activo: Optional[bool] = None

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _normalizar_codigo(v)

    @field_validator("nombre")
    @classmethod
    def _val_nombre(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _texto_obligatorio(v, "nombre")

    @field_validator("url_template")
    @classmethod
    def _val_url(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _validar_https(v, "url_template")


class RecursoOut(_Salida):
    id: int
    agencia_id: int
    chatbot_configuracion_id: Optional[int] = None
    campania_id: Optional[int] = None
    codigo: str
    nombre: str
    tipo: TipoRecurso
    url_template: str
    descripcion: Optional[str] = None
    texto_boton: Optional[str] = None
    requiere_token: bool = False
    tipo_token: Optional[str] = None
    abrir_externo: bool = True
    version: int = 1
    vigencia_desde: Optional[date] = None
    vigencia_hasta: Optional[date] = None
    activo: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Prueba LIVE y evidencias requeridas
# ---------------------------------------------------------------------------


class EvidenciaRequeridaCreate(_Entrada):
    prueba_live_id: Optional[int] = Field(None, gt=0)
    codigo: str = Field(..., max_length=100)
    nombre: str = Field(..., max_length=180)
    descripcion: Optional[str] = Field(None, max_length=2000)
    tipo_evidencia: TipoEvidenciaRequerida
    momento_requerido: Optional[MomentoEvidencia] = None
    obligatoria: bool = True
    orden: int = Field(0, ge=0)
    formatos_permitidos: List[str] = Field(default_factory=list)
    ejemplo_url: Optional[str] = Field(None, max_length=2000)
    activo: bool = True

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: str) -> str:
        return _normalizar_codigo(v)

    @field_validator("nombre")
    @classmethod
    def _val_nombre(cls, v: str) -> str:
        return _texto_obligatorio(v, "nombre")

    @field_validator("ejemplo_url")
    @classmethod
    def _val_url(cls, v: Optional[str]) -> Optional[str]:
        return _validar_https(v, "ejemplo_url")

    @field_validator("formatos_permitidos")
    @classmethod
    def _val_formatos(cls, v: List[str]) -> List[str]:
        limpios: List[str] = []
        for formato in v or []:
            texto = str(formato).strip().lower().lstrip(".")
            if texto and texto not in limpios:
                limpios.append(texto[:20])
        return limpios


class EvidenciaRequeridaUpdate(_Entrada):
    codigo: Optional[str] = Field(None, max_length=100)
    nombre: Optional[str] = Field(None, max_length=180)
    descripcion: Optional[str] = Field(None, max_length=2000)
    tipo_evidencia: Optional[TipoEvidenciaRequerida] = None
    momento_requerido: Optional[MomentoEvidencia] = None
    obligatoria: Optional[bool] = None
    orden: Optional[int] = Field(None, ge=0)
    formatos_permitidos: Optional[List[str]] = None
    ejemplo_url: Optional[str] = Field(None, max_length=2000)
    activo: Optional[bool] = None

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _normalizar_codigo(v)

    @field_validator("nombre")
    @classmethod
    def _val_nombre(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _texto_obligatorio(v, "nombre")

    @field_validator("ejemplo_url")
    @classmethod
    def _val_url(cls, v: Optional[str]) -> Optional[str]:
        return _validar_https(v, "ejemplo_url")


class EvidenciaRequeridaOut(_Salida):
    id: int
    agencia_id: int
    prueba_live_id: int
    codigo: str
    nombre: str
    descripcion: Optional[str] = None
    tipo_evidencia: TipoEvidenciaRequerida
    momento_requerido: Optional[MomentoEvidencia] = None
    obligatoria: bool = True
    orden: int = 0
    formatos_permitidos: List[str] = Field(default_factory=list)
    ejemplo_url: Optional[str] = None
    activo: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PruebaLiveCreate(_Entrada):
    flujo_id: int = Field(..., gt=0)
    campania_id: Optional[int] = Field(None, gt=0)
    codigo: str = Field(..., max_length=100)
    nombre: str = Field(..., max_length=180)
    duracion_minima_minutos: int = Field(30, gt=0, le=1440)
    cantidad_batallas: int = Field(0, ge=0, le=100)
    requiere_agendamiento: bool = True
    zona_horaria: str = Field("America/Bogota", max_length=60)
    dias_permitidos: List[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7])
    horarios_permitidos: Dict[str, Any] = Field(default_factory=dict)
    plazo_evidencias_horas: int = Field(24, gt=0, le=720)
    permite_reintento: bool = True
    maximo_reintentos: int = Field(1, ge=0, le=10)
    instrucciones_antes: Optional[str] = Field(None, max_length=4000)
    instrucciones_durante: Optional[str] = Field(None, max_length=4000)
    instrucciones_despues: Optional[str] = Field(None, max_length=4000)
    activo: bool = True

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: str) -> str:
        return _normalizar_codigo(v)

    @field_validator("nombre")
    @classmethod
    def _val_nombre(cls, v: str) -> str:
        return _texto_obligatorio(v, "nombre")

    @field_validator("dias_permitidos")
    @classmethod
    def _val_dias(cls, v: List[int]) -> List[int]:
        dias = sorted({int(d) for d in (v or [])})
        if not dias:
            raise ValueError("dias_permitidos no puede estar vacío")
        if any(d < 1 or d > 7 for d in dias):
            raise ValueError("dias_permitidos usa 1 (lunes) a 7 (domingo)")
        return dias

    @model_validator(mode="after")
    def _val_reintentos(self) -> "PruebaLiveCreate":
        if not self.permite_reintento and self.maximo_reintentos > 0:
            raise ValueError(
                "maximo_reintentos debe ser 0 cuando no se permiten reintentos"
            )
        return self


class PruebaLiveUpdate(_Entrada):
    campania_id: Optional[int] = Field(None, gt=0)
    codigo: Optional[str] = Field(None, max_length=100)
    nombre: Optional[str] = Field(None, max_length=180)
    duracion_minima_minutos: Optional[int] = Field(None, gt=0, le=1440)
    cantidad_batallas: Optional[int] = Field(None, ge=0, le=100)
    requiere_agendamiento: Optional[bool] = None
    zona_horaria: Optional[str] = Field(None, max_length=60)
    dias_permitidos: Optional[List[int]] = None
    horarios_permitidos: Optional[Dict[str, Any]] = None
    plazo_evidencias_horas: Optional[int] = Field(None, gt=0, le=720)
    permite_reintento: Optional[bool] = None
    maximo_reintentos: Optional[int] = Field(None, ge=0, le=10)
    instrucciones_antes: Optional[str] = Field(None, max_length=4000)
    instrucciones_durante: Optional[str] = Field(None, max_length=4000)
    instrucciones_despues: Optional[str] = Field(None, max_length=4000)
    activo: Optional[bool] = None

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _normalizar_codigo(v)

    @field_validator("nombre")
    @classmethod
    def _val_nombre(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _texto_obligatorio(v, "nombre")

    @field_validator("dias_permitidos")
    @classmethod
    def _val_dias(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is None:
            return None
        dias = sorted({int(d) for d in v})
        if not dias:
            raise ValueError("dias_permitidos no puede estar vacío")
        if any(d < 1 or d > 7 for d in dias):
            raise ValueError("dias_permitidos usa 1 (lunes) a 7 (domingo)")
        return dias


class PruebaLiveOut(_Salida):
    id: int
    agencia_id: int
    flujo_id: int
    campania_id: Optional[int] = None
    codigo: str
    nombre: str
    duracion_minima_minutos: int = 30
    cantidad_batallas: int = 0
    requiere_agendamiento: bool = True
    zona_horaria: str = "America/Bogota"
    dias_permitidos: List[int] = Field(default_factory=list)
    horarios_permitidos: Dict[str, Any] = Field(default_factory=dict)
    plazo_evidencias_horas: int = 24
    permite_reintento: bool = True
    maximo_reintentos: int = 1
    instrucciones_antes: Optional[str] = None
    instrucciones_durante: Optional[str] = None
    instrucciones_despues: Optional[str] = None
    activo: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PruebaLiveDetalleOut(PruebaLiveOut):
    evidencias_requeridas: List[EvidenciaRequeridaOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Reglas de escalamiento
# ---------------------------------------------------------------------------


class ReglaEscalamientoCreate(_Entrada):
    chatbot_configuracion_id: Optional[int] = Field(None, gt=0)
    flujo_id: Optional[int] = Field(None, gt=0)
    campania_id: Optional[int] = Field(None, gt=0)
    evento: str = Field(..., max_length=100)
    descripcion: Optional[str] = Field(None, max_length=2000)
    prioridad: PrioridadEscalamiento = "normal"
    manager_id: Optional[int] = Field(None, gt=0)
    equipo_destino: Optional[str] = Field(None, max_length=120)
    canal_destino: CanalDestinoEscalamiento = "panel"
    mensaje_usuario: Optional[str] = Field(None, max_length=2000)
    mensaje_interno: Optional[str] = Field(None, max_length=2000)
    estado_destino: Optional[str] = Field(None, max_length=100)
    aplicar_fuera_horario: bool = True
    configuracion: Dict[str, Any] = Field(default_factory=dict)
    orden: int = Field(0, ge=0)
    activo: bool = True

    @field_validator("evento")
    @classmethod
    def _val_evento(cls, v: str) -> str:
        return _normalizar_codigo(v, "evento")

    @model_validator(mode="after")
    def _val_destino(self) -> "ReglaEscalamientoCreate":
        if self.canal_destino != "panel" and not (self.manager_id or self.equipo_destino):
            raise ValueError(
                "Fuera del panel se requiere manager_id o equipo_destino para notificar"
            )
        return self


class ReglaEscalamientoUpdate(_Entrada):
    chatbot_configuracion_id: Optional[int] = Field(None, gt=0)
    flujo_id: Optional[int] = Field(None, gt=0)
    campania_id: Optional[int] = Field(None, gt=0)
    evento: Optional[str] = Field(None, max_length=100)
    descripcion: Optional[str] = Field(None, max_length=2000)
    prioridad: Optional[PrioridadEscalamiento] = None
    manager_id: Optional[int] = Field(None, gt=0)
    equipo_destino: Optional[str] = Field(None, max_length=120)
    canal_destino: Optional[CanalDestinoEscalamiento] = None
    mensaje_usuario: Optional[str] = Field(None, max_length=2000)
    mensaje_interno: Optional[str] = Field(None, max_length=2000)
    estado_destino: Optional[str] = Field(None, max_length=100)
    aplicar_fuera_horario: Optional[bool] = None
    configuracion: Optional[Dict[str, Any]] = None
    orden: Optional[int] = Field(None, ge=0)
    activo: Optional[bool] = None

    @field_validator("evento")
    @classmethod
    def _val_evento(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _normalizar_codigo(v, "evento")


class ReglaEscalamientoOut(_Salida):
    id: int
    agencia_id: int
    chatbot_configuracion_id: Optional[int] = None
    flujo_id: Optional[int] = None
    campania_id: Optional[int] = None
    evento: str
    descripcion: Optional[str] = None
    prioridad: PrioridadEscalamiento = "normal"
    manager_id: Optional[int] = None
    equipo_destino: Optional[str] = None
    canal_destino: CanalDestinoEscalamiento = "panel"
    mensaje_usuario: Optional[str] = None
    mensaje_interno: Optional[str] = None
    estado_destino: Optional[str] = None
    aplicar_fuera_horario: bool = True
    configuracion: Dict[str, Any] = Field(default_factory=dict)
    orden: int = 0
    activo: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Mensajes, tareas, evidencias y eventos
# ---------------------------------------------------------------------------


class MensajeOut(_Salida):
    id: int
    agencia_id: int
    conversacion_id: int
    canal: CanalConversacion
    direccion: DireccionMensaje
    remitente_tipo: RemitenteMensaje
    tipo_mensaje: TipoMensaje = "texto"
    texto: Optional[str] = None
    media_url: Optional[str] = None
    media_id_externo: Optional[str] = None
    media_nombre: Optional[str] = None
    media_mime_type: Optional[str] = None
    mensaje_externo_id: Optional[str] = None
    respuesta_a_mensaje_id: Optional[int] = None
    estado_envio: EstadoEnvioMensaje = "recibido"
    error_detalle: Optional[str] = None
    procesado_por_ia: bool = False
    modelo_ia: Optional[str] = None
    prompt_version: Optional[str] = None
    tokens_entrada: Optional[int] = None
    tokens_salida: Optional[int] = None
    costo_estimado_usd: Optional[Decimal] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


class TareaCreate(_Entrada):
    conversacion_id: Optional[int] = Field(None, gt=0)
    aspirante_id: Optional[int] = Field(None, gt=0)
    paso_flujo_id: Optional[int] = Field(None, gt=0)
    tipo_tarea: TipoTarea
    titulo: str = Field(..., max_length=180)
    descripcion: Optional[str] = Field(None, max_length=4000)
    estado: EstadoTarea = "pendiente"
    fecha_limite: Optional[datetime] = None
    creada_por_tipo: CreadaPorTipo = "humano"
    creada_por_id: Optional[int] = Field(None, gt=0)
    configuracion_recordatorio: Dict[str, Any] = Field(default_factory=dict)
    datos_resultado: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("titulo")
    @classmethod
    def _val_titulo(cls, v: str) -> str:
        return _texto_obligatorio(v, "titulo")


class TareaUpdate(_Entrada):
    tipo_tarea: Optional[TipoTarea] = None
    titulo: Optional[str] = Field(None, max_length=180)
    descripcion: Optional[str] = Field(None, max_length=4000)
    estado: Optional[EstadoTarea] = None
    fecha_limite: Optional[datetime] = None
    completada_at: Optional[datetime] = None
    paso_flujo_id: Optional[int] = Field(None, gt=0)
    configuracion_recordatorio: Optional[Dict[str, Any]] = None
    datos_resultado: Optional[Dict[str, Any]] = None

    @field_validator("titulo")
    @classmethod
    def _val_titulo(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _texto_obligatorio(v, "titulo")


class TareaOut(_Salida):
    id: int
    agencia_id: int
    conversacion_id: int
    aspirante_id: Optional[int] = None
    paso_flujo_id: Optional[int] = None
    tipo_tarea: TipoTarea
    titulo: str
    descripcion: Optional[str] = None
    estado: EstadoTarea = "pendiente"
    fecha_limite: Optional[datetime] = None
    completada_at: Optional[datetime] = None
    creada_por_tipo: CreadaPorTipo = "chatbot"
    creada_por_id: Optional[int] = None
    configuracion_recordatorio: Dict[str, Any] = Field(default_factory=dict)
    datos_resultado: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class EvidenciaCreate(_Entrada):
    conversacion_id: Optional[int] = Field(None, gt=0)
    aspirante_id: Optional[int] = Field(None, gt=0)
    tarea_id: Optional[int] = Field(None, gt=0)
    mensaje_id: Optional[int] = Field(None, gt=0)
    evidencia_requerida_id: Optional[int] = Field(None, gt=0)
    tipo_evidencia: TipoEvidenciaCandidato
    tipo_archivo: Optional[TipoArchivoEvidencia] = None
    archivo_url: Optional[str] = Field(None, max_length=2000)
    archivo_id_externo: Optional[str] = Field(None, max_length=255)
    archivo_nombre: Optional[str] = Field(None, max_length=255)
    mime_type: Optional[str] = Field(None, max_length=120)
    valor_texto: Optional[str] = Field(None, max_length=8000)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    estado_revision: EstadoRevisionEvidencia = "recibida"
    capturada_at: Optional[datetime] = None

    @field_validator("archivo_url")
    @classmethod
    def _val_url(cls, v: Optional[str]) -> Optional[str]:
        return _validar_https(v, "archivo_url")

    @model_validator(mode="after")
    def _val_contenido(self) -> "EvidenciaCreate":
        if not (self.archivo_url or self.archivo_id_externo or self.valor_texto):
            raise ValueError(
                "La evidencia debe traer archivo_url, archivo_id_externo o valor_texto"
            )
        return self


class RevisionEvidenciaIn(_Entrada):
    estado_revision: Literal[
        "en_revision", "aprobada", "rechazada", "solicitar_nuevamente", "pendiente"
    ]
    observaciones_revision: Optional[str] = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _val_observaciones(self) -> "RevisionEvidenciaIn":
        if self.estado_revision in {"rechazada", "solicitar_nuevamente"} and not (
            self.observaciones_revision or ""
        ).strip():
            raise ValueError(
                "Debe indicar observaciones al rechazar o volver a solicitar la evidencia"
            )
        return self


class EvidenciaOut(_Salida):
    id: int
    agencia_id: int
    conversacion_id: int
    aspirante_id: Optional[int] = None
    tarea_id: Optional[int] = None
    mensaje_id: Optional[int] = None
    evidencia_requerida_id: Optional[int] = None
    tipo_evidencia: TipoEvidenciaCandidato
    tipo_archivo: Optional[TipoArchivoEvidencia] = None
    archivo_url: Optional[str] = None
    archivo_id_externo: Optional[str] = None
    archivo_nombre: Optional[str] = None
    mime_type: Optional[str] = None
    valor_texto: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    estado_revision: EstadoRevisionEvidencia = "recibida"
    observaciones_revision: Optional[str] = None
    revisado_por: Optional[int] = None
    revisado_at: Optional[datetime] = None
    capturada_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class EventoOut(_Salida):
    id: int
    agencia_id: int
    conversacion_id: int
    mensaje_id: Optional[int] = None
    tipo_evento: TipoEvento
    nombre_evento: str
    origen: OrigenEvento
    estado_anterior: Optional[str] = None
    estado_nuevo: Optional[str] = None
    exitoso: bool = True
    detalle: Dict[str, Any] = Field(default_factory=dict)
    error_detalle: Optional[str] = None
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Conversaciones
# ---------------------------------------------------------------------------


class ConversacionListItem(_Salida):
    id: int
    agencia_id: int
    chatbot_configuracion_id: Optional[int] = None
    aspirante_id: Optional[int] = None
    campania_id: Optional[int] = None
    campania_nombre: Optional[str] = None
    flujo_id: Optional[int] = None
    flujo_nombre: Optional[str] = None
    aspirante_nombre: Optional[str] = None
    plataforma_codigo: Optional[str] = None
    canal: CanalConversacion
    usuario_externo_id: str
    nombre_contacto: Optional[str] = None
    telefono: Optional[str] = None
    usuario_plataforma: Optional[str] = None
    modo: Modo = "informativo"
    estado: EstadoConversacion = "abierta"
    estado_actual: str = "inicio"
    ia_habilitada: bool = True
    modo_humano: bool = False
    manager_id: Optional[int] = None
    evidencias_pendientes: int = 0
    tareas_pendientes: int = 0
    iniciada_at: Optional[datetime] = None
    ultimo_mensaje_at: Optional[datetime] = None
    escalada_at: Optional[datetime] = None
    cerrada_at: Optional[datetime] = None


class ConversacionDetalle(ConversacionListItem):
    cuenta_externa_id: Optional[str] = None
    conversacion_externa_id: Optional[str] = None
    paso_actual_id: Optional[int] = None
    paso_actual_nombre: Optional[str] = None
    paso_actual_codigo: Optional[str] = None
    campania_codigo: Optional[str] = None
    flujo_codigo: Optional[str] = None
    configuracion_nombre: Optional[str] = None
    configuracion_plataforma: Optional[str] = None
    aspirante_telefono: Optional[str] = None
    aspirante_estado: Optional[str] = None
    motivo_escalamiento: Optional[str] = None
    proveedor_conversation_id: Optional[str] = None
    resumen_contexto: Optional[str] = None
    contexto: Dict[str, Any] = Field(default_factory=dict)
    consentimiento_datos: Optional[bool] = None
    consentimiento_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    mensajes: List[MensajeOut] = Field(default_factory=list)
    tareas: List[TareaOut] = Field(default_factory=list)
    evidencias: List[EvidenciaOut] = Field(default_factory=list)
    eventos: List[EventoOut] = Field(default_factory=list)


class ConversacionUpdate(_Entrada):
    estado: Optional[EstadoConversacion] = None
    estado_actual: Optional[str] = Field(None, max_length=100)
    modo: Optional[Modo] = None
    ia_habilitada: Optional[bool] = None
    flujo_id: Optional[int] = Field(None, gt=0)
    paso_actual_id: Optional[int] = Field(None, gt=0)
    aspirante_id: Optional[int] = Field(None, gt=0)
    nombre_contacto: Optional[str] = Field(None, max_length=180)
    telefono: Optional[str] = Field(None, max_length=25)
    usuario_plataforma: Optional[str] = Field(None, max_length=150)
    resumen_contexto: Optional[str] = Field(None, max_length=8000)
    contexto: Optional[Dict[str, Any]] = None
    consentimiento_datos: Optional[bool] = None


class ConversacionesResumen(_Salida):
    total: int = 0
    abiertas: int = 0
    esperando_usuario: int = 0
    esperando_humano: int = 0
    cerradas: int = 0
    bloqueadas: int = 0
    en_modo_humano: int = 0
    con_ia_activa: int = 0
    en_conversion: int = 0
    evidencias_pendientes: int = 0
    conversaciones_con_evidencias_pendientes: int = 0
    tareas_pendientes: int = 0
    tareas_vencidas: int = 0


# ---------------------------------------------------------------------------
# Acciones sobre la conversación
# ---------------------------------------------------------------------------


class TomarConversacionIn(_Entrada):
    """El manager se identifica por el token; aquí sólo viaja el contexto."""

    motivo: Optional[str] = Field(None, max_length=1000)

    @field_validator("motivo")
    @classmethod
    def _val_motivo(cls, v: Optional[str]) -> Optional[str]:
        return _texto_opcional(v)


class DevolverIaIn(_Entrada):
    estado: Literal["abierta", "esperando_usuario"] = "abierta"
    nota: Optional[str] = Field(None, max_length=1000)


class EnviarMensajeIn(_Entrada):
    texto: Optional[str] = Field(None, max_length=4000)
    tipo_mensaje: TipoMensaje = "texto"
    media_url: Optional[str] = Field(None, max_length=2000)
    media_nombre: Optional[str] = Field(None, max_length=255)
    media_mime_type: Optional[str] = Field(None, max_length=120)
    responder_a_mensaje_id: Optional[int] = Field(None, gt=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("media_url")
    @classmethod
    def _val_media(cls, v: Optional[str]) -> Optional[str]:
        return _validar_https(v, "media_url")

    @model_validator(mode="after")
    def _val_contenido(self) -> "EnviarMensajeIn":
        if self.tipo_mensaje == "texto":
            if not (self.texto or "").strip():
                raise ValueError("texto es obligatorio para un mensaje de tipo texto")
        elif not self.media_url:
            raise ValueError("media_url es obligatorio para mensajes con adjunto")
        return self


class EscalarConversacionIn(_Entrada):
    motivo: str = Field(..., max_length=1000)
    manager_id: Optional[int] = Field(None, gt=0)
    estado_destino: Optional[str] = Field(None, max_length=100)
    prioridad: PrioridadEscalamiento = "normal"

    @field_validator("motivo")
    @classmethod
    def _val_motivo(cls, v: str) -> str:
        return _texto_obligatorio(v, "motivo")


class CerrarConversacionIn(_Entrada):
    motivo: Optional[str] = Field(None, max_length=1000)
    estado_actual: Optional[str] = Field(None, max_length=100)

    @field_validator("motivo")
    @classmethod
    def _val_motivo(cls, v: Optional[str]) -> Optional[str]:
        return _texto_opcional(v)


class AsignarCampaniaIn(_Entrada):
    campania_id: int = Field(..., gt=0)
    aplicar_modo: bool = True
    aplicar_flujo: bool = True


class MensajeHistorialSimulacion(_Entrada):
    """Ítem de historial del simulador (acepta alias legibles)."""

    direccion: Optional[Literal["entrante", "saliente"]] = None
    texto: Optional[str] = Field(None, max_length=4000)
    rol: Optional[Literal["usuario", "asistente", "user", "assistant"]] = None
    contenido: Optional[str] = Field(None, max_length=4000)

    @model_validator(mode="after")
    def _normalizar(self):
        texto = (self.texto or self.contenido or "").strip()
        if not texto:
            raise ValueError("Cada mensaje del historial necesita texto o contenido")
        direccion = self.direccion
        if not direccion:
            rol = (self.rol or "").lower()
            if rol in {"usuario", "user"}:
                direccion = "entrante"
            elif rol in {"asistente", "assistant"}:
                direccion = "saliente"
        if direccion not in {"entrante", "saliente"}:
            raise ValueError(
                "Cada mensaje del historial necesita direccion entrante/saliente "
                "o rol usuario/asistente"
            )
        self.direccion = direccion
        self.texto = texto
        return self


class SimularMensajeIn(_Entrada):
    """
    Prueba el asistente sin tocar canales reales ni crear conversaciones.

    ``chatbot_configuracion_id`` NO es obligatorio: se toma de la ruta.
    Si un cliente antiguo lo envía en el body, el router exige que coincida
    con el ID del path.
    """

    mensaje: str = Field(..., max_length=4000)
    modo: Modo = "informativo"
    campania_id: Optional[int] = Field(None, gt=0)
    historial: List[MensajeHistorialSimulacion] = Field(default_factory=list)
    # Compatibilidad temporal con clientes antiguos (opcional).
    chatbot_configuracion_id: Optional[int] = Field(None, gt=0)

    @field_validator("mensaje")
    @classmethod
    def _val_mensaje(cls, v: str) -> str:
        return _texto_obligatorio(v, "mensaje")

    @field_validator("historial")
    @classmethod
    def _val_historial(
        cls, v: List[MensajeHistorialSimulacion]
    ) -> List[MensajeHistorialSimulacion]:
        if len(v or []) > 12:
            raise ValueError("El historial de simulación admite máximo 12 mensajes")
        return v or []


class SimularMensajeOut(_Salida):
    respuesta: str
    modo: Modo = "informativo"
    simulacion: bool = True
    estado_actual: Optional[str] = None
    requiere_humano: bool = False
    herramientas_usadas: List[str] = Field(default_factory=list)
    acciones: List[Any] = Field(default_factory=list)
    fuentes: List[Dict[str, Any]] = Field(default_factory=list)
    advertencias: List[str] = Field(default_factory=list)
    modelo_ia: Optional[str] = None
    tokens_entrada: Optional[int] = None
    tokens_salida: Optional[int] = None
    usado: bool = True
    motivo: Optional[str] = None
    uso: Optional[Dict[str, Any]] = None


class AspiranteCamposConversacionalesIn(_Entrada):
    origen_captacion: Optional[CanalOrigen] = None
    campania_id: Optional[int] = Field(None, gt=0)
    modo_conversacional: Optional[Modo] = None
    preseleccionado_ads: Optional[bool] = None


class ContextoAgenteOut(_Salida):
    """Conocimiento autorizado que se inyecta al asistente."""

    asistente: Optional[AsistenteConfiguracionOut] = None
    requisitos: List[RequisitoOut] = Field(default_factory=list)
    beneficios: List[BeneficioOut] = Field(default_factory=list)
    faqs: List[FaqOut] = Field(default_factory=list)
    recursos: List[RecursoOut] = Field(default_factory=list)
    campania: Optional[CampaniaOut] = None


class AccionSimpleOut(_Salida):
    ok: bool = True
    mensaje: Optional[str] = None
    id: Optional[int] = None


# ---------------------------------------------------------------------------
# Menú informativo
# ---------------------------------------------------------------------------

TipoFuenteMenuInformativo = Literal[
    "requisitos",
    "beneficios",
    "bonos",
    "faq",
    "texto",
    "asesor",
]


class MenuInformativoCreate(_Entrada):
    chatbot_configuracion_id: Optional[int] = Field(None, gt=0)
    numero: int = Field(..., ge=1, le=99)
    codigo: str = Field(..., max_length=100)
    titulo: str = Field(..., max_length=200)
    descripcion: Optional[str] = Field(None, max_length=1000)
    intencion: Optional[str] = Field(None, max_length=60)
    tipo_fuente: TipoFuenteMenuInformativo = "faq"
    respuesta_personalizada: Optional[str] = Field(None, max_length=8000)
    requiere_asesor: bool = False
    orden: int = Field(0, ge=0)
    activo: bool = True

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: str) -> str:
        return _normalizar_codigo(v)

    @field_validator("titulo")
    @classmethod
    def _val_titulo(cls, v: str) -> str:
        return _texto_obligatorio(v, "titulo")


class MenuInformativoUpdate(_Entrada):
    numero: Optional[int] = Field(None, ge=1, le=99)
    codigo: Optional[str] = Field(None, max_length=100)
    titulo: Optional[str] = Field(None, max_length=200)
    descripcion: Optional[str] = Field(None, max_length=1000)
    intencion: Optional[str] = Field(None, max_length=60)
    tipo_fuente: Optional[TipoFuenteMenuInformativo] = None
    respuesta_personalizada: Optional[str] = Field(None, max_length=8000)
    requiere_asesor: Optional[bool] = None
    orden: Optional[int] = Field(None, ge=0)
    activo: Optional[bool] = None

    @field_validator("codigo")
    @classmethod
    def _val_codigo(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _normalizar_codigo(v)

    @field_validator("titulo")
    @classmethod
    def _val_titulo(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _texto_obligatorio(v, "titulo")


class MenuInformativoOut(_Salida):
    id: int
    agencia_id: int
    chatbot_configuracion_id: int
    numero: int
    codigo: str
    titulo: str
    descripcion: Optional[str] = None
    intencion: Optional[str] = None
    tipo_fuente: TipoFuenteMenuInformativo
    respuesta_personalizada: Optional[str] = None
    requiere_asesor: bool = False
    orden: int = 0
    activo: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MenuInformativoReordenarIn(_Entrada):
    orden_ids: List[int] = Field(..., min_length=1)


class MenuInformativoInicializarOut(_Salida):
    insertadas: int = 0
    total: int = 0
    opciones: List[MenuInformativoOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Alias de compatibilidad con router_chatbot_conversacional
# ---------------------------------------------------------------------------

AsistenteConfiguracionUpsert = AsistenteConfiguracionUpdate
AsistenteInicializarIn = InicializarAsistenteIn
BeneficioIn = BeneficioCreate
CampaniaIn = CampaniaCreate
ConversacionAsignarCampaniaIn = AsignarCampaniaIn
ConversacionCerrarIn = CerrarConversacionIn
ConversacionEnviarMensajeIn = EnviarMensajeIn
ConversacionEscalarIn = EscalarConversacionIn
ConversacionTomarIn = TomarConversacionIn
EvidenciaRequeridaIn = EvidenciaRequeridaCreate
EvidenciaRevisionIn = RevisionEvidenciaIn
FaqConversacionalIn = FaqCreate
FaqImportarIn = ImportarFaqsIn
FlujoIn = FlujoCreate
FlujoPasoIn = FlujoPasoCreate
PruebaLiveIn = PruebaLiveCreate
RecursoEnlaceIn = RecursoCreate
ReglaEscalamientoIn = ReglaEscalamientoCreate
RequisitoIn = RequisitoCreate
SimulacionIn = SimularMensajeIn
TareaCandidatoUpdate = TareaUpdate
MenuInformativoIn = MenuInformativoCreate
