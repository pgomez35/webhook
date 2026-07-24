"""
Lógica de disponibilidad semanal y bloqueos para agendamientos.

Tablas (schema del tenant vía search_path):
  - disponibilidad_agendamiento
  - bloqueos_agendamiento
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from psycopg2.extras import RealDictCursor

from main_configuracion import get_config


def _parse_time(value: Any) -> Optional[time]:
    if value is None:
        return None
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0)
    texto = str(value).strip()
    if not texto:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(texto, fmt).time()
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail=f"Hora inválida: {value}")


def _time_to_str(value: Optional[time]) -> Optional[str]:
    if value is None:
        return None
    return value.strftime("%H:%M")


def _row_disponibilidad(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "dia_semana": int(row["dia_semana"]),
        "hora_inicio": _time_to_str(_parse_time(row["hora_inicio"])),
        "hora_fin": _time_to_str(_parse_time(row["hora_fin"])),
        "activo": bool(row["activo"]),
    }


def _row_bloqueo(row: Dict[str, Any]) -> Dict[str, Any]:
    hi = _parse_time(row.get("hora_inicio"))
    hf = _parse_time(row.get("hora_fin"))
    return {
        "id": int(row["id"]),
        "fecha": row["fecha"].isoformat() if isinstance(row["fecha"], date) else str(row["fecha"]),
        "hora_inicio": _time_to_str(hi),
        "hora_fin": _time_to_str(hf),
        "motivo": row.get("motivo"),
        "activo": bool(row["activo"]),
        "dia_completo": hi is None and hf is None,
    }


def _franjas_se_solapan(a_ini: time, a_fin: time, b_ini: time, b_fin: time) -> bool:
    return a_ini < b_fin and b_ini < a_fin


def hay_disponibilidad_configurada(cur) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM disponibilidad_agendamiento
        WHERE activo = true
        LIMIT 1
        """
    )
    return cur.fetchone() is not None


def listar_disponibilidad(cur, solo_activos: bool = False) -> List[Dict[str, Any]]:
    sql = """
        SELECT id, dia_semana, hora_inicio, hora_fin, activo
        FROM disponibilidad_agendamiento
    """
    if solo_activos:
        sql += " WHERE activo = true"
    sql += " ORDER BY dia_semana, hora_inicio"
    cur.execute(sql)
    return [_row_disponibilidad(dict(r)) for r in cur.fetchall()]


def _assert_no_solape_franja(
    cur,
    dia_semana: int,
    hora_inicio: time,
    hora_fin: time,
    exclude_id: Optional[int] = None,
) -> None:
    cur.execute(
        """
        SELECT id, hora_inicio, hora_fin
        FROM disponibilidad_agendamiento
        WHERE dia_semana = %s
        """,
        (dia_semana,),
    )
    for row in cur.fetchall():
        rid = int(row["id"])
        if exclude_id is not None and rid == exclude_id:
            continue
        other_ini = _parse_time(row["hora_inicio"])
        other_fin = _parse_time(row["hora_fin"])
        if other_ini and other_fin and _franjas_se_solapan(hora_inicio, hora_fin, other_ini, other_fin):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"La franja se superpone con otra existente "
                    f"({_time_to_str(other_ini)}–{_time_to_str(other_fin)}) el mismo día."
                ),
            )


def crear_disponibilidad(cur, dia_semana: int, hora_inicio: Any, hora_fin: Any, activo: bool = True) -> Dict[str, Any]:
    if dia_semana < 1 or dia_semana > 7:
        raise HTTPException(status_code=400, detail="dia_semana debe estar entre 1 (lunes) y 7 (domingo).")
    hi = _parse_time(hora_inicio)
    hf = _parse_time(hora_fin)
    if hi is None or hf is None:
        raise HTTPException(status_code=400, detail="hora_inicio y hora_fin son obligatorias.")
    if hf <= hi:
        raise HTTPException(status_code=400, detail="hora_fin debe ser mayor que hora_inicio.")
    _assert_no_solape_franja(cur, dia_semana, hi, hf)
    cur.execute(
        """
        INSERT INTO disponibilidad_agendamiento (dia_semana, hora_inicio, hora_fin, activo)
        VALUES (%s, %s, %s, %s)
        RETURNING id, dia_semana, hora_inicio, hora_fin, activo
        """,
        (dia_semana, hi, hf, bool(activo)),
    )
    return _row_disponibilidad(dict(cur.fetchone()))


