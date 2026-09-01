"""Funciones puras y deterministas del motor técnico (Fase 3, SC-003).

Todas las funciones son puras: mismo input -> mismo output. Sin I/O, sin LLM,
sin reloj. Usa shapely para cálculo geométrico determinista del área neta.

Constantes configurables: densidad y COS desde urbanistic_parameters; fallback
a defaults si faltan.
"""

from __future__ import annotations

from typing import Any

try:
    from shapely.geometry import shape as _shape
except ImportError:  # fallback si shapely no está disponible en tests sin instalación
    _shape = None  # type: ignore[assignment]


def calcular_area_bruta(geometry: dict[str, Any] | None) -> float | None:
    """Área bruta del lote en m² a partir de GeoJSON.

    Usa shapely si está disponible; retorna None si falta geometría o shapely.
    La geometría está en WGS84 (4326) por lo que el área en grados se convierte
    aproximadamente a m² usando factor heurístico 111km por grado (FR-014: estimación).
    Para tests deterministas el factor es fijo.

    NOTA (M1/M5): el factor 111 km/grado es una APROXIMACIÓN de escala que NO
    usa un CRS proyectado (p.ej. EPSG:4686/CTM12). Solo es válido como estimación
    gruesa cerca del ecuador y distorsiona en latitudes altas. En la cadena real
    este camino es secundario: el área proviene de `economic_context` (capa Predio,
    `PREATERRE`) vía `area_terreno_fin`; shapely solo se ejercita cuando falta el
    dato catastral. No se usa para decisiones normativas (FR-014).
    """
    if geometry is None or _shape is None:
        return None
    try:
        geom = _shape(geometry)
        if geom.is_empty or not geom.is_valid:
            return None
        area_grados = geom.area
        # Conversión heurística grados² -> m²: 1 grado ~ 111_000 m.
        # Aproximación sin CRS proyectado (M1/M5): ver nota del docstring.
        area_m2 = area_grados * 111_000 * 111_000
        return float(area_m2) if area_m2 > 0 else None
    except Exception:
        return None


def calcular_area_neta(
    area_bruta: float | None,
    afectacion_reserva_vial: bool | None,
    porcentaje_afectacion: float = 0.15,
) -> float | None:
    """Área neta = área bruta - afectación por reserva vial.

    Si afecta lote es True, se descuenta porcentaje_afectacion (default 15%).
    Retorna None si falta área bruta.
    """
    if area_bruta is None:
        return None
    if afectacion_reserva_vial is True:
        return area_bruta * (1 - porcentaje_afectacion)
    return area_bruta


def calcular_cabida(
    area_neta: float | None,
    cos: float | None,
) -> float | None:
    """Cabida arquitectónica = área neta * COS.

    Retorna None si falta algún dato.
    """
    if area_neta is None or cos is None:
        return None
    return area_neta * cos


def analisis_tecnico(
    geometry: dict[str, Any] | None,
    afecta_reserva_vial: bool | None,
    cos: float | None,
    area_terreno_catastral: float | None = None,
) -> dict[str, Any]:
    """Orquestación determinista del análisis técnico completo.

    Prioriza área catastral si está disponible; si no, calcula área bruta
    desde geometría vía shapely. Luego aplica afectación y cabida.

    Returns dict con área neta, bruta, cabida y viable.
    """
    area_bruta = area_terreno_catastral
    if area_bruta is None:
        area_bruta = calcular_area_bruta(geometry)
    area_neta = calcular_area_neta(area_bruta, afecta_reserva_vial)
    cabida = calcular_cabida(area_neta, cos)
    # viable: None = datos insuficientes (degradacion), True/False = calculado.
    if cabida is None or area_neta is None:
        viable: bool | None = None
    else:
        viable = cabida > 0 and area_neta > 0
    return {
        "area_bruta_m2": area_bruta,
        "area_neta_m2": area_neta,
        "cabida_arquitectonica": cabida,
        "afectacion_reserva_vial": bool(afecta_reserva_vial) if afecta_reserva_vial is not None else None,
        "viable": viable,
    }
