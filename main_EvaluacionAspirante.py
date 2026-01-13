import secrets
import string
from uuid import uuid4

import pytz
import logging
import traceback

from types import SimpleNamespace
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, List
from pydantic import BaseModel, AnyUrl
from datetime import datetime, timedelta
from typing import Optional

from main_auth import obtener_usuario_actual
from enviar_msg_wp import enviar_plantilla_generica_parametros, enviar_plantilla_generica
from DataBase import get_connection_context, obtener_cuenta_por_subdominio
from evaluaciones import evaluar_perfil_pre, diagnostico_perfil_creador_pre, obtener_guardar_pre_resumen
# from main import crear_evento_google
from main_webhook import  enviar_mensaje
from schemas import ResumenEvaluacionOutput
from tenant import current_tenant


logger = logging.getLogger(__name__)

router = APIRouter()   # ← ESTE ES EL ROUTER QUE VAS A IMPORTAR EN main.py

from pydantic import BaseModel, Field
from typing import Literal

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


class TokenInfoOut(BaseModel):
    creador_id: int
    responsable_id: int
    zona_horaria: Optional[str] = None
    nombre_mostrable: Optional[str] = None
    duracion_minutos: Optional[int] = None


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

    # 1. Mapeo de Estado de Negocio (Tu lógica actual)
    # Ejemplo: "APROBADO" -> 100
    estado_id = ESTADO_MAP_PREEVAL.get(estado, ESTADO_DEFAULT)

    id_chatbot = 1
    # 2. Mapeo de Estado del Chatbot (NUEVO)
    if estado_id == 7:
         id_chatbot = 4
    elif estado_id == 4:
        id_chatbot = 5
    elif estado_id == 5:
        id_chatbot = 15

    with get_connection_context() as conn:
        cur = conn.cursor()

        # A. Update original (Tabla creadores)
        cur.execute("""
                    UPDATE creadores
                    SET estado_id = %s
                    WHERE id = %s
                    """, (estado_id, creador_id))

        # B. Nuevo Update (Tabla perfil_creador)
        # Sincronizamos el estado del bot
        cur.execute("""
                    UPDATE perfil_creador
                    SET id_chatbot_estado = %s,
                        actualizado_en    = NOW()
                    WHERE creador_id = %s
                    """, (id_chatbot, creador_id))

        # Confirmamos ambas transacciones
        conn.commit()

    print(f"✅ Creador {creador_id} actualizado: Negocio={estado_id}, Chatbot={id_chatbot}")


# def actualizar_estado_creador_preevaluacion(creador_id: int, estado: str):
#     estado_id = ESTADO_MAP_PREEVAL.get(estado, ESTADO_DEFAULT)
#
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         cur.execute("""
#             UPDATE creadores
#             SET estado_id = %s
#             WHERE id = %s
#         """, (estado_id, creador_id))


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


# services/db_service.py

def forzar_cambio_estado_por_id(creador_id: int, nuevo_id_estado: int):
    """
    Actualiza directamente el estado de un aspirante usando el ID numérico del estado.

    Args:
        creador_id (int): ID del aspirante (ej: 3236).
        nuevo_id_estado (int): ID del estado (ej: 5 para LIVE, 8 para ENTREVISTA).
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                # Query directa (sin buscar en tabla de estados)
                query = """
                        UPDATE test.perfil_creador
                        SET id_chatbot_estado = %s,
                            actualizado_en    = NOW() -- Opcional: para saber cuándo cambió
                        WHERE id = %s \
                        """

                cur.execute(query, (nuevo_id_estado, creador_id))
                conn.commit()

                if cur.rowcount > 0:
                    print(f"✅ [DB] Creador {creador_id} actualizado al estado ID {nuevo_id_estado}.")
                    return True
                else:
                    print(f"⚠️ [DB] No se encontró el creador ID {creador_id}.")
                    return False

    except Exception as e:
        print(f"❌ Error cambiando estado por ID: {e}")
        return False



@router.post("/api/agendamientos/aspirante/enviar", response_model=LinkAgendamientoOut)
def crear_y_enviar_link_agendamiento_aspirante(
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




@router.post("/api/perfil_creador/{creador_id}/pre_resumen/calcular",
    tags=["Resumen Pre-Evaluación"]
)
def calcular_y_guardar_pre_resumen(
    creador_id: int,
    potencial_estimado: int,   # 👈 Recibe potencial_estimado aquí
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    """
    Recalcula la pre-evaluación y actualiza el potencial_estimado manual.
    """
    try:
        # 1️⃣ Actualizar manualmente el campo potencial_estimado en perfil_creador
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE perfil_creador
                    SET potencial_estimado = %s
                    WHERE creador_id = %s
                """, (potencial_estimado, creador_id))
                conn.commit()

        print(f"🔧 potencial_estimado actualizado a {potencial_estimado}")

        # 2️⃣ Ejecuta la función completa que calcula y guarda
        obtener_guardar_pre_resumen(creador_id)
        print(f"✅ Pre-evaluación calculada y GUARDADA para creador_id={creador_id}")


        return {
            "status": "ok",
            "mensaje": "potencial_estimado actualizado",
            "creador_id": creador_id,
            "potencial_estimado": potencial_estimado
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Error al recalcular/guardar pre-evaluación: {str(e)}"
        )

@router.get("/api/perfil_creador/{creador_id}/pre_resumen",
         tags=["Resumen Pre-Evaluación"],
         response_model=ResumenEvaluacionOutput)
