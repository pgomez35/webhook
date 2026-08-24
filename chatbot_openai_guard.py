"""
Guardas operativas de OpenAI: semáforo de concurrencia + presupuesto diario.

Fail-open si la tabla de uso no existe (migración pendiente).
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterator, Optional, Tuple

logger = logging.getLogger("uvicorn.error")


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


OPENAI_CONCURRENCY = max(1, _env_int("CHATBOT_OPENAI_CONCURRENCY", 3))
OPENAI_LLAMADAS_DIA = max(1, _env_int("CHATBOT_OPENAI_LLAMADAS_DIA", 500))
OPENAI_TOKENS_DIA = max(0, _env_int("CHATBOT_OPENAI_TOKENS_DIA", 800_000))
OPENAI_SLOT_TIMEOUT_SEG = max(1, _env_int("CHATBOT_OPENAI_SLOT_TIMEOUT_SEG", 30))

_sem = threading.BoundedSemaphore(OPENAI_CONCURRENCY)
_sem_init_lock = threading.Lock()


class PresupuestoAgotado(Exception):
    """La agencia superó el tope diario de OpenAI."""


class ConcurrenciaTimeout(Exception):
    """No hubo slot libre de OpenAI a tiempo."""


def _fecha_utc() -> date:
    return datetime.now(timezone.utc).date()


def _tabla_ausente(exc: BaseException) -> bool:
    from psycopg2 import errorcodes

    pgcode = getattr(exc, "pgcode", None)
    if pgcode == errorcodes.UNDEFINED_TABLE:
        return True
    msg = str(exc).lower()
    return "undefinedtable" in msg or "does not exist" in msg


def obtener_uso_diario(agencia_id: int) -> Dict[str, int]:
    vacio = {"llamadas": 0, "tokens_entrada": 0, "tokens_salida": 0}
    if not agencia_id:
        return vacio
    try:
        from DataBase import get_connection_chatbot_context

        with get_connection_chatbot_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT llamadas, tokens_entrada, tokens_salida
                    FROM chatbot.openai_uso_diario
                    WHERE agencia_id = %s AND fecha = %s
                    LIMIT 1
                    """,
                    (int(agencia_id), _fecha_utc()),
                )
                row = cur.fetchone()
                if not row:
                    return vacio
                return {
                    "llamadas": int(row[0] or 0),
                    "tokens_entrada": int(row[1] or 0),
                    "tokens_salida": int(row[2] or 0),
                }
    except Exception as exc:  # noqa: BLE001
        if _tabla_ausente(exc):
            logger.warning(
                "[CHATBOT_OPENAI_GUARD] tabla openai_uso_diario ausente; "
                "presupuesto omitido"
            )
            return vacio
        logger.exception(
            "[CHATBOT_OPENAI_GUARD] error leyendo uso agencia_id=%s", agencia_id
        )
        return vacio


def puede_llamar_openai(agencia_id: int) -> Tuple[bool, Dict[str, Any]]:
    """
    Retorna (ok, info). ok=False → no iniciar llamada (presupuesto).
    """
    uso = obtener_uso_diario(agencia_id)
    llamadas = uso["llamadas"]
    tokens = uso["tokens_entrada"] + uso["tokens_salida"]
    info = {
        "llamadas": llamadas,
        "tokens": tokens,
        "limite_llamadas": OPENAI_LLAMADAS_DIA,
        "limite_tokens": OPENAI_TOKENS_DIA,
    }
    if llamadas >= OPENAI_LLAMADAS_DIA:
        info["motivo"] = "limite_llamadas"
        return False, info
    if OPENAI_TOKENS_DIA > 0 and tokens >= OPENAI_TOKENS_DIA:
        info["motivo"] = "limite_tokens"
        return False, info
    return True, info


