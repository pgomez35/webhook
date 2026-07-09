-- Capacitaciones de creadores (ejecutar en el esquema del tenant)

CREATE TABLE IF NOT EXISTS creadores_capacitaciones
(
    id_capacitacion serial PRIMARY KEY,

    nombre varchar(150) NOT NULL,
    descripcion text,
    categoria varchar(100),

    obligatoria boolean NOT NULL DEFAULT true,
    activa boolean NOT NULL DEFAULT true,

    orden integer NOT NULL DEFAULT 1,

    fecha_creacion timestamp without time zone DEFAULT now(),
    fecha_actualizacion timestamp without time zone DEFAULT now(),

    CONSTRAINT uq_creadores_capacitaciones_nombre
    UNIQUE (nombre)
);

CREATE TABLE IF NOT EXISTS creadores_capacitaciones_seguimiento
(
    id_seguimiento serial PRIMARY KEY,

    creador_id integer,
    creador_tiktok_id varchar(255) NOT NULL,
    usuario_tiktok varchar(100),

    manager varchar(200),
    grupo varchar(150),

    id_capacitacion integer NOT NULL,

    estado varchar(30) NOT NULL DEFAULT 'pendiente',

    fecha_realizacion date,
    observacion text,

    actualizado_por integer,

    fecha_creacion timestamp without time zone DEFAULT now(),
    fecha_actualizacion timestamp without time zone DEFAULT now(),

    CONSTRAINT fk_capacitacion_seguimiento
    FOREIGN KEY (id_capacitacion)
    REFERENCES creadores_capacitaciones (id_capacitacion),

    CONSTRAINT chk_capacitacion_estado
    CHECK (estado IN ('pendiente', 'realizada', 'no_aplica')),

    CONSTRAINT uq_capacitacion_creador
    UNIQUE (creador_tiktok_id, id_capacitacion)
);

CREATE INDEX IF NOT EXISTS idx_capacitaciones_activa_orden
ON creadores_capacitaciones (activa, orden);

CREATE INDEX IF NOT EXISTS idx_capacitaciones_seguimiento_creador
ON creadores_capacitaciones_seguimiento (creador_tiktok_id);

CREATE INDEX IF NOT EXISTS idx_capacitaciones_seguimiento_manager
ON creadores_capacitaciones_seguimiento (manager);

CREATE INDEX IF NOT EXISTS idx_capacitaciones_seguimiento_estado
ON creadores_capacitaciones_seguimiento (estado);

CREATE INDEX IF NOT EXISTS idx_capacitaciones_seguimiento_capacitacion
ON creadores_capacitaciones_seguimiento (id_capacitacion);

INSERT INTO creadores_capacitaciones
(nombre, categoria, obligatoria, activa, orden)
VALUES
('Llamada de bienvenida', 'Inicio', true, true, 1),
('Capa herramienta', 'Formación', true, true, 2),
('Capa general', 'Formación', true, true, 3),
('Capa creatividad y estrategias', 'Contenido', true, true, 4),
('Club de fans', 'Comunidad', false, true, 5),
('Planeador LIVE', 'Planeación', true, true, 6),
('Creando comunidad', 'Comunidad', true, true, 7),
('Capa gaming', 'Nicho', false, true, 8)
ON CONFLICT (nombre) DO NOTHING;
