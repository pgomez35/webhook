import secrets
import string
from uuid import uuid4

import pytz
import logging
import traceback
import math
from psycopg2 import OperationalError, DatabaseError

from types import SimpleNamespace
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Depends, Query
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
from tenant import current_tenant, current_business_name
from typing import Union



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
        # cur.execute("""
        #             UPDATE perfil_creador
        #             SET id_chatbot_estado = %s,
        #                 actualizado_en    = NOW()
        #             WHERE creador_id = %s
        #             """, (id_chatbot, creador_id))

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
                        UPDATE perfil_creador
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


class PerfilCualitativoPayload(BaseModel):
    puntaje_cualitativo: int = Field(..., ge=0, le=5)
    apariencia: int = Field(..., ge=0, le=5)
    engagement: int = Field(..., ge=0, le=5)
    calidad_contenido: int = Field(..., ge=0, le=5)
    eval_biografia: int = Field(..., ge=0, le=5)
    metadata_videos: int = Field(..., ge=0, le=5)
    eval_foto: int = Field(..., ge=0, le=5)  # solo perfil_creador


@router.post(
    "/api/perfil_creador/{creador_id}/talento/actualizar",
    tags=["Categoria talento"]
)
def sync_cualitativo_perfil_y_variables(
    creador_id: int,
    payload: PerfilCualitativoPayload,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    """
    - Actualiza en perfil_creador: apariencia, engagement, calidad_contenido, eval_biografia, metadata_videos, eval_foto
    - Actualiza/crea en talento_score_variable (score) SOLO para variables que vienen de:
        SELECT id FROM modelo_variable WHERE categoria_id = 1
      Mapeo: usa el campo_db (si existe) o el nombre (fallback) para decidir qué valor poner.
    """
    try:
        # Normaliza valores a int por seguridad (aunque Pydantic ya valida)
        data = payload.model_dump()
        for k, v in data.items():
            try:
                data[k] = int(v)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail=f"{k} debe ser entero")
            if not (0 <= data[k] <= 5):
                raise HTTPException(status_code=400, detail=f"{k} debe estar entre 0 y 5")

        perfil_rows = 0
        upsert_actualizadas = 0
        upsert_insertadas = 0
        variables_procesadas = []

        # Campos que sí existen en payload para mapping
        payload_keys = set(data.keys())  # incluye eval_foto
        # Pero talento_score_variable solo usa estos (sin eval_foto)
        payload_keys_tvs = payload_keys - {"eval_foto"}

        with get_connection_context() as conn:
            with conn.cursor() as cur:

                # 1) Update perfil_creador
                cur.execute("""
                    UPDATE perfil_creador
                    SET apariencia = %s,
                        engagement = %s,
                        calidad_contenido = %s,
                        eval_biografia = %s,
                        metadata_videos = %s,
                        eval_foto = %s,
                        potencial_estimado = %s
                    WHERE creador_id = %s
                """, (
                    data["apariencia"],
                    data["engagement"],
                    data["calidad_contenido"],
                    data["eval_biografia"],
                    data["metadata_videos"],
                    data["eval_foto"],
                    data["puntaje_cualitativo"],
                    creador_id
                ))
                perfil_rows = cur.rowcount

                # 2) Traer variables categoria_id=1 con campo_db para mapear
                cur.execute("""
                    SELECT id, campo_db, nombre
                    FROM modelo_variable
                    WHERE categoria_id = 1
                    ORDER BY id
                """)
                vars_rows = cur.fetchall()

                if not vars_rows:
                    conn.commit()
                    return {
                        "status": "ok",
                        "mensaje": "perfil_creador actualizado. No hay variables en modelo_variable con categoria_id=1",
                        "creador_id": creador_id,
                        "perfil_creador_filas_afectadas": perfil_rows,
                        "talento_score_variable_actualizadas": 0,
                        "talento_score_variable_insertadas": 0,
                        "variables_procesadas": []
                    }

                # 3) Para cada variable, decidir qué score asignar según campo_db / nombre
                #    - campo_db preferido (ej: 'apariencia')
                #    - si campo_db es null, fallback a nombre normalizado
                def normalize_key(s: str) -> str:
                    return (
                        (s or "")
                        .strip()
                        .lower()
                        .replace(" ", "_")
                    )

                # Construye lista de (variable_id, score) solo para las que podamos mapear
                pairs = []
                for var_id, campo_db, nombre in vars_rows:
                    key = normalize_key(campo_db) if campo_db else normalize_key(nombre)
                    if key in payload_keys_tvs:
                        pairs.append((var_id, data[key], key))
                        variables_procesadas.append({"variable_id": var_id, "campo": key, "score": data[key]})
                    else:
                        # No la tocamos: no existe en payload o es eval_foto u otro nombre
                        variables_procesadas.append({"variable_id": var_id, "campo": key, "omitida": True})

                if pairs:
                    var_ids = [p[0] for p in pairs]

                    # 4) Update existentes (por variable_id)
                    #    Usamos un UPDATE con FROM (VALUES ...) para setear score distinto por variable
                    cur.execute("""
                        UPDATE talento_score_variable tvs
                        SET score = v.score
                        FROM (VALUES %s) AS v(variable_id, score)
                        WHERE tvs.creador_id = %s
                          AND tvs.variable_id = v.variable_id
                    """ % ",".join(["(%s,%s)"] * len(pairs)),
                    tuple([x for p in pairs for x in (p[0], p[1])] + [creador_id]))
                    upsert_actualizadas = cur.rowcount

                    # 5) Insert faltantes
                    cur.execute("""
                        INSERT INTO talento_score_variable (creador_id, variable_id, score)
                        SELECT %s, v.variable_id, v.score
                        FROM (VALUES %s) AS v(variable_id, score)
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM talento_score_variable tvs
                            WHERE tvs.creador_id = %s
                              AND tvs.variable_id = v.variable_id
                        )
                    """ % ( "%s", ",".join(["(%s,%s)"] * len(pairs)), "%s" ),
                    tuple([creador_id] + [x for p in pairs for x in (p[0], p[1])] + [creador_id]))
                    upsert_insertadas = cur.rowcount

            conn.commit()

        return {
            "status": "ok",
            "mensaje": "perfil_creador actualizado + talento_score_variable actualizado/insertado para variables categoria_id=1 (mapeadas por campo_db/nombre)",
            "creador_id": creador_id,
            "perfil_creador_filas_afectadas": perfil_rows,
            "talento_score_variable_actualizadas": upsert_actualizadas,
            "talento_score_variable_insertadas": upsert_insertadas,
            "variables_procesadas": variables_procesadas,
            "payload": data
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Error en sync_cualitativo_perfil_y_variables_v1: {str(e)}"
        )


# from fastapi import APIRouter, Depends, HTTPException
# from pydantic import BaseModel, Field
#
# router = APIRouter()


class PerfilCualitativoPayloadOut(BaseModel):
    potencial_estimado: int = Field(..., ge=0, le=5)
    apariencia: int = Field(..., ge=0, le=5)
    engagement: int = Field(..., ge=0, le=5)
    calidad_contenido: int = Field(..., ge=0, le=5)
    eval_biografia: int = Field(..., ge=0, le=5)
    metadata_videos: int = Field(..., ge=0, le=5)
    eval_foto: int = Field(..., ge=0, le=5)


