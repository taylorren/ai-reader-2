/* The library's interactions: theme, search, menus, upload, delete, completion.

The card grid is rendered by the server; these handlers act on it in place,
and reload when the grouping changes (upload, completion). */

const { createApp } = Vue;

const app = createApp({
    data() {
        return {
            // The two library filters, combined: a free-text query and the
            // letter index ("all" shows every group).
            query: "",
            group: "all",
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
    },
    methods: {
        toggleTheme(event) {
            const isDark = document.body.classList.toggle("dark-mode");
            event.currentTarget.textContent = isDark ? "☀️" : "🌙";
            localStorage.setItem("reader-theme", isDark ? "dark" : "light");
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
            // A card shows when it matches the query *and* the chosen letter.
            let visible = 0;
            document.querySelectorAll(".book-card").forEach((card) => {
                const matchesQuery = !this.query ||
                    (card.dataset.search || "").includes(this.query);
                const matchesGroup = this.group === "all" ||
                    card.dataset.group === this.group;
                const show = matchesQuery && matchesGroup;
                card.classList.toggle("hidden", !show);
                if (show) visible += 1;
            });
            const none = document.getElementById("no-results");
            if (none) none.hidden = visible > 0;
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
                setTimeout(() => { card.remove(); this.applyFilters(); }, 250);
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