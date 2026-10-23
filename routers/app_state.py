"""The process's shared state: paths, the book cache, the database, the AI.

One module owns what every router needs to *reach* — the two directories, the
open books, the SQLite singleton and the AI service — so a router can say
`from .app_state import get_db` at the top of the file and a reader can see the
dependency. They used to live in `routers/__init__.py`, which meant every router
imported them function-locally to dodge a circular import through the package
itself: the direction of the dependency was invisible (REVIEW P3-14).
"""

from __future__ import annotations

import contextlib
import os
import threading
from collections import OrderedDict
from pathlib import Path

from booksource import Book

BASE_DIR = Path(__file__).resolve().parent.parent
BOOKS_DIR = BASE_DIR / "books"


class BookCache:
    """Open books, keyed by slug, with a bound on how many stay open.

    An open book holds a file handle, so books are never cached with
    `lru_cache` — handles are not immutable, and eviction must close(). The
    first parse of a chapter is CPU-bound lxml work, so keeping a few books
    open keeps page turns cheap.

    The bound is enforced over the whole cache, but an in-use entry is never the
    one evicted: a cache whose entries are all in use stays over the cap until
    one is released. Eviction used to close whatever was least recently used,
    and every accessor on a closed book answers `""`/`[]`/`None` rather than
    failing — so a request could have the book it was reading closed under it
    and render a blank chapter instead of raising (REVIEW P2-5). `borrow()` is
    how a request says it is using one; `get_or_open()` stays for a caller that
    only peeks.
    """

    def __init__(self, maxsize: int = 8):
        self._maxsize = maxsize
        self._entries: OrderedDict[str, Book] = OrderedDict()
        self._in_use: dict[str, int] = {}
        self._pending_close: set[str] = set()
        self._lock = threading.Lock()

    def get_or_open(self, slug: str, path: str | os.PathLike) -> Book:
        """The open book for `slug`, opened from `path` on first use.

        Not a claim on it: eviction may close it as soon as another book is
        opened. A request that goes on to read should `borrow()` instead.
        """
        return self._acquire(slug, path, claim=False)

    @contextlib.contextmanager
    def borrow(self, slug: str, path: str | os.PathLike):
        """The open book for `slug`, held for the length of the block.

        Held means eviction leaves it alone, and a `drop()` — a delete, or a
        re-upload of the same slug — closes it when the reader lets go rather
        than in the middle of a chapter.
        """
        book = self._acquire(slug, path, claim=True)
        try:
            yield book
        finally:
            with self._lock:
                self._in_use[slug] -= 1
                if not self._in_use[slug]:
                    del self._in_use[slug]
                    if slug in self._pending_close:
                        self._pending_close.discard(slug)
                        self._close(slug)
                    else:
                        self._evict_idle()

    def drop(self, slug: str) -> None:
        """Forget a book — delete or re-upload closes its handle.

        A book someone is reading is closed when they let go (see `borrow`).
        """
        with self._lock:
            if slug in self._in_use:
                self._pending_close.add(slug)
                return
            self._close(slug)

    def clear(self) -> None:
        with self._lock:
            open_books = list(self._entries.values())
            self._entries.clear()
            self._in_use.clear()
            self._pending_close.clear()
        for book in open_books:
            book.close()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    # -- internals -----------------------------------------------------------

    def _acquire(self, slug: str, path, claim: bool) -> Book:
        """The open book, opened if needed — and, for `borrow`, marked in use.

        Claiming happens under the same lock as the lookup, so a `drop()` cannot
        slip in between the two and close the book just handed over. The parse
        itself stays outside the lock: it is the slow part, and a concurrent
        open that wins the race is closed rather than duplicated.
        """
        with self._lock:
            cached = self._entries.get(slug)
            if cached is not None:
                self._entries.move_to_end(slug)
                if claim:
                    self._in_use[slug] = self._in_use.get(slug, 0) + 1
                return cached
        book = Book.open(path)
        with self._lock:
            existing = self._entries.get(slug)
            if existing is not None:  # a concurrent open won the race
                book.close()
                self._entries.move_to_end(slug)
                if claim:
                    self._in_use[slug] = self._in_use.get(slug, 0) + 1
                return existing
            self._entries[slug] = book
            if claim:
                self._in_use[slug] = self._in_use.get(slug, 0) + 1
            self._evict_idle()
            return book

    def _close(self, slug: str) -> None:
        """Close and forget one book. Caller holds the lock."""
        book = self._entries.pop(slug, None)
        if book is not None:
            book.close()

    def _evict_idle(self) -> None:
        """Close least-recently-used idle books until the cap holds.

        Caller holds the lock. In-use books are skipped rather than counted: a
        chapter turn must not close the book another request is reading. Every
        entry in use means the cache stays over the cap until one is released —
        the cap is a memory heuristic, not a promise.
        """
        for slug in list(self._entries):
            if len(self._entries) <= self._maxsize:
                return
            if slug in self._in_use:
                continue
            self._close(slug)


book_cache = BookCache()




DB_PATH = Path(os.getenv("READER_DB", str(BASE_DIR / "reader_data.db")))
_db = None


_db_lock = threading.Lock()


def get_db():
    """The shared Database singleton, created on first use.

    Under a lock, double-checked: two concurrent first requests could otherwise
    both construct it and both run `init_db()`, and on a database from an older
    build the two `ALTER TABLE` statements in `_ensure_columns` then race to
    `duplicate column name`. The common path still reads a plain global, so the
    lock costs a request nothing (REVIEW P2-6).
    """
    global _db
    if _db is None:
        with _db_lock:
            if _db is None:
                from database import Database

                _db = Database(DB_PATH)
    return _db




# Runtime settings, mirroring ai-reader: a provider override chosen from the
# settings panel, kept in memory (a restart returns to the .env default).
runtime_settings = {"provider_override": None}
_ai_service = None


def get_ai_service():
    """The shared AIService singleton, created on first use."""
    global _ai_service
    if _ai_service is None:
        from ai_service import AIService

        _ai_service = AIService()
    return _ai_service


