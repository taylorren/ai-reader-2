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
        if (state.busy) { toast("AI 正在思考中，请稍候…"); return; }
        el("ai-panel").hidden = true;
        el("toggle-panel").hidden = false;
        resetPanel();
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
        el("panel-close").addEventListener("click", closePanel);
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
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") { hideContextMenu(); }
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

    function wrapText(doc, root, text, highlight) {
        const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        const nodes = [];
        let node;
        while ((node = walker.nextNode())) nodes.push(node);
        const full = nodes.map((item) => item.nodeValue).join("");
        const at = full.indexOf(text);
        if (at < 0) return false;
        let start = null, startOffset = 0, end = null, endOffset = 0, pos = 0;
        for (const item of nodes) {
            const length = item.nodeValue.length;
            if (start === null && at < pos + length) {
                start = item;
                startOffset = at - pos;
            }
            if (start !== null && at + text.length <= pos + length) {
                end = item;
                endOffset = at + text.length - pos;
                break;
            }
            pos += length;
        }
        if (!start || !end) return false;
        const range = doc.createRange();
        range.setStart(start, startOffset);
        range.setEnd(end, endOffset);
        const mark = doc.createElement("mark");
        mark.className = "reader-highlight hl-" + (highlight.kind || "highlight");
        mark.dataset.highlightId = highlight.id;
        mark.title = KIND_LABELS[highlight.kind] || "高亮";
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
        if (!doc) return;
        clearMarks(doc);
        for (const highlight of highlights) {
            const block = highlight.block_id
                ? blocks.find((item) => item.id === highlight.block_id)
                : findBlockForText(blocks, highlight.selected_text);
            const root = block ? blockElement(doc, block) : doc.body;
            if (!root) continue;
            wrapText(doc, root, highlight.selected_text, highlight);
        }
    }

    async function refreshHighlights() {
        if (!state.slug) return;
        try {
            const blocks = await blocksFor(state.index);
            const highlights = await highlightsFor(state.index);
            paint(blocks, highlights);
        } catch (error) { /* the chapter may have moved on */ }
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
        P.wireSelection();
        await refreshHighlights();
    };

    return P;
})();





