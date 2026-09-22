"""Transporte Streamable HTTP opcional del servidor MCP (F12, FR-001…FR-005).

La Constitución (v1.0.1) permite stdio por defecto y este modo HTTP opcional. El
transporte NO es un provider (Principio II): vive en la capa de arranque y se
limita a enmarcar JSON-RPC sobre HTTP — el payload de las 7 tools es idéntico al
de stdio (FR-008/SC-002), y los errores de dominio viajan como tool-result de
error MCP, nunca como 5xx del transporte.

Composición con el SDK (mcp 2.x, verificado en runtime):

- `streamable_http_app()` devuelve una app Starlette cuyo lifespan entra el
  `session_manager.run()`, que a su vez encadena el `lifespan` del constructor
  del servidor (`_lifespan_cerrar_providers` de `app/main.py`): al apagar la app
  se cierran los `httpx.AsyncClient` de los providers (FR-004). El contract test
  `test_lifespan_encadenado_cierra_providers` fija ese comportamiento.
- La validación `Origin` anti DNS-rebinding (FR-003) la aplica el SDK vía
  `TransportSecuritySettings`: petición SIN `Origin` siempre permitida (clientes
  no-browser); petición CON `Origin` solo si está en la allowlist, si no 403 sin
  procesar JSON-RPC. El 403/421 es del transporte: la taxonomía `CodigoError`
  (10 códigos) permanece invariable.

Seguridad por defecto (data-model.md §1):

- Bind `127.0.0.1` (FR-002): `0.0.0.0` solo si el operador lo pide explícito.
- Allowlist de orígenes VACÍA por defecto → ningún `Origin` navegador es
  aceptado; quien quiera servir desde un túnel/dominio debe listar los orígenes
  en `MCP_ALLOWED_ORIGINS` (CSV) — de ellos se derivan también los `Host`
  permitidos (cabecera validada por el SDK, código 421).
- Stateless-first (D-05): respuestas JSON por petición (`json_response=True`)
  sin streams SSE colgados; las sesiones `Mcp-Session-Id` las gestiona el SDK
  por proceso (D-03: un solo uvicorn, sin Redis en Fase 1).
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from starlette.applications import Starlette

try:  # mcp >= 1.12: protección DNS-rebinding integrada en el SDK
    from mcp.server.transport_security import TransportSecuritySettings
except ImportError:  # pragma: no cover - entorno con SDK antiguo
    TransportSecuritySettings = None  # type: ignore[assignment]

# Valores canónicos del flag --transport (FR-001).
TRANSPORTES_VALIDOS = ("stdio", "http")

# Patrones de Host/Origin de loopback que SIEMPRE se permiten binds locales.
_PATRONES_HOST_LOOPBACK = ("127.0.0.1:*", "localhost:*", "[::1]:*")

# Host/hostname/IP: sin esquema, sin path, permite puerto opcional implícito.
_PATRON_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-_:]*$")

# Origen de allowlist: scheme http/https + host[:puerto|:*], sin path ni slash.
_PATRON_ORIGIN = re.compile(r"^https?://[A-Za-z0-9.\-_\[\]:]+$")


class ErrorConfigTransporte(SystemExit):
    """Config de transporte inválida: mensaje claro por stderr y salida código 2.

    (Principio IV — fail-fast sin traceback crudo; el exit code 2 sigue la
    convención de argparse para errores de uso.)
    """

    def __init__(self, mensaje: str) -> None:
        self.mensaje = f"[config] {mensaje}"
        print(self.mensaje, file=sys.stderr)
        super().__init__(2)


@dataclass(frozen=True)
class ConfigTransporte:
    """Configuración de arranque del transporte (data-model.md §1, solo lectura)."""

    transporte: str = "stdio"
    host: str = "127.0.0.1"
    puerto: int = 8000
    origines_permitidos: tuple[str, ...] = ()
    # Fase 3 (OAuth 2.1 resource server, D-01): los tres viajan juntos o ninguno.
    emisor_url: str | None = None  # MCP_AUTH_ISSUER_URL (AS gestionado)
    recurso_url: str | None = None  # MCP_AUTH_RESOURCE_URL (URL pública del /mcp)
    jwks_url: str | None = None  # MCP_AUTH_JWKS_URL (JWKS del AS)
    scopes_requeridos: tuple[str, ...] = ()  # MCP_AUTH_SCOPES (CSV)

    @property
    def auth_activa(self) -> bool:
        return bool(self.emisor_url and self.recurso_url)


def _parsear_origines(valor_env: str | None) -> tuple[str, ...]:
    """Convierte el CSV de MCP_ALLOWED_ORIGINS en tupla validada.

    Cada entrada debe ser un origen `http(s)://host[:puerto]` (o con puerto
    `:*` para desarrollo). Se rechazan paths, espacios o esquemas distintos —
    fail-fast con mensaje explícito en español (Principio IV).
    """
    if not valor_env or not valor_env.strip():
        return ()
    orígenes: list[str] = []
    for trozo in valor_env.split(","):
        origen = trozo.strip()
        if not origen:
            continue
        if not _PATRON_ORIGIN.match(origen):
            raise ErrorConfigTransporte(
                f"origen inválido en MCP_ALLOWED_ORIGINS: {origen!r} "
                "(esperado http(s)://host o http(s)://host:puerto, sin path)."
            )
        orígenes.append(origen)
    return tuple(orígenes)


def resolver_config(
    transporte_cli: str | None = None,
    host_cli: str | None = None,
    puerto_cli: int | None = None,
) -> ConfigTransporte:
    """Resuelve la config de transporte: flag CLI > variable de entorno > default.

    Valida fail-fast ANTES de abrir sockets (contrato §1): `transporte` siempre;
    `host`/`puerto`/orígenes solo en modo http (no se rompe el arranque stdio
    actual por variables irrelevantes).
    """
    transporte = (transporte_cli or os.environ.get("MCP_TRANSPORT") or "stdio").strip().lower()
    if transporte not in TRANSPORTES_VALIDOS:
        raise ErrorConfigTransporte(
            f"MCP_TRANSPORT/--transport={transporte!r} no soportado "
            f"(valores válidos: {', '.join(TRANSPORTES_VALIDOS)})."
        )
    if transporte == "stdio":
        return ConfigTransporte(transporte="stdio")

    host = (host_cli or os.environ.get("MCP_HOST") or "127.0.0.1").strip()
    if not _PATRON_HOST.match(host):
        raise ErrorConfigTransporte(f"MCP_HOST/--host inválido: {host!r}.")

    puerto_bruto = os.environ.get("MCP_PORT") if puerto_cli is None else str(puerto_cli)
    try:
        puerto = int(puerto_bruto or "8000")
    except (TypeError, ValueError):
        raise ErrorConfigTransporte(
            f"MCP_PORT/--port debe ser un entero, recibido: {puerto_bruto!r}."
        ) from None
    if not 1 <= puerto <= 65535:
        raise ErrorConfigTransporte(
            f"MCP_PORT/--port fuera de rango 1-65535: {puerto}."
        )

    return ConfigTransporte(
        transporte="http",
        host=host,
        puerto=puerto,
        origines_permitidos=_parsear_origines(os.environ.get("MCP_ALLOWED_ORIGINS")),
        **_resolver_auth_desde_entorno(),
    )


def _resolver_auth_desde_entorno() -> dict[str, Any]:
    """Campos OAuth de `ConfigTransporte` desde el entorno, validados fail-fast.

    Regla: `MCP_AUTH_ISSUER_URL` y `MCP_AUTH_RESOURCE_URL` viajan OBLIGATORIAMENTE
    juntos (resource server sin emisor verificable es una configuración rota); si
    se activa el par, `MCP_AUTH_JWKS_URL` es requerido — la URL del JWKS no se
    deduce para no hacer red al arrancar. `MCP_AUTH_SCOPES` es opcional (CSV;
    vacío = cualquier token válido del emisor, sin exigencia de scope).
    """
    emisor = (os.environ.get("MCP_AUTH_ISSUER_URL") or "").strip()
    recurso = (os.environ.get("MCP_AUTH_RESOURCE_URL") or "").strip()
    jwks = (os.environ.get("MCP_AUTH_JWKS_URL") or "").strip()
    scopes_bruto = (os.environ.get("MCP_AUTH_SCOPES") or "").strip()
    if not emisor and not recurso:
        if scopes_bruto or jwks:
            raise ErrorConfigTransporte(
                "MCP_AUTH_SCOPES/MCP_AUTH_JWKS_URL requieren autenticación activa "
                "(MCP_AUTH_ISSUER_URL y MCP_AUTH_RESOURCE_URL)."
            )
        return {}
    if not (emisor and recurso):
        raise ErrorConfigTransporte(
            "la autenticación OAuth requiere MCP_AUTH_ISSUER_URL y "
            "MCP_AUTH_RESOURCE_URL configurados a la vez."
        )
    _validar_url(emisor, "MCP_AUTH_ISSUER_URL")
    _validar_url(recurso, "MCP_AUTH_RESOURCE_URL")
    if not jwks:
        raise ErrorConfigTransporte(
            "falta MCP_AUTH_JWKS_URL (URL del JWKS del AS, p. ej. "
            "https://<tenant>.auth0.com/.well-known/jwks.json)."
        )
    _validar_url(jwks, "MCP_AUTH_JWKS_URL")
    scopes = tuple(s.strip() for s in scopes_bruto.split(",") if s.strip())
    return {
        "emisor_url": emisor,
        "recurso_url": recurso,
        "jwks_url": jwks,
        "scopes_requeridos": scopes,
    }


def _validar_url(valor: str, nombre: str) -> None:
    """URL absoluta http(s):// (https es responsabilidad del TLS del borde)."""
    partes = urlsplit(valor)
    if partes.scheme not in ("http", "https") or not partes.netloc:
        raise ErrorConfigTransporte(
            f"{nombre} debe ser una URL absoluta http(s)://..., recibido: {valor!r}."
        )


