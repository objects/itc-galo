"""Smoke test web (Feature 5): la interfaz web arranca, registra las rutas
US1/US2 y sirve los estaticos (htmx + fuentes Fraunces vendorizadas).

Sin red real ni Ollama: se inyecta `server_lotes_f3` (providers simulados) y un
`ProyectoRepositorio` temporal. Verifica el contrato de arranque de la Fase 1
(crear_app_web) y los assets del diseno de la Fase 6 (5 Pillars).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.web.db import ProyectoRepositorio
from app.web.main import crear_app_web
from tests.conftest import CHIP_VALIDO, NormativaProviderStub, respuesta_normativa_ok, server_lotes_f3

ESTATICOS_ESPERADOS = {
    "/static/htmx.min.js",
    "/static/fonts.css",
    "/static/estilos.css",
    "/static/fonts/fraunces-var-normal-latin.woff2",
    "/static/fonts/fraunces-var-normal-latinext.woff2",
    "/static/fonts/fraunces-var-normal-viet.woff2",
    "/static/fonts/fraunces-var-italic-latin.woff2",
    "/static/fonts/fraunces-var-italic-latinext.woff2",
    "/static/fonts/fraunces-var-italic-viet.woff2",
}

RUTAS_ESPERADAS = {
    "/",
    "/proyectos",
    "/proyectos/{proyecto_id}",
    "/proyectos/{proyecto_id}/reevaluar",
    "/proyectos/{proyecto_id}/json",
}


def _cliente(tmp_path) -> TestClient:
    servidor = server_lotes_f3(normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok()))
    repositorio = ProyectoRepositorio(tmp_path / "web.db")
    app = crear_app_web(servidor_lotes=servidor, repositorio=repositorio)
    return TestClient(app)


def test_crear_app_web_registra_las_rutas_us1_us2(tmp_path):
    """La factory expone las 5 rutas de la interfaz (US1 + US2)."""
    with _cliente(tmp_path) as cliente:
        rutas = {ruta.path for ruta in cliente.app.routes}
        assert RUTAS_ESPERADAS <= rutas


def test_index_responde_200_y_carga_la_identidad_visual(tmp_path):
    with _cliente(tmp_path) as cliente:
        respuesta = cliente.get("/")
        assert respuesta.status_code == 200
        # Identidad "Bogota Reverdece" (Pilar 2): titulo de marca + kicker del POT.
        assert "Prefactibilidad de lotes" in respuesta.text
        assert "Bogotá Reverdece" in respuesta.text
        # HTMX cargado desde el propio servidor (sin CDN) y estilos vendorizados.
        assert '/static/htmx.min.js' in respuesta.text
        assert '/static/fonts.css' in respuesta.text
        assert '/static/estilos.css' in respuesta.text


def test_estaticos_vendorizados_se_sirven_sin_cdn(tmp_path):
    """Todos los assets del diseno (htmx + Fraunces) se sirven localmente (200)."""
    with _cliente(tmp_path) as cliente:
        for ruta in ESTATICOS_ESPERADOS:
            respuesta = cliente.get(ruta)
            assert respuesta.status_code == 200, f"{ruta} deberia servirse (200)"


def test_flujo_completo_web_crea_y_muestra_informe(tmp_path):
    """End-to-end minimo: POST crea, redirige, GET muestra el score y /json lo expone."""
    with _cliente(tmp_path) as cliente:
        creado = cliente.post(
            "/proyectos",
            data={"nombre": "Smoke", "criterio_tipo": "chip", "criterio_valor": CHIP_VALIDO},
            follow_redirects=False,
        )
        assert creado.status_code == 303
        ruta = creado.headers["location"]

        detalle = cliente.get(ruta)
        assert detalle.status_code == 200
        assert "Smoke" in detalle.text
        # La unica animacion del sitio (Pilar 3): el anillo de score.
        assert "anillo-score" in detalle.text

        informe = cliente.get(f"{ruta}/json")
        assert informe.status_code == 200
        assert informe.json()["feasibility_score"]["score"] >= 0