"""
main_creadores_performance.py

Módulo de Performance de Creadores para Talentum Manager.

Objetivo:
- Alimentar la pantalla interna del manager.
- Integrar métricas automáticas, metas, insights, score, alertas, recomendaciones IA,
  acciones de seguimiento y observaciones humanas.
- Mantener compatibilidad con endpoints legacy de seguimiento.

IMPORTANTE:
- Todas las tablas se consultan sin schema test.
- Este módulo asume PostgreSQL y el helper get_connection_context() de DataBase.py.
- Para usar OpenAI requiere:
    OPENAI_API_KEY en variables de entorno
    configuracion_agencia.open_AI_enabled activo mediante main_configuracion.get_config()

Tablas principales usadas:
- creadores
- creadores_detalle
- creadores_reporte_integral
- creadores_metas_mensuales
- creadores_insights_mensuales
- creadores_performance_seguimiento
- creadores_performance_acciones
- creadores_performance_alertas
- creadores_performance_recomendaciones
- creadores_performance_score
- creadores_performance_resumen
- creadores_perfil_respuesta
- creadores_perfil_variable
- creadores_perfil_categoria
"""

import json
import os
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query
from openai import OpenAI
from pydantic import AliasChoices, BaseModel, Field

from DataBase import get_connection_context

load_dotenv()

router = APIRouter()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL_DEFAULT = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_CONFIG_CLAVE = "open_AI_enabled"

_openai_client: Optional[OpenAI] = None
DEBUG_PERFORMANCE_IA = str(os.getenv("DEBUG_PERFORMANCE_IA", "false")).lower() in {"1", "true", "yes", "on"}


# =========================================================
# CONSTANTES DE NEGOCIO
# =========================================================

ESTADOS_ACCION_VALIDOS = {
    "pendiente",
    "en_proceso",
    "cumplido",
    "incumplido",
    "cancelado",
}

PRIORIDADES_VALIDAS = {
    "baja",
    "media",
    "alta",
    "critica",
}

ESTADOS_ALERTA_VALIDOS = {
    "activa",
    "pendiente",
    "resuelta",
    "descartada",
}

NIVELES_ALERTA_VALIDOS = {
    "baja",
    "media",
    "alta",
    "critica",
}

TIPOS_ACCION_SUGERIDOS = {
    "CAMBIO_HORARIO",
    "AUMENTAR_FRECUENCIA",
    "MEJORAR_INTERACCION",
    "CAPACITACION",
    "MENTORIA",
    "REVISION_CONTENIDO",
    "OPTIMIZAR_PERFIL",
    "META_SEMANAL",
    "SEGUIMIENTO_DISCIPLINA",
    "SEGUIMIENTO_EMOCIONAL",
    "MEJORAR_MONETIZACION",
    "PRUEBA_NUEVO_FORMATO",
}

NIVELES_RENDIMIENTO = {
    "excelente",
    "alto",
    "medio",
    "bajo",
    "critico",
}


# =========================================================
# SCHEMAS
# =========================================================

class SeguimientoPerformanceCreate(BaseModel):
    creador_id: int = Field(
        ...,
        validation_alias=AliasChoices("creador_id", "creador_activo_id"),
    )
    fecha_seguimiento: Optional[date] = None
    observaciones_manager: Optional[str] = ""
    resumen_compromisos: Optional[str] = ""


class SeguimientoPerformanceUpdate(BaseModel):
    fecha_seguimiento: Optional[date] = None
    observaciones_manager: Optional[str] = None
    resumen_compromisos: Optional[str] = None


class SeguimientoConAccionesCreate(BaseModel):
    creador_id: int
    fecha_seguimiento: Optional[date] = None
    observaciones_manager: Optional[str] = ""
    resumen_compromisos: Optional[str] = ""
    acciones: List["AccionPerformanceCreateSinSeguimiento"] = []


class AccionPerformanceCreateSinSeguimiento(BaseModel):
    tipo_accion: str
    titulo: Optional[str] = None
    descripcion: Optional[str] = None
    prioridad: Optional[str] = "media"
    estado: Optional[str] = "pendiente"
    fecha_compromiso: Optional[date] = None
    creado_por: Optional[int] = None


class AccionPerformanceCreate(BaseModel):
    seguimiento_id: int
    tipo_accion: str
    titulo: Optional[str] = None
    descripcion: Optional[str] = None
    prioridad: Optional[str] = "media"
    estado: Optional[str] = "pendiente"
    fecha_compromiso: Optional[date] = None
    creado_por: Optional[int] = None


class AccionPerformanceUpdate(BaseModel):
    tipo_accion: Optional[str] = None
    titulo: Optional[str] = None
    descripcion: Optional[str] = None
    prioridad: Optional[str] = None
    estado: Optional[str] = None
    fecha_compromiso: Optional[date] = None
    fecha_cumplimiento: Optional[date] = None


class AccionEstadoUpdate(BaseModel):
    estado: str
    fecha_cumplimiento: Optional[date] = None


class AlertaPerformanceCreate(BaseModel):
    creador_id: int
    id_reporte: Optional[int] = None
    tipo_alerta: Optional[str] = None
    nivel_alerta: Optional[str] = "media"
    titulo: Optional[str] = None
    descripcion: Optional[str] = None
    origen: Optional[str] = "manual"
    estado: Optional[str] = "activa"


class AlertaPerformanceUpdate(BaseModel):
    tipo_alerta: Optional[str] = None
    nivel_alerta: Optional[str] = None
    titulo: Optional[str] = None
    descripcion: Optional[str] = None
    origen: Optional[str] = None
    estado: Optional[str] = None
    resolved_at: Optional[datetime] = None


class ResolverAlertaRequest(BaseModel):
    estado: Optional[str] = "resuelta"


class RecomendacionPerformanceCreate(BaseModel):
    creador_id: int
    id_reporte: Optional[int] = None
    categoria: Optional[str] = None
    prioridad: Optional[str] = "media"
    recomendacion: str
    justificacion: Optional[str] = None
    aplicada: Optional[bool] = False


class RecomendacionPerformanceUpdate(BaseModel):
    categoria: Optional[str] = None
    prioridad: Optional[str] = None
    recomendacion: Optional[str] = None
    justificacion: Optional[str] = None
    aplicada: Optional[bool] = None
    aplicada_at: Optional[datetime] = None


class AplicarRecomendacionRequest(BaseModel):
    aplicada: bool = True


class ScorePerformanceCreate(BaseModel):
    creador_id: int
    id_reporte: Optional[int] = None
    score_general: Optional[float] = None
    nivel_rendimiento: Optional[str] = None
    riesgo_abandono: Optional[str] = None
    probabilidad_crecimiento: Optional[float] = None
    consistencia_score: Optional[float] = None
    monetizacion_score: Optional[float] = None
    engagement_score: Optional[float] = None
    observacion_ia: Optional[str] = None


class ResumenPerformanceCreate(BaseModel):
    creador_id: int
    periodo_inicio: date
    periodo_fin: date
    diamantes: Optional[int] = None
    horas_live: Optional[float] = None
    dias_validos: Optional[int] = None
    emisiones: Optional[int] = None
    nuevos_seguidores: Optional[int] = None
    cumplimiento_general: Optional[float] = None
    tendencia: Optional[str] = None
    nivel_rendimiento: Optional[str] = None


class IARequest(BaseModel):
    guardar: bool = False
    instrucciones_extra: Optional[str] = None
    id_reporte: Optional[int] = None


class GenerarSeguimientoIARequest(BaseModel):
    observaciones_manager: Optional[str] = ""
    resumen_compromisos: Optional[str] = ""
    instrucciones_extra: Optional[str] = None


class GenerarAccionesIARequest(BaseModel):
    seguimiento_id: Optional[int] = None
    guardar: bool = False
    max_acciones: int = Field(default=5, ge=1, le=10)
    instrucciones_extra: Optional[str] = None


class GenerarRecomendacionesIARequest(BaseModel):
    guardar: bool = False
    max_recomendaciones: int = Field(default=5, ge=1, le=10)
    instrucciones_extra: Optional[str] = None


class GenerarAlertasScoreIARequest(BaseModel):
    guardar: bool = False
    instrucciones_extra: Optional[str] = None


class DashboardPerformanceResponse(BaseModel):
    ok: bool
    creador: Optional[Dict[str, Any]] = None
    detalle: Optional[Dict[str, Any]] = None
    categoria_creador: Optional[Dict[str, Any]] = None
    ultimo_reporte: Optional[Dict[str, Any]] = None
    metas: Optional[Dict[str, Any]] = None
    insights: Optional[Dict[str, Any]] = None
    score: Optional[Dict[str, Any]] = None
    alertas: List[Dict[str, Any]] = []
    recomendaciones: List[Dict[str, Any]] = []
    seguimientos: List[Dict[str, Any]] = []
    acciones_abiertas: List[Dict[str, Any]] = []
    perfil_respuestas: List[Dict[str, Any]] = []
    perfil_estrategico: Optional[Dict[str, Any]] = None
    performance_partidas: Optional[Dict[str, Any]] = None


# Para compatibilidad con Pydantic forward refs
try:
    SeguimientoConAccionesCreate.update_forward_refs()
except Exception:
    pass


# =========================================================
# HELPERS GENERALES
# =========================================================

def model_to_dict(model: BaseModel, *, exclude_unset: bool = False) -> Dict[str, Any]:
    """
    Compatible con Pydantic v1 y v2.
    """
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=exclude_unset)
    return model.dict(exclude_unset=exclude_unset)


def normalizar_texto(valor: Optional[str]) -> Optional[str]:
    if valor is None:
        return None
    return str(valor).strip()


def normalizar_texto_parrafos(valor: Optional[str]) -> str:
    """
    Unifica saltos de línea para que el front (p. ej. white-space: pre-line)
    pueda mostrar párrafos separados. No altera el contenido salvo espacios
    al final de línea y líneas en blanco excesivas.
    """
    if valor is None:
        return ""
    texto = str(valor).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not texto:
        return ""
    lineas = [ln.rstrip() for ln in texto.split("\n")]
    texto = "\n".join(lineas)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto


