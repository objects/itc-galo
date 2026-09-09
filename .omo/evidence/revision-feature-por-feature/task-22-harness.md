# Task 22 - Higiene harness (dev extra + ruff + hermeticidad)

Fecha: 2026-09-08
Bloque: Todo22 Wave4

## Cambios aplicados
- pyproject.toml dev extra: añadidos fastapi, uvicorn, jinja2, python-multipart, ruff
- pyproject.toml [tool.ruff] line-length 100, target py311, select E,F
- tests/conftest.py construir_servidor() param normativa=None -> NormativaProviderStub por defecto (línea 252 gap cerrado)
- tests/conftest.py server_lotes_f3() param sdp stub + normativa stub por defecto (línea 438 gap cerrado)

## Verificación: colección sin errores
```
uv run pytest --collect-only -q
486 tests collected, 0 collection errors (antes 3 errors fastapi)
```

## Verificación: ejecución completa
```
uv run pytest -q
486 passed, 49 warnings in 14.40s (exit 0)
- Antes: 463 collected + 3 errors fastapi (MAJOR M-A5)
- Ahora: 486 collected, 0 errors
```

## Verificación: Dockerfile regresión
```
grep "pip install" Dockerfile
14:RUN pip install --no-cache-dir ".[web]"
```
Sin regresión: sigue instalando .[web], no .[dev]

## Verificación: ruff config mínima
```
uv run ruff check . -> 192 errors (E501 mayormente), no bloqueante
uv run ruff --version -> 0.16.6
[tool.ruff] presente en pyproject.toml
```
Config mínima no bloqueante, deuda E501 documentada (no fix masivo)

## Commit strategy
chore(harness): Todo22 - dev extra completo + ruff + conftest hermético
