from fastapi import APIRouter, Body, UploadFile, File
import os
import json
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd

import logging
from pathlib import Path
import uuid

router = APIRouter()


import re
from pathlib import Path

# --- Parser del archivo de texto (respeta los valores tal cual) ---
def _keep(s: str) -> str:
    return (s or "").strip()

# def parsear_bloques_desde_txt(ruta_txt: str | Path) -> dict:
#
#     texto = Path(ruta_txt).read_text(encoding="utf-8", errors="ignore")
#     lineas = [ln.rstrip("\n\r") for ln in texto.splitlines()]
#     i, n = 0, len(lineas)
#     out = {}
#
#     while i < n:
#         linea = lineas[i].strip()
#         i += 1
#         if not linea:
#             continue
#
#         usuario = linea
#
#         # "Nombre"
#         while i < n and lineas[i].strip() == "":
#             i += 1
#         if i < n and lineas[i].strip().lower() == "nombre":
#             i += 1
#
#         while i < n and lineas[i].strip() == "":
#             i += 1
#         nombre = _keep(lineas[i]) if i < n else ""
#         i += 1
#
#         # métricas por tabs
#         while i < n and lineas[i].strip() == "":
#             i += 1
#         metrica_line = lineas[i].strip() if i < n else ""
#         i += 1
#
#         m = re.match(r"([^\t]+)\t([^\t]+)\t([^\t]+)\t([^\t]+)\t([^\t]+)", metrica_line)
#         if m:
#             s_seg, s_vid, s_like, s_dur, s_dias = m.groups()
#         else:
#             partes = metrica_line.split("\t") if metrica_line else []
#             while len(partes) < 5:
#                 partes += [""]
#             s_seg, s_vid, s_like, s_dur, s_dias = partes[:5]
#
#         seguidores = _keep(s_seg)      # <- texto tal cual
#         videos = _keep(s_vid)          # <- texto tal cual
#         likes = _keep(s_like)          # <- texto tal cual (ej: "47 237")
#         duracion = _keep(s_dur)
#         dias_validos = _keep(s_dias)
#
#         # caducidad
#         while i < n and lineas[i].strip() == "":
#             i += 1
#         caducidad = _keep(lineas[i]) if i < n else ""
#         i += 1
#
#         # email agente
#         while i < n and lineas[i].strip() == "":
#             i += 1
#         agente = _keep(lineas[i]) if i < n else ""
#         i += 1
#
#         # etiqueta + fecha
#         while i < n and lineas[i].strip() == "":
#             i += 1
#         fecha_sol = ""
#         if i < n:
#             ult = lineas[i].strip()
#             i += 1
#             partes = ult.split("\t")
#             if len(partes) >= 2:
#                 fecha_sol = _keep(partes[1])
#             else:
#                 mm = re.search(r"\b\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}\b", ult)
#                 if mm:
#                     fecha_sol = mm.group(0)
#
#         out[usuario] = {
#             "usuario": usuario,
#             "nombre": nombre,
#             "seguidores": seguidores,
#             "videos": videos,
#             "likes": likes,
#             # Nota: tu código usa estas claves con guion bajo y mayúscula:
#             "Duracion_Emisiones": duracion,
#             "Dias_Emisiones": dias_validos,
#             "caducidad_solicitud": caducidad,
#             "agente_recluta": agente,
#             "fecha_solicitud": fecha_sol,  # se respeta la grafía pedida
#         }
#
#         while i < n and lineas[i].strip() == "":
#             i += 1
#
#     return out


import re
from pathlib import Path

def _keep(s: str) -> str:
    """Conserva el texto tal cual, recortando solo espacios al inicio/fin."""
    return (s or "").strip()

