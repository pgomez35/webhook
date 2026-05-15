import os
from datetime import date
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, constr
import logging
from typing import Optional, List, Literal, Dict, Any

from DataBase import get_connection_context
from tenant import current_tenant
from portal_access_tokens import revocar_tokens_portal_por_aspirante_id
from utils_aspirantes import (
    enviar_portal_bienvenida_incorporacion,
    registrar_cambio_estado_con_cursor,
    crear_o_actualizar_creador_desde_aspirante,
)

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


# =========================================================
# CONSTANTES
# =========================================================

ESTADO_CREADOR_NUEVO = 1
ESTADO_CREADOR_PRESELECCION = 2
ESTADO_CREADOR_EVALUACION = 3
ESTADO_CREADOR_ENTREVISTA = 4
ESTADO_CREADOR_INVITACION = 5
ESTADO_CREADOR_INCORPORADO = 6
ESTADO_CREADOR_RECHAZADO = 7

ESTADO_INVITACION_PENDIENTE_ENVIO = "pendiente_envio"
ESTADO_INVITACION_ENVIADA = "enviada"
ESTADO_INVITACION_EN_ESPERA = "en_espera"
ESTADO_INVITACION_ACEPTADA = "aceptada"
ESTADO_INVITACION_RECHAZADA = "rechazada"

ESTADO_TIKTOK_PENDIENTE = "pendiente"
ESTADO_TIKTOK_ENVIADO = "enviado"
ESTADO_TIKTOK_APROBADO = "aprobado"
ESTADO_TIKTOK_RECHAZADO = "rechazado"

ROL_MANAGER = "Manager"

ESTADOS_INVITACION_VALIDOS = {
    ESTADO_INVITACION_PENDIENTE_ENVIO,
    ESTADO_INVITACION_ENVIADA,
    ESTADO_INVITACION_EN_ESPERA,
    ESTADO_INVITACION_ACEPTADA,
    ESTADO_INVITACION_RECHAZADA,
}

ESTADOS_TIKTOK_VALIDOS = {
    ESTADO_TIKTOK_PENDIENTE,
    ESTADO_TIKTOK_ENVIADO,
    ESTADO_TIKTOK_APROBADO,
    ESTADO_TIKTOK_RECHAZADO,
}

# Link global por agencia
LINK_INVITACION_TIKTOK_DEFAULT = os.getenv(
    "LINK_INVITACION_TIKTOK_DEFAULT",
    "https://www.tiktok.com/t/ZMAqjPPCK/"
)

NOMBRE_AGENCIA_DEFAULT = os.getenv(
    "NOMBRE_AGENCIA_PORTAL",
    "Prestige Agency Live"
)


# =========================================================
# SCHEMAS
# =========================================================

class InvitacionCreate(BaseModel):
    aspirante_id: int
    usuario_invita: int
    fecha_invitacion: Optional[date] = None
    observaciones: Optional[constr(max_length=300)] = None


class InvitacionUpdate(BaseModel):
    fecha_invitacion: Optional[date] = None
    usuario_invita: Optional[int] = None
    manager_id: Optional[int] = None
    estado_invitacion: Optional[
        Literal[
            "pendiente_envio",
            "enviada",
            "en_espera",
            "aceptada",
            "rechazada",
        ]
    ] = None
    estado_tiktok: Optional[
        Literal[
            "pendiente",
            "enviado",
            "aprobado",
            "rechazado",
        ]
    ] = None
    fecha_respuesta_invitacion: Optional[date] = None
    fecha_respuesta_tiktok: Optional[date] = None
    fecha_incorporacion: Optional[date] = None
    mensaje_enviado: Optional[bool] = None
    solicitud_tiktok_enviada: Optional[bool] = None
    observaciones: Optional[constr(max_length=300)] = None


class InvitacionEstadosUpdate(BaseModel):
    estado_invitacion: Optional[
        Literal[
            "pendiente_envio",
            "enviada",
            "en_espera",
            "aceptada",
            "rechazada",
        ]
    ] = None
    estado_tiktok: Optional[
        Literal[
            "pendiente",
            "enviado",
            "aprobado",
            "rechazado",
        ]
    ] = None
    fecha_respuesta_invitacion: Optional[date] = None
    fecha_respuesta_tiktok: Optional[date] = None
    observaciones: Optional[constr(max_length=300)] = None


class InvitacionAsignacionUpdate(BaseModel):
    manager_id: int
    fecha_incorporacion: date
    observaciones: Optional[constr(max_length=300)] = None


class InvitacionDecisionFinalUpdate(BaseModel):
    observaciones: Optional[constr(max_length=300)] = None


class InvitacionPortalOut(BaseModel):
    existe: bool = False
    aspirante_id: Optional[int] = None
    invitacion_id: Optional[int] = None
    estado_invitacion: Optional[str] = None
    estado_tiktok: Optional[str] = None
    estado_invitacion_label: Optional[str] = None
    estado_tiktok_label: Optional[str] = None
    fecha_invitacion: Optional[date] = None
    fecha_respuesta_invitacion: Optional[date] = None
    fecha_respuesta_tiktok: Optional[date] = None
    fecha_incorporacion: Optional[date] = None
    manager_id: Optional[int] = None
    manager_nombre: Optional[str] = None
    mensaje_enviado: Optional[bool] = None
    solicitud_tiktok_enviada: Optional[bool] = None
    observaciones: Optional[str] = None
    puede_incorporarse: bool = False
    link_invitacion: Optional[str] = None
    ruta_tiktok: Optional[str] = None
    agencia_nombre: Optional[str] = None
    titulo: Optional[str] = None
    mensaje_portal: Optional[str] = None
    mostrar_boton_abrir_tiktok: bool = False


# =========================================================
# HELPERS BÁSICOS
# =========================================================

def row_to_dict(cur, row) -> Dict[str, Any]:
    columns = [desc[0] for desc in cur.description]
    return dict(zip(columns, row))


def validar_estado_invitacion(estado: str) -> None:
    if estado not in ESTADOS_INVITACION_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=f"Estado de invitación no válido: {estado}"
        )


def validar_estado_tiktok(estado: str) -> None:
    if estado not in ESTADOS_TIKTOK_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=f"Estado TikTok no válido: {estado}"
        )


def validar_creador_existe(cur, aspirante_id: int) -> Dict[str, Any]:
    cur.execute("""
        SELECT
            id,
            usuario,
            nickname,
            nombre_real,
            email,
            telefono,
            whatsapp,
            foto_url,
            estado_id,
            verificado,
            fecha_verificacion,
            activo,
            creado_en,
            actualizado_en,
            foto_url_mini,
            rol_id,
            fecha_solicitud,
            encuesta_terminada
        FROM aspirantes
        WHERE id = %s
        LIMIT 1
    """, (aspirante_id,))
    row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Creador no encontrado")

    creador = row_to_dict(cur, row)

    if creador["activo"] is False:
        raise HTTPException(status_code=400, detail="El creador está inactivo")

    return creador


def validar_usuario_existe(cur, usuario_id: int) -> Dict[str, Any]:
    cur.execute("""
        SELECT
            a.id,
            a.username,
            a.password_hash,
            ur.nombre AS rol,
            a.nombre_completo,
            a.email,
            a.telefono,
            a.grupo,
            a.activo,
            a.creado_en,
            a.actualizado_en
        FROM administradores a
        LEFT JOIN administradores_roles ur ON ur.id = a.administradores_roles_id
        WHERE a.id = %s
        LIMIT 1
    """, (usuario_id,))
    row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    usuario = row_to_dict(cur, row)

    if usuario["activo"] is False:
        raise HTTPException(status_code=400, detail="El usuario está inactivo")

    return usuario


