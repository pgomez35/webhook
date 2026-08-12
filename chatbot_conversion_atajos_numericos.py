"""
Atajos numéricos para el chatbot inteligente (conversion).

No es un menú informativo: solo interpreta números aislados como
atajos hacia conocimiento o "continuar proceso". El texto libre sigue
yendo a la IA.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("uvicorn.error")

CTX_KEY = "atajos_numericos"

_RE_SOLO_NUMERO = re.compile(
    r"^\s*(?:opci[oó]n\s*)?(\d{1,2})\s*[.)]?\s*$",
    re.IGNORECASE,
)


@dataclass
class ResultadoAtajo:
    """Respuesta directa o reescritura del mensaje para la IA."""

    respuesta: Optional[str] = None
    texto_para_ia: Optional[str] = None
    mapa_nuevo: Optional[Dict[str, Any]] = None
    limpiar_mapa: bool = False
    motivo: str = "atajo_numerico"


def es_seleccion_numerica_aislada(texto: str) -> Optional[str]:
    """
    True solo para mensajes esencialmente numéricos: "2", "opción 2", "2.".

    No captura "tengo 2 horas", "tengo 18 años", "he hecho 3 LIVE".
    """
    crudo = str(texto or "").strip()
    if not crudo or len(crudo) > 24:
        return None
    # Si hay letras fuera de "opcion/opción", no es menú.
    sin_opcion = re.sub(r"(?i)opci[oó]n", "", crudo)
    if re.search(r"[a-zA-ZáéíóúÁÉÍÓÚñÑ]", sin_opcion):
        return None
    m = _RE_SOLO_NUMERO.match(crudo)
    if not m:
        return None
    return str(int(m.group(1)))  # normaliza "01" → "1"


def leer_mapa_atajos(conversacion: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    ctx = (conversacion or {}).get("contexto") or {}
    if not isinstance(ctx, dict):
        return {}
    bloque = ctx.get(CTX_KEY) or {}
    if not isinstance(bloque, dict):
        return {}
    mapa = bloque.get("mapa") or {}
    return dict(mapa) if isinstance(mapa, dict) else {}


def escribir_mapa_atajos(
    conversacion: Dict[str, Any],
    mapa: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Persiste el mapa en conversacion.contexto (mutación in-place)."""
    ctx = dict(conversacion.get("contexto") or {})
    if mapa:
        ctx[CTX_KEY] = {"mapa": mapa}
    else:
        ctx.pop(CTX_KEY, None)
    conversacion["contexto"] = ctx
    return ctx


def mapa_menu_inicial() -> Dict[str, Any]:
    return {
        "1": {"kind": "conocimiento", "tipo": "requisitos"},
        "2": {"kind": "conocimiento", "tipo": "beneficios"},
        "3": {"kind": "conocimiento", "tipo": "bonos"},
        "4": {"kind": "continuar"},
    }


def texto_bienvenida_con_atajos(nombre_agencia: str) -> str:
    nombre = (nombre_agencia or "la agencia").strip() or "la agencia"
    return (
        f"¡Hola! 👋 Bienvenido(a) a {nombre}.\n"
        "\n"
        "Estoy aquí para ayudarte con tus dudas y orientarte sobre la agencia. "
        "Puedes preguntarme sobre:\n"
        "\n"
        "1. Requisitos para ingresar a la agencia.\n"
        "2. Beneficios que ofrecemos.\n"
        "3. Bonos disponibles.\n"
        "4. Quiero continuar con el proceso.\n"
        "\n"
        "O escríbeme directamente cualquier otra duda que tengas."
    )