def parsear_bloques_desde_txt(ruta_txt: str | Path) -> dict:
    texto = Path(ruta_txt).read_text(encoding="utf-8", errors="ignore")
    lineas = [ln.rstrip("\n\r") for ln in texto.splitlines()]
    i, n = 0, len(lineas)
    out = {}

    while i < n:
        # Posible inicio de bloque: línea con el usuario
        linea = lineas[i].strip()
        i += 1
        if not linea:
            continue

        usuario = linea  # <-- aquí empieza el bloque del usuario

        # "Nombre" o "Name"
        while i < n and lineas[i].strip() == "":
            i += 1
        if i < n and lineas[i].strip().lower() in ("nombre", "name"):
            i += 1

        # Nombre real
        while i < n and lineas[i].strip() == "":
            i += 1
        nombre = _keep(lineas[i]) if i < n else ""
        i += 1

        # Métricas por tabs: seguidores, videos, likes, duración, días
        while i < n and lineas[i].strip() == "":
            i += 1
        metrica_line = lineas[i].strip() if i < n else ""
        i += 1

        m = re.match(r"([^\t]+)\t([^\t]+)\t([^\t]+)\t([^\t]+)\t([^\t]+)", metrica_line)
        if m:
            s_seg, s_vid, s_like, s_dur, s_dias = m.groups()
        else:
            partes = metrica_line.split("\t") if metrica_line else []
            while len(partes) < 5:
                partes += [""]
            s_seg, s_vid, s_like, s_dur, s_dias = partes[:5]

        seguidores = _keep(s_seg)    # texto tal cual
        videos     = _keep(s_vid)    # texto tal cual
        likes      = _keep(s_like)   # texto tal cual (ej. "47 237")
        duracion   = _keep(s_dur)
        dias_validos = _keep(s_dias)

        # Caducidad
        while i < n and lineas[i].strip() == "":
            i += 1
        caducidad = _keep(lineas[i]) if i < n else ""
        i += 1

        # Email agente recluta
        while i < n and lineas[i].strip() == "":
            i += 1
        agente = _keep(lineas[i]) if i < n else ""
        i += 1

        # Etiqueta de canal (LIVE / Código QR / QR code) + fecha
        while i < n and lineas[i].strip() == "":
            i += 1
        fecha_sol = ""
        canal = ""
        if i < n:
            ult = lineas[i].strip()
            i += 1

            # Caso típico: "<CANAL>\t<FECHA>"
            partes = ult.split("\t")
            if len(partes) >= 2:
                canal = _keep(partes[0])  # conserva exactamente lo que venga (LIVE, Código QR, QR code)
                fecha_sol = _keep(partes[1])
            else:
                # Intento flexible: extraer fecha dd/mm/yyyy hh:mm:ss en cualquier parte de la línea
                mm = re.search(r"\b\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}\b", ult)
                if mm:
                    fecha_sol = mm.group(0)
                # Extraer canal si la línea inicia con LIVE / Código QR / QR code (u otra etiqueta)
                # Guardamos el token inicial, que suele ser el canal.
                canal_match = re.match(r"^\s*([A-Za-zÁÉÍÓÚáéíóúÑñÜü\s]+)", ult)
                if canal_match:
                    canal = _keep(canal_match.group(1))

        out[usuario] = {
            "usuario": usuario,
            "nombre": nombre,
            "seguidores": seguidores,
            "videos": videos,
            "likes": likes,
            "Duracion_Emisiones": duracion,     # se mantiene la misma clave que usas en tu código
            "Dias_Emisiones": dias_validos,     # idem
            "caducidad_solicitud": caducidad,
            "agente_recluta": agente,
            "fecha_solicitud": fecha_sol,        # se respeta la grafía pedida
            "canal": canal,                     # NUEVO: LIVE / Código QR / QR code (texto tal cual)
        }

        # Saltar blancos entre bloques
        while i < n and lineas[i].strip() == "":
            i += 1

    return out


def get_gspread_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    cred_json = os.getenv("GOOGLE_CREDENTIALS_JSON_VIEJA")
    cred_dict = json.loads(cred_json)
    creds = Credentials.from_service_account_info(cred_dict, scopes=scope)
    return gspread.authorize(creds)


logger = logging.getLogger("uvicorn.error")

@router.post("/upload_txt")  # ruta será /api/upload_txt
async def upload_txt(file: UploadFile = File(...)):
    filename = file.filename or "datos.txt"
    if not filename.lower().endswith(".txt"):
        return {"status": "error", "mensaje": "El archivo debe ser .txt"}

    base_dir = Path("uploads/txt")
    base_dir.mkdir(parents=True, exist_ok=True)

    unique_name = f"{uuid.uuid4().hex}_{filename}"
    destino = base_dir / unique_name

    contenido = await file.read()
    destino.write_bytes(contenido)

    return {"status": "ok", "ruta_txt": str(destino)}


@router.get("/listar_hojas")
def listar_hojas(str_key: str):
    """
    Devuelve la lista de hojas disponibles en el documento Google Sheets.
    """
    try:
        gc = get_gspread_client()
        spreadsheet = gc.open_by_key(str_key)
        hojas = [ws.title for ws in spreadsheet.worksheets()]
        return {"status": "ok", "hojas": hojas}
    except Exception as e:
        logger.error(f"❌ Error en listar_hojas con str_key={str_key}: {e}", exc_info=True)
        return {"status": "error", "mensaje": f"Error al listar hojas: {str(e)}"}

@router.post("/cargar_aspirantes")
def cargar_aspirantes_desde_workspace(
    nombre_hoja: str = Body(..., embed=True),
    str_key: str = Body(..., embed=True),
    ruta_txt: str = Body(..., embed=True)
):
    try:
        logger.info(f"📥 Iniciando carga de aspirantes: hoja={nombre_hoja}, str_key={str_key}")
        aspirantes = obtener_aspirantes_desde_hoja(str_key, nombre_hoja, ruta_txt)
        if not aspirantes:
            logger.warning(f"⚠️ No se encontraron aspirantes en la hoja {nombre_hoja}")
            return {
                "status": "error",
                "mensaje": "No se encontraron aspirantes en la hoja"
            }
        guardar_aspirantes(aspirantes)
        logger.info(f"✅ {len(aspirantes)} aspirantes cargados y guardados correctamente")
        return {
            "status": "ok",
            "mensaje": f"{len(aspirantes)} aspirantes cargados y guardados correctamente"
        }
    except Exception as e:
        logger.error(
            f"❌ Error en cargar_aspirantes con hoja={nombre_hoja}, str_key={str_key}: {e}",
            exc_info=True
        )
        return {
            "status": "error",
            "mensaje": f"Error al cargar aspirantes: {str(e)}"
        }


