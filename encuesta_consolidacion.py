"""
Consolidación compartida de la encuesta inicial (portal y WhatsApp).

Independiente de FastAPI / BackgroundTasks / JSONResponse.
No importa main_webhook (evita dependencia circular).
"""
from __future__ import annotations

import json
import traceback
from typing import Any, Callable, Dict, Optional

import phonenumbers
from phonenumbers import geocoder, region_code_for_number

from DataBase import (
    buscar_usuario_por_telefono,
    get_connection_context,
    marcar_encuesta_completada,
)
from portal_access_tokens import generar_url_portal
from utils_aspirantes import registrar_cambio_estado

VARIABLE_PAIS_ID = 20
ORIGEN_PORTAL = "portal-aspirante"

PAISES_SISTEMA = {
    "AR": {"id": 119, "nombre": "Argentina"},
    "BO": {"id": 120, "nombre": "Bolivia"},
    "CL": {"id": 121, "nombre": "Chile"},
    "CO": {"id": 122, "nombre": "Colombia"},
    "CR": {"id": 123, "nombre": "Costa Rica"},
    "CU": {"id": 124, "nombre": "Cuba"},
    "EC": {"id": 125, "nombre": "Ecuador"},
    "SV": {"id": 126, "nombre": "El Salvador"},
    "GT": {"id": 127, "nombre": "Guatemala"},
    "HN": {"id": 128, "nombre": "Honduras"},
    "MX": {"id": 82, "nombre": "México"},
    "NI": {"id": 83, "nombre": "Nicaragua"},
    "PA": {"id": 84, "nombre": "Panamá"},
    "PY": {"id": 85, "nombre": "Paraguay"},
    "PE": {"id": 86, "nombre": "Perú"},
    "PR": {"id": 87, "nombre": "Puerto Rico"},
    "DO": {"id": 88, "nombre": "República Dominicana"},
    "UY": {"id": 89, "nombre": "Uruguay"},
    "VE": {"id": 90, "nombre": "Venezuela"},
}


def obtener_datos_pais(telefono_webhook: str) -> dict:
    """Detecta país por indicativo telefónico (misma lógica que el portal)."""
    try:
        numero_limpio = (telefono_webhook or "").strip()
        if not numero_limpio.startswith("+"):
            numero_limpio = f"+{numero_limpio}"

        parsed_number = phonenumbers.parse(numero_limpio, None)

        if not phonenumbers.is_valid_number(parsed_number):
            return {"error": True, "mensaje": "Número inválido"}

        codigo_iso = region_code_for_number(parsed_number)
        if not codigo_iso:
            codigo_iso = phonenumbers.region_code_for_country_code(parsed_number.country_code)
        if not codigo_iso:
            return {"error": True, "mensaje": "No se pudo detectar el país"}

        indicativo = f"+{parsed_number.country_code}"

        if codigo_iso in PAISES_SISTEMA:
            pais = PAISES_SISTEMA[codigo_iso]
            return {
                "id_pais": pais["id"],
                "nombre_pais": pais["nombre"],
                "indicativo": indicativo,
                "iso": codigo_iso,
                "es_otro": False,
            }

        nombre_real = geocoder.country_name_for_number(parsed_number, "es")
        return {
            "id_pais": None,
            "nombre_pais": "Otro",
            "pais_real_detectado": nombre_real,
            "indicativo": indicativo,
            "iso": codigo_iso,
            "es_otro": True,
        }
    except Exception as e:
        return {"error": True, "mensaje": f"Error procesando número: {str(e)}"}


def _normalizar_respuestas_entrada(respuestas: Optional[dict]) -> Dict[int, str]:
    out: Dict[int, str] = {}
    if not respuestas:
        return out
    for key, valor in respuestas.items():
        if isinstance(key, str) and key.isdigit():
            key_int = int(key)
        elif isinstance(key, int):
            key_int = key
        else:
            continue
        out[key_int] = str(valor).strip() if valor is not None else ""
    return out


