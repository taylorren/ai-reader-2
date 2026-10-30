/* The reader shell: drives the sandboxed iframe through the spine, and
   dresses the book's own document with the paper experience (injected —
   the book's scripts never run). Layout mirrors the reference reader:
   collapsible TOC sidebar, slim bar, chapter frame. */

// The pure helpers live in reader-core.js (loaded first), shared with
// panel.js and unit-tested in Node — REVIEW T1.
const { clampSize, fileURL, tocKey, blockElement, firstVisibleBlockId,
        headingForLabel, findLatexSpans } = window.ReaderCore;

const app = document.getElementById("reader-app");
const frame = document.getElementById("chapter-frame");
const tocList = document.getElementById("toc-list");
const styleToggle = document.getElementById("style-toggle");
const themeToggle = document.getElementById("theme-toggle");

const FONTS = {
    song: 'Georgia, "Noto Serif CJK SC", "Songti SC", "SimSun", serif',
    hei: '-apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
    kai: '"Kaiti SC", "STKaiti", KaiTi, "Noto Serif CJK SC", serif',
    enserif: 'Georgia, "Palatino Linotype", "Times New Roman", serif',
    ensans: 'Helvetica, Arial, "Segoe UI", "Helvetica Neue", sans-serif',
};

const state = {
    open: localStorage.getItem("sidebarOpen") !== "false",
    theme: localStorage.getItem("reader-theme") === "dark" ? "dark" : "light",
    mode: localStorage.getItem("reader-style-mode") === "book" ? "book" : "paper",
    font: FONTS[localStorage.getItem("reader-font")]
        ? localStorage.getItem("reader-font") : "song",
    size: clampSize(parseInt(localStorage.getItem("reader-font-size") || "19", 10)),
};

// The same directory, decoded. The server builds srcs with Python's `quote`,
// which escapes "(" and ")" as %28/%29; `encodeURIComponent` leaves them
// literal — so an encoded-form comparison silently failed for any slug with
// parentheses (most translated titles have them) and the frame-load handler
// bailed before wiring the panel. Compare decoded paths instead.
const bookPrefix = "/book/" + BOOK.slug + "/";

// The contents entry the reader clicked, until the frame reaches it. A click
// that changes `frame.src` leaves the old document on screen, so the heading
// asked for cannot be measured at that instant — and an entry that names a
// heading the book gave no id has no fragment to carry that aim in the frame's
// URL, so the entry itself has to travel: it keeps the sidebar lit across the
// load, and `onFrameLoad` aims the frame at it once the chapter is in it.
let pendingEntry = null;

/* Move to a chapter, optionally aiming at one of its headings.

`target` is what a contents entry names: `anchor` — the id the book gave the
heading — or, a book that gave it none, `label`, which the heading carries as
its own text (ReaderCore.headingForLabel) — plus `link`, the entry itself. A
heading's id is a fragment the frame's URL can carry; a label is not, so the
shell aims the frame itself. */
function load(index, target = {}) {
    const { anchor, label, link } = target;
    index = Math.max(0, Math.min(BOOK.spine.length - 1, index));
    // Already here: the entry names a heading inside the chapter on screen, so
    // the frame is scrolled to it directly and nothing is loaded — a fragment
    // navigation is not the way either (re-assigning `frame.src` with only a new
    // fragment does not move every browser). A chapter entry that names no
    // heading has nothing to do at all: re-loading the frame would flash the
    // chapter and write a progress row for a move that never happened. The nav
    // buttons are disabled at the ends for the same reason — and the arrow keys
    // reach those ends too (REVIEW P1-5).
    if (index === BOOK.index) {
        jumpToTarget(anchor, label);
        return;
    }
    // Record where the reader was in the chapter they are leaving, *before* the
    // index moves: `lastPercentByChapter` is what restoreScroll() consults, and
    // the 0 written for the chapter being entered must not erase the chapter
    // being left — that is what made A → B → A start A at the top (REVIEW P2-8).
    saveProgress(lastPercentByChapter.has(BOOK.index)
        ? lastPercentByChapter.get(BOOK.index)
        : frameScrollPercent());
    BOOK.index = index;
    // The entry asked for, across the load — and the fragment, when the book
    // gave the heading an id for the frame's URL to carry.
    pendingEntry = link || null;
    frame.src = fileURL(BOOK.slug, BOOK.spine[index], anchor);
    if (scrollSaveTimer) clearTimeout(scrollSaveTimer);
    // The chapter being entered: 0 when the session knows nothing about it, and
    // its remembered position when it does. Returning to a chapter is a return
    // to where the reader was — restoreScroll() is about to put them there — not
    // a fresh start, and writing 0 unconditionally is what made A → B → A begin
    // at the top (REVIEW P2-8).
    saveProgress(lastPercentByChapter.get(BOOK.index) ?? 0);
    mark();
    ReaderPanel.setChapter(index);
}

function mark() {
    for (const nav of navs) {
        nav.pos.textContent = (BOOK.index + 1) + " / " + BOOK.spine.length;
        nav.prev.disabled = BOOK.index <= 0;
        nav.next.disabled = BOOK.index >= BOOK.spine.length - 1;
    }
    // Refresh-proof: the URL always names the chapter being read. Full
    // progress — scroll percent, resume — lands in P4 with the database.
    history.replaceState(null, "",
        "/read/" + encodeURIComponent(BOOK.slug) + "/" + BOOK.index);
    syncTocHighlight();
}

/* The TOC highlight follows the heading, not merely the chapter. A book's
   contents usually names sections *inside* one document: epubx splits the nav
   href, so those entries share the chapter's `href` and differ only in what
   they point at inside it — the fragment it hands over as `anchor` (nav.py), or,
   for a book whose headings carry no id at all, the label the heading itself
   spells out. Measure instead: of this chapter's entries, the last heading above
   the reading line is the one being read. */

const TOC_READING_LINE = 0.3; // fraction of the viewport a heading owns

function frameAnchorElement(doc, anchor) {
    // A fragment names an id, or a legacy named anchor.
    return doc.getElementById(anchor) || doc.getElementsByName(anchor)[0] || null;
}

/* The element a contents entry names in the frame's own document: the heading
   the book gave an id to, or — a book that gave it none — the heading whose own
   text is the entry's label. Null when the document carries neither, which is
   how an anchor the book never wrote is treated everywhere here. */
function frameTargetElement(doc, anchor, label) {
    if (!doc || !doc.body) return null;
    if (anchor) return frameAnchorElement(doc, anchor);
    return headingForLabel(doc, label);
}

/* Aim the frame at a target inside the chapter already on screen, and light the
   entry that names it. Returns whether the document defines it: a target it does
   not is nothing to do rather than a reason to load something. */
function jumpToTarget(anchor, label) {
    const target = frameTargetElement(frameDocument(), anchor, label);
    if (!target) return false;
    pendingEntry = null;          // the frame is where the reader asked
    target.scrollIntoView({ block: "start" });
    syncTocHighlight();
    return true;
}

