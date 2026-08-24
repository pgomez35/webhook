"""
Persistencia de denylist y contadores de protección (schema chatbot).

Si las tablas aún no existen (migración pendiente), las funciones fallan
en abierto (False / no-op) y registran warning — el webhook no se cae.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from psycopg2 import errorcodes
from psycopg2.extras import RealDictCursor

from chatbot_captacion_logic import normalizar_telefono_chatbot
from chatbot_proteccion import (
    ANTI_BUCLE_M_SEG,
    ANTI_BUCLE_N,
    CAP_SALIENTES_N,
    CAP_SALIENTES_VENTANA_SEG,
    decidir_anti_bucle,
    normalizar_texto_anti_bucle,
)
from DataBase import get_connection_chatbot_context

logger = logging.getLogger("uvicorn.error")


def _tabla_ausente(exc: BaseException) -> bool:
    pgcode = getattr(exc, "pgcode", None)
    if pgcode == errorcodes.UNDEFINED_TABLE:
        return True
    msg = str(exc).lower()
    return "undefinedtable" in msg or "does not exist" in msg


def telefono_esta_bloqueado(agencia_id: int, telefono: str) -> bool:
    tel = normalizar_telefono_chatbot(telefono)
    if not tel or not agencia_id:
        return False
    try:
        with get_connection_chatbot_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM chatbot.telefonos_bloqueados
                    WHERE agencia_id = %s
                      AND telefono = %s
                      AND activo = TRUE
                    LIMIT 1
                    """,
                    (int(agencia_id), tel),
                )
                return cur.fetchone() is not None
    except Exception as exc:  # noqa: BLE001
        if _tabla_ausente(exc):
            logger.warning(
                "[CHATBOT_PROTECCION] tabla telefonos_bloqueados ausente; denylist omitida"
            )
            return False
        logger.exception(
            "[CHATBOT_PROTECCION] error consultando denylist agencia_id=%s",
            agencia_id,
        )
        return False


def listar_telefonos_bloqueados(
    agencia_id: int,
    *,
    solo_activos: bool = True,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    try:
        with get_connection_chatbot_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                sql = """
                    SELECT id, agencia_id, telefono, activo, motivo,
                           conversacion_id, aspirante_id, creado_por,
                           created_at, updated_at
                    FROM chatbot.telefonos_bloqueados
                    WHERE agencia_id = %s
                """
                params: list = [int(agencia_id)]
                if solo_activos:
                    sql += " AND activo = TRUE"
                sql += " ORDER BY updated_at DESC LIMIT %s"
                params.append(max(1, min(int(limit), 500)))
                cur.execute(sql, params)
                return [dict(r) for r in (cur.fetchall() or [])]
    except Exception as exc:  # noqa: BLE001
        if _tabla_ausente(exc):
            return []
        raise


def bloquear_telefono(
    agencia_id: int,
    telefono: str,
    *,
    motivo: Optional[str] = None,
    conversacion_id: Optional[int] = None,
    aspirante_id: Optional[int] = None,
    creado_por: Optional[int] = None,
) -> Dict[str, Any]:
    tel = normalizar_telefono_chatbot(telefono)
    if not tel:
        raise ValueError("Teléfono vacío o inválido")
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO chatbot.telefonos_bloqueados (
                    agencia_id, telefono, activo, motivo,
                    conversacion_id, aspirante_id, creado_por
                ) VALUES (%s, %s, TRUE, %s, %s, %s, %s)
                ON CONFLICT (agencia_id, telefono) DO UPDATE
                SET activo = TRUE,
                    motivo = COALESCE(EXCLUDED.motivo, chatbot.telefonos_bloqueados.motivo),
                    conversacion_id = COALESCE(
                        EXCLUDED.conversacion_id,
                        chatbot.telefonos_bloqueados.conversacion_id
                    ),
                    aspirante_id = COALESCE(
                        EXCLUDED.aspirante_id,
                        chatbot.telefonos_bloqueados.aspirante_id
                    ),
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id, agencia_id, telefono, activo, motivo,
                          conversacion_id, aspirante_id, creado_por,
                          created_at, updated_at
                """,
                (
                    int(agencia_id),
                    tel,
                    (motivo or "").strip() or None,
                    int(conversacion_id) if conversacion_id else None,
                    int(aspirante_id) if aspirante_id else None,
                    int(creado_por) if creado_por else None,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return dict(row)


def desbloquear_telefono(agencia_id: int, telefono: str) -> Optional[Dict[str, Any]]:
    tel = normalizar_telefono_chatbot(telefono)
    if not tel:
        raise ValueError("Teléfono vacío o inválido")
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE chatbot.telefonos_bloqueados
                SET activo = FALSE, updated_at = CURRENT_TIMESTAMP
                WHERE agencia_id = %s AND telefono = %s
                RETURNING id, agencia_id, telefono, activo, motivo,
                          conversacion_id, aspirante_id, creado_por,
                          created_at, updated_at
                """,
                (int(agencia_id), tel),
            )
            row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None


