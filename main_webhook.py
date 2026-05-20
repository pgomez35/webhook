# ============================
# IMPORTS - Estándar de Python
# ============================
import json
import os
import re
import secrets

import requests
import time
import traceback
import unicodedata
import phonenumbers
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta

# ============================
# IMPORTS - Terceros
# ============================
import psycopg2
from dotenv import load_dotenv
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from phonenumbers import geocoder, region_code_for_number
from pydantic import BaseModel
from rapidfuzz import process, fuzz

from DataBase import buscar_usuario_por_telefono, get_connection, marcar_encuesta_no_finalizada, guardar_mensaje, \
    obtener_cuenta_por_phone_id, obtener_configuracion_agencia, guardar_mensaje_nuevo, obtener_cuenta_por_subdominio, \
    marcar_encuesta_completada, buscar_aspirante_por_usuario_tiktok, encuesta_finalizada, actualizar_telefono_aspirante
# ============================
# IMPORTS - Locales
# ============================
# from DataBase import *
from enviar_msg_wp import (
    enviar_boton_iniciar_Completa,
    enviar_botones_Completa,
    enviar_mensaje_texto_simple,
    enviar_plantilla_generica,
    enviar_plantilla_generica_parametros
)
from main_diagnostico import obtener_estado_aspirante
from main_configuracion import get_config
from main_mensajeria_whatsapp import reenviar_ultimo_mensaje, enviar_mensaje_whatsapp_texto
from portal_access_tokens import generar_url_portal, generar_url_portal_usuario
from tenant import (
    current_business_name,
    current_phone_id,
    current_tenant,
    current_token
)
from utils_aspirantes_1 import *
from redis_client import redis_set_temp, redis_get_temp, redis_delete_temp
from utils_aspirantes import obtener_status_24hrs, \
    enviar_plantilla_estado_evaluacion, buscar_estado_creador, \
    accion_menu_estado_evaluacion, _handle_statuses, enviar_confirmacion_interactiva, manejar_input_link_tiktok, \
    registrar_cambio_estado, construir_url_actualizar_perfil, iniciar_trazabilidad_encuesta_inicial, \
    habilitar_trazabilidad_encuesta_inicial, obtener_persona_portal_por_telefono, \
    obtener_aspirante_portal_por_telefono, obtener_plantilla_mensaje_portal, \
    construir_mensaje_portal, enviar_inicio_portal

# from utils_aspirantes import guardar_estado_eval, obtener_status_24hrs, Enviar_msg_estado, \
#     enviar_plantilla_estado_evaluacion, obtener_aspirante_id_por_telefono, buscar_estado_creador, Enviar_menu_quickreply, \
#     accion_menu_estado_evaluacion, validar_url_link_tiktok_live, guardar_link_tiktok_live, \
#     actualizar_mensaje_desde_status, _handle_statuses, enviar_confirmacion_interactiva

load_dotenv()

# ============================
# CONFIGURACIÓN - URLs Frontend
# ============================
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "https://talentum-manager.com")

router = APIRouter()

# Estado del flujo en memoria
usuarios_flujo = {}    # { numero: paso_actual }
# ⚠️ respuestas = {} - ELIMINADO: No se usaba. Las respuestas se guardan en aspirantes_perfil_flujo_temp
usuarios_temp = {}  # ⚠️ Fallback a memoria si Redis falla (solo para datos temporales de onboarding)

# ============================
# ENVIAR MENSAJES INICIO
# ============================


# # ✅ Wrapper opcional: mantiene compatibilidad con tu código actual (sin tocar todo)
# def enviar_mensaje(numero: str, texto: str):
#     try:
#         token = current_token.get()
#         phone_id = current_phone_id.get()
#         return enviar_mensaje_con_credenciales(numero, texto, token, phone_id)
#     except LookupError as e:
#         print(f"❌ Contexto de tenant no disponible al enviar mensaje a {numero}: {e}")
#         raise



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


def obtener_mensaje_bienvenida_onboarding() -> str:
    """
    Obtiene el mensaje inicial de onboarding desde configuración.
    Si la clave no existe o viene vacía, retorna el mensaje por defecto.
    """
    mensaje_default = (
        "¡Hola! 👋 Bienvenido.\n"
        "Para comenzar, por favor escribe tu *usuario de TikTok* "
        "(sin @)."
    )

    try:
        valor = get_config("mensaje_bienvenida_onboarding")
        if valor is None:
            return mensaje_default

        valor_str = str(valor).strip()
        return valor_str if valor_str else mensaje_default
    except Exception:
        return mensaje_default

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
            "3️⃣ Enviar comunicado a aspirantes/aspirantes\n"
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
                    FROM aspirantes
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

                aspirante_id, usuario, nombre_real = row

                # 2️⃣ Obtener estado/observaciones desde aspirantes_perfil
                cur.execute(
                    """
                    SELECT observaciones_finales, estado_evaluacion
                    FROM aspirantes_perfil
                    WHERE aspirante_id = %s
                    LIMIT 1;
                    """,
                    (aspirante_id,),
                )
                fila = cur.fetchone()

        # 3️⃣ Armar el diagnóstico fuera del contexto de conexión
        texto_resumen = None
        if fila:
            observaciones = str(fila[0]).strip() if fila[0] is not None else ""
            estado_eval = str(fila[1]).strip() if len(fila) > 1 and fila[1] is not None else ""
            texto_resumen = observaciones or estado_eval

        if not texto_resumen:
            diagnostico = (
                f"🔎 Diagnóstico para {nombre_real}:\n"
                "Aún estamos preparando la evaluación de tu perfil. "
                "Te avisaremos tan pronto esté lista. ⏳"
            )
        else:
            diagnostico = f"🔎 Diagnóstico para {nombre_real}:\n\n{texto_resumen}"

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

    # Nombre
    datos["nombre"] = respuestas.get(1)

    # Edad (ID numérico)
    datos["edad"] = int(respuestas.get(2)) if respuestas.get(2) else None

    # Género (ID)
    datos["genero"] = int(respuestas.get(3)) if respuestas.get(3) else None

    # País (ID)
    datos["pais"] = int(respuestas.get(4)) if respuestas.get(4) else None

    # Ciudad (texto libre validado)
    ciudad_usuario = respuestas.get(5)
    if ciudad_usuario:
        resultado = validar_aceptar_ciudad(ciudad_usuario)
        datos["ciudad"] = resultado["ciudad"]
    else:
        datos["ciudad"] = None

    # Actividad (ID)
    datos["actividad_actual"] = int(respuestas.get(6)) if respuestas.get(6) else None

    # Intención (ID)
    datos["intencion_trabajo"] = int(respuestas.get(7)) if respuestas.get(7) else None

    # ✅ NUEVO CAMPO DIRECTO EN BD
    datos["experiencia_tiktok_live"] = int(respuestas.get(8)) if respuestas.get(8) else None

    # Horas disponibles (ID opción)
    datos["tiempo_disponible"] = int(respuestas.get(9)) if respuestas.get(9) else None

    # Días disponibles (ID opción)
    datos["frecuencia_lives"] = int(respuestas.get(10)) if respuestas.get(10) else None

    # Zona horaria según país
    if datos.get("pais"):
        tz = infer_zona_horaria(datos["pais"])
        if tz:
            datos["zona_horaria"] = tz

    return datos

# Asumo que ya existen en tu proyecto:
# - get_connection_context()
# - current_tenant (contextvar)
# - procesar_respuestas(respuestas_dict)
# - validar_aceptar_ciudad(), infer_zona_horaria(), etc. (usadas dentro de procesar_respuestas)


# def insertar_aspirante_encuesta_inicial(
#     telefono: str,
#     datos: dict,
#     tenant_schema: str
# ):
#     """
#     Inserta los datos iniciales del aspirante en {schema}.aspirante_encuesta_inicial
#     SOLO si aún no existe ese teléfono.
#     """
#     try:
#         print("🧪 [ASPIRANTE] Iniciando inserción en aspirante_encuesta_inicial")
#         print(f"📞 [ASPIRANTE] Teléfono: {telefono}")
#         print(f"📦 [ASPIRANTE] Datos recibidos: {datos}")
#
#         with get_connection_context() as conn:
#             with conn.cursor() as cur:
#
#                 # 🔎 Validar existencia previa
#                 cur.execute(f"""
#                     SELECT 1
#                     FROM {tenant_schema}.aspirante_encuesta_inicial
#                     WHERE telefono = %s
#                     LIMIT 1
#                 """, (telefono,))
#
#                 if cur.fetchone():
#                     print(f"ℹ️ [ASPIRANTE] Ya existe registro para {telefono}. No se inserta.")
#                     return {"inserted": False, "reason": "exists"}
#
#                 # 👇 Tomar experiencia TikTok Live desde el json (si existe)
#                 experiencia_tiktok = 0
#                 try:
#                     exp_raw = datos.get("experiencia_otras_plataformas") or "{}"
#                     exp_json = json.loads(exp_raw) if isinstance(exp_raw, str) else (exp_raw or {})
#                     experiencia_tiktok = exp_json.get("TikTok Live", 0) or 0
#                 except Exception:
#                     experiencia_tiktok = 0
#
#                 # ✅ Insert
#                 cur.execute(f"""
#                     INSERT INTO {tenant_schema}.aspirante_encuesta_inicial (
#                         telefono,
#                         nombre,
#                         edad,
#                         genero,
#                         pais,
#                         ciudad,
#                         actividad_actual,
#                         intencion_trabajo,
#                         tiempo_disponible,
#                         frecuencia_lives,
#                         experiencia_tiktok,
#                         tiempo_experiencia,
#                         created_at
#                     ) VALUES (
#                         %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
#                     )
#                 """, (
#                     telefono,
#                     datos.get("nombre"),
#                     datos.get("edad"),
#                     datos.get("genero"),
#                     datos.get("pais"),
#                     datos.get("ciudad"),
#                     datos.get("actividad_actual"),
#                     datos.get("intencion_trabajo"),
#                     datos.get("tiempo_disponible"),
#                     datos.get("frecuencia_lives"),
#                     experiencia_tiktok,
#                     # Si tú quieres guardar "tiempo_experiencia" (paso 9) en meses, aquí podrías ponerlo:
#                     # pero en tu procesar_respuestas lo conviertes a años. Si no existe, queda None.
#                     None
#                 ))
#
#                 conn.commit()
#                 print(f"✅ [ASPIRANTE] Insertado correctamente en {tenant_schema}.aspirante_encuesta_inicial")
#                 return {"inserted": True}
#
#     except Exception as e:
#         print(f"❌ [ASPIRANTE] Error insertando encuesta inicial para {telefono}: {e}")
#         traceback.print_exc()
#         return {"inserted": False, "error": str(e)}