// The entry being read: of this chapter's entries, the last heading above the
// reading line. Entries whose target the document never defines are stepped
// over, and the chapter's own entry — the first link naming this document — is
// what is left when nothing is above the line.
function frameTargetInView(path) {
    const doc = frameDocument();
    if (!doc || !doc.body) return null;
    let line, innerHeight, atEnd;
    try {
        const win = frame.contentWindow;
        innerHeight = win.innerHeight || 0;
        line = innerHeight * TOC_READING_LINE;
        // A heading the frame cannot bring up to the line — the chapter's last
        // section, with less than a screenful of text after it — is the one being
        // read once the frame has reached its end. Measured rather than
        // remembered, so the highlight is right however the reader got there.
        const max = doc.documentElement.scrollHeight - innerHeight;
        atEnd = max > 0 && win.scrollY >= max - 1;
    } catch {
        return null; // opaque origin: nothing to measure
    }
    let inView = null;
    const links = tocList.querySelectorAll(
        `a[data-anchor][data-path="${CSS.escape(path)}"], `
        + `a[data-heading][data-path="${CSS.escape(path)}"]`);
    for (const link of links) {
        const target = frameTargetElement(doc, link.dataset.anchor, link.dataset.heading);
        if (!target) continue;
        const top = target.getBoundingClientRect().top;
        if (top <= line || (atEnd && top <= innerHeight)) inView = link;
    }
    return inView;
}

function syncTocHighlight() {
    const path = BOOK.spine[BOOK.index];
    if (!path) return;
    const links = tocList.querySelectorAll(`a[data-path="${CSS.escape(path)}"]`);
    if (!links.length) return;
    // The entry a click asked for wins until the frame reaches it — its own
    // scroll clears the choice (queueTocSync) — and the reading line decides
    // otherwise. The chapter's own entry is the fallback: the first link naming
    // this document, which is the one that owns it in the outline.
    const active = pendingEntry || frameTargetInView(path) || links[0];
    const previous = tocList.querySelector("a.current");
    if (previous === active) return;
    // The entry being read must be visible: open its branch and the branches
    // above it. Done only when the active entry changes, so a reader can still
    // collapse it by hand without it springing back on the next sync.
    revealEntry(active);
    if (previous) previous.classList.remove("current");
    active.classList.add("current");
    active.scrollIntoView({ block: "nearest" });
}

/* A deep outline — a volume of forty chapters — is unusable fully open, so
   every entry with children carries a caret and starts collapsed. The branch
   of the chapter being read opens automatically (syncTocHighlight), and a
   reader's own toggles are remembered per book. */

const TOC_STORE_KEY = "tocExpanded:" + BOOK.slug;

function loadExpanded() {
    try {
        return new Set(JSON.parse(localStorage.getItem(TOC_STORE_KEY) || "[]"));
    } catch {
        return new Set();
    }
}

function saveExpanded(expanded) {
    try {
        localStorage.setItem(TOC_STORE_KEY, JSON.stringify([...expanded]));
    } catch {
        // Storage full or disabled: the pane still works, just not remembered.
    }
}

// Open or close a branch. `remember` is true only for a reader's own click —
// automatic reveals are not written, so the stored set stays the reader's.
function setBranch(li, expanded, remember) {
    li.classList.toggle("expanded", expanded);
    li.classList.toggle("collapsed", !expanded);
    const caret = li.querySelector(":scope > .toc-node > .toc-caret");
    if (caret) caret.setAttribute("aria-expanded", String(expanded));
    if (remember && li.dataset.tocKey) {
        const stored = loadExpanded();
        if (expanded) stored.add(li.dataset.tocKey);
        else stored.delete(li.dataset.tocKey);
        saveExpanded(stored);
    }
}

// Open the entry's own branch and every branch above it, so the entry being
// read is on screen together with its sub-entries.
function revealEntry(link) {
    for (let li = link.closest("li"); li; li = li.parentElement.closest("li")) {
        if (li.classList.contains("toc-branch") && li.classList.contains("collapsed")) {
            setBranch(li, true, false);
        }
    }
}

function tocLabel(node, parentHref) {
    if (node.href && BOOK.spine.includes(node.href)) {
        const link = document.createElement("a");
        link.href = "#";
        link.dataset.path = node.href;
        // What the entry points at inside that document. An entry that names a
        // heading *inside* the document its parent names is a section: the
        // fragment the book wrote for it, or — a book whose headings carry no id
        // — the label the heading itself spells out. The entry that names the
        // document is not a section and points at nothing more specific.
        const section = Boolean(node.anchor)
            || Boolean(parentHref && node.href === parentHref);
        if (node.anchor) link.dataset.anchor = node.anchor;
        else if (section && node.label) link.dataset.heading = node.label;
        link.textContent = node.label || node.href;
        const index = BOOK.spine.indexOf(node.href);
        link.onclick = (event) => {
            event.preventDefault();
            load(index, { anchor: node.anchor || null,
                          label: link.dataset.heading || null, link });
        };
        return link;
    }
    const span = document.createElement("span");
    span.textContent = node.label || "";
    return span;
}

// `parentHref` is the href of the entry this one hangs under, so a section —
// an entry naming a heading inside the document its parent names — can be told
// from the entry that names the document itself (see tocLabel).
function buildTocList(nodes, expanded, parentHref) {
    const ul = document.createElement("ul");
    ul.className = "toc-children";
    for (const node of nodes) {
        const li = document.createElement("li");
        const children = node.children || [];
        const row = document.createElement("div");
        row.className = "toc-node";

        if (children.length) {
            const open = expanded.has(tocKey(node));
            li.className = open ? "toc-branch expanded" : "toc-branch collapsed";
            li.dataset.tocKey = tocKey(node);
            const caret = document.createElement("button");
            caret.type = "button";
            caret.className = "toc-caret";
            caret.setAttribute("aria-expanded", String(open));
            caret.title = "展开 / 收起";
            caret.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                setBranch(li, !li.classList.contains("expanded"), true);
            });
            row.appendChild(caret);
        } else {
            // A leaf keeps the caret's width, so labels stay aligned.
            const spacer = document.createElement("i");
            spacer.className = "toc-caret toc-caret-spacer";
            spacer.setAttribute("aria-hidden", "true");
            row.appendChild(spacer);
        }

        row.appendChild(tocLabel(node, parentHref));
        li.appendChild(row);
        if (children.length) {
            li.appendChild(buildTocList(children, expanded, node.href));
        }
        ul.appendChild(li);
    }
    return ul;
}

function renderToc(nodes, container) {
    container.appendChild(buildTocList(nodes, loadExpanded(), null));
}

function applySidebar() {
    app.classList.toggle("sidebar-collapsed", !state.open);
    localStorage.setItem("sidebarOpen", state.open ? "true" : "false");
}

document.getElementById("sidebar-collapse").addEventListener("click", () => {
    state.open = false;
    applySidebar();
});
document.getElementById("sidebar-expand").addEventListener("click", () => {
    state.open = true;
    applySidebar();
});

document.addEventListener("keydown", (event) => {
    if (event.target.tagName === "INPUT" || event.target.tagName === "TEXTAREA") return;
    // A popped-out image is modal: ESC closes it, and the arrows do not turn
    // the chapter behind it.
    if (!imagePopup.hidden) {
        if (event.key === "Escape") hideImagePopup();
        return;
    }
    if (event.key === "Escape") hidePopup();
    if (event.key === "ArrowLeft") load(BOOK.index - 1);
    if (event.key === "ArrowRight") load(BOOK.index + 1);
});

/* ---- The reading experience: paper styles injected into the frame ----

The frame is same-origin (sandbox="allow-same-origin"), so the shell can
dress the book's document: a paper sheet on the desk, serif typography,
indented paragraphs — with !important where the book's own CSS must yield.
The book's own scripts still never run. Choosing 书本 removes the injection
and restores the publisher's design untouched. */

const READER_STYLE_ID = "reader-style";

