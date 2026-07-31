"""
Parsers determinísticos de cabecera de perfil (TikTok, BIGO, genérico).
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from diagnostico_reglas import parse_numero_abreviado

ParserFn = Callable[[str], Dict[str, Any]]

_PARSERS: Dict[str, ParserFn] = {}


def register_parser(codigo: str):
    def deco(fn: ParserFn):
        _PARSERS[codigo.strip().lower()] = fn
        return fn

    return deco


def obtener_parser(plataforma_codigo: str) -> Optional[ParserFn]:
    return _PARSERS.get((plataforma_codigo or "").strip().lower())


def _lineas_limpias(cabecera: str) -> List[str]:
    return [ln.strip() for ln in (cabecera or "").splitlines() if ln.strip()]


def _es_bio_ignorada(linea: str) -> bool:
    low = linea.lower().strip()
    return low.startswith("no bio") or low in {"no bio yet.", "no bio yet", "sin biografía"}


@register_parser("tiktok")
def parse_tiktok(cabecera: str) -> Dict[str, Any]:
    lineas = [ln for ln in _lineas_limpias(cabecera) if not _es_bio_ignorada(ln)]
    advertencias: List[str] = []
    campos_confirmacion: List[str] = []

    labels = {
        "following": "siguiendo",
        "siguiendo": "siguiendo",
        "followers": "seguidores",
        "seguidores": "seguidores",
        "likes": "me_gusta",
        "me gusta": "me_gusta",
        "me_gusta": "me_gusta",
    }

    metricas: Dict[str, Any] = {}
    identificador: Optional[str] = None
    nombre_perfil: Optional[str] = None

    # Emparejar valor + etiqueta (orden valor→etiqueta o etiqueta→valor)
    i = 0
    usados = set()
    while i < len(lineas):
        cur = lineas[i]
        cur_low = cur.lower()
        nxt = lineas[i + 1] if i + 1 < len(lineas) else None
        nxt_low = (nxt or "").lower()

        # valor luego etiqueta
        if nxt is not None and nxt_low in labels:
            clave = labels[nxt_low]
            num = parse_numero_abreviado(cur)
            if num is not None:
                metricas[clave] = num
                usados.add(i)
                usados.add(i + 1)
                i += 2
                continue
        # etiqueta luego valor
        if cur_low in labels and nxt is not None:
            clave = labels[cur_low]
            num = parse_numero_abreviado(nxt)
            if num is not None:
                metricas[clave] = num
                usados.add(i)
                usados.add(i + 1)
                i += 2
                continue
        i += 1

    # Identificador / nombre: primeras líneas no usadas que no sean números puros
    candidatos = []
    for idx, ln in enumerate(lineas):
        if idx in usados:
            continue
        if parse_numero_abreviado(ln) is not None and re.fullmatch(r"[\d\s.,KkMm]+", ln.replace(" ", "")):
            continue
        if ln.lower() in labels:
            continue
        candidatos.append(ln)

    if candidatos:
        # Primera línea candidata = identificador (o nombre si hay @)
        first = candidatos[0].lstrip("@").strip()
        identificador = first
        if len(candidatos) > 1 and candidatos[1].lstrip("@").strip() != first:
            # Si la segunda es distinta, puede ser nombre visible
            second = candidatos[1].lstrip("@").strip()
            if second.lower() != first.lower():
                nombre_perfil = second
            else:
                nombre_perfil = first
        else:
            nombre_perfil = first
        # Si hay dos líneas idénticas (caso blackvideo), una sola identidad
        if len(candidatos) >= 2 and candidatos[0].lstrip("@") == candidatos[1].lstrip("@"):
            identificador = candidatos[0].lstrip("@").strip()
            nombre_perfil = identificador

    faltantes = [k for k in ("siguiendo", "seguidores", "me_gusta") if k not in metricas]
    if faltantes:
        advertencias.append(f"Métricas no detectadas: {', '.join(faltantes)}")
        campos_confirmacion.extend(faltantes)
    if not identificador:
        advertencias.append("No se detectó identificador de usuario")
        campos_confirmacion.append("identificador")

    return {
        "plataforma_codigo": "tiktok",
        "identificador_detectado": identificador,
        "nombre_perfil": nombre_perfil,
        "metricas": metricas,
        "advertencias": advertencias,
        "campos_confirmacion": campos_confirmacion,
        "parser_especializado": True,
        "dato_secundario": None,
    }


@register_parser("bigo")
def parse_bigo(cabecera: str) -> Dict[str, Any]:
    lineas = _lineas_limpias(cabecera)
    advertencias: List[str] = []
    campos_confirmacion: List[str] = ["dato_secundario_tipo"]

    nombre_perfil: Optional[str] = None
    identificador: Optional[str] = None
    semillas: Optional[int] = None
    dato_secundario: Optional[int] = None

    # Buscar línea BIGO ID
    resto_nums: List[int] = []
    for ln in lineas:
        m = re.search(r"bigo\s*id\s*:\s*(.+)$", ln, re.I)
        if m:
            nums = re.findall(r"\d+", m.group(1))
            if nums:
                identificador = nums[0]
                for n in nums[1:]:
                    resto_nums.append(int(n))
            continue
        if nombre_perfil is None and not re.search(r"bigo\s*id", ln, re.I):
            nombre_perfil = ln

    if len(resto_nums) >= 1:
        semillas = resto_nums[0]
    if len(resto_nums) >= 2:
        dato_secundario = resto_nums[1]
        advertencias.append(
            "Dato adicional por confirmar: no se asume que sea espectadores"
        )

    if not identificador:
        advertencias.append("No se detectó BIGO ID")
        campos_confirmacion.append("identificador")
    if semillas is None:
        advertencias.append("No se detectaron semillas")
        campos_confirmacion.append("semillas")

    metricas: Dict[str, Any] = {}
    if semillas is not None:
        metricas["semillas"] = semillas
    if dato_secundario is not None:
        metricas["dato_secundario"] = dato_secundario
        metricas["dato_secundario_tipo"] = None  # evaluador elige

    return {
        "plataforma_codigo": "bigo",
        "identificador_detectado": identificador,
        "nombre_perfil": nombre_perfil,
        "metricas": metricas,
        "advertencias": advertencias,
        "campos_confirmacion": campos_confirmacion,
        "parser_especializado": True,
        "dato_secundario": dato_secundario,
        "dato_secundario_opciones": [
            "espectadores",
            "fans",
            "siguiendo",
            "otro",
            "ignorar",
        ],
    }


def parse_generico(cabecera: str, plataforma_codigo: str) -> Dict[str, Any]:
    return {
        "plataforma_codigo": (plataforma_codigo or "").strip().lower(),
        "identificador_detectado": None,
        "nombre_perfil": None,
        "metricas": {},
        "advertencias": [
            "Plataforma sin parser especializado: complete métricas manualmente"
        ],
        "campos_confirmacion": ["identificador", "metricas", "mercado_manual"],
        "parser_especializado": False,
        "dato_secundario": None,
    }


def analizar_cabecera(cabecera: str, plataforma_codigo: str) -> Dict[str, Any]:
    codigo = (plataforma_codigo or "").strip().lower()
    parser = obtener_parser(codigo)
    if parser:
        return parser(cabecera)
    return parse_generico(cabecera, codigo)
