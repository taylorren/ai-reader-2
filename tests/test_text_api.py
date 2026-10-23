"""P4: /api/text — the AI's context and the blocks a highlight anchors to."""

from __future__ import annotations


def test_the_text_api_returns_prose_and_its_blocks(isolated_client, isolated,
                                                   upload):
    slug = upload()
    payload = isolated_client.get(f"/api/text/{slug}/0").json()
    assert payload["chapter_path"] == "OEBPS/ch1.xhtml"
    # The chapter is not shipped twice: the blocks carry their own text, and the
    # whole-chapter prose is opt-in (REVIEW P2-9).
    assert "text" not in payload
    assert "word_count" not in payload          # it was a character count
    assert payload["char_count"] > 0

    block_ids = [block["id"] for block in payload["blocks"]]
    assert "c0000/b0003" in block_ids  # the paragraph with the plate
    # Blocks carry their text, so the reader can locate them in the frame.
    paragraph = next(b for b in payload["blocks"] if b["id"] == "c0000/b0003")
    assert paragraph["text"].startswith("The first paragraph mentions a plate")
    # The heading carries the DOM id the book itself declares.
    heading = next(b for b in payload["blocks"] if b["id"] == "c0000/b0002")
    assert heading["dom_ids"] == ["top"]

    # `?text=1` hands over the chapter as one string, for a caller that wants
    # the prose rather than the anchors.
    whole = isolated_client.get(f"/api/text/{slug}/0?text=1").json()
    assert "The first paragraph mentions a plate" in whole["text"]
    assert whole["char_count"] == len(whole["text"])
    assert whole["blocks"] == payload["blocks"]


def test_the_text_api_rejects_unknown_books_and_chapters(isolated_client,
                                                         isolated, upload):
    slug = upload()
    assert isolated_client.get("/api/text/ghost/0").status_code == 404
    assert isolated_client.get(f"/api/text/{slug}/9").status_code == 404


def test_a_text_less_paragraph_does_not_break_the_text_api(isolated_client,
                                                           isolated, upload):
    """A chapter holding a blank `<p>` still answers, and that block is skipped.

    A CJK/InDesign export marks a blank line with `<p>　</p>` (U+3000), and
    epubx reports such a block with `text=None` — the same value an uncaptioned
    figure carries. Calling `.strip()` on it raised, so the endpoint returned a
    500; the reader's selection menu treats a failed block lookup as fatal, so
    a whole book lost its AI menu (a real library: 128 of 301 books carry this
    shape, one of them in 40 of its 42 chapters).
    """
    from booksource import Book
    from routers import BOOKS_DIR, book_cache, get_db

    slug = upload()
    response = isolated_client.get(f"/api/text/{slug}/0")
    assert response.status_code == 200
    payload = response.json()

    # The shape under test must be in the book, or this test proves nothing.
    row = get_db().get_book(slug)
    book = book_cache.get_or_open(slug, BOOKS_DIR / row["path"])
    text_less = [block for block in book.blocks(0) if block["text"] is None]
    assert text_less, "the fixture chapter must carry a text-less block"

    ids = [block["id"] for block in payload["blocks"]]
    # The text-less block cannot be selected in the served document, so it is
    # not an anchor: it is left out rather than crashing the request.
    assert not {block["id"] for block in text_less} & set(ids)
    assert all(block["text"] for block in payload["blocks"])
    # And it does not renumber its neighbours: these are the ids stored
    # highlights and the rest of the suite already depend on.
    assert "c0000/b0002" in ids   # the heading
    assert "c0000/b0003" in ids   # the paragraph with the plate

