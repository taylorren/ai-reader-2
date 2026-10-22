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

from . import BASE_DIR, get_asset_version

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
def book_file(slug: str, path: str):
    """One of the book's own files, at its own path. Nothing is rewritten."""
    from . import BOOKS_DIR, book_cache, get_db

    row = get_db().get_book(slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    book = book_cache.get_or_open(slug, BOOKS_DIR / row["path"])
    found = book.resource(path)
    if found is None:
        raise HTTPException(status_code=404, detail="No such file in the book")
    return Response(content=found.read(), media_type=content_type(found.media_type))


# -- the reader shell -----------------------------------------------------

@router.get("/read/{slug}")
def read_redirect(slug: str):
    """The library links here; resume the last-read chapter (P4 stores it)."""
    from . import BOOKS_DIR, book_cache, get_db

    row = get_db().get_book(slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    index = 0
    progress = get_db().get_progress(slug)
    if progress:
        book = book_cache.get_or_open(slug, BOOKS_DIR / row["path"])
        index = min(progress["chapter_index"], book.chapter_count - 1)
    # The slug is quoted: `#` in a Location header is read by the browser as the
    # start of a fragment, so `/read/C# in Depth/0` sent it to `/read/C`.
    return RedirectResponse(f"/read/{quote(slug, safe='')}/{index}", status_code=307)


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
    from . import BOOKS_DIR, book_cache, get_db

    row = get_db().get_book(slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    book = book_cache.get_or_open(slug, BOOKS_DIR / row["path"])
    if not 0 <= chapter_index < book.chapter_count:
        raise HTTPException(status_code=404, detail="No such chapter")

    progress = get_db().get_progress(slug)
    saved_percent = 0.0
    if progress and progress["chapter_index"] == chapter_index:
        saved_percent = progress["scroll_percent"] or 0.0

    return templates.TemplateResponse(
        request=request,
        name="reader.html",
        context={
            "slug": slug,
            "title": row["title"] or slug,
            "index": chapter_index,
            "chapter_count": book.chapter_count,
            "unsupported": row["unsupported"],
            "asset_version": get_asset_version(
                "static/js/reader.js", "static/js/panel.js", "static/css/reader.css"),
            "initial_src": (
                f"/book/{quote(slug, safe='')}/"
                f"{quote(book.spine[chapter_index], safe='/')}"
            ),
            "book_data": {
                "slug": slug,
                "index": chapter_index,
                "spine": list(book.spine),
                "toc": book.toc_json(),
                "saved_percent": saved_percent,
                # ?highlight=<id> — a "在书中定位" link; the shell scrolls to it.
                "target_highlight": request.query_params.get("highlight", ""),
            },
        },
    )


@router.get("/api/book/{slug}")
def book_api(slug: str):
    """Spine, TOC and metadata as JSON."""
    from . import BOOKS_DIR, book_cache, get_db

    row = get_db().get_book(slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    book = book_cache.get_or_open(slug, BOOKS_DIR / row["path"])
    return {
        "slug": slug,
        "title": row["title"] or slug,
        "author": row["author"] or "",
        "unsupported": row["unsupported"],
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
    from . import BOOKS_DIR, book_cache, get_db

    row = get_db().get_book(slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    book = book_cache.get_or_open(slug, BOOKS_DIR / row["path"])
    if not 0 <= chapter_index < book.chapter_count:
        raise HTTPException(status_code=404, detail="No such chapter")
    return {
        "slug": slug,
        "chapter_index": chapter_index,
        "edges": book.footnotes(chapter_index),
    }


@router.get("/api/text/{slug}/{chapter_index}")
def chapter_text_api(slug: str, chapter_index: int):
    """A chapter's plain text and its anchorable blocks.

    The text is the AI's context and the word count's source; the blocks are
    what a highlight anchors to. Only prose kinds come back — a list or table
    is not a single selectable run in the served document, so a highlight in
    one is located by its selected text alone.
    """
    from . import BOOKS_DIR, book_cache, get_db

    row = get_db().get_book(slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    book = book_cache.get_or_open(slug, BOOKS_DIR / row["path"])
    if not 0 <= chapter_index < book.chapter_count:
        raise HTTPException(status_code=404, detail="No such chapter")
    text = book.chapter_text(chapter_index)
    blocks = anchor_blocks(book.blocks(chapter_index))
    return {
        "slug": slug,
        "chapter_index": chapter_index,
        "chapter_path": book.spine[chapter_index],
        "text": text,
        "word_count": len(text),
        "blocks": blocks,
    }


