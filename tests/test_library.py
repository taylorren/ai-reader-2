"""P1: upload → listed → metadata in one step; delete keeps annotations."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import write_drm_epub, write_epub, write_twin_epub  # noqa: E402


def upload(client, path, name=None):
    return client.post(
        "/upload",
        files={"file": (name or path.name, path.read_bytes(), "application/epub+zip")},
    )


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