"""DB interaction module (course requirement §2.2): the only component that
talks to the database directly. Everything else (backend, ingestion) reaches
data through this service's HTTP API — see app/main.py.

Uses synchronous SQLAlchemy, dispatched onto FastAPI's threadpool by
declaring endpoints as plain `def` rather than `async def` (the standard
pattern for a blocking DB driver under an async framework). This sidesteps
SQLAlchemy's asyncio mode, which depends on the `greenlet` C extension —
whose prebuilt wheel does not load on the bleeding-edge Python used here.

DATABASE_URL defaults to a local SQLite file for zero-setup development.
Point it at a PostgreSQL DSN (e.g. postgresql+psycopg2://user:pass@host/db)
for the production/course-defense deployment described in docker-compose.yml.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data.db")

connect_args = (
    {"check_same_thread": False, "timeout": 30} if DATABASE_URL.startswith("sqlite") else {}
)
engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