def consolidar_perfil(
    telefono: str,
    respuestas_dict: dict | None = None,
    tenant_schema: Optional[str] = None
):
    """
    Procesa y actualiza un número en aspirantes_perfil con manejo de errores.

    - Lee creador por teléfono en aspirantes
    - Si respuestas_dict es None, lee respuestas de {schema}.aspirantes_perfil_flujo_temp
    - Procesa respuestas (procesar_respuestas)
    - Inserta en {schema}.aspirante_encuesta_inicial (NUEVO) si no existe aún
    - Actualiza nombre_real en aspirantes
    - Actualiza aspirantes_perfil para ese aspirante_id

    Retorna {"status": "ok"} si no revienta.
    """
    schema = tenant_schema or current_tenant.get() or "public"

    print("🧩 [CONSOLIDAR] ===============================")
    print(f"🧩 [CONSOLIDAR] Teléfono: {telefono}")
    print(f"🧩 [CONSOLIDAR] Tenant schema: {schema}")
    print(f"🧩 [CONSOLIDAR] ¿Respuestas vienen en request? {'SI' if respuestas_dict else 'NO'}")

    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                # -------------------------------
                # 1) Buscar creador por teléfono
                # -------------------------------
                print("🔎 [CONSOLIDAR] Buscando creador en tabla aspirantes...")
                cur.execute(
                    f"SELECT id, usuario, nombre_real, whatsapp FROM {schema}.aspirantes WHERE telefono=%s",
                    (telefono,)
                )
                creador = cur.fetchone()

                if not creador:
                    print(f"⚠️ [CONSOLIDAR] No se encontró creador con telefono {telefono} en {schema}.aspirantes")
                    return {"status": "skip", "reason": "no_creator"}

                aspirante_id = creador[0]
                print(f"✅ [CONSOLIDAR] aspirante_id={aspirante_id}")

                # -------------------------------
                # 2) Si no hay respuestas, leer de temp
                # -------------------------------
                if respuestas_dict is None:
                    print("📋 [CONSOLIDAR] Leyendo respuestas desde aspirantes_perfil_flujo_temp...")
                    cur.execute(f"""
                        SELECT paso, respuesta
                        FROM {schema}.aspirantes_perfil_flujo_temp
                        WHERE telefono=%s
                        ORDER BY paso ASC
                    """, (telefono,))
                    rows = cur.fetchall()
                    respuestas_dict = {int(p): (r or "") for p, r in rows} if rows else {}
                    print(f"📋 [CONSOLIDAR] Respuestas leídas: {respuestas_dict}")
                else:
                    # Normalizar llaves por si vienen como string
                    respuestas_dict = {
                        (int(k) if isinstance(k, str) and k.isdigit() else k): (str(v) if v is not None else "")
                        for k, v in respuestas_dict.items()
                    }
                    print(f"📋 [CONSOLIDAR] Respuestas recibidas en request: {respuestas_dict}")

                # -------------------------------
                # 3) Procesar respuestas
                # -------------------------------
                print("⚙️ [CONSOLIDAR] Procesando respuestas...")
                datos_update = procesar_respuestas(respuestas_dict)
                print(f"🧠 [CONSOLIDAR] datos_update procesado: {datos_update}")

                # AÑADIMOS teléfono al update de aspirantes_perfil
                datos_update["telefono"] = telefono

                # PENDIENTE REVISAR 11 FEB 2026
                # -------------------------------
                # 4) NUEVO: Insertar aspirante inicial
                # -------------------------------
                # print("🧾 [CONSOLIDAR] Insertando (si aplica) en aspirante_encuesta_inicial...")
                # resp_insert = insertar_aspirante_encuesta_inicial(
                #     telefono=telefono,
                #     datos=datos_update,
                #     tenant_schema=schema
                # )
                # print(f"🧾 [CONSOLIDAR] Resultado inserción aspirante: {resp_insert}")


                # -------------------------------
                # 5) Actualizar nombre_real en aspirantes si hay nombre
                # -------------------------------
                if datos_update.get("nombre"):
                    print(f"🧩 [CONSOLIDAR] Actualizando nombre_real='{datos_update['nombre']}' en aspirantes...")
                    cur.execute(
                        f"UPDATE {schema}.aspirantes SET nombre_real=%s WHERE id=%s",
                        (datos_update["nombre"], aspirante_id)
                    )

                # -------------------------------
                # 6) UPDATE dinámico aspirantes_perfil
                # -------------------------------
                print("🛠️ [CONSOLIDAR] Actualizando aspirantes_perfil...")
                set_clause = ", ".join([f"{k}=%s" for k in datos_update.keys()])
                values = list(datos_update.values())
                values.append(aspirante_id)

                query = f"UPDATE {schema}.aspirantes_perfil SET {set_clause} WHERE aspirante_id=%s"
                print(f"🧾 [CONSOLIDAR] Query UPDATE aspirantes_perfil: {query}")
                print(f"🧾 [CONSOLIDAR] Values (len={len(values)}): {values}")

                cur.execute(query, values)

                conn.commit()
                print(f"✅ [CONSOLIDAR] Actualizado aspirantes_perfil para aspirante_id={aspirante_id} ({telefono})")
                print("🧩 [CONSOLIDAR] ===============================")

        return {"status": "ok"}

    except psycopg2.OperationalError as e:
        print(f"❌ [CONSOLIDAR] Error de conexión BD para {telefono}: {e}")
        traceback.print_exc()
        return {"status": "error", "type": "OperationalError", "error": str(e)}

    except psycopg2.IntegrityError as e:
        print(f"❌ [CONSOLIDAR] Error de integridad BD para {telefono}: {e}")
        traceback.print_exc()
        return {"status": "error", "type": "IntegrityError", "error": str(e)}

    except KeyError as e:
        print(f"❌ [CONSOLIDAR] Clave faltante al consolidar {telefono}: {e}")
        traceback.print_exc()
        return {"status": "error", "type": "KeyError", "error": str(e)}

    except Exception as e:
        print(f"❌ [CONSOLIDAR] Error inesperado al procesar {telefono}: {e}")
        traceback.print_exc()
        return {"status": "error", "type": "Exception", "error": str(e)}


def upsert_encuesta_temp(telefono: str, datos: dict, respuestas_dict: dict | None = None):
    """
    Inserta/actualiza la encuesta del aspirante por telefono.
    datos: ya procesado (nombre, edad, genero, pais, etc.)
    respuestas_dict: opcional (se guarda también completo como json)
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                respuestas_json = json.dumps(respuestas_dict or {}, ensure_ascii=False)

                cur.execute("""
                    INSERT INTO aspirante_encuesta_inicial (
                        telefono, nombre, edad, genero, pais, ciudad,
                        actividad_actual, intencion_trabajo, tiempo_disponible,
                        frecuencia_lives, experiencia_tiktok, tiempo_experiencia,
                        respuestas_json, updated_at
                    )
                    VALUES (
                        %s,%s,%s,%s,%s,%s,
                        %s,%s,%s,
                        %s,%s,%s,
                        %s, NOW()
                    )
                    ON CONFLICT (telefono) DO UPDATE SET
                        nombre = EXCLUDED.nombre,
                        edad = EXCLUDED.edad,
                        genero = EXCLUDED.genero,
                        pais = EXCLUDED.pais,
                        ciudad = EXCLUDED.ciudad,
                        actividad_actual = EXCLUDED.actividad_actual,
                        intencion_trabajo = EXCLUDED.intencion_trabajo,
                        tiempo_disponible = EXCLUDED.tiempo_disponible,
                        frecuencia_lives = EXCLUDED.frecuencia_lives,
                        experiencia_tiktok = EXCLUDED.experiencia_tiktok,
                        tiempo_experiencia = EXCLUDED.tiempo_experiencia,
                        respuestas_json = EXCLUDED.respuestas_json,
                        updated_at = NOW();
                """, (
                    telefono,
                    datos.get("nombre"),
                    datos.get("edad"),
                    datos.get("genero"),
                    datos.get("pais"),
                    datos.get("ciudad"),
                    datos.get("actividad_actual"),
                    datos.get("intencion_trabajo"),
                    datos.get("tiempo_disponible"),
                    datos.get("frecuencia_lives"),
                    datos.get("experiencia_tiktok"),
                    datos.get("tiempo_experiencia"),
                    respuestas_json
                ))

                conn.commit()
                print(f"✅ Encuesta guardada/actualizada en aspirante_encuesta_temp para {telefono}")

    except Exception as e:
        print(f"❌ Error en upsert_encuesta_temp({telefono}): {e}")
        traceback.print_exc()


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


def mensaje_encuesta_final(
    nombre: str | None = None,
    url_info: str | None = None
) -> str:
    nombre_agencia = current_business_name.get()

    saludo = f"¡Gracias, *{nombre}*! 🙌" if nombre else "¡Gracias! 🙌"

    cuerpo = (
        f"✅ {saludo}\n\n"
        f"*{nombre_agencia}* ya recibió tu información y "
        "nuestro equipo la está evaluando.\n\n"
        "⏳ El diagnóstico se enviará en las próximas horas.\n\n"
        "Mientras tanto, puedes conocer cómo funciona el proceso de "
        "evaluación, incorporación y resolver preguntas frecuentes aquí 👇"
    )

    if url_info:
        cuerpo += f"\n\n🔗 {url_info}"

    cuerpo += (
        "\n\n📌 Importante:\n"
        "Este enlace se irá actualizando conforme avance tu proceso."
    )

    return cuerpo


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
        "No es necesario. Contamos con capacitaciones para nuevos aspirantes.\n\n"
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
            enviar_mensaje(numero, "✉️ Escribe el comunicado a enviar a aspirantes/aspirantes:")
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
    Pide usuario TikTok -> confirma nickname -> envía encuesta.
    Si el aspirante está en estado 1 y confirma su identidad,
    se actualiza a estado 2 usando registrar_cambio_estado.
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
        enviar_mensaje(numero, obtener_mensaje_bienvenida_onboarding())
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

        # Nickname real a confirmar
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
                nickname=nickname_tiktok,
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

            aspirante_id = aspirante["id"]

            # Asociar teléfono
            actualizar_telefono_aspirante(aspirante_id, numero)

            # Cambiar de estado 1 -> 2
            try:
                estado_actual = obtener_estado_aspirante(aspirante_id)

                if estado_actual == 1:
                    cambio_hecho = registrar_cambio_estado(
                        aspirante_id=aspirante_id,
                        nuevo_estado_id=2,
                        usuario_id=None,
                        origen_cambio="whatsapp_onboarding",
                        observacion="Aspirante identificado por primera vez en chatbot y enviado a encuesta"
                    )
                    print(f"🔄 Cambio estado 1->2 aspirante={aspirante_id}: {cambio_hecho}")
                else:
                    print(
                        f"ℹ️ Aspirante {aspirante_id} no estaba en estado 1. "
                        f"Estado actual: {estado_actual}"
                    )

            except Exception as e:
                print(f"❌ Error cambiando estado del aspirante {aspirante_id}: {e}")

            # Limpiar temporales
            try:
                redis_delete_temp(numero)
            except Exception:
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
            except Exception:
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
    # PASO 3 – REENVÍO DE LINK (mismo envío que paso 4 de procesar_flujo_aspirante)
    # =====================================================
    if paso == "esperando_inicio_encuesta":
        enviar_inicio_encuesta(numero)
        return {"status": "ok"}

    return None


def _process_new_user_onboardingV1(
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
    Pide usuario TikTok -> confirma nickname -> cambia a estado 2 -> envía portal.
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
        enviar_mensaje(numero, obtener_mensaje_bienvenida_onboarding())
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
                nickname=nickname_tiktok,
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

            aspirante_id = aspirante["id"]

            # Asociar teléfono
            actualizar_telefono_aspirante(aspirante_id, numero)

            # Cambiar de estado 1 -> 2
            try:
                estado_actual = obtener_estado_aspirante(aspirante_id)

                if estado_actual == 1:
                    cambio_hecho = registrar_cambio_estado(
                        aspirante_id=aspirante_id,
                        nuevo_estado_id=2,
                        usuario_id=None,
                        origen_cambio="whatsapp_onboarding",
                        observacion="Aspirante identificado por primera vez en chatbot y enviado a portal"
                    )
                    print(f"🔄 Cambio estado 1->2 aspirante={aspirante_id}: {cambio_hecho}")
                else:
                    print(f"ℹ️ Aspirante {aspirante_id} no estaba en estado 1. Estado actual: {estado_actual}")

            except Exception as e:
                print(f"❌ Error cambiando estado del aspirante {aspirante_id}: {e}")

            # Limpiar temporales
            try:
                redis_delete_temp(numero)
            except Exception:
                pass

            usuarios_temp.pop(numero, None)

            # Enviar portal en vez de encuesta directa
            enviar_inicio_portal(numero)
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
            except Exception:
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
    # PASO 3 – REENVÍO DE LINK (mismo envío que paso 4 de procesar_flujo_aspirante)
    # =====================================================
    if paso == "esperando_inicio_encuesta":
        enviar_inicio_encuesta(numero)
        return {"status": "ok"}

    return None


def _enviar_link_portal_paso4_flujo_aspirante(
    wa_id: str,
    *,
    tipo_portal: str,
    aspirante_id: Optional[int],
    creador_id: Optional[int],
    nombre: str,
    token_cliente: str,
    phone_number_id: str,
    origen: str = "whatsapp",
    plantilla: Optional[str] = None,
    nickname: str = "",
    nombre_real: str = "",
    usuario: str = "",
    nombre_agencia: str = "",
) -> bool:
    """
    Mismo envío que el paso 4 de procesar_flujo_aspirante:
    generar_url_portal_usuario, plantilla configurable, API y guardar_mensaje_nuevo.

    Si plantilla viene con texto (p. ej. mensaje_inicio_encuesta_form), se usa tal cual;
    si no, se usa obtener_plantilla_mensaje_portal(tipo_portal).
    """
    try:
        url_portal = generar_url_portal_usuario(
            tipo_portal=tipo_portal,
            aspirante_id=aspirante_id,
            creador_id=creador_id,
            origen=origen,
        )

        if plantilla is not None and str(plantilla).strip():
            plantilla_final = str(plantilla).strip()
        else:
            plantilla_final = obtener_plantilla_mensaje_portal(tipo_portal)

        try:
            agencia = nombre_agencia or current_business_name.get() or ""
        except LookupError:
            agencia = nombre_agencia or ""

        mensaje_portal = construir_mensaje_portal(
            plantilla=plantilla_final,
            nombre=nombre,
            url_portal=url_portal,
            tipo_portal=tipo_portal,
            nickname=nickname,
            nombre_real=nombre_real,
            usuario=usuario,
            nombre_agencia=agencia,
        )

        if not mensaje_portal.strip():
            raise ValueError("El mensaje del portal quedó vacío.")

        codigo_api, respuesta_api = enviar_mensaje_texto_simple(
            token=token_cliente,
            numero_id=phone_number_id,
            telefono_destino=wa_id,
            texto=mensaje_portal,
        )

        print(
            f"📤 [PORTAL] Envío portal -> código={codigo_api} "
            f"| wa_id={wa_id} "
            f"| tipo_portal={tipo_portal} "
            f"| aspirante_id={aspirante_id} "
            f"| creador_id={creador_id}"
        )

        message_id_meta = None

        if isinstance(respuesta_api, dict):
            mensajes = respuesta_api.get("messages") or []
            if mensajes:
                message_id_meta = mensajes[0].get("id")

        try:
            guardar_mensaje_nuevo(
                telefono=wa_id,
                contenido=mensaje_portal,
                direccion="enviado",
                tipo="text",
                message_id_meta=message_id_meta,
                estado="sent" if codigo_api == 200 else "error",
            )

        except Exception as e:
            print(f"⚠️ [PORTAL] No se pudo guardar log del mensaje enviado: {e}")

        return True

    except Exception as e:
        print(f"❌ [PORTAL] Error enviando link del portal: {e}")
        return True


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


# def mensaje_inicio_encuesta() -> str:
#     nombre_agencia = current_business_name.get() or "nuestra agencia"
#
#     mensaje_db = obtener_configuracion_agencia("mensaje_inicio_encuesta_chat")
#
#     if mensaje_db:
#         return mensaje_db.replace("{nombre_agencia}", nombre_agencia)
#
#     return (
#         f"🔐 *Perfil de creador – {nombre_agencia}*\n\n"
#         f"Queremos conocerte mejor para identificar tu potencial como creador LIVE en TikTok.\n\n"
#         f"⏱️ Te tomará menos de 1 minuto.\n"
#         f"🔒 Tu información será tratada de forma privada y segura.\n\n"
#         "Ingresa aquí para comenzar 👇"
#     )

def enviar_inicio_encuesta(numero: str):
    """
    Envía el acceso al portal tipo aspirante (siempre tipo_portal='aspirante'),
    con el mismo mecanismo de envío que el paso 4 de procesar_flujo_aspirante:
    generar_url_portal_usuario, plantilla configurable, API y guardar_mensaje_nuevo.
    """
    wa_id = (numero or "").strip()
    if not wa_id:
        print("❌ [PORTAL] enviar_inicio_encuesta: número vacío")
        return

    try:
        token_cliente = current_token.get()
        phone_number_id = current_phone_id.get()
    except LookupError as e:
        print(f"❌ [PORTAL] Contexto tenant no disponible en enviar_inicio_encuesta: {e}")
        return

    if not token_cliente or not phone_number_id:
        print("❌ [PORTAL] No hay token o phone_number_id en contexto (enviar_inicio_encuesta).")
        return

    datos = obtener_aspirante_portal_por_telefono(wa_id)
    if not datos:
        print(f"❌ [PORTAL] enviar_inicio_encuesta: sin aspirante para número: {wa_id}")
        try:
            enviar_mensaje_texto_simple(
                token=token_cliente,
                numero_id=phone_number_id,
                telefono_destino=wa_id,
                texto="⚠️ No pudimos identificar tu proceso en este momento.",
            )
        except Exception as e:
            print(f"❌ [PORTAL] Error enviando aviso sin aspirante: {e}")
        return

    aspirante_id = datos.get("aspirante_id")
    nombre = (datos.get("nombre") or "").strip() or "aspirante"

    plantilla = obtener_configuracion_agencia("mensaje_inicio_encuesta_form")

    _enviar_link_portal_paso4_flujo_aspirante(
        wa_id,
        tipo_portal="aspirante",
        aspirante_id=aspirante_id,
        creador_id=None,
        nombre=nombre,
        token_cliente=token_cliente,
        phone_number_id=phone_number_id,
        origen="whatsapp",
        plantilla=plantilla,
        nickname=(datos.get("nickname") or "") or "",
        nombre_real=(datos.get("nombre_real") or "") or "",
        usuario=(datos.get("usuario") or "") or "",
    )
    print(f"🔗 [PORTAL] enviar_inicio_encuesta (portal aspirante) enviado a {wa_id}")


# ⚠️ DEPRECADO: Ya no se usa. Las respuestas se envían todas juntas a /consolidar
# class RespuestaInput(BaseModel):
#     numero: str
#     paso: int
#     respuesta: str

class ConsolidarInput(BaseModel):
    numero: str
    respuestas: Optional[dict] = None  # Diccionario opcional: {1: "Ricardo", 2: "5", 3: "1", ...}
                                      # Si es None, se leen de la tabla aspirantes_perfil_flujo_temp


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

tbox = {"t": time.perf_counter()}

def lap(tag: str):
    now = time.perf_counter()
    print(f"⏱️ [CONSOLIDAR] {tag}: {(now - tbox['t'])*1000:.1f} ms")
    tbox["t"] = now

def guardar_diagnostico_aspirantes_perfil(aspirante_id: int, diagnostico: str):
    if not aspirante_id:
        return

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE aspirantes_perfil
                SET observaciones_finales = %s
                WHERE aspirante_id = %s
                """,
                (diagnostico or "", aspirante_id),
            )

            if cur.rowcount == 0:
                print(f"⚠️ No se actualizaron observaciones: no existe aspirantes_perfil para aspirante_id={aspirante_id}")
            else:
                print(f"✅ Observaciones guardadas en aspirantes_perfil (aspirante_id={aspirante_id})")


