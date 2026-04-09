import os
import re
import json
import secrets
import traceback
import psycopg2
import pytz
from psycopg2 import OperationalError, IntegrityError, DatabaseError
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
from gspread.worksheet import JSONResponse as GSpreadJSONResponse
from fastapi.responses import JSONResponse

from fastapi import HTTPException
from psycopg2.errors import UniqueViolation

from schemas import ActualizacionContactoInfo
from psycopg2.extras import RealDictCursor

from datetime import date, datetime, timedelta, timezone
from typing import Optional, List, Dict
from contextlib import contextmanager

# Para hash de contraseñas (instalar con: pip install bcrypt)
try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    print("⚠️ bcrypt no instalado. Las contraseñas no se hashearán correctamente.")

# Cargar variables de entorno (incluye DATABASE_URL)
load_dotenv()

INTERNAL_DATABASE_URL = os.getenv("INTERNAL_DATABASE_URL")

EXTERNAL_DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")

from tenant import current_tenant

_SCHEMA_RE = re.compile(r"^[a-z0-9_]+$")  # validación para schema

class TenantSchemaError(Exception):
    pass


def _sanitize_schema(schema: str) -> str:
    """
    Valida el nombre del schema del tenant.
    Acepta nombres simples como 'test', 'public', 'agencia_xxx', etc.
    """
    if not schema:
        raise TenantSchemaError("⚠️ current_tenant vacío o no configurado")

    # 1. Talentum Manager SIEMPRE va a public
    if schema == "talentum-manager":
        return "public"

    # 2) Schemas especiales que sabemos que existen
    if schema in ("public", "test"):
        return schema

    # 3) Cualquier nombre simple tipo mytenant_123
    if _SCHEMA_RE.fullmatch(schema):
        return schema

    # 4) Si no cumple nada, error
    raise TenantSchemaError(f"⚠️ Schema de tenant inválido: {schema!r}")



def get_connection():
    tenant_schema = current_tenant.get()
    tenant_schema = _sanitize_schema(tenant_schema)  # aquí puede explotar

    conn = psycopg2.connect(INTERNAL_DATABASE_URL)
    conn.autocommit = False
    with conn.cursor() as cur:
        cur.execute(f"SET search_path TO {tenant_schema}, public;")
    return conn


@contextmanager
def get_connection_context(schema=None):
    """
    Context manager para obtener y cerrar conexiones automáticamente.
    
    Usage:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ...")
                conn.commit()
    """
    conn = None
    try:
        conn = get_connection()
        yield conn
        if conn:
            conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

def get_connection_public():
    """
    Devuelve una conexión a la base de datos con search_path fijo a public,
    ignorando cualquier tenant/contexto.
    """
    conn = psycopg2.connect(INTERNAL_DATABASE_URL)
    conn.autocommit = False

    with conn.cursor() as cur:
        cur.execute("SET search_path TO public;")

    return conn





@contextmanager
def get_connection_public_context():
    """
    Context manager para obtener y cerrar conexiones públicas automáticamente.
    
    Usage:
        with get_connection_public_context() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ...")
                conn.commit()
    """
    conn = None
    try:
        conn = get_connection_public()
        yield conn
        if conn:
            conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


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
    with get_connection_context() as conn:
        with conn.cursor() as cur:
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

                    # 1. aspirantes
                    cur.execute("SELECT id FROM aspirantes WHERE usuario = %s", (usuario,))
                    creador_row = cur.fetchone()
                    if creador_row:
                        aspirante_id = creador_row[0]
                        cur.execute("""
                            UPDATE aspirantes SET
                                nickname = %s,
                                email = %s,
                                telefono = %s,
                                actualizado_en = NOW()
                            WHERE id = %s
                        """, (nickname, email, telefono, aspirante_id))
                    else:
                        cur.execute("""
                            INSERT INTO aspirantes (usuario, nickname, email, telefono, activo, creado_en, actualizado_en)
                            VALUES (%s, %s, %s, %s, TRUE, NOW(), NOW())
                            RETURNING id
                        """, (usuario, nickname, email, telefono))
                        aspirante_id = cur.fetchone()[0]

                    # 2. aspirantes_perfil
                    cur.execute("SELECT id FROM aspirantes_perfil WHERE aspirante_id = %s", (aspirante_id,))
                    perfil_row = cur.fetchone()
                    if perfil_row:
                        cur.execute("""
                            UPDATE aspirantes_perfil SET
                                perfil = %s,
                                seguidores = %s,
                                cantidad_videos = %s,
                                likes_totales = %s,
                                duracion_emisiones = %s,
                                dias_emisiones = %s,
                                actualizado_en = NOW()
                            WHERE aspirante_id = %s
                        """, (
                        perfil, seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones, aspirante_id))
                    else:
                        cur.execute("""
                            INSERT INTO aspirantes_perfil (
                                aspirante_id, perfil,
                                seguidores, cantidad_videos, likes_totales,
                                duracion_emisiones, dias_emisiones,
                                creado_en, actualizado_en
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                            )
                        """, (
                        aspirante_id, perfil, seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones))

                    # 3. cargue_aspirantes
                    cur.execute("SELECT id FROM cargue_aspirantes WHERE usuario = %s AND hoja_excel = %s", (usuario, hoja_excel))
                    cargue_row = cur.fetchone()
                    if cargue_row:
                        cargue_id = cargue_row[0]
                        cur.execute("""
                            UPDATE cargue_aspirantes SET
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
                                aspirante_id = %s,
                                apto = %s,
                                observaciones = %s,
                                actualizado_en = NOW()
                            WHERE id = %s
                        """, (
                            nickname, email, telefono, disponibilidad, perfil, motivo_no_apto,
                            contacto, respuesta_creador, entrevista, tipo_solicitud, razon_no_contacto,
                            seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones,
                            nombre_archivo, fila_excel, lote_carga, "Procesando", False, procesado_por,
                            aspirante_id, apto, observaciones, cargue_id
                        ))
                    else:
                        cur.execute("""
                            INSERT INTO cargue_aspirantes (
                                usuario, nickname, email, telefono, disponibilidad, perfil, motivo_no_apto,
                                contacto, respuesta_creador, entrevista, tipo_solicitud, razon_no_contacto,
                                seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones,
                                nombre_archivo, hoja_excel, fila_excel, lote_carga,
                                estado, procesado, procesado_por, aspirante_id,
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
                            "Procesando", False, procesado_por, aspirante_id,
                            apto, observaciones
                        ))

                    resultados.append({
                        "fila": fila_excel,
                        "usuario": usuario,
                        "aspirante_id": aspirante_id
                    })

                except Exception as err:
                    conn.rollback()
                    filas_fallidas.append({
                        "fila": c.get("fila_excel"),
                        "error": str(err),
                        "contacto": c
                    })

            conn.commit()
            print(f"✅ Contactos procesados. Filas exitosas: {len(resultados)}. Filas fallidas: {len(filas_fallidas)}")
            return {
                "exitosos": resultados,
                "fallidos": filas_fallidas
            }

# ------------------------------
def obtener_usuario_id_por_telefono(telefono: str):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id FROM aspirantes WHERE telefono = %s
                """, (telefono,))

                resultado = cur.fetchone()

                return resultado[0] if resultado else None
    except (OperationalError, DatabaseError) as e:
        print(f"❌ Error de base de datos al obtener aspirante_id: {e}")
        traceback.print_exc()
        return None
    except Exception as e:
        print(f"❌ Error inesperado al obtener aspirante_id: {e}")
        traceback.print_exc()
        return None

from datetime import datetime, timedelta, timezone
from psycopg2 import OperationalError, DatabaseError
import traceback

def paso_limite_24h(telefono: str) -> bool:
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT fecha
                    FROM mensajes_whatsapp
                    WHERE telefono = %s
                      AND direccion = 'recibido'
                    ORDER BY fecha DESC
                    LIMIT 1
                """, (telefono,))
                resultado = cur.fetchone()
                # 🔹 Si nunca escribió → fuera de ventana
                if not resultado:
                    return True
                ultima_fecha = resultado[0]
                # Asegurar que tenga timezone
                if ultima_fecha.tzinfo is None:
                    ultima_fecha = ultima_fecha.replace(tzinfo=timezone.utc)
                ahora = datetime.now(timezone.utc)
                diferencia = ahora - ultima_fecha
                return diferencia > timedelta(hours=24)

    except (OperationalError, DatabaseError) as e:
        print(f"❌ Error de base de datos verificando límite 24h: {e}")
        traceback.print_exc()
        return True  # Por seguridad

    except Exception as e:
        print(f"❌ Error inesperado verificando límite 24h: {e}")
        traceback.print_exc()
        return True  # Por seguridad

def actualizar_contacto_info_db(telefono: str, datos: ActualizacionContactoInfo):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
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
                    UPDATE aspirantes
                    SET {', '.join(updates)}
                    WHERE telefono = %s
                """
                cur.execute(query, tuple(valores))
                conn.commit()
                return {"status": "ok", "mensaje": "Contacto actualizado correctamente"}

    except IntegrityError as e:
        print(f"❌ Error de integridad actualizando contacto_info: {e}")
        traceback.print_exc()
        return {"status": "error", "mensaje": f"Error de integridad: {str(e)}"}
    except (OperationalError, DatabaseError) as e:
        print(f"❌ Error de base de datos actualizando contacto_info: {e}")
        traceback.print_exc()
        return {"status": "error", "mensaje": f"Error de base de datos: {str(e)}"}
    except Exception as e:
        print(f"❌ Error inesperado actualizando contacto_info: {e}")
        traceback.print_exc()
        return {"status": "error", "mensaje": str(e)}

def obtener_contactos_db_nueva(estado=None):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                base_query = """
                    SELECT a.usuario,
                           a.nickname,
                           a.nombre_real AS nombre,
                           a.whatsapp AS telefono,
                           b.nombre AS estado
                    FROM aspirantes a
                    INNER JOIN aspirantes_estados b ON a.estado_id = b.id
                    WHERE a.whatsapp IS NOT NULL
                      AND a.whatsapp != ''
                      AND a.estado_id IN (1,2,3,4,5)
                """

                params = []

                # 🔥 Filtro dinámico por estado
                if estado:
                    base_query += " AND b.id = %s"
                    params.append(estado)

                base_query += " ORDER BY a.usuario ASC"

                cur.execute(base_query, params)

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

                return contactos

    except Exception as e:
        print(f"❌ Error obteniendo contactos: {e}")
        traceback.print_exc()
        return []


