# ✅ main.py
from fastapi import FastAPI, HTTPException, Path, Body, Request, Response, UploadFile, File
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import io

# Respuestas personalizadas (usa solo si las necesitas)
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from dotenv import load_dotenv  # Solo si usas variables de entorno
import os
import json
import logging
import traceback

from datetime import datetime
from typing import List

from google.oauth2.credentials import Credentials as UserCredentials
import psycopg2

from DataBase import actualizar_contacto_info_db, actualizar_nombre_contacto, eliminar_mensajes, \
    obtener_todos_usuarioss, crear_usuarios, obtener_usuarios_por_id, eliminar_usuarios, cambiar_estado_usuarios, \
    obtener_usuarios_por_username, es_admin, actualiza_password_usuario, actualizar_usuarios, \
    obtener_estadisticas_evaluacion, obtener_todos_responsables_agendas, obtener_todos_manager, \
    guardar_o_actualizar_token_db, guardar_o_actualizar_whatsapp_business_account, \
    hash_password
from schemas import *

# Tu propio código/librerías
from enviar_msg_wp import *
# from borrar_buscador import inicializar_busqueda, responder_pregunta
# from DataBase import *
from Excel import *

# from borrar_utils import actualizar_info_phone

# 🔄 Cargar variables de entorno
load_dotenv()
try:
    from utils_whatsapp_flujos import onboarding_sin_aviso_expiracion

    print(
        "[STARTUP] WHATSAPP_ONBOARDING_SIN_AVISO_EXPIRACION="
        f"{os.getenv('WHATSAPP_ONBOARDING_SIN_AVISO_EXPIRACION')!r} "
        f"activo={onboarding_sin_aviso_expiracion()}"
    )
except Exception as e:
    print(f"[STARTUP] No se pudo leer flag onboarding sin aviso: {e}")

API_KEY = os.getenv("OPENAI_API_KEY")

TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_ID")


VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "142848PITUFO")
CHROMA_DIR = "./chroma_faq_openai"

# SERVICE_ACCOUNT_FILE = "credentials.json"
SERVICE_ACCOUNT_INFO = os.getenv("GOOGLE_CREDENTIALS_JSON")
# CALENDAR_ID="primary"
# CALENDAR_ID = "atavillamil.prestige@gmail.com"  # ID del calendario Prestige
CALENDAR_ID = os.getenv("CALENDAR_ID")
# CALENDAR_ID = "primary" # para que sea siempre primary, pero tambien puedo configurarlo en variables del backend

try:
    from main_webhook import router as aspirantes_perfil_router
except Exception:
    print("FATAL: error importando main_webhook (revisa utils_whatsapp_flujos.py y dependencias)")
    traceback.print_exc()
    raise
from main_cargar_aspirantes import router as aspirantes_router
from middleware_tenant import TenantMiddleware   # 👈 importa tu middleware
# from borrar_middleware_rate_limit import RateLimitMiddleware  # 👈 Rate limiting por tenant
from main_agendamiento import router as agendamiento_router
from main_evaluacion_aspirante import router as EvaluacionAspirante_router
from main_entrevistas import router as entrevistas_router
from utils_aspirantes import router as utils_aspirantes_router
from utils_aspirantes_1 import actualizar_info_phone
from main_auth import router as main_auth_router
from main_diagnostico import router as diagnostico_router
from main_configuracion import router as bienvenida_router
from main_mensajeria_whatsapp import router as main_mensajeria_whatsapp_router
from main_invitacion import router as main_invitacion_router
from main_diagnostico_config import router as diagnostico_config_router
from main_aspirantes import router as main_aspirantes_router
from main_portal_usuarios import router as main_portal_aspirantes_router
from main_portal_creadores import router as main_portal_creadores_router
from main_estadisticas_aspirantes import router as main_estadisticas_router
from main_creadores_perfil import router as main_creadores_perfil_router
from main_creadores_perfil_config import router as main_creadores_perfil_config_router
from main_creadores_categoria import router as main_creadores_categoria_router
from main_creadores_metricas import router as main_creadores_metricas_router
from performance_routes import router as main_creadores_performance_router
from creadores_performance_tablero import router as creadores_performance_tablero_router
from creadores_capacitaciones import router as creadores_capacitaciones_router
from creadores_importacion import router as creadores_importacion_router



