"""Contratos F11 (T016) del wizard de prefactibilidad v2: preview ligero del lote.

Cubre `POST /proyectos/preview` (resolución por chip, dirección y coordenadas,
sin crear proyecto), sus validaciones 400/404, y el submit con los 5 campos
opcionales del interrogatorio (inversión). La persistencia de los campos vive
en `test_wizard_persistencia.py` (T017).

Todo hermético: providers simulados de `tests/conftest.py` (httpx.MockTransport,
sin red real ni Ollama).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.web.db import ProyectoRepositorio
from app.web.main import crear_app_web
from tests.conftest import (
    CHIP_INEXISTENTE,
    CHIP_VALIDO,
    NormativaProviderStub,
    respuesta_normativa_ok,
    server_lotes_f3,
)

CAMPOS_WIZARD_COMPLETOS = {
    "uso_previsto": "residencial",
    "escala_m2": "120",
    # Enum real del servidor (PRESUPUESTO_VALIDOS en app/web/main.py), que
    # diverge del literal {bajo,medio,alto} de contracts/wizard.md.
    "presupuesto_rango": "1000_5000M",
    "horizonte_meses": "12",
    "aversion_riesgo": "baja",
}


def _cliente(tmp_path: Path) -> tuple[TestClient, ProyectoRepositorio]:
    """App web con providers herméticos; retorna cliente y repositorio."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok())
    )
    repositorio = ProyectoRepositorio(tmp_path / "web.db")
    app = crear_app_web(servidor_lotes=servidor, repositorio=repositorio)
    cliente = TestClient(app)
    return cliente, repositorio


def _datos_base(**extra: str) -> dict[str, str]:
    datos = {"nombre": "Mi lote", "criterio_tipo": "chip", "criterio_valor": CHIP_VALIDO}
    datos.update(extra)
    return datos


# --- Preview: tres criterios de resolución ---------------------------------


def test_preview_por_chip_devuelve_lote_y_upl_sin_crear_proyecto(tmp_path: Path) -> None:
    cliente, repositorio = _cliente(tmp_path)
    with cliente:
        respuesta = cliente.post(
            "/proyectos/preview",
            data={"criterio_tipo": "chip", "criterio_valor": CHIP_VALIDO},
        )
        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert cuerpo["lote"]["chip"] == CHIP_VALIDO
        assert "lat" in cuerpo["lote"]["centroid"]
        assert "lng" in cuerpo["lote"]["centroid"]
        assert cuerpo["upl"]["codigo"] == "UPL24"
        # Invariante wizard.md: el preview NUNCA crea un Proyecto.
        assert repositorio.listar() == []


def test_preview_por_direccion_resuelve_geocodificada(tmp_path: Path) -> None:
    cliente, _ = _cliente(tmp_path)
    with cliente:
        respuesta = cliente.post(
            "/proyectos/preview",
            data={"criterio_tipo": "direccion", "criterio_valor": "Calle 26 # 69-76"},
        )
        assert respuesta.status_code == 200
        assert "lote" in respuesta.json()


def test_preview_por_coordenadas_formato_lat_lon(tmp_path: Path) -> None:
    cliente, repositorio = _cliente(tmp_path)
    with cliente:
        respuesta = cliente.post(
            "/proyectos/preview",
            data={"criterio_tipo": "coordenadas", "criterio_valor": "4.665,-74.102"},
        )
        assert respuesta.status_code == 200
        assert "lote" in respuesta.json()
        assert repositorio.listar() == []


def test_preview_coordenadas_invalidas_400(tmp_path: Path) -> None:
    cliente, _ = _cliente(tmp_path)
    with cliente:
        respuesta = cliente.post(
            "/proyectos/preview",
            data={"criterio_tipo": "coordenadas", "criterio_valor": "abc"},
        )
        assert respuesta.status_code == 400