def obtener_pre_resumen(creador_id: int, usuario_actual: dict = Depends(obtener_usuario_actual)):

    # Llamamos a la función maestra (puntajes parciales)
    resultado = evaluar_perfil_pre(creador_id)

    if resultado.get("status") != "ok":
        raise HTTPException(status_code=404, detail="Perfil no encontrado")

    # =======================================
    # Obtener diagnóstico parcial
    # =======================================
    try:
        diagnostico = diagnostico_perfil_creador_pre(creador_id)
    except Exception:
        diagnostico = "-"

    # Texto final para mostrar en front
    texto = (
        f"📊 Pre-Evaluación:\n"
        f"Puntaje parcial: {resultado.get('puntaje_total')}\n"
        f"Categoría: {resultado.get('puntaje_total_categoria')}\n\n"
        f"🩺 Diagnóstico Preliminar:\n{diagnostico}\n"
    )

    calidad_visual_val= resultado.get("potencial_estimado")

    decision = sugerencia_decision_final(resultado["alerta"],
        puntaje_total=int(round(resultado["puntaje_total"])),
        calidad_visual_cualitativo=calidad_visual_val
    )


    # =======================================
    # Respuesta final en formato ResumenEvaluacionOutput
    # =======================================
    return ResumenEvaluacionOutput(
        status="ok",
        mensaje="Resumen preliminar calculado",

        puntaje_estadistica=resultado.get("puntaje_estadistica"),
        puntaje_estadistica_categoria=resultado.get("puntaje_estadistica_categoria"),

        puntaje_general=resultado.get("puntaje_general"),
        puntaje_general_categoria=resultado.get("puntaje_general_categoria"),

        puntaje_habitos=resultado.get("puntaje_habitos"),
        puntaje_habitos_categoria=resultado.get("puntaje_habitos_categoria"),

        puntaje_manual=None,
        puntaje_manual_categoria=None,

        puntaje_total=resultado.get("puntaje_total"),
        puntaje_total_categoria=resultado.get("puntaje_total_categoria"),
        puntaje_total_categoria_Ajustado=convertir_1a5_a_1a3(resultado.get("puntaje_total")),

        puntaje_total_ponderado=resultado.get("puntaje_total_ponderado"),
        puntaje_total_ponderado_cat=resultado.get("puntaje_total_ponderado_cat"),

        diagnostico=texto,
        mejoras_sugeridas=None,  # no aplica en pre-evaluación

        potencial_estimado=calidad_visual_val,
        potencial_estimado_texto=mapear_potencial_categoria(calidad_visual_val),
        decision_icono = decision["decision_icono"],
        decision = decision["decision"],
        recomendacion = decision["recomendacion"]

    )


def convertir_1a5_a_1a3(puntaje):
    if puntaje is None:
        return None

    # Redondear al múltiplo de 0.5 más cercano
    puntaje_redondeado = round(puntaje * 2) / 2

    # Convertir a categoría 1–3
    if puntaje_redondeado <= 2:
        return "bajo"
    elif puntaje_redondeado == 3:
        return "medio"
    else:
        return "alto"


def mapear_potencial_categoria(valor: int | None) -> str:
    if valor == 1:
        return "bajo"
    if valor == 3:
        return "medio"
    if valor == 5:
        return "alto"
    return ""  # por defecto


def sugerencia_decision_final(
    alerta: int = 0,
    puntaje_total: float | None = None,
    calidad_visual_cualitativo: int | None = None
):
    """
    ALERTAS:
        0 = sin alerta
        1 = menor de edad → No apto automático
        2 = seguidores < 50 → No apto automático
    """

    # ==========================================
    # NORMALIZAR puntaje_total
    # ==========================================
    if puntaje_total is None or puntaje_total == 0:
        cat_total = None
    else:
        if puntaje_total <= 2:
            cat_total = "bajo"
        elif puntaje_total == 3:
            cat_total = "medio"
        else:
            cat_total = "alto"

    # ==========================================
    # NORMALIZAR calidad_visual → (bajo/medio/alto)
    # ==========================================
    visual_map = {
        1: "bajo",
        3: "medio",
        5: "alto",
    }
    cat_visual = visual_map.get(calidad_visual_cualitativo, None)

    # ==========================================
    # ALERTAS AUTOMÁTICAS
    # ==========================================
    if alerta == 1:
        return {
            "puntaje_total_categoria": cat_total,
            "calidad_visual_categoria": cat_visual,
            "decision_icono": "❌",
            "decision": "No apto",
            "recomendacion": (
                "El aspirante es menor de edad. No puede ser ingresado a la agencia."
            ),
            "motivo_alerta": "menor_edad"
        }

    if alerta == 2:
        return {
            "puntaje_total_categoria": cat_total,
            "calidad_visual_categoria": cat_visual,
            "decision_icono": "❌",
            "decision": "No apto",
            "recomendacion": (
                "El aspirante tiene menos de 50 seguidores. No cumple el requisito mínimo."
            ),
            "motivo_alerta": "seguidores_insuficientes"
        }

    # ==========================================
    # CASO SIN DATOS
    # ==========================================
    if cat_total is None and cat_visual is None:
        return {
            "puntaje_total_categoria": None,
            "calidad_visual_categoria": None,
            "decision_icono": "❓",
            "decision": "Indeterminado",
            "recomendacion": "Faltan datos para la evaluación.",
        }

    # ==========================================
    # SOLO PUNTAJE TOTAL
    # ==========================================
    if cat_visual is None:
        if cat_total == "bajo":
            icono, decision = "❌", "No apto"
        elif cat_total == "medio":
            icono, decision = "🟡", "Prueba"
        else:
            icono, decision = "⭐", "Apto"

        # Puedes dejar este texto simple o cambiarlo luego si quieres
        return {
            "puntaje_total_categoria": cat_total,
            "calidad_visual_categoria": None,
            "decision_icono": icono,
            "decision": decision,
            "recomendacion": "Evaluación basada únicamente en el puntaje total.",
        }

    # ==========================================
    # SOLO VISUAL
    # ==========================================
    if cat_total is None and cat_visual:
        if cat_visual == "bajo":
            icono, decision = "❌", "No apto"
        elif cat_visual == "medio":
            icono, decision = "🟡", "Prueba"
        else:
            icono, decision = "⭐", "Apto"

        return {
            "puntaje_total_categoria": None,
            "calidad_visual_categoria": cat_visual,
            "decision_icono": icono,
            "decision": decision,
            "recomendacion": "Evaluación basada solo en análisis visual.",
        }

    # ==========================================
    # MATRIZ FINAL COMBINADA (bajo/medio/alto)
    # ==========================================
    matriz = {
        ("bajo", "bajo"):  ("❌", "No apto"),
        ("medio", "bajo"): ("❌", "No apto"),
        ("alto", "bajo"):  ("🟡", "Prueba"),

        ("bajo", "medio"):  ("🟡", "Prueba"),
        ("medio", "medio"): ("🟡", "Prueba"),
        ("alto", "medio"):  ("⭐", "Apto / prueba"),

        ("medio", "alto"): ("⭐", "Apto"),
        ("alto", "alto"):  ("⭐", "Apto"),
    }

    icono, decision = matriz.get((cat_total, cat_visual), ("❓", "Indeterminado"))

    # ===== NUEVO: recomendaciones detalladas según la decisión =====
    recomendaciones = {
        "No apto": (
            "El creador no cumple con los criterios visuales o de desempeño necesarios. "
            "Se recomienda descartar por ahora o reevaluar más adelante si mejora su perfil."
        ),
        "Requiere prueba": (
            "El puntaje es bueno, pero visualmente no muestra suficiente potencial. "
            "Se recomienda una prueba corta o entrevista para confirmar."
        ),
        "Prueba": (
            "El perfil muestra señales positivas, pero aún no es consistente. "
            "Realizar una prueba o entrevista para validar el desempeño en vivo."
        ),
        "Apto / prueba": (
            "El desempeño general es alto y muestra buen potencial. "
            "Se recomienda una prueba rápida para confirmar antes de la invitación definitiva."
        ),
        "Apto": (
            "Muy buen perfil, con buena energía y potencial claro. "
            "Recomendado para continuar el proceso o enviar a TikTok."
        ),
        "Indeterminado": (
            "La combinación de puntajes no permite una conclusión clara. "
            "Revise manualmente el perfil o complemente la evaluación."
        ),
    }

    return {
        "puntaje_total_categoria": cat_total,
        "calidad_visual_categoria": cat_visual,
        "decision_icono": icono,
        "decision": decision,
        "recomendacion": recomendaciones.get(decision, "Sin recomendación definida."),
    }



