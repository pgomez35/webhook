from fastapi import APIRouter, HTTPException
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

# Cargar variables de entorno (incluye DATABASE_URL)
load_dotenv()
INTERNAL_DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")

# SCHEMAS
# schemas_aspirantes.py
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, EmailStr

# ---------- Compat Pydantic v1/v2 ----------
def to_dict(model: BaseModel) -> dict:
    """
    Devuelve dict excluyendo campos no enviados (v1/v2 compatible).
    """
    if hasattr(model, "model_dump"):  # Pydantic v2
        return model.model_dump(exclude_unset=True)
    return model.dict(exclude_unset=True)  # Pydantic v1


# ---------- Base con tolerancia a extras ----------
class _Model(BaseModel):
    """
    Base para ignorar campos extra que vengan desde la BD (RealDictCursor):
    evita errores si la tabla tiene más columnas de las que modelamos aquí.
    """
    if hasattr(BaseModel, "model_config"):  # Pydantic v2
        model_config = {"extra": "ignore"}  # permite keys extra sin error
    else:  # Pydantic v1
        class Config:
            extra = "ignore"


# ---------- Schemas ----------
class AspiranteBase(_Model):
    nombre: str
    edad: Optional[int] = None
    correo: Optional[EmailStr] = None
    telefono: Optional[str] = None
    pais: Optional[str] = None
    ciudad: Optional[str] = None


class AspiranteCreate(AspiranteBase):
    # Permite que el front envíe un usuario explícito (si lo quieres usar)
    usuario_id: Optional[int] = None


class AspiranteUpdate(_Model):
    # Todos opcionales para permitir updates parciales (PATCH-like semantics)
    nombre: Optional[str] = None
    edad: Optional[int] = None
    correo: Optional[EmailStr] = None
    telefono: Optional[str] = None
    pais: Optional[str] = None
    ciudad: Optional[str] = None
    usuario_id: Optional[int] = None  # idem: puede venir del front


class AspiranteOut(AspiranteBase):
    id: int
    creado_en: datetime
    actualizado_en: Optional[datetime] = None  # si tu tabla lo tiene

    # Si tu tabla tiene más columnas (creado_por, actualizado_por, etc.) las ignorará por el extra="ignore"



def get_connection():
    return psycopg2.connect(
        INTERNAL_DATABASE_URL,
        cursor_factory=RealDictCursor   # 👈 esto hace que fetchone/fetchall devuelvan dicts
    )

def obtener_aspirante(aspirante_id: int):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM aspirantes WHERE id = %s;", (aspirante_id,))
        return cur.fetchone()  # ✅ devuelve dict directo
    finally:
        cur.close()
        conn.close()


def listar_aspirantes():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM aspirantes ORDER BY creado_en DESC;")
        return cur.fetchall()  # ✅ lista de dicts
    finally:
        cur.close()
        conn.close()


def crear_aspirante(datos: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        columnas = ", ".join(datos.keys())
        placeholders = ", ".join(["%s"] * len(datos))
        valores = tuple(datos.values())

        cur.execute(f"""
            INSERT INTO aspirantes ({columnas})
            VALUES ({placeholders})
            RETURNING *;
        """, valores)

        aspirante = cur.fetchone()  # ✅ dict directo
        conn.commit()
        return aspirante
    finally:
        cur.close()
        conn.close()


def actualizar_aspirante(aspirante_id: int, datos: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        if not datos:
            return None
        sets = ", ".join([f"{k} = %s" for k in datos.keys()])
        valores = list(datos.values()) + [aspirante_id]

        cur.execute(f"""
            UPDATE aspirantes
               SET {sets}, actualizado_en = NOW()
             WHERE id = %s
         RETURNING *;
        """, valores)

        aspirante = cur.fetchone()  # ✅ dict directo
        conn.commit()
        return aspirante
    finally:
        cur.close()
        conn.close()


def eliminar_aspirante(aspirante_id: int):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM aspirantes WHERE id = %s RETURNING id;", (aspirante_id,))
        eliminado = cur.fetchone()  # ✅ dict directo (ej. {"id": 5})
        conn.commit()
        return eliminado
    finally:
        cur.close()
        conn.close()

# ENDPOINTS


from fastapi import APIRouter, HTTPException, Body, Depends
from auth import obtener_usuario_actual

router = APIRouter(prefix="/api/aspirantes", tags=["Aspirantes"])

# ---------- Helper ----------
def resolver_usuario_id(body_usuario_id: Optional[int], usuario_actual: Optional[dict]) -> Optional[int]:
    if body_usuario_id is not None:
        return int(body_usuario_id)
    if usuario_actual and usuario_actual.get("id"):
        return int(usuario_actual["id"])
    return None


@router.get("/", response_model=list[AspiranteOut])
def api_listar_aspirantes():
    return listar_aspirantes()


@router.get("/{aspirante_id}", response_model=AspiranteOut)
def api_obtener_aspirante(aspirante_id: int):
    aspirante = obtener_aspirante(aspirante_id)
    if not aspirante:
        raise HTTPException(status_code=404, detail="Aspirante no encontrado")
    return aspirante


@router.post("/", response_model=AspiranteOut)
def api_crear_aspirante(
    payload: AspiranteCreate = Body(...),
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    data = payload.model_dump(exclude_unset=True)

    # Resuelve usuario (prioriza el que viene del front)
    usuario_id = resolver_usuario_id(getattr(payload, "usuario_id", None), usuario_actual)
    # Si tu tabla tiene columna `creado_por`, puedes usarla así:
    # if usuario_id is not None:
    #     data["creado_por"] = usuario_id

    creado = crear_aspirante(data)
    if not creado:
        raise HTTPException(status_code=500, detail="No se pudo crear el aspirante")
    return creado


@router.put("/{aspirante_id}", response_model=AspiranteOut)
def api_actualizar_aspirante(
    aspirante_id: int,
    payload: AspiranteUpdate = Body(...),
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No se enviaron datos para actualizar")

    usuario_id = resolver_usuario_id(getattr(payload, "usuario_id", None), usuario_actual)
    # Si tu tabla tiene columna `actualizado_por`, puedes usarla así:
    # if usuario_id is not None:
    #     data["actualizado_por"] = usuario_id

    actualizado = actualizar_aspirante(aspirante_id, data)
    if not actualizado:
        raise HTTPException(status_code=404, detail="Aspirante no encontrado")
    return actualizado


@router.delete("/{aspirante_id}")
def api_eliminar_aspirante(
    aspirante_id: int,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    # En DELETE no hay body; si quisieras permitir usuario_id del front, tendrías que pasarlo por query param.
    usuario_id = resolver_usuario_id(None, usuario_actual)
    # Si quieres auditar, aquí puedes loguear usuario_id.

    eliminado = eliminar_aspirante(aspirante_id)
    if not eliminado:
        raise HTTPException(status_code=404, detail="Aspirante no encontrado")
    return {"status": "ok", "eliminado": eliminado}
