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
    estado: Optional[str] = None,
    estado_diagnostico: Optional[str] = None,
    resultado_global: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[int, List[Dict[str, Any]], List[Dict[str, str]]]:
    """
    Listado ligero paginado (una consulta con COUNT OVER).
    No incluye cabecera_perfil, metricas ni observaciones.
    """
    import time

    t0 = time.perf_counter()
    where = ["a.agencia_id = %s"]
    params: List[Any] = [agencia_id]

    if plataforma:
        where.append("COALESCE(c.plataforma_codigo, a.plataforma_codigo) = %s")
        params.append(str(plataforma).strip().lower())

    if estado:
        where.append("a.estado = %s")
        params.append(str(estado).strip().lower())

    if resultado_global:
        where.append("e.resultado_global = %s")
        params.append(str(resultado_global).strip().lower())

    estado_diag = (estado_diagnostico or "").strip().lower()
    if estado_diag == "evaluado":
        where.append("e.evaluado_at IS NOT NULL")
    elif estado_diag == "pendiente":
        where.append("e.evaluado_at IS NULL")

    where_sql = " AND ".join(where)
    page_size = max(1, min(int(page_size), 100))
    offset = max(page - 1, 0) * page_size

    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT DISTINCT
                    c.plataforma_codigo AS codigo,
                    COALESCE(p.nombre, c.plataforma_codigo) AS nombre
                FROM chatbot.chatbot_configuracion c
                LEFT JOIN chatbot.plataformas p ON p.codigo = c.plataforma_codigo
                WHERE c.agencia_id = %s
                  AND c.plataforma_codigo IS NOT NULL
                ORDER BY 2 ASC
                """,
                (agencia_id,),
            )
            plataformas = [
                {"codigo": r["codigo"], "nombre": r["nombre"]}
                for r in (cur.fetchall() or [])
                if r.get("codigo")
            ]

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
                    CASE
                        WHEN e.evaluado_at IS NOT NULL THEN 'evaluado'
                        ELSE 'pendiente'
                    END AS estado_diagnostico,
                    e.resultado_global,
                    e.evaluado_at,
                    e.evaluado_por AS evaluado_por,
                    COUNT(*) OVER()::int AS _total
                FROM chatbot.chatbot_aspirantes a
                LEFT JOIN chatbot.chatbot_configuracion c
                    ON c.id = a.chatbot_configuracion_id
                   AND c.agencia_id = a.agencia_id
                LEFT JOIN chatbot.plataformas p
                    ON p.codigo = COALESCE(c.plataforma_codigo, a.plataforma_codigo)
                LEFT JOIN chatbot.evaluaciones_aspirantes e
                    ON e.aspirante_id = a.id
                   AND e.agencia_id = a.agencia_id
                   AND e.chatbot_configuracion_id = a.chatbot_configuracion_id
                WHERE {where_sql}
                ORDER BY a.ultima_interaccion DESC NULLS LAST, a.id DESC
                LIMIT %s OFFSET %s
                """,
                params + [page_size, offset],
            )
            fetched = [dict(r) for r in (cur.fetchall() or [])]
            total = int(fetched[0]["_total"]) if fetched else 0
            rows = []
            for r in fetched:
                r.pop("_total", None)
                r["evaluado_por_nombre"] = r.get("evaluado_por")
                rows.append(r)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "[DIAGNOSTICO-LIST] agencia_id=%s page=%s size=%s total=%s ms=%.1f",
                agencia_id,
                page,
                page_size,
                total,
                elapsed_ms,
            )
            return total, rows, plataformas


