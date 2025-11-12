import os, json
import psycopg2
import json
import unicodedata
import traceback
import time
import traceback  # colócalo al inicio del archivo (si no está ya importado)
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional

from dotenv import load_dotenv
from rapidfuzz import process, fuzz
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse

from tenant import current_tenant, current_token, current_phone_id,current_business_name
from DataBase import *
from enviar_msg_wp import enviar_plantilla_generica, enviar_mensaje_texto_simple,enviar_boton_iniciar_Completa,enviar_botones_Completa,enviar_plantilla_generica_parametros
# from enviar_msg_wp import *

from main import guardar_mensaje
from utils import *

logger = logging.getLogger(__name__)

load_dotenv()

# Configuración
# TOKEN = os.getenv("WHATSAPP_TOKEN")
# PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_ID")

INTERNAL_DATABASE_URL = os.getenv("INTERNAL_DATABASE_URL")  # 🔹 corregido nombre

router = APIRouter()


# ============================
# CACHE DE TOKENS POR TENANT
# ============================
_token_cache: dict[str, tuple[str, str, float]] = {}  # {subdominio: (token, phone_id, timestamp)}
_cache_lock = threading.Lock()
_TOKEN_CACHE_TTL = 300  # 5 minutos

def _get_cached_tokens(subdominio: str) -> Optional[tuple[str, str]]:
    """Obtiene tokens del cache si aún son válidos."""
    with _cache_lock:
        if subdominio in _token_cache:
            token, phone_id, timestamp = _token_cache[subdominio]
            if time.time() - timestamp < _TOKEN_CACHE_TTL:
                return token, phone_id
            else:
                # Token expirado, eliminar del cache
                del _token_cache[subdominio]
    return None

def _set_cached_tokens(subdominio: str, token: str, phone_id: str):
    """Guarda tokens en el cache."""
    with _cache_lock:
        _token_cache[subdominio] = (token, phone_id, time.time())

# ============================
# ENVIAR MENSAJES INICIO
# ============================

def obtener_tokens_por_tenant(subdominio: str | None = None) -> tuple[str, str]:
    """
    Obtiene los tokens (access_token, phone_number_id) para un tenant.
    Usa cache para evitar consultas repetidas a la BD.
    Si no se proporciona subdominio, usa el tenant actual del contexto.
    """
    if subdominio is None:
        subdominio = current_tenant.get()
    
    # Intentar obtener del cache primero
    cached = _get_cached_tokens(subdominio)
    if cached:
        return cached
    
    # Si no está en cache, consultar BD
    cuenta = obtener_cuenta_por_subdominio(subdominio)
    if not cuenta:
        raise ValueError(f"No se encontraron credenciales para {subdominio}")
    
    token = cuenta["access_token"]
    phone_id = cuenta["phone_number_id"]
    
    # Guardar en cache
    _set_cached_tokens(subdominio, token, phone_id)
    
    return token, phone_id

def enviar_mensaje(numero: str, texto: str, token: str, numero_id: str):
    """
    Envía un mensaje de texto a un número de WhatsApp.
    
    Args:
        numero: Número de teléfono destino
        texto: Texto del mensaje
        token: Access token de WhatsApp (obligatorio)
        numero_id: Phone number ID de WhatsApp (obligatorio)
    """
    return enviar_mensaje_texto_simple(
        token=token,
        numero_id=numero_id,
        telefono_destino=numero,
        texto=texto
    )

def enviar_boton_iniciar(numero: str, texto: str, token: str, numero_id: str):
    """
    Envía un botón de inicio a un número de WhatsApp.
    
    Args:
        numero: Número de teléfono destino
        texto: Texto del mensaje
        token: Access token de WhatsApp (obligatorio)
        numero_id: Phone number ID de WhatsApp (obligatorio)
    """
    return enviar_boton_iniciar_Completa(
        token=token,
        numero_id=numero_id,
        telefono_destino=numero,
        texto=texto
    )

def enviar_botones(numero: str, texto: str, botones: list, token: str, numero_id: str):
    """
    Envía botones interactivos a un número de WhatsApp.
    
    Args:
        numero: Número de teléfono destino
        texto: Texto del mensaje
        botones: Lista de botones
        token: Access token de WhatsApp (obligatorio)
        numero_id: Phone number ID de WhatsApp (obligatorio)
    """
    return enviar_botones_Completa(
        token=token,
        numero_id=numero_id,
        telefono_destino=numero,
        texto=texto,
        botones=botones
    )

def enviar_inicio_encuesta_plantilla(numero: str, token: str, numero_id: str):
    """
    Envía una plantilla de inicio de encuesta a un número de WhatsApp.
    
    Args:
        numero: Número de teléfono destino
        token: Access token de WhatsApp (obligatorio)
        numero_id: Phone number ID de WhatsApp (obligatorio)
    """
    nombre_agencia = current_business_name.get()
    parametros = [
        nombre_agencia,     # Llene {{1}} del body
        numero              # Llene {{2}} del botón dinámico
    ]
    return enviar_plantilla_generica_parametros(
        token=token,
        phone_number_id=numero_id,
        numero_destino=numero,
        nombre_plantilla="inicio_encuesta",
        codigo_idioma="es_CO",
        parametros=parametros
    )

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


