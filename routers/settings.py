"""Settings routes: provider override, progress, completion.

Landed:

    GET  /api/settings                   provider override + default
    POST /api/settings                   set or clear the override
    POST /api/progress                   reading position (chapter + percent)
    POST /api/books/{slug}/completion    mark a book completed or not
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ai_service import PROVIDERS

# `BOOKS_DIR` is read through the module at every use rather than imported by
# value: the suite points the app at a private library by patching
# `app_state.BOOKS_DIR`, and a value bound at import time would not see it.
# The old function-local `from . import BOOKS_DIR` did exactly that by
# accident — it re-read the attribute per call — and it is also why the
# dependency direction was invisible (REVIEW P3-14).
from . import app_state
from .app_state import book_cache, get_db, runtime_settings

router = APIRouter()


class SettingsUpdate(BaseModel):
    """Runtime settings. A null override clears it and returns to the default."""
    provider_override: str | None = None


@router.get("/api/settings")
def get_settings():
    """The current provider override and the .env default behind it."""
    return {
        "provider_override": runtime_settings["provider_override"],
        "default_provider": os.getenv("OLLAMA_DEFAULT_PROVIDER", "ollama_cloud"),
        "status": "success",
    }


@router.post("/api/settings")
def update_settings(settings: SettingsUpdate):
    """Set the provider override, or clear it with a null value."""
    if settings.provider_override is None:
        runtime_settings["provider_override"] = None
    else:
        provider = settings.provider_override.lower()
        if provider not in PROVIDERS:
            raise HTTPException(
                status_code=400,
                detail="Invalid provider. Must be 'ollama' or 'ollama_cloud'")
        runtime_settings["provider_override"] = provider
    return {"provider_override": runtime_settings["provider_override"],
            "status": "success"}


class ProgressUpdate(BaseModel):
    """A reading position: the chapter, how far down it, and the block there.

    `block_id` is the position's identity — the first block on screen when the
    reader stopped — and it is what a resume is anchored to; `scroll_percent`
    is the fallback, for a row written before the anchor existed and for a
    block the served document no longer has (REVIEW P2-10).

    `seq` orders the writes from the client. Saves are fire-and-forget, so one
    from the chapter a reader just left can land after the new chapter's, and
    the stored position then moved backwards (REVIEW P2-8). 0 means "no ordering
    information" and is always accepted.
    """
    book_id: str
    chapter_index: int
    scroll_percent: float = 0.0
    block_id: str | None = None
    seq: int = 0



@router.post("/api/books/{slug}/completion")
def set_completion(slug: str, completed: bool):
    """Mark a book as completed or not completed."""

    db = get_db()
    if db.get_book(slug) is None:
        raise HTTPException(status_code=404, detail="Book not found")
    db.set_completed(slug, completed)
    return {"status": "success", "slug": slug, "completed": completed}


@router.post("/api/progress")
def save_progress(update: ProgressUpdate):
    """Save the reading position: chapter plus percent within the chapter."""

    db = get_db()
    row = db.get_book(update.book_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    with book_cache.borrow(update.book_id, app_state.BOOKS_DIR / row["path"]) as book:
        if not 0 <= update.chapter_index < book.chapter_count:
            raise HTTPException(status_code=400, detail="No such chapter")
        chapter_path = book.spine[update.chapter_index]
    db.save_progress(
        update.book_id,
        update.chapter_index,
        scroll_percent=max(0.0, min(100.0, update.scroll_percent)),
        block_id=update.block_id,
        chapter_path=chapter_path,
        seq=update.seq,
    )
    return {"status": "success"}
