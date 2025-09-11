import os
import psycopg2
from dotenv import load_dotenv
from datetime import datetime
import re
import gspread
from google.oauth2.service_account import Credentials
from schemas import ActualizacionContactoInfo
# Para hash de contraseñas (instalar con: pip install bcrypt)
try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    print("⚠️ bcrypt no instalado. Las contraseñas no se hashearán correctamente.")

# Cargar variables de entorno (incluye DATABASE_URL)
load_dotenv()

INTERNAL_DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")

EXTERNAL_DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")

from DataBase import get_connection


def crear_agendamiento(data):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO agendamientos (
                titulo, descripcion, fecha_inicio, fecha_fin, 
                creador_id, responsable_id, 
                estado, link_meet, google_event_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
        """, (
            data['titulo'],
            data['descripcion'],
            data['fecha_inicio'],
            data['fecha_fin'],
            data.get('creador_id'),
            data.get('responsable_id'),
            data.get('estado', 'pendiente'),
            data.get('link_meet'),
            data.get('google_event_id')
        ))
        agendamiento_id = cur.fetchone()[0]
        conn.commit()
        return {"status": "ok", "id": agendamiento_id}
    except Exception as e:
        conn.rollback()
        return {"status": "error", "error": str(e)}
    finally:
        cur.close()
        conn.close()


def listar_agendamientos_filtros(estado=None, desde=None, hasta=None, responsable_id=None):
    conn = get_connection()
    cur = conn.cursor()
    try:
        query = """
            SELECT a.*, 
                   c.nickname, 
                   d.nombre_completo AS responsable 
            FROM agendamientos a
            LEFT JOIN creadores c ON a.creador_id = c.id
            LEFT JOIN admin_usuario d ON a.responsable_id = d.id
            WHERE 1=1
        """
        params = []

        if estado:
            query += " AND a.estado = %s"
            params.append(estado)

        if desde:
            query += " AND a.fecha_inicio >= %s"
            params.append(desde)

        if hasta:
            query += " AND a.fecha_fin <= %s"
            params.append(hasta)

        if responsable_id:
            query += " AND a.responsable_id = %s"
            params.append(responsable_id)

        query += " ORDER BY a.fecha_inicio DESC"

        cur.execute(query, params)
        resultados = cur.fetchall()
        columnas = [desc[0] for desc in cur.description]
        agendamientos = [dict(zip(columnas, fila)) for fila in resultados]

        return agendamientos

    except Exception as e:
        print("Error al listar agendamientos:", e)
        return []

    finally:
        cur.close()
        conn.close()


def listar_agendamientos():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT a.*, c.nickname,d.nombre_completo as responsable 
            FROM agendamientos a
            LEFT JOIN creadores c ON a.creador_id = c.id
            LEFT JOIN admin_usuario d ON a.responsable_id =d.id
            ORDER BY a.fecha_inicio DESC;
        """)
        rows = cur.fetchall()
        colnames = [desc[0] for desc in cur.description]
        agendamientos = [dict(zip(colnames, row)) for row in rows]
        return agendamientos
    finally:
        cur.close()
        conn.close()


def obtener_agendamiento(id):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT * FROM agendamientos WHERE id = %s;
        """, (id,))
        row = cur.fetchone()
        if row:
            colnames = [desc[0] for desc in cur.description]
            return dict(zip(colnames, row))
        return None
    finally:
        cur.close()
        conn.close()


def editar_agendamiento(id, data):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE agendamientos SET 
                titulo = %s,
                descripcion = %s,
                fecha_inicio = %s,
                fecha_fin = %s,
                creador_id = %s,
                responsable_id = %s,
                estado = %s,
                link_meet = %s,
                google_event_id = %s,
                actualizado_en = NOW()
            WHERE id = %s;
        """, (
            data['titulo'],
            data['descripcion'],
            data['fecha_inicio'],
            data['fecha_fin'],
            data['creador_id'],
            data['responsable_id'],
            data['estado'],
            data['link_meet'],
            data['google_event_id'],
            id
        ))
        conn.commit()
        return {"status": "ok"}
    except Exception as e:
        conn.rollback()
        return {"status": "error", "error": str(e)}
    finally:
        cur.close()
        conn.close()


def eliminar_agendamiento(id):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM agendamientos WHERE id = %s", (id,))
        conn.commit()
        return {"status": "ok"}
    except Exception as e:
        conn.rollback()
        return {"status": "error", "error": str(e)}
    finally:
        cur.close()
        conn.close()


def listar_creadores():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, nickname, usuario, telefono 
            FROM creadores
            ORDER BY creado_en DESC;
        """)
        rows = cur.fetchall()
        return [{"id": r[0], "nickname": r[1], "usuario": r[2], "telefono": r[3]} for r in rows]
    finally:
        cur.close()
        conn.close()


def crear_agendamiento_grupal(titulo, descripcion, fecha_inicio, fecha_fin, estado, responsable_id, lista_creadores):
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Crear evento principal
        cur.execute("""
            INSERT INTO agendamientos (titulo, descripcion, fecha_inicio, fecha_fin, estado, responsable_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id;
        """, (titulo, descripcion, fecha_inicio, fecha_fin, estado, responsable_id))

        agendamiento_id = cur.fetchone()[0]

        # Asociar los creadores
        for creador_id in lista_creadores:
            cur.execute("""
                INSERT INTO agendamiento_creadores (agendamiento_id, creador_id)
                VALUES (%s, %s)
            """, (agendamiento_id, creador_id))

        conn.commit()
        return agendamiento_id

    except Exception as e:
        print("Error al crear agendamiento grupal:", e)
        conn.rollback()
        return None

    finally:
        cur.close()
        conn.close()

def listar_agendamientos_grupales():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT a.id as agendamiento_id, a.titulo, a.descripcion, a.fecha_inicio, a.fecha_fin, 
                   a.estado, d.nombre_completo AS responsable,
                   c.id as creador_id, c.nickname
            FROM agendamientos a
            LEFT JOIN admin_usuario d ON a.responsable_id = d.id
            LEFT JOIN agendamiento_creadores ac ON a.id = ac.agendamiento_id
            LEFT JOIN creadores c ON ac.creador_id = c.id
            ORDER BY a.fecha_inicio DESC;
        """)
        resultados = cur.fetchall()
        columnas = [desc[0] for desc in cur.description]
        filas = [dict(zip(columnas, fila)) for fila in resultados]

        # Agrupar creadores por agendamiento
        agendamientos_dict = {}
        for fila in filas:
            ag_id = fila['agendamiento_id']
            if ag_id not in agendamientos_dict:
                agendamientos_dict[ag_id] = {
                    'agendamiento_id': ag_id,
                    'titulo': fila['titulo'],
                    'descripcion': fila['descripcion'],
                    'fecha_inicio': fila['fecha_inicio'],
                    'fecha_fin': fila['fecha_fin'],
                    'estado': fila['estado'],
                    'responsable': fila['responsable'],
                    'creadores': []
                }
            agendamientos_dict[ag_id]['creadores'].append({
                'id': fila['creador_id'],
                'nickname': fila['nickname']
            })

        return list(agendamientos_dict.values())

    except Exception as e:
        print("Error al listar agendamientos grupales:", e)
        return []

    finally:
        cur.close()
        conn.close()