# def obtener_aspirantes_desde_hoja(str_key, nombre_hoja, ruta_txt):
#     """
#     Lee la hoja de Google Sheets (gspread) y mezcla los datos base con
#     los obtenidos desde el archivo de texto vertical para cada 'usuario'.
#     """
#     try:
#         logger.info(f"📥 Iniciando lectura de aspirantes: hoja={nombre_hoja}, str_key={str_key}, txt={ruta_txt}")
#
#         # 1) Parsear archivo de texto
#         info_por_usuario = parsear_bloques_desde_txt(ruta_txt)
#         logger.info(f"✅ TXT parseado, usuarios encontrados: {len(info_por_usuario)}")
#
#         # 2) Leer la hoja
#         gc = get_gspread_client()
#         logger.info("✅ Cliente gspread obtenido")
#
#         spreadsheet = gc.open_by_key(str_key)
#         logger.info(f"✅ Spreadsheet abierto: {spreadsheet.title}")
#
#         worksheet = spreadsheet.worksheet(nombre_hoja)
#         logger.info(f"✅ Worksheet abierto: {worksheet.title}")
#
#         # Detectar rango
#         columna_B = worksheet.col_values(2)[3:]
#         ultima_fila = 3 + len([c for c in columna_B if c.strip() != ""])
#         rango = f"A4:X{ultima_fila}"
#         logger.info(f"📊 Rango calculado: {rango}")
#
#         filas = worksheet.get(rango)
#         logger.info(f"✅ Filas obtenidas: {len(filas)}")
#
#         aspirantes = []
#         for i, fila in enumerate(filas):
#             fila += [''] * (25 - len(fila))  # normaliza tamaño
#             usuario = fila[1].strip()
#
#             aspirante = {
#                 "usuario": usuario,
#                 "telefono": fila[2].strip().replace(" ", "").replace("+", ""),
#                 "disponibilidad": fila[3].strip(),
#                 "motivo_no_apto": fila[4].strip().upper(),
#                 "perfil": fila[5].strip(),
#                 "contacto": fila[8].strip(),
#                 "respuesta_creador": fila[9].strip(),
#                 "entrevista": fila[11].strip(),
#                 "tipo_solicitud": fila[15].strip(),
#                 "email": fila[16].strip(),
#                 "nickname": fila[17].strip(),
#                 "razon_no_contacto": fila[18].strip().upper(),
#                 "fila_excel": i + 4
#             }
#
#             # Mezclar datos del TXT
#             txt = info_por_usuario.get(usuario, {})
#             aspirante["seguidores"] = txt.get("seguidores", "")
#             aspirante["videos"] = txt.get("videos", "")
#             aspirante["likes"] = txt.get("likes", "")
#             aspirante["Duracion_Emisiones"] = txt.get("Duracion_Emisiones", "")
#             aspirante["Dias_Emisiones"] = txt.get("Dias_Emisiones", "")
#             aspirante["caducidad_solicitud"] = txt.get("caducidad_solicitud", "")
#             aspirante["agente_recluta"] = txt.get("agente_recluta", "")
#             aspirante["fecha_solicitud"] = txt.get("fecha_solicitud", "")
#
#             aspirantes.append(aspirante)
#
#         logger.info(f"✅ Aspirantes procesados: {len(aspirantes)}")
#         return aspirantes
#
#     except Exception as e:
#         logger.error(f"❌ Error leyendo hoja de cálculo: {e}", exc_info=True)
#         return []



# def obtener_aspirantes_desde_hoja(str_key, nombre_hoja):
#     try:
#         gc = get_gspread_client()
#         spreadsheet = gc.open_by_key(str_key)
#         worksheet = spreadsheet.worksheet(nombre_hoja)
#         columna_B = worksheet.col_values(2)[3:]
#         ultima_fila = 3 + len([c for c in columna_B if c.strip() != ""])
#         rango = f"A4:X{ultima_fila}"
#         filas = worksheet.get(rango)
#
#         def to_int(val):
#             try: return int(val)
#             except: return None
#
#         aspirantes = []
#         for i, fila in enumerate(filas):
#             fila += [''] * (25 - len(fila))
#             aspirante = {
#                 "usuario": fila[1].strip(),
#                 "telefono": fila[2].strip().replace(" ", "").replace("+", ""),
#                 "disponibilidad": fila[3].strip(),
#                 "motivo_no_apto": fila[4].strip().upper(),
#                 "perfil": fila[5].strip(),
#                 "contacto": fila[8].strip(),
#                 "respuesta_creador": fila[9].strip(),
#                 "entrevista": fila[11].strip(),
#                 "tipo_solicitud": fila[15].strip(),
#                 "email": fila[16].strip(),
#                 "nickname": fila[17].strip(),
#                 "razon_no_contacto": fila[18].strip().upper(),
#                 "seguidores": to_int(fila[19].strip()),
#                 "videos": to_int(fila[20].strip()),
#                 "likes": to_int(fila[21].strip()),
#                 "Duracion_Emisiones": to_int(fila[22].strip()),
#                 "Dias_Emisiones": to_int(fila[23].strip()),
#                 "fila_excel": i + 4
#             }
#             aspirantes.append(aspirante)
#         return aspirantes
#     except Exception as e:
#         print(f"❌ Error leyendo hoja de cálculo: {e}")
#         return []

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


