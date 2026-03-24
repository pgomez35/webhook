from DataBase import get_connection_context, registrar_envio_mensaje
from enviar_msg_wp import *
import os
from dotenv import load_dotenv
import json
load_dotenv()

# TOKEN = os.getenv("WHATSAPP_TOKEN_PRESTIGE")
# ID = os.getenv("WHATSAPP_PHONE_ID_PRESTIGE")



# enviar_plantilla_hello_world("EAAJ4EEYGr4MBO4OD8qfqvsQzgv0oFEiXDsW6IpqZA0lvMiuHPXjHkrXLLW4WKqVHt11tQ6wa9HdzZBLDKfKaVhIZB3RrdePPqufwWvCZBmCoRmF9ey3jcprss0206BYrDehit2mFinqjyJZAT4nHNZCOPZBYSlZAlJDk0YZC85vMmsZCnGX5mYbeo2LWLOWHYUkZCEDwAcv2lW7cJbJqwFbkkA4pCHThZCw8IV1VeX1s", "677957268731281", "573006962342")
# enviar_plantilla_saludo(TOKEN, ID, "573153638069")

# enviar_plantilla_generica(
#     token=TOKEN,
#     phone_number_id=ID,
#     numero_destino="573153638069",
#     nombre_plantilla="hello_world",
#     codigo_idioma="en_US"
# )

# enviar_plantilla_generica(
#     token=TOKEN,
#     phone_number_id=ID,
#     numero_destino="573153638069",
#     nombre_plantilla="test_variable",
#     codigo_idioma="en_US",
#     parametros=["Pablo"]
# )

# enviar_plantilla_generica(
#     token=TOKEN,
#     phone_number_id=ID,
#     numero_destino="573153638069",
#     nombre_plantilla="saludo",
#     codigo_idioma="es_CO"
# )

# enviar_plantilla_generica(
#     token=TOKEN,
#     phone_number_id=ID,
#     numero_destino="573153638069",
#     nombre_plantilla="solicitar_informacion",
#     codigo_idioma="es_CO",
#     parametros=["Pablo"]
# )

# resp_status, data = enviar_mensaje_texto_simple(
#     token=TOKEN,
#     numero_id=ID,
#     telefono_destino="+573153638069",
#     texto="Hi, this is another message text🚀"
# )
#
# # Opcional: validar que todo salió bien
# if resp_status != 200:
#     print(f"❌ Error al enviar mensaje. Status: {resp_status}")
# else:
#     print("✅ Mensaje enviado correctamente.")
#
# msg_id = data["messages"][0]["id"]
#
# registrar_envio_mensaje(
#     tenant="pruebas",
#     phone_number_id=ID,
#     display_phone_number="573144667587",
#     recipient="573153638069",
#     message_id=msg_id,
#     content="Hi, this is another message text🚀"
# )


# numero = "573153638069"
# enviar_plantilla_generica(
#     token=TOKEN,
#     phone_number_id=ID,
#     numero_destino=numero,
#     nombre_plantilla="inicio_encuesta",
#     codigo_idioma="es_CO",
#     parametros=["AgenciaX", numero]  # primero -> {{1}}, segundo -> {{2}} (botón url)
# )

if __name__ == "__main__":
    TOKEN = os.getenv("WHATSAPP_TOKEN")
    PHONE_ID = os.getenv("WHATSAPP_PHONE_ID") # p.ej. "573144667587"
    telefono = "+573153638069"
    # opciones = [
    #     {"id": "opt_1", "emoji": "1️⃣", "label": "Actualizar perfil"},
    #     {"id": "opt_2", "emoji": "2️⃣", "label": "Análisis de perfil"},
    #     {"id": "opt_3", "emoji": "3️⃣", "label": "Chat con asesor"},
    # ]
    #
    # status, data = enviar_botones_con_iconos_minimal(
    #     token=TOKEN,
    #     phone_number_id=ID,
    #     telefono_destino=telefono,
    #     opciones=opciones
    # )

    # status, data = enviar_mensaje_texto_simple(
    #     token=TOKEN,
    #     numero_id=ID,
    #     telefono_destino="+573153638069",
    #     texto="Hi, this is another message text🚀"
    # )
    #
    #

import os
import requests
import psycopg2
from fpdf import FPDF

# --- CONFIGURACIÓN ---
# Render leerá esto de las Environment Variables que configures en el Dashboard
DB_URL = os.getenv("EXTERNAL_DATABASE_URL")
TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
DESTINO = "+573153638069"  # Ojo: En producción esto debería ser dinámico

