"""
Tokens y URLs del portal (aspirante/creador).

Módulo independiente: no importa utils_aspirantes ni main_webhook ni main_portal_usuarios,
para evitar referencias cruzadas. main_portal_usuarios y utils_aspirantes reutilizan estas funciones.
"""

import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from DataBase import get_connection_context
from tenant import current_tenant

# =========================================================
# CONFIG
# =========================================================

TOKEN_LENGTH = 10
TOKEN_DURACION_DIAS_ASPIRANTE = 10
TOKEN_DURACION_DIAS_CREADOR = 365

PORTAL_ROOT_DOMAIN = os.getenv("PORTAL_ROOT_DOMAIN", "talentum-manager.com").strip()
PORTAL_BASE_URL = os.getenv("PORTAL_BASE_URL", "").strip()

TIPOS_PORTAL_VALIDOS = ("aspirante", "creador")

# Alineado con aspirantes_estados / main_portal_usuarios
ESTADO_ASPIRANTE_RECHAZADO_ID = 7


# =========================================================
# HELPERS TENANT / URL
# =========================================================


def obtener_tenant_actual() -> str:
    try:
        tenant = current_tenant.get()
    except Exception:
        tenant = "public"

    return (tenant or "public").strip().lower()


def construir_base_portal_url() -> str:
    if PORTAL_BASE_URL:
        return PORTAL_BASE_URL.rstrip("/")

    tenant = obtener_tenant_actual()

    if tenant == "public":
        return f"https://{PORTAL_ROOT_DOMAIN}/portal"

    return f"https://{tenant}.{PORTAL_ROOT_DOMAIN}/portal"


def construir_base_agendamiento_url() -> str:
    if PORTAL_BASE_URL:
        base = PORTAL_BASE_URL.rstrip("/")
        if base.endswith("/portal"):
            return f"{base[:-7]}/agendar"
        return f"{base}/agendar"

    tenant = obtener_tenant_actual()

    if tenant == "public":
        return f"https://{PORTAL_ROOT_DOMAIN}/agendar"

    return f"https://{tenant}.{PORTAL_ROOT_DOMAIN}/agendar"


def construir_url_portal(token: str) -> str:
    return f"{construir_base_portal_url()}?access={token}"


def construir_url_agendamiento(token: str) -> str:
    return f"{construir_base_agendamiento_url()}?t={token}"


# =========================================================
# HELPERS TOKEN PORTAL UNIVERSAL
# =========================================================


def expiracion_desde_dias(duracion_dias: int) -> datetime:
    return datetime.now() + timedelta(days=duracion_dias)


def _token_row_to_dict(row, *, reutilizado: bool) -> dict:
    return {
        "id": row[0],
        "token": row[1],
        "expiracion": row[2],
        "creado_en": row[3],
        "duracion_dias": row[4],
        "creado_por": row[5],
        "origen": row[6],
        "aspirante_id": row[7],
        "creador_id": row[8],
        "tipo_portal": row[9],
        "reutilizado": reutilizado,
    }


_TOKEN_SELECT_COLUMNS = """
    id,
    token,
    expiracion,
    creado_en,
    duracion_dias,
    creado_por,
    origen,
    aspirante_id,
    creador_id,
    tipo_portal
"""


def validar_identidad_portal(
    tipo_portal: str,
    aspirante_id: Optional[int] = None,
    creador_id: Optional[int] = None,
) -> str:
    tipo_portal = (tipo_portal or "").strip().lower()

    if tipo_portal not in TIPOS_PORTAL_VALIDOS:
        raise ValueError(f"tipo_portal inválido: {tipo_portal}")

    if tipo_portal == "aspirante" and not aspirante_id:
        raise ValueError("Para tipo_portal='aspirante' se requiere aspirante_id.")

    if tipo_portal == "creador" and not creador_id:
        raise ValueError("Para tipo_portal='creador' se requiere creador_id.")

    return tipo_portal


