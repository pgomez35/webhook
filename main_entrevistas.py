from datetime import datetime,date,timedelta
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional,List
from pydantic import BaseModel, Field
import unicodedata
import logging

from auth import obtener_usuario_actual
from enviar_msg_wp import enviar_plantilla_generica_parametros, enviar_plantilla_generica
from main_Agendamiento import crear_evento

from main_webhook import enviar_mensaje, actualizar_link_prueba_live, validar_link_tiktok
from tenant import current_tenant


logger = logging.getLogger("uvicorn.error")


router = APIRouter()   # ← ESTE ES EL ROUTER QUE VAS A IMPORTAR EN main.py


from DataBase import get_connection_context, obtener_cuenta_por_subdominio, crear_invitacion_minima, \
    actualizar_estado_creador, actualizar_entrevista_por_creador


# =====================
# 🎯 ENTREVISTAS Y AGENDAMIENTOS
# 🎯 ENTREVISTAS Y AGENDAMIENTOS
# =====================


def _normalize_text(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    # quita acentos, pasa a mayúsculas y trimea
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.strip().upper()

# Mapa de estado_id según el resultado de la entrevista
# Ajusta los IDs si en tu catálogo son distintos
RESULTADO_TO_ESTADO_ID = {
    "PROGRAMADA": 4,
    "ENTREVISTA": 4,
    "INVITACION": 5,  # "Invitación"
    "RECHAZADO": 7,
}


class AgendamientoBase(BaseModel):
    creador_id: int
    fecha_programada: datetime
    duracion_minutos: Optional[int] = 30  # Agregar este campo
    usuario_programa: Optional[int] = None
    evento_id: Optional[str] = None

class AgendamientoCreate(AgendamientoBase):
    pass

class AgendamientoOut(BaseModel):
    id: int
    entrevista_id: int
    creador_id: int
    fecha_programada: datetime
    duracion_minutos: Optional[int]
    realizada: bool
    fecha_realizada: Optional[datetime]
    usuario_programa: Optional[int]
    evento_id: Optional[str]
    creado_en: datetime

# =====================
# 🎯 ENTREVISTAS
# =====================

class EntrevistaBase(BaseModel):
    creador_id: int
    usuario_evalua: Optional[int] = None
    resultado: Optional[str] = None
    observaciones: Optional[str] = None
    aspecto_tecnico: Optional[int] = None
    presencia_carisma: Optional[int] = None
    interaccion_audiencia: Optional[int] = None
    profesionalismo_normas: Optional[int] = None
    evaluacion_global: Optional[int] = None

class EntrevistaCreate(EntrevistaBase):
    pass

class EntrevistaUpdate(BaseModel):
    resultado: Optional[str] = None
    observaciones: Optional[str] = None
    usuario_evalua: Optional[int] = None
    aspecto_tecnico: Optional[int] = None
    presencia_carisma: Optional[int] = None
    interaccion_audiencia: Optional[int] = None
    profesionalismo_normas: Optional[int] = None
    evaluacion_global: Optional[int] = None

class EntrevistaOut(EntrevistaBase):
    id: int
    creado_en: datetime

class EntrevistaDetalleOut(EntrevistaOut):
    # 🔧 Importante: evitar mutable default
    agendamientos: List[AgendamientoOut] = Field(default_factory=list)



# =====================
# 🎯 EVENTOS
# =====================
from schemas import EventoIn,EventoOut

from zoneinfo import ZoneInfo
from main_EvaluacionAspirante import obtener_entrevista_id



from typing import Optional, Dict, Any
from datetime import timedelta
from zoneinfo import ZoneInfo

from DataBase import get_connection_context
from main_EvaluacionAspirante import obtener_entrevista_id  # ajusta el import según tu estructura

def insertar_agendamiento(data: dict) -> Optional[Dict[str, Any]]:
    """
    Crea un agendamiento, obtiene/crea entrevista y guarda la relación
    en entrevista_agendamiento, igual que crear_agendamiento_aspirante,
    pero con los parámetros usados en este endpoint.
    """
    try:
        # ✅ Usar SIEMPRE el context manager de conexión
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                creador_id = data["creador_id"]
                fecha_inicio = data["fecha_programada"]
                duracion_minutos = data["duracion_minutos"]
                usuario_programa = data["usuario_programa"]

                # === Zona horaria ===
                tz_local = ZoneInfo("America/Bogota")

                if fecha_inicio.tzinfo is None:
                    fecha_inicio = fecha_inicio.replace(tzinfo=tz_local)

                fecha_fin = fecha_inicio + timedelta(minutes=duracion_minutos)

                if fecha_fin.tzinfo is None:
                    fecha_fin = fecha_fin.replace(tzinfo=tz_local)

                # Convertir a UTC
                fecha_inicio_utc = fecha_inicio.astimezone(ZoneInfo("UTC"))
                fecha_fin_utc = fecha_fin.astimezone(ZoneInfo("UTC"))

                # ==========================================
                # 1️⃣ INSERTAR AGENDAMIENTO (sin entrevista_id)
                # ==========================================
                cur.execute(
                    """
                    INSERT INTO agendamientos (
                        creador_id,
                        fecha_inicio,
                        fecha_fin,
                        usuario_programa
                    )
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, creado_en
                    """,
                    (
                        creador_id,
                        fecha_inicio_utc,
                        fecha_fin_utc,
                        usuario_programa
                    )
                )

                row = cur.fetchone()
                agendamiento_id = row[0]
                creado_en = row[1]

                # ==========================================
                # 2️⃣ OBTENER O CREAR ENTREVISTA
                # ==========================================
                entrevista = obtener_entrevista_id(creador_id, usuario_programa)
                if not entrevista:
                    raise Exception("No se pudo obtener o crear la entrevista.")

                entrevista_id = entrevista["id"]

                # ==========================================
                # 3️⃣ INSERTAR RELACIÓN EN entrevista_agendamiento
                # ==========================================
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

                # ==========================================
                # 4️⃣ INSERTAR PARTICIPANTE
                # ==========================================
                cur.execute(
                    """
                    INSERT INTO agendamientos_participantes (agendamiento_id, creador_id)
                    VALUES (%s, %s)
                    """,
                    (agendamiento_id, creador_id)
                )

                # ❌ Nada de conn.commit(): lo hace get_connection_context()

                # ==========================================
                # 5️⃣ RETORNO
                # ==========================================
                return {
                    "id": agendamiento_id,
                    "entrevista_id": entrevista_id,
                    "creador_id": creador_id,
                    "fecha_programada": fecha_inicio_utc,
                    "fecha_fin": fecha_fin_utc,
                    "duracion_minutos": duracion_minutos,
                    "usuario_programa": usuario_programa,
                    "realizada": False,
                    "fecha_realizada": None,
                    "creado_en": creado_en,
                }

    except Exception as e:
        print(f"❌ Error insertando agendamiento: {e}")
        return None


def actualizar_entrevista(entrevista_id: int, datos: dict):
    if not datos:
        return None

    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                set_clauses = [f"{key} = %s" for key in datos.keys()]
                values = list(datos.values())

                sql = f"""
                    UPDATE entrevistas
                    SET {', '.join(set_clauses)}
                    WHERE id = %s
                    RETURNING id, creador_id, resultado, observaciones, evaluacion_global, creado_en
                """
                values.append(entrevista_id)
                cur.execute(sql, tuple(values))
                row = cur.fetchone()
                conn.commit()
                if not row:
                    return None

                return {
                    "id": row[0],
                    "creador_id": row[1],
                    "resultado": row[2],
                    "observaciones": row[3],
                    "evaluacion_global": row[4],
                    "creado_en": row[5]
                }
    except Exception as e:
        print("❌ Error al actualizar entrevista:", e)
        return None


@router.delete("/api/entrevistas/agendamientos/{agendamiento_id}", response_model=dict)
def eliminar_agendamiento(
    agendamiento_id: int,
    usuario_actual: dict = Depends(obtener_usuario_actual)
) -> Dict:
    if not usuario_actual:
        raise HTTPException(status_code=401, detail="Usuario no autorizado")

    try:
        # ✅ Usar siempre el context manager de conexión
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                # 1️⃣ Verificar que exista el agendamiento
                cur.execute("""
                    SELECT id
                    FROM agendamientos
                    WHERE id = %s
                """, (agendamiento_id,))
                row = cur.fetchone()

                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Agendamiento {agendamiento_id} no encontrado"
                    )

                # 2️⃣ Eliminar registro en entrevista_agendamiento
                cur.execute("""
                    DELETE FROM entrevista_agendamiento
                    WHERE agendamiento_id = %s
                """, (agendamiento_id,))

                # 3️⃣ Eliminar participantes del agendamiento
                cur.execute("""
                    DELETE FROM agendamientos_participantes
                    WHERE agendamiento_id = %s
                """, (agendamiento_id,))

                # 4️⃣ Eliminar el agendamiento
                cur.execute("""
                    DELETE FROM agendamientos
                    WHERE id = %s
                """, (agendamiento_id,))

                # ❌ Nada de conn.commit(): lo maneja get_connection_context()

                return {
                    "ok": True,
                    "mensaje": f"Agendamiento {agendamiento_id} eliminado con éxito"
                }

    except HTTPException:
        # Dejamos pasar los 401/404 tal cual
        raise
    except Exception as e:
        # El rollback también lo maneja el context manager
        logger.error(f"❌ Error al eliminar agendamiento {agendamiento_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno al eliminar agendamiento")



