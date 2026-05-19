"""
CRUD de maestros del perfil de creador: categorías, variables y valores (opciones).
Requiere JWT de administrador (mismo patrón que main_diagnostico_config).
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from DataBase import get_connection_context
from main_auth import obtener_usuario_actual

logger = logging.getLogger("uvicorn.error")

router = APIRouter()

_TABLAS_ID = frozenset({"creadores_perfil_categoria", "creadores_perfil_variable"})

_CATEGORIA_UPDATABLE = frozenset(
    {
        "nombre",
        "nombre_natural",
        "descripcion",
        "orden",
        "activa",
        "tipo",
    }
)
_VARIABLE_UPDATABLE = frozenset(
    {
        "categoria_id",
        "nombre",
        "campo_db",
        "peso_variable",
        "tipo",
        "encuesta_id",
        "activa",
        "tipo_form",
        "texto",
        "orden",
        "migrado",
        "nombre_natural",
    }
)
_VALOR_UPDATABLE = frozenset(
    {
        "variable_id",
        "min_val",
        "max_val",
        "score",
        "label",
        "nivel",
        "orden",
        "valor_padre_id",
    }
)


def fetchone_dict(cur) -> Optional[Dict[str, Any]]:
    row = cur.fetchone()
    if row is None:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def fetchall_dict(cur) -> List[Dict[str, Any]]:
    rows = cur.fetchall()
    if not rows:
        return []
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def _next_id(cur, tabla: str) -> int:
    if tabla not in _TABLAS_ID:
        raise ValueError("tabla no permitida")
    cur.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {tabla}")
    return cur.fetchone()[0]


def _build_update(
    payload: BaseModel, allowed: frozenset
) -> tuple[List[str], List[Any]]:
    data = payload.model_dump(exclude_unset=True)
    sets: List[str] = []
    vals: List[Any] = []
    for key, val in data.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = %s")
        vals.append(val)
    return sets, vals


# --- Pydantic ---


class CategoriaCreate(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=100)
    nombre_natural: Optional[str] = Field(None, max_length=100)
    descripcion: Optional[str] = Field(None, max_length=300)
    orden: Optional[int] = None
    activa: bool = True
    tipo: str = Field(default="DIAGNOSTICO", max_length=30)


class CategoriaUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=1, max_length=100)
    nombre_natural: Optional[str] = Field(None, max_length=100)
    descripcion: Optional[str] = Field(None, max_length=300)
    orden: Optional[int] = None
    activa: Optional[bool] = None
    tipo: Optional[str] = Field(None, max_length=30)


class VariableCreate(BaseModel):
    categoria_id: Optional[int] = None
    nombre: Optional[str] = Field(None, max_length=100)
    campo_db: Optional[str] = Field(None, max_length=100)
    peso_variable: Decimal = Field(default=Decimal("0"))
    tipo: Optional[str] = Field(None, max_length=50)
    encuesta_id: Optional[int] = None
    activa: bool = True
    tipo_form: Optional[str] = Field(None, max_length=15)
    texto: Optional[str] = Field(None, max_length=300)
    orden: Optional[int] = None
    migrado: bool = False
    nombre_natural: Optional[str] = Field(None, max_length=150)


class VariableUpdate(BaseModel):
    categoria_id: Optional[int] = None
    nombre: Optional[str] = Field(None, max_length=100)
    campo_db: Optional[str] = Field(None, max_length=100)
    peso_variable: Optional[Decimal] = None
    tipo: Optional[str] = Field(None, max_length=50)
    encuesta_id: Optional[int] = None
    activa: Optional[bool] = None
    tipo_form: Optional[str] = Field(None, max_length=15)
    texto: Optional[str] = Field(None, max_length=300)
    orden: Optional[int] = None
    migrado: Optional[bool] = None
    nombre_natural: Optional[str] = Field(None, max_length=150)


class ValorCreate(BaseModel):
    min_val: Optional[Decimal] = None
    max_val: Optional[Decimal] = None
    score: int = 0
    label: str = Field(..., min_length=1, max_length=80)
    nivel: Optional[str] = Field(None, max_length=20)
    orden: Optional[int] = None
    valor_padre_id: Optional[int] = None


class ValorUpdate(BaseModel):
    min_val: Optional[Decimal] = None
    max_val: Optional[Decimal] = None
    score: Optional[int] = None
    label: Optional[str] = Field(None, min_length=1, max_length=80)
    nivel: Optional[str] = Field(None, max_length=20)
    orden: Optional[int] = None
    valor_padre_id: Optional[int] = None


class ReorderItem(BaseModel):
    id: int
    orden: int


class ReordenarCategoriasBody(BaseModel):
    items: List[ReorderItem]


class ReordenarVariablesBody(BaseModel):
    items: List[ReorderItem]


class ReordenarValoresBody(BaseModel):
    items: List[ReorderItem]


# ---------- Categorías ----------


@router.get("/api/creadores/perfil-config/categorias")
def listar_categorias(
    solo_activas: bool = Query(False),
    tipo: Optional[str] = Query(None, max_length=30),
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                where = ["1=1"]
                params: List[Any] = []
                if solo_activas:
                    where.append("COALESCE(activa, true) = true")
                if tipo:
                    where.append("UPPER(tipo) = UPPER(%s)")
                    params.append(tipo)
                w = " AND ".join(where)
                cur.execute(
                    f"""
                    SELECT
                        id, nombre, nombre_natural, descripcion, orden, activa, tipo, created_at
                    FROM creadores_perfil_categoria
                    WHERE {w}
                    ORDER BY orden NULLS LAST, id ASC
                    """,
                    params,
                )
                return {"ok": True, "categorias": fetchall_dict(cur)}
    except Exception as e:
        logger.exception("perfil-config listar categorias: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/creadores/perfil-config/categorias/{categoria_id}")
def detalle_categoria(
    categoria_id: int,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        id, nombre, nombre_natural, descripcion, orden, activa, tipo, created_at
                    FROM creadores_perfil_categoria
                    WHERE id = %s
                    """,
                    (categoria_id,),
                )
                row = fetchone_dict(cur)
                if not row:
                    raise HTTPException(status_code=404, detail="Categoría no encontrada")
                return {"ok": True, "categoria": row}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("perfil-config detalle categoria: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/creadores/perfil-config/categorias")
