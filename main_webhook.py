# ============================
# IMPORTS - Estándar de Python
# ============================
import json
import os
import time
import traceback
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

# ============================
# IMPORTS - Terceros
# ============================
import psycopg2
from dotenv import load_dotenv
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from rapidfuzz import process, fuzz

# ============================
# IMPORTS - Locales
# ============================
from DataBase import *
from enviar_msg_wp import (
    enviar_boton_iniciar_Completa,
    enviar_botones_Completa,
    enviar_mensaje_texto_simple,
    enviar_plantilla_generica,
    enviar_plantilla_generica_parametros
)

from main import guardar_mensaje
from tenant import (
    current_business_name,
    current_phone_id,
    current_tenant,
    current_token
)
from utils import *
from redis_client import redis_set_temp, redis_get_temp, redis_delete_temp
from utils_aspirantes import guardar_estado_eval, obtener_status_24hrs, Enviar_msg_estado, \
    enviar_plantilla_estado_evaluacion, buscar_estado_creador, \
    accion_menu_estado_evaluacion, validar_url_link_tiktok_live, guardar_link_tiktok_live, \
    actualizar_mensaje_desde_status, _handle_statuses, enviar_confirmacion_interactiva



# from utils_aspirantes import guardar_estado_eval, obtener_status_24hrs, Enviar_msg_estado, \
#     enviar_plantilla_estado_evaluacion, obtener_creador_id_por_telefono, buscar_estado_creador, Enviar_menu_quickreply, \
#     accion_menu_estado_evaluacion, validar_url_link_tiktok_live, guardar_link_tiktok_live, \
#     actualizar_mensaje_desde_status, _handle_statuses, enviar_confirmacion_interactiva

load_dotenv()

# ============================
# CONFIGURACIÓN - URLs Frontend
# ============================
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "https://talentum-manager.com")

def construir_url_actualizar_perfil(numero: str, tenant_name: Optional[str] = None) -> str:
    """
    Construye la URL para actualizar perfil usando solo FRONTEND_BASE_URL.

    Args:
        numero: Número de teléfono del usuario
        tenant_name: Nombre del tenant (opcional)

    Returns:
        URL completa para actualizar perfil, por ejemplo:
        https://agencia.talentum-manager.com/actualizar-perfil?numero=573001112233
    """
    # Remover https:// y www. si están presentes, para poder insertar el tenant
    domain = FRONTEND_BASE_URL.replace("https://", "").replace("http://", "").replace("www.", "")
    
    if tenant_name:
        base_url = f"https://{tenant_name}.{domain}"
    else:
        base_url = f"https://{domain}"
    
    return f"{base_url}/actualizar-perfil?numero={numero}"

router = APIRouter()

# Estado del flujo en memoria
usuarios_flujo = {}    # { numero: paso_actual }
# ⚠️ respuestas = {} - ELIMINADO: No se usaba. Las respuestas se guardan en perfil_creador_flujo_temp
usuarios_temp = {}  # ⚠️ Fallback a memoria si Redis falla (solo para datos temporales de onboarding)

# ============================
# ENVIAR MENSAJES INICIO
# ============================

def enviar_mensaje(numero: str, texto: str):

    try:
        # Validar entrada
        if not numero or not numero.strip():
            raise ValueError("Número de teléfono no puede estar vacío")
        if not texto or not texto.strip():
            raise ValueError("Texto del mensaje no puede estar vacío")
        
        # Obtener contexto del tenant
        try:
            token = current_token.get()
            phone_id = current_phone_id.get()

            # Seguros: solo últimos 6 chars visibles
            token_safe = f"...{token[-6:]}" if token else "None"
            phone_id_safe = f"...{phone_id[-6:]}" if phone_id else "None"

            print(f"🔐 Token usado: {token_safe}")
            print(f"📱 Phone ID usado: {phone_id_safe}")


        except LookupError as e:
            print(f"❌ Contexto de tenant no disponible al enviar mensaje a {numero}: {e}")
            raise LookupError(f"Contexto de tenant no disponible: {e}") from e
        
        return enviar_mensaje_texto_simple(
            token=token,
            numero_id=phone_id,
            telefono_destino=numero.strip(),
            texto=texto.strip()
        )
    except (LookupError, ValueError) as e:
        # Re-raise errores de validación y contexto
        raise
    except Exception as e:
        print(f"❌ Error enviando mensaje a {numero}: {e}")
        traceback.print_exc()
        raise

def enviar_boton_iniciar(numero: str, texto: str):
    """
    Envía un mensaje con botón de inicio a través de WhatsApp.
    
    Args:
        numero: Número de teléfono del destinatario
        texto: Contenido del mensaje
    
    Returns:
        Respuesta de la API de WhatsApp
    
    Raises:
        LookupError: Si el contexto de tenant no está disponible
        ValueError: Si el número o texto son inválidos
        Exception: Si hay error al enviar el mensaje
    """
    try:
        if not numero or not numero.strip():
            raise ValueError("Número de teléfono no puede estar vacío")
        if not texto or not texto.strip():
            raise ValueError("Texto del mensaje no puede estar vacío")
        
        try:
            token = current_token.get()
            phone_id = current_phone_id.get()
        except LookupError as e:
            print(f"❌ Contexto de tenant no disponible al enviar botón a {numero}: {e}")
            raise LookupError(f"Contexto de tenant no disponible: {e}") from e
        
        return enviar_boton_iniciar_Completa(
            token=token,
            numero_id=phone_id,
            telefono_destino=numero.strip(),
            texto=texto.strip()
        )
    except (LookupError, ValueError) as e:
        raise
    except Exception as e:
        print(f"❌ Error enviando botón a {numero}: {e}")
        traceback.print_exc()
        raise

def enviar_botones(numero: str, texto: str, botones: list):
    """
    Envía un mensaje con botones interactivos a través de WhatsApp.
    
    Args:
        numero: Número de teléfono del destinatario
        texto: Contenido del mensaje
        botones: Lista de botones a mostrar
    
    Returns:
        Respuesta de la API de WhatsApp
    
    Raises:
        LookupError: Si el contexto de tenant no está disponible
        ValueError: Si los parámetros son inválidos
        Exception: Si hay error al enviar el mensaje
    """
    try:
        if not numero or not numero.strip():
            raise ValueError("Número de teléfono no puede estar vacío")
        if not texto or not texto.strip():
            raise ValueError("Texto del mensaje no puede estar vacío")
        if not botones or not isinstance(botones, list):
            raise ValueError("Botones debe ser una lista no vacía")
        
        try:
            token = current_token.get()
            phone_id = current_phone_id.get()
        except LookupError as e:
            print(f"❌ Contexto de tenant no disponible al enviar botones a {numero}: {e}")
            raise LookupError(f"Contexto de tenant no disponible: {e}") from e
        
        return enviar_botones_Completa(
            token=token,
            numero_id=phone_id,
            telefono_destino=numero.strip(),
            texto=texto.strip(),
            botones=botones
        )
    except (LookupError, ValueError) as e:
        raise
    except Exception as e:
        print(f"❌ Error enviando botones a {numero}: {e}")
        traceback.print_exc()
        raise

def enviar_inicio_encuesta_plantilla(numero: str):
    """
    Envía una plantilla de inicio de encuesta a través de WhatsApp.
    
    Args:
        numero: Número de teléfono del destinatario
    
    Returns:
        Respuesta de la API de WhatsApp
    
    Raises:
        LookupError: Si el contexto de tenant no está disponible
        ValueError: Si el número es inválido
        Exception: Si hay error al enviar la plantilla
    """
    try:
        if not numero or not numero.strip():
            raise ValueError("Número de teléfono no puede estar vacío")
        
        try:
            token = current_token.get()
            phone_id = current_phone_id.get()
            nombre_agencia = current_business_name.get()
        except LookupError as e:
            print(f"❌ Contexto de tenant no disponible al enviar plantilla a {numero}: {e}")
            raise LookupError(f"Contexto de tenant no disponible: {e}") from e
        
        parametros = [
            nombre_agencia,     # Llene {{1}} del body
            numero              # Llene {{2}} del botón dinámico
        ]
        
        return enviar_plantilla_generica_parametros(
            token=token,
            phone_number_id=phone_id,
            numero_destino=numero.strip(),
            nombre_plantilla="inicio_encuesta",
            codigo_idioma="es_CO",
            parametros=parametros
        )
    except (LookupError, ValueError) as e:
        raise
    except Exception as e:
        print(f"❌ Error enviando plantilla de inicio de encuesta a {numero}: {e}")
        traceback.print_exc()
        raise

# ============================
# FIN ENVIAR MENSAJES
# ============================



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

def asegurar_flujo(numero: str) -> dict:
    if numero not in usuarios_flujo or not isinstance(usuarios_flujo[numero], dict):
        usuarios_flujo[numero] = {"timestamp": time.time()}
    return usuarios_flujo[numero]