# @router.get(
#     "/api/perfil_creador/{creador_id}/talento/cargar",
#     tags=["Perfil Cualitativo"],
#     response_model=PerfilCualitativoPayloadOut
# )
# def obtener_cualitativo_perfil_creador(
#     creador_id: int,
#     usuario_actual: dict = Depends(obtener_usuario_actual),
# ):
#     try:
#         with get_connection_context() as conn:
#             with conn.cursor() as cur:
#                 cur.execute("""
#                     SELECT
#                         potencial_estimado,
#                         apariencia,
#                         engagement,
#                         calidad_contenido,
#                         eval_biografia,
#                         metadata_videos,
#                         eval_foto
#                     FROM perfil_creador
#                     WHERE creador_id = %s
#                     LIMIT 1
#                 """, (creador_id,))
#                 row = cur.fetchone()
#
#         if not row:
#             raise HTTPException(status_code=404, detail="perfil_creador no encontrado para ese creador_id")
#
#         # row = (potencial_estimado, apariencia, engagement, calidad_contenido, eval_biografia, metadata_videos, eval_foto)
#         data = {
#             "potencial_estimado": row[0],
#             "apariencia": row[1],
#             "engagement": row[2],
#             "calidad_contenido": row[3],
#             "eval_biografia": row[4],
#             "metadata_videos": row[5],
#             "eval_foto": row[6],
#         }
#
#         # Si tu DB puede traer NULL, aquí puedes decidir:
#         # - devolver 0 por defecto, o
#         # - lanzar error si alguno es None.
#         # Yo lo dejo estricto (si hay None, Pydantic se queja). Si quieres defaults, te lo ajusto.
#         return data
#
#     except HTTPException:
#         raise
#     except Exception as e:
#         import traceback
#         traceback.print_exc()
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error al obtener cualitativo de perfil_creador: {str(e)}"
#         )



@router.post("/api/perfil_creador/{creador_id}/pre_resumen/calcularV1",
    tags=["Resumen Pre-Evaluación"]
)
def actualizar_cualitativo_y_recalcular_pre_encuestaV1(
    creador_id: int,
    puntaje_cualitativo: int,  # 0..5
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    try:
        if puntaje_cualitativo is None:
            raise HTTPException(status_code=400, detail="puntaje_cualitativo es requerido")

        try:
            puntaje_cualitativo = int(puntaje_cualitativo)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="puntaje_cualitativo debe ser entero")

        if not (0 <= puntaje_cualitativo <= 5):
            raise HTTPException(status_code=400, detail="puntaje_cualitativo debe estar entre 0 y 5")

        categoria_cualitativa = convertir_1a5_a_1a3(puntaje_cualitativo)

        # 1️⃣ Guardar cualitativo
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE perfil_creador
                    SET puntaje_cualitativo = %s,
                        puntaje_cualitativo_categoria = %s
                    WHERE creador_id = %s
                """, (
                    puntaje_cualitativo,
                    categoria_cualitativa,
                    creador_id
                ))

        # 2️⃣ Recalcular total ponderado
        resumen = recalcular_y_guardar_pre_total_ponderado(
            creador_id=creador_id,
            puntaje_cualitativo=puntaje_cualitativo
        )

        return {
            "status": "ok",
            "mensaje": "puntaje_cualitativo actualizado y total recalculado",
            "creador_id": creador_id,
            "puntaje_cualitativo": puntaje_cualitativo,
            "puntaje_cualitativo_categoria": categoria_cualitativa,
            "resumen": resumen
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Error al actualizar cualitativo/recalcular: {str(e)}"
        )

def recalcular_y_guardar_pre_total_ponderado(
    creador_id: int,
    puntaje_cualitativo: int | None = None,
):
    """
    Recalcula y guarda puntaje_total con ponderación:
    estad 20%, personales 20%, hábitos 30%, cualitativo 30%
    """

    PESOS = {
        "estadistica": 0.20,
        "personales": 0.20,
        "habitos": 0.30,
        "cualitativo": 0.30,
    }

    def safe_float(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    puntaje_estadistica,
                    puntaje_general,
                    puntaje_habitos,
                    puntaje_cualitativo
                FROM perfil_creador
                WHERE creador_id = %s
                LIMIT 1
            """, (creador_id,))
            row = cur.fetchone()

            if not row:
                return {
                    "status": "error",
                    "msg": "perfil_creador no encontrado",
                    "creador_id": creador_id
                }

            puntaje_est, puntaje_gen, puntaje_hab, puntaje_cual_db = row

            # Prioridad al valor pasado por parámetro
            puntaje_cual = puntaje_cualitativo if puntaje_cualitativo is not None else puntaje_cual_db

            puntaje_est = safe_float(puntaje_est)
            puntaje_gen = safe_float(puntaje_gen)
            puntaje_hab = safe_float(puntaje_hab)
            puntaje_cual = safe_float(puntaje_cual)

            suma = 0.0
            suma_pesos = 0.0

            if puntaje_est is not None:
                suma += puntaje_est * PESOS["estadistica"]
                suma_pesos += PESOS["estadistica"]

            if puntaje_gen is not None:
                suma += puntaje_gen * PESOS["personales"]
                suma_pesos += PESOS["personales"]

            if puntaje_hab is not None:
                suma += puntaje_hab * PESOS["habitos"]
                suma_pesos += PESOS["habitos"]

            if puntaje_cual is not None:
                suma += puntaje_cual * PESOS["cualitativo"]
                suma_pesos += PESOS["cualitativo"]

            puntaje_total = round(suma / suma_pesos, 2) if suma_pesos > 0 else None
            puntaje_total_categoria = convertir_1a5_a_1a3(puntaje_total)

            cur.execute("""
                UPDATE perfil_creador
                SET puntaje_total = %s,
                    puntaje_total_categoria = %s
                WHERE creador_id = %s
            """, (
                round(puntaje_total) if puntaje_total is not None else None,
                puntaje_total_categoria,
                creador_id
            ))

            return {
                "status": "ok",
                "puntaje_total": puntaje_total,
                "puntaje_total_categoria": puntaje_total_categoria,
                "pesos": PESOS
            }




