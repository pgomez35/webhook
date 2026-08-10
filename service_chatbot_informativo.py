"""
Motor del chatbot informativo (menú numerado + respuestas por fuente).

Contrato (tipo_chatbot=informativo):
- menú + información + consultas libres
- no clasificación de aspirante (principiante/experimentado)
- no flujo obligatorio de conversión / solicitud / evidencias

Archivo plano en la raíz. No usa búsqueda en internet.
"""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("uvicorn.error")

NUMEROS_TEXTO = {
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
}

DEFAULTS_PRESENTACION = {
    "mostrar_menu_inicial": True,
    "titulo_menu_inicial": "Puedo ayudarte con información sobre:",
    "texto_indicacion_menu": (
        "Escribe el número de la opción, cuéntame qué deseas saber "
        "o escribe *menu* para ver las opciones otra vez."
    ),
    "formato_respuestas_informativas": "lista",
    "max_elementos_respuesta": 8,
    "mostrar_titulo_respuesta": True,
    "agregar_pregunta_final": True,
    "repetir_menu_despues_respuesta": False,
    "pie_volver_menu": "Escribe *menu* para ver las opciones otra vez.",
    "mensaje_no_entendido": (
        "No entendí tu mensaje. Puedes escribir el número de una opción "
        "o contarme qué deseas saber."
    ),
    "mensaje_sin_informacion": (
        "No tengo esa información confirmada en este momento. "
        "Dejé tu consulta pendiente para revisión y puedo seguir ayudándote "
        "con otras preguntas."
    ),
    "mensaje_escalamiento_sin_bloqueo": (
        "Dejé tu consulta marcada para que un asesor la revise. "
        "Mientras tanto, puedo seguir respondiendo tus preguntas."
    ),
    "mensaje_modo_humano": (
        "Recibí tu mensaje. Un asesor está atendiendo esta conversación "
        "y te responderá por aquí."
    ),
}

# Frases que solo piden remostrar el menú (sin buscar FAQ / IA).
_COMANDOS_VOLVER_MENU = frozenset(
    {
        "menu",
        "menú",
        "menus",
        "inicio",
        "opciones",
        "opcion",
        "opción",
        "volver",
        "atras",
        "atrás",
        "regresar",
        "hola",
        "buenas",
        "hey",
        "hi",
        "hello",
        "holi",
        "info",
    }
)
_PATRONES_VOLVER_MENU = (
    "menu anterior",
    "menú anterior",
    "volver al menu",
    "volver al menú",
    "volver menu",
    "ver menu",
    "ver menú",
    "mostrar menu",
    "mostrar menú",
    "otra opcion",
    "otra opción",
    "otras opciones",
)

INTENCIONES_INFORMATIVAS_IA = frozenset(
    {
        "requisitos",
        "beneficios",
        "bonos",
        "agencia",
        "proceso",
        "asesor",
        "faq",
        "desconocida",
    }
)


def _normalizar(texto: str) -> str:
    valor = str(texto or "").strip().lower()
    valor = unicodedata.normalize("NFD", valor)
    valor = "".join(ch for ch in valor if unicodedata.category(ch) != "Mn")
    valor = re.sub(r"[^\w\s]", " ", valor, flags=re.UNICODE)
    return re.sub(r"\s+", " ", valor).strip()


def es_comando_volver_menu(texto: str) -> bool:
    """True si el usuario solo pide remostrar el menú / elegir otra opción."""
    n = _normalizar(texto)
    if not n:
        return False
    if n in _COMANDOS_VOLVER_MENU:
        return True
    return any(p in n for p in _PATRONES_VOLVER_MENU)


def _pie_volver_menu(presentacion: Optional[Dict[str, Any]]) -> str:
    p = presentacion or {}
    return str(
        p.get("pie_volver_menu") or DEFAULTS_PRESENTACION["pie_volver_menu"]
    ).strip()


def _con_pie_menu(respuesta: str, presentacion: Optional[Dict[str, Any]]) -> str:
    cuerpo = str(respuesta or "").strip()
    if not cuerpo:
        return cuerpo
    pie = _pie_volver_menu(presentacion)
    if not pie:
        return cuerpo
    if "escribe *menu*" in cuerpo.lower() or "escribe menu" in _normalizar(cuerpo):
        return cuerpo
    return f"{cuerpo}\n\n{pie}"


