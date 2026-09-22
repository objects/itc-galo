"""Contract tests del transporte Streamable HTTP (F12, Fase 1).

Herméticos: la app ASGI de `app.servidor_http.construir_app_http` se ejercita con
`starlette.testclient.TestClient` sobre `httpx` MockTransport (nunca hay puertos
reales, red ni Ollama). Cubren el contrato §6 (contracts/transporte-http.md):

- Paridad stdio↔HTTP: `initialize` + `tools/list` → las mismas 7 tools con los
  mismos `name`/`inputSchema` (SC-002).
- Seguridad `Origin`: foráneo → 403 sin procesar JSON-RPC; ausente → permitido;
  allowlisted → permitido (FR-003, SC-003).
- Configuración: bind default loopback y fail-fast con SystemExit claro ante
  valores inválidos (FR-002, Principio IV).
- Lifespan encadenado (FR-004): una tool real ejecuta por HTTP y al apagar la
  app quedan cerrados los `httpx.AsyncClient` de los providers.
- US3 (contrato §5): patrón `Mount` en FastAPI con el lifespan propagado.
- F12 Fase 3 (D-01 resource server OAuth 2.1): 401/403 + `WWW-Authenticate`
  con `resource_metadata`, metadata RFC 9728, handshake completo con Bearer
  válido, config fail-fast de `MCP_AUTH_*` y `VerificadorJWT` real (RS256).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from starlette.testclient import TestClient

from app.main import NOMBRE_SERVIDOR, crear_servidor_mcp
from app.servidor_http import (
    ConfigTransporte,
    construir_app_http,
    construir_componentes_auth,
    resolver_config,
)
from app.verificador_jwt import VerificadorJWT
from tests.conftest import CHIP_VALIDO, construir_servidor

# Host loopback: la protección DNS-rebinding del SDK valida también la cabecera
# Host (421 si no está en allowed_hosts); TestClient debe usar el base_url real.
BASE_URL = "http://127.0.0.1:8000"
ACEPTAR = {"Accept": "application/json, text/event-stream"}
CONFIG_HTTP = ConfigTransporte(transporte="http")

SETUP_INICIAL = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    },
}

SIETE_TOOLS = {
    "resolve_lot_by_chip",
    "resolve_lot_by_address",
    "resolve_lot_by_coordinates",
    "get_lot_summary_by_chip",
    "get_upl",
    "consultar_normativa",
    "get_feasibility_report",
}


def _encabezados_sesion(sesion: str) -> dict[str, str]:
    return {**ACEPTAR, "Mcp-Session-Id": sesion, "MCP-Protocol-Version": "2025-06-18"}


def _inicializar(cliente: TestClient, extra: dict[str, str] | None = None) -> str:
    """Completa initialize + notifications/initialized y devuelve el session id.

    `extra` (p. ej. Authorization Bearer de la Fase 3) se aplica a TODAS las
    peticiones del handshake: con OAuth activo cada request debe traer el token.
    """
    respuesta = cliente.post("/mcp", json=SETUP_INICIAL, headers={**ACEPTAR, **(extra or {})})
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["result"]["serverInfo"]["name"] == NOMBRE_SERVIDOR
    sesion = respuesta.headers.get("mcp-session-id")
    assert sesion, "initialize debe asignar Mcp-Session-Id"
    aviso = cliente.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={**_encabezados_sesion(sesion), **(extra or {})},
    )
    assert aviso.status_code == 202, aviso.text
    return sesion


@pytest.fixture()
def sin_entorno_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla la config de transporte del entorno del ejecutor (fail-fast predecible)."""
    for variable in (
        "MCP_TRANSPORT",
        "MCP_HOST",
        "MCP_PORT",
        "MCP_ALLOWED_ORIGINS",
        "MCP_AUTH_ISSUER_URL",
        "MCP_AUTH_RESOURCE_URL",
        "MCP_AUTH_JWKS_URL",
        "MCP_AUTH_SCOPES",
    ):
        monkeypatch.delenv(variable, raising=False)


# --- T006: paridad stdio↔HTTP (SC-002) ---


