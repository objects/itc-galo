"""Provider de servicios ArcGIS REST del catastro de Bogota (T011, T017, T018).

Frontera de parsing para
https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/ (constitucion,
Principio II). Resuelve la capa Lote (Mapa_Referencia, layer 38) por punto y las
3 tematicas activas en paralelo con asyncio.gather (SC-001 < 10 s).

Criterio de consulta tematica (research.md D5, lineas 125-128):
- valorreferencia (catastro/valorreferencia): por punto/centroide.
- reservavial (ordenamientoterritorial/reservavial): por punto/centroide.
- obraspublicas (gestionpublica/obraspublicas): por punto/centroide.

NOTA destinolt (catastro/destinolt): el servicio responde 500 en vivo ("Service
catastro/destinolt/MapServer not started") y no aparece en el listado del folder
catastro, asi que se retiro del contexto tematico por defecto (Fix C). El codigo
queda listo para re-anadirlo cuando el servicio vuelva: basta con restaurar su
CapaConfig (VIGENCIAS_DEFAULT/_NOMBRES_CANONICOS/_URLS_CANONICOS/_CAPAS_CANONICOS),
la tarea _consultar_destino_economico en consultar_contexto_tematico y el campo
destino_economico de ContextoTematico (app/models.py).

Manejo de errores (FR-009, Principio IV): un 5xx (HTTP o code del body) es
Fuente5xxError y nunca "no encontrado"; un 4xx es Fuente4xxError; un payload no
utilizable es FuenteDatosInvalidosError. ArcGIS REST reporta errores con HTTP 200
+ body {"error": {code, ...}}; verificar_body_sin_error los detecta (hallazgo A2).

Utilidades compartidas (plan.md:303-312): la construccion de params por punto
(construir_params_punto), el clasificador de consulta (consultar_query) y
CapaConfig viven en arcgis_utils.py; este modulo delega en ellas para no duplicar
la semantica espacial. El refactor no cambia el comportamiento de F1 (garantia de
no-regresion de los 33 tests).

Fail-fast del contexto tematico: asyncio.gather corre SIN return_exceptions de
forma deliberada. Si una tematica falla (5xx), toda la respuesta es FUENTE_5XX y
no se "rescata" parcialmente el contexto: el shape de salida no tiene canal de
error por tematica (estado es solo disponible/no_encontrado, contrato) y mapear un
5xx a no_encontrado violaria FR-009. En el caso normal (ausencia de dato), cada
tematica reporta no_encontrado por separado (FR-007).

Bloques multifuente F6/F7 (riesgos, socioeconomico, regulatorio, patrimonio,
movilidad, catastro): cada capa SI reporta sus fallos tipados. asyncio.gather
corre con return_exceptions pero las excepciones NUNCA se tragan: se convierten
en FalloCapa (fuente + causa legible) y viajan en el tercer elemento de la tupla
de retorno para que el limite emita el warning BLOQUE_DEGRADADO con la causa real
(FR-009). Un fallo de capa jamas se maquilla como "no encontrado" silencioso.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Coroutine, Sequence
from typing import Any, Literal

import httpx
from pydantic import BaseModel

# Helpers compartidos (hallazgo m7): unica definicion en app/utilidades.py.
from app.utilidades import (
    PATRON_CHIP,
    ahora_iso as _ahora_iso,
    extraer_numero as _extraer_numero,
    primer_texto as _primer_texto,
    primer_valor as _primer_valor,
)

from app.errores import (
    Fuente4xxError,
    Fuente5xxError,
    FuenteDatosInvalidosError,
)
from app.models import (
    AccesoMovilidad,
    ContextoCatastro,
    ContextoTematico,
    ContextoSocioeconomico,
    DestinoEconomico,
    EntornoRegulatorio,
    EquipamientoCercano,
    EquipamientosCercanos,
    EspacioPublicoLote,
    ObraPublica,
    PatrimonioCultural,
    RedVialLote,
    ReservaVial,
    RiesgoGeotecnicos,
    SourceTrace,
    UsoEconomico,
    ValorReferencia,
    ViaFrenteLote,
)
from app.providers.arcgis_utils import (
    RAIZ_ARCGIS,
    CapaConfig,
    construir_params_punto,
    consultar_query,
)

# Vigencias declaradas por capa (research.md D5 y brief 20260809-01-perplexity.md):
# - Mapa de Referencia: ano 2019.
# - valorreferencia: datos recopilados 2012-2025.
# - destinolt (retirado, ver NOTA en el docstring): informacion 2022.
# - reservavial: actualizacion 2019-08-15.
# - obraspublicas: vigencia de publicacion del servicio (asumida, no documentada
#   en el brief; configurable via vigencias_por_tema para pruebas).
# - predio (capa tabular Predio, F3): la vigencia del dato es la del registro
#   (PREVACTUAL, research H7); este valor es solo el respaldo de CapaConfig
#   cuando el registro no la declara.
VIGENCIAS_DEFAULT: dict[str, str] = {
    "lote": "2019",
    "valorreferencia": "2012-2025",
    "reservavial": "2019-08-15",
    "obraspublicas": "2025",
    "predio": "2026",
    "geotecnia_amenaza": "2023",
    "geotecnia_geologia": "2023",
    "geotecnia_sismo": "2023",
    "geotecnia_zonificacion": "2023",
    "estratificacion": "2024",
    "usopredominante": "2024",
    "alturamedia": "2024",
    "medianaavaluo": "2024",
    "licencias": "2025",
    "plusvalia": "2024",
    "bic": "2023",
    "planarqueologico": "2023",
    "transmilenio": "2025",
    "sitp": "2025",
    "metro": "2025",
    "construccion": "2024",
    "manzana_catastro": "2024",
    "densidad_predial": "2024",
    "variacion_area": "2024",
    "sector_catastral": "2024",
    # Fase 3 (espacio publico, malla vial, equipamientos): vigencia de
    # publicacion del servicio (asumida, no declarada en la metadata), salvo
    # malla_vial que hereda el ano 2019 del Mapa de Referencia.
    "espacio_publico": "2024",
    "malla_vial": "2019",
    "facilidad_salud": "2025",
    "facilidad_educacion": "2025",
    "facilidad_cultura_ciencia": "2025",
    "facilidad_cultura_arte": "2025",
    "facilidad_cultura_historia": "2025",
}


def _configuracion_capas(vigencias_por_tema: dict[str, str] | None) -> dict[str, CapaConfig]:
    vigencias = {**VIGENCIAS_DEFAULT, **(vigencias_por_tema or {})}
    return {
        clave: CapaConfig(
            clave=clave,
            source_name=_NOMBRES_CANONICOS[clave],
            service_url=_URLS_CANONICOS[clave],
            layer_id=_CAPAS_CANONICOS[clave],
            data_vigencia=vigencias[clave],
        )
        for clave in VIGENCIAS_DEFAULT
    }


_NOMBRES_CANONICOS = {
    "lote": "Mapa_Referencia/Mapa_Referencia",
    "valorreferencia": "catastro/valorreferencia",
    "reservavial": "ordenamientoterritorial/reservavial",
    "obraspublicas": "gestionpublica/obraspublicas",
    "predio": "Predio (catastro/lote)",
    "geotecnia_amenaza": "Gestión de Riesgos — Amenaza movimientos en masa urbano",
    "geotecnia_geologia": "Gestión de Riesgos — Geología Rural",
    "geotecnia_sismo": "Gestión de Riesgos — Respuesta Sísmica",
    "geotecnia_zonificacion": "Gestión de Riesgos — Zonificación Geotécnica",
    "estratificacion": "Estratificación socioeconómica",
    "usopredominante": "Uso predominante",
    "alturamedia": "Altura media",
    "medianaavaluo": "Mediana avalúo catastral",
    "licencias": "Licencias de construcción aprobadas",
    "plusvalia": "Plusvalía — Planes parciales",
    "bic": "Bienes de Interés Cultural",
    "planarqueologico": "Plan Arqueológico",
    "transmilenio": "Transporte público — Estaciones TransMilenio",
    "sitp": "Transporte público — Paraderos SITP",
    "metro": "Metro Bogotá",
    "construccion": "Catastro — Construcción",
    "manzana_catastro": "Catastro — Manzana",
    "densidad_predial": "Catastro — Densidad Predial",
    "variacion_area": "Catastro — Variación Área Construida",
    "sector_catastral": "Catastro — Sector Catastral",
    "espacio_publico": "Indicadores de Espacio Público — Total por UPL",
    "malla_vial": "Mapa de Referencia — Malla Vial",
    "facilidad_salud": "Salud — IPS con Servicio de Vacunación",
    "facilidad_educacion": "Educación — Colegios",
    "facilidad_cultura_ciencia": "Cultura — Equipamientos culturales (Ciencia)",
    "facilidad_cultura_arte": "Cultura — Equipamientos culturales (Arte)",
    "facilidad_cultura_historia": "Cultura — Equipamientos culturales (Historia)",
}

_URLS_CANONICOS = {
    "lote": f"{RAIZ_ARCGIS}/Mapa_Referencia/Mapa_Referencia/MapServer",
    "valorreferencia": f"{RAIZ_ARCGIS}/catastro/valorreferencia/MapServer",
    "reservavial": f"{RAIZ_ARCGIS}/ordenamientoterritorial/reservavial/MapServer",
    "obraspublicas": f"{RAIZ_ARCGIS}/gestionpublica/obraspublicas/MapServer",
    "predio": f"{RAIZ_ARCGIS}/catastro/lote/MapServer",
    "geotecnia_amenaza": f"{RAIZ_ARCGIS}/emergencias/gestionriesgos/MapServer",
    "geotecnia_geologia": f"{RAIZ_ARCGIS}/emergencias/gestionriesgos/MapServer",
    "geotecnia_sismo": f"{RAIZ_ARCGIS}/emergencias/gestionriesgos/MapServer",
    "geotecnia_zonificacion": f"{RAIZ_ARCGIS}/emergencias/gestionriesgos/MapServer",
    "estratificacion": f"{RAIZ_ARCGIS}/ordenamientoterritorial/estratificacion/MapServer",
    "usopredominante": f"{RAIZ_ARCGIS}/catastro/usopredominante/MapServer",
    "alturamedia": f"{RAIZ_ARCGIS}/catastro/alturamedia/MapServer",
    "medianaavaluo": f"{RAIZ_ARCGIS}/catastro/medianaavaluocatastral/MapServer",
    "licencias": f"{RAIZ_ARCGIS}/ordenamientoterritorial/licenciasconstruccion/MapServer",
    "plusvalia": f"{RAIZ_ARCGIS}/ordenamientoterritorial/plusvalia/MapServer",
    "bic": f"{RAIZ_ARCGIS}/recreaciondeporte/bienesinterescultural/MapServer",
    "planarqueologico": f"{RAIZ_ARCGIS}/recreaciondeporte/planarqueologico/MapServer",
    "transmilenio": f"{RAIZ_ARCGIS}/movilidad/transportepublico/MapServer",
    "sitp": f"{RAIZ_ARCGIS}/movilidad/transportepublico/MapServer",
    "metro": f"{RAIZ_ARCGIS}/movilidad/metrobogota/MapServer",
    "construccion": f"{RAIZ_ARCGIS}/catastro/construccion/MapServer",
    "manzana_catastro": f"{RAIZ_ARCGIS}/catastro/manzana/MapServer",
    "densidad_predial": f"{RAIZ_ARCGIS}/catastro/densidadpredialmz/MapServer",
    "variacion_area": f"{RAIZ_ARCGIS}/catastro/variacionareaconstruida/MapServer",
    "sector_catastral": f"{RAIZ_ARCGIS}/catastro/sectorcatastral/MapServer",
    "espacio_publico": f"{RAIZ_ARCGIS}/espaciopublico/indicadorespaciopublico/MapServer",
    "malla_vial": f"{RAIZ_ARCGIS}/Mapa_Referencia/Mapa_Referencia/MapServer",
    "facilidad_salud": f"{RAIZ_ARCGIS}/salud/serviciosips/MapServer",
    "facilidad_educacion": f"{RAIZ_ARCGIS}/educacion/infraestructuraeducativa/MapServer",
    "facilidad_cultura_ciencia": f"{RAIZ_ARCGIS}/recreaciondeporte/equipamientocultural/MapServer",
    "facilidad_cultura_arte": f"{RAIZ_ARCGIS}/recreaciondeporte/equipamientocultural/MapServer",
    "facilidad_cultura_historia": f"{RAIZ_ARCGIS}/recreaciondeporte/equipamientocultural/MapServer",
}

_CAPAS_CANONICOS = {
    "lote": "38",
    "valorreferencia": "0",
    # reservavial usa el layer 2: el layer 1 es un Group Layer y la capa
    # consultable es el Feature Layer 2 (hallazgo vivo, Fix C).
    "reservavial": "2",
    "obraspublicas": "0",
    "predio": "3",
    "geotecnia_amenaza": "2",
    "geotecnia_geologia": "5",
    "geotecnia_sismo": "7",
    "geotecnia_zonificacion": "8",
    "estratificacion": "1",
    "usopredominante": "0",
    "alturamedia": "0",
    "medianaavaluo": "0",
    "licencias": "3",
    "plusvalia": "1",
    "bic": "1",
    "planarqueologico": "9",
    "transmilenio": "1",
    "sitp": "5",
    "metro": "0",
    "construccion": "0",
    "manzana_catastro": "0",
    "densidad_predial": "0",
    "variacion_area": "1",
    "sector_catastral": "0",
    # Fase 3: layer 8 = "Total por UPL" (poligonos con EPT m2/hab); layer 13 =
    # "Malla Vial" (ejes polyline del Mapa de Referencia); IPS de vacunacion
    # (layer 7) y colegios oficiales (layer 0); equipamiento cultural por
    # categoria (layers 1-3). El layer 6 "Museos" responde 400 en vivo y se
    # excluye (limitacion documentada en AGENTS.md).
    "espacio_publico": "8",
    "malla_vial": "13",
    "facilidad_salud": "7",
    "facilidad_educacion": "0",
    "facilidad_cultura_ciencia": "1",
    "facilidad_cultura_arte": "2",
    "facilidad_cultura_historia": "3",
}

# --- Dominios versionados de la capa Predio (catastro/lote/MapServer/3) ---
# Tablas estaticas D_PreDestino (PRECDESTIN, 28 codigos) y D_UsoTUso (PRECUSO,
# 85 codigos) extraidas de la metadata viva `?f=pjson` de la capa el 2026-08-12
# (research H1; dataset "Uso. Bogota D.C" de Datos Abiertos como respaldo, H8).
# Se versionan como constantes del provider (patron del mapeo NOMBRE -> localidad
# de F2) para traducir codigos sin consultar la metadata en runtime. Si un codigo
# no aparece (dominio actualizado), el fallback es el codigo crudo como
# descripcion (research H1 "Implicacion").

D_PREDESTINO: dict[str, str] = {
    "01": "Residencial",
    "03": "Industrial",
    "04": "Dotacional público",
    "05": "Recreacional público",
    "06": "Dotacional privado",
    "07": "Minero",
    "08": "Recreacional privado",
    "21": "Comercio en corredor comercial",
    "22": "Comercio en centros comerciales",
    "23": "Comercio puntual",
    "24": "Parqueaderos",
    "61": "Urbanizado no edificado",
    "62": "Urbanizable no urbanizado",
    "63": "No urbanizables y suelo protegido",
    "64": "Urbanizado no edificado propiedad del Estado",
    "65": "Vías",
    "66": "Espacio público",
    "67": "Predios con mejoras ajenas",
    "68": "Servidumbre Predial",
    "81": "Agropecuarios",
    "82": "Otros",
    "83": "Agrícola",
    "84": "Pecuario",
    "85": "Forestal",
    "86": "Agroindustrial",
    "87": "Agroforestal",
    "88": "Tierras improductivas",
    "89": "Predio rural con parcela no edificada",
}

D_USOTUSO: dict[str, str] = {
    "000": "Sin Uso",
    "001": "Habitacional menor o igual a 3 pisos en NPH",
    "002": "Habitacional mayor o igual a 4 pisos en NPH",
    "003": "Comercio Puntual en NPH",
    "004": "Corredor Comercial en NPH",
    "005": "Estaciones de servicio",
    "006": "Centro Comercial  Mediano  NPH",
    "007": "Centro Comercial  Grande NPH",
    "008": "Bodega comercial NPH",
    "009": "Industria artesanal",
    "010": "Industria Mediana",
    "011": "Industria Grande",
    "012": "Institucional Puntual",
    "013": "Colegios y Universidades de 1 a 3 pisos",
    "014": "Iglesias",
    "015": "Oficinas y Consultorios oficiales en NPH",
    "016": "Colegios y Universidades de 4 pisos o mas",
    "017": "Clinicas Hospitales Centro Medicos",
    "018": "Instalaciones Militares",
    "019": "Industria artesanal en PH",
    "020": "Oficinas y Consultorios en NPH",
    "021": "Hoteles en NPH",
    "022": "Depositos de Almacenamiento en NPH",
    "023": "Teatros y Cinemas en NPH",
    "024": "Edificio de Parqueo en NPH",
    "025": "Bodega de Almacenamiento en NPH",
    "026": "Moteles Amoblado y Residencias en NPH",
    "027": "Moteles Amoblado y Residencias en PH",
    "028": "Industria Mediana en PH",
    "029": "Parques de Diversion en NPH",
    "030": "Clubes de Mayor Extension",
    "031": "Piscinas en NPH",
    "032": "Coliseos",
    "033": "Bodega Economica",
    "034": "Industria Grande en PH",
    "035": "Colegios y Universidades de 1 a 3 pisos en PH",
    "036": "Parques de Diversion en PH",
    "037": "Habitacional menor o igual a 3 pisos en PH",
    "038": "Habitacional mayor o igual a 4 pisos en PH",
    "039": "Comercio Puntual en PH",
    "040": "Corredor Comercial en PH",
    "041": "Centro Comercial  Mediano en PH",
    "042": "Centro Comercial  Grande en PH",
    "043": "Clinicas Hospitales Centro Medicos en PH",
    "044": "Institucional Puntual en PH",
    "045": "Oficinas y Consultorios en PH",
    "046": "Hoteles en PH",
    "047": "Teatros y Cinemas en PH",
    "048": "Parqueo libre en PH",
    "049": "Parqueadero Cubierto en PH",
    "050": "Edificio de Parqueo en PH",
    "051": "Deposito Lockers en PH",
    "052": "Piscinas en PH",
    "053": "Iglesias en PH",
    "055": "Cementerios",
    "056": "Restaurantes en NPH",
    "057": "Área de Mezanine en PH",
    "058": "Culto Religioso en NPH",
    "059": "Culto Religioso en PH",
    "060": "Restaurantes en PH",
    "062": "Pista Aeropuerto",
    "064": "Aulas de Clases",
    "065": "Clubes Pequeños",
    "066": "Plazas de Mercado",
    "067": "Museos",
    "070": "Enrramadas Cobertizos Cayenes",
    "071": "Galpones Gallineros",
    "072": "Establos Pesebreras Caballerizas",
    "073": "Cocheras Marraneras Porquerizas",
    "074": "Beneficiadores",
    "075": "Secadores",
    "076": "Kioscos",
    "077": "Silos",
    "080": "Oficinas en Bodegas y/o Industrias en NPH",
    "081": "Oficinas en Bodegas y/o Industrias en PH",
    "082": "Oficinas operativas (estaciones de servicio)",
    "090": "Predios sin construir en PH",
    "091": "Bodega comercial en PH",
    "092": "Oficinas y Consultorios oficiales en PH",
    "093": "Bodega de Almacenamiento en PH",
    "094": "Centro Comercial Pequeño en NPH",
    "095": "Centro Comercial Pequeño en PH",
    "096": "Parqueadero Cubierto en NPH",
    "097": "Bodega Economica en PH",
    "098": "Deposito de Almacenamiento en PH",
}


class FalloCapa(BaseModel):
    """Fallo tipado de una capa dentro de un bloque multifuente (FR-009).

    Un 5xx/4xx/payload invalido de una capa NUNCA se reporta como "no
    encontrado": queda registrado aqui (fuente + causa legible) para que el
    limite construya el warning BLOQUE_DEGRADADO con la causa real.
    """

    source_name: str
    detalle: str


def _detalle_de_fallo(exc: BaseException) -> str:
    """Causa legible y determinista de un error tipado del provider (FR-009)."""
    if isinstance(exc, Fuente5xxError):
        return f"la fuente no está disponible (error {exc.status})"
    if isinstance(exc, Fuente4xxError):
        return f"la fuente rechazó la consulta (error {exc.status})"
    if isinstance(exc, FuenteDatosInvalidosError):
        return f"la fuente devolvió datos no válidos ({exc.detail})"
    return "error inesperado al consultar la fuente"


async def _gather_con_fallos(
    tareas_por_capa: Sequence[tuple[CapaConfig, Coroutine[Any, Any, dict[str, Any]]]],
) -> tuple[list[Any], list[FalloCapa]]:
    """Ejecuta las consultas de un bloque multifuente separando exitos de fallos.

    Los errores tipados de cada capa (FR-009) NO se tragan: quedan en `fallos`
    con su causa para que el limite emita el warning BLOQUE_DEGRADADO. Solo los
    resultados exitosos llegan al parsing del bloque.
    """
    resultados = await asyncio.gather(
        *(tarea for _, tarea in tareas_por_capa), return_exceptions=True
    )
    fallos = [
        FalloCapa(source_name=capa.source_name, detalle=_detalle_de_fallo(resultado))
        for (capa, _), resultado in zip(tareas_por_capa, resultados)
        if isinstance(resultado, BaseException)
    ]
    return list(resultados), fallos


def _traza_de_resultado(capa: CapaConfig, resultado: dict[str, Any]) -> SourceTrace:
    """Traza de una capa consultada EXITOSAMENTE (hallazgo M4).

    La vigencia es la que declara el primer feature de la propia capa (ANIO/
    VIGENCIA) o, si no lo declara, la vigencia documentada de CapaConfig: cada
    sub-fuente publica su propia vigencia, nunca la de otra capa.
    """
    features = resultado.get("features") or []
    if features:
        vigencia = _vigencia_del_feature(features[0].get("properties") or {})
        if vigencia:
            return _construir_trace(capa, data_vigencia=vigencia)
    return _construir_trace(capa)


def _trazas_de_bloque(
    tareas_por_capa: Sequence[tuple[CapaConfig, Coroutine[Any, Any, dict[str, Any]]]],
    resultados: list[Any],
) -> tuple[SourceTrace, list[SourceTrace]]:
    """Trazas por sub-fuente de un bloque multifuente (hallazgo M4).

    Retorna (traza_principal, trazas_subfuente):
    - `trazas_subfuente`: una entrada por capa consultada EXITOSAMENTE, en el
      orden de declaracion de las capas del bloque, con su vigencia propia. Las
      capas caidas NO generan traza aqui: su fallo viaja tipado en FalloCapa
      (FR-009); jamas se fabrica una traza para una capa que no respondio.
    - `traza_principal`: la primera capa exitosa o, si TODAS fallaron, la traza
      declarada de la primera capa del bloque (el contrato exige source_trace
      siempre poblado; comportamiento respaldado por el test M2).
    """
    trazas = [
        _traza_de_resultado(capa, resultado)
        for (capa, _), resultado in zip(tareas_por_capa, resultados)
        if not isinstance(resultado, BaseException)
    ]
    traza_principal = trazas[0] if trazas else _construir_trace(tareas_por_capa[0][0])
    return traza_principal, trazas


class LoteArcgis(BaseModel):
    """Lote parseado de la capa 38 del Mapa de Referencia (identity + geometria)."""

    codigo_catastral: str
    manzana: str
    chip: str | None = None
    direccion_normalizada: str | None = None
    barrio: str | None = None
    geometry: dict[str, Any]
    source_trace: SourceTrace


class ArcGISProvider:
    """Cliente httpx async para los servicios ArcGIS REST del catastro de Bogota."""

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        vigencias_por_tema: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._client = httpx.AsyncClient(base_url=RAIZ_ARCGIS, transport=transport, timeout=timeout)
        self._capas = _configuracion_capas(vigencias_por_tema)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def consultar_lotes_por_punto(self, lng: float, lat: float) -> list[LoteArcgis]:
        """Consulta la capa Lote (layer 38) con un punto (lng, lat) en WGS84.

        Devuelve los lotes que intersecan el punto (0, 1 o varios). La decision
        de lote unico / limite / fuera de cobertura la toma el limite de la tool.
        """
        capa = self._capas["lote"]
        params = {
            "f": "geojson",
            "geometry": f"{lng},{lat}",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outSR": "4326",
            "returnGeometry": "true",
            "outFields": "*",
        }
        data = await self._consultar(capa, params)
        return self._parsear_lotes(data)

    async def consultar_contexto_tematico(self, lng: float, lat: float) -> ContextoTematico:
        """Ejecuta las 3 consultas tematicas activas en paralelo (SC-001 < 10 s).

        destinolt (catastro/destinolt) se retiro del contexto por defecto: el
        servicio responde 500 en vivo (ver NOTA en el docstring del modulo).

        Fail-fast deliberado: asyncio.gather sin return_exceptions. Un 5xx de una
        tematica falla toda la respuesta (FUENTE_5XX en el limite de la tool); no
        se rescata parcialmente porque el contrato no tiene canal de error por
        tematica y mapear un 5xx a no_encontrado violaria FR-009 (ver docstring
        del modulo, decision A2 punto 11).
        """
        tareas = [
            self._consultar_valor_referencia(lng, lat),
            self._consultar_reserva_vial(lng, lat),
            self._consultar_obras_publicas(lng, lat),
        ]
        valor, reserva, obras = await asyncio.gather(*tareas)
        return ContextoTematico(
            valor_referencia=valor,
            reserva_vial=reserva,
            obras_publicas=obras,
        )

    async def consultar_destino_economico(
        self,
        chip: str | None = None,
        codigo_catastral: str | None = None,
    ) -> DestinoEconomico:
        """Consulta la capa tabular Predio (catastro/lote/MapServer/3, f=pjson).

        La capa es tabular (sin SHAPE): f=geojson responde 400, por lo que la
        consulta usa f=pjson con returnGeometry=false (research H1). El join es
        por PRECHIP cuando el lote tiene CHIP (mas preciso, research H2); si esa
        consulta no devuelve filas y se tiene `codigo_catastral`, se intenta
        BARMANPRE='<codigo>' (LOTCODIGO == BARMANPRE, comprobado en vivo).

        La fila con mayor PREAUSO define el destino principal
        (`codigo_destino`/`descripcion_destino`/`uso`/`area_uso`); las demas
        filas se listan en `usos` (research H3). Sin filas -> estado
        no_encontrado (nunca un dato inventado, FR-014). `data_vigencia` =
        PREVACTUAL de la fila dominante (research H7).
        """
        if chip is None and codigo_catastral is None:
            raise ValueError("consultar_destino_economico requiere chip o codigo_catastral")
        if chip is not None and not PATRON_CHIP.fullmatch(chip):
            raise ValueError("el chip debe tener 11 caracteres alfanuméricos")
        if codigo_catastral is not None and not re.fullmatch(r"[A-Za-z0-9]+", codigo_catastral):
            raise ValueError("el codigo_catastral contiene caracteres no alfanuméricos")

        capa = self._capas["predio"]
        if chip is not None:
            destino = await self._consultar_predio_por_where(capa, f"PRECHIP='{chip}'")
            if destino.estado == "disponible" or codigo_catastral is None:
                return destino
        return await self._consultar_predio_por_where(capa, f"BARMANPRE='{codigo_catastral}'")

    async def consultar_obras_publicas_radio(
        self, lng: float, lat: float, radio_m: int = 500
    ) -> ObraPublica:
        """Consulta obras publicas en un radio alrededor del punto (FR-004).

        La capa gestionpublica/obraspublicas/0 es multipunto (research H5): la
        consulta puntual de F1 (interseccion sin distancia) casi nunca devuelve
        features. Esta consulta anade `distance=<radio_m>&units=esriSRUnit_Meter`
        sobre el centroide del lote; por defecto radio de 500 m (FR-004). NO
        modifica `_consultar_obras_publicas` de F1 (CHK-015).
        """
        if radio_m is None or radio_m <= 0:
            raise ValueError("radio_m debe ser un valor positivo en metros")
        capa = self._capas["obraspublicas"]
        params = {
            "f": "geojson",
            "geometry": f"{lng},{lat}",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "distance": str(radio_m),
            "units": "esriSRUnit_Meter",
            "outSR": "4326",
            "returnGeometry": "false",
            "outFields": "*",
        }
        data = await self._consultar(capa, params)
        features = data.get("features") or []
        obras = []
        for feature in features:
            propiedades = feature.get("properties") or {}
            obra = {
                "nombre": _primer_texto(propiedades, ["NOMBRE", "OBRA", "NOMBRE_OBRA"]),
                "descripcion": _primer_texto(
                    propiedades, ["DESCRIPCION", "DESCRIPCION_OBRA", "OBJETO"]
                ),
            }
            if obra["nombre"] or obra["descripcion"]:
                obras.append(obra)
        if not obras:
            return ObraPublica(estado="no_encontrado", source_trace=_construir_trace(capa))
        vigencia = _vigencia_del_feature(features[0].get("properties") or {}) or capa.data_vigencia
        return ObraPublica(
            estado="disponible",
            obras=obras,
            vigencia=vigencia,
            source_trace=_construir_trace(capa, data_vigencia=vigencia),
        )

    async def _consultar_predio_por_where(
        self, capa: CapaConfig, where: str
    ) -> DestinoEconomico:
        """Consulta la capa Predio por atributo y construye el DestinoEconomico.

        Frontera de parsing de la capa Predio (research D5): el formato es
        pjson (`features[].attributes`), nunca geojson (H1). La fila dominante
        es la de mayor PREAUSO (H3); sin filas -> no_encontrado.
        """
        params = {
            "f": "pjson",
            "where": where,
            "returnGeometry": "false",
            "outFields": "*",
        }
        data = await self._consultar(capa, params)
        filas = _parsear_filas_predio(data)
        if not filas:
            return DestinoEconomico(estado="no_encontrado", source_trace=_construir_trace(capa))

        fila_dominante = max(filas, key=lambda fila: _extraer_numero(fila, ["PREAUSO"]) or 0.0)
        codigo_destino = _primer_texto(fila_dominante, ["PRECDESTIN"])
        codigo_uso = _primer_texto(fila_dominante, ["PRECUSO"])
        descripcion_uso = _traducir_dominio(D_USOTUSO, codigo_uso)
        vigencia = _primer_texto(fila_dominante, ["PREVACTUAL"]) or capa.data_vigencia

        return DestinoEconomico(
            estado="disponible",
            codigo_destino=codigo_destino,
            descripcion_destino=_traducir_dominio(D_PREDESTINO, codigo_destino),
            uso=f"{codigo_uso} - {descripcion_uso}" if codigo_uso else None,
            area_uso=_extraer_numero(fila_dominante, ["PREAUSO"]),
            usos=[
                UsoEconomico(
                    codigo=_primer_texto(fila, ["PRECUSO"]) or "",
                    descripcion=_traducir_dominio(D_USOTUSO, _primer_texto(fila, ["PRECUSO"])),
                    area_uso=_extraer_numero(fila, ["PREAUSO"]) or 0.0,
                )
                for fila in filas
            ],
            area_terreno=_extraer_numero(fila_dominante, ["PREATERRE"]),
            area_construccion=_extraer_numero(fila_dominante, ["PREACONST"]),
            direccion=_primer_texto(fila_dominante, ["PREDIRECC"]),
            barrio=_primer_texto(fila_dominante, ["PRENBARRIO"]),
            vigencia=vigencia,
            source_trace=_construir_trace(capa, data_vigencia=vigencia),
        )

    async def _consultar_valor_referencia(self, lng: float, lat: float) -> ValorReferencia:
        capa = self._capas["valorreferencia"]
        data = await self._consultar(capa, self._params_punto(lng, lat))
        features = data.get("features") or []
        if not features:
            return ValorReferencia(estado="no_encontrado", source_trace=_construir_trace(capa))
        propiedades = features[0].get("properties") or {}
        vigencia = _vigencia_del_feature(propiedades) or capa.data_vigencia
        return ValorReferencia(
            estado="disponible",
            valor_m2=_extraer_numero(
                propiedades,
                ["VALOR_M2", "VALOR_M2_REFERENCIA", "VRM", "VALOR", "VLRM2", "V_REF"],
            ),
            unidad_monetaria="COP",
            vigencia=vigencia,
            source_trace=_construir_trace(capa, data_vigencia=vigencia),
        )

    async def _consultar_reserva_vial(self, lng: float, lat: float) -> ReservaVial:
        capa = self._capas["reservavial"]
        data = await self._consultar(capa, self._params_punto(lng, lat))
        features = data.get("features") or []
        if not features:
            return ReservaVial(estado="no_encontrado", source_trace=_construir_trace(capa))
        propiedades = features[0].get("properties") or {}
        vigencia = _vigencia_del_feature(propiedades) or capa.data_vigencia
        return ReservaVial(
            estado="disponible",
            afecta_lote=True,
            descripcion=_primer_texto(propiedades, ["DESCRIPCION", "NOMBRE", "TIPO"]),
            vigencia=vigencia,
            source_trace=_construir_trace(capa, data_vigencia=vigencia),
        )

    async def _consultar_obras_publicas(self, lng: float, lat: float) -> ObraPublica:
        capa = self._capas["obraspublicas"]
        data = await self._consultar(capa, self._params_punto(lng, lat))
        features = data.get("features") or []
        obras = []
        for feature in features:
            propiedades = feature.get("properties") or {}
            obra = {
                "nombre": _primer_texto(propiedades, ["NOMBRE", "OBRA", "NOMBRE_OBRA"]),
                "descripcion": _primer_texto(
                    propiedades, ["DESCRIPCION", "DESCRIPCION_OBRA", "OBJETO"]
                ),
            }
            if obra["nombre"] or obra["descripcion"]:
                obras.append(obra)
        if not obras:
            return ObraPublica(estado="no_encontrado", source_trace=_construir_trace(capa))
        vigencia = _vigencia_del_feature(features[0].get("properties") or {}) or capa.data_vigencia
        return ObraPublica(
            estado="disponible",
            obras=obras,
            vigencia=vigencia,
            source_trace=_construir_trace(capa, data_vigencia=vigencia),
        )

    # --- Feature 6: Consultas de los 5 nuevos bloques del informe de factibilidad ---

    async def consultar_riesgos_geotecnicos(
        self, lng: float, lat: float
    ) -> tuple[RiesgoGeotecnicos, SourceTrace, list[SourceTrace], list[FalloCapa]]:
        """Consulta 4 capas de gestionriesgos en paralelo: amenaza, geologia, sismo, zonificacion.

        Retorna la tupla (riesgos, source_trace, source_traces, fallos) con la
        clasificacion dominante de cada capa, el nivel de amenaza mas critico
        encontrado, la trazabilidad por sub-fuente (hallazgo M4: una traza por
        capa exitosa con su vigencia propia) y los fallos tipados por capa
        (FR-009): una capa caida queda en `fallos` con su causa y jamas se
        confunde con "sin dato" ni genera una traza fabricada.
        """
        claves = [
            ("geotecnia_amenaza", "amenaza_movimientos"),
            ("geotecnia_geologia", "geologia"),
            ("geotecnia_sismo", "respuesta_sismica"),
            ("geotecnia_zonificacion", "zonificacion_geotecnica"),
        ]
        tareas = [
            (self._capas[clave], self._consultar_feature_punto(self._capas[clave], lng, lat))
            for clave, _ in claves
        ]
        resultados, fallos = await _gather_con_fallos(tareas)
        traza_principal, trazas_subfuente = _trazas_de_bloque(tareas, resultados)

        campos: dict[str, str | None] = {}
        for (_, campo), resultado in zip(claves, resultados):
            if isinstance(resultado, BaseException):
                campos[campo] = None
            else:
                features = resultado.get("features") or []
                campos[campo] = (
                    _primer_texto(
                        features[0].get("properties") or {},
                        ["GEOTECNIA", "NOMBRE", "TIPO", "DESCRIPCION"],
                    )
                    if features
                    else None
                )

        nivel = _inferir_nivel_amenaza(campos.get("amenaza_movimientos"))
        return (
            RiesgoGeotecnicos(
                amenaza_movimientos=campos.get("amenaza_movimientos"),
                geologia=campos.get("geologia"),
                respuesta_sismica=campos.get("respuesta_sismica"),
                zonificacion_geotecnica=campos.get("zonificacion_geotecnica"),
                nivel_amenaza=nivel,
            ),
            traza_principal,
            trazas_subfuente,
            fallos,
        )

    async def consultar_contexto_socioeconomico(
        self, lng: float, lat: float
    ) -> tuple[ContextoSocioeconomico, SourceTrace, list[SourceTrace], list[FalloCapa]]:
        """Consulta 4 capas socioeconomicas en paralelo: estratificacion, uso, altura, avaluo.

        Retorna la tupla (contexto, source_trace, source_traces, fallos) con la
        trazabilidad por sub-fuente (hallazgo M4: una traza por capa exitosa con
        su vigencia propia) y los fallos tipados por capa (FR-009).
        """
        claves = ["estratificacion", "usopredominante", "alturamedia", "medianaavaluo"]
        tareas = [
            (self._capas[clave], self._consultar_feature_punto(self._capas[clave], lng, lat))
            for clave in claves
        ]
        resultados, fallos = await _gather_con_fallos(tareas)
        traza_principal, trazas_subfuente = _trazas_de_bloque(tareas, resultados)

        estrato: int | None = None
        uso: str | None = None
        altura: float | None = None
        avaluo: float | None = None

        # Estratificacion (layer 1, SR PCS_CarMAGBOG)
        r_estrat = resultados[0]
        if not isinstance(r_estrat, BaseException):
            features = r_estrat.get("features") or []
            if features:
                propiedades = features[0].get("properties") or {}
                estrato = _extraer_numero(propiedades, ["ESTRATO", "ESTRATA", "ESTRAT"])
                if estrato is not None:
                    estrato = int(estrato)

        # Uso predominante
        r_uso = resultados[1]
        if not isinstance(r_uso, BaseException):
            features = r_uso.get("features") or []
            if features:
                propiedades = features[0].get("properties") or {}
                uso = _primer_texto(propiedades, ["GRUPOUSOECON", "USO", "GRUPO"])

        # Altura media
        r_altura = resultados[2]
        if not isinstance(r_altura, BaseException):
            features = r_altura.get("features") or []
            if features:
                propiedades = features[0].get("properties") or {}
                altura = _extraer_numero(propiedades, ["ALTURA", "ALTURAMEDIA", "PISOS"])

        # Mediana avaluo
        r_avaluo = resultados[3]
        if not isinstance(r_avaluo, BaseException):
            features = r_avaluo.get("features") or []
            if features:
                propiedades = features[0].get("properties") or {}
                avaluo = _extraer_numero(
                    propiedades, ["MED_VALOR_CATAS", "VALOR", "AVALUO"]
                )

        return (
            ContextoSocioeconomico(
                estrato=estrato,
                uso_predominante=uso,
                altura_media=altura,
                mediana_avaluo=avaluo,
            ),
            traza_principal,
            trazas_subfuente,
            fallos,
        )

    async def consultar_entorno_regulatorio(
        self, lng: float, lat: float
    ) -> tuple[EntornoRegulatorio, SourceTrace, list[SourceTrace], list[FalloCapa]]:
        """Consulta 2 capas regulatorias en paralelo: licencias y plusvalia.

        Retorna la tupla (entorno, source_trace, source_traces, fallos) con la
        trazabilidad por sub-fuente (hallazgo M4) y los fallos tipados por capa
        (FR-009).
        """
        claves = ["licencias", "plusvalia"]
        tareas = [
            (self._capas[clave], self._consultar_feature_punto(self._capas[clave], lng, lat))
            for clave in claves
        ]
        resultados, fallos = await _gather_con_fallos(tareas)
        traza_principal, trazas_subfuente = _trazas_de_bloque(tareas, resultados)

        licencias_count: int | None = None
        zona_plusvalia: bool | None = None
        nombre_plan: str | None = None

        # Licencias
        r_licencias = resultados[0]
        if not isinstance(r_licencias, BaseException):
            features = r_licencias.get("features") or []
            if features:
                licencias_count = len(features)

        # Plusvalia
        r_plusvalia = resultados[1]
        if not isinstance(r_plusvalia, BaseException):
            features = r_plusvalia.get("features") or []
            if features:
                zona_plusvalia = True
                propiedades = features[0].get("properties") or {}
                nombre_plan = _primer_texto(
                    propiedades, ["NOMBRE", "CODIGO_PLAN_PARCIAL", "NOMBRE_PLAN"]
                )

        return (
            EntornoRegulatorio(
                licencias_encontradas=licencias_count,
                zona_plusvalia=zona_plusvalia,
                nombre_plan_plusvalia=nombre_plan,
            ),
            traza_principal,
            trazas_subfuente,
            fallos,
        )

    async def consultar_patrimonio_cultural(
        self, lng: float, lat: float
    ) -> tuple[PatrimonioCultural, SourceTrace, list[SourceTrace], list[FalloCapa]]:
        """Consulta 2 capas de patrimonio cultural en paralelo: BIC y plan arqueologico.

        Retorna la tupla (patrimonio, source_trace, source_traces, fallos) con
        la trazabilidad por sub-fuente (hallazgo M4) y los fallos tipados por
        capa (FR-009).
        """
        claves = ["bic", "planarqueologico"]
        tareas = [
            (self._capas[clave], self._consultar_feature_punto(self._capas[clave], lng, lat))
            for clave in claves
        ]
        resultados, fallos = await _gather_con_fallos(tareas)
        traza_principal, trazas_subfuente = _trazas_de_bloque(tareas, resultados)

        bic_cercano: bool | None = None
        nombre_bic: str | None = None
        zona_arqueologica: bool | None = None

        # BIC
        r_bic = resultados[0]
        if not isinstance(r_bic, BaseException):
            features = r_bic.get("features") or []
            if features:
                bic_cercano = True
                propiedades = features[0].get("properties") or {}
                nombre_bic = _primer_texto(propiedades, ["NOMBRE", "CATEGORIA", "DENOMINACION"])

        # Plan arqueologico
        r_arq = resultados[1]
        if not isinstance(r_arq, BaseException):
            features = r_arq.get("features") or []
            if features:
                zona_arqueologica = True

        return (
            PatrimonioCultural(
                bic_cercano=bic_cercano,
                nombre_bic=nombre_bic,
                zona_arqueologica=zona_arqueologica,
            ),
            traza_principal,
            trazas_subfuente,
            fallos,
        )

    async def consultar_acceso_movilidad(
        self, lng: float, lat: float
    ) -> tuple[AccesoMovilidad, SourceTrace, list[SourceTrace], list[FalloCapa]]:
        """Consulta 3 capas de transporte publico con radio: TransMilenio, SITP, Metro.

        Usa distance + units=esriSRUnit_Meter para busqueda por proximidad
        (patron consultar_obras_publicas_radio). Retorna la tupla
        (movilidad, source_trace, source_traces, fallos) con la trazabilidad por
        sub-fuente (hallazgo M4) y los fallos tipados por capa (FR-009).
        """
        configuracion_radio = [
            ("transmilenio", 800, ["ETRNOMBRE", "NOMBRE", "ESTACION"]),
            ("sitp", 500, ["PSINOMBRE", "NOMBRE", "PARADERO"]),
            ("metro", 800, ["REFNAME", "NOMBRE", "ESTACION"]),
        ]
        tareas = [
            (
                self._capas[clave],
                self._consultar_radio(self._capas[clave], lng, lat, radio, campos),
            )
            for clave, radio, campos in configuracion_radio
        ]
        resultados, fallos = await _gather_con_fallos(tareas)
        traza_principal, trazas_subfuente = _trazas_de_bloque(tareas, resultados)

        count_tm: int | None = None
        count_sitp: int | None = None
        count_metro: int | None = None
        estacion_cercana: str | None = None

        # TransMilenio
        r_tm = resultados[0]
        if not isinstance(r_tm, BaseException):
            features = r_tm.get("features") or []
            if features:
                count_tm = len(features)
                propiedades = features[0].get("properties") or {}
                nombre_tm = _primer_texto(propiedades, ["ETRNOMBRE", "NOMBRE", "ESTACION"])
                if nombre_tm and estacion_cercana is None:
                    estacion_cercana = nombre_tm

        # SITP
        r_sitp = resultados[1]
        if not isinstance(r_sitp, BaseException):
            features = r_sitp.get("features") or []
            if features:
                count_sitp = len(features)

        # Metro
        r_metro = resultados[2]
        if not isinstance(r_metro, BaseException):
            features = r_metro.get("features") or []
            if features:
                count_metro = len(features)
                propiedades = features[0].get("properties") or {}
                nombre_metro = _primer_texto(propiedades, ["REFNAME", "NOMBRE", "ESTACION"])
                if nombre_metro and estacion_cercana is None:
                    estacion_cercana = nombre_metro

        return (
            AccesoMovilidad(
                estaciones_transmilenio=count_tm,
                paraderos_sitp=count_sitp,
                estaciones_metro=count_metro,
                estacion_cercana=estacion_cercana,
            ),
            traza_principal,
            trazas_subfuente,
            fallos,
        )

    async def consultar_contexto_catastro(
        self, lng: float, lat: float
    ) -> tuple[ContextoCatastro, SourceTrace, list[SourceTrace], list[FalloCapa]]:
        """Consulta 5 capas catastrales en paralelo: construccion, manzana, densidad, variacion, sector.

        Retorna la tupla (contexto_catastro, source_trace, source_traces,
        fallos) con la trazabilidad por sub-fuente (hallazgo M4: una traza por
        capa exitosa con su vigencia propia) y los fallos tipados por capa
        (FR-009): cada capa se degrada independientemente pero su fallo queda
        registrado, nunca silenciado.
        """
        claves = [
            "construccion",
            "manzana_catastro",
            "densidad_predial",
            "variacion_area",
            "sector_catastral",
        ]
        tareas = [
            (self._capas[clave], self._consultar_feature_punto(self._capas[clave], lng, lat))
            for clave in claves
        ]
        resultados, fallos = await _gather_con_fallos(tareas)
        traza_principal, trazas_subfuente = _trazas_de_bloque(tareas, resultados)

        construccion: dict[str, Any] | None = None
        manzana: dict[str, Any] | None = None
        densidad_predial: dict[str, Any] | None = None
        variacion_area: dict[str, Any] | None = None
        sector_catastral: str | None = None

        # Construccion (layer 0): CONCODIGO, CONNPISOS, CONALTURA, etc.
        r_construccion = resultados[0]
        if not isinstance(r_construccion, BaseException):
            features = r_construccion.get("features") or []
            if features:
                propiedades = features[0].get("properties") or {}
                construccion = {
                    "codigo": _primer_texto(propiedades, ["CONCODIGO"]),
                    "pisos": _extraer_numero(propiedades, ["CONNPISOS"]),
                    "sotanos": _extraer_numero(propiedades, ["CONNSOTANO"]),
                    "semisotanos": _extraer_numero(propiedades, ["CONTSEMIS"]),
                    "altura": _extraer_numero(propiedades, ["CONALTURA"]),
                    "elevacion_cota": _extraer_numero(propiedades, ["CONELEVACI"]),
                    "mejoras": _extraer_numero(propiedades, ["CONMEJORA"]),
                    "voladizo": _extraer_numero(propiedades, ["CONVOLADIZ"]),
                }

        # Manzana catastro (layer 0): MANCODIGO, SECCODIGO
        r_manzana = resultados[1]
        if not isinstance(r_manzana, BaseException):
            features = r_manzana.get("features") or []
            if features:
                propiedades = features[0].get("properties") or {}
                manzana = {
                    "codigo_manzana": _primer_texto(propiedades, ["MANCODIGO"]),
                    "codigo_seccion": _primer_texto(propiedades, ["SECCODIGO"]),
                }

        # Densidad predial (layer 0): MANCODIGO, N_PREDIOS, ANO
        r_densidad = resultados[2]
        if not isinstance(r_densidad, BaseException):
            features = r_densidad.get("features") or []
            if features:
                propiedades = features[0].get("properties") or {}
                densidad_predial = {
                    "codigo_manzana": _primer_texto(propiedades, ["MANCODIGO"]),
                    "num_predios": _extraer_numero(propiedades, ["N_PREDIOS"]),
                    "ano": _extraer_numero(propiedades, ["ANO"]),
                }

        # Variacion area construida (layer 1): MANCODIGO, AC_M2_MZ_INIC, AC_M2_MZ_FIN, etc.
        r_variacion = resultados[3]
        if not isinstance(r_variacion, BaseException):
            features = r_variacion.get("features") or []
            if features:
                propiedades = features[0].get("properties") or {}
                variacion_area = {
                    "codigo_manzana": _primer_texto(propiedades, ["MANCODIGO"]),
                    "area_inicial_m2": _extraer_numero(propiedades, ["AC_M2_MZ_INIC"]),
                    "area_final_m2": _extraer_numero(propiedades, ["AC_M2_MZ_FIN"]),
                    "variacion_m2": _extraer_numero(propiedades, ["VAR_M2_AC"]),
                    "variacion_porcentual": _extraer_numero(propiedades, ["PVAR_M2_AC"]),
                    "periodo": _primer_texto(propiedades, ["PERIODO"]),
                }

        # Sector catastral (layer 0): SCACODIGO, SCATIPO, SCANOMBRE
        r_sector = resultados[4]
        if not isinstance(r_sector, BaseException):
            features = r_sector.get("features") or []
            if features:
                propiedades = features[0].get("properties") or {}
                sector_catastral = _primer_texto(propiedades, ["SCANOMBRE"])

        return (
            ContextoCatastro(
                construccion=construccion,
                manzana=manzana,
                densidad_predial=densidad_predial,
                variacion_area=variacion_area,
                sector_catastral=sector_catastral,
            ),
            traza_principal,
            trazas_subfuente,
            fallos,
        )

    async def _consultar_feature_punto(
        self, capa: CapaConfig, lng: float, lat: float
    ) -> dict[str, Any]:
        """Consulta un feature por punto usando los params estandar (inSR=4326)."""
        return await self._consultar(capa, self._params_punto(lng, lat))

    # --- Fase 3: espacio publico, malla vial y equipamientos cercanos ---

    async def consultar_espacio_publico(
        self, lng: float, lat: float
    ) -> tuple[EspacioPublicoLote, SourceTrace, list[SourceTrace], list[FalloCapa]]:
        """Consulta el indicador de espacio publico de la UPL del lote (layer 8).

        Join punto-en-poligono sobre el centroide: la capa "Total por UPL"
        publica EPT (m2/hab) por UPL. Retorna la tupla uniforme de bloques
        (dato, source_trace, source_traces, fallos) para que el limite degrada
        independientemente con la causa real (FR-009).
        """
        capa = self._capas["espacio_publico"]
        tareas = [(capa, self._consultar_feature_punto(capa, lng, lat))]
        resultados, fallos = await _gather_con_fallos(tareas)
        traza_principal, trazas_subfuente = _trazas_de_bloque(tareas, resultados)

        resultado = resultados[0]
        if isinstance(resultado, BaseException):
            return EspacioPublicoLote(), traza_principal, trazas_subfuente, fallos
        features = resultado.get("features") or []
        if not features:
            return EspacioPublicoLote(), traza_principal, trazas_subfuente, fallos
        propiedades = features[0].get("properties") or {}
        return (
            EspacioPublicoLote(
                codigo_upl=_primer_texto(propiedades, ["CODIGO_UPL"]),
                nombre_upl=_primer_texto(propiedades, ["NOMBRE"]),
                ep_total_m2_hab=_extraer_numero(propiedades, ["EPT", "EP_TOTAL", "TOTAL"]),
            ),
            traza_principal,
            trazas_subfuente,
            fallos,
        )

    async def consultar_red_vial(
        self, lng: float, lat: float, radio_m: int = 100
    ) -> tuple[RedVialLote, SourceTrace, list[SourceTrace], list[FalloCapa]]:
        """Consulta los ejes viales del frente del lote (Mapa_Referencia layer 13).

        Radio de 100 m sobre el centroide: el eje vial del frente queda a menos
        de una manzana corta del lote (verificado en vivo: ejes de la Avenida
        Mariscal Sucre a ~60-100 m del centroide de un lote interior). La
        jerarquia se DERIVA del tipo de via (MVITIPO) porque la capa no publica
        un campo de jerarquia funcional explicita (limitacion documentada);
        nunca se inventa una jerarquia ausente (FR-014).
        """
        if radio_m is None or radio_m <= 0:
            raise ValueError("radio_m debe ser un valor positivo en metros")
        capa = self._capas["malla_vial"]
        tareas = [
            (capa, self._consultar_radio(capa, lng, lat, radio_m, ["MVINOMBRE"]))
        ]
        resultados, fallos = await _gather_con_fallos(tareas)
        traza_principal, trazas_subfuente = _trazas_de_bloque(tareas, resultados)

        resultado = resultados[0]
        if isinstance(resultado, BaseException):
            return RedVialLote(), traza_principal, trazas_subfuente, fallos
        features = resultado.get("features") or []
        vias: list[ViaFrenteLote] = []
        for feature in features:
            propiedades = feature.get("properties") or {}
            tipo_via = _primer_texto(propiedades, ["MVITIPO"])
            carriles = _extraer_numero(propiedades, ["MVINUMC"])
            vias.append(
                ViaFrenteLote(
                    tipo_via=tipo_via,
                    nombre_via=_primer_texto(propiedades, ["MVINOMBRE", "MVIETIQUET"]),
                    carriles=int(carriles) if carriles is not None else None,
                    velocidad_reglamentaria=_primer_texto(propiedades, ["MVIVELREG"]),
                    jerarquia=_jerarquia_de_via(tipo_via),
                )
            )
        jerarquia_maxima = _jerarquia_maxima(vias)
        return (
            RedVialLote(vias_frente=vias, jerarquia_maxima=jerarquia_maxima),
            traza_principal,
            trazas_subfuente,
            fallos,
        )

    async def consultar_equipamientos_cercanos(
        self, lng: float, lat: float
    ) -> tuple[EquipamientosCercanos, SourceTrace, list[SourceTrace], list[FalloCapa]]:
        """Consulta equipamientos cercanos por tipo en paralelo (5 capas).

        Salud: IPS con servicio de vacunacion (800 m); educacion: colegios
        oficiales (500 m); cultura: equipamientos culturales por categoria
        Ciencia/Arte/Historia (800 m; el layer 6 "Museos" responde 400 en vivo
        y se excluye). Las distancias se calculan con haversine desde el
        centroide del lote sobre la geometria real de cada feature. Retorna la
        tupla uniforme de bloques con trazas por sub-fuente y fallos tipados
        (FR-009).
        """
        configuracion_radio: list[tuple[str, int, Literal["salud", "educacion", "cultura"]]] = [
            ("facilidad_salud", 800, "salud"),
            ("facilidad_educacion", 500, "educacion"),
            ("facilidad_cultura_ciencia", 800, "cultura"),
            ("facilidad_cultura_arte", 800, "cultura"),
            ("facilidad_cultura_historia", 800, "cultura"),
        ]
        tareas = [
            (
                self._capas[clave],
                self._consultar_radio_con_geometria(self._capas[clave], lng, lat, radio),
            )
            for clave, radio, _ in configuracion_radio
        ]
        resultados, fallos = await _gather_con_fallos(tareas)
        traza_principal, trazas_subfuente = _trazas_de_bloque(tareas, resultados)

        campos_nombre_por_capa = {
            "facilidad_salud": ["NOMBRE_IPS"],
            "facilidad_educacion": ["NOMBRE_EST", "NOMBRE_SED"],
            "facilidad_cultura_ciencia": ["NOMBRE_D_1", "NOMBRE"],
            "facilidad_cultura_arte": ["NOMBRE_D_1", "NOMBRE"],
            "facilidad_cultura_historia": ["NOMBRE_D_1", "NOMBRE"],
        }
        campos_direccion_por_capa = {
            "facilidad_salud": ["DIR_IPS"],
            "facilidad_educacion": ["DIRECCION"],
            "facilidad_cultura_ciencia": ["DIRECCIO_1", "DIRECCION"],
            "facilidad_cultura_arte": ["DIRECCIO_1", "DIRECCION"],
            "facilidad_cultura_historia": ["DIRECCIO_1", "DIRECCION"],
        }

        equipamientos: list[EquipamientoCercano] = []
        totales: dict[str, int | None] = {"salud": None, "educacion": None, "cultura": None}
        for (clave, _, tipo), resultado in zip(configuracion_radio, resultados):
            if isinstance(resultado, BaseException):
                continue
            features = resultado.get("features") or []
            totales[tipo] = len(features)
            for feature in features:
                propiedades = feature.get("properties") or {}
                distancia = _distancia_del_feature(feature, lng, lat)
                equipamientos.append(
                    EquipamientoCercano(
                        tipo=tipo,
                        nombre=_primer_texto(propiedades, campos_nombre_por_capa[clave]),
                        direccion=_primer_texto(propiedades, campos_direccion_por_capa[clave]),
                        distancia_m=distancia,
                    )
                )

        mas_cercano = (
            min(equipamientos, key=lambda eq: eq.distancia_m or float("inf"))
            if equipamientos
            else None
        )
        return (
            EquipamientosCercanos(
                total_salud=totales["salud"],
                total_educacion=totales["educacion"],
                total_cultura=totales["cultura"],
                equipamientos=equipamientos,
                mas_cercano=mas_cercano,
            ),
            traza_principal,
            trazas_subfuente,
            fallos,
        )


    async def _consultar_radio(
        self,
        capa: CapaConfig,
        lng: float,
        lat: float,
        radio_m: int,
        campos_nombre: list[str],
    ) -> dict[str, Any]:
        """Consulta features en un radio alrededor del punto (patron obras_publicas_radio)."""
        params = {
            "f": "geojson",
            "geometry": f"{lng},{lat}",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "distance": str(radio_m),
            "units": "esriSRUnit_Meter",
            "outSR": "4326",
            "returnGeometry": "false",
            "outFields": "*",
        }
        return await self._consultar(capa, params)

    async def _consultar_radio_con_geometria(
        self, capa: CapaConfig, lng: float, lat: float, radio_m: int
    ) -> dict[str, Any]:
        """Consulta features en un radio CON geometria (para calcular distancias).

        Patron de `consultar_equipamientos_cercanos`: la geometria Point del
        feature permite computar la distancia haversine desde el centroide del
        lote de forma determinista (sin depender de campos de distancia de la
        fuente).
        """
        params = {
            "f": "geojson",
            "geometry": f"{lng},{lat}",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "distance": str(radio_m),
            "units": "esriSRUnit_Meter",
            "outSR": "4326",
            "returnGeometry": "true",
            "outFields": "*",
        }
        return await self._consultar(capa, params)

    async def _consultar(self, capa: CapaConfig, params: dict[str, Any]) -> dict[str, Any]:
        """Consulta la capa ArcGIS delegando en las utilidades compartidas.

        La clasificacion de errores (5xx/4xx/body/payload, FR-009) vive en
        `arcgis_utils.consultar_query` (plan.md:303-312): este modulo no duplica
        la semantica espacial ni el clasificador.
        """
        return await consultar_query(
            client=self._client,
            base_url=capa.service_url,
            layer_id=capa.layer_id,
            source_name=capa.source_name,
            params=params,
        )

    @staticmethod
    def _params_punto(lng: float, lat: float) -> dict[str, Any]:
        """Params de la consulta espacial por punto (patron F1, delegado).

        `construir_params_punto` usa la firma (lat, lon); aqui se conserva el
        orden historico (lng, lat) de los llamadores de F1 sin cambiar el dict
        resultante.
        """
        return construir_params_punto(lat=lat, lon=lng)

    def _parsear_lotes(self, data: dict[str, Any]) -> list[LoteArcgis]:
        capa = self._capas["lote"]
        trace = _construir_trace(capa)
        lotes: list[LoteArcgis] = []
        for feature in data.get("features") or []:
            propiedades = feature.get("properties") or {}
            codigo = _primer_texto(propiedades, ["LOTCODIGO"])
            manzana = _primer_texto(propiedades, ["MANZCODIGO"])
            if not codigo or not manzana:
                # Feature no identificable: no es un lote resoluble
                continue
            geometria = _parsear_geometria(feature, capa)
            lotes.append(
                LoteArcgis(
                    codigo_catastral=codigo,
                    manzana=manzana,
                    chip=_normalizar_chip(propiedades),
                    direccion_normalizada=_primer_texto(propiedades, ["DIRECCION", "NOMBRE"]),
                    barrio=_primer_texto(propiedades, ["BARRIO"]),
                    geometry=geometria,
                    source_trace=trace,
                )
            )
        return lotes


def _construir_trace(capa: CapaConfig, *, data_vigencia: str | None = None) -> SourceTrace:
    return SourceTrace(
        source_name=capa.source_name,
        layer_id=capa.layer_id,
        service_url=capa.service_url,
        data_vigencia=data_vigencia or capa.data_vigencia,
        query_timestamp=_ahora_iso(),
    )


def _normalizar_chip(propiedades: dict[str, Any]) -> str | None:
    valor = _primer_valor(propiedades, ["CHIP", "CHIP_PREDIO", "CODIGO_CHIP"])
    if valor is None:
        return None
    chip = str(valor).strip().upper()
    return chip if PATRON_CHIP.fullmatch(chip) else None


def _parsear_geometria(feature: dict[str, Any], capa: CapaConfig) -> dict[str, Any]:
    """Valida la geometria GeoJSON del feature de la capa Lote (hallazgo A2, punto 8).

    La geometria es parte central del lote (requerida por el contrato): si la
    capa devuelve un feature sin geometria o con estructura no esperada, se falla
    alto con FuenteDatosInvalidosError en vez de publicar un objeto vacio o
    confundirlo con "lote no encontrado" (FR-009).
    """
    geometria = feature.get("geometry")
    if not isinstance(geometria, dict):
        raise FuenteDatosInvalidosError(capa.source_name, "la capa Lote devolvió un feature sin geometría GeoJSON")
    if not isinstance(geometria.get("type"), str) or not geometria.get("coordinates"):
        raise FuenteDatosInvalidosError(
            capa.source_name, "la capa Lote devolvió una geometría sin estructura GeoJSON válida"
        )
    return geometria


def _vigencia_del_feature(propiedades: dict[str, Any]) -> str | None:
    return _primer_texto(propiedades, ["ANIO", "ANO", "VIGENCIA", "ANIO_VIGENCIA"])


# --- Fase 3: jerarquia vial derivada y distancia haversine ---

# Jerarquia DERIVADA del tipo de via (MVITIPO). La capa Malla Vial no publica
# un campo de jerarquia funcional explicita: MVITCLA ("Tipo de clasificacion")
# no tiene dominio publicado y no correlaciona con una jerarquia funcional.
# La capa publica el tipo en dos formas (abreviada viva 'AC'/'KR' y nombre
# largo de la metadata 'Avenida Calle'/'Carrera'); ambas se mapean. Criterio
# documentado: avenida > calle/carrera > diagonal/transversal (limitacion
# documentada en AGENTS.md; nunca se inventa una jerarquia ausente, FR-014).
_JERARQUIA_POR_TIPO_VIA: dict[str, Literal["alta", "media", "baja"]] = {
    "ac": "alta",
    "ak": "alta",
    "avenida calle": "alta",
    "avenida carrera": "alta",
    "cl": "media",
    "kr": "media",
    "calle": "media",
    "carrera": "media",
    "dg": "baja",
    "tv": "baja",
    "diagonal": "baja",
    "transversal": "baja",
}

_ORDEN_JERARQUIA: dict[str, int] = {"alta": 3, "media": 2, "baja": 1, "desconocida": 0}

_RADIO_TIERRA_M = 6_371_000.0


def _jerarquia_de_via(tipo_via: str | None) -> Literal["alta", "media", "baja", "desconocida"]:
    """Deriva la jerarquia vial desde el tipo de via (MVITIPO), sin inventarla."""
    if tipo_via is None:
        return "desconocida"
    return _JERARQUIA_POR_TIPO_VIA.get(tipo_via.strip().lower(), "desconocida")


def _jerarquia_maxima(vias: list[ViaFrenteLote]) -> Literal["alta", "media", "baja", "desconocida"]:
    """Jerarquia mas alta entre las vias del frente ('desconocida' si no hay vias)."""
    if not vias:
        return "desconocida"
    return max(
        (via.jerarquia or "desconocida" for via in vias),
        key=lambda jerarquia: _ORDEN_JERARQUIA[jerarquia],
    )


def _distancia_haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distancia haversine en metros entre dos puntos WGS84 (funcion pura)."""
    lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng / 2) ** 2
    )
    return 2 * _RADIO_TIERRA_M * math.asin(math.sqrt(a))


