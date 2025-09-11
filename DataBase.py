import os
import psycopg2
from dotenv import load_dotenv
from datetime import datetime
import re
import gspread
from google.oauth2.service_account import Credentials
from gspread.worksheet import JSONResponse

from schemas import ActualizacionContactoInfo
from psycopg2.extras import RealDictCursor
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

from typing import Optional
import psycopg2

from datetime import datetime, timedelta


from datetime import datetime, timedelta


def get_connection():
    conn = psycopg2.connect(INTERNAL_DATABASE_URL)
    return conn

def limpiar_telefono(telefono):
    telefono = telefono.strip().replace("+", "").replace(" ", "")
    # Si el teléfono comienza con 93, cambia a 57
    if telefono.startswith("93"):
        telefono = "57" + telefono[2:]
    return telefono

def safe_int(val):
    if val is None or str(val).strip() == "":
        return None
    return int(val)

def guardar_contactos(contactos, nombre_archivo=None, hoja_excel=None, lote_carga=None, procesado_por=None,
                      observaciones=None):
    conn = psycopg2.connect(INTERNAL_DATABASE_URL)
    cur = conn.cursor()
    resultados = []
    filas_fallidas = []

    for c in contactos:
        try:
            usuario = c.get("usuario", "")
            nickname = c.get("nickname", "")
            email = c.get("email", "")
            telefono = limpiar_telefono(c.get("telefono", ""))
            disponibilidad = c.get("disponibilidad", "")
            perfil = c.get("perfil", "")
            motivo_no_apto = c.get("motivo_no_apto", "")
            contacto = c.get("contacto", "")
            respuesta_creador = c.get("respuesta_creador", "")
            entrevista = c.get("entrevista", "")
            tipo_solicitud = c.get("tipo_solicitud", "")
            razon_no_contacto = c.get("razon_no_contacto", "")
            seguidores = safe_int(c.get("seguidores", ""))
            cantidad_videos = safe_int(c.get("videos", ""))
            likes_totales = safe_int(c.get("likes", ""))
            duracion_emisiones = safe_int(c.get("Duracion_Emisiones", ""))
            dias_emisiones = safe_int(c.get("Dias_Emisiones", ""))
            fila_excel = c.get("fila_excel")
            apto = not bool(str(motivo_no_apto).strip())

            # 1. creadores
            cur.execute("SELECT id FROM creadores WHERE usuario = %s", (usuario,))
            creador_row = cur.fetchone()
            if creador_row:
                creador_id = creador_row[0]
                cur.execute("""
                    UPDATE creadores SET
                        nickname = %s,
                        email = %s,
                        telefono = %s,
                        actualizado_en = NOW()
                    WHERE id = %s
                """, (nickname, email, telefono, creador_id))
            else:
                cur.execute("""
                    INSERT INTO creadores (usuario, nickname, email, telefono, activo, creado_en, actualizado_en)
                    VALUES (%s, %s, %s, %s, TRUE, NOW(), NOW())
                    RETURNING id
                """, (usuario, nickname, email, telefono))
                creador_id = cur.fetchone()[0]

            # 2. perfil_creador
            cur.execute("SELECT id FROM perfil_creador WHERE creador_id = %s", (creador_id,))
            perfil_row = cur.fetchone()
            if perfil_row:
                cur.execute("""
                    UPDATE perfil_creador SET
                        perfil = %s,
                        seguidores = %s,
                        cantidad_videos = %s,
                        likes_totales = %s,
                        duracion_emisiones = %s,
                        dias_emisiones = %s,
                        actualizado_en = NOW()
                    WHERE creador_id = %s
                """, (
                perfil, seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones, creador_id))
            else:
                cur.execute("""
                    INSERT INTO perfil_creador (
                        creador_id, perfil,
                        seguidores, cantidad_videos, likes_totales,
                        duracion_emisiones, dias_emisiones,
                        creado_en, actualizado_en
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                    )
                """, (
                creador_id, perfil, seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones))

            # 3. cargue_creadores
            cur.execute("SELECT id FROM cargue_creadores WHERE usuario = %s AND hoja_excel = %s", (usuario, hoja_excel))
            cargue_row = cur.fetchone()
            if cargue_row:
                cargue_id = cargue_row[0]
                cur.execute("""
                    UPDATE cargue_creadores SET
                        nickname = %s,
                        email = %s,
                        telefono = %s,
                        disponibilidad = %s,
                        perfil = %s,
                        motivo_no_apto = %s,
                        contacto = %s,
                        respuesta_creador = %s,
                        entrevista = %s,
                        tipo_solicitud = %s,
                        razon_no_contacto = %s,
                        seguidores = %s,
                        cantidad_videos = %s,
                        likes_totales = %s,
                        duracion_emisiones = %s,
                        dias_emisiones = %s,
                        nombre_archivo = %s,
                        fila_excel = %s,
                        lote_carga = %s,
                        estado = %s,
                        procesado = %s,
                        procesado_por = %s,
                        creador_id = %s,
                        apto = %s,
                        observaciones = %s,
                        actualizado_en = NOW()
                    WHERE id = %s
                """, (
                    nickname, email, telefono, disponibilidad, perfil, motivo_no_apto,
                    contacto, respuesta_creador, entrevista, tipo_solicitud, razon_no_contacto,
                    seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones,
                    nombre_archivo, fila_excel, lote_carga, "Procesando", False, procesado_por,
                    creador_id, apto, observaciones, cargue_id
                ))
            else:
                cur.execute("""
                    INSERT INTO cargue_creadores (
                        usuario, nickname, email, telefono, disponibilidad, perfil, motivo_no_apto,
                        contacto, respuesta_creador, entrevista, tipo_solicitud, razon_no_contacto,
                        seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones,
                        nombre_archivo, hoja_excel, fila_excel, lote_carga,
                        estado, procesado, procesado_por, creador_id,
                        apto, observaciones, activo, creado_en, actualizado_en
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, TRUE, NOW(), NOW()
                    )
                """, (
                    usuario, nickname, email, telefono, disponibilidad, perfil, motivo_no_apto,
                    contacto, respuesta_creador, entrevista, tipo_solicitud, razon_no_contacto,
                    seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones,
                    nombre_archivo, hoja_excel, fila_excel, lote_carga,
                    "Procesando", False, procesado_por, creador_id,
                    apto, observaciones
                ))

            resultados.append({
                "fila": fila_excel,
                "usuario": usuario,
                "creador_id": creador_id
            })

        except Exception as err:
            conn.rollback()
            filas_fallidas.append({
                "fila": c.get("fila_excel"),
                "error": str(err),
                "contacto": c
            })

    conn.commit()
    cur.close()
    conn.close()
    print(f"✅ Contactos procesados. Filas exitosas: {len(resultados)}. Filas fallidas: {len(filas_fallidas)}")
    return {
        "exitosos": resultados,
        "fallidos": filas_fallidas
    }

