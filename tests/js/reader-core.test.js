/* Unit tests for the front end's pure helpers — REVIEW T1, step 2.
 *
 * Run with `node --test "tests/js/*.test.js"` from the repo root (or through
 * pytest: tests/test_frontend.py).
 * No dependencies: Node's own test runner, and a stub document where one is
 * needed, so `uv run pytest` covers the front end on any machine with node. */
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");

const REPO = path.resolve(__dirname, "..", "..");
const source = fs.readFileSync(
    path.join(REPO, "static", "js", "reader-core.js"), "utf8");
// Loaded in this realm rather than a vm context: a context would give the
// returned arrays and objects another realm's prototypes, and deepStrictEqual
// (rightly) refuses to call those equal. The module is a plain browser script
// assigning window.ReaderCore, so a `window` parameter is all it needs.
const core = new Function("window", `${source}\nreturn window.ReaderCore;`)({});

test("the module exposes the helpers the shell relies on", () => {
    for (const name of ["escapeHtml", "normalizeText", "normalizedIndex",
                        "offsetToPoint", "textNodes", "markPieces", "textOffset",
                        "findTextRange", "contextAround", "findBlockForText",
                        "blockElement", "firstVisibleBlockId", "fileURL",
                        "clampSize", "tocKey", "findLatexSpans", "mathText"]) {
        assert.equal(typeof core[name], "function", name);
    }
});

test("escapeHtml escapes what an innerHTML interpolation must not carry", () => {
    assert.equal(core.escapeHtml("<b>hi</b>"), "&lt;b&gt;hi&lt;/b&gt;");
    assert.equal(core.escapeHtml("a & b"), "a &amp; b");
    // Quotes are escaped too: the result is also safe in an attribute.
    assert.equal(core.escapeHtml('say "hi"'), "say &quot;hi&quot;");
    assert.equal(core.escapeHtml("it's"), "it&#39;s");
    // No double-escaping of an existing entity, and nothing crashes on null.
    assert.equal(core.escapeHtml("&amp;"), "&amp;amp;");
    assert.equal(core.escapeHtml(null), "");
    assert.equal(core.escapeHtml(undefined), "");
    assert.equal(core.escapeHtml(0), "0");
});

test("normalizeText collapses whitespace, including the ideographic space", () => {
    assert.equal(core.normalizeText("  a \n\n b\t c  "), "a b c");
    // U+3000 is what a CJK/InDesign export sets a blank line with; `\s` in
    // JavaScript matches it, which is why the block matching works at all.
    assert.equal(core.normalizeText("　"), "");
    assert.equal(core.normalizeText("甲　乙"), "甲 乙");
    assert.equal(core.normalizeText(""), "");
    assert.equal(core.normalizeText(null), "");
});

test("normalizedIndex keeps a map back to the source offsets", () => {
    const { value, map } = core.normalizedIndex("a  \n b");
    assert.equal(value, "a b");
    // The collapsed space maps to the *first* character of the whitespace run,
    // so the map always points at real source offsets.
    assert.deepEqual(map, [0, 1, 5]);
    // The property that matters: every mapped offset points at the character
    // the normalised value came from.
    for (let i = 0; i < value.length; i++) {
        if (value[i] !== " ") assert.equal("a  \n b"[map[i]], value[i]);
    }
});

test("normalizedIndex drops a trailing run and keeps the leading one", () => {
    assert.deepEqual(core.normalizedIndex("ab   "), { value: "ab", map: [0, 1] });
    assert.deepEqual(core.normalizedIndex("   ab"), { value: "ab", map: [3, 4] });
    assert.deepEqual(core.normalizedIndex("　　"), { value: "", map: [] });
    assert.deepEqual(core.normalizedIndex(""), { value: "", map: [] });
});

