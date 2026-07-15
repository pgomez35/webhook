"""
Encuesta inicial del aspirante por WhatsApp (fase 1: solo presentación).
"""
from __future__ import annotations

import re
import traceback
from typing import Any, Dict, List, Optional, Tuple

from DataBase import obtener_configuracion_agencia
from encuesta_inicial_service import obtener_encuesta_inicial_normalizada
from encuesta_portal_utils import ENCUESTA_INICIAL_ID
from enviar_msg_wp import enviar_mensaje_interactivo, enviar_mensaje_texto_simple
from tenant import current_phone_id, current_token

MENSAJE_INICIO_ENCUESTA_WHATSAPP = (
    "✨ ¡Perfecto, {nombre}!\n\n"
    "Realizaremos tu evaluación inicial directamente por WhatsApp.\n\n"
    "A continuación recibirás unas preguntas breves. "
    "Selecciona una opción en cada una."
)

SUFIJO_RESPUESTA_TEXTO = "\n\nResponde escribiendo tu respuesta."

MAX_BUTTONS = 3
MAX_BUTTON_TITLE = 20
MAX_LIST_ROWS = 10
MAX_LIST_ROW_TITLE = 24
MAX_LIST_ROW_DESCRIPTION = 72
MAX_BODY_TEXT = 1024

_RE_VALOR_JS = re.compile(r"\$\{valor(?:\s*\|\|\s*[^}]*)?\}", re.IGNORECASE)
_RE_NOMBRE_BRACE = re.compile(r"\{nombre\}", re.IGNORECASE)


def _nombre_aspirante(aspirante: Optional[Dict[str, Any]]) -> str:
    if not aspirante:
        return ""
    for key in ("nombre", "nombre_real", "nickname", "usuario_tiktok", "usuario"):
        val = aspirante.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return ""


def limpiar_texto_pregunta_whatsapp(texto: str, aspirante: Optional[Dict[str, Any]] = None) -> str:
    if not texto:
        return ""
    nombre = _nombre_aspirante(aspirante)
    out = texto
    if nombre:
        out = _RE_NOMBRE_BRACE.sub(nombre, out)
        out = _RE_VALOR_JS.sub(nombre, out)
    else:
        out = _RE_NOMBRE_BRACE.sub("", out)
        out = _RE_VALOR_JS.sub("", out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.!?])", r"\1", out)
    return out.strip()


