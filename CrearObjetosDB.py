import os
import psycopg2
from dotenv import load_dotenv
from datetime import datetime

# Cargar variables de entorno (incluye DATABASE_URL)
load_dotenv()

INTERNAL_DATABASE_URL = os.getenv("INTERNAL_DATABASE_URL")

EXTERNAL_DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")

def cambiar_puntaje_a_numeric():
    conn = psycopg2.connect(EXTERNAL_DATABASE_URL)
    cur = conn.cursor()

    try:
        cur.execute("""
            ALTER TABLE perfil_creador
            ALTER COLUMN puntaje_total TYPE NUMERIC(10,2)
            USING puntaje_total::NUMERIC(10,2);
        """)
        conn.commit()
        print("Columna 'puntaje_total' cambiada a NUMERIC(10,2).")
    except Exception as e:
        conn.rollback()
        print("Error al cambiar tipo de 'puntaje_total':", e)
    finally:
        cur.close()
        conn.close()

def agregar_columnas_extra():
    conn = psycopg2.connect(EXTERNAL_DATABASE_URL)
    cur = conn.cursor()

    try:
        cur.execute("""
            ALTER TABLE perfil_creador
            ADD COLUMN IF NOT EXISTS usuario_evalua INTEGER,
            ADD COLUMN IF NOT EXISTS mejoras_sugeridas VARCHAR(500);
        """)
        conn.commit()
        print("Columnas 'usuario_evalua' y 'mejoras_sugeridas' agregadas correctamente.")
    except Exception as e:
        conn.rollback()
        print("Error al agregar columnas:", e)
    finally:
        cur.close()
        conn.close()

def agregar_columna_puntaje():
    conn = psycopg2.connect(EXTERNAL_DATABASE_URL)
    cur = conn.cursor()

    try:
        cur.execute("""
            ALTER TABLE perfil_creador
            ADD COLUMN IF NOT EXISTS puntaje_total INTEGER;
        """)
        conn.commit()
        print("Columna 'puntaje_total' agregada correctamente.")
    except Exception as e:
        conn.rollback()
        print("Error al agregar columna:", e)
    finally:
        cur.close()
        conn.close()


def cambiar_tipo_potencial():
    conn = psycopg2.connect(EXTERNAL_DATABASE_URL)
    cur = conn.cursor()

    try:
        cur.execute("""
            ALTER TABLE perfil_creador
            ALTER COLUMN usuario_evalua TYPE VARCHAR(100);
        """)
        conn.commit()
        print("Campo 'potencial_estimado' convertido a VARCHAR(20).")
    except Exception as e:
        conn.rollback()
        print("Error al cambiar tipo:", e)
    finally:
        cur.close()
        conn.close()

def eliminar_campo():
    conn = psycopg2.connect(EXTERNAL_DATABASE_URL)
    cur = conn.cursor()

    try:
        cur.execute("""
            ALTER TABLE agendamientos DROP COLUMN manager_id;
        """)
        conn.commit()
        print("Campo 'potencial_estimado' convertido a VARCHAR(20).")
    except Exception as e:
        conn.rollback()
        print("Error al cambiar tipo:", e)
    finally:
        cur.close()
        conn.close()

