"""
Encuesta inicial del aspirante por WhatsApp.
"""
from __future__ import annotations

import math
import re
import traceback
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from DataBase import obtener_configuracion_agencia
from encuesta_inicial_service import obtener_encuesta_inicial_normalizada
from encuesta_portal_utils import ENCUESTA_INICIAL_ID
from enviar_msg_wp import enviar_mensaje_interactivo, enviar_mensaje_texto_simple
from tenant import current_phone_id, current_token
from utils_whatsapp_flujos import (
    actualizar_flujo_whatsapp,
    eliminar_flujo_whatsapp,
    obtener_flujo_whatsapp,
    ttl_onboarding_encuesta,
)

TIPO_FLUJO_ENCUESTA = "encuesta_aspirante_whatsapp"
PASO_ESPERANDO_INICIO = "encuesta_whatsapp_esperando_inicio"
PASO_ESPERANDO_RESPUESTA = "encuesta_whatsapp_esperando_respuesta"

PAYLOAD_COMENZAR = "ENCUESTA_WA_COMENZAR"
PAYLOAD_FAQ = "ENCUESTA_WA_FAQ"

MAX_TEXTO_RESPUESTA = 500
MAX_WA_TEXT = 4000

_RE_ID_OPCION = re.compile(r"^enc_(\d+)_preg_(\d+)_opc_(\d+)$")

MSG_OPCION_INVALIDA = (
    "⚠️ Esa opción no corresponde a la pregunta actual. "
    "Selecciona una de las opciones mostradas."
)
MSG_TEXTO_INVALIDO = "⚠️ Por favor escribe tu respuesta en texto."
MSG_CONSOLIDACION_FALLIDA = (
    "⚠️ Recibimos tus respuestas, pero no pudimos finalizar el proceso "
    "en este momento. Intenta nuevamente más tarde."
)
MSG_OPCIONES_INICIO = (
    "Para continuar, selecciona *Comenzar*. "
    "También puedes consultar las preguntas frecuentes antes de iniciar."
)

MENSAJE_INICIO_ENCUESTA_WHATSAPP = (
    "✨ ¡Perfecto, {nombre}!\n\n"
    "Antes de continuar, queremos conocerte un poco mejor.\n\n"
    "Son solo *{total_preguntas}* preguntas breves y te tomará menos de un minuto.\n\n"
    "No hay respuestas buenas o malas: queremos conocer tus objetivos "
    "y disponibilidad para orientarte mejor."
)

SUFIJO_RESPUESTA_TEXTO = "\n\nEscribe tu respuesta."

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


