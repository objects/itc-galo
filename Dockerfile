# Etapa de construccion: instala dependencias en un entorno limpio
FROM python:3.11-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Instala el proyecto y sus dependencias (sin dev). Incluye el extra web
# (Feature 5: FastAPI + Jinja2 + HTMX) para la interfaz de prefactibilidad;
# el CMD por defecto sigue siendo el servidor MCP por stdio.
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir ".[web]"

# Etapa de runtime: imagen final minimizada con stdio como transporte MCP
FROM python:3.11-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Usuario no privilegiado
RUN groupadd -r mcp && useradd -r -g mcp mcp

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY app ./app

USER mcp

# Transporte MCP por stdio: el proceso lee/escribe JSON-RPC en entrada/salida estandar
CMD ["python", "-m", "app.main"]