def test_parity_tools_list_http_vs_stdio() -> None:
    servidor_lotes = construir_servidor()
    servidor = crear_servidor_mcp(servidor_lotes)
    esperado = {herr.name: herr.input_schema for herr in asyncio.run(servidor.list_tools())}
    assert set(esperado) == SIETE_TOOLS  # invariante FR-008 también en stdio

    app = construir_app_http(servidor, CONFIG_HTTP)
    with TestClient(app, base_url=BASE_URL) as cliente:
        sesion = _inicializar(cliente)
        respuesta = cliente.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers=_encabezados_sesion(sesion),
        )
        assert respuesta.status_code == 200, respuesta.text
        obtenido = {t["name"]: t["inputSchema"] for t in respuesta.json()["result"]["tools"]}

    assert set(obtenido) == SIETE_TOOLS
    assert obtenido == esperado  # mismo contrato de entrada por ambos transportes


# --- T007: seguridad Origin (FR-003, SC-003) ---


def test_origin_foraneo_403_sin_permitir_jsonrpc() -> None:
    servidor_lotes = construir_servidor()
    app = construir_app_http(crear_servidor_mcp(servidor_lotes), CONFIG_HTTP)
    with TestClient(app, base_url=BASE_URL) as cliente:
        respuesta = cliente.post(
            "/mcp",
            json=SETUP_INICIAL,
            headers={**ACEPTAR, "Origin": "https://evil.example.com"},
        )
        assert respuesta.status_code == 403  # rechazo sin procesar el mensaje


def test_sin_origin_permitido_con_allowlist_vacia() -> None:
    servidor_lotes = construir_servidor()
    app = construir_app_http(crear_servidor_mcp(servidor_lotes), CONFIG_HTTP)
    with TestClient(app, base_url=BASE_URL) as cliente:
        sesion = _inicializar(cliente)  # sin Origin: clientes no-browser (curl, mcp-remote)
        respuesta = cliente.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers=_encabezados_sesion(sesion),
        )
        assert respuesta.status_code == 200


def test_origin_allowlist_configurado_permitido() -> None:
    config = ConfigTransporte(transporte="http", origines_permitidos=("https://app.example",))
    servidor_lotes = construir_servidor()
    app = construir_app_http(crear_servidor_mcp(servidor_lotes), config)
    with TestClient(app, base_url=BASE_URL) as cliente:
        sesion = _inicializar(cliente, extra={"Origin": "https://app.example"})
        assert sesion


# --- T008: configuración default + fail-fast (FR-002, Principio IV) ---


def test_default_stdio_ignora_config_http(sin_entorno_mcp) -> None:
    config = resolver_config()
    assert config.transporte == "stdio"
    assert config.host == "127.0.0.1" and config.puerto == 8000


def test_default_http_bind_loopback_y_allowlist_vacia(sin_entorno_mcp) -> None:
    config = resolver_config(transporte_cli="http")
    assert config.host == "127.0.0.1"
    assert config.puerto == 8000
    assert config.origines_permitidos == ()


def test_transporte_invalido_aborta(sin_entorno_mcp, monkeypatch) -> None:
    monkeypatch.setenv("MCP_TRANSPORT", "ftp")
    with pytest.raises(SystemExit) as info:
        resolver_config()
    assert info.value.code == 2
    assert "no soportado" in info.value.mensaje  # mensaje claro en español


def test_puerto_fuera_de_rango_aborta(sin_entorno_mcp, monkeypatch) -> None:
    monkeypatch.setenv("MCP_PORT", "0")
    with pytest.raises(SystemExit) as info:
        resolver_config(transporte_cli="http")
    assert info.value.code == 2
    assert "fuera de rango" in info.value.mensaje


def test_puerto_no_entero_aborta(sin_entorno_mcp, monkeypatch) -> None:
    monkeypatch.setenv("MCP_PORT", "no-es-numero")
    with pytest.raises(SystemExit) as info:
        resolver_config(transporte_cli="http")
    assert "entero" in info.value.mensaje


def test_origen_malformado_aborta(sin_entorno_mcp, monkeypatch) -> None:
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://app.example/path")
    with pytest.raises(SystemExit) as info:
        resolver_config(transporte_cli="http")
    assert "inv" in info.value.mensaje  # "origen inválido"


def test_flag_cli_gana_sobre_entorno(sin_entorno_mcp, monkeypatch) -> None:
    monkeypatch.setenv("MCP_PORT", "9999")
    monkeypatch.setenv("MCP_HOST", "0.0.0.0")
    config = resolver_config(transporte_cli="http", host_cli="127.0.0.1", puerto_cli=8001)
    assert (config.host, config.puerto) == ("127.0.0.1", 8001)


