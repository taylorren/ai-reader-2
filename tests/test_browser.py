"""T1's browser smoke: the reader shell driven by a real browser.

Everything else in the suite drives the reader's JavaScript against a stub DOM
(tests/js/) or asserts server-rendered HTML. Four of the review's findings live
in the browser's own rules and can only be seen here:

    P3-3   a shown toast's *computed* opacity — the class was set, the rule was
           missing, so the message reached the DOM and stayed invisible
    P1-4   a saved mark, actually painted into the frame's document, on the
           first load and again after a reload
    P2-1   the book's own <script>, which must never execute — neither inside
           the reader nor when the book's document is opened directly
    P2-10  a mark on the second of two identical sentences, which needs a real
           Range: the capture reads the context from the document around it —
           and a reading position, stored by block rather than by percent alone

The whole module skips unless playwright and its browser are both present:

    uv add --dev playwright && uv run playwright install chromium

That is the one dependency the suite cannot work around, and the findings here
are exactly the ones a stub DOM cannot see: a stylesheet rule that never
applied, a sandbox that did its job.
"""

from __future__ import annotations

import socket
import threading
import time
from urllib.parse import quote

import pytest

sync_api = pytest.importorskip(
    "playwright.sync_api",
    reason="playwright is not installed (uv add --dev playwright)",
)

import httpx  # noqa: E402

from fixtures import (  # noqa: E402
    write_epub,
    write_inline_epub,
    write_latex_epub,
    write_long_epub,
    write_repeated_epub,
    write_scripted_epub,
)


# -- the app, over real HTTP ------------------------------------------------

@pytest.fixture
def base_url(isolated):
    """The real app on a real port, over the `isolated` fixture's directories.

    A browser cannot drive an ASGI object, so uvicorn runs in a thread against
    the same module globals the fixture patched: the pages a browser loads are
    the isolated library's, never the developer's.
    """
    import uvicorn

    import server

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    instance = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1",
                                             port=port, log_level="warning"))
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not instance.started and time.time() < deadline:
        time.sleep(0.02)
    if not instance.started:
        raise RuntimeError("the test server did not start")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        instance.should_exit = True
        thread.join(timeout=15)


@pytest.fixture(scope="module")
def browser():
    """One Chromium for the module — or a skip that says how to get one."""
    with sync_api.sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch()
        except Exception as error:        # noqa: BLE001 — the message is the reason
            pytest.skip(f"playwright's browser is not installed: {error}")
        yield instance
        instance.close()


# -- helpers ----------------------------------------------------------------

def upload_book(base_url, path, name="book.epub"):
    """Upload a fixture EPUB the way the library page's own form does."""
    with httpx.Client(base_url=base_url, timeout=30) as client:
        response = client.post("/upload", files={
            "file": (name, path.read_bytes(), "application/epub+zip")})
    assert response.status_code == 200, response.text
    return response.json()["slug"]


def chapter_payload(base_url, slug, index=0):
    with httpx.Client(base_url=base_url, timeout=30) as client:
        response = client.get(f"/api/text/{quote(slug)}/{index}")
    assert response.status_code == 200, response.text
    return response.json()


def stored_highlights(base_url, slug, index=0):
    """A chapter's stored marks, as the panel's own API returns them."""
    with httpx.Client(base_url=base_url, timeout=30) as client:
        response = client.get(f"/api/highlights/{quote(slug)}/{index}")
    assert response.status_code == 200, response.text
    return response.json()["highlights"]


def seed_highlight(base_url, slug, selected_text, block_id=None, index=0):
    """A stored mark, through the route that exists to store exactly that."""
    with httpx.Client(base_url=base_url, timeout=30) as client:
        response = client.post("/api/highlight", json={
            "book_id": slug, "chapter_index": index,
            "selected_text": selected_text, "block_id": block_id})
    assert response.status_code == 200, response.text
    return response.json()["highlight_id"]


def collapsed(text):
    """Text with its whitespace flattened: the spacing is the book's, not ours."""
    return " ".join(text.split())


def settled_opacity(page, selector, deadline=2.0):
    """The computed opacity once the transition has settled.

    `.toast.visible` carries a transition, so the value read the instant the
    class lands is mid-flight — 0.07, not 1 — and asserting on it would fail
    the fix it is meant to pin. Polling to a deadline also keeps a failure a
    value to read rather than a timeout to interpret.
    """
    end = time.time() + deadline
    while True:
        opacity = page.eval_on_selector(
            selector, "node => getComputedStyle(node).opacity")
        if opacity == "1" or time.time() >= end:
            return opacity
        time.sleep(0.05)


def stored_progress(isolated, slug):
    """The stored position row, read from the same database the server uses."""
    from database import Database

    return Database(isolated / "reader_data.db").get_progress(slug)


def save_progress(base_url, slug, **fields):
    payload = {"book_id": slug, "chapter_index": 0, "scroll_percent": 0}
    payload.update(fields)
    with httpx.Client(base_url=base_url, timeout=30) as client:
        response = client.post("/api/progress", json=payload)
    assert response.status_code == 200, response.text


def stored_settings(base_url):
    """What the server reports the AI provider is — the route the panel reads."""
    with httpx.Client(base_url=base_url, timeout=30) as client:
        response = client.get("/api/settings")
    assert response.status_code == 200, response.text
    return response.json()


def save_analysis(base_url, slug, kind, index=0, text="a saved line of the book"):
    """A stored mark with one analysis of `kind` — no AI involved."""
    with httpx.Client(base_url=base_url, timeout=30) as client:
        response = client.post("/api/ai/save", json={
            "analysis_type": kind, "response": f"the {kind} body",
            "book_id": slug, "chapter_index": index, "selected_text": text})
    assert response.status_code == 200, response.text


