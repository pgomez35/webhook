"""
Compatibilidad: las funciones que antes usaban Redis delegan en whatsapp_flujos (PostgreSQL).
"""
from utils_whatsapp_flujos import (
    actualizar_flujo,
    eliminar_flujo,
    guardar_aspirante_temp,
    limpiar_aspirante_temp,
    obtener_aspirante_temp,
    obtener_flujo,
)

# Alias históricos usados en main_webhook
redis_set_temp = guardar_aspirante_temp
redis_get_temp = obtener_aspirante_temp
redis_delete_temp = limpiar_aspirante_temp


def get_redis():
    """Obsoleto: ya no hay cliente Redis en este proyecto."""
    return None