def test_csv_de_origenes_se_parsea(sin_entorno_mcp, monkeypatch) -> None:
    monkeypatch.setenv(
        "MCP_ALLOWED_ORIGINS",
        "https://a.example, https://b.example:8443",
    )
    config = resolver_config(transporte_cli="http")
    assert config.origines_permitidos == ("https://a.example", "https://b.example:8443")


# --- T009: lifespan encadenado + tool real por HTTP (FR-004, SC-002) ---


def test_lifespan_cierra_providers_y_tool_ejecuta() -> None:
    servidor_lotes = construir_servidor()
    servidor = crear_servidor_mcp(servidor_lotes)
    app = construir_app_http(servidor, CONFIG_HTTP)
    assert not servidor_lotes._arcgis._client.is_closed

    with TestClient(app, base_url=BASE_URL) as cliente:
        sesion = _inicializar(cliente)
        llamada = cliente.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "resolve_lot_by_chip", "arguments": {"chip": CHIP_VALIDO}},
            },
            headers=_encabezados_sesion(sesion),
        )
        assert llamada.status_code == 200, llamada.text
        resultado = llamada.json()["result"]
        assert resultado.get("isError") is not True
        payload = json.loads(resultado["content"][0]["text"])
        assert payload["lote"]["chip"] == CHIP_VALIDO  # mismo dominio que stdio

    # FR-004: apagada la app, los httpx.AsyncClient de los providers quedaron cerrados
    assert servidor_lotes._arcgis._client.is_closed
    assert servidor_lotes._sdp._client.is_closed
    assert servidor_lotes._mapas._client.is_closed


# --- T015 (US3): patrón Mount en FastAPI con lifespan propagado (contrato §5) ---


def test_mount_asgi_fastapi_con_lifespan_propagado() -> None:
    from fastapi import FastAPI

    servidor_lotes = construir_servidor()
    app_mcp = construir_app_http(crear_servidor_mcp(servidor_lotes), CONFIG_HTTP)
    # Los lifespans de sub-apps montadas NO se ejecutan solos: el padre debe
    # entrar explícitamente el del session manager (patrón documentado SDK).
    lifespan_hijo = app_mcp.router.lifespan_context

    @asynccontextmanager
    async def lifespan_padre(_app) -> AsyncIterator[None]:
        async with lifespan_hijo(app_mcp):
            yield

    app_web = FastAPI(lifespan=lifespan_padre)

    @app_web.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    app_web.mount("/", app_mcp)  # endpoint externo resultante: POST /mcp

    with TestClient(app_web, base_url=BASE_URL) as cliente:
        assert cliente.get("/health").json() == {"ok": True}  # rutas web intactas
        sesion = _inicializar(cliente)
        respuesta = cliente.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 9, "method": "tools/list"},
            headers=_encabezados_sesion(sesion),
        )
        assert respuesta.status_code == 200
        assert {t["name"] for t in respuesta.json()["result"]["tools"]} == SIETE_TOOLS

    assert servidor_lotes._arcgis._client.is_closed


# --- F12 Fase 3: resource server OAuth 2.1 (D-01) — config fail-fast ---


def test_auth_par_incompleto_aborta(sin_entorno_mcp, monkeypatch) -> None:
    monkeypatch.setenv("MCP_AUTH_ISSUER_URL", "https://auth.example")
    with pytest.raises(SystemExit) as info:
        resolver_config(transporte_cli="http")
    assert "a la vez" in info.value.mensaje


def test_auth_sin_jwks_aborta(sin_entorno_mcp, monkeypatch) -> None:
    monkeypatch.setenv("MCP_AUTH_ISSUER_URL", "https://auth.example")
    monkeypatch.setenv("MCP_AUTH_RESOURCE_URL", "https://mcp.example")
    with pytest.raises(SystemExit) as info:
        resolver_config(transporte_cli="http")
    assert "MCP_AUTH_JWKS_URL" in info.value.mensaje


def test_auth_campos_huerfanos_abortan(sin_entorno_mcp, monkeypatch) -> None:
    monkeypatch.setenv("MCP_AUTH_SCOPES", "mcp:tools")
    with pytest.raises(SystemExit) as info:
        resolver_config(transporte_cli="http")
    assert "autenticación activa" in info.value.mensaje


