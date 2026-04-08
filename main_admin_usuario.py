from fastapi import FastAPI,APIRouter, HTTPException, Path, Body, Request, UploadFile, Form,File,Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import pandas as pd
import io

# Respuestas personalizadas (usa solo si las necesitas)
from fastapi.responses import JSONResponse, PlainTextResponse

from dotenv import load_dotenv  # Solo si usas variables de entorno
import os
import json
import re
import logging
import subprocess
import traceback

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel

from schemas import *
from DataBase import *
from rapidfuzz import process, fuzz
import unicodedata
import traceback

import psycopg2

# Configuración


from main_auth import *

router = APIRouter()

@router.get("/api/admin-usuario", response_model=List[AdminUsuarioResponse])
async def obtener_usuarios(request: Request):

    usuarios = obtener_todos_usuarioss()
    return usuarios

@router.post("/api/admin-usuario", response_model=AdminUsuarioResponse)
async def crear_usuario(usuario: AdminUsuarioCreate, request: Request):
    """Crea un nuevo usuario administrador dentro del tenant actual."""

    usuario_creado = crear_usuarios(usuario)
    return usuario_creado

@router.get("/api/admin-usuario/{administrador_id}", response_model=AdminUsuarioResponse)
async def obtener_usuario(administrador_id: int, request: Request):
    """Obtiene un usuario administrador por ID dentro del tenant actual."""

    usuario = obtener_usuarios_por_id(administrador_id)

    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return usuario


@router.delete("/api/admin-usuario/{administrador_id}")
async def eliminar_usuario(administrador_id: int, request: Request):
    """Elimina un usuario administrador dentro del tenant actual."""

    resultado = eliminar_usuarios(administrador_id)

    if resultado.get("status") == "error":
        raise HTTPException(status_code=404, detail=resultado.get("mensaje"))

    return {"mensaje": resultado.get("mensaje", "Usuario eliminado exitosamente")}

@router.patch("/api/admin-usuario/{administrador_id}/activo")
async def cambiar_estado_usuario(administrador_id: int, request: Request, activo: bool = Body(...)):
    """Cambia el estado activo/inactivo de un usuario administrador dentro del tenant actual."""

    resultado = cambiar_estado_usuarios(administrador_id, activo)

    if resultado.get("status") == "error":
        raise HTTPException(status_code=404, detail=resultado.get("mensaje"))

    return {"mensaje": resultado.get("mensaje")}


@router.get("/api/admin-usuario/username/{username}", response_model=AdminUsuarioResponse)
async def obtener_usuario_por_username(username: str, request: Request):
    """Obtiene un usuario administrador por username (útil para autenticación dentro del tenant actual)"""

    usuario = obtener_usuarios_por_username(username)

    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return usuario


# === LOGIN ===
@router.post("/login", response_model=TokenResponse)
async def login_usuario(request: Request, credentials: dict = Body(...)):
    """
    Inicia sesión para un usuario administrador dentro de su agencia (tenant actual).
    """
    username = credentials.get("username", "").strip().lower()
    password = credentials.get("password", "")
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username y password son requeridos")


    # Validar usuario
    resultado = autenticar_usuarios(username, password)
    if resultado["status"] != "ok":
        raise HTTPException(status_code=401, detail=resultado["mensaje"])

    usuario = resultado["usuario"]

    # Generar tokens
    access_token = crear_access_token(usuario)
    refresh_token = crear_refresh_token(usuario)

    return TokenResponse(
        usuario=UsuarioOut(id=usuario["id"], nombre=usuario["nombre"], rol=usuario["rol"]),
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        mensaje="Login exitoso"
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: Request, data: dict = Body(...)):
    token = data.get("refresh_token")
    if not token:
        raise HTTPException(status_code=400, detail="refresh_token requerido")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("tipo") != "refresh":
            raise HTTPException(status_code=401, detail="Token inválido")

        user_id = payload.get("sub")

        with get_connection_context() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT a.id, a.nombre_completo AS nombre, ur.nombre AS rol, a.activo
                FROM administradores a
                LEFT JOIN administradores_roles ur ON ur.id = a.administradores_roles_id
                WHERE a.id = %s
                """,
                (user_id,)  # 👈 importante: debe ser tupla
            )
            row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        if not row[3]:
            raise HTTPException(status_code=401, detail="Usuario inactivo")

        usuario = {
            "id": row[0],
            "nombre": row[1],
            "rol": row[2]
        }

        new_access_token = crear_access_token(usuario)

        return TokenResponse(
            access_token=new_access_token,
            refresh_token=token,
            token_type="bearer",
            mensaje="Access token renovado",
            usuario=UsuarioOut(**usuario)
        )

    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="refresh_token expirado")

    except JWTError:
        raise HTTPException(status_code=401, detail="refresh_token inválido")

    except Exception as e:
        print("❌ Error al renovar token:", e)
        raise HTTPException(status_code=500, detail="Error interno del servidor")


from tenant import current_tenant, current_business_name

@router.get("/me", response_model=UsuarioOut, tags=["Auth"])
async def get_me(usuario_actual: dict = Depends(obtener_usuario_actual)):
    """Devuelve la información del usuario autenticado y su tenant actual."""
    if not usuario_actual:
        raise HTTPException(status_code=401, detail="Usuario no autenticado")

    return UsuarioOut(
        id=usuario_actual["id"],
        nombre=usuario_actual["nombre"],
        rol=usuario_actual["rol"],
        agencia=current_tenant.get(),  # 👈 schema / tenant
        agencia_nombre=current_business_name.get(None)  # 👈 nombre legible (opcional)
    )


@router.put("/api/admin-usuario/cambiar-password")
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


@router.put("/api/admin-usuario/{administrador_id:int}", response_model=AdminUsuarioResponse)
async def actualizar_usuario(administrador_id: int, usuario: AdminUsuarioUpdate):
    try:
        usuario_actualizado = actualizar_usuarios(administrador_id, usuario.dict())
        if not usuario_actualizado:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        return usuario_actualizado
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error interno del servidor")
