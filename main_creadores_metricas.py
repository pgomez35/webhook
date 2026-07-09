import io
import re
import traceback
from datetime import datetime, date
from typing import Optional, Any, List, Dict, Tuple

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from DataBase import get_connection_context

router = APIRouter()


# =========================================================
# MODELOS / SCHEMAS
# =========================================================

class MetaMensualManualIn(BaseModel):
    creador_id: int
    periodo_inicio: date
    periodo_fin: date
    meta_diamantes: Optional[int] = None
    meta_horas_live: Optional[int] = None
    meta_dias_validos: Optional[int] = None
    meta_emisiones: Optional[int] = None
    meta_nuevos_seguidores: Optional[int] = None
    fuente: Optional[str] = "manual"


class GenerarMetasPeriodoIn(BaseModel):
    periodo_inicio: date
    periodo_fin: date
    porcentaje_crecimiento_diamantes: Optional[float] = 0.20
    porcentaje_crecimiento_horas: Optional[float] = 0.10
    porcentaje_crecimiento_seguidores: Optional[float] = 0.15
    fuente: Optional[str] = "sistema"


class GenerarInsightsPeriodoIn(BaseModel):
    periodo_inicio: date
    periodo_fin: date


# =========================================================
# HELPERS DE LIMPIEZA
# =========================================================

def _clean_nan(value: Any) -> Any:
    if pd.isna(value):
        return None
    return value


def _to_str(value: Any) -> Optional[str]:
    value = _clean_nan(value)
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in ["nan", "none", "null", ""]:
        return None
    return text


def _to_int(value: Any) -> Optional[int]:
    value = _clean_nan(value)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value).strip()
    if not text or text.lower() in ["nan", "none", "null", "-"]:
        return None

    text = text.replace(",", "")
    text = re.sub(r"[^0-9\-]", "", text)
    if text in ["", "-"]:
        return None
    return int(text)


def _to_percent_numeric(value: Any) -> Optional[float]:
    value = _clean_nan(value)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)

    text = str(value).strip()
    if not text or text.lower() in ["nan", "none", "null", "-"]:
        return None

    text = text.replace("%", "").replace(",", "").strip()
    try:
        return round(float(text), 2)
    except Exception:
        return None


def _parse_periodo(value: Any) -> Tuple[date, date]:
    text = _to_str(value)
    if not text:
        raise ValueError("Periodo de datos vacío")

    # Formato esperado: 2026-02-01 ~ 2026-02-25
    parts = [p.strip() for p in text.split("~")]
    if len(parts) != 2:
        raise ValueError(f"Formato de periodo inválido: {text}")

    periodo_inicio = datetime.strptime(parts[0], "%Y-%m-%d").date()
    periodo_fin = datetime.strptime(parts[1], "%Y-%m-%d").date()
    return periodo_inicio, periodo_fin


def _parse_datetime_tiktok(value: Any) -> Optional[datetime]:
    text = _to_str(value)
    if not text:
        return None

    # Ejemplo: 2025-04-23 23:05:22 (UTC+0)
    text = re.sub(r"\s*\(UTC.*?\)", "", text).strip()

    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except Exception:
        try:
            return pd.to_datetime(text).to_pydatetime()
        except Exception:
            return None


def _duration_to_minutes(value: Any) -> Optional[int]:
    value = _clean_nan(value)
    if value is None:
        return None

    if isinstance(value, (int, float)):
        # Si TikTok lo exporta numérico, asumimos horas y convertimos a minutos.
        return int(round(float(value) * 60))

    text = str(value).strip().lower()
    if not text or text in ["nan", "none", "null", "-"]:
        return None

    hours = 0
    minutes = 0
    seconds = 0

    h_match = re.search(r"(\d+)\s*h", text)
    m_match = re.search(r"(\d+)\s*min", text)
    s_match = re.search(r"(\d+)\s*s", text)

    if h_match:
        hours = int(h_match.group(1))
    if m_match:
        minutes = int(m_match.group(1))
    if s_match:
        seconds = int(s_match.group(1))

    total = hours * 60 + minutes + (1 if seconds >= 30 else 0)
    return total


def _minutes_to_hours_int(minutes: Optional[int]) -> Optional[int]:
    if minutes is None:
        return None
    return int(round(minutes / 60))


# =========================================================
# MAPEO DEL EXCEL A DB
# =========================================================

REQUIRED_COLUMNS = [
    "Periodo de datos",
    "ID del creador",
    "Nombre de usuario del creador",
    "Hora de incorporación",
    "Días desde la incorporación",
    "Diamantes",
    "Duración de LIVE",
    "Días válidos de emisiones LIVE",
    "Nuevos seguidores",
    "Emisiones LIVE",
    "Diamantes en el último mes",
    "Duración de emisiones LIVE (en horas) durante el último mes",
    "Días válidos de emisiones LIVE del mes pasado",
    "Nuevos seguidores en el último mes",
    "Emisiones LIVE en el último mes",
    "Estado de graduación",
]

ESTADO_RANGO_COLUMNS = [
    "Estado de rango",
    "Estado del rango",
    "Estado de rango del creador",
    "Rango del creador",
]


def _leer_columna_opcional(row: pd.Series, columnas_posibles: List[str]) -> Optional[str]:
    for columna in columnas_posibles:
        if columna in row.index:
            valor = _to_str(row.get(columna))
            if valor:
                return valor
    return None


def _inferir_tipo_periodo(periodo_inicio: date, periodo_fin: date) -> str:
    dias = (periodo_fin - periodo_inicio).days
    if dias <= 10:
        return "semanal"
    if dias <= 31:
        return "mensual"
    return "otro"


def _validar_columnas_excel(df: pd.DataFrame) -> None:
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "mensaje": "El Excel no tiene todas las columnas requeridas.",
                "columnas_faltantes": missing,
                "columnas_recibidas": list(df.columns),
            },
        )


