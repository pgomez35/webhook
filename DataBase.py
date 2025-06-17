import os
import psycopg2
from dotenv import load_dotenv
from datetime import datetime
import re
import gspread
from google.oauth2.service_account import Credentials

# Cargar variables de entorno (incluye DATABASE_URL)
load_dotenv()

INTERNAL_DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")

EXTERNAL_DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")

def guardar_contactos(contactos):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        for c in contactos:
            # Insertar en tabla usuarios
            cur.execute("SELECT id FROM usuarios WHERE telefono = %s", (c["telefono"],))
            usuario = cur.fetchone()
            if not usuario:
                cur.execute("INSERT INTO usuarios (telefono, nombre) VALUES (%s, %s) RETURNING id", (c["telefono"], c["usuario"]))
                usuario_id = cur.fetchone()[0]
            else:
                usuario_id = usuario[0]

            # Insertar o actualizar contacto_info
            cur.execute("SELECT 1 FROM contacto_info WHERE usuario_id = %s", (usuario_id,))
            existe = cur.fetchone()

            if existe:
                cur.execute("""
                    UPDATE contacto_info SET
                        disponibilidad = %s,
                        contacto = %s,
                        respuesta_creador = %s,
                        perfil = %s,
                        entrevista = %s,
                        nickname = %s
                    WHERE usuario_id = %s
                """, (
                    c["disponibilidad"], c["contacto"], c["respuesta_creador"],
                    c["perfil"], c["entrevista"], c["nickname"], usuario_id
                ))
            else:
                cur.execute("""
                    INSERT INTO contacto_info (
                        usuario_id, disponibilidad, contacto, respuesta_creador,
                        perfil, entrevista, nickname
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    usuario_id, c["disponibilidad"], c["contacto"], c["respuesta_creador"],
                    c["perfil"], c["entrevista"], c["nickname"]
                ))

        conn.commit()
        cur.close()
        conn.close()
        print("✅ Contactos guardados exitosamente.")
    except Exception as e:
        print(f"❌ Error guardando contactos en base de datos: {e}")

def guardar_mensaje(telefono, texto, tipo="recibido", es_audio=False):
    try:
        # Si es un mensaje de audio, extrae solo el nombre del archivo
        if es_audio and texto.startswith("[Audio guardado:"):
            match = re.search(r"\[Audio guardado: (.+)\]", texto)
            if match:
                texto = match.group(1)  # Ej: "9998555913574750.ogg"

        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        # Buscar si ya existe el usuario
        cur.execute("SELECT id FROM usuarios WHERE telefono = %s", (telefono,))
        usuario = cur.fetchone()

        # Insertar usuario si no existe
        if not usuario:
            cur.execute("INSERT INTO usuarios (telefono) VALUES (%s) RETURNING id", (telefono,))
            usuario_id = cur.fetchone()[0]
        else:
            usuario_id = usuario[0]

        # Insertar mensaje
        cur.execute("""
            INSERT INTO mensajes (usuario_id, contenido, tipo, es_audio, fecha)
            VALUES (%s, %s, %s, %s, %s)
        """, (usuario_id, texto, tipo, es_audio, datetime.now()))

        conn.commit()
        cur.close()
        conn.close()

        print("✅ Mensaje y usuario guardados correctamente.")
    except Exception as e:
        print("❌ Error al guardar mensaje:", e)
# def guardar_mensaje(telefono, texto, tipo="recibido", es_audio=False):
#     try:
#         conn = psycopg2.connect(INTERNAL_DATABASE_URL)
#         cur = conn.cursor()
#
#         cur.execute("SELECT id FROM usuarios WHERE telefono = %s", (telefono,))
#         usuario = cur.fetchone()
#
#         if not usuario:
#             cur.execute("INSERT INTO usuarios (telefono) VALUES (%s) RETURNING id", (telefono,))
#             usuario_id = cur.fetchone()[0]
#         else:
#             usuario_id = usuario[0]
#
#         cur.execute(
#             "INSERT INTO mensajes (usuario_id, contenido, tipo, es_audio, fecha) VALUES (%s, %s, %s, %s, %s)",
#             (usuario_id, texto, tipo, es_audio, datetime.now())
#         )
#
#         conn.commit()
#         cur.close()
#         conn.close()
#
#         print("✅ Mensaje y usuario guardados correctamente.")
#
#     except Exception as e:
#         print("❌ Error al guardar mensaje:", e)

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


def obtener_ultimos_mensajes(limit=10):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            SELECT m.contenido, m.tipo, m.fecha, m.es_audio
            FROM mensajes m
            JOIN usuarios u ON m.usuario_id = u.id
            ORDER BY m.fecha ASC
            LIMIT %s;
            """, (limit,))
        resultados = cur.fetchall()
        for fila in resultados:
            print(f"🟢 {fila}")
        cur.close()
        conn.close()
    except Exception as e:
        print("❌ Error al consultar mensajes:", e)