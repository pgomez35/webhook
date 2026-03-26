import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from DataBase import (
    actualizar_datos_aspirantes_perfil,
    actualizar_estado_creador,
    crear_invitacion_minima,
    obtener_aspirantes_db,
    obtener_aspirantes_perfil,
    obtener_biografia_aspirantes_perfil, get_connection_context,
)
from evaluaciones import (
    evaluar_cualitativa,
    evaluar_datos_generales,
    evaluar_estadisticas,
    evaluar_preferencias_habitos,
    evaluar_potencial_creador,
    evaluar_y_mejorar_biografia,
    limpiar_biografia_ia,
)
from main_auth import obtener_usuario_actual
from schemas import (
    DatosPersonalesInput,
    DatosPersonalesOutput,
    EstadoCreadorIn,
    EstadoCreadorOut,
    EstadisticasPerfilInput,
    EstadisticasPerfilOutput,
    EvaluacionCualitativaInput,
    EvaluacionCualitativaOutput,
    GuardarResumenInput,
    PerfilCreadorSchema,
    PreferenciasHabitosInput,
    PreferenciasHabitosOutput,
)

router = APIRouter()

ESTADO_MAP = {
    "Evaluacion": 3,
    "Entrevista": 4,
    "Invitacion": 5,
    "Rechazado": 7,
}
ESTADO_DEFAULT = 99


@router.get("/api/aspirantes", tags=["Creadores"])
def listar_creadores(estado_id: Optional[int] = Query(None, description="Filtrar por estado_id")):
    try:
        try:
            return obtener_aspirantes_db(estado_id=estado_id)
        except TypeError:
            return obtener_aspirantes_db()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/aspirantes/en_proceso", tags=["Creadores"])
def listar_creadores_en_proceso():
    try:
        return obtener_aspirantes_db()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/aspirantes_perfil/{aspirante_id}", tags=["Perfil"])
def aspirantes_perfil(aspirante_id: int):
    perfil = obtener_aspirantes_perfil(aspirante_id)
    if not perfil:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    return perfil


