"""
Protección operativa del chatbot: denylist, anti-bucle de texto y cap de salientes.

Defaults ajustables por env (sin tocar FAQ/prompts/menú).
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Optional, Tuple


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# Mismo texto inbound ≥ N veces dentro de M segundos → no auto-responder
ANTI_BUCLE_N = _env_int("CHATBOT_ANTI_BUCLE_N", 3)
ANTI_BUCLE_M_SEG = _env_int("CHATBOT_ANTI_BUCLE_M_SEG", 60)

# Máx. salientes del bot por conversación en la ventana
CAP_SALIENTES_N = _env_int("CHATBOT_CAP_SALIENTES_N", 20)
CAP_SALIENTES_VENTANA_SEG = _env_int("CHATBOT_CAP_SALIENTES_VENTANA_SEG", 3600)

# Rate limit inbound por teléfono (cualquier texto)
INBOUND_RATE_N = _env_int("CHATBOT_INBOUND_RATE_N", 15)
INBOUND_RATE_M_SEG = _env_int("CHATBOT_INBOUND_RATE_M_SEG", 300)

# Circuit breaker por agencia: demasiados salientes del bot → pausa
CIRCUIT_SALIENTES_N = _env_int("CHATBOT_CIRCUIT_SALIENTES_N", 80)
CIRCUIT_SALIENTES_VENTANA_SEG = _env_int("CHATBOT_CIRCUIT_SALIENTES_VENTANA_SEG", 600)
CIRCUIT_PAUSA_SEG = _env_int("CHATBOT_CIRCUIT_PAUSA_SEG", 900)

# Tipos Meta / placeholders que no aportan texto útil → no auto-responder
TIPOS_SIN_AUTO_RESPUESTA = frozenset(
    {
        "unsupported",
        "reaction",
        "location",
        "contacts",
        "contact",
        "sticker",
    }
)


def normalizar_texto_anti_bucle(texto: Optional[str]) -> str:
    """Normaliza para comparar repeticiones (minúsculas, espacios colapsados)."""
    t = str(texto or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t


def hash_texto_norm(texto_norm: str) -> str:
    return hashlib.sha256(texto_norm.encode("utf-8")).hexdigest()[:32]


def decidir_anti_bucle(
    *,
    texto_norm: str,
    texto_prev: str,
    repeticiones_prev: int,
    edad_ventana_seg: float,
    n: int = ANTI_BUCLE_N,
    m_seg: int = ANTI_BUCLE_M_SEG,
) -> Tuple[bool, int, bool]:
    """
    Retorna (disparar_bloqueo, nuevas_repeticiones, reiniciar_ventana).

    - Si texto vacío → no dispara, reinicia a 0.
    - Si fuera de ventana o texto distinto → reinicia contador en 1.
    - Si mismo texto dentro de ventana → incrementa; dispara si >= n.
    """
    if not texto_norm:
        return False, 0, True

    if edad_ventana_seg > float(m_seg) or texto_prev != texto_norm:
        return False, 1, True

    nuevas = int(repeticiones_prev or 0) + 1
    return nuevas >= int(n), nuevas, False


def cap_salientes_excedido(count: int, limite: int = CAP_SALIENTES_N) -> bool:
    return int(count or 0) >= int(limite)


def decidir_rate_inbound(
    *,
    count_prev: int,
    edad_ventana_seg: float,
    n: int = INBOUND_RATE_N,
    m_seg: int = INBOUND_RATE_M_SEG,
) -> Tuple[bool, int, bool]:
    """
    Retorna (disparar, nuevo_count, reiniciar_ventana).
    Cuenta cualquier inbound; dispara al alcanzar n dentro de m_seg.
    """
    if edad_ventana_seg > float(m_seg):
        return False, 1, True
    nuevas = int(count_prev or 0) + 1
    return nuevas >= int(n), nuevas, False


def circuit_debe_abrir(count_salientes: int, limite: int = CIRCUIT_SALIENTES_N) -> bool:
    return int(count_salientes or 0) >= int(limite)


def es_entrada_sin_auto_respuesta(
    tipo: Optional[str],
    texto: Optional[str],
    payload_id: Optional[str] = None,
) -> bool:
    """
    True si el inbound no debe disparar auto-respuesta del chatbot.

    - Tipos Meta sin contenido útil (unsupported, reaction, sticker, …).
    - Texto vacío sin payload interactivo.
    - Placeholders tipo ``[unsupported]`` / ``[reaction]``.
    No bloquea image/video/document/audio (pueden ser evidencias).
    """
    if str(payload_id or "").strip():
        return False

    t = str(tipo or "").strip().lower()
    if t in TIPOS_SIN_AUTO_RESPUESTA:
        return True

    body = str(texto or "").strip()
    if not body:
        # text vacío u otros tipos sin cuerpo
        if t in ("", "text", "unknown", "other") or t in TIPOS_SIN_AUTO_RESPUESTA:
            return True
        return False

    if body.startswith("[") and body.endswith("]") and len(body) <= 24:
        inner = body[1:-1].strip().lower()
        if inner in TIPOS_SIN_AUTO_RESPUESTA:
            return True

    return False
