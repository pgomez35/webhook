"""Servicio — Diagnóstico de aspirantes (Chatbot)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException

import database_chatbot_diagnostico as db
from diagnostico_parsers import analizar_cabecera
from diagnostico_reglas import (
    MOTIVO_BLOQUEO_MENOR,
    calcular_diagnostico,
    construir_url_perfil,
    normalizar_identificador_perfil,
    parse_numero_abreviado,
)
from schemas_chatbot_diagnostico import (
    AnalizarCabeceraIn,
    AnalizarCabeceraOut,
    DiagnosticoAspiranteDetalle,
    DiagnosticoAspiranteListItem,
    EvaluacionGuardarIn,
    EvaluacionResultadoOut,
    PerfilUrlIn,
    PerfilUrlOut,
)


MSG_DESHABILITADO = "Diagnóstico de perfiles no habilitado para esta agencia"
MSG_BLOQUEO_EDAD = "No cumple el requisito obligatorio de mayoría de edad"


def _exigir_habilitado(agencia_id: int) -> None:
    if not db.agencia_diagnostico_habilitado(agencia_id):
        raise HTTPException(status_code=403, detail=MSG_DESHABILITADO)


def _contexto_aspirante(agencia_id: int, aspirante_id: int) -> Dict[str, Any]:
    row = db.obtener_aspirante_con_plataforma(agencia_id, aspirante_id)
    if not row:
        raise HTTPException(status_code=404, detail="Aspirante no encontrado")
    if not row.get("chatbot_configuracion_id") or not row.get("config_id"):
        raise HTTPException(
            status_code=400,
            detail="El aspirante no tiene configuración de chatbot asociada",
        )
    if not row.get("plataforma_codigo"):
        raise HTTPException(
            status_code=400,
            detail="No se pudo determinar la plataforma desde la configuración",
        )
    return row


def _normalizar_metricas(metricas: Dict[str, Any], plataforma: str) -> Dict[str, Any]:
    out = dict(metricas or {})
    codigo = (plataforma or "").strip().lower()
    claves_num = []
    if codigo == "tiktok":
        claves_num = ["siguiendo", "seguidores", "me_gusta"]
    elif codigo == "bigo":
        claves_num = ["semillas", "dato_secundario"]
    else:
        # métricas manuales: convertir valores numéricos/abreviados
        for k, v in list(out.items()):
            if k.endswith("_tipo") or k in ("mercado_manual",):
                continue
            if isinstance(v, str):
                n = parse_numero_abreviado(v)
                if n is not None:
                    out[k] = n
        return out

    for k in claves_num:
        if k not in out or out[k] is None or out[k] == "":
            continue
        if isinstance(out[k], (int, float)) and not isinstance(out[k], bool):
            out[k] = int(out[k])
        else:
            n = parse_numero_abreviado(out[k])
            if n is not None:
                out[k] = n
    return out


def _evaluacion_out(
    row: Dict[str, Any],
    *,
    perfil_url: Optional[str] = None,
    pesos: Optional[Dict[str, float]] = None,
) -> EvaluacionResultadoOut:
    motivo = row.get("motivo_bloqueo")
    return EvaluacionResultadoOut(
        id=row["id"],
        aspirante_id=row["aspirante_id"],
        chatbot_configuracion_id=row["chatbot_configuracion_id"],
        plataforma_codigo=row.get("plataforma_codigo") or "",
        cabecera_perfil=row.get("cabecera_perfil") or "",
        identificador_detectado=row.get("identificador_detectado"),
        nombre_perfil=row.get("nombre_perfil"),
        metricas=row.get("metricas") or {},
        talento_calificacion=row.get("talento_calificacion"),
        talento_observacion=row.get("talento_observacion"),
        puntaje_requisitos=row.get("puntaje_requisitos"),
        puntaje_mercado=row.get("puntaje_mercado"),
        puntaje_talento=row.get("puntaje_talento"),
        puntaje_global=row.get("puntaje_global"),
        resultado_requisitos=row.get("resultado_requisitos"),
        resultado_mercado=row.get("resultado_mercado"),
        resultado_talento=row.get("resultado_talento"),
        resultado_global=row.get("resultado_global"),
        motivo_bloqueo=motivo,
        evaluado_por=row.get("evaluado_por") or None,
        evaluado_por_nombre=(
            row.get("evaluado_por_nombre") or row.get("evaluado_por") or None
        ),
        evaluado_at=row.get("evaluado_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        pesos=pesos,
        perfil_url=perfil_url,
        mensaje_bloqueo=MSG_BLOQUEO_EDAD if motivo == MOTIVO_BLOQUEO_MENOR else None,
    )


def listar_aspirantes(
    agencia_id: int,
    *,
    plataforma: Optional[str] = None,
    estado_diagnostico: Optional[str] = None,
    resultado_global: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    _exigir_habilitado(agencia_id)
    total, rows = db.listar_aspirantes_diagnostico(
        agencia_id,
        plataforma=plataforma,
        estado_diagnostico=estado_diagnostico,
        resultado_global=resultado_global,
        page=page,
        page_size=page_size,
    )
    items = [DiagnosticoAspiranteListItem(**r) for r in rows]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def _resolver_perfil_url(
    asp: Dict[str, Any],
    *,
    identificador: Optional[str] = None,
    evaluacion: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Plantilla desde chatbot.plataformas (vía configuración del aspirante).
    Identificador: argumento > evaluación > usuario_plataforma.
    """
    ident = normalizar_identificador_perfil(identificador)
    if not ident and evaluacion:
        ident = normalizar_identificador_perfil(evaluacion.get("identificador_detectado"))
    if not ident:
        ident = normalizar_identificador_perfil(asp.get("usuario_plataforma"))
    return construir_url_perfil(asp.get("perfil_url_template"), ident)