def recalcular_y_guardar_pre_resumen_v2(
    creador_id: int,
    puntaje_cualitativo: int | None = None
):
    """
    Recalcula el total incluyendo:
      - puntaje_estadistica
      - puntaje_general
      - puntaje_habitos
      - puntaje_manual (cualitativo)

    Guarda en perfil_creador:
      - puntaje_total
      - puntaje_total_categoria
    (y opcionalmente puedes guardar promedios si tienes campos)
    """

    # Pesos por defecto (ajústalos a tu decisión final)
    # OJO: esto es solo propuesta. Cambia si tu negocio quiere otra cosa.
    pesos_default = {
        "estadistica": 0.20,
        "general": 0.20,
        "habitos": 0.30,
        "cualitativo": 0.30,
    }
    w =  pesos_default

    def safe_float(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    puntaje_estadistica,
                    puntaje_general,
                    puntaje_habitos,
                    puntaje_manual
                FROM perfil_creador
                WHERE creador_id = %s
                LIMIT 1
            """, (creador_id,))
            row = cur.fetchone()

            if not row:
                return {"status": "error", "msg": "perfil_creador no encontrado"}

            puntaje_est, puntaje_gen, puntaje_hab, puntaje_man_db = row

            # Determinar cualitativo: prioridad al parámetro, si no al DB
            puntaje_cual = puntaje_cualitativo if puntaje_cualitativo is not None else puntaje_man_db

            puntaje_est = safe_float(puntaje_est)
            puntaje_gen = safe_float(puntaje_gen)
            puntaje_hab = safe_float(puntaje_hab)
            puntaje_cual = safe_float(puntaje_cual)

            # Promedios útiles (no guardo si no tienes columnas)
            puntajes_presentes = [p for p in [puntaje_est, puntaje_gen, puntaje_hab, puntaje_cual] if p is not None]
            promedio_simple = round(sum(puntajes_presentes) / len(puntajes_presentes), 2) if puntajes_presentes else None

            # Total ponderado con renormalización si falta alguno
            suma = 0.0
            suma_pesos = 0.0

            if puntaje_est is not None:
                suma += puntaje_est * w["estadistica"]
                suma_pesos += w["estadistica"]

            if puntaje_gen is not None:
                suma += puntaje_gen * w["general"]
                suma_pesos += w["general"]

            if puntaje_hab is not None:
                suma += puntaje_hab * w["habitos"]
                suma_pesos += w["habitos"]

            if puntaje_cual is not None:
                suma += puntaje_cual * w["cualitativo"]
                suma_pesos += w["cualitativo"]

            puntaje_total = round(suma / suma_pesos, 2) if suma_pesos > 0 else None
            puntaje_total_cat = convertir_1a5_a_1a3(puntaje_total)

            # Guardar total
            cur.execute("""
                UPDATE perfil_creador
                SET puntaje_total = %s,
                    puntaje_total_categoria = %s
                WHERE creador_id = %s
            """, (round(puntaje_total) if puntaje_total is not None else None,
                  puntaje_total_cat,
                  creador_id))

            return {
                "status": "ok",
                "puntaje_estadistica": puntaje_est,
                "puntaje_general": puntaje_gen,
                "puntaje_habitos": puntaje_hab,
                "puntaje_cualitativo": puntaje_cual,
                "promedio_simple": promedio_simple,
                "puntaje_total": puntaje_total,
                "puntaje_total_categoria": puntaje_total_cat,
                "pesos": w,
            }

import json
from fastapi import Depends, HTTPException

import json

def _obtener_pre_resumen_guardado(creador_id: int) -> dict:
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    edad,
                    seguidores,
                    puntaje_estadistica,
                    puntaje_estadistica_categoria,
                    puntaje_general,
                    puntaje_general_categoria,
                    puntaje_habitos,
                    puntaje_habitos_categoria,
                    puntaje_cualitativo,
                    puntaje_cualitativo_categoria,
                    puntaje_total,
                    puntaje_total_categoria,
                    experiencia_otras_plataformas
                FROM perfil_creador
                WHERE creador_id = %s
                LIMIT 1
            """, (creador_id,))
            row = cur.fetchone()

    if not row:
        return {"status": "error"}

    (
        edad,
        seguidores,
        puntaje_estadistica,
        puntaje_estadistica_categoria,
        puntaje_general,
        puntaje_general_categoria,
        puntaje_habitos,
        puntaje_habitos_categoria,
        puntaje_cualitativo,
        puntaje_cualitativo_categoria,
        puntaje_total,
        puntaje_total_categoria,
        experiencia_otras_plataformas,
    ) = row

    # ✅ calcular alerta (sin columna en DB)
    alerta = 0
    try:
        if edad == 1:
            alerta = 1
        elif seguidores is not None and seguidores < 50:
            alerta = 2
    except Exception:
        alerta = 0

    # parse experiencia si viene JSON string
    exp = experiencia_otras_plataformas or {}
    if isinstance(exp, str):
        try:
            exp = json.loads(exp)
        except Exception:
            exp = {}

    return {
        "status": "ok",
        "edad": edad,
        "seguidores": seguidores,
        "puntaje_estadistica": puntaje_estadistica,
        "puntaje_estadistica_categoria": puntaje_estadistica_categoria,
        "puntaje_general": puntaje_general,
        "puntaje_general_categoria": puntaje_general_categoria,
        "puntaje_habitos": puntaje_habitos,
        "puntaje_habitos_categoria": puntaje_habitos_categoria,
        "puntaje_cualitativo": puntaje_cualitativo,
        "puntaje_cualitativo_categoria": puntaje_cualitativo_categoria,
        "puntaje_total": puntaje_total,
        "puntaje_total_categoria": puntaje_total_categoria,
        "alerta": alerta,
        "experiencia_otras_plataformas": exp,
    }