def eliminar_flujo(numero: str, tenant_schema: Optional[str] = None):
    """Reinicia cualquier flujo o estado temporal del usuario."""
    usuarios_flujo.pop(numero, None)
    # ✅ Limpiar también de Redis
    try:
        redis_delete_temp(numero)
    except Exception as e:
        print(f"⚠️ Error eliminando de Redis en eliminar_flujo para {numero}: {e}")
    usuarios_temp.pop(numero, None)  # Limpiar también de memoria (fallback)
    print(f"🧹 Flujo reiniciado para {numero}")


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
    rol = "aspirante_entrevista" #-- quitar luego

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

    # --- MENÚ POR ROL ---
    if rol == "aspirante_entrevista":
        mensaje = (
            f"{encabezado}"
            "1️⃣ Adjuntar link TikTok LIVE\n"
            "2️⃣ Citas agendadas\n"
            "3️⃣ Chat libre con un asesor\n"
            "4️⃣ Guia presentación tikTok LIVE\n"
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

def enviar_diagnostico(numero: str) -> bool:

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # 1️⃣ Buscar el creador por su número
                cur.execute(
                    """
                    SELECT id, usuario, COALESCE(nombre_real, usuario) AS nombre_real
                    FROM creadores
                    WHERE whatsapp = %s
                    LIMIT 1;
                    """,
                    (numero,),
                )
                row = cur.fetchone()

                if not row:
                    print(f"⚠️ No se encontró creador con whatsapp {numero}")
                    enviar_mensaje(numero, "No encontramos tu perfil en el sistema. Verifica tu número.")
                    return False

                creador_id, usuario, nombre_real = row

                # 2️⃣ Obtener mejoras_sugeridas desde perfil_creador
                cur.execute(
                    """
                    SELECT mejoras_sugeridas
                    FROM perfil_creador
                    WHERE creador_id = %s
                    LIMIT 1;
                    """,
                    (creador_id,),
                )
                fila = cur.fetchone()

        # 3️⃣ Armar el diagnóstico fuera del contexto de conexión
        if not fila or not fila[0] or not str(fila[0]).strip():
            diagnostico = (
                f"🔎 Diagnóstico para {nombre_real}:\n"
                "Aún estamos preparando la evaluación de tu perfil. "
                "Te avisaremos tan pronto esté lista. ⏳"
            )
        else:
            mejoras = str(fila[0]).strip()
            diagnostico = f"🔎 Diagnóstico para {nombre_real}:\n\n{mejoras}"

        # 4️⃣ Enviar el diagnóstico
        enviar_mensaje(numero, diagnostico)
        print(f"✅ Diagnóstico enviado correctamente a {numero} ({nombre_real})")
        return True

    except psycopg2.OperationalError as e:
        print(f"❌ Error de conexión a BD al enviar diagnóstico a {numero}: {e}")
        traceback.print_exc()
        try:
            enviar_mensaje(numero, "Ocurrió un error de conexión al generar tu diagnóstico. Intenta más tarde.")
        except Exception:
            pass  # Si falla el mensaje de error, no hacer nada más
        return False
    except LookupError as e:
        print(f"❌ Error de contexto al enviar diagnóstico a {numero}: {e}")
        traceback.print_exc()
        try:
            enviar_mensaje(numero, "Ocurrió un error de configuración. Intenta más tarde.")
        except Exception:
            pass
        return False
    except Exception as e:
        print(f"❌ Error inesperado al enviar diagnóstico a {numero}: {e}")
        traceback.print_exc()
        try:
            enviar_mensaje(numero, "Ocurrió un error al generar tu diagnóstico. Intenta más tarde.")
        except Exception as e2:
            print(f"❌ Error adicional al intentar notificar al usuario {numero}: {e2}")
            traceback.print_exc()
        return False


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

def enviar_guia_tikTok_LIVE(numero):
    requisitos = (
        "📋 *Requisitos para Haer TikTok LIVE:*\n"
        "1️⃣ 1) .\n"
        "2️⃣ 2) .\n"
        "3️⃣ 3) .\n"
        "4️⃣ 4) .\n"
        "\n¿Tienes dudas? Responde este mensaje y te ayudamos. Puedes volver al *menú principal* escribiendo 'menu'."
    )
    enviar_mensaje(numero, requisitos)


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
    respuesta_8 = respuestas.get(8, "").strip().lower()
    # Considera "sí", "si", "s" o "1" como afirmativo
    if respuesta_8 in {"si", "sí", "s", "1"}:
        try:
            meses = int(respuestas.get(9, 0))
            experiencia_tiktok = round(meses / 12, 1)
        except Exception:
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

def consolidar_perfil(telefono: str, respuestas_dict: dict | None = None, tenant_schema: Optional[str] = None):
    """Procesa y actualiza un solo número en perfil_creador con manejo de errores
    
    Args:
        telefono: Número de teléfono del usuario
        respuestas_dict: Diccionario opcional con respuestas {paso: respuesta}.
                        Si es None, se leen de la tabla perfil_creador_flujo_temp
        tenant_schema: Schema del tenant. Si es None, usa current_tenant.get()
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # Buscar creador por número
                cur.execute("SELECT id, usuario, nombre_real, whatsapp FROM creadores WHERE telefono=%s", (telefono,))
                creador = cur.fetchone()
                if not creador:
                    print(f"⚠️ No se encontró creador con whatsapp {telefono}")
                    return

                creador_id = creador[0]

                # Si no se pasaron respuestas, leerlas de la tabla perfil_creador_flujo_temp
                if respuestas_dict is None:
                    cur.execute("""
                        SELECT paso, respuesta 
                        FROM perfil_creador_flujo_temp 
                        WHERE telefono=%s 
                        ORDER BY paso ASC
                    """, (telefono,))
                    rows = cur.fetchall()
                    respuestas_dict = {int(p): r for p, r in rows} if rows else {}
                    print(f"📋 Respuestas leídas de la tabla: {respuestas_dict}")

                # Procesar respuestas
                datos_update = procesar_respuestas(respuestas_dict)

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

    except psycopg2.OperationalError as e:
        print(f"❌ Error de conexión a BD al consolidar perfil para {telefono}: {e}")
        traceback.print_exc()
    except psycopg2.IntegrityError as e:
        print(f"❌ Error de integridad en BD al consolidar perfil para {telefono}: {e}")
        traceback.print_exc()
    except KeyError as e:
        print(f"❌ Error de clave faltante al consolidar perfil para {telefono}: {e}")
        traceback.print_exc()
    except Exception as e:
        print(f"❌ Error inesperado al procesar número {telefono}: {e}")
        traceback.print_exc()

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


def mensaje_encuesta_final(nombre: str | None = None) -> str:
    nombre_agencia = current_business_name.get()

    if nombre:
        return (
            f"✅ ¡Gracias, *{nombre}*! 🙌\n\n"
            f"*{nombre_agencia}* validará tu información y en las próximas 2 horas te daremos una respuesta.\n\n"
            "Si prefieres, también puedes consultarla desde el menú de opciones."
        )
    else:
        return (
            "✅ ¡Gracias! 🙌\n\n"
            f"*{nombre_agencia}* validará tu información y en las próximas horas te daremos una respuesta.\n\n"
            "Si prefieres, también puedes consultarla desde el menú de opciones."
        )


def obtener_nombre_usuario(numero: str) -> str | None:
    datos = usuarios_flujo.get(numero)
    if isinstance(datos, dict):
        return datos.get("nombre")
    # Limpieza automática si el valor es inválido
    usuarios_flujo.pop(numero, None)
    return None

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
    # elif isinstance(paso, int):
    #     manejar_encuesta(numero, texto, texto_normalizado, paso, rol)  # 👈 ENCUESTA
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
    tenant_name = current_tenant.get()  # ✅ Obtenemos el tenant actual
    # Menús por rol

    if rol == "aspirante":
        if texto_normalizado in {"1", "actualizar mi información", "perfil"}:
            marcar_encuesta_no_finalizada(numero)
            actualizar_flujo(numero, 1)

            # 1) PARA ACTUALIZAR INFO DESDE WHATSAPP DESMARCAR 1 Y MARCAR 2:
            # -------------------------------------------------
            # enviar_pregunta(numero, 1)
            # enviar_mensaje(numero, "✏️ Perfecto. Vamos a actualizar tu información. Empecemos...")
            # -------------------------------------------------

            # 2) PARA ACTUALIZAR INFO DESDE REACT DESMARCAR 2 Y MARCAR 1:
            # -------------------------------------------------
            url_web = construir_url_actualizar_perfil(numero, tenant_name=tenant_name)
            enviar_mensaje(
                numero,
                f"✏️ Para actualizar tu información de perfil, haz clic en este enlace:\n{url_web}\n\nPuedes hacerlo desde tu celular o computadora."
            )
            # -------------------------------------------------

            return
        if texto_normalizado in {"2", "análisis", "diagnóstico", "diagnostico"}:
            actualizar_flujo(numero, "diagnostico")

            # marcar y desmarcar despues
            # ----------------------------
            enviar_citas_agendadas(numero)
            # enviar_diagnostico(numero)
            # ----------------------------

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

    # ------------------------------------------------------------------
    # 🟠 NUEVO MENÚ PARA ROL ASPIRANTE_EN ENTREVISTA / PRUEBA LIVE
    # ------------------------------------------------------------------
    rol = "aspirante_entrevista" #-- quitar luego
    if rol == "aspirante_entrevista":
        # 1) Adjuntar link TikTok LIVE
        if texto_normalizado in {"1", "link tiktok live", "live tiktok", "enviar link live"}:
            # 👇 Este paso se usará luego en _process_single_message
            actualizar_flujo(numero, "esperando_link_tiktok_live")
            enviar_mensaje(
                numero,
                "🟢 Cuando inicies el LIVE pega aquí el link para que te podamos evaluar."
            )
            return

        # 2) Ver citas agendadas
        if texto_normalizado in {"2", "citas agendadas", "citas"}:
            actualizar_flujo(numero, "citas_agendadas")
            # Aquí podrías llamar a una función específica si ya la tienes
            # enviar_citas_agendadas(numero)
            enviar_mensaje(
                numero,
                "📅 Estas son tus citas agendadas. (Próximamente mostraremos el detalle desde sistema 😉)"
            )
            enviar_citas_agendadas(numero)
            usuarios_flujo.pop(numero, None)
            return

        # 3) Chat libre
        if texto_normalizado in {"3", "chat libre"}:
            actualizar_flujo(numero, "chat_libre")
            enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.")
            return

        # 4) Guía presentación TikTok LIVE
        if texto_normalizado in {
            "4",
            "guia presentacion tiktok live",
            "guía presentación tiktok live",
            "guia live"
        }:
            actualizar_flujo(numero, "guia_presentacion_tiktok_live")
            enviar_guia_tikTok_LIVE(numero)
            usuarios_flujo.pop(numero, None)
            return

        # Opción no válida → podrías reenviar menú específico de entrevista
        datos = buscar_usuario_por_telefono(numero) or {}
        nombre = (datos.get("nombre") or "").split(" ")[0]
        enviar_menu_principal(numero, rol=rol, nombre=nombre)
        return

# ----------------------------------------------------------------------
# ----------------------------------------------------------------------

    if rol == "creador":
        if texto_normalizado == "1":
            actualizar_flujo(numero, 1)
            # enviar_pregunta(numero, 1)
            enviar_inicio_encuesta(numero)
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


# manejo de encuesta y envío de preguntas

# --- Asumo que estas funciones y estructuras están definidas en tu proyecto ---
# asegurar_flujo(numero) -> dict
# guardar_respuesta(numero, paso, valor)
# actualizar_flujo(numero, siguiente)
# enviar_mensaje(numero, texto)
# validar_aceptar_ciudad(texto) -> dict con keys "corregida" y "ciudad"
# consolidar_perfil(numero)
# marcar_encuesta_completada(numero) -> bool
# usuarios_flujo: dict (cache en memoria)
# -------------------------------------------------------------------------

# ============================
# FUNCIONES HELPER PARA WEBHOOK
# ============================

def _extract_webhook_data(data: dict) -> Optional[dict]:
    """
    Extrae y valida los datos del webhook.
    
    Returns:
        Dict con entry, change, value, field, event o None si hay error
    """
    try:
        entry = data.get("entry", [])
        if not entry:
            return None
        
        change = entry[0].get("changes", [])
        if not change:
            return None
        
        change_data = change[0]
        value = change_data.get("value", {})
        field = change_data.get("field")
        event = value.get("event")
        
        return {
            "entry": entry[0],
            "change": change_data,
            "value": value,
            "field": field,
            "event": event
        }
    except (IndexError, KeyError, TypeError) as e:
        print(f"❌ Error extrayendo datos del webhook: {e}")
        return None


def _handle_account_update_event(entry: dict, change: dict, value: dict, event: str) -> dict:
    """
    Maneja eventos de actualización de cuenta (account_update).
    
    Returns:
        Dict con status y resultado del procesamiento
    """
    waba_info = value.get("waba_info", {})
    waba_id = waba_info.get("waba_id")
    owner_id = waba_info.get("owner_business_id")
    partner_app_id = waba_info.get("partner_app_id")
    
    print(f"🟦 Evento de cuenta detectado ({value.get('event')}):")
    print(f"➡️ WABA_ID: {waba_id}")
    print(f"➡️ OWNER_ID: {owner_id}")
    print(f"➡️ PARTNER_APP_ID: {partner_app_id}")
    
    resultado = procesar_evento_partner_instalado(entry, change, value, event)
    if resultado.get("status") in ("waba_linked", "missing_token", "error_getting_number"):
        return resultado  # Detenemos el flujo si es evento de instalación
    
    return {"status": "ok"}


def _setup_tenant_context(phone_number_id: str) -> Optional[dict]:
    """
    Configura el contexto del tenant basado en phone_number_id.
    
    Returns:
        Dict con información de la cuenta o None si no se encuentra
    """
    cuenta = obtener_cuenta_por_phone_id(phone_number_id)
    if not cuenta:
        print(f"⚠️ No se encontró cuenta asociada al número {phone_number_id}")
        return None
    
    # Extraer info de la cuenta
    token_cliente = cuenta["access_token"]
    phone_id_cliente = cuenta["phone_number_id"]
    tenant_name = cuenta["subdominio"]
    business_name = cuenta["business_name"]
    
    # Asignar valores de contexto
    current_token.set(token_cliente)
    current_phone_id.set(phone_id_cliente)
    current_tenant.set(tenant_name)
    current_business_name.set(business_name)
    
    print(f"🌐 Tenant actual: {current_tenant.get()}")
    print(f"🔑 Token actual: {current_token.get()}")
    print(f"📞 phone_id actual: {current_phone_id.get()}")
    print(f"📞 business_name: {current_business_name.get()}")

    return {
        "access_token": token_cliente,
        "phone_number_id": phone_id_cliente,
        "tenant_name": tenant_name,
        "business_name": business_name
    }


def _process_chat_libre_message(mensaje: dict, numero: str) -> dict:
    """
    Procesa mensajes cuando el usuario está en modo chat libre.
    
    Returns:
        Dict con status
    """
    tipo = mensaje.get("type")
    
    if tipo == "text":
        texto = mensaje.get("text", {}).get("body", "").strip()
        guardar_mensaje(numero, texto, tipo="recibido", es_audio=False)
    elif tipo == "audio":
        audio_id = mensaje.get("audio", {}).get("id")
        url_cloudinary = descargar_audio(audio_id, current_token.get())
        if url_cloudinary:
            guardar_mensaje(numero, url_cloudinary, tipo="recibido", es_audio=True)
            enviar_mensaje(numero, "🎧 Recibimos tu audio. Un asesor lo revisará pronto.")
        else:
            enviar_mensaje(numero, "⚠️ No se pudo procesar tu audio, inténtalo de nuevo.")
    
    return {"status": "ok"}


def _process_interactive_message(mensaje: dict, numero: str, paso: Optional[str | int]) -> dict:
    """
    Procesa mensajes interactivos (botones).
    
    Returns:
        Dict con status
    """
    print("🔘 [DEBUG] Se recibió un mensaje interactivo:", json.dumps(mensaje, indent=2))
    
    interactive = mensaje.get("interactive", {})
    if interactive.get("type") == "button_reply":
        button_data = interactive.get("button_reply", {})
        button_id = button_data.get("id")
        button_title = button_data.get("title")
        
        print(f"🧩 [DEBUG] Botón presionado -> id='{button_id}', título='{button_title}'")
        print(f"📍 [DEBUG] Paso actual del usuario: {paso}")
        
        # Aquí se pueden agregar más botones en el futuro
        enviar_mensaje(numero, "Este botón no es válido en este momento.")
    
    return {"status": "ok"}


from typing import Optional


def _process_new_user_onboarding(
    mensaje: dict,
    numero: str,
    texto: str,
    texto_lower: str,
    payload: str,
    paso: Optional[str | int],
    tenant_name: str,
    phone_id: str = None,
    token: str = None
) -> Optional[dict]:
    """
    Flujo de onboarding para nuevos usuarios vía WhatsApp.
    Pide usuario TikTok → confirma nickname → envía encuesta.
    """

    tipo = mensaje.get("type")

    # -----------------------------------------------------
    # VALIDACIÓN DE TIPO DE MENSAJE
    # -----------------------------------------------------
    if tipo not in ["text", "interactive"]:
        return None

    # Extraer payload si es botón
    if not payload and tipo == "interactive":
        payload = (
            mensaje.get("interactive", {})
            .get("button_reply", {})
            .get("id")
        )

    # -----------------------------------------------------
    # VALIDACIÓN DE PASO (ANTI-CORRUPCIÓN DE FLUJO)
    # -----------------------------------------------------
    pasos_validos = [
        None,
        "esperando_usuario_tiktok",
        "confirmando_nickname",
        "esperando_inicio_encuesta",
    ]

    if paso not in pasos_validos:
        print(f"⚠️ Reiniciando flujo para {numero}, paso inválido: {paso}")
        eliminar_flujo(numero)
        paso = None

    # =====================================================
    # PASO 0 – INICIO
    # =====================================================
    if paso is None:
        enviar_mensaje(
            numero,
            "¡Hola! 👋 Bienvenido.\n"
            "Para comenzar, por favor escribe tu *usuario de TikTok* "
            "(sin @)."
        )
        actualizar_flujo(numero, "esperando_usuario_tiktok")
        return {"status": "ok"}

    # =====================================================
    # PASO 1 – ESPERANDO USUARIO TIKTOK
    # =====================================================
    if paso == "esperando_usuario_tiktok":

        if tipo != "text":
            enviar_mensaje(numero, "✍️ Por favor escribe tu usuario de TikTok.")
            return {"status": "ok"}

        input_usuario = texto.strip()
        aspirante = buscar_aspirante_por_usuario_tiktok(input_usuario)

        if not aspirante:
            enviar_mensaje(
                numero,
                "❌ No encontramos ese usuario.\n"
                "Verifica e inténtalo nuevamente."
            )
            return {"status": "ok"}

        # 🔑 NICKNAME REAL (LO ÚNICO QUE SE CONFIRMA)
        nickname_tiktok = (
            aspirante.get("usuario_tiktok")
            or aspirante.get("nickname")
        )

        if not nickname_tiktok:
            enviar_mensaje(
                numero,
                "⚠️ Encontramos el perfil, pero no pudimos obtener "
                "el usuario de TikTok. Escríbelo nuevamente."
            )
            return {"status": "ok"}

        # Guardar aspirante temporal
        try:
            redis_set_temp(numero, aspirante, ttl=900)
        except Exception as e:
            print(f"⚠️ Redis falló, usando memoria: {e}")
            usuarios_temp[numero] = aspirante

        # Confirmación con botones
        if phone_id and token:
            enviar_confirmacion_interactiva(
                numero=numero,
                nickname=nickname_tiktok,  # ✅ SIEMPRE EL NICKNAME
                phone_id=phone_id,
                token=token
            )
        else:
            enviar_mensaje(
                numero,
                f"Encontramos el usuario: *{nickname_tiktok}*.\n"
                "¿Eres tú? (Responde SÍ o NO)"
            )

        actualizar_flujo(numero, "confirmando_nickname")
        return {"status": "ok"}

    # =====================================================
    # PASO 2 – CONFIRMANDO NICKNAME
    # =====================================================
    if paso == "confirmando_nickname":

        es_si = (
            payload == "BTN_CONFIRM_YES"
            or (tipo == "text" and texto_lower in ["si", "sí", "s", "y", "yes"])
        )

        es_no = (
            payload == "BTN_CONFIRM_NO"
            or (tipo == "text" and texto_lower in ["no", "n"])
        )

        # -------------------------
        # CONFIRMA QUE SÍ
        # -------------------------
        if es_si:
            aspirante = redis_get_temp(numero) or usuarios_temp.get(numero)

            if not aspirante:
                enviar_mensaje(
                    numero,
                    "⏳ La sesión expiró. "
                    "Por favor escribe nuevamente tu usuario de TikTok."
                )
                actualizar_flujo(numero, "esperando_usuario_tiktok")
                return {"status": "ok"}

            # Asociar teléfono
            actualizar_telefono_aspirante(aspirante["id"], numero)

            # Limpiar temporales
            try:
                redis_delete_temp(numero)
            except:
                pass
            usuarios_temp.pop(numero, None)

            # Enviar encuesta
            enviar_inicio_encuesta(numero)
            actualizar_flujo(numero, "esperando_inicio_encuesta")
            return {"status": "ok"}

        # -------------------------
        # CONFIRMA QUE NO
        # -------------------------
        if es_no:
            enviar_mensaje(
                numero,
                "👌 Entendido.\n"
                "Por favor escribe nuevamente tu *usuario de TikTok* correcto."
            )

            try:
                redis_delete_temp(numero)
            except:
                pass
            usuarios_temp.pop(numero, None)

            actualizar_flujo(numero, "esperando_usuario_tiktok")
            return {"status": "ok"}

        # -------------------------
        # INPUT INVÁLIDO
        # -------------------------
        enviar_mensaje(
            numero,
            "⚠️ No te entendí.\n"
            "Por favor selecciona una de las opciones."
        )
        return {"status": "ok"}

    # =====================================================
    # PASO 3 – REENVÍO DE LINK DE ENCUESTA
    # =====================================================
    if paso == "esperando_inicio_encuesta":
        tenant_actual = tenant_name or current_tenant.get() or "default"
        url_web = construir_url_actualizar_perfil(
            numero,
            tenant_name=tenant_actual
        )

        enviar_mensaje(
            numero,
            "📋 Para comenzar la encuesta, haz clic aquí:\n\n"
            f"{url_web}\n\n"
            "Puedes hacerlo desde tu celular o computadora."
        )
        return {"status": "ok"}

    return None





def _process_aspirante_message(mensaje: dict, numero: str, texto_lower: str, rol: str, tenant_name: str) -> dict:
    """
    Procesa mensajes de usuarios con rol 'aspirante'.
    
    Returns:
        Dict con status
    """
    finalizada = encuesta_finalizada(numero)
    
    # Si encuesta finalizada, SIEMPRE muestra el menú para cualquier mensaje
    if finalizada:
        manejar_menu(numero, texto_lower, rol)
        return {"status": "ok"}
    
    # Si no ha terminado la encuesta
    if texto_lower in {"brillar", "menu", "menú", "inicio"}:
        # ✅ Validación mínima solo para evitar URLs inválidas si tenant_name es None/vacío
        if not tenant_name:
            print(f"⚠️ tenant_name es None o vacío para {numero}, usando fallback")
            tenant_name = "default"  # Fallback solo si es necesario
        
        url_web = construir_url_actualizar_perfil(numero, tenant_name=tenant_name)
        mensaje_texto = (
            f"💬 🚩 No has finalizado tu encuesta. Por favor haz clic en el enlace para completar la encuesta 📋\n\n"
            f"{url_web}\n\n"
            f"Puedes hacerlo desde tu celular o computadora."
        )
        enviar_mensaje(numero, mensaje_texto)
        ultimo_paso = 1
        actualizar_flujo(numero, ultimo_paso)
        enviar_inicio_encuesta(numero)
        return {"status": "ok"}
    
    # Obtener texto original (sin normalizar) para manejar_respuesta
    texto_original = mensaje.get("text", {}).get("body", "").strip()
    manejar_respuesta(numero, texto_original)
    return {"status": "ok"}


def _process_admin_creador_message(numero: str, texto_lower: str, rol: str) -> dict:
    """
    Procesa mensajes de usuarios con rol 'admin' o 'creador'.
    
    Returns:
        Dict con status
    """
    manejar_menu(numero, texto_lower, rol)
    return {"status": "ok"}


def _process_tiktok_live_link(numero, texto, tenant_name):
    pass


def _process_single_message(mensaje: dict, tenant_name: str, datos_normalizados: dict = None):
    """
    Maneja Admins, Creadores y Fallback.
    NO maneja onboarding ni evaluación.
    """

    if not datos_normalizados:
        tipo, texto, payload = _normalizar_entrada_whatsapp(mensaje)
        numero = mensaje.get("from")
        paso = obtener_flujo(numero)
    else:
        numero = datos_normalizados["wa_id"]
        tipo = datos_normalizados["tipo"]
        texto = datos_normalizados["texto"]
        payload = datos_normalizados["payload"]
        paso = datos_normalizados["paso"]

    texto_lower = texto.lower() if texto else ""

    usuario_bd = buscar_usuario_por_telefono(numero)
    rol = obtener_rol_usuario(numero) if usuario_bd else None

    print(f"📍 [General Flow] número={numero}, rol={rol}, paso={paso}")

    # ---------------------------------------------------------
    # 1. INTERACTIVOS (NO aspirantes)
    # ---------------------------------------------------------
    if tipo == "interactive" or payload:
        return _process_interactive_message(mensaje, numero, paso)

    # ---------------------------------------------------------
    # 2. ADMIN / CREADOR
    # ---------------------------------------------------------
    if usuario_bd and rol in ("admin", "creador"):
        return _process_admin_creador_message(numero, texto_lower, rol)

    # ---------------------------------------------------------
    # 3. FALLBACK
    # ---------------------------------------------------------
    print(f"🤖 Fallback IA: {texto_lower}")
    return {"status": "ok_fallback"}


# def _process_single_message(mensaje: dict, tenant_name: str) -> dict:
#     """
#     Procesa un mensaje individual del webhook.
#
#     Returns:
#         Dict con status
#     """
#     numero = mensaje.get("from")
#     tipo = mensaje.get("type")
#     paso = obtener_flujo(numero)
#     usuario_bd = buscar_usuario_por_telefono(numero)
#     rol = obtener_rol_usuario(numero) if usuario_bd else None
#
#     # Obtener el texto antes de cualquier uso
#     texto = mensaje.get("text", {}).get("body", "").strip()
#     texto_lower = texto.lower()
#
#     # CHAT LIBRE (prioridad alta)
#     if paso == "chat_libre":
#         return _process_chat_libre_message(mensaje, numero)
#
#
#
#     # 🔹 2) NUEVO PASO: si el usuario YA es aspirante y está en
#     # 'esperando_link_tiktok_live', procesar aquí el link
#     if (
#         usuario_bd
#         and rol == "aspirante"
#         and paso == "esperando_link_tiktok_live"
#         and tipo == "text"
#     ):
#         return _process_tiktok_live_link(numero, texto, tenant_name)
#
#
#     # MENSAJES INTERACTIVOS (botones)
#     if tipo == "interactive":
#         return _process_interactive_message(mensaje, numero, paso)
#
#     print(f"📍 [DEBUG] número={numero}, paso={paso}, texto='{texto_lower}'")
#
#     # NUEVO USUARIO: FLUJO DE ONBOARDING
#     if tipo == "text" and not usuario_bd:
#         resultado = _process_new_user_onboarding(mensaje, numero, texto, texto_lower, paso, tenant_name)
#         if resultado:
#             return resultado
#
#     # ASPIRANTE EN BASE DE DATOS
#     if usuario_bd and rol == "aspirante":
#         return _process_aspirante_message(mensaje, numero, texto_lower, rol, tenant_name)
#
#     # ADMIN O CREADOR EN BD
#     if usuario_bd and rol in ("admin", "creador", "creadores"):
#         return _process_admin_creador_message(numero, texto_lower, rol)
#
#     print(f"🟣 DEBUG CHAT LIBRE - paso actual: {paso}")
#     return {"status": "ok"}

#

# @router.post("/webhook")
# async def whatsapp_webhook(request: Request):
#     """
#     Endpoint principal para recibir webhooks de WhatsApp.
#
#     Procesa diferentes tipos de eventos:
#     - account_update: Eventos de actualización de cuenta
#     - messages: Mensajes de usuarios
#     """
#     data = await request.json()
#     print("📩 Webhook recibido:", json.dumps(data, indent=2))
#
#     try:
#         # Extraer datos del webhook
#         webhook_data = _extract_webhook_data(data)
#         if not webhook_data:
#             return {"status": "ok"}
#
#         entry = webhook_data["entry"]
#         change = webhook_data["change"]
#         value = webhook_data["value"]
#         field = webhook_data["field"]
#         event = webhook_data["event"]
#
#         # CASO 1: EVENTOS DE WHATSAPP BUSINESS ACCOUNT (account_update)
#         if field == "account_update":
#             return _handle_account_update_event(entry, change, value, event)
#
#         # CASO 2: MENSAJES NORMALES CON PHONE_NUMBER_ID
#         metadata = value.get("metadata", {})
#         phone_number_id = metadata.get("phone_number_id")
#
#         # Configurar contexto del tenant
#         cuenta_info = _setup_tenant_context(phone_number_id)
#         if not cuenta_info:
#             return {"status": "ignored"}
#
#         tenant_name = cuenta_info["tenant_name"]
#         display_phone_number = metadata.get("display_phone_number", "")
#
#         # CASO 3: PROCESAR STATUSES (actualizaciones de estado de mensajes)
#         statuses = value.get("statuses", [])
#         if statuses:
#             try:
#                 for st in statuses:
#                     actualizar_mensaje_desde_status(
#                         tenant=tenant_name,
#                         phone_number_id=phone_number_id,
#                         display_phone_number=display_phone_number,
#                         status_obj=st,
#                         raw_payload=value
#                     )
#             except Exception as e:
#                 print(f"⚠️ Error al procesar statuses (continuando procesamiento): {e}")
#                 traceback.print_exc()
#
#         # Obtener mensajes
#         mensajes = value.get("messages", [])
#         if not mensajes:
#             return {"status": "ok"}
#
#         # Procesar cada mensaje
#         for mensaje in mensajes:
#             # Registrar mensaje entrante en BD
#             try:
#                 wa_id = mensaje.get("from")
#                 message_id = mensaje.get("id")
#                 tipo = mensaje.get("type")
#
#                 # Extraer contenido según el tipo de mensaje
#                 content = None
#                 if tipo == "text":
#                     content = mensaje.get("text", {}).get("body", "")
#                 elif tipo == "audio":
#                     content = f"[Audio: {mensaje.get('audio', {}).get('id', 'unknown')}]"
#                 elif tipo == "image":
#                     content = f"[Image: {mensaje.get('image', {}).get('id', 'unknown')}]"
#                 elif tipo == "video":
#                     content = f"[Video: {mensaje.get('video', {}).get('id', 'unknown')}]"
#                 elif tipo == "document":
#                     content = f"[Document: {mensaje.get('document', {}).get('filename', 'unknown')}]"
#                 elif tipo == "interactive":
#                     content = f"[Interactive: {mensaje.get('interactive', {}).get('type', 'unknown')}]"
#                 else:
#                     content = f"[{tipo}]"
#
#                 # Registrar el mensaje
#                 registrar_mensaje_recibido(
#                     tenant=tenant_name,
#                     phone_number_id=phone_number_id,
#                     display_phone_number=display_phone_number,
#                     wa_id=wa_id,
#                     message_id=message_id,
#                     content=content,
#                     raw_payload=mensaje
#                 )
#
#             except Exception as e:
#                 print(f"⚠️ Error al registrar mensaje en BD (continuando procesamiento): {e}")
#                 traceback.print_exc()
#
#             # Procesar el mensaje normalmente
#             _process_single_message(mensaje, tenant_name)
#
#     except (IndexError, KeyError, TypeError) as e:
#         print(f"❌ Error de estructura en webhook (datos inválidos): {e}")
#         traceback.print_exc()
#     except LookupError as e:
#         print(f"❌ Error de contexto en webhook: {e}")
#         traceback.print_exc()
#     except Exception as e:
#         print(f"❌ Error inesperado procesando webhook: {e}")
#         traceback.print_exc()
#
#     return {"status": "ok"}


def mensaje_inicio_encuesta() -> str:
    nombre_agencia = current_business_name.get()
    return (
        f"🔒 *Preguntas básicas*\n\n"
        f"Antes de continuar, se te harán *preguntas personales básicas* para evaluar tu perfil como aspirante a creador de contenido en *{nombre_agencia}*.\n\n"
        "Si aceptas y deseas iniciar la encuesta, haz clic en el siguiente enlace 👇"
    )

def enviar_inicio_encuesta(numero: str):
    tenant_name = current_tenant.get()  # ✅ Obtenemos el tenant actual
    if not tenant_name:
        tenant_name = "default"  # Valor por defecto si no hay tenant activo

    url_web = construir_url_actualizar_perfil(numero, tenant_name=tenant_name)

    mensaje = (
        f"{mensaje_inicio_encuesta()}\n\n"
        f"✏️ *Enlace para continuar:*\n{url_web}\n\n"
        "Puedes hacerlo desde tu celular o computadora."
    )

    enviar_mensaje(numero, mensaje)
    print(f"🔗 Enviado mensaje de inicio de encuesta a {numero}: {url_web}")


from pydantic import BaseModel

# ⚠️ DEPRECADO: Ya no se usa. Las respuestas se envían todas juntas a /consolidar
# class RespuestaInput(BaseModel):
#     numero: str
#     paso: int
#     respuesta: str

class ConsolidarInput(BaseModel):
    numero: str
    respuestas: Optional[dict] = None  # Diccionario opcional: {1: "Ricardo", 2: "5", 3: "1", ...}
                                      # Si es None, se leen de la tabla perfil_creador_flujo_temp


@router.post("/enviar_solicitud_informacion")
async def api_enviar_solicitar_informacion(data: dict):
    telefono = data.get("telefono")
    nombre = data.get("nombre", "").strip()

    if not telefono or not nombre:
        return JSONResponse({"error": "Faltan datos (telefono o nombre)"}, status_code=400)

    try:
        subdominio= current_tenant.get()
        cuenta = obtener_cuenta_por_subdominio(subdominio)
        if not cuenta:
            return JSONResponse({"error": f"No se encontraron credenciales para {subdominio}"}, status_code=404)

        token_cliente = cuenta["access_token"]
        phone_id_cliente = cuenta["phone_number_id"]


        plantilla = "solicitar_informacion"
        parametros = [nombre]

        codigo, respuesta_api = enviar_plantilla_generica(
            token=token_cliente,
            phone_number_id=phone_id_cliente,
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

    except LookupError as e:
        print(f"❌ Error de contexto al enviar solicitud de información: {e}")
        traceback.print_exc()
        return JSONResponse({"error": f"Error de configuración: {e}"}, status_code=500)
    except KeyError as e:
        print(f"❌ Error de clave faltante al enviar solicitud de información: {e}")
        traceback.print_exc()
        return JSONResponse({"error": f"Error de datos: {e}"}, status_code=500)
    except Exception as e:
        print(f"❌ Error inesperado al enviar solicitud de información: {e}")
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

@router.post("/consolidar")
def consolidar_perfil_web(data: ConsolidarInput):
    try:
        subdominio = current_tenant.get()
        cuenta = obtener_cuenta_por_subdominio(subdominio)
        if not cuenta:
            return JSONResponse({"error": f"No se encontraron credenciales para {subdominio}"}, status_code=404)

        token_cliente = cuenta["access_token"]
        phone_id_cliente = cuenta["phone_number_id"]
        business_name = cuenta.get("business_name", "la agencia")

        # ✅ Establecer valores de contexto para que las funciones puedan usarlos
        current_token.set(token_cliente)
        current_phone_id.set(phone_id_cliente)
        current_business_name.set(business_name)

        # Procesar diccionario de respuestas si viene en el request
        # Si no viene, consolidar_perfil leerá de la tabla perfil_creador_flujo_temp
        respuestas_dict = None
        if data.respuestas:
            # Procesar diccionario de respuestas directamente
            # Formato: {1: "Ricardo", 2: "5", 3: "1", ...}
            respuestas_dict = {}
            for key, valor in data.respuestas.items():
                # Convertir claves a int si vienen como string
                key_int = int(key) if isinstance(key, str) and key.isdigit() else key
                # Normalizar valores: convertir "no"/"si" a "0"/"1" para pregunta 8
                if key_int == 8:
                    valor_str = str(valor).strip().lower()
                    if valor_str in {"no", "n", "0"}:
                        respuestas_dict[key_int] = "0"
                    elif valor_str in {"si", "sí", "s", "yes", "y", "1"}:
                        respuestas_dict[key_int] = "1"
                    else:
                        respuestas_dict[key_int] = str(valor)
                else:
                    respuestas_dict[key_int] = str(valor) if valor else ""
            print(f"📋 Respuestas recibidas en request: {respuestas_dict}")
        else:
            print(f"📋 No se recibieron respuestas en request, se leerán de la tabla perfil_creador_flujo_temp")

        print(f"🔗 Iniciando consolidación de perfil en subdominio: {subdominio}")
        consolidar_perfil(data.numero, respuestas_dict=respuestas_dict, tenant_schema=subdominio)
        eliminar_flujo(data.numero, tenant_schema=subdominio)
        
        # Obtener nombre del usuario si está disponible
        try:
            usuario_bd = buscar_usuario_por_telefono(data.numero)
            nombre_usuario = usuario_bd.get("nombre") if usuario_bd else None
        except Exception as e:
            print(f"⚠️ No se pudo obtener nombre del usuario {data.numero}: {e}")
            nombre_usuario = None

        # MARCAR ENCUESTA COMPLETADA
        marcar_encuesta_completada(data.numero)

        mensaje_final = mensaje_encuesta_final(nombre=nombre_usuario)
        enviar_mensaje(data.numero, mensaje_final)
        print(f"✅ Perfil consolidado y mensaje final enviado a {data.numero}")

        return {"ok": True, "msg": "Perfil consolidado correctamente"}

    except LookupError as e:
        print(f"❌ Error de contexto al consolidar perfil: {e}")
        traceback.print_exc()
        return {"ok": False, "error": f"Error de configuración: {e}"}
    except KeyError as e:
        print(f"❌ Error de clave faltante al consolidar perfil: {e}")
        traceback.print_exc()
        return {"ok": False, "error": f"Error de datos: {e}"}
    except psycopg2.OperationalError as e:
        print(f"❌ Error de conexión a BD al consolidar perfil: {e}")
        traceback.print_exc()
        return {"ok": False, "error": "Error de conexión a base de datos"}
    except psycopg2.IntegrityError as e:
        print(f"❌ Error de integridad en BD al consolidar perfil: {e}")
        traceback.print_exc()
        return {"ok": False, "error": "Error de integridad de datos"}
    except Exception as e:
        print(f"❌ Error inesperado consolidando perfil: {e}")
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


# ============================
# REGISTRO DE MENSAJES DE STATUS
# ============================




# ============================
# REGISTRO DE MENSAJES ENTRANTES
# ============================

def registrar_mensaje_recibido(
    tenant: str,
    phone_number_id: str,
    display_phone_number: str,
    wa_id: str,
    message_id: str,
    content: Optional[str] = None,
    raw_payload: Optional[dict] = None,
) -> None:
    """
    Registra en la BD un mensaje ENTRANTE (inbound) de WhatsApp.

    - tenant: tenant/subdominio (ej: 'pruebas', 'prestige')
    - phone_number_id: phone_number_id WABA que recibió el mensaje
    - display_phone_number: número de negocio (ej: '573144667587')
    - wa_id: número de WhatsApp del usuario (ej: '573153638069')
    - message_id: id del mensaje (wamid....)
    - content: texto recibido (si aplica; para tipos no-text puedes dejar None)
    - raw_payload: JSON completo del evento (value o message específico)
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO whatsapp_messages (
                        tenant,
                        phone_number_id,
                        display_phone_number,
                        recipient,
                        message_id,
                        direction,
                        content,
                        status,
                        raw_payload,
                        last_status_at
                    )
                    VALUES (%s, %s, %s, %s, %s, 'inbound', %s, 'received', %s, NOW())
                    ON CONFLICT (message_id) DO NOTHING;
                    """,
                    (
                        tenant,
                        phone_number_id,
                        display_phone_number,
                        wa_id,                          # aquí guardamos el número del usuario
                        message_id,
                        content,
                        json.dumps(raw_payload) if raw_payload else None,
                    ),
                )
        print(f"📥 Mensaje inbound registrado en DB: {message_id}")
    except Exception as e:
        print(f"❌ Error al registrar mensaje inbound {message_id}: {e}")
        traceback.print_exc()



# ----------------------------------------------------------------------
#     NUEVA FUNCIONALIDAD  ASPIRANTE EN ESTADO ENTREVISTA
# ----------------------------------------------------------------------



# def _process_tiktok_live_link(numero: str, texto: str, tenant_name: str) -> dict:
#     """
#     Maneja el caso donde el aspirante debe enviar el link del LIVE de TikTok.
#     """
#     # 1. Validar el link
#     if not validar_link_tiktok(texto):
#         enviar_mensaje(
#             numero,
#             "❌ El formato del link no es válido.\n\n"
#             "Por favor pega el enlace completo del LIVE de TikTok, por ejemplo:\n"
#             "https://www.tiktok.com/@usuario/live"
#         )
#         # No cambiamos el paso: sigue en 'esperando_link_tiktok_live'
#         return {"status": "ok"}
#
#     # 2. Guardar/el link
#     grabar_link_tiktok(numero, texto, tenant_name)
#
#     # 3. Actualizar el flujo: ya no estamos esperando el link
#     # Puedes dejar None, o pasar a algo como 'esperando_evaluacion_live'
#     actualizar_flujo(numero, None)
#
#     # 4. Confirmar al aspirante
#     enviar_mensaje(
#         numero,
#         "✅ ¡Perfecto! Hemos recibido el link de tu LIVE de TikTok.\n"
#         "Nuestro equipo lo revisará y te compartiremos la retroalimentación pronto. 💫"
#     )
#
#     return {"status": "ok"}



import re
from urllib.parse import urlparse

TIKTOK_DOMINIOS_VALIDOS = (
    "tiktok.com",
    "www.tiktok.com",
    "vt.tiktok.com",
)

PATRON_TIKTOK_URL = re.compile(
    r"(https?://[^\s]+tiktok\.com[^\s]*)",
    re.IGNORECASE
)

def validar_link_tiktok(texto: str) -> bool:
    """
    Valida si el texto contiene un link válido de TikTok (idealmente de LIVE).
    """
    if not texto:
        return False

    # 1. Buscar un link dentro del texto
    match = PATRON_TIKTOK_URL.search(texto)
    if not match:
        return False

    url = match.group(1).strip()

    # 2. Parsear la URL
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    # 3. Verificar dominio
    dominio = parsed.netloc.lower()
    if dominio not in TIKTOK_DOMINIOS_VALIDOS:
        return False

    # 4. Revisar el path
    path = parsed.path.lower()

    # Si quieres ser estricta y aceptar SOLO lives:
    if "live" not in path:
        return False

    return True


# def grabar_link_tiktok(numero: str, link: str, tenant_name: str) -> None:
#     """
#     Guarda el link del LIVE de TikTok asociado al aspirante.
#     Ajusta según tu modelo y tus funciones de acceso a datos.
#     """
#     # 1. Buscar aspirante por teléfono
#     aspirante = buscar_usuario_por_telefono(numero)
#     if not aspirante:
#         print(f"⚠️ No se encontró aspirante con número {numero} en tenant {tenant_name}")
#         return
#
#     aspirante_id = aspirante.get("id")  # o como lo tengas
#
#     # 2. Guardar en la tabla correspondiente
#     # Ejemplos posibles (ajusta):
#     # - actualizar_link_prueba_live(aspirante_id, link)
#     # - crear_registro_prueba_live(aspirante_id, link, tenant_name)
#
#     actualizar_link_prueba_live(aspirante_id, link)

    from typing import Optional


# def actualizar_link_prueba_live(
#         creador_id: int,
#         link_tiktok: str,
#         responsable_id: Optional[int] = None
# ) -> Optional[int]:
#     """
#     Actualiza o crea un agendamiento para una prueba TikTok LIVE.
#
#     Lógica:
#     1️⃣ Busca un agendamiento relacionado con una ENTREVISTA del creador (aspirante),
#        cuya fecha_inicio esté a menos de 60 minutos de diferencia de la hora actual.
#        - Relaciones:
#          entrevistas -> entrevista_agendamiento -> agendamientos
#        - Filtro:
#          ABS(fecha_inicio - NOW_UTC) <= 60 minutos
#
#     2️⃣ Si existe:
#         - Actualiza el campo link_meet de ese agendamiento con el link de TikTok.
#         - Devuelve el id del agendamiento.
#
#     3️⃣ Si NO existe:
#         - Obtiene (o infiere) un responsable_id.
#         - Crea un nuevo agendamiento de 60 minutos a partir de ahora,
#           con el link de TikTok en link_meet.
#         - Crea/obtiene la entrevista y registra en entrevista_agendamiento.
#         - Registra al creador como participante en agendamientos_participantes.
#         - Devuelve el id del nuevo agendamiento.
#
#     Devuelve:
#         agendamiento_id (int) o None si algo falla.
#     """
#
#     try:
#         with get_connection_context() as conn:
#             with conn.cursor() as cur:
#                 # 1️⃣ Buscar agendamiento cercano (±60 minutos) vinculado a entrevista de este creador
#                 cur.execute(
#                     """
#                     SELECT a.id
#                     FROM entrevistas e
#                     JOIN entrevista_agendamiento ea ON ea.entrevista_id = e.id
#                     JOIN agendamientos a ON a.id = ea.agendamiento_id
#                     WHERE e.creador_id = %s
#                       AND ABS(
#                             EXTRACT(
#                                 EPOCH FROM (
#                                     a.fecha_inicio - (NOW() AT TIME ZONE 'UTC')
#                                 )
#                             )
#                       ) <= 60 * 60
#                     ORDER BY ABS(
#                         EXTRACT(
#                             EPOCH FROM (
#                                 a.fecha_inicio - (NOW() AT TIME ZONE 'UTC')
#                             )
#                         )
#                     )
#                     LIMIT 1
#                     """,
#                     (creador_id,)
#                 )
#                 row = cur.fetchone()
#
#                 if row:
#                     # ✅ Caso 1: ya hay una cita cercana → actualizar link_meet
#                     agendamiento_id = row[0]
#                     cur.execute(
#                         """
#                         UPDATE agendamientos
#                         SET link_meet = %s
#                         WHERE id = %s
#                         """,
#                         (link_tiktok, agendamiento_id)
#                     )
#                     print(
#                         f"✅ link_meet actualizado en agendamiento_id={agendamiento_id} para creador_id={creador_id}")
#                     return agendamiento_id
#
#                 # 2️⃣ No hay cita cercana → crear una nueva
#
#                 # 2.1 Obtener responsable_id si no viene por parámetro
#                 if responsable_id is None:
#                     cur.execute(
#                         """
#                         SELECT responsable_id
#                         FROM entrevistas
#                         WHERE creador_id = %s
#                         ORDER BY id DESC
#                         LIMIT 1
#                         """,
#                         (creador_id,)
#                     )
#                     row_resp = cur.fetchone()
#                     if row_resp:
#                         responsable_id = row_resp[0]
#
#                 if responsable_id is None:
#                     # ⚠️ Fallback de seguridad: evita reventar si no hay responsable configurado
#                     print(
#                         f"⚠️ No se encontró responsable para creador_id={creador_id}. Usando responsable_id=1 por defecto.")
#                     responsable_id = 1
#
#                 # 2.2 Crear nuevo agendamiento (60 min a partir de ahora) con el link de TikTok
#                 cur.execute(
#                     """
#                     INSERT INTO agendamientos (
#                         titulo,
#                         descripcion,
#                         fecha_inicio,
#                         fecha_fin,
#                         creador_id,
#                         responsable_id,
#                         estado,
#                         link_meet,
#                         google_event_id
#                     )
#                     VALUES (
#                         %s,
#                         %s,
#                         NOW() AT TIME ZONE 'UTC',
#                         (NOW() AT TIME ZONE 'UTC') + INTERVAL '60 minutes',
#                         %s,
#                         %s,
#                         'programado',
#                         %s,
#                         NULL
#                     )
#                     RETURNING id
#                     """,
#                     (
#                         "Prueba TikTok LIVE",
#                         "Sesión de evaluación TikTok LIVE (registrada desde WhatsApp bot).",
#                         creador_id,
#                         responsable_id,
#                         link_tiktok,
#                     )
#                 )
#
#                 agendamiento_id = cur.fetchone()[0]
#
#                 # 2.3 Obtener o crear la entrevista asociada
#                 entrevista = obtener_entrevista_id(creador_id, responsable_id)
#                 if not entrevista:
#                     raise Exception("No se pudo obtener o crear la entrevista asociada a la prueba TikTok LIVE.")
#
#                 entrevista_id = entrevista["id"]
#
#                 # 2.4 Registrar relación en entrevista_agendamiento
#                 cur.execute(
#                     """
#                     INSERT INTO entrevista_agendamiento (
#                         agendamiento_id,
#                         entrevista_id,
#                         creado_en
#                     )
#                     VALUES (%s, %s, NOW() AT TIME ZONE 'UTC')
#                     """,
#                     (agendamiento_id, entrevista_id)
#                 )
#
#                 # 2.5 Registrar participante en agendamientos_participantes
#                 cur.execute(
#                     """
#                     INSERT INTO agendamientos_participantes (agendamiento_id, creador_id)
#                     VALUES (%s, %s)
#                     """,
#                     (agendamiento_id, creador_id)
#                 )
#
#                 print(
#                     f"✅ Agendamiento de prueba TikTok LIVE creado con id={agendamiento_id} para creador_id={creador_id}")
#                 return agendamiento_id
#
#     except Exception as e:
#         print(f"❌ Error en actualizar_link_prueba_live para creador_id={creador_id}: {e}")
#         return None


from typing import Optional


def obtener_entrevista_id(creador_id: int, usuario_evalua: int) -> Optional[dict]:
    """
    Obtiene la entrevista asociada a (creador_id, usuario_evalua).
    - Si ya existe una entrevista: la devuelve como dict.
    - Si no existe: crea una nueva entrevista con resultado='sin_programar'
      y la devuelve como dict.

    Devuelve:
        dict con los campos principales de la entrevista o None si falla.
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # 1️⃣ Buscar entrevista existente para este creador + evaluador
                cur.execute(
                    """
                    SELECT
                        id,
                        creador_id,
                        usuario_evalua,
                        resultado,
                        observaciones,
                        aspecto_tecnico,
                        presencia_carisma,
                        interaccion_audiencia,
                        profesionalismo_normas,
                        evaluacion_global,
                        creado_en,
                        modificado_en
                    FROM entrevistas
                    WHERE creador_id = %s
                      AND usuario_evalua = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (creador_id, usuario_evalua)
                )
                row = cur.fetchone()

                columnas = [
                    "id",
                    "creador_id",
                    "usuario_evalua",
                    "resultado",
                    "observaciones",
                    "aspecto_tecnico",
                    "presencia_carisma",
                    "interaccion_audiencia",
                    "profesionalismo_normas",
                    "evaluacion_global",
                    "creado_en",
                    "modificado_en",
                ]

                if row:
                    # ✅ Ya existe una entrevista → devolverla como dict
                    return dict(zip(columnas, row))

                # 2️⃣ No existe entrevista → crear una nueva
                cur.execute(
                    """
                    INSERT INTO entrevistas (
                        creador_id,
                        usuario_evalua,
                        resultado,
                        creado_en,
                        modificado_en
                    )
                    VALUES (
                        %s,
                        %s,
                        'sin_programar',
                        NOW() AT TIME ZONE 'UTC',
                        NOW() AT TIME ZONE 'UTC'
                    )
                    RETURNING
                        id,
                        creador_id,
                        usuario_evalua,
                        resultado,
                        observaciones,
                        aspecto_tecnico,
                        presencia_carisma,
                        interaccion_audiencia,
                        profesionalismo_normas,
                        evaluacion_global,
                        creado_en,
                        modificado_en
                    """,
                    (creador_id, usuario_evalua)
                )

                row = cur.fetchone()
                if not row:
                    print(
                        f"⚠️ No se pudo crear entrevista para creador_id={creador_id}, usuario_evalua={usuario_evalua}")
                    return None

                return dict(zip(columnas, row))

    except Exception as e:
        print(f"❌ Error en obtener_entrevista_id para creador_id={creador_id}, usuario_evalua={usuario_evalua}: {e}")
        return None




# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
#------CREAR LINK PARA ABRIR PORTAL CITAS ASPIRANTES
# --------------------------------------------------------------------------

from typing import Optional

def enviar_citas_agendadas(numero: str) -> None:
    """
    Envía al aspirante, por WhatsApp, el listado de sus citas agendadas
    y un enlace al portal de citas con token de acceso.

    Usa:
      - buscar_usuario_por_telefono(numero)
      - get_connection_context()
      - agendamientos, agendamientos_participantes
      - crear_token_portal_citas(creador_id, responsable_id?, minutos_validez?)
      - construir_url_portal_citas(token, tenant_name)
      - current_tenant.get()
      - enviar_mensaje(numero, texto)
    """

    # 1️⃣ Verificar aspirante
    aspirante = buscar_usuario_por_telefono(numero)
    if not aspirante:
        enviar_mensaje(
            numero,
            "⚠️ No encontramos tu información como aspirante. Por favor intenta más tarde."
        )
        return

    creador_id = aspirante.get("id")
    if not creador_id:
        enviar_mensaje(
            numero,
            "⚠️ No encontramos tu perfil completo. Por favor intenta más tarde."
        )
        return

    # 2️⃣ Consultar citas agendadas del aspirante
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 
                        a.id,
                        a.titulo,
                        a.descripcion,
                        a.fecha_inicio,
                        a.fecha_fin,
                        a.estado,
                        COALESCE(a.tipo_agendamiento, 'ENTREVISTA') AS tipo_agendamiento,
                        a.link_meet
                    FROM agendamientos a
                    JOIN agendamientos_participantes ap
                      ON ap.agendamiento_id = a.id
                    WHERE ap.creador_id = %s
                    ORDER BY a.fecha_inicio ASC
                    """,
                    (creador_id,)
                )
                rows = cur.fetchall()
    except Exception as e:
        print("❌ Error cargando citas desde DB en enviar_citas_agendadas:", e)
        enviar_mensaje(
            numero,
            "⚠️ Ocurrió un error consultando tus citas. Intenta de nuevo más tarde."
        )
        return

    # 3️⃣ Si no hay citas
    if not rows:
        enviar_mensaje(
            numero,
            "📅 Por ahora no tienes citas agendadas."
        )
    else:
        # 4️⃣ Formatear y enviar detalle de citas
        mensajes: list[str] = ["📅 *Tus citas agendadas:*"]

        for r in rows:
            (
                ag_id,
                titulo,
                descripcion,
                fecha_inicio,
                fecha_fin,
                estado,
                tipo_agendamiento,
                link_meet,
            ) = r

            # Duración en minutos
            try:
                duracion_min = int((fecha_fin - fecha_inicio).total_seconds() // 60)
            except Exception:
                duracion_min = 60

            # Fecha formateada (puedes ajustar formato si quieres)
            fecha_str = fecha_inicio.strftime("%d/%m/%Y %I:%M %p")

            # Realizada o no
            realizada = "Sí" if estado == "realizada" else "No"

            mensajes.append(
                (
                    f"\n🗂️ *Cita #{ag_id}*\n"
                    f"• Fecha: {fecha_str}\n"
                    f"• Duración: {duracion_min} min\n"
                    f"• Tipo de prueba: *{tipo_agendamiento.upper()}*\n"
                    f"• Realizada: {realizada}\n"
                    f"• Enlace asignado: {link_meet or 'N/A'}"
                )
            )

        # Enviar bloques para evitar límites de tamaño en WhatsApp
        for bloque in mensajes:
            enviar_mensaje(numero, bloque)

    # 5️⃣ Generar token para portal de citas
    try:
        token = crear_token_portal_citas(creador_id=creador_id)
    except Exception as e:
        print(f"❌ Error creando token de portal de citas para creador_id={creador_id}: {e}")
        token = None

    if not token:
        enviar_mensaje(
            numero,
            "⚠️ Hubo un problema generando el acceso a tu portal de citas. "
            "Puedes volver a intentar más tarde."
        )
        return

    # 6️⃣ Obtener tenant actual (si existe)
    try:
        tenant_name: Optional[str] = current_tenant.get()
    except LookupError:
        tenant_name = None

    # 7️⃣ Construir URL del portal usando la misma lógica multitenant del frontend
    url_portal = construir_url_portal_citas(token, tenant_name=tenant_name)

    # 8️⃣ Enviar enlace del portal al aspirante
    enviar_mensaje(
        numero,
        (
            "🌐 También puedes ver y gestionar tus citas desde tu portal:\n"
            f"{url_portal}\n\n"
            "Ábrelo desde tu celular o computador para revisar tus citas, unirte a evaluaciones "
            "y enviar tu TikTok LIVE."
        )
    )


FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "https://talentum-manager.com")

def construir_url_portal_citas(token: str, tenant_name: Optional[str] = None) -> str:
    """
    Construye la URL pública del portal de citas para aspirantes.
    Ejemplo:
        https://agencia.talentum-manager.com/portal-citas?token=ABC123

    Args:
        token: token generado para el acceso del aspirante.
        tenant_name: nombre del tenant actual para construir subdominio.

    Returns:
        URL completa al portal de citas.
    """
    # Limpiar dominio base (igual que en tu función original)
    domain = (
        FRONTEND_BASE_URL
        .replace("https://", "")
        .replace("http://", "")
        .replace("www.", "")
    )

    # Construir base URL según tenant
    if tenant_name:
        base_url = f"https://{tenant_name}.{domain}"
    else:
        base_url = f"https://{domain}"

    return f"{base_url}/portal-citas?token={token}"



import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional

def crear_token_portal_citas(
    creador_id: int,
    responsable_id: Optional[int] = None,
    minutos_validez: int = 24 * 60  # por defecto, 24 horas
) -> Optional[str]:
    """
    Crea un token para que el aspirante pueda acceder al portal de citas.
    Registra el token en la tabla link_agendamiento_tokens.

    - Si responsable_id no se pasa, intenta obtenerlo de la última entrevista del creador.
    - expiracion = ahora + minutos_validez (en UTC).
    """

    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # 1️⃣ Resolver responsable_id si no viene
                if responsable_id is None:
                    cur.execute(
                        """
                        SELECT usuario_evalua
                        FROM entrevistas
                        WHERE creador_id = %s
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (creador_id,)
                    )
                    row = cur.fetchone()
                    if row and row[0] is not None:
                        responsable_id = row[0]

                # Fallback mínimo si sigue siendo None
                if responsable_id is None:
                    print(
                        f"⚠️ crear_token_portal_citas: sin responsable para creador_id={creador_id}. "
                        f"Usando responsable_id=1 por defecto."
                    )
                    responsable_id = 1

                # 2️⃣ Generar token seguro
                token = secrets.token_urlsafe(16)

                # 3️⃣ Calcular expiración (UTC)
                now_utc = datetime.now(timezone.utc)
                expiracion = now_utc + timedelta(minutes=minutos_validez)

                # 4️⃣ Insertar en link_agendamiento_tokens
                cur.execute(
                    """
                    INSERT INTO link_agendamiento_tokens (
                        token,
                        creador_id,
                        responsable_id,
                        expiracion,
                        usado,
                        creado_en
                    )
                    VALUES (%s, %s, %s, %s, false, NOW() AT TIME ZONE 'UTC')
                    """,
                    (token, creador_id, responsable_id, expiracion.replace(tzinfo=None))
                )

                print(
                    f"✅ Token portal citas creado para creador_id={creador_id}, "
                    f"responsable_id={responsable_id}, token={token}"
                )
                return token

    except Exception as e:
        print(f"❌ Error en crear_token_portal_citas para creador_id={creador_id}: {e}")
        return None


