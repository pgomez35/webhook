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
    guardar_o_actualizar_token_db, hash_password
from schemas import *

# Tu propio código/librerías
from enviar_msg_wp import *
# from borrar_buscador import inicializar_busqueda, responder_pregunta
# from DataBase import *
from Excel import *

# from borrar_utils import actualizar_info_phone

# 🔄 Cargar variables de entorno
load_dotenv()
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

from main_webhook import router as aspirantes_perfil_router
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
from main_portal_aspirantes import router as main_portal_aspirantes_router
from main_estadisticas_aspirantes import router as main_estadisticas_router
from main_creadores_perfil import router as main_creadores_perfil_router

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
app.include_router(main_estadisticas_router, tags=["estadisticas aspirantes"])
app.include_router(main_creadores_perfil_router, tags=["creadores perfil"])

# ✅ Configurar correctamente CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://talentum-manager.com",
        "https://test.talentum-manager.com",
        "https://prestige.talentum-manager.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-Tenant-Name"],
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


# CREADORES ACTIVOS

# 1. Listar todos los aspirantes activos
@app.get("/api/creadores_activos", response_model=List[CreadorActivoDB])
def listar_creadores_activos():
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM creadores_activos")
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
                result = [dict(zip(columns, row)) for row in rows]
                return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 2. Obtener un creador activo por ID
@app.get("/api/creadores_activos/{id}", response_model=CreadorActivoConManager)
def obtener_creador_activo(id: int):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT ca.*, au.nombre_completo AS manager_nombre
                    FROM creadores_activos ca
                    LEFT JOIN administradores au ON ca.manager_id = au.id
                    WHERE ca.id = %s
                """, (id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Creador no encontrado")
                columns = [desc[0] for desc in cur.description]
                return dict(zip(columns, row))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 3. Agregar un nuevo creador activo
@app.post("/api/creadores_activos", response_model=CreadorActivoDB, status_code=201)
def agregar_creador_activo(creador: CreadorActivoCreate):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO creadores_activos (
                        aspirante_id, nombre, usuario_tiktok, foto, categoria, estado, manager_id,
                        horario_lives, tiempo_disponible, fecha_incorporacion, fecha_graduacion,
                        seguidores, videos, me_gusta, diamantes, horas_live, numero_partidas, dias_emision
                    ) VALUES (
                        %(aspirante_id)s, %(nombre)s, %(usuario_tiktok)s, %(foto)s, %(categoria)s, %(estado)s, %(manager_id)s,
                        %(horario_lives)s, %(tiempo_disponible)s, %(fecha_incorporacion)s, %(fecha_graduacion)s,
                        %(seguidores)s, %(videos)s, %(me_gusta)s, %(diamantes)s, %(horas_live)s, %(numero_partidas)s, %(dias_emision)s
                    ) RETURNING *;
                """, creador.dict())
                row = cur.fetchone()
                conn.commit()
                columns = [desc[0] for desc in cur.description]
                return dict(zip(columns, row))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 4. Editar un creador activo existente
