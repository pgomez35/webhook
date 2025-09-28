from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import os, json
from dotenv import load_dotenv
from enviar_msg_wp import enviar_plantilla_generica, enviar_mensaje_texto_simple,enviar_boton_iniciar_Completa
from main import guardar_mensaje
from utils import *
from rapidfuzz import process, fuzz
import unicodedata
import traceback

import psycopg2

load_dotenv()

# Configuración
TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_ID")
INTERNAL_DATABASE_URL = os.getenv("INTERNAL_DATABASE_URL")  # 🔹 corregido nombre

router = APIRouter()

# Estado del flujo en memoria
usuarios_flujo = {}    # { numero: paso_actual }
respuestas = {}        # { numero: {campo: valor} }
usuarios_temp = {}

# ============================
# OPCIONES
# ============================
tiposContenido_opciones = {
    "1": ["Bailes"],
    "2": ["Charlas"],
    "3": ["Gaming", "streams de videojuegos"],
    "4": ["Tutoriales"],
    "5": ["Entretenimiento"],
    "6": ["Humor"],
    "7": ["Música en vivo"],
    "8": ["Reacción a videos"],
    "9": ["Religión"],
    "10": ["Temas sociales", "debates", "foros"],
    "11": ["Estudios/tareas"],
    "12": ["Ventas en vivo"],
    "13": ["Otro"]
}

interesesOpciones_opciones = {
    "1": ["Deportes"],
    "2": ["Moda"],
    "3": ["Maquillaje"],
    "4": ["Cocina"],
    "5": ["Fitness"],
    "6": ["Música"],
    "7": ["Bailes"],
    "8": ["Gaming"],
    "9": ["Lectura"],
    "10": ["Salud mental"],
    "11": ["Comedia"],
    "12": ["Religión"],
    "13": ["Política"],
    "14": ["Emprendimiento"],
    "15": ["Viajes"],
    "16": ["Idiomas"],
    "17": ["Educación"],
    "18": ["Noticias"],
    "19": ["Relaciones"],
    "20": ["Arte"],
    "21": ["Tecnología"],
    "22": ["Fotografía"],
    "23": ["Otro"]
}


mapa_paises = {
    "1": "argentina",
    "2": "bolivia",
    "3": "chile",
    "4": "colombia",
    "5": "costarica",
    "6": "cuba",
    "7": "ecuador",
    "8": "elsalvador",
    "9": "guatemala",
    "10": "honduras",
    "11": "mexico",
    "12": "nicaragua",
    "13": "panama",
    "14": "paraguay",
    "15": "peru",
    "16": "puertorico",
    "17": "dominicana",
    "18": "uruguay",
    "19": "venezuela"
}

# === Diccionario de ciudades por país (Latinoamérica) ===
ciudades_por_pais = {
    "argentina": ["Buenos Aires", "Córdoba", "Rosario", "Mendoza", "La Plata",
                  "San Miguel de Tucumán", "Mar del Plata", "Salta", "Santa Fe", "San Juan"],
    "bolivia": ["La Paz", "Santa Cruz de la Sierra", "Cochabamba", "Sucre", "Oruro",
                "Potosí", "Tarija", "El Alto", "Trinidad", "Cobija"],
    "chile": ["Santiago", "Valparaíso", "Concepción", "La Serena", "Antofagasta",
              "Temuco", "Rancagua", "Talca", "Arica", "Chillán"],
    "colombia": ["Bogotá", "Medellín", "Cali", "Barranquilla", "Cartagena",
                 "Bucaramanga", "Pereira", "Santa Marta", "Ibagué", "Cúcuta"],
    "costarica": ["San José", "Alajuela", "Cartago", "Heredia", "Liberia",
                  "Puntarenas", "Limón", "San Carlos", "Desamparados", "San Ramón"],
    "cuba": ["La Habana", "Santiago de Cuba", "Camagüey", "Holguín", "Guantánamo",
             "Santa Clara", "Bayamo", "Pinar del Río", "Cienfuegos", "Matanzas"],
    "ecuador": ["Quito", "Guayaquil", "Cuenca", "Santo Domingo", "Machala",
                "Manta", "Portoviejo", "Ambato", "Riobamba", "Esmeraldas"],
    "elsalvador": ["San Salvador", "Santa Ana", "San Miguel", "Soyapango", "Mejicanos",
                   "Santa Tecla", "Apopa", "Delgado", "Usulután", "Sonsonate"],
    "guatemala": ["Ciudad de Guatemala", "Mixco", "Villa Nueva", "Quetzaltenango",
                  "Escuintla", "San Juan Sacatepéquez", "Villa Canales", "Chinautla",
                  "Chimaltenango", "Amatitlán"],
    "honduras": ["Tegucigalpa", "San Pedro Sula", "Choloma", "La Ceiba", "El Progreso",
                 "Comayagua", "Puerto Cortés", "Choluteca", "Danlí", "Juticalpa"],
    "mexico": ["Ciudad de México", "Guadalajara", "Monterrey", "Puebla", "Tijuana",
               "León", "Juárez", "Torreón", "Querétaro", "Mérida"],
    "nicaragua": ["Managua", "León", "Masaya", "Chinandega", "Matagalpa",
                  "Estelí", "Granada", "Jinotega", "Bluefields", "Carazo"],
    "panama": ["Ciudad de Panamá", "San Miguelito", "Colón", "David", "La Chorrera",
               "Santiago", "Chitré", "Penonomé", "Aguadulce", "Arraiján"],
    "paraguay": ["Asunción", "Ciudad del Este", "Encarnación", "San Lorenzo", "Luque",
                 "Capiatá", "Fernando de la Mora", "Lambaré", "Mariano Roque Alonso", "Itauguá"],
    "peru": ["Lima", "Arequipa", "Trujillo", "Chiclayo", "Piura",
             "Iquitos", "Cusco", "Chimbote", "Huancayo", "Tacna"],
    "puertorico": ["San Juan", "Bayamón", "Carolina", "Ponce", "Caguas",
                   "Guaynabo", "Mayagüez", "Trujillo Alto", "Arecibo", "Fajardo"],
    "dominicana": ["Santo Domingo", "Santiago de los Caballeros", "La Romana",
                   "San Pedro de Macorís", "San Francisco de Macorís", "Puerto Plata",
                   "La Vega", "Higüey", "Moca", "Bonao"],
    "uruguay": ["Montevideo", "Salto", "Paysandú", "Las Piedras", "Rivera",
                "Maldonado", "Tacuarembó", "Melo", "Mercedes", "Artigas"],
    "venezuela": ["Caracas", "Maracaibo", "Valencia", "Barquisimeto", "Maracay",
                  "Ciudad Guayana", "San Cristóbal", "Maturín", "Ciudad Bolívar", "Cumaná"]
}

