from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import re

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
                FROM configuracion_agencia_keys
                ORDER BY grupo ASC
            """)
            rows = cur.fetchall()

    return [r[0] for r in rows]


@router.get("/api/configuracion-agencia/keys", response_model=List[ConfigKeyOut])
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
                FROM configuracion_agencia_keys
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


@router.get("/api/configuracion-agencia/full", response_model=List[ConfigItemFullOut])
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


@router.get("/api/configuracion-agencia", response_model=List[ConfigItemOut])
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
