"""
IA: prompts, personalización, tarjetas y normalización (sin endpoints HTTP).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple, TypedDict

from fastapi import HTTPException

from performance_core import (
    PRIORIDADES_VALIDAS,
    TIPOS_ACCION_SUGERIDOS,
    _arquetipo_estrategia_contexto,
    _estrategia_json_de_arquetipo,
    _items_estrategia_arquetipo_por_categoria,
    _lista_desde_jsonb,
    _valor_a_texto_resumen,
    contexto_para_prompt,
    generar_recomendaciones_basicas,
    normalizar_lower,
    normalizar_texto_parrafos,
    performance_partidas_vacio,
    safe_float,
    validar_valor_en_set,
)

# =========================================================
# PROMPTS IA
# =========================================================

_REGLAS_ANTI_REPETICION_TARJETAS = """
REGLAS ANTI-REPETICIÓN ENTRE TARJETAS (obligatorio):
- horario: solo franja horaria, días fijos de transmisión y métrica a revisar en 7 días. No repitas intereses ni parrilla.
- emocional: reto semanal 3 lives, celebrar cumplimiento 3/3 antes de subir metas. Sin horario ni diamantes.
- disciplina: rutina mínima y preparación. NO repitas horario si ya hay tarjeta de horario.
- contenido: parrilla Live 1 / Live 2 / Live 3 con un interés por live. Sin horario ni partidas.
- interacción: 2 equipos, pregunta rápida, ranking simbólico y top 3 por ronda. Sin repetir «dividir equipos» dos veces.
- monetización: metas pequeñas por tramo (apertura, mitad del LIVE, cierre). Un interés como gancho.
"""


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

_TERMINOS_TECNICOS_PROHIBIDOS_MANAGER = (
    "estrategia_json",
    "arquetipo_estrategia",
    "perfil_estrategico",
    "performance_partidas",
    "según el json",
    "segun el json",
    "del json",
    "según el contexto",
    "segun el contexto",
    "del contexto",
    "la estrategia_json indica",
    "metadata",
    "sin dato de [",
    "sin dato de ",
    "% asociado a partidas",
    "diamantes_de_partidas supera diamantes_mes",
    "porcentaje asociado supera",
    "hilo operativo del live",
    "aplicada antes",
    "aplicada entre",
    "aplicada en",
)

_REGLAS_PROHIBIDO_LENGUAJE_TECNICO_MANAGER = """
PROHIBIDO escribir en el texto final visible al manager:
- "estrategia_json", "arquetipo_estrategia", "perfil_estrategico", "performance_partidas"
- "JSON", "del contexto", "según el JSON", "campo", "metadata"
- "la estrategia_json indica"

Usa lenguaje natural:
- "Según la estrategia del arquetipo..."
- "Como creadora/o Batallista..."
- "Por su perfil operativo..."
- "Por su rendimiento en partidas..."

Ejemplo INCORRECTO:
"La estrategia_json indica usar interacción tipo: dividir audiencia en equipos."

Ejemplo CORRECTO:
"Según la estrategia del arquetipo Batallista, conviene dividir la audiencia en equipos y usar rankings simbólicos."

No copies la definición larga completa del arquetipo en cada recomendación.
Resume el arquetipo en una sola frase operativa corta.
Si porcentaje_diamantes_por_partidas supera 100, NO lo presentes como porcentaje normal.
"""


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


def _items_estrategia_arquetipo(contexto: Dict[str, Any], clave: str, limit: int = 5) -> List[str]:
    estrategia = _arquetipo_estrategia_contexto(contexto)
    estrategia_json = estrategia.get("estrategia_json") if isinstance(estrategia, dict) else {}
    if not isinstance(estrategia_json, dict):
        return []
    return _lista_desde_jsonb(estrategia_json.get(clave))[:limit]


def _texto_estrategia_arquetipo_para_prompt(contexto: Dict[str, Any]) -> str:
    estrategia = _arquetipo_estrategia_contexto(contexto)
    if not estrategia:
        return "Sin estrategia operativa de arquetipo registrada en creadores_arquetipo."

    estrategia_json = estrategia.get("estrategia_json") or {}
    dinamicas = _lista_desde_jsonb(estrategia_json.get("dinamicas_recomendadas"))[:6]
    contenido = _lista_desde_jsonb(estrategia_json.get("estrategias_contenido"))[:5]
    interaccion = _lista_desde_jsonb(estrategia_json.get("estrategias_interaccion"))[:5]
    monetizacion = _lista_desde_jsonb(estrategia_json.get("estrategias_monetizacion"))[:5]
    evitar = _lista_desde_jsonb(estrategia_json.get("evitar"))[:5]
    instruccion = _valor_a_texto_resumen(estrategia_json.get("instruccion_ia"))

    partes = [
        f"Arquetipo operativo: {estrategia.get('nombre') or 'sin nombre'}",
        f"Código: {estrategia.get('codigo') or 'sin código'}",
    ]

    if estrategia.get("descripcion_operativa"):
        partes.append(f"Definición operativa: {estrategia.get('descripcion_operativa')}")
    if estrategia_json.get("estilo_live"):
        partes.append(f"Estilo LIVE: {estrategia_json.get('estilo_live')}")
    if dinamicas:
        partes.append("Dinámicas recomendadas: " + ", ".join(dinamicas))
    if contenido:
        partes.append("Estrategias de contenido: " + ", ".join(contenido))
    if interaccion:
        partes.append("Estrategias de interacción: " + ", ".join(interaccion))
    if monetizacion:
        partes.append("Estrategias de monetización: " + ", ".join(monetizacion))
    if evitar:
        partes.append("Evitar: " + ", ".join(evitar))
    if instruccion:
        partes.append("Instrucción IA: " + instruccion)

    return "\n".join(f"- {p}" for p in partes)


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
    estrategia_arquetipo = _arquetipo_estrategia_contexto(contexto)
    estrategia_prompt = _texto_estrategia_arquetipo_para_prompt(contexto)

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
    if estrategia_arquetipo:
        resumen_arq = _resumen_arquetipo_para_recomendacion(estrategia_arquetipo)
        checklist.append(f"- Resume el arquetipo en una frase operativa: {resumen_arq}")
    elif arquetipo:
        checklist.append(
            f"- Arquetipo declarado en encuesta (sin catálogo operativo en BD): {arquetipo}"
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
        datos_partidas_tmp = {
            "partidas": partidas.get("partidas"),
            "diamantes_por_partida": partidas.get("diamantes_por_partida"),
            "pct_diamantes_partidas": partidas.get("porcentaje_diamantes_por_partidas"),
            "advertencia_partidas": partidas.get("advertencia_partidas"),
            "diagnostico_partidas": diag_part,
        }
        checklist.append(
            "- Describe partidas en lenguaje de manager: "
            f"{_texto_partidas_para_manager(datos_partidas_tmp)}"
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
        'CORRECTO: "Como Nicolisita, su arquetipo pide competencia y retos visibles. '
        "Fitness: mini reto antes de la batalla. Música: votación de canción. "
        'Objetivo: comentarios, retención y regalos."'
    )

    return f"""
REGLAS OBLIGATORIAS DE PERSONALIZACIÓN (prioridad sobre cualquier otra instrucción):
{_REGLAS_PROHIBIDO_LENGUAJE_TECNICO_MANAGER}

Usa obligatoriamente los datos del contexto (arquetipo, intereses, horario, categoría, meta y partidas).

ARQUETIPO OPERATIVO (referencia interna; NO copies nombres técnicos ni la definición larga al manager):
{estrategia_prompt}

Checklist para ESTE creador:
{obligatorias}

PROHIBIDO usar frases vagas como:
{prohibidas}

REGLA ANTI-REPETICIÓN ENTRE CATEGORÍAS (tarjetas cortas):
- horario_preferido → solo horario / disciplina / emocional.
- arquetipo operativo → solo interacción (y una frase en audiencia o contenido si hace falta).
- partidas y meta de diamantes → solo monetización (horario: solo métrica de bloque).
- intereses: monetización ≤1 gancho; contenido = parrilla Live 1/2/3; interacción sin listar los 3.

{ejemplo_malo}
{ejemplo_bueno}

