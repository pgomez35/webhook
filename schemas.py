from pydantic import BaseModel, EmailStr, Field,field_validator
from typing import Optional, Union, Dict,List
from datetime import datetime, date


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

class EventoIn(BaseModel):
    titulo: str
    descripcion: Optional[str] = None
    inicio: datetime
    fin: datetime
    participantes_ids: List[int] = []  # << agregar esta línea
    link_meet: Optional[str] = None  # ← agregar esto si quieres permitir edición manual


class EventoOut(EventoIn):
    id: str
    link_meet: Optional[str] = None
    origen: Optional[str] = "google_calendar"  # Para distinguir fuentes
    participantes: Optional[List[dict]] = None  # ← para devolver nombres, roles, etc

# ===============================
# ESQUEMAS PARA ADMIN_USUARIO
# ===============================

class ChangePasswordRequest(BaseModel):
    user_id: int = Field(..., gt=0, description="ID del usuario")
    new_password: str = Field(..., min_length=6, description="Nueva contraseña (mínimo 6 caracteres)")

class AdminUsuarioBase(BaseModel):
    username: str
    nombre_completo: Optional[str] = None
    email: Optional[str] = None  # Cambié EmailStr por str para simplicidad
    telefono: Optional[str] = None
    rol: str
    grupo: Optional[str] = None
    activo: bool = True


class AdminUsuarioCreate(AdminUsuarioBase):
    password: Optional[str] = None   # 👈 ahora acepta password en texto plano (o vacío si se genera automática)


class AdminUsuarioUpdate(BaseModel):
    username: Optional[str] = None
    nombre_completo: Optional[str] = None
    email: Optional[str] = None
    telefono: Optional[str] = None
    rol: Optional[str] = None
    grupo: Optional[str] = None
    activo: Optional[bool] = None
    password: Optional[str] = None   # 👈 opcional para permitir cambio de contraseña


class AdminUsuarioResponse(AdminUsuarioBase):
    id: int
    creado_en: Optional[str] = None  # Como string ISO format
    actualizado_en: Optional[str] = None
    password_inicial: Optional[str] = None  # 👈 solo para mostrar al admin la contraseña asignada

    class Config:
        from_attributes = True


class AdminUsuarioLogin(BaseModel):
    username: str
    password: str



# ===============================
# ESQUEMAS PARA PERFIL_CREADOR  
# ===============================

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
    diagnostico: Optional[str] = Field(None, max_length=500)

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
                "diagnostico": "Perfil con gran potencial de crecimiento."
            }
        }
