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
    "titulo_menu_retorno": "Menú",
    "texto_indicacion_menu": (
        "Escribe el número de una opción o pregúntame directamente lo que quieras saber."
    ),
    "texto_indicacion_menu_retorno": (
        "Escribe un número o hazme directamente tu pregunta."
    ),
    "formato_respuestas_informativas": "lista",
    "max_elementos_respuesta": 15,
    "mostrar_titulo_respuesta": True,
    "agregar_pregunta_final": True,
    "repetir_menu_despues_respuesta": False,
    "pie_volver_menu": "Puedes escribir *menu* cuando quieras ver las opciones.",
    "mensaje_hola_de_nuevo": "¡Hola de nuevo! 👋 ¿En qué puedo ayudarte?",
    "mensaje_no_entendido": (
        "No entendí tu mensaje. Puedes escribir el número de una opción "
        "o preguntarme algo concreto sobre la agencia."
    ),
    "mensaje_sin_informacion": (
        "No tengo información confirmada sobre ese tema. "
        "Puedes preguntarme otra cosa o escribir *asesor* si quieres "
        "que el equipo lo revise contigo."
    ),
    "mensaje_escalamiento_sin_bloqueo": (
        "Dejé tu consulta marcada para que un asesor la revise. "
        "Mientras tanto, puedo seguir respondiendo tus preguntas."
    ),
    "mensaje_modo_humano": (
        "Recibí tu mensaje. Un asesor está atendiendo esta conversación "
        "y te responderá por aquí."
    ),
    "mensaje_pedir_otra_pregunta": (
        "Claro. ¿Qué quieres saber?\n\n"
        "Escríbeme tu pregunta y te respondo con la información disponible."
    ),
    "mensaje_faq_no_encontrada": (
        "No tengo información confirmada sobre ese tema. "
        "Puedes preguntarme otra cosa o escribir *asesor* si quieres "
        "que el equipo lo revise contigo."
    ),
    "mensaje_opcion_no_valida": (
        "Esa no es una opción válida del menú.\n\n"
        "Escribe el *número* de una opción, *menu* para verlas otra vez "
        "o pregúntame directamente lo que quieras saber."
    ),
}

# Solo piden remostrar el menú (sin bienvenida).
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
    "ver opciones",
    "mostrar menu",
    "mostrar menú",
    "otra opcion",
    "otra opción",
    "otras opciones",
)

# Saludos puros (no equivalen automáticamente a menú de retorno).
_COMANDOS_SALUDO = frozenset(
    {
        "hola",
        "buenas",
        "hey",
        "hi",
        "hello",
        "holi",
        "buenas tardes",
        "buenas noches",
        "buen dia",
        "buen día",
        "buenos dias",
        "buenos días",
    }
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
    """True si el usuario solo pide remostrar el menú (sin saludo)."""
    n = _normalizar(texto)
    if not n:
        return False
    if n in _COMANDOS_VOLVER_MENU:
        return True
    return any(p in n for p in _PATRONES_VOLVER_MENU)


def es_comando_saludo(texto: str) -> bool:
    """True si el mensaje es solo un saludo (hola / buenas / …)."""
    n = _normalizar(texto)
    if not n:
        return False
    if n in _COMANDOS_SALUDO:
        return True
    partes = n.split()
    if len(partes) <= 3 and partes[0] in {"buenas", "buen", "buenos"}:
        return True
    return False


def es_comando_menu_o_saludo(texto: str) -> bool:
    return es_comando_volver_menu(texto) or es_comando_saludo(texto)


def _pie_volver_menu(presentacion: Optional[Dict[str, Any]]) -> str:
    """Pie opcional; el aviso de *menu* redundante se omite siempre."""
    p = presentacion or {}
    pie = str(
        p.get("pie_volver_menu")
        if p.get("pie_volver_menu") is not None
        else DEFAULTS_PRESENTACION["pie_volver_menu"]
    ).strip()
    if not pie:
        return ""
    n = _normalizar(pie)
    # Omite solo el pie antiguo redundante ("…opciones otra vez").
    if "escribe menu" in n and "opciones otra vez" in n:
        return str(DEFAULTS_PRESENTACION["pie_volver_menu"] or "").strip()
    return pie


def _ya_indica_volver_menu(texto: str) -> bool:
    """True si el cuerpo ya explica cómo volver al menú (evita duplicar el pie)."""
    n = _normalizar(texto)
    if not n:
        return False
    if "escribe menu" in n:
        return True
    if "volver al menu" in n or "ver el menu" in n or "ver las opciones" in n:
        return True
    if "o menu" in n and "menu" in n:
        return True
    return False


def _con_pie_menu(respuesta: str, presentacion: Optional[Dict[str, Any]]) -> str:
    cuerpo = str(respuesta or "").strip()
    if not cuerpo:
        return cuerpo
    pie = _pie_volver_menu(presentacion)
    if not pie:
        return cuerpo
    if _ya_indica_volver_menu(cuerpo):
        return cuerpo
    return f"{cuerpo}\n\n{pie}"


def _linea_lista_numerada(numero: int, texto: str) -> str:
    """Formato unificado de menús/listas: 1. ✅ Título"""
    titulo = str(texto or "").strip()
    return f"{int(numero)}. ✅ {titulo}"


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
            1, min(20, int(out.get("max_elementos_respuesta") or 15))
        )
    except (TypeError, ValueError):
        out["max_elementos_respuesta"] = 15
    formato = str(out.get("formato_respuestas_informativas") or "lista").lower()
    if formato not in {"lista", "texto_breve", "automatico"}:
        formato = "lista"
    out["formato_respuestas_informativas"] = formato

    # Contexto de agencia para "Cómo funciona" y similares.
    if a.get("descripcion_agencia") is not None:
        out["descripcion_agencia"] = a.get("descripcion_agencia")

    # Indicación del menú: solo la primera frase (sin el recordatorio de *menu*).
    indicacion = str(out.get("texto_indicacion_menu") or "").strip()
    if indicacion:
        for sep in (". ", "! ", "? "):
            if sep in indicacion[:-1]:
                indicacion = indicacion.split(sep, 1)[0].rstrip(".") + "."
                break
        n_ind = _normalizar(indicacion)
        if "escribe menu" in n_ind:
            indicacion = DEFAULTS_PRESENTACION["texto_indicacion_menu"]
        out["texto_indicacion_menu"] = indicacion

    # Nunca reinyectar el pie largo redundante antiguo.
    pie = str(out.get("pie_volver_menu") or "").strip()
    n_pie = _normalizar(pie)
    if pie and "escribe menu" in n_pie and "opciones otra vez" in n_pie:
        out["pie_volver_menu"] = DEFAULTS_PRESENTACION["pie_volver_menu"]
    elif pie and n_pie in {
        "escribe menu para volver al menu",
        "escribe menu para volver al menu.",
    }:
        out["pie_volver_menu"] = DEFAULTS_PRESENTACION["pie_volver_menu"]
    elif not pie:
        out["pie_volver_menu"] = DEFAULTS_PRESENTACION["pie_volver_menu"]
    return out


