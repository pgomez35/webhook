"""
Catálogo y CRUD de maestros de creadores:
- creadores_categoria (niveles operativos, meta diamantes)
- creadores_estados (Activo, Inactivo, Retirado, Expulsado, etc.)

Distinto de creadores_perfil_categoria (grupos del cuestionario de perfil).

Requiere JWT de administrador (mismo patrón que main_creadores_perfil_config).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from DataBase import get_connection_context
from main_auth import obtener_usuario_actual

logger = logging.getLogger("uvicorn.error")

router = APIRouter()

_SELECT_ESTADO = """
    SELECT
        id,
        nombre,
        descripcion,
        activo,
        orden,
        creado_en
    FROM creadores_estados
"""

_SELECT_CATEGORIA = """
    SELECT
        id,
        nombre,
        meta_diamantes_objetivo,
        descripcion,
        orden,
        activa,
        created_at
    FROM creadores_categoria
"""

_UPDATABLE = frozenset(
    {
        "nombre",
        "meta_diamantes_objetivo",
        "descripcion",
        "orden",
        "activa",
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


def _build_update(payload: BaseModel) -> tuple[List[str], List[Any]]:
    data = payload.model_dump(exclude_unset=True)
    sets: List[str] = []
    vals: List[Any] = []
    for key, val in data.items():
        if key not in _UPDATABLE:
            continue
        sets.append(f"{key} = %s")
        vals.append(val)
    return sets, vals


class CreadorCategoriaCreate(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=50)
    meta_diamantes_objetivo: Optional[int] = Field(None, ge=0)
    descripcion: Optional[str] = Field(None, max_length=300)
    orden: Optional[int] = None
    activa: bool = True


class CreadorCategoriaUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=1, max_length=50)
    meta_diamantes_objetivo: Optional[int] = Field(None, ge=0)
    descripcion: Optional[str] = Field(None, max_length=300)
    orden: Optional[int] = None
    activa: Optional[bool] = None


class ReorderItem(BaseModel):
    id: int
    orden: int


class ReordenarCategoriasBody(BaseModel):
    items: List[ReorderItem]


def _get_categoria_or_404(cur, categoria_id: int) -> Dict[str, Any]:
    cur.execute(f"{_SELECT_CATEGORIA} WHERE id = %s", (categoria_id,))
    row = fetchone_dict(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Categoría de creador no encontrada")
    return row


def _get_estado_or_404(cur, estado_id: int) -> Dict[str, Any]:
    cur.execute(f"{_SELECT_ESTADO} WHERE id = %s", (estado_id,))
    row = fetchone_dict(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Estado de creador no encontrado")
    return row


# ---------- Catálogo creadores_estados ----------


@router.get("/api/creadores/estados")
def listar_creadores_estados(
    solo_activos: bool = Query(
        False,
        description="Si true, solo filas con activo = true",
    ),
    _usuario: dict = Depends(obtener_usuario_actual),
):
    """
    Lista el catálogo creadores_estados (para selects en formularios de creador).
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                where = "1=1"
                if solo_activos:
                    where = "activo = true"
                cur.execute(
                    f"""
                    {_SELECT_ESTADO}
                    WHERE {where}
                    ORDER BY orden ASC, id ASC
                    """
                )
                return {"ok": True, "estados": fetchall_dict(cur)}
    except Exception as e:
        logger.exception("listar creadores_estados: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/creadores/estados/{estado_id}")