def validar_manager_existe(cur, manager_id: int) -> Dict[str, Any]:
    cur.execute("""
        SELECT
            a.id,
            a.username,
            a.password_hash,
            ur.nombre AS rol,
            a.nombre_completo,
            a.email,
            a.telefono,
            a.grupo,
            a.activo,
            a.creado_en,
            a.actualizado_en
        FROM administradores a
        INNER JOIN administradores_roles ur ON ur.id = a.administradores_roles_id
        WHERE a.id = %s
          AND ur.nombre = %s
          AND a.activo = true
        LIMIT 1
    """, (manager_id, ROL_MANAGER))
    row = cur.fetchone()

    if not row:
        raise HTTPException(
            status_code=400,
            detail="El manager seleccionado no existe, no está activo o no tiene rol Manager"
        )

    return row_to_dict(cur, row)


def puede_incorporarse(invitacion: Dict[str, Any]) -> bool:
    return (
        invitacion["estado_invitacion"] == ESTADO_INVITACION_ACEPTADA
        and invitacion["estado_tiktok"] == ESTADO_TIKTOK_APROBADO
        and invitacion.get("manager_id") is not None
        and invitacion.get("fecha_incorporacion") is not None
    )


def ejecutar_incorporacion_invitacion(
    cur,
    invitacion: Dict[str, Any],
    invitacion_id: int,
    manager_id: int,
    fecha_incorporacion: date,
    *,
    estado_aspirante_id_anterior: Optional[int] = None,
    usuario_id: Optional[int] = None,
    origen_cambio: str = "asignar_manager",
) -> Dict[str, Any]:
    """
    Incorporación completa (solo si puede_incorporarse):
    estado aspirante → Incorporado, creadores, token portal, marca envío WhatsApp.
    El mensaje se envía después del commit (ver procesar_bienvenida_incorporacion).
    """
    if not puede_incorporarse(invitacion):
        raise HTTPException(
            status_code=400,
            detail=(
                "No se puede incorporar: la invitación debe estar aceptada, "
                "TikTok aprobado, y tener manager y fecha de incorporación."
            ),
        )

    ya_estaba_incorporado = estado_aspirante_id_anterior == ESTADO_CREADOR_INCORPORADO

    if not ya_estaba_incorporado:
        registrar_cambio_estado_con_cursor(
            cur=cur,
            aspirante_id=invitacion["aspirante_id"],
            nuevo_estado_id=ESTADO_CREADOR_INCORPORADO,
            usuario_id=usuario_id,
            origen_cambio=origen_cambio,
            observacion=(
                "Aspirante pasa a Incorporado tras asignación de manager "
                "y fecha de incorporación"
            ),
        )

    creador_id = crear_o_actualizar_creador_desde_aspirante(
        cur=cur,
        aspirante_id=invitacion["aspirante_id"],
        manager_id=manager_id,
        fecha_incorporacion=fecha_incorporacion,
    )

    debe_enviar_whatsapp = reclamar_envio_mensaje_incorporacion(cur, invitacion_id)
    telefono = obtener_numero_invitacion(invitacion) if debe_enviar_whatsapp else None

    return {
        "creador_id": creador_id,
        "debe_enviar_whatsapp": debe_enviar_whatsapp,
        "telefono": telefono,
    }


def procesar_bienvenida_incorporacion(
    invitacion_id: int,
    telefono: Optional[str],
    debe_enviar: bool,
) -> bool:
    """Envía WhatsApp de bienvenida tras commit; resetea flag si falla."""
    if not debe_enviar:
        return False

    enviado = enviar_mensaje_incorporacion_si_aplica(
        invitacion_id=invitacion_id,
        telefono=telefono,
    )
    if not enviado:
        resetear_envio_mensaje_incorporacion(invitacion_id)
    return enviado


def actualizar_estado_creador_según_invitacion(
    cur,
    aspirante_id: int,
    invitacion: Dict[str, Any]
) -> int:
    nuevo_estado = ESTADO_CREADOR_INVITACION

    if (
        invitacion["estado_invitacion"] == ESTADO_INVITACION_RECHAZADA
        or invitacion["estado_tiktok"] == ESTADO_TIKTOK_RECHAZADO
    ):
        nuevo_estado = ESTADO_CREADOR_RECHAZADO
    elif puede_incorporarse(invitacion):
        nuevo_estado = ESTADO_CREADOR_INCORPORADO

    cur.execute(
        "SELECT estado_id FROM aspirantes WHERE id = %s LIMIT 1",
        (aspirante_id,),
    )
    estado_anterior_row = cur.fetchone()
    estado_anterior = estado_anterior_row[0] if estado_anterior_row else None

    cur.execute("""
        UPDATE aspirantes
        SET
            estado_id = %s,
            actualizado_en = now()
        WHERE id = %s
    """, (nuevo_estado, aspirante_id))

    if (
        nuevo_estado == ESTADO_CREADOR_RECHAZADO
        and estado_anterior != ESTADO_CREADOR_RECHAZADO
    ):
        revocar_tokens_portal_por_aspirante_id(cur, aspirante_id)

    return nuevo_estado


def obtener_invitacion_por_id(cur, invitacion_id: int) -> Dict[str, Any]:
    cur.execute("""
        SELECT
            i.id,
            i.aspirante_id,
            i.fecha_invitacion,
            i.usuario_invita,
            i.manager_id,
            i.estado_invitacion,
            i.estado_tiktok,
            i.fecha_respuesta_invitacion,
            i.fecha_respuesta_tiktok,
            i.fecha_incorporacion,
            i.mensaje_enviado,
            i.solicitud_tiktok_enviada,
            i.observaciones,
            i.creado_en,
            i.actualizado_en,

            c.usuario AS creador_usuario,
            c.nickname AS creador_nickname,
            c.nombre_real AS creador_nombre_real,
            c.email AS creador_email,
            c.telefono AS creador_telefono,
            c.whatsapp AS creador_whatsapp,
            c.foto_url AS creador_foto_url,
            c.estado_id AS estado_aspirante_id,
            c.verificado AS creador_verificado,
            c.fecha_verificacion AS creador_fecha_verificacion,
            c.activo AS creador_activo,
            c.creado_en AS creador_creado_en,
            c.actualizado_en AS creador_actualizado_en,
            c.foto_url_mini AS creador_foto_url_mini,
            c.rol_id AS creador_rol_id,
            c.fecha_solicitud AS creador_fecha_solicitud,
            c.encuesta_terminada AS creador_encuesta_terminada,

            ui.username AS username_usuario_invita,
            uir.nombre AS rol_usuario_invita,
            ui.nombre_completo AS nombre_usuario_invita,
            ui.email AS email_usuario_invita,
            ui.telefono AS telefono_usuario_invita,
            ui.grupo AS grupo_usuario_invita,
            ui.activo AS activo_usuario_invita,
            ui.creado_en AS creado_en_usuario_invita,
            ui.actualizado_en AS actualizado_en_usuario_invita,

            um.username AS username_manager,
            umr.nombre AS rol_manager,
            um.nombre_completo AS nombre_manager,
            um.email AS email_manager,
            um.telefono AS telefono_manager,
            um.grupo AS grupo_manager,
            um.activo AS activo_manager,
            um.creado_en AS creado_en_manager,
            um.actualizado_en AS actualizado_en_manager
        FROM invitaciones i
        JOIN aspirantes c
            ON c.id = i.aspirante_id
        LEFT JOIN administradores ui
            ON ui.id = i.usuario_invita
        LEFT JOIN administradores_roles uir ON uir.id = ui.administradores_roles_id
        LEFT JOIN administradores um
            ON um.id = i.manager_id
        LEFT JOIN administradores_roles umr ON umr.id = um.administradores_roles_id
        WHERE i.id = %s
        LIMIT 1
    """, (invitacion_id,))
    row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Invitación no encontrada")

    return row_to_dict(cur, row)