# ===================================================
# 📌 CREAR AGENDAMIENTO ENTREVISTA EN FRONT END
# ===================================================

@router.post("/api/entrevistas/agendamientos", response_model=AgendamientoOut)
def crear_agendamiento(
    datos: AgendamientoCreate,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    try:
        if not usuario_actual:
            raise HTTPException(status_code=401, detail="Usuario no autorizado")

        # === Validaciones ===
        if datos.creador_id is None:
            raise HTTPException(status_code=400, detail="El campo creador_id es obligatorio")
        if datos.fecha_programada is None:
            raise HTTPException(status_code=400, detail="El campo fecha_programada es obligatorio")

        creador_id = datos.creador_id
        fecha_inicio: datetime = datos.fecha_programada

        # Default 60 minutos si no viene duración
        duracion_minutos = datos.duracion_minutos or 60
        fecha_fin = fecha_inicio + timedelta(minutes=duracion_minutos)


        # === Preparar payload para DB ===
        payload_ag = {
            "creador_id": creador_id,
            "fecha_programada": fecha_inicio,
            "duracion_minutos": duracion_minutos,
            "usuario_programa": usuario_actual.get("id")
        }

        # === Insertar en la DB ===
        resultado = insertar_agendamiento(payload_ag)

        if not resultado:
            raise HTTPException(status_code=500, detail="Error al insertar agendamiento")

        # === Retorno ===
        return AgendamientoOut(
            id=resultado["id"],
            entrevista_id=resultado["entrevista_id"],
            creador_id=resultado["creador_id"],
            fecha_programada=resultado["fecha_programada"],
            duracion_minutos=resultado["duracion_minutos"],
            realizada=resultado.get("realizada"),
            fecha_realizada=resultado.get("fecha_realizada"),
            usuario_programa=resultado.get("usuario_programa"),
            creado_en=resultado["creado_en"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("❌ Error al crear agendamiento")
        raise HTTPException(status_code=500, detail=f"Error al crear agendamiento: {e}")




# ================================
# 📌 OBTENER ENTREVISTA + AGENDAMIENTOS
# ================================
@router.get("/api/entrevistas/{creador_id}", response_model=EntrevistaDetalleOut)
def obtener_entrevista(creador_id: int):
    try:
        entrevista = obtener_entrevista_con_agendamientos(creador_id)
        if not entrevista:
            # ❗ Si prefieres auto-crear entrevista en vez de 404,
            # llama a crear_entrevista_base(creador_id) y retorna esa.
            raise HTTPException(status_code=404, detail="Entrevista no encontrada")
        return entrevista
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener entrevista: {e}")

@router.put("/api/entrevistas/{creador_id}", response_model=EntrevistaOut, tags=["Entrevistas"])
def actualizar_entrevista(
    creador_id: int,
    datos: EntrevistaUpdate,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    usuario_id = usuario_actual.get("id")
    if not usuario_id:
        raise HTTPException(status_code=401, detail="Usuario no autorizado")

    # Solo campos presentes en el body
    payload = datos.dict(exclude_unset=True)

    # Si hay calificaciones pero no usuario_evalua, setear el evaluador actual
    if any(k in payload for k in (
        "aspecto_tecnico", "presencia_carisma",
        "interaccion_audiencia", "profesionalismo_normas",
        "evaluacion_global"
    )):
        payload.setdefault("usuario_evalua", usuario_id)

    # 1️⃣ Actualiza entrevista por creador
    actualizado = actualizar_entrevista_por_creador(creador_id, payload)
    if not actualizado:
        raise HTTPException(status_code=404, detail="No existe entrevista para este creador")

    # 2️⃣ Actualizar estado_id según `resultado`
    try:
        resultado_raw = payload.get("resultado") or actualizado.get("resultado")
        resultado_norm = _normalize_text(resultado_raw) if resultado_raw else None

        print(f"🧩 Resultado bruto recibido: {resultado_raw}")
        print(f"🧩 Resultado normalizado: {resultado_norm}")

        if resultado_norm:
            estado_id = RESULTADO_TO_ESTADO_ID.get(resultado_norm)

            if estado_id is None:
                print(
                    f"⚠️ Resultado '{resultado_norm}' no reconocido en RESULTADO_TO_ESTADO_ID, no se actualizará estado.")
            else:
                print(f"🔄 Estado asignado: {estado_id} (según resultado '{resultado_norm}')")

                # Actualiza el estado del creador
                actualizar_estado_creador(creador_id, estado_id)
                print(f"✅ Estado del creador {creador_id} actualizado correctamente a {estado_id}")

                # 3️⃣ Crear invitación automática si el resultado implica una invitación
                if estado_id == 5:  # 5 = INVITACIÓN
                    try:
                        print(f"📩 Intentando crear invitación automática para creador {creador_id}...")

                        # Llamamos directamente con parámetros, no con dict
                        invitacion_creada = crear_invitacion_minima(
                            creador_id=creador_id,
                            usuario_invita=usuario_id,
                            manager_id=None,
                            estado="sin programar"
                        )

                        if invitacion_creada:
                            print(f"✅ Invitación creada automáticamente para creador {creador_id}")
                        else:
                            print(
                                f"⚠️ No se pudo crear la invitación para creador {creador_id} (posiblemente ya existe).")

                    except Exception as e:
                        print(f"❌ Error al crear invitación automática para creador {creador_id}: {e}")

    except Exception as e:
        print(f"⚠️ Error general al actualizar estado o crear invitación: {e}")
        # No interrumpe la respuesta si algo falla


    # 4️⃣ Retorna respuesta normalizada
    return EntrevistaOut(
        id=actualizado["id"],
        creado_en=actualizado["creado_en"],
        creador_id=actualizado["creador_id"],
        usuario_evalua=actualizado.get("usuario_evalua"),
        resultado=actualizado.get("resultado"),
        observaciones=actualizado.get("observaciones"),
        aspecto_tecnico=actualizado.get("aspecto_tecnico"),
        presencia_carisma=actualizado.get("presencia_carisma"),
        interaccion_audiencia=actualizado.get("interaccion_audiencia"),
        profesionalismo_normas=actualizado.get("profesionalismo_normas"),
        evaluacion_global=actualizado.get("evaluacion_global"),
    )

def obtener_entrevista_con_agendamientos(creador_id: int) -> Optional[dict]:
    """
    Obtiene la entrevista más reciente del creador y sus agendamientos asociados.
    Devuelve un diccionario compatible con EntrevistaDetalleOut
    (incluye lista de AgendamientoOut).
    """
    try:
        # ✅ Usar SIEMPRE el context manager
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                # 1️⃣ Entrevista más reciente del creador
                cur.execute("""
                    SELECT id, creador_id, usuario_evalua, resultado, observaciones,
                           aspecto_tecnico, presencia_carisma, interaccion_audiencia,
                           profesionalismo_normas, evaluacion_global, creado_en
                    FROM entrevistas
                    WHERE creador_id = %s
                    ORDER BY creado_en DESC
                    LIMIT 1
                """, (creador_id,))
                e = cur.fetchone()

                if not e:
                    return None

                entrevista_dict = {
                    "id": e[0],
                    "creador_id": e[1],
                    "usuario_evalua": e[2],
                    "resultado": e[3],
                    "observaciones": e[4],
                    "aspecto_tecnico": e[5],
                    "presencia_carisma": e[6],
                    "interaccion_audiencia": e[7],
                    "profesionalismo_normas": e[8],
                    "evaluacion_global": e[9],
                    "creado_en": e[10],
                    "agendamientos": []
                }

                entrevista_id = e[0]

                # 2️⃣ Agendamientos asociados (JOIN correcto)
                cur.execute("""
                    SELECT ea.id, 
                           ea.agendamiento_id,
                           ea.creado_en,

                           a.titulo,
                           a.descripcion,
                           a.fecha_inicio,
                           a.fecha_fin,
                           a.creador_id,
                           a.responsable_id,
                           a.estado,
                           a.link_meet,
                           a.google_event_id,
                           a.creado_en,
                           a.actualizado_en

                    FROM entrevista_agendamiento ea
                    JOIN agendamientos a ON a.id = ea.agendamiento_id
                    WHERE ea.entrevista_id = %s
                    ORDER BY a.fecha_inicio ASC
                """, (entrevista_id,))
                rows = cur.fetchall()

                for r in rows:
                    (
                        rel_id,            # ea.id (no lo usamos en el modelo)
                        agendamiento_id,   # a.id
                        rel_creado_en,     # ea.creado_en (no lo usamos)

                        titulo,
                        descripcion,
                        fecha_inicio,
                        fecha_fin,
                        creador_id_ag,
                        responsable_id,
                        estado,
                        link_meet,
                        google_event_id,
                        ag_creado_en,      # a.creado_en
                        ag_actualizado_en  # a.actualizado_en (no lo usamos)
                    ) = r

                    # ⏱️ Duración en minutos
                    duracion_minutos: Optional[int] = None
                    if fecha_inicio and fecha_fin:
                        duracion_minutos = int(
                            (fecha_fin - fecha_inicio).total_seconds() // 60
                        )

                    # 🔁 Lógica simple para 'realizada'
                    realizada = (estado == "realizado")

                    # ✅ Construir EXACTAMENTE AgendamientoOut
                    entrevista_dict["agendamientos"].append({
                        "id": agendamiento_id,          # id del agendamiento
                        "entrevista_id": entrevista_id,
                        "creador_id": creador_id_ag,
                        "fecha_programada": fecha_inicio,
                        "duracion_minutos": duracion_minutos,
                        "realizada": realizada,
                        "fecha_realizada": None,        # si luego lo manejas en DB, aquí lo lees
                        "usuario_programa": None,       # no tenemos la columna en este SELECT
                        "evento_id": google_event_id,
                        "creado_en": ag_creado_en,
                    })

                return entrevista_dict

    except Exception as e:
        print(f"❌ Error al obtener entrevista con agendamientos: {e}")
        return None

# def obtener_entrevista_con_agendamientos(creador_id: int) -> Optional[dict]:
#     """
#     Obtiene la entrevista más reciente del creador y sus agendamientos asociados.
#     Devuelve un diccionario con la entrevista y una lista de agendamientos.
#     """
#
#     try:
#         # ✅ Usar SIEMPRE el context manager
#         with get_connection_context() as conn:
#             with conn.cursor() as cur:
#
#                 # 1️⃣ Entrevista más reciente del creador
#                 cur.execute("""
#                     SELECT id, creador_id, usuario_evalua, resultado, observaciones,
#                            aspecto_tecnico, presencia_carisma, interaccion_audiencia,
#                            profesionalismo_normas, evaluacion_global, creado_en
#                     FROM entrevistas
#                     WHERE creador_id = %s
#                     ORDER BY creado_en DESC
#                     LIMIT 1
#                 """, (creador_id,))
#                 e = cur.fetchone()
#
#                 if not e:
#                     return None
#
#                 entrevista_dict = {
#                     "id": e[0],
#                     "creador_id": e[1],
#                     "usuario_evalua": e[2],
#                     "resultado": e[3],
#                     "observaciones": e[4],
#                     "aspecto_tecnico": e[5],
#                     "presencia_carisma": e[6],
#                     "interaccion_audiencia": e[7],
#                     "profesionalismo_normas": e[8],
#                     "evaluacion_global": e[9],
#                     "creado_en": e[10],
#                     "agendamientos": []
#                 }
#
#                 entrevista_id = e[0]
#
#                 # 2️⃣ Agendamientos asociados (JOIN correcto)
#                 cur.execute("""
#                     SELECT ea.id,
#                            ea.agendamiento_id,
#                            ea.creado_en,
#
#                            a.titulo,
#                            a.descripcion,
#                            a.fecha_inicio,
#                            a.fecha_fin,
#                            a.creador_id,
#                            a.responsable_id,
#                            a.estado,
#                            a.link_meet,
#                            a.google_event_id,
#                            a.creado_en,
#                            a.actualizado_en
#
#                     FROM entrevista_agendamiento ea
#                     JOIN agendamientos a ON a.id = ea.agendamiento_id
#                     WHERE ea.entrevista_id = %s
#                     ORDER BY a.fecha_inicio ASC
#                 """, (entrevista_id,))
#                 rows = cur.fetchall()
#
#                 for r in rows:
#                     entrevista_dict["agendamientos"].append({
#                         "id": r[0],                     # id de entrevista_agendamiento
#                         "agendamiento_id": r[1],        # FK real
#                         "rel_creado_en": r[2],          # fecha de creación de la relación
#
#                         # Datos del agendamiento
#                         "titulo": r[3],
#                         "descripcion": r[4],
#                         "fecha_inicio": r[5],
#                         "fecha_fin": r[6],
#                         "creador_id": r[7],
#                         "responsable_id": r[8],
#                         "estado": r[9],
#                         "link_meet": r[10],
#                         "google_event_id": r[11],
#                         "ag_creado_en": r[12],
#                         "ag_actualizado_en": r[13],
#                     })
#
#                 return entrevista_dict
#
#     except Exception as e:
#         print(f"❌ Error al obtener entrevista con agendamientos: {e}")
#         return None



# def insertar_agendamiento(data: dict):
#     try:
#         conn = get_connection_context()
#         with conn.cursor() as cur:
#
#             entrevista_id = data["entrevista_id"]
#             creador_id = data["creador_id"]
#             fecha_inicio = data["fecha_programada"]
#             duracion_minutos = data["duracion_minutos"]
#             usuario_programa = data["usuario_programa"]
#
#             # === Definir zona horaria de origen (Bogotá) ===
#             tz_local = ZoneInfo("America/Bogota")
#
#             # === Asegurar timezone ===
#             if fecha_inicio.tzinfo is None:
#                 fecha_inicio = fecha_inicio.replace(tzinfo=tz_local)
#
#             fecha_fin = fecha_inicio + timedelta(minutes=duracion_minutos)
#
#             if fecha_fin.tzinfo is None:
#                 fecha_fin = fecha_fin.replace(tzinfo=tz_local)
#
#             # === Convertir a UTC antes de guardar ===
#             fecha_inicio_utc = fecha_inicio.astimezone(ZoneInfo("UTC"))
#             fecha_fin_utc = fecha_fin.astimezone(ZoneInfo("UTC"))
#
#             # === Insertar agendamiento ===
#             cur.execute(
#                 """
#                 INSERT INTO agendamientos (
#                     entrevista_id,
#                     creador_id,
#                     fecha_inicio,
#                     fecha_fin,
#                     usuario_programa
#                 )
#                 VALUES (%s, %s, %s, %s, %s)
#                 RETURNING id, creado_en
#                 """,
#                 (
#                     entrevista_id,
#                     creador_id,
#                     fecha_inicio_utc,
#                     fecha_fin_utc,
#                     usuario_programa
#                 )
#             )
#
#             row = cur.fetchone()
#             agendamiento_id = row[0]
#             creado_en = row[1]
#
#             # === Insertar participante ===
#             cur.execute(
#                 """
#                 INSERT INTO agendamientos_participantes (agendamiento_id, creador_id)
#                 VALUES (%s, %s)
#                 """,
#                 (agendamiento_id, creador_id)
#             )
#
#             conn.commit()
#
#             return {
#                 "id": agendamiento_id,
#                 "entrevista_id": entrevista_id,
#                 "creador_id": creador_id,
#                 "fecha_programada": fecha_inicio_utc,
#                 "fecha_fin": fecha_fin_utc,
#                 "duracion_minutos": duracion_minutos,
#                 "usuario_programa": usuario_programa,
#                 "realizada": False,
#                 "fecha_realizada": None,
#                 "creado_en": creado_en,
#             }
#
#     except Exception as e:
#         print(f"❌ Error insertando agendamiento: {e}")
#         return None


# def obtener_entrevista_con_agendamientos(creador_id: int):
#     conn = None
#     try:
#         conn = get_connection_context()
#         with conn.cursor() as cur:
#             # 1) Entrevista más reciente del creador
#             cur.execute("""
#                 SELECT id, creador_id, usuario_evalua, resultado, observaciones,
#                        aspecto_tecnico, presencia_carisma, interaccion_audiencia,
#                        profesionalismo_normas, evaluacion_global, creado_en
#                 FROM entrevistas
#                 WHERE creador_id = %s
#                 ORDER BY creado_en DESC
#                 LIMIT 1
#             """, (creador_id,))
#             e = cur.fetchone()
#             if not e:
#                 return None
#
#             entrevista_dict = {
#                 "id": e[0],
#                 "creador_id": e[1],
#                 "usuario_evalua": e[2],
#                 "resultado": e[3],
#                 "observaciones": e[4],
#                 "aspecto_tecnico": e[5],
#                 "presencia_carisma": e[6],
#                 "interaccion_audiencia": e[7],
#                 "profesionalismo_normas": e[8],
#                 "evaluacion_global": e[9],
#                 "creado_en": e[10],
#                 "agendamientos": []
#             }
#
#             # 2) Agendamientos relacionados (tabla: entrevista_agendamiento)
#             cur.execute("""
#                 SELECT id, entrevista_id, creador_id, fecha_programada, duracion_minutos,
#                        realizada, fecha_realizada, usuario_programa, evento_id, creado_en
#                 FROM entrevista_agendamiento
#                 WHERE entrevista_id = %s
#                 ORDER BY fecha_programada ASC
#             """, (e[0],))
#             rows = cur.fetchall()
#
#             for r in rows:
#                 entrevista_dict["agendamientos"].append({
#                     "id": r[0],
#                     "entrevista_id": r[1],
#                     "creador_id": r[2],
#                     "fecha_programada": r[3],
#                     "duracion_minutos": r[4],
#                     "realizada": r[5],
#                     "fecha_realizada": r[6],
#                     "usuario_programa": r[7],
#                     "evento_id": r[8],     # <- string/nullable
#                     "creado_en": r[9],
#                 })
#
#             return entrevista_dict
#     except Exception as e:
#         print(f"❌ Error al obtener entrevista con agendamientos: {e}")
#         return None
#     finally:
#         if conn:
#             conn.close()



# @router.delete("/api/entrevistas/agendamientos/{agendamiento_id}", response_model=dict)
# def eliminar_agendamiento(
#     agendamiento_id: int,
#     usuario_actual: dict = Depends(obtener_usuario_actual)
# ):
#     if not usuario_actual:
#         raise HTTPException(status_code=401, detail="Usuario no autorizado")
#
#     conn = get_connection_context()
#     cur = conn.cursor()
#     try:
#         # 1. Buscar el evento_id asociado al agendamiento
#         cur.execute("""
#             SELECT evento_id
#             FROM entrevista_agendamiento
#             WHERE id = %s
#         """, (agendamiento_id,))
#         row = cur.fetchone()
#
#         if not row:
#             raise HTTPException(status_code=404, detail=f"Agendamiento {agendamiento_id} no encontrado")
#
#         evento_id = row[0]
#
#         # 2. Eliminar el agendamiento
#         cur.execute("DELETE FROM entrevista_agendamiento WHERE id = %s", (agendamiento_id,))
#         conn.commit()
#         # revisar 19 nov
#         # 3. Si tenía evento asociado, borrarlo de Google Calendar
#         # if evento_id:
#         #     try:
#         #         eliminar_evento(evento_id)
#         #     except Exception as e:
#         #         # No hacemos rollback del DELETE si falla el Calendar
#         #         logger.warning(f"⚠️ No se pudo eliminar el evento {evento_id} en Calendar: {e}")
#
#         return {
#             "ok": True,
#             "mensaje": f"Agendamiento {agendamiento_id} eliminado"
#                       + (f" y evento {evento_id} eliminado" if evento_id else "")
#         }
#
#     except HTTPException:
#         raise
#     except Exception as e:
#         conn.rollback()
#         logger.error(f"❌ Error al eliminar agendamiento {agendamiento_id}: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#     finally:
#         cur.close()
#         conn.close()


# def obtener_entrevista_con_agendamientos(creador_id: int):
#     conn = None
#     try:
#         conn = get_connection_context()
#         with conn.cursor() as cur:
#
#             # 1) Entrevista más reciente del creador
#             cur.execute("""
#                 SELECT id, creador_id, usuario_evalua, resultado, observaciones,
#                        aspecto_tecnico, presencia_carisma, interaccion_audiencia,
#                        profesionalismo_normas, evaluacion_global, creado_en
#                 FROM entrevistas
#                 WHERE creador_id = %s
#                 ORDER BY creado_en DESC
#                 LIMIT 1
#             """, (creador_id,))
#             e = cur.fetchone()
#
#             if not e:
#                 return None
#
#             entrevista_dict = {
#                 "id": e[0],
#                 "creador_id": e[1],
#                 "usuario_evalua": e[2],
#                 "resultado": e[3],
#                 "observaciones": e[4],
#                 "aspecto_tecnico": e[5],
#                 "presencia_carisma": e[6],
#                 "interaccion_audiencia": e[7],
#                 "profesionalismo_normas": e[8],
#                 "evaluacion_global": e[9],
#                 "creado_en": e[10],
#                 "agendamientos": []
#             }
#
#             entrevista_id = e[0]
#
#             # 2) Agendamientos asociados (JOIN correcto)
#             cur.execute("""
#                 SELECT ea.id,
#                        ea.agendamiento_id,
#                        ea.creado_en,
#
#                        a.titulo,
#                        a.descripcion,
#                        a.fecha_inicio,
#                        a.fecha_fin,
#                        a.creador_id,
#                        a.responsable_id,
#                        a.estado,
#                        a.link_meet,
#                        a.google_event_id,
#                        a.creado_en,
#                        a.actualizado_en
#
#                 FROM entrevista_agendamiento ea
#                 JOIN agendamientos a ON a.id = ea.agendamiento_id
#                 WHERE ea.entrevista_id = %s
#                 ORDER BY a.fecha_inicio ASC
#             """, (entrevista_id,))
#             rows = cur.fetchall()
#
#             for r in rows:
#                 entrevista_dict["agendamientos"].append({
#                     "id": r[0],                     # id de entrevista_agendamiento
#                     "agendamiento_id": r[1],        # FK real
#                     "rel_creado_en": r[2],          # fecha de creación de la relación
#
#                     # Datos reales del agendamiento
#                     "titulo": r[3],
#                     "descripcion": r[4],
#                     "fecha_inicio": r[5],
#                     "fecha_fin": r[6],
#                     "creador_id": r[7],
#                     "responsable_id": r[8],
#                     "estado": r[9],
#                     "link_meet": r[10],
#                     "google_event_id": r[11],
#                     "ag_creado_en": r[12],
#                     "ag_actualizado_en": r[13],
#                 })
#
#             return entrevista_dict
#
#     except Exception as e:
#         print(f"❌ Error al obtener entrevista con agendamientos: {e}")
#         return None
#     finally:
#         if conn:
#             conn.close()

# def insertar_agendamiento(data: dict):
#     """
#     Crea un agendamiento, obtiene/crea entrevista y guarda la relación
#     en entrevista_agendamiento, igual que crear_agendamiento_aspirante,
#     pero con los parámetros usados en este endpoint.
#     """
#     try:
#         conn = get_connection_context()
#         with conn.cursor() as cur:
#
#             creador_id = data["creador_id"]
#             fecha_inicio = data["fecha_programada"]
#             duracion_minutos = data["duracion_minutos"]
#             usuario_programa = data["usuario_programa"]
#
#             # === Zona horaria ===
#             tz_local = ZoneInfo("America/Bogota")
#
#             if fecha_inicio.tzinfo is None:
#                 fecha_inicio = fecha_inicio.replace(tzinfo=tz_local)
#
#             fecha_fin = fecha_inicio + timedelta(minutes=duracion_minutos)
#
#             if fecha_fin.tzinfo is None:
#                 fecha_fin = fecha_fin.replace(tzinfo=tz_local)
#
#             # Convertir a UTC
#             fecha_inicio_utc = fecha_inicio.astimezone(ZoneInfo("UTC"))
#             fecha_fin_utc = fecha_fin.astimezone(ZoneInfo("UTC"))
#
#             # ==========================================
#             # 1️⃣ INSERTAR AGENDAMIENTO (sin entrevista_id)
#             # ==========================================
#             cur.execute(
#                 """
#                 INSERT INTO agendamientos (
#                     creador_id,
#                     fecha_inicio,
#                     fecha_fin,
#                     usuario_programa
#                 )
#                 VALUES (%s, %s, %s, %s)
#                 RETURNING id, creado_en
#                 """,
#                 (
#                     creador_id,
#                     fecha_inicio_utc,
#                     fecha_fin_utc,
#                     usuario_programa
#                 )
#             )
#
#             row = cur.fetchone()
#             agendamiento_id = row[0]
#             creado_en = row[1]
#
#             # ==========================================
#             # 2️⃣ OBTENER O CREAR ENTREVISTA
#             # ==========================================
#             entrevista = obtener_entrevista_id(creador_id, usuario_programa)
#             if not entrevista:
#                 raise Exception("No se pudo obtener o crear la entrevista.")
#
#             entrevista_id = entrevista["id"]
#
#             # ==========================================
#             # 3️⃣ INSERTAR RELACIÓN EN entrevista_agendamiento
#             # ==========================================
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
#             # ==========================================
#             # 4️⃣ INSERTAR PARTICIPANTE
#             # ==========================================
#             cur.execute(
#                 """
#                 INSERT INTO agendamientos_participantes (agendamiento_id, creador_id)
#                 VALUES (%s, %s)
#                 """,
#                 (agendamiento_id, creador_id)
#             )
#
#             conn.commit()
#
#             # ==========================================
#             # 5️⃣ RETORNO
#             # ==========================================
#             return {
#                 "id": agendamiento_id,
#                 "entrevista_id": entrevista_id,
#                 "creador_id": creador_id,
#                 "fecha_programada": fecha_inicio_utc,
#                 "fecha_fin": fecha_fin_utc,
#                 "duracion_minutos": duracion_minutos,
#                 "usuario_programa": usuario_programa,
#                 "realizada": False,
#                 "fecha_realizada": None,
#                 "creado_en": creado_en,
#             }
#
#     except Exception as e:
#         print(f"❌ Error insertando agendamiento: {e}")
#         return None

# @router.delete("/api/entrevistas/agendamientos/{agendamiento_id}", response_model=dict)
# def eliminar_agendamiento(
#     agendamiento_id: int,
#     usuario_actual: dict = Depends(obtener_usuario_actual)
# ):
#     if not usuario_actual:
#         raise HTTPException(status_code=401, detail="Usuario no autorizado")
#
#     conn = get_connection_context()
#     cur = conn.cursor()
#
#     try:
#         # 1. Verificar que exista el agendamiento
#         cur.execute("""
#             SELECT id
#             FROM agendamientos
#             WHERE id = %s
#         """, (agendamiento_id,))
#         row = cur.fetchone()
#
#         if not row:
#             raise HTTPException(
#                 status_code=404,
#                 detail=f"Agendamiento {agendamiento_id} no encontrado"
#             )
#
#         # 2. Eliminar registro en entrevista_agendamiento
#         cur.execute("""
#             DELETE FROM entrevista_agendamiento
#             WHERE agendamiento_id = %s
#         """, (agendamiento_id,))
#
#         # 3. Eliminar participantes del agendamiento
#         cur.execute("""
#             DELETE FROM agendamientos_participantes
#             WHERE agendamiento_id = %s
#         """, (agendamiento_id,))
#
#         # 4. Eliminar el agendamiento
#         cur.execute("""
#             DELETE FROM agendamientos
#             WHERE id = %s
#         """, (agendamiento_id,))
#
#         conn.commit()
#
#         return {
#             "ok": True,
#             "mensaje": f"Agendamiento {agendamiento_id} eliminado con éxito"
#         }
#
#     except HTTPException:
#         raise
#     except Exception as e:
#         conn.rollback()
#         logger.error(f"❌ Error al eliminar agendamiento {agendamiento_id}: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#
#     finally:
#         cur.close()
#         conn.close()

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter()

class CitaAspiranteOut(BaseModel):
    id: int
    fecha_inicio: str
    fecha_fin: str
    duracion_minutos: int
    tipo_prueba: str
    realizada: bool
    link_meet: Optional[str] = None
    url_reagendar: Optional[str] = None

def resolver_creador_por_token(token: str) -> int:
    # TODO: aquí miras en tu tabla de tokens / creadores
    ...

@router.get("/api/aspirantes/citas", response_model=List[CitaAspiranteOut])
def listar_citas_aspirante(token: str = Query(...)):
    creador_id = resolver_creador_por_token(token)
    if not creador_id:
        raise HTTPException(status_code=404, detail="Aspirante no encontrado")

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
                    COALESCE(a.tipo_prueba, 'ENTREVISTA') AS tipo_prueba,
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

    for r in rows:
        a_id, f_ini, f_fin, estado, tipo_prueba, link_meet = r
        duracion_min = int((f_fin - f_ini).total_seconds() // 60)
        realizada = (estado == "realizada")

        citas.append(
            CitaAspiranteOut(
                id=a_id,
                fecha_inicio=f_ini.isoformat(),
                fecha_fin=f_fin.isoformat(),
                duracion_minutos=duracion_min,
                tipo_prueba=tipo_prueba.upper(),
                realizada=realizada,
                link_meet=link_meet,
                url_reagendar=None,  # aquí podrías construir una URL pública si quieres
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
    creador_id = resolver_creador_por_token(payload.token)
    if not creador_id:
        raise HTTPException(status_code=404, detail="Aspirante no encontrado")

    link = payload.link_tiktok.strip()
    if not validar_link_tiktok(link):
        raise HTTPException(status_code=400, detail="El formato del enlace de TikTok no es válido.")

    # Caso 1: se especifica un agendamiento concreto
    if payload.agendamiento_id:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # Verificar que la cita pertenece al creador
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
                    raise HTTPException(status_code=403, detail="No tienes permiso sobre esta cita.")

                # Actualizar link_meet con el link de TikTok
                cur.execute(
                    """
                    UPDATE agendamientos
                    SET link_meet = %s
                    WHERE id = %s
                    """,
                    (link, payload.agendamiento_id)
                )

        return TikTokLiveLinkOut(
            agendamiento_id=payload.agendamiento_id,
            message="Enlace de TikTok LIVE actualizado para tu cita."
        )

    # Caso 2: sin agendamiento → usamos actualizar_link_prueba_live
    ag_id = actualizar_link_prueba_live(creador_id=creador_id, link_tiktok=link)
    if not ag_id:
        raise HTTPException(status_code=500, detail="No se pudo registrar el enlace de TikTok LIVE.")

    return TikTokLiveLinkOut(
        agendamiento_id=ag_id,
        message="Enlace de TikTok LIVE registrado correctamente."
    )

