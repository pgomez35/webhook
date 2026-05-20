import os
import traceback
import logging
import secrets
import string
import requests

from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Literal
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, AnyUrl
from psycopg2.extras import RealDictCursor

from DataBase import get_connection_context, obtener_cuenta_por_subdominio, \
    obtener_participantes_por_tipo_db, guardar_mensaje_nuevo
from enviar_msg_wp import enviar_mensaje_texto_simple
from main_configuracion import get_config
from utils_aspirantes import validar_link_tiktok
from schemas import *
from main_auth import obtener_usuario_actual

# Configurar logger
from tenant import current_tenant, current_business_name


logger = logging.getLogger(__name__)

router = APIRouter()   # ← ESTE ES EL ROUTER QUE VAS A IMPORTAR EN main.py

# participante_tipo.id (FK agendamientos_participantes.participante_tipo_id)
PARTICIPANTE_TIPO_ASPIRANTE_ID = 1
PARTICIPANTE_TIPO_CREADOR_ID = 2
PARTICIPANTE_TIPO_ADMINISTRADOR_ID = 3

_PARTICIPANTE_TIPO_STR_A_ID = {
    "aspirante": PARTICIPANTE_TIPO_ASPIRANTE_ID,
    "creador": PARTICIPANTE_TIPO_CREADOR_ID,
    "administrador": PARTICIPANTE_TIPO_ADMINISTRADOR_ID,
    "usuario": PARTICIPANTE_TIPO_ADMINISTRADOR_ID,  # alias legacy (schemas / lecturas antiguas)
}

_PARTICIPANTE_TIPO_ID_A_STR: Dict[int, str] = {
    PARTICIPANTE_TIPO_ASPIRANTE_ID: "aspirante",
    PARTICIPANTE_TIPO_CREADOR_ID: "creador",
    PARTICIPANTE_TIPO_ADMINISTRADOR_ID: "administrador",
}

# agendamientos_medio.id (semillas estándar)
MEDIO_REUNION_GOOGLE_MEET = 1
MEDIO_REUNION_TIKTOK_LIVE = 2