def _opcion_otras_preguntas_sintetica(
    opciones: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Opción en memoria si la BD aún no la tiene (p. ej. check constraint viejo)."""
    asesor = next(
        (
            o
            for o in (opciones or [])
            if _normalizar(str(o.get("codigo") or "")) == "asesor"
        ),
        None,
    )
    numero = int((asesor or {}).get("numero") or 0) or (
        max((int(o.get("numero") or 0) for o in (opciones or [])), default=0) + 1
    )
    orden = int((asesor or {}).get("orden") or 0) or (
        max((int(o.get("orden") or 0) for o in (opciones or [])), default=0) + 1
    )
    return {
        "id": None,
        "numero": numero,
        "codigo": "otras_preguntas",
        "titulo": "Otras preguntas",
        "descripcion": "Haz una pregunta que no esté en el menú.",
        "intencion": "faq",
        "tipo_fuente": "faq",
        "requiere_asesor": False,
        "orden": orden,
        "activo": True,
        "_sintetica": True,
    }


def garantizar_opcion_otras_preguntas(
    opciones: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Asegura que el listado usado para el menú incluya Otras preguntas."""
    lista = [dict(o) for o in (opciones or []) if o]
    if any(_normalizar(str(o.get("codigo") or "")) == "otras_preguntas" for o in lista):
        return lista
    sintetica = _opcion_otras_preguntas_sintetica(lista)
    asesor_idx = next(
        (
            i
            for i, o in enumerate(lista)
            if _normalizar(str(o.get("codigo") or "")) == "asesor"
        ),
        None,
    )
    if asesor_idx is None:
        lista.append(sintetica)
    else:
        asesor = lista[asesor_idx]
        asesor["numero"] = int(asesor.get("numero") or sintetica["numero"]) + 1
        asesor["orden"] = int(asesor.get("orden") or sintetica["orden"]) + 1
        lista.insert(asesor_idx, sintetica)
    return lista


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


def _lineas_opciones_menu(opciones: List[Dict[str, Any]]) -> List[str]:
    """Única fuente de numeración visible 1..N para menú inicial y de retorno."""
    lineas: List[str] = []
    for op in numerar_opciones_activas(opciones):
        titulo = _titulo_opcion_menu_corta(str(op.get("titulo") or "").strip())
        if not titulo:
            continue
        lineas.append(_linea_lista_numerada(int(op["numero_visible"]), titulo))
    return lineas


def construir_menu_inicial(
    *,
    nombre_agencia: str,
    opciones: List[Dict[str, Any]],
    presentacion: Optional[Dict[str, Any]] = None,
    presentacion_inicial: Optional[str] = None,
) -> str:
    """Bienvenida + opciones (solo primer contacto de la conversación)."""
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
    lineas.extend(_lineas_opciones_menu(opciones))
    lineas.append("")
    lineas.append(
        str(p.get("texto_indicacion_menu") or DEFAULTS_PRESENTACION["texto_indicacion_menu"])
    )
    return "\n".join(lineas)


def construir_menu_retorno(
    *,
    opciones: List[Dict[str, Any]],
    presentacion: Optional[Dict[str, Any]] = None,
    prefijo: Optional[str] = None,
) -> str:
    """Menú corto sin bienvenida (cuando el usuario pide menu/volver/opciones)."""
    p = presentacion_desde_asistente(presentacion)
    titulo = str(
        prefijo
        or p.get("titulo_menu_retorno")
        or DEFAULTS_PRESENTACION["titulo_menu_retorno"]
    ).strip() or "Menú"
    lineas = [titulo, ""]
    lineas.extend(_lineas_opciones_menu(opciones))
    lineas.append("")
    lineas.append(
        str(
            p.get("texto_indicacion_menu_retorno")
            or DEFAULTS_PRESENTACION["texto_indicacion_menu_retorno"]
        )
    )
    return "\n".join(lineas)


def construir_texto_menu(
    *,
    nombre_agencia: str,
    opciones: List[Dict[str, Any]],
    presentacion: Optional[Dict[str, Any]] = None,
    presentacion_inicial: Optional[str] = None,
    incluir_bienvenida: bool = True,
) -> str:
    """
    Compat: por defecto construye el menú inicial (con bienvenida).
    Con incluir_bienvenida=False → menú de retorno.
    """
    if incluir_bienvenida:
        return construir_menu_inicial(
            nombre_agencia=nombre_agencia,
            opciones=opciones,
            presentacion=presentacion,
            presentacion_inicial=presentacion_inicial,
        )
    return construir_menu_retorno(opciones=opciones, presentacion=presentacion)


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


_STOPWORDS_MENU = frozenset(
    {
        "como",
        "que",
        "cual",
        "cuales",
        "cuando",
        "donde",
        "porque",
        "para",
        "por",
        "con",
        "sin",
        "una",
        "unos",
        "unas",
        "sobre",
        "esta",
        "este",
        "esto",
        "tiene",
        "tienen",
        "puedo",
        "puede",
        "quiero",
        "saber",
        "dime",
        "explica",
        "explicame",
        "es",
        "la",
        "el",
        "los",
        "las",
        "de",
        "del",
        "se",
        "me",
        "te",
        "mi",
        "tu",
        "su",
        "al",
        "lo",
        "hay",
        "son",
        "mas",
        "muy",
        "the",
        "and",
    }
)


def _tokens_menu_utiles(texto_n: str) -> List[str]:
    return [
        t
        for t in str(texto_n or "").split()
        if len(t) > 2 and t not in _STOPWORDS_MENU
    ]


def resolver_opcion_menu(
    texto: str,
    opciones: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Retorna (opcion|None, modo) donde modo ∈ {numero, texto, invalido, ninguna}.

    El número del usuario se interpreta como el número visible del menú (1..N
    de opciones activas), no como el campo fijo `numero` en base de datos.

    Las preguntas libres (p. ej. «qué es monetizar?») no hacen match débil por
    keywords: deben entrar por la opción «Otras preguntas».
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

    # Coincidencia exacta / contención fuerte por codigo / titulo / intencion
    for op in activas:
        candidatos = [
            _normalizar(str(op.get("codigo") or "")),
            _normalizar(str(op.get("titulo") or "")),
            _normalizar(str(op.get("intencion") or "")),
        ]
        for c in candidatos:
            if not c:
                continue
            if c == n or (n in c and len(n) >= 6) or (c in n and len(c) >= 10):
                return op, "texto"

    # Preguntas libres: solo atajos explícitos a Otras preguntas / asesor.
    if _parece_pregunta_libre(texto):
        for op in activas:
            codigo = _normalizar(str(op.get("codigo") or ""))
            titulo = _normalizar(str(op.get("titulo") or ""))
            if codigo in {"otras_preguntas", "asesor"} and (
                codigo == n or titulo == n or (titulo and titulo in n)
            ):
                return op, "texto"
        return None, "ninguna"

    # Palabras clave solo para mensajes cortos de menú (no preguntas).
    # Sin «monetizar»: eso se consulta por Otras preguntas / FAQ.
    mapa = {
        "requisitos": ("requisito", "requisitos"),
        "beneficios": ("beneficio", "beneficios"),
        "bonos": ("bono", "bonos", "incentivo", "incentivos"),
        "bonos_monetizacion": ("bono", "bonos", "incentivo", "incentivos"),
        "monetizacion": ("bono", "bonos", "incentivo"),
        "agencia": ("funcionamiento", "como funciona"),
        "como_funciona": ("funcionamiento", "como funciona"),
        "proceso": ("proceso", "continuar", "solicitud", "unirme"),
        "continuar_proceso": ("proceso", "continuar", "solicitud", "unirme"),
        "otras_preguntas": (
            "otra pregunta",
            "otras preguntas",
            "otra consulta",
            "otras consultas",
            "otra duda",
        ),
        "asesor": ("asesor", "humano", "persona", "agente", "manager"),
    }
    mejor: Optional[Dict[str, Any]] = None
    mejor_score = 0
    toks = _tokens_menu_utiles(n)
    for op in activas:
        score = 0
        intencion = _normalizar(str(op.get("intencion") or ""))
        codigo = _normalizar(str(op.get("codigo") or ""))
        titulo = _normalizar(str(op.get("titulo") or ""))
        claves = set(mapa.get(intencion, ())) | set(mapa.get(codigo, ()))
        for k in claves:
            if k and k in n:
                score += 12 if " " in k or len(k) >= 6 else 8
        if titulo:
            solapa = [t for t in toks if t in titulo]
            if solapa:
                score += 6 * len(solapa)
                if any(len(t) >= 6 for t in solapa):
                    score += 4
        if score > mejor_score:
            mejor_score = score
            mejor = op

    # Umbral alto: evita falsos positivos tipo «monetizar» → bonos.
    if mejor and mejor_score >= 12 and len(n.split()) <= 4:
        return mejor, "texto"

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
    if any(k in n for k in ("responsable", "compromiso", "horario", "meta")):
        return "compromiso"
    if any(k in n for k in ("disponibilidad", "disponible")):
        return "disponibilidad"
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
    vineta: str = "✅",
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
        marca = str(vineta or "✅").strip() or "✅"
        for idx, item in enumerate(utiles, start=1):
            if numerada:
                lineas.append(_linea_lista_numerada(idx, item))
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
) -> Tuple[str, bool, Optional[Dict[str, Any]]]:
    """
    Construye respuesta SOLO desde tablas autorizadas según intención.
    Retorna (texto, requiere_asesor, lista_detalle|None).
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
            None,
        )

    if intencion_n == "requisitos":
        reqs = db_conv.listar_requisitos(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            solo_activos=True,
        )
        reqs = sorted(reqs or [], key=lambda r: int(r.get("orden") or 0))
        items = preparar_items_requisitos(
            reqs,
            max_elementos=int(presentacion.get("max_elementos_respuesta") or 15),
        )
        texto, lista, _det = construir_respuesta_lista_o_detalle(
            texto_consulta,
            items,
            tipo="requisitos",
            titulo="Requisitos para ser creador LIVE 🎥",
            introduccion="Para formar parte de la agencia necesitas:",
            presentacion=presentacion,
        )
        return texto, not bool(texto), lista if items else None

    if intencion_n == "beneficios":
        bens = db_conv.listar_beneficios(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            solo_activos=True,
        )
        items = preparar_items_beneficios(
            bens or [],
            tipos=("beneficio", "capacitacion", "acompanamiento", "otro"),
            max_elementos=int(presentacion.get("max_elementos_respuesta") or 15),
        )
        texto, lista, _det = construir_respuesta_lista_o_detalle(
            texto_consulta,
            items,
            tipo="beneficios",
            titulo="Beneficios de pertenecer a la agencia",
            introduccion="Esto es lo que ofrece la agencia:",
            presentacion=presentacion,
        )
        return texto, not bool(texto), lista if items else None

    if intencion_n == "bonos":
        bens = db_conv.listar_beneficios(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            solo_activos=True,
        )
        items = preparar_items_beneficios(
            bens or [],
            tipos=("bono", "incentivo"),
            max_elementos=int(presentacion.get("max_elementos_respuesta") or 15),
        )
        texto, lista, _det = construir_respuesta_lista_o_detalle(
            texto_consulta,
            items,
            tipo="bonos",
            titulo="Bonos e incentivos",
            introduccion="Esto es lo que ofrece la agencia:",
            presentacion=presentacion,
        )
        return texto, not bool(texto), lista if items else None

    if intencion_n in {"agencia", "proceso", "faq"}:
        faqs = db_conv.listar_faqs(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            solo_activos=True,
        )
        opcion_virtual = {
            "intencion": intencion_n,
            "codigo": "como_funciona" if intencion_n == "agencia" else intencion_n,
            "titulo": {
                "agencia": "Cómo funciona la agencia",
                "proceso": "Continuar con el proceso",
                "faq": "Información",
            }.get(intencion_n, "Información"),
        }
        texto, lista, ok = construir_respuesta_menu_faq(
            opcion=opcion_virtual,
            faqs=faqs or [],
            texto_usuario=texto_consulta,
            presentacion=presentacion,
            intencion_forzada=intencion_n,
        )
        return texto, (not ok), lista

    return "", True, None


def empaquetar_lista_detalle(
    tipo: str,
    titulo: str,
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "tipo": str(tipo or "").strip().lower(),
        "titulo": str(titulo or "").strip(),
        "items": [
            {
                "n": int(it.get("n") or 0),
                "titulo": str(it.get("titulo") or "").strip(),
                "detalle": str(it.get("detalle") or "").strip(),
            }
            for it in (items or [])
            if int(it.get("n") or 0) > 0 and str(it.get("titulo") or "").strip()
        ],
    }


def construir_texto_detalle_item(
    item: Dict[str, Any],
    *,
    presentacion: Optional[Dict[str, Any]] = None,
    total: int = 0,
) -> str:
    p = presentacion_desde_asistente(presentacion)
    titulo = str(item.get("titulo") or "").strip() or "Detalle"
    detalle = str(item.get("detalle") or "").strip() or "Sin detalle adicional."
    lineas = [f"*{titulo}*", "", detalle]
    if p.get("agregar_pregunta_final"):
        lineas.append("")
        if total > 1:
            lineas.append(
                f"Escribe otro *número* (1-{int(total)}) para más detalle, "
                "o *menu* para volver al menú."
            )
        else:
            lineas.append("Escribe *menu* para volver al menú.")
    return "\n".join(lineas).strip()


_STOPWORDS_CONSULTA = frozenset(
    {
        "que",
        "es",
        "el",
        "la",
        "los",
        "las",
        "de",
        "del",
        "un",
        "una",
        "unos",
        "unas",
        "me",
        "te",
        "se",
        "mi",
        "tu",
        "su",
        "al",
        "lo",
        "como",
        "cual",
        "cuales",
        "cuando",
        "donde",
        "porque",
        "por",
        "para",
        "con",
        "sin",
        "sobre",
        "hay",
        "tiene",
        "tienen",
        "quiero",
        "saber",
        "explica",
        "explicame",
        "explicar",
        "dime",
        "cuentame",
        "info",
        "informacion",
        "mas",
        "detalle",
        "detalles",
        "significa",
        "consiste",
        "puedes",
        "podrias",
        "hola",
    }
)


def _tokens_consulta(texto: str) -> List[str]:
    return [
        t
        for t in _normalizar(texto).split()
        if len(t) > 2 and t not in _STOPWORDS_CONSULTA
    ]


def _score_coincidencia_item(texto_n: str, item: Dict[str, Any]) -> int:
    """Puntúa qué tan bien una pregunta en texto apunta a un ítem de la lista."""
    titulo = _normalizar(str(item.get("titulo") or ""))
    detalle = _normalizar(str(item.get("detalle") or ""))
    if not texto_n or not titulo:
        return 0
    if titulo == texto_n or titulo in texto_n or texto_n in titulo:
        return 100

    toks_q = set(_tokens_consulta(texto_n))
    if not toks_q:
        return 0
    toks_t = set(_tokens_consulta(titulo))
    toks_d = set(_tokens_consulta(detalle))
    solapa_t = toks_q & toks_t
    solapa_d = toks_q & toks_d
    score = 0
    if solapa_t:
        score += 35 + 15 * len(solapa_t)
        # Coincidencia casi completa del título (p. ej. "bono incorporacion").
        if toks_t and len(solapa_t) >= max(1, len(toks_t) - 1):
            score += 25
    if solapa_d:
        score += 8 * min(3, len(solapa_d))
    # Palabra distintiva larga del título dentro de la pregunta.
    for tok in toks_t:
        if len(tok) >= 6 and tok in texto_n:
            score += 20
            break
    return score


def resolver_item_lista_detalle(
    texto: str,
    lista: Optional[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Retorna (item|None, modo) con modo ∈ {detalle, invalido, ninguna}.

    Acepta número (1, 2…) o pregunta en texto sobre un ítem
    (p. ej. "qué es el bono de incorporación").
    """
    items = list((lista or {}).get("items") or [])
    if not items:
        return None, "ninguna"

    numero = extraer_numero_opcion(texto)
    if numero is not None:
        for item in items:
            if int(item.get("n") or 0) == int(numero):
                return item, "detalle"
        return None, "invalido"

    texto_n = _normalizar(texto)
    if not texto_n:
        return None, "ninguna"

    mejor: Optional[Dict[str, Any]] = None
    mejor_score = 0
    segundo = 0
    for item in items:
        score = _score_coincidencia_item(texto_n, item)
        if score > mejor_score:
            segundo = mejor_score
            mejor_score = score
            mejor = item
        elif score > segundo:
            segundo = score

    # Umbral: evita falsos positivos; exige margen si hay empate cercano.
    if mejor and mejor_score >= 40 and (mejor_score - segundo) >= 10:
        return mejor, "detalle"
    if mejor and mejor_score >= 70:
        return mejor, "detalle"
    return None, "ninguna"


def _es_solo_seleccion_menu(texto: str) -> bool:
    """
    True si el mensaje es solo elegir opción de menú (1, uno, opción 2),
    no una pregunta sobre un ítem concreto.
    """
    n = _normalizar(texto)
    if not n:
        return True
    if extraer_numero_opcion(texto) is None:
        return False
    # "1", "uno", "opcion 2", "opc 3"
    return len(n.split()) <= 2


def _parece_pregunta_libre(texto: str) -> bool:
    """True si el mensaje parece una consulta/pregunta y no solo elegir menú."""
    crudo = str(texto or "").strip()
    if not crudo or _es_solo_seleccion_menu(crudo):
        return False
    if "?" in crudo or "¿" in crudo:
        return True
    n = _normalizar(crudo)
    toks = _tokens_menu_utiles(n)
    if not toks:
        return False
    prefijos = (
        "que ",
        "como ",
        "cual ",
        "cuales ",
        "cuanto ",
        "cuantos ",
        "donde ",
        "por que ",
        "porque ",
        "para que ",
    )
    if any(n.startswith(p) for p in prefijos):
        return True
    if any(p in n for p in ("explic", "significa", "consiste", "diferencia")):
        return True
    return len(n.split()) >= 4 and len(toks) >= 2


def construir_respuesta_lista_o_detalle(
    texto_usuario: str,
    items: List[Dict[str, Any]],
    *,
    tipo: str,
    titulo: str,
    introduccion: str,
    presentacion: Dict[str, Any],
) -> Tuple[str, Dict[str, Any], bool]:
    """
    Si el usuario pregunta por un ítem concreto → detalle;
    si no → lista numerada. Siempre devuelve la lista para dejarla pendiente.
    """
    lista = empaquetar_lista_detalle(tipo, titulo, items)
    # Si acabamos de elegir la opción del menú con un número ("1"/"uno"),
    # mostramos la lista completa; el detalle por número aplica cuando ya
    # hay lista pendiente en el siguiente turno.
    if items and not _es_solo_seleccion_menu(texto_usuario):
        item, modo = resolver_item_lista_detalle(texto_usuario, lista)
        if modo == "detalle" and item:
            texto = construir_texto_detalle_item(
                item,
                presentacion=presentacion,
                total=len(list(lista.get("items") or [])),
            )
            return texto, lista, True
    texto = construir_texto_lista_detalle(
        items,
        titulo=titulo,
        introduccion=introduccion,
        presentacion=presentacion,
    )
    return texto, lista, False


def _contexto_conversacion(conversacion: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not conversacion:
        return {}
    ctx = conversacion.get("contexto")
    if isinstance(ctx, str):
        try:
            ctx = json.loads(ctx)
        except Exception:
            ctx = {}
    return dict(ctx or {}) if isinstance(ctx, dict) else {}


def _persistir_contexto_conversacion(
    *,
    db_conv: Any,
    agencia_id: int,
    conversacion_id: Optional[int],
    conversacion: Optional[Dict[str, Any]],
    contexto: Dict[str, Any],
    dry_run: bool,
) -> None:
    if conversacion is not None:
        conversacion["contexto"] = contexto
    if dry_run or not conversacion_id:
        return
    try:
        db_conv.actualizar_conversacion(
            agencia_id,
            int(conversacion_id),
            {"contexto": contexto},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CHATBOT_MENU] no se pudo guardar contexto: %s", exc)


def _set_lista_detalle_pendiente(
    *,
    db_conv: Any,
    agencia_id: int,
    conversacion_id: Optional[int],
    conversacion: Optional[Dict[str, Any]],
    lista: Optional[Dict[str, Any]],
    dry_run: bool,
) -> None:
    ctx = _contexto_conversacion(conversacion)
    if lista and (lista.get("items") or []):
        ctx["lista_detalle_pendiente"] = lista
        ctx.pop("pregunta_faq_pendiente", None)
    else:
        ctx.pop("lista_detalle_pendiente", None)
    _persistir_contexto_conversacion(
        db_conv=db_conv,
        agencia_id=agencia_id,
        conversacion_id=conversacion_id,
        conversacion=conversacion,
        contexto=ctx,
        dry_run=dry_run,
    )


def _set_pregunta_faq_pendiente(
    *,
    db_conv: Any,
    agencia_id: int,
    conversacion_id: Optional[int],
    conversacion: Optional[Dict[str, Any]],
    activa: bool,
    dry_run: bool,
) -> None:
    ctx = _contexto_conversacion(conversacion)
    if activa:
        ctx["pregunta_faq_pendiente"] = True
        ctx.pop("lista_detalle_pendiente", None)
    else:
        ctx.pop("pregunta_faq_pendiente", None)
    _persistir_contexto_conversacion(
        db_conv=db_conv,
        agencia_id=agencia_id,
        conversacion_id=conversacion_id,
        conversacion=conversacion,
        contexto=ctx,
        dry_run=dry_run,
    )


def _marcar_menu_bienvenida_enviada(
    *,
    db_conv: Any,
    agencia_id: int,
    conversacion_id: Optional[int],
    conversacion: Optional[Dict[str, Any]],
    dry_run: bool,
) -> None:
    ctx = _contexto_conversacion(conversacion)
    if ctx.get("menu_bienvenida_enviada"):
        return
    ctx["menu_bienvenida_enviada"] = True
    _persistir_contexto_conversacion(
        db_conv=db_conv,
        agencia_id=agencia_id,
        conversacion_id=conversacion_id,
        conversacion=conversacion,
        contexto=ctx,
        dry_run=dry_run,
    )


def _bienvenida_menu_ya_enviada(
    *,
    ctx: Dict[str, Any],
    db_conv: Any,
    agencia_id: int,
    conversacion_id: Optional[int],
) -> bool:
    """
    True si esta conversación ya recibió la bienvenida/menú inicial.

    Usa la bandera de contexto; si falta (conversaciones previas), infiere
    por mensajes salientes ya existentes (sin nueva columna de BD).
    """
    if ctx.get("menu_bienvenida_enviada"):
        return True
    if not conversacion_id:
        return False
    try:
        mensajes = db_conv.listar_mensajes(
            agencia_id, int(conversacion_id), limit=20, orden="desc"
        )
    except Exception:
        return False
    for m in mensajes or []:
        if str(m.get("direccion") or "").lower() == "saliente":
            return True
    return False


def _resumir_frase(texto: str, *, max_len: int = 72) -> str:
    """Primera frase corta para listados numerados."""
    t = _limpiar_frase_requisito(texto)
    if not t:
        return ""
    # Cortar en el primer punto si hay más de una oración.
    for sep in (". ", "! ", "? "):
        if sep in t[:-1]:
            t = t.split(sep, 1)[0].rstrip(".") + "."
            break
    if len(t) > max_len:
        t = t[: max_len - 1].rstrip(" .,;:") + "…"
    return t


def _titulo_opcion_menu_corta(titulo: str) -> str:
    """Título del menú = texto configurado (sin reescribir etiquetas fijas)."""
    crudo = re.sub(r"\s+", " ", str(titulo or "").strip())
    if not crudo:
        return ""
    # Solo acorta si es excesivamente largo para WhatsApp.
    if len(crudo) <= 60:
        return crudo
    return _resumir_frase(crudo, max_len=60).rstrip(".")


def _titulo_corto_requisito(requisito: Dict[str, Any]) -> str:
    """Título de lista = nombre configurado en el admin (sin reescribir)."""
    nombre = re.sub(r"\s+", " ", str(requisito.get("nombre") or "").strip())
    if nombre and not _es_pregunta(nombre):
        return nombre
    desc = str(
        requisito.get("descripcion") or requisito.get("valor_texto") or ""
    ).strip()
    if desc and not _es_pregunta(desc):
        return _resumir_frase(desc, max_len=80).rstrip(".")
    return nombre or _resumir_frase(desc or "Requisito", max_len=80).rstrip(".")


def _detalle_requisito(requisito: Dict[str, Any]) -> str:
    """Detalle = descripción configurada; si es pregunta de formulario, usa el nombre."""
    nombre = str(requisito.get("nombre") or "").strip()
    desc = str(
        requisito.get("descripcion") or requisito.get("valor_texto") or ""
    ).strip()
    if desc and not _es_pregunta(desc):
        return _limpiar_frase_requisito(desc)
    if desc and _es_pregunta(desc) and nombre:
        # Evita responder solo con "¿Eres mayor de 18?" en WhatsApp.
        return _limpiar_frase_requisito(nombre)
    return _limpiar_frase_requisito(desc or nombre or "Sin detalle adicional.")


def preparar_items_requisitos(
    requisitos: List[Dict[str, Any]],
    *,
    max_elementos: int = 15,
) -> List[Dict[str, Any]]:
    """Lista numerada con nombre configurado + detalle de la descripción."""
    crudos: List[Dict[str, Any]] = []
    for r in requisitos or []:
        if not _vigente(r):
            continue
        if r.get("permitir_mencion_automatica") is False:
            continue
        titulo = _titulo_corto_requisito(r)
        if not titulo:
            continue
        desc_raw = str(r.get("descripcion") or r.get("valor_texto") or "")
        crudos.append(
            {
                "id": r.get("id"),
                "titulo": titulo,
                "detalle": _detalle_requisito(r),
                "_clave": _normalizar(titulo),
                "_detalle_pregunta": _es_pregunta(desc_raw),
            }
        )

    # Dedup por tema/clave: evita repetir p. ej. dos requisitos de edad.
    # Conserva el de mejor detalle (descripción afirmativa / más completa).
    vistos: List[str] = []
    tema_idx: Dict[str, int] = {}
    dedup: List[Dict[str, Any]] = []
    for item in crudos:
        clave = item["_clave"]
        tema = _tema_requisito(item["titulo"] + " " + item["detalle"])
        if tema is not None and tema in tema_idx:
            idx = tema_idx[tema]
            actual = dedup[idx]
            reemplazar = False
            if item.get("_detalle_pregunta") and not actual.get("_detalle_pregunta"):
                reemplazar = False
            elif (not item.get("_detalle_pregunta")) and actual.get("_detalle_pregunta"):
                reemplazar = True
            elif len(item["detalle"]) > len(actual["detalle"]):
                reemplazar = True
            if reemplazar:
                dedup[idx] = item
                vistos[idx] = clave
            continue
        if any(clave in v or v in clave for v in vistos):
            continue
        if tema is not None:
            tema_idx[tema] = len(dedup)
        dedup.append(item)
        vistos.append(clave)

    out: List[Dict[str, Any]] = []
    for idx, item in enumerate(dedup[: max(1, int(max_elementos or 15))], start=1):
        out.append(
            {
                "n": idx,
                "id": item.get("id"),
                "titulo": item["titulo"],
                "detalle": item["detalle"],
            }
        )
    return out


def construir_texto_lista_detalle(
    items: List[Dict[str, Any]],
    *,
    titulo: str,
    introduccion: str,
    presentacion: Optional[Dict[str, Any]] = None,
) -> str:
    """Lista numerada + ✅ para elegir detalle con un número."""
    p = presentacion_desde_asistente(presentacion)
    lineas: List[str] = []
    if p.get("mostrar_titulo_respuesta"):
        lineas.append(str(titulo).strip())
        lineas.append("")
    if introduccion:
        lineas.append(str(introduccion).strip())
        lineas.append("")
    for item in items:
        lineas.append(_linea_lista_numerada(int(item["n"]), item["titulo"]))
    if p.get("agregar_pregunta_final"):
        lineas.append("")
        lineas.append(
            "Escribe el *número* para más detalle, o *menu* para volver al menú."
        )
    return "\n".join(lineas).strip()


def construir_respuesta_requisitos(
    requisitos: List[Dict[str, Any]],
    presentacion: Dict[str, Any],
) -> Tuple[str, List[Dict[str, Any]]]:
    items = preparar_items_requisitos(
        requisitos,
        max_elementos=int(presentacion.get("max_elementos_respuesta") or 15),
    )
    texto = construir_texto_lista_detalle(
        items,
        titulo="Requisitos para ser creador LIVE 🎥",
        introduccion="Para formar parte de la agencia necesitas:",
        presentacion=presentacion,
    )
    return texto, items


def preparar_items_beneficios(
    beneficios: List[Dict[str, Any]],
    *,
    tipos: Tuple[str, ...],
    max_elementos: int = 15,
) -> List[Dict[str, Any]]:
    """Lista numerada: título = nombre del admin; detalle = texto/descripción configurada."""
    out: List[Dict[str, Any]] = []
    n = 0
    for b in beneficios or []:
        if not _vigente(b):
            continue
        if b.get("permitir_mencion_automatica") is False:
            continue
        if b.get("visible_publicamente") is False:
            continue
        tipo = str(b.get("tipo") or "").lower()
        if tipos and tipo not in tipos:
            continue

        nombre = re.sub(r"\s+", " ", str(b.get("nombre") or "").strip())
        detalle_raw = (
            str(b.get("texto_autorizado") or "").strip()
            or str(b.get("descripcion_corta") or "").strip()
            or str(b.get("descripcion_completa") or "").strip()
        )
        if not nombre and not detalle_raw:
            continue
        titulo = nombre or _resumir_frase(detalle_raw, max_len=80).rstrip(".")
        detalle = detalle_raw or nombre
        if b.get("requiere_validacion_humana"):
            detalle = f"{detalle.rstrip('.')} (sujeto a validación del equipo)"
        n += 1
        out.append(
            {
                "n": n,
                "id": b.get("id"),
                "titulo": titulo,
                "detalle": _limpiar_frase_requisito(detalle),
            }
        )
        if n >= max(1, int(max_elementos or 15)):
            break
    return out


def construir_respuesta_beneficios(
    beneficios: List[Dict[str, Any]],
    presentacion: Dict[str, Any],
    *,
    tipos: Tuple[str, ...],
    titulo: str,
) -> Tuple[str, List[Dict[str, Any]]]:
    items = preparar_items_beneficios(
        beneficios,
        tipos=tipos,
        max_elementos=int(presentacion.get("max_elementos_respuesta") or 15),
    )
    texto = construir_texto_lista_detalle(
        items,
        titulo=titulo,
        introduccion="Esto es lo que ofrece la agencia:",
        presentacion=presentacion,
    )
    return texto, items


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
        max_elementos=int(presentacion.get("max_elementos_respuesta") or 15),
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

    # Sembrar menú vacío o desactivar «Otras preguntas» históricas.
    if not dry_run:
        try:
            seed = db_conv.asegurar_menu_informativo_base(
                agencia_id,
                chatbot_configuracion_id,
            )
            if (
                not opciones
                or int(seed.get("insertadas") or 0) > 0
                or int(seed.get("desactivadas") or 0) > 0
            ):
                opciones = db_conv.listar_menu_informativo(
                    agencia_id,
                    chatbot_configuracion_id=chatbot_configuracion_id,
                    solo_activas=True,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[CHATBOT_MENU] no se pudo sembrar/actualizar menú: %s", exc
            )

    # FAQ es conocimiento interno: no inyectar «Otras preguntas» en el menú.
    opciones = [
        o
        for o in (opciones or [])
        if _normalizar(str(o.get("codigo") or "")) != "otras_preguntas"
    ]
    opciones = ordenar_opciones_menu(opciones)
    nombre_agencia = str(
        (agencia or {}).get("nombre")
        or (asistente or {}).get("nombre_asistente")
        or "la agencia"
    )
    texto_menu_inicial = construir_menu_inicial(
        nombre_agencia=nombre_agencia,
        opciones=opciones,
        presentacion=presentacion,
        presentacion_inicial=(asistente or {}).get("presentacion_inicial"),
    )
    texto_menu_retorno = construir_menu_retorno(
        opciones=opciones,
        presentacion=presentacion,
    )
    # Por defecto el menú corto: no reinyectar bienvenida en pies / repeticiones.
    texto_menu = texto_menu_retorno

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

    # Menú inicial / volver al menú (menu, volver, opciones, hola…)
    texto_in = str(texto or "").strip()
    mostrar_menu = bool(presentacion.get("mostrar_menu_inicial", True))
    ctx_conv = _contexto_conversacion(conversacion)
    lista_detalle = ctx_conv.get("lista_detalle_pendiente")
    if not isinstance(lista_detalle, dict):
        lista_detalle = None
    lista_detalle_a_guardar: Optional[Dict[str, Any]] = None
    limpiar_lista_detalle = False

    pide_menu = (not texto_in) or es_comando_menu_o_saludo(texto_in)
    if pide_menu and mostrar_menu and opciones:
        bienvenida_ya = _bienvenida_menu_ya_enviada(
            ctx=ctx_conv,
            db_conv=db_conv,
            agencia_id=agencia_id,
            conversacion_id=conversacion_id,
        )
        es_saludo = bool(texto_in) and es_comando_saludo(texto_in)
        es_volver = bool(texto_in) and es_comando_volver_menu(texto_in)

        if not bienvenida_ya:
            texto_a_enviar = texto_menu_inicial
            tipo_menu = "initial"
            origen_menu = "primer_contacto" if not texto_in else (
                "saludo" if es_saludo else "menu"
            )
        elif es_saludo and not es_volver:
            saludo_corto = str(
                presentacion.get("mensaje_hola_de_nuevo")
                or DEFAULTS_PRESENTACION["mensaje_hola_de_nuevo"]
            ).strip()
            texto_a_enviar = f"{saludo_corto}\n\n{texto_menu_retorno}"
            tipo_menu = "return"
            origen_menu = "saludo"
        else:
            texto_a_enviar = texto_menu_retorno
            tipo_menu = "return"
            origen_menu = "menu" if (es_volver or not texto_in) else "saludo"

        limpiar_lista_detalle = True
        _set_lista_detalle_pendiente(
            db_conv=db_conv,
            agencia_id=agencia_id,
            conversacion_id=conversacion_id,
            conversacion=conversacion,
            lista=None,
            dry_run=dry_run,
        )
        _set_pregunta_faq_pendiente(
            db_conv=db_conv,
            agencia_id=agencia_id,
            conversacion_id=conversacion_id,
            conversacion=conversacion,
            activa=False,
            dry_run=dry_run,
        )
        envio = await garantizar_respuesta_saliente(
            agencia_id=agencia_id,
            conversacion_id=conversacion_id,
            canal=canal,
            texto=texto_a_enviar,
            dry_run=dry_run,
            enviar_callback=enviar_callback,
            token=token,
            phone_number_id=phone_number_id,
            destino=destino,
            motivo_fallback=f"menu_{tipo_menu}",
            mensaje_externo_id=mensaje_externo_id,
        )
        if tipo_menu == "initial":
            _marcar_menu_bienvenida_enviada(
                db_conv=db_conv,
                agencia_id=agencia_id,
                conversacion_id=conversacion_id,
                conversacion=conversacion,
                dry_run=dry_run,
            )
        logger.info(
            "[CHATBOT_MENU] tipo=%s origen=%s conversacion_id=%s "
            "respuesta_enviada=%s",
            tipo_menu,
            origen_menu,
            conversacion_id,
            bool(envio.get("enviado") or dry_run),
        )
        return {
            "usado": True,
            "respuesta": texto_a_enviar,
            "respuesta_enviada": bool(envio.get("enviado") is True) or dry_run,
            "enlaces": [],
            "menu": True,
            "menu_tipo": tipo_menu,
        }

    # Compat: si quedó pendiente de «Otras preguntas», tratar como consulta FAQ libre.
    if ctx_conv.get("pregunta_faq_pendiente") and texto_in:
        op_menu, modo_menu = resolver_opcion_menu(texto_in, opciones)
        if not (modo_menu in {"numero", "texto"} and op_menu):
            r_faq = await _responder_conocimiento_faq(
                texto_in,
                agencia_id=agencia_id,
                chatbot_configuracion_id=chatbot_configuracion_id,
                presentacion=presentacion,
                db_conv=db_conv,
                db_cap=db_cap,
                conversacion_id=conversacion_id,
                conversacion=conversacion,
                canal=canal,
                dry_run=dry_run,
                enviar_callback=enviar_callback,
                token=token,
                phone_number_id=phone_number_id,
                destino=destino,
                mensaje_externo_id=mensaje_externo_id,
                aspirante_id=aspirante_id,
            )
            _set_pregunta_faq_pendiente(
                db_conv=db_conv,
                agencia_id=agencia_id,
                conversacion_id=conversacion_id,
                conversacion=conversacion,
                activa=False,
                dry_run=dry_run,
            )
            return r_faq
        _set_pregunta_faq_pendiente(
            db_conv=db_conv,
            agencia_id=agencia_id,
            conversacion_id=conversacion_id,
            conversacion=conversacion,
            activa=False,
            dry_run=dry_run,
        )

    # Si hay lista numerada pendiente (requisitos/beneficios/…), el número
    # profundiza en un ítem; no compite con el menú principal.
    if lista_detalle:
        item_det, modo_det = resolver_item_lista_detalle(texto_in, lista_detalle)
        if modo_det == "detalle" and item_det:
            items_lista = list(lista_detalle.get("items") or [])
            respuesta = construir_texto_detalle_item(
                item_det,
                presentacion=presentacion,
                total=len(items_lista),
            )
            if respuesta and texto_menu and texto_menu not in respuesta:
                respuesta = _con_pie_menu(respuesta, presentacion)
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
                motivo_fallback="detalle_lista",
                mensaje_externo_id=mensaje_externo_id,
            )
            logger.info(
                "[CHATBOT_MENU] conversacion_id=%s entrada=detalle_lista "
                "item=%s respuesta_enviada=%s",
                conversacion_id,
                item_det.get("n"),
                bool(envio.get("enviado") or dry_run),
            )
            return {
                "usado": True,
                "motivo": None,
                "respuesta": respuesta,
                "respuesta_enviada": bool(envio.get("enviado") is True) or dry_run,
                "requiere_asesor": False,
                "modo_humano": False,
                "enlaces": [],
                "intencion": str(lista_detalle.get("tipo") or "detalle"),
                "detalle_lista": True,
            }
        if modo_det == "invalido":
            total = len(list(lista_detalle.get("items") or []))
            respuesta = (
                f"Ese número no está en la lista. Escribe un número del *1* al *{total}*."
            )
            if texto_menu and texto_menu not in respuesta:
                respuesta = _con_pie_menu(respuesta, presentacion)
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
                motivo_fallback="detalle_lista_invalido",
                mensaje_externo_id=mensaje_externo_id,
            )
            return {
                "usado": True,
                "motivo": "detalle_lista_invalido",
                "respuesta": respuesta,
                "respuesta_enviada": bool(envio.get("enviado") is True) or dry_run,
                "requiere_asesor": False,
                "modo_humano": False,
                "enlaces": [],
                "intencion": str(lista_detalle.get("tipo") or "detalle"),
            }

    # Pregunta libre en cualquier momento → conocimiento FAQ (sin pasar por menú).
    if texto_in and (
        _parece_pregunta_libre(texto_in)
        or (resolver_opcion_menu(texto_in, opciones)[1] == "ninguna")
    ):
        op_previa, modo_previo = resolver_opcion_menu(texto_in, opciones)
        # Si es selección clara de menú (número/título corto), no forzar FAQ.
        if not (modo_previo in {"numero", "texto"} and op_previa):
            return await _responder_conocimiento_faq(
                texto_in,
                agencia_id=agencia_id,
                chatbot_configuracion_id=chatbot_configuracion_id,
                presentacion=presentacion,
                db_conv=db_conv,
                db_cap=db_cap,
                conversacion_id=conversacion_id,
                conversacion=conversacion,
                canal=canal,
                dry_run=dry_run,
                enviar_callback=enviar_callback,
                token=token,
                phone_number_id=phone_number_id,
                destino=destino,
                mensaje_externo_id=mensaje_externo_id,
                aspirante_id=aspirante_id,
                texto_menu=texto_menu,
            )

    opcion, modo = resolver_opcion_menu(texto_in, opciones)
    requiere_asesor = False
    respuesta = ""
    intencion = "desconocida"

    if modo == "invalido":
        respuesta = str(
            presentacion.get("mensaje_opcion_no_valida")
            or DEFAULTS_PRESENTACION["mensaje_opcion_no_valida"]
        )
        intencion = "menu"
        limpiar_lista_detalle = True
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
            reqs = sorted(reqs or [], key=lambda r: int(r.get("orden") or 0))
            items = preparar_items_requisitos(
                reqs,
                max_elementos=int(presentacion.get("max_elementos_respuesta") or 15),
            )
            respuesta, lista_detalle_a_guardar, _det = construir_respuesta_lista_o_detalle(
                texto_in,
                items,
                tipo="requisitos",
                titulo="Requisitos para ser creador LIVE 🎥",
                introduccion="Para formar parte de la agencia necesitas:",
                presentacion=presentacion,
            )
        elif tipo_fuente == "beneficios":
            bens = db_conv.listar_beneficios(
                agencia_id,
                chatbot_configuracion_id=chatbot_configuracion_id,
                solo_activos=True,
            )
            codigo_op = _normalizar(str(opcion.get("codigo") or ""))
            # Opción unificada «Beneficios y bonos» (menú mínimo).
            if codigo_op in {
                "beneficios_bonos",
                "beneficios_y_bonos",
                "beneficios_bonos_monetizacion",
            }:
                items = preparar_items_beneficios(
                    bens or [],
                    tipos=(
                        "beneficio",
                        "capacitacion",
                        "acompanamiento",
                        "otro",
                        "bono",
                        "incentivo",
                    ),
                    max_elementos=int(presentacion.get("max_elementos_respuesta") or 15),
                )
                titulo_ben = "Beneficios y bonos"
            else:
                items = preparar_items_beneficios(
                    bens or [],
                    tipos=("beneficio", "capacitacion", "acompanamiento", "otro"),
                    max_elementos=int(presentacion.get("max_elementos_respuesta") or 15),
                )
                titulo_ben = "Beneficios de pertenecer a la agencia"
            respuesta, lista_detalle_a_guardar, _det = construir_respuesta_lista_o_detalle(
                texto_in,
                items,
                tipo="beneficios",
                titulo=titulo_ben,
                introduccion="Esto es lo que ofrece la agencia:",
                presentacion=presentacion,
            )
        elif tipo_fuente == "bonos":
            bens = db_conv.listar_beneficios(
                agencia_id,
                chatbot_configuracion_id=chatbot_configuracion_id,
                solo_activos=True,
            )
            items = preparar_items_beneficios(
                bens or [],
                tipos=("bono", "incentivo"),
                max_elementos=int(presentacion.get("max_elementos_respuesta") or 15),
            )
            respuesta, lista_detalle_a_guardar, _det = construir_respuesta_lista_o_detalle(
                texto_in,
                items,
                tipo="bonos",
                titulo="Bonos e incentivos",
                introduccion="Esto es lo que ofrece la agencia:",
                presentacion=presentacion,
            )
        elif tipo_fuente == "texto":
            respuesta = str(opcion.get("respuesta_personalizada") or "").strip()
            limpiar_lista_detalle = True
        elif tipo_fuente in {"pregunta_libre", "otras_preguntas"} or _normalizar(
            str(opcion.get("codigo") or "")
        ) == "otras_preguntas":
            # Legacy: no pedir paso intermedio; si ya trae pregunta, resolver.
            if _parece_pregunta_libre(texto_in):
                return await _responder_conocimiento_faq(
                    texto_in,
                    agencia_id=agencia_id,
                    chatbot_configuracion_id=chatbot_configuracion_id,
                    presentacion=presentacion,
                    db_conv=db_conv,
                    db_cap=db_cap,
                    conversacion_id=conversacion_id,
                    conversacion=conversacion,
                    canal=canal,
                    dry_run=dry_run,
                    enviar_callback=enviar_callback,
                    token=token,
                    phone_number_id=phone_number_id,
                    destino=destino,
                    mensaje_externo_id=mensaje_externo_id,
                    aspirante_id=aspirante_id,
                    texto_menu=texto_menu,
                )
            respuesta = (
                "Puedes preguntarme directamente lo que quieras saber "
                "(por ejemplo: ¿cómo monetizo? o ¿qué son los regalos?)."
            )
            limpiar_lista_detalle = True
            lista_detalle_a_guardar = None
            _set_pregunta_faq_pendiente(
                db_conv=db_conv,
                agencia_id=agencia_id,
                conversacion_id=conversacion_id,
                conversacion=conversacion,
                activa=False,
                dry_run=dry_run,
            )
        elif tipo_fuente == "asesor":
            requiere_asesor = True
            respuesta = str(
                presentacion.get("mensaje_escalamiento_sin_bloqueo")
                or DEFAULTS_PRESENTACION["mensaje_escalamiento_sin_bloqueo"]
            )
            limpiar_lista_detalle = True
            _set_pregunta_faq_pendiente(
                db_conv=db_conv,
                agencia_id=agencia_id,
                conversacion_id=conversacion_id,
                conversacion=conversacion,
                activa=False,
                dry_run=dry_run,
            )
        else:  # faq (cómo funciona, continuar proceso, etc.)
            faqs = db_conv.listar_faqs(
                agencia_id,
                chatbot_configuracion_id=chatbot_configuracion_id,
                solo_activos=True,
            )
            respuesta, lista_faq, ok_faq = construir_respuesta_menu_faq(
                opcion=opcion,
                faqs=faqs or [],
                texto_usuario=texto_in,
                presentacion=presentacion,
            )
            if lista_faq:
                lista_detalle_a_guardar = lista_faq
            else:
                limpiar_lista_detalle = True
            if not ok_faq:
                respuesta = ""

        if not respuesta:
            respuesta = str(
                presentacion.get("mensaje_sin_informacion")
                or DEFAULTS_PRESENTACION["mensaje_sin_informacion"]
            )
            requiere_asesor = True
            limpiar_lista_detalle = True
            lista_detalle_a_guardar = None

        if presentacion.get("repetir_menu_despues_respuesta") and opciones:
            respuesta = f"{respuesta}\n\n{texto_menu}"
            limpiar_lista_detalle = True
            lista_detalle_a_guardar = None
    else:
        # Sin texto útil: remostrar menú (sin IA semántica; evita demoras).
        respuesta = texto_menu
        intencion = "menu"
        modo = "menu"
        limpiar_lista_detalle = True

    if lista_detalle_a_guardar is not None:
        _set_lista_detalle_pendiente(
            db_conv=db_conv,
            agencia_id=agencia_id,
            conversacion_id=conversacion_id,
            conversacion=conversacion,
            lista=lista_detalle_a_guardar,
            dry_run=dry_run,
        )
    elif limpiar_lista_detalle and lista_detalle:
        _set_lista_detalle_pendiente(
            db_conv=db_conv,
            agencia_id=agencia_id,
            conversacion_id=conversacion_id,
            conversacion=conversacion,
            lista=None,
            dry_run=dry_run,
        )

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


