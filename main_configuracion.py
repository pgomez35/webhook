import os

from fastapi import APIRouter, HTTPException, Body, Query, UploadFile, Form
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

import re

import cloudinary
import cloudinary.uploader

from tenant import current_tenant, current_business_name

_cloudinary_configured = False


def _ensure_cloudinary_config() -> None:
    global _cloudinary_configured
    if _cloudinary_configured:
        return
    cloudinary.config(
        cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key=os.environ["CLOUDINARY_API_KEY"],
        api_secret=os.environ["CLOUDINARY_API_SECRET"],
        secure=True,
    )
    _cloudinary_configured = True


from DataBase import get_connection_context, get_connection_public

router = APIRouter()

# ==========================================================
# MODELOS
# ==========================================================

class ConfigKeyOut(BaseModel):
    clave: str
    grupo: str
    tipo: str
    valor_default: str
    descripcion: Optional[str] = None
    editable: bool
    orden: int
    requerido: bool
    validacion_regex: Optional[str] = None
    actualizado_en: Optional[datetime] = None


class ConfigItemOut(BaseModel):
    clave: str
    valor: str
    actualizado_en: Optional[datetime] = None


class ConfigUpdateIn(BaseModel):
    valor: str


class ConfigItemFullOut(BaseModel):
    # KEYS (public)
    clave: str
    grupo: str
    tipo: str
    valor_default: str
    descripcion: Optional[str] = None
    editable: bool
    orden: int
    requerido: bool
    validacion_regex: Optional[str] = None
    actualizado_en: Optional[datetime] = None  # keys actualizado_en

    # TENANT
    valor: str
    valor_actualizado_en: Optional[datetime] = None


# ==========================================================
# RUTAS FIJAS (SIEMPRE VAN PRIMERO)
# ==========================================================

@router.get("/api/configuracion-agencia/grupos", response_model=List[str])
def listar_grupos_config():
    with get_connection_public() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT grupo
                FROM public.configuracion_agencia_keys
                ORDER BY grupo ASC
            """)
            rows = cur.fetchall()

    return [r[0] for r in rows]


def listar_config_keys():
    with get_connection_public() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    clave,
                    grupo,
                    tipo,
                    valor_default,
                    descripcion,
                    editable,
                    orden,
                    requerido,
                    validacion_regex,
                    actualizado_en
                FROM public.configuracion_agencia_keys
                ORDER BY grupo ASC, orden ASC, clave ASC
            """)
            rows = cur.fetchall()

    return [
        ConfigKeyOut(
            clave=r[0],
            grupo=r[1],
            tipo=r[2],
            valor_default=r[3],
            descripcion=r[4],
            editable=r[5],
            orden=r[6],
            requerido=r[7],
            validacion_regex=r[8],
            actualizado_en=r[9],
        )
        for r in rows
    ]


def obtener_config_full():
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    k.clave,
                    k.grupo,
                    k.tipo,
                    k.valor_default,
                    k.descripcion,
                    k.editable,
                    k.orden,
                    k.requerido,
                    k.validacion_regex,
                    k.actualizado_en,
                    a.valor,
                    a.actualizado_en
                FROM public.configuracion_agencia_keys k
                LEFT JOIN configuracion_agencia a
                       ON a.clave = k.clave
                ORDER BY k.grupo ASC, k.orden ASC, k.clave ASC
            """)
            rows = cur.fetchall()

    out = []
    for r in rows:
        valor_final = r[10] if r[10] else r[3]

        out.append(
            ConfigItemFullOut(
                clave=r[0],
                grupo=r[1],
                tipo=r[2],
                valor_default=r[3],
                descripcion=r[4],
                editable=r[5],
                orden=r[6],
                requerido=r[7],
                validacion_regex=r[8],
                actualizado_en=r[9],
                valor=valor_final,
                valor_actualizado_en=r[11],
            )
        )

    return out


@router.get("/api/configuracion-agencia/full/grupo/{grupo}", response_model=List[ConfigItemFullOut])
def obtener_config_full_por_grupo(grupo: str):
    grupo = grupo.strip()

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    k.clave,
                    k.grupo,
                    k.tipo,
                    k.valor_default,
                    k.descripcion,
                    k.editable,
                    k.orden,
                    k.requerido,
                    k.validacion_regex,
                    k.actualizado_en,
                    a.valor,
                    a.actualizado_en
                FROM public.configuracion_agencia_keys k
                LEFT JOIN configuracion_agencia a
                       ON a.clave = k.clave
                WHERE k.grupo = %s
                ORDER BY k.orden ASC, k.clave ASC
            """, (grupo,))
            rows = cur.fetchall()

    out = []
    for r in rows:
        valor_final = r[10] if r[10] else r[3]

        out.append(
            ConfigItemFullOut(
                clave=r[0],
                grupo=r[1],
                tipo=r[2],
                valor_default=r[3],
                descripcion=r[4],
                editable=r[5],
                orden=r[6],
                requerido=r[7],
                validacion_regex=r[8],
                actualizado_en=r[9],
                valor=valor_final,
                valor_actualizado_en=r[11],
            )
        )

    return out