def detalle_aspirante(agencia_id: int, aspirante_id: int) -> DiagnosticoAspiranteDetalle:
    _exigir_habilitado(agencia_id)
    asp = _contexto_aspirante(agencia_id, aspirante_id)
    cfg_id = int(asp["chatbot_configuracion_id"])
    ev = db.obtener_evaluacion(agencia_id, aspirante_id, cfg_id)
    perfil_url = _resolver_perfil_url(asp, evaluacion=ev)
    evaluacion = None
    if ev:
        from diagnostico_reglas import PESO_MERCADO, PESO_REQUISITOS, PESO_TALENTO

        evaluacion = _evaluacion_out(
            ev,
            perfil_url=perfil_url,
            pesos={
                "requisitos": float(PESO_REQUISITOS),
                "mercado": float(PESO_MERCADO),
                "talento": float(PESO_TALENTO),
            },
        )
    return DiagnosticoAspiranteDetalle(
        id=asp["id"],
        nombre=asp.get("nombre"),
        telefono=asp.get("telefono"),
        mayor_edad=asp.get("mayor_edad"),
        disponibilidad_live=asp.get("disponibilidad_live"),
        usuario_plataforma=asp.get("usuario_plataforma"),
        chatbot_configuracion_id=cfg_id,
        plataforma_codigo=asp.get("plataforma_codigo"),
        plataforma_nombre=asp.get("plataforma_nombre"),
        perfil_url=perfil_url,
        estado_diagnostico="evaluado" if ev else "pendiente",
        evaluacion=evaluacion,
    )


def calcular_perfil_url(
    agencia_id: int, aspirante_id: int, payload: PerfilUrlIn
) -> PerfilUrlOut:
    """Recalcula perfil_url cuando el evaluador corrige el identificador."""
    _exigir_habilitado(agencia_id)
    asp = _contexto_aspirante(agencia_id, aspirante_id)
    cfg_id = int(asp["chatbot_configuracion_id"])
    ev = db.obtener_evaluacion(agencia_id, aspirante_id, cfg_id)
    perfil_url = _resolver_perfil_url(
        asp,
        identificador=payload.identificador,
        evaluacion=ev,
    )
    return PerfilUrlOut(aspirante_id=aspirante_id, perfil_url=perfil_url)


