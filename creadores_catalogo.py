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