def _fetch_medio_reunion_id_por_tipo(cur, tipo_agendamiento_id: Optional[int]) -> Optional[int]:
    if tipo_agendamiento_id is None:
        return None
    cur.execute(
        "SELECT medio_reunion_id FROM agendamientos_tipo WHERE id = %s",
        (tipo_agendamiento_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return row[0]


def _resolver_medio_reunion_id(
    cur, tipo_agendamiento_id: Optional[int], explicit: Optional[int]
) -> Optional[int]:
    if explicit is not None:
        return explicit
    return _fetch_medio_reunion_id_por_tipo(cur, tipo_agendamiento_id)


def _resolver_participante_tipo_id(cur, evento: EventoIn) -> Optional[int]:
    if evento.participante_tipo:
        return _PARTICIPANTE_TIPO_STR_A_ID.get(evento.participante_tipo)
    tid = evento.tipo_agendamiento
    if tid is None:
        return PARTICIPANTE_TIPO_ASPIRANTE_ID
    cur.execute(
        "SELECT participante_tipo_id FROM agendamientos_tipo WHERE id = %s",
        (tid,),
    )
    row = cur.fetchone()
    if row and row[0] is not None:
        return int(row[0])
    return PARTICIPANTE_TIPO_ASPIRANTE_ID


def _cargar_participantes_por_tipo_pid(cur, participante_ids: List[int], tipo_pid: int) -> List[dict]:
    if not participante_ids:
        return []
    if tipo_pid == PARTICIPANTE_TIPO_ASPIRANTE_ID:
        cur.execute(
            """
            SELECT
                id,
                COALESCE(NULLIF(nombre_real, ''), nickname, usuario, telefono) AS nombre,
                nickname
            FROM aspirantes
            WHERE id = ANY(%s)
            """,
            (participante_ids,),
        )
    elif tipo_pid == PARTICIPANTE_TIPO_CREADOR_ID:
        cur.execute(
            """
            SELECT
                id,
                COALESCE(NULLIF(nombre, ''), usuario_tiktok, telefono) AS nombre,
                usuario_tiktok AS nickname
            FROM creadores
            WHERE id = ANY(%s)
            """,
            (participante_ids,),
        )
    elif tipo_pid == PARTICIPANTE_TIPO_ADMINISTRADOR_ID:
        cur.execute(
            """
            SELECT
                id,
                COALESCE(NULLIF(nombre_completo, ''), username, email, telefono) AS nombre,
                NULL AS nickname
            FROM administradores
            WHERE id = ANY(%s)
            """,
            (participante_ids,),
        )
    else:
        return []
    return [{"id": r[0], "nombre": r[1], "nickname": r[2]} for r in cur.fetchall()]


# router_agendamientos_aspirante = APIRouter()

class AgendamientoAspiranteIn(BaseModel):
    aspirante_id: int                     # 👈 directo
    responsable_id: Optional[int] = None
    titulo: str
    descripcion: Optional[str] = None
    inicio: datetime                    # hora local del aspirante
    fin: Optional[datetime] = None      # fallback si no hay duración
    duracion_minutos: Optional[int] = None
    tipo_agendamiento: str              # "LIVE" | "ENTREVISTA"
    timezone: Optional[str] = None      # "America/Santiago"


@router.get("/api/eventos/{evento_id}", response_model=EventoOut)
def obtener_evento(evento_id: str):
    """
    Obtiene un evento desde la BD interna.

    - Si evento_id es numérico: busca por agendamientos.id
    - Si es texto: busca por google_event_id
    """
    with get_connection_context() as conn:
        cur = conn.cursor()

        try:
            # ---------------------------------------------------------
            # 1️⃣ Un solo query: evento + participantes
            # ---------------------------------------------------------
            if evento_id.isdigit():
                sql = """
                    SELECT
                        a.id,
                        a.titulo,
                        a.descripcion,
                        a.fecha_inicio,
                        a.fecha_fin,
                        a.responsable_id,
                        a.estado_id,
                        a.link_meet,
                        a.google_event_id,
                        a.creado_en,
                        a.actualizado_en,
                        a.tipo_agendamiento,
                        a.medio_reunion_id,

                        ap.participante_id AS participante_id,

                        COALESCE(
                            NULLIF(asp.nombre_real, ''),
                            NULLIF(asp.nickname, ''),
                            NULLIF(asp.usuario, ''),
                            NULLIF(cre.nombre_real, ''),
                            NULLIF(cre.nickname, ''),
                            NULLIF(usr.nombre_completo, ''),
                            NULLIF(usr.username, ''),
                            asp.telefono,
                            cre.telefono,
                            usr.telefono
                        ) AS participante_nombre,

                        COALESCE(asp.nickname, cre.nickname, NULL) AS participante_nickname,

                        CASE ap.participante_tipo_id
                            WHEN 1 THEN 'aspirante'
                            WHEN 2 THEN 'creador'
                            WHEN 3 THEN 'usuario'
                            ELSE NULL
                        END AS participante_tipo

                    FROM agendamientos a
                    INNER JOIN agendamientos_participantes ap
                        ON ap.agendamiento_id = a.id
                    LEFT JOIN aspirantes asp
                        ON asp.id = ap.participante_id AND ap.participante_tipo_id = 1
                    LEFT JOIN aspirantes cre
                        ON cre.id = ap.participante_id AND ap.participante_tipo_id = 2
                    LEFT JOIN administradores usr
                        ON usr.id = ap.participante_id AND ap.participante_tipo_id = 3
                    WHERE a.id = %s
                    ORDER BY ap.id ASC
                """
                cur.execute(sql, (int(evento_id),))
            else:
                sql = """
                    SELECT
                        a.id,
                        a.titulo,
                        a.descripcion,
                        a.fecha_inicio,
                        a.fecha_fin,
                        a.responsable_id,
                        a.estado_id,
                        a.link_meet,
                        a.google_event_id,
                        a.creado_en,
                        a.actualizado_en,
                        a.tipo_agendamiento,
                        a.medio_reunion_id,

                        ap.participante_id AS participante_id,

                        COALESCE(
                            NULLIF(asp.nombre_real, ''),
                            NULLIF(asp.nickname, ''),
                            NULLIF(asp.usuario, ''),
                            NULLIF(cre.nombre_real, ''),
                            NULLIF(cre.nickname, ''),
                            NULLIF(usr.nombre_completo, ''),
                            NULLIF(usr.username, ''),
                            asp.telefono,
                            cre.telefono,
                            usr.telefono
                        ) AS participante_nombre,

                        COALESCE(asp.nickname, cre.nickname, NULL) AS participante_nickname,

                        CASE ap.participante_tipo_id
                            WHEN 1 THEN 'aspirante'
                            WHEN 2 THEN 'creador'
                            WHEN 3 THEN 'usuario'
                            ELSE NULL
                        END AS participante_tipo

                    FROM agendamientos a
                    INNER JOIN agendamientos_participantes ap
                        ON ap.agendamiento_id = a.id
                    LEFT JOIN aspirantes asp
                        ON asp.id = ap.participante_id AND ap.participante_tipo_id = 1
                    LEFT JOIN aspirantes cre
                        ON cre.id = ap.participante_id AND ap.participante_tipo_id = 2
                    LEFT JOIN administradores usr
                        ON usr.id = ap.participante_id AND ap.participante_tipo_id = 3
                    WHERE a.google_event_id = %s
                    ORDER BY ap.id ASC
                """
                cur.execute(sql, (evento_id,))

            rows = cur.fetchall()

            if not rows:
                raise HTTPException(status_code=404, detail="Evento no encontrado.")

            # ---------------------------------------------------------
            # 2️⃣ Datos del evento salen de la primera fila
            # ---------------------------------------------------------
            (
                ag_id,
                titulo,
                descripcion,
                fecha_inicio,
                fecha_fin,
                responsable_id,
                estado_id,
                link_meet,
                google_event_id,
                creado_en,
                actualizado_en,
                tipo_agendamiento,
                medio_reunion_id,
                _participante_id,
                _participante_nombre,
                _participante_nickname,
                _participante_tipo,
            ) = rows[0]

            # ---------------------------------------------------------
            # 3️⃣ Construir participantes desde las filas
            # ---------------------------------------------------------
            participantes_out = []
            participantes_ids = []
            participante_tipo = None
            vistos = set()

            for row in rows:
                participante_id = row[13]
                participante_nombre = row[14]
                participante_nickname = row[15]
                participante_tipo_row = row[16]

                if participante_id is None:
                    continue

                clave = f"{participante_tipo_row}:{participante_id}"
                if clave in vistos:
                    continue

                vistos.add(clave)
                participantes_ids.append(participante_id)
                participantes_out.append(
                    {
                        "id": participante_id,
                        "nombre": participante_nombre,
                        "nickname": participante_nickname
                    }
                )

                if participante_tipo is None:
                    participante_tipo = participante_tipo_row

            # ---------------------------------------------------------
            # 4️⃣ Origen
            # ---------------------------------------------------------
            origen = "google_calendar" if google_event_id else "interno"

            # ---------------------------------------------------------
            # 5️⃣ Respuesta
            # ---------------------------------------------------------
            return EventoOut(
                agendamiento_id=str(ag_id),
                titulo=titulo or "Sin título",
                descripcion=descripcion or "",
                inicio=fecha_inicio,
                fin=fecha_fin,
                participantes=participantes_out,
                participantes_ids=participantes_ids,
                participante_tipo=participante_tipo,
                link_meet=link_meet,
                responsable_id=responsable_id,
                origen=origen,
                tipo_agendamiento=tipo_agendamiento,
                google_event_id=google_event_id,
                medio_reunion_id=medio_reunion_id,
            )

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"❌ Error al obtener evento {evento_id}: {e}")
            logger.error(traceback.format_exc())
            raise HTTPException(
                status_code=500,
                detail="Error interno al obtener el evento."
            )

@router.get("/api/eventos", response_model=List[EventoOut])
def listar_eventos(
    time_min: Optional[datetime] = None,
    time_max: Optional[datetime] = None,
    max_results: Optional[int] = 100
):
    try:
        return obtener_eventos(
            time_min=time_min,
            time_max=time_max,
            max_results=max_results)
    except Exception as e:
        logger.error(f"❌ Error al obtener eventos: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/eventos/{evento_id}", response_model=EventoOut)
def editar_evento(evento_id: str, evento: EventoIn):
    with get_connection_context() as conn:
        cur = conn.cursor()
        try:
            # 1️⃣ Validación básica de fechas
            if evento.fin <= evento.inicio:
                raise HTTPException(
                    status_code=400,
                    detail="La fecha de fin debe ser posterior a la fecha de inicio."
                )

            if evento.participante_tipo is not None and evento.participante_tipo not in (
                "aspirante",
                "creador",
                "administrador",
                "usuario",
            ):
                raise HTTPException(
                    status_code=400,
                    detail="participante_tipo inválido. Use: aspirante, creador o administrador."
                )

            # 2️⃣ Buscar el agendamiento en BD
            if evento_id.isdigit():
                cur.execute(
                    """
                    SELECT id,
                           titulo,
                           descripcion,
                           fecha_inicio,
                           fecha_fin,
                           responsable_id,
                           estado,
                           link_meet,
                           google_event_id,
                           tipo_agendamiento,
                           medio_reunion_id
                    FROM agendamientos
                    WHERE id = %s
                    """,
                    (int(evento_id),)
                )
            else:
                cur.execute(
                    """
                    SELECT id,
                           titulo,
                           descripcion,
                           fecha_inicio,
                           fecha_fin,
                           responsable_id,
                           estado,
                           link_meet,
                           google_event_id,
                           tipo_agendamiento,
                           medio_reunion_id
                    FROM agendamientos
                    WHERE google_event_id = %s
                    """,
                    (evento_id,)
                )

            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Evento no encontrado.")

            (
                ag_id,
                _titulo_actual,
                _descripcion_actual,
                _inicio_actual,
                _fin_actual,
                responsable_id,
                estado,
                link_meet_actual,
                google_event_id,
                tipo_agendamiento_actual,
                medio_actual,
            ) = row

            medio_resuelto = _resolver_medio_reunion_id(
                cur, evento.tipo_agendamiento, evento.medio_reunion_id
            )
            if medio_resuelto is None and medio_actual is not None:
                medio_resuelto = medio_actual

            # 3️⃣ Determinar nuevo link_meet
            nuevo_link_meet = getattr(evento, "link_meet", None)
            if nuevo_link_meet is None:
                nuevo_link_meet = link_meet_actual

            # 4️⃣ TikTok LIVE según medio de reunión (primer participante = usuario TikTok en aspirantes)
            if medio_resuelto == MEDIO_REUNION_TIKTOK_LIVE:
                if not evento.participantes_ids:
                    raise HTTPException(
                        status_code=400,
                        detail="Se requiere al menos un participante para generar el enlace TikTok LIVE.",
                    )
                tik_uid = evento.participantes_ids[0]
                link_tiktok = obtener_link_live_por_creador(tik_uid)
                if link_tiktok:
                    nuevo_link_meet = link_tiktok
                else:
                    logger.warning(
                        "No se pudo generar link TikTok LIVE para participante_id=%s",
                        tik_uid,
                    )

            # 5️⃣ Actualizar el agendamiento en BD
            cur.execute(
                """
                UPDATE agendamientos
                SET fecha_inicio = %s,
                    fecha_fin = %s,
                    titulo = %s,
                    descripcion = %s,
                    link_meet = %s,
                    tipo_agendamiento = %s,
                    medio_reunion_id = %s,
                    actualizado_en = NOW()
                WHERE id = %s
                """,
                (
                    evento.inicio,
                    evento.fin,
                    evento.titulo,
                    evento.descripcion,
                    nuevo_link_meet,
                    evento.tipo_agendamiento,
                    medio_resuelto,
                    ag_id,
                )
            )

            # 6️⃣ Reemplazar participantes
            cur.execute(
                "DELETE FROM agendamientos_participantes WHERE agendamiento_id = %s",
                (ag_id,)
            )

            tipo_pid = _resolver_participante_tipo_id(cur, evento)
            if evento.participantes_ids and tipo_pid is None:
                raise HTTPException(
                    status_code=400,
                    detail="participante_tipo no válido o no se pudo resolver desde agendamientos_tipo.",
                )

            for participante_id in evento.participantes_ids:
                cur.execute(
                    """
                    INSERT INTO agendamientos_participantes (
                        agendamiento_id,
                        participante_tipo_id,
                        participante_id,
                        estado
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    (ag_id, tipo_pid, participante_id, "programado"),
                )

            participantes = _cargar_participantes_por_tipo_pid(
                cur, evento.participantes_ids, tipo_pid
            )

            conn.commit()

            # 8️⃣ Determinar ID público y origen
            public_id = google_event_id if google_event_id else str(ag_id)
            origen = "google_calendar" if google_event_id else "interno"

            pt_out = evento.participante_tipo or _PARTICIPANTE_TIPO_ID_A_STR.get(
                tipo_pid or 0
            )

            # 9️⃣ Respuesta final
            return EventoOut(
                agendamiento_id=str(ag_id),
                titulo=evento.titulo,
                descripcion=evento.descripcion,
                inicio=evento.inicio,
                fin=evento.fin,
                participantes_ids=evento.participantes_ids,
                participantes=participantes,
                participante_tipo=pt_out,
                link_meet=nuevo_link_meet,
                responsable_id=responsable_id,
                origen=origen,
                tipo_agendamiento=evento.tipo_agendamiento,
                google_event_id=google_event_id,
                medio_reunion_id=medio_resuelto,
            )

        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ Error al editar evento {evento_id}: {e}")
            logger.error(traceback.format_exc())
            raise HTTPException(
                status_code=500,
                detail="Error interno al editar el evento."
            )


@router.delete("/api/eventos/{evento_id}")
def eliminar_evento(evento_id: str):
    with get_connection_context() as conn:
        cur = conn.cursor()

        try:
            # 1️⃣ Determinar si el evento es interno o google_event_id
            if evento_id.isdigit():
                # Buscar por ID interno
                cur.execute("SELECT id FROM agendamientos WHERE id = %s", (int(evento_id),))
            else:
                # Buscar por google_event_id
                cur.execute("SELECT id FROM agendamientos WHERE google_event_id = %s", (evento_id,))

            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="El evento no existe.")

            ag_id = row[0]

            # 2️⃣ Eliminar agendamiento (borra también participantes por CASCADE)
            cur.execute("DELETE FROM agendamientos WHERE id = %s", (ag_id,))

            return {"ok": True, "mensaje": f"Evento {evento_id} eliminado correctamente"}

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"❌ Error al eliminar evento {evento_id}: {e}")
            logger.error(traceback.format_exc())
            raise HTTPException(status_code=500, detail="Error interno al eliminar evento.")


@router.post("/api/eventos", response_model=EventoOut)
def crear_evento(evento: EventoIn, usuario_actual: Any = Depends(obtener_usuario_actual)):
    if evento.fin <= evento.inicio:
        raise HTTPException(
            status_code=400,
            detail="La fecha de fin debe ser posterior a la fecha de inicio."
        )

    if evento.participante_tipo is not None and evento.participante_tipo not in (
        "aspirante",
        "creador",
        "administrador",
        "usuario",
    ):
        raise HTTPException(
            status_code=400,
            detail="participante_tipo inválido. Use: aspirante, creador o administrador."
        )

    google_meet_enabled_str = get_config("google_meet_enabled")
    google_meet_enabled = str(google_meet_enabled_str).lower() in ["true", "1", "t", "y", "yes"]
    debe_crear_meet = google_meet_enabled and evento.requiere_meet

    link_reunion = evento.link_meet
    google_event_id = None

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            medio_id = _resolver_medio_reunion_id(
                cur, evento.tipo_agendamiento, evento.medio_reunion_id
            )

    if medio_id == MEDIO_REUNION_GOOGLE_MEET and google_meet_enabled:
        try:
            google_event = crear_evento_google(
                resumen=evento.titulo,
                descripcion=evento.descripcion or "",
                fecha_inicio=evento.inicio,
                fecha_fin=evento.fin,
                requiere_meet=debe_crear_meet,
            )
            google_event_id = google_event.get("id")
            link_reunion = google_event.get("hangoutLink")
        except Exception as e:
            logger.error(f"⚠️ Error creando evento Google Calendar: {e}")
            logger.error(traceback.format_exc())
            google_event_id = None

    if medio_id == MEDIO_REUNION_TIKTOK_LIVE:
        if not evento.participantes_ids:
            raise HTTPException(
                status_code=400,
                detail="Se requiere al menos un participante (usuario TikTok) para generar el enlace LIVE.",
            )
        tik_uid = evento.participantes_ids[0]
        link_tiktok = obtener_link_live_por_creador(tik_uid)
        if link_tiktok:
            link_reunion = link_tiktok
        else:
            logger.warning(
                "No se pudo generar link TikTok LIVE para participante_id=%s",
                tik_uid,
            )

    with get_connection_context() as conn:
        try:
            cur = conn.cursor()
            medio_guardar = _resolver_medio_reunion_id(
                cur, evento.tipo_agendamiento, evento.medio_reunion_id
            )
            tipo_pid = _resolver_participante_tipo_id(cur, evento)
            if evento.participantes_ids and tipo_pid is None:
                raise HTTPException(
                    status_code=400,
                    detail="participante_tipo no válido o no se pudo resolver desde agendamientos_tipo.",
                )

            cur.execute(
                """
                INSERT INTO agendamientos (
                    titulo,
                    descripcion,
                    fecha_inicio,
                    fecha_fin,
                    tipo_agendamiento,
                    link_meet,
                    estado_id,
                    responsable_id,
                    google_event_id,
                    medio_reunion_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    evento.titulo,
                    evento.descripcion,
                    evento.inicio,
                    evento.fin,
                    evento.tipo_agendamiento,
                    link_reunion,
                    1,
                    usuario_actual["id"],
                    google_event_id,
                    medio_guardar,
                ),
            )

            agendamiento_id = cur.fetchone()[0]

            if evento.participantes_ids:
                for participante_id in evento.participantes_ids:
                    cur.execute(
                        """
                        INSERT INTO agendamientos_participantes (
                            agendamiento_id,
                            participante_tipo_id,
                            participante_id,
                            estado
                        )
                        VALUES (%s, %s, %s, %s)
                        """,
                        (agendamiento_id, tipo_pid, participante_id, "programado"),
                    )

            participantes = _cargar_participantes_por_tipo_pid(
                cur, evento.participantes_ids, tipo_pid
            )

            conn.commit()

            pt_out = evento.participante_tipo or _PARTICIPANTE_TIPO_ID_A_STR.get(
                tipo_pid or 0
            )

            return EventoOut(
                agendamiento_id=str(agendamiento_id),
                titulo=evento.titulo,
                descripcion=evento.descripcion,
                inicio=evento.inicio,
                fin=evento.fin,
                participantes_ids=evento.participantes_ids,
                participantes=participantes,
                participante_tipo=pt_out,
                link_meet=link_reunion,
                responsable_id=usuario_actual["id"],
                origen="interno",
                tipo_agendamiento=evento.tipo_agendamiento,
                google_event_id=google_event_id,
                medio_reunion_id=medio_guardar,
            )

        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ Error creando evento BD: {e}")
            logger.error(traceback.format_exc())
            raise HTTPException(
                status_code=500,
                detail="Error guardando el evento en la base de datos."
            )

# # === Listar todos los administradores ===
#     try:

@router.get("/api/participantes", tags=["Participantes"])
def listar_participantes(tipo: str):
    try:
        return obtener_participantes_por_tipo_db(tipo)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/agendamientos")
def listar_agendamientos():
    try:
        with get_connection_context() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Obtener agendamientos con nombre del responsable
            cur.execute("""
            SELECT 
                a.id, a.titulo, a.descripcion, a.fecha_inicio, a.fecha_fin,
                a.estado_id, a.link_meet,
                u.nombre_completo AS responsable
            FROM agendamientos a
            LEFT JOIN administradores u ON u.id = a.responsable_id
                ORDER BY a.fecha_inicio DESC;
            """)
            agendamientos = cur.fetchall()

            # Para cada agendamiento, obtener los participantes (nombre, nickname)
            for evento in agendamientos:
                cur.execute("""
                    SELECT
                        ap.participante_id AS id,
                        COALESCE(
                            COALESCE(NULLIF(asp.nombre_real, ''), asp.nickname),
                            COALESCE(NULLIF(cre.nombre_real, ''), cre.nickname),
                            COALESCE(NULLIF(adm.nombre_completo, ''), adm.username)
                        ) AS nombre,
                        COALESCE(asp.nickname, cre.nickname, NULL) AS nickname
                    FROM agendamientos_participantes ap
                    LEFT JOIN aspirantes asp
                        ON ap.participante_tipo_id = 1 AND asp.id = ap.participante_id
                    LEFT JOIN aspirantes cre
                        ON ap.participante_tipo_id = 2 AND cre.id = ap.participante_id
                    LEFT JOIN administradores adm
                        ON ap.participante_tipo_id = 3 AND adm.id = ap.participante_id
                    WHERE ap.agendamiento_id = %s
                """, (evento["id"],))
                participantes = cur.fetchall()
                evento["participantes"] = participantes

                # Opcional: convertir fechas a string ISO si FastAPI no lo hace automáticamente
                evento["fecha_inicio"] = evento["fecha_inicio"].isoformat() if isinstance(evento["fecha_inicio"], datetime) else evento["fecha_inicio"]
                evento["fecha_fin"] = evento["fecha_fin"].isoformat() if isinstance(evento["fecha_fin"], datetime) else evento["fecha_fin"]

            return agendamientos

    except Exception as e:
        logger.error(f"❌ Error consultando agendamientos: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Error consultando agendamientos")


def obtener_eventos(
    time_min: Optional[datetime] = None,
    time_max: Optional[datetime] = None,
    max_results: int = 100
) -> List[EventoOut]:
    """
    Obtiene eventos desde la base de datos usando:
      - agendamientos
      - agendamientos_participantes (participante_tipo_id + participante_id)
      - aspirantes / administradores
    """

    if time_min is None:
        time_min = datetime.utcnow() - timedelta(days=60)
    if time_max is None:
        time_max = datetime.utcnow() + timedelta(days=60)

    try:
        with get_connection_context() as conn:
            cur = conn.cursor()

            sql = """
            SELECT
                a.id AS ag_id,
                a.titulo,
                a.descripcion,
                a.fecha_inicio,
                a.fecha_fin,
                a.responsable_id,
                a.estado_id,
                a.link_meet,
                a.tipo_agendamiento,
                a.google_event_id,
                a.timezone,
                a.medio_reunion_id,

                ap.estado AS estado_participante,

                ap.participante_id AS participante_id,

                CASE ap.participante_tipo_id
                    WHEN 1 THEN 'aspirante'
                    WHEN 2 THEN 'creador'
                    WHEN 3 THEN 'usuario'
                    ELSE 'usuario'
                END AS participante_tipo,

                COALESCE(
                    NULLIF(asp.nombre_real, ''),
                    NULLIF(asp.nickname, ''),
                    NULLIF(asp.usuario, ''),
                    NULLIF(cre.nombre_real, ''),
                    NULLIF(cre.nickname, ''),
                    NULLIF(usr.nombre_completo, ''),
                    NULLIF(usr.username, ''),
                    asp.telefono,
                    cre.telefono,
                    usr.telefono
                ) AS nombre,

                COALESCE(asp.nickname, cre.nickname, NULL) AS nickname

            FROM agendamientos a
            INNER JOIN agendamientos_participantes ap
                   ON ap.agendamiento_id = a.id
            LEFT JOIN aspirantes asp
                   ON asp.id = ap.participante_id AND ap.participante_tipo_id = 1
            LEFT JOIN aspirantes cre
                   ON cre.id = ap.participante_id AND ap.participante_tipo_id = 2
            LEFT JOIN administradores usr
                   ON usr.id = ap.participante_id AND ap.participante_tipo_id = 3
            WHERE a.fecha_inicio >= %s
              AND a.fecha_inicio <= %s
            ORDER BY a.fecha_inicio ASC, a.id ASC
            LIMIT %s
            """

            cur.execute(sql, (time_min, time_max, max_results))
            rows = cur.fetchall()

            if not rows:
                logger.info("✅ No hay agendamientos en el rango solicitado")
                return []

            eventos_map: Dict[int, Dict] = {}

            for (
                ag_id,
                titulo,
                descripcion,
                fecha_inicio,
                fecha_fin,
                responsable_id,
                estado_id,
                link_meet,
                tipo_agendamiento,
                google_event_id,
                timezone,
                medio_reunion_id,
                estado_participante,
                participante_id,
                participante_tipo,
                nombre,
                nickname,
            ) in rows:

                if ag_id not in eventos_map:
                    eventos_map[ag_id] = {
                        "agendamiento_id": str(ag_id),
                        "titulo": titulo or "Sin título",
                        "descripcion": descripcion or "",
                        "inicio": fecha_inicio,
                        "fin": fecha_fin,
                        "responsable_id": responsable_id,
                        "estado": estado_id,
                        "link_meet": link_meet,
                        "tipo_agendamiento": tipo_agendamiento,
                        "google_event_id": google_event_id,
                        "timezone": timezone,
                        "medio_reunion_id": medio_reunion_id,
                        "origen": "google_calendar" if google_event_id else "interno",
                        "participantes": [],
                        "participantes_ids": set(),
                        "participante_tipo": None,
                    }

                if participante_id is not None:
                    ev = eventos_map[ag_id]

                    if participante_id not in ev["participantes_ids"]:
                        ev["participantes_ids"].add(participante_id)

                        ev["participantes"].append(
                            {
                                "id": participante_id,
                                "nombre": nombre,
                                "nickname": nickname,
                                "tipo": participante_tipo,
                                "estado": estado_participante,
                            }
                        )

                    # Si todos los participantes del evento son del mismo tipo,
                    # dejamos ese valor. Si luego quieres manejar mixtos,
                    # esto se puede volver una lista/set.
                    if ev["participante_tipo"] is None:
                        ev["participante_tipo"] = participante_tipo

            resultado: List[EventoOut] = []
            for _, ev in eventos_map.items():
                resultado.append(
                    EventoOut(
                        agendamiento_id=ev["agendamiento_id"],
                        titulo=ev["titulo"],
                        descripcion=ev["descripcion"],
                        inicio=ev["inicio"],
                        fin=ev["fin"],
                        participantes_ids=list(ev["participantes_ids"]),
                        participantes=ev["participantes"],
                        link_meet=ev["link_meet"],
                        tipo_agendamiento=ev["tipo_agendamiento"],
                        responsable_id=ev["responsable_id"],
                        origen=ev["origen"],
                        google_event_id=ev["google_event_id"],
                        participante_tipo=ev["participante_tipo"],
                        medio_reunion_id=ev["medio_reunion_id"],
                    )
                )

            logger.info(f"✅ Se obtuvieron {len(resultado)} agendamientos desde BD")
            return resultado

    except Exception as e:
        logger.error(f"❌ Error al obtener eventos desde BD: {e}")
        logger.error(traceback.format_exc())
        raise

class TimeZoneOut(BaseModel):
    aspirante_id: int
    zona_horaria: Optional[str] = None

@router.get("/api/aspirantes/{aspirante_id}/timezone", response_model=TimeZoneOut)
def obtener_timezone_creador(aspirante_id: int):
    with get_connection_context() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT zona_horaria
                FROM aspirantes_perfil
                WHERE aspirante_id = %s
                """,
                (aspirante_id,)
            )
            row = cur.fetchone()
            if not row:
                # existe el creador, pero puede que no tenga aspirantes_perfil, tú ya dijiste que sí tiene,
                # igual por seguridad devolvemos zona_horaria = None
                return TimeZoneOut(aspirante_id=aspirante_id, zona_horaria=None)

            return TimeZoneOut(
                aspirante_id=aspirante_id,
                zona_horaria=row[0]
            )
        except Exception as e:
            logger.error(f"❌ Error obteniendo timezone del creador {aspirante_id}: {e}")
            logger.error(traceback.format_exc())
            raise HTTPException(
                status_code=500,
                detail="Error interno al obtener timezone del creador."
            )

# ----------
# ------EDITAR AGENDAMIENTO MOBILE
# ----------


import json
from googleapiclient.discovery import build
load_dotenv()
SERVICE_ACCOUNT_INFO = os.getenv("GOOGLE_CREDENTIALS_JSON")
CALENDAR_ID = os.getenv("CALENDAR_ID")

from google.oauth2 import service_account
def get_calendar_service():
    try:
        SCOPES = ["https://www.googleapis.com/auth/calendar"]
        creds_dict = json.loads(SERVICE_ACCOUNT_INFO)  # string JSON desde env
        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=SCOPES
        )

        # 👉 Impersonar al usuario de Workspace
        delegated_creds = creds.with_subject(os.getenv("CALENDAR_ID"))

        service = build("calendar", "v3", credentials=delegated_creds)
        logger.info(f"✅ Servicio de Google Calendar inicializado con impersonación como {os.getenv('CALENDAR_ID')}")
        return service

    except Exception as e:
        logger.error("❌ Error al inicializar el servicio de Google Calendar:")
        logger.error(traceback.format_exc())
        raise


class AgendamientoUpdateIn(BaseModel):
    inicio: datetime
    fin: Optional[datetime] = None
    timezone: Optional[str] = None


class TokenInfoOut(BaseModel):
    aspirante_id: int
    responsable_id: int
    zona_horaria: Optional[str] = None
    nombre_mostrable: Optional[str] = None
    duracion_minutos: Optional[int] = None

class CrearLinkAgendamientoIn(BaseModel):
    aspirante_id: int
    responsable_id: int
    minutos_validez: int = 60          # vigencia del token
    duracion_minutos: int = 60         # duración estimada de la cita
    tipo_agendamiento: Literal["LIVE", "ENTREVISTA"] = Field(
        default="ENTREVISTA",
        description="Tipo de cita: 'LIVE' para prueba TikTok LIVE o 'ENTREVISTA' con asesor."
    )


class LinkAgendamientoOut(BaseModel):
    token: str
    url: AnyUrl
    expiracion: datetime


@router.put("/api/agendamientos/{agendamiento_id}", response_model=EventoOut)
def actualizar_fecha_agendamiento(
    agendamiento_id: int,
    data: AgendamientoUpdateIn,
):
    """
    Reagenda una cita existente.
    - Solo modifica fecha/hora
    - Mantiene duración si no se envía fin
    - link_meet solo aplica si tipo_agendamiento = ENTREVISTA
    """

    with get_connection_context() as conn:
        cur = conn.cursor()

        try:
            # 1️⃣ Buscar agendamiento
            cur.execute(
                """
                SELECT
                    a.id,
                    a.titulo,
                    a.descripcion,
                    a.fecha_inicio,
                    a.fecha_fin,
                    ap.participante_id AS aspirante_id,
                    a.responsable_id,
                    a.estado_id,
                    a.link_meet,
                    a.tipo_agendamiento
                FROM agendamientos a
                LEFT JOIN agendamientos_participantes ap
                    ON ap.agendamiento_id = a.id
                   AND ap.participante_tipo_id = %s
                WHERE a.id = %s
                """,
                (PARTICIPANTE_TIPO_ASPIRANTE_ID, agendamiento_id),
            )

            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="El agendamiento no existe.")

            (
                ag_id,
                titulo_actual,
                descripcion_actual,
                inicio_actual,
                fin_actual,
                aspirante_id,
                responsable_id,
                estado,
                link_meet_actual,
                tipo_agendamiento,
            ) = row

            # 2️⃣ Calcular inicio (UTC si viene timezone)
            nuevo_inicio = data.inicio
            tz = None

            if data.timezone:
                tz = ZoneInfo(data.timezone)
                if nuevo_inicio.tzinfo is None:
                    nuevo_inicio = nuevo_inicio.replace(tzinfo=tz)
                nuevo_inicio = nuevo_inicio.astimezone(ZoneInfo("UTC"))
            else:
                if nuevo_inicio.tzinfo:
                    nuevo_inicio = nuevo_inicio.astimezone(ZoneInfo("UTC"))

            # 3️⃣ Calcular fin
            if data.fin:
                nuevo_fin = data.fin
                if data.timezone:
                    if nuevo_fin.tzinfo is None:
                        nuevo_fin = nuevo_fin.replace(tzinfo=tz)
                    nuevo_fin = nuevo_fin.astimezone(ZoneInfo("UTC"))
                else:
                    if nuevo_fin.tzinfo:
                        nuevo_fin = nuevo_fin.astimezone(ZoneInfo("UTC"))
            else:
                duracion = fin_actual - inicio_actual
                nuevo_fin = nuevo_inicio + duracion

            if nuevo_fin <= nuevo_inicio:
                raise HTTPException(
                    status_code=400,
                    detail="La fecha de fin debe ser posterior a la fecha de inicio."
                )

            # # 4️⃣ Regla de negocio: Meet solo para ENTREVISTA
            #     link_meet_actual = None

            # 5️⃣ Update BD
            cur.execute(
                """
                UPDATE agendamientos
                SET fecha_inicio = %s,
                    fecha_fin = %s,
                    link_meet = %s,
                    actualizado_en = NOW()
                WHERE id = %s
                """,
                (
                    nuevo_inicio,
                    nuevo_fin,
                    link_meet_actual,
                    ag_id,
                )
            )

            conn.commit()

            # 6️⃣ Respuesta (EventoOut exige agendamiento_id; no usar id ni campos fuera del schema)
            return EventoOut(
                agendamiento_id=str(ag_id),
                titulo=titulo_actual or "Sin título",
                descripcion=descripcion_actual or "",
                inicio=nuevo_inicio,
                fin=nuevo_fin,
                participantes_ids=[aspirante_id] if aspirante_id is not None else [],
                link_meet=link_meet_actual if tipo_agendamiento == "ENTREVISTA" else None,
                responsable_id=responsable_id,
                origen="interno",
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Error actualizando agendamiento {agendamiento_id}: {e}")
            logger.error(traceback.format_exc())
            raise HTTPException(
                status_code=500,
                detail="Error interno al actualizar el agendamiento."
            )

@router.delete("/api/agendamientos/{agendamiento_id}")
def eliminar_agendamiento(agendamiento_id: int):
    with get_connection_context() as conn:
        cur = conn.cursor()

        try:
            # 1️⃣ Verificar que el agendamiento exista
            cur.execute(
                """
                SELECT id, tipo_agendamiento
                FROM agendamientos
                WHERE id = %s
                """,
                (agendamiento_id,)
            )

            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="El agendamiento no existe."
                )

            # 2️⃣ Eliminar agendamiento
            # (participantes se eliminan por ON DELETE CASCADE)
            cur.execute(
                "DELETE FROM agendamientos WHERE id = %s",
                (agendamiento_id,)
            )

            return {
                "ok": True,
                "mensaje": f"Agendamiento {agendamiento_id} eliminado correctamente"
            }

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"❌ Error al eliminar agendamiento {agendamiento_id}: {e}")
            logger.error(traceback.format_exc())
            raise HTTPException(
                status_code=500,
                detail="Error interno al eliminar el agendamiento."
            )


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


@router.get("/api/aspirantes/{aspirante_id}/citas", response_model=list[CitaAspiranteOut])
def listar_citas_creador(aspirante_id: int):
    citas: list[CitaAspiranteOut] = []

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
                    ON ae.id = a.estado_id
                INNER JOIN agendamientos_tipo at
                    ON at.id = a.tipo_agendamiento
                WHERE ap.participante_tipo_id = 1
                  AND ap.participante_id = %s
                  AND at.participante_tipo_id = 1
                ORDER BY a.fecha_inicio ASC
                """,
                (aspirante_id,)
            )
            rows = cur.fetchall()

    for a_id, f_ini, f_fin, estado_nombre, tipo_nombre, link_meet in rows:
        duracion_min = int((f_fin - f_ini).total_seconds() // 60)

        # lógica nueva
        realizada = (estado_nombre == "cumplido")

        citas.append(
            CitaAspiranteOut(
                id=a_id,
                fecha_inicio=f_ini.isoformat(),
                fecha_fin=f_fin.isoformat(),
                duracion_minutos=duracion_min,
                tipo_agendamiento=tipo_nombre.upper(),
                realizada=realizada,
                estado=estado_nombre or "programado",
                link_meet=link_meet,
                url_reagendar=None,
            )
        )

    return citas


class TikTokLiveLinkIn(BaseModel):
    token: str
    link_tiktok: str
    agendamiento_id: Optional[int] = None

class TikTokLiveLinkOut(BaseModel):
    agendamiento_id: int
    message: str

@router.post("/api/aspirantes/tiktok-live-link", response_model=TikTokLiveLinkOut)
def guardar_tiktok_live_link(payload: TikTokLiveLinkIn):
    # 1️⃣ Resolver token → devuelve dict con aspirante_id y responsable_id
    info_token = resolver_creador_por_token(payload.token)
    if not info_token:
        raise HTTPException(status_code=404, detail="Aspirante no encontrado")

    aspirante_id = info_token["aspirante_id"]

    # 2️⃣ Validar link de TikTok
    link = payload.link_tiktok.strip()
    if not validar_link_tiktok(link):
        raise HTTPException(
            status_code=400,
            detail="El formato del enlace de TikTok no es válido."
        )

    # 3️⃣ Exigir agendamiento_id (ya no se crean citas nuevas)
    if not payload.agendamiento_id:
        raise HTTPException(
            status_code=400,
            detail="Debes seleccionar una cita para asociar tu TikTok LIVE."
        )

    # 4️⃣ Verificar que la cita pertenece al creador del token
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM agendamientos a
                JOIN agendamientos_participantes ap
                  ON ap.agendamiento_id = a.id
                WHERE a.id = %s
                  AND ap.participante_tipo_id = 1
                  AND ap.participante_id = %s
                """,
                (payload.agendamiento_id, aspirante_id)
            )
            if not cur.fetchone():
                raise HTTPException(
                    status_code=403,
                    detail="No tienes permiso sobre esta cita."
                )

            # 5️⃣ Actualizar link_meet con el link de TikTok
            cur.execute(
                """
                UPDATE agendamientos
                SET link_meet = %s
                WHERE id = %s
                """,
                (link, payload.agendamiento_id)
            )

    # 6️⃣ Respuesta final
    return TikTokLiveLinkOut(
        agendamiento_id=payload.agendamiento_id,
        message="Enlace de TikTok LIVE actualizado para tu cita."
    )


def resolver_creador_por_token(token: str) -> Optional[Dict]:
    """
    Resuelve un token público de acceso para aspirantes.

    Tabla usada: link_agendamiento_tokens
    Campos:
      - token: str
      - aspirante_id: int
      - responsable_id: int (opcional)
      - expiracion: timestamp
      - usado: bool

    Devuelve:
        {
            "aspirante_id": int,
            "responsable_id": Optional[int]
        }
    O None si:
        - no existe
        - expiró
        - fue marcado como usado (opcional)
    """

    if not token:
        return None

    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT token, aspirante_id, responsable_id, expiracion, usado
                    FROM agendamientos_link_tokens
                    WHERE token = %s
                    """,
                    (token,)
                )
                row = cur.fetchone()

        if not row:
            print(f"⚠️ Token inválido o no encontrado: {token}")
            return None

        (
            token_db,
            aspirante_id,
            responsable_id,
            expiracion,
            usado,
        ) = row

        # 1) Verificar expiración
        if expiracion:
            now_utc = datetime.now(timezone.utc)
            # Convertir expiración a timezone-aware si es naive
            if expiracion.tzinfo is None:
                expiracion = expiracion.replace(tzinfo=timezone.utc)

            if now_utc > expiracion:
                print(f"⚠️ Token expirado: {token}")
                return None

        # 2) Verificar si ya fue usado (si quieres bloquearlo)
        if usado:
            print(f"⚠️ Token ya usado: {token}")
            return None

        # 3) Devuelve creador y responsable asociado
        return {
            "aspirante_id": aspirante_id,
            "responsable_id": responsable_id
        }

    except Exception as e:
        print(f"❌ Error en resolver_creador_por_token: {e}")
        return None