# def guardar_aspirantes(aspirantes, nombre_archivo=None, hoja_excel=None, lote_carga=None, procesado_por=None,
#                       observaciones=None):
#     conn = get_connection()
#     cur = conn.cursor()
#     resultados = []
#     filas_fallidas = []
#
#     for c in aspirantes:
#         try:
#             usuario = c.get("usuario", "")
#             nickname = c.get("nickname", "")
#             email = c.get("email", "")
#             telefono = limpiar_telefono(c.get("telefono", ""))
#             disponibilidad = c.get("disponibilidad", "")
#             perfil = c.get("perfil", "")
#             motivo_no_apto = c.get("motivo_no_apto", "")
#             contacto = c.get("contacto", "")
#             respuesta_creador = c.get("respuesta_creador", "")
#             entrevista = c.get("entrevista", "")
#             tipo_solicitud = c.get("tipo_solicitud", "")
#             razon_no_contacto = c.get("razon_no_contacto", "")
#             seguidores = safe_int(c.get("seguidores", ""))
#             cantidad_videos = safe_int(c.get("videos", ""))
#             likes_totales = safe_int(c.get("likes", ""))
#             duracion_emisiones = safe_int(c.get("Duracion_Emisiones", ""))
#             dias_emisiones = safe_int(c.get("Dias_Emisiones", ""))
#             fila_excel = c.get("fila_excel")
#             apto = not bool(str(motivo_no_apto).strip())
#
#             # 1. creadores
#             cur.execute("SELECT id FROM creadores WHERE usuario = %s", (usuario,))
#             creador_row = cur.fetchone()
#             if creador_row:
#                 creador_id = creador_row[0]
#                 cur.execute("""
#                     UPDATE creadores SET
#                         nickname = %s,
#                         email = %s,
#                         telefono = %s,
#                         actualizado_en = NOW()
#                     WHERE id = %s
#                 """, (nickname, email, telefono, creador_id))
#             else:
#                 cur.execute("""
#                     INSERT INTO creadores (usuario, nickname, email, telefono, activo, creado_en, actualizado_en)
#                     VALUES (%s, %s, %s, %s, TRUE, NOW(), NOW())
#                     RETURNING id
#                 """, (usuario, nickname, email, telefono))
#                 creador_id = cur.fetchone()[0]
#
#             # 2. perfil_creador
#
#             # Elimina cualquier referencia a perfil en perfil_creador:
#             cur.execute("SELECT id FROM perfil_creador WHERE creador_id = %s", (creador_id,))
#             perfil_row = cur.fetchone()
#             if perfil_row:
#                 cur.execute("""
#                     UPDATE perfil_creador SET
#                         seguidores = %s,
#                         cantidad_videos = %s,
#                         likes_totales = %s,
#                         duracion_emisiones = %s,
#                         dias_emisiones = %s,
#                         actualizado_en = NOW()
#                     WHERE creador_id = %s
#                 """, (
#                     seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones, creador_id
#                 ))
#             else:
#                 cur.execute("""
#                     INSERT INTO perfil_creador (
#                         creador_id,
#                         seguidores, cantidad_videos, likes_totales,
#                         duracion_emisiones, dias_emisiones,
#                         creado_en, actualizado_en
#                     ) VALUES (
#                         %s, %s, %s, %s, %s, %s, NOW(), NOW()
#                     )
#                 """, (
#                     creador_id, seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones
#                 ))
#
#             # 3. cargue_creadores
#             cur.execute("SELECT id FROM cargue_creadores WHERE usuario = %s AND hoja_excel = %s", (usuario, hoja_excel))
#             cargue_row = cur.fetchone()
#             if cargue_row:
#                 cargue_id = cargue_row[0]
#                 cur.execute("""
#                     UPDATE cargue_creadores SET
#                         nickname = %s,
#                         email = %s,
#                         telefono = %s,
#                         disponibilidad = %s,
#                         perfil = %s,
#                         motivo_no_apto = %s,
#                         contacto = %s,
#                         respuesta_creador = %s,
#                         entrevista = %s,
#                         tipo_solicitud = %s,
#                         razon_no_contacto = %s,
#                         seguidores = %s,
#                         cantidad_videos = %s,
#                         likes_totales = %s,
#                         duracion_emisiones = %s,
#                         dias_emisiones = %s,
#                         nombre_archivo = %s,
#                         fila_excel = %s,
#                         lote_carga = %s,
#                         estado = %s,
#                         procesado = %s,
#                         procesado_por = %s,
#                         creador_id = %s,
#                         apto = %s,
#                         observaciones = %s,
#                         actualizado_en = NOW()
#                     WHERE id = %s
#                 """, (
#                     nickname, email, telefono, disponibilidad, perfil, motivo_no_apto,
#                     contacto, respuesta_creador, entrevista, tipo_solicitud, razon_no_contacto,
#                     seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones,
#                     nombre_archivo, fila_excel, lote_carga, "Procesando", False, procesado_por,
#                     creador_id, apto, observaciones, cargue_id
#                 ))
#             else:
#                 cur.execute("""
#                     INSERT INTO cargue_creadores (
#                         usuario, nickname, email, telefono, disponibilidad, perfil, motivo_no_apto,
#                         contacto, respuesta_creador, entrevista, tipo_solicitud, razon_no_contacto,
#                         seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones,
#                         nombre_archivo, hoja_excel, fila_excel, lote_carga,
#                         estado, procesado, procesado_por, creador_id,
#                         apto, observaciones, activo, creado_en, actualizado_en
#                     ) VALUES (
#                         %s, %s, %s, %s, %s, %s, %s,
#                         %s, %s, %s, %s, %s,
#                         %s, %s, %s, %s, %s,
#                         %s, %s, %s, %s,
#                         %s, %s, %s, %s,
#                         %s, %s, TRUE, NOW(), NOW()
#                     )
#                 """, (
#                     usuario, nickname, email, telefono, disponibilidad, perfil, motivo_no_apto,
#                     contacto, respuesta_creador, entrevista, tipo_solicitud, razon_no_contacto,
#                     seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones,
#                     nombre_archivo, hoja_excel, fila_excel, lote_carga,
#                     "Procesando", False, procesado_por, creador_id,
#                     apto, observaciones
#                 ))
#
#             resultados.append({
#                 "fila": fila_excel,
#                 "usuario": usuario,
#                 "creador_id": creador_id
#             })
#         except Exception as e:
#             logger.error("Error al guardar aspirante", exc_info=True)
#             return {
#                 "status": "error",
#                 "mensaje": "Error guardando aspirantes",
#                 "error": str(e),  # <- usa e, no err
#             }
#
#     conn.commit()
#     cur.close()
#     conn.close()
#     print(f"✅ Contactos procesados. Filas exitosas: {len(resultados)}. Filas fallidas: {len(filas_fallidas)}")
#     return {
#         "exitosos": resultados,
#         "fallidos": filas_fallidas
#     }


