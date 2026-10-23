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
