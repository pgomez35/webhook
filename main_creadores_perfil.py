import io
import json
import traceback
from datetime import date
from typing import Optional, Any, List, Dict

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import JSONResponse
from psycopg2.extras import RealDictCursor, Json
from pydantic import BaseModel

from DataBase import get_connection_context
from schemas import (
    CreadorActivoDB,
    CreadorActivoCreate,
    CreadorActivoUpdate,
    CreadorActivoConManager,
    CreadorActivoAutoCreate,
    SeguimientoCreadorDB,
    SeguimientoCreadorCreate,
    SeguimientoCreadorConManager,
)
from utils_aspirantes import obtener_creadores_activos_db

router = APIRouter()


# =========================================================
# MODELOS
# =========================================================

class RespuestaPerfilCreadorIn(BaseModel):
    variable_id: int
    valor_integer: Optional[int] = None
    valor_id: Optional[int] = None
    valor_numeric: Optional[float] = None
    valor_texto: Optional[str] = None
    valor_json: Optional[Any] = None


class GuardarPerfilCreadorIn(BaseModel):
    creador_id: int
    respuestas: List[RespuestaPerfilCreadorIn]


# =========================================================
# FORMULARIO PERFIL CREADOR
# =========================================================

@router.get("/api/creadores/perfil-formulario")
def obtener_formulario_perfil_creador(
    encuesta_id: int = Query(2)
):
    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        c.id AS categoria_id,
                        c.nombre AS categoria_nombre,
                        c.nombre_natural,
                        c.descripcion,
                        c.orden AS categoria_orden,

                        v.id AS variable_id,
                        v.nombre AS variable_nombre,
                        v.campo_db,
                        v.peso_variable,
                        v.tipo,
                        v.tipo_form,
                        v.texto,
                        v.orden AS variable_orden,

                        val.id AS valor_id,
                        val.score,
                        val.label,
                        val.nivel,
                        val.orden AS valor_orden

                    FROM creadores_perfil_variable v
                    LEFT JOIN creadores_perfil_categoria c
                        ON c.id = v.categoria_id
                    LEFT JOIN creadores_perfil_valor val
                        ON val.variable_id = v.id
                    WHERE v.encuesta_id = %s
                      AND v.activa = TRUE
                    ORDER BY
                        c.orden ASC NULLS LAST,
                        v.orden ASC NULLS LAST,
                        val.orden ASC NULLS LAST
                """, (encuesta_id,))

                rows = cur.fetchall()

        categorias_map = {}

        for row in rows:
            categoria_id = row["categoria_id"] or 0

            if categoria_id not in categorias_map:
                categorias_map[categoria_id] = {
                    "id": categoria_id,
                    "nombre": row["categoria_nombre"],
                    "nombre_natural": row["nombre_natural"],
                    "descripcion": row["descripcion"],
                    "orden": row["categoria_orden"],
                    "variables": {}
                }

            variable_id = row["variable_id"]

            if variable_id not in categorias_map[categoria_id]["variables"]:
                categorias_map[categoria_id]["variables"][variable_id] = {
                    "id": variable_id,
                    "nombre": row["variable_nombre"],
                    "campo_db": row["campo_db"],
                    "peso_variable": float(row["peso_variable"] or 0),
                    "tipo": row["tipo"],
                    "tipo_form": row["tipo_form"],
                    "texto": row["texto"],
                    "orden": row["variable_orden"],
                    "opciones": []
                }

            if row["valor_id"] is not None:
                categorias_map[categoria_id]["variables"][variable_id]["opciones"].append({
                    "id": row["valor_id"],
                    "score": row["score"],
                    "label": row["label"],
                    "nivel": row["nivel"],
                    "orden": row["valor_orden"]
                })

        categorias = []
        for categoria in categorias_map.values():
            categoria["variables"] = list(categoria["variables"].values())
            categorias.append(categoria)

        return {
            "ok": True,
            "encuesta_id": encuesta_id,
            "categorias": categorias
        }

    except Exception as e:
        print("❌ Error obteniendo formulario perfil creador:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error obteniendo formulario del creador")


# =========================================================
# RESPUESTAS DE UN CREADOR
# =========================================================

@router.get("/api/creadores/{creador_id}/perfil-respuestas")
def obtener_respuestas_perfil_creador(
    creador_id: int,
    encuesta_id: int = Query(2)
):
    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        r.id,
                        r.creador_id,
                        r.variable_id,

                        v.nombre AS variable_nombre,
                        v.campo_db,
                        v.tipo,
                        v.tipo_form,
                        v.texto,
                        v.orden,

                        r.valor_integer,
                        r.valor_id,
                        r.valor_numeric,
                        r.valor_texto,
                        r.valor_json,

                        val.label AS valor_label,
                        val.score AS valor_score,
                        val.nivel AS valor_nivel,

                        r.created_at,
                        r.updated_at

                    FROM creadores_perfil_respuesta r
                    INNER JOIN creadores_perfil_variable v
                        ON v.id = r.variable_id
                    LEFT JOIN creadores_perfil_valor val
                        ON val.id = r.valor_id
                    WHERE r.creador_id = %s
                      AND v.encuesta_id = %s
                    ORDER BY v.orden ASC
                """, (creador_id, encuesta_id))

                rows = cur.fetchall()

        return {
            "ok": True,
            "creador_id": creador_id,
            "respuestas": rows
        }

    except Exception as e:
        print("❌ Error obteniendo respuestas perfil creador:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error obteniendo respuestas del creador")


# =========================================================
# GUARDAR RESPUESTAS
# =========================================================

@router.post("/api/creadores/perfil-respuestas")
def guardar_respuestas_perfil_creador(data: GuardarPerfilCreadorIn):
    if not data.creador_id:
        raise HTTPException(status_code=400, detail="creador_id requerido")

    if not data.respuestas:
        raise HTTPException(status_code=400, detail="No hay respuestas para guardar")

    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                for respuesta in data.respuestas:
                    cur.execute("""
                        INSERT INTO creadores_perfil_respuesta
                        (
                            creador_id,
                            variable_id,
                            valor_integer,
                            valor_id,
                            valor_numeric,
                            valor_texto,
                            valor_json,
                            created_at,
                            updated_at
                        )
                        VALUES
                        (
                            %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                        )
                        ON CONFLICT (creador_id, variable_id)
                        DO UPDATE SET
                            valor_integer = EXCLUDED.valor_integer,
                            valor_id = EXCLUDED.valor_id,
                            valor_numeric = EXCLUDED.valor_numeric,
                            valor_texto = EXCLUDED.valor_texto,
                            valor_json = EXCLUDED.valor_json,
                            updated_at = NOW()
                    """, (
                        data.creador_id,
                        respuesta.variable_id,
                        respuesta.valor_integer,
                        respuesta.valor_id,
                        respuesta.valor_numeric,
                        respuesta.valor_texto,
                        Json(respuesta.valor_json) if respuesta.valor_json is not None else None
                    ))

            conn.commit()

        return {
            "ok": True,
            "mensaje": "Respuestas guardadas correctamente"
        }

    except Exception as e:
        print("❌ Error guardando respuestas perfil creador:", e)
        traceback.print_exc()
        return JSONResponse(
            {"ok": False, "error": "Error guardando respuestas del creador"},
            status_code=500
        )



# ---------------------------------------------------------------
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# ---------------------------------------------------------------

# =========================================================
# CREADORES (antes creadores_activos; tabla: creadores)
# =========================================================

@router.get("/api/creadores/activos", tags=["Creadores"])
def listar_creadores_activos():
    try:
        return obtener_creadores_activos_db()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/creadores_activos/{id}", response_model=CreadorActivoConManager)