def obtener_contactos_db(estado: Optional[str] = None):
    try:
        tenant_actual = current_tenant.get()
        print(f"🔍 [obtener_contactos_db] Tenant actual antes de conexión: {tenant_actual}")
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                if estado:
                    cur.execute("""
                        SELECT a.usuario, a.nickname, a.nombre_real AS nombre, a.whatsapp as telefono, b.nombre AS estado
                        FROM aspirantes a
                        INNER JOIN aspirantes_estados b ON a.estado_id = b.id
                        WHERE whatsapp IS NOT NULL
                          AND whatsapp != ''
                          AND UPPER(b.nombre) = %s
                        ORDER BY a.usuario ASC
                    """, (estado.upper(),))
                else:
                    cur.execute("""
                        SELECT a.usuario, a.nickname, a.nombre_real AS nombre, a.whatsapp as telefono, b.nombre AS estado
                        FROM aspirantes a
                        INNER JOIN aspirantes_estados b ON a.estado_id = b.id
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

                return contactos

    except (OperationalError, DatabaseError) as e:
        print(f"❌ Error de base de datos obteniendo contactos: {e}")
        traceback.print_exc()
        return {"status": "error", "mensaje": f"Error de base de datos: {str(e)}"}
    except Exception as e:
        print(f"❌ Error inesperado obteniendo contactos: {e}")
        traceback.print_exc()
        return {"status": "error", "mensaje": str(e)}


def guardar_mensaje_nuevo(
    telefono,
    contenido=None,
    direccion="recibido",
    tipo="texto",
    media_url=None,
    message_id_meta=None,
    estado="sent"
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                aspirante_id = None

                # Buscar aspirante existente
                cur.execute(
                    "SELECT id FROM aspirantes WHERE telefono = %s OR whatsapp = %s LIMIT 1",
                    (telefono, telefono)
                )
                usuario = cur.fetchone()

                if usuario:
                    aspirante_id = usuario[0]

                # Insertar mensaje sin crear aspirante automáticamente
                cur.execute("""
                    INSERT INTO mensajes_whatsapp
                    (aspirante_id, telefono, direccion, tipo, contenido,
                     media_url, message_id_meta, estado)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    aspirante_id,
                    telefono,
                    direccion,
                    tipo,
                    contenido,
                    media_url,
                    message_id_meta,
                    estado
                ))

                conn.commit()

        print("✅ Mensaje guardado correctamente.")

    except Exception as e:
        print(f"❌ Error guardando mensaje: {e}")
        traceback.print_exc()


def guardar_mensaje_nuevo20260325(
    telefono,
    contenido=None,
    direccion="recibido",
    tipo="texto",
    media_url=None,
    message_id_meta=None,
    estado="sent"
):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                # Buscar usuario
                cur.execute(
                    "SELECT id FROM aspirantes WHERE telefono = %s",
                    (telefono,)
                )
                usuario = cur.fetchone()

                if not usuario:
                    cur.execute(
                        "INSERT INTO aspirantes (telefono) VALUES (%s) RETURNING id",
                        (telefono,)
                    )
                    aspirante_id = cur.fetchone()[0]
                else:
                    aspirante_id = usuario[0]

                # Insertar mensaje en NUEVA tabla
                cur.execute("""
                    INSERT INTO mensajes_whatsapp
                    (aspirante_id, telefono, direccion, tipo, contenido,
                     media_url, message_id_meta, estado)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    aspirante_id,
                    telefono,
                    direccion,
                    tipo,
                    contenido,
                    media_url,
                    message_id_meta,
                    estado
                ))

                conn.commit()

        print("✅ Mensaje guardado correctamente.")

    except Exception as e:
        print(f"❌ Error guardando mensaje: {e}")
        traceback.print_exc()


import re
from datetime import datetime
from psycopg2 import DatabaseError


def guardar_mensaje(telefono, texto, tipo="recibido", es_audio=False):
    try:
        # Normalizar texto
        texto = str(texto or "").strip()

        # Extraer nombre de audio
        if es_audio and texto.startswith("[Audio guardado:"):
            match = re.search(r"\[Audio guardado: (.+?)\]", texto)
            if match:
                texto = match.group(1)

        with get_connection_context() as conn:
            with conn.cursor() as cur:

                # Buscar o crear usuario
                cur.execute("SELECT id FROM aspirantes WHERE telefono = %s", (telefono,))
                row = cur.fetchone()

                if row:
                    aspirante_id = row[0]
                else:
                    cur.execute(
                        "INSERT INTO aspirantes (telefono) VALUES (%s) RETURNING id",
                        (telefono,)
                    )
                    aspirante_id = cur.fetchone()[0]

                # Insertar mensaje
                cur.execute("""
                    INSERT INTO mensajes (aspirante_id, contenido, tipo, es_audio, fecha)
                    VALUES (%s, %s, %s, %s, %s)
                """, (aspirante_id, texto, tipo, es_audio, datetime.now()))

            conn.commit()

        return True

    except DatabaseError as e:
        print(f"❌ Error de base de datos: {e}")
        return False

    except Exception as e:
        print(f"❌ Error inesperado: {e}")
        return False



def actualizar_nombre_contacto(telefono, nuevo_nombre):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE aspirantes
                    SET nombre_real = %s
                    WHERE telefono = %s
                """, (nuevo_nombre, telefono))
                conn.commit()
        print(f"✅ Nombre actualizado para {telefono}: {nuevo_nombre}")
        return True
    except IntegrityError as e:
        print(f"❌ Error de integridad al actualizar nombre de contacto: {e}")
        traceback.print_exc()
        return False
    except (OperationalError, DatabaseError) as e:
        print(f"❌ Error de base de datos al actualizar nombre de contacto: {e}")
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"❌ Error inesperado al actualizar nombre de contacto: {e}")
        traceback.print_exc()
        return False

def eliminar_mensajes(telefono):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM mensajes
                    USING aspirantes
                    WHERE mensajes.aspirante_id = aspirantes.id
                    AND aspirantes.telefono = %s
                """, (telefono,))
                conn.commit()
        print(f"🗑️ Mensajes eliminados para {telefono}")
        return True
    except (OperationalError, DatabaseError) as e:
        print(f"❌ Error de base de datos al eliminar mensajes: {e}")
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"❌ Error inesperado al eliminar mensajes: {e}")
        traceback.print_exc()
        return False

def ver_mensajes(limit=10):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, telefono, contenido, tipo, es_audio, fecha
                    FROM mensajes
                    ORDER BY fecha DESC
                    LIMIT %s;
                """, (limit,))
                resultados = cur.fetchall()
                for fila in resultados:
                    print(f"🟢 {fila}")
    except (OperationalError, DatabaseError) as e:
        print(f"❌ Error de base de datos al consultar mensajes: {e}")
        traceback.print_exc()
    except Exception as e:
        print(f"❌ Error inesperado al consultar mensajes: {e}")
        traceback.print_exc()



def obtener_contactos():
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT telefono, nombre, creado_en FROM aspirantes ORDER BY creado_en DESC")
                contactos = cur.fetchall()
                return [
                    {"telefono": telefono, "nombre": nombre or "", "creado_en": creado_en.isoformat()}
                    for telefono, nombre, creado_en in contactos
                ]
    except (OperationalError, DatabaseError) as e:
        print(f"❌ Error de base de datos al obtener contactos: {e}")
        traceback.print_exc()
        return []
    except Exception as e:
        print(f"❌ Error inesperado al obtener contactos: {e}")
        traceback.print_exc()
        return []


def obtener_mensajes(telefono):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT contenido,
                           direccion,
                           tipo,
                           fecha
                    FROM mensajes_whatsapp
                    WHERE telefono = %s
                    ORDER BY fecha ASC
                """, (telefono,))

                mensajes = cur.fetchall()

                return [
                    {
                        "contenido": contenido,
                        # 🔁 El front espera que "tipo" sea enviado/recibido
                        "tipo": direccion,
                        "fecha": fecha.isoformat(),
                        # 🔊 Derivado del nuevo campo tipo
                        "es_audio": True if tipo == "audio" else False
                    }
                    for contenido, direccion, tipo, fecha in mensajes
                ]

    except Exception as e:
        print(f"❌ Error obteniendo mensajes: {e}")
        traceback.print_exc()
        return []





def obtener_mensajesV0(telefono):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT m.contenido, m.tipo, m.fecha, m.es_audio
                    FROM mensajes m
                    INNER JOIN aspirantes u ON m.aspirante_id = u.id
                    WHERE u.telefono = %s
                    ORDER BY m.fecha ASC
                """, (telefono,))
                mensajes = cur.fetchall()
                return [
                    {
                        "contenido": contenido,
                        "tipo": tipo,
                        "fecha": fecha.isoformat(),
                        "es_audio": es_audio
                    }
                    for contenido, tipo, fecha, es_audio in mensajes
                ]
    except (OperationalError, DatabaseError) as e:
        print(f"❌ Error de base de datos al obtener mensajes: {e}")
        traceback.print_exc()
        return []
    except Exception as e:
        print(f"❌ Error inesperado al obtener mensajes: {e}")
        traceback.print_exc()
        return []