def obtener_ultima_invitacion_por_creador(cur, aspirante_id: int) -> Optional[Dict[str, Any]]:
    cur.execute("""
        SELECT
            i.id,
            i.aspirante_id,
            i.fecha_invitacion,
            i.usuario_invita,
            i.manager_id,
            i.estado_invitacion,
            i.estado_tiktok,
            i.fecha_respuesta_invitacion,
            i.fecha_respuesta_tiktok,
            i.fecha_incorporacion,
            i.mensaje_enviado,
            i.solicitud_tiktok_enviada,
            i.observaciones,
            i.creado_en,
            i.actualizado_en,

            c.usuario AS creador_usuario,
            c.nickname AS creador_nickname,
            c.nombre_real AS creador_nombre_real,
            c.email AS creador_email,
            c.telefono AS creador_telefono,
            c.whatsapp AS creador_whatsapp,
            c.foto_url AS creador_foto_url,
            c.estado_id AS estado_aspirante_id,
            c.verificado AS creador_verificado,
            c.fecha_verificacion AS creador_fecha_verificacion,
            c.activo AS creador_activo,
            c.creado_en AS creador_creado_en,
            c.actualizado_en AS creador_actualizado_en,
            c.foto_url_mini AS creador_foto_url_mini,
            c.rol_id AS creador_rol_id,
            c.fecha_solicitud AS creador_fecha_solicitud,
            c.encuesta_terminada AS creador_encuesta_terminada,

            ui.username AS username_usuario_invita,
            uir.nombre AS rol_usuario_invita,
            ui.nombre_completo AS nombre_usuario_invita,
            ui.email AS email_usuario_invita,
            ui.telefono AS telefono_usuario_invita,
            ui.grupo AS grupo_usuario_invita,
            ui.activo AS activo_usuario_invita,
            ui.creado_en AS creado_en_usuario_invita,
            ui.actualizado_en AS actualizado_en_usuario_invita,

            um.username AS username_manager,
            umr.nombre AS rol_manager,
            um.nombre_completo AS nombre_manager,
            um.email AS email_manager,
            um.telefono AS telefono_manager,
            um.grupo AS grupo_manager,
            um.activo AS activo_manager,
            um.creado_en AS creado_en_manager,
            um.actualizado_en AS actualizado_en_manager
        FROM invitaciones i
        JOIN aspirantes c
            ON c.id = i.aspirante_id
        LEFT JOIN administradores ui
            ON ui.id = i.usuario_invita
        LEFT JOIN administradores_roles uir ON uir.id = ui.administradores_roles_id
        LEFT JOIN administradores um
            ON um.id = i.manager_id
        LEFT JOIN administradores_roles umr ON umr.id = um.administradores_roles_id
        WHERE i.aspirante_id = %s
        ORDER BY i.id DESC
        LIMIT 1
    """, (aspirante_id,))
    row = cur.fetchone()

    if not row:
        return None

    return row_to_dict(cur, row)


def validar_puede_asignarse_manager(invitacion: Dict[str, Any]) -> None:
    if invitacion["estado_invitacion"] != ESTADO_INVITACION_ACEPTADA:
        raise HTTPException(
            status_code=400,
            detail="No se puede asignar manager si la invitación no está aceptada"
        )

    if invitacion["estado_tiktok"] != ESTADO_TIKTOK_APROBADO:
        raise HTTPException(
            status_code=400,
            detail="No se puede incorporar si TikTok no está aprobado"
        )


# =========================================================
# HELPERS NUEVOS PARA PORTAL
# =========================================================

def obtener_nombre_agencia_portal() -> str:
    tenant_name = None
    try:
        tenant_name = current_tenant.get()
    except Exception:
        tenant_name = None

    if tenant_name:
        return f"{tenant_name.capitalize()} Agency Live"

    return NOMBRE_AGENCIA_DEFAULT


def obtener_link_invitacion_tiktok_agencia() -> str:
    return LINK_INVITACION_TIKTOK_DEFAULT


def label_estado_invitacion(estado: Optional[str]) -> str:
    mapa = {
        ESTADO_INVITACION_PENDIENTE_ENVIO: "Pendiente de envío",
        ESTADO_INVITACION_ENVIADA: "Enviada",
        ESTADO_INVITACION_EN_ESPERA: "En espera",
        ESTADO_INVITACION_ACEPTADA: "Aceptada",
        ESTADO_INVITACION_RECHAZADA: "Rechazada",
    }
    return mapa.get(estado or "", "Sin información")


def label_estado_tiktok(estado: Optional[str]) -> str:
    mapa = {
        ESTADO_TIKTOK_PENDIENTE: "Pendiente",
        ESTADO_TIKTOK_ENVIADO: "Enviado",
        ESTADO_TIKTOK_APROBADO: "Aprobado",
        ESTADO_TIKTOK_RECHAZADO: "Rechazado",
    }
    return mapa.get(estado or "", "Sin información")


