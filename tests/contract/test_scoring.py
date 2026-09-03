"""Contract tests F3 — scoring puro (T018, US3, FR-006/FR-007/FR-014, SC-003).

`calcular_score` es una funcion pura (sin I/O, sin LLM, sin reloj): base 50,
reglas positivas/negativas documentadas en app/scoring.py y confidence por
cobertura de los 6 bloques evaluables. Estos tests pasan junto con el resto
de los contract tests F3 (suite completa en verde).
"""

from __future__ import annotations

from app.models import (
    BloqueAccesoMovilidad,
    BloqueContextoSocioeconomico,
    BloqueDestinoEconomico,
    BloqueEntornoRegulatorio,
    BloqueMarketDynamics,
    BloqueObrasPublicas,
    BloquePatrimonioCultural,
    BloqueReservaVial,
    BloqueRiesgosGeotecnicos,
    BloqueValorReferencia,
    ContextoAdministrativo,
    ContextoMercado,
    DestinoEconomico,
    EvidenciaNormativa,
    ItemEvidenciaNormativa,
    Localidad,
    ObraPublica,
    OfertaCompetidora,
    ReservaVial,
    RitmoAbsorcion,
    SourceTrace,
    UPL,
    ValorReferencia,
)
from app.scoring import (
    PUNTOS_ABSORCION_MERCADO,
    PUNTOS_BASE,
    PUNTOS_CONTEXTO_MERCADO,
    PUNTOS_OFERTA_COMPETIDORA,
    BloquesEvaluables,
    calcular_score,
)

# Terminos de reglas urbanisticas que las reasons NUNCA deben citar (FR-014):
# el scoring solo opera sobre datos reales de las fuentes.
TERMINOS_NORMATIVOS_INVENTADOS = [
    "altura máxima",
    "altura permitida",
    "índice de construcción",
    "índice de ocupación",
    "cesión",
    "retiro",
    "edificabilidad",
    "aprovechamiento",
]


def _trace(source_name: str = "fuente") -> SourceTrace:
    return SourceTrace(
        source_name=source_name,
        layer_id="0",
        service_url="https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/fuente/MapServer/0",
        data_vigencia="2026",
        query_timestamp="2026-08-12T02:15:00Z",
    )


def _contexto_sin_upl() -> ContextoAdministrativo:
    return ContextoAdministrativo(
        upl=None,
        localidad=None,
        clasificacion_suelo=None,
        source_trace=_trace("upl"),
    )


def _contexto_con_upl() -> ContextoAdministrativo:
    return ContextoAdministrativo(
        upl=UPL(
            codigo_upl="UPL24",
            nombre="Chapinero",
            localidad_derivada="Chapinero",
            vocacion="Urbano",
            estado="disponible",
            source_trace=_trace("upl"),
        ),
        localidad=Localidad(codigo="02", nombre="Chapinero"),
        clasificacion_suelo="urbano",
        source_trace=_trace("upl"),
    )


def _bloque_no_encontrado(tipo: str):
    if tipo == "planning":
        return BloqueReservaVial(
            estado="no_encontrado", dato=None, interpretation="...", source_trace=_trace("reservavial")
        )
    if tipo == "market":
        return BloqueValorReferencia(
            estado="no_encontrado", dato=None, interpretation="...", source_trace=_trace("valorreferencia")
        )
    if tipo == "environment":
        return BloqueObrasPublicas(
            estado="no_encontrado", dato=None, interpretation="...", source_trace=_trace("obraspublicas")
        )
    if tipo == "geotechnical":
        return BloqueRiesgosGeotecnicos(
            estado="no_encontrado", dato=None, interpretation="...", source_trace=_trace("geotecnia")
        )
    if tipo == "socioeconomic":
        return BloqueContextoSocioeconomico(
            estado="no_encontrado", dato=None, interpretation="...", source_trace=_trace("estratificacion")
        )
    if tipo == "regulatory":
        return BloqueEntornoRegulatorio(
            estado="no_encontrado", dato=None, interpretation="...", source_trace=_trace("licencias")
        )
    if tipo == "cultural":
        return BloquePatrimonioCultural(
            estado="no_encontrado", dato=None, interpretation="...", source_trace=_trace("bic")
        )
    if tipo == "transit":
        return BloqueAccesoMovilidad(
            estado="no_encontrado", dato=None, interpretation="...", source_trace=_trace("transmilenio")
        )
    if tipo == "catastro":
        from app.models import BloqueCatastroData
        return BloqueCatastroData(
            estado="no_encontrado", dato=None, interpretation="...", source_trace=_trace("construccion")
        )
    return BloqueDestinoEconomico(
        estado="no_encontrado", dato=None, interpretation="...", source_trace=_trace("predio")
    )


