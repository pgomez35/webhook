import logging
import json
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException

from tenant import current_tenant, current_business_name
from DataBase import get_connection_context

logger = logging.getLogger(__name__)
router = APIRouter()


# =====================================================
# Utilidades de scoring / niveles
# =====================================================
def convertir_score_a_nivel_5(score: float) -> int:
    """Convierte score (0..5) a nivel 1..5."""
    if score >= 4.2:
        return 5
    elif score >= 3.8:
        return 4
    elif score >= 3.2:
        return 3
    elif score >= 2.5:
        return 2
    return 1


def nivel_5_a_3(nivel_5: int) -> int:
    """Reduce 1..5 a 1..3 para scripts cortos."""
    if nivel_5 <= 2:
        return 1
    if nivel_5 == 3:
        return 2
    return 3


def grupo_tarjeta(nivel_5: int) -> Dict[str, Any]:
    """
    Para front:
      Fortalezas = 1
      Desarrollo = 2
      Riesgos     = 3
    """
    if nivel_5 >= 4:
        return {"grupo_id": 1, "grupo_nombre": "Fortalezas"}
    if nivel_5 == 3:
        return {"grupo_id": 2, "grupo_nombre": "Desarrollo"}
    return {"grupo_id": 3, "grupo_nombre": "Riesgos"}


def icono_semaforo(nivel_3: int) -> str:
    if nivel_3 == 3:
        return "🟢"
    if nivel_3 == 2:
        return "🟡"
    return "🔴"


# =====================================================
# Resumen ejecutivo por filas (sin motor)
# =====================================================
def generar_resumen_ejecutivo_filas(categorias: List[Dict[str, Any]]) -> str:
    """
    Espera categorias con:
      - categoria_nombre
      - nivel_3
      - script_3
    Devuelve 4 filas ordenadas:
      POTENCIAL DE TALENTO
      CAPACIDAD OPERATIVA
      POTENCIAL DE MONETIZACIÓN
      INTENCIÓN Y ALINEACIÓN
    """

    def linea(nivel_3: int, texto: str) -> str:
        return f"{icono_semaforo(nivel_3)} {texto}"

    # Mapeo flexible por nombre (por si en DB "Mercado" y tú lo llamas "Monetización")
    mapa = {
        "POTENCIAL DE TALENTO": None,
        "CAPACIDAD OPERATIVA": None,
        "POTENCIAL DE MONETIZACIÓN": None,
        "INTENCIÓN Y ALINEACIÓN": None,
    }

    for c in categorias:
        nombre = (c.get("categoria_nombre") or "").strip()
        n3 = int(c.get("nivel_3") or 1)
        s3 = (c.get("script_3") or "").strip()

        if not s3:
            s3 = "Sin definición estratégica."

        if nombre == "Potencial de Talento":
            mapa["POTENCIAL DE TALENTO"] = linea(n3, s3)

        elif nombre == "Capacidad Operativa":
            mapa["CAPACIDAD OPERATIVA"] = linea(n3, s3)

        elif nombre in ("Potencial de Mercado", "Potencial de Monetización"):
            mapa["POTENCIAL DE MONETIZACIÓN"] = linea(n3, s3)

        elif nombre == "Intención y Alineación":
            mapa["INTENCIÓN Y ALINEACIÓN"] = linea(n3, s3)

    filas = []
    if mapa["POTENCIAL DE TALENTO"]:
        filas.append(f"POTENCIAL DE TALENTO: {mapa['POTENCIAL DE TALENTO']}")
    if mapa["CAPACIDAD OPERATIVA"]:
        filas.append(f"CAPACIDAD OPERATIVA: {mapa['CAPACIDAD OPERATIVA']}")
    if mapa["POTENCIAL DE MONETIZACIÓN"]:
        filas.append(f"POTENCIAL DE MONETIZACIÓN: {mapa['POTENCIAL DE MONETIZACIÓN']}")
    if mapa["INTENCIÓN Y ALINEACIÓN"]:
        filas.append(f"INTENCIÓN Y ALINEACIÓN: {mapa['INTENCIÓN Y ALINEACIÓN']}")

    return "\n\n".join(filas)


