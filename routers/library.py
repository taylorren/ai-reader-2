"""Library routes: book listing, upload, delete. (P1)

    GET    /                the library view, from SQLite — no EPUB parsing
    POST   /upload          save, validate, metadata, word count, insert —
                           one step, no subprocess
    DELETE /delete/{slug}   remove the book folder, keep the annotations

Upload stores a book that opened, even when `unsupported` names a deferred
case (DRM, image-only) — the reason shows on the card, not an error. A file
that is not a book at all is refused with the same named reason.
"""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from booksource import Book

from . import (BASE_DIR, build_grouped_books, estimate_book_word_count,
               estimate_reading_time, format_reading_time, format_word_count,
               get_asset_version, next_free_folder, sanitize_folder_name,
               title_group_key, transliterate_for_sort)

router = APIRouter()

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# -- the library view -----------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def library_view(request: Request):
    """The library, read from SQLite — no EPUB is parsed to render it."""
    from . import get_db

    cards = [library_card(row) for row in get_db().list_books()]
    return templates.TemplateResponse(
        request=request,
        name="library.html",
        context={
            "groups": build_grouped_books(cards),
            "asset_version": get_asset_version(
                "static/js/library-app.js", "static/css/library.css"),
        },
    )


def library_card(row: dict) -> dict:
    """One books row, shaped for a library card."""
    from . import get_db

    progress = get_db().get_progress(row["slug"])
    title = row["title"] or row["slug"]
    word_count = row["word_count"] or 0
    return {
        "slug": row["slug"],
        "title": title,
        "author": row["author"] or "",
        "stats_display": (
            f"{format_word_count(word_count)} · "
            f"{format_reading_time(estimate_reading_time(word_count))}"
        ) if word_count > 0 else "",
        "cover_url": (
            f"/book/{quote(row['slug'], safe='')}/"
            f"{quote(row['cover_path'], safe='/')}"
            if row["cover_path"] else None
        ),
        "unsupported": row["unsupported"],
        "progress_percent": int(progress["scroll_percent"] or 0) if progress else 0,
        "has_progress": progress is not None,
        "is_completed": bool(progress["is_completed"]) if progress else False,
        "title_sort_key": transliterate_for_sort(title),
        "title_group": title_group_key(title),
    }


# -- upload ---------------------------------------------------------------

@router.post("/upload")
def upload_book(file: UploadFile = File(...)):
    """Upload → stored → metadata extracted, in one step. No subprocess.

    Sync on purpose: FastAPI runs this handler in a threadpool, which is
    where the CPU-bound parse and word count belong.
    """
    from . import BOOKS_DIR, book_cache, get_db

    safe_filename = os.path.basename((file.filename or "").replace("\\", "/"))
    if not safe_filename.lower().endswith(".epub"):
        raise HTTPException(status_code=400, detail="Only EPUB files are supported")

    temp_dir = BASE_DIR / "temp"
    temp_dir.mkdir(exist_ok=True)
    temp_path = temp_dir / f"{uuid.uuid4().hex}.epub"
    with open(temp_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    try:
        book = Book.open(temp_path)
        if not book.opened:
            # Not a book at all: refuse with the named reason, store nothing.
            raise HTTPException(status_code=400,
                                detail=book.unsupported or "unopenable book")

        db = get_db()
        title = book.title or os.path.splitext(safe_filename)[0]
        slug = sanitize_folder_name(title) or "book"
        existing = db.get_book(slug)
        if existing is not None and _same_book(existing, book):
            target_slug, replaced = slug, True          # same book: in place
        else:
            target_slug = next_free_folder(
                BOOKS_DIR, slug,
                taken={row["slug"] for row in db.list_books()}).name
            replaced = False

        folder = BOOKS_DIR / target_slug
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{target_slug}.epub"
        os.replace(temp_path, target)

        word_count = 0 if book.unsupported else estimate_book_word_count(book)
        reason = book.unsupported
        db.upsert_book({
            "slug": target_slug,
            # The path is relative to the books directory: books/<slug>/<slug>.epub
            "path": target.relative_to(BOOKS_DIR).as_posix(),
            "title": title,
            "author": book.author,
            "language": book.language,
            "identifier": book.identifier,
            "publisher": book.publisher,
            "date": book.date,
            "word_count": word_count,
            "cover_path": book.cover_path,
            "unsupported": reason,
            "added_at": (existing["added_at"] if replaced
                         else datetime.now().isoformat()),
        })
        book_cache.drop(target_slug)  # a replaced file must be re-opened
        book.close()

        return {"status": "success", "slug": target_slug, "title": title,
                "replaced": replaced, "unsupported": reason}
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _same_book(row: dict, book: Book) -> bool:
    """True when the row and the upload are the same book.

    The identifier decides when both declare one; otherwise title and author
    together. Only a genuine match may replace a row in place — that is what
    keeps a re-upload's annotations attached.
    """
    if row["identifier"] and book.identifier:
        return row["identifier"] == book.identifier
    return ((row["title"] or "") == (book.title or "")
            and (row["author"] or "") == (book.author or ""))


# -- delete ---------------------------------------------------------------

@router.delete("/delete/{slug}")
def delete_book(slug: str):
    """Remove the book folder and its row; the annotations stay."""
    if ".." in slug or "/" in slug or "\\" in slug:
        raise HTTPException(status_code=400, detail="Invalid book ID")
    from . import BOOKS_DIR, book_cache, get_db

    db = get_db()
    folder = BOOKS_DIR / slug
    if db.get_book(slug) is None and not folder.exists():
        raise HTTPException(status_code=404, detail="Book not found")
    if folder.exists():
        shutil.rmtree(folder)
    db.delete_book(slug)
    book_cache.drop(slug)
    return {"status": "success",
            "message": "Book deleted. Your highlights and analyses are preserved."}
