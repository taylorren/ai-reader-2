"""Corpus tests: the adapter against real books.

The reference corpus lives at `EPUBX_CORPUS`. These tests skip cleanly when
it is absent, so CI runs with no books present (SPEC.md, Testing).
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

CORPUS = os.environ.get("EPUBX_CORPUS")

pytestmark = pytest.mark.skipif(
    not CORPUS or not Path(CORPUS).is_dir(),
    reason="set EPUBX_CORPUS to a directory of EPUB files to run corpus tests",
)


def corpus_books():
    return sorted(Path(CORPUS).rglob("*.epub"))


def serve_tool():
    """epubx's MVP reader, loaded from its repo.

    A path-installed epubx is copied into site-packages without its tools/
    directory, so the file is looked up beside the installed package first
    and then in the sibling checkout.
    """
    import epubx

    candidates = [
        Path(epubx.__file__).resolve().parent.parent / "tools" / "serve.py",
        Path(__file__).resolve().parents[2] / "epubx" / "tools" / "serve.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            break
    else:
        pytest.skip("epubx's tools/serve.py is not available")
    spec = importlib.util.spec_from_file_location("epubx_serve", candidate)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_corpus_is_discovered():
    assert corpus_books(), "EPUBX_CORPUS is set but contains no .epub files"


def test_every_book_opens_or_names_its_reason():
    """Success criterion 7: open, or a named reason — never an uncaught error."""
    from booksource import Book

    failures = []
    for path in corpus_books():
        book = Book.open(path)
        try:
            if book.unsupported:
                continue  # named, not an error
            assert book.spine is not None
            for index in range(book.chapter_count):
                book.chapter_text(index)
                book.footnotes(index)
        except Exception as exc:  # the test collects failures, it does not raise
            failures.append(f"{path.name}: {exc!r}")
        finally:
            book.close()
    assert not failures, f"{len(failures)} books failed: " + "; ".join(failures[:10])


def test_footnote_edges_match_the_mvp():
    """P0 acceptance: the adapter's edges are the MVP's edges."""
    from booksource import Book

    serve = serve_tool()
    mismatches = []
    compared = 0
    for path in corpus_books():
        book = Book.open(path)
        try:
            if book.unsupported:
                continue
            for index in range(book.chapter_count):
                theirs = serve.footnotes(book._book, index)
                ours = book.footnotes(index)
                compared += 1
                want = [(e["text"], e["href"], e["resolved"], e["target_chapter"])
                        for e in theirs]
                got = [(e["text"], e["href"], e["resolved"], e["target_chapter"])
                       for e in ours]
                if want != got:
                    mismatches.append(f"{path.name} chapter {index}")
        finally:
            book.close()
    assert not mismatches, (
        f"{len(mismatches)} chapters differ: " + ", ".join(mismatches[:10])
    )
    assert compared, "no chapters were compared"