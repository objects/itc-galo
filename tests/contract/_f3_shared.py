"""Constantes compartidas de los contract tests F3 (DRY entre archivos de tests).

Evita duplicar `CAMPOS_TRAZA` / `BLOQUES_RAIZ` / `BLOQUES_CON_ESTADO` en cada
archivo: un solo lugar de verdad para el shape del reporte del contrato.
"""

# Campos obligatorios del source_trace (5, contrato get-feasibility-report.md).
CAMPOS_TRAZA = {
    "source_name",
    "layer_id",
    "service_url",
    "data_vigencia",
    "query_timestamp",
}

# Los 17 bloques raiz del reporte (FR-001, F3 + F5 + F7 + F8).
BLOQUES_RAIZ = {
    "lot_identity",
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
    "urbanistic_parameters",
    "normative_evidence",
    "feasibility_score",
    "warnings",
    "query_timestamp",
}

# Bloques con el patron {estado, dato, interpretation, source_trace} (FR-004/FR-005).
BLOQUES_CON_ESTADO = {
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
    "urbanistic_parameters",
}

# Bloques multifuente que ademas publican `source_traces` (procedencia por
# sub-fuente, hallazgo M4): una traza por capa exitosa con su vigencia propia.
BLOQUES_MULTIFUENTE = {
    "geotechnical_risks",
    "socioeconomic_context",
    "regulatory_environment",
    "cultural_heritage",
    "transit_access",
    "catastro_data",
}
