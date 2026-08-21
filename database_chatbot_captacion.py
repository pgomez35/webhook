"""
Capa de datos — Chatbot de captación (schema chatbot).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from psycopg2.extras import RealDictCursor, Json

from chatbot_captacion_logic import (
    ETAPA_INICIO,
    enmascarar_telefono,
    nombre_agencia_desde_cuenta,
    normalizar_codigo_agencia,
)
from DataBase import get_connection_chatbot_context, get_connection_public_context

logger = logging.getLogger("uvicorn.error")

# Re-export para compatibilidad
__all_helpers__ = (
    enmascarar_telefono,
    nombre_agencia_desde_cuenta,
    normalizar_codigo_agencia,
)

PRODUCTOS_CONOCIDOS = frozenset({"talentum_manager", "chatbot"})


def normalizar_product_type(raw: Any) -> str:
    """NULL / vacío → talentum_manager (compatibilidad)."""
    valor = (str(raw).strip().lower() if raw is not None else "") or "talentum_manager"
    return valor


def validar_producto_chatbot(product_type: str, whatsapp_account_id: int) -> None:
    """
    Defensa obligatoria antes de escribir en chatbot.agencias /
    chatbot.agencia_whatsapp_accounts.
    """
    pt = normalizar_product_type(product_type)
    if pt != "chatbot":
        raise ValueError(
            f"No se puede relacionar la cuenta {whatsapp_account_id} "
            f"con el producto chatbot porque product_type={pt}"
        )


def asegurar_agencia_chatbot_y_canal(
    whatsapp_account_id: int,
    subdominio: Optional[str] = None,
    business_name: Optional[str] = None,
    product_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Crea/actualiza chatbot.agencias y la relación con el canal WABA.
    Solo escribe si product_type == 'chatbot'.
    Idempotente. Una sola transacción (agencia + relación).
    """
    if not whatsapp_account_id:
        raise ValueError("whatsapp_account_id es obligatorio")

    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    id,
                    subdominio,
                    business_name,
                    status,
                    phone_number_id,
                    product_type
                FROM public.whatsapp_business_accounts
                WHERE id = %s
                LIMIT 1
                """,
                (whatsapp_account_id,),
            )
            cuenta = cur.fetchone()
            if not cuenta:
                raise ValueError(
                    f"No existe public.whatsapp_business_accounts.id={whatsapp_account_id}"
                )

            # Fuente de verdad: columna en public.whatsapp_business_accounts
            pt_db = normalizar_product_type(cuenta.get("product_type"))
            if product_type is not None:
                pt_arg = normalizar_product_type(product_type)
                if pt_arg != pt_db:
                    logger.warning(
                        "product_type argumento=%s difiere de DB=%s "
                        "whatsapp_account_id=%s; se usa DB",
                        pt_arg,
                        pt_db,
                        whatsapp_account_id,
                    )
            product_type_efectivo = pt_db

            if product_type_efectivo not in PRODUCTOS_CONOCIDOS:
                raise ValueError(
                    f"product_type desconocido='{product_type_efectivo}' "
                    f"para whatsapp_account_id={whatsapp_account_id}"
                )

            if product_type_efectivo != "chatbot":
                logger.info(
                    "omitir escritura chatbot: whatsapp_account_id=%s "
                    "phone_number_id=%s product_type=%s operacion=skip",
                    whatsapp_account_id,
                    cuenta.get("phone_number_id"),
                    product_type_efectivo,
                )
                print(
                    f"ℹ️ Chatbot omitido (product_type={product_type_efectivo}) "
                    f"whatsapp_account_id={whatsapp_account_id} "
                    f"phone_number_id={cuenta.get('phone_number_id')}"
                )
                return {
                    "skipped": True,
                    "product_type": product_type_efectivo,
                    "whatsapp_account_id": whatsapp_account_id,
                    "agencia_id": None,
                }

            validar_producto_chatbot(product_type_efectivo, whatsapp_account_id)

            sub = subdominio if subdominio is not None else cuenta.get("subdominio")
            bname = business_name if business_name is not None else cuenta.get("business_name")
            codigo = normalizar_codigo_agencia(sub, whatsapp_account_id)
            nombre = nombre_agencia_desde_cuenta(bname, sub, whatsapp_account_id)

            cur.execute(
                """
                INSERT INTO chatbot.agencias (nombre, codigo, estado)
                VALUES (%s, %s, 'activa')
                ON CONFLICT (codigo) DO UPDATE
                SET
                    nombre = CASE
                        WHEN chatbot.agencias.nombre LIKE 'Agencia WhatsApp %%'
                            THEN EXCLUDED.nombre
                        ELSE chatbot.agencias.nombre
                    END,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id, nombre, codigo, estado
                """,
                (nombre, codigo),
            )
            agencia = cur.fetchone()
            agencia_id = agencia["id"]

            cur.execute(
                """
                SELECT id, agencia_id, principal, activo
                FROM chatbot.agencia_whatsapp_accounts
                WHERE whatsapp_account_id = %s
                LIMIT 1
                """,
                (whatsapp_account_id,),
            )
            rel = cur.fetchone()
            if rel:
                if rel["agencia_id"] != agencia_id:
                    logger.warning(
                        "Canal whatsapp_account_id=%s ya ligado a agencia_id=%s "
                        "(intento agencia_id=%s). Se conserva la relación actual.",
                        whatsapp_account_id,
                        rel["agencia_id"],
                        agencia_id,
                    )
                    agencia_id = rel["agencia_id"]
                elif not rel["activo"]:
                    cur.execute(
                        """
                        UPDATE chatbot.agencia_whatsapp_accounts
                        SET activo = TRUE, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        (rel["id"],),
                    )
            else:
                cur.execute(
                    """
                    SELECT 1
                    FROM chatbot.agencia_whatsapp_accounts
                    WHERE agencia_id = %s AND principal = TRUE AND activo = TRUE
                    LIMIT 1
                    """,
                    (agencia_id,),
                )
                tiene_principal = cur.fetchone() is not None
                cur.execute(
                    """
                    INSERT INTO chatbot.agencia_whatsapp_accounts (
                        agencia_id, whatsapp_account_id, principal, activo
                    ) VALUES (%s, %s, %s, TRUE)
                    ON CONFLICT (whatsapp_account_id) DO NOTHING
                    """,
                    (agencia_id, whatsapp_account_id, not tiene_principal),
                )

            print(
                f"✅ Chatbot asegurado whatsapp_account_id={whatsapp_account_id} "
                f"phone_number_id={cuenta.get('phone_number_id')} "
                f"product_type=chatbot codigo={codigo} "
                f"chatbot_agencia_id={agencia_id} operacion=upsert"
            )
            return {
                "skipped": False,
                "product_type": "chatbot",
                "agencia_id": agencia_id,
                "whatsapp_account_id": whatsapp_account_id,
                "codigo": codigo,
            }


def obtener_cuenta_conectada_por_phone_id(phone_number_id: str) -> Optional[Dict[str, Any]]:
    with get_connection_public_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    id,
                    waba_id,
                    access_token,
                    phone_number,
                    phone_number_id,
                    business_name,
                    status,
                    subdominio,
                    onboarding_type,
                    coexistence_enabled,
                    business_id,
                    product_type
                FROM public.whatsapp_business_accounts
                WHERE phone_number_id = %s
                  AND status = 'connected'
                LIMIT 1
                """,
                (phone_number_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            data = dict(row)
            data["product_type"] = normalizar_product_type(data.get("product_type"))
            return data


def obtener_relacion_agencia_activa(whatsapp_account_id: int) -> Optional[Dict[str, Any]]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    aw.agencia_id,
                    aw.whatsapp_account_id,
                    aw.activo,
                    a.estado AS agencia_estado
                FROM chatbot.agencia_whatsapp_accounts aw
                INNER JOIN chatbot.agencias a ON a.id = aw.agencia_id
                WHERE aw.whatsapp_account_id = %s
                  AND aw.activo = TRUE
                  AND a.estado = 'activa'
                LIMIT 1
                """,
                (whatsapp_account_id,),
            )
            return cur.fetchone()


