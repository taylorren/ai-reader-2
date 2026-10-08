"""The adapter: opening, metadata, serving, text, footnotes — never raising."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import write_epub, write_sectioned_epub  # noqa: E402

from booksource import Book  # noqa: E402


@pytest.fixture(scope="module")
def book_path(tmp_path_factory):
    return write_epub(tmp_path_factory.mktemp("book") / "fixture.epub")


@pytest.fixture()
def book(book_path):
    opened = Book.open(book_path)
    yield opened
    opened.close()


# -- opening and metadata -------------------------------------------------

def test_open_exposes_metadata(book):
    assert book.title == "Fixture Book"
    assert book.author == "Jane Doe"
    assert book.language == "en"
    assert book.identifier == "urn:uuid:fixture-0001"
    assert book.publisher == "Fixture Press"
    assert book.date == "2020-01-02"
    assert book.unsupported is None


def test_spine_is_the_reading_order(book):
    assert book.spine == ("OEBPS/ch1.xhtml", "OEBPS/ch2.xhtml")
    assert book.chapter_count == 2


def test_toc_json_is_the_books_contents(book):
    tree = book.toc_json()
    assert [(n["label"], n["href"]) for n in tree] == [
        ("Chapter One", "OEBPS/ch1.xhtml"),
        ("Chapter Two", "OEBPS/ch2.xhtml"),
    ]
    assert all(n["children"] == [] for n in tree)


def test_toc_keeps_a_sections_fragment_beside_its_chapter(tmp_path):
    """A section named inside a chapter shares that chapter's href: epubx strips
    the fragment from `href` and hands it over as `anchor`. The reader tells the
    entries apart by that fragment, so the split must survive into toc_json."""
    opened = Book.open(write_sectioned_epub(tmp_path / "sectioned.epub"))
    try:
        tree = opened.toc_json()
    finally:
        opened.close()

    chapter = tree[0]
    assert chapter["label"] == "Sectioned Book"
    assert chapter["href"] == "OEBPS/ch1.xhtml"
    assert chapter["anchor"] is None  # the chapter's own entry names no section
    assert [(n["href"], n["anchor"]) for n in chapter["children"]] == [
        ("OEBPS/ch1.xhtml", "sec-a"),
        ("OEBPS/ch1.xhtml", "sec-b"),
    ]


def test_cover_path_points_into_the_book_itself(book):
    assert book.cover_path == "OEBPS/img/cover.jpg"


# -- the book's own files -------------------------------------------------

def test_resource_serves_the_books_own_bytes(book):
    found = book.resource("OEBPS/style.css")
    assert found is not None
    assert found.media_type == "text/css"
    assert b"margin" in found.read()


def test_resource_accepts_the_url_the_browser_asked_for(book):
    """A leading slash and percent-encoding are normalised, not 404s."""
    found = book.resource("/OEBPS/img/plate%20one.png")
    assert found is not None
    assert found.media_type == "image/png"
    assert found.path == "OEBPS/img/plate one.png"
    assert found.read().startswith(b"\x89PNG")


def test_path_traversal_cannot_escape_the_book(book):
    assert book.resource("../../etc/passwd") is None
    assert book.resource("/../../etc/passwd") is None
    assert book.resource("OEBPS/../../etc/passwd") is None


def test_missing_member_is_none(book):
    assert book.resource("OEBPS/no-such-file.css") is None


# -- text and footnote edges ----------------------------------------------

def test_chapter_text_is_the_extracted_plain_text(book):
    text = book.chapter_text(0)
    assert "The first paragraph" in text
    assert "A plate" in text  # the image's alt text travels with it


def test_footnote_edges_cover_the_three_shapes(book):
    edges = book.footnotes(0)
    assert [e["href"] for e in edges] == [
        "#local-note", "ch2.xhtml#endnote-1", "ch2.xhtml#no-such-note",
    ]
    assert [e["text"] for e in edges] == ["1", "2", "3"]


def test_in_chapter_edge_resolves_locally(book):
    edge = book.footnotes(0)[0]
    assert edge["resolved"] is True
    assert edge["block_id"].startswith("c0000/b")
    assert edge["target_chapter"] == 0
    assert edge["target_href"] == "OEBPS/ch1.xhtml"
    assert edge["target_anchor"] == "local-note"
    assert edge["target_text"] == "The local note."


def test_cross_chapter_edge_resolves_through_the_spine(book):
    edge = book.footnotes(0)[1]
    assert edge["resolved"] is True
    assert edge["target_chapter"] == 1
    assert edge["target_href"] == "OEBPS/ch2.xhtml"
    assert edge["target_anchor"] == "endnote-1"
    assert edge["target_text"] == "The endnote text."


def test_unresolvable_edge_is_named_not_broken(book):
    edge = book.footnotes(0)[2]
    assert edge["resolved"] is False
    assert edge["target_chapter"] is None
    assert edge["target_href"] is None
    assert edge["target_anchor"] is None
    assert edge["target_text"] is None


# -- named failures -------------------------------------------------------

def test_a_file_that_is_not_an_epub_is_named_not_raised(tmp_path):
    bad = tmp_path / "bad.epub"
    bad.write_bytes(b"this is not a zip archive")
    book = Book.open(bad)
    try:
        assert book.unsupported, "the failure is named"
        assert book.title is None
        assert book.spine == ()
        assert book.chapter_count == 0
        assert book.toc_json() == []
        assert book.resource("anything") is None
        assert book.chapter_text(0) == ""
        assert book.footnotes(0) == []
    finally:
        book.close()


def test_a_missing_file_is_named_not_raised(tmp_path):
    book = Book.open(tmp_path / "absent.epub")
    try:
        assert book.unsupported
    finally:
        book.close()


def test_close_releases_the_book(book):
    assert book.chapter_text(0)  # open and parsed
    book.close()
    assert book.chapter_text(0) == ""  # a closed book yields nothing, not errors