import re

def normalizar_numero(numero: str) -> str:
    """
    Normaliza un número de WhatsApp a formato estándar (E.164-like).
    Funciona para Colombia y entradas comunes de usuarios.

    Reglas:
    - Quita espacios, guiones, paréntesis.
    - Quita prefijo "+" si existe.
    - Si empieza con "57" y tiene 12 dígitos -> lo deja así.
    - Si empieza con "3" y tiene 10 dígitos -> lo convierte a "57" + número.
    - Si empieza con "0" y luego "3" (ej: 03...) -> quita el 0.
    - Si tiene 10 dígitos y empieza por 3 -> es celular CO, añade 57.
    """

    if not numero:
        return ""

    # Quitar caracteres no numéricos
    numero = re.sub(r"[^\d+]", "", numero).strip()

    # Quitar "+" si existe
    if numero.startswith("+"):
        numero = numero[1:]

    # Caso: número ya completo "57xxxxxxxxxx"
    if numero.startswith("57") and len(numero) == 12:
        return numero

    # Si empieza con 03..., quitar el cero
    if numero.startswith("03") and len(numero) == 11:
        numero = numero[1:]  # queda 3xxxxxxxxx

    # Si tiene 10 dígitos y empieza por 3 ⇒ celular colombiano
    if len(numero) == 10 and numero.startswith("3"):
        return "57" + numero

    # Si ya empieza por 57 pero la longitud no es de 12, tratamos de corregir
    if numero.startswith("57") and len(numero) > 12:
        # eliminar exceso de dígitos accidentales
        return numero[:12]

    # Si envían un número sin indicativo (ej: 3012345678)
    if len(numero) == 10:
        return "57" + numero

    # Último fallback: devolver tal cual
    return numero




# ------------------------------------------------
# ------------------------------------------------
# ------------------------------------------------
# ------------------------------------------------

ESTADOS_TERMINALES = {
    "rechazado_inicial",
    "rechazado_prueba_tiktok",
    "rechazado_entrevista",
    "invitacion_usuario_rechazada"
}







def enviar_menu_por_estado(token, wa_id, estado):
    if not estado:
        return

    enviar_menu_interactivo(
        token=token,
        recipient=wa_id,
        estado=estado
    )


import requests


# Función para enviar un mensaje con botones interactivos
def enviar_menu_interactivo(token, recipient, estado):
    """
    Genera y envía un menú interactivo a un usuario dependiendo del estado del aspirante.

    :param token: Token de autenticación de WhatsApp Cloud API.
    :param recipient: Número de teléfono del destinatario (incluyendo el código de país, ej. +57).
    :param estado: Estado del aspirante que define el menú (ej: 'post_encuesta_inicial').
    """
    url = f"https://graph.facebook.com/v19.0/{recipient}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Menús y mensajes dependiendo del estado
    menus = {
        "post_encuesta_inicial": {
            "header": "Explora la información sobre el proceso de Prestige Agency.",
            "buttons": [
                {"id": "proceso_incorporacion", "title": "Proceso de Incorporación en Prestige Agency"},
                {"id": "beneficios_agencia", "title": "Beneficios de pertenecer a nuestra Agencia"},
                {"id": "rol_creador", "title": "Rol de Creador de Contenido"}
            ]
        },
        "solicitud_agendamiento_tiktok": {
            "header": "Consulta tu Diagnóstico Inicial y coordina tu prueba TikTok LIVE.",
            "buttons": [
                {"id": "dx_inicial", "title": "Mi Dx Inicial"},
                {"id": "agenda_tiktok", "title": "Agenda Prueba tikTok LIVE"}
            ]
        },
        "solicitud_agendamiento_entrevista": {
            "header": "Consulta tu Diagnóstico Completo y coordina tu prueba de Entrevista.",
            "buttons": [
                {"id": "dx_completo", "title": "Mi Dx Completo"},
                {"id": "agenda_entrevista", "title": "Agenda Prueba Entrevista"}
            ]
        }
    }

    # Validar si el estado existe en el diccionario de menús
    if estado not in menus:
        print(f"Estado '{estado}' no tiene un menú asociado.")
        return

    # Generar el cuerpo del mensaje
    menu = menus[estado]
    body_text = menu["header"]
    buttons = [{"type": "reply", "reply": {"id": btn["id"], "title": btn["title"]}} for btn in menu["buttons"]]

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": buttons}
        }
    }

    # Realizar la solicitud HTTP POST
    response = requests.post(url, headers=headers, json=payload)

    # Manejo de respuesta
    if response.status_code == 200:
        print(f"Menú enviado exitosamente al destinatario: {recipient}")
    else:
        print(f"Error al enviar menú: {response.json()}")


def generar_y_enviar_dx_inicial(tenant, wa_id):
    pass


def generar_y_enviar_dx_completo(tenant, wa_id):
    pass


def enviar_link_agenda_tiktok(wa_id):
    pass


def enviar_link_agenda_entrevista(wa_id):
    pass


def procesar_boton_interactivo(
    tenant: str,
    wa_id: str,
    phone_number_id: str,
    button_id: str
):
    """
    Router central para botones interactivos.
    """

    # ---- MENÚ POST ENCUESTA INICIAL ----
    if button_id == "proceso_incorporacion":
        enviar_texto_simple(
            wa_id,
            "📌 El proceso incluye evaluación inicial, prueba y acompañamiento continuo."
        )

    elif button_id == "beneficios_agencia":
        enviar_texto_simple(
            wa_id,
            "✨ Beneficios: formación, acompañamiento y crecimiento en TikTok LIVE."
        )

    elif button_id == "rol_creador":
        enviar_texto_simple(
            wa_id,
            "🎥 Como creador realizarás transmisiones en TikTok LIVE siguiendo lineamientos."
        )

    # ---- DX / AGENDA ----
    elif button_id == "dx_inicial":
        generar_y_enviar_dx_inicial(tenant, wa_id)

    elif button_id == "dx_completo":
        generar_y_enviar_dx_completo(tenant, wa_id)

    elif button_id == "agenda_tiktok":
        enviar_link_agenda_tiktok(wa_id)

    elif button_id == "agenda_entrevista":
        enviar_link_agenda_entrevista(wa_id)

    else:
        enviar_texto_simple(
            wa_id,
            "⚠️ Opción no reconocida."
        )


def send_whatsapp_text(wa_id, texto):
    pass


def enviar_texto_simple(wa_id, texto):
    send_whatsapp_text(wa_id, texto)



# ---------------------------
# ----VERSION WEBHOOK ANTERIOR-------
# ---------------------------

# @router.post("/webhook")
# async def whatsapp_webhookV0(request: Request):
#     """
#     Endpoint principal para recibir webhooks de WhatsApp.
#     """
#     data = await request.json()
#     print("📩 Webhook recibido:", json.dumps(data, indent=2))
#
#     try:
#         webhook_data = _extract_webhook_data(data)
#         if not webhook_data:
#             return {"status": "ok"}
#
#         entry = webhook_data["entry"]
#         change = webhook_data["change"]
#         value = webhook_data["value"]
#         field = webhook_data["field"]
#         event = webhook_data["event"]
#
#         # ==============================
#         # CASO 1: account_update
#         # ==============================
#         if field == "account_update":
#             return _handle_account_update_event(entry, change, value, event)
#
#         # ==============================
#         # METADATA / TENANT
#         # ==============================
#         metadata = value.get("metadata", {})
#         phone_number_id = metadata.get("phone_number_id")
#
#         cuenta_info = _setup_tenant_context(phone_number_id)
#         if not cuenta_info:
#             return {"status": "ignored"}
#
#         tenant_name = cuenta_info["tenant_name"]
#         display_phone_number = metadata.get("display_phone_number", "")
#
#         # ==============================
#         # CASO 2: STATUSES
#         # ==============================
#         statuses = value.get("statuses", [])
#         if statuses:
#             for st in statuses:
#                 try:
#                     actualizar_mensaje_desde_status(
#                         tenant=tenant_name,
#                         phone_number_id=phone_number_id,
#                         display_phone_number=display_phone_number,
#                         status_obj=st,
#                         raw_payload=value
#                     )
#                 except Exception as e:
#                     print(f"⚠️ Error procesando status: {e}")
#                     traceback.print_exc()
#
#         # ==============================
#         # CASO 3: MENSAJES
#         # ==============================
#         mensajes = value.get("messages", [])
#         if not mensajes:
#             return {"status": "ok"}
#
#         for mensaje in mensajes:
#             procesado = False  # 🔑 CLAVE
#
#             wa_id = mensaje.get("from")
#             message_id = mensaje.get("id")
#             tipo = mensaje.get("type")
#
#             # ==============================
#             # REGISTRO EN BD
#             # ==============================
#             try:
#                 if tipo == "text":
#                     content = mensaje.get("text", {}).get("body", "")
#                 elif tipo == "audio":
#                     content = f"[Audio: {mensaje.get('audio', {}).get('id', 'unknown')}]"
#                 elif tipo == "image":
#                     content = f"[Image: {mensaje.get('image', {}).get('id', 'unknown')}]"
#                 elif tipo == "video":
#                     content = f"[Video: {mensaje.get('video', {}).get('id', 'unknown')}]"
#                 elif tipo == "document":
#                     content = f"[Document: {mensaje.get('document', {}).get('filename', 'unknown')}]"
#                 elif tipo == "interactive":
#                     content = "[Interactive]"
#                 else:
#                     content = f"[{tipo}]"
#
#                 registrar_mensaje_recibido(
#                     tenant=tenant_name,
#                     phone_number_id=phone_number_id,
#                     display_phone_number=display_phone_number,
#                     wa_id=wa_id,
#                     message_id=message_id,
#                     content=content,
#                     raw_payload=mensaje
#                 )
#             except Exception as e:
#                 print(f"⚠️ Error registrando mensaje: {e}")
#                 traceback.print_exc()
#
#             # ==================================================
#             # 🟢 PRIORIDAD 1: MENÚ POR ESTADO (mensaje normal)
#             # ==================================================
#             if tipo in ["text", "audio", "image", "video", "document"]:
#                 estado = obtener_estado_aspirante(tenant_name, wa_id)
#
#                 if estado:
#                     enviar_menu_por_estado(
#                         token=cuenta_info["access_token"],
#                         wa_id=wa_id,
#                         estado=estado
#                     )
#                     procesado = True
#
#             # ==================================================
#             # 🟢 PRIORIDAD 2: INTERACTIVE (botones)
#             # ==================================================
#             if tipo == "interactive":
#                 interactive = mensaje.get("interactive", {})
#                 itype = interactive.get("type")
#
#                 if itype == "button_reply":
#                     button_reply = interactive.get("button_reply", {})
#                     button_title = button_reply.get("title", "").strip().lower()
#
#                     # ------------------------------------
#                     # REENGANCHE (plantillas y cualquier botón "sí / no")
#                     # ------------------------------------
#                     if button_title in ("sí", "si", "yes", "continuar"):
#                         estado = obtener_estado_aspirante(tenant_name, wa_id)
#                         if estado:
#                             enviar_menu_por_estado(
#                                 token=cuenta_info["access_token"],
#                                 wa_id=wa_id,
#                                 estado=estado
#                             )
#                         procesado = True
#
#                     elif button_title in ("no", "ahora no"):
#                         enviar_texto_simple(
#                             wa_id,
#                             "Perfecto 👍 Si deseas continuar más adelante, escríbenos."
#                         )
#                         procesado = True
#
#                     # ------------------------------------
#                     # BOTONES NORMALES (menús interactivos)
#                     # ------------------------------------
#                     else:
#                         # Aquí sí usamos el ID porque viene de mensajes interactivos NO plantilla
#                         button_id = button_reply.get("id")
#
#                         procesar_boton_interactivo(
#                             tenant=tenant_name,
#                             wa_id=wa_id,
#                             phone_number_id=phone_number_id,
#                             button_id=button_id
#                         )
#                         procesado = True
#
#             # ==================================================
#             # 🔁 DELEGAR A CHAT CONVERSACIONAL
#             # ==================================================
#             if not procesado:
#                 _process_single_message(mensaje, tenant_name)
#
#         return {"status": "ok"}
#
#     except (IndexError, KeyError, TypeError) as e:
#         print(f"❌ Error estructura webhook: {e}")
#         traceback.print_exc()
#     except LookupError as e:
#         print(f"❌ Error contexto tenant: {e}")
#         traceback.print_exc()
#     except Exception as e:
#         print(f"❌ Error inesperado webhook: {e}")
#         traceback.print_exc()
#
#     return {"status": "ok"}




