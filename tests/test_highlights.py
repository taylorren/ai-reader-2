"""P4: highlights — CRUD, the chapter API, the view and the export."""

from __future__ import annotations


def make_highlight(client, slug, **overrides):
    """Create a highlight and return its id."""
    payload = {
        "book_id": slug,
        "chapter_index": 0,
        "selected_text": "The first paragraph mentions a plate",
        "block_id": "c0000/b0003",
        "context_before": "",
        "context_after": " and then keeps going",
    }
    payload.update(overrides)
    response = client.post("/api/highlight", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["highlight_id"]


def test_a_highlight_is_created_and_stored(isolated_client, isolated, upload, db):
    slug = upload()
    highlight_id = make_highlight(isolated_client, slug)
    stored = db.get_highlight(highlight_id)
    assert stored["book_id"] == slug
    assert stored["chapter_index"] == 0
    assert stored["block_id"] == "c0000/b0003"
    # The chapter path is filled in from the spine when the client omits it.
    assert stored["chapter_path"] == "OEBPS/ch1.xhtml"
    assert stored["selected_text"] == "The first paragraph mentions a plate"


def test_a_highlight_needs_a_stored_book_and_a_real_chapter(
        isolated_client, isolated, upload):
    slug = upload()
    unknown = isolated_client.post("/api/highlight", json={
        "book_id": "ghost", "chapter_index": 0, "selected_text": "x"})
    assert unknown.status_code == 404
    bad_chapter = isolated_client.post("/api/highlight", json={
        "book_id": slug, "chapter_index": 9, "selected_text": "x"})
    assert bad_chapter.status_code == 400
    empty = isolated_client.post("/api/highlight", json={
        "book_id": slug, "chapter_index": 0, "selected_text": "   "})
    assert empty.status_code == 400


def test_the_chapter_api_lists_highlights_with_their_analyses(
        isolated_client, isolated, upload):
    slug = upload()
    highlight_id = make_highlight(isolated_client, slug)
    # A highlight with no analyses is still a highlight.
    payload = isolated_client.get(f"/api/highlights/{slug}/0").json()
    assert payload["highlights"][0]["id"] == highlight_id
    assert payload["highlights"][0]["kind"] == "highlight"
    assert payload["highlights"][0]["analyses"] == []

    isolated_client.post("/api/ai/save", json={
        "highlight_id": highlight_id, "analysis_type": "fact_check",
        "prompt": "p", "response": "an explanation"})
    payload = isolated_client.get(f"/api/highlights/{slug}/0").json()
    assert payload["highlights"][0]["kind"] == "fact_check"
    assert payload["highlights"][0]["analyses"][0]["response"] == "an explanation"

    # Another chapter has none, and a bad chapter is refused.
    assert isolated_client.get(f"/api/highlights/{slug}/1").json()["highlights"] == []
    assert isolated_client.get(f"/api/highlights/{slug}/9").status_code == 400


def test_a_highlight_and_its_analyses_are_deleted(isolated_client, isolated,
                                                  upload, db):
    slug = upload()
    highlight_id = make_highlight(isolated_client, slug)
    isolated_client.post("/api/ai/save", json={
        "highlight_id": highlight_id, "analysis_type": "comment",
        "prompt": "", "response": "my note"})
    assert isolated_client.delete(f"/api/highlight/{highlight_id}").status_code == 200
    assert db.get_highlight(highlight_id) is None
    assert db.analyses_for_highlight(highlight_id) == []
    assert isolated_client.delete("/api/highlight/999").status_code == 404


def test_the_highlights_view_renders_and_sanitises(isolated_client, isolated, upload):
    slug = upload()
    highlight_id = make_highlight(isolated_client, slug)
    isolated_client.post("/api/ai/save", json={
        "highlight_id": highlight_id, "analysis_type": "fact_check",
        "prompt": "p",
        "response": "<script>alert(1)</script>**bold** finding"})

    page = isolated_client.get(f"/highlights/{slug}")
    assert page.status_code == 200
    body = page.text
    assert "The first paragraph mentions a plate" in body
    assert "<strong>bold</strong>" in body          # markdown rendered
    assert "<script>alert(1)</script>" not in body  # but sanitised
    assert "解释说明" in body

    assert isolated_client.get("/highlights/ghost").status_code == 404


def test_the_highlights_view_deep_links_to_each_highlight(isolated_client,
                                                          isolated, upload):
    """Each 在书中定位 link names the highlight, so the shell can scroll to it."""
    from urllib.parse import quote

    slug = upload()
    highlight_id = make_highlight(isolated_client, slug)
    body = isolated_client.get(f"/highlights/{slug}").text
    # The slug is percent-encoded in the href (it may be CJK or carry spaces)…
    assert quote(slug, safe="") in body
    # …and the chapter link carries the highlight id.
    assert f"/{quote(slug, safe='')}/0?highlight={highlight_id}" in body


def test_the_highlights_export_is_markdown(isolated_client, isolated, upload):
    slug = upload()
    highlight_id = make_highlight(isolated_client, slug)
    isolated_client.post("/api/ai/save", json={
        "highlight_id": highlight_id, "analysis_type": "comment",
        "prompt": "", "response": "A note about the plate."})

    response = isolated_client.get(f"/highlights/{slug}/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "attachment" in response.headers["content-disposition"]
    body = response.text
    assert "> The first paragraph mentions a plate" in body
    assert "A note about the plate." in body
    assert isolated_client.get("/highlights/ghost/export").status_code == 404