@router.get(
    "/api/perfil_creador/{creador_id}/pre_resumen",
    tags=["Resumen Pre-Evaluación"],
    response_model=ResumenEvaluacionOutput
)
def obtener_pre_resumen(
    creador_id: int,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    # ✅ 1) Leer lo ya calculado/guardado (NO recalcula)
    resultado = _obtener_pre_resumen_guardado(creador_id)
    if resultado.get("status") != "ok":
        raise HTTPException(status_code=404, detail="Perfil no encontrado")

    # ✅ 2) Diagnóstico (usa DB; tu función ya debe parsear JSON internamente)
    try:
        # Si tu diagnostico usa obtener_datos_mejoras_perfil_creador y lee DB,
        # perfecto: no recalcula puntajes.
        diagnostico = diagnostico_perfil_creador_pre(creador_id, puntajes_calculados=resultado)
    except Exception:
        diagnostico = "-"

    texto = (
        f"📊 Pre-Evaluación:\n"
        f"Puntaje parcial: {resultado.get('puntaje_total')}\n"
        f"Categoría: {resultado.get('puntaje_total_categoria')}\n\n"
        f"🩺 Diagnóstico Preliminar:\n{diagnostico}\n"
    )

    # ✅ 3) Decision (ya no potencial_estimado; ahora es puntaje_cualitativo)
    calidad_visual_val = resultado.get("puntaje_cualitativo")
    puntaje_total_val = resultado.get("puntaje_total")

    # Evitar fallos por None
    puntaje_total_int = int(round(float(puntaje_total_val))) if puntaje_total_val is not None else 0

    decision = sugerencia_decision_final(
        resultado.get("alerta") or 0,
        puntaje_total=puntaje_total_int,
        calidad_visual_cualitativo=calidad_visual_val
    )

    # ✅ 4) Respuesta final (solo lectura)
    return ResumenEvaluacionOutput(
        status="ok",
        mensaje="Resumen preliminar consultado",

        puntaje_estadistica=resultado.get("puntaje_estadistica"),
        puntaje_estadistica_categoria=resultado.get("puntaje_estadistica_categoria"),

        puntaje_general=resultado.get("puntaje_general"),
        puntaje_general_categoria=resultado.get("puntaje_general_categoria"),

        puntaje_habitos=resultado.get("puntaje_habitos"),
        puntaje_habitos_categoria=resultado.get("puntaje_habitos_categoria"),

        puntaje_cualitativo=resultado.get("puntaje_cualitativo"),
        puntaje_cualitativo_categoria=resultado.get("puntaje_cualitativo_categoria"),

        puntaje_total=resultado.get("puntaje_total"),
        puntaje_total_categoria=resultado.get("puntaje_total_categoria"),
        # Si ya guardas puntaje_total_categoria, esto podría sobrar:
        puntaje_total_categoria_Ajustado=convertir_1a5_a_1a3(resultado.get("puntaje_total")),

        # Ya no los tienes si eliminaste ponderado/potencial_estimado
        puntaje_total_ponderado=None,
        puntaje_total_ponderado_cat=None,

        diagnostico=texto,
        mejoras_sugeridas=None,

        potencial_estimado=None,
        potencial_estimado_texto=None,

        decision_icono=decision.get("decision_icono"),
        decision=decision.get("decision"),
        recomendacion=decision.get("recomendacion"),
    )



@router.get("/api/perfil_creador/{creador_id}/pre_resumenV1",
         tags=["Resumen Pre-Evaluación"],
         response_model=ResumenEvaluacionOutput)
def obtener_pre_resumenV1(creador_id: int, usuario_actual: dict = Depends(obtener_usuario_actual)):

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

        puntaje_cualitativo=None,
        puntaje_cualitativo_categoria=None,

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




# ------------------------------
# ------------------------------
# ------------------------------
# ------------------------------
# -------NUEVO MODELO---------
# -------NUEVO MODELO---------
# -------NUEVO MODELO---------
# ------------------------------
# ------------------------------
# ------------------------------


class ModeloEvaluacionOut(BaseModel):
    id: int
    nombre: str
    descripcion: Optional[str]
    activo: bool

    class Config:
        orm_mode = True


class ModeloEvaluacionCreate(BaseModel):
    nombre: str = Field(..., max_length=100)
    descripcion: Optional[str] = None


class ModeloCategoriaOut(BaseModel):
    id: int
    nombre: str
    peso_categoria: float

    class Config:
        orm_mode = True


class ModeloCategoriaCreate(BaseModel):
    nombre: str
    peso_categoria: float


class ModeloVariableOut(BaseModel):
    id: int
    nombre: str
    campo_db: Optional[str]
    peso_variable: float
    tipo: str

    class Config:
        orm_mode = True


class ModeloVariableCreate(BaseModel):
    nombre: str
    campo_db: Optional[str] = None
    peso_variable: float
    tipo: str  # cuantitativa / cualitativa / declarativa


class TalentoScoreCreate(BaseModel):
    variable_id: int
    score: int = Field(..., ge=1, le=5)


class EvaluacionResultadoOut(BaseModel):
    modelo_id: int
    puntaje_total: float
    categoria_final: str
    fecha: datetime

    class Config:
        orm_mode = True

class ModeloEvaluacionUpdate(BaseModel):
    activo: bool

class CategoriaPesoUpdate(BaseModel):
    id: int
    peso_categoria: float

class ModeloCategoriasUpdate(BaseModel):
    categorias: List[CategoriaPesoUpdate]

@router.get("/api/modelos-evaluacion", response_model=List[ModeloEvaluacionOut])
def listar_modelos(activos: bool = Query(True)):
    TENANT = current_tenant.get()

    if not TENANT:
        raise HTTPException(status_code=400, detail="Tenant no disponible")

    with get_connection_context() as conn:
        cur = conn.cursor()

        # 🔥 Base de la consulta
        query = """
            SELECT id, nombre, descripcion, activo
            FROM modelo_evaluacion
        """

        params = []

        # ✅ Agregar condición dinámicamente
        if activos:
            query += " WHERE activo = TRUE"

        query += " ORDER BY id ASC"

        cur.execute(query, params)
        rows = cur.fetchall()

    return [
        ModeloEvaluacionOut(
            id=r[0],
            nombre=r[1],
            descripcion=r[2],
            activo=r[3]
        )
        for r in rows
    ]


@router.post("/api/modelos-evaluacion")
def crear_modelo(data: ModeloEvaluacionCreate):
    TENANT = current_tenant.get()
    if not TENANT:
        raise HTTPException(status_code=400, detail="Tenant no disponible")

    with get_connection_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO modelo_evaluacion (nombre, descripcion)
            VALUES (%s, %s)
            RETURNING id
        """, (data.nombre, data.descripcion))

        modelo_id = cur.fetchone()[0]
        conn.commit()

    return {"id": modelo_id}


@router.get("/api/modelos-evaluacion/{modelo_id}/categorias",
            response_model=List[ModeloCategoriaOut])
def listar_categorias(modelo_id: int):
    TENANT = current_tenant.get()
    if not TENANT:
        raise HTTPException(status_code=400, detail="Tenant no disponible")

    with get_connection_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, nombre, peso_categoria
            FROM modelo_categoria
            WHERE modelo_id = %s
            ORDER BY id ASC
        """, (modelo_id,))

        rows = cur.fetchall()

    return [
        ModeloCategoriaOut(
            id=r[0],
            nombre=r[1],
            peso_categoria=r[2]
        )
        for r in rows
    ]


@router.post("/api/modelos-evaluacion/{modelo_id}/categorias")
def crear_categoria(modelo_id: int, data: ModeloCategoriaCreate):
    TENANT = current_tenant.get()
    if not TENANT:
        raise HTTPException(status_code=400, detail="Tenant no disponible")

    with get_connection_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO modelo_categoria (modelo_id, nombre, peso_categoria)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (modelo_id, data.nombre, data.peso_categoria))

        categoria_id = cur.fetchone()[0]
        conn.commit()

    return {"id": categoria_id}


@router.get("/api/categorias/{categoria_id}/variables",
            response_model=List[ModeloVariableOut])