def _label_valor_opcion(cur, valor_id: int) -> Optional[str]:
    cur.execute(
        """
        SELECT label
        FROM diagnostico_variable_valor
        WHERE id = %s
        LIMIT 1
        """,
        (valor_id,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _origen_cambio_desde_origen(origen: Optional[str]) -> str:
    if (origen or "").strip().lower() == "whatsapp":
        return "encuesta_whatsapp"
    return "encuesta_link"


def _aplicar_pais(
    respuestas_dict: Dict[int, str],
    numero: str,
) -> Optional[str]:
    """Infiere país solo si no hay respuesta explícita."""
    pais_texto: Optional[str] = None
    tiene_pais_explicito = bool(respuestas_dict.get(VARIABLE_PAIS_ID))

    if not tiene_pais_explicito:
        datos_pais = obtener_datos_pais(numero)
        if not datos_pais.get("error"):
            pais_id = datos_pais.get("id_pais")
            if datos_pais.get("es_otro"):
                pais_texto = (
                    datos_pais.get("pais_real_detectado") or datos_pais.get("nombre_pais")
                )
            else:
                pais_texto = datos_pais.get("nombre_pais")
            if pais_id is not None:
                respuestas_dict[VARIABLE_PAIS_ID] = str(pais_id)
        return pais_texto

    valor_pais = respuestas_dict.get(VARIABLE_PAIS_ID, "")
    if valor_pais.isdigit():
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                pais_texto = _label_valor_opcion(cur, int(valor_pais))
    return pais_texto


def _mensaje_final_default(nombre: Optional[str], url_info: Optional[str]) -> str:
    saludo = f"¡Gracias, *{nombre}*! 🙌" if nombre else "¡Gracias! 🙌"
    cuerpo = (
        f"✅ {saludo}\n\n"
        "Ya recibimos tu información y nuestro equipo la está evaluando.\n\n"
        "⏳ El diagnóstico se enviará en las próximas horas."
    )
    if url_info:
        cuerpo += f"\n\n🔗 {url_info}"
    return cuerpo


def _upsert_trazabilidad_encuesta(
    cur,
    aspirante_id: int,
    respuestas_dict: Dict[int, str],
) -> None:
    """Idempotente: actualiza la fila más reciente o inserta una nueva."""
    cur.execute(
        """
        SELECT id
        FROM aspirantes_encuesta_inicial
        WHERE aspirante_id = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (aspirante_id,),
    )
    row = cur.fetchone()
    payload_json = json.dumps(respuestas_dict, ensure_ascii=False)
    n_resp = len(respuestas_dict)

    if row:
        cur.execute(
            """
            UPDATE aspirantes_encuesta_inicial
            SET respuestas_json = %s::jsonb,
                fecha_fin = now(),
                completada = true,
                abandonada = false,
                preguntas_respondidas = %s,
                sincronizado = true,
                fecha_sincronizacion = now(),
                updated_at = now()
            WHERE id = %s
            """,
            (payload_json, n_resp, row[0]),
        )
    else:
        cur.execute(
            """
            INSERT INTO aspirantes_encuesta_inicial (
                aspirante_id,
                respuestas_json,
                fecha_inicio,
                fecha_fin,
                completada,
                abandonada,
                preguntas_respondidas,
                sincronizado,
                fecha_sincronizacion,
                created_at,
                updated_at
            )
            VALUES (
                %s, %s::jsonb, now(), now(), true, false,
                %s, true, now(), now(), now()
            )
            """,
            (aspirante_id, payload_json, n_resp),
        )


def consolidar_encuesta_inicial(
    numero: str,
    respuestas: Optional[dict],
    meta: Optional[Dict[str, Any]] = None,
    origen: str = "whatsapp",
    construir_mensaje_final: Optional[Callable[..., str]] = None,
) -> Dict[str, Any]:
    """
    Persiste respuestas, trazabilidad y cambio de estado.
    Idempotente ante reintentos. No envía mensajes.
    """
    try:
        respuestas_dict = _normalizar_respuestas_entrada(respuestas)
        pais_texto = _aplicar_pais(respuestas_dict, numero)

        try:
            usuario_bd = buscar_usuario_por_telefono(numero)
            nombre_usuario = usuario_bd.get("nombre") if usuario_bd else None
            aspirante_id = usuario_bd.get("id") if usuario_bd else None
        except Exception as e:
            print(f"⚠️ Error obteniendo usuario {numero}: {e}")
            nombre_usuario = None
            aspirante_id = None

        if not aspirante_id:
            return {"ok": False, "error": "No se encontró aspirante para ese número"}

        if not respuestas_dict:
            return {"ok": False, "error": "No hay respuestas para consolidar"}

        zona_horaria = None
        if meta and isinstance(meta, dict):
            zona_horaria = meta.get("zona_horaria")

        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, campo_db
                    FROM diagnostico_variable
                    WHERE migrado = true
                      AND COALESCE(activa, true) = true
                    """
                )
                variables = {row[0]: row[1] for row in cur.fetchall()}

                for pregunta_id, valor in respuestas_dict.items():
                    campo_db = variables.get(pregunta_id)

                    if isinstance(valor, str) and valor.isdigit():
                        valor_int = int(valor)
                        cur.execute(
                            """
                            INSERT INTO diagnostico_score_variable
                                (aspirante_id, variable_id, valor_id)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (aspirante_id, variable_id)
                            DO UPDATE SET valor_id = EXCLUDED.valor_id
                            """,
                            (aspirante_id, pregunta_id, valor_int),
                        )

                    if campo_db:
                        if not campo_db.replace("_", "").isalnum():
                            continue
                        cur.execute(
                            f"""
                            UPDATE aspirantes_perfil
                            SET {campo_db} = %s
                            WHERE aspirante_id = %s
                            """,
                            (valor, aspirante_id),
                        )
                        if campo_db == "nombre":
                            nombre_usuario = valor

                if pais_texto:
                    cur.execute(
                        """
                        UPDATE aspirantes_perfil
                        SET pais_texto = %s
                        WHERE aspirante_id = %s
                        """,
                        (pais_texto, aspirante_id),
                    )

                if zona_horaria:
                    cur.execute(
                        """
                        UPDATE aspirantes_perfil
                        SET zona_horaria = %s
                        WHERE aspirante_id = %s
                        """,
                        (zona_horaria, aspirante_id),
                    )

                _upsert_trazabilidad_encuesta(cur, aspirante_id, respuestas_dict)
                conn.commit()

        # Solo después del commit exitoso
        marcar_encuesta_completada(numero)

        # Idempotente: no cambia si ya está en estado 3
        registrar_cambio_estado(
            aspirante_id=aspirante_id,
            nuevo_estado_id=3,
            usuario_id=None,
            origen_cambio=_origen_cambio_desde_origen(origen),
            observacion="Aspirante pasa a Evaluación al completar la encuesta inicial",
        )

        portal_data = generar_url_portal(
            tipo_portal="aspirante",
            aspirante_id=aspirante_id,
            creador_id=None,
            origen="encuesta",
        )
        url_info = portal_data["url"]

        builder = construir_mensaje_final or _mensaje_final_default
        mensaje_final = builder(nombre=nombre_usuario, url_info=url_info)

        return {
            "ok": True,
            "aspirante_id": aspirante_id,
            "nombre": nombre_usuario,
            "pais_texto": pais_texto,
            "zona_horaria": zona_horaria,
            "url_portal": url_info,
            "mensaje_final": mensaje_final,
        }

    except Exception as e:
        print(f"❌ Error en consolidar_encuesta_inicial: {e}")
        traceback.print_exc()
        return {"ok": False, "error": str(e)}