def _hosts_permitidos(config: ConfigTransporte) -> list[str]:
    """Hosts aceptados por la protección DNS-rebinding del SDK (cabecera Host).

    Loopback siempre (bind por defecto, FR-002) + las autoridades derivadas de
    la allowlist de orígenes (p. ej. el hostname del túnel cloudflared) + el
    host de bind explícito si no es comodín. Con bind 0.0.0.0 y allowlist vacía
    el servidor queda de hecho inalcanzable desde fuera (421): postura segura.
    """
    hosts = list(_PATRONES_HOST_LOOPBACK)
    for origen in config.origines_permitidos:
        autoridad = urlsplit(origen).netloc
        if autoridad and autoridad not in hosts:
            hosts.append(autoridad)
            # Variante comodín de puerto para orígenes sin puerto explícito.
            if ":" not in autoridad.rsplit("]", 1)[-1]:
                hosts.append(f"{autoridad}:*")
    if config.host not in ("0.0.0.0", "::", "") and config.host not in hosts:
        hosts.append(config.host)
    return hosts


def construir_app_http(servidor: Any, config: ConfigTransporte) -> Starlette:
    """App ASGI Streamable HTTP del endpoint `/mcp` (contrato §2).

    Recibe el servidor ya construido por `crear_servidor_mcp()` para NO acoplar
    este módulo a `app/main.py` (import circular) y para que el lifespan de
    cierre de providers quede registrado en el constructor (FR-004).
    """
    if TransportSecuritySettings is None:  # pragma: no cover - SDK < 1.12
        raise ErrorConfigTransporte(
            "el modo http requiere el paquete mcp>=1.12 (protección DNS-rebinding "
            "no disponible en el SDK instalado)."
        )
    if not hasattr(servidor, "streamable_http_app"):  # pragma: no cover - SDK inesperado
        raise ErrorConfigTransporte(
            "el objeto de servidor MCP no expone streamable_http_app(); "
            "verifica la dependencia mcp>=1.0."
        )
    seguridad = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_hosts_permitidos(config),
        allowed_origins=list(config.origines_permitidos),
    )
    return servidor.streamable_http_app(
        streamable_http_path="/mcp",
        host=config.host,
        json_response=True,
        transport_security=seguridad,
    )


