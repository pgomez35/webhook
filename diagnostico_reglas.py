"""
Reglas centralizadas del diagnóstico de aspirantes (Chatbot Talentum).
Modificar pesos/umbrales aquí; no dispersar valores por el proyecto.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, Optional, Tuple

# --- Pesos globales ---
PESO_REQUISITOS = Decimal("0.30")
PESO_MERCADO = Decimal("0.30")
PESO_TALENTO = Decimal("0.40")

# --- Talento ---
PUNTOS_TALENTO = {
    "bueno": 100,
    "regular": 60,
    "malo": 20,
}

# --- Clasificación por puntaje ---
UMBRAL_BUENO = Decimal("75")
UMBRAL_REGULAR = Decimal("50")

# --- TikTok: seguidores ---
TIKTOK_SEGUIDORES = (
    (1000, 20),
    (10000, 50),
    (50000, 75),
    (None, 100),
)

# --- TikTok: me gusta ---
TIKTOK_ME_GUSTA = (
    (10000, 20),
    (100000, 50),
    (500000, 75),
    (None, 100),
)

TIKTOK_PESO_SEGUIDORES = Decimal("0.70")
TIKTOK_PESO_ME_GUSTA = Decimal("0.30")

# --- BIGO: semillas ---
BIGO_SEMILLAS = (
    (10000, 20),
    (100000, 50),
    (1000000, 75),
    (None, 100),
)

MOTIVO_BLOQUEO_MENOR = "no_cumple_mayoria_edad"

_SUFIJOS = (
    (re.compile(r"^(millones?|millons?|millions?)$", re.I), Decimal("1000000")),
    (re.compile(r"^(mil|miles|thousands?)$", re.I), Decimal("1000")),
    (re.compile(r"^m$", re.I), Decimal("1000000")),
    (re.compile(r"^k$", re.I), Decimal("1000")),
)


def _to_decimal(raw: str) -> Decimal:
    s = (raw or "").strip().replace(" ", "")
    if not s:
        raise ValueError("número vacío")
    # 1.200,5 (EU) vs 1,200.5 (US) vs 81.5 / 81,5 / 1.200 (miles)
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        partes = s.split(",")
        if len(partes) == 2 and len(partes[1]) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "." in s:
        partes = s.split(".")
        if len(partes) > 2:
            s = s.replace(".", "")
        elif len(partes) == 2 and len(partes[1]) == 3 and len(partes[0]) <= 3:
            # miles: 1.200 → 1200 (no confundir con 81.5)
            s = s.replace(".", "")
        # si hay 1-2 decimales (81.5, 265.1) se deja
    return Decimal(s)


def parse_numero_abreviado(valor: Any) -> Optional[int]:
    """
    Convierte valores abreviados a entero.
    Acepta K/M, mil/millón, thousand/million, punto o coma decimal.
    """
    if valor is None:
        return None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor
    if isinstance(valor, float):
        return int(Decimal(str(valor)).to_integral_value(rounding=ROUND_HALF_UP))

    texto = str(valor).strip()
    if not texto:
        return None

    m = re.match(
        r"^([+-]?\d[\d\s.,]*)\s*([A-Za-zÁÉÍÓÚáéíóúüÜñÑ]+)?\s*$",
        texto,
    )
    if not m:
        # Solo letras tipo "2K" ya cubierto; intentar sin espacios internos raros
        m = re.match(r"^([+-]?\d[\d.,]*)\s*([KkMm]|mil(?:es)?|millones?|thousand|thousands|million|millions)?\s*$", texto, re.I)
        if not m:
            return None

    num_raw = m.group(1)
    suf_raw = (m.group(2) or "").strip()
    try:
        base = _to_decimal(num_raw)
    except (InvalidOperation, ValueError):
        return None

    factor = Decimal("1")
    if suf_raw:
        matched = False
        for rx, fac in _SUFIJOS:
            if rx.match(suf_raw):
                factor = fac
                matched = True
                break
        if not matched:
            return None

    total = (base * factor).to_integral_value(rounding=ROUND_HALF_UP)
    return int(total)


def _banda(valor: Optional[int], bands: Tuple[Tuple[Optional[int], int], ...]) -> Optional[int]:
    if valor is None:
        return None
    v = int(valor)
    for limite, puntos in bands:
        if limite is None or v < limite:
            return puntos
    return bands[-1][1]


def clasificar_puntaje(puntaje: Optional[Decimal]) -> Optional[str]:
    if puntaje is None:
        return None
    if puntaje >= UMBRAL_BUENO:
        return "bueno"
    if puntaje >= UMBRAL_REGULAR:
        return "regular"
    return "malo"


def puntaje_talento(calificacion: Optional[str]) -> Optional[int]:
    if not calificacion:
        return None
    return PUNTOS_TALENTO.get(str(calificacion).strip().lower())


def puntaje_requisitos(
    *,
    mayor_edad: Optional[bool],
    disponibilidad_live: Optional[bool],
) -> Tuple[Optional[int], Optional[str], Optional[str], bool]:
    """
    Retorna (puntaje, resultado, motivo_bloqueo, incompleto).
    """
    if mayor_edad is None or disponibilidad_live is None:
        return None, None, None, True
    if mayor_edad is False:
        return 0, "malo", MOTIVO_BLOQUEO_MENOR, False
    if disponibilidad_live is True:
        return 100, "bueno", None, False
    return 0, "malo", None, False


def puntaje_mercado_tiktok(metricas: Dict[str, Any]) -> Tuple[Optional[Decimal], Optional[str], Dict[str, Any]]:
    seguidores = metricas.get("seguidores")
    me_gusta = metricas.get("me_gusta")
    if seguidores is None or me_gusta is None:
        return None, None, {"incompleto": True}
    p_seg = _banda(int(seguidores), TIKTOK_SEGUIDORES)
    p_likes = _banda(int(me_gusta), TIKTOK_ME_GUSTA)
    if p_seg is None or p_likes is None:
        return None, None, {"incompleto": True}
    total = (
        Decimal(p_seg) * TIKTOK_PESO_SEGUIDORES
        + Decimal(p_likes) * TIKTOK_PESO_ME_GUSTA
    )
    total = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return total, clasificar_puntaje(total), {
        "puntaje_seguidores": p_seg,
        "puntaje_me_gusta": p_likes,
    }


def puntaje_mercado_bigo(metricas: Dict[str, Any]) -> Tuple[Optional[Decimal], Optional[str], Dict[str, Any]]:
    semillas = metricas.get("semillas")
    if semillas is None:
        return None, None, {"incompleto": True}
    p = _banda(int(semillas), BIGO_SEMILLAS)
    if p is None:
        return None, None, {"incompleto": True}
    total = Decimal(p)
    return total, clasificar_puntaje(total), {"puntaje_semillas": p}


def puntaje_mercado_manual(calificacion: Optional[str]) -> Tuple[Optional[Decimal], Optional[str], Dict[str, Any]]:
    """Otras plataformas: mercado elegido manualmente (bueno/regular/malo)."""
    pts = puntaje_talento(calificacion)  # misma escala
    if pts is None:
        return None, None, {"incompleto": True}
    total = Decimal(pts)
    return total, clasificar_puntaje(total), {"origen": "manual"}


def calcular_diagnostico(
    *,
    plataforma_codigo: str,
    mayor_edad: Optional[bool],
    disponibilidad_live: Optional[bool],
    metricas: Dict[str, Any],
    talento_calificacion: Optional[str],
    mercado_manual: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Cálculo definitivo 30/30/40. No inventa puntajes si faltan datos.
    """
    p_req, r_req, motivo, incompleto_req = puntaje_requisitos(
        mayor_edad=mayor_edad,
        disponibilidad_live=disponibilidad_live,
    )
    p_tal = puntaje_talento(talento_calificacion)
    r_tal = clasificar_puntaje(Decimal(p_tal)) if p_tal is not None else None

    codigo = (plataforma_codigo or "").strip().lower()
    detalle_mercado: Dict[str, Any] = {}
    if codigo == "tiktok":
        p_mer, r_mer, detalle_mercado = puntaje_mercado_tiktok(metricas or {})
    elif codigo == "bigo":
        p_mer, r_mer, detalle_mercado = puntaje_mercado_bigo(metricas or {})
    else:
        p_mer, r_mer, detalle_mercado = puntaje_mercado_manual(mercado_manual)

    incompleto = bool(
        incompleto_req
        or p_req is None
        or p_mer is None
        or p_tal is None
    )

    out: Dict[str, Any] = {
        "puntaje_requisitos": p_req,
        "resultado_requisitos": r_req,
        "puntaje_mercado": float(p_mer) if p_mer is not None else None,
        "resultado_mercado": r_mer,
        "puntaje_talento": p_tal,
        "resultado_talento": r_tal,
        "puntaje_global": None,
        "resultado_global": None,
        "motivo_bloqueo": motivo,
        "incompleto": incompleto,
        "detalle_mercado": detalle_mercado,
        "pesos": {
            "requisitos": float(PESO_REQUISITOS),
            "mercado": float(PESO_MERCADO),
            "talento": float(PESO_TALENTO),
        },
    }

    if incompleto:
        return out

    global_dec = (
        Decimal(p_req) * PESO_REQUISITOS
        + Decimal(str(p_mer)) * PESO_MERCADO
        + Decimal(p_tal) * PESO_TALENTO
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if motivo == MOTIVO_BLOQUEO_MENOR:
        out["puntaje_global"] = float(global_dec)
        out["resultado_global"] = "malo"
        return out

    out["puntaje_global"] = float(global_dec)
    out["resultado_global"] = clasificar_puntaje(global_dec)
    return out


_MARCADOR_IDENTIFICADOR = "{identificador}"


def normalizar_identificador_perfil(identificador: Optional[str]) -> Optional[str]:
    """
    Espacios externos fuera; si comienza por @, elimina solo el @ inicial.
    """
    if identificador is None:
        return None
    ident = str(identificador).strip()
    if not ident:
        return None
    if ident.startswith("@"):
        ident = ident[1:]
    ident = ident.strip()
    return ident or None


def construir_url_perfil(
    template: Optional[str],
    identificador: Optional[str],
) -> Optional[str]:
    """
    Construye URL desde chatbot.plataformas.perfil_url_template.
    No inventa hosts; si falla cualquier validación retorna None.
    """
    from urllib.parse import quote

    plantilla = (template or "").strip()
    if not plantilla:
        return None
    if not plantilla.lower().startswith("https://"):
        return None
    if _MARCADOR_IDENTIFICADOR not in plantilla:
        return None

    ident = normalizar_identificador_perfil(identificador)
    if not ident:
        return None

    # Codifica de forma segura; conserva caracteres habituales de usuario (._-~)
    ident_enc = quote(ident, safe="._-~")
    return plantilla.replace(_MARCADOR_IDENTIFICADOR, ident_enc)
