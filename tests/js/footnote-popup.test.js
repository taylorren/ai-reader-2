/* The footnote popup: the note's own label, printed once — as its head.
 *
 * A note's paragraph in a CJK edition opens with the note's own number, and
 * epubx folds that label into the note's text — so the popup printed the number
 * twice, once as the head and again at the head of the text (reported from the
 * deployment, 项狄传 ch. 17). The head prints the label now — a label, not a
 * link: the popup is dismissed by clicking outside it — and the note's text no
 * longer carries it.
 *
 * Two shapes of label are *known* to the shell, because the book's own markup
 * says so: a link back to the marker (项狄传), or an element that is nothing but
 * the label (剑桥中华民国史). Everywhere else nothing is taken out of the text —
 * a note in another chapter, a note that merely opens with the same digits, a
 * marker that swallowed prose — and the head yields instead. A digit dropped
 * from the book's text would be unrecoverable.
 *
 * The frame here is a stub document — a real one needs a browser — but the
 * marker click, the edge the API served and the DOM the shell builds are real.
 */
const test = require("node:test");
const assert = require("node:assert/strict");

const { createPage } = require("./dom-stub.js");

// A fresh book per page: reader.js mutates BOOK.index as the reader moves.
const book = () => ({
    slug: "Fixture Book",
    index: 0,
    spine: ["OEBPS/ch1.xhtml", "OEBPS/ch2.xhtml"],
    toc: [],
    saved_percent: 0,
    target_highlight: "",
});

// The marker the reader clicks, as the frame's own document hands it over: the
// raw href the book wrote is what the shell matches an edge by, and the marker's
// own id is what a note's back-link points at.
function marker(href, id) {
    return {
        id,
        dataset: {},
        getAttribute: () => href,
        getBoundingClientRect: () => ({ top: 10, left: 10, bottom: 24, right: 20 }),
        addEventListener(type, fn) {
            if (type !== "click") return;
            this.click = () => fn({
                preventDefault() {}, stopPropagation() {}, currentTarget: this,
            });
        },
    };
}

// The label as the link the note opens with — 项狄传's own back-link.
function labelLink(text, href) {
    return { textContent: text, getAttribute: () => href, dataset: {} };
}

// The element a note resolves to when the book printed the label *as* that
// element — 剑桥中华民国史's `<a id="filepos39577" href="#filepos23590">①</a>`,
// the number linked back to the marker it belongs to.
function ownLabelElement(text, href) {
    return {
        textContent: text,
        dataset: {},
        childNodes: [],
        getAttribute: () => href,
        querySelectorAll: () => [],
    };
}

// The frame's own document, with the note the marker opens. `note` is that
// note's element as the book wrote it: `{ link }` for the back-link shape,
// `{ own }` for the label-as-element shape, or null for a note with neither.
// The shell looks the label up here, and that lookup is what makes it a fact
// rather than a guess about the note's text.
function frameDocumentFor(anchor, targetId, note) {
    const target = (note && note.own) || {
        childNodes: [],
        textContent: "The local note.",
        getAttribute: () => null,
        querySelectorAll: () => [],
    };
    if (note && note.link) {
        const wrapper = { childNodes: [note.link], textContent: "" };
        wrapper.contains = (child) => child === note.link;
        target.childNodes = [wrapper];
        target.textContent = "";
        target.querySelectorAll = () => [note.link];
    }
    return {
        _listeners: {},
        body: { dataset: {}, addEventListener() {} },
        getElementById: (id) => (id === targetId ? target : null),
        // Only the book's links answer: the image wiring asks the same document
        // for its own selector, and must not be handed a marker.
        querySelectorAll: (selector) => (selector.includes("a[href]") ? [anchor] : []),
        addEventListener() {},
    };
}

