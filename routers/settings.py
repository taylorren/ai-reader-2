"""Settings routes: provider override, progress, completion. (P4 — completion early)

Landed so far (the library's completion toggle needs it):

    POST /api/books/{slug}/completion   mark a book completed or not

Planned, per SPEC.md:

    GET  /api/settings     provider override status
    POST /api/settings     provider override
    POST /api/progress     reading position
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/api/books/{slug}/completion")
def set_completion(slug: str, completed: bool):
    """Mark a book as completed or not completed."""
    from . import get_db

    db = get_db()
    if db.get_book(slug) is None:
        raise HTTPException(status_code=404, detail="Book not found")
    db.set_completed(slug, completed)
    return {"status": "success", "slug": slug, "completed": completed}
