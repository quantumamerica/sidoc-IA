from __future__ import annotations

from typing import Any

from config.settings import Settings


def get_engine(settings: Settings) -> Any | None:
    if not settings.database_url:
        return None
    from sqlalchemy import create_engine

    return create_engine(settings.database_url, future=True)


def get_session(settings: Settings) -> Any:
    engine = get_engine(settings)
    if engine is None:
        raise RuntimeError("DATABASE_URL no configurada.")

    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=engine, future=True)()


def test_connection(settings: Settings) -> tuple[bool, str]:
    engine = get_engine(settings)
    if engine is None:
        return False, "DATABASE_URL no configurada."

    try:
        from sqlalchemy import inspect, text

        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        inspector = inspect(engine)
        if not inspector.has_table(settings.db_table_name):
            return False, f"Conecta, pero falta la tabla '{settings.db_table_name}'."

        return True, f"Conexion OK. Tabla encontrada: {settings.db_table_name}."
    except Exception as exc:
        return False, f"No conecta la DB: {exc}"


def create_database_engine(settings: Settings) -> Any | None:
    return get_engine(settings)