def _row_to_reporte(row: pd.Series) -> Dict[str, Any]:
    periodo_inicio, periodo_fin = _parse_periodo(row.get("Periodo de datos"))

    duracion_live_minutos = _duration_to_minutes(row.get("Duración de LIVE"))
    duracion_live_mes_minutos = _duration_to_minutes(
        row.get("Duración de emisiones LIVE (en horas) durante el último mes")
    )

    return {
        "creador_tiktok_id": _to_str(row.get("ID del creador")),
        "usuario_tiktok": _to_str(row.get("Nombre de usuario del creador")),
        "grupo": _to_str(row.get("Grupo")),
        "agente": _to_str(row.get("Agente")),
        "periodo_inicio": periodo_inicio,
        "periodo_fin": periodo_fin,
        "hora_incorporacion": _parse_datetime_tiktok(row.get("Hora de incorporación")),
        "dias_desde_incorporacion": _to_int(row.get("Días desde la incorporación")),
        "estado_graduacion": _to_str(row.get("Estado de graduación")),
        "estado_rango": _leer_columna_opcional(row, ESTADO_RANGO_COLUMNS),
        "diamantes_totales": _to_int(row.get("Diamantes")),
        "duracion_live_minutos": duracion_live_minutos,
        "dias_validos_emisiones_live": _to_int(row.get("Días válidos de emisiones LIVE")),
        "nuevos_seguidores": _to_int(row.get("Nuevos seguidores")),
        "emisiones_live": _to_int(row.get("Emisiones LIVE")),
        "diamantes_mes": _to_int(row.get("Diamantes en el último mes")),
        "duracion_live_mes_minutos": duracion_live_mes_minutos,
        "dias_validos_live_mes": _to_int(row.get("Días válidos de emisiones LIVE del mes pasado")),
        "nuevos_seguidores_mes": _to_int(row.get("Nuevos seguidores en el último mes")),
        "emisiones_live_mes": _to_int(row.get("Emisiones LIVE en el último mes")),
        "porcentaje_logro_diamantes": _to_percent_numeric(row.get("Diamantes - Porcentaje logrado")),
        "porcentaje_logro_duracion_live": _to_percent_numeric(row.get("Duración de LIVE - Porcentaje logrado")),
        "porcentaje_logro_dias_validos": _to_percent_numeric(row.get("Días válidos de emisiones LIVE - Porcentaje logrado")),
        "porcentaje_logro_nuevos_seguidores": _to_percent_numeric(row.get("Nuevos seguidores - Porcentaje logrado")),
        "porcentaje_logro_emisiones": _to_percent_numeric(row.get("Emisiones LIVE - Porcentaje logrado")),
        "variacion_diamantes_mes_anterior": _to_percent_numeric(row.get("Diamantes - frente al mes pasado")),
        "variacion_duracion_live_mes_anterior": _to_percent_numeric(row.get("Duración de LIVE - frente al mes pasado")),
        "variacion_dias_validos_mes_anterior": _to_percent_numeric(row.get("Días válidos de emisiones LIVE - frente al mes pasado")),
        "variacion_nuevos_seguidores_mes_anterior": _to_percent_numeric(row.get("Nuevos seguidores - frente al mes pasado")),
        "variacion_emisiones_mes_anterior": _to_percent_numeric(row.get("Emisiones LIVE - frente al mes pasado")),
        "partidas": _to_int(row.get("Partidas")),
        "diamantes_de_partidas": _to_int(row.get("Diamantes de partidas")),
        "nuevos_creadores_live": _to_str(row.get("Nuevos creadores LIVE")),
        "diamantes_modo_varios_invitados": _to_int(row.get("Diamantes del modo de varios invitados")),
        "diamantes_modo_varios_invitados_anfitrion": _to_int(row.get("Diamantes de varios invitados (como anfitrión)")),
        "diamantes_modo_varios_invitados_invitado": _to_int(row.get("Diamantes del modo de varios invitados (como invitado)")),
        "base_diamantes_antes_unirse": _to_int(row.get("Base de Diamantes antes de unirse")),
    }


# =========================================================
# HELPERS DB
# =========================================================

def _buscar_creador_por_tiktok(cur, creador_tiktok_id: str, usuario_tiktok: Optional[str]) -> Optional[int]:
    cur.execute(
        """
        SELECT id
        FROM creadores
        WHERE creador_tiktok_id = %s
           OR LOWER(usuario_tiktok) = LOWER(%s)
        LIMIT 1
        """,
        (creador_tiktok_id, usuario_tiktok),
    )
    row = cur.fetchone()
    return row["id"] if row else None


def _actualizar_creador_base(cur, creador_id: int, data: Dict[str, Any]) -> None:
    cur.execute(
        """
        UPDATE creadores
        SET
            creador_tiktok_id = COALESCE(creador_tiktok_id, %s),
            usuario_tiktok = COALESCE(usuario_tiktok, %s),
            updated_at = NOW()
        WHERE id = %s
        """,
        (data["creador_tiktok_id"], data["usuario_tiktok"], creador_id),
    )


def _registrar_importaciones_desde_df(
    cur,
    df: pd.DataFrame,
    archivo_nombre: Optional[str],
    archivo_origen: str,
) -> Dict[Tuple[date, date], int]:
    periodos_stats: Dict[Tuple[date, date], Dict[str, Any]] = {}

    for _, row in df.iterrows():
        try:
            periodo_inicio, periodo_fin = _parse_periodo(row.get("Periodo de datos"))
            key = (periodo_inicio, periodo_fin)
            periodos_stats.setdefault(key, {"filas": 0, "creadores": set()})
            periodos_stats[key]["filas"] += 1

            creador_tiktok_id = _to_str(row.get("ID del creador"))
            if creador_tiktok_id:
                periodos_stats[key]["creadores"].add(creador_tiktok_id)
        except Exception:
            continue

    importaciones: Dict[Tuple[date, date], int] = {}

    for (periodo_inicio, periodo_fin), stats in periodos_stats.items():
        tipo_periodo = _inferir_tipo_periodo(periodo_inicio, periodo_fin)

        cur.execute(
            """
            INSERT INTO creadores_reporte_importaciones (
                archivo_nombre,
                archivo_origen,
                periodo_inicio,
                periodo_fin,
                tipo_periodo,
                total_filas,
                total_creadores,
                estado,
                metadata_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'procesado', %s::jsonb)
            RETURNING id_importacion
            """,
            (
                archivo_nombre,
                archivo_origen,
                periodo_inicio,
                periodo_fin,
                tipo_periodo,
                stats["filas"],
                len(stats["creadores"]),
                "{}",
            ),
        )

        importaciones[(periodo_inicio, periodo_fin)] = cur.fetchone()["id_importacion"]

    return importaciones