def obtener_ultimos_mensajes(limit=10):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT m.contenido, m.tipo, m.fecha, m.es_audio
                    FROM mensajes m
                    JOIN aspirantes u ON m.aspirante_id = u.id
                    ORDER BY m.fecha ASC
                    LIMIT %s;
                    """, (limit,))
                resultados = cur.fetchall()
                for fila in resultados:
                    print(f"🟢 {fila}")
    except (OperationalError, DatabaseError) as e:
        print(f"❌ Error de base de datos al consultar mensajes: {e}")
        traceback.print_exc()
    except Exception as e:
        print(f"❌ Error inesperado al consultar mensajes: {e}")
        traceback.print_exc()


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
# FUNCIONES PARA administradores
# ===============================

def _administradores_roles_id_por_nombre(cur, nombre_rol: str):
    """Resuelve el id en administradores_roles a partir del nombre (ej. 'Manager', 'admin')."""
    if not nombre_rol or not str(nombre_rol).strip():
        return None
    cur.execute(
        "SELECT id FROM administradores_roles WHERE nombre = %s",
        (str(nombre_rol).strip(),),
    )
    row = cur.fetchone()
    return row[0] if row else None


def obtener_todos_usuarioss():
    """Obtiene todos los administradores administradores"""
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT a.id, a.username, a.nombre_completo, a.email, a.telefono,
                           ur.nombre AS rol, a.grupo, a.activo,
                           a.creado_en, a.actualizado_en
                    FROM administradores a
                    LEFT JOIN administradores_roles ur ON ur.id = a.administradores_roles_id
                    ORDER BY a.creado_en DESC
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
                
                return usuarios
        
    except (OperationalError, DatabaseError) as e:
        print(f"❌ Error de base de datos al obtener usuarios administradores: {e}")
        traceback.print_exc()
        return []
    except Exception as e:
        print(f"❌ Error inesperado al obtener administradores administradores: {e}")
        traceback.print_exc()
        return []


def obtener_todos_responsables_agendas():
    """Obtiene todos los administradores responsables de agendas"""
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT a.id, a.username, a.nombre_completo, a.email, a.telefono,
                           ur.nombre AS rol, a.grupo, a.activo,
                           a.creado_en, a.actualizado_en
                    FROM administradores a
                    LEFT JOIN administradores_roles ur ON ur.id = a.administradores_roles_id
                    ORDER BY a.creado_en DESC
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

                return usuarios
        
    except (OperationalError, DatabaseError) as e:
        print(f"❌ Error de base de datos al obtener usuarios responsables agendas: {e}")
        traceback.print_exc()
        return []
    except Exception as e:
        print(f"❌ Error inesperado al obtener usuarios responsables agendas: {e}")
        traceback.print_exc()
        return []





def crear_usuarios(datos):
    """Crea un nuevo usuario administrador dentro del tenant actual."""

    # Normalizar datos si vienen de Pydantic
    if hasattr(datos, "dict"):
        datos = datos.dict()

    # Validar campos requeridos
    requeridos = ["username", "nombre_completo", "email", "rol"]
    faltantes = [campo for campo in requeridos if not datos.get(campo)]
    if faltantes:
        raise HTTPException(
            status_code=400,
            detail=f"Faltan campos obligatorios: {', '.join(faltantes)}"
        )

    # Normalizar datos
    username = datos["username"].strip().lower()
    email = datos["email"].strip().lower()
    nombre_completo = datos.get("nombre_completo")
    telefono = datos.get("telefono")
    rol = datos["rol"]
    grupo = datos.get("grupo")
    activo = datos.get("activo", True)

    # Generar contraseña si no viene
    password = datos.get("password")
    if not password:
        password = f"{username}123"

    password_hash = hash_password(password)

    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                administradores_roles_id = _administradores_roles_id_por_nombre(cur, rol)
                if administradores_roles_id is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Rol no válido o no existe en administradores_roles: {rol!r}",
                    )

                cur.execute("""
                    INSERT INTO administradores (
                        username, nombre_completo, email, telefono, grupo, activo,
                        password_hash, administradores_roles_id, creado_en, actualizado_en
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    RETURNING id, username, nombre_completo, email, telefono, grupo, activo,
                              creado_en, actualizado_en
                """, (
                    username, nombre_completo, email, telefono,
                    grupo, activo, password_hash, administradores_roles_id,
                ))

                row = cur.fetchone()
                conn.commit()

                return {
                    "id": row[0],
                    "username": row[1],
                    "nombre_completo": row[2],
                    "email": row[3],
                    "telefono": row[4],
                    "rol": rol,
                    "grupo": row[5],
                    "activo": row[6],
                    "creado_en": row[7].isoformat() if row[7] else None,
                    "actualizado_en": row[8].isoformat() if row[8] else None,
                    "password_inicial": password  # 👈 solo para admin
                }

    except UniqueViolation:
        raise HTTPException(
            status_code=409,
            detail="El username o el email ya existe"
        )

    except Exception as e:
        print("❌ Error al crear usuario administrador:", e)
        raise HTTPException(
            status_code=500,
            detail="Error interno del servidor"
        )



def obtener_usuarios_por_id(administrador_id):
    """Obtiene un usuario administrador por ID"""
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT a.id, a.username, a.nombre_completo, a.email, a.telefono,
                           ur.nombre AS rol, a.grupo, a.activo,
                           a.creado_en, a.actualizado_en
                    FROM administradores a
                    LEFT JOIN administradores_roles ur ON ur.id = a.administradores_roles_id
                    WHERE a.id = %s
                """, (administrador_id,))
                
                row = cur.fetchone()
                
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

def actualizar_usuarios(administrador_id, datos):
    """Actualiza un usuario administrador y retorna los datos actualizados"""
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # Verificar si el usuario existe
                cur.execute("SELECT id FROM administradores WHERE id = %s", (administrador_id,))
                if not cur.fetchone():
                    # En vez de devolver dict, lanza excepción en el endpoint
                    return None

                # Verificar username único (excluyendo el usuario actual)
                if datos.get("username"):
                    cur.execute(
                        "SELECT id FROM administradores WHERE username = %s AND id != %s",
                        (datos.get("username"), administrador_id)
                    )
                    if cur.fetchone():
                        raise ValueError("El username ya existe")

                # Verificar email único (excluyendo el usuario actual)
                if datos.get("email"):
                    cur.execute(
                        "SELECT id FROM administradores WHERE email = %s AND id != %s",
                        (datos.get("email"), administrador_id)
                    )
                    if cur.fetchone():
                        raise ValueError("El email ya existe")

                # Construir query de actualización dinámicamente
                updates = []
                valores = []

                campos_permitidos = ["username", "nombre_completo", "email", "telefono", "grupo", "activo"]
                for campo in campos_permitidos:
                    if campo in datos:
                        updates.append(f"{campo} = %s")
                        valores.append(datos[campo])

                if "rol" in datos and datos["rol"] is not None:
                    rid = _administradores_roles_id_por_nombre(cur, datos["rol"])
                    if rid is None:
                        raise ValueError(f"Rol no válido: {datos['rol']!r}")
                    updates.append("administradores_roles_id = %s")
                    valores.append(rid)

                if not updates:
                    raise ValueError("No se proporcionaron campos para actualizar")

                updates.append("actualizado_en = NOW()")
                valores.append(administrador_id)

                query = f"UPDATE administradores SET {', '.join(updates)} WHERE id = %s"
                cur.execute(query, tuple(valores))
                conn.commit()

                # Obtener los datos actualizados
                cur.execute("""
                    SELECT a.id, a.username, ur.nombre AS rol, a.nombre_completo, a.email, a.telefono, a.grupo, a.activo
                    FROM administradores a
                    LEFT JOIN administradores_roles ur ON ur.id = a.administradores_roles_id
                    WHERE a.id = %s
                """, (administrador_id,))
                row = cur.fetchone()

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


def eliminar_usuarios(administrador_id):
    """Elimina un usuario administrador"""
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # Verificar si el usuario existe
                cur.execute("SELECT id FROM administradores WHERE id = %s", (administrador_id,))
                if not cur.fetchone():
                    return {"status": "error", "mensaje": "Usuario no encontrado"}
                
                cur.execute("DELETE FROM administradores WHERE id = %s", (administrador_id,))
                conn.commit()
                
                return {"status": "ok", "mensaje": "Usuario eliminado correctamente"}
        
    except Exception as e:
        print("❌ Error al eliminar usuario administrador:", e)
        return {"status": "error", "mensaje": str(e)}


def cambiar_estado_usuarios(administrador_id, activo):
    """Cambia el estado activo/inactivo de un usuario administrador"""
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # Verificar si el usuario existe
                cur.execute("SELECT id FROM administradores WHERE id = %s", (administrador_id,))
                if not cur.fetchone():
                    return {"status": "error", "mensaje": "Usuario no encontrado"}
                
                cur.execute("""
                    UPDATE administradores 
                    SET activo = %s, actualizado_en = NOW() 
                    WHERE id = %s
                """, (activo, administrador_id))
                
                conn.commit()
                
                estado_texto = "activado" if activo else "desactivado"
                return {"status": "ok", "mensaje": f"Usuario {estado_texto} correctamente"}
        
    except Exception as e:
        print("❌ Error al cambiar estado del usuario administrador:", e)
        return {"status": "error", "mensaje": str(e)}


def obtener_usuarios_por_username(username):
    """Obtiene un usuario administrador por username (útil para autenticación)"""
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT a.id, a.username, a.nombre_completo AS nombre, a.email, a.telefono,
                           ur.nombre AS rol, a.grupo, a.activo,
                           a.password_hash, a.creado_en, a.actualizado_en
                    FROM administradores a
                    LEFT JOIN administradores_roles ur ON ur.id = a.administradores_roles_id
                    WHERE a.username = %s
                """, (username,))
                
                row = cur.fetchone()
                
                if row:
                    return {
                        "id": row[0],
                        "username": row[1],
                        "nombre": row[2],
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
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # Siempre usa parámetros para evitar SQL Injection
                cur.execute(
                    "UPDATE administradores SET password_hash = %s WHERE id = %s",
                    (nuevo_hash, user_id)
                )
                conn.commit()
                actualizado = cur.rowcount > 0  # True si se actualizó
        return actualizado
    except Exception as e:
        print(f"Error al actualizar contraseña: {e}")
        return False



def autenticar_usuarios(username, password):
    """Autentica un usuario administrador"""
    try:
        # Obtener usuario por username
        usuario = obtener_usuarios_por_username(username)
        
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
    """Obtiene todos los perfiles de aspirantes"""
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, aspirante_id, perfil, biografia_actual as biografia, seguidores, cantidad_videos as videos, engagement_rate as engagement, clasificacion_actual as acciones
                    FROM aspirantes_perfil
                    ORDER BY id DESC
                """)

                perfiles = []
                for row in cur.fetchall():
                    perfiles.append({
                        "id": row[0],
                        "aspirante_id": row[1] or f"creator_{row[0]}",
                        "perfil": row[2] or "Sin clasificar",
                        "biografia": row[3] or "",
                        "seguidores": row[4] or 0,
                        "videos": row[5] or 0,
                        "engagement": f"{row[6]*100:.2f}%" if row[6] is not None else "0%",
                        "acciones": row[7] or "Pendiente"
                    })

                return perfiles

    except Exception as e:
        print("❌ Error al obtener perfiles de aspirantes:", e)
        return []


def obtener_aspirantes_perfil_por_id(perfil_id: int):
    """Obtiene un perfil de creador por ID"""
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, aspirante_id, perfil, biografia_actual as biografia, seguidores, cantidad_videos as videos, engagement_rate as engagement, clasificacion_actual as acciones
                    FROM aspirantes_perfil
                    WHERE id = %s
                """, (perfil_id,))

                row = cur.fetchone()
                if row:
                    perfil = {
                        "id": row[0],
                        "aspirante_id": row[1] or f"creator_{row[0]}",
                        "perfil": row[2] or "Sin clasificar",
                        "biografia": row[3] or "",
                        "seguidores": row[4] or 0,
                        "videos": row[5] or 0,
                        "engagement": f"{row[6]*100:.2f}%" if row[6] is not None else "0%",
                        "acciones": row[7] or "Pendiente"
                    }
                else:
                    perfil = None

                return perfil

    except Exception as e:
        print("❌ Error al obtener perfil de creador:", e)
        return None


def crear_aspirantes_perfil(perfil_data):
    """Crea un nuevo perfil de creador"""
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO aspirantes_perfil (aspirante_id, perfil, biografia_actual, seguidores, cantidad_videos, engagement_rate, clasificacion_actual)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, aspirante_id, perfil, biografia_actual, seguidores, cantidad_videos, engagement_rate, clasificacion_actual
                """, (
                    perfil_data["aspirante_id"],
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
                    "aspirante_id": row[1],
                    "perfil": row[2],
                    "biografia": row[3],
                    "seguidores": row[4],
                    "videos": row[5],
                    "engagement": f"{row[6]*100:.2f}%",
                    "acciones": row[7]
                }

                conn.commit()
                return perfil

    except Exception as e:
        print("❌ Error al crear perfil de creador:", e)
        return None

