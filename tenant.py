# tenant.py
from contextvars import ContextVar

# Variables de contexto por request/thread
current_tenant: ContextVar[str] = ContextVar("current_tenant", default="public")
current_business_name: ContextVar[str] = ContextVar("current_business_name")
current_token: ContextVar[str] = ContextVar("current_token", default=None)
current_phone_id: ContextVar[str] = ContextVar("current_phone_id", default=None)
