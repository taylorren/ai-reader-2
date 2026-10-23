/* The front end's pure helpers — no lookups, no network, no state of their own.

Loaded before reader.js and panel.js (templates/reader.html) and exposed as
`window.ReaderCore`. They live here because this is the logic that has actually
been wrong: the whitespace-insensitive matching that paints a highlight into a
book whose text does not match what the old app extracted, and the frame-URL
encoding that silently failed for any slug with parentheses in it. Both are
pure enough to be tested without a browser — `node --test "tests/js/*.test.js"` — which is
what keeps them from regressing (REVIEW T1).

`blockElement` takes the document it searches as an argument for the same
reason: a stub document is enough to test it. */

window.ReaderCore = (function () {
    "use strict";

    // Text → safe HTML. The DOM-based original (`createElement("div")` +
    // `textContent`/`innerHTML`) escaped only `&`, `<` and `>` — an explicit map
    // also escapes the quotes, which the DOM version left alone because it
    // escapes for text position only. Callers interpolate the result into
    // `innerHTML`, so the strict form is the safe one.
    function escapeHtml(text) {
        return String(text == null ? "" : text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    // Whitespace → single spaces, trimmed. `\s` covers U+3000, the ideographic
    // space a CJK/InDesign export sets blank lines with.
    function normalizeText(text) {
        return (text || "").replace(/\s+/g, " ").trim();
    }

    // A whitespace-insensitive index: the value, plus the source offset each
    // of its characters came from. A row migrated from the old app carries
    // text that app extracted, whose spacing need not match this DOM's —
    // matching the normalised form is what lets those highlights paint.
    function normalizedIndex(text) {
        let value = "";
        const map = [];
        let lastWasSpace = false;
        for (let i = 0; i < text.length; i++) {
            if (/\s/.test(text[i])) {
                if (value && !lastWasSpace) { value += " "; map.push(i); lastWasSpace = true; }
            } else {
                value += text[i];
                map.push(i);
                lastWasSpace = false;
            }
        }
        if (lastWasSpace) { value = value.slice(0, -1); map.pop(); }
        return { value, map };
    }

    // The text node an offset into the concatenated run lands in.
    function offsetToPoint(nodes, offset) {
        let position = 0;
        for (const node of nodes) {
            const length = node.nodeValue.length;
            if (offset <= position + length) {
                return { node, offset: offset - position };
            }
            position += length;
        }
        return null;
    }

    // The smallest block that contains the selection is the anchor.
    function findBlockForText(blocks, text) {
        let best = null;
        for (const block of blocks) {
            if (block.text.includes(text) &&
                (!best || block.text.length < best.text.length)) {
                best = block;
            }
        }
        return best;
    }

    // The element in the frame's own document that carries the block's text.
    // Compared normalised, because the served document's whitespace is the
    // book's, not the extractor's.
    function blockElement(doc, block) {
        const target = normalizeText(block.text);
        if (!target) return null;
        const candidates = doc.querySelectorAll(
            "p, h1, h2, h3, h4, h5, h6, blockquote, pre, dt, dd, li, td");
        for (const node of candidates) {
            if (normalizeText(node.textContent) === target) return node;
        }
        return null;
    }

    // A book-internal path and anchor → the URL the frame loads. Each path
    // segment is encoded separately so the separators survive; the anchor is
    // encoded too, because a heading's id can hold anything.
    //
    // `encodeURIComponent` leaves "(" and ")" literal while the server's
    // Python `quote` escapes them as %28/%29 — which is why the shell compares
    // *decoded* paths (see bookPrefix in reader.js) and why this encoding is
    // pinned by a test: an encoded-form comparison silently failed for every
    // translated title with parentheses in it.
    function fileURL(slug, path, anchor) {
        const prefix = "/book/" + encodeURIComponent(slug) + "/";
        const encoded = path.split("/").map(encodeURIComponent).join("/");
        return prefix + encoded + (anchor ? "#" + encodeURIComponent(anchor) : "");
    }

    // The reading font size, clamped to what the sheet can carry; anything
    // unusable falls back to the default.
    function clampSize(size) {
        return Math.max(12, Math.min(48, Number.isFinite(size) ? size : 19));
    }

    // A TOC node's identity in localStorage. The label is part of it because a
    // book can name two sections with the same href and anchor.
    function tocKey(node) {
        return (node.href || "") + "|" + (node.anchor || "") + "|" + (node.label || "");
    }

    return {
        escapeHtml,
        normalizeText,
        normalizedIndex,
        offsetToPoint,
        findBlockForText,
        blockElement,
        fileURL,
        clampSize,
        tocKey,
    };
})();
