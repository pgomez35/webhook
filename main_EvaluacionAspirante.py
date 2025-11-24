import secrets
import string
import pytz
import logging
import traceback

from types import SimpleNamespace
from zoneinfo import ZoneInfo
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, List
from pydantic import BaseModel, AnyUrl
from datetime import datetime, timedelta
from typing import Optional

from auth import obtener_usuario_actual
from enviar_msg_wp import enviar_plantilla_generica_parametros, enviar_plantilla_generica
from DataBase import get_connection_context, obtener_cuenta_por_subdominio
from main_webhook import  enviar_mensaje
from tenant import current_tenant


logger = logging.getLogger(__name__)

router = APIRouter()   # ← ESTE ES EL ROUTER QUE VAS A IMPORTAR EN main.py

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


class ActualizarPreEvaluacionIn(BaseModel):
    estado_evaluacion: Optional[str] = None  # "No apto" | "Entrevista" | "Invitar a TikTok"
    usuario_evalua: Optional[str] = None
    observaciones_finales: Optional[str] = None


class EventoIn(BaseModel):
    titulo: str
    descripcion: Optional[str] = None
    inicio: datetime
    fin: datetime
    participantes_ids: List[int] = []  # << agregar esta línea
    link_meet: Optional[str] = None  # ← agregar esto si quieres permitir edición manual
    requiere_meet: Optional[bool] = True  # ✅ nuevo flag


class EventoOut(EventoIn):
    id: str
    link_meet: Optional[str] = None
    origen: Optional[str] = "google_calendar"  # Para distinguir fuentes
    responsable_id: Optional[int] = None
    participantes: Optional[List[dict]] = None  # ← para devolver nombres, roles, etc

class AgendamientoAspiranteIn(BaseModel):
    titulo: str
    descripcion: Optional[str] = None
    inicio: datetime            # "2025-11-30T09:30:00" (hora local del aspirante)
    fin: datetime               # "2025-11-30T10:40:00"
    timezone: Optional[str] = None  # "America/Santiago", etc.
    aspirante_nombre: Optional[str] = None
    aspirante_email: Optional[str] = None
    token: str

ESTADO_MAP_PREEVAL = {
    "No apto": 7,
    "Entrevista": 4,
    "Invitar a TikTok": 5,
}
ESTADO_DEFAULT = 99  # si no coincide



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