# --------------------------------
# --------------------------------
# --------------------------------

def generar_token_corto(longitud=10):
    caracteres = string.ascii_letters + string.digits  # A-Z a-z 0-9
    return ''.join(secrets.choice(caracteres) for _ in range(longitud))


class EnviarNoAptoIn(BaseModel):
    aspirante_id: int

def mensaje_no_apto_simple(nombre: Optional[str], business_name: str) -> str:

    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT valor
                    FROM configuracion_agencia_keys
                    WHERE clave = %s
                    LIMIT 1
                """, ("mensaje_rechazado",))

                row = cur.fetchone()
                template_text = row[0] if row and row[0] else None

    except Exception as e:
        print("❌ Error obteniendo mensaje_rechazado:", e)
        traceback.print_exc()
        template_text = None

    # 🔹 Si existe en DB → usarlo tal cual pero formateado
    if template_text:
        return template_text.format(
            nombre=nombre.strip() if nombre and nombre.strip() else "Hola",
            business_name=business_name
        )

    # 🔹 Fallback original (exactamente tu mensaje)
    if nombre:
        saludo = f"Hola {nombre} 👋\n\n"
    else:
        saludo = "Hola 👋\n\n"

    cuerpo = (
        f"Gracias por tu interés en *{business_name}* y por el tiempo que dedicaste a completar tu información.\n\n"
        "Después de revisar tu preevaluación, en este momento no cumples con los requisitos "
        "para continuar en el proceso de selección de aspirantes de TikTok LIVE.\n\n"
        "Esto no refleja tu talento ni tu potencial. Te invitamos a seguir fortaleciendo tu contenido "
        "y métricas, y a postular nuevamente más adelante si lo deseas.\n\n"
        "Puedes consultar el diagnóstico completo en el portal que te compartimos anteriormente.\n\n"
        "Te deseamos muchos éxitos en tus próximos proyectos 🙌"
    )

    return saludo + cuerpo


def mensaje_invitacion_simple(nombre: Optional[str], business_name: str) -> str:

    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT valor
                    FROM configuracion_agencia
                    WHERE clave = %s
                    LIMIT 1
                """, ("mensaje_invitacion",))

                row = cur.fetchone()

                if not row or not row[0]:
                    raise ValueError("La clave 'mensaje_invitacion' no existe en configuracion_agencia")

                template_text = row[0]

    except Exception as e:
        print("❌ Error obteniendo mensaje_invitacion:", e)
        traceback.print_exc()
        raise  # 🔥 Aquí forzamos a que falle si no existe

    nombre_final = nombre.strip() if nombre and nombre.strip() else "Hola"

    try:
        return template_text.format(
            nombre=nombre_final,
            business_name=business_name
        )
    except KeyError as e:
        print(f"⚠️ Placeholder incorrecto en mensaje_invitacion: {e}")
        return template_text  # lo envía sin reemplazar si hay error