test("offsetToPoint finds the text node an offset lands in", () => {
    const nodes = [{ nodeValue: "abc" }, { nodeValue: "def" }, { nodeValue: "gh" }];
    assert.equal(core.offsetToPoint(nodes, 0).node, nodes[0]);
    assert.equal(core.offsetToPoint(nodes, 2).offset, 2);
    // The boundary belongs to the node it closes: offset 3 is the *end* of the
    // first node, not the start of the second (the caller then splits there).
    assert.equal(core.offsetToPoint(nodes, 3).node, nodes[0]);
    assert.equal(core.offsetToPoint(nodes, 3).offset, 3);
    assert.equal(core.offsetToPoint(nodes, 4).node, nodes[1]);
    assert.equal(core.offsetToPoint(nodes, 4).offset, 1);
    assert.equal(core.offsetToPoint(nodes, 8).node, nodes[2]);
    assert.equal(core.offsetToPoint(nodes, 9), null);
    assert.equal(core.offsetToPoint([], 0), null);
});

test("offsetToPoint can resolve a boundary forward, for a range start", () => {
    // A selection that begins right after an inline element starts, by default,
    // at the *end* of that element's text node. A Range may hold that point —
    // but `surroundContents` will not: the range then partially selects the
    // element, and the wrap threw `InvalidStateError`, so the mark was stored
    // and never painted (项狄传 vol 5 ch 34: "Ars longa，——和Vita brevis" sits
    // right after `<small>希波克拉底</small>`). `preferNext` puts the start in
    // the node the selection really begins in, which is what the wrap asks for.
    const nodes = [{ nodeValue: "abc" }, { nodeValue: "def" }];
    assert.equal(core.offsetToPoint(nodes, 3).node, nodes[0]);
    assert.equal(core.offsetToPoint(nodes, 3).offset, 3);
    assert.equal(core.offsetToPoint(nodes, 3, true).node, nodes[1]);
    assert.equal(core.offsetToPoint(nodes, 3, true).offset, 0);
    // At the run's end there is no next node to move to: the closing node is
    // all there is, and the start stays there.
    assert.equal(core.offsetToPoint(nodes, 6, true).node, nodes[1]);
    assert.equal(core.offsetToPoint(nodes, 6, true).offset, 3);
    // An offset inside a node is unaffected, with or without the bias.
    assert.equal(core.offsetToPoint(nodes, 4, true).node, nodes[1]);
    assert.equal(core.offsetToPoint(nodes, 4, true).offset, 1);
    assert.equal(core.offsetToPoint(nodes, 0, true).node, nodes[0]);
    assert.equal(core.offsetToPoint(nodes, 0, true).offset, 0);
});

test("markPieces cuts a run at the text nodes and names the mark each sits in", () => {
    // A run over the middle of the first node, all of the second and the start
    // of the third: three pieces, each inside one text node — what a wrap has to
    // fall back to when it cannot take the run in one range.
    const mark = { classList: { contains: (name) => name === "reader-highlight" } };
    const nodes = [
        { nodeValue: "abcdef", parentElement: null },
        { nodeValue: "ghij", parentElement: mark },
        { nodeValue: "kl", parentElement: null },
    ];
    const pieces = core.markPieces(nodes, 3, 9);
    assert.deepEqual(pieces.map((piece) => [piece.at, piece.length, piece.mark === mark]),
                     [[3, 3, false], [0, 4, true], [0, 2, false]]);
    assert.equal(pieces[0].node, nodes[0]);
    assert.equal(pieces[2].node, nodes[2]);
    // The mark is the one the piece sits inside, found up the parent chain — the
    // shape a painted highlight has: <mark><span>text</span></mark>.
    const nested = { nodeValue: "ab", parentElement: { classList: { contains: () => false },
                                                      parentElement: mark } };
    assert.equal(core.markPieces([nested], 0, 2)[0].mark, mark);
    // A run that covers nothing, or a document with no text nodes: no pieces.
    assert.deepEqual(core.markPieces(nodes, 12, 1), []);
    assert.deepEqual(core.markPieces([], 0, 3), []);
});

