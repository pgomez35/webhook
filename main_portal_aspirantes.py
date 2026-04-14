import secrets
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from DataBase import get_connection_context
from main_auth import obtener_usuario_actual

router = APIRouter()

# =========================================================
# CONFIG
# =========================================================

BASE_PORTAL_URL = "https://test.talentum-manager.com/portal"
TOKEN_LENGTH = 10
TOKEN_DURACION_MINUTOS = 10080  # 7 días


# =========================================================
# SCHEMAS BASE PORTAL
# =========================================================

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
# HELPERS TOKEN / URL
# =========================================================

def construir_url_portal(token: str) -> str:
    return f"{BASE_PORTAL_URL}?access={token}"


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
# HELPERS RESOLVER TOKEN
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
# HELPERS PORTAL
# =========================================================

def construir_modulos(estado_id: Optional[int]) -> dict:
    return {
        "proceso": True,
        "faq": True,
        "diagnostico": estado_id in (3, 4, 5, 6),
        "citas": estado_id == 4,
        "incorporacion": estado_id in (5, 6),
        # Deja este espacio para crecer sin romper contrato:
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

@router.post("/api/portal/aspirantes/{aspirante_id}/generar-link", response_model=LinkPortalOut)
def generar_link(
    aspirante_id: int,
    forzar_nuevo: bool = Query(False),
    usuario=Depends(obtener_usuario_actual),
):
    data = generar_url_portal(
        aspirante_id=aspirante_id,
        creado_por=usuario.get("id") if isinstance(usuario, dict) else None,
        origen="backoffice",
        forzar_nuevo=forzar_nuevo,
    )

    return LinkPortalOut(**data)


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
        modulos=construir_modulos(info["estado_id"]),
        expiracion_token=info["expiracion"],
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
# ENDPOINT COMPATIBLE LISTADO SIMPLE
# =========================================================

@router.get("/api/aspirantes/{aspirante_id}/citas", response_model=List[CitaAspiranteOut])
def listar_citas_aspirante(aspirante_id: int):
    citas: List[CitaAspiranteOut] = []

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    a.id,
                    a.fecha_inicio,
                    a.fecha_fin,
                    COALESCE(ae.nombre, 'programado') AS estado_nombre,
                    at.nombre AS tipo_nombre,
                    a.link_meet
                FROM agendamientos a
                INNER JOIN agendamientos_participantes ap
                    ON ap.agendamiento_id = a.id
                LEFT JOIN agendamientos_estados ae
                    ON ae.id = a.estado
                INNER JOIN agendamientos_tipo at
                    ON at.id = a.tipo_agendamiento
                WHERE ap.participante_tipo_id = 1
                  AND ap.participante_id = %s
                  AND at.participante_tipo_id = 1
                ORDER BY a.fecha_inicio ASC
                """,
                (aspirante_id,),
            )
            rows = cur.fetchall()

    for a_id, f_ini, f_fin, estado_nombre, tipo_nombre, link_meet in rows:
        duracion_min = calcular_duracion_minutos(f_ini, f_fin)
        realizada = (estado_nombre or "").strip().lower() == "cumplido"

        citas.append(
            CitaAspiranteOut(
                id=a_id,
                fecha_inicio=f_ini.isoformat() if f_ini else "",
                fecha_fin=f_fin.isoformat() if f_fin else "",
                duracion_minutos=duracion_min,
                tipo_agendamiento=tipo_nombre,
                realizada=realizada,
                estado=estado_nombre or "programado",
                link_meet=link_meet,
                url_reagendar=None,
            )
        )

    return citas


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




# import secrets
# from datetime import datetime, timedelta
# from typing import Optional
#
# from fastapi import APIRouter, HTTPException, Query, Depends
#
# from DataBase import get_connection_context
# from main_auth import obtener_usuario_actual
#
# router = APIRouter()
#
# # =========================================================
# # CONFIG
# # =========================================================
#
# BASE_PORTAL_URL = "https://test.talentum-manager.com/portal"
# TOKEN_LENGTH = 10
# TOKEN_DURACION_MINUTOS = 10080  # 7 días
#
#
# # =========================================================
# # TOKEN LOGIC
# # =========================================================
#
# def token_existe_activo(cur, token: str) -> bool:
#     cur.execute("""
#         SELECT 1
#         FROM portal_access_tokens
#         WHERE token = %s
#           AND estado = 'activo'
#           AND expiracion > NOW()
#         LIMIT 1
#     """, (token,))
#     return cur.fetchone() is not None
#
#
# def generar_token_seguro(cur, longitud_token: int = TOKEN_LENGTH) -> str:
#     while True:
#         token = secrets.token_urlsafe(8)[:longitud_token]
#         if not token_existe_activo(cur, token):
#             return token
#
#
# def revocar_tokens_activos(cur, aspirante_id: int):
#     cur.execute("""
#         UPDATE portal_access_tokens
#         SET estado = 'revocado'
#         WHERE aspirante_id = %s
#           AND estado = 'activo'
#     """, (aspirante_id,))
#
#
# def crear_token_portal(
#     cur,
#     aspirante_id: int,
#     duracion_minutos: int = TOKEN_DURACION_MINUTOS,
#     creado_por: Optional[int] = None,
#     origen: str = "whatsapp"
# ) -> dict:
#
#     token = generar_token_seguro(cur, TOKEN_LENGTH)
#     expiracion = datetime.now() + timedelta(minutes=duracion_minutos)
#
#     cur.execute("""
#         INSERT INTO portal_access_tokens (
#             token,
#             aspirante_id,
#             expiracion,
#             estado,
#             creado_en,
#             duracion_minutos,
#             creado_por,
#             origen
#         )
#         VALUES (%s, %s, %s, 'activo', now(), %s, %s, %s)
#         RETURNING id, token, expiracion
#     """, (
#         token,
#         aspirante_id,
#         expiracion,
#         duracion_minutos,
#         creado_por,
#         origen
#     ))
#
#     row = cur.fetchone()
#
#     return {
#         "id": row[0],
#         "token": row[1],
#         "expiracion": row[2],
#     }
#
#
# def generar_url_portal(
#     aspirante_id: int,
#     origen: str = "encuesta",
#     creado_por: Optional[int] = None
# ) -> str:
#
#     with get_connection_context() as conn:
#         with conn.cursor() as cur:
#
#             # 🔁 Revocar tokens anteriores
#             revocar_tokens_activos(cur, aspirante_id)
#
#             # 🆕 Crear token
#             token_data = crear_token_portal(
#                 cur=cur,
#                 aspirante_id=aspirante_id,
#                 creado_por=creado_por,
#                 origen=origen
#             )
#
#             return f"{BASE_PORTAL_URL}?access={token_data['token']}"
#
#
# # =========================================================
# # RESOLVER TOKEN
# # =========================================================
#
# def resolver_token_vigente_o_error(token: str) -> dict:
#     with get_connection_context() as conn:
#         with conn.cursor() as cur:
#
#             cur.execute("""
#                 SELECT
#                     pat.token,
#                     pat.aspirante_id,
#                     pat.expiracion,
#
#                     a.nombre_real,
#                     a.nickname,
#                     a.estado_id,
#                     a.telefono,
#                     a.whatsapp,
#                     a.email,
#                     a.usuario,
#                     COALESCE(a.encuesta_terminada, false),
#
#                     ae.nombre as estado_nombre
#
#                 FROM portal_access_tokens pat
#                 JOIN aspirantes a ON a.id = pat.aspirante_id
#                 LEFT JOIN aspirantes_estados ae ON ae.id = a.estado_id
#
#                 WHERE pat.token = %s
#                   AND pat.estado = 'activo'
#                   AND pat.expiracion > now()
#
#                 LIMIT 1
#             """, (token,))
#
#             row = cur.fetchone()
#
#             if not row:
#                 raise HTTPException(
#                     status_code=404,
#                     detail="El enlace del portal no es válido o expiró."
#                 )
#
#             return {
#                 "token": row[0],
#                 "aspirante_id": row[1],
#                 "expiracion": row[2],
#                 "nombre": row[3] or row[4],
#                 "estado_id": row[5],
#                 "telefono": row[6],
#                 "whatsapp": row[7],
#                 "email": row[8],
#                 "usuario": row[9],
#                 "encuesta_terminada": row[10],
#                 "estado_nombre": row[11] or "Proceso"
#             }
#
#
# def actualizar_uso_token(token: str):
#     with get_connection_context() as conn:
#         with conn.cursor() as cur:
#             cur.execute("""
#                 UPDATE portal_access_tokens
#                 SET ultimo_uso_en = now()
#                 WHERE token = %s
#             """, (token,))
#
#
# # =========================================================
# # ENDPOINT: GENERAR LINK (BACKOFFICE)
# # =========================================================
#
# @router.post("/api/portal/aspirantes/{aspirante_id}/generar-link")
# def generar_link(
#     aspirante_id: int,
#     usuario=Depends(obtener_usuario_actual)
# ):
#     url = generar_url_portal(
#         aspirante_id=aspirante_id,
#         creado_por=usuario.get("id"),
#         origen="backoffice"
#     )
#
#     return {
#         "url": url
#     }
#
#
# # =========================================================
# # ENDPOINT: VALIDAR TOKEN
# # =========================================================
#
# @router.get("/api/portal/aspirantes/validar")
# def validar_portal(token: str = Query(..., min_length=10)):
#
#     info = resolver_token_vigente_o_error(token)
#
#     actualizar_uso_token(token)
#
#     return {
#         "valid": True,
#         "aspirante_id": info["aspirante_id"],
#         "nombre": info["nombre"],
#         "estado_id": info["estado_id"],
#         "estado_nombre": info["estado_nombre"],
#         "expiracion": info["expiracion"],
#     }
#
#
# # =========================================================
# # HELPERS PORTAL
# # =========================================================
#
# def construir_modulos(estado_id: int) -> dict:
#     return {
#         "proceso": True,
#         "faq": True,
#         "diagnostico": estado_id in (3, 4, 5, 6),
#         "citas": estado_id == 4,
#         "incorporacion": estado_id in (5, 6),
#     }
#
#
# def mensaje_estado(estado_id: int) -> str:
#     mensajes = {
#         1: "Tu registro fue recibido y está pendiente de revisión.",
#         2: "Tu perfil está en preselección.",
#         3: "Estamos evaluando tu perfil. Esta etapa suele tardar entre 7 y 10 días.",
#         4: "Tu proceso avanzó a entrevista.",
#         5: "Tu proceso avanzó a invitación.",
#         6: "¡Bienvenido! Estás en proceso de incorporación.",
#         7: "Tu proceso finalizó. Gracias por participar."
#     }
#     return mensajes.get(estado_id, "Proceso en curso.")
#
#
# def tiempo_estimado_estado(estado_id: int) -> Optional[str]:
#     if estado_id == 3:
#         return "7 a 10 días"
#     return None
#
#
# # =========================================================
# # ENDPOINT: RESUMEN PORTAL
# # =========================================================
#
# @router.get("/api/portal/aspirantes/resumen")
# def resumen_portal(token: str = Query(..., min_length=10)):
#
#     info = resolver_token_vigente_o_error(token)
#
#     actualizar_uso_token(token)
#
#     return {
#         "aspirante_id": info["aspirante_id"],
#         "nombre": info["nombre"],
#         "telefono": info["telefono"],
#         "whatsapp": info["whatsapp"],
#         "email": info["email"],
#         "usuario": info["usuario"],
#         "estado_id": info["estado_id"],
#         "estado_nombre": info["estado_nombre"],
#         "mensaje_estado": mensaje_estado(info["estado_id"]),
#         "tiempo_estimado": tiempo_estimado_estado(info["estado_id"]),
#         "encuesta_terminada": info["encuesta_terminada"],
#         "modulos": construir_modulos(info["estado_id"]),
#         "expiracion_token": info["expiracion"]
#     }
#
#
#
#
#
# # -------------------------------------------
# # -------------------------------------------
# # -------------------------------------------
# # -------------------------------------------
#
# from pydantic import BaseModel
# from typing import List
#
# # =========================
# # SCHEMAS
# # =========================
#
# class CitaPortalOut(BaseModel):
#     id: int
#     titulo: str
#     fecha_inicio: str
#     fecha_fin: str
#     duracion_minutos: int
#     tipo_agendamiento: str
#     tipo_color: Optional[str] = None
#     tipo_icono: Optional[str] = None
#     estado: str
#     realizada: bool
#     cancelada: bool
#     puede_unirse: bool
#     permite_modificar: bool
#     es_proxima: bool
#     link_meet: Optional[str] = None
#     url_modificar: Optional[str] = None
#     tiempo_restante_texto: Optional[str] = None
#
#
# class PortalCitasOut(BaseModel):
#     proxima_cita: Optional[CitaPortalOut] = None
#     otras_citas: List[CitaPortalOut] = []
#     total_citas: int
#     tiene_citas: bool
#
#
# # =========================
# # HELPERS
# # =========================
#
# def calcular_duracion_minutos(fecha_inicio: Optional[datetime], fecha_fin: Optional[datetime]) -> int:
#     if not fecha_inicio or not fecha_fin:
#         return 0
#     return int((fecha_fin - fecha_inicio).total_seconds() // 60)
#
#
# def construir_tiempo_restante_texto(ahora: datetime, fecha_inicio: Optional[datetime], fecha_fin: Optional[datetime]) -> Optional[str]:
#     if not fecha_inicio or not fecha_fin:
#         return None
#
#     if fecha_fin < ahora:
#         return "Cita finalizada"
#
#     if fecha_inicio <= ahora <= fecha_fin:
#         return "Disponible ahora"
#
#     diferencia = fecha_inicio - ahora
#     total_min = int(diferencia.total_seconds() // 60)
#
#     if total_min < 1:
#         return "Disponible ahora"
#
#     if total_min < 60:
#         return f"Empieza en {total_min} min"
#
#     horas = total_min // 60
#     minutos = total_min % 60
#
#     if minutos == 0:
#         return f"Empieza en {horas} h"
#
#     return f"Empieza en {horas} h {minutos} min"
#
#
# def calcular_puede_unirse(
#     ahora: datetime,
#     fecha_inicio: Optional[datetime],
#     fecha_fin: Optional[datetime],
#     estado: str,
#     link_meet: Optional[str],
# ) -> bool:
#     if not fecha_inicio or not fecha_fin or not link_meet:
#         return False
#
#     estado_norm = (estado or "").strip().lower()
#
#     if estado_norm in ("cancelado", "cumplido"):
#         return False
#
#     ventana_inicio = fecha_inicio - timedelta(minutes=15)
#     ventana_fin = fecha_fin + timedelta(hours=4)
#
#     return ventana_inicio <= ahora <= ventana_fin
#
#
# def construir_titulo_cita(tipo_icono: Optional[str], tipo_nombre: str) -> str:
#     if tipo_icono:
#         return f"{tipo_icono} {tipo_nombre}"
#     return tipo_nombre
#
#
# def mapear_cita_portal(
#     row,
#     ahora: datetime,
#     es_proxima: bool = False,
# ) -> CitaPortalOut:
#     (
#         a_id,
#         titulo_db,
#         fecha_inicio,
#         fecha_fin,
#         estado_nombre,
#         tipo_nombre,
#         tipo_color,
#         tipo_icono,
#         link_meet,
#     ) = row
#
#     estado = estado_nombre or "programado"
#     estado_norm = estado.strip().lower()
#
#     realizada = estado_norm == "cumplido"
#     cancelada = estado_norm == "cancelado"
#     permite_modificar = not realizada and not cancelada
#     puede_unirse = calcular_puede_unirse(
#         ahora=ahora,
#         fecha_inicio=fecha_inicio,
#         fecha_fin=fecha_fin,
#         estado=estado,
#         link_meet=link_meet,
#     )
#
#     duracion_minutos = calcular_duracion_minutos(fecha_inicio, fecha_fin)
#
#     titulo = titulo_db or construir_titulo_cita(tipo_icono, tipo_nombre)
#
#     return CitaPortalOut(
#         id=a_id,
#         titulo=titulo,
#         fecha_inicio=fecha_inicio.isoformat() if fecha_inicio else "",
#         fecha_fin=fecha_fin.isoformat() if fecha_fin else "",
#         duracion_minutos=duracion_minutos,
#         tipo_agendamiento=tipo_nombre,
#         tipo_color=tipo_color,
#         tipo_icono=tipo_icono,
#         estado=estado,
#         realizada=realizada,
#         cancelada=cancelada,
#         puede_unirse=puede_unirse,
#         permite_modificar=permite_modificar,
#         es_proxima=es_proxima,
#         link_meet=link_meet,
#         url_modificar=f"/portal/citas/{a_id}/modificar" if permite_modificar else None,
#         tiempo_restante_texto=construir_tiempo_restante_texto(
#             ahora=ahora,
#             fecha_inicio=fecha_inicio,
#             fecha_fin=fecha_fin,
#         ),
#     )
#
#
# # =========================
# # ENDPOINT PRINCIPAL PORTAL
# # =========================
#
# @router.get("/api/portal/aspirantes/{aspirante_id}/citas", response_model=PortalCitasOut)
# def obtener_citas_portal_aspirante(aspirante_id: int):
#     """
#     Devuelve las citas del aspirante separadas en:
#     - proxima_cita
#     - otras_citas
#
#     Reglas:
#     - solo participante_tipo_id = 1 (aspirante)
#     - excluye canceladas
#     - excluye cumplidas
#     - excluye citas ya terminadas
#     """
#
#     with get_connection_context() as conn:
#         with conn.cursor() as cur:
#             cur.execute(
#                 """
#                 SELECT
#                     a.id,
#                     a.titulo,
#                     a.fecha_inicio,
#                     a.fecha_fin,
#                     COALESCE(ae.nombre, 'programado') AS estado_nombre,
#                     at.nombre AS tipo_nombre,
#                     at.color AS tipo_color,
#                     at.icono AS tipo_icono,
#                     a.link_meet
#                 FROM agendamientos a
#                 INNER JOIN agendamientos_participantes ap
#                     ON ap.agendamiento_id = a.id
#                 INNER JOIN agendamientos_tipo at
#                     ON at.id = a.tipo_agendamiento
#                 LEFT JOIN agendamientos_estados ae
#                     ON ae.id = a.estado
#                 WHERE ap.participante_tipo_id = 1
#                   AND ap.participante_id = %s
#                   AND at.participante_tipo_id = 1
#                 ORDER BY a.fecha_inicio ASC
#                 """,
#                 (aspirante_id,)
#             )
#             rows = cur.fetchall()
#
#     ahora = datetime.now()
#     citas_validas = []
#
#     for row in rows:
#         (
#             a_id,
#             titulo_db,
#             fecha_inicio,
#             fecha_fin,
#             estado_nombre,
#             tipo_nombre,
#             tipo_color,
#             tipo_icono,
#             link_meet,
#         ) = row
#
#         estado_norm = (estado_nombre or "programado").strip().lower()
#
#         # Excluir canceladas y cumplidas
#         if estado_norm in ("cancelado", "cumplido"):
#             continue
#
#         # Excluir citas que ya terminaron
#         if fecha_fin and fecha_fin < ahora:
#             continue
#
#         citas_validas.append(
#             (
#                 a_id,
#                 titulo_db,
#                 fecha_inicio,
#                 fecha_fin,
#                 estado_nombre,
#                 tipo_nombre,
#                 tipo_color,
#                 tipo_icono,
#                 link_meet,
#             )
#         )
#
#     if not citas_validas:
#         return PortalCitasOut(
#             proxima_cita=None,
#             otras_citas=[],
#             total_citas=0,
#             tiene_citas=False,
#         )
#
#     proxima_row = citas_validas[0]
#     otras_rows = citas_validas[1:]
#
#     proxima_cita = mapear_cita_portal(
#         row=proxima_row,
#         ahora=ahora,
#         es_proxima=True,
#     )
#
#     otras_citas = [
#         mapear_cita_portal(row=row, ahora=ahora, es_proxima=False)
#         for row in otras_rows
#     ]
#
#     return PortalCitasOut(
#         proxima_cita=proxima_cita,
#         otras_citas=otras_citas,
#         total_citas=len(citas_validas),
#         tiene_citas=True,
#     )
#
#
# # =========================
# # ENDPOINT COMPATIBLE CON LISTADO SIMPLE
# # =========================
#
# class CitaAspiranteOut(BaseModel):
#     id: int
#     fecha_inicio: str
#     fecha_fin: str
#     duracion_minutos: int
#     tipo_agendamiento: str
#     realizada: bool
#     estado: str
#     link_meet: Optional[str] = None
#     url_reagendar: Optional[str] = None
#
#
# @router.get("/api/aspirantes/{aspirante_id}/citas", response_model=List[CitaAspiranteOut])
# def listar_citas_aspirante(aspirante_id: int):
#     citas: List[CitaAspiranteOut] = []
#
#     with get_connection_context() as conn:
#         with conn.cursor() as cur:
#             cur.execute(
#                 """
#                 SELECT
#                     a.id,
#                     a.fecha_inicio,
#                     a.fecha_fin,
#                     COALESCE(ae.nombre, 'programado') AS estado_nombre,
#                     at.nombre AS tipo_nombre,
#                     a.link_meet
#                 FROM agendamientos a
#                 INNER JOIN agendamientos_participantes ap
#                     ON ap.agendamiento_id = a.id
#                 LEFT JOIN agendamientos_estados ae
#                     ON ae.id = a.estado
#                 INNER JOIN agendamientos_tipo at
#                     ON at.id = a.tipo_agendamiento
#                 WHERE ap.participante_tipo_id = 1
#                   AND ap.participante_id = %s
#                   AND at.participante_tipo_id = 1
#                 ORDER BY a.fecha_inicio ASC
#                 """,
#                 (aspirante_id,)
#             )
#             rows = cur.fetchall()
#
#     for a_id, f_ini, f_fin, estado_nombre, tipo_nombre, link_meet in rows:
#         duracion_min = calcular_duracion_minutos(f_ini, f_fin)
#         realizada = (estado_nombre or "").strip().lower() == "cumplido"
#
#         citas.append(
#             CitaAspiranteOut(
#                 id=a_id,
#                 fecha_inicio=f_ini.isoformat() if f_ini else "",
#                 fecha_fin=f_fin.isoformat() if f_fin else "",
#                 duracion_minutos=duracion_min,
#                 tipo_agendamiento=tipo_nombre,
#                 realizada=realizada,
#                 estado=estado_nombre or "programado",
#                 link_meet=link_meet,
#                 url_reagendar=None,
#             )
#         )
#
#     return citas

# ----------------------------------------------------
# ----------------------------------------------------
# ----------------------------------------------------
# ---------------VERSION 1-----------------
# ----------------------------------------------------
# ----------------------------------------------------
# ----------------------------------------------------
# ----------------------------------------------------





# def generar_url_portal_para_aspirante(aspirante_id: int, origen="encuesta") -> str:
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         revocar_tokens_portal_activos(cur, aspirante_id)
#
#         token_data = crear_link_portal_token(
#             cur=cur,
#             aspirante_id=aspirante_id,
#             duracion_minutos=10080,
#             creado_por=None,
#             origen=origen
#         )
#
#         conn.commit()
#
#     return construir_url_portal(token_data["token"])


# from datetime import datetime, timedelta
# from typing import Optional
#
# import logging
# import secrets
#
# from fastapi import APIRouter, HTTPException, Depends, Query
# from pydantic import BaseModel, Field
#
# from DataBase import (
#     get_connection_context,
#     obtener_cuenta_por_subdominio,
#     guardar_mensaje_nuevo,
# )
# from enviar_msg_wp import enviar_mensaje_texto_simple
# from main_auth import obtener_usuario_actual
# from tenant import current_tenant
#
#
# logger = logging.getLogger("uvicorn.error")
# router = APIRouter()
#
#
# # =========================================================
# # CONFIG
# # =========================================================
#
# DURACION_TOKEN_PORTAL_MINUTOS = 10080  # 7 días
#
#
# # =========================================================
# # MODELOS
# # =========================================================
#
# class CrearLinkPortalIn(BaseModel):
#     aspirante_id: int
#     duracion_minutos: int = Field(default=DURACION_TOKEN_PORTAL_MINUTOS, ge=5, le=43200)
#     origen: str = Field(default="whatsapp", max_length=30)
#
#
# class LinkPortalOut(BaseModel):
#     token: str
#     url: str
#     expiracion: datetime
#
#
# class PortalValidateOut(BaseModel):
#     valid: bool
#     aspirante_id: int
#     nombre: str
#     estado_id: Optional[int] = None
#     estado_nombre: str
#     expiracion: datetime
#
#
# class PortalModuloFlags(BaseModel):
#     proceso: bool = True
#     diagnostico: bool = False
#     faq: bool = True
#     incorporacion: bool = False
#     citas: bool = False
#
#
# class PortalResumenOut(BaseModel):
#     aspirante_id: int
#     nombre: str
#     telefono: Optional[str] = None
#     whatsapp: Optional[str] = None
#     email: Optional[str] = None
#     usuario: Optional[str] = None
#     estado_id: Optional[int] = None
#     estado_nombre: str
#     mensaje_estado: str
#     tiempo_estimado: Optional[str] = None
#     encuesta_terminada: bool = False
#     modulos: PortalModuloFlags
#     expiracion_token: datetime
#
#
# class RevocarPortalOut(BaseModel):
#     ok: bool
#     message: str
#
#
# # =========================================================
# # HELPERS GENERALES
# # =========================================================
#
# # def generar_token_seguro(longitud_token: int = 24) -> str:
# #     return secrets.token_urlsafe(longitud_token)
#
# def generar_token_seguro(cur, longitud_token: int = 12) -> str:
#     while True:
#         token = secrets.token_urlsafe(9)[:longitud_token]
#         if not token_existe_activo(cur, token):
#             return token
#
# def token_existe_activo(cur, token: str) -> bool:
#     cur.execute("""
#         SELECT 1
#         FROM portal_access_tokens
#         WHERE token = %s
#           AND estado = 'activo'
#           AND expiracion > NOW()
#         LIMIT 1
#     """, (token,))
#     return cur.fetchone() is not None
#
#
# def obtener_tenant_key() -> str:
#     return current_tenant.get() or "test"
#
#
# def construir_url_portal(token: str) -> str:
#     tenant_key = obtener_tenant_key()
#     subdominio = tenant_key if tenant_key != "public" else "test"
#     return f"https://{subdominio}.talentum-manager.com/portal?access={token}"
#
#
# def mensaje_estado(estado_id: Optional[int]) -> str:
#     if estado_id == 1:
#         return "Tu registro fue recibido y está pendiente de revisión."
#     if estado_id == 2:
#         return "Tu perfil está en preselección."
#     if estado_id == 3:
#         return "Estamos evaluando tu perfil. Esta etapa suele tardar entre 7 y 10 días."
#     if estado_id == 4:
#         return "Tu proceso avanzó a entrevista."
#     if estado_id == 5:
#         return "Tu proceso avanzó a invitación. Aquí podrás revisar los siguientes pasos."
#     if estado_id == 6:
#         return "¡Bienvenido! Tu proceso ya fue aprobado y estás en etapa de incorporación."
#     if estado_id == 7:
#         return "Tu proceso finalizó. Gracias por tu interés en formar parte de la agencia."
#     return "Consulta aquí el estado actualizado de tu proceso."
#
#
# def tiempo_estimado_estado(estado_id: Optional[int]) -> Optional[str]:
#     if estado_id == 3:
#         return "7 a 10 días"
#     return None
#
#
# def construir_modulos(estado_id: Optional[int]) -> PortalModuloFlags:
#     modulos = PortalModuloFlags(
#         proceso=True,
#         diagnostico=False,
#         faq=True,
#         incorporacion=False,
#         citas=False,
#     )
#
#     if estado_id in (3, 4, 5, 6):
#         modulos.diagnostico = True
#
#     if estado_id == 4:
#         modulos.citas = True
#
#     if estado_id in (5, 6):
#         modulos.incorporacion = True
#
#     return modulos
#
#
# # =========================================================
# # HELPERS BD
# # =========================================================
#
# def obtener_aspirante_basico(cur, aspirante_id: int):
#     cur.execute(
#         """
#         SELECT
#             id,
#             COALESCE(nickname, nombre_real, usuario, 'aspirante') AS nombre,
#             telefono
#         FROM aspirantes
#         WHERE id = %s
#         """,
#         (aspirante_id,)
#     )
#     return cur.fetchone()
#
#
# def revocar_tokens_portal_activos(cur, aspirante_id: int) -> int:
#     cur.execute(
#         """
#         UPDATE portal_access_tokens
#         SET estado = 'revocado'
#         WHERE aspirante_id = %s
#           AND estado = 'activo'
#           AND expiracion > now()
#         """,
#         (aspirante_id,)
#     )
#     return cur.rowcount or 0
#
#
# def crear_link_portal_token(
#     cur,
#     aspirante_id: int,
#     duracion_minutos: int,
#     creado_por: Optional[int] = None,
#     origen: str = "whatsapp",
#     longitud_token: int = 10,
# ) -> dict:
#     token = generar_token_seguro(longitud_token)
#     expiracion = datetime.now() + timedelta(minutes=duracion_minutos)
#
#     cur.execute(
#         """
#         INSERT INTO portal_access_tokens
#         (
#             token,
#             aspirante_id,
#             expiracion,
#             estado,
#             creado_en,
#             duracion_minutos,
#             creado_por,
#             origen
#         )
#         VALUES (%s, %s, %s, 'activo', now(), %s, %s, %s)
#         RETURNING id, token, expiracion
#         """,
#         (token, aspirante_id, expiracion, duracion_minutos, creado_por, origen)
#     )
#     row = cur.fetchone()
#
#     return {
#         "id": row[0],
#         "token": row[1],
#         "expiracion": row[2],
#     }
#
#
# def generar_link_portal_interno(
#     aspirante_id: int,
#     duracion_minutos: int,
#     origen: str,
#     creado_por: Optional[int],
# ) -> dict:
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         aspirante = obtener_aspirante_basico(cur, aspirante_id)
#         if not aspirante:
#             raise HTTPException(status_code=404, detail="El aspirante no existe.")
#
#         _, nombre_aspirante, telefono = aspirante
#
#         revocar_tokens_portal_activos(cur, aspirante_id)
#
#         token_data = crear_link_portal_token(
#             cur=cur,
#             aspirante_id=aspirante_id,
#             duracion_minutos=duracion_minutos,
#             creado_por=creado_por,
#             origen=origen,
#             longitud_token=24,
#         )
#
#         conn.commit()
#
#     token = token_data["token"]
#     expiracion = token_data["expiracion"]
#     url = construir_url_portal(token)
#
#     return {
#         "nombre": nombre_aspirante,
#         "telefono": telefono,
#         "token": token,
#         "url": url,
#         "expiracion": expiracion,
#     }
#
#
# def actualizar_ultimo_uso_token(token: str) -> None:
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#         cur.execute(
#             """
#             UPDATE portal_access_tokens
#             SET ultimo_uso_en = now()
#             WHERE token = %s
#             """,
#             (token,)
#         )
#         conn.commit()
#
#
# def resolver_aspirante_por_token_portal(token: str) -> Optional[dict]:
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#         cur.execute(
#             """
#             SELECT
#                 pat.id AS token_id,
#                 pat.token,
#                 pat.aspirante_id,
#                 pat.expiracion,
#                 pat.estado AS token_estado,
#
#                 a.id,
#                 a.usuario,
#                 a.nickname,
#                 a.nombre_real,
#                 a.email,
#                 a.telefono,
#                 a.whatsapp,
#                 a.estado_id,
#                 COALESCE(a.encuesta_terminada, false) AS encuesta_terminada,
#
#                 COALESCE(ae.nombre, 'Proceso') AS estado_nombre
#             FROM portal_access_tokens pat
#             JOIN aspirantes a
#               ON a.id = pat.aspirante_id
#             LEFT JOIN aspirantes_estados ae
#               ON ae.id = a.estado_id
#             WHERE pat.token = %s
#               AND pat.estado = 'activo'
#               AND pat.expiracion > now()
#             LIMIT 1
#             """,
#             (token,)
#         )
#         row = cur.fetchone()
#
#         if not row:
#             return None
#
#         nombre = row[7] or row[8] or row[6] or f"Aspirante {row[5]}"
#
#         return {
#             "token_id": row[0],
#             "token": row[1],
#             "aspirante_id": row[2],
#             "expiracion": row[3],
#             "token_estado": row[4],
#             "id": row[5],
#             "usuario": row[6],
#             "nickname": row[7],
#             "nombre_real": row[8],
#             "email": row[9],
#             "telefono": row[10],
#             "whatsapp": row[11],
#             "estado_id": row[12],
#             "encuesta_terminada": row[13],
#             "estado_nombre": row[14],
#             "nombre": nombre,
#         }
#
#
# def resolver_token_vigente_o_error(token: str) -> dict:
#     info = resolver_aspirante_por_token_portal(token)
#     if not info:
#         raise HTTPException(
#             status_code=404,
#             detail="El enlace del portal no es válido o ya expiró.",
#         )
#     return info
#
#
# def enviar_whatsapp_link_portal(
#     telefono: str,
#     nombre_aspirante: str,
#     url: str,
#     expiracion: datetime,
# ) -> None:
#     tenant_key = obtener_tenant_key()
#     cuenta = obtener_cuenta_por_subdominio(tenant_key)
#
#     if not cuenta:
#         raise HTTPException(
#             status_code=500,
#             detail=f"No hay credenciales WABA para '{tenant_key}'.",
#         )
#
#     business_name = cuenta.get("business_name", "la agencia")
#
#     mensaje = (
#         f"Hola {nombre_aspirante or 'aspirante'} 👋\n\n"
#         f"Tu proceso con *{business_name}* continúa avanzando.\n\n"
#         "Desde este portal podrás revisar tu estado, conocer las etapas del proceso "
#         "y acceder a la información disponible para ti.\n\n"
#         f"🔗 {url}\n\n"
#         f"🕒 Este enlace estará disponible hasta: {expiracion.strftime('%Y-%m-%d %H:%M')}.\n\n"
#         "Este enlace se actualizará conforme avance tu proceso."
#     )
#
#     try:
#         codigo, respuesta = enviar_mensaje_texto_simple(
#             token=cuenta["access_token"],
#             numero_id=cuenta["phone_number_id"],
#             telefono_destino=telefono,
#             texto=mensaje,
#         )
#
#         message_id_meta = None
#         if isinstance(respuesta, dict) and respuesta.get("messages"):
#             try:
#                 message_id_meta = respuesta["messages"][0].get("id")
#             except Exception:
#                 message_id_meta = None
#
#         guardar_mensaje_nuevo(
#             telefono=telefono,
#             contenido=mensaje,
#             direccion="enviado",
#             tipo="text",
#             message_id_meta=message_id_meta,
#             estado="sent" if codigo and codigo < 300 else "error",
#         )
#
#     except Exception as e:
#         logger.exception("❌ Error enviando link de portal al teléfono %s: %s", telefono, e)
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error enviando link de portal: {str(e)}",
#         )
#
#
# # =========================================================
# # ENDPOINTS INTERNOS
# # =========================================================
#
# @router.post("/api/portal/aspirantes/crear-link", response_model=LinkPortalOut)
# def crear_link_portal_aspirante(
#     data: CrearLinkPortalIn,
#     usuario_actual: dict = Depends(obtener_usuario_actual),
# ):
#     creado_por = usuario_actual.get("id") if isinstance(usuario_actual, dict) else None
#
#     link_data = generar_link_portal_interno(
#         aspirante_id=data.aspirante_id,
#         duracion_minutos=data.duracion_minutos,
#         origen=data.origen,
#         creado_por=creado_por,
#     )
#
#     return LinkPortalOut(
#         token=link_data["token"],
#         url=link_data["url"],
#         expiracion=link_data["expiracion"],
#     )
#
#
# @router.post("/api/portal/aspirantes/enviar", response_model=LinkPortalOut)
# def enviar_link_portal_aspirante(
#     data: CrearLinkPortalIn,
#     usuario_actual: dict = Depends(obtener_usuario_actual),
# ):
#     creado_por = usuario_actual.get("id") if isinstance(usuario_actual, dict) else None
#
#     link_data = generar_link_portal_interno(
#         aspirante_id=data.aspirante_id,
#         duracion_minutos=data.duracion_minutos,
#         origen=data.origen,
#         creado_por=creado_por,
#     )
#
#     if not link_data["telefono"]:
#         raise HTTPException(
#             status_code=400,
#             detail="El aspirante no tiene teléfono registrado.",
#         )
#
#     enviar_whatsapp_link_portal(
#         telefono=link_data["telefono"],
#         nombre_aspirante=link_data["nombre"],
#         url=link_data["url"],
#         expiracion=link_data["expiracion"],
#     )
#
#     return LinkPortalOut(
#         token=link_data["token"],
#         url=link_data["url"],
#         expiracion=link_data["expiracion"],
#     )
#
#
# @router.post("/api/portal/aspirantes/{aspirante_id}/revocar", response_model=RevocarPortalOut)
# def revocar_link_portal_aspirante(
#     aspirante_id: int,
#     usuario_actual: dict = Depends(obtener_usuario_actual),
# ):
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         aspirante = obtener_aspirante_basico(cur, aspirante_id)
#         if not aspirante:
#             raise HTTPException(status_code=404, detail="El aspirante no existe.")
#
#         total = revocar_tokens_portal_activos(cur, aspirante_id)
#         conn.commit()
#
#     return RevocarPortalOut(
#         ok=True,
#         message=f"Se revocaron {total} token(s) activos del portal.",
#     )
#
#
# # =========================================================
# # ENDPOINTS PÚBLICOS DEL PORTAL
# # =========================================================
#
# @router.get("/api/portal/aspirantes/validar", response_model=PortalValidateOut)
# def validar_token_portal_aspirante(token: str = Query(..., min_length=10)):
#     info = resolver_token_vigente_o_error(token)
#     actualizar_ultimo_uso_token(token)
#
#     return PortalValidateOut(
#         valid=True,
#         aspirante_id=info["aspirante_id"],
#         nombre=info["nombre"],
#         estado_id=info["estado_id"],
#         estado_nombre=info["estado_nombre"],
#         expiracion=info["expiracion"],
#     )
#
#
# @router.get("/api/portal/aspirantes/resumen", response_model=PortalResumenOut)
# def obtener_resumen_portal_aspirante(token: str = Query(..., min_length=10)):
#     info = resolver_token_vigente_o_error(token)
#     actualizar_ultimo_uso_token(token)
#
#     return PortalResumenOut(
#         aspirante_id=info["aspirante_id"],
#         nombre=info["nombre"],
#         telefono=info["telefono"],
#         whatsapp=info["whatsapp"],
#         email=info["email"],
#         usuario=info["usuario"],
#         estado_id=info["estado_id"],
#         estado_nombre=info["estado_nombre"],
#         mensaje_estado=mensaje_estado(info["estado_id"]),
#         tiempo_estimado=tiempo_estimado_estado(info["estado_id"]),
#         encuesta_terminada=info["encuesta_terminada"],
#         modulos=construir_modulos(info["estado_id"]),
#         expiracion_token=info["expiracion"],
#     )
#
#
# # =========================================================
# # FUNCION PARA GENERA RURL
# # =========================================================
# def generar_url_portal_para_aspirante(aspirante_id: int, origen="encuesta") -> str:
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         revocar_tokens_portal_activos(cur, aspirante_id)
#
#         token_data = crear_link_portal_token(
#             cur=cur,
#             aspirante_id=aspirante_id,
#             duracion_minutos=10080,
#             creado_por=None,
#             origen=origen
#         )
#
#         conn.commit()
#
#     return construir_url_portal(token_data["token"])

# from datetime import datetime, timedelta
# from typing import Optional
#
# import secrets
# import logging
#
# from fastapi import APIRouter, HTTPException, Depends, Query
# from pydantic import BaseModel, Field
#
# from DataBase import get_connection_context, obtener_cuenta_por_subdominio, guardar_mensaje_nuevo
# from enviar_msg_wp import enviar_mensaje_texto_simple
# from main_auth import obtener_usuario_actual
# from tenant import current_tenant
#
# logger = logging.getLogger("uvicorn.error")
# router = APIRouter()
#
#
# # =========================================================
# # CONFIG
# # =========================================================
#
# DURACION_TOKEN_PORTAL_MINUTOS = 10080  # 7 días
#
#
# # =========================================================
# # MODELOS PYDANTIC
# # =========================================================
#
# class CrearLinkPortalIn(BaseModel):
#     aspirante_id: int
#     duracion_minutos: int = Field(default=DURACION_TOKEN_PORTAL_MINUTOS, ge=5, le=43200)
#     origen: str = Field(default="whatsapp", max_length=30)
#
#
# class LinkPortalOut(BaseModel):
#     token: str
#     url: str
#     expiracion: datetime
#
#
# class PortalValidateOut(BaseModel):
#     valid: bool
#     aspirante_id: int
#     nombre: str
#     estado_id: Optional[int] = None
#     estado_nombre: str
#     expiracion: datetime
#
#
# class PortalModuloFlags(BaseModel):
#     proceso: bool = True
#     diagnostico: bool = False
#     faq: bool = True
#     incorporacion: bool = False
#
#
# class PortalResumenOut(BaseModel):
#     aspirante_id: int
#     nombre: str
#     telefono: Optional[str] = None
#     whatsapp: Optional[str] = None
#     email: Optional[str] = None
#     usuario: Optional[str] = None
#     estado_id: Optional[int] = None
#     estado_nombre: str
#     mensaje_estado: str
#     tiempo_estimado: Optional[str] = None
#     encuesta_terminada: bool = False
#     modulos: PortalModuloFlags
#     expiracion_token: datetime
#
#
# class RevocarPortalOut(BaseModel):
#     ok: bool
#     message: str
#
#
# # =========================================================
# # HELPERS
# # =========================================================
#
# def generar_token_seguro(longitud_token: int = 24) -> str:
#     """
#     Genera token URL-safe.
#     """
#     return secrets.token_urlsafe(longitud_token)
#
#
# def construir_url_portal(token: str) -> str:
#     """
#     Construye la URL del portal usando el tenant actual.
#     """
#     tenant_key = current_tenant.get() or "test"
#     subdominio = tenant_key if tenant_key != "public" else "test"
#     return f"https://{subdominio}.talentum-manager.com/portal?access={token}"
#
#
# def mensaje_estado(estado_id: Optional[int]) -> str:
#     """
#     Estados actuales:
#     1 Nuevo
#     2 Preselección
#     3 Evaluación
#     4 Entrevista
#     5 Invitación
#     6 Incorporado
#     7 Rechazado
#     """
#     if estado_id == 1:
#         return "Tu registro fue recibido y está pendiente de revisión."
#     if estado_id == 2:
#         return "Tu perfil está en preselección."
#     if estado_id == 3:
#         return "Estamos evaluando tu perfil. Esta etapa suele tardar entre 7 y 10 días."
#     if estado_id == 4:
#         return "Tu proceso avanzó a entrevista."
#     if estado_id == 5:
#         return "Tu proceso avanzó a invitación. Aquí podrás revisar los siguientes pasos."
#     if estado_id == 6:
#         return "¡Bienvenido! Tu proceso ya fue aprobado y estás en etapa de incorporación."
#     if estado_id == 7:
#         return "Tu proceso finalizó. Gracias por tu interés en formar parte de la agencia."
#     return "Consulta aquí el estado actualizado de tu proceso."
#
#
# def tiempo_estimado_estado(estado_id: Optional[int]) -> Optional[str]:
#     if estado_id == 3:
#         return "7 a 10 días"
#     return None
#
#
# def construir_modulos(estado_id: Optional[int]) -> PortalModuloFlags:
#     """
#     No consulta diagnóstico ni citas.
#     Solo define visibilidad mínima del menú del portal.
#     """
#     modulos = PortalModuloFlags(
#         proceso=True,
#         diagnostico=False,
#         faq=True,
#         incorporacion=False
#     )
#
#     # El módulo existe desde evaluación en adelante,
#     # aunque el contenido real lo maneje otro endpoint/módulo.
#     if estado_id in (3, 4, 5, 6):
#         modulos.diagnostico = True
#
#     if estado_id in (5, 6):
#         modulos.incorporacion = True
#
#     return modulos
#
#
# def crear_link_portal_token(
#     cur,
#     aspirante_id: int,
#     duracion_minutos: int,
#     creado_por: Optional[int] = None,
#     origen: str = "whatsapp",
#     horas_expiracion: Optional[int] = None,
#     longitud_token: int = 24
# ) -> dict:
#     """
#     Crea el token del portal.
#     Si horas_expiracion viene informado, prevalece sobre duracion_minutos.
#     """
#     token = generar_token_seguro(longitud_token)
#
#     if horas_expiracion is not None:
#         expiracion = datetime.now() + timedelta(hours=horas_expiracion)
#     else:
#         expiracion = datetime.now() + timedelta(minutes=duracion_minutos)
#
#     cur.execute(
#         """
#         INSERT INTO portal_access_tokens
#         (
#             token,
#             aspirante_id,
#             expiracion,
#             estado,
#             creado_en,
#             duracion_minutos,
#             creado_por,
#             origen
#         )
#         VALUES (%s, %s, %s, 'activo', now(), %s, %s, %s)
#         RETURNING id, token, expiracion
#         """,
#         (token, aspirante_id, expiracion, duracion_minutos, creado_por, origen)
#     )
#     row = cur.fetchone()
#
#     return {
#         "id": row[0],
#         "token": row[1],
#         "expiracion": row[2],
#     }
#
#
# def revocar_tokens_portal_activos(cur, aspirante_id: int) -> int:
#     """
#     Revoca tokens activos vigentes del aspirante.
#     """
#     cur.execute(
#         """
#         UPDATE portal_access_tokens
#         SET estado = 'revocado'
#         WHERE aspirante_id = %s
#           AND estado = 'activo'
#           AND expiracion > now()
#         """,
#         (aspirante_id,)
#     )
#     return cur.rowcount or 0
#
#
# def actualizar_ultimo_uso_token(token: str) -> None:
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#         cur.execute(
#             """
#             UPDATE portal_access_tokens
#             SET ultimo_uso_en = now()
#             WHERE token = %s
#             """,
#             (token,)
#         )
#         conn.commit()
#
#
# def resolver_aspirante_por_token_portal(token: str) -> Optional[dict]:
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#         cur.execute(
#             """
#             SELECT
#                 pat.id AS token_id,
#                 pat.token,
#                 pat.aspirante_id,
#                 pat.expiracion,
#                 pat.estado AS token_estado,
#
#                 a.id,
#                 a.usuario,
#                 a.nickname,
#                 a.nombre_real,
#                 a.email,
#                 a.telefono,
#                 a.whatsapp,
#                 a.estado_id,
#                 COALESCE(a.encuesta_terminada, false) AS encuesta_terminada,
#
#                 COALESCE(ae.nombre, 'Proceso') AS estado_nombre
#             FROM portal_access_tokens pat
#             JOIN aspirantes a
#               ON a.id = pat.aspirante_id
#             LEFT JOIN aspirantes_estados ae
#               ON ae.id = a.estado_id
#             WHERE pat.token = %s
#               AND pat.estado = 'activo'
#               AND pat.expiracion > now()
#             LIMIT 1
#             """,
#             (token,)
#         )
#         row = cur.fetchone()
#
#         if not row:
#             return None
#
#         nombre = row[7] or row[8] or row[6] or f"Aspirante {row[5]}"
#
#         return {
#             "token_id": row[0],
#             "token": row[1],
#             "aspirante_id": row[2],
#             "expiracion": row[3],
#             "token_estado": row[4],
#
#             "id": row[5],
#             "usuario": row[6],
#             "nickname": row[7],
#             "nombre_real": row[8],
#             "email": row[9],
#             "telefono": row[10],
#             "whatsapp": row[11],
#             "estado_id": row[12],
#             "encuesta_terminada": row[13],
#             "estado_nombre": row[14],
#             "nombre": nombre,
#         }
#
#
# def resolver_token_vigente_o_error(token: str) -> dict:
#     info = resolver_aspirante_por_token_portal(token)
#     if not info:
#         raise HTTPException(
#             status_code=404,
#             detail="El enlace del portal no es válido o ya expiró."
#         )
#     return info
#
#
# # =========================================================
# # ENDPOINTS INTERNOS
# # =========================================================
#
# @router.post("/api/portal/aspirantes/crear-link", response_model=LinkPortalOut)
# def crear_link_portal_aspirante(
#     data: CrearLinkPortalIn,
#     usuario_actual: dict = Depends(obtener_usuario_actual),
# ):
#     """
#     Crea un link nuevo del portal para el aspirante.
#     Regla simple:
#     - revoca tokens activos anteriores
#     - genera uno nuevo
#     """
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         # 1️⃣ Obtener datos del aspirante
#         cur.execute(
#             """
#             SELECT id
#             FROM aspirantes
#             WHERE id = %s
#             """,
#             (data.aspirante_id,)
#         )
#         row = cur.fetchone()
#
#         if not row:
#             raise HTTPException(status_code=404, detail="El aspirante no existe.")
#
#         # 2️⃣ Revocar tokens anteriores
#         revocar_tokens_portal_activos(cur, data.aspirante_id)
#
#         # 3️⃣ Crear token de portal
#         creado_por = usuario_actual.get("id") if isinstance(usuario_actual, dict) else None
#
#         token_data = crear_link_portal_token(
#             cur=cur,
#             aspirante_id=data.aspirante_id,
#             duracion_minutos=data.duracion_minutos,
#             creado_por=creado_por,
#             origen=data.origen,
#             horas_expiracion=None,
#             longitud_token=24
#         )
#
#         token = token_data["token"]
#         expiracion = token_data["expiracion"]
#
#         conn.commit()
#
#     # 4️⃣ Construir URL del portal
#     url = construir_url_portal(token)
#
#     # 5️⃣ Respuesta API
#     return LinkPortalOut(
#         token=token,
#         url=url,
#         expiracion=expiracion,
#     )
#
#
# @router.post("/api/portal/aspirantes/enviar", response_model=LinkPortalOut)
# def enviar_link_portal_aspirante(
#     data: CrearLinkPortalIn,
#     usuario_actual: dict = Depends(obtener_usuario_actual),
# ):
#     """
#     Envía un link del portal al aspirante por WhatsApp.
#     Siempre intenta mensaje simple.
#     Si Meta rechaza por ventana 24h, el webhook maneja el flujo de reenvío.
#     """
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         # 1️⃣ Obtener datos del aspirante
#         cur.execute(
#             """
#             SELECT
#                 COALESCE(nickname, nombre_real, usuario) AS nombre,
#                 telefono
#             FROM aspirantes
#             WHERE id = %s
#             """,
#             (data.aspirante_id,)
#         )
#         row = cur.fetchone()
#
#         if not row:
#             raise HTTPException(status_code=404, detail="El aspirante no existe.")
#
#         nombre_aspirante, telefono = row
#
#         if not telefono:
#             raise HTTPException(status_code=400, detail="El aspirante no tiene teléfono registrado.")
#
#         # 2️⃣ Revocar tokens anteriores
#         revocar_tokens_portal_activos(cur, data.aspirante_id)
#
#         # 3️⃣ Crear token de portal
#         creado_por = usuario_actual.get("id") if isinstance(usuario_actual, dict) else None
#
#         token_data = crear_link_portal_token(
#             cur=cur,
#             aspirante_id=data.aspirante_id,
#             duracion_minutos=data.duracion_minutos,
#             creado_por=creado_por,
#             origen=data.origen,
#             horas_expiracion=None,
#             longitud_token=24
#         )
#
#         token = token_data["token"]
#         expiracion = token_data["expiracion"]
#
#         conn.commit()
#
#     # 4️⃣ Construir URL del portal
#     url = construir_url_portal(token)
#
#     # 5️⃣ Obtener credenciales WABA
#     tenant_key = current_tenant.get() or "test"
#     cuenta = obtener_cuenta_por_subdominio(tenant_key)
#     if not cuenta:
#         raise HTTPException(
#             status_code=500,
#             detail=f"No hay credenciales WABA para '{tenant_key}'."
#         )
#
#     business_name = cuenta.get("business_name", "la agencia")
#
#     # 6️⃣ Construir mensaje simple
#     mensaje = (
#         f"Hola {nombre_aspirante or 'aspirante'} 👋\n\n"
#         f"Tu proceso con *{business_name}* continúa avanzando.\n\n"
#         "Desde este portal podrás revisar tu estado, conocer las etapas del proceso "
#         "y acceder a la información disponible para ti.\n\n"
#         f"🔗 {url}\n\n"
#         f"🕒 Este enlace estará disponible hasta: {expiracion.strftime('%Y-%m-%d %H:%M')}.\n\n"
#         "Este enlace se actualizará conforme avance tu proceso."
#     )
#
#     # 7️⃣ Enviar WhatsApp siempre como mensaje simple
#     try:
#         codigo, respuesta = enviar_mensaje_texto_simple(
#             token=cuenta["access_token"],
#             numero_id=cuenta["phone_number_id"],
#             telefono_destino=telefono,
#             texto=mensaje
#         )
#
#         message_id_meta = None
#         if isinstance(respuesta, dict) and respuesta.get("messages"):
#             try:
#                 message_id_meta = respuesta["messages"][0].get("id")
#             except Exception:
#                 message_id_meta = None
#
#         guardar_mensaje_nuevo(
#             telefono=telefono,
#             contenido=mensaje,
#             direccion="enviado",
#             tipo="text",
#             message_id_meta=message_id_meta,
#             estado="sent" if codigo and codigo < 300 else "error"
#         )
#
#     except Exception as e:
#         logger.exception(
#             "❌ Error enviando link de portal (aspirante_id=%s): %s",
#             data.aspirante_id, e
#         )
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error enviando link de portal: {str(e)}"
#         )
#
#     # 8️⃣ Respuesta API
#     return LinkPortalOut(
#         token=token,
#         url=url,
#         expiracion=expiracion,
#     )
#
#
# @router.post("/api/portal/aspirantes/{aspirante_id}/revocar", response_model=RevocarPortalOut)
# def revocar_link_portal_aspirante(
#     aspirante_id: int,
#     usuario_actual: dict = Depends(obtener_usuario_actual),
# ):
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         cur.execute(
#             """
#             SELECT id
#             FROM aspirantes
#             WHERE id = %s
#             """,
#             (aspirante_id,)
#         )
#         row = cur.fetchone()
#
#         if not row:
#             raise HTTPException(status_code=404, detail="El aspirante no existe.")
#
#         total = revocar_tokens_portal_activos(cur, aspirante_id)
#         conn.commit()
#
#     return RevocarPortalOut(
#         ok=True,
#         message=f"Se revocaron {total} token(s) activos del portal."
#     )
#
#
# # =========================================================
# # ENDPOINTS PÚBLICOS DEL PORTAL
# # =========================================================
#
# @router.get("/api/portal/aspirantes/validar", response_model=PortalValidateOut)
# def validar_token_portal_aspirante(token: str = Query(..., min_length=10)):
#     info = resolver_token_vigente_o_error(token)
#     actualizar_ultimo_uso_token(token)
#
#     return PortalValidateOut(
#         valid=True,
#         aspirante_id=info["aspirante_id"],
#         nombre=info["nombre"],
#         estado_id=info["estado_id"],
#         estado_nombre=info["estado_nombre"],
#         expiracion=info["expiracion"],
#     )
#
#
# @router.get("/api/portal/aspirantes/resumen", response_model=PortalResumenOut)
# def obtener_resumen_portal_aspirante(token: str = Query(..., min_length=10)):
#     info = resolver_token_vigente_o_error(token)
#     actualizar_ultimo_uso_token(token)
#
#     modulos = construir_modulos(info["estado_id"])
#
#     return PortalResumenOut(
#         aspirante_id=info["aspirante_id"],
#         nombre=info["nombre"],
#         telefono=info["telefono"],
#         whatsapp=info["whatsapp"],
#         email=info["email"],
#         usuario=info["usuario"],
#         estado_id=info["estado_id"],
#         estado_nombre=info["estado_nombre"],
#         mensaje_estado=mensaje_estado(info["estado_id"]),
#         tiempo_estimado=tiempo_estimado_estado(info["estado_id"]),
#         encuesta_terminada=info["encuesta_terminada"],
#         modulos=modulos,
#         expiracion_token=info["expiracion"],
#     )