def block_named(blocks, prefix):
    """The block whose text starts with `prefix` — the fixture names them."""
    return next(block for block in blocks if block["text"].startswith(prefix))


def assert_mark(page, snippet, highlight_id):
    """The frame carries the mark, wrapped around exactly the saved text."""
    mark = page.frame_locator("#chapter-frame").locator(
        "mark.reader-highlight").first
    mark.wait_for()
    assert mark.get_attribute("data-highlight-id") == str(highlight_id)
    assert collapsed(mark.inner_text()) == collapsed(snippet)


# -- the three things only a browser can see --------------------------------

def test_a_shown_toast_is_actually_visible(browser, base_url, upload):
    """P3-3: `toast()` set the class `visible` and reader.css had no rule for
    it, so the message reached the DOM and stayed at `opacity: 0` — invisible
    on screen. A stub DOM cannot see a stylesheet rule that never applied.

    The trigger is a stored highlight whose text is not in the chapter: the
    shell reports it (「本章有 N 条高亮未能定位」) rather than losing it
    silently, which needs no AI, no clipboard and no key press.
    """
    slug = upload()
    seed_highlight(base_url, slug, "这段文字不在这一章里")

    page = browser.new_page()
    try:
        page.goto(f"{base_url}/read/{quote(slug)}/0")
        toast = page.locator("#toast")
        page.wait_for_function(
            "document.querySelector('#toast').classList.contains('visible')")
        assert toast.inner_text() == "本章有 1 条高亮未能定位"
        assert settled_opacity(page, "#toast") == "1", (
            "the toast carries the class `visible` and is still invisible — "
            "reader.css has no rule for it")
    finally:
        page.close()


def test_a_saved_mark_is_painted_into_the_frame(browser, base_url, upload):
    """P1-4: a highlight row is not a mark on screen until the shell paints it
    into the frame's own document. Painted on the first load, and painted again
    after a reload — which is where a saved mark has to come back from.
    """
    slug = upload()
    payload = chapter_payload(base_url, slug)
    block = next(item for item in payload["blocks"] if item["kind"] == "paragraph")
    snippet = block["text"][:40]
    highlight_id = seed_highlight(base_url, slug, snippet, block["id"])

    page = browser.new_page()
    try:
        page.goto(f"{base_url}/read/{quote(slug)}/0")
        assert_mark(page, snippet, highlight_id)

        page.reload()
        assert_mark(page, snippet, highlight_id)
    finally:
        page.close()


def test_a_books_own_script_never_runs(browser, base_url, isolated):
    """P2-1's other half: the reader serves the book's bytes untouched, so a
    book's `<script>` and its inline handler do reach the browser — and must
    not execute. Inside the reader the frame's sandbox stops them (it grants
    `allow-same-origin`, never `allow-scripts`); opened directly, the
    response's `Content-Security-Policy: script-src 'none'` does.

    The control at the end fetches the same document with that header stripped
    away, and the markers appear — so their absence above is the guard doing
    the work, not a fixture that could never have run in the first place.
    """
    slug = upload_book(base_url, write_scripted_epub(isolated / "scripted.epub"))
    chapter_path = chapter_payload(base_url, slug)["chapter_path"]

    page = browser.new_page()
    try:
        page.goto(f"{base_url}/read/{quote(slug)}/0")
        frame = page.frame_locator("#chapter-frame")
        frame.locator("h1").wait_for()          # the chapter really rendered
        assert frame.locator("html").get_attribute("data-book-script-ran") is None
        assert frame.locator("html").get_attribute("data-book-handler-ran") is None

        page.goto(f"{base_url}/book/{quote(slug)}/{chapter_path}")
        assert page.locator("html").get_attribute("data-book-script-ran") is None
        assert page.locator("html").get_attribute("data-book-handler-ran") is None
    finally:
        page.close()

    context = browser.new_context()
    control = context.new_page()
    try:
        def strip_csp(route):
            response = route.fetch()
            headers = {name: value for name, value in response.headers.items()
                       if name.lower() != "content-security-policy"}
            route.fulfill(response=response, headers=headers)

        control.route("**/book/**", strip_csp)
        control.goto(f"{base_url}/book/{quote(slug)}/{chapter_path}")
        assert control.locator("html").get_attribute("data-book-script-ran") == "1"
        assert control.locator("html").get_attribute("data-book-handler-ran") == "1"
    finally:
        context.close()


def test_scrolling_stores_the_block_at_the_top_of_the_screen(browser, base_url, isolated):
    """P2-10's other half, the write: a reading position is stored with the block
    it is in, not only with a percent.

    The percent is a proportion of a document that reflows — a font-size change
    or a window resize moves it — while a block is an identity. Scroll to a named
    paragraph and the stored anchor names *that* paragraph, not the chapter's
    first one.
    """
    slug = upload_book(base_url, write_long_epub(isolated / "long.epub"))
    blocks = chapter_payload(base_url, slug)["blocks"]
    target = block_named(blocks, "Paragraph 20 ")
    assert blocks.index(target) > 5, "the fixture must have blocks before it"

    page = browser.new_page()
    try:
        page.goto(f"{base_url}/read/{quote(slug)}/0")
        frame = page.frame_locator("#chapter-frame")
        frame.locator("#p20").wait_for()
        # Scroll the paragraph's first line just past the top edge, so the block
        # *containing* the reading line is unambiguously this one, then let the
        # debounced save (500 ms) land.
        frame.locator("#p20").evaluate(
            "node => window.scrollTo(0, window.pageYOffset"
            " + node.getBoundingClientRect().top + 20)")
        # The write is a server side effect after a 500 ms debounce, so it is
        # waited for rather than slept on.
        stored = None
        deadline = time.time() + 10
        while time.time() < deadline:
            stored = stored_progress(isolated, slug)
            if stored and stored["block_id"]:
                break
            time.sleep(0.1)

        assert stored and stored["block_id"], "scrolling wrote no position"
        assert stored["scroll_percent"] > 0, stored
        assert stored["block_id"] == target["id"], (
            f"the anchor is {stored['block_id']}, not the paragraph at the top")
    finally:
        page.close()


