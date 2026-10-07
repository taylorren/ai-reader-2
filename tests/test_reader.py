"""P2: the reader shell, resume redirect, and the book API.

Model A: the shell serves the book's own document in a sandboxed iframe —
nothing from the book executes, and the shell rewrites nothing."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import unquote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import write_drm_epub, write_epub  # noqa: E402


def upload(client, isolated, builder=write_epub, name="fixture.epub"):
    response = client.post(
        "/upload",
        files={"file": (name, builder(isolated / name).read_bytes(),
                        "application/epub+zip")},
    )
    assert response.status_code == 200, response.text
    return response.json()["slug"]


def test_the_library_link_resumes_or_starts_at_chapter_zero(
        isolated_client, isolated):
    slug = upload(isolated_client, isolated)
    response = isolated_client.get(f"/read/{slug}", follow_redirects=False)
    assert response.status_code == 307
    assert unquote(response.headers["location"]) == f"/read/{slug}/0"


def test_reader_js_only_looks_up_ids_the_shell_has(isolated_client, isolated):
    """reader.js once died silently on a stale getElementById — the whole
    shell went dead (no TOC, no controls). This guards the whole class:
    every literal id the script looks up must exist in the served shell."""
    import re

    slug = upload(isolated_client, isolated)
    shell = isolated_client.get(f"/read/{slug}/0").text
    script = isolated_client.get("/static/js/reader.js").text

    wanted = set(re.findall(r'getElementById\("([^"]+)"\)', script))
    missing = [eid for eid in sorted(wanted) if f'id="{eid}"' not in shell]
    assert not missing, f"reader.js looks up ids the shell lacks: {missing}"


def test_the_shell_serves_the_books_own_document(isolated_client, isolated):
    slug = upload(isolated_client, isolated)
    response = isolated_client.get(f"/read/{slug}/0")
    assert response.status_code == 200
    body = response.text
    # The frame loads the chapter at its own path — nothing rewritten.
    assert 'sandbox="allow-same-origin"' in body
    assert 'src="/book/Fixture%20Book/OEBPS/ch1.xhtml"' in body
    # The reference design: a sidebar with a way home and a collapse control.
    assert "返回图书馆" in body
    assert 'id="sidebar-collapse"' in body
    assert 'id="sidebar-expand"' in body
    # Reading controls: a font selector (Chinese and English families) and a
    # paper/book switch (not a flipper).
    assert 'id="font-select"' in body
    assert 'value="ensans"' in body and 'value="enserif"' in body
    assert 'role="switch"' in body
    # Chapter navigation: the same nav component sits centered in the header
    # and in the footer — one style, recognizable in both places.
    assert 'id="top-prev"' in body
    assert 'id="bottom-prev"' in body
    assert body.count('class="chapter-nav') == 2
    # The shell hands the spine and TOC to its script.
    assert "OEBPS/ch2.xhtml" in body
    assert '"label": "Chapter Two"' in body or '"label":"Chapter Two"' in body


def test_the_shell_of_a_later_chapter(isolated_client, isolated):
    slug = upload(isolated_client, isolated)
    response = isolated_client.get(f"/read/{slug}/1")
    assert response.status_code == 200
    assert 'src="/book/Fixture%20Book/OEBPS/ch2.xhtml"' in response.text


def test_chapter_out_of_range_is_a_404(isolated_client, isolated):
    slug = upload(isolated_client, isolated)
    assert isolated_client.get(f"/read/{slug}/2").status_code == 404
    assert isolated_client.get(f"/read/{slug}/-1").status_code == 404


def test_an_unknown_book_is_a_404(isolated_client):
    assert isolated_client.get("/read/ghost/0").status_code == 404
    assert isolated_client.get("/read/ghost", follow_redirects=False).status_code == 404


def test_a_non_numeric_chapter_is_rejected(isolated_client, isolated):
    slug = upload(isolated_client, isolated)
    assert isolated_client.get(f"/read/{slug}/zero").status_code == 422


def test_the_book_api_reports_spine_and_toc(isolated_client, isolated):
    slug = upload(isolated_client, isolated)
    payload = isolated_client.get(f"/api/book/{slug}").json()
    assert payload["title"] == "Fixture Book"
    assert payload["chapter_count"] == 2
    assert payload["spine"] == ["OEBPS/ch1.xhtml", "OEBPS/ch2.xhtml"]
    assert [node["label"] for node in payload["toc"]] == [
        "Chapter One", "Chapter Two"]
    assert payload["toc"][0]["href"] == "OEBPS/ch1.xhtml"
    assert payload["unsupported"] is None


def test_the_book_api_for_an_unknown_slug_is_a_404(isolated_client):
    assert isolated_client.get("/api/book/ghost").status_code == 404


def test_the_footnote_api_returns_the_resolved_edges(isolated_client, isolated):
    slug = upload(isolated_client, isolated)
    payload = isolated_client.get(f"/api/footnotes/{slug}/0").json()
    edges = payload["edges"]
    assert [e["href"] for e in edges] == [
        "#local-note", "ch2.xhtml#endnote-1", "ch2.xhtml#no-such-note",
    ]
    assert edges[0]["resolved"] is True
    assert edges[0]["target_chapter"] == 0
    assert edges[0]["target_text"] == "The local note."
    assert edges[1]["target_chapter"] == 1
    assert edges[1]["target_anchor"] == "endnote-1"
    assert edges[2]["resolved"] is False


def test_the_footnote_api_for_a_bad_chapter_is_a_404(isolated_client, isolated):
    slug = upload(isolated_client, isolated)
    assert isolated_client.get(f"/api/footnotes/{slug}/7").status_code == 404
    assert isolated_client.get("/api/footnotes/ghost/0").status_code == 404


def test_the_shell_carries_the_footnote_popup(isolated_client, isolated):
    slug = upload(isolated_client, isolated)
    body = isolated_client.get(f"/read/{slug}/0").text
    assert 'id="footnote-popup"' in body


def test_progress_is_saved_and_restored(isolated_client, isolated, db):
    slug = upload(isolated_client, isolated)
    response = isolated_client.post(
        "/api/progress",
        json={"book_id": slug, "chapter_index": 1, "scroll_percent": 42.0},
    )
    assert response.status_code == 200
    progress = db.get_progress(slug)
    assert progress["chapter_index"] == 1
    assert progress["scroll_percent"] == 42.0

    # The resume link and the shell both honour it.
    redirect = isolated_client.get(f"/read/{slug}", follow_redirects=False)
    assert unquote(redirect.headers["location"]) == f"/read/{slug}/1"
    body = isolated_client.get(f"/read/{slug}/1").text
    assert '"saved_percent": 42' in body or '"saved_percent":42' in body


def test_progress_rejects_a_bad_chapter_and_unknown_book(
        isolated_client, isolated):
    slug = upload(isolated_client, isolated)
    bad_chapter = isolated_client.post(
        "/api/progress",
        json={"book_id": slug, "chapter_index": 99, "scroll_percent": 5},
    )
    assert bad_chapter.status_code == 400
    unknown = isolated_client.post(
        "/api/progress",
        json={"book_id": "ghost", "chapter_index": 0, "scroll_percent": 5},
    )
    assert unknown.status_code == 404


def test_the_shell_asset_version_covers_the_panel(isolated_client, isolated):
    """panel.js must be in the cache-busting token, or a browser that has the
    old copy keeps it — and the panel's fixes never arrive."""
    from routers import get_asset_version

    slug = upload(isolated_client, isolated)
    body = isolated_client.get(f"/read/{slug}/0").text
    expected = str(get_asset_version(
        "static/js/reader.js", "static/js/panel.js", "static/css/reader.css"))
    assert expected in body


def test_the_shell_carries_a_highlight_deep_link(isolated_client, isolated):
    """?highlight=<id> reaches the shell, so "在书中定位" can scroll to it."""
    slug = upload(isolated_client, isolated)
    body = isolated_client.get(f"/read/{slug}/0?highlight=7").text
    assert '"target_highlight": "7"' in body or '"target_highlight":"7"' in body
    # Without the parameter the shell carries an empty target.
    plain = isolated_client.get(f"/read/{slug}/0").text
    assert '"target_highlight": ""' in plain or '"target_highlight":""' in plain


def test_an_unsupported_book_gets_a_named_shell(isolated_client, isolated):
    slug = upload(isolated_client, isolated, write_drm_epub, "locked.epub")
    response = isolated_client.get(f"/read/{slug}/0")
    assert response.status_code == 200
    body = response.text
    assert "无法打开此书" in body
    assert "drm" in body
    assert "<iframe" not in body  # no frame for a book that cannot render