# ============================
# PREGUNTAS
# ============================
preguntas = {
    1: "📌 ¿Cuál es tu nombre completo?",
    2: "📌 ¿Cuál es tu edad?",
    3: "📌 Género:\n"
       "1️⃣ Masculino\n"
       "2️⃣ Femenino\n"
       "3️⃣ Otro\n"
       "4️⃣ Prefiero no decir",
    4: "📌 País (elige de la lista o escribe el tuyo si no aparece):\n"
       "1️⃣ Argentina\n"
       "2️⃣ Bolivia\n"
       "3️⃣ Chile\n"
       "4️⃣ Colombia\n"
       "5️⃣ Costa Rica\n"
       "6️⃣ Cuba\n"
       "7️⃣ Ecuador\n"
       "8️⃣ El Salvador\n"
       "9️⃣ Guatemala\n"
       "🔟 Honduras\n"
       "1️⃣1️⃣ México\n"
       "1️⃣2️⃣ Nicaragua\n"
       "1️⃣3️⃣ Panamá\n"
       "1️⃣4️⃣ Paraguay\n"
       "1️⃣5️⃣ Perú\n"
       "1️⃣6️⃣ Puerto Rico\n"
       "1️⃣7️⃣ República Dominicana\n"
       "1️⃣8️⃣ Uruguay\n"
       "1️⃣9️⃣ Venezuela\n"
       "2️⃣0️⃣ Otro (escribe tu país)",
    5: "📌 Ciudad principal (escríbela en texto)",
    6: "📌 Nivel de estudios:\n"
       "1️⃣ Ninguno\n"
       "2️⃣ Primaria completa\n"
       "3️⃣ Secundaria completa\n"
       "4️⃣ Técnico o tecnólogo\n"
       "5️⃣ Universitario incompleto\n"
       "6️⃣ Universitario completo\n"
       "7️⃣ Postgrado / Especialización\n"
       "8️⃣ Autodidacta / Formación no formal\n"
       "9️⃣ Otro (especificar)",
    7: "📌 Idioma principal:\n"
       "1️⃣ Español\n"
       "2️⃣ Inglés\n"
       "3️⃣ Portugués\n"
       "4️⃣ Francés\n"
       "5️⃣ Italiano\n"
       "6️⃣ Alemán\n"
       "7️⃣ Otro",
    8: "📌 Actividad actual:\n"
       "1️⃣ Estudia tiempo completo\n"
       "2️⃣ Estudia medio tiempo\n"
       "3️⃣ Trabaja tiempo completo\n"
       "4️⃣ Trabaja medio tiempo\n"
       "5️⃣ Buscando empleo\n"
       "6️⃣ Emprendiendo\n"
       "7️⃣ Disponible tiempo completo\n"
       "8️⃣ Otro",
    # 🔹 Hábitos
    9: "📌 ¿Cuál es tu horario preferido para hacer lives?\n"
       "1️⃣ Mañana (6am–12pm)\n"
       "2️⃣ Tarde (12pm–6pm)\n"
       "3️⃣ Noche (6pm–12am)\n"
       "4️⃣ Madrugada (12am–6am)\n"
       "5️⃣ Variable\n"
       "6️⃣ Otro",
    10: "📌 ¿Cuál es tu intención principal en la plataforma?\n"
        "1️⃣ Trabajo principal\n"
        "2️⃣ Trabajo secundario\n"
        "3️⃣ Hobby, pero me gustaría profesionalizarlo\n"
        "4️⃣ Diversión, sin intención profesional\n"
        "5️⃣ No estoy seguro",
    11: "📌 ¿Cuántos lives puedes hacer por semana?",
    12: "📌 ¿Cuántas horas a la semana tienes disponibles para crear contenido?",

    # 🔹 Experiencia en plataformas
    13: "📌 ¿Cuántos meses de experiencia tienes en TikTok?",
    14: "📌 ¿Cuántos meses de experiencia tienes en YouTube?",
    15: "📌 ¿Cuántos meses de experiencia tienes en Instagram?",

    # 16: "📌 ¿Qué tipo de contenido creas?\n"
    #     "Responde con los números, separados por coma.\n\n"
    #     "1️⃣ Entretenimiento (entretenimiento general, humor, música en vivo, bailes, reacción a videos)\n"
    #     "2️⃣ Gaming\n"
    #     "3️⃣ Educación (tutoriales, charlas, estudios / tareas)\n"
    #     "4️⃣ Sociedad y espiritualidad (temas sociales, religión y espiritualidad)\n"
    #     "5️⃣ Ventas en vivo\n"
    #     "6️⃣ Otros",

    # # 🔹 Intereses
    # 17: (
    #     "📌 ¿Cuáles son tus intereses?\n"
    #     "Responde con los números, separados por coma.\n\n"
    #     "1️⃣ Estilo vida (deportes, moda, cocina, maquillaje, fitness, viajes, relaciones)\n"
    #     "2️⃣ Arte & Cultura (música, bailes, arte, fotografía, lectura, comedia)\n"
    #     "3️⃣ Sociedad (salud mental, religión, política, noticias))\n"
    #     "4️⃣ Educación (idiomas, emprendimiento, educación)\n"
    #     "5️⃣ Tecno/Gaming(tecnología, gaming)\n"
    #     "6️⃣ Otros"
    # )

# 🔹 Tipo de Contenido
16: (
    "📌 ¿Qué tipo de contenido creas?\n"
    "Responde con los números, separados por coma.\n\n"
    "1️⃣ Bailes   |  2️⃣ Charlas   |  3️⃣ Gaming\n"
    "4️⃣ Tutoriales   |  5️⃣ Entretenimiento   |  6️⃣ Humor\n"
    "7️⃣ Música en vivo   |  8️⃣ Reacción a videos   |  9️⃣ Religión\n"
    "1️⃣0️⃣ Temas sociales   |  1️⃣1️⃣ Estudios/tareas   |  1️⃣2️⃣ Ventas en vivo\n"
    "1️⃣3️⃣ Otro"
),


# 🔹 Intereses
17: (
    "📌 ¿Cuáles son tus intereses?\n"
    "Responde con los números, separados por coma.\n\n"
    "1️⃣ Deportes   |  2️⃣ Moda   |  3️⃣ Maquillaje   |  4️⃣ Cocina\n"
    "5️⃣ Fitness   |  6️⃣ Música   |  7️⃣ Bailes   |  8️⃣ Gaming\n"
    "9️⃣ Lectura   |  1️⃣0️⃣ Salud mental   |  1️⃣1️⃣ Comedia   |  1️⃣2️⃣ Religión\n"
    "1️⃣3️⃣ Política   |  1️⃣4️⃣ Emprendimiento   |  1️⃣5️⃣ Viajes   |  1️⃣6️⃣ Idiomas\n"
    "1️⃣7️⃣ Educación   |  1️⃣8️⃣ Noticias   |  1️⃣9️⃣ Relaciones   |  2️⃣0️⃣ Arte\n"
    "2️⃣1️⃣ Tecnología   |  2️⃣2️⃣ Fotografía   |  2️⃣3️⃣ Otro"
)

}

