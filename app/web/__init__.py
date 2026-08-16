"""Capa web de prefactibilidad (Feature 5).

Interfaz HTTP (FastAPI + Jinja2 + HTMX) que reutiliza la logica de dominio de
`ServidorLotes` (app/main.py) SIN protocolo MCP: el usuario crea proyectos de
evaluacion de prefactibilidad para un lote (por CHIP, direccion o coordenadas),
los lista y los reabre. El repositorio de proyectos vive en `app/web/db.py`.
"""