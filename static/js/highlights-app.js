/* The highlights view's interactions: theme, filtering, and deletion.

The list is rendered by the server; these handlers act on it in place and
drop a row once its highlight or analysis is gone. */

const { createApp } = Vue;

createApp({
    data() {
        return {};
    },
    mounted() {
        if (localStorage.getItem("reader-theme") === "dark") {
            document.body.classList.add("dark-mode");
            const toggle = document.querySelector(".theme-toggle");
            if (toggle) toggle.textContent = "☀️";
        }
    },
    methods: {
        toggleTheme(event) {
            const isDark = document.body.classList.toggle("dark-mode");
            event.currentTarget.textContent = isDark ? "☀️" : "🌙";
            localStorage.setItem("reader-theme", isDark ? "dark" : "light");
        },
        filterItems(kind, event) {
            document.querySelectorAll(".filter-btn")
                .forEach((button) => button.classList.remove("active"));
            event.currentTarget.classList.add("active");
            document.querySelectorAll(".highlight-item").forEach((item) => {
                item.style.display =
                    (kind === "all" || item.dataset.kind === kind) ? "" : "none";
            });
            this.applyVisibility();
        },
        // Whether the grid still has anything to show. A deletion can empty the
        // filter that is in view, which used to leave a blank page with no
        // explanation at all (REVIEW P3-12's sibling case).
        applyVisibility() {
            const any = [...document.querySelectorAll(".highlight-item")]
                .some((item) => item.style.display !== "none");
            const none = document.getElementById("no-results");
            if (none) none.hidden = any;
        },
        // The counts were rendered once by the server, so deleting a row left
        // them claiming items that were gone (REVIEW P3-12). Recounted from what
        // is on screen: the server builds one item per analysis, so one
        // `data-kind` per card is exactly what `_stats()` counted.
        recount() {
            const counts = {};
            let total = 0;
            document.querySelectorAll(".highlight-item").forEach((item) => {
                const kind = item.dataset.kind;
                counts[kind] = (counts[kind] || 0) + 1;
                total += 1;
            });
            document.querySelectorAll(".stat-count").forEach((node) => {
                const kind = node.dataset.kind;
                node.textContent = kind === "total" ? total : (counts[kind] || 0);
            });
            // Nothing left: four zeroes over an empty page is not a summary.
            const bar = document.querySelector(".stats-bar");
            if (bar) bar.hidden = total === 0;
            this.applyVisibility();
        },
        async deleteAnalysis(event) {
            const button = event.currentTarget;
            if (!confirm("删除这条批注？")) return;
            const response = await fetch(`/api/ai/delete/${button.dataset.analysisId}`,
                { method: "DELETE" });
            if (response.ok) {
                button.closest(".highlight-item").remove();
                this.recount();
            } else {
                alert("删除失败，请重试。");
            }
        },
        async deleteHighlight(event) {
            const button = event.currentTarget;
            if (!confirm("删除这条高亮及其所有批注？")) return;
            const response = await fetch(`/api/highlight/${button.dataset.highlightId}`,
                { method: "DELETE" });
            if (response.ok) {
                button.closest(".highlight-item").remove();
                this.recount();
            } else {
                alert("删除失败，请重试。");
            }
        },
    },
}).mount("#highlights-app");
