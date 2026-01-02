import os
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, APIRouter, status, Body
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt, JWTError, ExpiredSignatureError
from pydantic import BaseModel
from DataBase import get_connection_context, autenticar_admin_usuario
from dotenv import load_dotenv
import logging
import bcrypt

# ================= CONFIG =================
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY no está definido")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 7

logger = logging.getLogger("uvicorn.error")

# ================= ROUTER =================
router = APIRouter()   # ← ESTE ES EL ROUTER QUE VAS A IMPORTAR EN main.py

# OAuth2 apunta al endpoint de login que DEFINIMOS abajo
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/login"
)

# ================= MODELOS =================
class UsuarioOut(BaseModel):
    id: int
    nombre: str
    rol: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    usuario: UsuarioOut


# ================= TOKENS =================
def crear_access_token(usuario: dict) -> str:
    payload = {
        "sub": str(usuario["id"]),
        "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def crear_refresh_token(usuario: dict) -> str:
    payload = {
        "sub": str(usuario["id"]),
        "tipo": "refresh",
        "exp": datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


# ================= UTILIDADES =================
def verificar_password(password_plano: str, password_hash: str) -> bool:
    return bcrypt.checkpw(
        password_plano.encode("utf-8"),
        password_hash.encode("utf-8")
    )


# ================= DEPENDENCY =================
def obtener_usuario_actual(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        print("🔥 [AUTH] Entró a obtener_usuario_actual")
        print("🔥 [AUTH] Token recibido:", token)

        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")

        if not user_id:
            raise HTTPException(status_code=401, detail="Token inválido")

        with get_connection_context() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, nombre_completo, rol, activo
                FROM admin_usuario
                WHERE id = %s
            """, (user_id,))
            row = cursor.fetchone()

        if not row or not row[3]:
            raise HTTPException(status_code=401, detail="Usuario no encontrado o inactivo")

        return {
            "id": row[0],
            "nombre": row[1],
            "rol": row[2]
        }

    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")


# ================= ENDPOINTS =================
# === LOGIN ===
@router.post("/login", response_model=TokenResponse)
async def login_usuario(credentials: dict = Body(...)):
    print("🔥 ENTRÓ AL LOGIN")
    print("📥 credentials:", credentials)
    username = credentials.get("username", "").strip().lower()
    password = credentials.get("password", "")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username y password son requeridos")

    resultado = autenticar_admin_usuario(username, password)
    if resultado["status"] != "ok":
        raise HTTPException(status_code=401, detail=resultado["mensaje"])

    usuario = resultado["usuario"]

    access_token = crear_access_token(usuario)
    refresh_token = crear_refresh_token(usuario)

    return TokenResponse(
        usuario=UsuarioOut(
            id=usuario["id"],
            nombre=usuario["nombre"],
            rol=usuario["rol"]
        ),
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        mensaje="Login exitoso"
    )


@router.get("/me", response_model=UsuarioOut)
def get_me(usuario_actual: dict = Depends(obtener_usuario_actual)):
    print("✅ [ME] Entró al endpoint /me")
    print("✅ [ME] usuario_actual:", usuario_actual)
    return UsuarioOut(
        id=usuario_actual["id"],
        nombre=usuario_actual["nombre"],
        rol=usuario_actual["rol"]
    )

# === REFRESH TOKEN ===
@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(data: dict = Body(...)):
    refresh_token = data.get("refresh_token")

    if not refresh_token:
        raise HTTPException(status_code=400, detail="Refresh token requerido")

    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])

        # Validar que sea refresh
        if payload.get("tipo") != "refresh":
            raise HTTPException(status_code=401, detail="Token inválido")

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token inválido")

        # Buscar usuario
        with get_connection_context() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, nombre_completo, rol, activo FROM admin_usuario WHERE id = %s",
                (user_id,)
            )
            row = cursor.fetchone()

        if not row or not row[3]:
            raise HTTPException(status_code=401, detail="Usuario no encontrado o inactivo")

        usuario = {
            "id": row[0],
            "nombre": row[1],
            "rol": row[2]
        }

        # Crear nuevo access token
        new_access_token = crear_access_token(usuario)

        return TokenResponse(
            access_token=new_access_token,
            refresh_token=refresh_token,  # se reutiliza
            token_type="bearer",
            usuario=UsuarioOut(**usuario),
            mensaje="Token renovado"
        )

    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expirado")
    except JWTError:
        raise HTTPException(status_code=401, detail="Refresh token inválido")


# === REFRESH ===
# @router.post("/refresh", response_model=TokenResponse)
# async def refresh_token(data: dict = Body(...)):
#     token = data.get("refresh_token")
#     if not token:
#         raise HTTPException(status_code=400, detail="refresh_token requerido")
#
#     try:
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         if payload.get("tipo") != "refresh":
#             raise HTTPException(status_code=401, detail="Token inválido")
#
#         user_id = payload.get("sub")
#
#         # validar usuario en DB
#         with get_connection_context() as conn:
#             cursor = conn.cursor()
#             cursor.execute(
#                 "SELECT id, nombre_completo AS nombre, rol, activo FROM admin_usuario WHERE id = %s",
#                 (user_id,),
#             )
#             row = cursor.fetchone()
#
#         if not row or not row[3]:
#             raise HTTPException(status_code=401, detail="Usuario no encontrado o inactivo")
#
#         usuario = {"id": row[0], "nombre": row[1], "rol": row[2]}
#         new_access_token = crear_access_token(usuario)
#
#         return TokenResponse(
#             access_token=new_access_token,
#             refresh_token=token,  # opcional: devolver el mismo refresh token
#             token_type="bearer",
#             mensaje="Access token renovado",
#             usuario=UsuarioOut(**usuario)
#         )
#
#     except ExpiredSignatureError:
#         raise HTTPException(status_code=401, detail="refresh_token expirado")
#     except JWTError:
#         raise HTTPException(status_code=401, detail="refresh_token inválido")


# import os
# from datetime import datetime, timedelta
# from fastapi import Depends, HTTPException, Body, APIRouter
# from fastapi.security import OAuth2PasswordBearer
# from jose import jwt, JWTError, ExpiredSignatureError
# from pydantic import BaseModel
# from DataBase import get_connection, get_connection_context
# from dotenv import load_dotenv  # Solo si usas variables de entorno
#
# load_dotenv()
#
# SECRET_KEY = os.getenv("SECRET_KEY")
# ALGORITHM = "HS256"
#
# ACCESS_TOKEN_EXPIRE_MINUTES = 60   # puedes subir a 30–60 min
# REFRESH_TOKEN_EXPIRE_DAYS = 7
#
# oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/admin-usuario/login")
# router = APIRouter(prefix="/api/admin-usuario")
#
#
# # === MODELOS Pydantic ===
# class UsuarioOut(BaseModel):
#     id: int
#     nombre: str
#     rol: str
#
#
# class TokenResponse(BaseModel):
#     access_token: str
#     refresh_token: str | None = None
#     token_type: str = "bearer"
#     usuario: UsuarioOut | None = None
#     mensaje: str | None = None
#
#
# # === CREAR TOKENS ===
# def crear_access_token(usuario: dict) -> str:
#     data = {
#         "sub": str(usuario["id"]),
#         "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
#     }
#     return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)
#
#
# def crear_refresh_token(usuario: dict) -> str:
#     data = {
#         "sub": str(usuario["id"]),
#         "tipo": "refresh",
#         "exp": datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
#     }
#     return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)
#
# import logging
# logger = logging.getLogger("uvicorn.error")
#
# def obtener_usuario_actual(token: str = Depends(oauth2_scheme)) -> dict:
#     try:
#         logger.info(f"DEBUG: Token recibido: {token}")
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         logger.info(f"DEBUG: Payload decodificado: {payload}")
#         user_id = payload.get("sub")
#         if not user_id:
#             raise HTTPException(status_code=401, detail="Token inválido")
#
#         with get_connection_context() as conn:
#             cursor = conn.cursor()
#             cursor.execute(
#                 "SELECT id, nombre_completo, rol, activo FROM admin_usuario WHERE id = %s",
#                 (user_id,)
#             )
#             row = cursor.fetchone()
#
#         logger.info(f"DEBUG: Usuario DB: {row}")
#         if not row or not row[3]:
#             raise HTTPException(status_code=401, detail="Usuario no encontrado o inactivo")
#
#         return {"id": row[0], "nombre": row[1], "rol": row[2]}
#
#     except ExpiredSignatureError:
#         logger.warning("DEBUG: Token expirado")
#         raise HTTPException(status_code=401, detail="Token expirado")
#     except JWTError:
#         logger.warning("DEBUG: Token inválido")
#         raise HTTPException(status_code=401, detail="Token inválido")

# # === DEPENDENCIA: USUARIO ACTUAL ===
# def obtener_usuario_actual(token: str = Depends(oauth2_scheme)) -> dict:
#     try:
#         print("DEBUG: Token recibido:", token)  # log
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         print("DEBUG: Payload decodificado:", payload)
#         user_id = payload.get("sub")
#         if not user_id:
#             raise HTTPException(status_code=401, detail="Token inválido")
#
#         with get_connection() as conn:
#             cursor = conn.cursor()
#             cursor.execute(
#                 "SELECT id, nombre_completo, rol, activo FROM admin_usuario WHERE id = %s",
#                 (user_id,)
#             )
#             row = cursor.fetchone()
#
#         print("DEBUG: Usuario DB:", row)
#         if not row or not row[3]:
#             raise HTTPException(status_code=401, detail="Usuario no encontrado o inactivo")
#
#         return {"id": row[0], "nombre": row[1], "rol": row[2]}
#
#     except ExpiredSignatureError:
#         print("DEBUG: Token expirado")
#         raise HTTPException(status_code=401, detail="Token expirado")
#     except JWTError:
#         print("DEBUG: Token inválido")
#         raise HTTPException(status_code=401, detail="Token inválido")



# from datetime import datetime, timedelta
# from fastapi import Depends, HTTPException, Body, APIRouter
# from fastapi.security import OAuth2PasswordBearer
# from jose import jwt, JWTError
# from DataBase import get_connection
#
# SECRET_KEY = "CLAVE_SECRETA"
# ALGORITHM = "HS256"
#
# ACCESS_TOKEN_EXPIRE_MINUTES = 15
# REFRESH_TOKEN_EXPIRE_DAYS = 7
#
# oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/admin-usuario/login")
#
# router = APIRouter(prefix="/api/admin-usuario")
#
#
# # ========== CREAR TOKENS ==========
# def crear_access_token(usuario: dict) -> str:
#     data = {
#         "sub": str(usuario["id"]),
#         "nombre": usuario["nombre_completo"],
#         "rol": usuario["rol"],
#         "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
#     }
#     return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)
#
#
# def crear_refresh_token(usuario: dict) -> str:
#     data = {
#         "sub": str(usuario["id"]),
#         "tipo": "refresh",
#         "exp": datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
#     }
#     return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)
#
#
# # ========== DEPENDENCIAS ==========
# def obtener_usuario_actual(token: str = Depends(oauth2_scheme)) -> dict:
#     try:
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         user_id = payload.get("sub")
#         if not user_id:
#             raise HTTPException(status_code=401, detail="Token inválido")
#
#         # validar en DB
#         conn = get_connection()
#         cursor = conn.cursor()
#         cursor.execute(
#             "SELECT id, nombre_completo, rol, activo FROM admin_usuario WHERE id = %s",
#             (user_id,)
#         )
#         row = cursor.fetchone()
#         cursor.close()
#         conn.close()
#
#         if not row or not row[3]:
#             raise HTTPException(status_code=401, detail="Usuario no encontrado o inactivo")
#
#         return {"id": row[0], "nombre": row[1], "rol": row[2]}
#     except JWTError:
#         raise HTTPException(status_code=401, detail="Token inválido")
#
#
# # from datetime import datetime, timedelta
# #
# # from fastapi import Depends, HTTPException
# # from fastapi.security import OAuth2PasswordBearer
# # from jose import jwt, JWTError
# # from DataBase import get_connection
# #
# # SECRET_KEY = "CLAVE_SECRETA"
# # ALGORITHM = "HS256"
# # ACCESS_TOKEN_EXPIRE_HOURS = 8
# # # oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
# # oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/admin-usuario/login")
# #
# #
# # # Función para crear el JWT
# # def crear_token_jwt(usuario: dict) -> str:
# #     data = {
# #         "sub": str(usuario["id"]),   # 👈 siempre será el ID del usuario
# #         "nombre": usuario["nombre_completo"], # 👈 consistente con obtener_usuario_actual
# #         "rol": usuario["rol"],
# #         "exp": datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
# #     }
# #     return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)
# #
# #
# # def obtener_usuario_actual(token: str = Depends(oauth2_scheme)) -> dict:
# #     try:
# #         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
# #         user_id = payload.get("sub")
# #         if not user_id:
# #             raise HTTPException(status_code=401, detail="Token inválido")
# #
# #         # Conexión a la base
# #         conn = get_connection()
# #         cursor = conn.cursor()
# #         cursor.execute(
# #             "SELECT id, nombre_completo, rol, activo FROM admin_usuario WHERE id = %s",
# #             (user_id,)
# #         )
# #         row = cursor.fetchone()
# #         cursor.close()
# #         conn.close()
# #
# #         if not row or not row[3]:  # activo = False
# #             raise HTTPException(status_code=401, detail="Usuario no encontrado o inactivo")
# #
# #         return {
# #             "id": row[0],
# #             "nombre": row[1],
# #             "rol": row[2]
# #         }
# #
# #     except JWTError:
# #         raise HTTPException(status_code=401, detail="Token inválido")
#
#
# # def obtener_usuario_actual(token: str = Depends(oauth2_scheme)) -> dict:
# #     try:
# #         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
# #         print("DEBUG payload:", payload)
# #
# #         user_id = payload.get("sub")
# #         nombre = payload.get("nombre")
# #         rol = payload.get("rol")
# #
# #         if user_id is None or nombre is None or rol is None:
# #             raise HTTPException(status_code=401, detail="Token inválido")
# #
# #         return {
# #             "id": int(user_id),
# #             "nombre": nombre,
# #             "rol": rol
# #         }
# #
# #     except JWTError:
# #         raise HTTPException(status_code=401, detail="Token inválido")
#
#
# def get_usuario_actual_id(token: str = Depends(oauth2_scheme)) -> int:
#     try:
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         user_id = int(payload.get("sub"))
#         return user_id
#     except:
#         raise HTTPException(status_code=401, detail="Token inválido")
#
#
# def get_usuario_actual_idV0() -> int:
#     return 1  # ID ficticio de prueba
#
# def obtener_usuario_actualV1() -> dict:
#     return {
#         "id": 1,
#         "nombre": "pablo gomez",
#         "rol": "admin"
#     }
#
# def obtener_usuario_actualV0(token: str = Depends(oauth2_scheme)) -> dict:
#
#         return {
#             "id": 1,
#             "nombre": "pablo gomez",
#             "rol": "admin"
#         }
#