def obtener_relacion_agencia_canal(whatsapp_account_id: int) -> Optional[Dict[str, Any]]:
    """
    Relación canal↔agencia chatbot (activa o no).
    Sirve para distinguir 'sin relación' vs 'relación inactiva'.
    """
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    aw.agencia_id,
                    aw.whatsapp_account_id,
                    aw.activo,
                    a.estado AS agencia_estado
                FROM chatbot.agencia_whatsapp_accounts aw
                INNER JOIN chatbot.agencias a ON a.id = aw.agencia_id
                WHERE aw.whatsapp_account_id = %s
                LIMIT 1
                """,
                (whatsapp_account_id,),
            )
            return cur.fetchone()


def resolver_contexto_webhook(phone_number_id: str) -> Optional[Dict[str, Any]]:
    """
    Resuelve cuenta WABA conectada + agencia chatbot.
    Solo asegura escritura en schema chatbot si product_type=chatbot.
    """
    cuenta = obtener_cuenta_conectada_por_phone_id(phone_number_id)
    if not cuenta:
        return None

    whatsapp_account_id = cuenta["id"]
    product_type = normalizar_product_type(cuenta.get("product_type"))
    rel = obtener_relacion_agencia_activa(whatsapp_account_id)
    chatbot_agencia_id = None

    if rel:
        chatbot_agencia_id = rel["agencia_id"]
    elif product_type == "chatbot":
        asegurado = asegurar_agencia_chatbot_y_canal(
            whatsapp_account_id=whatsapp_account_id,
            subdominio=cuenta.get("subdominio"),
            business_name=cuenta.get("business_name"),
            product_type=product_type,
        )
        if not asegurado.get("skipped"):
            chatbot_agencia_id = asegurado.get("agencia_id")
    else:
        # talentum_manager / otro: no crear registros chatbot
        logger.info(
            "resolver_contexto_webhook: omitir asegurar chatbot "
            "whatsapp_account_id=%s product_type=%s",
            whatsapp_account_id,
            product_type,
        )

    return {
        "account_id": whatsapp_account_id,
        "product_type": product_type,
        "chatbot_agencia_id": chatbot_agencia_id,
        "access_token": cuenta["access_token"],
        "phone_number_id": cuenta["phone_number_id"],
        "tenant_name": "chatbot" if product_type == "chatbot" else cuenta.get("subdominio"),
        "business_name": cuenta.get("business_name"),
        "onboarding_type": cuenta.get("onboarding_type"),
        "coexistence_enabled": cuenta.get("coexistence_enabled"),
    }


def obtener_agencia_por_codigo(codigo: str) -> Optional[Dict[str, Any]]:
    # Misma normalización que el backfill: LOWER(TRIM(...))
    codigo_norm = (codigo or "").strip().lower()
    if not codigo_norm:
        return None
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, nombre, codigo, estado
                FROM chatbot.agencias
                WHERE LOWER(TRIM(codigo)) = LOWER(TRIM(%s))
                LIMIT 1
                """,
                (codigo_norm,),
            )
            return cur.fetchone()


def listar_cuentas_conectadas_por_subdominio(subdominio: str) -> List[Dict[str, Any]]:
    sub_norm = (subdominio or "").strip().lower()
    if not sub_norm:
        return []
    with get_connection_public_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    id, waba_id, phone_number, phone_number_id, business_name,
                    status, subdominio, onboarding_type, coexistence_enabled,
                    product_type
                FROM public.whatsapp_business_accounts
                WHERE LOWER(TRIM(subdominio)) = LOWER(TRIM(%s))
                  AND status = 'connected'
                ORDER BY COALESCE(connected_at, updated_at, created_at) DESC NULLS LAST, id DESC
                """,
                (sub_norm,),
            )
            return list(cur.fetchall() or [])


def resolver_agencia_administrativa(tenant_name: str) -> Dict[str, Any]:
    """
    Resuelve chatbot.agencias por request.state.tenant_name (= codigo).
    Normaliza con LOWER(TRIM(...)) igual que el poblado de chatbot.agencias.
    Si no existe, intenta asegurar desde WABAs del subdominio.
    """
    from fastapi import HTTPException

    tenant_norm = (tenant_name or "").strip().lower()
    if not tenant_norm:
        raise HTTPException(status_code=400, detail="No se pudo identificar el tenant.")

    agencia = obtener_agencia_por_codigo(tenant_norm)
    if agencia:
        return dict(agencia)

    cuentas = listar_cuentas_conectadas_por_subdominio(tenant_norm)
    if not cuentas:
        raise HTTPException(
            status_code=404,
            detail="No se encontró agencia de chatbot para este tenant.",
        )

    for cuenta in cuentas:
        pt = normalizar_product_type(cuenta.get("product_type"))
        if pt != "chatbot":
            continue
        asegurar_agencia_chatbot_y_canal(
            whatsapp_account_id=cuenta["id"],
            subdominio=cuenta.get("subdominio") or tenant_norm,
            business_name=cuenta.get("business_name"),
            product_type=pt,
        )

    agencia = obtener_agencia_por_codigo(tenant_norm)
    if not agencia:
        raise HTTPException(
            status_code=404,
            detail="No se pudo resolver la agencia de chatbot.",
        )
    return dict(agencia)


def _faqs_plain(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    faqs = data.get("preguntas_frecuentes") or []
    if isinstance(faqs, list):
        return [
            f.model_dump(mode="json") if hasattr(f, "model_dump") else dict(f)
            for f in faqs
        ]
    return []


def _recursos_plain(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    recursos = data.get("recursos_bienvenida") or []
    if isinstance(recursos, list):
        return [
            r.model_dump(mode="json") if hasattr(r, "model_dump") else dict(r)
            for r in recursos
        ]
    return []


def listar_plataformas_activas() -> List[Dict[str, Any]]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT codigo, nombre, activo, perfil_url_template,
                       created_at, updated_at
                FROM chatbot.plataformas
                WHERE activo = TRUE
                ORDER BY nombre ASC, codigo ASC
                """
            )
            return [dict(r) for r in (cur.fetchall() or [])]


def obtener_plataforma(codigo: str) -> Optional[Dict[str, Any]]:
    codigo_norm = (codigo or "").strip().lower()
    if not codigo_norm:
        return None
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT codigo, nombre, activo, perfil_url_template,
                       created_at, updated_at
                FROM chatbot.plataformas
                WHERE codigo = %s
                LIMIT 1
                """,
                (codigo_norm,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def obtener_agencia_por_id(agencia_id: int) -> Optional[Dict[str, Any]]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, nombre, codigo, estado,
                       mensaje_seleccion_configuracion,
                       seleccion_por_palabras_activa,
                       COALESCE(diagnostico_habilitado, FALSE) AS diagnostico_habilitado,
                       created_at, updated_at
                FROM chatbot.agencias
                WHERE id = %s
                LIMIT 1
                """,
                (agencia_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def actualizar_mensaje_seleccion_configuracion(
    agencia_id: int,
    mensaje: str,
    *,
    seleccion_por_palabras_activa: Optional[bool] = None,
) -> Dict[str, Any]:
    mensaje_norm = (mensaje or "").strip()
    if not mensaje_norm:
        raise ValueError("mensaje_seleccion_configuracion no puede estar vacío")
    if len(mensaje_norm) > 300:
        raise ValueError(
            "mensaje_seleccion_configuracion no puede superar 300 caracteres"
        )

    sets = [
        "mensaje_seleccion_configuracion = %s",
        "updated_at = CURRENT_TIMESTAMP",
    ]
    params: List[Any] = [mensaje_norm]
    if seleccion_por_palabras_activa is not None:
        sets.insert(1, "seleccion_por_palabras_activa = %s")
        params.append(bool(seleccion_por_palabras_activa))
    params.append(agencia_id)

    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                UPDATE chatbot.agencias
                SET {", ".join(sets)}
                WHERE id = %s
                RETURNING id, nombre, codigo, estado,
                          mensaje_seleccion_configuracion,
                          seleccion_por_palabras_activa,
                          COALESCE(diagnostico_habilitado, FALSE) AS diagnostico_habilitado,
                          created_at, updated_at
                """,
                params,
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Agencia no encontrada")
            return dict(row)


def listar_configuraciones(
    agencia_id: int,
    *,
    solo_activas: bool = False,
) -> List[Dict[str, Any]]:
    where = ["c.agencia_id = %s"]
    params: List[Any] = [agencia_id]
    if solo_activas:
        where.append("c.activo = TRUE")
    where_sql = " AND ".join(where)
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    c.*,
                    p.nombre AS plataforma_nombre
                FROM chatbot.chatbot_configuracion c
                LEFT JOIN chatbot.plataformas p
                    ON p.codigo = c.plataforma_codigo
                WHERE {where_sql}
                ORDER BY c.orden ASC NULLS LAST, c.id ASC
                """,
                params,
            )
            return [dict(r) for r in (cur.fetchall() or [])]


def listar_configuraciones_activas(agencia_id: int) -> List[Dict[str, Any]]:
    """Configuraciones activas ordenadas por orden, id (runtime WhatsApp)."""
    return listar_configuraciones(agencia_id, solo_activas=True)


