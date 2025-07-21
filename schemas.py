from pydantic import BaseModel, EmailStr
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
class EventoIn(BaseModel):
    titulo: str
    inicio: datetime
    fin: datetime
    descripcion: Optional[str] = None
    tiktok_user: Optional[str] = None

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
