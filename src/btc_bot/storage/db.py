"""SQLAlchemy engine + session factory."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from btc_bot.storage.models import Base

_engine = None
_SessionLocal = None


def init_db(database_url: str) -> None:
    global _engine, _SessionLocal
    # Normalise driver: prefer psycopg2 for Windows SSL compatibility
    url = database_url.replace("postgresql+psycopg://", "postgresql+psycopg2://")
    import urllib.parse
    url = urllib.parse.unquote(url)  # decode %23 -> # etc.
    _engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def create_tables() -> None:
    assert _engine is not None, "Call init_db() first."
    Base.metadata.create_all(_engine)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    assert _SessionLocal is not None, "Call init_db() first."
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def health_check() -> bool:
    try:
        with get_session() as s:
            s.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
