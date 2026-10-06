"""The /book route: the book's own bytes at their own paths, nothing rewritten."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import PNG, JPEG, write_epub  # noqa: E402


@pytest.fixture()
def uploaded(isolated_client, isolated):
    response = isolated_client.post(
        "/upload",
        files={"file": ("fixture.epub",
                        write_epub(isolated / "fixture.epub").read_bytes(),
                        "application/epub+zip")},
    )
    return isolated_client, response.json()["slug"]


def test_the_cover_comes_from_the_book_itself(uploaded):
    client, slug = uploaded
    response = client.get(f"/book/{slug}/OEBPS/img/cover.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content.startswith(JPEG[:8])


def test_the_url_the_browser_will_ask_for_is_normalised(uploaded):
    """Percent-encoding is resolved, not reported missing."""
    client, slug = uploaded
    response = client.get(f"/book/{slug}/OEBPS/img/plate%20one.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(PNG[:8])


def test_xhtml_goes_out_as_text_html(uploaded):
    """The rendering contract: XHTML is served as text/html, with a charset."""
    client, slug = uploaded
    response = client.get(f"/book/{slug}/OEBPS/ch1.xhtml")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert "The first paragraph" in response.content.decode("utf-8")


def test_css_keeps_its_declared_type(uploaded):
    client, slug = uploaded
    response = client.get(f"/book/{slug}/OEBPS/style.css")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/css; charset=utf-8"


def test_a_missing_member_is_a_404(uploaded):
    client, slug = uploaded
    assert client.get(f"/book/{slug}/OEBPS/no-such-file.css").status_code == 404


def test_traversal_cannot_leave_the_book(uploaded):
    client, slug = uploaded
    assert client.get(f"/book/{slug}/..%2F..%2Fserver.py").status_code == 404
    assert client.get(f"/book/{slug}/..%2F..%2F..%2Fpyproject.toml").status_code == 404
    assert client.get(f"/book/{slug}/OEBPS/..%2F..%2Fserver.py").status_code == 404


def test_an_unknown_book_is_a_404(uploaded):
    client, _ = uploaded
    assert client.get("/book/ghost/OEBPS/ch1.xhtml").status_code == 404