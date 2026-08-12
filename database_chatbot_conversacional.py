"""
Acceso a datos — Chatbot conversacional.

Cubre el asistente configurable, el catálogo de conocimiento (requisitos,
beneficios, FAQ, recursos), los flujos y pasos, las campañas de captación, las
pruebas LIVE con sus evidencias requeridas, las reglas de escalamiento y la
operación en vivo (conversaciones, mensajes, tareas, evidencias y eventos).

Todas las consultas filtran siempre por ``agencia_id``: el identificador que
llega desde el cliente nunca se usa sin restringir el WHERE.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from psycopg2.extras import Json, RealDictCursor

from DataBase import get_connection_chatbot_context

logger = logging.getLogger("uvicorn.error")


# ---------------------------------------------------------------------------
# Constantes: tablas, columnas escribibles y tipos especiales
# ---------------------------------------------------------------------------

_TABLAS: Dict[str, str] = {
    "asistente": "chatbot.asistente_configuracion",
    "requisitos": "chatbot.requisitos_conversacionales",
    "beneficios": "chatbot.beneficios_bonos",
    "faq": "chatbot.faq_conversacional",
    "flujos": "chatbot.flujos_conversacionales",
    "flujo_pasos": "chatbot.flujo_pasos",
    "campanias": "chatbot.campanias_captacion",
    "recursos": "chatbot.recursos_enlaces",
    "pruebas_live": "chatbot.pruebas_live_configuracion",
    "evidencias_requeridas": "chatbot.evidencias_requeridas",
    "reglas_escalamiento": "chatbot.reglas_escalamiento",
    "conversaciones": "chatbot.conversaciones",
    "mensajes": "chatbot.mensajes_conversacion",
    "tareas": "chatbot.tareas_candidato",
    "evidencias": "chatbot.evidencias_candidato",
    "eventos": "chatbot.eventos_conversacion",
    "menu_informativo": "chatbot.menu_informativo_opciones",
}

# Tablas que llevan updated_at (el trigger lo refresca, se envía igualmente).
_TABLAS_CON_UPDATED_AT = {
    "asistente",
    "requisitos",
    "beneficios",
    "faq",
    "flujos",
    "flujo_pasos",
    "campanias",
    "recursos",
    "pruebas_live",
    "evidencias_requeridas",
    "reglas_escalamiento",
    "conversaciones",
    "tareas",
    "evidencias",
    "menu_informativo",
}

# Tablas con borrado lógico disponible.
_TABLAS_CON_ACTIVO = {
    "asistente",
    "requisitos",
    "beneficios",
    "faq",
    "flujos",
    "flujo_pasos",
    "campanias",
    "recursos",
    "pruebas_live",
    "evidencias_requeridas",
    "reglas_escalamiento",
    "menu_informativo",
}

# Columnas jsonb (se envuelven con Json) y columnas array (se pasan como lista).
_COLUMNAS_JSONB = {
    "horario_atencion_humana",
    "herramientas_permitidas",
    "contenido_prohibido",
    "reglas_adicionales",
    "valor_json",
    "condiciones",
    "paises_aplica",
    "perfiles_aplica",
    "configuracion",
    "horarios_permitidos",
    "metadata",
    "contexto",
    "configuracion_recordatorio",
    "datos_resultado",
    "detalle",
}

_COLUMNAS_ARRAY = {
    "palabras_clave",
    "formatos_permitidos",
    "dias_permitidos",
}

# Columnas jsonb que deben ser array (el CHECK de la BD lo exige).
_COLUMNAS_JSONB_ARRAY = {
    "herramientas_permitidas",
    "contenido_prohibido",
    "paises_aplica",
    "perfiles_aplica",
}

COLUMNAS_ASISTENTE = {
    "nombre_asistente",
    "descripcion_agencia",
    "presentacion_inicial",
    "presentacion_informativo",
    "presentacion_inteligente",
    "tono",
    "idioma",
    "zona_horaria",
    "declarar_asistente_virtual",
    "modo_informativo_activo",
    "modo_conversion_activo",
    "modo_predeterminado",
    "proveedor_ia",
    "modelo_ia",
    "instrucciones_sistema",
    "prompt_version",
    "max_tokens_salida",
    "max_preguntas_seguidas",
    "max_intentos_aclaracion",
    "horario_atencion_humana",
    "mensaje_fuera_horario",
    "herramientas_permitidas",
    "contenido_prohibido",
    "reglas_adicionales",
    "texto_privacidad",
    "activo",
    "creado_por",
    "actualizado_por",
    # Clasificación adaptativa (columnas ya existentes en BD)
    "estrategia_nivel_aspirante",
    "nivel_predeterminado",
    "nivel_fijo",
    "permitir_reclasificacion_automatica",
    "preguntar_nivel_si_ambiguo",
    "umbral_confianza_nivel",
    "max_preguntas_clasificacion",
    "pregunta_clasificacion_nivel",
    "texto_inicio_principiante",
    "texto_inicio_experimentado",
    # Presentación chatbot informativo (columnas ya disponibles en BD)
    "mostrar_menu_inicial",
    "titulo_menu_inicial",
    "texto_indicacion_menu",
    "formato_respuestas_informativas",
    "max_elementos_respuesta",
    "mostrar_titulo_respuesta",
    "agregar_pregunta_final",
    "repetir_menu_despues_respuesta",
    "mensaje_no_entendido",
    "mensaje_sin_informacion",
    "mensaje_escalamiento_sin_bloqueo",
    "mensaje_modo_humano",
}

COLUMNAS_REQUISITO = {
    "chatbot_configuracion_id",
    "codigo",
    "nombre",
    "descripcion",
    "categoria",
    "tipo_dato",
    "operador",
    "valor_minimo",
    "valor_maximo",
    "valor_texto",
    "valor_json",
    "unidad",
    "bloquea_proceso",
    "permitir_mencion_automatica",
    "mensaje_si_no_cumple",
    "orden",
    "version",
    "vigencia_desde",
    "vigencia_hasta",
    "activo",
    "creado_por",
    "actualizado_por",
}

COLUMNAS_BENEFICIO = {
    "chatbot_configuracion_id",
    "campania_id",
    "codigo",
    "nombre",
    "tipo",
    "descripcion_corta",
    "descripcion_completa",
    "texto_autorizado",
    "valor",
    "moneda",
    "formula_calculo",
    "condiciones",
    "paises_aplica",
    "perfiles_aplica",
    "requiere_validacion_humana",
    "permitir_mencion_automatica",
    "visible_publicamente",
    "version",
    "fecha_inicio",
    "fecha_fin",
    "activo",
    "creado_por",
    "actualizado_por",
}

COLUMNAS_FAQ = {
    "chatbot_configuracion_id",
    "codigo",
    "categoria",
    "intencion",
    "pregunta",
    "respuesta_corta",
    "respuesta_completa",
    "palabras_clave",
    "requiere_humano",
    "evento_escalamiento",
    "prioridad",
    "fuente",
    "version",
    "vigencia_desde",
    "vigencia_hasta",
    "activo",
    "creado_por",
    "actualizado_por",
}

COLUMNAS_MENU_INFORMATIVO = {
    "chatbot_configuracion_id",
    "numero",
    "codigo",
    "titulo",
    "descripcion",
    "intencion",
    "tipo_fuente",
    "respuesta_personalizada",
    "requiere_asesor",
    "orden",
    "activo",
    "creado_por",
    "actualizado_por",
}

COLUMNAS_FLUJO = {
    "chatbot_configuracion_id",
    "codigo",
    "nombre",
    "tipo_flujo",
    "nivel_objetivo",
    "descripcion",
    "evento_inicio",
    "estado_inicial",
    "estado_final",
    "configuracion",
    "activo",
    "creado_por",
    "actualizado_por",
}

COLUMNAS_FLUJO_PASO = {
    "flujo_id",
    "codigo",
    "nombre",
    "descripcion",
    "orden",
    "tipo_accion",
    "obligatorio",
    "permite_omitir",
    "requiere_humano",
    "mensaje_instrucciones",
    "estado_exitoso",
    "estado_fallido",
    "siguiente_paso_id",
    "siguiente_paso_fallo_id",
    "configuracion",
    "activo",
    "creado_por",
    "actualizado_por",
}

COLUMNAS_CAMPANIA = {
    "chatbot_configuracion_id",
    "flujo_id",
    "codigo",
    "nombre",
    "plataforma_codigo",
    "canal_origen",
    "identificador_externo",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "modo_predeterminado",
    "candidato_preseleccionado",
    "mensaje_inicial",
    "beneficio_principal",
    "publico_objetivo",
    "metadata",
    "fecha_inicio",
    "fecha_fin",
    "activo",
    "creado_por",
    "actualizado_por",
}

COLUMNAS_RECURSO = {
    "chatbot_configuracion_id",
    "campania_id",
    "codigo",
    "nombre",
    "tipo",
    "url_template",
    "descripcion",
    "texto_boton",
    "requiere_token",
    "tipo_token",
    "abrir_externo",
    "version",
    "vigencia_desde",
    "vigencia_hasta",
    "activo",
    "creado_por",
    "actualizado_por",
}

COLUMNAS_PRUEBA_LIVE = {
    "flujo_id",
    "campania_id",
    "codigo",
    "nombre",
    "duracion_minima_minutos",
    "cantidad_batallas",
    "requiere_agendamiento",
    "zona_horaria",
    "dias_permitidos",
    "horarios_permitidos",
    "plazo_evidencias_horas",
    "permite_reintento",
    "maximo_reintentos",
    "instrucciones_antes",
    "instrucciones_durante",
    "instrucciones_despues",
    "activo",
    "creado_por",
    "actualizado_por",
}

COLUMNAS_EVIDENCIA_REQUERIDA = {
    "prueba_live_id",
    "codigo",
    "nombre",
    "descripcion",
    "tipo_evidencia",
    "momento_requerido",
    "obligatoria",
    "orden",
    "formatos_permitidos",
    "ejemplo_url",
    "activo",
    "creado_por",
    "actualizado_por",
}

COLUMNAS_REGLA_ESCALAMIENTO = {
    "chatbot_configuracion_id",
    "flujo_id",
    "campania_id",
    "evento",
    "descripcion",
    "prioridad",
    "manager_id",
    "equipo_destino",
    "canal_destino",
    "mensaje_usuario",
    "mensaje_interno",
    "estado_destino",
    "aplicar_fuera_horario",
    "configuracion",
    "orden",
    "activo",
    "creado_por",
    "actualizado_por",
}

COLUMNAS_CONVERSACION = {
    "chatbot_configuracion_id",
    "aspirante_id",
    "campania_id",
    "flujo_id",
    "paso_actual_id",
    "plataforma_codigo",
    "canal",
    "cuenta_externa_id",
    "usuario_externo_id",
    "conversacion_externa_id",
    "nombre_contacto",
    "telefono",
    "usuario_plataforma",
    "modo",
    "estado",
    "estado_actual",
    "ia_habilitada",
    "modo_humano",
    "manager_id",
    "motivo_escalamiento",
    "proveedor_conversation_id",
    "resumen_contexto",
    "contexto",
    "consentimiento_datos",
    "consentimiento_at",
    "iniciada_at",
    "ultimo_mensaje_at",
    "escalada_at",
    "cerrada_at",
    # Estado dinámico adaptativo (columnas ya existentes en BD)
    "nivel_experiencia",
    "nivel_experiencia_fuente",
    "nivel_experiencia_confianza",
    "nivel_experiencia_confirmado",
    "nivel_experiencia_bloqueado_manual",
    "nivel_experiencia_actualizado_at",
    "estrategia_nivel_aplicada",
    "preguntas_clasificacion_realizadas",
    "intencion_actual",
    "intencion_confianza",
    "intencion_actualizada_at",
    "ultima_clasificacion_at",
}

COLUMNAS_TAREA = {
    "conversacion_id",
    "aspirante_id",
    "paso_flujo_id",
    "tipo_tarea",
    "titulo",
    "descripcion",
    "estado",
    "fecha_limite",
    "completada_at",
    "creada_por_tipo",
    "creada_por_id",
    "configuracion_recordatorio",
    "datos_resultado",
}

COLUMNAS_EVIDENCIA = {
    "conversacion_id",
    "aspirante_id",
    "tarea_id",
    "mensaje_id",
    "evidencia_requerida_id",
    "tipo_evidencia",
    "tipo_archivo",
    "archivo_url",
    "archivo_id_externo",
    "archivo_nombre",
    "mime_type",
    "valor_texto",
    "metadata",
    "estado_revision",
    "observaciones_revision",
    "revisado_por",
    "revisado_at",
    "capturada_at",
}

COLUMNAS_ASPIRANTE_CONVERSACIONAL = {
    "origen_captacion",
    "campania_id",
    "modo_conversacional",
    "preseleccionado_ads",
    # Clasificación estable (columnas ya existentes en BD)
    "nivel_experiencia",
    "nivel_experiencia_fuente",
    "nivel_experiencia_confianza",
    "nivel_experiencia_confirmado_at",
    "nivel_experiencia_bloqueado_manual",
}

ESTADOS_CONVERSACION = (
    "abierta",
    "esperando_usuario",
    "esperando_humano",
    "cerrada",
    "bloqueada",
)

ESTADOS_EVIDENCIA_PENDIENTE = ("recibida", "pendiente", "en_revision")

ESTADOS_TAREA_PENDIENTE = ("pendiente", "en_progreso")

_CODIGO_RE = re.compile(r"[^a-z0-9_]+")

# Centinela para distinguir "no enviado" de "enviado como NULL".
class _SinValor:
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - ayuda en depuración
        return "<sin_valor>"


SIN_VALOR = _SinValor()


class ErrorDatosConversacional(Exception):
    """Error de negocio en la capa de datos conversacional."""


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


@contextmanager
def _cursor(cur=None):
    """Reutiliza un cursor abierto o crea conexión/cursor propios."""
    if cur is not None:
        yield cur
    else:
        with get_connection_chatbot_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as nuevo:
                yield nuevo


def _ahora() -> datetime:
    """Timestamp con zona para columnas ``timestamptz``."""
    return datetime.now(timezone.utc)


def _fila(row: Any) -> Optional[Dict[str, Any]]:
    return dict(row) if row else None


def _filas(rows: Any) -> List[Dict[str, Any]]:
    return [dict(r) for r in (rows or [])]


def _slug_codigo(valor: Any, prefijo: str = "item") -> str:
    texto = str(valor or "").strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = texto.replace(" ", "_").replace("-", "_")
    texto = _CODIGO_RE.sub("", texto)
    texto = re.sub(r"_+", "_", texto).strip("_")
    return (texto or prefijo)[:100]


def _valor_jsonb(columna: str, valor: Any) -> Any:
    if valor is None:
        return None
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except (TypeError, ValueError):
            valor = [] if columna in _COLUMNAS_JSONB_ARRAY else {}
    if columna in _COLUMNAS_JSONB_ARRAY and not isinstance(valor, list):
        valor = list(valor) if isinstance(valor, (tuple, set)) else []
    if columna not in _COLUMNAS_JSONB_ARRAY and not isinstance(valor, (dict, list)):
        valor = {}
    # Defensa: Decimal/datetime desde filas RealDictCursor no son JSON-safe.
    try:
        from chatbot_conversacional_perfil import normalizar_json_safe

        valor = normalizar_json_safe(valor)
    except Exception:  # noqa: BLE001
        pass
    return Json(valor)


def _valor_array(valor: Any) -> Any:
    if valor is None:
        return None
    if isinstance(valor, (list, tuple, set)):
        return list(valor)
    return [valor]


def _preparar_valor(columna: str, valor: Any) -> Any:
    if columna in _COLUMNAS_JSONB:
        return _valor_jsonb(columna, valor)
    if columna in _COLUMNAS_ARRAY:
        return _valor_array(valor)
    return valor


def _campos_permitidos(
    campos: Optional[Dict[str, Any]],
    permitidas: Iterable[str],
) -> Dict[str, Any]:
    """Descarta cualquier clave que no esté en la lista blanca de columnas."""
    if not campos:
        return {}
    permitidas = set(permitidas)
    return {k: v for k, v in campos.items() if k in permitidas}


def _tabla(clave: str) -> str:
    try:
        return _TABLAS[clave]
    except KeyError as exc:  # pragma: no cover - error de programación
        raise ErrorDatosConversacional(f"Tabla desconocida: {clave}") from exc


def _limite(limit: Optional[int], defecto: int = 50, maximo: int = 200) -> int:
    try:
        valor = int(limit) if limit is not None else defecto
    except (TypeError, ValueError):
        valor = defecto
    return max(1, min(valor, maximo))


def _offset(offset: Optional[int]) -> int:
    try:
        valor = int(offset or 0)
    except (TypeError, ValueError):
        valor = 0
    return max(0, valor)


def _crear_registro(
    clave_tabla: str,
    agencia_id: int,
    campos: Dict[str, Any],
    permitidas: Iterable[str],
    *,
    cur=None,
) -> Dict[str, Any]:
    datos = _campos_permitidos(campos, permitidas)
    columnas = ["agencia_id"] + list(datos.keys())
    valores: List[Any] = [agencia_id] + [
        _preparar_valor(col, datos[col]) for col in datos
    ]
    placeholders = ", ".join(["%s"] * len(columnas))
    sql = (
        f"INSERT INTO {_tabla(clave_tabla)} ({', '.join(columnas)}) "
        f"VALUES ({placeholders}) RETURNING *"
    )
    with _cursor(cur) as c:
        c.execute(sql, valores)
        row = c.fetchone()
    if not row:  # pragma: no cover - INSERT ... RETURNING siempre devuelve fila
        raise ErrorDatosConversacional(f"No se pudo crear el registro en {clave_tabla}")
    return dict(row)


def _obtener_registro(
    clave_tabla: str,
    agencia_id: int,
    registro_id: int,
    *,
    cur=None,
) -> Optional[Dict[str, Any]]:
    sql = f"SELECT * FROM {_tabla(clave_tabla)} WHERE id = %s AND agencia_id = %s LIMIT 1"
    with _cursor(cur) as c:
        c.execute(sql, (registro_id, agencia_id))
        return _fila(c.fetchone())


def _actualizar_registro(
    clave_tabla: str,
    agencia_id: int,
    registro_id: int,
    campos: Dict[str, Any],
    permitidas: Iterable[str],
    *,
    cur=None,
) -> Optional[Dict[str, Any]]:
    datos = _campos_permitidos(campos, permitidas)
    if not datos:
        return _obtener_registro(clave_tabla, agencia_id, registro_id, cur=cur)

    sets = [f"{col} = %s" for col in datos]
    valores: List[Any] = [_preparar_valor(col, datos[col]) for col in datos]
    if clave_tabla in _TABLAS_CON_UPDATED_AT:
        sets.append("updated_at = CURRENT_TIMESTAMP")
    valores.extend([registro_id, agencia_id])

    sql = (
        f"UPDATE {_tabla(clave_tabla)} SET {', '.join(sets)} "
        f"WHERE id = %s AND agencia_id = %s RETURNING *"
    )
    with _cursor(cur) as c:
        c.execute(sql, valores)
        return _fila(c.fetchone())


def _eliminar_registro(
    clave_tabla: str,
    agencia_id: int,
    registro_id: int,
    *,
    hard: bool = False,
    cur=None,
) -> bool:
    """Borrado lógico (activo=False) salvo que se pida hard delete."""
    soft = (not hard) and clave_tabla in _TABLAS_CON_ACTIVO
    if soft:
        sql = (
            f"UPDATE {_tabla(clave_tabla)} SET activo = FALSE, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE id = %s AND agencia_id = %s RETURNING id"
        )
    else:
        sql = f"DELETE FROM {_tabla(clave_tabla)} WHERE id = %s AND agencia_id = %s RETURNING id"
    with _cursor(cur) as c:
        c.execute(sql, (registro_id, agencia_id))
        return c.fetchone() is not None


def _listar_registros(
    clave_tabla: str,
    agencia_id: int,
    *,
    where_extra: Optional[Sequence[str]] = None,
    params_extra: Optional[Sequence[Any]] = None,
    order_by: str = "id ASC",
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    cur=None,
) -> List[Dict[str, Any]]:
    where = ["agencia_id = %s"]
    params: List[Any] = [agencia_id]
    if where_extra:
        where.extend(where_extra)
    if params_extra:
        params.extend(params_extra)

    sql = (
        f"SELECT * FROM {_tabla(clave_tabla)} "
        f"WHERE {' AND '.join(where)} ORDER BY {order_by}"
    )
    if limit is not None:
        sql += " LIMIT %s OFFSET %s"
        params.extend([_limite(limit, maximo=500), _offset(offset)])

    with _cursor(cur) as c:
        c.execute(sql, params)
        return _filas(c.fetchall())


def _configuracion_pertenece_agencia(
    agencia_id: int,
    chatbot_configuracion_id: int,
    *,
    cur=None,
) -> bool:
    with _cursor(cur) as c:
        c.execute(
            """
            SELECT 1
            FROM chatbot.chatbot_configuracion
            WHERE id = %s AND agencia_id = %s
            LIMIT 1
            """,
            (chatbot_configuracion_id, agencia_id),
        )
        return c.fetchone() is not None


def _exige_configuracion(agencia_id: int, chatbot_configuracion_id: int, *, cur=None) -> None:
    if not _configuracion_pertenece_agencia(agencia_id, chatbot_configuracion_id, cur=cur):
        raise ErrorDatosConversacional(
            "La configuración de chatbot no existe o no pertenece a la agencia"
        )


# ---------------------------------------------------------------------------
# Asistente configurable
# ---------------------------------------------------------------------------


def _normalizar_campos_presentacion(campos: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Alias de escritura:
    - presentacion_inicial → también presentacion_informativo (si no viene explícita)
    - si solo llega informativo y no inicial, sincroniza inicial para legacy
    """
    datos = dict(campos or {})
    if "presentacion_inicial" in datos and "presentacion_informativo" not in datos:
        datos["presentacion_informativo"] = datos.get("presentacion_inicial")
    if "presentacion_informativo" in datos and "presentacion_inicial" not in datos:
        datos["presentacion_inicial"] = datos.get("presentacion_informativo")
    return datos


