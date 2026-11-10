"""The AI client: local Ollama and remote Cline, one OpenAI-compatible surface.

Reimplemented from ai-reader's service (its behaviour is the requirement),
not copied. Two providers share one endpoint shape: `ollama` is a local daemon,
`cline` is the Cline API (api.cline.bot), billed to CLINE_KEY. The endpoint,
key and model differ per provider. Failures raise `AIServiceError` —
a route maps that to 502, so an AI failure is never a 200 carrying error text.

Every call is async httpx: the FastAPI routes that await it are async too.
Prompts ask for Simplified Chinese, matching the reference's output contract.
"""

from __future__ import annotations

import asyncio
import os

import httpx


class AIServiceError(Exception):
    """An AI call failed — network, HTTP status, or unreadable response."""


PROVIDERS = ("ollama", "cline")

# How much of the selection's surroundings travels with it. The panel captures
# the same span (CONTEXT_SPAN in panel.js), so the two bounds agree.
CONTEXT_SPAN = 300


def _excerpt(selected: str, before: str = "", after: str = "",
             span: int = CONTEXT_SPAN) -> str:
    """The selection with its surroundings, labelled — never the bare join.

    `computeSelection` in the panel captures the text around a selection as two
    slices with the selection cut out of the middle, so joining them hands the
    model a sentence with a hole where the quoted words belong. Labelling the
    three parts is what lets a short or pronoun-first selection — 他們, 该党,
    因此 — be answered with its referent in view instead of guessed, and the
    span keeps a long paragraph from swamping the selection (REVIEW P1-3).

    Returns "" when there is no context to show; the caller then sends the bare
    selection, which is exactly the prompt the reader got before.
    """
    if not (before or after):
        return ""
    lines = ["（上下文，仅供参考）"]
    if before:
        lines.append(f"上文：…{before[-span:]}")
    lines.append(f"【选中的文本】{selected}")
    if after:
        lines.append(f"下文：{after[:span]}…")
    return "\n".join(lines)


def _system_prompt(provider: str) -> str:
    """The Chinese-output contract the reference app enforces per provider."""
    if provider == "ollama":
        return (
            "你是中文阅读助手。必须仅使用简体中文回答。"
            "不要输出英文句子，不要输出英文小标题；如需术语请给出中文解释。"
        )
    return "请使用简体中文回答，保持表达清晰、准确。"


# How much of a rejected call's own words travel on. A provider puts the reason
# in the body — Ollama Cloud answers an account with no credits with
# `402 {"error": {"message": "Add usage credits or subscribe …"}}` — and that
# is the only sentence a reader can act on. The whole body is not relayed: it
# is the provider's payload, and the panel has room for a line.
ERROR_DETAIL_LIMIT = 300


def _provider_error(exc: httpx.HTTPStatusError) -> str:
    """The status line plus whatever the provider said about it.

    `raise_for_status()` keeps the status and drops the body, so an exhausted
    Ollama Cloud account reached the panel as the bare phrase "402 Payment
    Required" — with the reason ("Add usage credits or subscribe …") lost, and
    nothing to do about it. Both Ollama shapes are read: `{"error":
    {"message": …}}` on its OpenAI-compatible endpoint, `{"error": …}` on its
    native one. A body that says nothing usable leaves the status line alone.
    """
    response = exc.response
    status = f"{response.status_code} {response.reason_phrase}".strip()
    try:
        data = response.json()
    except ValueError:
        return status
    if not isinstance(data, dict):
        return status
    message = data.get("error")
    if isinstance(message, dict):
        message = message.get("message")
    if not isinstance(message, str) or not message.strip():
        message = data.get("detail") or data.get("message")
    if not isinstance(message, str) or not message.strip():
        return status
    message = " ".join(message.split())
    if len(message) > ERROR_DETAIL_LIMIT:
        message = message[:ERROR_DETAIL_LIMIT].rstrip() + "…"
    return f"{status}: {message}"


