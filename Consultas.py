import os
import psycopg2
from dotenv import load_dotenv

# Cargar variables de entorno (.env)
load_dotenv()
DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")  # O EXTERNAL, según tu caso

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
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_name = '{nombre_tabla}';
    """
    ejecutar_consulta(query)

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

def contar_mensajes_por_tipo():
    print("\n📊 Cantidad de mensajes por tipo:")
    query = """
    SELECT tipo, COUNT(*) AS cantidad
    FROM mensajes
    GROUP BY tipo;
    """
    ejecutar_consulta(query)

# Ejecutar todo si corres el script directamente
if __name__ == "__main__":
    ver_tablas()
    ver_columnas("mensajes")
    ver_columnas("usuarios")
    ultimos_mensajes()
    ultimos_usuarios()
    contar_mensajes_por_tipo()