def _enriquecer_asistente_presentaciones(
    fila: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Lectura: rellena faltantes desde presentacion_inicial legacy."""
    if not fila:
        return fila
    out = dict(fila)
    legacy = str(out.get("presentacion_inicial") or "").strip() or None
    info = str(out.get("presentacion_informativo") or "").strip() or None
    intel = str(out.get("presentacion_inteligente") or "").strip() or None
    if not info and legacy:
        out["presentacion_informativo"] = legacy
        info = legacy
    if not intel and legacy:
        out["presentacion_inteligente"] = legacy
    if not legacy and info:
        out["presentacion_inicial"] = info
    return out


def obtener_asistente_por_config(
    agencia_id: int,
    chatbot_configuracion_id: int,
    *,
    cur=None,
) -> Optional[Dict[str, Any]]:
    with _cursor(cur) as c:
        c.execute(
            """
            SELECT *
            FROM chatbot.asistente_configuracion
            WHERE agencia_id = %s AND chatbot_configuracion_id = %s
            LIMIT 1
            """,
            (agencia_id, chatbot_configuracion_id),
        )
        return _enriquecer_asistente_presentaciones(_fila(c.fetchone()))


def asistente_activo_para_config(
    agencia_id: int,
    chatbot_configuracion_id: int,
    *,
    cur=None,
) -> bool:
    with _cursor(cur) as c:
        c.execute(
            """
            SELECT activo
            FROM chatbot.asistente_configuracion
            WHERE agencia_id = %s AND chatbot_configuracion_id = %s
            LIMIT 1
            """,
            (agencia_id, chatbot_configuracion_id),
        )
        row = c.fetchone()
        return bool(row and row.get("activo"))


def upsert_asistente(
    agencia_id: int,
    chatbot_configuracion_id: int,
    campos: Optional[Dict[str, Any]] = None,
    *,
    cur=None,
) -> Dict[str, Any]:
    """
    Crea o actualiza la configuración del asistente de una configuración.

    La unicidad de la tabla es por ``chatbot_configuracion_id``; el DO UPDATE
    lleva además el filtro por agencia para que una agencia nunca pueda pisar la
    fila de otra.
    """
    datos = _campos_permitidos(
        _normalizar_campos_presentacion(campos), COLUMNAS_ASISTENTE
    )

    with _cursor(cur) as c:
        _exige_configuracion(agencia_id, chatbot_configuracion_id, cur=c)

        columnas = ["agencia_id", "chatbot_configuracion_id"] + list(datos.keys())
        valores: List[Any] = [agencia_id, chatbot_configuracion_id] + [
            _preparar_valor(col, datos[col]) for col in datos
        ]
        placeholders = ", ".join(["%s"] * len(columnas))
        sets = [f"{col} = EXCLUDED.{col}" for col in datos]
        sets.append("updated_at = CURRENT_TIMESTAMP")

        c.execute(
            f"""
            INSERT INTO chatbot.asistente_configuracion ({', '.join(columnas)})
            VALUES ({placeholders})
            ON CONFLICT (chatbot_configuracion_id) DO UPDATE
                SET {', '.join(sets)}
            WHERE asistente_configuracion.agencia_id = %s
            RETURNING *
            """,
            valores + [agencia_id],
        )
        row = c.fetchone()

    if not row:
        raise ErrorDatosConversacional(
            "No se pudo guardar el asistente: la configuración pertenece a otra agencia"
        )
    logger.info(
        "[CONVERSACIONAL] upsert asistente agencia_id=%s config_id=%s",
        agencia_id,
        chatbot_configuracion_id,
    )
    return _enriquecer_asistente_presentaciones(dict(row))


def actualizar_asistente(
    agencia_id: int,
    asistente_id: int,
    campos: Dict[str, Any],
    *,
    cur=None,
) -> Optional[Dict[str, Any]]:
    out = _actualizar_registro(
        "asistente",
        agencia_id,
        asistente_id,
        _normalizar_campos_presentacion(campos),
        COLUMNAS_ASISTENTE,
        cur=cur,
    )
    return _enriquecer_asistente_presentaciones(out)


def listar_asistentes(agencia_id: int, *, solo_activos: bool = False, cur=None) -> List[Dict[str, Any]]:
    where = ["activo = TRUE"] if solo_activos else None
    return _listar_registros(
        "asistente",
        agencia_id,
        where_extra=where,
        order_by="chatbot_configuracion_id ASC",
        cur=cur,
    )


# ---------------------------------------------------------------------------
# Requisitos conversacionales
# ---------------------------------------------------------------------------


def listar_requisitos(
    agencia_id: int,
    *,
    chatbot_configuracion_id: Optional[int] = None,
    incluir_globales: bool = True,
    categoria: Optional[str] = None,
    solo_activos: bool = True,
    solo_vigentes: bool = False,
    cur=None,
) -> List[Dict[str, Any]]:
    where: List[str] = []
    params: List[Any] = []

    if chatbot_configuracion_id is not None:
        if incluir_globales:
            where.append(
                "(chatbot_configuracion_id = %s OR chatbot_configuracion_id IS NULL)"
            )
        else:
            where.append("chatbot_configuracion_id = %s")
        params.append(chatbot_configuracion_id)
    if categoria:
        where.append("categoria = %s")
        params.append(str(categoria).strip().lower())
    if solo_activos:
        where.append("activo = TRUE")
    if solo_vigentes:
        where.append("(vigencia_desde IS NULL OR vigencia_desde <= CURRENT_DATE)")
        where.append("(vigencia_hasta IS NULL OR vigencia_hasta >= CURRENT_DATE)")

    return _listar_registros(
        "requisitos",
        agencia_id,
        where_extra=where,
        params_extra=params,
        order_by="orden ASC, id ASC",
        cur=cur,
    )


def obtener_requisito(agencia_id: int, requisito_id: int, *, cur=None) -> Optional[Dict[str, Any]]:
    return _obtener_registro("requisitos", agencia_id, requisito_id, cur=cur)


def obtener_requisito_por_codigo(
    agencia_id: int,
    codigo: str,
    *,
    chatbot_configuracion_id: Optional[int] = None,
    solo_activos: bool = True,
    cur=None,
) -> Optional[Dict[str, Any]]:
    where = ["codigo = %s", "COALESCE(chatbot_configuracion_id, 0) = %s"]
    params: List[Any] = [codigo, chatbot_configuracion_id or 0]
    if solo_activos:
        where.append("activo = TRUE")
    filas = _listar_registros(
        "requisitos",
        agencia_id,
        where_extra=where,
        params_extra=params,
        order_by="id DESC",
        limit=1,
        cur=cur,
    )
    return filas[0] if filas else None


def crear_requisito(agencia_id: int, campos: Dict[str, Any], *, cur=None) -> Dict[str, Any]:
    with _cursor(cur) as c:
        cfg = (campos or {}).get("chatbot_configuracion_id")
        if cfg:
            _exige_configuracion(agencia_id, int(cfg), cur=c)
        return _crear_registro("requisitos", agencia_id, campos, COLUMNAS_REQUISITO, cur=c)


def actualizar_requisito(
    agencia_id: int, requisito_id: int, campos: Dict[str, Any], *, cur=None
) -> Optional[Dict[str, Any]]:
    return _actualizar_registro(
        "requisitos", agencia_id, requisito_id, campos, COLUMNAS_REQUISITO, cur=cur
    )


def eliminar_requisito(
    agencia_id: int, requisito_id: int, *, hard: bool = False, cur=None
) -> bool:
    return _eliminar_registro("requisitos", agencia_id, requisito_id, hard=hard, cur=cur)


# ---------------------------------------------------------------------------
# Beneficios y bonos
# ---------------------------------------------------------------------------


def listar_beneficios(
    agencia_id: int,
    *,
    chatbot_configuracion_id: Optional[int] = None,
    incluir_globales: bool = True,
    campania_id: Optional[int] = None,
    tipo: Optional[str] = None,
    solo_activos: bool = True,
    solo_vigentes: bool = False,
    cur=None,
) -> List[Dict[str, Any]]:
    where: List[str] = []
    params: List[Any] = []

    if chatbot_configuracion_id is not None:
        if incluir_globales:
            where.append(
                "(chatbot_configuracion_id = %s OR chatbot_configuracion_id IS NULL)"
            )
        else:
            where.append("chatbot_configuracion_id = %s")
        params.append(chatbot_configuracion_id)
    if campania_id is not None:
        where.append("(campania_id = %s OR campania_id IS NULL)")
        params.append(campania_id)
    if tipo:
        where.append("tipo = %s")
        params.append(str(tipo).strip().lower())
    if solo_activos:
        where.append("activo = TRUE")
    if solo_vigentes:
        where.append("(fecha_inicio IS NULL OR fecha_inicio <= CURRENT_DATE)")
        where.append("(fecha_fin IS NULL OR fecha_fin >= CURRENT_DATE)")

    return _listar_registros(
        "beneficios",
        agencia_id,
        where_extra=where,
        params_extra=params,
        order_by="tipo ASC, nombre ASC, id ASC",
        cur=cur,
    )


def listar_beneficios_vigentes(
    agencia_id: int,
    chatbot_configuracion_id: Optional[int] = None,
    campania_id: Optional[int] = None,
    *,
    cur=None,
) -> List[Dict[str, Any]]:
    """
    Beneficios que el agente puede mencionar por sí mismo: activos, dentro de
    vigencia y con ``permitir_mencion_automatica = TRUE``.
    """
    where = [
        "activo = TRUE",
        "permitir_mencion_automatica = TRUE",
        "(fecha_inicio IS NULL OR fecha_inicio <= CURRENT_DATE)",
        "(fecha_fin IS NULL OR fecha_fin >= CURRENT_DATE)",
    ]
    params: List[Any] = []

    if chatbot_configuracion_id is not None:
        where.append("(chatbot_configuracion_id = %s OR chatbot_configuracion_id IS NULL)")
        params.append(chatbot_configuracion_id)
    else:
        where.append("chatbot_configuracion_id IS NULL")

    if campania_id is not None:
        where.append("(campania_id = %s OR campania_id IS NULL)")
        params.append(campania_id)
    else:
        where.append("campania_id IS NULL")

    return _listar_registros(
        "beneficios",
        agencia_id,
        where_extra=where,
        params_extra=params,
        order_by="campania_id NULLS LAST, tipo ASC, nombre ASC",
        cur=cur,
    )


def obtener_beneficio(agencia_id: int, beneficio_id: int, *, cur=None) -> Optional[Dict[str, Any]]:
    return _obtener_registro("beneficios", agencia_id, beneficio_id, cur=cur)


def crear_beneficio(agencia_id: int, campos: Dict[str, Any], *, cur=None) -> Dict[str, Any]:
    with _cursor(cur) as c:
        cfg = (campos or {}).get("chatbot_configuracion_id")
        if cfg:
            _exige_configuracion(agencia_id, int(cfg), cur=c)
        return _crear_registro("beneficios", agencia_id, campos, COLUMNAS_BENEFICIO, cur=c)


def actualizar_beneficio(
    agencia_id: int, beneficio_id: int, campos: Dict[str, Any], *, cur=None
) -> Optional[Dict[str, Any]]:
    return _actualizar_registro(
        "beneficios", agencia_id, beneficio_id, campos, COLUMNAS_BENEFICIO, cur=cur
    )


def eliminar_beneficio(
    agencia_id: int, beneficio_id: int, *, hard: bool = False, cur=None
) -> bool:
    return _eliminar_registro("beneficios", agencia_id, beneficio_id, hard=hard, cur=cur)


# ---------------------------------------------------------------------------
# FAQ conversacional
# ---------------------------------------------------------------------------


def listar_faqs(
    agencia_id: int,
    *,
    chatbot_configuracion_id: Optional[int] = None,
    incluir_globales: bool = True,
    categoria: Optional[str] = None,
    search: Optional[str] = None,
    solo_activos: bool = True,
    solo_vigentes: bool = False,
    cur=None,
) -> List[Dict[str, Any]]:
    where: List[str] = []
    params: List[Any] = []

    if chatbot_configuracion_id is not None:
        if incluir_globales:
            where.append(
                "(chatbot_configuracion_id = %s OR chatbot_configuracion_id IS NULL)"
            )
        else:
            where.append("chatbot_configuracion_id = %s")
        params.append(chatbot_configuracion_id)
    if categoria:
        where.append("categoria = %s")
        params.append(str(categoria).strip())
    if search:
        where.append(
            "(pregunta ILIKE %s OR COALESCE(respuesta_corta,'') ILIKE %s "
            "OR respuesta_completa ILIKE %s OR codigo ILIKE %s)"
        )
        like = f"%{str(search).strip()}%"
        params.extend([like, like, like, like])
    if solo_activos:
        where.append("activo = TRUE")
    if solo_vigentes:
        where.append("(vigencia_desde IS NULL OR vigencia_desde <= CURRENT_DATE)")
        where.append("(vigencia_hasta IS NULL OR vigencia_hasta >= CURRENT_DATE)")

    return _listar_registros(
        "faq",
        agencia_id,
        where_extra=where,
        params_extra=params,
        order_by="prioridad DESC, categoria NULLS LAST, id ASC",
        cur=cur,
    )


def obtener_faq(agencia_id: int, faq_id: int, *, cur=None) -> Optional[Dict[str, Any]]:
    return _obtener_registro("faq", agencia_id, faq_id, cur=cur)


def obtener_faq_por_codigo(
    agencia_id: int,
    codigo: str,
    *,
    chatbot_configuracion_id: Optional[int] = None,
    solo_activos: bool = True,
    cur=None,
) -> Optional[Dict[str, Any]]:
    where = ["codigo = %s", "COALESCE(chatbot_configuracion_id, 0) = %s"]
    params: List[Any] = [codigo, chatbot_configuracion_id or 0]
    if solo_activos:
        where.append("activo = TRUE")
    filas = _listar_registros(
        "faq",
        agencia_id,
        where_extra=where,
        params_extra=params,
        order_by="id DESC",
        limit=1,
        cur=cur,
    )
    return filas[0] if filas else None


def crear_faq(agencia_id: int, campos: Dict[str, Any], *, cur=None) -> Dict[str, Any]:
    with _cursor(cur) as c:
        cfg = (campos or {}).get("chatbot_configuracion_id")
        if cfg:
            _exige_configuracion(agencia_id, int(cfg), cur=c)
        return _crear_registro("faq", agencia_id, campos, COLUMNAS_FAQ, cur=c)


def actualizar_faq(
    agencia_id: int, faq_id: int, campos: Dict[str, Any], *, cur=None
) -> Optional[Dict[str, Any]]:
    return _actualizar_registro("faq", agencia_id, faq_id, campos, COLUMNAS_FAQ, cur=cur)


def eliminar_faq(agencia_id: int, faq_id: int, *, hard: bool = False, cur=None) -> bool:
    return _eliminar_registro("faq", agencia_id, faq_id, hard=hard, cur=cur)


def buscar_faqs_por_texto(
    agencia_id: int,
    texto: str,
    *,
    chatbot_configuracion_id: Optional[int] = None,
    limit: int = 5,
    cur=None,
) -> List[Dict[str, Any]]:
    """Búsqueda full-text en español para alimentar el contexto del agente."""
    consulta = str(texto or "").strip()
    if not consulta:
        return []

    where = ["f.agencia_id = %s", "f.activo = TRUE"]
    params: List[Any] = [agencia_id]
    if chatbot_configuracion_id is not None:
        where.append(
            "(f.chatbot_configuracion_id = %s OR f.chatbot_configuracion_id IS NULL)"
        )
        params.append(chatbot_configuracion_id)
    where.append("(f.vigencia_desde IS NULL OR f.vigencia_desde <= CURRENT_DATE)")
    where.append("(f.vigencia_hasta IS NULL OR f.vigencia_hasta >= CURRENT_DATE)")
    params.extend([consulta, consulta, _limite(limit, defecto=5, maximo=50)])

    with _cursor(cur) as c:
        c.execute(
            f"""
            SELECT f.*,
                   ts_rank(
                       to_tsvector(
                           'spanish',
                           COALESCE(f.pregunta,'') || ' ' ||
                           COALESCE(f.respuesta_corta,'') || ' ' ||
                           COALESCE(f.respuesta_completa,'')
                       ),
                       plainto_tsquery('spanish', %s)
                   ) AS relevancia
            FROM chatbot.faq_conversacional f
            WHERE {' AND '.join(where)}
              AND (
                  to_tsvector(
                      'spanish',
                      COALESCE(f.pregunta,'') || ' ' ||
                      COALESCE(f.respuesta_corta,'') || ' ' ||
                      COALESCE(f.respuesta_completa,'')
                  ) @@ plainto_tsquery('spanish', %s)
              )
            ORDER BY relevancia DESC, f.prioridad DESC, f.id ASC
            LIMIT %s
            """,
            params,
        )
        return _filas(c.fetchall())


def importar_faqs_desde_json(
    agencia_id: int,
    chatbot_configuracion_id: Optional[int],
    faqs_json: Any,
    *,
    cur=None,
) -> int:
    """
    Importa el JSON legado ``preguntas_frecuentes`` a ``faq_conversacional``.

    Idempotente por ``codigo``: las FAQ ya existentes en el mismo alcance no se
    duplican ni se sobrescriben. Devuelve cuántas se insertaron.
    """
    if isinstance(faqs_json, str):
        try:
            faqs_json = json.loads(faqs_json)
        except (TypeError, ValueError):
            faqs_json = []
    if not isinstance(faqs_json, list):
        return 0

    candidatos: List[Dict[str, Any]] = []
    vistos: set = set()
    for indice, item in enumerate(faqs_json):
        if not isinstance(item, dict):
            continue
        pregunta = str(item.get("titulo") or item.get("pregunta") or "").strip()
        respuesta = str(item.get("respuesta") or item.get("respuesta_completa") or "").strip()
        if not pregunta or not respuesta:
            continue
        codigo = _slug_codigo(item.get("codigo") or item.get("id") or pregunta, f"faq_{indice + 1}")
        if codigo in vistos:
            continue
        vistos.add(codigo)
        try:
            orden = int(item.get("orden") or (indice + 1))
        except (TypeError, ValueError):
            orden = indice + 1
        candidatos.append(
            {
                "codigo": codigo,
                "pregunta": pregunta[:2000],
                "respuesta_corta": respuesta[:300],
                "respuesta_completa": respuesta,
                "prioridad": max(0, min(100, 100 - orden)),
                "activo": bool(item.get("activo", True)),
                "fuente": "preguntas_frecuentes_json",
            }
        )

    if not candidatos:
        return 0

    insertadas = 0
    with _cursor(cur) as c:
        c.execute(
            """
            SELECT codigo
            FROM chatbot.faq_conversacional
            WHERE agencia_id = %s
              AND COALESCE(chatbot_configuracion_id, 0) = %s
              AND codigo = ANY(%s)
            """,
            (agencia_id, chatbot_configuracion_id or 0, [x["codigo"] for x in candidatos]),
        )
        existentes = {r["codigo"] for r in (c.fetchall() or [])}

        for faq in candidatos:
            if faq["codigo"] in existentes:
                continue
            c.execute(
                """
                INSERT INTO chatbot.faq_conversacional (
                    agencia_id, chatbot_configuracion_id, codigo, pregunta,
                    respuesta_corta, respuesta_completa, prioridad, activo, fuente
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    agencia_id,
                    chatbot_configuracion_id,
                    faq["codigo"],
                    faq["pregunta"],
                    faq["respuesta_corta"],
                    faq["respuesta_completa"],
                    faq["prioridad"],
                    faq["activo"],
                    faq["fuente"],
                ),
            )
            if c.fetchone():
                insertadas += 1

    logger.info(
        "[CONVERSACIONAL] import FAQs agencia_id=%s config_id=%s insertadas=%s",
        agencia_id,
        chatbot_configuracion_id,
        insertadas,
    )
    return insertadas


