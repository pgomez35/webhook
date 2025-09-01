from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import os, json
from dotenv import load_dotenv
from enviar_msg_wp import enviar_plantilla_generica, enviar_mensaje_texto_simple
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
DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")  # 🔹 corregido nombre

router = APIRouter()

# Estado del flujo en memoria
usuarios_flujo = {}    # { numero: paso_actual }
respuestas = {}        # { numero: {campo: valor} }


# ============================
# OPCIONES
# ============================
tiposContenido_opciones = {
    "1": ["Entretenimiento", "música en vivo", "bailes", "humor","shows en vivo"],
    "2": ["Gaming", "streams de videojuegos"],
    "3": ["tutoriales", "charlas", "clases", "estudios/tareas"],
    "4": ["temas sociales","debates","foros", "religión"],
    "5": ["Negocios", "ventas en vivo", "otros"],
    "6": ["Otros"]
}

interesesOpciones_opciones = {
    "1": ["Estilo vida", "deporte", "moda", "cocina","fitness", "salud"],
    "2": ["Arte y cultura", "música","baile","lectura", "fotografía"],
    "3": ["religión", "política", "noticias", "relaciones", "psicología"],
    "4": ["Educación", "idiomas", "emprendimiento"],
    "5": ["Tecnología y gaming", "innovación"],
    "6": ["Otros"]
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
       "4️⃣ Técnico\n"
       "5️⃣ Universitario\n"
       "6️⃣ Posgrado\n"
       "7️⃣ Otro",
    7: "📌 Idioma principal:\n"
       "1️⃣ Español\n"
       "2️⃣ Inglés\n"
       "3️⃣ Portugués\n"
       "4️⃣ Otro",
    8: "📌 Actividad actual:\n"
       "1️⃣ Estudia tiempo completo\n"
       "2️⃣ Trabaja medio tiempo\n"
       "3️⃣ Trabaja tiempo completo\n"
       "4️⃣ Crea contenido a tiempo completo\n"
       "5️⃣ Otro",

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
        "3️⃣ No estoy seguro",
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
    "1️⃣ Bailes\n"
    "2️⃣ Charlas\n"
    "3️⃣ Gaming\n"
    "4️⃣ Tutoriales\n"
    "5️⃣ Entretenimiento general\n"
    "6️⃣ Humor\n"
    "7️⃣ Música en vivo\n"
    "8️⃣ Reacción a videos\n"
    "9️⃣ Religión y espiritualidad\n"
    "1️⃣0️⃣ Temas sociales\n"
    "1️⃣1️⃣ Estudios / tareas\n"
    "1️⃣2️⃣ Ventas en vivo\n"
    "1️⃣3️⃣ Otro"
),