def _upsert_reporte_integral(cur, data: Dict[str, Any], creador_id: Optional[int]) -> int:
    cur.execute(
        """
        INSERT INTO creadores_reporte_integral (
            creador_tiktok_id,
            creador_id,
            usuario_tiktok,
            grupo,
            agente,
            periodo_inicio,
            periodo_fin,
            hora_incorporacion,
            dias_desde_incorporacion,
            estado_graduacion,
            estado_rango,
            diamantes_totales,
            duracion_live_minutos,
            dias_validos_emisiones_live,
            nuevos_seguidores,
            emisiones_live,
            diamantes_mes,
            duracion_live_mes_minutos,
            dias_validos_live_mes,
            nuevos_seguidores_mes,
            emisiones_live_mes,
            porcentaje_logro_diamantes,
            porcentaje_logro_duracion_live,
            porcentaje_logro_dias_validos,
            porcentaje_logro_nuevos_seguidores,
            porcentaje_logro_emisiones,
            variacion_diamantes_mes_anterior,
            variacion_duracion_live_mes_anterior,
            variacion_dias_validos_mes_anterior,
            variacion_nuevos_seguidores_mes_anterior,
            variacion_emisiones_mes_anterior,
            partidas,
            diamantes_de_partidas,
            nuevos_creadores_live,
            diamantes_modo_varios_invitados,
            diamantes_modo_varios_invitados_anfitrion,
            diamantes_modo_varios_invitados_invitado,
            base_diamantes_antes_unirse,
            importacion_id,
            tipo_periodo,
            archivo_origen
        ) VALUES (
            %(creador_tiktok_id)s,
            %(creador_id)s,
            %(usuario_tiktok)s,
            %(grupo)s,
            %(agente)s,
            %(periodo_inicio)s,
            %(periodo_fin)s,
            %(hora_incorporacion)s,
            %(dias_desde_incorporacion)s,
            %(estado_graduacion)s,
            %(estado_rango)s,
            %(diamantes_totales)s,
            %(duracion_live_minutos)s,
            %(dias_validos_emisiones_live)s,
            %(nuevos_seguidores)s,
            %(emisiones_live)s,
            %(diamantes_mes)s,
            %(duracion_live_mes_minutos)s,
            %(dias_validos_live_mes)s,
            %(nuevos_seguidores_mes)s,
            %(emisiones_live_mes)s,
            %(porcentaje_logro_diamantes)s,
            %(porcentaje_logro_duracion_live)s,
            %(porcentaje_logro_dias_validos)s,
            %(porcentaje_logro_nuevos_seguidores)s,
            %(porcentaje_logro_emisiones)s,
            %(variacion_diamantes_mes_anterior)s,
            %(variacion_duracion_live_mes_anterior)s,
            %(variacion_dias_validos_mes_anterior)s,
            %(variacion_nuevos_seguidores_mes_anterior)s,
            %(variacion_emisiones_mes_anterior)s,
            %(partidas)s,
            %(diamantes_de_partidas)s,
            %(nuevos_creadores_live)s,
            %(diamantes_modo_varios_invitados)s,
            %(diamantes_modo_varios_invitados_anfitrion)s,
            %(diamantes_modo_varios_invitados_invitado)s,
            %(base_diamantes_antes_unirse)s,
            %(importacion_id)s,
            %(tipo_periodo)s,
            %(archivo_origen)s
        )
        ON CONFLICT (creador_tiktok_id, periodo_inicio, periodo_fin)
        DO UPDATE SET
            creador_id = EXCLUDED.creador_id,
            usuario_tiktok = EXCLUDED.usuario_tiktok,
            grupo = EXCLUDED.grupo,
            agente = EXCLUDED.agente,
            fecha_carga = NOW(),
            hora_incorporacion = EXCLUDED.hora_incorporacion,
            dias_desde_incorporacion = EXCLUDED.dias_desde_incorporacion,
            estado_graduacion = EXCLUDED.estado_graduacion,
            estado_rango = EXCLUDED.estado_rango,
            diamantes_totales = EXCLUDED.diamantes_totales,
            duracion_live_minutos = EXCLUDED.duracion_live_minutos,
            dias_validos_emisiones_live = EXCLUDED.dias_validos_emisiones_live,
            nuevos_seguidores = EXCLUDED.nuevos_seguidores,
            emisiones_live = EXCLUDED.emisiones_live,
            diamantes_mes = EXCLUDED.diamantes_mes,
            duracion_live_mes_minutos = EXCLUDED.duracion_live_mes_minutos,
            dias_validos_live_mes = EXCLUDED.dias_validos_live_mes,
            nuevos_seguidores_mes = EXCLUDED.nuevos_seguidores_mes,
            emisiones_live_mes = EXCLUDED.emisiones_live_mes,
            porcentaje_logro_diamantes = EXCLUDED.porcentaje_logro_diamantes,
            porcentaje_logro_duracion_live = EXCLUDED.porcentaje_logro_duracion_live,
            porcentaje_logro_dias_validos = EXCLUDED.porcentaje_logro_dias_validos,
            porcentaje_logro_nuevos_seguidores = EXCLUDED.porcentaje_logro_nuevos_seguidores,
            porcentaje_logro_emisiones = EXCLUDED.porcentaje_logro_emisiones,
            variacion_diamantes_mes_anterior = EXCLUDED.variacion_diamantes_mes_anterior,
            variacion_duracion_live_mes_anterior = EXCLUDED.variacion_duracion_live_mes_anterior,
            variacion_dias_validos_mes_anterior = EXCLUDED.variacion_dias_validos_mes_anterior,
            variacion_nuevos_seguidores_mes_anterior = EXCLUDED.variacion_nuevos_seguidores_mes_anterior,
            variacion_emisiones_mes_anterior = EXCLUDED.variacion_emisiones_mes_anterior,
            partidas = EXCLUDED.partidas,
            diamantes_de_partidas = EXCLUDED.diamantes_de_partidas,
            nuevos_creadores_live = EXCLUDED.nuevos_creadores_live,
            diamantes_modo_varios_invitados = EXCLUDED.diamantes_modo_varios_invitados,
            diamantes_modo_varios_invitados_anfitrion = EXCLUDED.diamantes_modo_varios_invitados_anfitrion,
            diamantes_modo_varios_invitados_invitado = EXCLUDED.diamantes_modo_varios_invitados_invitado,
            base_diamantes_antes_unirse = EXCLUDED.base_diamantes_antes_unirse,
            importacion_id = EXCLUDED.importacion_id,
            tipo_periodo = EXCLUDED.tipo_periodo,
            archivo_origen = EXCLUDED.archivo_origen
        RETURNING id_reporte
        """,
        {**data, "creador_id": creador_id},
    )
    return cur.fetchone()["id_reporte"]