# ---------------------------------------------------------------------------
# Menú informativo
# ---------------------------------------------------------------------------

# Menú mínimo: FAQ es conocimiento interno (pregunta libre), no opción aparte.
OPCIONES_MENU_INFORMATIVO_DEFECTO: Tuple[Dict[str, Any], ...] = (
    {
        "numero": 1,
        "codigo": "requisitos",
        "titulo": "Requisitos para ser creador LIVE",
        "descripcion": "Conoce los requisitos vigentes para unirte.",
        "intencion": "requisitos",
        "tipo_fuente": "requisitos",
        "requiere_asesor": False,
        "orden": 1,
        "activo": True,
    },
    {
        "numero": 2,
        "codigo": "beneficios_bonos",
        "titulo": "Beneficios y bonos",
        "descripcion": "Ventajas, bonos e incentivos de la agencia.",
        "intencion": "beneficios",
        "tipo_fuente": "beneficios",
        "requiere_asesor": False,
        "orden": 2,
        "activo": True,
    },
    {
        "numero": 3,
        "codigo": "como_funciona",
        "titulo": "Cómo funciona la agencia",
        "descripcion": "Funcionamiento general y acompañamiento.",
        "intencion": "agencia",
        "tipo_fuente": "faq",
        "requiere_asesor": False,
        "orden": 3,
        "activo": True,
    },
    {
        "numero": 4,
        "codigo": "asesor",
        "titulo": "Hablar con un asesor",
        "descripcion": "Solicitar contacto de una persona del equipo.",
        "intencion": "asesor",
        "tipo_fuente": "asesor",
        "requiere_asesor": True,
        "orden": 4,
        "activo": True,
    },
)


def asegurar_menu_informativo_base(
    agencia_id: int,
    chatbot_configuracion_id: int,
    *,
    cur=None,
) -> Dict[str, Any]:
    """
    Inserta las opciones base del menú informativo si la config no tiene ninguna.

    Si ya hay opciones, solo desactiva «Otras preguntas» históricas (compatibilidad)
    sin tocar el resto de la configuración del cliente.
    """
    with _cursor(cur) as c:
        _exige_configuracion(agencia_id, int(chatbot_configuracion_id), cur=c)
        existentes = listar_menu_informativo(
            agencia_id,
            chatbot_configuracion_id=int(chatbot_configuracion_id),
            solo_activas=False,
            cur=c,
        )
        if not existentes:
            creadas: List[Dict[str, Any]] = []
            for plantilla in OPCIONES_MENU_INFORMATIVO_DEFECTO:
                campos = dict(plantilla)
                campos["chatbot_configuracion_id"] = int(chatbot_configuracion_id)
                creadas.append(crear_menu_informativo(agencia_id, campos, cur=c))

            logger.info(
                "[CHATBOT_MENU] seed agencia_id=%s config_id=%s insertadas=%s",
                agencia_id,
                chatbot_configuracion_id,
                len(creadas),
            )
            return {
                "insertadas": len(creadas),
                "total": len(creadas),
                "opciones": creadas,
            }

        # Compatibilidad: ocultar «Otras preguntas» del menú (FAQ es conocimiento interno).
        desactivadas = 0
        for o in existentes:
            if (
                str(o.get("codigo") or "").strip().lower() == "otras_preguntas"
                and o.get("activo") is not False
                and o.get("id")
            ):
                actualizar_menu_informativo(
                    agencia_id, int(o["id"]), {"activo": False}, cur=c
                )
                desactivadas += 1

        if desactivadas:
            logger.info(
                "[CHATBOT_MENU] desactivar otras_preguntas agencia_id=%s "
                "config_id=%s desactivadas=%s",
                agencia_id,
                chatbot_configuracion_id,
                desactivadas,
            )
            existentes = listar_menu_informativo(
                agencia_id,
                chatbot_configuracion_id=int(chatbot_configuracion_id),
                solo_activas=False,
                cur=c,
            )

        return {
            "insertadas": 0,
            "desactivadas": desactivadas,
            "total": len(existentes),
            "opciones": existentes,
        }


def listar_menu_informativo(
    agencia_id: int,
    *,
    chatbot_configuracion_id: Optional[int] = None,
    solo_activas: bool = True,
    cur=None,
) -> List[Dict[str, Any]]:
    where: List[str] = []
    params: List[Any] = []
    if chatbot_configuracion_id is not None:
        where.append("chatbot_configuracion_id = %s")
        params.append(int(chatbot_configuracion_id))
    if solo_activas:
        where.append("activo = TRUE")
    return _listar_registros(
        "menu_informativo",
        agencia_id,
        where_extra=where,
        params_extra=params,
        order_by="orden ASC, numero ASC, id ASC",
        cur=cur,
    )


def obtener_menu_informativo(
    agencia_id: int, opcion_id: int, *, cur=None
) -> Optional[Dict[str, Any]]:
    return _obtener_registro("menu_informativo", agencia_id, opcion_id, cur=cur)


def crear_menu_informativo(
    agencia_id: int, campos: Dict[str, Any], *, cur=None
) -> Dict[str, Any]:
    with _cursor(cur) as c:
        cfg = (campos or {}).get("chatbot_configuracion_id")
        if cfg:
            _exige_configuracion(agencia_id, int(cfg), cur=c)
        return _crear_registro(
            "menu_informativo", agencia_id, campos, COLUMNAS_MENU_INFORMATIVO, cur=c
        )


def actualizar_menu_informativo(
    agencia_id: int, opcion_id: int, campos: Dict[str, Any], *, cur=None
) -> Optional[Dict[str, Any]]:
    return _actualizar_registro(
        "menu_informativo",
        agencia_id,
        opcion_id,
        campos,
        COLUMNAS_MENU_INFORMATIVO,
        cur=cur,
    )


def eliminar_menu_informativo(
    agencia_id: int, opcion_id: int, *, hard: bool = False, cur=None
) -> bool:
    return _eliminar_registro(
        "menu_informativo", agencia_id, opcion_id, hard=hard, cur=cur
    )


def reordenar_menu_informativo(
    agencia_id: int,
    chatbot_configuracion_id: int,
    orden_ids: Sequence[int],
    *,
    cur=None,
) -> List[Dict[str, Any]]:
    ids = [int(x) for x in (orden_ids or [])]
    if not ids:
        raise ErrorDatosConversacional("Debe enviar al menos una opción para reordenar")
    with _cursor(cur) as c:
        _exige_configuracion(agencia_id, int(chatbot_configuracion_id), cur=c)
        for idx, oid in enumerate(ids, start=1):
            c.execute(
                """
                UPDATE chatbot.menu_informativo_opciones
                SET orden = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND agencia_id = %s AND chatbot_configuracion_id = %s
                """,
                (idx, oid, agencia_id, chatbot_configuracion_id),
            )
    return listar_menu_informativo(
        agencia_id,
        chatbot_configuracion_id=chatbot_configuracion_id,
        solo_activas=False,
        cur=cur,
    )


# ---------------------------------------------------------------------------
# Flujos conversacionales
# ---------------------------------------------------------------------------


def listar_flujos(
    agencia_id: int,
    *,
    chatbot_configuracion_id: Optional[int] = None,
    tipo_flujo: Optional[str] = None,
    nivel_objetivo: Optional[str] = None,
    solo_activos: bool = True,
    cur=None,
) -> List[Dict[str, Any]]:
    where: List[str] = []
    params: List[Any] = []
    if chatbot_configuracion_id is not None:
        where.append("chatbot_configuracion_id = %s")
        params.append(chatbot_configuracion_id)
    if tipo_flujo:
        where.append("tipo_flujo = %s")
        params.append(str(tipo_flujo).strip().lower())
    if nivel_objetivo:
        where.append("nivel_objetivo = %s")
        params.append(str(nivel_objetivo).strip().lower())
    if solo_activos:
        where.append("activo = TRUE")

    return _listar_registros(
        "flujos",
        agencia_id,
        where_extra=where,
        params_extra=params,
        order_by="tipo_flujo ASC, nombre ASC, id ASC",
        cur=cur,
    )


def obtener_flujo_por_nivel(
    agencia_id: int,
    chatbot_configuracion_id: int,
    *,
    nivel: str,
    tipo_flujo: str = "conversion",
    cur=None,
) -> Optional[Dict[str, Any]]:
    """principiante/experimentado con fallback a general."""
    nivel_n = str(nivel or "").strip().lower()
    for candidato in (nivel_n, "general"):
        if not candidato:
            continue
        filas = listar_flujos(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            tipo_flujo=tipo_flujo,
            nivel_objetivo=candidato,
            solo_activos=True,
            cur=cur,
        )
        if filas:
            return filas[0]
    # Último recurso: cualquier flujo conversion activo
    filas = listar_flujos(
        agencia_id,
        chatbot_configuracion_id=chatbot_configuracion_id,
        tipo_flujo=tipo_flujo,
        solo_activos=True,
        cur=cur,
    )
    return filas[0] if filas else None


# alias histórico (firma original sin nivel_objetivo) — listar_flujos ya extendido



def obtener_flujo(agencia_id: int, flujo_id: int, *, cur=None) -> Optional[Dict[str, Any]]:
    return _obtener_registro("flujos", agencia_id, flujo_id, cur=cur)


def obtener_flujo_por_codigo(
    agencia_id: int,
    chatbot_configuracion_id: int,
    codigo: str,
    *,
    cur=None,
) -> Optional[Dict[str, Any]]:
    filas = _listar_registros(
        "flujos",
        agencia_id,
        where_extra=["chatbot_configuracion_id = %s", "codigo = %s"],
        params_extra=[chatbot_configuracion_id, codigo],
        order_by="id DESC",
        limit=1,
        cur=cur,
    )
    return filas[0] if filas else None


def obtener_flujo_con_pasos(
    agencia_id: int,
    flujo_id: int,
    *,
    solo_pasos_activos: bool = True,
    cur=None,
) -> Optional[Dict[str, Any]]:
    with _cursor(cur) as c:
        flujo = _obtener_registro("flujos", agencia_id, flujo_id, cur=c)
        if not flujo:
            return None
        flujo["pasos"] = listar_flujo_pasos(
            agencia_id, flujo_id, solo_activos=solo_pasos_activos, cur=c
        )
        return flujo


def crear_flujo(agencia_id: int, campos: Dict[str, Any], *, cur=None) -> Dict[str, Any]:
    cfg = (campos or {}).get("chatbot_configuracion_id")
    if not cfg:
        raise ErrorDatosConversacional("chatbot_configuracion_id es obligatorio para el flujo")
    with _cursor(cur) as c:
        _exige_configuracion(agencia_id, int(cfg), cur=c)
        return _crear_registro("flujos", agencia_id, campos, COLUMNAS_FLUJO, cur=c)


def actualizar_flujo(
    agencia_id: int, flujo_id: int, campos: Dict[str, Any], *, cur=None
) -> Optional[Dict[str, Any]]:
    return _actualizar_registro("flujos", agencia_id, flujo_id, campos, COLUMNAS_FLUJO, cur=cur)


def eliminar_flujo(agencia_id: int, flujo_id: int, *, hard: bool = False, cur=None) -> bool:
    return _eliminar_registro("flujos", agencia_id, flujo_id, hard=hard, cur=cur)


# ---------------------------------------------------------------------------
# Pasos de flujo
# ---------------------------------------------------------------------------


def listar_flujo_pasos(
    agencia_id: int,
    flujo_id: int,
    *,
    solo_activos: bool = True,
    cur=None,
) -> List[Dict[str, Any]]:
    where = ["flujo_id = %s"]
    params: List[Any] = [flujo_id]
    if solo_activos:
        where.append("activo = TRUE")
    return _listar_registros(
        "flujo_pasos",
        agencia_id,
        where_extra=where,
        params_extra=params,
        order_by="orden ASC, id ASC",
        cur=cur,
    )