# ---------------------------------------------------------
# ---------------------------------------------------------
# ---------------------------------------------------------
# ---------NUEVO CODIGO 15 DIC 2025-------------
# ---------------------------------------------------------
# ---------------------------------------------------------
# ---------------------------------------------------------


class EstadoEvalInput(BaseModel):
    creador_id: int
    estado_evaluacion: str


@router.post("/actualizar-estado-aspiranteV1")
def actualizar_estado_aspiranteV1(data: EstadoEvalInput):
    try:
        # 1. Obtener credenciales del Tenant (Igual que en tu ejemplo)
        # Descomentarear para producción
        # subdominio = current_tenant.get()
        subdominio = 'test'
        # Asumo que esta función ya la tienes importada
        # cuenta = obtener_cuenta_por_subdominio(subdominio)

        # if not cuenta:
        #     return JSONResponse(
        #         {"error": f"No se encontraron credenciales para {subdominio}"},
        #         status_code=404
        #     )
        #
        # token_cliente = cuenta["access_token"]
        # phone_id_cliente = cuenta["phone_number_id"]
        # business_name = cuenta.get("business_name", "la agencia")


        token_cliente = 'EAAJ4EEYGr4MBP6vKlAOhKzDM0bZBINqLxM5vQZAkSbxdyTAiv0muncuvZBZBhAoDdTshsz1FmEvqdZByWfYQA8VcL3g8BIWMQZCNGBrZAWZAz6HRSzSgP2WV93B962N4e3VmLCfTtO2nsBfl53i9qVXX9ywTOdsuhYaSf3W3IVS5MdKvl53lppC2zV9qlIZCYvQacmsXZBoSgVDZAiD6zKZBOOLN3FVzE90xKAF1y07zECxiGb2bVxoi2jGjEIBA'
        phone_id_cliente ='840551055814715'
        business_name = 'Prestige Agency'


        # # 2. Contexto (Opcional, si usas logs globales)
        # current_token.set(token_cliente)
        # current_phone_id.set(phone_id_cliente)

        # 2. Obtener datos del creador
        # info_creador = obtener_info_creador(data.creador_id)
        telefono = "573153638069"  # Mock

        # 3. Guardar nuevo estado en BD
        guardar_estado_eval(data.creador_id, data.estado_evaluacion)

        # 4. Verificar ventana 24hrs (Tarea 2 - Parte A aplicada al envío)
        en_ventana = obtener_status_24hrs(telefono)

        if en_ventana:
            print("✅ En ventana: Enviando Mensaje Interactivo + Botón Opciones")
            Enviar_msg_estado(
                data.creador_id,
                data.estado_evaluacion,
                phone_id_cliente,
                token_cliente,
                telefono
            )
        else:
            print("⚠️ Fuera de ventana: Enviando Plantilla + Botón Opciones")
            enviar_plantilla_estado_evaluacion(
                data.creador_id,
                data.estado_evaluacion,
                phone_id_cliente,
                token_cliente,
                telefono
            )

        return {"message": "Estado actualizado y notificación enviada"}

    except Exception as e:
        print(f"Error: {e}")
        return {"error": str(e)}


def procesar_evento_webhook_anticuado(body, phone_id_cliente, token_cliente):
    """
    Función principal llamada desde tu ruta @router.post("/webhook")
    """
    try:
        entry = body['entry'][0]
        changes = entry['changes'][0]
        value = changes['value']

        if 'messages' not in value:
            return  # No es un mensaje (puede ser status 'read', etc)

        message = value['messages'][0]
        telefono = message['from']
        tipo_mensaje = message['type']

        # 1. Identificar al creador y su estado actual
        creador_id = obtener_creador_id_por_telefono(telefono)
        estado_actual = buscar_estado_creador(creador_id)

        print(f"📩 Msg de {telefono} | Estado DB: {estado_actual} | Tipo: {tipo_mensaje}")

        # --- CAPTURA DE BOTONES (Interactive y Template) ---
        boton_id = None

        # A. Clic en botón de Plantilla
        if tipo_mensaje == 'button':
            boton_id = message['button']['payload']

        # B. Clic en botón Interactivo (Menú normal)
        elif tipo_mensaje == 'interactive':
            tipo_interaccion = message['interactive']['type']
            if tipo_interaccion == 'button_reply':
                boton_id = message['interactive']['button_reply']['id']

        # --- LÓGICA DE BOTONES ---
        if boton_id:
            # Caso 1: El botón es "Opciones" (viene de msg inicial o plantilla)
            if boton_id == "BTN_ABRIR_MENU_OPCIONES":
                Enviar_menu_quickreply(creador_id, estado_actual, phone_id_cliente, token_cliente, telefono)

            # Caso 2: Es una opción específica (Ej: "Enviar Link")
            else:
                accion_menu_estado_evaluacion(creador_id, boton_id, phone_id_cliente, token_cliente, estado_actual,
                                              telefono)

            return  # Fin del procesamiento de botón

        # --- CAPTURA DE TEXTO (URL) ---
        if tipo_mensaje == 'text':
            texto_usuario = message['text']['body']

            # Validar si estamos esperando una URL
            if estado_actual == 'solicitud_link_enviado':

                es_valido = validar_url_link_tiktok_live(texto_usuario)

                if es_valido:
                    guardar_link_tiktok_live(creador_id, texto_usuario)
                    # Opcional: Avanzar al siguiente estado
                    guardar_estado_eval(creador_id, "revision_link_tiktok")
                    enviar_texto_simple(telefono, "✅ ¡Link recibido! Lo revisaremos pronto.", phone_id_cliente,
                                        token_cliente)
                else:
                    enviar_texto_simple(telefono,
                                        "❌ El link no parece válido. Asegúrate de que sea de TikTok y vuelve a intentarlo.",
                                        phone_id_cliente, token_cliente)

            else:
                # Si escribe texto y no esperamos nada, quizás reactivar menú
                # Opcional: Chequear 24h si quisieras responder proactivamente,
                # pero como el usuario ACABA de escribir, la ventana está abierta.
                pass

    except Exception as e:
        print(f"❌ Error webhook: {e}")


# services/aspirant_flow.py

def procesar_flujo_aspirante(tenant, phone_number_id, wa_id, tipo, texto, payload_id):
    """
    Intenta manejar el mensaje basándose en el estado del aspirante.
    Retorna True si procesó el mensaje, False si debe pasar al siguiente nivel (Chatbot).
    """
    # 1. Identificar al creador y estado
    # (Estas funciones deben venir de tu capa de base de datos)
    creador_id = obtener_creador_id_por_telefono(wa_id)
    if not creador_id:
        return False  # No es aspirante, pasar al bot normal

    estado_creador = buscar_estado_creador(creador_id)
    if not estado_creador or not estado_creador.get("codigo_estado"):
        print(f"⚠️ creador_id={creador_id} sin estado asociado")
        return False

    estado_actual = estado_creador["codigo_estado"]

    # -PENDIENTE REVISAR SI NO SE NECESITA ENVIAR MSG CHAT
    msg_chat_bot = estado_creador.get("mensaje_chatbot_simple") or "Selecciona una opción:"
    # -PENDIENTE REVISAR SI NO SE NECESITA ENVIAR MSG CHAT

    token_cliente = current_token.get()  # O pasarlo como argumento

    print(f"🕵️‍♂️ Procesando Aspirante {wa_id} | Estado: {estado_actual}")

    # ====================================================
    # CASO A: CLIC EN BOTONES (Payloads)
    # ====================================================
    if payload_id:
        # ✅ Botón continuar de plantilla
        if payload_id.strip().lower() == "continuar":
            Enviar_menu_quickreply(
                creador_id,
                estado_actual,
                msg_chat_bot,
                phone_number_id,
                token_cliente,
                wa_id
            )
            return True

        # A.1 Botón "Opciones" (Viene de Plantilla o Mensaje previo)
        if payload_id == "BTN_ABRIR_MENU_OPCIONES":
            Enviar_menu_quickreply(creador_id, estado_actual,msg_chat_bot, phone_number_id, token_cliente, wa_id)
            return True

        # A.2 Acciones específicas del menú
        # Verificamos si el payload empieza con BTN_ para saber si es nuestro
        if payload_id.startswith("MENU_"):
            accion_menu_estado_evaluacion(creador_id, payload_id, phone_number_id, token_cliente, estado_actual, wa_id)
            return True

    # ====================================================
    # CASO B: TEXTO (Validación de URL)
    # ====================================================
    if tipo == "text" and estado_actual == "solicitud_link_enviado":
        es_valido = validar_url_link_tiktok_live(texto)

        if es_valido:
            guardar_link_tiktok_live(creador_id, texto)
            # Avanzar estado
            guardar_estado_eval(creador_id, "revision_link_tiktok")
            enviar_texto_simple(wa_id, "✅ Link recibido. Lo revisaremos pronto.", phone_number_id, token_cliente)
        else:
            enviar_texto_simple(wa_id, "❌ Link no válido. Asegúrate de copiar la URL de TikTok completa.",
                                phone_number_id, token_cliente)

        return True  # Procesado, no contestar con el bot IA

    # ====================================================
    # CASO C: MENÚ POR ESTADO (Reenganche por texto)
    # ====================================================
    # Si escribe algo y no es URL, pero tiene un estado activo,
    # le recordamos sus opciones enviando el menú de nuevo.
    if tipo == "text" and estado_actual:
        # Opcional: Solo si pasaron X horas o si la intención no es clara
        Enviar_msg_estado(creador_id, estado_actual, phone_number_id, token_cliente, wa_id)
        return True

    return False  # Si no coincide nada, dejar que el bot conversacional responda


# --- SUB-FUNCIONES DE ORQUESTACIÓN ---


def _normalizar_entrada_whatsapp(mensaje):
    """
    Convierte la estructura compleja de Meta en 3 variables simples.
    Retorna: (tipo_simple, texto_visible, payload_oculto)
    """
    tipo = mensaje.get("type")
    texto = None
    payload = None

    if tipo == "text":
        texto = mensaje["text"]["body"]

    elif tipo == "button":  # Respuesta de Plantilla
        texto = mensaje["button"]["text"]
        payload = mensaje["button"]["payload"]

    elif tipo == "interactive":  # Respuesta de Menú
        interactive = mensaje["interactive"]
        itype = interactive["type"]

        if itype == "button_reply":
            texto = interactive["button_reply"]["title"]
            payload = interactive["button_reply"]["id"]
        elif itype == "list_reply":
            texto = interactive["list_reply"]["title"]
            payload = interactive["list_reply"]["id"]

    # Manejo de multimedia si es necesario
    elif tipo in ["image", "audio", "document"]:
        texto = f"[{tipo}]"

    return tipo, texto, payload


@router.post("/webhook")
async def whatsapp_webhook(request: Request):
    data = await request.json()

    try:
        webhook_data = _extract_webhook_data(data)
        if not webhook_data:
            return {"status": "ok"}

        entry = webhook_data.get("entry")
        change = webhook_data.get("change")
        value = webhook_data.get("value")
        field = webhook_data.get("field")
        event = webhook_data.get("event")

        # 1. account_update (NO usa tenant ni phone_number_id)
        if field == "account_update":
            return _handle_account_update_event(
                entry=entry,
                change=change,
                value=value,
                event=event
            )

        # 2. Contexto tenant
        metadata = value.get("metadata", {})
        phone_number_id = metadata.get("phone_number_id")

        cuenta_info = _setup_tenant_context(phone_number_id)
        if not cuenta_info:
            return {"status": "ignored"}

        tenant_name = cuenta_info["tenant_name"]
        token_access = cuenta_info["access_token"]

        # 3. Statuses (SIN return)
        statuses = value.get("statuses", [])
        if statuses:
            await _handle_statuses(
                statuses=statuses,
                tenant_name=tenant_name,
                phone_number_id=phone_number_id,
                token_access=token_access,
                raw_payload=value
            )

        # 4. Mensajes
        for mensaje in value.get("messages", []):
            await _procesar_mensaje_unico(
                mensaje,
                tenant_name,
                phone_number_id,
                token_access
            )

    except Exception as e:
        print("❌ Error webhook:", e)
        traceback.print_exc()

    return {"status": "ok"}


async def _procesar_mensaje_unico(mensaje, tenant_name, phone_number_id, token):
    """
    Orquestador principal:
    1. Normaliza
    2. Registra mensaje
    3. Onboarding (nuevo usuario)
    4. Flujo Aspirante
    5. Flujo General
    """

    wa_id = mensaje.get("from")

    # ---------------------------------------------------------
    # A. NORMALIZACIÓN
    # ---------------------------------------------------------
    tipo, texto, payload_id = _normalizar_entrada_whatsapp(mensaje)
    texto_lower = (texto or "").lower()

    # ---------------------------------------------------------
    # B. LOG EN BD
    # ---------------------------------------------------------
    try:
        registrar_mensaje_recibido(
            tenant=tenant_name,
            phone_number_id=phone_number_id,
            display_phone_number=wa_id,
            wa_id=wa_id,
            message_id=mensaje.get("id"),
            content=f"[{tipo}] {texto or ''} {payload_id or ''}",
            raw_payload=mensaje
        )
    except Exception as e:
        print(f"⚠️ Log Error (No crítico): {e}")

    # ---------------------------------------------------------
    # C. ONBOARDING (PRIMERO)
    # ---------------------------------------------------------
    paso = obtener_flujo(wa_id)
    usuario_bd = buscar_usuario_por_telefono(wa_id)

    if not usuario_bd:
        resultado = _process_new_user_onboarding(
            mensaje=mensaje,
            numero=wa_id,
            texto=texto,
            texto_lower=texto_lower,
            payload=payload_id,
            paso=paso,
            tenant_name=tenant_name,
            phone_id=phone_number_id,
            token=token
        )

        if resultado:
            return

    # ---------------------------------------------------------
    # D. FLUJO ASPIRANTE
    # ---------------------------------------------------------
    try:
        procesado_aspirante = procesar_flujo_aspirante(
            tenant=tenant_name,
            phone_number_id=phone_number_id,
            wa_id=wa_id,
            tipo=tipo,
            texto=texto,
            payload_id=payload_id
        )

        if procesado_aspirante:
            return

    except Exception as e:
        print(f"❌ Error flujo aspirante: {e}")

    # ---------------------------------------------------------
    # E. FLUJO GENERAL
    # ---------------------------------------------------------
    _process_single_message(mensaje, tenant_name)


async def _procesar_mensaje_unicoV1(mensaje, tenant_name, phone_number_id, token):
    wa_id = mensaje.get("from")

    # A. Normalización
    tipo, texto, payload_id = _normalizar_entrada_whatsapp(mensaje)
    texto_lower = texto.lower() if texto else ""

    # B. Logging
    try:
        registrar_mensaje_recibido(
            tenant=tenant_name,
            phone_number_id=phone_number_id,
            display_phone_number=wa_id,
            wa_id=wa_id,
            message_id=mensaje.get("id"),
            content=f"[{tipo}] {texto or ''} {payload_id or ''}",
            raw_payload=mensaje
        )
    except Exception as e:
        print(f"⚠️ Log Error (No crítico): {e}")

    # ---------------------------------------------------------
    # 🆕 NIVEL 1: ONBOARDING (PRIORIDAD ABSOLUTA)
    # ---------------------------------------------------------
    usuario_bd = buscar_usuario_por_telefono(wa_id)
    paso = obtener_flujo(wa_id)

    if not usuario_bd and tipo == "text":
        resultado = _process_new_user_onboarding(
            mensaje=mensaje,
            numero=wa_id,
            texto=texto,
            texto_lower=texto_lower,
            paso=paso,
            tenant_name=tenant_name,
            payload=payload_id,
            phone_id=phone_number_id,
            token=token
        )
        if resultado:
            return  # ⛔ nadie más responde

    # ---------------------------------------------------------
    # NIVEL 2: FLUJO ASPIRANTE
    # ---------------------------------------------------------
    try:
        procesado_aspirante = procesar_flujo_aspirante(
            tenant=tenant_name,
            phone_number_id=phone_number_id,
            wa_id=wa_id,
            tipo=tipo,
            texto=texto,
            payload_id=payload_id,
            token_cliente=token
        )

        if procesado_aspirante:
            return

    except Exception as e:
        print(f"❌ Error en flujo aspirante: {e}")

    # ---------------------------------------------------------
    # NIVEL 3: FLUJO GENERAL (Admin / Bot)
    # ---------------------------------------------------------
    datos_normalizados = {
        "wa_id": wa_id,
        "tipo": tipo,
        "texto": texto,
        "payload": payload_id,
        "paso": paso
    }

    _process_single_message(mensaje, tenant_name, datos_normalizados)



def _normalizar_entrada_whatsapp(mensaje):
    """
    Convierte la estructura compleja de Meta en 3 variables simples.
    Retorna: (tipo_simple, texto_visible, payload_oculto)
    """
    tipo = mensaje.get("type")
    texto = None
    payload = None

    if tipo == "text":
        texto = mensaje["text"]["body"]

    elif tipo == "button":  # Respuesta de Plantilla
        texto = mensaje["button"]["text"]
        payload = mensaje["button"]["payload"]

    elif tipo == "interactive":  # Respuesta de Menú
        interactive = mensaje["interactive"]
        itype = interactive["type"]

        if itype == "button_reply":
            texto = interactive["button_reply"]["title"]
            payload = interactive["button_reply"]["id"]
        elif itype == "list_reply":
            texto = interactive["list_reply"]["title"]
            payload = interactive["list_reply"]["id"]

    # Manejo de multimedia si es necesario
    elif tipo in ["image", "audio", "document"]:
        texto = f"[{tipo}]"

    return tipo, texto, payload