def listar_variables(categoria_id: int):
    TENANT = current_tenant.get()
    if not TENANT:
        raise HTTPException(status_code=400, detail="Tenant no disponible")

    with get_connection_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, nombre, campo_db, peso_variable, tipo
            FROM modelo_variable
            WHERE categoria_id = %s
            ORDER BY id ASC
        """, (categoria_id,))

        rows = cur.fetchall()

    return [
        ModeloVariableOut(
            id=r[0],
            nombre=r[1],
            campo_db=r[2],
            peso_variable=r[3],
            tipo=r[4]
        )
        for r in rows
    ]


@router.post("/api/categorias/{categoria_id}/variables")
def crear_variable(categoria_id: int, data: ModeloVariableCreate):
    TENANT = current_tenant.get()
    if not TENANT:
        raise HTTPException(status_code=400, detail="Tenant no disponible")

    with get_connection_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO modelo_variable 
            (categoria_id, nombre, campo_db, peso_variable, tipo)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (
            categoria_id,
            data.nombre,
            data.campo_db,
            data.peso_variable,
            data.tipo
        ))

        variable_id = cur.fetchone()[0]
        conn.commit()

    return {"id": variable_id}

@router.post("/api/creadores/{creador_id}/talento-score")
def guardar_talento_score(creador_id: int, data: TalentoScoreCreate):
    TENANT = current_tenant.get()
    if not TENANT:
        raise HTTPException(status_code=400, detail="Tenant no disponible")

    with get_connection_context() as conn:
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO talento_score_variable 
            (creador_id, variable_id, score)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (creador_id, data.variable_id, data.score))

        conn.commit()

    return {"ok": True}


@router.post("/api/creadores/{creador_id}/evaluar/{modelo_id}")
def evaluar_creador(creador_id: int, modelo_id: int):

    TENANT = current_tenant.get()
    if not TENANT:
        raise HTTPException(status_code=400, detail="Tenant no disponible")

    resultado = calcular_evaluacion(creador_id, modelo_id)

    with get_connection_context() as conn:
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO evaluacion_resultado
            (creador_id, modelo_id, 
             puntaje_total, puntaje_talento,
             puntaje_mercado, puntaje_operativa,
             puntaje_intencion, categoria_final,
             recomendacion)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            creador_id,
            modelo_id,
            resultado["total"],
            resultado["talento"],
            resultado["mercado"],
            resultado["operativa"],
            resultado["intencion"],
            resultado["categoria"],
            resultado["recomendacion"]
        ))

        conn.commit()

    return resultado


@router.get("/api/creadores/{creador_id}/resultados",
            response_model=List[EvaluacionResultadoOut])
def listar_resultados(creador_id: int):

    TENANT = current_tenant.get()
    if not TENANT:
        raise HTTPException(status_code=400, detail="Tenant no disponible")

    with get_connection_context() as conn:
        cur = conn.cursor()

        cur.execute("""
            SELECT modelo_id,
                   puntaje_total,
                   categoria_final,
                   created_at
            FROM evaluacion_resultado
            WHERE creador_id = %s
            ORDER BY created_at DESC
        """, (creador_id,))

        rows = cur.fetchall()

    return [
        EvaluacionResultadoOut(
            modelo_id=r[0],
            puntaje_total=r[1],
            categoria_final=r[2],
            fecha=r[3]
        )
        for r in rows
    ]

@router.put("/api/modelos-evaluacion/{modelo_id}/estado")
def actualizar_estado_modelo(
    modelo_id: int,
    data: ModeloEvaluacionUpdate
):
    TENANT = current_tenant.get()

    if not TENANT:
        raise HTTPException(status_code=400, detail="Tenant no disponible")

    with get_connection_context() as conn:
        cur = conn.cursor()

        # 🔍 Verificar que el modelo exista
        cur.execute("""
            SELECT id
            FROM modelo_evaluacion
            WHERE id = %s
        """, (modelo_id,))

        modelo = cur.fetchone()

        if not modelo:
            raise HTTPException(
                status_code=404,
                detail="Modelo de evaluación no encontrado"
            )

        # ✅ 1. Colocar TODOS los modelos en FALSE
        cur.execute("""
            UPDATE modelo_evaluacion
            SET activo = FALSE
        """)

        # ✅ 2. Si el usuario quiere activar → activar solo el seleccionado
        if data.activo:
            cur.execute("""
                UPDATE modelo_evaluacion
                SET activo = TRUE
                WHERE id = %s
            """, (modelo_id,))

        conn.commit()

    return {
        "modelo_id": modelo_id,
        "activo": data.activo,
        "mensaje": "Estado actualizado correctamente. Solo un modelo puede estar activo."
    }


@router.put("/api/modelos-evaluacion/{modelo_id}/categorias")
def actualizar_pesos_categorias(modelo_id: int, data: ModeloCategoriasUpdate):
    TENANT = current_tenant.get()
    if not TENANT:
        raise HTTPException(status_code=400, detail="Tenant no disponible")

    with get_connection_context() as conn:
        cur = conn.cursor()
        for c in data.categorias:
            cur.execute("""
                UPDATE modelo_categoria
                SET peso_categoria = %s
                WHERE id = %s AND modelo_id = %s
            """, (c.peso_categoria, c.id, modelo_id))
        conn.commit()
    return {"ok": True}


def calcular_evaluacion(creador_id: int, modelo_id: int):

    with get_connection_context() as conn:
        cur = conn.cursor()

        # 1️⃣ Obtener categorías
        cur.execute("""
            SELECT id, nombre, peso_categoria
            FROM modelo_categoria
            WHERE modelo_id = %s
        """, (modelo_id,))
        categorias = cur.fetchall()

        total_score = 0
        detalle = {}

        for cat_id, cat_nombre, cat_peso in categorias:

            # 2️⃣ Obtener variables de la categoría
            cur.execute("""
                SELECT id, campo_db, peso_variable, tipo
                FROM modelo_variable
                WHERE categoria_id = %s
            """, (cat_id,))
            variables = cur.fetchall()

            subtotal_categoria = 0

            for var_id, campo_db, peso_variable, tipo in variables:

                valor_normalizado = 0

                # 🔹 CUALITATIVA (ej: talento 1–5)
                if tipo == "cualitativa":
                    cur.execute("""
                        SELECT score
                        FROM talento_score_variable
                        WHERE creador_id = %s
                        AND variable_id = %s
                    """, (creador_id, var_id))
                    row = cur.fetchone()

                    if row:
                        valor_normalizado = row[0] / 5  # normaliza a 0–1

                # 🔹 CUANTITATIVA (desde perfil_creador)
                elif tipo == "cuantitativa" and campo_db:
                    cur.execute(f"""
                        SELECT {campo_db}
                        FROM perfil_creador
                        WHERE id = %s
                    """, (creador_id,))
                    row = cur.fetchone()

                    if row and row[0] is not None:
                        valor_normalizado = normalizar_cuantitativa(row[0])

                # 🔹 DECLARATIVA (horas, dias, objetivo, etc.)
                elif tipo == "declarativa" and campo_db:
                    cur.execute(f"""
                        SELECT {campo_db}
                        FROM perfil_creador
                        WHERE id = %s
                    """, (creador_id,))
                    row = cur.fetchone()

                    if row:
                        valor_normalizado = normalizar_declarativa(row[0])

                subtotal_categoria += valor_normalizado * (peso_variable / 100)

            puntaje_categoria = subtotal_categoria * (cat_peso / 100)
            total_score += puntaje_categoria
            detalle[cat_nombre.lower()] = round(puntaje_categoria, 4)

        categoria_final = clasificar_score(total_score)

        return {
            "total": round(total_score, 4),
            "talento": detalle.get("talento", 0),
            "mercado": detalle.get("mercado", 0),
            "operativa": detalle.get("operativa", 0),
            "intencion": detalle.get("intencion", 0),
            "categoria": categoria_final,
            "recomendacion": generar_recomendacion(categoria_final)
        }


# ============================================================
# 🔵 NORMALIZACIÓN CUANTITATIVA
# ============================================================

def normalizar_cuantitativa(
    valor: Union[int, float],
    minimo: float = 0,
    maximo: float = 1_000_000,
    usar_log: bool = False
) -> float:
    """
    Normaliza variables cuantitativas al rango 0–1.

    - Si usar_log=True → usa escala logarítmica (ideal para seguidores/likes)
    - Si usar_log=False → usa min-max scaling tradicional
    """

    if valor is None:
        return 0.0

    try:
        valor = float(valor)
    except Exception:
        return 0.0

    if valor <= minimo:
        return 0.0

    if usar_log:
        # Escala logarítmica
        if valor <= 0:
            return 0.0

        valor_log = math.log10(valor + 1)
        max_log = math.log10(maximo + 1)

        if max_log == 0:
            return 0.0

        resultado = valor_log / max_log
        return round(min(resultado, 1.0), 4)

    # 🔵 Escala lineal tradicional
    if valor >= maximo:
        return 1.0

    resultado = (valor - minimo) / (maximo - minimo)
    return round(max(resultado, 0.0), 4)


# ============================================================
# 🔵 NORMALIZACIÓN DECLARATIVA
# ============================================================

def normalizar_declarativa(valor) -> float:
    """
    Normaliza variables declarativas.

    - Si es número (1–5) → lo escala a 0–1
    - Si es texto → usa mapeo categórico
    """

    if valor is None:
        return 0.0

    # ✅ Caso numérico
    if isinstance(valor, (int, float)):
        valor = float(valor)
        valor = max(1, min(valor, 5))  # limitar entre 1 y 5
        return round(valor / 5, 4)

    # ✅ Caso texto
    texto = str(valor).strip().lower()

    mapping = {
        "muy bajo": 0.1,
        "bajo": 0.2,
        "media": 0.5,
        "medio": 0.5,
        "alta": 0.8,
        "alto": 0.8,
        "muy alto": 1.0,
        "alto compromiso": 1.0,
        "baja": 0.2
    }

    return mapping.get(texto, 0.0)


# ============================================================
# 🔵 CLASIFICACIÓN DEL SCORE FINAL
# ============================================================

def clasificar_score(score: float) -> str:
    """
    Clasifica el score total en niveles estratégicos.
    """

    if score is None:
        return "Muy Bajo"

    if score < 0.2:
        return "Muy Bajo"
    elif score < 0.4:
        return "Bajo"
    elif score < 0.6:
        return "Medio"
    elif score < 0.8:
        return "Alto"
    else:
        return "Muy Alto"


# ============================================================
# 🔵 GENERACIÓN DE RECOMENDACIONES AUTOMÁTICAS
# ============================================================

def generar_recomendacion(categoria: str) -> str:
    """
    Genera recomendaciones automáticas según el nivel obtenido.
    """

    recomendaciones = {
        "Muy Bajo": """