// A page whose one footnote edge is served, wired and clicked — so the popup
// the shell built is what a reader would see.
async function popupPage(edgeData, note) {
    const page = createPage({ book: book() });
    page.route(/\/api\/footnotes\//, { edges: [edgeData] });
    page.route(/\/api\/text\//, { blocks: [] });
    page.route(/\/api\/highlights\//, { highlights: [] });
    page.route(/\/api\/progress$/, { status: "success" });
    const anchor = marker(edgeData.href, edgeData.marker_id);
    page.frame().contentDocument =
        frameDocumentFor(anchor, edgeData.target_anchor, note);
    page.frame().contentWindow = {
        location: { pathname: "/book/Fixture%20Book/OEBPS/ch1.xhtml" },
        document: { documentElement: { scrollHeight: 1000 } },
        innerHeight: 800,
        addEventListener() {},
        scrollTo() {},
    };
    // The frame's load is what wires the chapter's markers (reader.js).
    page.fire("load", page.frame());
    await page.settle();        // loadEdges' fetch resolves
    await page.settle();        // and the edges are wired
    anchor.click();
    return page;
}


const children = (page) => page.el("footnote-popup").children;
const head = (page) => children(page).find((child) => child.className === "popup-head");
const note = (page) => children(page).find(
    (child) => child.className.startsWith("popup-note"));

// The edge the API serves for a note in the same chapter, resolved.
const edge = (overrides) => ({
    text: "1",
    href: "#local-note",
    marker_id: "fnref1",
    resolved: true,
    target_chapter: 0,
    target_href: "OEBPS/ch1.xhtml",
    target_anchor: "local-note",
    target_text: "The local note.",
    ...overrides,
});

// 项狄传 ch. 17's note 4, verbatim: the paragraph opens with the back-link that
// epubx folds into the note's text.
const NOTE_4 = "4斯特恩耍调皮的典型例子。已声明他锁上书房门——意即他已经与他常常"
    + "窃取的作家们一刀两断。";
const NOTE_4_ELEMENT = { link: labelLink("4", "part0009_split_001.html#fnref564") };
const note4Edge = (overrides) => edge({
    text: "4", href: "part0009_split_001.html#fn564",
    marker_id: "fnref564", target_anchor: "fn564", target_text: NOTE_4,
    ...overrides,
});

test("the note's own label is the head, and leaves the note's text", async () => {
    const page = await popupPage(note4Edge(), NOTE_4_ELEMENT);

    assert.equal(head(page).textContent, "4", "the head prints the label");
    assert.equal(head(page).tagName, "DIV", "a label, not a link");
    assert.equal(note(page).textContent,
                 "斯特恩耍调皮的典型例子。已声明他锁上书房门——意即他已经与他常常"
                 + "窃取的作家们一刀两断。");
});

test("a label the book printed against the text is marked for the paper sheet", async () => {
    // 项狄传's own CSS prints the label at full size (its class is 1em, nudged
    // 4px up), so it runs into the note's first word. Marked, never rewritten:
    // the document on disk is untouched.
    const page = await popupPage(note4Edge(), NOTE_4_ELEMENT);

    assert.equal(NOTE_4_ELEMENT.link.dataset.noteLabel, "1");
    assert.equal(head(page).textContent, "4");
});

test("a label the book already spaced is left alone", async () => {
    // 剑桥中华民国史 prints its note numbers as anchors that link back to the
    // marker, and its text already runs "① 关于汉学…": the number is still the
    // head — the label is known — but the paper sheet has no space to add.
    const own = ownLabelElement("①", "#filepos23590");
    const page = await popupPage(edge({
        text: "①", href: "ch7.html#filepos39577", marker_id: "filepos23590",
        target_anchor: "filepos39577", target_text: "① 关于汉学和“中国文明的自我形象”。",
    }), { own });

    assert.equal(head(page).textContent, "①");
    assert.equal(note(page).textContent, "关于汉学和“中国文明的自我形象”。");
    assert.equal(own.dataset.noteLabel, undefined, "nothing to space");
});

test("a note in another chapter is not trimmed: the head yields", async () => {
    // The note is not on screen, so its leading number cannot be seen for what
    // it is — and the shell does not guess at the book's text.
    const page = await popupPage(edge({
        text: "2", target_href: "OEBPS/ch2.xhtml", target_anchor: "endnote-1",
        target_text: "2第5、第6两卷于1761年12月出版。",
    }));

    assert.equal(head(page), undefined);
    assert.equal(note(page).textContent, "2第5、第6两卷于1761年12月出版。");
});

test("a note whose own text opens with the same digits keeps them", async () => {
    // Same chapter, but the note has no label element: the "4" is the note's own
    // first word. The head yields; the text is printed whole.
    const page = await popupPage(
        edge({ text: "4", target_text: "4月5日，他离开了。" }), null);

    assert.equal(head(page), undefined);
    assert.equal(note(page).textContent, "4月5日，他离开了。");
});

test("a marker that swallowed prose never trims the note", async () => {
    // Death of Caesar anchors its markers on an empty element, and the back-link
    // its producer built out of the words after it wraps real prose: the note
    // reads "In 50 B.C. Decimus was back in Rome…" and opens with a link reading
    // "In 50". That is not a label, and the note keeps every word.
    const page = await popupPage(edge({
        text: "In 50", href: "ch01.html#note07", marker_id: "note07",
        target_anchor: "note07",
        target_text: "In 50 B.C. Decimus was back in Rome for his first office.",
    }), { link: labelLink("In 50", "ch01.html#note07") });

    assert.equal(head(page), undefined, "the head yields");
    assert.equal(note(page).textContent,
                 "In 50 B.C. Decimus was back in Rome for his first office.");
});

test("a note that does not carry its own number keeps the head", async () => {
    const page = await popupPage(edge({ text: "1" }), null);

    assert.ok(head(page), "the head is what labels the popup");
    assert.equal(head(page).textContent, "1");
    assert.equal(note(page).textContent, "The local note.");
});

test("a reference the book never defines still says which marker it was", async () => {
    const page = await popupPage(edge({
        text: "7", href: "ch2.xhtml#no-such-note", resolved: false,
    }), null);

    assert.equal(head(page).textContent, "7");
    assert.equal(note(page).textContent, "这个引用无法定位 — ch2.xhtml#no-such-note");
    assert.equal(note(page).className, "popup-note unresolved");
});