def registrar_mensaje_recibido(
    telefono: str,
    message_id_meta: str,
    tipo: str,
    contenido: Optional[str] = None,
    media_url: Optional[str] = None,
) -> None:

    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                # ----------------------------------------
                # 1️⃣ Buscar creador (NO crear si no existe)
                # ----------------------------------------
                cur.execute(
                    """
                    SELECT id
                    FROM aspirantes
                    WHERE telefono = %s
                    LIMIT 1
                    """,
                    (telefono,),
                )
                row = cur.fetchone()

                aspirante_id = row[0] if row else None

                if aspirante_id:
                    print(f"🧾 Mensaje asociado a aspirante_id={aspirante_id}")
                else:
                    print(f"🆕 Mensaje sin creador (aspirante_id=NULL)")

                # ----------------------------------------
                # 2️⃣ Insert mensaje
                # ----------------------------------------
                cur.execute(
                    """
                    INSERT INTO mensajes_whatsapp
                    (
                        usuario_id,
                        telefono,
                        direccion,
                        tipo,
                        contenido,
                        media_url,
                        message_id_meta,
                        estado
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (message_id_meta) DO NOTHING;
                    """,
                    (
                        aspirante_id,        # Puede ser NULL
                        telefono,
                        "recibido",
                        tipo,
                        contenido,
                        media_url,
                        message_id_meta,
                        "received",
                    )
                )

            conn.commit()

        print(f"📥 Mensaje inbound registrado correctamente: {message_id_meta}")

    except Exception as e:
        print(f"❌ Error al registrar mensaje inbound {message_id_meta}: {e}")
        traceback.print_exc()


def obtener_entrevista_id(aspirante_id: int, usuario_evalua: int) -> Optional[dict]:
    """
    Obtiene la entrevista asociada a (aspirante_id, usuario_evalua).
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
                        aspirante_id,
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
                    WHERE aspirante_id = %s
                      AND usuario_evalua = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (aspirante_id, usuario_evalua)
                )
                row = cur.fetchone()

                columnas = [
                    "id",
                    "aspirante_id",
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
                        aspirante_id,
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
                        aspirante_id,
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
                    (aspirante_id, usuario_evalua)
                )

                row = cur.fetchone()
                if not row:
                    print(
                        f"⚠️ No se pudo crear entrevista para aspirante_id={aspirante_id}, usuario_evalua={usuario_evalua}")
                    return None

                return dict(zip(columnas, row))

    except Exception as e:
        print(f"❌ Error en obtener_entrevista_id para aspirante_id={aspirante_id}, usuario_evalua={usuario_evalua}: {e}")
        return None

def enviar_citas_agendadas(numero: str) -> None:
    """
    Envía al aspirante, por WhatsApp, el listado de sus citas agendadas
    y un enlace al portal de citas con token de acceso.

    Usa:
      - buscar_usuario_por_telefono(numero)
      - get_connection_context()
      - agendamientos, agendamientos_participantes
      - crear_token_portal_citas(aspirante_id, responsable_id?, minutos_validez?)
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

    aspirante_id = aspirante.get("id")
    if not aspirante_id:
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
                        COALESCE(ae.nombre, 'programado') AS estado,
                        COALESCE(a.tipo_agendamiento, 'ENTREVISTA') AS tipo_agendamiento,
                        a.link_meet
                    FROM agendamientos a
                    JOIN agendamientos_participantes ap
                      ON ap.agendamiento_id = a.id
                    LEFT JOIN agendamientos_estados ae
                      ON ae.id = a.estado_id
                    WHERE ap.participante_tipo_id = 1
                      AND ap.participante_id = %s
                    ORDER BY a.fecha_inicio ASC
                    """,
                    (aspirante_id,)
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
        token = crear_token_portal_citas(aspirante_id=aspirante_id)
    except Exception as e:
        print(f"❌ Error creando token de portal de citas para aspirante_id={aspirante_id}: {e}")
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



def crear_token_portal_citas(
    aspirante_id: int,
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
                        WHERE aspirante_id = %s
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (aspirante_id,)
                    )
                    row = cur.fetchone()
                    if row and row[0] is not None:
                        responsable_id = row[0]

                # Fallback mínimo si sigue siendo None
                if responsable_id is None:
                    print(
                        f"⚠️ crear_token_portal_citas: sin responsable para aspirante_id={aspirante_id}. "
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
                        aspirante_id,
                        responsable_id,
                        expiracion,
                        usado,
                        creado_en
                    )
                    VALUES (%s, %s, %s, %s, false, NOW() AT TIME ZONE 'UTC')
                    """,
                    (token, aspirante_id, responsable_id, expiracion.replace(tzinfo=None))
                )

                print(
                    f"✅ Token portal citas creado para aspirante_id={aspirante_id}, "
                    f"responsable_id={responsable_id}, token={token}"
                )
                return token

    except Exception as e:
        print(f"❌ Error en crear_token_portal_citas para aspirante_id={aspirante_id}: {e}")
        return None


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



class EstadoEvalInput(BaseModel):
    aspirante_id: int
    estado_evaluacion: str


async def procesar_flujo_aspirante(
    tenant,
    phone_number_id,
    wa_id,
    tipo,
    texto,
    payload_id
):
    """
    Flujo principal para acceso al portal por WhatsApp.

    Atiende:
    - Aspirantes
    - Creadores

    Prioridad:
    1. Verificar si el número pertenece a creador o aspirante.
    2. Si es aspirante, ejecutar interceptor temporal.
    3. Procesar botón de reconexión "Continuar".
    4. Enviar link del portal según tipo_portal.

    Retorna:
    - True  -> si el mensaje fue atendido por este flujo.
    - False -> si no corresponde a aspirante ni creador.
    """

    print(
        f"\n📨 [PORTAL] Recibido de: {wa_id} | "
        f"Tenant: {tenant} | Tipo: {tipo} | "
        f"Payload: {payload_id} | Texto: '{texto}'"
    )

    # ---------------------------------------------------------
    # 1. VALIDAR SI ES CREADOR O ASPIRANTE
    # ---------------------------------------------------------
    try:
        persona = obtener_persona_portal_por_telefono(wa_id)
    except Exception as e:
        print(f"❌ [PORTAL] Error buscando persona por teléfono {wa_id}: {e}")
        return False

    if not persona:
        print(
            f"❌ [PORTAL] El teléfono {wa_id} no está registrado "
            f"como aspirante ni creador."
        )
        return False

    tipo_portal = persona.get("tipo_portal")
    aspirante_id = persona.get("aspirante_id")
    creador_id = persona.get("creador_id")
    nombre = persona.get("nombre") or ""

    print(
        f"✅ [PORTAL] Persona identificada | "
        f"tipo_portal={tipo_portal} | "
        f"aspirante_id={aspirante_id} | "
        f"creador_id={creador_id} | "
        f"nombre={nombre}"
    )

    # ---------------------------------------------------------
    # TOKEN WABA DEL CONTEXTO
    # ---------------------------------------------------------
    token_cliente = current_token.get()

    if not token_cliente:
        print("❌ [PORTAL] No hay token de cliente en contexto.")
        return True

    # ---------------------------------------------------------
    # 2. INTERCEPTOR TEMPORAL SOLO PARA ASPIRANTES
    # ---------------------------------------------------------
    if tipo_portal == "aspirante" and aspirante_id:
        try:
            capturado_por_interceptor = manejar_input_link_tiktok(
                aspirante_id,
                wa_id,
                tipo,
                texto,
                payload_id,
                token_cliente,
                phone_number_id
            )

            if capturado_por_interceptor:
                print("⚡ [ASPIRANTE] Mensaje capturado por interceptor temporal.")
                return True

        except Exception as e:
            print(f"❌ [ASPIRANTE] Error en interceptor temporal: {e}")
            # No detenemos el flujo; sigue al portal.

    # ---------------------------------------------------------
    # 3. BOTÓN DE RECONEXIÓN
    # ---------------------------------------------------------
    try:
        if payload_id:
            payload_limpio = payload_id.strip()
            print(f"🔘 [PORTAL] Payload recibido: '{payload_limpio}'")

            if payload_limpio == "Continuar":
                print(f"✅ [PORTAL] Usuario {wa_id} hizo clic en Continuar.")

                try:
                    await reenviar_ultimo_mensaje(wa_id)
                    print(
                        f"🚀 [PORTAL] Último mensaje reenviado correctamente "
                        f"a {wa_id}"
                    )
                    return True

                except Exception as e:
                    print(f"❌ [PORTAL] Falló el reenvío tras reconexión: {e}")
                    return True

    except Exception as e:
        print(f"❌ [PORTAL] Error procesando botón de reconexión: {e}")
        return True

    # ---------------------------------------------------------
    # 4. ENVIAR LINK DEL PORTAL
    # ---------------------------------------------------------
    _enviar_link_portal_paso4_flujo_aspirante(
        wa_id,
        tipo_portal=tipo_portal,
        aspirante_id=aspirante_id,
        creador_id=creador_id,
        nombre=nombre,
        token_cliente=token_cliente,
        phone_number_id=phone_number_id,
        origen="whatsapp",
    )
    return True


