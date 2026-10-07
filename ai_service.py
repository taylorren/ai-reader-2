"""The Ollama client: local and cloud, one OpenAI-compatible surface.

Reimplemented from ai-reader's service (its behaviour is the requirement),
not copied. Two providers share one endpoint shape; only the model and the
key differ. Failures raise `AIServiceError` — a route maps that to 502, so
an AI failure is never a 200 carrying error text.

Every call is async httpx: the FastAPI routes that await it are async too.
Prompts ask for Simplified Chinese, matching the reference's output contract.
"""

from __future__ import annotations

import os

import httpx


class AIServiceError(Exception):
    """An AI call failed — network, HTTP status, or unreadable response."""


PROVIDERS = ("ollama", "ollama_cloud")


def _system_prompt(provider: str) -> str:
    """The Chinese-output contract the reference app enforces per provider."""
    if provider == "ollama":
        return (
            "你是中文阅读助手。必须仅使用简体中文回答。"
            "不要输出英文句子，不要输出英文小标题；如需术语请给出中文解释。"
        )
    return "请使用简体中文回答，保持表达清晰、准确。"


class AIService:
    """Fact-check, discussion and summarising against an Ollama endpoint."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.base_url = base_url or os.getenv(
            "OLLAMA_BASE_URL", "http://localhost:11434/v1")
        self.api_key = api_key or os.getenv("OLLAMA_API_KEY", "ollama")
        self.model = os.getenv("OLLAMA_MODEL", "llama3")
        self.cloud_model = os.getenv("OLLAMA_CLOUD_MODEL", "gpt-oss:120b-cloud")

    # -- provider plumbing ---------------------------------------------------

    def connection(self, provider: str) -> tuple[str, str, str]:
        """(base_url, api_key, model) for a provider. Unknown → AIServiceError."""
        provider = (provider or "ollama").lower()
        if provider not in PROVIDERS:
            raise AIServiceError(f"不支持的AI提供商: {provider}")
        model = self.cloud_model if provider == "ollama_cloud" else self.model
        return self.base_url, self.api_key, model

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
        base_url, api_key, model = self.connection(provider)
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(
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
                return data["choices"][0]["message"]["content"]
            except httpx.HTTPError as exc:
                raise AIServiceError(f"AI API调用失败: {exc}") from exc
            except AIServiceError:
                raise
            except Exception as exc:
                raise AIServiceError(f"AI 处理失败: {exc}") from exc

    # -- the analysis kinds --------------------------------------------------

    async def fact_check(self, text: str, context: str = "",
                         provider: str = "ollama") -> str:
        """Explain and check the selected text: term, person, event, claim."""
        prompt = f"""请帮我理解以下内容：

{text}

请根据内容类型提供相应的解释：

**如果是专有名词/概念**：给出清晰的定义和解释
**如果是人物**：介绍其身份、背景和重要性
**如果是历史事件**：说明事件经过、时间、影响
**如果是地点**：介绍其地理位置、特点、相关背景
**如果是数据/事实陈述**：验证准确性，提供来源或背景

要求：
- 简洁明了，重点突出
- 如有错误或争议，明确指出
- 如果内容不完整或无法判断，说明需要更多上下文"""
        return await self._call(prompt, provider=provider)

    async def discuss(self, text: str, context: str = "",
                      provider: str = "ollama") -> str:
        """A structured, academic discussion of the selected text."""
        prompt = f"""请对以下文本进行深入的学术性分析和讨论：

{text}

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

    async def discussion_overview(self, text: str,
                                  provider: str = "ollama") -> str:
        """The brief opener that seeds an interactive discussion."""
        prompt = f"""请对以下文本提供一个简要的概览分析（1-2段），突出关键论点、
可能的争议点和值得深入探讨的问题：

{text}

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

    async def summarize_conversation(self, text: str,
                                     conversation_history: list[dict],
                                     provider: str = "ollama") -> str:
        """Collapse a whole discussion into one comprehensive analysis."""
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
