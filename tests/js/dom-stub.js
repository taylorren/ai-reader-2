/* A stub document and page loader for the reader's scripts — REVIEW T1.
 *
 * The repo has no jsdom and no npm dependency, so the front end's *wiring* is
 * exercised against a small hand-rolled DOM instead: enough of one to load
 * static/js/reader-core.js and panel.js unmodified, click the buttons the shell
 * carries, and see what the scripts send. It is deliberately not a browser —
 * layout, painting and a real text selection are out of reach here (that is
 * what a Playwright smoke would add), but every request shape, every class the
 * toast gets and every state transition is real.
 *
 * Used by tests/js/panel-flow.test.js.
 */
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const REPO = path.resolve(__dirname, "..", "..");

// The shell's own context menu (templates/reader.html), so a test can click
// 解释说明 the way a reader does instead of calling a private function.
const MENU_ACTIONS = ["fact_check", "discussion", "comment", "copy"];

function makeElement(tag, registry) {
    const element = {
        tagName: String(tag || "div").toUpperCase(),
        id: "", hidden: false, value: "", textContent: "", className: "",
        style: {}, dataset: {}, children: [], focused: false, _attributes: {},
        _innerHTML: "", _createdIds: [], _listeners: {}, _classes: new Set(),
        addEventListener(type, fn) { (this._listeners[type] ||= []).push(fn); },
        click() { for (const fn of this._listeners.click || []) fn({ target: this }); },
        appendChild(child) { this.children.push(child); return child; },
        setAttribute(name, value) { this._attributes[name] = String(value); },
        getAttribute(name) { return this._attributes[name]; },
        removeAttribute(name) { delete this._attributes[name]; },
        remove() { this.removed = true; },
        select() { this.selected = true; },
        scrollIntoView() {},
        // `.class` only: the shell's own listeners use compound selectors
        // (`#ai-panel, #context-menu, #toggle-panel`) that no stub element is
        // inside, while the provider toggle's click handler asks which option
        // was pressed.
        closest(selector) {
            if (!selector.startsWith(".")) return null;
            return (this.className || "").split(" ").includes(selector.slice(1))
                ? this : null;
        },
        querySelector: () => null,
        querySelectorAll: () => [],
        focus() { this.focused = true; },
        getBoundingClientRect: () => ({ top: 0, left: 0, width: 100, height: 100 }),
        classList: {
            add: (name) => element._classes.add(name),
            remove: (name) => element._classes.delete(name),
            toggle: (name, on) => (on ? element._classes.add(name)
                                     : element._classes.delete(name)),
            contains: (name) => element._classes.has(name),
        },
    };
    // `innerHTML = …` also removes what the old html created, so a later
    // getElementById does not still find it — a real DOM's behaviour, and the
    // difference between "the box is open" and "the box is gone".
    Object.defineProperty(element, "innerHTML", {
        get() { return this._innerHTML; },
        set(html) {
            for (const id of this._createdIds) delete registry[id];
            this._createdIds = [];
            this._innerHTML = String(html);
            this.children = [];
            for (const match of this._innerHTML.matchAll(/id="([^"]+)"/g)) {
                const child = makeElement("textarea", registry);
                child.id = match[1];
                registry[match[1]] = child;
                this._createdIds.push(match[1]);
            }
        },
    });
    return element;
}

