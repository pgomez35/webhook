"""Acceso a datos — Diagnóstico de aspirantes (Chatbot)."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from psycopg2.extras import RealDictCursor, Json

from DataBase import get_connection_chatbot_context

logger = logging.getLogger("uvicorn.error")


def agencia_diagnostico_habilitado(agencia_id: int) -> bool:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT COALESCE(diagnostico_habilitado, FALSE) AS diagnostico_habilitado
                FROM chatbot.agencias
                WHERE id = %s
                LIMIT 1
                """,
                (agencia_id,),
            )
            row = cur.fetchone()
            return bool(row and row.get("diagnostico_habilitado"))


def obtener_aspirante_con_plataforma(
    agencia_id: int, aspirante_id: int
) -> Optional[Dict[str, Any]]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    a.id,
                    a.agencia_id,
                    a.nombre,
                    a.telefono,
                    a.usuario_plataforma,
                    a.mayor_edad,
                    a.disponibilidad_live,
                    a.estado,
                    a.etapa_chatbot,
                    a.chatbot_configuracion_id,
                    a.plataforma_codigo AS aspirante_plataforma_codigo,
                    c.plataforma_codigo,
                    c.id AS config_id,
                    p.nombre AS plataforma_nombre,
                    p.perfil_url_template
                FROM chatbot.chatbot_aspirantes a
                LEFT JOIN chatbot.chatbot_configuracion c
                    ON c.id = a.chatbot_configuracion_id
                   AND c.agencia_id = a.agencia_id
                LEFT JOIN chatbot.plataformas p
                    ON p.codigo = c.plataforma_codigo
                WHERE a.id = %s
                  AND a.agencia_id = %s
                LIMIT 1
                """,
                (aspirante_id, agencia_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def listar_aspirantes_diagnostico(
    agencia_id: int,
    *,
    plataforma: Optional[str] = None,
    estado_diagnostico: Optional[str] = None,
    resultado_global: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> Tuple[int, List[Dict[str, Any]]]:
    where = ["a.agencia_id = %s"]
    params: List[Any] = [agencia_id]

    if plataforma:
        where.append("COALESCE(c.plataforma_codigo, a.plataforma_codigo) = %s")
        params.append(str(plataforma).strip().lower())

    if resultado_global:
        where.append("e.resultado_global = %s")
        params.append(str(resultado_global).strip().lower())

    if estado_diagnostico == "evaluado":
        where.append("e.id IS NOT NULL")
    elif estado_diagnostico == "pendiente":
        where.append("e.id IS NULL")

    where_sql = " AND ".join(where)
    offset = max(page - 1, 0) * page_size

    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT COUNT(*)::int AS total
                FROM chatbot.chatbot_aspirantes a
                LEFT JOIN chatbot.chatbot_configuracion c
                    ON c.id = a.chatbot_configuracion_id
                   AND c.agencia_id = a.agencia_id
                LEFT JOIN chatbot.evaluaciones_aspirantes e
                    ON e.aspirante_id = a.id
                   AND e.chatbot_configuracion_id = a.chatbot_configuracion_id
                   AND e.agencia_id = a.agencia_id
                WHERE {where_sql}
                """,
                params,
            )
            total = (cur.fetchone() or {}).get("total") or 0

            cur.execute(
                f"""
                SELECT
                    a.id,
                    a.nombre,
                    a.telefono,
                    a.usuario_plataforma,
                    a.estado AS estado_flujo,
                    a.chatbot_configuracion_id,
                    COALESCE(c.plataforma_codigo, a.plataforma_codigo) AS plataforma_codigo,
                    p.nombre AS plataforma_nombre,
                    CASE WHEN e.id IS NULL THEN 'pendiente' ELSE 'evaluado' END
                        AS estado_diagnostico,
                    e.resultado_global,
                    e.evaluado_at,
                    e.evaluado_por AS evaluado_por
                FROM chatbot.chatbot_aspirantes a
                LEFT JOIN chatbot.chatbot_configuracion c
                    ON c.id = a.chatbot_configuracion_id
                   AND c.agencia_id = a.agencia_id
                LEFT JOIN chatbot.plataformas p
                    ON p.codigo = COALESCE(c.plataforma_codigo, a.plataforma_codigo)
                LEFT JOIN chatbot.evaluaciones_aspirantes e
                    ON e.aspirante_id = a.id
                   AND e.chatbot_configuracion_id = a.chatbot_configuracion_id
                   AND e.agencia_id = a.agencia_id
                WHERE {where_sql}
                ORDER BY a.ultima_interaccion DESC NULLS LAST, a.id DESC
                LIMIT %s OFFSET %s
                """,
                params + [page_size, offset],
            )
            rows = []
            for r in cur.fetchall() or []:
                item = dict(r)
                item["evaluado_por_nombre"] = item.get("evaluado_por")
                rows.append(item)
            return total, rows


