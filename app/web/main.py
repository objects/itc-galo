"""Capa web de prefactibilidad (Feature 5): FastAPI + Jinja2 + HTMX.

Reutiliza la logica de dominio de `ServidorLotes` (app/main.py) SIN protocolo
MCP. La app web construye SU PROPIO `ServidorLotes` en el lifespan (ciclo de
vida independiente del singleton de app.main) y lo cierra al terminar
(aclose de los 4 providers). No se usan los singletons `servidor_lotes`/`mcp`
de app.main: se importa solo la clase y las clases de providers.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.main import ServidorLotes
from app.providers.arcgis import ArcGISProvider
from app.providers.mapas_bogota import MapasBogotaProvider
from app.providers.normativa import NormativaProvider
from app.providers.upl import UPLProvider

# Rutas de plantillas y estaticos dentro del paquete (empaquetadas via
# package-data en pyproject.toml).
RUTA_PAQUETE = Path(__file__).resolve().parent
RUTA_TEMPLATES = RUTA_PAQUETE / "templates"
RUTA_STATIC = RUTA_PAQUETE / "static"


def _construir_servidor_lotes() -> ServidorLotes:
    """ServidorLotes con los 4 providers reales (misma fabrica que app.main).

    Fase 1: los providers se construyen sin red (httpx.AsyncClient perezoso);
    solo arrancan al consultar. Sin rutas todavia, el lifespan garantiza el
    cierre (aclose) aunque no haya consultas.
    """
    api_key = os.environ.get("MAPAS_BOGOTA_APIKEY")
    return ServidorLotes(
        MapasBogotaProvider(api_key=api_key),
        ArcGISProvider(),
        UPLProvider(),
        NormativaProvider(),
    )


def crear_app_web() -> FastAPI:
    """Construye la app FastAPI de prefactibilidad (factory para uvicorn).

    - Lifespan propio: crea un `ServidorLotes` y lo cierra al terminar.
    - Plantillas Jinja2 y estaticos configurados (sin rutas todavia; las
      rutas de las fases 3-4 se registran sobre esta factory).
    """
    plantillas = Jinja2Templates(directory=str(RUTA_TEMPLATES))

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        app.state.servidor_lotes = _construir_servidor_lotes()
        app.state.plantillas = plantillas
        try:
            yield
        finally:
            await app.state.servidor_lotes.aclose()

    app = FastAPI(title="mcp-bogota-factibilidad web", lifespan=_lifespan)
    app.mount("/static", StaticFiles(directory=str(RUTA_STATIC)), name="static")
    return app


def main() -> None:
    """Punto de entrada: uvicorn con la factory `crear_app_web`.

    Host/puerto configurables via entorno (WEB_HOST/WEB_PORT), con los
    valores por defecto del quickstart (127.0.0.1:8000).
    """
    import uvicorn

    host = os.environ.get("WEB_HOST", "127.0.0.1")
    puerto = int(os.environ.get("WEB_PORT", "8000"))
    uvicorn.run("app.web.main:crear_app_web", host=host, port=puerto, factory=True)


if __name__ == "__main__":
    main()