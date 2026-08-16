"""Contract tests web — Interfaz web de prefactibilidad (Feature 5, Fase 3-5).

Rutas US1 (crear y listar proyectos) y US2 (detalle, reevaluar y JSON) sobre la
factory `crear_app_web` con providers simulados (`server_lotes_f3`) y
repositorio temporal (tmp_path): ninguna prueba hace llamadas de red reales ni
requiere Ollama (mismos fixtures httpx.MockTransport de F1-F4).

Fase 5: mapeo de errores canonicos (app/errores.py) a status HTTP — el error
de evaluacion NO se lanza como excepcion: el proyecto se persiste "fallido" y
el endpoint /json lo expone con el status mapeado (400/404/502/503/500).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.web.db import ProyectoRepositorio
from app.web.main import _error_a_http, crear_app_web
from tests.conftest import (
    CHIP_INEXISTENTE,
    CHIP_VALIDO,
    NormativaProviderStub,
    provider_arcgis_f3,
    respuesta_normativa_ok,
    server_lotes_f3,
)


def _cliente(tmp_path) -> TestClient:
    """TestClient con providers simulados y base temporal (lifespan al entrar)."""
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    repositorio = ProyectoRepositorio(tmp_path / "web.db")
    app = crear_app_web(servidor_lotes=servidor, repositorio=repositorio)
    return TestClient(app)


# --- US1: crear y listar proyectos ---


def test_index_lista_vacia(tmp_path):
    with _cliente(tmp_path) as cliente:
        respuesta = cliente.get("/")
        assert respuesta.status_code == 200
        assert "No hay proyectos" in respuesta.text


def test_index_lista_proyectos_despues_de_crear(tmp_path):
    with _cliente(tmp_path) as cliente:
        cliente.post(
            "/proyectos",
            data={"nombre": "Mi lote", "criterio_tipo": "chip", "criterio_valor": CHIP_VALIDO},
            follow_redirects=False,
        )
        respuesta = cliente.get("/")
        assert respuesta.status_code == 200
        assert "Mi lote" in respuesta.text
        assert "completado" in respuesta.text


def test_crear_proyecto_por_chip_redirige_a_detalle(tmp_path):
    with _cliente(tmp_path) as cliente:
        respuesta = cliente.post(
            "/proyectos",
            data={"nombre": "Mi lote", "criterio_tipo": "chip", "criterio_valor": CHIP_VALIDO},
            follow_redirects=False,
        )
        assert respuesta.status_code == 303
        ruta = respuesta.headers["location"]
        assert ruta.startswith("/proyectos/")

        detalle = cliente.get(ruta)
        assert detalle.status_code == 200
        assert "Mi lote" in detalle.text

        informe = cliente.get(f"{ruta}/json")
        assert informe.status_code == 200
        assert "feasibility_score" in informe.json()


def test_crear_proyecto_por_direccion(tmp_path):
    with _cliente(tmp_path) as cliente:
        respuesta = cliente.post(
            "/proyectos",
            data={"nombre": "Por dirección", "criterio_tipo": "direccion", "criterio_valor": "Calle 26 # 69-76"},
            follow_redirects=False,
        )
        assert respuesta.status_code == 303
        ruta = respuesta.headers["location"]
        assert cliente.get(f"{ruta}/json").status_code == 200


def test_crear_proyecto_por_coordenadas(tmp_path):
    with _cliente(tmp_path) as cliente:
        respuesta = cliente.post(
            "/proyectos",
            data={"nombre": "Por coordenadas", "criterio_tipo": "coordenadas", "criterio_valor": "4.665,-74.102"},
            follow_redirects=False,
        )
        assert respuesta.status_code == 303
        ruta = respuesta.headers["location"]
        assert cliente.get(f"{ruta}/json").status_code == 200


# --- US1: validacion del formulario (fail-fast, HTTPException 400) ---


def test_crear_proyecto_validacion_nombre_vacio(tmp_path):
    with _cliente(tmp_path) as cliente:
        respuesta = cliente.post(
            "/proyectos",
            data={"nombre": "", "criterio_tipo": "chip", "criterio_valor": CHIP_VALIDO},
        )
        assert respuesta.status_code == 400


def test_crear_proyecto_validacion_criterio_invalido(tmp_path):
    with _cliente(tmp_path) as cliente:
        respuesta = cliente.post(
            "/proyectos",
            data={"nombre": "X", "criterio_tipo": "manzana", "criterio_valor": "ABC"},
        )
        assert respuesta.status_code == 400


def test_crear_proyecto_validacion_valor_vacio(tmp_path):
    with _cliente(tmp_path) as cliente:
        respuesta = cliente.post(
            "/proyectos",
            data={"nombre": "X", "criterio_tipo": "chip", "criterio_valor": ""},
        )
        assert respuesta.status_code == 400


def test_crear_proyecto_validacion_top_k_fuera_de_rango(tmp_path):
    with _cliente(tmp_path) as cliente:
        respuesta = cliente.post(
            "/proyectos",
            data={"nombre": "X", "criterio_tipo": "chip", "criterio_valor": CHIP_VALIDO, "top_k": "0"},
        )
        assert respuesta.status_code == 400


def test_crear_proyecto_validacion_coordenadas_invalidas(tmp_path):
    with _cliente(tmp_path) as cliente:
        respuesta = cliente.post(
            "/proyectos",
            data={"nombre": "X", "criterio_tipo": "coordenadas", "criterio_valor": "abc,def"},
        )
        assert respuesta.status_code == 400


# --- Fase 5: errores de evaluacion se persisten como "fallido" (no se lanzan) ---


def test_crear_proyecto_lote_inexistente_persiste_fallido(tmp_path):
    with _cliente(tmp_path) as cliente:
        respuesta = cliente.post(
            "/proyectos",
            data={"nombre": "Inexistente", "criterio_tipo": "chip", "criterio_valor": CHIP_INEXISTENTE},
            follow_redirects=False,
        )
        assert respuesta.status_code == 303
        ruta = respuesta.headers["location"]

        detalle = cliente.get(ruta)
        assert detalle.status_code == 200
        assert "LOTE_NO_ENCONTRADO" in detalle.text

        informe = cliente.get(f"{ruta}/json")
        assert informe.status_code == 404
        assert informe.json()["error"]["code"] == "LOTE_NO_ENCONTRADO"


def test_fuente_5xx_se_mapea_a_502_en_json(tmp_path):
    servidor = server_lotes_f3(
        arcgis=provider_arcgis_f3(lotes=(None, 500)),
        normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()),
    )
    repositorio = ProyectoRepositorio(tmp_path / "web.db")
    app = crear_app_web(servidor_lotes=servidor, repositorio=repositorio)
    with TestClient(app) as cliente:
        respuesta = cliente.post(
            "/proyectos",
            data={"nombre": "5xx", "criterio_tipo": "chip", "criterio_valor": CHIP_VALIDO},
            follow_redirects=False,
        )
        assert respuesta.status_code == 303
        ruta = respuesta.headers["location"]
        informe = cliente.get(f"{ruta}/json")
        assert informe.status_code == 502
        assert informe.json()["error"]["code"] == "FUENTE_5XX"


def test_mapeo_errores_http():
    assert _error_a_http("PARAMETROS_INVALIDOS") == 400
    assert _error_a_http("LOTE_NO_ENCONTRADO") == 404
    assert _error_a_http("DIRECCION_NO_LOCALIZADA") == 404
    assert _error_a_http("FUERA_DE_COBERTURA") == 404
    assert _error_a_http("DATO_NO_ENCONTRADO_POR_FUENTE") == 404
    assert _error_a_http("LOTE_SIN_UPL") == 404
    assert _error_a_http("CREDENCIAL_FALTANTE") == 503
    assert _error_a_http("CORPUS_NO_INGESTADO") == 503
    assert _error_a_http("OLLAMA_NO_DISPONIBLE") == 503
    assert _error_a_http("FUENTE_5XX") == 502
    assert _error_a_http("CODIGO_DESCONOCIDO") == 500
    assert _error_a_http(None) == 500


# --- US2: detalle, reevaluar y JSON ---


def test_detalle_proyecto_inexistente_404(tmp_path):
    with _cliente(tmp_path) as cliente:
        assert cliente.get("/proyectos/inexistente").status_code == 404


def test_json_proyecto_inexistente_404(tmp_path):
    with _cliente(tmp_path) as cliente:
        assert cliente.get("/proyectos/inexistente/json").status_code == 404


def test_reevaluar_proyecto_redirige_y_mantiene_informe(tmp_path):
    with _cliente(tmp_path) as cliente:
        creado = cliente.post(
            "/proyectos",
            data={"nombre": "Reevaluar", "criterio_tipo": "chip", "criterio_valor": CHIP_VALIDO},
            follow_redirects=False,
        )
        ruta = creado.headers["location"]

        reevaluado = cliente.post(f"{ruta}/reevaluar", follow_redirects=False)
        assert reevaluado.status_code == 303
        assert reevaluado.headers["location"] == ruta
        assert cliente.get(f"{ruta}/json").status_code == 200