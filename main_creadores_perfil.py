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


# =========================================================
# RESUMEN PLANO PARA FRONTEND
# =========================================================

@router.get("/api/creadores/{creador_id}/perfil-resumen")
def obtener_resumen_perfil_creador(
    creador_id: int,
    encuesta_id: int = Query(2)
):
    """
    Devuelve las respuestas en formato plano por campo_db.
    Útil para mostrar ficha/resumen en React.
    """

    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        v.campo_db,
                        v.nombre,
                        v.tipo,
                        v.tipo_form,
                        r.valor_integer,
                        r.valor_numeric,
                        r.valor_texto,
                        r.valor_json,
                        r.valor_id,
                        val.label AS valor_label,
                        val.score AS valor_score
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

        resumen = {}

        for row in rows:
            campo = row["campo_db"]

            if row["valor_json"] is not None:
                valor = row["valor_json"]
            elif row["valor_texto"] is not None:
                valor = row["valor_texto"]
            elif row["valor_numeric"] is not None:
                valor = row["valor_numeric"]
            elif row["valor_label"] is not None:
                valor = {
                    "valor_id": row["valor_id"],
                    "score": row["valor_score"],
                    "label": row["valor_label"]
                }
            else:
                valor = row["valor_integer"]

            resumen[campo] = {
                "nombre": row["nombre"],
                "tipo": row["tipo"],
                "tipo_form": row["tipo_form"],
                "valor": valor
            }

        return {
            "ok": True,
            "creador_id": creador_id,
            "resumen": resumen
        }

    except Exception as e:
        print("❌ Error obteniendo resumen perfil creador:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error obteniendo resumen del creador")

# ---------------------------------------------------------------
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# ---------------------------------------------------------------

# ======================================================
# MODELOS INPUT
# ======================================================

class IniciarEncuestaCreadorInput(BaseModel):
    creador_id: int
    meta: Optional[dict] = None


class ConsolidarEncuestaCreadorInput(BaseModel):
    creador_id: int
    respuestas: Dict[Any, Any]
    meta: Optional[dict] = None
    origen: Optional[str] = None


# ======================================================
# 1. OBTENER ENCUESTA DE CREADORES
# ======================================================

