# Excel.py
import gspread
from google.oauth2.service_account import Credentials
import os
import json
from dotenv import load_dotenv

def obtener_contactos_desde_hoja(NOMBRE_HOJA):
    try:
        import os, json, gspread
        from google.oauth2.service_account import Credentials

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

        columna_B = worksheet.col_values(2)[3:]  # Columna B
        ultima_fila = 3 + len([c for c in columna_B if c.strip() != ""])

        rango = f"A4:R{ultima_fila}"
        filas = worksheet.get(rango)

        print(f"📋 Filas leídas desde la hoja: {len(filas)}")

        def to_int(val):
            try:
                return int(val)
            except:
                return None

        contactos = []
        for i, fila in enumerate(filas):
            fila += [''] * (25 - len(fila))  # Asegura mínimo 25 columnas

            contacto = {
                "usuario": fila[1].strip(),
                "telefono": fila[2].strip().replace(" ", "").replace("+", ""),
                "disponibilidad": fila[3].strip(),
                "motivo_no_apto": fila[4].strip().upper(),
                "perfil": fila[5].strip(),
                "contacto": fila[8].strip(),
                "respuesta_creador": fila[9].strip(),
                "entrevista": fila[11].strip(),
                "tipo_solicitud": fila[15].strip(),
                "email": fila[16].strip(),
                "nickname": fila[17].strip(),
                "razon_no_contacto": fila[18].strip().upper(),
                "seguidores": to_int(fila[19].strip()),
                "videos": to_int(fila[20].strip()),
                "likes": to_int(fila[21].strip()),
                "Duracion_Emisiones": to_int(fila[22].strip()),
                "Dias_Emisiones": to_int(fila[23].strip()),
                "fila_excel": i + 4
            }
            print(f"➡️ Contacto válido {i + 1}: {contacto}")
            contactos.append(contacto)

        return contactos

    except Exception as e:
        print(f"❌ Error leyendo hoja de cálculo: {e}")
        return []


def obtener_contactos_desde_hoja_(NOMBRE_HOJA):
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
            fila += [''] * (25 - len(fila))  # Asegura mínimo 25 columnas

            contacto = {
                "usuario": fila[1].strip(),
                "telefono": fila[2].strip().replace(" ", "").replace("+", ""),
                "disponibilidad": fila[3].strip(),
                "motivo_no_apto": fila[4].strip().upper(),
                "perfil": fila[5].strip(),
                "contacto": fila[8].strip(),
                "respuesta_creador": fila[9].strip(),
                "entrevista": fila[11].strip(),
                "tipo_solicitud": fila[15].strip(),
                "email": fila[16].strip(),
                "nickname": fila[17].strip(),
                "razon_no_contacto": fila[18].strip().upper(),
                "seguidores": fila[19].strip(),
                "videos": fila[20].strip(),
                "likes": fila[21].strip(),
                "Duracion_Emisiones": fila[22].strip(),
                "Dias_Emisiones": fila[23].strip(),
                "fila_excel": i + 4  # <---- Añade el número de fila de Excel (comenzando en 4)
            }
            print(f"➡️ Contacto válido {i + 1}: {contacto}")
            contactos.append(contacto)

        return contactos

    except Exception as e:
        print(f"❌ Error leyendo hoja de cálculo: {e}")
        return []