def obtener_creador_activo(id: int):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        c.id,
                        c.aspirante_id,
                        c.nombre,
                        c.usuario_tiktok,
                        c.email,
                        c.telefono,
                        c.foto,
                        c.categoria,
                        c.estado,

                        d.manager_id,
                        au.nombre_completo AS manager_nombre,

                        d.horario_lives,
                        d.tiempo_disponible,
                        d.fecha_incorporacion,
                        d.fecha_graduacion,
                        d.seguidores,
                        d.videos,
                        d.me_gusta,
                        d.diamantes,
                        d.horas_live,
                        d.numero_partidas,
                        d.dias_emision

                    FROM creadores c
                    LEFT JOIN creadores_detalle d
                        ON d.creador_id = c.id
                    LEFT JOIN administradores au
                        ON au.id = d.manager_id
                    WHERE c.id = %s
                    LIMIT 1
                """, (id,))

                row = cur.fetchone()

                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail="Creador no encontrado"
                    )

                columns = [desc[0] for desc in cur.description]
                return dict(zip(columns, row))

    except HTTPException:
        raise

    except Exception as e:
        print(f"❌ Error obteniendo creador activo {id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/creadores_activos", status_code=201)
def agregar_creador_activo(creador: CreadorActivoCreate):
    try:
        data = creador.dict()

        with get_connection_context() as conn:
            with conn.cursor() as cur:

                # 1. Insertar datos base en creadores
                cur.execute("""
                    INSERT INTO creadores (
                        aspirante_id,
                        nombre,
                        usuario_tiktok,
                        email,
                        telefono,
                        foto,
                        categoria,
                        estado
                    )
                    VALUES (
                        %(aspirante_id)s,
                        %(nombre)s,
                        %(usuario_tiktok)s,
                        %(email)s,
                        %(telefono)s,
                        %(foto)s,
                        %(categoria)s,
                        COALESCE(%(estado)s, 'activo')
                    )
                    RETURNING id;
                """, data)

                creador_id = cur.fetchone()[0]

                # 2. Insertar datos operativos en creadores_detalle
                cur.execute("""
                    INSERT INTO creadores_detalle (
                        creador_id,
                        manager_id,
                        horario_lives,
                        tiempo_disponible,
                        fecha_incorporacion,
                        fecha_graduacion,
                        seguidores,
                        videos,
                        me_gusta,
                        diamantes,
                        horas_live,
                        numero_partidas,
                        dias_emision,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        %s,
                        %(manager_id)s,
                        %(horario_lives)s,
                        %(tiempo_disponible)s,
                        %(fecha_incorporacion)s,
                        %(fecha_graduacion)s,
                        %(seguidores)s,
                        %(videos)s,
                        %(me_gusta)s,
                        %(diamantes)s,
                        %(horas_live)s,
                        %(numero_partidas)s,
                        %(dias_emision)s,
                        now(),
                        now()
                    );
                """, {"creador_id": creador_id, **data})

                conn.commit()

                # 3. Retornar creador completo
                cur.execute("""
                    SELECT
                        c.id,
                        c.aspirante_id,
                        c.nombre,
                        c.usuario_tiktok,
                        c.email,
                        c.telefono,
                        c.foto,
                        c.categoria,
                        c.estado,

                        d.manager_id,
                        d.horario_lives,
                        d.tiempo_disponible,
                        d.fecha_incorporacion,
                        d.fecha_graduacion,
                        d.seguidores,
                        d.videos,
                        d.me_gusta,
                        d.diamantes,
                        d.horas_live,
                        d.numero_partidas,
                        d.dias_emision

                    FROM creadores c
                    LEFT JOIN creadores_detalle d
                        ON d.creador_id = c.id
                    WHERE c.id = %s
                """, (creador_id,))

                row = cur.fetchone()
                columns = [desc[0] for desc in cur.description]

                return dict(zip(columns, row))

    except Exception as e:
        print(f"❌ Error creando creador activo: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/creadores_activos/{id}")
def editar_creador_activo(id: int, creador: CreadorActivoUpdate):
    try:
        data = creador.dict()

        with get_connection_context() as conn:
            with conn.cursor() as cur:

                # 1. Verificar que exista
                cur.execute("""
                    SELECT id
                    FROM creadores
                    WHERE id = %s
                """, (id,))

                if not cur.fetchone():
                    raise HTTPException(
                        status_code=404,
                        detail="Creador no encontrado"
                    )

                # 2. Actualizar tabla principal
                cur.execute("""
                    UPDATE creadores
                    SET
                        aspirante_id = %(aspirante_id)s,
                        nombre = %(nombre)s,
                        usuario_tiktok = %(usuario_tiktok)s,
                        email = %(email)s,
                        telefono = %(telefono)s,
                        foto = %(foto)s,
                        categoria = %(categoria)s,
                        estado = %(estado)s,
                        updated_at = now()
                    WHERE id = %(id)s
                """, {**data, "id": id})

                # 3. Insertar o actualizar detalle
                cur.execute("""
                    INSERT INTO creadores_detalle (
                        creador_id,
                        manager_id,
                        horario_lives,
                        tiempo_disponible,
                        fecha_incorporacion,
                        fecha_graduacion,
                        seguidores,
                        videos,
                        me_gusta,
                        diamantes,
                        horas_live,
                        numero_partidas,
                        dias_emision,
                        updated_at
                    )
                    VALUES (
                        %(id)s,
                        %(manager_id)s,
                        %(horario_lives)s,
                        %(tiempo_disponible)s,
                        %(fecha_incorporacion)s,
                        %(fecha_graduacion)s,
                        %(seguidores)s,
                        %(videos)s,
                        %(me_gusta)s,
                        %(diamantes)s,
                        %(horas_live)s,
                        %(numero_partidas)s,
                        %(dias_emision)s,
                        now()
                    )
                    ON CONFLICT (creador_id)
                    DO UPDATE SET
                        manager_id = EXCLUDED.manager_id,
                        horario_lives = EXCLUDED.horario_lives,
                        tiempo_disponible = EXCLUDED.tiempo_disponible,
                        fecha_incorporacion = EXCLUDED.fecha_incorporacion,
                        fecha_graduacion = EXCLUDED.fecha_graduacion,
                        seguidores = EXCLUDED.seguidores,
                        videos = EXCLUDED.videos,
                        me_gusta = EXCLUDED.me_gusta,
                        diamantes = EXCLUDED.diamantes,
                        horas_live = EXCLUDED.horas_live,
                        numero_partidas = EXCLUDED.numero_partidas,
                        dias_emision = EXCLUDED.dias_emision,
                        updated_at = now()
                """, {**data, "id": id})

                conn.commit()

                # 4. Retornar creador completo
                cur.execute("""
                    SELECT
                        c.id,
                        c.aspirante_id,
                        c.nombre,
                        c.usuario_tiktok,
                        c.email,
                        c.telefono,
                        c.foto,
                        c.categoria,
                        c.estado,

                        d.manager_id,
                        d.horario_lives,
                        d.tiempo_disponible,
                        d.fecha_incorporacion,
                        d.fecha_graduacion,
                        d.seguidores,
                        d.videos,
                        d.me_gusta,
                        d.diamantes,
                        d.horas_live,
                        d.numero_partidas,
                        d.dias_emision

                    FROM creadores c
                    LEFT JOIN creadores_detalle d
                        ON d.creador_id = c.id
                    WHERE c.id = %s
                """, (id,))

                row = cur.fetchone()
                columns = [desc[0] for desc in cur.description]

                return dict(zip(columns, row))

    except HTTPException:
        raise

    except Exception as e:
        print(f"❌ Error editando creador activo {id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/creadores_activos/auto", response_model=dict)
def crear_creador_activo_automatico(data: CreadorActivoAutoCreate):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        id,
                        usuario AS usuario_tiktok,
                        foto_url AS foto,
                        NULL AS categoria,
                        'activo' AS estado,
                        nickname AS nombre
                    FROM aspirantes
                    WHERE id = %s
                """, (data.aspirante_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Creador no encontrado")

                creador = dict(zip([desc[0] for desc in cur.description], row))

                valores = {
                    "aspirante_id": creador["id"],
                    "usuario_tiktok": creador["usuario_tiktok"],
                    "email": None,
                    "telefono": None,
                    "foto": creador["foto"],
                    "categoria": creador["categoria"],
                    "estado": creador["estado"],
                    "nombre": creador["nombre"],
                    "manager_id": data.manager_id,
                    "fecha_incorporacion": data.fecha_incorporacion or date.today(),
                    "horario_lives": None,
                    "tiempo_disponible": None,
                    "fecha_graduacion": None,
                    "seguidores": None,
                    "videos": None,
                    "me_gusta": None,
                    "diamantes": None,
                    "horas_live": None,
                    "numero_partidas": None,
                    "dias_emision": None,
                }

                cur.execute("""
                    INSERT INTO creadores (
                        aspirante_id, usuario_tiktok, email, telefono, foto, categoria, estado, nombre,
                        manager_id, horario_lives, tiempo_disponible, fecha_incorporacion, fecha_graduacion,
                        seguidores, videos, me_gusta, diamantes, horas_live, numero_partidas, dias_emision
                    ) VALUES (
                        %(aspirante_id)s, %(usuario_tiktok)s, %(email)s, %(telefono)s, %(foto)s, %(categoria)s, %(estado)s, %(nombre)s,
                        %(manager_id)s, %(horario_lives)s, %(tiempo_disponible)s, %(fecha_incorporacion)s, %(fecha_graduacion)s,
                        %(seguidores)s, %(videos)s, %(me_gusta)s, %(diamantes)s, %(horas_live)s, %(numero_partidas)s, %(dias_emision)s
                    )
                    RETURNING *;
                """, valores)
                new_row = cur.fetchone()
                conn.commit()
                columns = [desc[0] for desc in cur.description]
                return dict(zip(columns, new_row))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al crear creador activo: {e}")

@router.post("/api/seguimiento_creadores/", response_model=SeguimientoCreadorDB)
def crear_seguimiento_creador(seg: SeguimientoCreadorCreate):
    try:

        if not seg.creador_id:
            raise HTTPException(
                status_code=400,
                detail="creador_id es requerido"
            )

        with get_connection_context() as conn:
            with conn.cursor() as cur:

                # Obtener manager asignado al creador
                cur.execute("""
                    SELECT manager_id
                    FROM creadores_detalle
                    WHERE creador_id = %s
                """, (seg.creador_id,))

                result = cur.fetchone()

                if not result:
                    raise HTTPException(
                        status_code=404,
                        detail="No se encontró el detalle del creador"
                    )

                manager_id = result[0]

                # Insertar seguimiento
                cur.execute("""
                    INSERT INTO creadores_seguimiento (
                        creador_id,
                        manager_id,
                        fecha_seguimiento,
                        estrategias_mejora,
                        compromisos
                    )
                    VALUES (
                        %(creador_id)s,
                        %(manager_id)s,
                        %(fecha_seguimiento)s,
                        %(estrategias_mejora)s,
                        %(compromisos)s
                    )
                    RETURNING *;
                """, {
                    "creador_id": seg.creador_id,
                    "manager_id": manager_id,
                    "fecha_seguimiento": seg.fecha_seguimiento,
                    "estrategias_mejora": seg.estrategias_mejora,
                    "compromisos": seg.compromisos
                })

                row = cur.fetchone()

                columns = [desc[0] for desc in cur.description]

                conn.commit()

                return dict(zip(columns, row))

    except HTTPException:
        raise

    except Exception as e:
        print("ERROR:", e)

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@router.get("/api/seguimiento_creadores/creador/{creador_id}", response_model=List[SeguimientoCreadorConManager])
def listar_seguimientos_por_creador(creador_id: int):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT sc.*, au.nombre_completo AS manager_nombre
                    FROM creadores_seguimiento sc
                    LEFT JOIN administradores au ON sc.manager_id = au.id
                    WHERE sc.creador_id = %s
                    ORDER BY sc.fecha_seguimiento DESC
                """, (creador_id,))
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def obtener_estadisticas_por_creador(creador_activo_id: int):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM estadisticas_creadores WHERE creador_activo_id = %s",
                (creador_activo_id,)
            )
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
            resultados = [dict(zip(columns, row)) for row in rows]
            return resultados


@router.post("/estadisticas_creadores/cargar_excel/")
async def cargar_estadisticas_excel(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents), header=1)

        df.columns = [col.strip().replace(":", "") for col in df.columns]

        required_columns = [
            "ID de creador", "Nombre de usuario del creador", "Grupo",
            "Diamantes de los últimos 30 días",
            "Duración de emisiones LIVE en los últimos 30 días",
            "Seguidores", "Vídeos", "Me gusta"
        ]
        for col in required_columns:
            if col not in df.columns:
                raise HTTPException(status_code=400, detail=f"Falta columna: {col}")

        with get_connection_context() as conn:
            with conn.cursor() as cur:
                creados = 0
                actualizados = 0

                for _, row in df.iterrows():
                    usuario_tiktok = str(row["Nombre de usuario del creador"]).strip()
                    grupo = str(row["Grupo"])
                    seguidores = int(row["Seguidores"])
                    videos = int(row["Vídeos"])
                    me_gusta = int(row["Me gusta"])
                    diamantes = int(row["Diamantes de los últimos 30 días"])
                    duracion_lives = int(row["Duración de emisiones LIVE en los últimos 30 días"])

                    cur.execute("""
                        SELECT id, aspirante_id FROM creadores WHERE usuario_tiktok = %s
                    """, (usuario_tiktok,))
                    res = cur.fetchone()
                    if not res:
                        continue

                    creador_activo_id, aspirante_id = res

                    cur.execute("""
                        INSERT INTO estadisticas_creadores (
                            aspirante_id, creador_activo_id, fecha_reporte, grupo, diamantes_ult_30, duracion_emsiones_live_ult_30
                        ) VALUES (%s, %s, CURRENT_DATE, %s, %s, %s)
                    """, (
                        aspirante_id,
                        creador_activo_id,
                        grupo,
                        diamantes,
                        duracion_lives
                    ))
                    creados += 1

                    cur.execute("""
                        UPDATE creadores
                        SET seguidores = %s, me_gusta = %s, videos = %s
                        WHERE id = %s
                    """, (seguidores, me_gusta, videos, creador_activo_id))
                    actualizados += 1

                conn.commit()
                return {
                    "ok": True,
                    "registros_creados": creados,
                    "registros_actualizados": actualizados
                }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar el archivo: {e}")


@router.get("/creadores_activos/{creador_activo_id}/foto")
def obtener_foto_creador_activo(creador_activo_id: int):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT foto FROM creadores WHERE id = %s", (creador_activo_id,)
            )
            res = cur.fetchone()
            if not res or not res[0]:
                raise HTTPException(status_code=404, detail="Foto no encontrada")
            return {"foto_url": res[0]}


# -------------------------------------------
# -------------------------------------------
# -----ENDPOINTS TALEND CARD---------
# -------------------------------------------
# -------------------------------------------

# ============================================================
# HELPERS
# ============================================================

def parse_jsonb(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def nivel_por_score(score):
    if score is None:
        return "SIN_DATOS"

    score = float(score)

    if score < 2.5:
        return "BAJO"
    if score < 4:
        return "MEDIO"
    return "ALTO"


def color_por_nivel(nivel):
    return {
        "BAJO": "red",
        "MEDIO": "yellow",
        "ALTO": "green",
        "SIN_DATOS": "gray"
    }.get(nivel, "gray")


def prioridad_por_score(score):
    if score is None:
        return "sin_datos"

    score = float(score)

    if score < 2.5:
        return "alta"
    if score < 4:
        return "media"
    return "baja"


def texto_analisis_categoria(nombre_categoria, nivel):
    if nivel == "ALTO":
        return f"{nombre_categoria} es una fortaleza clara del creador."
    if nivel == "MEDIO":
        return f"{nombre_categoria} muestra potencial entrenable y requiere seguimiento."
    if nivel == "BAJO":
        return f"{nombre_categoria} requiere fortalecimiento prioritario."
    return f"No hay información suficiente para analizar {nombre_categoria}."


def recomendacion_capacitacion(nombre_variable, campo_db, nivel):
    if nivel == "ALTO":
        return f"{nombre_variable} está en buen nivel. Se recomienda mantener seguimiento."

    recomendaciones = {
        "kpi_compliance_real": "Reforzar normas de comunidad, políticas de contenido y prevención de infracciones.",
        "kpi_monetizacion_live": "Capacitar en dinámicas de monetización, regalos, retención y activación de audiencia.",
        "kpi_uso_operativo": "Capacitar en herramientas LIVE, funciones de TikTok, OBS, TikTok Live Studio o Tikfinity.",
        "kpi_calidad_tecnica": "Fortalecer setup, iluminación, encuadre, audio y producción básica del entorno."
    }

    return recomendaciones.get(
        campo_db,
        f"Requiere capacitación en {nombre_variable}."
    )


def normalizar_respuesta(row, opciones_map=None):
    """
    Normaliza la respuesta para que React la pueda pintar sin lógica compleja.
    Importante:
    - Para boton usa respuesta_valor_id.
    - respuesta_valor_id corrige también casos viejos donde el ID quedó en valor_texto.
    """

    respuesta_valor_id = row.get("respuesta_valor_id")

    if respuesta_valor_id is not None:
        return {
            "tipo": "opcion",
            "valor_id": respuesta_valor_id,
            "label": row.get("valor_label"),
            "score": row.get("valor_score"),
            "nivel": row.get("valor_nivel")
        }

    if row.get("valor_json") is not None:
        raw = parse_jsonb(row["valor_json"])

        if isinstance(raw, list):
            opciones = []

            if opciones_map:
                for item in raw:
                    try:
                        item_id = int(item)
                        if item_id in opciones_map:
                            opciones.append(opciones_map[item_id])
                    except Exception:
                        pass

            return {
                "tipo": "multiple",
                "valor": raw,
                "opciones": opciones
            }

        return {
            "tipo": "json",
            "valor": raw
        }

    if row.get("valor_texto") is not None:
        return {
            "tipo": "texto",
            "valor": row["valor_texto"]
        }

    if row.get("valor_numeric") is not None:
        return {
            "tipo": "numeric",
            "valor": float(row["valor_numeric"])
        }

    if row.get("valor_integer") is not None:
        return {
            "tipo": "integer",
            "valor": row["valor_integer"]
        }

    return {
        "tipo": "sin_respuesta",
        "valor": None
    }


def construir_variable_payload(row, opciones_map=None):
    return {
        "variable_id": row["variable_id"],
        "nombre": row["variable_nombre"],
        "campo_db": row["campo_db"],
        "pregunta": row["pregunta"],
        "tipo": row["tipo"],
        "tipo_form": row["tipo_form"],
        "peso_variable": float(row["peso_variable"] or 0),
        "orden": row["variable_orden"],
        "respuesta": normalizar_respuesta(row, opciones_map)
    }


# ============================================================
# QUERY BASE FILTRABLE
# ============================================================

def obtener_rows_por_tipos_categoria(
    cur,
    creador_id: int,
    encuesta_id: int,
    tipos_categoria: Optional[List[str]] = None
):
    """
    Si tipos_categoria es None, trae todas las categorías.
    Si tipos_categoria tiene valores, filtra desde SQL.
    """

    params = [creador_id, encuesta_id]
    filtro_tipo = ""

    if tipos_categoria:
        tipos_normalizados = [t.upper() for t in tipos_categoria]
        placeholders = ", ".join(["%s"] * len(tipos_normalizados))
        filtro_tipo = f" AND UPPER(c.tipo) IN ({placeholders}) "
        params.extend(tipos_normalizados)

    cur.execute(f"""
        SELECT
            c.id AS categoria_id,
            c.nombre AS categoria_nombre,
            c.nombre_natural,
            c.descripcion AS categoria_descripcion,
            c.orden AS categoria_orden,
            c.tipo AS categoria_tipo,

            v.id AS variable_id,
            v.nombre AS variable_nombre,
            v.campo_db,
            v.texto AS pregunta,
            v.tipo,
            v.tipo_form,
            COALESCE(v.peso_variable, 0) AS peso_variable,
            v.orden AS variable_orden,

            r.valor_integer,
            r.valor_numeric,
            r.valor_texto,
            r.valor_json,
            r.valor_id,

            COALESCE(
                r.valor_id,
                CASE
                    WHEN v.tipo_form = 'boton'
                     AND r.valor_texto ~ '^[0-9]+$'
                    THEN r.valor_texto::integer
                    ELSE NULL
                END
            ) AS respuesta_valor_id,

            val.label AS valor_label,
            val.score AS valor_score,
            val.nivel AS valor_nivel
        FROM creadores_perfil_variable v
        INNER JOIN creadores_perfil_categoria c
            ON c.id = v.categoria_id
        LEFT JOIN creadores_perfil_respuesta r
            ON r.variable_id = v.id
           AND r.creador_id = %s
        LEFT JOIN creadores_perfil_valor val
            ON val.id = COALESCE(
                r.valor_id,
                CASE
                    WHEN v.tipo_form = 'boton'
                     AND r.valor_texto ~ '^[0-9]+$'
                    THEN r.valor_texto::integer
                    ELSE NULL
                END
            )
        WHERE v.encuesta_id = %s
          AND COALESCE(v.activa, true) = true
          AND COALESCE(c.activa, true) = true
          {filtro_tipo}
        ORDER BY c.orden ASC NULLS LAST, v.orden ASC NULLS LAST, v.id ASC
    """, params)

    return cur.fetchall()


def obtener_opciones_multiple_map(cur, rows):
    multiple_ids = set()

    for row in rows:
        valor_json = parse_jsonb(row.get("valor_json"))

        if isinstance(valor_json, list):
            for item in valor_json:
                if str(item).isdigit():
                    multiple_ids.add(int(item))

    opciones_map = {}

    if multiple_ids:
        cur.execute("""
            SELECT
                id,
                variable_id,
                label,
                score,
                nivel
            FROM creadores_perfil_valor
            WHERE id = ANY(%s)
        """, (list(multiple_ids),))

        for opt in cur.fetchall():
            opciones_map[opt["id"]] = {
                "valor_id": opt["id"],
                "variable_id": opt["variable_id"],
                "label": opt["label"],
                "score": opt["score"],
                "nivel": opt["nivel"]
            }

    return opciones_map


def agrupar_rows_por_categoria(rows, opciones_map=None):
    categorias_map = {}

    for row in rows:
        categoria_id = row["categoria_id"]

        if categoria_id not in categorias_map:
            categorias_map[categoria_id] = {
                "categoria_id": categoria_id,
                "nombre": row["categoria_nombre"],
                "nombre_natural": row["nombre_natural"],
                "descripcion": row["categoria_descripcion"],
                "tipo": row["categoria_tipo"],
                "orden": row["categoria_orden"],
                "variables": []
            }

        categorias_map[categoria_id]["variables"].append(
            construir_variable_payload(row, opciones_map)
        )

    return list(categorias_map.values())


# ============================================================
# ENDPOINT 1: DETALLE GENERAL DE TODAS LAS VARIABLES
# ============================================================

@router.get("/api/creadores/{creador_id}/perfil-detalle")
def obtener_perfil_detalle_completo(
    creador_id: int,
    encuesta_id: int = Query(2)
):
    """
    Muestra todo el detalle de todas las variables de todas las categorías.
    Este sí es el endpoint general.
    """

    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id
                    FROM creadores
                    WHERE id = %s
                    LIMIT 1
                """, (creador_id,))

                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="No se encontró el creador")

                rows = obtener_rows_por_tipos_categoria(
                    cur,
                    creador_id,
                    encuesta_id,
                    tipos_categoria=None
                )

                opciones_map = obtener_opciones_multiple_map(cur, rows)

        return {
            "ok": True,
            "creador_id": creador_id,
            "encuesta_id": encuesta_id,
            "categorias": agrupar_rows_por_categoria(rows, opciones_map)
        }

    except HTTPException:
        raise

    except Exception as e:
        print("❌ Error obteniendo perfil detalle completo:", e)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Error obteniendo detalle completo del perfil"
        )


