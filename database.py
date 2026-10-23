"""SQLite storage: books, highlights, AI analyses, reading progress.

The books row is derived metadata — recomputable from the EPUB at any time
(principle 3), stored because it is expensive to compute. Annotations are
keyed by slug as `book_id`, so a re-uploaded book keeps its highlights,
analyses and progress with no migration. Columns added later arrive through
the idempotent ALTER TABLE pattern, so an earlier database keeps working.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any


class Database:
    """The reader's database; one connection per operation."""

    def __init__(self, db_path):
        self.db_path = str(db_path)
        self.init_db()

    def _connect(self) -> sqlite3.Connection:
        """A connection tuned for a reader, not for a batch job.

        `timeout` and WAL are the two that matter. A progress save landing while
        a highlight is being written used to be able to raise `database is
        locked` — and the reader's client swallows that (`.catch(() => {})`), so
        the position silently did not save (REVIEW P2-12). WAL lets a read run
        while a write is in flight, and the timeout waits out the brief overlap
        that remains. `synchronous=NORMAL` is WAL's usual companion: still
        durable against a process crash, which is the failure this app can
        actually have.

        The pragmas are best-effort by design — a filesystem without shared
        memory falls back to the rollback journal rather than failing to open.
        """
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def init_db(self) -> None:
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS books (
                    slug TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    title TEXT,
                    author TEXT,
                    language TEXT,
                    identifier TEXT,
                    publisher TEXT,
                    date TEXT,
                    word_count INTEGER NOT NULL DEFAULT 0,
                    chapter_count INTEGER NOT NULL DEFAULT 0,
                    cover_path TEXT,
                    unsupported TEXT,
                    added_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS highlights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id TEXT NOT NULL,
                    chapter_index INTEGER NOT NULL,
                    chapter_path TEXT,
                    block_id TEXT,
                    selected_text TEXT NOT NULL,
                    context_before TEXT,
                    context_after TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ai_analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    highlight_id INTEGER NOT NULL,
                    analysis_type TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    response TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (highlight_id) REFERENCES highlights (id)
                );

                CREATE TABLE IF NOT EXISTS reading_progress (
                    book_id TEXT PRIMARY KEY,
                    chapter_index INTEGER NOT NULL DEFAULT 0,
                    chapter_path TEXT,
                    scroll_percent REAL DEFAULT 0,
                    block_id TEXT,
                    is_completed INTEGER NOT NULL DEFAULT 0,
                    last_read_at TEXT NOT NULL
                );
            """)
            # Columns the model gained after an earlier build of this schema:
            # added in place, never recreated.
            self._ensure_columns(conn, "books", {
                "chapter_count": "INTEGER NOT NULL DEFAULT 0",
            })
            self._ensure_columns(conn, "highlights", {
                "chapter_path": "TEXT",
                "block_id": "TEXT",
            })
            self._ensure_columns(conn, "reading_progress", {
                "chapter_path": "TEXT",
                "block_id": "TEXT",
                # The client's write order (REVIEW P2-8). An existing row gets 0,
                # which any versioned write outranks.
                "seq": "INTEGER NOT NULL DEFAULT 0",
            })
            # A column the model no longer has: `anchor` was accepted by the API
            # and written to the database, and nothing ever read it — a second,
            # competing anchor scheme (path + fragment) beside the block id,
            # which is the one that is now real (REVIEW P2-10).
            self._drop_columns(conn, "reading_progress", ("anchor",))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection, table: str,
                        columns: dict[str, str]) -> None:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, declaration in columns.items():
            if name not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

    @staticmethod
    def _drop_columns(conn: sqlite3.Connection, table: str,
                      names: tuple[str, ...]) -> None:
        """Remove columns the model no longer has.

        The counterpart of `_ensure_columns`, idempotent the same way: a column
        that is already gone is not an error. `DROP COLUMN` needs SQLite 3.35
        (2021) — older would fail loudly at startup rather than quietly keep a
        column nothing writes.
        """
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name in names:
            if name in present:
                conn.execute(f"ALTER TABLE {table} DROP COLUMN {name}")

    # -- books ---------------------------------------------------------------

    def upsert_book(self, row: dict[str, Any]) -> None:
        """Insert a book row, or refresh it in place on re-upload.

        `added_at` survives an update, so re-uploading a book does not
        reshuffle the library's ordering.
        """
        conn = self._connect()
        try:
            conn.execute("""
                INSERT INTO books (slug, path, title, author, language, identifier,
                                   publisher, date, word_count, chapter_count,
                                   cover_path, unsupported, added_at)
                VALUES (:slug, :path, :title, :author, :language, :identifier,
                        :publisher, :date, :word_count, :chapter_count,
                        :cover_path, :unsupported, :added_at)
                ON CONFLICT(slug) DO UPDATE SET
                    path = excluded.path,
                    title = excluded.title,
                    author = excluded.author,
                    language = excluded.language,
                    identifier = excluded.identifier,
                    publisher = excluded.publisher,
                    date = excluded.date,
                    word_count = excluded.word_count,
                    chapter_count = excluded.chapter_count,
                    cover_path = excluded.cover_path,
                    unsupported = excluded.unsupported
            """, row)
            conn.commit()
        finally:
            conn.close()

    def get_book(self, slug: str) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM books WHERE slug = ?", (slug,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_books(self) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM books").fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def books_with_progress(self) -> list[dict]:
        """Every book, with its progress joined on — one query, one connection.

        A library card needs both, and asking per book opened a connection per
        book: 299 books meant 299 of them on every render (REVIEW P2-2).
        `p_present` distinguishes "no progress row" from "a row of zeroes".
        """
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT b.*,
                       p.book_id IS NOT NULL AS p_present,
                       p.chapter_index AS p_chapter,
                       p.scroll_percent AS p_scroll,
                       p.is_completed AS p_completed
                FROM books b
                LEFT JOIN reading_progress p ON p.book_id = b.slug
            """).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def set_chapter_count(self, slug: str, chapter_count: int) -> None:
        """Record a book's spine length.

        Uploads write it with the row; this exists for a one-time backfill of
        a library whose rows predate the column.
        """
        conn = self._connect()
        try:
            conn.execute("UPDATE books SET chapter_count = ? WHERE slug = ?",
                         (chapter_count, slug))
            conn.commit()
        finally:
            conn.close()

    def delete_book(self, slug: str) -> None:
        """Remove the book's row. Annotations are deliberately kept."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM books WHERE slug = ?", (slug,))
            conn.commit()
        finally:
            conn.close()

    # -- annotations ---------------------------------------------------------

    def save_highlight(self, book_id: str, chapter_index: int, selected_text: str,
                       chapter_path: str | None = None, block_id: str | None = None,
                       context_before: str = "", context_after: str = "") -> int:
        conn = self._connect()
        try:
            cursor = conn.execute("""
                INSERT INTO highlights (book_id, chapter_index, chapter_path,
                                        block_id, selected_text, context_before,
                                        context_after, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (book_id, chapter_index, chapter_path, block_id, selected_text,
                  context_before, context_after, datetime.now().isoformat()))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def highlights_for(self, book_id: str) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM highlights WHERE book_id = ? ORDER BY id", (book_id,)
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def highlights_for_chapter(self, book_id: str, chapter_index: int) -> list[dict]:
        """A chapter's highlights, oldest first — the order they were made."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM highlights WHERE book_id = ? AND chapter_index = ? "
                "ORDER BY id", (book_id, chapter_index)
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_highlight(self, highlight_id: int) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM highlights WHERE id = ?", (highlight_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def delete_highlight(self, highlight_id: int) -> None:
        """Delete a highlight and every analysis attached to it."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM ai_analyses WHERE highlight_id = ?",
                         (highlight_id,))
            conn.execute("DELETE FROM highlights WHERE id = ?", (highlight_id,))
            conn.commit()
        finally:
            conn.close()

    # -- analyses --------------------------------------------------------------

    def save_analysis(self, highlight_id: int, analysis_type: str, prompt: str,
                      response: str) -> int:
        conn = self._connect()
        try:
            cursor = conn.execute("""
                INSERT INTO ai_analyses (highlight_id, analysis_type, prompt,
                                         response, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (highlight_id, analysis_type, prompt, response,
                  datetime.now().isoformat()))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def analyses_for_highlight(self, highlight_id: int) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM ai_analyses WHERE highlight_id = ? ORDER BY id",
                (highlight_id,)
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_analysis(self, analysis_id: int) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM ai_analyses WHERE id = ?", (analysis_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_analysis(self, analysis_id: int, response: str) -> None:
        """Edit an analysis' response in place (an edited note)."""
        conn = self._connect()
        try:
            conn.execute("UPDATE ai_analyses SET response = ? WHERE id = ?",
                         (response, analysis_id))
            conn.commit()
        finally:
            conn.close()

    def delete_analysis(self, analysis_id: int) -> None:
        """Delete one analysis. The highlight stays unless it was the last one."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT highlight_id FROM ai_analyses WHERE id = ?", (analysis_id,)
            ).fetchone()
            if row is None:
                return
            highlight_id = row["highlight_id"]
            conn.execute("DELETE FROM ai_analyses WHERE id = ?", (analysis_id,))
            remaining = conn.execute(
                "SELECT COUNT(*) AS n FROM ai_analyses WHERE highlight_id = ?",
                (highlight_id,)).fetchone()["n"]
            if remaining == 0:
                conn.execute("DELETE FROM highlights WHERE id = ?", (highlight_id,))
            conn.commit()
        finally:
            conn.close()


    # -- progress ------------------------------------------------------------

    def get_progress(self, book_id: str) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM reading_progress WHERE book_id = ?", (book_id,)
            ).fetchone()
            if row is None:
                return None
            progress = dict(row)
            progress["is_completed"] = bool(progress.get("is_completed", 0))
            return progress
        finally:
            conn.close()

    def set_completed(self, book_id: str, completed: bool) -> None:
        """Mark a book completed or not, without disturbing reading position."""
        now = datetime.now().isoformat()
        conn = self._connect()
        try:
            conn.execute("""
                INSERT INTO reading_progress (book_id, chapter_index, is_completed,
                                              last_read_at)
                VALUES (?, 0, ?, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    is_completed = excluded.is_completed,
                    last_read_at = excluded.last_read_at
            """, (book_id, int(completed), now))
            conn.commit()
        finally:
            conn.close()

    def save_progress(self, book_id: str, chapter_index: int,
                      scroll_percent: float = 0.0, block_id: str | None = None,
                      chapter_path: str | None = None, seq: int = 0) -> None:
        """Save or update the reading position: chapter, percent, and block.

        `is_completed` is deliberately untouched — finishing a book and
        being partway through it are independent facts.

        `block_id` is the position's *identity*: the first block on screen when
        the reader stopped. A percent moves when the text reflows — a font-size
        change, a window resize — while a block lands on the same paragraph
        (REVIEW P2-10). The percent stays as the fallback for a row written
        before this existed, and for a block the served document no longer has.

        `seq` orders the writes. Progress saves are fire-and-forget, so the
        request from the chapter a reader just left can arrive *after* the one
        for the chapter they are in, and the stored position then moved
        backwards a chapter (REVIEW P2-8). A write whose `seq` is older than the
        stored one is ignored; `seq = 0` means "no ordering information" and is
        always accepted, so an unversioned client still saves.
        """
        now = datetime.now().isoformat()
        conn = self._connect()
        try:
            conn.execute("""
                INSERT INTO reading_progress (book_id, chapter_index, chapter_path,
                                              scroll_percent, block_id, is_completed,
                                              last_read_at, seq)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    chapter_index = excluded.chapter_index,
                    chapter_path = excluded.chapter_path,
                    scroll_percent = excluded.scroll_percent,
                    block_id = excluded.block_id,
                    last_read_at = excluded.last_read_at,
                    seq = excluded.seq
                WHERE excluded.seq = 0 OR excluded.seq >= reading_progress.seq
            """, (book_id, chapter_index, chapter_path, scroll_percent,
                  block_id, now, seq))
            conn.commit()
        finally:
            conn.close()