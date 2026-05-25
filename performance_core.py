"""
Núcleo: constantes, schemas, infra, repositorios y servicios de performance.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import HTTPException
from openai import OpenAI
from pydantic import AliasChoices, BaseModel, Field

from DataBase import get_connection_context

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL_DEFAULT = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_CONFIG_CLAVE = "open_AI_enabled"
_openai_client: Optional[OpenAI] = None
DEBUG_PERFORMANCE_IA = str(os.getenv("DEBUG_PERFORMANCE_IA", "false")).lower() in {
    "1", "true", "yes", "on",
}

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


class ActualizarArquetipoCreadorRequest(BaseModel):
    arquetipo_id: Optional[int] = None


class DashboardPerformanceResponse(BaseModel):
    ok: bool
    creador: Optional[Dict[str, Any]] = None
    detalle: Optional[Dict[str, Any]] = None
    categoria_creador: Optional[Dict[str, Any]] = None
    arquetipo_creador: Optional[Dict[str, Any]] = None
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
    Unifica saltos de línea para que el front pueda mostrar párrafos separados
    usando white-space: pre-line. No altera el contenido salvo espacios al final
    de línea y líneas en blanco excesivas.
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
    json_mode: bool = False,
) -> str:
    messages: List[dict] = []

    if system:
        messages.append({"role": "system", "content": system})

    messages.append({"role": "user", "content": prompt})

    kwargs: Dict[str, Any] = {
        "model": model or OPENAI_MODEL_DEFAULT,
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        client = get_openai_client()
        try:
            response = client.with_options(timeout=60).chat.completions.create(**kwargs)
        except Exception as e:
            if json_mode and "response_format" in kwargs:
                kwargs_retry = dict(kwargs)
                kwargs_retry.pop("response_format", None)
                response = client.with_options(timeout=60).chat.completions.create(
                    **kwargs_retry
                )
            else:
                raise e
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
        json_mode=True,
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


def obtener_arquetipo_creador(creador_id: int) -> Optional[Dict[str, Any]]:
    """
    Arquetipo operativo definido por el manager en creadores.arquetipo_id.

    Prioridad de uso IA:
    1. Este arquetipo operativo, si existe.
    2. Arquetipo declarado por el creador en la encuesta.
    """
    row = fetch_one(
        """
        SELECT
            a.id,
            a.codigo,
            a.nombre,
            a.descripcion_operativa,
            a.estrategia_json,
            a.activo,
            a.orden
        FROM creadores c
        LEFT JOIN creadores_arquetipo a
            ON a.id = c.arquetipo_id
        WHERE c.id = %s
        LIMIT 1
        """,
        (creador_id,),
    )
    if not row or row.get("id") is None:
        return None
    return row


def obtener_arquetipos_activos() -> List[Dict[str, Any]]:
    """Catálogo de arquetipos operativos para frontend/manager."""
    return fetch_all(
        """
        SELECT
            id,
            codigo,
            nombre,
            descripcion_operativa,
            estrategia_json,
            activo,
            orden,
            created_at,
            updated_at
        FROM creadores_arquetipo
        WHERE COALESCE(activo, true) = true
        ORDER BY orden ASC NULLS LAST, nombre ASC
        """
    )


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
            "El reporte muestra que los diamantes asociados a partidas superan "
            "los diamantes del mes; revisar si ambos datos usan el mismo período "
            "o la misma base de cálculo."
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
        "arquetipo_declarado": None,
        "arquetipo_operativo": None,
        "arquetipo_fuente": None,
        "arquetipo_estrategia": None,
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


def _normalizar_jsonb_db(valor: Any) -> Any:
    """Normaliza JSONB de PostgreSQL; puede llegar como dict/list o string."""
    if valor is None:
        return None
    if isinstance(valor, (dict, list)):
        return valor
    if isinstance(valor, str):
        texto = valor.strip()
        if not texto:
            return None
        try:
            return json.loads(texto)
        except Exception:
            return texto
    return valor


def _lista_desde_jsonb(valor: Any) -> List[str]:
    """Convierte un campo JSONB a lista de textos útil para prompts."""
    valor = _normalizar_jsonb_db(valor)
    if valor is None:
        return []
    if isinstance(valor, list):
        return [str(v).strip() for v in valor if v is not None and str(v).strip()]
    if isinstance(valor, dict):
        for clave in ("items", "valores", "dinamicas", "estrategias", "opciones"):
            if isinstance(valor.get(clave), list):
                return _lista_desde_jsonb(valor.get(clave))
        return [str(v).strip() for v in valor.values() if v is not None and str(v).strip()]
    texto = str(valor).strip()
    return [texto] if texto else []


def _arquetipo_estrategia_desde_row(
    arquetipo_creador: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Estructura compacta para enviar a la IA:
    - nombre/código del arquetipo operativo
    - definición operativa
    - estrategia_json con dinámicas, monetización, interacción, contenido y evitar
    """
    if not arquetipo_creador or arquetipo_creador.get("id") is None:
        return None

    estrategia_json = _normalizar_jsonb_db(arquetipo_creador.get("estrategia_json"))
    if estrategia_json is None:
        estrategia_json = {}

    return {
        "codigo": arquetipo_creador.get("codigo"),
        "nombre": arquetipo_creador.get("nombre"),
        "descripcion_operativa": arquetipo_creador.get("descripcion_operativa"),
        "estrategia_json": estrategia_json,
    }