def test_a_stored_block_anchor_is_where_the_reader_returns(browser, base_url, isolated):
    """P2-10's other half, the read: the anchored paragraph is put at the top.

    The row carries a block and *no* percent, so the percent cannot be what put
    the reader there — and a row whose block this document does not have still
    resumes by percent, which is what keeps rows written before the anchor
    existed working.
    """
    slug = upload_book(base_url, write_long_epub(isolated / "long.epub"))
    blocks = chapter_payload(base_url, slug)["blocks"]
    target = block_named(blocks, "Paragraph 25 ")
    save_progress(base_url, slug, block_id=target["id"], seq=1)

    page = browser.new_page()
    try:
        page.goto(f"{base_url}/read/{quote(slug)}/0")
        frame = page.frame_locator("#chapter-frame")
        frame.locator("#p25").wait_for()
        # The blocks arrive with the panel's own fetch, so the anchor takes over
        # a moment after the frame lands: until then the percent (0 here) has the
        # reader at the top.
        page.wait_for_function(
            "() => { const node = document.querySelector('#chapter-frame')"
            ".contentDocument.getElementById('p25');"
            "        return node && node.getBoundingClientRect().top <= 1; }")
        top = frame.locator("#p25").evaluate("node => node.getBoundingClientRect().top")
        # The anchored block *contains* the reading line — its top edge at or just
        # above the viewport's. That is what keeps the anchor from drifting: the
        # position is stored with the block containing the line, so a resume that
        # left the block below it would have the next save record the paragraph
        # before (see RESUME_BLOCK_TOP).
        assert -8 <= top <= 1, f"the anchored paragraph is at {top}px, not the line"
        assert frame.locator("#p25").evaluate("() => window.pageYOffset") > 0

        # The rule marks the reader's place, not the chapter's first paragraph —
        # which is where it would stay if the anchor's scroll did not move it.
        rule = frame.locator(".reader-resume-line").first
        rule.wait_for()
        gap = rule.evaluate(
            "node => parseFloat(node.style.top)"
            " - document.getElementById('p25').offsetTop")
        assert gap > -10, f"the rule is {gap}px above the anchored paragraph"

        # The invariant that keeps the anchor from drifting: the position this
        # resume left behind is the same block. A resume that put the block's top
        # *below* the reading line would have the next save re-derive the
        # paragraph before it, walking the anchor backwards on every open.
        page.wait_for_timeout(1200)
        assert stored_progress(isolated, slug)["block_id"] == target["id"]

        # A row whose block is not in this document: the percent decides.
        #
        # The first page has to be *closed* before seeding it: a reader that is
        # still open keeps saving its own position, and its `seq` is a timestamp
        # — so it outranks any row a test writes, and the fallback check would be
        # reading the other page's save (which is exactly what it did, until the
        # probe showed the percent landing perfectly on its own).
        page.close()
        # `seq` above any the client can send: its writes carry
        # `Math.max(counter + 1, Date.now())`, and a smaller `seq` is refused as
        # stale — which is what the guard is for (REVIEW P2-8).
        save_progress(base_url, slug, scroll_percent=50, block_id="c9999/b9999",
                      seq=10 ** 15)
        context = browser.new_context()
        try:
            fresh = context.new_page()
            fresh.goto(f"{base_url}/read/{quote(slug)}/0")
            landed = fresh.wait_for_function(
                "() => { const win = document.querySelector('#chapter-frame')"
                ".contentWindow;"
                "        const max = win.document.documentElement.scrollHeight"
                " - win.innerHeight;"
                "        if (!(max > 0)) return false;"
                "        return Math.abs(win.pageYOffset - max * 0.5) < max * 0.02; }"
            )
            assert landed, "the percent fallback did not land where the percent asked"
        finally:
            context.close()
    finally:
        page.close()


def test_deleting_the_last_book_of_a_letter_takes_its_pill(browser, base_url, isolated):
    """P3-12: the letter index kept a pill for a group whose last book was gone,
    and clicking it filtered the shelf to nothing.

    The two Vue pages are the one surface a stub DOM cannot honestly stand in
    for — they render through Vue itself — so they are covered here, where a
    real browser is already available.
    """
    upload_book(base_url, write_epub(isolated / "alpha.epub", title="Alpha Book"))
    slug = upload_book(base_url, write_epub(isolated / "beta.epub", title="Beta Book"))

    page = browser.new_page()
    page.on("dialog", lambda dialog: dialog.accept())     # the delete confirms
    try:
        page.goto(f"{base_url}/")
        assert page.locator(".library-index-link").count() == 3   # 全部 + A + B

        card = page.locator(f'.book-card[data-slug="{slug}"]')
        group = card.get_attribute("data-group")
        pill = page.locator(f'.library-index-link[data-group="{group}"]')
        assert pill.is_visible()

        # Filter to that letter, so the fallback below is observable.
        pill.click()
        assert page.locator(".book-card:not(.hidden)").count() == 1

        # Delete the book through its own card menu.
        card.locator(".menu-btn").click()
        card.locator(".dropdown-item.danger").click()
        page.wait_for_selector(
            f'.library-index-link[data-group="{group}"][hidden]', state="attached")

        assert not pill.is_visible(), "the empty letter is still in the index"
        # ...and the filter fell back to 全部, so the shelf is not blank with the
        # only way back hidden.
        assert page.locator(".book-card:not(.hidden)").count() == 1
        assert page.locator(".library-index-link.active").get_attribute(
            "data-group") == "all"
    finally:
        page.close()