# ============================
# VALIDACIONES
# ============================
def validar_opciones_multiples(texto, opciones_validas):
    # Permitir separadores por coma, punto y coma, espacio
    import re
    items = [x.strip() for x in re.split(r"[,\s;]+", texto) if x.strip()]
    if not items:
        return None
    # Validar cada ítem
    seleccion = []
    for item in items:
        if item in opciones_validas:
            if item not in seleccion:  # evita duplicados
                seleccion.append(item)
        else:
            return None  # Si alguna opción no es válida, rechaza todo
    return seleccion if seleccion else None

# ============================
# ENVIAR PREGUNTAS
# ============================
def enviar_pregunta(numero: str, paso: int):
    texto = preguntas[paso]
    return enviar_mensaje(numero, texto)

def enviar_mensaje(numero: str, texto: str):
    return enviar_mensaje_texto_simple(
        token=TOKEN,
        numero_id=PHONE_NUMBER_ID,
        telefono_destino=numero,
        texto=texto
    )

def enviar_boton_iniciar(numero: str, texto: str):
    return enviar_boton_iniciar_Completa(
        token=TOKEN,
        numero_id=PHONE_NUMBER_ID,
        telefono_destino=numero,
        texto=texto
    )


import time

# 🗂️ Cachés en memoria con timestamp
usuarios_flujo = {}   # {numero: (paso, timestamp)}
usuarios_roles = {}   # {numero: (rol, timestamp)}

# Tiempo de vida en segundos (1 hora = 3600)
TTL = 3600


# --- Funciones de cache ---
def actualizar_flujo(numero, paso):
    usuarios_flujo[numero] = (paso, time.time())

def obtener_flujo(numero):
    if numero in usuarios_flujo:
        paso, t = usuarios_flujo[numero]
        if time.time() - t < TTL:
            return paso
        else:
            usuarios_flujo.pop(numero, None)  # 🧹 expira por inactividad
    return None

def obtener_rol_usuario(numero):
    if numero in usuarios_roles:
        rol, t = usuarios_roles[numero]
        if time.time() - t < TTL:
            return rol
        else:
            usuarios_roles.pop(numero, None)  # 🧹 expira por inactividad

    rol = consultar_rol_bd(numero)
    usuarios_roles[numero] = (rol, time.time())
    return rol

def consultar_rol_bd(numero):
    usuario = buscar_usuario_por_telefono(numero)
    if usuario:
        return usuario.get("rol", "aspirante")
    return "aspirante"

