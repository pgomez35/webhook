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


def resolver_categoria_id_creador(
    cur,
    categoria_id=None,
    categoria_legacy=None,
):
    """
    Resuelve FK creadores.categoria_id.
    Acepta categoria_id directo o nombre legado (campo categoria varchar antiguo).
    """
    from fastapi import HTTPException

    if categoria_id is not None:
        try:
            cid = int(categoria_id)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail=f"categoria_id inválido: {categoria_id}",
            )
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