def test_a_completed_book_is_marked_on_the_shelf(browser, base_url, isolated):
    """A completed book has to *look* completed — the card and the cover both.

    The server renders the class and the badge, which tests/test_library.py
    asserts; what that cannot assert is that a stylesheet rule stands behind
    either of them, which is the failure P3-3 was: a class that landed with
    nothing to paint it. So the two cards are compared side by side, in the
    computed styles a reader's eye actually gets — a tinted card, a dimmed
    cover, a check drawn *on* the cover rather than beside it.
    """
    open_slug = upload_book(base_url,
                            write_epub(isolated / "open.epub", title="Open Book"))
    done_slug = upload_book(base_url,
                            write_epub(isolated / "done.epub", title="Done Book"))
    with httpx.Client(base_url=base_url, timeout=30) as client:
        response = client.post(f"/api/books/{done_slug}/completion?completed=true")
    assert response.status_code == 200, response.text

    page = browser.new_page()
    try:
        page.goto(f"{base_url}/")
        done = page.locator(f'.book-card[data-slug="{done_slug}"]')
        plain = page.locator(f'.book-card[data-slug="{open_slug}"]')

        def painted(locator, prop):
            """A computed style — what the browser paints with, not what we set."""
            return locator.evaluate(f"node => getComputedStyle(node).{prop}")

        assert "completed" in (done.get_attribute("class") or "")
        assert "completed" not in (plain.get_attribute("class") or "")

        # The card: the "done" tint rather than the plain card colour.
        assert painted(done, "backgroundColor") != painted(plain, "backgroundColor"), (
            "a completed card is painted exactly like an open one")

        # The cover: dimmed and desaturated against the open book's.
        dimmed = done.locator(".book-cover")
        opened = plain.locator(".book-cover")
        assert float(painted(dimmed, "opacity")) < float(painted(opened, "opacity")), (
            "a completed cover is not dimmed")
        assert painted(dimmed, "filter") != painted(opened, "filter"), (
            "a completed cover is not desaturated")

        # The check, drawn over the cover's own corner rather than beside it.
        badge = done.locator(".completion-badge")
        assert badge.is_visible(), "the completed card carries no visible check"
        assert badge.inner_text() == "✓"
        assert plain.locator(".completion-badge").count() == 0

        badge_box, cover_box = badge.bounding_box(), dimmed.bounding_box()
        assert cover_box["x"] <= badge_box["x"] and (
            badge_box["x"] + badge_box["width"]
            <= cover_box["x"] + cover_box["width"])
        assert cover_box["y"] <= badge_box["y"], "the check is not on the cover"

        # The mark must not swallow the cover: a click on the check itself is a
        # click on the book, which is the only thing that corner can be for.
        page.mouse.click(badge_box["x"] + badge_box["width"] / 2,
                         badge_box["y"] + badge_box["height"] / 2)
        page.wait_for_url(lambda url: "/read/" in url)
        assert "/read/" in page.url
    finally:
        page.close()


def test_deleting_an_item_recounts_the_stats_bar(browser, base_url, isolated):
    """P3-12: the counts are rendered once by the server, so a deletion used to
    leave them claiming items that were gone — and an empty page still showing
    four numbers."""
    slug = upload_book(base_url, write_epub(isolated / "stats.epub"))
    save_analysis(base_url, slug, "fact_check")
    save_analysis(base_url, slug, "comment")

    page = browser.new_page()
    page.on("dialog", lambda dialog: dialog.accept())     # the delete confirms
    try:
        page.goto(f"{base_url}/highlights/{quote(slug)}")
        count = lambda kind: page.locator(
            f'.stat-count[data-kind="{kind}"]').inner_text()
        assert (count("fact_check"), count("comment"), count("total")) == ("1", "1", "2")

        # Delete the 解释说明 card, by its kind rather than by position: the list
        # is newest-first, so "the first card" is not a stable target.
        page.locator('.highlight-item[data-kind="fact_check"]'
                     ' .action-link.danger').click()
        page.wait_for_function(
            "() => document.querySelector('.stat-count[data-kind=\"total\"]')"
            ".textContent.trim() === '1'")
        assert count("fact_check") == "0"
        assert count("comment") == "1"
        assert count("total") == "1"

        # The last one: the bar goes rather than showing four zeroes, and the
        # empty page says so.
        page.locator('.highlight-item[data-kind="comment"]'
                     ' .action-link.danger').click()
        page.wait_for_function(
            "() => document.querySelector('.stats-bar').hidden === true")
        assert page.locator("#no-results").is_visible()
    finally:
        page.close()


