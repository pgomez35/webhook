-- Opcional: índice único funcional para usuario_tiktok normalizado.
-- NO ejecutar sin revisar duplicados existentes en cada esquema de agencia.
--
-- SELECT LOWER(TRIM(BOTH '@' FROM TRIM(usuario_tiktok))) AS u, COUNT(*)
-- FROM creadores
-- GROUP BY 1
-- HAVING COUNT(*) > 1;

-- CREATE UNIQUE INDEX IF NOT EXISTS uq_creadores_usuario_tiktok_norm
-- ON creadores (LOWER(TRIM(BOTH '@' FROM TRIM(usuario_tiktok))));