FLOW_STATE_TABLE = "whatsapp_flow_state"
TEMP_DATA_TABLE = "whatsapp_temp_data"
TTL = 1800
FLOW_STATE_TTL = timedelta(seconds=TTL)


def _load_flow_state(numero: str, tenant_schema: Optional[str] = None):
    try:
        with get_connection_context(tenant_schema) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT estado, actualizado_en FROM {FLOW_STATE_TABLE} WHERE telefono = %s",
                    (numero,),
                )
                row = cur.fetchone()
            conn.commit()
            if not row:
                return None, None
            estado, actualizado_en = row
            if isinstance(estado, str):
                estado = json.loads(estado)
            return estado or {}, actualizado_en
    except Exception as exc:
        print(f"❌ Error cargando estado de flujo para {numero}: {exc}")
        return None, None


def _save_flow_state(numero: str, estado: dict, tenant_schema: Optional[str] = None):
    try:
        with get_connection_context(tenant_schema) as conn:
            payload = json.dumps(estado)
            now = datetime.now(timezone.utc)
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {FLOW_STATE_TABLE} (telefono, estado, actualizado_en)
                    VALUES (%s, %s::jsonb, %s)
                    ON CONFLICT (telefono)
                    DO UPDATE SET estado = EXCLUDED.estado, actualizado_en = EXCLUDED.actualizado_en
                    """,
                    (numero, payload, now),
                )
            conn.commit()
    except Exception as exc:
        print(f"❌ Error guardando estado de flujo para {numero}: {exc}")


def _set_temp_data(numero: str, clave: str, valor, tenant_schema: Optional[str] = None) -> None:
    try:
        with get_connection_context(tenant_schema) as conn:
            now = datetime.now(timezone.utc)
            payload = json.dumps(valor)
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {TEMP_DATA_TABLE} (telefono, clave, valor, actualizado_en)
                    VALUES (%s, %s, %s::jsonb, %s)
                    ON CONFLICT (telefono, clave)
                    DO UPDATE SET valor = EXCLUDED.valor, actualizado_en = EXCLUDED.actualizado_en
                    """,
                    (numero, clave, payload, now),
                )
            conn.commit()
    except Exception as exc:
        print(f"❌ Error guardando dato temporal '{clave}' para {numero}: {exc}")


def _get_temp_data(numero: str, clave: str, tenant_schema: Optional[str] = None):
    try:
        with get_connection_context(tenant_schema) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT valor FROM {TEMP_DATA_TABLE} WHERE telefono = %s AND clave = %s",
                    (numero, clave),
                )
                row = cur.fetchone()
            conn.commit()
            if not row:
                return None
            valor = row[0]
            if isinstance(valor, str):
                return json.loads(valor)
            return valor
    except Exception as exc:
        print(f"❌ Error obteniendo dato temporal '{clave}' para {numero}: {exc}")
        return None


def _clear_temp_data(numero: str, clave: str | None = None, tenant_schema: Optional[str] = None) -> None:
    try:
        with get_connection_context(tenant_schema) as conn:
            with conn.cursor() as cur:
                if clave:
                    cur.execute(
                        f"DELETE FROM {TEMP_DATA_TABLE} WHERE telefono = %s AND clave = %s",
                        (numero, clave),
                    )
                else:
                    cur.execute(
                        f"DELETE FROM {TEMP_DATA_TABLE} WHERE telefono = %s",
                        (numero,),
                    )
            conn.commit()
    except Exception as exc:
        print(f"❌ Error limpiando datos temporales para {numero}: {exc}")


def actualizar_flujo(numero, paso, tenant_schema: Optional[str] = None):
    estado, _ = _load_flow_state(numero, tenant_schema)
    if not isinstance(estado, dict):
        estado = {}
    estado["paso"] = paso
    estado["timestamp"] = datetime.now(timezone.utc).isoformat()
    _save_flow_state(numero, estado, tenant_schema)


def obtener_flujo(numero, tenant_schema: Optional[str] = None):
    estado, actualizado_en = _load_flow_state(numero, tenant_schema)
    if not estado:
        return None
    if actualizado_en:
        diferencia = datetime.now(timezone.utc) - actualizado_en
        if diferencia > FLOW_STATE_TTL:
            eliminar_flujo(numero, tenant_schema)
            return None
    return estado.get("paso")


def asegurar_flujo(numero: str, tenant_schema: Optional[str] = None) -> dict:
    estado, _ = _load_flow_state(numero, tenant_schema)
    if not isinstance(estado, dict):
        estado = {}
    if "timestamp" not in estado:
        estado["timestamp"] = datetime.now(timezone.utc).isoformat()
    _save_flow_state(numero, estado, tenant_schema)
    return estado


