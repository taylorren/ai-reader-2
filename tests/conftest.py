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

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)


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


@pytest.fixture
def upload(isolated_client, isolated):
    """Upload the synthetic fixture EPUB and return its slug.

    Every test that needs a book in the isolated library uses this; the
    fixture's chapters carry the footnote and block shapes the reader
    relies on (see tests/fixtures.py).
    """
    from fixtures import write_epub

    def _upload(name="fixture.epub"):
        response = isolated_client.post(
            "/upload",
            files={"file": (name, write_epub(isolated / name).read_bytes(),
                            "application/epub+zip")},
        )
        assert response.status_code == 200, response.text
        return response.json()["slug"]

    return _upload


@pytest.fixture(autouse=True)
def _reset_provider_override():
    """The provider override is in-memory state: never leak between tests."""
    import routers

    routers._runtime_settings["provider_override"] = None
    yield
    routers._runtime_settings["provider_override"] = None
