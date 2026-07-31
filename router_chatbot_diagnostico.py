"""
API Diagnóstico de aspirantes — producto Chatbot Talentum.
Aislado por agencia JWT. Requiere chatbot.agencias.diagnostico_habilitado.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from router_chatbot_auth import obtener_agencia_chatbot_actual, obtener_sesion_chatbot
from schemas_chatbot_diagnostico import (
    AnalizarCabeceraIn,
    AnalizarCabeceraOut,
    DiagnosticoAspiranteDetalle,
    EvaluacionGuardarIn,
    EvaluacionResultadoOut,
    PerfilUrlIn,
    PerfilUrlOut,
)
import service_chatbot_diagnostico as svc

router = APIRouter(
    prefix="/api/chatbot-captacion/diagnostico",
    tags=["Chatbot Diagnóstico"],
)


@router.get("/aspirantes")
def listar_aspirantes_diagnostico(
    plataforma: Optional[str] = Query(None),
    estado: Optional[str] = Query(None, description="Estado de gestión del aspirante"),
    estado_diagnostico: Optional[str] = Query(
        None, description="pendiente | evaluado"
    ),
    resultado_global: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
) -> Dict[str, Any]:
    return svc.listar_aspirantes(
        int(agencia["id"]),
        plataforma=plataforma,
        estado=estado,
        estado_diagnostico=estado_diagnostico,
        resultado_global=resultado_global,
        page=page,
        page_size=page_size,
    )


@router.get("/aspirantes/{aspirante_id}", response_model=DiagnosticoAspiranteDetalle)
def detalle_aspirante_diagnostico(
    aspirante_id: int,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
) -> DiagnosticoAspiranteDetalle:
    return svc.detalle_aspirante(int(agencia["id"]), aspirante_id)


@router.post(
    "/aspirantes/{aspirante_id}/analizar-cabecera",
    response_model=AnalizarCabeceraOut,
)
def analizar_cabecera_aspirante(
    aspirante_id: int,
    payload: AnalizarCabeceraIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
) -> AnalizarCabeceraOut:
    return svc.analizar(int(agencia["id"]), aspirante_id, payload)


@router.post(
    "/aspirantes/{aspirante_id}/perfil-url",
    response_model=PerfilUrlOut,
)
def recalcular_perfil_url(
    aspirante_id: int,
    payload: PerfilUrlIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
) -> PerfilUrlOut:
    """Recalcula perfil_url desde la plantilla de plataforma (sin persistir)."""
    return svc.calcular_perfil_url(int(agencia["id"]), aspirante_id, payload)


@router.put("/aspirantes/{aspirante_id}", response_model=EvaluacionResultadoOut)
def guardar_evaluacion_aspirante(
    aspirante_id: int,
    payload: EvaluacionGuardarIn,
    agencia: dict = Depends(obtener_agencia_chatbot_actual),
    sesion: dict = Depends(obtener_sesion_chatbot),
) -> EvaluacionResultadoOut:
    # evaluado_por = usuario autenticado (login), nunca desde el body
    evaluado_por = (sesion.get("usuario") or "").strip()
    if not evaluado_por:
        evaluado_por = str((sesion.get("agencia") or {}).get("nombre") or "").strip()

    return svc.guardar_evaluacion(
        int(agencia["id"]),
        aspirante_id,
        payload,
        evaluado_por=evaluado_por,
    )