class AIService:
    """Fact-check, discussion and summarising against an Ollama endpoint."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        # Every endpoint, key and model comes from the environment (.env) — no
        # value is baked in here. A missing one is reported by `connection()`,
        # naming the variable, when that provider is first used.
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "")
        self.api_key = api_key or os.getenv("OLLAMA_API_KEY", "")
        self.model = os.getenv("OLLAMA_MODEL", "")
        # The remote provider is the Cline API: OpenAI-compatible, one key for
        # every upstream model, whose ids are `provider/model`.
        self.cline_base_url = os.getenv("CLINE_BASE_URL", "")
        self.cline_key = os.getenv("CLINE_KEY", "")
        self.cline_model = os.getenv("CLINE_MODEL", "")
        # Seconds; a shared pool-wide ceiling, not a per-provider setting.
        self.timeout = float(os.getenv("AI_TIMEOUT") or 60)
        self._client: httpx.AsyncClient | None = None
        self._client_loop = None

    # -- provider plumbing ---------------------------------------------------

    def client(self) -> httpx.AsyncClient:
        """The shared HTTP client: one pool, one TLS context, reused.

        A client per call meant a new connection pool and handshake for every
        request, and a discussion issues one call per turn (REVIEW P3-9). It is
        kept per *event loop*, not per service: an AsyncClient belongs to the
        loop that built it, and the app's tests build one loop per client — a
        single cached client would be dead on the next one.
        """
        loop = asyncio.get_running_loop()
        if (self._client is None or self._client.is_closed
                or self._client_loop is not loop):
            self._client = httpx.AsyncClient(timeout=self.timeout)
            self._client_loop = loop
        return self._client

    async def aclose(self) -> None:
        """Release the client — on application shutdown, not per request."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
        self._client_loop = None

    def connection(self, provider: str) -> tuple[str, str, str]:
        """(base_url, api_key, model) for a provider. Unknown → AIServiceError."""
        provider = (provider or "ollama").lower()
        if provider not in PROVIDERS:
            raise AIServiceError(f"不支持的AI提供商: {provider}")
        if provider == "cline":
            settings = (
                ("CLINE_BASE_URL", self.cline_base_url),
                ("CLINE_KEY", self.cline_key),
                ("CLINE_MODEL", self.cline_model))
        else:
            settings = (
                ("OLLAMA_BASE_URL", self.base_url),
                ("OLLAMA_API_KEY", self.api_key),
                ("OLLAMA_MODEL", self.model))
        missing = [name for name, value in settings if not value]
        if missing:
            raise AIServiceError(
                f"未配置 {', '.join(missing)}（请在 .env 中设置）")
        (_, base_url), (_, key), (_, model) = settings
        return base_url.rstrip("/"), key, model

    def _messages(self, prompt: str, provider: str,
                  history: list[dict] | None = None) -> list[dict]:
        """System prompt plus either the conversation history or one prompt."""
        messages = [{"role": "system", "content": _system_prompt(provider)}]
        if history:
            messages.extend(history)
        else:
            messages.append({"role": "user", "content": prompt})
        return messages

    async def _call(self, prompt: str, provider: str = "ollama",
                    history: list[dict] | None = None) -> str:
        """One chat completion. Raises AIServiceError, never returns error text."""
        try:
            # `connection()` is inside the try because it is the only raiser of
            # AIServiceError before the request: the old code called it above the
            # try and then caught the error below it, so that handler was dead
            # code (REVIEW P3-9).
            base_url, api_key, model = self.connection(provider)
            response = await self.client().post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": self._messages(prompt, provider, history),
                    "temperature": 0.7,
                },
            )
            response.raise_for_status()
            data = response.json()
            # The Cline API wraps the OpenAI body: {"data": {"choices": …},
            # "success": true}. Ollama answers the bare body.
            if isinstance(data, dict) and "choices" not in data:
                data = data.get("data", data)
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            # The status *and* the provider's own reason: a bare "402 Payment
            # Required" tells the reader nothing they can act on.
            raise AIServiceError(f"AI API调用失败: {_provider_error(exc)}") from exc
        except httpx.HTTPError as exc:
            raise AIServiceError(f"AI API调用失败: {exc}") from exc
        except AIServiceError:
            raise
        except Exception as exc:
            raise AIServiceError(f"AI 处理失败: {exc}") from exc

    # -- the analysis kinds --------------------------------------------------

    async def fact_check(self, text: str, context_before: str = "",
                         context_after: str = "",
                         provider: str = "ollama") -> str:
        """Explain and check the selected text: term, person, event, claim.

        The selection travels inside the sentence it came from, so a pronoun
        without an antecedent in the selection itself is resolved from the
        text around it rather than guessed (REVIEW P1-3).
        """
        body = _excerpt(text, context_before, context_after) or text
        prompt = f"""请核查并解释以下内容（读者正在阅读，只想快速弄清它是什么、对不对）：

{body}

按类型作答，只答最关键的几点：
- 概念/术语：一句话定义，再补一句它在此处的含义
- 人物：身份 + 最重要的一两件事（生卒年可略）
- 事件：时间、经过、影响，各一句
- 地点：位置 + 与此处相关的要点
- 事实/数据陈述：第一句直接下结论——「属实」「不实」「部分属实」「存疑」之一——然后用一两句给出依据或更正

硬性要求：
- 总字数不超过 150 字，最多 4 个要点，每点一行，不分小标题
- 不要开场白、不要复述原文、不要结尾总结或客套话
- 先给结论，再给依据；有错误或争议，直接点明
- 不确定就写「存疑」并说明原因，不要编造来源、年份或数字
- 无法判断时，只用一句话说明还需要什么上下文"""
        return await self._call(prompt, provider=provider)

    async def discuss(self, text: str, context_before: str = "",
                      context_after: str = "",
                      provider: str = "ollama") -> str:
        """A structured, academic discussion of the selected text.

        The excerpt goes in too: "核心论点解析" is about the author's argument,
        which a fragment read on its own does not show (REVIEW P1-3).
        """
        body = _excerpt(text, context_before, context_after) or text
        prompt = f"""请对以下文本进行深入的学术性分析和讨论：

{body}

请从以下几个维度展开分析：

**1. 核心论点解析**
- 作者的主要观点是什么？
- 论证逻辑和结构如何？
- 使用了哪些论证方法（举例、类比、引用等）？

**2. 理论与学术视角**
- 这段文本涉及哪些学术领域或理论框架？
- 与哪些经典理论、学派或学者的观点相关？
- 在学术史或思想史上的位置如何？

**3. 批判性思考**
- 论证是否充分？有无逻辑漏洞？
- 是否存在隐含的假设或前提？
- 可能的反驳观点是什么？

**4. 启发性问题**
- 这段文本引发了哪些值得深入思考的问题？
- 如何将这些观点应用到其他领域或情境？
- 对当代有什么启示意义？

要求：
- 保持学术严谨性，但避免过于晦涩
- 提出具有启发性的问题，引导深入思考
- 如涉及专业术语，简要解释
- 鼓励多角度、批判性的思考"""
        return await self._call(prompt, provider=provider)

    async def discussion_overview(self, text: str, context_before: str = "",
                                  context_after: str = "",
                                  provider: str = "ollama") -> str:
        """The brief opener that seeds an interactive discussion.

        This is the reader's most-used action (深入讨论), and it used to be the
        one that sent the least: the panel did not even put the context on the
        wire, and this method had no parameter to receive it (REVIEW P1-3).
        """
        body = _excerpt(text, context_before, context_after) or text
        prompt = f"""请对以下文本提供一个简要的概览分析（1-2段），突出关键论点、
可能的争议点和值得深入探讨的问题：

{body}

要求：
- 简明扼要，控制在两段以内
- 提出 2-3 个值得讨论的问题
- 语言清晰，便于读者接续提问"""
        return await self._call(prompt, provider=provider)

    async def continue_discussion(self, user_message: str,
                                  conversation_history: list[dict],
                                  provider: str = "ollama") -> str:
        """One turn of an interactive discussion.

        `conversation_history` already ends with the user's message; the
        caller appends the assistant's reply.
        """
        return await self._call(
            prompt=user_message, provider=provider,
            history=list(conversation_history))

    async def summarize_conversation(self, conversation_history: list[dict],
                                     provider: str = "ollama") -> str:
        """Collapse a whole discussion into one comprehensive analysis.

        The transcript is the input — the selection is its first user message —
        so there is no separate `text` parameter: there used to be, and it was
        never read (REVIEW P3-15).
        """
        prompt = """基于我们的整个对话历史，请创建一个综合性的学术分析总结。

请创建综合总结，涵盖以下维度：
**1. 核心论点与观点总结**
**2. 深入分析与见解**
**3. 批判性思考总结**
**4. 结论与启示**

要求：
- 保持学术严谨性
- 基于整个对话历史进行综合
- 突出最有价值的见解
- 结构清晰，层次分明"""
        history = list(conversation_history) + [
            {"role": "user", "content": prompt}]
        return await self._call(prompt=prompt, provider=provider, history=history)
