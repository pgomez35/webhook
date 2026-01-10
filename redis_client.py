import os
import redis
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL")


def create_redis_client():
    if REDIS_URL:
        print("🔧 Usando REDIS_URL:", REDIS_URL)
        # No TLS, según el ejemplo de Redis Cloud
        return redis.from_url(
            REDIS_URL,
            decode_responses=True,
        )
    else:
        # Fallback local
        REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
        REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
        REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

        return redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD,
            db=0,
            decode_responses=True,
        )


r = create_redis_client()


def get_redis():
    return r


# ============================
# FUNCIONES PARA usuarios_temp
# ============================

def redis_set_temp(numero: str, aspirante_data: dict, ttl: int = 900):
    """
    Guarda datos temporales del aspirante en Redis.
    
    Args:
        numero: Número de teléfono
        aspirante_data: Dict con {"id": int, ...} del aspirante
        ttl: Tiempo de vida en segundos (default: 15 min = 900 seg)
    
    Nota: NO persiste en BD porque es muy temporal y no crítico.
          Si se pierde, el usuario puede volver a empezar.
    """
    import json
    key = f"temp:{numero}"  # Clave optimizada
    
    try:
        # Solo guardar los datos necesarios (minimizar memoria)
        data = {
            "id": aspirante_data.get("id")
        }
        # Agregar datos adicionales si existen
        if "usuario" in aspirante_data:
            data["usuario"] = aspirante_data["usuario"]
        if "nombre_real" in aspirante_data:
            data["nombre_real"] = aspirante_data["nombre_real"]
        if "nickname" in aspirante_data:
            data["nickname"] = aspirante_data["nickname"]
        
        # Comprimir JSON (sin espacios)
        json_str = json.dumps(data, separators=(',', ':'))
        r.setex(key, ttl, json_str)
        print(f"✅ Datos temporales guardados en Redis para {numero} (TTL: {ttl}s)")
    except Exception as e:
        print(f"⚠️ Error guardando temp en Redis para {numero}: {e}")
        # No crítico, puede continuar sin caché
        raise


def redis_get_temp(numero: str) -> dict | None:
    """
    Obtiene datos temporales del aspirante desde Redis.
    
    Args:
        numero: Número de teléfono
    
    Returns:
        Dict con {"id": int, ...} o None si no existe/expió
    
    Nota: Si Redis falla, retorna None (no hay fallback a BD porque
          no es crítico y el usuario puede volver a empezar).
    """
    import json
    key = f"temp:{numero}"
    
    try:
        data = r.get(key)
        if data:
            return json.loads(data)
        return None
    except Exception as e:
        print(f"⚠️ Error leyendo temp de Redis para {numero}: {e}")
        return None


def redis_delete_temp(numero: str):
    """
    Elimina datos temporales de Redis (después de confirmar).
    
    Args:
        numero: Número de teléfono
    """
    key = f"temp:{numero}"
    try:
        r.delete(key)
        print(f"🗑️ Datos temporales eliminados de Redis para {numero}")
    except Exception as e:
        print(f"⚠️ Error eliminando temp de Redis para {numero}: {e}")


# ----------------------------------------
# ----------------------------------------
# ----------------------------------------
# ----------------------------------------
# ----------------------------------------

# ============================
# FUNCIONES PARA CONTROL DE FLUJO (Pasos simples)
# ============================

def actualizar_flujo(numero: str, paso: str, ttl: int = 600):
    """
    Guarda el paso actual de la conversación (String simple).
    TTL default: 10 minutos (600s).
    """
    key = f"flow:{numero}"
    try:
        r.setex(key, ttl, paso)
        print(f"⏳ Redis: Usuario {numero} en paso temporal '{paso}'")
    except Exception as e:
        print(f"⚠️ Error Redis actualizar_flujo: {e}")

def obtener_flujo(numero: str) -> str | None:
    """Retorna el paso actual (String) o None."""
    key = f"flow:{numero}"
    try:
        return r.get(key)
    except Exception as e:
        print(f"⚠️ Error Redis obtener_flujo: {e}")
        return None

def eliminar_flujo(numero: str):
    """Borra el paso actual."""
    key = f"flow:{numero}"
    try:
        r.delete(key)
        print(f"🗑️ Flujo temporal eliminado para {numero}")
    except Exception as e:
        print(f"⚠️ Error Redis eliminar_flujo: {e}")