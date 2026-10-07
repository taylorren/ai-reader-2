"""P4: /api/text — the AI's context and the blocks a highlight anchors to."""

from __future__ import annotations


def test_the_text_api_returns_prose_and_its_blocks(isolated_client, isolated,
                                                   upload):
    slug = upload()
    payload = isolated_client.get(f"/api/text/{slug}/0").json()
    assert payload["chapter_path"] == "OEBPS/ch1.xhtml"
    assert "The first paragraph mentions a plate" in payload["text"]
    assert payload["word_count"] == len(payload["text"])

    block_ids = [block["id"] for block in payload["blocks"]]
    assert "c0000/b0003" in block_ids  # the paragraph with the plate
    # Blocks carry their text, so the reader can locate them in the frame.
    paragraph = next(b for b in payload["blocks"] if b["id"] == "c0000/b0003")
    assert paragraph["text"].startswith("The first paragraph mentions a plate")
    # The heading carries the DOM id the book itself declares.
    heading = next(b for b in payload["blocks"] if b["id"] == "c0000/b0002")
    assert heading["dom_ids"] == ["top"]


def test_the_text_api_rejects_unknown_books_and_chapters(isolated_client,
                                                         isolated, upload):
    slug = upload()
    assert isolated_client.get("/api/text/ghost/0").status_code == 404
    assert isolated_client.get(f"/api/text/{slug}/9").status_code == 404
