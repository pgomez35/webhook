from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import os, json
from dotenv import load_dotenv
from enviar_msg_wp import enviar_plantilla_generica, enviar_mensaje_texto_simple
from main import guardar_mensaje
from utils import *
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
opciones_plataformas = {
    "1": "YouTube", "2": "Instagram", "3": "Twitch", "4": "Facebook",
    "5": "Twitter/X", "6": "LinkedIn", "7": "TikTok", "8": "Otro"
}

tiposContenido_opciones  = {
    "1": "bailes", "2": "charlas", "3": "gaming", "4": "tutoriales",
    "5": "entretenimiento general", "6": "humor", "7": "música en vivo",
    "8": "reacción a videos", "9": "religión y espiritualidad",
    "10": "temas sociales", "11": "estudios / tareas", "12": "ventas en vivo",
    "13": "Otro"
}

interesesOpciones_opciones = {
    "1": "Deportes", "2": "Moda", "3": "Maquillaje", "4": "Cocina", "5": "Fitness",
    "6": "Música", "7": "Bailes", "8": "Gaming", "9": "Lectura", "10": "Salud mental",
    "11": "Comedia", "12": "Religión", "13": "Política", "14": "Emprendimiento",
    "15": "Viajes", "16": "Idiomas", "17": "Educación", "18": "Noticias",
    "19": "Relaciones", "20": "Arte", "21": "Tecnología", "22": "Fotografía", "23": "Otro"
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
    11: "📌 ¿Cuántos lives haces por semana?",
    12: "📌 ¿Cuántas horas a la semana tienes disponibles para crear contenido?",

    # 🔹 Experiencia en plataformas
    13: "📌 ¿En qué plataformas tienes experiencia como creador de contenido?\n"
        "Responde con los números separados por coma.\n\n"
        "1️⃣ YouTube\n"
        "2️⃣ Instagram\n"
        "3️⃣ Twitch\n"
        "4️⃣ Facebook\n"
        "5️⃣ Twitter/X\n"
        "6️⃣ LinkedIn\n"
        "7️⃣ TikTok\n"
        "8️⃣ Otro",
    14: "📌 Indica tu experiencia en AÑOS para cada plataforma seleccionada.\n"
        "Responde en el formato: Plataforma=Años.\n\n"
        "Ejemplo: YouTube=2, TikTok=1, Otro=Kick=0.5",

    # 🔹 Tipo de contenido
    15: "📌 ¿Qué tipo de contenido sueles crear?\n"
        "Responde con los números correspondientes (puedes elegir varios separados por coma).\n\n"
        "1️⃣ Bailes\n"
        "2️⃣ Charlas\n"
        "3️⃣ Gaming\n"
        "4️⃣ Tutoriales\n"
        "5️⃣ Entretenimiento general\n"
        "6️⃣ Humor\n"
        "7️⃣ Música en vivo\n"
        "8️⃣ Reacción a videos\n"
        "9️⃣ Religión y espiritualidad\n"
        "🔟 Temas sociales\n"
        "1️⃣1️⃣ Estudios / tareas\n"
        "1️⃣2️⃣ Ventas en vivo\n"
        "1️⃣3️⃣ Otro",

    # 🔹 Intereses
    16: "📌 ¿Cuáles son tus intereses principales?\n"
        "Responde con los números separados por coma.\n\n"
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

# ============================
# MANEJO RESPUESTAS
# ============================
def manejar_respuesta(numero, texto):
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

    # --- FLUJOS ESPECIALES ---

    # # Selección ciudad principal
    # if paso == 5:
    #     ciudad_seleccionada = texto.strip()
    #     ciudades_mostradas = respuestas.setdefault(numero, {}).get("ciudades_mostradas")
    #
    #     if ciudades_mostradas:
    #         if ciudad_seleccionada.isdigit():
    #             idx = int(ciudad_seleccionada) - 1
    #             if 0 <= idx < len(ciudades_mostradas):
    #                 ciudad = ciudades_mostradas[idx]
    #                 respuestas[numero]["ciudad"] = ciudad
    #                 guardar_respuesta(numero, 5, ciudad)
    #                 usuarios_flujo[numero] += 1
    #                 enviar_pregunta(numero, usuarios_flujo[numero])
    #                 return
    #             elif idx == len(ciudades_mostradas):
    #                 usuarios_flujo[numero] = "ciudad_otro"
    #                 enviar_mensaje(numero, "Por favor, escribe tu ciudad principal:")
    #                 return
    #         enviar_mensaje(numero, "Por favor elige una opción válida (ejemplo: 1, 2 ... o el número de 'Otra').")
    #         return
    #
    #     # Si no había ciudades guardadas
    #     pais_num = respuestas.setdefault(numero, {}).get(4)
    #     clave_pais = mapa_paises.get(str(pais_num))
    #     ciudades = ciudades_por_pais.get(clave_pais)
    #     if ciudades:
    #         opciones = "\n".join([f"{i+1}. {c}" for i, c in enumerate(ciudades)])
    #         opciones += f"\n{len(ciudades)+1}. Otra (especifica)"
    #         respuestas[numero]["ciudades_mostradas"] = ciudades
    #         enviar_mensaje(numero, f"📌 Elige tu ciudad principal:\n{opciones}")
    #     else:
    #         usuarios_flujo[numero] = "ciudad_otro"
    #         enviar_mensaje(numero, "Por favor, escribe tu ciudad principal:")
    #     return
    #
    # elif paso == "ciudad_otro":
    #     respuestas[numero]["ciudad"] = texto.strip()
    #     guardar_respuesta(numero, 5, texto.strip())
    #     usuarios_flujo[numero] = 6
    #     enviar_pregunta(numero, 6)
    #     return

    # # Plataformas (selección múltiple)
    # if paso == 13:
    #     seleccion = validar_opciones_multiples(texto, opciones_plataformas)
    #     if not seleccion:
    #         enviar_mensaje(numero, "❌ Respuesta inválida. Ejemplo válido: 1,3,5")
    #         return
    #     respuestas.setdefault(numero, {})["plataformas"] = seleccion
    #     if "8" in seleccion:
    #         usuarios_flujo[numero] = "plataforma_otro_nombre"
    #         enviar_mensaje(numero, "Indica el nombre de la otra plataforma:")
    #     else:
    #         usuarios_flujo[numero] = 14
    #         enviar_pregunta(numero, 14)
    #     return
    #
    # elif paso == "plataforma_otro_nombre":
    #     respuestas[numero]["plataforma_otro"] = texto
    #     usuarios_flujo[numero] = "plataforma_otro_experiencia"
    #     enviar_mensaje(numero, f"¿Cuántos años de experiencia tienes en {texto}?")
    #     return
    #
    # elif paso == "plataforma_otro_experiencia":
    #     if not texto.isdigit():
    #         enviar_mensaje(numero, "Por favor ingresa solo el número de años (ejemplo: 2)")
    #         return
    #     respuestas[numero]["plataforma_otro_experiencia"] = int(texto)
    #     usuarios_flujo[numero] = 14
    #     enviar_pregunta(numero, 14)
    #     return

    # Cuando selecciona plataformas (paso 13)
    if paso == 13:
        seleccion = validar_opciones_multiples(texto, opciones_plataformas)
        if not seleccion:
            enviar_mensaje(numero, "❌ Respuesta inválida. Ejemplo válido: 1,3,5")
            return
        respuestas.setdefault(numero, {})["plataformas"] = seleccion
        usuarios_flujo[numero] = ("experiencia_plataforma", 0)  # 0: primer índice de plataforma
        plataforma_actual = opciones_plataformas[int(seleccion[0]) - 1]
        enviar_mensaje(numero, f"¿Cuántos años de experiencia tienes en {plataforma_actual}?")
        return

    # Cuando está preguntando experiencia por plataforma
    if isinstance(paso, tuple) and paso[0] == "experiencia_plataforma":
        idx = paso[1]
        seleccionadas = respuestas[numero]["plataformas"]
        plataforma_actual = opciones_plataformas[int(seleccionadas[idx]) - 1]
        # Validar y guardar la respuesta
        try:
            años = float(texto.replace(",", "."))
        except Exception:
            enviar_mensaje(numero, "Por favor ingresa solo el número de años (ejemplo: 2 o 0.5)")
            return
        if "experiencia_por_plataforma" not in respuestas[numero]:
            respuestas[numero]["experiencia_por_plataforma"] = {}
        respuestas[numero]["experiencia_por_plataforma"][plataforma_actual] = años
        if idx + 1 < len(seleccionadas):
            usuarios_flujo[numero] = ("experiencia_plataforma", idx + 1)
            plataforma_actual = opciones_plataformas[int(seleccionadas[idx + 1]) - 1]
            enviar_mensaje(numero, f"¿Cuántos años de experiencia tienes en {plataforma_actual}?")
        else:
            usuarios_flujo[numero] = 14
            enviar_pregunta(numero, 14)
        return

    # Tipos de contenido
    if paso == 15:
        seleccion = validar_opciones_multiples(texto, tiposContenido_opciones)
        if not seleccion:
            enviar_mensaje(numero, "❌ Respuesta inválida. Ejemplo válido: 1,4,7")
            return
        respuestas.setdefault(numero, {})["tipos_contenido"] = seleccion
        guardar_respuesta(numero, 15, seleccion)  # <--- GUARDA LA RESPUESTA
        if "13" in seleccion:
            usuarios_flujo[numero] = "contenido_otro_nombre"
            enviar_mensaje(numero, "Indica el tipo de contenido adicional:")
        else:
            usuarios_flujo[numero] = 16
            enviar_pregunta(numero, 16)
        return

    elif paso == "contenido_otro_nombre":
        respuestas[numero]["contenido_otro"] = texto
        guardar_respuesta(numero, "contenido_otro_nombre", texto)  # <--- GUARDA
        usuarios_flujo[numero] = 16
        enviar_pregunta(numero, 16)
        return

    # Intereses
    if paso == 16:
        seleccion = validar_opciones_multiples(texto, interesesOpciones_opciones)
        if not seleccion:
            enviar_mensaje(numero, "❌ Respuesta inválida. Ejemplo válido: 2,8,12")
            return
        respuestas.setdefault(numero, {})["intereses"] = seleccion
        guardar_respuesta(numero, 16, seleccion)  # <--- GUARDA LA RESPUESTA
        if "23" in seleccion:
            usuarios_flujo[numero] = "interes_otro_nombre"
            enviar_mensaje(numero, "Indica el interés adicional:")
        else:
            usuarios_flujo[numero] = 17
            enviar_mensaje(numero, "✅ Gracias, completaste todas las preguntas.")
            consolidar_perfil(numero)
        return

    elif paso == "interes_otro_nombre":
        respuestas[numero]["interes_otro"] = texto
        guardar_respuesta(numero, "interes_otro_nombre", texto)  # <--- GUARDA
        usuarios_flujo[numero] = 17
        enviar_mensaje(numero, "✅ Gracias, completaste todas las preguntas.")
        consolidar_perfil(numero)
        return

    # Validación de edad
    if paso == 2:
        try:
            edad = int(texto)
            if not (0 < edad < 120):
                raise ValueError
        except Exception:
            enviar_mensaje(numero, "⚠️ Por favor, ingresa una edad válida (número entre 1 y 119).")
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

# ============================
# MANEJO RESPUESTAS
# ============================
# def manejar_respuesta(numero, texto):
#     paso = usuarios_flujo.get(numero)
#
#     # Si el usuario no tiene flujo asignado, muestra opciones principales
#     if paso is None:
#         if texto in ["1", "actualizar", "actualizar información", "perfil"]:
#             usuarios_flujo[numero] = 1  # Empieza el flujo de preguntas
#             enviar_pregunta(numero, 1)
#             return
#
#         elif texto in ["2", "diagnóstico", "diagnostico"]:
#             usuarios_flujo[numero] = "diagnostico"
#             enviar_diagnostico(numero)  # función que analiza y envía el diagnóstico
#             return
#
#         elif texto in ["3", "requisitos"]:
#             usuarios_flujo[numero] = "requisitos"
#             enviar_requisitos(numero)  # función que envía información de requisitos
#             return
#
#         elif texto in ["4", "chat", "asesor"]:
#             usuarios_flujo[numero] = "chat_libre"
#             enviar_mensaje(numero, "Estás en chat libre. Escribe tu consulta y un asesor te responderá pronto.")
#             return
#
#         else:
#             enviar_mensaje(numero, """
#     👋 ¡Hola! ¿Qué deseas hacer hoy?
#     1️⃣ Actualizar información de mi perfil
#     2️⃣ Diagnóstico y mejoras de mi perfil
#     3️⃣ Ver requisitos para ingresar a la Agencia
#     4️⃣ Chat libre con un asesor
#     Responde con el número de la opción.
#     """)
#             return
#
#     # --- PASO ESPECIAL: Selección ciudad principal según país ---
#     if paso == 5:
#         # Si ya mostramos opciones, validamos la respuesta a la ciudad
#         ciudad_seleccionada = texto.strip()
#         ciudades_mostradas = respuestas.setdefault(numero, {}).get("ciudades_mostradas")
#
#         if ciudades_mostradas:
#             # El usuario debe responder con número válido o "otra"
#             if ciudad_seleccionada.isdigit():
#                 idx = int(ciudad_seleccionada) - 1
#                 if idx >= 0 and idx < len(ciudades_mostradas):
#                     ciudad = ciudades_mostradas[idx]
#                     respuestas[numero]["ciudad"] = ciudad
#                     guardar_respuesta(numero, 5, ciudad)
#                     usuarios_flujo[numero] += 1
#                     enviar_pregunta(numero, usuarios_flujo[numero])
#                     return
#                 elif idx == len(ciudades_mostradas):
#                     # Eligió "Otra"
#                     usuarios_flujo[numero] = "ciudad_otro"
#                     enviar_mensaje(numero, "Por favor, escribe tu ciudad principal:")
#                     return
#             # Si no válido, pídelo de nuevo
#             enviar_mensaje(numero, "Por favor elige una opción válida (ejemplo: 1, 2 ... o el número de 'Otra').")
#             return
#
#         # Si no hay ciudades guardadas, es la primera vez que llega a este paso
#         pais_num = respuestas.setdefault(numero, {}).get(4)
#         clave_pais = mapa_paises.get(str(pais_num))
#         ciudades = ciudades_por_pais.get(clave_pais)
#         if ciudades:
#             # Mostrar opciones y guardar para validarlas luego
#             opciones = "\n".join([f"{i+1}. {ciudad}" for i, ciudad in enumerate(ciudades)])
#             opciones += f"\n{len(ciudades)+1}. Otra (especifica)"
#             respuestas[numero]["ciudades_mostradas"] = ciudades
#             enviar_mensaje(numero, f"📌 Elige tu ciudad principal:\n{opciones}")
#             return
#         else:
#             # Si el país no está en la lista, pide ciudad en texto libre
#             usuarios_flujo[numero] = "ciudad_otro"
#             enviar_mensaje(numero, "Por favor, escribe tu ciudad principal:")
#             return
#
#     elif paso == "ciudad_otro":
#         # Guarda la ciudad escrita por el usuario
#         respuestas[numero]["ciudad"] = texto.strip()
#         guardar_respuesta(numero, 5, texto.strip())
#         usuarios_flujo[numero] = 6
#         enviar_pregunta(numero, 6)
#         return
#
#     # Plataformas (selección múltiple)
#     if paso == 13:
#         seleccion = validar_opciones_multiples(texto, opciones_plataformas)
#         if not seleccion:
#             enviar_mensaje(numero, "❌ Respuesta inválida. Ejemplo válido: 1,3,5")
#             return
#         respuestas.setdefault(numero, {})["plataformas"] = seleccion
#         if "8" in seleccion:  # "Otro"
#             usuarios_flujo[numero] = "plataforma_otro_nombre"
#             enviar_mensaje(numero, "Indica el nombre de la otra plataforma:")
#         else:
#             usuarios_flujo[numero] = 14
#             enviar_pregunta(numero, 14)
#         return
#
#     elif paso == "plataforma_otro_nombre":
#         respuestas[numero]["plataforma_otro"] = texto
#         usuarios_flujo[numero] = "plataforma_otro_experiencia"
#         enviar_mensaje(numero, f"¿Cuántos años de experiencia tienes en {texto}?")
#         return
#
#     elif paso == "plataforma_otro_experiencia":
#         if not texto.isdigit():
#             enviar_mensaje(numero, "Por favor ingresa solo el número de años (ejemplo: 2)")
#             return
#         respuestas[numero]["plataforma_otro_experiencia"] = int(texto)
#         usuarios_flujo[numero] = 14
#         enviar_pregunta(numero, 14)
#         return
#
#     # Tipo de contenido (selección múltiple)
#     if paso == 15:
#         seleccion = validar_opciones_multiples(texto, tiposContenido_opciones)
#         if not seleccion:
#             enviar_mensaje(numero, "❌ Respuesta inválida. Ejemplo válido: 1,4,7")
#             return
#         respuestas.setdefault(numero, {})["tipos_contenido"] = seleccion
#         if "13" in seleccion:  # "Otro"
#             usuarios_flujo[numero] = "contenido_otro_nombre"
#             enviar_mensaje(numero, "Indica el tipo de contenido adicional:")
#         else:
#             usuarios_flujo[numero] = 16
#             enviar_pregunta(numero, 16)
#         return
#
#     elif paso == "contenido_otro_nombre":
#         respuestas[numero]["contenido_otro"] = texto
#         usuarios_flujo[numero] = 16
#         enviar_pregunta(numero, 16)
#         return
#
#     # Intereses (selección múltiple)
#     if paso == 16:
#         seleccion = validar_opciones_multiples(texto, interesesOpciones_opciones)
#         if not seleccion:
#             enviar_mensaje(numero, "❌ Respuesta inválida. Ejemplo válido: 2,8,12")
#             return
#         respuestas.setdefault(numero, {})["intereses"] = seleccion
#         if "23" in seleccion:  # "Otro"
#             usuarios_flujo[numero] = "interes_otro_nombre"
#             enviar_mensaje(numero, "Indica el interés adicional:")
#         else:
#             usuarios_flujo[numero] = 17
#             enviar_mensaje(numero, "✅ Gracias, completaste todas las preguntas.")
#             consolidar_perfil(numero)
#         return
#
#     elif paso == "interes_otro_nombre":
#         respuestas[numero]["interes_otro"] = texto
#         usuarios_flujo[numero] = 17
#         enviar_mensaje(numero, "✅ Gracias, completaste todas las preguntas.")
#         consolidar_perfil(numero)
#         return
#
#     # ----- PASOS GENÉRICOS -----
#     # Ejemplo: validación de edad
#     if paso == 2:
#         try:
#             edad = int(texto)
#             if not (0 < edad < 120):
#                 raise ValueError
#         except Exception:
#             enviar_mensaje(numero, "⚠️ Por favor, ingresa una edad válida (número entre 1 y 119).")
#             return
#
#     # Guardar la respuesta
#     guardar_respuesta(numero, paso, texto)
#
#     # Avanzar al siguiente paso (si hay más)
#     if paso < len(preguntas):
#         usuarios_flujo[numero] += 1
#         enviar_pregunta(numero, usuarios_flujo[numero])
#     else:
#         del usuarios_flujo[numero]
#         enviar_mensaje(numero, "✅ Gracias, completaste todas las preguntas.")
#         consolidar_perfil(numero)

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

def guardar_respuesta(numero: str, paso: Union[int, str], texto: Any):
    """
    Guarda la respuesta del usuario para un paso, aceptando cualquier tipo de valor.
    Serializa listas y diccionarios como JSON.
    """
    # Serializa el valor si es lista o dict
    if isinstance(texto, (list, dict)):
        valor_guardar = json.dumps(texto, ensure_ascii=False)
    else:
        valor_guardar = str(texto)
    print(f"GUARDADO: {numero} | Paso: {paso} | Valor: {valor_guardar}")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO perfil_creador_flujo_temp (telefono, paso, respuesta)
            VALUES (%s, %s, %s)
            ON CONFLICT (telefono, paso) DO UPDATE SET respuesta = EXCLUDED.respuesta
        """, (numero, str(paso), valor_guardar))
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