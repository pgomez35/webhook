from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime

class ActualizacionContactoInfo(BaseModel):
    estado_whatsapp: Optional[str] = None
    fecha_entrevista: Optional[str] = None  # formato ISO
    entrevista: Optional[str] = None

class MensajeEntrada(BaseModel):
    telefono: str
    mensaje: str

class NombreActualizacion(BaseModel):
    telefono: str
    nombre: str

# ✅ Para entrada (crear/editar)
# class EventoIn(BaseModel):
#     titulo: str
#     descripcion: Optional[str] = ""
#     inicio: datetime
#     fin: datetime
#     tiktok_user: Optional[str] = None
#     creador_id: Optional[int] = None
#     responsable_id: Optional[int] = None
#     estado: Optional[str] = "pendiente"

class EventoIn(BaseModel):
    titulo: str
    descripcion: Optional[str] = None
    inicio: datetime
    fin: datetime
    tiktok_user: Optional[str] = None
    creador_id: int
    ubicacion: Optional[str] = None
    prioridad: Optional[str] = "Media"  # 'Alta', 'Media', 'Baja'
    tipo_evento: Optional[str] = None
    recordatorio_minutos: Optional[int] = 15


# ✅ Para salida (incluye ID)
class EventoOut(EventoIn):
    id: str
    link_meet: Optional[str] = None

# ===============================
# ESQUEMAS PARA ADMIN_USUARIO
# ===============================

class AdminUsuarioBase(BaseModel):
    username: str
    nombre_completo: Optional[str] = None
    email: Optional[str] = None  # Cambié EmailStr por str para simplicidad
    telefono: Optional[str] = None
    rol: str
    grupo: Optional[str] = None
    activo: bool = True

class AdminUsuarioCreate(AdminUsuarioBase):
    password_hash: str

class AdminUsuarioUpdate(BaseModel):
    username: Optional[str] = None
    nombre_completo: Optional[str] = None
    email: Optional[str] = None
    telefono: Optional[str] = None
    rol: Optional[str] = None
    grupo: Optional[str] = None
    activo: Optional[bool] = None

class AdminUsuarioResponse(AdminUsuarioBase):
    id: int
    creado_en: Optional[str] = None  # Como string ISO format
    actualizado_en: Optional[str] = None
    
    class Config:
        from_attributes = True

class AdminUsuarioLogin(BaseModel):
    username: str
    password: str


# ===============================
# ESQUEMAS PARA PERFIL_CREADOR  
# ===============================

class EvaluacionInicialSchema(BaseModel):
    apariencia: Optional[int] = Field(None, ge=1, le=10)
    engagement: Optional[int] = Field(None, ge=1, le=10)
    calidad_contenido: Optional[int] = Field(None, ge=1, le=10)
    puntaje_total: Optional[float] = Field(None, ge=0, le=100)
    potencial_estimado: Optional[str] = Field(None, example="Alto", description="Bajo, Medio, Alto, Excelente")
    mejoras_sugeridas: Optional[str] = Field(None, max_length=1000)
    usuario_evalua: Optional[str] = Field(None, max_length=100, description="Usuario que realiza la evaluación")

    class Config:
        schema_extra = {
            "example": {
                "apariencia": 8,
                "engagement": 7,
                "calidad_contenido": 9,
                "puntaje_total": 78.5,
                "potencial_estimado": "Alto",
                "mejoras_sugeridas": "Podría mejorar la iluminación de sus videos.",
                "usuario_evalua": "admin_pedro"
            }
        }