def _formatear_seguimiento_respuesta(
    row: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not row:
        return row
    for campo in ("observaciones_manager", "resumen_compromisos"):
        if campo in row and row[campo]:
            row[campo] = normalizar_texto_parrafos(row[campo])
    return row


def _formatear_lista_seguimientos(
    filas: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return [_formatear_seguimiento_respuesta(dict(f)) for f in filas]


def normalizar_lower(valor: Optional[str]) -> Optional[str]:
    if valor is None:
        return None
    return str(valor).strip().lower()


def decimal_to_float(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: decimal_to_float(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decimal_to_float(v) for v in value]
    return value


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except Exception:
        return default


def clamp(value: float, min_value: float = 0.0, max_value: float = 100.0) -> float:
    return max(min_value, min(max_value, value))


def limpiar_json_openai(texto: str) -> str:
    texto = (texto or "").strip()
    texto = re.sub(r"^```json\s*", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"^```\s*", "", texto)
    texto = re.sub(r"\s*```$", "", texto)
    return texto.strip()


def parse_json_openai(texto: str) -> Any:
    limpio = limpiar_json_openai(texto)
    try:
        return json.loads(limpio)
    except Exception:
        return {
            "raw": texto,
            "error_parse_json": True,
        }


def serializable(obj: Any) -> Any:
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [serializable(v) for v in obj]
    return obj


def contexto_para_prompt(contexto: Dict[str, Any]) -> str:
    return json.dumps(serializable(contexto), ensure_ascii=False, indent=2)


def validar_valor_en_set(
    valor: Optional[str],
    validos: set,
    campo: str,
    *,
    requerido: bool = False,
) -> Optional[str]:
    valor_norm = normalizar_lower(valor)

    if not valor_norm:
        if requerido:
            raise HTTPException(status_code=400, detail=f"{campo} es requerido")
        return valor_norm

    if valor_norm not in validos:
        raise HTTPException(
            status_code=400,
            detail=f"{campo} inválido. Valores permitidos: {sorted(validos)}",
        )

    return valor_norm


# =========================================================
# DB HELPERS
# =========================================================

def row_to_dict(cur, row):
    if row is None:
        return None
    columns = [desc[0] for desc in cur.description]
    result = dict(zip(columns, row))
    return decimal_to_float(result)


def rows_to_dicts(cur, rows):
    columns = [desc[0] for desc in cur.description]
    data = [dict(zip(columns, row)) for row in rows]
    return decimal_to_float(data)


def fetch_one(query: str, params: tuple = ()):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            return row_to_dict(cur, row)


def fetch_all(query: str, params: tuple = ()):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            return rows_to_dicts(cur, rows)


def execute_returning(query: str, params: Any):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            result = row_to_dict(cur, row)
            conn.commit()
            return result


def execute_returning_many(query: str, params_list: List[Any]):
    results = []
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            for params in params_list:
                cur.execute(query, params)
                row = cur.fetchone()
                results.append(row_to_dict(cur, row))
            conn.commit()
    return results


def execute_no_return(query: str, params: tuple = ()):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            conn.commit()


def update_row_dynamic(
    *,
    table_name: str,
    id_column: str,
    id_value: int,
    data: Dict[str, Any],
    allowed_fields: set,
):
    """
    Update seguro con campos controlados por allowed_fields.
    No permite nombres de tabla/campos enviados por el usuario.
    """
    fields = {
        k: v
        for k, v in data.items()
        if k in allowed_fields
    }

    if not fields:
        raise HTTPException(status_code=400, detail="No hay campos válidos para actualizar")

    set_parts = []
    params: Dict[str, Any] = {"id_value": id_value}

    for key, value in fields.items():
        set_parts.append(f"{key} = %({key})s")
        params[key] = value

    query = f"""
        UPDATE {table_name}
        SET {", ".join(set_parts)}
        WHERE {id_column} = %(id_value)s
        RETURNING *;
    """
    return execute_returning(query, params)


# =========================================================
# OPENAI HELPERS
# =========================================================

def openai_api_key_configurada() -> bool:
    return bool(OPENAI_API_KEY and str(OPENAI_API_KEY).strip())


def openai_habilitado_en_agencia() -> bool:
    """
    Lee configuracion_agencia.open_AI_enabled usando el mismo patrón
    de otros módulos del proyecto.
    """
    try:
        from main_configuracion import get_config

        valor = get_config(OPENAI_CONFIG_CLAVE)
        if isinstance(valor, bool):
            return valor

        from utils_whatsapp_flujos import _valor_activo

        return _valor_activo(valor)

    except Exception as e:
        print(f"⚠️ Error leyendo configuración '{OPENAI_CONFIG_CLAVE}': {e}")
        return False


def openai_disponible() -> bool:
    return openai_api_key_configurada() and openai_habilitado_en_agencia()


def validar_openai_habilitado() -> None:
    if not openai_habilitado_en_agencia():
        raise HTTPException(
            status_code=403,
            detail=(
                "OpenAI está deshabilitado para esta agencia. "
                f"Actívalo en configuración ({OPENAI_CONFIG_CLAVE})."
            ),
        )

    if not openai_api_key_configurada():
        raise HTTPException(
            status_code=503,
            detail="OpenAI no configurado: define OPENAI_API_KEY en el entorno.",
        )


def get_openai_client() -> OpenAI:
    global _openai_client
    validar_openai_habilitado()

    if _openai_client is None:
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)

    return _openai_client


def openai_chat_completion(
    prompt: str,
    *,
    model: Optional[str] = None,
    temperature: float = 0.4,
    system: Optional[str] = None,
) -> str:
    messages: List[dict] = []

    if system:
        messages.append({"role": "system", "content": system})

    messages.append({"role": "user", "content": prompt})

    try:
        client = get_openai_client()
        response = client.with_options(timeout=60).chat.completions.create(
            model=model or OPENAI_MODEL_DEFAULT,
            messages=messages,
            temperature=temperature,
        )
        content = response.choices[0].message.content
        return (content or "").strip()

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Error al consultar OpenAI: {e}",
        ) from e


def openai_json_completion(
    prompt: str,
    *,
    model: Optional[str] = None,
    temperature: float = 0.3,
    system: Optional[str] = None,
) -> Any:
    validar_openai_habilitado()
    content = openai_chat_completion(
        prompt,
        model=model,
        temperature=temperature,
        system=system,
    )
    parsed = parse_json_openai(content)
    if isinstance(parsed, dict) and parsed.get("error_parse_json"):
        raise HTTPException(
            status_code=502,
            detail="OpenAI devolvió una respuesta que no es JSON válido. Intenta de nuevo.",
        )
    return parsed


# =========================================================
# QUERIES DE CONTEXTO
# =========================================================

def obtener_creador(creador_id: int) -> Optional[Dict[str, Any]]:
    return fetch_one(
        """
        SELECT *
        FROM creadores
        WHERE id = %s
        """,
        (creador_id,),
    )


def obtener_detalle_creador(creador_id: int) -> Optional[Dict[str, Any]]:
    return fetch_one(
        """
        SELECT *
        FROM creadores_detalle
        WHERE creador_id = %s
        """,
        (creador_id,),
    )


def obtener_manager_id_por_creador(creador_id: int) -> Optional[int]:
    row = fetch_one(
        """
        SELECT manager_id
        FROM creadores_detalle
        WHERE creador_id = %s
        """,
        (creador_id,),
    )
    return row["manager_id"] if row else None


def obtener_ultimo_reporte(
    creador_id: int,
    id_reporte: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    if id_reporte:
        return fetch_one(
            """
            SELECT *
            FROM creadores_reporte_integral
            WHERE creador_id = %s
              AND id_reporte = %s
            LIMIT 1
            """,
            (creador_id, id_reporte),
        )

    return fetch_one(
        """
        SELECT *
        FROM creadores_reporte_integral
        WHERE creador_id = %s
        ORDER BY periodo_fin DESC, fecha_carga DESC, id_reporte DESC
        LIMIT 1
        """,
        (creador_id,),
    )


def obtener_metas_por_reporte(
    creador_id: int,
    reporte: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not reporte:
        return None

    return fetch_one(
        """
        SELECT *
        FROM creadores_metas_mensuales
        WHERE creador_id = %s
          AND periodo_inicio = %s
          AND periodo_fin = %s
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (
            creador_id,
            reporte["periodo_inicio"],
            reporte["periodo_fin"],
        ),
    )


def obtener_insights_por_reporte(
    creador_id: int,
    reporte: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not reporte:
        return None

    return fetch_one(
        """
        SELECT *
        FROM creadores_insights_mensuales
        WHERE creador_id = %s
          AND id_reporte = %s
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (
            creador_id,
            reporte["id_reporte"],
        ),
    )


def obtener_score_actual(creador_id: int) -> Optional[Dict[str, Any]]:
    return fetch_one(
        """
        SELECT *
        FROM creadores_performance_score
        WHERE creador_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (creador_id,),
    )


def obtener_alertas_activas(creador_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    return fetch_all(
        """
        SELECT *
        FROM creadores_performance_alertas
        WHERE creador_id = %s
          AND COALESCE(estado, 'activa') IN ('activa', 'pendiente')
        ORDER BY
            CASE nivel_alerta
                WHEN 'critica' THEN 1
                WHEN 'alta' THEN 2
                WHEN 'media' THEN 3
                WHEN 'baja' THEN 4
                ELSE 5
            END,
            created_at DESC,
            id DESC
        LIMIT %s
        """,
        (creador_id, limit),
    )


def obtener_recomendaciones_pendientes(creador_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    return fetch_all(
        """
        SELECT *
        FROM creadores_performance_recomendaciones
        WHERE creador_id = %s
          AND COALESCE(aplicada, false) = false
        ORDER BY
            CASE prioridad
                WHEN 'critica' THEN 1
                WHEN 'alta' THEN 2
                WHEN 'media' THEN 3
                WHEN 'baja' THEN 4
                ELSE 5
            END,
            created_at DESC,
            id DESC
        LIMIT %s
        """,
        (creador_id, limit),
    )


def obtener_ultimos_seguimientos(creador_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    filas = fetch_all(
        """
        SELECT sc.*, au.nombre_completo AS manager_nombre
        FROM creadores_performance_seguimiento sc
        LEFT JOIN administradores au ON sc.manager_id = au.id
        WHERE sc.creador_id = %s
        ORDER BY sc.fecha_seguimiento DESC, sc.id DESC
        LIMIT %s
        """,
        (creador_id, limit),
    )
    return _formatear_lista_seguimientos(filas)


def obtener_acciones_abiertas(creador_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    return fetch_all(
        """
        SELECT a.*, s.creador_id, s.fecha_seguimiento
        FROM creadores_performance_acciones a
        INNER JOIN creadores_performance_seguimiento s
            ON a.seguimiento_id = s.id
        WHERE s.creador_id = %s
          AND COALESCE(a.estado, 'pendiente') NOT IN ('cumplido', 'cancelado')
        ORDER BY
            CASE a.prioridad
                WHEN 'critica' THEN 1
                WHEN 'alta' THEN 2
                WHEN 'media' THEN 3
                WHEN 'baja' THEN 4
                ELSE 5
            END,
            a.fecha_compromiso ASC NULLS LAST,
            a.created_at DESC,
            a.id DESC
        LIMIT %s
        """,
        (creador_id, limit),
    )


def obtener_perfil_respuestas(creador_id: int) -> List[Dict[str, Any]]:
    return fetch_all(
        """
        SELECT
            r.id,
            r.creador_id,
            r.variable_id,
            v.nombre AS variable_nombre,
            v.nombre_natural,
            v.campo_db,
            v.texto AS pregunta,
            c.nombre AS categoria_nombre,
            c.nombre_natural AS categoria_natural,
            r.valor_integer,
            r.valor_numeric,
            r.valor_texto,
            r.valor_json,
            r.valor_id,
            pv.label AS valor_label,
            pv.nivel AS valor_nivel,
            r.created_at,
            r.updated_at
        FROM creadores_perfil_respuesta r
        INNER JOIN creadores_perfil_variable v ON r.variable_id = v.id
        LEFT JOIN creadores_perfil_categoria c ON v.categoria_id = c.id
        LEFT JOIN creadores_perfil_valor pv ON r.valor_id = pv.id
        WHERE r.creador_id = %s
        ORDER BY c.orden ASC NULLS LAST, v.orden ASC NULLS LAST, v.id ASC
        """,
        (creador_id,),
    )


def obtener_categoria_creador(creador_id: int) -> Optional[Dict[str, Any]]:
    row = fetch_one(
        """
        SELECT
            cc.id,
            cc.nombre,
            cc.meta_diamantes_objetivo,
            cc.descripcion,
            cc.orden,
            cc.activa
        FROM creadores c
        LEFT JOIN creadores_categoria cc
            ON c.categoria_id = cc.id
        WHERE c.id = %s
        LIMIT 1
        """,
        (creador_id,),
    )
    if not row or row.get("id") is None:
        return None
    return row


def _ratio_seguro(numerador: Any, denominador: Any, default: float = 0.0) -> float:
    num = safe_float(numerador)
    den = safe_float(denominador)
    if den <= 0:
        return default
    return num / den


def performance_partidas_vacio() -> Dict[str, Any]:
    return {
        "partidas": 0,
        "diamantes_de_partidas": 0,
        "diamantes_mes": 0,
        "diamantes_por_partida": 0,
        "porcentaje_diamantes_por_partidas": 0,
        "partidas_por_emision": 0,
        "diamantes_modo_varios_invitados": 0,
        "diamantes_modo_varios_invitados_anfitrion": 0,
        "diamantes_modo_varios_invitados_invitado": 0,
        "peso_modo_varios_invitados": 0,
        "porcentaje_diamantes_por_partidas_visual": 0,
        "advertencia_partidas": None,
        "diagnostico_partidas": "Sin datos de partidas disponibles.",
    }


def _diagnostico_performance_partidas(
    partidas: float,
    diamantes_de_partidas: float,
    diamantes_mes: float,
    porcentaje_diamantes_por_partidas: float,
) -> str:
    if partidas <= 0:
        return (
            "No registra partidas en el período. Puede existir oportunidad de activar "
            "batallas o dinámicas competitivas."
        )
    if partidas > 0 and diamantes_de_partidas <= 0:
        return (
            "Tiene partidas registradas, pero no generan diamantes relevantes. "
            "Debe mejorar conversión durante partidas."
        )
    if porcentaje_diamantes_por_partidas >= 60:
        return (
            "Alta dependencia de partidas para monetización. Conviene optimizar y "
            "escalar estrategia de batallas."
        )
    if porcentaje_diamantes_por_partidas >= 30:
        return (
            "Las partidas aportan una parte importante de los diamantes. Hay oportunidad "
            "de mejorar eficiencia por partida."
        )
    if porcentaje_diamantes_por_partidas < 30 and diamantes_mes > 0:
        return (
            "Las partidas no son la principal fuente de diamantes. Pueden usarse como "
            "palanca adicional."
        )
    return "Datos de partidas disponibles para análisis."


def construir_performance_partidas(reporte: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not reporte:
        return performance_partidas_vacio()

    partidas = safe_float(reporte.get("partidas"))
    diamantes_de_partidas = safe_float(reporte.get("diamantes_de_partidas"))
    diamantes_mes = safe_float(reporte.get("diamantes_mes"))
    emisiones_live_mes = safe_float(reporte.get("emisiones_live_mes"))
    diam_modo_varios = safe_float(reporte.get("diamantes_modo_varios_invitados"))
    diam_anfitrion = safe_float(reporte.get("diamantes_modo_varios_invitados_anfitrion"))
    diam_invitado = safe_float(reporte.get("diamantes_modo_varios_invitados_invitado"))

    diamantes_por_partida = _ratio_seguro(diamantes_de_partidas, partidas)
    porcentaje_diamantes_por_partidas = _ratio_seguro(diamantes_de_partidas, diamantes_mes) * 100
    partidas_por_emision = _ratio_seguro(partidas, emisiones_live_mes)
    peso_modo_varios_invitados = _ratio_seguro(diam_modo_varios, diamantes_mes) * 100

    diagnostico = _diagnostico_performance_partidas(
        partidas,
        diamantes_de_partidas,
        diamantes_mes,
        porcentaje_diamantes_por_partidas,
    )

    advertencia_partidas = None
    if diamantes_mes > 0 and diamantes_de_partidas > diamantes_mes:
        advertencia_partidas = (
            "diamantes_de_partidas supera diamantes_mes; revisar si ambos campos "
            "corresponden al mismo período o a la misma base de cálculo."
        )

    return {
        "partidas": int(partidas) if partidas == int(partidas) else partidas,
        "diamantes_de_partidas": diamantes_de_partidas,
        "diamantes_mes": diamantes_mes,
        "diamantes_por_partida": round(diamantes_por_partida, 2),
        "porcentaje_diamantes_por_partidas": round(porcentaje_diamantes_por_partidas, 2),
        "porcentaje_diamantes_por_partidas_visual": round(clamp(porcentaje_diamantes_por_partidas), 2),
        "partidas_por_emision": round(partidas_por_emision, 2),
        "diamantes_modo_varios_invitados": diam_modo_varios,
        "diamantes_modo_varios_invitados_anfitrion": diam_anfitrion,
        "diamantes_modo_varios_invitados_invitado": diam_invitado,
        "peso_modo_varios_invitados": round(peso_modo_varios_invitados, 2),
        "advertencia_partidas": advertencia_partidas,
        "diagnostico_partidas": diagnostico,
    }


def _parse_valor_json_perfil(valor_json: Any) -> Any:
    if valor_json is None:
        return None
    if isinstance(valor_json, (dict, list)):
        return valor_json
    if isinstance(valor_json, str):
        texto = valor_json.strip()
        if not texto:
            return None
        try:
            return json.loads(texto)
        except Exception:
            return texto
    return valor_json


def _es_id_opcion_perfil(valor: Any) -> bool:
    """
    Detecta posibles IDs de creadores_perfil_valor.
    Evita tratar booleanos como enteros.
    """
    if isinstance(valor, bool):
        return False

    if isinstance(valor, int):
        return valor > 0

    if isinstance(valor, float):
        return valor.is_integer() and valor > 0

    if isinstance(valor, str):
        texto = valor.strip()
        return texto.isdigit()

    return False


def obtener_label_valor_por_id(valor_id: Any) -> Optional[str]:
    """
    Convierte un valor_id de creadores_perfil_valor en su label.
    Respeta el search_path del tenant; no usa schema test.
    """
    if not _es_id_opcion_perfil(valor_id):
        return None

    try:
        row = fetch_one(
            """
            SELECT label
            FROM creadores_perfil_valor
            WHERE id = %s
            LIMIT 1
            """,
            (int(float(valor_id)),),
        )
        if row and row.get("label") not in (None, ""):
            return str(row["label"]).strip()
    except Exception as e:
        print(f"⚠️ [PERFIL] No se pudo resolver label para valor_id={valor_id}: {e}", flush=True)

    return None


def obtener_labels_valores_por_ids(ids: List[Any]) -> List[Any]:
    """
    Convierte una lista de IDs de creadores_perfil_valor en labels.
    Mantiene el orden original. Si algún ID no existe, conserva el valor original.
    """
    if not ids:
        return []

    ids_limpios: List[int] = []
    for item in ids:
        if _es_id_opcion_perfil(item):
            try:
                ids_limpios.append(int(float(item)))
            except Exception:
                pass

    if not ids_limpios:
        return ids

    try:
        rows = fetch_all(
            """
            SELECT id, label
            FROM creadores_perfil_valor
            WHERE id = ANY(%s)
            """,
            (ids_limpios,),
        )

        mapa = {
            int(row["id"]): str(row["label"]).strip()
            for row in rows
            if row.get("id") is not None and row.get("label") not in (None, "")
        }

        resultado: List[Any] = []
        for item in ids:
            if _es_id_opcion_perfil(item):
                item_int = int(float(item))
                resultado.append(mapa.get(item_int, item))
            else:
                resultado.append(item)
        return resultado

    except Exception as e:
        print(f"⚠️ [PERFIL] No se pudieron resolver labels para ids={ids_limpios}: {e}", flush=True)
        return ids


def _resolver_ids_en_valor_perfil(valor: Any) -> Any:
    """
    Reemplaza IDs numéricos por labels cuando correspondan a creadores_perfil_valor.
    Si no hay label, conserva el valor original.
    """
    if valor is None:
        return None

    if isinstance(valor, list):
        if valor and all(_es_id_opcion_perfil(v) for v in valor):
            return obtener_labels_valores_por_ids(valor)

        resultado: List[Any] = []
        for item in valor:
            resuelto = _resolver_ids_en_valor_perfil(item)
            if resuelto is None:
                continue
            if isinstance(resuelto, list):
                resultado.extend(resuelto)
            else:
                resultado.append(resuelto)
        return resultado

    if isinstance(valor, dict):
        return {
            key: _resolver_ids_en_valor_perfil(item)
            for key, item in valor.items()
        }

    if _es_id_opcion_perfil(valor):
        label = obtener_label_valor_por_id(valor)
        return label if label else valor

    return valor


def obtener_valor_perfil(perfil_respuestas: List[Dict[str, Any]], campo_db: str) -> Any:
    """
    Obtiene y normaliza el valor de un campo_db en perfil_respuestas.

    Prioridad:
    1. valor_json normalizado y con IDs resueltos a labels.
    2. valor_texto.
    3. valor_label, traído desde creadores_perfil_valor.
    4. valor_numeric.
    5. valor_integer resuelto a label si aplica.
    6. valor_id resuelto a label como último recurso.

    Esto evita enviar a OpenAI valores como 740, 751 o 769 cuando existen labels.
    """
    if not perfil_respuestas or not campo_db:
        return None

    campo_buscado = str(campo_db).strip()
    for row in perfil_respuestas:
        if not isinstance(row, dict):
            continue

        if str(row.get("campo_db") or "").strip() != campo_buscado:
            continue

        valor_json = _parse_valor_json_perfil(row.get("valor_json"))
        if valor_json is not None:
            normalizado_json = normalizar_respuesta_perfil(valor_json)
            return _resolver_ids_en_valor_perfil(normalizado_json)

        if row.get("valor_texto") not in (None, ""):
            return row.get("valor_texto")

        if row.get("valor_label") not in (None, ""):
            return row.get("valor_label")

        if row.get("valor_numeric") is not None:
            return row.get("valor_numeric")

        if row.get("valor_integer") is not None:
            label = obtener_label_valor_por_id(row.get("valor_integer"))
            return label if label else row.get("valor_integer")

        if row.get("valor_id") is not None:
            label = obtener_label_valor_por_id(row.get("valor_id"))
            return label if label else row.get("valor_id")

        return None

    return None


def normalizar_respuesta_perfil(valor: Any) -> Any:
    """Normaliza dict/list/string/number de respuestas de perfil a texto o lista legible."""
    if valor is None:
        return None

    if isinstance(valor, str):
        texto = valor.strip()
        if not texto:
            return None
        try:
            return normalizar_respuesta_perfil(json.loads(texto))
        except Exception:
            return texto

    if isinstance(valor, bool):
        return valor

    if isinstance(valor, int):
        label = obtener_label_valor_por_id(valor)
        return label if label else valor

    if isinstance(valor, float):
        if valor.is_integer():
            label = obtener_label_valor_por_id(int(valor))
            return label if label else valor
        return valor

    if isinstance(valor, list):
        if valor and all(_es_id_opcion_perfil(item) for item in valor):
            labels = obtener_labels_valores_por_ids(valor)
            return labels or None

        normalizados: List[Any] = []
        for item in valor:
            n = normalizar_respuesta_perfil(item)
            if n is None:
                continue
            if isinstance(n, list):
                normalizados.extend(n)
            else:
                normalizados.append(n)
        return normalizados or None

    if isinstance(valor, dict):
        if valor.get("label") not in (None, ""):
            return str(valor["label"]).strip()

        opciones = valor.get("opciones") or valor.get("options")
        if opciones is not None:
            return normalizar_respuesta_perfil(opciones)

        if str(valor.get("tipo") or "").lower() == "multiple":
            return normalizar_respuesta_perfil(
                valor.get("opciones") or valor.get("valor") or valor.get("value")
            )

        if valor.get("valor") is not None:
            return normalizar_respuesta_perfil(valor.get("valor"))
        if valor.get("value") is not None:
            return normalizar_respuesta_perfil(valor.get("value"))

        labels: List[str] = []
        for item in valor.values():
            if isinstance(item, dict) and item.get("label") not in (None, ""):
                labels.append(str(item["label"]).strip())
        if labels:
            return labels

        return valor

    return valor


def perfil_estrategico_vacio() -> Dict[str, Any]:
    return {
        "arquetipo_definicion": None,
        "arquetipo_valor": None,
        "intereses": [],
        "horario_preferido": None,
        "nivel_estudios": None,
        "idiomas_dominio": None,
        "categoria_actual": None,
        "meta_categoria_diamantes": None,
        "descripcion_categoria": None,
        "perfil_resumen": None,
    }


def _valor_a_texto_resumen(valor: Any) -> Optional[str]:
    if valor is None:
        return None
    if isinstance(valor, list):
        partes = [str(v).strip() for v in valor if v is not None and str(v).strip()]
        return ", ".join(partes) if partes else None
    texto = str(valor).strip()
    return texto or None


def _campos_categoria_en_perfil(categoria_creador: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not categoria_creador or categoria_creador.get("id") is None:
        return {
            "categoria_actual": None,
            "meta_categoria_diamantes": None,
            "descripcion_categoria": None,
        }
    meta = categoria_creador.get("meta_diamantes_objetivo")
    meta_num = None
    if meta is not None:
        try:
            meta_num = int(meta)
        except (TypeError, ValueError):
            meta_num = safe_int(meta, default=0) or None

    return {
        "categoria_actual": categoria_creador.get("nombre"),
        "meta_categoria_diamantes": meta_num,
        "descripcion_categoria": categoria_creador.get("descripcion"),
    }


def construir_perfil_estrategico(
    perfil_respuestas: Optional[List[Dict[str, Any]]],
    categoria_creador: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    campos_cat = _campos_categoria_en_perfil(categoria_creador)

    if not perfil_respuestas:
        resultado = perfil_estrategico_vacio()
        resultado.update(campos_cat)
        partes_cat: List[str] = []
        if campos_cat.get("categoria_actual"):
            partes_cat.append(f"Categoría: {campos_cat['categoria_actual']}")
        if campos_cat.get("meta_categoria_diamantes") is not None:
            partes_cat.append(f"Meta categoría: {campos_cat['meta_categoria_diamantes']} diamantes")
        if partes_cat:
            resultado["perfil_resumen"] = ". ".join(partes_cat) + "."
        return resultado

    arquetipo_definicion = normalizar_respuesta_perfil(
        obtener_valor_perfil(perfil_respuestas, "arquetipo_definicion")
    )
    arquetipo_valor = normalizar_respuesta_perfil(
        obtener_valor_perfil(perfil_respuestas, "arquetipo_valor")
    )

    intereses_raw = obtener_valor_perfil(perfil_respuestas, "intereses_multiples")
    if intereses_raw is None:
        intereses_raw = obtener_valor_perfil(perfil_respuestas, "intereses")
    intereses_norm = normalizar_respuesta_perfil(intereses_raw)
    if intereses_norm is None:
        intereses: List[Any] = []
    elif isinstance(intereses_norm, list):
        intereses = intereses_norm
    else:
        intereses = [intereses_norm]

    horario_preferido = normalizar_respuesta_perfil(
        obtener_valor_perfil(perfil_respuestas, "horario_preferido")
    )
    nivel_estudios = normalizar_respuesta_perfil(
        obtener_valor_perfil(perfil_respuestas, "nivel_estudios")
    )
    idiomas_norm = normalizar_respuesta_perfil(
        obtener_valor_perfil(perfil_respuestas, "idiomas_dominio")
    )
    if idiomas_norm is None:
        idiomas_dominio = None
    elif isinstance(idiomas_norm, list):
        idiomas_dominio = idiomas_norm
    else:
        idiomas_dominio = idiomas_norm

    partes_resumen: List[str] = []
    if campos_cat.get("categoria_actual"):
        partes_resumen.append(f"Categoría: {campos_cat['categoria_actual']}")
    if campos_cat.get("meta_categoria_diamantes") is not None:
        partes_resumen.append(
            f"Meta categoría: {campos_cat['meta_categoria_diamantes']} diamantes"
        )

    arq_val_txt = _valor_a_texto_resumen(arquetipo_valor)
    if arq_val_txt:
        partes_resumen.append(f"Arquetipo: {arq_val_txt}")

    intereses_txt = _valor_a_texto_resumen(intereses)
    if intereses_txt:
        partes_resumen.append(f"Intereses: {intereses_txt}")

    horario_txt = _valor_a_texto_resumen(horario_preferido)
    if horario_txt:
        partes_resumen.append(f"Horario preferido: {horario_txt}")

    arq_def_txt = _valor_a_texto_resumen(arquetipo_definicion)
    if arq_def_txt:
        partes_resumen.append(f"Nivel de definición de estilo: {arq_def_txt}")

    nivel_txt = _valor_a_texto_resumen(nivel_estudios)
    if nivel_txt:
        partes_resumen.append(f"Nivel de estudios: {nivel_txt}")

    idiomas_txt = _valor_a_texto_resumen(idiomas_dominio)
    if idiomas_txt:
        partes_resumen.append(f"Idiomas: {idiomas_txt}")

    perfil_resumen = ". ".join(partes_resumen) if partes_resumen else None
    if perfil_resumen:
        perfil_resumen = perfil_resumen + "."

    return {
        "arquetipo_definicion": arquetipo_definicion,
        "arquetipo_valor": arquetipo_valor,
        "intereses": intereses,
        "horario_preferido": horario_preferido,
        "nivel_estudios": nivel_estudios,
        "idiomas_dominio": idiomas_dominio,
        **campos_cat,
        "perfil_resumen": perfil_resumen,
    }


def obtener_contexto_performance(
    creador_id: int,
    *,
    id_reporte: Optional[int] = None,
    incluir_perfil: bool = True,
) -> Dict[str, Any]:
    creador = obtener_creador(creador_id)

    if not creador:
        raise HTTPException(status_code=404, detail="Creador no encontrado")

    detalle = obtener_detalle_creador(creador_id)
    ultimo_reporte = obtener_ultimo_reporte(creador_id, id_reporte=id_reporte)
    metas = obtener_metas_por_reporte(creador_id, ultimo_reporte)
    insights = obtener_insights_por_reporte(creador_id, ultimo_reporte)

    perfil_respuestas = obtener_perfil_respuestas(creador_id) if incluir_perfil else []
    categoria_creador = obtener_categoria_creador(creador_id)
    performance_partidas = construir_performance_partidas(ultimo_reporte)

    contexto = {
        "creador": creador,
        "detalle": detalle,
        "categoria_creador": categoria_creador,
        "ultimo_reporte": ultimo_reporte,
        "metas": metas,
        "insights": insights,
        "score": obtener_score_actual(creador_id),
        "alertas": obtener_alertas_activas(creador_id),
        "recomendaciones": obtener_recomendaciones_pendientes(creador_id),
        "seguimientos": obtener_ultimos_seguimientos(creador_id),
        "acciones_abiertas": obtener_acciones_abiertas(creador_id),
        "perfil_respuestas": perfil_respuestas,
        "perfil_estrategico": construir_perfil_estrategico(
            perfil_respuestas, categoria_creador
        ),
        "performance_partidas": performance_partidas,
    }

    return contexto


def obtener_contexto_ia_manager(
    creador_id: int,
    *,
    id_reporte: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Contexto reducido para prompts IA: prioriza perfil_estrategico y limita listas.
    """
    contexto = obtener_contexto_performance(creador_id, id_reporte=id_reporte, incluir_perfil=True)

    return {
        "creador": contexto.get("creador"),
        "detalle": contexto.get("detalle"),
        "categoria_creador": contexto.get("categoria_creador"),
        "ultimo_reporte": contexto.get("ultimo_reporte"),
        "metas": contexto.get("metas"),
        "insights": contexto.get("insights"),
        "score": contexto.get("score"),
        "perfil_estrategico": contexto.get("perfil_estrategico") or perfil_estrategico_vacio(),
        "performance_partidas": contexto.get("performance_partidas") or performance_partidas_vacio(),
        "alertas": (contexto.get("alertas") or [])[:5],
        "recomendaciones": (contexto.get("recomendaciones") or [])[:5],
        "seguimientos": (contexto.get("seguimientos") or [])[:3],
        "acciones_abiertas": (contexto.get("acciones_abiertas") or [])[:5],
    }


# =========================================================
# MOTOR BÁSICO DE SCORE / ALERTAS / RECOMENDACIONES
# =========================================================

def calcular_promedio_valores(valores: List[float]) -> float:
    valores_limpios = [safe_float(v) for v in valores if v is not None]
    if not valores_limpios:
        return 0.0
    return sum(valores_limpios) / len(valores_limpios)


def clasificar_nivel_rendimiento(score: float) -> str:
    score = safe_float(score)
    if score >= 85:
        return "excelente"
    if score >= 70:
        return "alto"
    if score >= 50:
        return "medio"
    if score >= 30:
        return "bajo"
    return "critico"


def clasificar_riesgo_abandono(
    score_general: float,
    consistencia_score: float,
    variacion_duracion: float,
    variacion_emisiones: float,
    variacion_diamantes: float,
) -> str:
    negativos_fuertes = sum([
        1 if variacion_duracion <= -25 else 0,
        1 if variacion_emisiones <= -25 else 0,
        1 if variacion_diamantes <= -25 else 0,
    ])

    if score_general < 35 or consistencia_score < 30 or negativos_fuertes >= 2:
        return "alto"

    if score_general < 55 or consistencia_score < 50 or negativos_fuertes == 1:
        return "medio"

    return "bajo"


def calcular_score_basico(contexto: Dict[str, Any]) -> Dict[str, Any]:
    reporte = contexto.get("ultimo_reporte") or {}
    insights = contexto.get("insights") or {}

    p_diamantes = clamp(safe_float(reporte.get("porcentaje_logro_diamantes")))
    p_duracion = clamp(safe_float(reporte.get("porcentaje_logro_duracion_live")))
    p_dias = clamp(safe_float(reporte.get("porcentaje_logro_dias_validos")))
    p_seguidores = clamp(safe_float(reporte.get("porcentaje_logro_nuevos_seguidores")))
    p_emisiones = clamp(safe_float(reporte.get("porcentaje_logro_emisiones")))

    variacion_diamantes = safe_float(reporte.get("variacion_diamantes_mes_anterior"))
    variacion_duracion = safe_float(reporte.get("variacion_duracion_live_mes_anterior"))
    variacion_dias = safe_float(reporte.get("variacion_dias_validos_mes_anterior"))
    variacion_seguidores = safe_float(reporte.get("variacion_nuevos_seguidores_mes_anterior"))
    variacion_emisiones = safe_float(reporte.get("variacion_emisiones_mes_anterior"))

    consistencia_score = calcular_promedio_valores([p_duracion, p_dias, p_emisiones])
    monetizacion_score = clamp((p_diamantes * 0.75) + (clamp(50 + variacion_diamantes, 0, 100) * 0.25))
    engagement_score = clamp((p_seguidores * 0.80) + (clamp(50 + variacion_seguidores, 0, 100) * 0.20))

    score_general = clamp(
        (monetizacion_score * 0.35)
        + (consistencia_score * 0.35)
        + (engagement_score * 0.20)
        + (p_dias * 0.10)
    )

    nivel = clasificar_nivel_rendimiento(score_general)
    riesgo = clasificar_riesgo_abandono(
        score_general,
        consistencia_score,
        variacion_duracion,
        variacion_emisiones,
        variacion_diamantes,
    )

    crecimiento_base = calcular_promedio_valores([
        clamp(50 + variacion_diamantes, 0, 100),
        clamp(50 + variacion_duracion, 0, 100),
        clamp(50 + variacion_dias, 0, 100),
        clamp(50 + variacion_seguidores, 0, 100),
        clamp(50 + variacion_emisiones, 0, 100),
    ])

    probabilidad_crecimiento = clamp(
        (score_general * 0.55) + (crecimiento_base * 0.45)
    )

    observacion = (
        f"Score calculado automáticamente. Nivel {nivel}. "
        f"Riesgo de abandono {riesgo}. "
        f"Consistencia {round(consistencia_score, 2)}, "
        f"monetización {round(monetizacion_score, 2)} y engagement {round(engagement_score, 2)}."
    )

    if insights.get("alerta_principal"):
        observacion += f" Alerta previa del sistema: {insights.get('alerta_principal')}."

    return {
        "creador_id": contexto["creador"]["id"],
        "id_reporte": reporte.get("id_reporte"),
        "score_general": round(score_general, 2),
        "nivel_rendimiento": nivel,
        "riesgo_abandono": riesgo,
        "probabilidad_crecimiento": round(probabilidad_crecimiento, 2),
        "consistencia_score": round(consistencia_score, 2),
        "monetizacion_score": round(monetizacion_score, 2),
        "engagement_score": round(engagement_score, 2),
        "observacion_ia": observacion,
    }


def detectar_alertas_basicas(contexto: Dict[str, Any]) -> List[Dict[str, Any]]:
    reporte = contexto.get("ultimo_reporte") or {}
    alertas: List[Dict[str, Any]] = []

    if not reporte:
        return alertas

    def agregar(tipo: str, nivel: str, titulo: str, descripcion: str):
        alertas.append({
            "creador_id": contexto["creador"]["id"],
            "id_reporte": reporte.get("id_reporte"),
            "tipo_alerta": tipo,
            "nivel_alerta": nivel,
            "titulo": titulo,
            "descripcion": descripcion,
            "origen": "sistema",
            "estado": "activa",
        })

    p_diamantes = safe_float(reporte.get("porcentaje_logro_diamantes"))
    p_duracion = safe_float(reporte.get("porcentaje_logro_duracion_live"))
    p_dias = safe_float(reporte.get("porcentaje_logro_dias_validos"))
    p_seguidores = safe_float(reporte.get("porcentaje_logro_nuevos_seguidores"))
    p_emisiones = safe_float(reporte.get("porcentaje_logro_emisiones"))

    v_diamantes = safe_float(reporte.get("variacion_diamantes_mes_anterior"))
    v_duracion = safe_float(reporte.get("variacion_duracion_live_mes_anterior"))
    v_emisiones = safe_float(reporte.get("variacion_emisiones_mes_anterior"))
    v_seguidores = safe_float(reporte.get("variacion_nuevos_seguidores_mes_anterior"))

    if p_diamantes < 40:
        agregar(
            "bajo_logro_diamantes",
            "alta",
            "Bajo cumplimiento en diamantes",
            f"El creador tiene {round(p_diamantes, 2)}% de cumplimiento en diamantes.",
        )

    if p_duracion < 50:
        agregar(
            "baja_duracion_live",
            "media",
            "Baja duración acumulada de LIVE",
            f"El cumplimiento de duración LIVE está en {round(p_duracion, 2)}%.",
        )

    if p_dias < 60:
        agregar(
            "bajos_dias_validos",
            "media",
            "Días válidos por debajo de la meta",
            f"El cumplimiento de días válidos está en {round(p_dias, 2)}%.",
        )

    if p_seguidores < 40:
        agregar(
            "bajo_crecimiento_seguidores",
            "alta",
            "Bajo crecimiento de seguidores",
            f"El cumplimiento de nuevos seguidores está en {round(p_seguidores, 2)}%.",
        )

    if p_emisiones < 50:
        agregar(
            "baja_frecuencia_emisiones",
            "media",
            "Baja frecuencia de emisiones",
            f"El cumplimiento de emisiones LIVE está en {round(p_emisiones, 2)}%.",
        )

    if v_diamantes <= -25:
        agregar(
            "caida_diamantes",
            "alta",
            "Caída fuerte en diamantes",
            f"La variación de diamantes frente al mes anterior es {round(v_diamantes, 2)}%.",
        )

    if v_duracion <= -25 or v_emisiones <= -25:
        agregar(
            "caida_actividad_live",
            "alta",
            "Caída en actividad LIVE",
            (
                f"Variación duración LIVE: {round(v_duracion, 2)}%. "
                f"Variación emisiones: {round(v_emisiones, 2)}%."
            ),
        )

    if v_seguidores <= -20:
        agregar(
            "caida_crecimiento_audiencia",
            "media",
            "Caída en crecimiento de audiencia",
            f"La variación de nuevos seguidores es {round(v_seguidores, 2)}%.",
        )

    return alertas


def generar_recomendaciones_basicas(contexto: Dict[str, Any]) -> List[Dict[str, Any]]:
    reporte = contexto.get("ultimo_reporte") or {}
    metas = contexto.get("metas") or {}
    creador_id = contexto["creador"]["id"]

    if not reporte:
        return []

    recomendaciones: List[Dict[str, Any]] = []

    def agregar(categoria: str, prioridad: str, recomendacion: str, justificacion: str):
        recomendaciones.append({
            "creador_id": creador_id,
            "id_reporte": reporte.get("id_reporte"),
            "categoria": categoria,
            "prioridad": prioridad,
            "recomendacion": recomendacion,
            "justificacion": justificacion,
            "aplicada": False,
        })

    p_diamantes = safe_float(reporte.get("porcentaje_logro_diamantes"))
    p_duracion = safe_float(reporte.get("porcentaje_logro_duracion_live"))
    p_dias = safe_float(reporte.get("porcentaje_logro_dias_validos"))
    p_seguidores = safe_float(reporte.get("porcentaje_logro_nuevos_seguidores"))
    p_emisiones = safe_float(reporte.get("porcentaje_logro_emisiones"))

    if p_seguidores < 50:
        agregar(
            "crecimiento_audiencia",
            "alta",
            "Trabajar dinámicas específicas para convertir espectadores en seguidores durante el LIVE.",
            "El cumplimiento de nuevos seguidores está por debajo del nivel esperado.",
        )

    if p_diamantes < 50:
        agregar(
            "monetizacion",
            "alta",
            "Definir metas visibles de regalos, retos por tramos y llamados a la acción sin presionar al usuario.",
            "El cumplimiento de diamantes está bajo frente a la meta mensual.",
        )

    if p_duracion < 60:
        agregar(
            "duracion_live",
            "media",
            "Ajustar bloques de transmisión para sostener más tiempo con energía y estructura.",
            "La duración LIVE acumulada no alcanza el objetivo esperado.",
        )

    if p_dias < 70:
        agregar(
            "disciplina",
            "media",
            "Crear una meta semanal de días válidos con revisión del manager cada 7 días.",
            "Los días válidos están afectando el cumplimiento general.",
        )

    if p_emisiones < 60:
        agregar(
            "frecuencia",
            "media",
            "Planificar una parrilla de emisiones con horarios fijos y recordatorios.",
            "La frecuencia de emisiones está por debajo de la meta.",
        )

    partidas_ctx = contexto.get("performance_partidas") or performance_partidas_vacio()
    partidas = safe_float(partidas_ctx.get("partidas"))
    diamantes_por_partida = safe_float(partidas_ctx.get("diamantes_por_partida"))
    pct_partidas = safe_float(partidas_ctx.get("porcentaje_diamantes_por_partidas"))
    perfil_est = contexto.get("perfil_estrategico") or {}
    arquetipo = str(perfil_est.get("arquetipo_valor") or "").upper()

    if partidas <= 0 and p_diamantes < 70:
        agregar(
            "monetizacion",
            "alta",
            "Activar estrategia de partidas o batallas con metas visibles de diamantes por tramo.",
            "No registra partidas y el cumplimiento de diamantes está por debajo del 70%.",
        )

    if partidas > 0 and diamantes_por_partida > 0 and diamantes_por_partida < 2000:
        agregar(
            "monetizacion",
            "media",
            "Mejorar conversión durante partidas: narrativa, retos, selección de rivales y cierre de regalos.",
            f"Diamantes por partida bajos ({round(diamantes_por_partida, 0)}).",
        )

    if pct_partidas >= 60:
        agregar(
            "monetizacion",
            "media",
            "Optimizar selección de rivales, narrativa competitiva y metas por tramos en batallas.",
            f"Las partidas concentran {round(pct_partidas, 1)}% de los diamantes del mes.",
        )

    if arquetipo == "BATALLISTA" and partidas < 5:
        agregar(
            "contenido",
            "alta",
            "Probar dinámica competitiva o batallas alineadas al arquetipo BATALLISTA en horario preferido.",
            "Arquetipo BATALLISTA con pocas partidas registradas en el período.",
        )

    if not recomendaciones:
        agregar(
            "optimizar_resultados",
            "baja",
            "Mantener la frecuencia actual y optimizar la calidad de interacción para acelerar el crecimiento.",
            "El creador no presenta alertas fuertes, pero puede mejorar conversión y monetización.",
        )

    return recomendaciones


def construir_resumen_basico(contexto: Dict[str, Any], score: Dict[str, Any]) -> Dict[str, Any]:
    reporte = contexto.get("ultimo_reporte") or {}
    if not reporte:
        raise HTTPException(status_code=404, detail="No hay reporte integral para este creador")

    horas_live = round(safe_float(reporte.get("duracion_live_mes_minutos")) / 60, 2)

    return {
        "creador_id": contexto["creador"]["id"],
        "periodo_inicio": reporte.get("periodo_inicio"),
        "periodo_fin": reporte.get("periodo_fin"),
        "diamantes": reporte.get("diamantes_mes"),
        "horas_live": horas_live,
        "dias_validos": reporte.get("dias_validos_live_mes"),
        "emisiones": reporte.get("emisiones_live_mes"),
        "nuevos_seguidores": reporte.get("nuevos_seguidores_mes"),
        "cumplimiento_general": score.get("score_general"),
        "tendencia": determinar_tendencia_reporte(reporte),
        "nivel_rendimiento": score.get("nivel_rendimiento"),
    }


def determinar_tendencia_reporte(reporte: Dict[str, Any]) -> str:
    variaciones = [
        safe_float(reporte.get("variacion_diamantes_mes_anterior")),
        safe_float(reporte.get("variacion_duracion_live_mes_anterior")),
        safe_float(reporte.get("variacion_dias_validos_mes_anterior")),
        safe_float(reporte.get("variacion_nuevos_seguidores_mes_anterior")),
        safe_float(reporte.get("variacion_emisiones_mes_anterior")),
    ]

    promedio = calcular_promedio_valores(variaciones)

    if promedio >= 15:
        return "positiva"
    if promedio <= -15:
        return "negativa"
    return "estable"


# =========================================================
# INSERT HELPERS PERFORMANCE
# =========================================================

def insertar_score(score: Dict[str, Any]) -> Dict[str, Any]:
    return execute_returning(
        """
        INSERT INTO creadores_performance_score (
            creador_id,
            id_reporte,
            score_general,
            nivel_rendimiento,
            riesgo_abandono,
            probabilidad_crecimiento,
            consistencia_score,
            monetizacion_score,
            engagement_score,
            observacion_ia
        )
        VALUES (
            %(creador_id)s,
            %(id_reporte)s,
            %(score_general)s,
            %(nivel_rendimiento)s,
            %(riesgo_abandono)s,
            %(probabilidad_crecimiento)s,
            %(consistencia_score)s,
            %(monetizacion_score)s,
            %(engagement_score)s,
            %(observacion_ia)s
        )
        RETURNING *;
        """,
        score,
    )


def insertar_alerta(alerta: Dict[str, Any]) -> Dict[str, Any]:
    alerta["nivel_alerta"] = validar_valor_en_set(
        alerta.get("nivel_alerta") or "media",
        NIVELES_ALERTA_VALIDOS,
        "nivel_alerta",
    )
    alerta["estado"] = validar_valor_en_set(
        alerta.get("estado") or "activa",
        ESTADOS_ALERTA_VALIDOS,
        "estado",
    )

    return execute_returning(
        """
        INSERT INTO creadores_performance_alertas (
            creador_id,
            id_reporte,
            tipo_alerta,
            nivel_alerta,
            titulo,
            descripcion,
            origen,
            estado
        )
        VALUES (
            %(creador_id)s,
            %(id_reporte)s,
            %(tipo_alerta)s,
            %(nivel_alerta)s,
            %(titulo)s,
            %(descripcion)s,
            %(origen)s,
            %(estado)s
        )
        RETURNING *;
        """,
        alerta,
    )


def insertar_recomendacion(recomendacion: Dict[str, Any]) -> Dict[str, Any]:
    recomendacion["prioridad"] = validar_valor_en_set(
        recomendacion.get("prioridad") or "media",
        PRIORIDADES_VALIDAS,
        "prioridad",
    )

    return execute_returning(
        """
        INSERT INTO creadores_performance_recomendaciones (
            creador_id,
            id_reporte,
            categoria,
            prioridad,
            recomendacion,
            justificacion,
            aplicada
        )
        VALUES (
            %(creador_id)s,
            %(id_reporte)s,
            %(categoria)s,
            %(prioridad)s,
            %(recomendacion)s,
            %(justificacion)s,
            %(aplicada)s
        )
        RETURNING *;
        """,
        recomendacion,
    )


def insertar_resumen(resumen: Dict[str, Any]) -> Dict[str, Any]:
    return execute_returning(
        """
        INSERT INTO creadores_performance_resumen (
            creador_id,
            periodo_inicio,
            periodo_fin,
            diamantes,
            horas_live,
            dias_validos,
            emisiones,
            nuevos_seguidores,
            cumplimiento_general,
            tendencia,
            nivel_rendimiento
        )
        VALUES (
            %(creador_id)s,
            %(periodo_inicio)s,
            %(periodo_fin)s,
            %(diamantes)s,
            %(horas_live)s,
            %(dias_validos)s,
            %(emisiones)s,
            %(nuevos_seguidores)s,
            %(cumplimiento_general)s,
            %(tendencia)s,
            %(nivel_rendimiento)s
        )
        RETURNING *;
        """,
        resumen,
    )


def insertar_accion(
    seguimiento_id: int,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    prioridad = validar_valor_en_set(
        data.get("prioridad") or "media",
        PRIORIDADES_VALIDAS,
        "prioridad",
    )
    estado = validar_valor_en_set(
        data.get("estado") or "pendiente",
        ESTADOS_ACCION_VALIDOS,
        "estado",
    )

    params = {
        "seguimiento_id": seguimiento_id,
        "tipo_accion": data.get("tipo_accion"),
        "titulo": data.get("titulo"),
        "descripcion": data.get("descripcion"),
        "prioridad": prioridad,
        "estado": estado,
        "fecha_compromiso": data.get("fecha_compromiso"),
        "creado_por": data.get("creado_por"),
    }

    if not params["tipo_accion"]:
        raise HTTPException(status_code=400, detail="tipo_accion es requerido")

    return execute_returning(
        """
        INSERT INTO creadores_performance_acciones (
            seguimiento_id,
            tipo_accion,
            titulo,
            descripcion,
            prioridad,
            estado,
            fecha_compromiso,
            creado_por
        )
        VALUES (
            %(seguimiento_id)s,
            %(tipo_accion)s,
            %(titulo)s,
            %(descripcion)s,
            %(prioridad)s,
            %(estado)s,
            %(fecha_compromiso)s,
            %(creado_por)s
        )
        RETURNING *;
        """,
        params,
    )


# =========================================================
# ENDPOINTS — ESTADO OPENAI
# =========================================================

@router.get("/api/creadores/performance/openai/estado")
def estado_openai_performance():
    return {
        "ok": True,
        "clave_config": OPENAI_CONFIG_CLAVE,
        "habilitado_agencia": openai_habilitado_en_agencia(),
        "api_key_configurada": openai_api_key_configurada(),
        "puede_usarse": openai_disponible(),
        "modelo": OPENAI_MODEL_DEFAULT,
    }


# =========================================================
# ENDPOINTS — DASHBOARD / CONTEXTO
# =========================================================

@router.get(
    "/api/creadores/performance/{creador_id}/dashboard",
    response_model=DashboardPerformanceResponse,
)
def dashboard_performance_creador(
    creador_id: int,
    id_reporte: Optional[int] = Query(default=None),
):
    contexto = obtener_contexto_performance(creador_id, id_reporte=id_reporte)
    return {
        "ok": True,
        **contexto,
    }


@router.get("/api/creadores/performance/{creador_id}/contexto")
def contexto_performance_creador(
    creador_id: int,
    id_reporte: Optional[int] = Query(default=None),
    incluir_perfil: bool = Query(default=True),
):
    return {
        "ok": True,
        "contexto": obtener_contexto_performance(
            creador_id,
            id_reporte=id_reporte,
            incluir_perfil=incluir_perfil,
        ),
    }


@router.get("/api/creadores/performance/{creador_id}/metricas")
def metricas_performance_creador(creador_id: int):
    creador = obtener_creador(creador_id)
    if not creador:
        raise HTTPException(status_code=404, detail="Creador no encontrado")

    reportes = fetch_all(
        """
        SELECT *
        FROM creadores_reporte_integral
        WHERE creador_id = %s
        ORDER BY periodo_fin DESC, fecha_carga DESC, id_reporte DESC
        """,
        (creador_id,),
    )

    return {
        "ok": True,
        "creador_id": creador_id,
        "reportes": reportes,
    }


@router.get("/api/creadores/performance/{creador_id}/metas")
def metas_performance_creador(creador_id: int):
    metas = fetch_all(
        """
        SELECT *
        FROM creadores_metas_mensuales
        WHERE creador_id = %s
        ORDER BY periodo_fin DESC, created_at DESC, id DESC
        """,
        (creador_id,),
    )
    return {"ok": True, "creador_id": creador_id, "metas": metas}


@router.get("/api/creadores/performance/{creador_id}/insights")
def insights_performance_creador(creador_id: int):
    insights = fetch_all(
        """
        SELECT *
        FROM creadores_insights_mensuales
        WHERE creador_id = %s
        ORDER BY periodo_fin DESC, created_at DESC, id DESC
        """,
        (creador_id,),
    )
    return {"ok": True, "creador_id": creador_id, "insights": insights}


@router.get("/api/creadores/performance/{creador_id}/perfil-respuestas")
def perfil_respuestas_performance_creador(creador_id: int):
    perfil_respuestas = obtener_perfil_respuestas(creador_id)
    return {
        "ok": True,
        "creador_id": creador_id,
        "perfil_respuestas": perfil_respuestas,
        "perfil_estrategico": construir_perfil_estrategico(
            perfil_respuestas,
            obtener_categoria_creador(creador_id),
        ),
    }


# =========================================================
# ENDPOINTS — SEGUIMIENTOS
# =========================================================

@router.post("/api/creadores/performance/seguimientos")
def crear_seguimiento_performance(seg: SeguimientoPerformanceCreate):
    if not seg.creador_id:
        raise HTTPException(status_code=400, detail="creador_id es requerido")

    creador = obtener_creador(seg.creador_id)
    if not creador:
        raise HTTPException(status_code=404, detail="Creador no encontrado")

    manager_id = obtener_manager_id_por_creador(seg.creador_id)

    if manager_id is None:
        raise HTTPException(
            status_code=404,
            detail="No se encontró manager asociado en creadores_detalle",
        )

    fecha = seg.fecha_seguimiento or date.today()
    observaciones = normalizar_texto_parrafos(seg.observaciones_manager)
    compromisos = normalizar_texto_parrafos(seg.resumen_compromisos)

    fila = execute_returning(
        """
        INSERT INTO creadores_performance_seguimiento (
            creador_id,
            manager_id,
            fecha_seguimiento,
            observaciones_manager,
            resumen_compromisos
        )
        VALUES (
            %(creador_id)s,
            %(manager_id)s,
            %(fecha_seguimiento)s,
            %(observaciones_manager)s,
            %(resumen_compromisos)s
        )
        RETURNING *;
        """,
        {
            "creador_id": seg.creador_id,
            "manager_id": manager_id,
            "fecha_seguimiento": fecha,
            "observaciones_manager": observaciones,
            "resumen_compromisos": compromisos,
        },
    )
    return _formatear_seguimiento_respuesta(fila)


@router.post("/api/creadores/performance/seguimientos-con-acciones")
def crear_seguimiento_con_acciones(data: SeguimientoConAccionesCreate):
    seguimiento = crear_seguimiento_performance(
        SeguimientoPerformanceCreate(
            creador_id=data.creador_id,
            fecha_seguimiento=data.fecha_seguimiento,
            observaciones_manager=data.observaciones_manager,
            resumen_compromisos=data.resumen_compromisos,
        )
    )

    acciones_creadas = []
    for accion in data.acciones:
        accion_dict = model_to_dict(accion)
        acciones_creadas.append(insertar_accion(seguimiento["id"], accion_dict))

    seguimiento["acciones"] = acciones_creadas
    return seguimiento


@router.get("/api/creadores/performance/{creador_id}/seguimientos")
def listar_seguimientos_performance(
    creador_id: int,
    limit: int = Query(default=100, ge=1, le=500),
):
    filas = fetch_all(
        """
        SELECT sc.*, au.nombre_completo AS manager_nombre
        FROM creadores_performance_seguimiento sc
        LEFT JOIN administradores au ON sc.manager_id = au.id
        WHERE sc.creador_id = %s
        ORDER BY sc.fecha_seguimiento DESC, sc.id DESC
        LIMIT %s
        """,
        (creador_id, limit),
    )
    return _formatear_lista_seguimientos(filas)


@router.get("/api/creadores/performance/seguimientos/{seguimiento_id}")
def obtener_seguimiento_performance(seguimiento_id: int):
    seguimiento = fetch_one(
        """
        SELECT sc.*, au.nombre_completo AS manager_nombre
        FROM creadores_performance_seguimiento sc
        LEFT JOIN administradores au ON sc.manager_id = au.id
        WHERE sc.id = %s
        """,
        (seguimiento_id,),
    )

    if not seguimiento:
        raise HTTPException(status_code=404, detail="Seguimiento no encontrado")

    acciones = fetch_all(
        """
        SELECT *
        FROM creadores_performance_acciones
        WHERE seguimiento_id = %s
        ORDER BY created_at DESC, id DESC
        """,
        (seguimiento_id,),
    )

    seguimiento["acciones"] = acciones
    return _formatear_seguimiento_respuesta(seguimiento)


@router.put("/api/creadores/performance/seguimientos/{seguimiento_id}")
def actualizar_seguimiento_performance(
    seguimiento_id: int,
    data: SeguimientoPerformanceUpdate,
):
    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_seguimiento
        WHERE id = %s
        """,
        (seguimiento_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Seguimiento no encontrado")

    payload = model_to_dict(data, exclude_unset=True)
    if "observaciones_manager" in payload:
        payload["observaciones_manager"] = normalizar_texto_parrafos(
            payload["observaciones_manager"]
        )
    if "resumen_compromisos" in payload:
        payload["resumen_compromisos"] = normalizar_texto_parrafos(
            payload["resumen_compromisos"]
        )

    actualizado = update_row_dynamic(
        table_name="creadores_performance_seguimiento",
        id_column="id",
        id_value=seguimiento_id,
        data=payload,
        allowed_fields={
            "fecha_seguimiento",
            "observaciones_manager",
            "resumen_compromisos",
        },
    )
    return _formatear_seguimiento_respuesta(actualizado)


@router.delete("/api/creadores/performance/seguimientos/{seguimiento_id}")
def eliminar_seguimiento_performance(seguimiento_id: int):
    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_seguimiento
        WHERE id = %s
        """,
        (seguimiento_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Seguimiento no encontrado")

    execute_no_return(
        """
        DELETE FROM creadores_performance_acciones
        WHERE seguimiento_id = %s
        """,
        (seguimiento_id,),
    )
    execute_no_return(
        """
        DELETE FROM creadores_performance_seguimiento
        WHERE id = %s
        """,
        (seguimiento_id,),
    )

    return {"ok": True, "message": "Seguimiento eliminado"}


# Compatibilidad con rutas antiguas
@router.post("/api/seguimiento_creadores/")
def crear_seguimiento_creador_legacy(seg: SeguimientoPerformanceCreate):
    return crear_seguimiento_performance(seg)


@router.get("/api/seguimiento_creadores/creador/{creador_id}")
def listar_seguimientos_por_creador_legacy(creador_id: int):
    return listar_seguimientos_performance(creador_id)


# =========================================================
# ENDPOINTS — ACCIONES
# =========================================================

@router.post("/api/creadores/performance/acciones")
def crear_accion_performance(data: AccionPerformanceCreate):
    seguimiento = fetch_one(
        """
        SELECT *
        FROM creadores_performance_seguimiento
        WHERE id = %s
        """,
        (data.seguimiento_id,),
    )

    if not seguimiento:
        raise HTTPException(status_code=404, detail="Seguimiento no encontrado")

    return insertar_accion(data.seguimiento_id, model_to_dict(data))


@router.get("/api/creadores/performance/{creador_id}/acciones")
def listar_acciones_por_creador(
    creador_id: int,
    estado: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
):
    params: List[Any] = [creador_id]
    filtro_estado = ""

    if estado:
        estado_norm = validar_valor_en_set(estado, ESTADOS_ACCION_VALIDOS, "estado")
        filtro_estado = " AND COALESCE(a.estado, 'pendiente') = %s "
        params.append(estado_norm)

    params.append(limit)

    return fetch_all(
        f"""
        SELECT a.*, s.creador_id, s.fecha_seguimiento
        FROM creadores_performance_acciones a
        INNER JOIN creadores_performance_seguimiento s
            ON a.seguimiento_id = s.id
        WHERE s.creador_id = %s
        {filtro_estado}
        ORDER BY
            CASE a.prioridad
                WHEN 'critica' THEN 1
                WHEN 'alta' THEN 2
                WHEN 'media' THEN 3
                WHEN 'baja' THEN 4
                ELSE 5
            END,
            a.fecha_compromiso ASC NULLS LAST,
            a.created_at DESC,
            a.id DESC
        LIMIT %s
        """,
        tuple(params),
    )


@router.get("/api/creadores/performance/acciones/{accion_id}")
def obtener_accion_performance(accion_id: int):
    accion = fetch_one(
        """
        SELECT a.*, s.creador_id, s.fecha_seguimiento
        FROM creadores_performance_acciones a
        INNER JOIN creadores_performance_seguimiento s
            ON a.seguimiento_id = s.id
        WHERE a.id = %s
        """,
        (accion_id,),
    )

    if not accion:
        raise HTTPException(status_code=404, detail="Acción no encontrada")

    return accion


@router.put("/api/creadores/performance/acciones/{accion_id}")
def actualizar_accion_performance(
    accion_id: int,
    data: AccionPerformanceUpdate,
):
    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_acciones
        WHERE id = %s
        """,
        (accion_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Acción no encontrada")

    payload = model_to_dict(data, exclude_unset=True)

    if "prioridad" in payload:
        payload["prioridad"] = validar_valor_en_set(
            payload.get("prioridad"),
            PRIORIDADES_VALIDAS,
            "prioridad",
        )

    if "estado" in payload:
        payload["estado"] = validar_valor_en_set(
            payload.get("estado"),
            ESTADOS_ACCION_VALIDOS,
            "estado",
        )

    payload["updated_at"] = datetime.now()

    return update_row_dynamic(
        table_name="creadores_performance_acciones",
        id_column="id",
        id_value=accion_id,
        data=payload,
        allowed_fields={
            "tipo_accion",
            "titulo",
            "descripcion",
            "prioridad",
            "estado",
            "fecha_compromiso",
            "fecha_cumplimiento",
            "updated_at",
        },
    )


@router.patch("/api/creadores/performance/acciones/{accion_id}/estado")
def cambiar_estado_accion_performance(
    accion_id: int,
    data: AccionEstadoUpdate,
):
    estado_norm = validar_valor_en_set(
        data.estado,
        ESTADOS_ACCION_VALIDOS,
        "estado",
        requerido=True,
    )

    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_acciones
        WHERE id = %s
        """,
        (accion_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Acción no encontrada")

    fecha_cumplimiento = data.fecha_cumplimiento

    if estado_norm == "cumplido" and not fecha_cumplimiento:
        fecha_cumplimiento = date.today()

    return execute_returning(
        """
        UPDATE creadores_performance_acciones
        SET
            estado = %(estado)s,
            fecha_cumplimiento = %(fecha_cumplimiento)s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %(id)s
        RETURNING *;
        """,
        {
            "id": accion_id,
            "estado": estado_norm,
            "fecha_cumplimiento": fecha_cumplimiento,
        },
    )


@router.delete("/api/creadores/performance/acciones/{accion_id}")
def eliminar_accion_performance(accion_id: int):
    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_acciones
        WHERE id = %s
        """,
        (accion_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Acción no encontrada")

    execute_no_return(
        """
        DELETE FROM creadores_performance_acciones
        WHERE id = %s
        """,
        (accion_id,),
    )

    return {"ok": True, "message": "Acción eliminada"}


# =========================================================
# ENDPOINTS — ALERTAS
# =========================================================

@router.post("/api/creadores/performance/alertas")
def crear_alerta_performance(data: AlertaPerformanceCreate):
    payload = model_to_dict(data)
    return insertar_alerta(payload)


@router.get("/api/creadores/performance/{creador_id}/alertas")
def listar_alertas_performance(
    creador_id: int,
    estado: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    params: List[Any] = [creador_id]
    filtro_estado = ""

    if estado:
        estado_norm = validar_valor_en_set(estado, ESTADOS_ALERTA_VALIDOS, "estado")
        filtro_estado = " AND COALESCE(estado, 'activa') = %s "
        params.append(estado_norm)

    params.append(limit)

    return fetch_all(
        f"""
        SELECT *
        FROM creadores_performance_alertas
        WHERE creador_id = %s
        {filtro_estado}
        ORDER BY
            CASE nivel_alerta
                WHEN 'critica' THEN 1
                WHEN 'alta' THEN 2
                WHEN 'media' THEN 3
                WHEN 'baja' THEN 4
                ELSE 5
            END,
            created_at DESC,
            id DESC
        LIMIT %s
        """,
        tuple(params),
    )


@router.put("/api/creadores/performance/alertas/{alerta_id}")
def actualizar_alerta_performance(
    alerta_id: int,
    data: AlertaPerformanceUpdate,
):
    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_alertas
        WHERE id = %s
        """,
        (alerta_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    payload = model_to_dict(data, exclude_unset=True)

    if "nivel_alerta" in payload:
        payload["nivel_alerta"] = validar_valor_en_set(
            payload.get("nivel_alerta"),
            NIVELES_ALERTA_VALIDOS,
            "nivel_alerta",
        )

    if "estado" in payload:
        payload["estado"] = validar_valor_en_set(
            payload.get("estado"),
            ESTADOS_ALERTA_VALIDOS,
            "estado",
        )

    return update_row_dynamic(
        table_name="creadores_performance_alertas",
        id_column="id",
        id_value=alerta_id,
        data=payload,
        allowed_fields={
            "tipo_alerta",
            "nivel_alerta",
            "titulo",
            "descripcion",
            "origen",
            "estado",
            "resolved_at",
        },
    )


@router.patch("/api/creadores/performance/alertas/{alerta_id}/resolver")
def resolver_alerta_performance(
    alerta_id: int,
    data: ResolverAlertaRequest = ResolverAlertaRequest(),
):
    estado_norm = validar_valor_en_set(
        data.estado or "resuelta",
        ESTADOS_ALERTA_VALIDOS,
        "estado",
    )

    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_alertas
        WHERE id = %s
        """,
        (alerta_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    return execute_returning(
        """
        UPDATE creadores_performance_alertas
        SET
            estado = %(estado)s,
            resolved_at = CURRENT_TIMESTAMP
        WHERE id = %(id)s
        RETURNING *;
        """,
        {
            "id": alerta_id,
            "estado": estado_norm,
        },
    )


@router.delete("/api/creadores/performance/alertas/{alerta_id}")
def eliminar_alerta_performance(alerta_id: int):
    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_alertas
        WHERE id = %s
        """,
        (alerta_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    execute_no_return(
        """
        DELETE FROM creadores_performance_alertas
        WHERE id = %s
        """,
        (alerta_id,),
    )

    return {"ok": True, "message": "Alerta eliminada"}


# =========================================================
# ENDPOINTS — RECOMENDACIONES
# =========================================================

@router.post("/api/creadores/performance/recomendaciones")
def crear_recomendacion_performance(data: RecomendacionPerformanceCreate):
    payload = model_to_dict(data)
    return insertar_recomendacion(payload)


@router.get("/api/creadores/performance/{creador_id}/recomendaciones")
def listar_recomendaciones_performance(
    creador_id: int,
    aplicada: Optional[bool] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    params: List[Any] = [creador_id]
    filtro = ""

    if aplicada is not None:
        filtro = " AND COALESCE(aplicada, false) = %s "
        params.append(aplicada)

    params.append(limit)

    return fetch_all(
        f"""
        SELECT *
        FROM creadores_performance_recomendaciones
        WHERE creador_id = %s
        {filtro}
        ORDER BY
            CASE prioridad
                WHEN 'critica' THEN 1
                WHEN 'alta' THEN 2
                WHEN 'media' THEN 3
                WHEN 'baja' THEN 4
                ELSE 5
            END,
            created_at DESC,
            id DESC
        LIMIT %s
        """,
        tuple(params),
    )


@router.put("/api/creadores/performance/recomendaciones/{recomendacion_id}")
def actualizar_recomendacion_performance(
    recomendacion_id: int,
    data: RecomendacionPerformanceUpdate,
):
    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_recomendaciones
        WHERE id = %s
        """,
        (recomendacion_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Recomendación no encontrada")

    payload = model_to_dict(data, exclude_unset=True)

    if "prioridad" in payload:
        payload["prioridad"] = validar_valor_en_set(
            payload.get("prioridad"),
            PRIORIDADES_VALIDAS,
            "prioridad",
        )

    if payload.get("aplicada") is True and not payload.get("aplicada_at"):
        payload["aplicada_at"] = datetime.now()

    if payload.get("aplicada") is False:
        payload["aplicada_at"] = None

    return update_row_dynamic(
        table_name="creadores_performance_recomendaciones",
        id_column="id",
        id_value=recomendacion_id,
        data=payload,
        allowed_fields={
            "categoria",
            "prioridad",
            "recomendacion",
            "justificacion",
            "aplicada",
            "aplicada_at",
        },
    )


@router.patch("/api/creadores/performance/recomendaciones/{recomendacion_id}/aplicar")
def aplicar_recomendacion_performance(
    recomendacion_id: int,
    data: AplicarRecomendacionRequest = AplicarRecomendacionRequest(),
):
    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_recomendaciones
        WHERE id = %s
        """,
        (recomendacion_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Recomendación no encontrada")

    aplicada_at = datetime.now() if data.aplicada else None

    return execute_returning(
        """
        UPDATE creadores_performance_recomendaciones
        SET
            aplicada = %(aplicada)s,
            aplicada_at = %(aplicada_at)s
        WHERE id = %(id)s
        RETURNING *;
        """,
        {
            "id": recomendacion_id,
            "aplicada": data.aplicada,
            "aplicada_at": aplicada_at,
        },
    )


@router.delete("/api/creadores/performance/recomendaciones/{recomendacion_id}")
def eliminar_recomendacion_performance(recomendacion_id: int):
    existente = fetch_one(
        """
        SELECT *
        FROM creadores_performance_recomendaciones
        WHERE id = %s
        """,
        (recomendacion_id,),
    )

    if not existente:
        raise HTTPException(status_code=404, detail="Recomendación no encontrada")

    execute_no_return(
        """
        DELETE FROM creadores_performance_recomendaciones
        WHERE id = %s
        """,
        (recomendacion_id,),
    )

    return {"ok": True, "message": "Recomendación eliminada"}


# =========================================================
# ENDPOINTS — SCORE / RESUMEN
# =========================================================

@router.get("/api/creadores/performance/{creador_id}/score")
def obtener_score_performance(creador_id: int):
    score = obtener_score_actual(creador_id)
    return {
        "ok": True,
        "creador_id": creador_id,
        "score": score,
    }


@router.get("/api/creadores/performance/{creador_id}/score/historial")
def historial_score_performance(
    creador_id: int,
    limit: int = Query(default=50, ge=1, le=500),
):
    scores = fetch_all(
        """
        SELECT *
        FROM creadores_performance_score
        WHERE creador_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT %s
        """,
        (creador_id, limit),
    )
    return {
        "ok": True,
        "creador_id": creador_id,
        "scores": scores,
    }


@router.post("/api/creadores/performance/score")
def crear_score_performance(data: ScorePerformanceCreate):
    payload = model_to_dict(data)
    return insertar_score(payload)


@router.post("/api/creadores/performance/{creador_id}/score/recalcular")
def recalcular_score_performance(
    creador_id: int,
    guardar: bool = Query(default=True),
):
    contexto = obtener_contexto_performance(creador_id)
    score = calcular_score_basico(contexto)

    if guardar:
        score_guardado = insertar_score(score)
        return {
            "ok": True,
            "guardado": True,
            "score": score_guardado,
        }

    return {
        "ok": True,
        "guardado": False,
        "score": score,
    }


@router.get("/api/creadores/performance/{creador_id}/resumen")
def obtener_resumen_performance(
    creador_id: int,
    limit: int = Query(default=24, ge=1, le=120),
):
    resumen = fetch_all(
        """
        SELECT *
        FROM creadores_performance_resumen
        WHERE creador_id = %s
        ORDER BY periodo_fin DESC, created_at DESC, id DESC
        LIMIT %s
        """,
        (creador_id, limit),
    )
    return {
        "ok": True,
        "creador_id": creador_id,
        "resumen": resumen,
    }


@router.post("/api/creadores/performance/resumen")
def crear_resumen_performance(data: ResumenPerformanceCreate):
    payload = model_to_dict(data)
    return insertar_resumen(payload)


@router.post("/api/creadores/performance/{creador_id}/resumen/recalcular")
def recalcular_resumen_performance(
    creador_id: int,
    guardar: bool = Query(default=True),
):
    contexto = obtener_contexto_performance(creador_id)
    score = calcular_score_basico(contexto)
    resumen = construir_resumen_basico(contexto, score)

    if guardar:
        resumen_guardado = insertar_resumen(resumen)
        return {
            "ok": True,
            "guardado": True,
            "resumen": resumen_guardado,
        }

    return {
        "ok": True,
        "guardado": False,
        "resumen": resumen,
    }


# =========================================================
# ENDPOINTS — ANÁLISIS BÁSICO SIN IA
# =========================================================

@router.post("/api/creadores/performance/{creador_id}/analisis-basico")
def generar_analisis_basico_performance(
    creador_id: int,
    guardar: bool = Query(default=True),
):
    contexto = obtener_contexto_performance(creador_id)

    score = calcular_score_basico(contexto)
    alertas = detectar_alertas_basicas(contexto)
    recomendaciones = generar_recomendaciones_basicas(contexto)
    resumen = construir_resumen_basico(contexto, score)

    resultado: Dict[str, Any] = {
        "ok": True,
        "guardado": guardar,
        "score": score,
        "alertas": alertas,
        "recomendaciones": recomendaciones,
        "resumen": resumen,
    }

    if guardar:
        resultado["score"] = insertar_score(score)
        resultado["alertas"] = [insertar_alerta(a) for a in alertas]
        resultado["recomendaciones"] = [insertar_recomendacion(r) for r in recomendaciones]
        resultado["resumen"] = insertar_resumen(resumen)

    return resultado


# =========================================================
# PROMPTS IA
# =========================================================

_FRASES_IA_PROHIBIDAS = (
    "incluir temas de interés",
    "temas de interés relacionados",
    "mejorar contenido",
    "alinear contenido con su arquetipo",
    "alinear contenido con el arquetipo",
    "aumentar interacción",
    "aumentar la interacción",
    "optimizar contenido",
    "trabajar el contenido",
    "enfocarse en intereses",
    "dinámicas acordes a su perfil",
)


def _texto_campo_perfil(valor: Any) -> Optional[str]:
    if valor is None:
        return None
    if isinstance(valor, dict):
        for clave in ("label", "nombre", "valor", "texto", "value"):
            if valor.get(clave):
                return str(valor[clave]).strip()
        return str(valor).strip() or None
    if isinstance(valor, list):
        partes = [_texto_campo_perfil(v) for v in valor]
        partes_limpias = [p for p in partes if p]
        return ", ".join(partes_limpias) if partes_limpias else None
    texto = str(valor).strip()
    return texto or None


def _intereses_texto(perfil: Dict[str, Any]) -> List[str]:
    raw = perfil.get("intereses") or []
    if isinstance(raw, list):
        resultado: List[str] = []
        for item in raw:
            t = _texto_campo_perfil(item)
            if t and t not in resultado:
                resultado.append(t)
        return resultado
    t = _texto_campo_perfil(raw)
    return [t] if t else []


def _nombre_creador_contexto(contexto: Dict[str, Any]) -> Optional[str]:
    creador = contexto.get("creador") or {}
    for campo in ("nombre", "nombre_real", "nickname", "usuario_tiktok", "usuario"):
        valor = creador.get(campo)
        if valor and str(valor).strip():
            return str(valor).strip()
    return None


def _reglas_personalizacion_ia_obligatorias(contexto: Dict[str, Any]) -> str:
    """
    Reglas compartidas para evitar respuestas genéricas en todos los prompts IA de performance.
    """
    perfil = contexto.get("perfil_estrategico") or {}
    categoria = contexto.get("categoria_creador") or {}
    partidas = contexto.get("performance_partidas") or {}

    arquetipo = _texto_campo_perfil(perfil.get("arquetipo_valor"))
    horario = _texto_campo_perfil(perfil.get("horario_preferido"))
    intereses = _intereses_texto(perfil)
    cat_nombre = categoria.get("nombre")
    cat_meta = categoria.get("meta_diamantes_objetivo")
    nombre_creador = _nombre_creador_contexto(contexto)

    checklist: List[str] = []
    if nombre_creador:
        checklist.append(f"- Usa el nombre del creador: {nombre_creador}")
    if arquetipo:
        checklist.append(
            f"- Menciona el arquetipo por nombre exacto: {arquetipo} "
            "(no digas solo «su arquetipo» ni «el arquetipo del creador»)."
        )
    if intereses:
        lista = ", ".join(intereses[:8])
        minimo = min(2, len(intereses))
        checklist.append(
            f"- Cita al menos {minimo} interés(es) concretos de perfil_estrategico.intereses: {lista}"
        )
    if horario:
        checklist.append(
            f"- Adapta horarios y frecuencia al horario_preferido: {horario}"
        )
    if cat_nombre:
        linea = f"- Referencia la categoría creador: {cat_nombre}"
        if cat_meta is not None:
            linea += f" (meta_diamantes_objetivo: {cat_meta})"
        checklist.append(linea)
    elif cat_meta is not None:
        checklist.append(f"- Referencia meta_diamantes_objetivo: {cat_meta}")

    n_partidas = safe_float(partidas.get("partidas"))
    pct_partidas = safe_float(partidas.get("porcentaje_diamantes_por_partidas"))
    diag_part = partidas.get("diagnostico_partidas")
    if n_partidas > 0 or pct_partidas > 0 or diag_part:
        checklist.append(
            "- Analiza performance_partidas: indica si las partidas son oportunidad "
            "subutilizada o fuente principal de diamantes, citando partidas, "
            "porcentaje_diamantes_por_partidas y diagnostico_partidas del contexto."
        )

    prohibidas = "\n".join(f'  · "{f}"' for f in _FRASES_IA_PROHIBIDAS)
    obligatorias = (
        "\n".join(checklist)
        if checklist
        else (
            "- Si faltan datos en el contexto, indícalo explícitamente; "
            "no rellenes con frases genéricas."
        )
    )

    ejemplo_malo = (
        'INCORRECTO: "Incluir temas de interés relacionados con sus arquetipos."'
    )
    ejemplo_bueno = (
        'CORRECTO: "Como Nicolisita tiene arquetipo BATALLISTA y sus intereses son '
        "Fitness, Música y Lectura, probar 3 lives nocturnos con dinámica de batalla "
        'fitness, música energética y preguntas rápidas para aumentar comentarios, '
        'seguidores y regalos."'
    )

    return f"""
REGLAS OBLIGATORIAS DE PERSONALIZACIÓN (prioridad sobre cualquier otra instrucción):
Usa obligatoriamente del JSON de contexto, si existen y no son null:
- perfil_estrategico.arquetipo_valor
- perfil_estrategico.intereses
- perfil_estrategico.horario_preferido
- categoria_creador.nombre
- categoria_creador.meta_diamantes_objetivo
- performance_partidas (métricas y diagnostico_partidas)

Checklist para ESTE creador:
{obligatorias}

PROHIBIDO usar frases vagas como:
{prohibidas}

{ejemplo_malo}
{ejemplo_bueno}

Cada párrafo, prioridad, recomendación, acción o alerta debe incluir datos concretos del checklist.
Si un dato no está en el contexto, escribe "sin dato de [campo]" en lugar de inventar o generalizar.
"""


def _extraer_datos_personalizacion_recomendaciones(contexto: Dict[str, Any]) -> Dict[str, Any]:
    perfil = contexto.get("perfil_estrategico") or {}
    categoria = contexto.get("categoria_creador") or {}
    partidas = contexto.get("performance_partidas") or performance_partidas_vacio()
    intereses_lista = _intereses_texto(perfil)

    return {
        "nombre_creador": _nombre_creador_contexto(contexto),
        "arquetipo": _texto_campo_perfil(perfil.get("arquetipo_valor")),
        "intereses_lista": intereses_lista,
        "intereses": ", ".join(intereses_lista) if intereses_lista else None,
        "horario": _texto_campo_perfil(perfil.get("horario_preferido")),
        "categoria_nombre": categoria.get("nombre"),
        "meta_diamantes": categoria.get("meta_diamantes_objetivo"),
        "partidas": partidas.get("partidas"),
        "pct_diamantes_partidas": partidas.get("porcentaje_diamantes_por_partidas"),
        "diagnostico_partidas": partidas.get("diagnostico_partidas"),
        "diamantes_por_partida": partidas.get("diamantes_por_partida"),
    }


def _bloque_datos_obligatorios_recomendaciones(contexto: Dict[str, Any]) -> str:
    d = _extraer_datos_personalizacion_recomendaciones(contexto)

    def _linea(etiqueta: str, valor: Any) -> str:
        if valor is None or valor == "":
            return f"- {etiqueta}: sin dato"
        return f"- {etiqueta}: {valor}"

    return "\n".join(
        [
            "DATOS OBLIGATORIOS DEL CREADOR (debes citarlos literalmente en cada recomendacion):",
            _linea("nombre_creador", d.get("nombre_creador")),
            _linea("arquetipo_valor", d.get("arquetipo")),
            _linea("intereses", d.get("intereses")),
            _linea("horario_preferido", d.get("horario")),
            _linea("categoria_creador.nombre", d.get("categoria_nombre")),
            _linea("categoria_creador.meta_diamantes_objetivo", d.get("meta_diamantes")),
            _linea("performance_partidas.partidas", d.get("partidas")),
            _linea("performance_partidas.porcentaje_diamantes_por_partidas", d.get("pct_diamantes_partidas")),
            _linea("performance_partidas.diagnostico_partidas", d.get("diagnostico_partidas")),
        ]
    )


def _es_texto_recomendacion_generico(texto: str) -> bool:
    t = (texto or "").strip().lower()
    if not t:
        return True

    patrones_vagos = list(_FRASES_IA_PROHIBIDAS) + [
        "temas de interés",
        "temas de interes",
        "relacionados con sus arquetipos",
        "relacionados con su arquetipo",
        "relacionado con su arquetipo",
        "según su perfil",
        "segun su perfil",
        "de acuerdo a su perfil",
        "contenido acorde",
        "dinámicas acordes",
        "dinamicas acordes",
    ]
    return any(p in t for p in patrones_vagos)


def _cumple_personalizacion_minima_recomendacion(
    texto: str, datos: Dict[str, Any]
) -> bool:
    t = (texto or "").lower()
    if not t:
        return False

    arquetipo = datos.get("arquetipo")
    if arquetipo and str(arquetipo).lower() not in t:
        return False

    intereses = datos.get("intereses_lista") or []
    if intereses:
        minimo = 2 if len(intereses) >= 2 else 1
        mencionados = sum(1 for interes in intereses if interes.lower() in t)
        if mencionados < minimo:
            return False

    horario = datos.get("horario")
    if horario:
        palabras_horario = [p.strip().lower() for p in str(horario).replace(",", " ").split() if p.strip()]
        if palabras_horario and not any(p in t for p in palabras_horario if len(p) > 3):
            return False

    return True


def _limpiar_texto_generado(texto: Any) -> str:
    """
    Limpieza pequeña para textos generados por IA o fallback:
    - elimina espacios repetidos
    - corrige doble punto
    - conserva saltos de párrafo
    """
    if texto is None:
        return ""

    resultado = str(texto).strip()
    resultado = re.sub(r"[ \t]+", " ", resultado)
    resultado = re.sub(r"\s+\.", ".", resultado)
    resultado = re.sub(r"\.{2,}", ".", resultado)
    resultado = resultado.replace(" .", ".")
    return resultado.strip()


def _normalizar_categoria_recomendacion(categoria: Any) -> str:
    """
    Normaliza categorías que vienen de IA o del motor básico para generar
    fallbacks distintos y evitar recomendaciones repetidas.
    """
    cat = normalizar_lower(str(categoria or "otro")) or "otro"
    mapa = {
        "crecimiento_audiencia": "audiencia",
        "audiencia": "audiencia",
        "seguidores": "audiencia",
        "monetizacion": "monetizacion",
        "monetización": "monetizacion",
        "diamantes": "monetizacion",
        "interaccion": "interaccion",
        "interacción": "interaccion",
        "contenido": "contenido",
        "horario": "horario",
        "frecuencia": "horario",
        "duracion_live": "horario",
        "duración_live": "horario",
        "disciplina": "disciplina",
        "tecnica": "tecnica",
        "técnica": "tecnica",
        "emocional": "emocional",
        "optimizar_resultados": "monetizacion",
    }
    return mapa.get(cat, cat)


def _construir_recomendacion_personalizada_fallback(
    contexto: Dict[str, Any],
    categoria: str = "monetizacion",
    prioridad: str = "media",
) -> Dict[str, str]:
    """
    Fallback determinístico cuando OpenAI devuelve una recomendación genérica.

    Importante:
    - No repite el mismo texto para todas las categorías.
    - Usa arquetipo, intereses, horario, categoría y partidas.
    - Evita frases genéricas tipo "mejorar contenido".
    """
    datos = _extraer_datos_personalizacion_recomendaciones(contexto)

    nombre = datos.get("nombre_creador") or "el creador"
    arquetipo = datos.get("arquetipo") or "sin arquetipo definido"
    intereses_lista = datos.get("intereses_lista") or []
    intereses = datos.get("intereses") or "sin intereses definidos"
    horario = datos.get("horario") or "su franja horaria principal"
    cat = datos.get("categoria_nombre") or "Sin categoría"
    meta = datos.get("meta_diamantes")
    partidas = datos.get("partidas")
    pct_partidas = datos.get("pct_diamantes_partidas")
    diamantes_por_partida = datos.get("diamantes_por_partida")
    diag_part = datos.get("diagnostico_partidas") or "sin diagnóstico de partidas"

    interes_1 = intereses_lista[0] if len(intereses_lista) >= 1 else "su tema principal"
    interes_2 = intereses_lista[1] if len(intereses_lista) >= 2 else "otro interés del perfil"
    interes_3 = intereses_lista[2] if len(intereses_lista) >= 3 else interes_1

    meta_txt = f"{meta} diamantes" if meta is not None else "su meta de diamantes"
    partidas_txt = f"{partidas} partidas" if partidas not in (None, "") else "partidas sin dato"
    diam_partida_txt = (
        f"{diamantes_por_partida} diamantes por partida"
        if diamantes_por_partida not in (None, "")
        else "diamantes por partida sin dato"
    )
    pct_txt = (
        f"{pct_partidas}% asociado a partidas"
        if pct_partidas not in (None, "")
        else "porcentaje de partidas sin dato"
    )

    categoria_norm = _normalizar_categoria_recomendacion(categoria)

    recomendaciones_por_categoria = {
        "horario": {
            "recomendacion": (
                f"Para {nombre}, validar durante 7 días un bloque fijo de LIVE en {horario}. "
                f"Abrir cada transmisión con una dinámica {arquetipo}: reto rápido de {interes_1}, "
                f"conversación de {interes_2} y una mini batalla antes del minuto 20. "
                f"Registrar asistencia, retención y regalos por cada bloque."
            ),
            "justificacion": (
                f"{nombre} tiene horario preferido {horario}, arquetipo {arquetipo} e intereses {intereses}. "
                f"Como está en categoría {cat} con meta de {meta_txt}, primero conviene estabilizar una franja "
                f"antes de aumentar volumen. Partidas: {diag_part}."
            ),
        },
        "monetizacion": {
            "recomendacion": (
                f"Para {nombre}, estructurar 3 lives en {horario} con batallas por tramos: "
                f"primer tramo de activación, segundo tramo con reto de {interes_1}, tercer tramo mezclando "
                f"{interes_2} y cierre con meta visible de regalos para acercarse a {meta_txt}."
            ),
            "justificacion": (
                f"El arquetipo {arquetipo} favorece competencia y metas visibles. Registra {partidas_txt}, "
                f"{diam_partida_txt} y {pct_txt}. Categoría {cat}, meta {meta_txt}. "
                f"Diagnóstico de partidas: {diag_part}."
            ),
        },
        "interaccion": {
            "recomendacion": (
                f"Para {nombre}, activar competencias entre seguidores en {horario}: preguntas rápidas sobre "
                f"{interes_1}, mini retos de {interes_2}, ranking simbólico de apoyo y llamado a comentar "
                f"antes de cada partida o batalla."
            ),
            "justificacion": (
                f"Como {nombre} es {arquetipo}, la interacción debe apoyarse en reto, competencia y reconocimiento. "
                f"Sus intereses ({intereses}) permiten conversación concreta. Partidas: {diag_part}."
            ),
        },
        "contenido": {
            "recomendacion": (
                f"Para {nombre}, crear una mini parrilla de 3 lives: Live 1 enfocado en {interes_1}, "
                f"Live 2 mezclando {interes_2} con batalla, y Live 3 usando {interes_3} como tema de reto. "
                f"Cada live debe terminar con una meta pequeña de regalos o seguidores."
            ),
            "justificacion": (
                f"Los intereses reales del perfil son {intereses}. Usarlos explícitamente evita contenido genérico "
                f"y conecta el arquetipo {arquetipo} con monetización. Categoría {cat}, meta {meta_txt}."
            ),
        },
        "audiencia": {
            "recomendacion": (
                f"Para {nombre}, convertir espectadores en seguidores usando tres momentos de llamado a seguir: "
                f"antes de la primera batalla, después de un reto de {interes_1} y al cerrar un bloque de {interes_2}. "
                f"El mensaje debe conectar con su estilo {arquetipo}."
            ),
            "justificacion": (
                f"El arquetipo {arquetipo} puede atraer audiencia si el LIVE tiene ritmo competitivo. "
                f"Los intereses {intereses} hacen que el llamado a seguir sea específico. "
                f"Categoría {cat}, meta {meta_txt}."
            ),
        },
        "tecnica": {
            "recomendacion": (
                f"Para {nombre}, hacer una revisión técnica antes de los lives de {horario}: iluminación frontal, "
                f"audio claro, encuadre estable y prueba de conexión. Esto es clave si hará batallas, retos de "
                f"{interes_1} o dinámicas de {interes_2}."
            ),
            "justificacion": (
                f"La estrategia depende de energía en vivo y partidas. Si la calidad técnica falla, baja la retención "
                f"y se pierde conversión. Perfil: {arquetipo}, intereses {intereses}, categoría {cat}."
            ),
        },
        "emocional": {
            "recomendacion": (
                f"Para {nombre}, definir un reto semanal alcanzable: completar 3 lives en {horario}, cada uno con "
                f"una dinámica {arquetipo} simple basada en {interes_1} y {interes_2}. Medir cumplimiento, no perfección."
            ),
            "justificacion": (
                f"Para categoría {cat}, una meta corta y repetible ayuda a sostener disciplina y confianza. "
                f"El arquetipo {arquetipo} puede mantener motivación si el avance se mide por retos concretos."
            ),
        },
        "disciplina": {
            "recomendacion": (
                f"Para {nombre}, fijar una rutina semanal mínima: 3 lives en {horario}, preparación 20 minutos antes, "
                f"una dinámica de {interes_1} por live y cierre con compromiso para la siguiente emisión."
            ),
            "justificacion": (
                f"Categoría {cat} con meta de {meta_txt} requiere consistencia antes de escalar. "
                f"El perfil {arquetipo} funciona mejor con retos medibles y seguimiento semanal."
            ),
        },
        "otro": {
            "recomendacion": (
                f"Para {nombre}, probar esta semana 3 lives en {horario} combinando {interes_1}, {interes_2} "
                f"y una dinámica competitiva del arquetipo {arquetipo}, con una meta visible relacionada con {meta_txt}."
            ),
            "justificacion": (
                f"La recomendación usa perfil estratégico ({arquetipo}, {intereses}, {horario}), categoría {cat} "
                f"y lectura de partidas: {diag_part}."
            ),
        },
    }

    elegido = recomendaciones_por_categoria.get(
        categoria_norm,
        recomendaciones_por_categoria["otro"],
    )

    recomendacion = _limpiar_texto_generado(elegido["recomendacion"])
    justificacion = _limpiar_texto_generado(elegido["justificacion"])

    return {
        "categoria": categoria_norm,
        "prioridad": prioridad,
        "recomendacion": recomendacion,
        "justificacion": justificacion,
    }


def _normalizar_resultado_recomendaciones_ia(
    contexto: Dict[str, Any],
    resultado: Any,
    max_recomendaciones: int,
) -> Dict[str, Any]:
    """
    Valida recomendaciones IA y reemplaza solo las que sean genéricas.
    Además:
    - evita duplicados exactos
    - evita que todas las recomendaciones terminen iguales
    - aplica fallback diferente según categoría
    """
    salida: Dict[str, Any] = resultado if isinstance(resultado, dict) else {}
    recs_raw = salida.get("recomendaciones")
    if not isinstance(recs_raw, list):
        recs_raw = []

    datos = _extraer_datos_personalizacion_recomendaciones(contexto)
    normalizadas: List[Dict[str, Any]] = []
    firmas_usadas: set = set()
    categorias_usadas: set = set()

    def _agregar_unica(rec: Dict[str, Any]) -> None:
        if not isinstance(rec, dict):
            return

        categoria_norm = _normalizar_categoria_recomendacion(rec.get("categoria") or "otro")
        prioridad_norm = validar_valor_en_set(
            rec.get("prioridad") or "media",
            PRIORIDADES_VALIDAS,
            "prioridad",
        ) or "media"

        recomendacion = _limpiar_texto_generado(rec.get("recomendacion"))
        justificacion = _limpiar_texto_generado(rec.get("justificacion") or recomendacion)

        if not recomendacion:
            return

        firma = re.sub(r"\W+", "", recomendacion.lower())[:180]
        if firma in firmas_usadas:
            return

        firmas_usadas.add(firma)
        categorias_usadas.add(categoria_norm)
        normalizadas.append({
            "categoria": categoria_norm,
            "prioridad": prioridad_norm,
            "recomendacion": recomendacion,
            "justificacion": justificacion,
        })

    for rec in recs_raw[:max_recomendaciones]:
        if not isinstance(rec, dict):
            continue

        categoria = _normalizar_categoria_recomendacion(rec.get("categoria") or "otro")
        prioridad = rec.get("prioridad") or "media"
        texto_rec = _limpiar_texto_generado(rec.get("recomendacion"))
        texto_just = _limpiar_texto_generado(rec.get("justificacion"))
        texto_union = f"{texto_rec} {texto_just}"

        debe_usar_fallback = (
            _es_texto_recomendacion_generico(texto_rec)
            or _es_texto_recomendacion_generico(texto_just)
            or not _cumple_personalizacion_minima_recomendacion(texto_union, datos)
        )

        if debe_usar_fallback:
            rec_normalizada = _construir_recomendacion_personalizada_fallback(
                contexto, categoria, str(prioridad)
            )
        else:
            rec_normalizada = {
                "categoria": categoria,
                "prioridad": prioridad,
                "recomendacion": texto_rec,
                "justificacion": texto_just or texto_rec,
            }

        _agregar_unica(rec_normalizada)

    categorias_preferidas = [
        "monetizacion",
        "interaccion",
        "contenido",
        "horario",
        "audiencia",
        "disciplina",
        "tecnica",
        "emocional",
    ]

    for categoria_objetivo in categorias_preferidas:
        if len(normalizadas) >= max_recomendaciones:
            break
        if categoria_objetivo in categorias_usadas:
            continue

        rec_fallback = _construir_recomendacion_personalizada_fallback(
            contexto,
            categoria_objetivo,
            "media",
        )
        _agregar_unica(rec_fallback)

    if not normalizadas:
        for basica in generar_recomendaciones_basicas(contexto)[:max_recomendaciones]:
            categoria = _normalizar_categoria_recomendacion(basica.get("categoria") or "otro")
            prioridad = basica.get("prioridad") or "media"
            texto_b = _limpiar_texto_generado(basica.get("recomendacion"))
            just_b = _limpiar_texto_generado(basica.get("justificacion"))

            if _es_texto_recomendacion_generico(texto_b) or not _cumple_personalizacion_minima_recomendacion(
                f"{texto_b} {just_b}", datos
            ):
                rec = _construir_recomendacion_personalizada_fallback(
                    contexto,
                    categoria,
                    str(prioridad),
                )
            else:
                rec = {
                    "categoria": categoria,
                    "prioridad": prioridad,
                    "recomendacion": texto_b,
                    "justificacion": just_b or texto_b,
                }
            _agregar_unica(rec)

    salida["recomendaciones"] = normalizadas[:max_recomendaciones]
    return salida


def prompt_diagnostico_performance(contexto: Dict[str, Any], instrucciones_extra: Optional[str] = None) -> str:
    extra = f"\nInstrucciones adicionales del manager:\n{instrucciones_extra}\n" if instrucciones_extra else ""
    reglas = _reglas_personalizacion_ia_obligatorias(contexto)

    return f"""
Eres un director de performance para una agencia de TikTok LIVE en LATAM.
Analiza el siguiente contexto del creador y responde con JSON válido.

Contexto:
{contexto_para_prompt(contexto)}

{reglas}

{extra}

En diagnostico, prioridades, lectura_manager y mensaje_para_creador:
- Nombra arquetipo, intereses (mínimo 2 si existen), horario, categoría/meta y lectura de partidas.
- No uses consejos que podrían aplicar a cualquier creador.

Devuelve exactamente este JSON:
{{
  "diagnostico": "texto breve de máximo 900 caracteres",
  "estado_general": "excelente|alto|medio|bajo|critico",
  "riesgo_abandono": "bajo|medio|alto",
  "prioridades": [
    "prioridad 1",
    "prioridad 2",
    "prioridad 3"
  ],
  "lectura_manager": "explicación ejecutiva para el manager, máximo 900 caracteres",
  "mensaje_para_creador": "mensaje motivador y accionable para el creador, máximo 700 caracteres"
}}

No uses markdown. No incluyas texto fuera del JSON.
"""


def prompt_recomendaciones_manager(contexto: Dict[str, Any], max_recomendaciones: int, instrucciones_extra: Optional[str] = None) -> str:
    extra = f"\nInstrucciones adicionales:\n{instrucciones_extra}\n" if instrucciones_extra else ""
    reglas = _reglas_personalizacion_ia_obligatorias(contexto)
    datos_obligatorios = _bloque_datos_obligatorios_recomendaciones(contexto)

    return f"""
Eres un coach senior de creadores TikTok LIVE y asesor de managers de agencia.
Tu única tarea: generar recomendaciones operativas ULTRA ESPECÍFICAS para el creador del contexto.

{datos_obligatorios}

{reglas}

Contexto completo (JSON):
{contexto_para_prompt(contexto)}

{extra}

FORMATO OBLIGATORIO de cada "recomendacion" (texto único, sin frases vagas):
1) Nombre del creador (si existe).
2) Arquetipo por nombre exacto (si existe en datos obligatorios).
3) Al menos 2 intereses literales separados por coma (si hay 2+ en datos obligatorios).
4) Bloque horario concreto según horario_preferido (si existe).
5) Decisión sobre partidas: ¿oportunidad, fuente principal o baja conversión? Cita diagnostico_partidas o métricas.
6) Acción ejecutable esta semana (número de lives, dinámica, meta de diamantes/regalos).

La "justificacion" debe citar métricas del JSON (metas, reporte, performance_partidas) y el perfil citado arriba.

Devuelve JSON válido con este formato:
{{
  "recomendaciones": [
    {{
      "categoria": "monetizacion|disciplina|horario|contenido|interaccion|audiencia|tecnica|emocional|otro",
      "prioridad": "baja|media|alta|critica",
      "recomendacion": "acción concreta que debe revisar el manager",
      "justificacion": "por qué se recomienda según métricas o perfil"
    }}
  ]
}}

Reglas:
- Exactamente entre 1 y {max_recomendaciones} recomendaciones.
- No repitas recomendaciones ya existentes en contexto.recomendaciones.
- Si falta un dato obligatorio, escribe "sin dato de X" en esa recomendación; no inventes ni generalices.
- No uses markdown.
- No incluyas texto fuera del JSON.
"""


def prompt_acciones_manager(contexto: Dict[str, Any], max_acciones: int, instrucciones_extra: Optional[str] = None) -> str:
    extra = f"\nInstrucciones adicionales:\n{instrucciones_extra}\n" if instrucciones_extra else ""
    reglas = _reglas_personalizacion_ia_obligatorias(contexto)

    tipos = ", ".join(sorted(TIPOS_ACCION_SUGERIDOS))

    return f"""
Eres un coordinador operativo de managers para una agencia TikTok LIVE.
Genera acciones concretas para registrar en el seguimiento del creador.

Contexto:
{contexto_para_prompt(contexto)}

Tipos de acción sugeridos:
{tipos}

{reglas}

{extra}

Cada titulo y descripcion debe incluir: nombre del creador (si existe), arquetipo por nombre,
al menos 2 intereses literales (si existen), horario concreto (si existe), categoría/meta
y decisión sobre partidas (oportunidad vs fuente principal de diamantes) según performance_partidas.

Devuelve JSON válido:
{{
  "acciones": [
    {{
      "tipo_accion": "uno de los tipos sugeridos o uno equivalente en MAYÚSCULAS",
      "titulo": "título corto",
      "descripcion": "descripción concreta",
      "prioridad": "baja|media|alta|critica",
      "estado": "pendiente"
    }}
  ]
}}

Reglas:
- Máximo {max_acciones} acciones.
- Deben ser acciones que un manager pueda ejecutar o revisar en la próxima semana.
- No uses markdown.
- No incluyas texto fuera del JSON.
"""


def prompt_alertas_score_ia(contexto: Dict[str, Any], instrucciones_extra: Optional[str] = None) -> str:
    extra = f"\nInstrucciones adicionales:\n{instrucciones_extra}\n" if instrucciones_extra else ""
    reglas = _reglas_personalizacion_ia_obligatorias(contexto)

    return f"""
Eres un analista de riesgo y performance de creadores TikTok LIVE.
Evalúa el contexto y genera un score, alertas y explicación operativa.

Contexto:
{contexto_para_prompt(contexto)}

{reglas}

{extra}

En observacion_ia y en cada alerta.descripcion:
- Fundamenta con arquetipo, intereses (≥2 si existen), horario, categoría/meta y lectura de partidas.
- El score debe reflejar si las partidas son palanca principal, oportunidad perdida o riesgo de dependencia.

Devuelve JSON válido:
{{
  "score": {{
    "score_general": 0,
    "nivel_rendimiento": "excelente|alto|medio|bajo|critico",
    "riesgo_abandono": "bajo|medio|alto",
    "probabilidad_crecimiento": 0,
    "consistencia_score": 0,
    "monetizacion_score": 0,
    "engagement_score": 0,
    "observacion_ia": "observación breve"
  }},
  "alertas": [
    {{
      "tipo_alerta": "tipo corto en snake_case",
      "nivel_alerta": "baja|media|alta|critica",
      "titulo": "título corto",
      "descripcion": "descripción concreta"
    }}
  ]
}}

Reglas:
- Los scores van de 0 a 100.
- No uses markdown.
- No incluyas texto fuera del JSON.
"""


def prompt_generar_seguimiento(
    contexto: Dict[str, Any],
    observaciones_manager: str,
    resumen_compromisos: str,
    instrucciones_extra: Optional[str] = None,
) -> str:
    extra = f"\nInstrucciones adicionales:\n{instrucciones_extra}\n" if instrucciones_extra else ""

    reglas = _reglas_personalizacion_ia_obligatorias(contexto)

    return f"""
Eres un coach de creadores de contenido en vivo para TikTok LIVE.
Ayuda al manager a redactar un seguimiento profesional.

Contexto del creador:
{contexto_para_prompt(contexto)}

Observaciones iniciales del manager:
{observaciones_manager or ""}

Compromisos iniciales:
{resumen_compromisos or ""}

{reglas}

{extra}

Mejora observaciones_manager y resumen_compromisos integrando datos concretos del contexto:
arquetipo por nombre, ≥2 intereses literales, horario, categoría/meta y plan sobre partidas.
Conserva la intención del manager; no sustituyas por texto genérico.

Devuelve JSON válido:
{{
  "observaciones_manager": "texto mejorado para guardar en observaciones_manager, máximo 1200 caracteres",
  "resumen_compromisos": "texto mejorado para guardar en resumen_compromisos, máximo 1200 caracteres",
  "resumen_corto": "párrafo de máximo 120 palabras para mostrar rápidamente"
}}

Reglas de formato (obligatorias):
- Separa párrafos con una línea en blanco: usa el carácter de salto de línea dos veces seguidas (\\n\\n) entre párrafos.
- observaciones_manager: 2 a 4 párrafos breves (contexto actual, diagnóstico con datos del checklist, plan concreto).
- resumen_compromisos: un párrafo por compromiso o acción acordada; si son varios ítems, un párrafo por ítem.
- resumen_corto: un solo párrafo, sin líneas en blanco internas.

Reglas:
- Mantén tono profesional y humano.
- No inventes situaciones personales no presentes en el contexto.
- No uses markdown.
- No incluyas texto fuera del JSON.
"""


# =========================================================
# ENDPOINTS — IA
# =========================================================

def _log_ia_debug_contexto(endpoint: str, creador_id: int, contexto: Dict[str, Any]) -> None:
    """Logs temporales de debug: verificar datos de perfil/categoría/partidas antes del prompt IA."""
    if not DEBUG_PERFORMANCE_IA:
        return

    print(f"🧠 [IA DEBUG] endpoint: {endpoint}", flush=True)
    print(f"🧠 [IA DEBUG] creador_id: {creador_id}", flush=True)
    print(f"🧠 [IA DEBUG] perfil_estrategico: {contexto.get('perfil_estrategico')}", flush=True)
    print(f"🧠 [IA DEBUG] categoria_creador: {contexto.get('categoria_creador')}", flush=True)
    print(f"🧠 [IA DEBUG] performance_partidas: {contexto.get('performance_partidas')}", flush=True)
    print(
        f"🧠 [IA DEBUG] tiene_perfil_estrategico: {bool(contexto.get('perfil_estrategico'))}",
        flush=True,
    )
    print(
        f"🧠 [IA DEBUG] tiene_categoria_creador: {bool(contexto.get('categoria_creador'))}",
        flush=True,
    )
    print(
        f"🧠 [IA DEBUG] tiene_performance_partidas: {bool(contexto.get('performance_partidas'))}",
        flush=True,
    )

    perfil = contexto.get("perfil_estrategico") or {}
    print(f"🧠 [IA DEBUG] arquetipo: {perfil.get('arquetipo_valor')}", flush=True)
    print(f"🧠 [IA DEBUG] intereses: {perfil.get('intereses')}", flush=True)
    print(f"🧠 [IA DEBUG] horario: {perfil.get('horario_preferido')}", flush=True)

    categoria = contexto.get("categoria_creador") or {}
    print(f"🧠 [IA DEBUG] categoria: {categoria.get('nombre')}", flush=True)
    print(
        f"🧠 [IA DEBUG] meta_categoria_diamantes: {categoria.get('meta_diamantes_objetivo')}",
        flush=True,
    )

    partidas = contexto.get("performance_partidas") or {}
    print(f"🧠 [IA DEBUG] partidas: {partidas.get('partidas')}", flush=True)
    print(
        f"🧠 [IA DEBUG] diamantes_de_partidas: {partidas.get('diamantes_de_partidas')}",
        flush=True,
    )
    print(
        "🧠 [IA DEBUG] porcentaje_diamantes_por_partidas: "
        f"{partidas.get('porcentaje_diamantes_por_partidas')}",
        flush=True,
    )
    print(
        f"🧠 [IA DEBUG] diagnostico_partidas: {partidas.get('diagnostico_partidas')}",
        flush=True,
    )


@router.post("/api/creadores/performance/{creador_id}/ia/diagnostico")
def generar_diagnostico_ia(
    creador_id: int,
    data: IARequest = IARequest(),
):
    contexto = obtener_contexto_ia_manager(creador_id, id_reporte=data.id_reporte)
    _log_ia_debug_contexto("diagnostico", creador_id, contexto)
    prompt = prompt_diagnostico_performance(contexto, data.instrucciones_extra)

    resultado = openai_json_completion(
        prompt,
        temperature=0.35,
        system=(
            "Eres experto en performance, coaching y crecimiento de creadores TikTok LIVE. "
            "Responde únicamente JSON válido."
        ),
    )

    return {
        "ok": True,
        "creador_id": creador_id,
        "resultado": resultado,
    }


@router.post("/api/creadores/performance/{creador_id}/ia/generar-seguimiento")
def generar_seguimiento_ia(
    creador_id: int,
    data: GenerarSeguimientoIARequest,
):
    contexto = obtener_contexto_ia_manager(creador_id)
    _log_ia_debug_contexto("generar_seguimiento", creador_id, contexto)
    prompt = prompt_generar_seguimiento(
        contexto,
        data.observaciones_manager or "",
        data.resumen_compromisos or "",
        data.instrucciones_extra,
    )

    resultado = openai_json_completion(
        prompt,
        temperature=0.55,
        system=(
            "Eres asistente de managers de una agencia TikTok LIVE. "
            "Redacta seguimientos accionables en español. "
            "Separa párrafos con doble salto de línea (\\n\\n). "
            "Responde únicamente JSON válido."
        ),
    )

    if isinstance(resultado, dict):
        for campo in ("observaciones_manager", "resumen_compromisos", "resumen_corto"):
            if resultado.get(campo):
                resultado[campo] = normalizar_texto_parrafos(resultado[campo])

    return {
        "ok": True,
        "creador_id": creador_id,
        "resultado": resultado,
    }


@router.post("/api/creadores/performance/{creador_id}/ia/recomendaciones")
def generar_recomendaciones_ia(
    creador_id: int,
    data: GenerarRecomendacionesIARequest = GenerarRecomendacionesIARequest(),
):
    contexto = obtener_contexto_ia_manager(creador_id)
    _log_ia_debug_contexto("recomendaciones", creador_id, contexto)
    prompt = prompt_recomendaciones_manager(
        contexto,
        data.max_recomendaciones,
        data.instrucciones_extra,
    )

    resultado = openai_json_completion(
        prompt,
        temperature=0.25,
        system=(
            "Eres experto en coaching operativo para managers de creadores TikTok LIVE. "
            "Cada recomendacion debe nombrar arquetipo, intereses concretos (minimo 2 si existen), "
            "horario, categoria/meta y analisis de partidas del contexto. "
            "Prohibido texto generico reutilizable entre creadores. Responde unicamente JSON valido."
        ),
    )

    resultado = _normalizar_resultado_recomendaciones_ia(
        contexto, resultado, data.max_recomendaciones
    )
    recomendaciones = resultado.get("recomendaciones", []) if isinstance(resultado, dict) else []

    guardadas = []
    if data.guardar:
        reporte = contexto.get("ultimo_reporte") or {}
        for rec in recomendaciones:
            if not isinstance(rec, dict):
                continue
            payload = {
                "creador_id": creador_id,
                "id_reporte": reporte.get("id_reporte"),
                "categoria": rec.get("categoria"),
                "prioridad": rec.get("prioridad") or "media",
                "recomendacion": rec.get("recomendacion"),
                "justificacion": rec.get("justificacion"),
                "aplicada": False,
            }
            if payload["recomendacion"]:
                guardadas.append(insertar_recomendacion(payload))

    return {
        "ok": True,
        "creador_id": creador_id,
        "guardado": data.guardar,
        "resultado": resultado,
        "guardadas": guardadas,
    }


@router.post("/api/creadores/performance/{creador_id}/ia/acciones")
def generar_acciones_ia(
    creador_id: int,
    data: GenerarAccionesIARequest = GenerarAccionesIARequest(),
):
    contexto = obtener_contexto_ia_manager(creador_id)
    _log_ia_debug_contexto("acciones", creador_id, contexto)
    prompt = prompt_acciones_manager(
        contexto,
        data.max_acciones,
        data.instrucciones_extra,
    )

    resultado = openai_json_completion(
        prompt,
        temperature=0.35,
        system=(
            "Eres coordinador operativo de managers para agencia TikTok LIVE. "
            "Responde únicamente JSON válido."
        ),
    )

    acciones = resultado.get("acciones", []) if isinstance(resultado, dict) else []
    guardadas = []

    if data.guardar:
        seguimiento_id = data.seguimiento_id

        if not seguimiento_id:
            seguimiento = crear_seguimiento_performance(
                SeguimientoPerformanceCreate(
                    creador_id=creador_id,
                    fecha_seguimiento=date.today(),
                    observaciones_manager="Seguimiento generado con apoyo de IA.",
                    resumen_compromisos="Acciones sugeridas por IA para revisión del manager.",
                )
            )
            seguimiento_id = seguimiento["id"]

        seguimiento = fetch_one(
            """
            SELECT *
            FROM creadores_performance_seguimiento
            WHERE id = %s
              AND creador_id = %s
            """,
            (seguimiento_id, creador_id),
        )

        if not seguimiento:
            raise HTTPException(
                status_code=404,
                detail="seguimiento_id no existe o no pertenece al creador",
            )

        for accion in acciones:
            if not isinstance(accion, dict):
                continue

            payload = {
                "tipo_accion": accion.get("tipo_accion") or "META_SEMANAL",
                "titulo": accion.get("titulo"),
                "descripcion": accion.get("descripcion"),
                "prioridad": accion.get("prioridad") or "media",
                "estado": accion.get("estado") or "pendiente",
                "fecha_compromiso": None,
                "creado_por": seguimiento.get("manager_id"),
            }
            guardadas.append(insertar_accion(seguimiento_id, payload))

    return {
        "ok": True,
        "creador_id": creador_id,
        "guardado": data.guardar,
        "resultado": resultado,
        "guardadas": guardadas,
    }


@router.post("/api/creadores/performance/{creador_id}/ia/alertas-score")
def generar_alertas_score_ia(
    creador_id: int,
    data: GenerarAlertasScoreIARequest = GenerarAlertasScoreIARequest(),
):
    contexto = obtener_contexto_ia_manager(creador_id)
    prompt = prompt_alertas_score_ia(contexto, data.instrucciones_extra)

    resultado = openai_json_completion(
        prompt,
        temperature=0.25,
        system=(
            "Eres analista de datos, riesgo y performance de creadores TikTok LIVE. "
            "Responde únicamente JSON válido."
        ),
    )

    reporte = contexto.get("ultimo_reporte") or {}
    guardado_score = None
    guardadas_alertas = []

    if data.guardar and isinstance(resultado, dict):
        score = resultado.get("score") or {}
        if isinstance(score, dict):
            payload_score = {
                "creador_id": creador_id,
                "id_reporte": reporte.get("id_reporte"),
                "score_general": score.get("score_general"),
                "nivel_rendimiento": score.get("nivel_rendimiento"),
                "riesgo_abandono": score.get("riesgo_abandono"),
                "probabilidad_crecimiento": score.get("probabilidad_crecimiento"),
                "consistencia_score": score.get("consistencia_score"),
                "monetizacion_score": score.get("monetizacion_score"),
                "engagement_score": score.get("engagement_score"),
                "observacion_ia": score.get("observacion_ia"),
            }
            guardado_score = insertar_score(payload_score)

        alertas = resultado.get("alertas") or []
        if isinstance(alertas, list):
            for alerta in alertas:
                if not isinstance(alerta, dict):
                    continue
                payload_alerta = {
                    "creador_id": creador_id,
                    "id_reporte": reporte.get("id_reporte"),
                    "tipo_alerta": alerta.get("tipo_alerta"),
                    "nivel_alerta": alerta.get("nivel_alerta") or "media",
                    "titulo": alerta.get("titulo"),
                    "descripcion": alerta.get("descripcion"),
                    "origen": "ia",
                    "estado": "activa",
                }
                guardadas_alertas.append(insertar_alerta(payload_alerta))

    return {
        "ok": True,
        "creador_id": creador_id,
        "guardado": data.guardar,
        "resultado": resultado,
        "score_guardado": guardado_score,
        "alertas_guardadas": guardadas_alertas,
    }


@router.post("/api/creadores/performance/{creador_id}/ia/analisis-completo")
def generar_analisis_completo_ia(
    creador_id: int,
    data: GenerarAlertasScoreIARequest = GenerarAlertasScoreIARequest(),
):
    """
    Endpoint cómodo para el frontend:
    1) Genera diagnóstico IA.
    2) Genera recomendaciones IA.
    3) Genera score + alertas IA.
    Puede guardar recomendaciones, score y alertas.
    """
    contexto = obtener_contexto_ia_manager(creador_id)
    _log_ia_debug_contexto("analisis_completo", creador_id, contexto)

    diagnostico = openai_json_completion(
        prompt_diagnostico_performance(contexto, data.instrucciones_extra),
        temperature=0.35,
        system="Responde únicamente JSON válido en español.",
    )

    recomendaciones_result = openai_json_completion(
        prompt_recomendaciones_manager(contexto, 5, data.instrucciones_extra),
        temperature=0.35,
        system="Responde únicamente JSON válido en español.",
    )
    recomendaciones_result = _normalizar_resultado_recomendaciones_ia(
        contexto,
        recomendaciones_result,
        5,
    )

    alertas_score_result = openai_json_completion(
        prompt_alertas_score_ia(contexto, data.instrucciones_extra),
        temperature=0.25,
        system="Responde únicamente JSON válido en español.",
    )

    reporte = contexto.get("ultimo_reporte") or {}
    guardado: Dict[str, Any] = {
        "score": None,
        "alertas": [],
        "recomendaciones": [],
    }

    if data.guardar:
        score = alertas_score_result.get("score", {}) if isinstance(alertas_score_result, dict) else {}
        if isinstance(score, dict):
            guardado["score"] = insertar_score({
                "creador_id": creador_id,
                "id_reporte": reporte.get("id_reporte"),
                "score_general": score.get("score_general"),
                "nivel_rendimiento": score.get("nivel_rendimiento"),
                "riesgo_abandono": score.get("riesgo_abandono"),
                "probabilidad_crecimiento": score.get("probabilidad_crecimiento"),
                "consistencia_score": score.get("consistencia_score"),
                "monetizacion_score": score.get("monetizacion_score"),
                "engagement_score": score.get("engagement_score"),
                "observacion_ia": score.get("observacion_ia"),
            })

        alertas = alertas_score_result.get("alertas", []) if isinstance(alertas_score_result, dict) else []
        if isinstance(alertas, list):
            for alerta in alertas:
                if not isinstance(alerta, dict):
                    continue
                guardado["alertas"].append(insertar_alerta({
                    "creador_id": creador_id,
                    "id_reporte": reporte.get("id_reporte"),
                    "tipo_alerta": alerta.get("tipo_alerta"),
                    "nivel_alerta": alerta.get("nivel_alerta") or "media",
                    "titulo": alerta.get("titulo"),
                    "descripcion": alerta.get("descripcion"),
                    "origen": "ia",
                    "estado": "activa",
                }))

        recomendaciones = recomendaciones_result.get("recomendaciones", []) if isinstance(recomendaciones_result, dict) else []
        if isinstance(recomendaciones, list):
            for rec in recomendaciones:
                if not isinstance(rec, dict):
                    continue
                if not rec.get("recomendacion"):
                    continue
                guardado["recomendaciones"].append(insertar_recomendacion({
                    "creador_id": creador_id,
                    "id_reporte": reporte.get("id_reporte"),
                    "categoria": rec.get("categoria"),
                    "prioridad": rec.get("prioridad") or "media",
                    "recomendacion": rec.get("recomendacion"),
                    "justificacion": rec.get("justificacion"),
                    "aplicada": False,
                }))

    return {
        "ok": True,
        "creador_id": creador_id,
        "guardado": data.guardar,
        "diagnostico": diagnostico,
        "recomendaciones": recomendaciones_result,
        "alertas_score": alertas_score_result,
        "guardado_detalle": guardado,
    }


# =========================================================
# ENDPOINTS — RANKINGS / LISTADOS PARA MANAGER
# =========================================================

@router.get("/api/creadores/performance/ranking/score")
def ranking_score_performance(
    limit: int = Query(default=50, ge=1, le=500),
):
    """
    Ranking usando el último score por creador.
    """
    return fetch_all(
        """
        SELECT *
        FROM (
            SELECT DISTINCT ON (s.creador_id)
                s.*,
                c.nombre,
                c.usuario_tiktok,
                cd.manager_id,
                au.nombre_completo AS manager_nombre
            FROM creadores_performance_score s
            INNER JOIN creadores c ON s.creador_id = c.id
            LEFT JOIN creadores_detalle cd ON c.id = cd.creador_id
            LEFT JOIN administradores au ON cd.manager_id = au.id
            ORDER BY s.creador_id, s.created_at DESC, s.id DESC
        ) ultimos
        ORDER BY ultimos.score_general DESC NULLS LAST, ultimos.creador_id ASC
        LIMIT %s
        """,
        (limit,),
    )


@router.get("/api/creadores/performance/riesgo")
def listar_creadores_en_riesgo(
    riesgo: Optional[str] = Query(default="alto"),
    limit: int = Query(default=50, ge=1, le=500),
):
    riesgo_norm = normalizar_lower(riesgo)

    return fetch_all(
        """
        SELECT *
        FROM (
            SELECT DISTINCT ON (s.creador_id)
                s.*,
                c.nombre,
                c.usuario_tiktok,
                cd.manager_id,
                au.nombre_completo AS manager_nombre
            FROM creadores_performance_score s
            INNER JOIN creadores c ON s.creador_id = c.id
            LEFT JOIN creadores_detalle cd ON c.id = cd.creador_id
            LEFT JOIN administradores au ON cd.manager_id = au.id
            ORDER BY s.creador_id, s.created_at DESC, s.id DESC
        ) ultimos
        WHERE riesgo_abandono = %s
        ORDER BY score_general ASC NULLS FIRST
        LIMIT %s
        """,
        (riesgo_norm, limit),
    )


@router.get("/api/creadores/performance/manager/{manager_id}/resumen")
def resumen_performance_manager(
    manager_id: int,
    limit: int = Query(default=100, ge=1, le=500),
):
    """
    Resumen operativo para un manager:
    - creadores asignados
    - último score
    - acciones abiertas
    - alertas activas
    """
    creadores = fetch_all(
        """
        SELECT
            c.id AS creador_id,
            c.nombre,
            c.usuario_tiktok,
            c.foto,
            c.categoria_id,
            COALESCE(cat.nombre, 'Sin categoría') AS categoria,
            cd.manager_id,
            s.score_general,
            s.nivel_rendimiento,
            s.riesgo_abandono,
            s.probabilidad_crecimiento,
            s.created_at AS score_created_at,
            COALESCE(alertas.alertas_activas, 0) AS alertas_activas,
            COALESCE(acciones.acciones_abiertas, 0) AS acciones_abiertas
        FROM creadores c
        LEFT JOIN creadores_categoria cat ON cat.id = c.categoria_id
        INNER JOIN creadores_detalle cd ON c.id = cd.creador_id
        LEFT JOIN LATERAL (
            SELECT *
            FROM creadores_performance_score s
            WHERE s.creador_id = c.id
            ORDER BY s.created_at DESC, s.id DESC
            LIMIT 1
        ) s ON true
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS alertas_activas
            FROM creadores_performance_alertas a
            WHERE a.creador_id = c.id
              AND COALESCE(a.estado, 'activa') IN ('activa', 'pendiente')
        ) alertas ON true
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS acciones_abiertas
            FROM creadores_performance_acciones a
            INNER JOIN creadores_performance_seguimiento seg
                ON a.seguimiento_id = seg.id
            WHERE seg.creador_id = c.id
              AND COALESCE(a.estado, 'pendiente') NOT IN ('cumplido', 'cancelado')
        ) acciones ON true
        WHERE cd.manager_id = %s
        ORDER BY
            CASE s.riesgo_abandono
                WHEN 'alto' THEN 1
                WHEN 'medio' THEN 2
                WHEN 'bajo' THEN 3
                ELSE 4
            END,
            s.score_general ASC NULLS LAST,
            c.nombre ASC
        LIMIT %s
        """,
        (manager_id, limit),
    )

    return {
        "ok": True,
        "manager_id": manager_id,
        "creadores": creadores,
    }


# =========================================================
# ENDPOINTS — CATÁLOGOS FRONTEND
# =========================================================

@router.get("/api/creadores/performance/catalogos")
def catalogos_performance():
    return {
        "ok": True,
        "estados_accion": sorted(ESTADOS_ACCION_VALIDOS),
        "prioridades": sorted(PRIORIDADES_VALIDAS),
        "estados_alerta": sorted(ESTADOS_ALERTA_VALIDOS),
        "niveles_alerta": sorted(NIVELES_ALERTA_VALIDOS),
        "tipos_accion_sugeridos": sorted(TIPOS_ACCION_SUGERIDOS),
        "niveles_rendimiento": sorted(NIVELES_RENDIMIENTO),
    }


# =========================================================
# ENDPOINTS — HEALTHCHECK
# =========================================================

@router.get("/api/creadores/performance/health")
def health_performance():
    """
    Healthcheck básico del módulo.
    """
    try:
        db_ok = fetch_one("SELECT 1 AS ok")
        return {
            "ok": True,
            "modulo": "creadores_performance",
            "db": db_ok,
            "openai": {
                "api_key_configurada": openai_api_key_configurada(),
                "habilitado_agencia": openai_habilitado_en_agencia(),
                "puede_usarse": openai_disponible(),
                "modelo": OPENAI_MODEL_DEFAULT,
            },
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error en healthcheck performance: {e}",
        )
