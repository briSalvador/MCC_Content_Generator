from collections.abc import Generator

from azure.identity import DefaultAzureCredential
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()


def create_database_engine() -> Engine:
    if settings.database_auth_mode == "entra" and not settings.database_url.startswith(
        ("postgresql://", "postgresql+psycopg://")
    ):
        raise RuntimeError(
            "DATABASE_AUTH_MODE=entra currently supports Azure Database for "
            "PostgreSQL only"
        )

    connect_args = (
        {"check_same_thread": False}
        if settings.database_url.startswith("sqlite")
        else {}
    )
    database_engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_recycle=3000,
        connect_args=connect_args,
    )

    if settings.database_auth_mode == "entra":
        credential = DefaultAzureCredential(
            exclude_interactive_browser_credential=True
        )

        @event.listens_for(database_engine, "do_connect")
        def add_entra_database_token(
            _dialect,
            _connection_record,
            _connection_args,
            connection_parameters,
        ) -> None:
            token = credential.get_token(settings.azure_database_scope).token
            connection_parameters["password"] = token
            connection_parameters.setdefault("sslmode", "require")

    return database_engine


engine = create_database_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def ensure_schema_compatibility() -> None:
    """Apply small additive migrations for existing starter databases."""
    inspector = inspect(engine)
    if "campaigns" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("campaigns")}
    if "additional_prompt" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE campaigns "
                    "ADD COLUMN additional_prompt TEXT NOT NULL DEFAULT ''"
                )
            )
    if "poster_content_json" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE campaigns ADD COLUMN poster_content_json TEXT")
            )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