def _limpiar_consulta_faq(texto: str) -> str:
    """Quita prefijos tipo «Pregunta:» que el usuario a veces pega tal cual."""
    n = _normalizar(texto)
    n = re.sub(r"^(pregunta|preguntas|q)\s+", "", n)
    return n.strip()


def _tokens_significativos_faq(texto_n: str) -> List[str]:
    return [
        t
        for t in str(texto_n or "").split()
        if len(t) > 3 and t not in _STOPWORDS_MENU
    ]


def _tokens_compatibles(a: str, b: str) -> bool:
    """True si comparten raíz (monetizar / monetizacion, diamante / diamantes)."""
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 5 and len(b) >= 5 and (a.startswith(b[:5]) or b.startswith(a[:5])):
        return True
    return False


def _score_faq_texto(consulta_n: str, faq: Dict[str, Any]) -> int:
    """Puntúa qué tan bien la consulta libre coincide con una FAQ."""
    pregunta = _limpiar_consulta_faq(str(faq.get("pregunta") or ""))
    if not pregunta and not (faq.get("palabras_clave") or []):
        return 0

    score = 0
    if pregunta:
        if pregunta == consulta_n:
            score += 40
        elif pregunta in consulta_n or consulta_n in pregunta:
            score += 24

        toks_c = _tokens_significativos_faq(consulta_n)
        toks_p = _tokens_significativos_faq(pregunta)
        if toks_c and toks_p:
            usados = set()
            for tc in toks_c:
                for tp in toks_p:
                    if tp in usados:
                        continue
                    if _tokens_compatibles(tc, tp):
                        # Una sola palabra clave fuerte (monetizar, diamante…) basta.
                        if tc == tp:
                            score += 12 if len(tc) >= 6 else 8
                        elif min(len(tc), len(tp)) >= 6:
                            score += 10
                        else:
                            score += 5
                        usados.add(tp)
                        break
            # Cobertura: varios tokens de la FAQ aparecen en la consulta
            if len(usados) >= 2:
                score += 6
            if len(usados) >= 3:
                score += 4

        # «qué es X / qué significa X» refuerza la consulta definitoria.
        if consulta_n.startswith(
            ("que es ", "que son ", "que significa ", "que quiere decir ")
        ):
            score += 2

    claves = faq.get("palabras_clave") or []
    if isinstance(claves, str):
        claves = [c.strip() for c in claves.split(",") if c.strip()]
    for c in claves:
        cn = _normalizar(str(c))
        if not cn:
            continue
        if cn in consulta_n:
            score += 6 if len(cn) >= 5 else 3
        else:
            for tc in _tokens_significativos_faq(consulta_n):
                if _tokens_compatibles(tc, cn):
                    score += 4
                    break

    return score


