import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from DataBase import get_connection_context
from tenant import current_tenant
from main_invitacion import obtener_invitacion_portal_por_aspirante, InvitacionPortalOut
from utils_aspirantes import construir_url_actualizar_perfil, actualizar_uso_token, \
    resolver_token_portal_general_o_error
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, quote


router = APIRouter()

# =========================================================
# CONFIG
# =========================================================

TOKEN_LENGTH = 10
TOKEN_DURACION_MINUTOS = 10080  # 7 días

PORTAL_ROOT_DOMAIN = os.getenv("PORTAL_ROOT_DOMAIN", "talentum-manager.com").strip()
PORTAL_BASE_URL = os.getenv("PORTAL_BASE_URL", "").strip()


from fastapi.responses import JSONResponse


@router.get("/api/portal/validar")
def validar_portal_general(token: str = Query(..., min_length=10)):
    print("🔥🔥🔥 ENTRÓ AL ENDPOINT NUEVO validar_portal_general 🔥🔥🔥")
    try:
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

    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={
                "valid": False,
                "error": e.detail,
                "code": getattr(e, "code", None)
            }
        )

    except Exception as e:
        print(f"❌ Error validando portal general: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "valid": False,
                "error": "Error interno validando el enlace del portal.",
                "detail": str(e)
            }
        )


