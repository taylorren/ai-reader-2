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
        style: {}, dataset: {}, children: [], focused: false,
        _innerHTML: "", _createdIds: [], _listeners: {}, _classes: new Set(),
        addEventListener(type, fn) { (this._listeners[type] ||= []).push(fn); },
        click() { for (const fn of this._listeners.click || []) fn({ target: this }); },
        appendChild(child) { this.children.push(child); return child; },
        querySelector: () => null,
        querySelectorAll: () => [],
        focus() { this.focused = true; },
        closest: () => null,
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

function createPage() {
    const registry = {};
    const created = [];
    const requests = [];
    const routes = [];
    let currentIndex = 0;

    const documentStub = {
        getElementById: (id) => (registry[id] ||= Object.assign(
            makeElement("div", registry), { id })),
        createElement: (tag) => {
            const element = makeElement(tag, registry);
            created.push(element);
            return element;
        },
        querySelectorAll: (selector) => (selector.includes("context-menu-item")
            ? menuItems : []),
        querySelector: () => null,
        addEventListener() {},
        body: makeElement("body", registry),
    };

    const menuItems = MENU_ACTIONS.map((action) => {
        const item = makeElement("div", registry);
        item.dataset.action = action;
        return item;
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

    const sandbox = {
        document: documentStub,
        fetch: fetchStub,
        console,
        setTimeout: () => 0,          // timers are not what these tests are about
        clearTimeout: () => {},
        navigator: { clipboard: { writeText() {} } },
        marked: { parse: (markdown) => markdown },
        DOMPurify: { sanitize: (html) => html },
        localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    for (const file of ["reader-core.js", "panel.js"]) {
        vm.runInContext(fs.readFileSync(path.join(REPO, "static", "js", file), "utf8"),
                        sandbox, { filename: file });
    }

    return {
        P: sandbox.window.ReaderPanel,
        el: (id) => registry[id],
        created,
        requests,
        menuItems,
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