# -----------------------------------------------------
# ---------------CREAR NUEVO MODULO .PY PRE-EVALUACION------------------------
# -----------------------------------------------------

from types import SimpleNamespace

ESTADO_AGENDAMIENTO_PROGRAMADO = 1
TIPO_AGENDAMIENTO_LIVE = 1
TIPO_AGENDAMIENTO_ENTREVISTA = 2
TIPO_AGENDAMIENTO_OTRO = 4

ENTREVISTA_TIPO_LIVE = 1
ENTREVISTA_TIPO_ENTREVISTA = 2
ESTADO_ENTREVISTA_PROGRAMADA = 1


@router.post("/api/agendamientos/aspirante/{token}", response_model=EventoOut)
def crear_agendamiento_aspirante(
    token: str,
    data: AgendamientoAspiranteIn,
):
    """
    Guarda una cita desde el link de agendamiento usando token en la URL:
    → Valida token
    → Crea agendamiento
    → Marca token como usado
    → Guarda agendamiento_id en agendamientos_link_tokens
    → Si es ENTREVISTA, crea evento en Google Calendar con Meet
    """

    with get_connection_context() as conn:
        cur = conn.cursor()

        try:
            # 1️⃣ Validar token
            cur.execute(
                """
                SELECT
                    token,
                    aspirante_id,
                    responsable_id,
                    expiracion,
                    usado,
                    duracion_minutos,
                    tipo_agendamiento,
                    agendamiento_id
                FROM agendamientos_link_tokens
                WHERE token = %s
                """,
                (token,)
            )
            token_row = cur.fetchone()

            if not token_row:
                raise HTTPException(status_code=404, detail="Link inválido.")

            (
                token_db,
                aspirante_id,
                responsable_id,
                expiracion,
                usado,
                duracion_minutos,
                tipo_agendamiento_db,
                agendamiento_id_existente
            ) = token_row

            if usado:
                raise HTTPException(
                    status_code=400,
                    detail="Este link ya fue utilizado."
                )

            if expiracion < datetime.now():
                raise HTTPException(
                    status_code=400,
                    detail="Este link ya expiró."
                )

            # Seguridad extra: si por alguna razón ya quedó ligado a una cita
            if agendamiento_id_existente:
                raise HTTPException(
                    status_code=400,
                    detail="Este link ya está asociado a un agendamiento."
                )

            # 2️⃣ Obtener aspirante
            cur.execute(
                """
                SELECT
                    id,
                    COALESCE(NULLIF(nombre_real, ''), nickname) AS nombre,
                    nickname
                FROM aspirantes
                WHERE id = %s
                """,
                (aspirante_id,)
            )
            row = cur.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="El aspirante no existe.")

            aspirante_id, aspirante_nombre_db, aspirante_nickname = row

            # 3️⃣ Guardar timezone si viene
            if data.timezone:
                cur.execute(
                    """
                    UPDATE aspirantes_perfil
                    SET zona_horaria = %s
                    WHERE aspirante_id = %s
                    """,
                    (data.timezone, aspirante_id)
                )

            # 4️⃣ Calcular fechas
            fecha_inicio = data.inicio
            tz = None

            if data.timezone:
                tz = ZoneInfo(data.timezone)
                if fecha_inicio.tzinfo is None:
                    fecha_inicio = fecha_inicio.replace(tzinfo=tz)
                fecha_inicio = fecha_inicio.astimezone(ZoneInfo("UTC"))
            elif fecha_inicio.tzinfo is not None:
                fecha_inicio = fecha_inicio.astimezone(ZoneInfo("UTC"))

            if duracion_minutos:
                fecha_fin = fecha_inicio + timedelta(minutes=duracion_minutos)
            else:
                if not data.fin:
                    raise HTTPException(
                        status_code=400,
                        detail="El link no tiene duración y no se recibió fecha fin."
                    )

                fecha_fin = data.fin
                if data.timezone and fecha_fin.tzinfo is None:
                    fecha_fin = fecha_fin.replace(tzinfo=tz)
                if fecha_fin.tzinfo is not None:
                    fecha_fin = fecha_fin.astimezone(ZoneInfo("UTC"))

                if fecha_fin <= fecha_inicio:
                    raise HTTPException(
                        status_code=400,
                        detail="La fecha fin debe ser posterior a la fecha inicio."
                    )

            tipo_agendamiento = (tipo_agendamiento_db or "").upper()

            # 5️⃣ Crear evento Google Calendar si aplica
            link_meet = None
            google_event_id = None

            if tipo_agendamiento == "ENTREVISTA":
                try:
                    google_event = crear_evento_google(
                        resumen=data.titulo,
                        descripcion=data.descripcion or "",
                        fecha_inicio=fecha_inicio,
                        fecha_fin=fecha_fin,
                        requiere_meet=True,
                    )
                    link_meet = google_event.get("hangoutLink")
                    google_event_id = google_event.get("id")
                except Exception as e:
                    logger.error(f"⚠️ Error creando evento Google Calendar: {e}")

            # 6️⃣ Crear agendamiento + entrevista en la misma transacción
            agendamiento_id = crear_agendamiento_aspirante_DB(
                cur=cur,
                data=SimpleNamespace(
                    titulo=data.titulo,
                    descripcion=data.descripcion,
                    fecha_inicio=fecha_inicio,
                    fecha_fin=fecha_fin,
                    tipo_agendamiento=tipo_agendamiento,
                    link_meet=link_meet,
                    google_event_id=google_event_id,
                ),
                aspirante_id=aspirante_id,
                responsable_id=responsable_id
            )

            if not agendamiento_id:
                raise HTTPException(
                    status_code=500,
                    detail="No se pudo crear el agendamiento."
                )

            # 7️⃣ Marcar token como usado + guardar agendamiento_id
            cur.execute(
                """
                UPDATE agendamientos_link_tokens
                SET usado = true,
                    usado_en = NOW(),
                    agendamiento_id = %s
                WHERE token = %s
                """,
                (agendamiento_id, token)
            )

            conn.commit()

            participante = {
                "id": aspirante_id,
                "nombre": aspirante_nombre_db,
                "nickname": aspirante_nickname,
            }

            # 8️⃣ Respuesta correcta según EventoOut
            return EventoOut(
                agendamiento_id=str(agendamiento_id),
                titulo=data.titulo,
                descripcion=data.descripcion,
                inicio=fecha_inicio,
                fin=fecha_fin,
                participantes_ids=[aspirante_id],
                aspirante_id=aspirante_id,
                responsable_id=responsable_id,
                participantes=[participante],
                estado="programado",
                link_meet=link_meet,
                origen="interno",
                google_event_id=google_event_id,
            )

        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ Error creando agendamiento de aspirante: {e}")
            logger.error(traceback.format_exc())
            raise HTTPException(
                status_code=500,
                detail="Error interno al crear agendamiento de aspirante."
            )


