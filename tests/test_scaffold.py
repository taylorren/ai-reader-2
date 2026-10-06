"""The scaffold's shape: the app assembles, the routers exist, epubx resolves.

These tests assert structure, not behaviour — no endpoint exists yet. They are
expected to change as phases land (P1 gives `/` a real response).
"""

import importlib
import sys

import pytest
from fastapi import APIRouter, FastAPI

ROUTER_MODULES = ("library", "reader", "highlights", "ai", "settings")


def test_app_is_a_fastapi_app():
    import server

    assert isinstance(server.app, FastAPI)


def test_app_responds(isolated_client):
    """P1 gave `/` a real response: the library page renders."""
    response = isolated_client.get("/")
    assert response.status_code == 200
    assert "Add New Book" in response.text


def test_static_mount_is_registered():
    import server

    mounted = [r for r in server.app.routes if getattr(r, "name", None) == "static"]
    assert mounted, "the /static mount is missing"


@pytest.mark.parametrize("name", ROUTER_MODULES)
def test_every_router_module_exposes_a_router(name):
    module = importlib.import_module(f"routers.{name}")
    assert isinstance(module.router, APIRouter)


def test_routers_are_wired_into_the_app():
    """Importing server.py must import every router module (the wiring)."""
    import server  # noqa: F401

    for name in ROUTER_MODULES:
        assert f"routers.{name}" in sys.modules, f"routers.{name} is not wired in"


def test_epubx_dependency_resolves():
    """The one EPUB dependency must import — from the uv source or site-packages."""
    import epubx

    assert callable(epubx.open_book)
    assert hasattr(epubx, "Book")


def test_books_dir_points_at_the_repo_books_directory():
    from routers import BASE_DIR, BOOKS_DIR

    assert BOOKS_DIR == BASE_DIR / "books"
    assert (BASE_DIR / "SPEC.md").exists(), "BASE_DIR is not the repo root"