# ⚙️ Inicializar FastAPI
app = FastAPI()

# 👇 Registrar Middlewares (orden importante: Tenant primero, luego RateLimit)
app.add_middleware(TenantMiddleware)
app.include_router(main_auth_router, tags=["auth"])
app.include_router(aspirantes_perfil_router, tags=["Perfil Creador WhatsApp"])
app.include_router(aspirantes_router, tags=["Cargar Aspirantes"])
app.include_router(agendamiento_router, tags=["Agendamiento"])
app.include_router(EvaluacionAspirante_router, tags=["Evaluacion Aspirante"])
app.include_router(entrevistas_router, tags=["entrevistas"])
app.include_router(utils_aspirantes_router, tags=["utils aspirantes"])
app.include_router(diagnostico_router, tags=["diagnostico"])
app.include_router(bienvenida_router, tags=["bienvenida"])
app.include_router(main_mensajeria_whatsapp_router, tags=["mensajeria whatsapp"])
app.include_router(main_invitacion_router, tags=["invitacion"])
app.include_router(diagnostico_config_router, tags=["diagnostico configuracion"])
app.include_router(main_aspirantes_router, tags=["aspirantes"])
app.include_router(main_portal_aspirantes_router, tags=["portal aspirantes"])
app.include_router(main_portal_creadores_router, tags=["portal creadores"])
app.include_router(main_estadisticas_router, tags=["estadisticas aspirantes"])
app.include_router(main_creadores_perfil_router, tags=["creadores perfil"])
app.include_router(main_creadores_perfil_config_router, tags=["creadores perfil config"])
app.include_router(main_creadores_categoria_router, tags=["creadores categorias"])
app.include_router(main_creadores_metricas_router, tags=["creadores metricas"])
app.include_router(main_creadores_performance_router, tags=["creadores seguimiento"])
app.include_router(creadores_performance_tablero_router, tags=["creadores tablero"])
app.include_router(creadores_capacitaciones_router, tags=["creadores capacitaciones"])
app.include_router(creadores_importacion_router, tags=["creadores importacion"])



# ✅ Configurar correctamente CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://talentum-manager.com",
        "https://www.talentum-manager.com",
        "https://test.talentum-manager.com",
        "https://agency15-5.talentum-manager.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-Tenant-Name", "Authorization"],
)

# -----------------------------------------------
# -----------------------------------------------
# -----------------------------------------------
# -----------------------------------------------
# -----------------------------------------------
# -----------------------------------------------
@app.middleware("http")
async def log_requests(request, call_next):
    print(f"🔥 ENDPOINT: {request.url}")
    response = await call_next(request)
    return response
# -----------------------------------------------
# -----------------------------------------------
# -----------------------------------------------
# -----------------------------------------------

# 🧠 Inicializar búsqueda semántica
# client, collection = inicializar_busqueda(API_KEY, persist_dir=CHROMA_DIR)

# ==================== PROYECTO CALENDAR ===========================
# === Configuración ===
SCOPES = ['https://www.googleapis.com/auth/calendar']
DB_URL = os.getenv("INTERNAL_DATABASE_URL")  # Debe estar en tus variables de entorno

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("calendar_sync")


# Middleware para manejo de errores
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"❌ Error no manejado: {str(exc)}")
    logger.error(traceback.format_exc())
    try:
        return JSONResponse(
            status_code=500,
            content={"detail": "Error interno del servidor"}
        )
    except Exception as e:
        # fallback por si JSONResponse se rompe
        return PlainTextResponse(
            str(e),
            status_code=500
        )

# ==================== FUNCIONES DE BD PARA TOKEN ===========================

