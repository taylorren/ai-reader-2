# Vendored front-end libraries

Copied from jsDelivr and served from `/static/vendor/`, so the reader has no
runtime CDN dependency: it works offline and behind a slow or blocked CDN.
Still no build step and no `node_modules` — these are the published bundles
as they ship.

| File | Version | Licence | Source |
|---|---|---|---|
| `vue.global.prod.js` | 3.5.13 | MIT | https://cdn.jsdelivr.net/npm/vue@3.5.13/dist/vue.global.prod.js |
| `marked.min.js` | 11.1.1 | MIT | https://cdn.jsdelivr.net/npm/marked@11.1.1/marked.min.js |
| `purify.min.js` | 3.1.6 | Apache-2.0 | https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js |
| `temml/temml.min.js` | 0.14.0 | MIT | https://cdn.jsdelivr.net/npm/temml@0.14.0/dist/temml.min.js |
| `temml/Temml-Local.css` | 0.14.0 | MIT | https://cdn.jsdelivr.net/npm/temml@0.14.0/dist/Temml-Local.css |
| `temml/Temml.woff2` | 0.14.0 | MIT | https://cdn.jsdelivr.net/npm/temml@0.14.0/dist/Temml.woff2 |

`temml/` is the one bundle a page does not load up front: the shell fetches it —
and its stylesheet — the first time a chapter turns out to carry LaTeX
(`reader.js`, `ensureMath`), so a library of ordinary prose never pays for it. It
converts LaTeX to **MathML**, which is what a browser already renders for a book
that ships MathML, so a formula stays *text*: selectable, searchable, and — since
the shell keeps each formula's source — what 复制文本 puts on the clipboard is the
LaTeX the book wrote rather than the characters the browser drew. The `-Local`
stylesheet is the one that uses locally installed math fonts, and the woff2
beside it is the single font it declares (script capitals); it is served from
this directory so that its relative `url()` resolves. sha256
`56b4338176d39170692503b8b7ec630d3edf8e10861895658deb74aefb66af9d` (JS),
`544f4e3fee4c36f4568e4f145fa626dc9573c5f4c96c523aadcc433c3989a239` (CSS),
`fc70501355ae6d38ff0b80f825af153557d5f2f474198d6b9b7dd2d3a291a0cc` (font).

To upgrade: download the new bundle over the file, update the version here and
the version note in `SPEC.md`, and check the templates still name the file
(`/static/vendor/…`).
