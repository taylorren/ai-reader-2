"""AI routes: fact-check, discussion, summarise, save. (P4)

    POST   /api/ai/analyze                     fact_check | discussion (unsaved)
    POST   /api/ai/save                        persist an analysis
    POST   /api/ai/discussion/start            overview + seed history
    POST   /api/ai/discussion/continue         one discussion turn
    POST   /api/ai/discussion/summarize        a discussion, as one analysis
    PUT    /api/ai/update/{analysis_id}        edit a saved analysis
    DELETE /api/ai/delete/{analysis_id}        remove a saved analysis

AI output is stored as the Markdown the model produced; it is rendered and
sanitised on the way out (bleach over markdown-it-py, in highlights.py) and
again in the browser (DOMPurify) — never on the book. A failing AI call is a
502, never a 200 carrying error text.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from ai_service import PROVIDERS, AIServiceError

from .app_state import (default_provider, get_ai_service, get_db,
                        runtime_settings)
from .highlights import highlight_fields

router = APIRouter()

# The kinds an analysis can be. A Literal, not a `str`: `analysis_type` is
# written straight into the database, becomes a CSS class (`hl-<kind>`), a
# KIND_LABELS lookup and a stats key, so an arbitrary string is a broken
# highlight wearing a valid one's clothes. `/api/ai/analyze` already refused
# anything else; this makes the save path agree (REVIEW P2-11).
AnalysisType = Literal["fact_check", "discussion", "comment"]

# Past these lengths a discussion is nudged towards summarising, because the
# model's context window — not the browser — is the limit.
SUMMARIZE_HINT_AT = 15
CONTEXT_LIMIT_HINT_AT = 20


class AnalyzeRequest(BaseModel):
    """A one-shot analysis over the selected text (nothing is stored).

    `context_before`/`context_after` are the two slices of surrounding text the
    panel captures around the selection. They travel as halves rather than one
    string because the selection sits *between* them: joining them would hand
    the model a sentence with a hole where the quoted words belong (REVIEW P1-3).
    """
    analysis_type: str              # 'fact_check' or 'discussion'
    selected_text: str
    context_before: str = ""
    context_after: str = ""
    provider: str | None = None


class SaveAnalysisRequest(BaseModel):
    """A saved analysis, and the highlight it marks.

    `highlight_id` names an existing highlight (a second note on the same
    text). When it is absent, the selection travels with the analysis and the
    highlight is created here — the mark is stored only with its content, so
    an explanation the reader never saves leaves nothing behind.
    """
    highlight_id: int | None = None
    analysis_type: AnalysisType
    prompt: str = ""
    response: str
    book_id: str | None = None
    chapter_index: int | None = None
    selected_text: str | None = None
    block_id: str | None = None
    context_before: str = ""
    context_after: str = ""


class ConversationMessage(BaseModel):
    # Only the two roles a discussion has. `system` is the server's own prompt
    # (see ai_service._messages); accepting it from a client would let a turn
    # rewrite the model's instructions (REVIEW P2-11).
    role: Literal["user", "assistant"]
    content: str


class UpdateAnalysisRequest(BaseModel):
    """The edited text of a saved analysis — the note in the panel's textarea.

    A typed body, not the bare dict this route used to take. `{}` meant an
    empty note (the missing key defaulted to ""), so a malformed request erased
    the reader's words; `null` reached SQLite as NULL and raised; a number was
    stored as text. Only text the reader actually wrote replaces a saved note —
    removing one is what DELETE is for.
    """

    response: str

    @field_validator("response")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        """Reject a blank edit, keep the text verbatim.

        Not `.strip()`: Markdown's two trailing spaces are a hard line break,
        and an edit that round-trips through the panel must keep them.
        """
        if not value.strip():
            raise ValueError("response must not be blank")
        return value


class DiscussionStartRequest(BaseModel):
    """The opener of a discussion: the selection and its surroundings."""
    selected_text: str
    context_before: str = ""
    context_after: str = ""
    provider: str | None = None


class DiscussionContinueRequest(BaseModel):
    """One turn. `selected_text` is deliberately absent: the selection is the
    first user message of `conversation_history`, which the model already has —
    the field was accepted and never read (REVIEW P3-15)."""
    conversation_history: list[ConversationMessage]
    user_message: str
    provider: str | None = None


class DiscussionSummarizeRequest(BaseModel):
    """The whole discussion, as one analysis. The transcript is the input: the
    selection is its first message, so no separate field is needed."""
    conversation_history: list[ConversationMessage]
    provider: str | None = None


def _provider(requested: str | None) -> str:
    """The provider to use: the runtime override, else the request, else default.

    An unknown provider is a 400 here, before any call is attempted.
    """
    provider = (runtime_settings["provider_override"] or requested
                or default_provider()).lower()
    if provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail="Invalid AI provider")
    return provider


def _require_highlight(highlight_id: int) -> dict:
    highlight = get_db().get_highlight(highlight_id)
    if highlight is None:
        raise HTTPException(status_code=404, detail="Highlight not found")
    return highlight


def _history(messages: list[ConversationMessage]) -> list[dict]:
    return [{"role": message.role, "content": message.content}
            for message in messages]


@router.post("/api/ai/analyze")
async def analyze_text(req: AnalyzeRequest):
    """Run a fact-check or discussion over the selection; store nothing."""
    provider = _provider(req.provider)
    if req.analysis_type not in ("fact_check", "discussion"):
        raise HTTPException(status_code=400, detail="Invalid analysis type")
    service = get_ai_service()
    try:
        if req.analysis_type == "fact_check":
            response = await service.fact_check(
                req.selected_text, context_before=req.context_before,
                context_after=req.context_after, provider=provider)
        else:
            response = await service.discuss(
                req.selected_text, context_before=req.context_before,
                context_after=req.context_after, provider=provider)
    except AIServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"response": response, "provider_used": provider, "status": "success"}


@router.post("/api/ai/save")
def save_analysis(req: SaveAnalysisRequest):
    """Persist an analysis — and, when there is none yet, the highlight it marks.

    A highlight is the mark a saved analysis hangs on: creating it here, in
    the same act, is what keeps an unsaved explanation from leaving a mark.
    The two rows are one transaction (`Database.save_highlight_with_analysis`),
    so a failure on the analysis cannot leave the mark behind either.
    """
    if req.highlight_id is None:
        if not req.book_id or req.chapter_index is None or not req.selected_text:
            raise HTTPException(
                status_code=400,
                detail="A new highlight needs a book, a chapter and a selection")
        highlight_id, analysis_id = get_db().save_highlight_with_analysis(
            **highlight_fields(
                req.book_id, req.chapter_index, req.selected_text,
                block_id=req.block_id,
                context_before=req.context_before,
                context_after=req.context_after),
            analysis_type=req.analysis_type, prompt=req.prompt,
            response=req.response)
    else:
        _require_highlight(req.highlight_id)
        highlight_id = req.highlight_id
        analysis_id = get_db().save_analysis(
            highlight_id, req.analysis_type, req.prompt, req.response)
    return {"analysis_id": analysis_id, "highlight_id": highlight_id,
            "status": "success"}


@router.post("/api/ai/discussion/start")
async def start_discussion(req: DiscussionStartRequest):
    """Open an interactive discussion: a brief overview, then a seed history."""
    provider = _provider(req.provider)
    try:
        overview = await get_ai_service().discussion_overview(
            req.selected_text, context_before=req.context_before,
            context_after=req.context_after, provider=provider)
    except AIServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "response": overview,
        "provider_used": provider,
        "status": "success",
        "conversation_history": [
            {"role": "user", "content": req.selected_text},
            {"role": "assistant", "content": overview},
        ],
    }


@router.post("/api/ai/discussion/continue")
async def continue_discussion(req: DiscussionContinueRequest):
    """One discussion turn. The user's message is not sent twice."""
    provider = _provider(req.provider)
    history = _history(req.conversation_history)
    if not history or history[-1].get("content") != req.user_message:
        history.append({"role": "user", "content": req.user_message})
    try:
        response = await get_ai_service().continue_discussion(
            req.user_message, history, provider=provider)
    except AIServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    history.append({"role": "assistant", "content": response})
    warnings = []
    if len(history) >= CONTEXT_LIMIT_HINT_AT:
        warnings.append("对话接近上下文限制，请尽快总结")
    elif len(history) >= SUMMARIZE_HINT_AT:
        warnings.append("对话较长，建议考虑总结当前讨论")
    return {
        "response": response,
        "provider_used": provider,
        "status": "success",
        "conversation_history": history,
        "message_count": len(history),
        "warnings": warnings,
    }


@router.post("/api/ai/discussion/summarize")
async def summarize_discussion(req: DiscussionSummarizeRequest):
    """Collapse a discussion into one comprehensive analysis."""
    provider = _provider(req.provider)
    try:
        summary = await get_ai_service().summarize_conversation(
            _history(req.conversation_history), provider=provider)
    except AIServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"summary": summary, "provider_used": provider, "status": "success",
            "original_message_count": len(req.conversation_history)}


@router.put("/api/ai/update/{analysis_id}")
def update_analysis(analysis_id: int, req: UpdateAnalysisRequest):
    """Edit a saved analysis' text (an edited note).

    The body is an `UpdateAnalysisRequest`: a missing, null, blank or non-string
    `response` is a 422 before this function runs, so a malformed edit cannot
    replace a note with nothing.
    """
    db = get_db()
    if db.get_analysis(analysis_id) is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    db.update_analysis(analysis_id, req.response)
    return {"status": "success"}


@router.delete("/api/ai/delete/{analysis_id}")
def delete_analysis(analysis_id: int):
    """Remove one analysis; its highlight goes only if it was the last one."""
    db = get_db()
    if db.get_analysis(analysis_id) is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    db.delete_analysis(analysis_id)
    return {"status": "success"}


