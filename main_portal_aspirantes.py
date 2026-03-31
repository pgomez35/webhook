from datetime import datetime, timedelta
from typing import Optional

import secrets
import logging

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from DataBase import get_connection_context, obtener_cuenta_por_subdominio, guardar_mensaje_nuevo
from enviar_msg_wp import enviar_mensaje_texto_simple
from main_auth import obtener_usuario_actual
from tenant import current_tenant

logger = logging.getLogger("uvicorn.error")
router = APIRouter()


# =========================================================
# CONFIG
# =========================================================

DURACION_TOKEN_PORTAL_MINUTOS = 10080  # 7 días


# =========================================================
# MODELOS PYDANTIC
# =========================================================

class CrearLinkPortalIn(BaseModel):
    aspirante_id: int
    duracion_minutos: int = Field(default=DURACION_TOKEN_PORTAL_MINUTOS, ge=5, le=43200)
    origen: str = Field(default="whatsapp", max_length=30)


class LinkPortalOut(BaseModel):
    token: str
    url: str
    expiracion: datetime


class PortalValidateOut(BaseModel):
    valid: bool
    aspirante_id: int
    nombre: str
    estado_id: Optional[int] = None
    estado_nombre: str
    expiracion: datetime


class PortalModuloFlags(BaseModel):
    proceso: bool = True
    diagnostico: bool = False
    faq: bool = True
    incorporacion: bool = False


class PortalResumenOut(BaseModel):
    aspirante_id: int
    nombre: str
    telefono: Optional[str] = None
    whatsapp: Optional[str] = None
    email: Optional[str] = None
    usuario: Optional[str] = None
    estado_id: Optional[int] = None
    estado_nombre: str
    mensaje_estado: str
    tiempo_estimado: Optional[str] = None
    encuesta_terminada: bool = False
    modulos: PortalModuloFlags
    expiracion_token: datetime


class RevocarPortalOut(BaseModel):
    ok: bool
    message: str


# =========================================================
# HELPERS
# =========================================================

def generar_token_seguro(longitud_token: int = 24) -> str:
    """
    Genera token URL-safe.
    """
    return secrets.token_urlsafe(longitud_token)


def construir_url_portal(token: str) -> str:
    """
    Construye la URL del portal usando el tenant actual.
    """
    tenant_key = current_tenant.get() or "test"
    subdominio = tenant_key if tenant_key != "public" else "test"
    return f"https://{subdominio}.talentum-manager.com/portal?access={token}"


def mensaje_estado(estado_id: Optional[int]) -> str:
    """
    Estados actuales:
    1 Nuevo
    2 Preselección
    3 Evaluación
    4 Entrevista
    5 Invitación
    6 Incorporado
    7 Rechazado
    """
    if estado_id == 1:
        return "Tu registro fue recibido y está pendiente de revisión."
    if estado_id == 2:
        return "Tu perfil está en preselección."
    if estado_id == 3:
        return "Estamos evaluando tu perfil. Esta etapa suele tardar entre 7 y 10 días."
    if estado_id == 4:
        return "Tu proceso avanzó a entrevista."
    if estado_id == 5:
        return "Tu proceso avanzó a invitación. Aquí podrás revisar los siguientes pasos."
    if estado_id == 6:
        return "¡Bienvenido! Tu proceso ya fue aprobado y estás en etapa de incorporación."
    if estado_id == 7:
        return "Tu proceso finalizó. Gracias por tu interés en formar parte de la agencia."
    return "Consulta aquí el estado actualizado de tu proceso."


def tiempo_estimado_estado(estado_id: Optional[int]) -> Optional[str]:
    if estado_id == 3:
        return "7 a 10 días"
    return None


def construir_modulos(estado_id: Optional[int]) -> PortalModuloFlags:
    """
    No consulta diagnóstico ni citas.
    Solo define visibilidad mínima del menú del portal.
    """
    modulos = PortalModuloFlags(
        proceso=True,
        diagnostico=False,
        faq=True,
        incorporacion=False
    )

    # El módulo existe desde evaluación en adelante,
    # aunque el contenido real lo maneje otro endpoint/módulo.
    if estado_id in (3, 4, 5, 6):
        modulos.diagnostico = True

    if estado_id in (5, 6):
        modulos.incorporacion = True

    return modulos


def crear_link_portal_token(
    cur,
    aspirante_id: int,
    duracion_minutos: int,
    creado_por: Optional[int] = None,
    origen: str = "whatsapp",
    horas_expiracion: Optional[int] = None,
    longitud_token: int = 24
) -> dict:
    """
    Crea el token del portal.
    Si horas_expiracion viene informado, prevalece sobre duracion_minutos.
    """
    token = generar_token_seguro(longitud_token)

    if horas_expiracion is not None:
        expiracion = datetime.now() + timedelta(hours=horas_expiracion)
    else:
        expiracion = datetime.now() + timedelta(minutes=duracion_minutos)

    cur.execute(
        """
        INSERT INTO portal_access_tokens
        (
            token,
            aspirante_id,
            expiracion,
            estado,
            creado_en,
            duracion_minutos,
            creado_por,
            origen
        )
        VALUES (%s, %s, %s, 'activo', now(), %s, %s, %s)
        RETURNING id, token, expiracion
        """,
        (token, aspirante_id, expiracion, duracion_minutos, creado_por, origen)
    )
    row = cur.fetchone()

    return {
        "id": row[0],
        "token": row[1],
        "expiracion": row[2],
    }


