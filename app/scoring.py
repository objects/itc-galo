"""Scoring heuristico del informe de factibilidad (research D3, FR-006/FR-007).

Funcion pura `calcular_score(bloques) -> FeasibilityScore`: sin I/O, sin LLM,
sin reloj (SC-003: mismo input -> mismo score/confidence/reasons). Opera sobre
hechos de disponibilidad o afectacion declarados por las fuentes (FR-014):
ninguna regla inventa normativa urbanistica ausente.

Reglas (data-model.md:205-227, research D3):
- Base 50.
- Positivas: UPL resuelta +10; localidad derivada +5; market_context disponible
  +10; economic_context disponible +10; normative_evidence con items +5;
  urbanistic_parameters con tratamiento+edificabilidad +10;
  estacionamientos requeridos > 0 +5; espacio publico EPT >= 15 m2/hab +5
  (Fase 3); frente vial de jerarquia alta (avenida) +5 (Fase 3);
  equipamientos de salud/educacion cercanos +5 (Fase 3).
- Negativas: reserva vial que afecta el lote -15; UPL ausente -5; cada bloque
  tematico/economico en no_encontrado -5; evidencia normativa vacia -5;
  riesgo geotecncico alto -10; patrimonio cultural -10; tratamiento de
  conservacion -15.
- `score = clamp(50 + Σ, 0, 100)` entero.
- `confidence` por cobertura de los 16 bloques evaluables: high >= 10 disponibles,
  medium 5-9, low <= 4. Con confidence low, las reasons enumeran los faltantes.
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
    BloqueEquipamientosCercanos,
    BloqueEspacioPublico,
    BloqueObrasPublicas,
    BloqueParametrosUrbanisticos,
    BloquePatrimonioCultural,
    BloqueRedVial,
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
PUNTOS_PARAMETROS_URBANISTICOS = 10  # F8: parámetros urbanísticos disponibles
PUNTOS_ESTACIONAMIENTOS = 5  # F8: estacionamientos calculados
# Fase 3: espacio publico suficiente, frente vial de jerarquia alta y
# equipamientos cercanos (salud/educacion) en radio.
PUNTOS_ESPACIO_PUBLICO_SUFICIENTE = 5
UMBRAL_ESPACIO_PUBLICO_M2_HAB = 15.0  # estandar distrital de espacio publico (m2/hab)
PUNTOS_FRENTE_VIAL_AVENIDA = 5
PUNTOS_EQUIPAMIENTOS_CERCANOS = 5
PENALIZACION_RESERVA_VIAL = 15
PENALIZACION_UPL_AUSENTE = 5
PENALIZACION_BLOQUE_NO_ENCONTRADO = 5
PENALIZACION_EVIDENCIA_VACIA = 5
PENALIZACION_RIESGO_GEOTECNICO_ALTO = 10
PENALIZACION_PATRIMONIO_CULTURAL = 10
PENALIZACION_CONSERVACION = 15  # F8: tratamiento de conservación

# Los bloques evaluables del confidence (6 originales F3 + 6 nuevos F6/F7 + 1 F8
# + 3 nuevos Fase 3). Los umbrales de confidence (high >= 10, medium 5-9,
# low <= 4) se mantienen absolutos: miden cobertura minima suficiente, no una
# proporcion de la lista.
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
    "public_space_context",
    "road_network_context",
    "nearby_facilities",
    "normative_evidence",
    "urbanistic_parameters",
)


class BloquesEvaluables(BaseModel):
    """Estructura tipada de los bloques evaluables del score (data-model).

    Los bloques Fase 3 son opcionales (None = no evaluado, p. ej. en tests que
    construyen la estructura parcialmente): no penalizan ni cuentan para el
    confidence, mismo tratamiento de `urbanistic_parameters` desde F8.
    """

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
    public_space_context: BloqueEspacioPublico | None = None
    road_network_context: BloqueRedVial | None = None
    nearby_facilities: BloqueEquipamientosCercanos | None = None
    normative_evidence: EvidenciaNormativa
    urbanistic_parameters: BloqueParametrosUrbanisticos | None = None


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

    # --- F8: Parámetros urbanísticos del lote ---
    # Regla r_parametros_urbanisticos: tratamiento + edificabilidad disponibles.
    # El orquestador solo construye ParametrosEdificabilidad cuando extrajo al
    # menos un valor real (capa 14 SINUPOT o RAG); edificabilidad no None
    # implica datos reales (hallazgo M6 del code review).
    if (
        bloques.urbanistic_parameters is not None
        and bloques.urbanistic_parameters.estado == "disponible"
        and bloques.urbanistic_parameters.dato is not None
        and bloques.urbanistic_parameters.dato.tratamiento is not None
        and bloques.urbanistic_parameters.dato.edificabilidad is not None
    ):
        puntos += PUNTOS_PARAMETROS_URBANISTICOS
        reglas.append("r_parametros_urbanisticos")
        nombre_trat = bloques.urbanistic_parameters.dato.tratamiento.denominacion
        razones.append(
            f"Parámetros urbanísticos disponibles: tratamiento {nombre_trat} "
            f"con parámetros de edificabilidad (SINUPOT)."
        )

    # Regla r_estacionamientos_calculados: estacionamientos requeridos > 0
    if (
        bloques.urbanistic_parameters is not None
        and bloques.urbanistic_parameters.estado == "disponible"
        and bloques.urbanistic_parameters.dato is not None
        and bloques.urbanistic_parameters.dato.estacionamientos is not None
        and bloques.urbanistic_parameters.dato.estacionamientos.requeridos is not None
        and bloques.urbanistic_parameters.dato.estacionamientos.requeridos > 0
    ):
        puntos += PUNTOS_ESTACIONAMIENTOS
        reglas.append("r_estacionamientos_calculados")
        num_est = bloques.urbanistic_parameters.dato.estacionamientos.requeridos
        razones.append(
            f"Estacionamientos requeridos calculados: {num_est} "
            f"(criterio del POT)."
        )

    # --- Fase 3: espacio publico, frente vial y equipamientos cercanos ---

    # Regla r_espacio_publico_suficiente: EPT >= 15 m2/hab (estandar distrital
    # de espacio publico efectivo por habitante de la Defensoria del Espacio
    # Publico). Solo con dato real de la capa; sin dato no hay bonus.
    if (
        bloques.public_space_context is not None
        and bloques.public_space_context.estado == "disponible"
        and bloques.public_space_context.dato is not None
        and bloques.public_space_context.dato.ep_total_m2_hab is not None
        and bloques.public_space_context.dato.ep_total_m2_hab >= UMBRAL_ESPACIO_PUBLICO_M2_HAB
    ):
        puntos += PUNTOS_ESPACIO_PUBLICO_SUFICIENTE
        reglas.append("r_espacio_publico_suficiente")
        ept = bloques.public_space_context.dato.ep_total_m2_hab
        razones.append(
            f"Espacio público suficiente: {_formatear_numero(ept)} m²/hab en la UPL "
            f"(umbral {int(UMBRAL_ESPACIO_PUBLICO_M2_HAB)} m²/hab)."
        )

    # Regla r_frente_vial_avenida: via de jerarquia alta (avenida) en el frente.
    if (
        bloques.road_network_context is not None
        and bloques.road_network_context.estado == "disponible"
        and bloques.road_network_context.dato is not None
        and bloques.road_network_context.dato.jerarquia_maxima == "alta"
    ):
        puntos += PUNTOS_FRENTE_VIAL_AVENIDA
        reglas.append("r_frente_vial_avenida")
        razones.append(
            "Frente vial de jerarquía alta: el lote colinda con una avenida."
        )

    # Regla r_equipamientos_cercanos: al menos un equipamiento de salud o
    # educacion en radio (servicios esenciales de uso diario).
    if (
        bloques.nearby_facilities is not None
        and bloques.nearby_facilities.estado == "disponible"
        and bloques.nearby_facilities.dato is not None
        and (
            (bloques.nearby_facilities.dato.total_salud or 0) > 0
            or (bloques.nearby_facilities.dato.total_educacion or 0) > 0
        )
    ):
        puntos += PUNTOS_EQUIPAMIENTOS_CERCANOS
        reglas.append("r_equipamientos_cercanos")
        razones.append(
            "Equipamientos cercanos: salud o educación disponibles en el radio consultado."
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

    # --- F8: Penalización por tratamiento de conservación ---
    # Regla r_tratamiento_conservacion: tratamiento == "Conservación" -> −15
    if (
        bloques.urbanistic_parameters is not None
        and bloques.urbanistic_parameters.estado == "disponible"
        and bloques.urbanistic_parameters.dato is not None
        and bloques.urbanistic_parameters.dato.tratamiento is not None
        and bloques.urbanistic_parameters.dato.tratamiento.denominacion.lower() == "conservación"
    ):
        puntos += PENALIZACION_CONSERVACION
        reglas.append("r_tratamiento_conservacion")
        razones.append(
            f"Tratamiento de conservación: penalización −{PENALIZACION_CONSERVACION}."
        )

    return puntos, reglas, razones


def _bloques_con_estado(
    bloques: BloquesEvaluables,
) -> list[tuple[str, Any]]:
    """Pares (nombre, bloque) de los bloques con patron {estado, dato, ...}."""
    items = [
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
    # F8: urbanistic_parameters es opcional (puede ser None si el provider no
    # se inyecta); solo se incluye cuando está presente.
    if bloques.urbanistic_parameters is not None:
        items.append(("urbanistic_parameters", bloques.urbanistic_parameters))
    # Fase 3: los 3 bloques nuevos son opcionales (None = no evaluado); solo
    # se incluyen cuando están presentes, mismo tratamiento de F8.
    for nombre_fase3 in ("public_space_context", "road_network_context", "nearby_facilities"):
        bloque_fase3 = getattr(bloques, nombre_fase3)
        if bloque_fase3 is not None:
            items.append((nombre_fase3, bloque_fase3))
    return items


def _confidence_por_cobertura(bloques: BloquesEvaluables) -> Literal["high", "medium", "low"]:
    """Confidence por cobertura de los 16 bloques evaluables (data-model.md:102-108).

    Disponible = bloque con dato (upl o localidad, estado == "disponible",
    items no vacios). high >= 10, medium 5-9, low <= 4.
    """
    disponibles = _contar_bloques_disponibles(bloques)
    if disponibles >= 10:
        return "high"
    if disponibles >= 5:
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
            # F8: urbanistic_parameters disponible si tratamiento poblado
            bloques.urbanistic_parameters is not None
            and bloques.urbanistic_parameters.estado == "disponible",
            # Fase 3: los 3 bloques nuevos cuentan solo cuando están presentes
            _bloque_fase3_disponible(bloques, "public_space_context"),
            _bloque_fase3_disponible(bloques, "road_network_context"),
            _bloque_fase3_disponible(bloques, "nearby_facilities"),
        ]
    )


def _bloque_fase3_disponible(bloques: BloquesEvaluables, nombre: str) -> bool:
    """Disponibilidad de un bloque Fase 3 opcional (None = no evaluado -> False)."""
    bloque = getattr(bloques, nombre)
    return bloque is not None and bloque.estado == "disponible"


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
        "public_space_context": _bloque_fase3_disponible(bloques, "public_space_context"),
        "road_network_context": _bloque_fase3_disponible(bloques, "road_network_context"),
        "nearby_facilities": _bloque_fase3_disponible(bloques, "nearby_facilities"),
        "normative_evidence": bool(bloques.normative_evidence.items),
        "urbanistic_parameters": (
            bloques.urbanistic_parameters is not None
            and bloques.urbanistic_parameters.estado == "disponible"
        ),
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