# ------------------------------
def obtener_usuario_id_por_telefono(telefono: str):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        cur.execute("""
            SELECT id FROM creadores WHERE telefono = %s
        """, (telefono,))

        resultado = cur.fetchone()
        cur.close()
        conn.close()

        return resultado[0] if resultado else None
    except Exception as e:
        print("❌ Error al obtener usuario_id:", e)
        return None


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
            UPDATE creadores
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

def obtener_contactos_db(estado: Optional[str] = None):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        if estado:
            cur.execute("""
                SELECT a.usuario, a.nickname, a.nombre_real AS nombre, a.whatsapp as telefono, b.nombre AS estado
                FROM creadores a
                INNER JOIN estados_creador b ON a.estado_id = b.id
                WHERE whatsapp IS NOT NULL
                  AND whatsapp != ''
                  AND UPPER(b.nombre) = %s
                ORDER BY a.usuario ASC
            """, (estado.upper(),))
        else:
            cur.execute("""
                SELECT a.usuario, a.nickname, a.nombre_real AS nombre, a.whatsapp as telefono, b.nombre AS estado
                FROM creadores a
                INNER JOIN estados_creador b ON a.estado_id = b.id
                WHERE whatsapp IS NOT NULL
                  AND whatsapp != ''
                ORDER BY a.usuario ASC
            """)

        contactos = [
            {
                "usuario": row[0],
                "nickname": row[1],
                "nombre": row[2],
                "telefono": row[3],
                "estado": row[4]
            }
            for row in cur.fetchall()
        ]

        cur.close()
        conn.close()
        return contactos

    except Exception as e:
        print("❌ Error obteniendo contactos:", e)
        return {"status": "error", "mensaje": str(e)}


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
        cur.execute("SELECT id FROM creadores WHERE telefono = %s", (telefono,))
        usuario = cur.fetchone()

        # Insertar usuario si no existe
        if not usuario:
            cur.execute("INSERT INTO creadores (telefono) VALUES (%s) RETURNING id", (telefono,))
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

def actualizar_nombre_contacto(telefono, nuevo_nombre):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            UPDATE creadores
            SET nombre_real = %s
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
            USING creadores
            WHERE mensajes.usuario_id = creadores.id
            AND creadores.telefono = %s
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
        cur.execute("SELECT telefono, nombre, creado_en FROM creadores ORDER BY creado_en DESC")
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
            INNER JOIN creadores u ON m.usuario_id = u.id
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
            JOIN creadores u ON m.usuario_id = u.id
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


# ===============================
# UTILIDADES PARA CONTRASEÑAS
# ===============================

def hash_password(password: str) -> str:
    """Genera un hash seguro de la contraseña usando bcrypt"""
    if not BCRYPT_AVAILABLE:
        # Fallback básico (NO usar en producción)
        return password  # ⚠️ TEMPORAL - instalar bcrypt
    
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    password_hash = bcrypt.hashpw(password_bytes, salt)
    return password_hash.decode('utf-8')

def verify_password(password: str, hashed_password: str) -> bool:
    """Verifica si una contraseña coincide con su hash"""
    if not BCRYPT_AVAILABLE:
        # Fallback básico (NO usar en producción)
        return password == hashed_password  # ⚠️ TEMPORAL
    
    password_bytes = password.encode('utf-8')
    hashed_password_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_password_bytes)

# ===============================
# FUNCIONES PARA ADMIN_USUARIO
# ===============================