def crear_agendamiento_aspirante_DB(
    cur,
    data,
    aspirante_id: int,
    responsable_id: int
) -> Optional[int]:
    """
    Crea un agendamiento y crea su entrevista asociada directamente.

    Devuelve agendamiento_id.

    Se espera que `data` tenga:
      - titulo
      - descripcion
      - fecha_inicio (UTC)
      - fecha_fin (UTC)
      - tipo_agendamiento (LIVE / ENTREVISTA)
      - link_meet (opcional)
      - google_event_id (opcional)
    """

    try:
        tipo_agendamiento = (getattr(data, "tipo_agendamiento", None) or "").upper()

        mapa_tipos_agendamiento = {
            "ENTREVISTA": TIPO_AGENDAMIENTO_ENTREVISTA,
            "LIVE": TIPO_AGENDAMIENTO_LIVE,
        }

        tipo_agendamiento_id = mapa_tipos_agendamiento.get(
            tipo_agendamiento,
            TIPO_AGENDAMIENTO_OTRO
        )

        mapa_tipos_entrevista = {
            "LIVE": ENTREVISTA_TIPO_LIVE,
            "ENTREVISTA": ENTREVISTA_TIPO_ENTREVISTA,
        }

        entrevista_tipo_id = mapa_tipos_entrevista.get(
            tipo_agendamiento,
            ENTREVISTA_TIPO_ENTREVISTA
        )

        titulo = getattr(data, "titulo", None)
        descripcion = getattr(data, "descripcion", None)
        fecha_inicio = getattr(data, "fecha_inicio", None)
        fecha_fin = getattr(data, "fecha_fin", None)
        link_meet = getattr(data, "link_meet", None)
        google_event_id = getattr(data, "google_event_id", None)

        if not titulo:
            raise ValueError("El título del agendamiento es obligatorio.")

        if not fecha_inicio or not fecha_fin:
            raise ValueError("fecha_inicio y fecha_fin son obligatorias.")

        if fecha_fin <= fecha_inicio:
            raise ValueError("fecha_fin debe ser posterior a fecha_inicio.")

        # Si es LIVE y no viene link, construirlo automáticamente (usuario TikTok en aspirantes)
        medio_ins = _fetch_medio_reunion_id_por_tipo(cur, tipo_agendamiento_id)
        if medio_ins == MEDIO_REUNION_TIKTOK_LIVE and not link_meet:
            link_meet = obtener_link_live_por_creador(aspirante_id)

        # 1️⃣ Crear agendamiento
        cur.execute(
            """
            INSERT INTO agendamientos (
                titulo,
                descripcion,
                fecha_inicio,
                fecha_fin,
                responsable_id,
                estado_id,
                tipo_agendamiento,
                link_meet,
                google_event_id,
                medio_reunion_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                titulo,
                descripcion,
                fecha_inicio,
                fecha_fin,
                responsable_id,
                ESTADO_AGENDAMIENTO_PROGRAMADO,
                tipo_agendamiento_id,
                link_meet,
                google_event_id,
                medio_ins,
            )
        )

        row = cur.fetchone()
        if not row:
            raise Exception("No se pudo crear el agendamiento.")

        agendamiento_id = row[0]

        # 2️⃣ Crear entrevista asociada
        cur.execute(
            """
            INSERT INTO entrevistas (
                aspirante_id,
                agendamiento_id,
                entrevista_tipo_id,
                usuario_evalua,
                estado_id,
                creado_en,
                actualizado_en
            )
            VALUES (%s, %s, %s, %s, %s, NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC')
            RETURNING id
            """,
            (
                aspirante_id,
                agendamiento_id,
                entrevista_tipo_id,
                responsable_id,
                ESTADO_ENTREVISTA_PROGRAMADA,
            )
        )

        entrevista_row = cur.fetchone()
        if not entrevista_row:
            raise Exception("No se pudo crear la entrevista asociada.")

        # 3️⃣ Insertar participante
        cur.execute(
            """
            INSERT INTO agendamientos_participantes (
                agendamiento_id,
                participante_tipo_id,
                participante_id
            )
            VALUES (%s, %s, %s)
            """,
            (agendamiento_id, PARTICIPANTE_TIPO_ASPIRANTE_ID, aspirante_id),
        )

        return agendamiento_id

    except Exception as e:
        print("❌ Error en crear_agendamiento_aspirante_DB:", e)
        return None


def crear_evento_google(resumen, descripcion, fecha_inicio, fecha_fin, requiere_meet=False):
    service = get_calendar_service()

    # 🧱 Estructura base del evento
    evento = {
        'summary': resumen,
        'description': descripcion,
        'start': {
            'dateTime': fecha_inicio.isoformat(),
            'timeZone': 'America/Bogota',
        },
        'end': {
            'dateTime': fecha_fin.isoformat(),
            'timeZone': 'America/Bogota',
        },
    }

    # ✅ Si requiere Meet, agregamos conferenceData
    if requiere_meet:
        evento['conferenceData'] = {
            'createRequest': {
                'requestId': str(uuid4()),
                'conferenceSolutionKey': {'type': 'hangoutsMeet'},
            }
        }

    # ⚙️ Insertar evento en Google Calendar
    evento_creado = service.events().insert(
        calendarId=CALENDAR_ID,
        body=evento,
        conferenceDataVersion=1 if requiere_meet else 0  # Solo activa el modo Meet si se requiere
    ).execute()

    logger.info(f"✅ Evento creado: {evento_creado.get('htmlLink')}")
    if requiere_meet:
        logger.info(f"🔗 Meet: {evento_creado.get('hangoutLink')}")

    return evento_creado

def obtener_link_live_por_creador(aspirante_id: int) -> Optional[str]:
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT usuario
                    FROM aspirantes
                    WHERE id = %s
                    """,
                    (aspirante_id,)
                )
                row = cur.fetchone()

                if not row or not row[0]:
                    return None

                usuario = row[0].strip()
                return f"https://www.tiktok.com/@{usuario}/live"

    except Exception as e:
        print("❌ Error obteniendo link LIVE:", e)
        return None


def obtener_entrevista_id(aspirante_id: int, usuario_evalua: int) -> Optional[dict]:
    """
    Obtiene una entrevista existente por aspirante_id.
    Si no existe, crea una entrevista mínima.
    Devuelve: { id, creado_en }
    """

    try:
        # ✅ usar siempre el context manager
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                # 1️⃣ Buscar entrevista existente
                cur.execute("""
                    SELECT id, creado_en
                    FROM entrevistas
                    WHERE aspirante_id = %s
                    ORDER BY creado_en ASC
                    LIMIT 1
                """, (aspirante_id,))

                row = cur.fetchone()

                if row:
                    return {"id": row[0], "creado_en": row[1]}

                # 2️⃣ Crear entrevista mínima
                cur.execute("""
                    INSERT INTO entrevistas (aspirante_id, usuario_evalua, creado_en)
                    VALUES (%s, %s, NOW() AT TIME ZONE 'UTC')
                    RETURNING id, creado_en
                """, (aspirante_id, usuario_evalua))

                new_row = cur.fetchone()

                if not new_row:
                    return None

                # El commit lo hace get_connection_context()
                return {"id": new_row[0], "creado_en": new_row[1]}

    except Exception as e:
        print("❌ Error en obtener_entrevista_id:", e)
        return None


from zoneinfo import ZoneInfo



class ParticipanteTipoOut(BaseModel):
    id: int
    codigo: str
    nombre: str


class TipoAgendamientoOut(BaseModel):
    id: int
    nombre: str
    color: Optional[str] = None
    icono: Optional[str] = None
    activo: bool
    participante_tipo: Optional[ParticipanteTipoOut] = None

@router.get("/api/agendamientos/tipos", response_model=List[TipoAgendamientoOut])
def listar_tipos_agendamiento(
    solo_activos: bool = Query(True, description="Si True, trae solo tipos activos")
):

    with get_connection_context() as conn:
        cur = conn.cursor()

        if solo_activos:
            cur.execute(
                """
                SELECT 
                    at.id, 
                    at.nombre, 
                    at.color, 
                    at.icono, 
                    at.activo,
                    pt.id,
                    pt.codigo,
                    pt.nombre
                FROM agendamientos_tipo at
                LEFT JOIN participante_tipo pt
                    ON pt.id = at.participante_tipo_id
                WHERE at.activo = TRUE
                ORDER BY at.id ASC
                """
            )
        else:
            cur.execute(
                """
                SELECT 
                    at.id, 
                    at.nombre, 
                    at.color, 
                    at.icono, 
                    at.activo,
                    pt.id,
                    pt.codigo,
                    pt.nombre
                FROM agendamientos_tipo at
                LEFT JOIN participante_tipo pt
                    ON pt.id = at.participante_tipo_id
                ORDER BY at.nombre ASC
                """
            )

        rows = cur.fetchall()

    return [
        TipoAgendamientoOut(
            id=r[0],
            nombre=r[1],
            color=r[2],
            icono=r[3],
            activo=r[4],
            participante_tipo=ParticipanteTipoOut(
                id=r[5],
                codigo=r[6],
                nombre=r[7]
            ) if r[5] else None
        )
        for r in rows
    ]


# ---------------------------------
# ------CAMBIO ESTADO--------------
# ---------------------------------


ESTADOS_AGENDAMIENTO = {
    "programado": 1,
    "confirmado": 2,
    "cancelado": 3,
    "cumplido": 4,
}


class EstadoUpdateIn(BaseModel):
    estado: str = Field(..., description="programado|confirmado|cancelado|cumplido")

@router.post("/api/agendamientos/{agendamiento_id}/recordatorio")
def enviar_recordatorio_manual(
    agendamiento_id: int,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    with get_connection_context() as conn:
        cur = conn.cursor()

        # =========================================================
        # 1. Obtener cita + participante principal en un solo query
        # =========================================================
        cur.execute("""
            SELECT
                a.id,
                a.fecha_inicio,
                a.fecha_fin,
                a.link_meet,
                ta.nombre AS tipo_cita_nombre,

                ap.participante_id AS participante_id,

                CASE ap.participante_tipo_id
                    WHEN 1 THEN 'aspirante'
                    WHEN 2 THEN 'creador'
                    WHEN 3 THEN 'usuario'
                    ELSE NULL
                END AS participante_tipo,

                COALESCE(
                    NULLIF(asp.whatsapp, ''),
                    asp.telefono,
                    NULLIF(cre.whatsapp, ''),
                    cre.telefono,
                    usr.telefono
                ) AS telefono_final,

                COALESCE(
                    NULLIF(asp.nickname, ''),
                    NULLIF(asp.nombre_real, ''),
                    NULLIF(asp.usuario, ''),
                    NULLIF(cre.nickname, ''),
                    NULLIF(cre.nombre_real, ''),
                    NULLIF(usr.nombre_completo, ''),
                    NULLIF(usr.username, '')
                ) AS nombre

            FROM agendamientos a
            INNER JOIN agendamientos_tipo ta
                ON a.tipo_agendamiento = ta.id
            INNER JOIN agendamientos_participantes ap
                ON ap.agendamiento_id = a.id
            LEFT JOIN aspirantes asp
                ON asp.id = ap.participante_id AND ap.participante_tipo_id = 1
            LEFT JOIN aspirantes cre
                ON cre.id = ap.participante_id AND ap.participante_tipo_id = 2
            LEFT JOIN administradores usr
                ON usr.id = ap.participante_id AND ap.participante_tipo_id = 3
            WHERE a.id = %s
            ORDER BY CASE ap.participante_tipo_id WHEN 1 THEN 0 WHEN 2 THEN 1 WHEN 3 THEN 2 ELSE 3 END, ap.id ASC
            LIMIT 1
        """, (agendamiento_id,))

        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Cita no encontrada.")

        (
            cita_id,
            fecha_inicio,
            fecha_fin,
            link_meet,
            tipo_cita_nombre,
            participante_id,
            participante_tipo,
            telefono,
            nombre
        ) = row

        if not participante_id:
            raise HTTPException(status_code=404, detail="Participante no encontrado para la cita.")

        if not telefono:
            raise HTTPException(status_code=400, detail="El participante no tiene teléfono registrado.")

    # =========================================================
    # 2. Formatear mensaje
    # =========================================================
    nombre_agencia = current_business_name.get() or "nuestra agencia"
    nombre_evento = tipo_cita_nombre.lower() if tipo_cita_nombre else "cita"

    fecha_str = fecha_inicio.strftime("%d de %B")
    hora_inicio_str = fecha_inicio.strftime("%I:%M %p").lower()

    if link_meet and "tiktok" not in link_meet.lower():
        link_final = link_meet
    else:
        link_final = "Ingresa a tu perfil de TikTok LIVE"

    # =========================================================
    # 3. Credenciales WABA
    # =========================================================
    tenant_key = current_tenant.get() or "test"
    cuenta = obtener_cuenta_por_subdominio(tenant_key)
    if not cuenta:
        raise HTTPException(status_code=500, detail=f"No hay credenciales WABA para '{tenant_key}'.")

    token = cuenta.get("access_token")
    phone_id = cuenta.get("phone_number_id")

    # =========================================================
    # 4. Enviar SIEMPRE mensaje simple
    # =========================================================
    texto_mensaje = (
        f"Hola {nombre} 😊\n"
        f"{nombre_agencia} te recuerda tu {nombre_evento} el día {fecha_str} a las {hora_inicio_str}.\n"
        f"🔗 Enlace: {link_final}\n"
        "Por favor confirma tu asistencia respondiendo este mensaje."
    )

    try:
        codigo, respuesta = enviar_mensaje_texto_simple(
            token=token,
            numero_id=phone_id,
            telefono_destino=telefono,
            texto=texto_mensaje
        )

        message_id_meta = None
        if isinstance(respuesta, dict) and respuesta.get("messages"):
            try:
                message_id_meta = respuesta["messages"][0].get("id")
            except Exception:
                message_id_meta = None

        guardar_mensaje_nuevo(
            telefono=telefono,
            contenido=texto_mensaje,
            direccion="enviado",
            tipo="text",
            message_id_meta=message_id_meta,
            estado="sent" if codigo and codigo < 300 else "error"
        )

        return {
            "status": "ok" if codigo and codigo < 300 else "error",
            "enviado_por": "mensaje_simple",
            "telefono": telefono,
            "cita_id": cita_id,
            "participante_tipo": participante_tipo,
            "message_id_meta": message_id_meta,
            "codigo_meta": codigo,
            "respuesta_api": respuesta if not (codigo and codigo < 300) else None
        }

    except Exception as e:
        logger.error(f"Error enviando recordatorio manual: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail="Error interno enviando el recordatorio."
        )

def enviar_mensaje_interactivo(token: str, phone_number_id: str, numero_destino: str, texto: str, botones: list):
    """
    Envía un mensaje interactivo de WhatsApp con botones (Quick Replies).
    OJO: Meta permite un MÁXIMO de 3 botones por mensaje.

    Args:
        token: Access token de la API de Meta.
        phone_number_id: ID del número de teléfono remitente.
        numero_destino: Número de teléfono del destinatario con código de país.
        texto: El cuerpo del mensaje.
        botones: Lista de diccionarios con la estructura de botones de Meta.
    """

    # Validamos el límite estricto de Meta
    if len(botones) > 3:
        raise ValueError("WhatsApp Cloud API solo permite un máximo de 3 botones interactivos por mensaje.")

    # Asegúrate de usar la versión de la API que manejes (v17.0, v18.0, etc.)
    # Si no estás seguro, v18.0 es muy estable en este momento.
    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Estructura obligatoria para mensajes interactivos de tipo 'button'
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": numero_destino,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": texto
            },
            "action": {
                "buttons": botones
            }
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)

        # Si la API de Meta devuelve un error (400, 401, 403, etc.)
        if response.status_code >= 400:
            logger.error(f"❌ Error de Meta API al enviar interactivo: {response.text}")
            response.raise_for_status()

        logger.info(f"✅ Mensaje interactivo enviado a {numero_destino}")
        return response.json()

    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Falla de conexión enviando mensaje interactivo a {numero_destino}: {e}")
        raise e

# Endpoints deshabilitados (cleanup frontend)
# - GET /api/eventosV01/{evento_id}
# - PUT /api/eventosV01/{evento_id}
# - POST /api/eventosV01
# - POST /api/eventosV00
# - POST /api/agendamientos/aspirante/enviarV0
# - POST /api/agendamientos/aspirante/enviarV1
# - POST /api/agendamientos/aspirante/enviar/tokenV1
# - POST /api/aspirantes/no_apto/enviarV0
# - POST /api/aspirantes/invitacion/enviarV0
# - GET /api/agendamientos/aspirante/token-info
# - PATCH /api/agendamientos/{agendamiento_id}/estado
# - POST /api/agendamientosV01/{agendamiento_id}/recordatorio

