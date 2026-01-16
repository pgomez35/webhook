import traceback
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import pytz
import secrets
import string


from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from psycopg2.extras import RealDictCursor

from DataBase import get_connection_context
from schemas import *
from main_auth import obtener_usuario_actual

# Configurar logger
from tenant import current_tenant

logger = logging.getLogger(__name__)

router = APIRouter()   # ← ESTE ES EL ROUTER QUE VAS A IMPORTAR EN main.py

class DiagnosticoOut(BaseModel):
    id: int
    diagnostico: Optional[str] = None
    mejoras_sugeridas: Optional[str] = None
    updated_at: Optional[datetime] = None  # si lo tienes en DB

@router.get("/api/creadores/{creador_id}/diagnostico", response_model=DiagnosticoOut)
def obtener_diagnostico_creador(creador_id: int):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.id,
                       b.diagnostico,
                       b.mejoras_sugeridas,
                       b.fecha_actualizacion
                FROM creadores a
                INNER JOIN perfil_creador b ON a.id = b.creador_id
                WHERE a.id = %s
                LIMIT 1
                """,
                (creador_id,)
            )
            row = cur.fetchone()

            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="No se encontró diagnóstico para este creador."
                )

            return {
                "id": row[0],
                "diagnostico": row[1],
                "mejoras_sugeridas": row[2],
                "updated_at": row[3],
            }