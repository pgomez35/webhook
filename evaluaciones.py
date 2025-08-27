def generar_reporte_completo(cualitativa: dict, creador_id: int) -> str:
    """
    Genera un reporte completo de un creador:
    - Evaluación cualitativa (con etiquetas y descripciones)
    - Evaluación estadística (valor, categoría y recomendaciones)
    """

    # --- Etiquetas cualitativas ---
    labels_cualitativas = {
        "apariencia": {
            1: "❌ No destaca — Apariencia poco llamativa",
            2: "🟡 Presentable — Imagen cuidada, pero neutra",
            3: "🟢 Agradable — Buena presencia, transmite bien",
            4: "✨ Muy atractivo — Impacta visualmente, destaca",
            5: "🌟 Excepcional — Imán visual, realmente impacta"
        },
        "engagement": {  # Carisma
            1: "❌ No conecta — No genera empatía",
            2: "🟡 Algo interesante — Tiene algo que atrapa",
            3: "🟢 Muy carismático — Cautiva y es natural al expresarse",
            4: "✨ Tiene chispa — Brilla con espontaneidad y energía",
            5: "🌟 Altamente carismático — Captura la atención de todos"
        },
        "calidad_contenido": {  # unión de calidad + contenido
            1: "❌ Mala calidad — Problemas graves de imagen, sonido o contenido",
            2: "🟡 Aceptable — Se entiende, pero puede mejorar",
            3: "🟢 Buena producción — Nítido, bien grabado, aporta valor",
            4: "✨ Excelente — Profesional, creativo y atractivo",
            5: "🌟 Sobresaliente — Muy original, impactante y cautivador"
        },
        "foto": {
            1: "❌ No tiene foto propia",
            2: "🟡 Foto genérica, poco clara o de baja calidad",
            3: "🟢 Buena foto personal",
            4: "✨ Foto muy buena, bien representado",
            5: "🌟 Foto excelente, muy profesional y atractiva"
        },
        "biografia": {
            1: "❌ Muy mala (inconexa, sin sentido).",
            2: "🟡 Deficiente (confusa, larga o sin propósito).",
            3: "🟢 Aceptable (se entiende pero poca identidad).",
            4: "✨ Buena (clara, corta, con identidad).",
            5: "🌟 Excelente (muy corta, clara y coherente)."
        },
        "metadata_videos": {
            1: "❌ Muy malos (hashtags y títulos incoherentes, sin sentido, no describen el video).",
            2: "🟡 Deficientes (hashtags y títulos poco claros).",
            3: "🟢 Aceptables (comprensibles pero poco atractivos).",
            4: "✨ Buenos (claros, alineados con el video).",
            5: "🌟 Excelentes (claros, breves, llamativos y atrapan al público)."
        }
    }

    # --- Obtener estadísticas ---
    estadisticas = obtener_datos_mejoras_perfil_creador(creador_id)

    # --- Evaluación cualitativa ---
    reporte = ["💡 Evaluación cualitativa:"]
    for key, valor in cualitativa.items():
        puntaje = min(max(valor,1),5)
        descripcion = labels_cualitativas.get(key, {}).get(puntaje, "❓ Sin etiqueta")
        reporte.append(f"  • {descripcion}")

    # --- Evaluación estadística ---
    reporte.append("\n📊 Evaluación estadística:")
    if estadisticas:
        # Categorizar indicadores
        seguidores = estadisticas.get("seguidores",0)
        siguiendo = estadisticas.get("siguiendo",0)
        videos = estadisticas.get("videos",0)
        likes = estadisticas.get("likes",0)
        duracion = estadisticas.get("duracion_emisiones",0)

        # Función auxiliar para categorizar
        def categoria_valor(valor, niveles):
            for label, rango in niveles.items():
                if rango[0] <= valor <= rango[1]:
                    return label
            return "Desconocido"

        niveles_seguidores = {"Malo": (0,49), "Regular": (50,299), "Bueno": (300,999), "Excelente": (1000,9999999)}
        niveles_videos = {"Malo": (0,9), "Regular": (10,20), "Bueno": (21,40), "Excelente": (41,9999)}
        niveles_likes = {"Malo": (0,0.02), "Regular": (0.02,0.05), "Bueno": (0.05,0.10), "Excelente": (0.10,1)}
        niveles_duracion = {"Malo": (0,19), "Regular": (20,89), "Bueno": (90,179), "Excelente": (180,9999)}

        likes_norm = likes / (seguidores*videos) if seguidores>0 and videos>0 else (likes/seguidores if seguidores>0 else 0)

        detalle = {
            "seguidores": f"Seguidores: {seguidores} → {categoria_valor(seguidores,niveles_seguidores)}",
            "videos": f"Videos: {videos} → {categoria_valor(videos,niveles_videos)}",
            "likes": f"Likes normalizados: {round(likes_norm,3)} → {categoria_valor(likes_norm,niveles_likes)}",
            "duracion": f"Días activo: {duracion} → {categoria_valor(duracion,niveles_duracion)}"
        }

        # Score global ponderado
        score_global = (categoria_valor(seguidores,niveles_seguidores) in ["Malo","Regular"])*1 + \
                       (categoria_valor(videos,niveles_videos) in ["Malo","Regular"])*1 + \
                       (categoria_valor(likes_norm,niveles_likes) in ["Malo","Regular"])*1 + \
                       (categoria_valor(duracion,niveles_duracion) in ["Malo","Regular"])*1
        score_global_text = f"Score global: {score_global}/4"

        for k,v in detalle.items():
            reporte.append(f"  • {v}")
            if "Malo" in v or "Regular" in v:
                if "seguidores" in k:
                    reporte.append("    - Incrementa tus seguidores mediante colaboraciones o estrategias de crecimiento.")
                elif "videos" in k:
                    reporte.append("    - Publica más videos de manera consistente.")
                elif "likes" in k:
                    reporte.append("    - Mejora el contenido para aumentar el engagement.")
                elif "duracion" in k:
                    reporte.append("    - Mantente activo de forma constante en la plataforma.")
    else:
        reporte.append("  ℹ️ No hay estadísticas disponibles, recomendaciones basadas solo en evaluación cualitativa.")

    # --- Mensaje final ---
    reporte.append("\n✨ Mensaje final: 🌟 ¡Vas por buen camino! Cada mejora te acerca más a tu objetivo.")

    return "\n".join(reporte)

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
    metadata_videos: float = 0,
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


