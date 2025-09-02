from DataBase import *
from openai import OpenAI
from dotenv import load_dotenv
import os

# Cargar variables de entorno
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

def diagnostico_perfil_creador(creador_id: int) -> str:
    """
    Diagnóstico integral del perfil del creador, con puntajes, labels y unidades correctas.
    """
    datos = obtener_datos_mejoras_perfil_creador(creador_id)
    puntajes = {
        "Calificación total": (datos.get("puntaje_total"), datos.get("puntaje_total_categoria")),
        "Calificación Estadísticas": (datos.get("puntaje_estadistica"), datos.get("puntaje_estadistica_categoria")),
        "Calificación Cualitativo": (datos.get("puntaje_manual"), datos.get("puntaje_manual_categoria")),
        "Calificación Datos personales": (datos.get("puntaje_general"), datos.get("puntaje_general_categoria")),
        "Calificación Hábitos y preferencias": (datos.get("puntaje_habitos"), datos.get("puntaje_habitos_categoria")),
    }

    advertencias = []
    diagnostico = {
        "📊 Estadísticas": [],
        "💡 Cualitativo": [],
        "🧑‍🎓 Datos personales": [],
        "📅 Hábitos y preferencias": [],
    }

    # Puntajes
    puntajes_lines = ["# 🏅 Categorías del Perfil"]
    for nombre, (_, categoria) in puntajes.items():
        puntajes_lines.append(
            f"- {nombre}: {categoria if categoria is not None else 'Sin categoría'}"
        )
    puntajes_lines.append("")

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

    # Cualitativo (con labels)
    apariencia = datos.get("apariencia")
    engagement = datos.get("engagement")
    calidad = datos.get("calidad_contenido")
    eval_foto = datos.get("eval_foto")
    eval_bio = datos.get("eval_biografia")

    diagnostico["💡 Cualitativo"].append(
        f"🧑‍🎤 Apariencia en cámara: {get_label('apariencia', apariencia)}"
    )
    diagnostico["💡 Cualitativo"].append(
        f"🤝 Engagement: {get_label('engagement', engagement)}"
    )
    diagnostico["💡 Cualitativo"].append(
        f"🎬 Calidad del contenido: {get_label('calidad_contenido', calidad)}"
    )
    diagnostico["💡 Cualitativo"].append(
        f"🖼️ Foto de perfil: {get_label('eval_foto', eval_foto)}"
    )
    diagnostico["💡 Cualitativo"].append(
        f"📖 Biografía: {get_label('eval_biografia', eval_bio)}"
    )

    if engagement is not None and engagement <= 2:
        advertencias.append("⚠️ Necesita mayor interacción con la audiencia.")
    if calidad is not None and calidad <= 2:
        advertencias.append("⚠️ Contenido de baja calidad percibida.")

    # Datos personales
    idioma = datos.get("idioma", "No especificado")
    estudios = datos.get("estudios", "No especificado")
    actividad = datos.get("actividad_actual", "No especificado")

    diagnostico["🧑‍🎓 Datos personales"].append(f"🌐 Idioma: {idioma}")
    diagnostico["🧑‍🎓 Datos personales"].append(
        f"- - 🎓 Estudios: {(estudios.replace('_', ' ') if estudios else 'No informado')}"
    )
    diagnostico["🧑‍🎓 Datos personales"].append(f"💼 Actividad actual: {actividad}")

    if idioma and idioma.lower() != "español":
        advertencias.append("🌍 Puede aprovechar público bilingüe.")
    if actividad and "estudiante" in actividad.lower():
        advertencias.append("📘 Puede aprovechar su etapa de formación para contenido educativo.")

    # Hábitos y preferencias (unidades ajustadas)
    tiempo = datos.get("tiempo_disponible", "No definido")
    frecuencia = datos.get("frecuencia_lives", "No definido")
    experiencia = datos.get("experiencia_otras_plataformas", {})
    intereses = datos.get("intereses", {})
    tipo_contenido = datos.get("tipo_contenido", {})
    intencion = datos.get("intencion_trabajo", "No definido")

    experiencia_fmt = [f"{k}: {v}" for k, v in experiencia.items() if v > 0] if isinstance(experiencia, dict) else experiencia
    # experiencia_str = ", ".join(experiencia_fmt) if experiencia_fmt else "Sin experiencia"

    experiencia_fmt = []
    for plataforma, valor in experiencia.items():
        if not valor or valor == 0:  # ignora None y 0
            continue
        sufijo = "año" if valor == 1 else "años"
        experiencia_fmt.append(f"{plataforma}: {valor} {sufijo}")

    experiencia_str = ", ".join(experiencia_fmt) if experiencia_fmt else "Sin experiencia"

    intereses_fmt = [k for k, v in intereses.items() if v] if isinstance(intereses, dict) else intereses
    intereses_str = ", ".join(intereses_fmt) if intereses_fmt else "No definidos"

    tipo_fmt = [k for k, v in tipo_contenido.items() if v] if isinstance(tipo_contenido, dict) else tipo_contenido
    tipo_str = ", ".join(tipo_fmt) if tipo_fmt else "No definido"

    diagnostico["📅 Hábitos y preferencias"].append(
        f"⌛ Tiempo disponible: {tiempo} horas por semana" if tiempo not in [None, "", "No definido"] else "⌛ Tiempo disponible: No definido"
    )
    diagnostico["📅 Hábitos y preferencias"].append(
        f"📡 Frecuencia de lives: {frecuencia} veces por semana" if frecuencia not in [None, "", "No definido"] else "📡 Frecuencia de lives: No definido"
    )
    diagnostico["📅 Hábitos y preferencias"].append(f"🌍 Experiencia en otras plataformas: {experiencia_str}")
    diagnostico["📅 Hábitos y preferencias"].append(f"🎯 Intereses: {intereses_str}")
    diagnostico["📅 Hábitos y preferencias"].append(f"🎨 Tipo de contenido: {tipo_str}")
    diagnostico["📅 Hábitos y preferencias"].append(f"💼 Intención de trabajo: {intencion}")

    if (isinstance(frecuencia, str) and frecuencia.lower() == "baja") or (isinstance(tiempo, str) and tiempo.lower() == "limitado"):
        advertencias.append("⚠️ Tiempo de dedicación limitado.")
    if isinstance(intencion, str) and intencion.lower() in ["hobbie", "ocasional"]:
        advertencias.append("ℹ️ Perfil más recreativo que profesional.")

    # Formatear salida
    mensaje = ["# 📋 DIAGNÓSTICO DEL PERFIL\n"]
    mensaje += puntajes_lines
    for seccion, items in diagnostico.items():
        mensaje.append(f"## {seccion}")
        for item in items:
            mensaje.append(f"- {item}")
        mensaje.append("")  # Espacio entre secciones

    if advertencias:
        mensaje.append("### ⚠️ Advertencias y oportunidades de mejora")
        for adv in advertencias:
            mensaje.append(f"- {adv}")

    return "\n".join(mensaje)