def eliminar_flujo(numero: str, tenant_schema: Optional[str] = None):
    try:
        with get_connection_context(tenant_schema) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {FLOW_STATE_TABLE} WHERE telefono = %s",
                    (numero,),
                )
            conn.commit()
    except Exception as exc:
        print(f"❌ Error reiniciando flujo para {numero}: {exc}")
    _clear_temp_data(numero, tenant_schema=tenant_schema)
    print(f"🧹 Flujo reiniciado para {numero}")


def guardar_respuesta(numero: str, paso: int, texto: str, tenant_schema: Optional[str] = None) -> bool:
    try:
        with get_connection_context(tenant_schema) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO perfil_creador_flujo_temp (telefono, paso, respuesta)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (telefono, paso)
                        DO UPDATE SET respuesta = EXCLUDED.respuesta
                    """,
                    (numero, paso, texto),
                )

        logger.info("✅ Respuesta guardada: numero=%s paso=%s", numero, paso)
        return True

    except Exception as e:
        logger.exception("❌ Error guardando respuesta: numero=%s paso=%s error=%s", numero, paso, e)
        return False

def eliminar_flujo_temp(numero: str, tenant_schema: Optional[str] = None) -> bool:
    try:
        with get_connection_context(tenant_schema) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM perfil_creador_flujo_temp
                    WHERE telefono = %s
                    """,
                    (numero,),
                )

        logger.info("🗑️ Datos temporales eliminados para %s", numero)
        return True

    except Exception as e:
        logger.exception("❌ Error eliminando flujo temporal para %s: %s", numero, e)
        return False


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
                    logger.warning("No se encontró creador con whatsapp %s", numero)
                    token, numero_id = obtener_tokens_por_tenant()
                    enviar_mensaje(numero, "No encontramos tu perfil en el sistema. Verifica tu número.", token, numero_id)
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
        token, numero_id = obtener_tokens_por_tenant()
        enviar_mensaje(numero, diagnostico, token, numero_id)
        logger.info("Diagnóstico enviado correctamente a %s (%s)", numero, nombre_real)
        return True

    except Exception as e:
        logger.exception("Error al enviar diagnóstico a %s: %s", numero, e)
        try:
            token, numero_id = obtener_tokens_por_tenant()
            enviar_mensaje(numero, "Ocurrió un error al generar tu diagnóstico. Intenta más tarde.", token, numero_id)
        except Exception:
            logger.exception("Error adicional al intentar notificar al usuario %s", numero)
        return False


def consolidar_perfil(telefono: str, respuestas_dict: dict | None = None, tenant_schema: Optional[str] = None):
    """Procesa y actualiza un solo número en perfil_creador con manejo de errores
    
    Args:
        telefono: Número de teléfono del usuario
        respuestas_dict: Diccionario opcional con respuestas {paso: respuesta}.
                        Si es None, se leen de la tabla perfil_creador_flujo_temp
        tenant_schema: Schema del tenant. Si es None, usa current_tenant.get()
    """
    try:
        with get_connection_context(tenant_schema) as conn:
            with conn.cursor() as cur:
                # Buscar creador por número
                cur.execute("SELECT id, usuario, nombre_real, whatsapp FROM creadores WHERE whatsapp=%s", (telefono,))
                creador = cur.fetchone()
                if not creador:
                    print(f"⚠️ No se encontró creador con whatsapp {telefono}")
                    return

                creador_id = creador[0]

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

    except Exception as e:
        print(f"❌ Error al procesar número {telefono}: {str(e)}")

    return {"status": "ok"}


def obtener_rol_usuario(numero):
    return consultar_rol_bd(numero)

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

    token, numero_id = obtener_tokens_por_tenant()
    enviar_mensaje(numero, mensaje, token, numero_id)


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
    token, numero_id = obtener_tokens_por_tenant()
    enviar_mensaje(numero, requisitos, token, numero_id)

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
    respuesta_8 = respuestas.get(8, "0")
    # Ahora acepta 0/1 (0=no, 1=sí)
    if str(respuesta_8).strip() in {"1", "si", "sí", "s"}:
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
    estado, _ = _load_flow_state(numero)
    if isinstance(estado, dict):
        nombre = estado.get("nombre")
        if nombre:
            return nombre
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
    token, numero_id = obtener_tokens_por_tenant()
    enviar_mensaje(numero, mensaje, token, numero_id)