def construir_mensaje_invitacion_portal(
    estado_invitacion: Optional[str],
    estado_tiktok: Optional[str],
    agencia_nombre: str
) -> str:
    if estado_invitacion == ESTADO_INVITACION_RECHAZADA:
        return (
            f"Has decidido no continuar con la invitación para unirte a {agencia_nombre}. "
            "Tu proceso quedó finalizado por el momento. "
            "Si en el futuro deseas retomarlo o tienes alguna duda, puedes comunicarte nuevamente con la agencia."
        )

    if estado_tiktok == ESTADO_TIKTOK_RECHAZADO:
        return (
            "La validación de TikTok no pudo completarse en esta etapa del proceso. "
            "En algunos casos puede deberse a requisitos técnicos o configuraciones de la cuenta. "
            "La agencia podrá orientarte sobre cómo continuar."
        )

    if estado_invitacion == ESTADO_INVITACION_PENDIENTE_ENVIO:
        return (
            f"📨 {agencia_nombre} está preparando tu invitación oficial. "
            "Cuando esté lista, la agencia podrá enviártela por WhatsApp y también podrás consultarla desde este portal."
        )

    if estado_invitacion == ESTADO_INVITACION_EN_ESPERA and estado_tiktok == ESTADO_TIKTOK_PENDIENTE:
        return (
            f"{agencia_nombre} tiene una invitación pendiente de tu revisión. "
            "El siguiente paso es abrirla en TikTok y aceptarla para continuar con tu incorporación. "
            "Puedes abrirla con el botón \"Aceptar invitación en TikTok\" en esta pantalla."
        )

    if estado_invitacion == ESTADO_INVITACION_ENVIADA and estado_tiktok == ESTADO_TIKTOK_PENDIENTE:
        return (
            f"{agencia_nombre} ya envió tu invitación formal. "
            "Revisa la invitación en TikTok y acéptala para seguir con tu incorporación; "
            "usa el botón \"Aceptar invitación en TikTok\" que aparece abajo."
        )

    if estado_invitacion == ESTADO_INVITACION_EN_ESPERA and estado_tiktok == ESTADO_TIKTOK_ENVIADO:
        return (
            f"Tu invitación con {agencia_nombre} sigue activa: TikTok está revisando tu perfil. "
            "Si aún debes completar algún paso en la app de TikTok, vuelve a entrar con el botón "
            "\"Aceptar invitación en TikTok\"."
        )

    if estado_invitacion == ESTADO_INVITACION_ENVIADA and estado_tiktok == ESTADO_TIKTOK_ENVIADO:
        return (
            f"Tu invitación con {agencia_nombre} está activa y TikTok ya recibió la solicitud para validar tu perfil. "
            "Para volver a ver la invitación en TikTok, usa el botón \"Aceptar invitación en TikTok\"."
        )

    if estado_invitacion == ESTADO_INVITACION_ACEPTADA and estado_tiktok in {ESTADO_TIKTOK_PENDIENTE, ESTADO_TIKTOK_ENVIADO}:
        return (
            f"Ya aceptaste la invitación de {agencia_nombre}. "
            "Estamos a la espera de la validación final por parte de TikTok."
        )

    if estado_invitacion == ESTADO_INVITACION_ACEPTADA and estado_tiktok == ESTADO_TIKTOK_APROBADO:
        return (
            f"🎉 Tu incorporación con {agencia_nombre} fue aprobada exitosamente. "
            "Ya haces parte de la agencia como creador TikTok LIVE."
        )

    return (
        f"Tienes una invitación activa con {agencia_nombre}. "
        "Revisa el estado en este portal y sigue los pasos que indique TikTok para continuar."
    )


