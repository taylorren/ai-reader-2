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
            const any = [...document.querySelectorAll(".highlight-item")]
                .some((item) => item.style.display !== "none");
            const none = document.getElementById("no-results");
            if (none) none.hidden = any;
        },
        async deleteAnalysis(event) {
            const button = event.currentTarget;
            if (!confirm("删除这条批注？")) return;
            const response = await fetch(`/api/ai/delete/${button.dataset.analysisId}`,
                { method: "DELETE" });
            if (response.ok) {
                button.closest(".highlight-item").remove();
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
            } else {
                alert("删除失败，请重试。");
            }
        },
    },
}).mount("#highlights-app");