def _actualizar_creador_activo(cur, creador_id: int, data: Dict[str, Any]) -> None:
    # 1. Actualizar datos base en creadores (solo lo que corresponde)
    cur.execute(
        """
        UPDATE creadores
        SET
            usuario_tiktok = COALESCE(usuario_tiktok, %s),
            updated_at = NOW()
        WHERE id = %s
        """,
        (
            data.get("usuario_tiktok"),
            creador_id,
        ),
    )

    # 2. Actualizar / acumular métricas en creadores_detalle
    cur.execute(
        """
        UPDATE creadores_detalle
        SET
            fecha_incorporacion = COALESCE(fecha_incorporacion, %s),

            diamantes = COALESCE(diamantes, 0) + COALESCE(%s, 0),
            horas_live = COALESCE(horas_live, 0) + COALESCE(%s, 0),
            numero_partidas = COALESCE(numero_partidas, 0) + COALESCE(%s, 0),
            dias_emision = COALESCE(dias_emision, 0) + COALESCE(%s, 0),

            updated_at = NOW()
        WHERE creador_id = %s
        """,
        (
            data.get("hora_incorporacion").date() if data.get("hora_incorporacion") else None,
            data.get("diamantes_totales"),
            _minutes_to_hours_int(data.get("duracion_live_minutos")),
            data.get("partidas"),
            data.get("dias_validos_emisiones_live"),
            creador_id,
        ),
    )

# def _actualizar_creador_activo(cur, creador_id: int, data: Dict[str, Any]) -> None:
#     cur.execute(
#         """
#         UPDATE creadores
#         SET
#             usuario_tiktok = COALESCE(usuario_tiktok, %s),
#             fecha_incorporacion = COALESCE(fecha_incorporacion, %s),
#             diamantes = %s,
#             horas_live = %s,
#             numero_partidas = %s,
#             dias_emision = %s
#         WHERE creador_id = %s
#         """,
#         (
#             data["usuario_tiktok"],
#             data["hora_incorporacion"].date() if data.get("hora_incorporacion") else None,
#             data.get("diamantes_totales"),
#             _minutes_to_hours_int(data.get("duracion_live_minutos")),
#             data.get("partidas"),
#             data.get("dias_validos_emisiones_live"),
#             creador_id,
#         ),
#     )


# =========================================================
# MOTOR DE METAS
# =========================================================

def _calcular_metas_para_reporte(cur, reporte: Dict[str, Any], config: GenerarMetasPeriodoIn) -> Dict[str, Optional[int]]:
    creador_id = reporte["creador_id"]

    cur.execute(
        """
        SELECT
            diamantes_mes,
            duracion_live_mes_minutos,
            dias_validos_live_mes,
            emisiones_live_mes,
            nuevos_seguidores_mes
        FROM creadores_reporte_integral
        WHERE creador_id = %s
          AND periodo_fin < %s
        ORDER BY periodo_fin DESC
        LIMIT 3
        """,
        (creador_id, reporte["periodo_inicio"]),
    )
    historico = cur.fetchall()

    if historico:
        avg_diamantes = sum([(r["diamantes_mes"] or 0) for r in historico]) / len(historico)
        avg_minutos = sum([(r["duracion_live_mes_minutos"] or 0) for r in historico]) / len(historico)
        avg_dias = sum([(r["dias_validos_live_mes"] or 0) for r in historico]) / len(historico)
        avg_emisiones = sum([(r["emisiones_live_mes"] or 0) for r in historico]) / len(historico)
        avg_seguidores = sum([(r["nuevos_seguidores_mes"] or 0) for r in historico]) / len(historico)
    else:
        avg_diamantes = reporte.get("diamantes_mes") or reporte.get("diamantes_totales") or 0
        avg_minutos = reporte.get("duracion_live_mes_minutos") or reporte.get("duracion_live_minutos") or 0
        avg_dias = reporte.get("dias_validos_live_mes") or reporte.get("dias_validos_emisiones_live") or 0
        avg_emisiones = reporte.get("emisiones_live_mes") or reporte.get("emisiones_live") or 0
        avg_seguidores = reporte.get("nuevos_seguidores_mes") or reporte.get("nuevos_seguidores") or 0

    return {
        "meta_diamantes": int(round(avg_diamantes * (1 + (config.porcentaje_crecimiento_diamantes or 0)))),
        "meta_horas_live": int(round((avg_minutos / 60) * (1 + (config.porcentaje_crecimiento_horas or 0)))),
        "meta_dias_validos": min(30, int(round(avg_dias + 2))),
        "meta_emisiones": int(round(avg_emisiones + 3)),
        "meta_nuevos_seguidores": int(round(avg_seguidores * (1 + (config.porcentaje_crecimiento_seguidores or 0)))),
    }


def _upsert_meta(cur, creador_id: int, periodo_inicio: date, periodo_fin: date, metas: Dict[str, Any], fuente: str) -> None:
    cur.execute(
        """
        INSERT INTO creadores_metas_mensuales (
            creador_id,
            periodo_inicio,
            periodo_fin,
            meta_diamantes,
            meta_horas_live,
            meta_dias_validos,
            meta_emisiones,
            meta_nuevos_seguidores,
            fuente
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (creador_id, periodo_inicio, periodo_fin)
        DO UPDATE SET
            meta_diamantes = EXCLUDED.meta_diamantes,
            meta_horas_live = EXCLUDED.meta_horas_live,
            meta_dias_validos = EXCLUDED.meta_dias_validos,
            meta_emisiones = EXCLUDED.meta_emisiones,
            meta_nuevos_seguidores = EXCLUDED.meta_nuevos_seguidores,
            fuente = EXCLUDED.fuente
        """,
        (
            creador_id,
            periodo_inicio,
            periodo_fin,
            metas.get("meta_diamantes"),
            metas.get("meta_horas_live"),
            metas.get("meta_dias_validos"),
            metas.get("meta_emisiones"),
            metas.get("meta_nuevos_seguidores"),
            fuente,
        ),
    )


# =========================================================
# MOTOR DE INSIGHTS
# =========================================================