# async def procesar_flujo_aspirante(
#     tenant,
#     phone_number_id,
#     wa_id,
#     tipo,
#     texto,
#     payload_id
# ):
#     """
#     Flujo principal para portal de aspirantes y creadores.
#
#     Prioridad:
#     1. Verificar si el número pertenece a creador o aspirante
#     2. Si es aspirante, ejecutar interceptor temporal
#     3. Procesar botón de reconexión "Continuar"
#     4. Enviar siempre link del portal según tipo_portal
#
#     Retorna:
#     - True  -> si el mensaje fue atendido por este flujo
#     - False -> si no corresponde a aspirante ni creador y debe seguir al flujo general
#     """
#
#     print(
#         f"\n📨 [PORTAL] Recibido de: {wa_id} | "
#         f"Tipo: {tipo} | Payload: {payload_id} | Texto: '{texto}'"
#     )
#
#     # ---------------------------------------------------------
#     # 1. VALIDAR SI ES CREADOR O ASPIRANTE
#     # ---------------------------------------------------------
#     persona = obtener_persona_portal_por_telefono(wa_id)
#
#     if not persona:
#         print(f"❌ [PORTAL] El teléfono {wa_id} no está registrado como aspirante ni creador.")
#         return False
#
#     tipo_portal = persona.get("tipo_portal")
#     aspirante_id = persona.get("aspirante_id")
#     creador_id = persona.get("creador_id")
#     nombre = persona.get("nombre") or ""
#
#     print(
#         f"✅ [PORTAL] Persona identificada | "
#         f"tipo_portal={tipo_portal} | "
#         f"aspirante_id={aspirante_id} | "
#         f"creador_id={creador_id}"
#     )
#
#     # Token del contexto actual WABA
#     token_cliente = current_token.get()
#
#     if not token_cliente:
#         print("❌ [PORTAL] No hay token de cliente en contexto.")
#         return True
#
#     # ---------------------------------------------------------
#     # 2. INTERCEPTOR TEMPORAL SOLO PARA ASPIRANTES
#     # ---------------------------------------------------------
#     if tipo_portal == "aspirante" and aspirante_id:
#         try:
#             capturado_por_interceptor = manejar_input_link_tiktok(
#                 aspirante_id,
#                 wa_id,
#                 tipo,
#                 texto,
#                 payload_id,
#                 token_cliente,
#                 phone_number_id
#             )
#
#             if capturado_por_interceptor:
#                 print("⚡ [ASPIRANTE] Mensaje capturado por interceptor temporal.")
#                 return True
#
#         except Exception as e:
#             print(f"❌ [ASPIRANTE] Error en interceptor temporal: {e}")
#             # No detenemos flujo; sigue al portal
#
#     # ---------------------------------------------------------
#     # 3. BOTÓN DE RECONEXIÓN
#     # ---------------------------------------------------------
#     try:
#         if payload_id:
#             payload_limpio = payload_id.strip()
#             print(f"🔘 [PORTAL] Payload recibido: '{payload_limpio}'")
#
#             if payload_limpio == "Continuar":
#                 print(f"✅ [PORTAL] Usuario {wa_id} hizo clic en Continuar.")
#
#                 try:
#                     await reenviar_ultimo_mensaje(wa_id)
#                     print(f"🚀 [PORTAL] Último mensaje reenviado correctamente a {wa_id}")
#                     return True
#
#                 except Exception as e:
#                     print(f"❌ [PORTAL] Falló el reenvío tras reconexión: {e}")
#                     return True
#
#     except Exception as e:
#         print(f"❌ [PORTAL] Error procesando botón de reconexión: {e}")
#         return True
#
#     # ---------------------------------------------------------
#     # 4. ENVIAR SIEMPRE LINK DEL PORTAL
#     # ---------------------------------------------------------
#     try:
#         url_portal = generar_url_portal_persona(
#             tipo_portal=tipo_portal,
#             aspirante_id=aspirante_id,
#             creador_id=creador_id,
#             origen="whatsapp"
#         )
#
#         plantilla = obtener_configuracion_agencia(
#             clave="mensaje_portal_whatsapp",
#             default=(
#                 "Hola {nombre}, puedes ingresar al siguiente link para consultar tu proceso:\n\n"
#                 "{url_portal}"
#             )
#         )
#
#         mensaje_portal = (
#             plantilla
#             .replace("{nombre}", nombre)
#             .replace("{tipo_portal}", tipo_portal or "")
#             .replace("{url_portal}", url_portal)
#         )
#
#         codigo_api, respuesta_api = enviar_mensaje_texto_simple(
#             token=token_cliente,
#             numero_id=phone_number_id,
#             telefono_destino=wa_id,
#             texto=mensaje_portal
#         )
#
#         print(
#             f"📤 [PORTAL] Envío portal -> código={codigo_api} "
#             f"| wa_id={wa_id} "
#             f"| tipo_portal={tipo_portal} "
#             f"| aspirante_id={aspirante_id} "
#             f"| creador_id={creador_id}"
#         )
#
#         message_id_meta = None
#
#         if isinstance(respuesta_api, dict):
#             mensajes = respuesta_api.get("messages") or []
#             if mensajes:
#                 message_id_meta = mensajes[0].get("id")
#
#         try:
#             guardar_mensaje_nuevo(
#                 telefono=wa_id,
#                 contenido=mensaje_portal,
#                 direccion="enviado",
#                 tipo="text",
#                 message_id_meta=message_id_meta,
#                 estado="sent" if codigo_api == 200 else "error"
#             )
#
#         except Exception as e:
#             print(f"⚠️ [PORTAL] No se pudo guardar log del mensaje enviado: {e}")
#
#         return True
#
#     except Exception as e:
#         print(f"❌ [PORTAL] Error enviando link del portal: {e}")
#         return True


# async def procesar_flujo_aspirante(
#     tenant,
#     phone_number_id,
#     wa_id,
#     tipo,
#     texto,
#     payload_id
# ):
#     """
#     Flujo principal para aspirantes.
#
#     Prioridad:
#     1. Verificar que el número sí pertenece a un aspirante
#     2. Interceptor temporal (Redis / captura de datos esperados)
#     3. Botón de reconexión "Continuar"
#     4. Enviar siempre el link del portal para consulta del proceso
#
#     Retorna:
#     - True  -> si el mensaje fue atendido por este flujo
#     - False -> si no corresponde a un aspirante y debe seguir al flujo general
#     """
#
#     print(
#         f"\n📨 [ASPIRANTE] Recibido de: {wa_id} | "
#         f"Tipo: {tipo} | Payload: {payload_id} | Texto: '{texto}'"
#     )
#
#     # ---------------------------------------------------------
#     # 1. VALIDAR SI ES ASPIRANTE
#     # ---------------------------------------------------------
#     aspirante_id = obtener_aspirante_id_por_telefono(wa_id)
#
#     if not aspirante_id:
#         print(f"❌ [ASPIRANTE] El teléfono {wa_id} no está registrado como aspirante.")
#         return False
#
#     print(f"✅ [ASPIRANTE] Aspirante identificado: {aspirante_id}")
#
#     # Token del contexto actual WABA
#     token_cliente = current_token.get()
#
#     if not token_cliente:
#         print("❌ [ASPIRANTE] No hay token de cliente en contexto.")
#         return True
#
#     # ---------------------------------------------------------
#     # 2. INTERCEPTOR TEMPORAL (ej. link TikTok, dato puntual)
#     # ---------------------------------------------------------
#     try:
#         capturado_por_interceptor = manejar_input_link_tiktok(
#             aspirante_id,
#             wa_id,
#             tipo,
#             texto,
#             payload_id,
#             token_cliente,
#             phone_number_id
#         )
#
#         if capturado_por_interceptor:
#             print("⚡ [ASPIRANTE] Mensaje capturado por interceptor temporal.")
#             return True
#
#     except Exception as e:
#         print(f"❌ [ASPIRANTE] Error en interceptor temporal: {e}")
#         # No detenemos flujo; sigue al portal
#
#     # ---------------------------------------------------------
#     # 3. BOTÓN DE RECONEXIÓN
#     # ---------------------------------------------------------
#     try:
#         if payload_id:
#             payload_limpio = payload_id.strip()
#             print(f"🔘 [ASPIRANTE] Payload recibido: '{payload_limpio}'")
#
#             if payload_limpio == "Continuar":
#                 print(f"✅ [ASPIRANTE] Usuario {wa_id} hizo clic en Continuar.")
#
#                 try:
#                     await reenviar_ultimo_mensaje(wa_id)
#                     print(f"🚀 [ASPIRANTE] Último mensaje reenviado correctamente a {wa_id}")
#                     return True
#
#                 except Exception as e:
#                     print(f"❌ [ASPIRANTE] Falló el reenvío tras reconexión: {e}")
#                     return True
#
#     except Exception as e:
#         print(f"❌ [ASPIRANTE] Error procesando botón de reconexión: {e}")
#         return True
#
#     # ---------------------------------------------------------
#     # 4. ENVIAR SIEMPRE LINK DEL PORTAL
#     # ---------------------------------------------------------
#     try:
#         url_portal = generar_url_portal_para_aspirante(
#             aspirante_id=aspirante_id,
#             origen="whatsapp"
#         )
#
#         mensaje_portal = (
#             "Puedes ingresar al siguiente link para consultar tu proceso:\n"
#             f"{url_portal}"
#         )
#
#         codigo_api, respuesta_api = enviar_mensaje_texto_simple(
#             token=token_cliente,
#             numero_id=phone_number_id,
#             telefono_destino=wa_id,
#             texto=mensaje_portal
#         )
#
#         print(
#             f"📤 [ASPIRANTE] Envío portal -> código={codigo_api} "
#             f"| wa_id={wa_id} | aspirante_id={aspirante_id}"
#         )
#
#         message_id_meta = None
#         if isinstance(respuesta_api, dict):
#             mensajes = respuesta_api.get("messages") or []
#             if mensajes:
#                 message_id_meta = mensajes[0].get("id")
#
#         # Guardar como mensaje enviado
#         try:
#             guardar_mensaje_nuevo(
#                 telefono=wa_id,
#                 contenido=mensaje_portal,
#                 direccion="enviado",
#                 tipo="text",
#                 message_id_meta=message_id_meta,
#                 estado="sent" if codigo_api == 200 else "error"
#             )
#         except Exception as e:
#             print(f"⚠️ [ASPIRANTE] No se pudo guardar log del mensaje enviado: {e}")
#
#         return True
#
#     except Exception as e:
#         print(f"❌ [ASPIRANTE] Error enviando link del portal: {e}")
#         return True


async def procesar_flujo_aspiranteV0(tenant, phone_number_id, wa_id, tipo, texto, payload_id):
    """
    Orquesta la prioridad: 1. Redis (Texto esperado) -> 2. BD (Botones/Menús).
    """
    # [LOG] Inicio
    print(f"\n📨 [INICIO] Recibido de: {wa_id} | Tipo: {tipo} | Payload: {payload_id} | Texto: '{texto}'")

    # 1. Identificación
    aspirante_id = obtener_aspirante_id_por_telefono(wa_id)
    if not aspirante_id:
        print("❌ [DEBUG] Usuario no es aspirante.")
        return False

    token_cliente = current_token.get()

    # =================================================================
    # ⚡ CAPA 1: INTERCEPTOR REDIS
    # =================================================================
    # Verifica si estamos esperando texto de este usuario.
    # Si devuelve True, Redis ya manejó el mensaje (era el link o un error de validación).
    if manejar_input_link_tiktok(aspirante_id, wa_id, tipo, texto, payload_id, token_cliente, phone_number_id):
        return True

    # =================================================================
    # 🐢 CAPA 2: LÓGICA DE NEGOCIO (Base de Datos)
    # =================================================================
    # Si Redis no atrapó el mensaje, consultamos el estado general.
    estado_creador = buscar_estado_creador(aspirante_id)
    if not estado_creador or not estado_creador.get("codigo_estado"):
        print(f"⚠️ [DEBUG] Creador {aspirante_id} sin estado en BD.")
        return False

    estado_actual = estado_creador["codigo_estado"]
    msg_chat_bot = estado_creador.get("mensaje_chatbot_simple") or "Selecciona una opción:"

    print(f"💾 [DEBUG] Estado BD: '{estado_actual}'")

    # --- A. CLIC EN BOTONES (Payloads) ---
    if payload_id:
        # 👇 NUEVO: 1. Aquí atrapas el botón de tu plantilla de reconexión
        # 👇 2. Capturamos "Continuar"
        if payload_id == "Continuar":
            print(f"✅ ¡Reconexión exitosa! El usuario {wa_id} presionó el botón 'Continuar'.")

            try:
                # 👇 3. Usamos 'await' y quitamos el ': str'
                await reenviar_ultimo_mensaje(wa_id)
                print(f"✅ Último mensaje reenviado a {wa_id}")
            except Exception as e:
                print(f"❌ Error reenviando el último mensaje: {e}")

            return True  # Retornamos True para detener el flujo aquí

        # A.1 Acciones del Menú (MENU_*)
        # Aquí caerá MENU_INGRESAR_LINK_TIKTOK y llamará a accion_menu...
        if payload_id.startswith("MENU_"):
            accion_menu_estado_evaluacion(aspirante_id, payload_id, phone_number_id, token_cliente, estado_actual, wa_id)
            return True

        # A.2 Botones de Navegación (Continuar/Opciones)
        if payload_id in ["Continuar", "BTN_ABRIR_MENU_OPCIONES"]:
            Enviar_menu_quickreply(aspirante_id, estado_actual, msg_chat_bot, phone_number_id, token_cliente, wa_id)
            return True

    # --- B. REENGANCHE (Texto suelto) ---
    # Si el usuario escribe "Hola" y no estábamos esperando un link (Redis=False),
    # le mostramos el menú de su estado actual.
    if tipo == "text" and estado_actual:
        print(f"🔄 [DEBUG] Texto sin contexto. Mostrando menú de estado '{estado_actual}'.")
        Enviar_menu_quickreply(aspirante_id, estado_actual, msg_chat_bot, phone_number_id, token_cliente, wa_id)
        return True

    return False

