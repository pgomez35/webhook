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
- emocional: energía, ritmo y celebración de avances. NO repitas horario ni cantidad de lives si ya hay tarjeta de horario.
- disciplina: rutina mínima y preparación. NO repitas horario si ya hay tarjeta de horario.
- contenido: parrilla en formato Live 1 / Live 2 / Live 3 con un interés por live. Sin horario ni partidas.
- interacción: equipos, preguntas rápidas, ranking simbólico o reconocimiento por nombre. Sin repetir los 3 intereses enteros.
- monetización: metas por tramos, regalos pequeños, batalla o diamantes. Un solo interés como gancho si aplica.
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


def _extraer_datos_personalizacion_recomendaciones(contexto: Dict[str, Any]) -> Dict[str, Any]:
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
                f"partidas: {_v(d.get('texto_partidas_manager'))} | interés gancho: "
                f"{intereses[0] if intereses else 'sin dato'}"
            ),
            "- interaccion:",
            (
                f"  arquetipo: {_v(d.get('arquetipo'))} | equipos, ranking, preguntas, reconocimiento | "
                f"dinámicas: {_v((d.get('arquetipo_interaccion') or [])[:2])}"
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
            f"  energía, confianza, reto semanal (3 lives) | no saturar a {_v(d.get('nombre_creador'))}",
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


def _justificacion_monetizacion_natural(justificacion: str) -> str:
    texto = (justificacion or "").strip()
    if not texto or "tramos pequeños" in texto.lower():
        return texto

    match_meta = re.search(r"(?i)meta\s+(\d[\d.,]*)\s+diamantes", texto)
    match_cat = re.search(r"(?i)categor[ií]a\s+([^,;.]+)", texto)
    if match_meta:
        meta_n = match_meta.group(1).replace(",", "")
        cat_n = match_cat.group(1).strip() if match_cat else "asignada"
        return (
            f"La meta {cat_n} de {meta_n} diamantes necesita tramos pequeños para que "
            "la audiencia sienta avance y participe con más facilidad."
        )
    if "priorizar conversión" in texto.lower() or "regalos por tramo" in texto.lower():
        return (
            "Los tramos pequeños de regalos ayudan a que la audiencia sienta avance "
            "y participe con más facilidad."
        )
    return texto


def _justificacion_interaccion_natural(justificacion: str, recomendacion: str) -> str:
    texto = (justificacion or "").strip()
    if texto and "reto, competencia y reconocimiento" in texto.lower():
        return texto

    match = re.search(r"(?i)como\s+([^,]+),", texto or recomendacion or "")
    arquetipo = match.group(1).strip() if match else "Batallista"
    return (
        f"Como {arquetipo}, la interacción debe sentirse como reto, "
        "competencia y reconocimiento público."
    )


def _pulir_recomendacion_por_categoria(
    rec: Dict[str, Any],
    *,
    hay_tarjeta_horario: bool = False,
) -> Dict[str, Any]:
    if not isinstance(rec, dict):
        return rec

    cat = _normalizar_categoria_recomendacion(rec.get("categoria") or "otro")
    recomendacion = str(rec.get("recomendacion") or "").strip()
    justificacion = str(rec.get("justificacion") or recomendacion).strip()

    if cat == "interaccion":
        recomendacion = _quitar_oraciones_interaccion_redundantes(recomendacion)
        justificacion = _justificacion_interaccion_natural(justificacion, recomendacion)

    elif cat == "contenido":
        just_l = justificacion.lower()
        if (
            "convertir convertir" in just_l
            or "con convertir" in just_l
            or "por live" in just_l
            or "desde convertir" in just_l
            or len(justificacion) > 200
        ):
            justificacion = _justificacion_contenido_natural(justificacion)

    elif cat == "monetizacion":
        justificacion = _justificacion_monetizacion_natural(justificacion)

    elif cat == "horario":
        if "consistencia horaria" not in justificacion.lower():
            justificacion = (
                "La consistencia horaria ayuda a crear expectativa y retorno de audiencia."
            )

    elif cat == "emocional" and hay_tarjeta_horario:
        recomendacion = _limpiar_horario_de_texto_emocional_disciplina(
            recomendacion,
            "",
        )
        if "sostener energía" not in justificacion.lower():
            justificacion = "Prioridad: sostener energía y ritmo sin saturar al creador."

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


def _pulir_recomendacion_item(
    rec: Dict[str, Any],
    *,
    hay_tarjeta_horario: bool = False,
) -> Dict[str, Any]:
    if not isinstance(rec, dict):
        return rec
    salida = dict(rec)
    salida["recomendacion"] = _pulir_texto_recomendacion_final(rec.get("recomendacion"))
    salida["justificacion"] = _pulir_texto_recomendacion_final(
        rec.get("justificacion") or rec.get("recomendacion")
    )
    return _pulir_recomendacion_por_categoria(salida, hay_tarjeta_horario=hay_tarjeta_horario)


def _aplicar_pulido_final_recomendaciones(resultado: Any) -> Dict[str, Any]:
    salida: Dict[str, Any] = resultado if isinstance(resultado, dict) else {}
    recs = salida.get("recomendaciones")
    if isinstance(recs, list):
        hay_tarjeta_horario = any(
            _normalizar_categoria_recomendacion(r.get("categoria") or "") == "horario"
            for r in recs
            if isinstance(r, dict)
        )
        salida["recomendaciones"] = [
            _pulir_recomendacion_item(r, hay_tarjeta_horario=hay_tarjeta_horario)
            for r in recs
            if isinstance(r, dict)
        ]
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
    reporte = contexto.get("ultimo_reporte") or {}
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
    nombre = ctx["nombre"]
    i1 = _interes_tarjeta(ctx, 0)
    cat_nombre = str(ctx.get("categoria_nombre") or "la categoría").strip()
    meta = ctx.get("meta_diamantes")
    gancho = f"usando {i1} como mini reto" if i1 else "con mini retos visibles"

    rec = (
        f"Establecer metas pequeñas de regalos por tramo {gancho}: "
        "apertura para activar el primer reto, entre batallas para desbloquear "
        "30 segundos de energía y cierre para elegir el reto del próximo LIVE."
    )
    if meta not in (None, ""):
        try:
            meta_n = int(float(meta))
            just = (
                f"La meta {cat_nombre} de {meta_n} diamantes necesita tramos pequeños para que "
                "la audiencia sienta avance y participe con más facilidad."
            )
        except Exception:
            just = (
                "Los tramos pequeños de regalos ayudan a que la audiencia sienta avance "
                "y participe con más facilidad."
            )
    else:
        just = (
            "La meta mensual necesita tramos pequeños para que la audiencia sienta avance "
            "y participe con más facilidad."
        )
    return {"recomendacion": rec.strip(), "justificacion": just}


def _tarjeta_recomendacion_interaccion(ctx: _TarjetaRecomendacionCtx) -> Dict[str, str]:
    nombre = ctx["nombre"]
    arquetipo = ctx.get("arquetipo") or "Batallista"
    rec = (
        f"Para {nombre}: dinámica {arquetipo} con 2 equipos, pregunta rápida antes de cada batalla "
        "y ranking simbólico en pantalla. Reconocer en vivo al top 3 que comenta o apoya en cada ronda."
    )
    just = _resumen_arquetipo_para_categoria(
        ctx.get("arquetipo_estrategia"), nombre, "interaccion"
    )
    if not just or "activar participación" in just.lower():
        just = (
            f"Como {arquetipo}, la interacción debe sentirse como reto, "
            "competencia y reconocimiento público."
        )
    return {
        "recomendacion": rec.strip(),
        "justificacion": just,
    }


def _tarjeta_recomendacion_contenido(ctx: _TarjetaRecomendacionCtx) -> Dict[str, str]:
    nombre = ctx["nombre"]
    i1, i2, i3 = _interes_tarjeta(ctx, 0), _interes_tarjeta(ctx, 1), _interes_tarjeta(ctx, 2)
    temas = [t for t in (i1, i2, i3 if i3 else i1) if t]

    arquetipo = ctx.get("arquetipo") or "su arquetipo"

    if len(temas) >= 3:
        parrilla = (
            f"Live 1 — {temas[0]} con batalla o reto corto. "
            f"Live 2 — {temas[1]} con energía entre partidas. "
            f"Live 3 — {temas[2]} con cierre y gancho al próximo LIVE."
        )
    elif len(temas) == 2:
        parrilla = (
            f"Live A — {temas[0]}; Live B — {temas[1]}; repetir el formato que mejor retenga."
        )
    elif len(temas) == 1:
        parrilla = f"Tres lives con variaciones de {temas[0]} (apertura, batalla, cierre)."
    else:
        parrilla = "Tres lives con un formato distinto cada día (apertura, batalla, cierre)."

    rec = (
        f"Para {nombre}: mini parrilla semanal. {parrilla} "
        "Preparar guion de 5 minutos antes de entrar."
    )
    just = (
        f"Como {arquetipo}, la parrilla debe convertir sus intereses en retos visibles "
        "desde el inicio del LIVE."
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
    nombre = ctx["nombre"]
    return {
        "recomendacion": (
            f"Para {nombre}: reto semanal — 3 lives; celebrar cumplimiento (3/3) "
            "antes de subir exigencia de metas."
        ),
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
    ctx = _tarjeta_ctx_desde_contexto(contexto)
    categoria_norm = _normalizar_categoria_recomendacion(categoria)
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

        rec_pulida = _pulir_recomendacion_item({
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

        debe_usar_fallback = (
            _es_texto_recomendacion_generico(texto_rec)
            or _es_texto_recomendacion_generico(texto_just)
            or not _cumple_personalizacion_minima_recomendacion(
                texto_union, datos, categoria
            )
            or (
                categoria in _CATEGORIAS_RECOMENDACION_CON_DINAMICAS
                and not _cumple_dinamicas_intereses_minimas(
                    texto_union, datos, categoria
                )
            )
            or any(p in texto_union.lower() for p in _TERMINOS_TECNICOS_PROHIBIDOS_MANAGER)
            or len(texto_rec) > 480
            or len(texto_just) > 280
        )

        if debe_usar_fallback:
            rec_normalizada = _construir_recomendacion_personalizada_fallback(
                contexto, categoria, str(prioridad)
            )
        else:
            rec_normalizada = _pulir_recomendacion_item({
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
    return _aplicar_pulido_final_recomendaciones(salida)

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
      "recomendacion": "Para Luna: reto semanal — 3 lives; celebrar cumplimiento 3/3 antes de subir exigencia de metas.",
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
      "recomendacion": "Para Luna: mini parrilla semanal. Live 1 — Baile con reto corto. Live 2 — Moda con votación de outfit. Live 3 — Humor con cierre y gancho al próximo LIVE. Preparar guion de 5 minutos antes de entrar.",
      "justificacion": "Como creadora de entretenimiento, la parrilla debe convertir sus intereses en momentos visibles desde el inicio del LIVE."
    },
    {
      "categoria": "interaccion",
      "prioridad": "alta",
      "recomendacion": "Para Luna: dinámica competitiva con 2 equipos, pregunta rápida antes de cada reto y ranking simbólico en pantalla. Reconocer en vivo al top 3 que comenta o apoya en cada ronda.",
      "justificacion": "La interacción debe sentirse como juego, competencia y reconocimiento público."
    },
    {
      "categoria": "monetizacion",
      "prioridad": "alta",
      "recomendacion": "Establecer metas pequeñas de regalos por tramo usando Baile como mini reto: apertura para activar el primer reto, mitad del LIVE para desbloquear una ronda extra y cierre para elegir el reto del próximo LIVE.",
      "justificacion": "La meta Bronce de 5000 diamantes necesita tramos pequeños para que la audiencia sienta avance y participe con más facilidad."
    }
  ]
}
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

