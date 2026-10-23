"""Highlight routes: CRUD, the highlights view, and the Markdown export. (P4)

    POST   /api/highlight                      create a highlight
    GET    /api/highlights/{slug}/{chapter}    a chapter's highlights + analyses
    DELETE /api/highlight/{highlight_id}       remove a highlight and its analyses
    GET    /highlights/{slug}                  the highlights view (HTML)
    GET    /highlights/{slug}/export           the same, as Markdown

Markdown is rendered and sanitised here, on the way out (bleach over
markdown-it-py) — sanitising belongs on AI output and user notes, never on
the book (SPEC.md).
"""

from __future__ import annotations

from urllib.parse import quote

import bleach
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from markupsafe import Markup
from pydantic import BaseModel

# `BOOKS_DIR` is read through the module at every use rather than imported by
# value: the suite points the app at a private library by patching
# `app_state.BOOKS_DIR`, and a value bound at import time would not see it.
# The old function-local `from . import BOOKS_DIR` did exactly that by
# accident — it re-read the attribute per call — and it is also why the
# dependency direction was invisible (REVIEW P3-14).
from . import app_state
from .app_state import BASE_DIR, book_cache, get_db
from .assets import get_asset_version

router = APIRouter()

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# The client renders with marked (gfm + breaks); the server mirrors that, so a
# note looks the same in the reader panel and in the highlights view.
_markdown = (
    MarkdownIt("commonmark", {"html": False, "breaks": True, "linkify": True})
    .enable("table")
    .enable("strikethrough")
)

_ALLOWED_TAGS = [
    "p", "br", "ul", "ol", "li", "strong", "em", "del",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "pre", "code", "blockquote", "a", "hr",
    "table", "thead", "tbody", "tr", "th", "td",
]
_ALLOWED_ATTRS = {"a": ["href", "title"], "th": ["align"], "td": ["align"]}


def render_markdown(text: str) -> str:
    """Markdown → safe HTML. Raw HTML is off upstream; bleach is depth."""
    if not text:
        return ""
    return bleach.clean(_markdown.render(text), tags=_ALLOWED_TAGS,
                        attributes=_ALLOWED_ATTRS, strip=True)


class HighlightRequest(BaseModel):
    """A new highlight: the selected text and where it sits."""
    book_id: str
    chapter_index: int
    selected_text: str
    chapter_path: str | None = None
    block_id: str | None = None
    context_before: str = ""
    context_after: str = ""


