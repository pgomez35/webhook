"""Reglas de forma y solape para reportes Backstage (semanal / mensual)."""
from __future__ import annotations

import calendar
from datetime import date
from typing import Any, Iterable, List, Optional, Sequence, Tuple

DIAS_SEMANA_ES = (
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
)


def nombre_dia_semana(d: date) -> str:
    return DIAS_SEMANA_ES[d.weekday()]


def formatear_periodo_humano(inicio: date, fin: date) -> str:
    return (
        f"{inicio.isoformat()} ({nombre_dia_semana(inicio)}) a "
        f"{fin.isoformat()} ({nombre_dia_semana(fin)})"
    )


def es_semana_lunes_domingo(inicio: date, fin: date) -> bool:
    return (
        inicio.weekday() == 0
        and fin.weekday() == 6
        and (fin - inicio).days == 6
    )


def es_mes_calendario_completo(inicio: date, fin: date) -> bool:
    if inicio.day != 1:
        return False
    if inicio.year != fin.year or inicio.month != fin.month:
        return False
    ultimo = calendar.monthrange(inicio.year, inicio.month)[1]
    return fin.day == ultimo


def periodos_se_solapan(
    a_inicio: date,
    a_fin: date,
    b_inicio: date,
    b_fin: date,
) -> bool:
    return a_inicio <= b_fin and a_fin >= b_inicio


def es_mismo_periodo(
    a_inicio: date,
    a_fin: date,
    b_inicio: date,
    b_fin: date,
) -> bool:
    return a_inicio == b_inicio and a_fin == b_fin


def mensaje_error_forma_periodo(tipo: str, inicio: date, fin: date) -> str:
    humano = formatear_periodo_humano(inicio, fin)
    if tipo == "semanal":
        return (
            "El reporte semanal debe ser de lunes a domingo (7 días calendario). "
            f"El periodo detectado es {humano}. "
            "En Backstage selecciona de lunes a domingo."
        )
    if tipo == "mensual":
        return (
            "El reporte mensual debe cubrir el mes calendario completo "
            "(del día 1 al último día del mes). "
            f"El periodo detectado es {humano}."
        )
    return f"Periodo inválido: {humano}."


def validar_forma_periodo(tipo: str, inicio: date, fin: date) -> None:
    if inicio > fin:
        raise ValueError(
            f"El periodo {formatear_periodo_humano(inicio, fin)} tiene fechas invertidas."
        )
    if tipo == "semanal" and not es_semana_lunes_domingo(inicio, fin):
        raise ValueError(mensaje_error_forma_periodo(tipo, inicio, fin))
    if tipo == "mensual" and not es_mes_calendario_completo(inicio, fin):
        raise ValueError(mensaje_error_forma_periodo(tipo, inicio, fin))


def validar_periodos_entre_si(periodos: Sequence[Tuple[date, date]]) -> None:
    for i, (a_inicio, a_fin) in enumerate(periodos):
        for b_inicio, b_fin in periodos[i + 1 :]:
            if es_mismo_periodo(a_inicio, a_fin, b_inicio, b_fin):
                continue
            if periodos_se_solapan(a_inicio, a_fin, b_inicio, b_fin):
                raise ValueError(
                    "El archivo contiene periodos que se solapan: "
                    f"{formatear_periodo_humano(a_inicio, a_fin)} y "
                    f"{formatear_periodo_humano(b_inicio, b_fin)}."
                )


def validar_periodos_cargue(tipo: str, periodos: Sequence[Tuple[date, date]]) -> None:
    if not periodos:
        raise ValueError("No se detectó ningún periodo de datos en el archivo.")
    for inicio, fin in periodos:
        validar_forma_periodo(tipo, inicio, fin)
    validar_periodos_entre_si(periodos)


def payload_periodo_detectado(
    inicio: date,
    fin: date,
    tipo_inferido: Optional[str] = None,
) -> dict[str, Any]:
    item = {
        "periodo_inicio": inicio.isoformat(),
        "periodo_fin": fin.isoformat(),
        "dias": (fin - inicio).days,
        "dia_inicio": nombre_dia_semana(inicio),
        "dia_fin": nombre_dia_semana(fin),
        "etiqueta": formatear_periodo_humano(inicio, fin),
    }
    if tipo_inferido is not None:
        item["tipo_inferido"] = tipo_inferido
    return item


def mensaje_solape(
    tipo_etiqueta: str,
    inicio: date,
    fin: date,
    existente_inicio: Any = None,
    existente_fin: Any = None,
) -> str:
    msg = (
        f"Ya existe un reporte {tipo_etiqueta} cargado que se solapa con el periodo "
        f"{formatear_periodo_humano(inicio, fin)}."
    )
    if existente_inicio and existente_fin:
        try:
            e_ini = existente_inicio if isinstance(existente_inicio, date) else date.fromisoformat(str(existente_inicio)[:10])
            e_fin = existente_fin if isinstance(existente_fin, date) else date.fromisoformat(str(existente_fin)[:10])
            msg += f" El periodo existente es {formatear_periodo_humano(e_ini, e_fin)}."
        except Exception:
            msg += f" El periodo existente es {existente_inicio} a {existente_fin}."
    return msg


def listar_periodos_unicos(valores: Iterable[Any], parse_periodo) -> List[Tuple[date, date]]:
    periodos: List[Tuple[date, date]] = []
    vistos = set()
    for value in valores:
        try:
            inicio, fin = parse_periodo(value)
        except Exception:
            raise ValueError(
                f"Formato de periodo inválido: {value}. Use YYYY-MM-DD ~ YYYY-MM-DD."
            )
        key = (inicio, fin)
        if key not in vistos:
            vistos.add(key)
            periodos.append(key)
    return periodos