def test_a_repeated_sentence_marks_the_one_that_was_selected(browser, base_url, isolated):
    """P2-10, end to end: a paragraph that repeats a sentence.

    `block.text.indexOf(selection)` answers "the first occurrence" whatever the
    reader selected, so the context captured with a mark described the *other*
    sentence — and painting then wrapped that other one. Both halves have to be
    right for the mark to land where the reader put it, and only one of them is
    reachable without a browser:

    * the **capture** reads the context from the document around the real Range
      (the stub tests hand the selection in, so they cannot see it at all);
    * the **paint** picks the occurrence whose surroundings match that context.

    Driven through the reader's own UI — select the second sentence, Ctrl+K,
    添加笔记, save — then the stored row is read back and the page reloaded,
    which is the review's own Verify line.
    """
    slug = upload_book(base_url, write_repeated_epub(isolated / "repeated.epub"))
    sentence = "The same sentence twice."

    page = browser.new_page()
    try:
        page.goto(f"{base_url}/read/{quote(slug)}/0")
        paragraph = page.frame_locator("#chapter-frame").locator("p").first
        paragraph.wait_for()

        # A click into the book, because that is what focuses the frame's own
        # document — and that is where the panel listens for Ctrl+K. Without it
        # the key lands in the shell and nothing happens: the keyboard trigger
        # belongs to a reader who is already *in* the book.
        paragraph.click()

        # The second occurrence, inside the paragraph's single text node.
        paragraph.evaluate("""(node, sentence) => {
            const text = node.firstChild;
            const at = text.nodeValue.lastIndexOf(sentence);
            const range = document.createRange();
            range.setStart(text, at);
            range.setEnd(text, at + sentence.length);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
        }""", sentence)

        # Then 添加笔记: a note is saved without the AI, which is what makes this
        # reachable without a provider.
        paragraph.press("Control+k")
        page.locator('#context-menu [data-action="comment"]').click()
        page.fill("#comment-input", "第二条句子上的笔记。")
        page.click("#panel-save")
        page.wait_for_function(
            "document.querySelector('#toast').textContent === '已保存到数据库'")

        # The capture: the context belongs to the *second* sentence, so the
        # before-side is the text between the two and the after-side is empty.
        stored = stored_highlights(base_url, slug)[0]
        assert stored["selected_text"] == sentence
        assert stored["context_before"].endswith("In between stands a marker.")
        assert stored["context_after"] == ""

        # The paint: after a reload the mark is on the second one. Its previous
        # sibling is the text the wrap split off, which only exists for the
        # second occurrence — the first would leave the mark at the paragraph's
        # start, with nothing before it.
        page.reload()
        mark = page.frame_locator("#chapter-frame").locator(
            "mark.reader-highlight").first
        mark.wait_for()
        assert mark.inner_text() == sentence
        before = mark.evaluate(
            "node => (node.previousSibling && node.previousSibling.nodeValue) || ''")
        assert before.strip().endswith("In between stands a marker."), (
            f"the mark landed on the wrong occurrence: {before!r}")
    finally:
        page.close()


def test_a_mark_that_begins_after_an_inline_element_is_painted(
        browser, base_url, isolated):
    """The wrap's range start must not sit inside the inline element it follows.

    `offsetToPoint` resolves a text-node boundary to the node it closes — right
    for a range's *end*, wrong for its *start*: the range then partially selects
    the inline element and `Range.surroundContents` throws `InvalidStateError`,
    so the mark was stored and never painted. 项狄传 vol 5 ch 34 is the book that
    showed it — "Ars longa，——和Vita brevis" begins right after
    `<small>希波克拉底</small>`, and the reader was told 「本章有 1 条高亮未能
    定位」 about a highlight that was in the database all along.

    The fixture is that same shape in English, and the mark is *seeded* rather
    than driven through the UI: the capture was never what broke, and seeding
    keeps the test clear of the AI and the clipboard.
    """
    slug = upload_book(base_url, write_inline_epub(isolated / "inline.epub"))
    payload = chapter_payload(base_url, slug)
    block = next(item for item in payload["blocks"] if "Ars longa" in item["text"])
    # The shape under test: the snippet begins exactly where the inline element
    # ends, which is the boundary the range must not start inside.
    assert "HippocratesArs longa" in block["text"]
    snippet = "Ars longa and then carried on"
    highlight_id = seed_highlight(base_url, slug, snippet, block["id"])

    page = browser.new_page()
    try:
        page.goto(f"{base_url}/read/{quote(slug)}/0")
        assert_mark(page, snippet, highlight_id)
        # And the shell had nothing to report: the mark was located.
        assert "未能定位" not in page.locator("#toast").inner_text()
    finally:
        page.close()


def test_a_selection_highlighted_twice_is_one_mark_and_is_not_lost(
        browser, base_url, upload):
    """Two stored highlights on one selection: one mark on the page, neither lost.

    Reported by the reader, on 自由的窄廊 — a heading whose two phrases run
    together (`受制約的巨靈與持續的競爭紅皇后效應`), so the same five characters
    were selected twice. The row is in the database, the API answered 200, the app
    says 已保存到数据库, and the reading pane shows one mark where two were saved —
    while the third save paints nothing at all:

    * the second wrap *nested* the new mark inside the first, so both painted the
      same pixels: one visible mark, the innermost clickable;
    * the third threw `InvalidStateError` — `surroundContents` leaves an empty
      text node inside the mark it builds, the new range began there and ended
      inside the nested mark, which was therefore *partially contained* in the
      range, and the wrap refused it. Stored, never painted, and reported as
      「本章有 N 条高亮未能定位」.

    One mark now stands for every highlight on that text: it carries the newest
    id (what a click opens), every id it stands for, and nothing is reported as
    unlocated. Seeded rather than driven through the UI — saving twice is what a
    reader does, but the AI and the clipboard are not what broke.
    """
    slug = upload()
    payload = chapter_payload(base_url, slug)
    block = block_named(payload["blocks"], "The first paragraph mentions")
    snippet = "and then keeps going for a while"
    ids = [seed_highlight(base_url, slug, snippet, block["id"]) for _ in range(3)]

    page = browser.new_page()
    try:
        page.goto(f"{base_url}/read/{quote(slug)}/0")
        marks = page.frame_locator("#chapter-frame").locator("mark.reader-highlight")
        marks.first.wait_for()
        assert marks.count() == 1, "one selection is one mark on the page"
        mark = marks.first
        assert collapsed(mark.inner_text()) == collapsed(snippet)
        assert mark.get_attribute("data-highlight-id") == str(ids[-1]), (
            "the mark is opened by the newest highlight on that text")
        assert mark.get_attribute("data-highlight-ids").split() == [
            str(item) for item in ids], "every id the mark stands for is on it"
        assert "未能定位" not in page.locator("#toast").inner_text()

        # 在书中定位 reaches the mark by *any* id it stands for, so the oldest of
        # the three rows still finds it — and flashes it.
        page.goto(f"{base_url}/read/{quote(slug)}/0?highlight={ids[0]}")
        page.wait_for_function(
            "() => document.getElementById('chapter-frame').contentDocument"
            ".querySelector('mark.reader-highlight.flash') !== null")
    finally:
        page.close()