# def sugerencia_decision_final(
#     alerta: int = 0,
#     puntaje_total: float | None = None,
#     calidad_visual_cualitativo: int | None = None
# ):
#     """
#     ALERTAS:
#         0 = sin alerta
#         1 = menor de edad → No apto automático
#         2 = seguidores < 50 → No apto automático
#     """
#
#     # ==========================================
#     # NORMALIZAR puntaje_total
#     # ==========================================
#     if puntaje_total is None or puntaje_total == 0:
#         cat_total = None
#     else:
#         if puntaje_total <= 2:
#             cat_total = "bajo"
#         elif puntaje_total == 3:
#             cat_total = "medio"
#         else:
#             cat_total = "alto"
#
#     # ==========================================
#     # NORMALIZAR calidad_visual → (bajo/medio/alto)
#     # ==========================================
#     visual_map = {
#         1: "bajo",
#         2: "medio",
#         3: "alto",
#     }
#     cat_visual = visual_map.get(calidad_visual_cualitativo, None)
#
#     # ==========================================
#     # ALERTAS AUTOMÁTICAS
#     # ==========================================
#     if alerta == 1:
#         return {
#             "puntaje_total_categoria": cat_total,
#             "calidad_visual_categoria": cat_visual,
#             "decision_icono": "❌",
#             "decision": "No apto",
#             "recomendacion": (
#                 "El aspirante es menor de edad. No puede ser ingresado a la agencia."
#             ),
#             "motivo_alerta": "menor_edad"
#         }
#
#     if alerta == 2:
#         return {
#             "puntaje_total_categoria": cat_total,
#             "calidad_visual_categoria": cat_visual,
#             "decision_icono": "❌",
#             "decision": "No apto",
#             "recomendacion": (
#                 "El aspirante tiene menos de 50 seguidores. No cumple el requisito mínimo."
#             ),
#             "motivo_alerta": "seguidores_insuficientes"
#         }
#
#     # ==========================================
#     # CASO SIN DATOS
#     # ==========================================
#     if cat_total is None and cat_visual is None:
#         return {
#             "puntaje_total_categoria": None,
#             "calidad_visual_categoria": None,
#             "decision_icono": "❓",
#             "decision": "Indeterminado",
#             "recomendacion": "Faltan datos para la evaluación.",
#         }
#
#     # ==========================================
#     # SOLO PUNTAJE TOTAL
#     # ==========================================
#     if cat_visual is None:
#         if cat_total == "bajo":
#             icono, decision = "❌", "No apto"
#         elif cat_total == "medio":
#             icono, decision = "🟡", "Prueba"
#         else:
#             icono, decision = "⭐", "Apto"
#
#         return {
#             "puntaje_total_categoria": cat_total,
#             "calidad_visual_categoria": None,
#             "decision_icono": icono,
#             "decision": decision,
#             "recomendacion": "Evaluación basada únicamente en el puntaje total.",
#         }
#
#     # ==========================================
#     # SOLO VISUAL
#     # ==========================================
#     if cat_total is None and cat_visual:
#         if cat_visual == "bajo":
#             icono, decision = "❌", "No apto"
#         elif cat_visual == "medio":
#             icono, decision = "🟡", "Prueba"
#         else:
#             icono, decision = "⭐", "Apto"
#
#         return {
#             "puntaje_total_categoria": None,
#             "calidad_visual_categoria": cat_visual,
#             "decision_icono": icono,
#             "decision": decision,
#             "recomendacion": "Evaluación basada solo en análisis visual.",
#         }
#
#     # ==========================================
#     # MATRIZ FINAL COMBINADA (bajo/medio/alto)
#     # ==========================================
#     matriz = {
#         ("bajo", "bajo"): ("❌", "No apto"),
#         ("medio", "bajo"): ("❌", "No apto"),
#         ("alto", "bajo"): ("🟡", "Prueba"),
#
#         ("bajo", "medio"): ("🟡", "Prueba"),
#         ("medio", "medio"): ("🟡", "Prueba"),
#         ("alto", "medio"): ("⭐", "Apto / prueba"),
#
#         ("medio", "alto"): ("⭐", "Apto"),
#         ("alto", "alto"): ("⭐", "Apto"),
#     }
#
#     icono, decision = matriz.get((cat_total, cat_visual), ("❓", "Indeterminado"))
#
#     return {
#         "puntaje_total_categoria": cat_total,
#         "calidad_visual_categoria": cat_visual,
#         "decision_icono": icono,
#         "decision": decision,
#         "recomendacion": "Evaluación completa realizada.",
#     }


