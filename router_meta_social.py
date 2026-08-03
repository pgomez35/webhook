"""Webhook Meta Social (Instagram Messaging + Instagram Login).

Reexporta el router completo de la integración.
Aislado de WhatsApp Cloud API. No reutiliza WHATSAPP_*.
"""
from __future__ import annotations

from app.integrations.meta_social.router import router

__all__ = ["router"]
