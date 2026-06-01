# from DataBase import *
import json

from openai import OpenAI
from dotenv import load_dotenv
import os

# Cargar variables de entorno
from DataBase import obtener_datos_mejoras_aspirantes_perfil, obtener_datos_estadisticas_aspirantes_perfil, \
    get_connection_context

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

def get_label(campo, valor):
    try:
        return SLIDER_LABELS[campo][int(valor)]
    except Exception:
        return "No informado"


def to_num(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0

def diagnostico_aspirantes_perfil(
    aspirante_id: int,
    puntajes_calculados: dict = None
) -> str:
    """
    Diagnóstico integral del perfil del creador, con puntajes, labels y unidades correctas.
    Si se pasan puntajes_calculados, se usan para la sección final de categorías y puntajes.
    """
    datos = obtener_datos_mejoras_aspirantes_perfil(aspirante_id)

    # Obtén los puntajes y categorías, usando puntajes_calculados si está disponible
    puntajes = {
        "Calificación total": (
            (puntajes_calculados or datos).get("puntaje_total"),
            (puntajes_calculados or datos).get("puntaje_total_categoria"),
        ),
        "Calificación Estadísticas": (
            (puntajes_calculados or datos).get("puntaje_estadistica"),
            (puntajes_calculados or datos).get("puntaje_estadistica_categoria"),
        ),
        "Calificación Cualitativo": (
            (puntajes_calculados or datos).get("puntaje_cualitativo"),
            (puntajes_calculados or datos).get("puntaje_cualitativo_categoria"),
        ),
        "Calificación Datos personales": (
            (puntajes_calculados or datos).get("puntaje_general"),
            (puntajes_calculados or datos).get("puntaje_general_categoria"),
        ),
        "Calificación Hábitos y preferencias": (
            (puntajes_calculados or datos).get("puntaje_habitos"),
            (puntajes_calculados or datos).get("puntaje_habitos_categoria"),
        ),
    }

    advertencias = []
    diagnostico = {
        "🧑‍🎓 Datos personales y generales": [],
        "📊 Estadísticas": [],
        "💡 Evaluación cualitativa": [],
        "📅 Preferencias y hábitos": [],
    }

    # Datos personales y generales
    idioma = datos.get("idioma", "No especificado")
    estudios = datos.get("estudios", "No especificado")
    actividad = datos.get("actividad_actual", "No especificado")
    edad = datos.get("edad", "")
    genero = datos.get("genero", "No especificado")
    pais = datos.get("pais", "No especificado")

    diagnostico["🧑‍🎓 Datos personales y generales"].append(f"🎂 Edad: {edad if edad else 'No informado'}")
    diagnostico["🧑‍🎓 Datos personales y generales"].append(f"🌐 Idioma: {idioma}")
    diagnostico["🧑‍🎓 Datos personales y generales"].append(f"👤 Género: {genero}")
    diagnostico["🧑‍🎓 Datos personales y generales"].append(f"🌎 País: {pais}")
    diagnostico["🧑‍🎓 Datos personales y generales"].append(
        f"🎓 Estudios: {(estudios.replace('_', ' ') if estudios else 'No informado')}"
    )
    diagnostico["🧑‍🎓 Datos personales y generales"].append(f"💼 Actividad actual: {actividad}")

    if idioma and idioma.lower() != "español":
        advertencias.append("🌍 Puede aprovechar público bilingüe.")
    if actividad and "estudiante" in actividad.lower():
        advertencias.append("📘 Puede aprovechar su etapa de formación para contenido educativo.")

    # Estadísticas
    seguidores = datos.get("seguidores")
    siguiendo = datos.get("siguiendo")
    likes = datos.get("likes")
    videos = datos.get("videos")
    duracion = datos.get("duracion_emisiones")

    diagnostico["📊 Estadísticas"].append(f"👥 Seguidores: {seguidores if seguidores is not None else 'No informado'}")
    diagnostico["📊 Estadísticas"].append(f"➡️ Siguiendo: {siguiendo if siguiendo is not None else 'No informado'}")
    diagnostico["📊 Estadísticas"].append(f"👍 Likes: {likes if likes is not None else 'No informado'}")
    diagnostico["📊 Estadísticas"].append(f"🎥 Videos: {videos if videos is not None else 'No informado'}")
    diagnostico["📊 Estadísticas"].append(f"⏳ Días activo: {duracion if duracion is not None else 'No informado'}")

    if seguidores is not None and seguidores < 100:
        advertencias.append("⚠️ Nivel bajo de seguidores.")
    if likes is not None and likes < 200:
        advertencias.append("⚠️ Poca interacción (likes bajos).")
    if videos is not None and videos < 5:
        advertencias.append("⚠️ Falta constancia en publicaciones.")

    # Evaluación cualitativa
    apariencia = datos.get("apariencia")
    engagement = datos.get("engagement")
    calidad = datos.get("calidad_contenido")
    eval_foto = datos.get("eval_foto")
    eval_bio = datos.get("eval_biografia")

    diagnostico["💡 Evaluación cualitativa"].append(
        f"🧑‍🎤 Apariencia en cámara: {get_label('apariencia', apariencia)}"
    )
    diagnostico["💡 Evaluación cualitativa"].append(
        f"🤝 Engagement: {get_label('engagement', engagement)}"
    )
    diagnostico["💡 Evaluación cualitativa"].append(
        f"🎬 Calidad del contenido: {get_label('calidad_contenido', calidad)}"
    )
    diagnostico["💡 Evaluación cualitativa"].append(
        f"🖼️ Foto de perfil: {get_label('eval_foto', eval_foto)}"
    )
    diagnostico["💡 Evaluación cualitativa"].append(
        f"📖 Biografía: {get_label('eval_biografia', eval_bio)}"
    )

    if engagement is not None and engagement <= 2:
        advertencias.append("⚠️ Necesita mayor interacción con la audiencia.")
    if calidad is not None and calidad <= 2:
        advertencias.append("⚠️ Contenido de baja calidad percibida.")

    # Preferencias y hábitos (corregido con or {})
    tiempo = datos.get("tiempo_disponible", "No definido")
    frecuencia = datos.get("frecuencia_lives", "No definido")
    experiencia = datos.get("experiencia_otras_plataformas") or {}
    intereses = datos.get("intereses") or {}
    tipo_contenido = datos.get("tipo_contenido") or {}
    intencion = datos.get("intencion_trabajo", "No definido")

    experiencia_fmt = []
    for plataforma, valor in experiencia.items():
        if not valor or valor == 0:
            continue
        sufijo = "año" if valor == 1 else "años"
        experiencia_fmt.append(f"{plataforma}: {valor} {sufijo}")
    experiencia_str = ", ".join(experiencia_fmt) if experiencia_fmt else "Sin experiencia"

    intereses_fmt = [k for k, v in intereses.items() if v] if isinstance(intereses, dict) else intereses
    intereses_str = ", ".join(intereses_fmt) if intereses_fmt else "No definidos"

    tipo_fmt = [k for k, v in tipo_contenido.items() if v] if isinstance(tipo_contenido, dict) else tipo_contenido
    tipo_str = ", ".join(tipo_fmt) if tipo_fmt else "No definido"

    diagnostico["📅 Preferencias y hábitos"].append(
        f"⌛ Tiempo disponible: {tiempo} horas por semana" if tiempo not in [None, "", "No definido"] else "⌛ Tiempo disponible: No definido"
    )
    diagnostico["📅 Preferencias y hábitos"].append(
        f"📡 Frecuencia de lives: {frecuencia} veces por semana" if frecuencia not in [None, "", "No definido"] else "📡 Frecuencia de lives: No definido"
    )
    diagnostico["📅 Preferencias y hábitos"].append(f"🌍 Experiencia en otras plataformas: {experiencia_str}")
    diagnostico["📅 Preferencias y hábitos"].append(f"🎯 Intereses: {intereses_str}")
    diagnostico["📅 Preferencias y hábitos"].append(f"🎨 Tipo de contenido: {tipo_str}")
    diagnostico["📅 Preferencias y hábitos"].append(f"💼 Intención de trabajo: {intencion}")

    if (isinstance(frecuencia, str) and frecuencia.lower() == "baja") or (isinstance(tiempo, str) and tiempo.lower() == "limitado"):
        advertencias.append("⚠️ Tiempo de dedicación limitado.")
    if isinstance(intencion, str) and intencion.lower() in ["hobbie", "ocasional"]:
        advertencias.append("ℹ️ Perfil más recreativo que profesional.")

    # Análisis de categorías bajas
    categoria_baja = []
    for nombre, (_, categoria) in puntajes.items():
        if categoria is not None and categoria.lower() in ['bajo', 'medio']:
            categoria_baja.append((nombre, categoria))
    if categoria_baja:
        advertencias.append("🔎 Análisis de categorías con oportunidad de mejora:")
        for nombre, categoria in categoria_baja:
            advertencias.append(f"→ {nombre}: {categoria.capitalize()} (Conviene enfocarse en este aspecto para subir de nivel).")

    # Formatear salida
    mensaje = ["# 📋 DIAGNÓSTICO DEL PERFIL\n"]
    mensaje.append("## 🧑‍🎓 Datos personales y generales")
    for item in diagnostico["🧑‍🎓 Datos personales y generales"]:
        mensaje.append(f"- {item}")
    mensaje.append("")

    mensaje.append("## 📊 Estadísticas")
    for item in diagnostico["📊 Estadísticas"]:
        mensaje.append(f"- {item}")
    mensaje.append("")

    mensaje.append("## 💡 Evaluación cualitativa")
    for item in diagnostico["💡 Evaluación cualitativa"]:
        mensaje.append(f"- {item}")
    mensaje.append("")

    mensaje.append("## 📅 Preferencias y hábitos")
    for item in diagnostico["📅 Preferencias y hábitos"]:
        mensaje.append(f"- {item}")
    mensaje.append("")

    mensaje.append("# 🏅 Categorías y puntajes del Perfil")
    for nombre, (_, categoria) in puntajes.items():
        mensaje.append(f"- {nombre}: {categoria if categoria is not None else 'Sin categoría'}")

    return "\n".join(mensaje)

def evaluar_estadisticas(seguidores, siguiendo, videos, likes, duracion):
    seguidores = to_num(seguidores) if seguidores is not None else None
    siguiendo = to_num(siguiendo) if siguiendo is not None else None
    videos = to_num(videos) if videos is not None else None
    likes = to_num(likes) if likes is not None else None
    duracion = to_num(duracion) if duracion is not None else None

    # Corte duro: si tiene muy pocos seguidores, no cuenta
    if seguidores is None or seguidores < 50:
        return {
            "puntaje_estadistica": 0.0,
            "puntaje_estadistica_categoria": "No aplicable"
        }

    # Evitar división por cero
    if seguidores > 0 and videos and videos > 0:
        likesNormalizado = likes / (seguidores * videos)
    elif seguidores > 0:
        likesNormalizado = likes / seguidores
    else:
        likesNormalizado = 0

    # Seguidores
    if seguidores is None or seguidores <= 0:
        seg = 0
    elif seguidores < 50:
        # Menos de 50 → mala calificación
        seg = 1
    elif seguidores <= 500:
        # 50 a 500 → regular
        seg = 2
    elif seguidores <= 1000:
        # 501 a 1000 → aceptable / medio
        seg = 3
    else:
        # Más de 1000 → bueno/alto
        seg = 4

    # Videos
    if videos is None:
        vid = 0
    elif videos < 10:
        vid = 1
    elif videos <= 20:
        vid = 2
    elif videos <= 40:
        vid = 3
    else:
        vid = 4

    # Likes normalizados (engagement relativo)
    if likesNormalizado == 0:
        lik = 0
    elif likesNormalizado < 0.02:   # <2%
        lik = 1
    elif likesNormalizado <= 0.05:  # 2% - 5%
        lik = 2
    elif likesNormalizado <= 0.10:  # 5% - 10%
        lik = 3
    else:                           # >10%
        lik = 4

    # Duración emisiones
    if duracion is None:
        dur = 0
    elif duracion < 20:
        dur = 1
    elif duracion <= 89:
        dur = 2
    elif duracion <= 179:
        dur = 3
    else:
        dur = 4

    # Score ponderado
    score = seg * 0.35 + vid * 0.25 + lik * 0.25 + dur * 0.15
    score = round(score * (5 / 4), 2)  # Normalización a escala 0–5

    # Categoría proporcional
    if score == 0:
        categoria = "No aplicable"
    elif score < 1.5:
        categoria = "Muy bajo"
    elif score < 2.5:
        categoria = "Bajo"
    elif score < 3.5:
        categoria = "Aceptable"
    elif score < 4.5:
        categoria = "Bueno"
    else:
        categoria = "Excelente"

    return {
        "puntaje_estadistica": score,
        "puntaje_estadistica_categoria": categoria
    }

def evaluar_cualitativa(
    apariencia: float = 0,
    engagement: float = 0,
    calidad_contenido: float = 0,
    foto: float = 0,
    biografia: float = 0,
    metadata_videos: float = 0
):
    # Pesos base
    pesos_base = {
        "apariencia": 0.33,
        "engagement": 0.32,
        "calidad_contenido": 0.2,
        "foto": 0.05,
        "biografia": 0.05,
        "metadata_videos": 0.05,
    }

    score = (
        (apariencia or 0) * pesos_base["apariencia"] +
        (engagement or 0) * pesos_base["engagement"] +
        (calidad_contenido or 0) * pesos_base["calidad_contenido"] +
        (foto or 0) * pesos_base["foto"] +
        (biografia or 0) * pesos_base["biografia"] +
        (metadata_videos or 0) * pesos_base["metadata_videos"]
    )

    score = round(score, 2)

    # Categorías según rangos
    if score < 2:
        categoria = "Muy bajo"
    elif score < 3:
        categoria = "Bajo"
    elif score < 4:
        categoria = "Medio"
    elif score < 4.5:
        categoria = "Bueno"
    else:
        categoria = "Excelente"

    return {
        "puntaje_cualitativo": score,
        "puntaje_cualitativo_categoria": categoria
    }

SLIDER_LABELS = {
    'apariencia': {
        1: "No destaca - poco llamativa",
        2: "Básico - Imagen neutra, sin impacto pero correcta",
        3: "Buena presencia — Estilo acorde, genera interés visual",
        4: "Agradable - buena presencia y tiene estilo propio",
        5: "Muy atractivo - Imagen profesional y sobresaliente"
    },
    'engagement': {
        1: "No conecta - sin emoción; no genera empatía ni interacción",
        2: "Limitado - poca interacción, le falta chispa",
        3: "Interesante - a veces atrapa",
        4: "Carismático - expresivo y cautiva con naturalidad",
        5: "Altamente carismático — Captura la atención de todos"
    },
    'calidad_contenido': {
        1: "Vacío — Solo bailes, lipsyncs o videos de terceros",
        2: "Básico — Intenta transmitir algo, pero poca creatividad",
        3: "Valioso — Entretenido, muestra creatividad o información útil",
        4: "Original — Innovador y bien producido",
        5: "Sobresaliente — Profesional, creativo y con gran impacto"
    },
    'eval_biografia': {
        1: 'No tiene Biografía',
        2: 'Deficiente (confusa, larga o sin propósito).',
        3: 'Aceptable (se entiende pero poco identidad).',
        4: 'Buena (clara, corta, con identidad).',
        5: 'Excelente (muy corta, clara y coherente).'
    },
    'eval_foto': {
        1: 'Sin foto propia - Avatar genérico o ausente ',
        2: 'Foto genérica, poco clara, de baja calidad o en grupo',
        3: 'Foto aceptable pero mejorable',
        4: 'Buena foto personal, adecuada',
        5: 'Foto excelente, muy profesional y atractiva'
    },
    'metadata_videos': {
        1: 'Muy malos – incoherentes, no describen',
        2: 'Deficientes – poco claros',
        3: 'Aceptables – comprensibles pero poco atractivos',
        4: 'Buenos – claros y alineados',
        5: 'Excelentes – muy claros, breves y llamativos'
    }
}

def evaluar_datos_generales(edad, genero, idiomas, estudios, pais=None, actividad_actual=None):
    # ==== Edad (Rango 1-5) ====
    # 1: Menos de 18 años
    # 2: 18 - 24 años
    # 3: 25 - 34 años
    # 4: 35 - 45 años
    # 5: Más de 45 años

    if edad is None:
        e = 0
    elif edad == 1:
        # Menores de 18: no apto
        return {
            "puntaje_general": 0,
            "puntaje_general_categoria": "No apto"
        }
    elif edad == 2:
        e = 2
    elif edad == 3 or edad == 4:
        e = 3
    elif edad == 5:
        e = 1
    else:
        e = 0

    # ==== Género ====
    genero_map = {
        "femenino": 3,
        "masculino": 2,
        "otro": 2,
        "prefiero no decir": 1
    }
    g = genero_map.get(str(genero).lower(), 0)

    # ==== Idiomas ====
    if not idiomas:
        i = 0
    else:
        if isinstance(idiomas, str):
            idiomas_list = [x.strip().lower() for x in idiomas.split(",")]
        elif isinstance(idiomas, list):
            idiomas_list = [str(x).lower().strip() for x in idiomas]
        else:
            idiomas_list = []

        if len(idiomas_list) == 1 and "espanol" in idiomas_list:
            i = 1
        elif len(idiomas_list) > 1:
            i = 3
        else:
            i = 2

    # ==== Estudios ====
    estudios_map = {
        "ninguno": 0,
        "primaria": 1,
        "secundaria": 2,
        "tecnico": 2,
        "universitario_incompleto": 2,
        "universitario": 3,
        "postgrado": 3,
        "autodidacta": 2,
        "otro": 1
    }
    est = estudios_map.get(str(estudios).lower(), 0)

    # ==== Actividad actual ====
    actividad_map = {
        "estudiante_tiempo_completo": 2,
        "estudiante_tiempo_parcial": 1.5,
        "trabajo_tiempo_completo": 2.5,
        "trabajo_medio_tiempo": 2,
        "buscando_empleo": 1.5,
        "emprendiendo": 3,
        "disponible_total": 3,
        "otro": 1
    }
    act = actividad_map.get(str(actividad_actual).lower(), 0) if actividad_actual else 0

    # ==== Bonus por país estratégico ====
    pais_bonus = ["mexico", "colombia", "argentina"]
    bonus = 0.2 if pais and str(pais).lower() in pais_bonus else 0

    # ==== Cálculo ponderado ====
    score = (e * 0.20 +
             g * 0.20 +
             i * 0.20 +
             est * 0.20 +
             act * 0.20 +
             bonus)

    score_final = round(score * (5/3), 2)

    # ==== Categorías por puntaje ====
    if score_final == 0:
        categoria = "No apto"
    elif score_final < 1.5:
        categoria = "Muy bajo"
    elif score_final < 2.5:
        categoria = "Bajo"
    elif score_final < 3.5:
        categoria = "Medio"
    elif score_final < 4.5:
        categoria = "Alto"
    else:
        categoria = "Excelente"

    return {
        "puntaje_general": score_final,
        "puntaje_general_categoria": categoria
    }

def _metrica_opcional_numerica(val):
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def evaluar_preferencias_habitos(
    exp_otras: dict,
    intereses: dict,
    tipo_contenido: dict,
    tiempo=None,
    freq_lives=None,
    intencion=None
):
    tiempo = _metrica_opcional_numerica(tiempo)
    freq_lives = _metrica_opcional_numerica(freq_lives)

    # ==============================
    # 1. Experiencia en otras plataformas
    # ==============================
    total_exp = sum(exp_otras.values())
    if total_exp == 0:
        exp = 0
    elif total_exp <= 2:
        exp = 1
    elif total_exp <= 5:
        exp = 2
    else:
        exp = 3

    # ==============================
    # 2. Intereses
    # ==============================

    categorias = {
        "deportes": "deportes",
        "moda": "estilo",
        "maquillaje": "estilo",
        "cocina": "gastronomia",
        "fitness": "salud",
        "música": "estilo",
        "bailes": "estilo",
        "gaming": "gaming",
        "lectura": "educacion",
        "salud mental": "salud",
        "comedia": "estilo",
        "religión": "opinion",
        "política": "opinion",
        "emprendimiento": "negocios",
        "viajes": "estilo",
        "idiomas": "educacion",
        "educación": "educacion",
        "noticias": "opinion",
        "relaciones": "opinion"
    }

    seleccionados = [cat for k, v in intereses.items() if v and k in categorias for cat in [categorias[k]]]
    if not seleccionados:
        inte =  0

    categorias_distintas = len(set(seleccionados))
    if categorias_distintas == 1:
        inte =  3  # muy relacionados
    elif categorias_distintas == 2:
        inte =  2  # medianamente relacionados
    else:
        inte =  1  # nada relacionados



    # ==============================
    # 3. Tipo de contenido
    # ==============================
    bonus_contenido = 0
    cont = 1  # default

    if isinstance(tipo_contenido, dict):
        activos = [k for k, v in tipo_contenido.items() if v]

        # Caso especial: ventas en vivo → calificación 0
        if "ventas en vivo" in activos:
            cont = 0
            bonus_contenido = 0

        # Contenido fuerte en plataformas
        elif any(cat in activos for cat in ["bailes", "humor", "gaming", "música en vivo","charlas","religión y espiritualidad","entretenimiento general"]):
            cont = 3

        # Contenido educativo o de valor
        elif any(cat in activos for cat in ["tutoriales", "temas sociales","estudios / tareas","reacción a videos"]):
            cont = 2

        # Nicho u otro → queda en 1

        # Bonus por enfoque / versatilidad
        if cont > 0:  # solo aplica si no es ventas en vivo
            if len(activos) == 1:
                bonus_contenido = 0.2  # enfoque claro
            elif 2 <= len(activos) <= 3:
                bonus_contenido = 0.1  # versátil, pero no disperso
            else:
                bonus_contenido = 0

    # ==============================
    # 4. Tiempo disponible (opcional)
    # ==============================
    if tiempo is None:
        t = 0
    elif tiempo < 12:
        t = 1
    elif tiempo < 21:
        t = 2
    elif tiempo < 36:
        t = 3
    else:
        t = 4


    # ==============================
    # 5. Frecuencia lives (opcional)
    # ==============================
    if freq_lives is None:
        f = 0
    elif freq_lives <= 3:
        f = 1
    elif freq_lives <= 5:
        f = 2
    else:
        f = 3

    # ==============================
    # 6. Intención de trabajo (opcional)
    # ==============================
    it = {
        "trabajo principal": 3,
        "trabajo secundario": 2,
        "hobby, pero me gustaría profesionalizarlo": 2,
        "diversión, sin intención profesional": 1,
        "no estoy seguro": 0
    }.get(str(intencion).strip().lower(), 0)

    # ==============================
    # Score final
    # ==============================
    score = (
        exp * 0.25 +
        inte * 0.20 +
        cont * 0.25 +
        t * 0.10*(3/4) +
        f * 0.10 +
        it * 0.10
    )

    score = round(score * (5 / 3), 2)  # normalización a 0–5

    # ==============================
    # Categoría proporcional
    # ==============================
    if score == 0:
        categoria = "No aplicable"
    elif score < 1.5:
        categoria = "Muy bajo"
    elif score < 2.5:
        categoria = "Bajo"
    elif score < 3.5:
        categoria = "Aceptable"
    elif score < 4.5:
        categoria = "Bueno"
    else:
        categoria = "Excelente"

    return {
        "puntaje_habitos": score,
        "puntaje_habitos_categoria": categoria
    }

def generar_mejoras_sugeridas_total(aspirante_id: int) -> str:
    def to_num(val):
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0

    datos = obtener_datos_mejoras_aspirantes_perfil(aspirante_id)
    sugerencias = {
        "🚀 Recomendaciones generales": [],
        "💡 Mejora tu contenido": [],
        "📊 Mejora tus estadísticas": [],
        "👤 Perfil personal": [],
        "🔄 Hábitos y preferencias": [],
        "⚠️ Oportunidades y riesgos": []
    }

    # 1. Evaluación cualitativa con feedback label
    sugerencias_cualitativas = mejoras_sugeridas_cualitativa(
        apariencia=to_num(datos.get("apariencia", 0)),
        engagement=to_num(datos.get("engagement", 0)),
        calidad_contenido=to_num(datos.get("calidad_contenido", 0)),
        eval_foto=to_num(datos.get("eval_foto", 0)),
        eval_biografia=to_num(datos.get("eval_biografia", 0)),
        metadata_videos=to_num(datos.get("metadata_videos", 0)),
        biografia_sugerida=datos.get("biografia_sugerida", "")
    )
    if sugerencias_cualitativas:
        sugerencias["💡 Mejora tu contenido"].extend(sugerencias_cualitativas)

    # 2. Evaluación estadística con oportunidades/riesgos
    sugerencias_estadisticas = mejoras_sugeridas_estadisticas(
        seguidores=to_num(datos.get("seguidores", 0)),
        siguiendo=to_num(datos.get("siguiendo", 0)),
        likes=to_num(datos.get("likes", 0)),
        videos=to_num(datos.get("videos", 0)),
        duracion=to_num(datos.get("duracion_emisiones", 0))
    )
    if sugerencias_estadisticas:
        sugerencias["📊 Mejora tus estadísticas"].extend(sugerencias_estadisticas)

    # 3. Evaluación datos generales (con oportunidades y mejoras personalizadas)
    sugerencias_generales = mejoras_sugeridas_datos_generales(
        edad=datos.get("edad"),
        genero=datos.get("genero"),
        idiomas=datos.get("idioma"),
        estudios=datos.get("estudios"),
        pais=datos.get("pais"),
        actividad_actual=datos.get("actividad_actual")
    )
    if sugerencias_generales:
        sugerencias["👤 Perfil personal"].append(sugerencias_generales)

    # 4. Evaluación hábitos y preferencias
    mejoras_sugeridas_habitos = mejoras_sugeridas_preferencias_habitos(
        exp_otras=datos.get("experiencia_otras_plataformas") or {},
        intereses=datos.get("intereses") or {},
        tipo_contenido=datos.get("tipo_contenido") or {},
        tiempo=datos.get("tiempo_disponible"),
        freq_lives=datos.get("frecuencia_lives"),
        intencion=datos.get("intencion_trabajo"),
        horario_preferido=datos.get("horario_preferido")
    )
    if mejoras_sugeridas_habitos:
        sugerencias["🔄 Hábitos y preferencias"].extend(mejoras_sugeridas_habitos)

    # 5. Recomendaciones generales extra
    if to_num(datos.get("engagement", 0)) < 3 and to_num(datos.get("seguidores", 0)) < 300:
        sugerencias["🚀 Recomendaciones generales"].append(
            "🔄 Mejora tu interacción y combina con estrategias de crecimiento.")
    if to_num(datos.get("calidad_contenido", 0)) >= 4 and to_num(datos.get("seguidores", 0)) < 300:
        sugerencias["🚀 Recomendaciones generales"].append("✅ Tu contenido es bueno, ahora enfócate en difundirlo más.")

    # 6. Limpieza final y salida
    sugerencias = {k: v for k, v in sugerencias.items() if v}
    if sugerencias:
        sugerencias["✨ Mensaje final"] = [
            "🌟 En TikTok, el talento y la disciplina son la clave para crecer.",
            "Cuando te comprometes y te esfuerzas, tu potencial no tiene límites. ¡Atrévete a llegar más lejos!"
        ]

    mensaje = []
    secciones = list(sugerencias.keys())
    for idx, seccion in enumerate(secciones):
        mensaje.append(f"{seccion}")
        for item in sugerencias[seccion]:
            mensaje.append(f"  • {item}")
        # Agrega línea de espacio después de cada sección, excepto la última
        if idx < len(secciones) - 1:
            mensaje.append("")
    return "\n".join(mensaje)


def mejoras_sugeridas_estadisticas(
    seguidores=0,
    siguiendo=0,
    likes=0,
    videos=0,
    duracion=0
):

    sugerencias = []

    seguidores = to_num(seguidores)
    siguiendo = to_num(siguiendo)
    likes = to_num(likes)
    videos = to_num(videos)
    duracion = to_num(duracion)

    sugerencias.append(
        f"📌 Estado actual → Seguidores: {seguidores}, Siguiendo: {siguiendo}, Likes: {likes}, Videos: {videos}, Días activo: {duracion}"
    )

    # Likes normalizados
    if seguidores > 0 and videos > 0:
        likes_normalizado = likes / (seguidores * videos)
    elif seguidores > 0:
        likes_normalizado = likes / seguidores
    else:
        likes_normalizado = 0

    # Seguidores
    if seguidores < 50:
        sugerencias.append("❌ Actualmente no es apto para ingresar a la agencia. El requisito mínimo es superar los 50 seguidores.")
        sugerencias.append("📌 Enfócate primero en superar los 50 seguidores antes de continuar con otros aspectos.")
        sugerencias.append("🔍 Revisa qué tipo de videos generan más interacción y replica los formatos que funcionen mejor.")
        sugerencias.append("🌐 Promociona tu perfil en otras redes sociales o grupos para atraer seguidores iniciales.")
    elif seguidores < 300:
        sugerencias.append("⏫ Prueba nuevas temáticas o formatos para atraer diferentes públicos.")
        sugerencias.append("🎯 Haz colaboraciones con otros aspirantes para aumentar tu alcance.")
    elif seguidores < 1000:
        sugerencias.append("🚀 Aprovecha los retos o tendencias populares para captar más seguidores.")
    else:
        sugerencias.append("✅ El crecimiento de tus seguidores es positivo, mantén la constancia y sigue innovando.")

    # Siguiendo
    if siguiendo >= seguidores or (seguidores > 0 and siguiendo >= (0.9 * seguidores)):
        sugerencias.append(
            "🔄 Prioriza la creación de contenido interesante y útil para tu audiencia, en lugar de enfocarte únicamente en conseguir seguidores por intercambio.")
    elif siguiendo < (0.3 * seguidores):
        sugerencias.append("🤝 Interactúa con otros aspirantes y participa en tendencias para aumentar tu visibilidad.")

    # Likes normalizados (engagement relativo)
    if likes_normalizado == 0:
        sugerencias.append(
            "⚡ Según el número de likes tus videos aún no generan interacción. Enfócate en contenidos que inviten a comentar, compartir y dar 'me gusta'.")
    elif likes_normalizado < 0.02:
        sugerencias.append(
            "📈 Según el número de likes el nivel de interacción es bajo en relación a tus seguidores y videos. Prueba diferentes formatos y fomenta la participación en tus publicaciones.")
    elif likes_normalizado <= 0.05:
        sugerencias.append(
            "🎯 Según el número de likes tienes una interacción moderada. Identifica qué tipos de contenido generan más respuesta y potencia esos temas.")
    elif likes_normalizado <= 0.10:
        sugerencias.append(
            "🔥 Según el número de likes tu nivel de interacción es bueno. Mantén la constancia y busca sorprender para seguir creciendo.")
    else:
        sugerencias.append(
            "✅ Excelente nivel de interacción relativa. Aprovecha tu comunidad activa para lanzar iniciativas, retos o colaboraciones.")

    # Videos
    if videos < 10:
        sugerencias.append("📅 Publica más videos de forma constante (mínimo 10) para mejorar tu presencia.")
    elif videos >= 10 and videos < 30:
        sugerencias.append("🔬 Si aumentas tu ritmo de publicación, tu alcance crecerá exponencialmente.")
    else:
        sugerencias.append("✅ Buen ritmo de publicación, mantén la calidad y genera interacción con tu audiencia.")

    # Días activos
    if duracion < 30:
        sugerencias.append("⏰ Mantente activo para mostrar consistencia y generar hábito en tu audiencia.")
    elif duracion >= 60:
        sugerencias.append("💡 Tu tiempo activo ayuda a consolidar tu audiencia, sigue así.")

    return sugerencias

def mejoras_sugeridas_cualitativa(
    apariencia=0,
    engagement=0,
    calidad_contenido=0,
    eval_foto=0,
    eval_biografia=0,
    metadata_videos=0,
    biografia_sugerida=""
):
    def to_num(val):
        try:
            return int(round(float(val)))
        except (TypeError, ValueError):
            return 0

    RECOMENDACIONES_USUARIO = {
        1: "Tu nombre de usuario incluye números o símbolos poco profesionales. Considera elegir un nombre sencillo, memorable y sin cifras, que represente tu identidad y facilite que otros te recuerden y te encuentren.",
        2: "El nombre de usuario es aceptable pero podría ser más profesional. Si es posible, elimina cifras o símbolos y utiliza tu nombre real o artístico para fortalecer tu marca personal.",
        3: "Tu nombre de usuario es claro y fácil de recordar, aunque puede beneficiarse de pequeños ajustes para hacerlo aún más profesional y representativo.",
        4: "¡Muy bien! Tu nombre de usuario es profesional y refleja tu identidad como creador. Mantén esta coherencia en todas tus plataformas.",
        5: "¡Excelente! Tu nombre de usuario es auténtico, profesional y se asocia fácilmente a tu contenido. Es ideal para construir tu marca."
    }

    RECOMENDACIONES_BIOGRAFIA = {
        1: "Tu biografía está incompleta o no comunica claramente quién eres y qué haces. Redáctala de forma auténtica, específica y orientada al tipo de contenido que realizas. Agrega una descripción personal que refleje tu esencia y motive a otros a seguirte.",
        2: "La biografía es genérica o poco clara. Intenta ser más específico sobre tu perfil y el tipo de contenido que ofreces. Incluye detalles sobre tus intereses y lo que te hace diferente.",
        3: "Biografía correcta, pero puede mejorar en autenticidad y claridad. Incorpora una frase que te defina y que conecte con tu audiencia.",
        4: "¡Muy bien! Tu biografía es clara y coherente con tu contenido. Personalízala regularmente para mantenerla actualizada y relevante.",
        5: "¡Excelente! Biografía auténtica, bien redactada y específica. Comunica perfectamente tu personalidad y estilo como creador."
    }

    RECOMENDACIONES_APARIENCIA = {
        1: "Tu apariencia actualmente no consigue captar la atención ni transmitir autenticidad. Trabaja en tu imagen personal, elige vestimenta que te favorezca y cuida detalles como peinado e higiene. Mostrarte auténtico y natural frente a cámara genera confianza y conexión.",
        2: "Imagen correcta pero neutra. Incorpora accesorios, colores y elementos que reflejen tu personalidad. Busca destacar con detalles propios y transmite autenticidad.",
        3: "Buena presencia, pero puedes mejorar tu atractivo visual y autenticidad. Ajusta iluminación, fondo y estilo de ropa para reforzar tu marca personal.",
        4: "¡Muy bien! Tu apariencia es agradable, auténtica y destaca frente a la cámara. Mantén tu estilo y cuida los detalles para seguir conectando con tu audiencia.",
        5: "¡Excelente! Tu presencia transmite autenticidad y profesionalismo, y complementa perfectamente tu contenido. Sigue mostrando tu esencia y fortalece tu conexión visual."
    }

    RECOMENDACIONES_CALIDAD_CONTENIDO = {
        1: "La calidad de tu contenido es baja y parece poco personal. Prioriza videos originales y propios, que comuniquen tu mensaje y estilo. Evita copiar contenido y enfócate en aportar valor auténtico a tu audiencia.",
        2: "Tu contenido es genérico o carece de autenticidad. Define claramente tu objetivo y tipo de creador, y muestra tu voz personal en cada video. Cuida la producción y elige temas que te representen.",
        3: "Contenido correcto, pero puede ser más personal y atractivo. Refuerza tu mensaje y experimenta con formatos que te permitan destacar tu estilo y creatividad.",
        4: "¡Muy bien! Tu contenido es innovador y aporta un mensaje claro. Se nota tu esfuerzo creativo y tu sello propio. Puedes seguir perfeccionando la edición y explorar nuevas ideas para diferenciarte.",
        5: "¡Excelente! La calidad de tu contenido es profesional, creativo y genera gran impacto o aporte en tu audiencia. Mantén ese enfoque y continúa evolucionando tu estilo."
    }

    RECOMENDACIONES_EMPATIA = {
        1: "Tu nivel de empatía con la audiencia es bajo y cuesta generar conexión. Es fundamental interactuar más durante las transmisiones, responder comentarios y mostrarte cercano a tu público. Trabaja en tu lenguaje corporal y expresión para transmitir energía y autenticidad.",
        2: "La interacción con tu audiencia es limitada y se refleja en una baja participación. Incorpora llamados a la acción, solicita opiniones y responde dudas en directo para que tus seguidores se sientan parte activa de tus contenidos. Mantén una comunicación constante y muestra interés genuino por su participación.",
        3: "Tu contenido comienza a generar conexión, pero puede potenciarse. Incrementa la empatía usando dinámicas regulares, colaboraciones y agradece siempre la participación de tus seguidores para fortalecer el vínculo.",
        4: "¡Muy bien! Conectas de forma natural y la audiencia responde positivamente. Promueves la participación y generas cercanía con tus seguidores.",
        5: "¡Excelente! Generas empatía y conexión con facilidad. Mantén tu carisma y busca nuevas formas de interactuar."
    }

    RECOMENDACIONES_EVAL_FOTO = {
        1: "Actualmente no tienes una foto personal en tu perfil. Es fundamental mostrar una imagen clara y auténtica, donde solo aparezcas tú, para que tu audiencia te identifique y confíe en tu perfil.",
        2: "La foto de perfil es genérica o de baja calidad, lo que puede afectar la percepción de profesionalismo. Elige una foto donde se te vea bien, con buena iluminación y resolución. Evita imágenes borrosas, impersonales o en las que aparezcas acompañado.",
        3: "Tu foto de perfil es aceptable, pero se puede mejorar. Actualízala con una imagen más reciente, de mejor calidad o que refleje mejor tu personalidad y propósito.",
        4: "¡Muy bien! Tu foto transmite confianza y profesionalismo, lo que genera una excelente primera impresión.",
        5: "¡Excelente! Foto profesional y atractiva. Mantén ese estándar."
    }

    RECOMENDACIONES_METADATA_VIDEOS = {
        1: "Los títulos, subtítulos y hashtags de tus videos actualmente son deficientes y no describen bien el contenido. Es fundamental que cada video tenga un título visible en la portada. Los títulos y subtitulos deben ser breves, claros y relacionados directamente con lo que muestras. Utiliza hashtags relevantes y específicos para facilitar que tu audiencia encuentre tus videos y mejorar tu alcance.",
        2: "Tus títulos, subtítulos y hashtags no logran resaltar tu contenido y pueden pasar desapercibidos. Procura que sean específicos, atractivos y despierten curiosidad. Selecciona hashtags que realmente representen el tema central del video.",
        3: "Tus títulos, subtítulos y hashtags son aceptables y comprensibles, pero pueden ser mucho más atractivos y efectivos. Intenta crear títulos que inviten a la acción y utiliza hashtags que ayuden a posicionar mejor tu contenido.",
        4: "¡Muy bien! Los títulos, subtítulos y hashtags son claros y alineados con el contenido que ofreces.",
        5: "¡Excelente! Títulos y hashtags claros, breves y llamativos."
    }

    apariencia_val = to_num(apariencia)
    engagement_val = to_num(engagement)
    calidad_contenido_val = to_num(calidad_contenido)
    eval_foto_val = to_num(eval_foto)
    eval_biografia_val = to_num(eval_biografia)
    metadata_videos_val = to_num(metadata_videos)

    sugerencias = []

    # Apariencia
    sugerencias.append(f"🧑‍🎤 Apariencia en cámara: {RECOMENDACIONES_APARIENCIA.get(apariencia_val, '')}")

    # Engagement
    sugerencias.append(f"🤝 Engagement: {RECOMENDACIONES_EMPATIA.get(engagement_val, '')}")

    # Calidad de contenido
    sugerencias.append(f"🎬 Calidad del contenido: {RECOMENDACIONES_CALIDAD_CONTENIDO.get(calidad_contenido_val, '')}")

    # Foto de perfil
    sugerencias.append(f"🖼️ Foto de perfil: {RECOMENDACIONES_EVAL_FOTO.get(eval_foto_val, '')}")

    # Biografía (solo sugerencia mejorada)
    bio_limpia = mejorar_biografia_sugerida(biografia_sugerida, eval_biografia_val)
    if bio_limpia:
        sugerencias.append(f"📝 Sugerencia de biografía:\n{bio_limpia}")

    # Metadata videos
    sugerencias.append(f"🏷️ Hastags y títulos de videos: {RECOMENDACIONES_METADATA_VIDEOS.get(metadata_videos_val, '')}")

    # Limpia para no mostrar elementos vacíos
    return [s for s in sugerencias if s.strip()]


def mejorar_biografia_sugerida(bio_salida: str, eval_biografia: int) -> str:

    labels = {
        1: 'No tiene Biografía',
        2: 'Deficiente (confusa, larga o sin propósito).',
        3: 'Aceptable (se entiende pero poco identidad).',
        4: 'Buena (clara, corta, con identidad).',
        5: 'Excelente (muy corta, clara y coherente).'
    }

    markdown = []

    # Si hay biografía sugerida, mostrar SOLO eso, limpio y bien redactado
    if bio_salida and str(bio_salida).strip():
        # Procesa atributos si están en formato "Corta: Sí", etc.
        atributos = {
            "Corta": False,
            "Comprensible": False,
            "Consistente": False,
            "Estética": False,
        }
        lineas = [l.strip() for l in bio_salida.splitlines() if l.strip()]
        frases = []
        bio_texto_final = []
        for linea in lineas:
            if ":" in linea:
                campo, valor = [x.strip() for x in linea.split(":", 1)]
                if campo in atributos and valor.lower() == "sí":
                    atributos[campo] = True
            elif "Recomendación:" in linea:
                continue  # omite esta línea
            else:
                bio_texto_final.append(linea)

        # Genera frase resumen de atributos
        if any(atributos.values()):
            lista_frases = []
            if atributos["Corta"]: lista_frases.append("corta")
            if atributos["Comprensible"]: lista_frases.append("comprensible")
            if atributos["Consistente"]: lista_frases.append("consistente")
            if atributos["Estética"]: lista_frases.append("estéticamente cuidada")
            frase_atributos = f"Tu biografía es {' ,'.join(lista_frases[:-1]) + ' y ' + lista_frases[-1] if len(lista_frases)>1 else lista_frases[0]}."
            markdown.append(f"\n{frase_atributos}")

        if bio_texto_final:
            markdown.append("\n" + "\n".join(bio_texto_final))

        # NO agrega recomendaciones automáticas si existe bio_salida
        return "\n".join(markdown)

    # Si NO hay biografía sugerida, muestra observación y recomendaciones automáticas
    observacion = labels.get(eval_biografia, "Sin evaluación.")
    markdown.append(f"{observacion}")
    if eval_biografia == 1:
        markdown.append("✍️ No tienes biografía, agrega una descripción breve y atractiva que resuma tu identidad o intereses.")
    elif eval_biografia == 2:
        markdown.append("⚠️ Tu biografía actual es confusa, extensa o sin propósito claro. Reescríbela para que sea corta, directa y comunique quién eres o qué ofreces.")
    elif eval_biografia == 3:
        markdown.append("🔄 La biografía es aceptable pero puedes reforzar tu identidad o mensaje. Agrega palabras clave, emojis o detalles que te diferencien.")
    elif eval_biografia == 4:
        markdown.append("👍 Tu biografía es buena, pero puedes pulirla para ser aún más memorable o coherente con tu marca personal.")
    elif eval_biografia == 5:
        markdown.append("🌟 ¡Excelente biografía! Es corta, clara y coherente. Mantén ese estilo.")

    return "\n".join(markdown)

def mejoras_sugeridas_datos_generales(edad, genero, idiomas, estudios, pais=None, actividad_actual=None):

    sugerencias = []

    # ==== Edad ====
    if edad is None:
        sugerencias.append("🔎 Completa tu edad para mejorar tu perfil.")
    elif edad < 18:
        sugerencias.append("🚫 Debes ser mayor de edad para participar como creador de lives en Tiktok.")
    elif edad < 20:
        sugerencias.append("🧑‍🎓 Eres joven, aprovecha tu energía y cercanía con tendencias actuales para conectar con audiencias similares.")
    elif edad <= 40:
        sugerencias.append("💪 Estás en una excelente etapa para crecer digitalmente.")
    elif edad <= 60:
        sugerencias.append("👨‍🏫 Puedes aportar experiencia y perspectiva única, enfócate en nichos que valoren conocimiento.")
    else:
        sugerencias.append("🕰️ Tu experiencia de vida puede ser un gran diferencial, comparte historias y consejos que inspiren.")

    # ==== Género ====
    if genero is None or not str(genero).strip():
        sugerencias.append("🔎 Completa el campo de género para personalizar mejor tus recomendaciones.")
    else:
        genero_l = str(genero).strip().lower()
        if genero_l == "femenino":
            sugerencias.append("🌸 🌸 Como creadora mujer, tienes la oportunidad de conectar con tendencias, marcas y públicos en el entorno digital latino.")
        elif genero_l == "masculino":
            sugerencias.append("La perspectiva masculina aporta valor en nichos específicos y puede diferenciarte en el entorno digital.")
        elif genero_l == "otro":
            sugerencias.append("🌈 La diversidad suma, busca comunidades inclusivas y auténticas.")
        elif genero_l == "prefiero no decir":
            sugerencias.append("🔐 Tu privacidad es importante, adapta tu comunicación como prefieras.")

    # ==== Idiomas ====
    idiomas_list = []
    if not idiomas:
        sugerencias.append("🌍 Agrega tus idiomas para ampliar tu alcance y recomendaciones.")
    else:
        if isinstance(idiomas, str):
            idiomas_list = [x.strip().lower() for x in idiomas.split(",")]
        elif isinstance(idiomas, list):
            idiomas_list = [str(x).lower().strip() for x in idiomas]
        else:
            idiomas_list = []

        if len(idiomas_list) == 1 and "espanol" in idiomas_list:
            sugerencias.append("🗣️ Si dominas otro idioma, agrégalo para atraer públicos internacionales.")
        elif len(idiomas_list) > 1:
            sugerencias.append("🌐 Aprovecha tu bilingüismo o multilingüismo para crear contenido dirigido a distintos países.")
        elif "otro" in idiomas_list:
            sugerencias.append("🔎 Especifica qué otros idiomas manejas para más recomendaciones.")

    # ==== Estudios ====
    if estudios is None or not str(estudios).strip():
        sugerencias.append("🎓 Completa tu nivel de estudios para adaptar mejor tus oportunidades.")
    else:
        estudios_l = str(estudios).strip().lower()
        if estudios_l in ["ninguno", "primaria"]:
            sugerencias.append("📚 Invierte en formación o aprendizaje autodidacta para ampliar tus oportunidades de colaboración.")
        elif estudios_l in ["secundaria", "tecnico", "autodidacta", "universitario_incompleto"]:
            sugerencias.append("💡 Refuerza tu perfil mostrando habilidades prácticas y proyectos personales.")
        elif estudios_l in ["universitario", "postgrado"]:
            sugerencias.append("🎓 Destaca tu formación en tu contenido para posicionarte como referente en tu área.")

    # ==== País ====
    if pais is None or not str(pais).strip():
        sugerencias.append("📍 Completa tu país para recibir oportunidades regionales.")
    else:
        pais_l = str(pais).strip().lower()
        pais_bonus = ["mexico", "colombia", "argentina"]
        if pais_l in pais_bonus:
            sugerencias.append(f"🌟 Tu país ({pais_l.title()}) es estratégico en TikTok, aprovecha para colaborar y crecer.")
        else:
            sugerencias.append(f"🌍 Puedes diferenciar tu contenido mostrando aspectos únicos de {pais_l.title()}.")

    # ==== Actividad actual ====
    if actividad_actual is None or not str(actividad_actual).strip():
        sugerencias.append("🔎 Completa tu actividad actual para recibir recomendaciones específicas.")
    else:
        act_l = str(actividad_actual).strip().lower()
        if "estudiante" in act_l:
            sugerencias.append("🎒 Aprovecha tu condición de estudiante para crear contenido educativo o para jóvenes.")
        elif "trabajo" in act_l:
            sugerencias.append("🏢 Organiza tu tiempo para compaginar trabajo y creación digital.")
        elif "emprendiendo" in act_l:
            sugerencias.append("🚀 Usa TikTok para mostrar tu emprendimiento y captar clientes.")
        elif "disponible_total" in act_l or "disponible" in act_l:
            sugerencias.append("⌛ Aprovecha tu disponibilidad para ser constante y probar nuevos formatos.")
        else:
            sugerencias.append("💡 Adapta tu contenido a tu realidad y público objetivo.")

    # ==== Puntaje y categoría general ====
    resultado = evaluar_datos_generales(edad, genero, idiomas, estudios, pais, actividad_actual)
    puntaje = resultado["puntaje_general"]
    categoria = resultado["puntaje_general_categoria"]


    return "\n".join(sugerencias)

def mejoras_sugeridas_preferencias_habitos(
    exp_otras: dict,
    intereses: dict,
    tipo_contenido: dict,
    tiempo=None,
    freq_lives=None,
    intencion=None,
    horario_preferido=None
) -> list:

    sugerencias_habitos = []

    # Experiencia en plataformas (incluye TikTok)
    total_exp = sum(exp_otras.values())
    exp_tiktok = exp_otras.get("TikTok", 0)

    if exp_tiktok > 0:
        sugerencias_habitos.append(
            "🎥 Ya tienes experiencia creando contenido en TikTok, lo cual es una ventaja importante. "
            "Aprovecha lo que has aprendido sobre la audiencia, el algoritmo y los formatos que funcionan para potenciar tu crecimiento."
        )
    elif total_exp == 0:
        sugerencias_habitos.append(
            "🔰 No tienes experiencia previa como creador en plataformas digitales, incluido TikTok. "
            "Esto puede dificultar tu adaptación. Te recomendamos explorar y analizar lo que hacen los aspirantes exitosos en TikTok y otras redes sociales, para entender tendencias y formatos populares."
        )
    elif total_exp <= 2:
        sugerencias_habitos.append(
            "📚 Tienes experiencia básica en plataformas, pero no en TikTok. "
            "Aprovecha tu aprendizaje previo y comienza a experimentar con contenido específico para esta red."
        )
    else:
        sugerencias_habitos.append(
            "🚀 Saca provecho de tu experiencia en otras plataformas para destacar en TikTok, adaptando las buenas prácticas y formatos que te funcionaron anteriormente."
        )

    # Intereses
    categorias_interes = [k for k, v in intereses.items() if v]
    if not categorias_interes:
        sugerencias_habitos.append(
            "❓ No has definido intereses principales para tu contenido. "
            "Esto puede dificultar que conectes con una audiencia específica. Reflexiona sobre tus pasiones y elige al menos una temática para orientar tus publicaciones."
        )
    elif len(categorias_interes) == 1:
        sugerencias_habitos.append("🎯 Enfócate en tu nicho para crear una comunidad fiel.")
    else:
        sugerencias_habitos.append("🌈 Aprovecha tu variedad de intereses para experimentar y conectar con públicos diversos.")

    # Tipo de contenido
    activos_contenido = [k for k, v in tipo_contenido.items() if v]
    if not activos_contenido:
        sugerencias_habitos.append(
            "⚠️ No seleccionaste ningún tipo de contenido. "
            "Identifica el formato que te resulta más natural (tutoriales, humor, charlas, etc.) y comienza a practicarlo para definir tu estilo."
        )
    elif "ventas en vivo" in activos_contenido:
        sugerencias_habitos.append(
            "🛒 Si haces ventas en vivo, combina entretenimiento y valor para captar audiencia. "
            "No descuides la interacción y la autenticidad."
        )
    elif len(activos_contenido) == 1:
        sugerencias_habitos.append("📌 Tener un enfoque claro te ayuda a posicionarte como referente.")
    elif 2 <= len(activos_contenido) <= 3:
        sugerencias_habitos.append("🎬 Probar varios tipos de contenido te permite ampliar tu alcance.")
    else:
        sugerencias_habitos.append(
            "⚠️ Tu enfoque es muy disperso, lo que puede confundir a tu audiencia. "
            "Prioriza los formatos que más disfrutas y donde tienes mejores resultados."
        )

    # Tiempo disponible
    tiempo_float = 0
    if tiempo is not None:
        try:
            tiempo_float = float(tiempo)
        except (ValueError, TypeError):
            tiempo_float = 0

        if tiempo_float < 12:
            sugerencias_habitos.append(
                "⏳ Tu tiempo disponible para realizar lives es menor a 12 horas por semana (menos de 2h diarias durante 6 días). Será muy difícil mantener constancia y crecer como creador. Te recomendamos organizar tu agenda y reservar al menos 2 horas diarias, 6 días a la semana."
            )
        elif tiempo_float < 21:
            sugerencias_habitos.append(
                "⚠️ Tu tiempo disponible para realizar lives está entre 12 y 20 horas semanales. Cumples el mínimo necesario, pero si puedes aumentar tu disponibilidad te acercarás al rango ideal para ver mejores resultados."
            )
        elif tiempo_float < 36:
            sugerencias_habitos.append(
                "✅ ¡Muy bien! Tu tiempo disponible está entre 21 y 35 horas por semana. Este es el rango ideal para un crecimiento constante, engagement y resultados positivos como creador de lives."
            )
        else:  # tiempo_float >= 36
            sugerencias_habitos.append(
                "🌟 Excelente, tienes 36 horas o más por semana para lives (por ejemplo, 3h en la mañana y 3h en la noche). Este nivel de dedicación es propio de aspirantes profesionales y te permitirá maximizar tu alcance y crecimiento."
            )

    # Frecuencia de lives
    freq_lives_int = 0
    if freq_lives is not None:
        try:
            freq_lives_int = int(freq_lives)
        except (ValueError, TypeError):
            freq_lives_int = 0
        if freq_lives_int == 0:
            sugerencias_habitos.append(
                "📡 No realizas transmisiones en vivo. "
                "Considera probar los lives para interactuar directamente y fortalecer tu comunidad."
            )
        elif freq_lives_int <= 3:
            sugerencias_habitos.append(
                "📡 Realizas pocas transmisiones en vivo. "
                "Aumentar la frecuencia podría ayudarte a crear vínculos más cercanos con tu audiencia."
            )
        else:
            sugerencias_habitos.append("🎤 Mantén la calidad y variedad en tus lives para no saturar a tu audiencia.")

    # Intención de trabajo
    if intencion is not None:
        intencion_str = str(intencion).strip().lower()

        if intencion_str == "no estoy seguro":
            sugerencias_habitos.append(
                "🤔 Define tus metas (diversión, aprendizaje, trabajo, ingresos). Tener claridad te ayudará a enfocar tu esfuerzo y medir tu progreso."
            )
        elif intencion_str == "trabajo secundario":
            sugerencias_habitos.append(
                "💼 Considera esta actividad como un complemento. Organiza tu tiempo, genera constancia y evalúa si en el futuro puede convertirse en un proyecto principal."
            )
        elif intencion_str == "trabajo principal":
            sugerencias_habitos.append(
                "🏆 Enfócate con disciplina y constancia. Crea rutinas profesionales, mide resultados y trabaja tu marca personal para consolidar tu presencia."
            )
        elif "hobby" in intencion_str:
            sugerencias_habitos.append(
                "🎨 Transforma tu hobby en una oportunidad: prueba distintos formatos, aprende de otros aspirantes y empieza a dar pasos hacia la profesionalización."
            )
        elif "diversión" in intencion_str:
            sugerencias_habitos.append(
                "😄 Disfruta el proceso y transmite tu autenticidad. Aunque lo veas como diversión, mantener cierta regularidad hará que conectes mejor con la audiencia."
            )

    # Horario preferido
    if horario_preferido is not None:
        horario = str(horario_preferido).strip().lower()
        if "variable" in horario or "otro" in horario:
            sugerencias_habitos.append(
                "🕑 Tu horario de publicación es variable. "
                "Esto puede dificultar que tu audiencia cree el hábito de buscar tu contenido. Trata de identificar los horarios en que tus seguidores están más activos y adapta tus publicaciones para maximizar el alcance."
            )
        elif "madrugada" in horario:
            sugerencias_habitos.append(
                "🌙 Publicas en la madrugada. Este horario puede ser una oportunidad para captar audiencias nocturnas, personas de otras zonas horarias y público internacional. "
                "Observa si tus videos reciben interacción en ese horario; si es así, potencia este segmento y adapta tu contenido a sus intereses. Si no, prueba otros horarios para comparar resultados."
            )
        else:
            sugerencias_habitos.append("📅 Mantener horarios regulares ayuda a crear hábito y fidelidad en tus seguidores.")

    return sugerencias_habitos

def evaluar_y_mejorar_biografia(bio, modelo="gpt-4"):
    prompt = f"""
Evalúa esta biografía de TikTok:

"{bio}"

Para cada uno de estos 3 criterios, responde con "Sí" o "No".  
Si respondes "No", añade una breve explicación (1 línea) de por qué.

1. ¿Es corta?  
2. ¿Es comprensible?  
3. ¿Es consistente con una identidad o propósito?

Al final, si alguno de los criterios fue "No", sugiere una nueva biografía para el creador".  
Responde en este formato estricto:

Corta: Sí / No  
[Justificación si aplica]  
Comprensible: Sí / No  
[Justificación si aplica]  
Consistente: Sí / No  
[Justificación si aplica]
Estética: Sí / No
[Justificación si aplica]  

Recomendación: [Solo si algún criterio fue "No", de lo contrario escribe "Ninguna"]
"""

    try:
        response = client.chat.completions.create(
            model=modelo,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        return f"❌ Error al evaluar la biografía: {e}"


def evaluacion_total(
    cualitativa_score=None,
    estadistica_score=None,
    general_score=None,
    habitos_score=None
):
    """Combina todos los puntajes en un puntaje total y determina la categoría."""

    def to_num(val):
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0

    # Asegura que todos los puntajes sean numéricos
    cualitativa_score = to_num(cualitativa_score)
    estadistica_score = to_num(estadistica_score)
    general_score = to_num(general_score)
    habitos_score = to_num(habitos_score)

    # Calcula el puntaje total ponderado y lo redondea a 2 decimales
    total = (
        cualitativa_score * 0.50 +
        estadistica_score * 0.25 +
        general_score * 0.15 +
        habitos_score * 0.10
    )

    total_redondeado = float(round(total, 2))  # 👈 asegura float limpio

    # Asigna la categoría basada en el puntaje total
    if total_redondeado < 1.5:
        categoria = "Muy bajo"
    elif total_redondeado < 2.5:
        categoria = "Bajo"
    elif total_redondeado < 3.5:
        categoria = "Medio"
    elif total_redondeado < 4.5:
        categoria = "Alto"
    else:
        categoria = "Excelente"

    return {
        "puntaje_total": total_redondeado,
        "puntaje_total_categoria": categoria
    }

def evaluar_potencial_creador(aspirante_id, score_cualitativa: float):
    """
    Evalúa el potencial de un creador y retorna el potencial estimado como entero.
    """
    try:
        # 1. Obtener métricas del creador
        data_dict = obtener_datos_estadisticas_aspirantes_perfil(aspirante_id)
        if not data_dict:
            return {"error": "No se encontraron métricas para el creador."}

        # 2. Calcular score estadístico
        score_estadistica_raw = evaluar_estadisticas(
            seguidores=data_dict.get("seguidores"),
            siguiendo=data_dict.get("siguiendo"),
            videos=data_dict.get("videos"),
            likes=data_dict.get("likes"),
            duracion=data_dict.get("duracion_emisiones")
        )

        # Extraer puntaje si viene como dict
        if isinstance(score_estadistica_raw, dict):
            score_estadistica = score_estadistica_raw.get("puntaje_estadistica")
        else:
            score_estadistica = score_estadistica_raw

        print("DEBUG score_estadistica:", score_estadistica)

        if not isinstance(score_estadistica, (int, float)):
            raise ValueError(f"Score estadístico inválido: {score_estadistica}")

        # 3. Calcular total ponderado y convertir a entero
        potencial_estimado = int(round(score_estadistica * 0.3 + score_cualitativa * 00.7))

        # 4. Clasificación en texto
        if potencial_estimado >= 4:
            nivel = "Alto potencial"
        elif potencial_estimado >= 3:
            nivel = "Potencial medio"
        elif potencial_estimado >= 2:
            nivel = "Potencial bajo"
        elif potencial_estimado >= 1:
            nivel = "Requiere desarrollo"
        else:
            nivel = "No recomendado"

        return {
            "potencial_estimado": potencial_estimado,
            "nivel": nivel
        }

    except Exception as e:
        print("❌ Error en evaluar_potencial_creador:", e)
        return {"error": str(e)}


def limpiar_biografia_ia(bio_ia: str) -> str:
    # Elimina comillas dobles al inicio y final, si están
    bio_ia = bio_ia.strip()
    if bio_ia.startswith('"') and bio_ia.endswith('"'):
        bio_ia = bio_ia[1:-1]
    # Reemplaza secuencias "\n" (texto) por salto de línea real
    bio_ia = bio_ia.replace("\\n", "\n")
    # (opcional) Borra espacios extra al inicio/final de cada línea
    bio_ia = "\n".join(line.strip() for line in bio_ia.splitlines())
    return bio_ia

def mejoras_sugeridas_estadisticas_cortas(
    seguidores=0,
    siguiendo=0,
    likes=0,
    videos=0,
    duracion=0
):

    sugerencias = []

    seguidores = to_num(seguidores)
    siguiendo = to_num(siguiendo)
    likes = to_num(likes)
    videos = to_num(videos)
    duracion = to_num(duracion)

    sugerencias.append(
        f"📌 Estado actual → Seguidores: {seguidores}, Siguiendo: {siguiendo}, Likes: {likes}, Videos: {videos}, Días activo: {duracion}"
    )

    # Likes normalizados
    if seguidores > 0 and videos > 0:
        likes_normalizado = likes / (seguidores * videos)
    elif seguidores > 0:
        likes_normalizado = likes / seguidores
    else:
        likes_normalizado = 0

    # Seguidores
    if seguidores < 50:
        sugerencias.append("❌ Actualmente no es apto para ingresar a la agencia. El requisito mínimo es superar los 50 seguidores.")
        sugerencias.append("📌 Enfócate primero en superar los 50 seguidores antes de continuar con otros aspectos.")
        sugerencias.append("🔍 Revisa qué tipo de videos generan más interacción y replica los formatos que funcionen mejor.")
        sugerencias.append("🌐 Promociona tu perfil en otras redes sociales o grupos para atraer seguidores iniciales.")
    elif seguidores < 300:
        sugerencias.append("⏫ Prueba nuevas temáticas o formatos para atraer diferentes públicos.")
        sugerencias.append("🎯 Haz colaboraciones con otros aspirantes para aumentar tu alcance.")

    # Siguiendo
    if siguiendo >= seguidores or (seguidores > 0 and siguiendo >= (0.9 * seguidores)):
        sugerencias.append(
            "🔄 Prioriza la creación de contenido interesante y útil para tu audiencia, en lugar de enfocarte únicamente en conseguir seguidores por intercambio.")
    elif siguiendo < (0.3 * seguidores):
        sugerencias.append("🤝 Interactúa con otros aspirantes y participa en tendencias para aumentar tu visibilidad.")

    # Likes normalizados (engagement relativo)
    if likes_normalizado == 0:
        sugerencias.append(
            "⚡ Según el número de likes tus videos aún no generan interacción. Enfócate en contenidos que inviten a comentar, compartir y dar 'me gusta'.")
    elif likes_normalizado < 0.02:
        sugerencias.append(
            "📈 Según el número de likes el nivel de interacción es bajo en relación a tus seguidores y videos. Prueba diferentes formatos y fomenta la participación en tus publicaciones.")

    # Videos
    if videos < 10:
        sugerencias.append("📅 Publica más videos de forma constante (mínimo 10) para mejorar tu presencia.")

    return sugerencias

def mejoras_sugeridas_cualitativa_cortas(
    apariencia=0,
    engagement=0,
    calidad_contenido=0,
    eval_foto=0,
    eval_biografia=0,
    metadata_videos=0,
    biografia_sugerida=""
):
    def to_num(val):
        try:
            return int(round(float(val)))
        except (TypeError, ValueError):
            return 0

    RECOMENDACIONES_USUARIO = {
        1: "Tu nombre de usuario incluye números o símbolos poco profesionales. Considera elegir un nombre sencillo, memorable y sin cifras, que represente tu identidad y facilite que otros te recuerden y te encuentren.",
        2: "El nombre de usuario es aceptable pero podría ser más profesional. Si es posible, elimina cifras o símbolos y utiliza tu nombre real o artístico para fortalecer tu marca personal.",
    }

    RECOMENDACIONES_BIOGRAFIA = {
        1: "Tu biografía está incompleta o no comunica claramente quién eres y qué haces. Redáctala de forma auténtica, específica y orientada al tipo de contenido que realizas. Agrega una descripción personal que refleje tu esencia y motive a otros a seguirte.",
        2: "La biografía es genérica o poco clara. Intenta ser más específico sobre tu perfil y el tipo de contenido que ofreces. Incluye detalles sobre tus intereses y lo que te hace diferente.",
    }

    RECOMENDACIONES_APARIENCIA = {
        1: "Tu apariencia actualmente no consigue captar la atención ni transmitir autenticidad. Trabaja en tu imagen personal, elige vestimenta que te favorezca y cuida detalles como peinado e higiene. Mostrarte auténtico y natural frente a cámara genera confianza y conexión.",
        2: "Imagen correcta pero neutra. Incorpora accesorios, colores y elementos que reflejen tu personalidad. Busca destacar con detalles propios y transmite autenticidad.",
    }

    RECOMENDACIONES_CALIDAD_CONTENIDO = {
        1: "La calidad de tu contenido es baja y parece poco personal. Prioriza videos originales y propios, que comuniquen tu mensaje y estilo. Evita copiar contenido y enfócate en aportar valor auténtico a tu audiencia.",
        2: "Tu contenido es genérico o carece de autenticidad. Define claramente tu objetivo y tipo de creador, y muestra tu voz personal en cada video. Cuida la producción y elige temas que te representen.",
    }

    RECOMENDACIONES_EMPATIA = {
        1: "Tu nivel de empatía con la audiencia es bajo y cuesta generar conexión. Es fundamental interactuar más durante las transmisiones, responder comentarios y mostrarte cercano a tu público. Trabaja en tu lenguaje corporal y expresión para transmitir energía y autenticidad.",
        2: "La interacción con tu audiencia es limitada y se refleja en una baja participación. Incorpora llamados a la acción, solicita opiniones y responde dudas en directo para que tus seguidores se sientan parte activa de tus contenidos. Mantén una comunicación constante y muestra interés genuino por su participación.",
    }

    RECOMENDACIONES_EVAL_FOTO = {
        1: "Actualmente no tienes una foto personal en tu perfil. Es fundamental mostrar una imagen clara y auténtica, donde solo aparezcas tú, para que tu audiencia te identifique y confíe en tu perfil.",
        2: "La foto de perfil es genérica o de baja calidad, lo que puede afectar la percepción de profesionalismo. Elige una foto donde se te vea bien, con buena iluminación y resolución. Evita imágenes borrosas, impersonales o en las que aparezcas acompañado.",
    }

    RECOMENDACIONES_METADATA_VIDEOS = {
        1: "Los títulos, subtítulos y hashtags de tus videos actualmente son deficientes y no describen bien el contenido. Es fundamental que cada video tenga un título visible en la portada. Los títulos y subtitulos deben ser breves, claros y relacionados directamente con lo que muestras. Utiliza hashtags relevantes y específicos para facilitar que tu audiencia encuentre tus videos y mejorar tu alcance.",
        2: "Tus títulos, subtítulos y hashtags no logran resaltar tu contenido y pueden pasar desapercibidos. Procura que sean específicos, atractivos y despierten curiosidad. Selecciona hashtags que realmente representen el tema central del video.",
    }

    apariencia_val = to_num(apariencia)
    engagement_val = to_num(engagement)
    calidad_contenido_val = to_num(calidad_contenido)
    eval_foto_val = to_num(eval_foto)
    eval_biografia_val = to_num(eval_biografia)
    metadata_videos_val = to_num(metadata_videos)

    sugerencias = []

    # Apariencia
    sugerencias.append(f"🧑‍🎤 Apariencia en cámara: {RECOMENDACIONES_APARIENCIA.get(apariencia_val, '')}")

    # Engagement
    sugerencias.append(f"🤝 Engagement: {RECOMENDACIONES_EMPATIA.get(engagement_val, '')}")

    # Calidad de contenido
    sugerencias.append(f"🎬 Calidad del contenido: {RECOMENDACIONES_CALIDAD_CONTENIDO.get(calidad_contenido_val, '')}")

    # Foto de perfil
    sugerencias.append(f"🖼️ Foto de perfil: {RECOMENDACIONES_EVAL_FOTO.get(eval_foto_val, '')}")

    # Biografía (solo sugerencia mejorada)
    bio_limpia = mejorar_biografia_sugerida(biografia_sugerida, eval_biografia_val)
    if bio_limpia:
        sugerencias.append(f"📝 Sugerencia de biografía:\n{bio_limpia}")

    # Metadata videos
    sugerencias.append(f"🏷️ Hastags y títulos de videos: {RECOMENDACIONES_METADATA_VIDEOS.get(metadata_videos_val, '')}")

    # Limpia para no mostrar elementos vacíos
    return [s for s in sugerencias if s.strip()]



def mejoras_sugeridas_datos_generales_cortas(edad, genero, idiomas, estudios, pais=None, actividad_actual=None):

    sugerencias = []

    # ==== Edad ====
    if edad is None:
        sugerencias.append("🔎 Completa tu edad para mejorar tu perfil.")
    elif edad < 18:
        sugerencias.append("🚫 Debes ser mayor de edad para participar como creador de lives en Tiktok.")

    # ==== Género ====
    if genero is None or not str(genero).strip():
        sugerencias.append("🔎 Completa el campo de género para personalizar mejor tus recomendaciones.")


    # ==== Estudios ====
    if estudios is None or not str(estudios).strip():
        sugerencias.append("🎓 Completa tu nivel de estudios para adaptar mejor tus oportunidades.")
    else:
        estudios_l = str(estudios).strip().lower()
        if estudios_l in ["ninguno", "primaria"]:
            sugerencias.append("📚 Invierte en formación o aprendizaje autodidacta para ampliar tus oportunidades de colaboración.")
        elif estudios_l in ["secundaria", "tecnico", "autodidacta", "universitario_incompleto"]:
            sugerencias.append("💡 Refuerza tu perfil mostrando habilidades prácticas y proyectos personales.")

    # ==== País ====
    if pais is None or not str(pais).strip():
        sugerencias.append("📍 Completa tu país para recibir oportunidades regionales.")
    else:
        pais_l = str(pais).strip().lower()
        pais_bonus = ["mexico", "colombia", "argentina"]
        if pais_l in pais_bonus:
            sugerencias.append(f"🌟 Tu país ({pais_l.title()}) es estratégico en TikTok, aprovecha para colaborar y crecer.")
        else:
            sugerencias.append(f"🌍 Puedes diferenciar tu contenido mostrando aspectos únicos de {pais_l.title()}.")


    # ==== Puntaje y categoría general ====
    resultado = evaluar_datos_generales(edad, genero, idiomas, estudios, pais, actividad_actual)
    puntaje = resultado["puntaje_general"]
    categoria = resultado["puntaje_general_categoria"]


    return "\n".join(sugerencias)

def evaluar_estadisticas_pre(seguidores, siguiendo, videos, likes, duracion):

    # Normalizar entradas
    seguidores = int(seguidores or 0)
    videos = int(videos or 0)
    likes = float(likes or 0)
    duracion = float(duracion or 0) if duracion is not None else 0

    # Corte duro
    if seguidores < 50:
        return {
            "puntaje_estadistica": 0.0,
            "puntaje_estadistica_categoria": "bajo"
        }

    # Likes normalizados
    if seguidores > 0 and videos > 0:
        likes_normalizado = likes / (seguidores * videos)
    elif seguidores > 0:
        likes_normalizado = likes / seguidores
    else:
        likes_normalizado = 0.0

    # Seguidores (0–4)
    if seguidores <= 500:
        seg = 2
    elif seguidores <= 1000:
        seg = 3
    else:
        seg = 4

    # Videos (0–4)
    if videos <= 0:
        vid = 0
    elif videos < 10:
        vid = 1
    elif videos <= 20:
        vid = 2
    elif videos <= 40:
        vid = 3
    else:
        vid = 4

    # Likes normalizados (0–4)
    if likes_normalizado <= 0:
        lik = 0
    elif likes_normalizado < 0.02:
        lik = 1
    elif likes_normalizado <= 0.05:
        lik = 2
    elif likes_normalizado <= 0.10:
        lik = 3
    else:
        lik = 4

    # Duración emisiones (0–4)
    if duracion < 20:
        dur = 1
    elif duracion <= 89:
        dur = 2
    elif duracion <= 179:
        dur = 3
    else:
        dur = 4

    # Score base
    score = seg * 0.35 + vid * 0.25 + lik * 0.25 + dur * 0.15
    score = round(score * (5 / 4), 2)

    # Convertir a bajo / medio / alto
    categoria = convertir_1a5_a_1a3(score)

    return {
        "puntaje_estadistica": score,
        "puntaje_estadistica_categoria": categoria
    }


def evaluar_estadisticas_preV0(seguidores, siguiendo, videos, likes, duracion):

    # Corte duro → debe devolver diccionario SIEMPRE
    if seguidores is None or seguidores < 50:
        return {
            "puntaje_estadistica": 0.0,
            "puntaje_estadistica_categoria": "No aplicable"
        }

    # Evitar división por cero
    if seguidores > 0 and videos and videos > 0:
        likesNormalizado = likes / (seguidores * videos)
    elif seguidores > 0:
        likesNormalizado = likes / seguidores
    else:
        likesNormalizado = 0

    # Seguidores
    if seguidores <= 0:
        seg = 0
    elif seguidores < 50:
        seg = 1
    elif seguidores <= 500:
        seg = 2
    elif seguidores <= 1000:
        seg = 3
    else:
        seg = 4

    # Videos
    if videos is None:
        vid = 0
    elif videos < 10:
        vid = 1
    elif videos <= 20:
        vid = 2
    elif videos <= 40:
        vid = 3
    else:
        vid = 4

    # Likes normalizados
    if likesNormalizado == 0:
        lik = 0
    elif likesNormalizado < 0.02:
        lik = 1
    elif likesNormalizado <= 0.05:
        lik = 2
    elif likesNormalizado <= 0.10:
        lik = 3
    else:
        lik = 4

    # Duración emisiones
    if duracion is None:
        dur = 0
    elif duracion < 20:
        dur = 1
    elif duracion <= 89:
        dur = 2
    elif duracion <= 179:
        dur = 3
    else:
        dur = 4

    # Score
    score = seg * 0.35 + vid * 0.25 + lik * 0.25 + dur * 0.15
    score = round(score * (5 / 4), 2)

    # Categoría proporcional
    if score == 0:
        categoria = "No aplicable"
    elif score < 1.5:
        categoria = "Muy bajo"
    elif score < 2.5:
        categoria = "Bajo"
    elif score < 3.5:
        categoria = "Aceptable"
    elif score < 4.5:
        categoria = "Bueno"
    else:
        categoria = "Excelente"

    return {
        "puntaje_estadistica": score,
        "puntaje_estadistica_categoria": categoria
    }


def evaluar_datos_generales_pre(edad, genero, pais=None, actividad_actual=None):
    """
    Evaluación PARCIAL de datos generales SIN considerar estudios ni idiomas.
    Factores usados:
      - Edad
      - Género
      - Actividad actual
      - Bono por país estratégico
    Devuelve categoría: bajo / medio / alto
    """

    # ==== Edad (Rango 1-5) ====
    if edad is None:
        e = 0
    elif edad == 1:
        # Menores de 18: corte duro
        score_final = 0.0
        return {
            "puntaje_general": score_final,
            "puntaje_general_categoria": convertir_1a5_a_1a3(score_final)  # -> "bajo"
        }
    elif edad in (2, 3):
        e = 3
    elif edad == 4:
        e = 2
    elif edad == 5:
        e = 1
    else:
        e = 0

    # ==== Género ====
    genero_map = {
        "femenino": 3,
        "masculino": 1,
        "otro": 2,
        "prefiero no decir": 2
    }
    g_key = str(genero).strip().lower() if genero is not None else ""
    g = genero_map.get(g_key, 0)

    # ==== Actividad actual ====
    actividad_map = {
        "estudiante_tiempo_completo": 1,
        "estudiante_tiempo_parcial": 2,
        "trabajo_tiempo_completo": 1,
        "trabajo_medio_tiempo": 2,
        "buscando_empleo": 3,
        "emprendiendo": 3,
        "disponible_total": 3,
        "otro": 1
    }
    act_key = str(actividad_actual).strip().lower() if actividad_actual else ""
    act = actividad_map.get(act_key, 0)

    # ==== Bono por país estratégico ====
    pais_bonus = {"colombia", "venezuela"}
    pais_key = str(pais).strip().lower() if pais else ""
    bonus = 0.5 if pais_key in pais_bonus else 0

    # ==== Ponderación ====
    score = (
        e * 0.30 +      # Edad
        g * 0.30 +      # Género
        act * 0.35 +    # Actividad
        bonus * 0.05    # Bono país
    )

    # Normalización 0–5 (máximo teórico ~3)
    score_final = round(score * (5 / 3), 2)

    # Categoría bajo/medio/alto (misma lógica que estadísticas)
    categoria = convertir_1a5_a_1a3(score_final)

    return {
        "puntaje_general": score_final,
        "puntaje_general_categoria": categoria
    }


def  evaluar_preferencias_habitos_pre(
    exp_otras,
    tiempo=None,
    freq_lives=None,
    intencion=None
):
    """
    Evaluación de preferencias y hábitos para Pre-Evaluación.
    Usa:
      - experiencia TikTok Live (años, ej: 0.5 = 6 meses)
      - tiempo disponible (1–3)
      - frecuencia de lives (1–4)
      - intención de trabajo (strings de map_intencion)
    Devuelve categoría: bajo / medio / alto
    """

    # ==============================
    # 1) Experiencia en TikTok Live (0–3)
    #    0 meses = mala
    #    1–3 meses = regular
    #    4–11 meses = buena
    #    12+ meses = excelente
    # ==============================
    exp_tiktok = 0.0
    if isinstance(exp_otras, dict):
        try:
            exp_tiktok = float(exp_otras.get("TikTok Live", 0) or 0)
        except (ValueError, TypeError):
            exp_tiktok = 0.0

    if exp_tiktok <= 0:
        exp = 0
    elif exp_tiktok <= 0.25:   # hasta 3 meses (3/12)
        exp = 1
    elif exp_tiktok < 1:       # 4–11 meses
        exp = 2
    else:                      # 12+ meses
        exp = 3

    # ==============================
    # 2) Tiempo disponible (1–3)
    # ==============================
    try:
        tiempo_int = int(tiempo) if tiempo is not None else None
    except (ValueError, TypeError):
        tiempo_int = None

    tiempo_map = {1: 1, 2: 2, 3: 3}
    t = tiempo_map.get(tiempo_int, 0)

    # ==============================
    # 3) Frecuencia lives (1–4)
    # ==============================
    try:
        freq_int = int(freq_lives) if freq_lives is not None else None
    except (ValueError, TypeError):
        freq_int = None

    freq_map = {1: 1, 2: 2, 3: 3, 4: 0}
    f = freq_map.get(freq_int, 0)

    # ==============================
    # 4) Intención (alineada con map_intencion)
    # ==============================
    it_key = str(intencion).strip().lower() if intencion else ""
    it_map = {
        "fuente de ingresos principal": 3,
        "fuente de ingresos secundario": 2,
        "fuente de ingresos secundaria": 2,
        "hobby, pero me gustaría profesionalizarlo": 2,
        "diversión, sin intención profesional": 1,
        "diversion, sin intención profesional": 1,
        "no estoy seguro": 0
    }
    it = it_map.get(it_key, 0)

    # ==============================
    # 5) Score base (0–3) -> normalizado a 0–5
    # ==============================
    score_base = (
        exp * 0.40 +
        t   * 0.25 +
        f   * 0.25 +
        it  * 0.10
    )
    score = round(score_base * (5 / 3), 2)

    # ==============================
    # 6) Categoría bajo / medio / alto
    # ==============================
    categoria = convertir_1a5_a_1a3(score)

    return {
        "puntaje_habitos": score,
        "puntaje_habitos_categoria": categoria
    }




def evaluar_preferencias_habitos_preV0(
    exp_otras: dict,
    tiempo=None,
    freq_lives=None,
    intencion=None
):
    """
    Evaluación de preferencias y hábitos para Pre-Evaluación.
    Usa:
      - experiencia TikTok Live
      - tiempo disponible (1–3)
      - frecuencia de lives (1–4)
      - intención de trabajo
    """

    # ==============================
    # 1. Experiencia en TikTok Live (0–2)
    # ==============================
    if isinstance(exp_otras, dict):
        exp_tiktok = float(exp_otras.get("TikTok Live", 0) or 0)
    else:
        exp_tiktok = 0

    # Nueva clasificación
    if exp_tiktok == 0:
        exp = 0       # mala experiencia
    elif exp_tiktok < 2:
        exp = 1       # regular
    else:
        exp = 2       # buena experiencia (≥1 año)

    # ==============================
    # 2. Tiempo disponible (según opcionesTiempoDisponible)
    # ==============================
    tiempo_map = {
        1: 1,   # 0–1 hrs
        2: 2,   # 1–3 hrs
        3: 3    # más de 3 hrs
    }
    t = tiempo_map.get(tiempo, 0)

    # ==============================
    # 3. Frecuencia live (según opcionesFrecuenciaLives)
    # ==============================
    freq_map = {
        1: 1,   # 1–2 días
        2: 2,   # 3–5 días
        3: 3,   # todos los días
        4: 0    # ninguno
    }
    f = freq_map.get(freq_lives, 0)

    # ==============================
    # 4. Intención de trabajo
    # ==============================
    it_map = {
        "trabajo principal": 3,
        "trabajo secundario": 2,
        "hobby, pero me gustaría profesionalizarlo": 2,
        "diversión, sin intención profesional": 1,
        "no estoy seguro": 0
    }
    it = it_map.get(
        str(intencion).strip().lower() if intencion else "",
        0
    )

    # ==============================
    # 5. Score final ajustado (0–5)
    # ==============================
    score = (
        exp * 0.40 +   # experiencia pesa más: DIRECTAMENTE relacionada al éxito en TikTok Live
        t   * 0.25 +   # tiempo disponible
        f   * 0.25 +   # frecuencia de lives
        it  * 0.10     # intención de profesionalizar
    )

    # Normalización a 0–5
    score = round(score * (5 / 3), 2)

    # ==============================
    # 6. Categorías ajustadas
    # ==============================
    if score == 0:
        categoria = "No aplicable"
    elif score < 1.5:
        categoria = "Muy bajo"
    elif score < 2.5:
        categoria = "Bajo"
    elif score < 3.5:
        categoria = "Aceptable"
    elif score < 4.5:
        categoria = "Bueno"
    else:
        categoria = "Excelente"

    return {
        "puntaje_habitos": score,
        "puntaje_habitos_categoria": categoria
    }



def evaluacion_total_pre(
        estadistica_score=None,
        general_score=None,
        habitos_score=None
):
    """Combina puntajes parciales en un total (float) y asigna categoría."""

    def to_num(val):
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0

    # Normalizar a float
    estadistica_score = to_num(estadistica_score)
    general_score = to_num(general_score)
    habitos_score = to_num(habitos_score)

    # Calcular total como float y redondear
    total = (
            estadistica_score * 0.33 +
            general_score * 0.33 +
            habitos_score * 0.33
    )

    total = float(round(total, 2))  # 👈 asegura float limpio

    if total < 1.5:
        categoria = "Muy bajo"
    elif total < 2.5:
        categoria = "Bajo"
    elif total < 3.5:
        categoria = "Medio"
    elif total < 4.5:
        categoria = "Alto"
    else:
        categoria = "Excelente"

    return {
        "puntaje_total": total,  # 👈 float
        "puntaje_total_categoria": categoria
    }

import json


import json

def evaluar_y_actualizar_perfil_pre_encuesta(aspirante_id: int):
    """
    Evalúa perfil PRE (sin potencial_estimado), calcula puntajes y
    actualiza aspirantes_perfil con:
      puntaje_estadistica, puntaje_estadistica_categoria,
      puntaje_general, puntaje_general_categoria,
      puntaje_habitos, puntaje_habitos_categoria,
      puntaje_total, puntaje_total_categoria
    Pesos total: 30% / 30% / 40%
    """

    def safe_float(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    def safe_round(x):
        return round(x) if isinstance(x, (int, float)) else None

    # -------------------------------
    # 1) Leer perfil
    # -------------------------------
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        edad,
                        genero,
                        pais,
                        actividad_actual,
                        seguidores,
                        siguiendo,
                        videos,
                        likes,
                        duracion_emisiones,
                        tiempo_disponible,
                        frecuencia_lives,
                        intencion_trabajo,
                        experiencia_otras_plataformas
                    FROM aspirantes_perfil
                    WHERE aspirante_id = %s
                    LIMIT 1
                """, (aspirante_id,))
                row = cur.fetchone()

                if not row:
                    return {
                        "status": "error",
                        "msg": "No existe aspirantes_perfil para ese aspirante_id",
                        "aspirante_id": aspirante_id,
                    }

                (
                    edad,
                    genero,
                    pais,
                    actividad_actual,
                    seguidores,
                    siguiendo,
                    videos,
                    likes,
                    duracion_emisiones,
                    tiempo_disponible,
                    frecuencia_lives,
                    intencion_trabajo,
                    experiencia_otras_plataformas
                ) = row

                # Parsear experiencia JSON
                if not experiencia_otras_plataformas:
                    experiencia_otras_plataformas = {}
                elif isinstance(experiencia_otras_plataformas, str):
                    try:
                        experiencia_otras_plataformas = json.loads(experiencia_otras_plataformas)
                    except Exception:
                        experiencia_otras_plataformas = {}

                # -------------------------------
                # 2) Sub-evaluaciones (ya traen bajo/medio/alto)
                # -------------------------------
                est = evaluar_estadisticas_pre(
                    seguidores=seguidores,
                    siguiendo=siguiendo,
                    videos=videos,
                    likes=likes,
                    duracion=duracion_emisiones,
                )

                gen = evaluar_datos_generales_pre(
                    edad=edad,
                    genero=genero,
                    pais=pais,
                    actividad_actual=actividad_actual,
                )

                hab = evaluar_preferencias_habitos_pre(
                    exp_otras=experiencia_otras_plataformas,
                    tiempo=tiempo_disponible,
                    freq_lives=frecuencia_lives,
                    intencion=intencion_trabajo,
                )

                puntaje_estadistica = safe_float(est.get("puntaje_estadistica"))
                cat_estadistica = est.get("puntaje_estadistica_categoria")

                puntaje_general = safe_float(gen.get("puntaje_general"))
                cat_general = gen.get("puntaje_general_categoria")

                puntaje_habitos = safe_float(hab.get("puntaje_habitos"))
                cat_habitos = hab.get("puntaje_habitos_categoria")

                # -------------------------------
                # 3) Puntaje total ponderado 30 / 30 / 40
                #    Re-normaliza pesos si falta algún componente (None)
                # -------------------------------
                suma = 0.0
                suma_pesos = 0.0

                if puntaje_estadistica is not None:
                    suma += puntaje_estadistica * 0.30
                    suma_pesos += 0.30
                if puntaje_general is not None:
                    suma += puntaje_general * 0.30
                    suma_pesos += 0.30
                if puntaje_habitos is not None:
                    suma += puntaje_habitos * 0.40
                    suma_pesos += 0.40

                puntaje_total = round(suma / suma_pesos, 2) if suma_pesos > 0 else None
                cat_total = convertir_1a5_a_1a3(puntaje_total)

                # -------------------------------
                # 4) Alertas (igual que antes)
                # -------------------------------
                alerta = 0
                if edad == 1:
                    alerta = 1
                elif (seguidores or 0) < 50:
                    alerta = 2

                # -------------------------------
                # 5) Update aspirantes_perfil
                # -------------------------------
                cur.execute("""
                    UPDATE aspirantes_perfil
                    SET
                        puntaje_estadistica = %s,
                        puntaje_estadistica_categoria = %s,
                        puntaje_general = %s,
                        puntaje_general_categoria = %s,
                        puntaje_habitos = %s,
                        puntaje_habitos_categoria = %s,
                        puntaje_total = %s,
                        puntaje_total_categoria = %s
                    WHERE aspirante_id = %s
                """, (
                    safe_round(puntaje_estadistica),
                    cat_estadistica,
                    safe_round(puntaje_general),
                    cat_general,
                    safe_round(puntaje_habitos),
                    cat_habitos,
                    safe_round(puntaje_total),
                    cat_total,
                    aspirante_id
                ))

                conn.commit()

                # -------------------------------
                # 6) Respuesta
                # -------------------------------
                return {
                    "status": "ok",
                    "puntaje_estadistica": safe_round(puntaje_estadistica),
                    "puntaje_estadistica_categoria": cat_estadistica,
                    "puntaje_general": safe_round(puntaje_general),
                    "puntaje_general_categoria": cat_general,
                    "puntaje_habitos": safe_round(puntaje_habitos),
                    "puntaje_habitos_categoria": cat_habitos,
                    "puntaje_total": safe_round(puntaje_total),
                    "puntaje_total_categoria": cat_total,
                    "alerta": alerta,
                }

    except Exception as e:
        print("❌ Error en evaluar_y_actualizar_perfil_pre_ponderado:", e)
        return {
            "status": "error",
            "msg": "Error evaluando/actualizando perfil",
            "aspirante_id": aspirante_id
        }


def evaluar_perfil_pre(aspirante_id: int):

    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        edad,
                        genero,
                        pais,
                        actividad_actual,
                        seguidores,
                        siguiendo,
                        videos,
                        likes,
                        duracion_emisiones,
                        tiempo_disponible,
                        frecuencia_lives,
                        intencion_trabajo,
                        experiencia_otras_plataformas,
                        potencial_estimado
                    FROM aspirantes_perfil
                    WHERE aspirante_id = %s
                    LIMIT 1
                """, (aspirante_id,))
                row = cur.fetchone()

                if not row:
                    return {
                        "status": "error",
                        "puntaje_estadistica": None,
                        "puntaje_estadistica_categoria": None,
                        "puntaje_general": None,
                        "puntaje_general_categoria": None,
                        "puntaje_habitos": None,
                        "puntaje_habitos_categoria": None,
                        "puntaje_cualitativo": None,
                        "puntaje_cualitativo_categoria": None,
                        "puntaje_total": None,
                        "puntaje_total_categoria": None,
                        "puntaje_total_ponderado": None,
                        "puntaje_total_ponderado_cat": None,
                        "alerta": None,
                    }

                (
                    edad,
                    genero,
                    pais,
                    actividad_actual,
                    seguidores,
                    siguiendo,
                    videos,
                    likes,
                    duracion_emisiones,
                    tiempo_disponible,
                    frecuencia_lives,
                    intencion_trabajo,
                    experiencia_otras_plataformas,
                    potencial_estimado
                ) = row

                # if experiencia_otras_plataformas is None:
                #     experiencia_otras_plataformas = {}

                if not experiencia_otras_plataformas:
                    experiencia_otras_plataformas = {}
                elif isinstance(experiencia_otras_plataformas, str):
                    try:
                        experiencia_otras_plataformas = json.loads(experiencia_otras_plataformas)
                    except Exception:
                        experiencia_otras_plataformas = {}

    except Exception as e:
        print("❌ Error obteniendo perfil:", e)
        return {
            "status": "error",
            "puntaje_estadistica": None,
            "puntaje_estadistica_categoria": None,
            "puntaje_general": None,
            "puntaje_general_categoria": None,
            "puntaje_habitos": None,
            "puntaje_habitos_categoria": None,
            "puntaje_cualitativo": None,
            "puntaje_cualitativo_categoria": None,
            "puntaje_total": None,
            "puntaje_total_categoria": None,
            "puntaje_total_ponderado": None,
            "puntaje_total_ponderado_cat": None,
            "alerta": None,
        }

    # 1) Estadísticas
    est = evaluar_estadisticas_pre(
        seguidores=seguidores,
        siguiendo=siguiendo,
        videos=videos,
        likes=likes,
        duracion=duracion_emisiones,
    )

    # 2) Datos generales
    gen = evaluar_datos_generales_pre(
        edad=edad,
        genero=genero,
        pais=pais,
        actividad_actual=actividad_actual,
    )

    # 3) Preferencias y hábitos
    hab = evaluar_preferencias_habitos_pre(
        exp_otras=experiencia_otras_plataformas,
        tiempo=tiempo_disponible,
        freq_lives=frecuencia_lives,
        intencion=intencion_trabajo,
    )

    puntaje_estadistica = est.get("puntaje_estadistica")
    puntaje_estadistica_categoria = est.get("puntaje_estadistica_categoria")

    puntaje_general = gen.get("puntaje_general")
    puntaje_general_categoria = gen.get("puntaje_general_categoria")

    puntaje_habitos = hab.get("puntaje_habitos")
    puntaje_habitos_categoria = hab.get("puntaje_habitos_categoria")

    # Calcular puntaje total a partir de los puntajes disponibles (no None)
    puntajes_validos = [
        s for s in [puntaje_estadistica, puntaje_general, puntaje_habitos]
        if s is not None
    ]

    if puntajes_validos:
        puntaje_total = round(sum(puntajes_validos) / len(puntajes_validos), 2)
    else:
        puntaje_total = None

    alerta = 0

    if edad == 1: # Menores 18 años
        alerta = 1
    elif seguidores < 50: # seguidores menores a 50
        alerta = 2

    visual = potencial_estimado if potencial_estimado in (1, 3, 5) else None

    resultado = puntaje_ponderado_completo(
        puntaje_total,  # ya es float promedio
        visual
    )

    puntaje_total_ponderado=resultado.get("puntuacion")
    puntaje_total_ponderado_cat=resultado.get("categoria_texto")


    return {
        "status": "ok",
        "puntaje_estadistica": round(puntaje_estadistica),
        "puntaje_estadistica_categoria": convertir_1a5_a_1a3(puntaje_estadistica),
        "puntaje_general": round(puntaje_general),
        "puntaje_general_categoria": convertir_1a5_a_1a3(puntaje_general),
        "puntaje_habitos": round(puntaje_habitos),
        "puntaje_habitos_categoria": convertir_1a5_a_1a3(puntaje_habitos),
        "puntaje_cualitativo": None,
        "puntaje_cualitativo_categoria": None,
        "puntaje_total": round(puntaje_total),
        "puntaje_total_categoria": convertir_1a5_a_1a3(puntaje_total),
        "puntaje_total_ponderado": puntaje_total_ponderado,
        "puntaje_total_ponderado_cat": puntaje_total_ponderado_cat,
        "potencial_estimado":potencial_estimado,
        "alerta": alerta,
    }

def puntaje_ponderado_completo(
    puntaje_total: float | int | None = None,
    calificacion_visual: int | None = None,
):

    # --- Normalizar puntaje_total (1–5 → 0–1) ---
    if puntaje_total is None or puntaje_total < 1:
        puntaje_norm = None
    else:
        pt = max(1, min(5, float(puntaje_total)))
        puntaje_norm = (pt - 1) / 4.0  # 0–1

    # --- Normalizar calificacion_visual (1–5 → 0–1) ---
    if calificacion_visual is None or calificacion_visual < 1:
        visual_norm = None
    else:
        cv = max(1, min(5, int(calificacion_visual)))
        visual_norm = (cv - 1) / 4.0  # 0–1 (ajustado)

    # --- Sin datos ---
    if puntaje_norm is None and visual_norm is None:
        puntuacion = 1
    else:
        # Si solo uno existe, usar ese
        if puntaje_norm is None:
            ponderado = visual_norm
        elif visual_norm is None:
            ponderado = puntaje_norm
        else:
            # 60% peso numérico + 40% peso visual
            ponderado = (puntaje_norm * 0.60) + (visual_norm * 0.40)

        # Convertir 0–1 → 1–5
        puntuacion = round(ponderado * 4 + 1)
        puntuacion = max(1, min(5, puntuacion))

    # --- Clasificación texto ---
    if puntuacion <= 2:
        categoria_texto = "bajo"
    elif puntuacion == 3:
        categoria_texto = "medio"
    else:
        categoria_texto = "alto"

    return {
        "puntuacion": puntuacion,
        "categoria_texto": categoria_texto
    }



def convertir_1a5_a_1a3(puntaje):
    if puntaje is None:
        return None

    # Redondear al múltiplo de 0.5 más cercano
    puntaje_redondeado = round(puntaje)

    # Convertir a categoría 1–3
    if puntaje_redondeado <= 2:
        return "bajo"
    elif puntaje_redondeado == 3:
        return "medio"
    else:
        return "alto"


import json

def diagnostico_aspirantes_perfil_pre(
    aspirante_id: int,
    puntajes_calculados: dict = None
) -> str:
    """
    Diagnóstico preliminar del perfil del creador para Pre-Evaluación.
    Usa datos personales, estadísticas, hábitos y cualitativo (si existe),
    coherente con:
      - puntaje_total (ponderado 20/20/30/30)
      - puntaje_total_categoria (convertir_1a5_a_1a3)
      - puntaje_cualitativo / puntaje_cualitativo_categoria (reemplaza potencial_estimado)
    """

    # =========================
    #  MAPEOS DEL FRONTEND / DB
    # =========================
    MAP_EDAD = {
        1: "Menos de 18 años",
        2: "18 - 24 años",
        3: "25 - 34 años",
        4: "35 - 45 años",
        5: "Más de 45 años",
    }

    MAP_ACTIVIDAD = {
        "estudiante_tiempo_completo": "Estudia tiempo completo",
        "estudiante_tiempo_parcial": "Estudia medio tiempo",
        "trabajo_tiempo_completo": "Trabaja tiempo completo",
        "trabajo_medio_tiempo": "Trabaja medio tiempo",
        "buscando_empleo": "Buscando empleo",
        "emprendiendo": "Emprendiendo",
        "disponible_total": "Disponible tiempo completo",
        "otro": "Otro",
    }

    MAP_TIEMPO = {
        1: "0–1 hrs",
        2: "1–3 hrs",
        3: "Más de 3 hrs",
    }

    MAP_FRECUENCIA = {
        1: "1–2 días",
        2: "3–5 días",
        3: "Todos los días",
        4: "Ninguno",
    }

    # =========================
    #  OBTENER DATOS
    # =========================
    datos = obtener_datos_mejoras_aspirantes_perfil(aspirante_id)
    fuente = puntajes_calculados or datos or {}

    # =========================
    #  ARMAR PUNTAJES (categorías ya vienen listas; total sí viene de convertir_1a5_a_1a3)
    # =========================
    puntajes = {
        "Calificación total (ponderado)": (
            fuente.get("puntaje_total"),
            fuente.get("puntaje_total_categoria"),
        ),
        "Calificación Estadísticas": (
            fuente.get("puntaje_estadistica"),
            fuente.get("puntaje_estadistica_categoria"),
        ),
        "Calificación Datos personales": (
            fuente.get("puntaje_general"),
            fuente.get("puntaje_general_categoria"),
        ),
        "Calificación Hábitos y preferencias": (
            fuente.get("puntaje_habitos"),
            fuente.get("puntaje_habitos_categoria"),
        ),
    }

    # Cualitativo (reemplaza potencial_estimado)
    if ("puntaje_cualitativo" in fuente) or ("puntaje_cualitativo_categoria" in fuente):
        puntajes["Calificación Cualitativa (revisión interna)"] = (
            fuente.get("puntaje_cualitativo"),
            fuente.get("puntaje_cualitativo_categoria"),
        )

    diagnostico = {
        "🧑‍🎓 Datos personales y generales": [],
        "📊 Estadísticas": [],
        "📅 Preferencias y hábitos": [],
    }

    # =========================
    # DATOS PERSONALES
    # =========================
    edad = datos.get("edad")
    genero = datos.get("genero") or "No informado"
    pais = datos.get("pais") or "No informado"
    actividad_raw = datos.get("actividad_actual")

    diagnostico["🧑‍🎓 Datos personales y generales"].extend([
        f"🎂 Edad: {MAP_EDAD.get(edad, 'No informado')}",
        f"👤 Género: {genero}",
        f"🌎 País: {pais}",
        f"💼 Actividad actual: {MAP_ACTIVIDAD.get(actividad_raw, 'No informado')}",
    ])

    # =========================
    # ESTADÍSTICAS
    # =========================
    seguidores = datos.get("seguidores")
    siguiendo = datos.get("siguiendo")
    likes = datos.get("likes")
    videos = datos.get("videos")
    duracion = datos.get("duracion_emisiones")

    diagnostico["📊 Estadísticas"].extend([
        f"👥 Seguidores: {seguidores if seguidores is not None else 'No informado'}",
        f"➡️ Siguiendo: {siguiendo if siguiendo is not None else 'No informado'}",
        f"👍 Likes: {likes if likes is not None else 'No informado'}",
        f"🎥 Videos publicados: {videos if videos is not None else 'No informado'}",
        # Nota: tu campo se llama duracion_emisiones. Ajusta el texto si son minutos u horas.
        f"⏳ Duración de emisiones: {duracion if duracion is not None else 'No informado'}",
    ])

    # =========================
    # PREFERENCIAS Y HÁBITOS
    # =========================
    tiempo = datos.get("tiempo_disponible")
    frecuencia = datos.get("frecuencia_lives")
    intencion = datos.get("intencion_trabajo") or "No informado"

    experiencia = datos.get("experiencia_otras_plataformas") or {}

    # ✅ BUG FIX: si viene como JSON string, parsearlo
    if isinstance(experiencia, str):
        try:
            experiencia = json.loads(experiencia)
        except Exception:
            experiencia = {}

    experiencia_fmt = []
    if isinstance(experiencia, dict):
        for plataforma, valor in experiencia.items():
            try:
                v = float(valor)
            except (TypeError, ValueError):
                continue
            if v:
                # v está en años (0.5 = 6 meses)
                experiencia_fmt.append(f"{plataforma}: {v} años")

    experiencia_str = ", ".join(experiencia_fmt) if experiencia_fmt else "Sin experiencia"

    diagnostico["📅 Preferencias y hábitos"].extend([
        f"⌛ Tiempo disponible: {MAP_TIEMPO.get(tiempo, 'No definido')}",
        f"📡 Frecuencia de lives: {MAP_FRECUENCIA.get(frecuencia, 'No definido')}",
        f"🌍 Experiencia en plataformas: {experiencia_str}",
        f"🎯 Intención de trabajo: {intencion}",
    ])

    # =========================
    # ARMADO DEL MENSAJE
    # =========================
    mensaje = ["# 📋 DIAGNÓSTICO PRELIMINAR DEL PERFIL\n"]

    mensaje.append("## 🧑‍🎓 Datos personales y generales")
    mensaje.extend([f"- {item}" for item in diagnostico["🧑‍🎓 Datos personales y generales"]])
    mensaje.append("")

    mensaje.append("## 📊 Estadísticas del perfil")
    mensaje.extend([f"- {item}" for item in diagnostico["📊 Estadísticas"]])
    mensaje.append("")

    mensaje.append("## 📅 Preferencias y hábitos")
    mensaje.extend([f"- {item}" for item in diagnostico["📅 Preferencias y hábitos"]])
    mensaje.append("")

    mensaje.append("# 🏅 Puntajes del Perfil")
    for nombre, (valor, categoria) in puntajes.items():
        # Solo mostrar categoría, pero dejo valor por si lo quieres mostrar después
        mensaje.append(f"- {nombre}: {categoria or 'Sin categoría'}")

    return "\n".join(mensaje)



def diagnostico_aspirantes_perfil_preV1(
    aspirante_id: int,
    puntajes_calculados: dict = None
) -> str:
    """
    Diagnóstico preliminar del perfil del creador para Pre-Evaluación.
    Usa datos personales, estadísticas y hábitos (SIN cualitativo).
    """

    # =========================
    #  MAPEOS DEL FRONTEND
    # =========================

    MAP_EDAD = {
        1: "Menos de 18 años",
        2: "18 - 24 años",
        3: "25 - 34 años",
        4: "35 - 45 años",
        5: "Más de 45 años",
    }

    MAP_ACTIVIDAD = {
        "estudiante_tiempo_completo": "Estudia tiempo completo",
        "estudiante_tiempo_parcial": "Estudia medio tiempo",
        "trabajo_tiempo_completo": "Trabaja tiempo completo",
        "trabajo_medio_tiempo": "Trabaja medio tiempo",
        "buscando_empleo": "Buscando empleo",
        "emprendiendo": "Emprendiendo",
        "disponible_total": "Disponible tiempo completo",
        "otro": "Otro",
    }

    MAP_TIEMPO = {
        1: "0–1 hrs",
        2: "1–3 hrs",
        3: "Más de 3 hrs",
    }

    MAP_FRECUENCIA = {
        1: "1–2 días",
        2: "3–5 días",
        3: "Todos los días",
        4: "Ninguno",
    }

    # =========================
    #  OBTENER DATOS
    # =========================

    datos = obtener_datos_mejoras_aspirantes_perfil(aspirante_id)

    puntajes = {
        "Calificación parcial total": (
            (puntajes_calculados or datos).get("puntaje_total"),
            (puntajes_calculados or datos).get("puntaje_total_categoria"),
        ),
        "Calificación Estadísticas": (
            (puntajes_calculados or datos).get("puntaje_estadistica"),
            (puntajes_calculados or datos).get("puntaje_estadistica_categoria"),
        ),
        "Calificación Datos personales": (
            (puntajes_calculados or datos).get("puntaje_general"),
            (puntajes_calculados or datos).get("puntaje_general_categoria"),
        ),
        "Calificación Hábitos y preferencias": (
            (puntajes_calculados or datos).get("puntaje_habitos"),
            (puntajes_calculados or datos).get("puntaje_habitos_categoria"),
        ),
    }

    diagnostico = {
        "🧑‍🎓 Datos personales y generales": [],
        "📊 Estadísticas": [],
        "📅 Preferencias y hábitos": [],
    }

    # =========================
    # DATOS PERSONALES
    # =========================

    edad = datos.get("edad")
    genero = datos.get("genero", "No informado")
    pais = datos.get("pais", "No informado")
    actividad_raw = datos.get("actividad_actual")

    diagnostico["🧑‍🎓 Datos personales y generales"].extend([
        f"🎂 Edad: {MAP_EDAD.get(edad, 'No informado')}",
        f"👤 Género: {genero or 'No informado'}",
        f"🌎 País: {pais or 'No informado'}",
        f"💼 Actividad actual: {MAP_ACTIVIDAD.get(actividad_raw, 'No informado')}",
    ])

    # =========================
    # ESTADÍSTICAS
    # =========================

    seguidores = datos.get("seguidores")
    siguiendo = datos.get("siguiendo")
    likes = datos.get("likes")
    videos = datos.get("videos")
    dias_activo = datos.get("duracion_emisiones")

    diagnostico["📊 Estadísticas"].extend([
        f"👥 Seguidores: {seguidores if seguidores is not None else 'No informado'}",
        f"➡️ Siguiendo: {siguiendo if siguiendo is not None else 'No informado'}",
        f"👍 Likes: {likes if likes is not None else 'No informado'}",
        f"🎥 Videos publicados: {videos if videos is not None else 'No informado'}",
        f"⏳ Días activo TikTok LIVE: {dias_activo if dias_activo is not None else 'No informado'}",
    ])

    # =========================
    # PREFERENCIAS Y HÁBITOS
    # =========================

    tiempo = datos.get("tiempo_disponible")
    frecuencia = datos.get("frecuencia_lives")
    experiencia = datos.get("experiencia_otras_plataformas") or {}
    intencion = datos.get("intencion_trabajo", "No informado")

    experiencia_fmt = [
        f"{plataforma}: {valor} {'año' if valor == 1 else 'años'}"
        for plataforma, valor in experiencia.items()
        if valor
    ]
    experiencia_str = ", ".join(experiencia_fmt) if experiencia_fmt else "Sin experiencia"

    diagnostico["📅 Preferencias y hábitos"].extend([
        f"⌛ Tiempo disponible: {MAP_TIEMPO.get(tiempo, 'No definido')}",
        f"📡 Frecuencia de lives: {MAP_FRECUENCIA.get(frecuencia, 'No definido')}",
        f"🌍 Experiencia en plataformas: {experiencia_str}",
        f"💼 Intención de trabajo: {intencion}",
    ])

    # =========================
    # NUEVO: POTENCIAL PERFIL TIKTOK
    # =========================

    MAP_POTENCIAL_TIKTOK = {
        1: "Bajo",
        3: "En desarrollo",
        5: "Alto",
    }
    potencial_val = datos.get("potencial_estimado")

    # Solo mostrar si es un valor válido
    if potencial_val in (1, 3, 5):
        potencial_txt = MAP_POTENCIAL_TIKTOK[potencial_val]
        diagnostico["📊 Estadísticas"].append(
            f"📈 Potencial Perfil Público TikTok(Contenido y presentación): {potencial_txt}"
        )


    # =========================
    # ARMADO DEL MENSAJE
    # =========================

    mensaje = ["# 📋 DIAGNÓSTICO PRELIMINAR DEL PERFIL\n"]

    mensaje.append("## 🧑‍🎓 Datos personales y generales")
    mensaje.extend([f"- {item}" for item in diagnostico["🧑‍🎓 Datos personales y generales"]])
    mensaje.append("")

    mensaje.append("## 📊 Estadísticas del perfil")
    mensaje.extend([f"- {item}" for item in diagnostico["📊 Estadísticas"]])
    mensaje.append("")

    mensaje.append("## 📅 Preferencias y hábitos")
    mensaje.extend([f"- {item}" for item in diagnostico["📅 Preferencias y hábitos"]])
    mensaje.append("")

    mensaje.append("# 🏅 Puntajes Parciales del Perfil")
    for nombre, (_, categoria) in puntajes.items():
        mensaje.append(f"- {nombre}: {categoria or 'Sin categoría'}")

    return "\n".join(mensaje)



def obtener_guardar_pre_resumen(aspirante_id: int):
    """
    Calcula la pre-evaluación del creador, genera el diagnóstico preliminar
    y actualiza la tabla aspirantes_perfil con los resultados.
    Retorna un diccionario con toda la información.
    """

    # 1️⃣ Calcular puntajes parciales de pre-evaluación
    resultado = evaluar_perfil_pre(aspirante_id)

    if resultado.get("status") != "ok":
        raise Exception("Perfil no encontrado")

    # 2️⃣ Obtener diagnóstico preliminar
    try:
        diagnostico = diagnostico_aspirantes_perfil_pre(aspirante_id)
    except Exception:
        diagnostico = "-"

    # 3️⃣ Texto para mostrar en interfaz
    texto = (
        f"📊 Pre-Evaluación:\n"
        f"Puntaje Parcial: {resultado.get('puntaje_total_ponderado')}\n"
        f"Categoría: {resultado.get('puntaje_total_ponderado_cat')}\n\n"
        f"🩺 Diagnóstico Preliminar:\n{diagnostico}\n"
    )

    # 4️⃣ Guardar resultados en tabla aspirantes_perfil
    try:
        with get_connection_context() as conn:
            cur = conn.cursor()

            cur.execute(
                """
                UPDATE aspirantes_perfil
                SET
                    puntaje_estadistica = %s,
                    puntaje_estadistica_categoria = %s,
                    puntaje_general = %s,
                    puntaje_general_categoria = %s,
                    puntaje_habitos = %s,
                    puntaje_habitos_categoria = %s,
                    puntaje_total = %s,
                    puntaje_total_categoria = %s,
                    diagnostico = %s,
                    actualizado_en = NOW()
                WHERE aspirante_id = %s
                """,
                (
                    resultado.get("puntaje_estadistica"),
                    resultado.get("puntaje_estadistica_categoria"),
                    resultado.get("puntaje_general"),
                    resultado.get("puntaje_general_categoria"),
                    resultado.get("puntaje_habitos"),
                    resultado.get("puntaje_habitos_categoria"),
                    resultado.get("puntaje_total_ponderado"),
                    resultado.get("puntaje_total_ponderado_cat"),
                    texto,
                    aspirante_id,
                )
            )

            if cur.rowcount == 0:
                raise Exception("No existe aspirantes_perfil para este aspirante_id")

    except Exception as e:
        raise Exception(f"Error al guardar la pre-evaluación en aspirantes_perfil: {str(e)}")


# def evaluar_perfil_pre(aspirante_id: int):
#     """
#     Obtiene datos de aspirantes_perfil y calcula:
#     - puntaje_estadisticas_pre
#     - puntaje_datos_generales_pre
#     - puntaje_preferencias_habitos_pre
#     - puntaje_total_pre (promedio parcial)
#     """
#
#     # ======================
#     # 1. Obtener datos desde BD
#     # ======================
#     try:
#         with get_connection_context() as conn:
#             with conn.cursor() as cur:
#                 cur.execute("""
#                     SELECT
#                         edad, genero, pais, actividad_actual,
#                         seguidores, siguiendo, videos, likes, duracion_emisiones,
#                         tiempo_disponible, frecuencia_lives, intencion_trabajo,
#                         experiencia_otras_plataformas
#                     FROM aspirantes_perfil
#                     WHERE aspirante_id = %s
#                     LIMIT 1
#                 """, (aspirante_id,))
#
#                 row = cur.fetchone()
#                 if not row:
#                     return {"error": "Perfil no encontrado"}
#
#                 (
#                     edad, genero, pais, actividad_actual,
#                     seguidores, siguiendo, videos, likes, duracion,
#                     tiempo_disponible, frecuencia_lives, intencion_trabajo,
#                     experiencia_otras_plataformas
#                 ) = row
#
#                 if experiencia_otras_plataformas is None:
#                     experiencia_otras_plataformas = {}
#     except Exception as e:
#         print("❌ Error obteniendo perfil:", e)
#         return {"error": "Error al consultar BD"}
#
#     # ======================
#     # 2. Evaluar estadísticas parciales
#     # ======================
#     est = evaluar_estadisticas_pre(
#         seguidores=seguidores,
#         siguiendo=siguiendo,
#         videos=videos,
#         likes=likes,
#         duracion=duracion
#     )
#
#     # ======================
#     # 3. Evaluar datos generales parciales
#     # ======================
#     gen = evaluar_datos_generales_pre(
#         edad=edad,
#         genero=genero,
#         pais=pais,
#         actividad_actual=actividad_actual
#     )
#
#     # ======================
#     # 4. Evaluar hábitos y preferencias parciales
#     # ======================
#     hab = evaluar_preferencias_habitos_pre(
#         exp_otras=experiencia_otras_plataformas,
#         tiempo=tiempo_disponible,
#         freq_lives=frecuencia_lives,
#         intencion=intencion_trabajo
#     )
#
#     # ======================
#     # 5. Calcular puntaje total PRE-EVALUACIÓN
#     # (promedio simple de los tres parciales)
#     # ======================
#     puntajes = [
#         est.get("puntaje_estadistica", 0),
#         gen.get("puntaje_general", 0),
#         hab.get("puntaje_habitos", 0)
#     ]
#
#     puntaje_total_pre = round(sum(puntajes) / 3, 2)
#
#     # Categoría total
#     if puntaje_total_pre < 1.5:
#         cat_total = "Muy bajo"
#     elif puntaje_total_pre < 2.5:
#         cat_total = "Bajo"
#     elif puntaje_total_pre < 3.5:
#         cat_total = "Aceptable"
#     elif puntaje_total_pre < 4.5:
#         cat_total = "Bueno"
#     else:
#         cat_total = "Excelente"
#
#     # ======================
#     # 6. Respuesta final
#     # ======================
#     return {
#         "status": "ok",
#         "aspirante_id": aspirante_id,
#
#         # Puntajes individuales
#         "estadisticas": est,
#         "datos_generales": gen,
#         "habitos": hab,
#
#         # Puntaje total pre-evaluación
#         "puntaje_total_pre": puntaje_total_pre,
#         "puntaje_total_categoria_pre": cat_total,
#     }
