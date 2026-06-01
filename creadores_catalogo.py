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
    "no definida",
    "no definido",
    "no asignada",
    "no asignado",
    "ninguna",
    "ninguno",
    "null",
    "none",
    "n/a",
    "na",
})


def _row_id(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get("id")
    return row[0]


def resolver_categoria_id(cur, categoria):
    """
    Resuelve categoria_id para creadores.
    Valores vacíos o placeholders → None (NULL en BD).
    Nombre desconocido → None (no bloquea el guardado).
    """
    if categoria is None:
        return None

    if isinstance(categoria, bool):
        return None

    if isinstance(categoria, int):
        if categoria <= 0:
            return None
        cur.execute(
            "SELECT id FROM creadores_categoria WHERE id = %s LIMIT 1",
            (categoria,),
        )
        return _row_id(cur.fetchone())

    texto_original = str(categoria).strip()
    texto = texto_original.lower()

    if texto in _CATEGORIA_VACIA_LABELS:
        return None

    if texto.isdigit():
        cid = int(texto)
        if cid <= 0:
            return None
        cur.execute(
            "SELECT id FROM creadores_categoria WHERE id = %s LIMIT 1",
            (cid,),
        )
        return _row_id(cur.fetchone())

    cur.execute(
        """
        SELECT id
        FROM creadores_categoria
        WHERE LOWER(nombre) = LOWER(%s)
        LIMIT 1
        """,
        (texto_original,),
    )
    row = cur.fetchone()
    if row:
        return _row_id(row)

    return None


def resolver_categoria_id_creador(
    cur,
    categoria_id=None,
    categoria_legacy=None,
):
    """
    Resuelve FK creadores.categoria_id.
    Acepta categoria_id directo o nombre legado (campo categoria varchar antiguo).
    """
    if categoria_id is not None and str(categoria_id).strip() != "":
        resolved = resolver_categoria_id(cur, categoria_id)
        if resolved is not None:
            return resolved

    if categoria_legacy is not None and str(categoria_legacy).strip() != "":
        return resolver_categoria_id(cur, categoria_legacy)

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
