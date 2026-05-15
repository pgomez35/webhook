import json
import traceback
from typing import Optional, Any, Dict

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import JSONResponse
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from DataBase import get_connection_context
from main_portal_usuarios import (
    obtener_configuracion_soporte_portal,
    PortalConfiguracionOut,
)

router = APIRouter()


class IniciarEncuestaCreadorInput(BaseModel):
    creador_id: int
    meta: Optional[dict] = None


class ConsolidarEncuestaCreadorInput(BaseModel):
    creador_id: int
    respuestas: Dict[Any, Any]
    meta: Optional[dict] = None
    origen: Optional[str] = None


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


def habilitar_trazabilidad_encuesta_creador(
        creador_id: int,
        respuestas_json: Optional[dict] = None
) -> bool:
    try:
        respuestas_json = respuestas_json or {}
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO creadores_encuesta_inicial (
                        creador_id,
                        respuestas_json,
                        fecha_inicio,
                        completada,
                        abandonada,
                        preguntas_respondidas,
                        sincronizado,
                        updated_at
                    )
                    VALUES (%s, %s::jsonb, now(), false, false, 0, false, now())
                    ON CONFLICT (creador_id)
                    DO UPDATE SET
                        respuestas_json = COALESCE(EXCLUDED.respuestas_json, creadores_encuesta_inicial.respuestas_json),
                        fecha_inicio = COALESCE(creadores_encuesta_inicial.fecha_inicio, now()),
                        completada = false,
                        abandonada = false,
                        updated_at = now()
                """, (
                    creador_id,
                    json.dumps(respuestas_json, ensure_ascii=False)
                ))
            conn.commit()

        print(f"✅ Encuesta de creador habilitada para creador_id={creador_id}")
        return True

    except Exception as e:
        print(f"❌ Error habilitando encuesta creador: {e}")
        traceback.print_exc()
        return False


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

                cur.execute("""
                    SELECT id
                    FROM creadores
                    WHERE id = %s
                    LIMIT 1
                """, (data.creador_id,))

                creador = cur.fetchone()

                if not creador:
                    return JSONResponse(
                        {"error": "No se encontró creador"},
                        status_code=404
                    )

                cur.execute("""
                    SELECT
                        id,
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
                preguntas_omitidas = []

                for pregunta_id, valor in respuestas_dict.items():
                    variable = variables.get(pregunta_id)

                    if not variable:
                        preguntas_omitidas.append(pregunta_id)
                        continue

                    tipo = (variable.get("tipo") or "").lower().strip()
                    tipo_form = (variable.get("tipo_form") or "").lower().strip()

                    valor_integer = None
                    valor_id = None
                    valor_numeric = None
                    valor_texto = None
                    valor_json = None

                    if valor is None or valor == "":
                        pass

                    elif tipo_form == "boton":
                        try:
                            valor_id = int(valor)
                        except Exception:
                            valor_texto = str(valor).strip()

                    elif tipo_form == "multiple":
                        if isinstance(valor, list):
                            valor_json = json.dumps(valor, ensure_ascii=False)
                        else:
                            valor_json = json.dumps([valor], ensure_ascii=False)

                    elif tipo_form == "number":
                        try:
                            valor_numeric = float(valor)
                        except Exception:
                            valor_texto = str(valor).strip()

                    elif tipo_form == "text":
                        valor_texto = str(valor).strip()

                    elif tipo in ["json", "jsonb"] or isinstance(valor, (dict, list)):
                        valor_json = json.dumps(valor, ensure_ascii=False)

                    elif tipo in ["boton", "select", "radio", "escala"]:
                        try:
                            valor_id = int(valor)
                        except Exception:
                            valor_texto = str(valor).strip()

                    elif tipo in ["number", "numeric", "decimal", "float"]:
                        try:
                            valor_numeric = float(valor)
                        except Exception:
                            valor_texto = str(valor).strip()

                    elif tipo in ["integer", "int", "numero_entero"]:
                        try:
                            valor_integer = int(valor)
                        except Exception:
                            valor_texto = str(valor).strip()

                    else:
                        valor_texto = str(valor).strip()

                    cur.execute("""
                        INSERT INTO creadores_perfil_respuesta (
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
                        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, now(), now())
                        ON CONFLICT (creador_id, variable_id)
                        DO UPDATE SET
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

                cur.execute("""
                    INSERT INTO creadores_encuesta_inicial (
                        creador_id,
                        respuestas_json,
                        fecha_inicio,
                        fecha_fin,
                        completada,
                        abandonada,
                        preguntas_respondidas,
                        sincronizado,
                        updated_at
                    )
                    VALUES (%s, %s::jsonb, now(), now(), true, false, %s, false, now())
                    ON CONFLICT (creador_id)
                    DO UPDATE SET
                        respuestas_json = EXCLUDED.respuestas_json,
                        fecha_inicio = COALESCE(creadores_encuesta_inicial.fecha_inicio, now()),
                        fecha_fin = now(),
                        completada = true,
                        abandonada = false,
                        preguntas_respondidas = EXCLUDED.preguntas_respondidas,
                        updated_at = now()
                """, (
                    data.creador_id,
                    json.dumps(respuestas_dict, ensure_ascii=False),
                    preguntas_guardadas
                ))

            conn.commit()

        return {
            "ok": True,
            "msg": "Encuesta de creador consolidada correctamente",
            "creador_id": data.creador_id,
            "preguntas_guardadas": preguntas_guardadas,
            "preguntas_omitidas": preguntas_omitidas
        }

    except Exception as e:
        print(f"❌ Error en consolidar_encuesta_creador: {e}")
        traceback.print_exc()
        return JSONResponse(
            {
                "error": "Error al consolidar encuesta del creador",
                "detalle": str(e)
            },
            status_code=500
        )

@router.get("/api/portal/creador/inicio")
def portal_creador_inicio(creador_id: int = Query(..., gt=0)):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                cur.execute("""
                    SELECT
                        c.id,
                        c.nombre,
                        c.usuario_tiktok,
                        ce.nombre AS estado,
                        COALESCE(cei.completada, false) AS encuesta_inicial_completada
                    FROM creadores c
                    LEFT JOIN creadores_estados ce ON ce.id = c.estado_id
                    LEFT JOIN creadores_encuesta_inicial cei
                        ON cei.creador_id = c.id
                    WHERE c.id = %s
                    LIMIT 1
                """, (creador_id,))

                row = cur.fetchone()

                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail="No se encontró el creador."
                    )

                (
                    creador_id,
                    nombre,
                    usuario_tiktok,
                    estado,
                    encuesta_inicial_completada
                ) = row

                encuesta_inicial_completada = bool(encuesta_inicial_completada)

                pantalla = (
                    "dashboard_creador"
                    if encuesta_inicial_completada
                    else "encuesta_inicial"
                )

                cfg_portal = obtener_configuracion_soporte_portal()

                return {
                    "valid": True,
                    "tipo_portal": "creador",
                    "creador": {
                        "id": creador_id,
                        "nombre": nombre,
                        "usuario_tiktok": usuario_tiktok,
                        "estado": estado
                    },
                    "encuesta_inicial": {
                        "completada": encuesta_inicial_completada
                    },
                    "pantalla": pantalla,
                    "configuracion_portal": PortalConfiguracionOut.model_validate(
                        cfg_portal
                    ).model_dump(),
                }

    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"valid": False, "error": e.detail}
        )

    except Exception as e:
        print(f"❌ Error en portal creador inicio: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "valid": False,
                "error": "Error interno cargando el portal del creador.",
                "detail": str(e)
            }
        )