def diagnostico_perfil_creador(creador_id: int) -> str:
    """
    Genera un diagnóstico integral del perfil del creador,
    evaluando estadísticas, cualidades, datos personales y hábitos.
    """

    # 🔹 Obtener datos desde la BD o API
    datos = obtener_datos_mejoras_perfil_creador(creador_id)

    diagnostico = {
        "📊 Estadísticas": [],
        "💡 Cualitativo": [],
        "🧑‍🎓 Datos personales": [],
        "📅 Hábitos y preferencias": [],
    }

    # -------------------------
    # 📊 Estadísticas
    # -------------------------
    seguidores = datos.get("seguidores", 0)
    siguiendo = datos.get("siguiendo", 0)
    likes = datos.get("likes", 0)
    videos = datos.get("videos", 0)
    duracion = datos.get("duracion_emisiones", 0)

    diagnostico["📊 Estadísticas"].append(f"👥 Seguidores: {seguidores}")
    diagnostico["📊 Estadísticas"].append(f"➡️ Siguiendo: {siguiendo}")
    diagnostico["📊 Estadísticas"].append(f"👍 Likes: {likes}")
    diagnostico["📊 Estadísticas"].append(f"🎥 Videos: {videos}")
    diagnostico["📊 Estadísticas"].append(f"⏳ Días activo: {duracion}")

    if seguidores < 100:
        diagnostico["📊 Estadísticas"].append("⚠️ Nivel bajo de seguidores.")
    if likes < 200:
        diagnostico["📊 Estadísticas"].append("⚠️ Poca interacción (likes bajos).")
    if videos < 5:
        diagnostico["📊 Estadísticas"].append("⚠️ Falta constancia en publicaciones.")

    # -------------------------
    # 💡 Cualitativo
    # -------------------------
    apariencia = datos.get("apariencia", 0)
    engagement = datos.get("engagement", 0)
    calidad = datos.get("calidad_contenido", 0)
    eval_foto = datos.get("eval_foto", 0)
    eval_bio = datos.get("eval_biografia", 0)

    diagnostico["💡 Cualitativo"].append(f"🧑‍🎤 Apariencia en cámara: {apariencia}/5")
    diagnostico["💡 Cualitativo"].append(f"🤝 Engagement: {engagement}/5")
    diagnostico["💡 Cualitativo"].append(f"🎬 Calidad del contenido: {calidad}/5")
    diagnostico["💡 Cualitativo"].append(f"🖼️ Foto de perfil: {eval_foto}/5")
    diagnostico["💡 Cualitativo"].append(f"📖 Biografía: {eval_bio}/5")

    if engagement <= 2:
        diagnostico["💡 Cualitativo"].append("⚠️ Necesita mayor interacción con la audiencia.")
    if calidad <= 2:
        diagnostico["💡 Cualitativo"].append("⚠️ Contenido de baja calidad percibida.")

    # -------------------------
    # 🧑‍🎓 Datos personales
    # -------------------------
    idioma = datos.get("idioma", "No especificado")
    estudios = datos.get("estudios", "No especificado")
    actividad = datos.get("actividad_actual", "No especificado")

    diagnostico["🧑‍🎓 Datos personales"].append(f"🌐 Idioma: {idioma}")
    diagnostico["🧑‍🎓 Datos personales"].append(f"🎓 Estudios: {estudios}")
    diagnostico["🧑‍🎓 Datos personales"].append(f"💼 Actividad actual: {actividad}")

    if idioma.lower() != "español":
        diagnostico["🧑‍🎓 Datos personales"].append("🌍 Puede aprovechar público bilingüe.")
    if "estudiante" in actividad.lower():
        diagnostico["🧑‍🎓 Datos personales"].append("📘 Puede aprovechar su etapa de formación para generar contenido educativo.")

    # -------------------------
    # 📅 Hábitos y preferencias
    # -------------------------
    tiempo = datos.get("tiempo_disponible", "No definido")
    frecuencia = datos.get("frecuencia_lives", "No definido")
    experiencia = datos.get("experiencia_otras_plataformas", "No definido")
    intereses = datos.get("intereses", "No definido")
    tipo_contenido = datos.get("tipo_contenido", "No definido")
    intencion = datos.get("intencion_trabajo", "No definido")

    diagnostico["📅 Hábitos y preferencias"].append(f"⌛ Tiempo disponible: {tiempo}")
    diagnostico["📅 Hábitos y preferencias"].append(f"📡 Frecuencia de lives: {frecuencia}")
    diagnostico["📅 Hábitos y preferencias"].append(f"🌍 Experiencia en otras plataformas: {experiencia}")
    diagnostico["📅 Hábitos y preferencias"].append(f"🎯 Intereses: {intereses}")
    diagnostico["📅 Hábitos y preferencias"].append(f"🎨 Tipo de contenido: {tipo_contenido}")
    diagnostico["📅 Hábitos y preferencias"].append(f"💼 Intención de trabajo: {intencion}")

    if frecuencia == "baja" or tiempo == "limitado":
        diagnostico["📅 Hábitos y preferencias"].append("⚠️ Tiempo de dedicación limitado.")
    if intencion.lower() in ["hobbie", "ocasional"]:
        diagnostico["📅 Hábitos y preferencias"].append("ℹ️ Perfil más recreativo que profesional.")

    # -------------------------
    # 📌 Formatear salida
    # -------------------------
    mensaje = ["📋 DIAGNÓSTICO DEL PERFIL\n"]
    for seccion, items in diagnostico.items():
        mensaje.append(seccion)
        for item in items:
            mensaje.append(f"  • {item}")
        mensaje.append("")  # Espacio entre secciones

    return "\n".join(mensaje)


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