def guardar_token_en_bd(token_dict, nombre='calendar'):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO google_tokens (nombre, token_json, actualizado)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (nombre)
                    DO UPDATE SET token_json = EXCLUDED.token_json, actualizado = EXCLUDED.actualizado;
                """, (nombre, json.dumps(token_dict), datetime.utcnow()))
                conn.commit()
        logger.info("✅ Token guardado en la base de datos.")
    except Exception as e:
        logger.error(f"❌ Error al guardar el token en la base de datos: {e}")
        raise

def leer_token_de_bd(nombre='calendar'):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT token_json FROM google_tokens WHERE nombre = %s LIMIT 1;",
                    (nombre,)
                )
                fila = cur.fetchone()
                if not fila:
                    raise Exception(f"⚠️ No se encontró ningún token con nombre '{nombre}' en la base de datos.")
                # Puede salir como str o dict, asegúrate de parsear
                token_info = fila[0]
                if isinstance(token_info, str):
                    token_info = json.loads(token_info)
                # Asegura el campo type
                if "type" not in token_info:
                    token_info["type"] = "authorized_user"
                return token_info
    except Exception as e:
        logger.error(f"❌ Error al leer el token de la base de datos: {e}")
        raise

from fastapi import Depends, status
from main_auth import *

logger = logging.getLogger(__name__)




def get_version():
    import google.auth
    from google.oauth2.credentials import Credentials as UserCredentials
    return {
        "google-auth-version": google.auth.__version__,
        "user_credentials_methods": dir(UserCredentials)
    }
# ==================== FIN PROYECTO CALENDAR =======================

# 🔊 Función para descargar audio desde WhatsApp Cloud API

def actualizar_contacto_info(telefono: str = Path(...), datos: ActualizacionContactoInfo = Body(...)):
    return actualizar_contacto_info_db(telefono, datos)



# ✅ VERIFICACIÓN DEL WEBHOOK (Facebook Developers)
@app.get("/webhook")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    print("📡 Verificación recibida:", params)
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(challenge or "")
    return PlainTextResponse("Verificación fallida", status_code=403)

async def actualizar_nombre(data: dict):
    telefono = data.get("telefono")
    nombre = data.get("nombre")
    if not telefono or not nombre:
        return JSONResponse({"error": "Faltan parámetros"}, status_code=400)
    actualizado = actualizar_nombre_contacto(telefono, nombre)
    if actualizado:
        return {"status": "ok", "mensaje": "Nombre actualizado"}
    else:
        return JSONResponse({"error": "No se pudo actualizar"}, status_code=500)

async def borrar_mensajes(telefono: str):
    eliminado = eliminar_mensajes(telefono)
    if eliminado:
        return {"status": "ok", "mensaje": f"Mensajes de {telefono} eliminados"}
    else:
        return JSONResponse({"error": "No se pudieron eliminar los mensajes"}, status_code=500)


# ===============================
# ENDPOINTS PARA ADMIN_USUARIO
# ===============================

async def test_conexion():
    """Prueba la conexión a la base de datos y la tabla admin_usuario"""
    try:
        import psycopg2
        from dotenv import load_dotenv
        load_dotenv()

        db_url = os.getenv("EXTERNAL_DATABASE_URL")
        print(f"🔗 Probando conexión a: {db_url}")

        conn = psycopg2.connect(db_url)
        cur = conn.cursor()

        # Verificar si la tabla existe
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'administradores'
            )
        """)
        table_exists = cur.fetchone()[0]

        if table_exists:
            # Contar registros
            cur.execute("SELECT COUNT(*) FROM administradores")
            count = cur.fetchone()[0]

            cur.close()
            conn.close()

            return {
                "status": "ok",
                "message": "Conexión exitosa",
                "table_exists": True,
                "record_count": count
            }
        else:
            cur.close()
            conn.close()

            return {
                "status": "warning",
                "message": "Conexión exitosa pero tabla no existe",
                "table_exists": False,
                "record_count": 0
            }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Error de conexión: {str(e)}",
            "table_exists": False,
            "record_count": 0
        }

@app.get("/api/admin-usuario", response_model=List[AdminUsuarioResponse])
async def obtener_usuarios():
    """Obtiene todos los usuarios administradores"""
    usuarios = obtener_todos_usuarioss()
    return usuarios

@app.post("/api/admin-usuario", response_model=AdminUsuarioResponse)
async def crear_usuario(usuario: AdminUsuarioCreate):
    """Crea un nuevo usuario administrador"""
    usuario_creado = crear_usuarios(usuario)
    return usuario_creado

