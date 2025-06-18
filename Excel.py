# Excel.py
import gspread
from google.oauth2.service_account import Credentials
import os
import json
from dotenv import load_dotenv

def obtener_contactos_desde_hoja():
    try:
        STR_KEY = os.getenv("STR_KEY")
        NOMBRE_HOJA = os.getenv("NOMBRE_HOJA")
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

        cred_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
        try:
            cred_dict = json.loads(cred_json)
            print("✅ Variable cargada correctamente")
            print("📧 client_email:", cred_dict.get("client_email", "NO EMAIL"))
            print("🔑 project_id:", cred_dict.get("project_id", "NO PROJECT"))
        except Exception as e:
            print("❌ Error al cargar GOOGLE_CREDENTIALS_JSON:", e)
            return []

        creds = Credentials.from_service_account_info(cred_dict, scopes=scope)
        gc = gspread.authorize(creds)

        spreadsheet = gc.open_by_key(STR_KEY)
        worksheet = spreadsheet.worksheet(NOMBRE_HOJA)

        # Leer columna B desde la fila 4 para determinar cuántas filas hay
        columna_B = worksheet.col_values(2)[3:]  # Columna B
        ultima_fila = 3 + len([c for c in columna_B if c.strip() != ""])

        rango = f"A4:R{ultima_fila}"
        filas = worksheet.get(rango)

        print(f"📋 Filas leídas desde la hoja: {len(filas)}")

        contactos = []
        for i, fila in enumerate(filas):
            fila += [''] * (18 - len(fila))  # R = columna 18
            contacto = {
                "usuario": fila[1].strip(),
                "telefono": fila[2].strip(),
                "disponibilidad": fila[3].strip().upper(),
                "contacto": fila[8].strip().upper(),
                "respuesta_creador": fila[9].strip().upper(),
                "perfil": fila[5].strip().upper(),
                "entrevista": fila[11].strip().upper(),
                "nickname": fila[17].strip(),
            }
            print(f"➡️ Contacto {i+1}: {contacto}")
            contactos.append(contacto)

        return contactos

    except Exception as e:
        print(f"❌ Error leyendo hoja de cálculo: {e}")
        return []
