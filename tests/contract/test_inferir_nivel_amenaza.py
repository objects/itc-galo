"""Tests de _inferir_nivel_amenaza (hallazgo m1).

La capa gestionriesgos publica "Amenaza alta/media/baja" (adjetivo femenino
pospuesto); la version anterior solo matcheaba masculinos y perdian la
penalizacion -10 del scoring. La clasificacion ahora usa raices con limite de
palabra, insensible a genero/numero, sin falsos positivos ("altitud", etc.).
"""

from __future__ import annotations

import pytest

from app.providers.arcgis import _inferir_nivel_amenaza


@pytest.mark.parametrize(
    ("amenaza", "esperado"),
    [
        # Formas masculinas (comportamiento previo preservado)
        ("Amenaza alto", "alto"),
        ("Riesgo alto", "alto"),
        ("Amenaza media", "medio"),
        ("Nivel medio de amenaza", "medio"),
        ("Riesgo moderado", "medio"),
        ("Amenaza bajo", "bajo"),
        ("Condición normal", "bajo"),
        # Formas femeninas (el bug: adjetivo pospuesto)
        ("Amenaza Alta", "alto"),
        ("AMENAZA ALTA", "alto"),
        ("Zona de amenaza alta", "alto"),
        ("Amenaza media", "medio"),
        ("Clase Media", "medio"),
        ("Amenaza Baja", "bajo"),
        ("amenaza baja-media", "medio"),
        # Criticidad
        ("Zona crítica", "alto"),
        ("Amenaza critica", "alto"),
        # Plurales
        ("Amenazas altas", "alto"),
        ("Zonas bajas", "bajo"),
        # Sin dato o sin nivel reconocible: nunca se inventa (FR-014)
        (None, "desconocido"),
        ("", "desconocido"),
        ("texto sin nivel reconocible", "desconocido"),
        # Falsos positivos que los limites de palabra evitan
        ("altitud 2600 msnm", "desconocido"),
        ("Altura de talud", "desconocido"),
        ("remediación del terreno", "desconocido"),
        ("medianoche", "desconocido"),
    ],
)
def test_inferir_nivel_amenaza(amenaza, esperado):
    assert _inferir_nivel_amenaza(amenaza) == esperado


def test_nivel_mas_critico_gana_cuando_hay_varios():
    """Si el texto menciona varios niveles, domina el mas critico."""
    assert _inferir_nivel_amenaza("amenaza media-alta") == "alto"
