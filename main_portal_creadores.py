import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from DataBase import get_connection_context
from tenant import current_tenant
from main_invitacion import obtener_invitacion_portal_por_aspirante, InvitacionPortalOut
from utils_aspirantes import construir_url_actualizar_perfil
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, quote


router = APIRouter()

# =========================================================
# CONFIG
# =========================================================

TOKEN_LENGTH = 10
TOKEN_DURACION_MINUTOS = 10080  # 7 días

PORTAL_ROOT_DOMAIN = os.getenv("PORTAL_ROOT_DOMAIN", "talentum-manager.com").strip()
PORTAL_BASE_URL = os.getenv("PORTAL_BASE_URL", "").strip()


@router.get("/api/portal/validar")
def validar_portal_general(token: str = Query(..., min_length=10)):
    info = resolver_token_portal_general_o_error(token)
    actualizar_uso_token(token)

    return {
        "valid": True,
        "tipo_portal": info["tipo_portal"],

        "aspirante_id": info.get("aspirante_id"),
        "creador_id": info.get("creador_id"),

        "nombre": info["nombre"],

        "estado_id": info.get("estado_id"),
        "estado_nombre": info.get("estado_nombre"),

        "expiracion": info["expiracion"],

        "features": {
            "portal_aspirante": info["tipo_portal"] == "aspirante",
            "portal_creador": info["tipo_portal"] == "creador",
            "encuesta_creador": info.get("creador_id") is not None,
        }
    }

def resolver_token_portal_general_o_error(token: str) -> dict:
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    pat.token,
                    COALESCE(pat.tipo_portal, 'aspirante') AS tipo_portal,
                    pat.aspirante_id,
                    pat.creador_id,
                    pat.expiracion,

                    a.nombre_real,
                    a.nickname,
                    a.usuario,
                    a.estado_id,
                    a.telefono,
                    a.whatsapp,
                    a.email,
                    COALESCE(a.encuesta_terminada, false) AS encuesta_terminada,

                    ae.nombre AS estado_nombre,

                    c.nombre AS creador_nombre,
                    c.nickname AS creador_nickname

                FROM portal_access_tokens pat
                LEFT JOIN aspirantes a
                    ON a.id = pat.aspirante_id
                LEFT JOIN aspirantes_estados ae
                    ON ae.id = a.estado_id
                LEFT JOIN creadores c
                    ON c.id = pat.creador_id
                WHERE pat.token = %s
                  AND pat.estado = 'activo'
                  AND pat.expiracion > NOW()
                LIMIT 1
                """,
                (token,),
            )

            row = cur.fetchone()

            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="El enlace del portal no es válido o expiró.",
                )

            tipo_portal = row[1] or "aspirante"

            aspirante_nombre = row[5] or row[6] or row[7]
            creador_nombre = row[14] or row[15]

            nombre = (
                creador_nombre
                if tipo_portal == "creador" and creador_nombre
                else aspirante_nombre
                or f"Usuario {row[2] or row[3]}"
            )

            return {
                "token": row[0],
                "tipo_portal": tipo_portal,

                "aspirante_id": row[2],
                "creador_id": row[3],
                "expiracion": row[4],

                "nombre": nombre,

                "estado_id": row[8],
                "telefono": row[9],
                "whatsapp": row[10],
                "email": row[11],
                "encuesta_terminada": row[12],
                "estado_nombre": row[13] or "Proceso",
                "usuario": row[7],
            }