def enviar_menu_principal(numero):
    rol = obtener_rol_usuario(numero)

    if rol == "aspirante":
        mensaje = (
            "👋 ¡Hola, bienvenido a la Agencia!\n"
            "¿Qué deseas hacer hoy?\n"
            "1️⃣ Actualizar mi información de perfil\n"
            "2️⃣ Diagnóstico y mejoras de mi perfil\n"
            "3️⃣ Ver requisitos para ingresar a la Agencia\n"
            "4️⃣ Chat libre con un asesor\n"
            "Por favor responde con el número de la opción."
        )
    elif rol == "creador":
        mensaje = (
            "👋 ¡Hola, creador de la Agencia!\n"
            "¿Qué deseas hacer hoy?\n"
            "1️⃣ Actualizar mi información de perfil\n"
            "3️⃣ Solicitar asesoría personalizada\n"
            "4️⃣ Acceder a recursos exclusivos\n"
            "5️⃣ Ver próximas actividades/eventos\n"
            "6️⃣ Solicitar soporte técnico\n"
            "7️⃣ Chat libre con el equipo\n"
            "8️⃣ Ver mis estadísticas/resultados\n"
            "9️⃣ Solicitar baja de la agencia"
        )
    elif rol == "admin":
        mensaje = (
            "👋 ¡Hola, administrador!\n"
            "¿Qué deseas hacer hoy?\n"
            "1️⃣ Ver panel de control\n"
            "2️⃣ Ver todos los perfiles\n"
            "3️⃣ Enviar comunicado a creadores/aspirantes\n"
            "4️⃣ Gestión de recursos\n"
            "5️⃣ Chat libre con el equipo"
        )
    else:
        mensaje = (
            "👋 ¡Hola! ¿Qué deseas hacer hoy?\n"
            "1️⃣ Información general\n"
            "2️⃣ Chat libre"
        )
    enviar_mensaje(numero, mensaje)

def normalizar_texto(texto):
    texto = texto.strip().lower()
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto)
                    if unicodedata.category(c) != 'Mn')
    return texto

# Une todas las ciudades en una sola lista para validación
CIUDADES_LATAM = []
for ciudades in ciudades_por_pais.values():
    CIUDADES_LATAM.extend(ciudades)

def validar_aceptar_ciudad(usuario_ciudad, ciudades=CIUDADES_LATAM, score_minimo=75):
    usuario_norm = normalizar_texto(usuario_ciudad)
    ciudades_norm = [normalizar_texto(c) for c in ciudades]

    # Usar partial_ratio para que "Bogo" matchee con "Bogotá"
    matches = process.extract(usuario_norm, ciudades_norm, scorer=fuzz.partial_ratio, limit=1)

    if matches and matches[0][1] >= score_minimo:
        idx = ciudades_norm.index(matches[0][0])
        ciudad_oficial = ciudades[idx]
        return {"ciudad": ciudad_oficial, "corregida": True}
    else:
        return {"ciudad": usuario_ciudad.strip(), "corregida": False}


