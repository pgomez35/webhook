from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from decimal import Decimal
import logging

from DataBase import get_connection_context
from main_auth import obtener_usuario_actual

logger = logging.getLogger("uvicorn.error")

router = APIRouter()

MODELO_PERSONALIZADO_NOMBRE = "Modelo Personalizado"


# =========================================================
# HELPERS DE CONVERSIÓN DE FILAS
# =========================================================

def fetchone_as_dict(cur) -> Optional[Dict[str, Any]]:
    row = cur.fetchone()
    if row is None:
        return None

    columns = [desc[0] for desc in cur.description]
    return dict(zip(columns, row))


def fetchall_as_dict(cur) -> List[Dict[str, Any]]:
    rows = cur.fetchall()
    if not rows:
        return []

    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row)) for row in rows]


# =========================================================
# SCHEMAS
# =========================================================

class ActivarModeloRequest(BaseModel):
    pass


class ModeloCategoriaPesoItem(BaseModel):
    categoria_id: int
    peso_categoria: Decimal = Field(..., ge=0, le=100)


class ModeloCategoriaPesosUpdate(BaseModel):
    categorias: List[ModeloCategoriaPesoItem]

    @field_validator("categorias")
    @classmethod
    def validar_lista_no_vacia(cls, value):
        if not value:
            raise ValueError("Debe enviar al menos una categoría")
        return value


# =========================================================
# HELPERS DE NEGOCIO
# =========================================================

def obtener_modelo(cur, modelo_id: int) -> Optional[Dict[str, Any]]:
    cur.execute("""
        SELECT
            id,
            nombre,
            descripcion,
            activo,
            created_at
        FROM diagnostico_modelo
        WHERE id = %s
    """, (modelo_id,))
    return fetchone_as_dict(cur)


def obtener_modelo_por_nombre(cur, nombre: str) -> Optional[Dict[str, Any]]:
    cur.execute("""
        SELECT
            id,
            nombre,
            descripcion,
            activo,
            created_at
        FROM diagnostico_modelo
        WHERE nombre = %s
    """, (nombre,))
    return fetchone_as_dict(cur)


def existe_modelo(cur, modelo_id: int) -> bool:
    cur.execute("""
        SELECT 1 AS existe
        FROM diagnostico_modelo
        WHERE id = %s
    """, (modelo_id,))
    return fetchone_as_dict(cur) is not None


def existe_categoria(cur, categoria_id: int) -> bool:
    cur.execute("""
        SELECT 1 AS existe
        FROM diagnostico_categoria
        WHERE id = %s
    """, (categoria_id,))
    return fetchone_as_dict(cur) is not None


def es_modelo_personalizado(modelo: Dict[str, Any]) -> bool:
    return (modelo or {}).get("nombre") == MODELO_PERSONALIZADO_NOMBRE


def obtener_ids_categoria_modelo(cur, modelo_id: int) -> List[int]:
    cur.execute("""
        SELECT categoria_id
        FROM diagnostico_modelo_categoria
        WHERE modelo_id = %s
        ORDER BY categoria_id
    """, (modelo_id,))
    rows = fetchall_as_dict(cur)
    return [row["categoria_id"] for row in rows]


def validar_suma_100(items: List[ModeloCategoriaPesoItem]):
    total = sum(Decimal(str(x.peso_categoria)) for x in items)
    if total != Decimal("100"):
        raise HTTPException(
            status_code=400,
            detail=f"La suma de pesos de categorías debe ser 100. Valor actual: {total}"
        )


def validar_categorias_duplicadas(items: List[ModeloCategoriaPesoItem]):
    ids = [x.categoria_id for x in items]
    if len(ids) != len(set(ids)):
        raise HTTPException(
            status_code=400,
            detail="No se puede repetir una categoría dentro del mismo modelo"
        )


def validar_todas_las_categorias_existen(cur, items: List[ModeloCategoriaPesoItem]):
    ids = [x.categoria_id for x in items]
    if not ids:
        raise HTTPException(status_code=400, detail="Debe enviar al menos una categoría")

    cur.execute("""
        SELECT id
        FROM diagnostico_categoria
        WHERE id = ANY(%s)
    """, (ids,))
    rows = fetchall_as_dict(cur)
    existentes = {row["id"] for row in rows}
    faltantes = [x for x in ids if x not in existentes]

    if faltantes:
        raise HTTPException(
            status_code=404,
            detail=f"Las siguientes categorías no existen: {faltantes}"
        )


def validar_modelo_tiene_categorias(cur, modelo_id: int):
    cur.execute("""
        SELECT COUNT(*) AS total
        FROM diagnostico_modelo_categoria
        WHERE modelo_id = %s
    """, (modelo_id,))
    row = fetchone_as_dict(cur)
    total = int(row["total"] or 0)

    if total == 0:
        raise HTTPException(
            status_code=400,
            detail="El modelo no tiene categorías configuradas"
        )


