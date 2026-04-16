import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from DataBase import get_connection_context
from tenant import current_tenant

router = APIRouter()

# =========================================================
# CONFIG
# =========================================================

TOKEN_LENGTH = 10
TOKEN_DURACION_MINUTOS = 10080  # 7 días

PORTAL_ROOT_DOMAIN = os.getenv("PORTAL_ROOT_DOMAIN", "talentum-manager.com").strip()
PORTAL_BASE_URL = os.getenv("PORTAL_BASE_URL", "").strip()


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
    """
    Construye la base del front para /agendar
    - test   -> https://test.talentum-manager.com/agendar
    - public -> https://talentum-manager.com/agendar
    """
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
# SCHEMAS BASE PORTAL
# =========================================================

class AgendamientoPendienteOut(BaseModel):
    pendiente: bool
    token: Optional[str] = None
    url: Optional[str] = None
    responsable_id: Optional[int] = None
    tipo_agendamiento: Optional[str] = None
    titulo: Optional[str] = None
    duracion_minutos: Optional[int] = None
    expiracion: Optional[datetime] = None


class PortalValidarOut(BaseModel):
    valid: bool
    aspirante_id: int
    nombre: str
    estado_id: Optional[int] = None
    estado_nombre: str
    expiracion: datetime


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
    modulos: dict
    expiracion_token: datetime
    agendamiento_pendiente: Optional[AgendamientoPendienteOut] = None


class LinkPortalOut(BaseModel):
    url: str
    token: str
    expiracion: datetime
    reutilizado: bool


# =========================================================
# SCHEMAS CITAS
# =========================================================

class CitaPortalOut(BaseModel):
    id: int
    titulo: str
    fecha_inicio: str
    fecha_fin: str
    duracion_minutos: int
    tipo_agendamiento: str
    tipo_color: Optional[str] = None
    tipo_icono: Optional[str] = None
    estado: str
    realizada: bool
    cancelada: bool
    puede_unirse: bool
    permite_modificar: bool
    es_proxima: bool
    link_meet: Optional[str] = None
    url_modificar: Optional[str] = None
    tiempo_restante_texto: Optional[str] = None


class PortalCitasOut(BaseModel):
    proxima_cita: Optional[CitaPortalOut] = None
    otras_citas: List[CitaPortalOut] = []
    total_citas: int
    tiene_citas: bool


class CitaAspiranteOut(BaseModel):
    id: int
    fecha_inicio: str
    fecha_fin: str
    duracion_minutos: int
    tipo_agendamiento: str
    realizada: bool
    estado: str
    link_meet: Optional[str] = None
    url_reagendar: Optional[str] = None


# =========================================================
# HELPERS TOKEN PORTAL
# =========================================================

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


def obtener_token_portal_activo(cur, aspirante_id: int) -> Optional[dict]:
    cur.execute(
        """
        SELECT
            id,
            token,
            expiracion,
            creado_en,
            duracion_minutos,
            creado_por,
            origen
        FROM portal_access_tokens
        WHERE aspirante_id = %s
          AND estado = 'activo'
          AND expiracion > NOW()
        ORDER BY expiracion DESC, id DESC
        LIMIT 1
        """,
        (aspirante_id,),
    )

    row = cur.fetchone()
    if not row:
        return None

    return {
        "id": row[0],
        "token": row[1],
        "expiracion": row[2],
        "creado_en": row[3],
        "duracion_minutos": row[4],
        "creado_por": row[5],
        "origen": row[6],
        "reutilizado": True,
    }


def revocar_tokens_activos(cur, aspirante_id: int) -> int:
    cur.execute(
        """
        UPDATE portal_access_tokens
        SET estado = 'revocado'
        WHERE aspirante_id = %s
          AND estado = 'activo'
          AND expiracion > NOW()
        """,
        (aspirante_id,),
    )
    return cur.rowcount or 0


