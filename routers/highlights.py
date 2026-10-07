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

from . import BASE_DIR, get_asset_version, get_db

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


def _require_chapter(slug: str, chapter_index: int):
    """The open book, validating the chapter index against its spine."""
    from . import BOOKS_DIR, book_cache

    row = _require_book(slug)
    book = book_cache.get_or_open(slug, BOOKS_DIR / row["path"])
    if not 0 <= chapter_index < book.chapter_count:
        raise HTTPException(status_code=400, detail="No such chapter")
    return book


def highlight_kind(highlight: dict) -> str:
    """A highlight's kind: its first analysis' type, else a plain 'highlight'."""
    analyses = highlight.get("analyses") or []
    return analyses[0]["analysis_type"] if analyses else "highlight"


@router.post("/api/highlight")
def create_highlight(req: HighlightRequest):
    """Save a highlight. Its analyses arrive later, one endpoint at a time."""
    book = _require_chapter(req.book_id, req.chapter_index)
    selected = req.selected_text.strip()
    if not selected:
        raise HTTPException(status_code=400, detail="Empty selection")
    highlight_id = get_db().save_highlight(
        req.book_id, req.chapter_index, selected,
        chapter_path=req.chapter_path or book.spine[req.chapter_index],
        block_id=req.block_id,
        context_before=req.context_before, context_after=req.context_after,
    )
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
        lines.append(f"> {item['selected_text']}")
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