def listar_config_tenant():
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT clave, valor, actualizado_en
                FROM configuracion_agencia
                ORDER BY clave ASC
            """)
            rows = cur.fetchall()

    return [
        ConfigItemOut(clave=r[0], valor=r[1], actualizado_en=r[2])
        for r in rows
    ]


# ==========================================================
# RUTA DINÁMICA (SIEMPRE AL FINAL)
# ==========================================================

@router.get("/api/configuracion-agencia/{clave}", response_model=ConfigItemOut)
def obtener_config_por_clave(clave: str):
    clave = clave.strip()

    with get_connection_context() as conn:
        with conn.cursor() as cur:

            # 1️⃣ Buscar en tenant
            cur.execute("""
                SELECT clave, valor, actualizado_en
                FROM configuracion_agencia
                WHERE clave = %s
                LIMIT 1
            """, (clave,))
            row = cur.fetchone()

            if row:
                return ConfigItemOut(
                    clave=row[0],
                    valor=row[1],
                    actualizado_en=row[2]
                )

            # 2️⃣ Si no existe en tenant, usar default
            cur.execute("""
                SELECT clave, valor_default, actualizado_en
                FROM public.configuracion_agencia_keys
                WHERE clave = %s
                LIMIT 1
            """, (clave,))
            key_row = cur.fetchone()

            if key_row:
                return ConfigItemOut(
                    clave=key_row[0],
                    valor=key_row[1],
                    actualizado_en=key_row[2]
                )

    raise HTTPException(status_code=404, detail="Clave de configuración no encontrada")


@router.put("/api/configuracion-agencia/{clave}", response_model=ConfigItemOut)
def upsert_config_valor(clave: str, data: ConfigUpdateIn = Body(...)):
    clave = clave.strip()

    with get_connection_context() as conn:
        with conn.cursor() as cur:

            # Validar existencia en keys
            cur.execute("""
                SELECT editable, requerido, validacion_regex
                FROM public.configuracion_agencia_keys
                WHERE clave = %s
                LIMIT 1
            """, (clave,))
            key_row = cur.fetchone()

            if not key_row:
                raise HTTPException(status_code=404, detail="Clave no existe")

            editable, requerido, validacion_regex = key_row

            if not editable:
                raise HTTPException(status_code=403, detail="Esta clave no es editable")

            valor = (data.valor or "").strip()

            if requerido and valor == "":
                raise HTTPException(status_code=422, detail="Este valor es requerido")

            if validacion_regex and valor:
                try:
                    if not re.fullmatch(validacion_regex, valor):
                        raise HTTPException(status_code=422, detail="El valor no cumple la validación")
                except re.error:
                    pass

            # UPSERT
            cur.execute("""
                INSERT INTO configuracion_agencia (clave, valor)
                VALUES (%s, %s)
                ON CONFLICT (clave)
                DO UPDATE SET
                    valor = EXCLUDED.valor,
                    actualizado_en = now()
                RETURNING clave, valor, actualizado_en
            """, (clave, valor))

            row = cur.fetchone()

    return ConfigItemOut(clave=row[0], valor=row[1], actualizado_en=row[2])

# ---------------------------------------------------------
# ---------------------------------------------------------
# ----------------TIPOS DE AGENDAMIENTO-----------
# ---------------------------------------------------------
# ---------------------------------------------------------

class TipoAgendamientoIn(BaseModel):
    nombre: str = Field(..., max_length=100)
    color: Optional[str] = Field(None, max_length=20)   # ej: "#4F46E5"
    icono: Optional[str] = Field(None, max_length=50)   # ej: "🎉" o "calendar"
    activo: Optional[bool] = True
    participante_tipo_id: Optional[int] = None
    medio_reunion_id: Optional[int] = None

class TipoAgendamientoOut(BaseModel):
    id: int
    nombre: str
    color: Optional[str] = None
    icono: Optional[str] = None
    activo: bool = True
    creado_en: Optional[datetime] = None
    participante_tipo_id: Optional[int] = None
    medio_reunion_id: Optional[int] = None


class AgendamientoMedioOut(BaseModel):
    id: int
    codigo: str
    nombre: str
    requiere_link: bool = False
    activo: bool = True


@router.get("/agendamientos/medios", response_model=List[AgendamientoMedioOut])
def listar_medios_reunion(solo_activos: bool = Query(True)):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            if solo_activos:
                cur.execute("""
                    SELECT id, codigo, nombre, requiere_link, activo
                    FROM agendamientos_medio
                    WHERE activo = TRUE
                    ORDER BY id ASC
                """)
            else:
                cur.execute("""
                    SELECT id, codigo, nombre, requiere_link, activo
                    FROM agendamientos_medio
                    ORDER BY id ASC
                """)
            rows = cur.fetchall()
    return [
        AgendamientoMedioOut(
            id=r[0], codigo=r[1], nombre=r[2], requiere_link=bool(r[3]), activo=bool(r[4])
        )
        for r in rows
    ]


@router.get("/agendamientos/tipos", response_model=List[TipoAgendamientoOut])
def listar_tipos_agendamiento(
    solo_activos: bool = Query(True)
):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            if solo_activos:
                cur.execute("""
                    SELECT id, nombre, color, icono, activo, creado_en,
                           participante_tipo_id, medio_reunion_id
                    FROM agendamientos_tipo
                    WHERE activo = TRUE
                    ORDER BY id ASC
                """)
            else:
                cur.execute("""
                    SELECT id, nombre, color, icono, activo, creado_en,
                           participante_tipo_id, medio_reunion_id
                    FROM agendamientos_tipo
                    ORDER BY id ASC
                """)
            rows = cur.fetchall()

    return [
        TipoAgendamientoOut(
            id=r[0],
            nombre=r[1],
            color=r[2],
            icono=r[3],
            activo=r[4],
            creado_en=r[5],
            participante_tipo_id=r[6],
            medio_reunion_id=r[7],
        )
        for r in rows
    ]


@router.post("/agendamientos/tipos", response_model=TipoAgendamientoOut)
def crear_tipo_agendamiento(payload: TipoAgendamientoIn):
    nombre = (payload.nombre or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio.")

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            # opcional: evitar duplicados por nombre (case-insensitive)
            cur.execute("""
                SELECT 1 FROM agendamientos_tipo
                WHERE LOWER(nombre) = LOWER(%s)
                LIMIT 1
            """, (nombre,))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="Ya existe un tipo con ese nombre.")

            cur.execute("""
                INSERT INTO agendamientos_tipo (
                    nombre, color, icono, activo,
                    participante_tipo_id, medio_reunion_id
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, nombre, color, icono, activo, creado_en,
                          participante_tipo_id, medio_reunion_id
            """, (
                nombre,
                payload.color,
                payload.icono,
                payload.activo if payload.activo is not None else True,
                payload.participante_tipo_id,
                payload.medio_reunion_id,
            ))

            row = cur.fetchone()
        conn.commit()

    return TipoAgendamientoOut(
        id=row[0],
        nombre=row[1],
        color=row[2],
        icono=row[3],
        activo=row[4],
        creado_en=row[5],
        participante_tipo_id=row[6],
        medio_reunion_id=row[7],
    )


class ToggleActivoIn(BaseModel):
    activo: bool

class TipoAgendamientoUpdate(BaseModel):
    nombre: Optional[str] = Field(None, max_length=100)
    color: Optional[str] = Field(None, max_length=20)
    icono: Optional[str] = Field(None, max_length=50)
    activo: Optional[bool] = None
    participante_tipo_id: Optional[int] = None
    medio_reunion_id: Optional[int] = None

@router.put("/agendamientos/tipos/{tipo_id}", response_model=TipoAgendamientoOut)
def actualizar_tipo_agendamiento(tipo_id: int, payload: TipoAgendamientoUpdate):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, color, icono, activo, creado_en,
                       participante_tipo_id, medio_reunion_id
                FROM agendamientos_tipo
                WHERE id = %s
                LIMIT 1
            """, (tipo_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Tipo de agendamiento no encontrado.")

            nombre = row[1]
            if payload.nombre is not None:
                nombre = payload.nombre.strip()
                if not nombre:
                    raise HTTPException(status_code=400, detail="El nombre no puede quedar vacío.")

            color = payload.color if payload.color is not None else row[2]
            icono = payload.icono if payload.icono is not None else row[3]
            activo = payload.activo if payload.activo is not None else row[4]
            participante_tipo_id = (
                payload.participante_tipo_id
                if payload.participante_tipo_id is not None
                else row[6]
            )
            medio_reunion_id = (
                payload.medio_reunion_id
                if payload.medio_reunion_id is not None
                else row[7]
            )

            # opcional: validar duplicados si cambia nombre
            if payload.nombre is not None:
                cur.execute("""
                    SELECT 1 FROM agendamientos_tipo
                    WHERE LOWER(nombre) = LOWER(%s) AND id <> %s
                    LIMIT 1
                """, (nombre, tipo_id))
                if cur.fetchone():
                    raise HTTPException(status_code=409, detail="Ya existe otro tipo con ese nombre.")

            cur.execute("""
                UPDATE agendamientos_tipo
                SET nombre = %s,
                    color = %s,
                    icono = %s,
                    activo = %s,
                    participante_tipo_id = %s,
                    medio_reunion_id = %s
                WHERE id = %s
                RETURNING id, nombre, color, icono, activo, creado_en,
                          participante_tipo_id, medio_reunion_id
            """, (nombre, color, icono, activo, participante_tipo_id, medio_reunion_id, tipo_id))

            updated = cur.fetchone()
        conn.commit()

    return TipoAgendamientoOut(
        id=updated[0],
        nombre=updated[1],
        color=updated[2],
        icono=updated[3],
        activo=updated[4],
        creado_en=updated[5],
        participante_tipo_id=updated[6],
        medio_reunion_id=updated[7],
    )

@router.patch("/agendamientos/tipos/{tipo_id}/activo", response_model=TipoAgendamientoOut)
def cambiar_activo_tipo_agendamiento(tipo_id: int, payload: ToggleActivoIn):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE agendamientos_tipo
                SET activo = %s
                WHERE id = %s
                RETURNING id, nombre, color, icono, activo, creado_en,
                          participante_tipo_id, medio_reunion_id
            """, (payload.activo, tipo_id))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Tipo de agendamiento no encontrado.")
        conn.commit()

    return TipoAgendamientoOut(
        id=row[0],
        nombre=row[1],
        color=row[2],
        icono=row[3],
        activo=row[4],
        creado_en=row[5],
        participante_tipo_id=row[6],
        medio_reunion_id=row[7],
    )

@router.delete("/agendamientos/tipos/{tipo_id}")
def eliminar_tipo_agendamiento(tipo_id: int):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            # seguridad: si está en uso, mejor bloquear (opcional)
            cur.execute("DELETE FROM agendamientos_tipo WHERE id = %s RETURNING id", (tipo_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Tipo de agendamiento no encontrado.")
        conn.commit()
    return {"status": "ok", "deleted_id": row[0]}



import re
from typing import Any, Optional

def _to_bool(v: Any) -> bool:
    if v is None:
        return False
    return str(v).strip().lower() in ("true", "1", "t", "yes", "si", "y", "on")

def _to_number(v: Any) -> Optional[float]:
    """
    Devuelve int si es entero, float si tiene decimales.
    Retorna None si no se puede convertir.
    """
    if v is None:
        return None
    s = str(v).strip().replace(",", ".")  # por si te llega "3,5"
    if not s:
        return None
    # entero puro
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    # decimal
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return float(s)
    return None

def get_config(clave: str) -> Any:
    """
    Obtiene el valor de configuracion_agencia (public) según la definición en configuracion_agencia_keys.
    Si no existe en configuracion_agencia, usa valor_default.
    Tipos soportados: url, textarea, color, number, boolean, text
    """
    if not clave:
        return None

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            # 1) Definición (tipo + default)
            cur.execute(
                """
                SELECT tipo, valor_default
                FROM public.configuracion_agencia_keys
                WHERE clave = %s
                LIMIT 1;
                """,
                (clave,)
            )
            row_key = cur.fetchone()
            if not row_key:
                return None  # clave no existe en keys

            tipo, valor_default = row_key

            # 2) Valor guardado
            cur.execute(
                """
                SELECT valor
                FROM configuracion_agencia
                WHERE clave = %s
                LIMIT 1;
                """,
                (clave,)
            )
            row_val = cur.fetchone()

    valor = row_val[0] if row_val and row_val[0] is not None else valor_default
    tipo = (tipo or "text").strip().lower()

    # 3) Cast por tipo
    if tipo in ("text", "url", "textarea", "color"):
        return "" if valor is None else str(valor)

    if tipo == "boolean":
        return _to_bool(valor)

    if tipo == "number":
        n = _to_number(valor)
        return n  # puede ser int o float o None

    # fallback
    return valor


@router.post("/api/configuracion-agencia/logo")
async def actualizar_logo_agencia(
    logo: UploadFile = Form(...)
):
    import os
    from datetime import datetime
    from fastapi import HTTPException

    TENANT = current_tenant.get()

    if not TENANT:
        raise HTTPException(status_code=400, detail="Tenant no disponible")

    # --------------------------------------------------
    # 1️⃣ Validar tipo
    # --------------------------------------------------
    if logo.content_type not in [
        "image/jpeg",
        "image/png",
        "image/jpg",
        "image/webp"
    ]:
        raise HTTPException(status_code=400, detail="Tipo de imagen no permitido")

    # --------------------------------------------------
    # 2️⃣ Guardar temporal
    # --------------------------------------------------
    timestamp = int(datetime.now().timestamp())
    filename = f"{TENANT}_logo_{timestamp}_{logo.filename}"

    MEDIA_DIR = "temp_logos"
    os.makedirs(MEDIA_DIR, exist_ok=True)

    ruta_logo = os.path.join(MEDIA_DIR, filename)

    with open(ruta_logo, "wb") as f:
        f.write(await logo.read())

    # --------------------------------------------------
    # 3️⃣ Subir a Cloudinary (optimizado)
    # --------------------------------------------------
    try:
        _ensure_cloudinary_config()
        result = cloudinary.uploader.upload(
            ruta_logo,
            folder=f"branding/{TENANT}",
            public_id=f"{TENANT}_logo",
            overwrite=True,
            resource_type="image",
            transformation=[
                {"width": 400, "crop": "limit"},
                {"quality": "auto"},
                {"fetch_format": "auto"}
            ]
        )

        logo_url = result.get("secure_url")

    except Exception as e:
        try:
            os.remove(ruta_logo)
        except:
            pass

        raise HTTPException(
            status_code=500,
            detail=f"Error subiendo logo: {str(e)}"
        )

    # --------------------------------------------------
    # 4️⃣ Guardar en configuracion_agencia (UPSERT)
    # --------------------------------------------------
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO configuracion_agencia (clave, valor)
                    VALUES ('logo_url', %s)
                    ON CONFLICT (clave)
                    DO UPDATE SET
                        valor = EXCLUDED.valor,
                        actualizado_en = now()
                """, (logo_url,))
                conn.commit()

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error guardando logo en BD: {str(e)}"
        )

    # --------------------------------------------------
    # 5️⃣ Borrar temporal
    # --------------------------------------------------
    try:
        os.remove(ruta_logo)
    except:
        pass

    return {
        "status": "ok",
        "logo_url": logo_url
    }


