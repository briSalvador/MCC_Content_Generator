import secrets
from urllib.parse import quote

import msal
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.security import Authenticated


router = APIRouter(tags=["authentication"])


def confidential_client() -> msal.ConfidentialClientApplication:
    settings = get_settings()
    if not settings.entra_web_login_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Microsoft Entra employee login is not configured",
        )
    return msal.ConfidentialClientApplication(
        client_id=settings.entra_api_client_id,
        client_credential=settings.entra_client_secret,
        authority=settings.entra_authority,
    )


@router.get("/auth/login", include_in_schema=False)
def login(request: Request) -> RedirectResponse:
    settings = get_settings()
    if settings.dev_auth_bypass:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    flow = confidential_client().initiate_auth_code_flow(
        scopes=[],
        redirect_uri=settings.entra_redirect_uri,
    )
    request.session["auth_flow"] = flow
    return RedirectResponse(url=flow["auth_uri"], status_code=status.HTTP_302_FOUND)


@router.get("/auth/callback", include_in_schema=False)
def auth_callback(request: Request) -> RedirectResponse:
    flow = request.session.pop("auth_flow", None)
    if not isinstance(flow, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The sign-in session expired. Start sign-in again.",
        )

    try:
        result = confidential_client().acquire_token_by_auth_code_flow(
            flow,
            dict(request.query_params),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Microsoft Entra rejected the sign-in response",
        ) from exc

    claims = result.get("id_token_claims")
    if not isinstance(claims, dict):
        error = str(result.get("error", "authentication_failed"))
        return RedirectResponse(
            url=f"/?auth_error={quote(error)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    subject = claims.get("oid") or claims.get("sub")
    email = claims.get("preferred_username") or claims.get("email") or subject
    if not subject or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The Microsoft Entra token does not contain a user identity",
        )

    request.session.clear()
    request.session["user"] = {
        "subject": str(subject),
        "email": str(email),
        "name": str(claims.get("name", "")),
    }
    request.session["csrf_token"] = secrets.token_urlsafe(32)
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/auth/logout", include_in_schema=False)
def logout(request: Request) -> RedirectResponse:
    settings = get_settings()
    request.session.clear()
    if settings.dev_auth_bypass:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    destination = quote(settings.entra_post_logout_redirect_uri, safe="")
    return RedirectResponse(
        url=(
            f"{settings.entra_authority}/oauth2/v2.0/logout"
            f"?post_logout_redirect_uri={destination}"
        ),
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/api/auth/me")
def current_user(request: Request, user: Authenticated) -> dict[str, object]:
    settings = get_settings()
    return {
        "subject": user.subject,
        "email": user.email,
        "name": user.name,
        "csrf_token": request.session.get("csrf_token", ""),
        "development_bypass": settings.dev_auth_bypass,
    }
