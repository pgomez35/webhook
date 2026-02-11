from pydantic import BaseModel
from typing import Optional
from DataBase import get_connection
from fastapi import APIRouter, Depends, HTTPException
from main_auth import obtener_usuario_actual


# -----------------------------
# Pydantic models
# -----------------------------
class PuntajeBase(BaseModel):
    aspirante_id: int
    puntaje_total: Optional[float] = None
    puntaje_estadistica: Optional[float] = None
    puntaje_cualitativo: Optional[float] = None
    puntaje_habitos: Optional[float] = None
    puntaje_general: Optional[float] = None
    puntaje_total_categoria: Optional[str] = None
    puntaje_estadistica_categoria: Optional[str] = None
    puntaje_cualitativo_categoria: Optional[str] = None
    puntaje_habitos_categoria: Optional[str] = None
    puntaje_general_categoria: Optional[str] = None


class PuntajeCreate(PuntajeBase):
    pass


class PuntajeUpdate(BaseModel):
    puntaje_total: Optional[float] = None
    puntaje_estadistica: Optional[float] = None
    puntaje_cualitativo: Optional[float] = None
    puntaje_habitos: Optional[float] = None
    puntaje_general: Optional[float] = None
    puntaje_total_categoria: Optional[str] = None
    puntaje_estadistica_categoria: Optional[str] = None
    puntaje_cualitativo_categoria: Optional[str] = None
    puntaje_habitos_categoria: Optional[str] = None
    puntaje_general_categoria: Optional[str] = None


class PuntajeDB(PuntajeBase):
    id: int
    modificado_por: Optional[int]

    class Config:
        orm_mode = True


# -----------------------------
# DB functions
# -----------------------------
def crear_puntaje(datos: dict, usuario_id: int):
    conn = get_connection()
    cur = conn.cursor()
    try:
        columnas = ", ".join(list(datos.keys()) + ["modificado_por"])
        placeholders = ", ".join(["%s"] * (len(datos) + 1))
        valores = tuple(datos.values()) + (usuario_id,)

        cur.execute(f"""
            INSERT INTO aspirantes_puntajes ({columnas})
            VALUES ({placeholders})
            RETURNING *;
        """, valores)

        conn.commit()
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def obtener_puntaje_por_aspirante(aspirante_id: int):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT * FROM aspirantes_puntajes
            WHERE aspirante_id = %s
            ORDER BY id DESC
            LIMIT 1;
        """, (aspirante_id,))
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def actualizar_puntaje_por_aspirante(aspirante_id: int, datos: dict, usuario_id: int):
    conn = get_connection()
    cur = conn.cursor()
    try:
        sets = ", ".join([f"{col} = %s" for col in datos.keys()])
        valores = tuple(datos.values()) + (usuario_id, aspirante_id)

        cur.execute(f"""
            UPDATE aspirantes_puntajes
            SET {sets}, modificado_por = %s
            WHERE aspirante_id = %s
            RETURNING *;
        """, valores)

        conn.commit()
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def eliminar_puntaje_por_aspirante(aspirante_id: int):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM aspirantes_puntajes WHERE aspirante_id = %s RETURNING id;", (aspirante_id,))
        conn.commit()
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


# -----------------------------
# FastAPI Router
# -----------------------------
router = APIRouter(prefix="/api/puntajes", tags=["Aspirantes Puntajes"])


@router.post("/", response_model=PuntajeDB)
def crear(datos: PuntajeCreate, usuario: dict = Depends(obtener_usuario_actual)):
    result = crear_puntaje(datos.dict(), usuario["id"])
    if not result:
        raise HTTPException(status_code=400, detail="No se pudo crear el puntaje")
    return result


@router.get("/aspirante/{aspirante_id}", response_model=PuntajeDB)
def leer_por_aspirante(aspirante_id: int):
    result = obtener_puntaje_por_aspirante(aspirante_id)
    if not result:
        raise HTTPException(status_code=404, detail="Puntaje no encontrado")
    return result


@router.put("/aspirante/{aspirante_id}", response_model=PuntajeDB)
def actualizar_por_aspirante(aspirante_id: int, datos: PuntajeUpdate, usuario: dict = Depends(obtener_usuario_actual)):
    result = actualizar_puntaje_por_aspirante(aspirante_id, datos.dict(exclude_unset=True), usuario["id"])
    if not result:
        raise HTTPException(status_code=404, detail="Puntaje no encontrado o no actualizado")
    return result


@router.delete("/aspirante/{aspirante_id}")
def eliminar_por_aspirante(aspirante_id: int):
    result = eliminar_puntaje_por_aspirante(aspirante_id)
    if not result:
        raise HTTPException(status_code=404, detail="Puntajes no encontrados")
    return {"message": "Puntajes eliminados", "ids": [r[0] for r in result]}
