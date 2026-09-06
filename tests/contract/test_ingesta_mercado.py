"""Contract tests F10 — ingesta del corpus de mercado (T023, US2).

Verifica el fallback a seeds ante fallo de scoring, la validacion de rangos
(estrato 1-6, area >= 36, precio/area positivos), la deduplicacion por id
estable y la escritura JSONL + huella SHA-256 (FR-005/FR-006/FR-008, D5/D6).
Sin red real: el scraping usa httpx.MockTransport.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from app.ingesta.mercado import (
    consolidar_corpus,
    escribir_corpus,
    id_estable,
    ingerir_mercado,
    procesar_registros,
    validar_registro,
)
from app.models import RegistroOfertaInmobiliaria


def _seed_chapinero(precio=690000000, area=120, estrato=6) -> dict:
    return {
        "fuente": "seed",
        "url": None,
        "precio": precio,
        "area_m2": area,
        "estrato": estrato,
        "amenidades": ["garaje"],
        "localidad": "Chapinero",
        "upl": "UPL24",
        "barrio": "Chico Norte",
        "fecha_captura": "2026-01-15",
    }


# --- Validacion de rangos (FR-006) ---


def test_validar_registro_valido_devuelve_none():
    assert validar_registro(_seed_chapinero()) is None


def test_validar_rechaza_estrato_fuera_de_rango():
    assert validar_registro(_seed_chapinero(estrato=7)) is not None
    assert validar_registro(_seed_chapinero(estrato=0)) is not None


def test_validar_rechaza_area_menor_al_minimo_pot():
    assert validar_registro(_seed_chapinero(area=35)) is not None


def test_validar_rechaza_precio_o_area_no_positivos():
    assert validar_registro(_seed_chapinero(precio=0)) is not None
    assert validar_registro(_seed_chapinero(area=0)) is not None


def test_validar_rechaza_sin_precio_o_sin_area():
    sin_precio = _seed_chapinero()
    del sin_precio["precio"]
    assert validar_registro(sin_precio) is not None
    sin_area = _seed_chapinero()
    del sin_area["area_m2"]
    assert validar_registro(sin_area) is not None


# --- Deduplicacion por id estable (D6) ---


def test_id_estable_determinista_para_mismo_registro():
    r1 = _seed_chapinero()
    r2 = _seed_chapinero()
    assert id_estable(r1) == id_estable(r2)


def test_id_estable_usa_url_si_presente():
    con_url = _seed_chapinero()
    con_url["url"] = "https://portal.example.com/oferta/123"
    sin_url = _seed_chapinero()
    assert id_estable(con_url) != id_estable(sin_url)


def test_procesar_registros_deduplica_por_id():
    duplicado = _seed_chapinero()
    registros = [_seed_chapinero(), duplicado, _seed_chapinero()]  # 3 iguales
    validos, motivos = procesar_registros(registros)
    assert len(validos) == 1
    assert motivos == []


def test_procesar_registros_descarta_invalidos_con_motivo_deduplicado():
    registros = [
        _seed_chapinero(estrato=9),
        _seed_chapinero(estrato=9),  # mismo motivo
        _seed_chapinero(area=10),
    ]
    validos, motivos = procesar_registros(registros)
    assert validos == []
    # motivos deduplicados: "estrato 9..." + "area 10..." = 2 unicos
    assert len(motivos) == 2


# --- Escritura y huella (FR-008/FR-020) ---


def test_escribir_corpus_persiste_jsonl_y_huella(tmp_path):
    registros = [_seed_chapinero()]
    validos, _ = procesar_registros(registros)
    ruta = tmp_path / "mercado.jsonl"
    ruta_hash = tmp_path / "mercado.sha256"
    huella = escribir_corpus(validos, str(ruta), str(ruta_hash))

    assert ruta.exists()
    assert ruta_hash.exists()
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 1
    RegistroOfertaInmobiliaria.model_validate_json(lineas[0])
    assert huella == hashlib.sha256(ruta.read_bytes()).hexdigest()


# --- Ingesta híbrida con fallback a seeds (FR-004/FR-007, D7) ---


def test_ingesta_solo_semillas_genera_corpus_determinista(tmp_path):
    ruta_corpus = tmp_path / "mercado.jsonl"
    ruta_hash = tmp_path / "mercado.sha256"
    ruta_seeds = tmp_path / "seeds.jsonl"
    ruta_seeds.write_text(
        json.dumps(_seed_chapinero(), ensure_ascii=False) + "\n", encoding="utf-8"
    )

    reporte_1 = asyncio.run(
        ingerir_mercado(
            solo_semillas=True,
            ruta_seeds=str(ruta_seeds),
            ruta_corpus=str(ruta_corpus),
            ruta_hash=str(ruta_hash),
        )
    )
    reporte_2 = asyncio.run(
        ingerir_mercado(
            solo_semillas=True,
            ruta_seeds=str(ruta_seeds),
            ruta_corpus=str(ruta_corpus),
            ruta_hash=str(ruta_hash),
        )
    )

    assert reporte_1["registros"] == 1
    assert reporte_1["huella_sha256"] == reporte_2["huella_sha256"]
    assert reporte_1["por_fuente"]["seed"] == 1


def test_ingesta_sin_seeds_y_sin_scraping_falla(tmp_path):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    ruta_seeds = tmp_path / "inexistente.jsonl"  # sin seeds
    with pytest.raises(Exception):
        asyncio.run(
            ingerir_mercado(
                client=client,
                ruta_seeds=str(ruta_seeds),
                ruta_corpus=str(tmp_path / "mercado.jsonl"),
                ruta_hash=str(tmp_path / "mercado.sha256"),
            )
        )


def test_consolidar_corpus_fusiona_scraping_y_seeds_sin_duplicar(tmp_path):
    """El mismo registro via scraping y via seeds se deduplica por id."""
    seed = _seed_chapinero()
    ruta_seeds = tmp_path / "seeds.jsonl"
    ruta_seeds.write_text(json.dumps(seed, ensure_ascii=False) + "\n", encoding="utf-8")
    scraping = [dict(seed)]  # mismo registro que la seed
    registros, motivos, conteo = consolidar_corpus(
        scraping, ruta_seeds=str(ruta_seeds), usar_semillas=True
    )
    assert len(registros) == 1
    assert conteo.get("seed", 0) == 1


# --- CLI `mercado` (T025, US3, FR-008) ---

RUTA_RAIZ = Path(__file__).resolve().parents[2]


def _invocar_cli(*args: str) -> "subprocess.CompletedProcess":
    import subprocess
    import sys

    return subprocess.run(
        [sys.executable, "-m", "app.ingesta.corpus", "mercado", *args],
        cwd=str(RUTA_RAIZ),
        capture_output=True,
        text=True,
    )


def test_cli_mercado_solo_semillas_exit_0(tmp_path):
    """El subcomando `mercado --solo-semillas --output <dir>` persiste el corpus en <dir> y sale 0."""
    resultado = _invocar_cli("--solo-semillas", "--output", str(tmp_path))
    assert resultado.returncode == 0, resultado.stderr
    assert "Corpus de mercado" in resultado.stdout
    # El corpus se escribe en el directorio de salida, NO en los versionados.
    assert (tmp_path / "mercado.jsonl").exists()
    assert (tmp_path / "mercado.sha256").exists()
    lines = (tmp_path / "mercado.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines


def test_cli_mercado_flags_mutuamente_excluyentes():
    """--solo-semillas y --solo-scrape son mutuamente excluyentes (argparse)."""
    resultado = _invocar_cli("--solo-semillas", "--solo-scrape")
    assert resultado.returncode != 0


def test_cli_mercado_es_determinista_al_reejecutar(tmp_path):
    """Re-ejecutar la ingesta reproduce el mismo corpus (dedup, SC-005)."""
    resultado_1 = _invocar_cli("--solo-semillas", "--output", str(tmp_path))
    assert resultado_1.returncode == 0
    huella_1 = (tmp_path / "mercado.sha256").read_text().strip()

    resultado_2 = _invocar_cli("--solo-semillas", "--output", str(tmp_path))
    assert resultado_2.returncode == 0
    huella_2 = (tmp_path / "mercado.sha256").read_text().strip()

    assert huella_1 == huella_2