def evaluar_estadisticas(seguidores, siguiendo, videos, likes, duracion):
    # Corte duro: si tiene muy pocos seguidores, no cuenta
    if seguidores is None or seguidores < 50:
        return 0.0

    # Evitar división por cero
    if seguidores > 0 and videos and videos > 0:
        likesNormalizado = likes / (seguidores * videos)
    elif seguidores > 0:
        likesNormalizado = likes / seguidores
    else:
        likesNormalizado = 0

    # Seguidores
    if seguidores <= 300:
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
        "apariencia": 0.37,
        "engagement": 0.28,
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
        "puntaje_manual": score,
        "puntaje_manual_categoria": categoria
    }

SLIDER_LABELS = {
    'apariencia': {
        1: "No destaca - poco llamativa",
        2: "Básico - simple, sin esfuerzo",
        3: "Presentable - cuidada y correcta",
        4: "Agradable - buena presencia",
        5: "Muy atractivo - sobresaliente"
    },
    'engagement': {
        1: "No conecta - No genera empatía",
        2: "Limitado - poca interacción",
        3: "Interesante - a veces atrapa",
        4: "Carismático - cautiva natural",
        5: "Altamente carismático — Captura la atención de todos"
    },
    'calidad_contenido': {
        1: "Muy deficiente - sin calidad ni mensaje",
        2: "Limitado - aporta poco",
        3: "Correcto - entendible y algo útil",
        4: "Bueno - bien producido y valioso",
        5: "Excelente - profesional con gran aporte"
    },
    'eval_biografia': {
        1: 'No tiene Biografía',
        2: 'Deficiente (confusa, larga o sin propósito).',
        3: 'Aceptable (se entiende pero poco identidad).',
        4: 'Buena (clara, corta, con identidad).',
        5: 'Excelente (muy corta, clara y coherente).'
    },
    'eval_foto': {
        1: 'No tiene foto propia',
        2: 'Foto genérica, poco clara o de baja calidad',
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
    """
    Evalúa características generales del creador.
    Retorna un score normalizado 0–3, luego escalado a 0–5.
    """

    # ==== Edad ====
    if edad is None:
        e = 0
    elif edad < 18:
        return 0   # no apto
    elif edad < 20:
        e = 2
    elif edad <= 40:
        e = 3
    elif edad <= 60:
        e = 2
    else:
        e = 1

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


def evaluar_preferencias_habitos(
    exp_otras: dict,
    intereses: dict,
    tipo_contenido: dict,
    tiempo=None,
    freq_lives=None,
    intencion=None
):
    """
    Evalúa las preferencias y hábitos con base en:
    - Experiencia en otras plataformas (dict con conteos por plataforma)
    - Intereses (dict con booleanos)
    - Tipo de contenido (dict con booleanos)
    - Opcional: tiempo disponible, frecuencia de lives, intención de trabajo
    """

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
    elif tiempo < 4:
        t = 1
    elif tiempo <= 7:
        t = 2
    elif tiempo <= 10:
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
        "no estoy seguro": 1,
        "trabajo secundario": 2,
        "trabajo principal": 3
    }.get(str(intencion).lower(), 0)

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

def generar_mejoras_sugeridas_total(creador_id: int) -> str:
    def to_num(val):
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0

    datos = obtener_datos_mejoras_perfil_creador(creador_id)
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
            "🌟 ¡Vas por buen camino! Cada mejora te acerca más a tu objetivo.",
            "Recuerda: El éxito en TikTok vive de la constancia, autenticidad y adaptación."
        ]

    mensaje = []
    for seccion, items in sugerencias.items():
        mensaje.append(f"{seccion}")
        for item in items:
            mensaje.append(f"  • {item}")
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
        sugerencias.append("🔍 Analiza qué videos atraen nuevos seguidores y replica o mejora ese formato.")
        sugerencias.append("🌐 Promociona tu perfil en otras redes para atraer nuevos seguidores.")
    elif seguidores < 300:
        sugerencias.append("⏫ Prueba nuevas temáticas o formatos para atraer diferentes públicos.")
        sugerencias.append("🎯 Haz colaboraciones con otros creadores para aumentar tu alcance.")
    elif seguidores < 1000:
        sugerencias.append("🚀 Aprovecha los retos o tendencias populares para captar más seguidores.")
    else:
        sugerencias.append("✅ El crecimiento de tus seguidores es positivo, mantén la constancia y sigue innovando.")

    # Siguiendo
    if siguiendo >= seguidores or (seguidores > 0 and siguiendo >= (0.9 * seguidores)):
        sugerencias.append(
            "🔄 Prioriza la creación de contenido interesante y útil para tu audiencia, en lugar de enfocarte únicamente en conseguir seguidores por intercambio.")
    elif siguiendo < (0.3 * seguidores):
        sugerencias.append("🤝 Interactúa con otros creadores y participa en tendencias para aumentar tu visibilidad.")

    # Likes normalizados (engagement relativo)
    if likes_normalizado == 0:
        sugerencias.append(
            "⚡ Tus videos aún no generan interacción. Enfócate en contenidos que inviten a comentar, compartir y dar 'me gusta'.")
    elif likes_normalizado < 0.02:
        sugerencias.append(
            "📈 El nivel de interacción es bajo en relación a tus seguidores y videos. Prueba diferentes formatos y fomenta la participación en tus publicaciones.")
    elif likes_normalizado <= 0.05:
        sugerencias.append(
            "🎯 Tienes una interacción moderada. Identifica qué tipos de contenido generan más respuesta y potencia esos temas.")
    elif likes_normalizado <= 0.10:
        sugerencias.append(
            "🔥 Tu nivel de interacción es bueno. Mantén la constancia y busca sorprender para seguir creciendo.")
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

