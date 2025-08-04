from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Union, Dict
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
    creador_id: Optional[int]

# ✅ Para salida (incluye ID)
# class EventoOut(EventoIn):
#     id: str
#     link_meet: Optional[str] = None

class EventoOut(EventoIn):
    id: str
    creador_id: Optional[int] = None  # Sobrescribir para hacerlo opcional
    link_meet: Optional[str] = None
    origen: Optional[str] = "google_calendar"  # Para distinguir fuentes

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

class PerfilCreadorSchema(BaseModel):
    # Datos personales
    nombre: Optional[str] = Field(None, max_length=100)
    edad: Optional[int] = Field(None, ge=0, le=120)
    genero: Optional[str] = Field(None, max_length=50)
    pais: Optional[str] = Field(None, max_length=100)
    ciudad: Optional[str] = Field(None, max_length=200)
    zona_horaria: Optional[str] = Field(None, max_length=100)
    idioma: Optional[str] = Field(None, max_length=100)
    estudios: Optional[Union[dict, list]] = None
    campo_estudios: Optional[str] = Field(None, max_length=200)
    puntaje_datos_personales: Optional[float] = Field(None, ge=0, le=100)
    puntaje_datos_personales_categoria: Optional[str] = Field(None, max_length=20)

    # Estadísticas
    puntaje_estadistico: Optional[float] = Field(None, ge=0, le=100)
    puntaje_estadistico_categoria: Optional[str] = Field(None, max_length=20)
    mejoras_sugeridas_estadistica: Optional[str] = Field(None, max_length=500)

    # Evaluación manual
    biografia: Optional[str] = Field(None, max_length=200)
    apariencia: Optional[int] = Field(None, ge=1, le=10)
    engagement: Optional[int] = Field(None, ge=1, le=10)
    calidad_contenido: Optional[int] = Field(None, ge=1, le=10)
    puntaje_manual: Optional[float] = Field(None, ge=0, le=100)
    puntaje_manual_categoria: Optional[str] = Field(None, max_length=20)
    usuario_id_evalua: Optional[int] = None
    mejoras_sugeridas_manual: Optional[str] = Field(None, max_length=500)

    # Preferencias y hábitos
    horario_preferido: Optional[dict] = None
    intencion_trabajo: Optional[dict] = None
    tiempo_disponible: Optional[dict] = None
    frecuencia_lives: Optional[int] = Field(None, ge=0, le=365)
    experiencia_otras_plataformas: Optional[dict] = None
    intereses: Optional[dict] = None
    tipo_contenido: Optional[dict] = None

    # Evaluación general
    puntaje_perfil: Optional[float] = Field(None, ge=0, le=100)
    puntaje_perfil_categoria: Optional[str] = Field(None, max_length=20)
    mejoras_sugeridas_perfil: Optional[str] = Field(None, max_length=500)

    puntaje_total: Optional[float] = Field(None, ge=0, le=100)
    puntaje_total_categoria: Optional[str] = Field(None, max_length=20)
    observaciones: Optional[str] = Field(None, max_length=500)

    class Config:
        schema_extra = {
            "example": {
                "nombre": "Juan Pérez",
                "edad": 28,
                "genero": "Masculino",
                "pais": "Colombia",
                "ciudad": "Medellín",
                "zona_horaria": "America/Bogota",
                "idioma": "español",
                "estudios": {"nivel": "universitario", "titulo": "Ingeniería"},
                "campo_estudios": "Ingeniería de Sistemas",
                "puntaje_datos_personales": 85.0,
                "puntaje_datos_personales_categoria": "Alto",
                "puntaje_estadistico": 75.0,
                "puntaje_estadistico_categoria": "Medio",
                "mejoras_sugeridas_estadistica": "Aumentar frecuencia de publicación.",
                "biografia": "Soy creador de contenido educativo.",
                "apariencia": 8,
                "engagement": 7,
                "calidad_contenido": 9,
                "puntaje_manual": 80.0,
                "puntaje_manual_categoria": "Alto",
                "usuario_id_evalua": 5,
                "mejoras_sugeridas_manual": "Mejorar diseño gráfico.",
                "horario_preferido": {"mañana": True, "tarde": False},
                "intencion_trabajo": {"tipo": "tiempo_completo"},
                "tiempo_disponible": {"horas_semana": 20},
                "frecuencia_lives": 3,
                "experiencia_otras_plataformas": {"tiktok": True, "instagram": False},
                "intereses": {"educación": True, "tecnología": True},
                "tipo_contenido": {"videos": True},
                "puntaje_perfil": 82.0,
                "puntaje_perfil_categoria": "Alto",
                "mejoras_sugeridas_perfil": "Definir una línea temática clara.",
                "puntaje_total": 83.0,
                "puntaje_total_categoria": "Alto",
                "observaciones": "Perfil con gran potencial de crecimiento."
            }
        }