def obtener_flujo_paso(agencia_id: int, paso_id: int, *, cur=None) -> Optional[Dict[str, Any]]:
    return _obtener_registro("flujo_pasos", agencia_id, paso_id, cur=cur)


def _siguiente_orden_paso(cur, agencia_id: int, flujo_id: int) -> int:
    cur.execute(
        """
        SELECT COALESCE(MAX(orden), -1) + 1 AS siguiente
        FROM chatbot.flujo_pasos
        WHERE agencia_id = %s AND flujo_id = %s
        """,
        (agencia_id, flujo_id),
    )
    row = cur.fetchone() or {}
    return int(row.get("siguiente") or 0)


def crear_flujo_paso(agencia_id: int, campos: Dict[str, Any], *, cur=None) -> Dict[str, Any]:
    datos = dict(campos or {})
    flujo_id = datos.get("flujo_id")
    if not flujo_id:
        raise ErrorDatosConversacional("flujo_id es obligatorio para el paso")

    with _cursor(cur) as c:
        if not _obtener_registro("flujos", agencia_id, int(flujo_id), cur=c):
            raise ErrorDatosConversacional("El flujo no existe o no pertenece a la agencia")
        if datos.get("orden") is None:
            datos["orden"] = _siguiente_orden_paso(c, agencia_id, int(flujo_id))
        return _crear_registro("flujo_pasos", agencia_id, datos, COLUMNAS_FLUJO_PASO, cur=c)


def actualizar_flujo_paso(
    agencia_id: int, paso_id: int, campos: Dict[str, Any], *, cur=None
) -> Optional[Dict[str, Any]]:
    return _actualizar_registro(
        "flujo_pasos", agencia_id, paso_id, campos, COLUMNAS_FLUJO_PASO, cur=cur
    )


def eliminar_flujo_paso(agencia_id: int, paso_id: int, *, hard: bool = False, cur=None) -> bool:
    return _eliminar_registro("flujo_pasos", agencia_id, paso_id, hard=hard, cur=cur)


def mover_flujo_paso(
    agencia_id: int,
    flujo_id: int,
    paso_id: int,
    direccion: str,
    *,
    cur=None,
) -> List[Dict[str, Any]]:
    """
    Intercambia el paso con su vecino inmediato.

    ``(flujo_id, orden)`` es único, así que el intercambio pasa por un orden
    temporal libre (max+1) para no violar la restricción.
    """
    dir_norm = str(direccion or "").strip().lower()
    if dir_norm not in {"subir", "bajar"}:
        raise ErrorDatosConversacional("direccion debe ser 'subir' o 'bajar'")

    with _cursor(cur) as c:
        c.execute(
            """
            SELECT id, orden
            FROM chatbot.flujo_pasos
            WHERE agencia_id = %s AND flujo_id = %s
            ORDER BY orden ASC
            FOR UPDATE
            """,
            (agencia_id, flujo_id),
        )
        pasos = _filas(c.fetchall())
        if not pasos:
            raise ErrorDatosConversacional("El flujo no tiene pasos o no pertenece a la agencia")

        actual = next((p for p in pasos if int(p["id"]) == int(paso_id)), None)
        if not actual:
            raise ErrorDatosConversacional("El paso no pertenece al flujo indicado")

        indice = pasos.index(actual)
        vecino_idx = indice - 1 if dir_norm == "subir" else indice + 1
        if vecino_idx < 0 or vecino_idx >= len(pasos):
            return listar_flujo_pasos(agencia_id, flujo_id, solo_activos=False, cur=c)
        vecino = pasos[vecino_idx]

        temporal = max(int(p["orden"]) for p in pasos) + 1
        for pid, orden in (
            (actual["id"], temporal),
            (vecino["id"], actual["orden"]),
            (actual["id"], vecino["orden"]),
        ):
            c.execute(
                """
                UPDATE chatbot.flujo_pasos
                SET orden = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND agencia_id = %s AND flujo_id = %s
                """,
                (orden, pid, agencia_id, flujo_id),
            )

        return listar_flujo_pasos(agencia_id, flujo_id, solo_activos=False, cur=c)


def subir_flujo_paso(agencia_id: int, flujo_id: int, paso_id: int, *, cur=None) -> List[Dict[str, Any]]:
    return mover_flujo_paso(agencia_id, flujo_id, paso_id, "subir", cur=cur)


def bajar_flujo_paso(agencia_id: int, flujo_id: int, paso_id: int, *, cur=None) -> List[Dict[str, Any]]:
    return mover_flujo_paso(agencia_id, flujo_id, paso_id, "bajar", cur=cur)


def reordenar_flujo_pasos(
    agencia_id: int,
    flujo_id: int,
    orden_ids: Sequence[int],
    *,
    cur=None,
) -> List[Dict[str, Any]]:
    """Reasigna el orden completo según la secuencia de ids recibida."""
    ids = [int(x) for x in (orden_ids or [])]
    if not ids:
        raise ErrorDatosConversacional("Debe enviar al menos un paso para reordenar")

    with _cursor(cur) as c:
        c.execute(
            """
            SELECT id, orden
            FROM chatbot.flujo_pasos
            WHERE agencia_id = %s AND flujo_id = %s
            ORDER BY orden ASC
            FOR UPDATE
            """,
            (agencia_id, flujo_id),
        )
        pasos = _filas(c.fetchall())
        existentes = {int(p["id"]) for p in pasos}
        if not existentes:
            raise ErrorDatosConversacional("El flujo no tiene pasos o no pertenece a la agencia")
        if set(ids) - existentes:
            raise ErrorDatosConversacional("Algún paso enviado no pertenece al flujo")

        base = max(int(p["orden"]) for p in pasos) + 1
        for desplazamiento, paso_id in enumerate(ids):
            c.execute(
                """
                UPDATE chatbot.flujo_pasos
                SET orden = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND agencia_id = %s AND flujo_id = %s
                """,
                (base + desplazamiento, paso_id, agencia_id, flujo_id),
            )
        for posicion, paso_id in enumerate(ids):
            c.execute(
                """
                UPDATE chatbot.flujo_pasos
                SET orden = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND agencia_id = %s AND flujo_id = %s
                """,
                (posicion, paso_id, agencia_id, flujo_id),
            )

        return listar_flujo_pasos(agencia_id, flujo_id, solo_activos=False, cur=c)


# ---------------------------------------------------------------------------
# Campañas de captación
# ---------------------------------------------------------------------------


def listar_campanias(
    agencia_id: int,
    *,
    chatbot_configuracion_id: Optional[int] = None,
    canal_origen: Optional[str] = None,
    plataforma_codigo: Optional[str] = None,
    search: Optional[str] = None,
    solo_activas: bool = True,
    solo_vigentes: bool = False,
    cur=None,
) -> List[Dict[str, Any]]:
    where: List[str] = []
    params: List[Any] = []
    if chatbot_configuracion_id is not None:
        where.append("chatbot_configuracion_id = %s")
        params.append(chatbot_configuracion_id)
    if canal_origen:
        where.append("canal_origen = %s")
        params.append(str(canal_origen).strip().lower())
    if plataforma_codigo:
        where.append("plataforma_codigo = %s")
        params.append(str(plataforma_codigo).strip().lower())
    if search:
        where.append(
            "(nombre ILIKE %s OR codigo ILIKE %s OR COALESCE(identificador_externo,'') ILIKE %s)"
        )
        like = f"%{str(search).strip()}%"
        params.extend([like, like, like])
    if solo_activas:
        where.append("activo = TRUE")
    if solo_vigentes:
        where.append("(fecha_inicio IS NULL OR fecha_inicio <= CURRENT_DATE)")
        where.append("(fecha_fin IS NULL OR fecha_fin >= CURRENT_DATE)")

    return _listar_registros(
        "campanias",
        agencia_id,
        where_extra=where,
        params_extra=params,
        order_by="created_at DESC, id DESC",
        cur=cur,
    )


def obtener_campania(agencia_id: int, campania_id: int, *, cur=None) -> Optional[Dict[str, Any]]:
    return _obtener_registro("campanias", agencia_id, campania_id, cur=cur)


def obtener_campania_por_codigo(
    agencia_id: int, codigo: str, *, cur=None
) -> Optional[Dict[str, Any]]:
    filas = _listar_registros(
        "campanias",
        agencia_id,
        where_extra=["codigo = %s"],
        params_extra=[codigo],
        order_by="id DESC",
        limit=1,
        cur=cur,
    )
    return filas[0] if filas else None


def buscar_campania_por_identificador(
    agencia_id: int,
    identificador_externo: str,
    canal_origen: str,
    *,
    solo_activas: bool = True,
    solo_vigentes: bool = True,
    cur=None,
) -> Optional[Dict[str, Any]]:
    """Resuelve la campaña de un click-to-message (ads) por su identificador."""
    identificador = str(identificador_externo or "").strip()
    canal = str(canal_origen or "").strip().lower()
    if not identificador or not canal:
        return None

    where = ["identificador_externo = %s", "canal_origen = %s"]
    params: List[Any] = [identificador, canal]
    if solo_activas:
        where.append("activo = TRUE")
    if solo_vigentes:
        where.append("(fecha_inicio IS NULL OR fecha_inicio <= CURRENT_DATE)")
        where.append("(fecha_fin IS NULL OR fecha_fin >= CURRENT_DATE)")

    filas = _listar_registros(
        "campanias",
        agencia_id,
        where_extra=where,
        params_extra=params,
        order_by="id DESC",
        limit=1,
        cur=cur,
    )
    return filas[0] if filas else None


def crear_campania(agencia_id: int, campos: Dict[str, Any], *, cur=None) -> Dict[str, Any]:
    cfg = (campos or {}).get("chatbot_configuracion_id")
    if not cfg:
        raise ErrorDatosConversacional("chatbot_configuracion_id es obligatorio para la campaña")
    with _cursor(cur) as c:
        _exige_configuracion(agencia_id, int(cfg), cur=c)
        flujo_id = (campos or {}).get("flujo_id")
        if flujo_id and not _obtener_registro("flujos", agencia_id, int(flujo_id), cur=c):
            raise ErrorDatosConversacional("El flujo no existe o no pertenece a la agencia")
        return _crear_registro("campanias", agencia_id, campos, COLUMNAS_CAMPANIA, cur=c)


def actualizar_campania(
    agencia_id: int, campania_id: int, campos: Dict[str, Any], *, cur=None
) -> Optional[Dict[str, Any]]:
    return _actualizar_registro(
        "campanias", agencia_id, campania_id, campos, COLUMNAS_CAMPANIA, cur=cur
    )


def eliminar_campania(agencia_id: int, campania_id: int, *, hard: bool = False, cur=None) -> bool:
    return _eliminar_registro("campanias", agencia_id, campania_id, hard=hard, cur=cur)


# ---------------------------------------------------------------------------
# Recursos y enlaces
# ---------------------------------------------------------------------------


def listar_recursos(
    agencia_id: int,
    *,
    chatbot_configuracion_id: Optional[int] = None,
    incluir_globales: bool = True,
    campania_id: Optional[int] = None,
    tipo: Optional[str] = None,
    solo_activos: bool = True,
    solo_vigentes: bool = False,
    cur=None,
) -> List[Dict[str, Any]]:
    where: List[str] = []
    params: List[Any] = []
    if chatbot_configuracion_id is not None:
        if incluir_globales:
            where.append(
                "(chatbot_configuracion_id = %s OR chatbot_configuracion_id IS NULL)"
            )
        else:
            where.append("chatbot_configuracion_id = %s")
        params.append(chatbot_configuracion_id)
    if campania_id is not None:
        where.append("(campania_id = %s OR campania_id IS NULL)")
        params.append(campania_id)
    if tipo:
        where.append("tipo = %s")
        params.append(str(tipo).strip().lower())
    if solo_activos:
        where.append("activo = TRUE")
    if solo_vigentes:
        where.append("(vigencia_desde IS NULL OR vigencia_desde <= CURRENT_DATE)")
        where.append("(vigencia_hasta IS NULL OR vigencia_hasta >= CURRENT_DATE)")

    return _listar_registros(
        "recursos",
        agencia_id,
        where_extra=where,
        params_extra=params,
        order_by="tipo ASC, nombre ASC, id ASC",
        cur=cur,
    )


def obtener_recurso(agencia_id: int, recurso_id: int, *, cur=None) -> Optional[Dict[str, Any]]:
    return _obtener_registro("recursos", agencia_id, recurso_id, cur=cur)


def obtener_recurso_por_codigo(
    agencia_id: int,
    codigo: str,
    *,
    chatbot_configuracion_id: Optional[int] = None,
    campania_id: Optional[int] = None,
    cur=None,
) -> Optional[Dict[str, Any]]:
    filas = _listar_registros(
        "recursos",
        agencia_id,
        where_extra=[
            "codigo = %s",
            "COALESCE(chatbot_configuracion_id, 0) = %s",
            "COALESCE(campania_id, 0) = %s",
            "activo = TRUE",
        ],
        params_extra=[codigo, chatbot_configuracion_id or 0, campania_id or 0],
        order_by="id DESC",
        limit=1,
        cur=cur,
    )
    if filas:
        return filas[0]

    # Fallback: mismo código en la agencia (config/campaña pueden no coincidir exactamente).
    if chatbot_configuracion_id or campania_id:
        filas = _listar_registros(
            "recursos",
            agencia_id,
            where_extra=["codigo = %s", "activo = TRUE"],
            params_extra=[codigo],
            order_by="id DESC",
            limit=5,
            cur=cur,
        )
        if not filas:
            return None
        if chatbot_configuracion_id:
            for fila in filas:
                if int(fila.get("chatbot_configuracion_id") or 0) == int(
                    chatbot_configuracion_id
                ):
                    return fila
        return filas[0]
    return None


def crear_recurso(agencia_id: int, campos: Dict[str, Any], *, cur=None) -> Dict[str, Any]:
    with _cursor(cur) as c:
        cfg = (campos or {}).get("chatbot_configuracion_id")
        if cfg:
            _exige_configuracion(agencia_id, int(cfg), cur=c)
        return _crear_registro("recursos", agencia_id, campos, COLUMNAS_RECURSO, cur=c)


def actualizar_recurso(
    agencia_id: int, recurso_id: int, campos: Dict[str, Any], *, cur=None
) -> Optional[Dict[str, Any]]:
    return _actualizar_registro(
        "recursos", agencia_id, recurso_id, campos, COLUMNAS_RECURSO, cur=cur
    )


def eliminar_recurso(agencia_id: int, recurso_id: int, *, hard: bool = False, cur=None) -> bool:
    return _eliminar_registro("recursos", agencia_id, recurso_id, hard=hard, cur=cur)


# ---------------------------------------------------------------------------
# Pruebas LIVE y evidencias requeridas
# ---------------------------------------------------------------------------


def listar_pruebas_live(
    agencia_id: int,
    *,
    flujo_id: Optional[int] = None,
    campania_id: Optional[int] = None,
    solo_activas: bool = True,
    cur=None,
) -> List[Dict[str, Any]]:
    where: List[str] = []
    params: List[Any] = []
    if flujo_id is not None:
        where.append("flujo_id = %s")
        params.append(flujo_id)
    if campania_id is not None:
        where.append("(campania_id = %s OR campania_id IS NULL)")
        params.append(campania_id)
    if solo_activas:
        where.append("activo = TRUE")

    return _listar_registros(
        "pruebas_live",
        agencia_id,
        where_extra=where,
        params_extra=params,
        order_by="nombre ASC, id ASC",
        cur=cur,
    )


def obtener_prueba_live(agencia_id: int, prueba_id: int, *, cur=None) -> Optional[Dict[str, Any]]:
    return _obtener_registro("pruebas_live", agencia_id, prueba_id, cur=cur)


def obtener_prueba_live_con_evidencias(
    agencia_id: int,
    prueba_id: int,
    *,
    solo_activas: bool = True,
    cur=None,
) -> Optional[Dict[str, Any]]:
    with _cursor(cur) as c:
        prueba = _obtener_registro("pruebas_live", agencia_id, prueba_id, cur=c)
        if not prueba:
            return None
        prueba["evidencias_requeridas"] = listar_evidencias_requeridas(
            agencia_id, prueba_id, solo_activas=solo_activas, cur=c
        )
        return prueba


def crear_prueba_live(agencia_id: int, campos: Dict[str, Any], *, cur=None) -> Dict[str, Any]:
    flujo_id = (campos or {}).get("flujo_id")
    if not flujo_id:
        raise ErrorDatosConversacional("flujo_id es obligatorio para la prueba LIVE")
    with _cursor(cur) as c:
        if not _obtener_registro("flujos", agencia_id, int(flujo_id), cur=c):
            raise ErrorDatosConversacional("El flujo no existe o no pertenece a la agencia")
        return _crear_registro("pruebas_live", agencia_id, campos, COLUMNAS_PRUEBA_LIVE, cur=c)


def actualizar_prueba_live(
    agencia_id: int, prueba_id: int, campos: Dict[str, Any], *, cur=None
) -> Optional[Dict[str, Any]]:
    return _actualizar_registro(
        "pruebas_live", agencia_id, prueba_id, campos, COLUMNAS_PRUEBA_LIVE, cur=cur
    )


def eliminar_prueba_live(agencia_id: int, prueba_id: int, *, hard: bool = False, cur=None) -> bool:
    return _eliminar_registro("pruebas_live", agencia_id, prueba_id, hard=hard, cur=cur)


def listar_evidencias_requeridas(
    agencia_id: int,
    prueba_live_id: int,
    *,
    solo_activas: bool = True,
    cur=None,
) -> List[Dict[str, Any]]:
    where = ["prueba_live_id = %s"]
    params: List[Any] = [prueba_live_id]
    if solo_activas:
        where.append("activo = TRUE")
    return _listar_registros(
        "evidencias_requeridas",
        agencia_id,
        where_extra=where,
        params_extra=params,
        order_by="orden ASC, id ASC",
        cur=cur,
    )


