# Excel.py
import gspread
from google.oauth2.service_account import Credentials
import os
from dotenv import load_dotenv

def obtener_contactos_desde_hoja():
    try:
        STR_KEY = os.getenv("STR_KEY")
        NOMBRE_HOJA = os.getenv("NOMBRE_HOJA")

        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file('credentials.json', scopes=scope)
        gc = gspread.authorize(creds)

        spreadsheet = gc.open_by_key(STR_KEY)
        worksheet = spreadsheet.worksheet(NOMBRE_HOJA)

        columna_B = worksheet.col_values(2)[3:]  # Usuarios
        ultima_fila = 3 + len([c for c in columna_B if c.strip() != ""])

        rango = f"A4:R{ultima_fila}"
        filas = worksheet.get(rango)

        contactos = []
        for fila in filas:
            fila += [''] * (18 - len(fila))  # R = columna 18
            contactos.append({
                "usuario": fila[1].strip(),
                "telefono": fila[2].strip(),
                "disponibilidad": fila[3].strip().upper(),
                "contacto": fila[8].strip().upper(),
                "respuesta_creador": fila[9].strip().upper(),
                "perfil": fila[5].strip().upper(),
                "entrevista": fila[11].strip().upper(),
                "nickname": fila[17].strip(),
            })

        return contactos

    except Exception as e:
        print(f"❌ Error leyendo hoja de cálculo: {e}")
        return []