def crear_agendamiento_aspirante_DB(
    data,
    aspirante_id: int,
    responsable_id: int
) -> Optional[int]:
    """
    Crea un agendamiento, obtiene/crea la entrevista y registra la relación
    en entrevista_agendamiento. Devuelve agendamiento_id o None si falla.
    """

    try:
        # ✅ usar SIEMPRE el context manager
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
                        link_meet,
                        google_event_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'programado', NULL, NULL)
                    RETURNING id
                    """,
                    (
                        data.titulo,
                        data.descripcion,
                        data.fecha_inicio,
                        data.fecha_fin,
                        aspirante_id,
                        responsable_id,
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

                # ❌ Nada de conn.commit() aquí: lo hace get_connection_context()
                return agendamiento_id

    except Exception as e:
        # Aquí solo logueamos; rollback y close los maneja el context manager
        print("❌ Error al crear agendamiento y relacionar entrevista:", e)
        return None


def actualizar_preevaluacion_perfil(creador_id: int, payload: dict):
    with get_connection_context() as conn:
        cur = conn.cursor()

        sets = []
        valores = []

        for campo, valor in payload.items():
            if valor is not None:
                sets.append(f"{campo} = %s")
                valores.append(valor)

        if not sets:
            return

        valores.append(creador_id)

        query = f"""
            UPDATE perfil_creador
            SET {', '.join(sets)}, actualizado_en = NOW()
            WHERE creador_id = %s
        """

        cur.execute(query, valores)


def actualizar_estado_creador_preevaluacion(creador_id: int, estado: str):
    estado_id = ESTADO_MAP_PREEVAL.get(estado, ESTADO_DEFAULT)

    with get_connection_context() as conn:
        cur = conn.cursor()

        cur.execute("""
            UPDATE creadores
            SET estado_id = %s
            WHERE id = %s
        """, (estado_id, creador_id))


@router.put("/api/perfil_creador/{creador_id}/preevaluacion")
def actualizar_preevaluacion(
    creador_id: int,
    datos: ActualizarPreEvaluacionIn,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    try:
        print("➡️ Payload recibido:", datos.dict())

        payload = {
            "estado_evaluacion": datos.estado_evaluacion,
            "usuario_evalua": datos.usuario_evalua,
            # "observaciones_finales": datos.observaciones_finales,
        }

        print("➡️ Actualizando perfil_creador con:", payload)
        actualizar_preevaluacion_perfil(creador_id, payload)

        if datos.estado_evaluacion:
            print("➡️ Actualizando tabla creadores.estado_id con:", datos.estado_evaluacion)
            actualizar_estado_creador_preevaluacion(creador_id, datos.estado_evaluacion)

        print("✔️ Pre-evaluación actualizada correctamente")

        return {
            "status": "ok",
            "mensaje": "Pre-evaluación actualizada correctamente",
            "creador_id": creador_id,
            "estado_evaluacion": datos.estado_evaluacion,
        }

    except Exception as e:
        print("❌ ERROR en actualizar_preevaluacion:", str(e))
        raise HTTPException(status_code=500, detail=str(e))




def generar_token_corto(longitud=10):
    caracteres = string.ascii_letters + string.digits  # A-Z a-z 0-9
    return ''.join(secrets.choice(caracteres) for _ in range(longitud))


@router.post("/api/agendamientos/aspirante/enviar", response_model=LinkAgendamientoOut)
def crear_y_enviar_link_agendamiento_aspirante(
    data: CrearLinkAgendamientoIn,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    """
    Genera un link de agendamiento, crea una entrevista mínima,
    guarda el entrevista_id dentro de link_agendamiento_tokens
    y envía la plantilla por WhatsApp.
    """

    # 1️⃣ Token
    token = generar_token_corto(10)
    expiracion = datetime.utcnow() + timedelta(minutes=data.minutos_validez)

    with get_connection_context() as conn:
        cur = conn.cursor()

        # ---------------------------------------------------------
        # 2️⃣ Obtener datos del aspirante
        # ---------------------------------------------------------
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

        # ---------------------------------------------------------
        # 3️⃣ Guardar token (YA NO se guarda entrevista_id)
        # ---------------------------------------------------------
        cur.execute(
            """
            INSERT INTO link_agendamiento_tokens
            (token, creador_id, responsable_id, expiracion, usado)
            VALUES (%s, %s, %s, %s, FALSE)
            """,
            (token, data.creador_id, data.responsable_id, expiracion)
        )

        conn.commit()

    # ---------------------------------------------------------
    # 5️⃣ Construir URL de agendamiento
    # ---------------------------------------------------------
    subdominio = current_tenant.get() or "test"
    if subdominio == "public":
        subdominio = "test"

    url = f"https://{subdominio}.talentum-manager.com/agendar?token={token}"

    # ---------------------------------------------------------
    # 6️⃣ Obtener credenciales WABA
    # ---------------------------------------------------------
    subdominio_cfg = current_tenant.get()
    cuenta = obtener_cuenta_por_subdominio(subdominio_cfg)

    if not cuenta:
        raise HTTPException(500, f"No hay credenciales WABA para '{subdominio_cfg}'.")

    access_token = cuenta.get("access_token")
    phone_id = cuenta.get("phone_number_id")

    # Debug seguro
    token_preview = access_token[:4] + "..." + access_token[-6:] if access_token else "None"
    phone_preview = phone_id[:3] + "..." + phone_id[-3:] if phone_id else "None"
    print(f"🔐 Token (preview): {token_preview}")
    print(f"📱 Phone ID (preview): {phone_preview}")

    if not access_token or not phone_id:
        raise HTTPException(500, f"Credenciales WABA incompletas para '{subdominio_cfg}'.")

    # ---------------------------------------------------------
    # 7️⃣ Enviar plantilla WhatsApp
    # ---------------------------------------------------------
    try:
        status_code, resp = enviar_plantilla_generica_parametros(
            token=access_token,
            phone_number_id=phone_id,
            numero_destino=telefono,
            nombre_plantilla="agenda_tu_entrevista_v2",
            codigo_idioma="es_CO",
            parametros=[nombre_creador, url],  # 2 parámetros
            body_vars_count=2
        )

        if status_code != 200:
            raise Exception(f"Error {status_code}: {resp}")

    except Exception as e:
        # Fallback texto normal
        try:
            mensaje = (
                f"Hola {nombre_creador} 👋\n\n"
                "Queremos continuar tu proceso en la agencia.\n\n"
                "📅 Agenda tu audición en TikTok LIVE aquí:\n"
                f"{url}\n\n"
                "Selecciona el horario que prefieras. Si necesitas cambiar la cita, contáctanos."
            )
            # enviar_mensaje(telefono, mensaje)

        except Exception as ex:
            raise HTTPException(
                500,
                detail=f"Token creado y entrevista registrada, "
                       f"pero falló la plantilla y el fallback: {e} / {ex}"
            )

    # ---------------------------------------------------------
    # 8️⃣ Respuesta final
    # ---------------------------------------------------------
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


@router.post("/api/agendamientos/aspirante", response_model=EventoOut)
def crear_agendamiento_aspirante(
    data: AgendamientoAspiranteIn,
):
    """
    Guarda una cita desde el link de agendamiento y:
    → Valida token
    → Crea agendamiento
    → Obtiene o crea entrevista
    → Inserta en entrevista_agendamiento
    """
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
                raise HTTPException(404, "Token no válido.")

            token, creador_id, responsable_id, expiracion, usado = row

            if usado:
                raise HTTPException(400, "Este enlace ya fue utilizado.")

            if expiracion < datetime.utcnow():
                raise HTTPException(400, "Este enlace ha expirado.")

            # 3️⃣ Verificar aspirante
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

            # 4️⃣ Guardar timezone opcional
            if data.timezone:
                cur.execute(
                    """
                    UPDATE perfil_creador
                    SET zona_horaria = %s
                    WHERE creador_id = %s
                    """,
                    (data.timezone, aspirante_id)
                )

            # 5️⃣ Fechas UTC
            fecha_inicio = data.inicio
            fecha_fin = data.fin

            if data.timezone:
                tz = ZoneInfo(data.timezone)

                if fecha_inicio.tzinfo is None:
                    fecha_inicio = fecha_inicio.replace(tzinfo=tz)
                if fecha_fin.tzinfo is None:
                    fecha_fin = fecha_fin.replace(tzinfo=tz)

                fecha_inicio = fecha_inicio.astimezone(ZoneInfo("UTC"))
                fecha_fin = fecha_fin.astimezone(ZoneInfo("UTC"))

            # 6️⃣ Crear agendamiento + relación entrevista en UNA sola función
            agendamiento_id = crear_agendamiento_aspirante_DB(
                data=SimpleNamespace(
                    titulo=data.titulo,
                    descripcion=data.descripcion,
                    fecha_inicio=fecha_inicio,
                    fecha_fin=fecha_fin
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
                500,
                "Error interno al crear agendamiento de aspirante."
            )

@router.get("/api/agendamientos/aspirante/token-info", response_model=TokenInfoOut)
def obtener_info_token_agendamiento(token: str):
    """
    Devuelve info básica asociada al token.
    Incluye mensajes claros para problemas comunes:
    - Token inválido
    - Token ya usado
    - Token expirado
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
            raise HTTPException(
                status_code=404,
                detail=(
                    "🔗 El enlace no es válido.\n"
                    "Por favor solicita un nuevo enlace de agendamiento."
                )
            )

        _, creador_id, responsable_id, expiracion, usado = row

        # 2) Token usado
        if usado:
            raise HTTPException(
                status_code=400,
                detail=(
                    "⚠️ Este enlace ya fue utilizado.\n"
                    "Si necesitas agendar otra cita, solicita un nuevo enlace."
                )
            )

        # 3) Token expirado
        if expiracion < datetime.utcnow():
            raise HTTPException(
                status_code=400,
                detail=(
                    "⏰ Este enlace ha expirado.\n"
                    "Solicita un nuevo enlace para continuar con tu agendamiento."
                )
            )

        # 4) Zona horaria desde perfil_creador
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

        # 5) Nombre mostrable
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