def limpiar_label_opcion_whatsapp(label: str, max_len: int = MAX_LIST_ROW_TITLE) -> str:
    text = " ".join(str(label or "").split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def construir_id_opcion_whatsapp(encuesta_id: int, variable_id: int, valor_id: int) -> str:
    return f"enc_{encuesta_id}_preg_{variable_id}_opc_{valor_id}"


def _titulo_cabe_en_boton(label: str) -> bool:
    return len(limpiar_label_opcion_whatsapp(label, MAX_BUTTON_TITLE)) <= MAX_BUTTON_TITLE


def _credenciales_whatsapp() -> Tuple[Optional[str], Optional[str]]:
    try:
        return current_token.get(), current_phone_id.get()
    except LookupError:
        return None, None


def obtener_encuesta_inicial_para_whatsapp(
    encuesta_id: int = ENCUESTA_INICIAL_ID,
) -> Dict[str, Any]:
    return obtener_encuesta_inicial_normalizada(encuesta_id)


def normalizar_encuesta_para_whatsapp(
    encuesta_id: int = ENCUESTA_INICIAL_ID,
) -> Dict[str, Any]:
    data = obtener_encuesta_inicial_para_whatsapp(encuesta_id)
    return {
        "encuesta_id": data["encuesta_id"],
        "preguntas": data["preguntas"],
    }


def construir_payload_botones(
    texto: str,
    opciones: List[Dict[str, Any]],
    encuesta_id: int,
    variable_id: int,
) -> Dict[str, Any]:
    buttons = []
    for opt in opciones[:MAX_BUTTONS]:
        buttons.append(
            {
                "type": "reply",
                "reply": {
                    "id": construir_id_opcion_whatsapp(encuesta_id, variable_id, int(opt["id"])),
                    "title": limpiar_label_opcion_whatsapp(opt.get("label") or "", MAX_BUTTON_TITLE),
                },
            }
        )
    return {
        "type": "button",
        "body": {"text": texto[:MAX_BODY_TEXT]},
        "action": {"buttons": buttons},
    }


def _row_lista(
    opt: Dict[str, Any],
    encuesta_id: int,
    variable_id: int,
) -> Dict[str, str]:
    label = str(opt.get("label") or "")
    title = limpiar_label_opcion_whatsapp(label, MAX_LIST_ROW_TITLE)
    row: Dict[str, str] = {
        "id": construir_id_opcion_whatsapp(encuesta_id, variable_id, int(opt["id"])),
        "title": title,
    }
    if len(label) > MAX_LIST_ROW_TITLE:
        row["description"] = limpiar_label_opcion_whatsapp(label, MAX_LIST_ROW_DESCRIPTION)
    return row


def construir_payload_lista(
    texto: str,
    opciones: List[Dict[str, Any]],
    encuesta_id: int,
    variable_id: int,
    *,
    button_label: str = "Ver opciones",
    section_title: str = "Opciones",
) -> Dict[str, Any]:
    rows = [_row_lista(o, encuesta_id, variable_id) for o in opciones[:MAX_LIST_ROWS]]
    return {
        "type": "list",
        "body": {"text": texto[:MAX_BODY_TEXT]},
        "action": {
            "button": button_label[:20],
            "sections": [{"title": section_title[:24], "rows": rows}],
        },
    }


def dividir_opciones_para_listas(
    opciones: List[Dict[str, Any]],
    max_por_lista: int = MAX_LIST_ROWS,
) -> List[List[Dict[str, Any]]]:
    if not opciones:
        return []
    grupos: List[List[Dict[str, Any]]] = []
    for i in range(0, len(opciones), max_por_lista):
        grupos.append(opciones[i : i + max_por_lista])
    return grupos


def _decidir_tipo_presentacion(pregunta: Dict[str, Any]) -> str:
    tipo = (pregunta.get("tipo_form") or "boton").lower()
    if tipo == "text":
        return "text"
    if tipo == "file":
        return "omit"
    opciones = pregunta.get("opciones") or []
    if not opciones:
        return "text"
    if len(opciones) <= MAX_BUTTONS and all(_titulo_cabe_en_boton(o.get("label") or "") for o in opciones):
        return "button"
    if len(opciones) <= MAX_LIST_ROWS:
        return "list"
    return "list_split"


def enviar_pregunta_whatsapp(
    numero: str,
    pregunta: Dict[str, Any],
    aspirante: Optional[Dict[str, Any]],
    token: str,
    phone_id: str,
) -> Dict[str, Any]:
    encuesta_id = int(pregunta.get("encuesta_id") or ENCUESTA_INICIAL_ID)
    variable_id = int(pregunta["id"])
    texto_base = limpiar_texto_pregunta_whatsapp(pregunta.get("texto") or "", aspirante)
    tipo_presentacion = _decidir_tipo_presentacion(pregunta)
    opciones = pregunta.get("opciones") or []

    resultado: Dict[str, Any] = {
        "variable_id": variable_id,
        "campo_db": pregunta.get("campo_db"),
        "tipo_presentacion": tipo_presentacion,
        "enviado": False,
        "mensajes": 0,
    }

    try:
        if tipo_presentacion == "omit":
            resultado["omitida"] = True
            resultado["motivo"] = "tipo_form=file no implementado en fase 1"
            return resultado

        if tipo_presentacion == "text":
            cuerpo = texto_base + SUFIJO_RESPUESTA_TEXTO
            codigo, _ = enviar_mensaje_texto_simple(token, phone_id, numero, cuerpo)
            resultado["enviado"] = codigo is not None and codigo < 300
            resultado["mensajes"] = 1
            resultado["http_status"] = codigo
            return resultado

        if tipo_presentacion == "button":
            payload = construir_payload_botones(texto_base, opciones, encuesta_id, variable_id)
            codigo, _ = enviar_mensaje_interactivo(token, phone_id, numero, payload)
            resultado["enviado"] = codigo is not None and codigo < 300
            resultado["mensajes"] = 1
            resultado["http_status"] = codigo
            return resultado

        if tipo_presentacion == "list":
            payload = construir_payload_lista(texto_base, opciones, encuesta_id, variable_id)
            codigo, _ = enviar_mensaje_interactivo(token, phone_id, numero, payload)
            resultado["enviado"] = codigo is not None and codigo < 300
            resultado["mensajes"] = 1
            resultado["http_status"] = codigo
            return resultado

        # list_split (>10 opciones)
        grupos = dividir_opciones_para_listas(opciones)
        total = len(grupos)
        enviados = 0
        for idx, grupo in enumerate(grupos, start=1):
            titulo = f"{texto_base} — opciones {idx} de {total}"
            payload = construir_payload_lista(
                titulo,
                grupo,
                encuesta_id,
                variable_id,
                button_label=f"Opciones {idx}/{total}",
                section_title=f"Grupo {idx}",
            )
            codigo, _ = enviar_mensaje_interactivo(token, phone_id, numero, payload)
            if codigo is not None and codigo < 300:
                enviados += 1
        resultado["enviado"] = enviados == total
        resultado["mensajes"] = total
        resultado["grupos"] = total
        return resultado

    except Exception as e:
        resultado["error"] = str(e)
        traceback.print_exc()
        return resultado


def enviar_preguntas_encuesta_whatsapp(
    numero: str,
    preguntas: List[Dict[str, Any]],
    aspirante: Optional[Dict[str, Any]],
    token: str,
    phone_id: str,
) -> Dict[str, Any]:
    enviadas = 0
    omitidas = 0
    errores: List[Dict[str, Any]] = []

    for pregunta in preguntas:
        res = enviar_pregunta_whatsapp(numero, pregunta, aspirante, token, phone_id)
        if res.get("omitida"):
            omitidas += 1
            continue
        if res.get("enviado"):
            enviadas += 1
        else:
            errores.append(
                {
                    "variable_id": res.get("variable_id"),
                    "campo_db": res.get("campo_db"),
                    "tipo_presentacion": res.get("tipo_presentacion"),
                    "error": res.get("error") or f"http_status={res.get('http_status')}",
                }
            )

    return {
        "total_preguntas": len(preguntas),
        "preguntas_enviadas": enviadas,
        "preguntas_omitidas": omitidas,
        "errores": errores,
    }


def enviar_encuesta_aspirante_whatsapp(
    numero: str,
    aspirante: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    wa_id = (numero or "").strip()
    token, phone_id = _credenciales_whatsapp()
    if not token or not phone_id:
        return {
            "canal": "whatsapp",
            "enviado": False,
            "error": "Contexto WhatsApp no disponible",
        }

    encuesta = normalizar_encuesta_para_whatsapp()
    preguntas = encuesta.get("preguntas") or []

    nombre = _nombre_aspirante(aspirante) or "aspirante"
    intro = MENSAJE_INICIO_ENCUESTA_WHATSAPP.format(nombre=nombre)
    codigo_intro, _ = enviar_mensaje_texto_simple(token, phone_id, wa_id, intro)
    if codigo_intro is None or codigo_intro >= 300:
        return {
            "canal": "whatsapp",
            "enviado": False,
            "error": "No se pudo enviar mensaje introductorio",
            "http_status": codigo_intro,
        }

    resumen = enviar_preguntas_encuesta_whatsapp(wa_id, preguntas, aspirante, token, phone_id)
    return {
        "canal": "whatsapp",
        "enviado": resumen["preguntas_enviadas"] > 0,
        **resumen,
    }


def _enviar_formulario_web(numero: str) -> None:
    from main_webhook import enviar_inicio_encuesta  # import tardío evita ciclo

    enviar_inicio_encuesta(numero)


def iniciar_encuesta_onboarding_por_canal(
    numero: str,
    aspirante: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Orquesta el inicio de encuesta según configuracion_agencia.canal_encuesta_aspirante.
    """
    raw = obtener_configuracion_agencia("canal_encuesta_aspirante")
    canal = str(raw or "").strip().lower()

    if canal == "whatsapp":
        resultado = enviar_encuesta_aspirante_whatsapp(numero=numero, aspirante=aspirante)
        return resultado

    # formulario_web por defecto (incluye vacío o valor desconocido)
    _enviar_formulario_web(numero)
    return {"canal": "formulario_web", "enviado": True}
