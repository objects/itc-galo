"""Utilidades geometricas puras compartidas por los providers (hallazgo M3).

El centroide publicado de un lote debe ser el centroide GEOMETRICO del
poligono (formula shoelace con areas), no la media aritmetica de los vertices
ni el punto de consulta: la media de vertices puede caer FUERA de lotes
concavos y provocar consultas fantasma ("lote no encontrado") al re-consultar
la capa por punto. Si ni siquiera el centroide geometrico cae dentro del
poligono (formas en U, multipoligonos), se busca un punto interior seguro con
una malla determinista sobre la envolvente.

Todas las funciones son puras y deterministas (SC-003): misma geometria de
entrada -> mismo punto de salida. Las coordenadas se manejan en el espacio
GeoJSON (x = longitud, y = latitud) sin proyecciones: cualquier transformacion
lineal (p. ej. Web Mercator) preserva centroides y contencion, asi que la
conversion del llamador puede hacerse despues, sobre el punto resultante.
"""

from __future__ import annotations

import math
from typing import Any

# Divisiones de la malla de busqueda del punto interior seguro (15x15 celdas
# internas): suficiente para lotes concavos reales y costo acotado.
_MALLA = 16


def centroide_de_anillo(anillo: list[list[float]]) -> tuple[float, float] | None:
    """Centroide geometrico (shoelace) de un anillo cerrado o abierto.

    Retorna None si el anillo es degenerado (menos de 3 vertices distintos o
    area nula): no hay centroide definible y el llamador debe usar su fallback.
    """
    puntos = _puntos_distintos(anillo)
    if len(puntos) < 3:
        return None
    area_doble = 0.0
    cx = 0.0
    cy = 0.0
    cantidad = len(puntos)
    for i in range(cantidad):
        x1, y1 = puntos[i]
        x2, y2 = puntos[(i + 1) % cantidad]
        cruz = x1 * y2 - x2 * y1
        area_doble += cruz
        cx += (x1 + x2) * cruz
        cy += (y1 + y2) * cruz
    if math.isclose(area_doble, 0.0, abs_tol=1e-12):
        return None
    return cx / (3 * area_doble), cy / (3 * area_doble)


def area_de_anillo(anillo: list[list[float]]) -> float:
    """Area absoluta del anillo (shoelace); 0.0 si es degenerado."""
    puntos = _puntos_distintos(anillo)
    if len(puntos) < 3:
        return 0.0
    area_doble = 0.0
    cantidad = len(puntos)
    for i in range(cantidad):
        x1, y1 = puntos[i]
        x2, y2 = puntos[(i + 1) % cantidad]
        area_doble += x1 * y2 - x2 * y1
    return abs(area_doble) / 2


def punto_en_anillo(punto: tuple[float, float], anillo: list[list[float]]) -> bool:
    """Ray casting: el punto esta dentro (o en el borde) del anillo."""
    x, y = punto
    puntos = _puntos_distintos(anillo)
    cantidad = len(puntos)
    dentro = False
    j = cantidad - 1
    for i in range(cantidad):
        xi, yi = puntos[i]
        xj, yj = puntos[j]
        cruza_horizontal = (yi > y) != (yj > y)
        if cruza_horizontal and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            dentro = not dentro
        j = i
    return dentro


def punto_en_poligono(punto: tuple[float, float], anillos: list[list[list[float]]]) -> bool:
    """Dentro del anillo exterior y fuera de los agujeros (formato ESRI rings)."""
    if not anillos or not punto_en_anillo(punto, anillos[0]):
        return False
    return all(not punto_en_anillo(punto, agujero) for agujero in anillos[1:])


def punto_interior_seguro(
    anillos: list[list[list[float]]],
) -> tuple[float, float] | None:
    """Punto interior determinista del poligono (anillos estilo ESRI).

    Estrategia (en orden): 1) centroide geometrico del anillo exterior si cae
    dentro del poligono; 2) primer punto de una malla fija sobre la envolvente
    que caiga dentro (recorrido determinista fila por fila); 3) None si nada
    funciona (poligono degenerado sin area util).
    """
    if not anillos:
        return None
    exterior = anillos[0]
    centroide = centroide_de_anillo(exterior)
    if centroide is not None and punto_en_poligono(centroide, anillos):
        return centroide
    xs = [punto[0] for punto in exterior]
    ys = [punto[1] for punto in exterior]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    for j in range(1, _MALLA):
        for i in range(1, _MALLA):
            candidato = (
                xmin + (xmax - xmin) * i / _MALLA,
                ymin + (ymax - ymin) * j / _MALLA,
            )
            if punto_en_poligono(candidato, anillos):
                return candidato
    return None


def centroide_interior_de_geometria(geometry: Any) -> tuple[float, float] | None:
    """Centroide interior de una geometria GeoJSON Polygon/MultiPolygon (lng, lat).

    Punto de entrada para publicar el centroide del lote: frontera de parsing,
    acepta cualquier entrada y retorna None si la geometria no es utilizable;
    el llamador aplica su fallback documentado. En MultiPolygon domina el
    poligono de mayor area exterior (determinismo).
    """
    if not isinstance(geometry, dict):
        return None
    tipo = geometry.get("type")
    coordenadas = geometry.get("coordinates")
    if tipo == "Polygon" and isinstance(coordenadas, list) and coordenadas:
        return punto_interior_seguro(coordenadas)
    if tipo == "MultiPolygon" and isinstance(coordenadas, list) and coordenadas:
        poligonos_validos = [
            poligono
            for poligono in coordenadas
            if isinstance(poligono, list) and poligono
        ]
        if not poligonos_validos:
            return None
        dominante = max(poligonos_validos, key=lambda p: area_de_anillo(p[0]))
        return punto_interior_seguro(dominante)
    return None


def _puntos_distintos(anillo: list[list[float]]) -> list[tuple[float, float]]:
    """Vertices del anillo sin el cierre repetido ni duplicados consecutivos."""
    try:
        puntos = [(float(p[0]), float(p[1])) for p in anillo]
    except (TypeError, ValueError, IndexError):
        return []
    if len(puntos) > 1 and puntos[0] == puntos[-1]:
        puntos = puntos[:-1]
    return [p for i, p in enumerate(puntos) if i == 0 or p != puntos[i - 1]]
