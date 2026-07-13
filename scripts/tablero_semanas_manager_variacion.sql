-- Columnas adicionales por semana en el tablero de seguimiento semanal.
-- manager_semana: agente del reporte semanal (creadores_reporte_integral.agente)
-- variacion_diamantes_pct: % de cambio de diamantes vs semana anterior del mismo creador

ALTER TABLE creadores_performance_tablero_semanas
ADD COLUMN IF NOT EXISTS manager_semana varchar(200);

ALTER TABLE creadores_performance_tablero_semanas
ADD COLUMN IF NOT EXISTS variacion_diamantes_pct numeric(8,2);
