"""
Estado temporal de flujos WhatsApp por tenant (tabla whatsapp_flujos).
Sustituye Redis / memoria para onboarding y pasos de conversación.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
import json

from DataBase import get_connection_context

# TTL onboarding (minutos de inactividad antes de reinicio)
TTL_ONBOARDING_USUARIO_TIKTOK = 5
TTL_ONBOARDING_CONFIRMACION = 3
TTL_ONBOARDING_ENCUESTA = 5


def obtener_flujo_whatsapp(numero: str) -> Optional[Dict[str, Any]]:
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT numero, paso, aspirante_id, payload_json, expiracion
                FROM whatsapp_flujos
                WHERE numero = %s
                  AND (expiracion IS NULL OR expiracion > now())
                LIMIT 1
                """,
                (numero,),
            )
            row = cur.fetchone()
            if not row:
                return None

            payload = row[3]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = {}
            elif payload is None:
                payload = {}

            return {
                "numero": row[0],
                "paso": row[1],
                "aspirante_id": row[2],
                "payload_json": payload,
                "expiracion": row[4],
            }


def flujo_whatsapp_expirado(numero: str) -> bool:
    """True si hay fila para el número pero ya pasó expiracion."""
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM whatsapp_flujos
                WHERE numero = %s
                  AND expiracion IS NOT NULL
                  AND expiracion <= now()
                LIMIT 1
                """,
                (numero,),
            )
            return cur.fetchone() is not None


def actualizar_flujo_whatsapp(
    numero: str,
    paso: str,
    aspirante_id: Optional[int] = None,
    payload_json: Optional[Dict[str, Any]] = None,
    ttl_minutos: int = TTL_ONBOARDING_USUARIO_TIKTOK,
) -> None:
    expiracion = datetime.now() + timedelta(minutes=ttl_minutos)

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO whatsapp_flujos (
                    numero,
                    paso,
                    aspirante_id,
                    payload_json,
                    expiracion,
                    actualizado_en
                )
                VALUES (%s, %s, %s, %s::jsonb, %s, now())
                ON CONFLICT (numero) DO UPDATE
                SET
                    paso = EXCLUDED.paso,
                    aspirante_id = EXCLUDED.aspirante_id,
                    payload_json = EXCLUDED.payload_json,
                    expiracion = EXCLUDED.expiracion,
                    actualizado_en = now()
                """,
                (
                    numero,
                    paso,
                    aspirante_id,
                    json.dumps(payload_json or {}),
                    expiracion,
                ),
            )
            conn.commit()


def eliminar_flujo_whatsapp(numero: str) -> None:
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM whatsapp_flujos
                WHERE numero = %s
                """,
                (numero,),
            )
            conn.commit()


def limpiar_flujos_whatsapp_expirados() -> int:
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM whatsapp_flujos
                WHERE expiracion IS NOT NULL
                  AND expiracion <= now()
                RETURNING numero
                """
            )
            eliminados = cur.fetchall()
            conn.commit()
            return len(eliminados)
