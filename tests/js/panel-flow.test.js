/* The reader's main flow, driven through the panel's own wiring — REVIEW T1.
 *
 * This is step 3 of T1 without a browser: select text → 解释说明 → 保存 →
 * the mark exists and the toast is shown. The selection itself is the one thing
 * a stub cannot make (the frame's own document and a real Range are needed), so
 * the test hands `state.selection` in the shape the mouseup handler produces —
 * see computeSelection() in panel.js. Everything after that is real: the menu
 * item is clicked, the panel's listeners run, and the requests are the ones the
 * browser would send.
 *
 * What it cannot see — layout, painted pixels, a real toast on screen — is what
 * a Playwright smoke would add.
 */
const test = require("node:test");
const assert = require("node:assert/strict");

const { createPage } = require("./dom-stub.js");

const SELECTION = {
    text: "The first paragraph mentions a plate",
    block_id: "c0000/b0003",
    context_before: "…《自由的窄廊》奠基於…",
    context_after: " and then keeps going",
};

function scriptedPage(options = {}) {
    const page = createPage(options);
    page.route(/\/api\/ai\/analyze$/, {
        response: "## 解释\n\n这是一段解释。", provider_used: "ollama",
        status: "success",
    });
    page.route(/\/api\/ai\/save$/, {
        status: "success", analysis_id: 1, highlight_id: 42,
    });
    page.route(/\/api\/text\//, { blocks: [] });
    page.route(/\/api\/highlights\//, { highlights: [] });
    page.P.init();
    page.P.setBook("Fixture Book");
    page.P.setChapter(0);
    page.P.state.selection = { ...SELECTION };
    return page;
}

test("explaining a selection asks for the context and stores nothing yet", async () => {
    const page = scriptedPage();
    const item = page.menuItems.find((i) => i.dataset.action === "fact_check");
    item.click();
    await page.settle(); await page.settle();

    const request = page.lastRequest(/\/api\/ai\/analyze$/);
    assert.ok(request, "the analysis was requested");
    assert.equal(request.method, "POST");
    const body = page.body(request);
    assert.equal(body.analysis_type, "fact_check");
    assert.equal(body.selected_text, SELECTION.text);
    // The halves, never their join: the selection sits between them (P1-3).
    assert.equal(body.context_before, SELECTION.context_before);
    assert.equal(body.context_after, SELECTION.context_after);
    assert.equal(body.context, undefined);

    // Nothing is stored by looking: a highlight is created only on save.
    assert.equal(page.requests.filter((r) => /\/api\/ai\/save$/.test(r.url)).length, 0);

    // The reply is rendered and the save button is offered.
    assert.match(page.el("panel-body").innerHTML, /这是一段解释/);
    assert.equal(page.el("panel-save").hidden, false);
    assert.equal(page.el("panel-save").textContent, "保存到数据库");
});

test("saving it creates the mark with the selection and shows a visible toast", async () => {
    const page = scriptedPage();
    page.menuItems.find((i) => i.dataset.action === "fact_check").click();
    await page.settle(); await page.settle();

    page.el("panel-save").click();
    await page.settle(); await page.settle();

    const save = page.lastRequest(/\/api\/ai\/save$/);
    assert.ok(save, "the save was requested");
    const body = page.body(save);
    assert.equal(body.analysis_type, "fact_check");
    assert.equal(body.selected_text, SELECTION.text);
    assert.equal(body.block_id, SELECTION.block_id);      // the mark's anchor
    assert.equal(body.book_id, "Fixture Book");
    assert.equal(body.chapter_index, 0);
    assert.equal(body.response, "## 解释\n\n这是一段解释。");
    assert.equal(body.context_before, SELECTION.context_before);

    // The toast is what tells the reader it worked — and it is only visible
    // because `.toast.visible` has a rule (P1-1); the class guard pins that
    // half, this pins the class being applied at all.
    assert.equal(page.el("toast").textContent, "已保存到数据库");
    assert.equal(page.el("toast").className, "toast visible");

    // The panel is now about a stored mark: no save button, a delete label.
    assert.equal(page.el("panel-save").hidden, true);
    assert.equal(page.el("panel-delete").textContent, "删除高亮");

    // …and the chapter's highlights are fetched again, which is the repaint.
    assert.ok(page.lastRequest(/\/api\/highlights\//), "the marks were refreshed");
});

test("a failed save keeps the panel open and says so", async () => {
    const page = scriptedPage();
    page.route(/\/api\/ai\/save$/, () => { throw new Error("nope"); });
    page.menuItems.find((i) => i.dataset.action === "fact_check").click();
    await page.settle(); await page.settle();

    page.el("panel-save").click();
    await page.settle(); await page.settle();

    // The reader is told, and the save is still on offer: nothing was stored.
    assert.equal(page.el("toast").className, "toast visible error");
    assert.equal(page.el("panel-save").hidden, false);
    assert.equal(page.el("panel-delete").textContent, "取消");
});

// The frame with a text selection in it, wired the way the shell wires it. The
// keyboard path to the menu starts from a selection made with Shift+arrows,
// which never fires a mouseup (REVIEW P1-5).
async function selectionPage() {
    const page = scriptedPage();
    const range = {
        startContainer: { nodeType: 1, parentNode: null },
        getBoundingClientRect: () => ({ left: 12, top: 4, bottom: 20 }),
    };
    page.frame().contentDocument = {
        _listeners: {},
        addEventListener(type, fn) { (this._listeners[type] ||= []).push(fn); },
    };
    page.frame().contentWindow = {
        getSelection: () => ({ toString: () => SELECTION.text, getRangeAt: () => range }),
    };
    await page.P.onFrameLoad();      // wires the frame's mouseup and keydown
    return page;
}

test("a menu item answers Enter, so the actions need no mouse", async () => {
    const page = scriptedPage();
    page.el("context-menu").hidden = false;
    const item = page.menuItems.find((i) => i.dataset.action === "fact_check");

    page.fire("keydown", item, { key: "Enter" });
    await page.settle(); await page.settle();

    assert.equal(page.el("context-menu").hidden, true, "the menu closes");
    const request = page.lastRequest(/\/api\/ai\/analyze$/);
    assert.ok(request, "the analysis was requested");
    assert.equal(page.body(request).selected_text, SELECTION.text);
});

test("Space activates a menu item too", async () => {
    const page = scriptedPage();
    page.el("context-menu").hidden = false;
    const item = page.menuItems.find((i) => i.dataset.action === "copy");

    page.fire("keydown", item, { key: " " });
    await page.settle();

    assert.equal(page.el("context-menu").hidden, true);
    assert.equal(page.el("toast").textContent, "已复制到剪贴板");
});

// -- 复制文本 ---------------------------------------------------------------
//
// Copying must not depend on the Clipboard API. That API is a *secure context*
// feature — https, or localhost — and the reader is normally served over plain
// http on a LAN address (http://192.168.…:8123), where `navigator.clipboard` is
// simply absent. The action called it unguarded, so on the deployment that
// exists the click raised `TypeError: navigator.clipboard is undefined`, copied
// nothing and said nothing — and every test until now ran on localhost, where
// the API is there.

test("the Clipboard API is used when the browser has one", async () => {
    const page = scriptedPage();
    page.el("context-menu").hidden = false;
    page.menuItems.find((i) => i.dataset.action === "copy").click();
    await page.settle();

    assert.deepEqual(page.clipboardWrites, [SELECTION.text]);
    assert.deepEqual(page.document.copied, [], "the fallback was not needed");
    assert.equal(page.el("toast").textContent, "已复制到剪贴板");
});

test("an insecure origin copies through the fallback instead of throwing", async () => {
    const page = scriptedPage({ clipboard: false });
    page.el("context-menu").hidden = false;
    page.menuItems.find((i) => i.dataset.action === "copy").click();
    await page.settle();

    assert.deepEqual(page.document.copied, [SELECTION.text],
                     "the document was asked to copy the selected text");
    assert.equal(page.el("toast").textContent, "已复制到剪贴板");
    assert.equal(page.el("toast").className.includes("error"), false);

    const staging = page.created.filter((element) => element.tagName === "TEXTAREA");
    assert.equal(staging.length, 1, "one staging textarea");
    assert.ok(staging[0].removed, "and it is taken back out of the document");
});

test("a refused Clipboard API falls back rather than giving up", async () => {
    const page = scriptedPage({ clipboard: "denied" });
    page.el("context-menu").hidden = false;
    page.menuItems.find((i) => i.dataset.action === "copy").click();
    await page.settle();

    assert.deepEqual(page.document.copied, [SELECTION.text]);
    assert.equal(page.el("toast").textContent, "已复制到剪贴板");
});

test("a copy that did not happen says so, instead of claiming success", async () => {
    const page = scriptedPage({ clipboard: false });
    page.document.copyWorks = false;
    page.el("context-menu").hidden = false;
    page.menuItems.find((i) => i.dataset.action === "copy").click();
    await page.settle();

    assert.equal(page.el("toast").textContent, "复制失败，请手动复制");
    assert.ok(page.el("toast").className.includes("error"),
              "and the toast is the error kind");
});

// -- the AI provider, in the bar --------------------------------------------
//
// The provider was changeable only inside the AI panel, which is not on screen
// until a selection opens it — so "which model answers" was a setting the
// reader could not see, let alone set, until they had already asked something.
// The bar's toggle is the same setting in the open: two named options, and one
// value shared with the panel's select, so the two cannot disagree.

test("the bar's toggle and the panel's select are one setting", async () => {
    const page = scriptedPage();
    page.route(/\/api\/settings$/, { provider_override: "ollama", status: "success" });

    const local = page.providerOptions.find((o) => o.dataset.provider === "ollama");
    page.fire("click", page.el("provider-toggle"), { target: local });
    await page.settle();

    assert.equal(page.P.state.provider, "ollama");
    assert.equal(page.body(page.lastRequest(/\/api\/settings$/)).provider_override,
                 "ollama", "the choice is stored, as the panel's select did");
    assert.equal(local.getAttribute("aria-checked"), "true");
    assert.equal(page.providerOptions[1].getAttribute("aria-checked"), "false");
    assert.equal(page.el("provider-select").value, "ollama",
                 "the panel's select shows the same value");

    // …and it is what the next request carries, without opening the panel.
    page.menuItems.find((i) => i.dataset.action === "fact_check").click();
    await page.settle(); await page.settle();
    assert.equal(page.body(page.lastRequest(/\/api\/ai\/analyze$/)).provider, "ollama");
});

test("a radiogroup is one tab stop, and the arrows move it", async () => {
    const page = scriptedPage();
    page.route(/\/api\/settings$/, { provider_override: "ollama", status: "success" });

    // Only the checked option is in the tab order: the group is one stop.
    assert.deepEqual(page.providerOptions.map((o) => o.tabIndex), [-1, 0]);

    page.fire("keydown", page.el("provider-toggle"), { key: "ArrowRight" });
    await page.settle();

    assert.equal(page.P.state.provider, "ollama", "the arrow chose the other option");
    assert.equal(page.providerOptions[0].focused, true, "and focus moved with it");
    assert.deepEqual(page.providerOptions.map((o) => o.tabIndex), [0, -1]);
});

test("the provider the shell was rendered with is the one in force", async () => {
    // `provider:` is what the server rendered as checked (routers/reader.py).
    // Reading it back means the first paint is authoritative: if /api/settings
    // cannot be reached, the control and the requests still agree.
    const page = scriptedPage({ provider: "ollama" });

    assert.equal(page.P.state.provider, "ollama");
    assert.equal(page.el("provider-select").value, "ollama");
    assert.equal(page.providerOptions[0].getAttribute("aria-checked"), "true");
});

test("Ctrl+K opens the menu over a selection made with the keyboard", async () => {
    const page = await selectionPage();
    assert.equal(page.el("context-menu").hidden, true, "closed to begin with");

    page.fire("keydown", page.frame().contentDocument, { key: "k", ctrlKey: true });
    await page.settle();

    assert.equal(page.el("context-menu").hidden, false, "the menu opened");
    assert.equal(page.P.state.selection.text, SELECTION.text);

    // …and the item it focused does the action.
    const item = page.menuItems.find((i) => i.dataset.action === "comment");
    page.fire("keydown", item, { key: "Enter" });
    await page.settle();

    assert.equal(page.el("panel-save").textContent, "保存笔记");
    assert.equal(page.el("comment-input").focused, true, "the note box takes the caret");
});

test("Ctrl+K with nothing selected opens nothing", async () => {
    const page = await selectionPage();
    page.frame().contentWindow.getSelection = () => ({ toString: () => "   " });

    page.fire("keydown", page.frame().contentDocument, { key: "k", ctrlKey: true });
    await page.settle();

    assert.equal(page.el("context-menu").hidden, true);
});


test("a note is stored as a comment, with the selection it marks", async () => {
    const page = scriptedPage();
    page.menuItems.find((i) => i.dataset.action === "comment").click();
    await page.settle();

    const box = page.el("comment-input");
    assert.ok(box, "the note box is open");
    assert.equal(box.focused, true);
    assert.equal(page.el("panel-save").textContent, "保存笔记");
    box.value = "第一段笔记。\n\n第二段笔记。";

    page.el("panel-save").click();
    await page.settle(); await page.settle();

    const body = page.body(page.lastRequest(/\/api\/ai\/save$/));
    assert.equal(body.analysis_type, "comment");
    assert.equal(body.response, "第一段笔记。\n\n第二段笔记。");
    assert.equal(page.el("toast").className, "toast visible");
});


test("with DOMPurify missing, markdown is escaped rather than injected", async () => {
    // A sanitiser must fail closed: purify.min.js 404s, or arrives truncated,
    // and `marked` passes raw HTML through by default — so the old fallback put
    // whatever the model wrote straight into innerHTML (REVIEW P3-13).
    const page = createPage({ domPurify: false });
    const hostile = '<img src=x onerror="alert(1)">';
    page.route(/\/api\/ai\/discussion\/start$/, {
        response: "an overview", provider_used: "ollama", status: "success",
        conversation_history: [{ role: "user", content: hostile },
                               { role: "assistant", content: "an overview" }],
    });
    page.route(/\/api\/text\//, { blocks: [] });
    page.route(/\/api\/highlights\//, { highlights: [] });
    page.P.init();
    page.P.setBook("Fixture Book");
    page.P.state.selection = { ...SELECTION };
    page.menuItems.find((i) => i.dataset.action === "discussion").click();
    await page.settle(); await page.settle();

    const bubble = page.created.find((el) => /discussion-message/.test(el.className));
    assert.ok(bubble, "the discussion rendered a bubble");
    assert.ok(!bubble.innerHTML.includes("<img"),
              `raw HTML survived into innerHTML: ${bubble.innerHTML}`);
    assert.ok(bubble.innerHTML.includes("&lt;img"), bubble.innerHTML);
});


test("one panel's label and state do not leak into the next", async () => {
    // A summary leaves the save button reading 保存总结 and a summary in memory;
    // the panel that follows must not offer to save either (REVIEW P3-1).
    const page = scriptedPage();
    page.route(/\/api\/ai\/discussion\/start$/, {
        response: "an overview", provider_used: "ollama", status: "success",
        conversation_history: [{ role: "user", content: SELECTION.text },
                               { role: "assistant", content: "an overview" }],
    });
    page.route(/\/api\/ai\/discussion\/summarize$/, {
        summary: "a summary of the discussion", provider_used: "ollama",
        status: "success",
    });

    page.menuItems.find((i) => i.dataset.action === "discussion").click();
    await page.settle(); await page.settle();
    page.el("panel-summarize").click();
    await page.settle(); await page.settle();
    assert.equal(page.el("panel-save").textContent, "保存总结");
    assert.equal(page.P.state.summary, "a summary of the discussion");
    // The transcript is the input; no `selected_text` is sent (P3-15).
    const summarized = page.body(page.lastRequest(/\/api\/ai\/discussion\/summarize$/));
    assert.equal(summarized.selected_text, undefined);
    assert.equal(summarized.conversation_history.length, 2);

    // The reader closes the panel and selects something else — a real click
    // arrives with a fresh selection from the frame's mouseup handler.
    page.el("panel-close").click();
    page.P.state.selection = { ...SELECTION };
    page.menuItems.find((i) => i.dataset.action === "fact_check").click();
    await page.settle(); await page.settle();

    assert.equal(page.el("panel-save").textContent, "保存到数据库");
    assert.equal(page.P.state.summary, null, "no stale summary to save");
    assert.equal(page.P.state.analysisType, "fact_check");
});