def crear_token_portal(
    cur,
    aspirante_id: int,
    duracion_minutos: int = TOKEN_DURACION_MINUTOS,
    creado_por: Optional[int] = None,
    origen: str = "whatsapp",
) -> dict:
    token = generar_token_seguro(cur, TOKEN_LENGTH)
    expiracion = datetime.now() + timedelta(minutes=duracion_minutos)

    cur.execute(
        """
        INSERT INTO portal_access_tokens (
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
        RETURNING id, token, expiracion, creado_en, duracion_minutos, creado_por, origen
        """,
        (
            token,
            aspirante_id,
            expiracion,
            duracion_minutos,
            creado_por,
            origen,
        ),
    )

    row = cur.fetchone()

    return {
        "id": row[0],
        "token": row[1],
        "expiracion": row[2],
        "creado_en": row[3],
        "duracion_minutos": row[4],
        "creado_por": row[5],
        "origen": row[6],
        "reutilizado": False,
    }


def obtener_o_crear_token_portal(
    cur,
    aspirante_id: int,
    origen: str = "encuesta",
    creado_por: Optional[int] = None,
    duracion_minutos: int = TOKEN_DURACION_MINUTOS,
    forzar_nuevo: bool = False,
) -> dict:
    if forzar_nuevo:
        revocar_tokens_activos(cur, aspirante_id)
        return crear_token_portal(
            cur=cur,
            aspirante_id=aspirante_id,
            duracion_minutos=duracion_minutos,
            creado_por=creado_por,
            origen=origen,
        )

    token_activo = obtener_token_portal_activo(cur, aspirante_id)
    if token_activo:
        return token_activo

    return crear_token_portal(
        cur=cur,
        aspirante_id=aspirante_id,
        duracion_minutos=duracion_minutos,
        creado_por=creado_por,
        origen=origen,
    )


def generar_url_portal(
    aspirante_id: int,
    origen: str = "encuesta",
    creado_por: Optional[int] = None,
    duracion_minutos: int = TOKEN_DURACION_MINUTOS,
    forzar_nuevo: bool = False,
) -> dict:
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            token_data = obtener_o_crear_token_portal(
                cur=cur,
                aspirante_id=aspirante_id,
                origen=origen,
                creado_por=creado_por,
                duracion_minutos=duracion_minutos,
                forzar_nuevo=forzar_nuevo,
            )
            conn.commit()

    return {
        "url": construir_url_portal(token_data["token"]),
        "token": token_data["token"],
        "expiracion": token_data["expiracion"],
        "reutilizado": token_data["reutilizado"],
    }


# =========================================================
# HELPERS RESOLVER TOKEN PORTAL
# =========================================================

def resolver_token_vigente_o_error(token: str) -> dict:
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    pat.token,
                    pat.aspirante_id,
                    pat.expiracion,

                    a.nombre_real,
                    a.nickname,
                    a.usuario,
                    a.estado_id,
                    a.telefono,
                    a.whatsapp,
                    a.email,
                    COALESCE(a.encuesta_terminada, false) AS encuesta_terminada,

                    ae.nombre AS estado_nombre

                FROM portal_access_tokens pat
                JOIN aspirantes a
                    ON a.id = pat.aspirante_id
                LEFT JOIN aspirantes_estados ae
                    ON ae.id = a.estado_id
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

            nombre = row[3] or row[4] or row[5] or f"Aspirante {row[1]}"

            return {
                "token": row[0],
                "aspirante_id": row[1],
                "expiracion": row[2],
                "nombre": nombre,
                "estado_id": row[6],
                "telefono": row[7],
                "whatsapp": row[8],
                "email": row[9],
                "encuesta_terminada": row[10],
                "estado_nombre": row[11] or "Proceso",
                "usuario": row[5],
            }