def _arquetipo_estrategia_contexto(contexto: Dict[str, Any]) -> Dict[str, Any]:
    """
    Obtiene la estrategia operativa del arquetipo desde perfil_estrategico
    o desde arquetipo_creador.
    """
    perfil = contexto.get("perfil_estrategico") or {}
    estrategia = perfil.get("arquetipo_estrategia")

    if not estrategia and contexto.get("arquetipo_creador"):
        estrategia = _arquetipo_estrategia_desde_row(contexto.get("arquetipo_creador"))

    if not isinstance(estrategia, dict):
        return {}

    estrategia_json = _normalizar_jsonb_db(estrategia.get("estrategia_json"))
    if estrategia_json is None:
        estrategia_json = {}
    if not isinstance(estrategia_json, dict):
        estrategia_json = {"valor": estrategia_json}

    return {
        "codigo": estrategia.get("codigo"),
        "nombre": estrategia.get("nombre"),
        "descripcion_operativa": estrategia.get("descripcion_operativa"),
        "estrategia_json": estrategia_json,
    }


_CLAVES_ESTRATEGIA_JSON_POR_CATEGORIA: Dict[str, List[str]] = {
    "contenido": ["estrategias_contenido", "dinamicas_recomendadas"],
    "interaccion": ["estrategias_interaccion", "dinamicas_recomendadas"],
    "monetizacion": ["estrategias_monetizacion", "dinamicas_recomendadas"],
    "horario": ["dinamicas_recomendadas", "estrategias_contenido"],
    "audiencia": ["dinamicas_recomendadas", "estrategias_interaccion"],
    "disciplina": ["dinamicas_recomendadas"],
    "emocional": ["dinamicas_recomendadas"],
    "tecnica": ["dinamicas_recomendadas"],
    "otro": ["dinamicas_recomendadas", "estrategias_contenido"],
}


