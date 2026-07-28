"""
Administración de clientes chatbot (schema chatbot) desde Talentum Manager.
No escribe en tablas de agencias de Talentum Manager.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from psycopg2.extras import RealDictCursor, Json

from DataBase import get_connection_chatbot_context, hash_password
from database_chatbot_captacion import normalizar_product_type

logger = logging.getLogger("uvicorn.error")

CODIGO_RE = re.compile(r"^[A-Za-z0-9_-]{2,80}$")


def _safe_agencia_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    out = dict(row)
    out.pop("password_hash", None)
    return out


def listar_agencias_admin() -> List[Dict[str, Any]]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    a.id,
                    a.nombre,
                    a.codigo,
                    a.estado,
                    a.usuario_login,
                    a.login_activo,
                    a.debe_cambiar_clave,
                    a.ultimo_login,
                    a.created_at,
                    a.updated_at,
                    aw.whatsapp_account_id,
                    aw.principal AS waba_principal,
                    aw.activo AS waba_relacion_activa,
                    w.business_name AS waba_business_name,
                    w.phone_number AS waba_phone_number,
                    w.phone_number_id AS waba_phone_number_id,
                    w.status AS waba_status,
                    w.product_type AS waba_product_type,
                    COALESCE(asp.total_aspirantes, 0)::int AS total_aspirantes,
                    COALESCE(asp.requieren_asesor, 0)::int AS requieren_asesor
                FROM chatbot.agencias a
                LEFT JOIN chatbot.agencia_whatsapp_accounts aw
                    ON aw.agencia_id = a.id AND aw.principal = TRUE
                LEFT JOIN public.whatsapp_business_accounts w
                    ON w.id = aw.whatsapp_account_id
                LEFT JOIN (
                    SELECT
                        agencia_id,
                        COUNT(*)::int AS total_aspirantes,
                        COUNT(*) FILTER (WHERE requiere_asesor IS TRUE)::int AS requieren_asesor
                    FROM chatbot.chatbot_aspirantes
                    GROUP BY agencia_id
                ) asp ON asp.agencia_id = a.id
                ORDER BY a.id ASC
                """
            )
            rows = [dict(r) for r in (cur.fetchall() or [])]
            for r in rows:
                r.pop("password_hash", None)
            return rows


def obtener_agencia_admin(agencia_id: int) -> Optional[Dict[str, Any]]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    a.id, a.nombre, a.codigo, a.estado,
                    a.usuario_login, a.login_activo, a.debe_cambiar_clave,
                    a.ultimo_login, a.created_at, a.updated_at,
                    aw.whatsapp_account_id,
                    aw.principal AS waba_principal,
                    aw.activo AS waba_relacion_activa,
                    w.business_name AS waba_business_name,
                    w.phone_number AS waba_phone_number,
                    w.phone_number_id AS waba_phone_number_id,
                    w.status AS waba_status,
                    w.product_type AS waba_product_type,
                    COALESCE(asp.total_aspirantes, 0)::int AS total_aspirantes,
                    COALESCE(asp.requieren_asesor, 0)::int AS requieren_asesor
                FROM chatbot.agencias a
                LEFT JOIN chatbot.agencia_whatsapp_accounts aw
                    ON aw.agencia_id = a.id AND aw.principal = TRUE
                LEFT JOIN public.whatsapp_business_accounts w
                    ON w.id = aw.whatsapp_account_id
                LEFT JOIN (
                    SELECT
                        agencia_id,
                        COUNT(*)::int AS total_aspirantes,
                        COUNT(*) FILTER (WHERE requiere_asesor IS TRUE)::int AS requieren_asesor
                    FROM chatbot.chatbot_aspirantes
                    WHERE agencia_id = %s
                    GROUP BY agencia_id
                ) asp ON asp.agencia_id = a.id
                WHERE a.id = %s
                LIMIT 1
                """,
                (agencia_id, agencia_id),
            )
            return _safe_agencia_row(cur.fetchone())


def obtener_resumen_agencia_admin(agencia_id: int) -> Optional[Dict[str, Any]]:
    """Resumen de soporte (sin edición operativa de mensajes/FAQ/media)."""
    agencia = obtener_agencia_admin(agencia_id)
    if not agencia:
        return None

    config_activa = None
    config_completa = False
    total_faqs = 0
    total_recursos = 0
    config_updated_at = None
    cfg = None

    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    activo,
                    mensaje_bienvenida,
                    pregunta_usuario,
                    pregunta_mayor_edad,
                    pregunta_disponibilidad,
                    mensaje_aprobado,
                    mensaje_no_aprobado,
                    preguntas_frecuentes,
                    recursos_bienvenida,
                    updated_at
                FROM chatbot.chatbot_configuracion
                WHERE agencia_id = %s
                LIMIT 1
                """,
                (agencia_id,),
            )
            cfg = cur.fetchone()

    if cfg:
        config_activa = bool(cfg.get("activo"))
        config_updated_at = cfg.get("updated_at")
        faqs = cfg.get("preguntas_frecuentes") or []
        recursos = cfg.get("recursos_bienvenida") or []
        if not isinstance(faqs, list):
            faqs = []
        if not isinstance(recursos, list):
            recursos = []
        total_faqs = len(faqs)
        total_recursos = len(recursos)
        campos = [
            cfg.get("mensaje_bienvenida"),
            cfg.get("pregunta_usuario"),
            cfg.get("pregunta_mayor_edad"),
            cfg.get("pregunta_disponibilidad"),
            cfg.get("mensaje_aprobado"),
            cfg.get("mensaje_no_aprobado"),
        ]
        config_completa = all(bool(str(c or "").strip()) for c in campos)

    return {
        "agencia": agencia,
        "configuracion": {
            "existe": cfg is not None,
            "activa": config_activa,
            "completa": config_completa if cfg else False,
            "total_preguntas_frecuentes": total_faqs,
            "total_recursos": total_recursos,
            "updated_at": config_updated_at,
        },
        "aspirantes": {
            "total": int(agencia.get("total_aspirantes") or 0),
            "requieren_asesor": int(agencia.get("requieren_asesor") or 0),
        },
    }


