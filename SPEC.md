# ai-reader-2 — Design Spec

## Goal

A self-hosted EPUB reader with AI-assisted annotation, built on **epubx**. It
renders the book the publisher shipped, and stores nothing about a book that the
book does not already say.

The previous implementation (`ai-reader`, a fork of reader3) converts each EPUB
into a pickle of cleaned HTML plus flattened images, and rebuilds the book on
screen. ai-reader-2 inverts that: **the EPUB is the storage format**, and the
browser renders it.

---

## Relationship to the existing projects

| Project | Role |
|---|---|
| **epubx** | The only EPUB knowledge in the system. A dependency — not vendored, not forked. |
| **ai-reader** | **Reference implementation.** Read freely; inherited in code never. Its schema, AI service, feature set and UI are the requirements document. |
| **reader3** | Predecessor of ai-reader. Its only surviving influence is the UX: one chapter at a time, beside an AI. |

**Carried over as concepts (reimplemented, not copied):** library grouping and
pinyin sorting · word-count and reading-time estimates · three highlight kinds
(fact-check, discussion, comment) · AI fact-check / discussion / summarize /
comment · progress persistence · Markdown sanitisation · provider override ·
Docker and systemd packaging.

**Never carried over:** `reader3.py` · the ebooklib nav monkey-patch ·
`clean_html_content` · `extract_plain_text` · `rewrite_chapter_image_paths` ·
`spine_map` · `_BookUnpickler` · `load_book_cached` · the upload subprocess ·
the client-side link-modal fetch-and-graft.

---

## Principles

1. **The book is the source of truth.** Stored as `books/<slug>/<slug>.epub`.
   No derived artifact is required to render it.
2. **Render, don't re-model.** Book documents are served, never cleaned, never
   rewritten, never re-pathed.
3. **Derived, never persisted — unless recomputable and expensive.** Metadata
   and word count are computed once at upload and stored in SQLite; either can
   be recomputed from the EPUB at any time. Nothing else is stored.
4. **One EPUB dependency.** epubx. No ebooklib, no BeautifulSoup, no pickle.
5. **Annotations anchor to identity, not to strings or pixels.** A block id is
   the primary anchor; selected text is the fallback for pre-existing rows.
6. **Nothing from a book executes.**
7. **Failures are named, not raised.** A book that cannot be read shows
   `book.unsupported`; it never 500s the library.

---

## Scope

**In:** upload and validation · library (list, search, filter, group, complete,
delete) · reader (TOC, prev/next, keyboard) · the book's own files served at
their own paths · footnotes and internal links · highlights · AI panel (local
and cloud Ollama, interactive discussion, summarise) · progress · highlights
view and Markdown export · settings · Docker and systemd packaging.

**Out (deferred, but named):** full-text search inside a book (epubx's
`plain_text` makes this cheap later) · multi-user and auth · annotation sync ·
DRM and image-only books (surfaced through `unsupported`) · vertical CJK ·
mobile apps.

Deferred cases return a named reason. They are never an uncaught exception.

---

## Architecture

### Storage

```
books/<slug>/<slug>.epub      ← the book, and nothing else
reader_data.db                ← annotations and derived metadata
```

No `book.pkl`, no extracted `images/`, no cover copies. Covers are served out of
the book itself.

### Database

Same tables as ai-reader, plus columns that make the model explicit:

```sql
books(slug PK, path, title, author, language, identifier, publisher, date,
      word_count, cover_path, unsupported, added_at)

highlights(id, book_id, chapter_index, chapter_path, block_id,
           selected_text, context_before, context_after, created_at)

ai_analyses(id, highlight_id, analysis_type, prompt, response, created_at)

reading_progress(book_id PK, chapter_index, chapter_path, scroll_percent,
                 anchor, block_id, is_completed, last_read_at)
```

`chapter_index` is **kept as the canonical chapter key** — spine order derives
from the OPF in both systems, so existing highlights, analyses and progress keep
working. `chapter_path` and `block_id` are added, not substituted.

### Book identity

The slug algorithm is copied from ai-reader verbatim (title → safe name, `_2`,
`_3`… on collision), so a re-uploaded book keeps its `book_id` and therefore its
annotations.

### Routes