def obtener_todos_admin_usuarios():
    """Obtiene todos los usuarios administradores"""
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, username, nombre_completo, email, telefono, rol, grupo, activo, 
                   creado_en, actualizado_en
            FROM admin_usuario
            ORDER BY creado_en DESC
        """)
        
        usuarios = []
        for row in cur.fetchall():
            usuarios.append({
                "id": row[0],
                "username": row[1],
                "nombre_completo": row[2],
                "email": row[3],
                "telefono": row[4],
                "rol": row[5],
                "grupo": row[6],
                "activo": row[7],
                "creado_en": row[8].isoformat() if row[8] else None,
                "actualizado_en": row[9].isoformat() if row[9] else None
            })
        
        cur.close()
        conn.close()
        return usuarios
        
    except Exception as e:
        print("❌ Error al obtener usuarios administradores:", e)
        return []


def obtener_todos_responsables_agendas():
    """Obtiene todos los usuarios responsables de agendas"""
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        cur.execute("""
            SELECT id, username, nombre_completo, email, telefono, rol, grupo, activo, 
                   creado_en, actualizado_en
            FROM admin_usuario
            ORDER BY creado_en DESC
        """)

        usuarios = []
        for row in cur.fetchall():
            usuarios.append({
                "id": row[0],
                "username": row[1],
                "nombre_completo": row[2],
                "email": row[3],
                "telefono": row[4],
                "rol": row[5],
                "grupo": row[6],
                "activo": row[7],
                "creado_en": row[8].isoformat() if row[8] else None,
                "actualizado_en": row[9].isoformat() if row[9] else None
            })

        cur.close()
        conn.close()
        return usuarios

    except Exception as e:
        print("❌ Error al obtener usuarios administradores:", e)
        return []

# def crear_admin_usuario_V0(datos):
#     """Crea un nuevo usuario administrador."""
#
#     # Validar campos requeridos antes de abrir la conexión
#     requeridos = ["username", "nombre_completo", "email", "rol", "password_hash"]
#     faltantes = [campo for campo in requeridos if not datos.get(campo)]
#     if faltantes:
#         return {"status": "error", "mensaje": f"Faltan campos obligatorios: {', '.join(faltantes)}"}
#
#     # Normalizar email y username
#     username = datos["username"].strip().lower()
#     email = datos["email"].strip().lower()
#
#     try:
#         import psycopg2
#         with psycopg2.connect(INTERNAL_DATABASE_URL) as conn:
#             with conn.cursor() as cur:
#                 # Verificar si el username ya existe
#                 cur.execute("SELECT id FROM admin_usuario WHERE username = %s", (username,))
#                 if cur.fetchone():
#                     return {"status": "error", "mensaje": "El username ya existe"}
#
#                 # Verificar si el email ya existe
#                 cur.execute("SELECT id FROM admin_usuario WHERE email = %s", (email,))
#                 if cur.fetchone():
#                     return {"status": "error", "mensaje": "El email ya existe"}
#
#                 # Hash de la contraseña (debe llegar como texto plano)
#                 password = datos.get("password_hash", "")
#                 if not password:
#                     return {"status": "error", "mensaje": "La contraseña no puede estar vacía"}
#                 password_hash = hash_password(password)
#
#                 # Insertar nuevo usuario
#                 cur.execute("""
#                     INSERT INTO admin_usuario (
#                         username, nombre_completo, email, telefono, rol, grupo, activo,
#                         password_hash, creado_en, actualizado_en
#                     ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
#                     RETURNING id
#                 """, (
#                     username,
#                     datos.get("nombre_completo").strip(),
#                     email,
#                     datos.get("telefono"),
#                     datos.get("rol"),
#                     datos.get("grupo"),
#                     datos.get("activo", True),
#                     password_hash
#                 ))
#                 usuario_id = cur.fetchone()[0]
#                 conn.commit()
#                 return {"status": "ok", "mensaje": "Usuario creado correctamente", "id": usuario_id}
#
#     except Exception as e:
#         print("❌ Error al crear usuario administrador:", e)
#         return {"status": "error", "mensaje": f"Error en la base de datos: {str(e)}"}


# def crear_admin_usuario(datos):
#     # Si datos es un modelo Pydantic, conviértelo a dict (opcional, pero recomendado para compatibilidad)
#     if hasattr(datos, "dict"):
#         datos = datos.dict()
#
#     username = datos["username"].strip().lower()
#     email = datos.get("email", "").strip().lower()
#     password = datos["password"]
#     nombre_completo = datos.get("nombre_completo")
#     telefono = datos.get("telefono")
#     rol = datos["rol"]
#     grupo = datos.get("grupo")
#     activo = datos.get("activo", True)
#
#     # Si tienes tu función hash_password importada
#     password_hash = hash_password(password)
#
#     try:
#         with psycopg2.connect(INTERNAL_DATABASE_URL) as conn:
#             with conn.cursor() as cur:
#                 cur.execute("SELECT 1 FROM admin_usuario WHERE username=%s", (username,))
#                 if cur.fetchone():
#                     return JSONResponse(status_code=409, content={"status": "error", "mensaje": "El username ya existe"})
#
#                 cur.execute("SELECT 1 FROM admin_usuario WHERE email=%s", (email,))
#                 if email and cur.fetchone():
#                     return JSONResponse(status_code=409, content={"status": "error", "mensaje": "El email ya existe"})
#
#                 cur.execute("""
#                     INSERT INTO admin_usuario (
#                         username, nombre_completo, email, telefono, rol, grupo, activo,
#                         password_hash, creado_en, actualizado_en
#                     ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
#                     RETURNING id, creado_en, actualizado_en
#                 """, (
#                     username, nombre_completo, email, telefono, rol, grupo, activo, password_hash
#                 ))
#                 result = cur.fetchone()
#                 usuario_id, creado_en, actualizado_en = result
#                 conn.commit()
#
#                 # Respuesta según tu esquema de AdminUsuarioResponse
#                 return {
#                     "id": usuario_id,
#                     "username": username,
#                     "nombre_completo": nombre_completo,
#                     "email": email,
#                     "telefono": telefono,
#                     "rol": rol,
#                     "grupo": grupo,
#                     "activo": activo,
#                     "creado_en": creado_en.isoformat() if creado_en else None,
#                     "actualizado_en": actualizado_en.isoformat() if actualizado_en else None,
#                 }
#     except Exception as e:
#         print("❌ Error al crear usuario administrador:", e)
#         return JSONResponse(status_code=500, content={"status": "error", "mensaje": str(e)})

import secrets
from fastapi.responses import JSONResponse

