"""Taxonomia de errores del contrato (data-model.md:137-149, Principio IV).

Los 7 codigos canonicos son compartidos por todas las tools. Un error del lado
del servidor de una fuente (5xx) NUNCA se reporta como "no encontrado" (FR-009):
es un fallo fatal de la tool que identifica la fuente.
"""

from __future__ import annotations

import enum
from typing import Any


class CodigoError(str, enum.Enum):
    """Codigos canonicos de error del contrato (Principio IV, Fail Fast)."""

    LOTE_NO_ENCONTRADO = "LOTE_NO_ENCONTRADO"
    DIRECCION_NO_LOCALIZADA = "DIRECCION_NO_LOCALIZADA"
    FUERA_DE_COBERTURA = "FUERA_DE_COBERTURA"
    DATO_NO_ENCONTRADO_POR_FUENTE = "DATO_NO_ENCONTRADO_POR_FUENTE"
    FUENTE_5XX = "FUENTE_5XX"
    CREDENCIAL_FALTANTE = "CREDENCIAL_FALTANTE"
    PARAMETROS_INVALIDOS = "PARAMETROS_INVALIDOS"


MENSAJES_ERROR: dict[CodigoError, str] = {
    CodigoError.LOTE_NO_ENCONTRADO: (
        "No se encontró ningún lote para el criterio consultado."
    ),
    CodigoError.DIRECCION_NO_LOCALIZADA: (
        "La dirección no pudo localizarse. Refina la dirección o usa CHIP/coordenadas."
    ),
    CodigoError.FUERA_DE_COBERTURA: (
        "El punto está fuera del área de cobertura (Bogotá)."
    ),
    CodigoError.DATO_NO_ENCONTRADO_POR_FUENTE: (
        "La fuente {source_name} no tiene datos para este lote."
    ),
    CodigoError.FUENTE_5XX: (
        "La fuente {source_name} no está disponible (error {status}). Intenta nuevamente."
    ),
    CodigoError.CREDENCIAL_FALTANTE: (
        "Falta la variable MAPAS_BOGOTA_APIKEY para consultas por dirección. "
        "Configúrala en .env."
    ),
    CodigoError.PARAMETROS_INVALIDOS: "Parámetros inválidos: {detalle}.",
}


class Fuente5xxError(Exception):
    """Fallo del lado del servidor de una fuente (HTTP 5xx o code 5xx del body).

    Es un error fatal de la tool (FR-009): nunca se reporta como dato no
    encontrado. Identifica la fuente que fallo para que el mensaje sea accionable.
    """

    def __init__(self, source_name: str, status: int) -> None:
        super().__init__(f"La fuente {source_name} no está disponible (error {status}).")
        self.source_name = source_name
        self.status = status


class Fuente4xxError(Exception):
    """La fuente rechazo la consulta (HTTP 4xx o code 4xx del body).

    NO es un 5xx: es una peticion invalida desde el lado del cliente/servidor de
    integracion. En el limite de la tool se traduce a PARAMETROS_INVALIDOS con
    mensaje que identifica la fuente y el status HTTP; nunca como "no encontrado"
    (FR-009).
    """

    def __init__(self, source_name: str, status: int, detail: str | None = None) -> None:
        detalle = f": {detail}" if detail else ""
        super().__init__(
            f"La fuente {source_name} rechazo la consulta (error {status}){detalle}."
        )
        self.source_name = source_name
        self.status = status
        self.detail = detail


class FuenteDatosInvalidosError(Exception):
    """La fuente respondio 2xx pero el payload no es utilizable (JSON invalido,
    estructura no esperada, geometria mal formada).

    Es un fallo del lado de la fuente (FR-009): nunca se reporta como "no
    encontrado". En el limite de la tool se traduce a FUENTE_5XX con mensaje
    descriptivo que identifica la fuente y el problema.
    """

    def __init__(self, source_name: str, detail: str) -> None:
        super().__init__(f"La fuente {source_name} devolvio datos no validos: {detail}")
        self.source_name = source_name
        self.detail = detail


class CredencialFaltanteError(Exception):
    """Falta la credencial requerida por la fuente (defensa en profundidad).

    El limite de la tool ya aplica el fail-fast de FR-010 antes de llamar al
    provider; este error solo protege llamadas directas al provider sin clave.
    """

    def __init__(self, source_name: str) -> None:
        super().__init__(f"Falta la credencial requerida por la fuente {source_name}.")
        self.source_name = source_name


def verificar_body_sin_error(data: Any, source_name: str) -> dict[str, Any]:
    """Detecta errores de fuente dentro de un body HTTP 2xx (patron ArcGIS REST:
    HTTP 200 + {"error": {code, message}}). Clasifica igual que los status HTTP:
    code >= 500 -> Fuente5xxError; 4xx -> Fuente4xxError. Devuelve el dict si no
    hay error; rechaza bodies que no sean objetos JSON (FuenteDatosInvalidosError).
    """
    if not isinstance(data, dict):
        raise FuenteDatosInvalidosError(source_name, "la respuesta no es un objeto JSON")
    error = data.get("error")
    if not isinstance(error, dict):
        return data
    codigo = error.get("code")
    if isinstance(codigo, int) and codigo >= 500:
        raise Fuente5xxError(source_name, codigo)
    if isinstance(codigo, int):
        raise Fuente4xxError(source_name, codigo)
    raise Fuente5xxError(source_name, 500)


def construir_error(
    codigo: CodigoError,
    *,
    message: str | None = None,
    source_name: str | None = None,
    **formato: Any,
) -> dict[str, Any]:
    """Construye la respuesta de error canonica {error: {code, message, source_name}}.

    `message` permite el mensaje especifico de cada tool (contratos); si se omite,
    se usa el mensaje canonico de data-model.md interpolando los valores de `formato`.
    """
    plantilla = message if message is not None else MENSAJES_ERROR[codigo]
    contexto_formato = {**formato}
    if source_name is not None:
        contexto_formato["source_name"] = source_name
    return {
        "error": {
            "code": codigo.value,
            "message": plantilla.format(**contexto_formato),
            "source_name": source_name,
        }
    }
