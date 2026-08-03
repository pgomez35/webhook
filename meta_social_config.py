"""Configuración exclusiva de Meta Social (Instagram Messaging + Instagram Login).

No reutiliza variables WHATSAPP_* ni META_APP_* de WhatsApp Cloud API.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

DEFAULT_GRAPH_API_VERSION = "v21.0"
DEFAULT_DEDUP_TTL_SECONDS = 24 * 3600

PRODUCTION_TEST_TRIGGER = "TALENTUM_DEMO_2026"
PRODUCTION_TEST_REPLY = (
    "👋 ¡Hola! Esta es una prueba de la integración de Talentum Manager con Instagram."
)


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


@dataclass(frozen=True)
class MetaSocialSettings:
    enabled: bool
    verify_token: str
    app_secret: str
    instagram_app_secret: str
    instagram_account_id: str
    instagram_access_token: str
    graph_api_version: str
    skip_signature_verify: bool = False
    http_timeout_seconds: float = 20.0
    dedup_ttl_seconds: int = DEFAULT_DEDUP_TTL_SECONDS

    @property
    def instagram_graph_base_url(self) -> str:
        version = (self.graph_api_version or DEFAULT_GRAPH_API_VERSION).strip()
        if not version.startswith("v"):
            version = f"v{version}"
        return f"https://graph.instagram.com/{version}"

    def webhook_signature_candidates(self) -> list[tuple[str, str]]:
        """Secretos candidatos para X-Hub-Signature-256 (label, secret).

        Instagram App Secret primero (caso messaging Instagram), luego el
        secreto principal (app Meta / futuro Messenger).
        """
        candidates: list[tuple[str, str]] = []
        ig_secret = (self.instagram_app_secret or "").strip()
        principal = (self.app_secret or "").strip()
        if ig_secret:
            candidates.append(("instagram", ig_secret))
        if principal and principal not in {c[1] for c in candidates}:
            candidates.append(("principal", principal))
        return candidates


@lru_cache(maxsize=1)
def get_settings() -> MetaSocialSettings:
    return MetaSocialSettings(
        enabled=_as_bool(os.getenv("META_SOCIAL_ENABLED"), default=False),
        verify_token=os.getenv("META_SOCIAL_VERIFY_TOKEN", "") or "",
        app_secret=os.getenv("META_SOCIAL_APP_SECRET", "") or "",
        instagram_app_secret=os.getenv("META_SOCIAL_INSTAGRAM_APP_SECRET", "") or "",
        instagram_account_id=os.getenv("META_SOCIAL_INSTAGRAM_ACCOUNT_ID", "") or "",
        instagram_access_token=os.getenv("META_SOCIAL_INSTAGRAM_ACCESS_TOKEN", "") or "",
        graph_api_version=(
            os.getenv("META_SOCIAL_GRAPH_API_VERSION", DEFAULT_GRAPH_API_VERSION)
            or DEFAULT_GRAPH_API_VERSION
        ),
        skip_signature_verify=_as_bool(
            os.getenv("META_SOCIAL_SKIP_SIGNATURE_VERIFY"),
            default=False,
        ),
    )


def reset_settings_cache() -> None:
    get_settings.cache_clear()