def revocar_tokens_portal_activos(cur, aspirante_id: int) -> int:
    """
    Revoca tokens activos vigentes del aspirante.
    """
    cur.execute(
        """
        UPDATE portal_access_tokens
        SET estado = 'revocado'
        WHERE aspirante_id = %s
          AND estado = 'activo'
          AND expiracion > now()
        """,
        (aspirante_id,)
    )
    return cur.rowcount or 0


def actualizar_ultimo_uso_token(token: str) -> None:
    with get_connection_context() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE portal_access_tokens
            SET ultimo_uso_en = now()
            WHERE token = %s
            """,
            (token,)
        )
        conn.commit()


def resolver_aspirante_por_token_portal(token: str) -> Optional[dict]:
    with get_connection_context() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                pat.id AS token_id,
                pat.token,
                pat.aspirante_id,
                pat.expiracion,
                pat.estado AS token_estado,

                a.id,
                a.usuario,
                a.nickname,
                a.nombre_real,
                a.email,
                a.telefono,
                a.whatsapp,
                a.estado_id,
                COALESCE(a.encuesta_terminada, false) AS encuesta_terminada,

                COALESCE(ae.nombre, 'Proceso') AS estado_nombre
            FROM portal_access_tokens pat
            JOIN aspirantes a
              ON a.id = pat.aspirante_id
            LEFT JOIN aspirantes_estados ae
              ON ae.id = a.estado_id
            WHERE pat.token = %s
              AND pat.estado = 'activo'
              AND pat.expiracion > now()
            LIMIT 1
            """,
            (token,)
        )
        row = cur.fetchone()

        if not row:
            return None

        nombre = row[7] or row[8] or row[6] or f"Aspirante {row[5]}"

        return {
            "token_id": row[0],
            "token": row[1],
            "aspirante_id": row[2],
            "expiracion": row[3],
            "token_estado": row[4],

            "id": row[5],
            "usuario": row[6],
            "nickname": row[7],
            "nombre_real": row[8],
            "email": row[9],
            "telefono": row[10],
            "whatsapp": row[11],
            "estado_id": row[12],
            "encuesta_terminada": row[13],
            "estado_nombre": row[14],
            "nombre": nombre,
        }


def resolver_token_vigente_o_error(token: str) -> dict:
    info = resolver_aspirante_por_token_portal(token)
    if not info:
        raise HTTPException(
            status_code=404,
            detail="El enlace del portal no es válido o ya expiró."
        )
    return info


# =========================================================
# ENDPOINTS INTERNOS
# =========================================================

@router.post("/api/portal/aspirantes/crear-link", response_model=LinkPortalOut)
def crear_link_portal_aspirante(
    data: CrearLinkPortalIn,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    """
    Crea un link nuevo del portal para el aspirante.
    Regla simple:
    - revoca tokens activos anteriores
    - genera uno nuevo
    """
    with get_connection_context() as conn:
        cur = conn.cursor()

        # 1️⃣ Obtener datos del aspirante
        cur.execute(
            """
            SELECT id
            FROM aspirantes
            WHERE id = %s
            """,
            (data.aspirante_id,)
        )
        row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="El aspirante no existe.")

        # 2️⃣ Revocar tokens anteriores
        revocar_tokens_portal_activos(cur, data.aspirante_id)

        # 3️⃣ Crear token de portal
        creado_por = usuario_actual.get("id") if isinstance(usuario_actual, dict) else None

        token_data = crear_link_portal_token(
            cur=cur,
            aspirante_id=data.aspirante_id,
            duracion_minutos=data.duracion_minutos,
            creado_por=creado_por,
            origen=data.origen,
            horas_expiracion=None,
            longitud_token=24
        )

        token = token_data["token"]
        expiracion = token_data["expiracion"]

        conn.commit()

    # 4️⃣ Construir URL del portal
    url = construir_url_portal(token)

    # 5️⃣ Respuesta API
    return LinkPortalOut(
        token=token,
        url=url,
        expiracion=expiracion,
    )