def _normalizar_comando(texto: Optional[str]) -> str:
    if not texto:
        return ""
    t = unicodedata.normalize("NFD", str(texto).strip().lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(t.split())


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


def construir_texto_pregunta_con_progreso(
    texto_pregunta: str,
    indice_actual: int,
    total_preguntas: int,
) -> str:
    numero_actual = int(indice_actual) + 1
    total = max(1, int(total_preguntas or 1))
    return f"*Pregunta {numero_actual} de {total}*\n\n{texto_pregunta}".strip()


def obtener_mensaje_progreso(
    respuestas_completadas: int,
    total_preguntas: int,
    nombre: str,
    *,
    progreso_mitad_enviado: bool = False,
    progreso_final_enviado: bool = False,
) -> Tuple[Optional[str], Dict[str, bool]]:
    """
    Mensajes estratégicos de progreso. Retorna (mensaje|None, flags_actualizados).
    """
    total = int(total_preguntas or 0)
    respondidas = int(respuestas_completadas or 0)
    flags = {
        "progreso_mitad_enviado": bool(progreso_mitad_enviado),
        "progreso_final_enviado": bool(progreso_final_enviado),
    }
    nombre_ok = (nombre or "").strip() or "tú"

    if total <= 3:
        return None, flags

    # Antes de la última pregunta: respondidas == total - 1
    es_antes_ultima = respondidas == total - 1 and respondidas > 0
    mitad = math.ceil(total / 2)
    es_mitad = respondidas == mitad and total >= 5

    if total == 4:
        if es_antes_ultima and not flags["progreso_final_enviado"]:
            flags["progreso_final_enviado"] = True
            return (
                f"🙌 Muy bien, {nombre_ok}. Ya casi terminamos: falta una pregunta.",
                flags,
            )
        return None, flags

    # 5 o más
    if es_antes_ultima and not flags["progreso_final_enviado"]:
        # Si mitad y final coinciden, solo enviar el de final
        flags["progreso_final_enviado"] = True
        if es_mitad:
            flags["progreso_mitad_enviado"] = True
        return ("🙌 Ya casi terminamos. Falta una pregunta.", flags)

    if es_mitad and not flags["progreso_mitad_enviado"]:
        flags["progreso_mitad_enviado"] = True
        return (
            f"✅ Muy bien, {nombre_ok}. Ya completaste {respondidas} de {total} preguntas.",
            flags,
        )

    return None, flags


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


def dividir_texto_whatsapp(texto: str, max_len: int = MAX_WA_TEXT) -> List[str]:
    """Divide texto largo respetando saltos de línea y sin cortar palabras."""
    texto = (texto or "").strip()
    if not texto:
        return []
    if len(texto) <= max_len:
        return [texto]

    partes: List[str] = []
    restante = texto
    while restante:
        if len(restante) <= max_len:
            partes.append(restante)
            break
        corte = restante.rfind("\n", 0, max_len + 1)
        if corte < max_len // 3:
            corte = restante.rfind(" ", 0, max_len + 1)
        if corte <= 0:
            corte = max_len
        partes.append(restante[:corte].rstrip())
        restante = restante[corte:].lstrip()
    return [p for p in partes if p]


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


def _faq_disponible() -> Optional[str]:
    raw = obtener_configuracion_agencia("preguntas_frecuentes")
    texto = str(raw or "").strip()
    return texto or None


def _payload_botones_inicio(*, incluir_faq: bool) -> Dict[str, Any]:
    buttons = [
        {
            "type": "reply",
            "reply": {
                "id": PAYLOAD_COMENZAR,
                "title": "🚀 Comenzar",
            },
        }
    ]
    if incluir_faq:
        buttons.append(
            {
                "type": "reply",
                "reply": {
                    "id": PAYLOAD_FAQ,
                    "title": "❓ Ver FAQ",
                },
            }
        )
    return {
        "type": "button",
        "body": {"text": "¿Listo para comenzar?"},
        "action": {"buttons": buttons},
    }


def enviar_pregunta_whatsapp(
    numero: str,
    pregunta: Dict[str, Any],
    aspirante: Optional[Dict[str, Any]],
    token: str,
    phone_id: str,
    *,
    indice_actual: int = 0,
    total_preguntas: int = 1,
) -> Dict[str, Any]:
    encuesta_id = int(pregunta.get("encuesta_id") or ENCUESTA_INICIAL_ID)
    variable_id = int(pregunta["id"])
    texto_limpio = limpiar_texto_pregunta_whatsapp(pregunta.get("texto") or "", aspirante)
    texto_base = construir_texto_pregunta_con_progreso(
        texto_limpio,
        indice_actual,
        total_preguntas,
    )
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
            resultado["motivo"] = "tipo_form=file no implementado"
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


def parsear_id_opcion_whatsapp(payload_id: Optional[str]) -> Optional[Dict[str, int]]:
    if not payload_id:
        return None
    match = _RE_ID_OPCION.match(str(payload_id).strip())
    if not match:
        return None
    return {
        "encuesta_id": int(match.group(1)),
        "variable_id": int(match.group(2)),
        "valor_id": int(match.group(3)),
    }


def _pregunta_serializable(pregunta: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": pregunta.get("id"),
        "encuesta_id": pregunta.get("encuesta_id") or ENCUESTA_INICIAL_ID,
        "orden": pregunta.get("orden"),
        "campo_db": pregunta.get("campo_db"),
        "tipo_form": pregunta.get("tipo_form"),
        "texto": pregunta.get("texto") or "",
        "opciones": [
            {"id": o.get("id"), "label": o.get("label") or "", "orden": o.get("orden")}
            for o in (pregunta.get("opciones") or [])
            if o and o.get("id") is not None
        ],
    }


def _crear_payload_sesion(
    aspirante: Optional[Dict[str, Any]],
    preguntas: List[Dict[str, Any]],
    encuesta_id: int,
) -> Dict[str, Any]:
    preguntas_ids = [int(p["id"]) for p in preguntas]
    preguntas_por_id = {str(p["id"]): _pregunta_serializable(p) for p in preguntas}
    return {
        "tipo_flujo": TIPO_FLUJO_ENCUESTA,
        "encuesta_id": encuesta_id,
        "aspirante_id": aspirante.get("id") if aspirante else None,
        "preguntas_ids": preguntas_ids,
        "preguntas_por_id": preguntas_por_id,
        "total_preguntas": len(preguntas_ids),
        "indice_actual": 0,
        "pregunta_actual_id": preguntas_ids[0] if preguntas_ids else None,
        "respuestas": {},
        "meta": {},
        "iniciada": False,
        "iniciada_en": None,
        "progreso_mitad_enviado": False,
        "progreso_final_enviado": False,
        "ultimo_message_id_meta": None,
        "nombre_saludo": _nombre_aspirante(aspirante) or None,
    }


def _obtener_sesion_encuesta(numero: str) -> Optional[Dict[str, Any]]:
    row = obtener_flujo_whatsapp(numero)
    if not row:
        return None
    payload = row.get("payload_json")
    if not isinstance(payload, dict):
        return None
    if payload.get("tipo_flujo") != TIPO_FLUJO_ENCUESTA:
        return None
    payload["_paso"] = row.get("paso")
    payload["_aspirante_id_row"] = row.get("aspirante_id")
    if not payload.get("total_preguntas"):
        payload["total_preguntas"] = len(payload.get("preguntas_ids") or [])
    return payload


def _persistir_sesion_encuesta(
    numero: str,
    payload: Dict[str, Any],
    paso: Optional[str] = None,
) -> None:
    aspirante_id = payload.get("aspirante_id") or payload.get("_aspirante_id_row")
    paso_final = paso or payload.get("_paso") or PASO_ESPERANDO_RESPUESTA
    # Limpiar claves internas antes de persistir
    clean = {k: v for k, v in payload.items() if not str(k).startswith("_")}
    actualizar_flujo_whatsapp(
        numero,
        paso_final,
        aspirante_id=aspirante_id,
        payload_json=clean,
        ttl_minutos=ttl_onboarding_encuesta(),
    )
    payload["_paso"] = paso_final


def _aspirante_ctx_desde_sesion(payload: Dict[str, Any]) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {"id": payload.get("aspirante_id")}
    if payload.get("nombre_saludo"):
        ctx["nombre"] = payload["nombre_saludo"]
    preguntas_por_id = payload.get("preguntas_por_id") or {}
    respuestas = payload.get("respuestas") or {}
    for pregunta in preguntas_por_id.values():
        if pregunta.get("campo_db") == "nombre":
            nombre = respuestas.get(str(pregunta["id"]))
            if nombre:
                ctx["nombre"] = nombre
            break
    return ctx


def _pregunta_actual(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    pid = payload.get("pregunta_actual_id")
    if pid is None:
        return None
    return (payload.get("preguntas_por_id") or {}).get(str(pid))


def _total_preguntas_sesion(payload: Dict[str, Any]) -> int:
    return int(payload.get("total_preguntas") or len(payload.get("preguntas_ids") or []) or 1)


def _es_pregunta_seleccionable(pregunta: Dict[str, Any]) -> bool:
    tipo = (pregunta.get("tipo_form") or "boton").lower()
    if tipo in {"text", "file"}:
        return False
    return bool(pregunta.get("opciones"))


def _validar_opcion_interactiva(
    payload: Dict[str, Any],
    parsed: Dict[str, int],
) -> Optional[str]:
    if parsed["encuesta_id"] != int(payload.get("encuesta_id") or ENCUESTA_INICIAL_ID):
        return "encuesta_id"
    if parsed["variable_id"] != int(payload.get("pregunta_actual_id")):
        return "variable_id"
    pregunta = _pregunta_actual(payload)
    if not pregunta:
        return "pregunta"
    opciones_ids = {int(o["id"]) for o in (pregunta.get("opciones") or [])}
    if parsed["valor_id"] not in opciones_ids:
        return "valor_id"
    return None


def _respuestas_a_consolidar(payload: Dict[str, Any]) -> Dict[int, str]:
    out: Dict[int, str] = {}
    for key, valor in (payload.get("respuestas") or {}).items():
        if str(key).isdigit():
            out[int(key)] = str(valor)
    return out


def _todas_respondidas(payload: Dict[str, Any]) -> bool:
    ids = payload.get("preguntas_ids") or []
    respuestas = payload.get("respuestas") or {}
    return bool(ids) and all(str(pid) in respuestas for pid in ids)


def _enviar_menu_inicio(
    numero: str,
    token: str,
    phone_id: str,
    *,
    enviar_intro: bool,
    nombre: str,
    total_preguntas: int,
) -> bool:
    if enviar_intro:
        intro = MENSAJE_INICIO_ENCUESTA_WHATSAPP.format(
            nombre=nombre or "aspirante",
            total_preguntas=total_preguntas,
        )
        codigo, _ = enviar_mensaje_texto_simple(token, phone_id, numero, intro)
        if codigo is None or codigo >= 300:
            return False

    faq = _faq_disponible()
    interactive = _payload_botones_inicio(incluir_faq=bool(faq))
    codigo, _ = enviar_mensaje_interactivo(token, phone_id, numero, interactive)
    return codigo is not None and codigo < 300


def _enviar_pregunta_actual_sesion(
    numero: str,
    payload: Dict[str, Any],
    token: str,
    phone_id: str,
) -> Dict[str, Any]:
    pregunta = _pregunta_actual(payload)
    if not pregunta:
        return {"enviado": False, "error": "sin_pregunta"}
    return enviar_pregunta_whatsapp(
        numero,
        pregunta,
        _aspirante_ctx_desde_sesion(payload),
        token,
        phone_id,
        indice_actual=int(payload.get("indice_actual") or 0),
        total_preguntas=_total_preguntas_sesion(payload),
    )


def comenzar_encuesta_whatsapp(numero: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    wa_id = (numero or "").strip()
    token, phone_id = _credenciales_whatsapp()
    if not token or not phone_id:
        return {"status": "sin_credenciales"}

    preguntas_ids = payload.get("preguntas_ids") or []
    if not preguntas_ids:
        return {"status": "sin_preguntas"}

    # Ya iniciada: reenviar pregunta pendiente, no reiniciar
    if payload.get("iniciada"):
        res = _enviar_pregunta_actual_sesion(wa_id, payload, token, phone_id)
        _persistir_sesion_encuesta(wa_id, payload, PASO_ESPERANDO_RESPUESTA)
        return {"status": "reanudada", "enviado": res.get("enviado")}

    payload["iniciada"] = True
    payload["iniciada_en"] = datetime.now(timezone.utc).isoformat()
    payload["indice_actual"] = 0
    payload["pregunta_actual_id"] = preguntas_ids[0]
    _persistir_sesion_encuesta(wa_id, payload, PASO_ESPERANDO_RESPUESTA)

    res = _enviar_pregunta_actual_sesion(wa_id, payload, token, phone_id)
    return {"status": "ok", "enviado": res.get("enviado"), "pregunta_actual_id": preguntas_ids[0]}


def enviar_faq_encuesta_whatsapp(numero: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    wa_id = (numero or "").strip()
    token, phone_id = _credenciales_whatsapp()
    if not token or not phone_id:
        return {"status": "sin_credenciales"}

    faq = _faq_disponible()
    if not faq:
        enviar_mensaje_texto_simple(
            token,
            phone_id,
            wa_id,
            "Por ahora no hay preguntas frecuentes configuradas.",
        )
        _enviar_menu_inicio(
            wa_id,
            token,
            phone_id,
            enviar_intro=False,
            nombre=payload.get("nombre_saludo") or "aspirante",
            total_preguntas=_total_preguntas_sesion(payload),
        )
        _persistir_sesion_encuesta(wa_id, payload, PASO_ESPERANDO_INICIO)
        return {"status": "faq_vacio"}

    for parte in dividir_texto_whatsapp(faq):
        enviar_mensaje_texto_simple(token, phone_id, wa_id, parte)

    # Solo botón Comenzar después del FAQ
    interactive = {
        "type": "button",
        "body": {"text": "Cuando quieras, puedes comenzar la encuesta."},
        "action": {
            "buttons": [
                {
                    "type": "reply",
                    "reply": {"id": PAYLOAD_COMENZAR, "title": "🚀 Comenzar"},
                }
            ]
        },
    }
    enviar_mensaje_interactivo(token, phone_id, wa_id, interactive)
    _persistir_sesion_encuesta(wa_id, payload, PASO_ESPERANDO_INICIO)
    return {"status": "faq_enviado"}


def procesar_inicio_encuesta_whatsapp(
    numero: str,
    tipo: Optional[str],
    texto: Optional[str],
    payload_id: Optional[str],
    message_id_meta: Optional[str] = None,
) -> Dict[str, Any]:
    wa_id = (numero or "").strip()
    payload = _obtener_sesion_encuesta(wa_id)
    if not payload:
        return {"status": "sin_sesion"}

    if message_id_meta and payload.get("ultimo_message_id_meta") == message_id_meta:
        return {"status": "duplicado"}

    if message_id_meta:
        payload["ultimo_message_id_meta"] = message_id_meta
        _persistir_sesion_encuesta(wa_id, payload, PASO_ESPERANDO_INICIO)

    token, phone_id = _credenciales_whatsapp()
    if not token or not phone_id:
        return {"status": "sin_credenciales"}

    cmd = _normalizar_comando(texto)
    es_comenzar = (
        payload_id == PAYLOAD_COMENZAR
        or cmd in {"comenzar", "empezar", "iniciar"}
    )
    es_faq = (
        payload_id == PAYLOAD_FAQ
        or cmd in {"preguntas frecuentes", "faq", "preguntas"}
    )

    if es_comenzar:
        return comenzar_encuesta_whatsapp(wa_id, payload)

    if es_faq:
        return enviar_faq_encuesta_whatsapp(wa_id, payload)

    enviar_mensaje_texto_simple(token, phone_id, wa_id, MSG_OPCIONES_INICIO)
    _enviar_menu_inicio(
        wa_id,
        token,
        phone_id,
        enviar_intro=False,
        nombre=payload.get("nombre_saludo") or "aspirante",
        total_preguntas=_total_preguntas_sesion(payload),
    )
    return {"status": "opcion_invalida"}


def _finalizar_encuesta_whatsapp(numero: str, payload: Dict[str, Any]) -> bool:
    token, phone_id = _credenciales_whatsapp()
    if not token or not phone_id:
        print(f"❌ [ENCUESTA WHATSAPP] Sin credenciales al finalizar {numero}")
        return False

    try:
        from main_webhook import mensaje_encuesta_final
        from encuesta_consolidacion import consolidar_encuesta_inicial
    except Exception as e:
        print(f"❌ [ENCUESTA WHATSAPP] Error importando consolidación: {e}")
        traceback.print_exc()
        payload["consolidacion_pendiente"] = True
        _persistir_sesion_encuesta(numero, payload, PASO_ESPERANDO_RESPUESTA)
        try:
            enviar_mensaje_texto_simple(token, phone_id, numero, MSG_CONSOLIDACION_FALLIDA)
        except Exception:
            pass
        return False

    try:
        resultado = consolidar_encuesta_inicial(
            numero=numero,
            respuestas=_respuestas_a_consolidar(payload),
            meta=payload.get("meta"),
            origen="whatsapp",
            construir_mensaje_final=mensaje_encuesta_final,
        )
    except Exception as e:
        print(f"❌ [ENCUESTA WHATSAPP] Excepción consolidando {numero}: {e}")
        traceback.print_exc()
        payload["consolidacion_pendiente"] = True
        _persistir_sesion_encuesta(numero, payload, PASO_ESPERANDO_RESPUESTA)
        try:
            enviar_mensaje_texto_simple(token, phone_id, numero, MSG_CONSOLIDACION_FALLIDA)
        except Exception:
            pass
        return False

    if not resultado.get("ok"):
        print(
            f"❌ [ENCUESTA WHATSAPP] Consolidación fallida para {numero}: "
            f"{resultado.get('error')}"
        )
        payload["consolidacion_pendiente"] = True
        _persistir_sesion_encuesta(numero, payload, PASO_ESPERANDO_RESPUESTA)
        try:
            enviar_mensaje_texto_simple(token, phone_id, numero, MSG_CONSOLIDACION_FALLIDA)
        except Exception:
            pass
        return False

    eliminar_flujo_whatsapp(numero)
    mensaje = resultado.get("mensaje_final") or ""
    if mensaje:
        enviar_mensaje_texto_simple(token, phone_id, numero, mensaje)
    return True


def _avanzar_o_finalizar(numero: str, payload: Dict[str, Any]) -> None:
    preguntas_ids: List[int] = payload.get("preguntas_ids") or []
    indice = int(payload.get("indice_actual") or 0)
    siguiente = indice + 1
    respondidas = len(payload.get("respuestas") or {})
    total = _total_preguntas_sesion(payload)

    if siguiente >= len(preguntas_ids):
        _finalizar_encuesta_whatsapp(numero, payload)
        return

    token, phone_id = _credenciales_whatsapp()
    if not token or not phone_id:
        return

    ctx = _aspirante_ctx_desde_sesion(payload)
    nombre = ctx.get("nombre") or payload.get("nombre_saludo") or "tú"
    msg_prog, flags = obtener_mensaje_progreso(
        respondidas,
        total,
        nombre,
        progreso_mitad_enviado=bool(payload.get("progreso_mitad_enviado")),
        progreso_final_enviado=bool(payload.get("progreso_final_enviado")),
    )
    payload["progreso_mitad_enviado"] = flags["progreso_mitad_enviado"]
    payload["progreso_final_enviado"] = flags["progreso_final_enviado"]
    if msg_prog:
        enviar_mensaje_texto_simple(token, phone_id, numero, msg_prog)

    payload["indice_actual"] = siguiente
    payload["pregunta_actual_id"] = preguntas_ids[siguiente]
    _persistir_sesion_encuesta(numero, payload, PASO_ESPERANDO_RESPUESTA)

    pregunta = _pregunta_actual(payload)
    if not pregunta:
        return
    enviar_pregunta_whatsapp(
        numero,
        pregunta,
        ctx,
        token,
        phone_id,
        indice_actual=siguiente,
        total_preguntas=total,
    )


def procesar_respuesta_encuesta_whatsapp(
    numero: str,
    tipo: Optional[str],
    texto: Optional[str],
    payload_id: Optional[str],
    message_id_meta: Optional[str] = None,
) -> Dict[str, Any]:
    wa_id = (numero or "").strip()
    payload = _obtener_sesion_encuesta(wa_id)
    if not payload:
        return {"status": "sin_sesion"}

    if message_id_meta and payload.get("ultimo_message_id_meta") == message_id_meta:
        return {"status": "duplicado"}

    # No interpretar botones de inicio como opciones de pregunta
    if payload_id in {PAYLOAD_COMENZAR, PAYLOAD_FAQ}:
        if payload.get("iniciada"):
            token, phone_id = _credenciales_whatsapp()
            if token and phone_id:
                _enviar_pregunta_actual_sesion(wa_id, payload, token, phone_id)
            return {"status": "ignorado_payload_inicio"}
        return procesar_inicio_encuesta_whatsapp(
            numero=wa_id,
            tipo=tipo,
            texto=texto,
            payload_id=payload_id,
            message_id_meta=message_id_meta,
        )

    if payload.get("consolidacion_pendiente") and _todas_respondidas(payload):
        if message_id_meta:
            payload["ultimo_message_id_meta"] = message_id_meta
            _persistir_sesion_encuesta(wa_id, payload, PASO_ESPERANDO_RESPUESTA)
        ok = _finalizar_encuesta_whatsapp(wa_id, payload)
        return {"status": "reintento_consolidacion", "ok": ok}

    pregunta = _pregunta_actual(payload)
    if not pregunta:
        return {"status": "sin_pregunta"}

    token, phone_id = _credenciales_whatsapp()
    if not token or not phone_id:
        return {"status": "sin_credenciales"}

    variable_id = int(payload["pregunta_actual_id"])
    valor_guardar: Optional[str] = None
    total = _total_preguntas_sesion(payload)
    indice = int(payload.get("indice_actual") or 0)

    if _es_pregunta_seleccionable(pregunta):
        if tipo != "interactive" or not payload_id:
            enviar_mensaje_texto_simple(token, phone_id, wa_id, MSG_OPCION_INVALIDA)
            enviar_pregunta_whatsapp(
                wa_id, pregunta, _aspirante_ctx_desde_sesion(payload), token, phone_id,
                indice_actual=indice, total_preguntas=total,
            )
            return {"status": "rechazado", "motivo": "se_esperaba_interactivo"}

        parsed = parsear_id_opcion_whatsapp(payload_id)
        if not parsed:
            enviar_mensaje_texto_simple(token, phone_id, wa_id, MSG_OPCION_INVALIDA)
            enviar_pregunta_whatsapp(
                wa_id, pregunta, _aspirante_ctx_desde_sesion(payload), token, phone_id,
                indice_actual=indice, total_preguntas=total,
            )
            return {"status": "rechazado", "motivo": "id_invalido"}

        error = _validar_opcion_interactiva(payload, parsed)
        if error:
            enviar_mensaje_texto_simple(token, phone_id, wa_id, MSG_OPCION_INVALIDA)
            enviar_pregunta_whatsapp(
                wa_id, pregunta, _aspirante_ctx_desde_sesion(payload), token, phone_id,
                indice_actual=indice, total_preguntas=total,
            )
            return {"status": "rechazado", "motivo": error}

        valor_guardar = str(parsed["valor_id"])
    else:
        if tipo != "text" or not (texto or "").strip():
            enviar_mensaje_texto_simple(token, phone_id, wa_id, MSG_TEXTO_INVALIDO)
            enviar_pregunta_whatsapp(
                wa_id, pregunta, _aspirante_ctx_desde_sesion(payload), token, phone_id,
                indice_actual=indice, total_preguntas=total,
            )
            return {"status": "rechazado", "motivo": "texto_invalido"}

        valor_limpio = texto.strip()
        if len(valor_limpio) > MAX_TEXTO_RESPUESTA:
            valor_limpio = valor_limpio[:MAX_TEXTO_RESPUESTA]
        valor_guardar = valor_limpio

    respuestas = dict(payload.get("respuestas") or {})
    respuestas[str(variable_id)] = valor_guardar
    payload["respuestas"] = respuestas
    if message_id_meta:
        payload["ultimo_message_id_meta"] = message_id_meta

    _persistir_sesion_encuesta(wa_id, payload, PASO_ESPERANDO_RESPUESTA)
    _avanzar_o_finalizar(wa_id, payload)
    return {"status": "ok", "variable_id": variable_id, "valor": valor_guardar}


def enviar_encuesta_aspirante_whatsapp(
    numero: str,
    aspirante: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    wa_id = (numero or "").strip()
    token, phone_id = _credenciales_whatsapp()
    if not token or not phone_id:
        return {
            "canal": "whatsapp",
            "iniciada": False,
            "error": "Contexto WhatsApp no disponible",
        }

    sesion_existente = _obtener_sesion_encuesta(wa_id)
    if sesion_existente:
        if sesion_existente.get("iniciada"):
            res = _enviar_pregunta_actual_sesion(wa_id, sesion_existente, token, phone_id)
            _persistir_sesion_encuesta(wa_id, sesion_existente, PASO_ESPERANDO_RESPUESTA)
            return {
                "canal": "whatsapp",
                "iniciada": True,
                "reanudada": True,
                "pregunta_actual_id": sesion_existente.get("pregunta_actual_id"),
                "total_preguntas": _total_preguntas_sesion(sesion_existente),
                "enviado": res.get("enviado"),
            }

        ok = _enviar_menu_inicio(
            wa_id,
            token,
            phone_id,
            enviar_intro=True,
            nombre=sesion_existente.get("nombre_saludo") or _nombre_aspirante(aspirante) or "aspirante",
            total_preguntas=_total_preguntas_sesion(sesion_existente),
        )
        _persistir_sesion_encuesta(wa_id, sesion_existente, PASO_ESPERANDO_INICIO)
        return {
            "canal": "whatsapp",
            "iniciada": False,
            "esperando_inicio": True,
            "total_preguntas": _total_preguntas_sesion(sesion_existente),
            "menu_enviado": ok,
        }

    encuesta = normalizar_encuesta_para_whatsapp()
    preguntas = encuesta.get("preguntas") or []
    encuesta_id = int(encuesta.get("encuesta_id") or ENCUESTA_INICIAL_ID)

    if not preguntas:
        return {
            "canal": "whatsapp",
            "iniciada": False,
            "error": "No hay preguntas disponibles para la encuesta inicial",
        }

    payload_sesion = _crear_payload_sesion(aspirante, preguntas, encuesta_id)
    total = len(preguntas)
    nombre = _nombre_aspirante(aspirante) or "aspirante"

    ok = _enviar_menu_inicio(
        wa_id,
        token,
        phone_id,
        enviar_intro=True,
        nombre=nombre,
        total_preguntas=total,
    )
    if not ok:
        return {
            "canal": "whatsapp",
            "iniciada": False,
            "error": "No se pudo enviar mensaje introductorio / menú",
        }

    _persistir_sesion_encuesta(wa_id, payload_sesion, PASO_ESPERANDO_INICIO)
    return {
        "canal": "whatsapp",
        "iniciada": False,
        "esperando_inicio": True,
        "total_preguntas": total,
        "pregunta_actual_id": payload_sesion.get("pregunta_actual_id"),
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
        return enviar_encuesta_aspirante_whatsapp(numero=numero, aspirante=aspirante)

    _enviar_formulario_web(numero)
    return {"canal": "formulario_web", "enviado": True}