// A click on an image pops it out into the shell (see showImagePopup). The
// cursor is the only hint inside the frame's own document, so it is injected
// there — with `!important` because a book's own CSS must not hide it. It
// stays in 书本 mode too: the pop-out is a reading aid, not paper styling.
const IMAGE_CSS = `
img[data-reader-zoom] { cursor: zoom-in !important; }
`;

// Painted highlights live in the frame's document, so their colours must be
// injected there too — and they stay visible in 书本 mode, where the book's
// own CSS otherwise rules.
const HIGHLIGHT_CSS = `
mark.reader-highlight { cursor: pointer; border-radius: 2px; color: inherit; }
mark.reader-highlight.hl-fact_check { background: rgba(217, 164, 65, 0.42); }
mark.reader-highlight.hl-discussion { background: rgba(90, 143, 214, 0.38); }
mark.reader-highlight.hl-comment { background: rgba(79, 174, 122, 0.38); }
mark.reader-highlight.hl-highlight { background: rgba(176, 111, 208, 0.34); }
mark.reader-highlight.flash { animation: reader-hl-flash 0.8s ease 3; }
@keyframes reader-hl-flash {
  50% { background: rgba(255, 208, 84, 0.9); }
}
`;

// The "last read position" rule is drawn in the frame's document as well, so
// its colours must be injected there too. It is *positioned*, not in the flow:
// an in-flow element would shift the text under the reader, and Firefox's
// scroll anchoring would compensate by scrolling past it — leaving the badge
// just above the fold.
const RESUME_CSS = `
body { position: relative; }
.reader-resume-line {
  position: absolute;
  left: 0;
  right: 0;
  height: 0;
  border-top: 2px solid #2f7bd6;
  cursor: pointer;
  /* The retire is a fade, not a pop. 500ms must match RESUME_MARKER_FADE_MS,
     the timer that removes the node once the transition has finished. */
  transition: opacity 0.5s ease;
}
/* Asked to go — the reader scrolled on, or clicked it: fade out, and stop
   taking clicks while it goes. */
.reader-resume-line.retiring {
  opacity: 0;
  pointer-events: none;
}
.reader-resume-line span {
  position: absolute;
  right: 0;
  top: -0.85em;
  padding: 2px 8px;
  border-radius: 4px 4px 0 4px;
  background: #2f7bd6;
  color: #ffffff;
  font-size: 0.72em;
  line-height: 1.7;
  white-space: nowrap;
}
`;

function framePaperCSS() {
    const dark = state.theme === "dark";
    const paper = dark
        ? { bg: "#26211b", ink: "#cfc4b0", link: "#d5ab74",
            shadow: "0 10px 28px rgba(0, 0, 0, 0.45)",
            selection: "rgba(240, 163, 112, 0.25)" }
        : { bg: "#f7f3e8", ink: "#3a3226", link: "#8c5d2e",
            shadow: "0 10px 28px rgba(70, 55, 32, 0.12)",
            selection: "rgba(156, 79, 46, 0.22)" };
    return `
html { background: transparent !important; }
body {
  max-width: 780px !important;
  margin: 28px auto 48px !important;
  padding: 70px 64px !important;
  background: ${paper.bg} !important;
  color: ${paper.ink} !important;
  box-shadow: ${paper.shadow} !important;
  border-radius: 10px;
  min-height: calc(100vh - 76px) !important;
  font-family: ${FONTS[state.font]} !important;
  font-size: ${state.size}px !important;
  line-height: 1.95 !important;
  letter-spacing: 0.01em !important;
}
p { text-indent: 1.4em !important; margin-bottom: 1.25em !important; }
h1 + p, h2 + p, h3 + p { text-indent: 0 !important; }
h1, h2, h3 { line-height: 1.4 !important; margin-top: 1.9em !important; margin-bottom: 0.9em !important; }
img, svg, video, table { max-width: 100% !important; height: auto !important; }
pre { white-space: pre-wrap !important; overflow-x: auto !important; }
a { color: ${paper.link} !important; }
/* A note's own label: the book's link back to the marker it was printed
   against. 项狄传's stylesheet prints it at full size (its calibre12 class is
   1em, nudged 4px up), so it runs straight into the note's first word — the
   paper sheet gives it the space the book did not. Marked by wireMarkers; 书本
   mode leaves the publisher's own spacing alone. */
[data-note-label] { margin-right: 0.3em !important; }
::selection { background: ${paper.selection} !important; }
`;
}

function applyFrameStyle() {
    let doc;
    try {
        doc = frame.contentDocument;
    } catch {
        return; // opaque origin: nothing to dress
    }
    if (!doc || !doc.documentElement) return;
    let style = doc.getElementById(READER_STYLE_ID);
    if (!style) {
        style = doc.createElement("style");
        style.id = READER_STYLE_ID;
        (doc.head || doc.documentElement).appendChild(style);
    }
    if (state.mode === "book") {
        // The publisher's design, untouched: no paper stylesheet — but the
        // painted highlights, the resume rule, the image cursor and the drawn
        // formulas still need to be there.
        style.textContent = IMAGE_CSS + HIGHLIGHT_CSS + RESUME_CSS + MATH_CSS;
        return;
    }
    style.textContent = framePaperCSS() + IMAGE_CSS + HIGHLIGHT_CSS + RESUME_CSS
        + MATH_CSS;
}

function applyTheme() {
    document.body.classList.toggle("dark-mode", state.theme === "dark");
    themeToggle.textContent = state.theme === "dark" ? "☀️" : "🌙";
    localStorage.setItem("reader-theme", state.theme);
}

function applyMode() {
    styleToggle.setAttribute("aria-checked", String(state.mode === "paper"));
    localStorage.setItem("reader-style-mode", state.mode);
    applyFrameStyle();
}

themeToggle.addEventListener("click", () => {
    state.theme = state.theme === "dark" ? "light" : "dark";
    applyTheme();
    applyFrameStyle();
});

styleToggle.addEventListener("click", () => {
    state.mode = state.mode === "paper" ? "book" : "paper";
    applyMode();
});

const fontSelect = document.getElementById("font-select");
fontSelect.value = state.font;
fontSelect.addEventListener("change", () => {
    state.font = fontSelect.value;
    localStorage.setItem("reader-font", state.font);
    applyFrameStyle();
});

function wireNav(prevId, nextId, positionId) {
    const prev = document.getElementById(prevId);
    const next = document.getElementById(nextId);
    const pos = document.getElementById(positionId);
    prev.addEventListener("click", () => load(BOOK.index - 1));
    next.addEventListener("click", () => load(BOOK.index + 1));
    return { prev, next, pos };
}

// The same nav in both bars — same style, so one teaches the other.
const navs = [
    wireNav("top-prev", "top-next", "top-position"),
    wireNav("bottom-prev", "bottom-next", "bottom-position"),
];

/* ---- Progress: where you were is where you return ----

The chapter lives in the URL (refresh-safe); the position within the
chapter is a scroll percent — restored on boot and on in-session returns,
saved on chapter change and debounced while scrolling. The database row
carries it; the database is never disturbed by a failed save. */

let pendingRestore = {
    chapter: BOOK.index,
    percent: Number(BOOK.saved_percent || 0),
    // The stored position's identity: the block the reader stopped in. The
    // percent is the fallback, for a row written before the anchor existed
    // (REVIEW P2-10).
    block_id: BOOK.saved_block_id || null,
};
const lastPercentByChapter = new Map();

