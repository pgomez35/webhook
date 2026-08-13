"""
Configuración rápida del asistente conversacional.

Reutiliza las tablas y CRUD de `database_chatbot_conversacional` sin crear
estructuras paralelas. Opera de forma transaccional, idempotente y multiagencia.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlparse

import database_chatbot_captacion as db_captacion
import database_chatbot_conversacional as db
from chatbot_conversacional_exceptions import ConversacionalError
from chatbot_conversacional_tools import (
    HERRAMIENTAS,
    NOMBRES_HERRAMIENTAS,
    _normalizar_nombre_herramienta,
)

logger = logging.getLogger("uvicorn.error")

PLANTILLA_AGENCIA_LIVE = "agencia_live_estandar"
CODIGO_FLUJO_INFORMATIVO = "informativo_base"
CODIGO_FLUJO_CONVERSION = "conversion_base"
CODIGO_RECURSO_SOLICITUD = "solicitud_principal"
CODIGO_PRUEBA_CONVERSION = "prueba_conversion_base"
CODIGO_REGLA_TRANSFERENCIA = "transferencia_humana_base"

HERRAMIENTAS_MINIMAS_PLANTILLA: Tuple[str, ...] = (
    "consultar_informacion_agencia",
    "consultar_requisitos",
    "consultar_beneficios_vigentes",
    "consultar_faq",
    "consultar_recursos_autorizados",
    "enviar_enlace_autorizado",
    "transferir_a_humano",
)

INSTRUCCIONES_BASE = (
    "Eres el asistente virtual de la agencia. Responde primero lo preguntado, "
    "sé breve y haz como máximo una pregunta para avanzar. No inventes "
    "requisitos, bonos ni enlaces. No afirmes que un aspirante fue aprobado. "
    "Declara que eres un asistente virtual. Transfiere a una persona cuando "
    "el aspirante lo pida o cuando no puedas resolver con la información "
    "autorizada. No repitas información ya dada."
)


# ---------------------------------------------------------------------------
# Herramientas
# ---------------------------------------------------------------------------


def listar_codigos_herramientas_validas() -> List[str]:
    return list(NOMBRES_HERRAMIENTAS)


def analizar_herramientas_permitidas(
    permitidas: Optional[Sequence[Any]],
) -> Dict[str, Any]:
    """Compara la lista guardada contra el registro real del agente."""
    originales = [str(x).strip() for x in (permitidas or []) if str(x or "").strip()]
    validas: List[str] = []
    invalidas: List[str] = []
    mapeadas: List[Dict[str, str]] = []
    vistos: Set[str] = set()

    for nombre in originales:
        canonico = _normalizar_nombre_herramienta(nombre)
        if canonico not in HERRAMIENTAS:
            invalidas.append(nombre)
            continue
        if nombre != canonico:
            mapeadas.append({"desde": nombre, "hacia": canonico})
        if canonico not in vistos:
            vistos.add(canonico)
            validas.append(canonico)

    return {
        "originales": originales,
        "validas": validas,
        "invalidas": invalidas,
        "mapeadas": mapeadas,
        "hay_invalidas": bool(invalidas),
    }


def herramientas_minimas_plantilla() -> List[str]:
    return [h for h in HERRAMIENTAS_MINIMAS_PLANTILLA if h in HERRAMIENTAS]


def corregir_herramientas_invalidas(
    agencia_id: int,
    chatbot_configuracion_id: int,
    *,
    confirmar: bool = False,
    cur=None,
) -> Dict[str, Any]:
    with db._cursor(cur) as c:
        db._exige_configuracion(agencia_id, chatbot_configuracion_id, cur=c)
        asistente = db.obtener_asistente_por_config(
            agencia_id, chatbot_configuracion_id, cur=c
        )
        if not asistente:
            raise ConversacionalError("Asistente no encontrado")

        analisis = analizar_herramientas_permitidas(
            asistente.get("herramientas_permitidas")
        )
        if not confirmar:
            return {
                "confirmado": False,
                "retiradas": analisis["invalidas"],
                "conservadas": analisis["validas"],
                "asistente_id": asistente.get("id"),
            }

        actualizado = db.actualizar_asistente(
            agencia_id,
            int(asistente["id"]),
            {"herramientas_permitidas": analisis["validas"]},
            cur=c,
        )
        logger.info(
            "[CONFIG_RAPIDA] agencia_id=%s chatbot_configuracion_id=%s "
            "accion=corregir_herramientas retiradas=%s conservadas=%s resultado=ok",
            agencia_id,
            chatbot_configuracion_id,
            len(analisis["invalidas"]),
            len(analisis["validas"]),
        )
        return {
            "confirmado": True,
            "retiradas": analisis["invalidas"],
            "conservadas": analisis["validas"],
            "asistente": actualizado,
        }


# ---------------------------------------------------------------------------
# Plantilla
# ---------------------------------------------------------------------------


def _presentacion_sugerida(nombre_agencia: str) -> str:
    nombre = (nombre_agencia or "").strip() or "nuestra agencia"
    return (
        f"¡Hola! 👋 Soy el asistente virtual de {nombre}. "
        "Cuéntame, ¿qué te gustaría saber o quieres iniciar tu proceso "
        "como creador LIVE?"
    )


def _url_real(url: Optional[str]) -> Optional[str]:
    texto = str(url or "").strip()
    if not texto:
        return None
    bajos = texto.lower()
    if bajos in {"#", "about:blank"}:
        return None
    if "example.com" in bajos or "localhost" in bajos or "127.0.0.1" in bajos:
        return None
    parsed = urlparse(texto if "://" in texto else f"https://{texto}")
    if parsed.scheme not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None
    return texto if "://" in texto else f"https://{texto}"


def _pasos_conversion(*, incluir_evidencias: bool, codigo_recurso: str) -> List[Dict[str, Any]]:
    pasos: List[Dict[str, Any]] = [
        {
            "codigo": "confirmar_interes",
            "nombre": "Confirmar interés",
            "orden": 0,
            "tipo_accion": "confirmar_interes",
            "obligatorio": True,
            "mensaje_instrucciones": (
                "Confirma si la persona quiere iniciar el proceso de ingreso."
            ),
            "estado_exitoso": "interes_confirmado",
            "configuracion": {},
        },
        {
            "codigo": "enviar_solicitud",
            "nombre": "Enviar solicitud",
            "orden": 1,
            "tipo_accion": "enviar_enlace",
            "obligatorio": True,
            "mensaje_instrucciones": (
                f"Envía el recurso autorizado con código '{codigo_recurso}' "
                "usando la herramienta enviar_enlace_autorizado."
            ),
            "estado_exitoso": "solicitud_enviada",
            "configuracion": {"codigo_recurso": codigo_recurso},
        },
    ]
    orden = 2
    if incluir_evidencias:
        pasos.append(
            {
                "codigo": "solicitar_evidencias",
                "nombre": "Solicitar evidencias",
                "orden": orden,
                "tipo_accion": "solicitar_evidencias",
                "obligatorio": False,
                "permite_omitir": True,
                "mensaje_instrucciones": (
                    "Solicita las evidencias configuradas después de la solicitud."
                ),
                "estado_exitoso": "evidencias_solicitadas",
                "configuracion": {"momento": "despues"},
            }
        )
        orden += 1
        pasos.append(
            {
                "codigo": "confirmar_evidencias",
                "nombre": "Confirmar recepción de evidencias",
                "orden": orden,
                "tipo_accion": "confirmar_evidencias",
                "obligatorio": False,
                "permite_omitir": True,
                "mensaje_instrucciones": "Confirma que recibiste las evidencias.",
                "estado_exitoso": "evidencias_recibidas",
                "configuracion": {},
            }
        )
        orden += 1

    pasos.append(
        {
            "codigo": "transferir_revision",
            "nombre": "Transferir a revisión humana",
            "orden": orden,
            "tipo_accion": "transferir_humano",
            "obligatorio": True,
            "requiere_humano": True,
            "mensaje_instrucciones": (
                "Transfiere a una persona del equipo para revisar el caso."
            ),
            "estado_exitoso": "escalado_humano",
            "configuracion": {},
        }
    )
    return pasos


def aplicar_plantilla_asistente_conversacional(
    agencia_id: int,
    chatbot_configuracion_id: int,
    plantilla_codigo: str = PLANTILLA_AGENCIA_LIVE,
    *,
    completar_solo_faltantes: bool = True,
    activar_asistente: bool = False,
    config_rigida: Optional[Dict[str, Any]] = None,
    agencia: Optional[Dict[str, Any]] = None,
    cur=None,
) -> Dict[str, Any]:
    """
    Completa registros faltantes para una prueba razonable.

    No sobrescribe personalizaciones ni inventa bonos/enlaces.
    No cambia `usar_asistente_conversacional`.
    """
    if plantilla_codigo != PLANTILLA_AGENCIA_LIVE:
        raise ConversacionalError(f"Plantilla desconocida: {plantilla_codigo}")

    cfg_rigida = dict(
        config_rigida
        or db_captacion.obtener_configuracion_por_id(
            agencia_id, chatbot_configuracion_id, solo_activa=False
        )
        or {}
    )
    datos_agencia = dict(
        agencia or db_captacion.obtener_agencia_por_id(agencia_id) or {}
    )
    nombre_agencia = str(datos_agencia.get("nombre") or "").strip()
    advertencias: List[str] = []

    with db._cursor(cur) as c:
        db._exige_configuracion(agencia_id, chatbot_configuracion_id, cur=c)

        # --- Base legacy (asistente, FAQ, requisitos, flujo informativo) ---
        base = db.inicializar_asistente_desde_config(
            agencia_id,
            chatbot_configuracion_id,
            cfg_rigida,
            datos_agencia,
            copiar_faq=True,
            crear_requisitos_base=True,
            crear_flujo_informativo=True,
            cur=c,
        )

        asistente = base.get("asistente") or db.obtener_asistente_por_config(
            agencia_id, chatbot_configuracion_id, cur=c
        )
        asistente_creado = bool(base.get("asistente_creado"))
        asistente_actualizado = False

        # Completar campos vacíos del asistente sin pisar textos existentes.
        if asistente and completar_solo_faltantes:
            parches: Dict[str, Any] = {}
            if not str(asistente.get("presentacion_inicial") or "").strip():
                parches["presentacion_inicial"] = (
                    str(cfg_rigida.get("mensaje_bienvenida") or "").strip()
                    or _presentacion_sugerida(nombre_agencia)
                )
            if not str(asistente.get("instrucciones_sistema") or "").strip():
                parches["instrucciones_sistema"] = INSTRUCCIONES_BASE
            if not str(asistente.get("descripcion_agencia") or "").strip() and nombre_agencia:
                parches["descripcion_agencia"] = nombre_agencia
            if asistente.get("tono") in (None, ""):
                parches["tono"] = "cercano"
            if not asistente.get("idioma"):
                parches["idioma"] = "es-CO"
            if not asistente.get("zona_horaria"):
                parches["zona_horaria"] = "America/Bogota"
            if asistente.get("max_tokens_salida") in (None, 0):
                parches["max_tokens_salida"] = 450
            if asistente.get("max_preguntas_seguidas") in (None, 0):
                parches["max_preguntas_seguidas"] = 1
            if asistente.get("max_intentos_aclaracion") is None:
                parches["max_intentos_aclaracion"] = 1

            tools_actuales = list(asistente.get("herramientas_permitidas") or [])
            if not tools_actuales:
                parches["herramientas_permitidas"] = herramientas_minimas_plantilla()
            else:
                analisis = analizar_herramientas_permitidas(tools_actuales)
                if analisis["hay_invalidas"]:
                    advertencias.append(
                        "Hay herramientas guardadas que no existen en el servidor."
                    )

            if not asistente.get("modo_informativo_activo"):
                # Solo activar informativo si estaba apagado y no había personalización clara.
                if asistente_creado:
                    parches["modo_informativo_activo"] = True
            if asistente_creado and not asistente.get("modo_conversion_activo"):
                parches["modo_conversion_activo"] = True
                parches["modo_predeterminado"] = "informativo"

            if activar_asistente and not asistente.get("activo"):
                parches["activo"] = True

            if parches:
                asistente = db.actualizar_asistente(
                    agencia_id, int(asistente["id"]), parches, cur=c
                )
                asistente_actualizado = True

        # --- Flujo conversión ---
        flujos_conv = db.listar_flujos(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            tipo_flujo="conversion",
            solo_activos=False,
            cur=c,
        )
        flujo_conv = next(
            (f for f in flujos_conv if f.get("codigo") == CODIGO_FLUJO_CONVERSION),
            None,
        ) or (flujos_conv[0] if flujos_conv else None)
        flujo_conversion_creado = False
        if not flujo_conv:
            recurso = db.obtener_recurso_por_codigo(
                agencia_id,
                CODIGO_RECURSO_SOLICITUD,
                chatbot_configuracion_id=chatbot_configuracion_id,
                cur=c,
            )
            incluir_evidencias = False
            flujo_conv = db.crear_flujo(
                agencia_id,
                {
                    "chatbot_configuracion_id": chatbot_configuracion_id,
                    "codigo": CODIGO_FLUJO_CONVERSION,
                    "nombre": "Ingreso de aspirante",
                    "tipo_flujo": "conversion",
                    "descripcion": (
                        "Flujo predeterminado: solicitud → evidencias opcionales → revisión humana."
                    ),
                    "estado_inicial": "inicio",
                    "estado_final": "escalado_humano",
                    "activo": bool(recurso),
                },
                cur=c,
            )
            flujo_conversion_creado = True
            for paso in _pasos_conversion(
                incluir_evidencias=incluir_evidencias,
                codigo_recurso=CODIGO_RECURSO_SOLICITUD,
            ):
                paso["flujo_id"] = flujo_conv["id"]
                db.crear_flujo_paso(agencia_id, paso, cur=c)
            if not recurso:
                advertencias.append("Falta el enlace de solicitud")

        # --- Regla escalamiento sencilla ---
        reglas = db.listar_reglas_escalamiento(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            solo_activas=False,
            cur=c,
        )
        regla_base = next(
            (
                r
                for r in reglas
                if r.get("evento") in {"solicitud_humano", "transferir_humano", "escalar"}
            ),
            None,
        )
        if not regla_base:
            db.crear_regla_escalamiento(
                agencia_id,
                {
                    "chatbot_configuracion_id": chatbot_configuracion_id,
                    "evento": "solicitud_humano",
                    "descripcion": "Transferencia a persona desde configuración rápida",
                    "prioridad": "alta",
                    "equipo_destino": "equipo_captacion",
                    "canal_destino": "panel",
                    "mensaje_usuario": (
                        "Te conectaré con una persona del equipo para continuar."
                    ),
                    "estado_destino": "escalado_humano",
                    "activo": True,
                    "orden": 1,
                },
                cur=c,
            )

        requisitos = db.listar_requisitos(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            solo_activos=False,
            cur=c,
        )
        beneficios = db.listar_beneficios(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            solo_activos=False,
            cur=c,
        )
        faqs = db.listar_faqs(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            solo_activos=False,
            cur=c,
        )
        recurso_solicitud = db.obtener_recurso_por_codigo(
            agencia_id,
            CODIGO_RECURSO_SOLICITUD,
            chatbot_configuracion_id=chatbot_configuracion_id,
            cur=c,
        )
        if not recurso_solicitud:
            advertencias.append("Falta el enlace de solicitud")

        estado = obtener_estado_configuracion_conversacional(
            agencia_id, chatbot_configuracion_id, cur=c
        )

        resumen = {
            "plantilla": plantilla_codigo,
            "asistente": {
                "creado": asistente_creado,
                "actualizado": asistente_actualizado,
                "id": int(asistente["id"]) if asistente else None,
            },
            "requisitos": {
                "creados": int(base.get("requisitos_creados") or 0),
                "existentes": max(
                    0, len(requisitos) - int(base.get("requisitos_creados") or 0)
                ),
            },
            "beneficios": {
                "creados": 0,
                "existentes": len(beneficios),
            },
            "faq": {
                "importadas": int(base.get("faqs_importadas") or 0),
                "existentes": max(
                    0, len(faqs) - int(base.get("faqs_importadas") or 0)
                ),
            },
            "flujos": {
                "informativo_creado": bool(base.get("flujo_creado")),
                "conversion_creado": flujo_conversion_creado,
            },
            "recursos": {
                "solicitud_creado": False,
                "advertencia": (
                    None if recurso_solicitud else "Falta el enlace de solicitud"
                ),
            },
            "advertencias": advertencias,
            "lista_para_probar": bool(estado.get("lista_para_prueba")),
            "estado_configuracion": estado,
            # Compatibilidad con el inicializador anterior:
            "asistente_creado": asistente_creado,
            "faqs_importadas": int(base.get("faqs_importadas") or 0),
            "requisitos_creados": int(base.get("requisitos_creados") or 0),
            "flujo_id": base.get("flujo_id"),
            "flujo_creado": bool(base.get("flujo_creado")),
            "pasos_creados": int(base.get("pasos_creados") or 0),
            "asistente_obj": asistente,
        }

        logger.info(
            "[PLANTILLA_CONVERSACIONAL] agencia_id=%s chatbot_configuracion_id=%s "
            "plantilla=%s asistente_creado=%s flujo_informativo_creado=%s "
            "flujo_conversion_creado=%s advertencias=%s resultado=ok",
            agencia_id,
            chatbot_configuracion_id,
            plantilla_codigo,
            asistente_creado,
            bool(base.get("flujo_creado")),
            flujo_conversion_creado,
            len(advertencias),
        )
        return resumen


# ---------------------------------------------------------------------------
# Diagnóstico
# ---------------------------------------------------------------------------


def _item_obligatorio(
    codigo: str, nombre: str, ok: bool, *, accion: Optional[str] = None
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "codigo": codigo,
        "nombre": nombre,
        "estado": "completo" if ok else "faltante",
    }
    if not ok and accion:
        out["accion"] = accion
    return out


def obtener_estado_configuracion_conversacional(
    agencia_id: int,
    chatbot_configuracion_id: int,
    *,
    cur=None,
) -> Dict[str, Any]:
    with db._cursor(cur) as c:
        db._exige_configuracion(agencia_id, chatbot_configuracion_id, cur=c)
        cfg = db_captacion.obtener_configuracion_por_id(
            agencia_id, chatbot_configuracion_id, solo_activa=False
        ) or {}
        asistente = db.obtener_asistente_por_config(
            agencia_id, chatbot_configuracion_id, cur=c
        )
        requisitos = db.listar_requisitos(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            solo_activos=True,
            cur=c,
        )
        beneficios = db.listar_beneficios(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            solo_activos=True,
            cur=c,
        )
        flujos_inf = db.listar_flujos(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            tipo_flujo="informativo",
            solo_activos=True,
            cur=c,
        )
        flujos_conv = db.listar_flujos(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            tipo_flujo="conversion",
            solo_activos=True,
            cur=c,
        )
        recurso = db.obtener_recurso_por_codigo(
            agencia_id,
            CODIGO_RECURSO_SOLICITUD,
            chatbot_configuracion_id=chatbot_configuracion_id,
            cur=c,
        )
        if not recurso:
            recursos = db.listar_recursos(
                agencia_id,
                chatbot_configuracion_id=chatbot_configuracion_id,
                tipo="solicitud",
                solo_activos=True,
                cur=c,
            )
            recurso = recursos[0] if recursos else None

        reglas = db.listar_reglas_escalamiento(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            solo_activas=True,
            cur=c,
        )
        analisis_tools = analizar_herramientas_permitidas(
            (asistente or {}).get("herramientas_permitidas")
        )

        tiene_asistente = bool(asistente)
        nombre_ok = bool(str((asistente or {}).get("nombre_asistente") or "").strip())
        presentacion_ok = bool(
            str((asistente or {}).get("presentacion_inicial") or "").strip()
        )
        requisitos_ok = len(requisitos) >= 1
        info_agencia_ok = bool(
            str((asistente or {}).get("descripcion_agencia") or "").strip()
        ) or len(beneficios) >= 1
        flujo_inf_ok = len(flujos_inf) >= 1
        tools_ok = not analisis_tools["hay_invalidas"]

        modo_conv = bool((asistente or {}).get("modo_conversion_activo"))
        flujo_conv_ok = len(flujos_conv) >= 1
        recurso_ok = bool(recurso and _url_real(recurso.get("url_template")))
        transferencia_ok = any(
            (r.get("evento") or "") in {"solicitud_humano", "transferir_humano", "escalar"}
            or (r.get("mensaje_usuario") or r.get("equipo_destino"))
            for r in reglas
        )
        salida_humana_ok = transferencia_ok
        if flujo_conv_ok:
            for flujo in flujos_conv:
                pasos = db.listar_flujo_pasos(
                    agencia_id, int(flujo["id"]), solo_activos=True, cur=c
                )
                if any(p.get("tipo_accion") == "transferir_humano" for p in pasos):
                    salida_humana_ok = True
                enviar = [p for p in pasos if p.get("tipo_accion") == "enviar_enlace"]
                for p in enviar:
                    cfg_paso = p.get("configuracion") or {}
                    if isinstance(cfg_paso, dict) and cfg_paso.get("codigo_recurso"):
                        break
                else:
                    if enviar and not recurso_ok:
                        flujo_conv_ok = flujo_conv_ok  # se valida aparte

        evidencias_activas = False
        evidencias_ok = True
        if flujo_conv_ok:
            for flujo in flujos_conv:
                pruebas = db.listar_pruebas_live(
                    agencia_id, flujo_id=int(flujo["id"]), solo_activas=True, cur=c
                )
                pasos = db.listar_flujo_pasos(
                    agencia_id, int(flujo["id"]), solo_activos=True, cur=c
                )
                pide_evidencias = any(
                    p.get("tipo_accion") == "solicitar_evidencias" for p in pasos
                )
                if pide_evidencias or pruebas:
                    evidencias_activas = True
                    if not pruebas:
                        evidencias_ok = False
                    else:
                        evs = db.listar_evidencias_requeridas(
                            agencia_id, int(pruebas[0]["id"]), solo_activas=True, cur=c
                        )
                        evidencias_ok = len(evs) >= 1

        obligatorios = [
            _item_obligatorio("asistente", "Asistente", tiene_asistente, accion="Crear configuración inicial"),
            _item_obligatorio("nombre_asistente", "Nombre del asistente", nombre_ok, accion="Completar nombre"),
            _item_obligatorio("presentacion", "Presentación inicial", presentacion_ok, accion="Completar presentación"),
            _item_obligatorio("requisitos", "Requisitos", requisitos_ok, accion="Agregar requisito"),
            _item_obligatorio(
                "info_agencia",
                "Descripción o beneficios",
                info_agencia_ok,
                accion="Agregar descripción o beneficio",
            ),
            _item_obligatorio("flujo_informativo", "Flujo informativo", flujo_inf_ok, accion="Completar con plantilla"),
            _item_obligatorio(
                "herramientas",
                "Herramientas válidas",
                tools_ok or not (asistente or {}).get("herramientas_permitidas"),
                accion="Corregir herramientas inválidas",
            ),
        ]

        obligatorios_conv = [
            _item_obligatorio(
                "modo_conversion",
                "Ayudar con el ingreso",
                modo_conv,
                accion="Activar ayuda con ingreso",
            ),
            _item_obligatorio(
                "flujo_conversion",
                "Flujo de ingreso",
                flujo_conv_ok,
                accion="Completar con plantilla",
            ),
            _item_obligatorio(
                "recurso_solicitud",
                "Enlace de solicitud",
                recurso_ok or transferencia_ok,
                accion="Agregar enlace",
            ),
            _item_obligatorio(
                "salida_humana",
                "Salida a humano",
                salida_humana_ok,
                accion="Configurar contacto humano",
            ),
            _item_obligatorio(
                "evidencias",
                "Evidencias (si aplica)",
                evidencias_ok,
                accion="Configurar evidencias",
            ),
        ]

        faltantes_info = [o for o in obligatorios if o["estado"] != "completo"]
        faltantes_conv = [o for o in obligatorios_conv if o["estado"] != "completo"]
        lista_para_prueba = len(faltantes_info) == 0
        lista_para_publicar = lista_para_prueba and (
            not modo_conv or len(faltantes_conv) == 0
        )

        total = len(obligatorios) + (len(obligatorios_conv) if modo_conv else 0)
        hechos = (len(obligatorios) - len(faltantes_info)) + (
            (len(obligatorios_conv) - len(faltantes_conv)) if modo_conv else 0
        )
        porcentaje = int(round((hechos / total) * 100)) if total else 0

        advertencias: List[Dict[str, str]] = []
        if analisis_tools["hay_invalidas"]:
            advertencias.append(
                {
                    "codigo": "herramientas_invalidas",
                    "mensaje": "Hay herramientas guardadas que no existen en el servidor.",
                }
            )
        if modo_conv and not recurso_ok:
            advertencias.append(
                {
                    "codigo": "sin_solicitud",
                    "mensaje": "Falta un enlace de solicitud válido para el modo de ingreso.",
                }
            )
        if not beneficios:
            advertencias.append(
                {
                    "codigo": "sin_bonos",
                    "mensaje": "Sin bonos configurados. El asistente no debe inventar valores.",
                }
            )

        motor = bool(cfg.get("usar_asistente_conversacional"))
        asistente_hab = bool((asistente or {}).get("activo"))
        estado = (
            "publicado"
            if lista_para_publicar and asistente_hab
            else "listo_para_probar"
            if lista_para_prueba
            else "incompleto"
        )

        out = {
            "estado": estado,
            "porcentaje": porcentaje,
            "motor_conversacional_seleccionado": motor,
            "asistente_habilitado": asistente_hab,
            "lista_para_prueba": lista_para_prueba,
            "lista_para_publicar": lista_para_publicar,
            "obligatorios": obligatorios + (obligatorios_conv if modo_conv else []),
            "recomendados": [],
            "advertencias": advertencias,
            "evidencias_activas": evidencias_activas,
            "faltantes": [
                o["codigo"] for o in (faltantes_info + (faltantes_conv if modo_conv else []))
            ],
        }
        logger.info(
            "[DIAGNOSTICO_CONVERSACIONAL] agencia_id=%s chatbot_configuracion_id=%s "
            "lista_para_prueba=%s lista_para_publicar=%s faltantes=%s",
            agencia_id,
            chatbot_configuracion_id,
            lista_para_prueba,
            lista_para_publicar,
            out["faltantes"],
        )
        return out


# ---------------------------------------------------------------------------
# DTO configuración rápida
# ---------------------------------------------------------------------------


def _items_contenido_requisitos(filas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in filas:
        if not r.get("activo", True):
            continue
        out.append(
            {
                "id": r.get("id"),
                "nombre": r.get("nombre") or "",
                "descripcion": r.get("descripcion") or "",
                "obligatorio": (r.get("categoria") or "") == "obligatorio",
                "activo": True,
                "codigo": r.get("codigo"),
            }
        )
    return out


def _items_contenido_beneficios(
    filas: List[Dict[str, Any]], *, tipos: Set[str]
) -> List[Dict[str, Any]]:
    out = []
    for r in filas:
        if not r.get("activo", True):
            continue
        tipo = str(r.get("tipo") or "beneficio").lower()
        if tipo not in tipos:
            continue
        out.append(
            {
                "id": r.get("id"),
                "nombre": r.get("nombre") or "",
                "descripcion": r.get("descripcion_corta")
                or r.get("texto_autorizado")
                or r.get("descripcion_completa")
                or "",
                "valor": r.get("valor"),
                "moneda": r.get("moneda"),
                "requiere_confirmacion_humana": bool(
                    r.get("requiere_validacion_humana")
                ),
                "activo": True,
                "codigo": r.get("codigo"),
                "tipo": tipo,
            }
        )
    return out


def _items_faq(filas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in filas:
        if not r.get("activo", True):
            continue
        out.append(
            {
                "id": r.get("id"),
                "pregunta": r.get("pregunta") or "",
                "respuesta": r.get("respuesta_completa")
                or r.get("respuesta_corta")
                or "",
                "activo": True,
                "codigo": r.get("codigo"),
            }
        )
    return out


def obtener_configuracion_rapida(
    agencia_id: int, chatbot_configuracion_id: int, *, cur=None
) -> Dict[str, Any]:
    with db._cursor(cur) as c:
        db._exige_configuracion(agencia_id, chatbot_configuracion_id, cur=c)
        asistente = db.obtener_asistente_por_config(
            agencia_id, chatbot_configuracion_id, cur=c
        ) or {}
        requisitos = db.listar_requisitos(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            incluir_globales=False,
            solo_activos=False,
            cur=c,
        )
        beneficios = db.listar_beneficios(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            incluir_globales=False,
            solo_activos=False,
            cur=c,
        )
        faqs = db.listar_faqs(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            incluir_globales=False,
            solo_activos=False,
            cur=c,
        )
        recurso = db.obtener_recurso_por_codigo(
            agencia_id,
            CODIGO_RECURSO_SOLICITUD,
            chatbot_configuracion_id=chatbot_configuracion_id,
            cur=c,
        )
        if not recurso:
            lista = db.listar_recursos(
                agencia_id,
                chatbot_configuracion_id=chatbot_configuracion_id,
                tipo="solicitud",
                solo_activos=True,
                cur=c,
            )
            recurso = lista[0] if lista else None

        reglas = db.listar_reglas_escalamiento(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            solo_activas=False,
            cur=c,
        )
        regla = next(
            (
                r
                for r in reglas
                if r.get("activo")
                and (r.get("evento") or "")
                in {"solicitud_humano", "transferir_humano", "escalar"}
            ),
            None,
        ) or next((r for r in reglas if r.get("activo")), None)

        flujos_conv = db.listar_flujos(
            agencia_id,
            chatbot_configuracion_id=chatbot_configuracion_id,
            tipo_flujo="conversion",
            solo_activos=False,
            cur=c,
        )
        evidencias = {
            "activo": False,
            "pedir_batalla": False,
            "pedir_mejores_momentos": False,
            "cantidad": 0,
            "instrucciones": "",
        }
        if flujos_conv:
            flujo = next(
                (f for f in flujos_conv if f.get("codigo") == CODIGO_FLUJO_CONVERSION),
                flujos_conv[0],
            )
            pasos = db.listar_flujo_pasos(
                agencia_id, int(flujo["id"]), solo_activos=True, cur=c
            )
            pide = any(p.get("tipo_accion") == "solicitar_evidencias" for p in pasos)
            pruebas = db.listar_pruebas_live(
                agencia_id, flujo_id=int(flujo["id"]), solo_activas=True, cur=c
            )
            if pide or pruebas:
                evidencias["activo"] = True
                if pruebas:
                    evidencias["instrucciones"] = (
                        pruebas[0].get("instrucciones_despues")
                        or pruebas[0].get("instrucciones_antes")
                        or ""
                    )
                    evs = db.listar_evidencias_requeridas(
                        agencia_id, int(pruebas[0]["id"]), solo_activas=True, cur=c
                    )
                    evidencias["cantidad"] = len(evs)
                    for ev in evs:
                        codigo = str(ev.get("codigo") or "").lower()
                        nombre = str(ev.get("nombre") or "").lower()
                        if "batalla" in codigo or "batalla" in nombre:
                            evidencias["pedir_batalla"] = True
                        if "momento" in codigo or "momento" in nombre:
                            evidencias["pedir_mejores_momentos"] = True

        estado = obtener_estado_configuracion_conversacional(
            agencia_id, chatbot_configuracion_id, cur=c
        )

        return {
            "general": {
                "nombre_asistente": asistente.get("nombre_asistente") or "",
                "descripcion_agencia": asistente.get("descripcion_agencia") or "",
                "presentacion_inicial": asistente.get("presentacion_inicial") or "",
                "tono": asistente.get("tono") or "cercano",
                "modo_informativo_activo": bool(
                    asistente.get("modo_informativo_activo", True)
                ),
                "modo_conversion_activo": bool(
                    asistente.get("modo_conversion_activo", False)
                ),
            },
            "solicitud": {
                "url": (recurso or {}).get("url_template") or "",
                "texto_boton": (recurso or {}).get("texto_boton")
                or "Completar solicitud",
                "recurso_id": (recurso or {}).get("id"),
            },
            "contacto_humano": {
                "activo": bool(regla and regla.get("activo")),
                "equipo_destino": (regla or {}).get("equipo_destino") or "",
                "mensaje_usuario": (regla or {}).get("mensaje_usuario") or "",
            },
            "contenido": {
                "requisitos": _items_contenido_requisitos(requisitos),
                "beneficios": _items_contenido_beneficios(
                    beneficios,
                    tipos={"beneficio", "incentivo", "capacitacion", "acompanamiento", "acompañamiento"},
                ),
                "bonos": _items_contenido_beneficios(beneficios, tipos={"bono"}),
                "faq": _items_faq(faqs),
            },
            "evidencias": evidencias,
            "estado_configuracion": estado,
            "asistente_existe": bool(asistente.get("id")),
            "asistente_activo": bool(asistente.get("activo")),
        }


# ---------------------------------------------------------------------------
# Guardar configuración rápida
# ---------------------------------------------------------------------------


def _slug_unico(base: str, usados: Set[str], prefijo: str) -> str:
    codigo = db._slug_codigo(base, prefijo=prefijo)
    if codigo not in usados:
        usados.add(codigo)
        return codigo
    i = 2
    while f"{codigo}_{i}" in usados:
        i += 1
    final = f"{codigo}_{i}"
    usados.add(final)
    return final


def _sincronizar_requisitos(
    agencia_id: int,
    cfg_id: int,
    items: List[Dict[str, Any]],
    *,
    cur,
) -> Dict[str, int]:
    from service_chatbot_carga_informacion import (
        _clave_dedupe_requisito,
        _descripcion_requisito_limpia,
        _nombre_item_limpio,
        _scrub_requisitos_duplicados,
    )

    existentes = db.listar_requisitos(
        agencia_id,
        chatbot_configuracion_id=cfg_id,
        incluir_globales=False,
        solo_activos=False,
        cur=cur,
    )
    por_id = {int(r["id"]): r for r in existentes if r.get("id")}
    por_clave = {}
    for r in existentes:
        clave = _clave_dedupe_requisito(str(r.get("nombre") or ""))
        if clave and clave != "n:":
            por_clave[clave] = r
    usados = {str(r.get("codigo")) for r in existentes if r.get("codigo")}
    vistos: Set[int] = set()
    creados = actualizados = 0

    for idx, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        if item.get("activo") is False:
            continue
        nombre = _nombre_item_limpio(str(item.get("nombre") or "").strip())
        if not nombre:
            continue
        campos = {
            "nombre": nombre[:160],
            "descripcion": _descripcion_requisito_limpia(
                nombre, item.get("descripcion")
            )
            or None,
            "categoria": "obligatorio" if item.get("obligatorio", True) else "deseable",
            "orden": idx + 1,
            "activo": True,
            "permitir_mencion_automatica": True,
        }
        item_id = item.get("id")
        clave = _clave_dedupe_requisito(nombre)
        hit = por_id.get(int(item_id)) if item_id else por_clave.get(clave)
        if hit and int(hit["id"]) in por_id:
            db.actualizar_requisito(agencia_id, int(hit["id"]), campos, cur=cur)
            vistos.add(int(hit["id"]))
            por_id[int(hit["id"])] = {**hit, **campos}
            por_clave[clave] = por_id[int(hit["id"])]
            actualizados += 1
        else:
            codigo = item.get("codigo") or _slug_unico(nombre, usados, "requisito")
            campos.update(
                {
                    "codigo": codigo,
                    "chatbot_configuracion_id": cfg_id,
                    "tipo_dato": "texto",
                }
            )
            creado = db.crear_requisito(agencia_id, campos, cur=cur)
            vistos.add(int(creado["id"]))
            por_id[int(creado["id"])] = creado
            por_clave[clave] = creado
            creados += 1

    scrub = _scrub_requisitos_duplicados(
        agencia_id,
        cfg_id,
        por_id,
        ids_conservar=vistos,
        cur=cur,
    )
    desactivados = int(scrub.get("desactivados") or 0)

    # Desactivar activos que ya no vienen en la carga rápida (si hubo items).
    if items:
        for rid, row in list(por_id.items()):
            if rid in vistos:
                continue
            if row.get("chatbot_configuracion_id") != cfg_id:
                continue
            if row.get("activo"):
                db.actualizar_requisito(agencia_id, rid, {"activo": False}, cur=cur)
                desactivados += 1

    return {"creados": creados, "actualizados": actualizados, "desactivados": desactivados}


def _sincronizar_beneficios(
    agencia_id: int,
    cfg_id: int,
    items: List[Dict[str, Any]],
    *,
    tipo_default: str,
    cur,
) -> Dict[str, int]:
    from service_chatbot_carga_informacion import (
        _ETIQUETAS_TEMA_BENEFICIO,
        _clave_dedupe_beneficio,
        _descripcion_requisito_limpia,
        _nombre_beneficio_parece_descripcion,
        _nombre_item_limpio,
        _scrub_beneficios_duplicados,
        _tema_beneficio_carga,
    )

    existentes = db.listar_beneficios(
        agencia_id,
        chatbot_configuracion_id=cfg_id,
        incluir_globales=False,
        solo_activos=False,
        cur=cur,
    )
    por_id = {int(r["id"]): r for r in existentes if r.get("id")}
    por_clave: Dict[str, Dict[str, Any]] = {}
    for r in existentes:
        clave = _clave_dedupe_beneficio(
            str(r.get("tipo") or tipo_default),
            str(r.get("nombre") or ""),
            str(
                r.get("descripcion_corta")
                or r.get("texto_autorizado")
                or ""
            ),
        )
        if clave and not clave.endswith(":") and clave != "tema:junk_money":
            por_clave[clave] = r
    usados = {str(r.get("codigo")) for r in existentes if r.get("codigo")}
    vistos: Set[int] = set()
    creados = actualizados = 0
    tipo_target = tipo_default

    for idx, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        if item.get("activo") is False:
            continue
        nombre = _nombre_item_limpio(str(item.get("nombre") or "").strip())
        if not nombre:
            continue
        tipo = str(item.get("tipo") or tipo_target).lower()
        desc = _descripcion_requisito_limpia(nombre, item.get("descripcion")) or None
        tema = _tema_beneficio_carga(nombre, desc)
        if tema == "junk_money":
            continue
        if tema and _nombre_beneficio_parece_descripcion(nombre):
            if not desc:
                desc = _descripcion_requisito_limpia(
                    _ETIQUETAS_TEMA_BENEFICIO.get(tema, nombre), nombre
                ) or None
            nombre = _ETIQUETAS_TEMA_BENEFICIO.get(tema, nombre[:80])
        if tema and tema.startswith("bono_"):
            tipo = "bono"
        campos = {
            "nombre": nombre[:160],
            "descripcion_corta": desc,
            "texto_autorizado": desc,
            "tipo": tipo,
            "activo": True,
            "permitir_mencion_automatica": True,
        }
        if item.get("valor") not in (None, ""):
            campos["valor"] = item.get("valor")
        if item.get("moneda"):
            campos["moneda"] = str(item.get("moneda"))[:10]
        if "requiere_confirmacion_humana" in item or tipo == "bono":
            campos["requiere_validacion_humana"] = bool(
                item.get("requiere_confirmacion_humana") or tipo == "bono"
            )

        item_id = item.get("id")
        clave = _clave_dedupe_beneficio(tipo, nombre, desc)
        hit = por_id.get(int(item_id)) if item_id else por_clave.get(clave)
        if hit and int(hit["id"]) in por_id:
            db.actualizar_beneficio(agencia_id, int(hit["id"]), campos, cur=cur)
            vistos.add(int(hit["id"]))
            merged = {**hit, **campos, "id": hit["id"]}
            por_id[int(hit["id"])] = merged
            por_clave[clave] = merged
            actualizados += 1
        else:
            codigo = item.get("codigo") or _slug_unico(nombre, usados, tipo)
            campos.update(
                {
                    "codigo": codigo,
                    "chatbot_configuracion_id": cfg_id,
                }
            )
            creado = db.crear_beneficio(agencia_id, campos, cur=cur)
            vistos.add(int(creado["id"]))
            por_id[int(creado["id"])] = creado
            por_clave[clave] = creado
            creados += 1

    scrub = _scrub_beneficios_duplicados(
        agencia_id,
        cfg_id,
        por_id,
        ids_conservar=vistos,
        cur=cur,
    )
    desactivados = int(scrub.get("desactivados") or 0)

    if tipo_default == "beneficio":
        tipos_sync = {
            "beneficio",
            "incentivo",
            "capacitacion",
            "acompanamiento",
            "acompañamiento",
        }
    else:
        tipos_sync = {tipo_default, "incentivo"}

    if items:
        for bid, row in list(por_id.items()):
            if bid in vistos:
                continue
            if row.get("chatbot_configuracion_id") != cfg_id:
                continue
            if str(row.get("tipo") or "").lower() not in tipos_sync:
                continue
            if row.get("activo"):
                db.actualizar_beneficio(agencia_id, bid, {"activo": False}, cur=cur)
                desactivados += 1

    return {"creados": creados, "actualizados": actualizados, "desactivados": desactivados}


def _sincronizar_faq(
    agencia_id: int,
    cfg_id: int,
    items: List[Dict[str, Any]],
    *,
    cur,
) -> Dict[str, int]:
    existentes = db.listar_faqs(
        agencia_id,
        chatbot_configuracion_id=cfg_id,
        incluir_globales=False,
        solo_activos=False,
        cur=cur,
    )
    por_id = {int(r["id"]): r for r in existentes if r.get("id")}
    usados = {str(r.get("codigo")) for r in existentes if r.get("codigo")}
    vistos: Set[int] = set()
    creados = actualizados = 0

    for idx, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        if item.get("activo") is False:
            continue
        pregunta = str(item.get("pregunta") or "").strip()
        respuesta = str(item.get("respuesta") or "").strip()
        if not pregunta or not respuesta:
            continue
        campos = {
            "pregunta": pregunta,
            "respuesta_corta": respuesta[:300],
            "respuesta_completa": respuesta,
            "prioridad": max(0, min(100, 100 - idx)),
            "activo": True,
        }
        item_id = item.get("id")
        if item_id and int(item_id) in por_id:
            db.actualizar_faq(agencia_id, int(item_id), campos, cur=cur)
            vistos.add(int(item_id))
            actualizados += 1
        else:
            codigo = item.get("codigo") or _slug_unico(pregunta, usados, "faq")
            campos.update(
                {
                    "codigo": codigo,
                    "chatbot_configuracion_id": cfg_id,
                    "categoria": "general",
                    "fuente": "configuracion_rapida",
                }
            )
            creado = db.crear_faq(agencia_id, campos, cur=cur)
            vistos.add(int(creado["id"]))
            creados += 1

    desactivados = 0
    for fid, row in por_id.items():
        if fid in vistos:
            continue
        if row.get("chatbot_configuracion_id") != cfg_id:
            continue
        if row.get("activo"):
            db.actualizar_faq(agencia_id, fid, {"activo": False}, cur=cur)
            desactivados += 1

    return {"creados": creados, "actualizados": actualizados, "desactivados": desactivados}


def _guardar_recurso_solicitud(
    agencia_id: int,
    cfg_id: int,
    solicitud: Dict[str, Any],
    *,
    cur,
) -> Optional[Dict[str, Any]]:
    url = _url_real((solicitud or {}).get("url"))
    texto = str((solicitud or {}).get("texto_boton") or "Completar solicitud").strip()
    existente = db.obtener_recurso_por_codigo(
        agencia_id,
        CODIGO_RECURSO_SOLICITUD,
        chatbot_configuracion_id=cfg_id,
        cur=cur,
    )
    if not url:
        if existente and existente.get("activo"):
            return db.actualizar_recurso(
                agencia_id, int(existente["id"]), {"activo": False}, cur=cur
            )
        return None

    campos = {
        "nombre": "Solicitud principal",
        "tipo": "solicitud",
        "url_template": url,
        "texto_boton": texto[:120],
        "activo": True,
        "abrir_externo": True,
        "chatbot_configuracion_id": cfg_id,
    }
    if existente:
        return db.actualizar_recurso(agencia_id, int(existente["id"]), campos, cur=cur)
    campos["codigo"] = CODIGO_RECURSO_SOLICITUD
    return db.crear_recurso(agencia_id, campos, cur=cur)


def _asegurar_flujo_conversion(
    agencia_id: int,
    cfg_id: int,
    *,
    incluir_evidencias: bool,
    cur,
) -> Dict[str, Any]:
    flujos = db.listar_flujos(
        agencia_id,
        chatbot_configuracion_id=cfg_id,
        tipo_flujo="conversion",
        solo_activos=False,
        cur=cur,
    )
    flujo = next(
        (f for f in flujos if f.get("codigo") == CODIGO_FLUJO_CONVERSION),
        None,
    )
    recurso = db.obtener_recurso_por_codigo(
        agencia_id,
        CODIGO_RECURSO_SOLICITUD,
        chatbot_configuracion_id=cfg_id,
        cur=cur,
    )
    activo = bool(recurso and _url_real(recurso.get("url_template")))

    if not flujo:
        flujo = db.crear_flujo(
            agencia_id,
            {
                "chatbot_configuracion_id": cfg_id,
                "codigo": CODIGO_FLUJO_CONVERSION,
                "nombre": "Ingreso de aspirante",
                "tipo_flujo": "conversion",
                "descripcion": "Flujo predeterminado de configuración rápida",
                "estado_inicial": "inicio",
                "estado_final": "escalado_humano",
                "activo": activo,
            },
            cur=cur,
        )
        for paso in _pasos_conversion(
            incluir_evidencias=incluir_evidencias,
            codigo_recurso=CODIGO_RECURSO_SOLICITUD,
        ):
            paso["flujo_id"] = flujo["id"]
            db.crear_flujo_paso(agencia_id, paso, cur=cur)
        return flujo

    db.actualizar_flujo(agencia_id, int(flujo["id"]), {"activo": activo}, cur=cur)
    pasos = db.listar_flujo_pasos(
        agencia_id, int(flujo["id"]), solo_activos=False, cur=cur
    )
    por_codigo = {p.get("codigo"): p for p in pasos}
    deseados = {
        p["codigo"]: p
        for p in _pasos_conversion(
            incluir_evidencias=incluir_evidencias,
            codigo_recurso=CODIGO_RECURSO_SOLICITUD,
        )
    }
    # Crear faltantes; no reemplazar personalizados.
    for codigo, paso in deseados.items():
        if codigo in por_codigo:
            if codigo == "enviar_solicitud":
                db.actualizar_flujo_paso(
                    agencia_id,
                    int(por_codigo[codigo]["id"]),
                    {
                        "configuracion": {"codigo_recurso": CODIGO_RECURSO_SOLICITUD},
                        "activo": True,
                    },
                    cur=cur,
                )
            continue
        paso["flujo_id"] = flujo["id"]
        db.crear_flujo_paso(agencia_id, paso, cur=cur)

    # Desactivar evidencias si el usuario las apagó (no borrar).
    for codigo in ("solicitar_evidencias", "confirmar_evidencias"):
        if codigo in por_codigo and codigo not in deseados:
            db.actualizar_flujo_paso(
                agencia_id, int(por_codigo[codigo]["id"]), {"activo": False}, cur=cur
            )
        elif codigo in por_codigo and codigo in deseados:
            db.actualizar_flujo_paso(
                agencia_id, int(por_codigo[codigo]["id"]), {"activo": True}, cur=cur
            )

    return db.obtener_flujo(agencia_id, int(flujo["id"]), cur=cur) or flujo


def _sincronizar_evidencias(
    agencia_id: int,
    flujo_id: int,
    evidencias: Dict[str, Any],
    *,
    cur,
) -> None:
    activo = bool((evidencias or {}).get("activo"))
    pruebas = db.listar_pruebas_live(
        agencia_id, flujo_id=flujo_id, solo_activas=False, cur=cur
    )
    prueba = next(
        (p for p in pruebas if p.get("codigo") == CODIGO_PRUEBA_CONVERSION),
        pruebas[0] if pruebas else None,
    )

    if not activo:
        if prueba and prueba.get("activo"):
            db.actualizar_prueba_live(
                agencia_id, int(prueba["id"]), {"activo": False}, cur=cur
            )
        return

    instrucciones = str((evidencias or {}).get("instrucciones") or "").strip()
    campos_prueba = {
        "flujo_id": flujo_id,
        "codigo": CODIGO_PRUEBA_CONVERSION,
        "nombre": "Evidencias post-solicitud",
        "duracion_minima_minutos": 0,
        "cantidad_batallas": 0,
        "requiere_agendamiento": False,
        "zona_horaria": "America/Bogota",
        "plazo_evidencias_horas": 72,
        "permite_reintento": True,
        "maximo_reintentos": 2,
        "instrucciones_despues": instrucciones or None,
        "activo": True,
    }
    if prueba:
        db.actualizar_prueba_live(agencia_id, int(prueba["id"]), campos_prueba, cur=cur)
        prueba_id = int(prueba["id"])
    else:
        creada = db.crear_prueba_live(agencia_id, campos_prueba, cur=cur)
        prueba_id = int(creada["id"])

    deseadas: List[Dict[str, Any]] = []
    if evidencias.get("pedir_batalla"):
        deseadas.append(
            {
                "codigo": "captura_batalla",
                "nombre": "Captura de batalla",
                "tipo_evidencia": "imagen",
                "momento_requerido": "despues",
                "obligatoria": True,
                "orden": 1,
            }
        )
    if evidencias.get("pedir_mejores_momentos"):
        deseadas.append(
            {
                "codigo": "mejores_momentos",
                "nombre": "Capturas de mejores momentos",
                "tipo_evidencia": "imagen",
                "momento_requerido": "despues",
                "obligatoria": False,
                "orden": 2,
            }
        )
    cantidad = int(evidencias.get("cantidad") or 0)
    while len(deseadas) < max(0, cantidad):
        n = len(deseadas) + 1
        deseadas.append(
            {
                "codigo": f"evidencia_{n}",
                "nombre": f"Evidencia {n}",
                "tipo_evidencia": "imagen",
                "momento_requerido": "despues",
                "obligatoria": n == 1,
                "orden": n,
            }
        )

    existentes = db.listar_evidencias_requeridas(
        agencia_id, prueba_id, solo_activas=False, cur=cur
    )
    por_codigo = {e.get("codigo"): e for e in existentes}
    activos_codigos = {d["codigo"] for d in deseadas}

    for d in deseadas:
        if d["codigo"] in por_codigo:
            db.actualizar_evidencia_requerida(
                agencia_id,
                int(por_codigo[d["codigo"]]["id"]),
                {
                    "nombre": d["nombre"],
                    "activo": True,
                    "obligatoria": d["obligatoria"],
                    "orden": d["orden"],
                    "descripcion": instrucciones or None,
                },
                cur=cur,
            )
        else:
            d["prueba_live_id"] = prueba_id
            d["descripcion"] = instrucciones or None
            d["activo"] = True
            db.crear_evidencia_requerida(agencia_id, d, cur=cur)

    for codigo, row in por_codigo.items():
        if codigo not in activos_codigos and row.get("activo"):
            db.actualizar_evidencia_requerida(
                agencia_id, int(row["id"]), {"activo": False}, cur=cur
            )


def _guardar_contacto_humano(
    agencia_id: int,
    cfg_id: int,
    contacto: Dict[str, Any],
    *,
    cur,
) -> None:
    reglas = db.listar_reglas_escalamiento(
        agencia_id,
        chatbot_configuracion_id=cfg_id,
        solo_activas=False,
        cur=cur,
    )
    regla = next(
        (
            r
            for r in reglas
            if (r.get("evento") or "")
            in {"solicitud_humano", "transferir_humano", "escalar"}
        ),
        None,
    )
    activo = bool((contacto or {}).get("activo", True))
    campos = {
        "chatbot_configuracion_id": cfg_id,
        "evento": "solicitud_humano",
        "descripcion": "Contacto humano (configuración rápida)",
        "prioridad": "alta",
        "equipo_destino": str((contacto or {}).get("equipo_destino") or "").strip()
        or "equipo_captacion",
        "canal_destino": "panel",
        "mensaje_usuario": str((contacto or {}).get("mensaje_usuario") or "").strip()
        or "Te conectaré con una persona del equipo para continuar.",
        "estado_destino": "escalado_humano",
        "activo": activo,
        "orden": 1,
    }
    if regla:
        db.actualizar_regla_escalamiento(agencia_id, int(regla["id"]), campos, cur=cur)
    else:
        db.crear_regla_escalamiento(agencia_id, campos, cur=cur)


def guardar_configuracion_rapida(
    agencia_id: int,
    chatbot_configuracion_id: int,
    payload: Dict[str, Any],
    *,
    cur=None,
) -> Dict[str, Any]:
    datos = dict(payload or {})
    general = dict(datos.get("general") or {})
    solicitud = dict(datos.get("solicitud") or {})
    contacto = dict(datos.get("contacto_humano") or {})
    contenido = dict(datos.get("contenido") or {})
    evidencias = dict(datos.get("evidencias") or {})

    with db._cursor(cur) as c:
        db._exige_configuracion(agencia_id, chatbot_configuracion_id, cur=c)

        asistente = db.obtener_asistente_por_config(
            agencia_id, chatbot_configuracion_id, cur=c
        )
        if not asistente:
            # Asegura base mínima sin activar.
            aplicar_plantilla_asistente_conversacional(
                agencia_id,
                chatbot_configuracion_id,
                completar_solo_faltantes=True,
                activar_asistente=False,
                cur=c,
            )
            asistente = db.obtener_asistente_por_config(
                agencia_id, chatbot_configuracion_id, cur=c
            )

        campos_asistente: Dict[str, Any] = {}
        if "nombre_asistente" in general:
            campos_asistente["nombre_asistente"] = (
                str(general.get("nombre_asistente") or "").strip() or "Asistente virtual"
            )
        if "descripcion_agencia" in general:
            campos_asistente["descripcion_agencia"] = (
                str(general.get("descripcion_agencia") or "").strip() or None
            )
        if "presentacion_inicial" in general:
            campos_asistente["presentacion_inicial"] = (
                str(general.get("presentacion_inicial") or "").strip() or None
            )
        if "presentacion_informativo" in general:
            campos_asistente["presentacion_informativo"] = (
                str(general.get("presentacion_informativo") or "").strip() or None
            )
        if "presentacion_inteligente" in general:
            campos_asistente["presentacion_inteligente"] = (
                str(general.get("presentacion_inteligente") or "").strip() or None
            )
        if "tono" in general and general.get("tono"):
            campos_asistente["tono"] = str(general.get("tono"))
        if "modo_informativo_activo" in general:
            campos_asistente["modo_informativo_activo"] = bool(
                general.get("modo_informativo_activo")
            )
        if "modo_conversion_activo" in general:
            campos_asistente["modo_conversion_activo"] = bool(
                general.get("modo_conversion_activo")
            )
            if campos_asistente["modo_conversion_activo"]:
                campos_asistente["modo_predeterminado"] = (
                    "conversion"
                    if not general.get("modo_informativo_activo", True)
                    else "informativo"
                )

        if campos_asistente and asistente:
            db.actualizar_asistente(
                agencia_id, int(asistente["id"]), campos_asistente, cur=c
            )

        sync_req = _sincronizar_requisitos(
            agencia_id, chatbot_configuracion_id, contenido.get("requisitos") or [], cur=c
        )
        sync_ben = _sincronizar_beneficios(
            agencia_id,
            chatbot_configuracion_id,
            contenido.get("beneficios") or [],
            tipo_default="beneficio",
            cur=c,
        )
        sync_bon = _sincronizar_beneficios(
            agencia_id,
            chatbot_configuracion_id,
            contenido.get("bonos") or [],
            tipo_default="bono",
            cur=c,
        )
        sync_faq = _sincronizar_faq(
            agencia_id, chatbot_configuracion_id, contenido.get("faq") or [], cur=c
        )

        _guardar_recurso_solicitud(
            agencia_id, chatbot_configuracion_id, solicitud, cur=c
        )
        _guardar_contacto_humano(
            agencia_id, chatbot_configuracion_id, contacto, cur=c
        )

        flujo = _asegurar_flujo_conversion(
            agencia_id,
            chatbot_configuracion_id,
            incluir_evidencias=bool(evidencias.get("activo")),
            cur=c,
        )
        _sincronizar_evidencias(
            agencia_id, int(flujo["id"]), evidencias, cur=c
        )

        dto = obtener_configuracion_rapida(
            agencia_id, chatbot_configuracion_id, cur=c
        )

        logger.info(
            "[CONFIG_RAPIDA] agencia_id=%s chatbot_configuracion_id=%s accion=guardar "
            "requisitos_creados=%s requisitos_actualizados=%s beneficios_creados=%s "
            "faq_creadas=%s flujo_conversion_id=%s resultado=ok",
            agencia_id,
            chatbot_configuracion_id,
            sync_req["creados"],
            sync_req["actualizados"],
            sync_ben["creados"] + sync_bon["creados"],
            sync_faq["creados"],
            flujo.get("id"),
        )
        return {
            "configuracion": dto,
            "sincronizacion": {
                "requisitos": sync_req,
                "beneficios": sync_ben,
                "bonos": sync_bon,
                "faq": sync_faq,
            },
            "estado_configuracion": dto.get("estado_configuracion"),
        }


def publicar_asistente(
    agencia_id: int,
    chatbot_configuracion_id: int,
    *,
    forzar: bool = False,
    cur=None,
) -> Dict[str, Any]:
    with db._cursor(cur) as c:
        estado = obtener_estado_configuracion_conversacional(
            agencia_id, chatbot_configuracion_id, cur=c
        )
        if not estado.get("lista_para_publicar") and not forzar:
            raise ConversacionalError(
                "La configuración está incompleta para publicar.",
                {"estado": estado},
            )
        asistente = db.obtener_asistente_por_config(
            agencia_id, chatbot_configuracion_id, cur=c
        )
        if not asistente:
            raise ConversacionalError("Asistente no encontrado")
        actualizado = db.actualizar_asistente(
            agencia_id, int(asistente["id"]), {"activo": True}, cur=c
        )
        estado = obtener_estado_configuracion_conversacional(
            agencia_id, chatbot_configuracion_id, cur=c
        )
        return {
            "asistente": actualizado,
            "estado_configuracion": estado,
            "motor_sin_cambiar": True,
        }


def despublicar_asistente(
    agencia_id: int, chatbot_configuracion_id: int, *, cur=None
) -> Dict[str, Any]:
    with db._cursor(cur) as c:
        asistente = db.obtener_asistente_por_config(
            agencia_id, chatbot_configuracion_id, cur=c
        )
        if not asistente:
            raise ConversacionalError("Asistente no encontrado")
        actualizado = db.actualizar_asistente(
            agencia_id, int(asistente["id"]), {"activo": False}, cur=c
        )
        estado = obtener_estado_configuracion_conversacional(
            agencia_id, chatbot_configuracion_id, cur=c
        )
        return {"asistente": actualizado, "estado_configuracion": estado}