# def sugerencia_decision_final(alerta: int = 0,
#     puntaje_total: float | None = None,
#     calidad_visual_cualitativo: int | None = None):
#     """
#     puntaje_total: 1-5 → se normaliza a bajo / medio / alto
#     calidad_visual_cualitativo:
#         0 = no evaluado
#         1 = no tiene potencial
#         2 = potencial en desarrollo
#         3 = alto potencial
#         None = valor ausente
#     """
#
#     # ============================================================
#     # CASO ESPECIAL: ambos valores nulos o cero
#     # ============================================================
#     if (puntaje_total is None or puntaje_total == 0) and \
#        (calidad_visual_cualitativo is None or calidad_visual_cualitativo == 0):
#
#         return {
#             "puntaje_total_categoria": None,
#             "calidad_visual_categoria": None,
#             "decision_icono": "❓",
#             "decision": "Indeterminado",
#             "recomendacion": (
#                 "Envíe nuevamente el link de la encuesta o haga prueba/entrevista "
#                 "para evaluar directamente."
#             ),
#         }
#
#     # ============================================================
#     # NORMALIZAR puntaje_total (1-5 → bajo / medio / alto)
#     # ============================================================
#     if puntaje_total is None or puntaje_total == 0:
#         cat_total = None
#     else:
#         if puntaje_total <= 2:
#             cat_total = "bajo"
#         elif puntaje_total == 3:
#             cat_total = "medio"
#         else:  # 4 o 5
#             cat_total = "alto"
#
#     # ============================================================
#     # CASO: calidad_visual_cualitativo == 0 → evaluar solo por puntaje_total
#     # ============================================================
#     if calidad_visual_cualitativo == 0:
#
#         if cat_total == "bajo":
#             icono, decision = "❌", "No apto"
#         elif cat_total == "medio":
#             icono, decision = "🟡", "Prueba"
#         else:  # alto
#             icono, decision = "⭐", "Apto"
#
#         recomendaciones_simple = {
#             "No apto": "El creador no muestra suficiente potencial según el desempeño numérico.",
#             "Prueba": (
#                 "El puntaje es aceptable, pero falta evaluación visual. "
#                 "Recomendar una prueba para confirmar."
#             ),
#             "Apto": (
#                 "Buen desempeño numérico. Aunque no hay evaluación visual, "
#                 "el perfil parece suficientemente sólido."
#             ),
#         }
#
#         return {
#             "puntaje_total_categoria": cat_total,
#             "calidad_visual_categoria": None,
#             "decision_icono": icono,
#             "decision": decision,
#             "recomendacion": recomendaciones_simple.get(decision),
#         }
#
#     # ============================================================
#     # CASO: puntaje_total vacío pero sí hay calidad_visual
#     # (Nuevo solicitado)
#     # ============================================================
#     if (puntaje_total is None or puntaje_total == 0) and \
#        calidad_visual_cualitativo in (1, 2, 3):
#
#         cualitativo_map = {
#             1: "no_potencial",
#             2: "desarrollo",
#             3: "alto_potencial",
#         }
#         cat_visual = cualitativo_map[calidad_visual_cualitativo]
#
#         # reglas solo por visual
#         if cat_visual == "no_potencial":
#             icono, decision = "❌", "No apto"
#         elif cat_visual == "desarrollo":
#             icono, decision = "🟡", "Prueba"
#         else:  # alto
#             icono, decision = "⭐", "Apto"
#
#         recomendaciones_visual = {
#             "No apto": "La evaluación visual indica bajo potencial.",
#             "Prueba": "Tiene potencial en desarrollo. Recomendado realizar una prueba.",
#             "Apto": "Visualmente muestra alto potencial. Apto para continuar.",
#         }
#
#         return {
#             "puntaje_total_categoria": None,
#             "calidad_visual_categoria": cat_visual,
#             "decision_icono": icono,
#             "decision": decision,
#             "recomendacion": recomendaciones_visual.get(decision),
#         }
#
#     # ============================================================
#     # CASO NORMAL: ambos valores existen
#     # ============================================================
#     cualitativo_map = {
#         1: "no_potencial",
#         2: "desarrollo",
#         3: "alto_potencial",
#     }
#
#     cat_visual = cualitativo_map.get(calidad_visual_cualitativo, None)
#
#     matriz = {
#         ("bajo", "no_potencial"):    ("❌", "No apto"),
#         ("medio", "no_potencial"):   ("❌", "No apto"),
#         ("alto", "no_potencial"):    ("🟡", "Requiere prueba"),
#
#         ("bajo", "desarrollo"):      ("🟡", "Prueba"),
#         ("medio", "desarrollo"):     ("🟡", "Prueba"),
#         ("alto", "desarrollo"):      ("⭐", "Apto / prueba"),
#
#         ("medio", "alto_potencial"): ("⭐", "Apto"),
#         ("alto", "alto_potencial"):  ("⭐", "Apto"),
#     }
#
#     icono, decision = matriz.get((cat_total, cat_visual), ("❓", "Indeterminado"))
#
#     recomendaciones = {
#         "No apto": (
#             "El creador no cumple con los criterios visuales o de desempeño necesarios. "
#             "Se recomienda descartar o reevaluar más adelante."
#         ),
#         "Requiere prueba": (
#             "El puntaje es bueno, pero visualmente no muestra suficiente potencial. "
#             "Recomienda una prueba corta para confirmar."
#         ),
#         "Prueba": (
#             "Tiene señales positivas pero aún no es consistente. "
#             "Realizar una prueba para validar desempeño en vivo."
#         ),
#         "Apto / prueba": (
#             "El desempeño es alto y muestra buen potencial, pero aún requiere una validación rápida."
#         ),
#         "Apto": (
#             "Muy buen perfil, buena energía y potencial claro. "
#             "Apto para continuar con el proceso."
#         ),
#     }
#
#     return {
#         "puntaje_total_categoria": cat_total,
#         "calidad_visual_categoria": cat_visual,
#         "decision_icono": icono,
#         "decision": decision,
#         "recomendacion": recomendaciones.get(decision, "Sin recomendación definida."),
#     }