def test_a_highlight_that_straddles_an_inline_element_is_painted(
        browser, base_url, isolated):
    """A selection that begins inside an inline element and ends outside it.

    `Range.surroundContents` refuses a range that *partially contains* a node —
    an element holding one end of the range but not the other — so this shape was
    stored and never painted, and the reader was told 「本章有 N 条高亮未能定位」
    about a highlight that was in the database all along. The forward bias in
    `offsetToPoint` rescues a boundary that lands exactly at a text node's end
    (the 项狄传 case, the test above); a selection that ends mid-element has no
    such boundary. The wrap now falls back to the run's pieces — one mark per
    text node it covers, all carrying the highlight's id.
    """
    slug = upload_book(base_url, write_inline_epub(isolated / "inline.epub"))
    payload = chapter_payload(base_url, slug)
    block = next(item for item in payload["blocks"] if "Ars longa" in item["text"])
    # Begins inside `<small>Hippocrates</small>` and ends in the paragraph.
    snippet = "ippocratesArs longa"
    highlight_id = seed_highlight(base_url, slug, snippet, block["id"])

    page = browser.new_page()
    try:
        page.goto(f"{base_url}/read/{quote(slug)}/0")
        marks = page.frame_locator("#chapter-frame").locator("mark.reader-highlight")
        marks.first.wait_for()
        assert marks.count() == 2, "one mark per text node the selection covers"
        assert [mark.get_attribute("data-highlight-id") for mark in marks.all()] == \
            [str(highlight_id)] * 2
        assert collapsed("".join(marks.all_inner_texts())) == collapsed(snippet)
        assert "未能定位" not in page.locator("#toast").inner_text()
    finally:
        page.close()


def test_the_copy_action_copies_where_the_clipboard_api_is_absent(
        browser, base_url, isolated):
    """复制文本 on the deployment that actually exists: plain http on a LAN.

    `navigator.clipboard` is a *secure context* feature — https, or localhost.
    At home this reader is served at `http://192.168.…:8123`, where the property
    is simply absent, and the copy action called it unguarded: selecting text and
    choosing 复制文本 raised `TypeError: navigator.clipboard is undefined`, copied
    nothing and said nothing — no toast, no error on screen. Every test until now
    ran on 127.0.0.1, where the API does exist, so nothing caught it.

    Removing the property is all an insecure context does, so the page models the
    LAN deployment, and the copy is observed where it lands: the text the
    fallback hands to the document's own copy command. The page-error check is
    the other half — the failure *was* an exception, and a silent one.
    """
    slug = upload_book(base_url, write_long_epub(isolated / "long.epub"))
    block = block_named(chapter_payload(base_url, slug)["blocks"], "Paragraph 3 ")

    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(f"{base_url}/read/{quote(slug)}/0")
        frame = page.frame_locator("#chapter-frame")
        frame.locator("#p3").wait_for()

        page.evaluate(
            """() => {
                Object.defineProperty(navigator, 'clipboard', { value: undefined });
                window.__copied = [];
                const real = document.execCommand.bind(document);
                document.execCommand = (command) => {
                    if (command === 'copy') {
                        window.__copied.push(document.getSelection().toString());
                    }
                    return real(command);
                };
            }""")

        # A real selection in the book's own document, and the mouseup that opens
        # the menu over it — what a reader does with a mouse.
        frame.locator("#p3").evaluate(
            """node => {
                const range = document.createRange();
                range.selectNodeContents(node);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
                node.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
            }""")
        page.locator('#context-menu .context-menu-item[data-action="copy"]').click()

        copied = page.evaluate("() => window.__copied")
        assert copied and collapsed(copied[0]) == collapsed(block["text"]), (
            f"the selected text never reached the clipboard: {copied!r}")
        assert page.locator("#toast").inner_text() == "已复制到剪贴板"
        assert errors == [], f"the page raised: {errors}"
    finally:
        page.close()