def crear_admin_usuario(datos):
    """Crea un nuevo usuario administrador."""

    # Normalizar datos si vienen de un modelo Pydantic
    if hasattr(datos, "dict"):
        datos = datos.dict()

    # Validar campos requeridos antes de abrir la conexión
    requeridos = ["username", "nombre_completo", "email", "rol"]
    faltantes = [campo for campo in requeridos if not datos.get(campo)]
    if faltantes:
        return {"status": "error", "mensaje": f"Faltan campos obligatorios: {', '.join(faltantes)}"}

    # Normalizar email y username
    username = datos["username"].strip().lower()
    email = datos["email"].strip().lower()
    nombre_completo = datos.get("nombre_completo")
    telefono = datos.get("telefono")
    rol = datos["rol"]
    grupo = datos.get("grupo")
    activo = datos.get("activo", True)

    # Generar contraseña fácil si no viene
    password = datos.get("password")
    if not password:
        password = f"{username}123"  # 👈 fácil de recordar

    # Hashear contraseña
    password_hash = hash_password(password)

    try:
        import psycopg2
        with psycopg2.connect(INTERNAL_DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # Verificar duplicados
                cur.execute("SELECT 1 FROM admin_usuario WHERE username=%s", (username,))
                if cur.fetchone():
                    return JSONResponse(
                        status_code=409,
                        content={"status": "error", "mensaje": "El username ya existe"}
                    )

                cur.execute("SELECT 1 FROM admin_usuario WHERE email=%s", (email,))
                if email and cur.fetchone():
                    return JSONResponse(
                        status_code=409,
                        content={"status": "error", "mensaje": "El email ya existe"}
                    )

                # Insertar usuario
                cur.execute("""
                    INSERT INTO admin_usuario (
                        username, nombre_completo, email, telefono, rol, grupo, activo,
                        password_hash, creado_en, actualizado_en
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    RETURNING id, creado_en, actualizado_en
                """, (
                    username, nombre_completo, email, telefono, rol, grupo, activo, password_hash
                ))

                usuario_id, creado_en, actualizado_en = cur.fetchone()
                conn.commit()

                return {
                    "id": usuario_id,
                    "username": username,
                    "nombre_completo": nombre_completo,
                    "email": email,
                    "telefono": telefono,
                    "rol": rol,
                    "grupo": grupo,
                    "activo": activo,
                    "creado_en": creado_en.isoformat() if creado_en else None,
                    "actualizado_en": actualizado_en.isoformat() if actualizado_en else None,
                    "password_inicial": password  # 👈 se devuelve para el admin
                }

    except Exception as e:
        print("❌ Error al crear usuario administrador:", e)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "mensaje": str(e)}
        )