async def _responder_conocimiento_faq(
    texto_in: str,
    *,
    agencia_id: int,
    chatbot_configuracion_id: int,
    presentacion: Dict[str, Any],
    db_conv: Any,
    db_cap: Any,
    conversacion_id: Optional[int],
    conversacion: Optional[Dict[str, Any]],
    canal: str,
    dry_run: bool,
    enviar_callback,
    token: Optional[str],
    phone_number_id: Optional[str],
    destino: Optional[str],
    mensaje_externo_id: Optional[str],
    aspirante_id: Optional[int] = None,
    texto_menu: str = "",
) -> Dict[str, Any]:
    """
    Resuelve pregunta libre: categorías estructuradas → FAQ (léxico/IA).
    No inventa contenido ni navega web.
    """
    from service_chatbot_respuesta_obligatoria import garantizar_respuesta_saliente
    import chatbot_faq_resolver as faq_res

    # A) Categorías estructuradas (requisitos / beneficios / bonos)
    cat = faq_res.detectar_categoria_estructurada(texto_in)
    lista_detalle_a_guardar = None
    requiere_asesor = False
    if cat == "requisitos":
        reqs = db_conv.listar_requisitos(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            solo_activos=True,
        )
        reqs = sorted(reqs or [], key=lambda r: int(r.get("orden") or 0))
        items = preparar_items_requisitos(
            reqs,
            max_elementos=int(presentacion.get("max_elementos_respuesta") or 15),
        )
        respuesta, lista_detalle_a_guardar, _det = construir_respuesta_lista_o_detalle(
            texto_in,
            items,
            tipo="requisitos",
            titulo="Requisitos para ser creador LIVE",
            introduccion="Para formar parte de la agencia necesitas:",
            presentacion=presentacion,
        )
        intencion = "requisitos"
        metodo = "estructurado"
        resultado = "encontrada"
    elif cat in {"beneficios", "bonos"}:
        bens = db_conv.listar_beneficios(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            solo_activos=True,
        )
        tipos = (
            ("bono", "incentivo")
            if cat == "bonos"
            else ("beneficio", "capacitacion", "acompanamiento", "otro")
        )
        items = preparar_items_beneficios(
            bens or [],
            tipos=tipos,
            max_elementos=int(presentacion.get("max_elementos_respuesta") or 15),
        )
        titulo = "Bonos e incentivos" if cat == "bonos" else "Beneficios de la agencia"
        respuesta, lista_detalle_a_guardar, _det = construir_respuesta_lista_o_detalle(
            texto_in,
            items,
            tipo=cat,
            titulo=titulo,
            introduccion="Esto es lo que ofrece la agencia:",
            presentacion=presentacion,
        )
        intencion = cat
        metodo = "estructurado"
        resultado = "encontrada"
    else:
        faqs: List[Dict[str, Any]] = []
        try:
            faqs = (
                db_conv.listar_faqs(
                    agencia_id,
                    chatbot_configuracion_id=chatbot_configuracion_id,
                    solo_activos=True,
                )
                or []
            )
        except Exception:
            faqs = []
        resolucion = faq_res.resolver_faq(texto_in, faqs, usar_ia=True)
        resultado = resolucion.get("resultado") or faq_res.RESULTADO_SIN_CONOCIMIENTO
        metodo = resolucion.get("metodo")
        intencion = "faq"
        if resultado == faq_res.RESULTADO_ENCONTRADA and resolucion.get("respuesta"):
            respuesta = str(resolucion["respuesta"])
            requiere_asesor = bool(resolucion.get("requiere_humano"))
        elif resultado == faq_res.RESULTADO_NO_ENTENDIDO:
            respuesta = str(
                presentacion.get("mensaje_no_entendido")
                or DEFAULTS_PRESENTACION["mensaje_no_entendido"]
            )
        else:
            respuesta = str(
                presentacion.get("mensaje_faq_no_encontrada")
                or presentacion.get("mensaje_sin_informacion")
                or DEFAULTS_PRESENTACION["mensaje_faq_no_encontrada"]
            )

    if lista_detalle_a_guardar is not None:
        _set_lista_detalle_pendiente(
            db_conv=db_conv,
            agencia_id=agencia_id,
            conversacion_id=conversacion_id,
            conversacion=conversacion,
            lista=lista_detalle_a_guardar,
            dry_run=dry_run,
        )

    if requiere_asesor and aspirante_id and not dry_run:
        try:
            db_cap.actualizar_aspirante_admin(
                agencia_id, int(aspirante_id), requiere_asesor=True
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CHATBOT_FAQ] no se pudo marcar requiere_asesor: %s", exc)

    respuesta = _con_pie_menu(str(respuesta or "").strip(), presentacion)
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
        motivo_fallback=f"faq_{resultado}",
        mensaje_externo_id=mensaje_externo_id,
    )
    logger.info(
        "[CHATBOT_FAQ] agencia_id=%s configuracion_id=%s conversacion_id=%s "
        "resultado=%s metodo=%s respuesta_enviada=%s",
        agencia_id,
        chatbot_configuracion_id,
        conversacion_id,
        resultado,
        metodo,
        bool(envio.get("enviado") or dry_run),
    )
    return {
        "usado": True,
        "motivo": resultado,
        "respuesta": respuesta,
        "respuesta_enviada": bool(envio.get("enviado") is True) or dry_run,
        "requiere_asesor": requiere_asesor,
        "modo_humano": False,
        "enlaces": [],
        "intencion": intencion,
        "faq": resultado == "encontrada" and cat is None,
        "resultado_faq": resultado,
    }