def _distancia_del_feature(
    feature: dict[str, Any], lng_centroide: float, lat_centroide: float
) -> float | None:
    """Distancia haversine del feature Point al centroide; None sin geometria utilizable."""
    geometria = feature.get("geometry")
    if not isinstance(geometria, dict):
        return None
    coordenadas = geometria.get("coordinates")
    if (
        not isinstance(coordenadas, list)
        or len(coordenadas) != 2
        or not all(isinstance(c, (int, float)) for c in coordenadas)
    ):
        return None
    lng_feature, lat_feature = float(coordenadas[0]), float(coordenadas[1])
    return _distancia_haversine_m(lat_centroide, lng_centroide, lat_feature, lng_feature)


# _primer_valor/_primer_texto/_extraer_numero/_ahora_iso viven en
# app/utilidades.py (hallazgo m7).


def _parsear_filas_predio(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extrae los atributos de las filas de la capa Predio (formato pjson).

    La capa Predio es tabular: la respuesta pjson trae `features[].attributes`
    sin geometria (research H1); nunca se parsea con el formato geojson
    (`properties`), que la capa no usa.
    """
    return [feature.get("attributes") or {} for feature in data.get("features") or []]


def _traducir_dominio(dominio: dict[str, str], codigo: str | None) -> str | None:
    """Traduce un codigo de dominio versionado a su descripcion.

    Fallback documentado (research H1): si el codigo no esta en la tabla (el
    dominio en vivo se actualizo), la descripcion es el codigo crudo; nunca se
    inventa un texto (FR-014).
    """
    if codigo is None:
        return None
    return dominio.get(codigo, codigo)


# Niveles de amenaza por raiz con limite de palabra (hallazgo m1): la capa
# gestionriesgos publica "Amenaza alta/media/baja" (adjetivo femenino
# pospuesto), ademas de las formas masculinas. Los limites de palabra evitan
# falsos positivos ("altitud", "altura", "remedia", "medianoche" no matchean).
_PATRON_NIVEL_ALTO = re.compile(r"\b(?:crític[oa]s?|critic[oa]s?|alt[oa]s?)\b")
_PATRON_NIVEL_MEDIO = re.compile(r"\b(?:moderad[oa]s?|medi[oa]s?)\b")
_PATRON_NIVEL_BAJO = re.compile(r"\b(?:normal(?:es)?|baj[oa]s?)\b")


def _inferir_nivel_amenaza(amenaza: str | None) -> Literal["alto", "medio", "bajo", "desconocido"]:
    """Infiere el nivel de amenaza geotecnicos desde el campo GEOTECNIA.

    Clasificacion por raices insensibles a genero y numero ("alto"/"alta",
    "medio"/"media", "bajo"/"baja") terminologia comun de las capas de gestion
    de riesgos de Bogota. Se evalua de mas critico a menos critico. Si no hay
    dato o ningun patron matchea, retorna "desconocido". Nunca inventa
    clasificaciones (FR-014).
    """
    if amenaza is None:
        return "desconocido"
    amenaza_normalizada = amenaza.lower()
    if _PATRON_NIVEL_ALTO.search(amenaza_normalizada):
        return "alto"
    if _PATRON_NIVEL_MEDIO.search(amenaza_normalizada):
        return "medio"
    if _PATRON_NIVEL_BAJO.search(amenaza_normalizada):
        return "bajo"
    return "desconocido"
