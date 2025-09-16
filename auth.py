from datetime import datetime, timedelta

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from DataBase import get_connection

SECRET_KEY = "CLAVE_SECRETA"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 8
# oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/admin-usuario/login")


# Función para crear el JWT
def crear_token_jwt(usuario: dict) -> str:
    data = {
        "sub": str(usuario["id"]),   # 👈 siempre será el ID del usuario
        "nombre": usuario["nombre_completo"], # 👈 consistente con obtener_usuario_actual
        "rol": usuario["rol"],
        "exp": datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    }
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)


def obtener_usuario_actual(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token inválido")

        # Conexión a la base
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, nombre_completo, rol, activo FROM admin_usuario WHERE id = %s",
            (user_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row or not row[3]:  # activo = False
            raise HTTPException(status_code=401, detail="Usuario no encontrado o inactivo")

        return {
            "id": row[0],
            "nombre": row[1],
            "rol": row[2]
        }

    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")


# def obtener_usuario_actual(token: str = Depends(oauth2_scheme)) -> dict:
#     try:
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         print("DEBUG payload:", payload)
#
#         user_id = payload.get("sub")
#         nombre = payload.get("nombre")
#         rol = payload.get("rol")
#
#         if user_id is None or nombre is None or rol is None:
#             raise HTTPException(status_code=401, detail="Token inválido")
#
#         return {
#             "id": int(user_id),
#             "nombre": nombre,
#             "rol": rol
#         }
#
#     except JWTError:
#         raise HTTPException(status_code=401, detail="Token inválido")


def get_usuario_actual_id(token: str = Depends(oauth2_scheme)) -> int:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
        return user_id
    except:
        raise HTTPException(status_code=401, detail="Token inválido")


def get_usuario_actual_idV0() -> int:
    return 1  # ID ficticio de prueba

def obtener_usuario_actualV1() -> dict:
    return {
        "id": 1,
        "nombre": "pablo gomez",
        "rol": "admin"
    }

def obtener_usuario_actualV0(token: str = Depends(oauth2_scheme)) -> dict:

        return {
            "id": 1,
            "nombre": "pablo gomez",
            "rol": "admin"
        }

