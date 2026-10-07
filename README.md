# ai-reader-2

A self-hosted EPUB reader with AI-assisted annotation, built on
[epubx](../epubx). It renders the book the publisher shipped, and stores nothing
about a book that the book does not already say.

**Design: [SPEC.md](SPEC.md).** The previous implementation, `ai-reader`, is a
reference for features and schema — not an ancestor in code.

```bash
uv sync
uv run server.py      # http://127.0.0.1:8123
uv run pytest -q
```

**Status: P4.** A real book renders from its own files: the reader shell loads
chapters in a sandboxed iframe (render model A — nothing rewritten, nothing
from the book executes), with the book's own typography, a TOC drawer,
prev/next and keyboard navigation. Footnotes open from the library's edges
without fetching a rendered page. Highlights, AI analysis and reading progress
now live on that DOM: select text to explain it (解释说明), discuss it
(深入讨论) or write a note (个人笔记); each becomes a highlight anchored to the
library's block id, and its AI response is stored as Markdown. `/highlights/{slug}`
lists everything and exports it as Markdown; `/api/settings` switches between
local and cloud Ollama. All of it survives a restart. Packaging and the old
world's removal come next (P5).

The AI panel talks to an OpenAI-compatible Ollama endpoint; copy `.env.example`
to `.env` and set `OLLAMA_BASE_URL` / `OLLAMA_MODEL` (and `OLLAMA_CLOUD_MODEL`
for the cloud provider). Without it the reader works; the AI panel reports a
named error.