def _assert_codigo_unico(cur, codigo: str, exclude_id: Optional[int] = None) -> None:
    if exclude_id:
        cur.execute(
            """
            SELECT id FROM chatbot.agencias
            WHERE LOWER(TRIM(codigo)) = LOWER(TRIM(%s)) AND id <> %s
            LIMIT 1
            """,
            (codigo, exclude_id),
        )
    else:
        cur.execute(
            """
            SELECT id FROM chatbot.agencias
            WHERE LOWER(TRIM(codigo)) = LOWER(TRIM(%s))
            LIMIT 1
            """,
            (codigo,),
        )
    if cur.fetchone():
        raise ValueError(f"Ya existe una agencia chatbot con código '{codigo}'")


def _assert_usuario_unico(cur, usuario: str, exclude_id: Optional[int] = None) -> None:
    if not usuario:
        return
    if exclude_id:
        cur.execute(
            """
            SELECT id FROM chatbot.agencias
            WHERE LOWER(TRIM(usuario_login)) = LOWER(TRIM(%s)) AND id <> %s
            LIMIT 1
            """,
            (usuario, exclude_id),
        )
    else:
        cur.execute(
            """
            SELECT id FROM chatbot.agencias
            WHERE LOWER(TRIM(usuario_login)) = LOWER(TRIM(%s))
            LIMIT 1
            """,
            (usuario,),
        )
    if cur.fetchone():
        raise ValueError(f"usuario_login '{usuario}' ya está en uso")


def _obtener_waba_chatbot(cur, whatsapp_account_id: int) -> Dict[str, Any]:
    cur.execute(
        """
        SELECT id, business_name, phone_number, phone_number_id, status, product_type
        FROM public.whatsapp_business_accounts
        WHERE id = %s
        LIMIT 1
        """,
        (whatsapp_account_id,),
    )
    row = cur.fetchone()
    if not row:
        raise ValueError(f"No existe whatsapp_business_accounts id={whatsapp_account_id}")
    data = dict(row)
    pt = normalizar_product_type(data.get("product_type"))
    if pt != "chatbot":
        raise ValueError(
            f"Solo se pueden vincular cuentas con product_type=chatbot "
            f"(recibido: {pt})"
        )
    data["product_type"] = pt
    return data