async def obtener_usuario(usuario_id: int):
    """Obtiene un usuario administrador por ID"""
    usuario = obtener_usuarios_por_id(usuario_id)

    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return usuario


@app.delete("/api/admin-usuario/{usuario_id}")
async def eliminar_usuario(usuario_id: int):
    """Elimina un usuario administrador"""
    eliminar_usuarios(usuario_id)
    return {"mensaje": "Usuario eliminado exitosamente"}

@app.patch("/api/admin-usuario/{usuario_id}/activo")
async def cambiar_estado_usuario(usuario_id: int, activo: bool = Body(...)):
    """Cambia el estado activo/inactivo de un usuario administrador"""
    cambiar_estado_usuarios(usuario_id, activo)
    return {"mensaje": f"Estado actualizado a {'activo' if activo else 'inactivo'}"}

async def obtener_usuario_por_username(username: str):
    """Obtiene un usuario administrador por username (útil para autenticación)"""
    usuario = obtener_usuarios_por_username(username)

    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return usuario

@app.put("/api/admin-usuario/cambiar-password")
async def cambiar_password_admin(
    datos: ChangePasswordRequest = Body(...),
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    """
    Permite a cualquier usuario cambiar su propia contraseña, o a un administrador cambiar la de cualquier usuario.
    """
    # Asegura que los IDs se comparen como enteros
    if not es_admin(usuario_actual) and datos.user_id != int(usuario_actual["sub"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes cambiar la contraseña de otro usuario.")

    usuario = obtener_usuarios_por_id(datos.user_id)
    if not usuario:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    nuevo_hash = hash_password(datos.new_password)
    actualiza_password_usuario(datos.user_id, nuevo_hash)

    return {"mensaje": "Contraseña actualizada correctamente."}


@app.put("/api/admin-usuario/{usuario_id:int}", response_model=AdminUsuarioResponse)
async def actualizar_usuario(usuario_id: int, usuario: AdminUsuarioUpdate):
    try:
        usuario_actualizado = actualizar_usuarios(usuario_id, usuario.dict())
        if not usuario_actualizado:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        return usuario_actualizado
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error interno del servidor")

# Ejemplo de endpoint protegido
async def perfil(usuario: dict = Depends(obtener_usuario_actual)):
    return {"usuario": usuario}

from evaluaciones import *

# === Estadísticas globales de evaluación ===
def estadisticas_evaluacion():
    try:
        return obtener_estadisticas_evaluacion()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# filtrar responsables Agendas
@app.get("/api/responsable-Agenda", response_model=List[AdminUsuarioResponse])
async def obtener_responsables_agenda():
    """Obtiene todos los usuarios administradores"""
    usuarios = obtener_todos_responsables_agendas()
    return usuarios

# if __name__ == "__main__":
#     resultado = diagnostico_aspirantes_perfil(27)  # id de prueba
#     print(resultado)


@app.get("/api/admin-usuario_manager", response_model=List[AdminUsuarioManagerResponse])
async def obtener_usuarios_manager():
    """Obtiene todos los usuarios manager"""
    usuarios = obtener_todos_manager()
    return usuarios

@app.middleware("http")
async def disable_partial_content(request: Request, call_next):
    response = await call_next(request)

    # Solo actuar si la respuesta es 206
    if response.status_code == 206:
        # Si es un StreamingResponse, debemos consumir el contenido
        if isinstance(response, StreamingResponse):
            body = b"".join([chunk async for chunk in response.body_iterator])
            headers = dict(response.headers)
            headers.pop("content-range", None)
            headers.pop("accept-ranges", None)
            return Response(content=body, status_code=200, headers=headers)

        # Si es respuesta normal
        body = getattr(response, "body", None)
        if body:
            headers = dict(response.headers)
            headers.pop("content-range", None)
            headers.pop("accept-ranges", None)
            return Response(content=body, status_code=200, headers=headers)

    return response

from tenant import current_tenant
import requests

META_APP_ID = os.getenv("META_APP_ID")
META_APP_SECRET = os.getenv("META_APP_SECRET")
META_REDIRECT_URL = os.getenv("META_REDIRECT_URL")
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION") or "v24.0"


def _meta_json_error(message, status_code=400, error="meta_error"):
    return JSONResponse(
        status_code=status_code,
        content={"status": "error", "error": error, "message": message},
    )


def _is_invalid_agency_tenant(subdominio: str) -> bool:
    s = (subdominio or "").strip().lower()
    return s in ("", "public", "webhook_axec", "www", "api")


def _debug_token_app_id(access_token):
    """Return data.app_id from Meta debug_token. Never log tokens."""
    try:
        app_token = f"{META_APP_ID}|{META_APP_SECRET}"
        url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/debug_token"
        r = requests.get(
            url,
            params={"input_token": access_token, "access_token": app_token},
            timeout=30,
        )
        data = r.json() if r.content else {}
        payload = data.get("data") if isinstance(data, dict) else None
        if not isinstance(payload, dict):
            return None
        app_id = payload.get("app_id")
        return str(app_id) if app_id is not None else None
    except Exception:
        logging.exception("Error en debug_token (sin token en log)")
        return None


def _fetch_phone_in_waba(access_token, waba_id, phone_number_id):
    """Return {id, display_phone_number, verified_name} or None."""
    try:
        url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{waba_id}/phone_numbers"
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            params={"fields": "id,display_phone_number,verified_name"},
            timeout=30,
        )
        data = r.json() if r.content else {}
        if r.status_code >= 400 or (isinstance(data, dict) and data.get("error")):
            logging.warning("No se pudieron listar phone_numbers de la WABA")
            return None
        phones = data.get("data") or []
        target = str(phone_number_id)
        for p in phones:
            if str(p.get("id")) == target:
                return {
                    "id": p.get("id"),
                    "display_phone_number": p.get("display_phone_number"),
                    "verified_name": p.get("verified_name"),
                }
        return None
    except Exception:
        logging.exception("Error validando phone_number_id contra WABA")
        return None


def _subscribe_waba(access_token, waba_id) -> bool:
    try:
        url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{waba_id}/subscribed_apps"
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )
        data = r.json() if r.content else {}
        if r.status_code < 400 and data.get("success") is True:
            return True
        err_msg = str((data.get("error") or {}).get("message") or "").lower()
        if "already" in err_msg or "subscribed" in err_msg:
            return True
        logging.warning("Suscripcion WABA fallida (sin token en log) status=%s", r.status_code)
        return False
    except Exception:
        logging.exception("Error suscribiendo app a WABA")
        return False


def _waba_has_meta_app_subscribed(access_token, waba_id):
    """Return (ok, list of {id, name}) based on subscribed_apps."""
    try:
        url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{waba_id}/subscribed_apps"
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )
        data = r.json() if r.content else {}
        if r.status_code >= 400 or (isinstance(data, dict) and data.get("error")):
            logging.warning("No se pudo listar subscribed_apps de la WABA")
            return False, []
        apps = data.get("data") or []
        summarized = []
        ok = False
        target = str(META_APP_ID) if META_APP_ID is not None else ""
        for app in apps:
            api_data = app.get("whatsapp_business_api_data") or {}
            app_id = api_data.get("id")
            name = api_data.get("name") or app.get("name")
            summarized.append({"id": app_id, "name": name})
            if str(app_id) == target:
                ok = True
        return ok, summarized
    except Exception:
        logging.exception("Error consultando subscribed_apps")
        return False, []


