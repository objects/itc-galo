"""Providers de fuentes externas (Principio II: frontera de parsing aislada)."""

from app.providers.arcgis import ArcGISProvider
from app.providers.mapas_bogota import MapasBogotaProvider
from app.providers.normativa import NormativaProvider
from app.providers.upl import UPLProvider

__all__ = [
    "ArcGISProvider",
    "MapasBogotaProvider",
    "UPLProvider",
    "NormativaProvider",
]