# def guardar_aspirantes(
#     aspirantes, nombre_archivo=None, hoja_excel=None, lote_carga=None, procesado_por=None,
#     observaciones=None
# ):
#     conn = get_connection()
#     cur = conn.cursor()
#     resultados = []
#     filas_fallidas = []
#
#     for c in aspirantes:
#         try:
#             usuario = get_text(c.get("usuario"))
#             nickname = get_text(c.get("nickname"))
#             email = get_text(c.get("email"))
#             telefono = limpiar_telefono(get_text(c.get("telefono")))
#             disponibilidad = get_text(c.get("disponibilidad"))
#             perfil = get_text(c.get("perfil"))
#             motivo_no_apto = get_text(c.get("motivo_no_apto"))
#             contacto = get_text(c.get("contacto"))
#             respuesta_creador = get_text(c.get("respuesta_creador"))
#             entrevista = get_text(c.get("entrevista"))
#             tipo_solicitud = get_text(c.get("tipo_solicitud"))
#             razon_no_contacto = get_text(c.get("razon_no_contacto"))
#
#             # ⬇️ AHORA TODO TEXTO (sin safe_int)
#             seguidores = get_text(c.get("seguidores"))
#             cantidad_videos = get_text(c.get("videos"))
#             likes_totales = get_text(c.get("likes"))
#             duracion_emisiones = get_text(c.get("Duracion_Emisiones"))
#             dias_emisiones = get_text(c.get("Dias_Emisiones"))
#
#             fila_excel = c.get("fila_excel")
#             apto = not bool(motivo_no_apto)
#
#             # 1) creadores
#             cur.execute("SELECT id FROM creadores WHERE usuario = %s", (usuario,))
#             creador_row = cur.fetchone()
#             if creador_row:
#                 creador_id = creador_row[0]
#                 cur.execute("""
#                     UPDATE creadores SET
#                         nickname = %s,
#                         email = %s,
#                         telefono = %s,
#                         actualizado_en = NOW()
#                     WHERE id = %s
#                 """, (nickname, email, telefono, creador_id))
#             else:
#                 cur.execute("""
#                     INSERT INTO creadores (usuario, nickname, email, telefono, activo, creado_en, actualizado_en)
#                     VALUES (%s, %s, %s, %s, TRUE, NOW(), NOW())
#                     RETURNING id
#                 """, (usuario, nickname, email, telefono))
#                 creador_id = cur.fetchone()[0]
#
#             # 2) perfil_creador (valores como TEXT)
#             cur.execute("SELECT id FROM perfil_creador WHERE creador_id = %s", (creador_id,))
#             perfil_row = cur.fetchone()
#             if perfil_row:
#                 cur.execute("""
#                     UPDATE perfil_creador SET
#                         seguidores = %s,
#                         cantidad_videos = %s,
#                         likes_totales = %s,
#                         duracion_emisiones = %s,
#                         dias_emisiones = %s,
#                         actualizado_en = NOW()
#                     WHERE creador_id = %s
#                 """, (
#                     seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones, creador_id
#                 ))
#             else:
#                 cur.execute("""
#                     INSERT INTO perfil_creador (
#                         creador_id,
#                         seguidores, cantidad_videos, likes_totales,
#                         duracion_emisiones, dias_emisiones,
#                         creado_en, actualizado_en
#                     ) VALUES (
#                         %s, %s, %s, %s, %s, %s, NOW(), NOW()
#                     )
#                 """, (
#                     creador_id, seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones
#                 ))
#
#             # 3) cargue_creadores (también como TEXT)
#             cur.execute("SELECT id FROM cargue_creadores WHERE usuario = %s AND hoja_excel = %s", (usuario, hoja_excel))
#             cargue_row = cur.fetchone()
#             if cargue_row:
#                 cargue_id = cargue_row[0]
#                 cur.execute("""
#                     UPDATE cargue_creadores SET
#                         nickname = %s,
#                         email = %s,
#                         telefono = %s,
#                         disponibilidad = %s,
#                         perfil = %s,
#                         motivo_no_apto = %s,
#                         contacto = %s,
#                         respuesta_creador = %s,
#                         entrevista = %s,
#                         tipo_solicitud = %s,
#                         razon_no_contacto = %s,
#                         seguidores = %s,
#                         cantidad_videos = %s,
#                         likes_totales = %s,
#                         duracion_emisiones = %s,
#                         dias_emisiones = %s,
#                         nombre_archivo = %s,
#                         fila_excel = %s,
#                         lote_carga = %s,
#                         estado = %s,
#                         procesado = %s,
#                         procesado_por = %s,
#                         creador_id = %s,
#                         apto = %s,
#                         observaciones = %s,
#                         actualizado_en = NOW()
#                     WHERE id = %s
#                 """, (
#                     nickname, email, telefono, disponibilidad, perfil, motivo_no_apto,
#                     contacto, respuesta_creador, entrevista, tipo_solicitud, razon_no_contacto,
#                     seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones,
#                     nombre_archivo, fila_excel, lote_carga, "Procesando", False, procesado_por,
#                     creador_id, apto, observaciones, cargue_id
#                 ))
#             else:
#                 cur.execute("""
#                     INSERT INTO cargue_creadores (
#                         usuario, nickname, email, telefono, disponibilidad, perfil, motivo_no_apto,
#                         contacto, respuesta_creador, entrevista, tipo_solicitud, razon_no_contacto,
#                         seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones,
#                         nombre_archivo, hoja_excel, fila_excel, lote_carga,
#                         estado, procesado, procesado_por, creador_id,
#                         apto, observaciones, activo, creado_en, actualizado_en
#                     ) VALUES (
#                         %s, %s, %s, %s, %s, %s, %s,
#                         %s, %s, %s, %s, %s,
#                         %s, %s, %s, %s, %s,
#                         %s, %s, %s, %s,
#                         %s, %s, %s, %s,
#                         %s, %s, TRUE, NOW(), NOW()
#                     )
#                 """, (
#                     usuario, nickname, email, telefono, disponibilidad, perfil, motivo_no_apto,
#                     contacto, respuesta_creador, entrevista, tipo_solicitud, razon_no_contacto,
#                     seguidores, cantidad_videos, likes_totales, duracion_emisiones, dias_emisiones,
#                     nombre_archivo, hoja_excel, fila_excel, lote_carga,
#                     "Procesando", False, procesado_por, creador_id,
#                     apto, observaciones
#                 ))
#
#             resultados.append({
#                 "fila": fila_excel,
#                 "usuario": usuario,
#                 "creador_id": creador_id
#             })
#
#         except Exception as e:
#             logger.error(f"Error al guardar aspirante (fila={c.get('fila_excel')}, usuario={c.get('usuario')})", exc_info=True)
#             filas_fallidas.append({
#                 "fila": c.get("fila_excel"),
#                 "usuario": c.get("usuario"),
#                 "error": str(e),
#             })
#             # continuar con el siguiente registro
#
#     conn.commit()
#     cur.close()
#     conn.close()
#
#     print(f"✅ Contactos procesados. Filas exitosas: {len(resultados)}. Filas fallidas: {len(filas_fallidas)}")
#     return {
#         "status": "ok",
#         "exitosos": resultados,
#         "fallidos": filas_fallidas
#     }


