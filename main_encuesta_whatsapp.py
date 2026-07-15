"""
Encuesta inicial del aspirante por WhatsApp.
"""
from __future__ import annotations

import re
import traceback
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
PASO_ENCUESTA_WHATSAPP = "encuesta_whatsapp_esperando_respuesta"
MAX_TEXTO_RESPUESTA = 500

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
        "indice_actual": 0,
        "pregunta_actual_id": preguntas_ids[0] if preguntas_ids else None,
        "respuestas": {},
        "meta": {},
        "iniciada_en": datetime.now(timezone.utc).isoformat(),
        "ultimo_message_id_meta": None,
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
    return payload


def _persistir_sesion_encuesta(numero: str, payload: Dict[str, Any]) -> None:
    aspirante_id = payload.get("aspirante_id") or payload.get("_aspirante_id_row")
    actualizar_flujo_whatsapp(
        numero,
        PASO_ENCUESTA_WHATSAPP,
        aspirante_id=aspirante_id,
        payload_json=payload,
        ttl_minutos=ttl_onboarding_encuesta(),
    )


def _aspirante_ctx_desde_sesion(payload: Dict[str, Any]) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {"id": payload.get("aspirante_id")}
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


def _finalizar_encuesta_whatsapp(numero: str, payload: Dict[str, Any]) -> bool:
    from main_webhook import mensaje_encuesta_final
    from services.encuesta_consolidacion import consolidar_encuesta_inicial

    token, phone_id = _credenciales_whatsapp()
    if not token or not phone_id:
        return False

    resultado = consolidar_encuesta_inicial(
        numero=numero,
        respuestas=_respuestas_a_consolidar(payload),
        meta=payload.get("meta"),
        origen="whatsapp",
        construir_mensaje_final=mensaje_encuesta_final,
    )

    if not resultado.get("ok"):
        print(f"❌ [ENCUESTA WHATSAPP] Consolidación fallida para {numero}: {resultado.get('error')}")
        enviar_mensaje_texto_simple(token, phone_id, numero, MSG_CONSOLIDACION_FALLIDA)
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

    if siguiente >= len(preguntas_ids):
        _finalizar_encuesta_whatsapp(numero, payload)
        return

    payload["indice_actual"] = siguiente
    payload["pregunta_actual_id"] = preguntas_ids[siguiente]
    _persistir_sesion_encuesta(numero, payload)

    token, phone_id = _credenciales_whatsapp()
    if not token or not phone_id:
        return

    pregunta = _pregunta_actual(payload)
    if not pregunta:
        return

    ctx = _aspirante_ctx_desde_sesion(payload)
    enviar_pregunta_whatsapp(numero, pregunta, ctx, token, phone_id)


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

    pregunta = _pregunta_actual(payload)
    if not pregunta:
        return {"status": "sin_pregunta"}

    token, phone_id = _credenciales_whatsapp()
    if not token or not phone_id:
        return {"status": "sin_credenciales"}

    variable_id = int(payload["pregunta_actual_id"])
    valor_guardar: Optional[str] = None

    if _es_pregunta_seleccionable(pregunta):
        if tipo != "interactive" or not payload_id:
            enviar_mensaje_texto_simple(token, phone_id, wa_id, MSG_OPCION_INVALIDA)
            enviar_pregunta_whatsapp(wa_id, pregunta, _aspirante_ctx_desde_sesion(payload), token, phone_id)
            return {"status": "rechazado", "motivo": "se_esperaba_interactivo"}

        parsed = parsear_id_opcion_whatsapp(payload_id)
        if not parsed:
            enviar_mensaje_texto_simple(token, phone_id, wa_id, MSG_OPCION_INVALIDA)
            enviar_pregunta_whatsapp(wa_id, pregunta, _aspirante_ctx_desde_sesion(payload), token, phone_id)
            return {"status": "rechazado", "motivo": "id_invalido"}

        error = _validar_opcion_interactiva(payload, parsed)
        if error:
            enviar_mensaje_texto_simple(token, phone_id, wa_id, MSG_OPCION_INVALIDA)
            enviar_pregunta_whatsapp(wa_id, pregunta, _aspirante_ctx_desde_sesion(payload), token, phone_id)
            return {"status": "rechazado", "motivo": error}

        valor_guardar = str(parsed["valor_id"])
    else:
        if tipo != "text" or not (texto or "").strip():
            enviar_mensaje_texto_simple(token, phone_id, wa_id, MSG_TEXTO_INVALIDO)
            enviar_pregunta_whatsapp(wa_id, pregunta, _aspirante_ctx_desde_sesion(payload), token, phone_id)
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

    _persistir_sesion_encuesta(wa_id, payload)
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

    encuesta = normalizar_encuesta_para_whatsapp()
    preguntas = encuesta.get("preguntas") or []
    encuesta_id = int(encuesta.get("encuesta_id") or ENCUESTA_INICIAL_ID)

    if not preguntas:
        return {
            "canal": "whatsapp",
            "iniciada": False,
            "error": "No hay preguntas disponibles para la encuesta inicial",
        }

    sesion_existente = _obtener_sesion_encuesta(wa_id)
    if sesion_existente and sesion_existente.get("pregunta_actual_id"):
        pregunta = _pregunta_actual(sesion_existente)
        if pregunta:
            enviar_pregunta_whatsapp(
                wa_id,
                pregunta,
                _aspirante_ctx_desde_sesion(sesion_existente),
                token,
                phone_id,
            )
            return {
                "canal": "whatsapp",
                "iniciada": True,
                "reanudada": True,
                "pregunta_actual_id": sesion_existente.get("pregunta_actual_id"),
                "total_preguntas": len(sesion_existente.get("preguntas_ids") or []),
            }

    payload_sesion = _crear_payload_sesion(aspirante, preguntas, encuesta_id)
    _persistir_sesion_encuesta(wa_id, payload_sesion)

    nombre = _nombre_aspirante(aspirante) or "aspirante"
    intro = MENSAJE_INICIO_ENCUESTA_WHATSAPP.format(nombre=nombre)
    codigo_intro, _ = enviar_mensaje_texto_simple(token, phone_id, wa_id, intro)
    if codigo_intro is None or codigo_intro >= 300:
        return {
            "canal": "whatsapp",
            "iniciada": False,
            "error": "No se pudo enviar mensaje introductorio",
            "http_status": codigo_intro,
        }

    primera = preguntas[0]
    res = enviar_pregunta_whatsapp(wa_id, primera, aspirante, token, phone_id)
    if not res.get("enviado"):
        return {
            "canal": "whatsapp",
            "iniciada": False,
            "error": "No se pudo enviar la primera pregunta",
            "detalle": res,
        }

    return {
        "canal": "whatsapp",
        "iniciada": True,
        "pregunta_actual_id": primera.get("id"),
        "total_preguntas": len(preguntas),
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
