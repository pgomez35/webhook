from fastapi import APIRouter, Body, UploadFile
import os
import json
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd

router = APIRouter()

def get_gspread_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    cred_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    cred_dict = json.loads(cred_json)
    creds = Credentials.from_service_account_info(cred_dict, scopes=scope)
    return gspread.authorize(creds)

@router.get("/listar_hojas")
def listar_hojas(str_key: str):
    """
    Devuelve la lista de hojas disponibles en el documento Google Sheets.
    Ahora recibe el str_key como parámetro (query param) desde el frontend.
    """
    try:
        gc = get_gspread_client()
        spreadsheet = gc.open_by_key(str_key)
        hojas = [ws.title for ws in spreadsheet.worksheets()]
        return {"status": "ok", "hojas": hojas}
    except Exception as e:
        return {"status": "error", "mensaje": f"Error al listar hojas: {str(e)}"}

@router.post("/cargar_aspirantes")
def cargar_aspirantes_desde_workspace(
    nombre_hoja: str = Body(..., embed=True),
    str_key: str = Body(..., embed=True)
):
    """
    Carga aspirantes desde una hoja específica de Google Sheets.
    Ahora recibe el str_key como parámetro desde el frontend.
    """
    try:
        aspirantes = obtener_aspirantes_desde_hoja(str_key, nombre_hoja)
        if not aspirantes:
            return {"status": "error", "mensaje": "No se encontraron aspirantes en la hoja"}
        guardar_aspirantes(aspirantes)
        return {"status": "ok", "mensaje": f"{len(aspirantes)} aspirantes cargados y guardados correctamente"}
    except Exception as e:
        return {"status": "error", "mensaje": f"Error al cargar aspirantes: {str(e)}"}