def actualizar_aspirantes_perfil_evalua(aspirante_id: int, data: Dict):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # Generar dinámicamente el SET para los campos que vienen en el body
                set_clause = ", ".join([f"{key} = %s" for key in data.keys()])
                values = list(data.values())

                query = f"""
                    UPDATE aspirantes_perfil
                    SET {set_clause}
                    WHERE aspirante_id = %s
                    RETURNING *;
                """

                cur.execute(query, values + [aspirante_id])
                updated_row = cur.fetchone()
                columnas = [desc[0] for desc in cur.description]
                conn.commit()

                if updated_row:
                    return dict(zip(columnas, updated_row))
                return None
    except Exception as e:
        print("❌ Error al actualizar perfil del creador:", e)
        return None


def actualizar_aspirantes_perfil(perfil_id: int, perfil_data):
    """Actualiza un perfil de creador"""
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE aspirantes_perfil 
                    SET aspirante_id = %s, perfil = %s, biografia_actual = %s, seguidores = %s, 
                        cantidad_videos = %s, engagement_rate = %s, clasificacion_actual = %s
                    WHERE id = %s
                    RETURNING id, aspirante_id, perfil, biografia_actual, seguidores, cantidad_videos, engagement_rate, clasificacion_actual
                """, (
                    perfil_data["aspirante_id"],
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
                        "aspirante_id": row[1],
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
                return perfil

    except Exception as e:
        print("❌ Error al actualizar perfil de creador:", e)
        return None


def eliminar_aspirantes_perfil(perfil_id: int):
    """Elimina un perfil de creador"""
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM aspirantes_perfil WHERE id = %s", (perfil_id,))
                affected_rows = cur.rowcount
                conn.commit()
                return affected_rows > 0

    except Exception as e:
        print("❌ Error al eliminar perfil de creador:", e)
        return False


# -----------------------------------
# -----------------------------------

def obtener_aspirantes_db():
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                sql = """
                    SELECT 
                        c.id, 
                        c.usuario, 
                        c.nickname, 
                        c.nombre_real, 
                        c.telefono,
                        ec.nombre AS estado_nombre,
                        COALESCE(c.fecha_solicitud, c.creado_en) AS creado_en
                    FROM aspirantes c
                    INNER JOIN aspirantes_estados ec ON c.estado_id = ec.id
                    WHERE c.activo = TRUE
                      AND c.estado_id IN (3,4,5,7)
                    ORDER BY creado_en ASC;
                """

                cur.execute(sql)
                datos = cur.fetchall()
                columnas = [desc[0] for desc in cur.description]
                resultados = [dict(zip(columnas, fila)) for fila in datos]

                return resultados
    except Exception as e:
        print("❌ Error al obtener aspirantes:", e)
        return []




def obtener_aspirantes_invitacion():
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        c.id, 
                        c.usuario, 
                        c.nickname, 
                        c.nombre_real, 
                        c.telefono,
                        ec.nombre AS estado_nombre,
                        c.creado_en,
                        d.puntaje_total_categoria
                    FROM aspirantes c
                    INNER JOIN aspirantes_estados ec ON c.estado_id = ec.id
                    INNER JOIN aspirantes_perfil d ON d.aspirante_id=c.id
                    WHERE c.activo = TRUE AND c.estado_id IN (4,5)
                    ORDER BY c.usuario ASC;
                """)
                datos = cur.fetchall()
                columnas = [desc[0] for desc in cur.description]
                resultados = [dict(zip(columnas, fila)) for fila in datos]
                return resultados
    except Exception as e:
        print("❌ Error al obtener aspirantes:", e)
        return []



def obtener_todos_los_participantes_db():
    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT 
                        a.id,
                        a.usuario AS username,
                        a.nickname,
                        a.nombre_real,
                        COALESCE(a.nickname, a.nombre_real, a.usuario, a.telefono) AS display_name,
                        a.email,
                        a.telefono,
                        a.whatsapp,
                        a.foto_url,
                        a.foto_url_mini,
                        a.verificado,
                        a.activo,
                        ae.nombre AS estado_nombre,
                        a.creado_en,
                        a.actualizado_en,
                        'aspirante' AS tipo_usuario,
                        NULL AS rol
                    FROM aspirantes a
                    LEFT JOIN aspirantes_estados ae
                        ON a.estado_id = ae.id
                    WHERE a.activo = TRUE

                    UNION ALL

                    SELECT
                        u.id,
                        u.username,
                        NULL AS nickname,
                        u.nombre_completo AS nombre_real,
                        COALESCE(u.nombre_completo, u.username, u.email, u.telefono) AS display_name,
                        u.email,
                        u.telefono,
                        NULL AS whatsapp,
                        NULL AS foto_url,
                        NULL AS foto_url_mini,
                        NULL AS verificado,
                        u.activo,
                        u.grupo AS estado_nombre,
                        u.creado_en,
                        u.actualizado_en,
                        'administrador' AS tipo_usuario,
                        ur.nombre AS rol
                    FROM administradores u
                    LEFT JOIN administradores_roles ur
                        ON ur.id = u.administradores_roles_id
                    WHERE u.activo = TRUE

                    ORDER BY actualizado_en DESC NULLS LAST, creado_en DESC;
                """)
                resultados = cur.fetchall()
                return resultados
    except Exception as e:
        print("❌ Error al obtener todos los participantes:", e)
        return []

def obtener_aspirantes_perfil(aspirante_id):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                        SELECT
                            pc.id,
                            pc.aspirante_id,
                            pc.edad,
                            pc.seguidores,
                            pc.siguiendo,
                            pc.videos,
                            pc.likes,
                            pc.duracion_emisiones,
                            pc.dias_emisiones,
                            pc.apariencia,
                            pc.engagement,
                            pc.calidad_contenido,
                            pc.frecuencia_lives,
                            pc.creado_en,
                            pc.actualizado_en,
                            pc.tiempo_disponible,
                            pc.experiencia_otras_plataformas,
                            pc.intereses,
                            pc.tipo_contenido,
                            pc.potencial_estimado,
                            pc.potencial_estimado,
                            pc.campo_estudios,
                            pc.estudios,
                            pc.horario_preferido,
                            pc.intencion_trabajo,
                            pc.usuario,
                            pc.biografia_sugerida,
                            pc.genero,
                            pc.telefono,
                            pc.pais,
                            pc.ciudad,
                            pc.zona_horaria,
                            pc.nombre,
                            pc.usuario_evalua,
                            pc.experiencia_otras_plataformas_otro_nombre,
                            pc.eval_foto,
                            pc.eval_biografia,
                            pc.biografia,
                            pc.estado,
                            pc.metadata_videos,
                            pc.actividad_actual,
                            pc.idioma,
                            pc.diagnostico,
                            pc.mejoras_sugeridas,
                            pc.fecha_entrevista,
                            pc.entrevista,
                            pc.estado_evaluacion,
                            -- Campo traído desde la tabla aspirantes
                            c.encuesta_terminada
                        FROM aspirantes_perfil pc
                        INNER JOIN aspirantes c
                            ON pc.aspirante_id = c.id
                        WHERE pc.aspirante_id = %s;
                """, (aspirante_id,))
                fila = cur.fetchone()
                columnas = [desc[0] for desc in cur.description]
                if fila:
                    return dict(zip(columnas, fila))
                return None
    except Exception as e:
        print("❌ Error al obtener perfil del creador:", e)
        return None

def obtener_aspirantes_perfil_entrevista_invitacion(aspirante_id):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        apto,
                        entrevista,
                        fecha_entrevista,
                        calificacion_entrevista,
                        invitacion_tiktok,
                        acepta_invitacion,
                        fecha_incorporacion,
                        observaciones_finales   -- 🔹 agregado
                    FROM aspirantes_perfil
                    WHERE aspirante_id = %s
                """, (aspirante_id,))
                fila = cur.fetchone()
                if not fila:
                    return None
                columnas = [desc[0] for desc in cur.description]
                return dict(zip(columnas, fila))
    except Exception as e:
        print("❌ Error al obtener perfil del creador:", e)
        return None



def obtener_datos_mejoras_aspirantes_perfil(aspirante_id):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT  edad,genero,idioma,estudios,pais,actividad_actual,seguidores, siguiendo, likes, videos, duracion_emisiones,dias_emisiones,apariencia,engagement,calidad_contenido,estudios,actividad_actual,tiempo_disponible,frecuencia_lives,experiencia_otras_plataformas,intereses,tipo_contenido,intencion_trabajo,eval_foto,biografia,eval_biografia,biografia_sugerida,metadata_videos,potencial_estimado,
                    puntaje_total,
                    puntaje_estadistica,
                    puntaje_cualitativo,
                    puntaje_general,
                    puntaje_habitos,
                    puntaje_total_categoria,
                    puntaje_estadistica_categoria,
                    puntaje_habitos_categoria,
                    puntaje_general_categoria,
                    puntaje_cualitativo_categoria
                    FROM aspirantes_perfil
                    WHERE aspirante_id = %s
                    LIMIT 1
                """, (aspirante_id,))
                fila = cur.fetchone()
                columnas = [desc[0] for desc in cur.description]
                if fila:
                    return dict(zip(columnas, fila))
                return None
    except Exception as e:
        print("❌ Error al obtener perfil del creador:", e)
        return None

def obtener_biografia_aspirantes_perfil(aspirante_id):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT biografia
                    FROM aspirantes_perfil
                    WHERE aspirante_id = %s
                    LIMIT 1
                """, (aspirante_id,))
                fila = cur.fetchone()
                columnas = [desc[0] for desc in cur.description]
                if fila:
                    return dict(zip(columnas, fila))
                return None
    except Exception as e:
        print("❌ Error al obtener perfil del creador:", e)
        return None

def obtener_datos_estadisticas_aspirantes_perfil(aspirante_id):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        seguidores,
                        siguiendo,
                        videos,
                        likes,
                        duracion_emisiones
                    FROM aspirantes_perfil
                    WHERE aspirante_id = %s
                    LIMIT 1
                """, (aspirante_id,))
                fila = cur.fetchone()
                columnas = [desc[0] for desc in cur.description]
                if fila:
                    return dict(zip(columnas, fila))
                return None
    except Exception as e:
        print("❌ Error al obtener perfil del creador:", e)
        return None

