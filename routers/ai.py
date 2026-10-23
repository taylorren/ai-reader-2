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
from pydantic import BaseModel

from ai_service import PROVIDERS, AIServiceError

from . import _runtime_settings, get_ai_service, get_db
from .highlights import store_highlight

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
    provider: str = "ollama_cloud"


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


class DiscussionStartRequest(BaseModel):
    """The opener of a discussion: the selection and its surroundings."""
    selected_text: str
    context_before: str = ""
    context_after: str = ""
    provider: str = "ollama_cloud"


class DiscussionContinueRequest(BaseModel):
    selected_text: str
    conversation_history: list[ConversationMessage]
    user_message: str
    provider: str = "ollama_cloud"


class DiscussionSummarizeRequest(BaseModel):
    selected_text: str
    conversation_history: list[ConversationMessage]
    provider: str = "ollama_cloud"


def _provider(requested: str | None) -> str:
    """The provider to use: the runtime override, else the request, else default.

    An unknown provider is a 400 here, before any call is attempted.
    """
    provider = (_runtime_settings["provider_override"] or requested
                or "ollama_cloud").lower()
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
    """
    highlight_id = req.highlight_id
    if highlight_id is None:
        if not req.book_id or req.chapter_index is None or not req.selected_text:
            raise HTTPException(
                status_code=400,
                detail="A new highlight needs a book, a chapter and a selection")
        highlight_id = store_highlight(
            req.book_id, req.chapter_index, req.selected_text,
            block_id=req.block_id,
            context_before=req.context_before, context_after=req.context_after)
    else:
        _require_highlight(highlight_id)
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
            req.selected_text, _history(req.conversation_history),
            provider=provider)
    except AIServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"summary": summary, "provider_used": provider, "status": "success",
            "original_message_count": len(req.conversation_history)}


@router.put("/api/ai/update/{analysis_id}")
def update_analysis(analysis_id: int, payload: dict):
    """Edit a saved analysis' text (an edited note)."""
    db = get_db()
    if db.get_analysis(analysis_id) is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    db.update_analysis(analysis_id, payload.get("response", ""))
    return {"status": "success"}


@router.delete("/api/ai/delete/{analysis_id}")
def delete_analysis(analysis_id: int):
    """Remove one analysis; its highlight goes only if it was the last one."""
    db = get_db()
    if db.get_analysis(analysis_id) is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    db.delete_analysis(analysis_id)
    return {"status": "success"}