@app.put("/api/creadores_activos/{id}", response_model=CreadorActivoDB)
def editar_creador_activo(id: int, creador: CreadorActivoUpdate):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE creadores_activos SET
                        aspirante_id=%(aspirante_id)s,
                        nombre=%(nombre)s,
                        usuario_tiktok=%(usuario_tiktok)s,
                        foto=%(foto)s,
                        categoria=%(categoria)s,
                        estado=%(estado)s,
                        manager_id=%(manager_id)s,
                        horario_lives=%(horario_lives)s,
                        tiempo_disponible=%(tiempo_disponible)s,
                        fecha_incorporacion=%(fecha_incorporacion)s,
                        fecha_graduacion=%(fecha_graduacion)s,
                        seguidores=%(seguidores)s,
                        videos=%(videos)s,
                        me_gusta=%(me_gusta)s,
                        diamantes=%(diamantes)s,
                        horas_live=%(horas_live)s,
                        numero_partidas=%(numero_partidas)s,
                        dias_emision=%(dias_emision)s
                    WHERE id=%(id)s
                    RETURNING *;
                """, {**creador.dict(), "id": id})
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Creador no encontrado")
                conn.commit()
                columns = [desc[0] for desc in cur.description]
                return dict(zip(columns, row))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin-usuario_manager", response_model=List[AdminUsuarioManagerResponse])
async def obtener_usuarios_manager():
    """Obtiene todos los usuarios manager"""
    usuarios = obtener_todos_manager()
    return usuarios

@app.post("/api/creadores_activos/auto", response_model=dict)
def crear_creador_activo_automatico(data: CreadorActivoAutoCreate):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # 1. Buscar datos del creador en la tabla   aspirantes
                cur.execute("""
                    SELECT
                        id,
                        usuario AS usuario_tiktok,
                        foto_url AS foto,
                        NULL AS categoria,
                        'activo' AS estado,
                        nickname AS nombre
                    FROM   aspirantes
                    WHERE id = %s
                """, (data.aspirante_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Creador no encontrado")

                creador = dict(zip([desc[0] for desc in cur.description], row))

                # 2. Preparar valores para insertar en creadores_activos
                valores = {
                    "aspirante_id": creador["id"],
                    "usuario_tiktok": creador["usuario_tiktok"],
                    "foto": creador["foto"],
                    "categoria": creador["categoria"],
                    "estado": creador["estado"],
                    "nombre": creador["nombre"],
                    "manager_id": data.manager_id,  # puede ser None
                    "fecha_incorporacion": data.fecha_incorporacion or date.today(),
                    "horario_lives": None,
                    "tiempo_disponible": None,
                    "fecha_graduacion": None,
                    "seguidores": None,
                    "videos": None,
                    "me_gusta": None,
                    "diamantes": None,
                    "horas_live": None,
                    "numero_partidas": None,
                    "dias_emision": None
                }

                # 3. Insertar en creadores_activos
                cur.execute("""
                    INSERT INTO creadores_activos (
                        aspirante_id, usuario_tiktok, foto, categoria, estado, nombre,
                        manager_id, horario_lives, tiempo_disponible, fecha_incorporacion, fecha_graduacion,
                        seguidores, videos, me_gusta, diamantes, horas_live, numero_partidas, dias_emision
                    ) VALUES (
                        %(aspirante_id)s, %(usuario_tiktok)s, %(foto)s, %(categoria)s, %(estado)s, %(nombre)s,
                        %(manager_id)s, %(horario_lives)s, %(tiempo_disponible)s, %(fecha_incorporacion)s, %(fecha_graduacion)s,
                        %(seguidores)s, %(videos)s, %(me_gusta)s, %(diamantes)s, %(horas_live)s, %(numero_partidas)s, %(dias_emision)s
                    )
                    RETURNING *;
                """, valores)
                new_row = cur.fetchone()
                conn.commit()
                columns = [desc[0] for desc in cur.description]
                return dict(zip(columns, new_row))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al crear creador activo: {e}")

# SEGUIMIENTO DE CREADORES
@app.post("/api/seguimiento_creadores/", response_model=SeguimientoCreadorDB)
def crear_seguimiento_creador(seg: SeguimientoCreadorCreate):
    try:
        # 1. Obtener manager_id de creadores_activos
        if not seg.creador_activo_id:
            raise HTTPException(status_code=400, detail="creador_activo_id es requerido")

        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT manager_id FROM creadores_activos WHERE id = %s
                """, (seg.creador_activo_id,))
                result = cur.fetchone()
                if not result:
                    raise HTTPException(status_code=404, detail="No se encontró el creador activo")
                manager_id = result[0]

                # 2. Insertar seguimiento usando manager_id obtenido
                cur.execute("""
                    INSERT INTO creadores_seguimiento (
                        aspirante_id, creador_activo_id, manager_id, fecha_seguimiento,
                        estrategias_mejora, compromisos
                    ) VALUES (
                        %(aspirante_id)s, %(creador_activo_id)s, %(manager_id)s, %(fecha_seguimiento)s,
                        %(estrategias_mejora)s, %(compromisos)s
                    )
                    RETURNING *;
                """, {
                    **seg.dict(),
                    "manager_id": manager_id
                })
                row = cur.fetchone()
                conn.commit()
                columns = [desc[0] for desc in cur.description]
                return dict(zip(columns, row))
    except HTTPException:
        raise
    except Exception as e:
        print("ERROR:", e)  # o usa logging
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/seguimiento_creadores/creador_activo/{creador_activo_id}", response_model=List[SeguimientoCreadorConManager])
def listar_seguimientos_por_creador_activo(creador_activo_id: int):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT sc.*, au.nombre_completo AS manager_nombre
                    FROM creadores_seguimiento sc
                    LEFT JOIN administradores au ON sc.manager_id = au.id
                    WHERE sc.creador_activo_id = %s
                    ORDER BY sc.fecha_seguimiento DESC
                """, (creador_activo_id,))
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/estadisticas_creadores/cargar_excel/")
async def cargar_estadisticas_excel(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        # Lee encabezados desde la segunda fila (índice 1)
        df = pd.read_excel(io.BytesIO(contents), header=1)

        # Limpia los encabezados: remueve espacios y dos puntos
        df.columns = [col.strip().replace(":", "") for col in df.columns]

        required_columns = [
            "ID de creador", "Nombre de usuario del creador", "Grupo",
            "Diamantes de los últimos 30 días",
            "Duración de emisiones LIVE en los últimos 30 días",
            "Seguidores", "Vídeos", "Me gusta"
        ]
        for col in required_columns:
            if col not in df.columns:
                raise HTTPException(status_code=400, detail=f"Falta columna: {col}")

        with get_connection_context() as conn:
            with conn.cursor() as cur:
                creados = 0
                actualizados = 0

                for _, row in df.iterrows():
                    usuario_tiktok = str(row["Nombre de usuario del creador"]).strip()
                    grupo = str(row["Grupo"])
                    seguidores = int(row["Seguidores"])
                    videos = int(row["Vídeos"])
                    me_gusta = int(row["Me gusta"])
                    diamantes = int(row["Diamantes de los últimos 30 días"])
                    duracion_lives = int(row["Duración de emisiones LIVE en los últimos 30 días"])

                    # Buscar el registro en creadores_activos
                    cur.execute("""
                        SELECT id, aspirante_id FROM creadores_activos WHERE usuario_tiktok = %s
                    """, (usuario_tiktok,))
                    res = cur.fetchone()
                    if not res:
                        continue

                    creador_activo_id, aspirante_id = res

                    cur.execute("""
                        INSERT INTO estadisticas_creadores (
                            aspirante_id, creador_activo_id, fecha_reporte, grupo, diamantes_ult_30, duracion_emsiones_live_ult_30
                        ) VALUES (%s, %s, CURRENT_DATE, %s, %s, %s)
                    """, (
                        aspirante_id,
                        creador_activo_id,
                        grupo,
                        diamantes,
                        duracion_lives
                    ))
                    creados += 1

                    cur.execute("""
                        UPDATE creadores_activos
                        SET seguidores = %s, me_gusta = %s, videos = %s
                        WHERE id = %s
                    """, (seguidores, me_gusta, videos, creador_activo_id))
                    actualizados += 1

                conn.commit()
                return {
                    "ok": True,
                    "registros_creados": creados,
                    "registros_actualizados": actualizados
                }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar el archivo: {e}")

def obtener_estadisticas_por_creador(creador_activo_id: int):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM estadisticas_creadores WHERE creador_activo_id = %s",
                (creador_activo_id,)
            )
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
            resultados = [dict(zip(columns, row)) for row in rows]
            return resultados

# 2. Consultar la URL de la foto
@app.get("/creadores_activos/{creador_activo_id}/foto")
def obtener_foto_creador_activo(creador_activo_id: int):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT foto FROM creadores_activos WHERE id = %s", (creador_activo_id,)
            )
            res = cur.fetchone()
            if not res or not res[0]:
                raise HTTPException(status_code=404, detail="Foto no encontrada")
            return {"foto_url": res[0]}

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

META_APP_ID = os.getenv("META_APP_ID")
META_APP_SECRET = os.getenv("META_APP_SECRET")
META_REDIRECT_URL = os.getenv("META_REDIRECT_URL")
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION")

@app.api_route("/meta/exchange_code", methods=["GET", "POST", "OPTIONS"])
async def exchange_code(request: Request):
    """Intercambia el 'code' OAuth de Meta por un access_token temporal.
    Si el WABA ID ya está en base de datos, completa la vinculación automáticamente.
    """

    # ✅ Manejo de preflight (CORS)
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
        # ✅ Obtener parámetros según método
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
                content={"error": "missing_code", "message": "El parámetro 'code' es requerido"},
                headers={"Access-Control-Allow-Origin": "*"}
            )

        logging.info(f"📥 Código OAuth recibido: {code[:6]}...{code[-6:]}")
        logging.info("🔄 Intercambiando code con Meta...")

        # ✅ Solicitud a Meta
        token_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/oauth/access_token"
        params = {
            "code": code,
            "client_id": META_APP_ID,
            "client_secret": META_APP_SECRET
        }
        r = requests.get(token_url, params=params, timeout=30)
        data = r.json()

        logging.info(f"📤 Respuesta Meta: {json.dumps(data, indent=2)}")

        # ✅ Validar respuesta
        access_token = data.get("access_token")
        if not access_token:
            return JSONResponse(
                status_code=400,
                content={"error": "no_access_token", "message": "Meta no devolvió access_token"},
                headers={"Access-Control-Allow-Origin": "*"}
            )

        # 🆔 Sesión temporal
        session_id = "abc123"

        # ✅ Guardar o actualizar token en DB
        resultado_token = guardar_o_actualizar_token_db(session_id, access_token)

        # ✅ Si existe WABA y TOKEN, completar vínculo y actualizar phone info
        if resultado_token["status"] == "completado":
            actualizado = actualizar_info_phone(resultado_token)
            if actualizado:
                logging.info(f"📞 Phone info actualizada para WABA {resultado_token['waba_id']}")

        # ✅ Respuesta final
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

    except Exception as e:
        logging.exception("❌ Error inesperado en /meta/exchange_code")
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": str(e)},
            headers={"Access-Control-Allow-Origin": "*"}
        )

from tenant import current_tenant
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

