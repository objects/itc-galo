# Quickstart: UX Web Informe Completo

## Verificación rápida

```bash
# 1. Ejecutar todos los tests
uv run pytest -q

# 2. Verificar prerequisitos del Spec Kit
bash .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks

# 3. Verificar que el template renderiza el informe completo
uv run pytest tests/contract/test_web_informe.py -v
```

## Verificación manual

```bash
# Arrancar la web app
uv run web-mcp-bogota-factibilidad

# Abrir http://127.0.0.1:8000/
# Crear un proyecto con CHIP AAA0072LRYN
# Verificar: score ring, mapa, bloques, evidencia, advertencias
```

## Archivos modificados

- `app/web/templates/base.html`: enlace a leaflet.css
- `app/web/templates/proyecto.html`: reescritura completa
- `app/web/static/estilos.css`: estilos para nuevas secciones
- `app/web/static/leaflet.js`: vendorizado
- `app/web/static/leaflet.css`: vendorizado
- `tests/contract/test_web_informe.py`: tests del informe web