import re

def get_text(val):
    """Texto limpio (str) o cadena vacía si viene None."""
    return "" if val is None else str(val).strip()

def to_int_relaxed(val, default=0):
    """
    Convierte '1,151' o '47 237' -> 1151 / 47237.
    - Elimina espacios y comas.
    - Si no se puede convertir, devuelve 'default' (por defecto 0).
    """
    if val is None:
        return default
    s = str(val).strip()
    if not s:
        return default
    s = s.replace(" ", "").replace(",", "")
    return int(s) if s.isdigit() else default

def parse_days_to_int(val, default=0):
    """
    Convierte '24d' -> 24, '1d' -> 1, '0d' -> 0, '15' -> 15.
    Si no se puede convertir, devuelve 'default' (por defecto 0).
    """
    if val is None:
        return default
    s = str(val).strip().lower()
    if not s:
        return default
    if s.endswith("d"):
        s = s[:-1]
    try:
        return int(s)
    except ValueError:
        # último intento: limpiar como número relajado
        return to_int_relaxed(s, default=default)

def parse_duration_to_hours_int(text, default=0):

    if text is None:
        return default
    s = str(text).strip().lower()
    if not s:
        return default

    # Unificar 'min' -> 'm'
    s = s.replace("min", "m")

    days = hours = mins = secs = 0
    md = re.search(r"(\d+)\s*d", s)
    mh = re.search(r"(\d+)\s*h", s)
    mm = re.search(r"(\d+)\s*m(?![a-z])", s)  # evita 'ms'
    ms = re.search(r"(\d+)\s*s", s)

    if md: days = int(md.group(1))
    if mh: hours = int(mh.group(1))
    if mm: mins = int(mm.group(1))
    if ms: secs = int(ms.group(1))

    # Si no hay ningún match pero es número simple, interpretarlo como horas
    if not (md or mh or mm or ms):
        try:
            return int(round(float(s)))
        except ValueError:
            return default

    total_hours = days * 24 + hours + mins / 60.0 + secs / 3600.0
    return int(round(total_hours))