def manejar_respuesta(numero, texto):
    # --- Volver al menú principal ---
    if texto.strip().lower() in ["menu", "menú", "volver", "inicio", "brillar"]:
        usuarios_flujo.pop(numero, None)   # 🧹 limpieza manual de flujo
        enviar_menu_principal(numero)
        return

    paso = usuarios_flujo.get(numero)

    # 🚫 Si está en chat libre, no procesar aquí
    if paso == "chat_libre":
        return

    # --- MENÚ PRINCIPAL SEGÚN ROL ---
    if paso is None:
        rol = obtener_rol_usuario(numero)

        if rol == "aspirante":
            if texto in ["1", "actualizar", "perfil"]:
                usuarios_flujo[numero] = 1
                enviar_pregunta(numero, 1)
                return
            elif texto in ["2", "diagnóstico", "diagnostico"]:
                usuarios_flujo[numero] = "diagnostico"
                enviar_diagnostico(numero)
                usuarios_flujo.pop(numero, None)
                return
            elif texto in ["3", "requisitos"]:
                usuarios_flujo[numero] = "requisitos"
                enviar_requisitos(numero)
                usuarios_flujo.pop(numero, None)
                return
            elif texto in ["4", "chat libre"]:
                usuarios_flujo[numero] = "chat_libre"
                enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
                return
            else:
                enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
                return

        elif rol == "creador":
            if texto == "1":
                usuarios_flujo[numero] = 1
                enviar_pregunta(numero, 1)
                return
            elif texto == "3":
                usuarios_flujo[numero] = "asesoria"
                enviar_mensaje(numero, "📌 Un asesor se pondrá en contacto contigo pronto.")
                usuarios_flujo.pop(numero, None)
                return
            elif texto == "4":
                usuarios_flujo[numero] = "recursos"
                enviar_recursos_exclusivos(numero)
                usuarios_flujo.pop(numero, None)
                return
            elif texto == "5":
                usuarios_flujo[numero] = "eventos"
                enviar_eventos(numero)
                usuarios_flujo.pop(numero, None)
                return
            elif texto == "6":
                usuarios_flujo[numero] = "soporte"
                enviar_mensaje(numero, "📩 Describe tu problema y el equipo técnico te responderá.")
                return
            elif texto == "8":
                usuarios_flujo[numero] = "estadisticas"
                enviar_estadisticas(numero)
                usuarios_flujo.pop(numero, None)
                return
            elif texto == "9":
                usuarios_flujo[numero] = "baja"
                solicitar_baja(numero)
                usuarios_flujo.pop(numero, None)
                return
            elif texto in ["7", "chat libre"]:
                usuarios_flujo[numero] = "chat_libre"
                enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
                return
            else:
                enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
                return

        elif rol == "admin":
            if texto == "1":
                usuarios_flujo[numero] = "panel"
                enviar_panel_control(numero)
                return
            elif texto == "2":
                usuarios_flujo[numero] = "ver_perfiles"
                enviar_perfiles(numero)
                usuarios_flujo.pop(numero, None)
                return
            elif texto == "3":
                usuarios_flujo[numero] = "comunicado"
                enviar_mensaje(numero, "✉️ Escribe el comunicado a enviar a creadores/aspirantes:")
                return
            elif texto == "4":
                usuarios_flujo[numero] = "recursos_admin"
                gestionar_recursos(numero)
                usuarios_flujo.pop(numero, None)
                return
            elif texto in ["5", "chat libre"]:
                usuarios_flujo[numero] = "chat_libre"
                enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
                return
            else:
                enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
                return

        else:  # Rol desconocido -> menú básico
            if texto == "1":
                usuarios_flujo[numero] = "info"
                enviar_info_general(numero)
                return
            else:
                enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
                return

    # --- VALIDACIONES DE FLUJO DE PREGUNTAS ---

    # 1: Nombre completo
    if paso == 1:
        if len(texto.strip()) < 3:
            enviar_mensaje(numero, "⚠️ Por favor, ingresa tu nombre completo (mínimo 3 caracteres).")
            return

    # 2: Edad
    if paso == 2:
        try:
            edad = int(texto)
            if not (0 < edad < 120):
                raise ValueError
        except Exception:
            enviar_mensaje(numero, "⚠️ Por favor, ingresa una edad válida (número entre 1 y 119).")
            return

    # 3: Género
    if paso == 3:
        if texto not in ["1", "2", "3", "4"]:
            enviar_mensaje(numero, "⚠️ Ingresa solo el número correspondiente (1, 2, 3 o 4).")
            return

    # 4: País
    if paso == 4:
        opciones_paises = list(mapa_paises.keys()) + ["20"]
        if texto not in opciones_paises and texto.lower() not in [p.lower() for p in mapa_paises.values()]:
            enviar_mensaje(numero, "⚠️ Ingresa el número de tu país o escríbelo si no está en la lista.")
            return

    # 5: Ciudad principal
    if paso == 5:
        resultado = validar_aceptar_ciudad(texto)
        if resultado["corregida"]:
            texto = resultado["ciudad"]
            enviar_mensaje(numero, f"✅ Ciudad reconocida y corregida: {texto}")
        else:
            enviar_mensaje(numero, f"✅ Ciudad aceptada como la escribiste: {texto}")

    # 6: Nivel de estudios (1–7)
    if paso == 6:
        if texto not in [str(i) for i in range(1, 8)]:
            enviar_mensaje(numero, "⚠️ Ingresa solo el número correspondiente (1 a 7).")
            return

    # 7: Idioma principal (1–7)
    if paso == 7:
        if texto not in [str(i) for i in range(1, 8)]:
            enviar_mensaje(numero, "⚠️ Ingresa solo el número correspondiente (1 a 7).")
            return

    # 8: Actividad actual (1–8)
    if paso == 8:
        if texto not in [str(i) for i in range(1, 9)]:
            enviar_mensaje(numero, "⚠️ Ingresa solo el número correspondiente (1 a 8).")
            return

    # 9: Horario preferido (1–6)
    if paso == 9:
        if texto not in [str(i) for i in range(1, 7)]:
            enviar_mensaje(numero, "⚠️ Ingresa solo el número correspondiente (1 a 6).")
            return

    # 10: Intención principal (1–5)
    if paso == 10:
        if texto not in [str(i) for i in range(1, 6)]:
            enviar_mensaje(numero, "⚠️ Ingresa solo el número correspondiente (1 a 5).")
            return

    # 11: ¿Cuántos lives por semana?
    if paso == 11:
        try:
            cantidad = int(texto)
            if not (0 < cantidad < 100):
                raise ValueError
        except Exception:
            enviar_mensaje(numero, "⚠️ Ingresa un número válido de lives por semana (1 a 99).")
            return

    # 12: ¿Cuántas horas a la semana?
    if paso == 12:
        try:
            horas = int(texto)
            if not (0 < horas < 168):
                raise ValueError
        except Exception:
            enviar_mensaje(numero, "⚠️ Ingresa un número válido de horas por semana (1 a 168).")
            return

    # 13-15: Meses de experiencia (0–999)
    if paso in range(13, 16):
        try:
            meses = int(texto)
            if not (0 <= meses <= 999):
                raise ValueError
        except Exception:
            enviar_mensaje(numero, "⚠️ Ingresa la cantidad de meses de experiencia (de 0 a 999).")
            return

    # 16: Tipo de contenido (múltiple, 1–13)
    if paso == 16:
        seleccion = validar_opciones_multiples(texto, [str(i) for i in range(1, 14)])
        if not seleccion:
            enviar_mensaje(numero, "⚠️ Respuesta inválida. Ejemplo válido: 1,2,3")
            return

    # 17: Intereses (múltiple, 1–23)
    if paso == 17:
        seleccion = validar_opciones_multiples(texto, [str(i) for i in range(1, 24)])
        if not seleccion:
            enviar_mensaje(numero, "⚠️ Respuesta inválida. Ejemplo válido: 1,3,5")
            return


    # Guardar respuesta y avanzar
    guardar_respuesta(numero, paso, texto)

    # Avanza o termina flujo
    if isinstance(paso, int) and paso < len(preguntas):
        usuarios_flujo[numero] += 1
        enviar_pregunta(numero, usuarios_flujo[numero])
    else:
        usuarios_flujo.pop(numero, None)
        enviar_mensaje(numero, "✅ Gracias, completaste todas las preguntas.")
        consolidar_perfil(numero)
        enviar_menu_principal(numero)  # <-- vuelve al menú según rol


import psycopg2
import json
from typing import Union, Any


