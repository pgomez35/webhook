from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import os, json
from dotenv import load_dotenv
from enviar_msg_wp import enviar_plantilla_generica, enviar_mensaje_texto_simple
from main import guardar_mensaje
import psycopg2

load_dotenv()

# Configuración
TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_ID")
DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")  # 🔹 corregido nombre

router = APIRouter()

# --- Flujo guiado ---
preguntas = {
    1: "📌 ¿Cuál es tu nombre completo?",
    2: "📌 ¿Cuál es tu edad?",
    3: "📌 Género:\n1. Masculino\n2. Femenino\n3. Otro\n4. Prefiero no decir",
    4: "📌 País:\n1. Argentina\n2. Bolivia\n3. Chile\n4. Colombia\n5. Costa Rica\n6. Cuba\n7. Ecuador\n8. El Salvador\n9. Guatemala\n10. Honduras\n11. México\n12. Nicaragua\n13. Panamá\n14. Paraguay\n15. Perú\n16. Puerto Rico\n17. República Dominicana\n18. Uruguay\n19. Venezuela",
    5: "📌 Ciudad (escribe tu ciudad principal)",
    6: "📌 Nivel de estudios:\n1. Ninguno\n2. Primaria completa\n3. Secundaria completa\n4. Técnico o tecnólogo\n5. Universitario incompleto\n6. Universitario completo\n7. Postgrado / Especialización\n8. Autodidacta / Formación no formal\n9. Otro (especificar)",
    7: "📌 Idioma principal:\n1. Español\n2. Inglés\n3. Portugués\n4. Francés\n5. Italiano\n6. Alemán\n7. Otro (especificar)",
    8: "📌 Actividad actual:\n1. Estudia tiempo completo\n2. Estudia medio tiempo\n3. Trabaja tiempo completo\n4. Trabaja medio tiempo\n5. Buscando empleo\n6. Emprendiendo\n7. Disponible tiempo completo\n8. Otro"
}

usuarios_flujo = {}  # { numero: paso_actual }


def enviar_pregunta(numero: str, paso: int):
    texto = preguntas[paso]
    codigo, respuesta_api = enviar_mensaje_texto_simple(
        token=TOKEN,
        numero_id=PHONE_NUMBER_ID,
        telefono_destino=numero,
        texto=texto
    )
    guardar_mensaje(numero, f"[Pregunta enviada: {texto}]", "enviado")
    return codigo, respuesta_api


@router.post("/enviar_solicitud_informacion")
async def api_enviar_solicitar_informacion(data: dict):
    telefono = data.get("telefono")
    nombre = data.get("nombre", "").strip()

    if not telefono or not nombre:
        return JSONResponse({"error": "Faltan datos (telefono o nombre)"}, status_code=400)

    try:
        plantilla = "solicitar_informacion"
        parametros = [nombre]

        codigo, respuesta_api = enviar_plantilla_generica(
            token=TOKEN,
            phone_number_id=PHONE_NUMBER_ID,
            numero_destino=telefono,
            nombre_plantilla=plantilla,
            codigo_idioma="es_CO",
            parametros=parametros
        )

        guardar_mensaje(
            telefono,
            f"[Plantilla enviada: {plantilla} - {parametros}]",
            tipo="enviado"
        )

        return {
            "status": "ok",
            "mensaje": f"Se envió la plantilla {plantilla} a {telefono}",
            "codigo_api": codigo,
            "respuesta_api": respuesta_api
        }

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/webhook")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    print("📩 Webhook recibido:", json.dumps(data, indent=2))

    try:
        mensajes = data["entry"][0]["changes"][0]["value"].get("messages", [])
        for mensaje in mensajes:
            numero = mensaje["from"]

            # Botón "continuar"
            if mensaje.get("type") == "button":
                boton_texto = mensaje["button"]["text"]
                if boton_texto.lower() == "sí, continuar":  # puedes comparar por texto
                    usuarios_flujo[numero] = 1  # iniciamos en paso 1
                    enviar_pregunta(numero, 1)

            # Mensaje de texto
            elif "text" in mensaje:
                texto = mensaje["text"]["body"].strip().lower()
                print(f"📥 Texto recibido de {numero}: {texto}")

                if numero in usuarios_flujo:
                    paso = usuarios_flujo[numero]
                    guardar_respuesta(numero, paso, texto)

                    if paso < len(preguntas):
                        usuarios_flujo[numero] += 1
                        enviar_pregunta(numero, usuarios_flujo[numero])
                    else:
                        del usuarios_flujo[numero]
                        enviar_mensaje_texto_simple(
                            token=TOKEN,
                            numero_id=PHONE_NUMBER_ID,
                            telefono_destino=numero,
                            texto="✅ Gracias, completaste todas las preguntas."
                        )
                        consolidar_perfil(numero)

                else:
                    # Mensaje fuera de flujo
                    if texto in ["hola", "buenas", "hey", "holi", "qué más", "que mas"]:
                        usuarios_flujo[numero] = 1
                        enviar_mensaje_texto_simple(
                            token=TOKEN,
                            numero_id=PHONE_NUMBER_ID,
                            telefono_destino=numero,
                            texto="👋 Hola! Iniciemos el flujo de preguntas:"
                        )
                        enviar_pregunta(numero, 1)
                    else:
                        enviar_mensaje_texto_simple(
                            token=TOKEN,
                            numero_id=PHONE_NUMBER_ID,
                            telefono_destino=numero,
                            texto="⚠️ No entendí tu mensaje. Escribe *hola* o presiona *Continuar* para iniciar."
                        )
                        guardar_respuesta(numero, 0, f"[Fuera de flujo]: {texto}")  # 🔹 corregido

    except Exception as e:
        print("❌ Error procesando webhook:", e)

    return {"status": "ok"}


def guardar_respuesta(numero: str, paso: int, texto: str):
    """
    Guarda la respuesta del usuario en la base de datos.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO perfil_creador_flujo_temp (telefono, paso, respuesta)
            VALUES (%s, %s, %s)
            ON CONFLICT (telefono, paso) DO UPDATE SET respuesta = EXCLUDED.respuesta
        """, (numero, paso, texto))
        conn.commit()
        cur.close()
        conn.close()
        print(f">>> Guardada respuesta paso {paso} de {numero}: {texto}")
    except Exception as e:
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        print("❌ Error guardando respuesta:", e)


def consolidar_perfil(numero: str):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        cur.execute("""
            SELECT paso, respuesta 
            FROM perfil_creador_flujo_temp 
            WHERE telefono = %s 
            ORDER BY paso ASC
        """, (numero,))
        respuestas = cur.fetchall()

        datos = {paso: resp for paso, resp in respuestas}

        cur.execute("""
            INSERT INTO perfil_creador (nombre, edad, genero, pais, ciudad, estudios, idioma, actividad, telefono)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            datos.get(1),
            datos.get(2),
            datos.get(3),
            datos.get(4),
            datos.get(5),
            datos.get(6),
            datos.get(7),
            datos.get(8),
            numero
        ))

        cur.execute("DELETE FROM perfil_creador_flujo_temp WHERE telefono = %s", (numero,))
        conn.commit()

        cur.close()
        conn.close()
        print(f"✅ Perfil consolidado para {numero}")
    except Exception as e:
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        print("❌ Error al consolidar perfil:", str(e))
