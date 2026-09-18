from dataclasses import dataclass
import secrets
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError

from app.config import get_settings


bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    subject: str
    email: str
    name: str = ""


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> CurrentUser:
    settings = get_settings()
    if settings.dev_auth_bypass:
        return CurrentUser(
            subject="local-developer",
            email="developer@example.com",
            name="Local developer",
        )

    session_user = request.session.get("user")
    if isinstance(session_user, dict):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            expected_csrf = request.session.get("csrf_token", "")
            supplied_csrf = request.headers.get("X-CSRF-Token", "")
            if not expected_csrf or not secrets.compare_digest(
                expected_csrf,
                supplied_csrf,
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid or missing CSRF token",
                )

        return CurrentUser(
            subject=str(session_user["subject"]),
            email=str(session_user["email"]),
            name=str(session_user.get("name", "")),
        )

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in with Microsoft Entra ID",
        )
    if not settings.entra_tenant_id or not settings.entra_api_client_id:
        raise HTTPException(status_code=500, detail="Entra authentication is not configured")

    try:
        signing_key = PyJWKClient(settings.entra_jwks_url).get_signing_key_from_jwt(credentials.credentials)
        claims = jwt.decode(
            credentials.credentials,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.entra_api_client_id,
            issuer=settings.entra_issuer,
        )
    except (jwt.PyJWTError, PyJWKClientError, KeyError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token") from exc

    return CurrentUser(
        subject=claims["sub"],
        email=claims.get("preferred_username") or claims.get("email") or claims["sub"],
        name=claims.get("name", ""),
    )


Authenticated = Annotated[CurrentUser, Depends(get_current_user)]