def crear_tablas():
    conn = psycopg2.connect(EXTERNAL_DATABASE_URL)
    cur = conn.cursor()

    # Tabla: creadores
    cur.execute("""
CREATE TABLE IF NOT EXISTS perfil_creador (
    id SERIAL PRIMARY KEY,
    usuario VARCHAR(100),
    creador_id INTEGER UNIQUE REFERENCES creadores(id) ON DELETE CASCADE,
    edad INTEGER,
    genero VARCHAR(50),
    pais VARCHAR(100),
    ciudad VARCHAR(200),
    zona_horaria VARCHAR(100),
    estudios VARCHAR(200),
    seguidores INTEGER DEFAULT 0,
    siguiendo INTEGER DEFAULT 0,
    videos INTEGER DEFAULT 0,
    likes BIGINT DEFAULT 0,
    duracion_emisiones INTEGER DEFAULT 0,
    dias_emisiones INTEGER DEFAULT 0,
    perfil VARCHAR(20),
    apariencia INTEGER DEFAULT 0,
    engagement INTEGER DEFAULT 0,
    calidad_contenido INTEGER DEFAULT 0,
    horario_preferido varchar(100),
    intencion_trabajo VARCHAR(50),
    tiempo_disponible INTEGER,
    frecuencia_lives INTEGER DEFAULT 0,
    intereses JSONB,
    biografia varchar(200),
    puntaje_total INTEGER,
    potencial_estimado varchar(20),
    fecha_evaluacion TIMESTAMP,
    estado VARCHAR(50) DEFAULT 'activo',
    creado_en TIMESTAMP DEFAULT NOW(),
    actualizado_en TIMESTAMP DEFAULT NOW()
);
    """)

    # cur.execute("""
    # # CREATE TABLE IF NOT EXISTS creadores (
    # #     id SERIAL PRIMARY KEY,
    # #     usuario VARCHAR(100) UNIQUE,
    # #     nickname VARCHAR(200),
    # #     nombre_real VARCHAR(200),
    # #     email VARCHAR(200),
    # #     telefono VARCHAR(50),
    # #     whatsapp VARCHAR(50),
    # #     foto_url TEXT,
    # #     estado_id INTEGER,
    # #     verificado BOOLEAN DEFAULT FALSE,
    # #     fecha_verificacion TIMESTAMP,
    # #     activo BOOLEAN DEFAULT TRUE,
    # #     creado_en TIMESTAMP DEFAULT NOW(),
    # #     actualizado_en TIMESTAMP DEFAULT NOW()
    # # );
    # # """)

    # # Tabla: cargue_creadores
    # cur.execute("""
    # CREATE TABLE IF NOT EXISTS cargue_creadores (
    #     id SERIAL PRIMARY KEY,
    #     usuario VARCHAR(100),
    #     nickname VARCHAR(200),
    #     email VARCHAR(200),
    #     telefono VARCHAR(50),
    #     disponibilidad VARCHAR(100),
    #     perfil VARCHAR(100),
    #     motivo_no_apto TEXT,
    #     contacto VARCHAR(100),
    #     respuesta_creador TEXT,
    #     entrevista VARCHAR(200),
    #     tipo_solicitud VARCHAR(100),
    #     razon_no_contacto TEXT,
    #     seguidores INTEGER DEFAULT 0,
    #     cantidad_videos INTEGER DEFAULT 0,
    #     likes_totales BIGINT DEFAULT 0,
    #     duracion_emisiones INTEGER DEFAULT 0,
    #     dias_emisiones INTEGER DEFAULT 0,
    #     nombre_archivo VARCHAR(500),
    #     hoja_excel VARCHAR(200),
    #     fila_excel INTEGER,
    #     lote_carga VARCHAR(200),
    #     fecha_carga DATE DEFAULT CURRENT_DATE,
    #     estado VARCHAR(100),
    #     procesado BOOLEAN DEFAULT FALSE,
    #     fecha_procesamiento TIMESTAMP,
    #     procesado_por INTEGER,
    #     creador_id INTEGER,
    #     apto BOOLEAN,
    #     puntaje_evaluacion DECIMAL(10,4),
    #     contactado BOOLEAN DEFAULT FALSE,
    #     fecha_contacto TIMESTAMP,
    #     respondio BOOLEAN DEFAULT FALSE,
    #     observaciones TEXT,
    #     activo BOOLEAN DEFAULT TRUE,
    #     creado_en TIMESTAMP DEFAULT NOW(),
    #     actualizado_en TIMESTAMP DEFAULT NOW(),
    #     UNIQUE (usuario, hoja_excel)
    # );
    # """)

    # # Tabla: perfil_creador_viejo
    # cur.execute("""
    # CREATE TABLE IF NOT EXISTS perfil_creador (
    #     id SERIAL PRIMARY KEY,
    #     creador_id INTEGER UNIQUE,
    #     edad INTEGER,
    #     genero VARCHAR(50),
    #     pais VARCHAR(100),
    #     ciudad VARCHAR(200),
    #     estudios VARCHAR(200),
    #     perfil VARCHAR(100),
    #     apariencia INTEGER,
    #     carisma INTEGER,
    #     calidad_contenido INTEGER,
    #     calidad_foto INTEGER,
    #     seguidores INTEGER DEFAULT 0,
    #     siguiendo INTEGER DEFAULT 0,
    #     cantidad_videos INTEGER DEFAULT 0,
    #     likes_totales BIGINT DEFAULT 0,
    #     duracion_emisiones INTEGER DEFAULT 0,
    #     dias_emisiones INTEGER DEFAULT 0,
    #     engagement_rate DECIMAL(10,4) DEFAULT 0,
    #     duracion_promedio_lives INTEGER,
    #     frecuencia_lives INTEGER,
    #     horario_preferido_inicio TIME,
    #     horario_preferido_fin TIME,
    #     intencion_trabajo VARCHAR(200),
    #     tiempo_disponible_horas INTEGER,
    #     dias_disponibles JSONB,
    #     zona_horaria VARCHAR(100),
    #     intereses JSONB,
    #     biografia_actual TEXT,
    #     biografia_tiene BOOLEAN DEFAULT FALSE,
    #     biografia_propuesta TEXT,
    #     temas_contenido JSONB,
    #     clasificacion_inicial VARCHAR(100),
    #     clasificacion_actual VARCHAR(100),
    #     potencial_estimado INTEGER,
    #     fecha_incorporacion TIMESTAMP,
    #     fecha_ultima_evaluacion TIMESTAMP,
    #     evaluacion_inicial_id INTEGER,
    #     evaluacion_prueba_id INTEGER,
    #     creado_en TIMESTAMP DEFAULT NOW(),
    #     actualizado_en TIMESTAMP DEFAULT NOW(),
    #     FOREIGN KEY (creador_id) REFERENCES creadores(id) ON DELETE CASCADE
    # );
    # """)

    # # Tabla: agendamientos
    # cur.execute("""
    # CREATE TABLE IF NOT EXISTS agendamientos (
    #     id SERIAL PRIMARY KEY,
    #     titulo VARCHAR(200),
    #     descripcion TEXT,
    #     fecha_inicio TIMESTAMP,
    #     fecha_fin TIMESTAMP,
    #     creador_id INTEGER REFERENCES creadores(id) ON DELETE SET NULL,
    #     manager_id INTEGER,
    #     responsable_id INTEGER,
    #     estado VARCHAR(50),
    #     link_meet TEXT,
    #     google_event_id VARCHAR(100),
    #     creado_en TIMESTAMP DEFAULT NOW(),
    #     actualizado_en TIMESTAMP DEFAULT NOW()
    # );
    # """)

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Tablas creadas exitosamente.")

