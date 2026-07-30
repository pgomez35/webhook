"""
Modelos Pydantic — Chatbot de captación.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


FAQ_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
ACCIONES = Literal["asesor", "url", "agendamiento", "finalizar"]
# pdf se acepta en entrada (legado) y se normaliza a document.
TIPOS_RECURSO = Literal["video", "document", "pdf", "image", "audio"]
MAX_RECURSOS_BIENVENIDA = 10
ESTADOS_ASPIRANTE = Literal[
    "nuevo",
    "en_proceso",
    "completado",
    "pendiente_asesor",
    "contactado",
    "aprobado",
    "descartado",
]
PLATAFORMAS = Literal["tiktok", "bigo", "twitch", "otra"]


def _strip_required(v: Any, field: str) -> str:
    if v is None:
        raise ValueError(f"{field} es obligatorio")
    texto = str(v).strip()
    if not texto:
        raise ValueError(f"{field} no puede estar vacío")
    return texto


def _validar_titulo_boton(v: Any, field: str, max_len: int = 20) -> str:
    """Meta impone máx. 20 caracteres en interactive.button reply titles."""
    texto = _strip_required(v, field)
    if len(texto) > max_len:
        raise ValueError(
            f"{field} no puede superar {max_len} caracteres (límite de WhatsApp). "
            f"Actual: {len(texto)}"
        )
    return texto


class PreguntaFrecuente(BaseModel):
    id: str = Field(..., max_length=50)
    titulo: str = Field(..., max_length=20)
    respuesta: str = Field(..., max_length=600)
    activo: bool = True
    orden: int = Field(..., ge=1)

    @field_validator("id")
    @classmethod
    def validar_id(cls, v: str) -> str:
        v = _strip_required(v, "id")
        if len(v) > 50:
            raise ValueError("id máximo 50 caracteres")
        if not FAQ_ID_RE.match(v):
            raise ValueError("id solo admite letras, números, guion y guion bajo (máx. 50)")
        return v

    @field_validator("titulo")
    @classmethod
    def validar_titulo(cls, v: str) -> str:
        return _validar_titulo_boton(v, "titulo", 20)

    @field_validator("respuesta")
    @classmethod
    def validar_respuesta(cls, v: str) -> str:
        texto = _strip_required(v, "respuesta")
        if len(texto) > 600:
            raise ValueError("respuesta máximo 600 caracteres")
        return texto


class RecursoBienvenida(BaseModel):
    """
    Recurso informativo / archivo adjunto en JSONB recursos_bienvenida.
    Tras Cloudinary: proveedor=cloudinary + metadatos (sin binarios ni secretos).
    `url` se mantiene como espejo de secure_url para compatibilidad de envío WhatsApp.
    Tipos canónicos: video | document | image | audio (alias pdf → document).
    """

    id: str = Field(..., max_length=80)
    tipo: TIPOS_RECURSO
    proveedor: Literal["cloudinary"] = "cloudinary"
    secure_url: Optional[str] = Field(None, max_length=2000)
    url: Optional[str] = Field(None, max_length=2000)
    public_id: Optional[str] = Field(None, max_length=500)
    asset_id: Optional[str] = Field(None, max_length=120)
    resource_type: Optional[Literal["video", "raw", "image"]] = None
    format: Optional[str] = Field(None, max_length=20)
    mime_type: Optional[str] = Field(None, max_length=100)
    bytes: Optional[int] = Field(None, ge=0)
    nombre_original: Optional[str] = Field(None, max_length=200)
    caption: Optional[str] = Field(None, max_length=300)
    nombre_archivo: Optional[str] = Field(None, max_length=150)
    momento_envio: Optional[str] = Field(None, max_length=40)
    mensaje_adicional: Optional[str] = Field(None, max_length=1000)
    orden: int = Field(..., ge=1, le=50)
    activo: bool = True

    @field_validator("id")
    @classmethod
    def validar_id(cls, v: str) -> str:
        v = _strip_required(v, "id")
        if len(v) > 80:
            raise ValueError("id máximo 80 caracteres")
        if not FAQ_ID_RE.match(v):
            raise ValueError("id solo admite letras, números, guion y guion bajo (máx. 80)")
        return v

    @field_validator("secure_url", "url")
    @classmethod
    def validar_https(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        texto = str(v).strip()
        if not texto:
            return None
        if not texto.startswith("https://"):
            raise ValueError("la URL debe comenzar por https://")
        return texto

    @field_validator("caption")
    @classmethod
    def validar_caption(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        texto = str(v).strip()
        if not texto:
            return None
        if len(texto) > 300:
            raise ValueError("caption máximo 300 caracteres")
        return texto

    @field_validator(
        "nombre_archivo",
        "nombre_original",
        "public_id",
        "asset_id",
        "format",
        "momento_envio",
        "mime_type",
    )
    @classmethod
    def strip_opcional(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        texto = str(v).strip()
        return texto or None

    @field_validator("mensaje_adicional")
    @classmethod
    def strip_mensaje_adicional(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        texto = str(v).strip()
        if not texto:
            return None
        if len(texto) > 1000:
            raise ValueError("mensaje_adicional máximo 1000 caracteres")
        return texto

    @field_validator("bytes", mode="before")
    @classmethod
    def coerce_bytes(cls, v: Any) -> Optional[int]:
        if v is None or v == "":
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    @model_validator(mode="before")
    @classmethod
    def normalizar_entrada(cls, data: Any) -> Any:
        """Compatibilidad: completa resource_type / url; alias pdf → document."""
        if not isinstance(data, dict):
            return data
        out = dict(data)
        tipo_raw = out.get("tipo")
        tipo_norm = str(tipo_raw or "").strip().lower()
        if tipo_norm in ("pdf", "documento", "doc"):
            out["tipo"] = "document"
            tipo_norm = "document"
        elif tipo_norm in ("imagen", "img", "photo", "foto"):
            out["tipo"] = "image"
            tipo_norm = "image"
        elif tipo_norm in ("voice", "voz"):
            out["tipo"] = "audio"
            tipo_norm = "audio"
        tipo = out.get("tipo")
        if not out.get("resource_type"):
            if tipo == "video":
                out["resource_type"] = "video"
            elif tipo == "image":
                out["resource_type"] = "image"
            elif tipo == "audio":
                # Cloudinary suele alojar audio en el endpoint video
                out["resource_type"] = "video"
            elif tipo_norm == "document":
                out["resource_type"] = "raw"
        secure = out.get("secure_url") or out.get("url")
        if secure:
            out["secure_url"] = secure
            out.setdefault("url", secure)
        if tipo_norm == "document":
            nombre = out.get("nombre_archivo") or out.get("nombre_original")
            if nombre:
                n = str(nombre).strip()
                base = n.rsplit("/", 1)[-1]
                if n.lower().endswith(".pdf"):
                    out["nombre_archivo"] = n
                elif "." not in base:
                    out["nombre_archivo"] = f"{n}.pdf"
                else:
                    out["nombre_archivo"] = n
        return out

    @model_validator(mode="after")
    def validar_tipo_archivo(self):
        secure = self.secure_url or self.url
        if not secure:
            raise ValueError("secure_url es obligatorio (carga Cloudinary)")
        if not self.public_id:
            raise ValueError("public_id es obligatorio (carga Cloudinary)")
        if not self.resource_type:
            raise ValueError("resource_type es obligatorio")

        object.__setattr__(self, "proveedor", "cloudinary")
        object.__setattr__(self, "secure_url", secure)
        object.__setattr__(self, "url", secure)

        if self.tipo == "video":
            if self.resource_type != "video":
                raise ValueError("video requiere resource_type=video")
        elif self.tipo == "image":
            if self.resource_type != "image":
                raise ValueError("image requiere resource_type=image")
        elif self.tipo == "audio":
            if self.resource_type not in ("video", "raw"):
                raise ValueError("audio requiere resource_type=video o raw")
        elif self.tipo == "document":
            if self.resource_type != "raw":
                raise ValueError("document requiere resource_type=raw")
            nombre = self.nombre_archivo or self.nombre_original
            if not nombre:
                raise ValueError("nombre_archivo es obligatorio para document")
            if not str(nombre).lower().endswith(".pdf"):
                raise ValueError("nombre_archivo debe terminar en .pdf")
            object.__setattr__(self, "nombre_archivo", nombre)
        return self


class AgenciaChatbotResponse(BaseModel):
    id: int
    nombre: str
    codigo: str
    estado: str
    mensaje_seleccion_configuracion: Optional[str] = None
    seleccion_por_palabras_activa: bool = False


class CanalWhatsAppResponse(BaseModel):
    mapping_id: int
    whatsapp_account_id: int
    phone_number: Optional[str] = None
    phone_number_id: Optional[str] = None
    business_name: Optional[str] = None
    waba_id: Optional[str] = None
    status: Optional[str] = None
    onboarding_type: Optional[str] = None
    coexistence_enabled: Optional[bool] = None
    principal: bool = False
    activo: bool = True


class PlataformaResponse(BaseModel):
    codigo: str
    nombre: str
    activo: bool = True


class ChatbotConfiguracionResumen(BaseModel):
    """Tarjeta/listado de configuraciones de la agencia."""

    id: int
    codigo: str
    nombre: str
    plataforma_codigo: str
    plataforma_nombre: Optional[str] = None
    texto_opcion: str
    es_predeterminada: bool = False
    orden: int = 1
    activo: bool = True
    updated_at: Optional[datetime] = None


class ChatbotConfiguracionResponse(BaseModel):
    id: int
    agencia: AgenciaChatbotResponse
    codigo: str = "tiktok"
    nombre: str = "TikTok"
    plataforma_codigo: str = "tiktok"
    plataforma_nombre: Optional[str] = None
    texto_opcion: str = "TikTok"
    es_predeterminada: bool = False
    orden: int = 1
    mensaje_bienvenida: str
    pregunta_usuario: str
    pregunta_mayor_edad: str
    pregunta_disponibilidad: str
    mensaje_aprobado: str
    mensaje_no_aprobado: str
    texto_boton_continuar: str
    accion_continuar: str
    url_continuar: Optional[str] = None
    texto_boton_preguntas: str
    preguntas_frecuentes: List[PreguntaFrecuente] = Field(default_factory=list)
    recursos_bienvenida: List[RecursoBienvenida] = Field(default_factory=list)
    mensaje_error: str
    activo: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ChatbotConfiguracionCreate(BaseModel):
    model_config = {"extra": "forbid"}

    codigo: str = Field(..., max_length=80)
    nombre: str = Field(..., max_length=120)
    plataforma_codigo: str = Field(..., max_length=30)
    texto_opcion: str = Field(..., max_length=40)
    es_predeterminada: bool = False
    orden: Optional[int] = Field(None, ge=1)
    activo: bool = True
    mensaje_bienvenida: str = Field(..., max_length=600)
    pregunta_usuario: str = Field(..., max_length=300)
    pregunta_mayor_edad: str = Field(..., max_length=150)
    pregunta_disponibilidad: str = Field(..., max_length=200)
    mensaje_aprobado: str = Field(..., max_length=300)
    mensaje_no_aprobado: str = Field(..., max_length=300)
    # DB permite 40; Meta reply buttons máx. 20
    texto_boton_continuar: str = Field(..., max_length=40)
    accion_continuar: ACCIONES
    url_continuar: Optional[str] = Field(None, max_length=500)
    texto_boton_preguntas: str = Field(..., max_length=40)
    preguntas_frecuentes: List[PreguntaFrecuente] = Field(default_factory=list)
    recursos_bienvenida: List[RecursoBienvenida] = Field(default_factory=list)
    mensaje_error: str = Field(..., max_length=250)

    @field_validator("codigo", "plataforma_codigo")
    @classmethod
    def lower_codigo(cls, v: str, info) -> str:
        return _strip_required(v, info.field_name).lower()

    @field_validator("nombre", "texto_opcion")
    @classmethod
    def strip_meta(cls, v: str, info) -> str:
        return _strip_required(v, info.field_name)

    @field_validator("texto_opcion")
    @classmethod
    def validar_texto_opcion(cls, v: str) -> str:
        return _validar_titulo_boton(v, "texto_opcion", 20)

    @field_validator(
        "mensaje_bienvenida",
        "pregunta_usuario",
        "pregunta_mayor_edad",
        "pregunta_disponibilidad",
        "mensaje_aprobado",
        "mensaje_no_aprobado",
        "mensaje_error",
    )
    @classmethod
    def strip_textos(cls, v: str, info) -> str:
        return _strip_required(v, info.field_name)

    @field_validator("texto_boton_continuar", "texto_boton_preguntas")
    @classmethod
    def validar_titulos_botones(cls, v: str, info) -> str:
        return _validar_titulo_boton(v, info.field_name, 20)

    @field_validator("url_continuar")
    @classmethod
    def strip_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        texto = str(v).strip()
        return texto or None

    @model_validator(mode="after")
    def validar_accion_y_faqs(self):
        return _validar_config_flujo(self)


class ChatbotConfiguracionUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    activo: bool
    codigo: Optional[str] = Field(None, max_length=80)
    nombre: Optional[str] = Field(None, max_length=120)
    plataforma_codigo: Optional[str] = Field(None, max_length=30)
    texto_opcion: Optional[str] = Field(None, max_length=40)
    es_predeterminada: Optional[bool] = None
    orden: Optional[int] = Field(None, ge=1)
    mensaje_bienvenida: str = Field(..., max_length=600)
    pregunta_usuario: str = Field(..., max_length=300)
    pregunta_mayor_edad: str = Field(..., max_length=150)
    pregunta_disponibilidad: str = Field(..., max_length=200)
    mensaje_aprobado: str = Field(..., max_length=300)
    mensaje_no_aprobado: str = Field(..., max_length=300)
    # DB permite 40; Meta reply buttons máx. 20
    texto_boton_continuar: str = Field(..., max_length=40)
    accion_continuar: ACCIONES
    url_continuar: Optional[str] = Field(None, max_length=500)
    texto_boton_preguntas: str = Field(..., max_length=40)
    preguntas_frecuentes: List[PreguntaFrecuente] = Field(default_factory=list)
    recursos_bienvenida: List[RecursoBienvenida] = Field(default_factory=list)
    mensaje_error: str = Field(..., max_length=250)

    @field_validator("codigo", "plataforma_codigo")
    @classmethod
    def lower_codigo_opt(cls, v: Optional[str], info) -> Optional[str]:
        if v is None:
            return None
        return _strip_required(v, info.field_name).lower()

    @field_validator("nombre")
    @classmethod
    def strip_nombre(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return _strip_required(v, "nombre")

    @field_validator("texto_opcion")
    @classmethod
    def validar_texto_opcion(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return _validar_titulo_boton(v, "texto_opcion", 20)

    @field_validator(
        "mensaje_bienvenida",
        "pregunta_usuario",
        "pregunta_mayor_edad",
        "pregunta_disponibilidad",
        "mensaje_aprobado",
        "mensaje_no_aprobado",
        "mensaje_error",
    )
    @classmethod
    def strip_textos(cls, v: str, info) -> str:
        return _strip_required(v, info.field_name)

    @field_validator("texto_boton_continuar", "texto_boton_preguntas")
    @classmethod
    def validar_titulos_botones(cls, v: str, info) -> str:
        # Rechaza (>20), no trunca: evita 400 de Meta al enviar interactive.button
        return _validar_titulo_boton(v, info.field_name, 20)

    @field_validator("url_continuar")
    @classmethod
    def strip_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        texto = str(v).strip()
        return texto or None

    @model_validator(mode="after")
    def validar_accion_y_faqs(self):
        return _validar_config_flujo(self)


class ChatbotConfiguracionDuplicarIn(BaseModel):
    model_config = {"extra": "forbid"}

    codigo: Optional[str] = Field(None, max_length=80)
    nombre: Optional[str] = Field(None, max_length=120)


class ChatbotConfiguracionActivoIn(BaseModel):
    model_config = {"extra": "forbid"}

    activo: bool


class ChatbotConfiguracionReordenarItem(BaseModel):
    id: int
    orden: int = Field(..., ge=1)


class ChatbotConfiguracionReordenarIn(BaseModel):
    model_config = {"extra": "forbid"}

    ordenes: List[ChatbotConfiguracionReordenarItem] = Field(..., min_length=1)


class AgenciaMensajeSeleccionUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    # chatbot.agencias.mensaje_seleccion_configuracion varchar(300)
    mensaje_seleccion_configuracion: str = Field(..., max_length=300)
    seleccion_por_palabras_activa: Optional[bool] = None

    @field_validator("mensaje_seleccion_configuracion")
    @classmethod
    def strip_msg(cls, v: str) -> str:
        return _strip_required(v, "mensaje_seleccion_configuracion")


def _validar_config_flujo(self):
    # Doble chequeo post-strip (defensa ante bypass de Field max_length)
    for campo, valor in (
        ("texto_boton_continuar", self.texto_boton_continuar),
        ("texto_boton_preguntas", self.texto_boton_preguntas),
    ):
        if len(valor or "") > 20:
            raise ValueError(f"{campo} no puede superar 20 caracteres (límite de WhatsApp)")

    if self.accion_continuar in ("url", "agendamiento"):
        if not self.url_continuar:
            raise ValueError("url_continuar es obligatoria para accion url/agendamiento")
        if not self.url_continuar.startswith("https://"):
            raise ValueError("url_continuar debe comenzar por https://")

    faqs = self.preguntas_frecuentes or []
    if len(faqs) > 10:
        raise ValueError("Máximo 10 preguntas frecuentes")

    activas = [f for f in faqs if f.activo]
    if len(activas) > 3:
        raise ValueError("Máximo 3 preguntas frecuentes activas")

    ids = [f.id.lower() for f in faqs]
    if len(ids) != len(set(ids)):
        raise ValueError("Los id de FAQ deben ser únicos")

    titulos_activos = [f.titulo.strip().lower() for f in activas]
    if len(titulos_activos) != len(set(titulos_activos)):
        raise ValueError("No se permiten títulos activos duplicados")

    for faq in activas:
        if len(faq.titulo) > 20:
            raise ValueError(
                f"FAQ '{faq.id}': titulo activo supera 20 caracteres (límite WhatsApp)"
            )

    recursos = self.recursos_bienvenida or []
    if len(recursos) > MAX_RECURSOS_BIENVENIDA:
        raise ValueError(f"Máximo {MAX_RECURSOS_BIENVENIDA} recursos informativos")

    ids_rec = [r.id.lower() for r in recursos]
    if len(ids_rec) != len(set(ids_rec)):
        raise ValueError("Los id de recursos_bienvenida deben ser únicos")

    ordenes = [r.orden for r in recursos]
    if len(ordenes) != len(set(ordenes)):
        raise ValueError("No se permiten órdenes duplicados en recursos_bienvenida")

    return self


class ChatbotAspiranteResponse(BaseModel):
    id: int
    telefono: str
    nombre: Optional[str] = None
    plataforma: Optional[str] = None
    plataforma_codigo: Optional[str] = None
    usuario_plataforma: Optional[str] = None
    chatbot_configuracion_id: Optional[int] = None
    mayor_edad: Optional[bool] = None
    disponibilidad_live: Optional[bool] = None
    estado: str
    etapa_chatbot: str
    cumple_requisitos: Optional[bool] = None
    requiere_asesor: bool
    observaciones: Optional[str] = None
    whatsapp_account_id: Optional[int] = None
    phone_number_origen: Optional[str] = None
    business_name_origen: Optional[str] = None
    fecha_registro: Optional[datetime] = None
    ultima_interaccion: Optional[datetime] = None


class ChatbotAspiranteDetalle(ChatbotAspiranteResponse):
    agencia_id: int
    updated_at: Optional[datetime] = None


class ChatbotAspiranteUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    estado: Optional[ESTADOS_ASPIRANTE] = None
    requiere_asesor: Optional[bool] = None
    observaciones: Optional[str] = Field(None, max_length=500)

    @field_validator("observaciones")
    @classmethod
    def strip_obs(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return str(v).strip() or None


class ChatbotAspiranteReiniciarFlujoIn(BaseModel):
    model_config = {"extra": "forbid"}

    limpiar_respuestas: bool = False


class ChatbotResumenResponse(BaseModel):
    total: int = 0
    nuevos: int = 0
    en_proceso: int = 0
    completados: int = 0
    pendientes_asesor: int = 0
    contactados: int = 0
    aprobados: int = 0
    descartados: int = 0


class MediaFirmaRequest(BaseModel):
    model_config = {"extra": "forbid"}

    tipo: TIPOS_RECURSO


class MediaFirmaResponse(BaseModel):
    cloud_name: str
    api_key: str
    timestamp: int
    signature: str
    resource_type: Literal["video", "raw", "image"]
    asset_folder: str
    upload_url: str
    overwrite: bool = False
    unique_filename: bool = True
    tags: str


class MediaEliminarRequest(BaseModel):
    model_config = {"extra": "forbid"}

    public_id: str = Field(..., min_length=1, max_length=300)
    resource_type: Literal["video", "raw", "image"]

    @field_validator("public_id")
    @classmethod
    def strip_pid(cls, v: str) -> str:
        return str(v or "").strip()


class MediaEliminarResponse(BaseModel):
    ok: bool = True
    public_id: str
    eliminado_cloudinary: bool = True
    eliminado_config: bool = False


class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    results: List[Any]
