"""P2: the reader shell, resume redirect, and the book API.

Model A: the shell serves the book's own document in a sandboxed iframe —
nothing from the book executes, and the shell rewrites nothing.

The guards at the top are T1's: the served shell, its scripts and its
stylesheets have to agree about the ids and classes they name."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import write_drm_epub, write_epub, write_sectioned_epub  # noqa: E402

# Ids a script looks up that the shell cannot carry because the script creates
# them itself.
SCRIPT_MADE_IDS = {"comment-input"}

# Classes a script names that its page's stylesheet deliberately does not
# define, each with the reason. Adding one here is a decision; the guard fails
# on a class that arrives without a reason, and on an entry that is no longer
# needed — a stale allowlist is how a guard rots.
#
# Empty since P3-2 landed (the reader panel's 编辑 button is styled now). The
# staleness check below is what emptied it: the moment `.action-link` had a rule
# on the reader page, the guard demanded the exemption's removal.
UNSTYLED_CLASSES: set[str] = set()


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


def test_the_scripts_only_look_up_ids_the_shell_has(isolated_client, isolated):
    """reader.js once died silently on a stale getElementById — the whole
    shell went dead (no TOC, no controls). This guards the whole class:
    every literal id the scripts look up must exist in the served shell.

    T1 extended it to panel.js's `el("…")` lookups and to reader-core.js: the
    same failure mode, in the scripts that own the panel."""
    slug = upload(isolated_client, isolated)
    shell = isolated_client.get(f"/read/{slug}/0").text

    wanted = set()
    for path in ("/static/js/reader.js", "/static/js/panel.js",
                 "/static/js/reader-core.js"):
        script = isolated_client.get(path).text
        wanted |= set(re.findall(r'getElementById\("([^"]+)"\)', script))
        wanted |= set(re.findall(r'\bel\("([^"]+)"\)', script))

    missing = [eid for eid in sorted(wanted - SCRIPT_MADE_IDS)
               if f'id="{eid}"' not in shell]
    assert not missing, f"the scripts look up ids the shell lacks: {missing}"
    assert len(wanted) > 15, f"the id extraction found almost nothing: {wanted}"


# -- the served front end's own contract (T1) ------------------------------

def page_assets(client, page: str) -> tuple[list[str], list[str]]:
    """A served page's own stylesheets and scripts, query strings stripped."""
    sheets = [href.split("?")[0] for href in
              re.findall(r'<link rel="stylesheet" href="([^"]+)"', page)]
    scripts = [src.split("?")[0] for src in
               re.findall(r'<script src="([^"]+)"', page)
               if "/static/vendor/" not in src]
    return sheets, scripts


def css_classes(css: str) -> set[str]:
    """Every class a stylesheet defines a rule for."""
    return set(re.findall(r"\.([A-Za-z_][-\w]*)", css))


def script_classes(script: str) -> tuple[set[str], set[str]]:
    """(classes, prefixes) a script names in its own source.

    `className = "toast visible"`, `classList.add("flash")`, the `class="…"`
    inside HTML it builds, and a concatenated prefix such as
    `"reader-highlight hl-" + kind` — the last returned as the bare prefix, for
    the caller to expand against the kinds the script knows.
    """
    found = set()
    for pattern in (r'className = "([^"]*)"',
                    r'classList\.(?:add|remove|toggle|contains)\("([^"]+)"',
                    r'class="([^"]+)"'):
        for literal in re.findall(pattern, script):
            found.update(literal.split())
    found = {name for name in found if "$" not in name and "{" not in name}
    return ({name for name in found if not name.endswith("-")},
            {name for name in found if name.endswith("-")})


def highlight_kinds(script: str) -> set[str]:
    """The highlight kinds a script knows, from its KIND_COLORS table."""
    block = re.search(r"KIND_COLORS = \{(.*?)\n    \};", script, re.S)
    return set(re.findall(r"(\w+):", block.group(1))) if block else set()