test("textOffset measures a range point in the run's own coordinates", () => {
    const nodes = [{ nodeValue: "abc" }, { nodeValue: "def" }, { nodeValue: "gh" }];
    assert.equal(core.textOffset(nodes, nodes[0], 0), 0);
    assert.equal(core.textOffset(nodes, nodes[0], 3), 3);
    assert.equal(core.textOffset(nodes, nodes[1], 1), 4);
    assert.equal(core.textOffset(nodes, nodes[2], 2), 8);
    // A range whose container is not one of the run's text nodes — it starts at
    // an element boundary — has no offset here: the caller falls back instead of
    // guessing which occurrence the reader meant.
    assert.equal(core.textOffset(nodes, { nodeValue: "other" }, 0), null);
    assert.equal(core.textOffset([], nodes[0], 0), null);
});

test("a normalised match round trips back into the right node", () => {
    // The shape wrapText relies on: the selection is found in the *normalised*
    // run, then mapped back through `map` to a real node and offset.
    const nodes = [{ nodeValue: "The first " }, { nodeValue: "paragraph  " },
                   { nodeValue: "mentions a plate" }];
    const full = nodes.map((n) => n.nodeValue).join("");
    const haystack = core.normalizedIndex(full);
    const needle = core.normalizedIndex("paragraph mentions");
    const at = haystack.value.indexOf(needle.value);
    assert.ok(at > 0, "the normalised selection is found");
    const start = core.offsetToPoint(nodes, haystack.map[at]);
    const end = core.offsetToPoint(
        nodes, haystack.map[at + needle.value.length - 1] + 1);
    // The start lands on a node boundary — the end of the node it closes, which
    // is where a Range legitimately starts — and the end is inside the last
    // node the selection touches.
    assert.equal(start.node, nodes[0]);
    assert.equal(start.offset, 10);
    assert.equal(end.node, nodes[2]);
    assert.equal(end.offset, 8);
    // The mapped range covers the selection, whitespace and all — the source
    // has two spaces where the normalised run has one.
    assert.equal(core.normalizeText(
        full.slice(haystack.map[at], haystack.map[at + needle.value.length - 1] + 1)),
        "paragraph mentions");
});

// The paragraph the repeated-sentence case is built from: the same sentence
// twice, with a middle that says which is which.
const SENTENCE = "The same sentence twice.";
const REPEATED = "The same sentence twice. In between stands a marker. "
               + "The same sentence twice.";

test("findTextRange wraps the occurrence the saved context points at", () => {
    // REVIEW P2-10: matching the *first* occurrence painted the wrong sentence
    // whenever a paragraph repeated one, which is the ambiguity the context
    // saved with the selection exists to resolve.
    const second = core.findTextRange(REPEATED, SENTENCE,
                                      "The same sentence twice. In between stands a marker.",
                                      "");
    assert.equal(second.at, REPEATED.lastIndexOf(SENTENCE));
    assert.equal(REPEATED.slice(second.at, second.at + second.length), SENTENCE);

    // ...and the first, when the context describes the first.
    const first = core.findTextRange(REPEATED, SENTENCE, "",
                                     "In between stands a marker. The same sentence twice.");
    assert.equal(first.at, REPEATED.indexOf(SENTENCE));

    // Three occurrences: the middle one, chosen by both halves at once.
    const three = SENTENCE + " alpha " + SENTENCE + " beta " + SENTENCE;
    const middle = core.findTextRange(three, SENTENCE, "alpha", "beta");
    assert.equal(middle.at, three.indexOf(SENTENCE, three.indexOf(SENTENCE) + 1));
});