def obtener_admin_usuario_por_id(usuario_id):
    """Obtiene un usuario administrador por ID"""
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, username, nombre_completo, email, telefono, rol, grupo, activo,
                   creado_en, actualizado_en
            FROM admin_usuario
            WHERE id = %s
        """, (usuario_id,))
        
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if row:
            return {
                "id": row[0],
                "username": row[1],
                "nombre_completo": row[2],
                "email": row[3],
                "telefono": row[4],
                "rol": row[5],
                "grupo": row[6],
                "activo": row[7],
                "creado_en": row[8].isoformat() if row[8] else None,
                "actualizado_en": row[9].isoformat() if row[9] else None
            }
        return None
        
    except Exception as e:
        print("❌ Error al obtener usuario administrador:", e)
        return None

def actualizar_admin_usuario(usuario_id, datos):
    """Actualiza un usuario administrador y retorna los datos actualizados"""
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        # Verificar si el usuario existe
        cur.execute("SELECT id FROM admin_usuario WHERE id = %s", (usuario_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            # En vez de devolver dict, lanza excepción en el endpoint
            return None

        # Verificar username único (excluyendo el usuario actual)
        if datos.get("username"):
            cur.execute(
                "SELECT id FROM admin_usuario WHERE username = %s AND id != %s",
                (datos.get("username"), usuario_id)
            )
            if cur.fetchone():
                cur.close()
                conn.close()
                raise ValueError("El username ya existe")

        # Verificar email único (excluyendo el usuario actual)
        if datos.get("email"):
            cur.execute(
                "SELECT id FROM admin_usuario WHERE email = %s AND id != %s",
                (datos.get("email"), usuario_id)
            )
            if cur.fetchone():
                cur.close()
                conn.close()
                raise ValueError("El email ya existe")

        # Construir query de actualización dinámicamente
        updates = []
        valores = []

        campos_permitidos = ["username", "nombre_completo", "email", "telefono", "rol", "grupo", "activo"]
        for campo in campos_permitidos:
            if campo in datos:
                updates.append(f"{campo} = %s")
                valores.append(datos[campo])

        if not updates:
            cur.close()
            conn.close()
            raise ValueError("No se proporcionaron campos para actualizar")

        updates.append("actualizado_en = NOW()")
        valores.append(usuario_id)

        query = f"UPDATE admin_usuario SET {', '.join(updates)} WHERE id = %s"
        cur.execute(query, tuple(valores))
        conn.commit()

        # Obtener los datos actualizados
        cur.execute(
            "SELECT id, username, rol, nombre_completo, email, telefono, grupo, activo FROM admin_usuario WHERE id = %s",
            (usuario_id,)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return None

        # Arma el dict que espera tu modelo de respuesta
        return {
            "id": row[0],
            "username": row[1],
            "rol": row[2],
            "nombre_completo": row[3],
            "email": row[4],
            "telefono": row[5],
            "grupo": row[6],
            "activo": row[7]
        }

    except ValueError as ve:
        # Lanza errores de validación para el endpoint
        raise ve
    except Exception as e:
        print("❌ Error al actualizar usuario administrador:", e)
        raise e


# def actualizar_admin_usuario(usuario_id, datos):
#     """Actualiza un usuario administrador"""
#     try:
#         conn = psycopg2.connect(INTERNAL_DATABASE_URL)
#         cur = conn.cursor()
#
#         # Verificar si el usuario existe
#         cur.execute("SELECT id FROM admin_usuario WHERE id = %s", (usuario_id,))
#         if not cur.fetchone():
#             cur.close()
#             conn.close()
#             return {"status": "error", "mensaje": "Usuario no encontrado"}
#
#         # Verificar username único (excluyendo el usuario actual)
#         if datos.get("username"):
#             cur.execute(
#                 "SELECT id FROM admin_usuario WHERE username = %s AND id != %s",
#                 (datos.get("username"), usuario_id)
#             )
#             if cur.fetchone():
#                 cur.close()
#                 conn.close()
#                 return {"status": "error", "mensaje": "El username ya existe"}
#
#         # Verificar email único (excluyendo el usuario actual)
#         if datos.get("email"):
#             cur.execute(
#                 "SELECT id FROM admin_usuario WHERE email = %s AND id != %s",
#                 (datos.get("email"), usuario_id)
#             )
#             if cur.fetchone():
#                 cur.close()
#                 conn.close()
#                 return {"status": "error", "mensaje": "El email ya existe"}
#
#         # Construir query de actualización dinámicamente
#         updates = []
#         valores = []
#
#         campos_permitidos = ["username", "nombre_completo", "email", "telefono", "rol", "grupo", "activo"]
#         for campo in campos_permitidos:
#             if campo in datos:
#                 updates.append(f"{campo} = %s")
#                 valores.append(datos[campo])
#
#         if not updates:
#             cur.close()
#             conn.close()
#             return {"status": "error", "mensaje": "No se proporcionaron campos para actualizar"}
#
#         updates.append("actualizado_en = NOW()")
#         valores.append(usuario_id)
#
#         query = f"UPDATE admin_usuario SET {', '.join(updates)} WHERE id = %s"
#         cur.execute(query, tuple(valores))
#
#         conn.commit()
#         cur.close()
#         conn.close()
#
#         return {"status": "ok", "mensaje": "Usuario actualizado correctamente"}
#
#     except Exception as e:
#         print("❌ Error al actualizar usuario administrador:", e)
#         return {"status": "error", "mensaje": str(e)}


def eliminar_admin_usuario(usuario_id):
    """Elimina un usuario administrador"""
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        
        # Verificar si el usuario existe
        cur.execute("SELECT id FROM admin_usuario WHERE id = %s", (usuario_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return {"status": "error", "mensaje": "Usuario no encontrado"}
        
        cur.execute("DELETE FROM admin_usuario WHERE id = %s", (usuario_id,))
        conn.commit()
        cur.close()
        conn.close()
        
        return {"status": "ok", "mensaje": "Usuario eliminado correctamente"}
        
    except Exception as e:
        print("❌ Error al eliminar usuario administrador:", e)
        return {"status": "error", "mensaje": str(e)}


def cambiar_estado_admin_usuario(usuario_id, activo):
    """Cambia el estado activo/inactivo de un usuario administrador"""
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        
        # Verificar si el usuario existe
        cur.execute("SELECT id FROM admin_usuario WHERE id = %s", (usuario_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return {"status": "error", "mensaje": "Usuario no encontrado"}
        
        cur.execute("""
            UPDATE admin_usuario 
            SET activo = %s, actualizado_en = NOW() 
            WHERE id = %s
        """, (activo, usuario_id))
        
        conn.commit()
        cur.close()
        conn.close()
        
        estado_texto = "activado" if activo else "desactivado"
        return {"status": "ok", "mensaje": f"Usuario {estado_texto} correctamente"}
        
    except Exception as e:
        print("❌ Error al cambiar estado del usuario administrador:", e)
        return {"status": "error", "mensaje": str(e)}


def obtener_admin_usuario_por_username(username):
    """Obtiene un usuario administrador por username (útil para autenticación)"""
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, username, nombre_completo, email, telefono, rol, grupo, activo,
                   password_hash, creado_en, actualizado_en
            FROM admin_usuario
            WHERE username = %s
        """, (username,))
        
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if row:
            return {
                "id": row[0],
                "username": row[1],
                "nombre_completo": row[2],
                "email": row[3],
                "telefono": row[4],
                "rol": row[5],
                "grupo": row[6],
                "activo": row[7],
                "password_hash": row[8],
                "creado_en": row[9].isoformat() if row[9] else None,
                "actualizado_en": row[10].isoformat() if row[10] else None
            }
        return None
        
    except Exception as e:
        print("❌ Error al obtener usuario por username:", e)
        return None

def es_admin(usuario_actual: dict):
    # Asegúrate de que 'rol' esté en el dict del usuario
    return usuario_actual.get("rol") == "admin"

def actualiza_password_usuario(user_id: int, nuevo_hash: str):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        # Siempre usa parámetros para evitar SQL Injection
        cur.execute(
            "UPDATE admin_usuario SET password_hash = %s WHERE id = %s",
            (nuevo_hash, user_id)
        )
        conn.commit()
        actualizado = cur.rowcount > 0  # True si se actualizó
        cur.close()
        conn.close()
        return actualizado
    except Exception as e:
        print(f"Error al actualizar contraseña: {e}")
        return False



def autenticar_admin_usuario(username, password):
    """Autentica un usuario administrador"""
    try:
        # Obtener usuario por username
        usuario = obtener_admin_usuario_por_username(username)
        
        if not usuario:
            return {"status": "error", "mensaje": "Usuario no encontrado"}
        
        if not usuario.get("activo"):
            return {"status": "error", "mensaje": "Usuario inactivo"}
        
        # Verificar contraseña
        if verify_password(password, usuario.get("password_hash", "")):
            # No retornar el password_hash en la respuesta
            usuario.pop("password_hash", None)
            return {"status": "ok", "usuario": usuario}
        else:
            return {"status": "error", "mensaje": "Contraseña incorrecta"}
            
    except Exception as e:
        print("❌ Error al autenticar usuario:", e)
        return {"status": "error", "mensaje": "Error en autenticación"}

