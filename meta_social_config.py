"""Configuración exclusiva de Meta Social (Instagram Messaging + Instagram Login).

No reutiliza variables WHATSAPP_* ni META_APP_* de WhatsApp Cloud API.
No usa PAGE_ID / PAGE_ACCESS_TOKEN / graph.facebook.com.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

DEFAULT_GRAPH_API_VERSION = "v21.0"
DEFAULT_DEDUP_TTL_SECONDS = 24 * 3600
DEFAULT_DEMO_TRIGGER = "TALENTUM_DEMO_2026"

PRODUCTION_TEST_TRIGGER = DEFAULT_DEMO_TRIGGER
PRODUCTION_TEST_REPLY = (
    "👋 ¡Hola! Esta es una prueba de la integración de Talentum Manager con Instagram."
)

INSTAGRAM_CARD_TITLE = "Talentum Manager para agencias LIVE"
INSTAGRAM_CARD_SUBTITLE = (
    "Capta aspirantes desde Instagram, valida información inicial y organiza "
    "los perfiles que debe revisar tu equipo."
)
INSTAGRAM_BUTTON_TITLE = "Probar en WhatsApp"

DEFAULT_INSTAGRAM_WHATSAPP_URL = (
    "https://wa.me/573180538911?text=Hola%2C%20vengo%20desde%20Instagram"
    "%20y%20quiero%20probar%20la%20demo%20de%20Talentum"
)

INSTAGRAM_FALLBACK_TEXT = (
    "Puedes probar la demostración aquí:\nhttps://wa.me/573180538911"
)

# Texto legacy (ya no se envía si la tarjeta tiene éxito).
RICH_DEMO_TEXT = (
    "🚀 Talentum Manager para agencias de creadores LIVE\n\n"
    "Capta aspirantes desde Instagram, valida información inicial y organiza "
    "los perfiles que debe revisar tu equipo.\n\n"
    "Puedes probar una demostración real del chatbot por WhatsApp."
)

_IMAGE_EXT_RE = re.compile(r"\.(png|jpe?g|gif|webp)(?:\?|#|$)", re.IGNORECASE)
_PRIVATE_HOST_RE = re.compile(
    r"^(localhost|127\.0\.0\.1|0\.0\.0\.0|::1|10\.|192\.168\.|172\.(1[6-9]|2\d|3[0-1])\.)",
    re.IGNORECASE,
)


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def validate_demo_image_url(url: str) -> tuple[bool, str]:
    """Valida URL pública HTTPS compatible con envío de imagen Instagram."""
    text = (url or "").strip()
    if not text:
        return False, "META_SOCIAL_DEMO_IMAGE_URL vacío"
    parsed = urlparse(text)
    if parsed.scheme.lower() != "https":
        return False, "META_SOCIAL_DEMO_IMAGE_URL debe usar HTTPS"
    if not parsed.netloc:
        return False, "META_SOCIAL_DEMO_IMAGE_URL sin host público"
    host = parsed.hostname or ""
    if _PRIVATE_HOST_RE.match(host) or host.endswith(".local"):
        return False, "META_SOCIAL_DEMO_IMAGE_URL no puede ser local/privada"
    path = parsed.path or ""
    if path not in {"", "/"}:
        if not _IMAGE_EXT_RE.search(path) and "format=" not in (parsed.query or "").lower():
            if "." not in path.rsplit("/", 1)[-1] and not path.endswith("/"):
                return True, "ok"
            if not _IMAGE_EXT_RE.search(text):
                return False, "META_SOCIAL_DEMO_IMAGE_URL debe apuntar a imagen (png/jpeg/gif/webp)"
    return True, "ok"


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
    debug: bool = False
    rich_demo_enabled: bool = False
    demo_trigger: str = DEFAULT_DEMO_TRIGGER
    demo_image_url: str = ""
    whatsapp_url: str = ""

    @property
    def instagram_graph_base_url(self) -> str:
        version = (self.graph_api_version or DEFAULT_GRAPH_API_VERSION).strip()
        if not version.startswith("v"):
            version = f"v{version}"
        return f"https://graph.instagram.com/{version}"

    def webhook_signature_candidates(self) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        ig_secret = (self.instagram_app_secret or "").strip()
        principal = (self.app_secret or "").strip()
        if ig_secret:
            candidates.append(("instagram", ig_secret))
        if principal and principal not in {c[1] for c in candidates}:
            candidates.append(("principal", principal))
        return candidates

    def normalized_demo_trigger(self) -> str:
        return (self.demo_trigger or DEFAULT_DEMO_TRIGGER).strip().upper()

    def rich_demo_ready(self) -> tuple[bool, Optional[str]]:
        if not self.rich_demo_enabled:
            return False, "META_SOCIAL_RICH_DEMO_ENABLED=false"
        if not (self.instagram_account_id or "").strip():
            return False, "META_SOCIAL_INSTAGRAM_ACCOUNT_ID vacío"
        if not (self.instagram_access_token or "").strip():
            return False, "META_SOCIAL_INSTAGRAM_ACCESS_TOKEN vacío"
        ok, reason = validate_demo_image_url(self.demo_image_url)
        if not ok:
            return False, reason
        if not (self.whatsapp_url or "").strip():
            return False, "META_SOCIAL_WHATSAPP_URL vacío"
        wa = urlparse(self.whatsapp_url.strip())
        if wa.scheme.lower() not in {"https", "http"}:
            return False, "META_SOCIAL_WHATSAPP_URL inválida"
        return True, None


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
        debug=_as_bool(os.getenv("META_SOCIAL_DEBUG"), default=False),
        rich_demo_enabled=_as_bool(
            os.getenv("META_SOCIAL_RICH_DEMO_ENABLED"),
            default=False,
        ),
        demo_trigger=(
            os.getenv("META_SOCIAL_DEMO_TRIGGER", DEFAULT_DEMO_TRIGGER)
            or DEFAULT_DEMO_TRIGGER
        ),
        demo_image_url=os.getenv("META_SOCIAL_DEMO_IMAGE_URL", "") or "",
        whatsapp_url=(
            os.getenv("META_SOCIAL_WHATSAPP_URL")
            or DEFAULT_INSTAGRAM_WHATSAPP_URL
        ),
    )


def reset_settings_cache() -> None:
    get_settings.cache_clear()
