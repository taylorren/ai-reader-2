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
                        "offsetToPoint", "findBlockForText", "blockElement",
                        "fileURL", "clampSize", "tocKey"]) {
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

