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

        cur.execute("SELECT id FROM usuarios WHERE telefono = %s", (telefono,))
        usuario = cur.fetchone()

        if not usuario:
            cur.execute("INSERT INTO usuarios (telefono) VALUES (%s) RETURNING id", (telefono,))
            usuario_id = cur.fetchone()[0]
        else:
            usuario_id = usuario[0]

        cur.execute(
            "INSERT INTO mensajes (usuario_id, contenido, tipo, es_audio, fecha) VALUES (%s, %s, %s, %s, %s)",
            (usuario_id, texto, tipo, es_audio, datetime.now())
        )

        conn.commit()
        cur.close()
        conn.close()

        print("✅ Mensaje y usuario guardados correctamente.")

    except Exception as e:
        print("❌ Error al guardar mensaje:", e)

def actualizar_nombre_contacto(telefono, nuevo_nombre):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            UPDATE usuarios
            SET nombre = %s
            WHERE telefono = %s
        """, (nuevo_nombre, telefono))
        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ Nombre actualizado para {telefono}: {nuevo_nombre}")
        return True
    except Exception as e:
        print("❌ Error al actualizar nombre de contacto:", e)
        return False

def eliminar_mensajes(telefono):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM mensajes
            USING usuarios
            WHERE mensajes.usuario_id = usuarios.id
            AND usuarios.telefono = %s
        """, (telefono,))
        conn.commit()
        cur.close()
        conn.close()
        print(f"🗑️ Mensajes eliminados para {telefono}")
        return True
    except Exception as e:
        print("❌ Error al eliminar mensajes:", e)
        return False

def ver_mensajes(limit=10):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
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



def obtener_contactos():
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT telefono, nombre, creado_en FROM usuarios ORDER BY creado_en DESC")
        contactos = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"telefono": telefono, "nombre": nombre or "", "creado_en": creado_en.isoformat()}
            for telefono, nombre, creado_en in contactos
        ]
    except Exception as e:
        print("❌ Error al obtener contactos:", e)
        return []

def obtener_mensajes(telefono):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            SELECT m.contenido, m.tipo, m.fecha, m.es_audio
            FROM mensajes m
            JOIN usuarios u ON m.usuario_id = u.id
            WHERE u.telefono = %s
            ORDER BY m.fecha ASC
        """, (telefono,))
        mensajes = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {
                "contenido": contenido,
                "tipo": tipo,
                "fecha": fecha.isoformat(),
                "es_audio": es_audio
            }
            for contenido, tipo, fecha, es_audio in mensajes
        ]
    except Exception as e:
        print("❌ Error al obtener mensajes:", e)
        return []