def obtener_configuracion_por_id(
    agencia_id: int,
    configuracion_id: int,
    *,
    solo_activa: bool = False,
) -> Optional[Dict[str, Any]]:
    where = ["c.id = %s", "c.agencia_id = %s"]
    params: List[Any] = [configuracion_id, agencia_id]
    if solo_activa:
        where.append("c.activo = TRUE")
    where_sql = " AND ".join(where)
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    c.*,
                    p.nombre AS plataforma_nombre
                FROM chatbot.chatbot_configuracion c
                LEFT JOIN chatbot.plataformas p
                    ON p.codigo = c.plataforma_codigo
                WHERE {where_sql}
                LIMIT 1
                """,
                params,
            )
            row = cur.fetchone()
            return dict(row) if row else None


def obtener_configuracion_activa(agencia_id: int) -> Optional[Dict[str, Any]]:
    """
    Compatibilidad: primera configuración activa (orden, id).
    Preferir listar_configuraciones_activas / obtener_configuracion_por_id.
    """
    configs = listar_configuraciones_activas(agencia_id)
    return configs[0] if configs else None


def obtener_configuracion_por_agencia(agencia_id: int) -> Optional[Dict[str, Any]]:
    """
    Compatibilidad: primera configuración de la agencia (activa o no).
    Preferir listar_configuraciones / obtener_configuracion_por_id.
    """
    configs = listar_configuraciones(agencia_id, solo_activas=False)
    return configs[0] if configs else None


def _siguiente_orden(cur, agencia_id: int) -> int:
    cur.execute(
        """
        SELECT COALESCE(MAX(orden), 0)::int + 1 AS siguiente
        FROM chatbot.chatbot_configuracion
        WHERE agencia_id = %s
        """,
        (agencia_id,),
    )
    row = cur.fetchone() or {}
    return int(row.get("siguiente") or 1)


def _limpiar_otras_predeterminadas(cur, agencia_id: int, except_id: int) -> None:
    cur.execute(
        """
        UPDATE chatbot.chatbot_configuracion
        SET es_predeterminada = FALSE, updated_at = CURRENT_TIMESTAMP
        WHERE agencia_id = %s
          AND id <> %s
          AND es_predeterminada = TRUE
        """,
        (agencia_id, except_id),
    )


def _agencia_tiene_plataforma(
    cur,
    agencia_id: int,
    plataforma_codigo: str,
    *,
    exclude_configuracion_id: Optional[int] = None,
) -> bool:
    """True si la agencia ya tiene una configuración para esa plataforma."""
    codigo = (plataforma_codigo or "").strip().lower()
    if not codigo:
        return False
    if exclude_configuracion_id is not None:
        cur.execute(
            """
            SELECT 1
            FROM chatbot.chatbot_configuracion
            WHERE agencia_id = %s
              AND lower(plataforma_codigo) = %s
              AND id <> %s
            LIMIT 1
            """,
            (agencia_id, codigo, int(exclude_configuracion_id)),
        )
    else:
        cur.execute(
            """
            SELECT 1
            FROM chatbot.chatbot_configuracion
            WHERE agencia_id = %s
              AND lower(plataforma_codigo) = %s
            LIMIT 1
            """,
            (agencia_id, codigo),
        )
    return cur.fetchone() is not None


def crear_configuracion_default(agencia_id: int) -> Dict[str, Any]:
    """
    Compatibilidad (admin / rutas legacy): crea TikTok solo si la agencia
    aún no tiene ninguna configuración. El portal multi-plataforma NO debe
    invocar esto en listados vacíos.
    """
    existentes = listar_configuraciones(agencia_id)
    if existentes:
        return existentes[0]

    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            orden = _siguiente_orden(cur, agencia_id)
            cur.execute(
                """
                INSERT INTO chatbot.chatbot_configuracion (
                    agencia_id,
                    codigo,
                    nombre,
                    plataforma_codigo,
                    texto_opcion,
                    es_predeterminada,
                    orden,
                    activo
                ) VALUES (
                    %s, 'tiktok', 'TikTok', 'tiktok', 'TikTok',
                    TRUE, %s, TRUE
                )
                RETURNING *
                """,
                (agencia_id, orden),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("No se pudo crear configuración default")
            out = dict(row)
            logger.info(
                "[CHATBOT-CONFIG] default creada agencia_id=%s configuracion_id=%s",
                agencia_id,
                out.get("id"),
            )
            return out


def crear_configuracion(agencia_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    from chatbot_tipo import preparar_payload_tipo

    data = preparar_payload_tipo(dict(data or {}))
    faqs_plain = _faqs_plain(data)
    recursos_plain = _recursos_plain(data)
    codigo = str(data.get("codigo") or "").strip().lower()[:80]
    plataforma_codigo = str(data.get("plataforma_codigo") or "").strip().lower()[:30]
    es_predeterminada = bool(data.get("es_predeterminada"))
    nombre = str(data.get("nombre") or "").strip()[:120]
    texto_opcion = str(data.get("texto_opcion") or "").strip()[:40]
    from chatbot_tipo import TIPOS_CHATBOT, normalizar_tipo_chatbot

    tipo_chatbot = normalizar_tipo_chatbot(data.get("tipo_chatbot")) or "informativo"
    if tipo_chatbot not in TIPOS_CHATBOT:
        tipo_chatbot = "informativo"
    if not codigo:
        raise ValueError("codigo es obligatorio")
    if not nombre:
        raise ValueError("nombre es obligatorio")
    if not texto_opcion:
        raise ValueError("texto_opcion es obligatorio")
    if not plataforma_codigo:
        raise ValueError("plataforma_codigo es obligatorio")

    plat = obtener_plataforma(plataforma_codigo)
    if not plat or not plat.get("activo"):
        raise ValueError("plataforma_codigo inválida o inactiva")

    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if _agencia_tiene_plataforma(cur, agencia_id, plataforma_codigo):
                raise ValueError(
                    f"Ya existe una configuración para la plataforma "
                    f"'{plataforma_codigo}' en esta agencia"
                )
            orden = data.get("orden")
            if orden is None:
                orden = _siguiente_orden(cur, agencia_id)
            try:
                cur.execute(
                    """
                    INSERT INTO chatbot.chatbot_configuracion (
                        agencia_id,
                        codigo,
                        nombre,
                        plataforma_codigo,
                        texto_opcion,
                        es_predeterminada,
                        orden,
                        activo,
                        tipo_chatbot,
                        usar_asistente_conversacional,
                        usar_rutas_adaptativas,
                        mensaje_bienvenida,
                        pregunta_usuario,
                        pregunta_mayor_edad,
                        pregunta_disponibilidad,
                        mensaje_aprobado,
                        mensaje_no_aprobado,
                        texto_boton_continuar,
                        accion_continuar,
                        url_continuar,
                        texto_boton_preguntas,
                        preguntas_frecuentes,
                        recursos_bienvenida,
                        mensaje_error
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING *
                    """,
                    (
                        agencia_id,
                        codigo,
                        nombre,
                        plataforma_codigo,
                        texto_opcion,
                        es_predeterminada,
                        int(orden),
                        bool(data.get("activo", False)),
                        tipo_chatbot,
                        bool(data.get("usar_asistente_conversacional", True)),
                        bool(data.get("usar_rutas_adaptativas", False)),
                        data["mensaje_bienvenida"],
                        data["pregunta_usuario"],
                        data["pregunta_mayor_edad"],
                        data["pregunta_disponibilidad"],
                        data["mensaje_aprobado"],
                        data["mensaje_no_aprobado"],
                        data["texto_boton_continuar"],
                        data["accion_continuar"],
                        data.get("url_continuar"),
                        data["texto_boton_preguntas"],
                        Json(faqs_plain),
                        Json(recursos_plain),
                        data["mensaje_error"],
                    ),
                )
            except Exception as e:
                if "uq_chatbot_configuracion" in str(e).lower() or "unique" in str(e).lower():
                    raise ValueError(
                        f"Ya existe una configuración con código '{codigo}' en esta agencia"
                    ) from e
                if "tipo_chatbot" in str(e).lower():
                    raise ValueError(
                        "La columna tipo_chatbot no está disponible. "
                        "Ejecute la migración SQL pendiente."
                    ) from e
                raise
            row = cur.fetchone()
            if not row:
                raise RuntimeError("No se pudo crear la configuración")
            cfg_id = int(row["id"])
            if es_predeterminada:
                _limpiar_otras_predeterminadas(cur, agencia_id, cfg_id)
            logger.info(
                "[CHATBOT-CONFIG] creada agencia_id=%s configuracion_id=%s "
                "plataforma_codigo=%s codigo=%s activo=%s tipo_chatbot=%s",
                agencia_id,
                cfg_id,
                plataforma_codigo,
                codigo,
                bool(data.get("activo", False)),
                tipo_chatbot,
            )
    return obtener_configuracion_por_id(agencia_id, cfg_id) or dict(row)


def actualizar_configuracion(
    agencia_id: int,
    data: Dict[str, Any],
    *,
    configuracion_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Actualiza una configuración por id (preferido) o, en compatibilidad,
    la primera de la agencia si no se indica configuracion_id.
    """
    from chatbot_tipo import preparar_payload_tipo

    data = preparar_payload_tipo(dict(data or {}))
    faqs_plain = _faqs_plain(data)
    recursos_plain = _recursos_plain(data)

    if configuracion_id is None:
        existente = obtener_configuracion_por_agencia(agencia_id)
        if not existente:
            raise ValueError("Configuración no encontrada")
        configuracion_id = int(existente["id"])

    plataforma_codigo = data.get("plataforma_codigo")
    if plataforma_codigo is not None:
        plataforma_codigo = str(plataforma_codigo).strip().lower()
        plat = obtener_plataforma(plataforma_codigo)
        if not plat or not plat.get("activo"):
            raise ValueError("plataforma_codigo inválida o inactiva")

    logger.info(
        "[CHATBOT-CONFIG] actualizar agencia_id=%s configuracion_id=%s "
        "faqs=%s recursos=%s tipo_chatbot=%s",
        agencia_id,
        configuracion_id,
        len(faqs_plain),
        len(recursos_plain),
        data.get("tipo_chatbot"),
    )

    sets = [
        "activo = %s",
        "tipo_chatbot = %s",
        "usar_asistente_conversacional = %s",
        "usar_rutas_adaptativas = %s",
        "mensaje_bienvenida = %s",
        "pregunta_usuario = %s",
        "pregunta_mayor_edad = %s",
        "pregunta_disponibilidad = %s",
        "mensaje_aprobado = %s",
        "mensaje_no_aprobado = %s",
        "texto_boton_continuar = %s",
        "accion_continuar = %s",
        "url_continuar = %s",
        "texto_boton_preguntas = %s",
        "preguntas_frecuentes = %s",
        "recursos_bienvenida = %s",
        "mensaje_error = %s",
        "updated_at = CURRENT_TIMESTAMP",
    ]
    from chatbot_tipo import TIPOS_CHATBOT, normalizar_tipo_chatbot

    tipo_chatbot = normalizar_tipo_chatbot(data.get("tipo_chatbot")) or "informativo"
    if tipo_chatbot not in TIPOS_CHATBOT:
        tipo_chatbot = "informativo"
    params: List[Any] = [
        data["activo"],
        tipo_chatbot,
        bool(data.get("usar_asistente_conversacional", False)),
        bool(data.get("usar_rutas_adaptativas", False)),
        data["mensaje_bienvenida"],
        data["pregunta_usuario"],
        data["pregunta_mayor_edad"],
        data["pregunta_disponibilidad"],
        data["mensaje_aprobado"],
        data["mensaje_no_aprobado"],
        data["texto_boton_continuar"],
        data["accion_continuar"],
        data.get("url_continuar"),
        data["texto_boton_preguntas"],
        Json(faqs_plain),
        Json(recursos_plain),
        data["mensaje_error"],
    ]

    if data.get("nombre") is not None:
        sets.insert(-1, "nombre = %s")
        params.append(str(data["nombre"]).strip()[:120])
    if data.get("codigo") is not None:
        sets.insert(-1, "codigo = %s")
        params.append(str(data["codigo"]).strip().lower()[:80])
    if plataforma_codigo is not None:
        sets.insert(-1, "plataforma_codigo = %s")
        params.append(plataforma_codigo[:30])
    if data.get("texto_opcion") is not None:
        sets.insert(-1, "texto_opcion = %s")
        params.append(str(data["texto_opcion"]).strip()[:40])
    if data.get("orden") is not None:
        sets.insert(-1, "orden = %s")
        params.append(int(data["orden"]))
    if "es_predeterminada" in data and data.get("es_predeterminada") is not None:
        sets.insert(-1, "es_predeterminada = %s")
        params.append(bool(data["es_predeterminada"]))

    params.extend([configuracion_id, agencia_id])

    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if plataforma_codigo is not None:
                if _agencia_tiene_plataforma(
                    cur,
                    agencia_id,
                    plataforma_codigo,
                    exclude_configuracion_id=configuracion_id,
                ):
                    raise ValueError(
                        f"Ya existe una configuración para la plataforma "
                        f"'{plataforma_codigo}' en esta agencia"
                    )
            try:
                # recursos_bienvenida va explícito en SET (JSONB) y se valida con
                # RETURNING de esta misma conexión/transacción — no releer con otra sesión.
                cur.execute(
                    f"""
                    UPDATE chatbot.chatbot_configuracion
                    SET {", ".join(sets)}
                    WHERE id = %s AND agencia_id = %s
                    RETURNING
                        id,
                        agencia_id,
                        codigo,
                        nombre,
                        plataforma_codigo,
                        texto_opcion,
                        es_predeterminada,
                        orden,
                        activo,
                        mensaje_bienvenida,
                        pregunta_usuario,
                        pregunta_mayor_edad,
                        pregunta_disponibilidad,
                        mensaje_aprobado,
                        mensaje_no_aprobado,
                        texto_boton_continuar,
                        accion_continuar,
                        url_continuar,
                        texto_boton_preguntas,
                        preguntas_frecuentes,
                        recursos_bienvenida,
                        mensaje_error,
                        created_at,
                        updated_at
                    """,
                    params,
                )
            except Exception as e:
                if "unique" in str(e).lower() or "uq_chatbot_configuracion" in str(e).lower():
                    raise ValueError(
                        "Ya existe una configuración con ese código en esta agencia"
                    ) from e
                raise
            row = cur.fetchone()
            if not row:
                raise ValueError("Configuración no encontrada")
            if data.get("es_predeterminada") is True:
                _limpiar_otras_predeterminadas(cur, agencia_id, int(row["id"]))

            out = dict(row)
            recursos_ret = parse_recursos_bienvenida(out.get("recursos_bienvenida"))
            out["recursos_bienvenida"] = recursos_ret

            cur.execute(
                """
                SELECT nombre
                FROM chatbot.plataformas
                WHERE codigo = %s
                LIMIT 1
                """,
                (out.get("plataforma_codigo"),),
            )
            plat = cur.fetchone()
            out["plataforma_nombre"] = plat["nombre"] if plat else None

            logger.info(
                "[CHATBOT-CONFIG] actualizada agencia_id=%s configuracion_id=%s "
                "plataforma_codigo=%s recursos_returning=%s activo=%s",
                agencia_id,
                out.get("id"),
                out.get("plataforma_codigo"),
                len(recursos_ret),
                out.get("activo"),
            )
            # Commit al salir del context manager, antes de devolver al caller.
            return out


def duplicar_configuracion(
    agencia_id: int,
    configuracion_id: int,
    *,
    nuevo_codigo: Optional[str] = None,
    nuevo_nombre: Optional[str] = None,
) -> Dict[str, Any]:
    origen = obtener_configuracion_por_id(agencia_id, configuracion_id)
    if not origen:
        raise ValueError("Configuración no encontrada")

    base_codigo = (nuevo_codigo or f"{origen.get('codigo') or 'cfg'}_copia").strip().lower()[:80]
    nombre = (nuevo_nombre or f"{origen.get('nombre') or 'Config'} (copia)").strip()[:120]

    data = {
        "codigo": base_codigo,
        "nombre": nombre,
        "plataforma_codigo": (origen.get("plataforma_codigo") or "tiktok")[:30],
        "texto_opcion": (origen.get("texto_opcion") or origen.get("nombre") or "Opción")[:40],
        "es_predeterminada": False,
        "orden": None,
        "activo": bool(origen.get("activo", True)),
        "usar_asistente_conversacional": bool(
            origen.get("usar_asistente_conversacional", False)
        ),
        "usar_rutas_adaptativas": bool(origen.get("usar_rutas_adaptativas", False)),
        "mensaje_bienvenida": (origen.get("mensaje_bienvenida") or "Bienvenido")[:600],
        "pregunta_usuario": (origen.get("pregunta_usuario") or "¿Cuál es tu usuario?")[:300],
        "pregunta_mayor_edad": (origen.get("pregunta_mayor_edad") or "¿Eres mayor de edad?")[:150],
        "pregunta_disponibilidad": (
            origen.get("pregunta_disponibilidad")
            or "¿Tienes disponibilidad para LIVE?"
        )[:200],
        "mensaje_aprobado": (origen.get("mensaje_aprobado") or "¡Aprobado!")[:300],
        "mensaje_no_aprobado": (
            origen.get("mensaje_no_aprobado") or "No cumples los requisitos."
        )[:300],
        "texto_boton_continuar": (origen.get("texto_boton_continuar") or "Continuar")[:40],
        "accion_continuar": origen.get("accion_continuar") or "asesor",
        "url_continuar": origen.get("url_continuar"),
        "texto_boton_preguntas": (origen.get("texto_boton_preguntas") or "Preguntas")[:40],
        "preguntas_frecuentes": parse_faqs(origen.get("preguntas_frecuentes")),
        "recursos_bienvenida": parse_recursos_bienvenida(origen.get("recursos_bienvenida")),
        "mensaje_error": (origen.get("mensaje_error") or "Ocurrió un error.")[:250],
    }
    # Si el código choca, sufijar con timestamp corto
    try:
        return crear_configuracion(agencia_id, data)
    except ValueError:
        data["codigo"] = f"{base_codigo}_{int(datetime.utcnow().timestamp()) % 100000}"
        return crear_configuracion(agencia_id, data)


def set_configuracion_activo(
    agencia_id: int,
    configuracion_id: int,
    activo: bool,
) -> Dict[str, Any]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE chatbot.chatbot_configuracion
                SET activo = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND agencia_id = %s
                RETURNING id
                """,
                (bool(activo), configuracion_id, agencia_id),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Configuración no encontrada")
    out = obtener_configuracion_por_id(agencia_id, configuracion_id)
    if not out:
        raise ValueError("Configuración no encontrada")
    logger.info(
        "[CHATBOT-CONFIG] activo=%s agencia_id=%s configuracion_id=%s",
        activo,
        agencia_id,
        configuracion_id,
    )
    return out


def set_usar_asistente_conversacional(
    agencia_id: int,
    configuracion_id: int,
    usar_asistente_conversacional: bool,
) -> Dict[str, Any]:
    """
    Selector de motor por plataforma.

    No modifica ``asistente_configuracion.activo``: son campos independientes.
    """
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE chatbot.chatbot_configuracion
                SET usar_asistente_conversacional = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND agencia_id = %s
                RETURNING id
                """,
                (bool(usar_asistente_conversacional), configuracion_id, agencia_id),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Configuración no encontrada")
    out = obtener_configuracion_por_id(agencia_id, configuracion_id)
    if not out:
        raise ValueError("Configuración no encontrada")
    logger.info(
        "[CHATBOT-CONFIG] usar_asistente_conversacional=%s "
        "agencia_id=%s configuracion_id=%s",
        bool(usar_asistente_conversacional),
        agencia_id,
        configuracion_id,
    )
    return out


def set_usar_rutas_adaptativas(
    agencia_id: int,
    configuracion_id: int,
    usar_rutas_adaptativas: bool,
) -> Dict[str, Any]:
    """
    Activa clasificación adaptativa. Solo aplica con asistente conversacional.

    No modifica ``asistente_configuracion.activo``.
    """
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE chatbot.chatbot_configuracion
                SET usar_rutas_adaptativas = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND agencia_id = %s
                RETURNING id
                """,
                (bool(usar_rutas_adaptativas), configuracion_id, agencia_id),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Configuración no encontrada")
    out = obtener_configuracion_por_id(agencia_id, configuracion_id)
    if not out:
        raise ValueError("Configuración no encontrada")
    logger.info(
        "[CHATBOT-CONFIG] usar_rutas_adaptativas=%s "
        "agencia_id=%s configuracion_id=%s",
        bool(usar_rutas_adaptativas),
        agencia_id,
        configuracion_id,
    )
    return out


def set_tipo_chatbot(
    agencia_id: int,
    configuracion_id: int,
    tipo_chatbot: str,
) -> Dict[str, Any]:
    """
    Persiste tipo_chatbot y sincroniza flags internos en una transacción.

    Al elegir informativo o inteligente, si existe asistente_configuracion
    asociada, queda activo=true. En tradicional el asistente queda inactivo
    (motor clásico de captación).
    """
    from chatbot_tipo import (
        TIPO_TRADICIONAL,
        modos_asistente_desde_tipo,
        normalizar_tipo_chatbot,
        sync_completo_desde_tipo,
    )

    tipo = normalizar_tipo_chatbot(tipo_chatbot)
    if not tipo:
        raise ValueError(
            "tipo_chatbot debe ser 'tradicional', 'informativo' o 'inteligente'"
        )
    sync = sync_completo_desde_tipo(tipo)
    modos = modos_asistente_desde_tipo(tipo)
    asistente_activo = tipo != TIPO_TRADICIONAL
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE chatbot.chatbot_configuracion
                SET tipo_chatbot = %s,
                    usar_asistente_conversacional = %s,
                    usar_rutas_adaptativas = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND agencia_id = %s
                RETURNING id
                """,
                (
                    sync["tipo_chatbot"],
                    sync["usar_asistente_conversacional"],
                    sync["usar_rutas_adaptativas"],
                    configuracion_id,
                    agencia_id,
                ),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Configuración no encontrada")

            # Sync modos internos; activar solo si no es tradicional
            cur.execute(
                """
                UPDATE chatbot.asistente_configuracion
                SET activo = %s,
                    modo_informativo_activo = %s,
                    modo_conversion_activo = %s,
                    modo_predeterminado = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE agencia_id = %s AND chatbot_configuracion_id = %s
                RETURNING id
                """,
                (
                    asistente_activo,
                    modos["modo_informativo_activo"],
                    modos["modo_conversion_activo"],
                    modos["modo_predeterminado"],
                    agencia_id,
                    configuracion_id,
                ),
            )
            asistente_row = cur.fetchone()

    out = obtener_configuracion_por_id(agencia_id, configuracion_id)
    if not out:
        raise ValueError("Configuración no encontrada")
    logger.info(
        "[CHATBOT-CONFIG] tipo_chatbot=%s usar_asistente=%s usar_rutas=%s "
        "asistente_activado=%s agencia_id=%s configuracion_id=%s",
        tipo,
        sync["usar_asistente_conversacional"],
        sync["usar_rutas_adaptativas"],
        bool(asistente_row),
        agencia_id,
        configuracion_id,
    )
    return out


def reordenar_configuraciones(
    agencia_id: int,
    ordenes: List[Dict[str, int]],
) -> List[Dict[str, Any]]:
    """
    ordenes: lista de {id, orden}. Transacción única.
    Valida que todos los ids pertenezcan a la agencia.
    """
    if not ordenes:
        return listar_configuraciones(agencia_id)

    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for item in ordenes:
                cfg_id = int(item["id"])
                orden = int(item["orden"])
                cur.execute(
                    """
                    UPDATE chatbot.chatbot_configuracion
                    SET orden = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND agencia_id = %s
                    RETURNING id
                    """,
                    (orden, cfg_id, agencia_id),
                )
                if not cur.fetchone():
                    raise ValueError(
                        f"Configuración id={cfg_id} no pertenece a esta agencia"
                    )
    logger.info(
        "[CHATBOT-CONFIG] reordenadas agencia_id=%s n=%s",
        agencia_id,
        len(ordenes),
    )
    return listar_configuraciones(agencia_id)


def actualizar_recursos_bienvenida(
    agencia_id: int,
    recursos: List[Dict[str, Any]],
    *,
    configuracion_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Actualiza solo recursos_bienvenida (p. ej. tras DELETE media)."""
    if configuracion_id is None:
        existente = obtener_configuracion_por_agencia(agencia_id)
        if not existente:
            raise ValueError("Configuración no encontrada")
        configuracion_id = int(existente["id"])

    recursos_json = Json(list(recursos or []))
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE chatbot.chatbot_configuracion
                SET
                    recursos_bienvenida = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND agencia_id = %s
                RETURNING *
                """,
                (recursos_json, configuracion_id, agencia_id),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Configuración no encontrada")
            return dict(row)


def asignar_configuracion_aspirante(
    *,
    aspirante_id: int,
    agencia_id: int,
    configuracion_id: int,
    message_id_meta: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Valida configuración (existe, activa, misma agencia) y asigna en una TX:
    chatbot_configuracion_id, plataforma_codigo, configuracion_seleccionada_at,
    etapa_chatbot='usuario'.
    """
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, agencia_id, plataforma_codigo, activo
                FROM chatbot.chatbot_configuracion
                WHERE id = %s
                FOR UPDATE
                """,
                (configuracion_id,),
            )
            cfg = cur.fetchone()
            if not cfg:
                raise ValueError("Configuración no encontrada")
            if int(cfg["agencia_id"]) != int(agencia_id):
                raise PermissionError("Configuración de otra agencia")
            if not cfg.get("activo"):
                raise ValueError("Configuración desactivada")

            cur.execute(
                """
                UPDATE chatbot.chatbot_aspirantes
                SET
                    chatbot_configuracion_id = %s,
                    plataforma_codigo = %s,
                    configuracion_seleccionada_at = CURRENT_TIMESTAMP,
                    etapa_chatbot = %s,
                    estado = CASE
                        WHEN estado = 'nuevo' THEN 'en_proceso'
                        ELSE estado
                    END,
                    ultimo_message_id_meta = COALESCE(%s, ultimo_message_id_meta),
                    ultima_interaccion = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                  AND agencia_id = %s
                RETURNING *
                """,
                (
                    configuracion_id,
                    cfg["plataforma_codigo"],
                    "usuario",
                    message_id_meta,
                    aspirante_id,
                    agencia_id,
                ),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Aspirante no encontrado")
            logger.info(
                "[CHATBOT] config asignada agencia_id=%s aspirante_id=%s "
                "chatbot_configuracion_id=%s plataforma_codigo=%s",
                agencia_id,
                aspirante_id,
                configuracion_id,
                cfg["plataforma_codigo"],
            )
            return dict(row)


def listar_canales_agencia(agencia_id: int) -> List[Dict[str, Any]]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    aw.id AS mapping_id,
                    aw.whatsapp_account_id,
                    w.phone_number,
                    w.phone_number_id,
                    w.business_name,
                    w.waba_id,
                    w.status,
                    w.onboarding_type,
                    w.coexistence_enabled,
                    aw.principal,
                    aw.activo
                FROM chatbot.agencia_whatsapp_accounts aw
                INNER JOIN public.whatsapp_business_accounts w
                    ON w.id = aw.whatsapp_account_id
                WHERE aw.agencia_id = %s
                ORDER BY aw.principal DESC, aw.id ASC
                """,
                (agencia_id,),
            )
            return [dict(r) for r in (cur.fetchall() or [])]


def canal_pertenece_agencia(agencia_id: int, whatsapp_account_id: int) -> bool:
    with get_connection_chatbot_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM chatbot.agencia_whatsapp_accounts
                WHERE agencia_id = %s
                  AND whatsapp_account_id = %s
                  AND activo = TRUE
                LIMIT 1
                """,
                (agencia_id, whatsapp_account_id),
            )
            return cur.fetchone() is not None


def resumen_aspirantes(agencia_id: int) -> Dict[str, int]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)::int AS total,
                    COUNT(*) FILTER (WHERE estado = 'nuevo')::int AS nuevos,
                    COUNT(*) FILTER (WHERE estado = 'en_proceso')::int AS en_proceso,
                    COUNT(*) FILTER (WHERE estado = 'completado')::int AS completados,
                    COUNT(*) FILTER (WHERE estado = 'pendiente_asesor')::int AS pendientes_asesor,
                    COUNT(*) FILTER (WHERE estado = 'contactado')::int AS contactados,
                    COUNT(*) FILTER (WHERE estado = 'aprobado')::int AS aprobados,
                    COUNT(*) FILTER (WHERE estado = 'descartado')::int AS descartados
                FROM chatbot.chatbot_aspirantes
                WHERE agencia_id = %s
                """,
                (agencia_id,),
            )
            row = cur.fetchone() or {}
            return {
                "total": row.get("total") or 0,
                "nuevos": row.get("nuevos") or 0,
                "en_proceso": row.get("en_proceso") or 0,
                "completados": row.get("completados") or 0,
                "pendientes_asesor": row.get("pendientes_asesor") or 0,
                "contactados": row.get("contactados") or 0,
                "aprobados": row.get("aprobados") or 0,
                "descartados": row.get("descartados") or 0,
            }


def listar_aspirantes(
    agencia_id: int,
    *,
    search: Optional[str] = None,
    estado: Optional[str] = None,
    plataforma: Optional[str] = None,
    cumple_requisitos: Optional[bool] = None,
    requiere_asesor: Optional[bool] = None,
    estado_diagnostico: Optional[str] = None,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    whatsapp_account_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
    order: str = "fecha_registro_desc",
) -> Tuple[int, List[Dict[str, Any]]]:
    import time

    t0 = time.perf_counter()
    where = ["a.agencia_id = %s"]
    params: List[Any] = [agencia_id]

    if search:
        where.append(
            "(a.telefono ILIKE %s OR COALESCE(a.nombre,'') ILIKE %s "
            "OR COALESCE(a.usuario_plataforma,'') ILIKE %s)"
        )
        like = f"%{search.strip()}%"
        params.extend([like, like, like])
    if estado:
        where.append("a.estado = %s")
        params.append(estado)
    if plataforma:
        where.append("a.plataforma_codigo = %s")
        params.append(str(plataforma).strip().lower())
    if cumple_requisitos is not None:
        where.append("a.cumple_requisitos = %s")
        params.append(cumple_requisitos)
    if requiere_asesor is not None:
        where.append("a.requiere_asesor = %s")
        params.append(requiere_asesor)
    if fecha_desde:
        where.append("a.fecha_registro::date >= %s")
        params.append(fecha_desde)
    if fecha_hasta:
        where.append("a.fecha_registro::date <= %s")
        params.append(fecha_hasta)
    if whatsapp_account_id is not None:
        where.append("a.whatsapp_account_id = %s")
        params.append(whatsapp_account_id)

    estado_diag = (estado_diagnostico or "").strip().lower()
    if estado_diag == "evaluado":
        where.append("e.evaluado_at IS NOT NULL")
    elif estado_diag == "pendiente":
        where.append("e.evaluado_at IS NULL")

    order_sql = "a.fecha_registro DESC"
    if order == "fecha_registro_asc":
        order_sql = "a.fecha_registro ASC"
    elif order == "ultima_interaccion_desc":
        order_sql = "a.ultima_interaccion DESC"

    where_sql = " AND ".join(where)
    offset = max(page - 1, 0) * page_size
    page_size = max(1, min(int(page_size), 100))

    join_eval = """
                LEFT JOIN chatbot.evaluaciones_aspirantes e
                    ON e.aspirante_id = a.id
                   AND e.agencia_id = a.agencia_id
                   AND (
                        (a.chatbot_configuracion_id IS NOT NULL
                         AND e.chatbot_configuracion_id = a.chatbot_configuracion_id)
                        OR (a.chatbot_configuracion_id IS NULL
                            AND e.chatbot_configuracion_id IS NULL)
                   )
    """

    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    a.id,
                    a.telefono,
                    a.nombre,
                    a.plataforma_codigo,
                    a.usuario_plataforma,
                    a.chatbot_configuracion_id,
                    a.mayor_edad,
                    a.disponibilidad_live,
                    a.estado,
                    a.etapa_chatbot,
                    a.cumple_requisitos,
                    a.requiere_asesor,
                    a.observaciones,
                    a.whatsapp_account_id,
                    a.fecha_registro,
                    a.ultima_interaccion,
                    a.agencia_id,
                    a.updated_at,
                    p.nombre AS plataforma,
                    w.phone_number AS phone_number_origen,
                    w.business_name AS business_name_origen,
                    CASE
                        WHEN e.evaluado_at IS NOT NULL THEN 'evaluado'
                        ELSE 'pendiente'
                    END AS estado_diagnostico,
                    e.resultado_global,
                    e.evaluado_at,
                    e.evaluado_por,
                    COUNT(*) OVER()::int AS _total
                FROM chatbot.chatbot_aspirantes a
                LEFT JOIN chatbot.plataformas p
                    ON p.codigo = a.plataforma_codigo
                LEFT JOIN public.whatsapp_business_accounts w
                    ON w.id = a.whatsapp_account_id
                {join_eval}
                WHERE {where_sql}
                ORDER BY {order_sql}
                LIMIT %s OFFSET %s
                """,
                params + [page_size, offset],
            )
            fetched = [dict(r) for r in (cur.fetchall() or [])]
            total = int(fetched[0]["_total"]) if fetched else 0
            for r in fetched:
                r.pop("_total", None)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "[CHATBOT-LIST] aspirantes agencia_id=%s page=%s size=%s total=%s ms=%.1f",
                agencia_id,
                page,
                page_size,
                total,
                elapsed_ms,
            )
            return total, fetched