Cada párrafo, prioridad, recomendación o acción debe incluir datos concretos del checklist.
Si falta un dato, dilo en lenguaje natural (ej. "sin horario definido"); no cites nombres de campos internos.
"""


def _es_contexto_compacto_ia(contexto: Dict[str, Any]) -> bool:
    return (
        isinstance(contexto, dict)
        and "perfil" in contexto
        and "reporte" in contexto
        and "perfil_estrategico" not in contexto
    )


def _reporte_desde_contexto(contexto: Dict[str, Any]) -> Dict[str, Any]:
    reporte = contexto.get("ultimo_reporte") or contexto.get("reporte")
    return reporte if isinstance(reporte, dict) else {}


def _intereses_desde_perfil_compacto(perfil: Dict[str, Any]) -> List[str]:
    if not isinstance(perfil, dict):
        return []
    raw = perfil.get("intereses_multiples") or perfil.get("intereses")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        texto = raw.strip()
        if not texto:
            return []
        try:
            parsed = json.loads(texto)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
        return [texto]
    return [str(raw).strip()]


def _partidas_desde_reporte_compacto(reporte: Dict[str, Any]) -> Dict[str, Any]:
    """Campos de partidas desde columnas del reporte, sin diagnóstico calculado."""
    if not reporte:
        return performance_partidas_vacio()

    partidas = safe_float(reporte.get("partidas"))
    diamantes_de_partidas = safe_float(reporte.get("diamantes_de_partidas"))
    diamantes_mes = safe_float(reporte.get("diamantes_mes"))
    pct = (diamantes_de_partidas / diamantes_mes * 100) if diamantes_mes > 0 else 0.0

    return {
        "partidas": int(partidas) if partidas == int(partidas) else partidas,
        "diamantes_de_partidas": diamantes_de_partidas,
        "diamantes_mes": diamantes_mes,
        "diamantes_por_partida": round(diamantes_de_partidas / partidas, 2) if partidas > 0 else 0.0,
        "porcentaje_diamantes_por_partidas": round(pct, 2),
        "porcentaje_diamantes_por_partidas_visual": round(min(pct, 100), 2),
        "advertencia_partidas": None,
        "diagnostico_partidas": None,
    }


def _entero_metrica_recomendacion(valor: Any) -> Optional[int]:
    if valor is None or valor == "":
        return None
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return None


def _extraer_metricas_reporte_recomendaciones(contexto: Dict[str, Any]) -> Dict[str, Any]:
    reporte = contexto.get("reporte") or contexto.get("ultimo_reporte") or {}
    metas = contexto.get("metas") or {}
    categoria = contexto.get("categoria") or contexto.get("categoria_creador") or {}

    duracion = reporte.get("duracion_live_mes_minutos")
    if duracion is None:
        duracion = reporte.get("duracion_live_mes")

    return {
        "meta_mensual_diamantes": metas.get("meta_diamantes"),
        "meta_horas_live": metas.get("meta_horas_live"),
        "meta_dias_validos": metas.get("meta_dias_validos"),
        "meta_emisiones": metas.get("meta_emisiones"),
        "meta_nuevos_seguidores": metas.get("meta_nuevos_seguidores"),
        "meta_categoria_diamantes": categoria.get("meta_diamantes_objetivo"),
        "categoria_nombre": categoria.get("nombre"),
        "diamantes_mes": reporte.get("diamantes_mes"),
        "duracion_live_mes_minutos": duracion,
        "dias_validos_live_mes": reporte.get("dias_validos_live_mes")
        or reporte.get("dias_validos_mes"),
        "emisiones_live_mes": reporte.get("emisiones_live_mes"),
        "nuevos_seguidores_mes": reporte.get("nuevos_seguidores_mes"),
        "partidas": reporte.get("partidas"),
        "diamantes_de_partidas": reporte.get("diamantes_de_partidas"),
        "diamantes_modo_varios_invitados": reporte.get("diamantes_modo_varios_invitados"),
        "porcentaje_logro_diamantes": reporte.get("porcentaje_logro_diamantes"),
        "porcentaje_logro_duracion_live": reporte.get("porcentaje_logro_duracion_live"),
        "porcentaje_logro_dias_validos": reporte.get("porcentaje_logro_dias_validos"),
        "porcentaje_logro_emisiones": reporte.get("porcentaje_logro_emisiones"),
        "porcentaje_logro_nuevos_seguidores": reporte.get("porcentaje_logro_nuevos_seguidores"),
    }


def _buscar_valor_perfil_compacto(perfil: Dict[str, Any], campo: str) -> Optional[Any]:
    if not isinstance(perfil, dict):
        return None

    if campo in perfil:
        return perfil.get(campo)

    for categoria_data in perfil.values():
        if not isinstance(categoria_data, dict):
            continue
        item = categoria_data.get(campo)
        if isinstance(item, dict):
            return item.get("valor")
        if item is not None:
            return item

    return None


_ETIQUETAS_SENALES_PERFIL = {
    "horario_preferido": "Horario preferido",
    "equipo_iluminacion": "Equipo e iluminación",
    "dominio_herramientas": "Herramientas LIVE",
    "calidad_produccion_video": "Producción de video",
    "fluidez_habla": "Fluidez hablando",
    "multitask_chat": "Manejo de chat/multitarea",
    "reaccion_crisis": "Reacción en crisis",
    "energia_vivos_largos": "Energía en vivos largos",
    "dias_horas_garantia": "Disponibilidad semanal",
    "feedback_inmediato": "Feedback inmediato",
    "normas_comunidad_tk": "Normas de comunidad TikTok",
    "analisis_metricas": "Análisis de métricas",
    "frecuencia_videos": "Frecuencia de videos",
    "pedir_regalos_metas": "Pedir regalos/metas",
    "actitud_pk_batallas": "Actitud frente a batallas",
    "constancia_crecimiento_lento": "Constancia y crecimiento",
    "experiencia_graduacion": "Experiencia en la agencia",
    "red_amigos_invitados": "Red de amigos/invitados",
    "impacto_agencia": "Impacto de la agencia",
    "kpi_compliance_real": "Cumplimiento real",
    "kpi_monetizacion_live": "Monetización en LIVE",
    "kpi_uso_operativo": "Uso operativo de funciones LIVE",
    "kpi_calidad_tecnica": "Calidad técnica",
    "arquetipo_valor": "Arquetipo declarado",
    "intereses_multiples": "Intereses principales",
}


def _extraer_senales_perfil_recomendaciones(contexto: Dict[str, Any]) -> Dict[str, Any]:
    perfil = contexto.get("perfil") or {}
    campos = (
        "horario_preferido",
        "equipo_iluminacion",
        "dominio_herramientas",
        "calidad_produccion_video",
        "fluidez_habla",
        "multitask_chat",
        "reaccion_crisis",
        "energia_vivos_largos",
        "dias_horas_garantia",
        "feedback_inmediato",
        "normas_comunidad_tk",
        "analisis_metricas",
        "frecuencia_videos",
        "pedir_regalos_metas",
        "actitud_pk_batallas",
        "constancia_crecimiento_lento",
        "experiencia_graduacion",
        "red_amigos_invitados",
        "impacto_agencia",
        "kpi_compliance_real",
        "kpi_monetizacion_live",
        "kpi_uso_operativo",
        "kpi_calidad_tecnica",
        "arquetipo_valor",
        "intereses_multiples",
    )
    senales: Dict[str, Any] = {}
    for campo in campos:
        valor = _buscar_valor_perfil_compacto(perfil, campo)
        if valor is not None and valor != "":
            senales[campo] = valor
    return senales


def _bloque_metricas_recomendaciones(contexto: Dict[str, Any]) -> str:
    metricas = _extraer_metricas_reporte_recomendaciones(contexto)
    lineas = ["MÉTRICAS Y METAS DISPONIBLES:"]

    def _linea(etiqueta: str, clave: str) -> None:
        valor = metricas.get(clave)
        if valor is not None and valor != "":
            entero = _entero_metrica_recomendacion(valor)
            lineas.append(f"- {etiqueta}: {entero if entero is not None else valor}")

    _linea("Meta mensual diamantes", "meta_mensual_diamantes")
    _linea("Diamantes del periodo", "diamantes_mes")
    _linea("Partidas", "partidas")
    _linea("Diamantes de partidas", "diamantes_de_partidas")
    _linea("Emisiones LIVE mes", "emisiones_live_mes")
    _linea("Días válidos LIVE mes", "dias_validos_live_mes")
    _linea("Duración LIVE mes minutos", "duracion_live_mes_minutos")
    _linea("Nuevos seguidores mes", "nuevos_seguidores_mes")
    _linea("Meta nuevos seguidores", "meta_nuevos_seguidores")
    _linea("Meta horas LIVE", "meta_horas_live")
    _linea("Meta emisiones", "meta_emisiones")
    if metricas.get("categoria_nombre"):
        lineas.append(
            f"- Categoría referencia (no usar como meta principal): "
            f"{metricas.get('categoria_nombre')} "
            f"({_entero_metrica_recomendacion(metricas.get('meta_categoria_diamantes')) or 'sin meta'} diamantes)"
        )

    return "\n".join(lineas)


def _bloque_senales_perfil_recomendaciones(contexto: Dict[str, Any]) -> str:
    senales = _extraer_senales_perfil_recomendaciones(contexto)
    if not senales:
        return "SEÑALES DEL PERFIL DEL CREADOR:\n- Sin señales de perfil disponibles."

    lineas = ["SEÑALES DEL PERFIL DEL CREADOR:"]
    for campo, valor in senales.items():
        etiqueta = _ETIQUETAS_SENALES_PERFIL.get(campo, campo.replace("_", " "))
        if isinstance(valor, list):
            valor_txt = ", ".join(str(v) for v in valor)
        else:
            valor_txt = str(valor)
        lineas.append(f"- {etiqueta}: {valor_txt}")

    intereses = contexto.get("perfil", {}).get("intereses_multiples") if isinstance(
        contexto.get("perfil"), dict
    ) else None
    if intereses and "intereses_multiples" not in senales:
        if isinstance(intereses, list):
            lineas.append(f"- Intereses principales: {', '.join(str(i) for i in intereses)}")
        else:
            lineas.append(f"- Intereses principales: {intereses}")

    return "\n".join(lineas)


def _texto_menciona_meta_categoria_como_objetivo(texto: str, contexto: Dict[str, Any]) -> bool:
    metricas = _extraer_metricas_reporte_recomendaciones(contexto)
    cat = str(metricas.get("categoria_nombre") or "").lower()
    meta_cat = _entero_metrica_recomendacion(metricas.get("meta_categoria_diamantes"))
    diamantes = _entero_metrica_recomendacion(metricas.get("diamantes_mes"))
    tl = (texto or "").lower()
    if not cat or not meta_cat:
        return False
    if diamantes and diamantes >= meta_cat:
        if f"{meta_cat}" in tl.replace(",", "") or f"bronce" in tl and str(meta_cat) in tl:
            return True
    return False


def _normalizar_numero_para_validacion(valor: Any) -> List[str]:
    if valor is None or valor == "":
        return []

    variantes: List[str] = []

    try:
        numero = float(valor)
        if numero.is_integer():
            variantes.append(str(int(numero)))
        else:
            variantes.append(str(numero))
            variantes.append(str(numero).rstrip("0").rstrip("."))
    except Exception:
        texto = str(valor).strip()
        if texto:
            variantes.append(texto)

    salida: List[str] = []
    for item in variantes:
        limpio = (
            str(item)
            .lower()
            .replace(",", "")
            .replace(".", "")
            .replace(" ", "")
        )
        if limpio and limpio not in salida:
            salida.append(limpio)

    return salida


def _recomendacion_usa_metricas_reporte(
    rec: Dict[str, Any],
    contexto: Dict[str, Any],
) -> bool:
    texto = (
        f"{rec.get('recomendacion') or ''} {rec.get('justificacion') or ''}"
    ).lower()

    texto_norm = (
        texto
        .replace(",", "")
        .replace(".", "")
        .replace(" ", "")
    )

    metricas = _extraer_metricas_reporte_recomendaciones(contexto)

    valores_operativos = [
        metricas.get("meta_mensual_diamantes"),
        metricas.get("meta_horas_live"),
        metricas.get("meta_dias_validos"),
        metricas.get("meta_emisiones"),
        metricas.get("meta_nuevos_seguidores"),
        metricas.get("diamantes_mes"),
        metricas.get("duracion_live_mes_minutos"),
        metricas.get("dias_validos_live_mes"),
        metricas.get("emisiones_live_mes"),
        metricas.get("nuevos_seguidores_mes"),
        metricas.get("partidas"),
        metricas.get("diamantes_de_partidas"),
        metricas.get("porcentaje_logro_diamantes"),
        metricas.get("porcentaje_logro_duracion_live"),
        metricas.get("porcentaje_logro_dias_validos"),
        metricas.get("porcentaje_logro_emisiones"),
        metricas.get("porcentaje_logro_nuevos_seguidores"),
    ]

    for valor in valores_operativos:
        for variante in _normalizar_numero_para_validacion(valor):
            if variante and variante in texto_norm:
                return True

    return False


def _recomendacion_usa_meta_categoria_prohibida(
    rec: Dict[str, Any],
    contexto: Dict[str, Any],
) -> bool:
    texto = (
        f"{rec.get('recomendacion') or ''} {rec.get('justificacion') or ''}"
    ).lower().replace(",", "")

    metricas = _extraer_metricas_reporte_recomendaciones(contexto)

    meta_mensual = _entero_metrica_recomendacion(metricas.get("meta_mensual_diamantes"))
    meta_categoria = _entero_metrica_recomendacion(metricas.get("meta_categoria_diamantes"))
    categoria = str(metricas.get("categoria_nombre") or "").lower()

    if not meta_mensual or not meta_categoria:
        return False

    if str(meta_categoria) in texto:
        return True

    if categoria and categoria in texto and "meta" in texto:
        return True

    return False


def _recomendacion_usa_senal_perfil(
    rec: Dict[str, Any],
    contexto: Dict[str, Any],
) -> bool:
    texto = (
        f"{rec.get('recomendacion') or ''} {rec.get('justificacion') or ''}"
    ).lower()
    palabras = (
        "fluidez",
        "chat",
        "leer",
        "comentario",
        "energía",
        "energia",
        "primera hora",
        "iluminación",
        "iluminacion",
        "luz",
        "celular",
        "herramienta",
        "funciones live",
        "setup",
        "feedback",
        "métricas",
        "metricas",
        "video",
        "regalo",
        "batalla",
        " pk",
        "frustración",
        "frustracion",
        "normas",
        "cumplimiento",
        "pedir",
        "comodidad",
        "encuadre",
        "portada",
        "multitarea",
        "distrae",
    )
    if any(p in texto for p in palabras):
        return True
    senales = _extraer_senales_perfil_recomendaciones(contexto)
    for valor in senales.values():
        fragmento = str(valor).lower()[:40]
        if fragmento and len(fragmento) > 3 and fragmento in texto:
            return True
    return False


def _recomendacion_es_buena_ia(
    rec: Dict[str, Any],
    contexto: Dict[str, Any],
) -> bool:
    categoria = _normalizar_categoria_recomendacion(rec.get("categoria") or "otro")
    texto_rec = str(rec.get("recomendacion") or "").strip()
    texto_just = str(rec.get("justificacion") or "").strip()
    texto_union = f"{texto_rec} {texto_just}"

    if not texto_rec:
        return False
    if _es_texto_recomendacion_generico(texto_rec):
        return False
    if any(p in texto_union.lower() for p in _TERMINOS_TECNICOS_PROHIBIDOS_MANAGER):
        return False
    if (
        _texto_menciona_meta_categoria_como_objetivo(texto_union, contexto)
        or _recomendacion_usa_meta_categoria_prohibida(rec, contexto)
    ):
        return False
    if len(texto_rec) < 40:
        return False

    usa_metrica = _recomendacion_usa_metricas_reporte(rec, contexto)
    usa_perfil = _recomendacion_usa_senal_perfil(rec, contexto)
    if not usa_metrica and not usa_perfil:
        return False

    return True


def _fallback_monetizacion_con_metricas_perfil(contexto: Dict[str, Any]) -> Dict[str, Any]:
    metricas = _extraer_metricas_reporte_recomendaciones(contexto)
    senales = _extraer_senales_perfil_recomendaciones(contexto)

    meta = _entero_metrica_recomendacion(metricas.get("meta_mensual_diamantes"))
    diamantes = _entero_metrica_recomendacion(metricas.get("diamantes_mes"))
    partidas = _entero_metrica_recomendacion(metricas.get("partidas"))
    diamantes_partidas = _entero_metrica_recomendacion(metricas.get("diamantes_de_partidas"))

    rec_parts = []
    if meta:
        rec_parts.append(
            f"Dividir la meta mensual de {meta} diamantes en objetivos por bloque de LIVE: "
            "apertura con meta rápida de regalos, mitad del directo con batallas cortas guiadas "
            "y cierre con reto final entre equipos."
        )
    else:
        rec_parts.append(
            "Dividir la monetización del periodo en objetivos por bloque de LIVE: "
            "apertura con meta rápida de regalos, mitad del directo con batallas cortas guiadas "
            "y cierre con reto final entre equipos."
        )

    if senales.get("pedir_regalos_metas") or senales.get("actitud_pk_batallas"):
        rec_parts.append(
            "Como pedir regalos le cuesta un poco y su comodidad con batallas es baja, "
            "el manager debe darle frases simples y repetibles para cada tramo."
        )

    just_parts = []
    if diamantes is not None:
        just_parts.append(f"El creador acumuló {diamantes} diamantes en el periodo")
    if diamantes_partidas is not None and partidas is not None:
        just_parts.append(
            f"las partidas generaron {diamantes_partidas} diamantes en {partidas} partidas"
        )
    if just_parts:
        justificacion = (
            f"{just_parts[0]} y {just_parts[1]}, señal de que las dinámicas competitivas "
            "están impulsando el rendimiento actual."
            if len(just_parts) > 1
            else f"{just_parts[0]}, señal de que las dinámicas competitivas impulsan el rendimiento."
        )
    else:
        justificacion = "Las métricas del periodo muestran oportunidad de convertir la energía del LIVE en apoyo concreto de la audiencia."

    return {
        "categoria": "monetizacion",
        "prioridad": "alta",
        "recomendacion": " ".join(rec_parts),
        "justificacion": justificacion,
    }


def _fallback_interaccion_con_perfil(contexto: Dict[str, Any]) -> Dict[str, Any]:
    senales = _extraer_senales_perfil_recomendaciones(contexto)
    just = (
        "Tiene muy buena fluidez hablando y puede sostener energía en cámara, "
        "pero se distrae fácilmente al leer el chat y manejar varias cosas al mismo tiempo."
    )
    if senales.get("fluidez_habla"):
        just = (
            f"Con fluidez hablando {senales.get('fluidez_habla')}, puede sostener energía en cámara, "
            "pero se distrae al leer el chat y manejar varias cosas al mismo tiempo."
        )
    return {
        "categoria": "interaccion",
        "prioridad": "alta",
        "recomendacion": (
            "Usar dinámicas simples antes de cada batalla: dividir el chat en 2 equipos, "
            "hacer una pregunta rápida y reconocer al top 3 de comentarios o apoyos al terminar cada ronda. "
            "Evitar mecánicas complejas que obliguen al creador a detener el show para leer."
        ),
        "justificacion": just,
    }


def _fallback_contenido_con_intereses_perfil(contexto: Dict[str, Any]) -> Dict[str, Any]:
    intereses = _intereses_desde_perfil_compacto(contexto.get("perfil") or {})
    if len(intereses) >= 3:
        i1, i2, i3 = intereses[0], intereses[1], intereses[2]
        parrilla = (
            f"Organizar una mini parrilla semanal: Live 1 — retos de {i1} donde el chat desbloquea momentos con regalos. "
            f"Live 2 — desafíos de {i2} por equipos con mini castigos al perder. "
            f"Live 3 — {i3} contra reloj con decisiones del chat para cada cambio."
        )
        just = (
            f"Sus intereses principales son {i1}, {i2} y {i3}."
        )
    elif intereses:
        parrilla = f"Organizar tres lives con variaciones de {intereses[0]} y dinámicas concretas por live."
        just = f"Su interés principal es {intereses[0]}."
    else:
        parrilla = "Organizar una mini parrilla semanal con tres formatos distintos y dinámicas concretas por live."
        just = "Conviene anclar cada live a un formato visible desde el inicio."

    senales = _extraer_senales_perfil_recomendaciones(contexto)
    if senales.get("calidad_produccion_video") and senales.get("frecuencia_videos"):
        parrilla += (
            " Además, reutilizar momentos fuertes de cada LIVE para aumentar "
            "la frecuencia de clips durante la semana."
        )
        just += (
            f" Además, tiene producción de video {senales.get('calidad_produccion_video')}, "
            f"pero actualmente publica {senales.get('frecuencia_videos')}."
        )

    return {
        "categoria": "contenido",
        "prioridad": "media",
        "recomendacion": parrilla,
        "justificacion": just,
    }


def _fallback_audiencia_con_metricas_perfil(contexto: Dict[str, Any]) -> Dict[str, Any]:
    metricas = _extraer_metricas_reporte_recomendaciones(contexto)
    senales = _extraer_senales_perfil_recomendaciones(contexto)
    nuevos = _entero_metrica_recomendacion(metricas.get("nuevos_seguidores_mes"))
    meta_seg = _entero_metrica_recomendacion(metricas.get("meta_nuevos_seguidores"))

    just = "El creador necesita convertir mejor la audiencia actual en seguidores recurrentes."
    if nuevos is not None:
        just = f"El creador consiguió {nuevos} nuevos seguidores en el periodo"
        if meta_seg:
            just += f", todavía lejos de la meta mensual de {meta_seg}."
    if senales.get("red_amigos_invitados"):
        just += f" Además, su red de contactos aparece como {senales.get('red_amigos_invitados')}."

    return {
        "categoria": "audiencia",
        "prioridad": "alta",
        "recomendacion": (
            "Cerrar cada LIVE anunciando un reto o duelo exclusivo para el siguiente directo y pedir follow "
            "antes de iniciar cada partida importante. El manager debe medir qué dinámica convierte más "
            "espectadores en seguidores recurrentes."
        ),
        "justificacion": just,
    }


def _fallback_tecnica_con_perfil(contexto: Dict[str, Any]) -> Dict[str, Any]:
    senales = _extraer_senales_perfil_recomendaciones(contexto)
    just = (
        "Aunque su calidad de producción general es alta, su calidad técnica en LIVE "
        "todavía es funcional pero mejorable."
    )
    if senales.get("equipo_iluminacion"):
        just = (
            f"Actualmente transmite con {senales.get('equipo_iluminacion')}. "
            f"Aunque su producción de video es {senales.get('calidad_produccion_video', 'buena')}, "
            "su setup de LIVE necesita mejoras simples."
        )
    if senales.get("kpi_uso_operativo"):
        just += f" Su uso operativo de funciones LIVE aparece como {senales.get('kpi_uso_operativo')}."

    return {
        "categoria": "tecnica",
        "prioridad": "media",
        "recomendacion": (
            "Priorizar mejoras simples esta semana: agregar aro de luz o iluminación frontal fija, "
            "mantener un encuadre estable y preparar una portada clara para cada LIVE con el reto principal visible. "
            "También usar un checklist básico antes de iniciar transmisión."
        ),
        "justificacion": just,
    }


def _fallback_emocional_con_perfil(contexto: Dict[str, Any]) -> Dict[str, Any]:
    senales = _extraer_senales_perfil_recomendaciones(contexto)
    just = "Conviene sostener energía y ritmo sin saturar al creador."
    if senales.get("energia_vivos_largos"):
        just = (
            f"Su energía en vivos largos aparece como {senales.get('energia_vivos_largos')}. "
            "Conviene concentrar retos fuertes al inicio y usar pausas estratégicas."
        )
    if senales.get("constancia_crecimiento_lento"):
        just += f" También muestra {senales.get('constancia_crecimiento_lento')}."
    if senales.get("feedback_inmediato"):
        just += " Aplica bien el feedback inmediato cuando se le indica."

    return {
        "categoria": "emocional",
        "prioridad": "alta",
        "recomendacion": (
            "Concentrar los retos más fuertes durante la primera hora, hacer pausas estratégicas después "
            "y celebrar en voz alta cada avance antes de subir la exigencia."
        ),
        "justificacion": just,
    }


def _fallback_disciplina_con_metricas_perfil(contexto: Dict[str, Any]) -> Dict[str, Any]:
    senales = _extraer_senales_perfil_recomendaciones(contexto)
    metricas = _extraer_metricas_reporte_recomendaciones(contexto)

    emisiones = _entero_metrica_recomendacion(metricas.get("emisiones_live_mes"))
    meta_emisiones = _entero_metrica_recomendacion(metricas.get("meta_emisiones"))
    dias = _entero_metrica_recomendacion(metricas.get("dias_validos_live_mes"))
    meta_dias = _entero_metrica_recomendacion(metricas.get("meta_dias_validos"))
    duracion = _entero_metrica_recomendacion(metricas.get("duracion_live_mes_minutos"))
    meta_horas = _entero_metrica_recomendacion(metricas.get("meta_horas_live"))

    recomendacion = (
        "Cerrar cada LIVE con una revisión de 5 minutos: diamantes, nuevos seguidores, "
        "duración, partidas y una mejora concreta para la siguiente transmisión."
    )

    partes: List[str] = []

    if emisiones is not None:
        if meta_emisiones is not None:
            partes.append(f"{emisiones} emisiones frente a una meta de {meta_emisiones}")
        else:
            partes.append(f"{emisiones} emisiones")

    if dias is not None:
        if meta_dias is not None:
            partes.append(f"{dias} días válidos frente a una meta de {meta_dias}")
        else:
            partes.append(f"{dias} días válidos")

    if duracion is not None:
        partes.append(f"{duracion} minutos de transmisión")

    if meta_horas is not None:
        partes.append(f"meta de {meta_horas} horas LIVE")

    if partes:
        justificacion = (
            "El reporte muestra "
            + ", ".join(partes)
            + "; por eso el foco debe pasar de actividad a productividad por LIVE."
        )
    else:
        justificacion = (
            "El análisis de métricas es regular; una revisión constante puede ayudar "
            "a convertir cada transmisión en aprendizaje operativo."
        )

    if senales.get("analisis_metricas"):
        justificacion += f" Además, su análisis de métricas aparece como {senales.get('analisis_metricas')}."

    if senales.get("feedback_inmediato"):
        justificacion += " Como aplica correcciones de inmediato, el manager puede asignar mejoras semanales."

    return {
        "categoria": "disciplina",
        "prioridad": "media",
        "recomendacion": recomendacion,
        "justificacion": justificacion,
    }


_FALLBACK_INTELIGENTE_POR_CATEGORIA: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "monetizacion": _fallback_monetizacion_con_metricas_perfil,
    "interaccion": _fallback_interaccion_con_perfil,
    "contenido": _fallback_contenido_con_intereses_perfil,
    "audiencia": _fallback_audiencia_con_metricas_perfil,
    "tecnica": _fallback_tecnica_con_perfil,
    "emocional": _fallback_emocional_con_perfil,
    "disciplina": _fallback_disciplina_con_metricas_perfil,
}


def _fallback_inteligente_por_categoria(
    contexto: Dict[str, Any],
    categoria: str,
    prioridad: str = "media",
) -> Optional[Dict[str, Any]]:
    cat = _normalizar_categoria_recomendacion(categoria)
    builder = _FALLBACK_INTELIGENTE_POR_CATEGORIA.get(cat)
    if not builder:
        return None
    rec = builder(contexto)
    rec["prioridad"] = _ajustar_prioridad_recomendacion(contexto, prioridad, cat)
    return rec


def _reforzar_recomendaciones_metricas_y_perfil_si_falta(
    resultado: Dict[str, Any],
    contexto: Dict[str, Any],
    max_recomendaciones: int = 5,
) -> Dict[str, Any]:
    if not isinstance(resultado, dict):
        return {"recomendaciones": []}

    recs = resultado.get("recomendaciones")
    if not isinstance(recs, list):
        return {"recomendaciones": []}

    por_categoria: Dict[str, Dict[str, Any]] = {}
    firmas: set = set()

    for rec in recs:
        if not isinstance(rec, dict):
            continue

        cat = _normalizar_categoria_recomendacion(rec.get("categoria") or "otro")
        if cat == "otro":
            continue

        rec_limpia = {
            "categoria": cat,
            "prioridad": rec.get("prioridad") or "media",
            "recomendacion": rec.get("recomendacion") or "",
            "justificacion": rec.get("justificacion") or "",
        }

        texto = rec_limpia.get("recomendacion") or ""
        firma = re.sub(r"\W+", "", texto.lower())[:200]
        if not texto or firma in firmas:
            continue

        firmas.add(firma)
        por_categoria[cat] = rec_limpia

    def _reemplazar_categoria(
        cat: str,
        builder: Callable[[Dict[str, Any]], Dict[str, Any]],
    ) -> None:
        fb = builder(contexto)
        fb["categoria"] = cat
        fb["prioridad"] = _ajustar_prioridad_recomendacion(
            contexto,
            fb.get("prioridad") or "media",
            cat,
        )
        por_categoria[cat] = fb

    rec_monetizacion = por_categoria.get("monetizacion")
    if (
        not rec_monetizacion
        or not _recomendacion_usa_metricas_reporte(rec_monetizacion, contexto)
        or _recomendacion_usa_meta_categoria_prohibida(rec_monetizacion, contexto)
    ):
        _reemplazar_categoria("monetizacion", _fallback_monetizacion_con_metricas_perfil)

    rec_audiencia = por_categoria.get("audiencia")
    if (
        not rec_audiencia
        or not _recomendacion_usa_metricas_reporte(rec_audiencia, contexto)
    ):
        _reemplazar_categoria("audiencia", _fallback_audiencia_con_metricas_perfil)

    rec_interaccion = por_categoria.get("interaccion")
    if (
        not rec_interaccion
        or not _recomendacion_usa_senal_perfil(rec_interaccion, contexto)
    ):
        _reemplazar_categoria("interaccion", _fallback_interaccion_con_perfil)

    rec_tecnica = por_categoria.get("tecnica")
    if rec_tecnica and not _recomendacion_usa_senal_perfil(rec_tecnica, contexto):
        _reemplazar_categoria("tecnica", _fallback_tecnica_con_perfil)

    rec_disciplina = por_categoria.get("disciplina")
    rec_horario = por_categoria.get("horario")

    disciplina_ok = bool(
        rec_disciplina and _recomendacion_usa_metricas_reporte(rec_disciplina, contexto)
    )
    horario_ok = bool(
        rec_horario and _recomendacion_usa_metricas_reporte(rec_horario, contexto)
    )

    if not disciplina_ok and not horario_ok:
        if "disciplina" in por_categoria:
            _reemplazar_categoria("disciplina", _fallback_disciplina_con_metricas_perfil)
        else:
            _reemplazar_categoria("disciplina", _fallback_disciplina_con_metricas_perfil)

    orden_metricas_refuerzo = [
        ("disciplina", _fallback_disciplina_con_metricas_perfil),
        ("audiencia", _fallback_audiencia_con_metricas_perfil),
        ("monetizacion", _fallback_monetizacion_con_metricas_perfil),
    ]

    for cat, builder in orden_metricas_refuerzo:
        cuenta_metricas = sum(
            1 for r in por_categoria.values()
            if _recomendacion_usa_metricas_reporte(r, contexto)
        )
        if cuenta_metricas >= 3:
            break

        rec_actual = por_categoria.get(cat)
        if not rec_actual or not _recomendacion_usa_metricas_reporte(rec_actual, contexto):
            _reemplazar_categoria(cat, builder)

    orden_perfil_refuerzo = [
        ("emocional", _fallback_emocional_con_perfil),
        ("interaccion", _fallback_interaccion_con_perfil),
        ("tecnica", _fallback_tecnica_con_perfil),
    ]

    for cat, builder in orden_perfil_refuerzo:
        cuenta_perfil = sum(
            1 for r in por_categoria.values()
            if _recomendacion_usa_senal_perfil(r, contexto)
        )
        if cuenta_perfil >= 3:
            break

        rec_actual = por_categoria.get(cat)
        if not rec_actual or not _recomendacion_usa_senal_perfil(rec_actual, contexto):
            if cat in por_categoria:
                _reemplazar_categoria(cat, builder)
            elif len(por_categoria) < max_recomendaciones:
                _reemplazar_categoria(cat, builder)

    orden = [
        "monetizacion",
        "interaccion",
        "contenido",
        "audiencia",
        "tecnica",
        "emocional",
        "disciplina",
        "horario",
    ]

    salida: List[Dict[str, Any]] = []
    for cat in orden:
        if cat in por_categoria:
            salida.append(por_categoria[cat])

    resultado["recomendaciones"] = salida[:max_recomendaciones]
    return resultado


def _extraer_datos_desde_contexto_compacto(contexto: Dict[str, Any]) -> Dict[str, Any]:
    creador = contexto.get("creador") or {}
    categoria = contexto.get("categoria") or {}
    arquetipo_row = contexto.get("arquetipo") or {}
    perfil = contexto.get("perfil") or {}
    reporte = _reporte_desde_contexto(contexto)
    partidas = _partidas_desde_reporte_compacto(reporte)

    intereses_lista = _intereses_desde_perfil_compacto(perfil)
    estrategia_json = arquetipo_row.get("estrategia_json") or {}
    if isinstance(estrategia_json, str):
        try:
            estrategia_json = json.loads(estrategia_json)
        except Exception:
            estrategia_json = {}
    if not isinstance(estrategia_json, dict):
        estrategia_json = {}

    arquetipo_estrategia = None
    if arquetipo_row:
        arquetipo_estrategia = {
            "codigo": arquetipo_row.get("codigo"),
            "nombre": arquetipo_row.get("nombre"),
            "descripcion_operativa": arquetipo_row.get("descripcion_operativa"),
            "estrategia_json": estrategia_json,
        }

    nombre = (
        creador.get("nombre_artistico")
        or creador.get("nickname")
        or creador.get("nombre")
        or creador.get("usuario_tiktok")
        or creador.get("usuario")
        or "el creador"
    )
    arquetipo_nombre = (
        arquetipo_row.get("nombre")
        or perfil.get("arquetipo_valor")
        or perfil.get("arquetipo_definicion")
    )
    horario = perfil.get("horario_preferido")
    if isinstance(horario, dict):
        horario = horario.get("label") or horario.get("nombre") or horario.get("valor")

    n_partidas = safe_float(partidas.get("partidas"))
    d_partidas = safe_float(partidas.get("diamantes_de_partidas"))
    texto_partidas = (
        f"{int(n_partidas)} partidas y {int(d_partidas)} diamantes asociados a batallas en el periodo."
        if n_partidas > 0
        else "Sin partidas registradas en el periodo del reporte."
    )

    metas = contexto.get("metas") or {}
    meta_mensual_diamantes = metas.get("meta_diamantes")
    meta_categoria_diamantes = categoria.get("meta_diamantes_objetivo")

    return {
        "nombre_creador": nombre,
        "arquetipo": arquetipo_nombre,
        "intereses_lista": intereses_lista,
        "intereses": ", ".join(intereses_lista) if intereses_lista else None,
        "horario": horario,
        "categoria_nombre": categoria.get("nombre"),
        "meta_diamantes": meta_mensual_diamantes,
        "meta_mensual_diamantes": meta_mensual_diamantes,
        "meta_categoria_diamantes": meta_categoria_diamantes,
        "partidas": partidas.get("partidas"),
        "pct_diamantes_partidas": partidas.get("porcentaje_diamantes_por_partidas"),
        "diagnostico_partidas": None,
        "diamantes_por_partida": partidas.get("diamantes_por_partida"),
        "arquetipo_codigo": arquetipo_row.get("codigo"),
        "arquetipo_descripcion": arquetipo_row.get("descripcion_operativa"),
        "arquetipo_estilo_live": estrategia_json.get("estilo_live"),
        "arquetipo_dinamicas": _lista_desde_jsonb(estrategia_json.get("dinamicas_recomendadas")),
        "arquetipo_contenido": _lista_desde_jsonb(estrategia_json.get("estrategias_contenido")),
        "arquetipo_interaccion": _lista_desde_jsonb(estrategia_json.get("estrategias_interaccion")),
        "arquetipo_monetizacion": _lista_desde_jsonb(estrategia_json.get("estrategias_monetizacion")),
        "arquetipo_evitar": _lista_desde_jsonb(estrategia_json.get("evitar")),
        "arquetipo_instruccion_ia": estrategia_json.get("instruccion_ia"),
        "advertencia_partidas": None,
        "arquetipo_estrategia": arquetipo_estrategia,
        "resumen_arquetipo": _resumen_arquetipo_para_recomendacion(arquetipo_estrategia),
        "texto_partidas_manager": texto_partidas,
        "diamantes_mes": reporte.get("diamantes_mes"),
        "diamantes_de_partidas": partidas.get("diamantes_de_partidas"),
        "metas": metas,
    }


def _extraer_datos_personalizacion_recomendaciones(contexto: Dict[str, Any]) -> Dict[str, Any]:
    if _es_contexto_compacto_ia(contexto):
        return _extraer_datos_desde_contexto_compacto(contexto)

    perfil = contexto.get("perfil_estrategico") or {}
    categoria = contexto.get("categoria_creador") or {}
    partidas = contexto.get("performance_partidas") or performance_partidas_vacio()
    intereses_lista = _intereses_texto(perfil)
    estrategia_arquetipo = _arquetipo_estrategia_contexto(contexto)
    estrategia_json = estrategia_arquetipo.get("estrategia_json") if estrategia_arquetipo else {}
    if not isinstance(estrategia_json, dict):
        estrategia_json = {}

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
        "arquetipo_codigo": estrategia_arquetipo.get("codigo"),
        "arquetipo_descripcion": estrategia_arquetipo.get("descripcion_operativa"),
        "arquetipo_estilo_live": estrategia_json.get("estilo_live"),
        "arquetipo_dinamicas": _lista_desde_jsonb(estrategia_json.get("dinamicas_recomendadas")),
        "arquetipo_contenido": _lista_desde_jsonb(estrategia_json.get("estrategias_contenido")),
        "arquetipo_interaccion": _lista_desde_jsonb(estrategia_json.get("estrategias_interaccion")),
        "arquetipo_monetizacion": _lista_desde_jsonb(estrategia_json.get("estrategias_monetizacion")),
        "arquetipo_evitar": _lista_desde_jsonb(estrategia_json.get("evitar")),
        "arquetipo_instruccion_ia": estrategia_json.get("instruccion_ia"),
        "advertencia_partidas": partidas.get("advertencia_partidas"),
        "arquetipo_estrategia": estrategia_arquetipo or None,
        "resumen_arquetipo": _resumen_arquetipo_para_recomendacion(estrategia_arquetipo),
        "texto_partidas_manager": _texto_partidas_para_manager({
            "partidas": partidas.get("partidas"),
            "diamantes_por_partida": partidas.get("diamantes_por_partida"),
            "pct_diamantes_partidas": partidas.get("porcentaje_diamantes_por_partidas"),
            "advertencia_partidas": partidas.get("advertencia_partidas"),
            "diagnostico_partidas": partidas.get("diagnostico_partidas"),
        }),
    }



def _bloque_datos_obligatorios_recomendaciones(contexto: Dict[str, Any]) -> str:
    """
    Bloque compacto para OpenAI.

    Importante:
    - La tabla creadores_arquetipo es fuente de verdad para el arquetipo.
    - Este bloque ayuda a razonar, pero NO debe copiarse literal al manager.
    """
    d = _extraer_datos_personalizacion_recomendaciones(contexto)

    def _linea(etiqueta: str, valor: Any) -> str:
        if valor is None or valor == "":
            return f"- {etiqueta}: sin dato"
        if isinstance(valor, list):
            valor = ", ".join(str(v) for v in valor[:5] if v)
        return f"- {etiqueta}: {valor}"

    return "\n".join(
        [
            "DATOS DEL CREADOR PARA RAZONAMIENTO (no copies nombres técnicos en el texto final):",
            _linea("nombre", d.get("nombre_creador")),
            _linea("arquetipo", d.get("arquetipo")),
            _linea("resumen operativo del arquetipo", d.get("resumen_arquetipo")),
            _linea("intereses", d.get("intereses")),
            _linea("horario", d.get("horario")),
            _linea("categoría", d.get("categoria_nombre")),
            _linea("meta de diamantes", d.get("meta_diamantes")),
            _linea("lectura de partidas para manager", d.get("texto_partidas_manager")),
            "",
            "GUÍA INTERNA DEL ARQUETIPO DESDE BD (úsala para decidir, no la pegues completa):",
            _linea("dinámicas recomendadas", d.get("arquetipo_dinamicas")),
            _linea("contenido", d.get("arquetipo_contenido")),
            _linea("interacción", d.get("arquetipo_interaccion")),
            _linea("monetización", d.get("arquetipo_monetizacion")),
            _linea("evitar", d.get("arquetipo_evitar")),
        ]
    )


def _bloque_datos_por_categoria_recomendaciones(contexto: Dict[str, Any]) -> str:
    d = _extraer_datos_personalizacion_recomendaciones(contexto)
    intereses = d.get("intereses_lista") or []
    intereses_txt = ", ".join(str(i) for i in intereses[:5] if i) or "sin dato"

    def _v(valor: Any) -> str:
        if valor is None or valor == "":
            return "sin dato"
        return str(valor)

    return "\n".join(
        [
            "DATOS REPARTIDOS POR TARJETA (usa cada dato solo en su categoría):",
            "- monetizacion:",
            (
                f"  meta: {_v(d.get('meta_diamantes'))} | categoría: {_v(d.get('categoria_nombre'))} | "
                f"interés gancho: {intereses[0] if intereses else 'sin dato'} | "
                "tramos: apertura, mitad del LIVE, cierre"
            ),
            "- interaccion:",
            (
                f"  arquetipo: {_v(d.get('arquetipo'))} | 2 equipos, pregunta rápida, ranking simbólico, "
                f"top 3 por ronda | dinámicas: {_v((d.get('arquetipo_interaccion') or [])[:2])}"
            ),
            "- contenido:",
            f"  intereses: {intereses_txt} | mini parrilla Live 1 / Live 2 / Live 3",
            "- audiencia:",
            "  follows, comunidad, retorno al próximo LIVE, retención",
            "- horario:",
            f"  franja: {_v(d.get('horario'))} | 3 lives/semana | medir asistencia, comentarios y regalos por bloque",
            "- tecnica:",
            "  luz, audio, conexión, encuadre, portada, título",
            "- emocional:",
            (
                f"  reto semanal 3 lives, celebrar 3/3 antes de subir metas | "
                f"sin horario ni diamantes | no saturar a {_v(d.get('nombre_creador'))}"
            ),
            "- disciplina:",
            "  rutina mínima, preparación pre-LIVE, cumplimiento semanal",
        ]
    )


def _texto_contiene_alguna(texto: str, palabras: Tuple[str, ...]) -> bool:
    t = (texto or "").lower()
    return any(p in t for p in palabras)


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
        "para generar conversación",
        "para generar conversacion",
        "usar música, fitness",
        "usar musica, fitness",
        "preguntas rápidas sobre",
        "preguntas rapidas sobre",
        "mini retos de",
    ]
    if any(p in t for p in patrones_vagos):
        return True
    if any(p in t for p in _TERMINOS_TECNICOS_PROHIBIDOS_MANAGER):
        return True
    if re.search(r"\d{2,}(\.\d+)?\s*%\s*asociado a partidas", t):
        return True
    return False


def _cumple_personalizacion_minima_recomendacion(
    texto: str,
    datos: Dict[str, Any],
    categoria: Optional[str] = None,
) -> bool:
    """
    Validación relajada por categoría: acepta recomendaciones concretas sin exigir
    menciones literales de arquetipo o 2 intereses en todas las tarjetas.
    """
    t = (texto or "").strip()
    if not t:
        return False

    tl = t.lower()
    if any(p in tl for p in _TERMINOS_TECNICOS_PROHIBIDOS_MANAGER):
        return False

    cat = _normalizar_categoria_recomendacion(categoria or "")
    intereses = datos.get("intereses_lista") or []

    if cat == "contenido":
        tiene_interes = any(str(i).lower() in tl for i in intereses if i)
        tiene_formato = _texto_contiene_alguna(
            tl,
            ("live 1", "live 2", "live 3", "live a", "live b", "parrilla", "tema", "formato", "guion", "guión", "reto"),
        )
        return tiene_formato and (tiene_interes or not intereses)

    if cat == "interaccion":
        return _texto_contiene_alguna(
            tl,
            ("chat", "equipo", "ranking", "pregunta", "comentario", "reconocer", "batalla", "dinámica", "dinamica", "reto"),
        )

    if cat == "monetizacion":
        return _texto_contiene_alguna(
            tl,
            ("regalo", "meta", "diamante", "tramo", "batalla", "monetiz", "apertura", "cierre"),
        )

    if cat == "horario":
        horario = datos.get("horario")
        menciona_horario = bool(horario) and str(horario).lower() in tl
        return menciona_horario or _texto_contiene_alguna(
            tl,
            ("horario", "bloque", "franja", "semana", "días", "dias", "medir", "asistencia", "3 live", "3 lives"),
        )

    if cat == "audiencia":
        return _texto_contiene_alguna(
            tl,
            ("follow", "seguidor", "comunidad", "retorno", "retención", "retencion", "volver", "fidel"),
        )

    if cat == "tecnica":
        return _texto_contiene_alguna(
            tl,
            ("luz", "audio", "encuadre", "conexión", "conexion", "cámara", "camara", "portada", "título", "titulo"),
        )

    if cat == "emocional":
        return _texto_contiene_alguna(
            tl,
            ("energía", "energia", "confianza", "ritmo", "reto", "semanal", "saturar", "motiv", "3 live", "3 lives"),
        )

    if cat == "disciplina":
        return _texto_contiene_alguna(
            tl,
            ("rutina", "preparación", "preparacion", "constancia", "cumplimiento", "semanal", "disciplina"),
        )

    return len(tl) >= 40


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



def _limpiar_lenguaje_tecnico_ia(texto: Any) -> str:
    """Quita nombres internos y frases robóticas del texto visible al manager."""
    if texto is None:
        return ""
    resultado = str(texto).strip()
    if not resultado:
        return ""

    reemplazos = (
        (r"(?im)^\s*Estrategia del arquetipo:\s*", "Aplicar: "),
        (r"(?i)la\s+estrategia_json\s+indica", "Según la estrategia del arquetipo"),
        (r"(?i)estrategia_json", "estrategia del arquetipo"),
        (r"(?i)arquetipo_estrategia", "estrategia del arquetipo"),
        (r"(?i)perfil_estrategico", "perfil del creador"),
        (r"(?i)performance_partidas", "rendimiento en partidas"),
        (r"(?i)según el json", "según los datos del creador"),
        (r"(?i)segun el json", "según los datos del creador"),
        (r"(?i)del json", "del perfil"),
        (r"(?i)según el contexto", "según los datos del creador"),
        (r"(?i)segun el contexto", "según los datos del creador"),
        (r"(?i)del contexto", "del perfil"),
        (r"(?i)\bmetadata\b", ""),
        (r"(?i)\bcampo\s+", ""),
        (r"(?i)sin dato de\s+\[[^\]]+\]", ""),
        (r"(?i)sin dato de\s+[a-z0-9_.]+", ""),
        (r"(?i)la tabla creadores_arquetipo", "la estrategia del arquetipo"),
        (r"(?i)creadores_arquetipo", "catálogo de arquetipos"),
        (r"(?i)instrucción ia del arquetipo", "guía operativa del arquetipo"),
        (r"(?i)instruccion ia del arquetipo", "guía operativa del arquetipo"),
        (r"(?i)como\s+hilo\s+operativo\s+del\s+LIVE", "para darle ritmo al LIVE"),
        (r"(?i)hilo\s+operativo\s+del\s+LIVE", "ritmo del LIVE"),
        (r"(?i)como\s+estructura\s+práctica\s+del\s+LIVE", "como estructura práctica del LIVE"),
        (
            r"(?i)diamantes_de_partidas supera diamantes_mes; revisar si ambos campos corresponden al mismo período o a la misma base de cálculo\.?",
            "El reporte sugiere alta relevancia de partidas; úsalo como señal operativa, no como proporción exacta.",
        ),
        (
            r"(?i)el porcentaje asociado supera el 100%, por lo que debe revisarse como dato operativo antes de interpretarlo como proporción exacta\.?",
            "usa este dato como señal operativa, no como proporción exacta.",
        ),
    )
    for patron, sustituto in reemplazos:
        resultado = re.sub(patron, sustituto, resultado)

    # Elimina la muletilla que ensuciaba las tarjetas:
    # "Música: ..., aplicada antes de la primera batalla para activar comentarios."
    resultado = re.sub(
        r",\s*aplicad[ao]\s+([^\.\n]+?)\s+para\s+([^\.\n]+)\.",
        r" \1 para \2.",
        resultado,
        flags=re.IGNORECASE,
    )
    resultado = re.sub(
        r"\s+aplicad[ao]\s+([^\.\n]+?)\s+para\s+([^\.\n]+)\.",
        r" \1 para \2.",
        resultado,
        flags=re.IGNORECASE,
    )

    # Pulido de frases frecuentes generadas desde la estrategia del arquetipo.
    resultado = re.sub(r"(?i)Usar\s+dividir audiencia", "Dividir la audiencia", resultado)
    resultado = re.sub(r"(?i)Usar\s+dividir la audiencia", "Dividir la audiencia", resultado)
    resultado = re.sub(r"(?i)Usar\s+convertir intereses", "Convertir intereses", resultado)
    resultado = re.sub(
        r"(?i)debe\s+construirse\s+con\s+convertir",
        "debe convertir",
        resultado,
    )
    resultado = re.sub(
        r"(?i)la\s+parrilla\s+debe\s+construirse\s+con\s+",
        "la parrilla debe convertir ",
        resultado,
    )
    resultado = re.sub(r"(?i)\bcon\s+construir\b", "construir", resultado)
    resultado = re.sub(r"(?i)\bcon\s+convertir\b", "convertir", resultado)
    resultado = re.sub(
        r"(?i)\bconvertir\s+sus\s+intereses\s+en\s+retos\b",
        "convertir sus intereses en retos visibles",
        resultado,
    )

    resultado = resultado.replace("Aplicar: Aplicar:", "Aplicar:")
    resultado = resultado.replace(" ,", ",")
    resultado = re.sub(r"[ \t]{2,}", " ", resultado)
    resultado = re.sub(r"\.{2,}", ".", resultado)
    resultado = re.sub(r"\s+\.", ".", resultado)
    resultado = re.sub(r"\n\s+", "\n", resultado)
    return resultado.strip()



def _fragmento_estrategia_corto(texto: str, max_len: int = 100) -> str:
    limpio = (texto or "").strip().rstrip(".")
    if not limpio:
        return ""
    if len(limpio) <= max_len:
        return limpio
    corto = limpio[:max_len].rsplit(" ", 1)[0]
    return corto or limpio[:max_len]





def _unir_lista_natural(items: List[str], max_items: int = 3) -> str:
    """Une una lista corta en español: 'a, b y c'."""
    limpios: List[str] = []
    for item in items or []:
        txt = str(item or "").strip().strip(".")
        if txt and txt not in limpios:
            limpios.append(txt)
        if len(limpios) >= max_items:
            break

    if not limpios:
        return ""
    if len(limpios) == 1:
        return limpios[0]
    if len(limpios) == 2:
        return f"{limpios[0]} y {limpios[1]}"
    return ", ".join(limpios[:-1]) + f" y {limpios[-1]}"


def _minuscula_inicial(texto: str) -> str:
    texto = str(texto or "").strip()
    if not texto:
        return ""
    return texto[0].lower() + texto[1:]


def _frase_estilo_live_desde_db(estilo_live: Any) -> str:
    """Convierte estilo_live de BD en frase natural, sin pegarlo como lista suelta."""
    estilo = _fragmento_estrategia_corto(
        _valor_a_texto_resumen(estilo_live) or "",
        max_len=100,
    )
    if not estilo:
        return ""
    estilo = _minuscula_inicial(estilo.rstrip("."))
    if estilo.startswith("un estilo") or estilo.startswith("una dinámica"):
        return estilo
    return f"un estilo {estilo}"

def _resumen_arquetipo_para_recomendacion(
    arquetipo_estrategia: Optional[Dict[str, Any]] = None,
    nombre_creador: Optional[str] = None,
) -> str:
    """
    Resumen operativo corto desde creadores_arquetipo (BD).
    Usa datos de estrategia_json, pero no copia la definición completa ni listas largas.
    No contiene lógica quemada por nombre de arquetipo.
    """
    sujeto = str(nombre_creador or "el creador").strip()

    if not arquetipo_estrategia or not arquetipo_estrategia.get("nombre"):
        return (
            f"Sin arquetipo operativo en catálogo; {sujeto} debe adaptar el plan "
            "al estilo declarado y a las métricas del LIVE."
        )

    nombre_arquetipo = str(arquetipo_estrategia.get("nombre") or "").strip()
    estrategia_json = _estrategia_json_de_arquetipo(arquetipo_estrategia)

    estilo = _frase_estilo_live_desde_db(estrategia_json.get("estilo_live"))

    apoyos: List[str] = []
    for clave in (
        "dinamicas_recomendadas",
        "estrategias_interaccion",
        "estrategias_monetizacion",
        "estrategias_contenido",
    ):
        for item in _lista_desde_jsonb(estrategia_json.get(clave)):
            fragmento = _fragmento_estrategia_corto(item, max_len=75)
            if fragmento:
                fragmento = _minuscula_inicial(fragmento)
            if fragmento and fragmento not in apoyos:
                apoyos.append(fragmento)
            if len(apoyos) >= 3:
                break
        if len(apoyos) >= 3:
            break

    if estilo and apoyos:
        return (
            f"Como {nombre_arquetipo}, {sujeto} debe mantener {estilo}, "
            f"apoyado en {_unir_lista_natural(apoyos, 3)}."
        )

    if apoyos:
        return (
            f"Como {nombre_arquetipo}, {sujeto} debe apoyarse en "
            f"{_unir_lista_natural(apoyos, 3)}."
        )

    desc = _fragmento_estrategia_corto(
        str(arquetipo_estrategia.get("descripcion_operativa") or ""),
        max_len=130,
    )
    if desc:
        return f"Como {nombre_arquetipo}, {sujeto} debe orientar el LIVE a {desc.lower()}."

    return (
        f"Como {nombre_arquetipo}, {sujeto} debe adaptar contenido, interacción y monetización "
        "según la estrategia operativa del catálogo."
    )


def _resumen_arquetipo_para_categoria(
    arquetipo_estrategia: Optional[Dict[str, Any]],
    nombre_creador: Optional[str],
    categoria_norm: str,
) -> str:
    """
    Variante corta del resumen del arquetipo según la categoría de recomendación.
    La fuente sigue siendo creadores_arquetipo. No quema definiciones por nombre.
    """
    categoria_norm = _normalizar_categoria_recomendacion(categoria_norm)
    if not arquetipo_estrategia or not arquetipo_estrategia.get("nombre"):
        return _resumen_arquetipo_para_recomendacion(arquetipo_estrategia, nombre_creador)

    nombre_arquetipo = str(arquetipo_estrategia.get("nombre") or "").strip()
    sujeto = str(nombre_creador or "el creador").strip()

    items = _items_estrategia_arquetipo_por_categoria(
        arquetipo_estrategia,
        categoria_norm,
        limit=2,
    )
    items_txt = _unir_lista_natural(
        [_minuscula_inicial(_fragmento_estrategia_corto(i, 72)) for i in items],
        max_items=2,
    )

    estrategia_json = _estrategia_json_de_arquetipo(arquetipo_estrategia)
    estilo = _frase_estilo_live_desde_db(estrategia_json.get("estilo_live"))

    if categoria_norm == "monetizacion":
        if items_txt:
            return f"Como {nombre_arquetipo}, {sujeto} debe monetizar con {items_txt}."
        if estilo:
            return f"Como {nombre_arquetipo}, {sujeto} debe monetizar manteniendo {estilo}."
    if categoria_norm == "interaccion":
        if items_txt:
            items_l = items_txt.lower()
            if "dividir la audiencia" in items_l or "dividir audiencia" in items_l:
                return (
                    f"Como {nombre_arquetipo}, la interacción debe sentirse como reto, "
                    "competencia y reconocimiento público."
                )
            return (
                f"Como {nombre_arquetipo}, la interacción debe activar participación, "
                f"competencia y reconocimiento desde {items_txt}."
            )
        if estilo:
            return f"Como {nombre_arquetipo}, la interacción debe mantener {estilo}."
    if categoria_norm == "contenido":
        if items_txt:
            return (
                f"Como {nombre_arquetipo}, la parrilla debe convertir sus intereses en retos visibles "
                "desde el inicio del LIVE."
            )
        if estilo:
            return f"Como {nombre_arquetipo}, la parrilla debe reflejar {estilo}."
    if categoria_norm == "horario":
        if items_txt:
            return f"Como {nombre_arquetipo}, cada bloque horario debe ordenar {items_txt}."
        if estilo:
            return f"Como {nombre_arquetipo}, el horario debe sostener {estilo}."
    if categoria_norm == "tecnica":
        if estilo:
            return f"Como {nombre_arquetipo}, la calidad técnica debe sostener {estilo}."
        if items_txt:
            return f"Como {nombre_arquetipo}, la calidad técnica debe facilitar {items_txt}."
    if categoria_norm == "audiencia":
        if items_txt:
            return f"Como {nombre_arquetipo}, la audiencia debe participar mediante {items_txt}."
        if estilo:
            return f"Como {nombre_arquetipo}, la audiencia debe reconocer {estilo}."

    return _resumen_arquetipo_para_recomendacion(arquetipo_estrategia, nombre_creador)


def _categoria_meta_para_manager(categoria_nombre: Any, meta_diamantes: Any) -> str:
    """
    Evita frases pobres como "Categoría Sin categoría, meta su meta de diamantes".
    """
    cat = str(categoria_nombre or "").strip()
    meta = None
    if meta_diamantes not in (None, ""):
        try:
            meta = int(float(meta_diamantes))
        except Exception:
            meta = str(meta_diamantes).strip() or None

    if cat and meta is not None:
        return f"Categoría {cat}, meta {meta} diamantes."
    if cat and meta is None:
        return f"Categoría {cat}; pendiente asignar meta de diamantes."
    if not cat and meta is not None:
        return f"Pendiente asignar categoría; meta {meta} diamantes."
    return "Pendiente asignar categoría y meta de diamantes para medir el avance."


def _frase_interaccion_arquetipo_sin_repetir(
    estrategias_arq_int: str,
    texto_partidas_interaccion: str,
) -> str:
    """
    Construye el cierre de interacción sin repetir "dividir la audiencia" si ya vino
    desde la estrategia del arquetipo en BD.
    """
    estrategia = (estrategias_arq_int or "").strip()
    partidas = (texto_partidas_interaccion or "").strip()

    if estrategia:
        estrategia_l = estrategia.lower()
        if "dividir la audiencia" in estrategia_l or "dividir audiencia" in estrategia_l:
            cierre = (
                "Reconocer públicamente a quienes apoyan, comentan o participan "
                "para reforzar competencia y pertenencia."
            )
        else:
            cierre = (
                "Reforzar la dinámica con reconocimiento público a quienes comentan, "
                "votan o apoyan durante el LIVE."
            )
        return " ".join(p for p in (estrategia, cierre, partidas) if p).strip()

    cierre = (
        "Reconocer públicamente a quienes comentan, votan o apoyan durante las dinámicas."
    )
    return " ".join(p for p in (cierre, partidas) if p).strip()


def _bloque_estrategias_arquetipo_categoria(
    arquetipo_estrategia: Optional[Dict[str, Any]],
    categoria_norm: str,
    *,
    minimo: int = 2,
) -> str:
    """
    Línea natural de apoyo desde estrategia_json.
    Usa la tabla creadores_arquetipo como guía, sin exponer lenguaje interno
    ni usar la frase "hilo operativo del LIVE".
    """
    items = _items_estrategia_arquetipo_por_categoria(
        arquetipo_estrategia,
        categoria_norm,
        limit=max(minimo, 3),
    )
    if not items:
        return ""

    items_limpios: List[str] = []
    for item in items:
        accion = _minuscula_inicial(_fragmento_estrategia_corto(item, 86))
        accion = re.sub(r"^dividir audiencia", "dividir la audiencia", accion, flags=re.IGNORECASE)
        accion = re.sub(r"^usar\s+", "", accion, flags=re.IGNORECASE)
        if accion and accion not in items_limpios:
            items_limpios.append(accion)
        if len(items_limpios) >= max(1, min(minimo, 2)):
            break

    if not items_limpios:
        return ""

    frase_items = _unir_lista_natural(items_limpios, 2)
    categoria_norm = _normalizar_categoria_recomendacion(categoria_norm)

    if categoria_norm == "monetizacion":
        return f"Usar {frase_items} para darle ritmo al LIVE y sostener la narrativa de regalos."
    if categoria_norm == "interaccion":
        return f"Usar {frase_items} para ordenar el chat y aumentar respuestas antes de cada batalla."
    if categoria_norm == "contenido":
        return f"Usar {frase_items} como estructura principal de la mini parrilla."
    if categoria_norm == "horario":
        return f"Usar {frase_items} para ordenar apertura, mitad y cierre del LIVE."
    if categoria_norm == "audiencia":
        return f"Usar {frase_items} para convertir participación en seguidores."
    return f"Usar {frase_items} como estructura práctica del LIVE."


def _texto_evitar_arquetipo(arquetipo_estrategia: Optional[Dict[str, Any]]) -> str:
    evitar = _lista_desde_jsonb(
        _estrategia_json_de_arquetipo(arquetipo_estrategia).get("evitar")
    )[:2]
    if not evitar:
        return ""
    if len(evitar) == 1:
        return f" Cuidar que el LIVE no caiga en {evitar[0]}."
    return f" Cuidar que el LIVE no caiga en {evitar[0]} ni en {evitar[1]}."



def _texto_partidas_para_manager(datos: Dict[str, Any], categoria: Optional[str] = None) -> str:
    """
    Texto legible de partidas para manager.
    Varía por categoría para evitar repetir la misma frase en todas las tarjetas.
    Evita exponer advertencias técnicas o porcentajes mayores al 100% como proporción exacta.
    """
    partidas = safe_float(datos.get("partidas"))
    diamantes_por_partida = datos.get("diamantes_por_partida")
    pct = safe_float(datos.get("pct_diamantes_partidas"))
    diagnostico = datos.get("diagnostico_partidas")
    categoria_norm = _normalizar_categoria_recomendacion(categoria or "otro")

    if partidas <= 0:
        if categoria_norm in {"monetizacion", "interaccion", "contenido"}:
            return (
                "No registra partidas suficientes; conviene probar batallas o dinámicas "
                "competitivas si encajan con el arquetipo."
            )
        return "No registra partidas suficientes en el período."

    partidas_txt = int(partidas) if partidas == int(partidas) else partidas
    base = f"Registra {partidas_txt} partidas"
    if diamantes_por_partida not in (None, ""):
        base += f" y {diamantes_por_partida} diamantes por partida"

    if pct > 100:
        if categoria_norm == "monetizacion":
            return f"{base}; las partidas deben seguir siendo una palanca central de monetización."
        if categoria_norm == "interaccion":
            return f"Con {partidas_txt} partidas registradas, cada batalla debe activar chat, equipos y reconocimiento."
        if categoria_norm == "contenido":
            return f"Con {partidas_txt} partidas registradas, cada live debe preparar contenido antes, durante y después de la batalla."
        if categoria_norm == "horario":
            return f"Con {partidas_txt} partidas registradas, conviene medir qué bloque horario convierte mejor durante batallas."
        if categoria_norm == "tecnica":
            return "Como trabaja con muchas partidas, la estabilidad de audio, luz y conexión debe revisarse antes de cada batalla."
        return f"{base}; úsalo como señal operativa para orientar batallas, no como proporción exacta."

    pct_redondeado = int(round(pct)) if pct == round(pct, 1) else round(pct, 1)

    if pct >= 60:
        if categoria_norm == "monetizacion":
            return (
                f"{base}. Las partidas aportan cerca del {pct_redondeado}% de los diamantes, "
                "por lo que deben ser eje de monetización."
            )
        return f"{base}. Las partidas son un eje fuerte del LIVE y deben ordenarse por momentos."
    if pct >= 30:
        return f"{base}. Las partidas aportan una parte importante de la monetización y pueden optimizarse."
    if diagnostico and categoria_norm in {"monetizacion", "contenido", "interaccion"}:
        return f"{base}. {diagnostico}"
    return f"{base}. Las partidas pueden usarse como palanca adicional sin depender solo de ellas."

def _deduplicar_oraciones_manager(texto: Any) -> str:
    """
    Quita repeticiones obvias dentro de una misma recomendación sin cambiar el sentido.
    Especialmente evita repetir mecánicas como "dividir la audiencia en equipos".
    """
    if texto is None:
        return ""

    original = str(texto).strip()
    if not original:
        return ""

    parrafos = re.split(r"\n{2,}", original)
    parrafos_limpios: List[str] = []
    firmas_globales: set = set()
    mecanicas_globales: set = set()

    for parrafo in parrafos:
        lineas = [ln.strip() for ln in parrafo.split("\n") if ln.strip()]
        nuevas_lineas: List[str] = []

        for linea in lineas:
            partes = re.split(r"(?<=[.!?])\s+", linea)
            nuevas_partes: List[str] = []

            for parte in partes:
                frase = parte.strip()
                if not frase:
                    continue

                firma = re.sub(r"\W+", "", frase.lower())
                if firma and firma in firmas_globales:
                    continue

                frase_l = frase.lower()
                mecanicas = []
                if "dividir la audiencia en equipos" in frase_l or "dividir audiencia en equipos" in frase_l:
                    mecanicas.append("dividir_audiencia")
                if "ranking simbólico" in frase_l or "ranking simbolico" in frase_l:
                    mecanicas.append("ranking_simbolico")
                if "reconocer públicamente" in frase_l or "reconocer publicamente" in frase_l:
                    mecanicas.append("reconocimiento")

                if mecanicas and all(m in mecanicas_globales for m in mecanicas):
                    continue

                firmas_globales.add(firma)
                for m in mecanicas:
                    mecanicas_globales.add(m)
                nuevas_partes.append(frase)

            if nuevas_partes:
                nuevas_lineas.append(" ".join(nuevas_partes))

        if nuevas_lineas:
            parrafos_limpios.append("\n".join(nuevas_lineas))

    return "\n\n".join(parrafos_limpios).strip()


def _pulir_frases_roboticas_manager(texto: Any) -> str:
    """Corrige duplicados y frases mecánicas en texto visible al manager."""
    if texto is None:
        return ""
    resultado = str(texto).strip()
    if not resultado:
        return ""

    while True:
        anterior = resultado
        resultado = re.sub(r"(?i)\b(convertir|construir)\s+\1\b", r"\1", resultado)
        if resultado == anterior:
            break

    reemplazos = (
        (r"(?i)\bcon\s+convertir\s+intereses\b", "convirtiendo intereses"),
        (r"(?i)\bdebe\s+convertir\s+intereses\b", "debe convertir sus intereses"),
        (
            r"(?i)\bdebe\s+convertir\s+intereses\s+en\s+retos\s+y\s+abrir\b",
            "debe convertir sus intereses en retos visibles y abrir",
        ),
        (
            r"(?i)\bla\s+parrilla\s+debe\s+construirse\s+con\s+convertir\b",
            "la parrilla debe convertir",
        ),
        (
            r"(?i)\bla\s+parrilla\s+debe\s+convertir\s+convertir\b",
            "la parrilla debe convertir sus",
        ),
        (r"(?i)\ben\s+retos\s+visibles\s+por\s+live\b", "desde el inicio del LIVE"),
        (r"(?i)\ben\s+retos\s+visibles\s+por\s+LIVE\b", "desde el inicio del LIVE"),
        (r"(?i)\bpor\s+live\b", "por LIVE"),
        (r"(?i)\bpr[oó]ximo\s+live\b", "próximo LIVE"),
    )
    for patron, sustituto in reemplazos:
        resultado = re.sub(patron, sustituto, resultado)

    resultado = re.sub(r"[ \t]{2,}", " ", resultado)
    resultado = re.sub(r"\.{2,}", ".", resultado)
    resultado = re.sub(r"\s+\.", ".", resultado)
    return resultado.strip()


def _quitar_oraciones_interaccion_redundantes(texto: str) -> str:
    """Evita repetir equipos / dividir audiencia en la misma recomendación."""
    original = (texto or "").strip()
    if not original:
        return ""

    texto_l = original.lower()
    tiene_equipos = "equipo" in texto_l
    tiene_ranking = "ranking" in texto_l
    if not tiene_equipos and not tiene_ranking:
        return original

    partes = re.split(r"(?<=[.!?])\s+", original)
    filtradas: List[str] = []
    for parte in partes:
        pl = parte.lower().strip()
        if not pl:
            continue
        if tiene_equipos and (
            "dividir la audiencia" in pl
            or "dividir audiencia" in pl
            or (pl.startswith("usar ") and "chat" in pl)
        ):
            continue
        filtradas.append(parte.strip())

    return " ".join(filtradas).strip() if filtradas else original


def _justificacion_contenido_natural(justificacion: str) -> str:
    match = re.search(r"(?i)como\s+([^,]+),", justificacion or "")
    if not match:
        return justificacion
    arquetipo = match.group(1).strip()
    return (
        f"Como {arquetipo}, la parrilla debe convertir sus intereses en retos visibles "
        "desde el inicio del LIVE."
    )


def _texto_tiene_tramos_monetizacion(texto: str) -> bool:
    tl = (texto or "").lower()
    return (
        "apertura" in tl
        and ("mitad" in tl or "entre batalla" in tl)
        and "cierre" in tl
    )


def _texto_tiene_ranking_y_top(texto: str) -> bool:
    tl = (texto or "").lower()
    tiene_ranking = _texto_contiene_alguna(
        tl,
        ("ranking", "puntuación", "puntuacion", "tabla de puntos", "marcador"),
    )
    tiene_top = _texto_contiene_alguna(
        tl,
        (
            "top 3",
            "top tres",
            "3 mejores",
            "tres mejores",
            "mejores que comenta",
            "mejores que apoya",
            "top coment",
            "reconocer en vivo",
        ),
    )
    return tiene_ranking and tiene_top


def _recomendacion_monetizacion_estructurada(interes: str = "") -> str:
    tramos = (
        "apertura para activar el primer mini reto, mitad del LIVE para desbloquear "
        "30 segundos de energía y cierre para elegir el reto del próximo LIVE."
    )
    if interes:
        return (
            f"Implementar metas pequeñas de regalos por tramo usando {interes} como gancho: "
            f"{tramos}"
        )
    return f"Implementar metas pequeñas de regalos por tramo: {tramos}"


def _justificacion_monetizacion_desde_datos(datos: Optional[Dict[str, Any]] = None) -> str:
    datos = datos or {}

    meta_mensual = (
        datos.get("meta_mensual_diamantes")
        or datos.get("meta_diamantes")
        or (datos.get("metas") or {}).get("meta_diamantes")
    )

    diamantes_mes = datos.get("diamantes_mes")
    partidas = datos.get("partidas")
    diamantes_partidas = (
        datos.get("diamantes_de_partidas")
        or datos.get("diamantes_partidas")
    )

    partes: List[str] = []

    def _entero(valor: Any) -> Optional[int]:
        if valor is None or valor == "":
            return None
        try:
            return int(float(valor))
        except Exception:
            return None

    meta_n = _entero(meta_mensual)
    diamantes_n = _entero(diamantes_mes)
    partidas_n = _entero(partidas)
    diamantes_partidas_n = _entero(diamantes_partidas)

    if diamantes_n is not None:
        partes.append(f"el creador acumuló {diamantes_n} diamantes en el periodo")

    if meta_n is not None:
        partes.append(f"frente a una meta mensual de {meta_n}")

    if partidas_n is not None and diamantes_partidas_n is not None:
        partes.append(
            f"y registra {partidas_n} partidas con {diamantes_partidas_n} diamantes asociados a partidas"
        )

    if partes:
        return (
            "El reporte muestra que "
            + ", ".join(partes)
            + "; por eso conviene ordenar la monetización por tramos claros."
        )

    return (
        "Ordenar la monetización por tramos ayuda a que la audiencia entienda qué apoyar "
        "en cada momento del LIVE."
    )


def _justificacion_monetizacion_natural(
    justificacion: str,
    datos: Optional[Dict[str, Any]] = None,
) -> str:
    texto = (justificacion or "").strip()
    jl = texto.lower()

    if texto and (
        "esto convierte la meta" in jl
        or ("bronce" in jl and "diamantes" in jl)
        or (datos and str(datos.get("meta_categoria_diamantes") or "") in jl.replace(",", ""))
    ):
        return _justificacion_monetizacion_desde_datos(datos)

    if not texto or "necesita tramos" in jl or "priorizar conversión" in jl:
        return _justificacion_monetizacion_desde_datos(datos)

    if texto and len(texto) >= 40:
        return texto

    return _justificacion_monetizacion_desde_datos(datos)


_ARQUETIPOS_INVALIDOS_FRASE = frozenset({
    "juego",
    "metadata",
    "estrategia",
    "json",
    "contexto",
    "schema",
    "tabla",
    "base de datos",
})


def _frase_estilo_arquetipo_natural(nombre: Optional[str]) -> str:
    nombre_limpio = str(nombre or "").strip()
    if not nombre_limpio or nombre_limpio.lower() in _ARQUETIPOS_INVALIDOS_FRASE:
        return "Por su dinámica competitiva"
    return f"Por su estilo {nombre_limpio}"


_ARQUETIPOS_VALIDOS_INTERACCION = frozenset({
    "pretty girl",
    "pretty boy",
    "humor",
    "cantante",
    "lifestyle",
    "batallista",
    "tarotista",
    "profesiones",
    "gamer",
    "discapacidad",
    "religión",
    "religion",
})


def _obtener_arquetipo_nombre_seguro_desde_contexto(
    contexto: Optional[Dict[str, Any]],
) -> Optional[str]:
    if not contexto:
        return None

    arquetipo = contexto.get("arquetipo") or contexto.get("arquetipo_creador") or {}
    perfil = contexto.get("perfil") or {}

    nombre = None
    if isinstance(arquetipo, dict):
        nombre = arquetipo.get("nombre") or arquetipo.get("codigo")

    if not nombre and isinstance(perfil, dict):
        nombre = perfil.get("arquetipo_valor")

    if not nombre:
        return None

    nombre = str(nombre).strip()

    if nombre.lower() not in _ARQUETIPOS_VALIDOS_INTERACCION:
        return None

    return nombre.title()


def _justificacion_interaccion_natural(
    justificacion: str,
    recomendacion: str,
    contexto: Optional[Dict[str, Any]] = None,
) -> str:
    texto = (justificacion or "").strip()
    texto_l = texto.lower()

    frases_rotas = (
        "por su estilo participación activa",
        "por su estilo participacion activa",
        "la interacción debe sentirse por su estilo",
        "la interaccion debe sentirse por su estilo",
    )

    if any(f in texto_l for f in frases_rotas):
        return (
            "Tiene buena fluidez hablando, pero se distrae al leer el chat; "
            "por eso la interacción debe mantenerse simple, competitiva y con reconocimiento público."
        )

    if texto and "reto, competencia y reconocimiento" in texto_l:
        if not re.search(r"(?i)como\s+(juego|metadata|estrategia|json)\b", texto):
            return texto

    arquetipo = _obtener_arquetipo_nombre_seguro_desde_contexto(contexto)
    if arquetipo:
        return (
            f"Como {arquetipo}, la interacción debe sentirse como reto, "
            "competencia y reconocimiento público."
        )

    return (
        "Tiene buena fluidez hablando, pero se distrae al leer el chat; "
        "por eso la interacción debe mantenerse simple, competitiva y con reconocimiento público."
    )


def _recomendacion_interaccion_estructurada() -> str:
    return (
        "Dividir la audiencia en 2 equipos antes de cada batalla, lanzar una pregunta rápida "
        "y mostrar un ranking simbólico. Reconocer en vivo al top 3 que comenta o apoya en cada ronda."
    )


def _enriquecer_recomendacion_interaccion_si_falta(recomendacion: str) -> str:
    """Añade solo lo que falta; no reemplaza texto ya bueno con sinónimos distintos."""
    base = (recomendacion or "").strip()
    if not base:
        return _recomendacion_interaccion_estructurada()

    tl = base.lower()
    if _texto_tiene_ranking_y_top(base) and _texto_contiene_alguna(
        tl, ("equipo", "pregunta", "batalla", "ronda"),
    ):
        return _quitar_oraciones_interaccion_redundantes(base)

    if len(base) < 55:
        return _recomendacion_interaccion_estructurada()

    extras: List[str] = []
    if not _texto_contiene_alguna(tl, ("pregunta", "preguntar")):
        extras.append("lanzar una pregunta rápida antes de cada batalla")
    if not _texto_contiene_alguna(tl, ("ranking", "puntuación", "puntuacion", "marcador")):
        extras.append("mostrar un ranking simbólico en pantalla")
    if not _texto_contiene_alguna(
        tl,
        (
            "top 3",
            "top tres",
            "3 mejores",
            "tres mejores",
            "mejores que comenta",
            "mejores que apoya",
            "reconocer en vivo",
        ),
    ):
        extras.append("reconocer en vivo al top 3 que comenta o apoya en cada ronda")

    if not extras:
        return _quitar_oraciones_interaccion_redundantes(base)

    return f"{base.rstrip('.')}. {' '.join(extras)}."


def _texto_tiene_cumplimiento_3_3(texto: str) -> bool:
    tl = (texto or "").lower()
    return _texto_contiene_alguna(
        tl,
        ("3/3", "3 de 3", "tres de tres", "tres en tres", "cumplimiento 3"),
    )


def _recomendacion_emocional_estructurada() -> str:
    return (
        "Establecer un reto semanal de 3 lives y celebrar el cumplimiento 3/3 "
        "antes de subir exigencia de metas."
    )


def _limpiar_emocional_de_horario_y_metricas(
    texto: str,
    horario: str = "",
) -> str:
    limpio = _limpiar_horario_de_texto_emocional_disciplina(texto, horario)
    limpio = re.sub(
        r"(?i)\b(?:tarde|mañana|noche)\s*\([^)]+\)",
        "",
        limpio,
    )
    limpio = re.sub(r"(?i)\b\d+\s*lives?\s+semanal(?:es)?\b", "3 lives", limpio)
    limpio = re.sub(r"(?i)\bdiamantes?\b", "", limpio)
    limpio = re.sub(r"\s{2,}", " ", limpio).strip()
    return limpio


def _recomendacion_es_concreta_util(texto: str, categoria: Optional[str] = None) -> bool:
    """True si el texto de IA ya es accionable; evita sobrescribir con builders rígidos."""
    t = (texto or "").strip()
    if not t or _es_texto_recomendacion_generico(t):
        return False
    if len(t) < 32:
        return False
    tl = t.lower()
    if any(p in tl for p in _TERMINOS_TECNICOS_PROHIBIDOS_MANAGER):
        return False
    return True


def _debe_usar_fallback_recomendacion(
    texto_rec: str,
    texto_just: str,
    categoria: str,
    datos: Dict[str, Any],
    contexto: Optional[Dict[str, Any]] = None,
) -> bool:
    texto_union = f"{texto_rec} {texto_just}".strip()
    rec_probe = {
        "recomendacion": texto_rec,
        "justificacion": texto_just,
        "categoria": categoria,
    }
    if contexto:
        if _recomendacion_es_buena_ia(rec_probe, contexto):
            return False
        if (
            _texto_menciona_meta_categoria_como_objetivo(texto_union, contexto)
            or _recomendacion_usa_meta_categoria_prohibida(
                {"recomendacion": texto_rec, "justificacion": texto_just},
                contexto,
            )
        ):
            return True
        if _es_contexto_compacto_ia(contexto) and _recomendacion_es_concreta_util(
            texto_rec, categoria
        ):
            if _recomendacion_usa_metricas_reporte(
                rec_probe, contexto
            ) or _recomendacion_usa_senal_perfil(rec_probe, contexto):
                return False

    if not texto_rec.strip():
        return True
    if _es_texto_recomendacion_generico(texto_rec) or _es_texto_recomendacion_generico(texto_just):
        return True
    if any(p in texto_union.lower() for p in _TERMINOS_TECNICOS_PROHIBIDOS_MANAGER):
        return True
    if len(texto_rec) > 480 or len(texto_just) > 280:
        return True
    if _recomendacion_es_concreta_util(texto_rec, categoria):
        return False
    if (
        categoria in _CATEGORIAS_RECOMENDACION_CON_DINAMICAS
        and not _cumple_dinamicas_intereses_minimas(texto_union, datos, categoria)
        and len(texto_rec) < 70
    ):
        return True
    if not _cumple_personalizacion_minima_recomendacion(texto_union, datos, categoria):
        return True
    return False


_SUAVIZAR_ABSOLUTOS_RECOMENDACIONES = (
    (r"\bprincipal palanca operativa\b", "palanca fuerte de monetización"),
    (r"\bprioridad absoluta\b", "prioridad importante"),
    (r"\bdefinitiva\b", "relevante"),
    (r"\bdefinitivo\b", "relevante"),
    (r"\bgarantiza\b", "puede ayudar a"),
    (r"\búnica palanca\b", "palanca importante"),
    (r"\bunica palanca\b", "palanca importante"),
)


def _corregir_frase_como_arquetipo_invalido(texto: str) -> str:
    if not texto:
        return texto

    reemplazos_fijos = (
        (
            "Por su estilo participación activa y reconocimiento público, la interacción debe sentirse Por su estilo reto, competencia y reconocimiento público.",
            "Tiene buena fluidez hablando, pero se distrae al leer el chat; por eso la interacción debe mantenerse simple, competitiva y con reconocimiento público.",
        ),
        (
            "Por su estilo participación activa y reconocimiento público, la interacción debe sentirse como reto, competencia y reconocimiento público.",
            "Tiene buena fluidez hablando, pero se distrae al leer el chat; por eso la interacción debe mantenerse simple, competitiva y con reconocimiento público.",
        ),
    )
    for malo, bueno in reemplazos_fijos:
        if malo.lower() in texto.lower():
            return bueno

    texto = re.sub(
        r"(?i)\bcomo\s+(juego|metadata|estrategia|json|contexto|schema)\b",
        "Por su dinámica en LIVE",
        texto,
    )
    return texto


def _pulir_recomendacion_final_suave(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Limpieza ligera sin cambiar el sentido ni reemplazar por plantillas."""
    if not isinstance(rec, dict):
        return rec
    salida = dict(rec)
    for campo in ("recomendacion", "justificacion"):
        texto = _limpiar_lenguaje_tecnico_ia(rec.get(campo))
        texto = _pulir_frases_roboticas_manager(texto)
        texto = _corregir_frase_como_arquetipo_invalido(texto)
        for patron, reemplazo in _SUAVIZAR_ABSOLUTOS_RECOMENDACIONES:
            texto = re.sub(patron, reemplazo, texto, flags=re.IGNORECASE)
        texto = re.sub(r"\.\.+", ".", texto)
        texto = re.sub(r"\s{2,}", " ", texto).strip()
        texto = _limpiar_texto_generado(texto)
        salida[campo] = texto
    return salida