def obtener_evaluacion(
    agencia_id: int,
    aspirante_id: int,
    chatbot_configuracion_id: int,
) -> Optional[Dict[str, Any]]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT e.*
                FROM chatbot.evaluaciones_aspirantes e
                WHERE e.agencia_id = %s
                  AND e.aspirante_id = %s
                  AND e.chatbot_configuracion_id = %s
                LIMIT 1
                """,
                (agencia_id, aspirante_id, chatbot_configuracion_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            out = dict(row)
            met = out.get("metricas")
            if isinstance(met, str):
                try:
                    out["metricas"] = json.loads(met)
                except Exception:
                    out["metricas"] = {}
            elif met is None:
                out["metricas"] = {}
            out["evaluado_por_nombre"] = out.get("evaluado_por")
            return out


def upsert_evaluacion(
    *,
    agencia_id: int,
    aspirante_id: int,
    chatbot_configuracion_id: int,
    plataforma_codigo: str,
    cabecera_perfil: str,
    identificador_detectado: Optional[str],
    nombre_perfil: Optional[str],
    metricas: Dict[str, Any],
    talento_calificacion: str,
    talento_observacion: Optional[str],
    puntaje_requisitos: Optional[float],
    puntaje_mercado: Optional[float],
    puntaje_talento: Optional[float],
    puntaje_global: Optional[float],
    resultado_requisitos: Optional[str],
    resultado_mercado: Optional[str],
    resultado_talento: Optional[str],
    resultado_global: Optional[str],
    motivo_bloqueo: Optional[str],
    evaluado_por: str,
) -> Dict[str, Any]:
    evaluado_por_txt = (evaluado_por or "").strip()
    if not evaluado_por_txt:
        raise ValueError("evaluado_por es obligatorio")
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id
                FROM chatbot.evaluaciones_aspirantes
                WHERE aspirante_id = %s
                  AND chatbot_configuracion_id = %s
                LIMIT 1
                FOR UPDATE
                """,
                (aspirante_id, chatbot_configuracion_id),
            )
            existing = cur.fetchone()
            metricas_json = Json(metricas or {})

            if existing:
                cur.execute(
                    """
                    UPDATE chatbot.evaluaciones_aspirantes
                    SET
                        agencia_id = %s,
                        plataforma_codigo = %s,
                        cabecera_perfil = %s,
                        identificador_detectado = %s,
                        nombre_perfil = %s,
                        metricas = %s,
                        talento_calificacion = %s,
                        talento_observacion = %s,
                        puntaje_requisitos = %s,
                        puntaje_mercado = %s,
                        puntaje_talento = %s,
                        puntaje_global = %s,
                        resultado_requisitos = %s,
                        resultado_mercado = %s,
                        resultado_talento = %s,
                        resultado_global = %s,
                        motivo_bloqueo = %s,
                        evaluado_por = %s,
                        evaluado_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        agencia_id,
                        plataforma_codigo,
                        cabecera_perfil,
                        identificador_detectado,
                        nombre_perfil,
                        metricas_json,
                        talento_calificacion,
                        talento_observacion,
                        puntaje_requisitos,
                        puntaje_mercado,
                        puntaje_talento,
                        puntaje_global,
                        resultado_requisitos,
                        resultado_mercado,
                        resultado_talento,
                        resultado_global,
                        motivo_bloqueo,
                        evaluado_por_txt,
                        existing["id"],
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO chatbot.evaluaciones_aspirantes (
                        agencia_id,
                        aspirante_id,
                        chatbot_configuracion_id,
                        plataforma_codigo,
                        cabecera_perfil,
                        identificador_detectado,
                        nombre_perfil,
                        metricas,
                        talento_calificacion,
                        talento_observacion,
                        puntaje_requisitos,
                        puntaje_mercado,
                        puntaje_talento,
                        puntaje_global,
                        resultado_requisitos,
                        resultado_mercado,
                        resultado_talento,
                        resultado_global,
                        motivo_bloqueo,
                        evaluado_por,
                        evaluado_at,
                        created_at,
                        updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    RETURNING *
                    """,
                    (
                        agencia_id,
                        aspirante_id,
                        chatbot_configuracion_id,
                        plataforma_codigo,
                        cabecera_perfil,
                        identificador_detectado,
                        nombre_perfil,
                        metricas_json,
                        talento_calificacion,
                        talento_observacion,
                        puntaje_requisitos,
                        puntaje_mercado,
                        puntaje_talento,
                        puntaje_global,
                        resultado_requisitos,
                        resultado_mercado,
                        resultado_talento,
                        resultado_global,
                        motivo_bloqueo,
                        evaluado_por_txt,
                    ),
                )
            row = dict(cur.fetchone())
            met = row.get("metricas")
            if isinstance(met, str):
                try:
                    row["metricas"] = json.loads(met)
                except Exception:
                    row["metricas"] = {}
            elif met is None:
                row["metricas"] = {}
            row["evaluado_por_nombre"] = row.get("evaluado_por")
            logger.info(
                "[DIAGNOSTICO] upsert evaluacion id=%s aspirante_id=%s agencia_id=%s",
                row.get("id"),
                aspirante_id,
                agencia_id,
            )
            return row