def obtener_aspirante(agencia_id: int, aspirante_id: int) -> Optional[Dict[str, Any]]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    a.*,
                    p.nombre AS plataforma,
                    w.phone_number AS phone_number_origen,
                    w.business_name AS business_name_origen,
                    CASE
                        WHEN e.evaluado_at IS NOT NULL THEN 'evaluado'
                        ELSE 'pendiente'
                    END AS estado_diagnostico,
                    e.resultado_global,
                    e.evaluado_at,
                    e.evaluado_por
                FROM chatbot.chatbot_aspirantes a
                LEFT JOIN chatbot.plataformas p
                    ON p.codigo = a.plataforma_codigo
                LEFT JOIN public.whatsapp_business_accounts w
                    ON w.id = a.whatsapp_account_id
                LEFT JOIN chatbot.evaluaciones_aspirantes e
                    ON e.aspirante_id = a.id
                   AND e.agencia_id = a.agencia_id
                   AND (
                        (a.chatbot_configuracion_id IS NOT NULL
                         AND e.chatbot_configuracion_id = a.chatbot_configuracion_id)
                        OR (a.chatbot_configuracion_id IS NULL
                            AND e.chatbot_configuracion_id IS NULL)
                   )
                WHERE a.id = %s
                  AND a.agencia_id = %s
                LIMIT 1
                """,
                (aspirante_id, agencia_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def actualizar_aspirante_admin(
    agencia_id: int,
    aspirante_id: int,
    *,
    estado: Optional[str] = None,
    requiere_asesor: Optional[bool] = None,
    observaciones: Optional[str] = None,
    nivel_experiencia: Optional[str] = None,
    nivel_experiencia_bloqueado_manual: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    sets = []
    params: List[Any] = []
    if estado is not None:
        sets.append("estado = %s")
        params.append(estado)
    if requiere_asesor is not None:
        sets.append("requiere_asesor = %s")
        params.append(requiere_asesor)
    if observaciones is not None:
        sets.append("observaciones = %s")
        params.append(observaciones)
    if nivel_experiencia is not None:
        sets.append("nivel_experiencia = %s")
        params.append(nivel_experiencia)
        sets.append("nivel_experiencia_fuente = %s")
        params.append("manual")
        sets.append("nivel_experiencia_confirmado_at = CURRENT_TIMESTAMP")
    if nivel_experiencia_bloqueado_manual is not None:
        sets.append("nivel_experiencia_bloqueado_manual = %s")
        params.append(bool(nivel_experiencia_bloqueado_manual))
    if not sets:
        return obtener_aspirante(agencia_id, aspirante_id)

    sets.append("updated_at = CURRENT_TIMESTAMP")
    params.extend([aspirante_id, agencia_id])

    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                UPDATE chatbot.chatbot_aspirantes
                SET {", ".join(sets)}
                WHERE id = %s AND agencia_id = %s
                RETURNING id
                """,
                params,
            )
            row = cur.fetchone()
            if not row:
                return None
    return obtener_aspirante(agencia_id, aspirante_id)