def actualizar_disponibilidad(
    cur,
    franja_id: int,
    dia_semana: Optional[int] = None,
    hora_inicio: Any = None,
    hora_fin: Any = None,
    activo: Optional[bool] = None,
) -> Dict[str, Any]:
    cur.execute(
        """
        SELECT id, dia_semana, hora_inicio, hora_fin, activo
        FROM disponibilidad_agendamiento
        WHERE id = %s
        """,
        (franja_id,),
    )
    actual = cur.fetchone()
    if not actual:
        raise HTTPException(status_code=404, detail="Franja de disponibilidad no encontrada.")

    nuevo_dia = int(dia_semana) if dia_semana is not None else int(actual["dia_semana"])
    if nuevo_dia < 1 or nuevo_dia > 7:
        raise HTTPException(status_code=400, detail="dia_semana debe estar entre 1 (lunes) y 7 (domingo).")

    hi = _parse_time(hora_inicio) if hora_inicio is not None else _parse_time(actual["hora_inicio"])
    hf = _parse_time(hora_fin) if hora_fin is not None else _parse_time(actual["hora_fin"])
    if hi is None or hf is None:
        raise HTTPException(status_code=400, detail="hora_inicio y hora_fin son obligatorias.")
    if hf <= hi:
        raise HTTPException(status_code=400, detail="hora_fin debe ser mayor que hora_inicio.")

    nuevo_activo = bool(activo) if activo is not None else bool(actual["activo"])
    _assert_no_solape_franja(cur, nuevo_dia, hi, hf, exclude_id=franja_id)

    cur.execute(
        """
        UPDATE disponibilidad_agendamiento
        SET dia_semana = %s,
            hora_inicio = %s,
            hora_fin = %s,
            activo = %s
        WHERE id = %s
        RETURNING id, dia_semana, hora_inicio, hora_fin, activo
        """,
        (nuevo_dia, hi, hf, nuevo_activo, franja_id),
    )
    return _row_disponibilidad(dict(cur.fetchone()))