# -------------------- guardar_aspirantes (ajustada) --------------------
def obtener_aspirantes_desde_hoja(str_key, nombre_hoja, ruta_txt):
    try:
        # 1) Parseo TXT (como ya lo tienes)
        info_por_usuario = parsear_bloques_desde_txt(ruta_txt)

        # 2) Conectar y abrir hoja
        gc = get_gspread_client()
        spreadsheet = gc.open_by_key(str_key)
        worksheet = spreadsheet.worksheet(nombre_hoja)

        # ---- Cálculo de última fila basado en Columna B (usuarios) ----
        # B4 en adelante son datos; B3 es encabezado.
        col_B_desde_4 = worksheet.col_values(2)[3:]  # índice base 0 => [3:] salta 3 filas (hasta B3)
        # Filas no vacías (trim)
        col_B_no_vacias = [c for c in col_B_desde_4 if str(c).strip() != ""]
        ultima_fila = 3 + len(col_B_no_vacias)  # fila 3 + cantidad de filas con usuario

        # Si por algún motivo viene un hueco en B pero hay otras columnas con datos,
        # usamos un fallback: leer A4:X(3 + len(col_B_desde_4)) y luego filtrar vacíos.
        rango = f"A4:X{ultima_fila}"
        filas = worksheet.get(rango)

        # Fallback si el rango vino vacío pero había datos en B
        if not filas and col_B_desde_4:
            rango_fallback = f"A4:X{3 + len(col_B_desde_4)}"
            filas = worksheet.get(rango_fallback)

        aspirantes = []
        for i, fila in enumerate(filas):
            # normaliza ancho a 24 columnas (A..X)
            if len(fila) < 24:
                fila += [''] * (24 - len(fila))

            usuario = fila[1].strip()  # Columna B
            if not usuario:
                # si la fila no tiene usuario, saltamos
                continue

            aspirante = {
                "usuario": usuario,
                "telefono": fila[2].strip().replace(" ", "").replace("+", ""),  # C
                "disponibilidad": fila[3].strip(),                              # D
                "motivo_no_apto": fila[4].strip().upper(),                     # E
                "perfil": fila[5].strip(),                                     # F
                "contacto": fila[8].strip(),                                   # I
                "respuesta_creador": fila[9].strip(),                          # J
                "entrevista": fila[11].strip(),                                 # L
                "tipo_solicitud": fila[15].strip(),                             # P
                "email": fila[16].strip(),                                      # Q
                "nickname": fila[17].strip(),                                   # R
                "razon_no_contacto": fila[18].strip().upper(),                  # S
                # Métricas vienen del TXT (no del sheet)
                "seguidores": "",
                "videos": "",
                "likes": "",
                "Duracion_Emisiones": "",
                "Dias_Emisiones": "",
                "fila_excel": i + 4,  # porque empezamos en la fila 4
            }

            # Mezcla con datos del TXT por usuario
            datos_txt = info_por_usuario.get(usuario, {})
            if datos_txt:
                aspirante["seguidores"] = datos_txt.get("seguidores", "")
                aspirante["videos"] = datos_txt.get("videos", "")
                aspirante["likes"] = datos_txt.get("likes", "")
                aspirante["Duracion_Emisiones"] = datos_txt.get("Duracion_Emisiones", "")
                aspirante["Dias_Emisiones"] = datos_txt.get("Dias_Emisiones", "")
                aspirante["nombre"] = datos_txt.get("nombre", "")
                aspirante["caducidad_solicitud"] = datos_txt.get("caducidad_solicitud", "")
                aspirante["agente_recluta"] = datos_txt.get("agente_recluta", "")
                aspirante["fecha_solicitud"] = datos_txt.get("fecha_solicitud", "")
                aspirante["canal"] = datos_txt.get("canal", "")

            aspirantes.append(aspirante)

        return aspirantes

    except Exception as e:
        print(f"❌ Error leyendo hoja de cálculo: {e}")
        return []


