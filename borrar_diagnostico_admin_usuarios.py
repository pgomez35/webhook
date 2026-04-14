#!/usr/bin/env python3
"""
Script de diagnóstico para el sistema de usuarios administradores
"""

import os
import sys
from dotenv import load_dotenv

def verificar_variables_entorno():
    """Verifica que las variables de entorno estén configuradas"""
    load_dotenv()
    
    print("🔍 VERIFICANDO VARIABLES DE ENTORNO...")
    
    internal_url = os.getenv("INTERNAL_DATABASE_URL")
    external_url = os.getenv("EXTERNAL_DATABASE_URL")
    
    print(f"INTERNAL_DATABASE_URL: {'✅ Configurada' if internal_url else '❌ No configurada'}")
    print(f"EXTERNAL_DATABASE_URL: {'✅ Configurada' if external_url else '❌ No configurada'}")
    
    if internal_url:
        print(f"🔗 URL: {internal_url[:50]}...")
    
    return internal_url or external_url

def verificar_conexion_bd(db_url):
    """Verifica la conexión a la base de datos"""
    print("\n🔍 VERIFICANDO CONEXIÓN A BASE DE DATOS...")
    
    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        
        # Verificar conexión básica
        cur.execute("SELECT version()")
        version = cur.fetchone()[0]
        print(f"✅ Conexión exitosa a PostgreSQL")
        print(f"📊 Versión: {version}")
        
        # Verificar si la tabla existe
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'administradores'
            )
        """)
        table_exists = cur.fetchone()[0]
        
        if table_exists:
            print("✅ Tabla 'administradores' existe")
            
            # Contar registros
            cur.execute("SELECT COUNT(*) FROM administradores")
            count = cur.fetchone()[0]
            print(f"📊 Registros en tabla: {count}")
            
            if count > 0:
                # Mostrar algunos registros
                cur.execute("SELECT id, username, nombre_completo, activo FROM administradores LIMIT 3")
                for row in cur.fetchall():
                    status = "🟢" if row[3] else "🔴"
                    print(f"   {status} ID: {row[0]}, Username: {row[1]}, Nombre: {row[2]}")
            
        else:
            print("❌ Tabla 'administradores' NO existe")
            print("💡 Ejecuta el script SQL de esquema (administradores) en tu base de datos")
        
        cur.close()
        conn.close()
        return table_exists
        
    except ImportError:
        print("❌ psycopg2 no instalado")
        print("💡 Instala con: pip install psycopg2-binary")
        return False
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        return False

def verificar_dependencias():
    """Verifica que las dependencias estén instaladas"""
    print("\n🔍 VERIFICANDO DEPENDENCIAS...")
    
    dependencias = [
        ("fastapi", "FastAPI"),
        ("uvicorn", "Uvicorn"),
        ("psycopg2", "PostgreSQL adapter"),
        ("pydantic", "Pydantic"),
        ("python-dotenv", "Environment loader"),
        ("bcrypt", "Password hashing")
    ]
    
    for modulo, descripcion in dependencias:
        try:
            __import__(modulo)
            print(f"✅ {descripcion}")
        except ImportError:
            print(f"❌ {descripcion} - pip install {modulo}")

def crear_usuario_prueba(db_url):
    """Crea un usuario de prueba si no existe"""
    print("\n🔍 CREANDO USUARIO DE PRUEBA...")
    
    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        
        # Verificar si ya existe el usuario de prueba
        cur.execute("SELECT id FROM administradores WHERE username = 'test_user'")
        if cur.fetchone():
            print("✅ Usuario de prueba ya existe")
            cur.close()
            conn.close()
            return True
        
        # Crear usuario de prueba
        cur.execute("""
            INSERT INTO administradores (
                username, nombre_completo, email, telefono, grupo, password_hash, administradores_roles_id
            )
            VALUES (
                'test_user', 'Usuario de Prueba', 'test@test.com', '+1111111111', 'PRUEBA', 'test123',
                (SELECT id FROM administradores_roles WHERE nombre = 'USUARIO' LIMIT 1)
            )
        """)
        
        conn.commit()
        cur.close()
        conn.close()
        
        print("✅ Usuario de prueba creado")
        print("   Username: test_user")
        print("   Password: test123")
        return True
        
    except Exception as e:
        print(f"❌ Error creando usuario de prueba: {e}")
        return False

def main():
    print("🚀 DIAGNÓSTICO DEL SISTEMA DE USUARIOS ADMINISTRADORES")
    print("=" * 60)
    
    # 1. Verificar variables de entorno
    db_url = verificar_variables_entorno()
    
    if not db_url:
        print("\n❌ No se encontraron variables de entorno de base de datos")
        print("💡 Crear archivo .env con INTERNAL_DATABASE_URL o EXTERNAL_DATABASE_URL")
        return
    
    # 2. Verificar dependencias
    verificar_dependencias()
    
    # 3. Verificar conexión a BD
    tabla_existe = verificar_conexion_bd(db_url)
    
    if not tabla_existe:
        print("\n💡 PASOS PARA SOLUCIONAR:")
        print("1. Ejecutar esquema_usuarios.sql en tu base de datos")
        print("2. Verificar que la conexión a BD sea correcta")
        return
    
    # 4. Crear usuario de prueba
    crear_usuario_prueba(db_url)
    
    print("\n🎉 DIAGNÓSTICO COMPLETADO")
    print("💡 Si el frontend aún no funciona, verifica que:")
    print("   - El servidor FastAPI esté corriendo en puerto 8000")
    print("   - No hay errores CORS")
    print("   - La URL del frontend apunte a http://localhost:8000")

if __name__ == "__main__":
    main()