def migrar_datos():
    conn = psycopg2.connect(EXTERNAL_DATABASE_URL)
    cur = conn.cursor()

    try:
        # Inserción
        cur.execute("""
            INSERT INTO perfil_creador1 (
                usuario,
                creador_id, edad, genero, pais, ciudad, zona_horaria,
                estudios, seguidores, siguiendo, videos, likes,
                duracion_emisiones, dias_emisiones, perfil, apariencia,
                engagement, calidad_contenido, horario_preferido,
                intencion_trabajo, tiempo_disponible, frecuencia_lives,
                intereses, biografia, potencial_estimado, fecha_evaluacion,
                creado_en, actualizado_en
            )
            SELECT 
                NULL,  -- usuario será actualizado luego
                creador_id, edad, genero, pais, ciudad, zona_horaria,
                estudios, seguidores, siguiendo, cantidad_videos, likes_totales,
                duracion_emisiones, dias_emisiones, perfil, apariencia,
                ROUND(engagement_rate * 100),
                calidad_contenido,
                CASE 
                    WHEN horario_preferido_inicio IS NOT NULL AND horario_preferido_fin IS NOT NULL 
                    THEN TO_CHAR(horario_preferido_inicio, 'HH24:MI') || '-' || TO_CHAR(horario_preferido_fin, 'HH24:MI')
                    ELSE NULL 
                END,
                intencion_trabajo, tiempo_disponible_horas, frecuencia_lives,
                intereses, biografia_actual, potencial_estimado,
                fecha_ultima_evaluacion, creado_en, actualizado_en
            FROM perfil_creador;
        """)

        # Actualización del campo `usuario`
        cur.execute("""
            UPDATE perfil_creador1 x
            SET usuario = y.usuario
            FROM creadores y
            WHERE x.creador_id = y.id;
        """)

        # Renombrar tablas
        cur.execute("ALTER TABLE perfil_creador RENAME TO perfil_creador_backup;")
        cur.execute("ALTER TABLE perfil_creador1 RENAME TO perfil_creador;")

        conn.commit()
        print("Migración y actualización completadas con éxito.")
    except Exception as e:
        conn.rollback()
        print("Error:", e)
    finally:
        cur.close()
        conn.close()