from DataBase import *

def generar_mejoras_sugeridas_total(creador_id: int) -> str:
    """
    Genera sugerencias en base a:
    - Evaluación cualitativa
    - Estadísticas de la BD
    - Datos generales/personales
    - Hábitos y preferencias
    """

    # 🔹 Obtener datos completos desde la BD
    datos = obtener_datos_mejoras_perfil_creador(creador_id)

    # Inicializar sugerencias
    sugerencias = {
        "🚀 Recomendaciones generales": [],
        "💡 Mejora tu contenido": [],
        "📊 Mejora tus estadísticas": [],
        "👤 Perfil personal": [],
        "🔄 Hábitos y preferencias": []
    }

    # ==========================
    # 1. Evaluación cualitativa
    # ==========================
    if datos.get("apariencia", 0) < 3:
        sugerencias["💡 Mejora tu contenido"].append(
            "✨ Mejora tu presentación en cámara: cuida la luz, vestuario y ambiente."
        )
    if datos.get("engagement", 0) < 3:
        sugerencias["💡 Mejora tu contenido"].append(
            "🤝 Interactúa más con tus seguidores: responde, haz preguntas y usa llamados a la acción."
        )
    if datos.get("calidad_contenido", 0) < 3:
        sugerencias["💡 Mejora tu contenido"].append(
            "🎬 Trabaja en la creatividad y edición de tus videos para hacerlos más atractivos."
        )
    if datos.get("eval_foto", 0) < 3:
        sugerencias["💡 Mejora tu contenido"].append(
            "🖼️ Cambia tu foto de perfil por una más profesional y llamativa."
        )
    if datos.get("eval_biografia", 0) < 3:
        sugerencias["💡 Mejora tu contenido"].append(
            "📖 Optimiza tu biografía: sé claro, breve y destaca tu valor."
        )
    if datos.get("metadata_videos", 0) < 3:
        sugerencias["💡 Mejora tu contenido"].append(
            "📌 Usa hashtags y títulos relevantes para mejorar el alcance."
        )

        # --- Nueva integración con OpenAI para mejorar biografía ---
    bio_texto = datos.get("biografia")
    bio_score = datos.get("eval_biografia", 0)

    if bio_texto and 2 <= bio_score <= 4:
        resultado_bio = evaluar_y_mejorar_biografia(bio_texto, modelo="gpt-4")
        if resultado_bio:
            sugerencias["💡 Mejora tu contenido"].append(f"🤖 Evaluación automática de tu biografía:\n{resultado_bio}")

    # ==========================
    # 2. Evaluación estadística
    # ==========================
    if datos.get("seguidores") is not None:
        seguidores = datos.get("seguidores", 0)
        siguiendo = datos.get("siguiendo", 0)
        likes = datos.get("likes", 0)
        videos = datos.get("videos", 0)
        duracion = datos.get("duracion_emisiones", 0)

        sugerencias["📊 Mejora tus estadísticas"].append(
            f"📌 Estado actual → Seguidores: {seguidores}, Siguiendo: {siguiendo}, Likes: {likes}, Videos: {videos}, Días activo: {duracion}"
        )

        mejoras_existentes = False

        if seguidores < 50:
            sugerencias["📊 Mejora tus estadísticas"].append("👥 Consigue al menos 50 seguidores para empezar a destacar.")
            mejoras_existentes = True
        elif seguidores < 300:
            sugerencias["📊 Mejora tus estadísticas"].append("📈 Crea estrategias para superar los 300 seguidores.")
            mejoras_existentes = True
        elif seguidores < 1000:
            sugerencias["📊 Mejora tus estadísticas"].append("🚀 Potencia tu alcance para superar los 1000 seguidores.")
            mejoras_existentes = True

        if siguiendo >= seguidores or (seguidores > 0 and siguiendo >= (0.9 * seguidores)):
            sugerencias["📊 Mejora tus estadísticas"].append("⚖️ Evita seguir a tantas cuentas: muchas no devuelven el follow.")
            mejoras_existentes = True

        if likes < 200:
            sugerencias["📊 Mejora tus estadísticas"].append("👍 Crea más contenido viral o compartible para aumentar tus likes.")
            mejoras_existentes = True
        elif likes < 1000:
            sugerencias["📊 Mejora tus estadísticas"].append("🔥 Mantén la constancia para superar los 1000 likes.")
            mejoras_existentes = True

        if videos < 10:
            sugerencias["📊 Mejora tus estadísticas"].append("🎥 Publica más videos de forma constante (mínimo 10).")
            mejoras_existentes = True

        if duracion < 30:
            sugerencias["📊 Mejora tus estadísticas"].append("⏳ Mantente activo para mostrar consistencia.")
            mejoras_existentes = True

        if not mejoras_existentes:
            sugerencias["📊 Mejora tus estadísticas"].append("✅ Tienes buenos indicadores! Sigue activo y mantén tu rendimiento.")
    else:
        sugerencias["📊 Mejora tus estadísticas"].append("ℹ️ No hay estadísticas disponibles actualmente. Solo análisis cualitativo.")

    # ==========================
    # 3. Evaluación datos generales
    # ==========================
    generales = evaluar_datos_generales(
        edad=datos.get("edad"),
        genero=datos.get("genero"),
        idiomas=datos.get("idiomas"),
        estudios=datos.get("estudios"),
        pais=datos.get("pais"),
        actividad_actual=datos.get("actividad_actual")
    )

    if generales:
        sugerencias["👤 Perfil personal"].append(
            f"📌 Puntaje general: {generales['puntaje_general']} → {generales['puntaje_general_categoria']}"
        )
        if generales["puntaje_general"] < 2.5:
            sugerencias["👤 Perfil personal"].append("🔧 Refuerza tu perfil personal: idiomas, formación o disponibilidad.")

    # ==========================
    # 4. Evaluación hábitos y preferencias
    # ==========================
    habitos = evaluar_preferencias_habitos(
        exp_otras=datos.get("experiencia_otras_plataformas", {}),
        intereses=datos.get("intereses", {}),
        tipo_contenido=datos.get("tipo_contenido", {}),
        tiempo=datos.get("tiempo_disponible"),
        freq_lives=datos.get("frecuencia_lives"),
        intencion=datos.get("intencion_trabajo")
    )

    if habitos:
        sugerencias["🔄 Hábitos y preferencias"].append(
            f"📌 Puntaje hábitos: {habitos['puntaje_habitos']} → {habitos['puntaje_habitos_categoria']}"
        )
        if habitos["puntaje_habitos"] < 2.5:
            sugerencias["🔄 Hábitos y preferencias"].append("🔧 Ajusta tu disponibilidad y constancia en lives para mejorar resultados.")

    # ==========================
    # 5. Recomendaciones generales extra
    # ==========================
    seguidores = datos.get("seguidores", 0)
    if datos.get("engagement", 0) < 3 and seguidores < 300:
        sugerencias["🚀 Recomendaciones generales"].append("🔄 Mejora tu interacción y combina con estrategias de crecimiento.")
    if datos.get("calidad_contenido", 0) >= 4 and seguidores < 300:
        sugerencias["🚀 Recomendaciones generales"].append("✅ Tu contenido es bueno, ahora enfócate en difundirlo más.")

    # ==========================
    # 6. Limpieza final y salida
    # ==========================
    sugerencias = {k: v for k, v in sugerencias.items() if v}
    if sugerencias:
        sugerencias["✨ Mensaje final"] = ["🌟 ¡Vas por buen camino! Cada mejora te acerca más a tu objetivo."]

    mensaje = []
    for seccion, items in sugerencias.items():
        mensaje.append(f"{seccion}")
        for item in items:
            mensaje.append(f"  • {item}")
    return "\n".join(mensaje)