# # === Schema de ENTRADA (lo que envía el cliente) ===
# class DatosPersonalesInput(BaseModel):
#     nombre: Optional[str] = None
#     edad: Optional[int] = None
#     genero: Optional[str] = None
#     pais: Optional[str] = None
#     ciudad: Optional[str] = None
#     zona_horaria: Optional[str] = None
#     idioma: Optional[str] = None
#     campo_estudios: Optional[str] = None
#     estudios: Optional[str] = None
#     actividad_actual: Optional[str] = None
#
# # === Schema de SALIDA (lo que devuelve la API) ===
# class DatosPersonalesOutput(DatosPersonalesInput):
#     status: str
#     mensaje: str
#     puntaje_general: Optional[float] = None
#     puntaje_general_categoria: Optional[str] = None
#
# # === Sección: Datos Personales ===
# class DatosPersonalesSchema(DatosPersonalesOutput):
#     pass
#
# # # === Sección: Estadísticas / Métricas ===
# # class EstadisticasPerfilSchema(BaseModel):
# #     seguidores: Optional[int] = None
# #     siguiendo: Optional[int] = None
# #     videos: Optional[int] = None
# #     likes: Optional[int] = None
# #     duracion_emisiones: Optional[int] = None
# #     dias_emisiones: Optional[int] = None
# #     puntaje_estadistica: Optional[float] = None
# #     puntaje_estadistica_categoria: Optional[str] = None
#
# # === Input Schema (lo que recibe el endpoint) ===
# class EstadisticasPerfilInput(BaseModel):
#     seguidores: Optional[int] = None
#     siguiendo: Optional[int] = None
#     videos: Optional[int] = None
#     likes: Optional[int] = None
#     duracion_emisiones: Optional[int] = None
#     dias_emisiones: Optional[int] = None
#
# # === Output Schema (lo que responde el endpoint) ===
# class EstadisticasPerfilOutput(BaseModel):
#     status: str
#     mensaje: str
#     puntaje_estadistica: float
#     puntaje_estadistica_categoria: str
#
#     class Config:
#         schema_extra = {
#             "example": {
#                 "status": "ok",
#                 "mensaje": "Estadisticas actualizadas",
#                 "puntaje_estadistica": 75.0,
#                 "puntaje_estadistica_categoria": "medio"
#             }
#         }
#
#
# # === Sección: Evaluación Cualitativa / Manual ===
# class EvaluacionCualitativaInput(BaseModel):
#     biografia: Optional[str] = None
#     apariencia: Optional[int] = None
#     engagement: Optional[int] = None
#     calidad_contenido: Optional[int] = None
#     eval_biografia: Optional[int] = None
#     eval_foto: Optional[int] = None
#     metadata_videos: Optional[int] = None
#     potencial_estimado: Optional[str] = None
#
# # === Response Schema (lo que devuelve el endpoint) ===
# class EvaluacionCualitativaOutput(BaseModel):
#     status: str
#     mensaje: str
#     puntaje_manual: Optional[float] = None
#     puntaje_manual_categoria: Optional[str] = None
#     mejoras_sugeridas: Optional[str] = None  # O dict si lo devuelves agrupado
#
# # === Sección: Contenido / Preferencias ===
# class PreferenciasHabitosInput(BaseModel):
#     tiempo_disponible: Optional[int] = None
#     frecuencia_lives: Optional[int] = None
#     experiencia_otras_plataformas: Optional[Dict[str, int]] = None
#     experiencia_otras_plataformas_otro_nombre: Optional[str] = None
#     intereses: Optional[Dict[str, bool]] = None
#     tipo_contenido: Optional[Dict[str, bool]] = None
#     horario_preferido: Optional[str] = None
#     intencion_trabajo: Optional[str] = None
#
#     class Config:
#         schema_extra = {
#             "example": {
#                 "tiempo_disponible": 15,
#                 "frecuencia_lives": 3,
#                 "experiencia_otras_plataformas": {"youtube": 2, "twitch": 1},
#                 "experiencia_otras_plataformas_otro_nombre": "Kwai",
#                 "intereses": {"deportes": True, "gaming": True},
#                 "tipo_contenido": {"tutoriales": True, "entretenimiento": True},
#                 "horario_preferido": "tarde",
#                 "intencion_trabajo": "profesional"
#             }
#         }
#
# class PreferenciasHabitosOutput(PreferenciasHabitosInput):
#     status: Optional[str] = None
#     mensaje: Optional[str] = None
#     puntaje_habitos: Optional[float] = None
#     puntaje_habitos_categoria: Optional[str] = None
#
#     class Config:
#         schema_extra = {
#             "example": {
#                 "status": "ok",
#                 "mensaje": "Preferencias actualizadas",
#                 "puntaje_habitos": 82.5,
#                 "puntaje_habitos_categoria": "alto"
#             }
#         }
#
# # === Sección: Resumen ===
# class ResumenEvaluacionInput(BaseModel):
#     estado: Optional[str] = None
#     observaciones: Optional[str] = None
#
# class ResumenEvaluacionOutput(ResumenEvaluacionInput):
#     status: Optional[str] = None
#     mensaje: Optional[str] = None
#     puntaje_total: Optional[float] = None
#     puntaje_total_categoria: Optional[str] = None
#
# class ResumenEvaluacionSchema(ResumenEvaluacionOutput):
#     pass
#
# # === Esquema completo para actualizar todo ===
# class PerfilCreadorSchema(BaseModel):
#     datos_personales: Optional[DatosPersonalesOutput] = None
#     evaluacion_cualitativa: Optional[EvaluacionCualitativaOutput] = None
#     estadisticas: Optional[EstadisticasPerfilOutput] = None
#     preferencias: Optional[PreferenciasHabitosOutput] = None
#     resumen: Optional[ResumenEvaluacionOutput] = None

