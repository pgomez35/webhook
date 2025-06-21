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
