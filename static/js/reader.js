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

function fileURL(path, anchor) {
    const encoded = path.split("/").map(encodeURIComponent).join("/");
    return prefix + encoded + (anchor ? "#" + encodeURIComponent(anchor) : "");
}

function load(index, anchor) {
    index = Math.max(0, Math.min(BOOK.spine.length - 1, index));
    BOOK.index = index;
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
    const current = tocList.querySelector("a.current");
    if (current) current.classList.remove("current");
    const active = tocList.querySelector(`a[data-path="${CSS.escape(BOOK.spine[BOOK.index])}"]`);
    if (active) {
        active.classList.add("current");
        active.scrollIntoView({ block: "nearest" });
    }
}

function renderToc(nodes, container) {
    const ul = document.createElement("ul");
    for (const node of nodes) {
        const li = document.createElement("li");
        if (node.href && BOOK.spine.includes(node.href)) {
            const link = document.createElement("a");
            link.href = "#";
            link.dataset.path = node.href;
            link.textContent = node.label || node.href;
            const index = BOOK.spine.indexOf(node.href);
            link.onclick = (event) => {
                event.preventDefault();
                load(index, node.anchor);
            };
            li.appendChild(link);
        } else {
            const span = document.createElement("span");
            span.textContent = node.label || "";
            li.appendChild(span);
        }
        if (node.children && node.children.length) renderToc(node.children, li);
        ul.appendChild(li);
    }
    container.appendChild(ul);
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
        // painted highlights still need their colours.
        style.textContent = HIGHLIGHT_CSS;
        return;
    }
    style.textContent = framePaperCSS() + HIGHLIGHT_CSS;
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

function restoreScroll(chapter) {
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
    setTimeout(scrollToPercent, 350);
}

function wireFrameScroll() {
    try {
        frame.contentWindow.addEventListener("scroll", scheduleProgressSave, { passive: true });
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
        const frameLocation = frame.contentWindow.location;
        if (!frameLocation.pathname.startsWith(prefix)) return;
        const raw = decodeURIComponent(frameLocation.pathname.slice(prefix.length));
        const index = BOOK.spine.indexOf(raw);
        if (index >= 0 && index !== BOOK.index) {
            BOOK.index = index;
            mark();
        }
    } catch (error) { /* opaque origin: nothing to sync */ }
    wireMarkers();  // word-convention markers wire immediately
    loadEdges();    // library-classified edges wire when they arrive
    ReaderPanel.onFrameLoad();  // selection + saved highlights for this chapter
});

/* ---- init ---- */

ReaderPanel.setBook(BOOK.slug);
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
loadEdges();
ReaderPanel.onFrameLoad();
setTimeout(wireMarkers, 300);