def _require_book(slug: str) -> dict:
    """The book's row, or 404. A highlight always names a stored book."""
    row = get_db().get_book(slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return row


def _require_chapter(slug: str, chapter_index: int) -> str:
    """The chapter's path in the book, validating the index against its spine.

    Returns the path rather than the book, because the caller needs one string
    from it and the cache hands a book out only for the length of a `borrow()`
    — holding one across a request is what let eviction close it mid-read
    (REVIEW P2-5).
    """

    row = _require_book(slug)
    with book_cache.borrow(slug, app_state.BOOKS_DIR / row["path"]) as book:
        if not 0 <= chapter_index < book.chapter_count:
            raise HTTPException(status_code=400, detail="No such chapter")
        return book.spine[chapter_index]


def highlight_kind(highlight: dict) -> str:
    """A highlight's kind: its first analysis' type, else a plain 'highlight'."""
    analyses = highlight.get("analyses") or []
    return analyses[0]["analysis_type"] if analyses else "highlight"


def store_highlight(book_id: str, chapter_index: int, selected_text: str,
                    chapter_path: str | None = None,
                    block_id: str | None = None,
                    context_before: str = "", context_after: str = "") -> int:
    """Validate and store a highlight, returning its id.

    The one place a highlight row is written: the highlight route and saving
    an analysis both come through here, so the reader's mark is created the
    same way whichever endpoint carries it.

    The *panel* only reaches it with content — the mark is created in the same
    act as the analysis it hangs on, so an explanation the reader never saves
    leaves nothing behind — but the row itself can stand alone, and
    `POST /api/highlight` stores exactly that. (The docstring here used to claim
    otherwise, which contradicted the route below it — REVIEW P3-7.)
    """
    spine_path = _require_chapter(book_id, chapter_index)
    selected = (selected_text or "").strip()
    if not selected:
        raise HTTPException(status_code=400, detail="Empty selection")
    return get_db().save_highlight(
        book_id, chapter_index, selected,
        chapter_path=chapter_path or spine_path,
        block_id=block_id,
        context_before=context_before, context_after=context_after,
    )


@router.post("/api/highlight")
def create_highlight(req: HighlightRequest):
    """Store a bare mark — a highlight with no analysis yet.

    The *app* does not call this: the panel saves a mark and its content in one
    act through `/api/ai/save`, which is what keeps an unsaved explanation from
    leaving a mark behind. This endpoint exists for the two things that need a
    bare mark on purpose — the tests, which use it to build the "highlight with
    no analyses" state the views must render, and any future import that brings
    marks over without their text. It is kept, not forgotten (REVIEW P3-15).
    """
    highlight_id = store_highlight(
        req.book_id, req.chapter_index, req.selected_text,
        chapter_path=req.chapter_path, block_id=req.block_id,
        context_before=req.context_before, context_after=req.context_after)
    return {"highlight_id": highlight_id, "status": "success"}


@router.get("/api/highlights/{slug}/{chapter_index}")
def chapter_highlights(slug: str, chapter_index: int):
    """A chapter's highlights, each with its analyses, for painting."""
    _require_chapter(slug, chapter_index)
    db = get_db()
    highlights = db.highlights_for_chapter(slug, chapter_index)
    for highlight in highlights:
        highlight["analyses"] = db.analyses_for_highlight(highlight["id"])
        highlight["kind"] = highlight_kind(highlight)
    return {"slug": slug, "chapter_index": chapter_index,
            "highlights": highlights}


@router.delete("/api/highlight/{highlight_id}")
def delete_highlight(highlight_id: int):
    """Remove a highlight and every analysis attached to it."""
    db = get_db()
    if db.get_highlight(highlight_id) is None:
        raise HTTPException(status_code=404, detail="Highlight not found")
    db.delete_highlight(highlight_id)
    return {"status": "success"}


# -- the highlights view and its export ------------------------------------

KIND_LABELS = {
    "fact_check": "解释说明",
    "discussion": "深入讨论",
    "comment": "个人笔记",
    "highlight": "高亮",
}


def _book_title(slug: str) -> str:
    row = get_db().get_book(slug)
    return (row["title"] or slug) if row else slug


def _view_items(slug: str) -> list[dict]:
    """One row per analysis (or per bare highlight), newest first.

    The highlights view is a reading record, so it lists analyses, not
    highlights: a highlight discussed and then annotated appears twice, each
    with its own text. A highlight with no analyses still appears once.
    """
    db = get_db()
    items = []
    for highlight in db.highlights_for(slug):
        analyses = db.analyses_for_highlight(highlight["id"])
        if not analyses:
            items.append({**highlight, "kind": "highlight",
                          "kind_label": KIND_LABELS["highlight"],
                          "analysis_id": None, "response": None,
                          "analysis_created_at": None, "response_html": ""})
            continue
        for analysis in analyses:
            items.append({
                **highlight,
                "kind": analysis["analysis_type"],
                "kind_label": KIND_LABELS.get(analysis["analysis_type"],
                                              analysis["analysis_type"]),
                "analysis_id": analysis["id"],
                "response": analysis["response"],
                "analysis_created_at": analysis["created_at"],
                "response_html": Markup(render_markdown(analysis["response"])),
            })
    items.sort(key=lambda item: item["analysis_created_at"] or item["created_at"],
               reverse=True)
    return items


def _stats(items: list[dict]) -> dict:
    counts = {kind: 0 for kind in KIND_LABELS}
    for item in items:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    counts["total"] = len(items)
    return counts


@router.get("/highlights/{slug}", response_class=HTMLResponse)
def highlights_view(request: Request, slug: str):
    """Every highlight and analysis for one book, newest first."""
    if get_db().get_book(slug) is None:
        raise HTTPException(status_code=404, detail="Book not found")
    items = _view_items(slug)
    return templates.TemplateResponse(
        request=request,
        name="highlights.html",
        context={
            "slug": slug,
            "book_title": _book_title(slug),
            "items": items,
            "stats": _stats(items),
            "asset_version": get_asset_version(
                "static/js/highlights-app.js", "static/css/highlights.css"),
        },
    )


@router.get("/highlights/{slug}/export")
def export_highlights(slug: str):
    """The highlights view as a Markdown file — a reading record you own."""
    if get_db().get_book(slug) is None:
        raise HTTPException(status_code=404, detail="Book not found")
    title = _book_title(slug)
    items = _view_items(slug)
    lines = [f"# {title}", "", f"*{len(items)} 条高亮与批注*", ""]
    for item in reversed(items):
        label = KIND_LABELS.get(item["kind"], item["kind"])
        lines.append(f"## {label} · 第 {item['chapter_index'] + 1} 章")
        lines.append("")
        # Every line of the quote, not just the first: a selection spanning two
        # paragraphs used to export as one quoted line followed by an unquoted
        # one, which reads as commentary rather than as the quoted text
        # (REVIEW P3-3). A blank line keeps the quote open as a bare `>`, so the
        # exported file carries no trailing whitespace.
        lines.append("\n".join(f"> {line}" if line.strip() else ">"
                               for line in item["selected_text"].splitlines()))
        lines.append("")
        if item["response"]:
            lines.append(item["response"])
            lines.append("")
    body = "\n".join(lines).rstrip() + "\n"
    # The slug can be CJK; HTTP headers are latin-1, so the readable name goes
    # in filename* (RFC 5987) and an ASCII fallback in filename.
    encoded = quote(f"{slug}-highlights.md", safe="")
    return Response(
        content=body,
        media_type="text/markdown",
        headers={
            "Content-Disposition":
                f"attachment; filename=\"highlights.md\"; filename*=UTF-8''{encoded}"
        },
    )



