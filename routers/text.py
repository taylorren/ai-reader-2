"""Word counts and reading times — what a book's text adds up to.

Pure functions over a book or a number: no state, no I/O of their own.
"""

from __future__ import annotations

import re

from booksource import Book


# The CJK blocks, in one place: the word count needs them twice — once to count
# characters, once to *exclude* them from the word pattern.
CJK_RANGES = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"

# A word: word characters that are not CJK. The old `\b\w+\b` matched a run of
# Chinese as a single "word" as well as counting its characters, so every
# paragraph was counted twice — once per run, once per character at half weight
# (REVIEW P2-4). Excluding CJK rather than whitelisting A-Z keeps accented Latin
# (`café`) and numerals (`2024`) counting, exactly as they did before.
LATIN_WORD_RE = re.compile(rf"[^\W{CJK_RANGES}]+", re.UNICODE)
CJK_CHAR_RE = re.compile(rf"[{CJK_RANGES}]")

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