# 🔹 Intereses
17: (
    "📌 ¿Cuáles son tus intereses?\n"
    "Responde con los números, separados por coma.\n\n"
    "1️⃣ Deportes\n"
    "2️⃣ Moda\n"
    "3️⃣ Maquillaje\n"
    "4️⃣ Cocina\n"
    "5️⃣ Fitness\n"
    "6️⃣ Música\n"
    "7️⃣ Bailes\n"
    "8️⃣ Gaming\n"
    "9️⃣ Lectura\n"
    "1️⃣0️⃣ Salud mental\n"
    "1️⃣1️⃣ Comedia\n"
    "1️⃣2️⃣ Religión\n"
    "1️⃣3️⃣ Política\n"
    "1️⃣4️⃣ Emprendimiento\n"
    "1️⃣5️⃣ Viajes\n"
    "1️⃣6️⃣ Idiomas\n"
    "1️⃣7️⃣ Educación\n"
    "1️⃣8️⃣ Noticias\n"
    "1️⃣9️⃣ Relaciones\n"
    "2️⃣0️⃣ Arte\n"
    "2️⃣1️⃣ Tecnología\n"
    "2️⃣2️⃣ Fotografía\n"
    "2️⃣3️⃣ Otro"
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

miembros_agencia = [
    {"telefono": "+573001234567", "nombre": "Pedro", "rol": "miembro"},
    {"telefono": "+5491133344455", "nombre": "Lucía", "rol": "miembro"},
    {"telefono": "+34666111222", "nombre": "Carlos", "rol": "miembro"},
]
admins = [
    {"telefono": "+573005551234", "nombre": "Admin Juan"},
    {"telefono": "+5491177788899", "nombre": "Admin Paula"},
    {"telefono": "+34666111223", "nombre": "Admin Sergio"}
]
def obtener_rol_usuario(numero):
    # Ejemplo: consulta a base de datos
    # Retorna: 'aspirante', 'miembro', 'admin', etc.
    # Aquí sólo para ejemplo:

    if numero in miembros_agencia:
        return "miembro"
    elif numero in admins:
        return "admin"
    else:
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
    elif rol == "miembro":
        mensaje = (
            "👋 ¡Hola, miembro de la Agencia!\n"
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
            "3️⃣ Enviar comunicado a miembros/aspirantes\n"
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

def validar_aceptar_ciudad(usuario_ciudad, ciudades=CIUDADES_LATAM, score_minimo=85):
    usuario_norm = normalizar_texto(usuario_ciudad)
    ciudades_norm = [normalizar_texto(c) for c in ciudades]
    matches = process.extract(usuario_norm, ciudades_norm, scorer=fuzz.ratio, limit=1)
    if matches and matches[0][1] >= score_minimo:
        idx = ciudades_norm.index(matches[0][0])
        ciudad_oficial = ciudades[idx]
        return {"ciudad": ciudad_oficial, "corregida": True}
    else:
        return {"ciudad": usuario_ciudad.strip(), "corregida": False}

# ============================
# MANEJO RESPUESTAS
# ============================
def manejar_respuesta(numero, texto):
    # --- Volver al menú principal ---
    if texto.strip().lower() in ["menu", "volver", "inicio","brillar"]:
        if numero in usuarios_flujo:
            del usuarios_flujo[numero]
        enviar_menu_principal(numero)
        return
    paso = usuarios_flujo.get(numero)

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
                return
            elif texto in ["3", "requisitos"]:
                usuarios_flujo[numero] = "requisitos"
                enviar_requisitos(numero)
                return
            elif texto in ["4", "chat", "asesor"]:
                usuarios_flujo[numero] = "chat_libre"
                enviar_mensaje(numero, "Estás en chat libre. Escribe tu consulta y un asesor te responderá pronto.")
                return
            else:
                enviar_menu_principal(numero)
                return

        elif rol == "miembro":
            if texto == "1":
                usuarios_flujo[numero] = 1
                enviar_pregunta(numero, 1)
                return
            elif texto == "3":
                usuarios_flujo[numero] = "asesoria"
                enviar_mensaje(numero, "📌 Un asesor se pondrá en contacto contigo pronto.")
                return
            elif texto == "4":
                usuarios_flujo[numero] = "recursos"
                enviar_recursos_exclusivos(numero)
                return
            elif texto == "5":
                usuarios_flujo[numero] = "eventos"
                enviar_eventos(numero)
                return
            elif texto == "6":
                usuarios_flujo[numero] = "soporte"
                enviar_mensaje(numero, "📩 Describe tu problema y el equipo técnico te responderá.")
                return
            elif texto == "7":
                usuarios_flujo[numero] = "chat_libre"
                enviar_mensaje(numero, "Estás en chat libre con el equipo.")
                return
            elif texto == "8":
                usuarios_flujo[numero] = "estadisticas"
                enviar_estadisticas(numero)
                return
            elif texto == "9":
                usuarios_flujo[numero] = "baja"
                solicitar_baja(numero)
                return
            else:
                enviar_menu_principal(numero)
                return

        elif rol == "admin":
            if texto == "1":
                usuarios_flujo[numero] = "panel"
                enviar_panel_control(numero)
                return
            elif texto == "2":
                usuarios_flujo[numero] = "ver_perfiles"
                enviar_perfiles(numero)
                return
            elif texto == "3":
                usuarios_flujo[numero] = "comunicado"
                enviar_mensaje(numero, "✉️ Escribe el comunicado a enviar a miembros/aspirantes:")
                return
            elif texto == "4":
                usuarios_flujo[numero] = "recursos_admin"
                gestionar_recursos(numero)
                return
            elif texto == "5":
                usuarios_flujo[numero] = "chat_libre"
                enviar_mensaje(numero, "Estás en chat libre con el equipo.")
                return
            else:
                enviar_menu_principal(numero)
                return

        else:  # Rol desconocido -> menú básico
            if texto == "1":
                usuarios_flujo[numero] = "info"
                enviar_info_general(numero)
                return
            elif texto == "2":
                usuarios_flujo[numero] = "chat_libre"
                enviar_mensaje(numero, "Estás en chat libre.")
                return
            else:
                enviar_menu_principal(numero)
                return

    # --- VALIDACIONES ---

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

    # 5: Ciudad principal (VALIDACIÓN ROBUSTA)
    if paso == 5:
        resultado = validar_aceptar_ciudad(texto)
        if resultado["corregida"]:
            texto = resultado["ciudad"]
            enviar_mensaje(numero, f"✅ Ciudad reconocida y corregida: {texto}")
        else:
            enviar_mensaje(numero, f"✅ Ciudad aceptada como la escribiste: {texto}")

    # 6: Nivel de estudios
    if paso == 6:
        if texto not in ["1", "2", "3", "4", "5", "6", "7"]:
            enviar_mensaje(numero, "⚠️ Ingresa solo el número correspondiente (1 a 7).")
            return

    # 7: Idioma principal
    if paso == 7:
        if texto not in ["1", "2", "3", "4"]:
            enviar_mensaje(numero, "⚠️ Ingresa solo el número correspondiente (1 a 4).")
            return

    # 8: Actividad actual
    if paso == 8:
        if texto not in ["1", "2", "3", "4", "5"]:
            enviar_mensaje(numero, "⚠️ Ingresa solo el número correspondiente (1 a 5).")
            return

    # 9: Horario preferido para lives
    if paso == 9:
        if texto not in ["1", "2", "3", "4", "5", "6"]:
            enviar_mensaje(numero, "⚠️ Ingresa solo el número correspondiente (1 a 6).")
            return

    # 10: Intención principal en la plataforma
    if paso == 10:
        if texto not in ["1", "2", "3"]:
            enviar_mensaje(numero, "⚠️ Ingresa solo el número correspondiente (1 a 3).")
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

    # 12: ¿Cuántas horas a la semana para crear contenido?
    if paso == 12:
        try:
            horas = int(texto)
            if not (0 < horas < 168):
                raise ValueError
        except Exception:
            enviar_mensaje(numero, "⚠️ Ingresa un número válido de horas por semana (1 a 168).")
            return

    # 13-15: Meses de experiencia en plataformas
    if paso in range(13, 15):
        try:
            meses = int(texto)
            if not (0 <= meses <= 999):
                raise ValueError
        except Exception:
            enviar_mensaje(numero, "⚠️ Ingresa la cantidad de meses de experiencia (de 0 a 999).")
            return

    # 19: Tipo de contenido (múltiple)
    if paso == 16:
        seleccion = validar_opciones_multiples(texto, tiposContenido_opciones.keys())
        if not seleccion:
            enviar_mensaje(numero, "⚠️ Respuesta inválida. Ejemplo válido: 1,2,3")
            return

    # 20: Intereses principales (múltiple)
    if paso == 17:
        seleccion = validar_opciones_multiples(texto, interesesOpciones_opciones.keys())
        if not seleccion:
            enviar_mensaje(numero, "⚠️ Respuesta inválida. Ejemplo válido: 1,3,5")
            return

    # Guardar respuesta y avanzar
    guardar_respuesta(numero, paso, texto)

    if isinstance(paso, int) and paso < len(preguntas):
        usuarios_flujo[numero] += 1
        enviar_pregunta(numero, usuarios_flujo[numero])
    else:
        del usuarios_flujo[numero]
        enviar_mensaje(numero, "✅ Gracias, completaste todas las preguntas.")
        consolidar_perfil(numero)
        enviar_menu_principal(numero)  # <-- vuelve al menú según rol


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


@router.post("/webhook")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    print("📩 Webhook recibido:", json.dumps(data, indent=2))

    try:
        mensajes = data["entry"][0]["changes"][0]["value"].get("messages", [])
        for mensaje in mensajes:
            numero = mensaje["from"]

            # Botón "continuar"
            if mensaje.get("type") == "button":
                boton_texto = mensaje["button"]["text"]
                if boton_texto.lower() == "sí, continuar":  # puedes comparar por texto
                    usuarios_flujo[numero] = 1  # iniciamos en paso 1
                    enviar_pregunta(numero, 1)

            # Mensaje de texto
            elif "text" in mensaje:
                texto = mensaje["text"]["body"].strip().lower()
                print(f"📥 Texto recibido de {numero}: {texto}")
                manejar_respuesta(numero, texto)

    except Exception as e:
        print("❌ Error procesando webhook:", e)
        traceback.print_exc()

    return {"status": "ok"}

import psycopg2
import json
from typing import Union, Any


def guardar_respuesta(numero: str, paso: int, texto: str):
    try:
        conn = psycopg2.connect(DATABASE_URL)
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

# def guardar_respuesta(numero: str, paso: Union[int, str], texto: Any):
#     """
#     Guarda la respuesta del usuario para un paso, aceptando cualquier tipo de valor.
#     Serializa listas y diccionarios como JSON.
#     """
#     # Serializa el valor si es lista o dict
#     if isinstance(texto, (list, dict)):
#         valor_guardar = json.dumps(texto, ensure_ascii=False)
#     else:
#         valor_guardar = str(texto)
#     print(f"GUARDADO: {numero} | Paso: {paso} | Valor: {valor_guardar}")
#     try:
#         conn = psycopg2.connect(DATABASE_URL)
#         cur = conn.cursor()
#         cur.execute("""
#             INSERT INTO perfil_creador_flujo_temp (telefono, paso, respuesta)
#             VALUES (%s, %s, %s)
#             ON CONFLICT (telefono, paso) DO UPDATE SET respuesta = EXCLUDED.respuesta
#         """, (numero, str(paso), valor_guardar))
#         conn.commit()
#     except Exception as e:
#         if 'conn' in locals():
#             conn.rollback()
#         print("❌ Error guardando respuesta:", e)
#     finally:
#         try:
#             cur.close()
#         except: pass
#         try:
#             conn.close()
#         except: pass

def consolidar_perfil(numero: str):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        cur.execute("""
            SELECT paso, respuesta 
            FROM perfil_creador_flujo_temp 
            WHERE telefono = %s 
            ORDER BY paso ASC
        """, (numero,))
        respuestas = cur.fetchall()

        datos = {paso: resp for paso, resp in respuestas}

        # cur.execute("""
        #     INSERT INTO perfil_creador (
        #         nombre, edad, genero, pais, ciudad, estudios, idioma, actividad,
        #         horario_preferido, intencion_trabajo, frecuencia_lives, tiempo_disponible,
        #         plataformas, plataformas_detalle, tipo_contenido, intereses, telefono
        #     )
        #     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        # """, (
        #     datos.get(1),  # nombre
        #     datos.get(2),  # edad
        #     datos.get(3),  # genero
        #     datos.get(4),  # pais
        #     datos.get(5),  # ciudad
        #     datos.get(6),  # estudios
        #     datos.get(7),  # idioma
        #     datos.get(8),  # actividad
        #     datos.get(9),  # horario preferido
        #     datos.get(10),  # intención
        #     datos.get(11),  # frecuencia lives
        #     datos.get(12),  # tiempo disponible
        #     datos.get(13),  # plataformas (lista cruda)
        #     datos.get(14),  # detalle de plataformas con años/horas
        #     datos.get(15),  # tipo contenido
        #     datos.get(16),  # intereses
        #     numero
        # ))
        #
        # cur.execute("DELETE FROM perfil_creador_flujo_temp WHERE telefono = %s", (numero,))
        conn.commit()

        cur.close()
        conn.close()
        print(f"✅ Perfil consolidado para {numero}")
    except Exception as e:
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        print("❌ Error al consolidar perfil:", str(e))


def enviar_diagnostico(numero):
    # 1. Recupera respuestas previas del usuario (puede ser de la tabla definitiva o temporal)
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            SELECT paso, respuesta 
            FROM perfil_creador_flujo_temp 
            WHERE telefono = %s 
            ORDER BY paso ASC
        """, (numero,))
        respuestas = dict(cur.fetchall())
        cur.close()
        conn.close()
    except Exception as e:
        print("❌ Error al obtener datos para diagnóstico:", e)
        enviar_mensaje(numero, "Ocurrió un error al generar tu diagnóstico. Intenta más tarde.")
        return

    # 2. Analiza y genera diagnóstico (ejemplo simple, personalízalo según tus reglas)
    nombre = respuestas.get(1, "usuario")
    edad = respuestas.get(2, "")
    plataformas = respuestas.get(13, "")
    tipos_contenido = respuestas.get(15, "")
    intereses = respuestas.get(16, "")

    diagnostico = f"🔎 Diagnóstico para {nombre}:\n"
    if edad and int(edad) < 18:
        diagnostico += "• Eres menor de edad, asegúrate de tener permiso de tus padres/tutores.\n"
    if plataformas:
        diagnostico += f"• Estás presente en: {plataformas}\n"
    if tipos_contenido:
        diagnostico += f"• Tus tipos de contenido: {tipos_contenido}\n"
    if intereses:
        diagnostico += f"• Tus intereses principales: {intereses}\n"

    # Ejemplo de recomendación simple
    if "TikTok" in plataformas or "7" in plataformas:
        diagnostico += "• ¡TikTok es excelente para crecer rápido! Asegúrate de publicar frecuentemente.\n"
    if "ventas" in tipos_contenido or "12" in tipos_contenido:
        diagnostico += "• El contenido de ventas en vivo es una gran oportunidad, ¡sigue capacitándote en esto!\n"
    if not intereses:
        diagnostico += "• Te sugerimos definir bien tus intereses para conectar mejor con tu audiencia.\n"

    diagnostico += "\n¿Te gustaría recibir asesoría personalizada? Responde 'asesoría'."

    # 3. Envía el diagnóstico
    enviar_mensaje(numero, diagnostico)

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