# ============================================================
# ENDPOINT 2: SOLO DATOS BÁSICOS
# ============================================================

@router.get("/api/creadores/{creador_id}/perfil-basico")
def obtener_perfil_basico_creador(
    creador_id: int,
    encuesta_id: int = Query(2)
):
    """
    Solo trae categoría tipo DATOS_BASICOS.
    Filtra directo en SQL.
    """

    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id
                    FROM creadores
                    WHERE id = %s
                    LIMIT 1
                """, (creador_id,))

                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="No se encontró el creador")

                rows = obtener_rows_por_tipos_categoria(
                    cur,
                    creador_id,
                    encuesta_id,
                    tipos_categoria=["DATOS_BASICOS"]
                )

                opciones_map = obtener_opciones_multiple_map(cur, rows)

        perfil_basico = {}

        for row in rows:
            campo = row["campo_db"] or f"variable_{row['variable_id']}"
            perfil_basico[campo] = construir_variable_payload(row, opciones_map)

        return {
            "ok": True,
            "creador_id": creador_id,
            "encuesta_id": encuesta_id,
            "perfil_basico": perfil_basico
        }

    except HTTPException:
        raise

    except Exception as e:
        print("❌ Error obteniendo perfil básico:", e)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Error obteniendo perfil básico"
        )


# ============================================================
# ENDPOINT 3: ANÁLISIS ESTADÍSTICO DIAGNÓSTICO
# ============================================================

@router.get("/api/creadores/{creador_id}/talent-card/analisis-diagnostico")
def obtener_analisis_estadistico_diagnostico(
    creador_id: int,
    encuesta_id: int = Query(2)
):
    """
    Endpoint pensado para Talent Card.
    No devuelve todo el detalle pesado.
    Devuelve métricas, score ponderado, distribución y decisiones.
    Solo categorías tipo DIAGNOSTICO.
    """

    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id
                    FROM creadores
                    WHERE id = %s
                    LIMIT 1
                """, (creador_id,))

                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="No se encontró el creador")

                rows = obtener_rows_por_tipos_categoria(
                    cur,
                    creador_id,
                    encuesta_id,
                    tipos_categoria=["DIAGNOSTICO"]
                )

                opciones_map = obtener_opciones_multiple_map(cur, rows)

        categorias_map = {}
        fortalezas = []
        oportunidades = []
        riesgos = []

        total_ponderado = 0
        total_pesos = 0
        total_variables = 0
        total_respondidas = 0

        distribucion = {
            "BAJO": 0,
            "MEDIO": 0,
            "ALTO": 0,
            "SIN_DATOS": 0
        }

        for row in rows:
            categoria_id = row["categoria_id"]

            if categoria_id not in categorias_map:
                categorias_map[categoria_id] = {
                    "categoria_id": categoria_id,
                    "nombre": row["categoria_nombre"],
                    "nombre_natural": row["nombre_natural"],
                    "descripcion": row["categoria_descripcion"],
                    "orden": row["categoria_orden"],
                    "_suma_ponderada": 0,
                    "_suma_pesos": 0,
                    "_respondidas": 0,
                    "_total_variables": 0,
                    "variables_resumen": []
                }

            peso = float(row["peso_variable"] or 0)
            score = row["valor_score"]
            nivel = nivel_por_score(score)

            total_variables += 1
            categorias_map[categoria_id]["_total_variables"] += 1

            if score is not None:
                total_respondidas += 1
                categorias_map[categoria_id]["_respondidas"] += 1
                distribucion[nivel] += 1

                if peso > 0:
                    categorias_map[categoria_id]["_suma_ponderada"] += float(score) * peso
                    categorias_map[categoria_id]["_suma_pesos"] += peso
                    total_ponderado += float(score) * peso
                    total_pesos += peso

                variable_resumen = {
                    "variable_id": row["variable_id"],
                    "nombre": row["variable_nombre"],
                    "campo_db": row["campo_db"],
                    "pregunta": row["pregunta"],
                    "peso_variable": peso,
                    "score": score,
                    "nivel": nivel,
                    "color": color_por_nivel(nivel),
                    "respuesta": normalizar_respuesta(row, opciones_map)
                }

                categorias_map[categoria_id]["variables_resumen"].append(variable_resumen)

                if float(score) >= 4:
                    fortalezas.append(variable_resumen)
                elif float(score) < 2.5:
                    riesgos.append(variable_resumen)
                else:
                    oportunidades.append(variable_resumen)

            else:
                distribucion["SIN_DATOS"] += 1

        categorias = []

        for cat in categorias_map.values():
            suma_pesos = cat.pop("_suma_pesos")
            suma_ponderada = cat.pop("_suma_ponderada")
            respondidas = cat.pop("_respondidas")
            total_cat = cat.pop("_total_variables")

            score_categoria = round(suma_ponderada / suma_pesos, 2) if suma_pesos > 0 else None
            nivel_categoria = nivel_por_score(score_categoria)

            cat["analisis"] = {
                "score": score_categoria,
                "nivel": nivel_categoria,
                "color": color_por_nivel(nivel_categoria),
                "variables_respondidas": respondidas,
                "total_variables": total_cat,
                "porcentaje_respuesta": round((respondidas / total_cat) * 100, 2) if total_cat else 0,
                "texto": texto_analisis_categoria(cat["nombre"], nivel_categoria)
            }

            categorias.append(cat)

        score_general = round(total_ponderado / total_pesos, 2) if total_pesos > 0 else None
        nivel_general = nivel_por_score(score_general)

        decision = {
            "nivel": nivel_general,
            "color": color_por_nivel(nivel_general),
            "resumen": texto_analisis_categoria("Diagnóstico general", nivel_general),
            "accion_sugerida": (
                "Priorizar acompañamiento antes de escalarlo."
                if nivel_general == "BAJO"
                else "Mantener seguimiento y plan de mejora."
                if nivel_general == "MEDIO"
                else "Perfil con alto potencial para escalar resultados."
                if nivel_general == "ALTO"
                else "Completar respuestas para generar análisis."
            )
        }

        return {
            "ok": True,
            "creador_id": creador_id,
            "encuesta_id": encuesta_id,
            "tipo": "DIAGNOSTICO",
            "score_general": score_general,
            "nivel_general": nivel_general,
            "color": color_por_nivel(nivel_general),
            "porcentaje_respuesta": round((total_respondidas / total_variables) * 100, 2) if total_variables else 0,
            "estadisticas": {
                "total_variables": total_variables,
                "variables_respondidas": total_respondidas,
                "distribucion_niveles": distribucion,
                "total_fortalezas": len(fortalezas),
                "total_oportunidades": len(oportunidades),
                "total_riesgos": len(riesgos)
            },
            "decision": decision,
            "categorias": categorias,
            "insights": {
                "fortalezas": sorted(fortalezas, key=lambda x: x["score"], reverse=True)[:5],
                "oportunidades": sorted(oportunidades, key=lambda x: x["score"])[:5],
                "riesgos": sorted(riesgos, key=lambda x: x["score"])[:5]
            }
        }

    except HTTPException:
        raise

    except Exception as e:
        print("❌ Error obteniendo análisis diagnóstico:", e)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Error obteniendo análisis diagnóstico"
        )