def _estrategia_json_de_arquetipo(
    arquetipo_estrategia: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not isinstance(arquetipo_estrategia, dict):
        return {}
    ej = _normalizar_jsonb_db(arquetipo_estrategia.get("estrategia_json"))
    if isinstance(ej, dict):
        return ej
    return {}


def _items_estrategia_arquetipo_por_categoria(
    arquetipo_estrategia: Optional[Dict[str, Any]],
    categoria_norm: str,
    limit: int = 3,
) -> List[str]:
    """Ítems de estrategia_json según categoría de recomendación (sin if por nombre de arquetipo)."""
    if not arquetipo_estrategia:
        return []

    estrategia_json = _estrategia_json_de_arquetipo(arquetipo_estrategia)
    claves = _CLAVES_ESTRATEGIA_JSON_POR_CATEGORIA.get(
        categoria_norm,
        ["dinamicas_recomendadas", "estrategias_contenido"],
    )

    resultado: List[str] = []
    for clave in claves:
        for item in _lista_desde_jsonb(estrategia_json.get(clave)):
            texto = (item or "").strip()
            if texto and texto not in resultado:
                resultado.append(texto)
            if len(resultado) >= limit:
                return resultado
    return resultado


def construir_perfil_estrategico(
    perfil_respuestas: Optional[List[Dict[str, Any]]],
    categoria_creador: Optional[Dict[str, Any]] = None,
    arquetipo_creador: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Construye el perfil estratégico usado por el dashboard y la IA.

    Prioridad de arquetipo:
    1. creadores.arquetipo_id -> creadores_arquetipo (manager / operativo).
    2. creadores_perfil_respuesta -> arquetipo declarado por encuesta.
    3. Sin dato.
    """
    campos_cat = _campos_categoria_en_perfil(categoria_creador)
    arquetipo_estrategia = _arquetipo_estrategia_desde_row(arquetipo_creador)
    arquetipo_operativo = (
        arquetipo_creador.get("nombre")
        if arquetipo_creador and arquetipo_creador.get("nombre")
        else None
    )

    arquetipo_definicion = None
    arquetipo_declarado = None
    intereses: List[Any] = []
    horario_preferido = None
    nivel_estudios = None
    idiomas_dominio = None

    if perfil_respuestas:
        arquetipo_definicion = normalizar_respuesta_perfil(
            obtener_valor_perfil(perfil_respuestas, "arquetipo_definicion")
        )
        arquetipo_declarado = normalizar_respuesta_perfil(
            obtener_valor_perfil(perfil_respuestas, "arquetipo_valor")
        )

        intereses_raw = obtener_valor_perfil(perfil_respuestas, "intereses_multiples")
        if intereses_raw is None:
            intereses_raw = obtener_valor_perfil(perfil_respuestas, "intereses")
        intereses_norm = normalizar_respuesta_perfil(intereses_raw)
        if intereses_norm is None:
            intereses = []
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

    arquetipo_valor = arquetipo_operativo or arquetipo_declarado
    if arquetipo_operativo:
        arquetipo_fuente = "manager"
    elif arquetipo_declarado:
        arquetipo_fuente = "encuesta"
    else:
        arquetipo_fuente = None

    partes_resumen: List[str] = []
    if campos_cat.get("categoria_actual"):
        partes_resumen.append(f"Categoría: {campos_cat['categoria_actual']}")
    if campos_cat.get("meta_categoria_diamantes") is not None:
        partes_resumen.append(
            f"Meta categoría: {campos_cat['meta_categoria_diamantes']} diamantes"
        )

    arq_val_txt = _valor_a_texto_resumen(arquetipo_valor)
    if arq_val_txt:
        if arquetipo_fuente == "manager":
            partes_resumen.append(f"Arquetipo operativo: {arq_val_txt}")
        else:
            partes_resumen.append(f"Arquetipo declarado: {arq_val_txt}")

    arq_decl_txt = _valor_a_texto_resumen(arquetipo_declarado)
    if arquetipo_operativo and arq_decl_txt and arq_decl_txt != arq_val_txt:
        partes_resumen.append(f"Arquetipo declarado por encuesta: {arq_decl_txt}")

    if arquetipo_estrategia and arquetipo_estrategia.get("descripcion_operativa"):
        partes_resumen.append(
            f"Definición arquetipo: {arquetipo_estrategia.get('descripcion_operativa')}"
        )

    estrategia_json = (
        arquetipo_estrategia.get("estrategia_json")
        if isinstance(arquetipo_estrategia, dict)
        else {}
    )
    if isinstance(estrategia_json, dict):
        estilo_live = _valor_a_texto_resumen(estrategia_json.get("estilo_live"))
        if estilo_live:
            partes_resumen.append(f"Estilo LIVE: {estilo_live}")

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
        "arquetipo_declarado": arquetipo_declarado,
        "arquetipo_operativo": arquetipo_operativo,
        "arquetipo_fuente": arquetipo_fuente,
        "arquetipo_estrategia": arquetipo_estrategia,
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
    arquetipo_creador = obtener_arquetipo_creador(creador_id)
    performance_partidas = construir_performance_partidas(ultimo_reporte)

    contexto = {
        "creador": creador,
        "detalle": detalle,
        "categoria_creador": categoria_creador,
        "arquetipo_creador": arquetipo_creador,
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
            perfil_respuestas,
            categoria_creador,
            arquetipo_creador,
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
        "arquetipo_creador": contexto.get("arquetipo_creador"),
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

    if partidas < 5 and arquetipo:
        estrategia_arq = _arquetipo_estrategia_contexto(contexto)
        dinamicas_arq = _items_estrategia_arquetipo_por_categoria(estrategia_arq, "contenido", 1)
        dinamica_txt = dinamicas_arq[0] if dinamicas_arq else "dinámicas competitivas o batallas"
        agregar(
            "contenido",
            "alta",
            f"Probar {dinamica_txt}, alineadas al arquetipo {arquetipo}, en horario preferido.",
            f"Arquetipo {arquetipo} con pocas partidas registradas en el período.",
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