def obtener_puntajes_aspirantes_perfil(aspirante_id):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT puntaje_general, puntaje_estadistica, puntaje_cualitativo, puntaje_habitos,puntaje_general_categoria, puntaje_estadistica_categoria, puntaje_cualitativo_categoria, puntaje_habitos_categoria,puntaje_total,puntaje_total_categoria
                    FROM aspirantes_perfil
                    WHERE aspirante_id = %s
                    LIMIT 1
                """, (aspirante_id,))
                fila = cur.fetchone()
                columnas = [desc[0] for desc in cur.description]
                if fila:
                    return dict(zip(columnas, fila))
                return None
    except Exception as e:
        print("❌ Error al obtener perfil del creador:", e)
        return None

def actualizar_datos_aspirantes_perfil(aspirante_id, datos_dict):
    try:
        # Debug
        print("📥 Datos recibidos en actualizar_datos_aspirantes_perfil:", datos_dict)

        # Aplanado “suave”
        flat_dict = {}
        for key, value in datos_dict.items():
            flat_dict[key] = value if not isinstance(value, dict) else value
        print("📦 Dict después de aplanar:", flat_dict)

        campos_validos = [
            # Datos personales y generales
            "nombre", "edad", "genero", "pais", "ciudad", "zona_horaria",
            "idioma", "campo_estudios", "estudios", "actividad_actual",
            "puntaje_general", "puntaje_general_categoria", "telefono",
            # Evaluación manual/cualitativa
            "biografia", "apariencia", "engagement", "calidad_contenido",
            "potencial_estimado", "usuario_evalua", "biografia_sugerida",
            "eval_biografia", "eval_foto", "metadata_videos",
            "puntaje_cualitativo", "puntaje_cualitativo_categoria",
            # Estadísticas del perfil
            "seguidores", "siguiendo", "videos", "likes",
            "duracion_emisiones", "dias_emisiones",
            "puntaje_estadistica", "puntaje_estadistica_categoria",
            # Preferencias y hábitos
            "tiempo_disponible", "frecuencia_lives",
            "experiencia_otras_plataformas", "experiencia_otras_plataformas_otro_nombre",
            "intereses", "tipo_contenido", "horario_preferido", "intencion_trabajo",
            "puntaje_habitos", "puntaje_habitos_categoria",
            # Resumen
            "estado", "diagnostico", "mejoras_sugeridas",
            "puntaje_total", "puntaje_total_categoria",
            "fecha_entrevista", "entrevista",
            "observaciones_finales", "estado_evaluacion",
        ]

        # Construir UPDATE dinámico para aspirantes_perfil
        campos = []
        valores = []
        for campo in campos_validos:
            if campo in flat_dict:
                valor = flat_dict[campo]
                if isinstance(valor, dict):
                    print(f"📝 Serializando {campo} →", valor)
                    valor = json.dumps(valor)
                campos.append(f"{campo} = %s")
                valores.append(valor)

        if not campos:
            raise ValueError("⚠️ No se enviaron campos válidos para actualizar")

        campos.append("actualizado_en = NOW()")
        valores.append(aspirante_id)

        query_perfil = f"""
            UPDATE aspirantes_perfil
            SET {', '.join(campos)}
            WHERE aspirante_id = %s;
        """

        # Posible update a aspirantes.telefono (opcional, sólo si viene en el payload)
        telefono_nuevo = flat_dict.get("telefono")
        telefono_nuevo = limpiar_telefono(telefono_nuevo) if telefono_nuevo else None

        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # 1) UPDATE aspirantes_perfil
                print("📤 Query aspirantes_perfil:", query_perfil)
                print("📤 Valores aspirantes_perfil:", valores)
                cur.execute(query_perfil, valores)

                # 2) UPDATE aspirantes.telefono (si aplica)
                if telefono_nuevo:
                    cur.execute(
                        "UPDATE aspirantes SET telefono = %s, actualizado_en = NOW() WHERE id = %s",
                        (telefono_nuevo, aspirante_id)
                    )
                    print(f"📞 aspirantes.telefono actualizado → {telefono_nuevo}")

                conn.commit()
                print(f"✅ Datos del perfil del creador {aspirante_id} actualizados (y teléfono de aspirantes si aplicaba).")

    except Exception as e:
        print(f"❌ Error al actualizar datos del perfil del creador {aspirante_id}: {e}")
        raise


def actualizar_aspirantes_perfil_(aspirante_id, evaluacion_dict):
    try:
        campos = []
        valores = []

        for campo in ['apariencia', 'engagement', 'calidad_contenido', 'puntaje_total', 'puntaje_cualitativo', 'mejoras_sugeridas_manual','usuario_evalua_inicial']:
            if campo in evaluacion_dict:
                campos.append(f"{campo} = %s")
                valores.append(evaluacion_dict[campo])

        if not campos:
            raise ValueError("No se enviaron campos válidos para actualizar")

        # Actualizar el campo actualizado_en también
        campos.append("actualizado_en = NOW()")

        valores.append(aspirante_id)

        query = f"""
            UPDATE aspirantes_perfil
            SET {', '.join(campos)}
            WHERE aspirante_id = %s;
        """

        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(query, valores)
                conn.commit()

    except Exception as e:
        print("❌ Error al actualizar evaluación:", e)
        raise

def obtener_estadisticas_evaluacion():
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM aspirantes;
            """)
            total_aspirantes = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM aspirantes_perfil 
                WHERE puntaje_total IS NULL OR puntaje_total = 0;
            """)
            evaluaciones_pendientes = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM aspirantes_perfil 
                WHERE puntaje_total >= 3.0;
            """)
            aprobados = cur.fetchone()[0]

            cur.execute("""
                SELECT AVG(puntaje_total) FROM aspirantes_perfil 
                WHERE puntaje_total IS NOT NULL AND puntaje_total > 0;
            """)
            promedio = cur.fetchone()[0] or 0

            return {
                "totalAspirantes": total_aspirantes,
                "evaluacionesPendientes": evaluaciones_pendientes,
                "aprobados": aprobados,
                "promedioPuntuacion": float(promedio)
            }

def guardar_en_bd(agendamiento, meet_link, usuario_actual_id, creado):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO agendamientos (
                        aspirante_id, fecha_inicio, fecha_fin, titulo, descripcion,
                        link_meet, estado, responsable_id, google_event_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'programado', %s, %s)
                """, (
                    agendamiento.aspirante_id,
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
        return False


def obtener_aspirante_id_por_usuario(usuario: str) -> Optional[int]:
    """Busca el aspirante_id en la base de datos por nombre de usuario"""
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM aspirantes WHERE usuario = %s", (usuario,))
                result = cur.fetchone()

                return result[0] if result else None

    except Exception as e:
        print(f"⚠️ Error buscando creador por usuario {usuario}: {str(e)}")
        return None


def eliminar_aspirantes_perfil(perfil_id: int):
    """Elimina un perfil de creador"""
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM aspirantes_perfil WHERE id = %s", (perfil_id,))
                affected_rows = cur.rowcount
                conn.commit()
                return affected_rows > 0

    except Exception as e:
        print("❌ Error al eliminar perfil de creador:", e)
        return False


def obtener_todos_manager():
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT a.id, a.username, a.nombre_completo, ur.nombre AS rol, a.grupo, a.activo
                    FROM administradores a
                    INNER JOIN administradores_roles ur ON ur.id = a.administradores_roles_id
                    WHERE ur.nombre = 'Manager'
                    ORDER BY a.nombre_completo DESC
                """)
                usuarios = []
                for row in cur.fetchall():
                    usuarios.append({
                        "id": row[0],
                        "username": row[1],
                        "nombre_completo": row[2],
                        "rol": row[3],
                        "grupo": row[4],
                        "activo": row[5]
                    })
                return usuarios
    except Exception as e:
        print("❌ Error al obtener usuarios manager:", e)
        return []

def actualizar_evaluacion_creador(aspirante_id: int, datos: dict):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # Mapear estado -> estado_id
                estado_map = {
                    "ENTREVISTA": 4,
                    "NO APTO": 7,
                    "INVITACION TIKTOK": 5
                }

                # Tomar el valor de forma segura
                estado_raw = datos.get("estado_evaluacion")

                # Normalizar (quita espacios y mayúsculas)
                estado_str = estado_raw.strip().upper() if estado_raw else None

                # Si no encuentra el estado, usa un número por defecto (ejemplo: 99)
                estado_id = estado_map.get(estado_str, 99)

                fecha_actual = datetime.now()

                # 🔹 Actualizar tabla aspirantes (estado_id)
                cur.execute("""
                    UPDATE aspirantes
                    SET estado_id = %s
                    WHERE id = %s
                """, (estado_id, aspirante_id))

                # 🔹 Verificar si viene de inicial o resumen
                if "usuario_evaluador_inicial" in datos:
                    # Caso: Evaluación inicial
                    cur.execute("""
                        UPDATE aspirantes_perfil
                        SET estado_evaluacion = %s,
                            fecha_evaluacion_inicial = %s,
                            usuario_evaluador_inicial = %s
                        WHERE aspirante_id = %s
                        RETURNING estado_evaluacion, fecha_evaluacion_inicial, usuario_evaluador_inicial
                    """, (
                        datos["estado_evaluacion"],
                        fecha_actual,
                        datos["usuario_evaluador_inicial"],
                        aspirante_id
                    ))
                elif "usuario_evaluador_resumen" in datos:
                    # Caso: Resumen
                    cur.execute("""
                        UPDATE aspirantes_perfil
                        SET estado_evaluacion = %s,
                            puntaje_total = %s,
                            puntaje_total_categoria = %s,
                            usuario_evalua = %s,  -- campo string en BD
                            actualizado_en = %s
                        WHERE aspirante_id = %s
                        RETURNING estado_evaluacion, puntaje_total, puntaje_total_categoria, usuario_evalua
                    """, (
                        datos["estado_evaluacion"],
                        datos.get("puntaje_total"),
                        datos.get("puntaje_total_categoria"),
                        str(datos["usuario_evaluador_resumen"]),  # guardar como string
                        fecha_actual,
                        aspirante_id
                    ))
                else:
                    raise ValueError("Datos inválidos: faltan campos de evaluador")

                row = cur.fetchone()
                conn.commit()

                return dict(zip([desc[0] for desc in cur.description], row))

    except Exception as e:
        raise

# ENTREVISTAS E INVITACIONES

