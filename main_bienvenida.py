from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict
from datetime import datetime

from DataBase import get_connection_context

router = APIRouter()

# --------------------------------------------------
# MODELOS
# --------------------------------------------------
class InfoIncorporacionOut(BaseModel):
    proceso_incorporacion: Optional[str] = None
    preguntas_frecuentes: Optional[str] = None
    actualizado_en: Optional[datetime] = None


class InfoIncorporacionIn(BaseModel):
    proceso_incorporacion: Optional[str] = None
    preguntas_frecuentes: Optional[str] = None


# --------------------------------------------------
# GET – leer info
# --------------------------------------------------
@router.get("/api/info-incorporacion", response_model=InfoIncorporacionOut)
def get_info_incorporacion():
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT clave, valor, actualizado_en
                FROM configuracion_agencia
                WHERE clave IN ('proceso_incorporacion', 'preguntas_frecuentes')
            """)
            rows = cur.fetchall()

    data = {k: (v, t) for (k, v, t) in rows}

    if "proceso_incorporacion" not in data:
        raise HTTPException(404, "Información de incorporación no configurada")

    return {
        "proceso_incorporacion": data.get("proceso_incorporacion", (None, None))[0],
        "preguntas_frecuentes": data.get("preguntas_frecuentes", (None, None))[0],
        "actualizado_en": max(
            (t for (_, t) in data.values() if t),
            default=None
        ),
    }


# --------------------------------------------------
# PUT – actualizar info
# --------------------------------------------------
@router.put("/api/info-incorporacion", response_model=InfoIncorporacionOut)
def update_info_incorporacion(payload: InfoIncorporacionIn):
    if not payload.proceso_incorporacion and not payload.preguntas_frecuentes:
        raise HTTPException(400, "No hay datos para actualizar")

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            if payload.proceso_incorporacion is not None:
                cur.execute("""
                    INSERT INTO configuracion_agencia (clave, valor, descripcion)
                    VALUES ('proceso_incorporacion', %s, 'Texto proceso incorporación')
                    ON CONFLICT (clave)
                    DO UPDATE SET
                        valor = EXCLUDED.valor,
                        actualizado_en = now()
                """, (payload.proceso_incorporacion,))

            if payload.preguntas_frecuentes is not None:
                cur.execute("""
                    INSERT INTO configuracion_agencia (clave, valor, descripcion)
                    VALUES ('preguntas_frecuentes', %s, 'Texto preguntas frecuentes')
                    ON CONFLICT (clave)
                    DO UPDATE SET
                        valor = EXCLUDED.valor,
                        actualizado_en = now()
                """, (payload.preguntas_frecuentes,))

        conn.commit()

    return get_info_incorporacion()

