# ai-reader-2

A self-hosted EPUB reader with AI-assisted annotation, built on
[epubx](https://pypi.org/project/epub-extended/). It renders the book the publisher shipped, and stores nothing
about a book that the book does not already say.

**The EPUB format is epubx's job.** reader3's parser (`reader3.py`) and
ebooklib — what `ai-reader` read books with, and what the 1.0.0 image ships —
are not vendored, not forked and not imported here: `booksource.py` is the only
module that knows epubx exists, and epubx is the only EPUB dependency.

**Design: [SPEC.md](SPEC.md). Pitfalls: [PITFALLS.md](PITFALLS.md)** — the bugs
that only the deployment produced, and the test that pins each one. The previous
implementation, `ai-reader`, is a reference for features and schema — not an
ancestor in code.

```bash
uv sync
uv run server.py      # http://127.0.0.1:8123
uv run pytest -q
```

`pytest` also runs the front end's pure logic: `tests/js/*.test.js` under Node's
own test runner — no npm, no build step, no jsdom — and skips them cleanly when
`node` is not installed. `node --test "tests/js/*.test.js"` runs them directly.

`tests/test_browser.py` drives the app in a real browser (Playwright) for the
things a stub DOM cannot see: a toast's *computed* opacity, a saved mark painted
into the book's own document, a book's own `<script>` not running, a mark on the
second of two identical sentences, one selection saved twice (and a mark that
straddles an inline element), the reading position's block anchor, a contents
entry for a section its book gave no id (the jump, and the sidebar highlight
that follows it), and the two Vue pages' own interactions (the letter index, the
stats bar). They skip cleanly unless a browser is present:

```bash
uv run playwright install chromium     # ~130 MB, once
```

Static assets are read from disk on every request, but Python is loaded once at
startup: after editing a router or a model, restart the server
(`systemctl restart reader3`). A running process serving the new `panel.js`
against the old request model rejects every save with a 422.

**Status: P4.** A real book renders from its own files: the reader shell loads
chapters in a sandboxed iframe (render model A — nothing rewritten, nothing
from the book executes), with the book's own typography, a TOC drawer whose
entries jump to the section they name — in a book whose headings carry no `id`
too, where the label is what locates the heading — prev/next and keyboard
navigation. Footnotes open from the library's edges
without fetching a rendered page. Highlights, AI analysis and reading progress
now live on that DOM: select text to explain it (解释说明), discuss it
(深入讨论) or write a note (个人笔记); each becomes a highlight anchored to the
library's block id, and its AI response is stored as Markdown. The same menu
copies the selection (复制文本) — on plain http too, where a browser has no
Clipboard API. Which AI answers is a choice in the bar itself (本地 / 云端),
not inside the panel: the panel is closed until a selection opens it, and that
is a setting a reader wants to see first. `/highlights/{slug}`
lists everything and exports it as Markdown; `/api/settings` switches between
local and cloud Ollama (the bar's toggle is that setting). **Formulas display,
whatever the book ships**: its own MathML and its images render natively, and the
shell converts a book's LaTeX to MathML itself with a vendored Temml (fetched
only for a chapter that has formulas) — so a formula stays selectable text, and
复制文本 copies the LaTeX the book wrote rather than the characters it drew. The
sandbox stays shut, and the book's own scripts still never run. All of it
survives a restart. **Docker packaging has
landed** (P5, in part — see below, and the image it publishes); systemd
packaging and the old world's removal come next.

The AI panel talks to an OpenAI-compatible Ollama endpoint; copy `.env.example`
to `.env` and set `OLLAMA_BASE_URL` / `OLLAMA_MODEL` (and `OLLAMA_CLOUD_MODEL`
for the cloud provider). Without it the reader works; the AI panel reports a
named error.

## Docker

The published image is **`taylorren/epub-ai-reader`**. Tag `2.0.0` is this app;
tag `1.0.0` was built from `ai-reader`, whose books volume holds
`<slug>_data/book.pkl` folders that nothing here reads.

```bash
# Build for this machine
docker build -t taylorren/epub-ai-reader:2.0.0 .

# Or both platforms straight to Docker Hub (needs a buildx builder with arm64)
docker buildx build --platform linux/amd64,linux/arm64 \
  -t taylorren/epub-ai-reader:2.0.0 -t taylorren/epub-ai-reader:latest --push .
```

`compose.yaml` is the same run as a file — `docker compose up -d`. The one-liner:

```bash
docker run -d --name epub-ai-reader -p 8123:8123 \
  -v "$(pwd)/books:/app/books" -v "$(pwd)/data:/data" \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434/v1 \
  taylorren/epub-ai-reader:2.0.0
```

| Container path | Contents | Environment |
|---|---|---|
| `/app/books` | `books/<slug>/<slug>.epub` — the library, and the only copy of it | — |
| `/data` | `reader_data.db` and its `-wal`/`-shm` companions — highlights, analyses, progress | `READER_DB` |

The container keeps the interface the 1.0.0 image had — port **8123**, uid
**1000**, `/app/books`, `/data`, the same `READER_*` and `OLLAMA_*` variables —
so an existing deployment directory keeps working. `READER_DB` is set in the
image (default `/data/reader_data.db`), so the database cannot land inside the
image and be lost on a rebuild. Both mounts must be writable by uid 1000.

**Coming from the 1.0.0 image, two things change:**

* **Books are re-uploaded.** ai-reader-2 lists the library from SQLite and keeps
  the EPUB itself; the old volume's `<slug>_data/book.pkl` folders are ignored.
  Uploading the same book restores its highlights, analyses and progress,
  because the slug is unchanged (SPEC.md, "Migration from ai-reader").
* **The database carries over — keep `./data` as it is.** The old
  `reader_data.db` holds `highlights`, `ai_analyses` and `reading_progress`,
  all keyed by slug and chapter; ai-reader-2 adds its own `books` table beside
  them and fills it as books are re-uploaded. It drops the `anchor` column
  nothing reads. Copy the file aside first if you want a rollback — the app is
  the only thing that writes to it.

AI configuration is environment, not a baked `.env` (`OLLAMA_BASE_URL`,
`OLLAMA_API_KEY`, `OLLAMA_MODEL`, `OLLAMA_CLOUD_MODEL`,
`OLLAMA_DEFAULT_PROVIDER`) — or mount one read-only:
`-v ./.env:/app/.env:ro`. Every one is optional; the reader works without AI.

## License

MIT — see [LICENSE](LICENSE). ai-reader-2 shares no code with `reader3` or with
its earlier implementation `ai-reader`: it reimplements the same idea on
[epubx](https://github.com/taylorren/epubx) — no `reader3.py`, no ebooklib —
which is where all knowledge of the EPUB format lives.


