"""Reader routes: the reader shell, the book's own files, chapter APIs.

Landed:

    GET /read/{slug}              resume: last-read chapter, else the first
    GET /read/{slug}/{index}      the reader shell — the book's own document
                                  in a sandboxed iframe (model A, the MVP's
                                  method); nothing from the book executes
    GET /book/{slug}/{path}       book.resource(path) — the book's own bytes
                                  and media type; covers come through here
    GET /api/book/{slug}          spine + toc + metadata as JSON
    GET /api/footnotes/{slug}/{i} resolved footnote edges (note text and
                                  target path included, for popups)
    GET /api/text/{slug}/{i}      plain_text and the chapter's block ids —
                                  AI context, and the anchors highlights use
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

# `BOOKS_DIR` is read through the module at every use rather than imported by
# value: the suite points the app at a private library by patching
# `app_state.BOOKS_DIR`, and a value bound at import time would not see it.
# The old function-local `from . import BOOKS_DIR` did exactly that by
# accident — it re-read the attribute per call — and it is also why the
# dependency direction was invisible (REVIEW P3-14).
from . import app_state
from .app_state import BASE_DIR, book_cache, effective_provider, get_db
from .assets import get_asset_version

router = APIRouter()

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# The block kinds worth anchoring a highlight to: prose the reader sees as
# text. Lists, tables and figures are skipped — their inner text is not a
# single selectable run in the served document.
ANCHOR_KINDS = ("paragraph", "heading", "quote", "preformatted", "definition")


def anchor_blocks(blocks) -> list[dict]:
    """The blocks a highlight can anchor to: prose that carries selectable text.

    `text` is `str | None` in epubx's model, and a block whose text collapses
    away is `None` — the same value an uncaptioned figure carries. `<p>　</p>`,
    the blank line a CJK/InDesign export sets with U+3000, is the common case
    (1,168 of them in one corpus book, in 40 of its 42 chapters). Such a block
    carries nothing a reader can select, so it is not an anchor: skip it rather
    than calling `.strip()` on it. Calling `.strip()` raised, and the 500
    silently disabled the reader's selection menu for the whole book (128 of
    301 corpus books carry the shape).
    """
    return [block for block in blocks
            if block["kind"] in ANCHOR_KINDS and (block["text"] or "").strip()]


def content_type(media_type: str) -> str:
    """The Content-Type for a book file — the MVP's rule.

    XHTML goes out as text/html: the consumer is a browser, and strict XML
    parsing would reject many readable books. Text-shaped types carry a
    charset so the browser does not have to guess.
    """
    if media_type == "application/xhtml+xml":
        media_type = "text/html"
    if media_type.startswith("text/") or media_type in (
        "application/xml", "application/json", "application/oebps-package+xml",
        "application/x-dtbncx+xml", "image/svg+xml",
    ):
        media_type = f"{media_type}; charset=utf-8"
    return media_type


@router.get("/book/{slug}/{path:path}")
def book_file(request: Request, slug: str, path: str):
    """One of the book's own files, at its own path. Nothing is rewritten.

    Two header jobs live here.

    **Safety.** Inside the reader the book is harmless — the frame is sandboxed
    without `allow-scripts`, so nothing it ships executes. The same URL opened
    *directly* (a bookmark, a copied link, "open in new tab", a link rendered in
    the highlights view) is an ordinary top-level document at this origin, where
    a script the EPUB carries would run with access to `/api/*` — able to delete
    books and rewrite annotations. `script-src 'none'` closes that path without
    touching the reader: styles, images and fonts still load, and the sandbox
    already stopped the scripts (REVIEW P2-1).

    **Caching.** A chapter turn re-requests that chapter's own CSS, fonts and
    images, and a re-read of a chapter re-requests everything: without a
    validator the browser re-downloads it all from disk every time (REVIEW
    P2-3). The EPUB file's mtime is the validator — a re-upload replaces the
    file, so its stamp changes, and the upload path drops the open book — and
    `If-None-Match` answers 304 with no body.
    """

    row = get_db().get_book(slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    book_path = app_state.BOOKS_DIR / row["path"]
    etag = _book_etag(book_path, path)
    headers = {
        "Content-Security-Policy": "script-src 'none'; object-src 'none'",
        "X-Content-Type-Options": "nosniff",
        "ETag": etag,
        "Cache-Control": "public, max-age=3600",
    }
    # The revalidation path never opens the book: it needs the validator, which
    # comes from the file, and a chapter turn that evicts the cache must not
    # close a book another response is reading from (REVIEW P2-5).
    if _etag_matches(request.headers.get("if-none-match", ""), etag):
        return Response(status_code=304, headers=headers)

    with book_cache.borrow(slug, book_path) as book:
        found = book.resource(path)
        if found is None:
            raise HTTPException(status_code=404, detail="No such file in the book")
        content = found.read()
    return Response(content=content, media_type=content_type(found.media_type),
                    headers=headers)


def _book_etag(epub_path, resource_path: str) -> str:
    """A validator for one file inside a book.

    The archive's mtime, not the member's: a member has no mtime of its own that
    survives a re-upload, and any change to the book replaces the archive.
    """
    try:
        stamp = epub_path.stat().st_mtime_ns
    except OSError:
        stamp = 0
    return f'"{stamp}-{resource_path}"'


def _etag_matches(header: str, etag: str) -> bool:
    """`If-None-Match` — `*`, one tag, or a list of them."""
    if not header:
        return False
    if header.strip() == "*":
        return True
    return etag in [candidate.strip() for candidate in header.split(",")]


# -- the reader shell -----------------------------------------------------

@router.get("/read/{slug}")
def read_redirect(slug: str):
    """The library links here; resume the last-read chapter (P4 stores it)."""

    row = get_db().get_book(slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    index = 0
    progress = get_db().get_progress(slug)
    if progress:
        with book_cache.borrow(slug, app_state.BOOKS_DIR / row["path"]) as book:
            chapter_count = book.chapter_count
        # Clamped at both ends: a book with an empty spine (`chapter_count == 0`,
        # a malformed file that still opened) used to compute -1 and redirect to
        # `/read/{slug}/-1`, which nothing accepts — the one place where a named
        # failure became a bare 404 (REVIEW P3-6).
        index = min(max(progress["chapter_index"], 0), max(chapter_count - 1, 0))
    # The slug is quoted: `#` in a Location header is read by the browser as the
    # start of a fragment, so `/read/C# in Depth/0` sent it to `/read/C`.
    return RedirectResponse(f"/read/{quote(slug, safe='')}/{index}", status_code=307)


def shell_context(request: Request, slug: str, row: dict, book, chapter_index: int,
                  unsupported: str | None, saved_percent: float = 0.0,
                  saved_block_id: str | None = None) -> dict:
    """The reader shell's context — for a chapter, or for a reason page.

    A book with no readable chapter renders the same template with
    `unsupported` set and no frame, so one construction serves both and the two
    cannot drift apart.
    """
    spine = list(book.spine)
    initial_src = ""
    if 0 <= chapter_index < len(spine):
        initial_src = (f"/book/{quote(slug, safe='')}/"
                       f"{quote(spine[chapter_index], safe='/')}")
    return {
        "slug": slug,
        "title": row["title"] or slug,
        "index": chapter_index,
        "chapter_count": book.chapter_count,
        "unsupported": unsupported,
        "asset_version": get_asset_version(
            "static/js/reader.js", "static/js/panel.js",
            "static/js/reader-core.js", "static/css/reader.css"),
        "initial_src": initial_src,
        # Which AI answers, for the bar's toggle — the only control that shows
        # it (the panel's select is gone). Server-rendered so the choice is right
        # on the first paint and stays right with no JavaScript — the same value
        # /api/settings serves, from the same definition (app_state.effective_provider).
        "provider": effective_provider(),
        "book_data": {
            "slug": slug,
            "index": chapter_index,
            "spine": spine,
            "toc": book.toc_json(),
            "saved_percent": saved_percent,
            # The block the reader stopped in: the resume's identity, with the
            # percent as the fallback for a row that predates it (REVIEW P2-10).
            "saved_block_id": saved_block_id or "",
            # ?highlight=<id> — a "在书中定位" link; the shell scrolls to it.
            "target_highlight": request.query_params.get("highlight", ""),
        },
    }


@router.get("/read/{slug}/{chapter_index}")
def reader_shell(request: Request, slug: str, chapter_index: int):
    """The reader shell: the book's own document in a sandboxed iframe.

    Model A, the MVP's method. The shell renders nothing of the book: the
    iframe loads the chapter at its own path through /book/{slug}/{path},
    with its own CSS, its own links and its own footnotes. The sandbox
    allows same-origin — so the shell can follow the frame's position — and
    nothing else: nothing from a book executes (principle 6). A book whose
    `unsupported` names a deferred case gets that reason instead of a frame.
    """

    row = get_db().get_book(slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    # Borrowed for the whole render: the shell's context reads the book's spine
    # and TOC, and eviction must not close it half-way through (REVIEW P2-5).
    with book_cache.borrow(slug, app_state.BOOKS_DIR / row["path"]) as book:
        # The live value wins over the stored one: a file deleted or replaced
        # behind the app's back still has a row saying it was readable, and
        # `unsupported` is cheap to recompute here — the book is open either way
        # (REVIEW P3-5).
        unsupported = book.unsupported or row["unsupported"]

        if not 0 <= chapter_index < book.chapter_count:
            # No chapter to show. If the book has none at all, its named reason
            # is what the reader needs — the library card cannot reach this page
            # (it hides its 浏览本书 link), and a bare 404 says nothing
            # (P3-5/P3-6).
            if book.chapter_count == 0:
                return templates.TemplateResponse(
                    request=request, name="reader.html",
                    context=shell_context(request, slug, row, book, 0,
                                          unsupported
                                          or "unreadable book: no chapters"))
            raise HTTPException(status_code=404, detail="No such chapter")

        progress = get_db().get_progress(slug)
        saved_percent = 0.0
        saved_block_id = None
        if progress and progress["chapter_index"] == chapter_index:
            saved_percent = progress["scroll_percent"] or 0.0
            saved_block_id = progress["block_id"]

        return templates.TemplateResponse(
            request=request,
            name="reader.html",
            context=shell_context(request, slug, row, book, chapter_index,
                                  unsupported, saved_percent, saved_block_id),
        )


@router.get("/api/book/{slug}")
def book_api(slug: str):
    """Spine, TOC and metadata as JSON."""

    row = get_db().get_book(slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    with book_cache.borrow(slug, app_state.BOOKS_DIR / row["path"]) as book:
        return {
            "slug": slug,
            "title": row["title"] or slug,
            "author": row["author"] or "",
            # The live reason wins: the row can be stale if the file changed
            # behind the app's back (REVIEW P3-5).
            "unsupported": book.unsupported or row["unsupported"],
            "chapter_count": book.chapter_count,
            "spine": list(book.spine),
            "toc": book.toc_json(),
        }


@router.get("/api/footnotes/{slug}/{chapter_index}")
def footnote_api(slug: str, chapter_index: int):
    """The chapter's footnote edges, resolved by the library at parse time.

    A marker's edge carries the note's text and the target's book-internal
    path, so a reader opens a footnote without fetching a rendered page.
    A book whose markers the library cannot classify (Word-style `_ftn`
    links, say) yields no edges — its own links still work natively.
    """

    row = get_db().get_book(slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    with book_cache.borrow(slug, app_state.BOOKS_DIR / row["path"]) as book:
        if not 0 <= chapter_index < book.chapter_count:
            raise HTTPException(status_code=404, detail="No such chapter")
        return {
            "slug": slug,
            "chapter_index": chapter_index,
            "edges": book.footnotes(chapter_index),
        }


@router.get("/api/text/{slug}/{chapter_index}")
def chapter_text_api(slug: str, chapter_index: int, text: bool = False):
    """A chapter's anchorable blocks — and, on request, its plain text.

    The blocks are what a highlight anchors to, and they already carry the text
    of every prose block, so shipping the whole chapter beside them sent the
    same words twice on every chapter turn (REVIEW P2-9). `?text=1` adds the
    prose as one string, for a caller that wants the chapter rather than its
    blocks.

    `char_count` counts characters, which is what it always did: it was named
    `word_count`, a misnomer that invited the wrong use. A word count is
    `estimate_book_word_count`'s job, with the rules it documents.
    """

    row = get_db().get_book(slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    with book_cache.borrow(slug, app_state.BOOKS_DIR / row["path"]) as book:
        if not 0 <= chapter_index < book.chapter_count:
            raise HTTPException(status_code=404, detail="No such chapter")

        prose = book.chapter_text(chapter_index)
        payload = {
            "slug": slug,
            "chapter_index": chapter_index,
            "chapter_path": book.spine[chapter_index],
            "char_count": len(prose),
            "blocks": anchor_blocks(book.blocks(chapter_index)),
        }
    if text:
        payload["text"] = prose
    return payload


