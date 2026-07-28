"""
Helpers puros del Chatbot de captación (sin DB / Meta).
"""
from __future__ import annotations

import re
from typing import Optional


BTN_EDAD_SI = "CHATBOT_EDAD_SI"
BTN_EDAD_NO = "CHATBOT_EDAD_NO"
BTN_DISP_SI = "CHATBOT_DISPONIBILIDAD_SI"
BTN_DISP_NO = "CHATBOT_DISPONIBILIDAD_NO"
BTN_CONTINUAR = "CHATBOT_CONTINUAR"
BTN_PREGUNTAS = "CHATBOT_PREGUNTAS"
FAQ_PREFIX = "CHATBOT_FAQ_"


def enmascarar_telefono(telefono: Optional[str]) -> str:
    if not telefono:
        return ""
    t = str(telefono)
    if len(t) < 6:
        return "****"
    return f"{t[:3]}****{t[-2:]}"


def normalizar_telefono_chatbot(telefono: Optional[str]) -> str:
    """Solo dígitos. Misma forma para buscar, insertar y actualizar."""
    return re.sub(r"\D", "", str(telefono or ""))


def normalizar_codigo_agencia(subdominio: Optional[str], whatsapp_account_id: int) -> str:
    codigo = (subdominio or "").strip().lower()
    if codigo:
        return codigo
    return f"waba_{whatsapp_account_id}"


def nombre_agencia_desde_cuenta(
    business_name: Optional[str],
    subdominio: Optional[str],
    whatsapp_account_id: int,
) -> str:
    for candidato in (business_name, subdominio):
        if candidato and str(candidato).strip():
            return str(candidato).strip()[:150]
    return f"Agencia WhatsApp {whatsapp_account_id}"


def normalizar_usuario_plataforma(texto: Optional[str]) -> Optional[str]:
    if texto is None:
        return None
    valor = str(texto).strip()
    valor = re.sub(r"\s+", " ", valor)
    if valor.startswith("@"):
        valor = valor[1:].strip()
    valor = valor.lower()
    if not valor or len(valor) > 100:
        return None
    return valor


def interpretar_si_no(
    payload_id: Optional[str],
    texto: Optional[str],
    id_si: str,
    id_no: str,
) -> Optional[bool]:
    pid = (payload_id or "").strip()
    if pid == id_si:
        return True
    if pid == id_no:
        return False

    t = (texto or "").strip().lower()
    t = t.replace("í", "i")
    if t in ("si", "s", "yes", "y"):
        return True
    if t in ("no", "n"):
        return False
    return None


def truncar_titulo_boton(titulo: str, max_len: int = 20) -> str:
    """
    Normaliza y valida título de botón WhatsApp.
    Rechaza (> max_len); no trunca silenciosamente.
    """
    t = " ".join(str(titulo or "").split())
    if not t:
        raise ValueError("El título del botón no puede estar vacío")
    if len(t) > max_len:
        raise ValueError(
            f"El título del botón no puede superar {max_len} caracteres "
            f"(límite de WhatsApp). Actual: {len(t)}"
        )
    return t


def validar_titulo_boton(titulo: str, max_len: int = 20) -> str:
    return truncar_titulo_boton(titulo, max_len=max_len)