from openai import OpenAI
from dotenv import load_dotenv
import os

# Cargar variables de entorno
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

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


def generar_mejoras_sugeridas(cualitativa: dict, creador_id: int) -> str:
    """
    Genera sugerencias en base a métricas cualitativas (payload) y estadísticas (desde BD).
    Si no hay estadísticas, continúa solo con el análisis cualitativo.
    """

    # 🔹 Obtener estadísticas desde la BD
    estadisticas = obtener_datos_mejoras_perfil_creador(creador_id)

    # Inicializar sugerencias
    sugerencias = {
        "🚀 Recomendaciones generales": [],
        "💡 Mejora tu contenido": [],
        "📊 Mejora tus estadísticas": []
    }

    # --- Evaluación cualitativa ---
    if cualitativa.get("apariencia", 0) < 3:
        sugerencias["💡 Mejora tu contenido"].append(
            "✨ Mejora tu presentación en cámara: cuida la luz, vestuario y ambiente."
        )
    if cualitativa.get("engagement", 0) < 3:
        sugerencias["💡 Mejora tu contenido"].append(
            "🤝 Interactúa más con tus seguidores: responde, haz preguntas y usa llamados a la acción."
        )
    if cualitativa.get("calidad_contenido", 0) < 3:
        sugerencias["💡 Mejora tu contenido"].append(
            "🎬 Trabaja en la creatividad y edición de tus videos para hacerlos más atractivos."
        )
    if cualitativa.get("foto", 0) < 3:
        sugerencias["💡 Mejora tu contenido"].append(
            "🖼️ Cambia tu foto de perfil por una más profesional y llamativa."
        )
    if cualitativa.get("biografia", 0) < 3:
        sugerencias["💡 Mejora tu contenido"].append(
            "📖 Optimiza tu biografía: sé claro, breve y destaca tu valor."
        )
    if cualitativa.get("metadata_videos", 0) < 3:
        sugerencias["💡 Mejora tu contenido"].append(
            "📌 Usa hashtags y títulos relevantes para mejorar el alcance."
        )

    # --- Nueva integración con OpenAI para mejorar biografía ---
    bio_texto = estadisticas.get("biografia") if estadisticas else None
    bio_score = cualitativa.get("biografia", 0)

    if bio_texto and 2 <= bio_score <= 4:
        resultado_bio = evaluar_y_mejorar_biografia(bio_texto, modelo="gpt-4")
        if resultado_bio:
            sugerencias["💡 Mejora tu contenido"].append(f"🤖 Evaluación automática de tu biografía:\n{resultado_bio}")



    # --- Evaluación estadística ---
    if estadisticas:
        seguidores = estadisticas.get("seguidores", 0)
        siguiendo = estadisticas.get("siguiendo", 0)
        likes = estadisticas.get("likes", 0)
        videos = estadisticas.get("videos", 0)
        duracion = estadisticas.get("duracion_emisiones", 0)

        # Mostrar siempre los valores actuales
        sugerencias["📊 Mejora tus estadísticas"].append(
            f"📌 Estado actual → Seguidores: {seguidores}, Siguiendo: {siguiendo}, Likes: {likes}, Videos: {videos}, Días activo: {duracion}"
        )

        mejoras_existentes = False

        if seguidores < 50:
            sugerencias["📊 Mejora tus estadísticas"].append(
                "👥 Consigue al menos 50 seguidores para empezar a destacar."
            )
            mejoras_existentes = True
        elif seguidores < 300:
            sugerencias["📊 Mejora tus estadísticas"].append(
                "📈 Crea estrategias para superar los 300 seguidores."
            )
            mejoras_existentes = True
        elif seguidores < 1000:
            sugerencias["📊 Mejora tus estadísticas"].append(
                "🚀 Potencia tu alcance para superar los 1000 seguidores."
            )
            mejoras_existentes = True

        if siguiendo >= seguidores or (seguidores > 0 and siguiendo >= (0.9 * seguidores)):
            sugerencias["📊 Mejora tus estadísticas"].append(
                "⚖️ Evita seguir a tantas cuentas: muchas no devuelven el follow."
            )
            mejoras_existentes = True

        if likes < 200:
            sugerencias["📊 Mejora tus estadísticas"].append(
                "👍 Crea más contenido viral o compartible para aumentar tus likes."
            )
            mejoras_existentes = True
        elif likes < 1000:
            sugerencias["📊 Mejora tus estadísticas"].append(
                "🔥 Mantén la constancia para superar los 1000 likes."
            )
            mejoras_existentes = True

        if videos < 10:
            sugerencias["📊 Mejora tus estadísticas"].append(
                "🎥 Publica más videos de forma constante (mínimo 10)."
            )
            mejoras_existentes = True

        if duracion < 30:
            sugerencias["📊 Mejora tus estadísticas"].append(
                "⏳ Mantente activo para mostrar consistencia."
            )
            mejoras_existentes = True

        # Si no hay mejoras, agregar mensaje positivo
        if not mejoras_existentes:
            sugerencias["📊 Mejora tus estadísticas"].append(
                "✅ Tienes buenos indicadores! Sigue activo y mantén tu rendimiento."
            )

    else:
        # Opcional: mensaje cuando no hay estadísticas
        sugerencias["📊 Mejora tus estadísticas"].append(
            "ℹ️ No hay estadísticas disponibles actualmente. Las recomendaciones se basan solo en análisis cualitativo."
        )

    # --- Recomendaciones generales ---
    seguidores = estadisticas.get("seguidores", 0) if estadisticas else 0

    if cualitativa.get("engagement", 0) < 3 and seguidores < 300:
        sugerencias["🚀 Recomendaciones generales"].append(
            "🔄 Mejora tu interacción y combina con estrategias de crecimiento."
        )
    if cualitativa.get("calidad_contenido", 0) >= 4 and seguidores < 300:
        sugerencias["🚀 Recomendaciones generales"].append(
            "✅ Tu contenido es bueno, ahora enfócate en difundirlo más."
        )

    # --- Eliminar secciones vacías ---
    sugerencias = {k: v for k, v in sugerencias.items() if v}

    # --- Mensaje positivo final ---
    if sugerencias:
        sugerencias["✨ Mensaje final"] = ["🌟 ¡Vas por buen camino! Cada mejora te acerca más a tu objetivo."]

    # 🔹 Devolver como string formateado
    mensaje = []
    for seccion, items in sugerencias.items():
        mensaje.append(f"{seccion}")
        for item in items:
            mensaje.append(f"  • {item}")
    return "\n".join(mensaje)

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

