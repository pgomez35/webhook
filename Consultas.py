import os
import psycopg2
from dotenv import load_dotenv

# Cargar variables de entorno (.env)
load_dotenv()
DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")  # O EXTERNAL, según tu caso

# def ejecutar_consulta(query, params=None):
#     try:
#         conn = psycopg2.connect(DATABASE_URL)
#         cur = conn.cursor()
#         cur.execute(query)
#         resultados = cur.fetchall()
#         for fila in resultados:
#             print(fila)
#         cur.close()
#         conn.close()
#     except Exception as e:
#         print("❌ Error al ejecutar consulta:", e)

def ejecutar_consulta(query):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(query)
        resultados = cur.fetchall()
        for fila in resultados:
            print(fila)
        cur.close()
        conn.close()
    except Exception as e:
        print("❌ Error al ejecutar consulta:", e)

def ver_tablas():
    print("\n📋 Tablas en la base de datos:")
    query = """
    SELECT table_name FROM information_schema.tables
    WHERE table_schema = 'public';
    """
    ejecutar_consulta(query)

def ver_columnas(nombre_tabla):
    print(f"\n🔎 Columnas de la tabla '{nombre_tabla}':")
    query = f"""
    SELECT 
        column_name, 
        data_type,
        character_maximum_length,
        is_nullable,
        column_default
    FROM information_schema.columns
    WHERE table_name = '{nombre_tabla}';
    """
    return ejecutar_consulta(query)


def ultimos_mensajes(limit=10):
    print(f"\n📩 Últimos {limit} mensajes:")
    query = f"""
    SELECT * FROM mensajes
    ORDER BY fecha DESC
    LIMIT {limit};
    """
    ejecutar_consulta(query)

def ultimos_usuarios(limit=10):
    print(f"\n👥 Últimos {limit} usuarios:")
    query = f"""
    SELECT * FROM usuarios
    ORDER BY creado_en DESC
    LIMIT {limit};
    """
    ejecutar_consulta(query)

def ultimos_contactos(limit=10):
    print(f"\n👥 Últimos {limit} contactos:")
    query = f"""
    SELECT * FROM contacto_info
    ORDER BY creado_en DESC
    LIMIT {limit};
    """
    ejecutar_consulta(query)

def verificar_contacto_info(limit=20):
    print(f"\n👥 verificar Últimos {limit} contactos:")
    query = f"""
    SELECT id, telefono, usuario, perfil, entrevista, estado_whatsapp
    FROM contacto_info
    ORDER BY creado_en DESC
    LIMIT {limit};
    """
    ejecutar_consulta(query)


def contar_mensajes_por_tipo():
    print("\n📊 Cantidad de mensajes por tipo:")
    query = """
    SELECT tipo, COUNT(*) AS cantidad
    FROM mensajes
    GROUP BY tipo;
    """
    ejecutar_consulta(query)

def ver_creadores():
    print("\n📊 creadores:")
    query = """
    SELECT *
    FROM creadores
    ;
    """

def ver_cargue_creadores():
    print("\n📊 cargue_creadores:")
    query = """
    SELECT *
    FROM cargue_creadores
    ;
    """

def ver_perfil_creador(usuario='%'):
    print("\n📊 Puntajes perfil_creador:")
    query = """
    SELECT
        creador_id,
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
    WHERE usuario LIKE %s
    LIMIT 10;
    """
    if '%' not in usuario:
        usuario = f'%{usuario}%'
    ejecutar_consulta(query, (usuario,))

def mostrar_puntajes_por_usuario(usuario_pattern):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    query = """
    SELECT
        creador_id,
        puntaje_total,
        puntaje_estadistica,
        puntaje_manual,
        puntaje_general,
        puntaje_habitos,
        puntaje_total_categoria,
        puntaje_estadistica_categoria,
        puntaje_habitos_categoria,
        puntaje_general_categoria,
        puntaje_manual_categoria,observaciones
    FROM perfil_creador
    WHERE usuario LIKE %s
    LIMIT 10;
    """

    cur.execute(query, (usuario_pattern,))

    columns = [desc[0] for desc in cur.description]
    filas = cur.fetchall()

    print("\n--- Puntajes perfil_creador ---")
    print(" | ".join(columns))
    for fila in filas:
        print(" | ".join(str(x) if x is not None else "" for x in fila))

    cur.close()
    conn.close()


def ver_perfil_creador1():
    print("\n📊 perfil_creador:")
    query = """
    SELECT creador_id,cantidad_videos,likes_totales,duracion_emisiones,dias_emisiones
    FROM perfil_creador
    LIMIT 10
    ;
    """
    ejecutar_consulta(query)

