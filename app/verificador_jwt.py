"""Verificador JWT para el resource server OAuth 2.1 del MCP remoto (F12 Fase 3).

El Authorization Server es GESTIONADO (research.md D-01: Auth0/Okta/Cognito):
este modulo NO emite tokens — solo verifica el JWT presentado como Bearer contra
el JWKS del AS. Implementa el protocolo `TokenVerifier` de
`mcp.server.auth.provider`: el `AuthenticationMiddleware`/`RequireAuthMiddleware`
del SDK convierte un `None` en 401 con `WWW-Authenticate: resource_metadata=…`
(descubrimiento RFC 9728, probe lazy de Claude y requisito de ChatGPT).

Validacion (fail-closed, Principio IV): firma RS256 contra la clave del JWKS cuyo
`kid`declare el header, `iss` == emisor configurado, `aud` == recurso declarado
(echo RFC 8707 del parámetro resource, exigido por OpenAI), expiracion y `sub`.
Cualquier fallo devuelve None y registra un warning — NUNCA propaga excepciones
al transporte (un error del JWKS remoto tampoco debe verborrear al cliente con 5xx).
"""

from __future__ import annotations

import logging
from typing import Any

import jwt
from mcp.server.auth.provider import AccessToken

logger = logging.getLogger(__name__)

# RS256: default de Auth0/Okta/Cognito para access tokens OP. Ampliable por
# config si un AS exige otro algoritmo (fuera del alcance F12).
ALGORITMOS_ACEPTADOS = ["RS256"]


class VerificadorJWT:
    """Verificador de access tokens JWT firmado por AS gestionado (JWKS cacheado).

    `jwk_client` es inyectable para pruebas hermeticas (sin red al JWKS real).
    La clase satisface el protocolo estructural `TokenVerifier` del SDK.
    """

    def __init__(
        self,
        *,
        jwks_url: str,
        emisor_url: str,
        audiencia: str,
        jwk_client: Any | None = None,
    ) -> None:
        self._jwks_url = jwks_url
        self._emisor_url = emisor_url
        self._audiencia = audiencia
        self._jwk_client = jwk_client or jwt.PyJWKClient(jwks_url, cache_keys=True)

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verifica `token` y devuelve el `AccessToken` del SDK, o None si no es válido.

        El SDK espera una corutina (`await` del `AuthenticationMiddleware`); la
        verificación JWT es CPU-bound y breve, suficiente sin off-thread.
        El chequeo de scopes requeridos NO vive aquí: el SDK lo aplica contra
        `AuthSettings.required_scopes` usando `AccessToken.scopes`.
        """
        try:
            # Incluye OSError por fallos de red del fetch JWKS: se degradan a 401
            # (fail-closed) en lugar de un 5xx del transporte.
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=ALGORITMOS_ACEPTADOS,
                audience=self._audiencia,
                issuer=self._emisor_url,
                options={"require": ["exp", "sub"]},
            )
        except jwt.PyJWTError as exc:
            logger.warning("token JWT rechazado (%s)", type(exc).__name__)
            return None
        except (OSError, ValueError) as exc:
            logger.warning("validación JWT indisponible/rechazada (%s)", type(exc).__name__)
            return None

        audiencia_claim = claims.get("aud")
        return AccessToken(
            token=token,
            # azp (authorized party) es el client id en tokens de 1ª parte de Auth0;
            # sin él, el propio sub representa al sujeto del token.
            client_id=str(claims.get("azp") or claims.get("client_id") or claims.get("sub")),
            scopes=_scopes_de(claims),
            expires_at=int(claims["exp"]),
            subject=str(claims["sub"]),
            resource=audiencia_claim if isinstance(audiencia_claim, str) else None,
            claims=claims,
        )


def _scopes_de(claims: dict[str, Any]) -> list[str]:
    """Normaliza el/los claim(s) de scope: `scope` string OAuth o `scp` list/str OIDC."""
    scope = claims.get("scope") or claims.get("scp") or []
    if isinstance(scope, str):
        return scope.split()
    if isinstance(scope, list):
        return [str(s) for s in scope]
    return []