def obtener_aspirantes_desde_hoja(str_key, nombre_hoja):
    try:
        gc = get_gspread_client()
        spreadsheet = gc.open_by_key(str_key)
        worksheet = spreadsheet.worksheet(nombre_hoja)
        columna_B = worksheet.col_values(2)[3:]
        ultima_fila = 3 + len([c for c in columna_B if c.strip() != ""])
        rango = f"A4:X{ultima_fila}"
        filas = worksheet.get(rango)

        def to_int(val):
            try: return int(val)
            except: return None

        aspirantes = []
        for i, fila in enumerate(filas):
            fila += [''] * (25 - len(fila))
            aspirante = {
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
            aspirantes.append(aspirante)
        return aspirantes
    except Exception as e:
        print(f"❌ Error leyendo hoja de cálculo: {e}")
        return []

@router.post("/cargar_aspirantes_local")
async def cargar_aspirantes_desde_archivo(file: UploadFile):
    """
    Carga aspirantes desde un archivo Excel local (.xlsx).
    El usuario debe subir el archivo desde el frontend.
    """
    try:
        filepath = f"/tmp/{file.filename}"
        with open(filepath, "wb") as f:
            f.write(await file.read())

        df = pd.read_excel(filepath)
        aspirantes = df.to_dict(orient="records")
        guardar_aspirantes(aspirantes)
        return {"status": "ok", "mensaje": f"{len(aspirantes)} aspirantes cargados y guardados correctamente"}
    except Exception as e:
        return {"status": "error", "mensaje": f"Error al cargar archivo: {str(e)}"}


from DataBase import get_connection,limpiar_telefono,safe_int


def guardar_aspirantes(aspirantes, nombre_archivo=None, hoja_excel=None, lote_carga=None, procesado_por=None,
                      observaciones=None):
    conn = get_connection()
    cur = conn.cursor()
    resultados = []
    filas_fallidas = []

    for c in aspirantes:
        try:
            usuario = c.get("usuario", "")
            nickname = c.get("nickname", "")
            email = c.get("email", "")
            telefono = limpiar_telefono(c.get("telefono", ""))
            disponibilidad = c.get("disponibilidad", "")
            perfil = c.get("perfil", "")
            motivo_no_apto = c.get("motivo_no_apto", "")
            contacto = c.get("contacto", "")
            respuesta_creador = c.get("respuesta_creador", "")
            entrevista = c.get("entrevista", "")
            tipo_solicitud = c.get("tipo_solicitud", "")
            razon_no_contacto = c.get("razon_no_contacto", "")
            seguidores = safe_int(c.get("seguidores", ""))
            cantidad_videos = safe_int(c.get("videos", ""))
            likes_totales = safe_int(c.get("likes", ""))
            duracion_emisiones = safe_int(c.get("Duracion_Emisiones", ""))
            dias_emisiones = safe_int(c.get("Dias_Emisiones", ""))
            fila_excel = c.get("fila_excel")
            apto = not bool(str(motivo_no_apto).strip())

            # 1. creadores
            cur.execute("SELECT id FROM creadores WHERE usuario = %s", (usuario,))
            creador_row = cur.fetchone()
            if creador_row:
                creador_id = creador_row[0]
                cur.execute("""
                    UPDATE creadores SET
                        nickname = %s,
                        email = %s,
                        telefono = %s,
                        actualizado_en = NOW()
                    WHERE id = %s
                """, (nickname, email, telefono, creador_id))
            else:
                cur.execute("""
                    INSERT INTO creadores (usuario, nickname, email, telefono, activo, creado_en, actualizado_en)
                    VALUES (%s, %s, %s, %s, TRUE, NOW(), NOW())
                    RETURNING id
                """, (usuario, nickname, email, telefono))
                creador_id = cur.fetchone()[0]

            # 2. perfil_creador

            # Elimina cualquier referencia a perfil en perfil_creador:
            cur.execute("SELECT id FROM perfil_creador WHERE creador_id = %s", (creador_id,))
            perfil_row = cur.fetchone()
            if perfil_row:
                cur.execute("""
                    UPDATE perfil_creador SET
                        seguidores = %s,
                        cantidad_videos = %s,
                        likes_totales = %s,
                        duracion_emisiones = %s,
                        dias_emisiones = %s,
                        actualizado_en = NOW()
                    WHERE creador_id = %s
                """, (
                    seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones, creador_id
                ))
            else:
                cur.execute("""
                    INSERT INTO perfil_creador (
                        creador_id,
                        seguidores, cantidad_videos, likes_totales,
                        duracion_emisiones, dias_emisiones,
                        creado_en, actualizado_en
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, NOW(), NOW()
                    )
                """, (
                    creador_id, seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones
                ))

            # 3. cargue_creadores
            cur.execute("SELECT id FROM cargue_creadores WHERE usuario = %s AND hoja_excel = %s", (usuario, hoja_excel))
            cargue_row = cur.fetchone()
            if cargue_row:
                cargue_id = cargue_row[0]
                cur.execute("""
                    UPDATE cargue_creadores SET
                        nickname = %s,
                        email = %s,
                        telefono = %s,
                        disponibilidad = %s,
                        perfil = %s,
                        motivo_no_apto = %s,
                        contacto = %s,
                        respuesta_creador = %s,
                        entrevista = %s,
                        tipo_solicitud = %s,
                        razon_no_contacto = %s,
                        seguidores = %s,
                        cantidad_videos = %s,
                        likes_totales = %s,
                        duracion_emisiones = %s,
                        dias_emisiones = %s,
                        nombre_archivo = %s,
                        fila_excel = %s,
                        lote_carga = %s,
                        estado = %s,
                        procesado = %s,
                        procesado_por = %s,
                        creador_id = %s,
                        apto = %s,
                        observaciones = %s,
                        actualizado_en = NOW()
                    WHERE id = %s
                """, (
                    nickname, email, telefono, disponibilidad, perfil, motivo_no_apto,
                    contacto, respuesta_creador, entrevista, tipo_solicitud, razon_no_contacto,
                    seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones,
                    nombre_archivo, fila_excel, lote_carga, "Procesando", False, procesado_por,
                    creador_id, apto, observaciones, cargue_id
                ))
            else:
                cur.execute("""
                    INSERT INTO cargue_creadores (
                        usuario, nickname, email, telefono, disponibilidad, perfil, motivo_no_apto,
                        contacto, respuesta_creador, entrevista, tipo_solicitud, razon_no_contacto,
                        seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones,
                        nombre_archivo, hoja_excel, fila_excel, lote_carga,
                        estado, procesado, procesado_por, creador_id,
                        apto, observaciones, activo, creado_en, actualizado_en
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, TRUE, NOW(), NOW()
                    )
                """, (
                    usuario, nickname, email, telefono, disponibilidad, perfil, motivo_no_apto,
                    contacto, respuesta_creador, entrevista, tipo_solicitud, razon_no_contacto,
                    seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones,
                    nombre_archivo, hoja_excel, fila_excel, lote_carga,
                    "Procesando", False, procesado_por, creador_id,
                    apto, observaciones
                ))

            resultados.append({
                "fila": fila_excel,
                "usuario": usuario,
                "creador_id": creador_id
            })

        except Exception as err:
            print(f"Error en fila {c.get('fila_excel')}: {err}")
        conn.rollback()
        filas_fallidas.append({
            "fila": c.get("fila_excel"),
            "error": str(err),
            "aspirante": c
        })

    conn.commit()
    cur.close()
    conn.close()
    print(f"✅ Contactos procesados. Filas exitosas: {len(resultados)}. Filas fallidas: {len(filas_fallidas)}")
    return {
        "exitosos": resultados,
        "fallidos": filas_fallidas
    }

