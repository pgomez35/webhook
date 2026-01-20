import os
import traceback
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Literal
from uuid import uuid4

import pytz
import secrets
import string

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from psycopg2.extras import RealDictCursor

from DataBase import get_connection_context, obtener_cuenta_por_subdominio
from enviar_msg_wp import enviar_plantilla_generica_parametros
from main_webhook import validar_link_tiktok, enviar_mensaje
from schemas import *
from main_auth import obtener_usuario_actual

# Configurar logger
from tenant import current_tenant

logger = logging.getLogger(__name__)

router = APIRouter()   # ← ESTE ES EL ROUTER QUE VAS A IMPORTAR EN main.py

# router_agendamientos_aspirante = APIRouter()

class AgendamientoAspiranteIn(BaseModel):
    titulo: str
    descripcion: Optional[str] = None
    inicio: datetime            # "2025-11-30T09:30:00" (hora local del aspirante)
    fin: datetime               # "2025-11-30T10:40:00"
    timezone: Optional[str] = None  # "America/Santiago", etc.
    aspirante_nombre: Optional[str] = None
    aspirante_email: Optional[str] = None
    token: str                  # 👈 viene en el body, generado antes


# class AgendamientoAspiranteIn(BaseModel):
#     titulo: str
#     descripcion: Optional[str] = None
#     inicio: datetime            # "2025-11-22T16:30:00"
#     fin: datetime               # "2025-11-22T17:40:00"
#     creador_id: int             # viene de cid=123 en el link
#     responsable_id: int         # viene de /agendar/6
#     aspirante_nombre: str       # lo escribe en el formulario React
#     aspirante_email: EmailStr   # lo escribe en el formulario React
#     timezone: Optional[str] = "America/Bogota"  # value del select, ej: "America/Bogota"


# @router.post("/api/agendamientos/aspirante", response_model=EventoOut)
# def crear_agendamiento_aspirante(
#     data: AgendamientoAspiranteIn,
# ):
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         try:
#             # 1️⃣ Validar fechas
#             if data.fin <= data.inicio:
#                 raise HTTPException(
#                     status_code=400,
#                     detail="La fecha de fin debe ser posterior a la fecha de inicio."
#                 )
#
#             # 2️⃣ Validar responsable
#             if not data.responsable_id:
#                 raise HTTPException(
#                     status_code=400,
#                     detail="responsable_id es obligatorio para crear el agendamiento."
#                 )
#             responsable_id = data.responsable_id
#
#             # 3️⃣ Verificar que el aspirante (creador_id) existe
#             cur.execute(
#                 """
#                 SELECT
#                     id,
#                     COALESCE(NULLIF(nombre_real, ''), nickname) AS nombre,
#                     nickname
#                 FROM creadores
#                 WHERE id = %s
#                 """,
#                 (data.creador_id,)
#             )
#             row = cur.fetchone()
#             if not row:
#                 raise HTTPException(
#                     status_code=404,
#                     detail="El aspirante (creador_id) no existe en la tabla creadores."
#                 )
#
#             aspirante_id = row[0]
#             aspirante_nombre_db = row[1]
#             aspirante_nickname = row[2]
#
#
#             # 4️⃣ Actualizar zona horaria en perfil_creador (si se envía)
#             if data.timezone:
#                 cur.execute(
#                     """
#                     UPDATE perfil_creador
#                     SET zona_horaria = %s
#                     WHERE creador_id = %s
#                     """,
#                     (data.timezone, aspirante_id)
#                 )
#
#             # (Opcional) también podrías actualizar email/nombre si quieres:
#             # cur.execute(
#             #     """
#             #     UPDATE creadores
#             #     SET email = COALESCE(NULLIF(%s, ''), email),
#             #         nombre_real = COALESCE(NULLIF(%s, ''), nombre_real)
#             #     WHERE id = %s
#             #     """,
#             #     (data.aspirante_email, data.aspirante_nombre, aspirante_id)
#             # )
#
#             # 5️⃣ Crear agendamiento principal (interno, sin Google)
#
#             # ---- Convertir inicio ----
#             naive_inicio = datetime.fromisoformat(data.inicio)  # sin zona horaria
#             tz = pytz.timezone(data.timezone)
#             inicio_local = tz.localize(naive_inicio)
#             inicio_utc = inicio_local.astimezone(pytz.utc)
#             fecha_inicio = inicio_utc.replace(tzinfo=None)
#
#             # ---- Convertir fin ----
#             naive_fin = datetime.fromisoformat(data.fin)
#             fin_local = tz.localize(naive_fin)
#             fin_utc = fin_local.astimezone(pytz.utc)
#             fecha_fin = fin_utc.replace(tzinfo=None)
#
#
#
#             cur.execute(
#                 """
#                 INSERT INTO agendamientos (
#                     titulo,
#                     descripcion,
#                     fecha_inicio,
#                     fecha_fin,
#                     creador_id,
#                     responsable_id,
#                     estado,
#                     link_meet,
#                     google_event_id
#                 )
#                 VALUES (%s, %s, %s, %s, %s, %s, 'programado', NULL, NULL)
#                 RETURNING id
#                 """,
#                 (
#                     data.titulo,
#                     data.descripcion,
#                     data.inicio,
#                     data.fin,
#                     aspirante_id,
#                     responsable_id,
#                 )
#             )
#             agendamiento_id = cur.fetchone()[0]
#
#             # 6️⃣ Insertar participante (el propio aspirante)
#             cur.execute(
#                 """
#                 INSERT INTO agendamientos_participantes (agendamiento_id, creador_id)
#                 VALUES (%s, %s)
#                 """,
#                 (agendamiento_id, aspirante_id)
#             )
#
#             # 7️⃣ Construir respuesta tipo EventoOut
#             participante = {
#                 "id": aspirante_id,
#                 "nombre": aspirante_nombre_db,
#                 "nickname": aspirante_nickname,
#             }
#
#             return EventoOut(
#                 id=str(agendamiento_id),
#                 titulo=data.titulo,
#                 descripcion=data.descripcion,
#                 inicio=data.inicio,
#                 fin=data.fin,
#                 creador_id=aspirante_id,
#                 participantes_ids=[aspirante_id],
#                 participantes=[participante],
#                 responsable_id=responsable_id,
#                 estado="programado",
#                 link_meet=None,
#                 origen="interno",
#                 google_event_id=None,
#             )
#
#         except HTTPException:
#             raise
#         except Exception as e:
#             logger.error(f"❌ Error creando agendamiento de aspirante: {e}")
#             logger.error(traceback.format_exc())
#             raise HTTPException(
#                 status_code=500,
#                 detail="Error interno al crear agendamiento de aspirante."
#             )

from datetime import datetime
import pytz
from fastapi import APIRouter, HTTPException
import traceback