def _evaluar_nivel_rendimiento(reporte: Dict[str, Any], meta: Optional[Dict[str, Any]]) -> str:
    if not meta:
        diamantes = reporte.get("diamantes_mes") or 0
        horas = _minutes_to_hours_int(reporte.get("duracion_live_mes_minutos")) or 0
        dias = reporte.get("dias_validos_live_mes") or 0

        if diamantes >= 200000 and horas >= 80 and dias >= 20:
            return "alto"
        if diamantes >= 80000 and horas >= 40 and dias >= 12:
            return "medio"
        return "bajo"

    cumplimientos = []

    def ratio(valor, objetivo):
        if not objetivo or objetivo <= 0:
            return None
        return (valor or 0) / objetivo

    cumplimientos.append(ratio(reporte.get("diamantes_mes"), meta.get("meta_diamantes")))
    cumplimientos.append(ratio(_minutes_to_hours_int(reporte.get("duracion_live_mes_minutos")), meta.get("meta_horas_live")))
    cumplimientos.append(ratio(reporte.get("dias_validos_live_mes"), meta.get("meta_dias_validos")))
    cumplimientos.append(ratio(reporte.get("emisiones_live_mes"), meta.get("meta_emisiones")))
    cumplimientos.append(ratio(reporte.get("nuevos_seguidores_mes"), meta.get("meta_nuevos_seguidores")))

    validos = [c for c in cumplimientos if c is not None]
    promedio = sum(validos) / len(validos) if validos else 0

    if promedio >= 1:
        return "alto"
    if promedio >= 0.70:
        return "medio"
    return "bajo"


def _generar_textos_insight(reporte: Dict[str, Any], meta: Optional[Dict[str, Any]]) -> Dict[str, str]:
    diamantes = reporte.get("diamantes_mes") or 0
    horas = _minutes_to_hours_int(reporte.get("duracion_live_mes_minutos")) or 0
    dias = reporte.get("dias_validos_live_mes") or 0
    emisiones = reporte.get("emisiones_live_mes") or 0
    seguidores = reporte.get("nuevos_seguidores_mes") or 0

    var_diamantes = reporte.get("variacion_diamantes_mes_anterior")
    var_horas = reporte.get("variacion_duracion_live_mes_anterior")
    var_dias = reporte.get("variacion_dias_validos_mes_anterior")

    nivel = _evaluar_nivel_rendimiento(reporte, meta)

    alerta = "sin_alerta"
    if dias < 10:
        alerta = "baja_constancia"
    elif horas < 30:
        alerta = "baja_duracion_live"
    elif diamantes < 50000:
        alerta = "baja_monetizacion"
    elif var_diamantes is not None and var_diamantes < -20:
        alerta = "caida_diamantes"

    insight = (
        f"Durante este periodo el creador generó {diamantes:,} diamantes, realizó {horas} horas LIVE, "
        f"tuvo {dias} días válidos, {emisiones} emisiones y obtuvo {seguidores} nuevos seguidores."
    ).replace(",", ".")

    if meta:
        meta_d = meta.get("meta_diamantes") or 0
        meta_h = meta.get("meta_horas_live") or 0
        meta_dias = meta.get("meta_dias_validos") or 0
        insight += (
            f" Frente a sus metas, la referencia era {meta_d:,} diamantes, {meta_h} horas LIVE "
            f"y {meta_dias} días válidos."
        ).replace(",", ".")

    if nivel == "alto":
        recomendacion_1 = "Mantener la frecuencia actual y reforzar los horarios donde mejor convierte en diamantes."
        recomendacion_2 = "Probar dinámicas de comunidad y retos semanales para sostener el crecimiento."
        recomendacion_3 = "Aumentar gradualmente la meta del siguiente mes sin sacrificar constancia."
    elif nivel == "medio":
        recomendacion_1 = "Priorizar constancia: distribuir mejor las emisiones durante la semana."
        recomendacion_2 = "Revisar qué lives generaron más diamantes para repetir formatos ganadores."
        recomendacion_3 = "Trabajar una meta semanal de horas, días válidos y seguidores nuevos."
    else:
        recomendacion_1 = "Definir un horario fijo de emisión para crear hábito y estabilidad."
        recomendacion_2 = "Enfocarse primero en días válidos antes de exigir una meta alta de diamantes."
        recomendacion_3 = "Hacer seguimiento semanal con el manager para ajustar contenido y duración de lives."

    if var_horas is not None and var_horas < -20:
        recomendacion_2 = "La duración de LIVE cayó frente al mes pasado; conviene recuperar horas antes de subir la meta de diamantes."
    if var_dias is not None and var_dias < -20:
        recomendacion_1 = "La constancia bajó frente al mes anterior; la prioridad debe ser recuperar días válidos de emisión."

    return {
        "nivel_rendimiento": nivel,
        "alerta_principal": alerta,
        "insight_general": insight[:600],
        "recomendacion_1": recomendacion_1[:600],
        "recomendacion_2": recomendacion_2[:600],
        "recomendacion_3": recomendacion_3[:600],
    }


