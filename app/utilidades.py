"""Utilidades compartidas entre modulos (hallazgo m7 del code review Fase 5).

Helpers puros y deterministas que antes estaban duplicados en `app/main.py`,
`app/scoring.py`, `app/providers/arcgis.py`, `app/providers/upl.py`,
`app/providers/sdp.py`, `app/providers/mapas_bogota.py`,
`app/providers/normativa.py` y `app/ingesta/corpus.py`. Extraccion mecanica:
mismas firmas y misma semantica, sin cambiar comportamiento.

Convencion de nombres: publicos sin guion bajo; los modulos consumidores los
importan con alias privado (`from app.utilidades import ahora_iso as _ahora_iso`)
para no tocar sus call sites.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

# CHIP catastral: 11 caracteres alfanumericos mayuscula (contrato F1). Unica
# definicion compartida por main.py (_validar_chip) y providers/arcgis.py
# (normalizacion de chip de Mapas Bogota).
PATRON_CHIP = re.compile(r"^[A-Z0-9]{11}$")


def primer_valor(objeto: dict[str, Any], claves: list[str]) -> Any:
    """Primer valor no None para las claves dadas (None si ninguna existe)."""
    for clave in claves:
        if clave in objeto and objeto[clave] is not None:
            return objeto[clave]
    return None


def primer_texto(objeto: dict[str, Any], claves: list[str]) -> str | None:
    """Primer valor de TEXTO no vacio para las claves dadas.

    Semantica canonica (variante upl.py): un valor presente pero vacio ("") NO
    corta la busqueda; se sigue con la siguiente clave candidata.
    """
    for clave in claves:
        if clave in objeto and objeto[clave] is not None:
            texto = str(objeto[clave]).strip()
            if texto:
                return texto
    return None


def extraer_numero(objeto: dict[str, Any], claves: list[str]) -> float | None:
    """Primer valor convertible a float para las claves dadas (None si no hay)."""
    valor = primer_valor(objeto, claves)
    if valor is None or valor == "":
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def ahora_iso() -> str:
    """Marca temporal ISO 8601 UTC (patron F1/F2/F3)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def formatear_numero(valor: float) -> str:
    """Formato determinista del numero en textos (4500000.0 -> "4500000")."""
    if float(valor).is_integer():
        return str(int(valor))
    return str(valor)


def clave_sin_tildes(texto: str) -> str:
    """Clave de comparacion textual: minusculas sin tildes (determinista).

    Usada para comparaciones insensibles a acentos/caso (clasificacion tematica,
    nombres de UPL, tratamientos urbanisticos).
    """
    normalizado = unicodedata.normalize("NFD", texto)
    return "".join(c for c in normalizado if unicodedata.category(c) != "Mn").lower()