# def sugerencia_decision_final(puntaje_total: int, calidad_visual_cualitativo: int):
#     """
#     puntaje_total: 1-5  -> bajo, medio, alto
#     calidad_visual_cualitativo:
#         0 = no evaluado (IGNORAR, usar solo puntaje_total)
#         1 = no tiene potencial
#         2 = potencial en desarrollo
#         3 = alto potencial
#     """
#
#     # --- Normalizar puntaje total ---
#     if puntaje_total <= 2:
#         cat_total = "bajo"
#     elif puntaje_total == 3:
#         cat_total = "medio"
#     else:  # 4 o 5
#         cat_total = "alto"
#
#     # ----------------------------------------------------------------------
#     #  CASO ESPECIAL: calidad_visual_cualitativo = 0 → evaluar SOLO por puntaje_total
#     # ----------------------------------------------------------------------
#     if calidad_visual_cualitativo == 0:
#         if cat_total == "bajo":
#             icono = "❌"
#             decision = "No apto"
#         elif cat_total == "medio":
#             icono = "🟡"
#             decision = "Prueba"
#         else:  # alto
#             icono = "⭐"
#             decision = "Apto"
#
#         recomendaciones_simple = {
#             "No apto": (
#                 "El creador no muestra suficiente potencial según el desempeño numérico."
#             ),
#             "Prueba": (
#                 "El puntaje es aceptable, pero falta evaluación visual. "
#                 "Recomendar una prueba para confirmar."
#             ),
#             "Apto": (
#                 "Buen desempeño numérico. Aunque no hay evaluación visual, "
#                 "el perfil parece suficientemente sólido."
#             ),
#         }
#
#         return {
#             "puntaje_total_categoria": cat_total,
#             "calidad_visual_categoria": None,
#             "decision_icono": icono,
#             "decision": decision,
#             "recomendacion": recomendaciones_simple.get(decision),
#         }
#
#     # ----------------------------------------------------------------------
#     #  CASO NORMAL (sí existe evaluación visual)
#     # ----------------------------------------------------------------------
#
#     # Normalizar cualitativo
#     cualitativo_map = {
#         1: "no_potencial",
#         2: "desarrollo",
#         3: "alto_potencial"
#     }
#
#     cat_visual = cualitativo_map.get(calidad_visual_cualitativo, None)
#     if cat_visual is None:
#         raise ValueError("El valor de calidad_visual_cualitativo debe ser 0, 1, 2 o 3.")
#
#     # Matriz
#     matriz = {
#         ("bajo", "no_potencial"):    ("❌", "No apto"),
#         ("medio", "no_potencial"):   ("❌", "No apto"),
#         ("alto", "no_potencial"):    ("🟡", "Requiere prueba"),
#
#         ("bajo", "desarrollo"):      ("🟡", "Prueba"),
#         ("medio", "desarrollo"):     ("🟡", "Prueba"),
#         ("alto", "desarrollo"):      ("⭐", "Apto / prueba"),
#
#         ("medio", "alto_potencial"): ("⭐", "Apto"),
#         ("alto", "alto_potencial"):  ("⭐", "Apto"),
#     }
#
#     icono, decision = matriz.get((cat_total, cat_visual), ("❓", "Indeterminado"))
#
#     recomendaciones = {
#         "No apto": (
#             "El creador no cumple con los criterios visuales o de desempeño necesarios. "
#             "Se recomienda descartar o reevaluar más adelante."
#         ),
#         "Requiere prueba": (
#             "El puntaje es bueno, pero visualmente no muestra suficiente potencial. "
#             "Recomienda una prueba corta para confirmar."
#         ),
#         "Prueba": (
#             "Tiene señales positivas pero aún no es consistente. "
#             "Realizar una prueba para validar desempeño en vivo."
#         ),
#         "Apto / prueba": (
#             "El desempeño es alto y muestra buen potencial, pero aún requiere una validación rápida."
#         ),
#         "Apto": (
#             "Muy buen perfil, buena energía y potencial claro. "
#             "Apto para continuar con el proceso."
#         ),
#     }
#
#     recomendacion = recomendaciones.get(decision, "Sin recomendación definida.")
#
#     return {
#         "puntaje_total_categoria": cat_total,
#         "calidad_visual_categoria": cat_visual,
#         "decision_icono": icono,
#         "decision": decision,
#         "recomendacion": recomendacion,
#     }