def _upsert_insight(cur, reporte: Dict[str, Any], textos: Dict[str, str]) -> None:
    # No hay unique constraint en la tabla de insights.
    # Para evitar duplicados, borramos el insight previo del mismo reporte y lo insertamos de nuevo.
    cur.execute(
        "DELETE FROM creadores_insights_mensuales WHERE id_reporte = %s",
        (reporte["id_reporte"],),
    )
    cur.execute(
        """
        INSERT INTO creadores_insights_mensuales (
            creador_id,
            id_reporte,
            periodo_inicio,
            periodo_fin,
            nivel_rendimiento,
            alerta_principal,
            insight_general,
            recomendacion_1,
            recomendacion_2,
            recomendacion_3
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            reporte["creador_id"],
            reporte["id_reporte"],
            reporte["periodo_inicio"],
            reporte["periodo_fin"],
            textos["nivel_rendimiento"],
            textos["alerta_principal"],
            textos["insight_general"],
            textos["recomendacion_1"],
            textos["recomendacion_2"],
            textos["recomendacion_3"],
        ),
    )


# =========================================================
# ENDPOINT: VALIDAR EXCEL SIN IMPORTAR
# =========================================================

@router.post("/api/creadores/performance/validar-reporte")
def validar_reporte_creadores_excel(file: UploadFile = File(...)):
    try:

        content = file.file.read()

        df = pd.read_excel(io.BytesIO(content))

        _validar_columnas_excel(df)

        periodos = []

        for value in df["Periodo de datos"].dropna().unique().tolist():

            try:
                inicio, fin = _parse_periodo(value)

                periodos.append({
                    "periodo_inicio": inicio,
                    "periodo_fin": fin
                })

            except Exception:
                pass

        # Validar solapamientos en DB
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                for periodo in periodos:

                    cur.execute("""
                        SELECT
                            periodo_inicio,
                            periodo_fin
                        FROM creadores_reporte_integral
                        WHERE
                            %s <= periodo_fin
                            AND
                            %s >= periodo_inicio
                        LIMIT 1
                    """, (
                        periodo["periodo_inicio"],
                        periodo["periodo_fin"]
                    ))

                    conflicto = cur.fetchone()

                    if conflicto:

                        raise HTTPException(
                            status_code=400,
                            detail=(
                                f"Ya existe un reporte cargado que se "
                                f"solapa con el periodo "
                                f"{periodo['periodo_inicio']} "
                                f"a {periodo['periodo_fin']}."
                            )
                        )

        return {
            "ok": True,
            "filename": file.filename,
            "filas": len(df),
            "columnas": list(df.columns),
            "periodos_detectados": periodos,
            "mensaje": "El archivo tiene la estructura esperada y no presenta solapamientos."
        }

    except HTTPException:
        raise

    except Exception as e:
        print("❌ Error validando reporte:", e)

        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail="Error validando el reporte de creadores"
        )


# =========================================================
# ENDPOINT: CARGAR EXCEL + INSERTAR REPORTE
# =========================================================

@router.post("/api/creadores/performance/upload-reporte")
def cargar_reporte_creadores_excel(
    file: UploadFile = File(...),
    actualizar_creadores_activos: bool = Query(True),
    generar_metas: bool = Query(True),
    generar_insights: bool = Query(True),
):
    try:
        content = file.file.read()
        df = pd.read_excel(io.BytesIO(content))
        _validar_columnas_excel(df)

        insertados_o_actualizados = 0
        con_creador_en_saas = 0
        no_encontrados = []
        errores = []
        reportes_procesados = []
        archivo_origen = "backstage_excel"
        importaciones_por_periodo: Dict[Tuple[date, date], int] = {}

        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                importaciones_por_periodo = _registrar_importaciones_desde_df(
                    cur,
                    df,
                    archivo_nombre=file.filename,
                    archivo_origen=archivo_origen,
                )

                for idx, row in df.iterrows():
                    try:
                        data = _row_to_reporte(row)

                        if not data["creador_tiktok_id"]:
                            errores.append({"fila": int(idx) + 2, "error": "ID del creador vacío"})
                            continue

                        periodo_key = (data["periodo_inicio"], data["periodo_fin"])
                        data["tipo_periodo"] = _inferir_tipo_periodo(
                            data["periodo_inicio"],
                            data["periodo_fin"],
                        )
                        data["archivo_origen"] = archivo_origen
                        data["importacion_id"] = importaciones_por_periodo.get(periodo_key)

                        creador_id = _buscar_creador_por_tiktok(
                            cur,
                            data["creador_tiktok_id"],
                            data["usuario_tiktok"],
                        )

                        if creador_id:
                            con_creador_en_saas += 1
                            _actualizar_creador_base(cur, creador_id, data)
                        else:
                            no_encontrados.append({
                                "fila": int(idx) + 2,
                                "creador_tiktok_id": data["creador_tiktok_id"],
                                "usuario_tiktok": data["usuario_tiktok"],
                            })

                        id_reporte = _upsert_reporte_integral(cur, data, creador_id)
                        insertados_o_actualizados += 1

                        if creador_id and actualizar_creadores_activos:
                            _actualizar_creador_activo(cur, creador_id, data)

                        reportes_procesados.append({
                            "id_reporte": id_reporte,
                            "creador_id": creador_id,
                            "periodo_inicio": data["periodo_inicio"],
                            "periodo_fin": data["periodo_fin"],
                        })

                    except Exception as row_error:
                        errores.append({
                            "fila": int(idx) + 2,
                            "error": str(row_error),
                        })

                if generar_metas:
                    config = GenerarMetasPeriodoIn(
                        periodo_inicio=reportes_procesados[0]["periodo_inicio"] if reportes_procesados else date.today(),
                        periodo_fin=reportes_procesados[0]["periodo_fin"] if reportes_procesados else date.today(),
                    )
                    for r in reportes_procesados:
                        if not r["creador_id"]:
                            continue
                        cur.execute(
                            "SELECT * FROM creadores_reporte_integral WHERE id_reporte = %s",
                            (r["id_reporte"],),
                        )
                        reporte = cur.fetchone()
                        metas = _calcular_metas_para_reporte(cur, reporte, config)
                        _upsert_meta(
                            cur,
                            r["creador_id"],
                            r["periodo_inicio"],
                            r["periodo_fin"],
                            metas,
                            config.fuente or "sistema",
                        )

                if generar_insights:
                    for r in reportes_procesados:
                        if not r["creador_id"]:
                            continue
                        cur.execute(
                            "SELECT * FROM creadores_reporte_integral WHERE id_reporte = %s",
                            (r["id_reporte"],),
                        )
                        reporte = cur.fetchone()

                        cur.execute(
                            """
                            SELECT *
                            FROM creadores_metas_mensuales
                            WHERE creador_id = %s
                              AND periodo_inicio = %s
                              AND periodo_fin = %s
                            LIMIT 1
                            """,
                            (r["creador_id"], r["periodo_inicio"], r["periodo_fin"]),
                        )
                        meta = cur.fetchone()
                        textos = _generar_textos_insight(reporte, meta)
                        _upsert_insight(cur, reporte, textos)

        importaciones_respuesta = [
            {
                "id_importacion": id_importacion,
                "periodo_inicio": periodo_inicio,
                "periodo_fin": periodo_fin,
                "tipo_periodo": _inferir_tipo_periodo(periodo_inicio, periodo_fin),
            }
            for (periodo_inicio, periodo_fin), id_importacion in importaciones_por_periodo.items()
        ]

        return {
            "ok": True,
            "filename": file.filename,
            "filas_excel": len(df),
            "importaciones": importaciones_respuesta,
            "reportes_insertados_o_actualizados": insertados_o_actualizados,
            "creadores_encontrados_en_saas": con_creador_en_saas,
            "creadores_no_encontrados": no_encontrados,
            "errores": errores,
            "actualizo_creadores_activos": actualizar_creadores_activos,
            "genero_metas": generar_metas,
            "genero_insights": generar_insights,
        }

    except HTTPException:
        raise
    except Exception as e:
        print("❌ Error cargando reporte de creadores:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error cargando el reporte de creadores")


# =========================================================
# ENDPOINT: GENERAR METAS POR PERIODO
# =========================================================

@router.post("/api/creadores/performance/generar-metas")
def generar_metas_periodo(payload: GenerarMetasPeriodoIn):
    try:
        creados_o_actualizados = 0

        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM creadores_reporte_integral
                    WHERE periodo_inicio = %s
                      AND periodo_fin = %s
                      AND creador_id IS NOT NULL
                    """,
                    (payload.periodo_inicio, payload.periodo_fin),
                )
                reportes = cur.fetchall()

                for reporte in reportes:
                    metas = _calcular_metas_para_reporte(cur, reporte, payload)
                    _upsert_meta(
                        cur,
                        reporte["creador_id"],
                        payload.periodo_inicio,
                        payload.periodo_fin,
                        metas,
                        payload.fuente or "sistema",
                    )
                    creados_o_actualizados += 1

            conn.commit()

        return {
            "ok": True,
            "periodo_inicio": payload.periodo_inicio,
            "periodo_fin": payload.periodo_fin,
            "metas_creadas_o_actualizadas": creados_o_actualizados,
        }

    except Exception as e:
        print("❌ Error generando metas:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error generando metas mensuales")