| Route | Purpose |
|---|---|
| `GET /` | Library, from SQLite — no EPUB parsing |
| `POST /upload` | Save, validate via `open_book`, extract metadata, insert row |
| `DELETE /delete/{slug}` | Remove the book folder, keep annotations |
| `GET /read/{slug}/{chapter_index}` | Reader shell |
| `GET /book/{slug}/{path:path}` | **`book.resource(path)` — the book's own bytes and media type** |
| `GET /api/book/{slug}` | spine + toc + metadata as JSON |
| `GET /api/footnotes/{slug}/{chapter_index}` | resolved footnote edges |
| `GET /api/text/{slug}/{chapter_index}` | `plain_text` — AI context, counts |
| `POST /api/highlight`, `GET /api/highlights/{slug}/{index}`, `DELETE /api/highlight/{id}` | Highlights |
| `GET /highlights/{slug}` | Highlights view and export |
| `POST /api/ai/analyze \| save \| discussion/start \| discussion/continue \| discussion/summarize`, `PUT /api/ai/update/{id}`, `DELETE /api/ai/delete/{id}` | AI |
| `GET/POST /api/settings`, `POST /api/progress`, `POST /api/books/{slug}/completion` | Settings, progress, completion |

### The rendering contract

**Invariant, whichever model is chosen:** the book's files are served at their
own paths by `/book/{slug}/{path}`; the reader rewrites nothing. XHTML goes out
as `text/html` — the consumer is a browser — and everything else carries its
declared media type.

Three models, to be decided before P2:

- **A. iframe** — the book's document, its CSS, its fonts, sandboxed. Native
  in-book links and footnotes. Costs: highlights and AI selection move into
  `iframe.contentDocument`; MathJax cannot run in a script-less frame; the
  book's CSS owns dark mode.
- **B. `<base href>` graft** — fetch the book's XHTML into the reader's DOM with
  `<base href="/book/<slug>/<dir>/">`. Keeps every existing highlight and AI
  routine; costs the book's typography, since book CSS and scripts must be
  stripped. This is today's behaviour, made non-destructive.
- **C. Hybrid** — iframe for pixels, epubx blocks and ids for anchors. Most
  faithful, most work.

**Recommendation: B to land it, A as the target**, behind a per-book flag if
both are ever needed. This is the single decision the spec leaves open.

### Caching and concurrency

An LRU of at most 8 open `Book` objects, `close()` on eviction — an open book
holds a file handle. First parse of a chapter is CPU-bound lxml work and is
dispatched through a threadpool under FastAPI. `lru_cache` is *not* used for
books: handles are not immutable.

---

## Robustness rules

Inherited from epubx, re-verified here:

| Case | Response |
|---|---|
| DRM, image-only, no OPF | `unsupported` reason on the book card; not an error |
| BOM'd XHTML, EPUB 2 labelled 1.0, NCX-only nav | handled by epubx; the reader never sees it |
| Book with no CSS at all | renders in the reader's default typography — model A must not depend on book CSS |
| Book with hostile CSS | contained by the iframe in model A |
| Book containing `<script>` | blocked by the sandbox |
| Footnote hrefs epubx cannot classify (*On China*: 0 edges) | the book's own link still works — the reader follows it natively |
| Path traversal in `/book/{slug}/{path}` | normalised by epubx; rejected, and tested |

---

## Technology

**Python ≥ 3.10** · FastAPI · uvicorn · Jinja2 · **epubx** · httpx · pypinyin ·
markdown-it-py · bleach · python-multipart.

**Dropped from ai-reader:** ebooklib, beautifulsoup4, and pickle.

**Frontend unchanged in kind:** Jinja + Vue 3 + marked + DOMPurify — the
published bundles are vendored in `static/vendor/` (see its README), so there
is no runtime CDN dependency, no build step and no `node_modules`.

**Dependency mechanics (decide early).** epubx as a path dependency
(`epubx @ file:///Users/tr/projects/epubx`) works locally but breaks
`docker build`, which cannot see outside its context. Options: a git dependency
on a tag, publishing to PyPI, or building with the parent directory as context.
Recommendation: **git dependency on a tag** once epubx is tagged.

---

## File layout

