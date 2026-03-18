import os
from datetime import datetime,date,timedelta
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
import unicodedata
import logging
from decimal import Decimal
from typing import Optional, List, Literal, Dict, Any


from main_auth import obtener_usuario_actual
from enviar_msg_wp import enviar_plantilla_generica_parametros, enviar_plantilla_generica
from main_Agendamiento import crear_evento

from main_webhook import enviar_mensaje, validar_link_tiktok
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
from main_Agendamiento import obtener_entrevista_id,obtener_entrevista_id

from typing import Optional, Dict, Any
from datetime import timedelta
from zoneinfo import ZoneInfo

from DataBase import get_connection_context


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

@router.post("/api/entrevistas/agendamientosV0", response_model=AgendamientoOut)
def crear_agendamientoV0(
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
@router.get("/api/entrevistasV0/{creador_id}", response_model=EntrevistaDetalleOut)
def obtener_entrevistaV0(creador_id: int):
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

@router.put("/api/entrevistasV0/{creador_id}", response_model=EntrevistaOut, tags=["Entrevistas"])
def actualizar_entrevistaV0(
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
                        SELECT
                            ea.id,
                            ea.agendamiento_id,
                            ea.creado_en AS entrevista_agendamiento_creado_en,
                        
                            a.titulo,
                            a.descripcion,
                            a.fecha_inicio,
                            a.fecha_fin,
                            COALESCE(a.creador_id, ap.creador_id) AS creador_id,
                            a.responsable_id,
                            a.estado,
                            a.link_meet,
                            a.google_event_id,
                            a.creado_en AS agendamiento_creado_en,
                            a.actualizado_en
                        
                        FROM entrevista_agendamiento ea
                        JOIN agendamientos a
                            ON a.id = ea.agendamiento_id
                        LEFT JOIN agendamientos_participantes ap
                            ON ap.agendamiento_id = a.id
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


# --------------------------------------------------------------
# --------------------------------------------------------------
# --------------------------------------------------------------
# --------------------------------------------------------------
# --------------------------------------------------------------
# --------------------------------------------------------------
# --------------------------------------------------------------
# ------------------17 marzo 2026------------------
# --------------------------------------------------------------
# --------------------------------------------------------------
# --------------------------------------------------------------
# --------------------------------------------------------------
# --------------------------------------------------------------
# --------------------------------------------------------------
# --------------------------------------------------------------


# =========================================================
# CONSTANTES
# =========================================================


TIPO_AGENDAMIENTO_PRUEBA = 1        # live
TIPO_AGENDAMIENTO_ENTREVISTA = 2    # entrevista

ESTADO_ENTREVISTA_PROGRAMADA = 1
ESTADO_ENTREVISTA_EVALUADA = 2
ESTADO_ENTREVISTA_CANCELADA = 3
ESTADO_ENTREVISTA_NO_ASISTIO = 4


# =========================================================
# SCHEMAS
# =========================================================

class EntrevistaEvaluacionUpdate(BaseModel):
    observaciones: Optional[str] = Field(default=None, max_length=500)
    aspecto_tecnico: int = Field(..., ge=1, le=5)
    presencia_carisma: int = Field(..., ge=1, le=5)
    interaccion_audiencia: int = Field(..., ge=1, le=5)
    profesionalismo_normas: int = Field(..., ge=1, le=5)
    estado_id: int = Field(default=ESTADO_ENTREVISTA_EVALUADA)


class DecisionUpdate(BaseModel):
    decision_final: Literal["continuar", "observar", "descartar", "reprogramar"]
    observacion_decision: Optional[str] = Field(default=None, max_length=300)


# =========================================================
# HELPERS
# =========================================================

def to_float(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def map_tipo_label(tipo_agendamiento: Optional[int]) -> str:
    if tipo_agendamiento == TIPO_AGENDAMIENTO_PRUEBA:
        return "Prueba"
    if tipo_agendamiento == TIPO_AGENDAMIENTO_ENTREVISTA:
        return "Entrevista"
    return "Agendamiento"


def map_tipo_codigo(tipo_agendamiento: Optional[int]) -> Optional[str]:
    if tipo_agendamiento == TIPO_AGENDAMIENTO_PRUEBA:
        return "live"
    if tipo_agendamiento == TIPO_AGENDAMIENTO_ENTREVISTA:
        return "entrevista"
    return None


def normalizar_item_db(row: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(row)
    item["score_total_entrevista"] = to_float(item.get("score_total_entrevista"))
    item["score_total"] = to_float(item.get("score_total"))
    item["diagnostico_score"] = to_float(item.get("diagnostico_score"))
    return item


def calcular_score_prueba(
    aspecto_tecnico: int,
    presencia_carisma: int,
    interaccion_audiencia: int,
    profesionalismo_normas: int
) -> float:
    promedio = (
        aspecto_tecnico +
        presencia_carisma +
        interaccion_audiencia +
        profesionalismo_normas
    ) / 4
    return round(promedio, 2)


def calcular_score_final(
    diagnostico_score: Optional[float],
    score_prueba: Optional[float]
) -> Optional[float]:
    if diagnostico_score is None and score_prueba is None:
        return None
    if diagnostico_score is None:
        return round(score_prueba, 2)
    if score_prueba is None:
        return round(diagnostico_score, 2)

    # Ajusta ponderación si luego quieres
    return round((diagnostico_score * 0.5) + (score_prueba * 0.5), 2)


def obtener_nivel_score(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    if score < 2.5:
        return "bajo"
    if score < 3.5:
        return "medio"
    if score < 4.3:
        return "bueno"
    return "alto"


def sugerir_decision(score_final: Optional[float]) -> Optional[str]:
    if score_final is None:
        return None
    if score_final >= 4.0:
        return "continuar"
    if score_final >= 3.0:
        return "observar"
    if score_final >= 2.0:
        return "reprogramar"
    return "descartar"


def calcular_estado_visual(item: Dict[str, Any], now: datetime) -> Dict[str, str]:
    fecha_inicio = item.get("fecha_inicio")
    fecha_fin = item.get("fecha_fin")
    estado_id = item.get("estado_id")
    score_prueba = item.get("score_total_entrevista")

    evaluada = (
        estado_id == ESTADO_ENTREVISTA_EVALUADA
        or score_prueba is not None
    )

    if evaluada:
        return {
            "codigo": "evaluada",
            "label": "Evaluada",
            "color": "success",
            "accion": "ver_resultado"
        }

    if fecha_inicio and fecha_fin and fecha_inicio <= now <= fecha_fin:
        return {
            "codigo": "en_curso",
            "label": "En curso",
            "color": "warning",
            "accion": "evaluar"
        }

    if fecha_fin and fecha_fin < now:
        return {
            "codigo": "pendiente_evaluacion",
            "label": "Pendiente evaluación",
            "color": "danger",
            "accion": "evaluar"
        }

    if fecha_inicio and fecha_inicio.date() == now.date():
        return {
            "codigo": "hoy",
            "label": "Hoy",
            "color": "warning",
            "accion": "evaluar"
        }

    if fecha_inicio and fecha_inicio > now:
        return {
            "codigo": "programada",
            "label": "Programada",
            "color": "info",
            "accion": "solo_ver"
        }

    return {
        "codigo": "programada",
        "label": "Programada",
        "color": "secondary",
        "accion": "solo_ver"
    }


def elegir_prueba_activa(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    prioridades = [
        "pendiente_evaluacion",
        "en_curso",
        "hoy",
        "programada",
        "evaluada"
    ]

    for prioridad in prioridades:
        for item in items:
            if item["estado_ui"]["codigo"] == prioridad:
                return item

    return None


def serializar_item_pantalla(item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not item:
        return None

    tipo_agendamiento = item.get("tipo_agendamiento")

    return {
        "agendamiento_id": item.get("agendamiento_id"),
        "entrevista_id": item.get("entrevista_id"),
        "titulo": item.get("titulo"),
        "descripcion": item.get("descripcion"),
        "tipo_agendamiento": {
            "id": tipo_agendamiento,
            "nombre": item.get("tipo_agendamiento_nombre") or map_tipo_label(tipo_agendamiento),
            "codigo": map_tipo_codigo(tipo_agendamiento),
            "color": item.get("tipo_agendamiento_color"),
            "icono": item.get("tipo_agendamiento_icono"),
        },
        "tipo_entrevista": {
            "id": item.get("entrevista_tipo_id"),
            "nombre": item.get("tipo_nombre"),
            "codigo": item.get("tipo_codigo")
        },
        "fecha_inicio": item.get("fecha_inicio"),
        "fecha_fin": item.get("fecha_fin"),
        "link_meet": item.get("link_meet"),
        "estado": item.get("estado_ui"),
        "accion_principal": item["estado_ui"]["accion"],
        "scores": {
            "diagnostico": item.get("diagnostico_score"),
            "prueba": item.get("score_total_entrevista"),
            "final": item.get("score_total"),
            "nivel_prueba": obtener_nivel_score(item.get("score_total_entrevista")),
            "nivel_final": obtener_nivel_score(item.get("score_total")),
        },
        "diagnostico_resumen": item.get("diagnostico_resumen"),
        "observaciones": item.get("observaciones"),
        "aspecto_tecnico": item.get("aspecto_tecnico"),
        "presencia_carisma": item.get("presencia_carisma"),
        "interaccion_audiencia": item.get("interaccion_audiencia"),
        "profesionalismo_normas": item.get("profesionalismo_normas"),
        "estado_id": item.get("estado_id"),
        "decision_sugerida": sugerir_decision(item.get("score_total"))
    }


def obtener_diagnostico_score(cur, creador_id: int) -> Dict[str, Any]:
    cur.execute("""
        SELECT puntaje_total, diagnostico_resumen
        FROM diagnostico_score_general
        WHERE creador_id = %s
        ORDER BY creador_id DESC
        LIMIT 1
    """, (creador_id,))

    row = cur.fetchone()
    if not row:
        return {
            "puntaje_total": None,
            "diagnostico_resumen": None
        }

    return {
        "puntaje_total": to_float(row[0]),
        "diagnostico_resumen": row[1]
    }


def asegurar_entrevista_existe(cur, agendamiento_id: int, creador_id: int) -> int:
    # 1) Si ya existe entrevista para ese agendamiento, la devuelve
    cur.execute("""
        SELECT e.id
        FROM entrevistas e
        JOIN agendamientos_participantes ap
          ON ap.agendamiento_id = e.agendamiento_id
        WHERE e.agendamiento_id = %s
          AND ap.creador_id = %s
        LIMIT 1
    """, (agendamiento_id, creador_id))
    row = cur.fetchone()

    if row:
        return row[0]

    # 2) Validar que el agendamiento exista para ese creador vía participantes
    cur.execute("""
        SELECT a.tipo_agendamiento
        FROM agendamientos a
        JOIN agendamientos_participantes ap
          ON ap.agendamiento_id = a.id
        WHERE a.id = %s
          AND ap.creador_id = %s
        LIMIT 1
    """, (agendamiento_id, creador_id))
    ag = cur.fetchone()

    if not ag:
        raise HTTPException(
            status_code=404,
            detail="Agendamiento no encontrado para este creador"
        )

    tipo_agendamiento = ag[0]

    if tipo_agendamiento not in (1, 2):
        raise HTTPException(
            status_code=400,
            detail=f"Solo se pueden crear entrevistas para tipo_agendamiento 1 o 2. Recibido: {tipo_agendamiento}"
        )

    entrevista_tipo_id = tipo_agendamiento

    cur.execute("""
        SELECT id
        FROM entrevista_tipo
        WHERE id = %s
          AND activo = true
        LIMIT 1
    """, (entrevista_tipo_id,))
    tipo_row = cur.fetchone()

    if not tipo_row:
        raise HTTPException(
            status_code=400,
            detail=f"No existe entrevista_tipo activo para id={entrevista_tipo_id}"
        )

    cur.execute("""
        INSERT INTO entrevistas (
            creador_id,
            agendamiento_id,
            entrevista_tipo_id,
            estado_id,
            creado_en
        )
        VALUES (%s, %s, %s, %s, now())
        RETURNING id
    """, (
        creador_id,
        agendamiento_id,
        entrevista_tipo_id,
        ESTADO_ENTREVISTA_PROGRAMADA
    ))

    created = cur.fetchone()
    return created[0]


# =========================================================
# ENDPOINT 1: PANTALLA COMPLETA
# =========================================================

@router.get("/api/creadores/{creador_id}/evaluacion-entrevistas")
def obtener_pantalla_evaluacion_entrevistas(creador_id: int):
    now = datetime.now()

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            diagnostico_data = obtener_diagnostico_score(cur, creador_id)
            diagnostico_score = diagnostico_data["puntaje_total"]
            diagnostico_resumen = diagnostico_data["diagnostico_resumen"]

            cur.execute("""
                SELECT
                    a.id AS agendamiento_id,
                    a.titulo,
                    a.descripcion,
                    a.fecha_inicio,
                    a.fecha_fin,
                    a.link_meet,
                    a.tipo_agendamiento,
                    a.estado AS agendamiento_estado,
                    ap.creador_id,

                    ta.nombre AS tipo_agendamiento_nombre,
                    ta.color AS tipo_agendamiento_color,
                    ta.icono AS tipo_agendamiento_icono,

                    e.id AS entrevista_id,
                    e.entrevista_tipo_id,
                    e.usuario_evalua,
                    e.observaciones,
                    e.aspecto_tecnico,
                    e.presencia_carisma,
                    e.interaccion_audiencia,
                    e.profesionalismo_normas,
                    e.score_total_entrevista,
                    e.score_total,
                    e.estado_id,
                    e.creado_en,

                    et.nombre AS tipo_nombre,
                    et.tipo AS tipo_codigo

                FROM agendamientos a
                JOIN agendamientos_participantes ap
                  ON ap.agendamiento_id = a.id
                LEFT JOIN tipos_agendamiento ta
                  ON ta.id = a.tipo_agendamiento
                LEFT JOIN entrevistas e
                  ON e.agendamiento_id = a.id
                LEFT JOIN entrevista_tipo et
                  ON et.id = e.entrevista_tipo_id
                WHERE ap.creador_id = %s
                  AND a.tipo_agendamiento IN (1, 2)
                ORDER BY a.fecha_inicio ASC, a.id ASC
            """, (creador_id,))

            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]

            items = []
            for r in rows:
                raw = dict(zip(columns, r))
                item = normalizar_item_db(raw)
                item["diagnostico_score"] = diagnostico_score
                item["diagnostico_resumen"] = diagnostico_resumen

                if item.get("score_total") is None:
                    item["score_total"] = calcular_score_final(
                        diagnostico_score,
                        item.get("score_total_entrevista")
                    )

                item["estado_ui"] = calcular_estado_visual(item, now)
                items.append(item)

            prueba_activa = elegir_prueba_activa(items)

            resumen = {
                "creador_id": creador_id,
                "diagnostico_score": diagnostico_score,
                "diagnostico_resumen": diagnostico_resumen,
                "prueba_score": prueba_activa.get("score_total_entrevista") if prueba_activa else None,
                "score_final": prueba_activa.get("score_total") if prueba_activa else None,
                "nivel_final": obtener_nivel_score(prueba_activa.get("score_total")) if prueba_activa else None,
                "decision_sugerida": sugerir_decision(prueba_activa.get("score_total")) if prueba_activa else None
            }

            return {
                "success": True,
                "data": {
                    "resumen": resumen,
                    "prueba_activa": serializar_item_pantalla(prueba_activa),
                    "agendamientos": [serializar_item_pantalla(x) for x in items]
                }
            }


# =========================================================
# ENDPOINT 2: DETALLE POR AGENDAMIENTO
# =========================================================

@router.get("/api/entrevistas/agendamiento/{agendamiento_id}/creador/{creador_id}")
def obtener_detalle_entrevista_por_agendamiento(
    agendamiento_id: int,
    creador_id: int
):
    now = datetime.now()

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    a.id AS agendamiento_id,
                    ap.creador_id,
                    a.titulo,
                    a.descripcion,
                    a.fecha_inicio,
                    a.fecha_fin,
                    a.link_meet,
                    a.tipo_agendamiento,
                    a.estado AS agendamiento_estado,

                    ta.nombre AS tipo_agendamiento_nombre,
                    ta.color AS tipo_agendamiento_color,
                    ta.icono AS tipo_agendamiento_icono,

                    e.id AS entrevista_id,
                    e.entrevista_tipo_id,
                    e.usuario_evalua,
                    e.observaciones,
                    e.aspecto_tecnico,
                    e.presencia_carisma,
                    e.interaccion_audiencia,
                    e.profesionalismo_normas,
                    e.score_total_entrevista,
                    e.score_total,
                    e.estado_id,
                    e.creado_en,

                    et.nombre AS tipo_nombre,
                    et.tipo AS tipo_codigo

                FROM agendamientos a
                JOIN agendamientos_participantes ap
                  ON ap.agendamiento_id = a.id
                LEFT JOIN tipos_agendamiento ta
                  ON ta.id = a.tipo_agendamiento
                LEFT JOIN entrevistas e
                  ON e.agendamiento_id = a.id
                LEFT JOIN entrevista_tipo et
                  ON et.id = e.entrevista_tipo_id
                WHERE a.id = %s
                  AND ap.creador_id = %s
                  AND a.tipo_agendamiento IN (1, 2)
                LIMIT 1
            """, (agendamiento_id, creador_id))

            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="Agendamiento no encontrado para este creador"
                )

            columns = [desc[0] for desc in cur.description]
            item = normalizar_item_db(dict(zip(columns, row)))

            diagnostico_data = obtener_diagnostico_score(cur, creador_id)
            item["diagnostico_score"] = diagnostico_data["puntaje_total"]
            item["diagnostico_resumen"] = diagnostico_data["diagnostico_resumen"]

            if item.get("score_total") is None:
                item["score_total"] = calcular_score_final(
                    item["diagnostico_score"],
                    item.get("score_total_entrevista")
                )

            item["estado_ui"] = calcular_estado_visual(item, now)

            return {
                "success": True,
                "data": serializar_item_pantalla(item)
            }


# =========================================================
# ENDPOINT 3: DETALLE POR ENTREVISTA ID
# =========================================================

@router.get("/api/entrevistas/{entrevista_id}/creador/{creador_id}")
def obtener_entrevista_por_id(entrevista_id: int, creador_id: int):
    now = datetime.now()

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    a.id AS agendamiento_id,
                    ap.creador_id,
                    a.titulo,
                    a.descripcion,
                    a.fecha_inicio,
                    a.fecha_fin,
                    a.link_meet,
                    a.tipo_agendamiento,
                    a.estado AS agendamiento_estado,

                    ta.nombre AS tipo_agendamiento_nombre,
                    ta.color AS tipo_agendamiento_color,
                    ta.icono AS tipo_agendamiento_icono,

                    e.id AS entrevista_id,
                    e.entrevista_tipo_id,
                    e.usuario_evalua,
                    e.observaciones,
                    e.aspecto_tecnico,
                    e.presencia_carisma,
                    e.interaccion_audiencia,
                    e.profesionalismo_normas,
                    e.score_total_entrevista,
                    e.score_total,
                    e.estado_id,
                    e.creado_en,

                    et.nombre AS tipo_nombre,
                    et.tipo AS tipo_codigo

                FROM entrevistas e
                JOIN agendamientos a
                  ON a.id = e.agendamiento_id
                JOIN agendamientos_participantes ap
                  ON ap.agendamiento_id = a.id
                LEFT JOIN tipos_agendamiento ta
                  ON ta.id = a.tipo_agendamiento
                LEFT JOIN entrevista_tipo et
                  ON et.id = e.entrevista_tipo_id
                WHERE e.id = %s
                  AND ap.creador_id = %s
                LIMIT 1
            """, (entrevista_id, creador_id))

            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="Entrevista no encontrada para este creador"
                )

            columns = [desc[0] for desc in cur.description]
            item = normalizar_item_db(dict(zip(columns, row)))

            diagnostico_data = obtener_diagnostico_score(cur, creador_id)
            item["diagnostico_score"] = diagnostico_data["puntaje_total"]
            item["diagnostico_resumen"] = diagnostico_data["diagnostico_resumen"]

            if item.get("score_total") is None:
                item["score_total"] = calcular_score_final(
                    item["diagnostico_score"],
                    item.get("score_total_entrevista")
                )

            item["estado_ui"] = calcular_estado_visual(item, now)

            return {
                "success": True,
                "data": serializar_item_pantalla(item)
            }


# =========================================================
# ENDPOINT 4: EVALUAR POR ENTREVISTA ID
# =========================================================

@router.patch("/api/entrevistas/{entrevista_id}/creador/{creador_id}/evaluar")
def evaluar_entrevista(
    entrevista_id: int,
    creador_id: int,
    data: EntrevistaEvaluacionUpdate
):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    e.id,
                    e.creador_id,
                    e.agendamiento_id
                FROM entrevistas e
                JOIN agendamientos_participantes ap
                  ON ap.agendamiento_id = e.agendamiento_id
                WHERE e.id = %s
                  AND ap.creador_id = %s
                LIMIT 1
            """, (entrevista_id, creador_id))
            base = cur.fetchone()

            if not base:
                raise HTTPException(
                    status_code=404,
                    detail="Entrevista no encontrada para este creador"
                )

            _, creador_id_db, agendamiento_id = base

            diagnostico_data = obtener_diagnostico_score(cur, creador_id)
            diagnostico_score = diagnostico_data["puntaje_total"]
            diagnostico_resumen = diagnostico_data["diagnostico_resumen"]

            score_prueba = calcular_score_prueba(
                data.aspecto_tecnico,
                data.presencia_carisma,
                data.interaccion_audiencia,
                data.profesionalismo_normas
            )

            score_final = calcular_score_final(diagnostico_score, score_prueba)

            cur.execute("""
                UPDATE entrevistas
                SET
                    observaciones = %s,
                    aspecto_tecnico = %s,
                    presencia_carisma = %s,
                    interaccion_audiencia = %s,
                    profesionalismo_normas = %s,
                    score_total_entrevista = %s,
                    score_total = %s,
                    estado_id = %s
                WHERE id = %s
                RETURNING
                    id,
                    creador_id,
                    agendamiento_id,
                    score_total_entrevista,
                    score_total,
                    estado_id
            """, (
                data.observaciones,
                data.aspecto_tecnico,
                data.presencia_carisma,
                data.interaccion_audiencia,
                data.profesionalismo_normas,
                score_prueba,
                score_final,
                data.estado_id,
                entrevista_id
            ))

            updated = cur.fetchone()
            conn.commit()

            return {
                "success": True,
                "message": "Evaluación guardada correctamente",
                "data": {
                    "entrevista_id": updated[0],
                    "creador_id": creador_id_db,
                    "agendamiento_id": updated[2],
                    "scores": {
                        "diagnostico": diagnostico_score,
                        "prueba": to_float(updated[3]),
                        "final": to_float(updated[4]),
                        "nivel_prueba": obtener_nivel_score(to_float(updated[3])),
                        "nivel_final": obtener_nivel_score(to_float(updated[4]))
                    },
                    "diagnostico_resumen": diagnostico_resumen,
                    "decision_sugerida": sugerir_decision(to_float(updated[4])),
                    "estado_id": updated[5]
                }
            }


# =========================================================
# ENDPOINT 5: EVALUAR POR AGENDAMIENTO
# =========================================================

@router.patch("/api/agendamientos/{agendamiento_id}/creador/{creador_id}/evaluar")
def evaluar_por_agendamiento(
    agendamiento_id: int,
    creador_id: int,
    data: EntrevistaEvaluacionUpdate
):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.id, a.tipo_agendamiento
                FROM agendamientos a
                JOIN agendamientos_participantes ap
                  ON ap.agendamiento_id = a.id
                WHERE a.id = %s
                  AND ap.creador_id = %s
                  AND a.tipo_agendamiento IN (1, 2)
                LIMIT 1
            """, (agendamiento_id, creador_id))
            ag = cur.fetchone()

            if not ag:
                raise HTTPException(
                    status_code=404,
                    detail="Agendamiento no encontrado para este creador"
                )

            entrevista_id = asegurar_entrevista_existe(cur, agendamiento_id, creador_id)

            diagnostico_data = obtener_diagnostico_score(cur, creador_id)
            diagnostico_score = diagnostico_data["puntaje_total"]
            diagnostico_resumen = diagnostico_data["diagnostico_resumen"]

            score_prueba = calcular_score_prueba(
                data.aspecto_tecnico,
                data.presencia_carisma,
                data.interaccion_audiencia,
                data.profesionalismo_normas
            )

            score_final = calcular_score_final(diagnostico_score, score_prueba)

            cur.execute("""
                UPDATE entrevistas
                SET
                    observaciones = %s,
                    aspecto_tecnico = %s,
                    presencia_carisma = %s,
                    interaccion_audiencia = %s,
                    profesionalismo_normas = %s,
                    score_total_entrevista = %s,
                    score_total = %s,
                    estado_id = %s
                WHERE id = %s
                RETURNING
                    id,
                    creador_id,
                    agendamiento_id,
                    score_total_entrevista,
                    score_total,
                    estado_id
            """, (
                data.observaciones,
                data.aspecto_tecnico,
                data.presencia_carisma,
                data.interaccion_audiencia,
                data.profesionalismo_normas,
                score_prueba,
                score_final,
                data.estado_id,
                entrevista_id
            ))

            updated = cur.fetchone()
            conn.commit()

            return {
                "success": True,
                "message": "Evaluación guardada correctamente",
                "data": {
                    "entrevista_id": updated[0],
                    "creador_id": updated[1],
                    "agendamiento_id": updated[2],
                    "scores": {
                        "diagnostico": diagnostico_score,
                        "prueba": to_float(updated[3]),
                        "final": to_float(updated[4]),
                        "nivel_prueba": obtener_nivel_score(to_float(updated[3])),
                        "nivel_final": obtener_nivel_score(to_float(updated[4]))
                    },
                    "diagnostico_resumen": diagnostico_resumen,
                    "decision_sugerida": sugerir_decision(to_float(updated[4])),
                    "estado_id": updated[5]
                }
            }


# =========================================================
# ENDPOINT 6: GUARDAR DECISIÓN FINAL
# =========================================================

@router.patch("/api/entrevistas/{entrevista_id}/creador/{creador_id}/decision")
def guardar_decision_final(
    entrevista_id: int,
    creador_id: int,
    data: DecisionUpdate
):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE entrevistas e
                SET
                    decision_final = %s,
                    observacion_decision = %s
                FROM agendamientos_participantes ap
                WHERE e.id = %s
                  AND ap.agendamiento_id = e.agendamiento_id
                  AND ap.creador_id = %s
                RETURNING e.id, e.decision_final, e.observacion_decision
            """, (
                data.decision_final,
                data.observacion_decision,
                entrevista_id,
                creador_id
            ))

            updated = cur.fetchone()
            if not updated:
                raise HTTPException(
                    status_code=404,
                    detail="Entrevista no encontrada para este creador"
                )

            conn.commit()

            return {
                "success": True,
                "message": "Decisión guardada correctamente",
                "data": {
                    "entrevista_id": updated[0],
                    "decision_final": updated[1],
                    "observacion_decision": updated[2]
                }
            }
