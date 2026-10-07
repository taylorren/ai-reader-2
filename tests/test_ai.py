"""P4: AI routes — provider validation, failure mapping, discussion, storage."""

from __future__ import annotations


def make_highlight(client, slug):
    response = client.post("/api/highlight", json={
        "book_id": slug, "chapter_index": 0,
        "selected_text": "The first paragraph mentions a plate",
        "block_id": "c0000/b0003"})
    assert response.status_code == 200, response.text
    return response.json()["highlight_id"]


def service():
    import routers

    return routers.get_ai_service()


def test_analyze_rejects_an_unknown_provider(isolated_client):
    response = isolated_client.post("/api/ai/analyze", json={
        "analysis_type": "fact_check", "selected_text": "some text",
        "provider": "openai"})
    assert response.status_code == 400


def test_analyze_rejects_an_unknown_analysis_type(isolated_client):
    response = isolated_client.post("/api/ai/analyze", json={
        "analysis_type": "summarize_everything", "selected_text": "some text",
        "provider": "ollama"})
    assert response.status_code == 400


def test_analyze_maps_ai_failures_to_502(isolated_client, monkeypatch):
    """An AI failure is an HTTP error, never a 200 carrying error text."""
    monkeypatch.setattr(service(), "base_url", "http://127.0.0.1:1")
    response = isolated_client.post("/api/ai/analyze", json={
        "analysis_type": "fact_check", "selected_text": "some text",
        "provider": "ollama"})
    assert response.status_code == 502


def test_analyze_returns_the_response(isolated_client, monkeypatch):
    async def fake_fact_check(text, context="", provider="ollama"):
        return f"explained: {text}"

    monkeypatch.setattr(service(), "fact_check", fake_fact_check)
    response = isolated_client.post("/api/ai/analyze", json={
        "analysis_type": "fact_check", "selected_text": "a plate",
        "provider": "ollama"})
    assert response.status_code == 200
    body = response.json()
    assert body["response"] == "explained: a plate"
    assert body["provider_used"] == "ollama"


def test_the_provider_override_wins(isolated_client, monkeypatch):
    import routers

    async def fake_fact_check(text, context="", provider="ollama"):
        return provider

    monkeypatch.setattr(service(), "fact_check", fake_fact_check)
    routers._runtime_settings["provider_override"] = "ollama_cloud"
    response = isolated_client.post("/api/ai/analyze", json={
        "analysis_type": "fact_check", "selected_text": "x",
        "provider": "ollama"})
    assert response.json()["provider_used"] == "ollama_cloud"


def test_start_discussion_seeds_the_history(isolated_client, monkeypatch):
    async def fake_overview(text, provider="ollama"):
        return "an overview"

    monkeypatch.setattr(service(), "discussion_overview", fake_overview)
    response = isolated_client.post("/api/ai/discussion/start", json={
        "selected_text": "sample text for discussion", "provider": "ollama"})
    assert response.status_code == 200
    history = response.json()["conversation_history"]
    assert [message["role"] for message in history] == ["user", "assistant"]
    assert history[0]["content"] == "sample text for discussion"
    assert history[1]["content"] == "an overview"


def test_continue_discussion_does_not_duplicate_the_user_message(
        isolated_client, monkeypatch):
    received = []

    async def fake_continue(user_message, conversation_history, provider="ollama"):
        received.extend(conversation_history)
        return "a reply"

    monkeypatch.setattr(service(), "continue_discussion", fake_continue)
    history = [
        {"role": "user", "content": "initial text"},
        {"role": "assistant", "content": "overview"},
        {"role": "user", "content": "my question"},
    ]
    response = isolated_client.post("/api/ai/discussion/continue", json={
        "selected_text": "sample text", "conversation_history": history,
        "user_message": "my question", "provider": "ollama"})
    assert response.status_code == 200
    body = response.json()
    user_messages = [m for m in body["conversation_history"]
                     if m["content"] == "my question"]
    assert len(user_messages) == 1
    assert len([m for m in received if m["content"] == "my question"]) == 1
    assert body["conversation_history"][-1]["content"] == "a reply"


def test_summarize_discussion_returns_the_summary(isolated_client, monkeypatch):
    async def fake_summarize(text, conversation_history, provider="ollama"):
        return "the whole discussion, summarised"

    monkeypatch.setattr(service(), "summarize_conversation", fake_summarize)
    response = isolated_client.post("/api/ai/discussion/summarize", json={
        "selected_text": "sample text",
        "conversation_history": [{"role": "user", "content": "q"}],
        "provider": "ollama"})
    assert response.status_code == 200
    assert response.json()["summary"] == "the whole discussion, summarised"


def test_discussion_endpoints_map_failures_to_502(isolated_client, monkeypatch):
    monkeypatch.setattr(service(), "base_url", "http://127.0.0.1:1")
    start = isolated_client.post("/api/ai/discussion/start", json={
        "selected_text": "text", "provider": "ollama"})
    assert start.status_code == 502
    cont = isolated_client.post("/api/ai/discussion/continue", json={
        "selected_text": "text",
        "conversation_history": [{"role": "user", "content": "q"}],
        "user_message": "q", "provider": "ollama"})
    assert cont.status_code == 502
    summ = isolated_client.post("/api/ai/discussion/summarize", json={
        "selected_text": "text",
        "conversation_history": [{"role": "user", "content": "q"}],
        "provider": "ollama"})
    assert summ.status_code == 502


def test_an_analysis_is_saved_edited_and_deleted(isolated_client, isolated,
                                                 upload, db):
    slug = upload()
    highlight_id = make_highlight(isolated_client, slug)
    saved = isolated_client.post("/api/ai/save", json={
        "highlight_id": highlight_id, "analysis_type": "comment",
        "prompt": "", "response": "my first note"})
    assert saved.status_code == 200
    analysis_id = saved.json()["analysis_id"]
    assert db.get_analysis(analysis_id)["response"] == "my first note"

    edited = isolated_client.put(f"/api/ai/update/{analysis_id}",
                                 json={"response": "my edited note"})
    assert edited.status_code == 200
    assert db.get_analysis(analysis_id)["response"] == "my edited note"

    # Deleting the only analysis takes its highlight with it.
    assert isolated_client.delete(f"/api/ai/delete/{analysis_id}").status_code == 200
    assert db.get_analysis(analysis_id) is None
    assert db.get_highlight(highlight_id) is None


def test_a_second_analysis_keeps_the_highlight(isolated_client, isolated,
                                               upload, db):
    slug = upload()
    highlight_id = make_highlight(isolated_client, slug)
    first = isolated_client.post("/api/ai/save", json={
        "highlight_id": highlight_id, "analysis_type": "fact_check",
        "prompt": "p", "response": "one"}).json()["analysis_id"]
    isolated_client.post("/api/ai/save", json={
        "highlight_id": highlight_id, "analysis_type": "comment",
        "prompt": "", "response": "two"})
    isolated_client.delete(f"/api/ai/delete/{first}")
    assert db.get_highlight(highlight_id) is not None


def test_ai_writes_need_a_real_highlight(isolated_client):
    unknown_save = isolated_client.post("/api/ai/save", json={
        "highlight_id": 999, "analysis_type": "comment", "response": "x"})
    assert unknown_save.status_code == 404
    assert isolated_client.put("/api/ai/update/999",
                               json={"response": "x"}).status_code == 404
    assert isolated_client.delete("/api/ai/delete/999").status_code == 404

