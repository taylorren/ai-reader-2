# ai-reader-2 — Pitfalls

Every entry here is a bug that **actually shipped**, found by using the app the
way it is deployed — in a container, over the LAN, with a real book — and not the
way the suite runs it. Each one produced plausible-looking behaviour: no
exception, no console error, and a feature that simply did not do its job — or,
in entries 3 and 4's case, a message that named the symptom and not the cause.
The suite was green for all of them.

Read this before changing the front end or the packaging. What the entries share
is not a subsystem but a *gap*: what the app runs against — the machine, the
book — is not what the tests run against, and every difference that mattered was
one the test harness had smoothed away.

**Evidence base:** the 2.0.0 image, built and smoke-tested in a NAS-shaped
deployment (uid 1000, `./books` and `./data` bind mounts, port 8123); the app
served over `http://192.168.150.60:8123`; a real library and a real `ai-reader`
database carried into it (100 highlights, 100 analyses, 13 progress rows). 159
Python tests, 47 Node tests and 8 browser tests were green through both.

---

## The rule that explains both

> **A test that ran on localhost, against the repo tree, has not run against the
> deployment.**

Five differences did all the damage, and every one of them was invisible in
development:

| Development | Deployment |
|---|---|
| `http://127.0.0.1:8123` — a *secure context* | `http://192.168.…:8123` — not one |
| one filesystem: `temp/` and `books/` inside the repo | two: `/app/temp` in the image layer, `/app/books` a bind mount |
| a `.env` on disk | environment only |
| a stub DOM that supplies whatever the code asks for | the browser that is actually there |
| fixtures written for the shape in mind — a paragraph is prose in one text node | a real book's paragraph: prose interleaved with `<small>`, `<sup>`, `<a>` |

---

## 1. 复制文本 copied nothing, and said nothing

**Provenance: reported by the reader, on the deployment that exists.** Not by a
test and not by a crash: select text, choose 复制文本, and the clipboard is
unchanged. No toast, no console error, no failed request — the action had run
and returned.

```js
navigator.clipboard.writeText(selection.text);   // ← undefined on a LAN origin
toast("已复制到剪贴板");
```

`navigator.clipboard` is a **secure context** API: it exists on `https://` and on
`localhost`, and is absent on plain `http://` served from an IP. Measured in
Chromium on the machine this was reported from:

```
http://127.0.0.1:42611        isSecureContext=True   typeof navigator.clipboard='object'
http://192.168.150.60:38669   isSecureContext=False  typeof navigator.clipboard='undefined'
```

So the call raised `TypeError: navigator.clipboard is undefined` inside an `async`
handler — a rejected promise, swallowed by the browser, with `toast()` never
reached. The feature failed precisely where it is used: this is a LAN app on
plain http.

**Fix:** `copyText()` in `static/js/panel.js` tries the API and falls back to a
staging textarea copied by `document.execCommand("copy")`, and returns whether
the text really reached the clipboard, so the caller can report a failure
(`复制失败，请手动复制`) instead of a copy that never happened. The reference
implementation (`ai-reader`) had this fallback; the rewrite dropped it.

**What pins it:** four cases in `tests/js/panel-flow.test.js` — the API, an absent
API, a refused API, and a copy that did not happen — and
`tests/test_browser.py::test_the_copy_action_copies_where_the_clipboard_api_is_absent`,
which makes a real selection in a real browser with the property removed.

**Lesson:** an API that is *absent* fails differently from one that is *denied*.
There is no error to catch in the first case, only a property that is not there,
so an unguarded call to a secure-context API is a silent no-op on http — and the
toast then lies about it.

## 2. The container could not accept an upload — and only the container

**Provenance: found by smoke-testing the image, before it was published.** The
first upload answered 500.

```
OSError: [Errno 18] Invalid cross-device link:
  '/app/temp/c19e50b901bf4e9fb485141270208d91.epub'
  -> '/app/books/Fixture Book/Fixture Book.epub'
```