# ============================================================
# ENDPOINT 4: DETALLE DIAGNÓSTICO + CAPACITACIÓN
# ============================================================

@router.get("/api/creadores/{creador_id}/talent-card/detalle")
def obtener_detalle_diagnostico_capacitacion(
    creador_id: int,
    encuesta_id: int = Query(2)
):
    """
    Devuelve detalle de variables para Talent Card:
    - DIAGNOSTICO
    - CAPACITACION
    No incluye DATOS_BASICOS.
    """

    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id
                    FROM creadores
                    WHERE id = %s
                    LIMIT 1
                """, (creador_id,))

                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="No se encontró el creador")

                rows = obtener_rows_por_tipos_categoria(
                    cur,
                    creador_id,
                    encuesta_id,
                    tipos_categoria=["DIAGNOSTICO", "CAPACITACION"]
                )

                opciones_map = obtener_opciones_multiple_map(cur, rows)

        categorias = agrupar_rows_por_categoria(rows, opciones_map)

        capacitacion_necesidades = []

        for categoria in categorias:
            if (categoria.get("tipo") or "").upper() != "CAPACITACION":
                continue

            for variable in categoria["variables"]:
                respuesta = variable.get("respuesta") or {}
                score = respuesta.get("score")
                nivel = nivel_por_score(score)
                prioridad = prioridad_por_score(score)

                variable["capacitacion"] = {
                    "score": score,
                    "nivel": nivel,
                    "color": color_por_nivel(nivel),
                    "prioridad": prioridad,
                    "requiere_capacitacion": prioridad in ["alta", "media"],
                    "recomendacion": recomendacion_capacitacion(
                        variable["nombre"],
                        variable["campo_db"],
                        nivel
                    )
                }

                if prioridad in ["alta", "media"]:
                    capacitacion_necesidades.append({
                        "variable_id": variable["variable_id"],
                        "nombre": variable["nombre"],
                        "campo_db": variable["campo_db"],
                        "score": score,
                        "nivel": nivel,
                        "prioridad": prioridad,
                        "color": color_por_nivel(nivel),
                        "recomendacion": variable["capacitacion"]["recomendacion"]
                    })

        capacitacion_necesidades = sorted(
            capacitacion_necesidades,
            key=lambda x: {"alta": 1, "media": 2, "baja": 3, "sin_datos": 4}.get(x["prioridad"], 5)
        )

        return {
            "ok": True,
            "creador_id": creador_id,
            "encuesta_id": encuesta_id,
            "categorias": categorias,
            "capacitacion_resumen": {
                "total_necesidades": len(capacitacion_necesidades),
                "prioridad_alta": len([n for n in capacitacion_necesidades if n["prioridad"] == "alta"]),
                "prioridad_media": len([n for n in capacitacion_necesidades if n["prioridad"] == "media"]),
                "sin_necesidades": len(capacitacion_necesidades) == 0,
                "necesidades": capacitacion_necesidades
            }
        }

    except HTTPException:
        raise

    except Exception as e:
        print("❌ Error obteniendo detalle Talent Card:", e)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Error obteniendo detalle de Talent Card"
        )


def parse_jsonb(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def nivel_por_score(score):
    if score is None:
        return "SIN_DATOS"
    score = float(score)
    if score < 2.5:
        return "BAJO"
    if score < 4:
        return "MEDIO"
    return "ALTO"


def color_por_nivel(nivel):
    return {
        "BAJO": "red",
        "MEDIO": "amber",
        "ALTO": "green",
        "SIN_DATOS": "gray"
    }.get(nivel, "gray")


def prioridad_por_score(score):
    if score is None:
        return "sin_datos"
    score = float(score)
    if score < 2.5:
        return "alta"
    if score < 4:
        return "media"
    return "baja"


def recomendacion_capacitacion(campo_db, nombre_variable, nivel):
    recomendaciones = {
        "kpi_compliance_real": {
            "tema": "Normas y cumplimiento de plataforma",
            "recomendacion": "Capacitar en normas de comunidad, políticas de contenido, prevención de infracciones y buenas prácticas para proteger la cuenta y la agencia."
        },
        "kpi_monetizacion_live": {
            "tema": "Monetización y retención en LIVE",
            "recomendacion": "Capacitar en dinámicas de regalos, metas, retención de audiencia, activación del chat y estrategias para mejorar ingresos."
        },
        "kpi_uso_operativo": {
            "tema": "Herramientas LIVE",
            "recomendacion": "Capacitar en uso operativo de TikTok LIVE, TikTok Live Studio, OBS, Tikfinity, alertas, escenas y funciones disponibles."
        },
        "kpi_calidad_tecnica": {
            "tema": "Setup, producción y calidad técnica",
            "recomendacion": "Capacitar en iluminación, encuadre, sonido, fondo, presencia visual y optimización básica del entorno de transmisión."
        }
    }

    base = recomendaciones.get(campo_db, {
        "tema": nombre_variable,
        "recomendacion": f"Capacitar en {nombre_variable}."
    })

    if nivel == "ALTO":
        return {
            "tema": base["tema"],
            "recomendacion": f"{base['tema']} está en buen nivel. Mantener seguimiento y refuerzo ligero."
        }

    return base


def normalizar_respuesta_capacitacion(row):
    if row.get("respuesta_valor_id") is not None:
        return {
            "tipo": "opcion",
            "valor_id": row["respuesta_valor_id"],
            "label": row.get("valor_label"),
            "score": row.get("valor_score"),
            "nivel": row.get("valor_nivel")
        }

    if row.get("valor_json") is not None:
        return {
            "tipo": "json",
            "valor": parse_jsonb(row["valor_json"])
        }

    if row.get("valor_texto") is not None:
        return {
            "tipo": "texto",
            "valor": row["valor_texto"]
        }

    if row.get("valor_numeric") is not None:
        return {
            "tipo": "numeric",
            "valor": float(row["valor_numeric"])
        }

    if row.get("valor_integer") is not None:
        return {
            "tipo": "integer",
            "valor": row["valor_integer"]
        }

    return {
        "tipo": "sin_respuesta",
        "valor": None
    }


@router.get("/api/creadores/{creador_id}/talent-card/capacitacion")
def obtener_capacitacion_talent_card(
    creador_id: int,
    encuesta_id: int = Query(2)
):
    """
    Devuelve la categoría CAPACITACION con:
    - detalle de variables
    - score general de capacitación
    - necesidades priorizadas
    - temas sugeridos de capacitación
    """

    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                # Validar creador
                cur.execute("""
                    SELECT id
                    FROM creadores
                    WHERE id = %s
                    LIMIT 1
                """, (creador_id,))

                if not cur.fetchone():
                    raise HTTPException(
                        status_code=404,
                        detail="No se encontró el creador"
                    )

                # Traer solo CAPACITACION
                cur.execute("""
                    SELECT
                        c.id AS categoria_id,
                        c.nombre AS categoria_nombre,
                        c.nombre_natural,
                        c.descripcion AS categoria_descripcion,
                        c.orden AS categoria_orden,
                        c.tipo AS categoria_tipo,

                        v.id AS variable_id,
                        v.nombre AS variable_nombre,
                        v.campo_db,
                        v.texto AS pregunta,
                        v.tipo,
                        v.tipo_form,
                        COALESCE(v.peso_variable, 0) AS peso_variable,
                        v.orden AS variable_orden,

                        r.valor_integer,
                        r.valor_numeric,
                        r.valor_texto,
                        r.valor_json,
                        r.valor_id,

                        COALESCE(
                            r.valor_id,
                            CASE
                                WHEN v.tipo_form = 'boton'
                                 AND r.valor_texto ~ '^[0-9]+$'
                                THEN r.valor_texto::integer
                                ELSE NULL
                            END
                        ) AS respuesta_valor_id,

                        val.label AS valor_label,
                        val.score AS valor_score,
                        val.nivel AS valor_nivel
                    FROM creadores_perfil_variable v
                    INNER JOIN creadores_perfil_categoria c
                        ON c.id = v.categoria_id
                    LEFT JOIN creadores_perfil_respuesta r
                        ON r.variable_id = v.id
                       AND r.creador_id = %s
                    LEFT JOIN creadores_perfil_valor val
                        ON val.id = COALESCE(
                            r.valor_id,
                            CASE
                                WHEN v.tipo_form = 'boton'
                                 AND r.valor_texto ~ '^[0-9]+$'
                                THEN r.valor_texto::integer
                                ELSE NULL
                            END
                        )
                    WHERE v.encuesta_id = %s
                      AND UPPER(c.tipo) = 'CAPACITACION'
                      AND COALESCE(v.activa, true) = true
                      AND COALESCE(c.activa, true) = true
                    ORDER BY c.orden ASC NULLS LAST, v.orden ASC NULLS LAST, v.id ASC
                """, (creador_id, encuesta_id))

                rows = cur.fetchall()

        if not rows:
            return {
                "ok": True,
                "creador_id": creador_id,
                "encuesta_id": encuesta_id,
                "capacitacion": None,
                "mensaje": "No hay categoría de capacitación configurada."
            }

        categoria = {
            "categoria_id": rows[0]["categoria_id"],
            "nombre": rows[0]["categoria_nombre"],
            "nombre_natural": rows[0]["nombre_natural"],
            "descripcion": rows[0]["categoria_descripcion"],
            "tipo": rows[0]["categoria_tipo"],
            "orden": rows[0]["categoria_orden"],
            "variables": []
        }

        suma_ponderada = 0
        suma_pesos = 0
        respondidas = 0

        necesidades = []
        temas_capacitacion = []

        distribucion = {
            "BAJO": 0,
            "MEDIO": 0,
            "ALTO": 0,
            "SIN_DATOS": 0
        }

        for row in rows:
            respuesta = normalizar_respuesta_capacitacion(row)

            score = respuesta.get("score")
            nivel = nivel_por_score(score)
            color = color_por_nivel(nivel)
            prioridad = prioridad_por_score(score)

            peso = float(row["peso_variable"] or 0)

            if score is not None and peso > 0:
                suma_ponderada += float(score) * peso
                suma_pesos += peso
                respondidas += 1

            distribucion[nivel] += 1

            recomendacion_data = recomendacion_capacitacion(
                row["campo_db"],
                row["variable_nombre"],
                nivel
            )

            variable_payload = {
                "variable_id": row["variable_id"],
                "nombre": row["variable_nombre"],
                "campo_db": row["campo_db"],
                "pregunta": row["pregunta"],
                "tipo": row["tipo"],
                "tipo_form": row["tipo_form"],
                "peso_variable": peso,
                "orden": row["variable_orden"],
                "respuesta": respuesta,
                "analisis": {
                    "score": score,
                    "nivel": nivel,
                    "color": color,
                    "prioridad": prioridad,
                    "requiere_capacitacion": prioridad in ["alta", "media", "sin_datos"],
                    "tema": recomendacion_data["tema"],
                    "recomendacion": recomendacion_data["recomendacion"]
                }
            }

            categoria["variables"].append(variable_payload)

            if prioridad in ["alta", "media", "sin_datos"]:
                necesidades.append({
                    "variable_id": row["variable_id"],
                    "nombre": row["variable_nombre"],
                    "campo_db": row["campo_db"],
                    "tema": recomendacion_data["tema"],
                    "score": score,
                    "nivel": nivel,
                    "color": color,
                    "prioridad": prioridad,
                    "recomendacion": recomendacion_data["recomendacion"]
                })

                temas_capacitacion.append({
                    "tema": recomendacion_data["tema"],
                    "prioridad": prioridad,
                    "campo_db": row["campo_db"],
                    "variable": row["variable_nombre"],
                    "recomendacion": recomendacion_data["recomendacion"]
                })

        score_general = round(suma_ponderada / suma_pesos, 2) if suma_pesos > 0 else None
        nivel_general = nivel_por_score(score_general)

        necesidades_ordenadas = sorted(
            necesidades,
            key=lambda x: {
                "alta": 1,
                "media": 2,
                "sin_datos": 3,
                "baja": 4
            }.get(x["prioridad"], 5)
        )

        temas_ordenados = sorted(
            temas_capacitacion,
            key=lambda x: {
                "alta": 1,
                "media": 2,
                "sin_datos": 3,
                "baja": 4
            }.get(x["prioridad"], 5)
        )

        if nivel_general == "BAJO":
            texto_general = "El creador requiere un plan de capacitación prioritario antes de escalar su operación."
            accion_sugerida = "Asignar formación inicial y acompañamiento cercano en los temas críticos detectados."
        elif nivel_general == "MEDIO":
            texto_general = "El creador tiene una base funcional, pero necesita refuerzo en áreas específicas."
            accion_sugerida = "Asignar capacitación focalizada en los temas con prioridad alta o media."
        elif nivel_general == "ALTO":
            texto_general = "El creador muestra buen nivel operativo y requiere solo seguimiento o formación avanzada."
            accion_sugerida = "Mantener seguimiento y ofrecer formación avanzada para optimizar resultados."
        else:
            texto_general = "No hay información suficiente para definir necesidades de capacitación."
            accion_sugerida = "Completar la encuesta o revisar respuestas faltantes."

        return {
            "ok": True,
            "creador_id": creador_id,
            "encuesta_id": encuesta_id,
            "capacitacion": {
                "score_general": score_general,
                "nivel_general": nivel_general,
                "color": color_por_nivel(nivel_general),
                "texto_general": texto_general,
                "accion_sugerida": accion_sugerida,
                "resumen": {
                    "total_variables": len(rows),
                    "variables_respondidas": respondidas,
                    "porcentaje_respuesta": round((respondidas / len(rows)) * 100, 2) if rows else 0,
                    "total_necesidades": len(necesidades_ordenadas),
                    "prioridad_alta": len([n for n in necesidades_ordenadas if n["prioridad"] == "alta"]),
                    "prioridad_media": len([n for n in necesidades_ordenadas if n["prioridad"] == "media"]),
                    "sin_datos": len([n for n in necesidades_ordenadas if n["prioridad"] == "sin_datos"]),
                    "sin_necesidades": len(necesidades_ordenadas) == 0,
                    "distribucion_niveles": distribucion
                },
                "necesidades": necesidades_ordenadas,
                "temas_capacitacion": temas_ordenados,
                "categoria": categoria
            }
        }

    except HTTPException:
        raise

    except Exception as e:
        print("❌ Error obteniendo capacitación Talent Card:", e)
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Error obteniendo capacitación del creador"
        )




# =========================================================
# RESUMEN PLANO PARA FRONTEND
# =========================================================

# @router.get("/api/creadores/{creador_id}/perfil-resumen")
# def obtener_resumen_perfil_creador(
#     creador_id: int,
#     encuesta_id: int = Query(2)
# ):
#     """
#     Devuelve las respuestas en formato plano por campo_db.
#     Útil para mostrar ficha/resumen en React.
#     """
#
#     try:
#         with get_connection_context() as conn:
#             with conn.cursor(cursor_factory=RealDictCursor) as cur:
#                 cur.execute("""
#                     SELECT
#                         v.campo_db,
#                         v.nombre,
#                         v.tipo,
#                         v.tipo_form,
#                         r.valor_integer,
#                         r.valor_numeric,
#                         r.valor_texto,
#                         r.valor_json,
#                         r.valor_id,
#                         val.label AS valor_label,
#                         val.score AS valor_score
#                     FROM creadores_perfil_respuesta r
#                     INNER JOIN creadores_perfil_variable v
#                         ON v.id = r.variable_id
#                     LEFT JOIN creadores_perfil_valor val
#                         ON val.id = r.valor_id
#                     WHERE r.creador_id = %s
#                       AND v.encuesta_id = %s
#                     ORDER BY v.orden ASC
#                 """, (creador_id, encuesta_id))
#
#                 rows = cur.fetchall()
#
#         resumen = {}
#
#         for row in rows:
#             campo = row["campo_db"]
#
#             if row["valor_json"] is not None:
#                 valor = row["valor_json"]
#             elif row["valor_texto"] is not None:
#                 valor = row["valor_texto"]
#             elif row["valor_numeric"] is not None:
#                 valor = row["valor_numeric"]
#             elif row["valor_label"] is not None:
#                 valor = {
#                     "valor_id": row["valor_id"],
#                     "score": row["valor_score"],
#                     "label": row["valor_label"]
#                 }
#             else:
#                 valor = row["valor_integer"]
#
#             resumen[campo] = {
#                 "nombre": row["nombre"],
#                 "tipo": row["tipo"],
#                 "tipo_form": row["tipo_form"],
#                 "valor": valor
#             }
#
#         return {
#             "ok": True,
#             "creador_id": creador_id,
#             "resumen": resumen
#         }
#
#     except Exception as e:
#         print("❌ Error obteniendo resumen perfil creador:", e)
#         traceback.print_exc()
#         raise HTTPException(status_code=500, detail="Error obteniendo resumen del creador")
#
#
# # ============================================================
# # HELPERS
# # ============================================================
#
# def parse_jsonb(value):
#     if value is None:
#         return None
#
#     if isinstance(value, (dict, list)):
#         return value
#
#     try:
#         return json.loads(value)
#     except Exception:
#         return value
#
#
# def nivel_por_score(score):
#     if score is None:
#         return "SIN_DATOS"
#
#     score = float(score)
#
#     if score < 2.5:
#         return "BAJO"
#     if score < 4:
#         return "MEDIO"
#     return "ALTO"
#
#
# def color_por_nivel(nivel):
#     return {
#         "BAJO": "red",
#         "MEDIO": "yellow",
#         "ALTO": "green",
#         "SIN_DATOS": "gray"
#     }.get(nivel, "gray")
#
#
# def texto_analisis_categoria(nombre_categoria, nivel):
#     if nivel == "ALTO":
#         return f"{nombre_categoria} es una fortaleza clara del creador."
#     if nivel == "MEDIO":
#         return f"{nombre_categoria} muestra una base entrenable, pero requiere seguimiento."
#     if nivel == "BAJO":
#         return f"{nombre_categoria} requiere fortalecimiento prioritario."
#     return f"No hay información suficiente para analizar {nombre_categoria}."
#
#
# def prioridad_por_score(score):
#     if score is None:
#         return "sin_datos"
#     score = float(score)
#
#     if score <= 2:
#         return "alta"
#     if score < 4:
#         return "media"
#     return "baja"
#
#
# def recomendacion_capacitacion(nombre_variable, campo_db, nivel):
#     if nivel == "ALTO":
#         return f"{nombre_variable} está en buen nivel. Se recomienda mantener seguimiento."
#
#     recomendaciones = {
#         "kpi_compliance_real": "Reforzar normas de comunidad, políticas de contenido y prevención de infracciones.",
#         "kpi_monetizacion_live": "Capacitar en dinámicas de monetización, regalos, retención y activación de audiencia.",
#         "kpi_uso_operativo": "Capacitar en herramientas LIVE, funciones de TikTok, OBS, Live Studio o Tikfinity.",
#         "kpi_calidad_tecnica": "Fortalecer setup, iluminación, encuadre, audio y producción básica del entorno."
#     }
#
#     return recomendaciones.get(
#         campo_db,
#         f"Requiere capacitación en {nombre_variable}."
#     )
#
#
# def normalizar_respuesta(row, opciones_map=None):
#     """
#     Devuelve respuesta en formato estándar para React.
#     """
#
#     if row.get("valor_id") is not None:
#         return {
#             "tipo": "opcion",
#             "valor_id": row["valor_id"],
#             "label": row.get("valor_label"),
#             "score": row.get("valor_score"),
#             "nivel": row.get("valor_nivel")
#         }
#
#     if row.get("valor_json") is not None:
#         raw = parse_jsonb(row["valor_json"])
#
#         if isinstance(raw, list) and opciones_map:
#             opciones = []
#
#             for item in raw:
#                 try:
#                     item_id = int(item)
#                     if item_id in opciones_map:
#                         opciones.append(opciones_map[item_id])
#                 except Exception:
#                     pass
#
#             return {
#                 "tipo": "multiple",
#                 "valor": raw,
#                 "opciones": opciones
#             }
#
#         return {
#             "tipo": "json",
#             "valor": raw
#         }
#
#     if row.get("valor_texto") is not None:
#         return {
#             "tipo": "texto",
#             "valor": row["valor_texto"]
#         }
#
#     if row.get("valor_numeric") is not None:
#         return {
#             "tipo": "numeric",
#             "valor": float(row["valor_numeric"])
#         }
#
#     if row.get("valor_integer") is not None:
#         return {
#             "tipo": "integer",
#             "valor": row["valor_integer"]
#         }
#
#     return {
#         "tipo": "sin_respuesta",
#         "valor": None
#     }
#
#
# def calcular_score_categoria(categoria):
#     suma_ponderada = categoria.get("_suma_ponderada", 0)
#     suma_pesos = categoria.get("_suma_pesos", 0)
#
#     if suma_pesos <= 0:
#         return None
#
#     return round(suma_ponderada / suma_pesos, 2)
#
#
# # ============================================================
# # QUERY BASE
# # ============================================================
#
# def obtener_rows_perfil_creador(cur, creador_id: int, encuesta_id: int):
#     cur.execute("""
#         SELECT
#             c.id AS categoria_id,
#             c.nombre AS categoria_nombre,
#             c.nombre_natural,
#             c.descripcion AS categoria_descripcion,
#             c.orden AS categoria_orden,
#             c.tipo AS categoria_tipo,
#
#             v.id AS variable_id,
#             v.nombre AS variable_nombre,
#             v.campo_db,
#             v.texto AS pregunta,
#             v.tipo,
#             v.tipo_form,
#             COALESCE(v.peso_variable, 0) AS peso_variable,
#             v.orden AS variable_orden,
#
#             r.valor_integer,
#             r.valor_numeric,
#             r.valor_texto,
#             r.valor_json,
#             r.valor_id,
#
#             val.label AS valor_label,
#             val.score AS valor_score,
#             val.nivel AS valor_nivel
#         FROM creadores_perfil_variable v
#         INNER JOIN creadores_perfil_categoria c
#             ON c.id = v.categoria_id
#         LEFT JOIN creadores_perfil_respuesta r
#             ON r.variable_id = v.id
#            AND r.creador_id = %s
#         LEFT JOIN creadores_perfil_valor val
#             ON val.id = r.valor_id
#         WHERE v.encuesta_id = %s
#           AND COALESCE(v.activa, true) = true
#           AND COALESCE(c.activa, true) = true
#         ORDER BY c.orden ASC NULLS LAST, v.orden ASC NULLS LAST, v.id ASC
#     """, (creador_id, encuesta_id))
#
#     return cur.fetchall()
#
#
# def obtener_opciones_multiple_map(cur, rows):
#     multiple_ids = set()
#
#     for row in rows:
#         valor_json = parse_jsonb(row.get("valor_json"))
#
#         if isinstance(valor_json, list):
#             for item in valor_json:
#                 if str(item).isdigit():
#                     multiple_ids.add(int(item))
#
#     opciones_map = {}
#
#     if multiple_ids:
#         cur.execute("""
#             SELECT
#                 id,
#                 variable_id,
#                 label,
#                 score,
#                 nivel
#             FROM creadores_perfil_valor
#             WHERE id = ANY(%s)
#         """, (list(multiple_ids),))
#
#         for opt in cur.fetchall():
#             opciones_map[opt["id"]] = {
#                 "valor_id": opt["id"],
#                 "variable_id": opt["variable_id"],
#                 "label": opt["label"],
#                 "score": opt["score"],
#                 "nivel": opt["nivel"]
#             }
#
#     return opciones_map
#
#
# # ============================================================
# # BUILDER PRINCIPAL
# # ============================================================
#
# def construir_talent_card_payload(creador_id: int, encuesta_id: int):
#     with get_connection_context() as conn:
#         with conn.cursor(cursor_factory=RealDictCursor) as cur:
#
#             cur.execute("""
#                 SELECT id
#                 FROM creadores
#                 WHERE id = %s
#                 LIMIT 1
#             """, (creador_id,))
#
#             creador = cur.fetchone()
#
#             if not creador:
#                 raise HTTPException(status_code=404, detail="No se encontró el creador")
#
#             rows = obtener_rows_perfil_creador(cur, creador_id, encuesta_id)
#             opciones_map = obtener_opciones_multiple_map(cur, rows)
#
#     perfil_basico = {}
#     detalle_categorias = {}
#     diagnostico_map = {}
#     capacitacion_map = {}
#
#     for row in rows:
#         categoria_id = row["categoria_id"]
#         categoria_tipo = row["categoria_tipo"]
#
#         respuesta = normalizar_respuesta(row, opciones_map)
#
#         variable_payload = {
#             "variable_id": row["variable_id"],
#             "nombre": row["variable_nombre"],
#             "campo_db": row["campo_db"],
#             "pregunta": row["pregunta"],
#             "tipo": row["tipo"],
#             "tipo_form": row["tipo_form"],
#             "peso_variable": float(row["peso_variable"] or 0),
#             "orden": row["variable_orden"],
#             "respuesta": respuesta
#         }
#
#         # ----------------------------
#         # Perfil básico
#         # ----------------------------
#         if categoria_tipo == "DATOS_BASICOS":
#             campo = row["campo_db"] or f"variable_{row['variable_id']}"
#             perfil_basico[campo] = variable_payload
#
#         # ----------------------------
#         # Detalle completo
#         # ----------------------------
#         if categoria_id not in detalle_categorias:
#             detalle_categorias[categoria_id] = {
#                 "categoria_id": categoria_id,
#                 "nombre": row["categoria_nombre"],
#                 "nombre_natural": row["nombre_natural"],
#                 "descripcion": row["categoria_descripcion"],
#                 "tipo": categoria_tipo,
#                 "orden": row["categoria_orden"],
#                 "variables": []
#             }
#
#         detalle_categorias[categoria_id]["variables"].append(variable_payload)
#
#         # ----------------------------
#         # Diagnóstico
#         # ----------------------------
#         if categoria_tipo == "DIAGNOSTICO":
#             if categoria_id not in diagnostico_map:
#                 diagnostico_map[categoria_id] = {
#                     "categoria_id": categoria_id,
#                     "nombre": row["categoria_nombre"],
#                     "nombre_natural": row["nombre_natural"],
#                     "descripcion": row["categoria_descripcion"],
#                     "tipo": categoria_tipo,
#                     "orden": row["categoria_orden"],
#                     "variables": [],
#                     "_suma_ponderada": 0,
#                     "_suma_pesos": 0,
#                     "_respondidas": 0
#                 }
#
#             peso = float(row["peso_variable"] or 0)
#             score = row["valor_score"]
#
#             if score is not None and peso > 0:
#                 diagnostico_map[categoria_id]["_suma_ponderada"] += float(score) * peso
#                 diagnostico_map[categoria_id]["_suma_pesos"] += peso
#                 diagnostico_map[categoria_id]["_respondidas"] += 1
#
#             diagnostico_map[categoria_id]["variables"].append(variable_payload)
#
#         # ----------------------------
#         # Capacitación
#         # ----------------------------
#         if categoria_tipo == "CAPACITACION":
#             if categoria_id not in capacitacion_map:
#                 capacitacion_map[categoria_id] = {
#                     "categoria_id": categoria_id,
#                     "nombre": row["categoria_nombre"],
#                     "nombre_natural": row["nombre_natural"],
#                     "descripcion": row["categoria_descripcion"],
#                     "tipo": categoria_tipo,
#                     "orden": row["categoria_orden"],
#                     "variables": [],
#                     "_suma_ponderada": 0,
#                     "_suma_pesos": 0,
#                     "_respondidas": 0
#                 }
#
#             peso = float(row["peso_variable"] or 0)
#             score = row["valor_score"]
#
#             if score is not None and peso > 0:
#                 capacitacion_map[categoria_id]["_suma_ponderada"] += float(score) * peso
#                 capacitacion_map[categoria_id]["_suma_pesos"] += peso
#                 capacitacion_map[categoria_id]["_respondidas"] += 1
#
#             capacitacion_map[categoria_id]["variables"].append(variable_payload)
#
#     # ========================================================
#     # ARMAR DIAGNÓSTICO
#     # ========================================================
#
#     diagnostico_categorias = []
#     total_ponderado = 0
#     total_pesos = 0
#
#     for cat in diagnostico_map.values():
#         suma_pesos = cat.pop("_suma_pesos")
#         suma_ponderada = cat.pop("_suma_ponderada")
#         respondidas = cat.pop("_respondidas")
#
#         score_categoria = round(suma_ponderada / suma_pesos, 2) if suma_pesos > 0 else None
#         nivel = nivel_por_score(score_categoria)
#
#         cat["analisis"] = {
#             "score": score_categoria,
#             "nivel": nivel,
#             "color": color_por_nivel(nivel),
#             "variables_respondidas": respondidas,
#             "total_variables": len(cat["variables"]),
#             "porcentaje_respuesta": round(
#                 (respondidas / len(cat["variables"])) * 100, 2
#             ) if cat["variables"] else 0,
#             "texto": texto_analisis_categoria(cat["nombre"], nivel)
#         }
#
#         if score_categoria is not None:
#             total_ponderado += score_categoria * suma_pesos
#             total_pesos += suma_pesos
#
#         diagnostico_categorias.append(cat)
#
#     score_general = round(total_ponderado / total_pesos, 2) if total_pesos > 0 else None
#     nivel_general = nivel_por_score(score_general)
#
#     diagnostico = {
#         "score_general": score_general,
#         "nivel_general": nivel_general,
#         "color": color_por_nivel(nivel_general),
#         "texto_general": texto_analisis_categoria("Diagnóstico general", nivel_general),
#         "categorias": diagnostico_categorias
#     }
#
#     # ========================================================
#     # ARMAR CAPACITACIÓN
#     # ========================================================
#
#     capacitacion_categorias = []
#     necesidades = []
#
#     cap_total_ponderado = 0
#     cap_total_pesos = 0
#
#     for cat in capacitacion_map.values():
#         suma_pesos = cat.pop("_suma_pesos")
#         suma_ponderada = cat.pop("_suma_ponderada")
#         respondidas = cat.pop("_respondidas")
#
#         score_categoria = round(suma_ponderada / suma_pesos, 2) if suma_pesos > 0 else None
#         nivel_categoria = nivel_por_score(score_categoria)
#
#         for variable in cat["variables"]:
#             respuesta = variable.get("respuesta") or {}
#             score_variable = respuesta.get("score")
#             nivel_variable = nivel_por_score(score_variable)
#
#             prioridad = prioridad_por_score(score_variable)
#
#             variable["capacitacion"] = {
#                 "score": score_variable,
#                 "nivel": nivel_variable,
#                 "color": color_por_nivel(nivel_variable),
#                 "prioridad": prioridad,
#                 "requiere_capacitacion": prioridad in ["alta", "media"],
#                 "recomendacion": recomendacion_capacitacion(
#                     variable["nombre"],
#                     variable["campo_db"],
#                     nivel_variable
#                 )
#             }
#
#             if prioridad in ["alta", "media"]:
#                 necesidades.append({
#                     "variable_id": variable["variable_id"],
#                     "nombre": variable["nombre"],
#                     "campo_db": variable["campo_db"],
#                     "score": score_variable,
#                     "nivel": nivel_variable,
#                     "prioridad": prioridad,
#                     "color": color_por_nivel(nivel_variable),
#                     "recomendacion": variable["capacitacion"]["recomendacion"]
#                 })
#
#         cat["analisis"] = {
#             "score": score_categoria,
#             "nivel": nivel_categoria,
#             "color": color_por_nivel(nivel_categoria),
#             "variables_respondidas": respondidas,
#             "total_variables": len(cat["variables"]),
#             "porcentaje_respuesta": round(
#                 (respondidas / len(cat["variables"])) * 100, 2
#             ) if cat["variables"] else 0,
#             "texto": texto_analisis_categoria(cat["nombre"], nivel_categoria)
#         }
#
#         if score_categoria is not None:
#             cap_total_ponderado += score_categoria * suma_pesos
#             cap_total_pesos += suma_pesos
#
#         capacitacion_categorias.append(cat)
#
#     score_capacitacion = (
#         round(cap_total_ponderado / cap_total_pesos, 2)
#         if cap_total_pesos > 0
#         else None
#     )
#
#     nivel_capacitacion = nivel_por_score(score_capacitacion)
#
#     necesidades_ordenadas = sorted(
#         necesidades,
#         key=lambda x: {"alta": 1, "media": 2, "baja": 3, "sin_datos": 4}.get(x["prioridad"], 5)
#     )
#
#     capacitacion = {
#         "score_general": score_capacitacion,
#         "nivel_general": nivel_capacitacion,
#         "color": color_por_nivel(nivel_capacitacion),
#         "texto_general": texto_analisis_categoria("Core Capacitación", nivel_capacitacion),
#         "resumen": {
#             "total_necesidades": len(necesidades_ordenadas),
#             "prioridad_alta": len([n for n in necesidades_ordenadas if n["prioridad"] == "alta"]),
#             "prioridad_media": len([n for n in necesidades_ordenadas if n["prioridad"] == "media"]),
#             "sin_necesidades": len(necesidades_ordenadas) == 0
#         },
#         "necesidades": necesidades_ordenadas,
#         "categorias": capacitacion_categorias
#     }
#
#     return {
#         "ok": True,
#         "creador_id": creador_id,
#         "encuesta_id": encuesta_id,
#         "perfil_basico": perfil_basico,
#         "diagnostico": diagnostico,
#         "capacitacion": capacitacion,
#         "detalle_categorias": list(detalle_categorias.values())
#     }
#
#
# # ============================================================
# # ENDPOINT 1: TALENT CARD COMPLETA
# # ============================================================
#
# @router.get("/api/creadores/{creador_id}/talent-card")
# def obtener_talent_card_creador(
#     creador_id: int,
#     encuesta_id: int = Query(2)
# ):
#     try:
#         return construir_talent_card_payload(creador_id, encuesta_id)
#
#     except HTTPException:
#         raise
#
#     except Exception as e:
#         print("❌ Error obteniendo Talent Card:", e)
#         traceback.print_exc()
#         raise HTTPException(
#             status_code=500,
#             detail="Error obteniendo Talent Card del creador"
#         )
#
#
# # ============================================================
# # ENDPOINT 2: PERFIL BÁSICO
# # ============================================================
#
# @router.get("/api/creadores/{creador_id}/perfil-basico")
# def obtener_perfil_basico_creador(
#     creador_id: int,
#     encuesta_id: int = Query(2)
# ):
#     try:
#         data = construir_talent_card_payload(creador_id, encuesta_id)
#
#         return {
#             "ok": True,
#             "creador_id": creador_id,
#             "encuesta_id": encuesta_id,
#             "perfil_basico": data["perfil_basico"]
#         }
#
#     except HTTPException:
#         raise
#
#     except Exception as e:
#         print("❌ Error obteniendo perfil básico:", e)
#         traceback.print_exc()
#         raise HTTPException(
#             status_code=500,
#             detail="Error obteniendo perfil básico del creador"
#         )
#
#
# # ============================================================
# # ENDPOINT 3: DIAGNÓSTICO
# # ============================================================
#
# @router.get("/api/creadores/{creador_id}/diagnostico")
# def obtener_diagnostico_creador(
#     creador_id: int,
#     encuesta_id: int = Query(2)
# ):
#     try:
#         data = construir_talent_card_payload(creador_id, encuesta_id)
#
#         return {
#             "ok": True,
#             "creador_id": creador_id,
#             "encuesta_id": encuesta_id,
#             "diagnostico": data["diagnostico"]
#         }
#
#     except HTTPException:
#         raise
#
#     except Exception as e:
#         print("❌ Error obteniendo diagnóstico:", e)
#         traceback.print_exc()
#         raise HTTPException(
#             status_code=500,
#             detail="Error obteniendo diagnóstico del creador"
#         )
#
#
# # ============================================================
# # ENDPOINT 4: CORE CAPACITACIÓN
# # ============================================================
#
# @router.get("/api/creadores/{creador_id}/capacitacion-core")
# def obtener_capacitacion_core_creador(
#     creador_id: int,
#     encuesta_id: int = Query(2)
# ):
#     try:
#         data = construir_talent_card_payload(creador_id, encuesta_id)
#
#         return {
#             "ok": True,
#             "creador_id": creador_id,
#             "encuesta_id": encuesta_id,
#             "capacitacion": data["capacitacion"]
#         }
#
#     except HTTPException:
#         raise
#
#     except Exception as e:
#         print("❌ Error obteniendo capacitación core:", e)
#         traceback.print_exc()
#         raise HTTPException(
#             status_code=500,
#             detail="Error obteniendo capacitación core del creador"
#         )
#
#
# # ============================================================
# # ENDPOINT 5: DETALLE POR CATEGORÍAS
# # ============================================================
#
# @router.get("/api/creadores/{creador_id}/perfil-detalle-categorias")
# def obtener_detalle_categorias_creador(
#     creador_id: int,
#     encuesta_id: int = Query(2),
#     tipo_categoria: str | None = Query(None)
# ):
#     """
#     tipo_categoria opcional:
#     - DATOS_BASICOS
#     - DIAGNOSTICO
#     - CAPACITACION
#     """
#
#     try:
#         data = construir_talent_card_payload(creador_id, encuesta_id)
#
#         categorias = data["detalle_categorias"]
#
#         if tipo_categoria:
#             categorias = [
#                 cat for cat in categorias
#                 if (cat.get("tipo") or "").upper() == tipo_categoria.upper()
#             ]
#
#         return {
#             "ok": True,
#             "creador_id": creador_id,
#             "encuesta_id": encuesta_id,
#             "tipo_categoria": tipo_categoria,
#             "categorias": categorias
#         }
#
#     except HTTPException:
#         raise
#
#     except Exception as e:
#         print("❌ Error obteniendo detalle por categorías:", e)
#         traceback.print_exc()
#         raise HTTPException(
#             status_code=500,
#             detail="Error obteniendo detalle por categorías del creador"
#         )
#







