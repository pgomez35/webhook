"""Catálogo de plantillas Meta permitidas en la pantalla Mensajes WhatsApp.

El identificador estable (`codigo`) es el nombre exacto de la plantilla en Meta.
El frontend muestra `etiqueta` y siempre envía `codigo`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Literal, Optional, Tuple

ParametroPlantilla = Literal["nombre", "agencia"]

FALLBACK_NOMBRE = "Candidato"
FALLBACK_AGENCIA = "Nuestro equipo"


class PlantillaMensajesDesconocida(ValueError):
    """El codigo no está en el catálogo o no es enviable desde Mensajes."""


@dataclass(frozen=True)
class PlantillaMensajes:
    codigo: str
    nombre_meta: str
    idioma: str
    parametros: Tuple[ParametroPlantilla, ...]
    body_vars_count: int
    etiqueta: str
    descripcion: str = ""
    visible_en_mensajes: bool = True


CATALOGO_PLANTILLAS_MENSAJES: Dict[str, PlantillaMensajes] = {
    "primer_contacto_usuarios": PlantillaMensajes(
        codigo="primer_contacto_usuarios",
        nombre_meta="primer_contacto_usuarios",
        idioma="es_CO",
        parametros=("nombre", "agencia"),
        body_vars_count=2,
        etiqueta="Primer contacto",
        descripcion=(
            "Hola {{1}}, te escribimos de {{2}} para continuar con una gestión "
            "relacionada con tu proceso en la agencia. Pulsa “Continuar” para seguir."
        ),
    ),
    "reconexion_general_corta": PlantillaMensajes(
        codigo="reconexion_general_corta",
        nombre_meta="reconexion_general_corta",
        idioma="es_CO",
        parametros=("nombre", "agencia"),
        body_vars_count=2,
        etiqueta="Reconexión (ventana 24h)",
        descripcion="Plantilla corta para reabrir la conversación fuera de la ventana de 24h.",
    ),
    "solicitar_informacion": PlantillaMensajes(
        codigo="solicitar_informacion",
        nombre_meta="solicitar_informacion",
        idioma="es_CO",
        parametros=("nombre",),
        body_vars_count=1,
        etiqueta="Solicitar información de perfil",
        descripcion="Solicita al contacto completar o actualizar su información de perfil.",
    ),
}

ORDEN_PLANTILLAS_MENSAJES: Tuple[str, ...] = (
    "primer_contacto_usuarios",
    "reconexion_general_corta",
    "solicitar_informacion",
)


def resolver_plantilla_mensajes(codigo: str) -> PlantillaMensajes:
    key = (codigo or "").strip()
    plantilla = CATALOGO_PLANTILLAS_MENSAJES.get(key)
    if not plantilla or not plantilla.visible_en_mensajes:
        raise PlantillaMensajesDesconocida(key)
    return plantilla


def construir_parametros_plantilla(
    plantilla: PlantillaMensajes,
    *,
    nombre: str = "",
    agencia: str = "",
) -> List[str]:
    valores = {
        "nombre": (nombre or "").strip() or FALLBACK_NOMBRE,
        "agencia": (agencia or "").strip() or FALLBACK_AGENCIA,
    }
    return [valores[campo] for campo in plantilla.parametros]


def serializar_plantilla_mensajes(plantilla: PlantillaMensajes) -> dict:
    return {
        "codigo": plantilla.codigo,
        "nombre_meta": plantilla.nombre_meta,
        "idioma": plantilla.idioma,
        "etiqueta": plantilla.etiqueta,
        "descripcion": plantilla.descripcion,
        "parametros": list(plantilla.parametros),
    }


def listar_plantillas_mensajes() -> List[dict]:
    visibles: List[dict] = []
    for codigo in ORDEN_PLANTILLAS_MENSAJES:
        plantilla = CATALOGO_PLANTILLAS_MENSAJES.get(codigo)
        if plantilla and plantilla.visible_en_mensajes:
            visibles.append(serializar_plantilla_mensajes(plantilla))
    return visibles


def enviar_plantilla_catalogo(
    *,
    codigo: str,
    telefono: str,
    nombre: str,
    agencia: str,
    token: str,
    phone_number_id: str,
    enviar_fn: Optional[Callable[..., Tuple[int, dict]]] = None,
) -> Tuple[int, dict, PlantillaMensajes, List[str]]:
    """Resuelve la plantilla por codigo (nombre Meta) y la envía con sus variables."""
    from enviar_msg_wp import enviar_plantilla_generica_parametros

    plantilla = resolver_plantilla_mensajes(codigo)
    parametros = construir_parametros_plantilla(
        plantilla,
        nombre=nombre,
        agencia=agencia,
    )
    fn = enviar_fn or enviar_plantilla_generica_parametros
    status_code, respuesta = fn(
        token=token,
        phone_number_id=phone_number_id,
        numero_destino=telefono,
        nombre_plantilla=plantilla.nombre_meta,
        codigo_idioma=plantilla.idioma,
        parametros=parametros,
        body_vars_count=plantilla.body_vars_count,
    )
    return status_code, respuesta, plantilla, parametros
