"""
Catálogo creadores_estados (nombre UNIQUE en BD).
Seed esperado: Activo, Inactivo, Retirado, Expulsado.
"""

CREADOR_ESTADO_NOMBRE_ACTIVO = "Activo"

# Subconsulta en INSERT/UPSERT: FK estado operativo por defecto
SQL_CREADOR_ESTADO_ID_ACTIVO = (
    "(SELECT id FROM creadores_estados WHERE nombre = 'Activo' "
    "AND COALESCE(activo, true) = true ORDER BY id LIMIT 1)"
)

# JOIN y columnas de categoría operativa (creadores_categoria)
SQL_JOIN_CREADOR_CATEGORIA = """
    LEFT JOIN creadores_categoria cat ON cat.id = c.categoria_id
"""

SQL_SELECT_CREADOR_CATEGORIA = """
    c.categoria_id,
    COALESCE(cat.nombre, 'Sin categoría') AS categoria,
"""

SQL_JOIN_CREADOR_ARQUETIPO = """
    LEFT JOIN creadores_arquetipo arq ON arq.id = c.arquetipo_id
"""

SQL_SELECT_CREADOR_ARQUETIPO = """
    c.arquetipo_id,
    COALESCE(arq.nombre, 'Sin arquetipo') AS arquetipo,
"""


_CATEGORIA_VACIA_LABELS = frozenset({
    "",
    "sin categoría",
    "sin categoria",
    "sin categoría ",
    "ninguna",
    "ninguno",
    "none",
    "null",
    "n/a",
    "na",
})


def _categoria_sin_asignar(categoria_id=None, categoria_legacy=None) -> bool:
    if categoria_id is not None and str(categoria_id).strip() != "":
        try:
            if int(categoria_id) > 0:
                return False
            return True
        except (TypeError, ValueError):
            pass
    if categoria_legacy is not None:
        leg = str(categoria_legacy).strip().lower()
        if leg in _CATEGORIA_VACIA_LABELS:
            return True
        if leg:
            return False
    return categoria_id is None or not str(categoria_id).strip()


def resolver_categoria_id_creador(
    cur,
    categoria_id=None,
    categoria_legacy=None,
):
    """
    Resuelve FK creadores.categoria_id.
    Acepta categoria_id directo o nombre legado (campo categoria varchar antiguo).
    Si no se envía categoría (null, 0, 'Sin categoría', etc.), devuelve None.
    """
    from fastapi import HTTPException

    if _categoria_sin_asignar(categoria_id, categoria_legacy):
        return None

    if categoria_id is not None:
        try:
            cid = int(categoria_id)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail=f"categoria_id inválido: {categoria_id}",
            )
        if cid <= 0:
            return None
        cur.execute(
            "SELECT id FROM creadores_categoria WHERE id = %s LIMIT 1",
            (cid,),
        )
        if not cur.fetchone():
            raise HTTPException(
                status_code=400,
                detail=f"categoria_id de creador no válido: {cid}",
            )
        return cid

    if categoria_legacy is not None and str(categoria_legacy).strip():
        leg = str(categoria_legacy).strip()
        if leg.lower() in _CATEGORIA_VACIA_LABELS:
            return None
        cur.execute(
            "SELECT id FROM creadores_categoria WHERE nombre ILIKE %s "
            "AND COALESCE(activa, true) = true ORDER BY id LIMIT 1",
            (leg,),
        )
        row = cur.fetchone()
        if not row:
            cur.execute(
                "SELECT id FROM creadores_categoria WHERE nombre ILIKE %s ORDER BY id LIMIT 1",
                (leg,),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(
                status_code=400,
                detail=f"Categoría de creador no reconocida: {categoria_legacy}",
            )
        return row[0]

    return None


def resolver_arquetipo_id_creador(
    cur,
    arquetipo_id=None,
    arquetipo_legacy=None,
):
    """
    Resuelve FK creadores.arquetipo_id por id o por nombre/código del catálogo.
    """
    from fastapi import HTTPException

    if arquetipo_id is not None:
        try:
            aid = int(arquetipo_id)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail=f"arquetipo_id inválido: {arquetipo_id}",
            )
        cur.execute(
            "SELECT id FROM creadores_arquetipo WHERE id = %s "
            "AND COALESCE(activo, true) = true LIMIT 1",
            (aid,),
        )
        if not cur.fetchone():
            cur.execute(
                "SELECT id FROM creadores_arquetipo WHERE id = %s LIMIT 1",
                (aid,),
            )
            if not cur.fetchone():
                raise HTTPException(
                    status_code=400,
                    detail=f"arquetipo_id de creador no válido: {aid}",
                )
        return aid

    if arquetipo_legacy is not None and str(arquetipo_legacy).strip():
        leg = str(arquetipo_legacy).strip()
        cur.execute(
            "SELECT id FROM creadores_arquetipo "
            "WHERE (nombre ILIKE %s OR codigo ILIKE %s) "
            "AND COALESCE(activo, true) = true "
            "ORDER BY id LIMIT 1",
            (leg, leg),
        )
        row = cur.fetchone()
        if not row:
            cur.execute(
                "SELECT id FROM creadores_arquetipo "
                "WHERE nombre ILIKE %s OR codigo ILIKE %s "
                "ORDER BY id LIMIT 1",
                (leg, leg),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(
                status_code=400,
                detail=f"Arquetipo de creador no reconocido: {arquetipo_legacy}",
            )
        return row[0]

    return None
