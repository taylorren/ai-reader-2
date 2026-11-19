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

import errno
import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from booksource import Book

# `BOOKS_DIR` is read through the module at every use rather than imported by
# value: the suite points the app at a private library by patching
# `app_state.BOOKS_DIR`, and a value bound at import time would not see it.
# The old function-local `from . import BOOKS_DIR` did exactly that by
# accident — it re-read the attribute per call — and it is also why the
# dependency direction was invisible (REVIEW P3-14).
from . import app_state
from .app_state import BASE_DIR, book_cache, get_db
from .assets import get_asset_version
from .text import (estimate_book_word_count, estimate_reading_time,
                   format_reading_time, format_word_count)
from .titles import (build_grouped_books, next_free_folder,
                     sanitize_folder_name, title_group_key,
                     transliterate_for_sort)

router = APIRouter()

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# -- the library view -----------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def library_view(request: Request):
    """The library, read from SQLite — no EPUB is parsed to render it.

    The one exception is a one-time backfill: a book uploaded before
    `chapter_count` existed is opened once so its card can show whole-book
    progress, then the column is written and every later render is SQLite.
    """

    rows = get_db().books_with_progress()
    backfill_chapter_counts(rows)
    cards = [library_card(row) for row in rows]
    return templates.TemplateResponse(
        request=request,
        name="library.html",
        context={
            "groups": build_grouped_books(cards),
            "asset_version": get_asset_version(
                "static/js/library-app.js", "static/css/library.css"),
        },
    )


def backfill_chapter_counts(rows: list[dict]) -> None:
    """Fill in `chapter_count` for books uploaded before the column existed.

    Whole-book progress needs the spine length, which an upload now writes
    with its row. A row that predates the column carries 0: its book is
    opened once here and the count stored, so this is a no-op on every later
    render — and for every newly uploaded book. An unsupported book is
    skipped: it has no spine to read and no progress to place.
    """

    missing = [row for row in rows
               if not row.get("chapter_count") and not row.get("unsupported")]
    if not missing:
        return
    db = get_db()
    for row in missing:
        with book_cache.borrow(row["slug"], app_state.BOOKS_DIR / row["path"]) as book:
            chapter_count = book.chapter_count
        if chapter_count:
            db.set_chapter_count(row["slug"], chapter_count)
            row["chapter_count"] = chapter_count


def book_percent(progress: dict | None, chapter_count: int) -> int:
    """How far through the whole book the reader is, as a percentage.

    `scroll_percent` is the position *within the current chapter* — what
    resume needs. A card must not show that as book progress: 60% down an
    early chapter is not 60% of the book. The chapter's place in the spine is
    combined with the in-chapter fraction, so the last chapter's last page is
    100%. A single-document book is exactly its scroll percent.
    """
    if not progress:
        return 0
    scroll = min(100.0, max(0.0, progress["scroll_percent"] or 0.0))
    if chapter_count <= 1:
        return int(round(scroll))
    index = min(max(progress["chapter_index"] or 0, 0), chapter_count - 1)
    return int(round((index + scroll / 100.0) / chapter_count * 100))


def library_card(row: dict) -> dict:
    """One books row, shaped for a library card.

    The progress fields arrive joined onto the row (`books_with_progress`), so
    shaping a card touches no database at all — it used to open a connection
    per book, on every render (REVIEW P2-2).
    """
    progress = None
    if row.get("p_present"):
        progress = {"chapter_index": row["p_chapter"] or 0,
                    "scroll_percent": row["p_scroll"] or 0.0,
                    "is_completed": row["p_completed"]}
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
        "progress_percent": book_percent(progress, row.get("chapter_count") or 0),
        "has_progress": progress is not None,
        "is_completed": bool(progress["is_completed"]) if progress else False,
        "title_sort_key": transliterate_for_sort(title),
        "title_group": title_group_key(title),
    }


# -- upload ---------------------------------------------------------------

# An upload cleans up after itself in `finally`. A killed process cannot run it,
# so half-written artifacts accumulate silently — the sweep below clears them at
# startup (REVIEW P3-10). Three kinds: a staging file in `temp/`, a `.part` beside
# a book, and the empty folder a kill can leave before a file lands.
UPLOAD_ORPHAN_AGE_SECONDS = 3600


def sweep_uploads(max_age_seconds: int = UPLOAD_ORPHAN_AGE_SECONDS) -> int:
    """Remove half-finished uploads an interrupted process left behind.

    Three artifacts, all older than `max_age_seconds` so a sweep can never race
    an upload that is in flight: `temp/*.epub` (killed between the copy and the
    move), `books/<slug>/*.part` (killed between staging and the rename that
    publishes the book), and the empty `books/<slug>/` an upload that died
    before its file landed leaves behind. A book file is never touched: this
    clears only artifacts no reader could open.

    Runs at startup (`server.py`), where no upload is in flight. The reader
    decided against a size cap on uploads (single user, own disk); this is the
    other half of P3-10, and the recovery for a kill the request's own
    `finally` cannot cover.
    """
    cutoff = time.time() - max_age_seconds
    removed = 0

    def old(path: Path) -> bool:
        try:
            return path.stat().st_mtime < cutoff
        except OSError:
            return False

    staging = BASE_DIR / "temp"
    if staging.is_dir():
        for leftover in staging.glob("*.epub"):
            try:
                if old(leftover):
                    leftover.unlink()
                    removed += 1
            except OSError:
                continue        # gone already, or not ours to remove: leave it

    books = app_state.BOOKS_DIR
    if not books.is_dir():
        return removed
    for folder in books.iterdir():
        if not folder.is_dir():
            continue
        # Decided before a part is unlinked: deleting the part updates the
        # folder's mtime, which would make the folder look young again.
        folder_old = old(folder)
        for part in folder.glob("*.part"):
            try:
                if old(part):
                    part.unlink()
                    removed += 1
            except OSError:
                continue
        try:
            if folder_old and not any(folder.iterdir()):
                folder.rmdir()
                removed += 1
        except OSError:
            continue            # not empty (a book is landing), or already gone
    return removed


