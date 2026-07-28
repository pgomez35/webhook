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


def obtener_configuracion_activa(agencia_id: int) -> Optional[Dict[str, Any]]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT *
                FROM chatbot.chatbot_configuracion
                WHERE agencia_id = %s
                  AND activo = TRUE
                LIMIT 1
                """,
                (agencia_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def obtener_configuracion_por_agencia(agencia_id: int) -> Optional[Dict[str, Any]]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT *
                FROM chatbot.chatbot_configuracion
                WHERE agencia_id = %s
                LIMIT 1
                """,
                (agencia_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def crear_configuracion_default(agencia_id: int) -> Dict[str, Any]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO chatbot.chatbot_configuracion (agencia_id)
                VALUES (%s)
                ON CONFLICT (agencia_id) DO UPDATE
                SET updated_at = chatbot.chatbot_configuracion.updated_at
                RETURNING *
                """,
                (agencia_id,),
            )
            return dict(cur.fetchone())


def actualizar_configuracion(agencia_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    faqs = data.get("preguntas_frecuentes") or []
    if isinstance(faqs, list):
        faqs_json = Json([
            f.model_dump() if hasattr(f, "model_dump") else f
            for f in faqs
        ])
    else:
        faqs_json = Json(faqs)

    recursos = data.get("recursos_bienvenida") or []
    if isinstance(recursos, list):
        recursos_json = Json([
            r.model_dump() if hasattr(r, "model_dump") else r
            for r in recursos
        ])
    else:
        recursos_json = Json(recursos)

    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE chatbot.chatbot_configuracion
                SET
                    activo = %s,
                    mensaje_bienvenida = %s,
                    pregunta_usuario = %s,
                    pregunta_mayor_edad = %s,
                    pregunta_disponibilidad = %s,
                    mensaje_aprobado = %s,
                    mensaje_no_aprobado = %s,
                    texto_boton_continuar = %s,
                    accion_continuar = %s,
                    url_continuar = %s,
                    texto_boton_preguntas = %s,
                    preguntas_frecuentes = %s,
                    recursos_bienvenida = %s,
                    mensaje_error = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE agencia_id = %s
                RETURNING *
                """,
                (
                    data["activo"],
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
                    faqs_json,
                    recursos_json,
                    data["mensaje_error"],
                    agencia_id,
                ),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Configuración no encontrada")
            return dict(row)


def actualizar_recursos_bienvenida(
    agencia_id: int,
    recursos: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Actualiza solo recursos_bienvenida (p. ej. tras DELETE media)."""
    recursos_json = Json(list(recursos or []))
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE chatbot.chatbot_configuracion
                SET
                    recursos_bienvenida = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE agencia_id = %s
                RETURNING *
                """,
                (recursos_json, agencia_id),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Configuración no encontrada")
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
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    whatsapp_account_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
    order: str = "fecha_registro_desc",
) -> Tuple[int, List[Dict[str, Any]]]:
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
        where.append("a.plataforma = %s")
        params.append(plataforma)
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

    order_sql = "a.fecha_registro DESC"
    if order == "fecha_registro_asc":
        order_sql = "a.fecha_registro ASC"
    elif order == "ultima_interaccion_desc":
        order_sql = "a.ultima_interaccion DESC"

    where_sql = " AND ".join(where)
    offset = max(page - 1, 0) * page_size

    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT COUNT(*)::int AS total FROM chatbot.chatbot_aspirantes a WHERE {where_sql}",
                params,
            )
            total = (cur.fetchone() or {}).get("total") or 0

            cur.execute(
                f"""
                SELECT
                    a.*,
                    w.phone_number AS phone_number_origen,
                    w.business_name AS business_name_origen
                FROM chatbot.chatbot_aspirantes a
                LEFT JOIN public.whatsapp_business_accounts w
                    ON w.id = a.whatsapp_account_id
                WHERE {where_sql}
                ORDER BY {order_sql}
                LIMIT %s OFFSET %s
                """,
                params + [page_size, offset],
            )
            rows = [dict(r) for r in (cur.fetchall() or [])]
            return total, rows


def obtener_aspirante(agencia_id: int, aspirante_id: int) -> Optional[Dict[str, Any]]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    a.*,
                    w.phone_number AS phone_number_origen,
                    w.business_name AS business_name_origen
                FROM chatbot.chatbot_aspirantes a
                LEFT JOIN public.whatsapp_business_accounts w
                    ON w.id = a.whatsapp_account_id
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
            plataforma,
            estado,
            etapa_chatbot,
            ultimo_message_id_meta
        ) VALUES (
            %s, %s, %s, 'tiktok', 'nuevo', %s, %s
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
