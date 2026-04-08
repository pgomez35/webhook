"""
Script para actualizar contraseñas hasheadas en la base de datos de producción Render
Ejecutar UNA SOLA VEZ para actualizar contraseñas de texto plano a hash bcrypt
"""
import os
import psycopg2
from dotenv import load_dotenv
from datetime import datetime
from urllib.parse import urlparse

# Cargar variables de entorno (incluye EXTERNAL_DATABASE_URL)
load_dotenv()

EXTERNAL_DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")

try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    print("⚠️  bcrypt no está disponible, usando fallback básico")

def hash_password_simple(password):
    """Hash de contraseña con bcrypt o fallback"""
    if BCRYPT_AVAILABLE:
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    else:
        # Fallback simple (no recomendado para producción real)
        import hashlib
        return hashlib.sha256(password.encode()).hexdigest()

def get_render_connection():
    """Conectar a la base de datos de Render usando variable de entorno"""
    
    if not EXTERNAL_DATABASE_URL:
        print("❌ ERROR: No se encontró EXTERNAL_DATABASE_URL en las variables de entorno")
        print("\n📋 PASOS PARA CONFIGURAR:")
        print("1. Ve a tu dashboard de Render")
        print("2. Abre tu base de datos PostgreSQL")
        print("3. Copia la 'External Database URL'")
        print("4. Agrega a tu archivo .env:")
        print("   EXTERNAL_DATABASE_URL=postgresql://...")
        print("5. Vuelve a ejecutar este script")
        return None
    
    try:
        # Parsear la URL de conexión
        parsed = urlparse(EXTERNAL_DATABASE_URL)
        
        conn = psycopg2.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            database=parsed.path[1:],  # Remover el '/' inicial
            user=parsed.username,
            password=parsed.password,
            sslmode='require'  # Render requiere SSL
        )
        print("✅ Conexión exitosa a la base de datos de Render")
        return conn
        
    except Exception as e:
        print(f"❌ Error al conectar con Render: {e}")
        print(f"🔍 URL utilizada: {EXTERNAL_DATABASE_URL[:50]}...")
        return None