@router.get("/api/agendamientos/aspirante/token-info", response_model=TokenInfoOut)
def obtener_info_token_agendamiento(token: str):
    """
    Devuelve info básica asociada al token.
    Incluye mensajes claros para problemas comunes:
    - Token inválido
    - Token ya usado
    - Token expirado
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
            raise HTTPException(
                status_code=404,
                detail=(
                    "🔗 El enlace no es válido.\n"
                    "Por favor solicita un nuevo enlace de agendamiento."
                )
            )

        _, creador_id, responsable_id, expiracion, usado = row

        # 2) Token usado
        if usado:
            raise HTTPException(
                status_code=400,
                detail=(
                    "⚠️ Este enlace ya fue utilizado.\n"
                    "Si necesitas agendar otra cita, solicita un nuevo enlace."
                )
            )

        # 3) Token expirado
        if expiracion < datetime.utcnow():
            raise HTTPException(
                status_code=400,
                detail=(
                    "⏰ Este enlace ha expirado.\n"
                    "Solicita un nuevo enlace para continuar con tu agendamiento."
                )
            )

        # 4) Zona horaria desde perfil_creador
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

        # 5) Nombre mostrable
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



# @router.post("/api/agendamientos/aspirante", response_model=EventoOut)
# def crear_agendamiento_aspirante(
#     data: AgendamientoAspiranteIn,
# ):
#     """
#     Guarda una cita desde el link de agendamiento y además:
#     → Obtiene entrevista_id desde link_agendamiento_tokens
#     → Inserta entrevista_id en la tabla agendamientos
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
#             # 2️⃣ Validar token + obtener entrevista_id
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
#                 raise HTTPException(404, "Token no válido.")
#
#             token, creador_id, responsable_id, expiracion, usado, entrevista_id = row
#
#             if usado:
#                 raise HTTPException(400, "Este enlace ya fue utilizado.")
#
#             if expiracion < datetime.utcnow():
#                 raise HTTPException(400, "Este enlace ha expirado.")
#
#             if entrevista_id is None:
#                 raise HTTPException(500, "El token no tiene entrevista_id asociado.")
#
#             # 3️⃣ Verificar aspirante
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
#                 raise HTTPException(404, "El aspirante no existe.")
#
#             aspirante_id = row[0]
#             aspirante_nombre_db = row[1]
#             aspirante_nickname = row[2]
#
#             # 4️⃣ Guardar timezone opcional
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
#             # 5️⃣ Fechas
#             fecha_inicio = data.inicio
#             fecha_fin = data.fin
#
#             # 6️⃣ Convertir a UTC si aplica
#             if data.timezone:
#                 tz = ZoneInfo(data.timezone)
#
#                 if fecha_inicio.tzinfo is None:
#                     fecha_inicio = fecha_inicio.replace(tzinfo=tz)
#                 if fecha_fin.tzinfo is None:
#                     fecha_fin = fecha_fin.replace(tzinfo=tz)
#
#                 fecha_inicio = fecha_inicio.astimezone(ZoneInfo("UTC"))
#                 fecha_fin = fecha_fin.astimezone(ZoneInfo("UTC"))
#
#             # 7️⃣ Insertar agendamiento (AQUÍ SE AGREGA entrevista_id)
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
#                     google_event_id,
#                     entrevista_id   -- 👈 NUEVO CAMPO
#                 )
#                 VALUES (%s, %s, %s, %s, %s, %s, 'programado', NULL, NULL, %s)
#                 RETURNING id
#                 """,
#                 (
#                     data.titulo,
#                     data.descripcion,
#                     fecha_inicio,
#                     fecha_fin,
#                     aspirante_id,
#                     responsable_id,
#                     entrevista_id,   # 👈 INSERTAR AQUÍ
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
#             # ⭐ YA NO SE ACTUALIZA ENTREVISTAS ⭐
#             # (se elimina por completo el bloque UPDATE entrevistas)
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
#                 500,
#                 "Error interno al crear agendamiento de aspirante."
#             )