def _pulir_recomendacion_por_categoria(
    rec: Dict[str, Any],
    contexto: Optional[Dict[str, Any]] = None,
    *,
    hay_tarjeta_horario: bool = False,
    modo_suave: bool = True,
) -> Dict[str, Any]:
    if not isinstance(rec, dict):
        return rec

    cat = _normalizar_categoria_recomendacion(rec.get("categoria") or "otro")
    recomendacion = str(rec.get("recomendacion") or "").strip()
    justificacion = str(rec.get("justificacion") or recomendacion).strip()
    datos = (
        _extraer_datos_personalizacion_recomendaciones(contexto)
        if contexto
        else {}
    )
    horario_ctx = str(datos.get("horario") or "")

    concreta = _recomendacion_es_concreta_util(recomendacion, cat)

    if cat == "monetizacion":
        tl = recomendacion.lower()
        just_l = justificacion.lower()
        if (
            "esto convierte la meta" in just_l
            or ("bronce" in just_l and "diamantes" in just_l)
        ):
            justificacion = _justificacion_monetizacion_desde_datos(datos)
        elif not modo_suave or not concreta:
            if (
                _texto_contiene_alguna(
                    tl,
                    ("metas pequeñas", "por tramo", "regalos por tramo", "mini reto"),
                )
                and not _texto_tiene_tramos_monetizacion(recomendacion)
            ) or _es_texto_recomendacion_generico(recomendacion):
                interes = (datos.get("intereses_lista") or [""])[0] if datos.get("intereses_lista") else ""
                recomendacion = _recomendacion_monetizacion_estructurada(str(interes or ""))
            justificacion = _justificacion_monetizacion_natural(justificacion, datos)
        elif len(justificacion) < 40:
            justificacion = _justificacion_monetizacion_natural(justificacion, datos)

    elif cat == "interaccion":
        if not modo_suave or not _texto_tiene_ranking_y_top(recomendacion):
            recomendacion = _enriquecer_recomendacion_interaccion_si_falta(recomendacion)
        if not modo_suave or "reto, competencia" not in justificacion.lower():
            justificacion = _justificacion_interaccion_natural(
                justificacion, recomendacion, contexto
            )

    elif cat == "contenido":
        recomendacion = _pulir_frases_roboticas_manager(recomendacion)
        justificacion = _pulir_frases_roboticas_manager(justificacion)
        just_l = justificacion.lower()
        justificacion_robotica = (
            "convertir convertir" in just_l
            or "con convertir" in just_l
            or "por live" in just_l
            or "debe construirse" in just_l
            or (
                "como batallista" in just_l
                and "ayuda a atraer" not in just_l
            )
        )
        if justificacion_robotica:
            justificacion = (
                "Convertir intereses en retos visibles desde el inicio del LIVE ayuda a atraer "
                "y mantener la atención de la audiencia."
            )

    elif cat == "emocional":
        recomendacion = _limpiar_emocional_de_horario_y_metricas(recomendacion, horario_ctx)
        if not modo_suave or not concreta:
            if (
                not _texto_tiene_cumplimiento_3_3(recomendacion)
                or "reto semanal" not in recomendacion.lower()
            ) or _es_texto_recomendacion_generico(recomendacion):
                recomendacion = _recomendacion_emocional_estructurada()
        if (not modo_suave or not concreta) and "sostener energía" not in justificacion.lower():
            justificacion = "Prioridad: sostener energía y ritmo sin saturar al creador."

    elif cat == "horario":
        if "consistencia horaria" not in justificacion.lower():
            justificacion = (
                "La consistencia horaria ayuda a crear expectativa y retorno de audiencia."
            )

    salida = dict(rec)
    salida["recomendacion"] = recomendacion
    salida["justificacion"] = justificacion
    return salida


