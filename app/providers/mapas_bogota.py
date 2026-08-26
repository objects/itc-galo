"""Provider de la API de busqueda de Mapas Bogota (T010, T016, T023).

Frontera de parsing para https://catalogopmb.catastrobogota.gov.co/PMBWeb/web
(constitucion, Principio II): expone modelos tipados y NO mezcla
responsabilidades con ArcGIS.

La API viva migro de https://mapas.bogota.gov.co/api/ (hoy un shell ReDoc
estatico sin API) a catalogopmb.catastrobogota.gov.co/PMBWeb/web con dos rutas:
- /buscar con cmd=direccion_chip: busca el predio por CHIP (geometria WGS84 +
  centroide); la geometria ya llega en grados decimales, no se convierte.
- /api con cmd=geocodificar: localiza una direccion (requiere
  MAPAS_BOGOTA_APIKEY; el fail-fast de credencial se hace en el limite de la
  tool, no aqui, FR-010). Una clave rechazada por la fuente ("API Key no
  valida") se reporta como CredencialFaltanteError.

Formas de error de la API viva (todas HTTP 200 JSON): CHIP desconocido o sin
spatialReference -> {"mensaje": "El servicio no esta disponible", "status":
false}; sin query -> {"status": false}; cmd desconocido -> {}. Ninguna es un
5xx: se tratan como "dato no encontrado" (None) salvo la clave invalida, que es
un problema de credencial.

Manejo de errores de fuente (FR-009, Principio IV): un 5xx (HTTP o code del
body) es Fuente5xxError y nunca "no encontrado"; un 4xx es Fuente4xxError (la
peticion fue rechazada, no es un estado de dato); un payload no utilizable es
FuenteDatosInvalidosError.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from pydantic import BaseModel

from app.errores import (
    CredencialFaltanteError,
    Fuente4xxError,
    Fuente5xxError,
    FuenteDatosInvalidosError,
    verificar_body_sin_error,
)
from app.models import SourceTrace
# Helper compartido (hallazgo m7): unica definicion en app/utilidades.py.
from app.utilidades import ahora_iso as _ahora_iso
from app.providers.geom import punto_interior_seguro

URL_SERVICIO = "https://catalogopmb.catastrobogota.gov.co/PMBWeb/web"
# Ruta relativa: httpx anexa a URL_SERVICIO quitando el "/" inicial
# (p. ej. "/buscar" -> .../PMBWeb/web/buscar); no es ruta absoluta del host.
RUTA_BUSCAR = "/buscar"
RUTA_API = "/api"
NOMBRE_FUENTE = "mapas_bogota"
VIGENCIA_API = "2025"  # vigencia declarada de la API de busqueda en vivo


class PredioBuscado(BaseModel):
    """Predio devuelto por cmd=direccion_chip, con centroide en WGS84 (lng, lat).

    `chip` es el VALUE del resultado (el CHIP puede no coincidir con el
    consultado si la API devuelve varios resultados); `direccion` y `barrio`
    son NOMBRE y BARRIO del predio.
    """

    chip: str | None = None
    direccion: str | None = None
    barrio: str | None = None
    centroid: tuple[float, float]


class CandidatoDireccion(BaseModel):
    """Candidato de cmd=geocodificar: direccion normalizada y punto WGS84."""

    direccion_normalizada: str
    lat: float
    lng: float


class MapasBogotaProvider:
    """Cliente httpx async para la API de busqueda de Mapas Bogota.

    Ante fallos transitorios de la fuente (cold-start del backend: 503 que
    desaparece al segundo intento, timeouts de conexion) reintenta los GET
    idempotentes con backoff exponencial corto antes de fallar (FR-009).
    """

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
        intentos: int = 3,
        backoff_segundos: float = 0.5,
        dormir: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if intentos < 1:
            raise ValueError("intentos debe ser >= 1")
        self._client = httpx.AsyncClient(
            base_url=URL_SERVICIO, transport=transport, timeout=timeout
        )
        self._api_key = api_key
        self._intentos = intentos
        self._backoff_segundos = backoff_segundos
        # Inyectable para tests (sin esperas reales); por defecto asyncio.sleep.
        self._dormir: Callable[[float], Awaitable[None]] = (
            dormir if dormir is not None else asyncio.sleep
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def tiene_api_key(self) -> bool:
        return bool(self._api_key)

    def construir_trace(self, layer_id: str) -> SourceTrace:
        """Trazabilidad de una consulta a la API de Mapas Bogota (5 campos)."""
        return SourceTrace(
            source_name=NOMBRE_FUENTE,
            layer_id=layer_id,
            service_url=URL_SERVICIO,
            data_vigencia=VIGENCIA_API,
            query_timestamp=_ahora_iso(),
        )

    async def buscar_por_chip(self, chip: str) -> PredioBuscado | None:
        """Resuelve el predio del CHIP (cmd=direccion_chip) o None si no existe.

        La API viva puede devolver 2+ resultados para un mismo CHIP; se toma el
        primero. Un body con status:false ("El servicio no esta disponible" para
        CHIP desconocido, "sin query", o cmd desconocido {}) NO es un 5xx: se
        trata como predio no encontrado (None).
        """
        params = {"cmd": "direccion_chip", "query": chip, "spatialReference": 102100}
        data = await self._consultar(RUTA_BUSCAR, params)
        if data.get("status") is False:
            # CHIP desconocido: la API viva responde HTTP 200 con status:false
            # ("El servicio no esta disponible"); es no encontrado (None), no 5xx.
            return None
        resultados = data.get("resultados") or []
        if not resultados:
            return None
        return self._parsear_predio(resultados[0])

    async def geocodificar(self, direccion: str) -> list[CandidatoDireccion]:
        """Geocodifica una direccion (cmd=geocodificar) y devuelve candidatos.

        Defensa en profundidad (FR-010): si falta la clave se falla rapido aqui
        tambien, aunque el limite de la tool ya valida antes de llamar al provider.
        Si la fuente rechaza la clave ("API Key no valida", HTTP 200 status:false),
        se reporta como CredencialFaltanteError (problema de credencial, no un
        dato ausente ni un 5xx).
        """
        if not self.tiene_api_key():
            raise CredencialFaltanteError(NOMBRE_FUENTE)
        params = {"cmd": "geocodificar", "query": direccion, "apikey": self._api_key}
        data = await self._consultar(RUTA_API, params)
        if data.get("status") is False:
            mensaje = _texto_o_none(data.get("message") or data.get("mensaje"))
            if mensaje and "API Key" in mensaje:
                raise CredencialFaltanteError(NOMBRE_FUENTE)
            # Sin candidatos: la direccion no se localizo (dato no encontrado)
            return []
        return self._parsear_candidatos(data)

    async def _consultar(self, ruta: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET a la API con reintentos ante fallos transitorios y clasificacion tipada.

        Reintenta (GET idempotente) ante `httpx.TransportError` (timeout/conexion)
        y respuestas HTTP >= 500 — los 503 transitorios por cold-start del backend
        de Mapas Bogota se recuperan solos — con backoff exponencial corto
        (`backoff_segundos * 2**(intento-1)`). Los 4xx NO se reintentan (fallan
        igual). Tras agotar `intentos` lanza Fuente5xxError (FR-009) con la causa
        distinguible en el mensaje ("tras N intentos", timeout vs HTTP real).

        - HTTP/body 5xx persistente -> Fuente5xxError (FR-009).
        - HTTP/body 4xx -> Fuente4xxError (peticion rechazada).
        - Payload no utilizable -> FuenteDatosInvalidosError.
        """
        ultima_causa: Exception | None = None
        ultimo_status = 503
        for intento in range(1, self._intentos + 1):
            try:
                respuesta = await self._client.get(ruta, params=params)
            except httpx.TransportError as exc:
                ultima_causa = exc
                ultimo_status = 503
            else:
                if respuesta.status_code < 500:
                    return self._clasificar_respuesta(respuesta)
                ultima_causa = None
                ultimo_status = respuesta.status_code
            if intento < self._intentos:
                await self._dormir(self._backoff_segundos * 2 ** (intento - 1))
        if ultima_causa is not None:
            raise Fuente5xxError(
                NOMBRE_FUENTE,
                503,
                detalle=(
                    "sin respuesta tras "
                    f"{self._intentos} intentos ({_causa_transporte(ultima_causa)})."
                ),
            ) from ultima_causa
        raise Fuente5xxError(
            NOMBRE_FUENTE,
            ultimo_status,
            detalle=f"error persistente tras {self._intentos} intentos.",
        )

    def _clasificar_respuesta(self, respuesta: httpx.Response) -> dict[str, Any]:
        """Clasifica una respuesta HTTP < 500 segun la taxonomia tipada."""
        if respuesta.status_code >= 400:
            raise Fuente4xxError(NOMBRE_FUENTE, respuesta.status_code)
        try:
            data = respuesta.json()
        except json.JSONDecodeError as exc:
            raise FuenteDatosInvalidosError(
                NOMBRE_FUENTE, "la respuesta no es JSON válido"
            ) from exc
        return verificar_body_sin_error(data, NOMBRE_FUENTE)

    def _parsear_predio(self, resultado: dict[str, Any]) -> PredioBuscado | None:
        geometria = resultado.get("GEOMETRY") or {}
        rings = geometria.get("rings") or []
        if rings:
            lng, lat = _centroide_desde_rings(rings)
        else:
            # Fallback defensivo: el item puede traer el punto directo
            # (LATITUD/LONGITUD) en vez de un poligono (parse, no valida).
            lat, lng = _extraer_coordenadas(resultado)
        if lng is None or lat is None:
            return None
        return PredioBuscado(
            chip=_texto_o_none(resultado.get("VALUE")),
            direccion=_texto_o_none(resultado.get("NOMBRE")),
            barrio=_texto_o_none(resultado.get("BARRIO")),
            centroid=(lng, lat),
        )

    def _parsear_candidatos(self, data: dict[str, Any]) -> list[CandidatoDireccion]:
        items = data.get("resultados") or data.get("candidatos") or []
        if isinstance(items, dict):
            items = [items]
        candidatos: list[CandidatoDireccion] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            lat, lng = _extraer_coordenadas(item)
            if lat is None or lng is None:
                continue
            candidatos.append(
                CandidatoDireccion(
                    direccion_normalizada=_texto_o_none(
                        _primer_valor(item, ["NOMBRE", "DIRECCION", "address"])
                    )
                    or "",
                    lat=lat,
                    lng=lng,
                )
            )
        return candidatos


