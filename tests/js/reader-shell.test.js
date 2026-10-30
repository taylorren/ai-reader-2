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
    saved_seq: 0,
    target_highlight: "",
});

function shellPage(options = {}) {
    const page = createPage({ book: options.book || book(), files: options.files });
    page.route(/\/api\/progress$/, { status: "success" });
    page.route(/\/api\/footnotes\//, { edges: [] });
    page.route(/\/api\/text\//, { blocks: [] });
    page.route(/\/api\/highlights\//, { highlights: [] });
    // The frame's own window: the shell reads its location, listens for keys
    // inside it, and on scroll reads its document.
    page.frame().contentWindow = frameWindow("/book/Fixture%20Book/OEBPS/ch1.xhtml");
    return page;
}

// The frame's window, with listeners the test can fire — a real frame is its
// own event tree, which is the whole point of P1-5.
function frameWindow(pathname) {
    return {
        location: { pathname },
        document: { documentElement: { scrollHeight: 4000 } },
        innerHeight: 800,
        _listeners: {},
        addEventListener(type, fn) { (this._listeners[type] ||= []).push(fn); },
        scrollTo() {},
    };
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


// -- the keyboard, inside the book (REVIEW P1-5) ---------------------------

test("the arrow keys turn the chapter when the reader is inside the book", () => {
    // A frame is its own event tree: the shell's keydown listener never sees a
    // key pressed in the book, and clicking into the book is what a reader does
    // before selecting text — so the advertised navigation used to die on the
    // first click.
    const page = shellPage();
    page.fire("load", page.frame());          // the frame wires its own keys

    page.fire("keydown", page.frame().contentWindow, { key: "ArrowRight" });

    assert.equal(page.el("top-position").textContent, "2 / 2");
    assert.equal(page.el("bottom-position").textContent, "2 / 2");
    const saved = progressSaves(page).pop();
    assert.ok(saved, "the chapter turn was recorded");
    assert.equal(JSON.parse(saved.body).chapter_index, 1);
});

test("a chapter turn records the chapter being left before the one entered", () => {
    // Progress writes are fire-and-forget, so the save for the chapter left can
    // arrive after the new chapter's — which moved the stored position backwards
    // (REVIEW P2-8). The outgoing chapter is written first, with a sequence.
    const page = shellPage();
    page.frame().contentWindow.scrollY = 1600;      // half of the scrollable
    page.fire("load", page.frame());

    page.fire("keydown", page.frame().contentWindow, { key: "ArrowRight" });

    const saves = progressSaves(page);
    assert.equal(saves.length, 2, "one for the chapter left, one for the one entered");
    const left = JSON.parse(saves[0].body);
    const entered = JSON.parse(saves[1].body);
    assert.equal(left.chapter_index, 0);
    assert.equal(left.scroll_percent, 50);
    assert.equal(entered.chapter_index, 1);
    assert.equal(entered.scroll_percent, 0);
    assert.ok(entered.seq > left.seq,
              `the later write must outrank the earlier: ${entered.seq} vs ${left.seq}`);
});

test("the first write outranks the sequence the server already holds", () => {
    // The guard refuses a write whose `seq` is older than the stored one, and
    // the client cannot otherwise learn that value — so a stored sequence far
    // ahead of the client's clock refused every write for that book, silently
    // and for good (PITFALLS). The shell passes the stored sequence in, so the
    // counter starts above it and the book records progress again.
    const stored = 10 ** 15;
    const page = shellPage({ book: { ...book(), saved_seq: stored } });
    page.frame().contentWindow.scrollY = 1600;
    page.fire("load", page.frame());

    page.fire("keydown", page.frame().contentWindow, { key: "ArrowRight" });

    const saved = progressSaves(page).pop();
    assert.ok(saved, "the position was written");
    const seq = JSON.parse(saved.body).seq;
    assert.ok(seq > stored,
              `the write must outrank the stored sequence: ${seq} vs ${stored}`);
});

test("coming back to a chapter restores where the reader was in it", () => {
    // A → B → A used to start A at the top: entering B wrote 0 over A's position
    // in the session's memory (P2-8).
    const page = shellPage();
    page.frame().contentWindow.scrollY = 1600;
    page.fire("load", page.frame());

    page.fire("keydown", page.frame().contentWindow, { key: "ArrowRight" });   // A → B
    page.fire("keydown", page.frame().contentWindow, { key: "ArrowLeft" });    // B → A

    const scrolled = [];
    page.frame().contentWindow.scrollTo = (x, y) => scrolled.push(y);
    page.frame().contentWindow.location.pathname = "/book/Fixture%20Book/OEBPS/ch1.xhtml";
    page.fire("load", page.frame());

    assert.deepEqual(scrolled, [1600], "back to the middle of chapter one");
});


test("the arrow keys do not walk past the ends of the book", () => {
    const page = shellPage();
    page.fire("load", page.frame());

    page.fire("keydown", page.frame().contentWindow, { key: "ArrowLeft" });

    assert.equal(page.el("top-position").textContent, "1 / 2");
    assert.equal(progressSaves(page).length, 0, "no chapter change to record");
});

test("ESC closes the image popup from inside the book", () => {
    const page = shellPage();
    page.fire("load", page.frame());
    page.el("image-popup").hidden = false;

    page.fire("keydown", page.frame().contentWindow, { key: "Escape" });

    assert.equal(page.el("image-popup").hidden, true);
});

test("a popped-out image is modal: the arrows do not turn the chapter behind it", () => {
    const page = shellPage();
    page.fire("load", page.frame());
    page.el("image-popup").hidden = false;

    page.fire("keydown", page.frame().contentWindow, { key: "ArrowRight" });

    assert.equal(page.el("top-position").textContent, "1 / 2");
    assert.equal(page.el("image-popup").hidden, false, "still open");
});

test("a book's own form keeps its keys", () => {
    const page = shellPage();
    page.fire("load", page.frame());

    page.fire("keydown", page.frame().contentWindow,
              { key: "ArrowRight", target: { tagName: "INPUT" } });

    assert.equal(page.el("top-position").textContent, "1 / 2");
});