def obtener_config_formulario():

    nombre = current_business_name.get()

    config = {
        "logo_url": None,
        "color_primario": None,
        "color_secundario": None
    }

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT clave, valor
                FROM configuracion_agencia
                WHERE clave IN ('logo_url', 'color_primario', 'color_secundario')
            """)
            rows = cur.fetchall()

            for clave, valor in rows:
                config[clave] = valor

    return {
        "nombre_agencia": nombre,
        **config
    }

@router.get("/api/encuesta-aspirante-public-config")
def obtener_config_publica_formulario():

    nombre = current_business_name.get()

    config = {
        "titulo_encuesta_aspirante": None,
        "mensaje_inicio_encuesta": None,
        "logo_url": None,
        "color_primario": None,
        "color_secundario": None
    }

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT clave, valor
                FROM configuracion_agencia
                WHERE clave IN (
                    'titulo_encuesta_aspirante',
                    'mensaje_inicio_encuesta_form',
                    'logo_url',
                    'color_primario',
                    'color_secundario'
                )
            """)
            rows = cur.fetchall()

            for clave, valor in rows:
                config[clave] = valor

    return {
        "nombre": nombre,
        "logo": config["logo_url"],
        "color_primario": config["color_primario"],
        "color_secundario": config["color_secundario"],
        "titulo_encuesta_aspirante": config["titulo_encuesta_aspirante"],
        "mensaje_inicio_encuesta": config.get("mensaje_inicio_encuesta_form")
    }

# -----------------------------------------------------
# -----------------------------------------------------
# -----------------------------------------------------
# -----------------------------------------------------
# -----------------------------------------------------

# Endpoints deshabilitados (cleanup frontend)
# - GET /api/configuracion-agencia/keys
# - GET /api/configuracion-agencia/full
# - GET /api/configuracion-agencia
# - GET /api/form-config