@router.post("/api/portal/aspirantes/enviar", response_model=LinkPortalOut)
def enviar_link_portal_aspirante(
    data: CrearLinkPortalIn,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    """
    Envía un link del portal al aspirante por WhatsApp.
    Siempre intenta mensaje simple.
    Si Meta rechaza por ventana 24h, el webhook maneja el flujo de reenvío.
    """
    with get_connection_context() as conn:
        cur = conn.cursor()

        # 1️⃣ Obtener datos del aspirante
        cur.execute(
            """
            SELECT
                COALESCE(nickname, nombre_real, usuario) AS nombre,
                telefono
            FROM aspirantes
            WHERE id = %s
            """,
            (data.aspirante_id,)
        )
        row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="El aspirante no existe.")

        nombre_aspirante, telefono = row

        if not telefono:
            raise HTTPException(status_code=400, detail="El aspirante no tiene teléfono registrado.")

        # 2️⃣ Revocar tokens anteriores
        revocar_tokens_portal_activos(cur, data.aspirante_id)

        # 3️⃣ Crear token de portal
        creado_por = usuario_actual.get("id") if isinstance(usuario_actual, dict) else None

        token_data = crear_link_portal_token(
            cur=cur,
            aspirante_id=data.aspirante_id,
            duracion_minutos=data.duracion_minutos,
            creado_por=creado_por,
            origen=data.origen,
            horas_expiracion=None,
            longitud_token=24
        )

        token = token_data["token"]
        expiracion = token_data["expiracion"]

        conn.commit()

    # 4️⃣ Construir URL del portal
    url = construir_url_portal(token)

    # 5️⃣ Obtener credenciales WABA
    tenant_key = current_tenant.get() or "test"
    cuenta = obtener_cuenta_por_subdominio(tenant_key)
    if not cuenta:
        raise HTTPException(
            status_code=500,
            detail=f"No hay credenciales WABA para '{tenant_key}'."
        )

    business_name = cuenta.get("business_name", "la agencia")

    # 6️⃣ Construir mensaje simple
    mensaje = (
        f"Hola {nombre_aspirante or 'aspirante'} 👋\n\n"
        f"Tu proceso con *{business_name}* continúa avanzando.\n\n"
        "Desde este portal podrás revisar tu estado, conocer las etapas del proceso "
        "y acceder a la información disponible para ti.\n\n"
        f"🔗 {url}\n\n"
        f"🕒 Este enlace estará disponible hasta: {expiracion.strftime('%Y-%m-%d %H:%M')}.\n\n"
        "Este enlace se actualizará conforme avance tu proceso."
    )

    # 7️⃣ Enviar WhatsApp siempre como mensaje simple
    try:
        codigo, respuesta = enviar_mensaje_texto_simple(
            token=cuenta["access_token"],
            numero_id=cuenta["phone_number_id"],
            telefono_destino=telefono,
            texto=mensaje
        )

        message_id_meta = None
        if isinstance(respuesta, dict) and respuesta.get("messages"):
            try:
                message_id_meta = respuesta["messages"][0].get("id")
            except Exception:
                message_id_meta = None

        guardar_mensaje_nuevo(
            telefono=telefono,
            contenido=mensaje,
            direccion="enviado",
            tipo="text",
            message_id_meta=message_id_meta,
            estado="sent" if codigo and codigo < 300 else "error"
        )

    except Exception as e:
        logger.exception(
            "❌ Error enviando link de portal (aspirante_id=%s): %s",
            data.aspirante_id, e
        )
        raise HTTPException(
            status_code=500,
            detail=f"Error enviando link de portal: {str(e)}"
        )

    # 8️⃣ Respuesta API
    return LinkPortalOut(
        token=token,
        url=url,
        expiracion=expiracion,
    )


@router.post("/api/portal/aspirantes/{aspirante_id}/revocar", response_model=RevocarPortalOut)
def revocar_link_portal_aspirante(
    aspirante_id: int,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    with get_connection_context() as conn:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id
            FROM aspirantes
            WHERE id = %s
            """,
            (aspirante_id,)
        )
        row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="El aspirante no existe.")

        total = revocar_tokens_portal_activos(cur, aspirante_id)
        conn.commit()

    return RevocarPortalOut(
        ok=True,
        message=f"Se revocaron {total} token(s) activos del portal."
    )


# =========================================================
# ENDPOINTS PÚBLICOS DEL PORTAL
# =========================================================

@router.get("/api/portal/aspirantes/validar", response_model=PortalValidateOut)
def validar_token_portal_aspirante(token: str = Query(..., min_length=10)):
    info = resolver_token_vigente_o_error(token)
    actualizar_ultimo_uso_token(token)

    return PortalValidateOut(
        valid=True,
        aspirante_id=info["aspirante_id"],
        nombre=info["nombre"],
        estado_id=info["estado_id"],
        estado_nombre=info["estado_nombre"],
        expiracion=info["expiracion"],
    )


@router.get("/api/portal/aspirantes/resumen", response_model=PortalResumenOut)
def obtener_resumen_portal_aspirante(token: str = Query(..., min_length=10)):
    info = resolver_token_vigente_o_error(token)
    actualizar_ultimo_uso_token(token)

    modulos = construir_modulos(info["estado_id"])

    return PortalResumenOut(
        aspirante_id=info["aspirante_id"],
        nombre=info["nombre"],
        telefono=info["telefono"],
        whatsapp=info["whatsapp"],
        email=info["email"],
        usuario=info["usuario"],
        estado_id=info["estado_id"],
        estado_nombre=info["estado_nombre"],
        mensaje_estado=mensaje_estado(info["estado_id"]),
        tiempo_estimado=tiempo_estimado_estado(info["estado_id"]),
        encuesta_terminada=info["encuesta_terminada"],
        modulos=modulos,
        expiracion_token=info["expiracion"],
    )