def manejar_respuesta(numero, texto, token: str | None = None, numero_id: str | None = None, tenant_schema: Optional[str] = None, background_tasks: BackgroundTasks | None = None):
    texto = texto.strip()
    texto_normalizado = texto.lower()

    # Estado actual
    paso = obtener_flujo(numero, tenant_schema)              # puede ser None, int, o string (p.e. "chat_libre")
    rol = obtener_rol_usuario(numero)
    asegurar_flujo(numero, tenant_schema)                    # asegura estructura en caché

    # 1) Atajos globales
    if _es_saludo(texto_normalizado):
        _procesar_saludo(numero, rol, background_tasks, tenant_schema)
        return

    if _es_volver_menu(texto_normalizado):
        eliminar_flujo(numero, tenant_schema)
        if background_tasks:
            # Enviar menú en background si hay background_tasks disponible
            background_tasks.add_task(_enviar_menu_principal_background, numero, rol)
        else:
            enviar_menu_principal(numero, rol)
        return

    if paso == "chat_libre":
        # En chat libre no procesamos menú/encuesta
        return

    # 2) Delegar según estado
    if paso is None or isinstance(paso, str):
        manejar_menu(numero, texto_normalizado, rol, token, numero_id, tenant_schema, background_tasks)     # 👈 MENÚ
    # elif isinstance(paso, int):
    #     manejar_encuesta(numero, texto, texto_normalizado, paso, rol)  # 👈 ENCUESTA
    else:
        if not token or not numero_id:
            token, numero_id = obtener_tokens_por_tenant()
        if background_tasks:
            background_tasks.add_task(_enviar_mensaje_background, numero, "Opción no válida. Escribe 'menu' para ver las opciones.", token, numero_id)
        else:
            enviar_mensaje(numero, "Opción no válida. Escribe 'menu' para ver las opciones.", token, numero_id)


# =========================
# Utilidades simples
# =========================
def _es_saludo(tn: str) -> bool:
    return tn in {"hola", "buenas", "saludos", "brillar"}

def _es_volver_menu(tn: str) -> bool:
    return tn in {"menu", "menú", "volver", "inicio"}

def _procesar_saludo(numero, rol_actual, background_tasks: BackgroundTasks | None = None, tenant_schema: Optional[str] = None):
    usuario_bd = buscar_usuario_por_telefono(numero)
    if background_tasks:
        # Procesar en background
        background_tasks.add_task(_procesar_saludo_background, numero, rol_actual, usuario_bd, tenant_schema)
    else:
        # Procesar síncronamente (compatibilidad hacia atrás)
        if usuario_bd:
            nombre = (usuario_bd.get("nombre") or "").split(" ")[0]
            rol = usuario_bd.get("rol", rol_actual or "aspirante")
            enviar_menu_principal(numero, rol=rol, nombre=nombre)
        else:
            token, numero_id = obtener_tokens_por_tenant()
            enviar_mensaje(numero, Mensaje_bienvenida, token, numero_id)
            actualizar_flujo(numero, "esperando_usuario_tiktok", tenant_schema)


# =========================
#  MENÚ (por rol)
# =========================