import traceback

async def _procesar_error_envio(status_obj, tenant, phone_id, token):
    """
    Analiza por qué falló el mensaje y toma acciones correctivas.
    """
    errors = status_obj.get("errors", [])
    recipient_id = status_obj.get("recipient_id")  # El teléfono del usuario

    for error in errors:
        code = error.get("code")
        message = error.get("message")

        print(f"❌ Error de entrega a {recipient_id}: Código {code} - {message}")

        # ---------------------------------------------------------
        # ERROR 131047: Re-engagement Message (Ventana 24h cerrada)
        # ---------------------------------------------------------
        if code == 131047:
            print(f"🔄 INTENTO DE RECUPERACIÓN: Enviando plantilla a {recipient_id}...")

            # 1. Identificar al aspirante
            # Nota: Usamos recipient_id como wa_id (teléfono)
            creador_id = obtener_creador_id_por_telefono(recipient_id)

            if creador_id:
                # 2. Buscar en qué estado se quedó para enviar la plantilla correcta
                estado_actual = buscar_estado_creador(creador_id)

                if estado_actual:
                    # 3. Enviar la PLANTILLA correspondiente
                    # Esta función ya la definimos en "Tarea 3" y sabe qué template usar
                    enviar_plantilla_estado_evaluacion(
                        creador_id=creador_id,
                        estado_evaluacion=estado_actual,
                        phone_id=phone_id,
                        token=token,
                        telefono=recipient_id
                    )
                    print(f"✅ Plantilla de recuperación enviada a {recipient_id}")
                else:
                    print(f"⚠️ No se encontró estado para creador {creador_id}, no se pudo enviar plantilla.")
            else:
                print(f"⚠️ El destinatario {recipient_id} no es un aspirante registrado.")

        # ---------------------------------------------------------
        # OTROS ERRORES (Opcional)
        # ---------------------------------------------------------
        elif code == 131026:
            print("⚠️ Mensaje no entregado: Usuario bloqueó al bot o no tiene WhatsApp.")
            # Aquí podrías marcar al usuario como 'inactivo' en tu BD


# def _process_new_user_onboarding(mensaje: dict, numero: str, texto: str, texto_lower: str, paso: Optional[str | int], tenant_name: str) -> Optional[dict]:
#     """
#     Procesa el flujo de onboarding para nuevos usuarios.
#
#     Returns:
#         Dict con status si se procesó, None si no aplica
#     """
#     tipo = mensaje.get("type")
#     if tipo != "text":
#         return None
#
#     # Si el paso guardado no tiene sentido, reiniciamos el flujo
#     if paso not in [None, "esperando_usuario_tiktok", "confirmando_nombre", "esperando_inicio_encuesta"]:
#         print(f"⚠️ Reiniciando flujo para {numero}, paso anterior: {paso}")
#         eliminar_flujo(numero)
#         paso = None
#
#     # Inicio del flujo
#     if paso is None:
#         enviar_mensaje(numero, Mensaje_bienvenida)
#         actualizar_flujo(numero, "esperando_usuario_tiktok")
#         return {"status": "ok"}
#
#     # Se espera usuario de TikTok
#     if paso == "esperando_usuario_tiktok":
#         usuario_tiktok = texto.strip()
#         aspirante = buscar_aspirante_por_usuario_tiktok(usuario_tiktok)
#         if aspirante:
#             nombre = aspirante.get("nickname") or aspirante.get("nombre_real") or "(sin nombre)"
#             enviar_mensaje(numero, mensaje_confirmar_nombre(nombre))
#             actualizar_flujo(numero, "confirmando_nombre")
#             # ✅ Guardar en Redis (con fallback a memoria si falla)
#             try:
#                 redis_set_temp(numero, aspirante, ttl=900)  # 15 minutos
#             except Exception as e:
#                 print(f"⚠️ Redis falló, usando memoria como fallback para {numero}: {e}")
#                 usuarios_temp[numero] = aspirante
#         else:
#             enviar_mensaje(numero, "❌ No encontramos ese usuario de TikTok. ¿Podrías verificarlo?")
#         return {"status": "ok"}
#
#     # Confirmar nickname y actualizar teléfono
#     if paso == "confirmando_nombre":
#         if texto_lower in ["si", "sí", "s"]:
#             # ✅ Leer de Redis (con fallback a memoria si falla)
#             aspirante = redis_get_temp(numero)
#             if not aspirante:
#                 # Fallback a memoria si Redis no tiene el dato
#                 aspirante = usuarios_temp.get(numero)
#                 if aspirante:
#                     print(f"⚠️ Datos encontrados en memoria (fallback) para {numero}")
#
#             if aspirante:
#                 actualizar_telefono_aspirante(aspirante["id"], numero)
#                 # ✅ Limpiar de Redis y memoria después de usar
#                 try:
#                     redis_delete_temp(numero)
#                 except Exception as e:
#                     print(f"⚠️ Error eliminando de Redis para {numero}: {e}")
#                 usuarios_temp.pop(numero, None)  # Limpiar también de memoria
#
#             enviar_inicio_encuesta(numero)
#             actualizar_flujo(numero, "esperando_inicio_encuesta")
#         elif texto_lower in ["no", "n"]:
#             enviar_mensaje(numero, "❌ Por favor verifica tu nombre o usuario de TikTok.")
#             # Limpiar datos temporales si el usuario rechaza
#             try:
#                 redis_delete_temp(numero)
#             except Exception:
#                 pass
#             usuarios_temp.pop(numero, None)
#         else:
#             enviar_mensaje(numero, "⚠️ Por favor responde solo *sí* o *no* para continuar.")
#         return {"status": "ok"}
#
#     # Si el usuario está esperando iniciar la encuesta pero escribe texto
#     if paso == "esperando_inicio_encuesta":
#         if texto_lower.strip() != "":
#             # ✅ Usar el parámetro tenant_name (ya disponible desde _process_single_message)
#             # Fallback al contexto si el parámetro no está disponible por alguna razón
#             tenant_actual = tenant_name
#             if not tenant_actual:
#                 try:
#                     tenant_actual = current_tenant.get()
#                 except LookupError:
#                     tenant_actual = "default"  # Fallback si no hay contexto
#
#             url_web = construir_url_actualizar_perfil(numero, tenant_name=tenant_actual)
#             mensaje = (
#                 f"💬 Haz clic en el enlace para comenzar la encuesta 📋\n\n"
#                 f"{url_web}\n\n"
#                 f"Puedes hacerlo desde tu celular o computadora."
#             )
#             enviar_mensaje(numero, mensaje)
#         return {"status": "ok"}
#
#     return None

# async def _procesar_mensaje_unico(mensaje, tenant_name, phone_number_id, token):
#     wa_id = mensaje.get("from")
#
#     # A. Normalizar datos (Abstraer si es template button o interactive button)
#     tipo, texto, payload_id = _normalizar_entrada_whatsapp(mensaje)
#
#     # B. Registro en Base de Datos (Logging)
#     try:
#         registrar_mensaje_recibido(
#             tenant=tenant_name,
#             phone_number_id=phone_number_id,
#             display_phone_number=mensaje.get("from"),  # Ajustar según metadata
#             wa_id=wa_id,
#             message_id=mensaje.get("id"),
#             content=f"[{tipo}] {texto or ''} {payload_id or ''}",
#             raw_payload=mensaje
#         )
#     except Exception as e:
#         print(f"⚠️ Log Error: {e}")
#
#     # C. CADENA DE RESPONSABILIDAD (La lógica de prioridades)
#
#     # NIVEL 1: Flujo de Aspirantes (Tu requerimiento específico)
#     #
#     procesado_aspirante = procesar_flujo_aspirante(
#         tenant=tenant_name,
#         phone_number_id=phone_number_id,
#         wa_id=wa_id,
#         tipo=tipo,
#         texto=texto,
#         payload_id=payload_id
#     )
#
#     if procesado_aspirante:
#         return  # ✅ Ya se manejó, detenemos el flujo aquí.
#
#     # NIVEL 2: Reenganche Genérico (Si/No) - Opcional, legacy code
#     if payload_id in ["BTN_SI", "BTN_NO"] or texto.lower() in ["si", "no"]:
#         # Tu lógica antigua de sí/no genérica
#         pass
#
#         # NIVEL 3: Chat Conversacional (Fallback AI)
#     # Si no es aspirante o no está en un estado que bloquee el chat
#     print(f"🤖 Delegando a ChatBot: {wa_id}")
#     _process_single_message(mensaje, tenant_name)


# Importar tus funciones de lógica de negocio (ajusta los imports según tu estructura)
# from services.aspirant_service import buscar_estado_creador, obtener_creador_id_por_telefono, enviar_plantilla_estado_evaluacion
# from services.db_service import actualizar_mensaje_desde_status

# async def _handle_statuses(statuses, tenant_name, phone_number_id, token_access, raw_payload):
#     """
#     Procesa la lista de estados (sent, delivered, read, failed).
#     Detecta errores de ventana de 24h y dispara la recuperación con plantillas.
#     """
#     for status_obj in statuses:
#         try:
#             # 1. ACTUALIZAR BD (Siempre se hace, sea éxito o error)
#             # Esta función actualiza el estado del mensaje en tu tabla de historial
#             actualizar_mensaje_desde_status(
#                 tenant=tenant_name,
#                 phone_number_id=phone_number_id,
#                 display_phone_number=status_obj.get("recipient_id"),
#                 status_obj=status_obj,
#                 raw_payload=raw_payload
#             )
#
#             # 2. DETECCIÓN DE ERRORES CRÍTICOS
#             if status_obj.get("status") == "failed":
#                 await _procesar_error_envio(status_obj, tenant_name, phone_number_id, token_access)
#
#         except Exception as e:
#             print(f"⚠️ Error procesando status individual: {e}")
#             traceback.print_exc()



# async def _procesar_mensaje_unico(mensaje, tenant_name, phone_number_id, token_access):
#     wa_id = mensaje.get("from")
#
#     # 1. NORMALIZAR (Hacerlo una sola vez)
#     tipo, texto, payload = _normalizar_entrada_whatsapp(mensaje)
#
#     # 2. LOGGING / BD (Tu lógica de registro existente)
#     # registrar_mensaje_recibido(...)
#
#     # 3. 🟢 PRIORIDAD 1: Chat Libre (Intervención Humana)
#     # Consultamos flujo antes de nada. Si está hablando con humano, nadie interrumpe.
#     paso_actual = obtener_flujo(wa_id)
#     if paso_actual == "chat_libre":
#         return _process_chat_libre_message(mensaje, wa_id)
#
#     # 4. 🟢 PRIORIDAD 2: Flujo de Aspirantes (Evaluación / Links / Estados)
#     # Llamamos a tu NUEVA lógica.
#     procesado_aspirante = procesar_flujo_aspirante(
#         tenant=tenant_name,
#         phone_number_id=phone_number_id,
#         wa_id=wa_id,
#         tipo=tipo,
#         texto=texto,
#         payload_id=payload  # Pasamos el payload ya limpio
#     )
#
#     if procesado_aspirante:
#         # ✅ Si la lógica de aspirantes manejó el mensaje (ej: guardó el link de tiktok),
#         # TERMINAMOS AQUÍ. No llamamos a _process_single_message.
#         return {"status": "handled_by_aspirant_flow"}
#
#     # 5. 🟢 PRIORIDAD 3: Flujo General (Onboarding / Admin / Bot Conversacional)
#     # Si llegamos aquí, es porque NO es un aspirante en evaluación activa
#     # o escribió algo que el flujo de evaluación no entendió.
#     return _process_single_message(
#         mensaje=mensaje,
#         tenant_name=tenant_name,
#         # OPTIMIZACIÓN: Pasamos los datos ya procesados para no buscarlos de nuevo
#         datos_normalizados={"wa_id": wa_id, "tipo": tipo, "texto": texto, "payload": payload, "paso": paso_actual}
#     )


# async def _procesar_mensaje_unico(mensaje, tenant_name, phone_number_id, token):
#     wa_id = mensaje.get("from")
#
#     # A. Normalizar datos (Abstraer si es template button o interactive button)
#     tipo, texto, payload_id = _normalizar_entrada_whatsapp(mensaje)
#
#     # B. Registro en Base de Datos (Logging)
#     try:
#         registrar_mensaje_recibido(
#             tenant=tenant_name,
#             phone_number_id=phone_number_id,
#             display_phone_number=mensaje.get("from"),  # Ajustar según metadata
#             wa_id=wa_id,
#             message_id=mensaje.get("id"),
#             content=f"[{tipo}] {texto or ''} {payload_id or ''}",
#             raw_payload=mensaje
#         )
#     except Exception as e:
#         print(f"⚠️ Log Error: {e}")
#
#     # C. CADENA DE RESPONSABILIDAD (La lógica de prioridades)
#
#     # NIVEL 1: Flujo de Aspirantes (Tu requerimiento específico)
#     #
#     procesado_aspirante = procesar_flujo_aspirante(
#         tenant=tenant_name,
#         phone_number_id=phone_number_id,
#         wa_id=wa_id,
#         tipo=tipo,
#         texto=texto,
#         payload_id=payload_id
#     )
#
#     if procesado_aspirante:
#         return  # ✅ Ya se manejó, detenemos el flujo aquí.
#
#     # NIVEL 2: Reenganche Genérico (Si/No) - Opcional, legacy code
#     if payload_id in ["BTN_SI", "BTN_NO"] or texto.lower() in ["si", "no"]:
#         # Tu lógica antigua de sí/no genérica
#         pass
#
#         # NIVEL 3: Chat Conversacional (Fallback AI)
#     # Si no es aspirante o no está en un estado que bloquee el chat
#     print(f"🤖 Delegando a ChatBot: {wa_id}")
#     _process_single_message(mensaje, tenant_name)



# @router.post("/webhook")
# async def whatsapp_webhookV2(request: Request):
#     data = await request.json()
#
#     # 1. Extracción Inicial
#     webhook_data = _extract_webhook_data(data)
#     if not webhook_data:
#         return {"status": "ok"}
#
#     value = webhook_data["value"]
#
#     # 2. Contexto del Tenant (Grupo Administrativo)
#     metadata = value.get("metadata", {})
#     phone_number_id = metadata.get("phone_number_id")
#     cuenta_info = _setup_tenant_context(phone_number_id)
#
#     if not cuenta_info:
#         return {"status": "ignored"}
#
#     tenant_name = cuenta_info["tenant_name"]
#     token_access = cuenta_info["access_token"]
#
#     # 3. Manejo de Status (Sent/Delivered/Read)
#     statuses = value.get("statuses", [])
#     if statuses:
#         # AHORA PASAMOS EL TOKEN TAMBIÉN
#         await _handle_statuses(
#             statuses=statuses,
#             tenant_name=tenant_name,
#             phone_number_id=phone_number_id,
#             token_access=cuenta_info["access_token"],  # <--- IMPORTANTE AGREGAR ESTO
#             raw_payload=value
#         )
#         return {"status": "ok"}
#
#     # 4. Manejo de Mensajes (Core Logic)
#     if "messages" in value:
#         for mensaje in value["messages"]:
#             await _procesar_mensaje_unico(
#                 mensaje,
#                 tenant_name,
#                 phone_number_id,
#                 token_access
#             )
#
#     return {"status": "ok"}


# --- SUB-FUNCIONES DE ORQUESTACIÓN ---


# def _process_new_user_onboarding2(
#         mensaje: dict,
#         numero: str,
#         texto: str,
#         texto_lower: str,
#         paso: Optional[str | int],
#         tenant_name: str,
#         payload: str = None,  # <--- Nuevo argumento (o extráelo dentro)
#         phone_id: str = None,  # <--- Necesarios para enviar botones
#         token: str = None  # <--- Necesarios para enviar botones
# ) -> Optional[dict]:
#     """
#     Procesa el flujo de onboarding para nuevos usuarios con botones interactivos.
#     """
#     tipo = mensaje.get("type")
#
#     # 1. VALIDACIÓN DE TIPO (Ahora permitimos texto E interactive)
#     if tipo not in ["text", "interactive"]:
#         return None
#
#     # Si el payload no vino como argumento, intentamos extraerlo aquí
#     if not payload and tipo == "interactive":
#         try:
#             payload = mensaje.get("interactive", {}).get("button_reply", {}).get("id")
#         except:
#             pass
#
#     # Reinicio de flujo si el estado es inválido
#     if paso not in [None, "esperando_usuario_tiktok", "confirmando_nombre", "esperando_inicio_encuesta"]:
#         print(f"⚠️ Reiniciando flujo para {numero}, paso anterior: {paso}")
#         eliminar_flujo(numero)
#         paso = None
#
#     # -----------------------------------------------------
#     # PASO 0: INICIO
#     # -----------------------------------------------------
#     if paso is None:
#         enviar_mensaje(numero, "¡Hola! 👋 Bienvenido.\nPara comenzar, por favor escribe tu *usuario de TikTok* (sin @).")
#         actualizar_flujo(numero, "esperando_usuario_tiktok")
#         return {"status": "ok"}
#
#     # -----------------------------------------------------
#     # PASO 1: ESPERANDO USUARIO TIKTOK
#     # -----------------------------------------------------
#     if paso == "esperando_usuario_tiktok":
#         # Aquí esperamos texto, no botones
#         if tipo != "text":
#             enviar_mensaje(numero, "Por favor escribe tu usuario de TikTok.")
#             return {"status": "ok"}
#
#         usuario_tiktok = texto.strip()
#         aspirante = buscar_aspirante_por_usuario_tiktok(usuario_tiktok)
#
#         if aspirante:
#             nombre = aspirante.get("nickname") or aspirante.get("nombre_real") or "(sin nombre)"
#
#             # --- CAMBIO CLAVE: Usamos botones en vez de texto plano ---
#             # Si tenemos credenciales enviamos botones, si no, texto plano (fallback)
#             if phone_id and token:
#                 enviar_confirmacion_interactiva(numero, nombre, phone_id, token)
#             else:
#                 enviar_mensaje(numero, f"Encontramos el usuario: *{nombre}*. ¿Eres tú? (Responde SÍ o NO)")
#
#             actualizar_flujo(numero, "confirmando_nombre")
#
#             # Guardar en Redis/Memoria
#             try:
#                 redis_set_temp(numero, aspirante, ttl=900)
#             except Exception as e:
#                 print(f"⚠️ Redis falló, usando memoria: {e}")
#                 usuarios_temp[numero] = aspirante
#         else:
#             enviar_mensaje(numero,
#                            "❌ No encontramos ese usuario en nuestra base de datos. Verifica y escríbelo nuevamente.")
#
#         return {"status": "ok"}
#
#     # -----------------------------------------------------
#     # PASO 2: CONFIRMANDO NOMBRE (Botones o Texto)
#     # -----------------------------------------------------
#     if paso == "confirmando_nombre":
#
#         # A. EL USUARIO DIJO QUE SÍ (Botón o Texto)
#         es_si_boton = (payload == "BTN_CONFIRM_YES")
#         es_si_texto = (tipo == "text" and texto_lower in ["si", "sí", "s", "y", "yes"])
#
#         if es_si_boton or es_si_texto:
#             # Recuperar datos
#             aspirante = redis_get_temp(numero)
#             if not aspirante:
#                 aspirante = usuarios_temp.get(numero)  # Fallback memoria
#
#             if aspirante:
#                 actualizar_telefono_aspirante(aspirante["id"], numero)
#
#                 # Limpiar temporales
#                 try:
#                     redis_delete_temp(numero)
#                 except:
#                     pass
#                 usuarios_temp.pop(numero, None)
#
#                 # Avanzar a encuesta
#                 enviar_inicio_encuesta(numero)  # Asumo que esta función envía el texto de bienvenida a la encuesta
#                 actualizar_flujo(numero, "esperando_inicio_encuesta")
#             else:
#                 # Caso borde: Se expiró el caché
#                 enviar_mensaje(numero, "⏳ La sesión expiró. Por favor escribe tu usuario de TikTok nuevamente.")
#                 actualizar_flujo(numero, "esperando_usuario_tiktok")
#
#         # B. EL USUARIO DIJO QUE NO (Botón o Texto)
#         elif payload == "BTN_CONFIRM_NO" or (tipo == "text" and texto_lower in ["no", "n"]):
#             enviar_mensaje(numero, "Entendido. Por favor escribe nuevamente tu usuario de TikTok correcto:")
#
#             # Limpiar datos erróneos
#             try:
#                 redis_delete_temp(numero)
#             except:
#                 pass
#             usuarios_temp.pop(numero, None)
#
#             # 🔄 REGRESAR AL PASO ANTERIOR
#             actualizar_flujo(numero, "esperando_usuario_tiktok")
#
#         # C. ESCRIBIÓ OTRA COSA
#         else:
#             enviar_mensaje(numero, "⚠️ No te entendí. Por favor selecciona una de las opciones.")
#             # Opcional: Reenviar los botones aquí si quieres ser insistente
#
#         return {"status": "ok"}
#
#     # -----------------------------------------------------
#     # PASO 3: ESPERANDO LINK (Encuesta)
#     # -----------------------------------------------------
#     if paso == "esperando_inicio_encuesta":
#         if texto_lower.strip() != "":
#             # Tu lógica de enviar link nuevamente
#             tenant_actual = tenant_name or current_tenant.get() or "default"
#             url_web = construir_url_actualizar_perfil(numero, tenant_name=tenant_actual)
#
#             mensaje = (
#                 f"💬 Haz clic en el enlace para comenzar la encuesta 📋\n\n"
#                 f"{url_web}\n\n"
#                 f"Puedes hacerlo desde tu celular o computadora."
#             )
#             enviar_mensaje(numero, mensaje)
#         return {"status": "ok"}
#
#     return None