@app.api_route("/meta/exchange_code", methods=["GET", "POST", "OPTIONS"])
async def exchange_code(request: Request):
    """Intercambia el 'code' OAuth de Meta por un access_token temporal.
    Si el WABA ID ya esta en base de datos, completa la vinculacion automaticamente.
    """
    if request.method == "OPTIONS":
        return JSONResponse(
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )

    try:
        if request.method == "GET":
            code = request.query_params.get("code")
            redirect_uri = request.query_params.get("redirect_uri", META_REDIRECT_URL)
        else:
            payload = await request.json()
            code = payload.get("code")
            redirect_uri = payload.get("redirect_uri", META_REDIRECT_URL)

        if not code:
            return JSONResponse(
                status_code=400,
                content={"error": "missing_code", "message": "El parametro 'code' es requerido"},
                headers={"Access-Control-Allow-Origin": "*"}
            )

        logging.info("Codigo OAuth recibido: %s...%s", code[:6], code[-6:])
        logging.info("Intercambiando code con Meta...")

        token_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/oauth/access_token"
        params = {
            "code": code,
            "client_id": META_APP_ID,
            "client_secret": META_APP_SECRET
        }
        r = requests.get(token_url, params=params, timeout=30)
        data = r.json()

        # Do NOT log full token response (security). Log only error keys if fail.
        access_token = data.get("access_token")
        if not access_token:
            err = data.get("error") if isinstance(data.get("error"), dict) else {}
            logging.warning(
                "Meta OAuth falló status=%s type=%s code=%s subcode=%s message=%s fbtrace_id=%s",
                r.status_code,
                err.get("type"),
                err.get("code"),
                err.get("error_subcode"),
                err.get("message"),
                err.get("fbtrace_id"),
            )
            return JSONResponse(
                status_code=400,
                content={"error": "no_access_token", "message": "Meta no devolvio access_token"},
                headers={"Access-Control-Allow-Origin": "*"}
            )

        session_id = "abc123"
        resultado_token = guardar_o_actualizar_token_db(session_id, access_token)

        if resultado_token["status"] == "completado":
            actualizado = actualizar_info_phone(resultado_token)
            if actualizado:
                logging.info("Phone info actualizada para WABA %s", resultado_token.get("waba_id"))

        return JSONResponse(
            status_code=200,
            content={
                "status": resultado_token["status"],
                "waba_id": resultado_token.get("waba_id"),
                "id": resultado_token.get("id"),
                "message": "Token procesado correctamente."
            },
            headers={"Access-Control-Allow-Origin": "*"}
        )

    except Exception:
        logging.exception("Error inesperado en /meta/exchange_code")
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": "Error interno al procesar el codigo"},
            headers={"Access-Control-Allow-Origin": "*"}
        )


