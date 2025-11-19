import traceback
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import pytz

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from psycopg2.extras import RealDictCursor

from DataBase import get_connection_context
from schemas import *
from auth import obtener_usuario_actual

# Configurar logger
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

router = APIRouter()




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


class CrearLinkAgendamientoIn(BaseModel):
    creador_id: int
    responsable_id: int
    minutos_validez: int = 1440  # 24 horas por defecto

class LinkAgendamientoOut(BaseModel):
    token: str
    url: AnyUrl
    expiracion: datetime


class TokenInfoOut(BaseModel):
    creador_id: int
    responsable_id: int
    zona_horaria: Optional[str] = None
    nombre_mostrable: Optional[str] = None

@router.get("/api/agendamientos/aspirante/token-info", response_model=TokenInfoOut)
def obtener_info_token_agendamiento(token: str):
    """
    Devuelve info básica asociada al token: creador, responsable y zona horaria
    guardada en perfil_creador (si existe).
    """
    with get_connection_context() as conn:
        cur = conn.cursor()

        # 1) Buscar token
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
            raise HTTPException(status_code=404, detail="Token no válido.")

        _, creador_id, responsable_id, expiracion, usado = row

        if usado:
            raise HTTPException(status_code=400, detail="Este enlace ya fue utilizado.")
        if expiracion < datetime.utcnow():
            raise HTTPException(status_code=400, detail="Este enlace ha expirado.")

        # 2) Buscar zona horaria en perfil_creador
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

        # 3) Nombre mostrable (opcional)
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

    return TokenInfoOut(
        creador_id=creador_id,
        responsable_id=responsable_id,
        zona_horaria=zona_horaria,
        nombre_mostrable=nombre_mostrable,
    )

@router.post("/api/agendamientos/aspirante/link", response_model=LinkAgendamientoOut)
def crear_link_agendamiento_aspirante(
    data: CrearLinkAgendamientoIn,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    """
    Crea un token de agendamiento para un aspirante específico.
    Devuelve un link listo para enviar por WhatsApp.
    """
    # (Opcional) aquí puedes validar permisos de usuario_actual.

    token = secrets.token_urlsafe(32)
    expiracion = datetime.utcnow() + timedelta(minutes=data.minutos_validez)

    with get_connection_context() as conn:
        cur = conn.cursor()

        # Verificar que el creador existe
        cur.execute(
            "SELECT id FROM creadores WHERE id = %s",
            (data.creador_id,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail="El creador/aspirante no existe."
            )

        # Guardar token
        cur.execute(
            """
            INSERT INTO link_agendamiento_tokens (
                token, creador_id, responsable_id, expiracion, usado
            )
            VALUES (%s, %s, %s, %s, FALSE)
            """,
            (token, data.creador_id, data.responsable_id, expiracion)
        )

    # Construir URL del front
    base_front = "https://test.talentum-manager.com/agendar"
    url = f"{base_front}?token={token}"

    return LinkAgendamientoOut(
        token=token,
        url=url,
        expiracion=expiracion,
    )

@router.post("/api/agendamientos/aspirante", response_model=EventoOut)
def crear_agendamiento_aspirante(
    data: AgendamientoAspiranteIn,
):
    with get_connection_context() as conn:
        cur = conn.cursor()

        try:
            # 1️⃣ Validar fechas
            if data.fin <= data.inicio:
                raise HTTPException(
                    status_code=400,
                    detail="La fecha de fin debe ser posterior a la fecha de inicio."
                )

            # 2️⃣ Validar token
            cur.execute(
                """
                SELECT token, creador_id, responsable_id, expiracion, usado
                FROM link_agendamiento_tokens
                WHERE token = %s
                """,
                (data.token,)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Token no válido.")

            token, creador_id, responsable_id, expiracion, usado = row

            if usado:
                raise HTTPException(status_code=400, detail="Este enlace ya fue utilizado.")
            if expiracion < datetime.utcnow():
                raise HTTPException(status_code=400, detail="Este enlace ha expirado.")

            # 3️⃣ Verificar que el aspirante existe
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
                raise HTTPException(
                    status_code=404,
                    detail="El aspirante (creador_id) no existe en la tabla creadores."
                )

            aspirante_id = row[0]
            aspirante_nombre_db = row[1]
            aspirante_nickname = row[2]

            # 4️⃣ Actualizar zona horaria en perfil_creador (si se envía)
            if data.timezone:
                cur.execute(
                    """
                    UPDATE perfil_creador
                    SET zona_horaria = %s
                    WHERE creador_id = %s
                    """,
                    (data.timezone, aspirante_id)
                )

            # (Opcional) actualizar nombre/email si quieres
            # if data.aspirante_email or data.aspirante_nombre:
            #     cur.execute(
            #         """
            #         UPDATE creadores
            #         SET email = COALESCE(NULLIF(%s, ''), email),
            #             nombre_real = COALESCE(NULLIF(%s, ''), nombre_real)
            #         WHERE id = %s
            #         """,
            #         (data.aspirante_email, data.aspirante_nombre, aspirante_id)
            #     )

            # 5️⃣ Guardar agendamiento
            # 👉 Guardamos las fechas tal cual llegan (hora local elegida por el aspirante)
            fecha_inicio = data.inicio
            fecha_fin = data.fin

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
                    link_meet,
                    google_event_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'programado', NULL, NULL)
                RETURNING id
                """,
                (
                    data.titulo,
                    data.descripcion,
                    fecha_inicio,
                    fecha_fin,
                    aspirante_id,
                    responsable_id,
                )
            )
            agendamiento_id = cur.fetchone()[0]

            # 6️⃣ Insertar participante (el propio aspirante)
            cur.execute(
                """
                INSERT INTO agendamientos_participantes (agendamiento_id, creador_id)
                VALUES (%s, %s)
                """,
                (agendamiento_id, aspirante_id)
            )

            # 7️⃣ Marcar token como usado
            cur.execute(
                "UPDATE link_agendamiento_tokens SET usado = TRUE WHERE token = %s",
                (token,)
            )

            # 8️⃣ Construir respuesta
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
                link_meet=None,
                origen="interno",
                google_event_id=None,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Error creando agendamiento de aspirante: {e}")
            logger.error(traceback.format_exc())
            raise HTTPException(
                status_code=500,
                detail="Error interno al crear agendamiento de aspirante."
            )

