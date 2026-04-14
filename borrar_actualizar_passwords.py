"""
Script para actualizar contraseñas hasheadas en la base de datos
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from DataBase import hash_password, get_connection

def actualizar_contraseñas():
    """Actualiza las contraseñas de texto plano a hash"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Verificar usuarios con contraseñas en texto plano
        cur.execute("SELECT id, username, password_hash FROM administradores WHERE LENGTH(password_hash) < 50")
        usuarios = cur.fetchall()
        
        if not usuarios:
            print("✅ Todas las contraseñas ya están hasheadas")
            return
        
        print(f"🔄 Actualizando {len(usuarios)} contraseñas...")
        
        for user_id, username, password_plain in usuarios:
            # Hashear la contraseña
            password_hashed = hash_password(password_plain)
            
            # Actualizar en la base de datos
            cur.execute(
                "UPDATE administradores SET password_hash = %s WHERE id = %s",
                (password_hashed, user_id)
            )
            print(f"✅ Contraseña actualizada para: {username}")
        
        conn.commit()
        print(f"🎉 {len(usuarios)} contraseñas actualizadas correctamente")
        
    except Exception as e:
        print(f"❌ Error al actualizar contraseñas: {e}")
        if 'conn' in locals():
            conn.rollback()
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    actualizar_contraseñas()