def _pulir_texto_recomendacion_final(texto: Any) -> str:
    limpio = _limpiar_lenguaje_tecnico_ia(texto)
    limpio = _pulir_frases_roboticas_manager(limpio)
    limpio = _limpiar_texto_generado(limpio)
    limpio = _deduplicar_oraciones_manager(limpio)
    return normalizar_texto_parrafos(limpio)


def _pulir_recomendacion_item(rec: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(rec, dict):
        return rec
    salida = dict(rec)
    salida["recomendacion"] = _pulir_texto_recomendacion_final(rec.get("recomendacion"))
    salida["justificacion"] = _pulir_texto_recomendacion_final(
        rec.get("justificacion") or rec.get("recomendacion")
    )
    return salida


def _aplicar_pulido_final_recomendaciones(
    resultado: Any,
    contexto: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    salida: Dict[str, Any] = resultado if isinstance(resultado, dict) else {}
    recs = salida.get("recomendaciones")
    if isinstance(recs, list):
        hay_tarjeta_horario = any(
            _normalizar_categoria_recomendacion(r.get("categoria") or "") == "horario"
            for r in recs
            if isinstance(r, dict)
        )
        pulidas: List[Dict[str, Any]] = []
        for r in recs:
            if not isinstance(r, dict):
                continue
            item = _pulir_recomendacion_item(r)
            item = _pulir_recomendacion_por_categoria(
                item,
                contexto,
                hay_tarjeta_horario=hay_tarjeta_horario,
                modo_suave=True,
            )
            pulidas.append(item)
        salida["recomendaciones"] = pulidas
    return salida


_CATEGORIAS_RECOMENDACION_CON_DINAMICAS = frozenset({
    "contenido",
    "interaccion",
    "monetizacion",
})

_CATEGORIAS_CON_FRANJA_HORARIO = frozenset({"horario", "disciplina", "emocional"})

_MOMENTOS_LIVE_VALIDOS = (
    "apertura",
    "antes de",
    "batalla",
    "partida",
    "mitad",
    "cierre",
    "inicio del live",
    "durante el live",
    "post-batalla",
    "entre batallas",
    "min 0",
    "minuto",
)

_OBJETIVOS_LIVE_VALIDOS = (
    "comentarios",
    "retención",
    "retencion",
    "seguidores",
    "regalos",
    "objetivo:",
)


def _cumple_dinamicas_intereses_minimas(
    texto: str,
    datos: Dict[str, Any],
    categoria: Optional[str] = None,
) -> bool:
    """
    Reglas por categoría (tarjetas cortas).
    - monetización / contenido: mencionar intereses con foco propio de la categoría.
    - interacción: mecánicas de chat/equipos (sin exigir los 3 intereses).
    - resto: no aplica.
    """
    cat = _normalizar_categoria_recomendacion(categoria or "")
    if cat not in _CATEGORIAS_RECOMENDACION_CON_DINAMICAS:
        return True

    t = (texto or "").lower()
    intereses = datos.get("intereses_lista") or []

    if cat == "interaccion":
        return any(
            k in t
            for k in (
                "comentario",
                "chat",
                "equipo",
                "batalla",
                "ranking",
                "pregunta",
                "reconoc",
            )
        )

    if not intereses:
        return True

    if cat == "contenido":
        minimo = min(2, len(intereses)) if len(intereses) >= 2 else 1
        mencionados = sum(1 for interes in intereses if interes.lower() in t)
        if mencionados < minimo:
            return False
        return any(k in t for k in ("live 1", "live 2", "live 3", "parrilla", "tema", "formato"))

    if cat == "monetizacion":
        mencionados = sum(1 for interes in intereses if interes.lower() in t)
        if mencionados < 1:
            return False
        return any(
            k in t
            for k in ("regalo", "meta", "tramo", "batalla", "monetiz", "diamante")
        )

    return True


def _estrategias_por_interes(interes: str) -> List[str]:
    interes_norm = str(interes or "").lower()

    if "música" in interes_norm or "musica" in interes_norm:
        return [
            "hacer “adivina la canción” antes de la primera batalla",
            "dejar que la audiencia vote la canción de la siguiente partida",
            "crear duelo de playlists entre equipos de seguidores",
        ]

    if "fitness" in interes_norm:
        return [
            "lanzar un mini reto de energía de 30 segundos antes de cada batalla",
            "lanzar un mini reto de energía de 30 segundos entre partidas",
            "desbloquear el siguiente mini reto con una meta pequeña de regalos",
        ]

    if "maquillaje" in interes_norm:
        return [
            "hacer votación para elegir color o estilo del look",
            "hacer transformación antes/después durante el LIVE",
            "desbloquear el siguiente paso del maquillaje con regalos pequeños",
        ]

    return [
        f"hacer pregunta rápida sobre {interes}",
        f"hacer votación de audiencia sobre {interes}",
        f"convertir {interes} en reto corto durante el LIVE",
    ]


def _resumenes_cortos_por_interes(interes: str) -> List[str]:
    return _estrategias_por_interes(interes)


def _interes_por_indice(intereses_lista: List[str], indice: int, default: str) -> str:
    fuente = [i for i in (intereses_lista or []) if i]
    if not fuente:
        return default
    while len(fuente) <= indice:
        fuente.append(fuente[-1])
    return fuente[indice]


def _linea_dinamica_interes(
    interes: str,
    indice_estrategia: int = 0,
    *,
    momento: Optional[str] = None,
    objetivo: Optional[str] = None,
) -> str:
    """
    Construye una línea natural de dinámica por interés.
    Evita la muletilla "aplicada..." y evita duplicar momentos.
    """
    estrategias = _estrategias_por_interes(interes)
    accion = estrategias[indice_estrategia % len(estrategias)].strip().rstrip(".")
    etiqueta = (interes or "Interés").strip()

    objetivo_limpio = str(objetivo or "").strip().rstrip(".")
    momento_limpio = str(momento or "").strip().rstrip(".")

    if objetivo_limpio:
        accion = re.sub(
            r"\s+para\s+(activar comentarios|comentarios|sostener retención|sostener retencion|retención|retencion|incentivar regalos|seguidores o regalos|regalos o seguidores)$",
            "",
            accion,
            flags=re.IGNORECASE,
        ).strip()

    incluir_momento = bool(momento_limpio)
    if incluir_momento:
        accion_l = accion.lower()
        momento_l = momento_limpio.lower()
        if momento_l in accion_l:
            incluir_momento = False
        if "antes de la primera batalla" in accion_l and ("apertura" in momento_l or "batalla" in momento_l):
            incluir_momento = False
        if "entre partidas" in accion_l and "partidas" in momento_l:
            incluir_momento = False
        if "entre partidas" in accion_l and "mitad" in momento_l:
            accion = re.sub(r"\s+entre partidas\b", "", accion, flags=re.IGNORECASE).strip()
            incluir_momento = False
        if "antes de cada batalla" in accion_l and "batalla" in momento_l:
            incluir_momento = False
        if "cierre" in accion_l and "cierre" in momento_l:
            incluir_momento = False

    frase = f"{etiqueta}: {accion}"
    if incluir_momento:
        frase += f" {momento_limpio}"
    if objetivo_limpio:
        frase += f" para {objetivo_limpio}"

    return frase.strip() + "."



def _bloque_dinamicas_por_intereses(
    intereses_lista: List[str],
    *,
    minimo: int = 2,
    objetivos: Optional[List[str]] = None,
) -> str:
    momentos_def = (
        "antes de la primera batalla",
        "entre partidas",
        "en el cierre del LIVE",
    )
    objs = objetivos or ["activar comentarios", "sostener retención", "incentivar regalos"]
    lineas = []
    for i in range(min(minimo, 3)):
        interes = _interes_por_indice(intereses_lista, i, f"interés {i + 1}")
        lineas.append(
            _linea_dinamica_interes(
                interes,
                i,
                momento=momentos_def[i % len(momentos_def)],
                objetivo=objs[i % len(objs)],
            )
        )
    return "\n".join(lineas)


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




def _valor_metrica_existe_y_menor(reporte: Dict[str, Any], campo: str, umbral: float) -> bool:
    """Evalúa métricas solo cuando el dato existe; evita convertir ausencias en crisis."""
    if not isinstance(reporte, dict) or reporte.get(campo) is None:
        return False
    return safe_float(reporte.get(campo)) < umbral


def _valor_metrica_existe_y_menor_o_igual(reporte: Dict[str, Any], campo: str, umbral: float) -> bool:
    if not isinstance(reporte, dict) or reporte.get(campo) is None:
        return False
    return safe_float(reporte.get(campo)) <= umbral


def _debe_conservar_prioridad_critica(contexto: Dict[str, Any], categoria_norm: str) -> bool:
    """
    Prioridad crítica solo cuando hay señal real de urgencia.
    Si no hay datos fuertes, baja automáticamente a alta para no alarmar al manager.
    """
    categoria_norm = _normalizar_categoria_recomendacion(categoria_norm)
    reporte = _reporte_desde_contexto(contexto)
    score = contexto.get("score") or {}
    alertas = contexto.get("alertas") or []

    for alerta in alertas if isinstance(alertas, list) else []:
        if not isinstance(alerta, dict):
            continue
        nivel = normalizar_lower(alerta.get("nivel_alerta") or "")
        estado = normalizar_lower(alerta.get("estado") or "activa")
        if nivel == "critica" and estado in {"activa", "pendiente"}:
            return True

    riesgo = normalizar_lower(score.get("riesgo_abandono") if isinstance(score, dict) else None)
    score_general = score.get("score_general") if isinstance(score, dict) else None
    score_muy_bajo = score_general is not None and safe_float(score_general) < 35
    riesgo_alto_con_score_bajo = riesgo == "alto" and (score_general is None or safe_float(score_general) < 45)

    if categoria_norm == "monetizacion":
        return (
            _valor_metrica_existe_y_menor(reporte, "porcentaje_logro_diamantes", 35)
            or _valor_metrica_existe_y_menor_o_igual(reporte, "variacion_diamantes_mes_anterior", -30)
            or riesgo_alto_con_score_bajo
        )

    if categoria_norm in {"audiencia", "interaccion"}:
        return (
            _valor_metrica_existe_y_menor(reporte, "porcentaje_logro_nuevos_seguidores", 35)
            or _valor_metrica_existe_y_menor_o_igual(reporte, "variacion_nuevos_seguidores_mes_anterior", -25)
            or riesgo_alto_con_score_bajo
        )

    if categoria_norm in {"horario", "disciplina"}:
        return (
            _valor_metrica_existe_y_menor(reporte, "porcentaje_logro_emisiones", 40)
            or _valor_metrica_existe_y_menor(reporte, "porcentaje_logro_dias_validos", 50)
            or _valor_metrica_existe_y_menor(reporte, "porcentaje_logro_duracion_live", 40)
            or riesgo_alto_con_score_bajo
        )

    if categoria_norm == "tecnica":
        return score_muy_bajo or riesgo_alto_con_score_bajo

    return score_muy_bajo or riesgo_alto_con_score_bajo


def _sufijo_franja_horario(categoria_norm: str, horario: str) -> str:
    """Menciona la franja horaria solo en categorías donde el horario es el foco."""
    h = str(horario or "").strip()
    if h and _normalizar_categoria_recomendacion(categoria_norm) in _CATEGORIAS_CON_FRANJA_HORARIO:
        return f" en {h}"
    return ""


class _TarjetaRecomendacionCtx(TypedDict, total=False):
    nombre: str
    arquetipo: str
    arquetipo_estrategia: Optional[Dict[str, Any]]
    intereses_lista: List[str]
    horario: str
    categoria_nombre: Optional[str]
    meta_diamantes: Any
    datos: Dict[str, Any]


def _tarjeta_ctx_desde_contexto(contexto: Dict[str, Any]) -> _TarjetaRecomendacionCtx:
    datos = _extraer_datos_personalizacion_recomendaciones(contexto)
    return {
        "nombre": datos.get("nombre_creador") or "el creador",
        "arquetipo": datos.get("arquetipo") or "",
        "arquetipo_estrategia": datos.get("arquetipo_estrategia"),
        "intereses_lista": datos.get("intereses_lista") or [],
        "horario": datos.get("horario") or "",
        "categoria_nombre": datos.get("categoria_nombre"),
        "meta_diamantes": datos.get("meta_diamantes"),
        "datos": datos,
    }


def _interes_tarjeta(ctx: _TarjetaRecomendacionCtx, indice: int) -> str:
    return _interes_por_indice(ctx.get("intereses_lista") or [], indice, "")


def _tarjeta_recomendacion_monetizacion(ctx: _TarjetaRecomendacionCtx) -> Dict[str, str]:
    i1 = _interes_tarjeta(ctx, 0)
    datos = ctx.get("datos") or {}
    rec = _recomendacion_monetizacion_estructurada(i1)
    just = _justificacion_monetizacion_desde_datos(datos)
    return {"recomendacion": rec.strip(), "justificacion": just}


def _tarjeta_recomendacion_interaccion(ctx: _TarjetaRecomendacionCtx) -> Dict[str, str]:
    rec = _recomendacion_interaccion_estructurada()
    datos = ctx.get("datos") or {}
    fake_ctx = {
        "arquetipo": {"nombre": datos.get("arquetipo")},
        "perfil": {"arquetipo_valor": datos.get("arquetipo")},
    }
    just = _justificacion_interaccion_natural("", rec, fake_ctx)
    return {
        "recomendacion": rec.strip(),
        "justificacion": just,
    }


def _tarjeta_recomendacion_contenido(ctx: _TarjetaRecomendacionCtx) -> Dict[str, str]:
    i1, i2, i3 = _interes_tarjeta(ctx, 0), _interes_tarjeta(ctx, 1), _interes_tarjeta(ctx, 2)
    temas = [t for t in (i1, i2, i3 if i3 else i1) if t]

    if len(temas) >= 3:
        parrilla = (
            f"Live 1 — {temas[0]} con mini reto; "
            f"Live 2 — {temas[1]} con votación de canción; "
            f"Live 3 — {temas[2]} con duelo de estilos."
        )
    elif len(temas) == 2:
        parrilla = (
            f"Live A — {temas[0]}; Live B — {temas[1]}; repetir el formato que mejor retenga."
        )
    elif len(temas) == 1:
        parrilla = f"Tres lives con variaciones de {temas[0]} (apertura, batalla, cierre)."
    else:
        parrilla = "Tres lives con un formato distinto cada día (apertura, batalla, cierre)."

    rec = f"Mini parrilla semanal: {parrilla}"
    just = (
        "Convertir intereses en retos visibles desde el inicio del LIVE ayuda a atraer "
        "y mantener la atención de la audiencia."
    )
    return {"recomendacion": rec.strip(), "justificacion": just}


def _tarjeta_recomendacion_audiencia(ctx: _TarjetaRecomendacionCtx) -> Dict[str, str]:
    nombre = ctx["nombre"]
    i1 = _interes_tarjeta(ctx, 0)
    gancho = f"tras la dinámica de {i1}" if i1 else "tras el pico de atención del inicio"
    rec = (
        f"Para {nombre}: tres llamados a follow — inicio ({gancho}), "
        f"mitad (después del mejor pico de comentarios), "
        f"cierre (fecha y tema del próximo LIVE para volver)."
    )
    just = _resumen_arquetipo_para_categoria(
        ctx.get("arquetipo_estrategia"), nombre, "audiencia"
    )
    return {
        "recomendacion": rec.strip(),
        "justificacion": just or "Los follows suben en picos de atención, no en momentos muertos.",
    }


def _tarjeta_recomendacion_horario(ctx: _TarjetaRecomendacionCtx) -> Dict[str, str]:
    horario = ctx.get("horario") or "su franja horaria principal"
    rec = (
        f"Definir un horario fijo en {horario} y realizar al menos 3 lives por semana. "
        "Medir asistencia, comentarios y regalos por bloque durante 7 días."
    )
    return {
        "recomendacion": rec.strip(),
        "justificacion": "La consistencia horaria ayuda a crear expectativa y retorno de audiencia.",
    }


def _tarjeta_recomendacion_tecnica(ctx: _TarjetaRecomendacionCtx) -> Dict[str, str]:
    nombre = ctx["nombre"]
    return {
        "recomendacion": (
            f"Para {nombre}: checklist pre-LIVE (luz, audio, encuadre, conexión) en 2 minutos. "
            f"Si hay batallas, revisar volumen de música y delay."
        ),
        "justificacion": "La técnica estable sostiene retención y conversión.",
    }


def _tarjeta_recomendacion_emocional(ctx: _TarjetaRecomendacionCtx) -> Dict[str, str]:
    return {
        "recomendacion": _recomendacion_emocional_estructurada(),
        "justificacion": "Prioridad: sostener energía y ritmo sin saturar al creador.",
    }


def _tarjeta_recomendacion_disciplina(ctx: _TarjetaRecomendacionCtx) -> Dict[str, str]:
    nombre = ctx["nombre"]
    franja = _sufijo_franja_horario("disciplina", ctx.get("horario") or "")
    meta = ctx.get("meta_diamantes")
    meta_txt = f"{meta} diamantes" if meta is not None else "la meta definida"
    return {
        "recomendacion": (
            f"Para {nombre}: rutina mínima — 3 lives{franja}, 20 min de preparación "
            f"y checklist de apertura (tema, meta de regalos, primer saludo)."
        ),
        "justificacion": f"La consistencia sostiene resultados. Meta operativa: {meta_txt}.",
    }


def _tarjeta_recomendacion_otro(ctx: _TarjetaRecomendacionCtx) -> Dict[str, str]:
    return _tarjeta_recomendacion_monetizacion(ctx)


_BUILDERS_TARJETA_RECOMENDACION: Dict[str, Callable[[_TarjetaRecomendacionCtx], Dict[str, str]]] = {
    "monetizacion": _tarjeta_recomendacion_monetizacion,
    "interaccion": _tarjeta_recomendacion_interaccion,
    "contenido": _tarjeta_recomendacion_contenido,
    "audiencia": _tarjeta_recomendacion_audiencia,
    "horario": _tarjeta_recomendacion_horario,
    "tecnica": _tarjeta_recomendacion_tecnica,
    "emocional": _tarjeta_recomendacion_emocional,
    "disciplina": _tarjeta_recomendacion_disciplina,
    "otro": _tarjeta_recomendacion_otro,
}


def _limpiar_horario_de_texto_emocional_disciplina(
    texto: str,
    horario: str,
) -> str:
    """Quita franja horaria y conteo de lives si ya hay tarjeta de horario."""
    if horario:
        texto = re.sub(re.escape(f" en {horario}"), "", texto, flags=re.IGNORECASE)
        texto = re.sub(rf"\ben\s+{re.escape(horario)}\b", "", texto, flags=re.IGNORECASE)
        texto = re.sub(
            r"\(?\s*\d{1,2}\s*(?:am|pm)\s*[–-]\s*\d{1,2}\s*(?:am|pm)\s*\)?",
            "",
            texto,
            flags=re.IGNORECASE,
        )
        texto = re.sub(r"\bTarde\s*\([^)]+\)", "", texto, flags=re.IGNORECASE)
        texto = re.sub(r"\bMañana\s*\([^)]+\)", "", texto, flags=re.IGNORECASE)
        texto = re.sub(r"\bNoche\s*\([^)]+\)", "", texto, flags=re.IGNORECASE)
    texto = re.sub(
        r"\b(?:al menos\s+)?\d+\s+lives?\s+semanal(?:es)?\b",
        "",
        texto,
        flags=re.IGNORECASE,
    )
    texto = re.sub(
        r"\b(?:realizar|hacer)\s+al menos\s+\d+\s+lives?\b",
        "",
        texto,
        flags=re.IGNORECASE,
    )
    texto = re.sub(
        r"\bhorario\s+fijo\s+para\s+sus\s+transmisiones\b",
        "mantener rutina de transmisión",
        texto,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s{2,}", " ", texto).strip()


def _reducir_repeticiones_en_lote_recomendaciones(
    recs: List[Dict[str, Any]],
    datos: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Limpia salidas IA: horario, arquetipo, partidas y «evitar» solo donde corresponde.
    """
    horario = str(datos.get("horario") or "").strip()
    arquetipo = str(datos.get("arquetipo") or "").strip()
    salida: List[Dict[str, Any]] = []
    vio_evitar = False
    vio_partidas = False
    vio_arquetipo_resumen = False
    hay_tarjeta_horario = any(
        _normalizar_categoria_recomendacion(r.get("categoria") or "") == "horario"
        for r in recs
        if isinstance(r, dict)
    )

    patron_evitar = re.compile(
        r"\s*Cuidar que el LIVE no caiga en[^.]+\.",
        re.IGNORECASE,
    )
    patron_partidas = re.compile(
        r"\s*(?:Registra|Con)\s+\d[\d.,]*\s+partidas[^.]*\.",
        re.IGNORECASE,
    )
    patron_como_arquetipo = None
    if arquetipo:
        patron_como_arquetipo = re.compile(
            rf"\s*Como\s+{re.escape(arquetipo)}[^.]*\.",
            re.IGNORECASE,
        )

    for rec in recs:
        if not isinstance(rec, dict):
            continue
        copia = dict(rec)
        cat = _normalizar_categoria_recomendacion(copia.get("categoria") or "otro")

        for campo in ("recomendacion", "justificacion"):
            texto = str(copia.get(campo) or "").strip()
            if not texto:
                continue

            if horario and cat not in _CATEGORIAS_CON_FRANJA_HORARIO:
                texto = re.sub(re.escape(f" en {horario}"), "", texto, flags=re.IGNORECASE)
                texto = re.sub(
                    rf"\ben\s+{re.escape(horario)}\b",
                    "",
                    texto,
                    flags=re.IGNORECASE,
                )

            if hay_tarjeta_horario and cat in ("emocional", "disciplina"):
                texto = _limpiar_horario_de_texto_emocional_disciplina(texto, horario)

            if patron_como_arquetipo and cat not in ("interaccion", "audiencia", "contenido"):
                if patron_como_arquetipo.search(texto):
                    if vio_arquetipo_resumen:
                        texto = patron_como_arquetipo.sub("", texto).strip()
                    else:
                        vio_arquetipo_resumen = True

            if patron_evitar.search(texto):
                if vio_evitar or cat != "monetizacion":
                    texto = patron_evitar.sub("", texto).strip()
                else:
                    vio_evitar = True

            if patron_partidas.search(texto):
                if vio_partidas and cat not in ("monetizacion", "horario"):
                    texto = patron_partidas.sub("", texto).strip()
                else:
                    vio_partidas = True

            texto = re.sub(r"\s{2,}", " ", texto).strip()
            copia[campo] = texto

        salida.append(copia)

    return salida


def _ajustar_prioridad_recomendacion(
    contexto: Dict[str, Any],
    prioridad: Optional[str],
    categoria_norm: str,
) -> str:
    """Evita usar 'critica' cuando la información disponible solo justifica 'alta'."""
    prioridad_norm = validar_valor_en_set(
        prioridad or "media",
        PRIORIDADES_VALIDAS,
        "prioridad",
    ) or "media"

    if prioridad_norm == "critica" and not _debe_conservar_prioridad_critica(contexto, categoria_norm):
        return "alta"

    return prioridad_norm

def _construir_recomendacion_personalizada_fallback(
    contexto: Dict[str, Any],
    categoria: str = "monetizacion",
    prioridad: str = "media",
) -> Dict[str, str]:
    """
    Tarjeta corta por categoría: cada builder aporta solo lo necesario para ese foco.
    Horario, arquetipo y partidas no se repiten en todas las tarjetas.
    """
    categoria_norm = _normalizar_categoria_recomendacion(categoria)
    if _es_contexto_compacto_ia(contexto):
        inteligente = _fallback_inteligente_por_categoria(
            contexto, categoria_norm, str(prioridad)
        )
        if inteligente:
            return _pulir_recomendacion_item(inteligente)

    ctx = _tarjeta_ctx_desde_contexto(contexto)
    builder = _BUILDERS_TARJETA_RECOMENDACION.get(
        categoria_norm,
        _tarjeta_recomendacion_otro,
    )
    cuerpo = builder(ctx)
    prioridad_final = _ajustar_prioridad_recomendacion(contexto, prioridad, categoria_norm)

    return _pulir_recomendacion_item({
        "categoria": categoria_norm,
        "prioridad": prioridad_final,
        "recomendacion": cuerpo["recomendacion"],
        "justificacion": cuerpo["justificacion"],
    })


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
    - exige dinámicas concretas por interés para contenido/interacción/monetización
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
        prioridad_norm = _ajustar_prioridad_recomendacion(
            contexto,
            rec.get("prioridad") or "media",
            categoria_norm,
        )

        rec_pulida = _pulir_recomendacion_final_suave({
            "categoria": categoria_norm,
            "prioridad": prioridad_norm,
            "recomendacion": rec.get("recomendacion"),
            "justificacion": rec.get("justificacion") or rec.get("recomendacion"),
        })
        recomendacion = rec_pulida.get("recomendacion") or ""
        justificacion = rec_pulida.get("justificacion") or recomendacion

        if not recomendacion:
            return

        firma = re.sub(r"\W+", "", recomendacion.lower())[:220]
        if firma in firmas_usadas:
            return

        firmas_usadas.add(firma)
        categorias_usadas.add(categoria_norm)
        normalizadas.append(rec_pulida)

    for rec in recs_raw[:max_recomendaciones]:
        if not isinstance(rec, dict):
            continue

        categoria = _normalizar_categoria_recomendacion(rec.get("categoria") or "otro")
        prioridad = rec.get("prioridad") or "media"
        texto_rec = _limpiar_texto_generado(rec.get("recomendacion"))
        texto_just = _limpiar_texto_generado(rec.get("justificacion"))
        texto_union = f"{texto_rec} {texto_just}"

        if _debe_usar_fallback_recomendacion(
            texto_rec, texto_just, categoria, datos, contexto
        ):
            rec_normalizada = _construir_recomendacion_personalizada_fallback(
                contexto, categoria, str(prioridad)
            )
        else:
            rec_normalizada = _pulir_recomendacion_final_suave({
                "categoria": categoria,
                "prioridad": prioridad,
                "recomendacion": texto_rec,
                "justificacion": texto_just or texto_rec,
            })

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

            texto_basico = f"{texto_b} {just_b}"
            if (
                _es_texto_recomendacion_generico(texto_b)
                or not _cumple_personalizacion_minima_recomendacion(
                    texto_basico, datos, categoria
                )
                or (
                    categoria in _CATEGORIAS_RECOMENDACION_CON_DINAMICAS
                    and not _cumple_dinamicas_intereses_minimas(
                        texto_basico, datos, categoria
                    )
                )
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

    normalizadas = _reducir_repeticiones_en_lote_recomendaciones(
        normalizadas[:max_recomendaciones],
        datos,
    )
    salida["recomendaciones"] = normalizadas
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
- Nombra arquetipo, estrategia operativa del catálogo de arquetipos, intereses (mínimo 2 si existen), horario, categoría/meta y lectura de partidas.
- Explica cómo el arquetipo cambia el plan del manager, sin mencionar nombres técnicos de campos o tablas.
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


_EJEMPLO_FEW_SHOT_RECOMENDACIONES = """
EJEMPLO DE SALIDA ESPERADA (creador inventado — imita el estilo, no los datos):
{
  "recomendaciones": [
    {
      "categoria": "emocional",
      "prioridad": "alta",
      "recomendacion": "Establecer un reto semanal de 3 lives y celebrar el cumplimiento 3/3 antes de subir exigencia de metas.",
      "justificacion": "Prioridad: sostener energía y ritmo sin saturar a la creadora."
    },
    {
      "categoria": "horario",
      "prioridad": "alta",
      "recomendacion": "Definir un horario fijo en Noche (7pm–11pm) y realizar al menos 3 lives por semana. Medir asistencia, comentarios y regalos por bloque durante 7 días.",
      "justificacion": "La consistencia horaria ayuda a crear expectativa y retorno de audiencia."
    },
    {
      "categoria": "contenido",
      "prioridad": "alta",
      "recomendacion": "Mini parrilla semanal: Live 1 — Baile con mini reto; Live 2 — Moda con votación de canción; Live 3 — Humor con duelo de estilos.",
      "justificacion": "Convertir intereses en retos visibles desde el inicio del LIVE ayuda a atraer y mantener la atención de la audiencia."
    },
    {
      "categoria": "interaccion",
      "prioridad": "alta",
      "recomendacion": "Dividir la audiencia en 2 equipos antes de cada batalla, lanzar una pregunta rápida y mostrar un ranking simbólico. Reconocer en vivo al top 3 que comenta o apoya en cada ronda.",
      "justificacion": "Como creadora de entretenimiento, la interacción debe sentirse como reto, competencia y reconocimiento público."
    },
    {
      "categoria": "monetizacion",
      "prioridad": "alta",
      "recomendacion": "Implementar metas pequeñas de regalos por tramo usando Baile como gancho: apertura para activar el primer mini reto, mitad del LIVE para desbloquear 30 segundos de energía y cierre para elegir el reto del próximo LIVE.",
      "justificacion": "Esto convierte la meta Bronce de 5000 diamantes en pasos pequeños y más fáciles de apoyar para la audiencia."
    }
  ]
}
"""


def prompt_recomendaciones_manager_v2(
    contexto: Dict[str, Any],
    *,
    max_recomendaciones: int = 5,
    instrucciones_extra: Optional[str] = None,
) -> str:
    instrucciones_extra_txt = instrucciones_extra or ""

    return f"""
Actúa como coach senior de creadores TikTok LIVE para una agencia.

Voy a darte un JSON con datos reales de un creador. Tu tarea es generar recomendaciones operativas para el manager.

Usa SOLO los datos que aparecen en el JSON.
No inventes datos.
No uses lenguaje técnico interno.
No menciones nombres de campos como estrategia_json, metadata, contexto, JSON, perfil_estrategico o performance_partidas.
No copies textos completos del arquetipo; úsalo solo para orientar la recomendación.
No repitas la misma acción en varias categorías.

IMPORTANTE SOBRE METAS:
- Si existe una meta mensual en el JSON, úsala como meta operativa principal.
- La meta de categoría, por ejemplo Bronce 5000 diamantes, solo sirve como referencia de nivel.
- No digas que el creador debe alcanzar la meta de categoría si sus diamantes del periodo ya superan esa cifra.
- Si los diamantes de partidas son mayores que los diamantes del mes, no lo presentes como porcentaje normal. Úsalo solo como señal de que las batallas/partidas son relevantes.

IMPORTANTE SOBRE FRECUENCIA Y HORARIO:
- No recomiendes aumentar frecuencia si el creador ya tiene buen cumplimiento en días válidos, emisiones o duración.
- En ese caso, recomienda optimizar bloques dentro de la franja actual.
- Horario solo debe hablar de franja, días, bloques y medición. No mezcles horario con emocional ni contenido.

IMPORTANTE SOBRE BATALLAS:
- Si el arquetipo es Batallista pero el perfil muestra baja comodidad con batallas o PK, no asumas que domina las batallas.
- Recomienda batallas estructuradas, progresivas y fáciles de ejecutar.

Genera exactamente {max_recomendaciones} recomendaciones.

Cada recomendación debe tener:
1. categoria
2. prioridad
3. recomendacion concreta para el manager
4. justificacion basada en datos del creador

Categorías permitidas:
- monetizacion
- interaccion
- contenido
- audiencia
- horario
- tecnica
- emocional
- disciplina

Reglas por categoría:

MONETIZACIÓN:
Debe hablar de regalos, metas, diamantes, tramos, batallas o partidas.
Debe ser una acción concreta, no genérica.
Idealmente dividir la acción en apertura, mitad del LIVE y cierre.

INTERACCIÓN:
Debe hablar de chat, equipos, preguntas, ranking, reconocimiento, top apoyadores o dinámica de batalla.
No basta con decir "mejorar interacción".
Si el perfil muestra dificultad leyendo chat o multitarea, usa estructuras simples.

CONTENIDO:
Debe convertir intereses del creador en una mini parrilla:
Live 1 —
Live 2 —
Live 3 —

AUDIENCIA:
Debe hablar de seguidores, comunidad, retorno al próximo LIVE, retención o conversión a follow.

HORARIO:
Solo debe hablar de franja horaria, días, bloques y medición.

TÉCNICA:
Debe usar datos de equipo, iluminación, herramientas, setup, cámara, audio, portada o título si aparecen en el JSON.

EMOCIONAL:
Debe hablar de energía, confianza, ritmo, constancia o no saturar al creador.
No menciones diamantes ni horario aquí.

DISCIPLINA:
Debe hablar de rutina, preparación, cumplimiento, feedback, métricas o constancia.

Instrucciones adicionales del manager:
{instrucciones_extra_txt}

Formato obligatorio:
Devuelve únicamente JSON válido, sin explicación antes ni después.

Schema exacto:

{{
  "recomendaciones": [
    {{
      "categoria": "monetizacion",
      "prioridad": "alta",
      "recomendacion": "texto concreto y accionable",
      "justificacion": "motivo basado en datos del JSON"
    }}
  ]
}}

Antes de responder, verifica internamente que:
- cada recomendación sea diferente
- cada recomendación use datos reales del JSON
- cada recomendación pueda ejecutarse esta semana por un manager
- no haya lenguaje técnico interno
- no se repita la misma acción en varias categorías

JSON DEL CREADOR:
{contexto_para_prompt(contexto)}
"""


def prompt_recomendaciones_manager_v3(
    contexto: Dict[str, Any],
    *,
    max_recomendaciones: int = 5,
    instrucciones_extra: Optional[str] = None,
) -> str:
    bloque_metricas = _bloque_metricas_recomendaciones(contexto)
    bloque_perfil = _bloque_senales_perfil_recomendaciones(contexto)
    instrucciones_extra_txt = instrucciones_extra or ""

    return f"""
Actúa como coach senior de creadores TikTok LIVE para una agencia.

Vas a recibir datos compactos y reales de un creador. Tu tarea es generar recomendaciones operativas para el manager.

Usa SOLO los datos entregados.
No inventes datos.
No uses información externa.
No uses lenguaje técnico interno.
No menciones palabras como JSON, metadata, estrategia_json, contexto, schema, tabla o base de datos.
No copies textos completos del arquetipo; úsalo solo como orientación.
No repitas la misma acción en varias categorías.
No escribas frases del tipo "Como juego" o "Como metadata".

OBJETIVO:
Generar exactamente {max_recomendaciones} recomendaciones accionables para mejorar el performance del creador.

FORMATO OBLIGATORIO:
Devuelve únicamente JSON válido, sin explicación antes ni después.

Schema exacto:

{{
  "recomendaciones": [
    {{
      "categoria": "monetizacion",
      "prioridad": "alta",
      "recomendacion": "acción concreta para el manager",
      "justificacion": "motivo basado en datos reales del creador"
    }}
  ]
}}

Categorías permitidas:
- monetizacion
- interaccion
- contenido
- audiencia
- horario
- tecnica
- emocional
- disciplina

Prioridades permitidas:
- baja
- media
- alta
- critica

Usa prioridad "critica" solo si hay riesgo grave, caída fuerte, abandono, cero actividad o incumplimiento severo. Si no, usa baja, media o alta.

REGLA CENTRAL:
Las métricas dicen qué está pasando.
El perfil del creador explica por qué pasa y cómo corregirlo.

Debes cruzar:
1. métricas del reporte
2. metas mensuales
3. respuestas del perfil/cuestionario
4. arquetipo
5. intereses

{bloque_metricas}

{bloque_perfil}

REGLAS OBLIGATORIAS SOBRE MÉTRICAS:
- Al menos 3 de las recomendaciones deben mencionar métricas reales del reporte o de metas.
- Monetización debe usar meta mensual, diamantes del periodo, partidas o diamantes de partidas.
- Audiencia debe usar nuevos seguidores o meta de nuevos seguidores si aparecen.
- Horario o disciplina debe usar días válidos, emisiones, duración o meta de horas si aparecen.
- No uses la meta de categoría como meta principal si existe una meta mensual.
- Si existe una meta mensual de diamantes, esa es la meta operativa principal.
- La meta de categoría, como Bronce 5000 diamantes, solo sirve como referencia de nivel.
- No digas "alcanzar Bronce" o "alcanzar 5000 diamantes" si el creador ya supera esa cifra.
- Si los diamantes de partidas son mayores que los diamantes del mes, no lo presentes como porcentaje normal; úsalo solo como señal de que las partidas/batallas son relevantes.
- Si una métrica porcentual contradice el valor absoluto y la meta, prioriza valor absoluto + meta y evita afirmaciones matemáticas dudosas.
- Si el creador ya tiene alto volumen de emisiones, días válidos o duración, no recomiendes simplemente "transmitir más"; recomienda optimizar bloques, productividad o conversión.

REGLAS OBLIGATORIAS SOBRE PERFIL:
- Al menos 3 de las recomendaciones deben usar una señal concreta del perfil/cuestionario.
- Interacción debe usar fluidez hablando, manejo del chat, multitarea o actitud frente a batallas si existen.
- Técnica debe usar equipo, iluminación, herramientas, uso operativo, setup, cámara, audio, portada o calidad técnica si existen.
- Emocional debe usar energía en vivos largos, frustración, constancia o feedback inmediato si existen.
- Monetización debe usar dificultad para pedir regalos, actitud frente a batallas, resultados de monetización o comodidad con metas si existen.
- Disciplina debe usar análisis de métricas, feedback inmediato, disponibilidad, frecuencia de videos o cumplimiento si existen.
- Horario debe usar horario preferido, disponibilidad y métricas reales de emisiones/días válidos si existen.
- No asumas que el creador domina batallas solo porque su arquetipo es Batallista. Si el perfil muestra baja comodidad con batallas, recomienda batallas progresivas, guiadas y simples.
- Si el perfil muestra dificultad para leer chat o manejar regalos al mismo tiempo, no propongas dinámicas complejas; usa estructuras simples como 2 equipos, pregunta rápida y top 3.
- Si el perfil muestra que la energía cae después de la primera hora, concentra los retos fuertes al inicio y recomienda pausas estratégicas.
- Si el perfil muestra baja iluminación o equipo básico, incluye una mejora técnica simple antes de cambios avanzados.
- Si el perfil muestra buen feedback inmediato, recomienda tareas semanales porque el creador puede aplicar correcciones rápido.
- Si el perfil muestra análisis de métricas regular o bajo, recomienda una rutina simple de revisión post-LIVE.

REGLAS POR CATEGORÍA:

MONETIZACIÓN:
Debe hablar de regalos, metas, diamantes, tramos, batallas o partidas.
Debe usar números reales si existen.
Debe cruzar métricas + perfil.
Debe adaptar la recomendación si pedir regalos le cuesta o si la comodidad con batallas es baja.

INTERACCIÓN:
Debe hablar de chat, equipos, preguntas, ranking, reconocimiento, top apoyadores o dinámica de batalla.
No basta con decir "mejorar interacción".
Debe cruzar fluidez hablando + dificultad con chat/multitarea + arquetipo si esos datos aparecen.

CONTENIDO:
Debe convertir los intereses del creador en una mini parrilla:
Live 1 —
Live 2 —
Live 3 —
Cada Live debe tener una dinámica concreta, no solo un tema.
Debe cruzar intereses + producción de video + frecuencia de videos si existen.
Si tiene buena producción de video pero publica pocos videos, recomienda reutilizar momentos fuertes de LIVE como clips.

AUDIENCIA:
Debe hablar de seguidores, comunidad, retorno al próximo LIVE, retención o conversión a follow.
Debe usar nuevos seguidores del periodo o meta de nuevos seguidores si aparecen.
Si el perfil muestra baja red de contactos, enfoca audiencia en convertir espectadores actuales a seguidores recurrentes.

HORARIO:
Solo debe hablar de franja horaria, días, bloques y medición.
No mezcles horario con emocional ni contenido.
Si ya hay muchas emisiones o días válidos, recomienda optimizar el mejor bloque, no aumentar días.

TÉCNICA:
Debe usar datos de equipo, iluminación, herramientas, setup, cámara, audio, portada o título si aparecen.
La recomendación debe ser práctica y ejecutable.

EMOCIONAL:
Debe hablar de energía, confianza, ritmo, constancia o no saturar al creador.
No menciones diamantes ni horario aquí.
Si el perfil indica que la energía cae en vivos largos, recomienda concentrar retos fuertes al inicio y usar pausas estratégicas.
Si hay frustración con crecimiento lento, incluye celebración de avances.

DISCIPLINA:
Debe hablar de rutina, preparación, cumplimiento, feedback, revisión de métricas o constancia.
Si ya hay alto volumen de transmisiones, enfócate en productividad por LIVE.

EVITA:
- recomendaciones genéricas
- repetir la misma acción con otras palabras
- decir "mejorar interacción" sin explicar cómo
- decir "transmitir más" si ya hay muchas emisiones/días válidos
- usar la meta de categoría como meta principal si hay meta mensual
- usar palabras absolutas como "garantiza", "definitivo", "única palanca", "prioridad absoluta"
- decir "Como juego" o usar arquetipos mal interpretados
- reemplazar datos reales por frases genéricas

Instrucciones adicionales del manager:
{instrucciones_extra_txt}

Antes de responder, verifica internamente:
- que haya exactamente {max_recomendaciones} recomendaciones
- que al menos 3 usen métricas reales
- que al menos 3 usen señales del perfil
- que monetización use meta mensual o diamantes/partidas
- que interacción use chat/fluidez/multitarea si aparece
- que técnica use iluminación/equipo/herramientas si aparece
- que emocional use energía/frustración/ritmo si aparece
- que cada recomendación pueda ejecutarse esta semana por un manager

Datos completos del creador:
{contexto_para_prompt(contexto)}
"""


def prompt_recomendaciones_manager(contexto: Dict[str, Any], max_recomendaciones: int, instrucciones_extra: Optional[str] = None) -> str:
    extra = f"\nInstrucciones adicionales:\n{instrucciones_extra}\n" if instrucciones_extra else ""
    reglas = _reglas_personalizacion_ia_obligatorias(contexto)
    datos_obligatorios = _bloque_datos_obligatorios_recomendaciones(contexto)
    datos_por_categoria = _bloque_datos_por_categoria_recomendaciones(contexto)

    return f"""
Eres un coach senior de creadores TikTok LIVE y asesor de managers de agencia.
Genera recomendaciones operativas específicas para el creador del contexto.
Responde únicamente con un objeto JSON válido en español.

{datos_obligatorios}

{datos_por_categoria}

{reglas}

{_REGLAS_ANTI_REPETICION_TARJETAS}

{_EJEMPLO_FEW_SHOT_RECOMENDACIONES}

Reglas de salida:
- Usa los datos reales del creador del contexto, no los del ejemplo.
- Devuelve JSON válido con la clave "recomendaciones".
- No repitas horario fuera de la tarjeta horario.
- No repitas partidas fuera de monetización.
- No repitas la misma mecánica dos veces en una tarjeta.
- Máximo 420 caracteres en "recomendacion" y 220 en "justificacion".
- Texto natural para manager; sin nombres técnicos internos.
- Entre 1 y {max_recomendaciones} recomendaciones; prioridad "alta" salvo caída fuerte (entonces "critica").
- Si partidas >100% de diamantes, no uses el porcentaje como cifra exacta.

Contexto completo (solo para razonar; no copies nombres de campos al manager):
{contexto_para_prompt(contexto)}

{extra}

{_REGLAS_PROHIBIDO_LENGUAJE_TECNICO_MANAGER}

Formato JSON requerido:
{{
  "recomendaciones": [
    {{
      "categoria": "monetizacion|disciplina|horario|contenido|interaccion|audiencia|tecnica|emocional|otro",
      "prioridad": "baja|media|alta|critica",
      "recomendacion": "acción concreta para el manager",
      "justificacion": "por qué importa según métricas o perfil"
    }}
  ]
}}
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
estrategia operativa del catálogo de arquetipos, al menos 2 intereses convertidos en dinámicas concretas,
horario concreto (si existe), categoría/meta y decisión sobre partidas según performance_partidas.

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
- Fundamenta con arquetipo, estrategia operativa del catálogo de arquetipos, intereses (≥2 si existen), horario, categoría/meta y lectura de partidas.
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
arquetipo por nombre, estrategia operativa del catálogo de arquetipos, ≥2 intereses convertidos
en dinámicas concretas, horario, categoría/meta y plan sobre partidas.
Conserva la intención del manager; no sustituyas por texto genérico.

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
# PIPELINE LIMPIO — RECOMENDACIONES (sin postprocesado agresivo)
# =========================================================

_CATEGORIAS_RECOMENDACION_LIMPIAS = frozenset({
    "monetizacion",
    "interaccion",
    "contenido",
    "audiencia",
    "horario",
    "tecnica",
    "emocional",
    "disciplina",
})

_PRIORIDADES_RECOMENDACION_LIMPIAS = frozenset({
    "baja",
    "media",
    "alta",
    "critica",
})

_FRASES_BLOQUEANTES_RECOMENDACIONES = (
    "meta bronce de 5000",
    "meta categoría",
    "meta categoria",
    "meta de categoría",
    "meta de categoria",
    "por su estilo participación activa",
    "por su estilo participacion activa",
    "según el json",
    "segun el json",
    "del contexto",
    "metadata",
    "estrategia_json",
    "schema",
    "base de datos",
)


def _normalizar_estructura_recomendaciones_minima(
    resultado: Any,
    *,
    max_recomendaciones: int = 5,
) -> Dict[str, Any]:
    if not isinstance(resultado, dict):
        return {"recomendaciones": []}

    recs = resultado.get("recomendaciones")
    if not isinstance(recs, list):
        return {"recomendaciones": []}

    salida: List[Dict[str, Any]] = []

    for rec in recs:
        if not isinstance(rec, dict):
            continue

        categoria = _normalizar_categoria_recomendacion(rec.get("categoria") or "")
        if categoria not in _CATEGORIAS_RECOMENDACION_LIMPIAS:
            continue

        prioridad = str(rec.get("prioridad") or "media").strip().lower()
        if prioridad not in _PRIORIDADES_RECOMENDACION_LIMPIAS:
            prioridad = "media"

        recomendacion = str(rec.get("recomendacion") or "").strip()
        justificacion = str(rec.get("justificacion") or "").strip()

        if not recomendacion:
            continue

        salida.append({
            "categoria": categoria,
            "prioridad": prioridad,
            "recomendacion": recomendacion,
            "justificacion": justificacion,
        })

        if len(salida) >= max_recomendaciones:
            break

    return {"recomendaciones": salida}


def _texto_contiene_numero_operativo(
    texto: str,
    contexto: Dict[str, Any],
) -> bool:
    texto_norm = (
        str(texto or "")
        .lower()
        .replace(",", "")
        .replace(".", "")
        .replace(" ", "")
    )

    metricas = _extraer_metricas_reporte_recomendaciones(contexto)

    valores = [
        metricas.get("meta_mensual_diamantes"),
        metricas.get("meta_horas_live"),
        metricas.get("meta_dias_validos"),
        metricas.get("meta_emisiones"),
        metricas.get("meta_nuevos_seguidores"),
        metricas.get("diamantes_mes"),
        metricas.get("duracion_live_mes_minutos"),
        metricas.get("dias_validos_live_mes"),
        metricas.get("emisiones_live_mes"),
        metricas.get("nuevos_seguidores_mes"),
        metricas.get("partidas"),
        metricas.get("diamantes_de_partidas"),
        metricas.get("porcentaje_logro_diamantes"),
        metricas.get("porcentaje_logro_duracion_live"),
        metricas.get("porcentaje_logro_dias_validos"),
        metricas.get("porcentaje_logro_emisiones"),
        metricas.get("porcentaje_logro_nuevos_seguidores"),
    ]

    for valor in valores:
        if valor is None or valor == "":
            continue

        try:
            numero = float(valor)
            if numero.is_integer():
                variantes = [str(int(numero))]
            else:
                variantes = [str(numero), str(numero).rstrip("0").rstrip(".")]
        except Exception:
            variantes = [str(valor)]

        for variante in variantes:
            variante_norm = (
                variante.lower()
                .replace(",", "")
                .replace(".", "")
                .replace(" ", "")
            )
            if variante_norm and variante_norm in texto_norm:
                return True

    return False


def _recomendacion_tiene_meta_categoria_prohibida(
    rec: Dict[str, Any],
    contexto: Dict[str, Any],
) -> bool:
    return _recomendacion_usa_meta_categoria_prohibida(rec, contexto)


def _recomendacion_tiene_senal_perfil_limpia(
    rec: Dict[str, Any],
    contexto: Dict[str, Any],
) -> bool:
    texto = (
        f"{rec.get('recomendacion') or ''} {rec.get('justificacion') or ''}"
    ).lower()

    senales_fuertes = (
        "se distrae",
        "leer el chat",
        "dejar de hablar",
        "fluidez",
        "primera hora",
        "energía cae",
        "energia cae",
        "luz natural",
        "celular",
        "iluminación",
        "iluminacion",
        "herramientas",
        "funciones live",
        "uso operativo",
        "le cuesta pedir",
        "pedir regalos",
        "comodidad con batallas",
        "prefiere no participar",
        "no le gustan",
        "aplica correcciones",
        "feedback inmediato",
        "analiza métricas",
        "analiza metricas",
        "de vez en cuando",
        "1 a 2 videos",
        "red de contactos",
        "otros creadores",
        "crecimiento lento",
        "se frustra",
        "calidad técnica",
        "calidad tecnica",
        "producción de video",
        "produccion de video",
        "multitarea",
        "multitask",
        "batallas",
        " pk",
    )

    if any(s in texto for s in senales_fuertes):
        return True

    senales = _extraer_senales_perfil_recomendaciones(contexto)
    for valor in senales.values():
        fragmento = str(valor).lower()[:50]
        if fragmento and len(fragmento) > 4 and fragmento in texto:
            return True

    return False


def _validar_recomendaciones_limpias(
    resultado: Dict[str, Any],
    contexto: Dict[str, Any],
    *,
    max_recomendaciones: int = 5,
) -> Dict[str, Any]:
    errores: List[str] = []
    detalle: List[Dict[str, Any]] = []

    recs = resultado.get("recomendaciones") if isinstance(resultado, dict) else None

    if not isinstance(recs, list):
        return {
            "ok": False,
            "errores": ["La respuesta no contiene lista recomendaciones."],
            "detalle": [],
            "total_con_metricas_reales": 0,
            "total_con_senal_perfil": 0,
        }

    if len(recs) != max_recomendaciones:
        errores.append(
            f"Debe devolver exactamente {max_recomendaciones} recomendaciones "
            f"y devolvió {len(recs)}."
        )

    total_metricas = 0
    total_perfil = 0
    categorias: set = set()

    for idx, rec in enumerate(recs, start=1):
        if not isinstance(rec, dict):
            continue

        categoria = rec.get("categoria")
        categorias.add(categoria)

        texto = f"{rec.get('recomendacion') or ''} {rec.get('justificacion') or ''}"
        texto_lower = texto.lower()

        for frase in _FRASES_BLOQUEANTES_RECOMENDACIONES:
            if frase in texto_lower:
                errores.append(f"Recomendación {idx} contiene frase bloqueada: {frase}")

        usa_metricas = _texto_contiene_numero_operativo(texto, contexto)
        usa_perfil = _recomendacion_tiene_senal_perfil_limpia(rec, contexto)
        usa_meta_categoria = _recomendacion_tiene_meta_categoria_prohibida(rec, contexto)

        if usa_metricas:
            total_metricas += 1
        if usa_perfil:
            total_perfil += 1

        if usa_meta_categoria:
            errores.append(f"Recomendación {idx} usa meta de categoría como meta principal.")

        if categoria == "monetizacion" and not usa_metricas:
            errores.append(
                "Monetización debe mencionar meta mensual, diamantes, partidas o "
                "diamantes de partidas con número real."
            )

        if categoria == "audiencia" and not usa_metricas:
            errores.append(
                "Audiencia debe mencionar nuevos seguidores o meta de seguidores con número real."
            )

        if categoria in {"disciplina", "horario"} and not usa_metricas:
            errores.append(
                f"{categoria} debe mencionar emisiones, días válidos, duración o metas con número real."
            )

        detalle.append({
            "idx": idx,
            "categoria": categoria,
            "usa_metricas_reales": usa_metricas,
            "usa_senal_perfil": usa_perfil,
            "usa_meta_categoria_prohibida": usa_meta_categoria,
        })

    if total_metricas < 3:
        errores.append(
            f"Solo {total_metricas} recomendaciones usan métricas reales; se requieren al menos 3."
        )

    if total_perfil < 3:
        errores.append(
            f"Solo {total_perfil} recomendaciones usan señales de perfil; se requieren al menos 3."
        )

    if "monetizacion" not in categorias:
        errores.append("Falta recomendación de monetización.")

    if "audiencia" not in categorias:
        errores.append("Falta recomendación de audiencia.")

    return {
        "ok": len(errores) == 0,
        "errores": errores,
        "detalle": detalle,
        "total_con_metricas_reales": total_metricas,
        "total_con_senal_perfil": total_perfil,
    }


def prompt_recomendaciones_manager_v4_limpio(
    contexto: Dict[str, Any],
    *,
    max_recomendaciones: int = 5,
    instrucciones_extra: Optional[str] = None,
) -> str:
    instrucciones_extra_txt = instrucciones_extra or ""

    return f"""
Actúa como coach senior de creadores TikTok LIVE para una agencia.

Voy a darte un JSON compacto con datos reales de un creador. Tu tarea es generar recomendaciones operativas para el manager usando SOLO ese JSON.

No inventes datos.
No uses información externa.
No uses lenguaje técnico interno.
No menciones palabras como JSON, metadata, estrategia_json, contexto, schema, tabla o base de datos.
No copies textos completos del arquetipo; úsalo solo como orientación.
No repitas la misma acción en varias categorías.

OBJETIVO:
Generar exactamente {max_recomendaciones} recomendaciones accionables para mejorar el performance del creador.

FORMATO OBLIGATORIO:
Devuelve únicamente JSON válido, sin explicación antes ni después.

Schema exacto:

{{
  "recomendaciones": [
    {{
      "categoria": "monetizacion",
      "prioridad": "alta",
      "recomendacion": "acción concreta para el manager",
      "justificacion": "motivo basado en datos reales del creador"
    }}
  ]
}}

Categorías permitidas:
- monetizacion
- interaccion
- contenido
- audiencia
- horario
- tecnica
- emocional
- disciplina

Prioridades permitidas:
- baja
- media
- alta
- critica

Usa prioridad "critica" solo si hay riesgo grave, caída fuerte, abandono, cero actividad o incumplimiento severo. Si no, usa baja, media o alta.

REGLA CENTRAL:
Las métricas dicen qué está pasando.
El perfil del creador explica por qué pasa y cómo corregirlo.

Debes cruzar:
1. métricas del reporte
2. metas mensuales
3. respuestas del perfil/cuestionario
4. arquetipo
5. intereses

REGLAS OBLIGATORIAS SOBRE MÉTRICAS:
- Al menos 3 de las {max_recomendaciones} recomendaciones deben mencionar números reales del reporte o de metas.
- Monetización debe usar meta mensual, diamantes del periodo, partidas o diamantes de partidas.
- Audiencia debe usar nuevos seguidores o meta de nuevos seguidores si aparecen.
- Horario o disciplina debe usar días válidos, emisiones, duración, meta de horas o meta de emisiones si aparecen.
- No uses la meta de categoría como meta principal si existe una meta mensual.
- Si existe metas.meta_diamantes, esa es la meta operativa principal.
- La meta de categoría, como Bronce 5000 diamantes, solo sirve como referencia de nivel.
- No digas "alcanzar Bronce" o "alcanzar 5000 diamantes" si el creador ya supera esa cifra.
- Si los diamantes de partidas son mayores que los diamantes del mes, no lo presentes como porcentaje normal; úsalo solo como señal de que las partidas/batallas son relevantes.
- Si una métrica porcentual contradice el valor absoluto y la meta, prioriza valor absoluto + meta y evita afirmaciones matemáticas dudosas.
- Si el creador ya tiene alto volumen de emisiones, días válidos o duración, no recomiendes simplemente "transmitir más"; recomienda optimizar bloques, productividad o conversión.

REGLAS OBLIGATORIAS SOBRE PERFIL:
- Al menos 3 de las {max_recomendaciones} recomendaciones deben usar una señal concreta del perfil/cuestionario.
- Interacción debe usar fluidez hablando, manejo del chat, multitarea o actitud frente a batallas si existen.
- Técnica debe usar equipo, iluminación, herramientas, uso operativo, setup, cámara, audio, portada o calidad técnica si existen.
- Emocional debe usar energía en vivos largos, frustración, constancia o feedback inmediato si existen.
- Monetización debe usar dificultad para pedir regalos, actitud frente a batallas, resultados de monetización o comodidad con metas si existen.
- Disciplina debe usar análisis de métricas, feedback inmediato, disponibilidad, frecuencia de videos o cumplimiento si existen.
- Horario debe usar horario preferido, disponibilidad y métricas reales de emisiones/días válidos si existen.
- No asumas que el creador domina batallas solo porque su arquetipo es Batallista. Si el perfil muestra baja comodidad con batallas, recomienda batallas progresivas, guiadas y simples.
- Si el perfil muestra dificultad para leer chat o manejar regalos al mismo tiempo, no propongas dinámicas complejas; usa estructuras simples como 2 equipos, pregunta rápida y top 3.
- Si el perfil muestra que la energía cae después de la primera hora, concentra los retos fuertes al inicio y recomienda pausas estratégicas.
- Si el perfil muestra baja iluminación o equipo básico, incluye una mejora técnica simple antes de cambios avanzados.
- Si el perfil muestra buen feedback inmediato, recomienda tareas semanales porque el creador puede aplicar correcciones rápido.
- Si el perfil muestra análisis de métricas regular o bajo, recomienda una rutina simple de revisión post-LIVE.

REGLAS POR CATEGORÍA:

MONETIZACIÓN:
Debe hablar de regalos, metas, diamantes, tramos, batallas o partidas.
Debe usar números reales si existen.
Debe cruzar métricas + perfil.
Debe adaptar la recomendación si pedir regalos le cuesta o si la comodidad con batallas es baja.
Ejemplo de estilo:
"Dividir la meta mensual de 306503 diamantes en objetivos por bloque de LIVE: apertura con meta rápida de regalos, mitad del directo con batallas cortas guiadas y cierre con reto final entre equipos."

INTERACCIÓN:
Debe hablar de chat, equipos, preguntas, ranking, reconocimiento, top apoyadores o dinámica de batalla.
No basta con decir "mejorar interacción".
Debe cruzar fluidez hablando + dificultad con chat/multitarea + arquetipo si esos datos aparecen.
No escribas frases como "Por su estilo participación activa...".
Ejemplo de estilo:
"Tiene buena fluidez hablando, pero se distrae al leer chat; por eso la dinámica debe ser simple."

CONTENIDO:
Debe convertir los intereses del creador en una mini parrilla:
Live 1 —
Live 2 —
Live 3 —
Cada Live debe tener una dinámica concreta, no solo un tema.
Debe cruzar intereses + producción de video + frecuencia de videos si existen.
Si tiene buena producción de video pero publica pocos videos, recomienda reutilizar momentos fuertes de LIVE como clips.

AUDIENCIA:
Debe hablar de seguidores, comunidad, retorno al próximo LIVE, retención o conversión a follow.
Debe usar nuevos seguidores del periodo o meta de nuevos seguidores si aparecen.
Si el perfil muestra baja red de contactos, enfoca audiencia en convertir espectadores actuales a seguidores recurrentes.

HORARIO:
Solo debe hablar de franja horaria, días, bloques y medición.
No mezcles horario con emocional ni contenido.
Si ya hay muchas emisiones o días válidos, recomienda optimizar el mejor bloque, no aumentar días.

TÉCNICA:
Debe usar datos de equipo, iluminación, herramientas, setup, cámara, audio, portada o título si aparecen.
La recomendación debe ser práctica y ejecutable.

EMOCIONAL:
Debe hablar de energía, confianza, ritmo, constancia o no saturar al creador.
No menciones diamantes ni horario aquí.
Si el perfil indica que la energía cae en vivos largos, recomienda concentrar retos fuertes al inicio y usar pausas estratégicas.
Si hay frustración con crecimiento lento, incluye celebración de avances.

DISCIPLINA:
Debe hablar de rutina, preparación, cumplimiento, feedback, revisión de métricas o constancia.
Si ya hay alto volumen de transmisiones, enfócate en productividad por LIVE.

EVITA:
- recomendaciones genéricas
- repetir la misma acción con otras palabras
- decir "mejorar interacción" sin explicar cómo
- decir "transmitir más" si ya hay muchas emisiones/días válidos
- usar la meta de categoría como meta principal si hay meta mensual
- usar palabras absolutas como "garantiza", "definitivo", "única palanca", "prioridad absoluta"
- decir "Como juego" o usar arquetipos mal interpretados
- reemplazar datos reales por frases genéricas
- escribir "Esto convierte la meta Bronce de 5000 diamantes"

Instrucciones adicionales del manager:
{instrucciones_extra_txt}

Antes de responder, verifica internamente:
- que haya exactamente {max_recomendaciones} recomendaciones
- que al menos 3 usen números reales
- que al menos 3 usen señales del perfil
- que monetización use meta mensual o diamantes/partidas
- que interacción use chat/fluidez/multitarea si aparece
- que técnica use iluminación/equipo/herramientas si aparece
- que emocional use energía/frustración/ritmo si aparece
- que cada recomendación pueda ejecutarse esta semana por un manager

Datos del creador:
{contexto_para_prompt(contexto)}
"""


def prompt_corregir_recomendaciones_limpias(
    *,
    contexto: Dict[str, Any],
    resultado_anterior: Optional[Dict[str, Any]] = None,
    errores: Optional[Dict[str, Any]] = None,
    max_recomendaciones: int = 5,
) -> str:
    del resultado_anterior  # no incluir respuesta fallida en el prompt

    return f"""
Regenera desde cero las recomendaciones.

La respuesta anterior falló validación.
NO copies frases de la respuesta anterior.
NO intentes parchar la respuesta anterior.
Crea una nueva respuesta desde cero usando solo los datos del creador.

Errores detectados:
{contexto_para_prompt(errores or {})}

Reglas obligatorias:
- Devuelve exactamente {max_recomendaciones} recomendaciones.
- Devuelve únicamente JSON válido.
- Al menos 3 recomendaciones deben contener números reales del reporte o metas.
- Al menos 3 recomendaciones deben usar señales reales del perfil.
- Monetización debe usar meta mensual, diamantes, partidas o diamantes de partidas.
- Audiencia debe usar nuevos seguidores o meta de nuevos seguidores.
- Disciplina u horario debe usar emisiones, días válidos, duración o metas.
- No uses la meta de categoría como meta principal.
- No escribas "meta Bronce de 5000".
- No escribas "Por su estilo participación activa".
- No uses lenguaje técnico interno.
- No digas JSON, contexto, metadata, tabla, schema o estrategia_json.
- Si el perfil dice que las batallas le cuestan o no le gustan, recomienda batallas guiadas, simples y progresivas.
- Si el perfil dice que se distrae con el chat, recomienda mecánicas simples.

Schema obligatorio:
{{
  "recomendaciones": [
    {{
      "categoria": "monetizacion",
      "prioridad": "alta",
      "recomendacion": "acción concreta",
      "justificacion": "justificación con datos reales"
    }}
  ]
}}

Categorías permitidas:
monetizacion, interaccion, contenido, audiencia, horario, tecnica, emocional, disciplina

Prioridades permitidas:
baja, media, alta, critica

Datos del creador:
{contexto_para_prompt(contexto)}
"""


def prompt_recomendaciones_externo_desde_json(
    contexto: Dict[str, Any],
    max_recomendaciones: int = 5,
) -> str:
    return f"""
Actúa como coach senior de creadores TikTok LIVE para una agencia.

Usa SOLO el JSON entregado.
No inventes datos.
No menciones JSON, metadata, tabla, schema, contexto ni base de datos.
Devuelve únicamente JSON válido.

Genera exactamente {max_recomendaciones} recomendaciones para el manager.

Schema obligatorio:
{{
  "recomendaciones": [
    {{
      "categoria": "monetizacion",
      "prioridad": "alta",
      "recomendacion": "acción concreta",
      "justificacion": "justificación con datos reales"
    }}
  ]
}}

Categorías permitidas:
monetizacion, interaccion, contenido, audiencia, horario, tecnica, emocional, disciplina

Prioridades permitidas:
baja, media, alta, critica

Reglas:
- Las métricas dicen qué está pasando.
- El perfil explica por qué pasa y cómo corregirlo.
- Al menos 3 recomendaciones deben mencionar números reales.
- Al menos 3 recomendaciones deben usar señales concretas del perfil.
- Monetización debe usar meta mensual, diamantes del periodo, partidas o diamantes de partidas.
- Audiencia debe usar nuevos seguidores o meta de nuevos seguidores.
- Horario o disciplina debe usar días válidos, emisiones, duración o metas.
- No uses la meta de categoría como meta principal si existe meta mensual.
- Si existe metas.meta_diamantes, esa es la meta operativa principal.
- La categoría Bronce y su meta de 5000 diamantes son solo referencia de nivel.
- No digas "alcanzar Bronce" si el creador ya supera esa cifra.
- Si diamantes de partidas supera diamantes del mes, úsalo solo como señal de relevancia de partidas, no como porcentaje normal.
- Si ya hay alto volumen de emisiones, días o duración, no recomiendes simplemente transmitir más.
- Interacción debe usar chat, fluidez, multitarea o batallas si aparecen.
- Técnica debe usar iluminación, equipo, herramientas, setup o calidad técnica si aparecen.
- Contenido debe convertir intereses en dinámicas concretas.
- Emocional debe usar energía, ritmo, constancia o feedback si aparecen.
- Disciplina debe proponer rutina concreta de revisión o preparación.

JSON:
{contexto_para_prompt(contexto)}
"""


def texto_copiable_prompt_externo_recomendaciones(prompt: str) -> str:
    """Texto único listo para pegar en IA externa (instrucciones + schema + JSON)."""
    return (prompt or "").strip()


def texto_copiable_prompt_externo_recomendaciones(prompt: str) -> str:
    """Texto único listo para pegar en IA externa (instrucciones + schema + JSON)."""
    return (prompt or "").strip()