def total_pesos_modelo(cur, modelo_id: int) -> Decimal:
    cur.execute("""
        SELECT COALESCE(SUM(peso_categoria), 0) AS total
        FROM diagnostico_modelo_categoria
        WHERE modelo_id = %s
    """, (modelo_id,))
    row = fetchone_as_dict(cur)
    return Decimal(str(row["total"] or 0))


def validar_modelo_activable(cur, modelo_id: int):
    validar_modelo_tiene_categorias(cur, modelo_id)
    total = total_pesos_modelo(cur, modelo_id)

    if total != Decimal("100"):
        raise HTTPException(
            status_code=400,
            detail=f"No se puede activar el modelo porque la suma de pesos es {total} y debe ser 100"
        )


def validar_edicion_pesos_modelo_personalizado(
    cur,
    modelo_id: int,
    categorias_payload: List[ModeloCategoriaPesoItem]
):
    modelo = obtener_modelo(cur, modelo_id)
    if not modelo:
        raise HTTPException(status_code=404, detail="Modelo no encontrado")

    if not es_modelo_personalizado(modelo):
        raise HTTPException(
            status_code=400,
            detail="Solo el Modelo Personalizado permite modificar los pesos de sus categorías"
        )

    validar_categorias_duplicadas(categorias_payload)
    validar_todas_las_categorias_existen(cur, categorias_payload)
    validar_suma_100(categorias_payload)

    actuales = sorted(obtener_ids_categoria_modelo(cur, modelo_id))
    enviados = sorted([item.categoria_id for item in categorias_payload])

    if actuales != enviados:
        raise HTTPException(
            status_code=400,
            detail="Solo se permite modificar el peso de las categorías existentes del Modelo Personalizado"
        )


def obtener_detalle_modelo_con_categorias(cur, modelo_id: int) -> Dict[str, Any]:
    modelo = obtener_modelo(cur, modelo_id)
    if not modelo:
        raise HTTPException(status_code=404, detail="Modelo no encontrado")

    cur.execute("""
        SELECT
            mc.id,
            mc.modelo_id,
            mc.categoria_id,
            c.nombre AS categoria_nombre,
            c.nombre_natural AS categoria_nombre_natural,
            c.descripcion AS categoria_descripcion,
            c.activo AS categoria_activa,
            mc.peso_categoria,
            mc.orden,
            mc.created_at
        FROM diagnostico_modelo_categoria mc
        INNER JOIN diagnostico_categoria c
            ON c.id = mc.categoria_id
        WHERE mc.modelo_id = %s
        ORDER BY mc.orden NULLS LAST, mc.id
    """, (modelo_id,))
    categorias = fetchall_as_dict(cur)

    modelo["categorias"] = categorias
    modelo["peso_total_categorias"] = str(
        sum(Decimal(str(x["peso_categoria"])) for x in categorias)
    ) if categorias else "0"
    modelo["editable"] = es_modelo_personalizado(modelo)

    return modelo


# =========================================================
# MODELOS - LISTADO Y DETALLE
# =========================================================

@router.get("/api/diagnostico-config/modelos")
def listar_modelos(usuario=Depends(obtener_usuario_actual)):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    m.id,
                    m.nombre,
                    m.descripcion,
                    m.activo,
                    m.created_at,
                    COALESCE(SUM(mc.peso_categoria), 0) AS peso_total_categorias,
                    COUNT(mc.id) AS total_categorias
                FROM diagnostico_modelo m
                LEFT JOIN diagnostico_modelo_categoria mc
                    ON mc.modelo_id = m.id
                GROUP BY m.id, m.nombre, m.descripcion, m.activo, m.created_at
                ORDER BY
                    CASE WHEN m.activo = true THEN 0 ELSE 1 END,
                    m.id
            """)
            modelos = fetchall_as_dict(cur)

            for m in modelos:
                m["editable"] = (m["nombre"] == MODELO_PERSONALIZADO_NOMBRE)

            return {"ok": True, "data": modelos}


@router.get("/api/diagnostico-config/modelos/{modelo_id}")
def detalle_modelo(modelo_id: int, usuario=Depends(obtener_usuario_actual)):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            data = obtener_detalle_modelo_con_categorias(cur, modelo_id)
            return {"ok": True, "data": data}


# =========================================================
# MODELOS - ACTIVAR
# =========================================================

@router.patch("/api/diagnostico-config/modelos/{modelo_id}/activar")
def activar_modelo(
    modelo_id: int,
    payload: Optional[ActivarModeloRequest] = None,
    usuario=Depends(obtener_usuario_actual)
):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            modelo = obtener_modelo(cur, modelo_id)
            if not modelo:
                raise HTTPException(status_code=404, detail="Modelo no encontrado")

            validar_modelo_activable(cur, modelo_id)

            cur.execute("""
                UPDATE diagnostico_modelo
                SET activo = false
                WHERE activo = true
            """)

            cur.execute("""
                UPDATE diagnostico_modelo
                SET activo = true
                WHERE id = %s
                RETURNING id, nombre, descripcion, activo, created_at
            """, (modelo_id,))
            activado = fetchone_as_dict(cur)
            activado["editable"] = es_modelo_personalizado(activado)

            conn.commit()

            return {
                "ok": True,
                "message": "Modelo activado correctamente. Los demás modelos fueron desactivados.",
                "data": activado
            }


# =========================================================
# CATEGORÍAS - LISTADO Y DETALLE
# =========================================================

@router.get("/api/diagnostico-config/categorias")
def listar_categorias(usuario=Depends(obtener_usuario_actual)):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    c.id,
                    c.nombre,
                    c.descripcion,
                    c.activo,
                    c.created_at,
                    c.nombre_natural,
                    COUNT(DISTINCT v.id) AS total_variables,
                    COUNT(DISTINCT mc.id) AS total_modelos
                FROM diagnostico_categoria c
                LEFT JOIN diagnostico_variable v
                    ON v.categoria_id = c.id
                LEFT JOIN diagnostico_modelo_categoria mc
                    ON mc.categoria_id = c.id
                GROUP BY c.id, c.nombre, c.descripcion, c.activo, c.created_at, c.nombre_natural
                ORDER BY c.id
            """)
            categorias = fetchall_as_dict(cur)
            return {"ok": True, "data": categorias}