# # === Schema de ENTRADA (lo que envía el cliente) ===
# class DatosPersonalesInput(BaseModel):
#     nombre: Optional[str] = None
#     edad: Optional[int] = None
#     genero: Optional[str] = None
#     pais: Optional[str] = None
#     ciudad: Optional[str] = None
#     zona_horaria: Optional[str] = None
#     idioma: Optional[str] = None
#     campo_estudios: Optional[str] = None
#     estudios: Optional[str] = None
#     actividad_actual: Optional[str] = None
#
#
# # === Schema de SALIDA (lo que devuelve la API) ===
# class DatosPersonalesOutput(DatosPersonalesInput):
#     puntaje_general: Optional[float] = None
#     puntaje_general_categoria: Optional[str] = None
#
# # === Sección: Datos Personales ===
# class DatosPersonalesSchema(BaseModel):
#     nombre: Optional[str]
#     edad: Optional[int]
#     genero: Optional[str]
#     pais: Optional[str]
#     ciudad: Optional[str]
#     zona_horaria: Optional[str]
#     idioma: Optional[str]
#     campo_estudios: Optional[str]
#     estudios: Optional[str]
#     actividad_actual: Optional[str]
#     puntaje_general: Optional[float]= None
#     puntaje_general_categoria: Optional[str]= None
#
# # # === Sección: Evaluación Cualitativa / Manual ===
# # class EvaluacionCualitativaSchema(BaseModel):
# #     biografia: Optional[str]
# #     apariencia: Optional[int]
# #     engagement: Optional[int]
# #     calidad_contenido: Optional[int]
# #     eval_biografia: Optional[int]
# #     eval_foto: Optional[int]
# #     metadata_videos: Optional[int]
# #     potencial_estimado: Optional[str]
# #     usuario_evalua: Optional[str]
# #     mejoras_sugeridas: Optional[str]
# #     puntaje_manual: Optional[float]
# #     puntaje_manual_categoria: Optional[str]
#
#
# # === Sección: Estadísticas / Métricas ===
# class EstadisticasPerfilSchema(BaseModel):
#     seguidores: Optional[int]
#     siguiendo: Optional[int]
#     videos: Optional[int]
#     likes: Optional[int]
#     duracion_emisiones: Optional[int]
#     dias_emisiones: Optional[int]
#     puntaje_estadistica: Optional[float]
#     puntaje_estadistica_categoria: Optional[str]
#
# # === Sección: Evaluación Cualitativa / Manual ===
# class EvaluacionCualitativaSchema(BaseModel):
#     biografia: Optional[str] = None
#     apariencia: Optional[int] = None
#     engagement: Optional[int] = None
#     calidad_contenido: Optional[int] = None
#     eval_biografia: Optional[int] = None
#     eval_foto: Optional[int] = None
#     metadata_videos: Optional[int] = None
#     potencial_estimado: Optional[str] = None
#
#
# # === Response Schema (lo que devuelve el endpoint) ===
# class EvaluacionCualitativaResponse(BaseModel):
#     status: str
#     mensaje: str
#     puntaje_manual: float
#     puntaje_manual_categoria: str
#     mejoras_sugeridas: Optional[str] = None
#
#
# # === Sección: Contenido / Preferencias ===
# class PreferenciasHabitosSchema(BaseModel):
#     tiempo_disponible: Optional[int]
#     frecuencia_lives: Optional[int]
#     experiencia_otras_plataformas: Optional[Dict[str, int]]
#     experiencia_otras_plataformas_otro_nombre: Optional[str]
#     intereses: Optional[Dict[str, bool]]
#     tipo_contenido: Optional[Dict[str, bool]]
#     horario_preferido: Optional[str]
#     intencion_trabajo: Optional[str]
#     puntaje_habitos: Optional[float]
#     puntaje_habitos_categoria: Optional[str]
#
# # === Sección: Contenido / Preferencias ===
#
# # ✅ Schema para entrada (lo que el cliente puede enviar)
# class PreferenciasHabitosInput(BaseModel):
#     tiempo_disponible: Optional[int]
#     frecuencia_lives: Optional[int]
#     experiencia_otras_plataformas: Optional[Dict[str, int]]
#     experiencia_otras_plataformas_otro_nombre: Optional[str]
#     intereses: Optional[Dict[str, bool]]
#     tipo_contenido: Optional[Dict[str, bool]]
#     horario_preferido: Optional[str]
#     intencion_trabajo: Optional[str]
#
#     class Config:
#         schema_extra = {
#             "example": {
#                 "tiempo_disponible": 15,
#                 "frecuencia_lives": 3,
#                 "experiencia_otras_plataformas": {"youtube": 2, "twitch": 1},
#                 "experiencia_otras_plataformas_otro_nombre": "Kwai",
#                 "intereses": {"deportes": True, "gaming": True},
#                 "tipo_contenido": {"tutoriales": True, "entretenimiento": True},
#                 "horario_preferido": "tarde",
#                 "intencion_trabajo": "profesional"
#             }
#         }
#
#
# # ✅ Schema para salida (lo que devuelve la API)
# class PreferenciasHabitosOutput(BaseModel):
#     status: str
#     mensaje: str
#     puntaje_habitos: float
#     puntaje_habitos_categoria: str
#
#     class Config:
#         schema_extra = {
#             "example": {
#                 "status": "ok",
#                 "mensaje": "Preferencias actualizadas",
#                 "puntaje_habitos": 82.5,
#                 "puntaje_habitos_categoria": "alto"
#             }
#         }
#
# # === Sección: Resumen ===
# class ResumenEvaluacionInput(BaseModel):
#     estado: Optional[str]         # el usuario puede actualizar estado
#     observaciones: Optional[str]  # observaciones iniciales opcionales
#
# class ResumenEvaluacionOutput(BaseModel):
#     estado: Optional[str]
#     observaciones: Optional[str]
#     puntaje_total: Optional[float]
#     puntaje_total_categoria: Optional[str]
#
#
# # === Sección: Resumen ===
# class ResumenEvaluacionSchema(BaseModel):
#     estado: Optional[str]
#     observaciones: Optional[str]
#     puntaje_total: Optional[float]
#     puntaje_total_categoria: Optional[str]
#
#
# # === Esquema completo para actualizar todo ===
# # class PerfilCreadorSchema(DatosPersonalesSchema,
# #                           EvaluacionCualitativaSchema,
# #                           EstadisticasPerfilSchema,
# #                           PreferenciasHabitosSchema,
# #                           ResumenEvaluacionSchema):
# #     pass
#
# class PerfilCreadorSchema(BaseModel):
#     datos_personales: DatosPersonalesOutput
#     evaluacion_cualitativa: EvaluacionCualitativaResponse
#     estadisticas: EstadisticasPerfilSchema
#     preferencias: PreferenciasHabitosOutput
#     resumen: ResumenEvaluacionOutput

