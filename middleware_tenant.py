# middleware_tenant.py
import re
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from tenant import current_tenant

class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        host = request.headers.get("host", "").lower()
        # Detectar subdominio - ejemplo: cliente.mi-dominio.com
        match = re.match(r"^([a-z0-9-]+)\.", host)
        subdominio = match.group(1) if match else None

        if not subdominio or subdominio in ("www", "api"):
            # Puedes permitir public o manejarlo según tu caso
            raise HTTPException(status_code=400, detail="Subdominio inválido o no permitido")

        # Normalizar: solo [a-z0-9_] para schema
        schema = subdominio.replace("-", "_")
        if not re.fullmatch(r"[a-z0-9_]+", schema):
            raise HTTPException(status_code=400, detail="Subdominio contiene caracteres no permitidos")

        tenant_schema = f"agencia_{schema}"

        # Guardar en contextvar y request.state para acceso desde handlers
        current_tenant.set(tenant_schema)
        request.state.agencia = tenant_schema

        response = await call_next(request)
        return response



# import re
# from fastapi import Request, HTTPException
# from starlette.middleware.base import BaseHTTPMiddleware
# from contextvars import ContextVar
#
# # Contexto global para el tenant actual
# current_tenant = ContextVar("current_tenant", default="public")
#
#
# class TenantMiddleware(BaseHTTPMiddleware):
#
#     async def dispatch(self, request: Request, call_next):
#         host = request.headers.get("host", "").lower()
#         # Detectar subdominio
#         subdominio_match = re.match(r"^([a-z0-9-]+)\.", host)
#         subdominio = subdominio_match.group(1) if subdominio_match else None
#
#         if not subdominio or subdominio in ("www", "api"):
#             raise HTTPException(status_code=400, detail="Subdominio inválido o no permitido")
#
#         # Formatear nombre de schema (debe coincidir con el schema en Postgres)
#         tenant_schema = f"agencia_{subdominio.replace('-', '_')}"
#
#         # Guardar en contexto y en request.state
#         current_tenant.set(tenant_schema)
#         request.state.agencia = tenant_schema
#
#         # Continuar con la request
#         response = await call_next(request)
#         return response