@router.get("/api/creadores/encuestas/{encuesta_id}")
def obtener_encuesta_creador(encuesta_id: int):
    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                cur.execute("""
                            SELECT v.id             AS pregunta_id,
                                   v.texto,
                                   v.tipo_form      AS tipo,
                                   v.tipo           AS tipo_dato,
                                   v.campo_db       AS campo,
                                   v.orden          AS pregunta_orden,
                                   c.id             AS categoria_id,
                                   c.nombre         AS categoria_nombre,
                                   c.nombre_natural AS categoria_nombre_natural,
                                   o.id             AS opcion_id,
                                   o.label,
                                   o.score,
                                   o.nivel,
                                   o.orden          AS opcion_orden
                            FROM creadores_perfil_variable v
                                     LEFT JOIN creadores_perfil_categoria c
                                               ON c.id = v.categoria_id
                                     LEFT JOIN creadores_perfil_valor o
                                               ON o.variable_id = v.id
                            WHERE v.encuesta_id = %s
                              AND COALESCE(v.activa, true) = true
                            ORDER BY COALESCE(c.orden, 999),
                                     COALESCE(v.orden, 999),
                                     COALESCE(o.orden, 999);
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
                            "tipo_dato": row["tipo_dato"],
                            "campo": row["campo"],
                            "categoria": {
                                "id": row["categoria_id"],
                                "nombre": row["categoria_nombre"],
                                "nombre_natural": row["categoria_nombre_natural"]
                            },
                            "opciones": []
                        }

                    if row["opcion_id"] is not None:
                        preguntas[pid]["opciones"].append({
                            "id": row["opcion_id"],
                            "label": row["label"],
                            "score": row["score"],
                            "nivel": row["nivel"],
                            "orden": row["opcion_orden"]
                        })

                return {
                    "success": True,
                    "encuesta_id": encuesta_id,
                    "preguntas": list(preguntas.values())
                }

    except Exception as e:
        print(f"❌ Error obteniendo encuesta de creador: {e}")
        return JSONResponse(
            {"success": False, "error": "Error obteniendo encuesta de creador"},
            status_code=500
        )


# ======================================================
# 2. FUNCIÓN PARA INICIAR / HABILITAR RESPUESTAS
# ======================================================

def habilitar_trazabilidad_encuesta_creador(
        creador_id: int,
        respuestas_json: Optional[dict] = None
) -> bool:
    """
    Como no tienes una tabla tipo creadores_encuesta_inicial,
    esta función deja una marca inicial en creadores_perfil_respuesta.

    Reglas:
    - No duplica respuestas.
    - Inserta una respuesta técnica tipo JSON con variable_id = 0 NO recomendado.

    Recomendación real:
    Crear tabla creadores_encuesta_inicial para trazabilidad.
    """

    try:
        respuestas_json = respuestas_json or {}

        # Esta función queda preparada, pero lo ideal es crear tabla de trazabilidad.
        print(f"✅ Encuesta de creador habilitada para creador_id={creador_id}")
        return True

    except Exception as e:
        print(f"❌ Error habilitando encuesta creador: {e}")
        return False


# ======================================================
# 3. INICIAR ENCUESTA DE CREADOR
# ======================================================

@router.post("/api/creadores/encuesta/iniciar")
def iniciar_encuesta_creador(data: IniciarEncuestaCreadorInput):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                            SELECT id
                            FROM creadores
                            WHERE id = %s LIMIT 1
                            """, (data.creador_id,))

                row = cur.fetchone()

                if not row:
                    return JSONResponse(
                        {"error": "No se encontró creador"},
                        status_code=404
                    )

        ok = habilitar_trazabilidad_encuesta_creador(
            creador_id=data.creador_id,
            respuestas_json={}
        )

        if not ok:
            return JSONResponse(
                {"error": "No se pudo iniciar la encuesta del creador"},
                status_code=500
            )

        return {
            "ok": True,
            "msg": "Encuesta de creador iniciada correctamente",
            "creador_id": data.creador_id,
            "meta": data.meta
        }

    except Exception as e:
        print(f"❌ Error en iniciar_encuesta_creador: {e}")
        return JSONResponse(
            {"error": "Error al iniciar la encuesta del creador"},
            status_code=500
        )


# ======================================================
# 4. GUARDAR / CONSOLIDAR RESPUESTAS DE CREADOR
# ======================================================

