from pydantic import BaseModel
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

# ✅ Para salida (incluye ID)
class EventoOut(EventoIn):
    id: str