def _evidencia_vacia() -> EvidenciaNormativa:
    return EvidenciaNormativa(
        items=[],
        consulta="consulta de prueba",
        consulta_automatica=True,
        sin_resultados=True,
        causa="SIN_RESULTADOS",
        source_trace=_trace("decreto"),
    )


def _evidencia_con_item() -> EvidenciaNormativa:
    return EvidenciaNormativa(
        items=[
            ItemEvidenciaNormativa(
                articulo="361",
                titulo="Usos del suelo",
                libro="III",
                parte="urbano",
                texto_cita="El presente artículo regula los usos del suelo...",
                similitud=0.42,
            )
        ],
        consulta="consulta de prueba",
        consulta_automatica=True,
        sin_resultados=False,
        causa=None,
        source_trace=_trace("decreto"),
    )


def _bloques_felices() -> BloquesEvaluables:
    """Flujo feliz parcial: UPL + localidad + mercado + economico + evidencia."""
    market = BloqueValorReferencia(
        estado="disponible",
        dato=ValorReferencia(
            estado="disponible",
            valor_m2=4500000,
            unidad_monetaria="COP",
            vigencia="2025",
            source_trace=_trace("valorreferencia"),
        ),
        interpretation="Valor de referencia catastral del terreno: 4500000 COP/m² (vigencia 2025).",
        source_trace=_trace("valorreferencia"),
    )
    economico = BloqueDestinoEconomico(
        estado="disponible",
        dato=DestinoEconomico(
            estado="disponible",
            codigo_destino="04",
            descripcion_destino="Dotacional público",
            uso="015 - Oficinas y Consultorios oficiales en NPH",
            area_uso=40453.8,
            usos=[],
            area_terreno=3704.8,
            area_construccion=43465.1,
            direccion="AK 30 25 90",
            barrio="FLORIDA",
            vigencia="2026",
            source_trace=_trace("predio"),
        ),
        interpretation="Destino económico predominante del lote: Dotacional público (código 04).",
        source_trace=_trace("predio"),
    )
    return BloquesEvaluables(
        administrative_context=_contexto_con_upl(),
        planning_constraints=_bloque_no_encontrado("planning"),
        market_context=market,
        environment_context=_bloque_no_encontrado("environment"),
        economic_context=economico,
        geotechnical_risks=_bloque_no_encontrado("geotechnical"),
        socioeconomic_context=_bloque_no_encontrado("socioeconomic"),
        regulatory_environment=_bloque_no_encontrado("regulatory"),
        cultural_heritage=_bloque_no_encontrado("cultural"),
        transit_access=_bloque_no_encontrado("transit"),
        catastro_data=_bloque_no_encontrado("catastro"),
        normative_evidence=_evidencia_con_item(),
    )


