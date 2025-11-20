
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from pydantic import BaseModel

from auth import obtener_usuario_actual
from enviar_msg_wp import enviar_plantilla_generica_parametros

from main_mensajeria_whatsapp import  enviar_mensaje
from tenant import current_tenant

router = APIRouter()   # ← ESTE ES EL ROUTER QUE VAS A IMPORTAR EN main.py


from DataBase import get_connection_context, obtener_cuenta_por_subdominio


class ActualizarPreEvaluacionIn(BaseModel):
    estado_evaluacion: Optional[str] = None  # "No apto" | "Entrevista" | "Invitar a TikTok"
    usuario_evalua: Optional[str] = None
    observaciones_finales: Optional[str] = None


ESTADO_MAP_PREEVAL = {
    "No apto": 7,
    "Entrevista": 4,
    "Invitar a TikTok": 5,
}
ESTADO_DEFAULT = 99  # si no coincide

def actualizar_preevaluacion_perfil(creador_id: int, payload: dict):
    with get_connection_context() as conn:
        cur = conn.cursor()

        sets = []
        valores = []

        for campo, valor in payload.items():
            if valor is not None:
                sets.append(f"{campo} = %s")
                valores.append(valor)

        if not sets:
            return

        valores.append(creador_id)

        query = f"""
            UPDATE perfil_creador
            SET {', '.join(sets)}, actualizado_en = NOW()
            WHERE creador_id = %s
        """

        cur.execute(query, valores)


def actualizar_estado_creador_preevaluacion(creador_id: int, estado: str):
    estado_id = ESTADO_MAP_PREEVAL.get(estado, ESTADO_DEFAULT)

    with get_connection_context() as conn:
        cur = conn.cursor()

        cur.execute("""
            UPDATE creadores
            SET estado_id = %s
            WHERE id = %s
        """, (estado_id, creador_id))


