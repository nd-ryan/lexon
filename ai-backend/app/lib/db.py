import os
from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL")
POSTGRES_SCHEMA = os.getenv("POSTGRES_SCHEMA", "public")


if not DATABASE_URL:
    # Allow import-time without env for tooling; runtime will fail fast on first use
    DATABASE_URL = "postgresql://user:password@localhost:5432/postgres"


# Neon pooled connections reject startup `options` like `-csearch_path=...`.
# Instead, set search_path *after* connecting (works with pooler and direct connections).
engine = create_engine(DATABASE_URL, pool_pre_ping=True)


@event.listens_for(engine, "connect")
def _set_search_path(dbapi_connection, _connection_record):
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute(f"SET search_path TO {POSTGRES_SCHEMA}")
        cursor.close()
    except Exception:
        # Don't hard-fail at import time; route handlers will surface DB errors.
        pass


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