# def sugerencia_decision_final(puntaje_total: int, calidad_visual_cualitativo: int):
#     """
#     puntaje_total: 1-5  -> bajo, medio, alto
#     calidad_visual_cualitativo: 1-3
#         1 = no tiene potencial
#         2 = potencial en desarrollo
#         3 = alto potencial
#     """
#
#     # --- Normalizar puntaje total ---
#     if puntaje_total <= 2:
#         cat_total = "bajo"
#     elif puntaje_total == 3:
#         cat_total = "medio"
#     else:  # 4 o 5
#         cat_total = "alto"
#
#     # --- Normalizar cualitativo ---
#     cualitativo_map = {
#         1: "no_potencial",
#         2: "desarrollo",
#         3: "alto_potencial"
#     }
#
#     cat_visual = cualitativo_map.get(calidad_visual_cualitativo, None)
#     if cat_visual is None:
#         raise ValueError("El valor de calidad_visual_cualitativo debe ser 1, 2 o 3.")
#
#     # --- Matriz de decisión ---
#     # Devuelve: icono, decisión
#     matriz = {
#         # no tiene potencial
#         ("bajo", "no_potencial"):    ("❌", "No apto"),
#         ("medio", "no_potencial"):   ("❌", "No apto"),
#         ("alto", "no_potencial"):    ("🟡", "Requiere prueba"),
#
#         # en desarrollo
#         ("bajo", "desarrollo"):      ("🟡", "Prueba"),
#         ("medio", "desarrollo"):     ("🟡", "Prueba"),
#         ("alto", "desarrollo"):      ("⭐", "Apto / prueba"),
#
#         # alto potencial
#         ("medio", "alto_potencial"): ("⭐", "Apto"),
#         ("alto", "alto_potencial"):  ("⭐", "Apto"),
#     }
#
#     icono, decision = matriz.get((cat_total, cat_visual), ("❓", "Indeterminado"))
#
#     # --- Recomendación en texto ---
#     recomendaciones = {
#         "No apto": (
#             "El creador no cumple con los criterios visuales o de desempeño necesarios. "
#             "Se recomienda descartar o reevaluar más adelante."
#         ),
#         "Requiere prueba": (
#             "El puntaje es bueno, pero visualmente no muestra suficiente potencial. "
#             "Recomienda una prueba corta para confirmar."
#         ),
#         "Prueba": (
#             "Tiene señales positivas pero aún no es consistente. "
#             "Realizar una prueba para validar desempeño en vivo."
#         ),
#         "Apto / prueba": (
#             "El desempeño es alto y muestra buen potencial, pero aún requiere una validación rápida."
#         ),
#         "Apto": (
#             "Muy buen perfil, buena energía y potencial claro. "
#             "Apto para continuar con el proceso."
#         ),
#     }
#
#     recomendacion = recomendaciones.get(decision, "Sin recomendación definida.")
#
#     return {
#         "puntaje_total_categoria": cat_total,
#         "calidad_visual_categoria": cat_visual,
#         "decision_icono": icono,
#         "decision": decision,
#         "recomendacion": recomendacion,
#     }


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

# @router.post("/api/agendamientos/aspirante", response_model=EventoOut)
# def crear_agendamiento_aspirante(
#     data: AgendamientoAspiranteIn,
# ):
#     """
#     Guarda una cita desde el link de agendamiento y:
#     → Valida token
#     → Crea agendamiento
#     → Obtiene o crea entrevista
#     → Inserta en entrevista_agendamiento
#     """
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
#                 raise HTTPException(404, "Token no válido.")
#
#             token, creador_id, responsable_id, expiracion, usado = row
#
#             if usado:
#                 raise HTTPException(400, "Este enlace ya fue utilizado.")
#
#             if expiracion < datetime.utcnow():
#                 raise HTTPException(400, "Este enlace ha expirado.")
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
#             # 5️⃣ Fechas UTC
#             fecha_inicio = data.inicio
#             fecha_fin = data.fin
#
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
#             # 6️⃣ Crear agendamiento + relación entrevista en UNA sola función
#             agendamiento_id = crear_agendamiento_aspirante_DB(
#                 data=SimpleNamespace(
#                     titulo=data.titulo,
#                     descripcion=data.descripcion,
#                     fecha_inicio=fecha_inicio,
#                     fecha_fin=fecha_fin
#                 ),
#                 aspirante_id=aspirante_id,
#                 responsable_id=responsable_id
#             )
#
#             if not agendamiento_id:
#                 raise HTTPException(500, "No se pudo crear el agendamiento.")
#
#             # 7️⃣ Marcar token como usado
#             cur.execute(
#                 "UPDATE link_agendamiento_tokens SET usado = TRUE WHERE token = %s",
#                 (token,)
#             )
#
#             conn.commit()
#
#             # 8️⃣ Respuesta final
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

