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

    # El CHIP solo proviene de la API de Mapas Bogota; las capas catastrales
    # ArcGIS no lo traen. Por coordenadas la identidad la dan LOTCODIGO/
    # MANZCODIGO, asi que chip puede ser None (decision de producto).
    chip: str | None = None
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


# --- Feature 2 (RAG normativo del POT, Decreto 555/2021) ---
# Entidades nuevas del data-model.md de F2: UPL y Localidad (get_upl) y
# ArticuloNormativo / Chunk / CorpusInfo (ingesta y RAG normativo). Reutilizan
# SourceTrace de F1 (5 campos, Principio III NON-NEGOTIABLE).

# Nombre unico de la coleccion ChromaDB del corpus normativo: lo comparten la
# ingesta (app.ingesta.corpus) y el provider RAG (app.providers.normativa).
COLECCION_NORMATIVA = "decreto_555_2021"

# Claves de metadata de la coleccion ChromaDB (FR-008): identifican la version
# del corpus indexada y el modelo de embeddings que genero los vectores. Un
# cambio en cualquiera de las dos obliga a reconstruir el indice para no mezclar
# vigencias/versiones ni vectores de modelos distintos en el mismo espacio HNSW.
METADATA_CORPUS_SHA256 = "corpus_sha256"
METADATA_EMBEDDING_MODEL = "embedding_model"


class UPL(BaseModel):
    """Unidad de Planeamiento Local del POT de Bogota (data-model.md:57-78).

    Entidad territorial de planeamiento definida por el Decreto 555/2021. Se
    obtiene por join espacial punto-en-poligono del centroide del Lote contra la
    capa `ordenamientoterritorial/unidadplaneamientolocal` (research D2). La
    `localidad_derivada` se obtiene por mapeo `NOMBRE -> localidad` (research
    D3): nunca se lee de la capa UPL. Los campos de acto administrativo,
    normativa y vocacion provienen de los atributos de la capa.

    Estados de dato (FR-007): `disponible` (UPL encontrada) o `no_encontrado`
    (en get_upl se reporta como LOTE_SIN_UPL, no como un objeto con ceros).
    """

    codigo_upl: str
    nombre: str
    localidad_derivada: str | None = None
    acto_administrativo: str | None = None
    numero_acto_administrativo: str | None = None
    fecha_acto_administrativo: str | None = None
    normativa: str | None = None
    vocacion: str | None = None
    observacion: str | None = None
    area_ha: float | None = None
    estado: EstadoDato | None = None
    source_trace: SourceTrace | None = None


class Localidad(BaseModel):
    """Division administrativa de Bogota (data-model.md:80-88).

    Contiene una o mas UPL; cada UPL se ubica dentro de una unica localidad
    (relacion normativa del POT).
    """

    codigo: str
    nombre: str


class ArticuloNormativo(BaseModel):
    """Articulo del Decreto 555/2021 con su texto literal y ubicacion en el
    documento (data-model.md:90-104).

    Unidad de recuperacion del RAG normativo. `texto` es el texto literal de la
    fuente oficial (FR-003) y `parte` (`general` | `urbano` | `rural`, o
    `None` para "sin parte") es la base del filtro estricto por UPL (FR-002).
    `upls_mencionadas` registra las UPLs que el articulo menciona
    explicitamente (mencion explicita del mismo filtro).
    """

    numero: int
    titulo: str
    texto: str
    libro: str
    parte: str | None = None
    seccion: str | None = None
    upls_mencionadas: list[str] = []
    articulos_derogados: list[int] = []


class Chunk(BaseModel):
    """Pieza indexada en el vector store, derivada de un ArticuloNormativo
    (data-model.md:128-143).

    Chunking boundary-aware (research D6): 1 chunk = 1 articulo; los articulos
    largos se parten por paragrafos con overlap y heredan los metadatos del
    articulo. `texto` es el fragmento literal que se cita (FR-003).
    """

    id: str
    articulo: int
    titulo: str
    libro: str
    parte: str | None = None
    seccion: str | None = None
    texto: str


class CorpusInfo(BaseModel):
    """Coleccion de articulos del Decreto 555/2021 indexada (data-model.md:106-126).

    El corpus parseado es la fuente de verdad versionada en git (FR-009); el
    indice vectorial es un dato derivado regenerable. `hash_sha256` es la huella
    del corpus que permite verificar integridad y actualidad del indice.
    """

    documento: str
    vigencia: str
    hash_sha256: str
    total_articulos: int