def test_auth_config_completa_resuelve(sin_entorno_mcp, monkeypatch) -> None:
    monkeypatch.setenv("MCP_AUTH_ISSUER_URL", "https://auth.example")
    monkeypatch.setenv("MCP_AUTH_RESOURCE_URL", "https://mcp.example")
    monkeypatch.setenv("MCP_AUTH_JWKS_URL", "https://auth.example/.well-known/jwks.json")
    monkeypatch.setenv("MCP_AUTH_SCOPES", "mcp:tools, mcp:read")
    config = resolver_config(transporte_cli="http")
    assert config.auth_activa
    assert config.scopes_requeridos == ("mcp:tools", "mcp:read")


def test_sin_auth_fases_1_y_2_intactas(sin_entorno_mcp) -> None:
    config = resolver_config(transporte_cli="http")
    assert config.auth_activa is False
    auth, verificador = construir_componentes_auth(config)
    assert auth is None and verificador is None


def test_construir_componentes_auth_empareja_sdk_y_verificador() -> None:
    config = ConfigTransporte(
        transporte="http",
        emisor_url="https://auth.example",
        recurso_url="https://mcp.example",
        jwks_url="https://auth.example/.well-known/jwks.json",
        scopes_requeridos=("mcp:tools",),
    )
    auth, verificador = construir_componentes_auth(config)
    assert isinstance(auth, AuthSettings)
    assert str(auth.resource_server_url).startswith("https://mcp.example")
    assert auth.required_scopes == ["mcp:tools"]
    assert isinstance(verificador, VerificadorJWT)


# --- F12 Fase 3: endpoint /mcp protegido (Bearer JWT) ---