🔴 Perfil con bajo potencial detectado.

Recomendaciones:
- Mejorar calidad de contenido
- Trabajar consistencia
- Aumentar interacción con audiencia
- Optimizar perfil y bio
        """,

        "Bajo": """
🟡 Potencial limitado.

Recomendaciones:
- Mejorar engagement
- Aumentar frecuencia de publicación
- Trabajar identidad de marca
- Mejorar estrategia de contenido
        """,

        "Medio": """
🟢 Buen perfil con oportunidad de crecimiento.

Recomendaciones:
- Optimizar estrategia
- Mejorar retención
- Aumentar conversión
- Fortalecer comunidad
        """,

        "Alto": """
🔵 Perfil fuerte.

Recomendaciones:
- Escalar audiencia
- Buscar alianzas estratégicas
- Activar monetización avanzada
- Diversificar contenido
        """,

        "Muy Alto": """
🏆 Perfil excelente.

Recomendaciones:
- Expansión de marca personal
- Contratos y colaboraciones premium
- Automatizar ingresos
- Construir autoridad en la industria
        """
    }

    return recomendaciones.get(
        categoria,
        "Sin recomendaciones disponibles."
    )


# ------------------------------------------------------
# ------------------------------------------------------
# -------FUNCIONES ---------
# ------------------------------------------------------
# ------------------------------------------------------
# ------------------------------------------------------



# from database import get_connection_context

def evaluar_potencial_talento(
        apariencia: int = None,
        engagement: int = None,
        calidad_contenido: int = None,
        eval_biografia: int = None,
        metadata_videos: int = None
):
    """
    Calcula el 'Potencial de Talento' (1-5) para el SaaS.
    Lee los pesos (20% c/u) desde modelo_variable usando los 5 campos activos.
    """

    # 1. Emparejar las 5 variables exactas con sus nombres en la BD
    valores = {
        "apariencia": apariencia,
        "engagement": engagement,
        "calidad_contenido": calidad_contenido,
        "eval_biografia": eval_biografia,
        "metadata_videos": metadata_videos
    }

    # 2. Consultar pesos dinámicos desde la BD
    pesos_db = {}
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                            SELECT campo_db, peso_variable
                            FROM modelo_variable
                            WHERE categoria_id = 1
                            """)
                for campo, peso in cur.fetchall():
                    pesos_db[campo] = float(peso)
    except Exception as e:
        print(f"❌ Error al consultar pesos de talento en BD: {e}")
        # Fallback de seguridad: 20% exacto para cada una si la BD falla
        pesos_db = {k: 20.0 for k in valores.keys()}

    suma = 0.0
    suma_pesos = 0.0

    # 3. Ponderación dinámica (solo con los valores que NO son nulos)
    for clave, valor in valores.items():
        if valor is not None:
            # Obtenemos el peso de la BD (ej. 20.0)
            peso_actual = pesos_db.get(clave, 0.0)

            val_float = float(valor)
            suma += val_float * peso_actual
            suma_pesos += peso_actual

    # 4. Prevención de división por cero (si el evaluador no ha calificado nada aún)
    if suma_pesos == 0:
        return {
            "score_talento": 0.0,
            "etiqueta_talento": "Sin Evaluar"
        }

    # 5. Cálculo final (Garantizado entre 1.0 y 5.0)
    score_talento = round(suma / suma_pesos, 2)

    # 6. Etiquetas Comerciales (Dashboard SaaS)
    if score_talento < 2.0:
        etiqueta = "Descartable"
    elif score_talento < 3.0:
        etiqueta = "En Desarrollo"
    elif score_talento < 4.0:
        etiqueta = "Promedio"
    elif score_talento < 4.6:
        etiqueta = "Alto Potencial"
    else:
        etiqueta = "Top Talent 🔥"

    return {
        "score_talento": score_talento,
        "etiqueta_talento": etiqueta
    }