test("findTextRange falls back to the first occurrence without usable context", () => {
    // No context at all: a row imported from the old app, or an import that
    // never captured one.
    assert.equal(core.findTextRange(REPEATED, SENTENCE, "", "").at, 0);
    assert.equal(core.findTextRange(REPEATED, SENTENCE, undefined, undefined).at, 0);
    // A context that matches nothing — the book was re-uploaded, the text
    // edited — leaves every candidate on zero, so the first wins: the behaviour
    // before this existed, kept as the fallback.
    assert.equal(core.findTextRange(REPEATED, SENTENCE,
                                    "somewhere else entirely", "and afterwards").at, 0);
    // Identical surroundings are a tie, and a tie keeps the first, so the
    // answer is deterministic rather than dependent on iteration order.
    assert.equal(core.findTextRange(SENTENCE + SENTENCE, SENTENCE, "", "").at, 0);
    assert.equal(core.findTextRange(SENTENCE + " x " + SENTENCE, SENTENCE, "", "").at, 0);
});

test("findTextRange matches the document's whitespace, not the extractor's", () => {
    // The block's text arrives from the extractor single-spaced; the served
    // document carries the book's own spacing. The range returned covers the
    // document's characters — whitespace and all — which is what a Range needs.
    const document = "The first paragraph mentions a plate\n     and then keeps going";
    const found = core.findTextRange(document, "mentions a plate and then", "", "");
    assert.equal(document.slice(found.at, found.at + found.length),
                 "mentions a plate\n     and then");

    // The context is compared normalised too, so the space that separates an
    // occurrence from its surroundings does not cost the match its last
    // character (which would make a correct context score zero).
    const twice = "One. Two. One. Two.";
    // What the capture would store for the *second* "Two.": the text actually
    // before it, trimmed.
    assert.equal(core.findTextRange(twice, "Two.", "One. Two. One.", "").at,
                 twice.lastIndexOf("Two."));
    assert.equal(core.findTextRange(twice, "Two.", "One.", "One.").at,
                 twice.indexOf("Two."));
});

test("findTextRange reports nothing when the text is not there", () => {
    assert.equal(core.findTextRange(REPEATED, "not in this paragraph", "", ""), null);
    assert.equal(core.findTextRange(REPEATED, "", "", ""), null);
    assert.equal(core.findTextRange("", SENTENCE, "", ""), null);
    // Whitespace-only normalises away to nothing, so it matches nothing.
    assert.equal(core.findTextRange(REPEATED, "   ", "", ""), null);
});

test("firstVisibleBlockId picks the block at the reading line", () => {
    // REVIEW P2-10: a reading position is stored by block as well as by
    // percent, so it lands on the same paragraph after the text reflows.
    const nodes = [
        { textContent: "scrolled past",
          getBoundingClientRect: () => ({ top: -80, bottom: -20 }) },
        { textContent: "the reading line sits here",
          getBoundingClientRect: () => ({ top: -10, bottom: 30 }) },
        { textContent: "below the fold",
          getBoundingClientRect: () => ({ top: 40, bottom: 90 }) },
    ];
    const doc = { querySelectorAll: () => nodes };
    const blocks = [
        { id: "c0/b0", text: "scrolled past" },
        { id: "c0/b1", text: "the reading line sits here" },
        { id: "c0/b2", text: "below the fold" },
    ];
    assert.equal(core.firstVisibleBlockId(blocks, doc, 0), "c0/b1");
    // At a line further down, the same page anchors to the lower block.
    assert.equal(core.firstVisibleBlockId(blocks, doc, 50), "c0/b2");
});

test("firstVisibleBlockId steps over a node the blocks do not know", () => {
    // An image between two paragraphs must not cost the anchor: the search
    // continues rather than ending on a node with no block behind it.
    const nodes = [
        { textContent: "", getBoundingClientRect: () => ({ top: -5, bottom: 20 }) },
        { textContent: "the paragraph after the plate",
          getBoundingClientRect: () => ({ top: 20, bottom: 60 }) },
    ];
    const doc = { querySelectorAll: () => nodes };
    assert.equal(core.firstVisibleBlockId(
        [{ id: "c0/b9", text: "the paragraph after the plate" }], doc, 0), "c0/b9");

    // Nothing on screen belongs to a block, or there are no blocks at all: no
    // anchor, and the caller keeps the percent.
    assert.equal(core.firstVisibleBlockId([{ id: "x", text: "elsewhere" }], doc, 0), null);
    assert.equal(core.firstVisibleBlockId([], doc, 0), null);
    assert.equal(core.firstVisibleBlockId(null, doc, 0), null);
});