# === Schema de ENTRADA (lo que envía el cliente) ===
class DatosPersonalesInput(BaseModel):
    nombre: Optional[str] = None
    edad: Optional[int] = None
    genero: Optional[str] = None
    pais: Optional[str] = None
    ciudad: Optional[str] = None
    zona_horaria: Optional[str] = None
    idioma: Optional[str] = None
    campo_estudios: Optional[str] = None
    estudios: Optional[str] = None
    actividad_actual: Optional[str] = None


# === Schema de SALIDA (lo que devuelve la API) ===
class DatosPersonalesOutput(DatosPersonalesInput):
    status: Optional[str] = None
    mensaje: Optional[str] = None
    puntaje_general: Optional[float] = None
    puntaje_general_categoria: Optional[str] = None

# === Input Schema (lo que recibe el endpoint) ===
class EstadisticasPerfilInput(BaseModel):
    seguidores: Optional[int] = None
    siguiendo: Optional[int] = None
    videos: Optional[int] = None
    likes: Optional[int] = None
    duracion_emisiones: Optional[int] = None
    dias_emisiones: Optional[int] = None

# === Output Schema (lo que responde el endpoint) ===
class EstadisticasPerfilOutput(BaseModel):
    status: str
    mensaje: str
    puntaje_estadistica: float = None
    puntaje_estadistica_categoria: str = None

# === Sección: Evaluación Cualitativa / Manual ===
class EvaluacionCualitativaInput(BaseModel):
    biografia: Optional[str] = None
    apariencia: Optional[int] = None
    engagement: Optional[int] = None
    calidad_contenido: Optional[int] = None
    eval_biografia: Optional[int] = None
    eval_foto: Optional[int] = None
    metadata_videos: Optional[int] = None
    biografia_sugerida: Optional[str] = None