```
ai-reader-2/
├── SPEC.md               # this document
├── pyproject.toml        # deps; epubx is the only EPUB dependency
├── server.py             # FastAPI app, router registration, .env loading
├── booksource.py         # THE ADAPTER: the only module that imports epubx
├── database.py           # SQLite: books, highlights, ai_analyses, progress
├── ai_service.py         # Ollama client (local/cloud), unchanged in spirit
├── routers/
│   ├── __init__.py       # shared deps, book cache, slug/word-count helpers
│   ├── library.py        # library view, upload, delete
│   ├── reader.py         # reader shell, /book/{slug}/{path}, chapter APIs
│   ├── highlights.py     # highlight CRUD, highlights view, export
│   ├── ai.py             # analyse, save, discussion, summarize
│   └── settings.py       # provider override, progress, completion
├── templates/            # library.html, reader.html, highlights.html
├── static/               # css + js (reader, library, highlights, panel) + vendor/
├── books/                # <slug>/<slug>.epub — the books themselves
└── tests/                # synthetic fixtures; corpus tests skip when absent
```

`booksource.py` is deliberately the only file that knows epubx exists. If the
adapter is right, replacing epubx later touches one module.

---

## Milestones

| Phase | Deliverable | Acceptance |
|---|---|---|
| **P0** | `booksource.py` over epubx; `Chapter.footnotes()` added to epubx | Adapter passes against the 299-book corpus; edges match `tools/serve.py` |
| **P1** | Storage, upload, library from SQLite | Upload → listed → metadata, in one step, no subprocess; re-upload preserves `book_id` |
| **P2** | Rendering, TOC, prev/next | A real book renders from its own files — no image rewriting, no `spine_map`, no `DOMParser` grafting |
| **P3** | Footnotes from edges | A footnote opens without fetching a rendered page |
| **P4** | Highlights, AI, progress on the new DOM | Create/edit/delete a highlight, run an analysis, resume position — all survive restart |
| **P5** | Delete the old world; docs, Docker, systemd | Zero `book.pkl` anywhere; no ebooklib or bs4 in `pyproject.toml` |

Each phase is independently shippable and verifiable.

---

## Testing

- **Synthetic fixtures** for routes, database and AI (AI mocked), mirroring
  epubx's `tests/fixtures.py` approach, so CI runs with no books present.
- **Corpus tests** via `EPUBX_CORPUS` for the adapter, skipping cleanly when the
  corpus is absent.
- **Real-book smoke**, four books chosen for the known hard cases: *On China*
  (footnote hrefs epubx does not classify — proves the book's own links still
  work), *Zhe Ben Shu Jiao Shi Yao* (77 of 79 edges resolved), a Ni Kuang novel
  (the loose-text book that motivated the epubx bug fix), and a CSS-heavy book
  (proves the book's typography survives).

---

## Migration from ai-reader

1. **Books must be re-uploaded.** ai-reader discarded the EPUB and kept only the
   pickle; nothing can be recovered from it.
2. A helper script lists the old `books/*_data/` slugs so they can be matched on
   re-upload.
3. Because the slug algorithm is copied and `chapter_index` is retained,
   re-uploading the same book restores highlights, analyses and progress with no
   data migration.
4. New columns are added with the same idempotent `ALTER TABLE` pattern
   ai-reader already uses.

---

## Success criteria

1. Upload → readable in one step, with no subprocess and no timeout.
2. Rendering a chapter rewrites nothing: no image paths, no href mapping, no
   HTML cleaning.
3. A footnote opens without fetching a full rendered page.
4. A book with its own CSS renders in the publisher's typography (model A),
   verified on a real book.
5. Highlights survive a re-upload of the same book.
6. Zero `.pkl` files and zero pickle code in the tree; no ebooklib, no
   BeautifulSoup.
7. Every book in the 299-book corpus either opens or reports a named
   `unsupported` reason.

---

## Honest coverage statement

The rendering model is **undecided** (A/B/C above); the spec is written so that
only `reader.html` and `reader.js` change when it is settled. MathJax under a
script-less sandbox is a **known unresolved trade-off**, not a solved one. Dark
mode versus a book's own CSS is likewise open. Search inside a book is deferred
despite being cheap — named rather than implied.

---

## Deliberate non-goals

**No `reader3.py`.** Not ported, not vendored. Its five responsibilities are now
epubx (parsing), the filesystem (storage), `book.resource()` (images),
`/api/footnotes` (links), and the browser (rendering).

**No pickle, ever.** Beyond being unnecessary, unpickling a file from disk is
code execution — and ai-reader's custom unpickler existed only to patch that.

**No HTML cleaning on the serving path.** Sanitising stays where it belongs: on
AI output (`bleach`) and user comments — never on the book.

**No in-place rewrite of ai-reader.** It is a reference, and it keeps working
while ai-reader-2 is built beside it.