def registrar_inbound_y_evaluar_anti_bucle(
    agencia_id: int,
    telefono: str,
    texto: Optional[str],
    *,
    n: int = ANTI_BUCLE_N,
    m_seg: int = ANTI_BUCLE_M_SEG,
) -> Dict[str, Any]:
    """
    Actualiza el contador de inbound idéntico y indica si hay que silenciar.

    Retorno: {disparar, repeticiones, texto_norm, omitido}
    """
    tel = normalizar_telefono_chatbot(telefono)
    texto_norm = normalizar_texto_anti_bucle(texto)
    vacio = {"disparar": False, "repeticiones": 0, "texto_norm": texto_norm, "omitido": False}
    if not tel or not agencia_id:
        return vacio
    if not texto_norm:
        return vacio

    try:
        with get_connection_chatbot_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT texto_norm, repeticiones, ventana_inicio
                    FROM chatbot.proteccion_inbound_estado
                    WHERE agencia_id = %s AND telefono = %s
                    FOR UPDATE
                    """,
                    (int(agencia_id), tel),
                )
                prev = cur.fetchone()
                ahora = datetime.now(timezone.utc)
                if prev and prev.get("ventana_inicio"):
                    vinicio = prev["ventana_inicio"]
                    if vinicio.tzinfo is None:
                        vinicio = vinicio.replace(tzinfo=timezone.utc)
                    edad = (ahora - vinicio).total_seconds()
                else:
                    edad = float(m_seg) + 1.0

                disparar, nuevas, reiniciar = decidir_anti_bucle(
                    texto_norm=texto_norm,
                    texto_prev=str((prev or {}).get("texto_norm") or ""),
                    repeticiones_prev=int((prev or {}).get("repeticiones") or 0),
                    edad_ventana_seg=edad,
                    n=n,
                    m_seg=m_seg,
                )
                # reiniciar=True o sin prev → nueva ventana; si incrementamos, conservar inicio
                if prev is None or reiniciar or nuevas <= 1:
                    cur.execute(
                        """
                        INSERT INTO chatbot.proteccion_inbound_estado (
                            agencia_id, telefono, texto_norm, repeticiones,
                            ventana_inicio, updated_at
                        ) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        ON CONFLICT (agencia_id, telefono) DO UPDATE
                        SET texto_norm = EXCLUDED.texto_norm,
                            repeticiones = EXCLUDED.repeticiones,
                            ventana_inicio = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (int(agencia_id), tel, texto_norm, nuevas),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE chatbot.proteccion_inbound_estado
                        SET texto_norm = %s,
                            repeticiones = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE agencia_id = %s AND telefono = %s
                        """,
                        (texto_norm, nuevas, int(agencia_id), tel),
                    )
                conn.commit()
                return {
                    "disparar": bool(disparar),
                    "repeticiones": nuevas,
                    "texto_norm": texto_norm,
                    "omitido": False,
                    "n": n,
                    "m_seg": m_seg,
                }
    except Exception as exc:  # noqa: BLE001
        if _tabla_ausente(exc):
            logger.warning(
                "[CHATBOT_PROTECCION] tabla proteccion_inbound_estado ausente; anti-bucle omitido"
            )
            return {**vacio, "omitido": True}
        logger.exception(
            "[CHATBOT_PROTECCION] error anti-bucle agencia_id=%s", agencia_id
        )
        return {**vacio, "omitido": True}


def contar_salientes_bot_conversacion(
    conversacion_id: int,
    *,
    ventana_seg: int = CAP_SALIENTES_VENTANA_SEG,
) -> int:
    if not conversacion_id:
        return 0
    try:
        with get_connection_chatbot_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)::int
                    FROM chatbot.mensajes_conversacion
                    WHERE conversacion_id = %s
                      AND direccion = 'saliente'
                      AND remitente_tipo IN ('chatbot', 'asistente', 'sistema', 'ia')
                      AND created_at >= (CURRENT_TIMESTAMP - (%s || ' seconds')::interval)
                    """,
                    (int(conversacion_id), str(int(ventana_seg))),
                )
                row = cur.fetchone()
                return int(row[0] if row else 0)
    except Exception as exc:  # noqa: BLE001
        if _tabla_ausente(exc):
            return 0
        logger.exception(
            "[CHATBOT_PROTECCION] error contando salientes conversacion_id=%s",
            conversacion_id,
        )
        return 0


def defaults_proteccion() -> Dict[str, int]:
    return {
        "anti_bucle_n": ANTI_BUCLE_N,
        "anti_bucle_m_seg": ANTI_BUCLE_M_SEG,
        "cap_salientes_n": CAP_SALIENTES_N,
        "cap_salientes_ventana_seg": CAP_SALIENTES_VENTANA_SEG,
    }