def crear_categoria(
    payload: CategoriaCreate,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                nuevo_id = _next_id(cur, "creadores_perfil_categoria")
                cur.execute(
                    """
                    INSERT INTO creadores_perfil_categoria (
                        id, nombre, nombre_natural, descripcion, orden, activa, tipo
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        nuevo_id,
                        payload.nombre,
                        payload.nombre_natural,
                        payload.descripcion,
                        payload.orden,
                        payload.activa,
                        payload.tipo,
                    ),
                )
                conn.commit()
                cur.execute(
                    """
                    SELECT
                        id, nombre, nombre_natural, descripcion, orden, activa, tipo, created_at
                    FROM creadores_perfil_categoria
                    WHERE id = %s
                    """,
                    (nuevo_id,),
                )
                return {"ok": True, "categoria": fetchone_dict(cur)}
    except Exception as e:
        logger.exception("perfil-config crear categoria: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/creadores/perfil-config/categorias/{categoria_id}")
def actualizar_categoria(
    categoria_id: int,
    payload: CategoriaUpdate,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        sets, vals = _build_update(payload, _CATEGORIA_UPDATABLE)
        if not sets:
            with get_connection_context() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            id, nombre, nombre_natural, descripcion, orden, activa, tipo, created_at
                        FROM creadores_perfil_categoria
                        WHERE id = %s
                        """,
                        (categoria_id,),
                    )
                    row = fetchone_dict(cur)
                    if not row:
                        raise HTTPException(status_code=404, detail="Categoría no encontrada")
                    return {"ok": True, "categoria": row}

        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM creadores_perfil_categoria WHERE id = %s",
                    (categoria_id,),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Categoría no encontrada")
                sql = f"UPDATE creadores_perfil_categoria SET {', '.join(sets)} WHERE id = %s"
                cur.execute(sql, vals + [categoria_id])
                conn.commit()
                cur.execute(
                    """
                    SELECT
                        id, nombre, nombre_natural, descripcion, orden, activa, tipo, created_at
                    FROM creadores_perfil_categoria
                    WHERE id = %s
                    """,
                    (categoria_id,),
                )
                return {"ok": True, "categoria": fetchone_dict(cur)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("perfil-config actualizar categoria: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/creadores/perfil-config/categorias/{categoria_id}")
def eliminar_categoria(
    categoria_id: int,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM creadores_perfil_variable
                    WHERE categoria_id = %s
                    """,
                    (categoria_id,),
                )
                n = cur.fetchone()[0]
                if n > 0:
                    raise HTTPException(
                        status_code=409,
                        detail=f"No se puede eliminar: hay {n} variable(s) en esta categoría.",
                    )
                cur.execute(
                    "DELETE FROM creadores_perfil_categoria WHERE id = %s RETURNING id",
                    (categoria_id,),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Categoría no encontrada")
                conn.commit()
                return {"ok": True, "eliminado_id": categoria_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("perfil-config eliminar categoria: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/api/creadores/perfil-config/categorias/reordenar")
def reordenar_categorias(
    body: ReordenarCategoriasBody,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    if not body.items:
        raise HTTPException(status_code=400, detail="items vacío")
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                for it in body.items:
                    cur.execute(
                        """
                        UPDATE creadores_perfil_categoria
                        SET orden = %s
                        WHERE id = %s
                        """,
                        (it.orden, it.id),
                    )
                    if cur.rowcount == 0:
                        raise HTTPException(
                            status_code=404,
                            detail=f"Categoría id={it.id} no encontrada",
                        )
                conn.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("perfil-config reordenar categorias: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Variables ----------


@router.get("/api/creadores/perfil-config/variables")
def listar_variables(
    categoria_id: Optional[int] = Query(None),
    encuesta_id: Optional[int] = Query(None),
    solo_activas: bool = Query(False),
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                where = ["1=1"]
                params: List[Any] = []
                if categoria_id is not None:
                    where.append("categoria_id = %s")
                    params.append(categoria_id)
                if encuesta_id is not None:
                    where.append("encuesta_id = %s")
                    params.append(encuesta_id)
                if solo_activas:
                    where.append("COALESCE(activa, true) = true")
                w = " AND ".join(where)
                cur.execute(
                    f"""
                    SELECT
                        id, categoria_id, nombre, campo_db, peso_variable, tipo,
                        created_at, encuesta_id, activa, tipo_form, texto, orden, migrado, nombre_natural
                    FROM creadores_perfil_variable
                    WHERE {w}
                    ORDER BY categoria_id NULLS LAST, orden NULLS LAST, id ASC
                    """,
                    params,
                )
                return {"ok": True, "variables": fetchall_dict(cur)}
    except Exception as e:
        logger.exception("perfil-config listar variables: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/creadores/perfil-config/variables/{variable_id}")
def detalle_variable(
    variable_id: int,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        id, categoria_id, nombre, campo_db, peso_variable, tipo,
                        created_at, encuesta_id, activa, tipo_form, texto, orden, migrado, nombre_natural
                    FROM creadores_perfil_variable
                    WHERE id = %s
                    """,
                    (variable_id,),
                )
                row = fetchone_dict(cur)
                if not row:
                    raise HTTPException(status_code=404, detail="Variable no encontrada")
                return {"ok": True, "variable": row}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("perfil-config detalle variable: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/creadores/perfil-config/variables")
def crear_variable(
    payload: VariableCreate,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                if payload.categoria_id is not None:
                    cur.execute(
                        "SELECT 1 FROM creadores_perfil_categoria WHERE id = %s",
                        (payload.categoria_id,),
                    )
                    if not cur.fetchone():
                        raise HTTPException(status_code=400, detail="categoria_id no existe")

                nuevo_id = _next_id(cur, "creadores_perfil_variable")
                cur.execute(
                    """
                    INSERT INTO creadores_perfil_variable (
                        id, categoria_id, nombre, campo_db, peso_variable, tipo,
                        encuesta_id, activa, tipo_form, texto, orden, migrado, nombre_natural
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        nuevo_id,
                        payload.categoria_id,
                        payload.nombre,
                        payload.campo_db,
                        payload.peso_variable,
                        payload.tipo,
                        payload.encuesta_id,
                        payload.activa,
                        payload.tipo_form,
                        payload.texto,
                        payload.orden,
                        payload.migrado,
                        payload.nombre_natural,
                    ),
                )
                conn.commit()
                cur.execute(
                    """
                    SELECT
                        id, categoria_id, nombre, campo_db, peso_variable, tipo,
                        created_at, encuesta_id, activa, tipo_form, texto, orden, migrado, nombre_natural
                    FROM creadores_perfil_variable
                    WHERE id = %s
                    """,
                    (nuevo_id,),
                )
                return {"ok": True, "variable": fetchone_dict(cur)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("perfil-config crear variable: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/creadores/perfil-config/variables/{variable_id}")
def actualizar_variable(
    variable_id: int,
    payload: VariableUpdate,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        data = payload.model_dump(exclude_unset=True)
        if "categoria_id" in data and data["categoria_id"] is not None:
            with get_connection_context() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM creadores_perfil_categoria WHERE id = %s",
                        (data["categoria_id"],),
                    )
                    if not cur.fetchone():
                        raise HTTPException(status_code=400, detail="categoria_id no existe")

        sets, vals = _build_update(payload, _VARIABLE_UPDATABLE)
        if not sets:
            with get_connection_context() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            id, categoria_id, nombre, campo_db, peso_variable, tipo,
                            created_at, encuesta_id, activa, tipo_form, texto, orden, migrado, nombre_natural
                        FROM creadores_perfil_variable
                        WHERE id = %s
                        """,
                        (variable_id,),
                    )
                    row = fetchone_dict(cur)
                    if not row:
                        raise HTTPException(status_code=404, detail="Variable no encontrada")
                    return {"ok": True, "variable": row}

        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM creadores_perfil_variable WHERE id = %s",
                    (variable_id,),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Variable no encontrada")
                sql = f"UPDATE creadores_perfil_variable SET {', '.join(sets)} WHERE id = %s"
                cur.execute(sql, vals + [variable_id])
                conn.commit()
                cur.execute(
                    """
                    SELECT
                        id, categoria_id, nombre, campo_db, peso_variable, tipo,
                        created_at, encuesta_id, activa, tipo_form, texto, orden, migrado, nombre_natural
                    FROM creadores_perfil_variable
                    WHERE id = %s
                    """,
                    (variable_id,),
                )
                return {"ok": True, "variable": fetchone_dict(cur)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("perfil-config actualizar variable: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


def _count_respuestas_variable(cur, variable_id: int) -> int:
    cur.execute(
        "SELECT COUNT(*) FROM creadores_perfil_respuesta WHERE variable_id = %s",
        (variable_id,),
    )
    return cur.fetchone()[0]


def _count_respuestas_valor(cur, valor_id: int) -> int:
    cur.execute(
        """
        SELECT COUNT(*) FROM creadores_perfil_respuesta
        WHERE valor_id = %s
        """,
        (valor_id,),
    )
    return cur.fetchone()[0]


@router.delete("/api/creadores/perfil-config/variables/{variable_id}")
def eliminar_variable(
    variable_id: int,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                if _count_respuestas_variable(cur, variable_id) > 0:
                    raise HTTPException(
                        status_code=409,
                        detail="Hay respuestas de creadores para esta variable; no se elimina.",
                    )
                cur.execute(
                    "DELETE FROM creadores_perfil_valor WHERE variable_id = %s",
                    (variable_id,),
                )
                cur.execute(
                    "DELETE FROM creadores_perfil_variable WHERE id = %s RETURNING id",
                    (variable_id,),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Variable no encontrada")
                conn.commit()
                return {"ok": True, "eliminado_id": variable_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("perfil-config eliminar variable: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/api/creadores/perfil-config/variables/reordenar")
def reordenar_variables(
    body: ReordenarVariablesBody,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    if not body.items:
        raise HTTPException(status_code=400, detail="items vacío")
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                for it in body.items:
                    cur.execute(
                        """
                        UPDATE creadores_perfil_variable
                        SET orden = %s
                        WHERE id = %s
                        """,
                        (it.orden, it.id),
                    )
                    if cur.rowcount == 0:
                        raise HTTPException(
                            status_code=404,
                            detail=f"Variable id={it.id} no encontrada",
                        )
                conn.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("perfil-config reordenar variables: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Valores (opciones) ----------


@router.get("/api/creadores/perfil-config/variables/{variable_id}/valores")
def listar_valores_por_variable(
    variable_id: int,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM creadores_perfil_variable WHERE id = %s",
                    (variable_id,),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Variable no encontrada")
                cur.execute(
                    """
                    SELECT
                        id, variable_id, min_val, max_val, score, label, nivel, orden,
                        created_at, valor_padre_id
                    FROM creadores_perfil_valor
                    WHERE variable_id = %s
                    ORDER BY orden NULLS LAST, id ASC
                    """,
                    (variable_id,),
                )
                return {"ok": True, "valores": fetchall_dict(cur)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("perfil-config listar valores: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/creadores/perfil-config/valores/{valor_id}")
def detalle_valor(
    valor_id: int,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        id, variable_id, min_val, max_val, score, label, nivel, orden,
                        created_at, valor_padre_id
                    FROM creadores_perfil_valor
                    WHERE id = %s
                    """,
                    (valor_id,),
                )
                row = fetchone_dict(cur)
                if not row:
                    raise HTTPException(status_code=404, detail="Valor no encontrado")
                return {"ok": True, "valor": row}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("perfil-config detalle valor: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/creadores/perfil-config/variables/{variable_id}/valores")
def crear_valor(
    variable_id: int,
    payload: ValorCreate,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM creadores_perfil_variable WHERE id = %s",
                    (variable_id,),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Variable no encontrada")
                cur.execute(
                    """
                    INSERT INTO creadores_perfil_valor (
                        variable_id, min_val, max_val, score, label, nivel, orden, valor_padre_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING
                        id, variable_id, min_val, max_val, score, label, nivel, orden,
                        created_at, valor_padre_id
                    """,
                    (
                        variable_id,
                        payload.min_val,
                        payload.max_val,
                        payload.score,
                        payload.label,
                        payload.nivel,
                        payload.orden,
                        payload.valor_padre_id,
                    ),
                )
                row = fetchone_dict(cur)
                conn.commit()
                return {"ok": True, "valor": row}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("perfil-config crear valor: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/creadores/perfil-config/valores/{valor_id}")
def actualizar_valor(
    valor_id: int,
    payload: ValorUpdate,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        sets, vals = _build_update(payload, _VALOR_UPDATABLE)
        if not sets:
            with get_connection_context() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            id, variable_id, min_val, max_val, score, label, nivel, orden,
                            created_at, valor_padre_id
                        FROM creadores_perfil_valor
                        WHERE id = %s
                        """,
                        (valor_id,),
                    )
                    row = fetchone_dict(cur)
                    if not row:
                        raise HTTPException(status_code=404, detail="Valor no encontrado")
                    return {"ok": True, "valor": row}

        if payload.variable_id is not None:
            with get_connection_context() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM creadores_perfil_variable WHERE id = %s",
                        (payload.variable_id,),
                    )
                    if not cur.fetchone():
                        raise HTTPException(status_code=400, detail="variable_id no existe")

        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM creadores_perfil_valor WHERE id = %s",
                    (valor_id,),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Valor no encontrado")
                sql = f"UPDATE creadores_perfil_valor SET {', '.join(sets)} WHERE id = %s"
                cur.execute(sql, vals + [valor_id])
                conn.commit()
                cur.execute(
                    """
                    SELECT
                        id, variable_id, min_val, max_val, score, label, nivel, orden,
                        created_at, valor_padre_id
                    FROM creadores_perfil_valor
                    WHERE id = %s
                    """,
                    (valor_id,),
                )
                return {"ok": True, "valor": fetchone_dict(cur)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("perfil-config actualizar valor: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/creadores/perfil-config/valores/{valor_id}")
def eliminar_valor(
    valor_id: int,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                if _count_respuestas_valor(cur, valor_id) > 0:
                    raise HTTPException(
                        status_code=409,
                        detail="Hay respuestas que usan esta opción (valor_id); no se elimina.",
                    )
                cur.execute(
                    "DELETE FROM creadores_perfil_valor WHERE id = %s RETURNING id",
                    (valor_id,),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Valor no encontrado")
                conn.commit()
                return {"ok": True, "eliminado_id": valor_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("perfil-config eliminar valor: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/api/creadores/perfil-config/valores/reordenar")
def reordenar_valores(
    body: ReordenarValoresBody,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    if not body.items:
        raise HTTPException(status_code=400, detail="items vacío")
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                for it in body.items:
                    cur.execute(
                        """
                        UPDATE creadores_perfil_valor
                        SET orden = %s
                        WHERE id = %s
                        """,
                        (it.orden, it.id),
                    )
                    if cur.rowcount == 0:
                        raise HTTPException(
                            status_code=404,
                            detail=f"Valor id={it.id} no encontrado",
                        )
                conn.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("perfil-config reordenar valores: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Árbol (una sola carga para el front) ----------


@router.get("/api/creadores/perfil-config/arbol")
def obtener_arbol_config(
    encuesta_id: Optional[int] = Query(None, description="Si se indica, solo variables de esa encuesta"),
    incluir_inactivas: bool = Query(False, description="Si true, incluye categorías y variables inactivas"),
    _usuario: dict = Depends(obtener_usuario_actual),
):
    """
    Categorías con variables anidadas y valores anidados (ordenados).
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cwhere = "1=1"
                if not incluir_inactivas:
                    cwhere = "COALESCE(activa, true) = true"
                cur.execute(
                    f"""
                    SELECT
                        id, nombre, nombre_natural, descripcion, orden, activa, tipo, created_at
                    FROM creadores_perfil_categoria
                    WHERE {cwhere}
                    ORDER BY orden NULLS LAST, id ASC
                    """
                )
                categorias = fetchall_dict(cur)

                vwhere = ["1=1"]
                vparams: List[Any] = []
                if not incluir_inactivas:
                    vwhere.append("COALESCE(v.activa, true) = true")
                if encuesta_id is not None:
                    vwhere.append("v.encuesta_id = %s")
                    vparams.append(encuesta_id)
                vw = " AND ".join(vwhere)

                cur.execute(
                    f"""
                    SELECT
                        v.id, v.categoria_id, v.nombre, v.campo_db, v.peso_variable, v.tipo,
                        v.created_at, v.encuesta_id, v.activa, v.tipo_form, v.texto,
                        v.orden, v.migrado, v.nombre_natural
                    FROM creadores_perfil_variable v
                    WHERE {vw}
                    ORDER BY v.categoria_id NULLS LAST, v.orden NULLS LAST, v.id ASC
                    """,
                    vparams,
                )
                variables = fetchall_dict(cur)

        by_cat: Dict[int, List[Dict[str, Any]]] = {}
        for v in variables:
            cid = v["categoria_id"]
            if cid is None:
                continue
            by_cat.setdefault(cid, []).append(v)

        var_ids = [v["id"] for v in variables]
        valores_by_var: Dict[int, List[Dict[str, Any]]] = {}
        if var_ids:
            with get_connection_context() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            id, variable_id, min_val, max_val, score, label, nivel, orden,
                            created_at, valor_padre_id
                        FROM creadores_perfil_valor
                        WHERE variable_id = ANY(%s)
                        ORDER BY variable_id ASC, orden NULLS LAST, id ASC
                        """,
                        (var_ids,),
                    )
                    for val in fetchall_dict(cur):
                        valores_by_var.setdefault(val["variable_id"], []).append(val)

        out = []
        for c in categorias:
            cid = c["id"]
            vars_cat = by_cat.get(cid, [])
            for vv in vars_cat:
                vv["valores"] = valores_by_var.get(vv["id"], [])
            c_out = {**c, "variables": vars_cat}
            out.append(c_out)

        return {
            "ok": True,
            "encuesta_id": encuesta_id,
            "categorias": out,
        }
    except Exception as e:
        logger.exception("perfil-config arbol: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