def manejar_menu(numero, texto_normalizado, rol, token: str | None = None, numero_id: str | None = None, tenant_schema: Optional[str] = None, background_tasks: BackgroundTasks | None = None):
    # Menús por rol

    if rol == "aspirante":
        if texto_normalizado in {"1", "actualizar mi información", "perfil"}:
            marcar_encuesta_no_finalizada(numero)
            eliminar_flujo_temp(numero, tenant_schema)
            actualizar_flujo(numero, 1, tenant_schema)

            # 1) PARA ACTUALIZAR INFO DESDE WHATSAPP DESMARCAR 1 Y MARCAR 2:
            # -------------------------------------------------
            # enviar_pregunta(numero, 1)
            # enviar_mensaje(numero, "✏️ Perfecto. Vamos a actualizar tu información. Empecemos...")
            # -------------------------------------------------

            # 2) PARA ACTUALIZAR INFO DESDE REACT DESMARCAR 2 Y MARCAR 1:
            # -------------------------------------------------
            if token is None or numero_id is None:
                token, numero_id = obtener_tokens_por_tenant()
            url_web = f"https://talentum-manager.com/actualizar-perfil?numero={numero}"
            mensaje_url = f"✏️ Para actualizar tu información de perfil, haz clic en este enlace:\n{url_web}\n\nPuedes hacerlo desde tu celular o computadora."
            if background_tasks:
                background_tasks.add_task(_enviar_mensaje_background, numero, mensaje_url, token, numero_id)
            else:
                enviar_mensaje(numero, mensaje_url, token, numero_id)
            # -------------------------------------------------

            return
        if texto_normalizado in {"2", "análisis", "diagnóstico", "diagnostico"}:
            actualizar_flujo(numero, "diagnostico", tenant_schema)
            enviar_diagnostico(numero)
            eliminar_flujo(numero, tenant_schema)
            return
        if texto_normalizado in {"3", "requisitos"}:
            actualizar_flujo(numero, "requisitos", tenant_schema)
            enviar_requisitos(numero)
            eliminar_flujo(numero, tenant_schema)
            return
        if texto_normalizado in {"4", "chat libre"}:
            actualizar_flujo(numero, "chat_libre", tenant_schema)
            if token is None or numero_id is None:
                token, numero_id = obtener_tokens_por_tenant()
            if background_tasks:
                background_tasks.add_task(_enviar_mensaje_background, numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.", token, numero_id)
            else:
                enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.", token, numero_id)
            return
        if texto_normalizado in {"5", "preguntas", "faq"}:
            actualizar_flujo(numero, "faq", tenant_schema)
            enviar_preguntas_frecuentes(numero)
            eliminar_flujo(numero, tenant_schema)
            return
        # Si no es una opción válida: muestra SIEMPRE el menú principal de aspirante
        nombre = buscar_usuario_por_telefono(numero).get("nombre", "").split(" ")[0] or ""
        if background_tasks:
            background_tasks.add_task(_enviar_menu_principal_background, numero, rol, nombre)
        else:
            enviar_menu_principal(numero, rol=rol, nombre=nombre)
        return

    if rol == "creador":
        if texto_normalizado == "1":
            actualizar_flujo(numero, 1, tenant_schema)
            # enviar_pregunta(numero, 1)
            if token is None or numero_id is None:
                token, numero_id = obtener_tokens_por_tenant()
            if background_tasks:
                background_tasks.add_task(_enviar_inicio_encuesta_background, numero, token, numero_id)
            else:
                enviar_inicio_encuesta(numero, token, numero_id)
            return
        if texto_normalizado == "3":
            actualizar_flujo(numero, "asesoria", tenant_schema)
            if token is None or numero_id is None:
                token, numero_id = obtener_tokens_por_tenant()
            if background_tasks:
                background_tasks.add_task(_enviar_mensaje_background, numero, "📌 Un asesor se pondrá en contacto contigo pronto.", token, numero_id)
            else:
                enviar_mensaje(numero, "📌 Un asesor se pondrá en contacto contigo pronto.", token, numero_id)
            eliminar_flujo(numero, tenant_schema)
            return
        if texto_normalizado == "4":
            actualizar_flujo(numero, "recursos", tenant_schema)
            enviar_recursos_exclusivos(numero)
            eliminar_flujo(numero, tenant_schema)
            return
        if texto_normalizado == "5":
            actualizar_flujo(numero, "eventos", tenant_schema)
            enviar_eventos(numero)
            eliminar_flujo(numero, tenant_schema)
            return
        if texto_normalizado == "6":
            actualizar_flujo(numero, "soporte", tenant_schema)
            if token is None or numero_id is None:
                token, numero_id = obtener_tokens_por_tenant()
            if background_tasks:
                background_tasks.add_task(_enviar_mensaje_background, numero, "📩 Describe tu problema y el equipo técnico te responderá.", token, numero_id)
            else:
                enviar_mensaje(numero, "📩 Describe tu problema y el equipo técnico te responderá.", token, numero_id)
            return
        if texto_normalizado in {"7", "chat libre"}:
            actualizar_flujo(numero, "chat_libre", tenant_schema)
            if token is None or numero_id is None:
                token, numero_id = obtener_tokens_por_tenant()
            if background_tasks:
                background_tasks.add_task(_enviar_mensaje_background, numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.", token, numero_id)
            else:
                enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.", token, numero_id)
            return
        if texto_normalizado == "8":
            actualizar_flujo(numero, "estadisticas")
            enviar_estadisticas(numero)
            eliminar_flujo(numero)
            return
        if texto_normalizado == "9":
            actualizar_flujo(numero, "baja")
            solicitar_baja(numero)
            eliminar_flujo(numero)
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
            eliminar_flujo(numero)
            return
        if texto_normalizado == "3":
            actualizar_flujo(numero, "comunicado")
            if token is None or numero_id is None:
                token, numero_id = obtener_tokens_por_tenant()
            enviar_mensaje(numero, "✉️ Escribe el comunicado a enviar a creadores/aspirantes:", token, numero_id)
            return
        if texto_normalizado == "4":
            actualizar_flujo(numero, "recursos_admin")
            gestionar_recursos(numero)
            eliminar_flujo(numero)
            return
        if texto_normalizado in {"5", "chat libre"}:
            actualizar_flujo(numero, "chat_libre")
            if token is None or numero_id is None:
                token, numero_id = obtener_tokens_por_tenant()
            enviar_mensaje(numero, "🟢 Estás en chat libre. Puedes escribir o enviar audios.", token, numero_id)
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
import traceback
from typing import Optional

# --- Asumo que estas funciones y estructuras están definidas en tu proyecto ---
# asegurar_flujo(numero) -> dict
# guardar_respuesta(numero, paso, valor)
# actualizar_flujo(numero, siguiente)
# enviar_mensaje(numero, texto)
# validar_aceptar_ciudad(texto) -> dict con keys "corregida" y "ciudad"
# consolidar_perfil(numero)
# marcar_encuesta_completada(numero) -> bool
# El estado del flujo se persiste en la tabla whatsapp_flow_state (por tenant)
# -------------------------------------------------------------------------

# ============================
# BACKGROUND TASKS HELPERS
# ============================

def _enviar_mensaje_background(numero: str, texto: str, token: str, numero_id: str):
    """
    Función helper para enviar mensajes en background.
    Maneja errores internamente para no afectar el flujo principal.
    """
    try:
        enviar_mensaje(numero, texto, token, numero_id)
    except Exception as e:
        print(f"❌ Error enviando mensaje en background a {numero}: {e}")

def _procesar_audio_background(numero: str, audio_id: str, token: str, phone_id: str):
    """
    Función helper para procesar audios en background.
    Descarga el audio, lo guarda y envía confirmación.
    """
    try:
        from utils import descargar_audio
        url_cloudinary = descargar_audio(audio_id, token)
        if url_cloudinary:
            guardar_mensaje(numero, url_cloudinary, tipo="recibido", es_audio=True)
            enviar_mensaje(numero, "🎧 Recibimos tu audio. Un asesor lo revisará pronto.", token, phone_id)
        else:
            enviar_mensaje(numero, "⚠️ No se pudo procesar tu audio, inténtalo de nuevo.", token, phone_id)
    except Exception as e:
        print(f"❌ Error procesando audio en background para {numero}: {e}")
        try:
            enviar_mensaje(numero, "⚠️ Ocurrió un error al procesar tu audio. Intenta más tarde.", token, phone_id)
        except:
            pass

def _guardar_mensaje_background(numero: str, texto: str, tipo: str = "recibido", es_audio: bool = False):
    """
    Función helper para guardar mensajes en background.
    """
    try:
        guardar_mensaje(numero, texto, tipo=tipo, es_audio=es_audio)
    except Exception as e:
        print(f"❌ Error guardando mensaje en background para {numero}: {e}")

def _enviar_inicio_encuesta_background(numero: str, token: str, phone_id: str):
    """
    Función helper para enviar inicio de encuesta en background.
    """
    try:
        enviar_inicio_encuesta(numero, token, phone_id)
    except Exception as e:
        print(f"❌ Error enviando inicio de encuesta en background a {numero}: {e}")

def _enviar_menu_principal_background(numero: str, rol: str, nombre: str = ""):
    """
    Función helper para enviar menú principal en background.
    """
    try:
        enviar_menu_principal(numero, rol=rol, nombre=nombre)
    except Exception as e:
        print(f"❌ Error enviando menú principal en background a {numero}: {e}")

def _procesar_saludo_background(numero: str, rol: str, usuario_bd: dict | None, tenant_schema: Optional[str] = None):
    """
    Función helper para procesar saludo en background.
    """
    try:
        if usuario_bd:
            nombre = (usuario_bd.get("nombre") or "").split(" ")[0]
            rol_actual = usuario_bd.get("rol", rol or "aspirante")
            enviar_menu_principal(numero, rol=rol_actual, nombre=nombre)
        else:
            token, numero_id = obtener_tokens_por_tenant()
            enviar_mensaje(numero, Mensaje_bienvenida, token, numero_id)
            actualizar_flujo(numero, "esperando_usuario_tiktok", tenant_schema)
    except Exception as e:
        print(f"❌ Error procesando saludo en background para {numero}: {e}")

@router.post("/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    print("📩 Webhook recibido:", json.dumps(data, indent=2))

    try:

        entry = data.get("entry", [])[0]
        change = entry.get("changes", [])[0]
        value = change.get("value", {})
        field = change.get("field")
        event = value.get("event")

        # ✅ si es evento de instalación de partner/app o asignación de WABA

        # === CASO 1: EVENTOS DE WHATSAPP BUSINESS ACCOUNT (account_update)
        if field == "account_update":
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
                return resultado  # detenemos el flujo si es evento de instalación

            return {"status": "ok"}

        # === CASO 2: MENSAJES NORMALES CON PHONE_NUMBER_ID
        metadata = value.get("metadata", {})
        phone_number_id = metadata.get("phone_number_id")

        cuenta = obtener_cuenta_por_phone_id(phone_number_id)
        if not cuenta:
            print(f"⚠️ No se encontró cuenta asociada al número {phone_number_id}")
            return {"status": "ignored"}

        # Extraer info de la cuenta
        token_cliente = cuenta["access_token"]
        phone_id_cliente = cuenta["phone_number_id"]
        tenant_name = cuenta["subdominio"]  # tenant_name sin prefijo (ej: "test")
        business_name = cuenta["business_name"]
        
        # ✅ Asignar valores de contexto
        # Los schemas en PostgreSQL no tienen prefijo 'agencia_', se usan directamente
        current_token.set(token_cliente)
        current_phone_id.set(phone_id_cliente)
        current_tenant.set(tenant_name)  # Guardar tenant_name directamente (ej: "test")
        current_business_name.set(business_name)

        print(f"🌐 Tenant actual: {current_tenant.get()}")
        print(f"🔑 Token actual: {current_token.get()}")
        print(f"📞 phone_id actual: {current_phone_id.get()}")
        print(f"📞business_name: {current_business_name.get()}")

        cambios = data.get("entry", [])[0].get("changes", [])[0].get("value", {})
        mensajes = cambios.get("messages", [])
        if not mensajes:
            return {"status": "ok"}

        for mensaje in mensajes:
            numero = mensaje.get("from")
            tipo = mensaje.get("type")
            # obtener_flujo usará current_tenant.get() si tenant_schema es None
            paso = obtener_flujo(numero, tenant_schema=None)
            usuario_bd = buscar_usuario_por_telefono(numero)
            rol = obtener_rol_usuario(numero) if usuario_bd else None

            # === Obtén el texto antes de cualquier uso ===
            texto = mensaje.get("text", {}).get("body", "").strip()
            texto_lower = texto.lower()

            # === 4️⃣ CHAT LIBRE ===  (Esto va primero)
            if paso == "chat_libre":
                if tipo == "text":
                    # Guardar mensaje en background (no bloquea respuesta)
                    background_tasks.add_task(_guardar_mensaje_background, numero, texto, "recibido", False)
                elif tipo == "audio":
                    # Procesar audio en background (operación pesada)
                    audio_id = mensaje.get("audio", {}).get("id")
                    background_tasks.add_task(_procesar_audio_background, numero, audio_id, token_cliente, phone_id_cliente)
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

                    # Aquí se pueden agregar más botones en el futuro
                    background_tasks.add_task(_enviar_mensaje_background, numero, "Este botón no es válido en este momento.", token_cliente, phone_id_cliente)
                    return {"status": "ok"}

            print(f"📍 [DEBUG] número={numero}, paso={paso}, texto='{texto_lower}'")

            # === 1️⃣ NUEVO USUARIO: FLUJO DE ONBOARDING Y ENCUESTA ===
            if tipo == "text" and not usuario_bd:
                # Si el paso guardado no tiene sentido, reiniciamos el flujo
                if paso not in [None, "esperando_usuario_tiktok", "confirmando_nombre", "esperando_inicio_encuesta"]:
                    print(f"⚠️ Reiniciando flujo para {numero}, paso anterior: {paso}")
                    eliminar_flujo(numero)  # usa current_tenant.get() automáticamente
                    paso = None

                # === Inicio del flujo ===
                if paso is None:
                    # Actualizar flujo primero (crítico), luego enviar mensaje en background
                    actualizar_flujo(numero, "esperando_usuario_tiktok")
                    background_tasks.add_task(_enviar_mensaje_background, numero, Mensaje_bienvenida, token_cliente, phone_id_cliente)
                    return {"status": "ok"}

                # Se espera usuario de TikTok
                if paso == "esperando_usuario_tiktok":
                    usuario_tiktok = texto.strip()
                    aspirante = buscar_aspirante_por_usuario_tiktok(usuario_tiktok)
                    if aspirante:
                        nombre = aspirante.get("nickname") or aspirante.get("nombre_real") or "(sin nombre)"
                        # Actualizar estado primero, luego enviar mensaje en background
                        actualizar_flujo(numero, "confirmando_nombre")
                        _set_temp_data(numero, "aspirante", aspirante)
                        background_tasks.add_task(_enviar_mensaje_background, numero, mensaje_confirmar_nombre(nombre), token_cliente, phone_id_cliente)
                    else:
                        background_tasks.add_task(_enviar_mensaje_background, numero, "❌ No encontramos ese usuario de TikTok. ¿Podrías verificarlo?", token_cliente, phone_id_cliente)
                    return {"status": "ok"}

                # Confirmar nickname y actualizar teléfono
                if paso == "confirmando_nombre":
                    if texto_lower in ["si", "sí", "s"]:
                        aspirante = _get_temp_data(numero, "aspirante")
                        if aspirante:
                            actualizar_telefono_aspirante(aspirante["id"], numero)
                        _clear_temp_data(numero, "aspirante")
                        actualizar_flujo(numero, "esperando_inicio_encuesta")
                        # Enviar inicio de encuesta en background (puede ser pesado)
                        background_tasks.add_task(_enviar_inicio_encuesta_background, numero, token_cliente, phone_id_cliente)
                    elif texto_lower in ["no", "n"]:
                        background_tasks.add_task(_enviar_mensaje_background, numero, "❌ Por favor verifica tu nombre o usuario de TikTok.", token_cliente, phone_id_cliente)
                    else:
                        background_tasks.add_task(_enviar_mensaje_background, numero, "⚠️ Por favor responde solo *sí* o *no* para continuar.", token_cliente, phone_id_cliente)
                    return {"status": "ok"}

                # Si el usuario está esperando iniciar la encuesta pero escribe texto
                if paso == "esperando_inicio_encuesta":
                    if texto_lower.strip() != "":
                        url_web = f"https://{tenant_name}.talentum-manager.com/actualizar-perfil?numero={numero}"
                        mensaje = ("💬 Haz clic en el enlace para comenzar la encuesta 📋\n\n"f"{url_web}\n\n""Puedes hacerlo desde tu celular o computadora.")
                        background_tasks.add_task(_enviar_mensaje_background,numero,mensaje,token_cliente,phone_id_cliente)
                        return {"status": "ok"}

            # === 2️⃣ ASPIRANTE EN BASE DE DATOS ===
            if usuario_bd and rol == "aspirante":
                finalizada = encuesta_finalizada(numero)
                # Si encuesta finalizada, SIEMPRE muestra el menú para cualquier mensaje
                if finalizada:
                    manejar_menu(numero, texto_lower, rol, token_cliente, phone_id_cliente, None, background_tasks)
                    return {"status": "ok"}

                # Si no ha terminado la encuesta
                if not finalizada:
                    if texto_lower in {"brillar", "menu", "menú", "inicio"}:
                        ultimo_paso = 1
                        actualizar_flujo(numero, ultimo_paso)
                        # Enviar mensajes en background
                        background_tasks.add_task(_enviar_mensaje_background, numero, "🚩 No has finalizado tu encuesta. Por favor continúa para completar la información.", token_cliente, phone_id_cliente)
                        background_tasks.add_task(_enviar_inicio_encuesta_background, numero, token_cliente, phone_id_cliente)
                        return {"status": "ok"}


                    manejar_respuesta(numero, texto, token_cliente, phone_id_cliente, None, background_tasks)
                    return {"status": "ok"}

            # === 3️⃣ ADMIN O CREADOR EN BD ===
            if usuario_bd and rol in ("admin", "creador", "creadores"):
                manejar_menu(numero, texto_lower, rol, token_cliente, phone_id_cliente, None, background_tasks)
                return {"status": "ok"}

            print(f"🟣 DEBUG CHAT LIBRE - paso actual: {paso}")

    except Exception as e:
        print("❌ Error procesando webhook:", e)
        import traceback
        traceback.print_exc()

    return {"status": "ok"}


def mensaje_inicio_encuesta() -> str:
    nombre_agencia = current_business_name.get()
    return (
        f"🔒 *Preguntas básicas*\n\n"
        f"Antes de continuar, se te harán *preguntas personales básicas* para evaluar tu perfil como aspirante a creador de contenido en *{nombre_agencia}*.\n\n"
        "Si aceptas y deseas iniciar la encuesta, haz clic en el siguiente enlace 👇"
    )

def enviar_inicio_encuesta(numero: str, token: str, numero_id: str):
    tenant_name = current_tenant.get()  # ✅ Obtenemos el tenant actual
    if not tenant_name:
        tenant_name = "default"  # Valor por defecto si no hay tenant activo

    # Elimina datos temporales si existen del numero
    eliminar_flujo_temp(numero)

    url_web = f"https://{tenant_name}.talentum-manager.com/actualizar-perfil?numero={numero}"

    mensaje = (
        f"{mensaje_inicio_encuesta()}\n\n"
        f"✏️ *Enlace para continuar:*\n{url_web}\n\n"
        "Puedes hacerlo desde tu celular o computadora."
    )

    enviar_mensaje(numero, mensaje, token, numero_id)
    print(f"🔗 Enviado mensaje de inicio de encuesta a {numero}: {url_web}")


from pydantic import BaseModel

# ⚠️ DEPRECADO: Ya no se usa. Las respuestas se envían todas juntas a /consolidar
# class RespuestaInput(BaseModel):
#     numero: str
#     paso: int
#     respuesta: str

class ConsolidarInput(BaseModel):
    numero: str
    respuestas: dict  # Diccionario: {1: "Ricardo", 2: "5", 3: "1", ...}


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

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ⚠️ DEPRECADO: Ya no se usa. Las respuestas se envían todas juntas a /consolidar
# @router.post("/respuesta")
# def guardar_respuesta_web(data: RespuestaInput):
#     try:
#         guardar_respuesta(data.numero, data.paso, data.respuesta)
#         return {"ok": True, "msg": "Respuesta guardada"}
#     except Exception as e:
#         return {"ok": False, "error": str(e)}

@router.post("/consolidar")
def consolidar_perfil_web(data: ConsolidarInput):
    try:
        subdominio = current_tenant.get()
        cuenta = obtener_cuenta_por_subdominio(subdominio)
        if not cuenta:
            return JSONResponse({"error": f"No se encontraron credenciales para {subdominio}"}, status_code=404)

        token_cliente = cuenta["access_token"]
        phone_id_cliente = cuenta["phone_number_id"]

        current_token.set(token_cliente)
        current_phone_id.set(phone_id_cliente)

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

        print(f"🔗 Iniciando consolidación de perfil en subdominio: {subdominio}")
        print(f"📋 Respuestas recibidas: {respuestas_dict}")
        consolidar_perfil(data.numero, respuestas_dict=respuestas_dict, tenant_schema=subdominio)
        eliminar_flujo(data.numero, tenant_schema=subdominio)
        eliminar_flujo_temp(data.numero, tenant_schema=subdominio)
        # Enviar mensaje de cierre en background (no bloquea la respuesta)
        # Nota: /consolidar no tiene background_tasks, pero podemos usar threading
        import threading
        threading.Thread(
            target=_enviar_mensaje_background,
            args=(data.numero, mensaje_encuesta_final(), token_cliente, phone_id_cliente),
            daemon=True
        ).start()
        print(f"✅ Perfil consolidado y mensaje final enviado a {data.numero}")
        return {"ok": True, "msg": "Perfil consolidado correctamente"}

    except Exception as e:
        print(f"❌ Error consolidando perfil: {e}")
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