# =========================================================
# ENDPOINT: GUARDAR META MANUAL
# =========================================================

@router.post("/api/creadores/performance/metas/manual")
def guardar_meta_manual(payload: MetaMensualManualIn):
    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                _upsert_meta(
                    cur,
                    payload.creador_id,
                    payload.periodo_inicio,
                    payload.periodo_fin,
                    payload.dict(),
                    payload.fuente or "manual",
                )
            conn.commit()

        return {
            "ok": True,
            "mensaje": "Meta mensual guardada correctamente.",
            "creador_id": payload.creador_id,
            "periodo_inicio": payload.periodo_inicio,
            "periodo_fin": payload.periodo_fin,
        }

    except Exception as e:
        print("❌ Error guardando meta manual:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error guardando meta mensual")


# =========================================================
# ENDPOINT: GENERAR INSIGHTS POR PERIODO
# =========================================================

@router.post("/api/creadores/performance/generar-insights")
def generar_insights_periodo(payload: GenerarInsightsPeriodoIn):
    try:
        generados = 0

        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM creadores_reporte_integral
                    WHERE periodo_inicio = %s
                      AND periodo_fin = %s
                      AND creador_id IS NOT NULL
                    """,
                    (payload.periodo_inicio, payload.periodo_fin),
                )
                reportes = cur.fetchall()

                for reporte in reportes:
                    cur.execute(
                        """
                        SELECT *
                        FROM creadores_metas_mensuales
                        WHERE creador_id = %s
                          AND periodo_inicio = %s
                          AND periodo_fin = %s
                        LIMIT 1
                        """,
                        (reporte["creador_id"], payload.periodo_inicio, payload.periodo_fin),
                    )
                    meta = cur.fetchone()
                    textos = _generar_textos_insight(reporte, meta)
                    _upsert_insight(cur, reporte, textos)
                    generados += 1

            conn.commit()

        return {
            "ok": True,
            "periodo_inicio": payload.periodo_inicio,
            "periodo_fin": payload.periodo_fin,
            "insights_generados": generados,
        }

    except Exception as e:
        print("❌ Error generando insights:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error generando insights mensuales")


def _insight_tiene_contenido(insight: Optional[Dict[str, Any]]) -> bool:
    if not insight:
        return False
    for key in (
        "insight_general",
        "recomendacion_1",
        "recomendacion_2",
        "recomendacion_3",
        "nivel_rendimiento",
    ):
        val = insight.get(key)
        if val is not None and str(val).strip():
            return True
    return False


def _cargar_o_generar_insight(cur, conn, reporte: Dict[str, Any], meta: Optional[Dict[str, Any]], creador_id: int):
    """
    Devuelve insight de creadores_insights_mensuales.
    Si no existe (p. ej. reporte importado sin generar_insights), lo calcula y persiste.
    """
    cur.execute(
        """
        SELECT *
        FROM creadores_insights_mensuales
        WHERE creador_id = %s
          AND id_reporte = %s
        LIMIT 1
        """,
        (creador_id, reporte["id_reporte"]),
    )
    insight = cur.fetchone()

    if not _insight_tiene_contenido(insight):
        cur.execute(
            """
            SELECT *
            FROM creadores_insights_mensuales
            WHERE creador_id = %s
              AND periodo_inicio = %s
              AND periodo_fin = %s
            ORDER BY created_at DESC NULLS LAST
            LIMIT 1
            """,
            (creador_id, reporte["periodo_inicio"], reporte["periodo_fin"]),
        )
        insight = cur.fetchone()

    if not _insight_tiene_contenido(insight) and reporte.get("creador_id"):
        textos = _generar_textos_insight(reporte, meta)
        _upsert_insight(cur, reporte, textos)
        conn.commit()
        cur.execute(
            """
            SELECT *
            FROM creadores_insights_mensuales
            WHERE creador_id = %s
              AND id_reporte = %s
            LIMIT 1
            """,
            (creador_id, reporte["id_reporte"]),
        )
        insight = cur.fetchone()

    return insight


# =========================================================
# ENDPOINT: RESUMEN PERFORMANCE DE UN CREADOR
# =========================================================

@router.get("/api/creadores/{creador_id}/performance/resumen")
def obtener_resumen_performance_creador(
    creador_id: int,
    periodo_inicio: Optional[date] = Query(None),
    periodo_fin: Optional[date] = Query(None),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if periodo_inicio and periodo_fin:
                    cur.execute(
                        """
                        SELECT *
                        FROM creadores_reporte_integral
                        WHERE creador_id = %s
                          AND periodo_inicio = %s
                          AND periodo_fin = %s
                        LIMIT 1
                        """,
                        (creador_id, periodo_inicio, periodo_fin),
                    )
                else:
                    cur.execute(
                        """
                        SELECT *
                        FROM creadores_reporte_integral
                        WHERE creador_id = %s
                        ORDER BY periodo_fin DESC
                        LIMIT 1
                        """,
                        (creador_id,),
                    )

                reporte = cur.fetchone()

                if not reporte:
                    raise HTTPException(status_code=404, detail="No hay reporte para este creador")

                cur.execute(
                    """
                    SELECT *
                    FROM creadores_metas_mensuales
                    WHERE creador_id = %s
                      AND periodo_inicio = %s
                      AND periodo_fin = %s
                    LIMIT 1
                    """,
                    (creador_id, reporte["periodo_inicio"], reporte["periodo_fin"]),
                )
                meta = cur.fetchone()

                insight = _cargar_o_generar_insight(cur, conn, reporte, meta, creador_id)

        return {
            "ok": True,
            "creador_id": creador_id,
            "periodo_inicio": reporte["periodo_inicio"],
            "periodo_fin": reporte["periodo_fin"],
            "reporte": reporte,
            "meta": meta,
            "insight": insight,
        }

    except HTTPException:
        raise
    except Exception as e:
        print("❌ Error obteniendo resumen performance:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error obteniendo resumen de performance")


# =========================================================
# ENDPOINT: HISTÓRICO DE UN CREADOR
# =========================================================

@router.get("/api/creadores/{creador_id}/performance/historico")
def obtener_historico_performance_creador(
    creador_id: int,
    limit: int = Query(12, ge=1, le=36),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        r.id_reporte,
                        r.periodo_inicio,
                        r.periodo_fin,
                        r.diamantes_mes,
                        r.duracion_live_mes_minutos,
                        ROUND((r.duracion_live_mes_minutos::numeric / 60), 2) AS horas_live_mes,
                        r.dias_validos_live_mes,
                        r.nuevos_seguidores_mes,
                        r.emisiones_live_mes,
                        r.variacion_diamantes_mes_anterior,
                        r.variacion_duracion_live_mes_anterior,
                        r.variacion_dias_validos_mes_anterior,
                        i.nivel_rendimiento,
                        i.alerta_principal
                    FROM creadores_reporte_integral r
                    LEFT JOIN creadores_insights_mensuales i
                        ON i.id_reporte = r.id_reporte
                    WHERE r.creador_id = %s
                    ORDER BY r.periodo_fin DESC
                    LIMIT %s
                    """,
                    (creador_id, limit),
                )
                rows = cur.fetchall()

        return {
            "ok": True,
            "creador_id": creador_id,
            "total": len(rows),
            "historico": rows,
        }

    except Exception as e:
        print("❌ Error obteniendo histórico performance:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error obteniendo histórico de performance")


