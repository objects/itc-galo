"""Contratos F11 (T017) de persistencia del wizard de prefactibilidad v2.

Verifica que los 5 campos del interrogatorio (uso_previsto, escala_m2,
presupuesto_rango, horizonte_meses, aversion_riesgo) persisten con el
proyecto, reaparecen en `GET /proyectos/{id}/json` (objeto aditivo `wizard`,
T012), sobreviven a `reevaluar`, y que una fila anterior a la migración se
lee con los campos en `None` sin error 500.

Todo hermético: SQLite en `tmp_path` y providers simulados de
`tests/conftest.py` (sin red real ni Ollama).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.web.db import ProyectoRepositorio
from app.web.main import crear_app_web
from tests.conftest import (
    CHIP_VALIDO,
    NormativaProviderStub,
    respuesta_normativa_ok,
    server_lotes_f3,
)

WIZARD_FORM = {
    "uso_previsto": "residencial",
    "escala_m2": "120",
    "presupuesto_rango": "1000_5000M",
    "horizonte_meses": "12",
    "aversion_riesgo": "baja",
}

# Valores esperados tras round-trip por SQLite (escala REAL, horizonte INTEGER).
WIZARD_ESPERADO = {
    "uso_previsto": "residencial",
    "escala_m2": 120.0,
    "presupuesto_rango": "1000_5000M",
    "horizonte_meses": 12,
    "aversion_riesgo": "baja",
}


def _cliente(tmp_path: Path) -> TestClient:
    """App web con providers herméticos (mismo patrón que test_web_rutas)."""
    servidor = server_lotes_f3(
        normativa=NormativaProviderStub(respuesta=respuesta_normativa_ok())
    )
    repositorio = ProyectoRepositorio(tmp_path / "web.db")
    app = crear_app_web(servidor_lotes=servidor, repositorio=repositorio)
    return TestClient(app)


def _crear_proyecto_con_wizard(cliente: TestClient) -> str:
    """Submit con los 5 campos; retorna el id según el header Location (303)."""
    respuesta = cliente.post(
        "/proyectos",
        data={
            "nombre": "Proyecto wizard",
            "criterio_tipo": "chip",
            "criterio_valor": CHIP_VALIDO,
            **WIZARD_FORM,
        },
        follow_redirects=False,
    )
    assert respuesta.status_code == 303
    return respuesta.headers["location"].rstrip("/").split("/")[-1]


def test_wizard_persiste_y_reaparece_en_json(tmp_path: Path) -> None:
    cliente = _cliente(tmp_path)
    with cliente:
        proyecto_id = _crear_proyecto_con_wizard(cliente)
        respuesta = cliente.get(f"/proyectos/{proyecto_id}/json")
        assert respuesta.status_code == 200
        assert respuesta.json()["wizard"] == WIZARD_ESPERADO


def test_reevaluar_conserva_los_campos_del_wizard(tmp_path: Path) -> None:
    cliente = _cliente(tmp_path)
    with cliente:
        proyecto_id = _crear_proyecto_con_wizard(cliente)
        reevaluado = cliente.post(
            f"/proyectos/{proyecto_id}/reevaluar", follow_redirects=False
        )
        assert reevaluado.status_code in (200, 303)
        respuesta = cliente.get(f"/proyectos/{proyecto_id}/json")
        assert respuesta.status_code == 200
        assert respuesta.json()["wizard"] == WIZARD_ESPERADO


def test_fila_antigua_sin_columnas_wizard_se_lee_sin_error(tmp_path: Path) -> None:
    """Una fila creada antes de la migración (columnas wizard NULL) se lee como
    Proyecto con los 5 campos en None: compatibilidad hacia atrás FR-011."""
    ruta_db = tmp_path / "web.db"
    repositorio = ProyectoRepositorio(ruta_db)  # corre CREATE + ALTER idempotentes
    conexion = sqlite3.connect(ruta_db)
    try:
        conexion.execute(
            "INSERT INTO proyectos ("
            "id, nombre, criterio_tipo, criterio_valor, consulta, top_k, "
            "estado, informe, error, creado_en, actualizado_en"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "viejo-1",
                "Viejo",
                "chip",
                CHIP_VALIDO,
                None,
                5,
                "completado",
                None,
                None,
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conexion.commit()
    finally:
        conexion.close()

    proyecto = repositorio.obtener("viejo-1")
    assert proyecto is not None
    assert proyecto.uso_previsto is None
    assert proyecto.escala_m2 is None
    assert proyecto.presupuesto_rango is None
    assert proyecto.horizonte_meses is None
    assert proyecto.aversion_riesgo is None
