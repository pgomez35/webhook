"""
Rate Limiter por Tenant
Implementa rate limiting usando sliding window algorithm
Thread-safe y eficiente para multitenant
"""
import asyncio
import time
from collections import defaultdict, deque
from typing import Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Configuración de rate limit para un tenant"""
    max_requests: int = 100  # Máximo de requests permitidos
    window_seconds: int = 60  # Ventana de tiempo en segundos
    burst_allowance: int = 10  # Requests adicionales permitidos en ráfagas cortas


class RateLimiter:
    """
    Rate limiter usando sliding window algorithm.
    Thread-safe y eficiente para múltiples tenants.
    """
    
    def __init__(self):
        # Estructura: {tenant_schema: deque de timestamps}
        self._request_timestamps: dict[str, deque] = defaultdict(lambda: deque())
        self._lock = asyncio.Lock()
        
        # Configuraciones por tenant (pueden ser personalizadas)
        self._configs: dict[str, RateLimitConfig] = {}
        
        # Configuración por defecto
        self._default_config = RateLimitConfig(
            max_requests=100,
            window_seconds=60,
            burst_allowance=10
        )
        
        # Estadísticas (opcional, para monitoreo)
        self._stats: dict[str, dict] = defaultdict(lambda: {
            "total_requests": 0,
            "blocked_requests": 0,
            "last_reset": time.time()
        })
    
    def set_tenant_config(
        self, 
        tenant_schema: str, 
        max_requests: int = None,
        window_seconds: int = None,
        burst_allowance: int = None
    ):
        """
        Configura límites personalizados para un tenant específico.
        
        Args:
            tenant_schema: Schema del tenant
            max_requests: Máximo de requests en la ventana
            window_seconds: Duración de la ventana en segundos
            burst_allowance: Requests adicionales permitidos en ráfagas
        """
        config = RateLimitConfig(
            max_requests=max_requests or self._default_config.max_requests,
            window_seconds=window_seconds or self._default_config.window_seconds,
            burst_allowance=burst_allowance or self._default_config.burst_allowance
        )
        self._configs[tenant_schema] = config
        logger.info(
            f"✅ Configuración de rate limit para {tenant_schema}: "
            f"{config.max_requests} req/{config.window_seconds}s (burst: {config.burst_allowance})"
        )
    
    def get_tenant_config(self, tenant_schema: str) -> RateLimitConfig:
        """Obtiene la configuración de rate limit para un tenant"""
        return self._configs.get(tenant_schema, self._default_config)
    
    async def check_rate_limit(
        self, 
        tenant_schema: str,
        identifier: Optional[str] = None
    ) -> tuple[bool, dict]:
        """
        Verifica si un request está dentro del rate limit.
        
        Args:
            tenant_schema: Schema del tenant
            identifier: Identificador adicional (opcional, ej: IP, user_id)
        
        Returns:
            Tuple (is_allowed, info_dict)
            - is_allowed: True si el request está permitido
            - info_dict: Información sobre el rate limit (remaining, reset_time, etc.)
        """
        async with self._lock:
            config = self.get_tenant_config(tenant_schema)
            now = time.time()
            
            # Usar identifier si está disponible, sino usar tenant_schema
            key = f"{tenant_schema}:{identifier}" if identifier else tenant_schema
            
            # Obtener timestamps del tenant
            timestamps = self._request_timestamps[key]
            
            # Limpiar timestamps fuera de la ventana
            cutoff_time = now - config.window_seconds
            while timestamps and timestamps[0] < cutoff_time:
                timestamps.popleft()
            
            # Contar requests en la ventana
            requests_in_window = len(timestamps)
            
            # Calcular límite efectivo (incluyendo burst allowance)
            effective_limit = config.max_requests + config.burst_allowance
            
            # Verificar si está permitido
            is_allowed = requests_in_window < effective_limit
            
            if is_allowed:
                # Registrar el request
                timestamps.append(now)
                self._stats[tenant_schema]["total_requests"] += 1
            else:
                self._stats[tenant_schema]["blocked_requests"] += 1
                logger.warning(
                    f"🚫 Rate limit excedido para {tenant_schema}: "
                    f"{requests_in_window}/{effective_limit} requests en {config.window_seconds}s"
                )
            
            # Calcular información para headers
            remaining = max(0, effective_limit - requests_in_window - (1 if is_allowed else 0))
            reset_time = int(now + config.window_seconds)
            
            # Si hay timestamps, el reset es el más antiguo + window
            if timestamps:
                oldest_timestamp = timestamps[0]
                reset_time = int(oldest_timestamp + config.window_seconds)
            
            info = {
                "allowed": is_allowed,
                "remaining": remaining,
                "limit": effective_limit,
                "reset": reset_time,
                "retry_after": max(0, reset_time - int(now)) if not is_allowed else 0
            }
            
            return is_allowed, info
    
    def get_stats(self, tenant_schema: Optional[str] = None) -> dict:
        """
        Obtiene estadísticas de rate limiting.
        
        Args:
            tenant_schema: Schema del tenant (opcional, si es None retorna todos)
        
        Returns:
            Diccionario con estadísticas
        """
        if tenant_schema:
            return self._stats.get(tenant_schema, {})
        return dict(self._stats)
    
    def reset_tenant(self, tenant_schema: str):
        """Resetea el rate limit para un tenant (útil para testing)"""
        async def _reset():
            async with self._lock:
                # Limpiar todos los keys que empiecen con el tenant
                keys_to_remove = [
                    key for key in self._request_timestamps.keys()
                    if key.startswith(tenant_schema)
                ]
                for key in keys_to_remove:
                    del self._request_timestamps[key]
                
                if tenant_schema in self._stats:
                    self._stats[tenant_schema] = {
                        "total_requests": 0,
                        "blocked_requests": 0,
                        "last_reset": time.time()
                    }
        
        # Ejecutar en el event loop si está disponible
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_reset())
            else:
                loop.run_until_complete(_reset())
        except RuntimeError:
            # Si no hay event loop, crear uno nuevo
            asyncio.run(_reset())


# Instancia global del rate limiter
_rate_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    """Obtiene la instancia global del rate limiter"""
    return _rate_limiter


async def check_rate_limit(
    tenant_schema: str,
    identifier: Optional[str] = None
) -> tuple[bool, dict]:
    """
    Función helper para verificar rate limit.
    
    Args:
        tenant_schema: Schema del tenant
        identifier: Identificador adicional (opcional)
    
    Returns:
        Tuple (is_allowed, info_dict)
    """
    return await _rate_limiter.check_rate_limit(tenant_schema, identifier)

