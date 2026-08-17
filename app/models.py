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

from pydantic import BaseModel, field_validator

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


class UsoEconomico(BaseModel):
    """Uso de una fila de construccion del predio (capa Predio, PRECUSO/PREAUSO).

    Sub-entidad de `DestinoEconomico`: cada fila de la capa tabular Predio
    representa un uso con su area asignada en la fuente (research H3).
    """

    codigo: str
    descripcion: str
    area_uso: float


class DestinoEconomico(BaseModel):
    """Destino economico predominante del lote (capa tabular Predio catastro/lote/3).

    Reactivado en F3 con la NUEVA fuente (research D1/H1): la capa tabular
    `catastro/lote/MapServer/3` (f=pjson), consultada por PRECHIP o BARMANPRE.
    La fila con mayor PREAUSO define el destino principal
    (`codigo_destino`/`descripcion_destino`/`uso`/`area_uso`); las demas se
    listan en `usos`. `vigencia` = PREVACTUAL del registro (research H7) y
    alimenta el `data_vigencia` del source_trace del bloque.
    """

    estado: EstadoDato
    codigo_destino: str | None = None
    descripcion_destino: str | None = None
    uso: str | None = None
    area_uso: float | None = None
    usos: list[UsoEconomico] = []
    area_terreno: float | None = None
    area_construccion: float | None = None
    direccion: str | None = None
    barrio: str | None = None
    vigencia: str | None = None
    source_trace: SourceTrace


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
    """Las tematicas consultadas en paralelo para un lote (FR-004, SC-001).

    destinolt (catastro/destinolt) se retiro del contexto por defecto: el
    servicio responde 500 en vivo (Fix C; ver app/providers/arcgis.py). Para
    re-anadirlo, restaurar su consulta y el campo `destino_economico` aqui.
    """

    valor_referencia: ValorReferencia
    reserva_vial: ReservaVial
    obras_publicas: ObraPublica

    def a_contexto_contrato(self) -> dict[str, Any]:
        """Formato contexto_tematico de los contratos resolve_lot_by_*."""
        return {
            "valor_referencia": self.valor_referencia.a_dato_contrato(),
            "reserva_vial": self.reserva_vial.a_dato_contrato(),
            "obras_publicas": self.obras_publicas.a_dato_contrato(),
        }

    def a_lista_por_fuente(self) -> list[dict[str, Any]]:
        """Formato contexto_por_fuente del contrato get_lot_summary_by_chip."""
        fuentes = [
            ("valor_referencia", self.valor_referencia),
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

# Vigencia del Decreto 555/2021 (FR-014): fecha mínima de expedición de un acto
# que pretenda reglamentarlo o modificarlo. Es el dato del POT base (research
# H4: Registro Distrital No. 7326, vigencia 30/12/2021).
FECHA_VIGENCIA_555 = "2021-12-30"

# Formato del archivo fuente de un acto normativo (FR-001): sisjur_html es el
# formato recomendado; pdf/docx/markdown/txt se extraen de forma genérica (D5).
FormatoDocumento = Literal["sisjur_html", "pdf", "docx", "markdown", "txt"]

# Campos aditivos F4 de identificación de norma (data-model.md:88-111). Se
# excluyen de la huella canónica del corpus (`hash_documento`) para que el
# Decreto 555 conserve exactamente su hash actual (FR-012): el 555 los tiene en
# None y el JSONL versionado NO se modifica; los actos los pueblan.
CAMPOS_ADITIVOS_F4 = (
    "norma_id",
    "tipo_norma",
    "numero_norma",
    "año",
    "fecha_vigencia",
    "titulo_norma",
)


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

    # --- Campos aditivos F4 (norma de origen, data-model.md:88-111) ---
    # Opcionales con default None: el 555 conserva exactamente su esquema F2
    # (FR-011, FR-012); los actos modificatorios los pueblan al integrarse al
    # corpus consolidado. `numero_norma` evita colisionar con `numero` (número
    # de ARTÍCULO, semántica F2 inalterable); el contrato JSONL usa ese nombre.
    norma_id: str | None = None
    tipo_norma: Literal["decreto", "resolucion"] | None = None
    numero_norma: int | None = None
    año: int | None = None
    fecha_vigencia: str | None = None
    titulo_norma: str | None = None


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

    # --- Campos aditivos F4 (norma de origen + trazabilidad, data-model.md:113-130) ---
    # Opcionales con default None: el 555 conserva su esquema F2 (FR-011); los
    # actos los pueblan. `source_name`/`data_vigencia` son los campos FR-004 del
    # SourceTrace por fragmento; `relacion_con_555` se hereda del documento.
    norma_id: str | None = None
    tipo_norma: Literal["decreto", "resolucion"] | None = None
    numero_norma: int | None = None
    año: int | None = None
    fecha_vigencia: str | None = None
    titulo_norma: str | None = None
    source_name: str | None = None
    data_vigencia: str | None = None
    relacion_con_555: Literal["referencia_articulos", "sin_referencia"] | None = None


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


class DocumentoNormativo(BaseModel):
    """Acto administrativo que reglamenta o modifica el Decreto 555/2021 (F4).

    Entidad nueva del data-model.md:40-70: cada acto (decreto o resolución)
    produce un JSONL versionado en git (FR-013) y un hash SHA-256 del ARCHIVO
    fuente para deduplicación (FR-007, SC-003). `articulos_referenciados` son
    los artículos del 555 enlazados desde sisjur (`Norma1.jsp?i=119582#NNN`,
    H2): referencia verificable por máquina para `relacion_con_555` (FR-014).

    Reglas de dominio:
    - Rechazo FR-014: `fecha_expedicion < FECHA_VIGENCIA_555` (2021-12-30) -> el
      acto NO puede reglamentar/modificar el 555 (validador + fail-fast tipificado
      en `app/ingesta/actos.py` ANTES de construir el modelo).
    - Advertencia FR-014: sin referencias verificables -> `relacion_con_555 =
      "sin_referencia"` (se integra con warning, no se rechaza).
    - Deduplicación FR-007: mismo `hash_sha256` en el registro -> no-op.
    """

    tipo_norma: Literal["decreto", "resolucion"]
    numero: int
    año: int
    documento_id: str
    titulo: str
    fecha_expedicion: str
    fecha_vigencia: str
    url_origen: str
    hash_sha256: str
    formato: FormatoDocumento
    relacion_con_555: Literal["referencia_articulos", "sin_referencia"]
    articulos_referenciados: list[int] = []
    estado_documento: Literal["vigente", "derogado"] | None = None
    derogado_compilado_por: str | None = None

    @field_validator("fecha_expedicion")
    @classmethod
    def _fecha_no_anterior_al_555(cls, valor: str) -> str:
        """Defensa en profundidad del FR-014 (el rechazo tipificado ya ocurrió en la ingesta).

        Comparación lexicográfica segura: ambas fechas son ISO 8601 (YYYY-MM-DD).
        """
        if valor < FECHA_VIGENCIA_555:
            raise ValueError(
                f"El acto no puede reglamentar ni modificar el Decreto 555 de 2021: "
                f"fecha_expedicion {valor} es anterior a la vigencia del 555 "
                f"({FECHA_VIGENCIA_555})."
            )
        return valor


# --- Feature 3 (Informe de factibilidad orquestado, get_feasibility_report) ---
# Entidades nuevas del data-model.md de F3 (data-model.md:71-152). El reporte es
# 100% deterministico (FR-006/FR-007): score e interpretaciones son funciones
# puras sobre los datos recuperados; la unica salida del RAG es normative_evidence.
# Reutiliza los modelos F1/F2 (Lote, SourceTrace, ValorReferencia, ReservaVial,
# ObraPublica, UPL, Localidad) sin modificarlos (CHK-015).


class FeasibilityScore(BaseModel):
    """Score heuristico 0-100 del reporte (research D3, FR-006/FR-007).

    `score` es un entero con clamp(0, 100); `confidence` canónico
    ("high" | "medium" | "low") por cobertura de los 6 bloques evaluables;
    `reasons` son textos fijos por regla con el dato interpolado y el
    `source_name`; `rules_applied` lista los codigos de regla que participaron
    (auditoria interna). Ninguna regla inventa normativa (FR-014).
    """

    score: int
    confidence: Literal["high", "medium", "low"]
    reasons: list[str]
    rules_applied: list[str]


class IdentidadLote(BaseModel):
    """Bloque lot_identity: identidad del lote (shape del contrato F1 `lote`).

    `chip` puede ser null cuando el lote se resolvio por coordenadas (la capa
    Lote 38 no publica CHIP); `codigo_catastral` (LOTCODIGO) siempre esta
    poblado y es el join key con BARMANPRE de la capa Predio (research H2).
    """

    chip: str | None = None
    codigo_catastral: str
    manzana: str
    direccion_normalizada: str | None = None
    barrio: str | None = None
    geometry: dict[str, Any]
    centroid: Centroide
    source_trace: SourceTrace


class ContextoAdministrativo(BaseModel):
    """Bloque administrative_context: UPL, localidad y clasificacion de suelo.

    `upl`/`localidad` son null + warning cuando la UPL no se resuelve (no error;
    research D5). `clasificacion_suelo` se deriva de `UPL.vocacion` (research
    D2/H4): "Urbano" -> urbano, "Rural" -> rural, "Urbano-Rural" -> urbano-rural;
    null si no hay UPL. `source_trace` es el de la capa UPL.
    """

    upl: UPL | None = None
    localidad: Localidad | None = None
    clasificacion_suelo: Literal["urbano", "rural", "urbano-rural"] | None = None
    source_trace: SourceTrace


class BloqueReservaVial(BaseModel):
    """Bloque planning_constraints con el patron F1 {estado, dato, interpretation, source_trace}."""

    estado: EstadoDato
    dato: ReservaVial | None = None
    interpretation: str
    source_trace: SourceTrace


class BloqueValorReferencia(BaseModel):
    """Bloque market_context con el patron F1 {estado, dato, interpretation, source_trace}."""

    estado: EstadoDato
    dato: ValorReferencia | None = None
    interpretation: str
    source_trace: SourceTrace


class BloqueObrasPublicas(BaseModel):
    """Bloque environment_context con el patron F1 {estado, dato, interpretation, source_trace}.

    El dato proviene de `consultar_obras_publicas_radio` (buffer 500 m sobre la
    capa multipunto, research H5); no reutiliza `ContextoTematico.obras_publicas`
    (consulta puntual de F1, que no cumple FR-004).
    """

    estado: EstadoDato
    dato: ObraPublica | None = None
    interpretation: str
    source_trace: SourceTrace


class BloqueDestinoEconomico(BaseModel):
    """Bloque economic_context con el patron F1 {estado, dato, interpretation, source_trace}.

    `dato` es el `DestinoEconomico` de la capa tabular Predio (research D1).
    """

    estado: EstadoDato
    dato: DestinoEconomico | None = None
    interpretation: str
    source_trace: SourceTrace


# --- Feature 5: Bloques adicionales del informe de factibilidad (riesgos geotecnicos,
# contexto socioeconomico, entorno regulatorio, patrimonio cultural, acceso movilidad) ---


class RiesgoGeotecnicos(BaseModel):
    """Riesgos geotecnicos del lote (emergencias/gestionriesgos).

    Consulta 4 capas en paralelo: amenaza movimientos en masa, geologia rural,
    respuesta sismica y zonificacion geotecnica. Reporta la clasificacion
    dominante y el nivel de amenaza.
    """

    amenaza_movimientos: str | None = None
    geologia: str | None = None
    respuesta_sismica: str | None = None
    zonificacion_geotecnica: str | None = None
    nivel_amenaza: Literal["alto", "medio", "bajo", "desconocido"] | None = None


class ContextoSocioeconomico(BaseModel):
    """Contexto socioeconomico del lote (estratificacion, uso predominante, altura, avaluo).

    Consulta 4 capas en paralelo: cada sub-bloque degrada independientemente.
    """

    estrato: int | None = None
    uso_predominante: str | None = None
    altura_media: float | None = None
    mediana_avaluo: float | None = None


class EntornoRegulatorio(BaseModel):
    """Entorno regulatorio del lote: licencias de construccion y zonas de plusvalia.

    Consulta 2 capas en paralelo: licencias aprobadas y planes parciales de plusvalia.
    """

    licencias_encontradas: int | None = None
    zona_plusvalia: bool | None = None
    nombre_plan_plusvalia: str | None = None


class PatrimonioCultural(BaseModel):
    """Patrimonio cultural del lote: BIC y zonas arqueologicas.

    Consulta 2 capas en paralelo: bienes de interes cultural y potencial arqueologico.
    """

    bic_cercano: bool | None = None
    nombre_bic: str | None = None
    zona_arqueologica: bool | None = None


class AccesoMovilidad(BaseModel):
    """Acceso a transporte publico del lote: TransMilenio, SITP y Metro.

    Consulta 3 capas con radio: estaciones TransMilenio (800 m), paraderos SITP
    (500 m) y estaciones Metro (800 m).
    """

    estaciones_transmilenio: int | None = None
    paraderos_sitp: int | None = None
    estaciones_metro: int | None = None
    estacion_cercana: str | None = None


class BloqueRiesgosGeotecnicos(BaseModel):
    """Bloque geotechnical_risks con el patron {estado, dato, interpretation, source_trace}."""

    estado: EstadoDato
    dato: RiesgoGeotecnicos | None = None
    interpretation: str
    source_trace: SourceTrace


class BloqueContextoSocioeconomico(BaseModel):
    """Bloque socioeconomic_context con el patron {estado, dato, interpretation, source_trace}."""

    estado: EstadoDato
    dato: ContextoSocioeconomico | None = None
    interpretation: str
    source_trace: SourceTrace


class BloqueEntornoRegulatorio(BaseModel):
    """Bloque regulatory_environment con el patron {estado, dato, interpretation, source_trace}."""

    estado: EstadoDato
    dato: EntornoRegulatorio | None = None
    interpretation: str
    source_trace: SourceTrace


class BloquePatrimonioCultural(BaseModel):
    """Bloque cultural_heritage con el patron {estado, dato, interpretation, source_trace}."""

    estado: EstadoDato
    dato: PatrimonioCultural | None = None
    interpretation: str
    source_trace: SourceTrace


class BloqueAccesoMovilidad(BaseModel):
    """Bloque transit_access con el patron {estado, dato, interpretation, source_trace}."""

    estado: EstadoDato
    dato: AccesoMovilidad | None = None
    interpretation: str
    source_trace: SourceTrace


class ContextoCatastro(BaseModel):
    """Datos catastrales adicionales del lote: construccion, manzana, densidad, variacion, sector.

    Consulta 5 capas del catastro en paralelo para enriquecer la respuesta
    del lote con informacion de construccion, manzana, densidad predial,
    variacion de area construida y sector catastral.
    """

    construccion: dict[str, Any] | None = None  # Building footprint data from catastro/construccion
    manzana: dict[str, Any] | None = None  # Block data from catastro/manzana
    densidad_predial: dict[str, Any] | None = None  # Property density from catastro/densidadpredialmz
    variacion_area: dict[str, Any] | None = None  # Built area variation from catastro/variacionareaconstruida
    sector_catastral: str | None = None  # Cadastral sector from catastro/sectorcatastral


class BloqueCatastroData(BaseModel):
    """Bloque catastro_data con el patron {estado, dato, interpretation, source_trace}."""

    estado: EstadoDato
    dato: ContextoCatastro | None = None
    interpretation: str
    source_trace: SourceTrace


class ItemEvidenciaNormativa(BaseModel):
    """Articulo del POT citado literalmente en normative_evidence (shape del contrato).

    `texto_cita` es el fragmento literal de la fuente oficial (FR-003);
    `similitud` es la similitud del chunk recuperado por el RAG.
    """

    articulo: str
    titulo: str
    libro: str
    parte: str | None = None
    texto_cita: str
    similitud: float | None = None

    # --- Campos aditivos F4 (data-model.md:148-152) ---
    # Identificación de la norma real del fragmento por ítem (FR-004/FR-005):
    # `norma` (nombre legible) y `source_name` (trazabilidad FR-004). El
    # `source_trace` de BLOQUE se conserva intacto.
    norma: str | None = None
    source_name: str | None = None


class EvidenciaNormativa(BaseModel):
    """Bloque normative_evidence: evidencia del POT (Decreto 555/2021) con citas literales.

    Degradacion deliberada (FR-009/FR-012, research.md "Divergencia deliberada"):
    si el RAG no esta disponible o no hay resultados, `items` queda vacio con
    `causa` y warning; no es un error de la tool.
    """

    items: list[ItemEvidenciaNormativa]
    consulta: str
    consulta_automatica: bool
    sin_resultados: bool
    causa: Literal["CORPUS_NO_INGESTADO", "OLLAMA_NO_DISPONIBLE", "SIN_RESULTADOS"] | None = None
    source_trace: SourceTrace


class Warning(BaseModel):
    """Advertencia determinista del reporte (una entrada por degradacion, deduplicada)."""

    codigo: Literal[
        "LOTE_SIN_CHIP",
        "UPL_NO_ENCONTRADA",
        "LOCALIDAD_NO_DERIVADA",
        "BLOQUE_SIN_DATO",
        "NORMATIVA_NO_DISPONIBLE",
        "NORMATIVA_SIN_RESULTADOS",
        "BLOQUE_DEGRADADO",
    ]
    mensaje: str


class InformeFactibilidad(BaseModel):
    """Entidad raiz del contrato get_feasibility_report: los 15 bloques.

    `query_timestamp` es ISO 8601 UTC de generacion del reporte; no participa
    del score (SC-003: el score es deterministico).
    """

    lot_identity: IdentidadLote
    administrative_context: ContextoAdministrativo
    planning_constraints: BloqueReservaVial
    market_context: BloqueValorReferencia
    environment_context: BloqueObrasPublicas
    economic_context: BloqueDestinoEconomico
    geotechnical_risks: BloqueRiesgosGeotecnicos
    socioeconomic_context: BloqueContextoSocioeconomico
    regulatory_environment: BloqueEntornoRegulatorio
    cultural_heritage: BloquePatrimonioCultural
    transit_access: BloqueAccesoMovilidad
    catastro_data: BloqueCatastroData
    normative_evidence: EvidenciaNormativa
    feasibility_score: FeasibilityScore
    warnings: list[Warning]
    query_timestamp: str
