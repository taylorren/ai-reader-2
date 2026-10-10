/* The reader shell: drives the sandboxed iframe through the spine, and
   dresses the book's own document with the paper experience (injected —
   the book's scripts never run). Layout mirrors the reference reader:
   collapsible TOC sidebar, slim bar, chapter frame. */

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

function clampSize(size) {
    return Math.max(12, Math.min(48, Number.isFinite(size) ? size : 19));
}

const prefix = "/book/" + encodeURIComponent(BOOK.slug) + "/";

// The same directory, decoded. The server builds srcs with Python's `quote`,
// which escapes "(" and ")" as %28/%29; `encodeURIComponent` leaves them
// literal — so an encoded-form comparison silently failed for any slug with
// parentheses (most translated titles have them) and the frame-load handler
// bailed before wiring the panel. Compare decoded paths instead.
const bookPrefix = "/book/" + BOOK.slug + "/";

function fileURL(path, anchor) {
    const encoded = path.split("/").map(encodeURIComponent).join("/");
    return prefix + encoded + (anchor ? "#" + encodeURIComponent(anchor) : "");
}

// The heading the reader asked for but the frame has not reached yet. A TOC
// click changes `frame.src` while the old document is still on screen, so the
// in-view heading cannot be measured at that instant: this carries the choice
// until the new chapter's `load` lands — or the reader scrolls away from it.
let pendingAnchor = null;

function load(index, anchor) {
    index = Math.max(0, Math.min(BOOK.spine.length - 1, index));
    BOOK.index = index;
    pendingAnchor = anchor || null;
    frame.src = fileURL(BOOK.spine[index], anchor);
    if (scrollSaveTimer) clearTimeout(scrollSaveTimer);
    saveProgress(0);
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
   href, so those entries share the chapter's `href` and differ only in the
   fragment it hands over as `anchor` (nav.py). Several links therefore carry
   one `data-path`, and a plain path lookup always finds the first — the
   chapter's own entry. Measure instead: of this chapter's anchored entries,
   the last heading above the reading line is the one being read. */

const TOC_READING_LINE = 0.3; // fraction of the viewport a heading owns

function frameAnchorElement(doc, anchor) {
    // A fragment names an id, or a legacy named anchor.
    return doc.getElementById(anchor) || doc.getElementsByName(anchor)[0] || null;
}

function frameAnchorInView(path) {
    const doc = frameDocument();
    if (!doc || !doc.body) return null;
    let line;
    try {
        line = (frame.contentWindow.innerHeight || 0) * TOC_READING_LINE;
    } catch {
        return null; // opaque origin: nothing to measure
    }
    let inView = null;
    const links = tocList.querySelectorAll(
        `a[data-anchor][data-path="${CSS.escape(path)}"]`);
    for (const link of links) {
        const target = frameAnchorElement(doc, link.dataset.anchor);
        if (!target) continue; // an anchor the book never defines
        if (target.getBoundingClientRect().top <= line) {
            inView = link.dataset.anchor;
        }
    }
    return inView;
}

function syncTocHighlight() {
    const path = BOOK.spine[BOOK.index];
    if (!path) return;
    const links = tocList.querySelectorAll(`a[data-path="${CSS.escape(path)}"]`);
    if (!links.length) return;
    const wanted = pendingAnchor || frameAnchorInView(path);
    let active = null;
    for (const link of links) {
        const anchor = link.dataset.anchor || "";
        if (wanted && anchor === wanted) { active = link; break; }
        // No heading in view — or an anchor the book never defines: the
        // chapter's own entry, the link that names no fragment.
        if (!active && !anchor) active = link;
    }
    active = active || links[0];
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

function tocKey(node) {
    return (node.href || "") + "|" + (node.anchor || "") + "|" + (node.label || "");
}

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

function tocLabel(node) {
    if (node.href && BOOK.spine.includes(node.href)) {
        const link = document.createElement("a");
        link.href = "#";
        link.dataset.path = node.href;
        // A fragment on this chapter's own file: the section's marker.
        // Chapter entries name no fragment and stay the fallback.
        if (node.anchor) link.dataset.anchor = node.anchor;
        link.textContent = node.label || node.href;
        const index = BOOK.spine.indexOf(node.href);
        link.onclick = (event) => {
            event.preventDefault();
            load(index, node.anchor);
        };
        return link;
    }
    const span = document.createElement("span");
    span.textContent = node.label || "";
    return span;
}

function buildTocList(nodes, expanded) {
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

        row.appendChild(tocLabel(node));
        li.appendChild(row);
        if (children.length) li.appendChild(buildTocList(children, expanded));
        ul.appendChild(li);
    }
    return ul;
}

function renderToc(nodes, container) {
    container.appendChild(buildTocList(nodes, loadExpanded()));
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
        // painted highlights and the resume rule still need their colours.
        style.textContent = HIGHLIGHT_CSS + RESUME_CSS;
        return;
    }
    style.textContent = framePaperCSS() + HIGHLIGHT_CSS + RESUME_CSS;
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
};
const lastPercentByChapter = new Map();
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
    fetch("/api/progress", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            book_id: BOOK.slug,
            chapter_index: BOOK.index,
            scroll_percent: Math.round(percent),
        }),
    }).catch(() => {}); // a failed save must never disturb the reading
}

function scheduleProgressSave() {
    if (scrollSaveTimer) clearTimeout(scrollSaveTimer);
    scrollSaveTimer = setTimeout(() => saveProgress(frameScrollPercent()), 500);
}

