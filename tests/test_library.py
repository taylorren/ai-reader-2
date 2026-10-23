"""P1: upload → listed → metadata in one step; delete keeps annotations."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import write_drm_epub, write_epub, write_twin_epub  # noqa: E402


def upload(client, path, name=None):
    return client.post(
        "/upload",
        files={"file": (name or path.name, path.read_bytes(), "application/epub+zip")},
    )


def book_links(page: str) -> list[str]:
    """Every `/read/…` and `/highlights/…` href the page emits, deduplicated.

    The library card, the reader shell and the highlights view all build these
    from the slug, so this is what a URL-hostile title breaks (REVIEW P1-2).
    """
    return sorted(set(re.findall(r'href="(/(?:read|highlights)/[^"]*)"', page)))


def test_upload_lists_metadata_in_one_step(isolated_client, isolated, db):
    response = upload(isolated_client, write_epub(isolated / "fixture.epub"))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["slug"] == "Fixture Book"
    assert body["unsupported"] is None

    folder = isolated / "books" / "Fixture Book"
    assert (folder / "Fixture Book.epub").exists()
    # The book, and nothing else: no pickle, no extracted images.
    assert list(folder.iterdir()) == [folder / "Fixture Book.epub"]

    row = db.get_book("Fixture Book")
    assert row["title"] == "Fixture Book"
    assert row["author"] == "Jane Doe"
    assert row["identifier"] == "urn:uuid:fixture-0001"
    assert row["language"] == "en"
    assert row["word_count"] > 0
    assert row["cover_path"] == "OEBPS/img/cover.jpg"
    assert row["path"] == "Fixture Book/Fixture Book.epub"

    page = isolated_client.get("/")
    assert page.status_code == 200
    assert "Fixture Book" in page.text
    assert "Jane Doe" in page.text
    assert "words" in page.text


def test_reupload_of_the_same_book_keeps_its_identity(isolated_client, isolated, db):
    slug = upload(isolated_client, write_epub(isolated / "a.epub")).json()["slug"]

    highlight_id = db.save_highlight(slug, 0, "quoted sentence",
                                     chapter_path="OEBPS/ch1.xhtml",
                                     block_id="c0000/b0002")

    # The same book again, under a different filename: identity comes from
    # the book, not the upload.
    second = upload(isolated_client, write_epub(isolated / "b.epub"),
                    name="renamed.epub")
    body = second.json()
    assert body["slug"] == slug
    assert body["replaced"] is True

    assert len(db.list_books()) == 1
    kept = db.highlights_for(slug)
    assert kept and kept[0]["id"] == highlight_id

    folders = sorted(p.name for p in (isolated / "books").iterdir())
    assert folders == [slug]


def test_reupload_keeps_the_original_added_at(isolated_client, isolated, db):
    upload(isolated_client, write_epub(isolated / "a.epub"))
    first_added = db.get_book("Fixture Book")["added_at"]
    upload(isolated_client, write_epub(isolated / "b.epub"))
    assert db.get_book("Fixture Book")["added_at"] == first_added


def test_a_different_book_with_the_same_title_gets_its_own_slug(
        isolated_client, isolated, db):
    upload(isolated_client, write_epub(isolated / "a.epub"))
    second = upload(isolated_client, write_twin_epub(isolated / "b.epub"))
    assert second.json()["slug"] == "Fixture Book_2"
    assert second.json()["replaced"] is False

    assert len(db.list_books()) == 2
    assert (isolated / "books" / "Fixture Book_2" / "Fixture Book_2.epub").exists()


def test_delete_removes_folder_and_row_but_keeps_annotations(
        isolated_client, isolated, db):
    slug = upload(isolated_client, write_epub(isolated / "a.epub")).json()["slug"]
    db.save_highlight(slug, 0, "kept sentence")

    response = isolated_client.delete(f"/delete/{slug}")
    assert response.status_code == 200

    assert not (isolated / "books" / slug).exists()
    assert db.get_book(slug) is None
    assert db.highlights_for(slug), "the annotations survive"

    # Re-uploading the same book restores its identity and its annotations.
    again = upload(isolated_client, write_epub(isolated / "b.epub"))
    assert again.json()["slug"] == slug
    assert db.highlights_for(slug)[0]["book_id"] == slug


def test_delete_of_an_unknown_book_is_a_404(isolated_client):
    assert isolated_client.delete("/delete/ghost").status_code == 404


def test_delete_rejects_traversal(isolated_client):
    assert isolated_client.delete("/delete/..%2Fbooks").status_code in (400, 404)


def test_an_unsupported_book_is_stored_with_its_reason(isolated_client, isolated, db):
    response = upload(isolated_client, write_drm_epub(isolated / "locked.epub"))
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "Locked Book"
    assert "drm" in body["unsupported"].lower()

    row = db.get_book("Locked Book")
    assert "drm" in row["unsupported"].lower()
    assert row["word_count"] == 0

    page = isolated_client.get("/")
    assert "无法打开此书" in page.text

    # P3-11: the reason belongs on the card, not only in a `title` hover — a
    # touch device has no hover, and the card cannot reach the reader's own
    # reason page (it hides its 浏览本书 link for an unsupported book).
    assert "unsupported-reason" in page.text
    assert "DRM" in page.text or "drm" in page.text


def test_a_file_that_is_not_an_epub_is_refused_with_a_named_reason(
        isolated_client, isolated, db):
    response = isolated_client.post(
        "/upload",
        files={"file": ("thing.epub", b"this is not a zip archive",
                        "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "not a zip" in response.json()["detail"]
    assert db.list_books() == []
    assert list((isolated / "books").iterdir()) == []


def test_a_non_epub_suffix_is_refused(isolated_client):
    response = isolated_client.post(
        "/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 400
    assert "EPUB" in response.json()["detail"]


def test_completion_toggle_round_trips(isolated_client, isolated, db):
    slug = upload(isolated_client, write_epub(isolated / "a.epub")).json()["slug"]

    response = isolated_client.post(f"/api/books/{slug}/completion?completed=true")
    assert response.status_code == 200
    assert db.get_progress(slug)["is_completed"] is True

    page = isolated_client.get("/")
    assert "Completed" in page.text

    response = isolated_client.post(f"/api/books/{slug}/completion?completed=false")
    assert response.status_code == 200
    assert db.get_progress(slug)["is_completed"] is False


def test_completion_of_an_unknown_book_is_a_404(isolated_client):
    response = isolated_client.post("/api/books/ghost/completion?completed=true")
    assert response.status_code == 404


def test_library_progress_spans_the_book_not_the_current_chapter(
        isolated_client, isolated):
    """`scroll_percent` is within-chapter; the card must show book progress."""
    slug = upload(isolated_client, write_epub(isolated / "a.epub")).json()["slug"]

    # 60% down the first of the fixture's two spine documents is 30% of the
    # book — the bug showed the raw 60.
    isolated_client.post("/api/progress", json={
        "book_id": slug, "chapter_index": 0, "scroll_percent": 60.0})
    assert 'data-progress="30"' in isolated_client.get("/").text

    # 90% down the last chapter is 95% of the book, not 90.
    isolated_client.post("/api/progress", json={
        "book_id": slug, "chapter_index": 1, "scroll_percent": 90.0})
    assert 'data-progress="95"' in isolated_client.get("/").text


# -- URL-hostile titles (REVIEW P1-2 / T2) --------------------------------

def test_the_library_page_costs_one_query_however_many_books(
        isolated_client, isolated, monkeypatch):
    """The card used to ask the database for its own progress, and the database
    opens a connection per call: 299 books meant 299 connections on every render
    (REVIEW P2-2 / T4). The page is one joined query now, so the cost is flat.
    """
    import sqlite3

    for index in range(5):
        upload(isolated_client, write_epub(isolated / f"book{index}.epub",
                                           title=f"Book {index}"))

    opened = []
    real_connect = sqlite3.connect

    def counting_connect(*args, **kwargs):
        opened.append(args[0] if args else None)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", counting_connect)
    page = isolated_client.get("/")
    assert page.status_code == 200
    for index in range(5):
        assert f"Book {index}" in page.text, f"book {index} is on the page"

    # One for the joined rows; the slack is for a backfill, which is a no-op
    # once every row carries its chapter_count.
    assert len(opened) <= 3, (
        f"the library page opened {len(opened)} connections for 5 books")


def test_a_card_shows_whole_book_progress_from_the_joined_row(
        isolated_client, isolated):
    """The join must carry what the per-book lookup used to: a card with no
    progress row is not "0% complete" but "no progress", and a completed one
    says so."""
    slug = upload(isolated_client, write_epub(isolated / "a.epub")).json()["slug"]

    fresh = isolated_client.get("/").text
    assert 'data-progress="0"' in fresh
    assert "progress-summary" not in fresh       # nothing to summarise yet

    isolated_client.post("/api/progress", json={
        "book_id": slug, "chapter_index": 1, "scroll_percent": 90.0})
    resumed = isolated_client.get("/").text
    assert 'data-progress="95"' in resumed       # 90% of the last of two
    assert "progress-summary" in resumed

    isolated_client.post(f"/api/books/{slug}/completion?completed=true")
    assert "Completed" in isolated_client.get("/").text


def test_a_title_a_url_cannot_carry_is_slugged_out(isolated_client, isolated):
    """`#` opens a fragment and a raw `%` is an invalid escape, so neither may
    survive into a slug: `href="/read/C# in Depth"` asks the server for
    `/read/C`, which 404s the book from its own card."""
    response = upload(isolated_client,
                      write_epub(isolated / "hash.epub", title="C# in Depth"))
    assert response.json()["slug"] == "C_ in Depth"
    upload(isolated_client, write_epub(isolated / "pct.epub", title="100% Pure"))

    page = isolated_client.get("/").text
    assert 'href="/read/C_%20in%20Depth"' in page
    assert 'href="/highlights/C_%20in%20Depth"' in page
    assert 'href="/read/100_%20Pure"' in page

    links = book_links(page)
    assert len(links) == 4, links      # two books × (read + highlights)
    for href in links:
        assert "#" not in href, f"unquoted # in {href}"
        assert isolated_client.get(href).status_code == 200


def test_a_slug_stored_before_the_fix_is_still_linked_safely(
        isolated_client, isolated, monkeypatch):
    """The sanitise half cannot repair rows already in the database, so the
    quoting half has to carry them. A library uploaded before P1-2 keeps a
    `C# in Depth` slug — that is this test's starting point — and every link
    the app emits for it must be percent-encoded, including the resume
    redirect's `Location` (an unquoted `#` there sends the browser to
    `/read/C`)."""
    import routers.library
    from routers import sanitize_folder_name

    # Upload through the pre-fix rule, so the row and the folder on disk carry
    # the hostile slug exactly as an existing library's do.
    monkeypatch.setattr(routers.library, "sanitize_folder_name", lambda name: name)
    slug = upload(isolated_client,
                  write_epub(isolated / "legacy.epub", title="C# in Depth")).json()["slug"]
    monkeypatch.setattr(routers.library, "sanitize_folder_name", sanitize_folder_name)
    assert slug == "C# in Depth"

    page = isolated_client.get("/").text
    assert 'href="/read/C%23%20in%20Depth"' in page
    assert 'href="/highlights/C%23%20in%20Depth"' in page

    for href in book_links(page):
        response = isolated_client.get(href, follow_redirects=False)
        assert response.status_code in (200, 307), f"{href} -> {response.status_code}"
        if response.status_code == 307:
            assert response.headers["location"] == "/read/C%23%20in%20Depth/0"
        # The journey the reader actually makes: card link → reader shell.
        assert isolated_client.get(href).status_code == 200

    # The reader shell's own link out, and the highlights view's link back.
    shell = isolated_client.get("/read/C%23%20in%20Depth/0").text
    assert 'href="/highlights/C%23%20in%20Depth"' in shell
    view = isolated_client.get("/highlights/C%23%20in%20Depth").text
    assert 'href="/read/C%23%20in%20Depth"' in view