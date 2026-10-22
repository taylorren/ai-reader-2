"""P2: the reader shell, resume redirect, and the book API.

Model A: the shell serves the book's own document in a sandboxed iframe —
nothing from the book executes, and the shell rewrites nothing."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import unquote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import write_drm_epub, write_epub, write_sectioned_epub  # noqa: E402


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


def test_every_toast_class_has_a_rule_in_reader_css(isolated_client):
    """The same class of bug as the id guard above, for CSS classes: `toast()`
    builds its className from literals in panel.js, and every one of them must
    have a rule in the stylesheet the reader page loads. The toast shipped with
    `className = "toast visible"` and no `.toast.visible` rule, so every message
    the reader showed — saves, deletes, AI failures, the named "本章有 N 条高亮
    未能定位" warning — stayed at `opacity: 0`: silent.

    Scoped to the toast rather than to every class in the reader scripts: some
    classes are painted into the frame (which loads no shell stylesheet, e.g.
    `reader-highlight` / `hl-*`) or belong to another page's stylesheet
    (`.action-link`, REVIEW P3-2), so a blanket guard would fail on unrelated,
    deliberate cases.
    """
    import re

    script = isolated_client.get("/static/js/panel.js").text
    stylesheet = isolated_client.get("/static/css/reader.css").text

    # The class literals `toast()` assigns ...
    body = re.search(r"function toast\([^)]*\)\s*\{(.*?)\n    \}", script, re.S)
    assert body, "toast() not found in panel.js — update this guard with it"
    classes = set()
    for literal in re.findall(r'className = "([^"]*)"', body.group(1)):
        classes.update(literal.split())
    # ... plus the optional `kind` at every call site (`toast(msg, "error")`).
    classes.update(re.findall(r'toast\([^)]*,\s*"([^"]+)"\s*\)', script))

    # If the extraction ever stops finding what is there, fail loudly instead of
    # passing on an empty set.
    assert {"toast", "visible"} <= classes, f"toast() classes changed: {classes}"
    missing = [name for name in sorted(classes)
               if not re.search(rf"\.{re.escape(name)}(?![\w-])", stylesheet)]
    assert not missing, f"toast() sets classes reader.css never styles: {missing}"


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


def test_the_shell_hands_over_the_toc_anchors(isolated_client, isolated):
    """The TOC highlight follows the heading, not merely the chapter. Sections
    named inside one document share the chapter's href, so the shell must carry
    the fragment (`anchor`) for reader.js to tell those entries apart — without
    it every one of them looks like the chapter's own entry."""
    slug = upload(isolated_client, isolated, write_sectioned_epub,
                  "sectioned.epub")
    chapter = isolated_client.get(f"/api/book/{slug}").json()["toc"][0]
    assert chapter["href"] == "OEBPS/ch1.xhtml" and chapter["anchor"] is None
    assert [n["anchor"] for n in chapter["children"]] == ["sec-a", "sec-b"]

    # The same entries reach the reading shell itself.
    body = isolated_client.get(f"/read/{slug}/0").text
    assert '"anchor": "sec-a"' in body or '"anchor":"sec-a"' in body
    assert '"anchor": "sec-b"' in body or '"anchor":"sec-b"' in body


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


def test_the_shell_carries_no_resume_notice(isolated_client, isolated):
    """A restored position is silent: the notice's chapter + percent misled.

    The in-text resume rule stays; only the bar's announcement is gone.
    """
    slug = upload(isolated_client, isolated)
    body = isolated_client.get(f"/read/{slug}/0").text
    assert 'id="resume-notice"' not in body
    assert "已回到上次阅读位置" not in body


def test_the_shell_loads_its_scripts_from_the_repo(isolated_client, isolated):
    """No runtime CDN: marked/DOMPurify come from static/vendor."""
    slug = upload(isolated_client, isolated)
    body = isolated_client.get(f"/read/{slug}/0").text
    assert "/static/vendor/marked.min.js" in body
    assert "/static/vendor/purify.min.js" in body
    assert "cdn.jsdelivr.net" not in body
    assert isolated_client.get("/static/vendor/marked.min.js").status_code == 200


def test_an_unsupported_book_gets_a_named_shell(isolated_client, isolated):
    slug = upload(isolated_client, isolated, write_drm_epub, "locked.epub")
    response = isolated_client.get(f"/read/{slug}/0")
    assert response.status_code == 200
    body = response.text
    assert "无法打开此书" in body
    assert "drm" in body
    assert "<iframe" not in body  # no frame for a book that cannot render