/* Progress writes carry a sequence, because they are fire-and-forget: the save
   for the chapter a reader just left can reach the server after the one for the
   chapter they are in, and the stored position then moved *backwards* a chapter
   (REVIEW P2-8). Strictly increasing, and comparable across sessions: a counter
   alone would restart at 1 after a reload — *below* whatever the server has
   stored — and every write after a refresh would be dropped as stale. */
let progressSeq = 0;

function nextProgressSeq() {
    progressSeq = Math.max(progressSeq + 1, Date.now());
    return progressSeq;
}
let scrollSaveTimer = null;

function frameScrollPercent() {
    try {
        const win = frame.contentWindow;
        const scrollable = win.document.documentElement;
        const max = scrollable.scrollHeight - win.innerHeight;
        if (max <= 0) return 0;
        return Math.max(0, Math.min(100, (100 * win.scrollY) / max));
    } catch {
        return 0; // opaque origin: nothing measurable
    }
}

function saveProgress(percent) {
    lastPercentByChapter.set(BOOK.index, percent);
    // The position's identity, measured *now*: `load()` moves the frame on as
    // soon as this returns, so an anchor measured after an await would describe
    // the chapter being entered rather than the one being left. Blocks not in
    // hand yet — the first scrolls of a chapter, before the panel has fetched
    // them — means percent only, exactly the write this made before the anchor
    // existed (REVIEW P2-10).
    const blocks = ReaderPanel.cachedBlocks(BOOK.index);
    const doc = frameDocument();
    const anchor = blocks && doc ? firstVisibleBlockId(blocks, doc, 0) : null;
    fetch("/api/progress", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            book_id: BOOK.slug,
            chapter_index: BOOK.index,
            scroll_percent: Math.round(percent),
            block_id: anchor,
            seq: nextProgressSeq(),
        }),
    }).catch(() => {}); // a failed save must never disturb the reading
}

function scheduleProgressSave() {
    if (scrollSaveTimer) clearTimeout(scrollSaveTimer);
    scrollSaveTimer = setTimeout(() => saveProgress(frameScrollPercent()), 500);
}

/* The resume rule is drawn once per session, on the return that restored a
   saved position — never resurrected after the reader moves on. */
let resumeMarkerPlaced = false;

/* The "last read position" rule: a line drawn across the column where the
   reader stopped, injected into the frame's document (in memory only — the
   book's file is never touched, exactly like the highlight marks). It is
   anchored to the block that the restored scroll put at the top of the
   viewport, so it sits on a paragraph boundary rather than mid-line. */

const RESUME_MARK_BLOCKS = ["P", "H1", "H2", "H3", "H4", "H5", "H6", "LI",
                            "BLOCKQUOTE", "PRE", "TD", "DT", "DD"];
const RESUME_MARK_SELECTOR = RESUME_MARK_BLOCKS.join(",").toLowerCase();

function clearResumeMarker() {
    const doc = frameDocument();
    const existing = doc && doc.querySelector(".reader-resume-line");
    if (existing) existing.remove();
}

/* The badge is a one-off: the reader scrolling away retires it, exactly as
   clicking it does. Two things keep that from feeling abrupt:

   - The restore's own `scrollTo()` fires scroll events as well, so the offset
     the badge sits at is remembered — an event still on that offset is the
     restore, not the reader moving. The offset is re-read from the window
     rather than captured from the event, so a scroll delivered after the
     delayed re-aim still compares against where the badge actually is.
   - Scrolling *pauses* the badge rather than killing it: the retire is
     debounced, so it stays put while the reader is moving, and only fades out
     once they have settled. */
const RESUME_MARKER_RETIRE_MS = 1500;   // after the reader stops scrolling
const RESUME_MARKER_FADE_MS = 500;      // must match RESUME_CSS's transition

let resumeMarkerTop = null;        // the offset the badge was placed at
let resumeMarkerRetired = false;   // the reader moved on: never place it again
let resumeMarkerTimer = null;      // the queued retire, while the reader scrolls

function retireResumeMarker() {
    resumeMarkerRetired = true;
    resumeMarkerTop = null;
    if (resumeMarkerTimer) {
        clearTimeout(resumeMarkerTimer);
        resumeMarkerTimer = null;
    }
    const doc = frameDocument();
    const line = doc && doc.querySelector(".reader-resume-line");
    if (!line) return;
    // Fade first, drop after: a removed node cannot transition, so the class
    // starts the fade and the timer takes it out once the fade is done.
    line.classList.add("retiring");
    setTimeout(() => line.remove(), RESUME_MARKER_FADE_MS);
}

function scheduleResumeMarkerRetire() {
    if (resumeMarkerTimer) clearTimeout(resumeMarkerTimer);
    resumeMarkerTimer = setTimeout(retireResumeMarker, RESUME_MARKER_RETIRE_MS);
}

function retireResumeMarkerOnScroll() {
    if (resumeMarkerTop === null || resumeMarkerRetired) return;
    let top;
    try {
        top = frame.contentWindow.pageYOffset || 0;
    } catch { return; }                        // opaque origin: nothing to measure
    if (Math.abs(top - resumeMarkerTop) < 2) return;  // the restore's own scroll
    scheduleResumeMarkerRetire();
}

function placeResumeMarker() {
    const doc = frameDocument();
    if (!doc || !doc.body) return;
    clearResumeMarker();
    const win = frame.contentWindow;
    const anchor = resumeAnchorBlock(doc);
    if (!anchor) return;
    // Positioned, not inserted into the flow: no layout shift, so the restored
    // scroll stays exactly where the reader left it — nothing is nudged, and
    // nothing fights the rule for the viewport. The rule is drawn at the
    // paragraph's own top edge, so it sits in the gap between paragraphs
    // instead of cutting across a line of text.
    const pageY = win.pageYOffset || 0;
    const bodyTop = doc.body.getBoundingClientRect().top + pageY;
    const anchorTop = anchor.getBoundingClientRect().top + pageY;
    const line = doc.createElement("div");
    line.className = "reader-resume-line";
    line.title = "点击隐藏";
    line.style.top = Math.round(anchorTop - bodyTop) + "px";
    const tag = doc.createElement("span");
    tag.textContent = "上次读到此处";
    line.appendChild(tag);
    line.addEventListener("click", retireResumeMarker);
    doc.body.appendChild(line);
    // Where the restore left the reader: the scroll event our own `scrollTo()`
    // fires lands here, and must not be mistaken for the reader moving.
    resumeMarkerTop = win.pageYOffset || 0;
    resumeMarkerRetired = false;
    // A re-aim replaces the badge, so a retire queued against the old one is
    // stale: drop it rather than let it fade the fresh badge out.
    if (resumeMarkerTimer) {
        clearTimeout(resumeMarkerTimer);
        resumeMarkerTimer = null;
    }
}

/* The resume rule is drawn at "the first paragraph boundary at or below the top
   edge", which skips a paragraph that is only partly scrolled past — a rule at
   its top edge would be above the fold. */
const RESUME_LINE_MIN_TOP = 2;

/* Where an anchored block is put: just *above* the viewport's top edge, so the
   block contains the reading line.

   That is the invariant that keeps the anchor stable. The position is stored
   with the block containing the line (`firstVisibleBlockId`), so a resume that
   put the block's top *below* the line would — wherever two blocks are adjacent,
   with no margin between them to fall into — have the next save re-derive the
   paragraph before it, and every open of the book would walk the anchor one
   paragraph backwards. A paragraph's margin usually hides the two pixels this
   costs (REVIEW P2-10). */
