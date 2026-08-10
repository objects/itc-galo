"""Modelos pydantic v2 del dominio de mcp-bogota-factibilidad (T006-T009).

Los providers parsean el JSON crudo de cada fuente una sola vez (constitucion,
Principio II) y exponen modelos tipados como frontera de parsing. Toda salida
para el LLM lleva un SourceTrace de 5 campos (Principio III, FR-006) y distingue
el estado `disponible` de `no_encontrado` por fuente (FR-007, SC-002).

Los nombres de campo del contrato se conservan en ingles donde lo exige
(constitucion, Principio I); la prosa esta en espanol.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

# Estado de un dato tematico por fuente (FR-007): un dato ausente o no aplicable
# se reporta como "no_encontrado", nunca como cero ni vacio silencioso.
EstadoDato = Literal["disponible", "no_encontrado"]


class SourceTrace(BaseModel):
    """Trazabilidad canonica de un dato (FR-006, Principio III NON-NEGOTIABLE).

    Los 5 campos son obligatorios en toda salida para el LLM, incluida la marca
    de tiempo de la consulta (hallazgo del revisor: el contrato la exige siempre).
    """

    source_name: str
    layer_id: str
    service_url: str
    data_vigencia: str
    query_timestamp: str


class Centroide(BaseModel):
    """Centroide de un lote en WGS84 (SRID 4326)."""

    lat: float
    lng: float


class Lote(BaseModel):
    """Unidad predial catastral de Bogota: entidad central de la feature.

    Toda consulta (por CHIP, direccion o coordenadas) resuelve a un Lote y el
    contexto tematico se asocia a el (data-model.md).

    Jerarquia de fuentes (decision A1 punto 1, opcion b): la fuente primaria de
    identidad y geometria es la capa ArcGIS layer 38 (Mapa_Referencia), y
    `source_trace` documenta esa capa. `direccion_normalizada` y `barrio`, cuando
    la capa no los trae, se enriquecen desde Mapas Bogota (direccion_chip) o
    desde el geocodificador en el flujo por direccion; el contrato documenta esta
    doble procedencia en su seccion Trazabilidad. Los campos enriquecidos no
    declaran vigencia propia: no se mezclan vigencias (FR-008).
    """

    chip: str
    codigo_catastral: str
    manzana: str
    direccion_normalizada: str | None = None
    barrio: str | None = None
    geometry: dict[str, Any]
    centroid: Centroide
    source_trace: SourceTrace


class DatoTematico(BaseModel):
    """Base de las entidades tematicas: cada una lleva estado y trazabilidad."""

    estado: EstadoDato
    source_trace: SourceTrace

    def a_dato_contrato(self) -> dict[str, Any]:
        """Serializa al shape {estado, dato, source_trace} de los contratos.

        Cuando estado=no_encontrado, `dato` es None (FR-007): nunca cero ni
        vacio silencioso.
        """
        contenido = self.model_dump(exclude={"estado", "source_trace"}, exclude_none=True)
        return {
            "estado": self.estado,
            "dato": contenido if self.estado == "disponible" else None,
            "source_trace": self.source_trace.model_dump(),
        }


class ValorReferencia(DatoTematico):
    """Valor de referencia catastral del terreno (catastro/valorreferencia)."""

    valor_m2: float | None = None
    unidad_monetaria: str | None = None
    vigencia: str | None = None


class DestinoEconomico(DatoTematico):
    """Destino economico predominante del lote (catastro/destinolt)."""

    codigo_destino: str | None = None
    descripcion_destino: str | None = None
    vigencia: str | None = None


class ReservaVial(DatoTematico):
    """Zona de reserva vial que afecta o se superpone al lote."""

    afecta_lote: bool | None = None
    descripcion: str | None = None
    vigencia: str | None = None


class ObraPublica(DatoTematico):
    """Obras publicas cercanas al lote segun la gestion publica distrital."""

    obras: list[dict[str, Any]] | None = None
    vigencia: str | None = None


class ContextoTematico(BaseModel):
    """Las 4 tematicas consultadas en paralelo para un lote (FR-004, SC-001)."""

    valor_referencia: ValorReferencia
    destino_economico: DestinoEconomico
    reserva_vial: ReservaVial
    obras_publicas: ObraPublica

    def a_contexto_contrato(self) -> dict[str, Any]:
        """Formato contexto_tematico de los contratos resolve_lot_by_*."""
        return {
            "valor_referencia": self.valor_referencia.a_dato_contrato(),
            "destino_economico": self.destino_economico.a_dato_contrato(),
            "reserva_vial": self.reserva_vial.a_dato_contrato(),
            "obras_publicas": self.obras_publicas.a_dato_contrato(),
        }

    def a_lista_por_fuente(self) -> list[dict[str, Any]]:
        """Formato contexto_por_fuente del contrato get_lot_summary_by_chip."""
        fuentes = [
            ("valor_referencia", self.valor_referencia),
            ("destino_economico", self.destino_economico),
            ("reserva_vial", self.reserva_vial),
            ("obras_publicas", self.obras_publicas),
        ]
        return [
            {
                "fuente": nombre,
                "estado": dato.estado,
                "dato": dato.a_dato_contrato()["dato"],
                "source_trace": dato.source_trace.model_dump(),
            }
            for nombre, dato in fuentes
        ]