# def _process_new_user_onboarding2(
#     mensaje: dict,
#     numero: str,
#     tipo: str,
#     texto: str,
#     texto_lower: str,
#     payload: str,
#     paso: str | None,
#     tenant_name: str,
#     phone_id: str,
#     token: str
# ) -> dict | None:
#     """
#     Flujo de onboarding con confirmación por botones.
#     """
#
#     # -----------------------------------------------------
#     # VALIDACIÓN DE TIPO
#     # -----------------------------------------------------
#     if tipo not in ("text", "interactive"):
#         return None
#
#     # -----------------------------------------------------
#     # VALIDAR / REINICIAR FLUJO
#     # -----------------------------------------------------
#     pasos_validos = {
#         None,
#         "esperando_usuario_tiktok",
#         "confirmando_nombre",
#         "encuesta_enviada"
#     }
#
#     if paso not in pasos_validos:
#         eliminar_flujo(numero)
#         paso = None
#
#     # -----------------------------------------------------
#     # PASO 0 - BIENVENIDA
#     # -----------------------------------------------------
#     if paso is None:
#         enviar_mensaje(
#             numero,
#             "¡Hola! 👋 Bienvenido.\n\n"
#             "Para comenzar, por favor escribe tu *usuario de TikTok* (sin @)."
#         )
#         actualizar_flujo(numero, "esperando_usuario_tiktok")
#         return {"status": "ok"}
#
#     # -----------------------------------------------------
#     # PASO 1 - ESPERANDO USUARIO TIKTOK
#     # -----------------------------------------------------
#     if paso == "esperando_usuario_tiktok":
#
#         if tipo != "text":
#             enviar_mensaje(numero, "✍️ Por favor escribe tu usuario de TikTok.")
#             return {"status": "ok"}
#
#         usuario_tiktok = texto.strip().lstrip("@")
#         aspirante = buscar_aspirante_por_usuario_tiktok(usuario_tiktok)
#
#         if not aspirante:
#             enviar_mensaje(
#                 numero,
#                 "❌ No encontramos ese usuario.\n"
#                 "Verifica e inténtalo nuevamente."
#             )
#             return {"status": "ok"}
#
#         nombre = aspirante.get("nickname") or aspirante.get("nombre_real") or "(sin nombre)"
#
#         # Guardar temporal
#         redis_set_temp(numero, aspirante, ttl=900)
#
#         # Enviar confirmación
#         enviar_confirmacion_interactiva(
#             numero=numero,
#             nickname=nombre,  # ✅ CORRECTO
#             phone_id=phone_id,
#             token=token
#         )
#
#         actualizar_flujo(numero, "confirmando_nombre")
#         return {"status": "ok"}
#
#     # -----------------------------------------------------
#     # PASO 2 - CONFIRMACIÓN
#     # -----------------------------------------------------
#     if paso == "confirmando_nombre":
#
#         es_si = payload == "BTN_CONFIRM_YES" or texto_lower in ("si", "sí", "s", "yes")
#         es_no = payload == "BTN_CONFIRM_NO" or texto_lower in ("no", "n")
#
#         if es_si:
#             aspirante = redis_get_temp(numero)
#
#             if not aspirante:
#                 enviar_mensaje(
#                     numero,
#                     "⏳ La sesión expiró. Escribe tu usuario de TikTok nuevamente."
#                 )
#                 actualizar_flujo(numero, "esperando_usuario_tiktok")
#                 return {"status": "ok"}
#
#             actualizar_telefono_aspirante(aspirante["id"], numero)
#
#             redis_delete_temp(numero)
#
#             url_encuesta = construir_url_actualizar_perfil(
#                 numero,
#                 tenant_name=tenant_name
#             )
#
#             enviar_mensaje(
#                 numero,
#                 f"📋 ¡Perfecto!\n\n"
#                 f"Para continuar, completa la siguiente encuesta:\n\n{url_encuesta}"
#             )
#
#             actualizar_flujo(numero, "encuesta_enviada")
#             return {"status": "ok"}
#
#         if es_no:
#             redis_delete_temp(numero)
#             enviar_mensaje(
#                 numero,
#                 "👌 Entendido.\n"
#                 "Escribe nuevamente tu usuario de TikTok correcto."
#             )
#             actualizar_flujo(numero, "esperando_usuario_tiktok")
#             return {"status": "ok"}
#
#         enviar_mensaje(
#             numero,
#             "⚠️ Por favor selecciona *Sí* o *No* usando los botones."
#         )
#         return {"status": "ok"}
#
#     # -----------------------------------------------------
#     # PASO FINAL - ENCUESTA YA ENVIADA
#     # -----------------------------------------------------
#     if paso == "encuesta_enviada":
#         enviar_mensaje(
#             numero,
#             "📋 Ya te enviamos el enlace de la encuesta.\n"
#             "Si necesitas ayuda, escríbenos."
#         )
#         return {"status": "ok"}
#
#     return None


# def obtener_estado_aspirante(tenant: str, wa_id: str) -> str | None:
#     """
#     Retorna el nombre_estado actual del aspirante según su wa_id.
#     """
#     try:
#         with get_connection_context() as conn:
#             with conn.cursor() as cur:
#                 cur.execute("""
#                     SELECT ea.nombre_estado
#                     FROM aspirantes a
#                     JOIN aspirante_estado_actual ae
#                         ON ae.id_aspirante = a.id_aspirante
#                     JOIN estados_aspirante ea
#                         ON ea.id_estado_aspirante = ae.id_estado_aspirante
#                     WHERE a.wa_id = %s
#                       AND ea.estado_activo = TRUE
#                     LIMIT 1
#                 """, (wa_id,))
#
#                 resultado = cur.fetchone()
#
#                 return resultado[0] if resultado else None
#
#     except (OperationalError, DatabaseError) as e:
#         print(f"❌ Error de base de datos al obtener estado del aspirante: {e}")
#         traceback.print_exc()
#         return None
#
#     except Exception as e:
#         print(f"❌ Error inesperado al obtener estado del aspirante: {e}")
#         traceback.print_exc()
#         return None



# -------------------------------------------------------
# -------------------------------------------------------
# PRUEBA NUEVO MODELOS
# PRUEBA NUEVO MODELOS
# PRUEBA NUEVO MODELOS
# PRUEBA NUEVO MODELOS
# -------------------------------------------------------
# -------------------------------------------------------



from pydantic import BaseModel

# Asegúrate de importar tus funciones y diccionarios
# from services.aspirant_flow import Enviar_menu_quickreply, accion_menu_estado_evaluacion
# from utils import MENUS (para que el front sepa qué botones existen)


# Modelos para la prueba
# class TestSendMenuInput(BaseModel):
#     phone_id: str
#     token: str
#     telefono_destino: str
#     estado_evaluacion: str
#
# class TestSimulateClickInput(BaseModel):
#     creador_id: int
#     button_id: str
#     phone_id: str
#     token: str
#     estado_evaluacion: str
#     telefono_destino: str

# @router.post("/enviar-menu")
# def test_enviar_menu(data: TestSendMenuInput):
#     """
#     Prueba unitaria: Envía el menú real a tu celular.
#     """
#     try:
#         # Usamos un creador_id dummy (1) para la prueba
#         Enviar_menu_quickreply(
#             creador_id=1,
#             estado_evaluacion=data.estado_evaluacion,
#             phone_id=data.phone_id,
#             token=data.token,
#             telefono=data.telefono_destino
#         )
#         return {"status": "success", "message": f"Menú '{data.estado_evaluacion}' enviado a {data.telefono_destino}"}
#     except Exception as e:
#         return {"status": "error", "message": str(e)}
#
# @router.post("/simular-clic")
# def test_simular_clic(data: TestSimulateClickInput):
#     """
#     Prueba unitaria: Ejecuta la lógica como si el usuario hubiera hecho clic.
#     NO espera a Meta, ejecuta la función de lógica directamente.
#     """
#     try:
#         # Aquí capturamos lo que haría el sistema (logs, updates de BD simulados)
#         accion_menu_estado_evaluacion(
#             creador_id=data.creador_id,
#             button_id=data.button_id,
#             phone_id=data.phone_id,
#             token=data.token,
#             estado_evaluacion=data.estado_evaluacion,
#             telefono=data.telefono_destino
#         )
#         return {"status": "success", "message": f"Acción '{data.button_id}' ejecutada exitosamente."}
#     except Exception as e:
#         return {"status": "error", "message": str(e)}


# Asegúrate de tener importado tu context manager
# from tu_archivo_conexion import get_connection_context

def obtener_datos_envio_aspirante(creador_id):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                sql = """
                    SELECT
                        c.telefono,
                        COALESCE(c.nickname, c.nombre_real) AS nombre,
                        cea.codigo,
                        cea.descripcion,
                        cea.mensaje_chatbot_simple,
                        cea.nombre_template
                    FROM creadores c
                    INNER JOIN perfil_creador pc
                        ON pc.creador_id = c.id
                    LEFT JOIN chatbot_estados_aspirante cea
                        ON cea.id_chatbot_estado = pc.id_chatbot_estado
                    WHERE c.id = %s
                    LIMIT 1
                """
                cur.execute(sql, (creador_id,))
                row = cur.fetchone()

                if not row:
                    return None

                return {
                    "telefono": row[0],
                    "nombre": row[1],                 # ✅ ahora sí llega al template
                    "codigo_estado": row[2],          # ✅ estado real
                    "descripcion": row[3],
                    "mensaje_chatbot_simple": row[4],
                    "nombre_template": row[5]
                }

    except Exception as e:
        print(f"❌ Error al obtener datos de envío para creador {creador_id}:", e)
        return None


def obtener_mensaje_por_codigo(codigo_estado):
    """
    Busca el mensaje de texto asociado a un código de estado específico.
    Útil para testing o flujos forzados.
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                sql = """
                      SELECT mensaje_chatbot_simple
                      FROM chatbot_estados_aspirante
                      WHERE codigo = %s \
                      """
                cur.execute(sql, (codigo_estado,))
                row = cur.fetchone()

                if row:
                    return row[0]
                return "Selecciona una opción:"

    except Exception as e:
        print(f"❌ Error al obtener mensaje por código {codigo_estado}:", e)
        return "Error recuperando mensaje."


def actualizar_estado_aspirante_(creador_id, nuevo_codigo_estado):
    """
    Actualiza el estado de un aspirante en perfil_creador basándose en el CÓDIGO de estado.
    Primero busca el ID del estado y luego actualiza.
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # 1. Obtener el ID numérico del estado basado en el código texto
                cur.execute("SELECT id_chatbot_estado FROM chatbot_estados_aspirante WHERE codigo = %s",
                            (nuevo_codigo_estado,))
                row = cur.fetchone()

                if not row:
                    print(f"⚠️ El código de estado '{nuevo_codigo_estado}' no existe en la BD.")
                    return False

                new_id_estado = row[0]

                # 2. Actualizar el perfil del creador
                sql_update = """
                             UPDATE perfil_creador
                             SET id_chatbot_estado   = %s, \
                                 fecha_actualizacion = CURRENT_TIMESTAMP
                             WHERE creador_id = %s \
                             """
                cur.execute(sql_update, (new_id_estado, creador_id))
                conn.commit()
                print(f"✅ Estado actualizado a '{nuevo_codigo_estado}' (ID: {new_id_estado}) para creador {creador_id}")
                return True

    except Exception as e:
        print(f"❌ Error actualizando estado para creador {creador_id}:", e)
        return False


def obtener_creador_id_por_telefono(telefono):
    """
    Busca el ID del creador a partir de su número de WhatsApp.
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # Nota: Asegúrate de que el formato del teléfono en BD coincida (con o sin +)
                cur.execute("SELECT id FROM creadores WHERE telefono = %s", (telefono,))
                row = cur.fetchone()

                if row:
                    return row[0]
                return None

    except Exception as e:
        print(f"❌ Error buscando creador por teléfono {telefono}:", e)
        return None


# Asegúrate de importar la función de actualización de DB
# from db_service import actualizar_estado_aspirante, obtener_datos_envio_aspirante


# Modelo para la petición de actualización
# class ActualizarEstadoRequest(BaseModel):
#     creador_id: int
#     estado_codigo: str


# @router.get("/obtener-estado-actual/{creador_id}")
# def get_estado_actual(creador_id: int):
#     """
#     Consulta en la BD en qué estado se encuentra el creador.
#     """
#     datos = obtener_datos_envio_aspirante(creador_id)
#     if not datos:
#         raise HTTPException(status_code=404, detail="Creador no encontrado")
#
#     return {
#         "status": "success",
#         "codigo_actual": datos["codigo_estado"],
#         "telefono": datos["telefono"]
#     }


# @router.post("/guardar-estado-db")
# def guardar_estado_db(data: ActualizarEstadoRequest):
#     """
#     Actualiza el campo id_chatbot_estado en la tabla perfil_creador.
#     """
#     exito = actualizar_estado_aspirante_(data.creador_id, data.estado_codigo)
#
#     if exito:
#         return {"status": "success", "mensaje": f"Estado actualizado a '{data.estado_codigo}' en BD."}
#     else:
#         raise HTTPException(status_code=500, detail="Error al actualizar en Base de Datos")


import requests
import json
# IMPORTANTE: Importa tus funciones de DB aquí
MENUS = {
    "post_encuesta_inicial": {
        "botones": [
            ("MENU_PROCESO_INCORPORACION", "Proceso incorporación"),
            ("MENU_PREGUNTAS_FRECUENTES", "Preguntas Frecuentes"),
        ]
    },
    "solicitud_agendamiento_tiktok": {
        "botones": [
            ("MENU_AGENDAR_PRUEBA_TIKTOK", "Agendar prueba Live"),
            ("MENU_VER_GUIA_PRUEBA", "Ver guía"),
            ("MENU_CHAT_ASESOR", "Hablar con asesor")
        ]
    },
    "usuario_agendo_prueba_tiktok": {
        "botones": [
            ("MENU_INGRESAR_LINK_TIKTOK", "Ingresar link Live"),
            ("MENU_MODIFICAR_CITA_PRUEBA", "Modificar cita"),
            ("MENU_VER_GUIA_PRUEBA", "Ver guía"),
        ]
    },
    "solicitud_agendamiento_entrevista": {
        "botones": [
            ("MENU_AGENDAR_ENTREVISTA", "Agendar entrevista"),
        ]
    },
    "usuario_agendo_entrevista": {
        "botones": [
            ("MENU_MODIFICAR_CITA_ENTREVISTA", "Modificar cita"),
        ]
    },
    "solicitud_agendamiento_tiktok2": {
        "botones": [
            ("MENU_AGENDAR_PRUEBA_TIKTOK_2", "Agendar prueba #2"),
            ("MENU_RESULTADO_PRUEBA_1", "Resultado prueba #1"),
        ]
    },
    "usuario_agendo_prueba_tiktok2": {
        "botones": [
            ("MENU_INGRESAR_LINK_TIKTOK_2", "Ingresar link #2"),
            ("MENU_MODIFICAR_CITA_PRUEBA_2", "Modificar cita #2"),
            ("MENU_VER_GUIA_PRUEBA_2", "Ver guía #2"),
        ]
    },
    "solicitud_agendamiento_entrevista2": {
        "botones": [
            ("MENU_AGENDAR_ENTREVISTA", "Agendar entrevista"),
        ]
    },
    "usuario_agendo_entrevista2": {
        "botones": [
            ("MENU_MODIFICAR_CITA_ENTREVISTA", "Modificar cita"),
            ("MENU_TEMAS_ENTREVISTA_2", "Temas entrevista #2"),
        ]
    },
    "solicitud_invitacion_tiktok": {
        "botones": [
            ("MENU_ESTADO_PROCESO", "Estado del proceso"),
        ]
    },
    "invitacion_tiktok_aceptada": {
        "botones": [
            ("MENU_ESTADO_PROCESO", "Estado del proceso"),
        ]
    },
    "solicitud_invitacion_usuario": {
        "botones": [
            ("MENU_VENTAJAS_AGENCIA", "Ventajas agencia"),
            ("MENU_ACEPTAR_INCORPORACION", "Acepta incorporación"),
        ]
    },

}




def Enviar_menu_quickreplyV3(
    *,
    creador_id: int,
    estado_evaluacion: str,
    phone_id: str,
    token: str,
    telefono_destino: str,
    texto_final: str,
):
    print(f"🏗️ Construyendo menú para estado: {estado_evaluacion}")

    menu_config = MENUS.get(estado_evaluacion)

    if not menu_config:
        print(f"⚠️ No hay botones configurados en Python para: {estado_evaluacion}")
        enviar_a_meta_texto_simple(texto_final, telefono_destino, phone_id, token)
        return

    botones = menu_config["botones"]

    botones_api = [
        {"type": "reply", "reply": {"id": boton_id, "title": titulo[:20]}}
        for boton_id, titulo in botones[:3]
    ]

    payload = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": texto_final},
            "action": {"buttons": botones_api}
        }
    }

    enviar_a_meta(payload, phone_id, token)



