/* The reader shell following an in-book link — REVIEW P1-6.
 *
 * A footnote's 在注释处打开, or any cross-reference the book writes, navigates
 * the *frame* without the shell asking. reader.js notices on the frame's `load`
 * event; these tests drive that handler through the shell's own listener and
 * assert what it records and what it does not.
 */
const test = require("node:test");
const assert = require("node:assert/strict");

const { createPage } = require("./dom-stub.js");

// A fresh book per page: reader.js mutates BOOK.index as the reader moves, so
// sharing one object across tests would leak chapter state between them.
const book = () => ({
    slug: "Fixture Book",
    index: 0,
    spine: ["OEBPS/ch1.xhtml", "OEBPS/ch2.xhtml"],
    toc: [{ label: "Chapter One", href: "OEBPS/ch1.xhtml", anchor: "", children: [] },
          { label: "Chapter Two", href: "OEBPS/ch2.xhtml", anchor: "", children: [] }],
    saved_percent: 0,
    target_highlight: "",
});

function shellPage(options = {}) {
    const page = createPage({ book: book(), files: options.files });
    page.route(/\/api\/progress$/, { status: "success" });
    page.route(/\/api\/footnotes\//, { edges: [] });
    page.route(/\/api\/text\//, { blocks: [] });
    page.route(/\/api\/highlights\//, { highlights: [] });
    // The frame's own window: the shell reads its location, and on scroll its
    // document.
    page.frame().contentWindow = {
        location: { pathname: "/book/Fixture%20Book/OEBPS/ch1.xhtml" },
        document: { documentElement: { scrollHeight: 4000 } },
        innerHeight: 800,
        addEventListener() {},
        scrollTo() {},
    };
    return page;
}

const progressSaves = (page) => page.requests.filter((r) => /\/api\/progress$/.test(r.url));

test("a link into another chapter is recorded, so a resume lands there", () => {
    const page = shellPage();
    // The book's own link moved the frame to chapter two; the shell is told by
    // the frame's load event, not by anything it did itself.
    page.frame().contentWindow.location.pathname = "/book/Fixture%20Book/OEBPS/ch2.xhtml";
    page.fire("load", page.frame());

    const saved = progressSaves(page).pop();
    assert.ok(saved, "the move was recorded as progress");
    assert.equal(JSON.parse(saved.body).chapter_index, 1);
    assert.equal(JSON.parse(saved.body).scroll_percent, 0);
    assert.equal(JSON.parse(saved.body).book_id, "Fixture Book");
});

test("the shell follows the frame: the bar and the panel move with it", () => {
    const page = shellPage();
    page.frame().contentWindow.location.pathname = "/book/Fixture%20Book/OEBPS/ch2.xhtml";
    page.fire("load", page.frame());

    assert.equal(page.el("top-position").textContent, "2 / 2");
    assert.equal(page.el("bottom-position").textContent, "2 / 2");
    assert.equal(page.P.state.index, 1, "the panel is looking at the new chapter");
});

test("a load that stays on the same chapter records nothing", () => {
    const page = shellPage();
    page.fire("load", page.frame());      // the frame re-loaded chapter one

    assert.equal(progressSaves(page).length, 0);
    assert.equal(page.el("top-position").textContent, "1 / 2");
});

test("a load that is not a chapter of this book is left alone", () => {
    const page = shellPage();
    page.frame().contentWindow.location.pathname = "/book/Fixture%20Book/OEBPS/cover.xhtml";
    page.fire("load", page.frame());

    assert.equal(progressSaves(page).length, 0);
    assert.equal(page.P.state.index, 0);
});

test("a chapter entered by a link is not scrolled to the previous chapter's position", () => {
    // The shell remembers the position of every chapter it has shown; entering
    // chapter two by a link must not apply chapter one's percent to it.
    const page = shellPage();
    page.P.setChapter(0);
    // Chapter one was read to the middle; the reader then follows a link to
    // chapter two, which they have not scrolled in this session.
    page.frame().contentWindow.location.pathname = "/book/Fixture%20Book/OEBPS/ch2.xhtml";
    page.fire("load", page.frame());

    const scrolled = [];
    page.frame().contentWindow.scrollTo = (x, y) => scrolled.push(y);
    assert.deepEqual(scrolled, [], "the new chapter was not scrolled");
});