def detalle_creador_estado(
    estado_id: int,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                return {"ok": True, "estado": _get_estado_or_404(cur, estado_id)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("detalle creadores_estados: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------- CRUD creadores_categoria ----------


def _count_creadores_con_nombre_categoria(cur, nombre: str) -> int:
    """creadores.categoria guarda el nombre (varchar), no FK."""
    cur.execute(
        """
        SELECT COUNT(*) FROM creadores
        WHERE categoria IS NOT NULL AND TRIM(categoria) = TRIM(%s)
        """,
        (nombre,),
    )
    return cur.fetchone()[0]


@router.get("/api/creadores/categorias")
def listar_creadores_categorias(
    solo_activas: bool = Query(False),
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                where = "1=1"
                params: List[Any] = []
                if solo_activas:
                    where = "COALESCE(activa, true) = true"
                cur.execute(
                    f"""
                    {_SELECT_CATEGORIA}
                    WHERE {where}
                    ORDER BY orden NULLS LAST, id ASC
                    """,
                    params,
                )
                return {"ok": True, "categorias": fetchall_dict(cur)}
    except Exception as e:
        logger.exception("listar creadores_categoria: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/creadores/categorias/{categoria_id}")
def detalle_creador_categoria(
    categoria_id: int,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                return {"ok": True, "categoria": _get_categoria_or_404(cur, categoria_id)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("detalle creadores_categoria: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/creadores/categorias")
def crear_creador_categoria(
    payload: CreadorCategoriaCreate,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO creadores_categoria (
                        nombre,
                        meta_diamantes_objetivo,
                        descripcion,
                        orden,
                        activa
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        payload.nombre.strip(),
                        payload.meta_diamantes_objetivo,
                        payload.descripcion,
                        payload.orden,
                        payload.activa,
                    ),
                )
                nuevo_id = cur.fetchone()[0]
                conn.commit()
                return {
                    "ok": True,
                    "categoria": _get_categoria_or_404(cur, nuevo_id),
                }
    except Exception as e:
        err = str(e).lower()
        if "unique" in err and "nombre" in err:
            raise HTTPException(
                status_code=409,
                detail=f"Ya existe una categoría con nombre '{payload.nombre}'",
            )
        logger.exception("crear creadores_categoria: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/creadores/categorias/{categoria_id}")
def actualizar_creador_categoria(
    categoria_id: int,
    payload: CreadorCategoriaUpdate,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        sets, vals = _build_update(payload)
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                actual = _get_categoria_or_404(cur, categoria_id)
                if not sets:
                    return {"ok": True, "categoria": actual}

                nombre_anterior = actual["nombre"]
                sql = f"UPDATE creadores_categoria SET {', '.join(sets)} WHERE id = %s"
                cur.execute(sql, vals + [categoria_id])

                if payload.nombre is not None and payload.nombre.strip() != nombre_anterior:
                    cur.execute(
                        """
                        UPDATE creadores
                        SET categoria = %s, updated_at = now()
                        WHERE categoria IS NOT NULL AND TRIM(categoria) = TRIM(%s)
                        """,
                        (payload.nombre.strip(), nombre_anterior),
                    )

                conn.commit()
                return {"ok": True, "categoria": _get_categoria_or_404(cur, categoria_id)}
    except HTTPException:
        raise
    except Exception as e:
        err = str(e).lower()
        if "unique" in err and "nombre" in err:
            raise HTTPException(status_code=409, detail="Nombre de categoría ya en uso")
        logger.exception("actualizar creadores_categoria: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/creadores/categorias/{categoria_id}")
def eliminar_creador_categoria(
    categoria_id: int,
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                actual = _get_categoria_or_404(cur, categoria_id)
                n = _count_creadores_con_nombre_categoria(cur, actual["nombre"])
                if n > 0:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"No se puede eliminar: {n} creador(es) usan la categoría "
                            f"'{actual['nombre']}'."
                        ),
                    )
                cur.execute(
                    "DELETE FROM creadores_categoria WHERE id = %s RETURNING id",
                    (categoria_id,),
                )
                if not cur.fetchone():
                    raise HTTPException(
                        status_code=404, detail="Categoría de creador no encontrada"
                    )
                conn.commit()
                return {"ok": True, "eliminado_id": categoria_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("eliminar creadores_categoria: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/api/creadores/categorias/reordenar")
def reordenar_creadores_categorias(
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
                        UPDATE creadores_categoria
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
        logger.exception("reordenar creadores_categoria: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
