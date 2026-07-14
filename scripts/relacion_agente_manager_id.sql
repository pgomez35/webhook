-- ============================================================
-- Relación Agente (Backstage) ↔ administradores / manager_id
-- Script OPCIONAL: no ejecutar migraciones destructivas.
-- Ejecutar por esquema de agencia (search_path).
-- ============================================================

-- Columnas
ALTER TABLE creadores_reporte_integral
ADD COLUMN IF NOT EXISTS manager_id integer;

ALTER TABLE creadores_performance_tablero_creadores
ADD COLUMN IF NOT EXISTS manager_id integer;

ALTER TABLE creadores_performance_tablero_semanas
ADD COLUMN IF NOT EXISTS manager_id integer;

ALTER TABLE administradores
ADD COLUMN IF NOT EXISTS agente varchar(100);

ALTER TABLE creadores_capacitaciones_seguimiento
ADD COLUMN IF NOT EXISTS manager_id integer;

-- Índices
CREATE INDEX IF NOT EXISTS idx_administradores_email_lower
ON administradores (LOWER(TRIM(email)));

CREATE INDEX IF NOT EXISTS idx_administradores_agente_lower
ON administradores (LOWER(TRIM(agente)));

CREATE INDEX IF NOT EXISTS idx_reporte_integral_manager_id
ON creadores_reporte_integral (manager_id);

CREATE INDEX IF NOT EXISTS idx_tablero_creadores_manager_id
ON creadores_performance_tablero_creadores (manager_id);

CREATE INDEX IF NOT EXISTS idx_tablero_semanas_manager_id
ON creadores_performance_tablero_semanas (manager_id);

CREATE INDEX IF NOT EXISTS idx_capacitaciones_seguimiento_manager_id
ON creadores_capacitaciones_seguimiento (manager_id);

-- ============================================================
-- Backfill: creadores_reporte_integral.manager_id
-- ============================================================
UPDATE creadores_reporte_integral r
SET manager_id = a.id
FROM administradores a
WHERE r.manager_id IS NULL
  AND COALESCE(a.activo, true) = true
  AND r.agente IS NOT NULL
  AND TRIM(r.agente) <> ''
  AND (
        LOWER(TRIM(a.agente)) = LOWER(TRIM(r.agente))
        OR LOWER(TRIM(a.email)) = LOWER(TRIM(r.agente))
      );

-- ============================================================
-- Backfill: tablero_creadores (última semana / manager actual)
-- Preferible: recalcular el tablero después del backfill del reporte.
-- Este UPDATE intenta alinear manager_id y nombre visible.
-- ============================================================
UPDATE creadores_performance_tablero_creadores tc
SET
    manager_id = sub.manager_id,
    manager_actual = COALESCE(sub.nombre_completo, tc.manager_actual)
FROM (
    SELECT DISTINCT ON (r.creador_tiktok_id)
        r.creador_tiktok_id,
        r.manager_id,
        a.nombre_completo
    FROM creadores_reporte_integral r
    LEFT JOIN administradores a ON a.id = r.manager_id
    WHERE r.creador_tiktok_id IS NOT NULL
    ORDER BY r.creador_tiktok_id, r.periodo_fin DESC, r.id_reporte DESC
) sub
WHERE tc.creador_tiktok_id = sub.creador_tiktok_id
  AND (tc.manager_id IS DISTINCT FROM sub.manager_id OR sub.nombre_completo IS NOT NULL);

-- ============================================================
-- Backfill: tablero_semanas por periodo
-- ============================================================
UPDATE creadores_performance_tablero_semanas ts
SET
    manager_id = r.manager_id,
    manager_semana = COALESCE(a.nombre_completo, r.agente, ts.manager_semana)
FROM creadores_performance_tablero_creadores tc
INNER JOIN creadores_reporte_integral r
    ON r.creador_tiktok_id = tc.creador_tiktok_id
   AND r.periodo_inicio = ts.periodo_inicio
   AND r.periodo_fin = ts.periodo_fin
LEFT JOIN administradores a ON a.id = r.manager_id
WHERE ts.id_tablero_creador = tc.id_tablero_creador;