def _buscar_faq(
    faqs: List[Dict[str, Any]],
    intencion: Optional[str],
    texto: str,
) -> str:
    """Compat: usa el resolver nuevo (léxico; sin IA para llamadas síncronas de menú)."""
    import chatbot_faq_resolver as faq_res

    # Si hay intención de menú, priorizar FAQs de esa intención primero.
    if intencion:
        filtradas = [
            f
            for f in (faqs or [])
            if faq_res.normalizar(str(f.get("intencion") or ""))
            == faq_res.normalizar(str(intencion))
            or faq_res.normalizar(str(f.get("categoria") or ""))
            == faq_res.normalizar(str(intencion))
        ]
        if filtradas:
            r = faq_res.resolver_faq(texto, filtradas, usar_ia=False)
            if r.get("respuesta"):
                return str(r["respuesta"])
    r = faq_res.resolver_faq(texto, faqs or [], usar_ia=False)
    return str(r.get("respuesta") or "")


def _aliases_intencion_faq(intencion: Optional[str], *, codigo_opcion: str = "") -> frozenset:
    """
    Normaliza intenciones del menú a las variantes usadas en FAQ
    (p. ej. proceso ↔ faq_proceso, agencia ↔ faq_agencia).
    """
    mapa = {
        "proceso": frozenset(
            {
                "proceso",
                "faq_proceso",
                "continuar_proceso",
                "proceso_ingreso",
                "incorporacion",
                "solicitud",
            }
        ),
        "agencia": frozenset(
            {
                "agencia",
                "faq_agencia",
                "como_funciona",
                "funcionamiento",
                "info_agencia",
            }
        ),
        "faq": frozenset({"faq", "general", "informacion"}),
        "requisitos": frozenset({"requisitos", "faq_requisitos"}),
        "beneficios": frozenset({"beneficios", "faq_beneficios"}),
        "bonos": frozenset({"bonos", "faq_bonos", "incentivos"}),
    }
    keys: set = set()
    n = _normalizar(intencion or "")
    c = _normalizar(codigo_opcion or "")
    if n in mapa:
        keys |= set(mapa[n])
    elif n:
        keys.add(n)
        if not n.startswith("faq_"):
            keys.add(f"faq_{n}")
        elif n.startswith("faq_") and len(n) > 4:
            keys.add(n[4:])
    for canon, aliases in mapa.items():
        if c == canon or c in aliases:
            keys |= set(aliases)
            keys.add(canon)
    # "Cómo funciona" NO arrastra FAQs de proceso automáticamente.
    return frozenset(keys)