def _vincular_waba_cur(cur, agencia_id: int, whatsapp_account_id: int) -> None:
    waba = _obtener_waba_chatbot(cur, whatsapp_account_id)

    cur.execute(
        """
        SELECT agencia_id
        FROM chatbot.agencia_whatsapp_accounts
        WHERE whatsapp_account_id = %s
        LIMIT 1
        """,
        (whatsapp_account_id,),
    )
    otra = cur.fetchone()
    if otra and int(otra["agencia_id"]) != int(agencia_id):
        raise ValueError(
            f"La WABA id={whatsapp_account_id} ya está vinculada a otra agencia "
            f"chatbot (agencia_id={otra['agencia_id']})"
        )

    # Desmarcar otras principales de esta agencia
    cur.execute(
        """
        UPDATE chatbot.agencia_whatsapp_accounts
        SET principal = FALSE, updated_at = CURRENT_TIMESTAMP
        WHERE agencia_id = %s AND whatsapp_account_id <> %s
        """,
        (agencia_id, whatsapp_account_id),
    )

    cur.execute(
        """
        INSERT INTO chatbot.agencia_whatsapp_accounts (
            agencia_id, whatsapp_account_id, principal, activo
        ) VALUES (%s, %s, TRUE, TRUE)
        ON CONFLICT (whatsapp_account_id) DO UPDATE
        SET agencia_id = EXCLUDED.agencia_id,
            principal = TRUE,
            activo = TRUE,
            updated_at = CURRENT_TIMESTAMP
        """,
        (agencia_id, whatsapp_account_id),
    )
    logger.info(
        "[ADMIN-CHATBOT] waba vinculada agencia_id=%s whatsapp_account_id=%s "
        "product_type=%s",
        agencia_id,
        whatsapp_account_id,
        waba.get("product_type"),
    )


def crear_agencia_completa(
    *,
    nombre: str,
    codigo: str,
    usuario_login: Optional[str],
    password_temporal: Optional[str],
    estado: str = "activa",
    login_activo: bool = True,
    debe_cambiar_clave: bool = True,
    whatsapp_account_id: Optional[int] = None,
) -> Dict[str, Any]:
    nombre = (nombre or "").strip()
    codigo = (codigo or "").strip()
    usuario = (usuario_login or "").strip().lower() or None

    if not nombre:
        raise ValueError("nombre es obligatorio")
    if not codigo or not CODIGO_RE.match(codigo):
        raise ValueError(
            "codigo inválido (2-80 caracteres: letras, números, _ o -)"
        )
    if password_temporal is not None and len(password_temporal) < 8:
        raise ValueError("contraseña temporal mínimo 8 caracteres")
    if password_temporal and not usuario:
        raise ValueError("usuario_login es obligatorio si hay contraseña temporal")

    pwd_hash = hash_password(password_temporal) if password_temporal else None

    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _assert_codigo_unico(cur, codigo)
            if usuario:
                _assert_usuario_unico(cur, usuario)

            cur.execute(
                """
                INSERT INTO chatbot.agencias (
                    nombre, codigo, estado,
                    usuario_login, password_hash,
                    login_activo, debe_cambiar_clave
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, nombre, codigo, estado, usuario_login,
                          login_activo, debe_cambiar_clave, ultimo_login,
                          created_at, updated_at
                """,
                (
                    nombre,
                    codigo,
                    estado or "activa",
                    usuario,
                    pwd_hash,
                    bool(login_activo),
                    bool(debe_cambiar_clave),
                ),
            )
            agencia = dict(cur.fetchone())
            agencia_id = agencia["id"]

            if whatsapp_account_id is not None:
                _vincular_waba_cur(cur, agencia_id, int(whatsapp_account_id))

            cur.execute(
                """
                INSERT INTO chatbot.chatbot_configuracion (agencia_id)
                VALUES (%s)
                ON CONFLICT (agencia_id) DO UPDATE
                SET updated_at = chatbot.chatbot_configuracion.updated_at
                RETURNING agencia_id
                """,
                (agencia_id,),
            )

            logger.info(
                "[ADMIN-CHATBOT] agencia creada agencia_id=%s codigo=%s "
                "admin_op=crear",
                agencia_id,
                codigo,
            )
            return obtener_agencia_admin(agencia_id) or agencia


