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


def test_a_book_file_is_safe_to_open_directly_and_to_cache(uploaded):
    """T5: the headers that make a book file safe at this origin, and cheap to
    re-read.

    Opened directly — a bookmark, a copied link, a new tab — the URL is a
    top-level document at the app's origin, so a script the EPUB ships would run
    with access to /api/*; `script-src 'none'` closes that (REVIEW P2-1). And
    every chapter turn re-requests the chapter's own CSS, fonts and images, so
    the response carries a validator and a lifetime (REVIEW P2-3).
    """
    client, slug = uploaded
    url = f"/book/{slug}/OEBPS/ch1.xhtml"

    first = client.get(url)
    assert first.status_code == 200
    assert first.headers["content-security-policy"] == "script-src 'none'; object-src 'none'"
    assert first.headers["x-content-type-options"] == "nosniff"
    assert first.headers["cache-control"] == "public, max-age=3600"
    etag = first.headers["etag"]
    assert etag and first.content

    # The second read is a 304 with no body: the browser keeps what it has.
    second = client.get(url, headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.content == b""
    assert second.headers["etag"] == etag

    # A stale validator still gets the file, and `*` means "anything will do".
    assert client.get(url, headers={"If-None-Match": '"stale"'}).status_code == 200
    assert client.get(url, headers={"If-None-Match": "*"}).status_code == 304
    # A different member of the same book is a different resource.
    other = client.get(f"/book/{slug}/OEBPS/ch2.xhtml")
    assert other.headers["etag"] != etag


def test_the_validator_changes_when_the_book_does(uploaded, isolated):
    """A re-uploaded book must not keep serving a cached chapter.

    The same book again (so the upload replaces it in place), from a fresh
    archive: the file's stamp changes with it, which is what invalidates the
    browser's copy.
    """
    client, slug = uploaded
    url = f"/book/{slug}/OEBPS/ch1.xhtml"
    before = client.get(url).headers["etag"]

    replacement = write_epub(isolated / "again.epub")
    client.post("/upload", files={"file": ("again.epub", replacement.read_bytes(),
                                           "application/epub+zip")})

    after = client.get(url).headers["etag"]
    assert after != before
    # The old validator is stale now: the file is served again, not 304'd.
    assert client.get(url, headers={"If-None-Match": before}).status_code == 200


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