from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import database, security
from app.routers import auth


def make_request(
    method: str = "GET",
    session: dict[str, object] | None = None,
    csrf_token: str | None = None,
) -> Request:
    headers = []
    if csrf_token:
        headers.append((b"x-csrf-token", csrf_token.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/campaigns",
            "query_string": b"",
            "headers": headers,
            "session": session or {},
        }
    )


def authentication_settings() -> SimpleNamespace:
    return SimpleNamespace(
        dev_auth_bypass=False,
        entra_tenant_id="tenant-id",
        entra_api_client_id="client-id",
    )


def test_session_user_is_authenticated_and_csrf_is_required(monkeypatch) -> None:
    monkeypatch.setattr(security, "get_settings", authentication_settings)
    session = {
        "user": {
            "subject": "employee-object-id",
            "email": "employee@example.com",
            "name": "Test Employee",
        },
        "csrf_token": "expected-token",
    }

    user = security.get_current_user(
        make_request("POST", session, "expected-token"),
        None,
    )
    assert user.email == "employee@example.com"

    with pytest.raises(HTTPException) as error:
        security.get_current_user(make_request("POST", session), None)
    assert error.value.status_code == 403


def test_auth_callback_stores_only_identity_claims(monkeypatch) -> None:
    class FakeClient:
        def acquire_token_by_auth_code_flow(self, flow, response):
            assert flow == {"state": "expected-state"}
            return {
                "id_token_claims": {
                    "oid": "employee-object-id",
                    "preferred_username": "employee@example.com",
                    "name": "Test Employee",
                }
            }

    monkeypatch.setattr(auth, "confidential_client", lambda: FakeClient())
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/auth/callback",
            "query_string": b"code=test&state=expected-state",
            "headers": [],
            "session": {"auth_flow": {"state": "expected-state"}},
        }
    )

    response = auth.auth_callback(request)

    assert response.status_code == 303
    assert request.session["user"]["email"] == "employee@example.com"
    assert "roles" not in request.session["user"]
    assert request.session["csrf_token"]
    assert "access_token" not in request.session


def test_entra_database_mode_injects_fresh_token(monkeypatch) -> None:
    captured: dict[str, object] = {}
    fake_engine = object()

    monkeypatch.setattr(
        database,
        "settings",
        SimpleNamespace(
            database_auth_mode="entra",
            database_url=(
                "postgresql+psycopg://cyber-awareness-workload@"
                "example.postgres.database.azure.com/cyber"
            ),
            azure_database_scope=(
                "https://ossrdbms-aad.database.windows.net/.default"
            ),
        ),
    )
    monkeypatch.setattr(database, "create_engine", lambda *args, **kwargs: fake_engine)

    def fake_listens_for(_engine, event_name):
        assert event_name == "do_connect"

        def decorator(function):
            captured["listener"] = function
            return function

        return decorator

    class FakeCredential:
        def get_token(self, scope):
            assert scope == "https://ossrdbms-aad.database.windows.net/.default"
            return SimpleNamespace(token="short-lived-database-token")

    monkeypatch.setattr(database.event, "listens_for", fake_listens_for)
    monkeypatch.setattr(
        database,
        "DefaultAzureCredential",
        lambda **kwargs: FakeCredential(),
    )

    assert database.create_database_engine() is fake_engine
    connection_parameters: dict[str, str] = {}
    captured["listener"](None, None, None, connection_parameters)
    assert connection_parameters == {
        "password": "short-lived-database-token",
        "sslmode": "require",
    }
