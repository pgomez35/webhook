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
    ultimo_reporte: Optional[Dict[str, Any]] = None
    metas: Optional[Dict[str, Any]] = None
    insights: Optional[Dict[str, Any]] = None
    score: Optional[Dict[str, Any]] = None
    alertas: List[Dict[str, Any]] = []
    recomendaciones: List[Dict[str, Any]] = []
    seguimientos: List[Dict[str, Any]] = []
    acciones_abiertas: List[Dict[str, Any]] = []
    perfil_respuestas: List[Dict[str, Any]] = []


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
        response = client.chat.completions.create(
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
    return fetch_all(
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
            r.created_at,
            r.updated_at
        FROM creadores_perfil_respuesta r
        INNER JOIN creadores_perfil_variable v ON r.variable_id = v.id
        LEFT JOIN creadores_perfil_categoria c ON v.categoria_id = c.id
        WHERE r.creador_id = %s
        ORDER BY c.orden ASC NULLS LAST, v.orden ASC NULLS LAST, v.id ASC
        """,
        (creador_id,),
    )


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

    contexto = {
        "creador": creador,
        "detalle": detalle,
        "ultimo_reporte": ultimo_reporte,
        "metas": metas,
        "insights": insights,
        "score": obtener_score_actual(creador_id),
        "alertas": obtener_alertas_activas(creador_id),
        "recomendaciones": obtener_recomendaciones_pendientes(creador_id),
        "seguimientos": obtener_ultimos_seguimientos(creador_id),
        "acciones_abiertas": obtener_acciones_abiertas(creador_id),
        "perfil_respuestas": obtener_perfil_respuestas(creador_id) if incluir_perfil else [],
    }

    return contexto


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
    return {
        "ok": True,
        "creador_id": creador_id,
        "perfil_respuestas": obtener_perfil_respuestas(creador_id),
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

    return execute_returning(
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
            "observaciones_manager": seg.observaciones_manager or "",
            "resumen_compromisos": seg.resumen_compromisos or "",
        },
    )


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
    return fetch_all(
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
    return seguimiento


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

    return update_row_dynamic(
        table_name="creadores_performance_seguimiento",
        id_column="id",
        id_value=seguimiento_id,
        data=model_to_dict(data, exclude_unset=True),
        allowed_fields={
            "fecha_seguimiento",
            "observaciones_manager",
            "resumen_compromisos",
        },
    )


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

def prompt_diagnostico_performance(contexto: Dict[str, Any], instrucciones_extra: Optional[str] = None) -> str:
    extra = f"\nInstrucciones adicionales del manager:\n{instrucciones_extra}\n" if instrucciones_extra else ""

    return f"""
Eres un director de performance para una agencia de TikTok LIVE en LATAM.
Analiza el siguiente contexto del creador y responde con JSON válido.

Contexto:
{contexto_para_prompt(contexto)}

{extra}

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

    return f"""
Eres un coach senior de creadores TikTok LIVE y asesor de managers de agencia.
Genera recomendaciones operativas para que el manager mejore el performance del creador.

Contexto:
{contexto_para_prompt(contexto)}

{extra}

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
- Máximo {max_recomendaciones} recomendaciones.
- No repitas recomendaciones ya existentes si aparecen en el contexto.
- Sé concreto, no genérico.
- No uses markdown.
- No incluyas texto fuera del JSON.
"""


def prompt_acciones_manager(contexto: Dict[str, Any], max_acciones: int, instrucciones_extra: Optional[str] = None) -> str:
    extra = f"\nInstrucciones adicionales:\n{instrucciones_extra}\n" if instrucciones_extra else ""

    tipos = ", ".join(sorted(TIPOS_ACCION_SUGERIDOS))

    return f"""
Eres un coordinador operativo de managers para una agencia TikTok LIVE.
Genera acciones concretas para registrar en el seguimiento del creador.

Contexto:
{contexto_para_prompt(contexto)}

Tipos de acción sugeridos:
{tipos}

{extra}

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
- Deben ser acciones que un manager pueda ejecutar o revisar.
- No uses markdown.
- No incluyas texto fuera del JSON.
"""


def prompt_alertas_score_ia(contexto: Dict[str, Any], instrucciones_extra: Optional[str] = None) -> str:
    extra = f"\nInstrucciones adicionales:\n{instrucciones_extra}\n" if instrucciones_extra else ""

    return f"""
Eres un analista de riesgo y performance de creadores TikTok LIVE.
Evalúa el contexto y genera un score, alertas y explicación operativa.

Contexto:
{contexto_para_prompt(contexto)}

{extra}

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

    return f"""
Eres un coach de creadores de contenido en vivo para TikTok LIVE.
Ayuda al manager a redactar un seguimiento profesional.

Contexto del creador:
{contexto_para_prompt(contexto)}

Observaciones iniciales del manager:
{observaciones_manager or ""}

Compromisos iniciales:
{resumen_compromisos or ""}

{extra}

Devuelve JSON válido:
{{
  "observaciones_manager": "texto mejorado para guardar en observaciones_manager, máximo 1200 caracteres",
  "resumen_compromisos": "texto mejorado para guardar en resumen_compromisos, máximo 1200 caracteres",
  "resumen_corto": "párrafo de máximo 120 palabras para mostrar rápidamente"
}}

Reglas:
- Mantén tono profesional y humano.
- No inventes situaciones personales no presentes en el contexto.
- No uses markdown.
- No incluyas texto fuera del JSON.
"""


# =========================================================
# ENDPOINTS — IA
# =========================================================

@router.post("/api/creadores/performance/{creador_id}/ia/diagnostico")
def generar_diagnostico_ia(
    creador_id: int,
    data: IARequest = IARequest(),
):
    contexto = obtener_contexto_performance(creador_id, id_reporte=data.id_reporte)
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
    contexto = obtener_contexto_performance(creador_id)
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
            "Redacta seguimientos accionables en español. Responde únicamente JSON válido."
        ),
    )

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
    contexto = obtener_contexto_performance(creador_id)
    prompt = prompt_recomendaciones_manager(
        contexto,
        data.max_recomendaciones,
        data.instrucciones_extra,
    )

    resultado = openai_json_completion(
        prompt,
        temperature=0.35,
        system=(
            "Eres experto en coaching operativo para managers de creadores TikTok LIVE. "
            "Responde únicamente JSON válido."
        ),
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
    contexto = obtener_contexto_performance(creador_id)
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
    contexto = obtener_contexto_performance(creador_id)
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
    contexto = obtener_contexto_performance(creador_id)

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
            c.categoria,
            cd.manager_id,
            s.score_general,
            s.nivel_rendimiento,
            s.riesgo_abandono,
            s.probabilidad_crecimiento,
            s.created_at AS score_created_at,
            COALESCE(alertas.alertas_activas, 0) AS alertas_activas,
            COALESCE(acciones.acciones_abiertas, 0) AS acciones_abiertas
        FROM creadores c
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
