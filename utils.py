from datetime import datetime
import psycopg2
from dotenv import load_dotenv  # Solo si usas variables de entorno
import os
import re
from enviar_msg_wp import enviar_plantilla_generica, enviar_mensaje_texto_simple

# Cargar variables de entorno (incluye DATABASE_URL)
load_dotenv()

INTERNAL_DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")

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

# === Funciones MOCK ===

def enviar_recursos_exclusivos(numero: str):
    print(f"[MOCK] Enviando recursos exclusivos al número {numero}")
    return {"status": "ok", "accion": "recursos_exclusivos", "numero": numero}

def enviar_eventos(numero: str):
    print(f"[MOCK] Enviando información de eventos al número {numero}")
    return {"status": "ok", "accion": "eventos", "numero": numero}

def enviar_estadisticas(numero: str):
    print(f"[MOCK] Enviando estadísticas personalizadas al número {numero}")
    return {"status": "ok", "accion": "estadisticas", "numero": numero}

def solicitar_baja(numero: str):
    print(f"[MOCK] Procesando solicitud de baja para el número {numero}")
    return {"status": "ok", "accion": "solicitud_baja", "numero": numero}

def enviar_panel_control(numero: str):
    print(f"[MOCK] Enviando acceso al panel de control al número {numero}")
    return {"status": "ok", "accion": "panel_control", "numero": numero}

def enviar_perfiles(numero: str):
    print(f"[MOCK] Enviando lista de perfiles disponibles al número {numero}")
    return {"status": "ok", "accion": "perfiles", "numero": numero}

def gestionar_recursos(numero: str):
    print(f"[MOCK] Gestionando recursos para el número {numero}")
    return {"status": "ok", "accion": "gestionar_recursos", "numero": numero}

def enviar_info_general(numero: str):
    print(f"[MOCK] Enviando información general al número {numero}")
    return {"status": "ok", "accion": "info_general", "numero": numero}