def obtener_evidencia_requerida(
    agencia_id: int, evidencia_requerida_id: int, *, cur=None
) -> Optional[Dict[str, Any]]:
    return _obtener_registro("evidencias_requeridas", agencia_id, evidencia_requerida_id, cur=cur)


def crear_evidencia_requerida(
    agencia_id: int, campos: Dict[str, Any], *, cur=None
) -> Dict[str, Any]:
    prueba_id = (campos or {}).get("prueba_live_id")
    if not prueba_id:
        raise ErrorDatosConversacional("prueba_live_id es obligatorio")
    with _cursor(cur) as c:
        if not _obtener_registro("pruebas_live", agencia_id, int(prueba_id), cur=c):
            raise ErrorDatosConversacional(
                "La prueba LIVE no existe o no pertenece a la agencia"
            )
        return _crear_registro(
            "evidencias_requeridas", agencia_id, campos, COLUMNAS_EVIDENCIA_REQUERIDA, cur=c
        )


def actualizar_evidencia_requerida(
    agencia_id: int, evidencia_requerida_id: int, campos: Dict[str, Any], *, cur=None
) -> Optional[Dict[str, Any]]:
    return _actualizar_registro(
        "evidencias_requeridas",
        agencia_id,
        evidencia_requerida_id,
        campos,
        COLUMNAS_EVIDENCIA_REQUERIDA,
        cur=cur,
    )


def eliminar_evidencia_requerida(
    agencia_id: int, evidencia_requerida_id: int, *, hard: bool = False, cur=None
) -> bool:
    return _eliminar_registro(
        "evidencias_requeridas", agencia_id, evidencia_requerida_id, hard=hard, cur=cur
    )


# ---------------------------------------------------------------------------
# Reglas de escalamiento
# ---------------------------------------------------------------------------


def listar_reglas_escalamiento(
    agencia_id: int,
    *,
    chatbot_configuracion_id: Optional[int] = None,
    incluir_globales: bool = True,
    flujo_id: Optional[int] = None,
    campania_id: Optional[int] = None,
    evento: Optional[str] = None,
    solo_activas: bool = True,
    cur=None,
) -> List[Dict[str, Any]]:
    where: List[str] = []
    params: List[Any] = []
    if chatbot_configuracion_id is not None:
        if incluir_globales:
            where.append(
                "(chatbot_configuracion_id = %s OR chatbot_configuracion_id IS NULL)"
            )
        else:
            where.append("chatbot_configuracion_id = %s")
        params.append(chatbot_configuracion_id)
    if flujo_id is not None:
        where.append("(flujo_id = %s OR flujo_id IS NULL)")
        params.append(flujo_id)
    if campania_id is not None:
        where.append("(campania_id = %s OR campania_id IS NULL)")
        params.append(campania_id)
    if evento:
        where.append("evento = %s")
        params.append(str(evento).strip())
    if solo_activas:
        where.append("activo = TRUE")

    return _listar_registros(
        "reglas_escalamiento",
        agencia_id,
        where_extra=where,
        params_extra=params,
        order_by="orden ASC, id ASC",
        cur=cur,
    )


def obtener_regla_escalamiento(
    agencia_id: int, regla_id: int, *, cur=None
) -> Optional[Dict[str, Any]]:
    return _obtener_registro("reglas_escalamiento", agencia_id, regla_id, cur=cur)


def resolver_regla_escalamiento(
    agencia_id: int,
    evento: str,
    *,
    chatbot_configuracion_id: Optional[int] = None,
    flujo_id: Optional[int] = None,
    campania_id: Optional[int] = None,
    cur=None,
) -> Optional[Dict[str, Any]]:
    """Devuelve la regla más específica que aplica al evento indicado."""
    reglas = listar_reglas_escalamiento(
        agencia_id,
        chatbot_configuracion_id=chatbot_configuracion_id,
        flujo_id=flujo_id,
        campania_id=campania_id,
        evento=evento,
        solo_activas=True,
        cur=cur,
    )
    if not reglas:
        return None

    def especificidad(regla: Dict[str, Any]) -> Tuple[int, int]:
        puntos = 0
        if regla.get("campania_id") is not None:
            puntos += 4
        if regla.get("flujo_id") is not None:
            puntos += 2
        if regla.get("chatbot_configuracion_id") is not None:
            puntos += 1
        return (-puntos, int(regla.get("orden") or 0))

    return sorted(reglas, key=especificidad)[0]


def crear_regla_escalamiento(
    agencia_id: int, campos: Dict[str, Any], *, cur=None
) -> Dict[str, Any]:
    with _cursor(cur) as c:
        cfg = (campos or {}).get("chatbot_configuracion_id")
        if cfg:
            _exige_configuracion(agencia_id, int(cfg), cur=c)
        return _crear_registro(
            "reglas_escalamiento", agencia_id, campos, COLUMNAS_REGLA_ESCALAMIENTO, cur=c
        )


def actualizar_regla_escalamiento(
    agencia_id: int, regla_id: int, campos: Dict[str, Any], *, cur=None
) -> Optional[Dict[str, Any]]:
    return _actualizar_registro(
        "reglas_escalamiento", agencia_id, regla_id, campos, COLUMNAS_REGLA_ESCALAMIENTO, cur=cur
    )


def eliminar_regla_escalamiento(
    agencia_id: int, regla_id: int, *, hard: bool = False, cur=None
) -> bool:
    return _eliminar_registro("reglas_escalamiento", agencia_id, regla_id, hard=hard, cur=cur)


# ---------------------------------------------------------------------------
# Conversaciones
# ---------------------------------------------------------------------------


def obtener_conversacion(
    agencia_id: int, conversacion_id: int, *, cur=None
) -> Optional[Dict[str, Any]]:
    return _obtener_registro("conversaciones", agencia_id, conversacion_id, cur=cur)


def obtener_conversacion_detalle(
    agencia_id: int, conversacion_id: int, *, cur=None
) -> Optional[Dict[str, Any]]:
    """Conversación con datos de campaña, flujo, paso actual y aspirante."""
    with _cursor(cur) as c:
        c.execute(
            """
            SELECT
                c.*,
                cam.nombre AS campania_nombre,
                cam.codigo AS campania_codigo,
                f.nombre AS flujo_nombre,
                f.codigo AS flujo_codigo,
                p.nombre AS paso_actual_nombre,
                p.codigo AS paso_actual_codigo,
                a.nombre AS aspirante_nombre,
                a.telefono AS aspirante_telefono,
                a.estado AS aspirante_estado,
                cfg.nombre AS configuracion_nombre,
                cfg.plataforma_codigo AS configuracion_plataforma
            FROM chatbot.conversaciones c
            LEFT JOIN chatbot.campanias_captacion cam
                ON cam.id = c.campania_id AND cam.agencia_id = c.agencia_id
            LEFT JOIN chatbot.flujos_conversacionales f
                ON f.id = c.flujo_id AND f.agencia_id = c.agencia_id
            LEFT JOIN chatbot.flujo_pasos p
                ON p.id = c.paso_actual_id AND p.agencia_id = c.agencia_id
            LEFT JOIN chatbot.chatbot_aspirantes a
                ON a.id = c.aspirante_id AND a.agencia_id = c.agencia_id
            LEFT JOIN chatbot.chatbot_configuracion cfg
                ON cfg.id = c.chatbot_configuracion_id AND cfg.agencia_id = c.agencia_id
            WHERE c.id = %s AND c.agencia_id = %s
            LIMIT 1
            """,
            (conversacion_id, agencia_id),
        )
        return _fila(c.fetchone())


def obtener_conversacion_abierta(
    agencia_id: int,
    canal: str,
    usuario_externo_id: str,
    *,
    cuenta_externa_id: Optional[str] = None,
    cur=None,
) -> Optional[Dict[str, Any]]:
    with _cursor(cur) as c:
        c.execute(
            """
            SELECT *
            FROM chatbot.conversaciones
            WHERE agencia_id = %s
              AND canal = %s
              AND COALESCE(cuenta_externa_id, '') = COALESCE(%s, '')
              AND usuario_externo_id = %s
              AND estado <> 'cerrada'
            ORDER BY id DESC
            LIMIT 1
            """,
            (agencia_id, canal, cuenta_externa_id, usuario_externo_id),
        )
        return _fila(c.fetchone())


def buscar_o_crear_conversacion(
    agencia_id: int,
    canal: str,
    usuario_externo_id: str,
    *,
    cuenta_externa_id: Optional[str] = None,
    chatbot_configuracion_id: Optional[int] = None,
    campania_id: Optional[int] = None,
    flujo_id: Optional[int] = None,
    aspirante_id: Optional[int] = None,
    plataforma_codigo: Optional[str] = None,
    conversacion_externa_id: Optional[str] = None,
    nombre_contacto: Optional[str] = None,
    telefono: Optional[str] = None,
    usuario_plataforma: Optional[str] = None,
    modo: str = "informativo",
    estado: str = "abierta",
    estado_actual: str = "inicio",
    contexto: Optional[Dict[str, Any]] = None,
    cur=None,
) -> Tuple[Dict[str, Any], bool]:
    """
    Devuelve la conversación abierta del usuario en ese canal o crea una nueva.

    La unicidad efectiva es ``(agencia_id, canal, cuenta_externa_id,
    usuario_externo_id)`` mientras la conversación no esté cerrada. Devuelve
    ``(conversacion, creada)``.
    """
    canal_norm = str(canal or "").strip().lower()
    usuario_norm = str(usuario_externo_id or "").strip()
    if not canal_norm or not usuario_norm:
        raise ErrorDatosConversacional("canal y usuario_externo_id son obligatorios")

    with _cursor(cur) as c:
        if chatbot_configuracion_id is not None:
            _exige_configuracion(agencia_id, int(chatbot_configuracion_id), cur=c)

        c.execute(
            """
            SELECT *
            FROM chatbot.conversaciones
            WHERE agencia_id = %s
              AND canal = %s
              AND COALESCE(cuenta_externa_id, '') = COALESCE(%s, '')
              AND usuario_externo_id = %s
              AND estado <> 'cerrada'
            ORDER BY id DESC
            LIMIT 1
            FOR UPDATE
            """,
            (agencia_id, canal_norm, cuenta_externa_id, usuario_norm),
        )
        existente = _fila(c.fetchone())

        if existente:
            # Completa sólo lo que aún esté vacío para no pisar el contexto vivo.
            relleno: Dict[str, Any] = {}
            candidatos = {
                "chatbot_configuracion_id": chatbot_configuracion_id,
                "campania_id": campania_id,
                "flujo_id": flujo_id,
                "aspirante_id": aspirante_id,
                "plataforma_codigo": plataforma_codigo,
                "conversacion_externa_id": conversacion_externa_id,
                "nombre_contacto": nombre_contacto,
                "telefono": telefono,
                "usuario_plataforma": usuario_plataforma,
            }
            for columna, valor in candidatos.items():
                if valor is not None and existente.get(columna) in (None, ""):
                    relleno[columna] = valor
            if relleno:
                actualizado = _actualizar_registro(
                    "conversaciones",
                    agencia_id,
                    int(existente["id"]),
                    relleno,
                    COLUMNAS_CONVERSACION,
                    cur=c,
                )
                if actualizado:
                    existente = actualizado
            return existente, False

        nueva = _crear_registro(
            "conversaciones",
            agencia_id,
            {
                "canal": canal_norm,
                "usuario_externo_id": usuario_norm,
                "cuenta_externa_id": cuenta_externa_id,
                "chatbot_configuracion_id": chatbot_configuracion_id,
                "campania_id": campania_id,
                "flujo_id": flujo_id,
                "aspirante_id": aspirante_id,
                "plataforma_codigo": plataforma_codigo,
                "conversacion_externa_id": conversacion_externa_id,
                "nombre_contacto": nombre_contacto,
                "telefono": telefono,
                "usuario_plataforma": usuario_plataforma,
                "modo": modo,
                "estado": estado,
                "estado_actual": estado_actual,
                "contexto": contexto or {},
            },
            COLUMNAS_CONVERSACION,
            cur=c,
        )
        registrar_evento(
            agencia_id,
            int(nueva["id"]),
            tipo_evento="inicio_conversacion",
            nombre_evento="conversacion_creada",
            origen="sistema",
            estado_nuevo=nueva.get("estado_actual"),
            detalle={"canal": canal_norm, "campania_id": campania_id},
            cur=c,
        )
        logger.info(
            "[CONVERSACIONAL] conversación creada id=%s agencia_id=%s canal=%s",
            nueva.get("id"),
            agencia_id,
            canal_norm,
        )
        return nueva, True


def listar_conversaciones(
    agencia_id: int,
    *,
    estado: Optional[str] = None,
    canal: Optional[str] = None,
    modo: Optional[str] = None,
    plataforma_codigo: Optional[str] = None,
    chatbot_configuracion_id: Optional[int] = None,
    campania_id: Optional[int] = None,
    flujo_id: Optional[int] = None,
    manager_id: Optional[int] = None,
    aspirante_id: Optional[int] = None,
    modo_humano: Optional[bool] = None,
    ia_habilitada: Optional[bool] = None,
    con_evidencias_pendientes: Optional[bool] = None,
    search: Optional[str] = None,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    order: str = "ultimo_mensaje_desc",
    limit: int = 20,
    offset: int = 0,
    cur=None,
) -> Tuple[List[Dict[str, Any]], int]:
    """Listado paginado de la bandeja de conversaciones. Devuelve (items, total)."""
    where = ["c.agencia_id = %s"]
    params: List[Any] = [agencia_id]

    if estado:
        where.append("c.estado = %s")
        params.append(str(estado).strip().lower())
    if canal:
        where.append("c.canal = %s")
        params.append(str(canal).strip().lower())
    if modo:
        where.append("c.modo = %s")
        params.append(str(modo).strip().lower())
    if plataforma_codigo:
        where.append("c.plataforma_codigo = %s")
        params.append(str(plataforma_codigo).strip().lower())
    if chatbot_configuracion_id is not None:
        where.append("c.chatbot_configuracion_id = %s")
        params.append(chatbot_configuracion_id)
    if campania_id is not None:
        where.append("c.campania_id = %s")
        params.append(campania_id)
    if flujo_id is not None:
        where.append("c.flujo_id = %s")
        params.append(flujo_id)
    if manager_id is not None:
        where.append("c.manager_id = %s")
        params.append(manager_id)
    if aspirante_id is not None:
        where.append("c.aspirante_id = %s")
        params.append(aspirante_id)
    if modo_humano is not None:
        where.append("c.modo_humano = %s")
        params.append(bool(modo_humano))
    if ia_habilitada is not None:
        where.append("c.ia_habilitada = %s")
        params.append(bool(ia_habilitada))
    if search:
        where.append(
            "(COALESCE(c.nombre_contacto,'') ILIKE %s OR COALESCE(c.telefono,'') ILIKE %s "
            "OR c.usuario_externo_id ILIKE %s OR COALESCE(c.usuario_plataforma,'') ILIKE %s)"
        )
        like = f"%{str(search).strip()}%"
        params.extend([like, like, like, like])
    if fecha_desde:
        where.append("c.iniciada_at::date >= %s")
        params.append(fecha_desde)
    if fecha_hasta:
        where.append("c.iniciada_at::date <= %s")
        params.append(fecha_hasta)
    if con_evidencias_pendientes is True:
        where.append(
            "EXISTS (SELECT 1 FROM chatbot.evidencias_candidato ev "
            "WHERE ev.conversacion_id = c.id AND ev.agencia_id = c.agencia_id "
            "AND ev.estado_revision = ANY(%s))"
        )
        params.append(list(ESTADOS_EVIDENCIA_PENDIENTE))

    ordenes = {
        "ultimo_mensaje_desc": "c.ultimo_mensaje_at DESC NULLS LAST, c.id DESC",
        "ultimo_mensaje_asc": "c.ultimo_mensaje_at ASC NULLS LAST, c.id ASC",
        "creada_desc": "c.iniciada_at DESC, c.id DESC",
        "creada_asc": "c.iniciada_at ASC, c.id ASC",
    }
    order_by = ordenes.get(str(order or "").strip().lower(), ordenes["ultimo_mensaje_desc"])

    page_size = _limite(limit, defecto=20, maximo=100)
    desplazamiento = _offset(offset)

    with _cursor(cur) as c:
        c.execute(
            f"""
            SELECT
                c.*,
                cam.nombre AS campania_nombre,
                f.nombre AS flujo_nombre,
                a.nombre AS aspirante_nombre,
                (
                    SELECT COUNT(*)::int
                    FROM chatbot.evidencias_candidato ev
                    WHERE ev.conversacion_id = c.id
                      AND ev.agencia_id = c.agencia_id
                      AND ev.estado_revision = ANY(%s)
                ) AS evidencias_pendientes,
                (
                    SELECT COUNT(*)::int
                    FROM chatbot.tareas_candidato t
                    WHERE t.conversacion_id = c.id
                      AND t.agencia_id = c.agencia_id
                      AND t.estado = ANY(%s)
                ) AS tareas_pendientes,
                COUNT(*) OVER()::int AS _total
            FROM chatbot.conversaciones c
            LEFT JOIN chatbot.campanias_captacion cam
                ON cam.id = c.campania_id AND cam.agencia_id = c.agencia_id
            LEFT JOIN chatbot.flujos_conversacionales f
                ON f.id = c.flujo_id AND f.agencia_id = c.agencia_id
            LEFT JOIN chatbot.chatbot_aspirantes a
                ON a.id = c.aspirante_id AND a.agencia_id = c.agencia_id
            WHERE {' AND '.join(where)}
            ORDER BY {order_by}
            LIMIT %s OFFSET %s
            """,
            [list(ESTADOS_EVIDENCIA_PENDIENTE), list(ESTADOS_TAREA_PENDIENTE)]
            + params
            + [page_size, desplazamiento],
        )
        filas = _filas(c.fetchall())

    total = int(filas[0]["_total"]) if filas else 0
    for fila in filas:
        fila.pop("_total", None)
    return filas, total