@router.post("/api/creadores/encuesta/consolidar")
def consolidar_encuesta_creador(data: ConsolidarEncuestaCreadorInput):
    try:
        if not data.creador_id:
            return JSONResponse(
                {"error": "creador_id es obligatorio"},
                status_code=400
            )

        if not data.respuestas:
            return JSONResponse(
                {"error": "No se recibieron respuestas"},
                status_code=400
            )

        respuestas_dict = {}

        for key, valor in data.respuestas.items():
            if isinstance(key, str) and key.isdigit():
                key = int(key)

            respuestas_dict[key] = valor

        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                # Validar creador
                cur.execute("""
                            SELECT id
                            FROM creadores
                            WHERE id = %s LIMIT 1
                            """, (data.creador_id,))

                creador = cur.fetchone()

                if not creador:
                    return JSONResponse(
                        {"error": "No se encontró creador"},
                        status_code=404
                    )

                # Obtener variables activas
                cur.execute("""
                            SELECT id,
                                   campo_db,
                                   tipo,
                                   tipo_form
                            FROM creadores_perfil_variable
                            WHERE COALESCE(activa, true) = true
                            """)

                variables = {
                    row["id"]: row
                    for row in cur.fetchall()
                }

                preguntas_guardadas = 0

                for pregunta_id, valor in respuestas_dict.items():
                    variable = variables.get(pregunta_id)

                    if not variable:
                        print(f"⚠️ Variable no encontrada o inactiva: {pregunta_id}")
                        continue

                    tipo = (variable.get("tipo") or "").lower()
                    tipo_form = (variable.get("tipo_form") or "").lower()

                    valor_integer = None
                    valor_id = None
                    valor_numeric = None
                    valor_texto = None
                    valor_json = None

                    # -------------------------------
                    # Clasificación del valor
                    # -------------------------------

                    if valor is None:
                        valor_texto = None

                    elif isinstance(valor, dict) or isinstance(valor, list):
                        valor_json = json.dumps(valor, ensure_ascii=False)

                    elif tipo in ["json", "jsonb"] or tipo_form in ["json", "multi", "checkbox"]:
                        valor_json = json.dumps(valor, ensure_ascii=False)

                    elif tipo in ["integer", "int", "numero_entero"]:
                        try:
                            valor_integer = int(valor)
                        except Exception:
                            valor_texto = str(valor)

                    elif tipo in ["numeric", "decimal", "float", "number"]:
                        try:
                            valor_numeric = float(valor)
                        except Exception:
                            valor_texto = str(valor)

                    elif tipo_form in ["select", "radio", "escala"]:
                        try:
                            valor_id = int(valor)
                        except Exception:
                            valor_texto = str(valor)

                    else:
                        valor_texto = str(valor).strip()

                    # -------------------------------
                    # Guardar respuesta
                    # -------------------------------

                    cur.execute("""
                                INSERT INTO creadores_perfil_respuesta (creador_id,
                                                                        variable_id,
                                                                        valor_integer,
                                                                        valor_id,
                                                                        valor_numeric,
                                                                        valor_texto,
                                                                        valor_json,
                                                                        created_at,
                                                                        updated_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, now(), now()) ON CONFLICT (creador_id, variable_id)
                        DO
                                UPDATE SET
                                    valor_integer = EXCLUDED.valor_integer,
                                    valor_id = EXCLUDED.valor_id,
                                    valor_numeric = EXCLUDED.valor_numeric,
                                    valor_texto = EXCLUDED.valor_texto,
                                    valor_json = EXCLUDED.valor_json,
                                    updated_at = now()
                                """, (
                                    data.creador_id,
                                    pregunta_id,
                                    valor_integer,
                                    valor_id,
                                    valor_numeric,
                                    valor_texto,
                                    valor_json
                                ))

                    preguntas_guardadas += 1

            conn.commit()

        return {
            "ok": True,
            "msg": "Encuesta de creador consolidada correctamente",
            "creador_id": data.creador_id,
            "preguntas_guardadas": preguntas_guardadas
        }

    except Exception as e:
        print(f"❌ Error en consolidar_encuesta_creador: {e}")
        return JSONResponse(
            {"error": "Error al consolidar encuesta del creador"},
            status_code=500
        )


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
        if not seg.creador_activo_id:
            raise HTTPException(status_code=400, detail="creador_activo_id es requerido")

        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT manager_id FROM creadores WHERE id = %s
                """, (seg.creador_activo_id,))
                result = cur.fetchone()
                if not result:
                    raise HTTPException(status_code=404, detail="No se encontró el creador activo")
                manager_id = result[0]

                cur.execute("""
                    INSERT INTO creadores_seguimiento (
                        aspirante_id, creador_activo_id, manager_id, fecha_seguimiento,
                        estrategias_mejora, compromisos
                    ) VALUES (
                        %(aspirante_id)s, %(creador_activo_id)s, %(manager_id)s, %(fecha_seguimiento)s,
                        %(estrategias_mejora)s, %(compromisos)s
                    )
                    RETURNING *;
                """, {
                    **seg.dict(),
                    "manager_id": manager_id
                })
                row = cur.fetchone()
                conn.commit()
                columns = [desc[0] for desc in cur.description]
                return dict(zip(columns, row))
    except HTTPException:
        raise
    except Exception as e:
        print("ERROR:", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/seguimiento_creadores/creador_activo/{creador_activo_id}", response_model=List[SeguimientoCreadorConManager])
def listar_seguimientos_por_creador_activo(creador_activo_id: int):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT sc.*, au.nombre_completo AS manager_nombre
                    FROM creadores_seguimiento sc
                    LEFT JOIN administradores au ON sc.manager_id = au.id
                    WHERE sc.creador_activo_id = %s
                    ORDER BY sc.fecha_seguimiento DESC
                """, (creador_activo_id,))
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