test("firstVisibleBlockId matches by text, whitespace aside, and keeps the first", () => {
    const nodes = [{ textContent: "the line\n     wraps here",
                     getBoundingClientRect: () => ({ top: -5, bottom: 20 }) }];
    const doc = { querySelectorAll: () => nodes };
    assert.equal(core.firstVisibleBlockId(
        [{ id: "c1/b2", text: "the line wraps here" }], doc, 0), "c1/b2");

    // Two blocks with the same text make the anchor ambiguous; the first wins,
    // which is the same answer the extractor's ordering gave before.
    const repeated = { querySelectorAll: () => [
        { textContent: "same", getBoundingClientRect: () => ({ top: 0, bottom: 10 }) }] };
    assert.equal(core.firstVisibleBlockId(
        [{ id: "first", text: "same" }, { id: "second", text: "same" }],
        repeated, 0), "first");
});

test("findBlockForText picks the smallest block that contains the selection", () => {
    const blocks = [
        { id: "c0000/b0001", text: "A long paragraph that mentions a plate and keeps going." },
        { id: "c0000/b0002", text: "mentions a plate" },
        { id: "c0000/b0003", text: "unrelated" },
    ];
    assert.equal(core.findBlockForText(blocks, "mentions a plate").id, "c0000/b0002");
    assert.equal(core.findBlockForText(blocks, "a plate").id, "c0000/b0002");
    assert.equal(core.findBlockForText(blocks, "nothing here"), null);
    assert.equal(core.findBlockForText([], "x"), null);
});

test("blockElement matches a block to the frame's element, whitespace aside", () => {
    const elements = [
        { textContent: "Chapter One" },
        { textContent: "The first paragraph mentions a plate\n     and then keeps going" },
    ];
    const doc = { querySelectorAll: () => elements };
    const found = core.blockElement(doc, {
        text: "The first paragraph mentions a plate and then keeps going" });
    assert.equal(found, elements[1]);
    // A blank block — the CJK export's `<p>　</p>` — has nothing to match.
    assert.equal(core.blockElement(doc, { text: "　" }), null);
    assert.equal(core.blockElement(doc, { text: "" }), null);
    assert.equal(core.blockElement(doc, { text: "not in this document" }), null);
});

test("fileURL encodes each path segment and the anchor", () => {
    assert.equal(core.fileURL("Fixture Book", "OEBPS/ch1.xhtml"),
                 "/book/Fixture%20Book/OEBPS/ch1.xhtml");
    assert.equal(core.fileURL("Fixture Book", "OEBPS/img/plate one.png"),
                 "/book/Fixture%20Book/OEBPS/img/plate%20one.png");
    assert.equal(core.fileURL("Fixture Book", "OEBPS/ch1.xhtml", "sec a"),
                 "/book/Fixture%20Book/OEBPS/ch1.xhtml#sec%20a");
    assert.equal(core.fileURL("Fixture Book", "ch1.xhtml", "#top"),
                 "/book/Fixture%20Book/ch1.xhtml#%23top");
});

test("fileURL survives the slugs the server's own quote() produces", () => {
    // The quirk this pins: `encodeURIComponent` leaves "(" and ")" literal —
    // they are unreserved for it — while the server's Python `quote` escapes
    // them as %28/%29. An encoded-form comparison against the frame's URL
    // therefore failed for every translated title with parentheses, which is
    // why reader.js compares *decoded* paths. The invariant that must hold is
    // that the decoded prefix is the slug, whichever side did the encoding.
    const slug = "项狄传 (劳伦斯·斯特恩作品)";
    const url = core.fileURL(slug, "OEBPS/ch1.xhtml");
    assert.ok(url.includes("(") && url.includes(")"), "parens stay literal");
    assert.equal(decodeURIComponent(url.split("/book/")[1].split("/")[0]), slug);
    // And the P1-2 characters: a slug that keeps them is still a usable URL.
    assert.equal(core.fileURL("C# in Depth", "ch1.xhtml"),
                 "/book/C%23%20in%20Depth/ch1.xhtml");
    assert.equal(core.fileURL("100% Pure", "ch1.xhtml"),
                 "/book/100%25%20Pure/ch1.xhtml");
});