def token_existe_activo(cur, token: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM portal_access_tokens
        WHERE token = %s
          AND estado = 'activo'
          AND expiracion > NOW()
        LIMIT 1
        """,
        (token,),
    )
    return cur.fetchone() is not None


def generar_token_seguro(cur, longitud_token: int = TOKEN_LENGTH) -> str:
    while True:
        token = secrets.token_urlsafe(8)[:longitud_token]
        if not token_existe_activo(cur, token):
            return token


def duracion_portal_por_tipo(
    tipo_portal: str,
    duracion_dias: Optional[int] = None,
) -> int:
    if duracion_dias and duracion_dias > 0:
        return duracion_dias

    if tipo_portal == "creador":
        return TOKEN_DURACION_DIAS_CREADOR

    return TOKEN_DURACION_DIAS_ASPIRANTE


def obtener_token_portal_por_aspirante_id(
    cur,
    aspirante_id: int,
) -> Optional[dict]:
    """Último token asociado al aspirante (activo preferido)."""
    cur.execute(
        f"""
        SELECT {_TOKEN_SELECT_COLUMNS}
        FROM portal_access_tokens
        WHERE aspirante_id = %s
        ORDER BY
            CASE WHEN estado = 'activo' THEN 0 ELSE 1 END,
            CASE WHEN expiracion > NOW() THEN 0 ELSE 1 END,
            creado_en DESC,
            id DESC
        LIMIT 1
        """,
        (aspirante_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return _token_row_to_dict(row, reutilizado=True)


def migrar_token_portal_aspirante_a_creador(
    cur,
    aspirante_id: int,
    creador_id: int,
    origen: str = "incorporacion",
) -> Optional[dict]:
    """
    Al incorporar: reutiliza el token del aspirante (no crea uno nuevo).
    Actualiza tipo_portal, creador_id, duracion_dias y expiración (365 días).
    """
    token_existente = obtener_token_portal_por_aspirante_id(cur, aspirante_id)
    if not token_existente:
        print(
            f"⚠️ [PORTAL] Sin token previo para aspirante_id={aspirante_id}; "
            "no se migró a creador."
        )
        return None

    duracion_dias = TOKEN_DURACION_DIAS_CREADOR
    expiracion = expiracion_desde_dias(duracion_dias)

    cur.execute(
        f"""
        UPDATE portal_access_tokens
        SET
            tipo_portal = 'creador',
            creador_id = %s,
            duracion_dias = %s,
            expiracion = %s,
            estado = 'activo',
            origen = COALESCE(%s, origen),
            aspirante_id = COALESCE(aspirante_id, %s)
        WHERE id = %s
        RETURNING {_TOKEN_SELECT_COLUMNS}
        """,
        (
            creador_id,
            duracion_dias,
            expiracion,
            origen,
            aspirante_id,
            token_existente["id"],
        ),
    )
    row = cur.fetchone()
    if not row:
        return None

    print(
        f"✅ [PORTAL] Token migrado aspirante→creador | "
        f"aspirante_id={aspirante_id} | creador_id={creador_id} | token={row[1]}"
    )
    return _token_row_to_dict(row, reutilizado=True)


def obtener_token_portal_activo(
    cur,
    tipo_portal: str,
    aspirante_id: Optional[int] = None,
    creador_id: Optional[int] = None,
) -> Optional[dict]:
    tipo_portal = validar_identidad_portal(
        tipo_portal=tipo_portal,
        aspirante_id=aspirante_id,
        creador_id=creador_id,
    )

    cur.execute(
        f"""
        SELECT {_TOKEN_SELECT_COLUMNS}
        FROM portal_access_tokens
        WHERE estado = 'activo'
          AND expiracion > NOW()
          AND tipo_portal = %s
          AND (
                (%s IS NOT NULL AND aspirante_id = %s)
             OR (%s IS NOT NULL AND creador_id = %s)
          )
        ORDER BY expiracion DESC, id DESC
        LIMIT 1
        """,
        (
            tipo_portal,
            aspirante_id,
            aspirante_id,
            creador_id,
            creador_id,
        ),
    )

    row = cur.fetchone()
    if not row:
        return None

    return _token_row_to_dict(row, reutilizado=True)


def obtener_token_portal_existente(
    cur,
    tipo_portal: str,
    aspirante_id: Optional[int] = None,
    creador_id: Optional[int] = None,
) -> Optional[dict]:
    tipo_portal = validar_identidad_portal(
        tipo_portal=tipo_portal,
        aspirante_id=aspirante_id,
        creador_id=creador_id,
    )

    cur.execute(
        f"""
        SELECT {_TOKEN_SELECT_COLUMNS}
        FROM portal_access_tokens
        WHERE tipo_portal = %s
          AND (
                (%s IS NOT NULL AND aspirante_id = %s)
             OR (%s IS NOT NULL AND creador_id = %s)
          )
        ORDER BY
            CASE WHEN estado = 'activo' THEN 0 ELSE 1 END,
            creado_en DESC,
            id DESC
        LIMIT 1
        """,
        (
            tipo_portal,
            aspirante_id,
            aspirante_id,
            creador_id,
            creador_id,
        ),
    )

    row = cur.fetchone()
    if not row:
        return None

    return _token_row_to_dict(row, reutilizado=True)


def renovar_token_portal(
    cur,
    token_id: int,
    duracion_dias: int,
    creado_por: Optional[int] = None,
    origen: str = "whatsapp",
) -> dict:
    expiracion = expiracion_desde_dias(duracion_dias)

    cur.execute(
        f"""
        UPDATE portal_access_tokens
        SET
            expiracion = %s,
            estado = 'activo',
            duracion_dias = %s,
            creado_por = COALESCE(%s, creado_por),
            origen = COALESCE(%s, origen)
        WHERE id = %s
        RETURNING {_TOKEN_SELECT_COLUMNS}
        """,
        (
            expiracion,
            duracion_dias,
            creado_por,
            origen,
            token_id,
        ),
    )

    row = cur.fetchone()
    return _token_row_to_dict(row, reutilizado=True)


def revocar_tokens_activos(
    cur,
    tipo_portal: str,
    aspirante_id: Optional[int] = None,
    creador_id: Optional[int] = None,
) -> int:
    tipo_portal = validar_identidad_portal(
        tipo_portal=tipo_portal,
        aspirante_id=aspirante_id,
        creador_id=creador_id,
    )

    cur.execute(
        """
        UPDATE portal_access_tokens
        SET estado = 'revocado'
        WHERE estado = 'activo'
          AND expiracion > NOW()
          AND tipo_portal = %s
          AND (
                (%s IS NOT NULL AND aspirante_id = %s)
             OR (%s IS NOT NULL AND creador_id = %s)
          )
        """,
        (
            tipo_portal,
            aspirante_id,
            aspirante_id,
            creador_id,
            creador_id,
        ),
    )

    return cur.rowcount or 0


def revocar_tokens_portal_por_aspirante_id(cur, aspirante_id: int) -> int:
    """
    Revoca todos los tokens activos del aspirante (aspirante o creador migrado).
    Se usa al pasar a estado Rechazado (7).
    """
    if not aspirante_id:
        return 0

    cur.execute(
        """
        UPDATE portal_access_tokens
        SET estado = 'revocado'
        WHERE estado = 'activo'
          AND aspirante_id = %s
        """,
        (aspirante_id,),
    )
    n = cur.rowcount or 0
    if n:
        print(
            f"🔒 [PORTAL] Revocados {n} token(s) activo(s) "
            f"para aspirante_id={aspirante_id}"
        )
    return n


def crear_token_portal(
    cur,
    tipo_portal: str,
    aspirante_id: Optional[int] = None,
    creador_id: Optional[int] = None,
    duracion_dias: Optional[int] = None,
    creado_por: Optional[int] = None,
    origen: str = "whatsapp",
) -> dict:
    tipo_portal = validar_identidad_portal(
        tipo_portal=tipo_portal,
        aspirante_id=aspirante_id,
        creador_id=creador_id,
    )

    duracion_final = duracion_portal_por_tipo(tipo_portal, duracion_dias)
    token = generar_token_seguro(cur, TOKEN_LENGTH)
    expiracion = expiracion_desde_dias(duracion_final)

    cur.execute(
        f"""
        INSERT INTO portal_access_tokens (
            token,
            aspirante_id,
            creador_id,
            tipo_portal,
            expiracion,
            estado,
            creado_en,
            duracion_dias,
            creado_por,
            origen
        )
        VALUES (
            %s, %s, %s, %s,
            %s, 'activo', now(),
            %s, %s, %s
        )
        RETURNING {_TOKEN_SELECT_COLUMNS}
        """,
        (
            token,
            aspirante_id,
            creador_id,
            tipo_portal,
            expiracion,
            duracion_final,
            creado_por,
            origen,
        ),
    )

    row = cur.fetchone()
    return _token_row_to_dict(row, reutilizado=False)


def obtener_o_crear_token_portal(
    cur,
    tipo_portal: str,
    aspirante_id: Optional[int] = None,
    creador_id: Optional[int] = None,
    origen: str = "encuesta",
    creado_por: Optional[int] = None,
    duracion_dias: Optional[int] = None,
    forzar_nuevo: bool = False,
) -> dict:
    tipo_portal = validar_identidad_portal(
        tipo_portal=tipo_portal,
        aspirante_id=aspirante_id,
        creador_id=creador_id,
    )
    duracion_final = duracion_portal_por_tipo(tipo_portal, duracion_dias)

    if forzar_nuevo:
        revocar_tokens_activos(
            cur=cur,
            tipo_portal=tipo_portal,
            aspirante_id=aspirante_id,
            creador_id=creador_id,
        )

        return crear_token_portal(
            cur=cur,
            tipo_portal=tipo_portal,
            aspirante_id=aspirante_id,
            creador_id=creador_id,
            duracion_dias=duracion_final,
            creado_por=creado_por,
            origen=origen,
        )

    token_existente = obtener_token_portal_existente(
        cur=cur,
        tipo_portal=tipo_portal,
        aspirante_id=aspirante_id,
        creador_id=creador_id,
    )

    if token_existente:
        return renovar_token_portal(
            cur=cur,
            token_id=token_existente["id"],
            duracion_dias=duracion_final,
            creado_por=creado_por,
            origen=origen,
        )

    return crear_token_portal(
        cur=cur,
        tipo_portal=tipo_portal,
        aspirante_id=aspirante_id,
        creador_id=creador_id,
        duracion_dias=duracion_final,
        creado_por=creado_por,
        origen=origen,
    )


def _respuesta_url_desde_token(token_data: dict) -> dict:
    return {
        "url": construir_url_portal(token_data["token"]),
        "token": token_data["token"],
        "expiracion": token_data["expiracion"],
        "reutilizado": token_data["reutilizado"],
        "tipo_portal": token_data["tipo_portal"],
        "aspirante_id": token_data["aspirante_id"],
        "creador_id": token_data["creador_id"],
    }


def obtener_url_portal_token_existente(
    aspirante_id: Optional[int] = None,
    creador_id: Optional[int] = None,
) -> Optional[dict]:
    """
    Devuelve la URL del token activo sin crear uno nuevo.
    Tras incorporación, busca por creador_id y luego por aspirante_id.
    """
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            if creador_id:
                token_data = obtener_token_portal_activo(
                    cur,
                    tipo_portal="creador",
                    creador_id=creador_id,
                )
                if token_data:
                    return _respuesta_url_desde_token(token_data)

            if aspirante_id:
                token_data = obtener_token_portal_activo(
                    cur,
                    tipo_portal="aspirante",
                    aspirante_id=aspirante_id,
                )
                if token_data:
                    return _respuesta_url_desde_token(token_data)

                cur.execute(
                    f"""
                    SELECT {_TOKEN_SELECT_COLUMNS}
                    FROM portal_access_tokens
                    WHERE aspirante_id = %s
                      AND estado = 'activo'
                      AND expiracion > NOW()
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (aspirante_id,),
                )
                row = cur.fetchone()
                if row:
                    return _respuesta_url_desde_token(
                        _token_row_to_dict(row, reutilizado=True)
                    )

    return None


