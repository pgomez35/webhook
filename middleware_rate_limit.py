"""
Middleware de Rate Limiting
Se integra después del TenantMiddleware para aplicar rate limiting por tenant
"""
import logging
from typing import Optional

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from tenant import current_tenant
from rate_limiter import get_rate_limiter

logger = logging.getLogger(__name__)

# Headers estándar de rate limiting
RATE_LIMIT_HEADER = "X-RateLimit-Limit"
RATE_LIMIT_REMAINING_HEADER = "X-RateLimit-Remaining"
RATE_LIMIT_RESET_HEADER = "X-RateLimit-Reset"
RETRY_AFTER_HEADER = "Retry-After"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware que aplica rate limiting por tenant.
    Debe agregarse DESPUÉS del TenantMiddleware para que el tenant ya esté resuelto.
    """
    
    def __init__(
        self,
        app,
        enabled: bool = True,
        exempt_paths: Optional[list[str]] = None,
        get_identifier: Optional[callable] = None
    ):
        """
        Args:
            app: Aplicación FastAPI
            enabled: Si está habilitado el rate limiting
            exempt_paths: Lista de paths exentos (ej: ["/health", "/metrics"])
            get_identifier: Función para obtener identificador adicional (ej: IP, user_id)
        """
        super().__init__(app)
        self.enabled = enabled
        self.exempt_paths = exempt_paths or []
        self.get_identifier = get_identifier or self._default_get_identifier
        self.rate_limiter = get_rate_limiter()
    
    def _default_get_identifier(self, request: Request) -> Optional[str]:
        """
        Obtiene un identificador del request (por defecto: IP del cliente).
        Puedes sobrescribir esto para usar user_id, session_id, etc.
        """
        # Intentar obtener IP real (considerando proxies)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Tomar la primera IP (cliente original)
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        
        # Fallback a client host
        if request.client:
            return request.client.host
        
        return None
    
    def _is_exempt(self, path: str) -> bool:
        """Verifica si un path está exento del rate limiting"""
        for exempt_path in self.exempt_paths:
            if path.startswith(exempt_path):
                return True
        return False
    
    async def dispatch(self, request: Request, call_next):
        # Si está deshabilitado, pasar directamente
        if not self.enabled:
            return await call_next(request)
        
        # Verificar si el path está exento
        if self._is_exempt(request.url.path):
            return await call_next(request)
        
        # Obtener tenant del contexto (debe estar resuelto por TenantMiddleware)
        tenant_schema = current_tenant.get()
        if not tenant_schema:
            # Si no hay tenant, no aplicar rate limiting
            logger.warning("⚠️ Rate limit: No se encontró tenant en el contexto")
            return await call_next(request)
        
        # Obtener identificador adicional (IP, user_id, etc.)
        identifier = self.get_identifier(request)
        
        # Verificar rate limit
        is_allowed, rate_limit_info = await self.rate_limiter.check_rate_limit(
            tenant_schema=tenant_schema,
            identifier=identifier
        )
        
        # Agregar headers de rate limit a la respuesta
        def add_rate_limit_headers(response):
            response.headers[RATE_LIMIT_HEADER] = str(rate_limit_info["limit"])
            response.headers[RATE_LIMIT_REMAINING_HEADER] = str(rate_limit_info["remaining"])
            response.headers[RATE_LIMIT_RESET_HEADER] = str(rate_limit_info["reset"])
            
            if not is_allowed:
                response.headers[RETRY_AFTER_HEADER] = str(rate_limit_info["retry_after"])
        
        # Si no está permitido, retornar error 429
        if not is_allowed:
            logger.warning(
                f"🚫 Rate limit excedido para tenant {tenant_schema} "
                f"(identifier: {identifier}). "
                f"Retry after: {rate_limit_info['retry_after']}s"
            )
            
            response = JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Rate limit exceeded",
                    "message": f"Has excedido el límite de requests. Intenta de nuevo en {rate_limit_info['retry_after']} segundos.",
                    "retry_after": rate_limit_info["retry_after"],
                    "limit": rate_limit_info["limit"],
                    "reset_at": rate_limit_info["reset"]
                }
            )
            add_rate_limit_headers(response)
            return response
        
        # Si está permitido, continuar con el request
        response = await call_next(request)
        add_rate_limit_headers(response)
        return response