# =====================================================
# DB helpers
# =====================================================
def obtener_modelo_activo(cur) -> Dict[str, Any]:
    cur.execute("""
        SELECT id, nombre
        FROM modelo_evaluacion
        WHERE activo = true
        LIMIT 1
    """)
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="No hay modelo activo")
    return {"modelo_id": row[0], "modelo_nombre": row[1]}


def obtener_perfil_creador(cur, creador_id: int) -> Dict[str, Any]:
    cur.execute("""
        SELECT nombre, edad, genero, pais, ciudad
        FROM perfil_creador
        WHERE creador_id = %s
        LIMIT 1
    """, (creador_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Creador no encontrado en perfil_creador")
    return {
        "nombre": row[0],
        "edad": row[1],
        "genero": row[2],
        "pais": row[3],
        "ciudad": row[4],
    }


def obtener_categorias_modelo(cur, modelo_id: int) -> List[Dict[str, Any]]:
    cur.execute("""
        SELECT id, nombre, peso_categoria
        FROM modelo_categoria
        WHERE modelo_id = %s
        ORDER BY id ASC
    """, (modelo_id,))
    rows = cur.fetchall()
    if not rows:
        raise HTTPException(status_code=400, detail="El modelo activo no tiene categorías configuradas")
    return [{"categoria_id": r[0], "categoria_nombre": r[1], "peso_categoria": float(r[2])} for r in rows]


def obtener_variables_de_categoria(cur, categoria_id: int) -> List[Dict[str, Any]]:
    cur.execute("""
        SELECT id, peso_variable
        FROM modelo_variable
        WHERE categoria_id = %s
    """, (categoria_id,))
    rows = cur.fetchall()
    return [{"variable_id": r[0], "peso_variable": float(r[1])} for r in rows]


def obtener_score_variable(cur, creador_id: int, variable_id: int) -> int:
    cur.execute("""
        SELECT score
        FROM talento_score_variable
        WHERE creador_id = %s
          AND variable_id = %s
        LIMIT 1
    """, (creador_id, variable_id))
    row = cur.fetchone()
    return int(row[0]) if row else 0


def obtener_script(cur, categoria_id: int, escala: int, nivel: int) -> str:
    cur.execute("""
        SELECT script
        FROM talento_script_categoria
        WHERE categoria_id = %s
          AND escala = %s
          AND nivel = %s
        LIMIT 1
    """, (categoria_id, escala, nivel))
    row = cur.fetchone()
    return row[0] if row else "Sin definición estratégica."


def sobrescribir_score_categoria(cur, creador_id: int, modelo_id: int, filas: List[Dict[str, Any]]) -> None:
    cur.execute("""
        DELETE FROM talento_score_categoria
        WHERE creador_id = %s AND modelo_id = %s
    """, (creador_id, modelo_id))

    for f in filas:
        cur.execute("""
            INSERT INTO talento_score_categoria (modelo_id, creador_id, categoria_id, score_categoria, nivel)
            VALUES (%s, %s, %s, %s, %s)
        """, (modelo_id, creador_id, f["categoria_id"], f["score_categoria"], f["nivel_5"]))


def sobrescribir_score_general(
    cur,
    creador_id: int,
    modelo_id: int,
    puntaje_total: float,
    nivel_5: int,
    diagnostico_json: dict,
    diagnostico_resumen: str
) -> None:
    cur.execute("""
        DELETE FROM talento_score_general
        WHERE creador_id = %s AND modelo_id = %s
    """, (creador_id, modelo_id))

    cur.execute("""
        INSERT INTO talento_score_general (creador_id, modelo_id, puntaje_total, nivel, diagnostico_json, diagnostico_resumen)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s)
    """, (
        creador_id,
        modelo_id,
        puntaje_total,
        nivel_5,
        json.dumps(diagnostico_json, ensure_ascii=False),
        (diagnostico_resumen or "")[:200]
    ))


def actualizar_diagnostico_perfil(cur, creador_id: int, texto: str) -> None:
    cur.execute("""
        UPDATE perfil_creador
        SET diagnostico = %s
        WHERE creador_id = %s
    """, (texto, creador_id))


# =====================================================
# Cálculo principal (sin MotorEnsamblajeV4)
# =====================================================
def calcular_diagnostico(conn, creador_id: int) -> Dict[str, Any]:
    cur = conn.cursor()

    # 1) Modelo activo
    modelo = obtener_modelo_activo(cur)
    modelo_id = modelo["modelo_id"]
    modelo_nombre = modelo["modelo_nombre"]

    # 2) Perfil demográfico
    perfil = obtener_perfil_creador(cur, creador_id)

    # 3) Categorías + pesos
    categorias = obtener_categorias_modelo(cur, modelo_id)

    resultado_categorias: List[Dict[str, Any]] = []
    score_total = 0.0

    # 4) Calcular score por categoría (ponderado por variable) y score total (ponderado por categoría)
    for c in categorias:
        cat_id = c["categoria_id"]
        cat_nombre = c["categoria_nombre"]
        peso_cat = c["peso_categoria"]

        variables = obtener_variables_de_categoria(cur, cat_id)

        score_categoria = 0.0
        for v in variables:
            var_id = v["variable_id"]
            peso_var = v["peso_variable"]
            score_var = obtener_score_variable(cur, creador_id, var_id)
            score_categoria += (score_var * (peso_var / 100.0))

        score_categoria = round(score_categoria, 2)
        nivel_5 = convertir_score_a_nivel_5(score_categoria)
        nivel_3 = nivel_5_a_3(nivel_5)

        # Scripts:
        script_5 = obtener_script(cur, cat_id, escala=5, nivel=nivel_5)   # requerido
        script_3 = obtener_script(cur, cat_id, escala=3, nivel=nivel_3)   # corto (para resumen)

        grupo = grupo_tarjeta(nivel_5)

        resultado_categorias.append({
            "categoria_id": cat_id,
            "categoria_nombre": cat_nombre,
            "peso_categoria": peso_cat,
            "score_5": score_categoria,
            "nivel_5": nivel_5,
            "nivel_3": nivel_3,
            "grupo_id": grupo["grupo_id"],
            "grupo_nombre": grupo["grupo_nombre"],
            "script_5": script_5,
            "script_3": script_3,
            "porcentaje": round((score_categoria / 5.0) * 100.0, 2),
        })

        score_total += (score_categoria * (peso_cat / 100.0))

    score_total = round(score_total, 2)
    nivel_total_5 = convertir_score_a_nivel_5(score_total)
    nivel_total_3 = nivel_5_a_3(nivel_total_5)

    # 5) Nuevo texto ejecutivo por filas + semáforo
    texto_ejecutivo = generar_resumen_ejecutivo_filas(resultado_categorias)
    resumen_corto = texto_ejecutivo[:200]

    # 6) Guardado (sobrescribir)
    sobrescribir_score_categoria(cur, creador_id, modelo_id, [
        {"categoria_id": c["categoria_id"], "score_categoria": c["score_5"], "nivel_5": c["nivel_5"]}
        for c in resultado_categorias
    ])

    diagnostico_json = {
        "creador_id": creador_id,
        "modelo": {"id": modelo_id, "nombre": modelo_nombre},
        "score_total": score_total,
        "nivel_total_5": nivel_total_5,
        "nivel_total_3": nivel_total_3,
        "texto_ejecutivo": texto_ejecutivo,
        "categorias": [
            {
                "categoria_id": c["categoria_id"],
                "nombre": c["categoria_nombre"],
                "peso_categoria": c["peso_categoria"],
                "score_5": c["score_5"],
                "nivel_5": c["nivel_5"],
                "nivel_3": c["nivel_3"],
                "grupo_id": c["grupo_id"],
                "grupo_nombre": c["grupo_nombre"],
                "script_5": c["script_5"],
                "script_3": c["script_3"],
            }
            for c in resultado_categorias
        ],
        "version_motor": "filas_v1"
    }

    sobrescribir_score_general(
        cur,
        creador_id=creador_id,
        modelo_id=modelo_id,
        puntaje_total=score_total,
        nivel_5=nivel_total_5,
        diagnostico_json=diagnostico_json,
        diagnostico_resumen=resumen_corto
    )

    # Actualiza perfil_creador.diagnostico con el texto ejecutivo (filas)
    actualizar_diagnostico_perfil(cur, creador_id, texto_ejecutivo)

    return {
        "modelo": {"id": modelo_id, "nombre": modelo_nombre},
        "perfil": perfil,
        "score_total": score_total,
        "nivel_total_5": nivel_total_5,
        "nivel_total_3": nivel_total_3,
        "texto_ejecutivo": texto_ejecutivo,
        "categorias": resultado_categorias,
    }


# =====================================================
# ENDPOINT
# =====================================================
@router.get("/api/creadores/{creador_id}/diagnostico")
def diagnostico_creador(creador_id: int):
    TENANT = current_tenant.get() if "current_tenant" in globals() else None
    if TENANT is None:
        raise HTTPException(status_code=400, detail="Tenant no disponible")

    with get_connection_context() as conn:
        data = calcular_diagnostico(conn, creador_id)
        conn.commit()

    nombre_agencia = current_business_name.get() if "current_business_name" in globals() else None

    return {
        "agencia": {"nombre": nombre_agencia},
        **data
    }
# import traceback
# import logging
# import pytz
# import secrets
# import string
# import random
# import json
#
# from pydantic import BaseModel, EmailStr
# from psycopg2.extras import RealDictCursor
# from datetime import datetime, timedelta
# from typing import Optional, List, Dict, Any
# from fastapi import APIRouter, HTTPException, Depends
# from schemas import *
# from main_auth import obtener_usuario_actual
#
# from tenant import current_tenant, current_business_name  # si ya los tienes (opcional)
# from DataBase import get_connection_context
#
# logger = logging.getLogger(__name__)
#
# router = APIRouter()   # ← ESTE ES EL ROUTER QUE VAS A IMPORTAR EN main.py
#
# # =====================================================
# # Motor de Ensamblaje (tu versión, sin cambios)
# # =====================================================
# class MotorEnsamblajeV4:
#     def __init__(self):
#         self.inicios = [
#             "Como síntesis ejecutiva, ",
#             "En el análisis estratégico del perfil, ",
#             "Evaluando el desempeño integral, ",
#             "Desde una perspectiva profesional, "
#         ]
#
#         self.conectores_adicion = [" Asimismo, ", " Además, ", " y adicionalmente "]
#         self.conectores_transicion = [
#             ". Por otro lado, ",
#             ". En términos de optimización, ",
#             ". A nivel de evolución estratégica, "
#         ]
#         self.conectores_adversidad = [
#             ". Sin embargo, ",
#             ". No obstante, ",
#             ". Como punto de atención prioritaria, "
#         ]
#
#         self.cierres_modelo = {
#             "Modelo Talento Premium": {
#                 "alto": ["El perfil está alineado con estándares premium de alto rendimiento."],
#                 "medio": ["Con ajustes estratégicos puede consolidarse en entorno premium."],
#                 "bajo": ["Debe reforzar fundamentos antes de aspirar a un posicionamiento premium."]
#             },
#             "Modelo Incubación": {
#                 "alto": ["El acompañamiento potenciará su consolidación acelerada."],
#                 "medio": ["Un plan estructurado permitirá evolución sólida."],
#                 "bajo": ["Requiere fase intensiva de desarrollo antes de avanzar."]
#             },
#             "Modelo Growth": {
#                 "alto": ["Está listo para escalar monetización y expansión."],
#                 "medio": ["Optimizar variables permitirá activar crecimiento sostenido."],
#                 "bajo": ["Debe estabilizar base antes de buscar expansión."]
#             },
#             "Modelo Balanceado": {
#                 "alto": ["Consolidar fortalezas garantizará estabilidad sostenible."],
#                 "medio": ["Nivelar variables permitirá mayor consistencia estratégica."],
#                 "bajo": ["Es fundamental reforzar estructura para equilibrio integral."]
#             }
#         }
#
#     def unir(self, textos: List[str], conectores: List[str]) -> str:
#         if not textos:
#             return ""
#         if len(textos) == 1:
#             return textos[0]
#         resultado = textos[0]
#         for t in textos[1:]:
#             resultado += random.choice(conectores) + t
#         return resultado
#
#     def tono(self, score: float) -> str:
#         if score >= 4.2:
#             return "alto"
#         elif score >= 3.3:
#             return "medio"
#         return "bajo"
#
#     def ensamblar(self, modelo: str, agrupado: Dict, score_total: float) -> str:
#         partes = []
#         inicio = random.choice(self.inicios)
#
#         if agrupado.get("fortalezas"):
#             textos = [c["mensaje"].lower() for c in agrupado["fortalezas"]]
#             partes.append(self.unir(textos, self.conectores_adicion))
#
#         if agrupado.get("desarrollo"):
#             textos = [c["mensaje"].lower() for c in agrupado["desarrollo"]]
#             bloque = self.unir(textos, self.conectores_adicion)
#             partes.append(random.choice(self.conectores_transicion) + bloque)
#
#         if agrupado.get("riesgos"):
#             textos = [c["mensaje"].lower() for c in agrupado["riesgos"]]
#             bloque = self.unir(textos, self.conectores_adicion)
#             partes.append(random.choice(self.conectores_adversidad) + bloque)
#
#         texto = inicio + "".join(partes)
#
#         cierre = random.choice(
#             self.cierres_modelo
#             .get(modelo, {"medio": ["Es necesario fortalecer estas áreas."]})
#             .get(self.tono(score_total), ["Es necesario fortalecer estas áreas."])
#         )
#
#         texto += " " + cierre
#         return texto[0].upper() + texto[1:]
#
#
# # =====================================================
# # Utilidades de scoring / niveles
# # =====================================================
# def convertir_score_a_nivel_5(score: float) -> int:
#     """Convierte score (0..5) a nivel 1..5."""
#     if score >= 4.2:
#         return 5
#     elif score >= 3.8:
#         return 4
#     elif score >= 3.2:
#         return 3
#     elif score >= 2.5:
#         return 2
#     return 1
#
#
# def nivel_5_a_3(nivel_5: int) -> int:
#     """Reduce 1..5 a 1..3 para resumen ejecutivo."""
#     if nivel_5 <= 2:
#         return 1
#     if nivel_5 == 3:
#         return 2
#     return 3
#
#
# def grupo_tarjeta(nivel_5: int) -> Dict[str, Any]:
#     """
#     Para front:
#       Fortalezas = 1
#       Desarrollo = 2
#       Riesgos     = 3
#     """
#     if nivel_5 >= 4:
#         return {"grupo_id": 1, "grupo_nombre": "Fortalezas"}
#     if nivel_5 == 3:
#         return {"grupo_id": 2, "grupo_nombre": "Desarrollo"}
#     return {"grupo_id": 3, "grupo_nombre": "Riesgos"}
#
#
# def agrupar_por_nivel_5(categorias_motor: list) -> dict:
#     fortalezas, desarrollo, riesgos = [], [], []
#     for c in categorias_motor:
#         if c["nivel_5"] >= 4:
#             fortalezas.append(c)
#         elif c["nivel_5"] == 3:
#             desarrollo.append(c)
#         else:
#             riesgos.append(c)
#     return {"fortalezas": fortalezas, "desarrollo": desarrollo, "riesgos": riesgos}
#
#
# # =====================================================
# # DB helpers
# # =====================================================
# def obtener_modelo_activo(cur) -> Dict[str, Any]:
#     cur.execute("""
#         SELECT id, nombre
#         FROM modelo_evaluacion
#         WHERE activo = true
#         LIMIT 1
#     """)
#     row = cur.fetchone()
#     if not row:
#         raise HTTPException(status_code=400, detail="No hay modelo activo")
#     return {"modelo_id": row[0], "modelo_nombre": row[1]}
#
#
# def obtener_perfil_creador(cur, creador_id: int) -> Dict[str, Any]:
#     # Ajusta columnas a tu tabla real:
#     cur.execute("""
#         SELECT nombre, edad, genero, pais, ciudad
#         FROM perfil_creador
#         WHERE creador_id = %s
#         LIMIT 1
#     """, (creador_id,))
#     row = cur.fetchone()
#     if not row:
#         raise HTTPException(status_code=404, detail="Creador no encontrado en perfil_creador")
#
#     return {
#         "nombre": row[0],
#         "edad": row[1],
#         "genero": row[2],
#         "pais": row[3],
#         "ciudad": row[4],
#     }
#
#
# def obtener_categorias_modelo(cur, modelo_id: int) -> List[Dict[str, Any]]:
#     cur.execute("""
#         SELECT id, nombre, peso_categoria
#         FROM modelo_categoria
#         WHERE modelo_id = %s
#         ORDER BY id ASC
#     """, (modelo_id,))
#     rows = cur.fetchall()
#     if not rows:
#         raise HTTPException(status_code=400, detail="El modelo activo no tiene categorías configuradas")
#
#     return [{"categoria_id": r[0], "categoria_nombre": r[1], "peso_categoria": float(r[2])} for r in rows]
#
#
# def obtener_variables_de_categoria(cur, categoria_id: int) -> List[Dict[str, Any]]:
#     cur.execute("""
#         SELECT id, peso_variable
#         FROM modelo_variable
#         WHERE categoria_id = %s
#     """, (categoria_id,))
#     rows = cur.fetchall()
#     return [{"variable_id": r[0], "peso_variable": float(r[1])} for r in rows]
#
#
# def obtener_score_variable(cur, creador_id: int, variable_id: int) -> int:
#     cur.execute("""
#         SELECT score
#         FROM talento_score_variable
#         WHERE creador_id = %s
#           AND variable_id = %s
#         LIMIT 1
#     """, (creador_id, variable_id))
#     row = cur.fetchone()
#     return int(row[0]) if row else 0
#
#
# def obtener_script(cur, modelo_id: int, categoria_id: int, escala: int, nivel: int) -> str:
#     cur.execute("""
#         SELECT script
#         FROM talento_script_categoria
#         WHERE modelo_id = %s
#           AND categoria_id = %s
#           AND escala = %s
#           AND nivel = %s
#         LIMIT 1
#     """, (modelo_id, categoria_id, escala, nivel))
#     row = cur.fetchone()
#     return row[0] if row else "Sin definición estratégica."
#
#
# def sobrescribir_score_categoria(cur, creador_id: int, modelo_id: int, filas: List[Dict[str, Any]]) -> None:
#     # sobrescribir = borrar y reinsertar
#     cur.execute("""
#         DELETE FROM talento_score_categoria
#         WHERE creador_id = %s AND modelo_id = %s
#     """, (creador_id, modelo_id))
#
#     for f in filas:
#         cur.execute("""
#             INSERT INTO talento_score_categoria (modelo_id, creador_id, categoria_id, score_categoria, nivel)
#             VALUES (%s, %s, %s, %s, %s)
#         """, (modelo_id, creador_id, f["categoria_id"], f["score_categoria"], f["nivel_5"]))
#
#
# def sobrescribir_score_general(cur, creador_id: int, modelo_id: int, puntaje_total: float,
#                               nivel_5: int, diagnostico_json: dict, diagnostico_resumen: str) -> None:
#     cur.execute("""
#         DELETE FROM talento_score_general
#         WHERE creador_id = %s AND modelo_id = %s
#     """, (creador_id, modelo_id))
#
#     cur.execute("""
#         INSERT INTO talento_score_general (creador_id, modelo_id, puntaje_total, nivel, diagnostico_json, diagnostico_resumen)
#         VALUES (%s, %s, %s, %s, %s::jsonb, %s)
#     """, (
#         creador_id,
#         modelo_id,
#         puntaje_total,
#         nivel_5,
#         json.dumps(diagnostico_json, ensure_ascii=False),
#         diagnostico_resumen[:200]
#     ))
#
#
# def actualizar_diagnostico_perfil(cur, creador_id: int, texto: str) -> None:
#     cur.execute("""
#         UPDATE perfil_creador
#         SET diagnostico = %s
#         WHERE creador_id = %s
#     """, (texto, creador_id))
#
#
# # =====================================================
# # Cálculo principal
# # =====================================================
# def calcular_diagnostico(conn, creador_id: int) -> Dict[str, Any]:
#     cur = conn.cursor()
#
#     # 1) Modelo activo
#     modelo = obtener_modelo_activo(cur)
#     modelo_id = modelo["modelo_id"]
#     modelo_nombre = modelo["modelo_nombre"]
#
#     # 2) Perfil demográfico
#     perfil = obtener_perfil_creador(cur, creador_id)
#
#     # 3) Categorías + pesos
#     categorias = obtener_categorias_modelo(cur, modelo_id)
#
#     resultado_categorias: List[Dict[str, Any]] = []
#     score_total = 0.0
#
#     # 4) Calcular score por categoría (ponderado por variable) y score total (ponderado por categoría)
#     for c in categorias:
#         cat_id = c["categoria_id"]
#         cat_nombre = c["categoria_nombre"]
#         peso_cat = c["peso_categoria"]
#
#         variables = obtener_variables_de_categoria(cur, cat_id)
#         if not variables:
#             score_categoria = 0.0
#         else:
#             # score_categoria: suma(score_var * peso_variable/100)
#             score_categoria = 0.0
#             for v in variables:
#                 var_id = v["variable_id"]
#                 peso_var = v["peso_variable"]
#                 score_var = obtener_score_variable(cur, creador_id, var_id)
#                 score_categoria += (score_var * (peso_var / 100.0))
#
#         score_categoria = round(score_categoria, 2)
#         nivel_5 = convertir_score_a_nivel_5(score_categoria)
#         nivel_3 = nivel_5_a_3(nivel_5)
#
#         # script correspondiente 1-5 (lo que pediste)
#         script_5 = obtener_script(cur, modelo_id, cat_id, escala=5, nivel=nivel_5)
#
#         # para el motor ejecutivo, usamos script 1-3
#         script_3 = obtener_script(cur, modelo_id, cat_id, escala=3, nivel=nivel_3)
#
#         grupo = grupo_tarjeta(nivel_5)
#
#         resultado_categorias.append({
#             "categoria_id": cat_id,
#             "categoria_nombre": cat_nombre,
#             "peso_categoria": peso_cat,
#             "score_5": score_categoria,     # 0..5 con decimales
#             "nivel_5": nivel_5,             # 1..5 (para colorear/segmentar)
#             "nivel_3": nivel_3,             # 1..3 (para resumen)
#             "grupo_id": grupo["grupo_id"],  # 1 fortalezas, 2 desarrollo, 3 riesgos
#             "grupo_nombre": grupo["grupo_nombre"],
#             "script_5": script_5,           # requerido
#             "script_3": script_3,           # útil para motor / opcional en front
#             "porcentaje": round((score_categoria / 5.0) * 100.0, 2),
#         })
#
#         score_total += (score_categoria * (peso_cat / 100.0))
#
#     score_total = round(score_total, 2)
#     nivel_total_5 = convertir_score_a_nivel_5(score_total)
#     nivel_total_3 = nivel_5_a_3(nivel_total_5)
#
#     # 5) Texto ejecutivo (con tu motor)
#     motor = MotorEnsamblajeV4()
#
#     categorias_motor = [
#         {
#             "categoria_id": c["categoria_id"],
#             "nivel_5": c["nivel_5"],
#             "mensaje": c["script_3"],  # resumen ejecutivo por categoría
#         }
#         for c in resultado_categorias
#     ]
#
#     agrupado = agrupar_por_nivel_5(categorias_motor)
#     texto_ejecutivo = motor.ensamblar(modelo_nombre, agrupado, score_total)
#     resumen_corto = texto_ejecutivo[:200]
#
#     # 6) Guardado (sobrescribir)
#     sobrescribir_score_categoria(cur, creador_id, modelo_id, [
#         {"categoria_id": c["categoria_id"], "score_categoria": c["score_5"], "nivel_5": c["nivel_5"]}
#         for c in resultado_categorias
#     ])
#
#     diagnostico_json = {
#         "creador_id": creador_id,
#         "modelo": {"id": modelo_id, "nombre": modelo_nombre},
#         "score_total": score_total,
#         "nivel_total_5": nivel_total_5,
#         "nivel_total_3": nivel_total_3,
#         "texto_ejecutivo": texto_ejecutivo,
#         "categorias": [
#             {
#                 "categoria_id": c["categoria_id"],
#                 "nombre": c["categoria_nombre"],
#                 "peso_categoria": c["peso_categoria"],
#                 "score_5": c["score_5"],
#                 "nivel_5": c["nivel_5"],
#                 "nivel_3": c["nivel_3"],
#                 "grupo_id": c["grupo_id"],
#                 "grupo_nombre": c["grupo_nombre"],
#                 "script_5": c["script_5"],
#             }
#             for c in resultado_categorias
#         ],
#         "version_motor": "v4"
#     }
#
#     sobrescribir_score_general(
#         cur,
#         creador_id=creador_id,
#         modelo_id=modelo_id,
#         puntaje_total=score_total,
#         nivel_5=nivel_total_5,
#         diagnostico_json=diagnostico_json,
#         diagnostico_resumen=resumen_corto
#     )
#
#     actualizar_diagnostico_perfil(cur, creador_id, texto_ejecutivo)
#
#     return {
#         "modelo": {"id": modelo_id, "nombre": modelo_nombre},
#         "perfil": perfil,
#         "score_total": score_total,
#         "nivel_total_5": nivel_total_5,
#         "nivel_total_3": nivel_total_3,
#         "texto_ejecutivo": texto_ejecutivo,
#         "categorias": resultado_categorias,
#     }
#
#
# # =====================================================
# # ENDPOINT
# # =====================================================
# @router.get("/api/creadores/{creador_id}/diagnostico")
# def diagnostico_creador(creador_id: int):
#     TENANT = current_tenant.get() if "current_tenant" in globals() else None
#     if TENANT is None:
#         # si en tu proyecto tenant no es obligatorio, puedes quitar esto
#         raise HTTPException(status_code=400, detail="Tenant no disponible")
#
#     with get_connection_context() as conn:
#         data = calcular_diagnostico(conn, creador_id)
#         conn.commit()
#
#     # Datos de agencia opcionales (si los manejas)
#     nombre_agencia = current_business_name.get() if "current_business_name" in globals() else None
#
#     return {
#         "agencia": {"nombre": nombre_agencia},
#         **data
#     }