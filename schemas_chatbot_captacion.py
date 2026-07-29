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
TIPOS_RECURSO = Literal["video", "document"]
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
    Recurso de bienvenida almacenado en JSONB.
    Tras Cloudinary: proveedor=cloudinary + metadatos (sin binarios ni secretos).
    `url` se mantiene como espejo de secure_url para compatibilidad de envío WhatsApp.
    """

    id: str = Field(..., max_length=80)
    tipo: TIPOS_RECURSO
    proveedor: Literal["cloudinary"] = "cloudinary"
    secure_url: Optional[str] = Field(None, max_length=2000)
    url: Optional[str] = Field(None, max_length=2000)
    public_id: Optional[str] = Field(None, max_length=500)
    asset_id: Optional[str] = Field(None, max_length=120)
    resource_type: Optional[Literal["video", "raw"]] = None
    format: Optional[str] = Field(None, max_length=20)
    bytes: Optional[int] = Field(None, ge=0)
    nombre_original: Optional[str] = Field(None, max_length=200)
    caption: Optional[str] = Field(None, max_length=300)
    nombre_archivo: Optional[str] = Field(None, max_length=150)
    momento_envio: Optional[str] = Field(None, max_length=40)
    mensaje_adicional: Optional[str] = Field(None, max_length=1000)
    orden: int = Field(..., ge=1, le=2)
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

    @field_validator("nombre_archivo", "nombre_original", "public_id", "asset_id", "format", "momento_envio")
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
        """Compatibilidad: completa resource_type / url desde campos parciales."""
        if not isinstance(data, dict):
            return data
        out = dict(data)
        tipo = out.get("tipo")
        if not out.get("resource_type"):
            if tipo == "video":
                out["resource_type"] = "video"
            elif tipo == "document":
                out["resource_type"] = "raw"
        secure = out.get("secure_url") or out.get("url")
        if secure:
            out["secure_url"] = secure
            out.setdefault("url", secure)
        if tipo == "document":
            nombre = out.get("nombre_archivo") or out.get("nombre_original")
            if nombre and not str(nombre).lower().endswith(".pdf"):
                out["nombre_archivo"] = f"{nombre}.pdf"
            elif nombre:
                out["nombre_archivo"] = nombre
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
            object.__setattr__(self, "nombre_archivo", None)
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


class ChatbotConfiguracionResponse(BaseModel):
    id: int
    agencia: AgenciaChatbotResponse
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


class ChatbotConfiguracionUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    activo: bool
    mensaje_bienvenida: str = Field(..., max_length=600)
    pregunta_usuario: str = Field(..., max_length=180)
    pregunta_mayor_edad: str = Field(..., max_length=150)
    pregunta_disponibilidad: str = Field(..., max_length=200)
    mensaje_aprobado: str = Field(..., max_length=300)
    mensaje_no_aprobado: str = Field(..., max_length=300)
    texto_boton_continuar: str = Field(..., max_length=20)
    accion_continuar: ACCIONES
    url_continuar: Optional[str] = Field(None, max_length=500)
    texto_boton_preguntas: str = Field(..., max_length=20)
    preguntas_frecuentes: List[PreguntaFrecuente] = Field(default_factory=list)
    recursos_bienvenida: List[RecursoBienvenida] = Field(default_factory=list)
    mensaje_error: str = Field(..., max_length=250)

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
        if len(recursos) > 2:
            raise ValueError("Máximo 2 recursos de bienvenida")

        videos = [r for r in recursos if r.tipo == "video"]
        docs = [r for r in recursos if r.tipo == "document"]
        if len(videos) > 1:
            raise ValueError("Máximo un video de bienvenida")
        if len(docs) > 1:
            raise ValueError("Máximo un documento de bienvenida")

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
    plataforma: str
    usuario_plataforma: Optional[str] = None
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
    resource_type: Literal["video", "raw"]
    asset_folder: str
    upload_url: str
    overwrite: bool = False
    unique_filename: bool = True
    tags: str


class MediaEliminarRequest(BaseModel):
    model_config = {"extra": "forbid"}

    public_id: str = Field(..., min_length=1, max_length=300)
    resource_type: Literal["video", "raw"]

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