def mejorar_biografia_sugerida(bio_salida: str, eval_biografia: int) -> str:

    labels = {
        1: 'No tiene Biografía',
        2: 'Deficiente (confusa, larga o sin propósito).',
        3: 'Aceptable (se entiende pero poco identidad).',
        4: 'Buena (clara, corta, con identidad).',
        5: 'Excelente (muy corta, clara y coherente).'
    }

    markdown = []

    # Si NO hay biografía sugerida
    if not bio_salida or not str(bio_salida).strip():
        observacion = labels.get(eval_biografia, "Sin evaluación.")
        markdown.append(f"**Observación de la biografía:** {observacion}")
        if eval_biografia == 1:
            markdown.append("✍️ _No tienes biografía, agrega una descripción breve y atractiva que resuma tu identidad o intereses._")
        elif eval_biografia == 2:
            markdown.append("⚠️ _Tu biografía actual es confusa, extensa o sin propósito claro. Reescríbela para que sea corta, directa y comunique quién eres o qué ofreces._")
        elif eval_biografia == 3:
            markdown.append("🔄 _La biografía es aceptable pero puedes reforzar tu identidad o mensaje. Agrega palabras clave, emojis o detalles que te diferencien._")
        elif eval_biografia == 4:
            markdown.append("👍 _Tu biografía es buena, pero puedes pulirla para ser aún más memorable o coherente con tu marca personal._")
        elif eval_biografia == 5:
            markdown.append("🌟 _¡Excelente biografía! Es corta, clara y coherente. Mantén ese estilo._")
        return "\n".join(markdown)

    # Si hay biografía sugerida (texto plano), mostrar solo evaluación automática
    markdown.append(f"**Biografía sugerida:**\n{bio_salida}")

    recomendaciones = []
    if len(bio_salida) > 120:
        recomendaciones.append("⚠️ La biografía es algo extensa. Intenta resumirla para que sea más fácil de leer y recordar.")
    if len(bio_salida.split()) < 6:
        recomendaciones.append("🔎 La biografía es muy corta. Puedes agregar algún detalle extra para que tu perfil sea más atractivo.")
    if not any(char in bio_salida for char in "😊🌟✨💡🔥🎯❤️"):
        recomendaciones.append("💡 Considera agregar un emoji para darle más personalidad y atraer la atención.")
    if not bio_salida[0].isupper():
        recomendaciones.append("✍️ Comienza la biografía con mayúscula para mejorar la presentación.")
    if not "." in bio_salida and not "," in bio_salida:
        recomendaciones.append("📝 Puedes separar ideas usando puntos o comas para una mejor lectura.")

    if recomendaciones:
        markdown.append("\n**Recomendación de mejora:**")
        markdown.extend(recomendaciones)

    return "\n".join(markdown)