`os.replace` is atomic and needs **one** filesystem. In the container there are
two: `/app/temp` is in the image's writable layer and `/app/books` is a bind
mount — the deployment shape the README documents. On a host both are
`<repo>/temp` and `<repo>/books`, which is why the dev server and every test
agreed that nothing was wrong: the same code cannot see the difference until the
two paths are on different devices.

**Fix:** `_move_into_place()` in `routers/library.py` keeps `os.replace`, and on
`EXDEV` copies into a `.part` file **beside the target** and renames that into
place — atomic again, on the filesystem that matters, and it still overwrites a
book in place on a re-upload.

**What pins it:** `tests/test_library.py::test_an_upload_survives_a_cross_filesystem_move`
(which makes `os.replace` raise `EXDEV`, as the container's kernel does) and the
image smoke test, which uploads through the real thing.

**Lesson:** `os.replace` and `os.rename` are same-filesystem operations. A bind
mount is a different filesystem, so "move the staged file into place" is a
cross-device move whenever staging belongs to the container and storage belongs
to a volume.

---

## 3. A highlight saved, and never appeared — in one book

**Provenance: reported by the reader, on a real book.** 项狄传, volume 5 chapter
34: select `Ars longa，——和Vita brevis`, 添加笔记, save — 「已保存到数据库」, the
row is in the database, the API answered 200, and no mark is on the page. The
shell did say so, in passing: 「本章有 1 条高亮未能定位」.

The phrase sits where it does because of an inline element:

```html
<p class="indent">一开始，他便对医界泰斗<small class="calibre8">希波克拉底</small>Ars longa，——和Vita brevis<sup class="calibre9">…93</sup>的哀怨…</p>
```

Painting maps a stored mark back onto the served document: the block's text nodes
are concatenated, the selection is found in that run, and the two offsets become
a `Range`. `offsetToPoint` resolved a boundary to the node it *closes* — correct
for a range's end, wrong for its start. The selection begins exactly where
`</small>` ends, so the range began at the end of the text node *inside*
`<small>`; a range that starts inside an element and ends outside it **partially
selects** that element, and `Range.surroundContents` refuses it with
`InvalidStateError`. The wrap caught that and returned false, so the mark was
left unpainted — with the row stored and a `console.warn` that named the symptom
(1 highlight not located) and not the cause.

**Fix:** `offsetToPoint(nodes, offset, preferNext)` in `static/js/reader-core.js`
resolves a boundary forward when the caller asks it to, and the wrap
(`wrapText`, `static/js/panel.js`) asks for that on the range's *start* only. The
end keeps the boundary's default — it belongs to the node it closes, which is
where a range legitimately ends.

**What pins it:** `tests/js/reader-core.test.js` ("offsetToPoint can resolve a
boundary forward, for a range start") and
`tests/test_browser.py::test_a_mark_that_begins_after_an_inline_element_is_painted`,
which uploads `tests/fixtures.py`'s `write_inline_epub` — the same shape in
English — and times out waiting for the mark when the bias is removed.

**Lesson:** a synthetic paragraph is prose in one text node. A real book's is
prose interleaved with `<small>`, `<sup>`, `<a>` — and a mark that begins right
after one of them starts on a boundary no fixture here had. `surroundContents`
is the part of the browser's range API that cares, and it fails by throwing, not
by doing something visible.

---

## 4. One selection, highlighted twice — a mark that doubled, then vanished

**Provenance: reported by the reader, on a real book.** 自由的窄廊, the
introduction's heading `受制約的巨靈與持續的競爭紅皇后效應` — two phrases the
book runs together, so the same five characters were selected twice. The row is
in the database, the API answered 200, the app said 已保存到数据库 — and the
reading pane showed one mark where two were saved. Marking it a third time
changed nothing at all, and the only sign was the passing toast
「本章有 N 条高亮未能定位」.

Painting is not idempotent. `paint()` walks the chapter's highlights and wraps
each one's text in a `<mark>`, on a document that already carries the marks the
earlier ones made — and wrapping text that is already wrapped fails in two
different ways, neither of them loudly:

```html
<!-- after the first: -->        <h3>受制約的巨靈與持續的競爭<mark data-highlight-id="55">紅皇后效應</mark></h3>
<!-- after the second: -->       <mark data-highlight-id="55"><mark data-highlight-id="56">紅皇后效應</mark></mark>
<!-- and the third threw: -->    InvalidStateError: The Range has partially selected a non-Text node
```

* the second wrap's range lands on the text node the first mark now holds, so
  `surroundContents` builds the new mark **inside** the old one. Both paint the
  same pixels — one band at double the tint — and only the innermost answers a
  click: the reader sees one highlight where the app says two;
* `surroundContents` leaves an **empty text node** behind inside the mark it
  built. The third wrap's range begins in that node and ends inside the nested
  mark, so the nested mark is *partially contained* in the range — an element
  holding one end of it but not the other — and the browser refuses it.
  `wrapText` caught that and returned false: stored, never painted, and counted
  in 「本章有 N 条高亮未能定位」.

**Fix:** `ReaderCore.markPieces` (`static/js/reader-core.js`) cuts a located run
into one piece per text node it covers and names the mark each piece already sits
inside. `wrapText` (`static/js/panel.js`) wraps the whole run in one range as
before, and falls back to those pieces when a piece is already marked or the
browser refuses the range. A piece that is already inside a mark is *shared*:
`shareMark` records the new id on that mark (so 在书中定位 finds it by any of the
ids it stands for) and makes the newest highlight the one a click opens — which
is what the nested mark used to be. One mark therefore stands for every highlight
on that text, and nothing is reported as unlocated.

The same fallback paints a shape that never painted at all: a selection that
**straddles** an inline element — it begins inside `<small>Hippocrates</small>`
and ends outside it, or the reverse. Entry 3's forward bias rescues only a
boundary that lands exactly at a text node's end; one that ends mid-element is a
partially contained element no bias can fix, and such a run is now wrapped one
text node at a time (two marks, both of them the highlight's).

**What pins it:**
`tests/test_browser.py::test_a_selection_highlighted_twice_is_one_mark_and_is_not_lost`
(three rows on one selection: one mark carrying the newest id and all three ids,
nothing reported as unlocated, and 在书中定位 reaching it by the *oldest* id),
`::test_a_highlight_that_straddles_an_inline_element_is_painted` (two marks, both
the highlight's, spelling out the saved text between them), and the `markPieces`
unit test in `tests/js/reader-core.test.js`.

**Lesson:** a painting pass is a *set* operation over a document it has already
painted — the second call sees the first's output. Ask what a re-run does to the
DOM, not only what a first run does: `surroundContents` nests rather than
throwing, so the damage stays invisible until a third mark arrives and throws
somewhere else entirely.

---

## 5. A contents entry for a section did nothing at all

**Provenance: reported by the reader, on a real book.** 自由的窄廊, chapter one,
9 / 42: clicking 多元化，而非歷史的終結 in the contents left the reading pane exactly
where it was — measured `scrollY 29050 → 29050` — and the sidebar lit the
chapter's own entry, 1 歷史如何終結？, for the whole of the chapter. No error, no
toast, no failed request: the click had run and returned.

The book's headings carry no `id`. Its contents names only its chapters, so
epubx derives the sections inside each chapter from the document's own headings
— and takes each entry's label *from the heading's own text*, leaving `anchor:
None` because there is no id to point at:

```
OEBPS/ch1.xhtml   <h3>多元化，而非歷史的終結</h3>       ← no id
{"label": "多元化，而非歷史的終結", "href": "OEBPS/ch1.xhtml", "anchor": null}
```

Two lines of the shell then had nothing to work with, and each failed
differently:

```js
if (node.anchor) link.dataset.anchor = node.anchor;   // no fragment: no data-anchor
if (index === BOOK.index && !anchor) return;          // …so the same-chapter click returns
const links = tocList.querySelectorAll(`a[data-anchor][data-path="…"]`);  // measures nothing
```

* the click was treated as a *chapter* click — already here, nothing asked for,
  return — so the frame never moved;
* `frameAnchorInView` measured only entries carrying a fragment, so of the
  chapter's fourteen entries it could only ever find none, and the highlight
  fell back to the chapter's own entry for every page of the chapter.

**It was not one book.** Measured over the library: 397 in-chapter entries with
no id — 自由的窄廊 175, God Created the Integers 134, Death of Caesar 88 — and
every single one names a heading whose normalised text is the entry's own label
(no label repeats inside a document). Books whose headings *do* carry ids
(项狄传 343 entries, Math Formula Test 9) were fine, which is why this looked
like a single book's oddity rather than a missing case: the ids were the
assumption, and the fixtures had them.

**Fix:** the label *is* the locator. `ReaderCore.headingForLabel(doc, label)`
(`static/js/reader-core.js`) finds the heading whose normalised text is the
entry's label, and `frameTargetElement` (`static/js/reader.js`) resolves an entry
either way — the id the book gave the heading, or the heading its label names. A
click inside the chapter on screen is now a `scrollIntoView` on that element
(the same move the footnote popup's 在注释处打开 already made, and for the same
reason: re-assigning `frame.src` with only a new fragment does not move every
browser); an entry in another chapter carries itself across the load
(`pendingEntry`), and `onFrameLoad` aims the frame after the saved position has
been restored — which is about the chapter the reader left, not the heading they
asked for. `frameTargetInView` measures both kinds of entry, so the highlight
follows the section being read; a heading the frame cannot bring up to the
reading line — the chapter's last section, with less than a screenful after it —
is taken as the entry being read once the frame has reached its end.

An entry that names a heading *inside* the document its parent names is the only
one given a label target: the entry that names the document itself keeps its
meaning (the fallback when nothing is above the reading line), and a click on it
still does nothing, because there is nothing more specific to point at.

**What pins it:**
`tests/test_browser.py::test_a_contents_entry_for_a_section_without_an_id_scrolls_the_chapter`
(the heading lands at the top of the frame, the entry is `.current`, and a click
on the chapter's own entry does not move the frame),
`::test_a_contents_entry_without_an_id_loads_its_chapter_and_lands_on_the_section`
(the other chapter is loaded *and* the section reached — with both chapters
naming their sections alike, so the lookup has to happen in the document that
arrived), `::test_the_contents_highlight_follows_a_section_that_has_no_id` (the
heading just above the reading line, and then the end of the chapter, where the
heading is *below* the line and the entry must still be the one lit), the
`write_unanchored_epub` fixture — a book whose headings carry no id at all, the
shape no fixture had — and `headingForLabel`'s unit tests.

**Lesson:** a heading without an id is not a target that does not exist, it is a
target whose *name* is its text — and the outline had already told us so, since
the label it derives is that very text. Ask what the book carries, not what the
outline promised: every fixture here gave its headings ids, and 175 of one real
book's entries were therefore unreachable in a way no test could see.

---

## 6. A book stopped recording where the reader was — silently, and for good

**Provenance: reported by the reader, on a real book.** 自由的窄廊: after a
session in chapter one, every return landed on the same 88%. Read on, close,
reopen — 88% again. The row was in the database, `/api/progress` answered 200,
the client logged nothing. The position was simply never written again.

Progress writes carry a sequence so that the save for the chapter a reader just
left cannot land after the one for the chapter they are in and move the stored
position *backwards* (REVIEW P2-8). The guard is
`WHERE excluded.seq = 0 OR excluded.seq >= reading_progress.seq`, and the client's
sequence is `Math.max(counter + 1, Date.now())` — a timestamp, near 1.79e12. This
book's row held **1e15**, written by a manual probe against the live app: an
`httpx.post` to `/api/progress` seeding the position (`chapter_index 8,
scroll_percent 88.0, block_id c0008/b0238`) with a sequence no client could beat,
so that the running reader could not overwrite it while the resume was checked.
It is the same trick `tests/test_browser.py` uses (`seq=10 ** 15`) — but that
test writes to an *isolated* database, and the probe wrote to the library. Every
write the reader made was therefore older than the stored one, and refused, for
ever:

```
stored now                    : scroll 88.0  block c0008/b0238  seq 1000000000000000
after client seq=1793351087248: scroll 88.0  block c0008/b0238  seq 1000000000000000   # unchanged
after seq=1e15+1              : scroll 12.0  block c0008/b0012  seq 1000000000000001   # accepted
```

The client could not recover on its own, because it had no way to *learn* that
value: the shell handed it the position's percent and block, never the sequence
the position was ordered by. The failure was total and invisible — the stored
position stayed at whatever the last accepted write had said, and no amount of
reading moved it.

**Fix:** the shell hands the client the sequence it has to outrank. `saved_seq`
joins `saved_percent`/`saved_block_id` in `window.BOOK` (`shell_context`,
`routers/reader.py`), and `progressSeq` in `static/js/reader.js` starts at
`Number(BOOK.saved_seq) || 0` rather than 0 — so a session's first write is above
whatever the row holds, whatever that is. The guard keeps its meaning (a
genuinely older write is still refused) and becomes self-healing: the row above
was repaired by the next scroll, with no data surgery. It also covers a client
whose clock runs behind the server's, which the old code would have refused for
as long as the skew lasted.

**What pins it:**
`tests/test_reader.py::test_the_shell_hands_the_client_the_sequence_it_must_outrank`
(the sequence reaches `window.BOOK` on the position's chapter *and* on another —
it orders the book's writes, not the chapter's), `tests/js/reader-shell.test.js`
("the first write outranks the sequence the server already holds": a stored 1e15
and a write above it), and
`tests/test_settings.py::test_an_older_progress_write_cannot_move_the_reader_backwards`
(the guard still refuses a straggler).

**Lesson:** an ordering token the *client* generates, used as a guard on the
*server*, must be one the client can always beat. A stored value out of the
client's reach does not fail loudly — it turns every later write into a silent
no-op, which is the worst shape a save can take. And a probe that *pins* state to
observe behaviour has to run against the isolated library: run by hand against the
real one, its "pass" (the reader really could not move the position) is
indistinguishable from the book never saving again.

---

## Why the suite was green for all of them

None of these is a hole in coverage — every path is tested. Each was tested under
an assumption that held only on the machine running the tests:

- **The origin.** Every Python and browser test serves the app from `127.0.0.1`,
  which *is* a secure context; the address it is deployed on is not. Closed: the
  browser test removes `navigator.clipboard` (all an insecure context does), and
  the stub DOM can model the real thing — `createPage({clipboard: false})` for an
  origin with no API, `{clipboard: "denied"}` for one that refuses the write —
  instead of always supplying a clipboard no LAN browser has.
- **The filesystem.** Tests run in a single directory tree. Closed: the upload
  test makes `os.replace` fail the way the container's kernel does, and the image
  is smoke-tested by running it — `docker run`, upload, read a chapter, check
  `/data`.
- **The environment.** A container has no `.env` by design; testing the image is
  how the message in the next section was found.
- **The book.** Every fixture paragraph here is prose in a single text node, so
  every mark begins and ends inside one. Closed: `write_inline_epub` puts an
  inline element where a mark can start against it, and a browser test seeds the
  mark there — the shape a real book has and a fixture had not.

When adding a feature, run it in the shape it ships in: the container, over the
LAN address, with the volume mounts the README names — and against a real book,
not only the fixtures.

## Near misses (caught before shipping, recorded for the same reason)

- **`READER_DB` defaulted inside the image.** `routers/app_state.py` puts the
  database at `BASE_DIR/reader_data.db`, which is `/app/reader_data.db` in the
  container — every rebuild would have taken the highlights with it. The image
  sets `READER_DB=/data/reader_data.db`. A container's writable layer is not
  storage.
- **A container with no `.env` announced "AI features will not work"** while
  compose was supplying the endpoint through the environment. The message now
  says what is true — `AI settings must come from the environment` — because in a
  container the environment *is* the configuration.
- **A validation artifact faked a failure.** The health check reported
  `unhealthy` for a container that was serving: the throwaway Dockerfile used to
  build behind a proxy had `ENV HTTP_PROXY` in the *runtime* stage, and
  `urllib.request.urlopen` honours it, so the check asked a proxy that does not
  exist inside the container. Read the artifact that produced a failure before
  believing it.
- **Drawing a book's LaTeX changes what the document says.** The shell converts a
  book's formulas into the frame's own document, so `$x = \frac{a}{b}$` becomes
  the MathML the browser draws. Every block lookup in `reader-core.js` compares
  text against what the library extracted — and that comparison is what anchors a
  highlight and the reading position — so a paragraph holding a formula stopped
  matching the moment it was converted: measured `matched` before the pass,
  `null` after it. The fix is to keep the source beside the formula (`data-source`
  on each converted span) and read it back (`ReaderCore.mathText`), which restores
  the match exactly — and which 复制文本 uses too, so a reader who copies a formula
  gets the LaTeX the book wrote instead of the characters the browser drew from
  it. Pinned by
  `tests/test_browser.py::test_the_shell_draws_a_books_latex` (the source is gone
  from the document's text and the block lookup matches anyway),
  `::test_copying_a_selection_carries_the_formula_source`, and the `mathText` unit
  tests.
- **A chapter that loads before the shell's own scripts is never wired.** The
  frame sits *above* the shell's scripts in `templates/reader.html`, so a chapter
  small enough to arrive first fires its `load` event before `reader.js` has
  attached the listener — and then the listener never runs for that chapter at
  all: no paper sheet, no saved highlights, no reading position, and (once math
  was added) formulas still as source. Found while testing math rendering, where
  it reproduced on the first page load roughly one time in eight and looked
  exactly like a renderer bug; the diagnostic that settled it was a `load`-handler
  log that never appeared. The footnote/image wiring already worked around this
  race at init; `onFrameLoad` is now guarded per document and asked for at init
  too, so the rest of the wiring cannot be missed. Pinned by
  `tests/test_browser.py::test_a_chapter_that_loads_before_the_shell_is_still_wired`,
  which *forces* the race by delaying `reader.js` instead of waiting for it.

## How to avoid adding to this list

1. **Run it where it is deployed before believing it works.** All three bugs
   above passed every test and failed in the container, on the LAN, or on a real
   book.
2. **When a browser API is involved, ask what the API requires** — a secure
   context, a user gesture, a permission. `navigator.clipboard` needs the first,
   and an insecure origin does not warn you; it simply has no property.
3. **Treat a filesystem boundary as a boundary.** Staging inside the image and
   storing on a mount means cross-device moves, and `os.replace` is not one.
4. **Say what happened, not what was attempted.** The toast claimed
   `已复制到剪贴板` for a copy that never occurred. A helper that returns whether
   it worked costs nothing and turns a silent lie into a message.
5. **Ask what the DOM looks like in a real book, not in the fixture.** A
   paragraph here is one text node; a paragraph there is prose between `<small>`
   and `<sup>`. A range API — `surroundContents` — is where that difference
   surfaces, and it throws rather than telling anyone.
6. **A missing id is not a missing target.** A book's headings may carry none at
   all, and its contents then names a section by the heading's own text — the
   very text the outline took the label from. Look for the identity the book
   *does* carry before concluding there is nothing to point at (entry 5).

---

## Related documents

- **epubx's pitfalls** — the EPUB-format traps one layer down, same genre, and
  where most of this project's format knowledge actually lives:
  <https://github.com/taylorren/epubx/blob/main/PITFALLS.md>.
- **`ai-reader`'s `TECHNICAL_CHALLENGES.md`** — the predecessor's record, most of
  it about a world ai-reader-2 deleted (reader3's parser, `book.pkl`, the upload
  subprocess): <https://github.com/taylorren/ai-reader/blob/master/TECHNICAL_CHALLENGES.md>.
- **`REVIEW.md`** — this app's code review, its findings, and the "After the
  review" section where the two bugs above are recorded with their evidence.
- **`SPEC.md`** — the design; its P5 milestone tracks the packaging these bugs
  came out of.