@router.put("/api/perfil_creador/{creador_id}/preevaluacion")
def actualizar_preevaluacion(
    creador_id: int,
    datos: ActualizarPreEvaluacionIn,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    try:
        print("➡️ Payload recibido:", datos.dict())

        payload = {
            "estado_evaluacion": datos.estado_evaluacion,
            "usuario_evalua": datos.usuario_evalua,
            "observaciones_finales": datos.observaciones_finales,
        }

        print("➡️ Actualizando perfil_creador con:", payload)
        actualizar_preevaluacion_perfil(creador_id, payload)

        if datos.estado_evaluacion:
            print("➡️ Actualizando tabla creadores.estado_id con:", datos.estado_evaluacion)
            actualizar_estado_creador_preevaluacion(creador_id, datos.estado_evaluacion)

        print("✔️ Pre-evaluación actualizada correctamente")

        return {
            "status": "ok",
            "mensaje": "Pre-evaluación actualizada correctamente",
            "creador_id": creador_id,
            "estado_evaluacion": datos.estado_evaluacion,
        }

    except Exception as e:
        print("❌ ERROR en actualizar_preevaluacion:", str(e))
        raise HTTPException(status_code=500, detail=str(e))



from pydantic import BaseModel, AnyUrl
from typing import Optional, List
from datetime import datetime, timedelta
import secrets
import string
import pytz


class CrearLinkAgendamientoIn(BaseModel):
    creador_id: int
    responsable_id: int
    minutos_validez: int = 1440  # 24 horas por defecto

class LinkAgendamientoOut(BaseModel):
    token: str
    url: AnyUrl
    expiracion: datetime


class TokenInfoOut(BaseModel):
    creador_id: int
    responsable_id: int
    zona_horaria: Optional[str] = None
    nombre_mostrable: Optional[str] = None

def generar_token_corto(longitud=10):
    caracteres = string.ascii_letters + string.digits  # A-Z a-z 0-9
    return ''.join(secrets.choice(caracteres) for _ in range(longitud))

@router.post("/api/agendamientos/aspirante/enviar", response_model=LinkAgendamientoOut)
def crear_y_enviar_link_agendamiento_aspirante(
    data: CrearLinkAgendamientoIn,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    """
    Genera un link de agendamiento y lo envía por WhatsApp al aspirante.
    El número de teléfono se obtiene automáticamente desde `creadores`.
    """

    # 1) Token corto
    token = generar_token_corto(10)
    expiracion = datetime.utcnow() + timedelta(minutes=data.minutos_validez)

    with get_connection_context() as conn:
        cur = conn.cursor()

        # 2) Obtener teléfono y nombre del aspirante
        cur.execute(
            """
            SELECT nombre_real, telefono
            FROM creadores
            WHERE id = %s
            """,
            (data.creador_id,)
        )
        row = cur.fetchone()

        if not row:
            raise HTTPException(404, "El aspirante no existe.")

        nombre_creador, telefono = row

        if not telefono:
            raise HTTPException(400, "El aspirante no tiene teléfono registrado.")

        # 3) Guardar token
        cur.execute(
            """
            INSERT INTO link_agendamiento_tokens (
                token, creador_id, responsable_id, expiracion, usado
            )
            VALUES (%s, %s, %s, %s, FALSE)
            """,
            (token, data.creador_id, data.responsable_id, expiracion)
        )

    # 4) Armar URL dinámica con tenant
    subdomain = current_tenant.get() or "test"
    if subdomain == "public":
        subdomain = "test"

    base_front = f"https://{subdomain}.talentum-manager.com/agendar"
    url = f"{base_front}?token={token}"

    # 5) Armar mensaje
    mensaje = (
        f"Hola {nombre_creador} 👋\n\n"
        "Queremos continuar tu proceso en la agencia.\n\n"
        "📅 Agenda tu entrevista aquí:\n"
        f"{url}\n\n"
        "Selecciona el horario que prefieras.\n"
        # "✨ Prestige Agency"
    )

    # 6) Enviar WhatsApp
    try:
        enviar_mensaje(telefono, mensaje)
    except Exception as e:
        raise HTTPException(500, f"Token generado, pero fallo al enviar WhatsApp: {e}")

    # 7) Respuesta
    return LinkAgendamientoOut(
        token=token,
        url=url,
        expiracion=expiracion,
    )

class EnviarNoAptoIn(BaseModel):
    creador_id: int


@router.post("/api/aspirantes/no_apto/enviar")
def enviar_mensaje_no_apto(
        data: EnviarNoAptoIn,
        usuario_actual: dict = Depends(obtener_usuario_actual)
):
    """
    Envía mensaje de NO APTO usando SIEMPRE la plantilla.
    Evita errores por ventana de 24h.
    """

    with get_connection_context() as conn:
        cur = conn.cursor()

        # 1) Obtener datos del aspirante
        cur.execute("""
            SELECT id, nombre_real, telefono
            FROM creadores
            WHERE id = %s
        """, (data.creador_id,))
        row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Aspirante no encontrado.")

        creador_id, nombre, telefono = row

        if not telefono:
            raise HTTPException(status_code=400, detail="El aspirante no tiene número registrado.")


    # =============================
    # 2) Preparar envío por plantilla
    # =============================
    subdominio = current_tenant.get()
    cuenta = obtener_cuenta_por_subdominio(subdominio)

    if not cuenta:
        raise HTTPException(
            status_code=500,
            detail=f"No hay credenciales WABA para el tenant '{subdominio}'."
        )

    token = cuenta["access_token"]
    phone_id = cuenta["phone_number_id"]
    business_name = (
        cuenta.get("business_name")
        or cuenta.get("nombre")
        or "nuestra agencia"
    )

    parametros = [
        nombre or "creador",
        business_name
    ]

    # =============================
    # 3) Enviar plantilla
    # =============================
    try:
        codigo, respuesta_api = enviar_plantilla_generica_parametros(
            token=token,
            phone_number_id=phone_id,
            numero_destino=telefono,
            nombre_plantilla="no_apto_proceso_v2",
            codigo_idioma="es_CO",
            parametros=parametros,  # [nombre, business_name]
            body_vars_count=2  # 👈 LOS 2 VAN AL BODY, SIN BOTÓN
        )

        return {
            "status": "ok" if codigo < 300 else "error",
            "tipo_envio": "plantilla",
            "codigo_meta": codigo,
            "respuesta_api": respuesta_api,
            "telefono": telefono
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error enviando plantilla: {str(e)}"
        )


# @router.post("/api/aspirantes/no_apto/enviar")
# def enviar_mensaje_no_apto(
#         data: EnviarNoAptoIn,
#         usuario_actual: dict = Depends(obtener_usuario_actual)
# ):
#     """
#     Envía mensaje de NO APTO.
#     1) Intenta mensaje simple.
#     2) Si falla por ventana 24h → envía plantilla no_apto_proceso_v2.
#     """
#
#     with get_connection_context() as conn:
#         cur = conn.cursor()
#
#         # 1) Obtener datos del aspirante
#         cur.execute("""
#             SELECT id, nombre_real, telefono
#             FROM creadores
#             WHERE id = %s
#         """, (data.creador_id,))
#
#         row = cur.fetchone()
#         if not row:
#             raise HTTPException(status_code=404, detail="Aspirante no encontrado.")
#
#         creador_id, nombre, telefono = row
#
#         if not telefono:
#             raise HTTPException(status_code=400, detail="El aspirante no tiene número registrado.")
#
#         # 2) Mensaje estándar (primer intento)
#         mensaje = (
#             f"Hola {nombre or ''} 👋\n\n"
#             "Después de revisar tu información inicial, "
#             "hemos determinado que por ahora *no cumples con los requisitos* "
#             "para continuar en el proceso de selección de creadores de TikTok LIVE.\n\n"
#             "Esto *no refleja tu talento* ni tu potencial. "
#             "Te invitamos a seguir creciendo y a aplicar nuevamente más adelante.\n\n"
#             "Gracias por tu tiempo 🙌"
#         )
#
#     # =============================
#     #   3) Intento 1: mensaje simple
#     # =============================
#     try:
#         resp = enviar_mensaje(telefono, mensaje)
#         return {
#             "status": "ok",
#             "tipo_envio": "mensaje_texto",
#             "mensaje": "Mensaje simple enviado correctamente",
#             "telefono": telefono
#         }
#
#     except Exception as e:
#         # Analizar error de ventana de 24h
#         err_str = str(e)
#
#         if "131047" not in err_str and "24 hours" not in err_str:
#             # Error REAL → no continuar
#             raise HTTPException(status_code=500, detail=f"Error enviando mensaje: {err_str}")
#
#         print("⚠️ Mensaje simple bloqueado por ventana de 24h. Intentando plantilla...")
#
#     # ===================================================
#     # 4) Intento 2: plantilla fallback no_apto_proceso_v2
#     # ===================================================
#     try:
#         subdominio = current_tenant.get()
#         cuenta = obtener_cuenta_por_subdominio(subdominio)
#
#         token = cuenta["access_token"]
#         phone_id = cuenta["phone_number_id"]
#         business_name = (
#             cuenta.get("business_name")
#             or cuenta.get("nombre")
#             or "nuestra agencia"
#         )
#
#         # Parámetros plantilla: {{1}} = nombre, {{2}} = agency
#         parametros = [
#             nombre or "creador",
#             business_name
#         ]
#
#         codigo, respuesta_api = enviar_plantilla_generica_parametros(
#             token=token,
#             phone_number_id=phone_id,
#             numero_destino=telefono,
#             nombre_plantilla="no_apto_proceso_v2",
#             codigo_idioma="es_CO",
#             parametros=parametros
#         )
#
#         return {
#             "status": "ok",
#             "tipo_envio": "plantilla",
#             "codigo_meta": codigo,
#             "respuesta_api": respuesta_api,
#             "telefono": telefono
#         }
#
#     except Exception as e:
#         raise HTTPException(
#             status_code=500,
#             detail=f"No se pudo enviar ni mensaje simple ni plantilla: {str(e)}"
#         )
#
#