def test_the_provider_is_chosen_from_the_bar(browser, base_url, upload):
    """The provider used to be changeable only inside the AI panel — which is
    not on screen until a selection opens it, so "which model answers" was
    invisible until the reader had already asked something.

    The bar carries it now. The panel stays closed throughout: the toggle is the
    setting, it is what the server is set to, and the next page load renders it
    checked — that last one is the server's own render, not a script's guess.
    """
    slug = upload()

    page = browser.new_page()
    try:
        page.goto(f"{base_url}/read/{quote(slug)}/0")
        toggle = page.locator("#provider-toggle")
        toggle.wait_for()
        assert page.locator("#ai-panel").is_hidden(), "the panel starts closed"

        local = toggle.locator('.provider-option[data-provider="ollama"]')
        cloud = toggle.locator('.provider-option[data-provider="ollama_cloud"]')
        # The shell rendered the provider the server is set to: the cloud
        # default, with the local option there to be chosen.
        assert cloud.get_attribute("aria-checked") == "true"
        assert local.get_attribute("aria-checked") == "false"

        local.click()

        assert local.get_attribute("aria-checked") == "true"
        assert cloud.get_attribute("aria-checked") == "false"
        assert stored_settings(base_url)["provider_override"] == "ollama"
        assert page.locator("#ai-panel").is_hidden(), "no panel was needed"

        # It is the server's choice now: a reload renders it checked, from the
        # markup (routers/reader.py), before any script runs.
        page.reload()
        toggle.wait_for()
        assert toggle.locator(
            '.provider-option[data-provider="ollama"]').get_attribute(
                "aria-checked") == "true"

        # A radiogroup is one tab stop, and the arrows move the choice.
        local = toggle.locator('.provider-option[data-provider="ollama"]')
        local.focus()
        page.keyboard.press("ArrowRight")
        page.wait_for_function(
            "() => document.querySelector('#provider-toggle "
            ".provider-option[data-provider=\"ollama_cloud\"]')"
            ".getAttribute('aria-checked') === 'true'")
        assert stored_settings(base_url)["provider_override"] == "ollama_cloud"
    finally:
        page.close()

# -- math: the shell draws a book's LaTeX -----------------------------------

def test_the_shell_draws_a_books_latex(browser, base_url, isolated):
    """A book of LaTeX: the shell converts it to MathML, and nothing else breaks.

    Four things only a browser can show. That a formula arrives as *MathML* —
    the same thing the browser already draws for a book that ships it, so the
    formula stays text: selectable, searchable, and the same characters a reader
    could copy. That the document still says what the library extracted —
    `ReaderCore.mathText` reads each converted span back as its source, without
    which `blockElement` stops finding the paragraph at all (measured before it
    existed: matched, then null). That the two shapes which must not be
    converted — a price, a macro the converter does not know — are left alone,
    the second of them marked rather than swallowed. And that the book's own
    script still never runs.
    """
    slug = upload_book(base_url, write_latex_epub(isolated / "latex.epub"))
    blocks = chapter_payload(base_url, slug)["blocks"]
    paragraph = next(block for block in blocks if "Inline math is" in block["text"])
    assert "$x = \\frac" in paragraph["text"], "the stored text is the book's source"

    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(f"{base_url}/read/{quote(slug)}/0", wait_until="load")
        page.wait_for_selector("#chapter-frame")
        frame = page.frame_locator("#chapter-frame")
        frame.locator("[data-reader-math]").first.wait_for(timeout=30000)
        drawn = page.evaluate("""(stored) => {
            const doc = document.querySelector('#chapter-frame').contentDocument;
            const Core = window.ReaderCore;
            const spans = [...doc.querySelectorAll('[data-reader-math]')];
            const paragraph = (needle) => [...doc.querySelectorAll('p')]
                .find((p) => p.textContent.includes(needle));
            const prices = paragraph('paperback');
            const macro = paragraph('nobody knows');
            const prose = paragraph('Inline math is');
            // What a reader can select over the formula. MathML is text, so
            // this is a real selection rather than a picture of one.
            const mathEl = prose.querySelector('math');
            const range = doc.createRange();
            range.selectNodeContents(mathEl);
            const selection = doc.defaultView.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            const selected = selection.toString();
            selection.removeAllRanges();
            const failed = macro.querySelector('[data-reader-math][data-math-error]');
            return {
                spans: spans.length,
                mathElements: doc.querySelectorAll('[data-reader-math] math').length,
                mfracs: doc.querySelectorAll('[data-reader-math] mfrac').length,
                displayMath: doc.querySelectorAll(
                    '[data-reader-math][data-display] math').length,
                formulaText: mathEl ? mathEl.textContent.replace(/\\s+/g, '') : null,
                selectionOverFormula: selected.replace(/\\s+/g, ' ').trim(),
                dollarsInText: (doc.body.innerText.match(/\\$/g) || []).length,
                sources: spans.map((s) => s.getAttribute('data-source')),
                rawTextHasSource: doc.body.textContent.includes('$x = \\\\frac'),
                blockMatched: Boolean(Core.blockElement(doc, {text: stored})),
                priceSpans: prices.querySelectorAll('[data-reader-math]').length,
                pricesIntact: prices.textContent.includes('$5 for the paperback'),
                macroSpans: macro.querySelectorAll('[data-reader-math]').length,
                macroError: failed
                    ? {source: failed.textContent,
                       reason: failed.getAttribute('data-math-error')}
                    : null,
                bookScriptRan: doc.documentElement.hasAttribute('data-book-script-ran'),
            };
        }""", paragraph["text"])
    finally:
        page.close()

    assert errors == []
    assert drawn["spans"] == 4, "two inline, one display, one beside the unknown macro"
    assert drawn["mathElements"] == 3, \
        "three converted; the one the converter cannot read keeps the book's source"
    assert drawn["mfracs"] >= 1
    assert drawn["displayMath"] == 1
    # Five dollar signs, not two: the three prices are prose, and the formula
    # the converter could not read keeps the dollars the book wrote.
    assert drawn["dollarsInText"] == 5
    assert drawn["sources"][0] == "$x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$"
    assert drawn["sources"][1] == "\\[ \\int_0^1 x^2 \\, dx = \\tfrac{1}{3} \\]"
    # The formula is text, and a reader can select it — the reason MathML is the
    # output rather than a picture of the formula.
    assert "4ac" in drawn["formulaText"]
    assert drawn["selectionOverFormula"], "a formula in the frame is selectable"
    # The projection, both halves of it: the source is gone from the document's
    # own text, and the block lookup still matches anyway.
    assert drawn["rawTextHasSource"] is False
    assert drawn["blockMatched"] is True
    # The hazards, in the same chapter: the prices are untouched, and the macro
    # nobody knows keeps the book's own source with the reason beside it.
    assert drawn["priceSpans"] == 0
    assert drawn["pricesIntact"] is True
    assert drawn["macroSpans"] == 2, "the formula beside it still converts"
    assert drawn["macroError"]["source"] == "$\\undefinedmacro{x}$"
    assert "Unsupported function name" in drawn["macroError"]["reason"]
    # The book's own script still never runs.
    assert drawn["bookScriptRan"] is False