def reiniciar_flujo_aspirante(
    agencia_id: int,
    aspirante_id: int,
    *,
    limpiar_respuestas: bool = False,
    modo_prueba: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Reinicia el flujo del chatbot para un aspirante de la agencia.

    Siempre (en una sola transacción):
    - restablece chatbot_aspirantes a nuevo/inicio (requiere_asesor=false);
    - limpia progreso conversacional (flujo, paso, contexto, resumen, intención);
    - cancela tareas_candidato abiertas (pendiente/en_progreso).

    Con modo_prueba=True (default, recomendado para re-probar el mismo número):
    - cierra conversaciones abiertas ligadas al aspirante/teléfono;
    - el siguiente mensaje crea conversación nueva (sin historial en contexto);
    - resetea nivel_experiencia del aspirante si no está bloqueado manualmente.

    Con modo_prueba=False (reinicio suave legacy):
    - deja la conversación abierta y limpia su progreso;
    - conserva nivel estable del aspirante.

    No elimina el aspirante ni altera telefono, agencia_id, whatsapp_account_id
    o fecha_registro. Tampoco borra mensajes, evidencias ni evaluaciones.
    """
    # limpiar_respuestas se conserva por compatibilidad de API (ya limpia siempre)
    _ = limpiar_respuestas
    modo_prueba = bool(modo_prueba)

    sets = [
        "estado = %s",
        "etapa_chatbot = %s",
        "requiere_asesor = FALSE",
        "cumple_requisitos = NULL",
        "chatbot_configuracion_id = NULL",
        "plataforma_codigo = NULL",
        "configuracion_seleccionada_at = NULL",
        "usuario_plataforma = NULL",
        "mayor_edad = NULL",
        "disponibilidad_live = NULL",
        "modo_conversacional = NULL",
        "updated_at = CURRENT_TIMESTAMP",
    ]
    params: List[Any] = ["nuevo", "inicio"]

    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, telefono, requiere_asesor, nivel_experiencia,
                       nivel_experiencia_bloqueado_manual
                FROM chatbot.chatbot_aspirantes
                WHERE id = %s AND agencia_id = %s
                LIMIT 1
                """,
                (aspirante_id, agencia_id),
            )
            aspirante_prev = cur.fetchone()
            if not aspirante_prev:
                return None

            requiere_asesor_anterior = bool(aspirante_prev.get("requiere_asesor"))
            nivel_bloqueado_asp = bool(
                aspirante_prev.get("nivel_experiencia_bloqueado_manual")
            )
            telefono = str(aspirante_prev.get("telefono") or "").strip() or None

            if modo_prueba and not nivel_bloqueado_asp:
                sets.extend(
                    [
                        "nivel_experiencia = 'desconocido'",
                        "nivel_experiencia_fuente = NULL",
                        "nivel_experiencia_confianza = NULL",
                        "nivel_experiencia_confirmado_at = NULL",
                    ]
                )

            params.extend([aspirante_id, agencia_id])
            cur.execute(
                f"""
                UPDATE chatbot.chatbot_aspirantes
                SET {", ".join(sets)}
                WHERE id = %s AND agencia_id = %s
                RETURNING id
                """,
                params,
            )
            row = cur.fetchone()
            if not row:
                return None

            # Conversaciones abiertas del aspirante (y por teléfono / wa_id).
            conv_params: List[Any] = [agencia_id, aspirante_id]
            if telefono:
                conv_sql = """
                    SELECT id, modo_humano, estado, estado_actual,
                           nivel_experiencia_bloqueado_manual, manager_id, aspirante_id
                    FROM chatbot.conversaciones
                    WHERE agencia_id = %s
                      AND estado <> 'cerrada'
                      AND (
                        aspirante_id = %s
                        OR telefono = %s
                        OR usuario_externo_id = %s
                      )
                    ORDER BY COALESCE(ultimo_mensaje_at, iniciada_at, created_at) DESC NULLS LAST,
                             id DESC
                    """
                conv_params.extend([telefono, telefono])
            else:
                conv_sql = """
                    SELECT id, modo_humano, estado, estado_actual,
                           nivel_experiencia_bloqueado_manual, manager_id, aspirante_id
                    FROM chatbot.conversaciones
                    WHERE agencia_id = %s
                      AND estado <> 'cerrada'
                      AND aspirante_id = %s
                    ORDER BY COALESCE(ultimo_mensaje_at, iniciada_at, created_at) DESC NULLS LAST,
                             id DESC
                    """

            cur.execute(conv_sql, conv_params)
            conversaciones = list(cur.fetchall() or [])

            conversaciones_actualizadas = 0
            conversacion_id = None
            modo_humano_anterior = False
            tareas_canceladas = 0
            estado_nuevo_conv = "cerrada" if modo_prueba else "abierta"

            for conv in conversaciones:
                cid = int(conv["id"])
                if conversacion_id is None:
                    conversacion_id = cid
                    modo_humano_anterior = bool(conv.get("modo_humano"))

                nivel_bloqueado_conv = bool(
                    conv.get("nivel_experiencia_bloqueado_manual")
                )
                campos_conv = [
                    "modo_humano = FALSE",
                    "manager_id = NULL",
                    "ia_habilitada = TRUE",
                    f"estado = '{estado_nuevo_conv}'",
                    "estado_actual = 'inicio'",
                    "flujo_id = NULL",
                    "paso_actual_id = NULL",
                    "contexto = '{}'::jsonb",
                    "resumen_contexto = NULL",
                    "preguntas_clasificacion_realizadas = 0",
                    "intencion_actual = 'desconocida'",
                    "intencion_confianza = NULL",
                    "intencion_actualizada_at = NULL",
                    "ultima_clasificacion_at = NULL",
                    "motivo_escalamiento = NULL",
                    "escalada_at = NULL",
                    "updated_at = CURRENT_TIMESTAMP",
                ]
                if modo_prueba:
                    campos_conv.append("cerrada_at = CURRENT_TIMESTAMP")
                else:
                    campos_conv.append("cerrada_at = NULL")

                if not nivel_bloqueado_conv:
                    campos_conv.extend(
                        [
                            "nivel_experiencia = 'desconocido'",
                            "nivel_experiencia_fuente = NULL",
                            "nivel_experiencia_confianza = NULL",
                            "nivel_experiencia_confirmado = FALSE",
                            "estrategia_nivel_aplicada = NULL",
                            "nivel_experiencia_actualizado_at = NULL",
                        ]
                    )

                cur.execute(
                    f"""
                    UPDATE chatbot.conversaciones
                    SET {", ".join(campos_conv)}
                    WHERE id = %s AND agencia_id = %s
                    """,
                    (cid, agencia_id),
                )
                conversaciones_actualizadas += cur.rowcount or 0

                try:
                    cur.execute(
                        """
                        INSERT INTO chatbot.eventos_conversacion (
                            agencia_id, conversacion_id, tipo_evento, nombre_evento,
                            origen, estado_anterior, estado_nuevo, exitoso, detalle
                        ) VALUES (
                            %s, %s, 'cambio_estado', 'reinicio_flujo_aspirante',
                            'backend', %s, %s, TRUE, %s
                        )
                        """,
                        (
                            agencia_id,
                            cid,
                            conv.get("estado"),
                            estado_nuevo_conv,
                            Json(
                                {
                                    "aspirante_id": aspirante_id,
                                    "modo_prueba": modo_prueba,
                                    "modo_humano_anterior": bool(conv.get("modo_humano")),
                                    "modo_humano_nuevo": False,
                                    "requiere_asesor_anterior": requiere_asesor_anterior,
                                    "requiere_asesor_nuevo": False,
                                    "nivel_aspirante_reseteado": bool(
                                        modo_prueba and not nivel_bloqueado_asp
                                    ),
                                    "nivel_bloqueado_conservado": nivel_bloqueado_conv
                                    or nivel_bloqueado_asp,
                                    "flujo_limpiado": True,
                                    "contexto_limpiado": True,
                                }
                            ),
                        ),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[CHATBOT-REINICIO] no se pudo registrar evento "
                        "aspirante_id=%s conversacion_id=%s: %s",
                        aspirante_id,
                        cid,
                        exc,
                    )

            # Cancelar tareas abiertas del aspirante (y de sus conversaciones).
            cur.execute(
                """
                UPDATE chatbot.tareas_candidato
                SET estado = 'cancelada',
                    updated_at = CURRENT_TIMESTAMP
                WHERE agencia_id = %s
                  AND estado IN ('pendiente', 'en_progreso')
                  AND (
                    aspirante_id = %s
                    OR conversacion_id IN (
                        SELECT id FROM chatbot.conversaciones
                        WHERE agencia_id = %s AND aspirante_id = %s
                    )
                  )
                """,
                (agencia_id, aspirante_id, agencia_id, aspirante_id),
            )
            tareas_canceladas = cur.rowcount or 0

            logger.info(
                "[CHATBOT-REINICIO] aspirante_id=%s conversacion_id=%s "
                "modo_prueba=%s modo_humano_anterior=%s modo_humano_nuevo=false "
                "requiere_asesor_anterior=%s requiere_asesor_nuevo=false "
                "conversaciones_actualizadas=%s tareas_canceladas=%s "
                "estado_conversacion=%s",
                aspirante_id,
                conversacion_id,
                str(modo_prueba).lower(),
                str(modo_humano_anterior).lower(),
                str(requiere_asesor_anterior).lower(),
                conversaciones_actualizadas,
                tareas_canceladas,
                estado_nuevo_conv,
            )
            logger.info(
                "[CHATBOT] flujo reiniciado agencia_id=%s aspirante_id=%s modo_prueba=%s",
                agencia_id,
                aspirante_id,
                str(modo_prueba).lower(),
            )

    return obtener_aspirante(agencia_id, aspirante_id)