# @router.get("/api/creadores_activos", response_model=List[CreadorActivoDB])
# def listar_creadores_activos():
#     try:
#         with get_connection_context() as conn:
#             with conn.cursor() as cur:
#                 cur.execute("SELECT * FROM creadores")
#                 rows = cur.fetchall()
#                 columns = [desc[0] for desc in cur.description]
#                 result = [dict(zip(columns, row)) for row in rows]
#                 return result
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @router.get("/api/creadores_activos/{id}", response_model=CreadorActivoConManager)
# def obtener_creador_activo(id: int):
#     try:
#         with get_connection_context() as conn:
#             with conn.cursor() as cur:
#                 cur.execute("""
#                     SELECT ca.*, au.nombre_completo AS manager_nombre
#                     FROM creadores ca
#                     LEFT JOIN administradores au ON ca.manager_id = au.id
#                     WHERE ca.id = %s
#                 """, (id,))
#                 row = cur.fetchone()
#                 if not row:
#                     raise HTTPException(status_code=404, detail="Creador no encontrado")
#                 columns = [desc[0] for desc in cur.description]
#                 return dict(zip(columns, row))
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @router.put("/api/creadores_activos/{id}", response_model=CreadorActivoDB)
# def editar_creador_activo(id: int, creador: CreadorActivoUpdate):
#     try:
#         with get_connection_context() as conn:
#             with conn.cursor() as cur:
#                 cur.execute("""
#                     UPDATE creadores SET
#                         aspirante_id=%(aspirante_id)s,
#                         nombre=%(nombre)s,
#                         usuario_tiktok=%(usuario_tiktok)s,
#                         email=%(email)s,
#                         telefono=%(telefono)s,
#                         foto=%(foto)s,
#                         categoria=%(categoria)s,
#                         estado=%(estado)s,
#                         manager_id=%(manager_id)s,
#                         horario_lives=%(horario_lives)s,
#                         tiempo_disponible=%(tiempo_disponible)s,
#                         fecha_incorporacion=%(fecha_incorporacion)s,
#                         fecha_graduacion=%(fecha_graduacion)s,
#                         seguidores=%(seguidores)s,
#                         videos=%(videos)s,
#                         me_gusta=%(me_gusta)s,
#                         diamantes=%(diamantes)s,
#                         horas_live=%(horas_live)s,
#                         numero_partidas=%(numero_partidas)s,
#                         dias_emision=%(dias_emision)s
#                     WHERE id=%(id)s
#                     RETURNING *;
#                 """, {**creador.dict(), "id": id})
#                 row = cur.fetchone()
#                 if not row:
#                     raise HTTPException(status_code=404, detail="Creador no encontrado")
#                 conn.commit()
#                 columns = [desc[0] for desc in cur.description]
#                 return dict(zip(columns, row))
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @router.post("/api/creadores_activos", response_model=CreadorActivoDB, status_code=201)
# def agregar_creador_activo(creador: CreadorActivoCreate):
#     try:
#         with get_connection_context() as conn:
#             with conn.cursor() as cur:
#                 cur.execute("""
#                     INSERT INTO creadores (
#                         aspirante_id, nombre, usuario_tiktok, email, telefono, foto, categoria, estado, manager_id,
#                         horario_lives, tiempo_disponible, fecha_incorporacion, fecha_graduacion,
#                         seguidores, videos, me_gusta, diamantes, horas_live, numero_partidas, dias_emision
#                     ) VALUES (
#                         %(aspirante_id)s, %(nombre)s, %(usuario_tiktok)s, %(email)s, %(telefono)s, %(foto)s, %(categoria)s, %(estado)s, %(manager_id)s,
#                         %(horario_lives)s, %(tiempo_disponible)s, %(fecha_incorporacion)s, %(fecha_graduacion)s,
#                         %(seguidores)s, %(videos)s, %(me_gusta)s, %(diamantes)s, %(horas_live)s, %(numero_partidas)s, %(dias_emision)s
#                     ) RETURNING *;
#                 """, creador.dict())
#                 row = cur.fetchone()
#                 conn.commit()
#                 columns = [desc[0] for desc in cur.description]
#                 return dict(zip(columns, row))
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))




