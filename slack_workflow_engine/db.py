"""Database engine and session utilities."""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from slack_workflow_engine import get_settings

Base = declarative_base()


@lru_cache()
def get_engine() -> Engine:
    """Create or return a cached SQLAlchemy engine."""

    settings = get_settings()
    return create_engine(settings.database_url, future=True, echo=False)


@lru_cache()
def get_session_factory() -> sessionmaker[Session]:
    """Return a cached session factory bound to the engine."""

    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Provide a transactional scope for DB operations."""

    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:  # pragma: no cover - exercised indirectly
        session.rollback()
        raise
    finally:
        session.close()
