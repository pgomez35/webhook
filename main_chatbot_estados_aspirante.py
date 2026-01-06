# app/routes/main_chatbot_estados_aspirante.py
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, constr
import psycopg2

# ✅ Importa tu contexto de conexión (respeta tenant/search_path)
# Ajusta el import según tu proyecto

from DataBase import get_connection_context

router = APIRouter(prefix="/api/chatbot-estados", tags=["Chatbot Estados"])   # ← ESTE ES EL ROUTER QUE VAS A IMPORTAR EN main.py



# =========================
# Pydantic Models
# =========================

class EstadoAspiranteOut(BaseModel):
    id_chatbot_estado: int
    codigo: str
    descripcion: Optional[str] = None
    estado_activo: bool = True
    mensaje_frontend_simple: Optional[str] = None
    mensaje_chatbot_simple: Optional[str] = None
    nombre_template: Optional[str] = None


class EstadoAspiranteUpdateIn(BaseModel):
    """
    PATCH: solo actualiza lo que llegue (campos opcionales).
    """
    descripcion: Optional[str] = None
    estado_activo: Optional[bool] = None
    mensaje_frontend_simple: Optional[str] = None
    mensaje_chatbot_simple: Optional[str] = None
    nombre_template: Optional[str] = None


class EstadoAspiranteCreateIn(BaseModel):
    """
    Opcional: si luego quieres crear estados por API.
    """
    codigo: constr(min_length=2, max_length=100)
    descripcion: Optional[str] = None
    estado_activo: bool = True
    mensaje_frontend_simple: Optional[str] = None
    mensaje_chatbot_simple: Optional[str] = None
    nombre_template: Optional[str] = None


# =========================
# Helpers
# =========================

def _row_to_dict(cur, row) -> Dict[str, Any]:
    columns = [desc[0] for desc in cur.description]
    return dict(zip(columns, row))


def _get_estado_por_id(cur, estado_id: int) -> Optional[Dict[str, Any]]:
    cur.execute(
        """
        SELECT
            id_chatbot_estado, codigo, descripcion, estado_activo,
            mensaje_frontend_simple, mensaje_chatbot_simple, nombre_template
        FROM public.chatbot_estados_aspirante
        WHERE id_chatbot_estado = %s
        """,
        (estado_id,)
    )
    row = cur.fetchone()
    return _row_to_dict(cur, row) if row else None


def _get_estado_por_codigo(cur, codigo: str) -> Optional[Dict[str, Any]]:
    cur.execute(
        """
        SELECT
            id_chatbot_estado, codigo, descripcion, estado_activo,
            mensaje_frontend_simple, mensaje_chatbot_simple, nombre_template
        FROM public.chatbot_estados_aspirante
        WHERE codigo = %s
        """,
        (codigo,)
    )
    row = cur.fetchone()
    return _row_to_dict(cur, row) if row else None


# =========================
# Endpoints
# =========================

@router.get("/", response_model=List[EstadoAspiranteOut])
def listar_estados(activos: Optional[bool] = None):
    """
    Lista estados. Si 'activos' viene, filtra por estado_activo.
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                if activos is None:
                    cur.execute(
                        """
                        SELECT
                            id_chatbot_estado, codigo, descripcion, estado_activo,
                            mensaje_frontend_simple, mensaje_chatbot_simple, nombre_template
                        FROM public.chatbot_estados_aspirante
                        ORDER BY id_chatbot_estado ASC
                        """
                    )
                else:
                    cur.execute(
                        """
                        SELECT
                            id_chatbot_estado, codigo, descripcion, estado_activo,
                            mensaje_frontend_simple, mensaje_chatbot_simple, nombre_template
                        FROM public.chatbot_estados_aspirante
                        WHERE estado_activo = %s
                        ORDER BY id_chatbot_estado ASC
                        """,
                        (activos,)
                    )
                rows = cur.fetchall()
                return [_row_to_dict(cur, r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al listar estados: {e}")


@router.get("/{estado_id}", response_model=EstadoAspiranteOut)
def obtener_estado_por_id(estado_id: int):
    """
    Obtiene un estado por ID.
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                estado = _get_estado_por_id(cur, estado_id)
                if not estado:
                    raise HTTPException(status_code=404, detail="Estado no encontrado")
                return estado
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener estado: {e}")


