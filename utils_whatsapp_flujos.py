"""
Estado temporal de flujos WhatsApp por tenant (tabla whatsapp_flujos).
Sustituye Redis / memoria para onboarding y pasos de conversación.
"""
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
import json

from dotenv import load_dotenv

from DataBase import get_connection_context

# Cargar .env del directorio del proyecto (no depende del cwd de uvicorn)
_ENV_FILE = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_FILE)
load_dotenv()  # por si el proceso arrancó desde otra ruta

# TTL onboarding (minutos de inactividad antes de reinicio)
TTL_ONBOARDING_USUARIO_TIKTOK = 5
TTL_ONBOARDING_CONFIRMACION = 3
TTL_ONBOARDING_ENCUESTA = 5


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _ttl_global_override() -> Optional[int]:
    """WHATSAPP_ONBOARDING_TTL_MINUTOS aplica a todos los pasos (útil en tutorial/dev)."""
    raw = os.getenv("WHATSAPP_ONBOARDING_TTL_MINUTOS")
    if raw is None or not str(raw).strip():
        return None
    return _env_int("WHATSAPP_ONBOARDING_TTL_MINUTOS", TTL_ONBOARDING_USUARIO_TIKTOK)


def ttl_onboarding_usuario() -> int:
    g = _ttl_global_override()
    if g is not None:
        return g
    return _env_int("WHATSAPP_TTL_USUARIO_TIKTOK", TTL_ONBOARDING_USUARIO_TIKTOK)


def ttl_onboarding_confirmacion() -> int:
    g = _ttl_global_override()
    if g is not None:
        return g
    return _env_int("WHATSAPP_TTL_CONFIRMACION", TTL_ONBOARDING_CONFIRMACION)


def ttl_onboarding_encuesta() -> int:
    g = _ttl_global_override()
    if g is not None:
        return g
    return _env_int("WHATSAPP_TTL_ENCUESTA", TTL_ONBOARDING_ENCUESTA)


def _valor_activo(valor: Any) -> bool:
    if valor is None:
        return False
    return str(valor).strip().lower() in ("1", "true", "yes", "on", "si", "sí")


def onboarding_sin_aviso_expiracion() -> bool:
    """
    Oculta avisos de sesión expirada si WHATSAPP_ONBOARDING_SIN_AVISO_EXPIRACION=1 en .env.
    """
    return _valor_activo(os.getenv("WHATSAPP_ONBOARDING_SIN_AVISO_EXPIRACION"))


def texto_aviso_sesion_expirada_onboarding(reinicio_corto: bool = False) -> str:
    """
    Texto de aviso por expiración, o cadena vacía si WHATSAPP_ONBOARDING_SIN_AVISO_EXPIRACION=1.
    reinicio_corto: mensaje al fallar confirmación SÍ/NO (sin repetir bienvenida completa).
    """
    if onboarding_sin_aviso_expiracion():
        return ""
    if reinicio_corto:
        return (
            "⏳ La sesión expiró por inactividad. "
            "Escribe nuevamente tu *usuario de TikTok* (sin @)."
        )
    return "⏳ Tu sesión expiró por inactividad. Empecemos de nuevo.\n\n"


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


__all__ = [
    "TTL_ONBOARDING_USUARIO_TIKTOK",
    "TTL_ONBOARDING_CONFIRMACION",
    "TTL_ONBOARDING_ENCUESTA",
    "obtener_flujo_whatsapp",
    "flujo_whatsapp_expirado",
    "actualizar_flujo_whatsapp",
    "eliminar_flujo_whatsapp",
    "limpiar_flujos_whatsapp_expirados",
    "onboarding_sin_aviso_expiracion",
    "texto_aviso_sesion_expirada_onboarding",
    "ttl_onboarding_usuario",
    "ttl_onboarding_confirmacion",
    "ttl_onboarding_encuesta",
]


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