def crear_tablas_extra():
    conn = psycopg2.connect(EXTERNAL_DATABASE_URL)
    cur = conn.cursor()

    # # Tabla: agendamiento_creadores
    cur.execute("""
      CREATE TABLE IF NOT EXISTS agendamiento_creadores (
    id SERIAL PRIMARY KEY,
    agendamiento_id INTEGER NOT NULL REFERENCES agendamientos(id) ON DELETE CASCADE,
    creador_id INTEGER NOT NULL REFERENCES creadores(id) ON DELETE CASCADE
);
    """)




    # # # Tabla: admin_usuario
    # cur.execute("""
    #     CREATE TABLE IF NOT EXISTS admin_usuario (
    #         id SERIAL PRIMARY KEY,
    #         username VARCHAR(50) UNIQUE NOT NULL,
    #         nombre_completo VARCHAR(255),
    #         email VARCHAR(255) UNIQUE,
    #         telefono VARCHAR(20),
    #         rol VARCHAR(50) NOT NULL,
    #         grupo VARCHAR(100),
    #         activo BOOLEAN DEFAULT TRUE,
    #         password_hash VARCHAR(255) NOT NULL,
    #         creado_en TIMESTAMP DEFAULT NOW(),
    #         actualizado_en TIMESTAMP DEFAULT NOW()
    #     );
    # """)

    # cur.execute("""
    #       INSERT INTO admin_usuario (username, nombre_completo, email, telefono, rol, grupo, password_hash)
    # VALUES
    #     ('admin', 'Administrador Principal', 'admin@sistema.com', '+1234567890', 'ADMINISTRADOR', 'SISTEMAS', '$2b$12$example_hash'),
    #     ('moderador1', 'Juan Pérez', 'juan@sistema.com', '+1234567891', 'MODERADOR', 'OPERACIONES', '$2b$12$example_hash2')
    # ON CONFLICT (username) DO NOTHING;
    # """)

    # # Tabla: manager
    # cur.execute("""
    # CREATE TABLE IF NOT EXISTS manager (
    #     id SERIAL PRIMARY KEY,
    #     nombre VARCHAR(100),
    #     email VARCHAR(100),
    #     telefono VARCHAR(20),
    #     total_diamantes_creadores INTEGER,
    #     total_creadores INTEGER,
    #     creado_en TIMESTAMP DEFAULT NOW()
    # );
    # """)
    #
    # # Tabla: admin_usuario
    # cur.execute("""
    # CREATE TABLE IF NOT EXISTS admin_usuario (
    #     id SERIAL PRIMARY KEY,
    #     username VARCHAR(50) UNIQUE NOT NULL,
    #     password_hash TEXT NOT NULL,
    #     rol VARCHAR(20) NOT NULL,
    #     nombre_completo VARCHAR(100),
    #     email VARCHAR(100),
    #     telefono VARCHAR(20),
    #     grupo VARCHAR(50),
    #     activo BOOLEAN DEFAULT TRUE,
    #     creado_en TIMESTAMP DEFAULT NOW()
    # );
    # """)
    #
    # # Tabla: creadores_activos
    # cur.execute("""
    # CREATE TABLE IF NOT EXISTS creadores_activos (
    #     id SERIAL PRIMARY KEY,
    #     creadores_id INTEGER REFERENCES creadores(id) ON DELETE CASCADE,
    #     manager_id INTEGER REFERENCES manager(id),
    #     fecha_ingreso TIMESTAMP NOT NULL,
    #     estado_actual VARCHAR(50),
    #     motivo_estado TEXT,
    #     grupo_asignado VARCHAR(100),
    #     diamantes_antes_agencia INTEGER,
    #     total_diamantes INTEGER,
    #     total_seguidores INTEGER,
    #     total_dias_emision INTEGER,
    #     total_minutos_emision INTEGER,
    #     numero_partidas INTEGER,
    #     meta_diamantes INTEGER,
    #     plazo_meses_graduacion INTEGER,
    #     estado_graduacion VARCHAR(50),
    #     dias_lives TEXT,
    #     tiempo_disponible VARCHAR(100),
    #     rango_creador VARCHAR(20),
    #     observaciones TEXT,
    #     creado_en TIMESTAMP DEFAULT NOW(),
    #     ultima_actualizacion TIMESTAMP DEFAULT NOW()
    # );
    # """)
    #
    # # Tabla: seguimiento_creador
    # cur.execute("""
    # CREATE TABLE IF NOT EXISTS seguimiento_creador (
    #     id SERIAL PRIMARY KEY,
    #     creadores_id INTEGER REFERENCES creadores(id) ON DELETE CASCADE,
    #     manager_id INTEGER REFERENCES manager(id),
    #     actividad_reciente TEXT,
    #     incidencias TEXT,
    #     retroalimentacion TEXT,
    #     avances TEXT,
    #     estrategias_mejora TEXT,
    #     diamantes_acumulados INTEGER,
    #     promedio_diamantes_semana NUMERIC(6,2),
    #     lives_ultima_semana INTEGER,
    #     ultimos_viewers_promedio INTEGER,
    #     engagement_ultima_semana NUMERIC(5,2),
    #     estado_actual VARCHAR(50),
    #     fecha_proxima_revision TIMESTAMP,
    #     ultima_revision TIMESTAMP DEFAULT NOW(),
    #     creado_en TIMESTAMP DEFAULT NOW()
    # );
    # """)
    #
    # # Tabla: lives_creadores
    # cur.execute("""
    # CREATE TABLE IF NOT EXISTS lives_creadores (
    #     id SERIAL PRIMARY KEY,
    #     creadores_id INTEGER REFERENCES creadores(id) ON DELETE CASCADE,
    #     fecha TIMESTAMP,
    #     duracion_minutos INTEGER,
    #     tipo_live VARCHAR(50),
    #     impresiones INTEGER,
    #     audiencia_alcanzada INTEGER,
    #     visualizaciones INTEGER,
    #     espectadores_unicos INTEGER,
    #     regalos_recibidos INTEGER,
    #     donadores INTEGER,
    #     diamantes_obtenidos INTEGER,
    #     promedio_duracion_espectador NUMERIC(5,2),
    #     tasa_clic_promedio NUMERIC(5,2),
    #     observaciones TEXT,
    #     creado_en TIMESTAMP DEFAULT NOW()
    # );
    # """)
    #
    # # Tabla: mensajes
    # cur.execute("""
    # CREATE TABLE IF NOT EXISTS mensajes (
    #     id SERIAL PRIMARY KEY,
    #     usuario_id INTEGER NOT NULL REFERENCES creadores(id) ON DELETE CASCADE,
    #     contenido TEXT,
    #     tipo VARCHAR(10),
    #     es_audio BOOLEAN DEFAULT FALSE,
    #     fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    # );
    # """)
    #
    # # Crear tabla de google_tokens
    # cur.execute("""
    #  CREATE TABLE IF NOT EXISTS google_tokens (
    #  id SERIAL PRIMARY KEY,
    #  nombre TEXT UNIQUE,                          -- por ejemplo: 'calendar'
    #  token_json JSONB NOT NULL,                   -- Mejor que TEXT
    #  actualizado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    #  );
    #  """)


    conn.commit()
    cur.close()
    conn.close()
    print("✅ Tablas extra creadas exitosamente.")