def Enviar_menu_quickreply_V1(creador_id, estado_evaluacion, phone_id, token, telefono_override=None):
    """
    Envía un menú interactivo.
    - TEXTO y TELÉFONO: Se obtienen dinámicamente de la Base de Datos.
    - BOTONES: Se obtienen de la configuración local (MENUS), ya que no existen en la tabla.
    """

    # -------------------------------------------------------------------------
    # 1. CONFIGURACIÓN DE BOTONES (Estructura Fija)
    # -------------------------------------------------------------------------
    # Mantenemos este diccionario SOLO para saber qué botones mostrar en cada caso.
    # El campo "texto" aquí es solo un fallback por si falla la BD.
    MENUS = {
        "post_encuesta_inicial": {
            "botones": [
                ("MENU_PROCESO_INCORPORACION", "Proceso de incorporación"),
                ("MENU_PREGUNTAS_FRECUENTES", "Preguntas Frecuentes"),
            ]
        },
        "solicitud_agendamiento_tiktok": {
            "botones": [
                ("MENU_AGENDAR_PRUEBA_TIKTOK", "Agendar prueba Live"),
                ("MENU_VER_GUIA_PRUEBA", "Ver guía"),
                ("MENU_CHAT_ASESOR", "Hablar con asesor")
            ]
        },
        "usuario_agendo_prueba_tiktok": {
            "botones": [
                ("MENU_INGRESAR_LINK_TIKTOK", "Ingresar link Live"),
                ("MENU_MODIFICAR_CITA_PRUEBA", "Modificar cita"),
                ("MENU_VER_GUIA_PRUEBA", "Ver guía"),
            ]
        },
        "solicitud_agendamiento_entrevista": {
            "botones": [
                ("MENU_AGENDAR_ENTREVISTA", "Agendar entrevista"),
            ]
        },
        "usuario_agendo_entrevista": {
            "botones": [
                ("MENU_MODIFICAR_CITA_ENTREVISTA", "Modificar cita"),
            ]
        },
        "solicitud_agendamiento_tiktok2": {
            "botones": [
                ("MENU_AGENDAR_PRUEBA_TIKTOK_2", "Agendar prueba #2"),
                ("MENU_RESULTADO_PRUEBA_1", "Resultado prueba #1"),
            ]
        },
        "usuario_agendo_prueba_tiktok2": {
            "botones": [
                ("MENU_INGRESAR_LINK_TIKTOK_2", "Ingresar link #2"),
                ("MENU_MODIFICAR_CITA_PRUEBA_2", "Modificar cita #2"),
                ("MENU_VER_GUIA_PRUEBA_2", "Ver guía #2"),
            ]
        },
        "solicitud_agendamiento_entrevista2": {
            "botones": [
                ("MENU_AGENDAR_ENTREVISTA", "Agendar entrevista"),
            ]
        },
        "usuario_agendo_entrevista2": {
            "botones": [
                ("MENU_MODIFICAR_CITA_ENTREVISTA", "Modificar cita"),
                ("MENU_TEMAS_ENTREVISTA_2", "Temas entrevista #2"),
            ]
        },
        "solicitud_invitacion_tiktok": {
            "botones": [
                ("MENU_ESTADO_PROCESO", "Estado del proceso"),
            ]
        },
        "invitacion_tiktok_aceptada": {
            "botones": [
                ("MENU_ESTADO_PROCESO", "Estado del proceso"),
            ]
        },
        "solicitud_invitacion_usuario": {
            "botones": [
                ("MENU_VENTAJAS_AGENCIA", "Ventajas agencia"),
                ("MENU_ACEPTAR_INCORPORACION", "Aceptar incorporación"),
            ]
        },
    }

    # -------------------------------------------------------------------------
    # 2. OBTENCIÓN DE DATOS REALES (DB)
    # -------------------------------------------------------------------------
    print(f"🏗️ Construyendo menú para estado: {estado_evaluacion}")

    # Variables finales
    texto_final = "Selecciona una opción:"  # Valor por defecto seguro
    telefono_destino = telefono_override

    # A. MODO PRODUCCIÓN (Sin override de teléfono)
    if not telefono_override:
        # Buscamos en la BD usando tu función SQL real
        datos_db = obtener_datos_envio_aspirante(creador_id)

        if datos_db:
            telefono_destino = datos_db["telefono"]

            # Prioridad absoluta al texto de la BD (según tu SELECT)
            texto_db = datos_db.get("mensaje_chatbot_simple")
            if texto_db:
                texto_final = texto_db
                print(f"✅ Texto DB cargado: '{texto_final[:20]}...'")
            else:
                print("⚠️ El estado en BD no tiene mensaje_chatbot_simple configurado.")
        else:
            print(f"❌ Error CRÍTICO: No se encontraron datos para creador_id {creador_id}")
            return

    # B. MODO TESTING (Con override de teléfono desde React)
    else:
        # Buscamos solo el mensaje asociado al código de estado
        msg_db = obtener_mensaje_por_codigo(estado_evaluacion)
        if msg_db:
            texto_final = msg_db
            print(f"✅ (Test) Texto DB cargado para {estado_evaluacion}")

    # -------------------------------------------------------------------------
    # 3. CONSTRUCCIÓN Y ENVÍO
    # -------------------------------------------------------------------------

    # Recuperar botones del diccionario
    menu_config = MENUS.get(estado_evaluacion)

    if not menu_config:
        print(f"⚠️ No hay botones configurados en Python para: {estado_evaluacion}")
        # Opcional: Enviar solo texto si no hay botones definidos
        enviar_a_meta_texto_simple(texto_final, telefono_destino, phone_id, token)
        return

    botones = menu_config["botones"]

    # Construir estructura de Meta
    botones_api = [
        {
            "type": "reply",
            "reply": {
                "id": boton_id,
                "title": titulo[:20]  # WhatsApp limita títulos a 20 chars
            }
        }
        for boton_id, titulo in botones[:3]  # Max 3 botones
    ]

    payload = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": texto_final},
            "action": {"buttons": botones_api}
        }
    }

    enviar_a_meta(payload, phone_id, token)


# --- Funciones Auxiliares de Envío ---

def enviar_a_meta(payload, phone_id, token):
    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        res = requests.post(url, headers=headers, json=payload)
        print(f"📤 Enviado a Meta: {res.status_code}")
        if res.status_code not in [200, 201]:
            print(f"❌ Error Meta: {res.text}")
    except Exception as e:
        print(f"❌ Excepción enviando: {e}")


def enviar_a_meta_texto_simple(texto, telefono, phone_id, token):
    """Fallback por si no hay botones"""
    payload = {
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "text",
        "text": {"body": texto}
    }
    enviar_a_meta(payload, phone_id, token)



# ----------CODIGO NUEVO-------------------------------
# -----------------------------------------------------
# -----------------------------------------------------
# -----------------------------------------------------
# -----------------------------------------------------
# -----------------------------------------------------
# -----------------------------------------------------

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# --- IMPORTACIONES DEL PROYECTO ---
# Ajusta estas rutas según tu estructura de carpetas real


# Router API


# --- MODELOS DE DATOS (PYDANTIC) ---
class EnvioPruebaRequest(BaseModel):
    creador_id: int
    estado_codigo: str
    tenant_name: str  # El Front envía el subdominio (ej: 'webhook_axec') para resolver credenciales


class ActualizarEstadoRequest(BaseModel):
    creador_id: int
    estado_codigo: Optional[str] = None


# =============================================================================
# ENDPOINT 1: LISTAR ESTADOS (Para llenar el Select del Front)
# =============================================================================
@router.get("/listar-estados")
def listar_estados_db():
    """
    Obtiene todos los estados posibles de la tabla chatbot_estados_aspirante.
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                            SELECT codigo, descripcion
                            FROM chatbot_estados_aspirante
                            WHERE estado_activo = true
                            ORDER BY id_chatbot_estado ASC
                            """)
                # Retornamos lista de diccionarios
                estados = [{"codigo": row[0], "descripcion": row[1]} for row in cur.fetchall()]
        return estados
    except Exception as e:
        print(f"❌ Error DB: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener estados")


# =============================================================================
# ENDPOINT 2: OBTENER ESTADO ACTUAL (Consultar Creador)
# =============================================================================
@router.get("/obtener-estado-actual/{creador_id}")
def get_estado_actual(creador_id: int):
    """
    Consulta el estado actual de un creador con metadata del chatbot.
    """
    try:
        datos = obtener_datos_envio_aspirante(creador_id)

        if not datos:
            raise HTTPException(status_code=404, detail="Creador no encontrado en BD")

        return {
            "status": "success",
            "codigo_actual": datos["codigo_estado"],
            "descripcion": datos["descripcion"],
            "mensaje_chatbot_simple": datos["mensaje_chatbot_simple"],
            "telefono": datos["telefono"]
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ENDPOINT 3: GUARDAR ESTADO MANUALMENTE (Update en BD)
# =============================================================================
@router.post("/guardar-estado-db")
def guardar_estado_db(data: ActualizarEstadoRequest):
    """
    Fuerza la actualización del estado de un creador en la base de datos.
    """
    try:
        exito = actualizar_estado_aspirante_(data.creador_id, data.estado_codigo)

        if exito:
            return {"status": "success", "mensaje": f"Estado actualizado a '{data.estado_codigo}'."}
        else:
            raise HTTPException(status_code=400, detail="No se pudo actualizar (verifica ID o código).")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ENDPOINT 4: ENVIAR MENSAJE SEGURO (Multitenant)
# =============================================================================
from fastapi import HTTPException
from starlette.responses import JSONResponse

@router.post("/enviar-mensaje-estado")
def enviar_mensaje_estado(data: EnvioPruebaRequest):
    try:
        print(f"🔐 Resolviendo credenciales para tenant: {data.tenant_name}")

        cuenta = obtener_cuenta_por_subdominio(data.tenant_name)
        if not cuenta:
            return JSONResponse(
                {"error": f"No se encontraron credenciales para el tenant '{data.tenant_name}'"},
                status_code=404
            )

        token_cliente = cuenta.get("access_token")
        phone_id_cliente = cuenta.get("phone_number_id")
        business_name = cuenta.get("business_name", "Agencia")

        if not token_cliente or not phone_id_cliente:
            return JSONResponse(
                {"error": "El tenant existe pero le faltan credenciales (token/phone_id)"},
                status_code=500
            )

        # Contextvars
        current_token.set(token_cliente)
        current_phone_id.set(phone_id_cliente)
        current_business_name.set(business_name)

        datos_creador = obtener_datos_envio_aspirante(data.creador_id)
        if not datos_creador:
            raise HTTPException(status_code=404, detail=f"Creador ID {data.creador_id} no existe")

        telefono_destino = datos_creador["telefono"]
        estado_real = datos_creador["codigo_estado"]

        texto_final = datos_creador.get("mensaje_chatbot_simple") or "Selecciona una opción:"

        # ✅ 4) Verificar ventana 24h
        en_ventana = obtener_status_24hrs(telefono_destino)

        if en_ventana:
            print("✅ En ventana: Enviando MENÚ quick reply")
            Enviar_menu_quickreply(
                creador_id=data.creador_id,
                estado_real=estado_real,
                msg_chat_bot=texto_final,
                phone_id=phone_id_cliente,
                token=token_cliente,
                telefono_destino=telefono_destino
            )
            return {
                "status": "success",
                "mensaje": f"Menú '{estado_real}' enviado a {telefono_destino} vía {business_name}",
                "en_ventana_24h": True
            }

        # 🚫 Fuera de ventana: enviar plantilla reconexión general
        print("⚠️ Fuera de ventana: Enviando PLANTILLA de reconexión")

        # Recomendado: nombre del template (el que creaste en Meta)
        nombre_plantilla = "reconexion_general_corta"

        # Variables del template:
        # {{1}} = nombre (si no lo tienes, usa un fallback)
        # {{2}} = nombre de la agencia
        nombre_contacto = (datos_creador.get("nombre") or "👋").strip()

        status_code, resp = enviar_plantilla_generica_parametros(
            token=token_cliente,
            phone_number_id=phone_id_cliente,
            numero_destino=telefono_destino,
            nombre_plantilla=nombre_plantilla,
            codigo_idioma="es_CO",
            parametros=[nombre_contacto, business_name],
            body_vars_count=2
        )

        if status_code not in (200, 201):
            raise HTTPException(status_code=502, detail={"error": "meta_template_failed", "meta": resp})

        # 🔔 Importante: aquí NO mandes el menú inmediatamente.
        # Debes mandarlo cuando el usuario haga clic en "Continuar" (webhook button reply).
        return {
            "status": "success",
            "mensaje": f"Plantilla de reconexión enviada a {telefono_destino} vía {business_name}",
            "en_ventana_24h": False,
            "template": nombre_plantilla,
            "meta": resp
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error en envío seguro: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.post("/enviar-mensaje-estadoV1")
def enviar_mensaje_estadoV1(data: EnvioPruebaRequest):
    """
    1. Resuelve credenciales basadas en el tenant (subdominio).
    2. Establece el contexto seguro.
    3. Envía el mensaje a WhatsApp.
    """
    try:
        print(f"🔐 Resolviendo credenciales para tenant: {data.tenant_name}")

        # A. OBTENER CREDENCIALES DEL TENANT (Backend Seguro)
        # Esto evita que el token viaje desde el Front
        cuenta = obtener_cuenta_por_subdominio(data.tenant_name)

        if not cuenta:
            return JSONResponse(
                {"error": f"No se encontraron credenciales para el tenant '{data.tenant_name}'"},
                status_code=404
            )

        # Extraer datos sensibles
        token_cliente = cuenta.get("access_token")
        phone_id_cliente = cuenta.get("phone_number_id")
        business_name = cuenta.get("business_name", "Agencia")

        if not token_cliente or not phone_id_cliente:
            return JSONResponse(
                {"error": "El tenant existe pero le faltan credenciales (token/phone_id)"},
                status_code=500
            )

        # B. ESTABLECER CONTEXTO (Igual que en tu middleware/consolidar)
        current_token.set(token_cliente)
        current_phone_id.set(phone_id_cliente)
        current_business_name.set(business_name)

        # C. VALIDAR DESTINATARIO
        datos_creador = obtener_datos_envio_aspirante(data.creador_id)
        if not datos_creador:
            raise HTTPException(status_code=404, detail=f"Creador ID {data.creador_id} no existe")

        telefono_destino = datos_creador["telefono"]

        # D. EJECUTAR EL ENVÍO
        # Pasamos las credenciales resueltas aquí
        Enviar_menu_quickreply(
            creador_id=data.creador_id,
            estado_evaluacion=datos_creador["codigo_estado"],  # ✅ VIENE DE BD
            phone_id=phone_id_cliente,
            token=token_cliente,
            telefono_override=None  # Usar el de la BD
        )

        return {
            "status": "success",
            "mensaje": f"Menú '{data.estado_codigo}' enviado a {telefono_destino} vía {business_name}"
        }

    except Exception as e:
        print(f"❌ Error en envío seguro: {e}")
        # Retornamos 500 pero con detalle para que lo veas en el log del Front
        raise HTTPException(status_code=500, detail=str(e))


def Enviar_boton_opciones_unico(
    creador_id: int,
    estado_evaluacion: str,
    phone_id: str,
    token: str,
    telefono_destino: str,
    texto_final: str,
):
    """
    Envía un mensaje interactivo con UN (1) botón quick reply.
    - Texto: texto_final (idealmente mensaje_chatbot_simple desde BD)
    - Botón: Menú de opciones
    """

    boton_id = "BTN_ABRIR_MENU_OPCIONES"
    boton_titulo = "Menú de opciones"

    print(f"🏗️ Enviando botón único para estado: {estado_evaluacion}")

    # (Opcional) Si quieres que el id sea trazable por estado:
    # boton_id = f"{boton_id}__{estado_evaluacion}"

    payload = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": texto_final},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": boton_id,
                            "title": boton_titulo[:20],  # límite WhatsApp
                        },
                    }
                ]
            },
        },
    }

    enviar_a_meta(payload, phone_id, token)



def Enviar_menu_quickreply(creador_id, estado_real,msg_chat_bot, phone_id, token, telefono_destino):
    """
    Envía el MENÚ de opciones (quick replies) basado en el estado REAL.
    Se usa desde webhook al hacer clic en MENU_OPCIONES.
    """
    texto_final = msg_chat_bot

    print(f"🏗️ Desplegando menú para estado REAL: {estado_real} (creador_id={creador_id})")

    menu_config = MENUS.get(estado_real)
    if not menu_config:
        print(f"⚠️ No hay botones configurados en MENUS para estado: {estado_real}")
        enviar_a_meta_texto_simple(texto_final, telefono_destino, phone_id, token)
        return True

    botones = menu_config.get("botones", [])
    if not botones:
        print(f"⚠️ MENUS[{estado_real}] no tiene botones")
        enviar_a_meta_texto_simple(texto_final, telefono_destino, phone_id, token)
        return True

    botones_api = [
        {"type": "reply", "reply": {"id": boton_id, "title": titulo[:20]}}
        for boton_id, titulo in botones[:3]
    ]

    payload = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": texto_final},
            "action": {"buttons": botones_api},
        },
    }

    enviar_a_meta(payload, phone_id, token)
    return True


# ------ENVIAR MENU SIN MENSAJE INICIAL
def Enviar_menu_quickreply_v4(creador_id, estado_real, phone_id, token, telefono_destino):
    """
    Envía el MENÚ de opciones (quick replies) basado en el estado REAL.
    Se usa desde webhook al hacer clic en MENU_OPCIONES.
    """
    texto_final = "Elige una opción"

    print(f"🏗️ Desplegando menú para estado REAL: {estado_real} (creador_id={creador_id})")

    menu_config = MENUS.get(estado_real)
    if not menu_config:
        print(f"⚠️ No hay botones configurados en MENUS para estado: {estado_real}")
        enviar_a_meta_texto_simple(texto_final, telefono_destino, phone_id, token)
        return True

    botones = menu_config.get("botones", [])
    if not botones:
        print(f"⚠️ MENUS[{estado_real}] no tiene botones")
        enviar_a_meta_texto_simple(texto_final, telefono_destino, phone_id, token)
        return True

    botones_api = [
        {"type": "reply", "reply": {"id": boton_id, "title": titulo[:20]}}
        for boton_id, titulo in botones[:3]
    ]

    payload = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": texto_final},
            "action": {"buttons": botones_api},
        },
    }

    enviar_a_meta(payload, phone_id, token)
    return True


# @router.post("/enviar-mensaje-estado")
# def enviar_mensaje_estado(data: EnvioPruebaRequest):
#     try:
#         print(f"🔐 Resolviendo credenciales para tenant: {data.tenant_name}")
#
#         cuenta = obtener_cuenta_por_subdominio(data.tenant_name)
#         if not cuenta:
#             return JSONResponse(
#                 {"error": f"No se encontraron credenciales para el tenant '{data.tenant_name}'"},
#                 status_code=404
#             )
#
#         token_cliente = cuenta.get("access_token")
#         phone_id_cliente = cuenta.get("phone_number_id")
#         business_name = cuenta.get("business_name", "Agencia")
#
#         if not token_cliente or not phone_id_cliente:
#             return JSONResponse(
#                 {"error": "El tenant existe pero le faltan credenciales (token/phone_id)"},
#                 status_code=500
#             )
#
#         # Contextvars (ideal: reset en finally, pero lo dejo mínimo aquí)
#         current_token.set(token_cliente)
#         current_phone_id.set(phone_id_cliente)
#         current_business_name.set(business_name)
#
#         datos_creador = obtener_datos_envio_aspirante(data.creador_id)
#         if not datos_creador:
#             raise HTTPException(status_code=404, detail=f"Creador ID {data.creador_id} no existe")
#
#         telefono_destino = datos_creador["telefono"]
#         estado_real = datos_creador["codigo_estado"]
#
#         # Texto a enviar: prioridad mensaje_chatbot_simple, luego descripcion, luego default
#         texto_final = (
#             datos_creador.get("mensaje_chatbot_simple")
#         )
#
#         # Enviar_boton_opciones_unico(
#         #     creador_id=data.creador_id,
#         #     estado_evaluacion=estado_real,
#         #     phone_id=phone_id_cliente,
#         #     token=token_cliente,
#         #     telefono_destino=telefono_destino,
#         #     texto_final=texto_final,
#         # )
#
#         Enviar_menu_quickreply(
#             creador_id=data.creador_id,
#             estado_real=estado_real,
#             msg_chat_bot=texto_final,
#             phone_id=phone_id_cliente,
#             token=token_cliente,
#             telefono_destino=telefono_destino
#         )
#
#
#         return {
#             "status": "success",
#             "mensaje": f"Menú '{estado_real}' enviado a {telefono_destino} vía {business_name}"
#         }
#
#     except Exception as e:
#         print(f"❌ Error en envío seguro: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