function createPage(options = {}) {
    const registry = {};
    const created = [];
    const requests = [];
    const routes = [];
    const clipboardWrites = [];
    let currentIndex = 0;

    const documentStub = {
        // The copy fallback's other half (panel.js, copyText): it selects a
        // staging textarea and asks the document to copy that selection. A stub
        // has no clipboard, so what it can see — and what a test needs — is the
        // text the document was asked to copy. `copyWorks: false` is a browser
        // that refuses.
        copied: [],
        copyWorks: true,
        execCommand(command) {
            if (command !== "copy") return false;
            const staging = created.filter((element) => element.selected).pop();
            this.copied.push(staging ? staging.value : null);
            return this.copyWorks;
        },
        getElementById: (id) => (registry[id] ||= Object.assign(
            makeElement("div", registry), { id })),
        createElement: (tag) => {
            const element = makeElement(tag, registry);
            created.push(element);
            return element;
        },
        querySelectorAll: (selector) => (selector.includes("context-menu-item")
            ? menuItems
            : selector.includes("provider-option") ? providerOptions : []),
        // The shell's own attribute selector for the rendered provider
        // (panel.js's renderedProvider), answered from the options — so a test
        // can say which one the server rendered.
        querySelector: (selector) => (selector.includes("provider-option")
            ? providerOptions.find(
                (option) => option.getAttribute("aria-checked") === "true") || null
            : null),
        addEventListener() {},
        body: makeElement("body", registry),
    };

    const menuItems = MENU_ACTIONS.map((action) => {
        const item = makeElement("div", registry);
        item.dataset.action = action;
        return item;
    });

    // The bar's provider toggle (templates/reader.html): a radiogroup of two
    // options, so a test can click one and see what the page sends. It is the
    // only provider control — the panel's select was removed.
    // `createPage({provider})` is the *server-rendered* choice: which option
    // arrives checked, before any script has run.
    const providerOptions = ["ollama", "ollama_cloud"].map((provider) => {
        const option = makeElement("button", registry);
        option.dataset.provider = provider;
        option.className = "provider-option";
        return option;
    });
    if (options.provider) {
        for (const option of providerOptions) {
            option.setAttribute("aria-checked",
                option.dataset.provider === options.provider ? "true" : "false");
        }
    }
    registry["provider-toggle"] = Object.assign(makeElement("div", registry), {
        id: "provider-toggle",
        querySelectorAll: (selector) => (selector.includes("provider-option")
            ? providerOptions : []),
    });

    async function fetchStub(url, options) {
        requests.push({
            url,
            method: (options && options.method) || "GET",
            body: options && options.body,
        });
        for (const route of routes) {
            if (route.pattern.test(url)) {
                const payload = typeof route.payload === "function"
                    ? route.payload(url, options) : route.payload;
                return { ok: true, status: 200, statusText: "OK",
                         json: async () => payload };
            }
        }
        throw new Error(`the page asked for an unscripted URL: ${url}`);
    }

    // A browser's Clipboard API is a *secure context* feature: present on
    // localhost and on https, absent on the plain-http LAN address this reader
    // is really served from. `clipboard: false` models that deployment;
    // `clipboard: "denied"` models a browser that has the API and refuses the
    // write (a permission policy, an unfocused window).
    const navigatorStub = options.clipboard === false ? {} : {
        clipboard: {
            writeText(text) {
                if (options.clipboard === "denied") {
                    return Promise.reject(new Error("NotAllowedError"));
                }
                clipboardWrites.push(text);
                return Promise.resolve();
            },
        },
    };

    const sandbox = {
        document: documentStub,
        fetch: fetchStub,
        console,
        setTimeout: () => 0,          // timers are not what these tests are about
        clearTimeout: () => {},
        navigator: navigatorStub,
        marked: { parse: (markdown) => markdown },
        // A passthrough sanitiser: the real one is a vendor bundle, and these
        // tests are about what the panel does with its output. `domPurify:
        // false` models the file failing to load (REVIEW P3-13).
        DOMPurify: options.domPurify === false ? undefined : { sanitize: (html) => html },
        localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
        history: { replaceState() {}, pushState() {} },
        requestAnimationFrame: () => 0,
        cancelAnimationFrame: () => {},
        matchMedia: () => ({ matches: false, addEventListener() {} }),
        CSS: { escape: (value) => String(value).replace(/["\\]/g, "\\$&") },
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    // The shell's own order: the core module, then the panel, then reader.js.
    // `options.files` overrides the list (absolute paths allowed), which is how
    // a test can run a historical copy of one script against the rest.
    const files = options.files || (options.book
        ? ["reader-core.js", "panel.js", "reader.js"]
        : ["reader-core.js", "panel.js"]);
    if (options.book) sandbox.BOOK = options.book;
    for (const file of files) {
        const full = file.includes("/") ? file : path.join(REPO, "static", "js", file);
        vm.runInContext(fs.readFileSync(full, "utf8"), sandbox, { filename: file });
    }

    return {
        P: sandbox.window.ReaderPanel,
        el: (id) => registry[id],
        created,
        requests,
        menuItems,
        providerOptions,
        document: documentStub,
        clipboardWrites,
        frame: () => documentStub.getElementById("chapter-frame"),
        // Fire an event on a stub element, as the browser would: the shell's
        // frame `load` handler is how an in-book link is noticed, and its
        // keydown handlers are how a reader navigates without a mouse.
        fire(type, target, event = {}) {
            const payload = {
                target,
                preventDefault() {},
                stopPropagation() {},
                ...event,
            };
            for (const fn of (target._listeners[type] || [])) fn(payload);
        },
        // What the page is allowed to ask for; anything else throws, so a new
        // request the test does not know about is a failure, not a silent pass.
        // The most recently registered route wins, so a test can override the
        // page's scripted answers (a failing save, say).
        route(pattern, payload) { routes.unshift({ pattern, payload }); },
        lastRequest: (pattern) => requests.filter((r) => pattern.test(r.url)).pop(),
        body: (request) => JSON.parse(request.body),
        settle: () => new Promise((resolve) => setImmediate(resolve)),
    };
}

module.exports = { createPage };
