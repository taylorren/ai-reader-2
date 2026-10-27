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
    //
    // A boundary belongs to the node it closes — offset 3 of "abc"+"def" is the
    // *end* of "abc", not the start of "def" — which is what a range's end
    // wants. A range's *start* at that same offset must not sit inside the
    // closing node: when an element splits the two, a range that begins at the
    // end of the inline element's text *partially selects* that element, and
    // `Range.surroundContents` refuses it — so the mark was stored and then
    // never painted (项狄传: `<small>希波克拉底</small>Ars longa，——和Vita
    // brevis`). `preferNext` resolves that boundary forward, into the node the
    // selection really begins in, which is what the wrap asks for.
    function offsetToPoint(nodes, offset, preferNext) {
        let position = 0;
        for (let i = 0; i < nodes.length; i++) {
            const length = nodes[i].nodeValue.length;
            if (offset < position + length) {
                return { node: nodes[i], offset: offset - position };
            }
            if (offset === position + length) {
                if (preferNext && i + 1 < nodes.length) {
                    return { node: nodes[i + 1], offset: 0 };
                }
                return { node: nodes[i], offset: length };
            }
            position += length;
        }
        return null;
    }

    // The text nodes under an element, in document order: the run a range
    // offset is measured against.
    function textNodes(doc, root) {
        const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        const nodes = [];
        let node;
        while ((node = walker.nextNode())) nodes.push(node);
        return nodes;
    }

    // Where a range point sits in the concatenated text of those nodes — or null
    // when it is not one of them, which is what a range starting at an element
    // boundary looks like.
    function textOffset(nodes, node, offset) {
        let position = 0;
        for (const candidate of nodes) {
            if (candidate === node) return position + offset;
            position += candidate.nodeValue.length;
        }
        return null;
    }

    // How many characters at the end of `text` `wanted` also ends with.
    function commonSuffix(text, wanted) {
        let matched = 0;
        while (matched < text.length && matched < wanted.length &&
               text[text.length - 1 - matched] === wanted[wanted.length - 1 - matched]) {
            matched += 1;
        }
        return matched;
    }

    // How many characters at the start of `text` `wanted` also starts with.
    function commonPrefix(text, wanted) {
        let matched = 0;
        while (matched < text.length && matched < wanted.length &&
               text[matched] === wanted[matched]) {
            matched += 1;
        }
        return matched;
    }

    // Where a highlight's text sits in `full`, as `{at, length}` in `full`'s own
    // coordinates — or null when the text is not in it at all.
    //
    // A block is an anchor, but not a precise one: a paragraph can repeat a
    // sentence, and wrapping the first occurrence paints the wrong one — the
    // exact ambiguity the context saved with the selection exists to resolve
    // (REVIEW P2-10). So every occurrence is scored by how well the text around
    // it matches that context, and the best one wins.
    //
    // With no context, or a context that matches nothing (a row imported from
    // the old app, a book re-uploaded since), every candidate scores zero and
    // the first wins: the behaviour before this existed, kept as the fallback.
    // A tie also keeps the first, so the answer is deterministic.
    //
    // Compared whitespace-insensitively like every other match here: the
    // extractor's spacing and the served document's need not agree.
    function findTextRange(full, text, before, after) {
        const haystack = normalizedIndex(full);
        const needle = normalizedIndex(text).value;
        if (!needle) return null;
        const wantedBefore = normalizedIndex(before || "").value;
        const wantedAfter = normalizedIndex(after || "").value;

        let best = -1;
        let bestScore = -1;
        let at = haystack.value.indexOf(needle);
        while (at >= 0) {
            // Both sides normalised before comparing: the run either side of an
            // occurrence is separated from it by a space, while the stored
            // context was trimmed when it was captured — compared raw, a
            // *correct* context would score zero on its last character.
            const score =
                commonSuffix(normalizeText(haystack.value.slice(0, at)), wantedBefore) +
                commonPrefix(normalizeText(haystack.value.slice(at + needle.length)),
                             wantedAfter);
            if (score > bestScore) {
                bestScore = score;
                best = at;
            }
            at = haystack.value.indexOf(needle, at + 1);
        }
        if (best < 0) return null;
        const start = haystack.map[best];
        const end = haystack.map[best + needle.length - 1] + 1;
        return { at: start, length: end - start };
    }

    // The block's text either side of a range, normalised — the context a
    // selection travels with.
    //
    // Read from the document rather than from the extractor's copy of the block,
    // because only the document knows *which* occurrence the reader selected:
    // `block.text.indexOf(selection)` answers "the first one", so a paragraph
    // repeating a sentence stored the other occurrence's surroundings — and the
    // mark then painted that other one (REVIEW P2-10). Null when the range's ends
    // are not text nodes of the block; the caller falls back from there.
    function contextAround(doc, root, range, span) {
        const nodes = textNodes(doc, root);
        const start = textOffset(nodes, range.startContainer, range.startOffset);
        const end = textOffset(nodes, range.endContainer, range.endOffset);
        if (start == null || end == null) return null;
        const full = nodes.map((node) => node.nodeValue).join("");
        return {
            before: normalizeText(full.slice(Math.max(0, start - span), start)),
            after: normalizeText(full.slice(end, end + span)),
        };
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

    // The id of the block a reader can see at `line` — a y offset inside the
    // frame's viewport — which is the block a reading position is anchored to
    // (REVIEW P2-10). A percent moves when the text reflows, a font-size change
    // or a window resize; a block lands on the same paragraph.
    //
    // Matched by text like every other block lookup here, because the served
    // document carries no ids from the extractor. A node the blocks do not know
    // — an image, an uncaptioned figure — is stepped over rather than ending the
    // search, so a picture between two paragraphs cannot cost the anchor.
    function firstVisibleBlockId(blocks, doc, line) {
        const ids = new Map();
        for (const block of blocks || []) {
            const key = normalizeText(block.text);
            if (key && !ids.has(key)) ids.set(key, block.id);
        }
        if (!ids.size) return null;
        const candidates = doc.querySelectorAll(
            "p, h1, h2, h3, h4, h5, h6, blockquote, pre, dt, dd, li, td");
        for (const node of candidates) {
            // `<=`: a block whose bottom edge is exactly on the line is
            // entirely above it, and nothing of it is on screen.
            if (node.getBoundingClientRect().bottom <= line) continue;
            const id = ids.get(normalizeText(node.textContent));
            if (id) return id;
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
        textNodes,
        textOffset,
        findTextRange,
        contextAround,
        findBlockForText,
        blockElement,
        firstVisibleBlockId,
        fileURL,
        clampSize,
        tocKey,
    };
})();
