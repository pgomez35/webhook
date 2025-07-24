from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError

SECRET_KEY = "CLAVE_SECRETA"
ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def get_usuario_actual_id_(token: str = Depends(oauth2_scheme)) -> int:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
        return user_id
    except:
        raise HTTPException(status_code=401, detail="Token inválido")

def get_usuario_actual_id() -> int:
    return 1  # ID ficticio de prueba

def obtener_usuario_actual_(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        email: str = payload.get("email")  # ← importante
        nombre: str = payload.get("nombre")
        rol: str = payload.get("rol")


        if user_id is None or email is None:
            raise HTTPException(status_code=401, detail="Token inválido")

        return {
            "id": user_id,
            "email": email,
            "nombre": nombre,
            "rol": rol
        }

    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")

def obtener_usuario_actual(token: str = Depends(oauth2_scheme)) -> dict:

        return {
            "id": 1,
            "email": "pgomez@gmail.com",
            "nombre": "pablo gomez",
            "rol": "admin"
        }

