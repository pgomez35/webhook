import traceback

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional

from DataBase import get_connection_context


router = APIRouter()   # ← ESTE ES EL ROUTER QUE VAS A IMPORTAR EN main.py


router_agendamientos_aspirante = APIRouter()

class AgendamientoAspiranteIn(BaseModel):
    titulo: str
    descripcion: Optional[str] = None  # nota libre del aspirante
    inicio: datetime                    # ISO string desde React
    fin: datetime
    aspirante_nombre: str
    aspirante_email: EmailStr
    timezone: Optional[str] = None
    responsable_id: Optional[int] = None  # id del coach / responsable


class AgendamientoAspiranteOut(BaseModel):
    id: int
    titulo: str
    descripcion: Optional[str]
    inicio: datetime
    fin: datetime
    aspirante_nombre: str
    aspirante_email: EmailStr
    link_meet: Optional[str] = None
    origen: str = "aspirante_interno"


@router.post("/api/agendamientos/aspirante", response_model=AgendamientoAspiranteOut)
def crear_agendamiento_aspirante(evento: AgendamientoAspiranteIn):
    """Crea un agendamiento desde el móvil para un aspirante."""
    try:
        # Validación de fechas antes de abrir conexión
        if evento.fin <= evento.inicio:
            raise HTTPException(
                status_code=400,
                detail="La fecha de fin debe ser posterior a la fecha de inicio."
            )

        # Construir descripción con datos del aspirante
        desc_base = evento.descripcion or ""
        extra = (
            f"\n\n---\n"
            f"Aspirante: {evento.aspirante_nombre}\n"
            f"Email: {evento.aspirante_email}\n"
            f"Timezone: {evento.timezone or 'no especificada'}\n"
        )
        descripcion_final = (desc_base + extra).strip()

        # Usar context manager para manejo automático de conexión
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agendamientos (
                        titulo, descripcion, fecha_inicio, fecha_fin,
                        creador_id, responsable_id, estado, link_meet, google_event_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'programado', %s, %s)
                    RETURNING id, titulo, descripcion, fecha_inicio, fecha_fin, link_meet;
                    """,
                    (
                        evento.titulo,
                        descripcion_final,
                        evento.inicio,
                        evento.fin,
                        None,                      # creador_id: aún no es creador
                        evento.responsable_id,     # coach/manager dueño del link
                        None,                      # link_meet
                        None,                      # google_event_id
                    ),
                )

                row = cur.fetchone()

        # El context manager maneja automáticamente commit, rollback y close
        return AgendamientoAspiranteOut(
            id=row[0],
            titulo=row[1],
            descripcion=row[2],
            inicio=row[3],
            fin=row[4],
            aspirante_nombre=evento.aspirante_nombre,
            aspirante_email=evento.aspirante_email,
            link_meet=row[5],
        )

    except HTTPException:
        # Re-raise HTTPException sin modificarla
        raise
    except Exception as e:
        print(f"❌ Error creando agendamiento aspirante: {e}")
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Error creando agendamiento de aspirante: {str(e)}"
        )
