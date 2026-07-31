"""Schemas Pydantic — Diagnóstico de aspirantes (Chatbot)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class AnalizarCabeceraIn(BaseModel):
    model_config = {"extra": "forbid"}
    cabecera_perfil: str = Field(..., min_length=1, max_length=5000)


class PerfilUrlIn(BaseModel):
    """Identificador opcional para recalcular perfil_url (nunca una URL completa)."""

    model_config = {"extra": "forbid"}
    identificador: Optional[str] = Field(None, max_length=200)


class PerfilUrlOut(BaseModel):
    aspirante_id: int
    perfil_url: Optional[str] = None



class AnalizarCabeceraOut(BaseModel):
    aspirante_id: int
    plataforma_codigo: str
    plataforma_nombre: Optional[str] = None
    identificador_detectado: Optional[str] = None
    nombre_perfil: Optional[str] = None
    metricas: Dict[str, Any] = Field(default_factory=dict)
    advertencias: List[str] = Field(default_factory=list)
    campos_confirmacion: List[str] = Field(default_factory=list)
    parser_especializado: bool = False
    perfil_url: Optional[str] = None
    dato_secundario_opciones: Optional[List[str]] = None


class EvaluacionGuardarIn(BaseModel):
    model_config = {"extra": "forbid"}
    cabecera_perfil: str = Field(..., min_length=1, max_length=5000)
    identificador_detectado: Optional[str] = Field(None, max_length=200)
    nombre_perfil: Optional[str] = Field(None, max_length=200)
    metricas: Dict[str, Any] = Field(default_factory=dict)
    talento_calificacion: str
    talento_observacion: Optional[str] = Field(None, max_length=1000)
    mercado_manual: Optional[str] = None  # bueno|regular|malo (otras plataformas)

    @field_validator("talento_calificacion")
    @classmethod
    def val_talento(cls, v: str) -> str:
        t = str(v or "").strip().lower()
        if t not in {"bueno", "regular", "malo"}:
            raise ValueError("talento_calificacion debe ser bueno, regular o malo")
        return t

    @field_validator("mercado_manual")
    @classmethod
    def val_mercado(cls, v: Optional[str]) -> Optional[str]:
        if v is None or str(v).strip() == "":
            return None
        t = str(v).strip().lower()
        if t not in {"bueno", "regular", "malo"}:
            raise ValueError("mercado_manual debe ser bueno, regular o malo")
        return t

    @field_validator("identificador_detectado", "nombre_perfil")
    @classmethod
    def strip_opt(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        t = str(v).strip()
        return t or None


class EvaluacionResultadoOut(BaseModel):
    id: int
    aspirante_id: int
    chatbot_configuracion_id: int
    plataforma_codigo: str
    cabecera_perfil: str
    identificador_detectado: Optional[str] = None
    nombre_perfil: Optional[str] = None
    metricas: Dict[str, Any] = Field(default_factory=dict)
    talento_calificacion: Optional[str] = None
    talento_observacion: Optional[str] = None
    puntaje_requisitos: Optional[float] = None
    puntaje_mercado: Optional[float] = None
    puntaje_talento: Optional[float] = None
    puntaje_global: Optional[float] = None
    resultado_requisitos: Optional[str] = None
    resultado_mercado: Optional[str] = None
    resultado_talento: Optional[str] = None
    resultado_global: Optional[str] = None
    motivo_bloqueo: Optional[str] = None
    evaluado_por: Optional[str] = None
    evaluado_por_nombre: Optional[str] = None
    evaluado_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    pesos: Optional[Dict[str, float]] = None
    perfil_url: Optional[str] = None
    mensaje_bloqueo: Optional[str] = None


class DiagnosticoAspiranteListItem(BaseModel):
    id: int
    nombre: Optional[str] = None
    telefono: Optional[str] = None
    plataforma_codigo: Optional[str] = None
    plataforma_nombre: Optional[str] = None
    chatbot_configuracion_id: Optional[int] = None
    usuario_plataforma: Optional[str] = None
    estado_flujo: Optional[str] = None
    estado_diagnostico: str  # pendiente | evaluado
    resultado_global: Optional[str] = None
    evaluado_at: Optional[datetime] = None
    evaluado_por: Optional[str] = None
    evaluado_por_nombre: Optional[str] = None


class DiagnosticoAspiranteDetalle(BaseModel):
    id: int
    nombre: Optional[str] = None
    telefono: Optional[str] = None
    mayor_edad: Optional[bool] = None
    disponibilidad_live: Optional[bool] = None
    cumple_requisitos: Optional[bool] = None
    usuario_plataforma: Optional[str] = None
    chatbot_configuracion_id: Optional[int] = None
    plataforma_codigo: Optional[str] = None
    plataforma_nombre: Optional[str] = None
    perfil_url: Optional[str] = None
    estado_diagnostico: str
    evaluacion: Optional[EvaluacionResultadoOut] = None