# def crear_agendamiento_aspirante_DB(
#     data,
#     aspirante_id: int,
#     responsable_id: int
# ) -> Optional[int]:
#     """
#     Crea un agendamiento, obtiene/crea la entrevista y registra la relación
#     en entrevista_agendamiento. Devuelve agendamiento_id o None si falla.
#     """
#
#     try:
#         # ✅ usar SIEMPRE el context manager
#         with get_connection_context() as conn:
#             with conn.cursor() as cur:
#
#                 # 1️⃣ INSERTAR AGENDAMIENTO
#                 cur.execute(
#                     """
#                     INSERT INTO agendamientos (
#                         titulo,
#                         descripcion,
#                         fecha_inicio,
#                         fecha_fin,
#                         creador_id,
#                         responsable_id,
#                         estado,
#                         link_meet,
#                         google_event_id
#                     )
#                     VALUES (%s, %s, %s, %s, %s, %s, 'programado', NULL, NULL)
#                     RETURNING id
#                     """,
#                     (
#                         data.titulo,
#                         data.descripcion,
#                         data.fecha_inicio,
#                         data.fecha_fin,
#                         aspirante_id,
#                         responsable_id,
#                     )
#                 )
#
#                 agendamiento_id = cur.fetchone()[0]
#
#                 # 2️⃣ OBTENER O CREAR ENTREVISTA
#                 entrevista = obtener_entrevista_id(aspirante_id, responsable_id)
#                 if not entrevista:
#                     raise Exception("No se pudo obtener o crear la entrevista.")
#
#                 entrevista_id = entrevista["id"]
#
#                 # 3️⃣ INSERTAR EN TABLA entrevista_agendamiento
#                 cur.execute(
#                     """
#                     INSERT INTO entrevista_agendamiento (
#                         agendamiento_id,
#                         entrevista_id,
#                         creado_en
#                     )
#                     VALUES (%s, %s, NOW() AT TIME ZONE 'UTC')
#                     """,
#                     (agendamiento_id, entrevista_id)
#                 )
#
#                 # 4️⃣ INSERTAR PARTICIPANTE
#                 cur.execute(
#                     """
#                     INSERT INTO agendamientos_participantes (agendamiento_id, creador_id)
#                     VALUES (%s, %s)
#                     """,
#                     (agendamiento_id, aspirante_id)
#                 )
#
#                 # ❌ Nada de conn.commit() aquí: lo hace get_connection_context()
#                 return agendamiento_id
#
#     except Exception as e:
#         # Aquí solo logueamos; rollback y close los maneja el context manager
#         print("❌ Error al crear agendamiento y relacionar entrevista:", e)
#         return None

# @router.post("/api/agendamientos/aspirante", response_model=EventoOut)
# def crear_agendamiento_aspirante(
#     data: AgendamientoAspiranteIn,
# ):
#     """
#     Guarda una cita desde el link de agendamiento y:
#     → Valida token
#     → Crea agendamiento (usando duración y tipo del token si existen)
#     → Obtiene o crea entrevista
#     → Inserta en entrevista_agendamiento
#     """
#
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         try:
#             # 1️⃣ Validar token y obtener parámetros asociados
#             cur.execute(
#                 """
#                 SELECT
#                     token,
#                     creador_id,
#                     responsable_id,
#                     expiracion,
#                     usado,
#                     duracion_minutos,
#                     tipo_agendamiento
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
#             (
#                 token,
#                 creador_id,
#                 responsable_id,
#                 expiracion,
#                 usado,
#                 duracion_minutos_token,
#                 tipo_agendamiento_token,
#             ) = row
#
#             if usado:
#                 raise HTTPException(400, "Este enlace ya fue utilizado.")
#
#             if expiracion < datetime.utcnow():
#                 raise HTTPException(400, "Este enlace ha expirado.")
#
#             # 2️⃣ Verificar aspirante
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
#             # 3️⃣ Guardar timezone opcional
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
#             # 4️⃣ Calcular fecha_inicio y fecha_fin en UTC
#             fecha_inicio = data.inicio
#             tz = None
#
#             if data.timezone:
#                 tz = ZoneInfo(data.timezone)
#                 if fecha_inicio.tzinfo is None:
#                     fecha_inicio = fecha_inicio.replace(tzinfo=tz)
#                 fecha_inicio = fecha_inicio.astimezone(ZoneInfo("UTC"))
#             else:
#                 # Si no hay timezone, asumimos que viene ya en UTC o naive → lo tomamos tal cual
#                 if fecha_inicio.tzinfo is not None:
#                     fecha_inicio = fecha_inicio.astimezone(ZoneInfo("UTC"))
#
#             # ➕ Si el token trae duración, usamos esa para calcular fecha_fin
#             if duracion_minutos_token is not None:
#                 fecha_fin = fecha_inicio + timedelta(minutes=duracion_minutos_token)
#             else:
#                 # Fallback: usamos data.fin como antes
#                 fecha_fin = data.fin
#
#                 # Validar que fin > inicio solo en este caso
#                 if fecha_fin <= data.inicio:
#                     raise HTTPException(
#                         status_code=400,
#                         detail="La fecha de fin debe ser posterior a la fecha de inicio."
#                     )
#
#                 if data.timezone:
#                     if fecha_fin.tzinfo is None:
#                         fecha_fin = fecha_fin.replace(tzinfo=tz)
#                     fecha_fin = fecha_fin.astimezone(ZoneInfo("UTC"))
#                 else:
#                     if fecha_fin.tzinfo is not None:
#                         fecha_fin = fecha_fin.astimezone(ZoneInfo("UTC"))
#
#             # Normalizar tipo_agendamiento
#             tipo_agendamiento = (tipo_agendamiento_token or "ENTREVISTA").upper()
#
#             # 5️⃣ Crear agendamiento + relación entrevista en UNA sola función
#             agendamiento_id = crear_agendamiento_aspirante_DB(
#                 data=SimpleNamespace(
#                     titulo=data.titulo,
#                     descripcion=data.descripcion,
#                     fecha_inicio=fecha_inicio,
#                     fecha_fin=fecha_fin,
#                     tipo_agendamiento=tipo_agendamiento,
#                 ),
#                 aspirante_id=aspirante_id,
#                 responsable_id=responsable_id,
#             )
#
#             if not agendamiento_id:
#                 raise HTTPException(500, "No se pudo crear el agendamiento.")
#
#             # 6️⃣ Marcar token como usado
#             cur.execute(
#                 "UPDATE link_agendamiento_tokens SET usado = TRUE WHERE token = %s",
#                 (token,)
#             )
#
#             conn.commit()
#
#             # 7️⃣ Respuesta final
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