test("clampSize keeps the reading size inside the sheet's range", () => {
    assert.equal(core.clampSize(19), 19);
    assert.equal(core.clampSize(1), 12);
    assert.equal(core.clampSize(999), 48);
    assert.equal(core.clampSize(12), 12);
    assert.equal(core.clampSize(48), 48);
    // A missing or unreadable localStorage value falls back to the default.
    assert.equal(core.clampSize(NaN), 19);
    assert.equal(core.clampSize(undefined), 19);
    assert.equal(core.clampSize("19"), 19);   // Number.isFinite("19") is false
});

test("tocKey identifies a TOC node by href, anchor and label", () => {
    assert.equal(core.tocKey({ href: "ch1.xhtml", anchor: "sec-a", label: "First" }),
                 "ch1.xhtml|sec-a|First");
    assert.equal(core.tocKey({}), "||");
    // Two sections of one document differ only by anchor or label — which is
    // the shape the derived outline produces.
    assert.notEqual(core.tocKey({ href: "ch1.xhtml", anchor: "sec-a" }),
                    core.tocKey({ href: "ch1.xhtml", anchor: "sec-b" }));
});


/* ---- LaTeX: what is math, and what the document says once it is drawn ----
 *
 * The pass that draws a book's LaTeX lives in reader.js and needs a browser
 * (tests/test_browser.py). These are the two halves of it that do not: which
 * spans are math at all — where a book about prices must stay a book about
 * prices — and what a paragraph *says* after a formula has been drawn into it,
 * which is what keeps every block lookup in this file working.
 */

test("findLatexSpans finds the delimiters a book writes math in", () => {
    const text = "Inline math is $x = \\frac{a}{b}$, and that is that.";
    const spans = core.findLatexSpans(text);
    assert.equal(spans.length, 1);
    assert.equal(spans[0].tex, "x = \\frac{a}{b}");
    assert.equal(spans[0].display, false);
    assert.equal(spans[0].source, "$x = \\frac{a}{b}$");
    // The offsets are the text's own, and they select the source exactly.
    assert.equal(text.slice(spans[0].start, spans[0].end), spans[0].source);
});

test("findLatexSpans knows the display forms and the bracket spellings", () => {
    for (const [text, source, tex] of [
        ["before $$x^2$$ after", "$$x^2$$", "x^2"],
        ["before \\[x^2\\] after", "\\[x^2\\]", "x^2"],
    ]) {
        const [span] = core.findLatexSpans(text);
        assert.equal(span.source, source);
        assert.equal(span.tex, tex);
        assert.equal(span.display, true);
    }
    const [inline] = core.findLatexSpans("before \\(x^2\\) after");
    assert.equal(inline.source, "\\(x^2\\)");
    assert.equal(inline.display, false);
});

test("findLatexSpans leaves a price alone", () => {
    // The two heuristics every auto-renderer carries: no whitespace after the
    // opening `$`, none before the closing one.
    assert.deepEqual(core.findLatexSpans("It cost $5 and then $10."), []);
    assert.deepEqual(core.findLatexSpans("$5.00"), []);
    assert.deepEqual(core.findLatexSpans("a single $ sign"), []);
    // An escaped dollar is a literal, and so is one inside a formula.
    assert.deepEqual(core.findLatexSpans("\\$5 is a price"), []);
    assert.equal(core.findLatexSpans("$a \\$ b$")[0].tex, "a \\$ b");
    // A rejected opener costs one character, not the rest of the paragraph: a
    // real formula after it is still found.
    const spans = core.findLatexSpans("$5 and $10, but $x^2$ is math.");
    assert.equal(spans.length, 1);
    assert.equal(spans[0].source, "$x^2$");
});