# === Response Schema (lo que devuelve el endpoint) ===
class EvaluacionCualitativaOutput(BaseModel):
    status: str
    mensaje: str
    puntaje_manual: Optional[float] = None
    puntaje_manual_categoria: Optional[str] = None
    potencial_estimado: Optional[str] = None

class PreferenciasHabitosInput(BaseModel):
    tiempo_disponible: Optional[int] = None
    frecuencia_lives: Optional[int] = None
    experiencia_otras_plataformas: Optional[Dict[str, float]] = None  # 👈 aquí el cambio
    experiencia_otras_plataformas_otro_nombre: Optional[str] = None
    intereses: Optional[Dict[str, bool]] = None
    tipo_contenido: Optional[Dict[str, bool]] = None
    horario_preferido: Optional[str] = None
    intencion_trabajo: Optional[str] = None

class PreferenciasHabitosOutput(PreferenciasHabitosInput):
    status: Optional[str] = None
    mensaje: Optional[str] = None
    puntaje_habitos: Optional[float] = None
    puntaje_habitos_categoria: Optional[str] = None



# === Sección: Resumen ===
class ResumenEvaluacionInput(BaseModel):
    estado: Optional[str] = None  # 👈 para que no sea requerido
    puntaje_total: Optional[float] = None
    puntaje_total_categoria: Optional[str] = None


class ResumenEvaluacionOutput(ResumenEvaluacionInput):
    estado: Optional[str] = None  # 👈 para que no sea requerido
    status: Optional[str] = None
    mensaje: Optional[str] = None

    puntaje_manual: Optional[float] = None
    puntaje_manual_categoria: Optional[str] = None

    puntaje_estadistica: Optional[float] = None
    ppuntaje_estadistica_categoria: Optional[str] = None

    puntaje_general: Optional[float] = None
    puntaje_general_categoria: Optional[str] = None

    puntaje_habitos: Optional[float] = None
    puntaje_habitos_categoria: Optional[str] = None

    puntaje_total: Optional[float] = None
    puntaje_total_categoria: Optional[str] = None

    diagnostico: Optional[str] = None
    mejoras_sugeridas: Optional[str] = None
    fecha_entrevista: Optional[datetime] = None
    entrevista: Optional[bool] = False  # 👈 agregado aquí


class ResumenEvaluacionSchema(ResumenEvaluacionOutput):
    pass

# === Esquema completo para actualizar todo ===
class PerfilCreadorSchema(BaseModel):
    datos_personales: Optional[DatosPersonalesOutput] = None
    evaluacion_cualitativa: Optional[EvaluacionCualitativaOutput] = None
    estadisticas: Optional[EstadisticasPerfilOutput] = None
    preferencias: Optional[PreferenciasHabitosOutput] = None
    resumen: Optional[ResumenEvaluacionOutput] = None


# ===============================
# ESQUEMAS PARA CREADORES ACTIVOS
# ===============================

# ==== Modelos Pydantic ====
class CreadorActivoBase(BaseModel):
    creador_id: Optional[int] = None
    nombre: str
    usuario_tiktok: str
    foto: Optional[str] = None
    categoria: Optional[str] = None
    estado: Optional[str] = None
    manager_id: Optional[int] = None
    horario_lives: Optional[str] = None
    tiempo_disponible: Optional[int] = None
    fecha_incorporacion: Optional[date] = None
    fecha_graduacion: Optional[date] = None
    seguidores: Optional[int] = None
    videos: Optional[int] = None
    me_gusta: Optional[int] = None
    diamantes: Optional[int] = None
    horas_live: Optional[int] = None
    numero_partidas: Optional[int] = None
    dias_emision: Optional[int] = None

class CreadorActivoCreate(CreadorActivoBase):
    pass

class CreadorActivoUpdate(CreadorActivoBase):
    pass

class CreadorActivoDB(CreadorActivoBase):
    id: int

# Modelo extendido para la respuesta con el nombre del manager
class CreadorActivoConManager(CreadorActivoDB):
    manager_nombre: Optional[str] = None

class AdminUsuarioManagerResponse(BaseModel):
    id: int
    username: str
    nombre_completo: str
    grupo: str
    activo: bool