# @router.post("/api/aspirantes/no_apto/enviar")
# def enviar_mensaje_no_apto(
#         data: EnviarNoAptoIn,
#         usuario_actual: dict = Depends(obtener_usuario_actual)
# ):
#     """
#     Envía mensaje de NO APTO.
#     1) Intenta mensaje simple.
#     2) Si falla por ventana 24h → envía plantilla no_apto_proceso_v2.
#     """
#
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         # 1) Obtener datos del aspirante
#         cur.execute("""
#             SELECT id, nombre_real, telefono
#             FROM creadores
#             WHERE id = %s
#         """, (data.creador_id,))
#
#         row = cur.fetchone()
#         if not row:
#             raise HTTPException(status_code=404, detail="Aspirante no encontrado.")
#
#         creador_id, nombre, telefono = row
#
#         if not telefono:
#             raise HTTPException(status_code=400, detail="El aspirante no tiene número registrado.")
#
#         # 2) Mensaje estándar (primer intento)
#         mensaje = (
#             f"Hola {nombre or ''} 👋\n\n"
#             "Después de revisar tu información inicial, "
#             "hemos determinado que por ahora *no cumples con los requisitos* "
#             "para continuar en el proceso de selección de creadores de TikTok LIVE.\n\n"
#             "Esto *no refleja tu talento* ni tu potencial. "
#             "Te invitamos a seguir creciendo y a aplicar nuevamente más adelante.\n\n"
#             "Gracias por tu tiempo 🙌"
#         )
#
#     # =============================
#     #   3) Intento 1: mensaje simple
#     # =============================
#     try:
#         resp = enviar_mensaje(telefono, mensaje)
#         return {
#             "status": "ok",
#             "tipo_envio": "mensaje_texto",
#             "mensaje": "Mensaje simple enviado correctamente",
#             "telefono": telefono
#         }
#
#     except Exception as e:
#         # Analizar error de ventana de 24h
#         err_str = str(e)
#
#         if "131047" not in err_str and "24 hours" not in err_str:
#             # Error REAL → no continuar
#             raise HTTPException(status_code=500, detail=f"Error enviando mensaje: {err_str}")
#
#         print("⚠️ Mensaje simple bloqueado por ventana de 24h. Intentando plantilla...")
#
#     # ===================================================
#     # 4) Intento 2: plantilla fallback no_apto_proceso_v2
#     # ===================================================
#     try:
#         subdominio = current_tenant.get()
#         cuenta = obtener_cuenta_por_subdominio(subdominio)
#
#         token = cuenta["access_token"]
#         phone_id = cuenta["phone_number_id"]
#         business_name = (
#             cuenta.get("business_name")
#             or cuenta.get("nombre")
#             or "nuestra agencia"
#         )
#
#         # Parámetros plantilla: {{1}} = nombre, {{2}} = agency
#         parametros = [
#             nombre or "creador",
#             business_name
#         ]
#
#         codigo, respuesta_api = enviar_plantilla_generica_parametros(
#             token=token,
#             phone_number_id=phone_id,
#             numero_destino=telefono,
#             nombre_plantilla="no_apto_proceso_v2",
#             codigo_idioma="es_CO",
#             parametros=parametros
#         )
#
#         return {
#             "status": "ok",
#             "tipo_envio": "plantilla",
#             "codigo_meta": codigo,
#             "respuesta_api": respuesta_api,
#             "telefono": telefono
#         }
#
#     except Exception as e:
#         raise HTTPException(
#             status_code=500,
#             detail=f"No se pudo enviar ni mensaje simple ni plantilla: {str(e)}"
#         )
#
#




