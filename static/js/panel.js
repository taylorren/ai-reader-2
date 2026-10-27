/* The AI panel and highlights for the reader shell (model A).

The book's document is served untouched in a sandboxed iframe, so selection
and painting happen inside `frame.contentDocument`: the shell reads the
frame's selection, and dresses saved highlights by wrapping the matching
text in <mark> — the book's file on disk is never modified.

Highlights anchor to the library's block ids (`c0000/b0003`), matched to the
frame's elements by text; the selected text is what a reader sees wrapped. */

window.ReaderPanel = (function () {
    // The pure helpers, shared with reader.js and unit-tested in Node
    // (static/js/reader-core.js, REVIEW T1).
    const { escapeHtml, findTextRange, contextAround, textNodes, offsetToPoint,
            findBlockForText, blockElement } = window.ReaderCore;

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

    // How much text either side of a selection travels with it to the AI. The
    // service bounds the same span (CONTEXT_SPAN in ai_service.py). 60 chars
    // looked like enough and was not: the referent of a pronoun such as 他們 is
    // often the sentence before the one selected (REVIEW P1-3).
    const CONTEXT_SPAN = 300;

    const state = {
        slug: null,
        index: 0,
        blocks: {},          // chapter index -> blocks (from /api/text)
        highlights: {},      // chapter index -> highlights
        selection: null,     // {text, block_id, context_before, context_after}
        highlightId: null,   // the highlight the open panel is about
        mode: "analysis",    // analysis | discussion | comment | saved
        conversation: [],
        summary: null,       // the discussion summary waiting to be saved
        analysisType: null,  // what the open analysis is (fact_check | discussion)
        provider: "ollama_cloud",
        busy: false,
        saved: false,
        editing: null,       // the saved analysis the panel is editing
        editingDraft: false, // true while the edit box is open (P1-4)
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

    // Markdown → HTML for the panel. A sanitiser must fail *closed*: if
    // DOMPurify did not load (a 404, a truncated vendor file, an upgrade), the
    // old code returned `marked`'s output unsanitised into innerHTML — and
    // `marked` passes raw HTML through by default. AI output and the reader's
    // own notes both arrive here, so the fallback is the escaped text
    // (REVIEW P3-13).
    function renderMarkdown(markdown) {
        const html = window.marked ? marked.parse(markdown || "") : escapeHtml(markdown);
        return window.DOMPurify ? DOMPurify.sanitize(html) : escapeHtml(markdown);
    }

    function toast(message, kind) {
        const node = el("toast");
        node.textContent = message;
        node.className = "toast visible" + (kind ? " " + kind : "");
        clearTimeout(node._timer);
        node._timer = setTimeout(() => { node.className = "toast"; }, 2500);
    }

    // FastAPI answers a validation failure (422) with a *list* of field errors,
    // not one string. Naming the field and the reason keeps a client/server
    // mismatch diagnosable — the panel used to collapse every 422 into
    // "请求失败", which is what a stale backend looked like from the browser.
    function errorMessage(payload, response) {
        const detail = payload && payload.detail;
        if (typeof detail === "string") return detail;
        if (Array.isArray(detail) && detail.length) {
            return detail.map((item) => {
                const field = (item.loc || [])
                    .filter((part) => part !== "body").join(".");
                return field ? `${field}: ${item.msg}` : item.msg;
            }).join("; ");
        }
        return response.statusText || "请求失败";
    }

    async function api(path, options) {
        const response = await fetch(path, options);
        let payload = null;
        try { payload = await response.json(); } catch (error) { payload = null; }
        if (!response.ok) throw new Error(errorMessage(payload, response));
        return payload;
    }

    // -- provider ------------------------------------------------------------

    // The provider has one control and one value: the bar's toggle, which is
    // always in sight. It used to be in two places — the toggle and a select
    // inside the panel — and the panel's copy is gone: the panel is closed until
    // a selection opens it, so it could not show the choice at the moment a
    // reader wants to make it. `renderProvider` paints the one control from
    // `state.provider`, which the server rendered it with.
    function renderProvider() {
        for (const option of document.querySelectorAll("#provider-toggle .provider-option")) {
            const chosen = option.dataset.provider === state.provider;
            option.setAttribute("aria-checked", chosen ? "true" : "false");
            // A radiogroup is one tab stop: Tab lands on the checked option and
            // the arrows move within the group (see init's keydown).
            option.tabIndex = chosen ? 0 : -1;
        }
    }

    // The choice the shell was rendered with — the server's own answer
    // (routers/reader.py). Reading it back from the markup keeps the first paint
    // authoritative: if /api/settings cannot be reached, the control on screen
    // and the provider sent with a request still agree.
    function renderedProvider() {
        const checked = document.querySelector(
            "#provider-toggle .provider-option[aria-checked='true']");
        return (checked && checked.dataset.provider) || "ollama_cloud";
    }

    async function loadSettings() {
        try {
            const settings = await api("/api/settings");
            state.provider = settings.provider_override || settings.default_provider;
            renderProvider();
        } catch (error) { /* the shell's server-rendered choice stands */ }
    }

    async function setProvider(provider) {
        state.provider = provider;
        renderProvider();
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

    // `keepState` hides the panel without wiping what it holds. It is used when
    // a dismiss lands while the AI is still thinking: the reply is on its way,
    // so it is kept (and shown when the panel is reopened) rather than thrown
    // away with the reset.
    function closePanel(keepState) {
        el("ai-panel").hidden = true;
        el("toggle-panel").hidden = false;
        if (!keepState) resetPanel();
    }

    // X and ESC are deliberate closes: a close while the AI is thinking would
    // lose the in-flight result, so those are refused with a toast instead (the
    // reference reader's rule). Click-outside is a *dismiss* — the reader
    // clicking back into the book to keep reading — and must always get the
    // panel out of the way, so it passes `force`; the reply is kept rather than
    // discarded.
    function requestClose(force) {
        if (state.busy && !force) {
            const message = "AI 正在思考中，请稍候…";
            if (el("toast").textContent !== message) toast(message);
            return;
        }
        closePanel(!!force && state.busy);
    }

    function resetPanel() {
        state.highlightId = null;
        state.mode = "analysis";
        state.conversation = [];
        state.saved = false;
        state.selection = null;
        // Nothing from the panel that closed may colour the next one: a stale
        // summary would be saved as the new panel's content, and a stale type
        // would file it under the wrong kind (REVIEW P3-1). The edit draft goes
        // with them — a stale flag would make the next 保存 update *that*
        // analysis instead of saving a new one (P1-4).
        state.summary = null;
        state.analysisType = null;
        state.editing = null;
        state.editingDraft = false;
        el("panel-selected").textContent = "";
        el("panel-body").innerHTML = "";
        // The label belongs to the mode that set it (保存笔记 / 保存总结 /
        // 保存修改), so it goes back to the default with everything else.
        el("panel-save").textContent = "保存到数据库";
        el("discussion-log").hidden = true;
        el("discussion-log").innerHTML = "";
        el("discussion-input-row").hidden = true;
        el("discussion-input").value = "";
        setDeleteLabel(false);
        showButtons({});
    }

    function showButtons(visible) {
        // No 编辑笔记 button: each saved analysis carries its own 编辑, which is
        // where editing belongs. The panel-wide button was wired but never
        // shown, so it was an unreachable control (REVIEW P3-15).
        for (const name of ["save", "summarize", "delete"]) {
            const button = el("panel-" + name);
            button.hidden = !visible[name];
        }
    }

    // Before a save the delete button is a cancel: nothing is stored yet, so
    // there is no highlight to remove. After a save it removes the highlight.
    function setDeleteLabel(saved) {
        el("panel-delete").textContent = saved ? "删除高亮" : "取消";
    }

    function setBusy(busy) {
        state.busy = busy;
        el("discussion-send").disabled = busy;
        const body = el("panel-body");
        if (busy) {
            body.innerHTML = '<div class="loading">AI 正在思考…</div>';
        } else if (body.querySelector(".loading")) {
            // The placeholder is still there: the request finished without
            // putting anything here (a discussion reply renders into the log,
            // not the body), so clear it rather than leave a stale "thinking"
            // line sitting above the conversation.
            body.innerHTML = "";
        }
    }

    // -- the public surface --------------------------------------------------

    const P = {};
    P.state = state;
    P.loadSettings = loadSettings;

    P.init = function () {
        // The provider the shell was rendered with, before any request: the
        // server rendered it, so it is already the right one (routers/reader.py)
        // — and /api/settings only confirms it.
        state.provider = renderedProvider();
        renderProvider();
        // The bar's toggle. A radiogroup is one tab stop, so the arrows move
        // between the two options; a click, or Space/Enter on an option, is
        // native button behaviour and arrives as a click.
        const providerToggle = el("provider-toggle");
        providerToggle.addEventListener("click", (event) => {
            const option = event.target.closest(".provider-option");
            if (option && option.dataset.provider !== state.provider) {
                setProvider(option.dataset.provider);   // nothing to store if unchanged
            }
        });
        providerToggle.addEventListener("keydown", (event) => {
            const step = { ArrowLeft: -1, ArrowUp: -1,
                           ArrowRight: 1, ArrowDown: 1 }[event.key];
            if (!step) return;
            const options = [...providerToggle.querySelectorAll(".provider-option")];
            const at = options.findIndex(
                (option) => option.dataset.provider === state.provider);
            const next = options[(at + step + options.length) % options.length];
            if (!next) return;
            event.preventDefault();
            next.focus();
            setProvider(next.dataset.provider);
        });
        el("panel-close").addEventListener("click", () => requestClose());
        el("toggle-panel").addEventListener("click", () => openPanel());
        el("panel-save").addEventListener("click", () => saveCurrent());
        el("panel-delete").addEventListener("click", () => deleteCurrent());
        el("panel-summarize").addEventListener("click", () => summarizeDiscussion());
        el("discussion-send").addEventListener("click", () => sendDiscussion());
        for (const item of document.querySelectorAll("#context-menu .context-menu-item")) {
            item.addEventListener("click", () => {
                hideContextMenu();
                handleAction(item.dataset.action);
            });
            // The items are focusable (role="menuitem", tabindex="0"), so a
            // reader who has never touched a mouse can still reach the actions:
            // Enter or Space does what a click does (REVIEW P1-5).
            item.addEventListener("keydown", (event) => {
                if (event.key !== "Enter" && event.key !== " ") return;
                event.preventDefault();
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
        // `true` = dismiss, never refused: even while the AI is thinking, the
        // reader must be able to click back into the book and keep reading.
        document.addEventListener("mousedown", (event) => {
            if (el("ai-panel").hidden) return;
            const inside = event.target.closest("#ai-panel, #context-menu, #toggle-panel");
            if (!inside) requestClose(true);
        });
        loadSettings();
    };

    P.setChapter = function (index) {
        state.index = index;
        hideContextMenu();
    };

    // The chapter's blocks, on demand and from cache. reader.js needs both
    // shapes for the reading position's anchor (REVIEW P2-10): `cachedBlocks`
    // synchronously, because the position is measured the instant before the
    // frame moves to the next chapter — an await would measure the wrong
    // document — and `blocksFor` for the resume, which can wait for them.
    P.blocksFor = blocksFor;
    P.cachedBlocks = function (index) {
        return state.blocks[index] || null;
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
        // The context is read from the document, not from the extractor's copy
        // of the block: only the document knows *which* occurrence the reader
        // selected. `block.text.indexOf(found.text)` answers "the first one", so
        // a paragraph that repeats a sentence used to store the other
        // occurrence's surroundings — and the mark then painted that one, while
        // the context sent to the AI described text the reader had not selected
        // (REVIEW P2-10).
        const root = blockElement(found.doc, block);
        const around = root
            ? contextAround(found.doc, root, found.range, CONTEXT_SPAN) : null;
        if (around) {
            return { text: found.text, block_id: block.id,
                     context_before: around.before, context_after: around.after };
        }
        // No element to measure against (the block's text is not one run in the
        // served document): the extractor's copy is all there is, and it can
        // only offer the first occurrence.
        const at = block.text.indexOf(found.text);
        return {
            text: found.text,
            block_id: block.id,
            context_before: block.text.slice(Math.max(0, at - CONTEXT_SPAN), at),
            context_after: block.text.slice(at + found.text.length,
                                            at + found.text.length + CONTEXT_SPAN),
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
        // Focus the first item, so the menu can be driven from the keyboard —
        // Tab reaches the rest. Focus moves without a click, so the frame keeps
        // the selection the menu is about (REVIEW P1-5).
        const first = menu.querySelector(".context-menu-item");
        if (first && first.focus) first.focus();
    }

    // The selection, resolved to a block when the lookup answers. It is an
    // enrichment: a refused /api/text must not take the menu down with it, since
    // the menu is about the text the reader selected and only *saving* a
    // highlight wants a block id.
    async function selectionOrNull() {
        try {
            return await computeSelection();
        } catch (error) {
            console.warn("ai-reader: could not resolve the selection's block", error);
            const found = selectionInFrame();
            return found ? { text: found.text, block_id: null,
                             context_before: "", context_after: "" } : null;
        }
    }

    // The menu over the selection, for a trigger that has no pointer
    // coordinates to give it: the selection's own box decides where it opens.
    function openMenuOverSelection() {
        const found = selectionInFrame();
        const frameRect = frameEl().getBoundingClientRect();
        let x = frameRect.left + 24;
        let y = frameRect.top + 64;
        if (found && found.range) {
            const box = found.range.getBoundingClientRect();
            x = frameRect.left + box.left;
            y = frameRect.top + box.bottom + 12;
        }
        showContextMenu(x, y);
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
        // presses. Dismiss here instead: `true` so a press back into the book
        // always closes the panel, even while the AI is thinking (the reply is
        // kept, not lost). A press on a painted highlight is the exception:
        // that highlight's own click handler opens the panel for it, so closing
        // first would only flicker.
        doc.addEventListener("mousedown", (event) => {
            if (el("ai-panel").hidden) return;
            const target = event.target;
            if (target.closest && target.closest("mark.reader-highlight")) return;
            requestClose(true);
        });
        doc.addEventListener("mouseup", async (event) => {
            const selection = await selectionOrNull();
            if (!selection) { hideContextMenu(); return; }
            state.selection = selection;
            const frameRect = frameEl().getBoundingClientRect();
            showContextMenu(frameRect.left + event.clientX, frameRect.top + event.clientY + 12);
        });
        // A selection made with the keyboard — Shift+arrows — has no mouseup, so
        // the menu needs a trigger that does not need a pointer. Ctrl/Cmd+K
        // (the reader's own habit, and the reference's) opens it over the
        // selection (REVIEW P1-5).
        doc.addEventListener("keydown", async (event) => {
            if (event.key !== "k" && event.key !== "K") return;
            if (!event.ctrlKey && !event.metaKey) return;
            const selection = await selectionOrNull();
            if (!selection) return;
            event.preventDefault();
            state.selection = selection;
            openMenuOverSelection();
        });
    };

    // -- actions -------------------------------------------------------------

    // A highlight is created only when the reader saves content for it (see
    // saveCurrent): choosing an action, explaining the text and then walking
    // away must leave no mark behind.

    // Copying cannot go through the Clipboard API alone. That API exists only
    // in a *secure context* — https, or localhost — and this reader is normally
    // served over plain http on a LAN address (http://192.168.…:8123), where
    // `navigator.clipboard` is not there at all. 复制文本 called it unguarded,
    // so on the real deployment it raised `TypeError: navigator.clipboard is
    // undefined`: the text was not copied, no toast appeared, and nothing said
    // so. Every test ran on 127.0.0.1, where the API does exist — which is why
    // this survived the rewrite (the reference implementation had the fallback
    // below; the port dropped it).
    //
    // Returns whether the text really reached the clipboard, so the caller can
    // report a failure instead of a copy that never happened.
    async function copyText(text) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            try {
                await navigator.clipboard.writeText(text);
                return true;
            } catch (error) {
                // A refused permission (a browser policy, an unfocused window)
                // is not a reason to give up: try the fallback first.
                console.warn("clipboard.writeText refused the copy:", error);
            }
        }
        // The fallback: a staging textarea, selected, copied by the document
        // itself. It works on an insecure origin, which is the whole point.
        const staging = document.createElement("textarea");
        staging.value = text;
        staging.setAttribute("readonly", "");
        staging.style.position = "fixed";
        staging.style.top = "-1000px";
        document.body.appendChild(staging);
        try {
            staging.select();
            return document.execCommand("copy") === true;
        } catch (error) {
            console.warn("the fallback copy failed:", error);
            return false;
        } finally {
            staging.remove();
        }
    }

    async function handleAction(action) {
        const selection = state.selection;
        if (action === "copy") {
            if (!selection) { toast("请先选中文字"); return; }
            const copied = await copyText(selection.text);
            if (copied) toast("已复制到剪贴板");
            else toast("复制失败，请手动复制", "error");
            return;
        }
        if (!selection) { toast("请先选中文字"); return; }
        resetPanel();
        state.selection = selection;
        el("panel-selected").textContent = selection.text;
        openPanel(KIND_LABELS[action] || "AI 分析");
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
                    analysis_type: kind,
                    selected_text: state.selection.text,
                    // The halves, never their join: the selection sits between
                    // them, and the server labels the three parts (P1-3).
                    context_before: state.selection.context_before || "",
                    context_after: state.selection.context_after || "",
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
        // The note is the whole point of this mode: put the caret in the box,
        // so 添加笔记 ends with typing rather than with a second click. The
        // panel is already open (openPanel ran before the highlight was
        // created), so the box is laid out and focusable by now.
        el("comment-input").focus();
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
                    selected_text: state.selection.text,
                    context_before: state.selection.context_before || "",
                    context_after: state.selection.context_after || "",
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
                    // No `selected_text`: the selection is the first message of
                    // the history, and the field was never read (P3-15).
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
                    // The transcript is the input; the selection is its first
                    // message (P3-15).
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
        // An open edit box makes 保存修改 an update, not a new save (P1-4).
        if (state.editingDraft) return saveEdit();
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
        const selection = state.selection || {};
        try {
            // The mark and its content are saved together: with no highlight
            // yet, the selection travels with the analysis and the server
            // creates the highlight in the same act. An explanation that is
            // never saved therefore leaves no highlight behind.
            const payload = await api("/api/ai/save", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    highlight_id: state.highlightId,
                    analysis_type: analysisType,
                    prompt: selection.text || "",
                    response: response,
                    book_id: state.slug,
                    chapter_index: state.index,
                    selected_text: selection.text || "",
                    block_id: selection.block_id || null,
                    context_before: selection.context_before || "",
                    context_after: selection.context_after || "",
                }),
            });
            if (payload && payload.highlight_id) {
                state.highlightId = payload.highlight_id;
            }
            state.saved = true;
            setDeleteLabel(true);
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

    // Editing happens in the panel, in the same textarea a new note uses.
    // `window.prompt` was the defect: it is a single-line box, so every stored
    // analysis — Markdown with paragraphs, lists and headings — came back
    // flattened onto one line the moment it was opened and saved, with no undo
    // (REVIEW P1-4).
    function editCurrent() {
        const analysis = state.editing;
        if (!analysis) return;
        el("panel-body").innerHTML =
            '<textarea id="comment-input" class="comment-input" rows="8"></textarea>';
        const box = el("comment-input");
        box.value = analysis.response;
        box.focus();
        showButtons({ save: true, delete: true });
        el("panel-save").textContent = "保存修改";
        state.editingDraft = true;   // saveCurrent() then PUTs this analysis
    }

    // The update half of an edit. The box is deliberately left in place when
    // the request fails: the reader's draft is the only copy of their words.
    async function saveEdit() {
        const analysis = state.editing;
        const box = el("comment-input");
        const response = box ? box.value.trim() : "";
        if (!analysis || !response) { toast("没有可保存的内容"); return; }
        try {
            await api(`/api/ai/update/${analysis.id}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ response: response }),
            });
            state.editingDraft = false;
            state.editing = null;
            toast("已更新");
            // The panel paints saved analyses from the chapter's cached
            // highlights, so the edit is fetched back before it is shown —
            // otherwise the old text would be repainted over the new.
            await refreshHighlights();
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

    function wrapText(doc, root, text, highlight) {
        const nodes = textNodes(doc, root);
        const full = nodes.map((item) => item.nodeValue).join("");
        // Which occurrence, when the block repeats the text: the context saved
        // with the selection decides (REVIEW P2-10).
        const found = findTextRange(full, text,
                                    highlight.context_before, highlight.context_after);
        if (!found) return false;
        const start = offsetToPoint(nodes, found.at);
        const end = offsetToPoint(nodes, found.at + found.length);
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
                            // The stored context travels with it: a note added
                            // later to this mark must not lose the surroundings
                            // that say which occurrence it is (REVIEW P2-10).
                            context_before: highlight.context_before || "",
                            context_after: highlight.context_after || "" };
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
        setDeleteLabel(true);
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