def _causa_transporte(exc: httpx.TransportError) -> str:
    """Causa legible de un TransportError para el mensaje de Fuente5xxError."""
    if isinstance(exc, httpx.TimeoutException):
        return "timeout de conexión"
    return "error de conexión"


def _centroide_desde_rings(rings: list[list[list[float]]]) -> tuple[float | None, float | None]:
    """Centroide geometrico interior del poligono ESRI (rings ya en WGS84).

    Usa la formula del centroide de poligono (shoelace con areas) sobre el
    anillo exterior respetando los agujeros; si el resultado cae fuera (lotes
    concavos), busca un punto interior seguro determinista (hallazgo M3). La
    media aritmetica de vertices quedo atras: puede caer fuera del lote y
    provocar consultas fantasma ("lote no encontrado") al re-consultar la capa
    por punto.

    La API viva entrega GEOMETRY.rings en grados decimales (WGS84); la conversion
    desde Web Mercator queda solo como defensa (D4) por si un payload futuro no
    respeta ese formato: cualquier transformacion lineal preserva centroides y
    contencion, asi que basta convertir el punto resultante.
    """
    if not rings:
        return None, None
    punto = punto_interior_seguro(rings)
    if punto is None:
        return None, None
    cx, cy = punto
    # La API se consulta con spatialReference=102100; si el centroide no parece
    # grados decimales, se convierte de Web Mercator a WGS84 (defensivo, D4).
    if abs(cx) > 180 or abs(cy) > 90:
        cx, cy = _web_mercator_a_wgs84(cx, cy)
    return cx, cy


def _web_mercator_a_wgs84(x: float, y: float) -> tuple[float, float]:
    lng = x / 20037508.34 * 180.0
    lat = math.degrees(2 * math.atan(math.exp(y / 20037508.34 * math.pi)) - math.pi / 2)
    return lng, lat


def _extraer_coordenadas(item: dict[str, Any]) -> tuple[float | None, float | None]:
    lat = _primer_valor(item, ["LATITUD", "lat", "latitude"])
    lng = _primer_valor(item, ["LONGITUD", "lng", "longitude", "lon"])
    if lat is None and lng is None:
        coords = item.get("coordinates")
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            lng, lat = coords[0], coords[1]
    return _a_float(lat), _a_float(lng)


def _primer_valor(objeto: dict[str, Any], claves: list[str]) -> Any:
    for clave in claves:
        if clave in objeto and objeto[clave] is not None:
            return objeto[clave]
    return None


def _texto_o_none(valor: Any) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _a_float(valor: Any) -> float | None:
    if valor is None:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


# _ahora_iso vive en app/utilidades.py (hallazgo m7).