def evaluar_potencial_mercado(
        seguidores: int = None,
        likes: int = None,
        engagement: float = None,
        videos: int = None
):
    """
    Calcula el 'Potencial de Mercado' (1-5) para el SaaS usando
    la lógica base original, escalada a 5 y con pesos dinámicos.
    """

    # ==========================================
    # 1. LIMPIEZA DE ENTRADAS
    # ==========================================
    seg_val = int(seguidores or 0)
    lik_val = int(likes or 0)
    vid_val = int(videos or 0)
    eng_val = float(engagement or 0.0)

    # Corte duro original: Si tiene menos de 50 seguidores, se descarta.
    if seg_val < 50:
        return {
            "score_mercado": 0.0,
            "etiqueta_mercado": "Audiencia Nula"
        }

    # ==========================================
    # 2. ESCALAS DE EVALUACIÓN (Lógica base 0-4)
    # ==========================================
    # Seguidores
    if seg_val <= 500:
        seg_score = 2
    elif seg_val <= 1000:
        seg_score = 3
    else:
        seg_score = 4

    # Videos
    if vid_val <= 0:
        vid_score = 0
    elif vid_val < 10:
        vid_score = 1
    elif vid_val <= 20:
        vid_score = 2
    elif vid_val <= 40:
        vid_score = 3
    else:
        vid_score = 4

    # Engagement (Usando tus cortes de likes_normalizado)
    if eng_val <= 0:
        eng_score = 0
    elif eng_val < 0.02:
        eng_score = 1
    elif eng_val <= 0.05:
        eng_score = 2
    elif eng_val <= 0.10:
        eng_score = 3
    else:
        eng_score = 4

    # Likes crudos (Nueva métrica adaptada a la escala 0-4)
    if lik_val <= 500:
        lik_score = 1
    elif lik_val <= 5000:
        lik_score = 2
    elif lik_val <= 15000:
        lik_score = 3
    else:
        lik_score = 4

    # ==========================================
    # 3. CONVERSIÓN A ESCALA 1-5 (Multiplicador 1.25)
    # ==========================================
    valores_escala_5 = {
        "seguidores": seg_score * 1.25,
        "videos": vid_score * 1.25,
        "engagement": eng_score * 1.25,
        "likes": lik_score * 1.25
    }

    # ==========================================
    # 4. CONSULTA DE PESOS EN BD (modelo_variable)
    # ==========================================
    pesos_db = {}
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                            SELECT campo_db, peso_variable
                            FROM modelo_variable
                            WHERE categoria_id = 2
                            """)
                for campo, peso in cur.fetchall():
                    pesos_db[campo] = float(peso)
    except Exception as e:
        print(f"❌ Error al consultar pesos de mercado en BD: {e}")
        # Fallback de seguridad usando tu script de INSERT
        pesos_db = {
            "seguidores": 29.41,
            "likes": 23.53,
            "engagement": 23.53,
            "videos": 23.53
        }

    # ==========================================
    # 5. PONDERACIÓN DINÁMICA
    # ==========================================
    suma = 0.0
    suma_pesos = 0.0

    for clave, valor_escala in valores_escala_5.items():
        peso_actual = pesos_db.get(clave, 0.0)
        suma += valor_escala * peso_actual
        suma_pesos += peso_actual

    if suma_pesos == 0:
        return {
            "score_mercado": 0.0,
            "etiqueta_mercado": "Sin Tracción"
        }

    # Cálculo final
    score_mercado = round(suma / suma_pesos, 2)

    # ==========================================
    # 6. ETIQUETAS COMERCIALES (Dashboard SaaS)
    # ==========================================
    if score_mercado < 2.0:
        etiqueta = "Audiencia Nula"
    elif score_mercado < 3.0:
        etiqueta = "Audiencia Base"
    elif score_mercado < 4.0:
        etiqueta = "Micro-Influencer"
    elif score_mercado < 4.6:
        etiqueta = "Creador Estable"
    else:
        etiqueta = "Influencer / Alto Alcance 🚀"

    return {
        "score_mercado": score_mercado,
        "etiqueta_mercado": etiqueta
    }


# from database import get_connection_context

def evaluar_capacidad_operativa(
        duracion_emisiones=None,
        dias_emisiones=None,
        frecuencia_lives=None,
        tiempo_disponible=None
):
    """
    Calcula la 'Capacidad Operativa' (1-5) para el SaaS.
    Convierte las variables de tiempo y hábitos en una escala de 1-5
    y aplica los pesos dinámicos de la BD (modelo_variable, Categoría 3).
    """

    # ==========================================
    # 1. NORMALIZACIÓN (De datos crudos a escala 1-5)
    # ==========================================

    def normalizar_duracion(dur):
        # Asumiendo que viene en minutos (basado en tus cortes anteriores)
        if dur is None: return None
        try:
            d = float(dur)
            if d < 20: return 1.0  # Muy corta
            if d < 60: return 2.0  # Menos de 1 hora
            if d < 120: return 3.0  # 1 a 2 horas
            if d < 180: return 4.0  # 2 a 3 horas
            return 5.0  # Más de 3 horas (Excelente para TikTok LIVE)
        except:
            return None

    def normalizar_dias(dias):
        # Días de transmisión a la semana
        if dias is None: return None
        try:
            d = int(dias)
            if d <= 1: return 1.0  # 0-1 día
            if d == 2: return 2.0  # 2 días
            if d <= 4: return 3.0  # 3-4 días
            if d <= 6: return 4.0  # 5-6 días
            return 5.0  # Todos los días
        except:
            return None

    def normalizar_frecuencia(freq):
        # Basado en tu freq_map: {1: 1, 2: 2, 3: 3, 4: 0}
        # Lo escalamos a 1.0 - 5.0
        if freq is None: return None
        try:
            f = int(freq)
            if f == 4: return 1.0  # Rara vez / Nula
            if f == 1: return 2.0  # Ocasional
            if f == 2: return 3.5  # Regular
            if f == 3: return 5.0  # Frecuente / Muy constante
            return None
        except:
            return None

    def normalizar_tiempo(tiempo):
        # Basado en tu tiempo_map: {1: 1, 2: 2, 3: 3}
        # Lo escalamos a 1.0 - 5.0
        if tiempo is None: return None
        try:
            t = int(tiempo)
            if t == 1: return 1.5  # Poco tiempo (ej. < 1 hr)
            if t == 2: return 3.5  # Tiempo medio (ej. 1-3 hrs)
            if t == 3: return 5.0  # Mucho tiempo libre (ej. 3+ hrs)
            return None
        except:
            return None

    # Emparejamos los valores ya normalizados (1 a 5)
    valores_normalizados = {
        "duracion_emisiones": normalizar_duracion(duracion_emisiones),
        "dias_emisiones": normalizar_dias(dias_emisiones),
        "frecuencia_lives": normalizar_frecuencia(frecuencia_lives),
        "tiempo_disponible": normalizar_tiempo(tiempo_disponible)
    }

    # ==========================================
    # 2. CONSULTA DE PESOS EN BD
    # ==========================================
    pesos_db = {}
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                            SELECT campo_db, peso_variable
                            FROM modelo_variable
                            WHERE categoria_id = 3
                            """)
                for campo, peso in cur.fetchall():
                    pesos_db[campo] = float(peso)
    except Exception as e:
        print(f"❌ Error al consultar pesos operativos en BD: {e}")
        # Fallback de seguridad (25% a cada una si falla la BD)
        pesos_db = {
            "duracion_emisiones": 25.0,
            "dias_emisiones": 25.0,
            "frecuencia_lives": 25.0,
            "tiempo_disponible": 25.0
        }

    # ==========================================
    # 3. PONDERACIÓN DINÁMICA
    # ==========================================
    suma = 0.0
    suma_pesos = 0.0

    for clave, valor in valores_normalizados.items():
        if valor is not None:
            peso_actual = pesos_db.get(clave, 0.0)
            suma += float(valor) * peso_actual
            suma_pesos += peso_actual

    # Prevención de división por cero
    if suma_pesos == 0:
        return {
            "score_operativo": 0.0,
            "etiqueta_operativa": "Sin Disponibilidad"
        }

    # Cálculo final (Garantizado entre 1.0 y 5.0)
    score_operativo = round(suma / suma_pesos, 2)

    # ==========================================
    # 4. ETIQUETAS COMERCIALES (Dashboard SaaS)
    # ==========================================
    if score_operativo < 2.0:
        etiqueta = "No Apto (Falta de tiempo)"
    elif score_operativo < 3.0:
        etiqueta = "Part-Time Limitado"
    elif score_operativo < 4.0:
        etiqueta = "Operación Regular"
    elif score_operativo < 4.6:
        etiqueta = "Creador Constante"
    else:
        etiqueta = "Máquina de Lives 🔥"

    return {
        "score_operativo": score_operativo,
        "etiqueta_operativa": etiqueta
    }