def set_activo_disponibilidad(cur, franja_id: int, activo: bool) -> Dict[str, Any]:
    cur.execute(
        """
        UPDATE disponibilidad_agendamiento
        SET activo = %s
        WHERE id = %s
        RETURNING id, dia_semana, hora_inicio, hora_fin, activo
        """,
        (bool(activo), franja_id),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Franja de disponibilidad no encontrada.")
    return _row_disponibilidad(dict(row))


def eliminar_disponibilidad(cur, franja_id: int) -> None:
    cur.execute(
        "DELETE FROM disponibilidad_agendamiento WHERE id = %s RETURNING id",
        (franja_id,),
    )
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Franja de disponibilidad no encontrada.")


def listar_bloqueos(
    cur,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    solo_activos: bool = False,
) -> List[Dict[str, Any]]:
    clauses = []
    params: List[Any] = []
    if fecha_desde:
        clauses.append("fecha >= %s")
        params.append(fecha_desde)
    if fecha_hasta:
        clauses.append("fecha <= %s")
        params.append(fecha_hasta)
    if solo_activos:
        clauses.append("activo = true")
    sql = """
        SELECT id, fecha, hora_inicio, hora_fin, motivo, activo
        FROM bloqueos_agendamiento
    """
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY fecha DESC, hora_inicio NULLS FIRST"
    cur.execute(sql, params)
    return [_row_bloqueo(dict(r)) for r in cur.fetchall()]


def crear_bloqueo(
    cur,
    fecha: date,
    hora_inicio: Any = None,
    hora_fin: Any = None,
    motivo: Optional[str] = None,
    activo: bool = True,
) -> Dict[str, Any]:
    hi = _parse_time(hora_inicio) if hora_inicio not in (None, "") else None
    hf = _parse_time(hora_fin) if hora_fin not in (None, "") else None
    if (hi is None) != (hf is None):
        raise HTTPException(
            status_code=400,
            detail="Para un bloqueo parcial deben indicarse hora_inicio y hora_fin. Para día completo, ambas deben ser nulas.",
        )
    if hi is not None and hf is not None and hf <= hi:
        raise HTTPException(status_code=400, detail="hora_fin debe ser mayor que hora_inicio.")
    motivo_clean = (motivo or "").strip() or None
    if motivo_clean and len(motivo_clean) > 200:
        raise HTTPException(status_code=400, detail="El motivo no puede superar 200 caracteres.")

    cur.execute(
        """
        INSERT INTO bloqueos_agendamiento (fecha, hora_inicio, hora_fin, motivo, activo)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id, fecha, hora_inicio, hora_fin, motivo, activo
        """,
        (fecha, hi, hf, motivo_clean, bool(activo)),
    )
    return _row_bloqueo(dict(cur.fetchone()))


def actualizar_bloqueo(
    cur,
    bloqueo_id: int,
    fecha: Optional[date] = None,
    hora_inicio: Any = ...,
    hora_fin: Any = ...,
    motivo: Any = ...,
    activo: Optional[bool] = None,
) -> Dict[str, Any]:
    cur.execute(
        """
        SELECT id, fecha, hora_inicio, hora_fin, motivo, activo
        FROM bloqueos_agendamiento
        WHERE id = %s
        """,
        (bloqueo_id,),
    )
    actual = cur.fetchone()
    if not actual:
        raise HTTPException(status_code=404, detail="Bloqueo no encontrado.")

    nueva_fecha = fecha if fecha is not None else actual["fecha"]
    if hora_inicio is ...:
        hi = _parse_time(actual.get("hora_inicio"))
    else:
        hi = _parse_time(hora_inicio) if hora_inicio not in (None, "") else None
    if hora_fin is ...:
        hf = _parse_time(actual.get("hora_fin"))
    else:
        hf = _parse_time(hora_fin) if hora_fin not in (None, "") else None

    if (hi is None) != (hf is None):
        raise HTTPException(
            status_code=400,
            detail="Para un bloqueo parcial deben indicarse hora_inicio y hora_fin. Para día completo, ambas deben ser nulas.",
        )
    if hi is not None and hf is not None and hf <= hi:
        raise HTTPException(status_code=400, detail="hora_fin debe ser mayor que hora_inicio.")

    if motivo is ...:
        motivo_clean = actual.get("motivo")
    else:
        motivo_clean = (str(motivo).strip() if motivo is not None else "") or None
        if motivo_clean and len(motivo_clean) > 200:
            raise HTTPException(status_code=400, detail="El motivo no puede superar 200 caracteres.")

    nuevo_activo = bool(activo) if activo is not None else bool(actual["activo"])

    cur.execute(
        """
        UPDATE bloqueos_agendamiento
        SET fecha = %s,
            hora_inicio = %s,
            hora_fin = %s,
            motivo = %s,
            activo = %s
        WHERE id = %s
        RETURNING id, fecha, hora_inicio, hora_fin, motivo, activo
        """,
        (nueva_fecha, hi, hf, motivo_clean, nuevo_activo, bloqueo_id),
    )
    return _row_bloqueo(dict(cur.fetchone()))


def set_activo_bloqueo(cur, bloqueo_id: int, activo: bool) -> Dict[str, Any]:
    cur.execute(
        """
        UPDATE bloqueos_agendamiento
        SET activo = %s
        WHERE id = %s
        RETURNING id, fecha, hora_inicio, hora_fin, motivo, activo
        """,
        (bool(activo), bloqueo_id),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Bloqueo no encontrado.")
    return _row_bloqueo(dict(row))


def eliminar_bloqueo(cur, bloqueo_id: int) -> None:
    cur.execute(
        "DELETE FROM bloqueos_agendamiento WHERE id = %s RETURNING id",
        (bloqueo_id,),
    )
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Bloqueo no encontrado.")


def _anticipacion_bounds(tz: ZoneInfo) -> Tuple[datetime, Optional[datetime]]:
    """Retorna (min_local_now, max_local_datetime_or_None) en zona de la agencia."""
    ahora_local = datetime.now(tz)
    min_horas = 0
    max_dias = 60
    try:
        raw_min = get_config("anticipacion_minima_horas")
        if raw_min is not None and str(raw_min).strip() != "":
            min_horas = max(0, int(float(raw_min)))
    except Exception:
        pass
    try:
        raw_max = get_config("anticipacion_maxima_dias")
        if raw_max is not None and str(raw_max).strip() != "":
            max_dias = max(1, int(float(raw_max)))
    except Exception:
        pass

    minimo = ahora_local + timedelta(hours=min_horas)
    maximo = ahora_local + timedelta(days=max_dias)
    return minimo, maximo


def _slot_cubierto_por_franja(slot_ini: time, slot_fin: time, franja_ini: time, franja_fin: time) -> bool:
    return slot_ini >= franja_ini and slot_fin <= franja_fin


def _slot_bloqueado(slot_ini: time, slot_fin: time, bloqueos_dia: List[Dict[str, Any]]) -> bool:
    for b in bloqueos_dia:
        hi = _parse_time(b.get("hora_inicio"))
        hf = _parse_time(b.get("hora_fin"))
        if hi is None and hf is None:
            return True
        if hi is not None and hf is not None and _franjas_se_solapan(slot_ini, slot_fin, hi, hf):
            return True
    return False


def _agendamientos_ocupados_utc(cur, desde_utc: datetime, hasta_utc: datetime) -> List[Tuple[datetime, datetime]]:
    cur.execute(
        """
        SELECT fecha_inicio, fecha_fin
        FROM agendamientos
        WHERE fecha_inicio < %s
          AND fecha_fin > %s
        """,
        (hasta_utc, desde_utc),
    )
    ocupados = []
    for row in cur.fetchall():
        ini = row["fecha_inicio"] if isinstance(row, dict) else row[0]
        fin = row["fecha_fin"] if isinstance(row, dict) else row[1]
        if ini is None or fin is None:
            continue
        if getattr(ini, "tzinfo", None) is None:
            ini = ini.replace(tzinfo=ZoneInfo("UTC"))
        else:
            ini = ini.astimezone(ZoneInfo("UTC"))
        if getattr(fin, "tzinfo", None) is None:
            fin = fin.replace(tzinfo=ZoneInfo("UTC"))
        else:
            fin = fin.astimezone(ZoneInfo("UTC"))
        ocupados.append((ini, fin))
    return ocupados


def _solapa_utc(a_ini: datetime, a_fin: datetime, b_ini: datetime, b_fin: datetime) -> bool:
    return a_ini < b_fin and b_ini < a_fin


def calcular_horarios_disponibles(
    cur,
    zona_horaria: str,
    fecha_desde: date,
    fecha_hasta: date,
    duracion_minutos: int,
    intervalo_minutos: int = 30,
) -> Dict[str, Any]:
    if fecha_hasta < fecha_desde:
        raise HTTPException(status_code=400, detail="fecha_hasta debe ser >= fecha_desde.")
    if duracion_minutos <= 0:
        raise HTTPException(status_code=400, detail="duracion_minutos debe ser mayor que 0.")
    if intervalo_minutos <= 0:
        raise HTTPException(status_code=400, detail="intervalo_minutos debe ser mayor que 0.")

    try:
        tz = ZoneInfo(zona_horaria)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Zona horaria inválida: {zona_horaria}")

    configurada = hay_disponibilidad_configurada(cur)
    if not configurada:
        return {
            "configurada": False,
            "zona_horaria": zona_horaria,
            "duracion_minutos": duracion_minutos,
            "fechas": [],
            "mensaje": "La agencia aún no tiene franjas de disponibilidad configuradas.",
        }

    franjas = listar_disponibilidad(cur, solo_activos=True)
    franjas_por_dia: Dict[int, List[Dict[str, Any]]] = {}
    for f in franjas:
        franjas_por_dia.setdefault(f["dia_semana"], []).append(f)

    bloqueos = listar_bloqueos(cur, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, solo_activos=True)
    bloqueos_por_fecha: Dict[str, List[Dict[str, Any]]] = {}
    for b in bloqueos:
        bloqueos_por_fecha.setdefault(b["fecha"], []).append(b)

    minimo_local, maximo_local = _anticipacion_bounds(tz)

    desde_utc = datetime.combine(fecha_desde, time.min, tzinfo=tz).astimezone(ZoneInfo("UTC"))
    hasta_utc = datetime.combine(fecha_hasta + timedelta(days=1), time.min, tzinfo=tz).astimezone(ZoneInfo("UTC"))
    ocupados = _agendamientos_ocupados_utc(cur, desde_utc, hasta_utc)

    fechas_out: List[Dict[str, Any]] = []
    dia = fecha_desde
    while dia <= fecha_hasta:
        dia_semana = dia.isoweekday()  # 1=lunes ... 7=domingo
        franjas_dia = franjas_por_dia.get(dia_semana, [])
        if not franjas_dia:
            dia += timedelta(days=1)
            continue

        fecha_iso = dia.isoformat()
        bloqueos_dia = bloqueos_por_fecha.get(fecha_iso, [])
        if any(_parse_time(b.get("hora_inicio")) is None and _parse_time(b.get("hora_fin")) is None for b in bloqueos_dia):
            dia += timedelta(days=1)
            continue

        horarios: List[str] = []
        for franja in franjas_dia:
            f_ini = _parse_time(franja["hora_inicio"])
            f_fin = _parse_time(franja["hora_fin"])
            if not f_ini or not f_fin:
                continue
            cursor_dt = datetime.combine(dia, f_ini)
            fin_franja_dt = datetime.combine(dia, f_fin)
            while cursor_dt + timedelta(minutes=duracion_minutos) <= fin_franja_dt:
                slot_ini = cursor_dt.time()
                slot_fin_dt = cursor_dt + timedelta(minutes=duracion_minutos)
                slot_fin = slot_fin_dt.time()

                if not _slot_cubierto_por_franja(slot_ini, slot_fin, f_ini, f_fin):
                    cursor_dt += timedelta(minutes=intervalo_minutos)
                    continue
                if _slot_bloqueado(slot_ini, slot_fin, bloqueos_dia):
                    cursor_dt += timedelta(minutes=intervalo_minutos)
                    continue

                slot_local = datetime.combine(dia, slot_ini, tzinfo=tz)
                slot_local_fin = datetime.combine(dia, slot_fin, tzinfo=tz)
                if slot_local < minimo_local:
                    cursor_dt += timedelta(minutes=intervalo_minutos)
                    continue
                if maximo_local is not None and slot_local > maximo_local:
                    cursor_dt += timedelta(minutes=intervalo_minutos)
                    continue

                slot_utc = slot_local.astimezone(ZoneInfo("UTC"))
                slot_utc_fin = slot_local_fin.astimezone(ZoneInfo("UTC"))
                if any(_solapa_utc(slot_utc, slot_utc_fin, o_ini, o_fin) for o_ini, o_fin in ocupados):
                    cursor_dt += timedelta(minutes=intervalo_minutos)
                    continue

                horarios.append(_time_to_str(slot_ini))
                cursor_dt += timedelta(minutes=intervalo_minutos)

        if horarios:
            fechas_out.append(
                {
                    "fecha": fecha_iso,
                    "dia_semana": dia_semana,
                    "horarios": horarios,
                }
            )
        dia += timedelta(days=1)

    return {
        "configurada": True,
        "zona_horaria": zona_horaria,
        "duracion_minutos": duracion_minutos,
        "fechas": fechas_out,
    }


def validar_cita_contra_disponibilidad(
    cur,
    zona_horaria: str,
    inicio_utc: datetime,
    fin_utc: datetime,
    excluir_agendamiento_id: Optional[int] = None,
) -> None:
    """
    Valida en servidor al confirmar/reagendar.
    Si no hay franjas activas configuradas, no bloquea (modo aditivo / legacy).
    """
    if not hay_disponibilidad_configurada(cur):
        return

    try:
        tz = ZoneInfo(zona_horaria)
    except Exception:
        tz = ZoneInfo("UTC")

    if inicio_utc.tzinfo is None:
        inicio_utc = inicio_utc.replace(tzinfo=ZoneInfo("UTC"))
    else:
        inicio_utc = inicio_utc.astimezone(ZoneInfo("UTC"))
    if fin_utc.tzinfo is None:
        fin_utc = fin_utc.replace(tzinfo=ZoneInfo("UTC"))
    else:
        fin_utc = fin_utc.astimezone(ZoneInfo("UTC"))

    if fin_utc <= inicio_utc:
        raise HTTPException(status_code=400, detail="La fecha fin debe ser posterior a la fecha inicio.")

    local_ini = inicio_utc.astimezone(tz)
    local_fin = fin_utc.astimezone(tz)
    if local_ini.date() != local_fin.date():
        raise HTTPException(
            status_code=400,
            detail="La cita debe comenzar y terminar el mismo día local de la agencia.",
        )

    dia = local_ini.date()
    dia_semana = dia.isoweekday()
    slot_ini = local_ini.time().replace(microsecond=0)
    slot_fin = local_fin.time().replace(microsecond=0)

    minimo_local, maximo_local = _anticipacion_bounds(tz)
    if local_ini < minimo_local:
        raise HTTPException(
            status_code=409,
            detail="El horario seleccionado no respeta la anticipación mínima configurada.",
        )
    if maximo_local is not None and local_ini > maximo_local:
        raise HTTPException(
            status_code=409,
            detail="El horario seleccionado supera la anticipación máxima configurada.",
        )

    cur.execute(
        """
        SELECT hora_inicio, hora_fin
        FROM disponibilidad_agendamiento
        WHERE activo = true AND dia_semana = %s
        """,
        (dia_semana,),
    )
    franjas = cur.fetchall()
    if not franjas:
        raise HTTPException(
            status_code=409,
            detail="No hay disponibilidad configurada para ese día de la semana.",
        )

    cubierto = False
    for row in franjas:
        f_ini = _parse_time(row["hora_inicio"] if isinstance(row, dict) else row[0])
        f_fin = _parse_time(row["hora_fin"] if isinstance(row, dict) else row[1])
        if f_ini and f_fin and _slot_cubierto_por_franja(slot_ini, slot_fin, f_ini, f_fin):
            cubierto = True
            break
    if not cubierto:
        raise HTTPException(
            status_code=409,
            detail="El horario seleccionado está fuera de las franjas de disponibilidad de la agencia.",
        )

    cur.execute(
        """
        SELECT hora_inicio, hora_fin
        FROM bloqueos_agendamiento
        WHERE activo = true AND fecha = %s
        """,
        (dia,),
    )
    for row in cur.fetchall():
        hi = _parse_time(row["hora_inicio"] if isinstance(row, dict) else row[0])
        hf = _parse_time(row["hora_fin"] if isinstance(row, dict) else row[1])
        if hi is None and hf is None:
            raise HTTPException(status_code=409, detail="Esa fecha está bloqueada completamente.")
        if hi is not None and hf is not None and _franjas_se_solapan(slot_ini, slot_fin, hi, hf):
            raise HTTPException(status_code=409, detail="El horario seleccionado está bloqueado.")

    params: List[Any] = [fin_utc, inicio_utc]
    sql = """
        SELECT id
        FROM agendamientos
        WHERE fecha_inicio < %s
          AND fecha_fin > %s
    """
    if excluir_agendamiento_id is not None:
        sql += " AND id <> %s"
        params.append(excluir_agendamiento_id)
    sql += " LIMIT 1"
    cur.execute(sql, params)
    if cur.fetchone():
        raise HTTPException(
            status_code=409,
            detail="Ese horario ya fue reservado. Elige otro horario disponible.",
        )
