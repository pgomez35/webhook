"""
Utilidades de logging seguro: nunca registrar secretos en logs.

Uso típico:
    from security_logging import sanitize_headers, authorization_status

    logger.error("HEADERS: %s", sanitize_headers(request.headers))
    logger.info("Authorization header: %s", authorization_status(auth))
"""
from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional

SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "proxy-authorization",
    "x-access-token",
    "x-auth-token",
    "x-csrf-token",
    "x-openai-key",
}

# Claves de cuerpo/metadata que no deben aparecer en logs de depuración.
SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "password",
        "password_hash",
        "password_actual",
        "password_nuevo",
        "new_password",
        "old_password",
        "access_token",
        "refresh_token",
        "token",
        "api_key",
        "openai_api_key",
        "secret",
        "client_secret",
        "cookie",
        "set-cookie",
        "codigo_verificacion",
        "otp",
        "verification_code",
        "portal_token",
        "link_privado",
        "private_link",
    }
)

_REDACTED = "[REDACTED]"


def authorization_status(authorization: Optional[str]) -> str:
    """Indica si el encabezado Authorization está presente, sin revelar el valor."""
    return "presente" if authorization else "ausente"


def sanitize_headers(headers: Any) -> dict:
    """
    Devuelve un dict de headers con valores sensibles enmascarados.

    Acepta ``Headers`` de Starlette/FastAPI, dicts u objetos con ``.items()``.
    """
    if headers is None:
        return {}

    try:
        items = headers.items()
    except Exception:
        try:
            items = dict(headers).items()
        except Exception:
            return {"_error": "headers_no_serializables"}

    out: dict = {}
    for key, value in items:
        nombre = str(key)
        if nombre.lower() in SENSITIVE_HEADERS:
            out[nombre] = _REDACTED
        else:
            out[nombre] = value
    return out


def mask_secret(valor: Any, *, visible: int = 0) -> str:
    """Enmascara un secreto; opcionalmente deja visibles los últimos N caracteres."""
    if valor is None or valor == "":
        return "ausente"
    texto = str(valor)
    if visible <= 0 or len(texto) <= visible:
        return _REDACTED
    return f"...{texto[-visible:]}"


def _es_clave_sensible(key: Any) -> bool:
    llave = str(key).lower().replace("-", "_")
    if llave in SENSITIVE_KEYS:
        return True
    return any(
        llave.endswith(sufijo)
        for sufijo in ("_token", "_secret", "_password", "_api_key", "_otp")
    )


def sanitize_mapping(
    data: Optional[Mapping[str, Any]],
    *,
    depth: int = 0,
    max_depth: int = 4,
) -> Any:
    """Redacta claves sensibles en dicts anidados (p. ej. cuerpos de error)."""
    if data is None:
        return None
    if depth > max_depth:
        return _REDACTED
    if not isinstance(data, Mapping):
        return data

    out: MutableMapping[str, Any] = {}
    for key, value in data.items():
        if _es_clave_sensible(key):
            out[str(key)] = _REDACTED
        elif isinstance(value, Mapping):
            out[str(key)] = sanitize_mapping(value, depth=depth + 1, max_depth=max_depth)
        elif isinstance(value, list):
            out[str(key)] = [
                sanitize_mapping(item, depth=depth + 1, max_depth=max_depth)
                if isinstance(item, Mapping)
                else item
                for item in value
            ]
        else:
            out[str(key)] = value
    return dict(out)


def sanitize_validation_errors(errors: Any) -> list:
    """
    Sanitiza ``RequestValidationError.errors()`` para logs.

    Si ``loc`` apunta a un campo sensible y ``input`` es el valor crudo,
    lo enmascara; si ``input`` es un dict, aplica ``sanitize_mapping``.
    """
    if not errors:
        return []
    out = []
    for err in errors:
        if not isinstance(err, Mapping):
            out.append(err)
            continue
        seguro = sanitize_mapping(err)
        loc = err.get("loc") or ()
        if any(_es_clave_sensible(parte) for parte in loc):
            if "input" in seguro and not isinstance(seguro.get("input"), Mapping):
                seguro["input"] = _REDACTED
        out.append(seguro)
    return out

