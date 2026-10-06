"""Highlight routes: CRUD and the highlights view. (P4)

Planned, per SPEC.md:

    POST   /api/highlight
    GET    /api/highlights/{slug}/{chapter_index}
    DELETE /api/highlight/{highlight_id}
    GET    /highlights/{slug}          view and Markdown export
"""

from fastapi import APIRouter

router = APIRouter()