/* A resumed position is announced once, so the reader knows the page did not
   open at the top by accident — and can jump back to the start. */
let resumeNoticeShown = false;

function showResumeNotice(percent) {
    const notice = document.getElementById("resume-notice");
    if (!notice) return;
    document.getElementById("resume-text").textContent =
        `⏱ 已回到上次阅读位置 · 第 ${BOOK.index + 1} 章 · ${Math.round(percent)}%`;
    notice.hidden = false;
}

function wireResumeNotice() {
    const notice = document.getElementById("resume-notice");
    if (!notice) return;
    document.getElementById("resume-dismiss").addEventListener("click", () => {
        notice.hidden = true;
    });
}

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

/* The first paragraph boundary at or below the top edge: the rule sits in the
   gap above it. The paragraph the reader stopped inside is usually partly
   scrolled past, and a rule at its top edge would be above the fold. */
function resumeAnchorBlock(doc) {
    for (const block of doc.querySelectorAll(RESUME_MARK_SELECTOR)) {
        if (block.getBoundingClientRect().top >= 2) return block;
    }
    return doc.body.querySelector(RESUME_MARK_SELECTOR);
}

function restoreScroll(chapter) {
    // A "在书中定位" deep link outranks the saved position: the reader asked
    // for that passage, not for where they left off. Its delayed scroll would
    // otherwise land after the highlight's, pulling the reader away from it.
    if (BOOK.target_highlight) return;
    let percent = null;
    if (pendingRestore && pendingRestore.chapter === chapter) {
        percent = pendingRestore.percent;
        pendingRestore = null;
    } else if (lastPercentByChapter.has(chapter)) {
        percent = lastPercentByChapter.get(chapter);
    }
    if (!(percent > 0)) return;
    // Layout settles as images load; restore now and once more shortly.
    const scrollToPercent = () => {
        try {
            const win = frame.contentWindow;
            const max = win.document.documentElement.scrollHeight - win.innerHeight;
            if (max > 0) win.scrollTo(0, Math.round((percent / 100) * max));
        } catch { /* opaque origin */ }
    };
    scrollToPercent();
    // The reader should know why the page did not open at the top — and where
    // it opened — but only for the return that this session resumed.
    const placed = !resumeNoticeShown;
    if (placed) {
        resumeNoticeShown = true;
        showResumeNotice(percent);
        placeResumeMarker();
    }
    setTimeout(() => {
        scrollToPercent();
        // Re-aim once the layout has settled — unless the reader has already
        // scrolled past the badge (or clicked it away): a retired badge stays
        // gone, so a late re-aim cannot resurrect it.
        if (placed && !resumeMarkerRetired) placeResumeMarker();
    }, 350);
}

let tocSyncQueued = false;

function queueTocSync() {
    if (tocSyncQueued) return;
    tocSyncQueued = true;
    requestAnimationFrame(() => {
        tocSyncQueued = false;
        // The reader scrolled: the reading line decides the highlight now, not
        // the entry a click asked for (whose scroll may already have passed).
        pendingAnchor = null;
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
        anchor.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            showPopup(event.currentTarget, edge);
        });
    }
}

function showPopup(anchor, edge) {
    footnotePopup.textContent = "";
    const head = document.createElement("div");
    head.className = "popup-head";
    head.textContent = edge.text || "※";
    footnotePopup.appendChild(head);
    const note = document.createElement("div");
    note.className = "popup-note" + (edge.resolved ? "" : " unresolved");
    note.textContent = edge.resolved
        ? (edge.target_text || "(this note block carries no text)")
        : "这个引用无法定位 — " + (edge.href || "no href");
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
            load(index >= 0 ? index : edge.target_chapter, edge.target_anchor);
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

// In-book links navigate the frame natively; follow along so the position
// and the TOC highlight stay in step with what the reader is looking at.
frame.addEventListener("load", () => {
    hidePopup();
    applyFrameStyle();
    wireFrameScroll();
    restoreScroll(BOOK.index);
    try {
        const pathname = decodeURIComponent(frame.contentWindow.location.pathname);
        if (pathname.startsWith(bookPrefix)) {
            const index = BOOK.spine.indexOf(pathname.slice(bookPrefix.length));
            if (index >= 0 && index !== BOOK.index) {
                BOOK.index = index;
                mark();
            }
        }
    } catch (error) { /* opaque origin: nothing to sync */ }
    // Wiring happens whatever the frame navigated to: an unrelated URL must
    // never leave the reader without footnotes or highlights.
    wireMarkers();  // word-convention markers wire immediately
    loadEdges();    // library-classified edges wire when they arrive
    ReaderPanel.onFrameLoad();  // selection + saved highlights for this chapter
    // The requested anchor is the frame's own scroll now; a cached chapter can
    // settle late (images push the headings down), so aim the highlight once
    // more after the layout has had a moment.
    pendingAnchor = null;
    syncTocHighlight();
    setTimeout(syncTocHighlight, 350);
});

/* ---- init ---- */

ReaderPanel.setBook(BOOK.slug);
ReaderPanel.setChapter(BOOK.index);
ReaderPanel.init();
wireResumeNotice();
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
loadEdges();
ReaderPanel.onFrameLoad();
setTimeout(wireMarkers, 300);
// A cached chapter can finish loading before the listener above was attached,
// so its `load` event never reaches us. Ask the panel again shortly: that also
// gives the frame's layout time to settle before any deep-link reveal.
setTimeout(() => ReaderPanel.onFrameLoad(), 400);