def token():
    print("\n📊 google Token:")
    query = """
    SELECT *
    FROM google_tokens;
    """
    ejecutar_consulta(query)


def mostrar_tabla(tabla, limit=300):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {tabla} ORDER BY 1 ASC LIMIT {limit};")
    columns = [desc[0] for desc in cur.description]
    filas = cur.fetchall()
    print(f"\n--- {tabla} ---")
    print(" | ".join(columns))
    for fila in filas:
        print(" | ".join(str(x) if x is not None else "" for x in fila))
    cur.close()
    conn.close()
def mostrar_usuario_id(tabla, usuario_id):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Consulta segura con parámetros
    cur.execute(f"SELECT * FROM {tabla} WHERE creador_id = %s;", (usuario_id,))

    columns = [desc[0] for desc in cur.description]
    filas = cur.fetchall()

    print(f"\n--- {tabla} ---")
    print(" | ".join(columns))
    for fila in filas:
        print(" | ".join(str(x) if x is not None else "" for x in fila))

    cur.close()
    conn.close()

def mostrar_usuario(tabla, usuario):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Consulta segura con parámetros
    cur.execute(f"SELECT * FROM {tabla} WHERE usuario = %s;", (usuario,))

    columns = [desc[0] for desc in cur.description]
    filas = cur.fetchall()

    print(f"\n--- {tabla} ---")
    print(" | ".join(columns))
    for fila in filas:
        print(" | ".join(str(x) if x is not None else "" for x in fila))

    cur.close()
    conn.close()


def borrar_tabla(tabla):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(f"DELETE FROM {tabla};")
    conn.commit()
    print(f"✅ Tabla '{tabla}' borrada.")
    cur.close()
    conn.close()

import csv
def exportar_tabla_csv(tabla, archivo_csv):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {tabla};")
    columns = [desc[0] for desc in cur.description]
    filas = cur.fetchall()
    with open(archivo_csv, "w", newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for fila in filas:
            writer.writerow(fila)
    print(f"✅ Exportado {len(filas)} filas de '{tabla}' a {archivo_csv}")
    cur.close()
    conn.close()


import psycopg2

INTERNAL_DATABASE_URL = "postgresql://usuario:password@host:puerto/db"  # Reemplaza por tu cadena real

TABLAS = [
    "estados_creador",
    "tipos_evento",
    "roles_sistema",
    "manager",
    "admin_usuario",
    "control_cargas_excel",
    "conversaciones",
    "mensajes",
    "bots_configuracion",
    "automatizaciones",
    "calendario_eventos",
    "evaluaciones",
    "creadores_activos",
    "seguimiento_creador",
    "lives_tiktok",
    "notificaciones",
    "metricas_sistema",
    "configuraciones_sistema",
    "auditoria_cambios",
    "logs_sistema",
    "creadores",
    "cargue_creadores",
    "perfil_creador"
]

def drop_todas_tablas():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    # Para evitar problemas de claves foráneas, borra en orden inverso
    for tabla in reversed(TABLAS):
        print(f"Eliminando tabla: {tabla}")
        cur.execute(f"DROP TABLE IF EXISTS {tabla} CASCADE;")
    conn.commit()
    cur.close()
    conn.close()
    print("✅ Todas las tablas han sido eliminadas.")

# if __name__ == "__main__":
#     drop_todas_tablas()


if __name__ == "__main__":
    # borrar_tabla("admin_usuario")
    # borrar_tabla("perfil_creador")
    # borrar_tabla("creadores")
    # ver_tablas()
    #  mostrar_tabla("perfil_creador_flujo_temp")
    # mostrar_tabla("perfil_creador")
    #  mostrar_usuario("perfil_creador","lyldetalles1")
    # mostrar_puntajes_por_usuario("davidaulla817")
     #mostrar_usuario_id("perfil_creador", "261")
     #mostrar_tabla("perfil_creador")
    # mostrar_tabla("cargue_creadores")
    #  ver_tablas()
    # exportar_tabla_csv("creadores", "creadores.csv")
    # exportar_tabla_csv("perfil_creador", "perfil_creador.csv")
    # exportar_tabla_csv("cargue_creadores", "cargue_creadores.csv")


# # Ejecutar todo si corres el script directamente
# if __name__ == "__main__":
    # ver_tablas()
#     ver_columnas("cargue_creadores")
#     ver_columnas("creadores")
    ver_columnas("perfil_creador")
#     # ultimos_mensajes()
#     # ultimos_usuarios()
#     # ultimos_contactos()
#     # verificar_contacto_info()
#     # contar_mensajes_por_tipo()
#     token()
#     ver_creadores()
#     # ver_perfil_creador()
#     # ver_cargue_creadores()

