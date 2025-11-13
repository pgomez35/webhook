import os
import redis
from dotenv import load_dotenv

load_dotenv()


# Usa REDIS_URL si existe (ej. rediss://default:password@host:port)
REDIS_URL = os.getenv("REDIS_URL")

if REDIS_URL:
    r = redis.StrictRedis.from_url(REDIS_URL, decode_responses=True)
else:
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

    r = redis.StrictRedis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        db=0,
        decode_responses=True
    )

def get_redis():
    """Devuelve la conexión activa de Redis"""
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