# from database import get_connection_context

def evaluar_intencion(
        intencion_trabajo: int = None
):
    """
    Calcula la 'Intención y Alineación' (1-5) para el SaaS.
    Lee los pesos desde modelo_variable (Categoría 4).
    El valor 'intencion_trabajo' ya viene en escala 1-5 desde la BD.
    """

    # ==========================================
    # 1. EMPAREJAR VARIABLES DIRECTAS
    # ==========================================
    valores = {
        "intencion_trabajo": intencion_trabajo
    }

    # ==========================================
    # 2. CONSULTA DE PESOS EN BD
    # ==========================================
    pesos_db = {}
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                            SELECT campo_db, peso_variable
                            FROM modelo_variable
                            WHERE categoria_id = 4
                            """)
                for campo, peso in cur.fetchall():
                    pesos_db[campo] = float(peso)
    except Exception as e:
        print(f"❌ Error al consultar pesos de intención en BD: {e}")
        # Fallback de seguridad: 100% a la única variable
        pesos_db = {"intencion_trabajo": 100.0}

    # ==========================================
    # 3. PONDERACIÓN DINÁMICA
    # ==========================================
    suma = 0.0
    suma_pesos = 0.0

    for clave, valor in valores.items():
        if valor is not None:
            peso_actual = pesos_db.get(clave, 0.0)
            suma += float(valor) * peso_actual
            suma_pesos += peso_actual

    # Prevención de división por cero
    if suma_pesos == 0:
        return {
            "score_intencion": 0.0,
            "etiqueta_intencion": "Sin Evaluar"
        }

    # Cálculo final (Garantizado entre 1.0 y 5.0)
    score_intencion = round(suma / suma_pesos, 2)

    # ==========================================
    # 4. ETIQUETAS COMERCIALES (SaaS Dashboard)
    # ==========================================
    if score_intencion < 2.0:
        etiqueta = "Solo Diversión"
    elif score_intencion < 3.5:
        etiqueta = "Hobby / Amateur"
    elif score_intencion < 4.5:
        etiqueta = "Ingreso Extra / Part-Time"
    else:
        etiqueta = "Profesional / Full-Time 🎯"

    return {
        "score_intencion": score_intencion,
        "etiqueta_intencion": etiqueta
    }


# from database import get_connection_context



# -------------------------------------------
# -------------------------------------------
# ----ENCUESTAS-------
# -------------------------------------------
# -------------------------------------------
# -------------------------------------------

def obtener_encuestas_activas():
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, nombre, descripcion
                    FROM form_encuestas
                    WHERE activa = true
                    ORDER BY id
                """)

                return cur.fetchall()

    except (OperationalError, DatabaseError) as e:
        print(f"❌ Error de base de datos al obtener encuestas: {e}")
        traceback.print_exc()
        return []
    except Exception as e:
        print(f"❌ Error inesperado al obtener encuestas: {e}")
        traceback.print_exc()
        return []

def obtener_preguntas_por_encuesta(encuesta_id: int):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, texto, tipo, campo, orden
                    FROM form_preguntas
                    WHERE encuesta_id = %s
                    AND activa = true
                    ORDER BY orden
                """, (encuesta_id,))

                return cur.fetchall()

    except (OperationalError, DatabaseError) as e:
        print(f"❌ Error de base de datos al obtener preguntas: {e}")
        traceback.print_exc()
        return []
    except Exception as e:
        print(f"❌ Error inesperado al obtener preguntas: {e}")
        traceback.print_exc()
        return []


def obtener_opciones_por_pregunta(pregunta_id: int):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                            SELECT id, label, orden
                            FROM form_opciones
                            WHERE pregunta_id = %s
                            ORDER BY orden
                            """, (pregunta_id,))

                return cur.fetchall()

    except (OperationalError, DatabaseError) as e:
        print(f"❌ Error de base de datos al obtener opciones: {e}")
        traceback.print_exc()
        return []
    except Exception as e:
        print(f"❌ Error inesperado al obtener opciones: {e}")
        traceback.print_exc()
        return []


from psycopg2.extras import RealDictCursor

@router.get("/api/encuestas/{encuesta_id}")
def obtener_encuesta(encuesta_id: int):
    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                cur.execute("""
                    SELECT 
                        p.id AS pregunta_id,
                        p.texto,
                        p.tipo,
                        p.campo,
                        o.id AS opcion_id,
                        o.label,
                        o.orden AS opcion_orden
                    FROM form_preguntas p
                    LEFT JOIN form_opciones o 
                        ON o.pregunta_id = p.id
                    WHERE p.encuesta_id = %s
                      AND p.activa = true
                    ORDER BY p.orden, o.orden
                """, (encuesta_id,))

                rows = cur.fetchall()

                preguntas = {}
                for row in rows:
                    pid = row["pregunta_id"]

                    if pid not in preguntas:
                        preguntas[pid] = {
                            "id": pid,
                            "texto": row["texto"],
                            "tipo": row["tipo"],
                            "campo": row["campo"],
                            "opciones": []
                        }

                    if row["opcion_id"]:
                        preguntas[pid]["opciones"].append({
                            "id": row["opcion_id"],
                            "label": row["label"],
                            "orden": row["opcion_orden"]
                        })

                return {
                    "success": True,
                    "encuesta_id": encuesta_id,
                    "preguntas": list(preguntas.values())
                }

    except Exception:
        return {"success": False}



@router.get("/api/encuestas/{encuesta_idV0}")
def obtener_encuestaV0(encuesta_id: int):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                cur.execute("""
                    SELECT 
                        p.id AS pregunta_id,
                        p.texto,
                        p.tipo,
                        p.campo,
                        p.orden AS pregunta_orden,
                        o.id AS opcion_id,
                        o.label,
                        o.orden AS opcion_orden
                    FROM form_preguntas p
                    LEFT JOIN form_opciones o 
                        ON o.pregunta_id = p.id
                    WHERE p.encuesta_id = %s
                      AND p.activa = true
                    ORDER BY p.orden, o.orden
                """, (encuesta_id,))

                rows = cur.fetchall()

                preguntas_dict = {}

                for row in rows:
                    (
                        pregunta_id,
                        texto,
                        tipo,
                        campo,
                        pregunta_orden,
                        opcion_id,
                        label,
                        opcion_orden
                    ) = row

                    if pregunta_id not in preguntas_dict:
                        preguntas_dict[pregunta_id] = {
                            "id": pregunta_id,
                            "texto": texto,
                            "tipo": tipo,
                            "campo": campo,
                            "opciones": []
                        }

                    if opcion_id:
                        preguntas_dict[pregunta_id]["opciones"].append({
                            "id": opcion_id,
                            "label": label,
                            "orden": opcion_orden
                        })

                return {
                    "success": True,
                    "encuesta_id": encuesta_id,
                    "preguntas": list(preguntas_dict.values())
                }

    except (OperationalError, DatabaseError) as e:
        print(f"❌ Error de base de datos al obtener encuesta: {e}")
        traceback.print_exc()
        return {
            "success": False,
            "error": "Error de base de datos"
        }

    except Exception as e:
        print(f"❌ Error inesperado al obtener encuesta: {e}")
        traceback.print_exc()
        return {
            "success": False,
            "error": "Error inesperado"
        }

