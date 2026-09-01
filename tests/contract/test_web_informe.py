"""Contract tests web — Informe completo de factibilidad (Feature 9).

Verifica que la pagina de detalle (`proyecto.html`) renderiza el informe
completo de 20 bloques: anillo de score, resumen deterministico
(llm_ready_summary), identidad del lote, mapa Leaflet, los 14 bloques de
contexto con su procedencia por fuente, la evidencia normativa, el detalle del
score y las advertencias. Sin red real ni Ollama (fixtures httpx.MockTransport).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.web.db import Proyecto, ProyectoRepositorio
from app.web.main import crear_app_web
from tests.conftest import (
    CHIP_VALIDO,
    NormativaProviderStub,
    respuesta_normativa_ok,
    server_lotes_f3,
)

# Claves de los 14 bloques de contexto del informe (para el caso sin geometria).
_BLOQUES = [
    "planning_constraints",
    "market_context",
    "environment_context",
    "economic_context",
    "geotechnical_risks",
    "socioeconomic_context",
    "regulatory_environment",
    "cultural_heritage",
    "transit_access",
    "catastro_data",
    "public_space_context",
    "road_network_context",
    "nearby_facilities",
    "urbanistic_parameters",
]


def _cliente(tmp_path) -> TestClient:
    """TestClient con providers simulados y base temporal (lifespan al entrar)."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    repositorio = ProyectoRepositorio(tmp_path / "web.db")
    app = crear_app_web(servidor_lotes=servidor, repositorio=repositorio)
    return TestClient(app)


def _crear_proyecto(cliente: TestClient) -> str:
    """Crea un proyecto por CHIP y devuelve la ruta de detalle."""
    respuesta = cliente.post(
        "/proyectos",
        data={"nombre": "Lote completo", "criterio_tipo": "chip", "criterio_valor": CHIP_VALIDO},
        follow_redirects=False,
    )
    assert respuesta.status_code == 303
    return respuesta.headers["location"]


def _informe_sin_geometria() -> dict:
    """Informe minimo sin geometry/centroid (caso defensivo T013)."""
    return {
        "lot_identity": {
            "chip": CHIP_VALIDO,
            "codigo_catastral": "006101016001",
            "manzana": "006101016",
            "direccion_normalizada": None,
            "barrio": None,
        },
        "administrative_context": {
            "upl": None,
            "localidad": None,
            "clasificacion_suelo": None,
            "source_trace": {},
        },
        **{clave: None for clave in _BLOQUES},
        "normative_evidence": {
            "items": [],
            "consulta": "",
            "consulta_automatica": False,
            "sin_resultados": True,
            "source_trace": {},
        },
        "feasibility_score": {"score": 50, "confidence": "low", "reasons": [], "rules_applied": []},
        "warnings": [],
        "llm_ready_summary": "Resumen de prueba sin geometría.",
        "query_timestamp": "2026-08-31T00:00:00Z",
    }


# --- Render del informe completo ---


def test_detalle_renderiza_informe_completo(tmp_path):
    with _cliente(tmp_path) as cliente:
        ruta = _crear_proyecto(cliente)
        html = cliente.get(ruta).text

        # Resumen ejecutivo: anillo de score + resumen deterministico.
        assert "anillo-score" in html
        assert "Confianza" in html

        # Identidad del lote.
        assert CHIP_VALIDO in html
        assert "Identidad del lote" in html

        # Mapa Leaflet.
        assert "contenedor-mapa" in html
        assert "data-geometry=" in html
        assert "data-centroid=" in html

        # Bloques de contexto (tarjetas).
        assert "bloque-informe" in html
        assert "Restricciones de planeación" in html
        assert "Parámetros urbanísticos" in html

        # Evidencia normativa (cita literal del RAG).
        assert "Evidencia normativa" in html
        assert "Artículo 361" in html
        assert "Usos del suelo" in html

        # Detalle del score.
        assert "Detalle del score" in html

        # Advertencias.
        assert "advertencia" in html


def test_detalle_muestra_procedencia_por_fuente(tmp_path):
    with _cliente(tmp_path) as cliente:
        ruta = _crear_proyecto(cliente)
        html = cliente.get(ruta).text

        # La traza de la capa Lote (identidad) y la del corpus (evidencia).
        assert "fuente" in html
        assert "capa" in html


def test_detalle_sin_geometria_no_renderiza_mapa(tmp_path):
    """Caso defensivo T013: sin geometry/centroid no se dibuja el mapa."""
    repositorio = ProyectoRepositorio(tmp_path / "web.db")
    proyecto = Proyecto(
        id="sin-geometria",
        nombre="Sin geometría",
        criterio_tipo="chip",
        criterio_valor=CHIP_VALIDO,
        estado="completado",
        informe=_informe_sin_geometria(),
        creado_en="2026-08-31T00:00:00Z",
        actualizado_en="2026-08-31T00:00:00Z",
    )
    repositorio.crear(proyecto)
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    app = crear_app_web(servidor_lotes=servidor, repositorio=repositorio)
    with TestClient(app) as cliente:
        html = cliente.get("/proyectos/sin-geometria").text
        # El contenedor del mapa (con sus data-attributes) no se renderiza.
        assert "data-geometry=" not in html
        assert "Resumen de prueba sin geometría." in html
