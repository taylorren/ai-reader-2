"""Reader routes: the reader shell, the book's own files, chapter APIs.

Landed:

    GET /read/{slug}              resume: last-read chapter, else the first
    GET /read/{slug}/{index}      the reader shell — the book's own document
                                  in a sandboxed iframe (model A, the MVP's
                                  method); nothing from the book executes
    GET /book/{slug}/{path}       book.resource(path) — the book's own bytes
                                  and media type; covers come through here
    GET /api/book/{slug}          spine + toc + metadata as JSON

Planned, per SPEC.md:

    GET /api/footnotes/{slug}/{chapter_index}  resolved footnote edges (P3)
    GET /api/text/{slug}/{chapter_index}       plain_text — AI context (P4)
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from . import BASE_DIR, get_asset_version

router = APIRouter()

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


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
    return RedirectResponse(f"/read/{slug}/{index}", status_code=307)


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
                "static/js/reader.js", "static/css/reader.css"),
            "initial_src": (
                f"/book/{quote(slug, safe='')}/"
                f"{quote(book.spine[chapter_index], safe='/')}"
            ),
            "book_data": {
                "slug": slug,
                "index": chapter_index,
                "spine": list(book.spine),
                "toc": book.toc_json(),
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