def _vigente(registro: Dict[str, Any], hoy: Optional[date] = None) -> bool:
    if registro.get("activo") is False:
        return False
    referencia = hoy or date.today()
    for clave_desde, clave_hasta in (
        ("vigencia_desde", "vigencia_hasta"),
        ("fecha_inicio", "fecha_fin"),
    ):
        desde = registro.get(clave_desde)
        hasta = registro.get(clave_hasta)
        if isinstance(desde, datetime):
            desde = desde.date()
        if isinstance(hasta, datetime):
            hasta = hasta.date()
        if isinstance(desde, date) and referencia < desde:
            return False
        if isinstance(hasta, date) and referencia > hasta:
            return False
    return True


def presentacion_desde_asistente(asistente: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    a = asistente or {}
    out = dict(DEFAULTS_PRESENTACION)
    for clave in DEFAULTS_PRESENTACION:
        if a.get(clave) is not None and str(a.get(clave)).strip() != "":
            out[clave] = a[clave]
    try:
        out["max_elementos_respuesta"] = max(
            1, min(20, int(out.get("max_elementos_respuesta") or 8))
        )
    except (TypeError, ValueError):
        out["max_elementos_respuesta"] = 8
    formato = str(out.get("formato_respuestas_informativas") or "lista").lower()
    if formato not in {"lista", "texto_breve", "automatico"}:
        formato = "lista"
    out["formato_respuestas_informativas"] = formato
    return out


def ordenar_opciones_menu(opciones: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        [o for o in (opciones or []) if o and o.get("activo") is not False],
        key=lambda o: (int(o.get("orden") or 0), int(o.get("numero") or 0), int(o.get("id") or 0)),
    )


def numerar_opciones_activas(opciones: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Asigna número visible 1..N solo a opciones activas, en orden de menú.

    Así, si se deshabilitan opciones intermedias, el menú no muestra huecos
    (p. ej. 1,2,3,5,7) y la respuesta del usuario coincide con lo listado.
    """
    out: List[Dict[str, Any]] = []
    for idx, op in enumerate(ordenar_opciones_menu(opciones), start=1):
        copia = dict(op)
        copia["numero_visible"] = idx
        out.append(copia)
    return out


def construir_texto_menu(
    *,
    nombre_agencia: str,
    opciones: List[Dict[str, Any]],
    presentacion: Optional[Dict[str, Any]] = None,
    presentacion_inicial: Optional[str] = None,
) -> str:
    p = presentacion_desde_asistente(presentacion)
    encabezado = str(presentacion_inicial or "").strip()
    if not encabezado:
        encabezado = f"¡Hola! 👋 Bienvenido(a) a {nombre_agencia or 'la agencia'}."

    lineas = [
        encabezado,
        "",
        str(p.get("titulo_menu_inicial") or DEFAULTS_PRESENTACION["titulo_menu_inicial"]),
        "",
    ]
    for op in numerar_opciones_activas(opciones):
        titulo = str(op.get("titulo") or "").strip()
        if not titulo:
            continue
        lineas.append(f"{int(op['numero_visible'])}. {titulo}")
    lineas.append("")
    lineas.append(
        str(p.get("texto_indicacion_menu") or DEFAULTS_PRESENTACION["texto_indicacion_menu"])
    )
    return "\n".join(lineas)


def extraer_numero_opcion(texto: str) -> Optional[int]:
    n = _normalizar(texto)
    if not n:
        return None
    if n.isdigit():
        return int(n)
    m = re.match(r"^(?:opcion|opción|opc)\s*(\d{1,2})$", n)
    if m:
        return int(m.group(1))
    m = re.match(r"^(\d{1,2})[\).\-\s]", n)
    if m:
        return int(m.group(1))
    if n in NUMEROS_TEXTO:
        return NUMEROS_TEXTO[n]
    return None


def resolver_opcion_menu(
    texto: str,
    opciones: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Retorna (opcion|None, modo) donde modo ∈ {numero, texto, invalido, ninguna}.

    El número del usuario se interpreta como el número visible del menú (1..N
    de opciones activas), no como el campo fijo `numero` en base de datos.
    """
    activas = numerar_opciones_activas(opciones)
    numero = extraer_numero_opcion(texto)
    if numero is not None:
        for op in activas:
            if int(op.get("numero_visible") or 0) == int(numero):
                return op, "numero"
        return None, "invalido"

    n = _normalizar(texto)
    if not n:
        return None, "ninguna"

    # Coincidencia por codigo / titulo / intencion
    for op in activas:
        candidatos = [
            _normalizar(str(op.get("codigo") or "")),
            _normalizar(str(op.get("titulo") or "")),
            _normalizar(str(op.get("intencion") or "")),
            _normalizar(str(op.get("descripcion") or "")),
        ]
        for c in candidatos:
            if c and (c == n or c in n or n in c):
                return op, "texto"

    # Palabras clave por intención conocida
    mapa = {
        "requisitos": ("requisito", "requisitos"),
        "beneficios": ("beneficio", "beneficios"),
        "bonos": ("bono", "bonos", "incentivo", "incentivos"),
        "monetizacion": ("monetizacion", "monetización", "live", "lives"),
        "agencia": ("agencia", "funcionamiento", "como funciona"),
        "proceso": ("proceso", "continuar", "solicitud", "unirme"),
        "asesor": ("asesor", "humano", "persona", "agente", "manager"),
    }
    for op in activas:
        intencion = _normalizar(str(op.get("intencion") or op.get("codigo") or ""))
        claves = mapa.get(intencion, ())
        if any(k in n for k in claves):
            return op, "texto"
        # título contiene palabra del usuario
        titulo = _normalizar(str(op.get("titulo") or ""))
        if titulo and any(tok in titulo for tok in n.split() if len(tok) > 3):
            return op, "texto"

    return None, "ninguna"


def _limitar(items: List[str], maximo: int) -> List[str]:
    return items[: max(1, int(maximo or 8))]


def _es_pregunta(texto: str) -> bool:
    t = str(texto or "").strip()
    if not t:
        return False
    if t.startswith("¿") or t.endswith("?"):
        return True
    n = _normalizar(t)
    return n.startswith(
        ("eres ", "tienes ", "puedes ", "cuentas ", "dispones ", "quieres ")
    )


def _limpiar_frase_requisito(texto: str) -> str:
    """Deja una frase corta y afirmativa para listar en WhatsApp."""
    t = re.sub(r"\s+", " ", str(texto or "").strip())
    t = re.sub(
        r"^(la persona debe|se requiere|es necesario|necesitas|debes)\s+",
        "",
        t,
        flags=re.IGNORECASE,
    )
    # Quita emojis/viñetas sueltos al inicio (la marca ✅ ya aporta el acento).
    t = re.sub(r"^[\W_🚀✅✔️☑️●•\-]+\s*", "", t)
    if not t:
        return ""
    if t[0].islower():
        t = t[0].upper() + t[1:]
    if t[-1] not in ".!…":
        t = f"{t}."
    return t


def _texto_item_requisito(requisito: Dict[str, Any]) -> Optional[str]:
    """
    Prioriza descripción afirmativa; si la descripción es pregunta (estilo
    formulario), usa el nombre. Evita el formato 'Nombre: ¿pregunta?'.
    """
    nombre = str(requisito.get("nombre") or "").strip()
    desc = str(
        requisito.get("descripcion") or requisito.get("valor_texto") or ""
    ).strip()

    if desc and not _es_pregunta(desc):
        return _limpiar_frase_requisito(desc)
    if nombre:
        return _limpiar_frase_requisito(nombre)
    if desc:
        return _limpiar_frase_requisito(desc)
    return None


def _tema_requisito(texto: str) -> Optional[str]:
    """Agrupa requisitos equivalentes para no repetirlos en el menú."""
    n = _normalizar(texto)
    if any(k in n for k in ("18", "edad", "mayor de edad", "mayoria de edad")):
        return "edad"
    if "hora" in n and ("dia" in n or "diaria" in n):
        return "horas_dia"
    if "semana" in n or "varios dia" in n:
        return "semana"
    if any(k in n for k in ("telefono", "celular", "conexion", "internet")):
        return "equipo"
    if any(k in n for k in ("hablador", "convers", "interact", "comunicativ", "audiencia")):
        return "comunicacion"
    if any(k in n for k in ("energia", "camara", "actitud", "entretenid")):
        return "energia"
    return None


def _deduplicar_frases(items: List[str]) -> List[str]:
    """Evita listar dos veces el mismo requisito (p. ej. edad duplicada)."""
    out: List[str] = []
    vistos: List[str] = []
    tema_idx: Dict[str, int] = {}
    for item in items:
        clave = _normalizar(item)
        if not clave:
            continue
        tema = _tema_requisito(item)
        if tema is not None and tema in tema_idx:
            idx = tema_idx[tema]
            # Conserva la frase más clara/completa del mismo tema.
            if len(item) > len(out[idx]):
                out[idx] = item
                vistos[idx] = clave
            continue
        if any(clave in v or v in clave for v in vistos):
            continue
        if tema is not None:
            tema_idx[tema] = len(out)
        out.append(item)
        vistos.append(clave)
    return out


def formatear_lista(
    items: List[str],
    *,
    formato: str,
    titulo: Optional[str] = None,
    mostrar_titulo: bool = True,
    numerada: bool = False,
    pregunta_final: Optional[str] = None,
    max_elementos: int = 8,
    introduccion: Optional[str] = None,
    vineta: str = "-",
) -> str:
    utiles = [str(i).strip() for i in items if str(i or "").strip()]
    utiles = _limitar(utiles, max_elementos)
    if not utiles:
        return ""

    usar_lista = formato == "lista" or (
        formato == "automatico" and len(utiles) >= 3
    )
    lineas: List[str] = []
    if mostrar_titulo and titulo:
        lineas.append(str(titulo).strip())
        lineas.append("")
    if introduccion:
        lineas.append(str(introduccion).strip())
        lineas.append("")

    if usar_lista:
        marca = str(vineta or "-").strip() or "-"
        for idx, item in enumerate(utiles, start=1):
            if numerada:
                lineas.append(f"{idx}. {item}")
            else:
                lineas.append(f"{marca} {item}")
    else:
        # texto_breve: máximo dos párrafos
        if len(utiles) == 1:
            lineas.append(utiles[0])
        else:
            mitad = max(1, len(utiles) // 2)
            lineas.append(" ".join(utiles[:mitad]))
            lineas.append("")
            lineas.append(" ".join(utiles[mitad:]))

    if pregunta_final:
        lineas.append("")
        lineas.append(pregunta_final)
    return "\n".join(lineas).strip()


def clasificar_intencion_informativa_semantica(
    texto: str,
    *,
    modelo: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Clasificación semántica restringida vía IA.

    Solo devuelve JSON con intencion, consulta_reformulada y confianza.
    No clasifica aspirantes ni activa modo humano.
    """
    texto_in = str(texto or "").strip()
    fallback = {
        "intencion": "desconocida",
        "consulta_reformulada": texto_in,
        "confianza": 0.0,
    }
    if not texto_in:
        return fallback

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not str(api_key).strip():
        return fallback

    prompt_sistema = (
        "Clasificador del chatbot informativo de captación LIVE. "
        "Responde SOLO con JSON válido, sin markdown ni texto extra. "
        'Formato: {"intencion":"...","consulta_reformulada":"...","confianza":0.0}. '
        "intencion debe ser exactamente una de: "
        "requisitos, beneficios, bonos, agencia, proceso, asesor, faq, desconocida. "
        "No inventes datos de la agencia. No clasifiques nivel del aspirante."
    )
    prompt_usuario = f"Mensaje del usuario: {texto_in}"

    try:
        from openai import OpenAI

        client = OpenAI(api_key=str(api_key).strip())
        respuesta = client.chat.completions.create(
            model=modelo or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario},
            ],
        )
        contenido = (respuesta.choices[0].message.content or "").strip()
        datos = json.loads(contenido) if contenido else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CHATBOT_MENU] clasificación IA falló: %s", exc)
        return fallback

    intencion = _normalizar(str(datos.get("intencion") or "desconocida"))
    if intencion not in INTENCIONES_INFORMATIVAS_IA:
        intencion = "desconocida"
    consulta = str(datos.get("consulta_reformulada") or texto_in).strip() or texto_in
    try:
        confianza = float(datos.get("confianza") or 0.0)
    except (TypeError, ValueError):
        confianza = 0.0
    confianza = max(0.0, min(1.0, confianza))
    return {
        "intencion": intencion,
        "consulta_reformulada": consulta,
        "confianza": confianza,
    }


def construir_respuesta_por_intencion_informativa(
    intencion: str,
    *,
    agencia_id: int,
    chatbot_configuracion_id: int,
    presentacion: Dict[str, Any],
    texto_consulta: str,
    db_conv: Any,
) -> Tuple[str, bool]:
    """
    Construye respuesta SOLO desde tablas autorizadas según intención.
    Retorna (texto, requiere_asesor).
    """
    intencion_n = _normalizar(intencion)
    requiere_asesor = False

    if intencion_n == "asesor":
        return (
            str(
                presentacion.get("mensaje_escalamiento_sin_bloqueo")
                or DEFAULTS_PRESENTACION["mensaje_escalamiento_sin_bloqueo"]
            ),
            True,
        )

    if intencion_n == "requisitos":
        reqs = db_conv.listar_requisitos(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            solo_activos=True,
        )
        reqs = sorted(reqs or [], key=lambda r: int(r.get("orden") or 0))
        texto = construir_respuesta_requisitos(reqs, presentacion)
        return texto, not bool(texto)

    if intencion_n == "beneficios":
        bens = db_conv.listar_beneficios(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            solo_activos=True,
        )
        texto = construir_respuesta_beneficios(
            bens or [],
            presentacion,
            tipos=("beneficio", "capacitacion", "acompanamiento", "otro"),
            titulo="Beneficios de pertenecer a la agencia",
        )
        return texto, not bool(texto)

    if intencion_n == "bonos":
        bens = db_conv.listar_beneficios(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            solo_activos=True,
        )
        texto = construir_respuesta_beneficios(
            bens or [],
            presentacion,
            tipos=("bono", "incentivo"),
            titulo="Bonos e incentivos",
        )
        return texto, not bool(texto)

    if intencion_n in {"agencia", "proceso", "faq"}:
        faqs = db_conv.listar_faqs(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            solo_activos=True,
        )
        intencion_faq = None if intencion_n == "faq" else intencion_n
        texto = _buscar_faq(faqs or [], intencion_faq, texto_consulta)
        return texto, not bool(texto)

    return "", True


def construir_respuesta_requisitos(
    requisitos: List[Dict[str, Any]],
    presentacion: Dict[str, Any],
) -> str:
    items: List[str] = []
    for r in requisitos:
        if not _vigente(r):
            continue
        if r.get("permitir_mencion_automatica") is False:
            continue
        frase = _texto_item_requisito(r)
        if frase:
            items.append(frase)

    items = _deduplicar_frases(items)
    pregunta = (
        "Si quieres, puedo explicarte cualquiera de estos requisitos."
        if presentacion.get("agregar_pregunta_final")
        else None
    )
    # En informativo los requisitos siempre van como lista limpia con ✅,
    # aunque el formato general sea texto_breve.
    return formatear_lista(
        items,
        formato="lista",
        titulo=(
            "Requisitos para ser creador LIVE 🎥"
            if presentacion.get("mostrar_titulo_respuesta")
            else None
        ),
        mostrar_titulo=bool(presentacion.get("mostrar_titulo_respuesta")),
        numerada=False,
        introduccion="Para formar parte de la agencia necesitas:",
        vineta="✅",
        pregunta_final=pregunta,
        max_elementos=int(presentacion.get("max_elementos_respuesta") or 8),
    )


def construir_respuesta_beneficios(
    beneficios: List[Dict[str, Any]],
    presentacion: Dict[str, Any],
    *,
    tipos: Tuple[str, ...],
    titulo: str,
) -> str:
    items = []
    for b in beneficios:
        if not _vigente(b):
            continue
        if b.get("permitir_mencion_automatica") is False:
            continue
        if b.get("visible_publicamente") is False:
            continue
        tipo = str(b.get("tipo") or "").lower()
        if tipos and tipo not in tipos:
            continue
        texto = (
            str(b.get("texto_autorizado") or "").strip()
            or str(b.get("descripcion_corta") or "").strip()
            or str(b.get("nombre") or "").strip()
        )
        if not texto:
            continue
        if b.get("requiere_validacion_humana"):
            texto = f"{texto} (sujeto a validación del equipo)"
        items.append(texto)
    pregunta = "¿Te gustaría conocer otra opción del menú?" if presentacion.get("agregar_pregunta_final") else None
    return formatear_lista(
        items,
        formato=presentacion.get("formato_respuestas_informativas") or "lista",
        titulo=titulo if presentacion.get("mostrar_titulo_respuesta") else None,
        mostrar_titulo=bool(presentacion.get("mostrar_titulo_respuesta")),
        numerada=False,
        pregunta_final=pregunta,
        max_elementos=int(presentacion.get("max_elementos_respuesta") or 8),
    )


def construir_respuesta_proceso(
    pasos: List[str],
    presentacion: Dict[str, Any],
) -> str:
    pregunta = "¿Quieres que te ayude con el siguiente paso?" if presentacion.get("agregar_pregunta_final") else None
    return formatear_lista(
        pasos,
        formato="lista",
        titulo="Cómo continuar con el proceso" if presentacion.get("mostrar_titulo_respuesta") else None,
        mostrar_titulo=bool(presentacion.get("mostrar_titulo_respuesta")),
        numerada=True,
        pregunta_final=pregunta,
        max_elementos=int(presentacion.get("max_elementos_respuesta") or 8),
    )


async def procesar_mensaje_informativo(
    *,
    agencia_id: int,
    chatbot_configuracion_id: int,
    conversacion_id: Optional[int],
    texto: str,
    canal: str = "whatsapp",
    dry_run: bool = False,
    enviar_callback=None,
    token: Optional[str] = None,
    phone_number_id: Optional[str] = None,
    destino: Optional[str] = None,
    aspirante_id: Optional[int] = None,
    mensaje_externo_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Procesa un mensaje del motor informativo y siempre intenta devolver
    una respuesta saliente visible.
    """
    import database_chatbot_captacion as db_cap
    import database_chatbot_conversacional as db_conv
    from service_chatbot_respuesta_obligatoria import garantizar_respuesta_saliente

    cfg = db_cap.obtener_configuracion_por_id(agencia_id, chatbot_configuracion_id)
    if not cfg:
        return {
            "usado": True,
            "motivo": "config_inexistente",
            "respuesta": DEFAULTS_PRESENTACION["mensaje_sin_informacion"],
            "respuesta_enviada": False,
        }

    asistente = db_conv.obtener_asistente_configuracion(
        agencia_id, chatbot_configuracion_id
    ) or {}
    presentacion = presentacion_desde_asistente(asistente)
    agencia = {}
    try:
        agencia = db_conv.obtener_agencia(agencia_id) or {}
    except Exception:
        try:
            agencia = db_cap.obtener_agencia_por_id(agencia_id) or {}
        except Exception:
            agencia = {"nombre": "la agencia"}

    opciones = []
    try:
        opciones = db_conv.listar_menu_informativo(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            solo_activas=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CHATBOT_MENU] no se pudo listar menú: %s", exc)

    if not opciones and not dry_run:
        try:
            db_conv.asegurar_menu_informativo_base(
                agencia_id,
                chatbot_configuracion_id,
            )
            opciones = db_conv.listar_menu_informativo(
                agencia_id,
                chatbot_configuracion_id=chatbot_configuracion_id,
                solo_activas=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CHATBOT_MENU] no se pudo sembrar menú: %s", exc)

    opciones = ordenar_opciones_menu(opciones)
    nombre_agencia = str(
        (agencia or {}).get("nombre")
        or (asistente or {}).get("nombre_asistente")
        or "la agencia"
    )
    texto_menu = construir_texto_menu(
        nombre_agencia=nombre_agencia,
        opciones=opciones,
        presentacion=presentacion,
        presentacion_inicial=(asistente or {}).get("presentacion_inicial"),
    )

    # Anti-duplicado: Meta puede reenviar el mismo webhook si tardamos.
    if mensaje_externo_id and not dry_run:
        try:
            if db_conv.mensaje_externo_ya_procesado(
                agencia_id, str(mensaje_externo_id), canal=canal
            ):
                logger.info(
                    "[CHATBOT_MENU] mensaje_duplicado mensaje_externo_id=%s "
                    "conversacion_id=%s",
                    mensaje_externo_id,
                    conversacion_id,
                )
                return {
                    "usado": True,
                    "motivo": "mensaje_duplicado",
                    "respuesta": None,
                    "respuesta_enviada": True,
                    "requiere_reintento": False,
                    "enlaces": [],
                }
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CHATBOT_MENU] dedup inbound falló: %s", exc)

    if conversacion_id and mensaje_externo_id and not dry_run:
        try:
            insertado = db_conv.insertar_mensaje(
                agencia_id,
                int(conversacion_id),
                canal=canal,
                direccion="entrante",
                remitente_tipo="usuario",
                tipo_mensaje="texto",
                texto=str(texto or "")[:4000],
                mensaje_externo_id=str(mensaje_externo_id),
                estado_envio="recibido",
                procesado_por_ia=False,
            )
            creado = True
            if isinstance(insertado, tuple) and len(insertado) > 1:
                creado = bool(insertado[1])
            if not creado:
                return {
                    "usado": True,
                    "motivo": "mensaje_duplicado",
                    "respuesta": None,
                    "respuesta_enviada": True,
                    "requiere_reintento": False,
                    "enlaces": [],
                }
        except Exception as exc:  # noqa: BLE001
            if db_conv.mensaje_externo_ya_procesado(
                agencia_id, str(mensaje_externo_id), canal=canal
            ):
                return {
                    "usado": True,
                    "motivo": "mensaje_duplicado",
                    "respuesta": None,
                    "respuesta_enviada": True,
                    "requiere_reintento": False,
                    "enlaces": [],
                }
            logger.warning("[CHATBOT_MENU] no se pudo insertar entrante: %s", exc)

    # Conversación / modo humano
    conversacion = None
    if conversacion_id:
        conversacion = db_conv.obtener_conversacion(agencia_id, conversacion_id)

    if conversacion and conversacion.get("modo_humano"):
        texto_resp = str(
            presentacion.get("mensaje_modo_humano")
            or DEFAULTS_PRESENTACION["mensaje_modo_humano"]
        )
        envio = await garantizar_respuesta_saliente(
            agencia_id=agencia_id,
            conversacion_id=conversacion_id,
            canal=canal,
            texto=texto_resp,
            dry_run=dry_run,
            enviar_callback=enviar_callback,
            token=token,
            phone_number_id=phone_number_id,
            destino=destino,
            motivo_fallback="modo_humano",
            mensaje_externo_id=mensaje_externo_id,
        )
        return {
            "usado": True,
            "motivo": None,
            "respuesta": texto_resp,
            "respuesta_enviada": bool(envio.get("enviado") is True) or dry_run,
            "modo_humano": True,
            "requiere_asesor": False,
            "enlaces": [],
        }

    # Menú inicial / volver al menú (menu, volver, menu anterior, otra opción…)
    texto_in = str(texto or "").strip()
    mostrar_menu = bool(presentacion.get("mostrar_menu_inicial", True))

    if (not texto_in or es_comando_volver_menu(texto_in)) and mostrar_menu and opciones:
        envio = await garantizar_respuesta_saliente(
            agencia_id=agencia_id,
            conversacion_id=conversacion_id,
            canal=canal,
            texto=texto_menu,
            dry_run=dry_run,
            enviar_callback=enviar_callback,
            token=token,
            phone_number_id=phone_number_id,
            destino=destino,
            motivo_fallback="menu_inicial",
            mensaje_externo_id=mensaje_externo_id,
        )
        logger.info(
            "[CHATBOT_MENU] conversacion_id=%s entrada=menu opcion=menu "
            "intencion=menu respuesta_enviada=%s",
            conversacion_id,
            bool(envio.get("enviado") or dry_run),
        )
        return {
            "usado": True,
            "respuesta": texto_menu,
            "respuesta_enviada": bool(envio.get("enviado") is True) or dry_run,
            "enlaces": [],
            "menu": True,
        }

    opcion, modo = resolver_opcion_menu(texto_in, opciones)
    requiere_asesor = False
    respuesta = ""
    intencion = "desconocida"

    if modo == "invalido":
        respuesta = (
            f"Esa opción no existe. Estas son las disponibles:\n\n{texto_menu}"
        )
        intencion = "menu"
    elif opcion:
        intencion = str(opcion.get("intencion") or opcion.get("codigo") or "info")
        tipo_fuente = str(opcion.get("tipo_fuente") or "faq").lower()
        if opcion.get("requiere_asesor"):
            requiere_asesor = True

        if tipo_fuente == "requisitos":
            reqs = db_conv.listar_requisitos(
                agencia_id,
                chatbot_configuracion_id=chatbot_configuracion_id,
                solo_activos=True,
            )
            # ordenar por orden
            reqs = sorted(reqs or [], key=lambda r: int(r.get("orden") or 0))
            respuesta = construir_respuesta_requisitos(reqs, presentacion)
        elif tipo_fuente == "beneficios":
            bens = db_conv.listar_beneficios(
                agencia_id,
                chatbot_configuracion_id=chatbot_configuracion_id,
                solo_activos=True,
            )
            respuesta = construir_respuesta_beneficios(
                bens or [],
                presentacion,
                tipos=("beneficio", "capacitacion", "acompanamiento", "otro"),
                titulo="Beneficios de pertenecer a la agencia",
            )
        elif tipo_fuente == "bonos":
            bens = db_conv.listar_beneficios(
                agencia_id,
                chatbot_configuracion_id=chatbot_configuracion_id,
                solo_activos=True,
            )
            respuesta = construir_respuesta_beneficios(
                bens or [],
                presentacion,
                tipos=("bono", "incentivo"),
                titulo="Bonos e incentivos",
            )
        elif tipo_fuente == "texto":
            respuesta = str(opcion.get("respuesta_personalizada") or "").strip()
        elif tipo_fuente == "asesor":
            requiere_asesor = True
            respuesta = str(
                presentacion.get("mensaje_escalamiento_sin_bloqueo")
                or DEFAULTS_PRESENTACION["mensaje_escalamiento_sin_bloqueo"]
            )
        else:  # faq
            faqs = db_conv.listar_faqs(
                agencia_id,
                chatbot_configuracion_id=chatbot_configuracion_id,
                solo_activos=True,
            )
            respuesta = _buscar_faq(faqs or [], intencion, texto_in)

        if not respuesta:
            respuesta = str(
                presentacion.get("mensaje_sin_informacion")
                or DEFAULTS_PRESENTACION["mensaje_sin_informacion"]
            )
            requiere_asesor = True

        if presentacion.get("repetir_menu_despues_respuesta") and opciones:
            respuesta = f"{respuesta}\n\n{texto_menu}"
    else:
        # Intento FAQ libre
        faqs = []
        try:
            faqs = db_conv.listar_faqs(
                agencia_id,
                chatbot_configuracion_id=chatbot_configuracion_id,
                solo_activos=True,
            )
        except Exception:
            faqs = []
        respuesta = _buscar_faq(faqs or [], None, texto_in)
        if respuesta:
            intencion = "faq"
            modo = "texto"
        else:
            clasif = clasificar_intencion_informativa_semantica(texto_in)
            intencion = str(clasif.get("intencion") or "desconocida")
            consulta = str(clasif.get("consulta_reformulada") or texto_in)
            respuesta, req_ia = construir_respuesta_por_intencion_informativa(
                intencion,
                agencia_id=agencia_id,
                chatbot_configuracion_id=chatbot_configuracion_id,
                presentacion=presentacion,
                texto_consulta=consulta,
                db_conv=db_conv,
            )
            requiere_asesor = req_ia or intencion == "desconocida"
            modo = "semantica"
            if not respuesta:
                respuesta = str(
                    presentacion.get("mensaje_sin_informacion")
                    or presentacion.get("mensaje_no_entendido")
                    or DEFAULTS_PRESENTACION["mensaje_sin_informacion"]
                )
            if intencion == "desconocida" and conversacion_id and not dry_run:
                try:
                    db_conv.actualizar_conversacion(
                        agencia_id,
                        int(conversacion_id),
                        {"ia_habilitada": True},
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[CHATBOT_MENU] no se pudo marcar ia_habilitada: %s", exc
                    )
            if opciones and intencion == "desconocida":
                respuesta = f"{respuesta}\n\n{texto_menu}"

    if requiere_asesor and aspirante_id and not dry_run:
        try:
            db_cap.actualizar_aspirante_admin(
                agencia_id, int(aspirante_id), requiere_asesor=True
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CHATBOT_MENU] no se pudo marcar requiere_asesor: %s", exc)

    # Pie corto para volver al menú (si la respuesta no es ya el menú completo).
    if respuesta and texto_menu and texto_menu not in respuesta:
        respuesta = _con_pie_menu(respuesta, presentacion)

    # Nunca modo_humano por falta de info
    envio = await garantizar_respuesta_saliente(
        agencia_id=agencia_id,
        conversacion_id=conversacion_id,
        canal=canal,
        texto=respuesta,
        dry_run=dry_run,
        enviar_callback=enviar_callback,
        token=token,
        phone_number_id=phone_number_id,
        destino=destino,
        motivo_fallback="informativo",
        mensaje_externo_id=mensaje_externo_id,
    )

    logger.info(
        "[CHATBOT_MENU] conversacion_id=%s entrada=%s opcion=%s "
        "intencion=%s respuesta_enviada=%s",
        conversacion_id,
        modo,
        (opcion or {}).get("numero"),
        intencion,
        bool(envio.get("enviado") or dry_run),
    )
    logger.info(
        "[CHATBOT_TIPO] agencia_id=%s chatbot_configuracion_id=%s "
        "tipo_chatbot=informativo canal=%s",
        agencia_id,
        chatbot_configuracion_id,
        canal,
    )

    return {
        "usado": True,
        "motivo": None,
        "respuesta": respuesta,
        "respuesta_enviada": bool(envio.get("enviado") is True) or dry_run,
        "requiere_asesor": requiere_asesor,
        "modo_humano": False,
        "enlaces": [],
        "opcion": opcion,
        "intencion": intencion,
    }


def _buscar_faq(
    faqs: List[Dict[str, Any]],
    intencion: Optional[str],
    texto: str,
) -> str:
    n = _normalizar(texto)
    intencion_n = _normalizar(intencion or "")
    mejores: List[Tuple[int, Dict[str, Any]]] = []
    for faq in faqs:
        if not _vigente(faq):
            continue
        score = 0
        fi = _normalizar(str(faq.get("intencion") or ""))
        if intencion_n and fi == intencion_n:
            score += 5
        pregunta = _normalizar(str(faq.get("pregunta") or ""))
        if pregunta and (pregunta in n or n in pregunta):
            score += 4
        claves = faq.get("palabras_clave") or []
        if isinstance(claves, str):
            claves = [c.strip() for c in claves.split(",") if c.strip()]
        for c in claves:
            cn = _normalizar(str(c))
            if cn and cn in n:
                score += 2
        if score:
            mejores.append((score, faq))
    if not mejores:
        # Si hay intención, tomar FAQ de esa intención
        if intencion_n:
            for faq in faqs:
                if _normalizar(str(faq.get("intencion") or "")) == intencion_n and _vigente(faq):
                    return str(
                        faq.get("respuesta_completa")
                        or faq.get("respuesta_corta")
                        or ""
                    ).strip()
        return ""
    mejores.sort(key=lambda x: (-x[0], -int((x[1].get("prioridad") or 0))))
    faq = mejores[0][1]
    return str(faq.get("respuesta_completa") or faq.get("respuesta_corta") or "").strip()