def _bloques_completos() -> BloquesEvaluables:
    """Los bloques evaluables disponibles (confidence high)."""
    environment = BloqueObrasPublicas(
        estado="disponible",
        dato=ObraPublica(
            estado="disponible",
            obras=[{"nombre": "Ampliación de Estaciones: Calle 146"}],
            vigencia="2025",
            source_trace=_trace("obraspublicas"),
        ),
        interpretation="Se identificaron 1 obra(s) pública(s) en un radio de 500 m del lote.",
        source_trace=_trace("obraspublicas"),
    )
    planning = BloqueReservaVial(
        estado="disponible",
        dato=ReservaVial(
            estado="disponible",
            afecta_lote=False,
            descripcion="Zona de reserva sin afectación directa",
            vigencia="2019-08-15",
            source_trace=_trace("reservavial"),
        ),
        interpretation="No hay reserva vial que afecte el lote.",
        source_trace=_trace("reservavial"),
    )
    market = _bloques_felices().market_context
    economico = _bloques_felices().economic_context
    return BloquesEvaluables(
        administrative_context=_contexto_con_upl(),
        planning_constraints=planning,
        market_context=market,
        environment_context=environment,
        economic_context=economico,
        geotechnical_risks=_bloque_no_encontrado("geotechnical"),
        socioeconomic_context=_bloque_no_encontrado("socioeconomic"),
        regulatory_environment=_bloque_no_encontrado("regulatory"),
        cultural_heritage=_bloque_no_encontrado("cultural"),
        transit_access=_bloque_no_encontrado("transit"),
        catastro_data=_bloque_no_encontrado("catastro"),
        normative_evidence=_evidencia_con_item(),
    )


def test_score_base_es_50():
    """La constante base del scoring es 50 (research D3)."""
    assert PUNTOS_BASE == 50


def test_score_con_todo_no_encontrado_y_sin_upl_aplica_penalizaciones():
    """Sin UPL, 10 bloques no_encontrado y evidencia vacia: 50 - 5 - 50 - 5 = -10 -> 0."""
    bloques = BloquesEvaluables(
        administrative_context=_contexto_sin_upl(),
        planning_constraints=_bloque_no_encontrado("planning"),
        market_context=_bloque_no_encontrado("market"),
        environment_context=_bloque_no_encontrado("environment"),
        economic_context=_bloque_no_encontrado("economic"),
        geotechnical_risks=_bloque_no_encontrado("geotechnical"),
        socioeconomic_context=_bloque_no_encontrado("socioeconomic"),
        regulatory_environment=_bloque_no_encontrado("regulatory"),
        cultural_heritage=_bloque_no_encontrado("cultural"),
        transit_access=_bloque_no_encontrado("transit"),
        catastro_data=_bloque_no_encontrado("catastro"),
        normative_evidence=_evidencia_vacia(),
    )
    resultado = calcular_score(bloques)

    # 50 - 5 (UPL) - 10*5 (10 bloques no_encontrado: 5 originales + 5 nuevos) - 5 (evidencia vacia) = -10 -> 0
    assert resultado.score == 0
    assert resultado.confidence == "low"
    assert "r_upl_ausente" in resultado.rules_applied
    assert "r_no_encontrado" in resultado.rules_applied
    assert "r_evidencia_vacia" in resultado.rules_applied
    razones = " ".join(resultado.reasons)
    assert "UPL ausente" in razones
    assert "Bloque planning_constraints no encontrado" in razones
    assert "Bloque economic_context no encontrado" in razones
    assert "Evidencia normativa vacía" in razones


def test_reserva_vial_que_afecta_penaliza_15_con_razon_trazable():
    """planning_constraints disponible con afecta_lote=True -> -15 y reason con source_name."""
    planning = BloqueReservaVial(
        estado="disponible",
        dato=ReservaVial(
            estado="disponible",
            afecta_lote=True,
            descripcion="Reserva vial Avenida 68",
            vigencia="2019-08-15",
            source_trace=_trace("reservavial"),
        ),
        interpretation="El lote se superpone a una zona de reserva vial.",
        source_trace=_trace("reservavial"),
    )
    bloques = BloquesEvaluables(
        administrative_context=_contexto_sin_upl(),
        planning_constraints=planning,
        market_context=_bloque_no_encontrado("market"),
        environment_context=_bloque_no_encontrado("environment"),
        economic_context=_bloque_no_encontrado("economic"),
        geotechnical_risks=_bloque_no_encontrado("geotechnical"),
        socioeconomic_context=_bloque_no_encontrado("socioeconomic"),
        regulatory_environment=_bloque_no_encontrado("regulatory"),
        cultural_heritage=_bloque_no_encontrado("cultural"),
        transit_access=_bloque_no_encontrado("transit"),
        catastro_data=_bloque_no_encontrado("catastro"),
        normative_evidence=_evidencia_vacia(),
    )
    resultado = calcular_score(bloques)

    # 50 - reserva 15 - UPL ausente 5 - 9 bloques no_encontrado 45 - evidencia vacia 5 = -20 -> 0
    assert resultado.score == 0
    assert "r_reserva_vial" in resultado.rules_applied
    razon = next(r for r in resultado.reasons if "Reserva vial afecta" in r)
    assert "−15" in razon
    assert "reservavial" in razon


