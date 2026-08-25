"""
Interceptor temporal: solicitudes de demo de la landing pública.

Mientras la agencia id=1 comparte el número +57 318 053 8911 con el WhatsApp
comercial de Talentum Manager, estos dos textos no deben entrar al flujo de
captación de aspirantes.

Quitar este módulo cuando el número comercial esté independizado.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

AGENCIA_INTERCEPT_DEMO_LANDING = 1

_TEXTO_ES = "hola, me interesa agendar una demo de talentum manager"
_TEXTO_EN = "hi, i'd like to schedule a talentum manager demo"

RESPUESTA_ES = (
    "¡Hola! Gracias por tu interés en Talentum Manager. "
    "Un asesor se comunicará contigo en breve para atender tu solicitud "
    "y agendar la demo."
)

RESPUESTA_EN = (
    "Hi! Thanks for your interest in Talentum Manager. "
    "An advisor will get in touch with you shortly to handle your request "
    "and schedule the demo."
)

_APOSTROFES = dict.fromkeys("’`´‘", "'")
_NOISE = re.compile(r"[\"«»“”]+")
_SPACES = re.compile(r"\s+")


def normalizar_texto_demo(texto: Optional[str]) -> str:
    valor = str(texto or "").strip().lower()
    valor = valor.translate(_APOSTROFES)
    valor = _NOISE.sub("", valor)
    valor = _SPACES.sub(" ", valor).strip(" .")
    return valor


def detectar_idioma_solicitud_demo(texto: Optional[str]) -> Optional[str]:
    normalizado = normalizar_texto_demo(texto)
    if not normalizado:
        return None
    if normalizado == _TEXTO_ES:
        return "es"
    sin_apostrofe = normalizado.replace("'", "")
    if normalizado == _TEXTO_EN or sin_apostrofe == _TEXTO_EN.replace("'", ""):
        return "en"
    return None


def intentar_respuesta_demo_landing(
    *,
    agencia_id: Optional[int],
    texto: Optional[str],
    tipo: Optional[str],
    token: str,
    phone_number_id: str,
    wa_id: str,
    enviar_texto: Callable[[str, str, str, str], None],
) -> bool:
    """
    Si coincide una solicitud de demo de la landing en agencia 1, envía la
    respuesta y retorna True (el mensaje no debe seguir a captación).
    """
    try:
        if int(agencia_id) != AGENCIA_INTERCEPT_DEMO_LANDING:
            return False
    except (TypeError, ValueError):
        return False

    tipo_norm = str(tipo or "text").strip().lower()
    if tipo_norm not in ("text", "texto", ""):
        return False

    idioma = detectar_idioma_solicitud_demo(texto)
    if not idioma:
        return False

    respuesta = RESPUESTA_ES if idioma == "es" else RESPUESTA_EN
    enviar_texto(token, phone_number_id, wa_id, respuesta)
    return True