def obtener_todos_perfiles_creador():
    """Obtiene todos los perfiles de creadores"""
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        cur.execute("""
            SELECT id, creador_id, perfil, biografia_actual as biografia, seguidores, cantidad_videos as videos, engagement_rate as engagement, clasificacion_actual as acciones
            FROM perfil_creador
            ORDER BY id DESC
        """)

        perfiles = []
        for row in cur.fetchall():
            perfiles.append({
                "id": row[0],
                "creador_id": row[1] or f"creator_{row[0]}",
                "perfil": row[2] or "Sin clasificar",
                "biografia": row[3] or "",
                "seguidores": row[4] or 0,
                "videos": row[5] or 0,
                "engagement": f"{row[6]*100:.2f}%" if row[6] is not None else "0%",
                "acciones": row[7] or "Pendiente"
            })

        cur.close()
        conn.close()
        return perfiles

    except Exception as e:
        print("❌ Error al obtener perfiles de creadores:", e)
        return []


def obtener_perfil_creador_por_id(perfil_id: int):
    """Obtiene un perfil de creador por ID"""
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        cur.execute("""
            SELECT id, creador_id, perfil, biografia_actual as biografia, seguidores, cantidad_videos as videos, engagement_rate as engagement, clasificacion_actual as acciones
            FROM perfil_creador
            WHERE id = %s
        """, (perfil_id,))

        row = cur.fetchone()
        if row:
            perfil = {
                "id": row[0],
                "creador_id": row[1] or f"creator_{row[0]}",
                "perfil": row[2] or "Sin clasificar",
                "biografia": row[3] or "",
                "seguidores": row[4] or 0,
                "videos": row[5] or 0,
                "engagement": f"{row[6]*100:.2f}%" if row[6] is not None else "0%",
                "acciones": row[7] or "Pendiente"
            }
        else:
            perfil = None

        cur.close()
        conn.close()
        return perfil

    except Exception as e:
        print("❌ Error al obtener perfil de creador:", e)
        return None


def crear_perfil_creador(perfil_data):
    """Crea un nuevo perfil de creador"""
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO perfil_creador (creador_id, perfil, biografia_actual, seguidores, cantidad_videos, engagement_rate, clasificacion_actual)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, creador_id, perfil, biografia_actual, seguidores, cantidad_videos, engagement_rate, clasificacion_actual
        """, (
            perfil_data["creador_id"],
            perfil_data["perfil"],
            perfil_data["biografia"],
            perfil_data["seguidores"],
            perfil_data["videos"],
            float(perfil_data["engagement"].strip('%')) / 100 if isinstance(perfil_data["engagement"], str) else perfil_data["engagement"],
            perfil_data["acciones"]
        ))

        row = cur.fetchone()
        perfil = {
            "id": row[0],
            "creador_id": row[1],
            "perfil": row[2],
            "biografia": row[3],
            "seguidores": row[4],
            "videos": row[5],
            "engagement": f"{row[6]*100:.2f}%",
            "acciones": row[7]
        }

        conn.commit()
        cur.close()
        conn.close()
        return perfil

    except Exception as e:
        print("❌ Error al crear perfil de creador:", e)
        return None


def actualizar_perfil_creador(perfil_id: int, perfil_data):
    """Actualiza un perfil de creador"""
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        cur.execute("""
            UPDATE perfil_creador 
            SET creador_id = %s, perfil = %s, biografia_actual = %s, seguidores = %s, 
                cantidad_videos = %s, engagement_rate = %s, clasificacion_actual = %s
            WHERE id = %s
            RETURNING id, creador_id, perfil, biografia_actual, seguidores, cantidad_videos, engagement_rate, clasificacion_actual
        """, (
            perfil_data["creador_id"],
            perfil_data["perfil"],
            perfil_data["biografia"],
            perfil_data["seguidores"],
            perfil_data["videos"],
            float(perfil_data["engagement"].strip('%')) / 100 if isinstance(perfil_data["engagement"], str) else perfil_data["engagement"],
            perfil_data["acciones"],
            perfil_id
        ))

        row = cur.fetchone()
        if row:
            perfil = {
                "id": row[0],
                "creador_id": row[1],
                "perfil": row[2],
                "biografia": row[3],
                "seguidores": row[4],
                "videos": row[5],
                "engagement": f"{row[6]*100:.2f}%",
                "acciones": row[7]
            }
        else:
            perfil = None

        conn.commit()
        cur.close()
        conn.close()
        return perfil

    except Exception as e:
        print("❌ Error al actualizar perfil de creador:", e)
        return None


def eliminar_perfil_creador(perfil_id: int):
    """Elimina un perfil de creador"""
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        cur.execute("DELETE FROM perfil_creador WHERE id = %s", (perfil_id,))
        affected_rows = cur.rowcount

        conn.commit()
        cur.close()
        conn.close()
        return affected_rows > 0

    except Exception as e:
        print("❌ Error al eliminar perfil de creador:", e)
        return False


# -----------------------------------
# -----------------------------------
def obtener_creadores():
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
                  SELECT 
                c.id, 
                c.usuario, 
                c.nickname, 
                c.nombre_real, 
                c.email,
                c.telefono,
                c.whatsapp,
                c.foto_url,
                c.verificado,
                c.activo,
                ec.nombre as estado_nombre,
                c.creado_en,
                c.actualizado_en
            FROM creadores c
            LEFT JOIN estados_creador ec ON c.estado_id = ec.id
            WHERE c.activo = TRUE
            ORDER BY c.actualizado_en DESC;
        """)
        datos = cur.fetchall()
        columnas = [desc[0] for desc in cur.description]
        resultados = [dict(zip(columnas, fila)) for fila in datos]
        cur.close()
        conn.close()
        return resultados
    except Exception as e:
        print("❌ Error al obtener creadores:", e)
        return []


