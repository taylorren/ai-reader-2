"""Shared dependencies for all routers.

The book cache, the slug algorithm and the word-count/reading-time helpers
live here. `booksource` is the only module that knows the EPUB library
exists; everything in this file speaks its plain-Python surface.
"""

from __future__ import annotations

import os
import re
import threading
from collections import OrderedDict
from itertools import groupby
from pathlib import Path

from booksource import Book

BASE_DIR = Path(__file__).resolve().parent.parent
BOOKS_DIR = BASE_DIR / "books"


# ---- The book cache ----

class BookCache:
    """At most 8 open books; the least recently used is closed on eviction.

    An open book holds a file handle, so books are never cached with
    `lru_cache` — handles are not immutable, and eviction must close(). The
    first parse of a chapter is CPU-bound lxml work, so keeping a few books
    open keeps page turns cheap.
    """

    def __init__(self, maxsize: int = 8):
        self._maxsize = maxsize
        self._entries: OrderedDict[str, Book] = OrderedDict()
        self._lock = threading.Lock()

    def get_or_open(self, slug: str, path: str | os.PathLike) -> Book:
        """The open book for `slug`, opened from `path` on first use."""
        with self._lock:
            cached = self._entries.get(slug)
            if cached is not None:
                self._entries.move_to_end(slug)
                return cached
        book = Book.open(path)
        with self._lock:
            existing = self._entries.get(slug)
            if existing is not None:  # a concurrent open won the race
                book.close()
                self._entries.move_to_end(slug)
                return existing
            self._entries[slug] = book
            while len(self._entries) > self._maxsize:
                _, evicted = self._entries.popitem(last=False)
                evicted.close()
        return book

    def drop(self, slug: str) -> None:
        """Forget a book — delete or re-upload closes its handle."""
        with self._lock:
            book = self._entries.pop(slug, None)
        if book is not None:
            book.close()

    def clear(self) -> None:
        with self._lock:
            open_books = list(self._entries.values())
            self._entries.clear()
        for book in open_books:
            book.close()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


book_cache = BookCache()


# ---- The database ----

DB_PATH = Path(os.getenv("READER_DB", str(BASE_DIR / "reader_data.db")))
_db = None


def get_db():
    """The shared Database singleton, created on first use."""
    global _db
    if _db is None:
        from database import Database

        _db = Database(DB_PATH)
    return _db


# ---- Slug: ai-reader's algorithm, unchanged ----

_INVALID_FILENAME_CHARS = '<>:"/\\|?*'


def sanitize_folder_name(name: str) -> str:
    """Title → safe folder name, preserving Unicode (Chinese titles included).

    Characters a filesystem cannot carry become `_`; leading and trailing
    dots and spaces are trimmed; the name is capped at 100 characters. The
    same title always yields the same slug, so a re-uploaded book keeps its
    identity and therefore its annotations.
    """
    for char in _INVALID_FILENAME_CHARS:
        name = name.replace(char, "_")
    name = name.strip(". ")
    if len(name) > 100:
        name = name[:100]
    return name


def next_free_folder(directory: Path, name: str, taken=()) -> Path:
    """`name`, or `name_2`, `name_3`, … — the first folder name not yet taken.

    `taken` reserves names that exist some other way — a database row, say.
    """
    candidate = directory / name
    counter = 1
    while candidate.exists() or candidate.name in taken:
        counter += 1
        candidate = directory / f"{name}_{counter}"
    return candidate


# ---- Word count and reading time ----

LATIN_WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)
CJK_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

WORDS_PER_MINUTE = 230  # mixed Chinese/English reading, per ai-reader


def estimate_book_word_count(book: Book) -> int:
    """Estimate a book's word count from its extracted text.

    Latin-script words count once; CJK characters count as half a word each.
    Parses every chapter — CPU-bound, so call it from a threadpool.
    """
    total_latin_words = 0
    total_cjk_chars = 0
    for index in range(book.chapter_count):
        text = book.chapter_text(index)
        total_latin_words += len(LATIN_WORD_RE.findall(text))
        total_cjk_chars += len(CJK_CHAR_RE.findall(text))
    return total_latin_words + round(total_cjk_chars / 2)


def format_word_count(word_count: int) -> str:
    """A raw count as a human-readable string like '123,456 words'."""
    return f"{word_count:,} words"


def estimate_reading_time(word_count: int, wpm: int = WORDS_PER_MINUTE) -> int:
    """Reading time in whole minutes, at 230 words per minute."""
    return max(1, round(word_count / wpm))


def format_reading_time(minutes: int) -> str:
    """Minutes as a human-readable string like '~3h 15m' or '~45 min'."""
    if minutes >= 60:
        h = minutes // 60
        m = minutes % 60
        return f"~{h}h {m}m" if m else f"~{h}h"
    return f"~{minutes} min"


# ---- Title sorting and grouping (pinyin-aware) ----

LEADING_SYMBOL_RE = re.compile(r"^[^0-9A-Za-z\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
LEADING_ARTICLE_RE = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)

try:
    from pypinyin import lazy_pinyin
except ImportError:  # sorting degrades to casefolded titles
    lazy_pinyin = None


def normalize_title_for_sort(title: str) -> str:
    """Strip leading symbols and articles (The/A/An) for sorting."""
    cleaned = LEADING_ARTICLE_RE.sub("", LEADING_SYMBOL_RE.sub("", (title or "").strip()))
    return cleaned or (title or "").strip() or "#"


def transliterate_for_sort(text: str) -> str:
    """Chinese titles sort by pinyin; everything else casefolds."""
    normalized = normalize_title_for_sort(text)
    if lazy_pinyin:
        transliterated = "".join(lazy_pinyin(normalized))
        if transliterated:
            return transliterated.casefold()
    return normalized.casefold()


def title_group_key(title: str) -> str:
    """The first letter of the sort key, or '#' for anything else."""
    key = transliterate_for_sort(title)
    if key:
        first = key[0].upper()
        if first.isalpha():
            return first
    return "#"


def build_grouped_books(books: list[dict]) -> list[dict]:
    """Group books into alphabetical sections (A–Z, #) for the library."""
    ordered = sorted(
        books,
        key=lambda book: (book["title_group"] == "#", book["title_group"],
                          book["title_sort_key"], book["title"].casefold()),
    )
    return [
        {"key": key, "label": key, "books": list(items)}
        for key, items in groupby(ordered, key=lambda book: book["title_group"])
    ]


# ---- Asset versioning ----

def get_asset_version(*relative_paths: str) -> int:
    """A stable cache-busting token from the assets' modification times."""
    mtimes = []
    for relative_path in relative_paths:
        asset_path = BASE_DIR / relative_path
        if asset_path.exists():
            mtimes.append(asset_path.stat().st_mtime_ns)
    return max(mtimes, default=0)
