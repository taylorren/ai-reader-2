"""P4: /api/settings — the in-memory AI provider override."""

from __future__ import annotations


def test_settings_report_the_default_provider(isolated_client):
    payload = isolated_client.get("/api/settings").json()
    assert payload["provider_override"] is None
    assert payload["default_provider"] in ("ollama", "ollama_cloud")
    assert payload["status"] == "success"


def test_the_override_is_set_and_cleared(isolated_client):
    set_response = isolated_client.post("/api/settings",
                                        json={"provider_override": "Ollama"})
    assert set_response.status_code == 200
    assert set_response.json()["provider_override"] == "ollama"
    assert isolated_client.get("/api/settings").json()["provider_override"] == "ollama"

    cleared = isolated_client.post("/api/settings", json={"provider_override": None})
    assert cleared.status_code == 200
    assert cleared.json()["provider_override"] is None


def test_an_unknown_provider_is_refused(isolated_client):
    response = isolated_client.post("/api/settings",
                                    json={"provider_override": "openai"})
    assert response.status_code == 400


# -- progress ordering (REVIEW P2-8) ---------------------------------------

def test_an_older_progress_write_cannot_move_the_reader_backwards(
        isolated_client, isolated, db):
    """Progress saves are fire-and-forget, so the write for the chapter a reader
    just left can arrive after the one for the chapter they are in — and the
    stored position then moved backwards a chapter."""
    from fixtures import write_epub

    response = isolated_client.post(
        "/upload", files={"file": ("fixture.epub",
                                   write_epub(isolated / "fixture.epub").read_bytes(),
                                   "application/epub+zip")})
    slug = response.json()["slug"]

    def save(chapter, percent, seq=None):
        body = {"book_id": slug, "chapter_index": chapter, "scroll_percent": percent}
        if seq is not None:
            body["seq"] = seq
        assert isolated_client.post("/api/progress", json=body).status_code == 200

    save(1, 90.0, seq=200)                      # the reader is in chapter two
    save(0, 40.0, seq=100)                      # a straggler from chapter one
    stored = db.get_progress(slug)
    assert stored["chapter_index"] == 1, "the newer write stands"
    assert stored["scroll_percent"] == 90.0

    # A newer write still lands, and an unversioned one (an older client, or a
    # request without the field) is accepted rather than silently dropped.
    save(1, 20.0, seq=300)
    assert db.get_progress(slug)["scroll_percent"] == 20.0
    save(0, 10.0)
    assert db.get_progress(slug)["chapter_index"] == 0

    # A row written before the column existed carries 0, so any versioned write
    # outranks it — an upgraded server does not freeze a reader's progress.
    db.save_progress(slug, 1, scroll_percent=5.0)          # seq defaults to 0
    save(1, 70.0, seq=1)
    assert db.get_progress(slug)["scroll_percent"] == 70.0