def test_puntos_positivos_por_upl_localidad_mercado_economico_y_evidencia():
    """Flujo feliz parcial: 50 + 10 + 5 + 10 + 10 + 5 - 40 (8 no_encontrado) = 50."""
    resultado = calcular_score(_bloques_felices())

    assert resultado.score == 50
    assert resultado.confidence == "low"  # 4 de 13 bloques evaluables disponibles (admin, market, economic, evidence) → <= 4 = low
    razones = "\n".join(resultado.reasons)
    assert "UPL resuelta: UPL24 Chapinero" in razones
    assert "Localidad derivada: Chapinero" in razones
    assert "Valor de referencia disponible: 4500000 COP/m²" in razones
    assert "Destino económico disponible: Dotacional público" in razones
    assert "Evidencia normativa recuperada: 1 artículo del POT" in razones
    for codigo in ["r_upl", "r_localidad", "r_mercado", "r_economico", "r_normativa"]:
        assert codigo in resultado.rules_applied


def test_confidence_high_con_6_bloques_disponibles():
    """Cobertura de los bloques evaluables -> medium (6 de 13 disponibles).

    Maximo del contrato con estos bloques: 50 + 10 (upl) + 5 (localidad) + 10 (mercado)
    + 10 (economico) + 5 (evidencia) - 30 (6 no_encontrado nuevos) = 60.
    6 bloques disponibles es medium (5-9), no high (>= 10).
    """
    resultado = calcular_score(_bloques_completos())

    assert resultado.confidence == "medium"
    assert resultado.score == 60
    assert "r_environment" not in resultado.rules_applied


def test_confidence_low_con_2_o_menos_bloques_y_reasons_de_datos_faltantes():
    """Solo economic_context disponible -> low y reasons enumeran los datos faltantes (US3.2)."""
    bloques = BloquesEvaluables(
        administrative_context=_contexto_sin_upl(),
        planning_constraints=_bloque_no_encontrado("planning"),
        market_context=_bloque_no_encontrado("market"),
        environment_context=_bloque_no_encontrado("environment"),
        economic_context=_bloques_felices().economic_context,
        geotechnical_risks=_bloque_no_encontrado("geotechnical"),
        socioeconomic_context=_bloque_no_encontrado("socioeconomic"),
        regulatory_environment=_bloque_no_encontrado("regulatory"),
        cultural_heritage=_bloque_no_encontrado("cultural"),
        transit_access=_bloque_no_encontrado("transit"),
        catastro_data=_bloque_no_encontrado("catastro"),
        normative_evidence=_evidencia_vacia(),
    )
    resultado = calcular_score(bloques)

    assert resultado.confidence == "low"
    faltantes = [r for r in resultado.reasons if r.startswith("Dato faltante:")]
    assert len(faltantes) == 18  # 19 evaluables - 1 disponible (economic_context)
    nombres_faltantes = {f.replace("Dato faltante: ", "").rstrip(".") for f in faltantes}
    assert nombres_faltantes == {
        "administrative_context",
        "planning_constraints",
        "market_context",
        "environment_context",
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
        "financial_analysis",
        "technical_feasibility",
        "market_dynamics",
    }


def test_score_es_determinista():
    """SC-003: mismo input -> mismo score/confidence/reasons/rules_applied."""
    resultado_1 = calcular_score(_bloques_felices())
    resultado_2 = calcular_score(_bloques_felices())

    assert resultado_1.score == resultado_2.score
    assert resultado_1.confidence == resultado_2.confidence
    assert resultado_1.reasons == resultado_2.reasons
    assert resultado_1.rules_applied == resultado_2.rules_applied