const RESUME_BLOCK_TOP = -2;

/* The first paragraph boundary at or below the top edge: the rule sits in the
   gap above it. The paragraph the reader stopped inside is usually partly
   scrolled past, and a rule at its top edge would be above the fold. */
function resumeAnchorBlock(doc) {
    for (const block of doc.querySelectorAll(RESUME_MARK_SELECTOR)) {
        if (block.getBoundingClientRect().top >= RESUME_LINE_MIN_TOP) return block;
    }
    return doc.body.querySelector(RESUME_MARK_SELECTOR);
}

/* Scroll the anchored block to the top of the frame's viewport.

   A block is an identity: it does not move when the text reflows, which is the
   whole point of storing it (REVIEW P2-10). Matched by text, the way a
   highlight is, because the served document carries no ids from the extractor.
   False when the block is not in hand or not in this document — the caller then
   falls back to the percent. */
function scrollToBlock(blockId, chapter) {
    const blocks = ReaderPanel.cachedBlocks(chapter);
    const block = blocks && blocks.find((item) => item.id === blockId);
    const doc = frameDocument();
    if (!block || !doc) return false;
    const element = blockElement(doc, block);
    if (!element) return false;
    try {
        const win = frame.contentWindow;
        const offset = (win.pageYOffset || 0)
                     + element.getBoundingClientRect().top - RESUME_BLOCK_TOP;
        win.scrollTo(0, Math.round(offset));
        return true;
    } catch {
        return false;   // opaque origin: nothing to scroll
    }
}

function frameOffset() {
    try {
        return frame.contentWindow.pageYOffset || 0;
    } catch {
        return 0;
    }
}

function restoreScroll(chapter) {
    // A "在书中定位" deep link outranks the saved position: the reader asked
    // for that passage, not for where they left off. Its delayed scroll would
    // otherwise land after the highlight's, pulling the reader away from it.
    if (BOOK.target_highlight) return;
    // Nothing can be measured or scrolled until the *chapter* is in the frame.
    // At boot the shell runs this before the frame has loaded, and consuming the
    // saved position then would lose it for good: the shell's `load` event may
    // already have fired (a fast local server, a cached chapter), so nothing
    // would run this again. Guarded rather than assumed — the frame's URL is the
    // only thing that says which chapter is really on screen (REVIEW P1-6's
    // shape; found by T1's browser smoke).
    if (frameChapterIndex() !== chapter) return;
    let percent = null;
    let blockId = null;
    if (pendingRestore && pendingRestore.chapter === chapter) {
        percent = pendingRestore.percent;
        blockId = pendingRestore.block_id;
        pendingRestore = null;
    } else if (lastPercentByChapter.has(chapter)) {
        percent = lastPercentByChapter.get(chapter);
    }
    if (!(percent > 0) && !blockId) return;
    // The block first: it is an identity, so it lands on the same paragraph
    // however the text has reflowed since — a font-size change, a window
    // resize, a different device. The percent is the fallback, for a row written
    // before the anchor existed and for a block this document no longer has
    // (REVIEW P2-10).
    const scrollToSaved = () => {
        if (blockId && scrollToBlock(blockId, chapter)) return;
        if (!(percent > 0)) return;
        try {
            const win = frame.contentWindow;
            const max = win.document.documentElement.scrollHeight - win.innerHeight;
            if (max > 0) win.scrollTo(0, Math.round((percent / 100) * max));
        } catch { /* opaque origin */ }
    };
    // Layout settles as images load; restore now and once more shortly.
    scrollToSaved();
    // The rule marks where the page opened — but only for the return that this
    // session resumed, and only once.
    const placed = !resumeMarkerPlaced;
    if (placed) {
        resumeMarkerPlaced = true;
        placeResumeMarker();
    }
    // The anchor needs the chapter's blocks, which the panel fetches on this
    // same frame load. The percent has already put the reader in the right
    // region, so nothing waits on them; this is the re-aim, and it happens when
    // they arrive rather than after a guessed delay.
    if (blockId) {
        ReaderPanel.blocksFor(chapter).then(() => {
            const before = frameOffset();
            scrollToSaved();
            // The anchor moved the page, so the rule belongs where the reader is
            // now — and this is still the restore's own scroll, not the reader
            // moving on, so the badge must not be retired by it.
            if (placed && !resumeMarkerRetired && frameOffset() !== before) {
                placeResumeMarker();
            }
        }).catch(() => {});
    }
    // Re-aim while the layout settles. The frame's own stylesheet is injected
    // after its `load` (and images arrive after that), so both targets move
    // under the restore: a single 350 ms attempt left a percent resume at the
    // wrong place on a cold load — the block anchor is immune, being measured
    // against the live document rather than against a height (REVIEW P2-10).
    //
    // Skipped as soon as the reader has scrolled away from where the restore
    // left them: their position is theirs, and no re-aim may pull them back.
    let restoredAt = frameOffset();
    for (const delay of [350, 900, 1800]) {
        setTimeout(() => {
            if (Math.abs(frameOffset() - restoredAt) > 2) return;
            scrollToSaved();
            restoredAt = frameOffset();
            // A retired badge stays gone, so a late re-aim cannot resurrect it.
            if (placed && !resumeMarkerRetired) placeResumeMarker();
        }, delay);
    }
}

let tocSyncQueued = false;

function queueTocSync() {
    if (tocSyncQueued) return;
    tocSyncQueued = true;
    requestAnimationFrame(() => {
        tocSyncQueued = false;
        // The reader scrolled: the reading line decides the highlight now, not
        // the entry a click asked for (whose scroll may already have passed).
        pendingEntry = null;
        syncTocHighlight();
    });
}

function wireFrameScroll() {
    try {
        const win = frame.contentWindow;
        // Wired once per window: a same-document fragment navigation keeps the
        // window, and a second listener would only repeat the work.
        if (win.readerScrollWired) return;
        win.readerScrollWired = true;
        win.addEventListener("scroll", scheduleProgressSave, { passive: true });
        win.addEventListener("scroll", queueTocSync, { passive: true });
        // The "上次读到此处" badge belongs to the restored position: scrolling
        // away retires it (debounced, so it stays put while the reader is still
        // moving), and it never lingers over text the reader has left.
        win.addEventListener("scroll", retireResumeMarkerOnScroll, { passive: true });
        // A frame is its own event tree, so the shell's keydown listener above
        // never sees a key pressed inside the book — and clicking into the book
        // is exactly what a reader does before selecting text. Without this the
        // arrow keys and ESC stopped working at the first click (REVIEW P1-5).
        win.addEventListener("keydown", (event) => {
            const target = event.target;
            if (target && (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)
                           || target.isContentEditable)) {
                return;      // a book with a form keeps its own keys
            }
            if (!imagePopup.hidden) {
                if (event.key === "Escape") hideImagePopup();
                return;      // a popped-out image is modal
            }
            if (event.key === "Escape") hidePopup();
            if (event.key === "ArrowLeft") load(BOOK.index - 1);
            if (event.key === "ArrowRight") load(BOOK.index + 1);
        });
    } catch { /* opaque origin */ }
}

document.getElementById("font-minus").addEventListener("click", () => {
    state.size = clampSize(state.size - 1);
    localStorage.setItem("reader-font-size", String(state.size));
    applyFrameStyle();
});
document.getElementById("font-plus").addEventListener("click", () => {
    state.size = clampSize(state.size + 1);
    localStorage.setItem("reader-font-size", String(state.size));
    applyFrameStyle();
});