def actualizar_aspirantes_perfil_entrevista(aspirante_id: int, datos: dict):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # Generar dinámicamente SET de columnas según los datos recibidos
                set_clauses = []
                values = []
                for key, value in datos.items():
                    set_clauses.append(f"{key} = %s")
                    values.append(value)

                if not set_clauses:
                    return False  # No hay datos para actualizar

                sql = f"""
                    UPDATE aspirantes_perfil
                    SET {', '.join(set_clauses)}
                    WHERE aspirante_id = %s
                """
                values.append(aspirante_id)
                cur.execute(sql, tuple(values))
                conn.commit()
                return True
    except Exception as e:
        print("❌ Error al actualizar aspirantes_perfil:", e)
        return False


def obtener_entrevista_por_creador(aspirante_id: int):
    bogota = pytz.timezone("America/Bogota")
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                sql = """
                    SELECT e.id, e.aspirante_id, 
                           COALESCE(a.fecha_inicio, e.fecha_programada) AS fecha_programada,
                           e.usuario_programa, e.realizada, e.fecha_realizada, 
                           e.usuario_evalua, e.resultado, e.observaciones, e.creado_en,
                           e.evento_id
                    FROM entrevistas e
                    LEFT JOIN agendamientos a
                        ON e.evento_id = a.google_event_id
                    WHERE e.aspirante_id = %s
                    ORDER BY e.fecha_programada ASC
                    LIMIT 1
                """
                cur.execute(sql, (aspirante_id,))
                row = cur.fetchone()
                if not row:
                    return None

                # Conversión UTC → America/Bogota
                fecha_programada = row[2]
                if fecha_programada and fecha_programada.tzinfo is None:
                    fecha_programada = fecha_programada.replace(tzinfo=pytz.utc)
                if fecha_programada:
                    fecha_programada = fecha_programada.astimezone(bogota)

                fecha_realizada = row[5]
                if fecha_realizada and fecha_realizada.tzinfo is None:
                    fecha_realizada = fecha_realizada.replace(tzinfo=pytz.utc)
                if fecha_realizada:
                    fecha_realizada = fecha_realizada.astimezone(bogota)

                resultado = {
                    "id": row[0],
                    "aspirante_id": row[1],
                    "fecha_programada": fecha_programada,
                    "usuario_programa": row[3],
                    "realizada": row[4],
                    "fecha_realizada": fecha_realizada,
                    "usuario_evalua": row[6],
                    "resultado": row[7],
                    "observaciones": row[8],
                    "creado_en": row[9],
                    "evento_id": row[10],
                }
                return resultado
    except Exception as e:
        print(f"Error al obtener entrevista por creador: {e}")
        return None

# Función para actualizar entrevista
def actualizar_entrevista_por_creador(aspirante_id: int, payload: dict) -> dict | None:
    """
    Actualiza la entrevista más reciente del creador y devuelve el registro actualizado.
    Retorna None si no hay entrevista para ese creador.
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # 1) Obtener la entrevista más reciente del creador
                cur.execute("""
                    SELECT id
                    FROM entrevistas
                    WHERE aspirante_id = %s
                    ORDER BY creado_en DESC
                    LIMIT 1
                """, (aspirante_id,))
                row = cur.fetchone()
                if not row:
                    return None
                entrevista_id = row[0]

                # 2) Campos válidos en la tabla entrevistas (según tu schema)
                campos_validos = {
                    "resultado",
                    "observaciones",
                    "usuario_evalua",
                    "aspecto_tecnico",
                    "presencia_carisma",
                    "interaccion_audiencia",
                    "profesionalismo_normas",
                    "evaluacion_global",
                }

                sets = []
                values = []
                for k, v in payload.items():
                    if k in campos_validos:
                        sets.append(f"{k} = %s")
                        values.append(v)

                if sets:
                    sql = f"""
                        UPDATE entrevistas
                        SET {', '.join(sets)}, modificado_en = NOW()
                        WHERE id = %s
                        RETURNING
                            id,
                            aspirante_id,
                            usuario_evalua,
                            resultado,
                            observaciones,
                            aspecto_tecnico,
                            presencia_carisma,
                            interaccion_audiencia,
                            profesionalismo_normas,
                            evaluacion_global,
                            creado_en
                    """
                    values.append(entrevista_id)
                    cur.execute(sql, tuple(values))
                else:
                    # Si no hay cambios, solo lee el registro actual
                    cur.execute("""
                        SELECT
                            id,
                            aspirante_id,
                            usuario_evalua,
                            resultado,
                            observaciones,
                            aspecto_tecnico,
                            presencia_carisma,
                            interaccion_audiencia,
                            profesionalismo_normas,
                            evaluacion_global,
                            creado_en
                        FROM entrevistas
                        WHERE id = %s
                    """, (entrevista_id,))

                updated = cur.fetchone()
                if not updated:
                    return None

                conn.commit()
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, updated))
    except Exception as e:
        print(f"Error al actualizar entrevista por creador: {e}")
        return None

# Función para insertar invitación
def insertar_invitacion(datos: dict):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                columnas = ', '.join(datos.keys())
                placeholders = ', '.join(['%s'] * len(datos))
                sql = f"""
                    INSERT INTO invitaciones ({columnas})
                    VALUES ({placeholders})
                    RETURNING id, creado_en
                """
                cur.execute(sql, tuple(datos.values()))
                row = cur.fetchone()
                conn.commit()
                return {"id": row[0], "creado_en": row[1]}
    except Exception as e:
        print("❌ Error al insertar invitación:", e)
        return None

# Función para obtener invitaciones por aspirante_id
def obtener_invitacion_por_creador(aspirante_id: int):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                sql = """
                    -- obtener_invitaciones_por_creador
                    SELECT id, aspirante_id, fecha_invitacion, usuario_invita, estado,
                           acepta_invitacion, manager_id, fecha_incorporacion, observaciones, creado_en
                    FROM invitaciones
                    WHERE aspirante_id = %s
                    ORDER BY creado_en DESC
                """
                cur.execute(sql, (aspirante_id,))
                rows = cur.fetchall()
                invitaciones = []
                for row in rows:
                    invitaciones.append({
                        "id": row[0],
                        "aspirante_id": row[1],
                        "fecha_revision": row[2],
                        "usuario_revision": row[3],
                        "estado": row[4],
                        "acepta_invitacion": row[5],
                        "observaciones": row[6],
                        "creado_en": row[7],
                    })
                return invitaciones
    except Exception as e:
        print("❌ Error al obtener invitaciones:", e)
        return None

def actualizar_invitacion_por_creador(aspirante_id: int, datos: dict):
    if not datos:
        return None  # Nada que actualizar

    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                set_clauses = [f"{k} = %s" for k in datos.keys()]
                values = list(datos.values())

                sql = f"""
                    UPDATE invitaciones
                       SET {', '.join(set_clauses)}
                     WHERE aspirante_id = %s
                 RETURNING
                        id,
                        aspirante_id,
                        fecha_invitacion,
                        usuario_invita,
                        estado,
                        acepta_invitacion,
                        manager_id,
                        fecha_incorporacion,
                        observaciones,
                        creado_en
                """
                values.append(aspirante_id)
                cur.execute(sql, tuple(values))
                row = cur.fetchone()
                conn.commit()

                if not row:
                    return None

                return {
                    "id": row[0],
                    "aspirante_id": row[1],
                    "fecha_invitacion": row[2],
                    "usuario_invita": row[3],
                    "estado": row[4],
                    "acepta_invitacion": row[5],
                    "manager_id": row[6],
                    "fecha_incorporacion": row[7],
                    "observaciones": row[8],
                    "creado_en": row[9],
                }
    except Exception as e:
        print("❌ Error al actualizar invitación:", e)
        return None


ESTADO_MAP = {
    "Entrevista": 4,
    "Invitación": 5,
    "Rechazado": 7,
}
ESTADO_DEFAULT = 99  # si te mandan algo desconocido

def actualizar_estado_creador(aspirante_id: int, estado_id: int):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE aspirantes
                       SET estado_id = %s
                     WHERE id = %s
                 RETURNING id, estado_id
                """, (estado_id, aspirante_id))
                row = cur.fetchone()
                conn.commit()
                if not row:
                    return None
                return {"id": row[0], "estado_id": row[1]}
    except Exception as e:
        raise

def buscar_aspirante_por_usuario_tiktok(usuario_tiktok: str):
    """Busca un creador en la tabla aspirantes por el usuario de TikTok usando with para cerrar la conexión."""
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id,nickname FROM aspirantes WHERE usuario = %s LIMIT 1",
                    (usuario_tiktok,)
                )
                row = cur.fetchone()
                if row:
                    columns = [desc[0] for desc in cur.description]
                    return dict(zip(columns, row))
                else:
                    return None
    except Exception as e:
        print("❌ Error al buscar creador por usuario de TikTok:", e)
        return None


def normalizar_numero(numero: str) -> str:
    numero = numero.strip().replace(" ", "").replace("-", "")
    numero = numero.replace("+", "").replace("@c.us", "").replace("@wa.me", "")
    numero = re.sub(r"\D", "", numero)  # elimina cualquier otro símbolo no numérico
    return numero


def buscar_usuario_por_telefono(numero: str):
    try:
        numero = normalizar_numero(numero)
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # Buscar en aspirantes
                cur.execute("""
                    SELECT c.id, c.nickname, COALESCE(NULLIF(TRIM(c.nickname), ''), c.nombre_real) AS nombre ,
                           COALESCE(r.nombre, 'aspirante') AS rol
                    FROM aspirantes c
                    LEFT JOIN roles r ON c.rol_id = r.id
                    WHERE c.telefono = %s OR c.whatsapp = %s
                    LIMIT 1;
                """, (numero, numero))
                row = cur.fetchone()
                if row:
                    return dict(zip([desc[0] for desc in cur.description], row))

                # Buscar en administradores
                cur.execute("""
                    SELECT a.id, a.username AS nickname,
                           a.nombre_completo AS nombre,
                           COALESCE(ur.nombre, 'admin') AS rol
                    FROM administradores a
                    LEFT JOIN administradores_roles ur ON ur.id = a.administradores_roles_id
                    WHERE a.telefono = %s
                    LIMIT 1;
                """, (numero,))
                row = cur.fetchone()
                if row:
                    return dict(zip([desc[0] for desc in cur.description], row))
                return None

    except Exception as e:
        import traceback
        print("❌ Error al buscar usuario por teléfono:", e)
        traceback.print_exc()
        return None


