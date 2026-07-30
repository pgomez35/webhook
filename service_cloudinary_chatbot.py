"""
Cloudinary — carga firmada y eliminación de recursos informativos del chatbot.
No exponer CLOUDINARY_API_SECRET en respuestas, logs ni frontend.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Literal, Tuple

import cloudinary
import cloudinary.uploader
import cloudinary.utils
from dotenv import load_dotenv
from fastapi import HTTPException

logger = logging.getLogger("uvicorn.error")

TipoMedia = Literal["video", "document", "image", "audio"]
ResourceType = Literal["video", "raw", "image"]

VIDEO_MAX_BYTES = 16 * 1024 * 1024
PDF_MAX_BYTES = 20 * 1024 * 1024
IMAGE_MAX_BYTES = 5 * 1024 * 1024
AUDIO_MAX_BYTES = 16 * 1024 * 1024

TIPOS_PERMITIDOS = frozenset({"video", "document", "image", "audio"})

_FORMATOS_VIDEO = frozenset({"mp4", "mov"})
_FORMATOS_IMAGE = frozenset({"jpg", "jpeg", "png", "webp"})
_FORMATOS_AUDIO = frozenset({"mp3", "m4a", "aac", "ogg"})

_cloudinary_configured = False


def _ensure_cloudinary_config() -> None:
    global _cloudinary_configured
    if _cloudinary_configured:
        return
    load_dotenv()
    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME")
    api_key = os.environ.get("CLOUDINARY_API_KEY")
    api_secret = os.environ.get("CLOUDINARY_API_SECRET")
    if not cloud_name or not api_key or not api_secret:
        raise HTTPException(
            status_code=503,
            detail="Cloudinary no configurado en el servidor",
        )
    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )
    _cloudinary_configured = True


def _creds() -> Tuple[str, str]:
    _ensure_cloudinary_config()
    conf = cloudinary.config()
    return conf.cloud_name, conf.api_key


def asset_folder_agencia(agencia_id: int) -> str:
    return f"chatbot/agencia_{int(agencia_id)}/recursos_bienvenida"


def public_id_pertenece_agencia(public_id: str, agencia_id: int) -> bool:
    """El public_id debe vivir bajo la carpeta de la agencia."""
    pid = (public_id or "").strip().lstrip("/")
    prefix = asset_folder_agencia(agencia_id)
    return pid == prefix or pid.startswith(prefix + "/")


def normalizar_tipo_media(tipo: str) -> str:
    t = (tipo or "").strip().lower()
    if t in ("pdf", "documento", "doc"):
        return "document"
    if t in ("imagen", "img", "photo", "foto"):
        return "image"
    if t in ("voice", "voz"):
        return "audio"
    return t


def resource_type_para_tipo(tipo: str) -> ResourceType:
    t = normalizar_tipo_media(tipo)
    if t == "video":
        return "video"
    if t == "image":
        return "image"
    if t == "document":
        return "raw"
    if t == "audio":
        # Cloudinary aloja audio vía endpoint video
        return "video"
    raise HTTPException(
        status_code=400,
        detail="tipo debe ser video, document, image o audio",
    )


def generar_firma_carga(*, agencia_id: int, tipo: str) -> Dict[str, Any]:
    """
    Firma de corta duración para upload directo desde el navegador.
    No incluye api_secret.
    """
    tipo_norm = normalizar_tipo_media(tipo)
    if tipo_norm not in TIPOS_PERMITIDOS:
        raise HTTPException(
            status_code=400,
            detail="tipo debe ser video, document, image o audio",
        )

    _ensure_cloudinary_config()
    cloud_name, api_key = _creds()
    resource_type = resource_type_para_tipo(tipo_norm)
    folder = asset_folder_agencia(agencia_id)
    timestamp = int(time.time())
    tags = f"chatbot,agencia_{int(agencia_id)},recursos_bienvenida,temporal,{tipo_norm}"
    params_to_sign = {
        "timestamp": timestamp,
        "folder": folder,
        "overwrite": "false",
        "unique_filename": "true",
        "tags": tags,
    }
    signature = cloudinary.utils.api_sign_request(
        params_to_sign,
        cloudinary.config().api_secret,
    )

    return {
        "cloud_name": cloud_name,
        "api_key": api_key,
        "timestamp": timestamp,
        "signature": signature,
        "resource_type": resource_type,
        "asset_folder": folder,
        "upload_url": f"https://api.cloudinary.com/v1_1/{cloud_name}/{resource_type}/upload",
        "overwrite": False,
        "unique_filename": True,
        "tags": tags,
    }


def destruir_recurso_cloudinary(
    *,
    public_id: str,
    resource_type: str,
    invalidate: bool = True,
) -> Dict[str, Any]:
    _ensure_cloudinary_config()
    rt = (resource_type or "").strip().lower()
    if rt not in ("video", "raw", "image"):
        raise HTTPException(status_code=400, detail="resource_type inválido")
    pid = (public_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="public_id obligatorio")
    try:
        result = cloudinary.uploader.destroy(
            pid,
            resource_type=rt,
            invalidate=invalidate,
            type="upload",
        )
        return result if isinstance(result, dict) else {"result": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(
            "cloudinary destroy falló public_id=%s resource_type=%s err=%s",
            pid[:80],
            rt,
            type(e).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail="No se pudo eliminar el archivo en Cloudinary",
        ) from e


def validar_respuesta_upload_cloudinary(
    *,
    tipo: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Valida la respuesta de Cloudinary antes de incorporar a recursos_bienvenida.
    No confiar solo en la extensión del nombre.
    """
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Respuesta de carga inválida")

    tipo_norm = normalizar_tipo_media(tipo)
    if tipo_norm not in TIPOS_PERMITIDOS:
        raise HTTPException(status_code=400, detail="tipo de media no permitido")

    secure_url = (data.get("secure_url") or "").strip()
    public_id = (data.get("public_id") or "").strip()
    resource_type = (data.get("resource_type") or "").strip().lower()
    if not secure_url or not public_id or not resource_type:
        raise HTTPException(
            status_code=400,
            detail="Carga inválida: faltan secure_url, public_id o resource_type",
        )
    if not secure_url.startswith("https://"):
        raise HTTPException(status_code=400, detail="secure_url inválida")

    fmt = (data.get("format") or "").strip().lower()
    original = (data.get("original_filename") or "").strip()
    bytes_val = data.get("bytes")

    expected_rt = resource_type_para_tipo(tipo_norm)
    if resource_type != expected_rt:
        raise HTTPException(
            status_code=400,
            detail=f"resource_type esperado {expected_rt}, recibido {resource_type}",
        )

    default_fmt = "bin"
    if tipo_norm == "video":
        if fmt and fmt not in _FORMATOS_VIDEO:
            raise HTTPException(
                status_code=400, detail="El video debe ser MP4 o MOV"
            )
        if bytes_val is not None and int(bytes_val) > VIDEO_MAX_BYTES:
            raise HTTPException(status_code=400, detail="Video máximo 16 MB")
        default_fmt = fmt or "mp4"
    elif tipo_norm == "document":
        name_ok = original.lower().endswith(".pdf") if original else False
        fmt_ok = fmt == "pdf" or (not fmt and name_ok)
        pid_ok = public_id.lower().endswith(".pdf")
        url_ok = ".pdf" in secure_url.lower()
        if not (fmt_ok or name_ok or pid_ok or url_ok):
            raise HTTPException(status_code=400, detail="El documento debe ser PDF")
        if bytes_val is not None and int(bytes_val) > PDF_MAX_BYTES:
            raise HTTPException(status_code=400, detail="PDF máximo 20 MB")
        default_fmt = "pdf"
    elif tipo_norm == "image":
        if fmt and fmt not in _FORMATOS_IMAGE:
            raise HTTPException(
                status_code=400,
                detail="La imagen debe ser JPG, JPEG, PNG o WEBP",
            )
        if bytes_val is not None and int(bytes_val) > IMAGE_MAX_BYTES:
            raise HTTPException(status_code=400, detail="Imagen máximo 5 MB")
        default_fmt = fmt or "jpg"
    elif tipo_norm == "audio":
        if fmt and fmt not in _FORMATOS_AUDIO:
            raise HTTPException(
                status_code=400,
                detail="El audio debe ser MP3, M4A, AAC u OGG",
            )
        if bytes_val is not None and int(bytes_val) > AUDIO_MAX_BYTES:
            raise HTTPException(status_code=400, detail="Audio máximo 16 MB")
        default_fmt = fmt or "mp3"

    return {
        "secure_url": secure_url,
        "public_id": public_id,
        "asset_id": data.get("asset_id"),
        "resource_type": resource_type,
        "format": fmt or default_fmt,
        "bytes": int(bytes_val) if bytes_val is not None else None,
        "nombre_original": original or None,
    }