def _stage_upload(file: UploadFile, temp_path: Path) -> None:
    """Write the request body to `temp_path`, removing a partial copy on failure.

    This runs before the `try/finally` that owns the staging file, so it has to
    clean up itself: a copy that dies — client gone, disk full — used to leave
    a partial `.epub` in `temp/` that only a restart cleared.
    """
    try:
        with open(temp_path, "wb") as out:
            shutil.copyfileobj(file.file, out)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def _stage_beside(source: Path, part: Path) -> None:
    """Put the upload's bytes on the part's filesystem, not yet in place.

    `part` sits beside the book it will become, so the rename that publishes it
    is same-filesystem and atomic. A rename is tried first — the usual case,
    where `temp/` and `books/` share a filesystem — and the staging file itself
    becomes the part. When they do not, `os.replace` raises `EXDEV`: in the
    container `/app/temp` lives in the image layer while `/app/books` is a bind
    mount, and every upload used to die there with `Invalid cross-device link`.
    The fallback copies instead, into the same place.
    """
    try:
        os.replace(source, part)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    shutil.copyfile(source, part)


@router.post("/upload")
def upload_book(file: UploadFile = File(...)):
    """Upload → validated → stored, in one step. No subprocess.

    Sync on purpose: FastAPI runs this handler in a threadpool, which is where
    the CPU-bound parse and word count belong.

    The order is the guarantee: the EPUB is parsed *and* counted while it is
    still a staging file, its row is written next, and only then does one
    rename publish it on the shelf. A failure anywhere before that rename
    leaves the library exactly as it was — including a re-upload, whose old
    file is not touched until the new metadata has been accepted. The rename
    is `os.replace`, so a reader never sees a half-written book.
    """

    safe_filename = os.path.basename((file.filename or "").replace("\\", "/"))
    if not safe_filename.lower().endswith(".epub"):
        raise HTTPException(status_code=400, detail="Only EPUB files are supported")

    temp_dir = BASE_DIR / "temp"
    temp_dir.mkdir(exist_ok=True)
    temp_path = temp_dir / f"{uuid.uuid4().hex}.epub"
    _stage_upload(file, temp_path)

    book = None
    part = None
    folder = None
    created_folder = False
    try:
        book = Book.open(temp_path)
        if not book.opened:
            # Not a book at all: refuse with the named reason, store nothing.
            raise HTTPException(status_code=400,
                                detail=book.unsupported or "unopenable book")

        # Everything that reads the EPUB happens before the shelf is touched:
        # a parse that fails here leaves only the staging file to clean up,
        # and a re-upload's old book is still the book the library has.
        title = book.title or os.path.splitext(safe_filename)[0]
        word_count = 0 if book.unsupported else estimate_book_word_count(book)
        reason = book.unsupported

        db = get_db()
        slug = sanitize_folder_name(title) or "book"
        existing = db.get_book(slug)
        if existing is not None and _same_book(existing, book):
            target_slug, replaced = slug, True          # same book: in place
        else:
            target_slug = next_free_folder(
                app_state.BOOKS_DIR, slug,
                taken={row["slug"] for row in db.list_books()}).name
            replaced = False

        folder = app_state.BOOKS_DIR / target_slug
        created_folder = not folder.exists()
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{target_slug}.epub"
        # Unique per request: two uploads of the same new book must not stage
        # over each other's bytes between the write and the rename.
        part = target.with_name(f"{target.name}.{uuid.uuid4().hex}.part")
        _stage_beside(temp_path, part)

        db.upsert_book({
            "slug": target_slug,
            # The path is relative to the books directory: books/<slug>/<slug>.epub
            "path": target.relative_to(app_state.BOOKS_DIR).as_posix(),
            "title": title,
            "author": book.author,
            "language": book.language,
            "identifier": book.identifier,
            "publisher": book.publisher,
            "date": book.date,
            "word_count": word_count,
            "chapter_count": book.chapter_count,
            "cover_path": book.cover_path,
            "unsupported": reason,
            "added_at": (existing["added_at"] if replaced
                         else datetime.now().isoformat()),
        })

        try:
            os.replace(part, target)
        except OSError:
            # The row ran ahead of the shelf. Put the metadata back (a fresh
            # book loses its row) so the two agree again, then fail.
            if replaced:
                db.upsert_book(existing)
            else:
                db.delete_book(target_slug)
            raise
        book_cache.drop(target_slug)  # a replaced file must be re-opened

        return {"status": "success", "slug": target_slug, "title": title,
                "replaced": replaced, "unsupported": reason}
    finally:
        # The staged file and the folder are removed only while they are still
        # ours to remove: after a successful publish the part is gone and the
        # folder holds a book.
        if part is not None:
            part.unlink(missing_ok=True)
        if created_folder and folder is not None:
            try:
                folder.rmdir()          # only if nothing landed in it
            except OSError:
                pass
        if book is not None:
            book.close()
        temp_path.unlink(missing_ok=True)


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

    db = get_db()
    folder = app_state.BOOKS_DIR / slug
    if db.get_book(slug) is None and not folder.exists():
        raise HTTPException(status_code=404, detail="Book not found")
    if folder.exists():
        shutil.rmtree(folder)
    db.delete_book(slug)
    book_cache.drop(slug)
    return {"status": "success",
            "message": "Book deleted. Your highlights and analyses are preserved."}
