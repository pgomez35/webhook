from datetime import datetime, timedelta

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError

SECRET_KEY = "CLAVE_SECRETA"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 8
# oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/admin-usuario/login")


# Función para crear el JWT
def crear_token_jwt(usuario: dict) -> str:
    data = {
        "sub": str(usuario["id"]),
        "nombre": usuario["nombre_completo"],
        "rol": usuario["rol"],
        "exp": datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    }
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

def obtener_usuario_actual(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        nombre: str = payload.get("nombre")
        rol: str = payload.get("rol")


        if user_id is None:
            raise HTTPException(status_code=401, detail="Token inválido")

        return {
            "id": user_id,
            "nombre": nombre,
            "rol": rol
        }

    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")


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

