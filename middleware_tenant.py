import re
from typing import Optional

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from tenant import current_tenant

TENANT_HEADER = "x-tenant-name"
SCHEMA_PREFIX = "agencia_"
INVALID_TENANT_MESSAGE = (
    "No se pudo determinar el tenant. Envía el encabezado X-Tenant-Name o usa un subdominio válido."
)
BLACKLISTED_SUBDOMAINS = {"www", "api"}


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        tenant_name = self._resolve_tenant_name(request)
        tenant_schema = self._build_schema_name(tenant_name)

        current_tenant.set(tenant_schema)
        request.state.agencia = tenant_schema
        request.state.tenant_name = tenant_name

        response = await call_next(request)
        return response

    def _resolve_tenant_name(self, request: Request) -> str:
        header_value = self._extract_header_tenant(request)
        if header_value:
            return header_value

        subdomain_value = self._extract_subdomain_tenant(request)
        if subdomain_value:
            return subdomain_value

        raise HTTPException(status_code=400, detail=INVALID_TENANT_MESSAGE)

    @staticmethod
    def _extract_header_tenant(request: Request) -> Optional[str]:
        raw_value = request.headers.get(TENANT_HEADER)
        if not raw_value:
            return None

        tenant = raw_value.strip().lower()
        if not tenant:
            return None

        TenantMiddleware._validate_tenant_value(tenant)
        return tenant

    @staticmethod
    def _extract_subdomain_tenant(request: Request) -> Optional[str]:
        host = (request.headers.get("host") or "").strip().lower()
        if not host:
            return None

        hostname = host.split(":")[0]

        match = re.match(r"^([a-z0-9-]+)\.", hostname)
        if not match:
            return None

        subdomain = match.group(1)
        if subdomain in BLACKLISTED_SUBDOMAINS:
            return None

        TenantMiddleware._validate_tenant_value(subdomain)
        return subdomain

    @staticmethod
    def _build_schema_name(tenant_name: str) -> str:
        normalized = tenant_name.replace("-", "_")
        if normalized.startswith(SCHEMA_PREFIX):
            normalized = normalized[len(SCHEMA_PREFIX) :]

        if not normalized:
            raise HTTPException(
                status_code=400,
                detail="Nombre de tenant inválido. Debe contener caracteres alfanuméricos.",
            )

        schema = f"{SCHEMA_PREFIX}{normalized}"

        if not re.fullmatch(r"[a-z0-9_]+", schema):
            raise HTTPException(
                status_code=400,
                detail="Nombre de tenant inválido. Usa solo letras, números y guiones bajos.",
            )

        return schema

    @staticmethod
    def _validate_tenant_value(value: str) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value):
            raise HTTPException(
                status_code=400,
                detail="Valor de X-Tenant-Name inválido. Usa solo letras, números, '-' o '_'.",
            )