#
# @router.post("/api/agendamientos/aspirante", response_model=EventoOut)
# def crear_agendamiento_aspirante(
#     data: AgendamientoAspiranteIn,
# ):
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         try:
#             # 1️⃣ Validar fechas
#             if data.fin <= data.inicio:
#                 raise HTTPException(
#                     status_code=400,
#                     detail="La fecha de fin debe ser posterior a la fecha de inicio."
#                 )
#
#             # 2️⃣ Validar responsable
#             if not data.responsable_id:
#                 raise HTTPException(
#                     status_code=400,
#                     detail="responsable_id es obligatorio para crear el agendamiento."
#                 )
#             responsable_id = data.responsable_id
#
#             # 2.1️⃣ Validar timezone
#             if not data.timezone:
#                 raise HTTPException(
#                     status_code=400,
#                     detail="timezone es obligatorio para crear el agendamiento."
#                 )
#
#             # 3️⃣ Verificar que el aspirante (creador_id) existe
#             cur.execute(
#                 """
#                 SELECT
#                     id,
#                     COALESCE(NULLIF(nombre_real, ''), nickname) AS nombre,
#                     nickname
#                 FROM creadores
#                 WHERE id = %s
#                 """,
#                 (data.creador_id,)
#             )
#             row = cur.fetchone()
#             if not row:
#                 raise HTTPException(
#                     status_code=404,
#                     detail="El aspirante (creador_id) no existe en la tabla creadores."
#                 )
#
#             aspirante_id = row[0]
#             aspirante_nombre_db = row[1]
#             aspirante_nickname = row[2]
#
#             # 4️⃣ Actualizar zona horaria en perfil_creador (si se envía)
#             if data.timezone:
#                 cur.execute(
#                     """
#                     UPDATE perfil_creador
#                     SET zona_horaria = %s
#                     WHERE creador_id = %s
#                     """,
#                     (data.timezone, aspirante_id)
#                 )
#
#             # 5️⃣ Convertir inicio/fin desde zona del aspirante a UTC
#             tz = pytz.timezone(data.timezone)
#
#             # data.inicio y data.fin ya vienen como datetime (naive)
#             if isinstance(data.inicio, datetime):
#                 naive_inicio = data.inicio.replace(tzinfo=None)
#             else:
#                 naive_inicio = datetime.fromisoformat(data.inicio)
#
#             if isinstance(data.fin, datetime):
#                 naive_fin = data.fin.replace(tzinfo=None)
#             else:
#                 naive_fin = datetime.fromisoformat(data.fin)
#
#             inicio_local = tz.localize(naive_inicio)
#             fin_local = tz.localize(naive_fin)
#
#             inicio_utc = inicio_local.astimezone(pytz.utc)
#             fin_utc = fin_local.astimezone(pytz.utc)
#
#             # 👇 Lo que se guarda en BD (sin tz, en UTC)
#             fecha_inicio = inicio_utc.replace(tzinfo=None)
#             fecha_fin = fin_utc.replace(tzinfo=None)
#
#             # 6️⃣ Crear agendamiento principal (interno, sin Google)
#             cur.execute(
#                 """
#                 INSERT INTO agendamientos (
#                     titulo,
#                     descripcion,
#                     fecha_inicio,
#                     fecha_fin,
#                     creador_id,
#                     responsable_id,
#                     estado,
#                     link_meet,
#                     google_event_id
#                 )
#                 VALUES (%s, %s, %s, %s, %s, %s, 'programado', NULL, NULL)
#                 RETURNING id
#                 """,
#                 (
#                     data.titulo,
#                     data.descripcion,
#                     fecha_inicio,      # 👈 AHORA USAMOS fecha_inicio UTC
#                     fecha_fin,         # 👈 Y fecha_fin UTC
#                     aspirante_id,
#                     responsable_id,
#                 )
#             )
#             agendamiento_id = cur.fetchone()[0]
#
#             # 7️⃣ Insertar participante (el propio aspirante)
#             cur.execute(
#                 """
#                 INSERT INTO agendamientos_participantes (agendamiento_id, creador_id)
#                 VALUES (%s, %s)
#                 """,
#                 (agendamiento_id, aspirante_id)
#             )
#
#             # 8️⃣ Construir respuesta tipo EventoOut
#             participante = {
#                 "id": aspirante_id,
#                 "nombre": aspirante_nombre_db,
#                 "nickname": aspirante_nickname,
#             }
#
#             # En la respuesta puedes mandar las horas en UTC (fecha_inicio/fecha_fin)
#             # o las originales locales (data.inicio/data.fin). Aquí dejo las locales:
#             return EventoOut(
#                 id=str(agendamiento_id),
#                 titulo=data.titulo,
#                 descripcion=data.descripcion,
#                 inicio=data.inicio,      # local (lo que escogió el aspirante)
#                 fin=data.fin,            # local
#                 creador_id=aspirante_id,
#                 participantes_ids=[aspirante_id],
#                 participantes=[participante],
#                 responsable_id=responsable_id,
#                 estado="programado",
#                 link_meet=None,
#                 origen="interno",
#                 google_event_id=None,
#             )
#
#         except HTTPException:
#             raise
#         except Exception as e:
#             logger.error(f"❌ Error creando agendamiento de aspirante: {e}")
#             logger.error(traceback.format_exc())
#             raise HTTPException(
#                 status_code=500,
#                 detail="Error interno al crear agendamiento de aspirante."
#             )