# def crear_agendamiento_aspirante_DB(
#     data,
#     aspirante_id: int,
#     responsable_id: int
# ) -> Optional[int]:
#     """
#     Crea un agendamiento, obtiene/crea la entrevista y registra la relación
#     en entrevista_agendamiento. Devuelve agendamiento_id o None si falla.
#
#     Se espera que `data` tenga:
#       - titulo
#       - descripcion
#       - fecha_inicio (UTC)
#       - fecha_fin (UTC)
#       - tipo_agendamiento (LIVE / ENTREVISTA)
#     """
#
#     try:
#         tipo_agendamiento = getattr(data, "tipo_agendamiento", None) or "ENTREVISTA"
#
#         with get_connection_context() as conn:
#             with conn.cursor() as cur:
#
#                 # 1️⃣ INSERTAR AGENDAMIENTO
#                 cur.execute(
#                     """
#                     INSERT INTO agendamientos (
#                         titulo,
#                         descripcion,
#                         fecha_inicio,
#                         fecha_fin,
#                         creador_id,
#                         responsable_id,
#                         estado,
#                         tipo_agendamiento,
#                         link_meet,
#                         google_event_id
#                     )
#                     VALUES (%s, %s, %s, %s, %s, %s, 'programado', %s, NULL, NULL)
#                     RETURNING id
#                     """,
#                     (
#                         data.titulo,
#                         data.descripcion,
#                         data.fecha_inicio,
#                         data.fecha_fin,
#                         aspirante_id,
#                         responsable_id,
#                         tipo_agendamiento,
#                     )
#                 )
#
#                 agendamiento_id = cur.fetchone()[0]
#
#                 # 2️⃣ OBTENER O CREAR ENTREVISTA
#                 entrevista = obtener_entrevista_id(aspirante_id, responsable_id)
#                 if not entrevista:
#                     raise Exception("No se pudo obtener o crear la entrevista.")
#
#                 entrevista_id = entrevista["id"]
#
#                 # 3️⃣ INSERTAR EN TABLA entrevista_agendamiento
#                 cur.execute(
#                     """
#                     INSERT INTO entrevista_agendamiento (
#                         agendamiento_id,
#                         entrevista_id,
#                         creado_en
#                     )
#                     VALUES (%s, %s, NOW() AT TIME ZONE 'UTC')
#                     """,
#                     (agendamiento_id, entrevista_id)
#                 )
#
#                 # 4️⃣ INSERTAR PARTICIPANTE
#                 cur.execute(
#                     """
#                     INSERT INTO agendamientos_participantes (agendamiento_id, creador_id)
#                     VALUES (%s, %s)
#                     """,
#                     (agendamiento_id, aspirante_id)
#                 )
#
#                 return agendamiento_id
#
#     except Exception as e:
#         print("❌ Error al crear agendamiento y relacionar entrevista:", e)
#         return None
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

# def crear_evento_google_(resumen, descripcion, fecha_inicio, fecha_fin):
#     service = get_calendar_service()
#
#     evento = {
#         'summary': resumen,
#         'description': descripcion,
#         'start': {
#             'dateTime': fecha_inicio.isoformat(),
#             'timeZone': 'America/Bogota',
#         },
#         'end': {
#             'dateTime': fecha_fin.isoformat(),
#             'timeZone': 'America/Bogota',
#         },
#         'conferenceData': {
#             'createRequest': {
#                 'requestId': str(uuid4()),
#                 'conferenceSolutionKey': {'type': 'hangoutsMeet'},
#             },
#         },
#     }
#
#     evento_creado = service.events().insert(
#         calendarId=CALENDAR_ID,
#         body=evento,
#         conferenceDataVersion=1
#     ).execute()
#
#     return evento_creado



# @router.get("/api/agendamientos/aspirante/token-info", response_model=TokenInfoOut)
# def obtener_info_token_agendamiento(token: str):
#     """
#     Devuelve info básica asociada al token.
#     Incluye mensajes claros para problemas comunes:
#     - Token inválido
#     - Token ya usado
#     - Token expirado
#     """
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         # 1) Buscar token
#         cur.execute(
#             """
#             SELECT token, creador_id, responsable_id, expiracion, usado, duracion_minutos
#             FROM link_agendamiento_tokens
#             WHERE token = %s
#             """,
#             (token,)
#         )
#         row = cur.fetchone()
#         if not row:
#             raise HTTPException(
#                 status_code=404,
#                 detail=(
#                     "🔗 El enlace no es válido.\n"
#                     "Por favor solicita un nuevo enlace de agendamiento."
#                 )
#             )
#
#         _, creador_id, responsable_id, expiracion, usado = row
#
#         # 2) Token usado
#         if usado:
#             raise HTTPException(
#                 status_code=400,
#                 detail=(
#                     "⚠️ Este enlace ya fue utilizado.\n"
#                     "Si necesitas agendar otra cita, solicita un nuevo enlace."
#                 )
#             )
#
#         # 3) Token expirado
#         if expiracion < datetime.utcnow():
#             raise HTTPException(
#                 status_code=400,
#                 detail=(
#                     "⏰ Este enlace ha expirado.\n"
#                     "Solicita un nuevo enlace para continuar con tu agendamiento."
#                 )
#             )
#
#         # 4) Zona horaria desde perfil_creador
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
#         # 5) Nombre mostrable
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
#         duracion_minutos=duracion_minutos,
#     )