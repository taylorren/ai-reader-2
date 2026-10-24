# ai-reader-2 — Pitfalls

Every entry here is a bug that **actually shipped**, found by using the app the
way it is deployed — in a container, over the LAN — and not the way the suite
runs it. Each one produced plausible-looking behaviour: no exception, no console
error, nothing in the log, and a feature that simply did not do its job. The
suite was green for both of them.

Read this before changing the front end or the packaging. What the two entries
share is not a subsystem but a *gap*: the deployment is not the development
machine, and every difference that mattered was one the test harness had smoothed
away.

**Evidence base:** the 2.0.0 image, built and smoke-tested in a NAS-shaped
deployment (uid 1000, `./books` and `./data` bind mounts, port 8123); the app
served over `http://192.168.150.60:8123`; a real library and a real `ai-reader`
database carried into it (100 highlights, 100 analyses, 13 progress rows). 159
Python tests, 47 Node tests and 8 browser tests were green through both.

---

## The rule that explains both

> **A test that ran on localhost, against the repo tree, has not run against the
> deployment.**

Four differences did all the damage, and every one of them was invisible in
development:

| Development | Deployment |
|---|---|
| `http://127.0.0.1:8123` — a *secure context* | `http://192.168.…:8123` — not one |
| one filesystem: `temp/` and `books/` inside the repo | two: `/app/temp` in the image layer, `/app/books` a bind mount |
| a `.env` on disk | environment only |
| a stub DOM that supplies whatever the code asks for | the browser that is actually there |

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

## Why the suite was green for both

Neither bug is a hole in coverage — both paths are tested. Both were tested under
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

When adding a feature, run it in the shape it ships in: the container, over the
LAN address, with the volume mounts the README names.

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

1. **Run it where it is deployed before believing it works.** Both bugs above
   passed every test and failed in the container and on the LAN.
2. **When a browser API is involved, ask what the API requires** — a secure
   context, a user gesture, a permission. `navigator.clipboard` needs the first,
   and an insecure origin does not warn you; it simply has no property.
3. **Treat a filesystem boundary as a boundary.** Staging inside the image and
   storing on a mount means cross-device moves, and `os.replace` is not one.
4. **Say what happened, not what was attempted.** The toast claimed
   `已复制到剪贴板` for a copy that never occurred. A helper that returns whether
   it worked costs nothing and turns a silent lie into a message.

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
