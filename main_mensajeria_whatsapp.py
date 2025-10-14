from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import os, json
from dotenv import load_dotenv
from enviar_msg_wp import enviar_plantilla_generica, enviar_mensaje_texto_simple,enviar_boton_iniciar_Completa,enviar_botones_Completa
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

def enviar_botones(numero: str, texto: str, botones: list):
    return enviar_botones_Completa(
        token=TOKEN,
        numero_id=PHONE_NUMBER_ID,
        telefono_destino=numero,
        texto=texto,
        botones=botones
    )

import time

# 🗂️ Cachés en memoria con timestamp
usuarios_flujo = {}   # {numero: (paso, timestamp)}
usuarios_roles = {}   # {numero: (rol, timestamp)}

# Tiempo de vida en segundos (1 hora = 3600)
TTL = 1800


def actualizar_flujo(numero, paso):
    """Actualiza el paso del flujo sin perder otros datos del usuario."""
    if numero not in usuarios_flujo or not isinstance(usuarios_flujo[numero], dict):
        usuarios_flujo[numero] = {}
    usuarios_flujo[numero]["paso"] = paso
    usuarios_flujo[numero]["timestamp"] = time.time()


def obtener_flujo(numero):

    cache = usuarios_flujo.get(numero)
    ahora = time.time()

    if not cache:
        return None

    # ✅ Formato nuevo (dict)
    if isinstance(cache, dict):
        t = cache.get("timestamp", 0)
        if ahora - t < TTL:
            return cache.get("paso")

    # ⚙️ Compatibilidad con formato antiguo (tuple)
    elif isinstance(cache, tuple) and len(cache) == 2:
        paso, t = cache
        if ahora - t < TTL:
            return paso

    # 🧹 Limpieza automática si expiró o no coincide formato
    usuarios_flujo.pop(numero, None)
    return None


def obtener_rol_usuario(numero):
    cache = usuarios_roles.get(numero)
    now = time.time()
    # Verifica que el cache sea una tupla (rol, tiempo) y esté vigente
    if cache and isinstance(cache, tuple) and len(cache) == 2:
        rol, cached_at = cache
        if now - cached_at < TTL:
            return rol
        else:
            usuarios_roles.pop(numero, None)  # Expira por tiempo
    else:
        usuarios_roles.pop(numero, None)  # Limpia formatos incorrectos

    # Consulta en la base de datos si no hay cache válido
    usuario = buscar_usuario_por_telefono(numero)
    if usuario:
        rol = usuario.get("rol", "aspirante")
    else:
        rol = "aspirante"

    usuarios_roles[numero] = (rol, now)
    return rol

def consultar_rol_bd(numero):
    usuario = buscar_usuario_por_telefono(numero)
    if usuario:
        return usuario.get("rol", "aspirante")
    return "aspirante"

