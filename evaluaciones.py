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
    return round(score*(5/4), 2)

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
        "puntuacion_manual": score,
        "puntuacion_manual_categoria": categoria
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

    return round(score * (5/3), 2)


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

    return round(score*(5/3), 2)

def generar_mejoras_sugeridas(
        cualitativa: dict,
        estadisticas: dict
) -> dict:
    """
    Genera mejoras sugeridas en base a las métricas cualitativas y estadísticas.

    cualitativa: dict con claves ["apariencia", "engagement", "calidad_contenido", "foto", "biografia", "metadata_videos"]
    estadisticas: dict con claves ["seguidores", "siguiendo", "videos", "likes", "duracion"]

    return: dict con sugerencias agrupadas
    """
    sugerencias = {
        "cualitativa": [],
        "estadisticas": [],
        "general": []
    }

    # --- Evaluación cualitativa ---
    if cualitativa.get("apariencia", 0) < 3:
        sugerencias["cualitativa"].append("Mejorar presentación personal en cámara (luz, vestuario, ambiente).")
    if cualitativa.get("engagement", 0) < 3:
        sugerencias["cualitativa"].append("Hacer más llamados a la acción e interactuar con seguidores.")
    if cualitativa.get("calidad_contenido", 0) < 3:
        sugerencias["cualitativa"].append("Incrementar la creatividad y edición de los videos.")
    if cualitativa.get("foto", 0) < 3:
        sugerencias["cualitativa"].append("Actualizar la foto de perfil con una más profesional o atractiva.")
    if cualitativa.get("biografia", 0) < 3:
        sugerencias["cualitativa"].append("Optimizar la biografía: debe ser clara, breve y mostrar valor.")
    if cualitativa.get("metadata_videos", 0) < 3:
        sugerencias["cualitativa"].append("Usar hashtags y títulos más relevantes para aumentar alcance.")

    # --- Evaluación estadística ---
    seguidores = estadisticas.get("seguidores", 0)
    siguiendo = estadisticas.get("siguiendo", 0)
    likes = estadisticas.get("likes", 0)
    videos = estadisticas.get("videos", 0)
    duracion = estadisticas.get("duracion", 0)

    if seguidores < 50:
        sugerencias["estadisticas"].append("Necesita conseguir al menos 50 seguidores para ser considerado apto.")
    elif seguidores < 300:
        sugerencias["estadisticas"].append("Trabajar en estrategias de crecimiento para superar los 300 seguidores.")
    elif seguidores < 1000:
        sugerencias["estadisticas"].append("Potenciar el alcance para pasar de bueno a muy bueno (+1000 seguidores).")

    # Regla de balance seguidores vs siguiendo (independiente de duración)
    if siguiendo >= seguidores or siguiendo >= (0.9 * seguidores):
        sugerencias["estadisticas"].append(
            "Se recomienda dejar de seguir tantas cuentas, ya que probablemente no devuelven el seguimiento en igual proporción."
        )

    if likes < 200:
        sugerencias["estadisticas"].append("Incrementar likes con contenido más viral o compartible.")
    elif likes < 1000:
        sugerencias["estadisticas"].append("Mantener la consistencia para llegar a +1000 likes.")

    if videos < 10:
        sugerencias["estadisticas"].append("Publicar más videos de forma constante (mínimo 10).")

    if duracion < 30:
        sugerencias["estadisticas"].append("Mantenerse activo al menos un mes para evaluar consistencia.")


    # --- Sugerencias generales ---
    if cualitativa.get("engagement", 0) < 3 and seguidores < 300:
        sugerencias["general"].append("Combinar mejoras en interacción y crecimiento de seguidores.")
    if cualitativa.get("calidad_contenido", 0) >= 4 and seguidores < 300:
        sugerencias["general"].append("El contenido es bueno, falta difusión y estrategia de crecimiento.")

    return sugerencias

def evaluar_total(cualitativa, estadisticas, generales, preferencias_habitos):
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





