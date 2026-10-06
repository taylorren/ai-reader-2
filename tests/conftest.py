"""Shared fixtures.

Repo-root imports (`server`, `routers`, `database`) must work regardless of the
CWD, exactly as they do in ai-reader.
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


@pytest.fixture
def client():
    """A TestClient for the real app, against the developer's real database.

    Only for tests that do not touch stored data — use `isolated_client`
    for anything that uploads, deletes or writes rows.
    """
    import server

    with TestClient(server.app) as test_client:
        yield test_client


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """A private library for one test: its own books dir and database."""
    import routers

    books = tmp_path / "books"
    books.mkdir()
    monkeypatch.setattr(routers, "BOOKS_DIR", books)
    monkeypatch.setattr(routers, "DB_PATH", tmp_path / "reader_data.db")
    monkeypatch.setattr(routers, "_db", None)
    yield tmp_path
    routers.book_cache.clear()


@pytest.fixture
def isolated_client(isolated):
    import server

    with TestClient(server.app) as test_client:
        yield test_client


@pytest.fixture
def db(isolated):
    """The isolated test's database, for direct row setup and checks."""
    from database import Database

    return Database(isolated / "reader_data.db")