@router.get("/by-codigo/{codigo}", response_model=EstadoAspiranteOut)
def obtener_estado_por_codigo(codigo: str):
    """
    Obtiene un estado por código (más útil para UI/admin).
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                estado = _get_estado_por_codigo(cur, codigo)
                if not estado:
                    raise HTTPException(status_code=404, detail="Estado no encontrado")
                return estado
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener estado: {e}")


@router.patch("/{estado_id}", response_model=EstadoAspiranteOut)
def editar_estado_por_id(estado_id: int, payload: EstadoAspiranteUpdateIn):
    """
    Edita los datos de un estado por ID.
    - Solo actualiza los campos enviados (PATCH).
    """
    data = payload.model_dump(exclude_unset=True)

    if not data:
        raise HTTPException(status_code=400, detail="No se enviaron campos para actualizar")

    # ✅ Construcción dinámica del UPDATE (seguro con parámetros)
    allowed_fields = {
        "descripcion",
        "estado_activo",
        "mensaje_frontend_simple",
        "mensaje_chatbot_simple",
        "nombre_template",
    }
    updates = []
    values = []

    for k, v in data.items():
        if k not in allowed_fields:
            continue
        updates.append(f"{k} = %s")
        values.append(v)

    if not updates:
        raise HTTPException(status_code=400, detail="Campos inválidos para actualizar")

    values.append(estado_id)

    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # Validar existencia
                estado = _get_estado_por_id(cur, estado_id)
                if not estado:
                    raise HTTPException(status_code=404, detail="Estado no encontrado")

                cur.execute(
                    f"""
                    UPDATE public.chatbot_estados_aspirante
                    SET {", ".join(updates)}
                    WHERE id_chatbot_estado = %s
                    RETURNING
                        id_chatbot_estado, codigo, descripcion, estado_activo,
                        mensaje_frontend_simple, mensaje_chatbot_simple, nombre_template
                    """,
                    tuple(values)
                )
                updated = cur.fetchone()
                conn.commit()

                return _row_to_dict(cur, updated)

    except HTTPException:
        raise
    except psycopg2.Error as e:
        raise HTTPException(status_code=400, detail=f"Error de BD al actualizar estado: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al actualizar estado: {e}")


@router.patch("/by-codigo/{codigo}", response_model=EstadoAspiranteOut)
def editar_estado_por_codigo(codigo: str, payload: EstadoAspiranteUpdateIn):
    """
    Edita los datos de un estado por CÓDIGO (más cómodo que por ID).
    """
    data = payload.model_dump(exclude_unset=True)

    if not data:
        raise HTTPException(status_code=400, detail="No se enviaron campos para actualizar")

    allowed_fields = {
        "descripcion",
        "estado_activo",
        "mensaje_frontend_simple",
        "mensaje_chatbot_simple",
        "nombre_template",
    }
    updates = []
    values = []

    for k, v in data.items():
        if k not in allowed_fields:
            continue
        updates.append(f"{k} = %s")
        values.append(v)

    if not updates:
        raise HTTPException(status_code=400, detail="Campos inválidos para actualizar")

    values.append(codigo)

    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                # Validar existencia
                estado = _get_estado_por_codigo(cur, codigo)
                if not estado:
                    raise HTTPException(status_code=404, detail="Estado no encontrado")

                cur.execute(
                    f"""
                    UPDATE public.chatbot_estados_aspirante
                    SET {", ".join(updates)}
                    WHERE codigo = %s
                    RETURNING
                        id_chatbot_estado, codigo, descripcion, estado_activo,
                        mensaje_frontend_simple, mensaje_chatbot_simple, nombre_template
                    """,
                    tuple(values)
                )
                updated = cur.fetchone()
                conn.commit()

                return _row_to_dict(cur, updated)

    except HTTPException:
        raise
    except psycopg2.Error as e:
        raise HTTPException(status_code=400, detail=f"Error de BD al actualizar estado: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al actualizar estado: {e}")


# (Opcional) Endpoint para crear estados por API
@router.post("/", response_model=EstadoAspiranteOut)
def crear_estado(payload: EstadoAspiranteCreateIn):
    data = payload.model_dump()
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.chatbot_estados_aspirante
                    (codigo, descripcion, estado_activo, mensaje_frontend_simple, mensaje_chatbot_simple, nombre_template)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING
                        id_chatbot_estado, codigo, descripcion, estado_activo,
                        mensaje_frontend_simple, mensaje_chatbot_simple, nombre_template
                    """,
                    (
                        data["codigo"],
                        data.get("descripcion"),
                        data.get("estado_activo", True),
                        data.get("mensaje_frontend_simple"),
                        data.get("mensaje_chatbot_simple"),
                        data.get("nombre_template"),
                    )
                )
                row = cur.fetchone()
                conn.commit()
                return _row_to_dict(cur, row)
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="Ya existe un estado con ese codigo")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al crear estado: {e}")