# @router.post("/api/agendamientos/aspirante/enviar", response_model=LinkAgendamientoOut)
# def crear_y_enviar_link_agendamiento_aspirante(
#     data: CrearLinkAgendamientoIn,
#     usuario_actual: dict = Depends(obtener_usuario_actual),
# ):
#     """
#     Genera un link de agendamiento y lo envía por WhatsApp al aspirante.
#     El número de teléfono se obtiene automáticamente desde `creadores`.
#     """
#
#     # 1) Token corto
#     token = generar_token_corto(10)
#     expiracion = datetime.utcnow() + timedelta(minutes=data.minutos_validez)
#
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         # 2) Obtener teléfono y nombre del aspirante
#         cur.execute(
#             """
#             SELECT COALESCE(nickname, nombre_real) AS nombre, telefono
#             FROM creadores
#             WHERE id = %s
#             """,
#             (data.creador_id,)
#         )
#         row = cur.fetchone()
#
#         if not row:
#             raise HTTPException(404, "El aspirante no existe.")
#
#         nombre_creador, telefono = row
#
#         if not telefono:
#             raise HTTPException(400, "El aspirante no tiene teléfono registrado.")
#
#         # 3) Guardar token
#         cur.execute(
#             """
#             INSERT INTO link_agendamiento_tokens (
#                 token, creador_id, responsable_id, expiracion, usado
#             )
#             VALUES (%s, %s, %s, %s, FALSE)
#             """,
#             (token, data.creador_id, data.responsable_id, expiracion)
#         )
#
#     # 4) Armar URL dinámica con tenant
#     subdomain = current_tenant.get() or "test"
#     if subdomain == "public":
#         subdomain = "test"
#
#     base_front = f"https://{subdomain}.talentum-manager.com/agendar"
#     url = f"{base_front}?token={token}"
#
#     # 5) Armar mensaje
#     mensaje = (
#         f"Hola {nombre_creador} 👋\n\n"
#         "Queremos continuar tu proceso en la agencia.\n\n"
#         "📅 Agenda tu entrevista aquí:\n"
#         f"{url}\n\n"
#         "Selecciona el horario que prefieras.\n"
#         # "✨ Prestige Agency"
#     )
#
#     # 6) Enviar WhatsApp
#     try:
#         enviar_mensaje(telefono, mensaje)
#     except Exception as e:
#         raise HTTPException(500, f"Token generado, pero fallo al enviar WhatsApp: {e}")
#
#     # 7) Respuesta
#     return LinkAgendamientoOut(
#         token=token,
#         url=url,
#         expiracion=expiracion,
#     )