def evaluar_total(cualitativa: dict, estadistica: dict, general: dict, habitos: dict):
    """
    Combina todos los puntajes en un puntaje total.
    """
    # Extraer los valores numéricos si vienen en dict
    cualitativa_score = (
        cualitativa.get("puntuacion_manual")
        if isinstance(cualitativa, dict) else cualitativa
    )
    estadistica_score = (
        estadistica.get("puntaje_estadistica")
        if isinstance(estadistica, dict) else estadistica
    )
    general_score = (
        general.get("puntaje_general")
        if isinstance(general, dict) else general
    )
    habitos_score = (
        habitos.get("puntaje_habitos")
        if isinstance(habitos, dict) else habitos
    )

    total = (
        (cualitativa_score or 0) * 0.50 +
        (estadistica_score or 0) * 0.25 +
        (general_score or 0) * 0.15 +
        (habitos_score or 0) * 0.10
    )

    total_redondeado = round(total, 2)

    # Determinar categoría proporcional (1-5)
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


def evaluar_total_(cualitativa, estadisticas, generales, preferencias_habitos):
    total = (
        cualitativa * 0.50 +
        estadisticas * 0.10 +
        generales * 0.20 +
        preferencias_habitos * 0.20
    )
    return round(total, 2)

# ==============================
# 🔎 Ejemplo con tus datos
# ==============================
# exp_otras = {'Otro': 7, 'TikTok': 1, 'Twitch': 0, 'YouTube': 0, 'Facebook': 0, 'LinkedIn': 0, 'Instagram': 0, 'Twitter/X': 0}
# intereses = {'arte': False, 'moda': True, 'bailes': True, 'cocina': False, 'gaming': False, 'musica': False, 'viajes': True, 'comedia': False,
#              'fitness': False, 'idiomas': False, 'lectura': False, 'deportes': True, 'noticias': False, 'politica': False, 'religion': False,
#              'educacion': False, 'fotografia': False, 'maquillaje': True, 'relaciones': True, 'tecnologia': False, 'salud_mental': False,
#              'emprendimiento': False}
# tipo_contenido = {'otro': False, 'humor': False, 'bailes': False, 'gaming': False, 'musica': False, 'ventas': False, 'charlas': True,
#                   'estudios': False, 'reaccion': False, 'religion': False, 'tutoriales': True, 'temas sociales': True, 'temas_sociales': False,
#                   'entretenimiento': False, 'música en vivo': True}
#
# p = evaluar_preferencias_habitos(exp_otras, intereses, tipo_contenido, tiempo=6, freq_lives=4, intencion="trabajo principal")
# print("Preferencias / Hábitos:", p)


