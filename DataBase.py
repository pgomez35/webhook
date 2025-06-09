import os
import psycopg2
from dotenv import load_dotenv
from datetime import datetime

# Cargar variables de entorno (incluye DATABASE_URL)
load_dotenv()

INTERNAL_DATABASE_URL = os.getenv("INTERNAL_DATABASE_URL")

EXTERNAL_DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")

def guardar_mensaje(telefono, texto, tipo="recibido", es_audio=False):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        # Verificar o insertar usuario
        cur.execute("SELECT 1 FROM usuarios WHERE telefono = %s", (telefono,))
        if cur.fetchone() is None:
            cur.execute("INSERT INTO usuarios (telefono) VALUES (%s)", (telefono,))

        # Insertar mensaje
        cur.execute("""
            INSERT INTO mensajes (telefono, contenido, tipo, es_audio, fecha)
            VALUES (%s, %s, %s, %s, %s)
        """, (telefono, texto, tipo, es_audio, datetime.now()))

        conn.commit()
        cur.close()
        conn.close()

        print("✅ Mensaje y usuario guardados correctamente.")

    except Exception as e:
        print("❌ Error al guardar mensaje:", e)



def ver_mensajes(limit=10):
    try:
        conn = psycopg2.connect(EXTERNAL_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            SELECT id, telefono, contenido, tipo, es_audio, fecha
            FROM mensajes
            ORDER BY fecha DESC
            LIMIT %s;
        """, (limit,))
        resultados = cur.fetchall()
        for fila in resultados:
            print(f"🟢 {fila}")
        cur.close()
        conn.close()
    except Exception as e:
        print("❌ Error al consultar mensajes:", e)


# def crear_tablas():
#     try:
#         conn = psycopg2.connect(EXTERNAL_DATABASE_URL)
#         cur = conn.cursor()

        # cur.execute("""
        #       drop TABLE mensajes;
        #       """)

        # # Crear tabla de usuarios
        # cur.execute("""
        # CREATE TABLE IF NOT EXISTS usuarios (
        #     id SERIAL PRIMARY KEY,
        #     telefono VARCHAR(20) UNIQUE NOT NULL,
        #     nombre VARCHAR(100),
        #     creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        # );
        # """)

        # Crear tabla de mensajes
        # cur.execute("""
        # CREATE TABLE IF NOT EXISTS mensajes (
        #     id SERIAL PRIMARY KEY,
        #     telefono VARCHAR(20) NOT NULL,
        #     contenido TEXT,
        #     tipo VARCHAR(10),  -- 'recibido' o 'enviado'
        #     es_audio BOOLEAN DEFAULT FALSE,
        #     fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        #     FOREIGN KEY (telefono) REFERENCES usuarios(telefono) ON DELETE CASCADE
        # );
        # """)

#         conn.commit()
#         print("✅ Tablas creadas correctamente.")
#
#         cur.close()
#         conn.close()
#
#     except Exception as e:
#         print("❌ Error al crear tablas:", e)
#
# if __name__ == "__main__":
#     crear_tablas()