class VerificadorSimulado:
    """TokenVerifier de prueba: solo 'tok-valido' pasa, con scope mcp:tools."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if token == "tok-valido":
            return AccessToken(
                token=token,
                client_id="claude-connector",
                scopes=["mcp:tools"],
                expires_at=int(time.time()) + 3600,
                subject="user-1",
            )
        return None


def _app_con_auth(scopes: tuple[str, ...] = ()):  # -> Starlette
    auth = AuthSettings(
        issuer_url="https://auth.example",
        resource_server_url="https://mcp.example",
        required_scopes=list(scopes) or None,
    )
    servidor = crear_servidor_mcp(
        construir_servidor(), auth=auth, token_verifier=VerificadorSimulado()
    )
    return construir_app_http(servidor, CONFIG_HTTP)


def test_sin_token_401_con_resource_metadata() -> None:
    app = _app_con_auth()
    with TestClient(app, base_url=BASE_URL) as cliente:
        respuesta = cliente.post("/mcp", json=SETUP_INICIAL, headers=ACEPTAR)
        assert respuesta.status_code == 401
        cabecera = respuesta.headers.get("www-authenticate", "")
        assert cabecera.startswith("Bearer ")
        assert 'error="invalid_token"' in cabecera
        assert "resource_metadata=" in cabecera  # RFC 9728 para probe lazy


def test_metadata_recurso_protecto_publica() -> None:
    app = _app_con_auth(scopes=("mcp:tools",))
    with TestClient(app, base_url=BASE_URL) as cliente:
        respuesta = cliente.get("/.well-known/oauth-protected-resource")
        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert str(cuerpo["resource"]).rstrip("/").endswith("mcp.example")
        assert any("auth.example" in str(s) for s in cuerpo["authorization_servers"])
        assert cuerpo["scopes_supported"] == ["mcp:tools"]


def test_token_invalido_401_y_valido_completa_handshake() -> None:
    app = _app_con_auth()
    with TestClient(app, base_url=BASE_URL) as cliente:
        malo = cliente.post(
            "/mcp",
            json=SETUP_INICIAL,
            headers={**ACEPTAR, "Authorization": "Bearer tok-robado"},
        )
        assert malo.status_code == 401

        sesion = _inicializar(cliente, extra={"Authorization": "Bearer tok-valido"})
        lista = cliente.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers={**_encabezados_sesion(sesion), "Authorization": "Bearer tok-valido"},
        )
        assert lista.status_code == 200
        assert {t["name"] for t in lista.json()["result"]["tools"]} == SIETE_TOOLS


def test_scope_insuficiente_403() -> None:
    app = _app_con_auth(scopes=("mcp:admin",))  # el token simulado trae mcp:tools
    with TestClient(app, base_url=BASE_URL) as cliente:
        respuesta = cliente.post(
            "/mcp",
            json=SETUP_INICIAL,
            headers={**ACEPTAR, "Authorization": "Bearer tok-valido"},
        )
        assert respuesta.status_code == 403
        assert "insufficient_scope" in respuesta.headers.get("www-authenticate", "")


# --- F12 Fase 3: VerificadorJWT real (RS256 con par de claves local) ---


@pytest.fixture(scope="module")
def claves_rsa() -> tuple:
    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(pyjwt.algorithms.RSAAlgorithm.to_jwk(privada.public_key()))
    jwk.update({"kid": "test-1", "alg": "RS256", "use": "sig"})
    return privada, PyJWK(jwk)


class ClienteJwkSimulado:
    """Sustituye el fetch de red del JWKS: siempre devuelve la clave local."""

    def __init__(self, pyjwk: PyJWK) -> None:
        self._pyjwk = pyjwk

    def get_signing_key_from_jwt(self, token: str) -> PyJWK:
        return self._pyjwk


def _verificador(claves) -> VerificadorJWT:
    _, pyjwk = claves
    return VerificadorJWT(
        jwks_url="https://auth.example/.well-known/jwks.json",
        emisor_url="https://auth.example",
        audiencia="https://mcp.example",
        jwk_client=ClienteJwkSimulado(pyjwk),
    )


def _jwt(
    claves,
    *,
    aud="https://mcp.example",
    iss="https://auth.example",
    sub="user-1",
    exp_offset=3600,
    **extra,
) -> str:
    privada, _ = claves
    ahora = int(time.time())
    payload: dict = {"iss": iss, "iat": ahora, "exp": ahora + exp_offset}
    if sub is not None:
        payload["sub"] = sub
    if aud is not None:
        payload["aud"] = aud
    payload.update(extra)
    return pyjwt.encode(payload, privada, algorithm="RS256", headers={"kid": "test-1"})


def test_jwt_valido_produce_access_token(claves_rsa) -> None:
    token = _jwt(claves_rsa, azp="client-app", scope="mcp:tools lectura")
    resultado = asyncio.run(_verificador(claves_rsa).verify_token(token))
    assert resultado is not None
    assert resultado.client_id == "client-app"
    assert resultado.subject == "user-1"
    assert resultado.scopes == ["mcp:tools", "lectura"]
    assert resultado.resource == "https://mcp.example"
    assert resultado.expires_at > int(time.time())


def test_jwt_expirado_rechazado(claves_rsa) -> None:
    token = _jwt(claves_rsa, exp_offset=-60)
    assert asyncio.run(_verificador(claves_rsa).verify_token(token)) is None


def test_jwt_audiencia_distinta_rechazada(claves_rsa) -> None:
    # RFC 8707: el token debe hacer echo del resource — otro aud no sirve.
    token = _jwt(claves_rsa, aud="https://otro.example")
    assert asyncio.run(_verificador(claves_rsa).verify_token(token)) is None


def test_jwt_emisor_distinto_rechazado(claves_rsa) -> None:
    token = _jwt(claves_rsa, iss="https://evil.example")
    assert asyncio.run(_verificador(claves_rsa).verify_token(token)) is None


def test_jwt_firma_ajena_rechazada(claves_rsa) -> None:
    intrusa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    payload = {
        "iss": "https://auth.example",
        "aud": "https://mcp.example",
        "sub": "user-1",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    token = pyjwt.encode(payload, intrusa, algorithm="RS256", headers={"kid": "test-1"})
    assert asyncio.run(_verificador(claves_rsa).verify_token(token)) is None


def test_jwt_sin_sub_rechazado(claves_rsa) -> None:
    token = _jwt(claves_rsa, sub=None)
    assert asyncio.run(_verificador(claves_rsa).verify_token(token)) is None


def test_jwt_scp_lista_oidc_normalizada(claves_rsa) -> None:
    token = _jwt(claves_rsa, scp=["mcp:tools", "mcp:read"])
    resultado = asyncio.run(_verificador(claves_rsa).verify_token(token))
    assert resultado is not None
    assert resultado.scopes == ["mcp:tools", "mcp:read"]
