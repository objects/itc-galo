"""Scoring heuristico del informe de factibilidad (research D3, FR-006/FR-007).

Funcion pura `calcular_score(bloques) -> FeasibilityScore`: sin I/O, sin LLM,
sin reloj (SC-003: mismo input -> mismo score/confidence/reasons). Opera sobre
hechos de disponibilidad o afectacion declarados por las fuentes (FR-014):
ninguna regla inventa normativa urbanistica ausente.

Reglas (data-model.md:205-227, research D3):
- Base 50.
- Positivas: UPL resuelta +10; localidad derivada +5; market_context disponible
  +10; economic_context disponible +10; normative_evidence con items +5.
- Negativas: reserva vial que afecta el lote -15; UPL ausente -5; cada bloque
  tematico/economico en no_encontrado -5; evidencia normativa vacia -5.
- `score = clamp(50 + Σ, 0, 100)` entero.
- `confidence` por cobertura de los 11 bloques evaluables: high >= 5 disponibles,
  medium 3-4, low <= 2. Con confidence low, las reasons enumeran los faltantes.
- `reasons`: textos fijos por regla con el dato interpolado y el source_name.
- `rules_applied`: codigos de regla aplicados (auditoria interna).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from app.models import (
    BloqueAccesoMovilidad,
    BloqueCatastroData,
    BloqueContextoSocioeconomico,
    BloqueDestinoEconomico,
    BloqueEntornoRegulatorio,
    BloqueObrasPublicas,
    BloquePatrimonioCultural,
    BloqueReservaVial,
    BloqueRiesgosGeotecnicos,
    BloqueValorReferencia,
    ContextoAdministrativo,
    EvidenciaNormativa,
    FeasibilityScore,
)

PUNTOS_BASE = 50
PUNTOS_UPL = 10
PUNTOS_LOCALIDAD = 5
PUNTOS_MERCADO = 10
PUNTOS_ECONOMICO = 10
PUNTOS_EVIDENCIA = 5
PUNTOS_CONTEXTO_SOCIO = 5
PUNTOS_ACCESO_MOVILIDAD = 5
PENALIZACION_RESERVA_VIAL = 15
PENALIZACION_UPL_AUSENTE = 5
PENALIZACION_BLOQUE_NO_ENCONTRADO = 5
PENALIZACION_EVIDENCIA_VACIA = 5
PENALIZACION_RIESGO_GEOTECNICO_ALTO = 10
PENALIZACION_PATRIMONIO_CULTURAL = 10

# Los bloques evaluables del confidence (6 originales F3 + 6 nuevos F6/F7).
BLOQUES_EVALUABLES = (
    "administrative_context",
    "planning_constraints",
    "market_context",
    "environment_context",
    "economic_context",
    "geotechnical_risks",
    "socioeconomic_context",
    "regulatory_environment",
    "cultural_heritage",
    "transit_access",
    "catastro_data",
    "normative_evidence",
)


class BloquesEvaluables(BaseModel):
    """Estructura tipada de los bloques evaluables del score (data-model)."""

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


def calcular_score(bloques: BloquesEvaluables) -> FeasibilityScore:
    """Calcula el score heuristico 0-100 con reglas puras (research D3).

    `bloques` es una estructura tipada de los 6 bloques evaluables; el score es
    deterministico: misma entrada -> mismo score/confidence/reasons (SC-003).
    """
    puntos_positivos, reglas_positivas, razones_positivas = _reglas_positivas(bloques)
    puntos_negativos, reglas_negativas, razones_negativas = _reglas_negativas(bloques)

    score = _clamp(PUNTOS_BASE + puntos_positivos - puntos_negativos)
    confidence = _confidence_por_cobertura(bloques)
    razones = razones_positivas + razones_negativas
    if confidence == "low":
        razones += _reasons_datos_faltantes(bloques)

    return FeasibilityScore(
        score=score,
        confidence=confidence,
        reasons=razones,
        rules_applied=["r_base"] + reglas_positivas + reglas_negativas,
    )


def _reglas_positivas(
    bloques: BloquesEvaluables,
) -> tuple[int, list[str], list[str]]:
    """Reglas positivas sobre datos reales (research D3): puntos, codigos, razones."""
    puntos = 0
    reglas: list[str] = []
    razones: list[str] = []

    if bloques.administrative_context.upl is not None:
        puntos += PUNTOS_UPL
        reglas.append("r_upl")
        upl = bloques.administrative_context.upl
        razones.append(
            f"UPL resuelta: {upl.codigo_upl} {upl.nombre} "
            f"({bloques.administrative_context.source_trace.source_name})."
        )

    if bloques.administrative_context.localidad is not None:
        puntos += PUNTOS_LOCALIDAD
        reglas.append("r_localidad")
        razones.append(
            f"Localidad derivada: {bloques.administrative_context.localidad.nombre} "
            f"({bloques.administrative_context.source_trace.source_name})."
        )

    if bloques.market_context.estado == "disponible":
        puntos += PUNTOS_MERCADO
        reglas.append("r_mercado")
        dato = bloques.market_context.dato
        valor_m2 = dato.valor_m2 if dato is not None else None
        if valor_m2 is not None:
            razones.append(
                f"Valor de referencia disponible: {_formatear_numero(valor_m2)} COP/m² "
                f"({bloques.market_context.source_trace.source_name})."
            )
        else:
            razones.append(
                f"Valor de referencia disponible: "
                f"({bloques.market_context.source_trace.source_name})."
            )

    if bloques.economic_context.estado == "disponible":
        puntos += PUNTOS_ECONOMICO
        reglas.append("r_economico")
        dato = bloques.economic_context.dato
        if dato is not None:
            etiqueta = dato.descripcion_destino or dato.codigo_destino or "destino económico"
            razones.append(
                f"Destino económico disponible: {etiqueta} "
                f"(código {dato.codigo_destino}, "
                f"{bloques.economic_context.source_trace.source_name})."
            )
        else:
            razones.append(
                f"Destino económico disponible: "
                f"({bloques.economic_context.source_trace.source_name})."
            )

    if bloques.normative_evidence.items:
        puntos += PUNTOS_EVIDENCIA
        reglas.append("r_normativa")
        cantidad = len(bloques.normative_evidence.items)
        plural = "s" if cantidad != 1 else ""
        razones.append(
            f"Evidencia normativa recuperada: {cantidad} artículo{plural} del POT "
            f"({bloques.normative_evidence.source_trace.source_name})."
        )

    # Contexto socioeconomico disponible: mas datos = mejor confidence (F6)
    if bloques.socioeconomic_context.estado == "disponible":
        puntos += PUNTOS_CONTEXTO_SOCIO
        reglas.append("r_contexto_socio")
        razones.append(
            "Contexto socioeconómico disponible: más datos para evaluar factibilidad."
        )

    # Acceso a movilidad con al menos una estacion (F6)
    if (
        bloques.transit_access.estado == "disponible"
        and bloques.transit_access.dato is not None
        and (
            (bloques.transit_access.dato.estaciones_transmilenio or 0) > 0
            or (bloques.transit_access.dato.estaciones_metro or 0) > 0
        )
    ):
        puntos += PUNTOS_ACCESO_MOVILIDAD
        reglas.append("r_acceso_movilidad")
        razones.append(
            "Acceso a transporte público disponible: estaciones de TransMilenio o Metro cercanas."
        )

    return puntos, reglas, razones


def _reglas_negativas(
    bloques: BloquesEvaluables,
) -> tuple[int, list[str], list[str]]:
    """Reglas negativas (research D3): puntos, codigos, razones."""
    puntos = 0
    reglas: list[str] = []
    razones: list[str] = []

    if (
        bloques.planning_constraints.estado == "disponible"
        and bloques.planning_constraints.dato is not None
        and bloques.planning_constraints.dato.afecta_lote is True
    ):
        puntos += PENALIZACION_RESERVA_VIAL
        reglas.append("r_reserva_vial")
        razones.append(
            f"Reserva vial afecta al lote: penalización −{PENALIZACION_RESERVA_VIAL} "
            f"({bloques.planning_constraints.source_trace.source_name})."
        )

    if bloques.administrative_context.upl is None:
        puntos += PENALIZACION_UPL_AUSENTE
        reglas.append("r_upl_ausente")
        razones.append(f"UPL ausente: penalización −{PENALIZACION_UPL_AUSENTE}.")

    bloque_no_encontrado = False
    for nombre, bloque in _bloques_con_estado(bloques):
        if bloque.estado == "no_encontrado":
            bloque_no_encontrado = True
            puntos += PENALIZACION_BLOQUE_NO_ENCONTRADO
            razones.append(
                f"Bloque {nombre} no encontrado: penalización "
                f"−{PENALIZACION_BLOQUE_NO_ENCONTRADO} "
                f"({bloque.source_trace.source_name})."
            )
    if bloque_no_encontrado:
        reglas.append("r_no_encontrado")

    if not bloques.normative_evidence.items:
        puntos += PENALIZACION_EVIDENCIA_VACIA
        reglas.append("r_evidencia_vacia")
        razones.append(
            f"Evidencia normativa vacía: penalización −{PENALIZACION_EVIDENCIA_VACIA}."
        )

    # Riesgo geotecnico alto: penalizacion fuerte (F6)
    if (
        bloques.geotechnical_risks.estado == "disponible"
        and bloques.geotechnical_risks.dato is not None
        and bloques.geotechnical_risks.dato.nivel_amenaza == "alto"
    ):
        puntos += PENALIZACION_RIESGO_GEOTECNICO_ALTO
        reglas.append("r_riesgo_geotec_alto")
        razones.append(
            f"Riesgo geotécnico alto: penalización −{PENALIZACION_RIESGO_GEOTECNICO_ALTO}."
        )

    # Patrimonio cultural: penalizacion si BIC o zona arqueologica (F6)
    if bloques.cultural_heritage.estado == "disponible" and bloques.cultural_heritage.dato is not None:
        tiene_patrimonio = (
            bloques.cultural_heritage.dato.bic_cercano is True
            or bloques.cultural_heritage.dato.zona_arqueologica is True
        )
        if tiene_patrimonio:
            puntos += PENALIZACION_PATRIMONIO_CULTURAL
            reglas.append("r_patrimonio_cultural")
            razones.append(
                f"Elementos de patrimonio cultural cercanos: penalización −{PENALIZACION_PATRIMONIO_CULTURAL}."
            )

    return puntos, reglas, razones


def _bloques_con_estado(
    bloques: BloquesEvaluables,
) -> list[tuple[str, Any]]:
    """Pares (nombre, bloque) de los bloques con patron {estado, dato, ...}."""
    return [
        ("planning_constraints", bloques.planning_constraints),
        ("market_context", bloques.market_context),
        ("environment_context", bloques.environment_context),
        ("economic_context", bloques.economic_context),
        ("geotechnical_risks", bloques.geotechnical_risks),
        ("socioeconomic_context", bloques.socioeconomic_context),
        ("regulatory_environment", bloques.regulatory_environment),
        ("cultural_heritage", bloques.cultural_heritage),
        ("transit_access", bloques.transit_access),
        ("catastro_data", bloques.catastro_data),
    ]


def _confidence_por_cobertura(bloques: BloquesEvaluables) -> Literal["high", "medium", "low"]:
    """Confidence por cobertura de los 6 bloques evaluables (data-model.md:221-223).

    Disponible = bloque con dato (upl o localidad, estado == "disponible",
    items no vacios). high >= 5, medium 3-4, low <= 2.
    """
    disponibles = _contar_bloques_disponibles(bloques)
    if disponibles >= 5:
        return "high"
    if disponibles >= 3:
        return "medium"
    return "low"


def _contar_bloques_disponibles(bloques: BloquesEvaluables) -> int:
    return sum(
        [
            bloques.administrative_context.upl is not None
            or bloques.administrative_context.localidad is not None,
            bloques.planning_constraints.estado == "disponible",
            bloques.market_context.estado == "disponible",
            bloques.environment_context.estado == "disponible",
            bloques.economic_context.estado == "disponible",
            bloques.geotechnical_risks.estado == "disponible",
            bloques.socioeconomic_context.estado == "disponible",
            bloques.regulatory_environment.estado == "disponible",
            bloques.cultural_heritage.estado == "disponible",
            bloques.transit_access.estado == "disponible",
            bloques.catastro_data.estado == "disponible",
            bool(bloques.normative_evidence.items),
        ]
    )


def _reasons_datos_faltantes(bloques: BloquesEvaluables) -> list[str]:
    """Enumera los bloques ausentes cuando confidence es low (escenario US3.2)."""
    disponibles = {
        "administrative_context": bloques.administrative_context.upl is not None
        or bloques.administrative_context.localidad is not None,
        "planning_constraints": bloques.planning_constraints.estado == "disponible",
        "market_context": bloques.market_context.estado == "disponible",
        "environment_context": bloques.environment_context.estado == "disponible",
        "economic_context": bloques.economic_context.estado == "disponible",
        "geotechnical_risks": bloques.geotechnical_risks.estado == "disponible",
        "socioeconomic_context": bloques.socioeconomic_context.estado == "disponible",
        "regulatory_environment": bloques.regulatory_environment.estado == "disponible",
        "cultural_heritage": bloques.cultural_heritage.estado == "disponible",
        "transit_access": bloques.transit_access.estado == "disponible",
        "catastro_data": bloques.catastro_data.estado == "disponible",
        "normative_evidence": bool(bloques.normative_evidence.items),
    }
    return [f"Dato faltante: {nombre}." for nombre in BLOQUES_EVALUABLES if not disponibles[nombre]]


def _clamp(valor: int) -> int:
    """Clamp entero 0-100 (FR-006)."""
    return max(0, min(100, valor))


def _formatear_numero(valor: float) -> str:
    """Formato determinista del numero para las reasons (4500000.0 -> "4500000")."""
    if float(valor).is_integer():
        return str(int(valor))
    return str(valor)
