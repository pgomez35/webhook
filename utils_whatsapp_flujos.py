"""
Estado temporal de flujos WhatsApp por tenant (tabla whatsapp_flujos).
Sustituye Redis / memoria para onboarding y pasos de conversación.
"""
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
import json

from dotenv import load_dotenv

# Mismo patrón que main_webhook: .env local antes de leer os.getenv / importar DataBase
load_dotenv()

from DataBase import get_connection_context

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


_ENV_SIN_AVISO = "WHATSAPP_ONBOARDING_SIN_AVISO_EXPIRACION"


def onboarding_sin_aviso_expiracion() -> bool:
    """
    Oculta avisos de sesión expirada si:
    - WHATSAPP_ONBOARDING_SIN_AVISO_EXPIRACION=1 en el entorno (Render / .env vía main_webhook),
    - configuracion_agencia.clave = onboarding_sin_aviso_expiracion con valor activo (1/true/si).
    """
    # Lectura en tiempo de ejecución (Render inyecta en os.environ al arrancar el proceso)
    if _valor_activo(os.environ.get(_ENV_SIN_AVISO) or os.getenv(_ENV_SIN_AVISO)):
        return True
    try:
        from main_configuracion import get_config

        return _valor_activo(get_config("onboarding_sin_aviso_expiracion"))
    except Exception:
        return False


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
    "actualizar_flujo",
    "obtener_flujo",
    "eliminar_flujo",
    "guardar_aspirante_temp",
    "obtener_aspirante_temp",
    "limpiar_aspirante_temp",
    "asegurar_flujo_payload",
    "guardar_nombre_en_flujo",
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


# ============================
# API compatible (antes Redis / memoria)
# ============================


def _ttl_para_paso(paso: Any) -> int:
    g = _ttl_global_override()
    if g is not None:
        return g
    p = str(paso or "").strip().lower()
    if p == "confirmando_nickname":
        return ttl_onboarding_confirmacion()
    if p == "esperando_inicio_encuesta":
        return ttl_onboarding_encuesta()
    if p in (
        "encuesta_whatsapp_esperando_respuesta",
        "encuesta_whatsapp_esperando_inicio",
        "encuesta_web_esperando_inicio",
        "encuesta_whatsapp_presentacion",
        "esperando_inicio_encuesta",
    ):
        return ttl_onboarding_encuesta()
    if p in (
        "esperando_usuario_tiktok",
        "esperando_input_link_tiktok",
        "esperando_link_tiktok_live",
    ):
        return ttl_onboarding_usuario()
    return _env_int("WHATSAPP_FLUJO_TTL_MINUTOS", 30)


def _paso_a_str(paso: Any) -> str:
    return str(paso)


def _paso_desde_str(paso: Optional[str]) -> Any:
    if paso is None:
        return None
    if str(paso).isdigit():
        return int(paso)
    return paso


def _payload_aspirante_serializable(aspirante_data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(aspirante_data, dict):
        return {}
    out: Dict[str, Any] = {}
    for key, valor in aspirante_data.items():
        if key == "id":
            continue
        if isinstance(valor, (str, int, float, bool)) or valor is None:
            out[key] = valor
    return out


def _aspirante_desde_fila(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    payload = row.get("payload_json")
    if not isinstance(payload, dict):
        payload = {}
    aspirante_id = row.get("aspirante_id") or payload.get("id")
    if not aspirante_id:
        return None
    out = dict(payload)
    out["id"] = aspirante_id
    return out


def actualizar_flujo(numero: str, paso: Any, ttl_segundos: Optional[int] = None) -> None:
    """Paso de conversación en whatsapp_flujos (sustituye Redis flow: y memoria)."""
    ttl_min = max(1, (ttl_segundos // 60) if ttl_segundos else _ttl_para_paso(paso))
    existing = obtener_flujo_whatsapp(numero)
    payload = (existing or {}).get("payload_json") if existing else {}
    if not isinstance(payload, dict):
        payload = {}
    aspirante_id = (existing or {}).get("aspirante_id") if existing else None
    actualizar_flujo_whatsapp(
        numero,
        _paso_a_str(paso),
        aspirante_id=aspirante_id,
        payload_json=payload,
        ttl_minutos=ttl_min,
    )


def obtener_flujo(numero: str) -> Any:
    if flujo_whatsapp_expirado(numero):
        eliminar_flujo_whatsapp(numero)
        return None
    row = obtener_flujo_whatsapp(numero)
    if not row:
        return None
    return _paso_desde_str(row.get("paso"))


def eliminar_flujo(numero: str) -> None:
    eliminar_flujo_whatsapp(numero)


def guardar_aspirante_temp(numero: str, aspirante_data: dict, ttl_segundos: int = 900) -> None:
    """Datos del aspirante en payload_json (sustituye Redis temp:)."""
    data = aspirante_data if isinstance(aspirante_data, dict) else {}
    aspirante_id = data.get("id")
    payload = _payload_aspirante_serializable(data)
    existing = obtener_flujo_whatsapp(numero)
    paso = (existing or {}).get("paso") or "confirmando_nickname"
    ttl_min = max(1, ttl_segundos // 60)
    actualizar_flujo_whatsapp(
        numero,
        paso,
        aspirante_id=aspirante_id,
        payload_json=payload,
        ttl_minutos=ttl_min,
    )


def obtener_aspirante_temp(numero: str) -> Optional[Dict[str, Any]]:
    row = obtener_flujo_whatsapp(numero)
    if not row:
        return None
    return _aspirante_desde_fila(row)


def limpiar_aspirante_temp(numero: str) -> None:
    row = obtener_flujo_whatsapp(numero)
    if not row:
        return
    paso = row.get("paso") or "esperando_usuario_tiktok"
    actualizar_flujo_whatsapp(
        numero,
        paso,
        aspirante_id=None,
        payload_json={},
        ttl_minutos=_ttl_para_paso(paso),
    )


def asegurar_flujo_payload(numero: str) -> Dict[str, Any]:
    """Asegura dict payload en BD (antes asegurar_flujo en memoria)."""
    row = obtener_flujo_whatsapp(numero)
    if row and isinstance(row.get("payload_json"), dict):
        return row["payload_json"]
    return {}


def guardar_nombre_en_flujo(numero: str, nombre: str, paso: Any = "info") -> None:
    payload = asegurar_flujo_payload(numero)
    payload["nombre"] = nombre
    actualizar_flujo_whatsapp(
        numero,
        _paso_a_str(paso),
        aspirante_id=None,
        payload_json=payload,
        ttl_minutos=_ttl_para_paso(paso),
    )