def generar_url_portal(
    tipo_portal: str,
    aspirante_id: Optional[int] = None,
    creador_id: Optional[int] = None,
    origen: str = "encuesta",
    creado_por: Optional[int] = None,
    duracion_dias: Optional[int] = None,
    forzar_nuevo: bool = False,
) -> dict:
    tipo_portal = validar_identidad_portal(
        tipo_portal=tipo_portal,
        aspirante_id=aspirante_id,
        creador_id=creador_id,
    )

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            token_data = obtener_o_crear_token_portal(
                cur=cur,
                tipo_portal=tipo_portal,
                aspirante_id=aspirante_id,
                creador_id=creador_id,
                origen=origen,
                creado_por=creado_por,
                duracion_dias=duracion_dias,
                forzar_nuevo=forzar_nuevo,
            )
            conn.commit()

    return _respuesta_url_desde_token(token_data)


def generar_url_portal_para_aspirante(
    aspirante_id: int,
    origen: str = "encuesta",
    creado_por: Optional[int] = None,
    forzar_nuevo: bool = False,
) -> str:
    data = generar_url_portal(
        tipo_portal="aspirante",
        aspirante_id=aspirante_id,
        creador_id=None,
        origen=origen,
        creado_por=creado_por,
        forzar_nuevo=forzar_nuevo,
    )
    return data["url"]


def generar_url_portal_para_creador(
    creador_id: int,
    origen: str = "whatsapp",
    creado_por: Optional[int] = None,
    forzar_nuevo: bool = False,
) -> str:
    data = generar_url_portal(
        tipo_portal="creador",
        aspirante_id=None,
        creador_id=creador_id,
        origen=origen,
        creado_por=creado_por,
        forzar_nuevo=forzar_nuevo,
    )
    return data["url"]


def generar_url_portal_usuario(
    tipo_portal: str,
    aspirante_id: Optional[int] = None,
    creador_id: Optional[int] = None,
    origen: str = "whatsapp",
    creado_por: Optional[int] = None,
    forzar_nuevo: bool = False,
) -> str:
    data = generar_url_portal(
        tipo_portal=tipo_portal,
        aspirante_id=aspirante_id,
        creador_id=creador_id,
        origen=origen,
        creado_por=creado_por,
        forzar_nuevo=forzar_nuevo,
    )
    return data["url"]