def guardar_respuesta(numero: str, paso: int, texto: str):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO perfil_creador_flujo_temp (telefono, paso, respuesta)
            VALUES (%s, %s, %s)
            ON CONFLICT (telefono, paso) DO UPDATE SET respuesta = EXCLUDED.respuesta
        """, (numero, paso, texto))
        conn.commit()
    except Exception as e:
        if 'conn' in locals():
            conn.rollback()
        print("❌ Error guardando respuesta:", e)
    finally:
        try:
            cur.close()
        except: pass
        try:
            conn.close()
        except: pass


def enviar_diagnostico(numero: str):
    """Envía el diagnóstico de un usuario tomando el campo observaciones de perfil_creador"""
    try:
        with psycopg2.connect(INTERNAL_DATABASE_URL) as conn:
            with conn.cursor() as cur:

                # 1️⃣ Buscar el creador por su número
                cur.execute("SELECT id, usuario, nombre_real FROM creadores WHERE whatsapp = %s", (numero,))
                creador = cur.fetchone()
                if not creador:
                    print(f"⚠️ No se encontró creador con whatsapp {numero}")
                    enviar_mensaje(numero, "No encontramos tu perfil en el sistema. Verifica tu número.")
                    return

                creador_id, usuario, nombre_real = creador

                # 2️⃣ Obtener observaciones desde perfil_creador
                cur.execute("SELECT observaciones FROM perfil_creador WHERE creador_id = %s", (creador_id,))
                fila = cur.fetchone()

        nombre = nombre_real if nombre_real else usuario
        if not fila or not fila[0]:
            diagnostico = f"🔎 Diagnóstico para {nombre}:\nAún no se han registrado observaciones en tu perfil."
        else:
            diagnostico = f"🔎 Diagnóstico para {nombre}:\n\n{fila[0]}"

        # 3️⃣ Enviar el diagnóstico
        enviar_mensaje(numero, diagnostico)
        print(f"✅ Diagnóstico enviado a {numero}")

    except Exception as e:
        print(f"❌ Error al enviar diagnóstico a {numero}:", str(e))
        enviar_mensaje(numero, "Ocurrió un error al generar tu diagnóstico. Intenta más tarde.")


def enviar_requisitos(numero):
    requisitos = (
        "📋 *Requisitos para ingresar a la Agencia:*\n"
        "1️⃣ Ser mayor de 18 años.\n"
        "2️⃣ Contar con documento de identidad vigente.\n"
        "3️⃣ Tener acceso a una computadora o smartphone con internet.\n"
        "4️⃣ Disponer de tiempo para transmisiones en vivo y capacitaciones.\n"
        "5️⃣ Contar con cuentas activas en al menos una red social (Instagram, TikTok, Facebook, etc.).\n"
        "6️⃣ Disposición para aprender y trabajar en equipo.\n"
        "7️⃣ Cumplir con las políticas y normas internas de la Agencia.\n"
        "\n¿Tienes dudas? Responde este mensaje y te ayudamos. Puedes volver al *menú principal* escribiendo 'menu'."
    )
    enviar_mensaje(numero, requisitos)

@router.post("/enviar_solicitud_informacion")
async def api_enviar_solicitar_informacion(data: dict):
    telefono = data.get("telefono")
    nombre = data.get("nombre", "").strip()

    if not telefono or not nombre:
        return JSONResponse({"error": "Faltan datos (telefono o nombre)"}, status_code=400)

    try:
        plantilla = "solicitar_informacion"
        parametros = [nombre]

        codigo, respuesta_api = enviar_plantilla_generica(
            token=TOKEN,
            phone_number_id=PHONE_NUMBER_ID,
            numero_destino=telefono,
            nombre_plantilla=plantilla,
            codigo_idioma="es_CO",
            parametros=parametros
        )

        guardar_mensaje(
            telefono,
            f"[Plantilla enviada: {plantilla} - {parametros}]",
            tipo="enviado"
        )

        return {
            "status": "ok",
            "mensaje": f"Se envió la plantilla {plantilla} a {telefono}",
            "codigo_api": codigo,
            "respuesta_api": respuesta_api
        }

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


from DataBase import *

@router.post("/webhook")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    print("📩 Webhook recibido:", json.dumps(data, indent=2))

    try:
        mensajes = data["entry"][0]["changes"][0]["value"].get("messages", [])
        if not mensajes:
            return {"status": "ok"}

        for mensaje in mensajes:
            numero = mensaje["from"]
            tipo = mensaje.get("type")
            paso = usuarios_flujo.get(numero)

            usuario_bd = buscar_usuario_por_telefono(numero)

            # 1. FLUJO DE NUEVO USUARIO (Onboarding)
            if not usuario_bd and paso is None:
                enviar_mensaje(numero, "Hola, bienvenido a la Agencia XXX 👋")
                enviar_mensaje(numero, "¿Me puede dar su usuario de TikTok?")
                usuarios_flujo[numero] = "esperando_usuario_tiktok"
                return {"status": "ok"}

            # 2. Esperando usuario TikTok
            if paso == "esperando_usuario_tiktok" and tipo == "text":
                usuario_tiktok = mensaje["text"]["body"].strip()
                aspirante = buscar_aspirante_por_usuario_tiktok(usuario_tiktok)
                if aspirante:
                    enviar_mensaje(numero, f"¿Tu nombre o nickname es: {aspirante['nombre_real']}?")
                    usuarios_flujo[numero] = "confirmando_nombre"
                    usuarios_temp[numero] = aspirante
                else:
                    enviar_mensaje(numero, "No encontramos ese usuario de TikTok en nuestra base de aspirantes. ¿Puedes verificarlo?")
                return {"status": "ok"}

            # 3. Confirmando nombre
            if paso == "confirmando_nombre" and tipo == "text":
                texto = mensaje["text"]["body"].strip().lower()
                if texto in ["sí", "si", "correcto"]:
                    aspirante = usuarios_temp.get(numero)
                    actualizar_telefono_aspirante(aspirante["id"], numero)
                    enviar_boton_iniciar(numero, "¡Perfecto! Ahora necesitamos que llenes una breve encuesta de datos personales.")
                    usuarios_flujo[numero] = "esperando_inicio_encuesta"
                else:
                    enviar_mensaje(numero, "Por favor escribe el nombre correcto o verifica tu usuario de TikTok.")
                return {"status": "ok"}

            # 4. Proceso del botón "Iniciar"
            if paso == "esperando_inicio_encuesta" and tipo == "button":
                boton_texto = mensaje["button"]["text"]
                if boton_texto.lower() == "iniciar":
                    usuarios_flujo[numero] = 1  # Empieza la encuesta
                    enviar_pregunta(numero, 1)
                    usuarios_temp.pop(numero, None)
                    return {"status": "ok"}

            # 5. ASIGNAR ROL SI USUARIO EXISTE
            if usuario_bd:
                usuarios_roles[numero] = usuario_bd["rol"]

            # 6. CHAT LIBRE - SIEMPRE ANTES DEL FLUJO NORMAL
            if paso == "chat_libre":
                if tipo == "text":
                    texto = mensaje["text"]["body"].strip()
                    if texto.lower() in ["menu", "volver", "inicio"]:
                        usuarios_flujo[numero] = 0
                        enviar_mensaje(numero, "🔙 Volviste al menú inicial.")
                        enviar_menu_principal(numero)
                        return {"status": "ok"}
                    print(f"💬 Chat libre de {numero}: {texto}")
                    guardar_mensaje(numero, texto, tipo="recibido", es_audio=False)
                elif tipo == "audio":
                    audio_id = mensaje.get("audio", {}).get("id")
                    print(f"🎤 Audio recibido de {numero}: {audio_id}")
                    url_cloudinary = descargar_audio(audio_id, TOKEN)
                    if url_cloudinary:
                        guardar_mensaje(numero, url_cloudinary, tipo="recibido", es_audio=True)
                        enviar_mensaje(numero, "🎧 Recibimos tu audio. Un asesor lo revisará pronto.")
                    else:
                        enviar_mensaje(numero, "⚠️ No se pudo procesar tu audio, inténtalo de nuevo.")
                elif tipo == "button":
                    boton_texto = mensaje["button"]["text"]
                    print(f"👆 Botón en chat libre: {boton_texto}")
                    guardar_mensaje(numero, boton_texto, tipo="recibido", es_audio=False)
                return {"status": "ok"}  # <-- IMPORTANTE: Cortar aquí

            # 7. FLUJO NORMAL (MENÚ/ENCUESTA)
            if tipo == "button":
                boton_texto = mensaje["button"]["text"]
                if boton_texto.lower() == "sí, continuar":
                    usuarios_flujo[numero] = 1
                    enviar_pregunta(numero, 1)

            elif tipo == "text":
                texto = mensaje["text"]["body"].strip().lower()
                print(f"📥 Texto recibido de {numero}: {texto}")

                # ACTIVAR CHAT LIBRE DESDE EL MENÚ
                if texto in ["4", "chat libre"] and usuarios_roles.get(numero) == "aspirante":
                    usuarios_flujo[numero] = "chat_libre"
                    enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
                    return {"status": "ok"}
                if texto in ["7", "chat libre"] and usuarios_roles.get(numero) == "creador":
                    usuarios_flujo[numero] = "chat_libre"
                    enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
                    return {"status": "ok"}
                if texto in ["5", "chat libre"] and usuarios_roles.get(numero) == "admin":
                    usuarios_flujo[numero] = "chat_libre"
                    enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
                    return {"status": "ok"}

                # FLUJO NORMAL (MENÚ, ENCUESTA, ETC.)
                manejar_respuesta(numero, texto)

    except Exception as e:
        print("❌ Error procesando webhook:", e)
        traceback.print_exc()

    return {"status": "ok"}

# ================== ** ==================
# ================== ACTUALIZAR PERFIL CREADOR ==================
# ================== ** ==================

import psycopg2
import json
from decimal import Decimal, ROUND_HALF_UP

# ================== MAPEOS ==================
map_genero = {
    "1": "Masculino",
    "2": "Femenino",
    "3": "Otro",
    "4": "Prefiero no decir"
}

#  opcionesPaises = [{value: "argentina", label: "Argentina"}, ...]
map_paises = {
    "1": "argentina",
    "2": "bolivia",
    "3": "chile",
    "4": "colombia",
    "5": "costarica",
    "6": "cuba",
    "7": "ecuador",
    "8": "elsalvador",
    "9": "guatemala",
    "10": "honduras",
    "11": "mexico",
    "12": "nicaragua",
    "13": "panama",
    "14": "paraguay",
    "15": "peru",
    "16": "puertorico",
    "17": "dominicana",
    "18": "uruguay",
    "19": "venezuela",
    "20": "otro"
}

#  opcionesEstudios = [{value: "ninguno", label: "Ninguno"}, ...]
map_estudios = {
    "1": "ninguno",
    "2": "primaria",
    "3": "secundaria",
    "4": "tecnico",
    "5": "universitario_incompleto",
    "6": "universitario",
    "7": "postgrado",
    "8": "autodidacta",
    "9": "otro"
}

#  opcionesIdiomas = [{value: "espanol", label: "Español"}, ...]
map_idiomas = {
    "1": "espanol",
    "2": "ingles",
    "3": "portugues",
    "4": "frances",
    "5": "italiano",
    "6": "aleman",
    "7": "otro"
}

#  opcionesActividadActual = [{value: "estudiante_tiempo_completo", label: ...}, ...]
map_actividad = {
    "1": "estudiante_tiempo_completo",
    "2": "estudiante_tiempo_parcial",
    "3": "trabajo_tiempo_completo",
    "4": "trabajo_medio_tiempo",
    "5": "buscando_empleo",
    "6": "emprendiendo",
    "7": "disponible_total",
    "8": "otro"
}

#  opcionesHorarios = [{value: "manana", label: ...}, ...]
map_horario = {
    "1": "Mañana (6am–12pm)",
    "2": "Tarde (12pm–6pm)",
    "3": "Noche (6pm–12am)",
    "4": "Madrugada (12am–6am)",
    "5": "Variable",
    "6": "Otro"
}

#  opcionesIntencionTrabajo = [{value: "trabajo_principal", label: ...}, ...]
map_intencion = {
    "1": "trabajo principal",
    "2": "trabajo secundario",
    "3": "Hobby, pero me gustaría profesionalizarlo",
    "4": "diversión, sin intención profesional",
    "5": "No estoy seguro"
}

#  tiposContenido = [{value: "bailes", label: ...}, ...]
map_tipo_contenido = {
    "1": "bailes",
    "2": "charlas",
    "3": "gaming",
    "4": "tutoriales",
    "5": "entretenimiento general",
    "6": "humor",
    "7": "música en vivo",
    "8": "reacción a videos",
    "9": "religión y espiritualidad",
    "10": "temas sociales",
    "11": "estudios / tareas",
    "12": "ventas en vivo",
    "13": "Otro"
}

#  interesesOpciones = [{value: "deportes", label: ...}, ...]
map_intereses = {
    "1": "deportes",
    "2": "moda",
    "3": "maquillaje",
    "4": "cocina",
    "5": "fitness",
    "6": "música",
    "7": "bailes",
    "8": "gaming",
    "9": "lectura",
    "10": "salud mental",
    "11": "comedia",
    "12": "religión",
    "13": "política",
    "14": "emprendimiento",
    "15": "viajes",
    "16": "idiomas",
    "17": "educación",
    "18": "noticias",
    "19": "relaciones",
    "20": "arte",
    "21": "tecnología",
    "22": "fotografía",
    "23": "Otro"
}

# ================== FUNCIONES ==================

def redondear_a_un_decimal(valor):
    return float(Decimal(valor).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))

def procesar_respuestas(respuestas):
    datos = {}

    datos["nombre"] = respuestas.get(1)
    datos["edad"] = int(respuestas.get(2)) if respuestas.get(2) else None
    datos["genero"] = map_genero.get(respuestas.get(3))
    datos["pais"] = map_paises.get(respuestas.get(4))
    datos["ciudad"] = respuestas.get(5)
    datos["estudios"] = map_estudios.get(respuestas.get(6))
    datos["idioma"] = map_idiomas.get(respuestas.get(7))
    datos["actividad_actual"] = map_actividad.get(respuestas.get(8))
    datos["horario_preferido"] = map_horario.get(respuestas.get(9))
    datos["intencion_trabajo"] = map_intencion.get(respuestas.get(10))
    datos["frecuencia_lives"] = int(respuestas.get(11)) if respuestas.get(11) else None
    datos["tiempo_disponible"] = int(respuestas.get(12)) if respuestas.get(12) else None

    # Experiencia plataformas principales
    experiencia = {
        "TikTok": redondear_a_un_decimal(int(respuestas.get(13, 0)) / 12) if respuestas.get(13) else 0,
        "YouTube": redondear_a_un_decimal(int(respuestas.get(14, 0)) / 12) if respuestas.get(14) else 0,
        "Instagram": redondear_a_un_decimal(int(respuestas.get(15, 0)) / 12) if respuestas.get(15) else 0,
        "Facebook": 0, "Twitch": 0, "LinkedIn": 0, "Twitter/X": 0, "Otro": 0
    }
    datos["experiencia_otras_plataformas"] = json.dumps(experiencia)

    # Tipo de contenido (checkbox)
    tipo_contenido = {v: False for v in map_tipo_contenido.values()}
    for opcion in respuestas.get(16, "").split(","):
        opcion = opcion.strip()
        if opcion in map_tipo_contenido:
            tipo_contenido[map_tipo_contenido[opcion]] = True
    datos["tipo_contenido"] = json.dumps(tipo_contenido)

    # Intereses (checkbox)
    intereses = {v: False for v in map_intereses.values()}
    for opcion in respuestas.get(17, "").split(","):
        opcion = opcion.strip()
        if opcion in map_intereses:
            intereses[map_intereses[opcion]] = True
    datos["intereses"] = json.dumps(intereses)

    return datos

def consolidar_perfil(telefono: str):
    """Procesa y actualiza un solo número en perfil_creador con manejo de errores"""
    try:
        with psycopg2.connect(INTERNAL_DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # Buscar creador por número
                cur.execute("SELECT id, usuario, nombre_real, whatsapp FROM creadores WHERE whatsapp=%s", (telefono,))
                creador = cur.fetchone()
                if not creador:
                    print(f"⚠️ No se encontró creador con whatsapp {telefono}")
                    return

                creador_id = creador[0]

                # Obtener respuestas de flujo temporal
                cur.execute("""
                    SELECT paso, respuesta 
                    FROM perfil_creador_flujo_temp 
                    WHERE telefono=%s 
                    ORDER BY paso ASC
                """, (telefono,))
                rows = cur.fetchall()
                respuestas = {int(p): r for p, r in rows}

                # Procesar respuestas
                datos_update = procesar_respuestas(respuestas)

                # Crear query dinámico UPDATE
                set_clause = ", ".join([f"{k}=%s" for k in datos_update.keys()])
                values = list(datos_update.values())
                values.append(creador_id)

                query = f"UPDATE perfil_creador SET {set_clause} WHERE creador_id=%s"
                cur.execute(query, values)
                conn.commit()

                print(f"✅ Actualizado perfil_creador para creador_id={creador_id} ({telefono})")

    except Exception as e:
        print(f"❌ Error al procesar número {telefono}: {str(e)}")

    return {"status": "ok"}