"""Slugs, folder names, and the pinyin-aware ordering of the library.

Everything that turns a *title* into something else: the slug a book is stored
and addressed by, the folder name an upload claims, and the sort key and letter
a title is filed under.
"""

from __future__ import annotations

import re
from itertools import groupby
from pathlib import Path


# ---- Slug: ai-reader's algorithm, plus the two URL-hostile characters ----

# Characters a filesystem cannot carry, plus the two a URL cannot carry
# literally in a path segment: `#` opens a fragment, and a raw `%` is an
# invalid escape. A slug is the title verbatim, so a title like `C# in Depth`
# used to be unreachable from its own card — `href="/read/C# in Depth"` asks
# the server for `/read/C`. Slugging them out is the source-level half of the
# fix; every template and redirect also quotes the slug (REVIEW P1-2).
_INVALID_FILENAME_CHARS = '<>:"/\\|?*#%'


def sanitize_folder_name(name: str) -> str:
    """Title → safe folder name, preserving Unicode (Chinese titles included).

    Characters a filesystem cannot carry — and the two a URL cannot carry
    literally, `#` and `%` — become `_`; leading and trailing dots and spaces
    are trimmed; the name is capped at 100 characters. The same title always
    yields the same slug, so a re-uploaded book keeps its identity and
    therefore its annotations.
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


