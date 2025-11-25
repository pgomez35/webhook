import re
from psycopg2.extras import RealDictCursor
from DataBase import get_connection_public_context

def guardar_o_actualizar_waba_db(session_id: str | None, waba_id: str):
    try:
        with get_connection_public_context() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 🔍 Buscar si existe registro previo con token pero sin WABA
                cur.execute("""
                    SELECT id, access_token
                    FROM whatsapp_business_accounts
                    WHERE session_id = %s
                      AND waba_id IS NULL
                      AND access_token IS NOT NULL
                      AND created_at >= NOW() - INTERVAL '10 minutes'
                    ORDER BY created_at DESC
                    LIMIT 1;
                """, (session_id,))
                existente = cur.fetchone()

                if existente:
                    # 🔄 Actualizar el waba_id
                    cur.execute("""
                        UPDATE whatsapp_business_accounts
                        SET waba_id = %s,
                            updated_at = NOW()
                        WHERE id = %s;
                    """, (waba_id, existente["id"]))

                    print(f"🔄 WABA actualizado en DB (ID: {existente['id']}) → {waba_id}")
                    return {
                        "status": "completado",
                        "id": existente["id"],
                        "access_token": existente.get("access_token"),
                        "waba_id": waba_id
                    }

                # 🆕 Si no existe, insertar nuevo registro
                cur.execute("""
                    INSERT INTO whatsapp_business_accounts (
                        waba_id, session_id, created_at, updated_at
                    ) VALUES (%s, %s, NOW(), NOW())
                    RETURNING id, waba_id;
                """, (waba_id, session_id))
                nuevo = cur.fetchone()

                print(f"🆕 Nuevo WABA guardado en DB (ID: {nuevo['id']}) → {waba_id}")
                return {"status": "inserted", "id": nuevo["id"], "waba_id": nuevo["waba_id"]}

    except Exception as e:
        print("❌ Error en guardar_o_actualizar_waba_db:", e)
        return {"status": "error", "error": str(e)}

def actualizar_phone_info_db(
    id: int,
    phone_number: str | None = None,
    phone_number_id: str | None = None,
    status: str = "connected"
) -> bool:
    try:

        # 🔹 Normalizar número: solo dígitos
        phone_number = re.sub(r'\D', '', phone_number or "")

        with get_connection_public_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE whatsapp_business_accounts
                    SET
                        phone_number = %s,
                        phone_number_id = %s,
                        status = %s,
                        updated_at = NOW()
                    WHERE id = %s;
                """, (phone_number, phone_number_id, status, id))

        print(f"✅ Registro WABA (id={id}) actualizado correctamente.")
        return True

    except Exception as e:
        print("❌ Error al actualizar información WABA en la base de datos:", e)
        return False
