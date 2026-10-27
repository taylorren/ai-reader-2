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
    // book's, not the extractor's — and through `mathText`, so a formula the
    // shell rendered is read as the source it was written as rather than as the
    // characters it draws.
    function blockElement(doc, block) {
        const target = normalizeText(block.text);
        if (!target) return null;
        const candidates = doc.querySelectorAll(
            "p, h1, h2, h3, h4, h5, h6, blockquote, pre, dt, dd, li, td");
        for (const node of candidates) {
            if (normalizeText(mathText(node)) === target) return node;
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
            const id = ids.get(normalizeText(mathText(node)));
            if (id) return id;
        }
        return null;
    }

    /* ---- LaTeX: what to render, and what the document then says ----

    A book's formulas are often LaTeX, and LaTeX is only text: nothing renders
    it by itself, and the reader's frame is sandboxed without `allow-scripts`,
    so a MathJax a book ships can never run (SPEC.md, the trade-off this
    closes). The shell renders it instead — reader.js, `renderMathInFrame` —
    and these are the two halves of that worth testing without a browser: which
    spans are math at all, and what the document *says* once they are drawn. */

    // The delimiters a book writes math in. `$$` before `$`, so the display
    // form wins at the same offset; the bracket forms are unambiguous.
    const LATEX_DELIMITERS = [
        { open: "$$", close: "$$", display: true },
        { open: "\\[", close: "\\]", display: true },
        { open: "\\(", close: "\\)", display: false },
        { open: "$", close: "$", display: false },
    ];

    // The LaTeX spans in a run of text: `{start, end, tex, display, source}` in
    // that text's own offsets. `end` is exclusive and includes the closing
    // delimiter; `source` is the span exactly as the book wrote it, which is
    // what `mathText` hands back to the block lookups below.
    //
    // The bare `$` carries the two heuristics every auto-renderer has, or a book
    // about prices becomes a book of mathematics: no whitespace after the
    // opening `$` and none before the closing one, so `$5 and $10` is prose.
    // A span that fails any check costs one character, never the rest of the
    // paragraph — a real formula after a rejected opener is still found.
    function findLatexSpans(text) {
        const source = String(text == null ? "" : text);
        const spans = [];
        for (let at = 0; at < source.length; at++) {
            // Cheap pre-filter: only these two characters can open a span.
            if (source[at] !== "$" && source[at] !== "\\") continue;
            if (at > 0 && source[at - 1] === "\\") continue;   // `\$5` is a price
            const delimiter = LATEX_DELIMITERS.find(
                (candidate) => source.startsWith(candidate.open, at));
            if (!delimiter) continue;
            const bare = delimiter.open === "$";
            const after = source[at + delimiter.open.length];
            if (after === undefined) continue;
            if (bare && (/\s/.test(after) || after === "$")) continue;
            let end = source.indexOf(delimiter.close, at + delimiter.open.length);
            while (end > 0 && source[end - 1] === "\\") {
                end = source.indexOf(delimiter.close, end + 1);   // `\$` inside
            }
            if (end < 0) continue;
            const before = source[end - 1];
            if (bare && (/\s/.test(before) || before === "$")) continue;
            const tex = source.slice(at + delimiter.open.length, end);
            if (!tex.trim() || tex.includes("\n")) continue;
            const span = {
                start: at, end: end + delimiter.close.length, tex,
                display: delimiter.display,
                source: source.slice(at, end + delimiter.close.length),
            };
            spans.push(span);
            at = span.end - 1;   // the loop's own step moves past the span
        }
        return spans;
    }

    // What a node *says*, with every rendered formula put back to the source the
    // book wrote. Converting a formula replaces its source with the MathML the
    // browser draws, and every lookup in this file compares text against what
    // the library extracted — so without this a paragraph holding a formula
    // stops matching the moment it is converted. Measured on the math test book:
    // matched before the pass, null after it, matched again with this. The pass
    // writes `data-source` on each converted span for exactly this.
    //
    // A `DocumentFragment` works as well as an element — that is what a copied
    // selection is (`range.cloneContents()`), which is how 复制文本 hands a
    // reader the formula rather than the characters it was drawn from.
    function mathText(node) {
        if (!node) return "";
        let text = "";
        const walk = (current) => {
            if (current.nodeType === 3) {          // a text node
                text += current.nodeValue;
                return;
            }
            // A node with no children is a leaf: a stand-in such as the stub
            // documents in tests/js carry only their text, and a real leaf has
            // no converted formula inside it to put back.
            if (!current.childNodes) {
                text += current.textContent || "";
                return;
            }
            if (typeof current.hasAttribute === "function"
                && current.hasAttribute("data-reader-math")) {
                const source = current.getAttribute("data-source");
                if (source != null) text += source;
                return;
            }
            for (const child of current.childNodes) walk(child);
        };
        walk(node);
        return text;
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
        findLatexSpans,
        mathText,
        fileURL,
        clampSize,
        tocKey,
    };
})();
