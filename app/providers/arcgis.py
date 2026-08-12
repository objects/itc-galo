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
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel

from app.errores import FuenteDatosInvalidosError
from app.models import (
    ContextoTematico,
    ObraPublica,
    ReservaVial,
    SourceTrace,
    ValorReferencia,
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
VIGENCIAS_DEFAULT: dict[str, str] = {
    "lote": "2019",
    "valorreferencia": "2012-2025",
    "reservavial": "2019-08-15",
    "obraspublicas": "2025",
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
}

_URLS_CANONICOS = {
    "lote": f"{RAIZ_ARCGIS}/Mapa_Referencia/Mapa_Referencia/MapServer",
    "valorreferencia": f"{RAIZ_ARCGIS}/catastro/valorreferencia/MapServer",
    "reservavial": f"{RAIZ_ARCGIS}/ordenamientoterritorial/reservavial/MapServer",
    "obraspublicas": f"{RAIZ_ARCGIS}/gestionpublica/obraspublicas/MapServer",
}

_CAPAS_CANONICOS = {
    "lote": "38",
    "valorreferencia": "0",
    # reservavial usa el layer 2: el layer 1 es un Group Layer y la capa
    # consultable es el Feature Layer 2 (hallazgo vivo, Fix C).
    "reservavial": "2",
    "obraspublicas": "0",
}

PATRON_CHIP = re.compile(r"^[A-Z0-9]{11}$")


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

    async def consultar_contexto_tematico(
        self, codigo_catastral: str, lng: float, lat: float
    ) -> ContextoTematico:
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


def _primer_valor(objeto: dict[str, Any], claves: list[str]) -> Any:
    for clave in claves:
        if clave in objeto and objeto[clave] is not None:
            return objeto[clave]
    return None


def _primer_texto(objeto: dict[str, Any], claves: list[str]) -> str | None:
    valor = _primer_valor(objeto, claves)
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _extraer_numero(objeto: dict[str, Any], claves: list[str]) -> float | None:
    valor = _primer_valor(objeto, claves)
    if valor is None or valor == "":
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _ahora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
