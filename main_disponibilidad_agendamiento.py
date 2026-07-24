"""
CRUD de disponibilidad / bloqueos y consulta de horarios disponibles.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from DataBase import get_connection_context
from main_auth import obtener_usuario_actual
from main_agendamiento import _resolver_zona_horaria_agencia
import disponibilidad_agendamiento_service as disp

router = APIRouter()


class DisponibilidadIn(BaseModel):
    dia_semana: int = Field(..., ge=1, le=7)
    hora_inicio: str
    hora_fin: str
    activo: bool = True


class DisponibilidadUpdateIn(BaseModel):
    dia_semana: Optional[int] = Field(None, ge=1, le=7)
    hora_inicio: Optional[str] = None
    hora_fin: Optional[str] = None
    activo: Optional[bool] = None


class ActivoIn(BaseModel):
    activo: bool


class BloqueoIn(BaseModel):
    fecha: date
    hora_inicio: Optional[str] = None
    hora_fin: Optional[str] = None
    motivo: Optional[str] = Field(None, max_length=200)
    activo: bool = True
    dia_completo: bool = False


class BloqueoUpdateIn(BaseModel):
    fecha: Optional[date] = None
    hora_inicio: Optional[str] = None
    hora_fin: Optional[str] = None
    motivo: Optional[str] = Field(None, max_length=200)
    activo: Optional[bool] = None
    dia_completo: Optional[bool] = None


# ---------- Disponibilidad semanal ----------

@router.get("/api/agendamientos/disponibilidad")
def api_listar_disponibilidad(
    solo_activos: bool = Query(False),
    usuario_actual: Any = Depends(obtener_usuario_actual),
):
    with get_connection_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            return disp.listar_disponibilidad(cur, solo_activos=solo_activos)


@router.post("/api/agendamientos/disponibilidad", status_code=201)
def api_crear_disponibilidad(
    payload: DisponibilidadIn,
    usuario_actual: Any = Depends(obtener_usuario_actual),
):
    with get_connection_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                row = disp.crear_disponibilidad(
                    cur,
                    dia_semana=payload.dia_semana,
                    hora_inicio=payload.hora_inicio,
                    hora_fin=payload.hora_fin,
                    activo=payload.activo,
                )
                conn.commit()
                return row
            except HTTPException:
                conn.rollback()
                raise
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=500, detail="Error al crear la franja de disponibilidad.") from e


@router.put("/api/agendamientos/disponibilidad/{franja_id}")
def api_actualizar_disponibilidad(
    franja_id: int,
    payload: DisponibilidadUpdateIn,
    usuario_actual: Any = Depends(obtener_usuario_actual),
):
    with get_connection_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                row = disp.actualizar_disponibilidad(
                    cur,
                    franja_id=franja_id,
                    dia_semana=payload.dia_semana,
                    hora_inicio=payload.hora_inicio,
                    hora_fin=payload.hora_fin,
                    activo=payload.activo,
                )
                conn.commit()
                return row
            except HTTPException:
                conn.rollback()
                raise
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=500, detail="Error al actualizar la franja.") from e


@router.patch("/api/agendamientos/disponibilidad/{franja_id}/activo")
def api_activar_disponibilidad(
    franja_id: int,
    payload: ActivoIn,
    usuario_actual: Any = Depends(obtener_usuario_actual),
):
    with get_connection_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                row = disp.set_activo_disponibilidad(cur, franja_id, payload.activo)
                conn.commit()
                return row
            except HTTPException:
                conn.rollback()
                raise
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=500, detail="Error al cambiar el estado de la franja.") from e


@router.delete("/api/agendamientos/disponibilidad/{franja_id}", status_code=204)
def api_eliminar_disponibilidad(
    franja_id: int,
    usuario_actual: Any = Depends(obtener_usuario_actual),
):
    with get_connection_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                disp.eliminar_disponibilidad(cur, franja_id)
                conn.commit()
            except HTTPException:
                conn.rollback()
                raise
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=500, detail="Error al eliminar la franja.") from e


# ---------- Bloqueos ----------

@router.get("/api/agendamientos/bloqueos")
def api_listar_bloqueos(
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    solo_activos: bool = Query(False),
    usuario_actual: Any = Depends(obtener_usuario_actual),
):
    with get_connection_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            return disp.listar_bloqueos(
                cur,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                solo_activos=solo_activos,
            )


@router.post("/api/agendamientos/bloqueos", status_code=201)
def api_crear_bloqueo(
    payload: BloqueoIn,
    usuario_actual: Any = Depends(obtener_usuario_actual),
):
    hi = None if payload.dia_completo else payload.hora_inicio
    hf = None if payload.dia_completo else payload.hora_fin
    with get_connection_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                row = disp.crear_bloqueo(
                    cur,
                    fecha=payload.fecha,
                    hora_inicio=hi,
                    hora_fin=hf,
                    motivo=payload.motivo,
                    activo=payload.activo,
                )
                conn.commit()
                return row
            except HTTPException:
                conn.rollback()
                raise
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=500, detail="Error al crear el bloqueo.") from e


@router.put("/api/agendamientos/bloqueos/{bloqueo_id}")
def api_actualizar_bloqueo(
    bloqueo_id: int,
    payload: BloqueoUpdateIn,
    usuario_actual: Any = Depends(obtener_usuario_actual),
):
    kwargs: dict = {
        "fecha": payload.fecha,
        "motivo": payload.motivo if payload.motivo is not None else ...,
        "activo": payload.activo,
    }
    if payload.dia_completo is True:
        kwargs["hora_inicio"] = None
        kwargs["hora_fin"] = None
    elif payload.dia_completo is False or payload.hora_inicio is not None or payload.hora_fin is not None:
        kwargs["hora_inicio"] = payload.hora_inicio
        kwargs["hora_fin"] = payload.hora_fin
    else:
        kwargs["hora_inicio"] = ...
        kwargs["hora_fin"] = ...

    with get_connection_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                row = disp.actualizar_bloqueo(cur, bloqueo_id, **kwargs)
                conn.commit()
                return row
            except HTTPException:
                conn.rollback()
                raise
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=500, detail="Error al actualizar el bloqueo.") from e


@router.patch("/api/agendamientos/bloqueos/{bloqueo_id}/activo")
def api_activar_bloqueo(
    bloqueo_id: int,
    payload: ActivoIn,
    usuario_actual: Any = Depends(obtener_usuario_actual),
):
    with get_connection_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                row = disp.set_activo_bloqueo(cur, bloqueo_id, payload.activo)
                conn.commit()
                return row
            except HTTPException:
                conn.rollback()
                raise
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=500, detail="Error al cambiar el estado del bloqueo.") from e


@router.delete("/api/agendamientos/bloqueos/{bloqueo_id}", status_code=204)
def api_eliminar_bloqueo(
    bloqueo_id: int,
    usuario_actual: Any = Depends(obtener_usuario_actual),
):
    with get_connection_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                disp.eliminar_bloqueo(cur, bloqueo_id)
                conn.commit()
            except HTTPException:
                conn.rollback()
                raise
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=500, detail="Error al eliminar el bloqueo.") from e


# ---------- Horarios disponibles (público / portales) ----------

@router.get("/api/agendamientos/horarios-disponibles")
def api_horarios_disponibles(
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    duracion_minutos: int = Query(60, ge=5, le=480),
    intervalo_minutos: int = Query(30, ge=5, le=120),
):
    """
    Endpoint consumido por portales y links externos.
    No exige autenticación de staff; el tenant se resuelve por middleware.
    """
    zona = _resolver_zona_horaria_agencia()
    with get_connection_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            return disp.calcular_horarios_disponibles(
                cur,
                zona_horaria=zona,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                duracion_minutos=duracion_minutos,
                intervalo_minutos=intervalo_minutos,
            )