def registrar_uso_openai(
    agencia_id: int,
    *,
    llamadas: int = 1,
    tokens_entrada: int = 0,
    tokens_salida: int = 0,
) -> None:
    if not agencia_id:
        return
    try:
        from DataBase import get_connection_chatbot_context

        with get_connection_chatbot_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chatbot.openai_uso_diario (
                        agencia_id, fecha, llamadas, tokens_entrada, tokens_salida
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (agencia_id, fecha) DO UPDATE
                    SET llamadas = chatbot.openai_uso_diario.llamadas + EXCLUDED.llamadas,
                        tokens_entrada = chatbot.openai_uso_diario.tokens_entrada
                            + EXCLUDED.tokens_entrada,
                        tokens_salida = chatbot.openai_uso_diario.tokens_salida
                            + EXCLUDED.tokens_salida,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        int(agencia_id),
                        _fecha_utc(),
                        max(0, int(llamadas)),
                        max(0, int(tokens_entrada or 0)),
                        max(0, int(tokens_salida or 0)),
                    ),
                )
                conn.commit()
    except Exception as exc:  # noqa: BLE001
        if _tabla_ausente(exc):
            return
        logger.exception(
            "[CHATBOT_OPENAI_GUARD] error registrando uso agencia_id=%s", agencia_id
        )


def _adquirir_slot_blocking(timeout_seg: float) -> bool:
    return bool(_sem.acquire(timeout=float(timeout_seg)))


def _liberar_slot() -> None:
    try:
        _sem.release()
    except ValueError:
        # release de más — no debería ocurrir
        logger.warning("[CHATBOT_OPENAI_GUARD] release de semáforo sin acquire")


@asynccontextmanager
async def llamada_openai(agencia_id: int):
    """
    Reserva presupuesto + slot de concurrencia para una llamada OpenAI (async).

    Registra 1 llamada al entrar. Los tokens se registran aparte con
    ``registrar_uso_openai(..., llamadas=0, tokens_entrada=..., tokens_salida=...)``.
    """
    ok, info = puede_llamar_openai(int(agencia_id))
    if not ok:
        logger.warning(
            "[CHATBOT_OPENAI_GUARD] presupuesto agotado agencia_id=%s "
            "llamadas=%s/%s tokens=%s/%s motivo=%s",
            agencia_id,
            info.get("llamadas"),
            info.get("limite_llamadas"),
            info.get("tokens"),
            info.get("limite_tokens"),
            info.get("motivo"),
        )
        raise PresupuestoAgotado(info.get("motivo") or "presupuesto")

    got = await asyncio.to_thread(_adquirir_slot_blocking, OPENAI_SLOT_TIMEOUT_SEG)
    if not got:
        logger.warning(
            "[CHATBOT_OPENAI_GUARD] concurrencia timeout agencia_id=%s "
            "limite=%s timeout_s=%s",
            agencia_id,
            OPENAI_CONCURRENCY,
            OPENAI_SLOT_TIMEOUT_SEG,
        )
        raise ConcurrenciaTimeout("openai_concurrencia")

    registrar_uso_openai(int(agencia_id), llamadas=1)
    try:
        yield info
    finally:
        _liberar_slot()


@contextmanager
def llamada_openai_sync(agencia_id: int) -> Iterator[Dict[str, Any]]:
    """Versión sync (informativo / carga)."""
    ok, info = puede_llamar_openai(int(agencia_id))
    if not ok:
        logger.warning(
            "[CHATBOT_OPENAI_GUARD] presupuesto agotado (sync) agencia_id=%s motivo=%s",
            agencia_id,
            info.get("motivo"),
        )
        raise PresupuestoAgotado(info.get("motivo") or "presupuesto")

    if not _adquirir_slot_blocking(OPENAI_SLOT_TIMEOUT_SEG):
        raise ConcurrenciaTimeout("openai_concurrencia")

    registrar_uso_openai(int(agencia_id), llamadas=1)
    try:
        yield info
    finally:
        _liberar_slot()


def defaults_openai_guard() -> Dict[str, int]:
    return {
        "openai_concurrency": OPENAI_CONCURRENCY,
        "openai_llamadas_dia": OPENAI_LLAMADAS_DIA,
        "openai_tokens_dia": OPENAI_TOKENS_DIA,
        "openai_slot_timeout_seg": OPENAI_SLOT_TIMEOUT_SEG,
    }