# ---------- Runtime aspirantes (flujo WhatsApp) ----------

def obtener_aspirante_por_telefono(
    agencia_id: int,
    telefono: str,
) -> Optional[Dict[str, Any]]:
    """Busca por agencia_id + telefono (sin lock)."""
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT *
                FROM chatbot.chatbot_aspirantes
                WHERE agencia_id = %s
                  AND telefono = %s
                LIMIT 1
                """,
                (agencia_id, telefono),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def aspirante_for_update(cur, agencia_id: int, telefono: str) -> Optional[Dict[str, Any]]:
    cur.execute(
        """
        SELECT *
        FROM chatbot.chatbot_aspirantes
        WHERE agencia_id = %s
          AND telefono = %s
        FOR UPDATE
        """,
        (agencia_id, telefono),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def crear_aspirante(
    cur,
    *,
    agencia_id: int,
    whatsapp_account_id: int,
    telefono: str,
    message_id_meta: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Inserta aspirante inicial. Debe ejecutarse dentro de una transacción abierta.
    El commit lo hace get_connection_chatbot_context al salir sin error.
    """
    cur.execute(
        """
        INSERT INTO chatbot.chatbot_aspirantes (
            agencia_id,
            whatsapp_account_id,
            telefono,
            estado,
            etapa_chatbot,
            ultimo_message_id_meta
        ) VALUES (
            %s, %s, %s, 'nuevo', %s, %s
        )
        ON CONFLICT (agencia_id, telefono) DO UPDATE
        SET updated_at = chatbot.chatbot_aspirantes.updated_at
        RETURNING *
        """,
        (agencia_id, whatsapp_account_id, telefono, ETAPA_INICIO, message_id_meta),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(
            f"INSERT chatbot_aspirantes no retornó fila "
            f"(agencia_id={agencia_id}, telefono={telefono})"
        )
    return dict(row)


def crear_o_obtener_aspirante(
    *,
    agencia_id: int,
    whatsapp_account_id: int,
    telefono: str,
) -> Dict[str, Any]:
    """
    Transacción completa: busca o crea aspirante y hace commit.
    """
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            existente = aspirante_for_update(cur, agencia_id, telefono)
            if existente:
                return dict(existente)
            creado = crear_aspirante(
                cur,
                agencia_id=agencia_id,
                whatsapp_account_id=whatsapp_account_id,
                telefono=telefono,
                message_id_meta=None,
            )
            logger.info(
                "[CHATBOT] aspirante creado id=%s agencia_id=%s tel=%s",
                creado.get("id"),
                agencia_id,
                telefono,
            )
            return creado


def actualizar_aspirante_flujo(cur, aspirante_id: int, campos: Dict[str, Any]) -> Dict[str, Any]:
    if not campos:
        cur.execute(
            "SELECT * FROM chatbot.chatbot_aspirantes WHERE id = %s",
            (aspirante_id,),
        )
        return dict(cur.fetchone())

    sets = []
    params: List[Any] = []
    for key, value in campos.items():
        sets.append(f"{key} = %s")
        params.append(value)
    sets.append("ultima_interaccion = CURRENT_TIMESTAMP")
    sets.append("updated_at = CURRENT_TIMESTAMP")
    params.append(aspirante_id)

    cur.execute(
        f"""
        UPDATE chatbot.chatbot_aspirantes
        SET {", ".join(sets)}
        WHERE id = %s
        RETURNING *
        """,
        params,
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"UPDATE chatbot_aspirantes id={aspirante_id} no retornó fila")
    return dict(row)


def claim_incoming_wamid(
    aspirante_id: int,
    message_id_meta: str,
) -> bool:
    """
    Reserva atómica del wamid entrante en chatbot_aspirantes.

    True  → este worker puede procesar el mensaje.
    False → otro request ya reclamó el mismo incoming_wamid.
    """
    mid = str(message_id_meta or "").strip()
    if not mid:
        # Sin id de Meta no hay idempotencia posible; no bloquear.
        return True

    with get_connection_chatbot_context() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE chatbot.chatbot_aspirantes
                SET ultimo_message_id_meta = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                  AND (
                    ultimo_message_id_meta IS NULL
                    OR ultimo_message_id_meta IS DISTINCT FROM %s
                  )
                RETURNING id
                """,
                (mid, int(aspirante_id), mid),
            )
            return cur.fetchone() is not None


def actualizar_aspirante_flujo_commit(
    aspirante_id: int,
    campos: Dict[str, Any],
) -> Dict[str, Any]:
    """Actualiza progreso y confirma la transacción."""
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            return actualizar_aspirante_flujo(cur, aspirante_id, campos)


def parse_faqs(raw: Any) -> List[Dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if isinstance(raw, list):
        return [dict(x) for x in raw if isinstance(x, dict)]
    return []


def parse_recursos_bienvenida(raw: Any) -> List[Dict[str, Any]]:
    return parse_faqs(raw)