/* ---- Footnotes: a popup per marker, from the resolved edges ----

The served XHTML carries no injected ids (it is served untouched), so
markers are matched to edges by the raw href the book wrote. A marker's
native navigation is prevented and the note's text comes from the edges
API — a footnote opens without fetching a rendered page. */

const footnotePopup = document.getElementById("footnote-popup");
let chapterEdges = [];

function frameDocument() {
    try {
        return frame.contentDocument;
    } catch {
        return null; // opaque origin: nothing to reach
    }
}

// The note a marker opens, when that note is in the chapter on screen — the
// only one the shell can look at. A note in another chapter is not here to
// inspect, and nothing is guessed about it.
function noteElement(edge) {
    const chapter = BOOK.spine.indexOf(edge.target_href);
    const doc = chapter === BOOK.index ? frameDocument() : null;
    return doc && edge.target_anchor ? doc.getElementById(edge.target_anchor) : null;
}

// The label a note prints for itself, or null. Two shapes are *known*, and only
// a known shape is ever acted on:
//
//   · the element the note resolves to *is* the label — 剑桥中华民国史's
//     `<a id="filepos39577" href="#filepos23590">①</a> 关于汉学…`, the number
//     linked back to the marker, with the note's text after it;
//   · the note opens with that link — 项狄传's `<sup><a
//     href="…/#fnref564">4</a></sup>斯特恩耍调皮的…`.
//
// Everything else is left alone; showPopup says why.
function leadingLabel(target, marker, label) {
    if (!target || !labelIsToken(label)) return null;
    if (isBackLink(target, marker) && (target.textContent || "").trim() === label) {
        return target;
    }
    for (const link of target.querySelectorAll("a[href]")) {
        if (isBackLink(link, marker) && opensElement(target, link)) return link;
    }
    return null;
}

// Does `link` point back at the marker the reader clicked? The book prints that
// pointer as a fragment naming the marker's own element.
function isBackLink(link, marker) {
    return Boolean(marker)
        && (link.getAttribute("href") || "").split("#").pop() === marker;
}

// Does `node` print `stop` before anything else? Walks down through whatever
// wrapper the book puts round its label (`<sup>`, `<span>`, `<i>`) and stops at
// the first text it meets.
function opensElement(node, stop) {
    for (const child of node.childNodes) {
        if (child === stop) return true;
        if (child.contains && child.contains(stop)) return opensElement(child, stop);
        if ((child.textContent || "").trim()) return false;
    }
    return false;
}

// A printed label is a token — "4", "①", "12" — never a phrase. Death of Caesar
// anchors its markers on an empty element, and the back-link its producer built
// out of the following words wraps real prose: the note prints "In 50 B.C.
// Decimus was back in Rome…" and opens with a link reading "In 50". A text like
// that must never be taken out of the note, so only tokens qualify.
function labelIsToken(label) {
    return Boolean(label) && label.length <= 4 && !/\s/.test(label);
}

function loadEdges() {
    const index = BOOK.index;
    fetch("/api/footnotes/" + encodeURIComponent(BOOK.slug) + "/" + index)
        .then((response) => response.json())
        .then((data) => {
            if (BOOK.index !== index) return; // a stale chapter response
            chapterEdges = Array.isArray(data.edges) ? data.edges : [];
            wireMarkers();
        })
        .catch(() => {
            chapterEdges = [];
        });
}

function wireMarkers() {
    const doc = frameDocument();
    if (!doc || !doc.body) return;
    if (!doc.body.dataset.dismissWired) {
        doc.body.dataset.dismissWired = "1";
        // A click anywhere else in the chapter dismisses the popup. (Frame
        // elements fail `instanceof Element` against this realm — duck-type.)
        doc.addEventListener("click", (event) => {
            const target = event.target;
            if (target.closest && target.closest("a[data-edge]")) return;
            hidePopup();
        });
    }
    const byHref = new Map();
    for (const edge of chapterEdges) {
        if (edge.href) byHref.set(edge.href, edge);
    }
    for (const anchor of doc.querySelectorAll("a[href]")) {
        if (anchor.dataset.edge) continue;
        const edge = byHref.get(anchor.getAttribute("href"));
        if (!edge) continue;
        anchor.dataset.edge = "1";
        // The note this marker opens prints its own number as a label, and the
        // book's own CSS prints it at full size (项狄传's class is 1em, nudged
        // 4px up), so it can run straight into the note's first word — when it
        // does. A book that spaced its own label (剑桥中华民国史 prints
        // "① 关于…") needs nothing. Marked for the paper sheet, which owns the
        // spacing; the note's own text is never rewritten.
        const label = (edge.text || "").trim();
        const printed = leadingLabel(noteElement(edge), anchor.id, label);
        const rest = printed
            ? (edge.target_text || "").slice((printed.textContent || "").length) : "";
        if (printed && rest && !/^\s/.test(rest)) printed.dataset.noteLabel = "1";
        anchor.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            showPopup(event.currentTarget, edge);
        });
    }
}

function showPopup(anchor, edge) {
    footnotePopup.textContent = "";
    const label = (edge.text || "").trim();
    let body = edge.resolved
        ? (edge.target_text || "(this note block carries no text)")
        : "这个引用无法定位 — " + (edge.href || "no href");
    // The note prints its own number as a label, and epubx folds it into the
    // note's text — so the number would appear twice: as the head, and again at
    // the head of the text. Where the note is on screen and that label is
    // *known* (leadingLabel), it comes out of the text and the head prints it
    // instead. Everywhere else nothing is taken out of the text: "the text opens
    // with its own number" is not proof — 项狄传's note 2 opens "1742年在伦敦…"
    // and Death of Caesar's markers are whole phrases — and a digit dropped from
    // the book's text is unrecoverable. There the head yields, so the number is
    // printed once either way.
    const printed = leadingLabel(noteElement(edge), anchor.id, label);
    const printedText = printed ? (printed.textContent || "").trim() : "";
    const stripped = Boolean(printedText) && body.startsWith(printedText);
    if (stripped) body = body.slice(printedText.length).replace(/^\s+/, "");
    const repeated = !stripped && label && body.startsWith(label);
    if (!repeated) {
        // The head is the note's own label, printed once — a label, not a link:
        // the popup is dismissed by clicking outside it, as it always was.
        const head = document.createElement("div");
        head.className = "popup-head";
        head.textContent = edge.text || "※";
        footnotePopup.appendChild(head);
    }
    const note = document.createElement("div");
    note.className = "popup-note" + (edge.resolved ? "" : " unresolved");
    note.textContent = body;
    footnotePopup.appendChild(note);
    if (edge.resolved && edge.target_href) {
        const open = document.createElement("a");
        open.href = "#";
        open.className = "popup-open";
        open.textContent = "在注释处打开 ↗";
        open.addEventListener("click", (event) => {
            event.preventDefault();
            hidePopup();
            const index = BOOK.spine.indexOf(edge.target_href);
            const chapter = index >= 0 ? index : edge.target_chapter;
            // A note in the chapter already on screen is reached by scrolling
            // the frame directly (jumpToTarget); any other chapter goes through
            // the normal load.
            if (chapter === BOOK.index && jumpToTarget(edge.target_anchor)) return;
            load(chapter, { anchor: edge.target_anchor });
        });
        footnotePopup.appendChild(open);
    }
    footnotePopup.classList.add("show");
    positionPopup(anchor);
}