def analizar(
    agencia_id: int, aspirante_id: int, payload: AnalizarCabeceraIn
) -> AnalizarCabeceraOut:
    _exigir_habilitado(agencia_id)
    asp = _contexto_aspirante(agencia_id, aspirante_id)
    plataforma = str(asp["plataforma_codigo"]).strip().lower()
    parsed = analizar_cabecera(payload.cabecera_perfil, plataforma)
    perfil_url = _resolver_perfil_url(
        asp,
        identificador=parsed.get("identificador_detectado"),
    )
    return AnalizarCabeceraOut(
        aspirante_id=aspirante_id,
        plataforma_codigo=plataforma,
        plataforma_nombre=asp.get("plataforma_nombre"),
        identificador_detectado=parsed.get("identificador_detectado"),
        nombre_perfil=parsed.get("nombre_perfil"),
        metricas=parsed.get("metricas") or {},
        advertencias=parsed.get("advertencias") or [],
        campos_confirmacion=parsed.get("campos_confirmacion") or [],
        parser_especializado=bool(parsed.get("parser_especializado")),
        perfil_url=perfil_url,
        dato_secundario_opciones=parsed.get("dato_secundario_opciones"),
    )


def guardar_evaluacion(
    agencia_id: int,
    aspirante_id: int,
    payload: EvaluacionGuardarIn,
    *,
    evaluado_por: str,
) -> EvaluacionResultadoOut:
    _exigir_habilitado(agencia_id)
    asp = _contexto_aspirante(agencia_id, aspirante_id)
    # Plataforma solo desde la configuración del aspirante (nunca del body)
    plataforma = str(asp["plataforma_codigo"]).strip().lower()

    evaluado_por_txt = (evaluado_por or "").strip()
    if not evaluado_por_txt:
        raise HTTPException(
            status_code=400,
            detail="No se pudo determinar el usuario autenticado para la evaluación",
        )

    metricas = _normalizar_metricas(payload.metricas, plataforma)
    if plataforma == "bigo" and metricas.get("dato_secundario") is not None:
        tipo = metricas.get("dato_secundario_tipo")
        if tipo is None or str(tipo).strip() == "":
            raise HTTPException(
                status_code=400,
                detail="Debe clasificar el dato adicional de BIGO o marcarlo como Ignorar",
            )

    calc = calcular_diagnostico(
        plataforma_codigo=plataforma,
        mayor_edad=asp.get("mayor_edad"),
        disponibilidad_live=asp.get("disponibilidad_live"),
        metricas=metricas,
        talento_calificacion=payload.talento_calificacion,
        mercado_manual=payload.mercado_manual,
    )
    if calc.get("incompleto"):
        raise HTTPException(
            status_code=400,
            detail=(
                "Diagnóstico incompleto: faltan respuestas de requisitos, "
                "métricas necesarias o evaluación de talento"
            ),
        )

    ident = normalizar_identificador_perfil(payload.identificador_detectado)
    if not ident:
        ident = normalizar_identificador_perfil(asp.get("usuario_plataforma"))

    try:
        row = db.upsert_evaluacion(
            agencia_id=agencia_id,
            aspirante_id=aspirante_id,
            cabecera_perfil=payload.cabecera_perfil,
            identificador_detectado=ident,
            nombre_perfil=payload.nombre_perfil,
            metricas=metricas,
            talento_calificacion=payload.talento_calificacion,
            talento_observacion=payload.talento_observacion,
            puntaje_requisitos=calc.get("puntaje_requisitos"),
            puntaje_mercado=calc.get("puntaje_mercado"),
            puntaje_talento=calc.get("puntaje_talento"),
            puntaje_global=calc.get("puntaje_global"),
            resultado_requisitos=calc.get("resultado_requisitos"),
            resultado_mercado=calc.get("resultado_mercado"),
            resultado_talento=calc.get("resultado_talento"),
            resultado_global=calc.get("resultado_global"),
            motivo_bloqueo=calc.get("motivo_bloqueo"),
            evaluado_por=evaluado_por_txt,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    perfil_url = _resolver_perfil_url(asp, identificador=ident)
    return _evaluacion_out(row, perfil_url=perfil_url, pesos=calc.get("pesos"))
