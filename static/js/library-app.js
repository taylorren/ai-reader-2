/* The library's interactions: theme, tabs, search, menus, upload, delete,
   completion.

The card grid is rendered by the server; these handlers act on it in place,
and reload when the grouping changes (upload, completion). The reload keeps the
shelf in the URL hash, so a reader who finishes a book from the completed shelf
comes back to it. */

const { createApp } = Vue;

const app = createApp({
    data() {
        return {
            // The two library filters, combined: a free-text query and the
            // letter index ("all" shows every group).
            query: "",
            group: "all",
            // The shelf in view. A book marked complete leaves the reading
            // shelf for the completed one, so "reading" is the default and
            // never shows a book the reader has finished.
            tab: "reading",
        };
    },
    mounted() {
        if (localStorage.getItem("reader-theme") === "dark") {
            document.body.classList.add("dark-mode");
            const toggle = document.querySelector(".theme-toggle");
            if (toggle) toggle.textContent = "☀️";
        }
        document.querySelectorAll(".progress-bar-fill[data-progress-percent]").forEach((bar) => {
            bar.style.width = `${bar.dataset.progressPercent || "0"}%`;
        });
        // The hash is how the shelf survives the reload that marking a book
        // complete triggers; without it that reload always landed on the
        // reading shelf, even for a reader working through the completed one.
        if (window.location.hash === "#completed") this.tab = "completed";
        this.showTab();
        this.hideEmptyGroups();
        this.applyFilters();
    },
    methods: {
        toggleTheme(event) {
            const isDark = document.body.classList.toggle("dark-mode");
            event.currentTarget.textContent = isDark ? "☀️" : "🌙";
            localStorage.setItem("reader-theme", isDark ? "dark" : "light");
        },
        setTab(key) {
            this.tab = key;
            this.showTab();
            // A letter with no books on this shelf would filter to nothing, so
            // the pills are brought up to date first — hideEmptyGroups may fall
            // back to 全部, and the filter must see that before it runs.
            this.hideEmptyGroups();
            this.applyFilters();
            this.rememberTab();
        },
        showTab() {
            document.querySelectorAll(".library-tab").forEach((tab) => {
                const active = tab.dataset.tab === this.tab;
                tab.classList.toggle("active", active);
                tab.setAttribute("aria-selected", active ? "true" : "false");
            });
            // Adding a book puts it on the reading shelf, so the card that
            // offers it has no place on the completed one.
            const add = document.getElementById("add-book-card");
            if (add) add.classList.toggle("hidden", this.tab === "completed");
        },
        rememberTab() {
            const url = new URL(window.location.href);
            if (this.tab === "completed") url.hash = "completed";
            else url.hash = "";
            history.replaceState(null, "", url);
        },
        // A card belongs to the shelf in view: the reading shelf takes every
        // book not marked complete, the completed shelf only those that are.
        cardIsOnTab(card) {
            const completed = card.dataset.completed === "true";
            return this.tab === "completed" ? completed : !completed;
        },
        filterBooks(event) {
            this.query = event.target.value.trim().toLowerCase();
            this.applyFilters();
        },
        setGroupFilter(key, event) {
            this.group = key;
            document.querySelectorAll(".library-index-link")
                .forEach((pill) => pill.classList.toggle("active", pill === event.currentTarget));
            this.applyFilters();
        },
        applyFilters() {
            // A card shows when it matches the query *and* the chosen letter
            // *and* belongs to the shelf in view.
            let visible = 0;
            let onShelf = 0;
            document.querySelectorAll(".book-card").forEach((card) => {
                const matchesQuery = !this.query ||
                    (card.dataset.search || "").includes(this.query);
                const matchesGroup = this.group === "all" ||
                    card.dataset.group === this.group;
                const onTab = this.cardIsOnTab(card);
                if (onTab) onShelf += 1;
                const show = matchesQuery && matchesGroup && onTab;
                card.classList.toggle("hidden", !show);
                if (show) visible += 1;
            });
            // "No books match" is about the filters; a shelf with nothing on it
            // says its own thing, and an empty library says neither.
            const none = document.getElementById("no-results");
            if (none) none.hidden = !(onShelf > 0 && visible === 0);
            const empty = document.getElementById("no-completed");
            if (empty) {
                empty.hidden = !(this.tab === "completed" && onShelf === 0);
            }
        },
        // A group whose last card is gone must not keep its letter in the index:
        // clicking it would filter to nothing (REVIEW P3-12). If that group is
        // the one in view, the filter falls back to 全部 — otherwise the reader
        // is looking at an empty grid with the only way back hidden.
        //
        // "Gone" means gone from the shelf in view: a letter carried only by
        // finished books has no pill on the reading shelf, and gets one back
        // when the reader switches to the completed shelf.
        hideEmptyGroups() {
            const groups = new Set();
            document.querySelectorAll(".book-card").forEach((card) => {
                if (this.cardIsOnTab(card)) groups.add(card.dataset.group);
            });
            let fellBack = false;
            document.querySelectorAll(".library-index-link").forEach((pill) => {
                const key = pill.dataset.group;
                if (key === "all") return;
                const empty = !groups.has(key);
                pill.hidden = empty;
                if (empty && pill.classList.contains("active")) {
                    pill.classList.remove("active");
                    fellBack = true;
                }
            });
            if (fellBack) {
                const all = document.querySelector(
                    '.library-index-link[data-group="all"]');
                if (all) all.classList.add("active");
                this.group = "all";
            }
        },
        toggleMenu(event) {
            const menu = event.currentTarget.parentElement.querySelector(".dropdown-menu");
            const wasOpen = menu.classList.contains("show");
            document.querySelectorAll(".dropdown-menu.show")
                .forEach((other) => other.classList.remove("show"));
            if (!wasOpen) menu.classList.add("show");
        },
        openFilePicker() {
            document.getElementById("file-input").click();
        },
        handleFileUpload(event) {
            const file = event.target.files[0];
            if (file) this.uploadFile(file);
            event.target.value = "";
        },
        showStatus(message, state) {
            const status = document.getElementById("upload-status");
            document.getElementById("status-message").textContent = message;
            status.className = `upload-status show ${state || ""}`.trim();
            if (state === "success") {
                setTimeout(() => { status.className = "upload-status"; }, 4000);
            }
        },
        async uploadFile(file) {
            if (!file.name.toLowerCase().endsWith(".epub")) {
                this.showStatus("✗ 请选择 EPUB 文件 (Please choose an EPUB file)", "error");
                return;
            }
            this.showStatus(`Uploading ${file.name}…`, "");
            const body = new FormData();
            body.append("file", file);
            try {
                const response = await fetch("/upload", { method: "POST", body });
                const result = await response.json();
                if (!response.ok) throw new Error(result.detail || "Upload failed");
                const note = result.unsupported ? ` — ${result.unsupported}` : "";
                this.showStatus(`✓ ${result.title}${note}`, "success");
                // The book lands on the reading shelf, so the reload goes
                // there: an upload dropped on the page from the completed
                // shelf would otherwise come back to a shelf the new book is
                // not on.
                this.setTab("reading");
                setTimeout(() => window.location.reload(), 1500);
            } catch (error) {
                this.showStatus(`✗ ${error.message}`, "error");
            }
        },
        async deleteBook(event) {
            const card = event.target.closest("[data-slug]");
            const slug = card.dataset.slug;
            const title = card.querySelector(".book-title").textContent;
            if (!confirm(`Delete “${title}”? Your highlights and analyses are kept.`)) return;
            try {
                const response = await fetch(`/delete/${encodeURIComponent(slug)}`,
                    { method: "DELETE" });
                const result = await response.json();
                if (!response.ok) throw new Error(result.detail || "Failed to delete book");
                card.style.opacity = "0";
                card.style.transform = "scale(0.8)";
                setTimeout(() => {
                    card.remove();
                    this.hideEmptyGroups();
                    this.applyFilters();
                }, 250);
                this.showStatus(`✓ ${result.message}`, "success");
            } catch (error) {
                alert(`Error: ${error.message}`);
            }
        },
        async toggleCompleted(event) {
            const card = event.target.closest("[data-slug]");
            const slug = card.dataset.slug;
            const completed = !card.classList.contains("completed");
            try {
                const response = await fetch(
                    `/api/books/${encodeURIComponent(slug)}/completion?completed=${completed}`,
                    { method: "POST" },
                );
                const result = await response.json();
                if (!response.ok) throw new Error(result.detail || "Failed to update");
                window.location.reload();
            } catch (error) {
                alert(`Error: ${error.message}`);
            }
        },
    },
});

window.__LIBRARY__ = app.mount("#library-app");

// Any click outside a dropdown closes every dropdown.
document.addEventListener("click", () => {
    document.querySelectorAll(".dropdown-menu.show")
        .forEach((menu) => menu.classList.remove("show"));
});

// Drop an EPUB anywhere on the page to upload it.
const bookArea = document.getElementById("book-area");
if (bookArea) {
    bookArea.addEventListener("dragover", (event) => {
        event.preventDefault();
        bookArea.classList.add("dragging");
    });
    bookArea.addEventListener("dragleave", () => bookArea.classList.remove("dragging"));
    bookArea.addEventListener("drop", (event) => {
        event.preventDefault();
        bookArea.classList.remove("dragging");
        const file = event.dataTransfer.files[0];
        if (file) window.__LIBRARY__.uploadFile(file);
    });
}