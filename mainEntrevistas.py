from typing import Optional, List
from datetime import datetime, timedelta
from pydantic import BaseModel

from auth import obtener_usuario_actual
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from DataBase import  get_connection,actualizar_estado_creador,actualizar_entrevista_por_creador
import unicodedata

from fastapi import APIRouter, HTTPException, Depends, Body
from typing import Optional, List, Dict

router = APIRouter(prefix="/api", tags=["Entrevistas"])

# =====================
# 🎯 AGENDAMIENTOS
# =====================

class AgendamientoBase(BaseModel):
    entrevista_id: int
    creador_id: int
    fecha_programada: datetime
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

def insertar_entrevista(datos: dict):
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            columnas = ', '.join(datos.keys())
            placeholders = ', '.join(['%s'] * len(datos))
            sql = f"""
                INSERT INTO entrevistas ({columnas})
                VALUES ({placeholders})
                RETURNING id, creado_en
            """
            cur.execute(sql, tuple(datos.values()))
            row = cur.fetchone()
            conn.commit()
            return {"id": row[0], "creado_en": row[1]}
    except Exception as e:
        print("❌ Error al insertar entrevista:", e)
        return None
    finally:
        conn.close()


def crear_entrevista_base(creador_id: int):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO entrevistas (creador_id)
                VALUES (%s)
                RETURNING id, creador_id,
                          NULL::int as usuario_evalua,
                          'sin_programar'::varchar as resultado,
                          ''::varchar as observaciones,
                          NULL::int as aspecto_tecnico,
                          NULL::int as presencia_carisma,
                          NULL::int as interaccion_audiencia,
                          NULL::int as profesionalismo_normas,
                          NULL::int as evaluacion_global,
                          NOW() as creado_en
            """, (creador_id,))

            row = cur.fetchone()
            conn.commit()
            return {
                "id": row[0],
                "creador_id": row[1],
                "usuario_evalua": row[2],
                "resultado": row[3],
                "observaciones": row[4],
                "aspecto_tecnico": row[5],
                "presencia_carisma": row[6],
                "interaccion_audiencia": row[7],
                "profesionalismo_normas": row[8],
                "evaluacion_global": row[9],
                "creado_en": row[10],
                "agendamientos": []
            }
    finally:
        conn.close()


def insertar_agendamiento(datos: dict):
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            columnas = ', '.join(datos.keys())
            placeholders = ', '.join(['%s'] * len(datos))
            sql = f"""
                INSERT INTO entrevista_agendamiento ({columnas})
                VALUES ({placeholders})
                RETURNING id, creado_en
            """
            cur.execute(sql, tuple(datos.values()))
            row = cur.fetchone()
            conn.commit()
            return {"id": row[0], "creado_en": row[1]}
    except Exception as e:
        print("❌ Error al insertar agendamiento:", e)
        return None
    finally:
        conn.close()

def obtener_entrevista_con_agendamientos(creador_id: int):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            # 1) Entrevista más reciente del creador
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

            # 2) Agendamientos relacionados (tabla: entrevista_agendamiento)
            cur.execute("""
                SELECT id, entrevista_id, creador_id, fecha_programada, duracion_minutos,
                       realizada, fecha_realizada, usuario_programa, evento_id, creado_en
                FROM entrevista_agendamiento
                WHERE entrevista_id = %s
                ORDER BY fecha_programada ASC
            """, (e[0],))
            rows = cur.fetchall()

            for r in rows:
                entrevista_dict["agendamientos"].append({
                    "id": r[0],
                    "entrevista_id": r[1],
                    "creador_id": r[2],
                    "fecha_programada": r[3],
                    "duracion_minutos": r[4],
                    "realizada": r[5],
                    "fecha_realizada": r[6],
                    "usuario_programa": r[7],
                    "evento_id": r[8],     # <- string/nullable
                    "creado_en": r[9],
                })

            return entrevista_dict
    except Exception as e:
        print(f"❌ Error al obtener entrevista con agendamientos: {e}")
        return None
    finally:
        if conn:
            conn.close()

def actualizar_entrevista(entrevista_id: int, datos: dict):
    if not datos:
        return None

    try:
        with get_connection() as conn:
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




# ================================
# 📌 CREAR ENTREVISTA
# ================================
@router.post("/api/entrevistas/{creador_id}", response_model=EntrevistaOut)
def crear_entrevista(creador_id: int, datos: EntrevistaCreate, usuario_actual: dict = Depends(obtener_usuario_actual)):
    try:
        datos["creador_id"] = datos.get("creador_id")
        if not datos["creador_id"]:
            raise HTTPException(status_code=400, detail="El campo creador_id es obligatorio")

        datos["usuario_evalua"] = usuario_actual.get("id")  # si aplica
        resultado = insertar_entrevista(datos)
        if not resultado:
            raise HTTPException(status_code=500, detail="Error al insertar entrevista")
        return {"status": "ok", "entrevista": resultado}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al crear entrevista: {e}")

import logging
logger = logging.getLogger("uvicorn.error")

from main import  eliminar_evento,crear_evento
# ================================
# 📌 CREAR AGENDAMIENTO DE ENTREVISTA + EVENTO
# ================================
@router.post("/api/entrevistas/{entrevista_id}/agendamientos", response_model=AgendamientoOut)
def crear_agendamiento(entrevista_id: int, datos: AgendamientoCreate, usuario_actual: dict = Depends(obtener_usuario_actual)):
    try:
        # Validación mínima
        if "creador_id" not in datos:
            raise HTTPException(status_code=400, detail="El campo creador_id es obligatorio")
        if "fecha_programada" not in datos:
            raise HTTPException(status_code=400, detail="El campo fecha_programada es obligatorio")

        creador_id = datos["creador_id"]
        fecha_inicio = datos["fecha_programada"]
        fecha_fin = fecha_inicio + timedelta(hours=1)  # duración por defecto 1h

        # === Crear evento en calendario ===
        try:
            evento_payload = EventoIn(
                titulo="Entrevista",
                descripcion=datos.get("observaciones") or "Entrevista programada",
                inicio=fecha_inicio,
                fin=fecha_fin,
                participantes_ids=[creador_id],
            )
            evento_creado = crear_evento(evento_payload, usuario_actual)
            datos["evento_id"] = evento_creado.id
        except Exception as e:
            print(f"⚠️ Error al crear evento en calendario: {e}")
            datos["evento_id"] = None

        # === Insertar agendamiento en DB ===
        datos["entrevista_id"] = entrevista_id
        datos["usuario_programa"] = usuario_actual.get("id")

        resultado = insertar_agendamiento(datos)
        if not resultado:
            raise HTTPException(status_code=500, detail="Error al insertar agendamiento")

        return {
            "status": "ok",
            "agendamiento": {**resultado, "evento": evento_creado.dict() if datos.get("evento_id") else None}
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al crear agendamiento: {e}")



# DELETE eliminar agendamiento de entrevista
@router.delete("/api/entrevistas/agendamientos/{agendamiento_id}", response_model=dict)
def eliminar_agendamiento(agendamiento_id: int, usuario_actual: dict = Depends(obtener_usuario_actual)):
    """
    Elimina un agendamiento de la tabla entrevista_agendamiento
    y también elimina el evento en Google Calendar (si existe).
    No actualiza estados de entrevista, perfil_creador ni creadores.
    """
    if not usuario_actual:
        raise HTTPException(status_code=401, detail="Usuario no autorizado")

    conn = get_connection()
    cur = conn.cursor()
    try:
        # 1. Buscar el evento_id asociado al agendamiento
        cur.execute("""
            SELECT evento_id 
            FROM entrevista_agendamiento 
            WHERE id = %s
        """, (agendamiento_id,))
        row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Agendamiento {agendamiento_id} no encontrado")

        evento_id = row[0]

        # 2. Eliminar el agendamiento de la tabla entrevista_agendamiento
        cur.execute("DELETE FROM entrevista_agendamiento WHERE id = %s", (agendamiento_id,))
        conn.commit()

        # 3. Si tenía evento asociado, borrarlo de Google Calendar y de agendamientos
        if evento_id:
            eliminar_evento(evento_id)

        return {
            "ok": True,
            "mensaje": f"Agendamiento {agendamiento_id} eliminado"
                      + (f" y evento {evento_id} eliminado" if evento_id else "")
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error al eliminar agendamiento {agendamiento_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()


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


# ================================
# 📌 ACTUALIZAR ENTREVISTA
# ================================
# @router.put("/entrevistas/{entrevista_id}", response_model=EntrevistaOut)
# def actualizar_entrevista_api(
#     entrevista_id: int,
#     datos: EntrevistaUpdate,
#     usuario_actual: dict = Depends(obtener_usuario_actual)
# ):
#     try:
#         payload = datos.dict(exclude_unset=True)
#         entrevista = actualizar_entrevista(entrevista_id, payload, usuario_actual["id"])
#         if not entrevista:
#             raise HTTPException(status_code=404, detail="Entrevista no encontrada")
#         return entrevista
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Error al actualizar entrevista: {e}")
#


# Mapa de estado_id según el resultado de la entrevista
# Ajusta los IDs si en tu catálogo son distintos
RESULTADO_TO_ESTADO_ID = {
    "PROGRAMADA": 4,
    "ENTREVISTA": 4,
    "INVITACION": 5,  # "Invitación"
    "RECHAZADO": 7,
}

def _normalize_text(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    # quita acentos, pasa a mayúsculas y trimea
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.strip().upper()

import unicodedata
from typing import Optional
from fastapi import HTTPException, Depends
from datetime import datetime

# Mapa de estados (ajusta IDs si tu catálogo cambia)
RESULTADO_TO_ESTADO_ID = {
    "PROGRAMADA": 4,
    "ENTREVISTA": 4,
    "INVITACION": 5,   # "Invitación"
    "RECHAZADO": 7,
}

def _normalize_text(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.strip().upper()


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

    # Si el payload incluye calificaciones pero no "usuario_evalua",
    # opcionalmente puedes setear el evaluador actual:
    if any(k in payload for k in (
        "aspecto_tecnico", "presencia_carisma",
        "interaccion_audiencia", "profesionalismo_normas",
        "evaluacion_global"
    )):
        payload.setdefault("usuario_evalua", usuario_id)

    # 1) Actualiza la entrevista (por creador_id) y devuelve el registro actualizado
    #    Debe devolver un dict con al menos estos campos:
    #    id, creado_en, creador_id, usuario_evalua, resultado, observaciones,
    #    aspecto_tecnico, presencia_carisma, interaccion_audiencia,
    #    profesionalismo_normas, evaluacion_global
    actualizado = actualizar_entrevista_por_creador(creador_id, payload)
    if not actualizado:
        raise HTTPException(status_code=404, detail="No existe entrevista para este creador")

    # 2) Derivar estado_id a partir de `resultado` (payload o valor final en DB)
    resultado_raw = payload.get("resultado") or actualizado.get("resultado")
    resultado_norm = _normalize_text(resultado_raw)
    estado_id = RESULTADO_TO_ESTADO_ID.get(resultado_norm)

    if estado_id is not None:
        try:
            actualizar_estado_creador(creador_id, estado_id)
        except Exception:
            # No rompemos la respuesta si falla el update de estado
            pass

    # 3) Responder exactamente con el schema EntrevistaOut
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

