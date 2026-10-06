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
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
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
                    anchor TEXT,
                    block_id TEXT,
                    is_completed INTEGER NOT NULL DEFAULT 0,
                    last_read_at TEXT NOT NULL
                );
            """)
            # Columns the model gained after an earlier build of this schema:
            # added in place, never recreated.
            self._ensure_columns(conn, "highlights", {
                "chapter_path": "TEXT",
                "block_id": "TEXT",
            })
            self._ensure_columns(conn, "reading_progress", {
                "chapter_path": "TEXT",
                "block_id": "TEXT",
            })
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
                                   publisher, date, word_count, cover_path,
                                   unsupported, added_at)
                VALUES (:slug, :path, :title, :author, :language, :identifier,
                        :publisher, :date, :word_count, :cover_path,
                        :unsupported, :added_at)
                ON CONFLICT(slug) DO UPDATE SET
                    path = excluded.path,
                    title = excluded.title,
                    author = excluded.author,
                    language = excluded.language,
                    identifier = excluded.identifier,
                    publisher = excluded.publisher,
                    date = excluded.date,
                    word_count = excluded.word_count,
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
                      scroll_percent: float = 0.0, anchor: str | None = None,
                      chapter_path: str | None = None) -> None:
        """Save or update the reading position: chapter plus percent within it.

        `is_completed` is deliberately untouched — finishing a book and
        being partway through it are independent facts.
        """
        now = datetime.now().isoformat()
        conn = self._connect()
        try:
            conn.execute("""
                INSERT INTO reading_progress (book_id, chapter_index, chapter_path,
                                              scroll_percent, anchor, is_completed,
                                              last_read_at)
                VALUES (?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    chapter_index = excluded.chapter_index,
                    chapter_path = excluded.chapter_path,
                    scroll_percent = excluded.scroll_percent,
                    anchor = excluded.anchor,
                    last_read_at = excluded.last_read_at
            """, (book_id, chapter_index, chapter_path, scroll_percent,
                  anchor, now))
            conn.commit()
        finally:
            conn.close()