def actualizar_agencia_admin(
    agencia_id: int,
    *,
    nombre: Optional[str] = None,
    codigo: Optional[str] = None,
    estado: Optional[str] = None,
    usuario_login: Optional[str] = None,
    password_temporal: Optional[str] = None,
    login_activo: Optional[bool] = None,
    debe_cambiar_clave: Optional[bool] = None,
) -> Dict[str, Any]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id FROM chatbot.agencias WHERE id = %s LIMIT 1",
                (agencia_id,),
            )
            if not cur.fetchone():
                raise ValueError(f"No existe agencia id={agencia_id}")

            sets: List[str] = []
            params: List[Any] = []

            if nombre is not None:
                n = nombre.strip()
                if not n:
                    raise ValueError("nombre no puede estar vacío")
                sets.append("nombre = %s")
                params.append(n)

            if codigo is not None:
                c = codigo.strip()
                if not CODIGO_RE.match(c):
                    raise ValueError("codigo inválido")
                _assert_codigo_unico(cur, c, exclude_id=agencia_id)
                sets.append("codigo = %s")
                params.append(c)

            if estado is not None:
                sets.append("estado = %s")
                params.append(estado.strip())

            if usuario_login is not None:
                u = usuario_login.strip().lower()
                if not u:
                    raise ValueError("usuario_login no puede estar vacío")
                _assert_usuario_unico(cur, u, exclude_id=agencia_id)
                sets.append("usuario_login = %s")
                params.append(u)

            if password_temporal is not None:
                if len(password_temporal) < 8:
                    raise ValueError("contraseña temporal mínimo 8 caracteres")
                sets.append("password_hash = %s")
                params.append(hash_password(password_temporal))

            if login_activo is not None:
                sets.append("login_activo = %s")
                params.append(bool(login_activo))

            if debe_cambiar_clave is not None:
                sets.append("debe_cambiar_clave = %s")
                params.append(bool(debe_cambiar_clave))

            if not sets:
                raise ValueError("No hay campos para actualizar")

            sets.append("updated_at = CURRENT_TIMESTAMP")
            params.append(agencia_id)
            cur.execute(
                f"""
                UPDATE chatbot.agencias
                SET {", ".join(sets)}
                WHERE id = %s
                RETURNING id
                """,
                params,
            )
            logger.info(
                "[ADMIN-CHATBOT] agencia actualizada agencia_id=%s",
                agencia_id,
            )
    out = obtener_agencia_admin(agencia_id)
    if not out:
        raise ValueError("Agencia no encontrada tras actualizar")
    return out


def restablecer_password_admin(agencia_id: int, password_temporal: str) -> Dict[str, Any]:
    if len(password_temporal or "") < 8:
        raise ValueError("contraseña temporal mínimo 8 caracteres")
    pwd_hash = hash_password(password_temporal)
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE chatbot.agencias
                SET password_hash = %s,
                    debe_cambiar_clave = TRUE,
                    login_activo = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id, nombre, codigo, usuario_login,
                          login_activo, debe_cambiar_clave
                """,
                (pwd_hash, agencia_id),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"No existe agencia id={agencia_id}")
            logger.info(
                "[ADMIN-CHATBOT] password restablecida agencia_id=%s",
                agencia_id,
            )
            return _safe_agencia_row(row) or dict(row)


def set_login_activo(agencia_id: int, login_activo: bool) -> Dict[str, Any]:
    return actualizar_agencia_admin(agencia_id, login_activo=login_activo)


def vincular_waba_admin(agencia_id: int, whatsapp_account_id: int) -> Dict[str, Any]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id FROM chatbot.agencias WHERE id = %s LIMIT 1",
                (agencia_id,),
            )
            if not cur.fetchone():
                raise ValueError(f"No existe agencia id={agencia_id}")
            _vincular_waba_cur(cur, agencia_id, int(whatsapp_account_id))
    out = obtener_agencia_admin(agencia_id)
    if not out:
        raise ValueError("Agencia no encontrada")
    return out


def listar_wabas_chatbot_disponibles(
    *,
    incluir_vinculadas: bool = True,
) -> List[Dict[str, Any]]:
    with get_connection_chatbot_context() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    w.id,
                    w.business_name,
                    w.phone_number,
                    w.phone_number_id,
                    w.status,
                    w.product_type,
                    aw.agencia_id AS vinculada_agencia_id,
                    a.nombre AS vinculada_agencia_nombre,
                    a.codigo AS vinculada_agencia_codigo
                FROM public.whatsapp_business_accounts w
                LEFT JOIN chatbot.agencia_whatsapp_accounts aw
                    ON aw.whatsapp_account_id = w.id
                LEFT JOIN chatbot.agencias a
                    ON a.id = aw.agencia_id
                WHERE LOWER(TRIM(COALESCE(w.product_type, ''))) = 'chatbot'
                ORDER BY COALESCE(w.business_name, ''), w.id
                """
            )
            rows = [dict(r) for r in (cur.fetchall() or [])]
            # Nunca exponer tokens
            for r in rows:
                r.pop("access_token", None)
                r.pop("access_token_encrypted", None)
            if not incluir_vinculadas:
                rows = [r for r in rows if not r.get("vinculada_agencia_id")]
            return rows


def obtener_configuracion_admin(agencia_id: int) -> Dict[str, Any]:
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
            row = cur.fetchone()
            if not row:
                raise ValueError("No se pudo obtener configuración")
            return dict(row)


def actualizar_configuracion_admin(
    agencia_id: int,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    # Reutiliza la lógica de actualización existente
    from database_chatbot_captacion import (
        actualizar_configuracion,
        crear_configuracion_default,
        obtener_configuracion_por_agencia,
    )

    if not obtener_configuracion_por_agencia(agencia_id):
        crear_configuracion_default(agencia_id)
    return actualizar_configuracion(agencia_id, data)