def obtener_detalle_diagnostico(
    agencia_id: int, aspirante_id: int
) -> Optional[Dict[str, Any]]:
    """
    Una sola consulta: aspirante + configuración + plataforma + evaluación ligera.
    """
    import time

    t0 = time.perf_counter()
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
                    a.cumple_requisitos,
                    a.chatbot_configuracion_id,
                    c.id AS config_id,
                    c.plataforma_codigo,
                    p.nombre AS plataforma_nombre,
                    p.perfil_url_template,
                    e.id AS evaluacion_id,
                    e.plataforma_codigo AS evaluacion_plataforma_codigo,
                    e.cabecera_perfil,
                    e.identificador_detectado,
                    e.nombre_perfil,
                    e.metricas,
                    e.talento_calificacion,
                    e.talento_observacion,
                    e.puntaje_requisitos,
                    e.puntaje_mercado,
                    e.puntaje_talento,
                    e.puntaje_global,
                    e.resultado_requisitos,
                    e.resultado_mercado,
                    e.resultado_talento,
                    e.resultado_global,
                    e.motivo_bloqueo,
                    e.evaluado_por,
                    e.evaluado_at,
                    e.created_at AS evaluacion_created_at,
                    e.updated_at AS evaluacion_updated_at,
                    e.chatbot_configuracion_id AS evaluacion_config_id
                FROM chatbot.chatbot_aspirantes a
                LEFT JOIN chatbot.chatbot_configuracion c
                    ON c.id = a.chatbot_configuracion_id
                   AND c.agencia_id = a.agencia_id
                LEFT JOIN chatbot.plataformas p
                    ON p.codigo = c.plataforma_codigo
                LEFT JOIN chatbot.evaluaciones_aspirantes e
                    ON e.aspirante_id = a.id
                   AND e.agencia_id = a.agencia_id
                   AND e.chatbot_configuracion_id = a.chatbot_configuracion_id
                WHERE a.id = %s
                  AND a.agencia_id = %s
                LIMIT 1
                """,
                (aspirante_id, agencia_id),
            )
            row = cur.fetchone()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "[DIAGNOSTICO-DETALLE] agencia_id=%s aspirante_id=%s found=%s ms=%.1f",
                agencia_id,
                aspirante_id,
                bool(row),
                elapsed_ms,
            )
            if not row:
                return None
            out = dict(row)
            met = out.get("metricas")
            if isinstance(met, str):
                try:
                    out["metricas"] = json.loads(met)
                except Exception:
                    out["metricas"] = {}
            elif met is None and out.get("evaluacion_id"):
                out["metricas"] = {}
            return out


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
    """
    Inserta o actualiza evaluación (una por aspirante_id + chatbot_configuracion_id).
    plataforma_codigo se resuelve desde la configuración del aspirante (no del frontend).
    Commit/rollback los gestiona get_connection_chatbot_context.
    """
    evaluado_por_txt = (evaluado_por or "").strip()
    if not evaluado_por_txt:
        raise ValueError("evaluado_por es obligatorio")

    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Aspirante + configuración de la agencia autenticada
            cur.execute(
                """
                SELECT
                    a.id AS aspirante_id,
                    a.agencia_id,
                    a.chatbot_configuracion_id,
                    c.id AS config_id,
                    c.plataforma_codigo
                FROM chatbot.chatbot_aspirantes a
                INNER JOIN chatbot.chatbot_configuracion c
                    ON c.id = a.chatbot_configuracion_id
                   AND c.agencia_id = a.agencia_id
                WHERE a.id = %s
                  AND a.agencia_id = %s
                LIMIT 1
                FOR UPDATE OF a
                """,
                (aspirante_id, agencia_id),
            )
            ctx = cur.fetchone()
            if not ctx:
                raise ValueError(
                    "Aspirante no encontrado o sin configuración válida para la agencia"
                )

            cfg_id = ctx.get("chatbot_configuracion_id") or ctx.get("config_id")
            plataforma_codigo = str(ctx.get("plataforma_codigo") or "").strip().lower()
            if not cfg_id:
                raise ValueError(
                    "El aspirante no tiene configuración de chatbot asociada"
                )
            if not plataforma_codigo:
                raise ValueError(
                    "No se pudo determinar plataforma_codigo desde la configuración"
                )

            metricas_json = Json(metricas or {})
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
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT (aspirante_id, chatbot_configuracion_id) DO UPDATE SET
                    agencia_id = EXCLUDED.agencia_id,
                    plataforma_codigo = EXCLUDED.plataforma_codigo,
                    cabecera_perfil = EXCLUDED.cabecera_perfil,
                    identificador_detectado = EXCLUDED.identificador_detectado,
                    nombre_perfil = EXCLUDED.nombre_perfil,
                    metricas = EXCLUDED.metricas,
                    talento_calificacion = EXCLUDED.talento_calificacion,
                    talento_observacion = EXCLUDED.talento_observacion,
                    puntaje_requisitos = EXCLUDED.puntaje_requisitos,
                    puntaje_mercado = EXCLUDED.puntaje_mercado,
                    puntaje_talento = EXCLUDED.puntaje_talento,
                    puntaje_global = EXCLUDED.puntaje_global,
                    resultado_requisitos = EXCLUDED.resultado_requisitos,
                    resultado_mercado = EXCLUDED.resultado_mercado,
                    resultado_talento = EXCLUDED.resultado_talento,
                    resultado_global = EXCLUDED.resultado_global,
                    motivo_bloqueo = EXCLUDED.motivo_bloqueo,
                    evaluado_por = EXCLUDED.evaluado_por,
                    evaluado_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING *
                """,
                (
                    agencia_id,
                    aspirante_id,
                    int(cfg_id),
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
                "[DIAGNOSTICO] upsert evaluacion id=%s aspirante_id=%s "
                "agencia_id=%s plataforma_codigo=%s",
                row.get("id"),
                aspirante_id,
                agencia_id,
                plataforma_codigo,
            )
            return row