def obtener_todos_usuarios():
    try:
        with psycopg2.connect(INTERNAL_DATABASE_URL) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                SELECT 
                c.id, 
                c.usuario AS username, 
                c.nickname, 
                c.nombre_real, 
                c.email,
                c.telefono,
                c.whatsapp,
                c.foto_url,
                c.verificado,
                c.activo,
                ec.nombre AS estado_nombre,
                c.creado_en,
                c.actualizado_en,
                'creador' AS tipo_usuario,
                NULL AS rol
                FROM creadores c
                LEFT JOIN estados_creador ec ON c.estado_id = ec.id
                WHERE c.activo = TRUE
                
                UNION ALL
                
                SELECT
                a.id,
                a.username,
                NULL AS nickname,
                a.nombre_completo AS nombre_real, 
                a.email,
                a.telefono,
                NULL AS whatsapp,
                NULL AS foto_url,
                NULL AS verificado,
                a.activo,
                NULL AS estado_nombre,
                a.creado_en,
                NULL AS actualizado_en,
                'administrativo' AS tipo_usuario,
                a.rol AS rol
                FROM admin_usuario a
                WHERE a.activo = TRUE
                ORDER BY actualizado_en DESC NULLS LAST, creado_en DESC;
                """)
                resultados = cur.fetchall()
                return resultados
    except Exception as e:
        print("❌ Error al obtener usuarios:", e)
        return []

def obtener_perfil_creador(creador_id):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            SELECT
                id,
                creador_id,
                edad,
                seguidores,
                siguiendo,
                videos,
                likes,
                duracion_emisiones,
                dias_emisiones,
                apariencia,
                engagement,
                calidad_contenido,
                frecuencia_lives,
                creado_en,
                actualizado_en,
                puntaje_total,
                tiempo_disponible,
                experiencia_otras_plataformas,
                intereses,
                tipo_contenido,
                puntaje_estadistica,
                puntaje_manual,
                puntaje_general,
                puntaje_habitos,
                puntaje_total_categoria,
                campo_estudios,
                estudios,
                horario_preferido,
                intencion_trabajo,
                puntaje_estadistica_categoria,
                usuario,
                biografia_sugerida,
                puntaje_manual_categoria,
                genero,
                pais,
                ciudad,
                zona_horaria,
                puntaje_habitos_categoria,
                nombre,
                usuario_evalua,
                potencial_estimado,
                experiencia_otras_plataformas_otro_nombre,
                eval_foto,
                eval_biografia,
                biografia,
                estado,
                metadata_videos,
                actividad_actual,
                puntaje_general_categoria,
                idioma,
                observaciones,
                mejoras_sugeridas
            FROM perfil_creador
            WHERE creador_id = %s;
        """, (creador_id,))
        fila = cur.fetchone()
        columnas = [desc[0] for desc in cur.description]
        cur.close()
        conn.close()
        if fila:
            return dict(zip(columnas, fila))
        return None
    except Exception as e:
        print("❌ Error al obtener perfil del creador:", e)
        return None


def obtener_datos_mejoras_perfil_creador(creador_id):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
        SELECT  edad,genero,idioma,estudios,pais,actividad_actual,seguidores, siguiendo, likes, videos, duracion_emisiones,dias_emisiones,apariencia,engagement,calidad_contenido,estudios,actividad_actual,tiempo_disponible,frecuencia_lives,experiencia_otras_plataformas,intereses,tipo_contenido,intencion_trabajo,eval_foto,biografia,eval_biografia,biografia_sugerida,metadata_videos,potencial_estimado,
        puntaje_total,
        puntaje_estadistica,
        puntaje_manual,
        puntaje_general,
        puntaje_habitos,
        puntaje_total_categoria,
        puntaje_estadistica_categoria,
        puntaje_habitos_categoria,
        puntaje_general_categoria,
        puntaje_manual_categoria
        FROM perfil_creador
        WHERE creador_id = %s
        LIMIT 1
        """, (creador_id,))
        fila = cur.fetchone()
        columnas = [desc[0] for desc in cur.description]
        cur.close()
        conn.close()
        if fila:
            return dict(zip(columnas, fila))
        return None
    except Exception as e:
        print("❌ Error al obtener perfil del creador:", e)
        return None

def obtener_biografia_perfil_creador(creador_id):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
           SELECT biografia
        FROM perfil_creador
        WHERE creador_id = %s
        LIMIT 1
        """, (creador_id,))
        fila = cur.fetchone()
        columnas = [desc[0] for desc in cur.description]
        cur.close()
        conn.close()
        if fila:
            return dict(zip(columnas, fila))
        return None
    except Exception as e:
        print("❌ Error al obtener perfil del creador:", e)
        return None

def obtener_datos_estadisticas_perfil_creador(creador_id):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
           SELECT 
            seguidores
            siguiendo,
            videos,
            likes,
            duracion_emisiones
        FROM perfil_creador
        WHERE creador_id = %s
        LIMIT 1
        """, (creador_id,))
        fila = cur.fetchone()
        columnas = [desc[0] for desc in cur.description]
        cur.close()
        conn.close()
        if fila:
            return dict(zip(columnas, fila))
        return None
    except Exception as e:
        print("❌ Error al obtener perfil del creador:", e)
        return None

def obtener_puntajes_perfil_creador(creador_id):
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
           SELECT puntaje_general, puntaje_estadistica, puntaje_manual, puntaje_habitos,puntaje_general_categoria, puntaje_estadistica_categoria, puntaje_manual_categoria, puntaje_habitos_categoria,puntaje_total,puntaje_total_categoria
        FROM perfil_creador
        WHERE creador_id = %s
        LIMIT 1
        """, (creador_id,))
        fila = cur.fetchone()
        columnas = [desc[0] for desc in cur.description]
        cur.close()
        conn.close()
        if fila:
            return dict(zip(columnas, fila))
        return None
    except Exception as e:
        print("❌ Error al obtener perfil del creador:", e)
        return None

import psycopg2
import json