def resumen_conversaciones(agencia_id: int, *, cur=None) -> Dict[str, int]:
    with _cursor(cur) as c:
        c.execute(
            """
            SELECT
                COUNT(*)::int AS total,
                COUNT(*) FILTER (WHERE estado = 'abierta')::int AS abiertas,
                COUNT(*) FILTER (WHERE estado = 'esperando_usuario')::int AS esperando_usuario,
                COUNT(*) FILTER (WHERE estado = 'esperando_humano')::int AS esperando_humano,
                COUNT(*) FILTER (WHERE estado = 'cerrada')::int AS cerradas,
                COUNT(*) FILTER (WHERE estado = 'bloqueada')::int AS bloqueadas,
                COUNT(*) FILTER (WHERE modo_humano = TRUE AND estado <> 'cerrada')::int
                    AS en_modo_humano,
                COUNT(*) FILTER (WHERE ia_habilitada = TRUE AND estado <> 'cerrada')::int
                    AS con_ia_activa,
                COUNT(*) FILTER (WHERE modo = 'conversion' AND estado <> 'cerrada')::int
                    AS en_conversion
            FROM chatbot.conversaciones
            WHERE agencia_id = %s
            """,
            (agencia_id,),
        )
        base = dict(c.fetchone() or {})

        c.execute(
            """
            SELECT
                COUNT(*)::int AS evidencias_pendientes,
                COUNT(DISTINCT conversacion_id)::int AS conversaciones_con_evidencias_pendientes
            FROM chatbot.evidencias_candidato
            WHERE agencia_id = %s AND estado_revision = ANY(%s)
            """,
            (agencia_id, list(ESTADOS_EVIDENCIA_PENDIENTE)),
        )
        evidencias = dict(c.fetchone() or {})

        c.execute(
            """
            SELECT
                COUNT(*)::int AS tareas_pendientes,
                COUNT(*) FILTER (
                    WHERE fecha_limite IS NOT NULL AND fecha_limite < CURRENT_TIMESTAMP
                )::int AS tareas_vencidas
            FROM chatbot.tareas_candidato
            WHERE agencia_id = %s AND estado = ANY(%s)
            """,
            (agencia_id, list(ESTADOS_TAREA_PENDIENTE)),
        )
        tareas = dict(c.fetchone() or {})

    resumen = {**base, **evidencias, **tareas}
    return {k: int(v or 0) for k, v in resumen.items()}


def actualizar_conversacion(
    agencia_id: int,
    conversacion_id: int,
    campos: Dict[str, Any],
    *,
    cur=None,
) -> Optional[Dict[str, Any]]:
    return _actualizar_registro(
        "conversaciones", agencia_id, conversacion_id, campos, COLUMNAS_CONVERSACION, cur=cur
    )


def tomar_conversacion(
    agencia_id: int,
    conversacion_id: int,
    manager_id: int,
    *,
    motivo: Optional[str] = None,
    cur=None,
) -> Optional[Dict[str, Any]]:
    """
    Un humano autenticado toma el control: la IA deja de responder.

    Solo este camino (o equivalente de panel) debe activar modo_humano=true.
    """
    with _cursor(cur) as c:
        actual = _obtener_registro("conversaciones", agencia_id, conversacion_id, cur=c)
        if not actual:
            return None
        ya_humano = bool(actual.get("modo_humano"))
        campos: Dict[str, Any] = {
            "modo_humano": True,
            "ia_habilitada": False,
            "manager_id": manager_id,
            "estado": "esperando_humano",
            "escalada_at": _ahora(),
        }
        if motivo:
            campos["motivo_escalamiento"] = motivo
        conversacion = _actualizar_registro(
            "conversaciones", agencia_id, conversacion_id, campos, COLUMNAS_CONVERSACION, cur=c
        )
        registrar_evento(
            agencia_id,
            conversacion_id,
            tipo_evento="escalamiento",
            nombre_evento="conversacion_tomada_por_humano",
            origen="humano",
            estado_anterior=actual.get("estado"),
            estado_nuevo="esperando_humano",
            detalle={
                "manager_id": manager_id,
                "motivo": motivo,
                "modo_humano": True,
                "origen_activacion": "panel_tomar",
            },
            cur=c,
        )
        # Confirmación visible al pasar a modo humano (solo en la transición)
        if not ya_humano:
            texto_conf = (
                "Un asesor continuará la conversación contigo. Tu mensaje fue recibido."
            )
            try:
                insertar_mensaje(
                    agencia_id,
                    conversacion_id,
                    canal=str(actual.get("canal") or "whatsapp"),
                    direccion="saliente",
                    remitente_tipo="sistema",
                    tipo_mensaje="texto",
                    texto=texto_conf,
                    estado_envio="pendiente",
                    metadata={
                        "confirmacion_modo_humano": True,
                        "manager_id": manager_id,
                    },
                    cur=c,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[CHATBOT] no se pudo registrar confirmación modo_humano "
                    "conversacion_id=%s: %s",
                    conversacion_id,
                    exc,
                )
        return conversacion


def devolver_a_ia(
    agencia_id: int,
    conversacion_id: int,
    *,
    manager_id: Optional[int] = None,
    estado: str = "abierta",
    cur=None,
) -> Optional[Dict[str, Any]]:
    """Devuelve la conversación al asistente automático."""
    with _cursor(cur) as c:
        actual = _obtener_registro("conversaciones", agencia_id, conversacion_id, cur=c)
        if not actual:
            return None
        conversacion = _actualizar_registro(
            "conversaciones",
            agencia_id,
            conversacion_id,
            {
                "modo_humano": False,
                "ia_habilitada": True,
                "manager_id": None,
                "estado": estado,
                "motivo_escalamiento": None,
            },
            COLUMNAS_CONVERSACION,
            cur=c,
        )
        registrar_evento(
            agencia_id,
            conversacion_id,
            tipo_evento="cambio_estado",
            nombre_evento="conversacion_devuelta_a_ia",
            origen="humano",
            estado_anterior=actual.get("estado"),
            estado_nuevo=estado,
            detalle={"manager_id": manager_id},
            cur=c,
        )
        return conversacion


def escalar_conversacion(
    agencia_id: int,
    conversacion_id: int,
    *,
    motivo: str,
    manager_id: Optional[int] = None,
    estado_destino: Optional[str] = None,
    origen: str = "chatbot",
    cur=None,
) -> Optional[Dict[str, Any]]:
    with _cursor(cur) as c:
        actual = _obtener_registro("conversaciones", agencia_id, conversacion_id, cur=c)
        if not actual:
            return None
        campos: Dict[str, Any] = {
            "estado": "esperando_humano",
            "modo_humano": True,
            "ia_habilitada": False,
            "motivo_escalamiento": motivo,
            "escalada_at": _ahora(),
        }
        if manager_id is not None:
            campos["manager_id"] = manager_id
        if estado_destino:
            campos["estado_actual"] = estado_destino
        conversacion = _actualizar_registro(
            "conversaciones", agencia_id, conversacion_id, campos, COLUMNAS_CONVERSACION, cur=c
        )
        registrar_evento(
            agencia_id,
            conversacion_id,
            tipo_evento="escalamiento",
            nombre_evento="conversacion_escalada",
            origen=origen,
            estado_anterior=actual.get("estado_actual"),
            estado_nuevo=estado_destino or actual.get("estado_actual"),
            detalle={"motivo": motivo, "manager_id": manager_id},
            cur=c,
        )
        return conversacion


def cerrar_conversacion(
    agencia_id: int,
    conversacion_id: int,
    *,
    motivo: Optional[str] = None,
    estado_actual: Optional[str] = None,
    origen: str = "humano",
    cur=None,
) -> Optional[Dict[str, Any]]:
    with _cursor(cur) as c:
        actual = _obtener_registro("conversaciones", agencia_id, conversacion_id, cur=c)
        if not actual:
            return None
        campos: Dict[str, Any] = {
            "estado": "cerrada",
            "ia_habilitada": False,
            "cerrada_at": _ahora(),
        }
        if estado_actual:
            campos["estado_actual"] = estado_actual
        conversacion = _actualizar_registro(
            "conversaciones", agencia_id, conversacion_id, campos, COLUMNAS_CONVERSACION, cur=c
        )
        registrar_evento(
            agencia_id,
            conversacion_id,
            tipo_evento="cierre",
            nombre_evento="conversacion_cerrada",
            origen=origen,
            estado_anterior=actual.get("estado"),
            estado_nuevo="cerrada",
            detalle={"motivo": motivo},
            cur=c,
        )
        return conversacion


def asignar_campania_conversacion(
    agencia_id: int,
    conversacion_id: int,
    campania_id: int,
    *,
    aplicar_modo: bool = True,
    aplicar_flujo: bool = True,
    cur=None,
) -> Optional[Dict[str, Any]]:
    """Asocia la conversación a una campaña y hereda su modo y flujo."""
    with _cursor(cur) as c:
        campania = _obtener_registro("campanias", agencia_id, campania_id, cur=c)
        if not campania:
            raise ErrorDatosConversacional("La campaña no existe o no pertenece a la agencia")

        campos: Dict[str, Any] = {"campania_id": campania_id}
        if aplicar_modo and campania.get("modo_predeterminado"):
            campos["modo"] = campania["modo_predeterminado"]
        if aplicar_flujo and campania.get("flujo_id"):
            campos["flujo_id"] = campania["flujo_id"]
        if campania.get("plataforma_codigo"):
            campos["plataforma_codigo"] = campania["plataforma_codigo"]

        conversacion = _actualizar_registro(
            "conversaciones", agencia_id, conversacion_id, campos, COLUMNAS_CONVERSACION, cur=c
        )
        if conversacion:
            registrar_evento(
                agencia_id,
                conversacion_id,
                tipo_evento="cambio_flujo",
                nombre_evento="campania_asignada",
                origen="humano",
                detalle={"campania_id": campania_id},
                cur=c,
            )
        return conversacion


# ---------------------------------------------------------------------------
# Mensajes
# ---------------------------------------------------------------------------


def mensaje_externo_ya_procesado(
    agencia_id: int,
    mensaje_externo_id: str,
    *,
    canal: Optional[str] = None,
    cur=None,
) -> bool:
    """True si el mensaje del proveedor ya fue almacenado (anti-duplicado)."""
    externo = str(mensaje_externo_id or "").strip()
    if not externo:
        return False

    where = ["agencia_id = %s", "mensaje_externo_id = %s"]
    params: List[Any] = [agencia_id, externo]
    if canal:
        where.append("canal = %s")
        params.append(str(canal).strip().lower())

    with _cursor(cur) as c:
        c.execute(
            f"SELECT 1 FROM chatbot.mensajes_conversacion WHERE {' AND '.join(where)} LIMIT 1",
            params,
        )
        return c.fetchone() is not None


def insertar_mensaje(
    agencia_id: int,
    conversacion_id: int,
    *,
    canal: str,
    direccion: str,
    remitente_tipo: str,
    tipo_mensaje: str = "texto",
    texto: Optional[str] = None,
    media_url: Optional[str] = None,
    media_id_externo: Optional[str] = None,
    media_nombre: Optional[str] = None,
    media_mime_type: Optional[str] = None,
    mensaje_externo_id: Optional[str] = None,
    respuesta_a_mensaje_id: Optional[int] = None,
    estado_envio: str = "recibido",
    error_detalle: Optional[str] = None,
    procesado_por_ia: bool = False,
    modelo_ia: Optional[str] = None,
    prompt_version: Optional[str] = None,
    tokens_entrada: Optional[int] = None,
    tokens_salida: Optional[int] = None,
    costo_estimado_usd: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None,
    actualizar_ultimo_mensaje: bool = True,
    cur=None,
) -> Tuple[Dict[str, Any], bool]:
    """
    Inserta un mensaje. Si llega ``mensaje_externo_id`` se aplica dedup contra
    el índice parcial ``ux_mensaje_externo``. Devuelve ``(mensaje, creado)``.
    """
    externo = str(mensaje_externo_id or "").strip() or None
    canal_norm = str(canal or "").strip().lower()

    with _cursor(cur) as c:
        if not _obtener_registro("conversaciones", agencia_id, conversacion_id, cur=c):
            raise ErrorDatosConversacional(
                "La conversación no existe o no pertenece a la agencia"
            )

        valores = (
            agencia_id,
            conversacion_id,
            canal_norm,
            str(direccion or "").strip().lower(),
            str(remitente_tipo or "").strip().lower(),
            str(tipo_mensaje or "texto").strip().lower(),
            texto,
            media_url,
            media_id_externo,
            media_nombre,
            media_mime_type,
            externo,
            respuesta_a_mensaje_id,
            str(estado_envio or "recibido").strip().lower(),
            error_detalle,
            bool(procesado_por_ia),
            modelo_ia,
            prompt_version,
            tokens_entrada,
            tokens_salida,
            costo_estimado_usd,
            _valor_jsonb("metadata", metadata or {}),
        )
        columnas = """
            agencia_id, conversacion_id, canal, direccion, remitente_tipo,
            tipo_mensaje, texto, media_url, media_id_externo, media_nombre,
            media_mime_type, mensaje_externo_id, respuesta_a_mensaje_id,
            estado_envio, error_detalle, procesado_por_ia, modelo_ia,
            prompt_version, tokens_entrada, tokens_salida, costo_estimado_usd,
            metadata
        """
        placeholders = ", ".join(["%s"] * 22)

        if externo:
            c.execute(
                f"""
                INSERT INTO chatbot.mensajes_conversacion ({columnas})
                VALUES ({placeholders})
                ON CONFLICT (agencia_id, canal, mensaje_externo_id)
                    WHERE mensaje_externo_id IS NOT NULL
                DO NOTHING
                RETURNING *
                """,
                valores,
            )
        else:
            c.execute(
                f"""
                INSERT INTO chatbot.mensajes_conversacion ({columnas})
                VALUES ({placeholders})
                RETURNING *
                """,
                valores,
            )
        row = _fila(c.fetchone())

        if row is None and externo:
            c.execute(
                """
                SELECT *
                FROM chatbot.mensajes_conversacion
                WHERE agencia_id = %s AND canal = %s AND mensaje_externo_id = %s
                LIMIT 1
                """,
                (agencia_id, canal_norm, externo),
            )
            existente = _fila(c.fetchone())
            if existente:
                logger.info(
                    "[CONVERSACIONAL] mensaje duplicado ignorado agencia_id=%s externo_id=%s",
                    agencia_id,
                    externo,
                )
                return existente, False
            raise ErrorDatosConversacional("No se pudo insertar ni recuperar el mensaje")

        if row is None:  # pragma: no cover - INSERT sin dedup siempre retorna
            raise ErrorDatosConversacional("No se pudo insertar el mensaje")

        if actualizar_ultimo_mensaje:
            c.execute(
                """
                UPDATE chatbot.conversaciones
                SET ultimo_mensaje_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND agencia_id = %s
                """,
                (conversacion_id, agencia_id),
            )

        return row, True


def listar_mensajes(
    agencia_id: int,
    conversacion_id: int,
    *,
    limit: int = 50,
    antes_de_id: Optional[int] = None,
    desde_id: Optional[int] = None,
    orden: str = "asc",
    cur=None,
) -> List[Dict[str, Any]]:
    """Historial de la conversación. ``antes_de_id`` permite paginar hacia atrás."""
    where = ["agencia_id = %s", "conversacion_id = %s"]
    params: List[Any] = [agencia_id, conversacion_id]
    if antes_de_id is not None:
        where.append("id < %s")
        params.append(antes_de_id)
    if desde_id is not None:
        where.append("id > %s")
        params.append(desde_id)

    page_size = _limite(limit, defecto=50, maximo=200)
    params.append(page_size)

    with _cursor(cur) as c:
        c.execute(
            f"""
            SELECT * FROM (
                SELECT *
                FROM chatbot.mensajes_conversacion
                WHERE {' AND '.join(where)}
                ORDER BY id DESC
                LIMIT %s
            ) AS ultimos
            ORDER BY id {'DESC' if str(orden).strip().lower() == 'desc' else 'ASC'}
            """,
            params,
        )
        return _filas(c.fetchall())


def obtener_mensaje(agencia_id: int, mensaje_id: int, *, cur=None) -> Optional[Dict[str, Any]]:
    return _obtener_registro("mensajes", agencia_id, mensaje_id, cur=cur)


def marcar_mensaje_procesado(
    agencia_id: int,
    mensaje_id: int,
    *,
    estado_envio: Optional[str] = None,
    modelo_ia: Optional[str] = None,
    prompt_version: Optional[str] = None,
    tokens_entrada: Optional[int] = None,
    tokens_salida: Optional[int] = None,
    costo_estimado_usd: Optional[float] = None,
    error_detalle: Optional[str] = None,
    cur=None,
) -> Optional[Dict[str, Any]]:
    sets = ["procesado_por_ia = TRUE"]
    params: List[Any] = []
    opcionales = {
        "estado_envio": estado_envio,
        "modelo_ia": modelo_ia,
        "prompt_version": prompt_version,
        "tokens_entrada": tokens_entrada,
        "tokens_salida": tokens_salida,
        "costo_estimado_usd": costo_estimado_usd,
        "error_detalle": error_detalle,
    }
    for columna, valor in opcionales.items():
        if valor is not None:
            sets.append(f"{columna} = %s")
            params.append(valor)
    params.extend([mensaje_id, agencia_id])

    with _cursor(cur) as c:
        c.execute(
            f"""
            UPDATE chatbot.mensajes_conversacion
            SET {', '.join(sets)}
            WHERE id = %s AND agencia_id = %s
            RETURNING *
            """,
            params,
        )
        return _fila(c.fetchone())


