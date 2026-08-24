"""Tests del extractor enriquecido de UPLs y del subcomando `enriquecer-upls`
(fase C: enriquecimiento de metadata UPL del corpus).

Cubre: códigos literales, nombres propios seguros (con/sin tildes), nombres
cualificados "UPL <nombre>", descarte de falsos positivos, determinismo,
cobertura completa del catálogo y el post-proceso del JSONL versionado.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.errores import CorpusNoIngestadoError
from app.ingesta.corpus import (
    NOMBRES_UPL_EXCLUIDOS_POR_AMBIGUEDAD,
    NOMBRES_UPL_SEGUROS,
    _extraer_upls,
    deserializar_corpus,
    enriquecer_upls_jsonl,
    hash_documento,
)
from app.models import ArticuloNormativo
from app.providers.upl import UPLS_BOGOTA


# --- Extractor enriquecido: capa 1 (códigos literales) ---


def test_extraer_upls_codigos_literales_con_y_sin_espacio():
    assert _extraer_upls("Usos del suelo en UPL17.") == ["UPL17"]
    assert _extraer_upls("Normas para la UPL 2 y la UPL 33.") == ["UPL02", "UPL33"]
    assert _extraer_upls("Edificabilidad UPL 2, UPL20 y UPL 33.") == [
        "UPL02",
        "UPL20",
        "UPL33",
    ]


def test_extraer_upls_deduplica_codigos_repetidos():
    assert _extraer_upls("la UPL20 y otra vez la UPL 20") == ["UPL20"]


def test_extraer_upls_sin_menciones_devuelve_lista_vacia():
    assert _extraer_upls("Texto sin ninguna unidad de planeamiento.") == []
    assert _extraer_upls("") == []


# --- Capa 2: nombres propios seguros ---


def test_extraer_upls_nombre_seguro_con_y_sin_tildes():
    # "Cerros Orientales" (UPL06): mayúsculas y tildes son irrelevantes.
    assert _extraer_upls("El parque de borde de los Cerros Orientales.") == ["UPL06"]
    assert _extraer_upls("los cerros orientales de Bogotá") == ["UPL06"]


def test_extraer_upls_nombre_seguro_compuesto_con_guion():
    # Variantes tipográficas del compuesto oficial "Usme - Entrenubes" (UPL05).
    assert _extraer_upls("el corredor Usme - Entrenubes") == ["UPL05"]
    assert _extraer_upls("el corredor Usme-Entrenubes") == ["UPL05"]
    assert _extraer_upls("el corredor usme entrenubes") == ["UPL05"]


def test_extraer_upls_nombre_seguro_no_matchea_dentro_de_otra_palabra():
    # Límites de palabra: "Tabora" dentro de un hipotético "Taborazo" no cuenta.
    assert _extraer_upls("vereda Taborazo") == []
    assert _extraer_upls("vereda Tabora") == ["UPL29"]


def test_extraer_upls_alias_suelto_entre_nubes_descartado():
    # El alias suelto "Entre Nubes" es homónimo del cerro/parque (art. 54 real):
    # solo matchea el compuesto oficial "Usme - Entrenubes".
    assert _extraer_upls("el cerro Entre Nubes") == []


def test_extraer_upls_falsos_positivos_descartados():
    # Casos REALES del corpus que NO deben etiquetarse como mención de UPL:
    assert _extraer_upls("la localidad de Suba y la de Bosa") == []  # localidades
    assert _extraer_upls("los ríos Tunjuelo, Fucha y Salitre") == []  # río Salitre
    assert _extraer_upls("humedales de Torca y Guaymaral") == []  # humedal homónimo
    assert _extraer_upls("Parque Nacional Natural Sumapaz") == []  # área protegida
    assert _extraer_upls("el porvenir de la ciudad") == []  # palabra común
    assert _extraer_upls("sectores como el Restrepo y el Ricaurte") == []  # barrios
    assert _extraer_upls("humedal de Córdoba y Niza") == []  # humedal homónimo


# --- Capa 3: nombres cualificados "UPL <nombre>" ---


def test_extraer_upls_nombre_cualificado_desambigua_excluidos():
    # El calificador "UPL" inmediato hace explícita la mención aunque el nombre
    # esté excluido del matcheo libre por ambigüedad.
    assert _extraer_upls("manzanas del cuidado en UPL Bosa") == ["UPL17"]
    assert _extraer_upls("en la UPL Kennedy") == ["UPL18"]
    assert _extraer_upls("upl tintal manzana 1") == ["UPL13"]
    assert _extraer_upls("en las UPL Sumapáz") == ["UPL01"]


def test_extraer_upls_nombre_cualificado_insensible_a_tildes():
    assert _extraer_upls("en la UPL San Cristóbal") == ["UPL21"]
    assert _extraer_upls("en la upl san cristobal") == ["UPL21"]


# --- Determinismo y cobertura del catálogo ---


def test_extraer_upls_es_determinista():
    texto = "Cerros Orientales, UPL 5 y UPL Bosa."
    assert _extraer_upls(texto) == _extraer_upls(texto)


def test_extraer_upls_resultado_ordenado_y_canonico():
    codigos = _extraer_upls("UPL Bosa, UPL 3 y Cuenca del Tunjuelo.")
    assert codigos == sorted(codigos)
    assert all(len(codigo) == 5 for codigo in codigos)


def test_catalogo_nombres_cubre_exactamente_las_33_upls():
    # Seguros + excluidos particionan el catálogo sin huecos ni solapes.
    total = set(NOMBRES_UPL_SEGUROS) | set(NOMBRES_UPL_EXCLUIDOS_POR_AMBIGUEDAD)
    assert total == set(UPLS_BOGOTA)
    assert not set(NOMBRES_UPL_SEGUROS) & set(NOMBRES_UPL_EXCLUIDOS_POR_AMBIGUEDAD)
    # Todo excluido está documentado con su justificación.
    for codigo, justificacion in NOMBRES_UPL_EXCLUIDOS_POR_AMBIGUEDAD.items():
        assert justificacion.strip()
        assert codigo in UPLS_BOGOTA


# --- Subcomando `enriquecer-upls`: post-proceso del JSONL ---


def _articulo(numero: int, titulo: str, texto: str) -> ArticuloNormativo:
    return ArticuloNormativo(
        numero=numero,
        titulo=titulo,
        texto=texto,
        libro="III",
        parte="urbano",
        upls_mencionadas=_extraer_upls(f"{titulo}\n{texto}"),
        articulos_derogados=[],
    )


def test_enriquecer_upls_jsonl_diff_correcto_y_sha256_regenerado(tmp_path):
    ruta = tmp_path / "corpus.jsonl"
    articulos = [
        _articulo(1, "Usos en Cerros Orientales.", "Protege los cerros orientales."),
        _articulo(2, "Norma urbana.", "Edificabilidad en la UPL 7."),
        _articulo(3, "Sin menciones.", "Texto neutro sin unidades."),
    ]
    # Persistir con upls VACÍAS para simular el corpus pre-enriquecido.
    lineas = []
    for articulo in articulos:
        dato = json.loads(articulo.model_dump_json())
        dato["upls_mencionadas"] = []
        lineas.append(json.dumps(dato, ensure_ascii=False, separators=(",", ":")))
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    ruta.with_name(ruta.name + ".sha256").write_text("hash-viejo", encoding="utf-8")

    reporte = enriquecer_upls_jsonl(str(ruta))

    assert reporte["articulos"] == 3
    assert reporte["cambiados"] == 2
    cambiados = {d["articulo"]: d for d in reporte["detalles"]}
    assert cambiados[1]["nuevas"] == ["UPL06"]
    assert cambiados[1]["agregadas"] == ["UPL06"]
    assert cambiados[2]["nuevas"] == ["UPL07"]
    assert 3 not in cambiados  # el artículo neutro no cambia

    corpus_actualizado = deserializar_corpus(str(ruta))
    assert corpus_actualizado[0].upls_mencionadas == ["UPL06"]
    assert corpus_actualizado[1].upls_mencionadas == ["UPL07"]
    assert corpus_actualizado[2].upls_mencionadas == []
    hash_esperado = hash_documento(corpus_actualizado)
    assert reporte["hash_sha256"] == hash_esperado
    assert (
        ruta.with_name(ruta.name + ".sha256").read_text(encoding="utf-8")
        == hash_esperado
    )


def test_enriquecer_upls_jsonl_idempotente(tmp_path):
    ruta = tmp_path / "corpus.jsonl"
    articulos = [_articulo(1, "Usos en Britalia.", "Sector Britalia.")]
    ruta.write_text(
        "\n".join(a.model_dump_json() for a in articulos) + "\n", encoding="utf-8"
    )

    primera = enriquecer_upls_jsonl(str(ruta))
    assert primera["cambiados"] == 0
    assert primera["hash_sha256"] is None
    # Segunda pasada sobre el archivo ya enriquecido: sin cambios.
    segunda = enriquecer_upls_jsonl(str(ruta))
    assert segunda["cambiados"] == 0


def test_enriquecer_upls_jsonl_conserva_lineas_sin_cambios_byte_a_byte(tmp_path):
    linea_inmutable = json.dumps(
        json.loads(_articulo(9, "Sin UPLs.", "Texto neutro.").model_dump_json()),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    linea_cambiable = json.dumps(
        {
            **json.loads(
                _articulo(12, "Perímetro urbano.", "Límite con los cerros orientales.").model_dump_json()
            ),
            "upls_mencionadas": [],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    ruta = tmp_path / "corpus.jsonl"
    ruta.write_text(f"{linea_inmutable}\n{linea_cambiable}\n", encoding="utf-8")

    enriquecer_upls_jsonl(str(ruta))

    lineas = ruta.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 2
    assert lineas[0] == linea_inmutable  # intacta
    dato = json.loads(lineas[1])
    assert dato["upls_mencionadas"] == ["UPL06"]
    # El resto de campos de la línea cambiada se conservan.
    assert dato["numero"] == 12
    assert dato["titulo"] == "Perímetro urbano."


def test_enriquecer_upls_jsonl_archivo_inexistente_falla_ruidoso(tmp_path):
    with pytest.raises(CorpusNoIngestadoError, match="No existe el archivo"):
        enriquecer_upls_jsonl(str(tmp_path / "inexistente.jsonl"))