# ==== CASOS DE PRUEBA ==== #

# ==== CASOS DE PRUEBA ==== #

# Aspirante 1 – principiante pero con buena actitud (bailes)
c1 = evaluar_cualitativa(apariencia=2, engagement=2, calidad_contenido=2, foto=2)
e1 = evaluar_estadisticas(seguidores=150, siguiendo=100, videos=15, likes=250, duracion=60)
g1 = evaluar_datos_generales(edad=20, genero="femenino", idiomas="espanol", estudios="universitario")
d1 = evaluar_preferencias_habitos(
    exp_otras={"TikTok": 1, "YouTube": 0, "Instagram": 0},
    intereses={"bailes": True, "moda": True, "gaming": False},
    tipo_contenido={"bailes": True},
    tiempo=3,
    freq_lives=2,
    intencion="trabajo secundario"
)
t1 = evaluar_total(c1, e1, g1, d1)

print("=== Aspirante 1 ===")
print("Cualitativa:", c1, "Estadísticas:", e1, "Generales:", g1, "Hábitos:", d1, "TOTAL:", t1, "\n")


# Aspirante 2 – creador versátil con muchos seguidores
c2 = evaluar_cualitativa(apariencia=3, engagement=3, calidad_contenido=3, foto=3, biografia=2)
e2 = evaluar_estadisticas(seguidores=1200, siguiendo=300, videos=40, likes=1500, duracion=120)
g2 = evaluar_datos_generales(edad=25, genero="masculino", idiomas=["espanol", "ingles"], estudios="universitario", pais="Mexico")
d2 = evaluar_preferencias_habitos(
    exp_otras={"TikTok": 2, "YouTube": 1, "Instagram": 1},
    intereses={"gaming": True, "musica": True, "viajes": True},
    tipo_contenido={"gaming": True, "música en vivo": True, "charlas": True},
    tiempo=6,
    freq_lives=4,
    intencion="trabajo principal"
)
t2 = evaluar_total(c2, e2, g2, d2)

