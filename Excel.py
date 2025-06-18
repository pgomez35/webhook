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
            if os.getenv("DEBUG_CREDENTIALS") == "true":
                print("✅ Variable cargada correctamente")
                print("📧 client_email:", cred_dict.get("client_email", "NO EMAIL"))
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
            fila += [''] * (18 - len(fila))  # Asegura longitud
            telefono = fila[2].strip().replace(" ", "").replace("+", "")

            if not telefono or not telefono.isdigit():
                print(f"⚠️ Contacto sin teléfono válido: {fila[1].strip()} - omitido")
                continue

            disponibilidad = fila[3].strip().upper()
            contacto_estado = fila[8].strip().upper()

            # if disponibilidad != "APTO" or contacto_estado != "CONTACTO":
            if disponibilidad != "APTO":
                print(f"⚠️ Contacto {fila[1].strip()} no cumple condiciones (APTO y CONTACTO) - omitido")
                continue

            contacto = {
                "usuario": fila[1].strip(),
                "telefono": telefono,
                "disponibilidad": disponibilidad,
                "contacto": contacto_estado,
                "respuesta_creador": fila[9].strip().upper(),
                "perfil": fila[5].strip().upper(),
                "entrevista": fila[11].strip().upper(),
                "nickname": fila[17].strip(),
            }
            print(f"➡️ Contacto válido {i + 1}: {contacto}")
            contactos.append(contacto)

        return contactos

    except Exception as e:
        print(f"❌ Error leyendo hoja de cálculo: {e}")
        return []