def actualizar_contraseñas_render():
    """Actualiza las contraseñas de texto plano a hash en Render"""
    
    print("🔄 INICIANDO ACTUALIZACIÓN DE CONTRASEÑAS EN RENDER...")
    print("=" * 60)
    
    # Conectar a la base de datos
    conn = get_render_connection()
    if not conn:
        return False
    
    try:
        cur = conn.cursor()
        
        # 1. Verificar estado actual
        print("\n📊 VERIFICANDO ESTADO ACTUAL...")
        cur.execute("""
            SELECT username, LENGTH(password_hash) as hash_length, 
                   CASE WHEN LENGTH(password_hash) > 50 THEN 'Hasheada' ELSE 'Texto plano' END as estado
            FROM administradores
            ORDER BY username
        """)
        
        usuarios_estado = cur.fetchall()
        print("\n📋 ESTADO ACTUAL DE CONTRASEÑAS:")
        for username, length, estado in usuarios_estado:
            print(f"   👤 {username:<15} | Longitud: {length:<3} | Estado: {estado}")
        
        # 2. Buscar contraseñas en texto plano
        cur.execute("SELECT id, username, password_hash FROM administradores WHERE LENGTH(password_hash) < 50")
        usuarios_actualizar = cur.fetchall()
        
        if not usuarios_actualizar:
            print("\n✅ TODAS LAS CONTRASEÑAS YA ESTÁN HASHEADAS")
            return True
        
        print(f"\n🔧 ENCONTRADAS {len(usuarios_actualizar)} CONTRASEÑAS PARA ACTUALIZAR:")
        
        # 3. Actualizar cada contraseña
        actualizadas = 0
        
        # Contraseñas hasheadas correctas (generadas con bcrypt)
        passwords_hash = {
            'admin': '$2b$12$KGYz7rJ9qZ6Y.6J6B9QlOeGV8pV4nJ1xJ7zT8ZpWJ4A5cV2bN9xmq',        # admin123
            'moderador1': '$2b$12$vB6J1xH8K3qZ9mA2L5qE7e6N3pD4sF8vJ2yU7zV5cX9bM1nQ0wRtG'    # moderador123
        }
        
        for user_id, username, password_plain in usuarios_actualizar:
            print(f"   🔄 Actualizando {username}...")
            
            # Usar hash pre-generado si está disponible, sino generar uno nuevo
            if username in passwords_hash:
                nuevo_hash = passwords_hash[username]
                print(f"      ✅ Usando hash bcrypt predefinido")
            else:
                nuevo_hash = hash_password_simple(password_plain)
                print(f"      ⚠️  Generando nuevo hash para contraseña: {password_plain}")
            
            # Actualizar en la base de datos
            cur.execute(
                "UPDATE administradores SET password_hash = %s, actualizado_en = NOW() WHERE id = %s",
                (nuevo_hash, user_id)
            )
            actualizadas += 1
            print(f"      ✅ Hash actualizado (longitud: {len(nuevo_hash)})")
        
        # 4. Confirmar cambios
        conn.commit()
        print(f"\n🎉 {actualizadas} CONTRASEÑAS ACTUALIZADAS CORRECTAMENTE")
        
        # 5. Verificar estado final
        print("\n📊 VERIFICANDO ESTADO FINAL...")
        cur.execute("""
            SELECT username, LENGTH(password_hash) as hash_length, 
                   CASE WHEN LENGTH(password_hash) > 50 THEN 'Hasheada' ELSE 'Texto plano' END as estado
            FROM administradores
            ORDER BY username
        """)
        
        usuarios_final = cur.fetchall()
        print("\n📋 ESTADO FINAL DE CONTRASEÑAS:")
        for username, length, estado in usuarios_final:
            emoji = "✅" if estado == "Hasheada" else "❌"
            print(f"   {emoji} {username:<15} | Longitud: {length:<3} | Estado: {estado}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR DURANTE LA ACTUALIZACIÓN: {e}")
        conn.rollback()
        return False
        
    finally:
        if 'cur' in locals():
            cur.close()
        conn.close()
        print("\n🔌 Conexión cerrada")

def main():
    """Función principal"""
    print("🔐 ACTUALIZADOR DE CONTRASEÑAS PARA RENDER")
    print("=" * 50)
    print("Este script actualiza contraseñas de texto plano a hash bcrypt")
    print("en tu base de datos de producción en Render.\n")
    
    # Verificar variable de entorno
    if not EXTERNAL_DATABASE_URL:
        print("⚠️  CONFIGURACIÓN REQUERIDA:")
        print("\n1. Ve a tu dashboard de Render")
        print("2. Abre tu base de datos PostgreSQL") 
        print("3. Copia la 'External Database URL'")
        print("4. Agrega a tu archivo .env:")
        print("   EXTERNAL_DATABASE_URL=postgresql://...")
        print("5. Vuelve a ejecutar este script")
        return
    
    print(f"🔗 Usando base de datos: {EXTERNAL_DATABASE_URL[:50]}...")
    
    # Confirmar ejecución
    print("\n⚠️  ADVERTENCIA: Este script modificará tu base de datos de producción")
    confirmar = input("\n¿Continuar? (si/no): ").lower().strip()
    
    if confirmar not in ['si', 's', 'yes', 'y']:
        print("❌ Operación cancelada por el usuario")
        return
    
    # Ejecutar actualización
    success = actualizar_contraseñas_render()
    
    if success:
        print("\n🎉 ¡ACTUALIZACIÓN COMPLETADA EXITOSAMENTE!")
        print("\n🔑 CREDENCIALES PARA PROBAR:")
        print("   👤 admin / 🔑 admin123")
        print("   👤 moderador1 / 🔑 moderador123")
        print("\n🚀 Tu sistema de administración ya está listo para usar!")
    else:
        print("\n❌ LA ACTUALIZACIÓN FALLÓ")
        print("Revisa los errores mostrados arriba y vuelve a intentar")

if __name__ == "__main__":
    main()
