"""Taxonomia de errores del contrato (data-model.md:137-149, Principio IV).

Los 10 codigos canonicos son compartidos por todas las tools. Un error del lado
del servidor de una fuente (5xx) NUNCA se reporta como "no encontrado" (FR-009):
es un fallo fatal de la tool que identifica la fuente.

Codigos de F2 (data-model.md:219-249): LOTE_SIN_UPL es un "dato no encontrado"
no fatal (FR-007); CORPUS_NO_INGESTADO es un estado de infraestructura que se
reporta como error para evitar resultados vacios silenciosos; OLLAMA_NO_DISPONIBLE
es fail-fast cuando el servicio de modelos no es accesible o falta un modelo
(FR-011).
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
    LOTE_SIN_UPL = "LOTE_SIN_UPL"
    CORPUS_NO_INGESTADO = "CORPUS_NO_INGESTADO"
    OLLAMA_NO_DISPONIBLE = "OLLAMA_NO_DISPONIBLE"


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
    CodigoError.LOTE_SIN_UPL: (
        "El lote {codigo_catastral} no tiene UPL asignada (dato no encontrado)."
    ),
    CodigoError.CORPUS_NO_INGESTADO: (
        "El corpus normativo no está ingestado o está desactualizado. "
        "Ejecuta el script de ingesta antes de consultar."
    ),
    CodigoError.OLLAMA_NO_DISPONIBLE: (
        "El servicio Ollama no está disponible o falta el modelo {modelo}. "
        "Verifica OLLAMA_HOST/OLLAMA_BASE_URL y ollama pull {modelo}."
    ),
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


class UplNoEncontradaError(Exception):
    """La capa UPL no tiene datos para el punto consultado (dato no encontrado).

    Es un estado no fatal (FR-007): el lote existe pero no tiene UPL asignada.
    Diferente de LOTE_NO_ENCONTRADO (lote no existe) y FUENTE_5XX (error servidor).
    """

    def __init__(self, source_name: str, codigo_catastral: str | None = None) -> None:
        msg = "La capa UPL no devolvio ningun feature para el punto consultado."
        if codigo_catastral:
            msg += f" Lote: {codigo_catastral}."
        super().__init__(msg)
        self.source_name = source_name
        self.codigo_catastral = codigo_catastral


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


class CorpusNoIngestadoError(Exception):
    """El corpus normativo no esta ingestado o el indice esta desactualizado (FR-009).

    Es un estado de infraestructura, NO "sin resultados" (data-model.md:247-248):
    se reporta como CORPUS_NO_INGESTADO en el limite de la tool para evitar
    resultados vacios silenciosos. El mensaje es accionable: ejecutar la ingesta.

    `detalle` permite anteponer el motivo concreto (p. ej. un hash del corpus que
    no coincide con el persistido, FIX 5) sin perder el mensaje canonico.
    """

    def __init__(self, source_name: str = "corpus", detalle: str | None = None) -> None:
        mensaje = (
            "El corpus normativo no está ingestado o está desactualizado. "
            "Ejecuta el script de ingesta antes de consultar."
        )
        if detalle:
            mensaje = f"{mensaje} {detalle}"
        super().__init__(mensaje)
        self.source_name = source_name


class OllamaNoDisponibleError(Exception):
    """El servicio Ollama no es accesible o un modelo requerido no esta instalado (FR-011).

    Fail-fast con mensaje claro y accionable que incluye el nombre del modelo:
    verificar OLLAMA_HOST/OLLAMA_BASE_URL y descargar el modelo con
    `ollama pull <modelo>`.
    """

    def __init__(self, source_name: str = "ollama", modelo: str | None = None) -> None:
        self.source_name = source_name
        self.modelo = modelo
        modelo_mensaje = modelo if modelo else "requerido"
        super().__init__(
            f"El servicio Ollama no está disponible o falta el modelo {modelo_mensaje}. "
            f"Verifica OLLAMA_HOST/OLLAMA_BASE_URL y ollama pull {modelo_mensaje}."
        )


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