class CreadorActivoAutoCreate(BaseModel):
    creador_id: int
    fecha_incorporacion: Optional[date] = None
    manager_id: Optional[int] = None

# ESQUEMAS PARA SEGUIMIENTO
# Modelo base: para creación y actualización (entrada)
class SeguimientoCreadorBase(BaseModel):
    creador_id: int
    creador_activo_id: Optional[int] = None
    fecha_seguimiento: date
    estrategias_mejora: str
    compromisos: str

# Modelo extendido: para respuesta (salida)
class SeguimientoCreadorConManager(SeguimientoCreadorBase):
    id: int
    manager_id: int
    manager_nombre: Optional[str] = None

class SeguimientoCreadorCreate(SeguimientoCreadorBase):
    pass

class SeguimientoCreadorDB(SeguimientoCreadorBase):
    id: int
    class Config:
        orm_mode = True

# ESQUEMAS PARA ESTADISTICAS DE CREADOR ACTIVO
class EstadisticaCreadorBase(BaseModel):
    creador_id: int
    creador_activo_id: int
    fecha_reporte: date
    grupo: str
    diamantes_ult_30: int
    duracion_emsiones_live_ult_30: int

class EstadisticaCreadorCreate(EstadisticaCreadorBase):
    pass

class EstadisticaCreadorDB(EstadisticaCreadorBase):
    id: int

class PerfilCreadorUpdate(BaseModel):
    estado: Optional[str] = None
    estado_evaluacion: Optional[str] = None
    fecha_evaluacion_inicial: Optional[datetime] = None
    usuario_evaluador_inicial: Optional[int] = None
    entrevista: Optional[bool] = None
    fecha_entrevista: Optional[datetime] = None
    calificacion_entrevista: Optional[bool] = None
    usuario_evalua_entrevista: Optional[str] = None
    invitacion_tiktok: Optional[bool] = None
    fecha_invitacion_tiktok: Optional[datetime] = None
    acepta_invitacion: Optional[bool] = None
    usuario_invita_tiktok: Optional[int] = None


class EvaluacionInput(BaseModel):
    estado_evaluacion: str  # Solo se envía desde React

class EvaluacionOutput(BaseModel):
    status: str
    mensaje: str
    estado_id: int
    estado_evaluacion: str
    fecha_evaluacion_inicial: datetime
    usuario_evaluador_inicial: int


# ========== INVITACIONES ==========
class InvitacionBase(BaseModel):
    fecha_invitacion: Optional[date] = None
    usuario_invita: Optional[int] = None
    manager_id: Optional[int] = None
    estado: Optional[str] = None
    acepta_invitacion: Optional[bool] = None
    fecha_incorporacion: Optional[date] = None
    observaciones: Optional[str] = None

class InvitacionCreate(InvitacionBase):
    creador_id: int

class InvitacionUpdate(InvitacionBase):
    pass

class InvitacionOut(InvitacionBase):
    id: int
    creador_id: int
    creado_en: datetime

# ========== ENTREVISTAS ==========
class EntrevistaBase(BaseModel):
    fecha_programada: Optional[datetime] = None
    usuario_programa: Optional[int] = None
    realizada: Optional[bool] = False
    fecha_realizada: Optional[datetime] = None
    usuario_evalua: Optional[int] = None
    resultado: Optional[str] = None  # "sin evaluar" por defecto
    observaciones: Optional[str] = None
    evento_id: Optional[str] = None  # ← nuevo campo

class EntrevistaCreate(EntrevistaBase):
    creador_id: int

class EntrevistaUpdate(EntrevistaBase):
    pass

class EntrevistaOut(EntrevistaBase):
    id: int
    creador_id: int
    creado_en: datetime

class EstadoCreadorIn(BaseModel):
    # Puedes enviar UNO de los dos:
    estado_id: Optional[int] = None
    estado_evaluacion: Optional[str] = None  # "ENTREVISTA" | "NO APTO" | "INVITACION TIKTOK"

    @field_validator("estado_evaluacion")
    @classmethod
    def norm_estado(cls, v):
        if v is None:
            return v
        v = v.strip()
        return v.upper()

class EstadoCreadorOut(BaseModel):
    id: int
    estado_id: int
    mensaje: str