# ai-reader-2 — Code Review

| | |
|---|---|
| **Commit reviewed** | `8c5102c` (main) — "Reader: a highlight is stored only with its content; Library: whole-book progress" |
| **Review date** | 2026-10-21 |
| **Scope** | Every Python module, template, JS and CSS file in the repo; the test suite; the live `reader_data.db`. |
| **Explicitly out of scope** | Multi-user, authentication, authorisation, annotation sync, per-user settings, CSRF as a multi-tenant concern. The in-memory global provider override, the shared database and the absence of origin checks are treated as intended single-user design. |

## Verification performed

```bash
.venv/bin/pytest -q          # 109 passed, 3 skipped in 77.11s  (3 skips = EPUBX_CORPUS unset)
sqlite3 reader_data.db       # PRAGMA integrity_check -> ok
                             # books 4 | highlights 17 | ai_analyses 16 | reading_progress 2
python -c "ast.parse(...)"    # AST pass over every module: no unused imports but `__future__`
```

Two findings (P1-1, P1-2) were **reproduced end-to-end**, not just read from the code; the
recipes are in Appendix A.

## How to use this file

* Each item has a stable ID (`P1-1` … `P3-15`, `T1` … `T5`) and a triage line:
  `Review: ☐ accept ☐ defer ☐ reject`.
* What each mark means on my side:
  * **accept** — I implement it in the next pass, and the check named in the item's
    **Verify** line (plus the linked test gap, where there is one) lands with it.
  * **defer** — the item stays documented here; no code change now, and I re-raise it only if
    a later change touches that code.
  * **reject** — I delete the item from this file, so it does not resurface as a "finding" in
    the next review. No code change.
  * **left blank** — undecided; I leave both the item and the code alone.
* You can tick the lines in this file, or answer in chat, e.g.
  `Accept: P1-1 P1-2 P1-3` · `Defer: P2-5 P2-10` · `Reject: P3-11`.
* IDs are stable, so `Ctrl+F` / `Cmd+F` on an ID (e.g. `P2-8`) jumps straight to the item, the
  same way in any editor or on the web. Cross-references in the text use bare IDs for that
  reason.
* **Severity** — `High` = user-visible breakage or a security boundary; `Medium` = wrong
  behaviour in a real scenario, or cost that grows with the library; `Low` = polish, docs,
  or a latent trap.
* **Effort** — `S` < 15 min · `M` ≈ 1 h · `L` ≥ half a day.
* A `✔ applied` marker in the index means the item has been accepted **and implemented** in the
  working tree; the item itself records what landed and the check that pins it. Items without
  the marker are still findings only — the tree is unchanged for them.

## Index

| ID | Sev | Area | Title | Effort |
|---|---|---|---|---|
| P1-1 | High | Front-end | Every toast notification is invisible ✔ applied | S |
| P1-2 | High | Routing / slugs | Titles containing `#` (or `%`) break every link to the book ✔ applied | S |
| P1-3 | Medium | AI | The AI gets the selection but never the surrounding context ✔ applied | S |
| P1-4 | High | Front-end | Editing a note flattens it to one line ✔ applied | M |
| P1-5 | High | A11y | Keyboard readers lose chapter nav and cannot create highlights ✔ applied | M |
| P1-6 | High | Reading state | Following an in-book link never saves progress ✔ applied | S |
| P2-1 | High | Security | Book files are served at the app origin with no CSP ✔ applied | S |
| P2-2 | Medium | Performance | The library page is N+1 ✔ applied | S |
| P2-3 | Medium | Performance | No caching headers on `/book/**` ✔ applied | S |
| P2-4 | Medium | Metadata | CJK word count double counts ✔ applied | S |
| P2-5 | Medium | Concurrency | The book cache can close a book another request is using | M |
| P2-6 | Medium | Concurrency | `get_db()` is not thread-safe ✔ applied | S |
| P2-7 | Medium | Config | `.env` overrides the real environment ✔ applied | S |
| P2-8 | Medium | Reading state | Progress writes can lose to older writes | M |
| P2-9 | Medium | API | `/api/text` ships the chapter twice and mislabels the count ✔ applied | S |
| P2-10 | Medium | Data model | Anchor data is stored that is never used | M |
| P2-11 | Medium | API | `analysis_type` is validated on one endpoint, not the other ✔ applied | S |
| P2-12 | Medium | Storage | SQLite tuning and connection boilerplate | S |
| P3-1 | Low | Front-end | Panel save label leaks across modes ✔ applied | S |
| P3-2 | Low | Front-end | The 编辑 button in the reader panel is unstyled ✔ applied | S |
| P3-3 | Low | Export | Markdown export breaks multi-paragraph quotes | S |
| P3-4 | Low | A11y | `<html lang="en">` on a Chinese UI | S |
| P3-5 | Low | Robustness | Stale `unsupported`, derived from the database row ✔ applied | S |
| P3-6 | Low | Routing | `read_redirect` can compute `chapter_index = -1` ✔ applied | S |
| P3-7 | Low | Docs | Docstrings and SPEC that contradict the code | S |
| P3-8 | Low | Dependencies | `httpx2` is a runtime dependency for a test-only need | S |
| P3-9 | Low | AI | AI client is created per call; one `except` is unreachable | S |
| P3-10 | Low | Operations | No upload size cap and no staging-directory sweep | S |
| P3-11 | Low | UX | The unsupported reason is only a tooltip | S |
| P3-12 | Low | UX | Deleting a card leaves an empty pill and stale stats | S |
| P3-13 | Low | Security | Markdown rendering fails open if DOMPurify is absent | S |
| P3-14 | Low | Architecture | `routers/__init__.py` is a grab-bag | M |
| P3-15 | Low | API | Dead API and schema surface | S |
| T1 | High | Testing | No front-end tests ✔ applied (browser smoke still open) | L |
| T2 | Medium | Testing | No fixture with a URL-hostile title ✔ applied | S |
| T3 | Medium | Testing | No tests on prompt content or save validation ✔ applied | S |
| T4 | Low | Testing | No cost test for the library render ✔ applied | S |
| T5 | Low | Testing | No test pins response headers ✔ applied | S |

**Counts:** 38 items — 7 High · 14 Medium · 17 Low — plus 5 test gaps (T1–T5).

---

## P1 — User-visible defects

*(P1-3 is rated Medium: the reading workflow completes, so it sits here for grouping — the
AI-panel items belong together — rather than for severity.)*

### P1-1 · Every toast notification is invisible ✔ applied

**Severity:** High · **Effort:** S · **Area:** Front-end feedback
**Review:** ☑ accept ☐ defer ☐ reject

**Where:** `static/js/panel.js:66-72`, `static/css/reader.css:610-624`

**Evidence:** `toast()` assigns `className = "toast visible"`, but no stylesheet in the repo
defines `.toast.visible` (`grep -rn "visible" static/css/` returns nothing), and `.toast` is
`opacity: 0; pointer-events: none`.

**Impact:** Every message the reader shows through `toast()` is silent:

* "已保存到数据库", "已删除", "已更新", "已复制到剪贴板";
* all AI failures (`toast(error.message, "error")` at `panel.js:493, 518, 570, 584, 602`);
* "AI 正在思考中，请稍候…" — so clicking × during a long call *appears* to do nothing;
* "本章有 N 条高亮未能定位" — the named-failure promise of the highlight engine;
* provider-switch failures and discussion length warnings.

**Fix:**

```css
/* static/css/reader.css, after .toast */
.toast.visible { opacity: 1; transform: translateX(-50%) translateY(0); }
.toast.error   { background: rgba(150, 40, 40, 0.95); }
```

**Verify:** stop the server, click 保存, and watch the bottom centre; add the class/CSS guard
test suggested in T1.

**Applied (2026-10-23, `static/css/reader.css` + `tests/test_reader.py`):**

* `static/css/reader.css` — the two rules above, after `.toast`, with a comment naming the
  failure they fix (the `.toast` block keeps `opacity: 0`; `.toast.visible` is what raises it).
  The `.toast.error` rule gives a failed save / AI call its own colour instead of the neutral
  grey, so "已保存到数据库" and `toast(error.message, "error")` no longer look alike.
* `tests/test_reader.py::test_every_toast_class_has_a_rule_in_reader_css` — T1's first
  recommendation, **scoped to the toast**: it extracts the class literals `toast()` assigns
  from `panel.js`, plus the quoted `kind` at every `toast(msg, "error")` call site, and asserts
  each one has a rule in the served `reader.css`. It asserts the extraction still finds
  `toast`/`visible` so it cannot pass vacuously. Confirmed to fail against the pre-fix
  stylesheet (`missing = ['error', 'visible']`) and pass now.
  The guard is deliberately not the blanket version T1 sketches: `reader-highlight` / `hl-*` are
  painted into the frame (which loads no shell stylesheet) and `.action-link` belongs to
  `highlights.css` (P3-2), so a blanket check would fail on unrelated, deliberate cases.
  T1 as a whole — the remaining class guard, the JS module extraction and the Playwright smoke —
  stays open.

---

### P1-2 · Titles containing `#` (or `%`) break every link to the book (verified) ✔ applied

**Severity:** High · **Effort:** S · **Area:** Routing / slugs
**Review:** ☑ accept ☐ defer ☐ reject

**Where:** `routers/__init__.py:117` (`_INVALID_FILENAME_CHARS = '<>:"/\\|?*'`),
`templates/library.html:53, 87, 92`, `templates/highlights.html:16, 34, 51`.

**Evidence:** The slug is the title verbatim (`sanitize_folder_name`). `#` and `%` are not in
`_INVALID_FILENAME_CHARS`, and `library.html` emits the slug **unquoted** into hrefs.
Reproduced with a fixture titled `C# Fixture12`:

```
upload 200   slug = 'C# Fixture12'
card hrefs   href="/read/C# Fixture12"        href="/highlights/C# Fixture12"
GET /read/C%23%20Fixture12          -> 307   (correct encoding works)
GET /read/C   (what the browser asks) -> 404
GET /highlights/C (what the browser asks) -> 404
```

`highlights.html` already quotes (`| urlencode`), so the codebase is simply inconsistent.

