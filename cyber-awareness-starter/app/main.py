from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.database import Base, engine, ensure_schema_compatibility
from app.routers.auth import router as auth_router
from app.routers.campaigns import router as campaigns_router
from app.services.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_authentication_configuration()
    Base.metadata.create_all(bind=engine)
    ensure_schema_compatibility()
    start_scheduler()
    yield
    stop_scheduler()


settings = get_settings()


def validate_authentication_configuration() -> None:
    if settings.dev_auth_bypass:
        return
    if not settings.entra_web_login_configured:
        raise RuntimeError(
            "Employee login is enabled but the ENTRA_* web login settings are incomplete"
        )
    if (
        len(settings.session_secret) < 32
        or settings.session_secret.startswith("replace-with-")
    ):
        raise RuntimeError(
            "SESSION_SECRET must be replaced with at least 32 random characters"
        )


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    max_age=settings.session_max_age_seconds,
    same_site="lax",
    https_only=settings.session_cookie_secure,
)
app.include_router(auth_router)
app.include_router(campaigns_router, prefix="/api")

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/health", tags=["operations"])
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(static_dir / "index.html")
