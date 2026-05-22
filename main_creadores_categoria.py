"""
Catálogo y CRUD de maestros de creadores:
- creadores_categoria (niveles operativos, meta diamantes)
- creadores_estados (Activo, Inactivo, Retirado, Expulsado, etc.)

Distinto de creadores_perfil_categoria (grupos del cuestionario de perfil).

Requiere JWT de administrador (mismo patrón que main_creadores_perfil_config).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from DataBase import get_connection_context, obtener_todos_manager
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

_SELECT_ARQUETIPO = """
    SELECT id, codigo, nombre, descripcion_operativa, orden, activo
    FROM creadores_arquetipo
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


def obtener_creadores_categorias_catalogo(solo_activas: bool = False) -> List[Dict[str, Any]]:
    """Misma consulta que GET /api/creadores/categorias."""
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            where = "1=1"
            if solo_activas:
                where = "COALESCE(activa, true) = true"
            cur.execute(
                f"""
                {_SELECT_CATEGORIA}
                WHERE {where}
                ORDER BY orden NULLS LAST, id ASC
                """
            )
            return fetchall_dict(cur)


def obtener_creadores_estados_catalogo(solo_activos: bool = False) -> List[Dict[str, Any]]:
    """Misma consulta que GET /api/creadores/estados."""
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
            return fetchall_dict(cur)


def obtener_arquetipos_creador_catalogo(solo_activos: bool = True) -> List[Dict[str, Any]]:
    """Misma consulta que GET /api/creadores/arquetipos."""
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            sql = f"{_SELECT_ARQUETIPO}"
            if solo_activos:
                sql += " WHERE COALESCE(activo, true) = true"
            sql += " ORDER BY orden NULLS LAST, nombre ASC, id ASC"
            cur.execute(sql)
            return fetchall_dict(cur)


def obtener_managers_catalogo() -> List[Dict[str, Any]]:
    """Mismo conjunto que GET /api/admin-usuario_manager (schema AdminUsuarioManagerResponse)."""
    return [
        {
            "id": u["id"],
            "username": u["username"],
            "nombre_completo": u["nombre_completo"],
            "grupo": u["grupo"],
            "activo": u["activo"],
        }
        for u in obtener_todos_manager()
    ]


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
        return {"ok": True, "estados": obtener_creadores_estados_catalogo(solo_activos)}
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


def _count_creadores_con_categoria_id(cur, categoria_id: int) -> int:
    cur.execute(
        """
        SELECT COUNT(*) FROM creadores
        WHERE categoria_id = %s
        """,
        (categoria_id,),
    )
    return cur.fetchone()[0]


@router.get("/api/creadores/categorias")
def listar_creadores_categorias(
    solo_activas: bool = Query(False),
    _usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        return {"ok": True, "categorias": obtener_creadores_categorias_catalogo(solo_activas)}
    except Exception as e:
        logger.exception("listar creadores_categoria: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Catálogos unificados (Creadores Activos) ----------


@router.get(
    "/api/creadores/activos/catalogos",
    tags=["Creadores"],
    response_model=None,
    responses={
        200: {
            "description": "Catálogos para selects del panel Creadores Activos",
            "content": {
                "application/json": {
                    "example": {
                        "ok": True,
                        "generado_en": "2026-05-19T12:00:00+00:00",
                        "categorias": [],
                        "estados": [],
                        "arquetipos": [],
                        "managers": [],
                    }
                }
            },
        }
    },
)
def catalogos_creadores_activos(
    solo_activas: bool = Query(
        False,
        description="Si true, solo categorías con activa = true (igual que /api/creadores/categorias)",
    ),
    solo_activos: bool = Query(
        False,
        description="Si true, filtra estados y arquetipos con activo = true",
    ),
    _usuario: dict = Depends(obtener_usuario_actual),
):
    """
    Agrega categorías, estados, arquetipos y managers en una sola respuesta cacheable.
    Reutiliza la misma lógica que los endpoints individuales; no incluye listado ni detalle de creador.
    """
    try:
        body = {
            "ok": True,
            "generado_en": datetime.now(timezone.utc).isoformat(),
            "categorias": obtener_creadores_categorias_catalogo(solo_activas),
            "estados": obtener_creadores_estados_catalogo(solo_activos),
            "arquetipos": obtener_arquetipos_creador_catalogo(solo_activos),
            "managers": obtener_managers_catalogo(),
        }
        return JSONResponse(
            content=body,
            headers={"Cache-Control": "private, max-age=300"},
        )
    except Exception as e:
        logger.exception("catalogos creadores activos: %s", e)
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

                sql = f"UPDATE creadores_categoria SET {', '.join(sets)} WHERE id = %s"
                cur.execute(sql, vals + [categoria_id])

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
                n = _count_creadores_con_categoria_id(cur, categoria_id)
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
