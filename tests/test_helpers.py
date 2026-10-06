"""The shared helpers: the book cache, the slug algorithm, word counts."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import write_counting_epub, write_epub  # noqa: E402

from booksource import Book  # noqa: E402
from routers import (  # noqa: E402
    BookCache,
    estimate_book_word_count,
    estimate_reading_time,
    format_reading_time,
    format_word_count,
    next_free_folder,
    sanitize_folder_name,
)


# -- slug ------------------------------------------------------------------

def test_sanitize_replaces_characters_filenames_cannot_carry():
    assert sanitize_folder_name('What "Is" Truth?') == "What _Is_ Truth_"
    assert sanitize_folder_name("a/b:c") == "a_b_c"


def test_sanitize_preserves_unicode_titles():
    assert sanitize_folder_name("三体") == "三体"


def test_sanitize_trims_dots_and_spaces():
    assert sanitize_folder_name("  . The Title . ") == "The Title"


def test_sanitize_caps_the_length():
    assert len(sanitize_folder_name("x" * 500)) == 100


def test_next_free_folder_takes_the_plain_name_first(tmp_path):
    assert next_free_folder(tmp_path, "Book") == tmp_path / "Book"


def test_next_free_folder_starts_at_two_on_collision(tmp_path):
    (tmp_path / "Book").mkdir()
    assert next_free_folder(tmp_path, "Book") == tmp_path / "Book_2"


def test_next_free_folder_skips_taken_suffixes(tmp_path):
    (tmp_path / "Book").mkdir()
    (tmp_path / "Book_2").mkdir()
    (tmp_path / "Book_3").mkdir()
    assert next_free_folder(tmp_path, "Book") == tmp_path / "Book_4"


# -- word count and reading time -------------------------------------------

@pytest.fixture(scope="module")
def counting_book(tmp_path_factory):
    path = write_counting_epub(tmp_path_factory.mktemp("count") / "counting.epub")
    book = Book.open(path)
    yield book
    book.close()


def test_word_count_counts_latin_words_and_halfweight_cjk(counting_book):
    # 'Hello world 汉字': three \w+ tokens, of which the two CJK characters
    # count as half a word each — 3 + 1.
    assert estimate_book_word_count(counting_book) == 4


def test_reading_time_is_at_least_one_minute():
    assert estimate_reading_time(0) == 1
    assert estimate_reading_time(230) == 1
    assert estimate_reading_time(460) == 2


def test_formatting_helpers():
    assert format_word_count(123456) == "123,456 words"
    assert format_reading_time(45) == "~45 min"
    assert format_reading_time(60) == "~1h"
    assert format_reading_time(135) == "~2h 15m"


# -- the book cache --------------------------------------------------------

@pytest.fixture(scope="module")
def nine_books(tmp_path_factory):
    base = tmp_path_factory.mktemp("cache")
    return [write_epub(base / f"b{i}.epub") for i in range(9)]


def test_cache_reuses_one_open_book_per_slug(nine_books):
    cache = BookCache(maxsize=8)
    try:
        first = cache.get_or_open("b0", nine_books[0])
        assert cache.get_or_open("b0", nine_books[0]) is first
        assert len(cache) == 1
    finally:
        cache.clear()


def test_cache_evicts_the_oldest_and_closes_it(nine_books):
    cache = BookCache(maxsize=8)
    try:
        oldest = cache.get_or_open("b0", nine_books[0])
        assert oldest.chapter_text(0)  # open and parsed
        for i in range(1, 9):
            cache.get_or_open(f"b{i}", nine_books[i])
        assert len(cache) == 8
        assert oldest.chapter_text(0) == ""  # closed on eviction, not errored
        reopened = cache.get_or_open("b0", nine_books[0])
        assert reopened is not oldest
        assert reopened.chapter_text(0)
    finally:
        cache.clear()


def test_cache_drop_closes_and_frees_the_slug(nine_books):
    cache = BookCache(maxsize=8)
    try:
        book = cache.get_or_open("b0", nine_books[0])
        cache.drop("b0")
        assert book.chapter_text(0) == ""
        assert len(cache) == 0
        assert cache.get_or_open("b0", nine_books[0]) is not book
    finally:
        cache.clear()