def actualizar_uso_token(token: str) -> None:
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE portal_access_tokens
                SET ultimo_uso_en = NOW()
                WHERE token = %s
                """,
                (token,),
            )
            conn.commit()


# =========================================================
# HELPERS AGENDAMIENTO PENDIENTE
# =========================================================

def construir_titulo_autoagendado(tipo_agendamiento: Optional[str]) -> str:
    tipo = (tipo_agendamiento or "").strip().upper()

    if tipo == "LIVE":
        return "Prueba TikTok LIVE"

    if tipo == "ENTREVISTA":
        return "Entrevista con asesor"

    return tipo_agendamiento or "Agendamiento pendiente"


def existe_cita_futura_del_tipo(cur, aspirante_id: int, tipo_agendamiento: Optional[str]) -> bool:
    """
    Evita mostrar botón de agendar si ya existe una cita futura del mismo tipo.
    """
    cur.execute(
        """
        SELECT 1
        FROM agendamientos a
        INNER JOIN agendamientos_participantes ap
            ON ap.agendamiento_id = a.id
        INNER JOIN agendamientos_tipo at
            ON at.id = a.tipo_agendamiento
        LEFT JOIN agendamientos_estados ae
            ON ae.id = a.estado
        WHERE ap.participante_tipo_id = 1
          AND ap.participante_id = %s
          AND at.participante_tipo_id = 1
          AND UPPER(COALESCE(at.nombre, '')) = UPPER(%s)
          AND COALESCE(ae.nombre, 'programado') NOT IN ('cancelado', 'cumplido')
          AND a.fecha_fin >= NOW()
        LIMIT 1
        """,
        (aspirante_id, tipo_agendamiento or ""),
    )
    return cur.fetchone() is not None


def obtener_agendamiento_pendiente(cur, aspirante_id: int) -> Optional[dict]:
    """
    Busca un autoagendado pendiente vigente en agendamientos_link_tokens.
    Reglas:
    - mismo aspirante
    - no usado
    - no expirado
    - si ya hay cita futura del mismo tipo, no lo muestra
    """
    cur.execute(
        """
        SELECT
            token,
            aspirante_id,
            responsable_id,
            expiracion,
            usado,
            creado_en,
            duracion_minutos,
            tipo_agendamiento,
            usado_en
        FROM agendamientos_link_tokens
        WHERE aspirante_id = %s
          AND COALESCE(usado, false) = false
          AND expiracion > NOW()
        ORDER BY expiracion ASC, creado_en DESC
        LIMIT 1
        """,
        (aspirante_id,),
    )

    row = cur.fetchone()
    if not row:
        return None

    data = {
        "token": row[0],
        "aspirante_id": row[1],
        "responsable_id": row[2],
        "expiracion": row[3],
        "usado": row[4],
        "creado_en": row[5],
        "duracion_minutos": row[6] or 60,
        "tipo_agendamiento": row[7] or "ENTREVISTA",
        "usado_en": row[8],
    }

    if existe_cita_futura_del_tipo(
        cur=cur,
        aspirante_id=aspirante_id,
        tipo_agendamiento=data["tipo_agendamiento"],
    ):
        return None

    return {
        "pendiente": True,
        "token": data["token"],
        "url": construir_url_agendamiento(data["token"]),
        "responsable_id": data["responsable_id"],
        "tipo_agendamiento": data["tipo_agendamiento"],
        "titulo": construir_titulo_autoagendado(data["tipo_agendamiento"]),
        "duracion_minutos": data["duracion_minutos"],
        "expiracion": data["expiracion"],
    }


# =========================================================
# HELPERS PORTAL
# =========================================================

def construir_modulos(estado_id: Optional[int], tiene_agendamiento_pendiente: bool = False) -> dict:
    return {
        "proceso": True,
        "faq": True,
        "diagnostico": estado_id in (3, 4, 5, 6),
        "citas": estado_id == 4 or tiene_agendamiento_pendiente,
        "incorporacion": estado_id in (5, 6),
        "documentos": False,
        "pagos": False,
        "soporte": True,
    }


def mensaje_estado(estado_id: Optional[int]) -> str:
    mensajes = {
        1: "Tu registro fue recibido y está pendiente de revisión.",
        2: "Tu perfil está en preselección.",
        3: "Estamos evaluando tu perfil. Esta etapa suele tardar entre 7 y 10 días.",
        4: "Tu proceso avanzó a entrevista.",
        5: "Tu proceso avanzó a invitación.",
        6: "¡Bienvenido! Estás en proceso de incorporación.",
        7: "Tu proceso finalizó. Gracias por participar.",
    }
    return mensajes.get(estado_id, "Proceso en curso.")


def tiempo_estimado_estado(estado_id: Optional[int]) -> Optional[str]:
    if estado_id == 3:
        return "7 a 10 días"
    return None


# =========================================================
# ENDPOINTS BASE PORTAL
# =========================================================

@router.get("/api/portal/aspirantes/validar", response_model=PortalValidarOut)
def validar_portal(token: str = Query(..., min_length=10)):
    info = resolver_token_vigente_o_error(token)
    actualizar_uso_token(token)

    return PortalValidarOut(
        valid=True,
        aspirante_id=info["aspirante_id"],
        nombre=info["nombre"],
        estado_id=info["estado_id"],
        estado_nombre=info["estado_nombre"],
        expiracion=info["expiracion"],
    )


@router.get("/api/portal/aspirantes/resumen", response_model=PortalResumenOut)
def resumen_portal(token: str = Query(..., min_length=10)):
    info = resolver_token_vigente_o_error(token)
    actualizar_uso_token(token)

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            agendamiento_pendiente = obtener_agendamiento_pendiente(
                cur=cur,
                aspirante_id=info["aspirante_id"],
            )

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
        modulos=construir_modulos(
            estado_id=info["estado_id"],
            tiene_agendamiento_pendiente=agendamiento_pendiente is not None,
        ),
        expiracion_token=info["expiracion"],
        agendamiento_pendiente=(
            AgendamientoPendienteOut(**agendamiento_pendiente)
            if agendamiento_pendiente
            else AgendamientoPendienteOut(pendiente=False)
        ),
    )


# =========================================================
# HELPERS CITAS
# =========================================================

def calcular_duracion_minutos(
    fecha_inicio: Optional[datetime],
    fecha_fin: Optional[datetime],
) -> int:
    if not fecha_inicio or not fecha_fin:
        return 0
    return int((fecha_fin - fecha_inicio).total_seconds() // 60)


def construir_tiempo_restante_texto(
    ahora: datetime,
    fecha_inicio: Optional[datetime],
    fecha_fin: Optional[datetime],
) -> Optional[str]:
    if not fecha_inicio or not fecha_fin:
        return None

    if fecha_fin < ahora:
        return "Cita finalizada"

    if fecha_inicio <= ahora <= fecha_fin:
        return "Disponible ahora"

    diferencia = fecha_inicio - ahora
    total_min = int(diferencia.total_seconds() // 60)

    if total_min < 1:
        return "Disponible ahora"

    if total_min < 60:
        return f"Empieza en {total_min} min"

    horas = total_min // 60
    minutos = total_min % 60

    if minutos == 0:
        return f"Empieza en {horas} h"

    return f"Empieza en {horas} h {minutos} min"


def calcular_puede_unirse(
    ahora: datetime,
    fecha_inicio: Optional[datetime],
    fecha_fin: Optional[datetime],
    estado: str,
    link_meet: Optional[str],
) -> bool:
    if not fecha_inicio or not fecha_fin or not link_meet:
        return False

    estado_norm = (estado or "").strip().lower()

    if estado_norm in ("cancelado", "cumplido"):
        return False

    ventana_inicio = fecha_inicio - timedelta(minutes=15)
    ventana_fin = fecha_fin + timedelta(hours=4)

    return ventana_inicio <= ahora <= ventana_fin


def construir_titulo_cita(tipo_icono: Optional[str], tipo_nombre: str) -> str:
    if tipo_icono:
        return f"{tipo_icono} {tipo_nombre}"
    return tipo_nombre


def mapear_cita_portal(
    row,
    ahora: datetime,
    es_proxima: bool = False,
) -> CitaPortalOut:
    (
        a_id,
        titulo_db,
        fecha_inicio,
        fecha_fin,
        estado_nombre,
        tipo_nombre,
        tipo_color,
        tipo_icono,
        link_meet,
    ) = row

    estado = estado_nombre or "programado"
    estado_norm = estado.strip().lower()

    realizada = estado_norm == "cumplido"
    cancelada = estado_norm == "cancelado"
    permite_modificar = not realizada and not cancelada

    puede_unirse = calcular_puede_unirse(
        ahora=ahora,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        estado=estado,
        link_meet=link_meet,
    )

    duracion_minutos = calcular_duracion_minutos(fecha_inicio, fecha_fin)
    titulo = titulo_db or construir_titulo_cita(tipo_icono, tipo_nombre)

    return CitaPortalOut(
        id=a_id,
        titulo=titulo,
        fecha_inicio=fecha_inicio.isoformat() if fecha_inicio else "",
        fecha_fin=fecha_fin.isoformat() if fecha_fin else "",
        duracion_minutos=duracion_minutos,
        tipo_agendamiento=tipo_nombre,
        tipo_color=tipo_color,
        tipo_icono=tipo_icono,
        estado=estado,
        realizada=realizada,
        cancelada=cancelada,
        puede_unirse=puede_unirse,
        permite_modificar=permite_modificar,
        es_proxima=es_proxima,
        link_meet=link_meet,
        url_modificar=f"/portal/citas/{a_id}/modificar" if permite_modificar else None,
        tiempo_restante_texto=construir_tiempo_restante_texto(
            ahora=ahora,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
        ),
    )


# =========================================================
# ENDPOINT CITAS PORTAL
# =========================================================

@router.get("/api/portal/aspirantes/{aspirante_id}/citas", response_model=PortalCitasOut)
def obtener_citas_portal_aspirante(aspirante_id: int):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    a.id,
                    a.titulo,
                    a.fecha_inicio,
                    a.fecha_fin,
                    COALESCE(ae.nombre, 'programado') AS estado_nombre,
                    at.nombre AS tipo_nombre,
                    at.color AS tipo_color,
                    at.icono AS tipo_icono,
                    a.link_meet
                FROM agendamientos a
                INNER JOIN agendamientos_participantes ap
                    ON ap.agendamiento_id = a.id
                INNER JOIN agendamientos_tipo at
                    ON at.id = a.tipo_agendamiento
                LEFT JOIN agendamientos_estados ae
                    ON ae.id = a.estado
                WHERE ap.participante_tipo_id = 1
                  AND ap.participante_id = %s
                  AND at.participante_tipo_id = 1
                ORDER BY a.fecha_inicio ASC
                """,
                (aspirante_id,),
            )
            rows = cur.fetchall()

    ahora = datetime.now()
    citas_validas = []

    for row in rows:
        (
            a_id,
            titulo_db,
            fecha_inicio,
            fecha_fin,
            estado_nombre,
            tipo_nombre,
            tipo_color,
            tipo_icono,
            link_meet,
        ) = row

        estado_norm = (estado_nombre or "programado").strip().lower()

        if estado_norm in ("cancelado", "cumplido"):
            continue

        if fecha_fin and fecha_fin < ahora:
            continue

        citas_validas.append(
            (
                a_id,
                titulo_db,
                fecha_inicio,
                fecha_fin,
                estado_nombre,
                tipo_nombre,
                tipo_color,
                tipo_icono,
                link_meet,
            )
        )

    if not citas_validas:
        return PortalCitasOut(
            proxima_cita=None,
            otras_citas=[],
            total_citas=0,
            tiene_citas=False,
        )

    proxima_row = citas_validas[0]
    otras_rows = citas_validas[1:]

    proxima_cita = mapear_cita_portal(
        row=proxima_row,
        ahora=ahora,
        es_proxima=True,
    )

    otras_citas = [
        mapear_cita_portal(row=row, ahora=ahora, es_proxima=False)
        for row in otras_rows
    ]

    return PortalCitasOut(
        proxima_cita=proxima_cita,
        otras_citas=otras_citas,
        total_citas=len(citas_validas),
        tiene_citas=True,
    )


# =========================================================
# FUNCION AUXILIAR PARA OTROS MODULOS
# =========================================================

def generar_url_portal_para_aspirante(
    aspirante_id: int,
    origen: str = "encuesta",
    creado_por: Optional[int] = None,
    forzar_nuevo: bool = False,
) -> str:
    data = generar_url_portal(
        aspirante_id=aspirante_id,
        origen=origen,
        creado_por=creado_por,
        forzar_nuevo=forzar_nuevo,
    )
    return data["url"]
