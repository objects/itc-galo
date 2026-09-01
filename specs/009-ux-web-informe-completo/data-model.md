# Data Model: UX Web Informe Completo

Este feature NO añade modelos nuevos al dominio. Consumé los modelos existentes de `app/models.py` para renderizarlos en el template.

## Modelos consumidos por el template

### InformeFactibilidad (raíz)

Campos del informe serializado a dict por FastAPI/JSON:

| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| lot_identity | IdentidadLote | Sí | Identidad y geometría del lote |
| administrative_context | ContextoAdministrativo | Sí | UPL, localidad, clasificación |
| planning_constraints | BloqueReservaVial | Sí | Reserva vial |
| market_context | BloqueValorReferencia | Sí | Valor catastral |
| environment_context | BloqueObrasPublicas | Sí | Obras públicas cercanas |
| economic_context | BloqueDestinoEconomico | Sí | Destino económico |
| geotechnical_risks | BloqueRiesgosGeotecnicos | Sí | Riesgos geotécnicos |
| socioeconomic_context | BloqueContextoSocioeconomico | Sí | Contexto socioeconómico |
| regulatory_environment | BloqueEntornoRegulatorio | Sí | Entorno regulatorio |
| cultural_heritage | BloquePatrimonioCultural | Sí | Patrimonio cultural |
| transit_access | BloqueAccesoMovilidad | Sí | Acceso a movilidad |
| catastro_data | BloqueCatastroData | Sí | Datos catastrales |
| urbanistic_parameters | BloqueParametrosUrbanisticos | No | Parámetros urbanísticos |
| public_space_context | BloqueEspacioPublico | No | Espacio público |
| road_network_context | BloqueRedVial | No | Red vial |
| nearby_facilities | BloqueEquipamientosCercanos | No | Equipamientos cercanos |
| normative_evidence | EvidenciaNormativa | Sí | Evidencia del POT |
| feasibility_score | FeasibilityScore | Sí | Score heurístico |
| warnings | list[Warning] | Sí | Advertencias |
| llm_ready_summary | str | No | Resumen ejecutivo |
| query_timestamp | str | Sí | Timestamp ISO |

### Bloques con patrón `{estado, dato, interpretation, source_trace}`

Cada bloque evaluable sigue el mismo patrón:

- `estado`: `"disponible"` | `"no_encontrado"`
- `dato`: el contenido del bloque (modelos específicos) o `None`
- `interpretation`: texto descriptivo en español
- `source_trace`: `{source_name, layer_id, service_url, data_vigencia, query_timestamp}`
- `source_traces`: lista adicional para bloques multifuente (opcional)

### Warning

```python
Warning(codigo: str, mensaje: str)
```

Códigos: `LOTE_SIN_CHIP`, `UPL_NO_ENCONTRADA`, `LOCALIDAD_NO_DERIVADA`, `BLOQUE_SIN_DATO`, `NORMATIVA_NO_DISPONIBLE`, `NORMATIVA_SIN_RESULTADOS`, `BLOQUE_DEGRADADO`.

### FeasibilityScore

```python
FeasibilityScore(score: int, confidence: str, reasons: list[str], rules_applied: list[str])
```

### EvidenciaNormativa

```python
EvidenciaNormativa(items: list[ItemEvidenciaNormativa], consulta: str, ...)
ItemEvidenciaNormativa(articulo: str, titulo: str, libro: str, parte: str, texto_cita: str, norma: str, ...)
```