# =========================================================
# ENDPOINT: DASHBOARD INTERNO AGENCIA
# =========================================================

@router.get("/api/creadores/performance/dashboard")
def obtener_dashboard_performance_agencia(
    periodo_inicio: date = Query(...),
    periodo_fin: date = Query(...),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS total_reportes,
                        COUNT(*) FILTER (WHERE creador_id IS NOT NULL) AS creadores_vinculados,
                        COUNT(*) FILTER (WHERE creador_id IS NULL) AS creadores_no_vinculados,
                        COALESCE(SUM(diamantes_mes), 0) AS total_diamantes_mes,
                        COALESCE(SUM(duracion_live_mes_minutos), 0) AS total_minutos_live_mes,
                        COALESCE(SUM(dias_validos_live_mes), 0) AS total_dias_validos_mes,
                        COALESCE(SUM(nuevos_seguidores_mes), 0) AS total_nuevos_seguidores_mes,
                        COALESCE(SUM(emisiones_live_mes), 0) AS total_emisiones_mes
                    FROM creadores_reporte_integral
                    WHERE periodo_inicio = %s
                      AND periodo_fin = %s
                    """,
                    (periodo_inicio, periodo_fin),
                )
                resumen = cur.fetchone()

                cur.execute(
                    """
                    SELECT
                        r.creador_id,
                        c.nombre,
                        r.usuario_tiktok,
                        r.diamantes_mes,
                        ROUND((r.duracion_live_mes_minutos::numeric / 60), 2) AS horas_live_mes,
                        r.dias_validos_live_mes,
                        r.nuevos_seguidores_mes,
                        i.nivel_rendimiento,
                        i.alerta_principal
                    FROM creadores_reporte_integral r
                    LEFT JOIN creadores c ON c.id = r.creador_id
                    LEFT JOIN creadores_insights_mensuales i ON i.id_reporte = r.id_reporte
                    WHERE r.periodo_inicio = %s
                      AND r.periodo_fin = %s
                    ORDER BY r.diamantes_mes DESC NULLS LAST
                    LIMIT 10
                    """,
                    (periodo_inicio, periodo_fin),
                )
                top_diamantes = cur.fetchall()

                cur.execute(
                    """
                    SELECT
                        r.creador_id,
                        c.nombre,
                        r.usuario_tiktok,
                        r.diamantes_mes,
                        ROUND((r.duracion_live_mes_minutos::numeric / 60), 2) AS horas_live_mes,
                        r.dias_validos_live_mes,
                        i.nivel_rendimiento,
                        i.alerta_principal
                    FROM creadores_reporte_integral r
                    LEFT JOIN creadores c ON c.id = r.creador_id
                    LEFT JOIN creadores_insights_mensuales i ON i.id_reporte = r.id_reporte
                    WHERE r.periodo_inicio = %s
                      AND r.periodo_fin = %s
                      AND (
                            i.alerta_principal IN ('baja_constancia', 'baja_duracion_live', 'baja_monetizacion', 'caida_diamantes')
                            OR i.nivel_rendimiento = 'bajo'
                          )
                    ORDER BY r.diamantes_mes ASC NULLS LAST
                    LIMIT 20
                    """,
                    (periodo_inicio, periodo_fin),
                )
                alertas = cur.fetchall()

        return {
            "ok": True,
            "periodo_inicio": periodo_inicio,
            "periodo_fin": periodo_fin,
            "resumen": resumen,
            "top_diamantes": top_diamantes,
            "alertas": alertas,
        }

    except Exception as e:
        print("❌ Error dashboard performance:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error obteniendo dashboard de performance")


# =========================================================
# ENDPOINT: CREADORES DEL REPORTE NO VINCULADOS AL SAAS
# =========================================================

@router.get("/api/creadores/performance/no-vinculados")
def obtener_creadores_reporte_no_vinculados(
    periodo_inicio: date = Query(...),
    periodo_fin: date = Query(...),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        id_reporte,
                        creador_tiktok_id,
                        usuario_tiktok,
                        grupo,
                        agente,
                        periodo_inicio,
                        periodo_fin,
                        diamantes_mes,
                        duracion_live_mes_minutos,
                        dias_validos_live_mes
                    FROM creadores_reporte_integral
                    WHERE periodo_inicio = %s
                      AND periodo_fin = %s
                      AND creador_id IS NULL
                    ORDER BY usuario_tiktok ASC
                    """,
                    (periodo_inicio, periodo_fin),
                )
                rows = cur.fetchall()

        return {
            "ok": True,
            "periodo_inicio": periodo_inicio,
            "periodo_fin": periodo_fin,
            "total": len(rows),
            "creadores_no_vinculados": rows,
        }

    except Exception as e:
        print("❌ Error obteniendo no vinculados:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error obteniendo creadores no vinculados")
