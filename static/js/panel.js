/* The AI panel and highlights for the reader shell (model A).

The book's document is served untouched in a sandboxed iframe, so selection
and painting happen inside `frame.contentDocument`: the shell reads the
frame's selection, and dresses saved highlights by wrapping the matching
text in <mark> — the book's file on disk is never modified.

Highlights anchor to the library's block ids (`c0000/b0003`), matched to the
frame's elements by text; the selected text is what a reader sees wrapped. */

window.ReaderPanel = (function () {
    const KIND_LABELS = {
        fact_check: "解释说明",
        discussion: "深入讨论",
        comment: "个人笔记",
        highlight: "高亮",
    };

    // The mark colours, mirrored by reader.js's injected frame CSS. They are
    // also set inline (with `important`) at paint time, so a book's own CSS
    // cannot hide a highlight.
    const KIND_COLORS = {
        fact_check: "rgba(217, 164, 65, 0.42)",
        discussion: "rgba(90, 143, 214, 0.38)",
        comment: "rgba(79, 174, 122, 0.38)",
        highlight: "rgba(176, 111, 208, 0.34)",
    };

    const state = {
        slug: null,
        index: 0,
        blocks: {},          // chapter index -> blocks (from /api/text)
        highlights: {},      // chapter index -> highlights
        selection: null,     // {text, block_id, context_before, context_after}
        highlightId: null,   // the highlight the open panel is about
        analysisId: null,
        mode: "analysis",    // analysis | discussion | comment
        conversation: [],
        provider: "ollama_cloud",
        busy: false,
        saved: false,
    };

    const el = (id) => document.getElementById(id);
    const frameEl = () => el("chapter-frame");

    // The shell hands its data to the scripts. `const BOOK = {...}` in a
    // classic <script> is a *lexical* global, not a property of `window`, so
    // read the bare identifier (guarded — `typeof` on an unknown name is safe)
    // and fall back to `window.BOOK` for when the shell sets it that way.
    function bookData() {
        return (typeof BOOK !== "undefined" && BOOK) || window.BOOK || {};
    }

    function escapeHtml(text) {
        const node = document.createElement("div");
        node.textContent = text == null ? "" : String(text);
        return node.innerHTML;
    }

    function renderMarkdown(markdown) {
        const html = window.marked ? marked.parse(markdown || "") : escapeHtml(markdown);
        return window.DOMPurify ? DOMPurify.sanitize(html) : html;
    }

    function toast(message, kind) {
        const node = el("toast");
        node.textContent = message;
        node.className = "toast visible" + (kind ? " " + kind : "");
        clearTimeout(node._timer);
        node._timer = setTimeout(() => { node.className = "toast"; }, 2500);
    }

    async function api(path, options) {
        const response = await fetch(path, options);
        let payload = null;
        try { payload = await response.json(); } catch (error) { payload = null; }
        if (!response.ok) {
            const detail = (payload && payload.detail) || response.statusText;
            throw new Error(typeof detail === "string" ? detail : "请求失败");
        }
        return payload;
    }

    // -- provider ------------------------------------------------------------

    async function loadSettings() {
        try {
            const settings = await api("/api/settings");
            state.provider = settings.provider_override || settings.default_provider;
            el("provider-select").value = state.provider;
        } catch (error) { /* the default stays */ }
    }

    async function setProvider(provider) {
        state.provider = provider;
        try {
            await api("/api/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ provider_override: provider }),
            });
        } catch (error) { toast("提供方设置失败", "error"); }
    }

    // -- panel open / close --------------------------------------------------

    function openPanel(title) {
        el("ai-panel").hidden = false;
        el("toggle-panel").hidden = true;
        if (title) el("panel-title").textContent = title;
    }

    function closePanel() {
        el("ai-panel").hidden = true;
        el("toggle-panel").hidden = false;
        resetPanel();
    }

    // X, ESC and click-outside all land here: a close while the AI is thinking
    // would lose the in-flight result, so it is refused with a toast instead
    // (the reference reader's rule).
    function requestClose() {
        if (state.busy) {
            const message = "AI 正在思考中，请稍候…";
            if (el("toast").textContent !== message) toast(message);
            return;
        }
        closePanel();
    }

    function resetPanel() {
        state.highlightId = null;
        state.analysisId = null;
        state.mode = "analysis";
        state.conversation = [];
        state.saved = false;
        state.selection = null;
        el("panel-selected").textContent = "";
        el("panel-body").innerHTML = "";
        el("discussion-log").hidden = true;
        el("discussion-log").innerHTML = "";
        el("discussion-input-row").hidden = true;
        el("discussion-input").value = "";
        showButtons({});
    }

    function showButtons(visible) {
        for (const name of ["save", "edit", "summarize", "delete"]) {
            const button = el("panel-" + name);
            button.hidden = !visible[name];
        }
    }

    function setBusy(busy) {
        state.busy = busy;
        el("discussion-send").disabled = busy;
        if (busy) {
            el("panel-body").innerHTML = '<div class="loading">AI 正在思考…</div>';
        }
    }

    // -- the public surface --------------------------------------------------

    const P = {};
    P.state = state;
    P.loadSettings = loadSettings;

    P.init = function () {
        el("provider-select").addEventListener("change",
            (event) => setProvider(event.currentTarget.value));
        el("panel-close").addEventListener("click", () => requestClose());
        el("toggle-panel").addEventListener("click", () => openPanel());
        el("panel-save").addEventListener("click", () => saveCurrent());
        el("panel-delete").addEventListener("click", () => deleteCurrent());
        el("panel-edit").addEventListener("click", () => editCurrent());
        el("panel-summarize").addEventListener("click", () => summarizeDiscussion());
        el("discussion-send").addEventListener("click", () => sendDiscussion());
        for (const item of document.querySelectorAll("#context-menu .context-menu-item")) {
            item.addEventListener("click", () => {
                hideContextMenu();
                handleAction(item.dataset.action);
            });
        }
        document.addEventListener("click", (event) => {
            if (!event.target.closest("#context-menu")) hideContextMenu();
        });
        // ESC closes the context menu and the panel — unless the reader is
        // typing into the discussion box or a note (ai-reader's rule).
        document.addEventListener("keydown", (event) => {
            const typing = ["TEXTAREA", "INPUT"].includes(event.target.tagName);
            if (event.key !== "Escape" || typing) return;
            const menuOpen = !el("context-menu").hidden;
            if (menuOpen || !el("ai-panel").hidden) {
                event.preventDefault();
                hideContextMenu();
                requestClose();
            }
        });
        // A click outside the panel dismisses it, as in the reference reader.
        document.addEventListener("mousedown", (event) => {
            if (el("ai-panel").hidden) return;
            const inside = event.target.closest("#ai-panel, #context-menu, #toggle-panel");
            if (!inside) requestClose();
        });
        loadSettings();
    };

    P.setChapter = function (index) {
        state.index = index;
        hideContextMenu();
    };

    // -- chapter data --------------------------------------------------------

    async function blocksFor(index) {
        if (!state.blocks[index]) {
            const payload = await api(`/api/text/${encodeURIComponent(state.slug)}/${index}`);
            state.blocks[index] = payload.blocks || [];
        }
        return state.blocks[index];
    }

    async function highlightsFor(index) {
        const payload = await api(
            `/api/highlights/${encodeURIComponent(state.slug)}/${index}`);
        state.highlights[index] = payload.highlights || [];
        return state.highlights[index];
    }

    function findBlockForText(blocks, text) {
        // The smallest block that contains the selection is the anchor.
        let best = null;
        for (const block of blocks) {
            if (block.text.includes(text) &&
                (!best || block.text.length < best.text.length)) {
                best = block;
            }
        }
        return best;
    }

    function selectionInFrame() {
        const doc = frameEl().contentDocument;
        if (!doc) return null;
        const selection = frameEl().contentWindow.getSelection();
        const text = selection ? selection.toString().trim() : "";
        if (!text) return null;
        const range = selection.getRangeAt(0);
        let node = range.startContainer;
        while (node && node.nodeType !== 1) node = node.parentNode;
        return { text, range, node, doc };
    }

    async function computeSelection() {
        const found = selectionInFrame();
        if (!found) return null;
        const blocks = await blocksFor(state.index);
        const block = findBlockForText(blocks, found.text);
        if (!block) {
            return { text: found.text, block_id: null,
                     context_before: "", context_after: "" };
        }
        const at = block.text.indexOf(found.text);
        return {
            text: found.text,
            block_id: block.id,
            context_before: block.text.slice(Math.max(0, at - 60), at),
            context_after: block.text.slice(at + found.text.length,
                                            at + found.text.length + 60),
        };
    }

    // -- the context menu ----------------------------------------------------

    function showContextMenu(x, y) {
        const menu = el("context-menu");
        menu.hidden = false;
        const width = menu.offsetWidth || 180;
        const height = menu.offsetHeight || 180;
        menu.style.left = Math.max(8, Math.min(x, window.innerWidth - width - 8)) + "px";
        menu.style.top = Math.max(8, Math.min(y, window.innerHeight - height - 8)) + "px";
    }

    function hideContextMenu() {
        el("context-menu").hidden = true;
    }

    P.wireSelection = function () {
        const doc = frameEl().contentDocument;
        if (!doc || doc._panelWired) return;
        doc._panelWired = true;
        // The panel is a fixed overlay in the *shell* document, so a press
        // inside the book is always outside it — but the frame is its own
        // event tree, and the shell's click-outside listener never sees these
        // presses. Close here instead (requestClose, so the in-flight-analysis
        // rule holds). A press on a painted highlight is the exception: that
        // highlight's own click handler opens the panel for it, so closing
        // first would only flicker — and could wipe an analysis in flight.
        doc.addEventListener("mousedown", (event) => {
            if (el("ai-panel").hidden) return;
            const target = event.target;
            if (target.closest && target.closest("mark.reader-highlight")) return;
            requestClose();
        });
        doc.addEventListener("mouseup", async (event) => {
            const selection = await computeSelection();
            if (!selection) { hideContextMenu(); return; }
            state.selection = selection;
            const frameRect = frameEl().getBoundingClientRect();
            showContextMenu(frameRect.left + event.clientX, frameRect.top + event.clientY + 12);
        });
    };

    // -- actions -------------------------------------------------------------

    async function ensureHighlight() {
        if (state.highlightId) return state.highlightId;
        const selection = state.selection;
        const payload = await api("/api/highlight", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                book_id: state.slug,
                chapter_index: state.index,
                selected_text: selection.text,
                block_id: selection.block_id,
                context_before: selection.context_before,
                context_after: selection.context_after,
            }),
        });
        state.highlightId = payload.highlight_id;
        return state.highlightId;
    }

    async function handleAction(action) {
        const selection = state.selection;
        if (action === "copy") {
            if (selection) {
                navigator.clipboard.writeText(selection.text);
                toast("已复制到剪贴板");
            }
            return;
        }
        if (!selection) { toast("请先选中文字"); return; }
        resetPanel();
        state.selection = selection;
        el("panel-selected").textContent = selection.text;
        openPanel(KIND_LABELS[action] || "AI 分析");
        try {
            await ensureHighlight();
        } catch (error) {
            toast(error.message, "error");
            return;
        }
        if (action === "comment") {
            startComment();
        } else if (action === "discussion") {
            await startDiscussion();
        } else {
            await runAnalysis(action);
        }
    }

    async function runAnalysis(kind) {
        state.mode = "analysis";
        state.analysisType = kind;
        setBusy(true);
        try {
            const payload = await api("/api/ai/analyze", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    highlight_id: state.highlightId,
                    analysis_type: kind,
                    selected_text: state.selection.text,
                    context: state.selection.context_before + state.selection.context_after,
                    provider: state.provider,
                }),
            });
            state.rawResponse = payload.response;
            el("panel-body").innerHTML = renderMarkdown(payload.response);
            showButtons({ save: true, delete: true });
        } catch (error) {
            el("panel-body").innerHTML =
                `<div class="panel-error">${escapeHtml(error.message)}</div>`;
            showButtons({ delete: true });
        } finally {
            setBusy(false);
        }
    }

    function startComment() {
        state.mode = "comment";
        el("panel-body").innerHTML =
            '<textarea id="comment-input" class="comment-input" rows="6" ' +
            'placeholder="写下你的笔记…（支持 Markdown）"></textarea>';
        showButtons({ save: true, delete: true });
        el("panel-save").textContent = "保存笔记";
    }

    async function startDiscussion() {
        state.mode = "discussion";
        state.conversation = [];
        state.saved = false;
        setBusy(true);
        try {
            const payload = await api("/api/ai/discussion/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    highlight_id: state.highlightId,
                    selected_text: state.selection.text,
                    provider: state.provider,
                }),
            });
            state.conversation = payload.conversation_history || [];
            el("panel-body").innerHTML = "";
            el("discussion-log").hidden = false;
            el("discussion-input-row").hidden = false;
            renderConversation();
            showButtons({ delete: true, summarize: true });
        } catch (error) {
            el("panel-body").innerHTML =
                `<div class="panel-error">${escapeHtml(error.message)}</div>`;
            showButtons({ delete: true });
        } finally {
            setBusy(false);
        }
    }

    // -- discussion, saving, deleting ---------------------------------------

    function renderConversation() {
        const log = el("discussion-log");
        log.innerHTML = "";
        for (const message of state.conversation) {
            const bubble = document.createElement("div");
            bubble.className = "discussion-message " + message.role;
            bubble.innerHTML = renderMarkdown(message.content);
            log.appendChild(bubble);
        }
        log.scrollTop = log.scrollHeight;
    }

    async function sendDiscussion() {
        const input = el("discussion-input");
        const message = input.value.trim();
        if (!message || state.busy) return;
        input.value = "";
        state.conversation.push({ role: "user", content: message });
        renderConversation();
        setBusy(true);
        el("discussion-log").hidden = false;
        try {
            const payload = await api("/api/ai/discussion/continue", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    highlight_id: state.highlightId,
                    selected_text: state.selection.text,
                    conversation_history: state.conversation,
                    user_message: message,
                    provider: state.provider,
                }),
            });
            state.conversation = payload.conversation_history || state.conversation;
            renderConversation();
            for (const warning of payload.warnings || []) toast(warning);
        } catch (error) {
            toast(error.message, "error");
        } finally {
            setBusy(false);
        }
    }

    async function summarizeDiscussion() {
        if (state.busy || state.conversation.length === 0) return;
        setBusy(true);
        try {
            const payload = await api("/api/ai/discussion/summarize", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    highlight_id: state.highlightId,
                    selected_text: state.selection.text,
                    conversation_history: state.conversation,
                    provider: state.provider,
                }),
            });
            state.summary = payload.summary;
            el("panel-body").innerHTML = renderMarkdown(payload.summary);
            showButtons({ save: true, delete: true, summarize: true });
            el("panel-save").textContent = "保存总结";
        } catch (error) {
            toast(error.message, "error");
        } finally {
            setBusy(false);
        }
    }

    async function saveCurrent() {
        if (state.saved) { toast("已经保存过了"); return; }
        let analysisType = "comment";
        let response = "";
        if (state.mode === "analysis") {
            analysisType = state.analysisType || "fact_check";
            response = state.rawResponse || "";
        } else if (state.mode === "discussion") {
            analysisType = "discussion";
            response = state.summary || "";
        } else {
            const input = document.getElementById("comment-input");
            response = input ? input.value.trim() : "";
        }
        if (!response) { toast("没有可保存的内容"); return; }
        try {
            await api("/api/ai/save", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    highlight_id: state.highlightId,
                    analysis_type: analysisType,
                    prompt: state.selection ? state.selection.text : "",
                    response: response,
                }),
            });
            state.saved = true;
            toast("已保存到数据库");
            el("panel-save").hidden = true;
            await refreshHighlights();
        } catch (error) {
            toast(error.message, "error");
        }
    }

    async function deleteCurrent() {
        if (!state.highlightId) { resetPanel(); closePanel(); return; }
        if (!confirm("删除这条高亮及其所有批注？")) return;
        try {
            await api(`/api/highlight/${state.highlightId}`, { method: "DELETE" });
            toast("已删除");
            resetPanel();
            closePanel();
            await refreshHighlights();
        } catch (error) {
            toast(error.message, "error");
        }
    }

    async function editCurrent() {
        const analysis = state.editing;
        if (!analysis) return;
        const edited = prompt("编辑批注：", analysis.response);
        if (edited === null) return;
        try {
            await api(`/api/ai/update/${analysis.id}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ response: edited }),
            });
            toast("已更新");
            showHighlight(state.highlightId);
        } catch (error) {
            toast(error.message, "error");
        }
    }

    // -- painting saved highlights into the frame ---------------------------

    function clearMarks(doc) {
        for (const mark of doc.querySelectorAll("mark.reader-highlight")) {
            const parent = mark.parentNode;
            while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
            parent.removeChild(mark);
            parent.normalize();
        }
    }

    const normalize = (text) => (text || "").replace(/\s+/g, " ").trim();

    function blockElement(doc, block) {
        const target = normalize(block.text);
        if (!target) return null;
        const candidates = doc.querySelectorAll(
            "p, h1, h2, h3, h4, h5, h6, blockquote, pre, dt, dd, li, td");
        for (const node of candidates) {
            if (normalize(node.textContent) === target) return node;
        }
        return null;
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

    function offsetToPoint(nodes, offset) {
        let position = 0;
        for (const node of nodes) {
            const length = node.nodeValue.length;
            if (offset <= position + length) {
                return { node, offset: offset - position };
            }
            position += length;
        }
        return null;
    }

    function wrapText(doc, root, text, highlight) {
        const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        const nodes = [];
        let node;
        while ((node = walker.nextNode())) nodes.push(node);
        const full = nodes.map((item) => item.nodeValue).join("");
        let at = full.indexOf(text);
        let length = text.length;
        if (at < 0) {
            const haystack = normalizedIndex(full);
            const needle = normalizedIndex(text).value;
            const found = needle ? haystack.value.indexOf(needle) : -1;
            if (found < 0) return false;
            at = haystack.map[found];
            length = haystack.map[found + needle.length - 1] + 1 - at;
        }
        const start = offsetToPoint(nodes, at);
        const end = offsetToPoint(nodes, at + length);
        if (!start || !end) return false;
        const range = doc.createRange();
        range.setStart(start.node, start.offset);
        range.setEnd(end.node, end.offset);
        const mark = doc.createElement("mark");
        mark.className = "reader-highlight hl-" + (highlight.kind || "highlight");
        mark.dataset.highlightId = highlight.id;
        mark.title = KIND_LABELS[highlight.kind] || "高亮";
        // The colour is set inline with `important`, so a book whose own CSS
        // paints every <mark>/<small>/<b> cannot hide the highlight.
        mark.style.setProperty("background",
            KIND_COLORS[highlight.kind] || KIND_COLORS.highlight, "important");
        try {
            range.surroundContents(mark);
        } catch (error) {
            return false;   // a selection crossing elements: leave it unpainted
        }
        mark.addEventListener("click", () => showHighlight(highlight.id));
        return true;
    }

    function paint(blocks, highlights) {
        const doc = frameEl().contentDocument;
        if (!doc) return 0;
        clearMarks(doc);
        let painted = 0;
        for (const highlight of highlights) {
            const block = highlight.block_id
                ? blocks.find((item) => item.id === highlight.block_id)
                : findBlockForText(blocks, highlight.selected_text);
            const root = block ? blockElement(doc, block) : doc.body;
            if (!root) continue;
            if (wrapText(doc, root, highlight.selected_text, highlight)) painted += 1;
        }
        return painted;
    }

    async function refreshHighlights() {
        if (!state.slug) return;
        try {
            const blocks = await blocksFor(state.index);
            const highlights = await highlightsFor(state.index);
            const painted = paint(blocks, highlights);
            if (highlights.length > painted) {
                // Named, not silent: a highlight whose text cannot be found in
                // the served document is reported rather than lost.
                const missing = highlights.length - painted;
                console.warn(`ai-reader: ${missing} highlight(s) not located in chapter ${state.index}`);
                toast(`本章有 ${missing} 条高亮未能定位`);
            }
            revealTarget();
        } catch (error) {
            console.warn("ai-reader: could not load highlights", error);
        }
    }

    // A "在书中定位" link arrives as ?highlight=<id>. The mark is painted into
    // the frame, whose own document is the scroll container, so the reader is
    // moved by offset — a smooth scrollIntoView into a large chapter can land
    // short when the layout is still settling — and re-aimed once it does.
    function revealTarget(attempt = 0) {
        const target = bookData().target_highlight;
        if (!target) return;
        const doc = frameEl().contentDocument;
        if (!doc) return;
        const mark = doc.querySelector(`mark[data-highlight-id="${target}"]`);
        if (!mark) {
            // The frame may still be loading — a cached chapter can beat the
            // shell's script, in which case its `load` event fired before the
            // listener existed and the load path never runs at all. Keep
            // looking until the document is complete, then report.
            if (doc.readyState !== "complete" && attempt < 20) {
                setTimeout(() => revealTarget(attempt + 1), 200);
            } else {
                console.warn("ai-reader: highlight not found in this chapter", target);
            }
            return;
        }
        mark.classList.add("flash");
        scrollToMark(mark);
        setTimeout(() => scrollToMark(mark), 300);   // images and fonts settle
        setTimeout(() => scrollToMark(mark), 900);
        setTimeout(() => mark.classList.remove("flash"), 2400);
    }

    // The chapter documents carry no <!DOCTYPE>, so the frame renders in
    // quirks mode ("此页面处于怪异模式"). There, `document.scrollingElement` is
    // the *body*, so reading `scrollTop` off it lands the reader short — so we
    // do not compute an offset at all. The browser scrolls (scrollIntoView is
    // correct in both modes), and then we *measure*: if the mark is still
    // outside the shell's container, the frame was not the scroller and the
    // container is moved instead. Both cases, decided by measurement.
    function scrollToMark(mark) {
        const win = frameEl().contentWindow;
        const holder = document.querySelector(".chapter-holder");
        mark.scrollIntoView({ block: "center", behavior: "auto" });
        if (!win) return;
        const rect = mark.getBoundingClientRect();
        const frameRect = frameEl().getBoundingClientRect();
        const offsetInHolder = frameRect.top
            - (holder ? holder.getBoundingClientRect().top : 0) + rect.top;
        if (holder &&
            (offsetInHolder < 0 || offsetInHolder > holder.clientHeight - rect.height)) {
            holder.scrollTop += offsetInHolder - (holder.clientHeight - rect.height) / 2;
        }
    }

    function showHighlight(highlightId) {
        const highlight = (state.highlights[state.index] || [])
            .find((item) => item.id === highlightId);
        if (!highlight) return;
        resetPanel();
        state.highlightId = highlightId;
        state.mode = "saved";
        state.selection = { text: highlight.selected_text,
                            block_id: highlight.block_id,
                            context_before: "", context_after: "" };
        el("panel-selected").textContent = highlight.selected_text;
        openPanel(KIND_LABELS[highlight.kind] || "高亮");
        const body = el("panel-body");
        body.innerHTML = "";
        for (const analysis of highlight.analyses || []) {
            const section = document.createElement("div");
            section.className = "saved-analysis";
            section.innerHTML = renderMarkdown(analysis.response);
            const edit = document.createElement("button");
            edit.className = "action-link";
            edit.textContent = "编辑";
            edit.addEventListener("click", () => {
                state.editing = analysis;
                editCurrent();
            });
            section.appendChild(edit);
            body.appendChild(section);
        }
        if (!(highlight.analyses || []).length) {
            body.innerHTML = '<div class="panel-hint">这条高亮还没有批注。</div>';
        }
        showButtons({ delete: true });
    }

    // -- frame hook ----------------------------------------------------------

    P.setBook = function (slug) { state.slug = slug; };

    P.onFrameLoad = async function () {
        // The frame is the truth about which chapter is on screen. A direct
        // load of /read/{slug}/{n} (a bookmark, or 在书中定位) never goes
        // through load(), so setChapter() alone would leave the panel looking
        // at chapter 0 — and painting nothing.
        const index = bookData().index;
        if (Number.isInteger(index)) {
            state.index = index;
        }
        P.wireSelection();
        await refreshHighlights();
    };

    return P;
})();