def test_preview_chip_inexistente_404_con_codigo_canonico(tmp_path: Path) -> None:
    cliente, _ = _cliente(tmp_path)
    with cliente:
        respuesta = cliente.post(
            "/proyectos/preview",
            data={"criterio_tipo": "chip", "criterio_valor": CHIP_INEXISTENTE},
        )
        assert respuesta.status_code == 404
        assert respuesta.json()["error"]["code"] == "LOTE_NO_ENCONTRADO"


# --- Preview: validaciones de entrada (400) --------------------------------


def test_preview_criterio_tipo_invalido_400(tmp_path: Path) -> None:
    cliente, _ = _cliente(tmp_path)
    with cliente:
        respuesta = cliente.post(
            "/proyectos/preview",
            data={"criterio_tipo": "otro", "criterio_valor": CHIP_VALIDO},
        )
        assert respuesta.status_code == 400


def test_preview_valor_vacio_400(tmp_path: Path) -> None:
    cliente, _ = _cliente(tmp_path)
    with cliente:
        respuesta = cliente.post(
            "/proyectos/preview",
            data={"criterio_tipo": "chip", "criterio_valor": ""},
        )
        assert respuesta.status_code == 400


def test_preview_chip_malformado_400(tmp_path: Path) -> None:
    cliente, _ = _cliente(tmp_path)
    with cliente:
        respuesta = cliente.post(
            "/proyectos/preview",
            data={"criterio_tipo": "chip", "criterio_valor": "ABC"},
        )
        assert respuesta.status_code == 400


# --- Submit con interrogatorio (validación server-side 400) -----------------


def test_submit_con_5_campos_wizard_aceptado(tmp_path: Path) -> None:
    cliente, _ = _cliente(tmp_path)
    with cliente:
        respuesta = cliente.post(
            "/proyectos",
            data=_datos_base(**CAMPOS_WIZARD_COMPLETOS),
            follow_redirects=False,
        )
        assert respuesta.status_code == 303


def test_submit_escala_menor_a_36_rechazada_400(tmp_path: Path) -> None:
    cliente, _ = _cliente(tmp_path)
    with cliente:
        respuesta = cliente.post(
            "/proyectos",
            data=_datos_base(uso_previsto="residencial", escala_m2="10"),
            follow_redirects=False,
        )
        assert respuesta.status_code == 400


def test_submit_escala_no_numerica_rechazada_400(tmp_path: Path) -> None:
    cliente, _ = _cliente(tmp_path)
    with cliente:
        respuesta = cliente.post(
            "/proyectos",
            data=_datos_base(escala_m2="abc"),
            follow_redirects=False,
        )
        assert respuesta.status_code == 400


def test_submit_uso_previsto_invalido_rechazado_400(tmp_path: Path) -> None:
    cliente, _ = _cliente(tmp_path)
    with cliente:
        respuesta = cliente.post(
            "/proyectos",
            data=_datos_base(uso_previsto="cuantico"),
            follow_redirects=False,
        )
        assert respuesta.status_code == 400


def test_submit_legacy_sin_campos_wizard_sigue_funcionando(tmp_path: Path) -> None:
    """No-regresión F5: el submit sin los 5 campos opcionales sigue siendo 303."""
    cliente, _ = _cliente(tmp_path)
    with cliente:
        respuesta = cliente.post("/proyectos", data=_datos_base(), follow_redirects=False)
        assert respuesta.status_code == 303


# --- Evidencia estática de la vista (clic mapa / un solo paso / sin recarga) --


def test_landing_incorpora_mapa_leaflet_y_formulario_unico(tmp_path: Path) -> None:
    """El preview con clic en mapa y la persistencia client-side entre pasos se
    materializan en una única página con Leaflet vendorizado y fetch del preview
    (desviación documentada: sin hx-include, el form único conserva los valores).
    """
    cliente, _ = _cliente(tmp_path)
    with cliente:
        html = cliente.get("/").text
        assert "mapa-seleccion" in html  # contenedor del mapa Leaflet (JS usa global L)
        assert "/proyectos/preview" in html
        assert "uso_previsto" in html
        assert "escala_m2" in html
