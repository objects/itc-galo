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
    DestinoEconomico,
    ObraPublica,
    ReservaVial,
    SourceTrace,
    UsoEconomico,
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
# - predio (capa tabular Predio, F3): la vigencia del dato es la del registro
#   (PREVACTUAL, research H7); este valor es solo el respaldo de CapaConfig
#   cuando el registro no la declara.
VIGENCIAS_DEFAULT: dict[str, str] = {
    "lote": "2019",
    "valorreferencia": "2012-2025",
    "reservavial": "2019-08-15",
    "obraspublicas": "2025",
    "predio": "2026",
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
}

_URLS_CANONICOS = {
    "lote": f"{RAIZ_ARCGIS}/Mapa_Referencia/Mapa_Referencia/MapServer",
    "valorreferencia": f"{RAIZ_ARCGIS}/catastro/valorreferencia/MapServer",
    "reservavial": f"{RAIZ_ARCGIS}/ordenamientoterritorial/reservavial/MapServer",
    "obraspublicas": f"{RAIZ_ARCGIS}/gestionpublica/obraspublicas/MapServer",
    "predio": f"{RAIZ_ARCGIS}/catastro/lote/MapServer",
}

_CAPAS_CANONICOS = {
    "lote": "38",
    "valorreferencia": "0",
    # reservavial usa el layer 2: el layer 1 es un Group Layer y la capa
    # consultable es el Feature Layer 2 (hallazgo vivo, Fix C).
    "reservavial": "2",
    "obraspublicas": "0",
    "predio": "3",
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
