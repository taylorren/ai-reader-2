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


def test_the_environment_wins_over_the_env_file(tmp_path, monkeypatch):
    """P2-7: `load_env()` assigned unconditionally, so a variable set for real —
    `READER_PORT=9000 uv run server.py`, a systemd unit, a container — was
    silently replaced by whatever `.env` said, exactly when someone was trying
    to change it.
    """
    import os

    import server

    (tmp_path / ".env").write_text(
        "# a comment line\n"
        "READER_PORT=8123\n"
        "OLLAMA_BASE_URL=http://example.test:11434/v1\n"
        'OLLAMA_MODEL="hermes3:latest"\n'
    )
    monkeypatch.setattr(server, "BASE_DIR", tmp_path)
    monkeypatch.setenv("READER_PORT", "9000")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)

    server.load_env()

    assert os.environ["READER_PORT"] == "9000"                        # the environment wins
    assert os.environ["OLLAMA_BASE_URL"] == "http://example.test:11434/v1"
    assert os.environ["OLLAMA_MODEL"] == "hermes3:latest"             # quotes stripped


def test_a_missing_env_file_is_not_fatal(tmp_path, monkeypatch):
    import server

    monkeypatch.setattr(server, "BASE_DIR", tmp_path)
    server.load_env()          # prints a warning, raises nothing


def test_the_reviews_index_and_its_items_agree():
    """REVIEW.md's index is what a reader scans; an item's own heading and its
    `Review:` line are what they read next, and the three drifted apart — nine
    items were applied in the index while their items said neither. The
    agreement is now checked rather than trusted.

    The rule is narrow, because the file is allowed to change freely otherwise:
    an item the index marks `✔ applied` must say so in its heading and be
    `☑ accept` in its own line, and an item that is not applied must say neither.
    """
    import re

    from routers import BASE_DIR

    text = (BASE_DIR / "REVIEW.md").read_text()

    applied = {}
    for line in text.splitlines():
        match = re.match(r"^\| ((?:P\d+-\d+|T\d+)) \|", line)
        if match:
            applied[match.group(1)] = "✔" in line
    assert applied, "REVIEW.md's index table was not found"

    sections: dict[str, dict] = {}
    current = None
    for line in text.splitlines():
        heading = re.match(r"^### ((?:P\d+-\d+|T\d+)) ", line)
        if heading:
            current = heading.group(1)
            sections[current] = {"heading": line, "review": ""}
        elif line.startswith("### "):
            current = None
        elif current and not sections[current]["review"]:
            if line.startswith("**Review:**"):
                sections[current]["review"] = line

    assert set(sections) == set(applied), (
        "every indexed item needs its own section, and the other way round")

    for item_id, section in sections.items():
        is_applied = applied[item_id]
        assert ("✔ applied" in section["heading"]) is is_applied, (
            f"{item_id}: the index says applied={is_applied}, "
            f"its heading says otherwise")
        assert ("☑ accept" in section["review"]) is is_applied, (
            f"{item_id}: the index says applied={is_applied}, "
            f"its Review line disagrees")


def test_books_dir_points_at_the_repo_books_directory():
    from routers import BASE_DIR, BOOKS_DIR

    assert BOOKS_DIR == BASE_DIR / "books"
    assert (BASE_DIR / "SPEC.md").exists(), "BASE_DIR is not the repo root"
