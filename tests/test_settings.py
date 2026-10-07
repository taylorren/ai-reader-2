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
