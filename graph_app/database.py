"""SQLite setup for the local project graph."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "project_graph.sqlite3"


class Base(DeclarativeBase):
    pass


def database_url(database_path: str | Path | None = None) -> str:
    path = Path(database_path or os.getenv("YONC_GRAPH_DB") or DEFAULT_DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.resolve().as_posix()}"


def make_engine(database_path: str | Path | None = None):
    return create_engine(
        database_url(database_path),
        connect_args={"check_same_thread": False},
        future=True,
    )


def make_session_factory(database_path: str | Path | None = None):
    return sessionmaker(bind=make_engine(database_path), autoflush=False, expire_on_commit=False)