# ---------------------------------------------------------------------------
# Tareas del candidato
# ---------------------------------------------------------------------------


def listar_tareas(
    agencia_id: int,
    *,
    conversacion_id: Optional[int] = None,
    aspirante_id: Optional[int] = None,
    estado: Optional[str] = None,
    tipo_tarea: Optional[str] = None,
    solo_pendientes: bool = False,
    solo_vencidas: bool = False,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    cur=None,
) -> List[Dict[str, Any]]:
    where: List[str] = []
    params: List[Any] = []
    if conversacion_id is not None:
        where.append("conversacion_id = %s")
        params.append(conversacion_id)
    if aspirante_id is not None:
        where.append("aspirante_id = %s")
        params.append(aspirante_id)
    if estado:
        where.append("estado = %s")
        params.append(str(estado).strip().lower())
    if tipo_tarea:
        where.append("tipo_tarea = %s")
        params.append(str(tipo_tarea).strip().lower())
    if solo_pendientes:
        where.append("estado = ANY(%s)")
        params.append(list(ESTADOS_TAREA_PENDIENTE))
    if solo_vencidas:
        where.append("fecha_limite IS NOT NULL AND fecha_limite < CURRENT_TIMESTAMP")

    return _listar_registros(
        "tareas",
        agencia_id,
        where_extra=where,
        params_extra=params,
        order_by="fecha_limite ASC NULLS LAST, created_at DESC",
        limit=limit,
        offset=offset,
        cur=cur,
    )


def obtener_tarea(agencia_id: int, tarea_id: int, *, cur=None) -> Optional[Dict[str, Any]]:
    return _obtener_registro("tareas", agencia_id, tarea_id, cur=cur)


def crear_tarea(agencia_id: int, campos: Dict[str, Any], *, cur=None) -> Dict[str, Any]:
    conversacion_id = (campos or {}).get("conversacion_id")
    if not conversacion_id:
        raise ErrorDatosConversacional("conversacion_id es obligatorio para la tarea")
    with _cursor(cur) as c:
        if not _obtener_registro("conversaciones", agencia_id, int(conversacion_id), cur=c):
            raise ErrorDatosConversacional(
                "La conversación no existe o no pertenece a la agencia"
            )
        tarea = _crear_registro("tareas", agencia_id, campos, COLUMNAS_TAREA, cur=c)
        registrar_evento(
            agencia_id,
            int(conversacion_id),
            tipo_evento="tarea",
            nombre_evento="tarea_creada",
            origen=str((campos or {}).get("creada_por_tipo") or "chatbot"),
            detalle={"tarea_id": tarea.get("id"), "tipo_tarea": tarea.get("tipo_tarea")},
            cur=c,
        )
        return tarea


def actualizar_tarea(
    agencia_id: int, tarea_id: int, campos: Dict[str, Any], *, cur=None
) -> Optional[Dict[str, Any]]:
    return _actualizar_registro("tareas", agencia_id, tarea_id, campos, COLUMNAS_TAREA, cur=cur)


def completar_tarea(
    agencia_id: int,
    tarea_id: int,
    *,
    datos_resultado: Optional[Dict[str, Any]] = None,
    cur=None,
) -> Optional[Dict[str, Any]]:
    campos: Dict[str, Any] = {"estado": "completada", "completada_at": _ahora()}
    if datos_resultado is not None:
        campos["datos_resultado"] = datos_resultado
    return _actualizar_registro("tareas", agencia_id, tarea_id, campos, COLUMNAS_TAREA, cur=cur)


def cancelar_tarea(agencia_id: int, tarea_id: int, *, cur=None) -> Optional[Dict[str, Any]]:
    return _actualizar_registro(
        "tareas", agencia_id, tarea_id, {"estado": "cancelada"}, COLUMNAS_TAREA, cur=cur
    )


def eliminar_tarea(agencia_id: int, tarea_id: int, *, cur=None) -> bool:
    return _eliminar_registro("tareas", agencia_id, tarea_id, hard=True, cur=cur)


# ---------------------------------------------------------------------------
# Evidencias del candidato
# ---------------------------------------------------------------------------


def listar_evidencias(
    agencia_id: int,
    *,
    conversacion_id: Optional[int] = None,
    aspirante_id: Optional[int] = None,
    tarea_id: Optional[int] = None,
    estado_revision: Optional[str] = None,
    tipo_evidencia: Optional[str] = None,
    solo_pendientes: bool = False,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    cur=None,
) -> List[Dict[str, Any]]:
    where: List[str] = []
    params: List[Any] = []
    if conversacion_id is not None:
        where.append("conversacion_id = %s")
        params.append(conversacion_id)
    if aspirante_id is not None:
        where.append("aspirante_id = %s")
        params.append(aspirante_id)
    if tarea_id is not None:
        where.append("tarea_id = %s")
        params.append(tarea_id)
    if estado_revision:
        where.append("estado_revision = %s")
        params.append(str(estado_revision).strip().lower())
    if tipo_evidencia:
        where.append("tipo_evidencia = %s")
        params.append(str(tipo_evidencia).strip().lower())
    if solo_pendientes:
        where.append("estado_revision = ANY(%s)")
        params.append(list(ESTADOS_EVIDENCIA_PENDIENTE))

    return _listar_registros(
        "evidencias",
        agencia_id,
        where_extra=where,
        params_extra=params,
        order_by="created_at DESC, id DESC",
        limit=limit,
        offset=offset,
        cur=cur,
    )


def obtener_evidencia(agencia_id: int, evidencia_id: int, *, cur=None) -> Optional[Dict[str, Any]]:
    return _obtener_registro("evidencias", agencia_id, evidencia_id, cur=cur)


def crear_evidencia(agencia_id: int, campos: Dict[str, Any], *, cur=None) -> Dict[str, Any]:
    conversacion_id = (campos or {}).get("conversacion_id")
    if not conversacion_id:
        raise ErrorDatosConversacional("conversacion_id es obligatorio para la evidencia")
    with _cursor(cur) as c:
        if not _obtener_registro("conversaciones", agencia_id, int(conversacion_id), cur=c):
            raise ErrorDatosConversacional(
                "La conversación no existe o no pertenece a la agencia"
            )
        evidencia = _crear_registro("evidencias", agencia_id, campos, COLUMNAS_EVIDENCIA, cur=c)
        registrar_evento(
            agencia_id,
            int(conversacion_id),
            tipo_evento="evidencia",
            nombre_evento="evidencia_recibida",
            origen="usuario",
            mensaje_id=evidencia.get("mensaje_id"),
            detalle={
                "evidencia_id": evidencia.get("id"),
                "tipo_evidencia": evidencia.get("tipo_evidencia"),
            },
            cur=c,
        )
        return evidencia


def actualizar_evidencia(
    agencia_id: int, evidencia_id: int, campos: Dict[str, Any], *, cur=None
) -> Optional[Dict[str, Any]]:
    return _actualizar_registro(
        "evidencias", agencia_id, evidencia_id, campos, COLUMNAS_EVIDENCIA, cur=cur
    )


def revisar_evidencia(
    agencia_id: int,
    evidencia_id: int,
    *,
    estado_revision: str,
    revisado_por: Optional[int] = None,
    observaciones_revision: Optional[str] = None,
    cur=None,
) -> Optional[Dict[str, Any]]:
    """Registra el veredicto humano sobre una evidencia."""
    with _cursor(cur) as c:
        evidencia = _obtener_registro("evidencias", agencia_id, evidencia_id, cur=c)
        if not evidencia:
            return None
        actualizada = _actualizar_registro(
            "evidencias",
            agencia_id,
            evidencia_id,
            {
                "estado_revision": str(estado_revision).strip().lower(),
                "revisado_por": revisado_por,
                "observaciones_revision": observaciones_revision,
                "revisado_at": _ahora(),
            },
            COLUMNAS_EVIDENCIA,
            cur=c,
        )
        registrar_evento(
            agencia_id,
            int(evidencia["conversacion_id"]),
            tipo_evento="evidencia",
            nombre_evento="evidencia_revisada",
            origen="humano",
            estado_anterior=evidencia.get("estado_revision"),
            estado_nuevo=str(estado_revision).strip().lower(),
            detalle={"evidencia_id": evidencia_id, "revisado_por": revisado_por},
            cur=c,
        )
        return actualizada


def eliminar_evidencia(agencia_id: int, evidencia_id: int, *, cur=None) -> bool:
    return _eliminar_registro("evidencias", agencia_id, evidencia_id, hard=True, cur=cur)


# ---------------------------------------------------------------------------
# Eventos de conversación (auditoría)
# ---------------------------------------------------------------------------


def registrar_evento(
    agencia_id: int,
    conversacion_id: int,
    *,
    tipo_evento: str,
    nombre_evento: str,
    origen: str,
    mensaje_id: Optional[int] = None,
    estado_anterior: Optional[str] = None,
    estado_nuevo: Optional[str] = None,
    exitoso: bool = True,
    detalle: Optional[Dict[str, Any]] = None,
    error_detalle: Optional[str] = None,
    cur=None,
) -> Dict[str, Any]:
    with _cursor(cur) as c:
        c.execute(
            """
            INSERT INTO chatbot.eventos_conversacion (
                agencia_id, conversacion_id, mensaje_id, tipo_evento, nombre_evento,
                origen, estado_anterior, estado_nuevo, exitoso, detalle, error_detalle
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                agencia_id,
                conversacion_id,
                mensaje_id,
                str(tipo_evento).strip().lower(),
                str(nombre_evento).strip(),
                str(origen).strip().lower(),
                estado_anterior,
                estado_nuevo,
                bool(exitoso),
                _valor_jsonb("detalle", detalle or {}),
                error_detalle,
            ),
        )
        return dict(c.fetchone())


def listar_eventos(
    agencia_id: int,
    conversacion_id: int,
    *,
    tipo_evento: Optional[str] = None,
    solo_errores: bool = False,
    limit: int = 100,
    cur=None,
) -> List[Dict[str, Any]]:
    where = ["agencia_id = %s", "conversacion_id = %s"]
    params: List[Any] = [agencia_id, conversacion_id]
    if tipo_evento:
        where.append("tipo_evento = %s")
        params.append(str(tipo_evento).strip().lower())
    if solo_errores:
        where.append("exitoso = FALSE")
    params.append(_limite(limit, defecto=100, maximo=500))

    with _cursor(cur) as c:
        c.execute(
            f"""
            SELECT *
            FROM chatbot.eventos_conversacion
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            params,
        )
        return _filas(c.fetchall())


# ---------------------------------------------------------------------------
# Aspirantes: campos conversacionales
# ---------------------------------------------------------------------------


def actualizar_aspirante_campos_conversacionales(
    aspirante_id: int,
    agencia_id: int,
    *,
    origen_captacion: Any = SIN_VALOR,
    campania_id: Any = SIN_VALOR,
    modo_conversacional: Any = SIN_VALOR,
    preseleccionado_ads: Any = SIN_VALOR,
    nivel_experiencia: Any = SIN_VALOR,
    nivel_experiencia_fuente: Any = SIN_VALOR,
    nivel_experiencia_confianza: Any = SIN_VALOR,
    nivel_experiencia_confirmado_at: Any = SIN_VALOR,
    nivel_experiencia_bloqueado_manual: Any = SIN_VALOR,
    cur=None,
) -> Optional[Dict[str, Any]]:
    """
    Actualiza el origen conversacional / nivel estable del aspirante.

    Usa el centinela ``SIN_VALOR`` para distinguir "no enviado" de "enviar
    NULL"; así se puede limpiar la campaña pasando ``campania_id=None``.
    """
    campos: Dict[str, Any] = {}
    entradas = {
        "origen_captacion": origen_captacion,
        "campania_id": campania_id,
        "modo_conversacional": modo_conversacional,
        "preseleccionado_ads": preseleccionado_ads,
        "nivel_experiencia": nivel_experiencia,
        "nivel_experiencia_fuente": nivel_experiencia_fuente,
        "nivel_experiencia_confianza": nivel_experiencia_confianza,
        "nivel_experiencia_confirmado_at": nivel_experiencia_confirmado_at,
        "nivel_experiencia_bloqueado_manual": nivel_experiencia_bloqueado_manual,
    }
    for columna, valor in entradas.items():
        if not isinstance(valor, _SinValor):
            campos[columna] = valor

    campos = _campos_permitidos(campos, COLUMNAS_ASPIRANTE_CONVERSACIONAL)
    if not campos:
        with _cursor(cur) as c:
            c.execute(
                """
                SELECT * FROM chatbot.chatbot_aspirantes
                WHERE id = %s AND agencia_id = %s
                LIMIT 1
                """,
                (aspirante_id, agencia_id),
            )
            return _fila(c.fetchone())

    sets = [f"{col} = %s" for col in campos]
    valores: List[Any] = list(campos.values())
    sets.append("updated_at = CURRENT_TIMESTAMP")
    valores.extend([aspirante_id, agencia_id])

    with _cursor(cur) as c:
        if campos.get("campania_id"):
            if not _obtener_registro("campanias", agencia_id, int(campos["campania_id"]), cur=c):
                raise ErrorDatosConversacional(
                    "La campaña no existe o no pertenece a la agencia"
                )
        c.execute(
            f"""
            UPDATE chatbot.chatbot_aspirantes
            SET {', '.join(sets)}
            WHERE id = %s AND agencia_id = %s
            RETURNING *
            """,
            valores,
        )
        return _fila(c.fetchone())


def actualizar_nivel_aspirante_estable(
    aspirante_id: int,
    agencia_id: int,
    *,
    nivel_experiencia: str,
    nivel_experiencia_fuente: str,
    nivel_experiencia_confianza: Optional[float] = None,
    nivel_experiencia_confirmado_at: Any = None,
    nivel_experiencia_bloqueado_manual: Optional[bool] = None,
    cur=None,
) -> Optional[Dict[str, Any]]:
    """Actualiza solo la clasificación estable del aspirante (valida agencia)."""
    kwargs: Dict[str, Any] = {
        "nivel_experiencia": nivel_experiencia,
        "nivel_experiencia_fuente": nivel_experiencia_fuente,
    }
    if nivel_experiencia_confianza is not None:
        kwargs["nivel_experiencia_confianza"] = nivel_experiencia_confianza
    if nivel_experiencia_confirmado_at is not None:
        kwargs["nivel_experiencia_confirmado_at"] = nivel_experiencia_confirmado_at
    if nivel_experiencia_bloqueado_manual is not None:
        kwargs["nivel_experiencia_bloqueado_manual"] = nivel_experiencia_bloqueado_manual
    return actualizar_aspirante_campos_conversacionales(
        aspirante_id, agencia_id, cur=cur, **kwargs
    )

# ---------------------------------------------------------------------------
# Inicialización desde la configuración rígida existente
# ---------------------------------------------------------------------------


def _requisitos_base(config_rigida: Dict[str, Any]) -> List[Dict[str, Any]]:
    cfg = config_rigida or {}
    return [
        {
            "codigo": "mayoria_edad",
            "nombre": "Mayoría de edad",
            "descripcion": str(cfg.get("pregunta_mayor_edad") or "").strip() or None,
            "categoria": "obligatorio",
            "tipo_dato": "booleano",
            "operador": "igual",
            "valor_texto": "true",
            "bloquea_proceso": True,
            "permitir_mencion_automatica": True,
            "mensaje_si_no_cumple": (
                str(cfg.get("mensaje_no_aprobado") or "").strip()
                or "Para continuar debes ser mayor de 18 años."
            ),
            "orden": 1,
        },
        {
            "codigo": "disponibilidad_live",
            "nombre": "Disponibilidad para transmisiones LIVE",
            "descripcion": str(cfg.get("pregunta_disponibilidad") or "").strip() or None,
            "categoria": "obligatorio",
            "tipo_dato": "booleano",
            "operador": "igual",
            "valor_texto": "true",
            "bloquea_proceso": False,
            "permitir_mencion_automatica": True,
            "mensaje_si_no_cumple": (
                "La agencia requiere disponibilidad para transmitir en vivo "
                "varias veces por semana."
            ),
            "orden": 2,
        },
    ]


def _pasos_flujo_informativo(config_rigida: Dict[str, Any]) -> List[Dict[str, Any]]:
    cfg = config_rigida or {}
    return [
        {
            "codigo": "presentacion",
            "nombre": "Presentación del asistente",
            "orden": 0,
            "tipo_accion": "informar",
            "obligatorio": True,
            "mensaje_instrucciones": (
                str(cfg.get("mensaje_bienvenida") or "").strip()
                or "Preséntate como asistente virtual de la agencia."
            ),
            "estado_exitoso": "presentado",
        },
        {
            "codigo": "explicar_requisitos",
            "nombre": "Explicar requisitos",
            "orden": 1,
            "tipo_accion": "explicar_requisitos",
            "obligatorio": True,
            "mensaje_instrucciones": (
                "Explica los requisitos vigentes sin prometer resultados ni evaluar al candidato."
            ),
            "estado_exitoso": "requisitos_explicados",
        },
        {
            "codigo": "explicar_beneficios",
            "nombre": "Explicar beneficios",
            "orden": 2,
            "tipo_accion": "explicar_beneficios",
            "obligatorio": False,
            "permite_omitir": True,
            "mensaje_instrucciones": (
                "Menciona únicamente beneficios vigentes y autorizados para mención automática."
            ),
            "estado_exitoso": "beneficios_explicados",
        },
        {
            "codigo": "resolver_dudas",
            "nombre": "Resolver preguntas frecuentes",
            "orden": 3,
            "tipo_accion": "esperar_respuesta",
            "obligatorio": False,
            "permite_omitir": True,
            "mensaje_instrucciones": "Responde con base en las FAQ registradas.",
            "estado_exitoso": "dudas_resueltas",
        },
        {
            "codigo": "cierre_informativo",
            "nombre": "Cierre informativo",
            "orden": 4,
            "tipo_accion": "finalizar",
            "obligatorio": True,
            "mensaje_instrucciones": (
                "Agradece el interés e indica cómo continuar el proceso si lo desea."
            ),
            "estado_exitoso": "finalizado",
        },
    ]