# --- OBTENER RUTA ACTUAL (CRÍTICO PARA RENDER) ---
# Esto encuentra la carpeta donde está este script ejecutándose
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ==========================================
# 1. BASE DE DATOS
# ==========================================
def obtener_diagnostico_db(creador_id):
    print(f"🔌 Consultando BD para ID: {creador_id}...")
    if not DB_URL:
        print("❌ Error: Falta variable EXTERNAL_DATABASE_URL")
        return None

    conn = None
    try:
        conn = psycopg2.connect(DB_URL)
        with conn.cursor() as cur:
            # Query directa
            sql = "SELECT mejoras_sugeridas as diagnostico FROM public.perfil_creador WHERE creador_id = %s"
            cur.execute(sql, (creador_id,))
            row = cur.fetchone()

        if row:
            return row[0]
        else:
            print("⚠️ ID no encontrado en BD.")
            return None
    except Exception as e:
        print(f"❌ Error BD: {e}")
        return None
    finally:
        if conn: conn.close()


# ==========================================
# 2. PDF (COMPATIBLE CON LINUX/RENDER)
# ==========================================
class PDFReport(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 10, "Reporte Automático", align="R", new_x="LMARGIN", new_y="NEXT")


def generar_pdf(texto_db, nombre_archivo="diagnostico.pdf"):
    print("📄 Generando PDF...")
    pdf = PDFReport()
    pdf.add_page()

    # --- DEFINIR RUTAS DE FUENTES ---
    # Usamos os.path.join para que funcione en Linux y Windows
    ruta_sans = os.path.join(BASE_DIR, "borrar_NotoSans-Regular.ttf")
    ruta_emoji = os.path.join(BASE_DIR, "borrar_NotoColorEmoji.ttf")

    # --- CARGAR FUENTES ---
    try:
        # Cargamos las fuentes desde la ruta relativa
        pdf.add_font("MiSans", style="", fname=ruta_sans)
        pdf.add_font("MiEmoji", style="", fname=ruta_emoji)
    except FileNotFoundError as e:
        print(f"❌ ERROR CRÍTICO: No encuentro las fuentes en: {BASE_DIR}")
        print(f"Asegúrate de subir {os.path.basename(e.filename)} al repositorio.")
        return None

    # --- CUERPO ---
    # Título
    pdf.set_font("MiSans", size=16)
    pdf.cell(0, 10, "Diagnóstico del Perfil", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # Texto con Emojis (Fallback)
    pdf.set_font("MiSans", size=12)
    pdf.set_fallback_fonts(["MiEmoji"])

    # Renderizamos el texto de la BD
    pdf.multi_cell(w=0, h=8, text=texto_db)

    # Guardar en ruta temporal (recomendado para servidores)
    ruta_salida = os.path.join("/tmp", nombre_archivo) if os.name != 'nt' else nombre_archivo

    pdf.output(ruta_salida)
    print(f"✅ PDF generado en: {ruta_salida}")
    return ruta_salida


# ==========================================
# 3. WHATSAPP
# ==========================================
def subir_y_enviar(path_archivo):
    if not TOKEN or not PHONE_ID:
        print("⚠️ Faltan credenciales de WhatsApp (TOKEN o PHONE_ID).")
        return

    print("☁️ Subiendo a WhatsApp...")
    url = f"https://graph.facebook.com/v19.0/{PHONE_ID}/media"
    headers = {"Authorization": f"Bearer {TOKEN}"}

    try:
        with open(path_archivo, "rb") as f:
            files = {"file": (os.path.basename(path_archivo), f, "application/pdf")}
            # type es obligatorio
            data = {"messaging_product": "whatsapp"}

            resp = requests.post(url, headers=headers, files=files, data=data)

        if resp.status_code == 200:
            media_id = resp.json().get('id')
            print(f"✅ Subido. ID: {media_id}")

            # Enviar mensaje
            print(f"🚀 Enviando a {DESTINO}...")
            url_msg = f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"
            payload = {
                "messaging_product": "whatsapp",
                "to": DESTINO,
                "type": "document",
                "document": {
                    "id": media_id,
                    "caption": "Tu Diagnóstico Preliminar",
                    "filename": "Diagnostico.pdf"
                }
            }
            r_msg = requests.post(url_msg,
                                  headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
                                  json=payload)
            print(f"Estado envío: {r_msg.status_code}")
        else:
            print(f"❌ Error subida: {resp.text}")

    except Exception as e:
        print(f"❌ Error general: {e}")


# ==========================================
# EJECUCIÓN
# ==========================================
if __name__ == "__main__":
    # 1. Definir ID
    ID_CREADOR = 3236

    # 2. Proceso
    texto = obtener_diagnostico_db(ID_CREADOR)

    if texto:
        path_pdf = generar_pdf(texto)
        if path_pdf:
            subir_y_enviar(path_pdf)




# ENVIO MENU OPCIONES
#
# # Ejemplo de uso
# if __name__ == "__main__":
#     TOKEN = os.getenv("WHATSAPP_TOKEN")
#     PHONE_ID = os.getenv("WHATSAPP_PHONE_ID") # p.ej. "573144667587"
#     telefono = "+573153638069"
#
#     status, data = enviar_mensaje_opciones(TOKEN, PHONE_ID, telefono)
#     print("Status:", status)
#     print("Data:", json.dumps(data, ensure_ascii=False, indent=2))
