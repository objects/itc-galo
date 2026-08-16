"""Contratos del repositorio de proyectos de prefactibilidad (Feature 5, Fase 2).

`ProyectoRepositorio` (app/web/db.py) persiste los proyectos creados desde la
interfaz web en SQLite (stdlib). Estos tests usan un archivo temporal
(tmp_path): ninguna prueba toca `PROYECTOS_DB_PATH` real.
"""

from __future__ import annotations

import pytest

from app.web.db import Proyecto, ProyectoRepositorio


def proyecto_ejemplo(**campos):
    """Proyecto canonico de prueba con campos overridables (patron conftest F3/F4)."""
    base = {
        "id": "proyecto-1",
        "nombre": "Lote de prueba",
        "criterio_tipo": "chip",
        "criterio_valor": "AAA0072LRYN",
        "consulta": "usos del suelo",
        "top_k": 3,
        "estado": "completado",
        "informe": {"feasibility_score": {"score": 70, "confidence": "media"}},
        "error": None,
        "creado_en": "2026-08-16T10:00:00Z",
        "actualizado_en": "2026-08-16T10:00:00Z",
    }
    base.update(campos)
    return Proyecto(**base)


def test_crear_y_obtener_roundtrip(tmp_path):
    repositorio = ProyectoRepositorio(tmp_path / "proyectos.db")
    proyecto = proyecto_ejemplo()
    repositorio.crear(proyecto)

    obtenido = repositorio.obtener("proyecto-1")

    assert obtenido is not None
    assert obtenido.id == "proyecto-1"
    assert obtenido.nombre == "Lote de prueba"
    assert obtenido.criterio_tipo == "chip"
    assert obtenido.criterio_valor == "AAA0072LRYN"
    assert obtenido.informe == {"feasibility_score": {"score": 70, "confidence": "media"}}


def test_obtener_inexistente_devuelve_none(tmp_path):
    repositorio = ProyectoRepositorio(tmp_path / "proyectos.db")

    assert repositorio.obtener("no-existe") is None


def test_listar_orden_descendente_por_actualizacion(tmp_path):
    repositorio = ProyectoRepositorio(tmp_path / "proyectos.db")
    repositorio.crear(proyecto_ejemplo(id="a", actualizado_en="2026-08-16T09:00:00Z"))
    repositorio.crear(proyecto_ejemplo(id="b", actualizado_en="2026-08-16T11:00:00Z"))
    repositorio.crear(proyecto_ejemplo(id="c", actualizado_en="2026-08-16T10:00:00Z"))

    ids = [proyecto.id for proyecto in repositorio.listar()]

    assert ids == ["b", "c", "a"]


def test_actualizar_reevaluacion_cambia_informe_y_estado(tmp_path):
    repositorio = ProyectoRepositorio(tmp_path / "proyectos.db")
    repositorio.crear(proyecto_ejemplo())

    reevaluado = proyecto_ejemplo(
        estado="completado",
        informe={"feasibility_score": {"score": 82, "confidence": "alta"}},
        actualizado_en="2026-08-16T12:00:00Z",
    )
    repositorio.actualizar(reevaluado)

    obtenido = repositorio.obtener("proyecto-1")
    assert obtenido is not None
    assert obtenido.informe == {"feasibility_score": {"score": 82, "confidence": "alta"}}
    assert obtenido.actualizado_en == "2026-08-16T12:00:00Z"


def test_actualizar_proyecto_fallido_con_error(tmp_path):
    repositorio = ProyectoRepositorio(tmp_path / "proyectos.db")
    repositorio.crear(proyecto_ejemplo())

    fallido = proyecto_ejemplo(
        estado="fallido",
        informe=None,
        error={"code": "FUENTE_5XX", "message": "La fuente no está disponible.", "source_name": "arcgis"},
        actualizado_en="2026-08-16T13:00:00Z",
    )
    repositorio.actualizar(fallido)

    obtenido = repositorio.obtener("proyecto-1")
    assert obtenido is not None
    assert obtenido.estado == "fallido"
    assert obtenido.informe is None
    assert obtenido.error["code"] == "FUENTE_5XX"


def test_actualizar_inexistente_levanta_error(tmp_path):
    repositorio = ProyectoRepositorio(tmp_path / "proyectos.db")

    with pytest.raises(ValueError):
        repositorio.actualizar(proyecto_ejemplo(id="fantasma"))


def test_crear_con_direccion_y_coordenadas(tmp_path):
    repositorio = ProyectoRepositorio(tmp_path / "proyectos.db")

    repositorio.crear(proyecto_ejemplo(id="d", criterio_tipo="direccion", criterio_valor="Calle 26 # 69-76"))
    repositorio.crear(proyecto_ejemplo(id="c", criterio_tipo="coordenadas", criterio_valor="4.665,-74.102"))

    assert repositorio.obtener("d").criterio_tipo == "direccion"
    assert repositorio.obtener("c").criterio_tipo == "coordenadas"


def test_repositorio_abre_archivo_existente_y_persiste(tmp_path):
    ruta = tmp_path / "proyectos.db"
    repositorio = ProyectoRepositorio(ruta)
    repositorio.crear(proyecto_ejemplo())

    segundo = ProyectoRepositorio(ruta)

    assert segundo.obtener("proyecto-1") is not None