@router.put("/api/aspirantes_perfil/{aspirante_id}", tags=["Perfil"])
def actualizar_aspirantes_perfil_endpoint(aspirante_id: int, evaluacion: PerfilCreadorSchema):
    try:
        data_dict = evaluacion.dict(exclude_unset=True)
        if not data_dict:
            raise HTTPException(status_code=400, detail="No se enviaron datos para actualizar.")
        actualizar_datos_aspirantes_perfil(aspirante_id, data_dict)
        return {"status": "ok", "mensaje": "Perfil actualizado correctamente"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put(
    "/api/aspirantes_perfil/{aspirante_id}/datos_personales",
    tags=["Perfil"],
    response_model=DatosPersonalesOutput,
)
def actualizar_datos_personales(aspirante_id: int, datos: DatosPersonalesInput):
    try:
        data_dict = datos.dict(exclude_unset=True)
        score = evaluar_datos_generales(
            edad=data_dict.get("edad"),
            genero=data_dict.get("genero"),
            idiomas=data_dict.get("idioma"),
            estudios=data_dict.get("estudios"),
            pais=data_dict.get("pais"),
            actividad_actual=data_dict.get("actividad_actual"),
        )
        data_dict["puntaje_general"] = score.get("puntaje_general")
        data_dict["puntaje_general_categoria"] = score.get("puntaje_general_categoria")
        actualizar_datos_aspirantes_perfil(aspirante_id, data_dict)
        return DatosPersonalesOutput(
            status="ok",
            mensaje="Evaluacion datos Generales actualizada",
            puntaje_general=score.get("puntaje_general"),
            puntaje_general_categoria=score.get("puntaje_general_categoria"),
        )
    except Exception as e:
        logging.error(f"Error en PUT /api/aspirantes_perfil/{aspirante_id}/datos_personales: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error al actualizar datos personales")


@router.put(
    "/api/aspirantes_perfil/{aspirante_id}/evaluacion_cualitativa",
    response_model=EvaluacionCualitativaOutput,
    tags=["Evaluacion"],
)
def actualizar_eval_cualitativa(
    aspirante_id: int,
    datos: EvaluacionCualitativaInput,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    try:
        data_dict = datos.dict(exclude_unset=True)
        data_dict["usuario_evalua"] = usuario_actual["nombre"]
        resultado = evaluar_cualitativa(
            apariencia=data_dict.get("apariencia", 0),
            engagement=data_dict.get("engagement", 0),
            calidad_contenido=data_dict.get("calidad_contenido", 0),
            foto=data_dict.get("eval_foto", 0),
            biografia=data_dict.get("eval_biografia", 0),
            metadata_videos=data_dict.get("metadata_videos", 0),
        )
        data_dict["puntaje_manual"] = resultado["puntaje_cualitativo"]
        data_dict["puntaje_manual_categoria"] = resultado["puntaje_cualitativo_categoria"]
        potencial_creador = evaluar_potencial_creador(aspirante_id, resultado["puntaje_cualitativo"])
        nivel_estimado = potencial_creador.get("nivel")
        actualizar_datos_aspirantes_perfil(aspirante_id, data_dict)
        return EvaluacionCualitativaOutput(
            status="ok",
            mensaje="Evaluacion cualitativa actualizada",
            puntaje_manual=resultado["puntaje_cualitativo"],
            puntaje_manual_categoria=resultado["puntaje_cualitativo_categoria"],
            potencial_estimado=nivel_estimado,
        )
    except Exception as e:
        logging.error(f"Error en PUT /api/aspirantes_perfil/{aspirante_id}/evaluacion_cualitativa: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Ocurrio un error interno en el servidor al procesar la evaluacion. Por favor intentalo nuevamente o contacta al administrador.",
        )


@router.put(
    "/api/aspirantes_perfil/{aspirante_id}/estadisticas",
    tags=["Estadisticas"],
    response_model=EstadisticasPerfilOutput,
)
def actualizar_estadisticas(aspirante_id: int, datos: EstadisticasPerfilInput):
    try:
        data_dict = datos.dict(exclude_unset=True)
        score = evaluar_estadisticas(
            seguidores=data_dict.get("seguidores"),
            siguiendo=data_dict.get("siguiendo"),
            videos=data_dict.get("videos"),
            likes=data_dict.get("likes"),
            duracion=data_dict.get("duracion_emisiones"),
        )
        data_dict["puntaje_estadistica"] = score["puntaje_estadistica"]
        data_dict["puntaje_estadistica_categoria"] = score["puntaje_estadistica_categoria"]
        actualizar_datos_aspirantes_perfil(aspirante_id, data_dict)
        return EstadisticasPerfilOutput(
            status="ok",
            mensaje="Estadisticas actualizadas",
            puntaje_estadistica=score["puntaje_estadistica"],
            puntaje_estadistica_categoria=score["puntaje_estadistica_categoria"],
        )
    except Exception as e:
        logging.error(f"Error en PUT /api/aspirantes_perfil/{aspirante_id}/estadisticas: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error al actualizar estadisticas")


@router.put(
    "/api/aspirantes_perfil/{aspirante_id}/preferencias",
    tags=["Preferencias"],
    response_model=PreferenciasHabitosOutput,
)
def actualizar_preferencias(aspirante_id: int, datos: PreferenciasHabitosInput):
    try:
        data_dict = datos.dict(exclude_unset=True)
        score = evaluar_preferencias_habitos(
            exp_otras=data_dict.get("experiencia_otras_plataformas") or {},
            intereses=data_dict.get("intereses") or {},
            tipo_contenido=data_dict.get("tipo_contenido") or {},
            tiempo=data_dict.get("tiempo_disponible"),
            freq_lives=data_dict.get("frecuencia_lives"),
            intencion=data_dict.get("intencion_trabajo"),
        )
        data_dict["puntaje_habitos"] = score["puntaje_habitos"]
        data_dict["puntaje_habitos_categoria"] = score["puntaje_habitos_categoria"]
        actualizar_datos_aspirantes_perfil(aspirante_id, data_dict)
        return PreferenciasHabitosOutput(
            status="ok",
            mensaje="Preferencias actualizadas",
            puntaje_habitos=score["puntaje_habitos"],
            puntaje_habitos_categoria=score["puntaje_habitos_categoria"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/aspirantes_perfil/{aspirante_id}/resumen")
def guardar_resumen_final(aspirante_id: int, datos: GuardarResumenInput):
    try:
        payload = {
            "diagnostico": datos.diagnostico,
            "mejoras_sugeridas": datos.mejoras_sugeridas,
            "observaciones_finales": datos.observaciones_finales,
            "usuario_evalua": datos.usuario_evalua,
            "estado_evaluacion": datos.estado_evaluacion,
        }
        actualizar_datos_aspirantes_perfil(aspirante_id, payload)
        entrevista_creada = None
        if datos.estado_evaluacion:
            estado_id = ESTADO_MAP.get(datos.estado_evaluacion, ESTADO_DEFAULT)
            actualizar_estado_creador(aspirante_id, estado_id)
            if estado_id == 5:
                invitacion_creada = crear_invitacion_minima(aspirante_id, estado="pendiente_tiktok")
                if invitacion_creada:
                    print(f"Invitacion creada correctamente para aspirante {aspirante_id}: {invitacion_creada}")
                else:
                    print(f"No se pudo crear la invitacion para el aspirante {aspirante_id}")
        return {
            "status": "ok",
            "mensaje": "Resumen actualizado correctamente",
            "entrevista_creada": entrevista_creada,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/aspirantes_perfil/{aspirante_id}/biografia_ia", tags=["Biografia IA"])
def actualizar_biografia_ia(aspirante_id: int):
    try:
        bio_texto = obtener_biografia_aspirantes_perfil(aspirante_id)
        if not bio_texto:
            raise HTTPException(status_code=404, detail="No existe biografia previa para este perfil.")
        try:
            biografia_sugerida = evaluar_y_mejorar_biografia(bio_texto)
        except Exception:
            raise HTTPException(status_code=500, detail="Error generando la biografia con IA.")
        biografia_sugerida = biografia_sugerida[:500]
        biografia_sugerida = limpiar_biografia_ia(biografia_sugerida)
        try:
            actualizar_datos_aspirantes_perfil(aspirante_id, {"biografia_sugerida": biografia_sugerida})
        except Exception:
            raise HTTPException(status_code=500, detail="Error guardando la biografia en la base de datos.")
        return {
            "status": "ok",
            "mensaje": "Biografia IA generada y guardada exitosamente",
            "biografia_sugerida": biografia_sugerida,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put(
    "/api/aspirantes/{aspirante_id}/estado",
    tags=["Creadores"],
    response_model=EstadoCreadorOut,
)
def actualizar_estado_creador_endpoint(
    aspirante_id: int,
    datos: EstadoCreadorIn = Body(...),
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    if not usuario_actual or not usuario_actual.get("id"):
        raise HTTPException(status_code=401, detail="Usuario no autorizado")
    estado_id: Optional[int] = None
    if datos.estado_id is not None:
        estado_id = int(datos.estado_id)
    elif datos.estado_evaluacion:
        estado_id = ESTADO_MAP.get(datos.estado_evaluacion, ESTADO_DEFAULT)
    else:
        raise HTTPException(status_code=400, detail="Debes enviar 'estado_id' o 'estado_evaluacion'.")
    res = actualizar_estado_creador(aspirante_id, estado_id)
    if not res:
        raise HTTPException(status_code=404, detail="Creador no encontrado")
    return EstadoCreadorOut(**res, mensaje="Estado del creador actualizado correctamente")



# ---------------------------------------
# ---------------------------------------
# ---------------------------------------


import logging

logger = logging.getLogger("uvicorn.error")

CAMPOS_CATALOGO_PERFIL = (
    "edad",
    "genero",
    "actividad_actual",
    "frecuencia_lives",
    "tiempo_disponible",
    "intencion_trabajo",
    "experiencia_tiktok_live",
    "pais",
)


@router.get("/api/aspirantes_perfil/catalogos/lista")
def obtener_catalogos_aspirante_perfil():
    return cargar_catalogos_aspirante_perfil()


def cargar_catalogos_aspirante_perfil():
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        a.campo_db,
                        b.id AS valor_id,
                        b.label,
                        b.orden,
                        b.score,
                        b.nivel
                    FROM diagnostico_variable a
                    INNER JOIN diagnostico_variable_valor b
                        ON a.id = b.variable_id
                    WHERE a.campo_db IN %s
                      AND COALESCE(a.activa, true) = true
                    ORDER BY a.campo_db, COALESCE(b.orden, 9999), b.id
                """, (CAMPOS_CATALOGO_PERFIL,))

                rows = cur.fetchall()
                catalogos = {campo: [] for campo in CAMPOS_CATALOGO_PERFIL}

                for campo_db, valor_id, label, orden, score, nivel in rows:
                    if campo_db not in catalogos:
                        continue

                    item = {
                        "id": valor_id,
                        "value": valor_id,
                        "label": label,
                        "orden": orden,
                    }

                    if score is not None:
                        item["score"] = score

                    if nivel:
                        item["nivel"] = nivel

                    catalogos[campo_db].append(item)

                return catalogos

    except Exception as e:
        logger.exception(f"❌ Error al cargar catálogos de aspirantes_perfil: {e}")
        return {}