def test_every_class_the_scripts_name_has_a_rule_in_the_stylesheet_the_page_loads(
        isolated_client, isolated):
    """The class guard T1 asks for, extending the id guard above.

    A class a script sets but no stylesheet defines is a silent no-op: the toast
    shipped with `className = "toast visible"` and no `.toast.visible` rule, so
    every notification the reader showed stayed invisible (P1-1).

    The reader's frame is part of its stylesheet surface — the CSS reader.js
    injects into the book's document is what styles the marks, the flash and the
    resume rule — so it is collected here too. Every page the app serves is
    checked, and the guard fails on an exemption that is no longer needed.
    """
    slug = upload(isolated_client, isolated)
    pages = {f"/read/{slug}/0": "reader",
             "/": "library",
             f"/highlights/{slug}": "highlights"}

    unstyled_anywhere = set()
    named_anywhere = set()
    for path, name in pages.items():
        page = isolated_client.get(path).text
        sheets, scripts = page_assets(isolated_client, page)
        assert sheets and scripts, f"{name}: no stylesheets or scripts found"

        css = "".join(isolated_client.get(sheet).text for sheet in sheets)
        sources = [isolated_client.get(script).text for script in scripts]
        if name == "reader":
            # The frame's own stylesheet: the CSS the shell injects into the
            # book's document, kept in reader.js as template literals.
            for source in sources:
                css += "\n".join(
                    re.findall(r"const [A-Z_]+_CSS = `(.*?)`;", source, re.S))

        styled = css_classes(css)
        named, prefixes = set(), set()
        kinds = set()
        for source in sources:
            classes, found_prefixes = script_classes(source)
            named |= classes
            prefixes |= found_prefixes
            kinds |= highlight_kinds(source)

        assert named, f"{name}: the class extraction found nothing at all"

        # A prefix is not a class: `"hl-" + kind` builds one of the kinds the
        # script knows, and each of those must have a rule — which is how a new
        # highlight kind without a colour gets caught.
        for prefix in sorted(prefixes):
            assert kinds, f"{name}: {prefix!r} is a prefix but no kinds were found"
            missing = sorted({prefix + kind for kind in kinds} - styled)
            assert not missing, (
                f"{name}: the scripts build these classes by prefix {prefix!r} "
                f"but no stylesheet defines them: {missing}")

        unstyled_anywhere |= named - styled
        named_anywhere |= named
        assert not named - styled - UNSTYLED_CLASSES, (
            f"{name}: these classes are set by the page's scripts but no "
            f"stylesheet the page loads defines them: "
            f"{sorted(named - styled - UNSTYLED_CLASSES)}")

    # A guard that quietly stops finding anything is worse than no guard.
    assert len(named_anywhere) > 20, (
        f"the class extraction found only {len(named_anywhere)} classes across "
        f"three pages — check the patterns in script_classes()")

    stale = UNSTYLED_CLASSES - unstyled_anywhere
    assert not stale, (
        f"these classes are exempt in UNSTYLED_CLASSES but every page now styles "
        f"them — delete them: {sorted(stale)}")


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


def test_the_shell_asset_version_covers_every_asset_it_loads(
        isolated_client, isolated):
    """Every script and stylesheet the shell loads must be in the cache-busting
    token, or a browser that has an old copy keeps it — and the fixes never
    arrive.

    Derived from the served page rather than from a list kept here (T1): adding
    a script to the shell without adding it to the router's list now fails this
    test, which is exactly the drift it exists to catch.
    """
    from routers import get_asset_version

    slug = upload(isolated_client, isolated)
    body = isolated_client.get(f"/read/{slug}/0").text
    assets = [href for href in re.findall(
        r'(?:src|href)="(/static/(?:js|css)/[^"]+)"', body)]
    assert assets, "the shell loads no local assets"

    token = str(get_asset_version(*(asset.split("?")[0].lstrip("/")
                                    for asset in assets)))
    unversioned = [asset for asset in assets if f"?v={token}" not in asset]
    assert not unversioned, (
        f"the shell's ?v= tokens do not match the token over the assets it loads "
        f"(?v={token}) — is every asset in the router's get_asset_version list? "
        f"{unversioned}")

    # The order is load-bearing: panel.js and reader.js take their pure helpers
    # from window.ReaderCore at load, so the module has to come first or the
    # whole panel is dead.
    order = [asset.split("?")[0] for asset in assets]
    for dependent in ("/static/js/panel.js", "/static/js/reader.js"):
        assert order.index("/static/js/reader-core.js") < order.index(dependent), (
            f"reader-core.js must load before {dependent}")


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