def _items_conocimiento(
    tipo: str,
    *,
    requisitos: Optional[List[Dict[str, Any]]],
    beneficios: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    tipo_n = str(tipo or "").strip().lower()
    if tipo_n == "requisitos":
        return [
            r
            for r in (requisitos or [])
            if r
            and r.get("activo") is not False
            and r.get("permitir_mencion_automatica") is not False
            and r.get("visible_publicamente") is not False
        ]
    items: List[Dict[str, Any]] = []
    for b in beneficios or []:
        if not b or b.get("activo") is False:
            continue
        if b.get("permitir_mencion_automatica") is False:
            continue
        if b.get("visible_publicamente") is False:
            continue
        tipo_b = str(b.get("tipo") or "").lower()
        if tipo_n == "bonos" and tipo_b not in {"bono", "incentivo"}:
            continue
        if tipo_n == "beneficios" and tipo_b in {"bono", "incentivo"}:
            continue
        items.append(b)
    return items


def _titulo_item(it: Dict[str, Any]) -> str:
    return str(it.get("nombre") or it.get("titulo") or "").strip()


def _detalle_item(it: Dict[str, Any]) -> str:
    return str(
        it.get("descripcion")
        or it.get("texto_autorizado")
        or it.get("descripcion_corta")
        or it.get("descripcion_completa")
        or it.get("detalle")
        or ""
    ).strip()


def formatear_lista_interactiva(
    tipo: str,
    *,
    requisitos: Optional[List[Dict[str, Any]]] = None,
    beneficios: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Lista numerada + mapa de subopciones (índice 1-based → item)."""
    tipo_n = str(tipo or "").strip().lower()
    titulos = {
        "requisitos": "Requisitos",
        "beneficios": "Beneficios",
        "bonos": "Bonos disponibles",
    }
    titulo = titulos.get(tipo_n, "Información")
    items = _items_conocimiento(
        tipo_n, requisitos=requisitos, beneficios=beneficios
    )
    if not items:
        return (
            f"No tengo {titulo.lower()} configurados para compartir en este momento. "
            "Puedes preguntarme con tus propias palabras o elegir otra opción.",
            {},
        )
    lineas = [f"{titulo}:", ""]
    mapa: Dict[str, Any] = {}
    for i, it in enumerate(items, start=1):
        nombre = _titulo_item(it)
        desc = _detalle_item(it)
        if nombre and desc and desc != nombre:
            # En la lista corta solo el nombre; el detalle va al elegir el número.
            lineas.append(f"{i}. {nombre}")
        else:
            lineas.append(f"{i}. {nombre or desc}")
        mapa[str(i)] = {
            "kind": "item",
            "tipo": tipo_n,
            "indice": i - 1,
            "nombre": nombre,
            "detalle": desc or nombre,
        }
    lineas.append("")
    lineas.append("Escribe el número para más detalle, o pregúntame con tus palabras.")
    return "\n".join(lineas).strip(), mapa


def resolver_atajo_numerico(
    texto: str,
    *,
    conversacion: Dict[str, Any],
    requisitos: Optional[List[Dict[str, Any]]] = None,
    beneficios: Optional[List[Dict[str, Any]]] = None,
) -> Optional[ResultadoAtajo]:
    clave = es_seleccion_numerica_aislada(texto)
    if clave is None:
        return None
    mapa = leer_mapa_atajos(conversacion)
    if not mapa or clave not in mapa:
        return None

    entrada = mapa[clave]
    if not isinstance(entrada, dict):
        return None

    kind = str(entrada.get("kind") or "").strip().lower()
    logger.info(
        "[CHATBOT_ATAJO] seleccion=%s kind=%s tipo=%s",
        clave,
        kind,
        entrada.get("tipo"),
    )

    if kind == "continuar":
        return ResultadoAtajo(
            texto_para_ia="Quiero continuar con el proceso de ingreso a la agencia.",
            motivo="atajo_continuar",
        )

    if kind == "conocimiento":
        tipo = str(entrada.get("tipo") or "").strip().lower()
        respuesta, mapa_sub = formatear_lista_interactiva(
            tipo, requisitos=requisitos, beneficios=beneficios
        )
        return ResultadoAtajo(
            respuesta=respuesta,
            mapa_nuevo=mapa_sub or None,
            limpiar_mapa=not bool(mapa_sub),
            motivo=f"atajo_{tipo}",
        )

    if kind == "item":
        detalle = str(entrada.get("detalle") or entrada.get("nombre") or "").strip()
        nombre = str(entrada.get("nombre") or "").strip()
        if not detalle:
            return ResultadoAtajo(
                respuesta=(
                    "No tengo el detalle de ese punto en la configuración actual. "
                    "Puedes preguntarme de otra forma o elegir otro número."
                ),
                mapa_nuevo=mapa,
                motivo="atajo_item_sin_dato",
            )
        if nombre and detalle != nombre:
            texto_out = f"{nombre}\n\n{detalle}"
        else:
            texto_out = detalle
        # Conservar el mismo mapa (submenú) para seguir eligiendo números.
        return ResultadoAtajo(
            respuesta=texto_out,
            mapa_nuevo=mapa,
            motivo="atajo_item",
        )

    return None