function positionPopup(anchor) {
    const markerRect = anchor.getBoundingClientRect();
    const frameRect = frame.getBoundingClientRect();
    const width = footnotePopup.offsetWidth || 320;
    const height = footnotePopup.offsetHeight || 120;
    let left = frameRect.left + markerRect.left;
    let top = frameRect.top + markerRect.bottom + 8;
    left = Math.max(12, Math.min(left, window.innerWidth - width - 12));
    if (top + height > window.innerHeight - 12) {
        top = frameRect.top + markerRect.top - height - 8;
    }
    top = Math.max(12, Math.min(top, window.innerHeight - height - 12));
    footnotePopup.style.left = left + "px";
    footnotePopup.style.top = top + "px";
}

function hidePopup() {
    footnotePopup.classList.remove("show");
}

/* ---- Images: click one to pop it out at its own size ----

The served XHTML carries the book's own <img> tags, which the paper styles
scale down to the reading column. Clicking one opens it in a shell overlay at
its intrinsic size — the book's own metrics, never the column's — so a plate
or map can be read in full. The book's document is never modified beyond the
cursor hint; the overlay and its image live in the shell. */

const imagePopup = document.getElementById("image-popup");
const imagePopupImg = document.getElementById("image-popup-img");
const imagePopupClose = document.getElementById("image-popup-close");

function showImagePopup(src, alt) {
    if (!src) return;
    imagePopupImg.src = src;
    imagePopupImg.alt = alt || "";
    imagePopup.hidden = false;
    // Focus the × so ESC lands in the shell's document (the frame is its own
    // event tree) and the overlay owns the keyboard while it is open.
    imagePopupClose.focus();
}

function hideImagePopup() {
    if (imagePopup.hidden) return;
    imagePopup.hidden = true;
    // Drop the src so a large plate is not kept decoded after it is closed.
    imagePopupImg.removeAttribute("src");
}

imagePopup.addEventListener("click", (event) => {
    // Only the dimmed surround closes: a click on the image (or the ×, which
    // has its own handler) must not. The image is a child, so a hit on the
    // backdrop is the overlay element itself.
    if (event.target === imagePopup) hideImagePopup();
});
imagePopupClose.addEventListener("click", hideImagePopup);

function wireImages() {
    const doc = frameDocument();
    if (!doc || !doc.body) return;
    for (const image of doc.querySelectorAll("img")) {
        if (image.dataset.readerZoom) continue;
        image.dataset.readerZoom = "1";  // also carries the zoom-in cursor (IMAGE_CSS)
        image.addEventListener("click", (event) => {
            // A figure wrapped in a link would otherwise navigate the frame.
            event.preventDefault();
            event.stopPropagation();
            showImagePopup(image.currentSrc || image.src, image.alt);
        });
    }
}

// The chapter the frame is showing, from its own path — decoded, because the
// server's `quote` escapes "(" and ")" while the spine does not (see
// bookPrefix). -1 when the frame is not on a chapter of this book.
function frameChapterIndex() {
    try {
        const pathname = decodeURIComponent(frame.contentWindow.location.pathname);
        if (!pathname.startsWith(bookPrefix)) return -1;
        return BOOK.spine.indexOf(pathname.slice(bookPrefix.length));
    } catch (error) {
        return -1;   // opaque origin: nothing to sync
    }
}

/* ---- Math: the shell renders the book's LaTeX ----

A book's formulas are usually LaTeX, and LaTeX is only text — nothing draws it
by itself. The reader serves the book's own document in a frame marked
`sandbox="allow-same-origin"`, with no `allow-scripts`, so a MathJax the book
ships can never run: SPEC.md named that as an open trade-off, and this is the
other way through it. The shell converts the formulas instead, with a converter
of its own, into the frame's own document — the same reach that injects the
paper stylesheet and paints a highlight. The book's file is never written to,
and the book's own scripts still never run.

**The output is MathML, not a picture of math.** Temml turns the book's LaTeX
into the same MathML the browser already renders natively (a book that ships
MathML needs none of this — see chapter 1 of the math test book), so a formula
stays *text*: it can be selected, found by find-in-page and read by assistive
technology, it follows the reader's font size, and it needs no font files of its
own. The alternative — MathJax drawing SVG — is what shipped first, and it is
what this replaced: 2.1 MB against 168 KB, and glyph outlines against text.

Rendering changes what the document *says*, so each drawn span carries the
source it was written as (`data-source`) beside the formula (`data-tex`), and
`ReaderCore.mathText` reads that back for every block lookup — and, since a
reader who selects a formula wants the formula rather than its rendering, for
the text 复制文本 puts on the clipboard. Without it a paragraph holding a
formula stops matching the text the library extracted: measured on the math
test book, matched before the pass, null after it, matched again with it.

A formula this converter cannot read is left exactly as the book wrote it. The
failure is marked (`data-math-error`, the parser's own message) rather than
swallowed, and the sentence around it is untouched — the chapter looks as it did
before any of this existed, which is the one failure a reader can still act on. */

const MATH_SCRIPT = "/static/vendor/temml/temml.min.js";

// Temml's own stylesheet, served from its own directory: it sets the math font
// stack and makes display math a block. Loaded into the frame as a `<link>`
// rather than inlined, because its `url(Temml.woff2)` must resolve against the
// stylesheet's own path, not the book's.
const MATH_STYLESHEET = "/static/vendor/temml/Temml-Local.css";

// Elements whose text is never a formula: code and pre are where a `$` is
// literal, and MathML is already math.
const MATH_SKIP_TAGS = new Set(["PRE", "CODE", "SCRIPT", "STYLE", "MATH",
                                "TEXTAREA"]);

// Injected into the frame in both modes, like the highlight colours and the
// resume rule. Temml's own stylesheet rides along as a `<link>` (see
// `applyMathStylesheet`); what is here is the reader's own dressing: a display
// formula is a centred block of its own, and one too wide for the column
// scrolls rather than widening the page.
const MATH_CSS = `
span[data-reader-math] { display: inline; }
span[data-reader-math][data-display] {
  display: block; text-align: center; margin: 1.1em 0; overflow-x: auto;
}
span[data-reader-math] math { max-width: 100%; }
`;

let mathPromise = null;

// The cache-busting the templates put on the shell's own scripts, taken from
// this script's own URL rather than hard-coded.
function assetQuery() {
    const shellScript = document.querySelector("script[src*='/static/js/reader.js']");
    const source = shellScript ? shellScript.getAttribute("src") || "" : "";
    return source.indexOf("?") >= 0 ? source.slice(source.indexOf("?")) : "";
}

// The converter is fetched the first time a chapter turns out to carry LaTeX,
// and never for a library of prose: 168 KB is not a page-load cost a reader
// should pay for a book with no formulas in it.
function ensureMath() {
    if (mathPromise) return mathPromise;
    mathPromise = new Promise((resolve) => {
        const script = document.createElement("script");
        script.src = MATH_SCRIPT + assetQuery();
        script.onload = () => resolve(typeof window.temml !== "undefined");
        script.onerror = () => resolve(false);   // no converter: the source stays
        document.head.appendChild(script);
    });
    return mathPromise;
}

// Temml's stylesheet in the frame's head, once per document. It is a `<link>`
// and not inlined because the font it declares resolves against the
// stylesheet's own path; it is added with the first formula, so a chapter
// without math never asks for it.
function applyMathStylesheet(doc) {
    if (doc.getElementById("reader-math-style")) return;
    const link = doc.createElement("link");
    link.id = "reader-math-style";
    link.rel = "stylesheet";
    link.href = MATH_STYLESHEET + assetQuery();
    (doc.head || doc.documentElement).appendChild(link);
}

