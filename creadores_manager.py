"""
Relación manager/agente del creador por email.

El valor del reporte (columna Agente) o del Excel de importación (manager)
se busca contra administradores.agente y, si no hay match, contra
administradores.email. Case-insensitive + TRIM.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

EMAIL_AGENTE_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_SAFE_RE = re.compile(r"[^a-z0-9._-]")


def normalizar_clave_manager(valor: Any) -> Optional[str]:
    if valor is None:
        return None
    text = str(valor).strip().lower()
    if not text or text in {"nan", "none", "null", "-", "—", "–", "<na>", "nat"}:
        return None
    return text


def es_email_agente(valor: Any) -> bool:
    clave = normalizar_clave_manager(valor)
    if not clave:
        return False
    return bool(EMAIL_AGENTE_RE.match(clave))


def username_base_desde_email(email: str) -> str:
    clave = normalizar_clave_manager(email) or ""
    local = clave.split("@", 1)[0]
    local = USERNAME_SAFE_RE.sub("", local).strip("._-")
    return local or "manager"


def username_unico_disponible(base: str, usados: Iterable[str]) -> str:
    usados_set = {str(u).strip().lower() for u in usados if u}
    candidato = (base or "manager").strip().lower() or "manager"
    if candidato not in usados_set:
        return candidato
    n = 2
    while f"{candidato}{n}" in usados_set:
        n += 1
    return f"{candidato}{n}"


def resolver_manager_id_por_indices(
    valor: Any,
    by_agente: Dict[str, List[int]],
    by_email: Dict[str, List[int]],
) -> Tuple[Optional[int], List[str], str]:
    """Retorna (manager_id, mensajes, severidad: ok|warn|error)."""
    clave = normalizar_clave_manager(valor)
    if not clave:
        return None, [], "ok"

    raw = str(valor).strip()
    ids = by_agente.get(clave, [])
    if len(ids) == 1:
        return ids[0], [], "ok"
    if len(ids) > 1:
        return None, [f'Manager "{raw}" es ambiguo (agente)'], "error"

    ids = by_email.get(clave, [])
    if len(ids) == 1:
        return ids[0], [], "ok"
    if len(ids) > 1:
        return None, [f'Manager "{raw}" es ambiguo (email)'], "error"

    return None, [f'Manager "{raw}" no encontrado'], "warn"


def construir_indices_manager(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    by_agente: Dict[str, List[int]] = {}
    by_email: Dict[str, List[int]] = {}
    for row in rows:
        mid = int(row["id"])
        agente = normalizar_clave_manager(row.get("agente"))
        email = normalizar_clave_manager(row.get("email"))
        if agente:
            by_agente.setdefault(agente, []).append(mid)
        if email:
            by_email.setdefault(email, []).append(mid)
    return {"by_agente": by_agente, "by_email": by_email}


def claves_admin_existentes(rows: Iterable[Dict[str, Any]]) -> Set[str]:
    claves: Set[str] = set()
    for row in rows:
        agente = normalizar_clave_manager(row.get("agente"))
        email = normalizar_clave_manager(row.get("email"))
        if agente:
            claves.add(agente)
        if email:
            claves.add(email)
    return claves
