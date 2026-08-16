"""Repositorio de proyectos de prefactibilidad (Feature 5, Fase 2).

Persistencia en SQLite (stdlib) de los proyectos creados desde la interfaz
web: crear/obtener/listar/actualizar sobre la entidad pydantic `Proyecto`.
El informe de factibilidad y el error se serializan a texto JSON (columnas
`informe`/`error`); los demas campos son columnas escalares.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

TipoCriterio = Literal["chip", "direccion", "coordenadas"]
EstadoProyecto = Literal["completado", "fallido"]


class Proyecto(BaseModel):
    """Proyecto de evaluacion de prefactibilidad persistido en la interfaz web."""

    id: str
    nombre: str
    criterio_tipo: TipoCriterio
    criterio_valor: str
    consulta: str | None = None
    top_k: int = 3
    estado: EstadoProyecto
    informe: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    creado_en: str
    actualizado_en: str


def ahora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _a_json(valor: dict[str, Any] | None) -> str | None:
    return json.dumps(valor) if valor is not None else None


def _fila_a_proyecto(fila: sqlite3.Row) -> Proyecto:
    return Proyecto(
        id=fila["id"],
        nombre=fila["nombre"],
        criterio_tipo=fila["criterio_tipo"],
        criterio_valor=fila["criterio_valor"],
        consulta=fila["consulta"],
        top_k=fila["top_k"],
        estado=fila["estado"],
        informe=json.loads(fila["informe"]) if fila["informe"] is not None else None,
        error=json.loads(fila["error"]) if fila["error"] is not None else None,
        creado_en=fila["creado_en"],
        actualizado_en=fila["actualizado_en"],
    )


class ProyectoRepositorio:
    """Repositorio SQLite (stdlib) de proyectos de prefactibilidad.

    Cada operacion abre una conexion nueva sobre el mismo archivo; la tabla se
    crea con IF NOT EXISTS en el constructor (abrir el repositorio es
    idempotente). El directorio padre se crea si no existe.
    """

    def __init__(self, ruta_db: str | Path) -> None:
        self._ruta = Path(ruta_db)
        self._crear_tabla()

    def _conexion(self) -> sqlite3.Connection:
        os.makedirs(self._ruta.parent, exist_ok=True)
        conexion = sqlite3.connect(self._ruta)
        conexion.row_factory = sqlite3.Row
        return conexion

    def _crear_tabla(self) -> None:
        with self._conexion() as conexion:
            conexion.execute(
                """
                CREATE TABLE IF NOT EXISTS proyectos (
                    id TEXT PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    criterio_tipo TEXT NOT NULL,
                    criterio_valor TEXT NOT NULL,
                    consulta TEXT,
                    top_k INTEGER NOT NULL,
                    estado TEXT NOT NULL,
                    informe TEXT,
                    error TEXT,
                    creado_en TEXT NOT NULL,
                    actualizado_en TEXT NOT NULL
                )
                """
            )

    def crear(self, proyecto: Proyecto) -> Proyecto:
        """Persiste un proyecto nuevo y lo devuelve tal cual."""
        with self._conexion() as conexion:
            conexion.execute(
                "INSERT INTO proyectos (id, nombre, criterio_tipo, criterio_valor, "
                "consulta, top_k, estado, informe, error, creado_en, actualizado_en) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    proyecto.id,
                    proyecto.nombre,
                    proyecto.criterio_tipo,
                    proyecto.criterio_valor,
                    proyecto.consulta,
                    proyecto.top_k,
                    proyecto.estado,
                    _a_json(proyecto.informe),
                    _a_json(proyecto.error),
                    proyecto.creado_en,
                    proyecto.actualizado_en,
                ),
            )
        return proyecto

    def obtener(self, proyecto_id: str) -> Proyecto | None:
        """Devuelve el proyecto por id, o None si no existe."""
        with self._conexion() as conexion:
            fila = conexion.execute(
                "SELECT * FROM proyectos WHERE id = ?", (proyecto_id,)
            ).fetchone()
        return _fila_a_proyecto(fila) if fila is not None else None

    def listar(self) -> list[Proyecto]:
        """Lista los proyectos ordenados por actualizacion descendente."""
        with self._conexion() as conexion:
            filas = conexion.execute(
                "SELECT * FROM proyectos ORDER BY actualizado_en DESC"
            ).fetchall()
        return [_fila_a_proyecto(fila) for fila in filas]

    def actualizar(self, proyecto: Proyecto) -> Proyecto:
        """Actualiza un proyecto existente; error si el id no existe."""
        with self._conexion() as conexion:
            cursor = conexion.execute(
                "UPDATE proyectos SET nombre = ?, criterio_tipo = ?, "
                "criterio_valor = ?, consulta = ?, top_k = ?, estado = ?, "
                "informe = ?, error = ?, actualizado_en = ? WHERE id = ?",
                (
                    proyecto.nombre,
                    proyecto.criterio_tipo,
                    proyecto.criterio_valor,
                    proyecto.consulta,
                    proyecto.top_k,
                    proyecto.estado,
                    _a_json(proyecto.informe),
                    _a_json(proyecto.error),
                    proyecto.actualizado_en,
                    proyecto.id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"No existe el proyecto {proyecto.id}")
        return proyecto