def guardar_aspirantes(
    aspirantes, nombre_archivo=None, hoja_excel=None, lote_carga=None, procesado_por=None,
    observaciones=None
):
    """
    Guarda aspirantes mapeando los campos del TXT a los tipos de la tabla:

      perfil_creador.seguidores            -> integer
      perfil_creador.videos                -> integer
      perfil_creador.likes                 -> bigint
      perfil_creador.duracion_emisiones    -> integer (HORAS redondeadas)
      perfil_creador.dias_emisiones        -> integer (quita 'd')

    NOTA: Se asume que get_connection(), limpiar_telefono() y logger existen en tu entorno.
    """
    conn = get_connection()
    cur = conn.cursor()
    resultados = []
    filas_fallidas = []

    for c in aspirantes:
        try:
            usuario = get_text(c.get("usuario"))
            nickname = get_text(c.get("nickname"))
            email = get_text(c.get("email"))
            telefono = limpiar_telefono(get_text(c.get("telefono")))
            disponibilidad = get_text(c.get("disponibilidad"))
            perfil = get_text(c.get("perfil"))
            motivo_no_apto = get_text(c.get("motivo_no_apto"))
            contacto = get_text(c.get("contacto"))
            respuesta_creador = get_text(c.get("respuesta_creador"))
            entrevista = get_text(c.get("entrevista"))
            tipo_solicitud = get_text(c.get("tipo_solicitud"))
            razon_no_contacto = get_text(c.get("razon_no_contacto"))

            # === Conversión a tipos que exige la tabla ===
            seguidores = to_int_relaxed(c.get("seguidores"), default=0)          # integer
            cantidad_videos = to_int_relaxed(c.get("videos"), default=0)         # integer
            likes_totales = to_int_relaxed(c.get("likes"), default=0)            # bigint ok
            duracion_emisiones = parse_duration_to_hours_int(c.get("Duracion_Emisiones"), default=0)  # integer (horas)
            dias_emisiones = parse_days_to_int(c.get("Dias_Emisiones"), default=0)                    # integer (días)

            fila_excel = c.get("fila_excel")
            apto = not bool(motivo_no_apto)

            # 1) creadores
            cur.execute("SELECT id FROM creadores WHERE usuario = %s", (usuario,))
            creador_row = cur.fetchone()
            if creador_row:
                creador_id = creador_row[0]
                cur.execute("""
                    UPDATE creadores SET
                        nickname = %s,
                        email = %s,
                        telefono = %s,
                        estado_id = 3,
                        actualizado_en = NOW()
                    WHERE id = %s
                """, (
                    get_text(c.get("nombre")),  # ⬅️ usamos el mismo nombre que en perfil_creador.nombre
                    email,
                    telefono,
                    creador_id
                ))
            else:
                cur.execute("""
                    INSERT INTO creadores (usuario, nickname, email, telefono, estado_id, activo, creado_en, actualizado_en)
                    VALUES (%s, %s, %s, %s, 3, TRUE, NOW(), NOW())
                    RETURNING id
                """, (
                    usuario,
                    get_text(c.get("nombre")),  # ⬅️ nickname = nombre del TXT
                    email,
                    telefono
                ))
                creador_id = cur.fetchone()[0]

            # 2) perfil_creador (tipos numéricos según tu esquema)
            cur.execute("SELECT id FROM perfil_creador WHERE creador_id = %s", (creador_id,))
            perfil_row = cur.fetchone()
            if perfil_row:
                cur.execute("""
                    UPDATE perfil_creador SET
                        usuario = %s,
                        seguidores = %s,
                        videos = %s,
                        likes = %s,
                        duracion_emisiones = %s,
                        dias_emisiones = %s,
                        nombre = %s,
                        actualizado_en = NOW()
                    WHERE creador_id = %s
                """, (
                    usuario,
                    seguidores, cantidad_videos, likes_totales,
                    duracion_emisiones, dias_emisiones,
                    get_text(c.get("nombre")),  # opcional: guardar el "Nombre" del TXT
                    creador_id
                ))
            else:
                cur.execute("""
                    INSERT INTO perfil_creador (
                        usuario, creador_id,
                        seguidores, videos, likes,
                        duracion_emisiones, dias_emisiones,
                        nombre, creado_en, actualizado_en
                    ) VALUES (
                        %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, NOW(), NOW()
                    )
                """, (
                    usuario, creador_id,
                    seguidores, cantidad_videos, likes_totales,
                    duracion_emisiones, dias_emisiones,
                    get_text(c.get("nombre"))
                ))

            # 3) cargue_creadores (si tus columnas allí son texto/mixtas, se mantienen)
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

        except Exception as e:
            logger.error(
                f"Error al guardar aspirante (fila={c.get('fila_excel')}, usuario={c.get('usuario')}): {e}",
                exc_info=True
            )
            filas_fallidas.append({
                "fila": c.get("fila_excel"),
                "usuario": c.get("usuario"),
                "error": str(e),
            })
            # continuar con el siguiente registro

    conn.commit()
    cur.close()
    conn.close()

    print(f"✅ Contactos procesados. Filas exitosas: {len(resultados)}. Filas fallidas: {len(filas_fallidas)}")
    return {
        "status": "ok",
        "exitosos": resultados,
        "fallidos": filas_fallidas
    }