// Text nodes whose parent chain forbids rendering.
function mathSkipped(node) {
    for (let el = node.parentElement; el; el = el.parentElement) {
        if (MATH_SKIP_TAGS.has(el.tagName)) return true;
        if (el.hasAttribute("data-reader-math")) return true;
    }
    return false;
}

// Draw the frame's LaTeX. Called on every frame load; an ordinary chapter costs
// one walk of its text nodes and no network at all. A document that cannot be
// walked — the stub documents in tests/js, or a frame that went away — has no
// math to draw, and returns here rather than breaking the rest of the frame's
// wiring: footnotes, highlights and the reading position are wired after this.
function renderMathInFrame() {
    const doc = frameDocument();
    if (!doc || !doc.body || typeof doc.createTreeWalker !== "function"
        || typeof NodeFilter === "undefined") {
        return;
    }
    const pending = [];
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
        const value = node.nodeValue;
        if (!value || (value.indexOf("$") < 0 && value.indexOf("\\") < 0)) continue;
        if (mathSkipped(node)) continue;
        const spans = findLatexSpans(value);
        if (spans.length) pending.push({ node, spans });
    }
    if (!pending.length) return;
    ensureMath().then((ready) => {
        if (!ready) return;
        applyMathStylesheet(doc);
        drawMath(doc, pending);
    }).catch(() => {});   // a converter that fails never breaks the chapter
}

function drawMath(doc, pending) {
    for (const { node, spans } of pending) {
        if (!doc.contains(node)) continue;   // the reader turned the chapter
        // Last span first: splitting at a later offset leaves the earlier ones
        // valid, and `findLatexSpans` returns the spans in order.
        for (let i = spans.length - 1; i >= 0; i--) {
            const span = spans[i];
            const holder = doc.createElement("span");
            holder.setAttribute("data-reader-math", "");
            holder.setAttribute("data-tex", span.tex);
            holder.setAttribute("data-source", span.source);
            if (span.display) holder.setAttribute("data-display", "block");
            try {
                // MathML, not a picture of it: the frame's document parses
                // `<math>` natively, so the formula is still text.
                holder.innerHTML = window.temml.renderToString(span.tex,
                    { displayMode: span.display, throwOnError: true });
            } catch (error) {
                // A formula this converter cannot read: the book's own text
                // stays where it was, and the reason is left in the DOM for a
                // developer rather than swallowed.
                holder.textContent = span.source;
                holder.setAttribute("data-math-error",
                                    String(error.message || error).slice(0, 200));
            }
            const tail = node.splitText(span.start);
            tail.splitText(span.end - span.start);
            tail.parentNode.replaceChild(holder, tail);
        }
    }
}



// The document this wiring was last run for. A `load` event always brings a new
// one, so a chapter is wired exactly once — whether it arrives through the
// listener below or through the check at init, which exists because that
// listener can be missed (see there).
let wiredDocument = null;

// In-book links navigate the frame natively; follow along so the position
// and the TOC highlight stay in step with what the reader is looking at.
function onFrameLoad() {
    const doc = frameDocument();
    if (doc && doc === wiredDocument) return;
    wiredDocument = doc;
    hidePopup();
    hideImagePopup();
    applyFrameStyle();
    // Before the scroll is restored and the highlights are painted, so what the
    // reader sees is the finished chapter rather than one that reflows under
    // them a moment later. It fetches the converter only for a chapter that
    // carries LaTeX, and does nothing at all otherwise.
    renderMathInFrame();
    wireFrameScroll();
    // The frame — not the shell — is the truth about which chapter is on
    // screen: a footnote's 在注释处打开 or any cross-reference moves it without
    // the shell asking. Decided *before* the scroll is restored, so a chapter
    // entered by a link is not scrolled to the previous chapter's position, and
    // recorded, so a resume lands here rather than where the link was followed
    // from (REVIEW P1-6).
    const moved = frameChapterIndex();
    if (moved >= 0 && moved !== BOOK.index) {
        BOOK.index = moved;
        saveProgress(0);            // the frame moved the reader: record it
        mark();
        ReaderPanel.setChapter(moved);
    }
    restoreScroll(BOOK.index);
    // Wiring happens whatever the frame navigated to: an unrelated URL must
    // never leave the reader without footnotes or highlights.
    wireMarkers();  // word-convention markers wire immediately
    wireImages();   // images pop out into the shell at their own size
    loadEdges();    // library-classified edges wire when they arrive
    ReaderPanel.onFrameLoad();  // selection + saved highlights for this chapter
    // The entry a click asked for: aimed here, once the chapter is in the frame
    // — a heading the book gave no id has no fragment to carry that aim in the
    // URL, and the saved position restoreScroll() just applied is about the
    // chapter the reader left rather than the heading they asked for. A cached
    // chapter can settle late (images push the headings down), so the highlight
    // is aimed once more after the layout has had a moment.
    if (pendingEntry) {
        const entry = pendingEntry;
        pendingEntry = null;
        jumpToTarget(entry.dataset.anchor, entry.dataset.heading);
    }
    syncTocHighlight();
    setTimeout(syncTocHighlight, 350);
}

frame.addEventListener("load", onFrameLoad);

/* ---- init ---- */

ReaderPanel.setBook(BOOK.slug);
ReaderPanel.setChapter(BOOK.index);
ReaderPanel.init();
renderToc(BOOK.toc, tocList);
applySidebar();
applyTheme();
applyMode();
mark();
// The initial chapter's frame may already have fired `load` before these
// listeners attached (fast local serving, cache) — wire now as well; the
// dataset guards make repeated wiring harmless. The delayed re-wire
// catches any load that completed in between.
wireMarkers();
wireImages();
loadEdges();
// The rest of the frame's wiring belongs to `onFrameLoad` — the paper sheet,
// the drawn math, the reading position, the saved highlights — and that
// listener is missed in the very same race: a chapter small enough to finish
// loading before these scripts ran (the frame sits above them in the document)
// never fires a `load` this script can hear, and the chapter then reads
// unstyled, unhighlighted, with its formulas still as source. Wiring is
// guarded per document, so asking here cannot wire one chapter twice.
function frameIsLoaded() {
    const doc = frameDocument();
    return Boolean(doc && doc.readyState === "complete" && doc.body
                   && doc.body.childNodes.length);
}

if (frameIsLoaded()) onFrameLoad();
// The scroll listeners are wired from the frame's `load` too, so a missed event
// meant no progress was ever saved while scrolling — the same race as the resume
// below, and the reason T1's browser smoke was flaky before this (the wiring is
// per-window, so this is safe either way: a frame still on about:blank gets a
// throwaway window marked, and the chapter's own window is wired on load).
wireFrameScroll();
ReaderPanel.onFrameLoad();
// The resume, for the case the `load` listener above cannot cover: a chapter
// that finished loading before that listener was attached never fires `load`
// again, and the saved position would then never be restored. `restoreScroll`
// returns unless the frame really holds this chapter, so this cannot consume the
// position early (T1's browser smoke found this as a flaky resume).
restoreScroll(BOOK.index);
setTimeout(wireMarkers, 300);
setTimeout(wireImages, 300);
// A cached chapter can finish loading before the listener above was attached,
// so its `load` event never reaches us. Ask the panel again shortly: that also
// gives the frame's layout time to settle before any deep-link reveal.
setTimeout(() => ReaderPanel.onFrameLoad(), 400);