print("=== Aspirante 2 ===")
print("Cualitativa:", c2, "Estadísticas:", e2, "Generales:", g2, "Hábitos:", d2, "TOTAL:", t2, "\n")


# Aspirante 3 – enfocado en ventas en vivo (penalización)
c3 = evaluar_cualitativa(apariencia=2, engagement=2, calidad_contenido=2, foto=2)
e3 = evaluar_estadisticas(seguidores=2000, siguiendo=500, videos=50, likes=600, duracion=30)
g3 = evaluar_datos_generales(edad=30, genero="femenino", idiomas="espanol", estudios="secundaria")
d3 = evaluar_preferencias_habitos(
    exp_otras={"Facebook": 3, "Instagram": 2},
    intereses={"ventas": True, "moda": True},
    tipo_contenido={"ventas en vivo": True},  # penalización
    tiempo=8,
    freq_lives=5,
    intencion="trabajo principal"
)
t3 = evaluar_total(c3, e3, g3, d3)

print("=== Aspirante 3 ===")
print("Cualitativa:", c3, "Estadísticas:", e3, "Generales:", g3, "Hábitos:", d3, "TOTAL:", t3, "\n")


# Aspirante 4 – muy débil, apenas comienza
c4 = evaluar_cualitativa(apariencia=1, engagement=0, calidad_contenido=1, foto=0)
e4 = evaluar_estadisticas(seguidores=30, siguiendo=10, videos=5, likes=50, duracion=15)
g4 = evaluar_datos_generales(edad=17, genero="otro", idiomas="espanol", estudios="secundaria")  # no apto por edad
d4 = evaluar_preferencias_habitos(
    exp_otras={"Otro": 0},
    intereses={"lectura": True},
    tipo_contenido={"lectura": True},
    tiempo=1,
    freq_lives=0,
    intencion="no estoy seguro"
)
t4 = evaluar_total(c4, e4, g4, d4)

print("=== Aspirante 4 ===")
print("Cualitativa:", c4, "Estadísticas:", e4, "Generales:", g4, "Hábitos:", d4, "TOTAL:", t4, "\n")





