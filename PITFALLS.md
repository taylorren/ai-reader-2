# ai-reader-2 — Pitfalls

Every entry here is a bug that **actually shipped**, found by using the app the
way it is deployed — in a container, over the LAN, with a real book — and not the
way the suite runs it. Each one produced plausible-looking behaviour: no
exception, no console error, and a feature that simply did not do its job — or,
in entry 3's case, a message that named the symptom and not the cause. The suite
was green for all of them.

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