def test_copying_a_selection_carries_the_formula_source(browser, base_url, isolated):
    """复制文本 on a formula: the reader gets the LaTeX, not the rendering.

    The point of converting a book's LaTeX to MathML rather than to a picture is
    that a formula stays text a reader can select — but what the browser hands
    back for a selection over MathML is its own extraction, spaced and in
    mathematical alphanumerics (`𝑥 = − 𝑏 ± …`), which is nothing anyone can
    paste into a document. The book's source is what a reader wants, and the
    shell keeps it (`data-source`), so the copy action reads the selection back
    through `ReaderCore.mathText`. Observed where it lands: the text the fallback
    hands to the document's own copy command.
    """
    slug = upload_book(base_url, write_latex_epub(isolated / "latex.epub"))
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(f"{base_url}/read/{quote(slug)}/0")
        frame = page.frame_locator("#chapter-frame")
        frame.locator("[data-reader-math]").first.wait_for(timeout=30000)

        # The LAN deployment's shape — plain http has no Clipboard API — and the
        # copy observed where it lands.
        page.evaluate(
            """() => {
                Object.defineProperty(navigator, 'clipboard', { value: undefined });
                window.__copied = [];
                const real = document.execCommand.bind(document);
                document.execCommand = (command) => {
                    if (command === 'copy') {
                        window.__copied.push(document.getSelection().toString());
                    }
                    return real(command);
                };
            }""")

        # A real selection over a paragraph that holds a formula, and the mouseup
        # that opens the menu over it.
        frame.locator("p").filter(has_text="Inline math is").evaluate(
            """node => {
                const range = document.createRange();
                range.selectNodeContents(node);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
                node.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
            }""")
        page.locator('#context-menu .context-menu-item[data-action="copy"]').click()

        copied = page.evaluate("() => window.__copied")
        assert copied, "nothing reached the clipboard"
        assert "$x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$" in copied[0], (
            f"the formula's source did not reach the clipboard: {copied[0]!r}")
        # And not the browser's own extraction of the MathML it was drawn into.
        assert "\U0001d465" not in copied[0], "the drawn characters were copied"
        assert page.locator("#toast").inner_text() == "已复制到剪贴板"
        assert errors == [], f"the page raised: {errors}"
    finally:
        page.close()


def test_a_chapter_that_loads_before_the_shell_is_still_wired(
        browser, base_url, isolated):
    """The frame sits above the shell's scripts, so a small chapter can finish
    loading before `reader.js` attaches its `load` listener — and then that
    listener never runs at all: no paper sheet, no saved highlights, no drawn
    math. Delaying the shell's own script is how the race is forced rather than
    waited for; without the check at init this page comes up unstyled and its
    formulas stay as source.
    """
    slug = upload_book(base_url, write_latex_epub(isolated / "latex.epub"))
    page = browser.new_page()

    def slow_shell(route):
        time.sleep(0.7)          # the chapter arrives first, deliberately
        route.continue_()

    try:
        page.route("**/static/js/reader.js*", slow_shell)
        page.goto(f"{base_url}/read/{quote(slug)}/0", wait_until="load")
        page.wait_for_selector("#chapter-frame")
        frame = page.frame_locator("#chapter-frame")
        frame.locator("[data-reader-math]").first.wait_for(timeout=30000)
        state = page.evaluate("""() => {
            const doc = document.querySelector('#chapter-frame').contentDocument;
            return {
                styled: Boolean(doc.getElementById('reader-style')),
                spans: doc.querySelectorAll('[data-reader-math]').length,
            };
        }""")
    finally:
        page.close()

    assert state == {"styled": True, "spans": 4}


def test_a_chapter_without_formulas_fetches_no_renderer(browser, base_url, isolated):
    """The converter is fetched for a chapter that has formulas, and not otherwise.

    A hundred and seventy kilobytes is not a cost a library of prose should pay
    on every page turn: the pass walks the chapter's text nodes first and only
    reaches for the bundle — or its stylesheet — when a delimiter is there.
    """
    slug = upload_book(base_url, write_epub(isolated / "prose.epub"))
    page = browser.new_page()
    fetched = []
    page.on("request", lambda request: fetched.append(request.url))
    try:
        page.goto(f"{base_url}/read/{quote(slug)}/0", wait_until="load")
        page.wait_for_selector("#chapter-frame")
        frame = page.frame_locator("#chapter-frame")
        frame.locator("h1").first.wait_for(timeout=20000)
        page.wait_for_timeout(500)      # long enough for a fetch to have started
        assert page.evaluate(
            "document.querySelector('#chapter-frame').contentDocument"
            ".querySelectorAll('[data-reader-math]').length") == 0
    finally:
        page.close()
    assert [url for url in fetched if "temml" in url] == []


