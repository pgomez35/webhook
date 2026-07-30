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

# Etapas de chatbot.chatbot_aspirantes.etapa_chatbot
# Deben coincidir exactamente con chk_chatbot_aspirante_etapa
ETAPA_INICIO = "inicio"
ETAPA_PLATAFORMA = "plataforma"
ETAPA_USUARIO = "usuario"
ETAPA_MAYOR_EDAD = "mayor_edad"
ETAPA_DISPONIBILIDAD = "disponibilidad"
ETAPA_RESULTADO = "resultado"
ETAPA_PREGUNTAS_FRECUENTES = "preguntas_frecuentes"
ETAPA_ASESOR = "asesor"
ETAPA_FINALIZADO = "finalizado"

# Prefijo seguro para botones/lista de selección de configuración
CONFIG_PAYLOAD_PREFIX = "chatbot_config:"

# WhatsApp: máx. 3 reply buttons; si hay más opciones → lista interactiva
MAX_REPLY_BUTTONS = 3

# Etapas sin bot automático (solo trazabilidad / chat humano)
ETAPAS_SIN_AUTO_RESPUESTA = frozenset(
    {
        ETAPA_ASESOR,
        ETAPA_FINALIZADO,
    }
)


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
    """
    Compatibilidad: normalización genérica estilo TikTok (strip, quitar un @, lower).
    Preferir normalizar_identificador_plataforma cuando se conoce plataforma_codigo.
    """
    return normalizar_identificador_plataforma("tiktok", texto)


def normalizar_identificador_plataforma(
    plataforma_codigo: Optional[str],
    valor: Optional[str],
) -> Optional[str]:
    """
    Normaliza el identificador del usuario según la plataforma.

    - tiktok: strip, acepta uno o varios @ iniciales, los elimina, minúsculas
    - bigo: strip, conserva el ID como texto (sin agregar @)
    - otras: solo strip()
    No consulta chatbot.plataformas: las reglas viven en código.
    """
    if valor is None:
        return None
    codigo = (plataforma_codigo or "").strip().lower()
    texto = str(valor)

    if codigo == "tiktok":
        texto = texto.strip()
        texto = re.sub(r"^@+", "", texto).strip()
        texto = texto.lower()
    elif codigo == "bigo":
        texto = texto.strip()
    else:
        texto = texto.strip()

    if not texto or len(texto) > 100:
        return None
    return texto


def payload_seleccion_config(configuracion_id: int) -> str:
    """Identificador interno seguro para botones/lista de WhatsApp."""
    return f"{CONFIG_PAYLOAD_PREFIX}{int(configuracion_id)}"


def extraer_id_config_desde_payload(payload_id: Optional[str]) -> Optional[int]:
    """Extrae chatbot_configuracion.id desde payload tipo chatbot_config:{id}."""
    raw = (payload_id or "").strip()
    if not raw.startswith(CONFIG_PAYLOAD_PREFIX):
        return None
    resto = raw[len(CONFIG_PAYLOAD_PREFIX) :].strip()
    if not resto.isdigit():
        return None
    try:
        return int(resto)
    except (TypeError, ValueError):
        return None


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