def construir_componentes_auth(
    config: ConfigTransporte,
) -> tuple[Any, Any] | tuple[None, None]:
    """(AuthSettings, VerificadorJWT) si el modo resource server OAuth está activo.

    Sin emisión de tokens (D-01): solo se configura la verificación del Bearer JWT
    que aplicará el middleware del SDK sobre `/mcp`, y la metadata RFC 9728 que
    publica la ruta `/.well-known/oauth-protected-resource`. Con OAuth inactivo
    devuelve (None, None) — el comportamiento de Fase 1/2 queda intacto.
    """
    if not config.auth_activa:
        return None, None
    # Import local: mantiene el arranque stdio ligero y evita exigir pyjwt/aiohttp
    # a entornos mínimos del SDK (Fase 3 es opt-in por variables MCP_AUTH_*).
    from mcp.server.auth.settings import AuthSettings

    from app.verificador_jwt import VerificadorJWT

    auth = AuthSettings(
        issuer_url=config.emisor_url,
        resource_server_url=config.recurso_url,
        required_scopes=list(config.scopes_requeridos) or None,
    )
    verificador = VerificadorJWT(
        jwks_url=config.jwks_url or "",
        emisor_url=config.emisor_url or "",
        audiencia=config.recurso_url or "",
    )
    return auth, verificador
