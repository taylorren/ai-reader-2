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

**Status: P2.** A real book renders from its own files: the reader shell loads
chapters in a sandboxed iframe (render model A — nothing rewritten, nothing
from the book executes), with the book's own typography, a TOC drawer,
prev/next and keyboard navigation. Footnote edges, highlights, AI and progress
come next (P3/P4).