def procesar_flujo_aspiranteV4(tenant, phone_number_id, wa_id, tipo, texto, payload_id):
    # [LOG 1] Inicio absoluto
    print(f"\n📨 [INICIO] Recibido de: {wa_id} | Tipo: {tipo} | Payload: {payload_id} | Texto: '{texto}'")

    """
    Intenta manejar el mensaje basándose en prioridad:
    1. Flujos Temporales (Redis)
    2. Estados de Base de Datos (Postgres)
    """

    # ------------------------------------------------------------------
    # 0. SETUP: IDENTIFICACIÓN BÁSICA
    # ------------------------------------------------------------------
    aspirante_id = obtener_aspirante_id_por_telefono(wa_id)
    if not aspirante_id:
        print("❌ [DEBUG] Usuario no encontrado en tabla aspirantes. Pasando al Bot General.")
        return False  # No es aspirante

    token_cliente = current_token.get()

    # =================================================================
    # ⚡ CAPA 1: INTERCEPTOR REDIS (Alta Prioridad)
    # =================================================================
    # Verifica si el usuario quiere ingresar un link o si ya lo estábamos esperando.
    # Si retorna True, Redis manejó todo y terminamos aquí.

    if manejar_input_link_tiktok(aspirante_id, wa_id, tipo, texto, payload_id, token_cliente, phone_number_id):
        return True

    # =================================================================
    # 🐢 CAPA 2: LÓGICA DE NEGOCIO (Base de Datos)
    # =================================================================
    # Si Redis devolvió False, consultamos el estado persistente en Postgres.

    estado_creador = buscar_estado_creador(aspirante_id)
    if not estado_creador or not estado_creador.get("codigo_estado"):
        print(f"⚠️ [DEBUG] Creador ID {aspirante_id} existe pero NO TIENE estado en BD.")
        return False

    estado_actual = estado_creador["codigo_estado"]
    msg_chat_bot = estado_creador.get("mensaje_chatbot_simple") or "Selecciona una opción:"

    print(f"💾 [DEBUG] ID Creador: {aspirante_id} | Estado BD: '{estado_actual}' (Procesando capa 2)")

    # --- A. CLIC EN BOTONES (Payloads) ---
    if payload_id:
        print(f"🔘 [DEBUG] Procesando botón standard: {payload_id}")

        # A.1 Botones de Navegación/Reenganche
        if payload_id.strip().lower() == "continuar" or payload_id == "BTN_ABRIR_MENU_OPCIONES":
            print("🚀 [DEBUG] Acción: Mostrar menú actual.")
            Enviar_menu_quickreply(aspirante_id, estado_actual, msg_chat_bot, phone_number_id, token_cliente, wa_id)
            return True

        # A.2 Acciones del Menú (MENU_*)
        # Nota: MENU_INGRESAR_LINK_TIKTOK ya fue atrapado por Redis arriba.
        # Aquí llegan el resto de botones (Ver guía, Agendar cita, etc.)
        if payload_id.startswith("MENU_"):
            print("⚡ [DEBUG] Acción: Ejecutar lógica de botón de menú (BD).")
            accion_menu_estado_evaluacion(aspirante_id, payload_id, phone_number_id, token_cliente, estado_actual, wa_id)
            return True

    # --- B. TEXTO GENÉRICO (Reenganche) ---
    # Si escribe texto y no fue capturado por Redis (no es un link esperado),
    # le mostramos el menú de su estado actual.
    if tipo == "text" and estado_actual:
        print(f"🔄 [DEBUG] Texto sin contexto temporal. Mostrando menú de estado '{estado_actual}'.")
        Enviar_menu_quickreply(aspirante_id, estado_actual, msg_chat_bot, phone_number_id, token_cliente, wa_id)
        return True

    print("🔻 [DEBUG] Ningún caso coincidió. Pasando al Bot IA.")
    return False