def marcar_encuesta_completada(numero: str) -> bool:
    """Marca la encuesta como completada en la tabla aspirantes."""
    try:
        numero = normalizar_numero(numero)
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE aspirantes
                    SET encuesta_terminada = TRUE
                    WHERE telefono = %s OR whatsapp = %s
                    RETURNING id;
                """, (numero, numero))
                row = cur.fetchone()
                conn.commit()

                if row:
                    print(f"✅ Encuesta marcada como completada para ID {row[0]}")
                    return True
                print("⚠️ No se encontró usuario para actualizar encuesta.")
                return False

    except Exception as e:
        import traceback
        print("❌ Error al marcar encuesta como completada:", e)
        traceback.print_exc()
        return False

def marcar_encuesta_no_finalizada(numero: str) -> bool:
    """Marca la encuesta como completada en la tabla aspirantes."""
    try:
        numero = normalizar_numero(numero)
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE aspirantes
                    SET encuesta_terminada = FALSE
                    WHERE telefono = %s OR whatsapp = %s
                    RETURNING id;
                """, (numero, numero))
                row = cur.fetchone()
                conn.commit()

                if row:
                    print(f"✅ Encuesta marcada como completada para ID {row[0]}")
                    return True
                print("⚠️ No se encontró usuario para actualizar encuesta.")
                return False

    except Exception as e:
        import traceback
        print("❌ Error al marcar encuesta como completada:", e)
        traceback.print_exc()
        return False

def encuesta_finalizada(numero: str) -> bool:
    """Retorna True si el usuario completó la encuesta, False en caso contrario."""
    try:
        numero = normalizar_numero(numero)
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT encuesta_terminada
                    FROM aspirantes
                    WHERE telefono = %s OR whatsapp = %s
                    LIMIT 1;
                """, (numero, numero))
                row = cur.fetchone()
                if row:
                    estado = bool(row[0])
                    print(f"🔎 Encuesta finalizada ({numero}): {estado}")
                    return estado
                return False
    except (OperationalError, DatabaseError) as e:
        print(f"❌ Error de base de datos al verificar encuesta terminada: {e}")
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"❌ Error inesperado al verificar encuesta terminada: {e}")
        traceback.print_exc()
        return False


def obtener_ultimo_paso_respondido(numero: str) -> int | None:

    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT MAX(paso)
                    FROM aspirantes_perfil_flujo_temp
                    WHERE telefono = %s
                    """,
                    (numero,)
                )
                row = cur.fetchone()
                if row and row[0]:
                    return int(row[0])
                return None
    except (OperationalError, DatabaseError) as e:
        print(f"❌ Error de base de datos al obtener último paso respondido: {e}")
        traceback.print_exc()
        return None
    except Exception as e:
        print(f"❌ Error inesperado al obtener último paso respondido: {e}")
        traceback.print_exc()
        return None


def formatear_numero(numero: str) -> str:
    # Quita espacios, guiones y paréntesis
    numero = re.sub(r"[^\d+]", "", numero)
    # Quita el '+' si lo tiene
    if numero.startswith('+'):
        numero = numero[1:]
    return numero

def actualizar_telefono_aspirante(aspirante_id: int, numero: str):
    try:
        numero_formateado = formatear_numero(numero)
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE aspirantes
                    SET telefono = %s, whatsapp = %s, actualizado_en = now()
                    WHERE id = %s
                    """,
                    (numero_formateado, numero_formateado, aspirante_id)
                )
                conn.commit()
                return cur.rowcount > 0  # True si se actualizó alguna fila
    except Exception as e:
        print("❌ Error al actualizar teléfono de aspirante:", e)
        return False


def crear_invitacion_minima(aspirante_id: int, usuario_invita: int, manager_id: int = None, estado: str = "sin programar"):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # Verificar si ya existe una invitación
                cur.execute(
                    "SELECT id FROM invitaciones WHERE aspirante_id = %s",
                    (aspirante_id,)
                )
                if cur.fetchone():
                    print(f"⚠️ Ya existe una invitación para el creador {aspirante_id}.")
                    return False

                # Insertar solo los campos mínimos
                cur.execute(
                    """
                    INSERT INTO invitaciones (
                        aspirante_id, usuario_invita, manager_id, estado, creado_en
                    )
                    VALUES (%s, %s, %s, %s, NOW())
                    RETURNING aspirante_id, usuario_invita, manager_id, estado, creado_en
                    """,
                    (aspirante_id, usuario_invita, manager_id, estado)
                )

                row = cur.fetchone()
                conn.commit()

                if row:
                    columns = [desc[0] for desc in cur.description]
                    invitacion = dict(zip(columns, row))
                    print(f"✅ Invitación mínima creada correctamente para creador {aspirante_id}")
                    return invitacion

                print(f"⚠️ No se retornaron datos al crear la invitación para creador {aspirante_id}.")
                return None

    except Exception as e:
        print(f"❌ Error al crear invitación mínima para creador {aspirante_id}:", e)
        return None



def obtener_invitacion_por_creador(aspirante_id: int):
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 
                        id,
                        aspirante_id,
                        fecha_invitacion,
                        usuario_invita,
                        manager_id,
                        estado,
                        acepta_invitacion,
                        fecha_incorporacion,
                        observaciones,
                        creado_en
                    FROM invitaciones
                    WHERE aspirante_id = %s
                    ORDER BY fecha_invitacion DESC
                    LIMIT 1;
                    """,
                    (aspirante_id,)
                )
                row = cur.fetchone()
                if row:
                    columns = [desc[0] for desc in cur.description]
                    invitacion = dict(zip(columns, row))
                    return invitacion
                return None
    except Exception as e:
        print(f"❌ Error al consultar invitación de creador {aspirante_id}: {e}")
        return None

#
# def obtener_potencial_estimado(aspirante_id: int):
#     try:
#         # Validación defensiva
#         if not isinstance(aspirante_id, int):
#             print("❌ Error: aspirante_id inválido (debe ser int).")
#             return 2  # Valor por defecto
#
#         with get_connection_context() as conn:
#             with conn.cursor() as cur:
#                 cur.execute("""
#                     SELECT potencial_estimado
#                     FROM aspirantes_perfil
#                     WHERE aspirante_id = %s;
#                 """, (aspirante_id,))
#
#                 row = cur.fetchone()
#
#         # Si no hay fila → usar 2
#         if row is None:
#             print(f"⚠️ No existe registro de potencial_estimado para aspirante_id={aspirante_id}. Usando valor=2 (default)")
#             return 0
#
#         valor = row[0]
#
#         # Si hay fila pero valor es NULL → usar 2
#         if valor is None:
#             print(f"⚠️ potencial_estimado es NULL para aspirante_id={aspirante_id}. Usando valor=2 (default)")
#             return 0
#
#         # Valor válido
#         print(f"✅ potencial_estimado obtenido para aspirante_id={aspirante_id}: {valor}")
#         return valor
#
#     except Exception as e:
#         print(f"❌ Error al obtener potencial_estimado (aspirante_id={aspirante_id}): {e}")
#         return 2  # fallback seguro
#
#


def guardar_o_actualizar_token_db(session_id: str, token: str):
    try:
        with get_connection_public_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 🔍 Buscar registro con WABA pero sin token aún
                cur.execute("""
                    SELECT id, waba_id
                    FROM whatsapp_business_accounts
                    WHERE session_id = %s
                      AND waba_id IS NOT NULL
                      AND access_token IS NULL
                      AND created_at >= NOW() - INTERVAL '10 minutes'
                    ORDER BY created_at DESC
                    LIMIT 1;
                """, (session_id,))
                existente = cur.fetchone()

                if existente:
                    # 🔄 Actualizar el token
                    cur.execute("""
                        UPDATE whatsapp_business_accounts
                        SET access_token = %s,
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id, waba_id, access_token;
                    """, (token, existente["id"]))
                    actualizado = cur.fetchone()

                    print(f"🔑 Token actualizado para registro ID: {actualizado['id']}")
                    return {
                        "status": "completado",
                        "id": actualizado["id"],
                        "access_token": actualizado["access_token"],
                        "waba_id": actualizado["waba_id"]
                    }

                # 🆕 Si no existe, insertar nuevo registro
                cur.execute("""
                    INSERT INTO whatsapp_business_accounts (
                        access_token, session_id, created_at, updated_at
                    ) VALUES (%s, %s, NOW(), NOW())
                    RETURNING id, access_token;
                """, (token, session_id))
                nuevo = cur.fetchone()

                print(f"🆕 Nuevo token guardado (registro ID: {nuevo['id']})")
                return {"status": "inserted", "id": nuevo["id"], "access_token": nuevo["access_token"]}

    except Exception as e:
        print("❌ Error en guardar_o_actualizar_token_db:", e)
        return {"status": "error", "error": str(e)}

def obtener_cuenta_por_phone_id(phone_number_id: str) -> dict | None:
    """Busca en la base de datos la cuenta de WhatsApp correspondiente al phone_number_id."""
    try:
        with get_connection_public_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        id,
                        waba_id,
                        access_token,
                        phone_number,
                        phone_number_id,
                        business_name,
                        subdominio,       -- ✅ importante
                        status
                    FROM whatsapp_business_accounts
                    WHERE phone_number_id = %s
                    LIMIT 1;
                """, (phone_number_id,))

                row = cur.fetchone()

        if not row:
            print(f"⚠️ No se encontró cuenta para phone_number_id={phone_number_id}")
            return None

        cuenta = {
            "id": row[0],
            "waba_id": row[1],
            "access_token": row[2],
            "phone_number": row[3],
            "phone_number_id": row[4],
            "business_name": row[5],
            "subdominio": row[6],    # ✅ ahora sí lo retorna
            "status": row[7],
        }

        print(
            f"✅ Cuenta WABA encontrada: {cuenta.get('business_name')} "
            f"({cuenta.get('phone_number')}) - Tenant/Subdominio: {cuenta.get('subdominio')}"
        )

        return cuenta

    except Exception as e:
        print(f"❌ Error al obtener cuenta WhatsApp (phone_number_id={phone_number_id}): {e}")
        return None


def obtener_cuenta_por_phone_number(phone_number: str) -> dict | None:
    """Busca en la base de datos la cuenta de WhatsApp correspondiente al phone_number."""

    try:
        # 🔹 Normalizar número: solo dígitos
        phone_number_normalizado = re.sub(r'\D', '', phone_number or "")

        if not phone_number_normalizado:
            print("⚠️ Número de teléfono vacío o inválido.")
            return None

        with get_connection_public_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        id,
                        waba_id,
                        access_token,
                        phone_number,
                        phone_number_id,
                        business_name,
                        subdominio,   -- ✅ ahora incluido
                        status
                    FROM whatsapp_business_accounts
                    WHERE phone_number = %s
                    LIMIT 1;
                """, (phone_number_normalizado,))

                row = cur.fetchone()

        if not row:
            print(f"⚠️ No se encontró cuenta para phone_number={phone_number_normalizado}")
            return None

        cuenta = {
            "id": row[0],
            "waba_id": row[1],
            "access_token": row[2],
            "phone_number": row[3],
            "phone_number_id": row[4],
            "business_name": row[5],
            "subdominio": row[6],   # ✅ agregado
            "status": row[7],
        }

        print(
            f"✅ Cuenta WABA encontrada: {cuenta['business_name']} "
            f"({cuenta['phone_number']}) - Tenant/Subdominio: {cuenta['subdominio']}"
        )
        return cuenta

    except Exception as e:
        print(f"❌ Error al obtener cuenta WhatsApp (phone_number={phone_number}): {e}")
        return None

