"""AI routes: fact-check, discussion, summarise, save. (P4)

Planned, per SPEC.md:

    POST   /api/ai/analyze
    POST   /api/ai/save
    POST   /api/ai/discussion/start | continue | summarize
    PUT    /api/ai/update/{analysis_id}
    DELETE /api/ai/delete/{analysis_id}

Sanitising AI output belongs here, on the way out (bleach) — never on the book.
"""

from fastapi import APIRouter

router = APIRouter()