@router.get("/api/eventos/{evento_id}", response_model=EventoOut)
def obtener_evento(evento_id: str):
    """
    Obtiene un evento desde la BD interna.

    - Si evento_id es numérico: busca por agendamientos.id
    - Si es texto (UUID, hash): busca por google_event_id
    """
    with get_connection_context() as conn:
        cur = conn.cursor()

        try:
            # ---------------------------------------------------------
            # 1️⃣ Identificar si el evento_id es interno o de Google
            # ---------------------------------------------------------
            if evento_id.isdigit():
                # Buscar por ID interno
                cur.execute("SELECT * FROM agendamientos WHERE id = %s", (int(evento_id),))
            else:
                # Buscar por google_event_id
                cur.execute("SELECT * FROM agendamientos WHERE google_event_id = %s", (evento_id,))

            ag = cur.fetchone()

            if not ag:
                raise HTTPException(status_code=404, detail="Evento no encontrado.")

            (
                ag_id,
                titulo,
                descripcion,
                fecha_inicio,
                fecha_fin,
                creador_id,
                responsable_id,
                estado,
                link_meet,
                google_event_id,
                creado_en,
                actualizado_en
            ) = ag

            # ---------------------------------------------------------
            # 2️⃣ Cargar participantes desde agendamientos_participantes
            # ---------------------------------------------------------
            cur.execute("""
                SELECT c.id, 
                       COALESCE(NULLIF(c.nombre_real, ''), c.nickname) AS nombre,
                       c.nickname
                FROM agendamientos_participantes ap
                JOIN creadores c ON c.id = ap.creador_id
                WHERE ap.agendamiento_id = %s
            """, (ag_id,))

            participantes = cur.fetchall()

            participantes_ids = [row[0] for row in participantes]
            participantes_out = [
                {
                    "id": row[0],
                    "nombre": row[1],
                    "nickname": row[2]
                }
                for row in participantes
            ]

            # ---------------------------------------------------------
            # 3️⃣ Crear ID expuesto al usuario
            # ---------------------------------------------------------
            # Si tiene google_event_id → ese es el ID usado antes
            # Si no, se usa el ID interno como string
            public_id = google_event_id if google_event_id else str(ag_id)

            # ---------------------------------------------------------
            # 4️⃣ Origen del evento (solo informativo)
            # ---------------------------------------------------------
            origen = "google_calendar" if google_event_id else "interno"

            # ---------------------------------------------------------
            # 5️⃣ Construir respuesta
            # ---------------------------------------------------------
            return EventoOut(
                id=public_id,
                titulo=titulo or "Sin título",
                descripcion=descripcion or "",
                inicio=fecha_inicio,
                fin=fecha_fin,
                participantes=participantes_out,
                participantes_ids=participantes_ids,
                link_meet=link_meet,
                responsable_id=responsable_id,
                origen=origen
            )

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"❌ Error al obtener evento {evento_id}: {e}")
            logger.error(traceback.format_exc())
            raise HTTPException(status_code=500, detail="Error interno al obtener el evento.")


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

            # 2️⃣ Buscar el agendamiento en BD
            #    - Si evento_id es numérico → buscar por id interno
            #    - Si no → buscar por google_event_id
            if evento_id.isdigit():
                cur.execute(
                    """
                    SELECT id, titulo, descripcion, fecha_inicio, fecha_fin,
                           creador_id, responsable_id, estado, link_meet, google_event_id
                    FROM agendamientos
                    WHERE id = %s
                    """,
                    (int(evento_id),)
                )
            else:
                cur.execute(
                    """
                    SELECT id, titulo, descripcion, fecha_inicio, fecha_fin,
                           creador_id, responsable_id, estado, link_meet, google_event_id
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
                _creador_id,
                responsable_id,
                estado,
                link_meet_actual,
                google_event_id
            ) = row

            # 3️⃣ Determinar nuevo link_meet (si tu EventoIn lo incluye como campo opcional)
            #    Si no existe en el modelo, simplemente deja esta línea como:
            #    nuevo_link_meet = link_meet_actual
            nuevo_link_meet = getattr(evento, "link_meet", link_meet_actual)

            # 4️⃣ Actualizar el agendamiento en BD
            cur.execute(
                """
                UPDATE agendamientos
                SET fecha_inicio = %s,
                    fecha_fin = %s,
                    titulo = %s,
                    descripcion = %s,
                    link_meet = %s,
                    actualizado_en = NOW()
                WHERE id = %s
                """,
                (
                    evento.inicio,
                    evento.fin,
                    evento.titulo,
                    evento.descripcion,
                    nuevo_link_meet,
                    ag_id,
                )
            )

            # 5️⃣ Actualizar participantes (tablas agendamientos_participantes)
            cur.execute(
                "DELETE FROM agendamientos_participantes WHERE agendamiento_id = %s",
                (ag_id,)
            )

            for participante_id in evento.participantes_ids:
                cur.execute(
                    """
                    INSERT INTO agendamientos_participantes (agendamiento_id, creador_id)
                    VALUES (%s, %s)
                    """,
                    (ag_id, participante_id)
                )

            # 6️⃣ Consultar datos de participantes para la respuesta
            participantes = []
            if evento.participantes_ids:
                cur.execute(
                    """
                    SELECT
                        id,
                        COALESCE(NULLIF(nombre_real, ''), nickname) AS nombre,
                        nickname
                    FROM creadores
                    WHERE id = ANY(%s)
                    """,
                    (evento.participantes_ids,)
                )
                participantes = [
                    {"id": row[0], "nombre": row[1], "nickname": row[2]}
                    for row in cur.fetchall()
                ]

            # 7️⃣ Determinar ID público y origen (solo informativo)
            public_id = google_event_id if google_event_id else str(ag_id)
            origen = "google_calendar" if google_event_id else "interno"

            # 8️⃣ Respuesta final
            return EventoOut(
                id=public_id,
                titulo=evento.titulo,
                descripcion=evento.descripcion,
                inicio=evento.inicio,
                fin=evento.fin,
                participantes_ids=evento.participantes_ids,
                participantes=participantes,
                link_meet=nuevo_link_meet,
                responsable_id=responsable_id,
                origen=origen,
            )

        except HTTPException:
            # Errores ya controlados
            raise
        except Exception as e:
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
    with get_connection_context() as conn:
        cur = conn.cursor()

        try:
            # 1️⃣ Validación básica
            if evento.fin <= evento.inicio:
                raise HTTPException(
                    status_code=400,
                    detail="La fecha de fin debe ser posterior a la fecha de inicio."
                )

            # 2️⃣ Crear agendamiento interno
            cur.execute("""
            INSERT INTO agendamientos (
                titulo,
                descripcion,
                fecha_inicio,
                fecha_fin,
                link_meet,
                estado,
                responsable_id,
                google_event_id
            ) VALUES (%s, %s, %s, %s, %s, 'programado', %s, NULL)
            RETURNING id
        """, (
            evento.titulo,
            evento.descripcion,
            evento.inicio,
            evento.fin,
            evento.link_meet if hasattr(evento, "link_meet") else None,
            usuario_actual["id"],
        ))

            agendamiento_id = cur.fetchone()[0]

            # 3️⃣ Insertar participantes
            for participante_id in evento.participantes_ids:
                cur.execute("""
                    INSERT INTO agendamientos_participantes (agendamiento_id, creador_id)
                    VALUES (%s, %s)
                """, (agendamiento_id, participante_id))

            # 4️⃣ Consultar datos de participantes
            participantes = []
            if evento.participantes_ids:
                cur.execute("""
                    SELECT id,
                           COALESCE(NULLIF(nombre_real, ''), nickname) AS nombre,
                           nickname
                    FROM creadores
                    WHERE id = ANY(%s)
                """, (evento.participantes_ids,))
                participantes = [
                    {
                        "id": row[0],
                        "nombre": row[1],
                        "nickname": row[2]
                    }
                    for row in cur.fetchall()
                ]

            # 5️⃣ Construir ID expuesto (para coherencia con otros endpoints)
            public_id = str(agendamiento_id)

            return EventoOut(
                id=public_id,
                titulo=evento.titulo,
                descripcion=evento.descripcion,
                inicio=evento.inicio,
                fin=evento.fin,
                participantes_ids=evento.participantes_ids,
                participantes=participantes,
                link_meet=evento.link_meet if hasattr(evento, "link_meet") else None,
                responsable_id=usuario_actual["id"],
                origen="interno"
            )

        except Exception as e:
            logger.error(f"❌ Error creando evento: {e}")
            logger.error(traceback.format_exc())
            raise HTTPException(status_code=500, detail="Error creando evento.")

@router.get("/api/agendamientos")
def listar_agendamientos():
    try:
        with get_connection_context() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Obtener agendamientos con nombre del responsable
            cur.execute("""
            SELECT 
                a.id, a.titulo, a.descripcion, a.fecha_inicio, a.fecha_fin,
                a.estado, a.link_meet,
                u.nombre_completo AS responsable
            FROM agendamientos a
            LEFT JOIN admin_usuario u ON u.id = a.responsable_id
                ORDER BY a.fecha_inicio DESC;
            """)
            agendamientos = cur.fetchall()

            # Para cada agendamiento, obtener los participantes (nombre, nickname)
            for evento in agendamientos:
                cur.execute("""
                    SELECT c.id, c.nombre_real as nombre, c.nickname
                    FROM agendamientos_participantes ap
                    JOIN creadores c ON c.id = ap.creador_id
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
      - agendamientos (evento principal)
      - agendamientos_participantes (asistentes)
      - creadores (datos de personas)

    Ya NO consulta Google Calendar directamente.
    Si el agendamiento tiene google_event_id, se marca origen="google_calendar",
    de lo contrario origen="interno".
    """

    # ✅ Rango por defecto: 30 días atrás y 30 adelante (como antes)
    if time_min is None:
        time_min = datetime.utcnow() - timedelta(days=30)
    if time_max is None:
        time_max = datetime.utcnow() + timedelta(days=30)

    try:
        with get_connection_context() as conn:
            cur = conn.cursor()

            # 🔍 Traer eventos + participantes en un solo query
            # - Un agendamiento puede aparecer en varias filas (una por participante)
            # - Luego agregamos en Python
            sql = """
            SELECT
                a.id AS ag_id,
                a.titulo,
                a.descripcion,
                a.fecha_inicio,
                a.fecha_fin,
                a.responsable_id,
                a.estado,
                a.link_meet,
                a.google_event_id,
                c.id AS creador_id,
                COALESCE(NULLIF(c.nombre_real, ''), c.nickname) AS nombre,
                c.nickname
            FROM agendamientos a
            LEFT JOIN agendamientos_participantes ap
                   ON ap.agendamiento_id = a.id
            LEFT JOIN creadores c
                   ON c.id = ap.creador_id
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

            # 🧩 Agregar por agendamiento_id
            eventos_map: Dict[int, Dict] = {}

            for (
                ag_id,
                titulo,
                descripcion,
                fecha_inicio,
                fecha_fin,
                responsable_id,
                estado,
                link_meet,
                google_event_id,
                creador_id,
                nombre,
                nickname,
            ) in rows:
                if ag_id not in eventos_map:
                    # Definir ID expuesto:
                    # - Si tiene google_event_id -> es el mismo que usabas antes
                    # - Si no, usamos el id interno como string
                    if google_event_id:
                        public_id = google_event_id
                        origen = "google_calendar"
                    else:
                        public_id = str(ag_id)
                        origen = "interno"

                    eventos_map[ag_id] = {
                        "public_id": public_id,
                        "titulo": titulo or "Sin título",
                        "descripcion": descripcion or "",
                        "inicio": fecha_inicio,
                        "fin": fecha_fin,
                        "responsable_id": responsable_id,
                        "estado": estado,
                        "link_meet": link_meet,
                        "google_event_id": google_event_id,
                        "origen": origen,
                        "participantes": [],
                        "participantes_ids": set(),  # usamos set para evitar duplicados
                    }

                # Agregar participante si existe
                if creador_id is not None:
                    ev = eventos_map[ag_id]
                    if creador_id not in ev["participantes_ids"]:
                        ev["participantes_ids"].add(creador_id)
                        ev["participantes"].append(
                            {
                                "id": creador_id,
                                "nombre": nombre,
                                "nickname": nickname,
                            }
                        )

            # 📦 Convertir a lista de EventoOut
            resultado: List[EventoOut] = []
            for ag_id, ev in eventos_map.items():
                resultado.append(
                    EventoOut(
                        id=ev["public_id"],
                        titulo=ev["titulo"],
                        descripcion=ev["descripcion"],
                        inicio=ev["inicio"],
                        fin=ev["fin"],
                        participantes_ids=list(ev["participantes_ids"]),
                        participantes=ev["participantes"],
                        link_meet=ev["link_meet"],
                        responsable_id=ev["responsable_id"],
                        origen=ev["origen"],
                    )
                )

            logger.info(f"✅ Se obtuvieron {len(resultado)} agendamientos desde BD")
            return resultado

    except Exception as e:
        logger.error(f"❌ Error al obtener eventos desde BD: {e}")
        logger.error(traceback.format_exc())
        raise

# schemas
class TimeZoneOut(BaseModel):
    creador_id: int
    zona_horaria: Optional[str] = None

@router.get("/api/creadores/{creador_id}/timezone", response_model=TimeZoneOut)
def obtener_timezone_creador(creador_id: int):
    with get_connection_context() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT zona_horaria
                FROM perfil_creador
                WHERE creador_id = %s
                """,
                (creador_id,)
            )
            row = cur.fetchone()
            if not row:
                # existe el creador, pero puede que no tenga perfil_creador, tú ya dijiste que sí tiene,
                # igual por seguridad devolvemos zona_horaria = None
                return TimeZoneOut(creador_id=creador_id, zona_horaria=None)

            return TimeZoneOut(
                creador_id=creador_id,
                zona_horaria=row[0]
            )
        except Exception as e:
            logger.error(f"❌ Error obteniendo timezone del creador {creador_id}: {e}")
            logger.error(traceback.format_exc())
            raise HTTPException(
                status_code=500,
                detail="Error interno al obtener timezone del creador."
            )

from pydantic import BaseModel, AnyUrl
from typing import Optional, List
from datetime import datetime, timedelta
import secrets
import pytz


# ----------
# ------EDITAR AGENDAMIENTO MOBILE
# ----------



import os
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
    creador_id: int
    responsable_id: int
    zona_horaria: Optional[str] = None
    nombre_mostrable: Optional[str] = None
    duracion_minutos: Optional[int] = None

class CrearLinkAgendamientoIn(BaseModel):
    creador_id: int
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
                    id,
                    titulo,
                    descripcion,
                    fecha_inicio,
                    fecha_fin,
                    creador_id,
                    responsable_id,
                    estado,
                    link_meet,
                    tipo_agendamiento
                FROM agendamientos
                WHERE id = %s
                """,
                (agendamiento_id,)
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
                creador_id,
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
            # if tipo_agendamiento != "ENTREVISTA":
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

            # 6️⃣ Respuesta
            return EventoOut(
                id=str(ag_id),
                titulo=titulo_actual,
                descripcion=descripcion_actual,
                inicio=nuevo_inicio,
                fin=nuevo_fin,
                creador_id=creador_id,
                responsable_id=responsable_id,
                estado=estado,
                link_meet=link_meet_actual if tipo_agendamiento == "ENTREVISTA" else None,
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


from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional


class CitaAspiranteOut(BaseModel):
    id: int
    fecha_inicio: str
    fecha_fin: str
    duracion_minutos: int
    tipo_agendamiento: str
    realizada: bool
    link_meet: Optional[str] = None
    url_reagendar: Optional[str] = None


@router.get("/api/creadores/{creador_id}/citas", response_model=list[CitaAspiranteOut])
def listar_citas_creador(creador_id: int):
    citas: list[CitaAspiranteOut] = []

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    a.id,
                    a.fecha_inicio,
                    a.fecha_fin,
                    a.estado,
                    COALESCE(a.tipo_agendamiento, 'ENTREVISTA') AS tipo_agendamiento,
                    a.link_meet
                FROM agendamientos a
                JOIN agendamientos_participantes ap
                  ON ap.agendamiento_id = a.id
                WHERE ap.creador_id = %s
                ORDER BY a.fecha_inicio ASC
                """,
                (creador_id,)
            )
            rows = cur.fetchall()

    for a_id, f_ini, f_fin, estado, tipo_agendamiento, link_meet in rows:
        duracion_min = int((f_fin - f_ini).total_seconds() // 60)
        realizada = (estado == "realizada")

        citas.append(
            CitaAspiranteOut(
                id=a_id,
                fecha_inicio=f_ini.isoformat(),
                fecha_fin=f_fin.isoformat(),
                duracion_minutos=duracion_min,
                tipo_agendamiento=tipo_agendamiento.upper(),
                realizada=realizada,
                link_meet=link_meet,
                url_reagendar=None,
            )
        )

    return citas



@router.get("/api/aspirantes/citasV1Token", response_model=List[CitaAspiranteOut])
def listar_citas_aspiranteV1Token(token: str = Query(...)):
    # 1️⃣ Resolver token correctamente
    info_token = resolver_creador_por_token(token)
    if not info_token:
        raise HTTPException(status_code=404, detail="Aspirante no encontrado")

    creador_id = info_token["creador_id"]  # 👈 ESTE es el INT que necesita SQL
    responsable_id = info_token.get("responsable_id")

    citas: list[CitaAspiranteOut] = []

    # 2️⃣ Consulta SQL usando el ID correcto
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    a.id,
                    a.fecha_inicio,
                    a.fecha_fin,
                    a.estado,
                    COALESCE(a.tipo_agendamiento, 'ENTREVISTA') AS tipo_agendamiento,
                    a.link_meet
                FROM agendamientos a
                JOIN agendamientos_participantes ap
                  ON ap.agendamiento_id = a.id
                WHERE ap.creador_id = %s
                ORDER BY a.fecha_inicio ASC
                """,
                (creador_id,)  # 👈 ahora sí funciona
            )
            rows = cur.fetchall()

    # 3️⃣ Construcción del response
    for r in rows:
        a_id, f_ini, f_fin, estado, tipo_agendamiento, link_meet = r
        duracion_min = int((f_fin - f_ini).total_seconds() // 60)
        realizada = (estado == "realizada")

        citas.append(
            CitaAspiranteOut(
                id=a_id,
                fecha_inicio=f_ini.isoformat(),
                fecha_fin=f_fin.isoformat(),
                duracion_minutos=duracion_min,
                tipo_agendamiento=tipo_agendamiento.upper(),
                realizada=realizada,
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
    # 1️⃣ Resolver token → devuelve dict con creador_id y responsable_id
    info_token = resolver_creador_por_token(payload.token)
    if not info_token:
        raise HTTPException(status_code=404, detail="Aspirante no encontrado")

    creador_id = info_token["creador_id"]

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
                  AND ap.creador_id = %s
                """,
                (payload.agendamiento_id, creador_id)
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




from typing import Optional, Dict
from datetime import datetime, timezone


def resolver_creador_por_token(token: str) -> Optional[Dict]:
    """
    Resuelve un token público de acceso para aspirantes.

    Tabla usada: link_agendamiento_tokens
    Campos:
      - token: str
      - creador_id: int
      - responsable_id: int (opcional)
      - expiracion: timestamp
      - usado: bool

    Devuelve:
        {
            "creador_id": int,
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
                    SELECT token, creador_id, responsable_id, expiracion, usado
                    FROM link_agendamiento_tokens
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
            creador_id,
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
            "creador_id": creador_id,
            "responsable_id": responsable_id
        }

    except Exception as e:
        print(f"❌ Error en resolver_creador_por_token: {e}")
        return None


# --------------------------------
# --------------------------------
# --------------------------------

from datetime import datetime
from fastapi import Depends, HTTPException
import logging

logger = logging.getLogger(__name__)

@router.post("/api/agendamientos/aspirante/enviar", response_model=LinkAgendamientoOut)
def enviar_link_agendamiento_aspirante(
    data: CrearLinkAgendamientoIn,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    """
    Envía un link de agendamiento usando creador_id (sin token).
    Actualiza estado del perfil y envía mensaje por WhatsApp.
    """

    with get_connection_context() as conn:
        cur = conn.cursor()

        # 1) Obtener datos del aspirante
        cur.execute(
            """
            SELECT COALESCE(nickname, nombre_real) AS nombre, telefono
            FROM creadores
            WHERE id = %s
            """,
            (data.creador_id,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "El aspirante no existe.")

        nombre_creador, telefono = row
        if not telefono:
            raise HTTPException(400, "El aspirante no tiene teléfono registrado.")

        # 2) Actualizar estado según tipo_agendamiento
        nuevo_estado_id = None
        if data.tipo_agendamiento == "ENTREVISTA":
            nuevo_estado_id = 8
        elif data.tipo_agendamiento == "LIVE":
            nuevo_estado_id = 5

        if nuevo_estado_id:
            cur.execute(
                """
                UPDATE perfil_creador
                SET id_chatbot_estado = %s,
                    actualizado_en    = NOW()
                WHERE creador_id = %s
                """,
                (nuevo_estado_id, data.creador_id)
            )

        conn.commit()

    # 3) Construir URL del agendador (sin token)
    tenant_key = current_tenant.get() or "test"
    subdominio = tenant_key if tenant_key != "public" else "test"

    # ✅ Pasamos creador_id y también tipo/duración por query (para que el agendador no pierda info)
    url = (
        f"https://{subdominio}.talentum-manager.com/agendar"
        f"?creador_id={data.creador_id}"
        f"&tipo={data.tipo_agendamiento}"
        f"&duracion={data.duracion_minutos}"
        f"&responsable_id={data.responsable_id}"
    )

    # 4) Texto del mensaje según tipo de agendamiento
    titulo_cita = "tu prueba TikTok LIVE" if data.tipo_agendamiento == "LIVE" else "tu entrevista con un asesor"

    mensaje = (
        f"Hola {nombre_creador} 👋\n\n"
        "Queremos continuar tu proceso en la agencia.\n\n"
        f"📅 Agenda {titulo_cita} aquí:\n"
        f"{url}\n\n"
        f"⏱️ Duración estimada: {data.duracion_minutos} minutos.\n"
        "Selecciona el horario que prefieras. Si necesitas cambiar la cita, contáctanos."
    )

    # 5) Enviar WhatsApp
    try:
        enviar_mensaje(telefono, mensaje)
    except Exception as e:
        logger.exception(
            "Fallo al enviar mensaje de agendamiento para creador_id=%s: %s",
            data.creador_id, e
        )

    # 6) Respuesta API (ya no hay token ni expiración real)
    return LinkAgendamientoOut(
        token=None,         # si tu modelo no lo permite, ajusta el response_model
        url=url,
        expiracion=None,    # idem
    )




@router.post("/api/agendamientos/aspirante/enviar", response_model=LinkAgendamientoOut)
def enviar_link_agendamiento_aspirante(
    data: CrearLinkAgendamientoIn,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    """
    Envía un link de agendamiento usando creador_id (sin token).
    Actualiza estado del perfil y envía mensaje por WhatsApp.
    """

    with get_connection_context() as conn:
        cur = conn.cursor()

        # 1) Obtener datos del aspirante
        cur.execute(
            """
            SELECT COALESCE(nickname, nombre_real) AS nombre, telefono
            FROM creadores
            WHERE id = %s
            """,
            (data.creador_id,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "El aspirante no existe.")

        nombre_creador, telefono = row
        if not telefono:
            raise HTTPException(400, "El aspirante no tiene teléfono registrado.")

        # 2) Actualizar estado según tipo_agendamiento
        nuevo_estado_id = None
        if data.tipo_agendamiento == "ENTREVISTA":
            nuevo_estado_id = 8
        elif data.tipo_agendamiento == "LIVE":
            nuevo_estado_id = 5

        if nuevo_estado_id:
            cur.execute(
                """
                UPDATE perfil_creador
                SET id_chatbot_estado = %s,
                    actualizado_en    = NOW()
                WHERE creador_id = %s
                """,
                (nuevo_estado_id, data.creador_id)
            )

        conn.commit()

    # 3) Construir URL del agendador (sin token)
    tenant_key = current_tenant.get() or "test"
    subdominio = tenant_key if tenant_key != "public" else "test"

    # ✅ Pasamos creador_id y también tipo/duración por query (para que el agendador no pierda info)
    url = (
        f"https://{subdominio}.talentum-manager.com/agendar"
        f"?creador_id={data.creador_id}"
        f"&tipo={data.tipo_agendamiento}"
        f"&duracion={data.duracion_minutos}"
        f"&responsable_id={data.responsable_id}"
    )

    # 4) Texto del mensaje según tipo de agendamiento
    titulo_cita = "tu prueba TikTok LIVE" if data.tipo_agendamiento == "LIVE" else "tu entrevista con un asesor"

    mensaje = (
        f"Hola {nombre_creador} 👋\n\n"
        "Queremos continuar tu proceso en la agencia.\n\n"
        f"📅 Agenda {titulo_cita} aquí:\n"
        f"{url}\n\n"
        f"⏱️ Duración estimada: {data.duracion_minutos} minutos.\n"
        "Selecciona el horario que prefieras. Si necesitas cambiar la cita, contáctanos."
    )

    # 5) Enviar WhatsApp
    try:
        enviar_mensaje(telefono, mensaje)
    except Exception as e:
        logger.exception(
            "Fallo al enviar mensaje de agendamiento para creador_id=%s: %s",
            data.creador_id, e
        )

    # 6) Respuesta API (ya no hay token ni expiración real)
    return LinkAgendamientoOut(
        token=None,         # si tu modelo no lo permite, ajusta el response_model
        url=url,
        expiracion=None,    # idem
    )





def generar_token_corto(longitud=10):
    caracteres = string.ascii_letters + string.digits  # A-Z a-z 0-9
    return ''.join(secrets.choice(caracteres) for _ in range(longitud))

@router.post("/api/agendamientos/aspirante/enviar/tokenV1", response_model=LinkAgendamientoOut)
def crear_y_enviar_link_agendamiento_aspiranteTokenV1(
    data: CrearLinkAgendamientoIn,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    """
    Genera un link de agendamiento, guarda el token en link_agendamiento_tokens
    (incluyendo tipo de cita y duración) y envía el mensaje por WhatsApp.
    """

    # 1️⃣ Token para el link
    token = generar_token_corto(10)
    expiracion = datetime.utcnow() + timedelta(minutes=data.minutos_validez)

    with get_connection_context() as conn:
        cur = conn.cursor()

        # 2️⃣ Obtener datos del aspirante
        cur.execute(
            """
            SELECT COALESCE(nickname, nombre_real) AS nombre, telefono
            FROM creadores
            WHERE id = %s
            """,
            (data.creador_id,)
        )
        row = cur.fetchone()

        if not row:
            raise HTTPException(404, "El aspirante no existe.")

        nombre_creador, telefono = row

        if not telefono:
            raise HTTPException(400, "El aspirante no tiene teléfono registrado.")

        # 3️⃣ Guardar token con tipo_agendamiento y duracion_minutos
        cur.execute(
            """
            INSERT INTO link_agendamiento_tokens
            (token, creador_id, responsable_id, expiracion, usado, duracion_minutos, tipo_agendamiento)
            VALUES (%s, %s, %s, %s, FALSE, %s, %s)
            """,
            (
                token,
                data.creador_id,
                data.responsable_id,
                expiracion,
                data.duracion_minutos,
                data.tipo_agendamiento,   # "LIVE" o "ENTREVISTA"
            )
        )
        # =================================================================
        # 3.5 🔄 ACTUALIZAR ESTADO (Usando el mismo cursor 'cur')
        # =================================================================
        nuevo_estado_id = None
        if data.tipo_agendamiento == "ENTREVISTA":
            nuevo_estado_id = 8
        elif data.tipo_agendamiento == "LIVE":
            nuevo_estado_id = 5

        if nuevo_estado_id:
            # Ejecutamos el update DIRECTAMENTE aquí
            # Nota: Verifica si tu tabla es 'creadores' o 'test.perfil_creador'
            cur.execute(
                """
                UPDATE perfil_creador
                SET id_chatbot_estado = %s,
                    actualizado_en    = NOW()
                WHERE creador_id = %s
                """,
                (nuevo_estado_id, data.creador_id)
            )

        # ✅ COMMIT FINAL: Guarda el Token Y el Estado al mismo tiempo
        conn.commit()

    # 4️⃣ Construir URL del agendador
    tenant_key = current_tenant.get() or "test"
    subdominio = tenant_key if tenant_key != "public" else "test"
    url = f"https://{subdominio}.talentum-manager.com/agendar?token={token}"

    # 5️⃣ Obtener credenciales WABA
    cuenta = obtener_cuenta_por_subdominio(tenant_key)
    if not cuenta:
        raise HTTPException(500, f"No hay credenciales WABA para '{tenant_key}'.")

    access_token = cuenta.get("access_token")
    phone_id = cuenta.get("phone_number_id")

    if not access_token or not phone_id:
        raise HTTPException(500, f"Credenciales WABA incompletas para '{tenant_key}'.")

    # 6️⃣ Texto del mensaje según tipo de agendamiento
    if data.tipo_agendamiento == "LIVE":
        titulo_cita = "tu prueba TikTok LIVE"
    else:
        titulo_cita = "tu entrevista con un asesor"

    mensaje = (
        f"Hola {nombre_creador} 👋\n\n"
        "Queremos continuar tu proceso en la agencia.\n\n"
        f"📅 Agenda {titulo_cita} aquí:\n"
        f"{url}\n\n"
        f"⏱️ Duración estimada: {data.duracion_minutos} minutos.\n"
        "Selecciona el horario que prefieras. Si necesitas cambiar la cita, contáctanos."
    )

    # 7️⃣ Enviar plantilla WhatsApp (único intento)
    try:
        resp = enviar_mensaje(telefono, mensaje)
        # (puedes mantener tu lógica de logging de status_code)
    except Exception as e:
        logger.exception("Fallo al intentar enviar mensaje de agendamiento para token %s: %s", token, e)

    # 8️⃣ Respuesta API
    return LinkAgendamientoOut(
        token=token,
        url=url,
        expiracion=expiracion,
    )


class EnviarNoAptoIn(BaseModel):
    creador_id: int


@router.post("/api/aspirantes/no_apto/enviar")
def enviar_mensaje_no_apto(
        data: EnviarNoAptoIn,
        usuario_actual: dict = Depends(obtener_usuario_actual)
):
    """
    Envía mensaje de NO APTO usando SIEMPRE la plantilla.
    Evita errores por ventana de 24h.
    """

    with get_connection_context() as conn:
        cur = conn.cursor()

        # 1) Obtener datos del aspirante
        cur.execute("""
                    SELECT id,
                           COALESCE(nickname, nombre_real) AS nombre,
                           telefono
                    FROM creadores
                    WHERE id = %s;
        """, (data.creador_id,))
        row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Aspirante no encontrado.")

        creador_id, nombre, telefono = row

        if not telefono:
            raise HTTPException(status_code=400, detail="El aspirante no tiene número registrado.")

        # =========================================================
        # 1.5) NUEVO: Actualizar estado a 4 (NO APTO)
        # =========================================================
        cur.execute("""
                    UPDATE perfil_creador
                    SET id_chatbot_estado = 4
                    WHERE creador_id = %s;
                    """, (creador_id,))

        # ⚠️ CRÍTICO: Confirmar la transacción para guardar el cambio
        conn.commit()

    # =============================
    # 2) Preparar envío por plantilla
    # =============================
    subdominio = current_tenant.get()
    cuenta = obtener_cuenta_por_subdominio(subdominio)

    if not cuenta:
        raise HTTPException(
            status_code=500,
            detail=f"No hay credenciales WABA para el tenant '{subdominio}'."
        )

    token = cuenta["access_token"]
    phone_id = cuenta["phone_number_id"]
    business_name = (
        cuenta.get("business_name")
        or cuenta.get("nombre")
        or "nuestra agencia"
    )

    parametros = [
        nombre or "creador",
        business_name
    ]

    # =============================
    # 3) Enviar plantilla
    # =============================
    try:
        codigo, respuesta_api = enviar_plantilla_generica_parametros(
            token=token,
            phone_number_id=phone_id,
            numero_destino=telefono,
            nombre_plantilla="no_apto_proceso_v2",
            codigo_idioma="es_CO",
            parametros=parametros,  # [nombre, business_name]
            body_vars_count=2  # 👈 LOS 2 VAN AL BODY, SIN BOTÓN
        )

        return {
            "status": "ok" if codigo < 300 else "error",
            "tipo_envio": "plantilla",
            "codigo_meta": codigo,
            "respuesta_api": respuesta_api,
            "telefono": telefono
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error enviando plantilla: {str(e)}"
        )

# ===================================================
# 📌 CREAR AUTO AGENDAMIENTO ENTREVISTA EN LINK POR WHATSAPP
# ===================================================
from types import SimpleNamespace

@router.post("/api/agendamientos/aspirante", response_model=EventoOut)
def crear_agendamiento_aspirante(
    data: AgendamientoAspiranteIn,
):
    """
    Guarda una cita desde el link de agendamiento y:
    → Valida token
    → Crea agendamiento (usando duración y tipo del token)
    → Si es ENTREVISTA, crea evento en Google Calendar con Meet
    → Obtiene o crea entrevista
    → Inserta en entrevista_agendamiento
    """

    with get_connection_context() as conn:
        cur = conn.cursor()

        try:
            # 1️⃣ Validar token + leer duración y tipo
            cur.execute(
                """
                SELECT 
                    token, 
                    creador_id, 
                    responsable_id, 
                    expiracion, 
                    usado,
                    duracion_minutos,
                    tipo_agendamiento
                FROM link_agendamiento_tokens
                WHERE token = %s
                """,
                (data.token,)
            )
            row = cur.fetchone()

            if not row:
                raise HTTPException(404, "Token no válido.")

            (
                token,
                creador_id,
                responsable_id,
                expiracion,
                usado,
                duracion_minutos_token,
                tipo_agendamiento_token,
            ) = row

            if usado:
                raise HTTPException(400, "Este enlace ya fue utilizado.")

            if expiracion < datetime.utcnow():
                raise HTTPException(400, "Este enlace ha expirado.")

            # 2️⃣ Verificar aspirante
            cur.execute(
                """
                SELECT
                    id,
                    COALESCE(NULLIF(nombre_real, ''), nickname) AS nombre,
                    nickname
                FROM creadores
                WHERE id = %s
                """,
                (creador_id,)
            )
            row = cur.fetchone()

            if not row:
                raise HTTPException(404, "El aspirante no existe.")

            aspirante_id = row[0]
            aspirante_nombre_db = row[1]
            aspirante_nickname = row[2]

            # 3️⃣ Guardar timezone opcional
            if data.timezone:
                cur.execute(
                    """
                    UPDATE perfil_creador
                    SET zona_horaria = %s
                    WHERE creador_id = %s
                    """,
                    (data.timezone, aspirante_id)
                )

            # 4️⃣ Calcular fecha_inicio/fin en UTC
            fecha_inicio = data.inicio
            tz = None

            if data.timezone:
                tz = ZoneInfo(data.timezone)
                if fecha_inicio.tzinfo is None:
                    fecha_inicio = fecha_inicio.replace(tzinfo=tz)
                fecha_inicio = fecha_inicio.astimezone(ZoneInfo("UTC"))
            else:
                if fecha_inicio.tzinfo is not None:
                    fecha_inicio = fecha_inicio.astimezone(ZoneInfo("UTC"))

            if duracion_minutos_token is not None:
                fecha_fin = fecha_inicio + timedelta(minutes=duracion_minutos_token)
            else:
                # fallback usando data.fin como antes
                fecha_fin = data.fin
                if fecha_fin <= data.inicio:
                    raise HTTPException(
                        status_code=400,
                        detail="La fecha de fin debe ser posterior a la fecha de inicio."
                    )
                if data.timezone:
                    if fecha_fin.tzinfo is None:
                        fecha_fin = fecha_fin.replace(tzinfo=tz)
                    fecha_fin = fecha_fin.astimezone(ZoneInfo("UTC"))
                else:
                    if fecha_fin.tzinfo is not None:
                        fecha_fin = fecha_fin.astimezone(ZoneInfo("UTC"))

            tipo_agendamiento = (tipo_agendamiento_token or "ENTREVISTA").upper()

            # 5️⃣ Si es ENTREVISTA → crear evento en Google Calendar con Meet
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
                    # si falla Google Calendar, seguimos pero sin Meet
                    logger.error(f"⚠️ Error creando evento de Google Calendar: {e}")
                    link_meet = None
                    google_event_id = None

            # 6️⃣ Crear agendamiento + relación entrevista
            agendamiento_id = crear_agendamiento_aspirante_DB(
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
                raise HTTPException(500, "No se pudo crear el agendamiento.")

            # 7️⃣ Marcar token como usado
            cur.execute(
                "UPDATE link_agendamiento_tokens SET usado = TRUE WHERE token = %s",
                (token,)
            )

            conn.commit()

            # 8️⃣ Respuesta final
            participante = {
                "id": aspirante_id,
                "nombre": aspirante_nombre_db,
                "nickname": aspirante_nickname,
            }

            return EventoOut(
                id=str(agendamiento_id),
                titulo=data.titulo,
                descripcion=data.descripcion,
                inicio=fecha_inicio,
                fin=fecha_fin,
                creador_id=aspirante_id,
                participantes_ids=[aspirante_id],
                participantes=[participante],
                responsable_id=responsable_id,
                estado="programado",
                link_meet=link_meet,
                origen="interno",           # aquí puedes poner "google_calendar" si quieres
                google_event_id=google_event_id,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Error creando agendamiento de aspirante: {e}")
            logger.error(traceback.format_exc())
            raise HTTPException(
                500,
                "Error interno al crear agendamiento de aspirante."
            )





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

def crear_agendamiento_aspirante_DB(
    data,
    aspirante_id: int,
    responsable_id: int
) -> Optional[int]:
    """
    Crea un agendamiento, obtiene/crea la entrevista y registra la relación
    en entrevista_agendamiento. Devuelve agendamiento_id o None si falla.

    Se espera que `data` tenga:
      - titulo
      - descripcion
      - fecha_inicio (UTC)
      - fecha_fin (UTC)
      - tipo_agendamiento (LIVE / ENTREVISTA)
      - link_meet (opcional, solo ENTREVISTA)
      - google_event_id (opcional)
    """

    try:
        tipo_agendamiento = getattr(data, "tipo_agendamiento", None) or "ENTREVISTA"
        link_meet = getattr(data, "link_meet", None)
        google_event_id = getattr(data, "google_event_id", None)

        with get_connection_context() as conn:
            with conn.cursor() as cur:

                # 1️⃣ INSERTAR AGENDAMIENTO
                cur.execute(
                    """
                    INSERT INTO agendamientos (
                        titulo,
                        descripcion,
                        fecha_inicio,
                        fecha_fin,
                        creador_id,
                        responsable_id,
                        estado,
                        tipo_agendamiento,
                        link_meet,
                        google_event_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'programado', %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        data.titulo,
                        data.descripcion,
                        data.fecha_inicio,
                        data.fecha_fin,
                        aspirante_id,
                        responsable_id,
                        tipo_agendamiento,
                        link_meet,
                        google_event_id,
                    )
                )

                agendamiento_id = cur.fetchone()[0]

                # 2️⃣ OBTENER O CREAR ENTREVISTA
                entrevista = obtener_entrevista_id(aspirante_id, responsable_id)
                if not entrevista:
                    raise Exception("No se pudo obtener o crear la entrevista.")

                entrevista_id = entrevista["id"]

                # 3️⃣ INSERTAR EN TABLA entrevista_agendamiento
                cur.execute(
                    """
                    INSERT INTO entrevista_agendamiento (
                        agendamiento_id,
                        entrevista_id,
                        creado_en
                    )
                    VALUES (%s, %s, NOW() AT TIME ZONE 'UTC')
                    """,
                    (agendamiento_id, entrevista_id)
                )

                # 4️⃣ INSERTAR PARTICIPANTE
                cur.execute(
                    """
                    INSERT INTO agendamientos_participantes (agendamiento_id, creador_id)
                    VALUES (%s, %s)
                    """,
                    (agendamiento_id, aspirante_id)
                )

                return agendamiento_id

    except Exception as e:
        print("❌ Error al crear agendamiento y relacionar entrevista:", e)
        return None

def obtener_entrevista_id(creador_id: int, usuario_evalua: int) -> Optional[dict]:
    """
    Obtiene una entrevista existente por creador_id.
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
                    WHERE creador_id = %s
                    ORDER BY creado_en ASC
                    LIMIT 1
                """, (creador_id,))

                row = cur.fetchone()

                if row:
                    return {"id": row[0], "creado_en": row[1]}

                # 2️⃣ Crear entrevista mínima
                cur.execute("""
                    INSERT INTO entrevistas (creador_id, usuario_evalua, creado_en)
                    VALUES (%s, %s, NOW() AT TIME ZONE 'UTC')
                    RETURNING id, creado_en
                """, (creador_id, usuario_evalua))

                new_row = cur.fetchone()

                if not new_row:
                    return None

                # El commit lo hace get_connection_context()
                return {"id": new_row[0], "creado_en": new_row[1]}

    except Exception as e:
        print("❌ Error en obtener_entrevista_id:", e)
        return None


@router.get("/api/agendamientos/aspirante/token-info", response_model=TokenInfoOut)
def obtener_info_token_agendamiento(token: str):
    """
    Devuelve info básica asociada al token:
    - Token inválido
    - Token ya usado
    - Token expirado
    - Datos básicos del aspirante
    - Zona horaria si existe
    - Duración de la cita
    """
    with get_connection_context() as conn:
        cur = conn.cursor()

        # 1️⃣ Buscar token
        cur.execute(
            """
            SELECT 
                token, 
                creador_id, 
                responsable_id, 
                expiracion, 
                usado,
                duracion_minutos
            FROM link_agendamiento_tokens
            WHERE token = %s
            """,
            (token,)
        )

        row = cur.fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail=(
                    "🔗 El enlace no es válido.\n"
                    "Por favor solicita un nuevo enlace de agendamiento."
                )
            )

        (
            _,
            creador_id,
            responsable_id,
            expiracion,
            usado,
            duracion_minutos,
        ) = row

        # 2️⃣ Token usado
        if usado:
            raise HTTPException(
                status_code=400,
                detail=(
                    "⚠️ Este enlace ya fue utilizado.\n"
                    "Si necesitas agendar otra cita, solicita un nuevo enlace."
                )
            )

        # 3️⃣ Token expirado
        if expiracion < datetime.utcnow():
            raise HTTPException(
                status_code=400,
                detail=(
                    "⏰ Este enlace ha expirado.\n"
                    "Solicita un nuevo enlace para continuar con tu agendamiento."
                )
            )

        # 4️⃣ Zona horaria desde perfil_creador
        cur.execute(
            """
            SELECT zona_horaria
            FROM perfil_creador
            WHERE creador_id = %s
            """,
            (creador_id,)
        )
        row_pc = cur.fetchone()
        zona_horaria = row_pc[0] if row_pc else None

        # 5️⃣ Nombre mostrable del creador
        cur.execute(
            """
            SELECT COALESCE(NULLIF(nombre_real, ''), nickname)
            FROM creadores
            WHERE id = %s
            """,
            (creador_id,)
        )
        row_cr = cur.fetchone()
        nombre_mostrable = row_cr[0] if row_cr else None

    # 6️⃣ Respuesta final
    return TokenInfoOut(
        creador_id=creador_id,
        responsable_id=responsable_id,
        zona_horaria=zona_horaria,
        nombre_mostrable=nombre_mostrable,
        duracion_minutos=duracion_minutos,
    )














# @router.post("/api/agendamientos/aspirante", response_model=EventoOut)
# def crear_agendamiento_aspirante(
#     data: AgendamientoAspiranteIn,
# ):
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         try:
#             # 1️⃣ Validar fechas
#             if data.fin <= data.inicio:
#                 raise HTTPException(
#                     status_code=400,
#                     detail="La fecha de fin debe ser posterior a la fecha de inicio."
#                 )
#
#             # 2️⃣ Validar token
#             cur.execute(
#                 """
#                 SELECT token, creador_id, responsable_id, expiracion, usado
#                 FROM link_agendamiento_tokens
#                 WHERE token = %s
#                 """,
#                 (data.token,)
#             )
#             row = cur.fetchone()
#             if not row:
#                 raise HTTPException(status_code=404, detail="Token no válido.")
#
#             token, creador_id, responsable_id, expiracion, usado = row
#
#             if usado:
#                 raise HTTPException(status_code=400, detail="Este enlace ya fue utilizado.")
#             if expiracion < datetime.utcnow():
#                 raise HTTPException(status_code=400, detail="Este enlace ha expirado.")
#
#             # 3️⃣ Verificar que el aspirante existe
#             cur.execute(
#                 """
#                 SELECT
#                     id,
#                     COALESCE(NULLIF(nombre_real, ''), nickname) AS nombre,
#                     nickname
#                 FROM creadores
#                 WHERE id = %s
#                 """,
#                 (creador_id,)
#             )
#             row = cur.fetchone()
#             if not row:
#                 raise HTTPException(
#                     status_code=404,
#                     detail="El aspirante (creador_id) no existe en la tabla creadores."
#                 )
#
#             aspirante_id = row[0]
#             aspirante_nombre_db = row[1]
#             aspirante_nickname = row[2]
#
#             # 4️⃣ Actualizar zona horaria en perfil_creador (si se envía)
#             if data.timezone:
#                 cur.execute(
#                     """
#                     UPDATE perfil_creador
#                     SET zona_horaria = %s
#                     WHERE creador_id = %s
#                     """,
#                     (data.timezone, aspirante_id)
#                 )
#
#             # (Opcional) actualizar nombre/email si quieres
#             # if data.aspirante_email or data.aspirante_nombre:
#             #     cur.execute(
#             #         """
#             #         UPDATE creadores
#             #         SET email = COALESCE(NULLIF(%s, ''), email),
#             #             nombre_real = COALESCE(NULLIF(%s, ''), nombre_real)
#             #         WHERE id = %s
#             #         """,
#             #         (data.aspirante_email, data.aspirante_nombre, aspirante_id)
#             #     )
#
#             # 5️⃣ Guardar agendamiento
#             # 👉 Guardamos las fechas tal cual llegan (hora local elegida por el aspirante)
#             fecha_inicio = data.inicio
#             fecha_fin = data.fin
#
#             cur.execute(
#                 """
#                 INSERT INTO agendamientos (
#                     titulo,
#                     descripcion,
#                     fecha_inicio,
#                     fecha_fin,
#                     creador_id,
#                     responsable_id,
#                     estado,
#                     link_meet,
#                     google_event_id
#                 )
#                 VALUES (%s, %s, %s, %s, %s, %s, 'programado', NULL, NULL)
#                 RETURNING id
#                 """,
#                 (
#                     data.titulo,
#                     data.descripcion,
#                     fecha_inicio,
#                     fecha_fin,
#                     aspirante_id,
#                     responsable_id,
#                 )
#             )
#             agendamiento_id = cur.fetchone()[0]
#
#             # 6️⃣ Insertar participante (el propio aspirante)
#             cur.execute(
#                 """
#                 INSERT INTO agendamientos_participantes (agendamiento_id, creador_id)
#                 VALUES (%s, %s)
#                 """,
#                 (agendamiento_id, aspirante_id)
#             )
#
#             # 7️⃣ Marcar token como usado
#             cur.execute(
#                 "UPDATE link_agendamiento_tokens SET usado = TRUE WHERE token = %s",
#                 (token,)
#             )
#
#             # 8️⃣ Construir respuesta
#             participante = {
#                 "id": aspirante_id,
#                 "nombre": aspirante_nombre_db,
#                 "nickname": aspirante_nickname,
#             }
#
#             return EventoOut(
#                 id=str(agendamiento_id),
#                 titulo=data.titulo,
#                 descripcion=data.descripcion,
#                 inicio=fecha_inicio,
#                 fin=fecha_fin,
#                 creador_id=aspirante_id,
#                 participantes_ids=[aspirante_id],
#                 participantes=[participante],
#                 responsable_id=responsable_id,
#                 estado="programado",
#                 link_meet=None,
#                 origen="interno",
#                 google_event_id=None,
#             )
#
#         except HTTPException:
#             raise
#         except Exception as e:
#             logger.error(f"❌ Error creando agendamiento de aspirante: {e}")
#             logger.error(traceback.format_exc())
#             raise HTTPException(
#                 status_code=500,
#                 detail="Error interno al crear agendamiento de aspirante."
#             )
#


from datetime import datetime
from fastapi import HTTPException
from zoneinfo import ZoneInfo



# @router.post("/api/agendamientos/aspirante", response_model=EventoOut)
# def crear_agendamiento_aspirante(
#     data: AgendamientoAspiranteIn,
# ):
#     """
#     Guarda una cita desde el link de agendamiento y además:
#     → Obtiene entrevista_id desde link_agendamiento_tokens
#     → Actualiza la entrevista con el nuevo agendamiento_id
#     """
#
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         try:
#             # 1️⃣ Validar fechas
#             if data.fin <= data.inicio:
#                 raise HTTPException(
#                     status_code=400,
#                     detail="La fecha de fin debe ser posterior a la fecha de inicio."
#                 )
#
#             # 2️⃣ Validar token + OBTENER entrevista_id
#             cur.execute(
#                 """
#                 SELECT token, creador_id, responsable_id, expiracion, usado, entrevista_id
#                 FROM link_agendamiento_tokens
#                 WHERE token = %s
#                 """,
#                 (data.token,)
#             )
#             row = cur.fetchone()
#
#             if not row:
#                 raise HTTPException(status_code=404, detail="Token no válido.")
#
#             token, creador_id, responsable_id, expiracion, usado, entrevista_id = row
#
#             if usado:
#                 raise HTTPException(status_code=400, detail="Este enlace ya fue utilizado.")
#
#             if expiracion < datetime.utcnow():
#                 raise HTTPException(status_code=400, detail="Este enlace ha expirado.")
#
#             if entrevista_id is None:
#                 raise HTTPException(
#                     status_code=500,
#                     detail="El token no tiene entrevista_id asociado."
#                 )
#
#             # 3️⃣ Verificar que el aspirante existe
#             cur.execute(
#                 """
#                 SELECT
#                     id,
#                     COALESCE(NULLIF(nombre_real, ''), nickname) AS nombre,
#                     nickname
#                 FROM creadores
#                 WHERE id = %s
#                 """,
#                 (creador_id,)
#             )
#             row = cur.fetchone()
#
#             if not row:
#                 raise HTTPException(
#                     status_code=404,
#                     detail="El aspirante (creador_id) no existe."
#                 )
#
#             aspirante_id = row[0]
#             aspirante_nombre_db = row[1]
#             aspirante_nickname = row[2]
#
#             # 4️⃣ Guardar timezone si la envían
#             if data.timezone:
#                 cur.execute(
#                     """
#                     UPDATE perfil_creador
#                     SET zona_horaria = %s
#                     WHERE creador_id = %s
#                     """,
#                     (data.timezone, aspirante_id)
#                 )
#
#             # 5️⃣ Guardar fechas (comportamiento original)
#             fecha_inicio = data.inicio
#             fecha_fin = data.fin
#
#             # 6️⃣ OPCIONAL: convertir a UTC
#             if data.timezone:
#                 tz = ZoneInfo(data.timezone)
#                 if fecha_inicio.tzinfo is None:
#                     fecha_inicio = fecha_inicio.replace(tzinfo=tz)
#                 if fecha_fin.tzinfo is None:
#                     fecha_fin = fecha_fin.replace(tzinfo=tz)
#
#                 fecha_inicio = fecha_inicio.astimezone(ZoneInfo("UTC"))
#                 fecha_fin = fecha_fin.astimezone(ZoneInfo("UTC"))
#
#             # 7️⃣ Insertar agendamiento
#             cur.execute(
#                 """
#                 INSERT INTO agendamientos (
#                     titulo,
#                     descripcion,
#                     fecha_inicio,
#                     fecha_fin,
#                     creador_id,
#                     responsable_id,
#                     estado,
#                     link_meet,
#                     google_event_id
#                 )
#                 VALUES (%s, %s, %s, %s, %s, %s, 'programado', NULL, NULL)
#                 RETURNING id
#                 """,
#                 (
#                     data.titulo,
#                     data.descripcion,
#                     fecha_inicio,
#                     fecha_fin,
#                     aspirante_id,
#                     responsable_id,
#                 )
#             )
#
#             agendamiento_id = cur.fetchone()[0]
#
#             # 8️⃣ Insertar participante
#             cur.execute(
#                 """
#                 INSERT INTO agendamientos_participantes (agendamiento_id, creador_id)
#                 VALUES (%s, %s)
#                 """,
#                 (agendamiento_id, aspirante_id)
#             )
#
#             # ⭐ NUEVO PASO: actualizar entrevista con el agendamiento ⭐
#             cur.execute(
#                 """
#                 UPDATE entrevistas
#                 SET agendamiento_id = %s,
#                     modificado_en = NOW()
#                 WHERE id = %s
#                 """,
#                 (agendamiento_id, entrevista_id)
#             )
#
#             # 9️⃣ Marcar token como usado
#             cur.execute(
#                 "UPDATE link_agendamiento_tokens SET usado = TRUE WHERE token = %s",
#                 (token,)
#             )
#
#             conn.commit()
#
#             # 🔟 Respuesta final
#             participante = {
#                 "id": aspirante_id,
#                 "nombre": aspirante_nombre_db,
#                 "nickname": aspirante_nickname,
#             }
#
#             return EventoOut(
#                 id=str(agendamiento_id),
#                 titulo=data.titulo,
#                 descripcion=data.descripcion,
#                 inicio=fecha_inicio,
#                 fin=fecha_fin,
#                 creador_id=aspirante_id,
#                 participantes_ids=[aspirante_id],
#                 participantes=[participante],
#                 responsable_id=responsable_id,
#                 estado="programado",
#                 link_meet=None,
#                 origen="interno",
#                 google_event_id=None,
#             )
#
#         except HTTPException:
#             raise
#         except Exception as e:
#             logger.error(f"❌ Error creando agendamiento de aspirante: {e}")
#             logger.error(traceback.format_exc())
#             raise HTTPException(
#                 status_code=500,
#                 detail="Error interno al crear agendamiento de aspirante."
#             )



# @router.post("/api/agendamientos/aspirante", response_model=EventoOut)
# def crear_agendamiento_aspirante(
#     data: AgendamientoAspiranteIn,
# ):
#     """
#     Guarda una cita desde el link de agendamiento.
#     → Respeta exactamente el comportamiento original.
#     → Solo se agrega un bloque OPCIONAL para convertir a UTC.
#     """
#
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         try:
#             # 1️⃣ Validar fechas
#             if data.fin <= data.inicio:
#                 raise HTTPException(
#                     status_code=400,
#                     detail="La fecha de fin debe ser posterior a la fecha de inicio."
#                 )
#
#             # 2️⃣ Validar token
#             cur.execute(
#                 """
#                 SELECT token, creador_id, responsable_id, expiracion, usado
#                 FROM link_agendamiento_tokens
#                 WHERE token = %s
#                 """,
#                 (data.token,)
#             )
#             row = cur.fetchone()
#
#             if not row:
#                 raise HTTPException(status_code=404, detail="Token no válido.")
#
#             token, creador_id, responsable_id, expiracion, usado = row
#
#             if usado:
#                 raise HTTPException(status_code=400, detail="Este enlace ya fue utilizado.")
#
#             if expiracion < datetime.utcnow():
#                 raise HTTPException(status_code=400, detail="Este enlace ha expirado.")
#
#             # 3️⃣ Verificar que el aspirante existe
#             cur.execute(
#                 """
#                 SELECT
#                     id,
#                     COALESCE(NULLIF(nombre_real, ''), nickname) AS nombre,
#                     nickname
#                 FROM creadores
#                 WHERE id = %s
#                 """,
#                 (creador_id,)
#             )
#             row = cur.fetchone()
#
#             if not row:
#                 raise HTTPException(
#                     status_code=404,
#                     detail="El aspirante (creador_id) no existe."
#                 )
#
#             aspirante_id = row[0]
#             aspirante_nombre_db = row[1]
#             aspirante_nickname = row[2]
#
#             # 4️⃣ Guardar timezone si la envían
#             if data.timezone:
#                 cur.execute(
#                     """
#                     UPDATE perfil_creador
#                     SET zona_horaria = %s
#                     WHERE creador_id = %s
#                     """,
#                     (data.timezone, aspirante_id)
#                 )
#
#             # ===========================================================
#             # 5️⃣ FECHAS: guardarlas tal cual (comportamiento ORIGINAL)
#             # ===========================================================
#             fecha_inicio = data.inicio
#             fecha_fin = data.fin
#
#             # ===========================================================
#             # ⭐ OPCIONAL: convertir a UTC antes de guardar ⭐
#             # (solo si quieres usar UTC más adelante)
#             #
#             if data.timezone:
#                 tz = ZoneInfo(data.timezone)
#                 if fecha_inicio.tzinfo is None:
#                     fecha_inicio = fecha_inicio.replace(tzinfo=tz)
#                 if fecha_fin.tzinfo is None:
#                     fecha_fin = fecha_fin.replace(tzinfo=tz)
#                 fecha_inicio = fecha_inicio.astimezone(ZoneInfo("UTC"))
#                 fecha_fin = fecha_fin.astimezone(ZoneInfo("UTC"))
#             #
#             # ===========================================================
#
#             # 6️⃣ Insertar agendamiento
#             cur.execute(
#                 """
#                 INSERT INTO agendamientos (
#                     titulo,
#                     descripcion,
#                     fecha_inicio,
#                     fecha_fin,
#                     creador_id,
#                     responsable_id,
#                     estado,
#                     link_meet,
#                     google_event_id
#                 )
#                 VALUES (%s, %s, %s, %s, %s, %s, 'programado', NULL, NULL)
#                 RETURNING id
#                 """,
#                 (
#                     data.titulo,
#                     data.descripcion,
#                     fecha_inicio,
#                     fecha_fin,
#                     aspirante_id,
#                     responsable_id,
#                 )
#             )
#
#             agendamiento_id = cur.fetchone()[0]
#
#             # 7️⃣ Insertar participante
#             cur.execute(
#                 """
#                 INSERT INTO agendamientos_participantes (agendamiento_id, creador_id)
#                 VALUES (%s, %s)
#                 """,
#                 (agendamiento_id, aspirante_id)
#             )
#
#             # 8️⃣ Marcar token como usado
#             cur.execute(
#                 "UPDATE link_agendamiento_tokens SET usado = TRUE WHERE token = %s",
#                 (token,)
#             )
#
#             # 9️⃣ Respuesta final
#             participante = {
#                 "id": aspirante_id,
#                 "nombre": aspirante_nombre_db,
#                 "nickname": aspirante_nickname,
#             }
#
#             return EventoOut(
#                 id=str(agendamiento_id),
#                 titulo=data.titulo,
#                 descripcion=data.descripcion,
#                 inicio=fecha_inicio,
#                 fin=fecha_fin,
#                 creador_id=aspirante_id,
#                 participantes_ids=[aspirante_id],
#                 participantes=[participante],
#                 responsable_id=responsable_id,
#                 estado="programado",
#                 link_meet=None,
#                 origen="interno",
#                 google_event_id=None,
#             )
#
#         except HTTPException:
#             raise
#         except Exception as e:
#             logger.error(f"❌ Error creando agendamiento de aspirante: {e}")
#             logger.error(traceback.format_exc())
#             raise HTTPException(
#                 status_code=500,
#                 detail="Error interno al crear agendamiento de aspirante."
#             )

# @router.get("/api/agendamientos/aspirante/token-info", response_model=TokenInfoOut)
# def obtener_info_token_agendamiento(token: str):
#     """
#     Devuelve info básica asociada al token: creador, responsable y zona horaria
#     guardada en perfil_creador (si existe).
#     """
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         # 1) Buscar token
#         cur.execute(
#             """
#             SELECT token, creador_id, responsable_id, expiracion, usado
#             FROM link_agendamiento_tokens
#             WHERE token = %s
#             """,
#             (token,)
#         )
#         row = cur.fetchone()
#         if not row:
#             raise HTTPException(status_code=404, detail="Token no válido.")
#
#         _, creador_id, responsable_id, expiracion, usado = row
#
#         if usado:
#             raise HTTPException(status_code=400, detail="Este enlace ya fue utilizado.")
#         if expiracion < datetime.utcnow():
#             raise HTTPException(status_code=400, detail="Este enlace ha expirado.")
#
#         # 2) Buscar zona horaria en perfil_creador
#         cur.execute(
#             """
#             SELECT zona_horaria
#             FROM perfil_creador
#             WHERE creador_id = %s
#             """,
#             (creador_id,)
#         )
#         row_pc = cur.fetchone()
#         zona_horaria = row_pc[0] if row_pc else None
#
#         # 3) Nombre mostrable (opcional)
#         cur.execute(
#             """
#             SELECT COALESCE(NULLIF(nombre_real, ''), nickname)
#             FROM creadores
#             WHERE id = %s
#             """,
#             (creador_id,)
#         )
#         row_cr = cur.fetchone()
#         nombre_mostrable = row_cr[0] if row_cr else None
#
#     return TokenInfoOut(
#         creador_id=creador_id,
#         responsable_id=responsable_id,
#         zona_horaria=zona_horaria,
#         nombre_mostrable=nombre_mostrable,
#     )