def mejoras_sugeridas_cualitativa(
    apariencia=0,
    engagement=0,
    calidad_contenido=0,
    eval_foto=0,
    eval_biografia=0,
    metadata_videos=0,
    biografia_sugerida=""
):

    SLIDER_LABELS = {
        'apariencia': {
            1: "No destaca - poco llamativa",
            2: "Básico - simple, sin esfuerzo",
            3: "Presentable - cuidada y correcta",
            4: "Agradable - buena presencia",
            5: "Muy atractivo - sobresaliente"
        },
        'engagement': {
            1: "No conecta - No genera empatía",
            2: "Limitado - poca interacción",
            3: "Interesante - a veces atrapa",
            4: "Carismático - cautiva natural",
            5: "Altamente carismático — Captura la atención de todos"
        },
        'calidad_contenido': {
            1: "Muy deficiente o son videos no propios",
            2: "Limitado - aporta poco",
            3: "Correcto - entendible y algo útil",
            4: "Bueno - bien producido y valioso",
            5: "Excelente - profesional con gran aporte"
        },
        'eval_biografia': {
            1: 'No tiene Biografía',
            2: 'Deficiente (confusa, larga o sin propósito).',
            3: 'Aceptable (se entiende pero poco identidad).',
            4: 'Buena (clara, corta, con identidad).',
            5: 'Excelente (muy corta, clara y coherente).'
        },
        'eval_foto': {
            1: 'No tiene foto propia',
            2: 'Foto genérica, poco clara o de baja calidad',
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

    def label(section, value):
        try:
            v = int(round(to_num(value)))
            return SLIDER_LABELS.get(section, {}).get(v, "No evaluado")
        except Exception:
            return "No evaluado"

    sugerencias = []
    apariencia = to_num(apariencia)
    engagement = to_num(engagement)
    calidad_contenido = to_num(calidad_contenido)
    eval_foto = to_num(eval_foto)
    eval_biografia = to_num(eval_biografia)
    metadata_videos = to_num(metadata_videos)

    sugerencias.append(f"🧑‍🎤 Apariencia en cámara: {label('apariencia', apariencia)}")
    sugerencias.append(f"🤝 Engagement: {label('engagement', engagement)}")
    sugerencias.append(f"🎬 Calidad del contenido: {label('calidad_contenido', calidad_contenido)}")
    sugerencias.append(f"🖼️ Foto de perfil: {label('eval_foto', eval_foto)}")
    sugerencias.append(f"📖 Biografía: {label('eval_biografia', eval_biografia)}")
    sugerencias.append(f"🏷️ Metadata videos: {label('metadata_videos', metadata_videos)}")

    if apariencia < 3:
        sugerencias.append("✨ Mejora tu presentación en cámara: cuida la luz, vestuario y ambiente.")
    if engagement < 3:
        sugerencias.append("🤝 Interactúa más con tus seguidores: responde, haz preguntas y usa llamados a la acción.")
    if calidad_contenido < 3:
        sugerencias.append("🎬 Trabaja en la creatividad y edición de tus videos para hacerlos más atractivos.")
    if eval_foto < 3:
        sugerencias.append("🖼️ Cambia tu foto de perfil por una más profesional y llamativa.")
    if metadata_videos < 3:
        sugerencias.append("📌 Usa hashtags y títulos relevantes para mejorar el alcance.")

    # ---- SUGERENCIA DE BIOGRAFÍA ----
    bio_limpia = mejorar_biografia_sugerida(biografia_sugerida, eval_biografia)
    if bio_limpia:
        sugerencias.append(f"📝 Sugerencia de biografía:\n{bio_limpia}")

    return sugerencias

def mejoras_sugeridas_datos_generales(edad, genero, idiomas, estudios, pais=None, actividad_actual=None):

    sugerencias = []

    # ==== Edad ====
    if edad is None:
        sugerencias.append("🔎 Completa tu edad para mejorar tu perfil.")
    elif edad < 18:
        sugerencias.append("🚫 Debes ser mayor de edad para participar como creador.")
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
    sugerencias.append(f"\n📊 **Puntaje general**: {puntaje} / 5 — Categoría: {categoria}")

    # Mensaje motivacional según categoría
    if categoria == "No apto":
        sugerencias.append("❌ Necesitas completar o mejorar tus datos personales para avanzar como creador.")
    elif categoria == "Muy bajo":
        sugerencias.append("⚠️ Tu perfil personal es débil, enfócate en mejorar formación, idiomas o disponibilidad.")
    elif categoria == "Bajo":
        sugerencias.append("🔧 Hay margen de mejora, potencia tus estudios, idiomas y actividad profesional.")
    elif categoria == "Medio":
        sugerencias.append("👍 Vas por buen camino, sigue reforzando tu perfil y aprovecha tus fortalezas.")
    elif categoria == "Alto":
        sugerencias.append("🌟 Tu perfil es muy sólido, busca colaboraciones y oportunidades premium.")
    elif categoria == "Excelente":
        sugerencias.append("🏆 ¡Perfil excelente! Aprovecha tu potencial para liderar proyectos y campañas.")

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
            "Esto puede dificultar tu adaptación. Te recomendamos explorar y analizar lo que hacen los creadores exitosos en TikTok y otras redes sociales, para entender tendencias y formatos populares."
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
        if tiempo_float < 4:
            sugerencias_habitos.append(
                "⏳ Solo cuentas con poco tiempo disponible para crear contenido. "
                "Esto limita tu constancia y crecimiento. Planifica bien tus sesiones y opta por videos cortos y de calidad."
            )
        elif tiempo_float <= 10:
            sugerencias_habitos.append("🕒 Puedes mantener una frecuencia regular y experimentar con nuevos formatos.")
        else:
            sugerencias_habitos.append("🔄 Con mucha disponibilidad, aprovecha para colaborar y mejorar tu producción.")

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
                "🔍 No tienes clara tu intención como creador. "
                "Define tus metas (diversión, aprendizaje, trabajo, ingresos) para enfocar tu esfuerzo y medir tu progreso."
            )
        elif intencion_str == "trabajo secundario":
            sugerencias_habitos.append("💼 Saca el máximo provecho al tiempo disponible y evalúa su potencial como actividad principal.")
        elif intencion_str == "trabajo principal":
            sugerencias_habitos.append("🏆 Mantén la disciplina y profesionalismo para consolidar tu presencia.")

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
    total_redondeado = round(total, 2)

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

def evaluar_potencial_creador(creador_id, score_cualitativa: float):
    """
    """
    try:
        # 1. Obtener métricas del creador
        data_dict = obtener_datos_estadisticas_perfil_creador(creador_id)
        if not data_dict:
            return {"error": "No se encontraron métricas para el creador."}

        # 2. Calcular score estadístico
        score_estadistica = evaluar_estadisticas(
            seguidores=data_dict.get("seguidores"),
            siguiendo=data_dict.get("siguiendo"),
            videos=data_dict.get("videos"),
            likes=data_dict.get("likes"),
            duracion=data_dict.get("duracion_emisiones")
        )

        # 3. Calcular total ponderado
        potencial_estimado = round(score_estadistica * 0.3 + score_cualitativa * 0.7, 2)

        # 4. Clasificación en texto
        if potencial_estimado >= 4.0:
            nivel = "Alto potencial"
        elif potencial_estimado >= 3.0:
            nivel = "Potencial medio"
        elif potencial_estimado >= 2.0:
            nivel = "Potencial bajo"
        elif potencial_estimado >= 1.0:
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
