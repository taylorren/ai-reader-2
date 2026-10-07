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

To upgrade: download the new bundle over the file, update the version here and
the version note in `SPEC.md`, and check the templates still name the file
(`/static/vendor/…`).
