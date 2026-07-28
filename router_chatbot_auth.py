"""
Autenticación del frontend centralizado Chatbot de captación.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError, jwt
from pydantic import BaseModel, Field, field_validator, model_validator
from psycopg2.extras import RealDictCursor

from DataBase import get_connection_chatbot_context, hash_password, verify_password
from main_auth import ALGORITHM, SECRET_KEY, ACCESS_TOKEN_EXPIRE_MINUTES

logger = logging.getLogger("chatbot_auth")

CHATBOT_SCOPE = "chatbot_frontend"
MSG_CREDENCIALES = "Usuario o contraseña incorrectos."

router = APIRouter(prefix="/api/chatbot-auth", tags=["Chatbot Auth"])

oauth2_chatbot = OAuth2PasswordBearer(tokenUrl="/api/chatbot-auth/login")


# ---------- Schemas ----------

class ChatbotLoginIn(BaseModel):
    model_config = {"extra": "forbid"}
    usuario: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=1, max_length=200)

    @field_validator("usuario")
    @classmethod
    def norm_usuario(cls, v: str) -> str:
        return str(v or "").strip().lower()


class ChatbotCambiarClaveIn(BaseModel):
    model_config = {"extra": "forbid"}
    password_actual: str = Field(..., min_length=1, max_length=200)
    password_nueva: str = Field(..., min_length=8, max_length=200)
    confirmacion_password: str = Field(..., min_length=8, max_length=200)

    @model_validator(mode="after")
    def validar_claves(self):
        if self.password_nueva != self.confirmacion_password:
            raise ValueError("La nueva contraseña y la confirmación no coinciden")
        if self.password_nueva == self.password_actual:
            raise ValueError("La nueva contraseña debe ser distinta a la actual")
        if len(self.password_nueva.strip()) < 8:
            raise ValueError("La nueva contraseña debe tener al menos 8 caracteres")
        return self


class AgenciaAuthOut(BaseModel):
    id: int
    nombre: str
    codigo: str
    estado: Optional[str] = None


class ChatbotLoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    debe_cambiar_clave: bool
    agencia: AgenciaAuthOut


class ChatbotMeOut(BaseModel):
    usuario: str
    agencia: AgenciaAuthOut
    debe_cambiar_clave: bool


# ---------- Token / deps ----------

def crear_access_token_chatbot(
    *,
    usuario_login: str,
    agencia_id: int,
    debe_cambiar_clave: bool,
    codigo: str = "",
    nombre: str = "",
) -> str:
    payload = {
        "sub": usuario_login,
        "chatbot_agencia_id": int(agencia_id),
        "agencia_id": int(agencia_id),
        "product_type": "chatbot",
        "rol": "chatbot_agencia",
        "codigo": codigo or "",
        "nombre": nombre or "",
        "scope": CHATBOT_SCOPE,
        "debe_cambiar_clave": bool(debe_cambiar_clave),
        "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _buscar_agencia_login(usuario_norm: str) -> Optional[dict]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    id,
                    nombre,
                    codigo,
                    estado,
                    usuario_login,
                    password_hash,
                    debe_cambiar_clave,
                    login_activo
                FROM chatbot.agencias
                WHERE LOWER(TRIM(usuario_login)) = LOWER(TRIM(%s))
                LIMIT 1
                """,
                (usuario_norm,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def _obtener_agencia_activa_por_id(agencia_id: int) -> Optional[dict]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, nombre, codigo, estado, usuario_login,
                       debe_cambiar_clave, login_activo
                FROM chatbot.agencias
                WHERE id = %s
                  AND estado = 'activa'
                LIMIT 1
                """,
                (agencia_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def _marcar_ultimo_login(agencia_id: int) -> None:
    with get_connection_chatbot_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE chatbot.agencias
                SET ultimo_login = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (agencia_id,),
            )


def _actualizar_password(agencia_id: int, password_hash: str) -> None:
    with get_connection_chatbot_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE chatbot.agencias
                SET password_hash = %s,
                    debe_cambiar_clave = FALSE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (password_hash, agencia_id),
            )


def obtener_sesion_chatbot(token: str = Depends(oauth2_chatbot)) -> dict:
    """
    Valida JWT del frontend chatbot (scope=chatbot_frontend)
    y resuelve la agencia activa.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")

    if payload.get("scope") != CHATBOT_SCOPE:
        raise HTTPException(status_code=403, detail="Token no autorizado para el chatbot")

    agencia_id = payload.get("chatbot_agencia_id")
    if not agencia_id:
        raise HTTPException(status_code=401, detail="Token inválido")

    agencia = _obtener_agencia_activa_por_id(int(agencia_id))
    if not agencia:
        raise HTTPException(status_code=403, detail="Agencia no autorizada o inactiva")

    if not agencia.get("login_activo", True):
        raise HTTPException(status_code=403, detail="Acceso desactivado")

    return {
        "agencia_id": agencia["id"],
        "usuario": agencia.get("usuario_login") or payload.get("sub"),
        "debe_cambiar_clave": bool(agencia.get("debe_cambiar_clave")),
        "agencia": {
            "id": agencia["id"],
            "nombre": agencia["nombre"],
            "codigo": agencia["codigo"],
            "estado": agencia["estado"],
        },
        "token_debe_cambiar_clave": bool(payload.get("debe_cambiar_clave")),
    }


def obtener_agencia_chatbot_actual(sesion: dict = Depends(obtener_sesion_chatbot)) -> dict:
    """Para endpoints /api/chatbot-captacion/* — agencia solo desde JWT."""
    return {
        "id": sesion["agencia_id"],
        "nombre": sesion["agencia"]["nombre"],
        "codigo": sesion["agencia"]["codigo"],
        "estado": sesion["agencia"]["estado"],
    }


# ---------- Endpoints ----------

@router.post("/login", response_model=ChatbotLoginOut)
def login_chatbot(payload: ChatbotLoginIn):
    usuario = payload.usuario
    agencia = _buscar_agencia_login(usuario)

    # Respuesta genérica siempre (no filtrar por causa)
    ok = False
    if (
        agencia
        and agencia.get("estado") == "activa"
        and agencia.get("login_activo") is True
        and agencia.get("password_hash")
    ):
        try:
            ok = verify_password(payload.password, agencia["password_hash"])
        except Exception:
            ok = False

    if not ok:
        raise HTTPException(status_code=401, detail=MSG_CREDENCIALES)

    _marcar_ultimo_login(agencia["id"])
    debe = bool(agencia.get("debe_cambiar_clave"))
    token = crear_access_token_chatbot(
        usuario_login=agencia["usuario_login"],
        agencia_id=agencia["id"],
        debe_cambiar_clave=debe,
        codigo=agencia.get("codigo") or "",
        nombre=agencia.get("nombre") or "",
    )
    logger.info(
        "chatbot login ok agencia_id=%s usuario=%s",
        agencia["id"],
        (agencia.get("usuario_login") or "")[:3] + "***",
    )
    return ChatbotLoginOut(
        access_token=token,
        debe_cambiar_clave=debe,
        agencia=AgenciaAuthOut(
            id=agencia["id"],
            nombre=agencia["nombre"],
            codigo=agencia["codigo"],
        ),
    )


@router.post("/cambiar-clave", response_model=ChatbotLoginOut)
def cambiar_clave_chatbot(
    payload: ChatbotCambiarClaveIn,
    sesion: dict = Depends(obtener_sesion_chatbot),
):
    agencia_id = sesion["agencia_id"]
    row = _buscar_agencia_login(sesion["usuario"])
    if not row or row["id"] != agencia_id or not row.get("password_hash"):
        raise HTTPException(status_code=401, detail=MSG_CREDENCIALES)

    if not verify_password(payload.password_actual, row["password_hash"]):
        raise HTTPException(status_code=401, detail="La contraseña actual es incorrecta")

    nuevo_hash = hash_password(payload.password_nueva)
    _actualizar_password(agencia_id, nuevo_hash)

    token = crear_access_token_chatbot(
        usuario_login=row["usuario_login"],
        agencia_id=agencia_id,
        debe_cambiar_clave=False,
        codigo=row.get("codigo") or "",
        nombre=row.get("nombre") or "",
    )
    return ChatbotLoginOut(
        access_token=token,
        debe_cambiar_clave=False,
        agencia=AgenciaAuthOut(
            id=row["id"],
            nombre=row["nombre"],
            codigo=row["codigo"],
        ),
    )


@router.get("/me", response_model=ChatbotMeOut)
def me_chatbot(sesion: dict = Depends(obtener_sesion_chatbot)):
    return ChatbotMeOut(
        usuario=sesion["usuario"],
        agencia=AgenciaAuthOut(**sesion["agencia"]),
        debe_cambiar_clave=sesion["debe_cambiar_clave"],
    )


def asignar_usuario_inicial_agencia(
    *,
    agencia_id: int,
    usuario_login: str,
    password_temporal: str,
) -> dict[str, Any]:
    """
    Asignación administrativa segura (script/CLI). No loguea contraseña ni hash.
    """
    usuario = (usuario_login or "").strip().lower()
    if not usuario:
        raise ValueError("usuario_login es obligatorio")
    if len(password_temporal or "") < 8:
        raise ValueError("password_temporal debe tener al menos 8 caracteres")

    pwd_hash = hash_password(password_temporal)

    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, nombre, codigo
                FROM chatbot.agencias
                WHERE id = %s
                LIMIT 1
                """,
                (agencia_id,),
            )
            ag = cur.fetchone()
            if not ag:
                raise ValueError(f"No existe agencia id={agencia_id}")

            cur.execute(
                """
                SELECT id
                FROM chatbot.agencias
                WHERE LOWER(TRIM(usuario_login)) = %s
                  AND id <> %s
                LIMIT 1
                """,
                (usuario, agencia_id),
            )
            if cur.fetchone():
                raise ValueError("usuario_login ya está en uso por otra agencia")

            cur.execute(
                """
                UPDATE chatbot.agencias
                SET usuario_login = %s,
                    password_hash = %s,
                    debe_cambiar_clave = TRUE,
                    login_activo = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id, nombre, codigo, usuario_login, debe_cambiar_clave, login_activo
                """,
                (usuario, pwd_hash, agencia_id),
            )
            out = dict(cur.fetchone())
            # Nunca devolver password_hash
            out.pop("password_hash", None)
            return out