test("findLatexSpans takes every formula in one run of text, in order", () => {
    const spans = core.findLatexSpans("$a$ then $$b$$ then \\(c\\)");
    assert.deepEqual(spans.map((span) => span.source), ["$a$", "$$b$$", "\\(c\\)"]);
    // Nothing to find, and nothing to crash on.
    assert.deepEqual(core.findLatexSpans("plain prose"), []);
    assert.deepEqual(core.findLatexSpans(""), []);
    assert.deepEqual(core.findLatexSpans(null), []);
    // Empty spans and multi-line ones are not formulas a renderer can be handed.
    assert.deepEqual(core.findLatexSpans("$$$$"), []);
    assert.deepEqual(core.findLatexSpans("$a\nb$"), []);
});

// A node tree for `mathText`, which reads nodeType/nodeValue/childNodes and the
// two attribute methods — and nothing else.
const textNode = (value) => ({ nodeType: 3, nodeValue: value });
const element = (attributes, ...children) => ({
    nodeType: 1, childNodes: children,
    hasAttribute: (name) => Object.prototype.hasOwnProperty.call(attributes, name),
    getAttribute: (name) => attributes[name],
});

test("mathText reads a drawn formula as the source the book wrote", () => {
    const drawn = element({ "data-reader-math": "", "data-tex": "x^2",
                            "data-source": "$x^2$" },
                          element({}, textNode("x2")));
    const paragraph = element({}, textNode("Area is "), drawn,
                              textNode(", roughly."));
    assert.equal(core.mathText(paragraph), "Area is $x^2$, roughly.");
    // A drawn formula with no source to fall back on contributes nothing, rather
    // than leaking the characters it draws.
    const orphan = element({ "data-reader-math": "" },
                           element({}, textNode("x2")));
    assert.equal(core.mathText(element({}, textNode("Area is "), orphan)), "Area is ");
    // Text nodes, nothing, and a plain element all answer sensibly.
    assert.equal(core.mathText(textNode("plain")), "plain");
    assert.equal(core.mathText(null), "");
    assert.equal(core.mathText(undefined), "");
    // A stand-in node that cannot be walked is read as its text — the shape the
    // stub documents in this suite are made of.
    assert.equal(core.mathText({ textContent: "no children here" }),
                 "no children here");
});

test("mathText projects a copied selection, not only a whole block", () => {
    // `range.cloneContents()` gives a fragment: nodeType 11, children, and no
    // attributes of its own — the shape 复制文本 hands to `mathText` so a copied
    // formula arrives as its source rather than as the characters it drew.
    const fragment = {
        nodeType: 11,
        childNodes: [
            textNode("Inline math is "),
            element({ "data-reader-math": "", "data-source": "$x = \\frac{a}{b}$" },
                    element({}, textNode("x=ab"))),
            textNode(", and that is that."),
        ],
    };
    assert.equal(core.mathText(fragment),
                 "Inline math is $x = \\frac{a}{b}$, and that is that.");
});

test("mathText is what keeps a block matchable after the math pass", () => {
    const paragraph = element({}, textNode("Inline math is "),
        element({ "data-reader-math": "", "data-tex": "x = \\frac{a}{b}",
                  "data-source": "$x = \\frac{a}{b}$" },
                element({}, textNode("x=ab"))),
        textNode(", and that is that."));
    // The two readings differ, which is the whole reason `mathText` exists: the
    // document's own text is the drawn characters, and what the library
    // extracted — what `blockElement` compares against — is the source.
    assert.notEqual(core.normalizeText(paragraph.childNodes.map(
        (child) => child.textContent || "").join("")),
        core.normalizeText(core.mathText(paragraph)));
    assert.equal(core.normalizeText(core.mathText(paragraph)),
                 "Inline math is $x = \\frac{a}{b}$, and that is that.");
});