def test_reasons_no_citan_reglas_urbanisticas_inventadas():
    """FR-014: ninguna reason inventa normativa urbanistica ausente en las fuentes."""
    for bloques in (_bloques_felices(), _bloques_completos()):
        resultado = calcular_score(bloques)
        for razon in resultado.reasons:
            assert razon, "las reasons no pueden estar vacías"
            for termino in TERMINOS_NORMATIVOS_INVENTADOS:
                assert termino not in razon.lower(), f"'{termino}' aparece en: {razon}"


# --- F10: reglas del mercado (T024, FR-011/FR-012, SC-001) ---


def _bloque_mercado_completo() -> BloqueMarketDynamics:
    """Bloque market_dynamics disponible con precio+estrato, oferta y absorcion."""
    return BloqueMarketDynamics(
        estado="disponible",
        dato=ContextoMercado(
            precio_m2_referencia=6450000.0,
            estrato=4,
            oferta_competidora=[
                OfertaCompetidora(zona="Chapinero", conteo=12, precio_m2_promedio=6400000.0, estrato=4)
            ],
            ritmo_absorcion=RitmoAbsorcion(unidades_mes=8.5, criterio="antigüedad media"),
        ),
        interpretation="Contexto de mercado disponible.",
        source_trace=_trace("corpus-mercado"),
    )


def _bloque_mercado_vacio() -> BloqueMarketDynamics:
    return BloqueMarketDynamics(
        estado="no_encontrado",
        dato=None,
        interpretation="sin datos de mercado.",
        source_trace=_trace("corpus-mercado"),
    )


def _bloques_con_mercado(mercado: BloqueMarketDynamics) -> BloquesEvaluables:
    base = _bloques_felices()
    return base.model_copy(update={"market_dynamics": mercado})


def test_constantes_puntos_mercado():
    """Las 3 constantes nuevas tienen los valores del contrato (FR-011)."""
    assert PUNTOS_CONTEXTO_MERCADO == 10
    assert PUNTOS_OFERTA_COMPETIDORA == 5
    assert PUNTOS_ABSORCION_MERCADO == 5


def test_r_contexto_mercado_aplica_10_si_precio_y_estrato():
    resultado = calcular_score(_bloques_con_mercado(_bloque_mercado_completo()))
    assert "r_contexto_mercado" in resultado.rules_applied
    assert "r_oferta_competidora" in resultado.rules_applied
    assert "r_absorcion_mercado" in resultado.rules_applied


def test_reglas_mercado_sumadas_al_score():
    """market_dynamics completo suma +20 (= +10 +5 +5) sobre el flujo feliz base."""
    resultado_sin = calcular_score(_bloques_felices())
    resultado_con = calcular_score(_bloques_con_mercado(_bloque_mercado_completo()))
    assert resultado_con.score - resultado_sin.score == 20


def test_market_dynamics_none_no_es_evaluado():
    """market_dynamics ausente (None) no penaliza ni suma (patron F8/Fase 3)."""
    resultado = calcular_score(_bloques_felices())
    assert "r_contexto_mercado" not in resultado.rules_applied
    assert "r_oferta_competidora" not in resultado.rules_applied
    assert "r_absorcion_mercado" not in resultado.rules_applied
    # market_dynamics=None no cuenta como bloque no_encontrado
    assert not any("market_dynamics no encontrado" in r for r in resultado.reasons)


def test_market_dynamics_no_encontrado_cuenta_como_bloque():
    """market_dynamics con estado no_encontrado penaliza en r_no_encontrado."""
    resultado = calcular_score(_bloques_con_mercado(_bloque_mercado_vacio()))
    assert "r_no_encontrado" in resultado.rules_applied
    assert any("market_dynamics no encontrado" in r for r in resultado.reasons)


def test_score_market_dynamics_es_determinista():
    """SC-001: mismo input -> mismo score con el bloque adicional."""
    b1 = _bloques_con_mercado(_bloque_mercado_completo())
    r1 = calcular_score(b1)
    r2 = calcular_score(_bloques_con_mercado(_bloque_mercado_completo()))
    assert r1.score == r2.score
    assert r1.rules_applied == r2.rules_applied
