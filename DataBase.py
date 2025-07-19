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

def limpiar_telefono(telefono):
    telefono = telefono.strip().replace("+", "").replace(" ", "")
    # Si el teléfono comienza con 93, cambia a 57
    if telefono.startswith("93"):
        telefono = "57" + telefono[2:]
    return telefono


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

def guardar_contactos___(contactos, nombre_archivo=None, hoja_excel=None, lote_carga=None, procesado_por=None, observaciones=None):
    conn = psycopg2.connect(INTERNAL_DATABASE_URL)
    cur = conn.cursor()
    resultados = []
    filas_fallidas = []

    for c in contactos:
        try:
            usuario = c.get("usuario")
            telefono = limpiar_telefono(c.get("telefono"))
            disponibilidad = c.get("disponibilidad")
            motivo_no_apto = c.get("motivo_no_apto")
            perfil = c.get("perfil")
            contacto_val = c.get("contacto")
            respuesta_creador = c.get("respuesta_creador")
            entrevista = c.get("entrevista")
            tipo_solicitud = c.get("tipo_solicitud")
            email = c.get("email")
            nickname = c.get("nickname")
            razon_no_contacto = c.get("razon_no_contacto")
            seguidores = int(c.get("seguidores", "0")) if c.get("seguidores", "0").isdigit() else 0
            videos = int(c.get("videos", "0")) if c.get("videos", "0").isdigit() else 0
            likes = int(c.get("likes", "0")) if c.get("likes", "0").isdigit() else 0
            duracion_emisiones = int(c.get("Duracion_Emisiones", "0")) if c.get("Duracion_Emisiones", "0").isdigit() else 0
            dias_emisiones = int(c.get("Dias_Emisiones", "0")) if c.get("Dias_Emisiones", "0").isdigit() else 0
            fila_excel = c.get("fila_excel")
            apto = not bool(motivo_no_apto.strip())

            # 1. Consultar si existe el usuario en creadores
            cur.execute("SELECT id FROM creadores WHERE usuario = %s", (usuario,))
            creador_row = cur.fetchone()
            if creador_row:
                creador_id = creador_row[0]
                creador_status = "existente"
                # Opcional: actualizar datos
                cur.execute("""
                    UPDATE creadores SET
                        nickname = %s,
                        email = %s,
                        telefono = %s,
                        actualizado_en = NOW()
                    WHERE id = %s
                """, (
                    nickname,
                    email,
                    telefono,
                    creador_id
                ))
            else:
                cur.execute("""
                    INSERT INTO creadores (usuario, nickname, email, telefono, activo, creado_en, actualizado_en)
                    VALUES (%s, %s, %s, %s, TRUE, NOW(), NOW())
                    RETURNING id
                """, (
                    usuario,
                    nickname,
                    email,
                    telefono,
                ))
                creador_id = cur.fetchone()[0]
                creador_status = "nuevo"

            # 2. Consultar si existe perfil_creador para ese creador
            cur.execute("SELECT id FROM perfil_creador WHERE creador_id = %s", (creador_id,))
            perfil_row = cur.fetchone()
            if perfil_row:
                perfil_creador_id = perfil_row[0]
                perfil_status = "actualizado"
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
                    perfil,
                    seguidores,
                    videos,
                    likes,
                    duracion_emisiones,
                    dias_emisiones,
                    creador_id
                ))
            else:
                cur.execute("""
                    INSERT INTO perfil_creador (
                        creador_id, perfil,
                        seguidores, cantidad_videos, likes_totales,
                        duracion_emisiones, dias_emisiones,
                        creado_en, actualizado_en
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                    ) RETURNING id
                """, (
                    creador_id,
                    perfil,
                    seguidores,
                    videos,
                    likes,
                    duracion_emisiones,
                    dias_emisiones,
                ))
                perfil_creador_id = cur.fetchone()[0]
                perfil_status = "nuevo"

            # 3. Consultar si existe cargue_creadores para usuario y hoja
            cur.execute(
                "SELECT id FROM cargue_creadores WHERE usuario = %s AND hoja_excel = %s",
                (usuario, hoja_excel)
            )
            cargue_row = cur.fetchone()
            if cargue_row:
                cargue_id = cargue_row[0]
                cargue_status = "existente"
                # Opcional: puedes actualizar cargue_creadores si lo necesitas aquí
            else:
                cur.execute("""
                    INSERT INTO cargue_creadores (
                        usuario, nickname, email, telefono, disponibilidad, perfil, motivo_no_apto,
                        contacto, respuesta_creador, entrevista, tipo_solicitud, razon_no_contacto,
                        seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones,
                        nombre_archivo, hoja_excel, fila_excel, lote_carga, fecha_carga,
                        estado, procesado, fecha_procesamiento, procesado_por, creador_id,
                        apto, puntaje_evaluacion,
                        contactado, fecha_contacto, respondio,
                        observaciones, activo, creado_en, actualizado_en
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, CURRENT_DATE,
                        %s, %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, NOW(), NOW()
                    ) RETURNING id
                """, (
                    usuario,
                    nickname,
                    email,
                    telefono,
                    disponibilidad,
                    perfil,
                    motivo_no_apto,
                    contacto_val,
                    respuesta_creador,
                    entrevista,
                    tipo_solicitud,
                    razon_no_contacto,
                    seguidores,
                    videos,
                    likes,
                    duracion_emisiones,
                    dias_emisiones,
                    nombre_archivo,
                    hoja_excel,
                    fila_excel,
                    lote_carga,
                    "Procesando",
                    False,
                    None,
                    procesado_por,
                    creador_id,
                    apto,
                    None,
                    False,
                    None,
                    False,
                    observaciones,
                    True
                ))
                cargue_id = cur.fetchone()[0]
                cargue_status = "nuevo"

            resultados.append({
                "fila": fila_excel,
                "usuario": usuario,
                "creador_id": creador_id,
                "creador_status": creador_status,
                "perfil_creador_id": perfil_creador_id,
                "perfil_status": perfil_status,
                "cargue_creadores_id": cargue_id,
                "cargue_status": cargue_status
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


def guardar_contactos__(contactos):
    conn = psycopg2.connect(INTERNAL_DATABASE_URL)
    cur = conn.cursor()

    for c in contactos:
        # Insertar en aspirantes
        cur.execute("""
        INSERT INTO aspirantes (usuario, nickname, telefono, email, motivo_no_apto, medio_contacto, mensaje_enviado, razon_no_contacto, tipo_solicitud)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """, (
            c["usuario"], c["nickname"], c["telefono"], c["email"], c["motivo_no_apto"],
            c["contacto"], c["respuesta_creador"], c["razon_no_contacto"], c["tipo_solicitud"]
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