# --- SUB-FUNCIONES DE ORQUESTACIÓN ---


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
        business_name = cuenta_info["business_name"]

        # 3. Statuses
        statuses = value.get("statuses", [])
        if statuses:
            await _handle_statuses(
                statuses=statuses,
                tenant_name=tenant_name,
                phone_number_id=phone_number_id,
                token_access=token_access,
                business_name=business_name,
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
    # B. LOG EN BD (CON MANEJO ESPECIAL PARA AUDIO)
    # ---------------------------------------------------------
    try:

        # 🔥 AUDIO INBOUND
        if tipo == "audio":

            audio_id = mensaje.get("audio", {}).get("id")

            if audio_id:
                print(f"🎧 Audio recibido. media_id={audio_id}")

                url_cloudinary = descargar_audio(audio_id, token)

                if url_cloudinary:
                    contenido_guardar = url_cloudinary
                    media_url_guardar = url_cloudinary
                else:
                    # Fallback seguro si Cloudinary falla
                    contenido_guardar = "[audio_error_no_subido]"
                    media_url_guardar = None

            else:
                print("⚠️ Audio sin media_id")
                contenido_guardar = "[audio_sin_id]"
                media_url_guardar = None

            registrar_mensaje_recibido(
                telefono=wa_id,
                message_id_meta=mensaje.get("id"),
                tipo="audio",
                contenido=contenido_guardar,
                media_url=media_url_guardar
            )

        # 🔵 OTROS TIPOS (texto, botones, etc.)
        else:

            registrar_mensaje_recibido(
                telefono=wa_id,
                message_id_meta=mensaje.get("id"),
                tipo=tipo,
                contenido=f"{texto or ''} {payload_id or ''}".strip()
            )

    except Exception as e:
        print(f"⚠️ Log Error (No crítico): {e}")

    # ---------------------------------------------------------
    # C. ONBOARDING (PRIMERO)
    # ---------------------------------------------------------
    paso = obtener_flujo(wa_id)
    usuario_bd = buscar_usuario_por_telefono(wa_id)

    print(
        f"🧾 [DEBUG USER LOOKUP] "
        f"tenant={tenant_name} | "
        f"wa_id={wa_id} | "
        f"usuario_encontrado={'SI' if usuario_bd else 'NO'} | "
        f"id={usuario_bd.get('id') if usuario_bd else None} | "
        f"onboarding_completado={usuario_bd.get('onboarding_completado') if usuario_bd else None}"
    )

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
        procesado_aspirante =await procesar_flujo_aspirante(
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
            aspirante_id = obtener_aspirante_id_por_telefono(recipient_id)

            if aspirante_id:
                # 2. Buscar en qué estado se quedó para enviar la plantilla correcta
                estado_actual = buscar_estado_creador(aspirante_id)

                if estado_actual:
                    # 3. Enviar la PLANTILLA correspondiente
                    # Esta función ya la definimos en "Tarea 3" y sabe qué template usar
                    enviar_plantilla_estado_evaluacion(
                        aspirante_id=aspirante_id,
                        estado_evaluacion=estado_actual,
                        phone_id=phone_id,
                        token=token,
                        telefono=recipient_id
                    )
                    print(f"✅ Plantilla de recuperación enviada a {recipient_id}")
                else:
                    print(f"⚠️ No se encontró estado para creador {aspirante_id}, no se pudo enviar plantilla.")
            else:
                print(f"⚠️ El destinatario {recipient_id} no es un aspirante registrado.")

        # ---------------------------------------------------------
        # OTROS ERRORES (Opcional)
        # ---------------------------------------------------------
        elif code == 131026:
            print("⚠️ Mensaje no entregado: Usuario bloqueó al bot o no tiene WhatsApp.")
            # Aquí podrías marcar al usuario como 'inactivo' en tu BD

def obtener_datos_envio_aspirante(aspirante_id):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                sql = """
                    SELECT
                        c.telefono,
                        COALESCE(c.nickname, c.nombre_real) AS nombre,
                        pc.estado_evaluacion
                    FROM aspirantes c
                    INNER JOIN aspirantes_perfil pc
                        ON pc.aspirante_id = c.id
                    WHERE c.id = %s
                    LIMIT 1
                """
                cur.execute(sql, (aspirante_id,))
                row = cur.fetchone()

                if not row:
                    return None

                return {
                    "telefono": row[0],
                    "nombre": row[1],                 # ✅ ahora sí llega al template
                    "codigo_estado": row[2],          # ✅ estado real (texto)
                    "descripcion": row[2],
                    "mensaje_chatbot_simple": row[2] or "Selecciona una opción:",
                    "nombre_template": None,
                }

    except Exception as e:
        print(f"❌ Error al obtener datos de envío para creador {aspirante_id}:", e)
        return None


def obtener_mensaje_por_codigo(codigo_estado):
    """
    Busca el mensaje de texto asociado a un código de estado específico.
    Útil para testing o flujos forzados.
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                return codigo_estado or "Selecciona una opción:"

    except Exception as e:
        print(f"❌ Error al obtener mensaje por código {codigo_estado}:", e)
        return "Error recuperando mensaje."


def actualizar_estado_aspirante_(aspirante_id, nuevo_codigo_estado):
    """
    Actualiza el estado textual de un aspirante en aspirantes_perfil.
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # Actualizar el perfil del creador
                sql_update = """
                             UPDATE aspirantes_perfil
                             SET estado_evaluacion = %s, \
                                 fecha_actualizacion = CURRENT_TIMESTAMP
                             WHERE aspirante_id = %s \
                             """
                cur.execute(sql_update, (nuevo_codigo_estado, aspirante_id))
                conn.commit()
                print(f"✅ Estado actualizado a '{nuevo_codigo_estado}' para creador {aspirante_id}")
                return True

    except Exception as e:
        print(f"❌ Error actualizando estado para creador {aspirante_id}:", e)
        return False


def obtener_aspirante_id_por_telefono(telefono):
    """
    Busca el ID del creador a partir de su número de WhatsApp.
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # Nota: Asegúrate de que el formato del teléfono en BD coincida (con o sin +)
                cur.execute("SELECT id FROM aspirantes WHERE telefono = %s", (telefono,))
                row = cur.fetchone()

                if row:
                    return row[0]
                return None

    except Exception as e:
        print(f"❌ Error buscando creador por teléfono {telefono}:", e)
        return None



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


# --- IMPORTACIONES DEL PROYECTO ---
# Ajusta estas rutas según tu estructura de carpetas real


# Router API


# --- MODELOS DE DATOS (PYDANTIC) ---
class EnvioPruebaRequest(BaseModel):
    aspirante_id: int
    estado_codigo: str
    tenant_name: str  # El Front envía el subdominio (ej: 'webhook_axec') para resolver credenciales


class ActualizarEstadoRequest(BaseModel):
    aspirante_id: int
    estado_codigo: Optional[str] = None


# =============================================================================
# ENDPOINT 1: LISTAR ESTADOS (Para llenar el Select del Front)
# =============================================================================
@router.get("/listar-estados")
def listar_estados_db():
    """
    Obtiene estados posibles (catálogo fijo en código).
    """
    try:
        estados = [
            {"codigo": "post_encuesta_inicial", "descripcion": "Post encuesta inicial"},
            {"codigo": "solicitud_agendamiento_tiktok", "descripcion": "Solicitud agendamiento TikTok"},
            {"codigo": "usuario_agendo_prueba_tiktok", "descripcion": "Usuario agendó prueba TikTok"},
            {"codigo": "solicitud_agendamiento_entrevista", "descripcion": "Solicitud agendamiento entrevista"},
            {"codigo": "usuario_agendo_entrevista", "descripcion": "Usuario agendó entrevista"},
            {"codigo": "solicitud_invitacion_tiktok", "descripcion": "Solicitud invitación TikTok"},
            {"codigo": "invitacion_tiktok_aceptada", "descripcion": "Invitación TikTok aceptada"},
            {"codigo": "solicitud_invitacion_usuario", "descripcion": "Solicitud invitación usuario"},
            {"codigo": "no_apto", "descripcion": "No apto"},
        ]
        return estados
    except Exception as e:
        print(f"❌ Error DB: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener estados")


# =============================================================================
# ENDPOINT 2: OBTENER ESTADO ACTUAL (Consultar Creador)
# =============================================================================
@router.get("/obtener-estado-actual/{aspirante_id}")
def get_estado_actual(aspirante_id: int):
    """
    Consulta el estado actual de un creador con metadata del chatbot.
    """
    try:
        datos = obtener_datos_envio_aspirante(aspirante_id)

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
        exito = actualizar_estado_aspirante_(data.aspirante_id, data.estado_codigo)

        if exito:
            return {"status": "success", "mensaje": f"Estado actualizado a '{data.estado_codigo}'."}
        else:
            raise HTTPException(status_code=400, detail="No se pudo actualizar (verifica ID o código).")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ENDPOINT 4: ENVIAR MENSAJE SEGURO (Multitenant)
# =============================================================================
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

        datos_creador = obtener_datos_envio_aspirante(data.aspirante_id)
        if not datos_creador:
            raise HTTPException(status_code=404, detail=f"Creador ID {data.aspirante_id} no existe")

        telefono_destino = datos_creador["telefono"]
        estado_real = datos_creador["codigo_estado"]

        texto_final = datos_creador.get("mensaje_chatbot_simple") or "Selecciona una opción:"

        # ✅ 4) Verificar ventana 24h
        en_ventana = obtener_status_24hrs(telefono_destino)

        if en_ventana:
            print("✅ En ventana: Enviando MENÚ quick reply")
            Enviar_menu_quickreply(
                aspirante_id=data.aspirante_id,
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



def Enviar_boton_opciones_unico(
    aspirante_id: int,
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



def Enviar_menu_quickreply(aspirante_id, estado_real,msg_chat_bot, phone_id, token, telefono_destino):
    """
    Envía el MENÚ de opciones (quick replies) basado en el estado REAL.
    Se usa desde webhook al hacer clic en MENU_OPCIONES.
    """
    texto_final = msg_chat_bot

    print(f"🏗️ Desplegando menú para estado REAL: {estado_real} (aspirante_id={aspirante_id})")

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



def poblar_scores_creador(aspirante_id: int,telefono_webhook: str):
    """
    Lee los datos crudos de aspirantes_perfil,
    normaliza variables según modelo y guarda en talento_variable_score.
    """

    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                # 1. Variables del modelo
                cur.execute("""
                    SELECT id, categoria_id, campo_db
                    FROM diagnostico_variable
                    WHERE campo_db IS NOT NULL
                """)
                variables_modelo = cur.fetchall()

                # 2. Perfil del creador
                cur.execute("""
                    SELECT apariencia,
                           engagement,
                           calidad_contenido,
                           eval_biografia,
                           metadata_videos,
                           seguidores,
                           likes,
                           videos,
                           duracion_emisiones,
                           dias_emisiones,
                           frecuencia_lives,
                           tiempo_disponible,
                           intencion_trabajo
                    FROM aspirantes_perfil
                    WHERE aspirante_id = %s
                    LIMIT 1
                """, (aspirante_id,))

                row = cur.fetchone()
                if not row:
                    print(f"⚠️ No se encontró el creador {aspirante_id}")
                    return False

                nombres_columnas = [desc[0] for desc in cur.description]
                datos_perfil = dict(zip(nombres_columnas, row))

                registros_a_insertar = []

                # 3. Procesar variables
                for var_id, cat_id, campo_db in variables_modelo:

                    if campo_db not in datos_perfil:
                        continue

                    val_crudo = datos_perfil[campo_db]
                    if val_crudo is None:
                        continue

                    score_final = None

                    # ==============================
                    # CATEGORÍAS YA NORMALIZADAS
                    # ==============================
                    if cat_id in (1, 3, 4):
                        try:
                            score_final = int(round(float(val_crudo)))
                        except Exception:
                            continue

                    # ==============================
                    # CATEGORÍA MERCADO
                    # ==============================
                    elif cat_id == 2:

                        try:
                            val = float(val_crudo)
                        except ValueError:
                            continue

                        s = 0

                        if campo_db == "seguidores":
                            if val < 50:
                                s = 0
                            elif val < 300:
                                s = 1
                            elif val < 500:
                                s = 2
                            elif val < 1000:
                                s = 3
                            elif val <= 5000:
                                s = 4
                            else:
                                s = 5

                        elif campo_db == "videos":
                            if val <= 0:
                                s = 1
                            elif val < 10:
                                s = 2
                            elif val <= 20:
                                s = 3
                            elif val <= 40:
                                s = 4
                            else:
                                s = 5

                        elif campo_db == "likes":
                            if val <= 500:
                                s = 1
                            elif val <= 5000:
                                s = 2
                            elif val <= 15000:
                                s = 3
                            elif val <= 50000:
                                s = 4
                            else:
                                s = 5

                        score_final = s  # ✅ 🔥 CORRECCIÓN IMPORTANTE

                    # ==============================

                    if score_final is not None:
                        score_final = max(1, min(5, score_final))

                        registros_a_insertar.append(
                            (aspirante_id, var_id, score_final)
                        )

                # 4. Guardar en BD
                if registros_a_insertar:

                    cur.execute(
                        "DELETE FROM diagnostico_score_variable WHERE aspirante_id = %s",
                        (aspirante_id,)
                    )

                    query_insert = """
                        INSERT INTO diagnostico_score_variable
                        (aspirante_id, variable_id, valor)
                        VALUES (%s, %s, %s)
                    """

                    cur.executemany(query_insert, registros_a_insertar)
                    conn.commit()

                    print(f"✅ Insertadas {len(registros_a_insertar)} variables.")
                    return True

                else:
                    print("⚠️ No hubo variables válidas.")
                    return False

    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def poblar_categoria_1(aspirante_id: int):
    """
    Población exclusiva de variables con categoria_id = 1
    (Variables que ya vienen normalizadas 1-5).
    """

    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                # 1. Obtener variables categoría 1
                cur.execute("""
                    SELECT id, campo_db
                    FROM diagnostico_variable
                    WHERE categoria_id = 1
                      AND campo_db IS NOT NULL
                """)
                variables = cur.fetchall()

                if not variables:
                    print("⚠️ No hay variables categoría 1 configuradas.")
                    return False

                # 2. Obtener perfil del creador
                cur.execute("""
                    SELECT *
                    FROM aspirantes_perfil
                    WHERE aspirante_id = %s
                    LIMIT 1
                """, (aspirante_id,))

                row = cur.fetchone()
                if not row:
                    print(f"⚠️ No existe creador {aspirante_id}")
                    return False

                columnas = [desc[0] for desc in cur.description]
                datos = dict(zip(columnas, row))

                registros = []

                # 3. Procesar cada variable categoría 1
                for var_id, campo_db in variables:

                    if campo_db not in datos:
                        continue

                    val = datos[campo_db]

                    if val is None:
                        continue

                    try:
                        score = int(round(float(val)))
                    except Exception:
                        continue

                    # 🔒 Asegurar rango 1 - 5
                    score = max(1, min(5, score))

                    registros.append((aspirante_id, var_id, score))

                # 4. Guardar
                if registros:

                    # Borrar solo categoría 1 previamente almacenada
                    cur.execute("""
                        DELETE FROM diagnostico_score_variable
                        WHERE aspirante_id = %s
                          AND variable_id IN (
                              SELECT id FROM diagnostico_variable
                              WHERE categoria_id = 1
                          )
                    """, (aspirante_id,))

                    insert_query = """
                        INSERT INTO diagnostico_score_variable
                        (aspirante_id, variable_id, valor)
                        VALUES (%s, %s, %s)
                    """

                    cur.executemany(insert_query, registros)
                    conn.commit()

                    print(f"✅ Categoría 1 actualizada ({len(registros)} variables)")
                    return True

                else:
                    print("⚠️ No hubo datos válidos categoría 1.")
                    return False

    except Exception as e:
        print(f"❌ Error poblando categoría 1: {e}")
        return False



# ---------------------------------------------------------
# ---------------------------------------------------------
# CONVERTIR INDICATIVO EN PAIS
# CONVERTIR INDICATIVO EN PAIS
# ---------------------------------------------------------
# ---------------------------------------------------------

VARIABLE_PAIS_ID = 20   # id de la variable pais en diagnostico_variable


class ConsolidarInput(BaseModel):
    numero: str
    respuestas: Optional[dict] = None
    meta: Optional[dict] = None
    origen: Optional[str] = None

PAISES_SISTEMA = {
    'AR': {'id': 119, 'nombre': 'Argentina'},
    'BO': {'id': 120, 'nombre': 'Bolivia'},
    'CL': {'id': 121, 'nombre': 'Chile'},
    'CO': {'id': 122, 'nombre': 'Colombia'},
    'CR': {'id': 123, 'nombre': 'Costa Rica'},
    'CU': {'id': 124, 'nombre': 'Cuba'},
    'EC': {'id': 125, 'nombre': 'Ecuador'},
    'SV': {'id': 126, 'nombre': 'El Salvador'},
    'GT': {'id': 127, 'nombre': 'Guatemala'},
    'HN': {'id': 128, 'nombre': 'Honduras'},
    'MX': {'id': 82,  'nombre': 'México'},
    'NI': {'id': 83,  'nombre': 'Nicaragua'},
    'PA': {'id': 84,  'nombre': 'Panamá'},
    'PY': {'id': 85,  'nombre': 'Paraguay'},
    'PE': {'id': 86,  'nombre': 'Perú'},
    'PR': {'id': 87,  'nombre': 'Puerto Rico'},
    'DO': {'id': 88,  'nombre': 'República Dominicana'},
    'UY': {'id': 89,  'nombre': 'Uruguay'},
    'VE': {'id': 90,  'nombre': 'Venezuela'}
}


def obtener_datos_pais(telefono_webhook: str) -> dict:
    try:
        numero_limpio = telefono_webhook.strip()
        if not numero_limpio.startswith('+'):
            numero_limpio = f"+{numero_limpio}"

        parsed_number = phonenumbers.parse(numero_limpio, None)

        if not phonenumbers.is_valid_number(parsed_number):
            return {"error": True, "mensaje": "Número inválido"}

        codigo_iso = region_code_for_number(parsed_number)

        if not codigo_iso:
            codigo_iso = phonenumbers.region_code_for_country_code(parsed_number.country_code)

        if not codigo_iso:
            return {"error": True, "mensaje": "No se pudo detectar el país"}

        indicativo = f"+{parsed_number.country_code}"

        if codigo_iso in PAISES_SISTEMA:
            pais = PAISES_SISTEMA[codigo_iso]
            return {
                "id_pais": pais["id"],
                "nombre_pais": pais["nombre"],
                "indicativo": indicativo,
                "iso": codigo_iso,
                "es_otro": False
            }

        nombre_real = geocoder.country_name_for_number(parsed_number, "es")

        return {
            "id_pais": 91,
            "nombre_pais": "Otro",
            "pais_real_detectado": nombre_real,
            "indicativo": indicativo,
            "iso": codigo_iso,
            "es_otro": True
        }

    except Exception as e:
        return {
            "error": True,
            "mensaje": f"Error procesando número: {str(e)}"
        }

ORIGEN_PORTAL = "portal-aspirante"

@router.post("/consolidar")
def consolidar_perfil_web(
    data: ConsolidarInput,
    background_tasks: BackgroundTasks
):
    try:
        subdominio = current_tenant.get()

        cuenta = obtener_cuenta_por_subdominio(subdominio)
        if not cuenta:
            return JSONResponse(
                {"error": f"No se encontraron credenciales para {subdominio}"},
                status_code=404
            )

        token_cliente = cuenta["access_token"]
        phone_id_cliente = cuenta["phone_number_id"]
        business_name = cuenta.get("business_name", "la agencia")

        current_token.set(token_cliente)
        current_phone_id.set(phone_id_cliente)
        current_business_name.set(business_name)

        # -------------------------------
        # Procesar respuestas
        # -------------------------------
        respuestas_dict = {}

        if data.respuestas:
            for key, valor in data.respuestas.items():
                if isinstance(key, str) and key.isdigit():
                    key = int(key)

                respuestas_dict[key] = str(valor).strip() if valor is not None else ""

        # -------------------------------
        # Detectar país
        # -------------------------------
        datos_pais = obtener_datos_pais(data.numero)

        pais_id = None
        pais_texto = None

        if not datos_pais.get("error"):
            pais_id = datos_pais.get("id_pais")

            if datos_pais.get("es_otro"):
                pais_texto = datos_pais.get("pais_real_detectado") or datos_pais.get("nombre_pais")
            else:
                pais_texto = datos_pais.get("nombre_pais")

            if pais_id is not None:
                respuestas_dict[VARIABLE_PAIS_ID] = str(pais_id)

        # -------------------------------
        # Obtener usuario / aspirante
        # -------------------------------
        try:
            usuario_bd = buscar_usuario_por_telefono(data.numero)

            nombre_usuario = usuario_bd.get("nombre") if usuario_bd else None
            aspirante_id = usuario_bd.get("id") if usuario_bd else None

        except Exception as e:
            print(f"⚠️ Error obteniendo usuario {data.numero}: {e}")
            nombre_usuario = None
            aspirante_id = None

        # -------------------------------
        # Marcar encuesta completada
        # -------------------------------
        marcar_encuesta_completada(data.numero)

        # -------------------------------
        # Guardar diagnóstico
        # -------------------------------
        if aspirante_id and respuestas_dict:
            with get_connection_context() as conn:
                with conn.cursor() as cur:

                    cur.execute("""
                        SELECT id, campo_db
                        FROM diagnostico_variable
                        WHERE migrado = true
                          AND COALESCE(activa, true) = true
                    """)

                    variables = {row[0]: row[1] for row in cur.fetchall()}

                    for pregunta_id, valor in respuestas_dict.items():
                        campo_db = variables.get(pregunta_id)

                        # Guardar score solo si es número
                        if isinstance(valor, str) and valor.isdigit():
                            valor_int = int(valor)

                            cur.execute("""
                                INSERT INTO diagnostico_score_variable
                                    (aspirante_id, variable_id, valor_id)
                                VALUES (%s, %s, %s)
                                ON CONFLICT (aspirante_id, variable_id)
                                DO UPDATE SET
                                    valor_id = EXCLUDED.valor_id
                            """, (
                                aspirante_id,
                                pregunta_id,
                                valor_int
                            ))

                        # Actualizar aspirantes_perfil según campo_db
                        if campo_db:
                            if not campo_db.replace("_", "").isalnum():
                                continue

                            query = f"""
                                UPDATE aspirantes_perfil
                                SET {campo_db} = %s
                                WHERE aspirante_id = %s
                            """

                            cur.execute(query, (valor, aspirante_id))

                            if campo_db == "nombre":
                                nombre_usuario = valor

                    # Guardar pais_texto
                    if pais_texto:
                        cur.execute("""
                            UPDATE aspirantes_perfil
                            SET pais_texto = %s
                            WHERE aspirante_id = %s
                        """, (pais_texto, aspirante_id))

                    # Guardar zona_horaria
                    zona_horaria = None
                    if data.meta and isinstance(data.meta, dict):
                        zona_horaria = data.meta.get("zona_horaria")

                    if zona_horaria:
                        cur.execute("""
                            UPDATE aspirantes_perfil
                            SET zona_horaria = %s
                            WHERE aspirante_id = %s
                        """, (zona_horaria, aspirante_id))

                    # -------------------------------
                    # Guardar trazabilidad encuesta inicial
                    # -------------------------------
                    cur.execute("""
                        INSERT INTO aspirantes_encuesta_inicial (
                            aspirante_id,
                            respuestas_json,
                            fecha_inicio,
                            fecha_fin,
                            completada,
                            abandonada,
                            preguntas_respondidas,
                            sincronizado,
                            fecha_sincronizacion,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            %s,
                            %s::jsonb,
                            now(),
                            now(),
                            true,
                            false,
                            %s,
                            true,
                            now(),
                            now(),
                            now()
                        )
                    """, (
                        aspirante_id,
                        json.dumps(respuestas_dict, ensure_ascii=False),
                        len(respuestas_dict)
                    ))

                    conn.commit()

            # -------------------------------
            # Pasar aspirante a Evaluación
            # -------------------------------
            registrar_cambio_estado(
                aspirante_id=aspirante_id,
                nuevo_estado_id=3,
                usuario_id=None,
                origen_cambio="encuesta_link",
                observacion="Aspirante pasa a Evaluación al completar la encuesta inicial"
            )

        # -------------------------------
        # URL del portal con token universal
        # -------------------------------
        portal_data = None
        url_info = None

        if aspirante_id:
            portal_data = generar_url_portal(
                tipo_portal="aspirante",
                aspirante_id=aspirante_id,
                creador_id=None,
                origen="encuesta"
            )

            url_info = portal_data["url"]

        # -------------------------------
        # Mensaje final
        # -------------------------------
        mensaje_final = mensaje_encuesta_final(
            nombre=nombre_usuario,
            url_info=url_info
        )

        origen = (data.origen or "").strip().lower()
        enviar_mensaje = origen != ORIGEN_PORTAL

        if enviar_mensaje:
            background_tasks.add_task(
                enviar_mensaje_whatsapp_texto,
                data.numero,
                mensaje_final,
                token_cliente,
                phone_id_cliente
            )
            print(f"✅ Perfil consolidado y mensaje enviado a {data.numero}")
        else:
            print(f"✅ Perfil consolidado sin envío de mensaje (origen={origen})")

        return {
            "ok": True,
            "msg": "Perfil consolidado correctamente",
            "aspirante_id": aspirante_id,
            "pais_texto": pais_texto,
            "zona_horaria": data.meta.get("zona_horaria") if data.meta else None,
            "url_portal": url_info,
            "mensaje_enviado": enviar_mensaje
        }

    except Exception as e:
        print(f"❌ Error en consolidar_perfil_web: {e}")

        return JSONResponse(
            {
                "error": "Error al consolidar el perfil",
                "detail": str(e)
            },
            status_code=500
        )


# @router.post("/consolidar")
# def consolidar_perfil_web(
#     data: ConsolidarInput,
#     background_tasks: BackgroundTasks
# ):
#     try:
#         subdominio = current_tenant.get()
#
#         cuenta = obtener_cuenta_por_subdominio(subdominio)
#         if not cuenta:
#             return JSONResponse(
#                 {"error": f"No se encontraron credenciales para {subdominio}"},
#                 status_code=404
#             )
#
#         token_cliente = cuenta["access_token"]
#         phone_id_cliente = cuenta["phone_number_id"]
#         business_name = cuenta.get("business_name", "la agencia")
#
#         current_token.set(token_cliente)
#         current_phone_id.set(phone_id_cliente)
#         current_business_name.set(business_name)
#
#         # -------------------------------
#         # Procesar respuestas
#         # -------------------------------
#         respuestas_dict = {}
#
#         if data.respuestas:
#             for key, valor in data.respuestas.items():
#                 if isinstance(key, str) and key.isdigit():
#                     key = int(key)
#
#                 respuestas_dict[key] = str(valor).strip() if valor is not None else ""
#
#         # -------------------------------
#         # Detectar país
#         # -------------------------------
#         datos_pais = obtener_datos_pais(data.numero)
#
#         pais_id = None
#         pais_texto = None
#
#         if not datos_pais.get("error"):
#             pais_id = datos_pais.get("id_pais")
#
#             if datos_pais.get("es_otro"):
#                 pais_texto = datos_pais.get("pais_real_detectado") or datos_pais.get("nombre_pais")
#             else:
#                 pais_texto = datos_pais.get("nombre_pais")
#
#             if pais_id is not None:
#                 respuestas_dict[VARIABLE_PAIS_ID] = str(pais_id)
#
#         # -------------------------------
#         # Obtener usuario
#         # -------------------------------
#         try:
#             usuario_bd = buscar_usuario_por_telefono(data.numero)
#
#             nombre_usuario = usuario_bd.get("nombre") if usuario_bd else None
#             aspirante_id = usuario_bd.get("id") if usuario_bd else None
#
#         except Exception as e:
#             print(f"⚠️ Error obteniendo usuario {data.numero}: {e}")
#             nombre_usuario = None
#             aspirante_id = None
#
#         # -------------------------------
#         # Marcar encuesta completada
#         # -------------------------------
#         marcar_encuesta_completada(data.numero)
#
#         # -------------------------------
#         # Guardar diagnóstico
#         # -------------------------------
#         if aspirante_id and respuestas_dict:
#             with get_connection_context() as conn:
#                 cur = conn.cursor()
#
#                 cur.execute("""
#                     SELECT id, campo_db
#                     FROM diagnostico_variable
#                     WHERE migrado = true
#                       AND COALESCE(activa, true) = true
#                 """)
#
#                 variables = {row[0]: row[1] for row in cur.fetchall()}
#
#                 for pregunta_id, valor in respuestas_dict.items():
#                     campo_db = variables.get(pregunta_id)
#
#                     # Guardar score solo si es número
#                     if valor.isdigit():
#                         valor_int = int(valor)
#
#                         cur.execute("""
#                             INSERT INTO diagnostico_score_variable
#                                 (aspirante_id, variable_id, valor_id)
#                             VALUES (%s, %s, %s)
#                             ON CONFLICT (aspirante_id, variable_id)
#                             DO UPDATE SET
#                                 valor_id = EXCLUDED.valor_id
#                         """, (
#                             aspirante_id,
#                             pregunta_id,
#                             valor_int
#                         ))
#
#                     # Actualizar aspirantes_perfil según campo_db
#                     if campo_db:
#                         if not campo_db.replace("_", "").isalnum():
#                             continue
#
#                         query = f"""
#                             UPDATE aspirantes_perfil
#                             SET {campo_db} = %s
#                             WHERE aspirante_id = %s
#                         """
#
#                         cur.execute(query, (valor, aspirante_id))
#
#                         if campo_db == "nombre":
#                             nombre_usuario = valor
#
#                 # Guardar pais_texto
#                 if pais_texto:
#                     cur.execute("""
#                         UPDATE aspirantes_perfil
#                         SET pais_texto = %s
#                         WHERE aspirante_id = %s
#                     """, (pais_texto, aspirante_id))
#
#                 # Guardar zona_horaria
#                 zona_horaria = None
#                 if data.meta and isinstance(data.meta, dict):
#                     zona_horaria = data.meta.get("zona_horaria")
#
#                 if zona_horaria:
#                     cur.execute("""
#                         UPDATE aspirantes_perfil
#                         SET zona_horaria = %s
#                         WHERE aspirante_id = %s
#                     """, (zona_horaria, aspirante_id))
#
#                 # -------------------------------
#                 # Guardar trazabilidad encuesta inicial
#                 # -------------------------------
#                 cur.execute("""
#                     INSERT INTO aspirantes_encuesta_inicial (
#                         aspirante_id,
#                         respuestas_json,
#                         fecha_inicio,
#                         fecha_fin,
#                         completada,
#                         abandonada,
#                         preguntas_respondidas,
#                         sincronizado,
#                         fecha_sincronizacion,
#                         created_at,
#                         updated_at
#                     )
#                     VALUES (
#                         %s,
#                         %s::jsonb,
#                         now(),
#                         now(),
#                         true,
#                         false,
#                         %s,
#                         true,
#                         now(),
#                         now(),
#                         now()
#                     )
#                 """, (
#                     aspirante_id,
#                     json.dumps(respuestas_dict, ensure_ascii=False),
#                     len(respuestas_dict)
#                 ))
#
#                 conn.commit()
#
#             # -------------------------------
#             # Pasar aspirante a Evaluación
#             # -------------------------------
#             registrar_cambio_estado(
#                 aspirante_id=aspirante_id,
#                 nuevo_estado_id=3,  # Evaluación
#                 usuario_id=None,
#                 origen_cambio="encuesta_link",
#                 observacion="Aspirante pasa a Evaluación al completar la encuesta inicial"
#             )
#
#         # -------------------------------
#         # URL del portal con token
#         # -------------------------------
#         portal_data = generar_url_portal(
#             aspirante_id=aspirante_id,
#             origen="encuesta"
#         ) if aspirante_id else None
#
#         url_info = portal_data["url"] if portal_data else None
#
#         # -------------------------------
#         # Mensaje final
#         # -------------------------------
#         mensaje_final = mensaje_encuesta_final(
#             nombre=nombre_usuario,
#             url_info=url_info
#         )
#
#         origen = (data.origen or "").strip().lower()
#         enviar_mensaje = origen != ORIGEN_PORTAL
#
#         if enviar_mensaje:
#             background_tasks.add_task(
#                 enviar_mensaje_whatsapp_texto,
#                 data.numero,
#                 mensaje_final,
#                 token_cliente,
#                 phone_id_cliente
#             )
#             print(f"✅ Perfil consolidado y mensaje enviado a {data.numero}")
#         else:
#             print(f"✅ Perfil consolidado sin envío de mensaje (origen={origen})")
#
#         return {
#             "ok": True,
#             "msg": "Perfil consolidado correctamente",
#             "pais_texto": pais_texto,
#             "zona_horaria": data.meta.get("zona_horaria") if data.meta else None,
#             "mensaje_enviado": enviar_mensaje
#         }
#
#     except Exception as e:
#         print(f"❌ Error en consolidar_perfil_web: {e}")
#
#         return JSONResponse(
#             {"error": "Error al consolidar el perfil"},
#             status_code=500
#         )



class IniciarEncuestaInput(BaseModel):
    numero: str
    meta: Optional[Dict[str, Any]] = None


@router.post("/encuesta/iniciar")
def iniciar_encuesta_inicial(data: IniciarEncuestaInput):
    try:
        # -------------------------------
        # Obtener usuario
        # -------------------------------
        try:
            usuario_bd = buscar_usuario_por_telefono(data.numero)
            aspirante_id = usuario_bd.get("id") if usuario_bd else None
        except Exception as e:
            print(f"⚠️ Error obteniendo usuario {data.numero}: {e}")
            aspirante_id = None

        if not aspirante_id:
            return JSONResponse(
                {"error": "No se encontró aspirante para ese número"},
                status_code=404
            )

        # -------------------------------
        # Guardar zona horaria si viene
        # -------------------------------
        zona_horaria = None
        if data.meta and isinstance(data.meta, dict):
            zona_horaria = data.meta.get("zona_horaria")

        if zona_horaria:
            try:
                with get_connection_context() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE aspirantes_perfil
                            SET zona_horaria = %s
                            WHERE aspirante_id = %s
                            """,
                            (zona_horaria, aspirante_id)
                        )
                    conn.commit()
            except Exception as e:
                print(f"⚠️ Error guardando zona_horaria para aspirante {aspirante_id}: {e}")

        # -------------------------------
        # Habilitar trazabilidad de encuesta
        # -------------------------------
        ok = habilitar_trazabilidad_encuesta_inicial(
            aspirante_id=aspirante_id,
            respuestas_json={},
            preguntas_respondidas=0
        )

        if not ok:
            return JSONResponse(
                {"error": "No se pudo iniciar la encuesta"},
                status_code=500
            )

        return {
            "ok": True,
            "msg": "Encuesta iniciada correctamente",
            "aspirante_id": aspirante_id,
            "zona_horaria": zona_horaria
        }

    except Exception as e:
        print(f"❌ Error en iniciar_encuesta_inicial: {e}")
        return JSONResponse(
            {"error": "Error al iniciar la encuesta"},
            status_code=500
        )






# @router.post("/consolidar")
# def consolidar_perfil_web(
#     data: ConsolidarInput,
#     background_tasks: BackgroundTasks
# ):
#     try:
#         subdominio = current_tenant.get()
#
#         cuenta = obtener_cuenta_por_subdominio(subdominio)
#         if not cuenta:
#             return JSONResponse(
#                 {"error": f"No se encontraron credenciales para {subdominio}"},
#                 status_code=404
#             )
#
#         token_cliente = cuenta["access_token"]
#         phone_id_cliente = cuenta["phone_number_id"]
#         business_name = cuenta.get("business_name", "la agencia")
#
#         current_token.set(token_cliente)
#         current_phone_id.set(phone_id_cliente)
#         current_business_name.set(business_name)
#
#         # -------------------------------
#         # Procesar respuestas
#         # -------------------------------
#         respuestas_dict = {}
#
#         if data.respuestas:
#             for key, valor in data.respuestas.items():
#                 if isinstance(key, str) and key.isdigit():
#                     key = int(key)
#
#                 respuestas_dict[key] = str(valor).strip() if valor is not None else ""
#
#         # -------------------------------
#         # Detectar país
#         # -------------------------------
#         datos_pais = obtener_datos_pais(data.numero)
#
#         pais_id = None
#         pais_texto = None
#
#         if not datos_pais.get("error"):
#             pais_id = datos_pais.get("id_pais")
#
#             if datos_pais.get("es_otro"):
#                 pais_texto = datos_pais.get("pais_real_detectado") or datos_pais.get("nombre_pais")
#             else:
#                 pais_texto = datos_pais.get("nombre_pais")
#
#             if pais_id is not None:
#                 respuestas_dict[VARIABLE_PAIS_ID] = str(pais_id)
#
#         # -------------------------------
#         # Obtener usuario
#         # -------------------------------
#         try:
#             usuario_bd = buscar_usuario_por_telefono(data.numero)
#
#             nombre_usuario = usuario_bd.get("nombre") if usuario_bd else None
#             aspirante_id = usuario_bd.get("id") if usuario_bd else None
#
#         except Exception as e:
#             print(f"⚠️ Error obteniendo usuario {data.numero}: {e}")
#             nombre_usuario = None
#             aspirante_id = None
#
#         # -------------------------------
#         # Marcar encuesta completada
#         # -------------------------------
#         marcar_encuesta_completada(data.numero)
#
#         # -------------------------------
#         # Guardar diagnóstico
#         # -------------------------------
#         if aspirante_id and respuestas_dict:
#             with get_connection_context() as conn:
#                 cur = conn.cursor()
#
#                 cur.execute("""
#                     SELECT id, campo_db
#                     FROM diagnostico_variable
#                     WHERE migrado = true
#                       AND COALESCE(activa, true) = true
#                 """)
#
#                 variables = {row[0]: row[1] for row in cur.fetchall()}
#
#                 for pregunta_id, valor in respuestas_dict.items():
#                     campo_db = variables.get(pregunta_id)
#
#                     # Guardar score solo si es número
#                     if valor.isdigit():
#                         valor_int = int(valor)
#
#                         cur.execute("""
#                             INSERT INTO diagnostico_score_variable
#                                 (aspirante_id, variable_id, valor_id)
#                             VALUES (%s, %s, %s)
#                             ON CONFLICT (aspirante_id, variable_id)
#                             DO UPDATE SET
#                                 valor_id = EXCLUDED.valor_id
#                         """, (
#                             aspirante_id,
#                             pregunta_id,
#                             valor_int
#                         ))
#
#                     # Actualizar aspirantes_perfil según campo_db
#                     if campo_db:
#                         if not campo_db.replace("_", "").isalnum():
#                             continue
#
#                         query = f"""
#                             UPDATE aspirantes_perfil
#                             SET {campo_db} = %s
#                             WHERE aspirante_id = %s
#                         """
#
#                         cur.execute(query, (valor, aspirante_id))
#
#                         if campo_db == "nombre":
#                             nombre_usuario = valor
#
#                 # Guardar pais_texto
#                 if pais_texto:
#                     cur.execute("""
#                         UPDATE aspirantes_perfil
#                         SET pais_texto = %s
#                         WHERE aspirante_id = %s
#                     """, (pais_texto, aspirante_id))
#
#                 # Guardar zona_horaria
#                 zona_horaria = None
#                 if data.meta and isinstance(data.meta, dict):
#                     zona_horaria = data.meta.get("zona_horaria")
#
#                 if zona_horaria:
#                     cur.execute("""
#                         UPDATE aspirantes_perfil
#                         SET zona_horaria = %s
#                         WHERE aspirante_id = %s
#                     """, (zona_horaria, aspirante_id))
#
#                 conn.commit()
#
#         # -------------------------------
#         # URL del portal con token
#         # -------------------------------
#
#         portal_data = generar_url_portal(
#             aspirante_id=aspirante_id,
#             origen="encuesta"
#         ) if aspirante_id else None
#
#         url_info = portal_data["url"] if portal_data else None
#
#         # -------------------------------
#         # Mensaje final
#         # -------------------------------
#         mensaje_final = mensaje_encuesta_final(
#             nombre=nombre_usuario,
#             url_info=url_info
#         )
#
#         background_tasks.add_task(
#             enviar_mensaje_whatsapp_texto,
#             data.numero,
#             mensaje_final,
#             token_cliente,
#             phone_id_cliente
#         )
#
#         print(f"✅ Perfil consolidado y mensaje enviado a {data.numero}")
#
#         return {
#             "ok": True,
#             "msg": "Perfil consolidado correctamente",
#             "pais_texto": pais_texto,
#             "zona_horaria": data.meta.get("zona_horaria") if data.meta else None
#         }
#
#     except Exception as e:
#         print(f"❌ Error en consolidar_perfil_web: {e}")
#
#         return JSONResponse(
#             {"error": "Error al consolidar el perfil"},
#             status_code=500
#         )

# def enviar_inicio_portal(numero: str, aspirante_id: int):
#     tenant_name = current_tenant.get() or "default"
#
#     portal_data = generar_url_portal(
#         aspirante_id=aspirante_id,
#         origen="whatsapp_onboarding"
#     )
#
#     url_portal = portal_data["url"]
#
#     mensaje = (
#         f"{mensaje_inicio_encuesta()}\n\n"
#         "🔗 *Ingresa aquí a tu portal:*\n"
#         f"{url_portal}\n\n"
#         "Desde allí podrás completar tu encuesta, revisar preguntas frecuentes "
#         "y conocer el proceso general.\n\n"
#         "Puedes hacerlo desde tu celular o computadora."
#     )
#
#     enviar_mensaje(numero, mensaje)
#
#     print(f"🔗 Enviado portal de onboarding a {numero}: {url_portal}")


# def _process_new_user_onboarding(
#     mensaje: dict,
#     numero: str,
#     texto: str,
#     texto_lower: str,
#     payload: str,
#     paso: Optional[str | int],
#     tenant_name: str,
#     phone_id: str = None,
#     token: str = None
# ) -> Optional[dict]:
#     """
#     Flujo de onboarding para nuevos usuarios vía WhatsApp.
#     Pide usuario TikTok → confirma nickname → envía encuesta.
#     """
#
#     tipo = mensaje.get("type")
#
#     # -----------------------------------------------------
#     # VALIDACIÓN DE TIPO DE MENSAJE
#     # -----------------------------------------------------
#     if tipo not in ["text", "interactive"]:
#         return None
#
#     # Extraer payload si es botón
#     if not payload and tipo == "interactive":
#         payload = (
#             mensaje.get("interactive", {})
#             .get("button_reply", {})
#             .get("id")
#         )
#
#     # -----------------------------------------------------
#     # VALIDACIÓN DE PASO (ANTI-CORRUPCIÓN DE FLUJO)
#     # -----------------------------------------------------
#     pasos_validos = [
#         None,
#         "esperando_usuario_tiktok",
#         "confirmando_nickname",
#         "esperando_inicio_encuesta",
#     ]
#
#     if paso not in pasos_validos:
#         print(f"⚠️ Reiniciando flujo para {numero}, paso inválido: {paso}")
#         eliminar_flujo(numero)
#         paso = None
#
#     # =====================================================
#     # PASO 0 – INICIO
#     # =====================================================
#     if paso is None:
#         enviar_mensaje(
#             numero,
#             "¡Hola! 👋 Bienvenido.\n"
#             "Para comenzar, por favor escribe tu *usuario de TikTok* "
#             "(sin @)."
#         )
#         actualizar_flujo(numero, "esperando_usuario_tiktok")
#         return {"status": "ok"}
#
#     # =====================================================
#     # PASO 1 – ESPERANDO USUARIO TIKTOK
#     # =====================================================
#     if paso == "esperando_usuario_tiktok":
#
#         if tipo != "text":
#             enviar_mensaje(numero, "✍️ Por favor escribe tu usuario de TikTok.")
#             return {"status": "ok"}
#
#         input_usuario = texto.strip()
#         aspirante = buscar_aspirante_por_usuario_tiktok(input_usuario)
#
#         if not aspirante:
#             enviar_mensaje(
#                 numero,
#                 "❌ No encontramos ese usuario.\n"
#                 "Verifica e inténtalo nuevamente."
#             )
#             return {"status": "ok"}
#
#         # 🔑 NICKNAME REAL (LO ÚNICO QUE SE CONFIRMA)
#         nickname_tiktok = (
#             aspirante.get("usuario_tiktok")
#             or aspirante.get("nickname")
#         )
#
#         if not nickname_tiktok:
#             enviar_mensaje(
#                 numero,
#                 "⚠️ Encontramos el perfil, pero no pudimos obtener "
#                 "el usuario de TikTok. Escríbelo nuevamente."
#             )
#             return {"status": "ok"}
#
#         # Guardar aspirante temporal
#         try:
#             redis_set_temp(numero, aspirante, ttl=900)
#         except Exception as e:
#             print(f"⚠️ Redis falló, usando memoria: {e}")
#             usuarios_temp[numero] = aspirante
#
#         # Confirmación con botones
#         if phone_id and token:
#             enviar_confirmacion_interactiva(
#                 numero=numero,
#                 nickname=nickname_tiktok,  # ✅ SIEMPRE EL NICKNAME
#                 phone_id=phone_id,
#                 token=token
#             )
#         else:
#             enviar_mensaje(
#                 numero,
#                 f"Encontramos el usuario: *{nickname_tiktok}*.\n"
#                 "¿Eres tú? (Responde SÍ o NO)"
#             )
#
#         actualizar_flujo(numero, "confirmando_nickname")
#         return {"status": "ok"}
#
#     # =====================================================
#     # PASO 2 – CONFIRMANDO NICKNAME
#     # =====================================================
#     if paso == "confirmando_nickname":
#
#         es_si = (
#             payload == "BTN_CONFIRM_YES"
#             or (tipo == "text" and texto_lower in ["si", "sí", "s", "y", "yes"])
#         )
#
#         es_no = (
#             payload == "BTN_CONFIRM_NO"
#             or (tipo == "text" and texto_lower in ["no", "n"])
#         )
#
#         # -------------------------
#         # CONFIRMA QUE SÍ
#         # -------------------------
#         if es_si:
#             aspirante = redis_get_temp(numero) or usuarios_temp.get(numero)
#
#             if not aspirante:
#                 enviar_mensaje(
#                     numero,
#                     "⏳ La sesión expiró. "
#                     "Por favor escribe nuevamente tu usuario de TikTok."
#                 )
#                 actualizar_flujo(numero, "esperando_usuario_tiktok")
#                 return {"status": "ok"}
#
#             # Asociar teléfono
#             actualizar_telefono_aspirante(aspirante["id"], numero)
#
#             # Limpiar temporales
#             try:
#                 redis_delete_temp(numero)
#             except:
#                 pass
#             usuarios_temp.pop(numero, None)
#
#             # Enviar encuesta
#             enviar_inicio_encuesta(numero)
#             actualizar_flujo(numero, "esperando_inicio_encuesta")
#             return {"status": "ok"}
#
#         # -------------------------
#         # CONFIRMA QUE NO
#         # -------------------------
#         if es_no:
#             enviar_mensaje(
#                 numero,
#                 "👌 Entendido.\n"
#                 "Por favor escribe nuevamente tu *usuario de TikTok* correcto."
#             )
#
#             try:
#                 redis_delete_temp(numero)
#             except:
#                 pass
#             usuarios_temp.pop(numero, None)
#
#             actualizar_flujo(numero, "esperando_usuario_tiktok")
#             return {"status": "ok"}
#
#         # -------------------------
#         # INPUT INVÁLIDO
#         # -------------------------
#         enviar_mensaje(
#             numero,
#             "⚠️ No te entendí.\n"
#             "Por favor selecciona una de las opciones."
#         )
#         return {"status": "ok"}
#
#     # =====================================================
#     # PASO 3 – REENVÍO DE LINK DE ENCUESTA
#     # =====================================================
#     if paso == "esperando_inicio_encuesta":
#         tenant_actual = tenant_name or current_tenant.get() or "default"
#         url_web = construir_url_actualizar_perfil(
#             numero,
#             tenant_name=tenant_actual
#         )
#
#         enviar_mensaje(
#             numero,
#             "📋 Para comenzar la encuesta, haz clic aquí:\n\n"
#             f"{url_web}\n\n"
#             "Puedes hacerlo desde tu celular o computadora."
#         )
#         return {"status": "ok"}
#
#     return None




# def enviar_inicio_portal(numero: str):
#     """
#     Envía el acceso al portal por WhatsApp.
#
#     Detecta automáticamente si el número es:
#     - Aspirante
#     - Creador
#     """
#
#     try:
#         print(f"\n📤 [PORTAL] Enviando inicio a {numero}")
#
#         # ---------------------------------------------------------
#         # 1. IDENTIFICAR PERSONA
#         # ---------------------------------------------------------
#         persona = obtener_persona_portal_por_telefono(numero)
#
#         if not persona:
#             print(f"❌ [PORTAL] Número no registrado: {numero}")
#             return False
#
#         tipo_portal = persona.get("tipo_portal")
#         aspirante_id = persona.get("aspirante_id")
#         creador_id = persona.get("creador_id")
#         nombre = persona.get("nombre") or ""
#
#         print(
#             f"✅ [PORTAL] Detectado -> tipo={tipo_portal} | "
#             f"aspirante_id={aspirante_id} | creador_id={creador_id}"
#         )
#
#         # ---------------------------------------------------------
#         # 2. GENERAR URL PORTAL
#         # ---------------------------------------------------------
#         portal_data = generar_url_portal(
#             tipo_portal=tipo_portal,
#             aspirante_id=aspirante_id,
#             creador_id=creador_id,
#             origen="whatsapp_onboarding"
#         )
#
#         url_portal = portal_data["url"]
#
#         # ---------------------------------------------------------
#         # 3. MENSAJE CONFIGURABLE
#         # ---------------------------------------------------------
#         plantilla = obtener_configuracion_agencia(
#             clave="mensaje_portal_whatsapp",
#             default=(
#                 "Hola {nombre}, puedes ingresar al siguiente link para consultar tu proceso:\n\n"
#                 "{url_portal}"
#             )
#         )
#
#         mensaje = (
#             plantilla
#             .replace("{nombre}", nombre)
#             .replace("{tipo_portal}", tipo_portal or "")
#             .replace("{url_portal}", url_portal)
#         )
#
#         # ---------------------------------------------------------
#         # 4. ENVIAR MENSAJE
#         # ---------------------------------------------------------
#         enviar_mensaje(numero, mensaje)
#
#         print(f"🔗 [PORTAL] Enviado correctamente a {numero}: {url_portal}")
#
#         return True
#
#     except Exception as e:
#         print(f"❌ [PORTAL] Error enviando inicio portal: {e}")
#         return False