def obtener_cuenta_por_subdominio(subdominio: str) -> dict | None:
    """Busca en la base de datos la cuenta de WhatsApp correspondiente al phone_number."""
    if not subdominio:
        return None

    try:
        # Usar context manager para asegurar que la conexión se devuelva al pool
        with get_connection_public_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        id,
                        waba_id,
                        access_token,
                        phone_number,
                        phone_number_id,
                        business_name,
                        subdominio,   -- ✅ ahora incluido
                        status
                    FROM whatsapp_business_accounts
                    WHERE subdominio = %s
                    LIMIT 1;
                """, (subdominio,))

                row = cur.fetchone()

        if not row:
            print(f"⚠️ No se encontró cuenta para subdominio={subdominio}")
            return None

        cuenta = {
            "id": row[0],
            "waba_id": row[1],
            "access_token": row[2],
            "phone_number": row[3],
            "phone_number_id": row[4],
            "business_name": row[5],
            "subdominio": row[6],   # ✅ agregado
            "status": row[7],
        }

        print(
            f"✅ Cuenta WABA encontrada: {cuenta['business_name']} "
            f"({cuenta['phone_number']}) - Tenant/Subdominio: {cuenta['subdominio']}"
        )
        return cuenta

    except Exception as e:
        print(f"❌ Error al obtener cuenta WhatsApp (phone_number={subdominio}): {e}")
        import traceback
        traceback.print_exc()
        return None


def guardar_o_actualizar_waba_db(session_id: str | None, waba_id: str):
    try:
        with get_connection_public_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 🔍 Buscar si existe registro previo con token pero sin WABA
                cur.execute("""
                    SELECT id, access_token
                    FROM whatsapp_business_accounts
                    WHERE session_id = %s
                      AND waba_id IS NULL
                      AND access_token IS NOT NULL
                      AND created_at >= NOW() - INTERVAL '10 minutes'
                    ORDER BY created_at DESC
                    LIMIT 1;
                """, (session_id,))
                existente = cur.fetchone()

                if existente:
                    # 🔄 Actualizar el waba_id
                    cur.execute("""
                        UPDATE whatsapp_business_accounts
                        SET waba_id = %s,
                            updated_at = NOW()
                        WHERE id = %s;
                    """, (waba_id, existente["id"]))

                    print(f"🔄 WABA actualizado en DB (ID: {existente['id']}) → {waba_id}")
                    return {
                        "status": "completado",
                        "id": existente["id"],
                        "access_token": existente.get("access_token"),
                        "waba_id": waba_id
                    }

                # 🆕 Si no existe, insertar nuevo registro
                cur.execute("""
                    INSERT INTO whatsapp_business_accounts (
                        waba_id, session_id, created_at, updated_at
                    ) VALUES (%s, %s, NOW(), NOW())
                    RETURNING id, waba_id;
                """, (waba_id, session_id))
                nuevo = cur.fetchone()

                print(f"🆕 Nuevo WABA guardado en DB (ID: {nuevo['id']}) → {waba_id}")
                return {"status": "inserted", "id": nuevo["id"], "waba_id": nuevo["waba_id"]}

    except Exception as e:
        print("❌ Error en guardar_o_actualizar_waba_db:", e)
        return {"status": "error", "error": str(e)}


def actualizar_phone_info_db(
    id: int,
    phone_number: str | None = None,
    phone_number_id: str | None = None,
    status: str = "connected"
) -> bool:
    try:

        # 🔹 Normalizar número: solo dígitos
        phone_number = re.sub(r'\D', '', phone_number or "")

        with get_connection_public_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE whatsapp_business_accounts
                    SET
                        phone_number = %s,
                        phone_number_id = %s,
                        status = %s,
                        updated_at = NOW()
                    WHERE id = %s;
                """, (phone_number, phone_number_id, status, id))

        print(f"✅ Registro WABA (id={id}) actualizado correctamente.")
        return True

    except Exception as e:
        print("❌ Error al actualizar información WABA en la base de datos:", e)
        return False




def get_connection_public_external():
    """
    Devuelve una conexión a la base de datos con search_path fijo a public,
    ignorando cualquier tenant/contexto.
    """
    conn = psycopg2.connect(EXTERNAL_DATABASE_URL)
    conn.autocommit = False

    with conn.cursor() as cur:
        cur.execute("SET search_path TO public;")

    return conn


def registrar_envio_mensaje(
    tenant: str,
    phone_number_id: str,
    display_phone_number: str,
    recipient: str,
    message_id: str,
    content: str | None = None,
):
    """
    Registra en la BD un mensaje enviado via WhatsApp Cloud API.
    Compatible con multi-tenant usando get_connection_context().
    """
    try:
        # Crea conexión y cursor como en tus otros módulos
        with get_connection_context() as conn:
            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO whatsapp_messages (
                        tenant,
                        phone_number_id,
                        display_phone_number,
                        recipient,
                        message_id,
                        direction,
                        content,
                        status,
                        last_status_at
                    )
                    VALUES (%s, %s, %s, %s, %s, 'outbound', %s, 'sent', NOW())
                    ON CONFLICT (message_id) DO NOTHING;
                    """,
                    (
                        tenant,
                        phone_number_id,
                        display_phone_number,
                        recipient,
                        message_id,
                        content,
                    ),
                )

            conn.commit()

        print(f"📩 Mensaje registrado en DB: {message_id}")

    except Exception as e:
        print(f"❌ Error al guardar mensaje {message_id}: {e}")

def obtener_configuracion_agencia(clave: str) -> str | None:
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT valor
                    FROM configuracion_agencia
                    WHERE clave = %s
                """, (clave,))

                row = cur.fetchone()
                return row[0] if row else None

    except Exception as e:
        print(f"⚠️ Error obteniendo configuración '{clave}': {e}")
        return None



def obtener_participantes_por_tipo_db(tipo: str):
    tipo = (tipo or "").strip().lower()

    try:
        with get_connection_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                if tipo == "aspirante":
                    cur.execute("""
                        SELECT
                            a.id,
                            a.usuario AS username,
                            a.nickname,
                            a.nombre_real,
                            COALESCE(a.nickname, a.nombre_real, a.usuario, a.telefono) AS display_name,
                            a.email,
                            a.telefono,
                            a.whatsapp,
                            a.foto_url,
                            a.foto_url_mini,
                            a.verificado,
                            a.activo,
                            ae.nombre AS estado_nombre,
                            a.creado_en,
                            a.actualizado_en,
                            'aspirante' AS tipo_usuario,
                             NULL AS rol
                        FROM aspirantes a
                        INNER JOIN aspirantes_estados ae
                            ON a.estado_id = ae.id
                        WHERE a.activo = TRUE
                        ORDER BY a.actualizado_en DESC NULLS LAST, a.creado_en DESC
                    """)

                elif tipo == "creador":
                    cur.execute("""
                        SELECT
                            c.id,
                            c.usuario AS username,
                            c.nickname,
                            c.nombre_real,
                            COALESCE(c.nickname, c.nombre_real, c.usuario, c.telefono) AS display_name,
                            c.email,
                            c.telefono,
                            c.whatsapp,
                            c.foto_url,
                            NULL AS foto_url_mini,
                            NULL AS verificado,
                            c.activo,
                            c.estado_operativo AS estado_nombre,
                            c.creado_en,
                            c.actualizado_en,
                            'creador' AS tipo_usuario,
                            NULL AS rol
                        FROM creadores c
                        WHERE c.activo = TRUE
                        ORDER BY c.actualizado_en DESC NULLS LAST, c.creado_en DESC
                    """)

                elif tipo == "administrador":
                    cur.execute("""
                        SELECT
                            u.id,
                            u.username,
                            NULL AS nickname,
                            u.nombre_completo AS nombre_real,
                            COALESCE(u.nombre_completo, u.username, u.email, u.telefono) AS display_name,
                            u.email,
                            u.telefono,
                            NULL AS whatsapp,
                            NULL AS foto_url,
                            NULL AS foto_url_mini,
                            NULL AS verificado,
                            u.activo,
                            u.grupo AS estado_nombre,
                            u.creado_en,
                            u.actualizado_en,
                            'administrador' AS tipo_usuario,
                            ur.nombre AS rol
                        FROM administradores u
                        INNER JOIN administradores_roles ur
                            ON ur.id = u.administradores_roles_id
                        WHERE u.activo = TRUE
                        ORDER BY u.actualizado_en DESC NULLS LAST, u.creado_en DESC
                    """)

                else:
                    raise HTTPException(
                        status_code=400,
                        detail="Tipo inválido. Use: aspirante, creador o administrador."
                    )

                return cur.fetchall()

    except HTTPException:
        raise
    except Exception as e:
        print("❌ Error al obtener participantes por tipo:", e)
        raise HTTPException(
            status_code=500,
            detail="Error interno al obtener participantes."
        )


#
# def actualizar_mensaje_desde_status(conn, tenant: str, value: dict):
#     """
#     value = value["changes"][0]["value"]
#     """
#     metadata = value.get("metadata", {})
#     phone_number_id = metadata.get("phone_number_id")
#     display_phone_number = metadata.get("display_phone_number")
#
#     statuses = value.get("statuses", [])
#
#     for st in statuses:
#         message_id = st.get("id")
#         status = st.get("status")
#         recipient_id = st.get("recipient_id")
#         timestamp = st.get("timestamp")
#
#         error = (st.get("errors") or [None])[0]  # primer error o None
#
#         error_code = error.get("code") if error else None
#         error_title = error.get("title") if error else None
#         error_message = error.get("message") if error else None
#         error_details = (error.get("error_data") or {}).get("details") if error else None
#
#         with conn.cursor() as cur:
#             cur.execute(
#                 """
#                 UPDATE whatsapp_messages
#                 SET
#                     status = %s,
#                     error_code = %s,
#                     error_title = %s,
#                     error_message = %s,
#                     error_details = %s,
#                     raw_payload = %s,
#                     updated_at = NOW(),
#                     last_status_at = TO_TIMESTAMP(%s)
#                 WHERE message_id = %s
#                   AND tenant = %s;
#                 """,
#                 (
#                     status,
#                     error_code,
#                     error_title,
#                     error_message,
#                     error_details,
#                     json.dumps(value),
#                     int(timestamp),
#                     message_id,
#                     tenant,
#                 ),
#             )
#         conn.commit()