@router.get("/api/diagnostico-config/categorias/{categoria_id}")
def detalle_categoria(categoria_id: int, usuario=Depends(obtener_usuario_actual)):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            if not existe_categoria(cur, categoria_id):
                raise HTTPException(status_code=404, detail="Categoría no encontrada")

            cur.execute("""
                SELECT
                    c.id,
                    c.nombre,
                    c.descripcion,
                    c.activo,
                    c.created_at,
                    c.nombre_natural
                FROM diagnostico_categoria c
                WHERE c.id = %s
            """, (categoria_id,))
            categoria = fetchone_as_dict(cur)

            cur.execute("""
                SELECT
                    mc.id,
                    mc.modelo_id,
                    m.nombre AS modelo_nombre,
                    m.activo AS modelo_activo,
                    mc.categoria_id,
                    mc.peso_categoria,
                    mc.orden
                FROM diagnostico_modelo_categoria mc
                INNER JOIN diagnostico_modelo m
                    ON m.id = mc.modelo_id
                WHERE mc.categoria_id = %s
                ORDER BY mc.modelo_id, mc.orden NULLS LAST
            """, (categoria_id,))
            categoria["modelos"] = fetchall_as_dict(cur)

            return {"ok": True, "data": categoria}


# =========================================================
# MODELO - CATEGORÍAS
# =========================================================

@router.get("/api/diagnostico-config/modelos/{modelo_id}/categorias")
def listar_categorias_por_modelo(modelo_id: int, usuario=Depends(obtener_usuario_actual)):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            data = obtener_detalle_modelo_con_categorias(cur, modelo_id)
            return {
                "ok": True,
                "data": {
                    "modelo": {
                        "id": data["id"],
                        "nombre": data["nombre"],
                        "descripcion": data["descripcion"],
                        "activo": data["activo"],
                        "created_at": data["created_at"],
                        "editable": data["editable"]
                    },
                    "categorias": data["categorias"],
                    "peso_total": data["peso_total_categorias"]
                }
            }


@router.put("/api/diagnostico-config/modelos/{modelo_id}/categorias/pesos")
def actualizar_pesos_categorias_modelo_personalizado(
    modelo_id: int,
    payload: ModeloCategoriaPesosUpdate,
    usuario=Depends(obtener_usuario_actual)
):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            validar_edicion_pesos_modelo_personalizado(cur, modelo_id, payload.categorias)

            for item in payload.categorias:
                cur.execute("""
                    UPDATE diagnostico_modelo_categoria
                    SET peso_categoria = %s
                    WHERE modelo_id = %s
                      AND categoria_id = %s
                """, (
                    item.peso_categoria,
                    modelo_id,
                    item.categoria_id
                ))

            data = obtener_detalle_modelo_con_categorias(cur, modelo_id)
            conn.commit()

            return {
                "ok": True,
                "message": "Pesos de categorías del Modelo Personalizado actualizados correctamente",
                "data": {
                    "modelo": {
                        "id": data["id"],
                        "nombre": data["nombre"],
                        "descripcion": data["descripcion"],
                        "activo": data["activo"],
                        "created_at": data["created_at"],
                        "editable": data["editable"]
                    },
                    "categorias": data["categorias"],
                    "peso_total": data["peso_total_categorias"]
                }
            }