def enviar_menu_principal(numero, rol=None, nombre=None):
    # Obtener el rol del usuario si no se pasa explícitamente
    if rol is None:
        rol = obtener_rol_usuario(numero)

    # Obtener el nombre desde la base de datos si no se pasa explícitamente
    if nombre is None:
        usuario = buscar_usuario_por_telefono(numero)
        nombre = usuario.get("nombre") if usuario and usuario.get("nombre") else ""

    encabezado = f"👋 ¡Hola {nombre}! 📋 Te damos este menú de opciones:\n\n" if nombre else "👋 ¡Hola! 📋 Te damos este menú de opciones:\n\n"

    # --- MENÚ POR ROL ---
    if rol == "aspirante":
        mensaje = (
            f"{encabezado}"
            "1️⃣ Actualizar mi información de perfil\n"
            "2️⃣ Análisis y diagnóstico de mi perfil\n"
            "3️⃣ Requisitos para ingresar a la agencia\n"
            "4️⃣ Chat libre con un asesor\n"
            "5️⃣ Preguntas frecuentes\n\n"
            "Por favor responde con el número de la opción."
        )

    elif rol == "creador":
        mensaje = (
            f"{encabezado}"
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
            f"{encabezado}"
            "1️⃣ Ver panel de control\n"
            "2️⃣ Ver todos los perfiles\n"
            "3️⃣ Enviar comunicado a creadores/aspirantes\n"
            "4️⃣ Gestión de recursos\n"
            "5️⃣ Chat libre con el equipo"
        )

    else:
        mensaje = (
            f"{encabezado}"
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

def eliminar_flujo_temp(numero: str):
    """Elimina todos los datos temporales de la encuesta para un número."""
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM perfil_creador_flujo_temp
            WHERE telefono = %s
        """, (numero,))
        conn.commit()
        print(f"🗑️ Datos temporales eliminados para {numero}")
    except Exception as e:
        if 'conn' in locals():
            conn.rollback()
        print("❌ Error eliminando flujo temporal:", e)
    finally:
        try:
            cur.close()
        except:
            pass
        try:
            conn.close()
        except:
            pass



def enviar_diagnostico(numero: str):
    """Envía el diagnóstico de un usuario tomando el campo mejoras_sugeridas de perfil_creador."""
    try:
        with psycopg2.connect(INTERNAL_DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # 1️⃣ Buscar el creador por su número
                cur.execute("""
                    SELECT id, usuario, COALESCE(nombre_real, usuario)
                    FROM creadores
                    WHERE whatsapp = %s
                """, (numero,))
                creador = cur.fetchone()

                if not creador:
                    print(f"⚠️ No se encontró creador con whatsapp {numero}")
                    enviar_mensaje(numero, "No encontramos tu perfil en el sistema. Verifica tu número.")
                    return

                creador_id, usuario, nombre_real = creador

                # 2️⃣ Obtener mejoras_sugeridas desde perfil_creador
                cur.execute("""
                    SELECT mejoras_sugeridas
                    FROM perfil_creador
                    WHERE creador_id = %s
                """, (creador_id,))
                fila = cur.fetchone()

        # 3️⃣ Armar el diagnóstico
        if not fila or not fila[0] or not fila[0].strip():
            diagnostico = (
                f"🔎 Diagnóstico para {nombre_real}:\n"
                "Aún estamos preparando la evaluación de tu perfil. "
                "Te avisaremos tan pronto esté lista. ⏳"
            )
        else:
            mejoras = fila[0].strip()
            diagnostico = f"🔎 Diagnóstico para {nombre_real}:\n\n{mejoras}"

        # 4️⃣ Enviar el diagnóstico
        enviar_mensaje(numero, diagnostico)
        print(f"✅ Diagnóstico enviado correctamente a {numero} ({nombre_real})")

    except Exception as e:
        print(f"❌ Error al enviar diagnóstico a {numero}: {e}")
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
    "7": "work_medio_study_medio",  # ← Nuevo valor según tu frontend
    "8": "disponible_total",
    "9": "otro"
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
    "1": "Fuente de ingresos principal",
    "2": "Fuente de ingresos secundario",
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

import unicodedata

def _norm(s: str) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.strip().lower()

# País → zona horaria (valores según tu fuente)
_PAIS_A_TZ = {
    # México
    _norm("México"): "America/Mexico_City",

    # Colombia / Perú / Ecuador / Panamá
    _norm("Colombia"): "America/Bogota",
    _norm("Perú"): "America/Bogota",
    _norm("Ecuador"): "America/Bogota",
    _norm("Panamá"): "America/Bogota",

    # Venezuela / Bolivia / Paraguay
    _norm("Venezuela"): "America/Caracas",
    _norm("Bolivia"): "America/Caracas",
    _norm("Paraguay"): "America/Caracas",

    # Chile
    _norm("Chile"): "America/Santiago",

    # Argentina / Uruguay
    _norm("Argentina"): "America/Argentina/Buenos_Aires",
    _norm("Uruguay"): "America/Argentina/Buenos_Aires",

    # “Centroamérica” (tu valor custom)
    _norm("Costa Rica"): "America/CentralAmerica",
    _norm("El Salvador"): "America/CentralAmerica",
    _norm("Guatemala"): "America/CentralAmerica",
    _norm("Honduras"): "America/CentralAmerica",
    _norm("Nicaragua"): "America/CentralAmerica",

    # Cuba
    _norm("Cuba"): "America/Cuba",

    # Caribe (Puerto Rico, República Dominicana)
    _norm("Puerto Rico"): "America/Santo_Domingo",
    _norm("República Dominicana"): "America/Santo_Domingo",

    # Brasil
    _norm("Brasil"): "America/Sao_Paulo",
}

def infer_zona_horaria(pais: str | None) -> str | None:
    if not pais:
        return None
    return _PAIS_A_TZ.get(_norm(pais))

def redondear_a_un_decimal(valor):
    return float(Decimal(valor).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))

def procesar_respuestas(respuestas):
    datos = {}

    datos["nombre"] = respuestas.get(1)
    datos["edad"] = int(respuestas.get(2)) if respuestas.get(2) else None
    datos["genero"] = map_genero.get(respuestas.get(3))
    datos["pais"] = map_paises.get(respuestas.get(4))

    # Ciudad: corrige antes de guardar
    ciudad_usuario = respuestas.get(5)
    if ciudad_usuario:
        resultado = validar_aceptar_ciudad(ciudad_usuario)
        datos["ciudad"] = resultado["ciudad"]
    else:
        datos["ciudad"] = None

    datos["actividad_actual"] = map_actividad.get(respuestas.get(6))
    datos["intencion_trabajo"] = map_intencion.get(respuestas.get(7))
    datos["tiempo_disponible"] = int(respuestas.get(10)) if respuestas.get(10) and respuestas.get(10).isdigit() else None
    datos["frecuencia_lives"] = int(respuestas.get(11)) if respuestas.get(11) and respuestas.get(11).isdigit() else None

    # ⬇️ NUEVO: zona_horaria con base al país
    if datos.get("pais"):
        tz = infer_zona_horaria(datos["pais"])
        if tz:
            datos["zona_horaria"] = tz

    # Experiencia TikTok Live (paso 8 y 9)
    experiencia_tiktok = 0
    if respuestas.get(8, "").lower() in {"si", "sí", "s"}:
        try:
            meses = int(respuestas.get(9, 0))
            experiencia_tiktok = round(meses / 12, 1)
        except:
            experiencia_tiktok = 0

    experiencia = {
        "TikTok Live": experiencia_tiktok,
        "Bigo Live": 0,
        "NimoTV": 0,
        "Twitch": 0,
        "Otro": 0
    }
    datos["experiencia_otras_plataformas"] = json.dumps(experiencia)

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

                # ⬅️ AÑADIMOS el teléfono al update de perfil_creador
                datos_update["telefono"] = telefono

                # ✅ Si hay nombre, actualizamos también en la tabla creadores
                if datos_update.get("nombre"):
                    cur.execute("""
                                       UPDATE creadores 
                                       SET nombre_real=%s 
                                       WHERE id=%s
                                   """, (datos_update["nombre"], creador_id))
                    print(f"🧩 Actualizado nombre_real='{datos_update['nombre']}' en creadores")

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



# --------------------
# PREGUNTAS ASPIRANTES
# --------------------

preguntas = {
    1: "👤✨ ¿Cuál es tu nombre completo sin apellidos?",

    2: (
        "🎂 {nombre}, dime por favor en qué rango de edad te encuentras:\n"
        "1️⃣ 👶 Menos de 18 años\n"
        "2️⃣ 🧑 18 - 24 años\n"
        "3️⃣ 👨‍🦱 25 - 34 años\n"
        "4️⃣ 👩‍🦳 35 - 45 años\n"
        "5️⃣ 🧓 Más de 45 años"
    ),

    3: (
        "🚻 ¿Qué género eres?:\n"
        "1️⃣ ♂️ Masculino\n"
        "2️⃣ ♀️ Femenino\n"
        "3️⃣ 🌈 Otro\n"
        "4️⃣ 🙊 Prefiero no decir"
    ),

    4: (
        "🌎 {nombre}, es importante conocer en qué país te encuentras para continuar en el proceso:\n"
        "1️⃣ 🇦🇷 Argentina\n"
        "2️⃣ 🇧🇴 Bolivia\n"
        "3️⃣ 🇨🇱 Chile\n"
        "4️⃣ 🇨🇴 Colombia\n"
        "5️⃣ 🇨🇷 Costa Rica\n"
        "6️⃣ 🇨🇺 Cuba\n"
        "7️⃣ 🇪🇨 Ecuador\n"
        "8️⃣ 🇸🇻 El Salvador\n"
        "9️⃣ 🇬🇹 Guatemala\n"
        "🔟 🇭🇳 Honduras\n"
        "1️⃣1️⃣ 🇲🇽 México\n"
        "1️⃣2️⃣ 🇳🇮 Nicaragua\n"
        "1️⃣3️⃣ 🇵🇦 Panamá\n"
        "1️⃣4️⃣ 🇵🇾 Paraguay\n"
        "1️⃣5️⃣ 🇵🇪 Perú\n"
        "1️⃣6️⃣ 🇵🇷 Puerto Rico\n"
        "1️⃣7️⃣ 🇩🇴 República Dominicana\n"
        "1️⃣8️⃣ 🇺🇾 Uruguay\n"
        "1️⃣9️⃣ 🇻🇪 Venezuela\n"
        "2️⃣0️⃣ 🌍 Otro (escribe tu país)"
    ),

    5: "🏙️ ¿En qué ciudad estás? (escríbela en texto)",

    6: (
        "👔 Me gustaría conocer tu actividad actual:\n"
        "1️⃣ 🎓 Estudia tiempo completo\n"
        "2️⃣ 📚 Estudia medio tiempo\n"
        "3️⃣ 💼 Trabaja tiempo completo\n"
        "4️⃣ 🕒 Trabaja medio tiempo\n"
        "5️⃣ 🔍 Buscando empleo\n"
        "6️⃣ 🚀 Emprendiendo\n"
        "7️⃣ ⏳ Trabaja/emprende medio tiempo y estudia medio tiempo\n"
        "8️⃣ 🟢 Disponible tiempo completo\n"
        "9️⃣ ❓ Otro"
    ),

    7: (
        "🌟 {nombre}, dime cuál es tu objetivo principal en la plataforma TikTok:\n"
        "1️⃣ 💰 Fuente de ingresos principal\n"
        "2️⃣ 🪙 Fuente de ingresos secundaria\n"
        "3️⃣ 🎭 Hobby, pero me gustaría profesionalizarlo\n"
        "4️⃣ 😄 Diversión, sin intención profesional\n"
        "5️⃣ 🤔 No estoy seguro"
    ),

    8: "📺 ¿Tienes experiencia transmitiendo lives en TikTok? Contesta *sí* o *no*.",

    9: "⏱️ ¿Cuántos meses de experiencia tienes en TikTok Live?",

    10: (
        "🕰️ ¿Cuánto tiempo en horas estarías dispuesto/a por día para hacer lives?\n"
        "1️⃣ ⏳ 0-1 hrs\n"
        "2️⃣ ⏰ 1-3 hrs\n"
        "3️⃣ 🕺 Más de 3 hrs"
    ),

    11: (
        "📅 ¿Cuántos días a la semana podrías transmitir?\n"
        "1️⃣ 1-2 días\n"
        "2️⃣ 3-5 días\n"
        "3️⃣ 🌞 Todos los días\n"
        "4️⃣ 🚫 Ninguno"
    ),
}

# ------------------------------------------------------------------
# ------------------------------------------------------------------
# MENSAJES
# ------------------------------------------------------------------
Mensaje_bienvenida = (
    "👋 Bienvenido a Prestige Agency Live."
    "Soy *Prestigio*, tu asistente de experiencia 🤖.\n"
    "Es un gusto acompañarte en este proceso de aplicación. 🚀\n\n"
    "Para comenzar, dime por favor:\n"
    "¿Cuál es tu usuario de TikTok para validar en la plataforma?"
)

Mensaje_encuesta_incompleta = (
    "📝 Hemos detectado que aún no has finalizado tu encuesta.\n\n"
    "Por favor, complétala para que podamos continuar con tu proceso en *Prestige Agency Live*. 💫\n\n"
    "¿Deseas retomarla ahora?"
)


def mensaje_confirmar_nombre(nombre: str) -> str:
    return f"Veo que tu nombre o seudónimo es {nombre}. Para continuar Contesta *sí* o *no*."

def mensaje_proteccion_datos() -> str:
    return (
        "🔒 *Protección de datos y consentimiento*\n\n"
        "Antes de continuar, se te harán *preguntas personales básicas* para evaluar tu perfil como aspirante a creador de contenido en *Prestige Agency Live*.\n\n"
        "Tus datos serán usados únicamente para este proceso y tienes derecho a conocer, actualizar o eliminar tu información en cualquier momento.\n\n"
        "Si aceptas y deseas iniciar la encuesta, haz clic en el siguiente botón."
    )

def mensaje_encuesta_final_parte1(nombre: str | None = None) -> str:

    if nombre:
        return (
            f"{nombre}, ya para finalizar esta primera parte del proceso, "
            "es importante que respondas estas 2 preguntas 💪"
        )
    else:
        return (
            "Ya para finalizar esta primera parte del proceso, "
            "es importante que respondas estas 2 preguntas 💪"
        )


def mensaje_encuesta_final(nombre: str | None = None) -> str:
    if nombre:
        return (
            f"✅ ¡Gracias, *{nombre}*! 🙌\n"
            "Prestige validará tu información y en las próximas 2 horas te daremos una respuesta.\n\n"
            "Si prefieres, también puedes consultarla desde el menú de opciones."
        )
    else:
        return (
            "✅ ¡Gracias! 🙌\n"
            "Prestige validará tu información y en las próximas 2 horas te daremos una respuesta.\n\n"
            "Si prefieres, también puedes consultarla desde el menú de opciones."
        )



def obtener_nombre_usuario(numero: str) -> str | None:
    datos = usuarios_flujo.get(numero)
    if isinstance(datos, dict):
        return datos.get("nombre")
    # Limpieza automática si el valor es inválido
    usuarios_flujo.pop(numero, None)
    return None


def asegurar_flujo(numero: str) -> dict:
    if numero not in usuarios_flujo or not isinstance(usuarios_flujo[numero], dict):
        usuarios_flujo[numero] = {"timestamp": time.time()}
    return usuarios_flujo[numero]

def enviar_preguntas_frecuentes(numero):
    """
    Envía una lista de preguntas frecuentes al usuario por WhatsApp.
    Temporal: se puede luego conectar a una base de datos o archivo dinámico.
    """
    mensaje = (
        "❓ *Preguntas Frecuentes (FAQ)*\n\n"
        "1️⃣ *¿Qué requisitos necesito para ingresar a la Agencia Prestige?*\n"
        "Debes tener una cuenta activa en TikTok, con contenido propio y al menos 50 seguidores.\n\n"
        "2️⃣ *¿Debo tener experiencia previa?*\n"
        "No es necesario. Contamos con capacitaciones para nuevos creadores.\n\n"
        "3️⃣ *¿Cuánto tiempo tarda el proceso de ingreso?*\n"
        "Generalmente entre 2 y 5 días hábiles, dependiendo de la respuesta a las entrevistas.\n\n"
        "4️⃣ *¿Puedo monetizar mis transmisiones en vivo?*\n"
        "Sí, una vez seas parte de la Agencia y cumplas los requisitos de TikTok Live.\n\n"
        "5️⃣ *¿Quién me asesora durante el proceso?*\n"
        "Uno de nuestros managers o asesores de reclutamiento te acompañará paso a paso.\n\n"
        "✨ Si deseas volver al menú principal, escribe *menu*."
    )
    enviar_mensaje(numero, mensaje)


def manejar_respuesta_v0(numero, texto):
    texto = texto.strip()
    texto_normalizado = texto.lower()
    paso = obtener_flujo(numero)
    rol = obtener_rol_usuario(numero)
    flujo = asegurar_flujo(numero)  # 🔒 Inicialización segura
    nombre = flujo.get("nombre") or obtener_nombre_usuario(numero)

    # --- 1️⃣ SALUDOS INICIALES ---
    if texto_normalizado in {"hola", "buenas", "saludos", "brillar"}:
        usuario_bd = buscar_usuario_por_telefono(numero)
        if usuario_bd:
            nombre = usuario_bd.get("nombre", "").split(" ")[0] or ""
            rol = usuario_bd.get("rol", "aspirante")
            enviar_menu_principal(numero, rol=rol, nombre=nombre)
        else:
            enviar_mensaje(numero, Mensaje_bienvenida)
            actualizar_flujo(numero, "esperando_usuario_tiktok")
        return

    # --- 2️⃣ VOLVER AL MENÚ PRINCIPAL ---
    if texto_normalizado in {"menu", "menú", "volver", "inicio"}:
        usuarios_flujo.pop(numero, None)
        enviar_menu_principal(numero, rol)
        return

    # 🚫 CHAT LIBRE NO PROCESA FLUJOS
    if paso == "chat_libre":
        return

    # --- 3️⃣ MENÚ PRINCIPAL POR ROL ---
    if paso is None:
        opciones = texto_normalizado
        match rol:
            # --- 🌟 MENÚ ASPIRANTE PERSONALIZADO ---
            case "aspirante":
                match opciones:
                    case "1" | "mi información" | "perfil":
                        actualizar_flujo(numero, 1)
                        enviar_pregunta(numero, 1)
                    case "2" | "análisis" | "diagnóstico" | "diagnostico":
                        actualizar_flujo(numero, "diagnostico")
                        enviar_diagnostico(numero)
                        usuarios_flujo.pop(numero, None)
                    case "3" | "requisitos":
                        actualizar_flujo(numero, "requisitos")
                        enviar_requisitos(numero)
                        usuarios_flujo.pop(numero, None)
                    case "4" | "chat libre":
                        actualizar_flujo(numero, "chat_libre")
                        enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
                    case "5" | "preguntas" | "faq":
                        actualizar_flujo(numero, "faq")
                        enviar_preguntas_frecuentes(numero)
                        usuarios_flujo.pop(numero, None)
                    case _:
                        enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
                return

            # --- 🎬 MENÚ CREADOR ---
            case "creador":
                match opciones:
                    case "1":
                        actualizar_flujo(numero, 1)
                        enviar_pregunta(numero, 1)
                    case "3":
                        actualizar_flujo(numero, "asesoria")
                        enviar_mensaje(numero, "📌 Un asesor se pondrá en contacto contigo pronto.")
                        usuarios_flujo.pop(numero, None)
                    case "4":
                        actualizar_flujo(numero, "recursos")
                        enviar_recursos_exclusivos(numero)
                        usuarios_flujo.pop(numero, None)
                    case "5":
                        actualizar_flujo(numero, "eventos")
                        enviar_eventos(numero)
                        usuarios_flujo.pop(numero, None)
                    case "6":
                        actualizar_flujo(numero, "soporte")
                        enviar_mensaje(numero, "📩 Describe tu problema y el equipo técnico te responderá.")
                    case "7" | "chat libre":
                        actualizar_flujo(numero, "chat_libre")
                        enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
                    case "8":
                        actualizar_flujo(numero, "estadisticas")
                        enviar_estadisticas(numero)
                        usuarios_flujo.pop(numero, None)
                    case "9":
                        actualizar_flujo(numero, "baja")
                        solicitar_baja(numero)
                        usuarios_flujo.pop(numero, None)
                    case _:
                        enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
                return

            # --- 🛠️ MENÚ ADMIN ---
            case "admin":
                match opciones:
                    case "1":
                        actualizar_flujo(numero, "panel")
                        enviar_panel_control(numero)
                    case "2":
                        actualizar_flujo(numero, "ver_perfiles")
                        enviar_perfiles(numero)
                        usuarios_flujo.pop(numero, None)
                    case "3":
                        actualizar_flujo(numero, "comunicado")
                        enviar_mensaje(numero, "✉️ Escribe el comunicado a enviar a creadores/aspirantes:")
                    case "4":
                        actualizar_flujo(numero, "recursos_admin")
                        gestionar_recursos(numero)
                        usuarios_flujo.pop(numero, None)
                    case "5" | "chat libre":
                        actualizar_flujo(numero, "chat_libre")
                        enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
                    case _:
                        enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
                return

            # --- 🧩 DEFAULT (SIN ROL) ---
            case _:
                if opciones == "1":
                    actualizar_flujo(numero, "info")
                    enviar_info_general(numero)
                else:
                    enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
                return

    # --- 4️⃣ FLUJO DE ENCUESTA ---
    if isinstance(paso, int):
        if paso == 1:
            if len(texto) < 3:
                enviar_mensaje(numero, "⚠️ Ingresa tu nombre completo (mínimo 3 caracteres).")
                return
            flujo["nombre"] = texto.title().strip()
            nombre = flujo["nombre"]

        validaciones = {
            2: lambda t: t.isdigit() and 1 <= int(t) <= 5,
            3: lambda t: t in {"1", "2", "3", "4"},
            4: lambda t: t in list(mapa_paises.keys()) + ["20"] or t.lower() in [v.lower() for v in mapa_paises.values()],
            6: lambda t: t in [str(i) for i in range(1, 10)],
            7: lambda t: t in [str(i) for i in range(1, 6)],
            9: lambda t: t in {"1", "2", "3"},
            10: lambda t: t in {"1", "2", "3", "4"}
        }

        if paso in validaciones and not validaciones[paso](texto_normalizado):
            enviar_mensaje(numero, f"⚠️ Ingresa una opción válida para la pregunta {paso}.")
            return

        if paso == 5:
            resultado = validar_aceptar_ciudad(texto)
            texto = resultado["ciudad"]
            # enviar_mensaje(numero, f"✅ Ciudad reconocida: {texto}")

        if paso == 7:
            enviar_mensaje(numero, "📌 ¿Tienes experiencia transmitiendo lives en TikTok? Contesta *sí* o *no*.")
            actualizar_flujo(numero, "7b")
            return

        if paso == 8:
            try:
                meses = int(texto)
                if not (0 <= meses <= 999):
                    raise ValueError
            except ValueError:
                enviar_mensaje(numero, "⚠️ Ingresa un número válido de meses (0–999).")
                return
            enviar_mensaje(numero, mensaje_encuesta_final_parte1(nombre))

        guardar_respuesta(numero, paso, texto)
        siguiente = paso + 1

        # ✅ Finalización del flujo
        if siguiente not in preguntas:
            usuarios_flujo.pop(numero, None)
            enviar_mensaje(numero, mensaje_encuesta_final(nombre))
            consolidar_perfil(numero)
            enviar_mensaje(numero, '✨ Para ir al menú principal escribe **brillar**')
            return

        actualizar_flujo(numero, siguiente)
        texto_pregunta = preguntas[siguiente]
        if "{nombre}" in texto_pregunta:
            texto_pregunta = texto_pregunta.format(nombre=nombre)
        enviar_mensaje(numero, texto_pregunta)
        return

    # --- 5️⃣ PREGUNTA CONDICIONAL (7b) ---
    if paso == "7b":
        if texto_normalizado in {"si", "sí", "s"}:
            enviar_mensaje(numero, preguntas[8])
            actualizar_flujo(numero, 8)
        elif texto_normalizado in {"no", "n"}:
            guardar_respuesta(numero, 8, "0")
            enviar_mensaje(numero, preguntas[9])
            actualizar_flujo(numero, 9)
        else:
            enviar_mensaje(numero, "Por favor responde solo *sí* o *no*.")


def manejar_menuv0(numero, texto, paso, rol):
    texto_normalizado = texto.strip().lower()
    # --- SALUDOS UNIVERSALES ---
    if texto_normalizado in {"hola", "buenas", "saludos", "brillar"}:
        usuario_bd = buscar_usuario_por_telefono(numero)
        if usuario_bd:
            nombre = usuario_bd.get("nombre", "").split(" ")[0] or ""
            rol = usuario_bd.get("rol", "aspirante")
            enviar_menu_principal(numero, rol=rol, nombre=nombre)
        else:
            enviar_mensaje(numero, Mensaje_bienvenida)
            actualizar_flujo(numero, "esperando_usuario_tiktok")
        return True

    # --- VOLVER AL MENÚ PRINCIPAL ---
    if texto_normalizado in {"menu", "menú", "volver", "inicio"}:
        usuarios_flujo.pop(numero, None)
        enviar_menu_principal(numero, rol)
        return True

    # --- MENU PRINCIPAL POR ROL ---
    if paso is None:
        match rol:
            case "aspirante":
                match texto_normalizado:
                    case "1" | "mi información" | "perfil":
                        actualizar_flujo(numero, 1)
                        enviar_pregunta(numero, 1)
                    case "2" | "análisis" | "diagnóstico" | "diagnostico":
                        actualizar_flujo(numero, "diagnostico")
                        enviar_diagnostico(numero)
                        usuarios_flujo.pop(numero, None)
                    case "3" | "requisitos":
                        actualizar_flujo(numero, "requisitos")
                        enviar_requisitos(numero)
                        usuarios_flujo.pop(numero, None)
                    case "4" | "chat libre":
                        actualizar_flujo(numero, "chat_libre")
                        enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
                    case "5" | "preguntas" | "faq":
                        actualizar_flujo(numero, "faq")
                        enviar_preguntas_frecuentes(numero)
                        usuarios_flujo.pop(numero, None)
                    case _:
                        enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
                return True
            # ... otros roles igual que antes ...
    return False  # No fue menú

# =========================
# Orquestador
# =========================
def manejar_respuesta(numero, texto):
    texto = texto.strip()
    texto_normalizado = texto.lower()

    # Estado actual
    paso = obtener_flujo(numero)              # puede ser None, int, o string (p.e. "chat_libre")
    rol = obtener_rol_usuario(numero)
    asegurar_flujo(numero)                    # asegura estructura en caché

    # 1) Atajos globales
    if _es_saludo(texto_normalizado):
        _procesar_saludo(numero, rol)
        return

    if _es_volver_menu(texto_normalizado):
        usuarios_flujo.pop(numero, None)
        enviar_menu_principal(numero, rol)
        return

    if paso == "chat_libre":
        # En chat libre no procesamos menú/encuesta
        return

    # 2) Delegar según estado
    if paso is None or isinstance(paso, str):
        manejar_menu(numero, texto_normalizado, rol)     # 👈 MENÚ
    elif isinstance(paso, int):
        manejar_encuesta(numero, texto, texto_normalizado, paso, rol)  # 👈 ENCUESTA
    else:
        enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")


# =========================
# Utilidades simples
# =========================
def _es_saludo(tn: str) -> bool:
    return tn in {"hola", "buenas", "saludos", "brillar"}

def _es_volver_menu(tn: str) -> bool:
    return tn in {"menu", "menú", "volver", "inicio"}

def _procesar_saludo(numero, rol_actual):
    usuario_bd = buscar_usuario_por_telefono(numero)
    if usuario_bd:
        nombre = (usuario_bd.get("nombre") or "").split(" ")[0]
        rol = usuario_bd.get("rol", rol_actual or "aspirante")
        enviar_menu_principal(numero, rol=rol, nombre=nombre)
    else:
        enviar_mensaje(numero, Mensaje_bienvenida)
        actualizar_flujo(numero, "esperando_usuario_tiktok")


# =========================
#  MENÚ (por rol)
# =========================
def manejar_menu(numero, texto_normalizado, rol):
    # Menús por rol

    if rol == "aspirante":
        if texto_normalizado in {"1", "actualizar mi información", "perfil"}:
            enviar_mensaje(numero, "✏️ Perfecto. Vamos a actualizar tu información. Empecemos...")
            marcar_encuesta_no_finalizada(numero)
            eliminar_flujo_temp(numero)
            actualizar_flujo(numero, 1)
            enviar_pregunta(numero, 1)
            return
        if texto_normalizado in {"2", "análisis", "diagnóstico", "diagnostico"}:
            actualizar_flujo(numero, "diagnostico")
            enviar_diagnostico(numero)
            usuarios_flujo.pop(numero, None)
            return
        if texto_normalizado in {"3", "requisitos"}:
            actualizar_flujo(numero, "requisitos")
            enviar_requisitos(numero)
            usuarios_flujo.pop(numero, None)
            return
        if texto_normalizado in {"4", "chat libre"}:
            actualizar_flujo(numero, "chat_libre")
            enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
            return
        if texto_normalizado in {"5", "preguntas", "faq"}:
            actualizar_flujo(numero, "faq")
            enviar_preguntas_frecuentes(numero)
            usuarios_flujo.pop(numero, None)
            return
        # Si no es una opción válida: muestra SIEMPRE el menú principal de aspirante
        nombre = buscar_usuario_por_telefono(numero).get("nombre", "").split(" ")[0] or ""
        enviar_menu_principal(numero, rol=rol, nombre=nombre)
        return

    if rol == "creador":
        if texto_normalizado == "1":
            actualizar_flujo(numero, 1)
            enviar_pregunta(numero, 1)
            return
        if texto_normalizado == "3":
            actualizar_flujo(numero, "asesoria")
            enviar_mensaje(numero, "📌 Un asesor se pondrá en contacto contigo pronto.")
            usuarios_flujo.pop(numero, None)
            return
        if texto_normalizado == "4":
            actualizar_flujo(numero, "recursos")
            enviar_recursos_exclusivos(numero)
            usuarios_flujo.pop(numero, None)
            return
        if texto_normalizado == "5":
            actualizar_flujo(numero, "eventos")
            enviar_eventos(numero)
            usuarios_flujo.pop(numero, None)
            return
        if texto_normalizado == "6":
            actualizar_flujo(numero, "soporte")
            enviar_mensaje(numero, "📩 Describe tu problema y el equipo técnico te responderá.")
            return
        if texto_normalizado in {"7", "chat libre"}:
            actualizar_flujo(numero, "chat_libre")
            enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
            return
        if texto_normalizado == "8":
            actualizar_flujo(numero, "estadisticas")
            enviar_estadisticas(numero)
            usuarios_flujo.pop(numero, None)
            return
        if texto_normalizado == "9":
            actualizar_flujo(numero, "baja")
            solicitar_baja(numero)
            usuarios_flujo.pop(numero, None)
            return
        # Si no es una opción válida: muestra SIEMPRE el menú principal de creador
        nombre = buscar_usuario_por_telefono(numero).get("nombre", "").split(" ")[0] or ""
        enviar_menu_principal(numero, rol=rol, nombre=nombre)
        return

    if rol == "admin":
        if texto_normalizado == "1":
            actualizar_flujo(numero, "panel")
            enviar_panel_control(numero)
            return
        if texto_normalizado == "2":
            actualizar_flujo(numero, "ver_perfiles")
            enviar_perfiles(numero)
            usuarios_flujo.pop(numero, None)
            return
        if texto_normalizado == "3":
            actualizar_flujo(numero, "comunicado")
            enviar_mensaje(numero, "✉️ Escribe el comunicado a enviar a creadores/aspirantes:")
            return
        if texto_normalizado == "4":
            actualizar_flujo(numero, "recursos_admin")
            gestionar_recursos(numero)
            usuarios_flujo.pop(numero, None)
            return
        if texto_normalizado in {"5", "chat libre"}:
            actualizar_flujo(numero, "chat_libre")
            enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
            return
        # Si no es una opción válida: muestra SIEMPRE el menú principal de admin
        nombre = buscar_usuario_por_telefono(numero).get("nombre", "").split(" ")[0] or ""
        enviar_menu_principal(numero, rol=rol, nombre=nombre)
        return

    # Rol desconocido → menú básico
    if texto_normalizado == "1":
        actualizar_flujo(numero, "info")
        enviar_info_general(numero)
        return

    # Cualquier otro caso, menú básico para rol desconocido
    nombre = buscar_usuario_por_telefono(numero).get("nombre", "").split(" ")[0] or ""
    enviar_menu_principal(numero, rol=rol, nombre=nombre)

def manejar_encuesta(numero, texto, texto_normalizado, paso, rol):
    # — Paso 1: Nombre
    if paso == 1:
        if len(texto) < 3:
            enviar_mensaje(numero, "⚠️ Ingresa tu nombre completo (mínimo 3 caracteres).")
            return
        flujo = asegurar_flujo(numero)
        flujo["nombre"] = texto.title().strip()

    # — Paso 2: Edad
    if paso == 2:
        try:
            edad = int(texto)
            if not (0 < edad < 120):
                raise ValueError
        except:
            enviar_mensaje(numero, "⚠️ Ingresa una edad válida (1–119).")
            return

    # — Paso 3: Género
    if paso == 3 and texto not in {"1", "2", "3", "4"}:
        enviar_mensaje(numero, "⚠️ Ingresa solo el número (1–4).")
        return

    # — Paso 4: País
    if paso == 4:
        opciones_validas = [str(i) for i in range(1, 21)]
        if texto not in opciones_validas and len(texto) < 2:
            enviar_mensaje(numero, "⚠️ Ingresa el número de tu país.")
            return

    # — Paso 5: Ciudad
    if paso == 5 and len(texto) < 2:
        enviar_mensaje(numero, "⚠️ Ingresa una ciudad válida.")
    else:
        resultado = validar_aceptar_ciudad(texto)
        if resultado["corregida"]:
            texto = resultado["ciudad"]
            enviar_mensaje(numero, f"✅ Ciudad reconocida y corregida: {texto}")
        return


    # — Paso 6: Actividad actual
    if paso == 6 and texto not in [str(i) for i in range(1, 9)]:
        enviar_mensaje(numero, "⚠️ Ingresa solo el número (1–8).")
        return

    # — Paso 7: Intención principal
    if paso == 7 and texto not in [str(i) for i in range(1, 6)]:
        enviar_mensaje(numero, "⚠️ Ingresa solo el número (1–5).")
        return

    # — Paso 8: ¿Tiene experiencia transmitiendo?
    if paso == 8:
        if texto_normalizado in {"si", "sí", "s"}:
            texto = "sí"
        elif texto_normalizado in {"no", "n"}:
            texto = "no"
        else:
            enviar_mensaje(numero, "⚠️ Por favor responde solo *sí* o *no*.")
            return

        guardar_respuesta(numero, paso, texto)
        nombre = (asegurar_flujo(numero).get("nombre") or "").split(" ")[0]

        # 👉 Si respondió NO, salta la 10
        if texto == "no":
            enviar_mensaje(
                numero,
                f"✅ Gracias {nombre}. Para continuar en el proceso, responde estas **3 preguntas adicionales**."
            )
            actualizar_flujo(numero, 10)
            enviar_mensaje(numero, preguntas[10].format(nombre=nombre))
            return

        # 👉 Si respondió SÍ, continúa normalmente a la 9
        actualizar_flujo(numero, 9)
        enviar_mensaje(numero, preguntas[9])
        return

    # — Paso 9: Meses de experiencia (solo si respondió sí)
    if paso == 9:
        try:
            meses = int(texto)
            if not (0 <= meses <= 999):
                raise ValueError
        except:
            enviar_mensaje(numero, "⚠️ Ingresa un número válido de meses (0–999).")
            return

        guardar_respuesta(numero, paso, texto)

        # ✅ Muestra el mensaje puente después de la 9
        nombre = (asegurar_flujo(numero).get("nombre") or "").split(" ")[0]
        enviar_mensaje(
            numero,
            f"✅ Gracias {nombre}. Para continuar en el proceso, responde estas **3 preguntas adicionales**."
        )

        # Avanza al paso 10
        actualizar_flujo(numero, 10)
        enviar_mensaje(numero, preguntas[10].format(nombre=nombre))
        return

    # — Paso 10: Horas/día
    if paso == 10:
        if texto not in {"1", "2", "3"}:
            enviar_mensaje(numero, "⚠️ Ingresa solo el número (1–3).")
            return

    # — Paso 11: Días a la semana para transmitir
    if paso == 11:
        if texto not in {"1", "2", "3", "4"}:
            enviar_mensaje(numero, "⚠️ Ingresa solo el número (1–4).")
            return

    # Guardar respuesta general
    guardar_respuesta(numero, paso, texto)

    # Determinar siguiente paso
    siguiente = paso + 1
    ultimo_paso = max(preguntas.keys())

    # 🏁 Si terminó la encuesta
    if siguiente > ultimo_paso:
        usuarios_flujo.pop(numero, None)
        nombre = (asegurar_flujo(numero).get("nombre") or "").split(" ")[0]
        enviar_mensaje(numero, mensaje_encuesta_final(nombre))
        consolidar_perfil(numero)

        # ✅ Marcar encuesta completada en la BD
        completada = marcar_encuesta_completada(numero)
        if completada:
            enviar_mensaje(numero, "📊 Tu encuesta fue registrada correctamente en el sistema.")
        else:
            enviar_mensaje(numero, "⚠️ No pudimos confirmar el registro en la base de datos, pero tus respuestas fueron guardadas.")

        enviar_mensaje(numero, '✨ Para ir al menú principal escribe **brillar**')
        return

    # Continuar flujo normal
    actualizar_flujo(numero, siguiente)
    texto_pregunta = preguntas[siguiente]
    nombre = (asegurar_flujo(numero).get("nombre") or "").split(" ")[0]
    if "{nombre}" in texto_pregunta:
        texto_pregunta = texto_pregunta.format(nombre=nombre)
    enviar_mensaje(numero, texto_pregunta)

def eliminar_flujo(numero: str):
    """Reinicia cualquier flujo o estado temporal del usuario."""
    usuarios_flujo.pop(numero, None)
    usuarios_temp.pop(numero, None)
    print(f"🧹 Flujo reiniciado para {numero}")

@router.post("/webhook")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    print("📩 Webhook recibido:", json.dumps(data, indent=2))

    try:
        cambios = data.get("entry", [])[0].get("changes", [])[0].get("value", {})
        mensajes = cambios.get("messages", [])
        if not mensajes:
            return {"status": "ok"}

        for mensaje in mensajes:
            numero = mensaje.get("from")
            tipo = mensaje.get("type")
            paso = obtener_flujo(numero)
            usuario_bd = buscar_usuario_por_telefono(numero)
            rol = obtener_rol_usuario(numero) if usuario_bd else None

            # === Obtén el texto antes de cualquier uso ===
            texto = mensaje.get("text", {}).get("body", "").strip()
            texto_lower = texto.lower()

            # === 4️⃣ CHAT LIBRE ===  (Esto va primero)
            if paso == "chat_libre":
                if tipo == "text":
                    guardar_mensaje(numero, texto, tipo="recibido", es_audio=False)
                elif tipo == "audio":
                    audio_id = mensaje.get("audio", {}).get("id")
                    url_cloudinary = descargar_audio(audio_id, TOKEN)
                    if url_cloudinary:
                        guardar_mensaje(numero, url_cloudinary, tipo="recibido", es_audio=True)
                        enviar_mensaje(numero, "🎧 Recibimos tu audio. Un asesor lo revisará pronto.")
                    else:
                        enviar_mensaje(numero, "⚠️ No se pudo procesar tu audio, inténtalo de nuevo.")
                return {"status": "ok"}

            # === 🟢 1️⃣ PRIORIDAD: MENSAJES INTERACTIVOS (botones) ===
            if tipo == "interactive":
                print("🔘 [DEBUG] Se recibió un mensaje interactivo:", json.dumps(mensaje, indent=2))

                interactive = mensaje.get("interactive", {})
                if interactive.get("type") == "button_reply":
                    button_data = interactive.get("button_reply", {})
                    button_id = button_data.get("id")
                    button_title = button_data.get("title")

                    print(f"🧩 [DEBUG] Botón presionado -> id='{button_id}', título='{button_title}'")
                    print(f"📍 [DEBUG] Paso actual del usuario: {paso}")

                    # ✅ Inicio de encuesta
                    if paso == "esperando_inicio_encuesta" and button_id == "iniciar_encuesta":
                        print("🚀 [DEBUG] Botón 'iniciar_encuesta' detectado. Iniciando encuesta...")
                        actualizar_flujo(numero, 1)
                        enviar_pregunta(numero, 1)
                        return {"status": "ok"}

                    # Aquí se pueden agregar más botones en el futuro
                    enviar_mensaje(numero, "Este botón no es válido en este momento.")
                    return {"status": "ok"}

            print(f"📍 [DEBUG] número={numero}, paso={paso}, texto='{texto_lower}'")

            # === 1️⃣ NUEVO USUARIO: FLUJO DE ONBOARDING Y ENCUESTA ===
            if tipo == "text" and not usuario_bd:
                # Si el paso guardado no tiene sentido, reiniciamos el flujo
                if paso not in [None, "esperando_usuario_tiktok", "confirmando_nombre", "esperando_inicio_encuesta"]:
                    print(f"⚠️ Reiniciando flujo para {numero}, paso anterior: {paso}")
                    eliminar_flujo(numero)  # limpia memoria o caché
                    paso = None

                # === Inicio del flujo ===
                if paso is None:
                    enviar_mensaje(numero, Mensaje_bienvenida)
                    actualizar_flujo(numero, "esperando_usuario_tiktok")
                    return {"status": "ok"}

                # Se espera usuario de TikTok
                if paso == "esperando_usuario_tiktok":
                    usuario_tiktok = texto.strip()
                    aspirante = buscar_aspirante_por_usuario_tiktok(usuario_tiktok)
                    if aspirante:
                        nombre = aspirante.get("nickname") or aspirante.get("nombre_real") or "(sin nombre)"
                        enviar_mensaje(numero, mensaje_confirmar_nombre(nombre))
                        actualizar_flujo(numero, "confirmando_nombre")
                        usuarios_temp[numero] = aspirante
                    else:
                        enviar_mensaje(numero, "❌ No encontramos ese usuario de TikTok. ¿Podrías verificarlo?")
                    return {"status": "ok"}

                # Confirmar nickname y actualizar teléfono
                if paso == "confirmando_nombre":
                    if texto_lower in ["si", "sí", "s"]:
                        aspirante = usuarios_temp.get(numero)
                        if aspirante:
                            actualizar_telefono_aspirante(aspirante["id"], numero)
                        enviar_botones(
                            numero,
                            texto=mensaje_proteccion_datos(),
                            botones=[{"id": "iniciar_encuesta", "title": "✅ Sí, quiero iniciar"}]
                        )
                        actualizar_flujo(numero, "esperando_inicio_encuesta")
                    elif texto_lower in ["no", "n"]:
                        enviar_mensaje(numero, "❌ Por favor verifica tu nombre o usuario de TikTok.")
                    else:
                        enviar_mensaje(numero, "⚠️ Por favor responde solo *sí* o *no* para continuar.")
                    return {"status": "ok"}

                # Si el usuario está esperando iniciar la encuesta pero escribe texto
                if paso == "esperando_inicio_encuesta":
                    if texto_lower in ["sí", "si", "ok", "dale", "listo", "empezar", "continuar"]:
                        print("🚀 [DEBUG] Usuario escribió 'sí' o equivalente, iniciando encuesta manualmente.")
                        actualizar_flujo(numero, 1)
                        enviar_pregunta(numero, 1)
                        return {"status": "ok"}

                    if texto_lower in ["hola", "buenas", "hey", "saludos", "brillar"]:
                        print("💬 [DEBUG] Usuario saludó, repitiendo bienvenida.")
                        enviar_mensaje(
                            numero,
                            "👋 ¡Hola! Aún no has iniciado la encuesta. "
                            "Por favor presiona el botón *✅ Sí, quiero iniciar* o escribe *sí* para comenzar 🚀"
                        )
                        return {"status": "ok"}

                    enviar_mensaje(numero, "💬 Escribe *sí* o presiona el botón para comenzar la encuesta 📋")
                    return {"status": "ok"}

                # Flujo de encuesta
                if isinstance(paso, int):
                    manejar_encuesta(numero, texto, texto_lower, paso, "aspirante")
                    return {"status": "ok"}

            # === 2️⃣ ASPIRANTE EN BASE DE DATOS ===
            if usuario_bd and rol == "aspirante":
                finalizada = encuesta_finalizada(numero)
                # Si encuesta finalizada, SIEMPRE muestra el menú para cualquier mensaje
                if finalizada:
                    manejar_menu(numero, texto_lower, rol)
                    return {"status": "ok"}

                # Si no ha terminado la encuesta
                if not finalizada:
                    if texto_lower in {"brillar", "menu", "menú", "inicio"}:
                        enviar_mensaje(numero, "🚩 No has finalizado tu encuesta. Por favor continúa para completar la información.")
                        ultimo_paso = 1
                        actualizar_flujo(numero, ultimo_paso)
                        enviar_pregunta(numero, ultimo_paso)
                        return {"status": "ok"}

                    # Flujo normal de encuesta
                    if isinstance(paso, int):
                        manejar_encuesta(numero, texto, texto_lower, paso, rol)
                        return {"status": "ok"}

                    manejar_respuesta(numero, texto)
                    return {"status": "ok"}

            # === 3️⃣ ADMIN O CREADOR EN BD ===
            if usuario_bd and rol in ("admin", "creador", "creadores"):
                manejar_menu(numero, texto_lower, rol)
                return {"status": "ok"}

            print(f"🟣 DEBUG CHAT LIBRE - paso actual: {paso}")

    except Exception as e:
        print("❌ Error procesando webhook:", e)
        import traceback
        traceback.print_exc()

    return {"status": "ok"}



# @router.post("/webhook")
# async def whatsapp_webhook(request: Request):
#     data = await request.json()
#     print("📩 Webhook recibido:", json.dumps(data, indent=2))
#
#     try:
#         cambios = data.get("entry", [])[0].get("changes", [])[0].get("value", {})
#         mensajes = cambios.get("messages", [])
#         if not mensajes:
#             return {"status": "ok"}
#
#         for mensaje in mensajes:
#             numero = mensaje.get("from")
#             tipo = mensaje.get("type")
#             paso = obtener_flujo(numero)
#             usuario_bd = buscar_usuario_por_telefono(numero)
#             rol = obtener_rol_usuario(numero) if usuario_bd else None
#
#             # === Obtén el texto antes de cualquier uso ===
#             texto = mensaje.get("text", {}).get("body", "").strip()
#             texto_lower = texto.lower()
#
#             # === 4️⃣ CHAT LIBRE ===  (Esto va primero)
#             if paso == "chat_libre":
#                 if tipo == "text":
#                     guardar_mensaje(numero, texto, tipo="recibido", es_audio=False)
#                 elif tipo == "audio":
#                     audio_id = mensaje.get("audio", {}).get("id")
#                     url_cloudinary = descargar_audio(audio_id, TOKEN)
#                     if url_cloudinary:
#                         guardar_mensaje(numero, url_cloudinary, tipo="recibido", es_audio=True)
#                         enviar_mensaje(numero, "🎧 Recibimos tu audio. Un asesor lo revisará pronto.")
#                     else:
#                         enviar_mensaje(numero, "⚠️ No se pudo procesar tu audio, inténtalo de nuevo.")
#                 return {"status": "ok"}
#
#             # === 🟢 1️⃣ PRIORIDAD: MENSAJES INTERACTIVOS (botones) ===
#             if tipo == "interactive":
#                 print("🔘 [DEBUG] Se recibió un mensaje interactivo:", json.dumps(mensaje, indent=2))
#
#                 interactive = mensaje.get("interactive", {})
#                 if interactive.get("type") == "button_reply":
#                     button_data = interactive.get("button_reply", {})
#                     button_id = button_data.get("id")
#                     button_title = button_data.get("title")
#
#                     print(f"🧩 [DEBUG] Botón presionado -> id='{button_id}', título='{button_title}'")
#                     print(f"📍 [DEBUG] Paso actual del usuario: {paso}")
#
#                     # ✅ Inicio de encuesta
#                     if paso == "esperando_inicio_encuesta" and button_id == "iniciar_encuesta":
#                         print("🚀 [DEBUG] Botón 'iniciar_encuesta' detectado. Iniciando encuesta...")
#                         actualizar_flujo(numero, 1)
#                         enviar_pregunta(numero, 1)
#                         return {"status": "ok"}
#
#                     # Aquí se pueden agregar más botones en el futuro
#                     enviar_mensaje(numero, "Este botón no es válido en este momento.")
#                     return {"status": "ok"}
#
#             print(f"📍 [DEBUG] número={numero}, paso={paso}, texto='{texto_lower}'")
#
#             # === 1️⃣ NUEVO USUARIO: FLUJO DE ONBOARDING Y ENCUESTA ===
#             if tipo == "text" and not usuario_bd:
#                 # Si el paso guardado no tiene sentido, reiniciamos el flujo
#                 if paso not in [None, "esperando_usuario_tiktok", "confirmando_nombre", "esperando_inicio_encuesta"]:
#                     print(f"⚠️ Reiniciando flujo para {numero}, paso anterior: {paso}")
#                     eliminar_flujo(numero)  # limpia memoria o caché
#                     paso = None
#
#                 # === Inicio del flujo ===
#                 if paso is None:
#                     enviar_mensaje(numero, Mensaje_bienvenida)
#                     actualizar_flujo(numero, "esperando_usuario_tiktok")
#                     return {"status": "ok"}
#
#                 # Se espera usuario de TikTok
#                 if paso == "esperando_usuario_tiktok":
#                     usuario_tiktok = texto.strip()
#                     aspirante = buscar_aspirante_por_usuario_tiktok(usuario_tiktok)
#                     if aspirante:
#                         nombre = aspirante.get("nickname") or aspirante.get("nombre_real") or "(sin nombre)"
#                         enviar_mensaje(numero, mensaje_confirmar_nombre(nombre))
#                         actualizar_flujo(numero, "confirmando_nombre")
#                         usuarios_temp[numero] = aspirante
#                     else:
#                         enviar_mensaje(numero, "❌ No encontramos ese usuario de TikTok. ¿Podrías verificarlo?")
#                     return {"status": "ok"}
#
#                 # Confirmar nickname y actualizar teléfono
#                 if paso == "confirmando_nombre":
#                     if texto_lower in ["si", "sí", "s"]:
#                         aspirante = usuarios_temp.get(numero)
#                         if aspirante:
#                             actualizar_telefono_aspirante(aspirante["id"], numero)
#                         enviar_botones(
#                             numero,
#                             texto=mensaje_proteccion_datos(),
#                             botones=[{"id": "iniciar_encuesta", "title": "✅ Sí, quiero iniciar"}]
#                         )
#                         actualizar_flujo(numero, "esperando_inicio_encuesta")
#                     elif texto_lower in ["no", "n"]:
#                         enviar_mensaje(numero, "❌ Por favor verifica tu nombre o usuario de TikTok.")
#                     else:
#                         enviar_mensaje(numero, "⚠️ Por favor responde solo *sí* o *no* para continuar.")
#                     return {"status": "ok"}
#
#                 # Si el usuario está esperando iniciar la encuesta pero escribe texto
#                 if paso == "esperando_inicio_encuesta":
#                     if texto_lower in ["sí", "si", "ok", "dale", "listo", "empezar", "continuar"]:
#                         print("🚀 [DEBUG] Usuario escribió 'sí' o equivalente, iniciando encuesta manualmente.")
#                         actualizar_flujo(numero, 1)
#                         enviar_pregunta(numero, 1)
#                         return {"status": "ok"}
#
#                     if texto_lower in ["hola", "buenas", "hey", "saludos", "brillar"]:
#                         print("💬 [DEBUG] Usuario saludó, repitiendo bienvenida.")
#                         enviar_mensaje(
#                             numero,
#                             "👋 ¡Hola! Aún no has iniciado la encuesta. "
#                             "Por favor presiona el botón *✅ Sí, quiero iniciar* o escribe *sí* para comenzar 🚀"
#                         )
#                         return {"status": "ok"}
#
#                     enviar_mensaje(numero, "💬 Escribe *sí* o presiona el botón para comenzar la encuesta 📋")
#                     return {"status": "ok"}
#
#                 # Flujo de encuesta
#                 if isinstance(paso, int):
#                     manejar_encuesta(numero, texto, texto_lower, paso, "aspirante")
#                     return {"status": "ok"}
#
#             # === 2️⃣ ASPIRANTE EN BASE DE DATOS ===
#             if usuario_bd and rol == "aspirante":
#                 finalizada = encuesta_finalizada(numero)
#                 # Si encuesta finalizada y escribe comando de menú
#                 if finalizada and texto_lower in {"brillar", "menu", "menú", "inicio"}:
#                     nombre = usuario_bd.get("nombre", "").split(" ")[0] or ""
#                     enviar_menu_principal(numero, rol=rol, nombre=nombre)
#                     return {"status": "ok"}
#
#                 # Si no ha terminado la encuesta
#                 if not finalizada:
#                     if texto_lower in {"brillar", "menu", "menú", "inicio"}:
#                         enviar_mensaje(numero, "🚩 No has finalizado tu encuesta. Por favor continúa para completar la información.")
#                         ultimo_paso = 1
#                         actualizar_flujo(numero, ultimo_paso)
#                         enviar_pregunta(numero, ultimo_paso)
#                         return {"status": "ok"}
#
#                     # Flujo normal de encuesta
#                     if isinstance(paso, int):
#                         manejar_encuesta(numero, texto, texto_lower, paso, rol)
#                         return {"status": "ok"}
#
#                     manejar_respuesta(numero, texto)
#                     return {"status": "ok"}
#
#                 # Si encuesta finalizada y responde opción de menú
#                 if finalizada:
#                     manejar_menu(numero, texto_lower, rol)
#                     return {"status": "ok"}
#
#             # === 3️⃣ ADMIN O CREADOR EN BD ===
#             if usuario_bd and rol in ("admin", "creador", "creadores"):
#                 if texto_lower in {"brillar", "menu", "menú", "inicio"}:
#                     nombre = usuario_bd.get("nombre", "").split(" ")[0] or ""
#                     enviar_menu_principal(numero, rol=rol, nombre=nombre)
#                     return {"status": "ok"}
#
#                 manejar_menu(numero, texto_lower, rol)
#                 return {"status": "ok"}
#
#             print(f"🟣 DEBUG CHAT LIBRE - paso actual: {paso}")
#
#     except Exception as e:
#         print("❌ Error procesando webhook:", e)
#         import traceback
#         traceback.print_exc()
#
#     return {"status": "ok"}


# @router.post("/webhook")
# async def whatsapp_webhook(request: Request):
#     data = await request.json()
#     print("📩 Webhook recibido:", json.dumps(data, indent=2))
#
#     try:
#         cambios = data.get("entry", [])[0].get("changes", [])[0].get("value", {})
#         mensajes = cambios.get("messages", [])
#         if not mensajes:
#             return {"status": "ok"}
#
#         for mensaje in mensajes:
#             numero = mensaje.get("from")
#             tipo = mensaje.get("type")
#             paso = obtener_flujo(numero)
#             usuario_bd = buscar_usuario_por_telefono(numero)
#             rol = obtener_rol_usuario(numero) if usuario_bd else None
#
#             # === 4️⃣ CHAT LIBRE ===  (PON ESTO AQUÍ)
#             if paso == "chat_libre":
#                 if tipo == "text":
#                     guardar_mensaje(numero, texto, tipo="recibido", es_audio=False)
#                 elif tipo == "audio":
#                     audio_id = mensaje.get("audio", {}).get("id")
#                     url_cloudinary = descargar_audio(audio_id, TOKEN)
#                     if url_cloudinary:
#                         guardar_mensaje(numero, url_cloudinary, tipo="recibido", es_audio=True)
#                         enviar_mensaje(numero, "🎧 Recibimos tu audio. Un asesor lo revisará pronto.")
#                     else:
#                         enviar_mensaje(numero, "⚠️ No se pudo procesar tu audio, inténtalo de nuevo.")
#                 return {"status": "ok"}
#
#             # === 🟢 1️⃣ PRIORIDAD: MENSAJES INTERACTIVOS (botones) ===
#             if tipo == "interactive":
#                 print("🔘 [DEBUG] Se recibió un mensaje interactivo:", json.dumps(mensaje, indent=2))
#
#                 interactive = mensaje.get("interactive", {})
#                 if interactive.get("type") == "button_reply":
#                     button_data = interactive.get("button_reply", {})
#                     button_id = button_data.get("id")
#                     button_title = button_data.get("title")
#
#                     print(f"🧩 [DEBUG] Botón presionado -> id='{button_id}', título='{button_title}'")
#                     print(f"📍 [DEBUG] Paso actual del usuario: {paso}")
#
#                     # ✅ Inicio de encuesta
#                     if paso == "esperando_inicio_encuesta" and button_id == "iniciar_encuesta":
#                         print("🚀 [DEBUG] Botón 'iniciar_encuesta' detectado. Iniciando encuesta...")
#                         actualizar_flujo(numero, 1)
#                         enviar_pregunta(numero, 1)
#                         return {"status": "ok"}
#
#                     # Aquí se pueden agregar más botones en el futuro
#                     enviar_mensaje(numero, "Este botón no es válido en este momento.")
#                     return {"status": "ok"}
#
#             # === 🟡 2️⃣ MENSAJES DE TEXTO (solo si no es interactivo) ===
#             texto = mensaje.get("text", {}).get("body", "").strip()
#             texto_lower = texto.lower()
#             print(f"📍 [DEBUG] número={numero}, paso={paso}, texto='{texto_lower}'")
#
#             # === 1️⃣ NUEVO USUARIO: FLUJO DE ONBOARDING Y ENCUESTA ===
#             if tipo == "text" and not usuario_bd:
#                 # Si el paso guardado no tiene sentido, reiniciamos el flujo
#                 if paso not in [None, "esperando_usuario_tiktok", "confirmando_nombre", "esperando_inicio_encuesta"]:
#                     print(f"⚠️ Reiniciando flujo para {numero}, paso anterior: {paso}")
#                     eliminar_flujo(numero)  # limpia memoria o caché
#                     paso = None
#
#                 # === Inicio del flujo ===
#                 if paso is None:
#                     enviar_mensaje(numero, Mensaje_bienvenida)
#                     actualizar_flujo(numero, "esperando_usuario_tiktok")
#                     return {"status": "ok"}
#
#                 # Se espera usuario de TikTok
#                 if paso == "esperando_usuario_tiktok":
#                     usuario_tiktok = texto.strip()
#                     aspirante = buscar_aspirante_por_usuario_tiktok(usuario_tiktok)
#                     if aspirante:
#                         nombre = aspirante.get("nickname") or aspirante.get("nombre_real") or "(sin nombre)"
#                         enviar_mensaje(numero, mensaje_confirmar_nombre(nombre))
#                         actualizar_flujo(numero, "confirmando_nombre")
#                         usuarios_temp[numero] = aspirante
#                     else:
#                         enviar_mensaje(numero, "❌ No encontramos ese usuario de TikTok. ¿Podrías verificarlo?")
#                     return {"status": "ok"}
#
#                 # Confirmar nickname y actualizar teléfono
#                 if paso == "confirmando_nombre":
#                     if texto_lower in ["si", "sí", "s"]:
#                         aspirante = usuarios_temp.get(numero)
#                         if aspirante:
#                             actualizar_telefono_aspirante(aspirante["id"], numero)
#                         enviar_botones(
#                             numero,
#                             texto=mensaje_proteccion_datos(),
#                             botones=[{"id": "iniciar_encuesta", "title": "✅ Sí, quiero iniciar"}]
#                         )
#                         actualizar_flujo(numero, "esperando_inicio_encuesta")
#                     elif texto_lower in ["no", "n"]:
#                         enviar_mensaje(numero, "❌ Por favor verifica tu nombre o usuario de TikTok.")
#                     else:
#                         enviar_mensaje(numero, "⚠️ Por favor responde solo *sí* o *no* para continuar.")
#                     return {"status": "ok"}
#
#                 # Si el usuario está esperando iniciar la encuesta pero escribe texto
#                 if paso == "esperando_inicio_encuesta":
#                     if texto_lower in ["sí", "si", "ok", "dale", "listo", "empezar", "continuar"]:
#                         print("🚀 [DEBUG] Usuario escribió 'sí' o equivalente, iniciando encuesta manualmente.")
#                         actualizar_flujo(numero, 1)
#                         enviar_pregunta(numero, 1)
#                         return {"status": "ok"}
#
#                     if texto_lower in ["hola", "buenas", "hey", "saludos", "brillar"]:
#                         print("💬 [DEBUG] Usuario saludó, repitiendo bienvenida.")
#                         enviar_mensaje(
#                             numero,
#                             "👋 ¡Hola! Aún no has iniciado la encuesta. "
#                             "Por favor presiona el botón *✅ Sí, quiero iniciar* o escribe *sí* para comenzar 🚀"
#                         )
#                         return {"status": "ok"}
#
#                     enviar_mensaje(numero, "💬 Escribe *sí* o presiona el botón para comenzar la encuesta 📋")
#                     return {"status": "ok"}
#
#                 # Flujo de encuesta
#                 if isinstance(paso, int):
#                     manejar_encuesta(numero, texto, texto_lower, paso, "aspirante")
#                     return {"status": "ok"}
#
#             # === 2️⃣ ASPIRANTE EN BASE DE DATOS ===
#             if usuario_bd and rol == "aspirante":
#                 finalizada = encuesta_finalizada(numero)
#                 # Si encuesta finalizada y escribe comando de menú
#                 if finalizada and texto_lower in {"brillar", "menu", "menú", "inicio"}:
#                     nombre = usuario_bd.get("nombre", "").split(" ")[0] or ""
#                     enviar_menu_principal(numero, rol=rol, nombre=nombre)
#                     return {"status": "ok"}
#
#                 # Si no ha terminado la encuesta
#                 if not finalizada:
#                     if texto_lower in {"brillar", "menu", "menú", "inicio"}:
#                         enviar_mensaje(numero, "🚩 No has finalizado tu encuesta. Por favor continúa para completar la información.")
#                         ultimo_paso = 1
#                         actualizar_flujo(numero, ultimo_paso)
#                         enviar_pregunta(numero, ultimo_paso)
#                         return {"status": "ok"}
#
#                     # Flujo normal de encuesta
#                     if isinstance(paso, int):
#                         manejar_encuesta(numero, texto, texto_lower, paso, rol)
#                         return {"status": "ok"}
#
#                     manejar_respuesta(numero, texto)
#                     return {"status": "ok"}
#
#                 # Si encuesta finalizada y responde opción de menú
#                 if finalizada:
#                     manejar_menu(numero, texto_lower, rol)
#                     return {"status": "ok"}
#
#             # === 3️⃣ ADMIN O CREADOR EN BD ===
#             if usuario_bd and rol in ("admin", "creador", "creadores"):
#                 if texto_lower in {"brillar", "menu", "menú", "inicio"}:
#                     nombre = usuario_bd.get("nombre", "").split(" ")[0] or ""
#                     enviar_menu_principal(numero, rol=rol, nombre=nombre)
#                     return {"status": "ok"}
#
#                 manejar_menu(numero, texto_lower, rol)
#                 return {"status": "ok"}
#
#             print(f"🟣 DEBUG CHAT LIBRE - paso actual: {paso}")
#
#             # # === 4️⃣ CHAT LIBRE ===
#             # if paso == "chat_libre":
#             #     if tipo == "text":
#             #         guardar_mensaje(numero, texto, tipo="recibido", es_audio=False)
#             #     elif tipo == "audio":
#             #         audio_id = mensaje.get("audio", {}).get("id")
#             #         url_cloudinary = descargar_audio(audio_id, TOKEN)
#             #         if url_cloudinary:
#             #             guardar_mensaje(numero, url_cloudinary, tipo="recibido", es_audio=True)
#             #             enviar_mensaje(numero, "🎧 Recibimos tu audio. Un asesor lo revisará pronto.")
#             #         else:
#             #             enviar_mensaje(numero, "⚠️ No se pudo procesar tu audio, inténtalo de nuevo.")
#             #     return {"status": "ok"}
#
#     except Exception as e:
#         print("❌ Error procesando webhook:", e)
#         import traceback
#         traceback.print_exc()
#
#     return {"status": "ok"}


from pydantic import BaseModel

class RespuestaInput(BaseModel):
    numero: str
    paso: int
    respuesta: str

class ConsolidarInput(BaseModel):
    numero: str

@router.post("/respuesta")
def guardar_respuesta_web(data: RespuestaInput):
    try:
        guardar_respuesta(data.numero, data.paso, data.respuesta)
        return {"ok": True, "msg": "Respuesta guardada"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@router.post("/consolidar")
def consolidar_perfil_web(data: ConsolidarInput):
    try:
        consolidar_perfil(data.numero)
        return {"ok": True, "msg": "Perfil consolidado"}
    except Exception as e:
        return {"ok": False, "error": str(e)}




# @router.post("/webhook")
# async def whatsapp_webhook(request: Request):
#     data = await request.json()
#     print("📩 Webhook recibido:", json.dumps(data, indent=2))
#
#     try:
#         cambios = data.get("entry", [])[0].get("changes", [])[0].get("value", {})
#         mensajes = cambios.get("messages", [])
#         if not mensajes:
#             return {"status": "ok"}
#
#         for mensaje in mensajes:
#             numero = mensaje.get("from")
#             tipo = mensaje.get("type")
#             texto = mensaje.get("text", {}).get("body", "").strip()
#             texto_lower = texto.lower()
#
#             # --- Variables auxiliares ---
#             paso = obtener_flujo(numero)
#             usuario_bd = buscar_usuario_por_telefono(numero)
#             rol = obtener_rol_usuario(numero)
#
#             print(f"📍 [DEBUG] número={numero}, paso={paso}, texto='{texto_lower}'")
#
#             # === 1️⃣ COMANDOS UNIVERSALES: SALUDOS / MENÚ / BRILLAR ===
#             if tipo == "text":
#                 palabras_clave = ["hola","buenas","brilla", "menu"]
#                 if any(palabra in texto_lower for palabra in palabras_clave):
#                     usuarios_flujo.pop(numero, None)  # reinicia cualquier flujo activo
#
#                     if usuario_bd:
#                         nombre = usuario_bd.get("nombre", "").split(" ")[0] or ""
#                         rol = usuario_bd.get("rol", "aspirante")
#                         enviar_mensaje(numero, f"👋 ¡Hola {nombre}! 💫 Te damos este menú de opciones.")
#                         enviar_menu_principal(numero, rol=rol, nombre=nombre)
#                     else:
#                         enviar_mensaje(numero, Mensaje_bienvenida)
#                         actualizar_flujo(numero, "esperando_usuario_tiktok")
#
#                     print(f"🔁 [DEBUG] Reinicio de flujo con mensaje que contiene palabra clave ({numero})")
#                     return {"status": "ok"}
#
#             # === 2️⃣ NUEVO USUARIO SIN REGISTRO ===
#             if not usuario_bd and paso is None:
#                 enviar_mensaje(numero, Mensaje_bienvenida)
#                 actualizar_flujo(numero, "esperando_usuario_tiktok")
#                 print(f"🟢 [DEBUG] Flujo inicial -> esperando_usuario_tiktok ({numero})")
#                 return {"status": "ok"}
#
#             # === 3️⃣ FLUJO DE VERIFICACIÓN USUARIO TIKTOK ===
#             if paso == "esperando_usuario_tiktok" and tipo == "text":
#                 usuario_tiktok = texto.strip()
#                 aspirante = buscar_aspirante_por_usuario_tiktok(usuario_tiktok)
#
#                 # ----- Depuración -----
#                 print(f"🔍 Usuario TikTok recibido: {usuario_tiktok}")
#                 print(f"🔍 Aspirante encontrado: {aspirante}")
#                 print(f"🔍 usuarios_temp: {usuarios_temp}")
#                 print(f"🔍 paso actual: {paso}")
#
#                 if aspirante:
#                     nombre = aspirante.get("nickname") or aspirante.get("nombre_real") or "(sin nombre)"
#                     enviar_mensaje(numero, mensaje_confirmar_nombre(nombre))
#                     actualizar_flujo(numero, "confirmando_nombre")
#                     usuarios_temp[numero] = aspirante
#                 else:
#                     enviar_mensaje(numero, "❌ No encontramos ese usuario de TikTok. ¿Podrías verificarlo?")
#                 return {"status": "ok"}
#
#             # === 4️⃣ CONFIRMAR NOMBRE ===
#             if paso == "confirmando_nombre" and tipo == "text":
#                 texto_normalizado = texto.lower().strip()
#
#                 # ✅ Solo aceptamos 'sí' o 'no'
#                 if texto_normalizado in ["si", "sí", "s"]:
#                     aspirante = usuarios_temp.get(numero)
#                     if aspirante:
#                         actualizar_telefono_aspirante(aspirante["id"], numero)
#
#                     enviar_botones(
#                         numero,
#                         texto=mensaje_proteccion_datos(),
#                         botones=[{"id": "iniciar_encuesta", "title": "✅ Sí, quiero iniciar"}],
#                     )
#                     actualizar_flujo(numero, "esperando_inicio_encuesta")
#                 elif texto_normalizado in ["no", "n"]:
#                     # Usuario confirma que el nombre NO es correcto
#                     enviar_mensaje(numero, "❌ Por favor verifica tu nombre o usuario de TikTok.")
#                     # Mantener el flujo en 'confirmando_nombre' para reintentar
#                 else:
#                     # Cualquier otra respuesta
#                     enviar_mensaje(numero, "⚠️ Por favor responde solo *sí* o *no* para continuar.")
#                     # Mantener el flujo en 'confirmando_nombre' hasta recibir respuesta válida
#                 return {"status": "ok"}
#
#             # === 5️⃣ ESPERANDO INICIO ENCUESTA ===
#             if paso == "esperando_inicio_encuesta":
#                 interactive = mensaje.get("interactive", {})
#                 if interactive.get("type") == "button_reply":
#                     button_id = interactive.get("button_reply", {}).get("id")
#                     if button_id == "iniciar_encuesta":
#                         actualizar_flujo(numero, 1)
#                         enviar_pregunta(numero, 1)
#                         print(f"🟢 [DEBUG] Encuesta iniciada -> paso=1 ({numero})")
#                         return {"status": "ok"}
#
#                 enviar_mensaje(numero, "Por favor usa el botón para iniciar la encuesta.")
#                 return {"status": "ok"}
#
#             # === 6️⃣ ASIGNAR ROL SI FALTA ===
#             if usuario_bd and numero not in usuarios_roles:
#                 usuarios_roles[numero] = (usuario_bd["rol"], time.time())
#
#             # === 7️⃣ CHAT LIBRE ===
#             if paso == "chat_libre":
#                 if tipo == "text":
#                     guardar_mensaje(numero, texto, tipo="recibido", es_audio=False)
#                     print(f"💬 Chat libre de {numero}: {texto}")
#                 elif tipo == "audio":
#                     audio_id = mensaje.get("audio", {}).get("id")
#                     url_cloudinary = descargar_audio(audio_id, TOKEN)
#                     if url_cloudinary:
#                         guardar_mensaje(numero, url_cloudinary, tipo="recibido", es_audio=True)
#                         enviar_mensaje(numero, "🎧 Recibimos tu audio. Un asesor lo revisará pronto.")
#                     else:
#                         enviar_mensaje(numero, "⚠️ No se pudo procesar tu audio, inténtalo de nuevo.")
#                 return {"status": "ok"}
#
#             # === 8️⃣ REINICIO DESDE PLANTILLA ENVIADA PARA QUE ASPIRANTE CONTESTE UNA ENCUESTA CON BOTÓN “Sí, continuar” ===
#             if paso is None and tipo == "interactive":
#                 interactive = mensaje.get("interactive", {})
#                 boton_texto = interactive.get("button_reply", {}).get("title", "").lower()
#                 if boton_texto == "sí, continuar":
#                     actualizar_flujo(numero, 1)
#                     enviar_pregunta(numero, 1)
#                     print(f"🟢 [DEBUG] Flujo reiniciado -> paso=1 ({numero})")
#                     return {"status": "ok"}
#
#             # === 9️⃣ ACTIVAR CHAT LIBRE SEGÚN ROL ===
#             if paso is None and tipo == "text":
#                 rol_usuario = usuarios_roles.get(numero, ("",))[0]
#                 if (texto_lower in ["4", "chat libre"] and rol_usuario == "aspirante") or \
#                    (texto_lower in ["7", "chat libre"] and rol_usuario == "creador") or \
#                    (texto_lower in ["5", "chat libre"] and rol_usuario == "admin"):
#                     actualizar_flujo(numero, "chat_libre")
#                     enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                     return {"status": "ok"}
#
#             # === 🔟 MANEJAR RESPUESTA NORMAL (ENCUESTA) ===
#             manejar_respuesta(numero, texto)
#
#     except Exception as e:
#         print("❌ Error procesando webhook:", e)
#         traceback.print_exc()
#
#     return {"status": "ok"}


# @router.post("/webhook")
# async def whatsapp_webhook(request: Request):
#     data = await request.json()
#     print("📩 Webhook recibido:", json.dumps(data, indent=2))
#
#     try:
#         cambios = data.get("entry", [])[0].get("changes", [])[0].get("value", {})
#         mensajes = cambios.get("messages", [])
#         if not mensajes:
#             return {"status": "ok"}
#
#         for mensaje in mensajes:
#             numero = mensaje.get("from")
#             tipo = mensaje.get("type")
#             texto = mensaje.get("text", {}).get("body", "").strip()
#             texto_lower = texto.lower()
#
#             # --- Variables auxiliares ---
#             paso = obtener_flujo(numero)
#             usuario_bd = buscar_usuario_por_telefono(numero)
#             rol = obtener_rol_usuario(numero)
#
#             print(f"📍 [DEBUG] número={numero}, paso={paso}, texto='{texto_lower}'")
#
#             # === 1️⃣ MENSAJES DE CONTROL UNIVERSALES ===
#             if tipo == "text":
#                 # --- 👋 SALUDOS INICIALES ---
#                 if texto_lower in ["hola", "buenas", "saludos", "brillar"]:
#                     if usuario_bd:
#                         nombre = usuario_bd.get("nombre", "").split(" ")[0] or ""
#                         rol = usuario_bd.get("rol", "aspirante")
#                         enviar_menu_principal(numero, rol=rol, nombre=nombre)
#                     else:
#                         enviar_mensaje(numero, Mensaje_bienvenida)
#                         actualizar_flujo(numero, "esperando_usuario_tiktok")
#                     return {"status": "ok"}
#
#                 # --- 🔄 Reinicio manual del flujo (menú principal) con saludo personalizado ---
#                 if texto_lower in ["menu", "menú", "brillar"]:
#                     usuarios_flujo.pop(numero, None)
#                     if usuario_bd:
#                         nombre = usuario_bd.get("nombre", "").split(" ")[0] or ""
#                         rol = usuario_bd.get("rol", "aspirante")
#                         enviar_mensaje(numero, f"👋 ¡Hola {nombre}! Te damos nuevamente este menú de opciones:")
#                         enviar_menu_principal(numero, rol=rol, nombre=nombre)
#                     else:
#                         enviar_mensaje(numero, "✨ Has vuelto al menú principal.")
#                         enviar_menu_principal(numero, rol)
#                     return {"status": "ok"}
#
#             # === 2️⃣ NUEVO USUARIO ===
#             if not usuario_bd and paso is None:
#                 enviar_mensaje(numero, Mensaje_bienvenida)
#                 actualizar_flujo(numero, "esperando_usuario_tiktok")
#                 print(f"🟢 [DEBUG] Flujo inicial -> esperando_usuario_tiktok ({numero})")
#                 return {"status": "ok"}
#
#             # === 3️⃣ FLUJO DE VERIFICACIÓN USUARIO TIKTOK ===
#             if paso == "esperando_usuario_tiktok" and tipo == "text":
#                 usuario_tiktok = texto.strip()
#                 aspirante = buscar_aspirante_por_usuario_tiktok(usuario_tiktok)
#
#                 if aspirante:
#                     nombre = aspirante.get("nickname") or aspirante.get("nombre_real") or "(sin nombre)"
#                     enviar_mensaje(numero, mensaje_confirmar_nombre(nombre))
#                     actualizar_flujo(numero, "confirmando_nombre")
#                     usuarios_temp[numero] = aspirante
#                 else:
#                     enviar_mensaje(numero, "❌ No encontramos ese usuario de TikTok. ¿Podrías verificarlo?")
#                 return {"status": "ok"}
#
#             # === 4️⃣ CONFIRMAR NOMBRE ===
#             if paso == "confirmando_nombre" and tipo == "text":
#                 if texto_lower in ["si", "sí", "correcto", "yes", "ok", "sip", "acuerdo"]:
#                     aspirante = usuarios_temp.get(numero)
#                     if aspirante:
#                         actualizar_telefono_aspirante(aspirante["id"], numero)
#
#                     enviar_botones(
#                         numero,
#                         texto=mensaje_proteccion_datos(),
#                         botones=[{"id": "iniciar_encuesta", "title": "✅ Sí, quiero iniciar"}],
#                     )
#                     actualizar_flujo(numero, "esperando_inicio_encuesta")
#                 else:
#                     enviar_mensaje(numero, "Por favor escribe el nombre correcto o verifica tu usuario de TikTok.")
#                 return {"status": "ok"}
#
#             # === 5️⃣ ESPERANDO INICIO ENCUESTA ===
#             if paso == "esperando_inicio_encuesta":
#                 interactive = mensaje.get("interactive", {})
#                 if interactive.get("type") == "button_reply":
#                     button_id = interactive.get("button_reply", {}).get("id")
#                     if button_id == "iniciar_encuesta":
#                         actualizar_flujo(numero, 1)
#                         enviar_pregunta(numero, 1)
#                         print(f"🟢 [DEBUG] Encuesta iniciada -> paso=1 ({numero})")
#                         return {"status": "ok"}
#
#                 enviar_mensaje(numero, "Por favor usa el botón para iniciar la encuesta.")
#                 return {"status": "ok"}
#
#             # === 6️⃣ ASIGNAR ROL SI FALTA ===
#             if usuario_bd and numero not in usuarios_roles:
#                 usuarios_roles[numero] = (usuario_bd["rol"], time.time())
#
#             # === 7️⃣ CHAT LIBRE ===
#             if paso == "chat_libre":
#                 if tipo == "text":
#                     if texto_lower in ["menu", "menú", "brillar"]:
#                         usuarios_flujo.pop(numero, None)
#                         if usuario_bd:
#                             nombre = usuario_bd.get("nombre", "").split(" ")[0] or ""
#                             rol = usuario_bd.get("rol", "aspirante")
#                             enviar_mensaje(numero, f"👋 ¡Hola {nombre}! Te damos nuevamente este menú de opciones:")
#                             enviar_menu_principal(numero, rol=rol, nombre=nombre)
#                         else:
#                             enviar_mensaje(numero, "🔙 Has vuelto al menú principal.")
#                             enviar_menu_principal(numero, rol)
#                         return {"status": "ok"}
#
#                     guardar_mensaje(numero, texto, tipo="recibido", es_audio=False)
#                     print(f"💬 Chat libre de {numero}: {texto}")
#
#                 elif tipo == "audio":
#                     audio_id = mensaje.get("audio", {}).get("id")
#                     url_cloudinary = descargar_audio(audio_id, TOKEN)
#                     if url_cloudinary:
#                         guardar_mensaje(numero, url_cloudinary, tipo="recibido", es_audio=True)
#                         enviar_mensaje(numero, "🎧 Recibimos tu audio. Un asesor lo revisará pronto.")
#                     else:
#                         enviar_mensaje(numero, "⚠️ No se pudo procesar tu audio, inténtalo de nuevo.")
#                 return {"status": "ok"}
#
#             # === 8️⃣ REINICIO DESDE BOTÓN “Sí, continuar” ===
#             if paso is None and tipo == "interactive":
#                 interactive = mensaje.get("interactive", {})
#                 boton_texto = interactive.get("button_reply", {}).get("title", "").lower()
#                 if boton_texto == "sí, continuar":
#                     actualizar_flujo(numero, 1)
#                     enviar_pregunta(numero, 1)
#                     print(f"🟢 [DEBUG] Flujo reiniciado -> paso=1 ({numero})")
#                     return {"status": "ok"}
#
#             # === 9️⃣ ACTIVAR CHAT LIBRE SEGÚN ROL ===
#             if paso is None and tipo == "text":
#                 rol_usuario = usuarios_roles.get(numero, ("",))[0]
#                 if (texto_lower in ["4", "chat libre"] and rol_usuario == "aspirante") or \
#                    (texto_lower in ["7", "chat libre"] and rol_usuario == "creador") or \
#                    (texto_lower in ["5", "chat libre"] and rol_usuario == "admin"):
#                     actualizar_flujo(numero, "chat_libre")
#                     enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                     return {"status": "ok"}
#
#             # === 🔟 MANEJAR RESPUESTA NORMAL (ENCUESTA) ===
#             manejar_respuesta(numero, texto)
#
#     except Exception as e:
#         print("❌ Error procesando webhook:", e)
#         traceback.print_exc()
#
#     return {"status": "ok"}


# @router.post("/webhook")
# async def whatsapp_webhook(request: Request):
#     data = await request.json()
#     print("📩 Webhook recibido:", json.dumps(data, indent=2))
#
#     try:
#         cambios = data.get("entry", [])[0].get("changes", [])[0].get("value", {})
#         mensajes = cambios.get("messages", [])
#         if not mensajes:
#             return {"status": "ok"}
#
#         for mensaje in mensajes:
#             numero = mensaje.get("from")
#             tipo = mensaje.get("type")
#             texto = mensaje.get("text", {}).get("body", "").strip()
#             texto_lower = texto.lower()
#
#             # --- Variables auxiliares ---
#             paso = obtener_flujo(numero)
#             usuario_bd = buscar_usuario_por_telefono(numero)
#             rol = obtener_rol_usuario(numero)
#
#             print(f"📍 [DEBUG] número={numero}, paso={paso}, texto='{texto_lower}'")
#
#             # === 1️⃣ MENSAJES DE CONTROL UNIVERSALES ===
#             if tipo == "text":
#                 # --- 👋 SALUDOS INICIALES ---
#                 if texto_lower in ["hola", "buenas", "saludos"]:
#                     if usuario_bd:
#                         nombre = usuario_bd.get("nombre", "").split(" ")[0] or ""
#                         rol = usuario_bd.get("rol", "aspirante")
#                         # 🔹 Nueva versión del menú con saludo personalizado
#                         enviar_menu_principal(numero, rol=rol, nombre=nombre)
#                     else:
#                         enviar_mensaje(numero, Mensaje_bienvenida)
#                         actualizar_flujo(numero, "esperando_usuario_tiktok")
#                     return {"status": "ok"}
#
#                 # --- 🔄 Reinicio manual del flujo (menú principal)
#                 if texto_lower in ["menu", "menú", "brillar"]:
#                     usuarios_flujo.pop(numero, None)
#                     enviar_mensaje(numero, "✨ Has vuelto al menú principal.")
#                     enviar_menu_principal(numero, rol)
#                     return {"status": "ok"}
#
#             # === 2️⃣ NUEVO USUARIO ===
#             if not usuario_bd and paso is None:
#                 enviar_mensaje(numero, Mensaje_bienvenida)
#                 actualizar_flujo(numero, "esperando_usuario_tiktok")
#                 print(f"🟢 [DEBUG] Flujo inicial -> esperando_usuario_tiktok ({numero})")
#                 return {"status": "ok"}
#
#             # === 3️⃣ FLUJO DE VERIFICACIÓN USUARIO TIKTOK ===
#             if paso == "esperando_usuario_tiktok" and tipo == "text":
#                 usuario_tiktok = texto.strip()
#                 aspirante = buscar_aspirante_por_usuario_tiktok(usuario_tiktok)
#
#                 if aspirante:
#                     nombre = aspirante.get("nickname") or aspirante.get("nombre_real") or "(sin nombre)"
#                     enviar_mensaje(numero, mensaje_confirmar_nombre(nombre))
#                     actualizar_flujo(numero, "confirmando_nombre")
#                     usuarios_temp[numero] = aspirante
#                 else:
#                     enviar_mensaje(numero, "❌ No encontramos ese usuario de TikTok. ¿Podrías verificarlo?")
#                 return {"status": "ok"}
#
#             # === 4️⃣ CONFIRMAR NOMBRE ===
#             if paso == "confirmando_nombre" and tipo == "text":
#                 if texto_lower in ["si", "sí", "correcto", "yes", "ok", "sip", "acuerdo"]:
#                     aspirante = usuarios_temp.get(numero)
#                     if aspirante:
#                         actualizar_telefono_aspirante(aspirante["id"], numero)
#
#                     enviar_botones(
#                         numero,
#                         texto=mensaje_proteccion_datos(),
#                         botones=[{"id": "iniciar_encuesta", "title": "✅ Sí, quiero iniciar"}],
#                     )
#                     actualizar_flujo(numero, "esperando_inicio_encuesta")
#                 else:
#                     enviar_mensaje(numero, "Por favor escribe el nombre correcto o verifica tu usuario de TikTok.")
#                 return {"status": "ok"}
#
#             # === 5️⃣ ESPERANDO INICIO ENCUESTA ===
#             if paso == "esperando_inicio_encuesta":
#                 interactive = mensaje.get("interactive", {})
#                 if interactive.get("type") == "button_reply":
#                     button_id = interactive.get("button_reply", {}).get("id")
#                     if button_id == "iniciar_encuesta":
#                         actualizar_flujo(numero, 1)
#                         enviar_pregunta(numero, 1)
#                         print(f"🟢 [DEBUG] Encuesta iniciada -> paso=1 ({numero})")
#                         return {"status": "ok"}
#
#                 enviar_mensaje(numero, "Por favor usa el botón para iniciar la encuesta.")
#                 return {"status": "ok"}
#
#             # === 6️⃣ ASIGNAR ROL SI FALTA ===
#             if usuario_bd and numero not in usuarios_roles:
#                 usuarios_roles[numero] = (usuario_bd["rol"], time.time())
#
#             # === 7️⃣ CHAT LIBRE ===
#             if paso == "chat_libre":
#                 if tipo == "text":
#                     if texto_lower in ["menu", "menú", "brillar"]:
#                         usuarios_flujo.pop(numero, None)
#                         enviar_mensaje(numero, "🔙 Has vuelto al menú inicial.")
#                         enviar_menu_principal(numero, rol)
#                         return {"status": "ok"}
#
#                     guardar_mensaje(numero, texto, tipo="recibido", es_audio=False)
#                     print(f"💬 Chat libre de {numero}: {texto}")
#
#                 elif tipo == "audio":
#                     audio_id = mensaje.get("audio", {}).get("id")
#                     url_cloudinary = descargar_audio(audio_id, TOKEN)
#                     if url_cloudinary:
#                         guardar_mensaje(numero, url_cloudinary, tipo="recibido", es_audio=True)
#                         enviar_mensaje(numero, "🎧 Recibimos tu audio. Un asesor lo revisará pronto.")
#                     else:
#                         enviar_mensaje(numero, "⚠️ No se pudo procesar tu audio, inténtalo de nuevo.")
#                 return {"status": "ok"}
#
#             # === 8️⃣ REINICIO DESDE BOTÓN “Sí, continuar” ===
#             if paso is None and tipo == "interactive":
#                 interactive = mensaje.get("interactive", {})
#                 boton_texto = interactive.get("button_reply", {}).get("title", "").lower()
#                 if boton_texto == "sí, continuar":
#                     actualizar_flujo(numero, 1)
#                     enviar_pregunta(numero, 1)
#                     print(f"🟢 [DEBUG] Flujo reiniciado -> paso=1 ({numero})")
#                     return {"status": "ok"}
#
#             # === 9️⃣ ACTIVAR CHAT LIBRE SEGÚN ROL ===
#             if paso is None and tipo == "text":
#                 rol_usuario = usuarios_roles.get(numero, ("",))[0]
#                 if (texto_lower in ["4", "chat libre"] and rol_usuario == "aspirante") or \
#                    (texto_lower in ["7", "chat libre"] and rol_usuario == "creador") or \
#                    (texto_lower in ["5", "chat libre"] and rol_usuario == "admin"):
#                     actualizar_flujo(numero, "chat_libre")
#                     enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                     return {"status": "ok"}
#
#             # === 🔟 MANEJAR RESPUESTA NORMAL (ENCUESTA) ===
#             manejar_respuesta(numero, texto)
#
#     except Exception as e:
#         print("❌ Error procesando webhook:", e)
#         traceback.print_exc()
#
#     return {"status": "ok"}





# @router.post("/webhook")
# async def whatsapp_webhook(request: Request):
#     data = await request.json()
#     print("📩 Webhook recibido:", json.dumps(data, indent=2))
#
#     try:
#         cambios = data.get("entry", [])[0].get("changes", [])[0].get("value", {})
#         mensajes = cambios.get("messages", [])
#         if not mensajes:
#             return {"status": "ok"}
#
#         for mensaje in mensajes:
#             numero = mensaje.get("from")
#             tipo = mensaje.get("type")
#             texto = mensaje.get("text", {}).get("body", "").strip()
#             texto_lower = texto.lower()
#
#             # --- Variables auxiliares ---
#             paso = obtener_flujo(numero)
#             usuario_bd = buscar_usuario_por_telefono(numero)
#             rol = obtener_rol_usuario(numero)
#
#             print(f"📍 [DEBUG] número={numero}, paso={paso}, texto='{texto_lower}'")
#
#             # === 1️⃣ MENSAJES DE CONTROL UNIVERSALES ===
#             if tipo == "text":
#                 # --- 👋 SALUDOS INICIALES ---
#                 if texto_lower in ["hola", "buenas", "saludos","brillar"]:
#                     if usuario_bd:
#                         nombre = usuario_bd.get("nombre", "").split(" ")[0] or ""
#                         rol = usuario_bd.get("rol", "aspirante")
#                         # 🔹 Nueva versión del menú con saludo personalizado
#                         enviar_menu_principal(numero, rol=rol, nombre=nombre)
#                     else:
#                         enviar_mensaje(numero, Mensaje_bienvenida)
#                         actualizar_flujo(numero, "esperando_usuario_tiktok")
#                     return {"status": "ok"}
#
#                 # --- 🔄 Reinicio manual del flujo (menú principal)
#                 if texto_lower in ["menu", "menú", "brillar"]:
#                     usuarios_flujo.pop(numero, None)
#                     enviar_mensaje(numero, "✨ Has vuelto al menú principal.")
#                     enviar_menu_principal(numero, rol)
#                     return {"status": "ok"}
#
#             # === 2️⃣ NUEVO USUARIO ===
#             if not usuario_bd and paso is None:
#                 enviar_mensaje(numero, Mensaje_bienvenida)
#                 actualizar_flujo(numero, "esperando_usuario_tiktok")
#                 print(f"🟢 [DEBUG] Flujo inicial -> esperando_usuario_tiktok ({numero})")
#                 return {"status": "ok"}
#
#             # === 3️⃣ FLUJO DE VERIFICACIÓN USUARIO TIKTOK ===
#             if paso == "esperando_usuario_tiktok" and tipo == "text":
#                 usuario_tiktok = texto.strip()
#                 aspirante = buscar_aspirante_por_usuario_tiktok(usuario_tiktok)
#
#                 if aspirante:
#                     nombre = aspirante.get("nickname") or aspirante.get("nombre_real") or "(sin nombre)"
#                     enviar_mensaje(numero, mensaje_confirmar_nombre(nombre))
#                     actualizar_flujo(numero, "confirmando_nombre")
#                     usuarios_temp[numero] = aspirante
#                 else:
#                     enviar_mensaje(numero, "❌ No encontramos ese usuario de TikTok. ¿Podrías verificarlo?")
#                 return {"status": "ok"}
#
#             # === 4️⃣ CONFIRMAR NOMBRE ===
#             if paso == "confirmando_nombre" and tipo == "text":
#                 if texto_lower in ["si", "sí", "correcto", "yes", "ok", "sip", "acuerdo"]:
#                     aspirante = usuarios_temp.get(numero)
#                     if aspirante:
#                         actualizar_telefono_aspirante(aspirante["id"], numero)
#
#                     enviar_botones(
#                         numero,
#                         texto=mensaje_proteccion_datos(),
#                         botones=[{"id": "iniciar_encuesta", "title": "✅ Sí, quiero iniciar"}],
#                     )
#                     actualizar_flujo(numero, "esperando_inicio_encuesta")
#                 else:
#                     enviar_mensaje(numero, "Por favor escribe el nombre correcto o verifica tu usuario de TikTok.")
#                 return {"status": "ok"}
#
#             # === 5️⃣ ESPERANDO INICIO ENCUESTA ===
#             if paso == "esperando_inicio_encuesta":
#                 interactive = mensaje.get("interactive", {})
#                 if interactive.get("type") == "button_reply":
#                     button_id = interactive.get("button_reply", {}).get("id")
#                     if button_id == "iniciar_encuesta":
#                         actualizar_flujo(numero, 1)
#                         enviar_pregunta(numero, 1)
#                         print(f"🟢 [DEBUG] Encuesta iniciada -> paso=1 ({numero})")
#                         return {"status": "ok"}
#
#                 enviar_mensaje(numero, "Por favor usa el botón para iniciar la encuesta.")
#                 return {"status": "ok"}
#
#             # === 6️⃣ ASIGNAR ROL SI FALTA ===
#             if usuario_bd and numero not in usuarios_roles:
#                 usuarios_roles[numero] = (usuario_bd["rol"], time.time())
#
#             # === 7️⃣ CHAT LIBRE ===
#             if paso == "chat_libre":
#                 if tipo == "text":
#                     if texto_lower in ["menu", "menú", "brillar"]:
#                         usuarios_flujo.pop(numero, None)
#                         enviar_mensaje(numero, "🔙 Has vuelto al menú inicial.")
#                         enviar_menu_principal(numero, rol)
#                         return {"status": "ok"}
#
#                     guardar_mensaje(numero, texto, tipo="recibido", es_audio=False)
#                     print(f"💬 Chat libre de {numero}: {texto}")
#
#                 elif tipo == "audio":
#                     audio_id = mensaje.get("audio", {}).get("id")
#                     url_cloudinary = descargar_audio(audio_id, TOKEN)
#                     if url_cloudinary:
#                         guardar_mensaje(numero, url_cloudinary, tipo="recibido", es_audio=True)
#                         enviar_mensaje(numero, "🎧 Recibimos tu audio. Un asesor lo revisará pronto.")
#                     else:
#                         enviar_mensaje(numero, "⚠️ No se pudo procesar tu audio, inténtalo de nuevo.")
#                 return {"status": "ok"}
#
#             # === 8️⃣ REINICIO DESDE BOTÓN “Sí, continuar” ===
#             if paso is None and tipo == "interactive":
#                 interactive = mensaje.get("interactive", {})
#                 boton_texto = interactive.get("button_reply", {}).get("title", "").lower()
#                 if boton_texto == "sí, continuar":
#                     actualizar_flujo(numero, 1)
#                     enviar_pregunta(numero, 1)
#                     print(f"🟢 [DEBUG] Flujo reiniciado -> paso=1 ({numero})")
#                     return {"status": "ok"}
#
#             # === 9️⃣ ACTIVAR CHAT LIBRE SEGÚN ROL ===
#             if paso is None and tipo == "text":
#                 rol_usuario = usuarios_roles.get(numero, ("",))[0]
#                 if (texto_lower in ["4", "chat libre"] and rol_usuario == "aspirante") or \
#                    (texto_lower in ["7", "chat libre"] and rol_usuario == "creador") or \
#                    (texto_lower in ["5", "chat libre"] and rol_usuario == "admin"):
#                     actualizar_flujo(numero, "chat_libre")
#                     enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                     return {"status": "ok"}
#
#             # === 🔟 MANEJAR RESPUESTA NORMAL (ENCUESTA) ===
#             manejar_respuesta(numero, texto)
#
#     except Exception as e:
#         print("❌ Error procesando webhook:", e)
#         traceback.print_exc()
#
#     return {"status": "ok"}


# def manejar_respuesta(numero, texto):
#     texto_normalizado = texto.strip().lower()
#     paso = obtener_flujo(numero)
#     rol = obtener_rol_usuario(numero)
#     flujo = asegurar_flujo(numero)  # 🔒 inicialización segura
#     nombre = flujo.get("nombre") or obtener_nombre_usuario(numero)
#
#     # --- 1️⃣ SALUDOS INICIALES ---
#     if texto_normalizado in {"hola", "buenas", "saludos"}:
#         usuario_bd = buscar_usuario_por_telefono(numero)
#         if usuario_bd:
#             enviar_mensaje(numero, "👋 Hola, bienvenido a la Agencia.")
#             enviar_menu_principal(numero, rol)
#         else:
#             enviar_mensaje(numero, Mensaje_bienvenida)
#             actualizar_flujo(numero, "esperando_usuario_tiktok")
#         return
#
#     # --- 2️⃣ VOLVER AL MENÚ PRINCIPAL ---
#     if texto_normalizado in {"menu", "menú", "volver", "inicio", "brillar"}:
#         usuarios_flujo.pop(numero, None)
#         enviar_menu_principal(numero, rol)
#         return
#
#     # 🚫 CHAT LIBRE NO PROCESA FLUJOS
#     if paso == "chat_libre":
#         return
#
#     # --- 3️⃣ MENÚ PRINCIPAL POR ROL ---
#     if paso is None:
#         opciones = texto_normalizado
#         if rol == "aspirante":
#             match opciones:
#                 case "1" | "actualizar" | "perfil":
#                     actualizar_flujo(numero, 1)
#                     enviar_pregunta(numero, 1)
#                 case "2" | "diagnóstico" | "diagnostico":
#                     actualizar_flujo(numero, "diagnostico")
#                     enviar_diagnostico(numero)
#                     usuarios_flujo.pop(numero, None)
#                 case "3" | "requisitos":
#                     actualizar_flujo(numero, "requisitos")
#                     enviar_requisitos(numero)
#                     usuarios_flujo.pop(numero, None)
#                 case "4" | "chat libre":
#                     actualizar_flujo(numero, "chat_libre")
#                     enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                 case _:
#                     enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
#             return
#
#         elif rol == "creador":
#             match opciones:
#                 case "1":
#                     actualizar_flujo(numero, 1)
#                     enviar_pregunta(numero, 1)
#                 case "3":
#                     actualizar_flujo(numero, "asesoria")
#                     enviar_mensaje(numero, "📌 Un asesor se pondrá en contacto contigo pronto.")
#                     usuarios_flujo.pop(numero, None)
#                 case "4":
#                     actualizar_flujo(numero, "recursos")
#                     enviar_recursos_exclusivos(numero)
#                     usuarios_flujo.pop(numero, None)
#                 case "5":
#                     actualizar_flujo(numero, "eventos")
#                     enviar_eventos(numero)
#                     usuarios_flujo.pop(numero, None)
#                 case "6":
#                     actualizar_flujo(numero, "soporte")
#                     enviar_mensaje(numero, "📩 Describe tu problema y el equipo técnico te responderá.")
#                 case "7" | "chat libre":
#                     actualizar_flujo(numero, "chat_libre")
#                     enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                 case "8":
#                     actualizar_flujo(numero, "estadisticas")
#                     enviar_estadisticas(numero)
#                     usuarios_flujo.pop(numero, None)
#                 case "9":
#                     actualizar_flujo(numero, "baja")
#                     solicitar_baja(numero)
#                     usuarios_flujo.pop(numero, None)
#                 case _:
#                     enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
#             return
#
#         elif rol == "admin":
#             match opciones:
#                 case "1":
#                     actualizar_flujo(numero, "panel")
#                     enviar_panel_control(numero)
#                 case "2":
#                     actualizar_flujo(numero, "ver_perfiles")
#                     enviar_perfiles(numero)
#                     usuarios_flujo.pop(numero, None)
#                 case "3":
#                     actualizar_flujo(numero, "comunicado")
#                     enviar_mensaje(numero, "✉️ Escribe el comunicado a enviar a creadores/aspirantes:")
#                 case "4":
#                     actualizar_flujo(numero, "recursos_admin")
#                     gestionar_recursos(numero)
#                     usuarios_flujo.pop(numero, None)
#                 case "5" | "chat libre":
#                     actualizar_flujo(numero, "chat_libre")
#                     enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                 case _:
#                     enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
#             return
#
#         else:
#             if opciones == "1":
#                 actualizar_flujo(numero, "info")
#                 enviar_info_general(numero)
#             else:
#                 enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
#             return
#
#     # --- 4️⃣ FLUJO DE ENCUESTA (PASOS NUMÉRICOS) ---
#     if isinstance(paso, int):
#         if paso == 1 and len(texto.strip()) < 3:
#             enviar_mensaje(numero, "⚠️ Ingresa tu nombre completo (mínimo 3 caracteres).")
#             return
#
#         # Guardar nombre si es el paso 1
#         if paso == 1:
#             flujo.update({"nombre": texto.strip()})
#
#         validaciones = {
#             2: lambda t: t.isdigit() and 1 <= int(t) <= 5,
#             3: lambda t: t in {"1", "2", "3", "4"},
#             4: lambda t: t in list(mapa_paises.keys()) + ["20"] or t.lower() in [v.lower() for v in mapa_paises.values()],
#             6: lambda t: t in [str(i) for i in range(1, 10)],
#             7: lambda t: t in [str(i) for i in range(1, 6)],
#             9: lambda t: t in {"1", "2", "3"},
#             10: lambda t: t in {"1", "2", "3", "4"}
#         }
#
#         if paso in validaciones and not validaciones[paso](texto_normalizado):
#             enviar_mensaje(numero, f"⚠️ Ingresa una opción válida para la pregunta {paso}.")
#             return
#
#         if paso == 5:
#             resultado = validar_aceptar_ciudad(texto)
#             texto = resultado["ciudad"]
#             enviar_mensaje(numero, f"✅ Ciudad reconocida: {texto}")
#
#         if paso == 7:
#             enviar_mensaje(numero, "🎥 ¿Tienes experiencia transmitiendo lives en TikTok? Contesta *sí* o *no*.")
#             actualizar_flujo(numero, "7b")
#             return
#
#         if paso == 8:
#             try:
#                 meses = int(texto)
#                 if not (0 <= meses <= 999):
#                     raise ValueError
#             except:
#                 enviar_mensaje(numero, "⚠️ Ingresa un número válido de meses (0–999).")
#                 return
#             enviar_mensaje(numero, mensaje_encuesta_final_parte1(nombre))
#
#         guardar_respuesta(numero, paso, texto)
#         siguiente = paso + 1
#
#         if siguiente not in preguntas:
#             usuarios_flujo.pop(numero, None)
#             enviar_mensaje(numero, mensaje_encuesta_final(nombre))
#             consolidar_perfil(numero)
#
#             # En vez de mostrar el menú automáticamente:
#             enviar_mensaje(
#                 numero,
#                 '✨ Para ir al menú principal escribe **"brillar"**'
#             )
#             return
#
#         actualizar_flujo(numero, siguiente)
#         texto_pregunta = preguntas[siguiente]
#         if "{nombre}" in texto_pregunta:
#             texto_pregunta = texto_pregunta.format(nombre=nombre)
#         enviar_mensaje(numero, texto_pregunta)
#         return
#
#     # --- 5️⃣ PREGUNTA CONDICIONAL (7b) ---
#     if paso == "7b":
#         respuesta = texto_normalizado
#         if respuesta in {"si", "sí", "s"}:
#             enviar_mensaje(numero, preguntas[8])
#             actualizar_flujo(numero, 8)
#         elif respuesta in {"no", "n"}:
#             guardar_respuesta(numero, 8, "0")
#             enviar_mensaje(numero, preguntas[9])
#             actualizar_flujo(numero, 9)
#         else:
#             enviar_mensaje(numero, "Por favor responde solo *sí* o *no*.")

# def manejar_respuesta(numero, texto):
#     texto = texto.strip()
#     texto_normalizado = texto.lower()
#     paso = obtener_flujo(numero)
#     rol = obtener_rol_usuario(numero)
#     flujo = asegurar_flujo(numero)  # 🔒 Inicialización segura
#     nombre = flujo.get("nombre") or obtener_nombre_usuario(numero)
#
#     # --- 1️⃣ SALUDOS INICIALES ---
#     if texto_normalizado in {"hola", "buenas", "saludos"}:
#         usuario_bd = buscar_usuario_por_telefono(numero)
#         if usuario_bd:
#             rol = usuario_bd.get("rol", "aspirante")
#             enviar_mensaje(numero, "👋 Hola, bienvenido a la Agencia.")
#             enviar_menu_principal(numero, rol)
#         else:
#             enviar_mensaje(numero, Mensaje_bienvenida)
#             actualizar_flujo(numero, "esperando_usuario_tiktok")
#         return
#
#     # --- 2️⃣ VOLVER AL MENÚ PRINCIPAL ---
#     if texto_normalizado in {"menu", "menú", "volver", "inicio", "brillar"}:
#         usuarios_flujo.pop(numero, None)
#         enviar_menu_principal(numero, rol)
#         return
#
#     # 🚫 CHAT LIBRE NO PROCESA FLUJOS
#     if paso == "chat_libre":
#         return
#
#     # --- 3️⃣ MENÚ PRINCIPAL POR ROL ---
#     if paso is None:
#         opciones = texto_normalizado
#         match rol:
#             case "aspirante":
#                 match opciones:
#                     case "1" | "actualizar" | "perfil":
#                         actualizar_flujo(numero, 1)
#                         enviar_pregunta(numero, 1)
#                     case "2" | "diagnóstico" | "diagnostico":
#                         actualizar_flujo(numero, "diagnostico")
#                         enviar_diagnostico(numero)
#                         usuarios_flujo.pop(numero, None)
#                     case "3" | "requisitos":
#                         actualizar_flujo(numero, "requisitos")
#                         enviar_requisitos(numero)
#                         usuarios_flujo.pop(numero, None)
#                     case "4" | "chat libre":
#                         actualizar_flujo(numero, "chat_libre")
#                         enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                     case _:
#                         enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
#                 return
#
#             case "creador":
#                 match opciones:
#                     case "1":
#                         actualizar_flujo(numero, 1)
#                         enviar_pregunta(numero, 1)
#                     case "3":
#                         actualizar_flujo(numero, "asesoria")
#                         enviar_mensaje(numero, "📌 Un asesor se pondrá en contacto contigo pronto.")
#                         usuarios_flujo.pop(numero, None)
#                     case "4":
#                         actualizar_flujo(numero, "recursos")
#                         enviar_recursos_exclusivos(numero)
#                         usuarios_flujo.pop(numero, None)
#                     case "5":
#                         actualizar_flujo(numero, "eventos")
#                         enviar_eventos(numero)
#                         usuarios_flujo.pop(numero, None)
#                     case "6":
#                         actualizar_flujo(numero, "soporte")
#                         enviar_mensaje(numero, "📩 Describe tu problema y el equipo técnico te responderá.")
#                     case "7" | "chat libre":
#                         actualizar_flujo(numero, "chat_libre")
#                         enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                     case "8":
#                         actualizar_flujo(numero, "estadisticas")
#                         enviar_estadisticas(numero)
#                         usuarios_flujo.pop(numero, None)
#                     case "9":
#                         actualizar_flujo(numero, "baja")
#                         solicitar_baja(numero)
#                         usuarios_flujo.pop(numero, None)
#                     case _:
#                         enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
#                 return
#
#             case "admin":
#                 match opciones:
#                     case "1":
#                         actualizar_flujo(numero, "panel")
#                         enviar_panel_control(numero)
#                     case "2":
#                         actualizar_flujo(numero, "ver_perfiles")
#                         enviar_perfiles(numero)
#                         usuarios_flujo.pop(numero, None)
#                     case "3":
#                         actualizar_flujo(numero, "comunicado")
#                         enviar_mensaje(numero, "✉️ Escribe el comunicado a enviar a creadores/aspirantes:")
#                     case "4":
#                         actualizar_flujo(numero, "recursos_admin")
#                         gestionar_recursos(numero)
#                         usuarios_flujo.pop(numero, None)
#                     case "5" | "chat libre":
#                         actualizar_flujo(numero, "chat_libre")
#                         enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                     case _:
#                         enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
#                 return
#
#             case _:
#                 if opciones == "1":
#                     actualizar_flujo(numero, "info")
#                     enviar_info_general(numero)
#                 else:
#                     enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
#                 return
#
#     # --- 4️⃣ FLUJO DE ENCUESTA ---
#     if isinstance(paso, int):
#         if paso == 1:
#             if len(texto) < 3:
#                 enviar_mensaje(numero, "⚠️ Ingresa tu nombre completo (mínimo 3 caracteres).")
#                 return
#             flujo["nombre"] = texto.title().strip()
#             nombre = flujo["nombre"]
#
#         validaciones = {
#             2: lambda t: t.isdigit() and 1 <= int(t) <= 5,
#             3: lambda t: t in {"1", "2", "3", "4"},
#             4: lambda t: t in list(mapa_paises.keys()) + ["20"] or t.lower() in [v.lower() for v in mapa_paises.values()],
#             6: lambda t: t in [str(i) for i in range(1, 10)],
#             7: lambda t: t in [str(i) for i in range(1, 6)],
#             9: lambda t: t in {"1", "2", "3"},
#             10: lambda t: t in {"1", "2", "3", "4"}
#         }
#
#         if paso in validaciones and not validaciones[paso](texto_normalizado):
#             enviar_mensaje(numero, f"⚠️ Ingresa una opción válida para la pregunta {paso}.")
#             return
#
#         if paso == 5:
#             resultado = validar_aceptar_ciudad(texto)
#             texto = resultado["ciudad"]
#             enviar_mensaje(numero, f"✅ Ciudad reconocida: {texto}")
#
#         if paso == 7:
#             enviar_mensaje(numero, "🎥 ¿Tienes experiencia transmitiendo lives en TikTok? Contesta *sí* o *no*.")
#             actualizar_flujo(numero, "7b")
#             return
#
#         if paso == 8:
#             try:
#                 meses = int(texto)
#                 if not (0 <= meses <= 999):
#                     raise ValueError
#             except ValueError:
#                 enviar_mensaje(numero, "⚠️ Ingresa un número válido de meses (0–999).")
#                 return
#             enviar_mensaje(numero, mensaje_encuesta_final_parte1(nombre))
#
#         guardar_respuesta(numero, paso, texto)
#         siguiente = paso + 1
#
#         # ✅ Finalización del flujo
#         if siguiente not in preguntas:
#             usuarios_flujo.pop(numero, None)
#             enviar_mensaje(numero, mensaje_encuesta_final(nombre))
#             consolidar_perfil(numero)
#             enviar_mensaje(numero, '✨ Para ir al menú principal escribe **"brillar"**')
#             return
#
#         actualizar_flujo(numero, siguiente)
#         texto_pregunta = preguntas[siguiente]
#         if "{nombre}" in texto_pregunta:
#             texto_pregunta = texto_pregunta.format(nombre=nombre)
#         enviar_mensaje(numero, texto_pregunta)
#         return
#
#     # --- 5️⃣ PREGUNTA CONDICIONAL (7b) ---
#     if paso == "7b":
#         if texto_normalizado in {"si", "sí", "s"}:
#             enviar_mensaje(numero, preguntas[8])
#             actualizar_flujo(numero, 8)
#         elif texto_normalizado in {"no", "n"}:
#             guardar_respuesta(numero, 8, "0")
#             enviar_mensaje(numero, preguntas[9])
#             actualizar_flujo(numero, 9)
#         else:
#             enviar_mensaje(numero, "Por favor responde solo *sí* o *no*.")
#
# @router.post("/webhook")
# async def whatsapp_webhook(request: Request):
#     data = await request.json()
#     print("📩 Webhook recibido:", json.dumps(data, indent=2))
#
#     try:
#         cambios = data.get("entry", [])[0].get("changes", [])[0].get("value", {})
#         mensajes = cambios.get("messages", [])
#         if not mensajes:
#             return {"status": "ok"}
#
#         for mensaje in mensajes:
#             numero = mensaje.get("from")
#             tipo = mensaje.get("type")
#             texto = mensaje.get("text", {}).get("body", "").strip()
#             texto_lower = texto.lower()
#
#             # --- Variables auxiliares ---
#             paso = obtener_flujo(numero)
#             usuario_bd = buscar_usuario_por_telefono(numero)
#             rol = obtener_rol_usuario(numero)
#
#             print(f"📍 [DEBUG] número={numero}, paso={paso}, texto='{texto_lower}'")
#
#             # === 1️⃣ MENSAJES DE CONTROL UNIVERSALES ===
#             if tipo == "text":
#                 # --- 👋 SALUDOS INICIALES ---
#                 if texto_lower in ["hola", "buenas", "saludos","brillar"]:
#                     if usuario_bd:
#                         nombre = usuario_bd.get("nombre", "").split(" ")[0] or ""
#                         rol = usuario_bd.get("rol", "aspirante")
#                         # 🔹 Nueva versión del menú con saludo personalizado
#                         enviar_menu_principal(numero, rol=rol, nombre=nombre)
#                     else:
#                         enviar_mensaje(numero, Mensaje_bienvenida)
#                         actualizar_flujo(numero, "esperando_usuario_tiktok")
#                     return {"status": "ok"}
#
#                 # --- 🔄 Reinicio manual del flujo (menú principal)
#                 if texto_lower in ["menu", "menú", "brillar"]:
#                     usuarios_flujo.pop(numero, None)
#                     enviar_mensaje(numero, "✨ Has vuelto al menú principal.")
#                     enviar_menu_principal(numero, rol)
#                     return {"status": "ok"}
#
#             # === 2️⃣ NUEVO USUARIO ===
#             if not usuario_bd and paso is None:
#                 enviar_mensaje(numero, Mensaje_bienvenida)
#                 actualizar_flujo(numero, "esperando_usuario_tiktok")
#                 print(f"🟢 [DEBUG] Flujo inicial -> esperando_usuario_tiktok ({numero})")
#                 return {"status": "ok"}
#
#             # === 3️⃣ FLUJO DE VERIFICACIÓN USUARIO TIKTOK ===
#             if paso == "esperando_usuario_tiktok" and tipo == "text":
#                 usuario_tiktok = texto.strip()
#                 aspirante = buscar_aspirante_por_usuario_tiktok(usuario_tiktok)
#
#                 if aspirante:
#                     nombre = aspirante.get("nickname") or aspirante.get("nombre_real") or "(sin nombre)"
#                     enviar_mensaje(numero, mensaje_confirmar_nombre(nombre))
#                     actualizar_flujo(numero, "confirmando_nombre")
#                     usuarios_temp[numero] = aspirante
#                 else:
#                     enviar_mensaje(numero, "❌ No encontramos ese usuario de TikTok. ¿Podrías verificarlo?")
#                 return {"status": "ok"}
#
#             # === 4️⃣ CONFIRMAR NOMBRE ===
#             if paso == "confirmando_nombre" and tipo == "text":
#                 if texto_lower in ["si", "sí", "correcto", "yes", "ok", "sip", "acuerdo"]:
#                     aspirante = usuarios_temp.get(numero)
#                     if aspirante:
#                         actualizar_telefono_aspirante(aspirante["id"], numero)
#
#                     enviar_botones(
#                         numero,
#                         texto=mensaje_proteccion_datos(),
#                         botones=[{"id": "iniciar_encuesta", "title": "✅ Sí, quiero iniciar"}],
#                     )
#                     actualizar_flujo(numero, "esperando_inicio_encuesta")
#                 else:
#                     enviar_mensaje(numero, "Por favor escribe el nombre correcto o verifica tu usuario de TikTok.")
#                 return {"status": "ok"}
#
#             # === 5️⃣ ESPERANDO INICIO ENCUESTA ===
#             if paso == "esperando_inicio_encuesta":
#                 interactive = mensaje.get("interactive", {})
#                 if interactive.get("type") == "button_reply":
#                     button_id = interactive.get("button_reply", {}).get("id")
#                     if button_id == "iniciar_encuesta":
#                         actualizar_flujo(numero, 1)
#                         enviar_pregunta(numero, 1)
#                         print(f"🟢 [DEBUG] Encuesta iniciada -> paso=1 ({numero})")
#                         return {"status": "ok"}
#
#                 enviar_mensaje(numero, "Por favor usa el botón para iniciar la encuesta.")
#                 return {"status": "ok"}
#
#             # === 6️⃣ ASIGNAR ROL SI FALTA ===
#             if usuario_bd and numero not in usuarios_roles:
#                 usuarios_roles[numero] = (usuario_bd["rol"], time.time())
#
#             # === 7️⃣ CHAT LIBRE ===
#             if paso == "chat_libre":
#                 if tipo == "text":
#                     if texto_lower in ["menu", "menú", "brillar"]:
#                         usuarios_flujo.pop(numero, None)
#                         enviar_mensaje(numero, "🔙 Has vuelto al menú inicial.")
#                         enviar_menu_principal(numero, rol)
#                         return {"status": "ok"}
#
#                     guardar_mensaje(numero, texto, tipo="recibido", es_audio=False)
#                     print(f"💬 Chat libre de {numero}: {texto}")
#
#                 elif tipo == "audio":
#                     audio_id = mensaje.get("audio", {}).get("id")
#                     url_cloudinary = descargar_audio(audio_id, TOKEN)
#                     if url_cloudinary:
#                         guardar_mensaje(numero, url_cloudinary, tipo="recibido", es_audio=True)
#                         enviar_mensaje(numero, "🎧 Recibimos tu audio. Un asesor lo revisará pronto.")
#                     else:
#                         enviar_mensaje(numero, "⚠️ No se pudo procesar tu audio, inténtalo de nuevo.")
#                 return {"status": "ok"}
#
#             # === 8️⃣ REINICIO DESDE BOTÓN “Sí, continuar” ===
#             if paso is None and tipo == "interactive":
#                 interactive = mensaje.get("interactive", {})
#                 boton_texto = interactive.get("button_reply", {}).get("title", "").lower()
#                 if boton_texto == "sí, continuar":
#                     actualizar_flujo(numero, 1)
#                     enviar_pregunta(numero, 1)
#                     print(f"🟢 [DEBUG] Flujo reiniciado -> paso=1 ({numero})")
#                     return {"status": "ok"}
#
#             # === 9️⃣ ACTIVAR CHAT LIBRE SEGÚN ROL ===
#             if paso is None and tipo == "text":
#                 rol_usuario = usuarios_roles.get(numero, ("",))[0]
#                 if (texto_lower in ["4", "chat libre"] and rol_usuario == "aspirante") or \
#                    (texto_lower in ["7", "chat libre"] and rol_usuario == "creador") or \
#                    (texto_lower in ["5", "chat libre"] and rol_usuario == "admin"):
#                     actualizar_flujo(numero, "chat_libre")
#                     enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                     return {"status": "ok"}
#
#             # === 🔟 MANEJAR RESPUESTA NORMAL (ENCUESTA) ===
#             manejar_respuesta(numero, texto)
#
#     except Exception as e:
#         print("❌ Error procesando webhook:", e)
#         traceback.print_exc()
#
#     return {"status": "ok"}

# @router.post("/webhook")
# async def whatsapp_webhook(request: Request):
#     data = await request.json()
#     print("📩 Webhook recibido:", json.dumps(data, indent=2))
#
#     try:
#         cambios = data.get("entry", [])[0].get("changes", [])[0].get("value", {})
#         mensajes = cambios.get("messages", [])
#         if not mensajes:
#             return {"status": "ok"}
#
#         for mensaje in mensajes:
#             numero = mensaje.get("from")
#             tipo = mensaje.get("type")
#             texto = mensaje.get("text", {}).get("body", "").strip()
#             texto_lower = texto.lower()
#
#             # --- Variables auxiliares ---
#             paso = obtener_flujo(numero)
#             usuario_bd = buscar_usuario_por_telefono(numero)
#             rol = obtener_rol_usuario(numero)
#
#             print(f"📍 [DEBUG] número={numero}, paso={paso}, texto='{texto_lower}'")
#
#             # === 1️⃣ MENSAJES DE CONTROL UNIVERSALES ===
#             if tipo == "text":
#                 if texto_lower in ["hola", "buenas", "saludos"]:
#                     if usuario_bd:
#                         nombre = usuario_bd.get("nombre", "").split(" ")[0] or ""
#                         rol = usuario_bd.get("rol", "aspirante")
#
#                         if nombre:
#                             mensaje_bienvenida = f"👋 ¡Hola {nombre}! 📋 Te damos este menú de opciones:"
#                         else:
#                             mensaje_bienvenida = "👋 ¡Hola! 📋 Te damos este menú de opciones:"
#
#                         enviar_mensaje(numero, mensaje_bienvenida)
#                         enviar_menu_principal(numero, rol)
#                     else:
#                         enviar_mensaje(numero, Mensaje_bienvenida)
#                         actualizar_flujo(numero, "esperando_usuario_tiktok")
#                     return {"status": "ok"}
#
#                 # Reinicio manual del flujo (menú principal)
#                 if texto_lower in ["menu", "menú", "brillar"]:
#                     usuarios_flujo.pop(numero, None)
#                     enviar_mensaje(numero, "✨ Has vuelto al menú principal.")
#                     enviar_menu_principal(numero, rol)
#                     return {"status": "ok"}
#
#             # === 2️⃣ NUEVO USUARIO ===
#             if not usuario_bd and paso is None:
#                 enviar_mensaje(numero, Mensaje_bienvenida)
#                 actualizar_flujo(numero, "esperando_usuario_tiktok")
#                 print(f"🟢 [DEBUG] Flujo inicial -> esperando_usuario_tiktok ({numero})")
#                 return {"status": "ok"}
#
#             # === 3️⃣ FLUJO DE VERIFICACIÓN USUARIO TIKTOK ===
#             if paso == "esperando_usuario_tiktok" and tipo == "text":
#                 usuario_tiktok = texto.strip()
#                 aspirante = buscar_aspirante_por_usuario_tiktok(usuario_tiktok)
#
#                 if aspirante:
#                     nombre = aspirante.get("nickname") or aspirante.get("nombre_real") or "(sin nombre)"
#                     enviar_mensaje(numero, mensaje_confirmar_nombre(nombre))
#                     actualizar_flujo(numero, "confirmando_nombre")
#                     usuarios_temp[numero] = aspirante
#                 else:
#                     enviar_mensaje(numero, "❌ No encontramos ese usuario de TikTok. ¿Podrías verificarlo?")
#                 return {"status": "ok"}
#
#             # === 4️⃣ CONFIRMAR NOMBRE ===
#             if paso == "confirmando_nombre" and tipo == "text":
#                 if texto_lower in ["si", "sí", "correcto", "yes", "ok", "sip", "acuerdo"]:
#                     aspirante = usuarios_temp.get(numero)
#                     if aspirante:
#                         actualizar_telefono_aspirante(aspirante["id"], numero)
#
#                     enviar_botones(
#                         numero,
#                         texto=mensaje_proteccion_datos(),
#                         botones=[{"id": "iniciar_encuesta", "title": "✅ Sí, quiero iniciar"}],
#                     )
#                     actualizar_flujo(numero, "esperando_inicio_encuesta")
#                 else:
#                     enviar_mensaje(numero, "Por favor escribe el nombre correcto o verifica tu usuario de TikTok.")
#                 return {"status": "ok"}
#
#             # === 5️⃣ ESPERANDO INICIO ENCUESTA ===
#             if paso == "esperando_inicio_encuesta":
#                 interactive = mensaje.get("interactive", {})
#                 if interactive.get("type") == "button_reply":
#                     button_id = interactive.get("button_reply", {}).get("id")
#                     if button_id == "iniciar_encuesta":
#                         actualizar_flujo(numero, 1)
#                         enviar_pregunta(numero, 1)
#                         print(f"🟢 [DEBUG] Encuesta iniciada -> paso=1 ({numero})")
#                         return {"status": "ok"}
#
#                 enviar_mensaje(numero, "Por favor usa el botón para iniciar la encuesta.")
#                 return {"status": "ok"}
#
#             # === 6️⃣ ASIGNAR ROL SI FALTA ===
#             if usuario_bd and numero not in usuarios_roles:
#                 usuarios_roles[numero] = (usuario_bd["rol"], time.time())
#
#             # === 7️⃣ CHAT LIBRE ===
#             if paso == "chat_libre":
#                 if tipo == "text":
#                     if texto_lower in ["menu", "menú", "brillar"]:
#                         usuarios_flujo.pop(numero, None)
#                         enviar_mensaje(numero, "🔙 Has vuelto al menú inicial.")
#                         enviar_menu_principal(numero, rol)
#                         return {"status": "ok"}
#
#                     guardar_mensaje(numero, texto, tipo="recibido", es_audio=False)
#                     print(f"💬 Chat libre de {numero}: {texto}")
#
#                 elif tipo == "audio":
#                     audio_id = mensaje.get("audio", {}).get("id")
#                     url_cloudinary = descargar_audio(audio_id, TOKEN)
#                     if url_cloudinary:
#                         guardar_mensaje(numero, url_cloudinary, tipo="recibido", es_audio=True)
#                         enviar_mensaje(numero, "🎧 Recibimos tu audio. Un asesor lo revisará pronto.")
#                     else:
#                         enviar_mensaje(numero, "⚠️ No se pudo procesar tu audio, inténtalo de nuevo.")
#                 return {"status": "ok"}
#
#             # === 8️⃣ REINICIO DESDE BOTÓN “Sí, continuar” ===
#             if paso is None and tipo == "interactive":
#                 interactive = mensaje.get("interactive", {})
#                 boton_texto = interactive.get("button_reply", {}).get("title", "").lower()
#                 if boton_texto == "sí, continuar":
#                     actualizar_flujo(numero, 1)
#                     enviar_pregunta(numero, 1)
#                     print(f"🟢 [DEBUG] Flujo reiniciado -> paso=1 ({numero})")
#                     return {"status": "ok"}
#
#             # === 9️⃣ ACTIVAR CHAT LIBRE SEGÚN ROL ===
#             if paso is None and tipo == "text":
#                 rol_usuario = usuarios_roles.get(numero, ("",))[0]
#                 if (texto_lower in ["4", "chat libre"] and rol_usuario == "aspirante") or \
#                    (texto_lower in ["7", "chat libre"] and rol_usuario == "creador") or \
#                    (texto_lower in ["5", "chat libre"] and rol_usuario == "admin"):
#                     actualizar_flujo(numero, "chat_libre")
#                     enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                     return {"status": "ok"}
#
#             # === 🔟 MANEJAR RESPUESTA NORMAL (ENCUESTA) ===
#             manejar_respuesta(numero, texto)
#
#     except Exception as e:
#         print("❌ Error procesando webhook:", e)
#         traceback.print_exc()
#
#     return {"status": "ok"}


# def manejar_respuesta(numero, texto):
#     texto_normalizado = texto.strip().lower()
#     paso = obtener_flujo(numero)
#     rol = obtener_rol_usuario(numero)
#
#     asegurar_flujo(numero)  # 🔒 Inicialización segura
#
#     # --- Detectar saludos ---
#     if texto_normalizado in ["hola", "buenas", "saludos"]:
#         usuario_bd = buscar_usuario_por_telefono(numero)
#         if usuario_bd:
#             enviar_mensaje(numero, f"👋 Hola, bienvenido a la Agencia.")
#             enviar_menu_principal(numero, rol)
#             return
#
#         enviar_mensaje(numero, Mensaje_bienvenida)
#
#         actualizar_flujo(numero, "esperando_usuario_tiktok")
#         return
#
#     # --- Volver al menú principal ---
#     if texto_normalizado in ["menu", "menú", "volver", "inicio", "brillar"]:
#         usuarios_flujo.pop(numero, None)
#         enviar_menu_principal(numero, rol)
#         return
#
#     # 🚫 Chat libre no procesa aquí
#     if paso == "chat_libre":
#         return
#
#     # --- MENÚ PRINCIPAL SEGÚN ROL ---
#     if paso is None:
#         if rol == "aspirante":
#             if texto_normalizado in ["1", "actualizar", "perfil"]:
#                 actualizar_flujo(numero, 1)
#                 enviar_pregunta(numero, 1)
#                 return
#             elif texto_normalizado in ["2", "diagnóstico", "diagnostico"]:
#                 actualizar_flujo(numero, "diagnostico")
#                 enviar_diagnostico(numero)
#                 usuarios_flujo.pop(numero, None)
#                 return
#             elif texto_normalizado in ["3", "requisitos"]:
#                 actualizar_flujo(numero, "requisitos")
#                 enviar_requisitos(numero)
#                 usuarios_flujo.pop(numero, None)
#                 return
#             elif texto_normalizado in ["4", "chat libre"]:
#                 actualizar_flujo(numero, "chat_libre")
#                 enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                 return
#             else:
#                 enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
#                 return
#
#         elif rol == "creador":
#             if texto_normalizado == "1":
#                 actualizar_flujo(numero, 1)
#                 enviar_pregunta(numero, 1)
#                 return
#             elif texto_normalizado == "3":
#                 actualizar_flujo(numero, "asesoria")
#                 enviar_mensaje(numero, "📌 Un asesor se pondrá en contacto contigo pronto.")
#                 usuarios_flujo.pop(numero, None)
#                 return
#             elif texto_normalizado == "4":
#                 actualizar_flujo(numero, "recursos")
#                 enviar_recursos_exclusivos(numero)
#                 usuarios_flujo.pop(numero, None)
#                 return
#             elif texto_normalizado == "5":
#                 actualizar_flujo(numero, "eventos")
#                 enviar_eventos(numero)
#                 usuarios_flujo.pop(numero, None)
#                 return
#             elif texto_normalizado == "6":
#                 actualizar_flujo(numero, "soporte")
#                 enviar_mensaje(numero, "📩 Describe tu problema y el equipo técnico te responderá.")
#                 return
#             elif texto_normalizado == "8":
#                 actualizar_flujo(numero, "estadisticas")
#                 enviar_estadisticas(numero)
#                 usuarios_flujo.pop(numero, None)
#                 return
#             elif texto_normalizado == "9":
#                 actualizar_flujo(numero, "baja")
#                 solicitar_baja(numero)
#                 usuarios_flujo.pop(numero, None)
#                 return
#             elif texto_normalizado in ["7", "chat libre"]:
#                 actualizar_flujo(numero, "chat_libre")
#                 enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                 return
#             else:
#                 enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
#                 return
#
#         elif rol == "admin":
#             if texto_normalizado == "1":
#                 actualizar_flujo(numero, "panel")
#                 enviar_panel_control(numero)
#                 return
#             elif texto_normalizado == "2":
#                 actualizar_flujo(numero, "ver_perfiles")
#                 enviar_perfiles(numero)
#                 usuarios_flujo.pop(numero, None)
#                 return
#             elif texto_normalizado == "3":
#                 actualizar_flujo(numero, "comunicado")
#                 enviar_mensaje(numero, "✉️ Escribe el comunicado a enviar a creadores/aspirantes:")
#                 return
#             elif texto_normalizado == "4":
#                 actualizar_flujo(numero, "recursos_admin")
#                 gestionar_recursos(numero)
#                 usuarios_flujo.pop(numero, None)
#                 return
#             elif texto_normalizado in ["5", "chat libre"]:
#                 actualizar_flujo(numero, "chat_libre")
#                 enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                 return
#             else:
#                 enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
#                 return
#
#         else:  # Rol desconocido -> menú básico
#             if texto_normalizado == "1":
#                 actualizar_flujo(numero, "info")
#                 enviar_info_general(numero)
#                 return
#             else:
#                 enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
#                 return
#
#     # --- FLUJO DE PREGUNTAS ---
#     if isinstance(paso, int):
#         # 🧩 Validaciones por paso
#         if paso == 1:  # Nombre
#             if len(texto.strip()) < 3:
#                 enviar_mensaje(numero, "⚠️ Ingresa tu nombre completo sin apellidos (mínimo 3 caracteres).")
#                 return
#
#             # Guardamos el nombre para reutilizar
#             if numero not in usuarios_flujo or not isinstance(usuarios_flujo[numero], dict):
#                 usuarios_flujo[numero] = {}
#             usuarios_flujo[numero].update({"paso": paso, "nombre": texto.strip()})
#
#         elif paso == 2:  # Edad
#             try:
#                 opcion = int(texto)
#                 if opcion not in [1, 2, 3, 4, 5]:
#                     raise ValueError
#             except:
#                 enviar_mensaje(numero, "⚠️ Ingresa una opción válida para tu rango de edad (1-5).")
#                 return
#
#         elif paso == 3:  # Género
#             if texto not in ["1", "2", "3", "4"]:
#                 enviar_mensaje(numero, "⚠️ Ingresa solo el número (1–4).")
#                 return
#
#         elif paso == 4:  # País
#             opciones_paises = list(mapa_paises.keys()) + ["20"]
#             if texto not in opciones_paises and texto.lower() not in [p.lower() for p in mapa_paises.values()]:
#                 enviar_mensaje(numero, "⚠️ Ingresa el número de tu país o escríbelo si no está en la lista.")
#                 return
#
#         elif paso == 5:  # Ciudad principal
#             resultado = validar_aceptar_ciudad(texto)
#             if resultado["corregida"]:
#                 texto = resultado["ciudad"]
#                 enviar_mensaje(numero, f"✅ Ciudad reconocida y corregida: {texto}")
#             else:
#                 enviar_mensaje(numero, f"✅ Ciudad aceptada como la escribiste: {texto}")
#
#         elif paso == 6:  # Actividad actual
#             if texto not in [str(i) for i in range(1, 10)]:
#                 enviar_mensaje(numero, "⚠️ Ingresa solo el número (1–9).")
#                 return
#
#         elif paso == 7:  # Intención principal
#             if texto not in [str(i) for i in range(1, 6)]:
#                 enviar_mensaje(numero, "⚠️ Ingresa solo el número (1–5).")
#                 return
#
#             # ✅ Pregunta condicional: experiencia en lives
#             enviar_mensaje(numero, "🎥 ¿Tienes experiencia transmitiendo lives en TikTok? Contesta *sí* o *no*.")
#             actualizar_flujo(numero, "7b")
#             return
#
#         elif paso == 8:  # Meses de experiencia
#             try:
#                 meses = int(texto)
#                 if not (0 <= meses <= 999):
#                     raise ValueError
#             except:
#                 enviar_mensaje(numero, "⚠️ Ingresa un número válido de meses (0–999).")
#                 return
#
#         elif paso == 9:  # Horas por día
#             if texto not in ["1", "2", "3"]:
#                 enviar_mensaje(numero, "⚠️ Ingresa solo el número (1–3).")
#                 return
#
#         elif paso == 10:  # Días por semana
#             if texto not in ["1", "2", "3", "4"]:
#                 enviar_mensaje(numero, "⚠️ Ingresa solo el número (1–4).")
#                 return
#
#         # ✅ Guardar respuesta válida en BD
#         guardar_respuesta(numero, paso, texto)
#
#         # --- Lógica de avance ---
#         siguiente = paso + 1
#
#         # 🚫 Si ya no hay más preguntas, finaliza el flujo
#         if siguiente not in preguntas:
#             usuarios_flujo.pop(numero, None)
#             nombre = obtener_nombre_usuario(numero)
#             enviar_mensaje(numero, mensaje_encuesta_final(nombre))
#             consolidar_perfil(numero)
#             enviar_menu_principal(numero, rol)
#             return
#
#         # ✅ Avanzar al siguiente paso
#         actualizar_flujo(numero, siguiente)
#
#         # 🟢 Personalizar pregunta con nombre
#         nombre = obtener_nombre_usuario(numero)
#         texto_pregunta = preguntas[siguiente]
#         if "{nombre}" in texto_pregunta:
#             texto_pregunta = texto_pregunta.format(nombre=nombre)
#
#         # 💬 Mensaje especial después de la 8
#         if paso == 8:
#             mensaje = mensaje_encuesta_final_parte1(nombre)
#             enviar_mensaje(numero, mensaje)
#
#         enviar_mensaje(numero, texto_pregunta)
#         return
#
#     # --- BLOQUE NUEVO: pregunta condicional “7b” ---
#     if paso == "7b":
#         respuesta = texto.strip().lower()
#
#         if respuesta in ["si", "sí", "s"]:
#             # Tiene experiencia → preguntar meses
#             enviar_mensaje(numero, preguntas[8])
#             actualizar_flujo(numero, 8)
#             return
#
#         elif respuesta in ["no", "n"]:
#             # No tiene experiencia → registrar 0 y pasar a 9
#             guardar_respuesta(numero, 8, "0")
#             enviar_mensaje(numero, preguntas[9])
#             actualizar_flujo(numero, 9)
#             return
#
#         else:
#             enviar_mensaje(numero, "Por favor responde solo *sí* o *no*.")
#             return
#
#
# # --- FLUJO DE PREGUNTAS ---
#     if isinstance(paso, int):
#         # Validaciones según paso
#         if paso == 1:  # Nombre
#             if len(texto.strip()) < 3:
#                 enviar_mensaje(numero, "⚠️ Ingresa tu nombre completo sin apellidos (mínimo 3 caracteres).")
#                 return
#
#             # Guardamos el nombre para reutilizar
#             if numero not in usuarios_flujo or not isinstance(usuarios_flujo[numero], dict):
#                 usuarios_flujo[numero] = {}
#             usuarios_flujo[numero].update({"paso": paso, "nombre": texto.strip()})
#
#
#         elif paso == 2:  # Edad
#             try:
#                 opcion = int(texto)
#                 if opcion not in [1, 2, 3, 4, 5]:
#                     raise ValueError
#             except:
#                 enviar_mensaje(numero, "⚠️ Ingresa una opción válida para tu rango de edad (1-5).")
#                 return
#
#         elif paso == 3:  # Género
#             if texto not in ["1", "2", "3", "4"]:
#                 enviar_mensaje(numero, "⚠️ Ingresa solo el número (1–4).")
#                 return
#
#         if paso == 4:  # País
#             opciones_paises = list(mapa_paises.keys()) + ["20"]
#             if texto not in opciones_paises and texto.lower() not in [p.lower() for p in mapa_paises.values()]:
#                 enviar_mensaje(numero, "⚠️ Ingresa el número de tu país o escríbelo si no está en la lista.")
#                 return
#
#         if paso == 5:  # Ciudad principal
#             resultado = validar_aceptar_ciudad(texto)
#             if resultado["corregida"]:
#                 texto = resultado["ciudad"]
#                 enviar_mensaje(numero, f"✅ Ciudad reconocida y corregida: {texto}")
#             else:
#                 enviar_mensaje(numero, f"✅ Ciudad aceptada como la escribiste: {texto}")
#
#         elif paso == 6:  # Actividad actual
#             if texto not in [str(i) for i in range(1, 10)]:
#                 enviar_mensaje(numero, "⚠️ Ingresa solo el número (1–9).")
#                 return
#
#         elif paso == 7:  # Intención principal
#             if texto not in [str(i) for i in range(1, 6)]:
#                 enviar_mensaje(numero, "⚠️ Ingresa solo el número (1–5).")
#                 return
#
#             # ✅ Después de la 7, se pregunta si tiene experiencia en lives
#             enviar_mensaje(numero, "🎥 ¿Tienes experiencia transmitiendo lives en TikTok?. Contesta *sí* o *no*.")
#             actualizar_flujo(numero, "7b")
#             return
#
#         elif paso == 8:  # Meses de experiencia
#             try:
#                 meses = int(texto)
#                 if not (0 <= meses <= 999):
#                     raise ValueError
#             except:
#                 enviar_mensaje(numero, "⚠️ Ingresa un número válido de meses (0–999).")
#                 return
#
#         elif paso == 9:  # Horas por día
#             if texto not in ["1", "2", "3"]:
#                 enviar_mensaje(numero, "⚠️ Ingresa solo el número (1–3).")
#                 return
#
#         elif paso == 10:  # Días por semana
#             if texto not in ["1", "2", "3", "4"]:
#                 enviar_mensaje(numero, "⚠️ Ingresa solo el número (1–4).")
#                 return
#
#         # Guardar respuesta válida
#         guardar_respuesta(numero, paso, texto)
#
#         # --- Lógica de avance ---
#         if paso < len(preguntas):
#             siguiente = paso + 1
#             actualizar_flujo(numero, siguiente)
#
#             # 🟢 Insertar el nombre en preguntas personalizadas
#             nombre = obtener_nombre_usuario(numero)
#             texto_pregunta = preguntas[siguiente]
#
#             if "{nombre}" in texto_pregunta:
#                 texto_pregunta = texto_pregunta.format(nombre=nombre)
#
#             # 💬 Mensaje especial después de la 8
#             if paso == 8:
#                 mensaje = mensaje_encuesta_final_parte1(nombre)
#                 enviar_mensaje(numero, mensaje)
#
#             enviar_mensaje(numero, texto_pregunta)
#
#         else:
#             # 🏁 Fin del flujo
#             usuarios_flujo.pop(numero, None)
#             nombre = obtener_nombre_usuario(numero)
#             enviar_mensaje(numero, mensaje_encuesta_final(nombre))
#             consolidar_perfil(numero)
#             enviar_menu_principal(numero, rol)
#         return
#
#     # --- BLOQUE NUEVO: validación para la pregunta condicional “7b” ---
#     if paso == "7b":
#         respuesta = texto.strip().lower()
#
#         if respuesta in ["si", "sí", "s"]:
#             # Tiene experiencia → preguntar meses
#             enviar_mensaje(numero, preguntas[8])
#             actualizar_flujo(numero, 8)
#             return
#
#         elif respuesta in ["no", "n"]:
#             # No tiene experiencia → registrar 0 y saltar a 9
#             guardar_respuesta(numero, 8, "0")
#             # enviar_mensaje(numero, "✅ Perfecto, registramos que no tienes experiencia previa en TikTok Live.")
#             enviar_mensaje(numero, preguntas[9])
#             actualizar_flujo(numero, 9)
#             return
#
#         else:
#             enviar_mensaje(numero, "Por favor responde solo *sí* o *no*.")
#             return



# @router.post("/webhook")
# async def whatsapp_webhook(request: Request):
#     data = await request.json()
#     print("📩 Webhook recibido:", json.dumps(data, indent=2))
#
#     try:
#         mensajes = data["entry"][0]["changes"][0]["value"].get("messages", [])
#         if not mensajes:
#             return {"status": "ok"}
#
#         for mensaje in mensajes:
#             numero = mensaje["from"]
#             tipo = mensaje.get("type")
#             texto = mensaje.get("text", {}).get("body", "").strip().lower()
#             paso = obtener_flujo(numero)  # <-- usa caché robusta!
#             usuario_bd = buscar_usuario_por_telefono(numero)
#             rol = obtener_rol_usuario(numero)
#
#             # 1. FLUJO DE NUEVO USUARIO (Onboarding)
#             if not usuario_bd and paso is None:
#                 enviar_mensaje(numero,Mensaje_bienvenida)
#                 actualizar_flujo(numero, "esperando_usuario_tiktok")
#                 return {"status": "ok"}
#
#             # 2. Saludos en cualquier momento
#             if tipo == "text" and texto in ["hola", "buenas", "saludos"]:
#                 if usuario_bd:
#                     enviar_mensaje(numero, f"👋 Hola, bienvenido a la Agencia Prestige.")
#                     enviar_menu_principal(numero, rol)
#                 else:
#                     enviar_mensaje(numero,Mensaje_bienvenida)
#                     actualizar_flujo(numero, "esperando_usuario_tiktok")
#                 return {"status": "ok"}
#
#             # 3. Volver al menú principal
#             if tipo == "text" and texto in ["menu","brillar"]:
#                 usuarios_flujo.pop(numero, None)
#                 enviar_menu_principal(numero, rol)
#                 return {"status": "ok"}
#
#             # 4. Esperando usuario TikTok
#             if paso == "esperando_usuario_tiktok" and tipo == "text":
#                 usuario_tiktok = mensaje["text"]["body"].strip()
#                 aspirante = buscar_aspirante_por_usuario_tiktok(usuario_tiktok)
#                 if aspirante:
#                     nombre = aspirante.get('nickname') or aspirante.get('nombre_real') or '(sin nombre)'
#                     enviar_mensaje(numero, mensaje_confirmar_nombre(nombre))
#                     actualizar_flujo(numero, "confirmando_nombre")
#                     usuarios_temp[numero] = aspirante
#                 else:
#                     enviar_mensaje(numero, "No encontramos ese usuario de TikTok en nuestra plataforma. ¿Puedes verificarlo?")
#                 return {"status": "ok"}
#
#             # 5. Confirmando nombre
#             if paso == "confirmando_nombre" and tipo == "text":
#                 if texto.strip().lower() in ["si", "correct", "yes", "yeah", "yep", "sip", "sipis","acuerdo"]:
#                     aspirante = usuarios_temp.get(numero)
#                     if aspirante:
#                         actualizar_telefono_aspirante(aspirante["id"], numero)
#
#                     # 🔒 Mensaje legal + inicio en un solo botón
#                     enviar_botones(
#                         numero,
#                         texto=mensaje_proteccion_datos(),
#                         botones=[
#                             {"id": "iniciar_encuesta", "title": "✅ Sí, quiero iniciar"}])
#                     actualizar_flujo(numero, "esperando_inicio_encuesta")
#                 else:
#                     enviar_mensaje(numero, "Por favor escribe el nombre correcto o verifica tu usuario de TikTok.")
#                 return {"status": "ok"}
#
#             # 6. Esperando inicio encuesta (botón único)
#             if paso == "esperando_inicio_encuesta":
#                 if tipo == "interactive":
#                     interactive = mensaje.get("interactive", {})
#                     if interactive.get("type") == "button_reply":
#                         button_id = interactive.get("button_reply", {}).get("id")
#                         if button_id == "iniciar_encuesta":
#                             actualizar_flujo(numero, 1)
#                             enviar_pregunta(numero, 1)
#                             return {"status": "ok"}
#                 # fallback si no usa botones
#                 enviar_mensaje(numero, "Por favor usa el botón para iniciar la encuesta.")
#                 return {"status": "ok"}
#
#             # 7. Asignar rol si usuario existe
#             if usuario_bd and numero not in usuarios_roles:
#                 usuarios_roles[numero] = (usuario_bd["rol"], time.time())
#
#             # 8. Chat libre
#             if paso == "chat_libre":
#                 if tipo == "text":
#                     if texto in ["menu", "brillar"]:
#                         usuarios_flujo.pop(numero, None)
#                         enviar_mensaje(numero, "🔙 Volviste al menú inicial.")
#                         enviar_menu_principal(numero, rol)
#                         return {"status": "ok"}
#                     print(f"💬 Chat libre de {numero}: {texto}")
#                     guardar_mensaje(numero, texto, tipo="recibido", es_audio=False)
#
#                 elif tipo == "audio":
#                     audio_id = mensaje.get("audio", {}).get("id")
#                     print(f"🎤 Audio recibido de {numero}: {audio_id}")
#                     url_cloudinary = descargar_audio(audio_id, TOKEN)
#                     if url_cloudinary:
#                         guardar_mensaje(numero, url_cloudinary, tipo="recibido", es_audio=True)
#                         enviar_mensaje(numero, "🎧 Recibimos tu audio. Un asesor lo revisará pronto.")
#                     else:
#                         enviar_mensaje(numero, "⚠️ No se pudo procesar tu audio, inténtalo de nuevo.")
#
#                 elif tipo == "interactive":
#                     interactive = mensaje.get("interactive", {})
#                     boton_texto = interactive.get("button_reply", {}).get("title", "")
#                     print(f"👆 Botón en chat libre: {boton_texto}")
#                     guardar_mensaje(numero, boton_texto, tipo="recibido", es_audio=False)
#
#                 return {"status": "ok"}
#
#             # 9. Flujo normal (encuesta)
#             if paso is None and tipo == "interactive":
#                 interactive = mensaje.get("interactive", {})
#                 boton_texto = interactive.get("button_reply", {}).get("title", "").lower()
#                 if boton_texto == "sí, continuar":
#                     actualizar_flujo(numero, 1)
#                     enviar_pregunta(numero, 1)
#                     return {"status": "ok"}
#
#             if paso is None and tipo == "text":
#                 if texto in ["4", "chat libre"] and usuarios_roles.get(numero, ("",))[0] == "aspirante":
#                     actualizar_flujo(numero, "chat_libre")
#                     enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                     return {"status": "ok"}
#                 if texto in ["7", "chat libre"] and usuarios_roles.get(numero, ("",))[0] == "creador":
#                     actualizar_flujo(numero, "chat_libre")
#                     enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                     return {"status": "ok"}
#                 if texto in ["5", "chat libre"] and usuarios_roles.get(numero, ("",))[0] == "admin":
#                     actualizar_flujo(numero, "chat_libre")
#                     enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                     return {"status": "ok"}
#
#             # 10. FLUJO DE PREGUNTAS (encuesta)
#             manejar_respuesta(numero, texto)
#
#     except Exception as e:
#         print("❌ Error procesando webhook:", e)
#         traceback.print_exc()
#
#     return {"status": "ok"}
#

# @router.post("/webhook")
# async def whatsapp_webhook(request: Request):
#     data = await request.json()
#     print("📩 Webhook recibido:", json.dumps(data, indent=2))
#
#     try:
#         mensajes = data["entry"][0]["changes"][0]["value"].get("messages", [])
#         if not mensajes:
#             return {"status": "ok"}
#
#         for mensaje in mensajes:
#             numero = mensaje["from"]
#             tipo = mensaje.get("type")
#             texto = mensaje.get("text", {}).get("body", "").strip()
#             texto_lower = texto.lower()
#
#             paso = obtener_flujo(numero)  # usa caché robusta
#             usuario_bd = buscar_usuario_por_telefono(numero)
#             rol = obtener_rol_usuario(numero)
#
#             print(f"📍 [DEBUG] número={numero}, paso={paso}, usuario_bd={bool(usuario_bd)}, texto='{texto}'")
#
#             # --- 1. FLUJO DE NUEVO USUARIO ---
#             if not usuario_bd and paso is None:
#                 enviar_mensaje(numero, Mensaje_bienvenida)
#                 actualizar_flujo(numero, "esperando_usuario_tiktok")
#                 print(f"🟢 [DEBUG] Flujo inicial asignado: esperando_usuario_tiktok -> {numero}")
#                 return {"status": "ok"}
#
#             # --- 2. SALUDOS EN CUALQUIER MOMENTO ---
#             if tipo == "text" and texto_lower in ["hola", "buenas", "saludos"]:
#                 if usuario_bd:
#                     enviar_mensaje(numero, "👋 Hola, bienvenido a la Agencia Prestige.")
#                     enviar_menu_principal(numero, rol)
#                 else:
#                     enviar_mensaje(numero, Mensaje_bienvenida)
#                     actualizar_flujo(numero, "esperando_usuario_tiktok")
#                 return {"status": "ok"}
#
#             # --- 3. VOLVER AL MENÚ PRINCIPAL ---
#             if tipo == "text" and texto_lower in ["menu", "brillar"]:
#                 usuarios_flujo.pop(numero, None)
#                 enviar_menu_principal(numero, rol)
#                 return {"status": "ok"}
#
#             # --- 4. ESPERANDO USUARIO TIKTOK ---
#             if paso == "esperando_usuario_tiktok" and tipo == "text":
#                 usuario_tiktok = texto.strip()
#                 aspirante = buscar_aspirante_por_usuario_tiktok(usuario_tiktok)
#                 print(f"🔍 [DEBUG] Buscando aspirante TikTok: {usuario_tiktok} -> {bool(aspirante)}")
#
#                 if aspirante:
#                     nombre = aspirante.get("nickname") or aspirante.get("nombre_real") or "(sin nombre)"
#                     enviar_mensaje(numero, mensaje_confirmar_nombre(nombre))
#                     actualizar_flujo(numero, "confirmando_nombre")
#                     usuarios_temp[numero] = aspirante
#                     print(f"🟡 [DEBUG] Flujo actualizado a confirmando_nombre -> {numero}")
#                 else:
#                     enviar_mensaje(numero, "No encontramos ese usuario de TikTok en nuestra plataforma. ¿Puedes verificarlo?")
#                 return {"status": "ok"}
#
#             # --- 5. CONFIRMANDO NOMBRE ---
#             if paso == "confirmando_nombre" and tipo == "text":
#                 if texto_lower in ["si", "sí", "correcto", "yes", "ok", "sip", "acuerdo"]:
#                     aspirante = usuarios_temp.get(numero)
#                     if aspirante:
#                         actualizar_telefono_aspirante(aspirante["id"], numero)
#
#                     enviar_botones(
#                         numero,
#                         texto=mensaje_proteccion_datos(),
#                         botones=[{"id": "iniciar_encuesta", "title": "✅ Sí, quiero iniciar"}],
#                     )
#                     actualizar_flujo(numero, "esperando_inicio_encuesta")
#                     print(f"🟢 [DEBUG] Flujo actualizado a esperando_inicio_encuesta -> {numero}")
#                 else:
#                     enviar_mensaje(numero, "Por favor escribe el nombre correcto o verifica tu usuario de TikTok.")
#                 return {"status": "ok"}
#
#             # --- 6. ESPERANDO INICIO ENCUESTA ---
#             if paso == "esperando_inicio_encuesta":
#                 if tipo == "interactive":
#                     interactive = mensaje.get("interactive", {})
#                     if interactive.get("type") == "button_reply":
#                         button_id = interactive.get("button_reply", {}).get("id")
#                         if button_id == "iniciar_encuesta":
#                             actualizar_flujo(numero, 1)
#                             enviar_pregunta(numero, 1)
#                             print(f"🟢 [DEBUG] Encuesta iniciada -> paso=1 para {numero}")
#                             return {"status": "ok"}
#                 enviar_mensaje(numero, "Por favor usa el botón para iniciar la encuesta.")
#                 return {"status": "ok"}
#
#             # --- 7. ASIGNAR ROL ---
#             if usuario_bd and numero not in usuarios_roles:
#                 usuarios_roles[numero] = (usuario_bd["rol"], time.time())
#
#             # --- 8. CHAT LIBRE ---
#             if paso == "chat_libre":
#                 if tipo == "text":
#                     if texto_lower in ["menu", "brillar"]:
#                         usuarios_flujo.pop(numero, None)
#                         enviar_mensaje(numero, "🔙 Volviste al menú inicial.")
#                         enviar_menu_principal(numero, rol)
#                         return {"status": "ok"}
#                     print(f"💬 Chat libre de {numero}: {texto}")
#                     guardar_mensaje(numero, texto, tipo="recibido", es_audio=False)
#
#                 elif tipo == "audio":
#                     audio_id = mensaje.get("audio", {}).get("id")
#                     print(f"🎤 Audio recibido de {numero}: {audio_id}")
#                     url_cloudinary = descargar_audio(audio_id, TOKEN)
#                     if url_cloudinary:
#                         guardar_mensaje(numero, url_cloudinary, tipo="recibido", es_audio=True)
#                         enviar_mensaje(numero, "🎧 Recibimos tu audio. Un asesor lo revisará pronto.")
#                     else:
#                         enviar_mensaje(numero, "⚠️ No se pudo procesar tu audio, inténtalo de nuevo.")
#                 return {"status": "ok"}
#
#             # --- 9. FLUJO NORMAL (botón continuar) ---
#             if paso is None and tipo == "interactive":
#                 interactive = mensaje.get("interactive", {})
#                 boton_texto = interactive.get("button_reply", {}).get("title", "").lower()
#                 if boton_texto == "sí, continuar":
#                     actualizar_flujo(numero, 1)
#                     enviar_pregunta(numero, 1)
#                     print(f"🟢 [DEBUG] Flujo reiniciado con 'sí, continuar' -> {numero}")
#                     return {"status": "ok"}
#
#             # --- 10. ENTRADA DE TEXTO NORMAL ---
#             if paso is None and tipo == "text":
#                 rol_usuario = usuarios_roles.get(numero, ("",))[0]
#                 if texto_lower in ["4", "chat libre"] and rol_usuario == "aspirante":
#                     actualizar_flujo(numero, "chat_libre")
#                     enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                     return {"status": "ok"}
#                 if texto_lower in ["7", "chat libre"] and rol_usuario == "creador":
#                     actualizar_flujo(numero, "chat_libre")
#                     enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                     return {"status": "ok"}
#                 if texto_lower in ["5", "chat libre"] and rol_usuario == "admin":
#                     actualizar_flujo(numero, "chat_libre")
#                     enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                     return {"status": "ok"}
#
#             # --- 11. FLUJO DE PREGUNTAS (ENCUESTA) ---
#             manejar_respuesta(numero, texto)
#
#     except Exception as e:
#         print("❌ Error procesando webhook:", e)
#         traceback.print_exc()
#
#     return {"status": "ok"}

# ------------------------------------------------------------------
# ------------------------------------------------------------------

# def obtener_nombre_usuario(numero: str) -> str:
#     datos = usuarios_flujo.get(numero, {})
#     return datos.get("nombre", None)

# def obtener_nombre_usuario(numero: str) -> str:
#     datos = usuarios_flujo.get(numero, {})
#     assert isinstance(datos, dict), f"usuarios_flujo[{numero}] no es un dict: {type(datos)}"
#     return datos.get("nombre", None)
#
#
# # --- Función de inicialización segura ---
# def asegurar_flujo(numero):
#     if numero not in usuarios_flujo or not isinstance(usuarios_flujo[numero], dict):
#         usuarios_flujo[numero] = {}



# def manejar_respuesta(numero, texto):
#     texto = texto.strip()
#     texto_normalizado = texto.lower()
#     paso = obtener_flujo(numero)
#     rol = obtener_rol_usuario(numero)
#     flujo = asegurar_flujo(numero)  # 🔒 Inicialización segura
#     nombre = flujo.get("nombre") or obtener_nombre_usuario(numero)
#
#     # --- 1️⃣ SALUDOS INICIALES ---
#     if texto_normalizado in {"hola", "buenas", "saludos"}:
#         usuario_bd = buscar_usuario_por_telefono(numero)
#         if usuario_bd:
#             rol = usuario_bd.get("rol", "aspirante")
#             enviar_mensaje(numero, "👋 Hola, bienvenido a la Agencia.")
#             enviar_menu_principal(numero, rol)
#         else:
#             enviar_mensaje(numero, Mensaje_bienvenida)
#             actualizar_flujo(numero, "esperando_usuario_tiktok")
#         return
#
#     # --- 2️⃣ VOLVER AL MENÚ PRINCIPAL ---
#     if texto_normalizado in {"menu", "menú", "volver", "inicio", "brillar"}:
#         usuarios_flujo.pop(numero, None)
#         enviar_menu_principal(numero, rol)
#         return
#
#     # 🚫 CHAT LIBRE NO PROCESA FLUJOS
#     if paso == "chat_libre":
#         return
#
#     # --- 3️⃣ MENÚ PRINCIPAL POR ROL ---
#     if paso is None:
#         opciones = texto_normalizado
#         match rol:
#             case "aspirante":
#                 match opciones:
#                     case "1" | "actualizar" | "perfil":
#                         actualizar_flujo(numero, 1)
#                         enviar_pregunta(numero, 1)
#                     case "2" | "diagnóstico" | "diagnostico":
#                         actualizar_flujo(numero, "diagnostico")
#                         enviar_diagnostico(numero)
#                         usuarios_flujo.pop(numero, None)
#                     case "3" | "requisitos":
#                         actualizar_flujo(numero, "requisitos")
#                         enviar_requisitos(numero)
#                         usuarios_flujo.pop(numero, None)
#                     case "4" | "chat libre":
#                         actualizar_flujo(numero, "chat_libre")
#                         enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                     case _:
#                         enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
#                 return
#
#             case "creador":
#                 match opciones:
#                     case "1":
#                         actualizar_flujo(numero, 1)
#                         enviar_pregunta(numero, 1)
#                     case "3":
#                         actualizar_flujo(numero, "asesoria")
#                         enviar_mensaje(numero, "📌 Un asesor se pondrá en contacto contigo pronto.")
#                         usuarios_flujo.pop(numero, None)
#                     case "4":
#                         actualizar_flujo(numero, "recursos")
#                         enviar_recursos_exclusivos(numero)
#                         usuarios_flujo.pop(numero, None)
#                     case "5":
#                         actualizar_flujo(numero, "eventos")
#                         enviar_eventos(numero)
#                         usuarios_flujo.pop(numero, None)
#                     case "6":
#                         actualizar_flujo(numero, "soporte")
#                         enviar_mensaje(numero, "📩 Describe tu problema y el equipo técnico te responderá.")
#                     case "7" | "chat libre":
#                         actualizar_flujo(numero, "chat_libre")
#                         enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                     case "8":
#                         actualizar_flujo(numero, "estadisticas")
#                         enviar_estadisticas(numero)
#                         usuarios_flujo.pop(numero, None)
#                     case "9":
#                         actualizar_flujo(numero, "baja")
#                         solicitar_baja(numero)
#                         usuarios_flujo.pop(numero, None)
#                     case _:
#                         enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
#                 return
#
#             case "admin":
#                 match opciones:
#                     case "1":
#                         actualizar_flujo(numero, "panel")
#                         enviar_panel_control(numero)
#                     case "2":
#                         actualizar_flujo(numero, "ver_perfiles")
#                         enviar_perfiles(numero)
#                         usuarios_flujo.pop(numero, None)
#                     case "3":
#                         actualizar_flujo(numero, "comunicado")
#                         enviar_mensaje(numero, "✉️ Escribe el comunicado a enviar a creadores/aspirantes:")
#                     case "4":
#                         actualizar_flujo(numero, "recursos_admin")
#                         gestionar_recursos(numero)
#                         usuarios_flujo.pop(numero, None)
#                     case "5" | "chat libre":
#                         actualizar_flujo(numero, "chat_libre")
#                         enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
#                     case _:
#                         enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
#                 return
#
#             case _:
#                 if opciones == "1":
#                     actualizar_flujo(numero, "info")
#                     enviar_info_general(numero)
#                 else:
#                     enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.")
#                 return
#
#     # --- 4️⃣ FLUJO DE ENCUESTA ---
#     if isinstance(paso, int):
#         if paso == 1:
#             if len(texto) < 3:
#                 enviar_mensaje(numero, "⚠️ Ingresa tu nombre completo (mínimo 3 caracteres).")
#                 return
#             flujo["nombre"] = texto.title().strip()
#             nombre = flujo["nombre"]
#
#         validaciones = {
#             2: lambda t: t.isdigit() and 1 <= int(t) <= 5,
#             3: lambda t: t in {"1", "2", "3", "4"},
#             4: lambda t: t in list(mapa_paises.keys()) + ["20"] or t.lower() in [v.lower() for v in mapa_paises.values()],
#             6: lambda t: t in [str(i) for i in range(1, 10)],
#             7: lambda t: t in [str(i) for i in range(1, 6)],
#             9: lambda t: t in {"1", "2", "3"},
#             10: lambda t: t in {"1", "2", "3", "4"}
#         }
#
#         if paso in validaciones and not validaciones[paso](texto_normalizado):
#             enviar_mensaje(numero, f"⚠️ Ingresa una opción válida para la pregunta {paso}.")
#             return
#
#         if paso == 5:
#             resultado = validar_aceptar_ciudad(texto)
#             texto = resultado["ciudad"]
#             enviar_mensaje(numero, f"✅ Ciudad reconocida: {texto}")
#
#         if paso == 7:
#             enviar_mensaje(numero, "🎥 ¿Tienes experiencia transmitiendo lives en TikTok? Contesta *sí* o *no*.")
#             actualizar_flujo(numero, "7b")
#             return
#
#         if paso == 8:
#             try:
#                 meses = int(texto)
#                 if not (0 <= meses <= 999):
#                     raise ValueError
#             except ValueError:
#                 enviar_mensaje(numero, "⚠️ Ingresa un número válido de meses (0–999).")
#                 return
#             enviar_mensaje(numero, mensaje_encuesta_final_parte1(nombre))
#
#         guardar_respuesta(numero, paso, texto)
#         siguiente = paso + 1
#
#         # ✅ Finalización del flujo
#         if siguiente not in preguntas:
#             usuarios_flujo.pop(numero, None)
#             enviar_mensaje(numero, mensaje_encuesta_final(nombre))
#             consolidar_perfil(numero)
#             enviar_mensaje(numero, '✨ Para ir al menú principal escribe **"brillar"**')
#             return
#
#         actualizar_flujo(numero, siguiente)
#         texto_pregunta = preguntas[siguiente]
#         if "{nombre}" in texto_pregunta:
#             texto_pregunta = texto_pregunta.format(nombre=nombre)
#         enviar_mensaje(numero, texto_pregunta)
#         return
#
#     # --- 5️⃣ PREGUNTA CONDICIONAL (7b) ---
#     if paso == "7b":
#         if texto_normalizado in {"si", "sí", "s"}:
#             enviar_mensaje(numero, preguntas[8])
#             actualizar_flujo(numero, 8)
#         elif texto_normalizado in {"no", "n"}:
#             guardar_respuesta(numero, 8, "0")
#             enviar_mensaje(numero, preguntas[9])
#             actualizar_flujo(numero, 9)
#         else:
#             enviar_mensaje(numero, "Por favor responde solo *sí* o *no*.")



# def enviar_menu_principal(numero, rol=None):
#     if rol is None:
#         rol = obtener_rol_usuario(numero)
#
#     if rol == "aspirante":
#         mensaje = (
#             "👋 ¡Hola! Qué alegría tenerte en la Agencia Prestige.\n\n"
#             "¿En qué puedo ayudarte hoy?\n"
#             "1️⃣ Actualizar mi información de perfil\n"
#             "2️⃣ Diagnóstico y mejoras de mi perfil\n"
#             "3️⃣ Ver requisitos para ingresar a la Agencia\n"
#             "4️⃣ Chat libre con un asesor\n"
#             "Por favor responde con el número de la opción."
#         )
#     elif rol == "creador":
#         mensaje = (
#             "👋 ¡Hola, creador de la Agencia Prestige!\n\n"
#             "¿En qué puedo ayudarte hoy?\n"
#             "1️⃣ Actualizar mi información de perfil\n"
#             "3️⃣ Solicitar asesoría personalizada\n"
#             "4️⃣ Acceder a recursos exclusivos\n"
#             "5️⃣ Ver próximas actividades/eventos\n"
#             "6️⃣ Solicitar soporte técnico\n"
#             "7️⃣ Chat libre con el equipo\n"
#             "8️⃣ Ver mis estadísticas/resultados\n"
#             "9️⃣ Solicitar baja de la agencia"
#         )
#     elif rol == "admin":
#         mensaje = (
#             "👋 ¡Hola, administrador  de la Agencia Prestige!\n\n"
#             "¿En qué puedo ayudarte hoy?\n"
#             "1️⃣ Ver panel de control\n"
#             "2️⃣ Ver todos los perfiles\n"
#             "3️⃣ Enviar comunicado a creadores/aspirantes\n"
#             "4️⃣ Gestión de recursos\n"
#             "5️⃣ Chat libre con el equipo"
#         )
#     else:
#         mensaje = (
#             "👋 ¡Hola! Qué alegría tenerte en la Agencia Prestige.\n\n"
#             "¿En qué puedo ayudarte hoy?\n"
#             "1️⃣ Información general\n"
#             "2️⃣ Chat libre"
#         )
#     enviar_mensaje(numero, mensaje)

# def actualizar_flujo(numero, paso):
#     usuarios_flujo[numero] = (paso, time.time())

# def actualizar_flujo(numero, paso):
#     if numero not in usuarios_flujo or not isinstance(usuarios_flujo[numero], dict):
#         usuarios_flujo[numero] = {}
#     usuarios_flujo[numero]['paso'] = paso
#     usuarios_flujo[numero]['timestamp'] = time.time()
# def actualizar_flujo(numero, paso):
#     usuarios_flujo[numero] = {
#         "paso": paso,
#         "timestamp": time.time()
#     }

# def obtener_flujo(numero):
#     cache = usuarios_flujo.get(numero)
#     if cache and isinstance(cache, tuple) and len(cache) == 2:
#         paso, t = cache
#         if time.time() - t < TTL:
#             return paso
#         else:
#             usuarios_flujo.pop(numero, None)  # 🧹 expira por inactividad
#     return None

# def obtener_flujo(numero):
#     cache = usuarios_flujo.get(numero)
#     if cache and isinstance(cache, tuple) and len(cache) == 2:
#         paso, t = cache
#         if time.time() - t < TTL:
#             return paso
#         else:
#             usuarios_flujo.pop(numero, None)  # 🧹 expira por inactividad
#     return None


# def obtener_flujo(numero):
#     cache = usuarios_flujo.get(numero)
#     ahora = time.time()
#
#     # 🧱 Nuevo formato (dict)
#     if isinstance(cache, dict):
#         paso = cache.get("paso")
#         t = cache.get("timestamp", 0)
#         if paso and ahora - t < TTL:
#             return paso
#         usuarios_flujo.pop(numero, None)
#         return None
#
#     # 🧩 Formato antiguo (tuple)
#     if isinstance(cache, tuple) and len(cache) == 2:
#         paso, t = cache
#         if paso and ahora - t < TTL:
#             return paso
#         usuarios_flujo.pop(numero, None)
#         return None
#
#     return None

# def actualizar_flujo(numero, paso):
#     ahora = time.time()
#
#     # 🧹 Limpieza ligera de entradas viejas (TTL global)
#     for k, v in list(usuarios_flujo.items()):
#         if isinstance(v, dict) and ahora - v.get("timestamp", 0) > TTL:
#             usuarios_flujo.pop(k, None)
#
#     # Actualización directa
#     usuarios_flujo[numero] = {"paso": paso, "timestamp": ahora}

# def enviar_diagnostico(numero: str):
#     """Envía el diagnóstico de un usuario tomando el campo observaciones de perfil_creador"""
#     try:
#         with psycopg2.connect(INTERNAL_DATABASE_URL) as conn:
#             with conn.cursor() as cur:
#
#                 # 1️⃣ Buscar el creador por su número
#                 cur.execute("SELECT id, usuario, nombre_real FROM creadores WHERE whatsapp = %s", (numero,))
#                 creador = cur.fetchone()
#                 if not creador:
#                     print(f"⚠️ No se encontró creador con whatsapp {numero}")
#                     enviar_mensaje(numero, "No encontramos tu perfil en el sistema. Verifica tu número.")
#                     return
#
#                 creador_id, usuario, nombre_real = creador
#
#                 # 2️⃣ Obtener observaciones desde perfil_creador
#                 cur.execute("SELECT mejoras_sugeridas FROM perfil_creador WHERE creador_id = %s", (creador_id,))
#                 fila = cur.fetchone()
#
#         nombre = nombre_real if nombre_real else usuario
#         if not fila or not fila[0]:
#             diagnostico = f"🔎 Diagnóstico para {nombre}:\nEstamos preparando tu evaluación de tu perfil."
#         else:
#             diagnostico = f"🔎 Diagnóstico para {nombre}:\n\n{fila[0]}"
#
#         # 3️⃣ Enviar el diagnóstico
#         enviar_mensaje(numero, diagnostico)
#         print(f"✅ Diagnóstico enviado a {numero}")
#
#     except Exception as e:
#         print(f"❌ Error al enviar diagnóstico a {numero}:", str(e))
#         enviar_mensaje(numero, "Ocurrió un error al generar tu diagnóstico. Intenta más tarde.")