# def crear_agendamiento_aspirante_DB(
#     data,
#     aspirante_id: int,
#     responsable_id: int
# ) -> Optional[int]:
#     """
#     Crea un agendamiento, obtiene/crea la entrevista y registra la relación
#     en entrevista_agendamiento. Devuelve agendamiento_id.
#     """
#     conn = get_connection_context()
#     try:
#         with conn.cursor() as cur:
#
#             # 1️⃣ INSERTAR AGENDAMIENTO
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
#                     data.fecha_inicio,
#                     data.fecha_fin,
#                     aspirante_id,
#                     responsable_id,
#                 )
#             )
#
#             agendamiento_id = cur.fetchone()[0]
#
#             # 2️⃣ OBTENER O CREAR ENTREVISTA
#             entrevista = obtener_entrevista_id(aspirante_id, responsable_id)
#             if not entrevista:
#                 raise Exception("No se pudo obtener o crear la entrevista.")
#
#             entrevista_id = entrevista["id"]
#
#             # 3️⃣ INSERTAR EN TABLA entrevista_agendamiento
#             cur.execute(
#                 """
#                 INSERT INTO entrevista_agendamiento (
#                     agendamiento_id,
#                     entrevista_id,
#                     creado_en
#                 )
#                 VALUES (%s, %s, NOW() AT TIME ZONE 'UTC')
#                 """,
#                 (agendamiento_id, entrevista_id)
#             )
#
#             # 4️⃣ INSERTAR PARTICIPANTE
#             cur.execute(
#                 """
#                 INSERT INTO agendamientos_participantes (agendamiento_id, creador_id)
#                 VALUES (%s, %s)
#                 """,
#                 (agendamiento_id, aspirante_id)
#             )
#
#             conn.commit()
#             return agendamiento_id
#
#     except Exception as e:
#         print("❌ Error al crear agendamiento y relacionar entrevista:", e)
#         conn.rollback()
#         return None
#
#     finally:
#         conn.close()



# def obtener_entrevista_id(creador_id: int, usuario_evalua: int) -> Optional[dict]:
#     """
#     Obtiene una entrevista existente por creador_id.
#     Si no existe, crea una entrevista mínima.
#     Devuelve: { id, creado_en }
#     """
#     conn = get_connection_context()
#     try:
#         with conn.cursor() as cur:
#
#             # 1️⃣ Buscar entrevista existente
#             cur.execute("""
#                 SELECT id, creado_en
#                 FROM entrevistas
#                 WHERE creador_id = %s
#                 ORDER BY creado_en ASC
#                 LIMIT 1
#             """, (creador_id,))
#
#             row = cur.fetchone()
#
#             # Si existe → retornarla
#             if row:
#                 return {"id": row[0], "creado_en": row[1]}
#
#             # 2️⃣ Si no existe → crear entrevista mínima
#             cur.execute("""
#                 INSERT INTO entrevistas (creador_id, usuario_evalua, creado_en)
#                 VALUES (%s, %s, NOW() AT TIME ZONE 'UTC')
#                 RETURNING id, creado_en
#             """, (creador_id, usuario_evalua))
#
#             new_row = cur.fetchone()
#             conn.commit()
#
#             if not new_row:
#                 return None
#
#             return {"id": new_row[0], "creado_en": new_row[1]}
#
#     except Exception as e:
#         print("❌ Error en obtener_o_crear_entrevista:", e)
#         return None
#
#     finally:
#         conn.close()



