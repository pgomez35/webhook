import os
import psycopg2
from dotenv import load_dotenv
from datetime import datetime
import re
import gspread
from google.oauth2.service_account import Credentials
from schemas import ActualizacionContactoInfo

# Cargar variables de entorno (incluye DATABASE_URL)
load_dotenv()

INTERNAL_DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")

EXTERNAL_DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")

from typing import Optional
import psycopg2

from datetime import datetime, timedelta

def obtener_usuario_id_por_telefono(telefono: str):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        cur.execute("""
            SELECT id FROM usuarios WHERE telefono = %s
        """, (telefono,))

        resultado = cur.fetchone()
        cur.close()
        conn.close()

        return resultado[0] if resultado else None
    except Exception as e:
        print("❌ Error al obtener usuario_id:", e)
        return None



from datetime import datetime, timedelta


def paso_limite_24h(usuario_id: int):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        cur.execute("""
            SELECT fecha FROM mensajes
            WHERE usuario_id = %s AND tipo = 'recibido'
            ORDER BY fecha DESC
            LIMIT 1
        """, (usuario_id,))

        resultado = cur.fetchone()
        cur.close()
        conn.close()

        if not resultado:
            # Si no hay mensajes recibidos, se considera fuera del límite
            return True

        ultima_fecha = resultado[0]
        ahora = datetime.utcnow()
        diferencia = ahora - ultima_fecha

        return diferencia > timedelta(hours=24)
    except Exception as e:
        print("❌ Error verificando límite 24h:", e)
        return True  # Por seguridad, asumir que sí pasó el límite



def actualizar_contacto_info_db(telefono: str, datos: ActualizacionContactoInfo):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        updates = []
        valores = []

        if datos.estado_whatsapp:
            updates.append("estado_whatsapp = %s")
            valores.append(datos.estado_whatsapp)
        if datos.fecha_entrevista:
            updates.append("fecha_entrevista = %s")
            valores.append(datos.fecha_entrevista)
        if datos.entrevista:
            updates.append("entrevista = %s")
            valores.append(datos.entrevista)

        if not updates:
            return {"status": "error", "mensaje": "No se proporcionaron campos para actualizar."}

        valores.append(telefono)
        query = f"""
            UPDATE contacto_info
            SET {', '.join(updates)}
            WHERE telefono = %s
        """
        cur.execute(query, tuple(valores))
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "ok", "mensaje": "Contacto actualizado correctamente"}

    except Exception as e:
        print("❌ Error actualizando contacto_info:", e)
        return {"status": "error", "mensaje": str(e)}

def obtener_contactos_db(perfil: Optional[str] = None):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        if perfil:
            cur.execute("""
                SELECT telefono, usuario, perfil, estado_whatsapp, entrevista, fecha_entrevista
                FROM contacto_info
                WHERE perfil = %s
            """, (perfil.upper(),))
        else:
            cur.execute("""
                SELECT telefono, usuario, perfil, estado_whatsapp, entrevista, fecha_entrevista
                FROM contacto_info
            """)

        contactos = [
            {
                "telefono": row[0],
                "usuario": row[1],
                "perfil": row[2],
                "estado_whatsapp": row[3],
                "entrevista": row[4],
                "fecha_entrevista": row[5]
            }
            for row in cur.fetchall()
        ]

        cur.close()
        conn.close()
        return contactos

    except Exception as e:
        print("❌ Error obteniendo contactos:", e)
        return {"status": "error", "mensaje": str(e)}

def guardar_contactos(contactos):
    conn = psycopg2.connect(INTERNAL_DATABASE_URL)
    cur = conn.cursor()

    for c in contactos:
        # Insertar en aspirantes
        cur.execute("""
        INSERT INTO aspirantes (usuario, nickname, telefono, email, motivo_no_apto, medio_contacto, mensaje_enviado, tipo_solicitud)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """, (
            c["usuario"], c["nickname"], c["telefono"], c["email"], c["motivo_no_apto"],
            c["contacto"], c["respuesta_creador"], c["tipo_solicitud"]
        ))
        aspirante_id = cur.fetchone()[0]

        # Insertar en perfil_aspirante
        cur.execute("""
        INSERT INTO perfil_aspirante (aspirante_id, clasificacion_inicial, fecha_incorporacion)
        VALUES (%s, %s, NOW())
        """, (aspirante_id, c["perfil"]))

        # Insertar en evaluacion_inicial
        try:
            seguidores = int(c["seguidores"]) if c["seguidores"].isdigit() else 0
            likes = int(c["likes"]) if c["likes"].isdigit() else 0
            videos = int(c["videos"]) if c["videos"].isdigit() else 0
            duracion = int(c["duracion_emisiones"]) if c["duracion_emisiones"].isdigit() else 0
            dias = int(c["dias_emisiones"]) if c["dias_emisiones"].isdigit() else 0
        except:
            seguidores = likes = videos = duracion = dias = 0

        cur.execute("""
        INSERT INTO evaluacion_inicial (
            aspirante_id, seguidores, likes, cantidad_videos,
            duracion_emisiones, dias_emisiones
        ) VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            aspirante_id, seguidores, likes, videos, duracion, dias
        ))

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Contactos insertados correctamente.")

def guardar_contactos_(contactos):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        for c in contactos:
            # Saltar si no hay teléfono
            if not c["telefono"]:
                print(f"⚠️ Contacto sin teléfono: {c['usuario']} - omitido")
                continue

            # Insertar en tabla usuarios
            cur.execute("SELECT id FROM usuarios WHERE telefono = %s", (c["telefono"],))
            usuario = cur.fetchone()

            if not usuario:
                cur.execute(
                    "INSERT INTO usuarios (telefono, nombre) VALUES (%s, %s) RETURNING id",
                    (c["telefono"], c["usuario"])
                )
                usuario_id = cur.fetchone()[0]
            else:
                usuario_id = usuario[0]

            # Insertar o actualizar en contacto_info
            cur.execute("SELECT 1 FROM contacto_info WHERE usuario_id = %s", (usuario_id,))
            existe = cur.fetchone()

            if existe:
                cur.execute("""
                    UPDATE contacto_info SET
                        telefono = %s,
                        usuario = %s,
                        disponibilidad = %s,
                        contacto = %s,
                        respuesta_creador = %s,
                        perfil = %s,
                        entrevista = %s,
                        nickname = %s
                    WHERE usuario_id = %s
                """, (
                    c["telefono"], c["usuario"], c["disponibilidad"], c["contacto"],
                    c["respuesta_creador"], c["perfil"], c["entrevista"], c["nickname"],
                    usuario_id
                ))
            else:
                cur.execute("""
                    INSERT INTO contacto_info (
                        usuario_id, telefono, usuario, disponibilidad, contacto,
                        respuesta_creador, perfil, entrevista, nickname
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    usuario_id, c["telefono"], c["usuario"], c["disponibilidad"],
                    c["contacto"], c["respuesta_creador"], c["perfil"],
                    c["entrevista"], c["nickname"]
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