def inicializar_asistente_desde_config(
    agencia_id: int,
    chatbot_configuracion_id: int,
    config_rigida: Optional[Dict[str, Any]] = None,
    agencia: Optional[Dict[str, Any]] = None,
    *,
    copiar_faq: bool = True,
    crear_requisitos_base: bool = True,
    crear_flujo_informativo: bool = True,
    cur=None,
) -> Dict[str, Any]:
    """
    Prepara el modo conversacional a partir de la configuración rígida.

    Es idempotente: si el asistente ya existe no se toca, las FAQ se importan
    sólo si faltan y los requisitos y el flujo base se crean únicamente cuando
    no están. El asistente se crea **inactivo** para que la agencia lo revise
    antes de exponerlo.
    """
    cfg_rigida = dict(config_rigida or {})
    datos_agencia = dict(agencia or {})

    with _cursor(cur) as c:
        _exige_configuracion(agencia_id, chatbot_configuracion_id, cur=c)

        asistente = obtener_asistente_por_config(agencia_id, chatbot_configuracion_id, cur=c)
        asistente_creado = False
        if not asistente:
            nombre_agencia = str(datos_agencia.get("nombre") or "").strip()
            nombre_asistente = (
                f"Asistente de {nombre_agencia}"[:120] if nombre_agencia else "Asistente virtual"
            )
            asistente = upsert_asistente(
                agencia_id,
                chatbot_configuracion_id,
                {
                    "nombre_asistente": nombre_asistente,
                    "descripcion_agencia": nombre_agencia or None,
                    "presentacion_inicial": (
                        str(cfg_rigida.get("mensaje_bienvenida") or "").strip() or None
                    ),
                    "presentacion_informativo": (
                        str(cfg_rigida.get("mensaje_bienvenida") or "").strip() or None
                    ),
                    "presentacion_inteligente": (
                        str(cfg_rigida.get("mensaje_bienvenida") or "").strip() or None
                    ),
                    "modo_informativo_activo": True,
                    "modo_conversion_activo": False,
                    "modo_predeterminado": "informativo",
                    "declarar_asistente_virtual": True,
                    "activo": False,
                },
                cur=c,
            )
            asistente_creado = True

        faqs_importadas = 0
        if copiar_faq:
            faqs_importadas = importar_faqs_desde_json(
                agencia_id,
                chatbot_configuracion_id,
                cfg_rigida.get("preguntas_frecuentes"),
                cur=c,
            )

        requisitos_creados = 0
        if crear_requisitos_base:
            for requisito in _requisitos_base(cfg_rigida):
                existente = obtener_requisito_por_codigo(
                    agencia_id,
                    requisito["codigo"],
                    chatbot_configuracion_id=chatbot_configuracion_id,
                    cur=c,
                )
                if existente:
                    continue
                requisito["chatbot_configuracion_id"] = chatbot_configuracion_id
                _crear_registro("requisitos", agencia_id, requisito, COLUMNAS_REQUISITO, cur=c)
                requisitos_creados += 1

        flujo = obtener_flujo_por_codigo(
            agencia_id, chatbot_configuracion_id, "informativo_base", cur=c
        )
        flujo_creado = False
        pasos_creados = 0
        if crear_flujo_informativo and not flujo:
            flujo = _crear_registro(
                "flujos",
                agencia_id,
                {
                    "chatbot_configuracion_id": chatbot_configuracion_id,
                    "codigo": "informativo_base",
                    "nombre": "Flujo informativo base",
                    "tipo_flujo": "informativo",
                    "descripcion": (
                        "Flujo generado automáticamente a partir de la configuración rígida."
                    ),
                    "estado_inicial": "inicio",
                    "estado_final": "finalizado",
                    "activo": True,
                },
                COLUMNAS_FLUJO,
                cur=c,
            )
            flujo_creado = True
            for paso in _pasos_flujo_informativo(cfg_rigida):
                paso["flujo_id"] = flujo["id"]
                _crear_registro("flujo_pasos", agencia_id, paso, COLUMNAS_FLUJO_PASO, cur=c)
                pasos_creados += 1

        menu_seed = asegurar_menu_informativo_base(
            agencia_id,
            chatbot_configuracion_id,
            cur=c,
        )

    resumen = {
        "asistente": asistente,
        "asistente_creado": asistente_creado,
        "faqs_importadas": faqs_importadas,
        "requisitos_creados": requisitos_creados,
        "flujo_id": int(flujo["id"]) if flujo else None,
        "flujo_creado": flujo_creado,
        "pasos_creados": pasos_creados,
        "menu_opciones_insertadas": int((menu_seed or {}).get("insertadas") or 0),
    }
    logger.info(
        "[CONVERSACIONAL] init agencia_id=%s config_id=%s asistente_creado=%s "
        "faqs=%s requisitos=%s flujo_creado=%s",
        agencia_id,
        chatbot_configuracion_id,
        asistente_creado,
        faqs_importadas,
        requisitos_creados,
        flujo_creado,
    )
    return resumen


# ---------------------------------------------------------------------------
# Contexto agregado para el agente
# ---------------------------------------------------------------------------


def obtener_contexto_agente(
    agencia_id: int,
    chatbot_configuracion_id: int,
    *,
    campania_id: Optional[int] = None,
    cur=None,
) -> Dict[str, Any]:
    """Reúne en una sola llamada el conocimiento autorizado del asistente."""
    with _cursor(cur) as c:
        return {
            "asistente": obtener_asistente_por_config(
                agencia_id, chatbot_configuracion_id, cur=c
            ),
            "requisitos": listar_requisitos(
                agencia_id,
                chatbot_configuracion_id=chatbot_configuracion_id,
                solo_activos=True,
                solo_vigentes=True,
                cur=c,
            ),
            "beneficios": listar_beneficios_vigentes(
                agencia_id, chatbot_configuracion_id, campania_id, cur=c
            ),
            "faqs": listar_faqs(
                agencia_id,
                chatbot_configuracion_id=chatbot_configuracion_id,
                solo_activos=True,
                solo_vigentes=True,
                cur=c,
            ),
            "recursos": listar_recursos(
                agencia_id,
                chatbot_configuracion_id=chatbot_configuracion_id,
                campania_id=campania_id,
                solo_activos=True,
                solo_vigentes=True,
                cur=c,
            ),
            "campania": (
                _obtener_registro("campanias", agencia_id, campania_id, cur=c)
                if campania_id
                else None
            ),
        }


# ---------------------------------------------------------------------------
# Alias de compatibilidad con chatbot_conversacional_db_gateway (raíz)
# ---------------------------------------------------------------------------


def obtener_asistente_configuracion(
    agencia_id: int, chatbot_configuracion_id: int, *, cur=None
) -> Optional[Dict[str, Any]]:
    return obtener_asistente_por_config(agencia_id, chatbot_configuracion_id, cur=cur)


def obtener_o_crear_conversacion(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    resultado = buscar_o_crear_conversacion(*args, **kwargs)
    if isinstance(resultado, tuple):
        return resultado[0]
    return resultado


def listar_faq(*args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
    """Alias tolerante: acepta `limite` (se aplica con slice) y 2º arg posicional."""
    limite = kwargs.pop("limite", None)
    if len(args) >= 2 and "chatbot_configuracion_id" not in kwargs:
        kwargs["chatbot_configuracion_id"] = args[1]
        args = args[:1]
    kwargs.pop("limit", None)
    filas = listar_faqs(*args, **kwargs)
    if limite is not None:
        try:
            return list(filas)[: max(0, int(limite))]
        except (TypeError, ValueError):
            return list(filas)
    return filas


def listar_recursos_enlaces(*args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
    """Alias tolerante: acepta `limite` y 2º arg posicional como config id."""
    limite = kwargs.pop("limite", None)
    if len(args) >= 2 and "chatbot_configuracion_id" not in kwargs:
        kwargs["chatbot_configuracion_id"] = args[1]
        args = args[:1]
    kwargs.pop("limit", None)
    filas = listar_recursos(*args, **kwargs)
    if limite is not None:
        try:
            return list(filas)[: max(0, int(limite))]
        except (TypeError, ValueError):
            return list(filas)
    return filas


def listar_requisitos_gateway(
    agencia_id: int,
    chatbot_configuracion_id: Optional[int] = None,
    *,
    limite: Optional[int] = None,
    cur=None,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """Compatibilidad con llamadas del context_builder vía gateway."""
    filas = listar_requisitos(
        agencia_id,
        chatbot_configuracion_id=chatbot_configuracion_id,
        cur=cur,
        **kwargs,
    )
    if limite is not None:
        try:
            return list(filas)[: max(0, int(limite))]
        except (TypeError, ValueError):
            return list(filas)
    return filas


# El gateway puede resolver por nombre exacto; no sustituimos listar_requisitos
# nativo (keyword-only). El context_builder ya llama con kwargs correctos.


def buscar_faq(
    agencia_id: int,
    chatbot_configuracion_id: int,
    consulta: str,
    limite: int = 3,
    *,
    cur=None,
) -> List[Dict[str, Any]]:
    return buscar_faqs_por_texto(
        agencia_id,
        consulta,
        chatbot_configuracion_id=chatbot_configuracion_id,
        limit=limite,
        cur=cur,
    )


def obtener_agencia(agencia_id: int, *, cur=None) -> Optional[Dict[str, Any]]:
    import database_chatbot_captacion as db_captacion

    return db_captacion.obtener_agencia_por_id(int(agencia_id))


def obtener_configuracion_chatbot(
    agencia_id: int, chatbot_configuracion_id: int, *, cur=None
) -> Optional[Dict[str, Any]]:
    import database_chatbot_captacion as db_captacion

    return db_captacion.obtener_configuracion_por_id(
        int(agencia_id), int(chatbot_configuracion_id), solo_activa=False
    )


def obtener_aspirante(agencia_id: int, aspirante_id: int, *, cur=None) -> Optional[Dict[str, Any]]:
    import database_chatbot_captacion as db_captacion

    return db_captacion.obtener_aspirante(int(agencia_id), int(aspirante_id))


def obtener_paso_flujo(agencia_id: int, paso_id: int, *, cur=None) -> Optional[Dict[str, Any]]:
    return obtener_flujo_paso(agencia_id, paso_id, cur=cur)


def obtener_flujo_activo(
    agencia_id: int,
    chatbot_configuracion_id: int,
    tipo_flujo: str,
    *,
    cur=None,
) -> Optional[Dict[str, Any]]:
    flujos = listar_flujos(
        agencia_id,
        chatbot_configuracion_id=chatbot_configuracion_id,
        tipo_flujo=tipo_flujo,
        solo_activos=True,
        cur=cur,
    )
    return flujos[0] if flujos else None


def listar_ultimos_mensajes(
    agencia_id: int, conversacion_id: int, limite: int = 12, *, cur=None
) -> List[Dict[str, Any]]:
    return listar_mensajes(agencia_id, conversacion_id, limit=limite, cur=cur)


def obtener_prueba_live_por_flujo(
    agencia_id: int,
    flujo_id: int,
    *,
    campania_id: Optional[int] = None,
    cur=None,
) -> Optional[Dict[str, Any]]:
    """Primera prueba LIVE activa del flujo (compatibilidad con context_builder)."""
    items = listar_pruebas_live(
        agencia_id,
        flujo_id=int(flujo_id),
        campania_id=campania_id,
        solo_activas=True,
        cur=cur,
    )
    return items[0] if items else None


def obtener_mensaje_por_externo_id(
    agencia_id: int,
    conversacion_id: int,
    mensaje_externo_id: str,
    *,
    cur=None,
) -> Optional[Dict[str, Any]]:
    externo = str(mensaje_externo_id or "").strip()
    if not externo:
        return None
    with _cursor(cur) as c:
        c.execute(
            """
            SELECT *
            FROM chatbot.mensajes_conversacion
            WHERE agencia_id = %s
              AND conversacion_id = %s
              AND mensaje_externo_id = %s
            LIMIT 1
            """,
            (agencia_id, conversacion_id, externo),
        )
        return _fila(c.fetchone())


def contar_errores_ia_recientes(
    agencia_id: int, conversacion_id: int, limite: int = 10, *, cur=None
) -> int:
    with _cursor(cur) as c:
        c.execute(
            """
            SELECT COUNT(*) AS n
            FROM (
                SELECT id
                FROM chatbot.eventos_conversacion
                WHERE agencia_id = %s
                  AND conversacion_id = %s
                  AND tipo_evento = 'error'
                ORDER BY id DESC
                LIMIT %s
            ) t
            """,
            (agencia_id, conversacion_id, max(1, int(limite))),
        )
        row = c.fetchone()
        return int((row or {}).get("n") or 0)


def listar_pruebas_live_por_config(
    agencia_id: int,
    chatbot_configuracion_id: int,
    *,
    solo_activas: bool = False,
    cur=None,
) -> List[Dict[str, Any]]:
    """Lista pruebas LIVE cuyos flujos pertenecen a la configuración."""
    where = ["f.chatbot_configuracion_id = %s", "pl.agencia_id = %s"]
    params: List[Any] = [int(chatbot_configuracion_id), int(agencia_id)]
    if solo_activas:
        where.append("pl.activo = TRUE")
    sql = f"""
        SELECT pl.*
        FROM chatbot.pruebas_live_configuracion pl
        INNER JOIN chatbot.flujos_conversacionales f
            ON f.id = pl.flujo_id AND f.agencia_id = pl.agencia_id
        WHERE {' AND '.join(where)}
        ORDER BY pl.nombre ASC, pl.id ASC
    """
    with _cursor(cur) as c:
        c.execute(sql, params)
        return _filas(c.fetchall())


def actualizar_datos_explicitos_aspirante(
    agencia_id: int,
    aspirante_id: int,
    campos: Dict[str, Any],
    *,
    cur=None,
) -> Optional[Dict[str, Any]]:
    """
    Persiste datos declarados explícitamente por la persona (usuario, edad, LIVE).

    Nunca acepta cambios de estado del proceso (aprobado/descartado/etc.).
    """
    permitidos = {
        "usuario_plataforma",
        "mayor_edad",
        "disponibilidad_live",
        "disponibilidad",
    }
    prohibidos = {"estado", "aprobado", "descartado", "cumple_requisitos", "etapa_chatbot"}
    limpios: Dict[str, Any] = {}
    for clave, valor in (campos or {}).items():
        if clave in prohibidos:
            raise ErrorDatosConversacional(
                f"El asistente no puede modificar el campo '{clave}'"
            )
        if clave not in permitidos:
            continue
        limpios["disponibilidad_live" if clave == "disponibilidad" else clave] = valor

    if not limpios:
        return obtener_aspirante(int(agencia_id), int(aspirante_id), cur=cur)

    import database_chatbot_captacion as db_captacion

    actual = db_captacion.obtener_aspirante(int(agencia_id), int(aspirante_id))
    if not actual:
        raise ErrorDatosConversacional(
            "El aspirante no existe o no pertenece a la agencia"
        )
    return db_captacion.actualizar_aspirante_flujo_commit(int(aspirante_id), limpios)


def crear_tarea_candidato(
    agencia_id: int,
    conversacion_id: int,
    *,
    aspirante_id: Optional[int] = None,
    paso_flujo_id: Optional[int] = None,
    tipo_tarea: str,
    titulo: str,
    descripcion: Optional[str] = None,
    fecha_limite: Any = None,
    estado: str = "pendiente",
    creada_por_tipo: str = "chatbot",
    creada_por_id: Optional[int] = None,
    configuracion_recordatorio: Optional[Dict[str, Any]] = None,
    cur=None,
) -> Dict[str, Any]:
    """Alias usado por las herramientas del agente conversacional."""
    return crear_tarea(
        int(agencia_id),
        {
            "conversacion_id": int(conversacion_id),
            "aspirante_id": aspirante_id,
            "paso_flujo_id": paso_flujo_id,
            "tipo_tarea": tipo_tarea,
            "titulo": titulo,
            "descripcion": descripcion,
            "fecha_limite": fecha_limite,
            "estado": estado,
            "creada_por_tipo": creada_por_tipo,
            "creada_por_id": creada_por_id,
            "configuracion_recordatorio": configuracion_recordatorio or {},
        },
        cur=cur,
    )


def registrar_evidencia(
    agencia_id: int,
    conversacion_id: int,
    *,
    aspirante_id: Optional[int] = None,
    tarea_id: Optional[int] = None,
    mensaje_id: Optional[int] = None,
    evidencia_requerida_id: Optional[int] = None,
    tipo_evidencia: str,
    tipo_archivo: Optional[str] = None,
    archivo_url: Optional[str] = None,
    archivo_id_externo: Optional[str] = None,
    archivo_nombre: Optional[str] = None,
    mime_type: Optional[str] = None,
    valor_texto: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    estado_revision: str = "recibida",
    cur=None,
) -> Dict[str, Any]:
    """Alias usado por las herramientas del agente; nunca aprueba evidencias."""
    estado = str(estado_revision or "recibida").strip().lower()
    if estado in {"aprobada", "rechazada"}:
        raise ErrorDatosConversacional(
            "El asistente no puede aprobar ni rechazar evidencias"
        )
    return crear_evidencia(
        int(agencia_id),
        {
            "conversacion_id": int(conversacion_id),
            "aspirante_id": aspirante_id,
            "tarea_id": tarea_id,
            "mensaje_id": mensaje_id,
            "evidencia_requerida_id": evidencia_requerida_id,
            "tipo_evidencia": tipo_evidencia,
            "tipo_archivo": tipo_archivo,
            "archivo_url": archivo_url,
            "archivo_id_externo": archivo_id_externo,
            "archivo_nombre": archivo_nombre,
            "mime_type": mime_type,
            "valor_texto": valor_texto,
            "metadata": metadata or {},
            "estado_revision": estado if estado else "recibida",
        },
        cur=cur,
    )