def add_campo_siguiendo():
    conn = None
    cur = None
    try:
        conn = psycopg2.connect(EXTERNAL_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            ALTER TABLE perfil_creador
            ADD COLUMN IF NOT EXISTS siguiendo INTEGER DEFAULT 0;
        """)
        conn.commit()
        print("✅ Campo 'siguiendo' (INTEGER DEFAULT 0) agregado a perfil_creador correctamente.")
    except Exception as e:
        print(f"❌ Error al agregar campo 'siguiendo' a perfil_creador:", e)
        if conn:
            conn.rollback()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def add_campo_foto_url_mini():
    conn = None
    cur = None
    try:
        conn = psycopg2.connect(EXTERNAL_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            ALTER TABLE creadores
            ADD COLUMN IF NOT EXISTS foto_url_mini TEXT;
        """)
        conn.commit()
        print("✅ Campo 'foto_url_mini' (TEXT) agregado a creadores correctamente.")
    except Exception as e:
        print(f"❌ Error al agregar campo 'foto_url_mini' a creadores:", e)
        if conn:
            conn.rollback()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    # agregar_columnas_extra()
    # cambiar_puntaje_a_numeric()
    # agregar_columna_puntaje()
    # cambiar_tipo_potencial()
    # eliminar_campo()
    # migrar_datos()
    # crear_tablas()
    crear_tablas_extra()
    # add_campo_foto_url_mini()