@router.get("/api/diagnostico-config/modelos/{modelo_id}/categorias/validacion-pesos")
def validar_pesos_modelo(modelo_id: int, usuario=Depends(obtener_usuario_actual)):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            modelo = obtener_modelo(cur, modelo_id)
            if not modelo:
                raise HTTPException(status_code=404, detail="Modelo no encontrado")

            total = total_pesos_modelo(cur, modelo_id)

            return {
                "ok": True,
                "data": {
                    "modelo_id": modelo_id,
                    "modelo_nombre": modelo["nombre"],
                    "editable": es_modelo_personalizado(modelo),
                    "peso_total": str(total),
                    "valido": total == Decimal("100"),
                    "message": "OK" if total == Decimal("100") else f"La suma actual es {total} y debe ser 100"
                }
            }


# =========================================================
# RESUMEN GENERAL PARA PANTALLA
# =========================================================

@router.get("/api/diagnostico-config/resumen")
def resumen_configuracion(usuario=Depends(obtener_usuario_actual)):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    m.id,
                    m.nombre,
                    m.descripcion,
                    m.activo,
                    m.created_at,
                    COALESCE(SUM(mc.peso_categoria), 0) AS peso_total_categorias,
                    COUNT(mc.id) AS total_categorias
                FROM diagnostico_modelo m
                LEFT JOIN diagnostico_modelo_categoria mc
                    ON mc.modelo_id = m.id
                GROUP BY m.id, m.nombre, m.descripcion, m.activo, m.created_at
                ORDER BY
                    CASE WHEN m.activo = true THEN 0 ELSE 1 END,
                    m.id
            """)
            modelos = fetchall_as_dict(cur)
            for m in modelos:
                m["editable"] = (m["nombre"] == MODELO_PERSONALIZADO_NOMBRE)

            cur.execute("""
                SELECT
                    c.id,
                    c.nombre,
                    c.descripcion,
                    c.activo,
                    c.created_at,
                    c.nombre_natural,
                    COUNT(DISTINCT v.id) AS total_variables,
                    COUNT(DISTINCT mc.id) AS total_modelos
                FROM diagnostico_categoria c
                LEFT JOIN diagnostico_variable v
                    ON v.categoria_id = c.id
                LEFT JOIN diagnostico_modelo_categoria mc
                    ON mc.categoria_id = c.id
                GROUP BY c.id, c.nombre, c.descripcion, c.activo, c.created_at, c.nombre_natural
                ORDER BY c.id
            """)
            categorias = fetchall_as_dict(cur)

            cur.execute("""
                SELECT
                    mc.id,
                    mc.modelo_id,
                    mc.categoria_id,
                    mc.peso_categoria,
                    mc.orden
                FROM diagnostico_modelo_categoria mc
                ORDER BY mc.modelo_id, mc.orden NULLS LAST, mc.id
            """)
            modelo_categorias = fetchall_as_dict(cur)

            return {
                "ok": True,
                "data": {
                    "modelos": modelos,
                    "categorias": categorias,
                    "modelo_categorias": modelo_categorias
                }
            }




# ------------------------------------------------
# ------------------------------------------------
# ----------PARTE 2-------------------------------
# ------------------------------------------------



# =========================================================
# PARTE 2: VARIABLES
# =========================================================

class VariableCreate(BaseModel):
    categoria_id: int = Field(..., ge=0)
    nombre: str = Field(..., min_length=1, max_length=100)
    campo_db: Optional[str] = Field(None, max_length=100)
    peso_variable: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    tipo: Optional[str] = Field(None, max_length=50)
    encuesta_id: Optional[int] = None
    activa: bool = True
    tipo_form: Optional[str] = Field(None, max_length=15)
    texto: Optional[str] = Field(None, max_length=300)
    orden: Optional[int] = None


class VariableUpdate(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=100)
    campo_db: Optional[str] = Field(None, max_length=100)
    peso_variable: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    tipo: Optional[str] = Field(None, max_length=50)
    encuesta_id: Optional[int] = None
    activa: bool = True
    tipo_form: Optional[str] = Field(None, max_length=15)
    texto: Optional[str] = Field(None, max_length=300)
    orden: Optional[int] = None


class VariablePesoUpdate(BaseModel):
    peso_variable: Decimal = Field(..., ge=0, le=100)


class VariableOrdenUpdate(BaseModel):
    orden: Optional[int] = None


class VariableCategoriaUpdate(BaseModel):
    categoria_id: int = Field(..., ge=0)


class VariableEstadoUpdate(BaseModel):
    activa: bool


class CategoriaVariablesPesosUpdateItem(BaseModel):
    variable_id: int
    peso_variable: Decimal = Field(..., ge=0, le=100)
    orden: Optional[int] = None


class CategoriaVariablesPesosUpdate(BaseModel):
    variables: List[CategoriaVariablesPesosUpdateItem]

    @field_validator("variables")
    @classmethod
    def validar_lista_no_vacia(cls, value):
        if not value:
            raise ValueError("Debe enviar al menos una variable")
        return value


# =========================================================
# HELPERS VARIABLES
# =========================================================

def obtener_variable(cur, variable_id: int) -> Optional[Dict[str, Any]]:
    cur.execute("""
        SELECT
            id,
            categoria_id,
            nombre,
            campo_db,
            peso_variable,
            tipo,
            created_at,
            encuesta_id,
            activa,
            tipo_form,
            texto,
            orden
        FROM diagnostico_variable
        WHERE id = %s
    """, (variable_id,))
    return fetchone_as_dict(cur)


def existe_variable(cur, variable_id: int) -> bool:
    cur.execute("""
        SELECT 1 AS existe
        FROM diagnostico_variable
        WHERE id = %s
    """, (variable_id,))
    return fetchone_as_dict(cur) is not None


def categoria_existe_o_es_cero(cur, categoria_id: int) -> bool:
    if categoria_id == 0:
        return True
    return existe_categoria(cur, categoria_id)


def validar_categoria_para_variable(cur, categoria_id: int):
    if categoria_id == 0:
        return
    if not existe_categoria(cur, categoria_id):
        raise HTTPException(status_code=404, detail="La categoría indicada no existe")


def validar_variable_nombre_no_vacio(nombre: str):
    if not nombre or not nombre.strip():
        raise HTTPException(status_code=400, detail="El nombre de la variable es obligatorio")


def validar_peso_variables_categoria_100(cur, categoria_id: int):
    """
    Solo valida variables activas, de la categoría, con peso > 0.
    Las variables auxiliares con peso 0 no participan.
    No aplica a categoria_id = 0.
    """
    if categoria_id == 0:
        return {
            "categoria_id": categoria_id,
            "total": Decimal("0"),
            "ok": True,
            "message": "La categoría 0 corresponde a variables de captura y no valida suma ponderada"
        }

    cur.execute("""
        SELECT COALESCE(SUM(peso_variable), 0) AS total
        FROM diagnostico_variable
        WHERE categoria_id = %s
          AND activa = true
          AND COALESCE(peso_variable, 0) > 0
    """, (categoria_id,))
    row = fetchone_as_dict(cur)
    total = Decimal(str(row["total"] or 0))

    return {
        "categoria_id": categoria_id,
        "total": total,
        "ok": total == Decimal("100"),
        "message": "La suma de variables ponderables debe ser 100" if total != Decimal("100") else "OK"
    }


def obtener_resumen_categoria_variables(cur, categoria_id: int) -> Dict[str, Any]:
    cur.execute("""
        SELECT
            id,
            categoria_id,
            nombre,
            campo_db,
            peso_variable,
            tipo,
            created_at,
            encuesta_id,
            activa,
            tipo_form,
            texto,
            orden
        FROM diagnostico_variable
        WHERE categoria_id = %s
        ORDER BY orden NULLS LAST, id
    """, (categoria_id,))
    variables = fetchall_as_dict(cur)

    validacion = validar_peso_variables_categoria_100(cur, categoria_id)

    return {
        "categoria_id": categoria_id,
        "variables": variables,
        "resumen_pesos": {
            "total_ponderables": str(validacion["total"]),
            "ok": validacion["ok"],
            "message": validacion["message"]
        }
    }


def variable_tiene_valores(cur, variable_id: int) -> bool:
    cur.execute("""
        SELECT 1 AS existe
        FROM diagnostico_variable_valor
        WHERE variable_id = %s
        LIMIT 1
    """, (variable_id,))
    return fetchone_as_dict(cur) is not None


def variable_tiene_uso_en_scores(cur, variable_id: int) -> bool:
    cur.execute("""
        SELECT 1 AS existe
        FROM diagnostico_score_variable
        WHERE variable_id = %s
        LIMIT 1
    """, (variable_id,))
    return fetchone_as_dict(cur) is not None


def validar_variables_pertenecen_a_categoria(cur, categoria_id: int, variable_ids: List[int]):
    cur.execute("""
        SELECT id
        FROM diagnostico_variable
        WHERE categoria_id = %s
          AND id = ANY(%s)
    """, (categoria_id, variable_ids))
    rows = fetchall_as_dict(cur)
    existentes = {row["id"] for row in rows}
    faltantes = [v for v in variable_ids if v not in existentes]

    if faltantes:
        raise HTTPException(
            status_code=400,
            detail=f"Estas variables no pertenecen a la categoría {categoria_id}: {faltantes}"
        )


def validar_variables_duplicadas(items: List[CategoriaVariablesPesosUpdateItem]):
    ids = [x.variable_id for x in items]
    if len(ids) != len(set(ids)):
        raise HTTPException(
            status_code=400,
            detail="No se pueden repetir variables en la misma actualización"
        )


def validar_suma_variables_100_payload(items: List[CategoriaVariablesPesosUpdateItem]):
    total = sum(
        Decimal(str(x.peso_variable))
        for x in items
        if Decimal(str(x.peso_variable)) > Decimal("0")
    )

    if total != Decimal("100"):
        raise HTTPException(
            status_code=400,
            detail=f"La suma de pesos ponderables de las variables debe ser 100. Valor actual: {total}"
        )


# =========================================================
# VARIABLES - LISTADOS
# =========================================================

@router.get("/api/diagnostico-config/variables")
def listar_variables(
    categoria_id: Optional[int] = None,
    activas: Optional[bool] = None,
    usuario=Depends(obtener_usuario_actual)
):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            query = """
                SELECT
                    v.id,
                    v.categoria_id,
                    c.nombre AS categoria_nombre,
                    v.nombre,
                    v.campo_db,
                    v.peso_variable,
                    v.tipo,
                    v.created_at,
                    v.encuesta_id,
                    v.activa,
                    v.tipo_form,
                    v.texto,
                    v.orden,
                    COUNT(DISTINCT vv.id) AS total_valores
                FROM diagnostico_variable v
                LEFT JOIN diagnostico_categoria c
                    ON c.id = v.categoria_id
                LEFT JOIN diagnostico_variable_valor vv
                    ON vv.variable_id = v.id
                WHERE 1 = 1
            """
            params = []

            if categoria_id is not None:
                query += " AND v.categoria_id = %s"
                params.append(categoria_id)

            if activas is not None:
                query += " AND v.activa = %s"
                params.append(activas)

            query += """
                GROUP BY
                    v.id, v.categoria_id, c.nombre, v.nombre, v.campo_db,
                    v.peso_variable, v.tipo, v.created_at, v.encuesta_id,
                    v.activa, v.tipo_form, v.texto, v.orden
                ORDER BY v.categoria_id, v.orden NULLS LAST, v.id
            """

            cur.execute(query, tuple(params))
            data = fetchall_as_dict(cur)
            return {"ok": True, "data": data}


@router.get("/api/diagnostico-config/variables/{variable_id}")
def detalle_variable(variable_id: int, usuario=Depends(obtener_usuario_actual)):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            variable = obtener_variable(cur, variable_id)
            if not variable:
                raise HTTPException(status_code=404, detail="Variable no encontrada")

            cur.execute("""
                SELECT
                    id,
                    variable_id,
                    min_val,
                    max_val,
                    score,
                    label,
                    nivel,
                    orden,
                    created_at
                FROM diagnostico_variable_valor
                WHERE variable_id = %s
                ORDER BY orden NULLS LAST, id
            """, (variable_id,))
            valores = fetchall_as_dict(cur)

            variable["valores"] = valores
            variable["tiene_valores"] = len(valores) > 0
            variable["tiene_uso_scores"] = variable_tiene_uso_en_scores(cur, variable_id)

            return {"ok": True, "data": variable}


@router.get("/api/diagnostico-config/categorias/{categoria_id}/variables")
def listar_variables_por_categoria(categoria_id: int, usuario=Depends(obtener_usuario_actual)):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            if categoria_id != 0 and not existe_categoria(cur, categoria_id):
                raise HTTPException(status_code=404, detail="Categoría no encontrada")

            data = obtener_resumen_categoria_variables(cur, categoria_id)
            return {"ok": True, "data": data}


# =========================================================
# VARIABLES - CREAR / EDITAR
# =========================================================

@router.post("/api/diagnostico-config/variables")
def crear_variable(payload: VariableCreate, usuario=Depends(obtener_usuario_actual)):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            validar_variable_nombre_no_vacio(payload.nombre)
            validar_categoria_para_variable(cur, payload.categoria_id)

            cur.execute("""
                INSERT INTO diagnostico_variable (
                    categoria_id,
                    nombre,
                    campo_db,
                    peso_variable,
                    tipo,
                    encuesta_id,
                    activa,
                    tipo_form,
                    texto,
                    orden
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING
                    id,
                    categoria_id,
                    nombre,
                    campo_db,
                    peso_variable,
                    tipo,
                    created_at,
                    encuesta_id,
                    activa,
                    tipo_form,
                    texto,
                    orden
            """, (
                payload.categoria_id,
                payload.nombre.strip(),
                payload.campo_db.strip() if payload.campo_db else None,
                payload.peso_variable,
                payload.tipo.strip() if payload.tipo else None,
                payload.encuesta_id,
                payload.activa,
                payload.tipo_form.strip() if payload.tipo_form else None,
                payload.texto.strip() if payload.texto else None,
                payload.orden
            ))

            nueva = fetchone_as_dict(cur)
            conn.commit()

            return {"ok": True, "message": "Variable creada correctamente", "data": nueva}


@router.put("/api/diagnostico-config/variables/{variable_id}")
def editar_variable(variable_id: int, payload: VariableUpdate, usuario=Depends(obtener_usuario_actual)):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            variable = obtener_variable(cur, variable_id)
            if not variable:
                raise HTTPException(status_code=404, detail="Variable no encontrada")

            validar_variable_nombre_no_vacio(payload.nombre)

            cur.execute("""
                UPDATE diagnostico_variable
                SET nombre = %s,
                    campo_db = %s,
                    peso_variable = %s,
                    tipo = %s,
                    encuesta_id = %s,
                    activa = %s,
                    tipo_form = %s,
                    texto = %s,
                    orden = %s
                WHERE id = %s
                RETURNING
                    id,
                    categoria_id,
                    nombre,
                    campo_db,
                    peso_variable,
                    tipo,
                    created_at,
                    encuesta_id,
                    activa,
                    tipo_form,
                    texto,
                    orden
            """, (
                payload.nombre.strip(),
                payload.campo_db.strip() if payload.campo_db else None,
                payload.peso_variable,
                payload.tipo.strip() if payload.tipo else None,
                payload.encuesta_id,
                payload.activa,
                payload.tipo_form.strip() if payload.tipo_form else None,
                payload.texto.strip() if payload.texto else None,
                payload.orden,
                variable_id
            ))

            actualizada = fetchone_as_dict(cur)
            conn.commit()

            return {"ok": True, "message": "Variable actualizada correctamente", "data": actualizada}


# =========================================================
# VARIABLES - CAMBIO DE PESO
# =========================================================

@router.patch("/api/diagnostico-config/variables/{variable_id}/peso")
def cambiar_peso_variable(variable_id: int, payload: VariablePesoUpdate, usuario=Depends(obtener_usuario_actual)):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            variable = obtener_variable(cur, variable_id)
            if not variable:
                raise HTTPException(status_code=404, detail="Variable no encontrada")

            cur.execute("""
                UPDATE diagnostico_variable
                SET peso_variable = %s
                WHERE id = %s
                RETURNING
                    id,
                    categoria_id,
                    nombre,
                    campo_db,
                    peso_variable,
                    tipo,
                    created_at,
                    encuesta_id,
                    activa,
                    tipo_form,
                    texto,
                    orden
            """, (payload.peso_variable, variable_id))

            actualizada = fetchone_as_dict(cur)
            validacion = validar_peso_variables_categoria_100(cur, actualizada["categoria_id"])
            conn.commit()

            return {
                "ok": True,
                "message": "Peso de variable actualizado correctamente",
                "data": actualizada,
                "validacion_categoria": {
                    "total_ponderables": str(validacion["total"]),
                    "ok": validacion["ok"],
                    "message": validacion["message"]
                }
            }


# =========================================================
# VARIABLES - CAMBIO DE ORDEN
# =========================================================

@router.patch("/api/diagnostico-config/variables/{variable_id}/orden")
def cambiar_orden_variable(variable_id: int, payload: VariableOrdenUpdate, usuario=Depends(obtener_usuario_actual)):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            variable = obtener_variable(cur, variable_id)
            if not variable:
                raise HTTPException(status_code=404, detail="Variable no encontrada")

            cur.execute("""
                UPDATE diagnostico_variable
                SET orden = %s
                WHERE id = %s
                RETURNING
                    id,
                    categoria_id,
                    nombre,
                    campo_db,
                    peso_variable,
                    tipo,
                    created_at,
                    encuesta_id,
                    activa,
                    tipo_form,
                    texto,
                    orden
            """, (payload.orden, variable_id))

            actualizada = fetchone_as_dict(cur)
            conn.commit()

            return {
                "ok": True,
                "message": "Orden de variable actualizado correctamente",
                "data": actualizada
            }


# =========================================================
# VARIABLES - CAMBIO DE CATEGORÍA
# =========================================================

@router.patch("/api/diagnostico-config/variables/{variable_id}/categoria")
def cambiar_categoria_variable(variable_id: int, payload: VariableCategoriaUpdate, usuario=Depends(obtener_usuario_actual)):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            variable = obtener_variable(cur, variable_id)
            if not variable:
                raise HTTPException(status_code=404, detail="Variable no encontrada")

            validar_categoria_para_variable(cur, payload.categoria_id)

            categoria_anterior = variable["categoria_id"]

            cur.execute("""
                UPDATE diagnostico_variable
                SET categoria_id = %s
                WHERE id = %s
                RETURNING
                    id,
                    categoria_id,
                    nombre,
                    campo_db,
                    peso_variable,
                    tipo,
                    created_at,
                    encuesta_id,
                    activa,
                    tipo_form,
                    texto,
                    orden
            """, (payload.categoria_id, variable_id))

            actualizada = fetchone_as_dict(cur)

            validacion_anterior = validar_peso_variables_categoria_100(cur, categoria_anterior)
            validacion_nueva = validar_peso_variables_categoria_100(cur, payload.categoria_id)

            conn.commit()

            return {
                "ok": True,
                "message": "Categoría de variable actualizada correctamente",
                "data": actualizada,
                "validacion_categoria_origen": {
                    "categoria_id": categoria_anterior,
                    "total_ponderables": str(validacion_anterior["total"]),
                    "ok": validacion_anterior["ok"],
                    "message": validacion_anterior["message"]
                },
                "validacion_categoria_destino": {
                    "categoria_id": payload.categoria_id,
                    "total_ponderables": str(validacion_nueva["total"]),
                    "ok": validacion_nueva["ok"],
                    "message": validacion_nueva["message"]
                }
            }


# =========================================================
# VARIABLES - ACTIVAR / INACTIVAR
# =========================================================

@router.patch("/api/diagnostico-config/variables/{variable_id}/estado")
def cambiar_estado_variable(variable_id: int, payload: VariableEstadoUpdate, usuario=Depends(obtener_usuario_actual)):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            variable = obtener_variable(cur, variable_id)
            if not variable:
                raise HTTPException(status_code=404, detail="Variable no encontrada")

            cur.execute("""
                UPDATE diagnostico_variable
                SET activa = %s
                WHERE id = %s
                RETURNING
                    id,
                    categoria_id,
                    nombre,
                    campo_db,
                    peso_variable,
                    tipo,
                    created_at,
                    encuesta_id,
                    activa,
                    tipo_form,
                    texto,
                    orden
            """, (payload.activa, variable_id))

            actualizada = fetchone_as_dict(cur)
            validacion = validar_peso_variables_categoria_100(cur, actualizada["categoria_id"])
            conn.commit()

            return {
                "ok": True,
                "message": "Estado de variable actualizado correctamente",
                "data": actualizada,
                "validacion_categoria": {
                    "total_ponderables": str(validacion["total"]),
                    "ok": validacion["ok"],
                    "message": validacion["message"]
                }
            }


# =========================================================
# VARIABLES - ACTUALIZACIÓN MASIVA DE PESOS / ORDEN
# =========================================================

@router.put("/api/diagnostico-config/categorias/{categoria_id}/variables/pesos")
def actualizar_pesos_variables_categoria(
    categoria_id: int,
    payload: CategoriaVariablesPesosUpdate,
    usuario=Depends(obtener_usuario_actual)
):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            if categoria_id == 0:
                raise HTTPException(
                    status_code=400,
                    detail="No aplica actualización masiva ponderada para la categoría 0"
                )

            if not existe_categoria(cur, categoria_id):
                raise HTTPException(status_code=404, detail="Categoría no encontrada")

            validar_variables_duplicadas(payload.variables)

            variable_ids = [x.variable_id for x in payload.variables]
            validar_variables_pertenecen_a_categoria(cur, categoria_id, variable_ids)
            validar_suma_variables_100_payload(payload.variables)

            for item in payload.variables:
                cur.execute("""
                    UPDATE diagnostico_variable
                    SET peso_variable = %s,
                        orden = %s
                    WHERE id = %s
                """, (item.peso_variable, item.orden, item.variable_id))

            resumen = obtener_resumen_categoria_variables(cur, categoria_id)
            conn.commit()

            return {
                "ok": True,
                "message": "Pesos y orden de variables actualizados correctamente",
                "data": resumen
            }


# =========================================================
# VARIABLES - VALIDACIÓN DE PESOS POR CATEGORÍA
# =========================================================

@router.get("/api/diagnostico-config/categorias/{categoria_id}/variables/validacion-pesos")
def validar_pesos_categoria(categoria_id: int, usuario=Depends(obtener_usuario_actual)):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            if categoria_id != 0 and not existe_categoria(cur, categoria_id):
                raise HTTPException(status_code=404, detail="Categoría no encontrada")

            validacion = validar_peso_variables_categoria_100(cur, categoria_id)
            return {
                "ok": True,
                "data": {
                    "categoria_id": categoria_id,
                    "total_ponderables": str(validacion["total"]),
                    "ok": validacion["ok"],
                    "message": validacion["message"]
                }
            }


# =========================================================
# VARIABLES - RESUMEN PARA PANTALLA
# =========================================================

@router.get("/api/diagnostico-config/variables-resumen")
def resumen_variables(usuario=Depends(obtener_usuario_actual)):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    c.id,
                    c.nombre,
                    c.descripcion,
                    c.activo,
                    c.created_at,
                    c.nombre_natural
                FROM diagnostico_categoria c
                ORDER BY c.id
            """)
            categorias = fetchall_as_dict(cur)

            resumen = []

            resumen.append(obtener_resumen_categoria_variables(cur, 0))

            for c in categorias:
                resumen.append(obtener_resumen_categoria_variables(cur, c["id"]))

            return {
                "ok": True,
                "data": resumen
            }