def transformar_invitacion_a_portal(invitacion: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    agencia_nombre = obtener_nombre_agencia_portal()
    link_invitacion = obtener_link_invitacion_tiktok_agencia()

    if not invitacion:
        return {
            "existe": False,
            "agencia_nombre": agencia_nombre,
            "link_invitacion": link_invitacion,
            "ruta_tiktok": "TikTok > Herramientas de creador > Centro LIVE > Centro para agencias",
            "titulo": f"Invitación a {agencia_nombre}",
            "mensaje_portal": (
                "Aún no hay una invitación activa registrada para tu proceso."
            ),
            "mostrar_boton_abrir_tiktok": False,
            "puede_incorporarse": False,
        }

    estado_invitacion = invitacion.get("estado_invitacion")
    estado_tiktok = invitacion.get("estado_tiktok")

    mostrar_boton_abrir_tiktok = estado_invitacion in {
        ESTADO_INVITACION_ENVIADA,
        ESTADO_INVITACION_EN_ESPERA,
        ESTADO_INVITACION_ACEPTADA,
    }

    return {
        "existe": True,
        "aspirante_id": invitacion.get("aspirante_id"),
        "invitacion_id": invitacion.get("id"),
        "estado_invitacion": estado_invitacion,
        "estado_tiktok": estado_tiktok,
        "estado_invitacion_label": label_estado_invitacion(estado_invitacion),
        "estado_tiktok_label": label_estado_tiktok(estado_tiktok),
        "fecha_invitacion": invitacion.get("fecha_invitacion"),
        "fecha_respuesta_invitacion": invitacion.get("fecha_respuesta_invitacion"),
        "fecha_respuesta_tiktok": invitacion.get("fecha_respuesta_tiktok"),
        "fecha_incorporacion": invitacion.get("fecha_incorporacion"),
        "manager_id": invitacion.get("manager_id"),
        "manager_nombre": invitacion.get("nombre_manager"),
        "mensaje_enviado": invitacion.get("mensaje_enviado"),
        "solicitud_tiktok_enviada": invitacion.get("solicitud_tiktok_enviada"),
        "observaciones": invitacion.get("observaciones"),
        "puede_incorporarse": puede_incorporarse(invitacion),
        "link_invitacion": link_invitacion,
        "ruta_tiktok": "TikTok > Herramientas de creador > Centro LIVE > Centro para agencias",
        "agencia_nombre": agencia_nombre,
        "titulo": f"Invitación a {agencia_nombre}",
        "mensaje_portal": construir_mensaje_invitacion_portal(
            estado_invitacion=estado_invitacion,
            estado_tiktok=estado_tiktok,
            agencia_nombre=agencia_nombre
        ),
        "mostrar_boton_abrir_tiktok": mostrar_boton_abrir_tiktok,
    }


def obtener_invitacion_portal_por_aspirante(cur, aspirante_id: int) -> Dict[str, Any]:
    invitacion = obtener_ultima_invitacion_por_creador(cur, aspirante_id)
    return transformar_invitacion_a_portal(invitacion)


# =========================================================
# ENDPOINT 1: LISTAR MANAGERS
# =========================================================

@router.get("/api/managers")
def listar_managers():
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    a.id,
                    a.username,
                    a.password_hash,
                    ur.nombre AS rol,
                    a.nombre_completo,
                    a.email,
                    a.telefono,
                    a.grupo,
                    a.activo,
                    a.creado_en,
                    a.actualizado_en
                FROM administradores a
                INNER JOIN administradores_roles ur ON ur.id = a.administradores_roles_id
                WHERE ur.nombre = %s
                  AND a.activo = true
                ORDER BY a.nombre_completo ASC, a.id ASC
            """, (ROL_MANAGER,))

            rows = cur.fetchall()
            items = [row_to_dict(cur, row) for row in rows]

            return {
                "success": True,
                "total": len(items),
                "data": items
            }


# =========================================================
# ENDPOINT 2: CREAR INVITACIÓN
# =========================================================

@router.post("/api/invitaciones")
def crear_invitacion(data: InvitacionCreate):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            validar_creador_existe(cur, data.aspirante_id)
            validar_usuario_existe(cur, data.usuario_invita)

            ultima = obtener_ultima_invitacion_por_creador(cur, data.aspirante_id)
            if ultima and ultima["estado_invitacion"] != ESTADO_INVITACION_RECHAZADA:
                raise HTTPException(
                    status_code=400,
                    detail="El creador ya tiene una invitación activa o en proceso"
                )

            cur.execute("""
                INSERT INTO invitaciones (
                    aspirante_id,
                    fecha_invitacion,
                    usuario_invita,
                    manager_id,
                    estado_invitacion,
                    estado_tiktok,
                    fecha_respuesta_invitacion,
                    fecha_respuesta_tiktok,
                    fecha_incorporacion,
                    mensaje_enviado,
                    solicitud_tiktok_enviada,
                    observaciones,
                    creado_en,
                    actualizado_en
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    now(), now()
                )
                RETURNING id
            """, (
                data.aspirante_id,
                data.fecha_invitacion,
                data.usuario_invita,
                None,
                ESTADO_INVITACION_PENDIENTE_ENVIO,
                ESTADO_TIKTOK_PENDIENTE,
                None,
                None,
                None,
                False,
                False,
                data.observaciones
            ))

            invitacion_id = cur.fetchone()[0]
            invitacion = obtener_invitacion_por_id(cur, invitacion_id)

            actualizar_estado_creador_según_invitacion(cur, data.aspirante_id, invitacion)
            conn.commit()

            invitacion = obtener_invitacion_por_id(cur, invitacion_id)

            return {
                "success": True,
                "message": "Invitación creada correctamente",
                "data": invitacion
            }


# =========================================================
# ENDPOINT 3: OBTENER ÚLTIMA INVITACIÓN POR CREADOR
# =========================================================

@router.get("/api/aspirantes/{aspirante_id}/invitacion")
def obtener_invitacion_actual_creador(aspirante_id: int):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            validar_creador_existe(cur, aspirante_id)
            invitacion = obtener_ultima_invitacion_por_creador(cur, aspirante_id)

            return {
                "success": True,
                "data": invitacion
            }


# =========================================================
# ENDPOINT 3B: OBTENER INVITACIÓN LIMPIA PARA PORTAL
# =========================================================

@router.get("/api/portal/aspirantes/{aspirante_id}/invitacion", response_model=InvitacionPortalOut)
def obtener_invitacion_portal(aspirante_id: int):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            validar_creador_existe(cur, aspirante_id)
            data = obtener_invitacion_portal_por_aspirante(cur, aspirante_id)
            return InvitacionPortalOut(**data)


# =========================================================
# ENDPOINT 4: OBTENER INVITACIÓN POR ID
# =========================================================

@router.get("/api/invitaciones/{invitacion_id}")
def obtener_invitacion(invitacion_id: int):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            invitacion = obtener_invitacion_por_id(cur, invitacion_id)

            return {
                "success": True,
                "data": invitacion
            }


# =========================================================
# ENDPOINT 5: LISTAR INVITACIONES
# =========================================================

@router.get("/api/invitaciones")
def listar_invitaciones(
    estado_invitacion: Optional[str] = None,
    estado_tiktok: Optional[str] = None,
    aspirante_id: Optional[int] = None
):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            filtros = []
            params: List[Any] = []

            if estado_invitacion:
                validar_estado_invitacion(estado_invitacion)
                filtros.append("i.estado_invitacion = %s")
                params.append(estado_invitacion)

            if estado_tiktok:
                validar_estado_tiktok(estado_tiktok)
                filtros.append("i.estado_tiktok = %s")
                params.append(estado_tiktok)

            if aspirante_id:
                filtros.append("i.aspirante_id = %s")
                params.append(aspirante_id)

            where_sql = ""
            if filtros:
                where_sql = "WHERE " + " AND ".join(filtros)

            cur.execute(f"""
                SELECT
                    i.id,
                    i.aspirante_id,
                    i.fecha_invitacion,
                    i.usuario_invita,
                    i.manager_id,
                    i.estado_invitacion,
                    i.estado_tiktok,
                    i.fecha_respuesta_invitacion,
                    i.fecha_respuesta_tiktok,
                    i.fecha_incorporacion,
                    i.mensaje_enviado,
                    i.solicitud_tiktok_enviada,
                    i.observaciones,
                    i.creado_en,
                    i.actualizado_en,

                    c.usuario AS creador_usuario,
                    c.nickname AS creador_nickname,
                    c.nombre_real AS creador_nombre_real,
                    c.email AS creador_email,
                    c.telefono AS creador_telefono,
                    c.whatsapp AS creador_whatsapp,
                    c.foto_url AS creador_foto_url,
                    c.estado_id AS estado_aspirante_id,
                    c.verificado AS creador_verificado,
                    c.fecha_verificacion AS creador_fecha_verificacion,
                    c.activo AS creador_activo,
                    c.creado_en AS creador_creado_en,
                    c.actualizado_en AS creador_actualizado_en,
                    c.foto_url_mini AS creador_foto_url_mini,
                    c.rol_id AS creador_rol_id,
                    c.fecha_solicitud AS creador_fecha_solicitud,
                    c.encuesta_terminada AS creador_encuesta_terminada,

                    ui.username AS username_usuario_invita,
                    uir.nombre AS rol_usuario_invita,
                    ui.nombre_completo AS nombre_usuario_invita,
                    ui.email AS email_usuario_invita,
                    ui.telefono AS telefono_usuario_invita,
                    ui.grupo AS grupo_usuario_invita,
                    ui.activo AS activo_usuario_invita,
                    ui.creado_en AS creado_en_usuario_invita,
                    ui.actualizado_en AS actualizado_en_usuario_invita,

                    um.username AS username_manager,
                    umr.nombre AS rol_manager,
                    um.nombre_completo AS nombre_manager,
                    um.email AS email_manager,
                    um.telefono AS telefono_manager,
                    um.grupo AS grupo_manager,
                    um.activo AS activo_manager,
                    um.creado_en AS creado_en_manager,
                    um.actualizado_en AS actualizado_en_manager
                FROM invitaciones i
                JOIN aspirantes c
                    ON c.id = i.aspirante_id
                LEFT JOIN administradores ui
                    ON ui.id = i.usuario_invita
                LEFT JOIN administradores_roles uir ON uir.id = ui.administradores_roles_id
                LEFT JOIN administradores um
                    ON um.id = i.manager_id
                LEFT JOIN administradores_roles umr ON umr.id = um.administradores_roles_id
                {where_sql}
                ORDER BY i.id DESC
            """, params)

            rows = cur.fetchall()
            items = [row_to_dict(cur, row) for row in rows]

            return {
                "success": True,
                "total": len(items),
                "data": items
            }


@router.put("/api/invitaciones/{invitacion_id}")
def actualizar_invitacion(invitacion_id: int, data: InvitacionUpdate):
    """
    Actualización general de la invitación (estados, fechas, observaciones).
    La incorporación (creadores, token portal, WhatsApp) es solo vía
    PATCH /api/invitaciones/{id}/asignar-manager.
    """
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            actual = obtener_invitacion_por_id(cur, invitacion_id)

            estado_invitacion = (
                data.estado_invitacion
                if data.estado_invitacion is not None
                else actual["estado_invitacion"]
            )

            estado_tiktok = (
                data.estado_tiktok
                if data.estado_tiktok is not None
                else actual["estado_tiktok"]
            )

            validar_estado_invitacion(estado_invitacion)
            validar_estado_tiktok(estado_tiktok)

            usuario_invita = (
                data.usuario_invita
                if data.usuario_invita is not None
                else actual["usuario_invita"]
            )

            if usuario_invita is not None:
                validar_usuario_existe(cur, usuario_invita)

            manager_id = (
                data.manager_id
                if data.manager_id is not None
                else actual["manager_id"]
            )

            if manager_id is not None:
                validar_manager_existe(cur, manager_id)

            fecha_incorporacion = (
                data.fecha_incorporacion
                if data.fecha_incorporacion is not None
                else actual["fecha_incorporacion"]
            )

            cur.execute("""
                UPDATE invitaciones
                SET
                    fecha_invitacion = %s,
                    usuario_invita = %s,
                    manager_id = %s,
                    estado_invitacion = %s,
                    estado_tiktok = %s,
                    fecha_respuesta_invitacion = %s,
                    fecha_respuesta_tiktok = %s,
                    fecha_incorporacion = %s,
                    mensaje_enviado = %s,
                    solicitud_tiktok_enviada = %s,
                    observaciones = %s,
                    actualizado_en = now()
                WHERE id = %s
            """, (
                data.fecha_invitacion
                if data.fecha_invitacion is not None
                else actual["fecha_invitacion"],

                usuario_invita,
                manager_id,
                estado_invitacion,
                estado_tiktok,

                data.fecha_respuesta_invitacion
                if data.fecha_respuesta_invitacion is not None
                else actual["fecha_respuesta_invitacion"],

                data.fecha_respuesta_tiktok
                if data.fecha_respuesta_tiktok is not None
                else actual["fecha_respuesta_tiktok"],

                fecha_incorporacion,

                data.mensaje_enviado
                if data.mensaje_enviado is not None
                else actual["mensaje_enviado"],

                data.solicitud_tiktok_enviada
                if data.solicitud_tiktok_enviada is not None
                else actual["solicitud_tiktok_enviada"],

                data.observaciones
                if data.observaciones is not None
                else actual["observaciones"],

                invitacion_id,
            ))

            invitacion = obtener_invitacion_por_id(cur, invitacion_id)
            actualizar_estado_creador_según_invitacion(
                cur, invitacion["aspirante_id"], invitacion
            )

            conn.commit()

            invitacion = obtener_invitacion_por_id(cur, invitacion_id)

    return {
        "success": True,
        "message": "Invitación actualizada correctamente",
        "data": invitacion,
    }


def obtener_numero_invitacion(invitacion: Dict[str, Any]) -> Optional[str]:
    return (
        invitacion.get("creador_whatsapp")
        or invitacion.get("creador_telefono")
    )


def reclamar_envio_mensaje_incorporacion(cur, invitacion_id: int) -> bool:
    """
    Marca el mensaje de incorporación como reclamado para evitar doble envío.
    Solo devuelve True una vez.
    """
    cur.execute("""
        UPDATE invitaciones
        SET
            mensaje_incorporacion_enviado = true,
            fecha_mensaje_incorporacion = now(),
            actualizado_en = now()
        WHERE id = %s
          AND COALESCE(mensaje_incorporacion_enviado, false) = false
        RETURNING id
    """, (invitacion_id,))

    return cur.fetchone() is not None


def resetear_envio_mensaje_incorporacion(invitacion_id: int) -> None:
    """
    Si falla el envío por WhatsApp, permite reintentar luego.
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE invitaciones
                    SET
                        mensaje_incorporacion_enviado = false,
                        fecha_mensaje_incorporacion = NULL,
                        actualizado_en = now()
                    WHERE id = %s
                """, (invitacion_id,))
                conn.commit()

    except Exception as e:
        print(f"⚠️ Error reseteando mensaje incorporación: {e}")


def enviar_mensaje_incorporacion_si_aplica(
    invitacion_id: int,
    telefono: Optional[str],
) -> bool:
    """
    Envía el mensaje de bienvenida por incorporación (link al portal).
    """
    if not telefono:
        print("⚠️ No se envió mensaje de incorporación: aspirante sin teléfono/WhatsApp")
        return False

    try:
        return enviar_portal_bienvenida_incorporacion(telefono)

    except Exception as e:
        print(f"❌ Error enviando mensaje incorporación invitacion_id={invitacion_id}: {e}")
        return False


# @router.put("/api/invitaciones/{invitacion_id}")
# def actualizar_invitacion(invitacion_id: int, data: InvitacionUpdate):
#     creador_id = None
#
#     with get_connection_context() as conn:
#         with conn.cursor() as cur:
#             actual = obtener_invitacion_por_id(cur, invitacion_id)
#
#             estado_invitacion = (
#                 data.estado_invitacion
#                 if data.estado_invitacion is not None
#                 else actual["estado_invitacion"]
#             )
#             estado_tiktok = (
#                 data.estado_tiktok
#                 if data.estado_tiktok is not None
#                 else actual["estado_tiktok"]
#             )
#
#             validar_estado_invitacion(estado_invitacion)
#             validar_estado_tiktok(estado_tiktok)
#
#             usuario_invita = (
#                 data.usuario_invita
#                 if data.usuario_invita is not None
#                 else actual["usuario_invita"]
#             )
#             if usuario_invita is not None:
#                 validar_usuario_existe(cur, usuario_invita)
#
#             manager_id = (
#                 data.manager_id
#                 if data.manager_id is not None
#                 else actual["manager_id"]
#             )
#             if manager_id is not None:
#                 validar_manager_existe(cur, manager_id)
#
#             fecha_incorporacion = (
#                 data.fecha_incorporacion
#                 if data.fecha_incorporacion is not None
#                 else actual["fecha_incorporacion"]
#             )
#
#             cur.execute("""
#                 UPDATE invitaciones
#                 SET
#                     fecha_invitacion = %s,
#                     usuario_invita = %s,
#                     manager_id = %s,
#                     estado_invitacion = %s,
#                     estado_tiktok = %s,
#                     fecha_respuesta_invitacion = %s,
#                     fecha_respuesta_tiktok = %s,
#                     fecha_incorporacion = %s,
#                     mensaje_enviado = %s,
#                     solicitud_tiktok_enviada = %s,
#                     observaciones = %s,
#                     actualizado_en = now()
#                 WHERE id = %s
#             """, (
#                 data.fecha_invitacion if data.fecha_invitacion is not None else actual["fecha_invitacion"],
#                 usuario_invita,
#                 manager_id,
#                 estado_invitacion,
#                 estado_tiktok,
#                 data.fecha_respuesta_invitacion if data.fecha_respuesta_invitacion is not None else actual["fecha_respuesta_invitacion"],
#                 data.fecha_respuesta_tiktok if data.fecha_respuesta_tiktok is not None else actual["fecha_respuesta_tiktok"],
#                 fecha_incorporacion,
#                 data.mensaje_enviado if data.mensaje_enviado is not None else actual["mensaje_enviado"],
#                 data.solicitud_tiktok_enviada if data.solicitud_tiktok_enviada is not None else actual["solicitud_tiktok_enviada"],
#                 data.observaciones if data.observaciones is not None else actual["observaciones"],
#                 invitacion_id
#             ))
#
#             invitacion = obtener_invitacion_por_id(cur, invitacion_id)
#
#             if puede_incorporarse(invitacion):
#                 registrar_cambio_estado_con_cursor(
#                     cur=cur,
#                     aspirante_id=invitacion["aspirante_id"],
#                     nuevo_estado_id=6,
#                     usuario_id=usuario_invita,
#                     origen_cambio="actualizar_invitacion",
#                     observacion="Aspirante pasa a Incorporado tras aceptación de invitación y TikTok"
#                 )
#                 creador_id = crear_o_actualizar_creador_desde_aspirante(
#                     cur=cur,
#                     aspirante_id=invitacion["aspirante_id"],
#                     manager_id=manager_id,
#                     fecha_incorporacion=fecha_incorporacion
#                 )
#
#             conn.commit()
#
#             invitacion = obtener_invitacion_por_id(cur, invitacion_id)
#
#     return {
#         "success": True,
#         "message": "Invitación actualizada correctamente",
#         "data": invitacion,
#         "creador_id": creador_id
#     }


# =========================================================
# ENDPOINT 7: ACTUALIZAR ESTADOS
# =========================================================

@router.patch("/api/invitaciones/{invitacion_id}/estados")
def actualizar_estados_invitacion(invitacion_id: int, data: InvitacionEstadosUpdate):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            actual = obtener_invitacion_por_id(cur, invitacion_id)

            estado_invitacion = (
                data.estado_invitacion
                if data.estado_invitacion is not None
                else actual["estado_invitacion"]
            )
            estado_tiktok = (
                data.estado_tiktok
                if data.estado_tiktok is not None
                else actual["estado_tiktok"]
            )

            validar_estado_invitacion(estado_invitacion)
            validar_estado_tiktok(estado_tiktok)

            cur.execute("""
                UPDATE invitaciones
                SET
                    estado_invitacion = %s,
                    estado_tiktok = %s,
                    fecha_respuesta_invitacion = %s,
                    fecha_respuesta_tiktok = %s,
                    observaciones = %s,
                    actualizado_en = now()
                WHERE id = %s
            """, (
                estado_invitacion,
                estado_tiktok,
                data.fecha_respuesta_invitacion if data.fecha_respuesta_invitacion is not None else actual["fecha_respuesta_invitacion"],
                data.fecha_respuesta_tiktok if data.fecha_respuesta_tiktok is not None else actual["fecha_respuesta_tiktok"],
                data.observaciones if data.observaciones is not None else actual["observaciones"],
                invitacion_id
            ))

            invitacion = obtener_invitacion_por_id(cur, invitacion_id)
            actualizar_estado_creador_según_invitacion(cur, invitacion["aspirante_id"], invitacion)
            conn.commit()

            invitacion = obtener_invitacion_por_id(cur, invitacion_id)

            return {
                "success": True,
                "message": "Estados actualizados correctamente",
                "data": invitacion
            }


# =========================================================
# ENDPOINT 8: MARCAR MENSAJE ENVIADO
# =========================================================

@router.patch("/api/invitaciones/{invitacion_id}/marcar-mensaje-enviado")
def marcar_mensaje_enviado(invitacion_id: int):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            actual = obtener_invitacion_por_id(cur, invitacion_id)

            nuevo_estado = actual["estado_invitacion"]
            if nuevo_estado == ESTADO_INVITACION_PENDIENTE_ENVIO:
                nuevo_estado = ESTADO_INVITACION_ENVIADA

            cur.execute("""
                UPDATE invitaciones
                SET
                    mensaje_enviado = true,
                    estado_invitacion = %s,
                    fecha_invitacion = COALESCE(fecha_invitacion, CURRENT_DATE),
                    actualizado_en = now()
                WHERE id = %s
            """, (nuevo_estado, invitacion_id))

            invitacion = obtener_invitacion_por_id(cur, invitacion_id)
            actualizar_estado_creador_según_invitacion(cur, invitacion["aspirante_id"], invitacion)
            conn.commit()

            invitacion = obtener_invitacion_por_id(cur, invitacion_id)

            return {
                "success": True,
                "message": "Mensaje marcado como enviado",
                "data": invitacion
            }


# =========================================================
# ENDPOINT 9: MARCAR TIKTOK ENVIADO
# =========================================================

@router.patch("/api/invitaciones/{invitacion_id}/marcar-tiktok-enviado")
def marcar_tiktok_enviado(invitacion_id: int):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            obtener_invitacion_por_id(cur, invitacion_id)

            cur.execute("""
                UPDATE invitaciones
                SET
                    solicitud_tiktok_enviada = true,
                    estado_tiktok = %s,
                    actualizado_en = now()
                WHERE id = %s
            """, (ESTADO_TIKTOK_ENVIADO, invitacion_id))

            invitacion = obtener_invitacion_por_id(cur, invitacion_id)
            actualizar_estado_creador_según_invitacion(cur, invitacion["aspirante_id"], invitacion)
            conn.commit()

            invitacion = obtener_invitacion_por_id(cur, invitacion_id)

            return {
                "success": True,
                "message": "Solicitud TikTok marcada como enviada",
                "data": invitacion
            }


# =========================================================
# ENDPOINT 10: ACEPTAR INVITACIÓN
# =========================================================

@router.patch("/api/invitaciones/{invitacion_id}/aceptar")
def aceptar_invitacion(invitacion_id: int, data: InvitacionDecisionFinalUpdate):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            actual = obtener_invitacion_por_id(cur, invitacion_id)

            cur.execute("""
                UPDATE invitaciones
                SET
                    estado_invitacion = %s,
                    fecha_respuesta_invitacion = COALESCE(fecha_respuesta_invitacion, CURRENT_DATE),
                    observaciones = %s,
                    actualizado_en = now()
                WHERE id = %s
            """, (
                ESTADO_INVITACION_ACEPTADA,
                data.observaciones if data.observaciones is not None else actual["observaciones"],
                invitacion_id
            ))

            invitacion = obtener_invitacion_por_id(cur, invitacion_id)
            actualizar_estado_creador_según_invitacion(cur, invitacion["aspirante_id"], invitacion)
            conn.commit()

            invitacion = obtener_invitacion_por_id(cur, invitacion_id)

            return {
                "success": True,
                "message": "Invitación aceptada correctamente",
                "data": invitacion
            }


# =========================================================
# ENDPOINT 11: RECHAZAR INVITACIÓN
# =========================================================

@router.patch("/api/invitaciones/{invitacion_id}/rechazar")
def rechazar_invitacion(invitacion_id: int, data: InvitacionDecisionFinalUpdate):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            actual = obtener_invitacion_por_id(cur, invitacion_id)

            cur.execute("""
                UPDATE invitaciones
                SET
                    estado_invitacion = %s,
                    fecha_respuesta_invitacion = COALESCE(fecha_respuesta_invitacion, CURRENT_DATE),
                    observaciones = %s,
                    actualizado_en = now()
                WHERE id = %s
            """, (
                ESTADO_INVITACION_RECHAZADA,
                data.observaciones if data.observaciones is not None else actual["observaciones"],
                invitacion_id
            ))

            invitacion = obtener_invitacion_por_id(cur, invitacion_id)
            actualizar_estado_creador_según_invitacion(cur, invitacion["aspirante_id"], invitacion)
            conn.commit()

            invitacion = obtener_invitacion_por_id(cur, invitacion_id)

            return {
                "success": True,
                "message": "Invitación rechazada correctamente",
                "data": invitacion
            }


# =========================================================
# ENDPOINT 12: APROBAR TIKTOK
# =========================================================

@router.patch("/api/invitaciones/{invitacion_id}/aprobar-tiktok")
def aprobar_tiktok(invitacion_id: int, data: InvitacionDecisionFinalUpdate):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            actual = obtener_invitacion_por_id(cur, invitacion_id)

            cur.execute("""
                UPDATE invitaciones
                SET
                    estado_tiktok = %s,
                    fecha_respuesta_tiktok = COALESCE(fecha_respuesta_tiktok, CURRENT_DATE),
                    observaciones = %s,
                    actualizado_en = now()
                WHERE id = %s
            """, (
                ESTADO_TIKTOK_APROBADO,
                data.observaciones if data.observaciones is not None else actual["observaciones"],
                invitacion_id
            ))

            invitacion = obtener_invitacion_por_id(cur, invitacion_id)
            actualizar_estado_creador_según_invitacion(cur, invitacion["aspirante_id"], invitacion)
            conn.commit()

            invitacion = obtener_invitacion_por_id(cur, invitacion_id)

            return {
                "success": True,
                "message": "TikTok aprobado correctamente",
                "data": invitacion
            }


# =========================================================
# ENDPOINT 13: RECHAZAR TIKTOK
# =========================================================

@router.patch("/api/invitaciones/{invitacion_id}/rechazar-tiktok")
def rechazar_tiktok(invitacion_id: int, data: InvitacionDecisionFinalUpdate):
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            actual = obtener_invitacion_por_id(cur, invitacion_id)

            cur.execute("""
                UPDATE invitaciones
                SET
                    estado_tiktok = %s,
                    fecha_respuesta_tiktok = COALESCE(fecha_respuesta_tiktok, CURRENT_DATE),
                    observaciones = %s,
                    actualizado_en = now()
                WHERE id = %s
            """, (
                ESTADO_TIKTOK_RECHAZADO,
                data.observaciones if data.observaciones is not None else actual["observaciones"],
                invitacion_id
            ))

            invitacion = obtener_invitacion_por_id(cur, invitacion_id)
            actualizar_estado_creador_según_invitacion(cur, invitacion["aspirante_id"], invitacion)
            conn.commit()

            invitacion = obtener_invitacion_por_id(cur, invitacion_id)

            return {
                "success": True,
                "message": "TikTok rechazado correctamente",
                "data": invitacion
            }


# =========================================================
# ENDPOINT 14: ASIGNAR MANAGER E INCORPORAR (flujo dedicado)
# =========================================================

@router.patch("/api/invitaciones/{invitacion_id}/asignar-manager")
def asignar_manager_e_incorporacion(invitacion_id: int, data: InvitacionAsignacionUpdate):
    """
    Guardar manager y fecha de incorporación.
    Ejecuta incorporación: creadores, migración de token portal y WhatsApp de bienvenida.
    """
    creador_id = None
    debe_enviar_whatsapp = False
    telefono_bienvenida = None

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            actual = obtener_invitacion_por_id(cur, invitacion_id)

            validar_puede_asignarse_manager(actual)
            validar_manager_existe(cur, data.manager_id)

            cur.execute("""
                UPDATE invitaciones
                SET
                    manager_id = %s,
                    fecha_incorporacion = %s,
                    observaciones = %s,
                    actualizado_en = now()
                WHERE id = %s
            """, (
                data.manager_id,
                data.fecha_incorporacion,
                data.observaciones if data.observaciones is not None else actual["observaciones"],
                invitacion_id,
            ))

            invitacion = obtener_invitacion_por_id(cur, invitacion_id)

            incorporacion = ejecutar_incorporacion_invitacion(
                cur=cur,
                invitacion=invitacion,
                invitacion_id=invitacion_id,
                manager_id=data.manager_id,
                fecha_incorporacion=data.fecha_incorporacion,
                estado_aspirante_id_anterior=actual.get("estado_aspirante_id"),
                usuario_id=actual.get("usuario_invita"),
                origen_cambio="asignar_manager",
            )

            creador_id = incorporacion["creador_id"]
            debe_enviar_whatsapp = incorporacion["debe_enviar_whatsapp"]
            telefono_bienvenida = incorporacion["telefono"]

            conn.commit()

            invitacion = obtener_invitacion_por_id(cur, invitacion_id)

    mensaje_incorporacion_enviado = procesar_bienvenida_incorporacion(
        invitacion_id=invitacion_id,
        telefono=telefono_bienvenida,
        debe_enviar=debe_enviar_whatsapp,
    )

    return {
        "success": True,
        "message": "Manager asignado e incorporación completada correctamente",
        "data": invitacion,
        "creador_id": creador_id,
        "mensaje_incorporacion_enviado": mensaje_incorporacion_enviado,
        "puede_incorporarse": puede_incorporarse(invitacion),
    }

# =========================================================
# ENDPOINT 6: ACTUALIZACIÓN GENERAL
# =========================================================

# @router.put("/api/invitaciones/{invitacion_id}")
# def actualizar_invitacion(invitacion_id: int, data: InvitacionUpdate):
#     with get_connection_context() as conn:
#         with conn.cursor() as cur:
#             actual = obtener_invitacion_por_id(cur, invitacion_id)
#
#             estado_invitacion = (
#                 data.estado_invitacion
#                 if data.estado_invitacion is not None
#                 else actual["estado_invitacion"]
#             )
#             estado_tiktok = (
#                 data.estado_tiktok
#                 if data.estado_tiktok is not None
#                 else actual["estado_tiktok"]
#             )
#
#             validar_estado_invitacion(estado_invitacion)
#             validar_estado_tiktok(estado_tiktok)
#
#             usuario_invita = (
#                 data.usuario_invita
#                 if data.usuario_invita is not None
#                 else actual["usuario_invita"]
#             )
#             if usuario_invita is not None:
#                 validar_usuario_existe(cur, usuario_invita)
#
#             manager_id = (
#                 data.manager_id
#                 if data.manager_id is not None
#                 else actual["manager_id"]
#             )
#             if manager_id is not None:
#                 validar_manager_existe(cur, manager_id)
#
#             cur.execute("""
#                 UPDATE invitaciones
#                 SET
#                     fecha_invitacion = %s,
#                     usuario_invita = %s,
#                     manager_id = %s,
#                     estado_invitacion = %s,
#                     estado_tiktok = %s,
#                     fecha_respuesta_invitacion = %s,
#                     fecha_respuesta_tiktok = %s,
#                     fecha_incorporacion = %s,
#                     mensaje_enviado = %s,
#                     solicitud_tiktok_enviada = %s,
#                     observaciones = %s,
#                     actualizado_en = now()
#                 WHERE id = %s
#             """, (
#                 data.fecha_invitacion if data.fecha_invitacion is not None else actual["fecha_invitacion"],
#                 usuario_invita,
#                 manager_id,
#                 estado_invitacion,
#                 estado_tiktok,
#                 data.fecha_respuesta_invitacion if data.fecha_respuesta_invitacion is not None else actual["fecha_respuesta_invitacion"],
#                 data.fecha_respuesta_tiktok if data.fecha_respuesta_tiktok is not None else actual["fecha_respuesta_tiktok"],
#                 data.fecha_incorporacion if data.fecha_incorporacion is not None else actual["fecha_incorporacion"],
#                 data.mensaje_enviado if data.mensaje_enviado is not None else actual["mensaje_enviado"],
#                 data.solicitud_tiktok_enviada if data.solicitud_tiktok_enviada is not None else actual["solicitud_tiktok_enviada"],
#                 data.observaciones if data.observaciones is not None else actual["observaciones"],
#                 invitacion_id
#             ))
#
#             invitacion = obtener_invitacion_por_id(cur, invitacion_id)
#             conn.commit()
#
#     # ✅ Cambiar a Incorporado solo si ya cumple condición final
#     if puede_incorporarse(invitacion):
#         registrar_cambio_estado(
#             aspirante_id=invitacion["aspirante_id"],
#             nuevo_estado_id=6,  # Incorporado
#             usuario_id=usuario_invita,
#             origen_cambio="actualizar_invitacion",
#             observacion="Aspirante pasa a Incorporado tras aceptación de invitación y TikTok"
#         )
#
#     return {
#         "success": True,
#         "message": "Invitación actualizada correctamente",
#         "data": invitacion
#     }