**Impact:** A book whose title contains `#` (e.g. *C# in Depth*) uploads successfully and is
then unreachable from its own card — cover link, 浏览本书 and 高亮与批注 all 404. `%` is a
second latent case (invalid escape in the request target).

**Fix (both halves):**

```python
# routers/__init__.py
_INVALID_FILENAME_CHARS = '<>:"/\\|?*#%'
```

```jinja
{# library.html — every occurrence #}
href="/read/{{ book.slug | urlencode }}"
href="/highlights/{{ book.slug | urlencode }}"
```

Quoting alone still leaves `%` in folder names; sanitising alone still leaves `#` in any
future unquoted href. Do both.

**Verify:** new fixture title with `#`; assert the rendered card hrefs contain `%23` and that
`client.get(href)` is 200/307. See T2.

**Applied (2026-10-23, `routers/` + `templates/` + `tests/`):** both halves, plus a third site
the **Where** list above missed.

* `routers/__init__.py` — `_INVALID_FILENAME_CHARS = '<>:"/\\|?*#%'`, with the docstring and a
  comment naming why a URL-hostile character belongs in a *filename* sanitiser (the slug is what
  lands in hrefs). Pinned by
  `tests/test_helpers.py::test_sanitize_slugs_out_the_characters_a_url_cannot_carry`.
* `templates/library.html:53, 87, 92` and `templates/reader.html:92` (the panel's 全部高亮 ↗) —
  `{{ … | urlencode }}`, matching what `highlights.html` already did. `reader.html` was not in
  the finding's list either.
* **`routers/reader.py:101` (`read_redirect`) — the third site, and the one that made the fix
  actually work.** It built its `Location` from the raw slug, and Starlette does not escape `#`
  (it escapes non-ASCII for you, which is why a Chinese title never showed this). Measured
  before the fix, with a legacy `C# in Depth` row:
  `GET /read/C%23%20in%20Depth -> 307, Location: '/read/C#%20in%20Depth/0'` — the browser reads
  `#%20in%20Depth/0` as a fragment, asks for `/read/C` and gets 404. Quoting the card href alone
  would not have fixed the journey. Now `Location: '/read/C%23%20in%20Depth/0'` → 200.
* `tests/fixtures.py` — `write_epub(path, title=…)` (T2's fix; the title is XML-escaped, so `&`
  and `<` are safe to pass).
* `tests/test_library.py` — two tests and a `book_links()` helper. One pins the sanitise half
  (`C# in Depth` → `C_ in Depth`, `100% Pure` → `100_ Pure`, every card link resolves); the other
  pins the quoting half on the case the sanitise half cannot reach — a row **already stored**
  with a hostile slug, uploaded through the pre-fix rule with `monkeypatch` — and asserts
  `%23` hrefs, the quoted `Location`, and that card → shell → highlights all reach the book.
  Both were confirmed to fail with the app-side change reverted.
* Also confirmed unaffected: a CJK title (`三体`) still resumes (`Location:
  '/read/%E4%B8%89%E4%BD%93/0'` → 200), and its hrefs are now explicitly percent-encoded rather
  than relying on the browser to encode a raw UTF-8 path on navigation.

**Known consequence (one-time, narrow).** Sanitising changes the slug of a title containing
`#`/`%`, so an *already stored* such book keeps its old slug and folder (and now works, via
quoting), but **re-uploading** it derives the sanitised slug, finds no row under it, and lands as
a second book instead of replacing in place — its annotations would not reattach. Only titles
containing `#` or `%` are affected, and only for uploads made before this change. The trade-off
table below is updated to record it, and `SPEC.md`'s "Book identity" and "Migration" sections —
which claimed the algorithm was copied *verbatim* — are amended, since this change is what makes
that claim false for those titles.

---

### P1-3 · The AI gets the selection but never the surrounding context ✔ applied

**Severity:** Medium · **Effort:** S · **Area:** AI
*(rated High in the first pass; lowered after the reader's challenge and the A/B below showed the
workflow completes — what is inert is the feature, not the reading experience)*
**Review:** ☑ accept ☐ defer ☐ reject

**Where:** `ai_service.py:96-115` (`fact_check`), `:117-151` (`discuss`), `:153-165`
(`discussion_overview`); `routers/ai.py:124-128, 164-165`; `static/js/panel.js:394, 433-437`;
`static/js/panel.js:305-307` (where the context is cut).

**Evidence — three independent checks.**

**(1) The selection does reach the model.** That is why the answer looks related to the text:
the panel's request carries `selected_text` and every prompt interpolates it
(`ai_service.py:101, 122, 159`). The reader's own observation is correct — and it is a
different field from the one in this finding.

**(2) The context does not reach it.** Captured prompts, with unique markers in each field and
`_call` stubbed so the prompt text can be inspected directly:

| path | selection in prompt | context in prompt |
|---|---|---|
| `POST /api/ai/analyze` (`fact_check`) | yes | **no** |
| `POST /api/ai/analyze` (`discussion`) | yes | **no** |
| `POST /api/ai/discussion/start`, `context` sent | yes | **no** |
| `POST /api/ai/discussion/start`, exactly as the panel sends it | yes | **no** — the field is not sent at all |

`context: str = ""` is accepted by all three service methods and never interpolated.

**(3) It changes the answer.** Same book (自由的窄廊, ch. 3), same model (`gpt-oss:120b-cloud`,
the panel's default provider), byte-identical instructions — the only difference is a context
block. Selection: 「他們偏好制度分析，比較富裕民主國家和絕大多數貧困充斥的絕望國家之異同。」

* *Current code:* treats the sentence as a standalone claim about "研究者" — it **guesses** the
  referent of 他們 — and reads it as the book's thesis.
* *With context* (上文 names the book and its predecessor 《國家為什麼會失敗》): correctly places
  it as the authors' own method, not the book's conclusion.

**Impact:** the answer is on-topic, so nothing *looks* broken — but a short or pronoun-first
selection is answered blind: 他們 / 该党 / 因此 resolve to a guess. Two books on this shelf
routinely yield such selections. Rated Medium rather than High for that reason: the workflow
completes; the feature that was designed, wired and shipped is inert. `AnalyzeRequest.highlight_id`
(`ai.py:37`) is likewise accepted and ignored.

**Two extra facts found while verifying** (both belong to the fix, not to separate items):

* 深入讨论 goes to `/api/ai/discussion/start`, whose panel payload omits `context` entirely
  (`panel.js:433-437`) even though `DiscussionStartRequest.context` exists — so for the reader's
  most-used action the context is not even put on the wire.
* `computeSelection` stores two *separate* slices with the selection cut out of the middle
  (`context_before` = the 60 chars before it, `context_after` = the 60 after), and the panel
  concatenates them (`panel.js:394`). Interpolating that string as-is would hand the model a
  seam with a hole where the quoted text belongs — so the fix must send the halves separately,
  or a contiguous excerpt with the selection marked inside it.

**Fix:** give the three methods a bounded, labelled excerpt and send the halves, e.g.

```python
def _excerpt(selected: str, before: str, after: str, span: int = 300) -> str:
    """The selection with its surroundings, labelled — never the bare concatenation."""
    if not (before or after):
        return ""
    return (f"（上下文，仅供参考）\n上文：…{before[-span:]}\n"
            f"【选中的文本】{selected}\n下文：{after[:span]}…")
```

then interpolate it into the `fact_check`, `discuss` and `discussion_overview` prompts, and have
`startDiscussion` send `context_before`/`context_after` too. If the fields are not going to be
used, delete them (with `AnalyzeRequest.highlight_id`) so the API stops claiming them.

**Verify:** T3 — assert the context reaches the mocked service *and* appears in the prompt; then
re-run the A/B above on the same selection and check that the referent is resolved.

**Applied (2026-10-23, `ai_service.py` + `routers/ai.py` + `static/js/panel.js` + tests):**

* `ai_service.py` — `CONTEXT_SPAN = 300` and `_excerpt(selected, before, after, span)`: the three
  parts labelled (`上文` / `【选中的文本】` / `下文`), each side bounded and the cut marked with `…`,
  and `""` when there is no context. `fact_check`, `discuss` **and** `discussion_overview` take
  `context_before`/`context_after` and put `_excerpt(...) or text` where the bare `{text}` used to
  be — so the excerpt *replaces* the selection rather than being added beside it (no duplication),
  and with no context the prompt is byte-for-byte what it was.
* `routers/ai.py` — `AnalyzeRequest.context` (the joined string) becomes the two halves;
  `DiscussionStartRequest` gains them; both routes pass them through. The unused `highlight_id`
  is gone from `AnalyzeRequest`, `DiscussionStartRequest`, `DiscussionContinueRequest` and
  `DiscussionSummarizeRequest`, and `panel.js` no longer sends it: the API was accepting four
  fields it never read. Pydantic ignores unknown keys, so an older client is unaffected.
* `static/js/panel.js` — `CONTEXT_SPAN = 300` replaces the 60-character slices in
  `computeSelection` (the review's `span=300` cannot bite if the client sends 60), and
  `context_before + context_after` no longer exists anywhere: the seam is gone at the source.
* Tests: five in `tests/test_ai.py` — four assert the context reaches the *prompt* by stubbing
  `_call` and capturing it, for `fact_check`, `discussion`, `discussion/start`, plus the
  no-context case that must stay bare; one pins `_excerpt`'s labels, its bound, its marked cut and
  the one-sided cases. Three existing fakes took the old signature and were updated.

**The A/B, re-run as the Verify line asks** (自由的窄廊 ch. 3, `gpt-oss:120b-cloud`, the panel's
default provider, same system prompt and temperature — only the excerpt differs):

| | prompt A (before) | prompt B (after) |
|---|---|---|
| The body | the selection alone | `上文：…《自由的窄廊》奠基於…而是和前作《國家為什麼會失敗》一樣好讀。` + `【选中的文本】…` + `下文：…` |
| Who 他們 is | **guessed** — "指代前文提到的某群体，常指社会科学家、政治学者等" (there is no 前文 in the prompt), and it ends by asking "**“他们”具体指谁**：是特定学者群体、研究机构，还是某本书/论文的作者？" | **resolved** — identifies 达龙·阿西莫格鲁 / 詹姆斯·罗宾逊 and their two books, and reads the sentence as *the authors' own method* ("作者偏好制度分析") |
| The book | never named | named, with its predecessor |

The defect is also visible in one line: the old payload was the two halves **joined**, so
`before[-60:] + after[:60]` reads `…而是和前作《國家為什麼會失敗》一樣好讀。他們有幸生長在前者…` — a
continuous sentence with the quoted words cut out of the middle, which is what the model would
have been handed if the service had interpolated that field.

**One correction to the finding:** "`context: str = ""` is accepted by all three service
methods" — only `fact_check` and `discuss` accepted it. `discussion_overview` had no context
parameter at all, which makes 深入讨论 slightly worse than the finding says: it is the reader's
most-used action and the one that sent the least.

**Note on stored data:** the panel now captures up to 300 characters per side instead of 60, so
new highlights store a richer `context_before`/`context_after` — which is also what P2-10's
context-aware painting will want. Existing rows keep their 60-character values; nothing is
migrated and no schema changes.

---

### P1-4 · Editing a note flattens it to one line ✔ applied

**Severity:** High · **Effort:** M · **Area:** Front-end
**Review:** ☑ accept ☐ defer ☐ reject

**Where:** `static/js/panel.js:588-604` (`editCurrent`), specifically `:591`.

**Evidence:** `const edited = prompt("编辑批注：", analysis.response);` — `window.prompt` is a
single-line input: newlines cannot be typed and Enter submits.

**Impact:** Every analysis the app stores is Markdown with paragraphs, bullet lists and
headings. Opening 编辑 and saving therefore collapses a multi-paragraph note onto one line,
destroying the structure of the content being edited. There is no undo.

**Fix:** edit in the panel instead of a browser dialog — reuse `#comment-input`:

```js
function editCurrent() {
    const analysis = state.editing;
    if (!analysis) return;
    el("panel-body").innerHTML =
        '<textarea id="comment-input" class="comment-input" rows="8"></textarea>';
    const box = el("comment-input");
    box.value = analysis.response;
    box.focus();
    showButtons({ save: true, delete: true });
    el("panel-save").textContent = "保存修改";
    state.editingDraft = true;   // saveCurrent() then PUTs this id
}
```

**Verify:** open a saved analysis with two paragraphs, edit, save, reload — both paragraphs
survive.

**Applied (2026-10-23, `static/js/panel.js` + `tests/test_ai.py`):**

* `editCurrent()` — the `prompt()` dialog is gone; the note opens in the panel's own
  `#comment-input` textarea (`rows="8"`, focused, pre-filled), the save button reads 保存修改, and
  `state.editingDraft` marks the open edit. Exactly the shape the finding proposes.
* `saveCurrent()` — an open draft routes to a new `saveEdit()`, which PUTs to
  `/api/ai/update/{analysis.id}` and then `await refreshHighlights()` before re-rendering. That
  refresh is not cosmetic: `showHighlight()` paints from the chapter's **cached** highlights, so
  without it the panel repainted the *old* text over the new — a second, quieter half of "editing
  does not work" that the finding does not mention. The box is deliberately left in place when the
  PUT fails, so a failed save cannot eat the reader's draft.
* `state` — `editing` and `editingDraft` are now declared fields, and `resetPanel()` clears both.
  Without that, dismissing a panel mid-edit left `editingDraft` set and the *next* 保存 would have
  PUT to the analysis the reader had walked away from.
* `resetPanel()` also restores the save label (`保存到数据库`). That is **P3-1's first clause**, and
  it is here because this change is what makes it necessary: 保存修改 would otherwise leak into the
  next panel — the exact leak P3-1 describes, now with a third label. P3-1's other two clauses
  (`state.summary`, `state.analysisType`) are untouched.
* `tests/test_ai.py::test_editing_a_note_keeps_its_paragraphs` — the server half of the Verify
  line: a multi-paragraph Markdown note (paragraphs, a list, a heading) survives save → edit, and
  comes back intact from both reads the panel makes afterwards (the chapter API it repaints from,
  and the highlights view).

**Client-side evidence.** The repo has no JS runner (T1, not accepted), so the panel was driven in
a throwaway stub DOM — `/tmp/p14_dom.js`, the same technique the `<p>　</p>` fix used — loading
`panel.js` unmodified except for one injected line exporting the private functions. Every click in
it goes through the listener the panel registered itself. 15 checks, against the real wiring:
opening the editor creates the textarea, the **whole** note is in it with its newlines, the box is
focused, the label reads 保存修改, the save sends `PUT /api/ai/update/7` and creates nothing, the
body carries both paragraphs byte-for-byte, the panel then repaints the *new* text, and a
dismissed draft cannot hijack a later save. Pointed at the pre-fix `panel.js` (with `prompt`
stubbed to behave as a browser's single-line dialog), the same harness reports 14 failures, and
the PUT body it captures is the defect in one line:

```
PUT /api/ai/update/7 {"response":"第一段：这一段的结尾在这里。 - 要点一 - 要点二 ## 小标题 第二段：结尾在这里。"}
```

---

### P1-5 · Keyboard readers lose chapter navigation and cannot create highlights ✔ applied

**Severity:** High · **Effort:** M · **Area:** Accessibility
**Review:** ☑ accept ☐ defer ☐ reject

**Where:** `static/js/reader.js:271-282` (keydown), `static/js/panel.js:326-350` (selection),
`templates/reader.html:76-82` (menu markup).

**Evidence:**

1. `keydown` is bound to the **shell** document only. Frames are separate event trees, so once
   the reader clicks into the book (which they must, to select text), ArrowLeft/ArrowRight no
   longer turn chapters and Escape no longer closes the image overlay.
2. Highlight creation is reachable only from `mouseup` on the frame; the menu items are
   `<div>`s with no `role`, `tabindex` or key handler.

**Impact:** After the first click in a chapter, the advertised keyboard navigation is dead;
and a reader who selects text with the keyboard (Shift+arrows) has *no* way to reach
解释说明 / 深入讨论 / 添加笔记 at all.

**Fix:**

```js
// wireFrameScroll(), next to the scroll listeners
win.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") load(BOOK.index - 1);
    if (event.key === "ArrowRight") load(BOOK.index + 1);
    if (event.key === "Escape") { hidePopup(); hideImagePopup(); }
});
```

plus menu semantics (`role="menu"` / `role="menuitem"` / `tabindex="0"`, Enter/Space
activates) and a non-mouse trigger such as `Ctrl/Cmd+K` on a non-empty selection.

**Verify:** click into a chapter, press →, chapter advances; Tab/Enter reaches the menu items.

**Applied (2026-10-23, `static/js/reader.js` + `static/js/panel.js` + `templates/reader.html`
+ `tests/js/`):**

* **The frame gets its own key handler.** `wireFrameScroll()` (already called on every frame load,
  already guarded per window) now wires `keydown` on the frame's window: arrows turn the chapter,
  ESC closes the footnote popup and the image overlay, and a popped-out image stays modal. It
  ignores keys aimed at a book's own `INPUT`/`TEXTAREA`/`SELECT`/contenteditable, so a book with a
  form keeps its keys. This is the finding's own snippet, plus the modal and form rules the
  shell-side handler already had.
* **The menu is reachable without a pointer.** The items carry `role="menuitem"`, `tabindex="0"`
  and an `aria-label` on the `role="menu"` container; `Enter` and `Space` do what a click does;
  and `showContextMenu()` focuses the first item (focus moves without a click, so the frame keeps
  the selection the menu is about).
* **Ctrl/Cmd+K opens the menu over a selection made with the keyboard**, which is the case that
  had *no* path at all: Shift+arrows never fires `mouseup`. The menu is placed under the
  selection's own box rather than at pointer coordinates. The mouseup handler's selection
  resolution moved into `selectionOrNull()` so both triggers share it.
* **One adjacent defect fell out of the tests.** `load()` re-loaded the frame even when the index
  did not change, so ArrowLeft on the first chapter flashed the chapter and wrote a progress row
  for a move that never happened — the nav buttons are `disabled` at the ends for exactly this
  reason, and the keyboard reached past that. `load()` now returns early when the index is
  unchanged *and* no anchor was asked for (a TOC entry inside the current chapter still jumps).

**Tested** — ten cases in `tests/js/reader-shell.test.js` and four in `tests/js/panel-flow.test.js`,
driving the shell's and the panel's own listeners through the stub DOM: the arrows turn the
chapter from inside the book (and record it), the ends are respected, ESC closes the image popup
from inside the book, a popped-out image stays modal, a book's form keeps its keys, `Enter` and
`Space` activate a menu item, Ctrl/Cmd+K opens the menu over a keyboard selection and its focused
item does the action, and Ctrl/Cmd+K with nothing selected opens nothing. Against the pre-P1-5
scripts exactly those five keyboard cases fail; with the fix, 31 of 31 front-end cases pass.

**Not verified here:** a real screen reader and real focus order need a browser engine (T1's open
step). The semantics are in the markup and the handlers, and the guards cover the wiring.

---

### P1-6 · Following an in-book link never saves progress ✔ applied

**Severity:** High · **Effort:** S · **Area:** Reading state
**Review:** ☑ accept ☐ defer ☐ reject

**Where:** `static/js/reader.js:875-903` (frame `load` handler), `:53-62` (`load`).

**Evidence:** When the reader follows a cross-document link inside the book (a footnote's
"在注释处打开", an internal cross-reference, a TOC-like link in the book's own front matter),
the frame navigates natively. The `load` handler detects the new chapter and updates
`BOOK.index` + the URL via `mark()`, but never calls `saveProgress()`. Only `load()` (the
shell's own navigation) and scroll events write progress.

**Impact:** Follow two links, close the tab without scrolling, and resume returns to the
chapter the reader started in — the URL and the database disagree. Compounded by
P2-8.

**Fix:**

```js
if (index >= 0 && index !== BOOK.index) {
    BOOK.index = index;
    mark();
    saveProgress(0);              // the frame moved the reader: record it
    ReaderPanel.setChapter(index);
}
```

**Verify:** open chapter 0, follow a cross-chapter link, close, reopen `/read/{slug}` — lands
on the linked chapter.

**Applied (2026-10-23, `static/js/reader.js` + `tests/js/reader-shell.test.js`):**

* The frame's `load` handler now reads the chapter the frame landed on *first*, then records it:
  `BOOK.index = moved; saveProgress(0); mark(); ReaderPanel.setChapter(moved)`. The path→index
  lookup became `frameChapterIndex()`, which returns `-1` for a document that is not a chapter of
  this book, so a link to a cover page still changes nothing.
* **A second defect in the same three lines, fixed with it.** `restoreScroll(BOOK.index)` ran
  *before* the index was updated, so a chapter entered by a link was scrolled to the **previous**
  chapter's remembered position — `lastPercentByChapter` has an entry for the chapter being left,
  not the one being entered. Deciding the chapter first fixes both; the review's fix snippet did
  not mention this half.
* `ReaderPanel.setChapter(moved)` is the review's, and it also hides an open context menu.

**Tested** (`tests/js/reader-shell.test.js`, five cases, driving the shell's own frame `load`
listener through the stub DOM T1 added): a link into another chapter records
`{chapter_index: 1, scroll_percent: 0}`; the bar and the panel follow it (`2 / 2`, panel state);
a load that stays on the chapter records **nothing** (no spurious writes on a reload); a load that
is not a chapter is left alone; and a chapter entered by a link is not scrolled to the previous
chapter's position. Against HEAD's `reader.js` the first case reports `progress POSTs=0` — the
finding's own evidence — and against the fixed file, `1`.

---

## P2 — Robustness, security, performance

### P2-1 · Book files are served at the app origin with no CSP ✔ applied

**Severity:** High · **Effort:** S · **Area:** Security
**Review:** ☑ accept ☐ defer ☐ reject

**Where:** `routers/reader.py:39-53` (`content_type`), `:56-68` (`book_file`).

**Evidence:** EPUB XHTML is returned as `text/html`; the response carries no
`Content-Security-Policy`, `X-Content-Type-Options` or caching headers (grep for any of them
across `*.py` returns nothing).

**Impact:** Inside the reader the content is safe: `sandbox="allow-same-origin"` (no
`allow-scripts`) prevents execution. But the same URL opened **directly** — bookmark, copied
link, "open in new tab", or a link rendered in the highlights view — is a normal top-level
document at the app's origin, so any script the EPUB ships runs with same-origin access to
`/api/*` (delete books, read/write annotations). The sandbox model deliberately treats the
book as untrusted; this is the one path that bypasses it. Self-hosting lowers the likelihood
but not the mechanism.

**Fix:** add the header in `book_file` (safe with the iframe — the shell's `contentDocument`
access is unaffected):

```python
return Response(
    content=found.read(),
    media_type=content_type(found.media_type),
    headers={
        "Content-Security-Policy": "script-src 'none'; object-src 'none'",
        "X-Content-Type-Options": "nosniff",
    },
)
```

`script-src 'none'` also blocks inline handlers; styles, images and fonts still load, so model
A renders unchanged.

**Verify:** T5; and open a chapter URL directly, with a
`<script>alert(1)</script>` planted in the fixture — it must not execute.

**Applied with P2-3 (2026-10-23, `routers/reader.py` + `tests/test_book_route.py`):** the route
now sends `Content-Security-Policy: script-src 'none'; object-src 'none'` and
`X-Content-Type-Options: nosniff`, exactly as the fix proposes, and T5's test asserts both on a
chapter URL. `script-src 'none'` also blocks inline handlers; styles, images and fonts still load,
so model A renders unchanged — the frame's sandbox already stopped the scripts, and this closes
the direct-navigation path the sandbox cannot.

**What could not be checked here:** the execution half of the Verify line needs a browser engine,
and this environment has none (see T1). The header is pinned; "the planted script does not run" is
the browser's job and would be the first assertion of the Playwright smoke if it is added.

---

### P2-2 · The library page is N+1 ✔ applied

**Severity:** Medium · **Effort:** S · **Area:** Performance
**Review:** ☑ accept ☐ defer ☐ reject

**Where:** `routers/library.py:104-130` (`library_card`), specifically `:108`;
`database.py:24-27` (`_connect` per call).

**Evidence:** `library_card()` calls `get_db().get_progress(row["slug"])`, and `Database`
opens and closes a fresh SQLite connection per method call.

**Impact:** The SPEC targets a 299-book corpus; the library page then opens/closes 299
connections per render, plus `backfill_chapter_counts` work on old rows. Cheap to fix and it
scales with the library, not with the request.

**Fix:** one `LEFT JOIN` in `Database`:

```python
def books_with_progress(self) -> list[dict]:
    rows = conn.execute("""
        SELECT b.*, p.chapter_index AS p_chapter, p.scroll_percent AS p_scroll,
               p.is_completed AS p_completed
        FROM books b LEFT JOIN reading_progress p ON p.book_id = b.slug
    """).fetchall()
```

and pass the joined fields into `library_card()` / `book_percent()` instead of a second call.

**Verify:** T4.

**Applied (2026-10-23, `database.py` + `routers/library.py` + `tests/test_library.py`):**

* `Database.books_with_progress()` — one `LEFT JOIN` over `reading_progress`, with the progress
  columns aliased (`p_present`, `p_chapter`, `p_scroll`, `p_completed`). `p_present` is the point
  of the alias: "no progress row" and "a row of zeroes" are different states, and the card has to
  tell them apart (`has_progress`).
* `library_card()` now takes the joined row and touches **no database at all** — the `get_db()`
  import inside it is gone, which is the shape the finding asked for. `library_view()` reads
  `books_with_progress()` instead of `list_books()`.
* **T4 landed with it**: `test_the_library_page_costs_one_query_however_many_books` counts
  `sqlite3.connect` calls across a five-book render. Against the pre-fix code it reports **6
  connections for 5 books** (one `list_books` plus one per card); after, 1 — with the threshold at
  3 so a future backfill has room without the test having to be loosened.
* A second test pins the join's fidelity, since the per-book lookup it replaced also fed
  `has_progress` and `is_completed`: a card with no progress row shows no summary, 90% of the last
  chapter of two reads 95%, and marking complete still says so.

---

### P2-3 · No caching headers on book files ✔ applied

**Severity:** Medium · **Effort:** S · **Area:** Performance
**Review:** ☑ accept ☐ defer ☐ reject

**Where:** `routers/reader.py:56-68`.

**Evidence:** `book_file` returns a bare `Response` with no `ETag`, `Last-Modified` or
`Cache-Control`.

**Impact:** Every chapter turn re-downloads that chapter's stylesheet, fonts, images and cover;
a re-read of the same chapter refetches everything. This is the largest avoidable cost on a
NAS/HDD and the easiest visible win after P2-2.

**Fix:** derive an `ETag` from the book row (`added_at` + `path`) or the file mtime, honour
`If-None-Match`, and send `Cache-Control: public, max-age=3600` (uploads already `drop()` the
cache, and a replaced file gets a new mtime, so invalidation is safe).

**Verify:** second load of the same chapter returns 304 and no body.

**Applied with P2-1 (2026-10-23, `routers/reader.py` + `tests/test_book_route.py`):** the response
carries `ETag`, `Cache-Control: public, max-age=3600`, and an `If-None-Match` check that answers
`304` with no body (`*` and a list of tags are honoured). The validator is the **EPUB file's**
mtime plus the member path — a member has no mtime that survives a re-upload, and any change to
the book replaces the archive — so the upload path's `book_cache.drop()` and a replaced file's new
stamp invalidate it together. T5's test asserts the 304, that a stale validator still gets the
file, that `*` is honoured, that two members of one book differ, and that a **re-upload changes
the validator** so a cached chapter cannot survive it.

---

### P2-4 · CJK word count double counts ✔ applied

**Severity:** Medium · **Effort:** S · **Area:** Metadata
**Review:** ☑ accept ☐ defer ☐ reject

**Where:** `routers/__init__.py:151-169`; test that pins the behaviour: `tests/test_helpers.py:71`.

**Evidence:** `LATIN_WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)` matches CJK runs, so each run
is counted once as a Latin word **and** its characters are counted at half weight. Measured:

```
"这是一段中文。" * 3  ->  3 tokens + round(15/2) = 12   (21 characters)
docstring rule        ->  0 latin + round(15/2) = 8
```

`test_word_count_counts_latin_words_and_halfweight_cjk` asserts the inflated number and its
comment ("three \w+ tokens") contradicts the function's own docstring ("Latin-script words
count once; CJK characters count as half a word each").

**Impact:** Word count and reading time are overstated by roughly one word per CJK run
(paragraph/line) — ~1–3% on Chinese books. Cosmetic, but the displayed stat is wrong, and the
test enshrines the wrong rule.

**Fix:**

```python
LATIN_WORD_RE = re.compile(r"[A-Za-z]+(?:['’\-][A-Za-z]+)*")
```

(optionally add `[0-9]+` if numerals should count). Update the test's expectation and comment.

**Verify:** `estimate_book_word_count` on a pure-CJK fixture equals `round(chars / 2)`.

**Applied (2026-10-23, `routers/__init__.py` + `tests/`):** the word pattern no longer matches CJK.
One deliberate deviation from the fix's snippet, in the reader's favour:

```python
CJK_RANGES = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
LATIN_WORD_RE = re.compile(rf"[^\W{CJK_RANGES}]+", re.UNICODE)
CJK_CHAR_RE = re.compile(rf"[{CJK_RANGES}]")
```

The review suggests `[A-Za-z]+(?:['’\-][A-Za-z]+)*` and notes numerals could be added back. That
whitelist would also have dropped every accented Latin word — `café`, `Straße`, `naïve` — which
`\b\w+\b` counted before, so a French or German book would have *lost* words to fix a Chinese
double count. Excluding the CJK blocks from `\w` instead fixes exactly the reported defect and
changes nothing else: accented letters, digits and underscores all still count, and a CJK run is
no longer also a word. The ranges now live in one constant, used by both patterns.

Three tests: the existing one updated (`'Hello world 汉字'` is **3**, not 4 — two words plus two
characters at half weight, and its comment no longer claims three `\w+` tokens); a pure-CJK book
equals `round(chars / 2)` (the Verify line); and accented Latin plus numerals still count, which is
what a whitelist would have broken.

**Stored values are not migrated.** `word_count` is written at upload, so the four books in the
developer's library keep their inflated numbers (707,455 for 剑桥中华民国史 and so on) until they
are uploaded again. Nothing reads the number as anything but a display string, and a re-upload
refreshes it — the same path that already restores annotations.

---

### P2-5 · The book cache can close a book another request is using

**Severity:** Medium · **Effort:** M · **Area:** Concurrency
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `routers/__init__.py:39-57` (`get_or_open`), `booksource.py:218-222` (`close`).

**Evidence:** Eviction (9th book) and `drop()` (upload/delete) call `Book.close()`, which sets
`_book = None`. Every accessor then returns `""`/`[]`/`None` instead of failing — so an
in-flight request holding the same `Book` object silently renders an empty chapter, an empty
TOC or a 404 rather than an error. `tests/test_helpers.py:108-121` asserts exactly this
"closed yields empty string" behaviour.

**Impact:** Low probability at 8 books and one user, but the failure is *silent* and the
symptom (blank chapter) is hard to attribute. A background library render that opens missing
books (`backfill_chapter_counts`) makes eviction during reading plausible on a large shelf.

**Fix:** reference-count entries — `with book_cache.borrow(slug, path) as book:` that marks an
entry in use and refuses to evict it (or reopens on release); alternatively have `close()`
set a `_closed` flag and raise a named error that routes map to a 503/retry, so the failure is
visible.

**Verify:** a test that evicts a book mid-use and asserts the second caller gets a usable book.

---

### P2-6 · `get_db()` is not thread-safe

**Severity:** Medium · **Effort:** S · **Area:** Concurrency
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `routers/__init__.py:87-94`.

**Evidence:** `if _db is None: _db = Database(DB_PATH)` — no lock. Two concurrent first
requests can both construct `Database`, and both run `init_db()`; on an existing database the
two `ALTER TABLE` statements in `_ensure_columns` (`database.py:99-105`) can race to
`duplicate column name`.

**Impact:** A rare 500 at process start against an older schema; the module already imports
`threading` for the cache, so there is no reason not to lock this.

**Fix:**

```python
_db_lock = threading.Lock()

def get_db():
    global _db
    if _db is None:
        with _db_lock:
            if _db is None:
                from database import Database
                _db = Database(DB_PATH)
    return _db
```

**Verify:** no behavioural test needed; note the lock in the docstring.

**Applied (2026-10-23, `routers/__init__.py` + `tests/test_helpers.py`):** a double-checked
`_db_lock` around the construction, with the docstring naming the failure it closes (`duplicate
column name` from two concurrent `_ensure_columns` runs), exactly as the fix proposes.

The review says no test is needed; there is one anyway, because it can be made non-flaky in the
only direction that matters.
`test_the_database_is_built_once_under_concurrent_first_requests` slows the constructor by 50 ms
and hammers `get_db()` from eight threads: with the lock exactly one build is *possible*, so the
test cannot fail spuriously — and against the pre-fix code it reports **"the database was built 8
times"**.

---

### P2-7 · `.env` overrides the real environment

**Severity:** Medium · **Effort:** S · **Area:** Configuration
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `server.py:16-30` (`load_env`).

**Evidence:** `os.environ[key.strip()] = value.strip()` unconditionally. It also does not strip
surrounding quotes, does not tolerate `export `, and does not handle inline comments.

**Impact:** `READER_PORT=9000 uv run server.py` or a systemd/container environment is silently
clobbered by whatever `.env` says. `.env.example` documents these same keys as the deployment
surface, so the override is likely to bite exactly when someone is trying to change it.

**Fix:** `os.environ.setdefault(key, value)` (plus `value.strip().strip('"\'')`), or adopt
`python-dotenv` with `override=False` — it is one dependency and handles quoting/comments.

**Verify:** run with `READER_PORT=9000` and `.env` containing `READER_PORT=8123`; the server
must bind 9000.

**Applied (2026-10-23, `server.py` + `tests/test_scaffold.py`):** `os.environ.setdefault(key,
value.strip().strip("\"'"))` — the fix's own shape, `setdefault` plus quote-stripping, so a
hand-written `.env` with quoted values still works. Two tests:
`test_the_environment_wins_over_the_env_file` asserts the real environment wins for `READER_PORT`
and that `.env` still fills the gaps (and that `"hermes3:latest"` loses its quotes); against the
pre-fix code it fails with `assert '8123' == '9000'`, which is the finding's own reproduction.
`test_a_missing_env_file_is_not_fatal` keeps the no-`.env` path covered.

---

### P2-8 · Progress writes can lose to older writes

**Severity:** Medium · **Effort:** M · **Area:** Reading state
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `static/js/reader.js:53-62` (`load`), `:486-502` (`saveProgress`),
`:619-655` (`restoreScroll`); server side `routers/settings.py:56-95`,
`database.py:362-388`.

**Evidence:** Progress saves are fire-and-forget `fetch()` calls without ordering. `load()`
cancels the *pending* debounce timer, but a request already on the wire from the previous
chapter can land after the new chapter's `saveProgress(0)`. SQLite keeps whichever arrives
last, so the stored position can move *backwards* a chapter.

Separately, `saveProgress()` writes `lastPercentByChapter.set(BOOK.index, percent)` and
`load()` immediately writes `0` for the chapter being entered — so the in-session memory that
`restoreScroll()` consults (`:628-629`) is always zero for a chapter entered this session.
Going A → B → A starts A at the top even though its scroll position was known.

**Impact:** "Resume" can land a chapter behind after fast navigation, and in-session
backtracking loses the position the map exists to remember. Both are silent.

**Fix:**

1. Stamp each save with a monotonic client sequence (`seq: ++state.seq`) and have
   `save_progress` ignore a write whose `seq` is lower than the stored one (a column, or an
   `UPDATE ... WHERE last_read_at <= ?` guard).
2. Write the outgoing chapter's final percent before overwriting `BOOK.index`, i.e. in
   `load()`: `saveProgress(lastPercentByChapter.get(BOOK.index) ?? frameScrollPercent())`
   before switching, and only then set the new chapter's entry.

**Verify:** throttle the network, click next twice quickly, reload — resume is on the last
chapter; A → B → A returns to A's position.

---

### P2-9 · `/api/text` ships the chapter twice and mislabels the count ✔ applied

**Severity:** Medium · **Effort:** S · **Area:** API
**Review:** ☑ accept ☐ defer ☐ reject

**Where:** `routers/reader.py:186-213`, specifically `:211`;
`tests/test_text_api.py:15`.

**Evidence:** The response carries `text` (the whole chapter's `plain_text`) **and** every
anchor block's `text`. The only consumer (`panel.js:253-259`) reads `blocks` and ignores
`text`. The field `"word_count": len(text)` is a **character** count — and the test asserts
`payload["word_count"] == len(payload["text"])`, baking the misnomer in.

**Impact:** On a large chapter the panel downloads the chapter twice (once as prose, once split
into blocks) on every chapter turn, only to map the user's selection to a block id. The name
`word_count` will mislead the next caller into using it as a word count.

**Fix:** return `text` only on `?text=1` (or drop it), and rename the count to `char_count`
(update the test). If a word count is wanted, reuse `estimate_book_word_count`'s rules.

**Verify:** response size halves for a big chapter; `len(blocks)` mapping unchanged.

**Applied (2026-10-23, `routers/reader.py` + `tests/test_text_api.py`):** the response is the
blocks and the count; the prose is opt-in behind `?text=1`, and `word_count` is `char_count` —
which is what it always was. The endpoint's docstring says both, and that a word count is
`estimate_book_word_count`'s job with the rules it documents. When the prose *is* asked for it is
parsed once and shared with the count rather than twice.

Measured on a real chapter after the change (自由的窄廊, ch. 25 — its largest, `OEBPS/quote.xhtml`,
656 blocks, 88,426 characters): **220,449 bytes → 129,649** per chapter turn, so the prose the
blocks already carry is no longer on the wire a second time. The saving is not exactly half because
the blocks are JSON objects with ids and DOM ids around their text; it grows with the chapter,
which is where the finding pointed. `len(blocks)` and the block ids are unchanged, which is what the
panel maps a selection against.

The test now asserts the absent fields as well as the present ones (`"text" not in payload`,
`"word_count" not in payload`) and exercises `?text=1` for the caller that wants the chapter as one
string.

---

### P2-10 · Anchor data is stored that is never used

**Severity:** Medium · **Effort:** M · **Area:** Data model
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `static/js/panel.js:292-309` (capture), `:663-716` (paint);
`routers/highlights.py:93-113` (store); `routers/settings.py:56-60` and
`database.py:362-388` (progress); `database.py:54, 77, 89, 93` (columns).

**Evidence:**

1. `computeSelection()` captures `context_before`/`context_after` (60 chars each side),
   `store_highlight()` writes them, and nothing ever reads them. `wrapText()` wraps the
   **first** occurrence of `selected_text` in the block — so two identical sentences in one
   paragraph always paint the first one, which is the exact ambiguity the context fields exist
   to resolve.
2. `reading_progress.block_id` is never written; `save_progress()` has no such parameter.
   `anchor` is accepted by `ProgressUpdate` but never read back. Live DB confirms: 0 rows with
   either set.

**Impact:** The stored annotation is weaker than it looks: a chapter with a repeated sentence
paints the wrong occurrence, and progress cannot anchor to a block the way SPEC principle 5
describes. Two columns and two request fields are dead weight.

**Fix:** use the context at paint time — choose the occurrence whose surroundings best match
`context_before`/`context_after` (fall back to first match), and persist a block-relative
offset if the strongest anchor is wanted. For progress, either write `block_id`/`anchor` from
the first visible block, or drop the columns so the schema stops implying a precision it does
not have.

**Verify:** a chapter with two identical sentences; highlight the second, reload — the second
is painted.

---

### P2-11 · `analysis_type` is validated on one endpoint and not the other ✔ applied

**Severity:** Medium · **Effort:** S · **Area:** API
**Review:** ☑ accept ☐ defer ☐ reject

**Where:** `routers/ai.py:35-41` and `:119-120` (validated) vs `:44-61` and `:134-156`
(unvalidated); consumers: `panel.js:686` (`hl-<kind>`), `routers/highlights.py:151-156, 197-202`.

**Evidence:** `/api/ai/analyze` rejects anything but `fact_check`/`discussion`;
`SaveAnalysisRequest.analysis_type` is a bare `str` and is written straight to the database.

**Impact:** An arbitrary string becomes a CSS class, a `KIND_LABELS` miss (rendered raw), and a
stats key the header never displays. `ConversationMessage.role` is likewise unconstrained, so
a client can inject a `system` turn into the model conversation — harmless for one trusted
user, but the API should not accept it.

**Fix:**

```python
from typing import Literal
AnalysisType = Literal["fact_check", "discussion", "comment"]

class SaveAnalysisRequest(BaseModel):
    analysis_type: AnalysisType
    ...

class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
```

**Applied (2026-10-23, `routers/ai.py` + `tests/test_ai.py`):** the two Literals the fix names —
`AnalysisType = Literal["fact_check", "discussion", "comment"]` on `SaveAnalysisRequest`, and
`role: Literal["user", "assistant"]` on `ConversationMessage` — with the module comment saying
what the string was becoming (a CSS class, a `KIND_LABELS` miss, a stats key nothing displays).
`AnalyzeRequest.analysis_type` is deliberately left a `str` with its route-level 400: the fix
scopes itself to the save path, and turning that one into a 422 would change the error the panel
already knows how to show.

Three tests: an unknown kind on save is a **422 that stores nothing**; the three real kinds are
still accepted (three highlights, three analyses); and a `system` turn is refused while the two
real roles still work. Against the pre-fix code the first two fail with `assert 200 == 422`.

---

### P2-12 · SQLite tuning and connection boilerplate

**Severity:** Medium · **Effort:** S · **Area:** Storage
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `database.py:24-27` (`_connect`), the ~20 methods that repeat
`conn = self._connect() / try / finally: conn.close()`; writes at `:362-388`.

**Evidence:** No `PRAGMA journal_mode=WAL`, no explicit `busy_timeout`, default rollback
journal, one connection per operation. Concurrent writes (progress save during a highlight
save) can raise `database is locked`; the reader's client-side `.catch(() => {})`
(`reader.js:496`) then swallows it, so the position silently does not save.

**Impact:** Rare under one user, but it converts a benign collision into invisible data loss —
and the boilerplate is ~150 lines that could be ~25.

**Fix:**

```python
def _connect(self):
    conn = sqlite3.connect(self.db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

@contextmanager
def _session(self):
    conn = self._connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
```

then `with self._session() as conn:` in each method.

**Verify:** concurrent progress + highlight writes under `ThreadPoolExecutor` do not 500.

---

## P3 — Polish, correctness nits, documentation

### P3-1 · Panel save label leaks across modes ✔ applied

**Severity:** Low · **Effort:** S · **Area:** Front-end
**Review:** ☑ accept ☐ defer ☐ reject

**Where:** `static/js/panel.js:153-168` (`resetPanel`), `:410-421` (`startComment`),
`:499-521` (`summarizeDiscussion`), `:524-573` (`saveCurrent`).

**Evidence:** `#panel-save` starts as 保存到数据库, but `startComment` rewrites it to 保存笔记 and
`summarizeDiscussion` to 保存总结. `resetPanel()` restores neither the label, `state.summary`,
nor `state.editing`.

**Impact:** After summarising a discussion once, the next 解释说明 panel offers a button labelled
保存总结 that actually saves a fact-check. Cosmetic but confusing, and it makes the saved
analysis type look wrong. A stale `state.summary` sits in memory between panels.

**Fix:** in `resetPanel()`: `el("panel-save").textContent = "保存到数据库";` and clear
`state.summary = null; state.editing = null; state.analysisType = null;`.

**Partly applied with P1-4 (2026-10-23):** the first clause landed — `resetPanel()` restores
`保存到数据库`, and clears `state.editing` — because P1-4 adds a third label (保存修改) and its
draft flag, and both must be reset or the leak gets worse. What remains here is `state.summary`
and `state.analysisType` (a stale summary and a stale type between panels), plus the triage
decision. Left unticked.

**Fully applied (2026-10-23, `static/js/panel.js` + `tests/js/panel-flow.test.js`):** the rest of
the fix's line — `state.summary = null; state.analysisType = null;` in `resetPanel()`, both now
declared fields of `state` rather than appearing on first assignment. The stale summary mattered
more than the label: it is what `saveCurrent()` writes in discussion mode, so the next panel's
save could have stored the *previous* discussion's summary.

Pinned by `one panel's label and state do not leak into the next`: summarise a discussion (the
button reads 保存总结, `state.summary` holds the text), close the panel, ask for 解释说明 — and the
button is back to 保存到数据库 with no summary in memory. Against the pre-P1-4/P3-1 `panel.js` it
fails with `actual: 'a summary of the discussion'`.

---

### P3-2 · The 编辑 button in the reader panel is unstyled ✔ applied

**Severity:** Low · **Effort:** S · **Area:** Front-end
**Review:** ☑ accept ☐ defer ☐ reject

**Where:** `static/js/panel.js:806-808`, `static/css/highlights.css:127-137`.

**Evidence:** The button is created with `className = "action-link"`, a class defined only in
`highlights.css` (loaded by the highlights page). `grep -c action-link static/css/reader.css`
= 0.

**Impact:** A default browser button appears inside the otherwise carefully styled panel —
the only unstyled control in the reader.

**Fix:** add `.saved-analysis .action-link { ... }` to `reader.css` (or a `btn-link` class
shared by both stylesheets).

**Applied (2026-10-23, `static/css/reader.css` + `tests/test_reader.py`):** the first option, scoped
to `.saved-analysis` so it cannot leak onto anything else the panel builds, mirroring
highlights.css's rule (no background, no border, accent colour, underline on hover).

**This one is now guarded by a test, which is the better half of it.** T1's class guard had exactly
one exemption, and it was this finding: `.action-link` named by `panel.js` with no rule on the
reader page. Fixing P3-2 emptied `UNSTYLED_CLASSES` — the guard's staleness check is what demanded
the exemption's removal — and deleting the rule again now fails the suite with
`['action-link']`.

---

### P3-3 · Markdown export breaks multi-paragraph quotes

**Severity:** Low · **Effort:** S · **Area:** Export
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `routers/highlights.py:226-253`, specifically `:237`.

**Evidence:** `lines.append(f"> {item['selected_text']}")` prefixes only the first line of the
selection. A selection spanning two paragraphs exports as one quoted line followed by an
unquoted paragraph (which then reads as commentary).

**Impact:** The exported record — the file the reader keeps — misrepresents where the quote
ends and the note begins.

**Fix:** `quoted = "\n".join("> " + line for line in text.splitlines())`, or normalise
whitespace in the export as `_view_items` already does for display.

---

### P3-4 · `<html lang="en">` on a Chinese UI

**Severity:** Low · **Effort:** S · **Area:** Accessibility
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `templates/library.html:2`, `templates/reader.html:2`, `templates/highlights.html:2`.

**Evidence:** All three declare `lang="en"`; the interface, buttons, notices and the book text
are predominantly Simplified Chinese.

**Impact:** Screen readers pick the wrong voice and pronunciation rules; browser translation
and hyphenation are misled. One attribute, three files.

**Fix:** `lang="zh-Hans"` (the English strings are short enough not to need per-element
`lang`), or `<html lang="zh-Hans">` with `lang="en"` on the few English labels.

---

### P3-5 · Stale `unsupported`, derived from the database row ✔ applied

**Severity:** Low · **Effort:** S · **Area:** Robustness
**Review:** ☑ accept ☐ defer ☐ reject

**Where:** `routers/reader.py:122` and `:155`; `booksource.py:54-59`.

**Evidence:** Both the reader shell and `/api/book` read `row["unsupported"]` from SQLite
rather than `book.unsupported` from the opened book. If the file is deleted or replaced behind
the app's back, the row still says "supported", `Book.open` returns an unopenable adapter, and
`chapter_count` is 0 — so `/api/book` reports `unsupported: null` while `/read/{slug}/0` 404s
"No such chapter".

**Impact:** A missing/broken file surfaces as a generic 404 instead of the named
`unreadable file: …` reason that principle 7 promises. `unsupported` is cheap to recompute
(the book is already open at that point), so caching it buys nothing.

**Fix:** report `book.unsupported or row["unsupported"]` (live value wins), and let the reader
shell render its existing unsupported panel when `chapter_count == 0`. Keep the DB column for
the library cards, which must not parse books.

**Applied with P3-6 (2026-10-23, `routers/reader.py` + `tests/test_reader.py`):** both the shell
and `/api/book` report `book.unsupported or row["unsupported"]`, and the shell renders its reason
page — rather than raising `No such chapter` — when the book has no chapters at all. The template
context moved into one `shell_context()` helper so the chapter page and the reason page cannot
drift apart. The DB column stays for the library cards, which must not parse books, exactly as the
fix says.

Tested by deleting a book's file behind the app's back (the row still says it is fine): the card
still links to it, and `/read/{slug}/0` answers **200 with 无法打开此书 and the `unreadable file: …`
reason**; `/api/book/{slug}` reports the same live value; and a healthy book still opens with its
frame and `unsupported: null`, so the live check cannot turn a good book into a reason page.
Against the pre-fix code the first assertion is `assert 404 == 200`.

---

### P3-6 · `read_redirect` can compute `chapter_index = -1` ✔ applied

**Severity:** Low · **Effort:** S · **Area:** Routing
**Review:** ☑ accept ☐ defer ☐ reject

**Where:** `routers/reader.py:74-86`.

**Evidence:** `index = min(progress["chapter_index"], book.chapter_count - 1)`. For a book with
an empty spine (`chapter_count == 0`) this yields `-1`, redirecting to `/read/<slug>/-1`, which
then 404s. Without a progress row it redirects to `/read/<slug>/0`, which also 404s.

**Impact:** An empty-spine book (malformed but openable) can never show its reason page from
the library link, because `/read/{slug}/{i}` rejects every index. Small, but it is the one
place where a named failure becomes a bare 404.

**Fix:** `index = min(max(progress_index, 0), max(book.chapter_count - 1, 0))` and let the
shell render the unsupported panel when `chapter_count == 0` (see
P3-5).

**Applied with P3-5 (2026-10-23):** the clamp is the fix's own line, and the shell now renders its
reason page at index 0 rather than 404ing on every index. Tested by giving a book a progress row
and *then* deleting its file: `/read/{slug}` redirects to `…/0` — against the pre-fix code it
reports `Location: /read/Fixture%20Book/-1`, the finding's own output — and that URL answers 200
with the reason.

---

### P3-7 · Docstrings and SPEC that contradict the code

**Severity:** Low · **Effort:** S · **Area:** Documentation
**Review:** ☐ accept ☐ defer ☐ reject

**Where/Evidence:**

| Claim | Reality |
|---|---|
| `server.py:1-5` — "The routers are empty until their phase lands" | every router is fully implemented |
| `routers/highlights.py:100-102` — "A highlight is never stored on its own" | `POST /api/highlight` (`:116-123`) stores exactly that, and `test_highlights.py:22` asserts it |
| `SPEC.md:286-293` — "the rendering model is **undecided** (A/B/C)" | model A shipped in P2, documented in `reader.html:62` and README |
| `SPEC.md:57-66` — Docker and systemd packaging are "in" scope | no `Dockerfile`, no unit file; P5 outstanding (README agrees) |

**Impact:** Comments are load-bearing in this codebase — they explain non-obvious decisions
(the `bookPrefix` encoding note, the resume marker). A stale one costs the next reader real
time, and the highlights one actively misdescribes the data model.

**Fix:** update the three docstrings, mark P5 explicitly as "not started" in SPEC, and replace
the "undecided rendering" paragraph with the model-A decision and its trade-offs (MathJax
under a script-less sandbox, dark mode vs the book's CSS) — those trade-offs are still open and
worth keeping.

---

### P3-8 · `httpx2` is a runtime dependency for a test-only need

**Severity:** Low · **Effort:** S · **Area:** Dependencies
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `pyproject.toml:13`.

**Evidence:** Starlette 1.7's `TestClient` prefers `httpx2` and warns when only `httpx` is
present (`starlette/testclient.py:33-48`). The application itself imports `httpx`
(`ai_service.py:16`). `httpx2` is therefore needed only by the test client, yet it sits in
`[project].dependencies`.

**Impact:** Production installs carry a package they never import; the dependency list
overstates the runtime surface.

**Fix:** move `"httpx2>=2.0"` into `[dependency-groups].dev` next to `pytest` and keep
`httpx` in the runtime list. `uv sync` still installs both for development and CI.

---

### P3-9 · AI client is created per call, and one `except` is unreachable

**Severity:** Low · **Effort:** S · **Area:** AI
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `ai_service.py:66-92`.

**Evidence:**

* `async with httpx.AsyncClient(timeout=60.0) as client:` inside every `_call` — a new pool,
  TLS context and teardown per request, and a discussion issues one call per turn.
* The 60 s timeout is fixed and there is no retry. Observed on this machine: a **cold**
  `hermes3:latest` (the configured local model) exceeded 60 s on the first
  `/api/ai/discussion/start`, i.e. `AIServiceError` → **502** on the reader's first 深入讨论
  after the model has been unloaded. The second attempt would have succeeded.
* `except AIServiceError: raise` at `:89-90` is dead: the only raiser, `connection()`, is
  called at `:69`, *before* the `try`.

**Impact:** No correctness problem, but needless per-call setup and a misleading error path —
someone reading the block will assume provider errors are handled there.

**Fix:** create one `httpx.AsyncClient` per `AIService` (or per event loop) and close it on
shutdown; move `connection()` inside the `try` or delete the dead handler.

---

### P3-10 · No upload size cap and no staging-directory sweep

**Severity:** Low · **Effort:** S · **Area:** Operations
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `routers/library.py:135-204`; `temp/`.

**Evidence:** `shutil.copyfileobj(file.file, out)` accepts a file of any size, and staging
files are removed only by the request's `finally`. `temp/` currently holds two orphaned EPUBs
from Oct 8 (an interrupted upload or a killed process).

**Impact:** A stray multi-GB upload fills the disk; orphans accumulate silently. Single-user,
so this is hygiene rather than a DoS boundary.

**Fix:** reject `file.size` above a configurable limit (e.g. `READER_MAX_UPLOAD_MB`, default
100) with a named 413, and sweep `temp/*.epub` older than an hour at startup.

---

### P3-11 · The unsupported reason is only a tooltip

**Severity:** Low · **Effort:** S · **Area:** UX
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `templates/library.html:69-71`; `routers/library.py:116-130`.

**Evidence:** The card shows `⚠ 无法打开此书` with `title="{{ book.unsupported }}"`, and the
reason is only visible in the reader's unsupported panel — which the card cannot reach
(no 浏览本书 link). SPEC §Principles 7 and the upload docs say the reason belongs on the card.

**Impact:** The one piece of information that tells the reader *why* the book is unusable
(drm, image-only, unreadable file) is hidden behind a hover, which touch devices do not have.

**Fix:** render a clamped `.unsupported-reason` line under the warning (CSS line-clamp +
`title` for the full text).

---

### P3-12 · Deleting a card leaves an empty letter pill and stale stats

**Severity:** Low · **Effort:** S · **Area:** UX
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `static/js/library-app.js:100-117`; `static/js/highlights-app.js:38-58`.

**Evidence:** `deleteBook` removes the `<article>` and re-runs `applyFilters()`, but the letter
pill for that group stays in the index even when its last book is gone. In the highlights view,
`deleteAnalysis`/`deleteHighlight` remove one row and leave the header counts (`stats-bar`)
unchanged.

**Impact:** The library shows an empty group that filters to nothing; the highlights page claims
"📝 12 全部" after three were deleted. Both are small trust costs in an app that otherwise
counts carefully.

**Fix:** after removal, hide any `.library-index-link` with no visible card (`data-group`) and
decrement/`recompute` the stats counts from the remaining items.

---

### P3-13 · Markdown rendering fails open if DOMPurify is absent

**Severity:** Low · **Effort:** S · **Area:** Security
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `static/js/panel.js:61-64`.

**Evidence:**

```js
function renderMarkdown(markdown) {
    const html = window.marked ? marked.parse(markdown || "") : escapeHtml(markdown);
    return window.DOMPurify ? DOMPurify.sanitize(html) : html;
}
```

If `purify.min.js` fails to load (404, truncated file, upgrade), AI output and **user note
text** go into `innerHTML` unsanitised. `marked` passes raw HTML through by default.

**Impact:** The server already sanitises with bleach before rendering the highlights page, so
the exposure is limited to the reader panel — but the panel is exactly where AI text and
user-authored Markdown are injected. A sanitiser should fail closed.

**Fix:**

```js
return window.DOMPurify ? DOMPurify.sanitize(html) : escapeHtml(markdown);
```

and consider a startup check for the vendor files (`static/vendor/README.md` already documents
versions).

---

### P3-14 · `routers/__init__.py` is a grab-bag

**Severity:** Low · **Effort:** M · **Area:** Architecture
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `routers/__init__.py:1-250`.

**Evidence:** One module owns the book cache, the database singleton, the AI service singleton,
runtime settings, the slug algorithm, folder naming, word counts, reading time, pinyin
sorting/grouping and asset versioning. Every router then imports pieces of it function-locally
(`from . import get_db`) to dodge circular imports — a symptom, not a style choice.

**Impact:** The file is the de facto application core but is named for the router package; the
lazy imports make dependency direction invisible and defeat static analysis. It is the one
place where a new reader cannot tell what depends on what.

**Fix:** split into `app_state.py` (cache, db, ai, settings), `text.py` (counts, reading time),
`titles.py` (slug, sorting, grouping) and `assets.py` (versioning); have routers import them
directly. Pure refactor — the tests already cover each helper.

---

### P3-15 · Dead API and schema surface

**Severity:** Low · **Effort:** S · **Area:** API
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `routers/highlights.py:116-123` (`POST /api/highlight`), `database.py:272-286`
(`analyses_for_book`), `routers/settings.py:56-60` (`anchor`).

**Evidence:** The panel never calls `POST /api/highlight` (it saves through `/api/ai/save`,
which creates the mark and its content together); `analyses_for_book()` has no caller;
`ProgressUpdate.anchor` is accepted and dropped on the floor.

**Impact:** Every unused endpoint is a second write path to validate and a promise the reader
never keeps. `POST /api/highlight` in particular contradicts the "a highlight is stored only
with its content" rule the last commit established.

**Fix:** remove the endpoint (and its test), `analyses_for_book()`, and `ProgressUpdate.anchor`
— or, if they are intentionally kept for the coming export/P5 work, say so in the docstring so
the next reader does not delete them.

---

## Test gaps

### T1 · No front-end tests ✔ applied — steps 1 and 2, and step 3 without a browser

**Severity:** High · **Effort:** L · **Area:** Testing
**Review:** ☑ accept ☐ defer ☐ reject

**Where:** `tests/` (13 Python files, zero JS); `static/js/reader.js` (927 lines),
`static/js/panel.js` (846 lines).

**Evidence:** The most intricate logic in the project — selection→block matching, the
whitespace-insensitive wrap, the resume marker, TOC anchoring, discussion state — has no
automated coverage. The only JS guard is an id-existence check
(`tests/test_reader.py:37-49`).

**Impact:** Both High front-end bugs found here (P1-1, P1-2) are statically detectable, and
neither would be caught by the suite. Every future change to `panel.js` relies on manual QA.

**Recommended first steps (value per unit of cost):**

1. Extend the id guard into a **class guard**: collect every `className = "…"` /
   `classList.add("…")` literal in the JS and assert each class has a rule in the stylesheet
   the page loads. Would have caught P1-1.
2. Extract `normalizedIndex`, `offsetToPoint`, `findBlockForText`, `blockElement`,
   `escapeHtml` into a small module and unit-test them in Node (`node --test` + `jsdom`).
3. One Playwright smoke: open a book → select text → 解释说明 (AI stubbed) → 保存 → reload →
   the mark is painted and the toast is visible.

**Applied (2026-10-23) — steps 1 and 2 in full, step 3 without the browser:**

**Step 1, the class guard** (`tests/test_reader.py`). The id guard it extends now also covers
`panel.js`'s `el("…")` lookups and `reader-core.js`; the class guard beside it walks **every page
the app serves** — the library, the reader shell and the highlights view — collects the class
literals from the scripts that page loads (`className = "…"`, `classList.add/remove/toggle/
contains`, and the `class="…"` inside HTML a script builds) and asserts each one has a rule in
the stylesheets that page loads. Two details make it honest rather than decorative:

* **The frame's stylesheet counts.** `reader-highlight`, `hl-*`, `flash` and `reader-resume-line`
  are painted into the book's document, so they are styled by the CSS `reader.js` injects there,
  not by `reader.css`. The guard reads those `const *_CSS = \`…\`` literals as part of the
  reader page's CSS surface — which is what turns "28 class literals, 2 unstyled" into a guard
  with a single exemption.
* **A prefix is expanded, not exempted.** `"reader-highlight hl-" + kind` yields the bare prefix
  `hl-`; the guard expands it against the kinds in `KIND_COLORS` and requires `hl-fact_check`,
  `hl-discussion`, `hl-comment`, `hl-highlight` to be styled. A new highlight kind without a
  colour therefore fails.

One exemption survives, and it is P3-2: `action-link`, the reader panel's 编辑 button, is styled
only in `highlights.css`. The guard also fails when an exemption stops being needed, so fixing
P3-2 forces its removal with a message that says so. Both guards fail loudly if their extraction
stops finding anything (a vacuity check), because a guard that quietly matches nothing is worse
than none.

**Verified by breaking it.** With `.toast.visible` deleted from `reader.css` — the P1-1 state —
the guard reports `['visible']`. With an id typo in `panel.js` (`el("panel-saveX")`) the id guard
reports `['panel-saveX']`, which the pre-T1 guard could not see, since it only read `reader.js`.
With `.action-link` styled (P3-2 as if fixed) the staleness check fires.

**Step 2, the module** (`static/js/reader-core.js` + `tests/js/reader-core.test.js`). The helpers
are out of `panel.js` and `reader.js` and into one file loaded first (and added to
`asset_version`, so the cache-buster covers it):

| Moved | Why it is worth pinning |
|---|---|
| `normalizedIndex`, `offsetToPoint`, `findBlockForText`, `blockElement`, `normalizeText` | The whitespace-insensitive matching that paints a highlight into a book whose extracted text does not match the DOM — the most intricate logic in the project. |
| `escapeHtml` | Now an explicit escape map rather than a `createElement` trick: it also escapes the quotes, so the result is safe in an attribute too. |
| `fileURL` | Takes the slug as an argument instead of closing over it, which is what makes the encoding testable — including the parenthesis quirk that broke the frame-load handler. |
| `clampSize`, `tocKey` | The reader's settings clamp and the TOC's localStorage identity. |

Thirteen `node --test` cases, **no new dependency** — Node's own runner, and a stub document
where one is needed (`blockElement` takes the document it searches as an argument, so a stub
suffices). `tests/test_frontend.py` runs them through pytest and skips cleanly when `node` is
absent, the way `test_corpus.py` skips without `EPUBX_CORPUS`. Two of my own expectations were
wrong when first run and the tests corrected them: the collapsed space in `normalizedIndex` maps
to the *first* whitespace of the run, and `encodeURIComponent` leaves `(`/`)` literal — which is
precisely the quirk `reader.js`'s comment describes.

**Step 3, the flow — without a browser** (`tests/js/panel-flow.test.js` + `tests/js/dom-stub.js`).
Four tests drive the real `panel.js` through its own wiring: clicking 解释说明 in the shell's
context menu, saving, failing to save, and writing a note. They assert the requests the browser
would send (the context halves and never their join — a P1-3 regression guard; the block id and
selection that become the mark), that a successful save sets `#toast` to `toast visible`, and
that a failed one sets `toast visible error` and leaves the save on offer. The stub document is
what T1's step 3 called a browser for; it is honest about the boundary: the text *selection* is
handed in (a real Range needs a real document), and nothing is rendered.

**What is still open, and it needs a decision.** The Playwright smoke itself. There is no usable
browser in this environment — `/usr/bin/chromium-browser` is the snap shim and the snap is not
installed, so the only way to run one here is to add it: `playwright` in the venv plus a ~130 MB
browser download, or a `package.json` with npm's Playwright beside uv. The test would then skip
wherever no browser is installed, as the corpus tests do. Its marginal value over what landed is
*rendering*: that the toast is actually on screen, that the mark is actually painted in the frame,
that layout has not swallowed either. Worth doing deliberately, as its own change — say the word.

---

### T2 · No fixture with a URL-hostile title

**Severity:** Medium · **Effort:** S · **Area:** Testing
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `tests/fixtures.py` (`OPF` title is always "Fixture Book").

**Evidence:** Every upload fixture has a space-and-letters title, so P1-2 cannot surface.

**Fix:** a `write_epub(path, title=…)` parameter (or a second OPF), then assert the library card
hrefs are percent-encoded and that `client.get(href)` does not 404.

**Applied with P1-2 (2026-10-23):** `write_epub(path, title=None)` landed, XML-escaping the title,
and the two tests in `tests/test_library.py` assert exactly the recipe above — the `%23` hrefs and
that every card link answers 200/307 and reaches the book when followed. Left unticked: the
decision is yours, but the work is in the tree.

---

### T3 · No tests on prompt content or save validation

**Severity:** Medium · **Effort:** S · **Area:** Testing
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `tests/test_ai.py` (mocks the service, asserts routing and status only).

**Evidence:** No test asserts what the model is asked, so P1-3 (context dropped) is invisible;
no test asserts `analysis_type` is rejected on `/api/ai/save`, so P2-11 is invisible.

**Fix:** capture the arguments passed to the mocked `fact_check`/`discuss` and assert the
context appears in the prompt; add a 422 case for an unknown `analysis_type` on save.

**Half applied with P1-3 (2026-10-23):** the prompt-content half landed —
`tests/test_ai.py` now stubs `_call` and captures what the model is actually asked, for
`fact_check`, `discussion` and `discussion/start`, plus a no-context case that pins the bare
prompt, and a unit test for `_excerpt`. The 422-on-save half is P2-11's.

**Both halves applied (2026-10-23):** the 422 half landed with P2-11 —
`test_save_rejects_an_unknown_analysis_type` asserts `/api/ai/save` answers 422 for an unknown
kind *and stores nothing*, and `test_a_conversation_turn_cannot_be_a_system_message` asserts a
`system` turn is refused. T3 is done; ticked.

---

### T4 · No cost test for the library render

**Severity:** Low · **Effort:** S · **Area:** Testing
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `tests/test_library.py` (asserts content, not query shape).

**Evidence:** P2-2 (N+1) is a property of the query pattern that a test can pin cheaply.

**Fix:** wrap `sqlite3.connect` with a counter and assert the library page's connection count is
constant as books are added (e.g. upload 5 books, count ≤ 3).

**Applied with P2-2 (2026-10-23):**
`tests/test_library.py::test_the_library_page_costs_one_query_however_many_books` counts
`sqlite3.connect` calls across a five-book render and asserts ≤ 3. It reports 6 against the
pre-P2-2 code and 1 after, which is the assertion T4 asked for.

---

### T5 · No test pins response headers

**Severity:** Low · **Effort:** S · **Area:** Testing
**Review:** ☐ accept ☐ defer ☐ reject

**Where:** `tests/test_book_route.py` (status, media type and body only).

**Evidence:** P2-1/P2-3 are one-line assertions away from being locked in.

**Fix:** assert `Content-Security-Policy: script-src 'none'` and
`X-Content-Type-Options: nosniff` on `/book/{slug}/…`, and that a second GET with
`If-None-Match` returns 304.

**Applied with P2-1 (2026-10-23):**
`tests/test_book_route.py::test_a_book_file_is_safe_to_open_directly_and_to_cache` asserts the
CSP, `nosniff`, the cache lifetime, the ETag and the 304-with-no-body on a chapter URL;
`test_the_validator_changes_when_the_book_does` asserts a re-upload moves the validator.

---

## What is working well (keep doing these)

* **`booksource.py` is exactly the adapter the SPEC promised.** One file names epubx; every
  failure becomes a named string (`open` catches `EpubError`, `BadZipFile`, `OSError`, and a
  final boundary `Exception`); `close()` even makes post-close access benign rather than
  explosive. `test_booksource.py` covers the three footnote shapes the real corpus breaks on.
* **Three tests guard whole classes of bug**, not just one incident — worth copying to the
  front end: the served-asset guards (`test_reader.py`: the id lookup guard, and the class guard
  T1 added beside it), traversal tests at both the
  route and adapter level (`test_book_route.py:64`, `test_booksource.py:119`), and the
  "book progress spans the book, not the chapter" test that pins an actually-reported bug
  (`test_library.py:171`).
* **Sanitisation is in the right place.** Bleach + `markdown-it` with raw HTML off on the
  server, DOMPurify in the browser, and *nothing* on the book path — exactly as the spec
  argues. An AI failure is a 502, never a 200 carrying error text (`ai.py:129-130`).
* **Migrations are honest.** `_ensure_columns` + nullable additions + `ON CONFLICT` upserts
  keep an old database working, and `added_at` surviving a re-upload keeps the shelf stable
  (`database.py:109-139`, `test_library.py:72`).
* **Comments explain *why*, not *what*.** The `bookPrefix` encoding note
  (`reader.js:35-40`), the resume-marker rationale, the quirks-mode scroll measurement
  (`panel.js:766-772`) and the `saveProgress` timer dance are the kind of notes that save the
  next reader a day. The one exception is P3-7, where three of them have gone stale.
* **The design is coherent under pressure.** Model A, the filesystem as storage, "derived,
  never persisted unless recomputable and expensive", and one dependency for EPUB knowledge are
  all visible in the code, not just in the document.

## Deliberate trade-offs treated as intended (not findings)

| Trade-off | Why it is reasonable here |
|---|---|
| `sandbox="allow-same-origin"` | Required for the shell to dress and paint the frame; scripts still cannot run. P2-1 closes the direct-navigation gap the sandbox cannot. |
| Chapter documents are never rewritten | The core bet of the project; it is why footnotes, images and typography just work. |
| One connection per database operation | Fine at one reader and a few hundred books; P2-2/P2-12 are the scale points where that stops being true. |
| A title-derived slug that preserves Unicode | It is what makes a re-upload restore annotations with no migration; P1-2 is about URL safety, not about changing the identity scheme. **Amended by P1-2:** `#` and `%` are slugged out, so a pre-existing title carrying one changes identity on re-upload (see P1-2's "known consequence"). |
| `skip` when `EPUBX_CORPUS` is unset | Correct: CI has no corpus, and the real-book claims stay honest. |
| In-memory provider override | Single-user by design (out of scope). |

---

## Appendix A — Reproduction recipes

### A.1 Toast never appears (P1-1)

```bash
cd /home/tr/projects/ai-reader-2
grep -rn "visible" static/css/     # no match: .toast.visible has no rule
grep -n -A4 "^\.toast {" static/css/reader.css
# .toast { ... opacity: 0; pointer-events: none; transition: ... }
```

In the browser: open a book, stop the server, click 保存 — the panel body shows the error
inline, but the toast at the bottom centre never becomes visible.

### A.2 A `#` in the title breaks the links (P1-2)

The probe used during the review uploads a copy of the fixture EPUB whose `<dc:title>` was
rewritten to `C# Fixture12` into an isolated library, then:

```
upload 200  {'slug': 'C# Fixture12', ...}
card hrefs  href="/read/C# Fixture12", href="/highlights/C# Fixture12"
GET /read/C%23%20Fixture12           -> 307   (correct encoding works)
GET /read/C                          -> 404
GET /highlights/C                    -> 404
```

Minimal equivalent without a script: upload any EPUB whose title contains `#`, then hover the
card's 浏览本书 link and read the status bar.

### A.3 Full suite

```bash
cd /home/tr/projects/ai-reader-2 && .venv/bin/pytest -q
# 109 passed, 3 skipped
```

---

### A.4 Does the context reach the model? (P1-3)

Stub the service's `_call` so the prompt text can be read without a model:

```python
import sys, pathlib, tempfile
sys.path.insert(0, 'tests'); sys.path.insert(0, '.')
import routers
base = pathlib.Path(tempfile.mkdtemp()); (base / 'books').mkdir()
routers.BOOKS_DIR, routers.DB_PATH, routers._db = base / 'books', base / 'db.sqlite', None

import ai_service
seen = []
async def stub(self, prompt, provider='ollama', history=None):
    seen.append(prompt); return '(stub)'
ai_service.AIService._call = stub

from fastapi.testclient import TestClient
import server
client = TestClient(server.app)
client.post('/api/ai/analyze', json={'analysis_type': 'fact_check',
                                     'selected_text': 'SEL', 'context': 'CTX'})
print('selection in prompt:', 'SEL' in seen[-1], '| context in prompt:', 'CTX' in seen[-1])
# -> selection in prompt: True | context in prompt: False
```

Then, for the live A/B, build prompt B from prompt A — same instructions, one block added:

```python
prompt_b = prompt_a.replace(
    selection, f'【上文】…{before}\n【选中的文本】{selection}\n【下文】{after}…', 1)
```

The demo in P1-3 used 自由的窄廊 ch. 3 with `gpt-oss:120b-cloud` (the panel's default provider);
note the app's own client timeout is 60 s (`ai_service.py:70`), so a slow local model can time
out — use a longer timeout for the experiment.

---

## Appendix B — Suggested order of work


**Batch 1 — "the UI stops lying" (≈ half a day, all S):**
~~P1-1 (toast CSS)~~ ✔ applied → ~~P1-2 (slug quoting + sanitising, with T2)~~ ✔ applied →
~~P1-3 (context into prompts, with T3)~~ ✔ applied →
~~P1-6 (save progress on in-frame navigation)~~ ✔ applied → ~~P2-2 (library join)~~ ✔ applied →
~~P2-3 (cache headers, with T5)~~ ✔ applied.

**Batch 2 — "the boundaries hold" (≈ one day):**
~~P2-1 (CSP on book files, with T5)~~ ✔ applied → ~~P2-6 (`get_db` lock)~~ ✔ applied →
~~P2-7 (`setdefault`)~~ ✔ applied → ~~P2-11 (`Literal` validation)~~ ✔ applied → P2-12 (WAL +
`_session`) → ~~P2-4 (word count + test)~~ ✔ applied → ~~P2-9 (`/api/text`)~~ ✔ applied.

**Batch 3 — "the reader is editable and keyboard-complete" (≈ one day, M each):**
~~P1-4 (textarea editing)~~ ✔ applied → ~~P1-5 (frame keydown + menu semantics)~~ ✔ applied →
~~P3-1~~ ✔ applied → ~~P3-2~~ ✔ applied. Batch 3 complete.

**Batch 4 — "the data model stops pretending" (deferred, needs a decision):**
P2-8 (progress ordering) → P2-10 (context-aware painting / block anchors) → P3-15 (remove the
dead surface) → P2-5 (cache refcounts, if the 8-book limit is ever raised).

**Independent:** P3-3 … P3-13 are one-line fixes that can ride along with any batch; P3-14 and
T1 are the two structural investments, best done together when the next feature touches
`panel.js`.