@app.post("/meta/exchange_code_business_app")
async def exchange_code_business_app(request: Request):
    """Coexistencia: Embedded Signup whatsapp_business_app_onboarding."""
    try:
        payload = await request.json()
    except Exception:
        return _meta_json_error("JSON invalido", error="invalid_payload")

    code = (payload.get("code") or "").strip()
    waba_id = (payload.get("waba_id") or "").strip()
    phone_number_id = (
        payload.get("phone_number_id") or payload.get("phone_id") or ""
    ).strip()
    onboarding_type = (payload.get("onboarding_type") or "").strip()
    redirect_uri = payload.get("redirect_uri")
    if isinstance(redirect_uri, str):
        redirect_uri = redirect_uri.strip() or None
    else:
        redirect_uri = None
    business_id = payload.get("business_id")
    if isinstance(business_id, str):
        business_id = business_id.strip() or None

    if not code:
        return _meta_json_error("Se requiere el parametro code", error="missing_code")
    if not waba_id or not phone_number_id:
        return _meta_json_error(
            "Se requieren waba_id y phone_number_id",
            error="missing_fields",
        )
    if onboarding_type != "whatsapp_business_app_onboarding":
        return _meta_json_error(
            "onboarding_type debe ser whatsapp_business_app_onboarding",
            error="invalid_onboarding_type",
        )

    # subdominio web (X-Tenant-Name / host), no el schema PostgreSQL
    subdominio = (getattr(request.state, "tenant_name", None) or "").strip().lower()
    if not subdominio:
        try:
            subdominio = (current_tenant.get() or "").strip().lower()
        except Exception:
            subdominio = ""
    if _is_invalid_agency_tenant(subdominio):
        return _meta_json_error(
            "No se pudo identificar la agencia que inició la conexión.",
            error="missing_tenant",
        )

    if not META_APP_ID or not META_APP_SECRET:
        return _meta_json_error(
            "Configuracion Meta incompleta en el servidor",
            error="server_config",
            status_code=500,
        )

    token_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/oauth/access_token"
    params = {
        "code": code,
        "client_id": META_APP_ID,
        "client_secret": META_APP_SECRET,
    }
    if redirect_uri:
        params["redirect_uri"] = redirect_uri

    try:
        r = requests.get(token_url, params=params, timeout=30)
        data = r.json() if r.content else {}
    except Exception:
        logging.exception("Error contactando Meta oauth/access_token (Business App)")
        return _meta_json_error(
            "No fue posible completar la conexion con Meta.",
            status_code=502,
        )

    access_token = data.get("access_token") if isinstance(data, dict) else None
    if r.status_code >= 400 or (isinstance(data, dict) and data.get("error")) or not access_token:
        err = data.get("error") if isinstance(data, dict) and isinstance(data.get("error"), dict) else {}
        logging.warning(
            "Meta OAuth Business App fallo status=%s type=%s code=%s subcode=%s message=%s fbtrace_id=%s",
            r.status_code,
            err.get("type"),
            err.get("code"),
            err.get("error_subcode"),
            err.get("message"),
            err.get("fbtrace_id"),
        )
        return _meta_json_error(
            "No fue posible completar la conexion con Meta.",
            error="oauth_failed",
            status_code=502,
        )

    token_app_id = _debug_token_app_id(access_token)
    if not token_app_id or str(token_app_id) != str(META_APP_ID):
        return _meta_json_error(
            "El token obtenido no corresponde a la aplicación de Meta configurada para Talentum Manager.",
            error="invalid_app_token",
            status_code=422,
        )

    phone = _fetch_phone_in_waba(access_token, waba_id, phone_number_id)
    if not phone:
        return _meta_json_error(
            "El número conectado no pertenece a la WABA seleccionada.",
            error="phone_waba_mismatch",
            status_code=422,
        )

    if not _subscribe_waba(access_token, waba_id):
        return _meta_json_error(
            "No fue posible suscribir la aplicación a la WABA.",
            error="subscribe_failed",
            status_code=502,
        )

    subscribed_ok, subscribed_apps = _waba_has_meta_app_subscribed(access_token, waba_id)
    logging.info(
        "Aplicaciones suscritas a WABA %s: %s",
        waba_id,
        [{"id": a.get("id"), "name": a.get("name")} for a in subscribed_apps],
    )
    if not subscribed_ok:
        return _meta_json_error(
            "La WABA fue procesada, pero no quedó suscrita a la aplicación de Meta configurada para Talentum Manager.",
            error="app_not_subscribed",
            status_code=422,
        )

    phone_number = phone.get("display_phone_number")
    business_name = phone.get("verified_name")

    resultado = guardar_o_actualizar_whatsapp_business_account(
        subdominio=subdominio,
        access_token=access_token,
        waba_id=waba_id,
        phone_number_id=phone_number_id,
        business_id=business_id,
        onboarding_type="whatsapp_business_app_onboarding",
        coexistence_enabled=True,
        phone_number=phone_number,
        business_name=business_name,
        session_id="",
    )

    if resultado.get("status") == "error":
        return _meta_json_error(
            "No fue posible guardar la conexión.",
            error="db_error",
            status_code=500,
        )

    return JSONResponse(
        status_code=200,
        content={
            "status": "connected",
            "id": resultado.get("id"),
            "waba_id": waba_id,
            "phone_number_id": phone_number_id,
            "phone_number": phone_number,
            "business_name": business_name,
            "subdominio": subdominio,
            "subscribed_app_id": str(META_APP_ID),
            "message": "WhatsApp Business existente conectado, suscrito y guardado correctamente.",
        },
    )

# from borrar_rate_limiter import get_rate_limiter

async def debug():
    return {"tenant": current_tenant.get()}

@app.on_event("startup")
def log_routes():
    logger.info("📌 RUTAS REGISTRADAS:")
    for route in app.routes:
        if hasattr(route, "methods"):
            logger.info(f"➡️ {route.path} {route.methods}")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error("❌ 422 VALIDATION ERROR")
    logger.error(f"➡️ URL: {request.method} {request.url}")
    logger.error(f"➡️ HEADERS: {dict(request.headers)}")
    logger.error(f"➡️ ERRORS: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()}
    )