def actualizar_datos_perfil_creador(creador_id, datos_dict):
    try:
        campos_validos = [
            # Datos personales y generales
            "nombre", "edad", "genero", "pais", "ciudad", "zona_horaria",
            "idioma", "campo_estudios", "estudios","actividad_actual","puntaje_general","puntaje_general_categoria",

            # Evaluación manual/cualitativa
            "biografia", "apariencia", "engagement", "calidad_contenido",
            "potencial_estimado", "usuario_evalua", "biografia_sugerida","eval_biografia","eval_foto","metadata_videos","puntaje_manual","puntaje_manual_categoria",

            # Estadísticas del perfil
            "seguidores", "siguiendo", "videos", "likes",
            "duracion_emisiones", "dias_emisiones","puntaje_estadistica","puntaje_estadistica_categoria",

            # Preferencias y hábitos
            "tiempo_disponible", "frecuencia_lives",
            "experiencia_otras_plataformas","experiencia_otras_plataformas_otro_nombre", "intereses", "tipo_contenido",
            "horario_preferido", "intencion_trabajo","puntaje_habitos","puntaje_habitos_categoria",

            # Resumen
            "estado", "observaciones","mejoras_sugeridas","puntaje_total", "puntaje_total_categoria"
        ]

        campos = []
        valores = []

        for campo in campos_validos:
            if campo in datos_dict:
                valor = datos_dict[campo]
                # 👇 Serializa los campos que son diccionarios (jsonb)
                if isinstance(valor, dict):
                    valor = json.dumps(valor)
                campos.append(f"{campo} = %s")
                valores.append(valor)

        if not campos:
            raise ValueError("⚠️ No se enviaron campos válidos para actualizar")

        campos.append("actualizado_en = NOW()")
        valores.append(creador_id)

        query = f"""
            UPDATE perfil_creador
            SET {', '.join(campos)}
            WHERE creador_id = %s;
        """

        with psycopg2.connect(INTERNAL_DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(query, valores)
                conn.commit()
                print(f"✅ Datos del perfil del creador {creador_id} actualizados.")

    except Exception as e:
        print(f"❌ Error al actualizar datos del perfil del creador {creador_id}: {e}")
        raise


def actualizar_perfil_creador_(creador_id, evaluacion_dict):
    try:
        campos = []
        valores = []

        for campo in ['apariencia', 'engagement', 'calidad_contenido', 'puntaje_total', 'puntaje_manual', 'mejoras_sugeridas_manual','usuario_evalua_inicial']:
            if campo in evaluacion_dict:
                campos.append(f"{campo} = %s")
                valores.append(evaluacion_dict[campo])

        if not campos:
            raise ValueError("No se enviaron campos válidos para actualizar")

        # Actualizar el campo actualizado_en también
        campos.append("actualizado_en = NOW()")

        valores.append(creador_id)

        query = f"""
            UPDATE perfil_creador
            SET {', '.join(campos)}
            WHERE creador_id = %s;
        """

        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()
        cur.execute(query, valores)
        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        print("❌ Error al actualizar evaluación:", e)
        raise

def obtener_estadisticas_evaluacion():
    conn = psycopg2.connect(INTERNAL_DATABASE_URL)
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*) FROM creadores;
    """)
    total_aspirantes = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM perfil_creador 
        WHERE puntaje_total IS NULL OR puntaje_total = 0;
    """)
    evaluaciones_pendientes = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM perfil_creador 
        WHERE puntaje_total >= 3.0;
    """)
    aprobados = cur.fetchone()[0]

    cur.execute("""
        SELECT AVG(puntaje_total) FROM perfil_creador 
        WHERE puntaje_total IS NOT NULL AND puntaje_total > 0;
    """)
    promedio = cur.fetchone()[0] or 0

    cur.close()
    conn.close()

    return {
        "totalAspirantes": total_aspirantes,
        "evaluacionesPendientes": evaluaciones_pendientes,
        "aprobados": aprobados,
        "promedioPuntuacion": float(promedio)
    }

def guardar_en_bd(agendamiento, meet_link, usuario_actual_id, creado):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO agendamientos (
                creador_id, fecha_inicio, fecha_fin, titulo, descripcion,
                link_meet, estado, responsable_id, google_event_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'programado', %s, %s, %s, %s, %s, %s)
        """, (
            agendamiento.creador_id,
            agendamiento.inicio,
            agendamiento.fin,
            agendamiento.titulo,
            agendamiento.descripcion,
            meet_link,
            usuario_actual_id,
            creado["id"]  # Google Event ID
        ))
        conn.commit()
        print("Agendamiento guardado correctamente.")
        return True
    except Exception as e:
        print("Error al guardar agendamiento:", e)
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


def obtener_creador_id_por_usuario(usuario: str) -> Optional[int]:
    """Busca el creador_id en la base de datos por nombre de usuario"""
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        cur.execute("SELECT id FROM creadores WHERE usuario = %s", (usuario,))
        result = cur.fetchone()

        cur.close()
        conn.close()

        return result[0] if result else None

    except Exception as e:
        print(f"⚠️ Error buscando creador por usuario {usuario}: {str(e)}")
        return None


def eliminar_perfil_creador(perfil_id: int):
    """Elimina un perfil de creador"""
    try:
        conn = psycopg2.connect(INTERNAL_DATABASE_URL)
        cur = conn.cursor()

        cur.execute("DELETE FROM perfil_creador WHERE id = %s", (perfil_id,))
        affected_rows = cur.rowcount

        conn.commit()
        cur.close()
        conn.close()
        return affected_rows > 0

    except Exception as e:
        print("❌ Error al eliminar perfil de creador:", e)
        return False


# if __name__ == "__main__":
#     print("Probando diagnóstico...")
#     # resultado = diagnostico_perfil_creador(27)  # Cambia el ID según quieras
#     creador_id=69
#     resultado=obtener_perfil_creador(creador_id)
#
#     print("Resultado:", resultado)