def _faq_coincide_claves(faq: Dict[str, Any], claves: frozenset) -> bool:
    if not claves:
        return False
    campos = (
        _normalizar(str(faq.get("intencion") or "")),
        _normalizar(str(faq.get("categoria") or "")),
        _normalizar(str(faq.get("codigo") or "")),
    )
    for campo in campos:
        if not campo:
            continue
        if campo in claves:
            return True
        # codigo tipo faq_proceso / proceso_ingreso
        for clave in claves:
            if clave and (campo == clave or campo.endswith(f"_{clave}") or campo.startswith(f"{clave}_")):
                return True
    return False


def _faqs_por_intencion(
    faqs: List[Dict[str, Any]],
    intencion: Optional[str],
    *,
    codigo_opcion: str = "",
) -> List[Dict[str, Any]]:
    claves = _aliases_intencion_faq(intencion, codigo_opcion=codigo_opcion)
    if not claves:
        return []
    out: List[Dict[str, Any]] = []
    for faq in faqs or []:
        if not _vigente(faq):
            continue
        if _faq_coincide_claves(faq, claves):
            out.append(faq)
    return sorted(
        out,
        key=lambda f: (-int(f.get("prioridad") or 0), int(f.get("id") or 0)),
    )


def construir_respuesta_menu_faq(
    *,
    opcion: Optional[Dict[str, Any]],
    faqs: List[Dict[str, Any]],
    texto_usuario: str,
    presentacion: Dict[str, Any],
    intencion_forzada: Optional[str] = None,
) -> Tuple[str, Optional[Dict[str, Any]], bool]:
    """
    Resuelve opciones tipo FAQ del menú.

    "Cómo funciona" (agencia):
      1) respuesta_personalizada de la opción
      2) descripcion_agencia configurada en el panel
      3) FAQ solo si el usuario hace una pregunta concreta
      4) mensaje orientativo si falta configurar

    Otras opciones (p. ej. Continuar proceso):
      FAQs de la intención / búsqueda / textos de respaldo.

    Retorna (texto, lista_detalle|None, encontrado).
    """
    opcion = opcion or {}
    intencion = str(intencion_forzada or opcion.get("intencion") or "").strip()
    codigo = _normalizar(str(opcion.get("codigo") or ""))
    titulo_op = str(opcion.get("titulo") or "").strip()
    texto_in = str(texto_usuario or "").strip()
    personalizada = str(opcion.get("respuesta_personalizada") or "").strip()
    desc_agencia = str(presentacion.get("descripcion_agencia") or "").strip()
    desc_op = str(opcion.get("descripcion") or "").strip()

    es_como_funciona = (
        _normalizar(intencion) == "agencia"
        or codigo in {"como_funciona", "agencia"}
        or "funciona" in _normalizar(titulo_op)
    )

    def _es_seleccion_esta_opcion() -> bool:
        if not texto_in or _es_solo_seleccion_menu(texto_in):
            return True
        n = _normalizar(texto_in)
        t = _normalizar(titulo_op)
        if t and (n == t or n in t):
            return True
        if codigo and n == codigo:
            return True
        if n in {"como funciona", "como funciona la agencia", "funcionamiento"}:
            return True
        return False

    # —— Cómo funciona: texto configurado, no lista de FAQs ——
    if es_como_funciona:
        if _es_seleccion_esta_opcion():
            if personalizada:
                return personalizada, None, True
            if desc_agencia:
                return desc_agencia, None, True
            return (
                "Aún no tengo cargada la explicación de cómo funciona la agencia. "
                "Configúrala en el panel (Descripción de la agencia / Cómo funciona) "
                "o escribe *asesor* para hablar con el equipo.",
                None,
                True,
            )
        # Pregunta concreta → FAQ puntual (sin listar todas).
        texto = _buscar_faq(faqs or [], intencion or None, texto_in)
        if texto:
            return texto, None, True
        texto = _buscar_faq(faqs or [], None, texto_in)
        if texto:
            return texto, None, True
        if personalizada:
            return personalizada, None, True
        if desc_agencia:
            return desc_agencia, None, True
        return "", None, False

    # —— Resto (proceso, faq genérico, etc.) ——
    texto_busqueda = texto_in
    if (not texto_busqueda) or _es_solo_seleccion_menu(texto_busqueda):
        texto_busqueda = " ".join(
            p for p in (titulo_op, desc_op, intencion) if p
        )

    if personalizada and _es_seleccion_esta_opcion():
        return personalizada, None, True

    faqs_int = _faqs_por_intencion(
        faqs, intencion, codigo_opcion=str(opcion.get("codigo") or "")
    )
    items_faq: List[Dict[str, Any]] = []
    for faq in faqs_int:
        detalle = str(
            faq.get("respuesta_completa") or faq.get("respuesta_corta") or ""
        ).strip()
        if not detalle:
            continue
        pregunta = str(faq.get("pregunta") or faq.get("codigo") or "Información").strip()
        items_faq.append(
            {
                "n": len(items_faq) + 1,
                "id": faq.get("id"),
                "titulo": pregunta,
                "detalle": detalle,
            }
        )

    if len(items_faq) > 1:
        texto, lista, _det = construir_respuesta_lista_o_detalle(
            texto_usuario,
            items_faq,
            tipo=f"faq_{_normalizar(intencion) or 'info'}",
            titulo=titulo_op or "Información",
            introduccion="Puedo contarte sobre:",
            presentacion=presentacion,
        )
        return texto, lista, True

    if len(items_faq) == 1:
        return items_faq[0]["detalle"], None, True

    texto = _buscar_faq(faqs or [], intencion or None, texto_busqueda)
    if texto:
        return texto, None, True

    if texto_in and not _es_solo_seleccion_menu(texto_in):
        texto = _buscar_faq(faqs or [], None, texto_in)
        if texto:
            return texto, None, True

    if personalizada:
        return personalizada, None, True

    if _normalizar(intencion) == "proceso" or codigo == "continuar_proceso":
        if desc_op and len(desc_op) > 40:
            return desc_op, None, True
        return (
            "Para continuar con el proceso puedes preguntarme lo que necesites "
            "o escribir *asesor* para que una persona del equipo te guíe.",
            None,
            True,
        )

    if desc_op and len(desc_op) > 40:
        return desc_op, None, True

    return "", None, False
