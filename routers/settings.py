"""Settings routes: provider override, progress, completion.

Landed so far:

    POST /api/books/{slug}/completion   mark a book completed or not
    POST /api/progress                  reading position (chapter + percent)

Planned, per SPEC.md:

    GET  /api/settings     provider override status
    POST /api/settings     provider override
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class ProgressUpdate(BaseModel):
    book_id: str
    chapter_index: int
    scroll_percent: float = 0.0
    anchor: str | None = None


@router.post("/api/books/{slug}/completion")
def set_completion(slug: str, completed: bool):
    """Mark a book as completed or not completed."""
    from . import get_db

    db = get_db()
    if db.get_book(slug) is None:
        raise HTTPException(status_code=404, detail="Book not found")
    db.set_completed(slug, completed)
    return {"status": "success", "slug": slug, "completed": completed}


@router.post("/api/progress")
def save_progress(update: ProgressUpdate):
    """Save the reading position: chapter plus percent within the chapter."""
    from . import BOOKS_DIR, book_cache, get_db

    db = get_db()
    row = db.get_book(update.book_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    book = book_cache.get_or_open(update.book_id, BOOKS_DIR / row["path"])
    if not 0 <= update.chapter_index < book.chapter_count:
        raise HTTPException(status_code=400, detail="No such chapter")
    db.save_progress(
        update.book_id,
        update.chapter_index,
        scroll_percent=max(0.0, min(100.0, update.scroll_percent)),
        anchor=update.anchor,
        chapter_path=book.spine[update.chapter_index],
    )
    return {"status": "success"}
