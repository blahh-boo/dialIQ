"""SQLAlchemy engine, session factory, and declarative base."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from mystery_shop.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the cached SQLAlchemy engine."""
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(),
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )


def get_session() -> Session:
    """Return a new SQLAlchemy session bound to the cached engine."""
    return _session_factory()()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Yield a session that commits on success and rolls back on exception."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
