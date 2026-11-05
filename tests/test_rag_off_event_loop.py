"""RAG searches (TF-IDF + NPU query embedding) run in a worker thread, not on the event loop."""
import threading
import types


async def test_spell_lookup_searches_in_a_worker_thread(monkeypatch):
    from src import rules_agent, tower_rag
    seen = {}

    def fake_search(query, top_k=5):
        seen["thread"] = threading.current_thread()
        return ["Fireball: 8d6 fire"]

    async def complete(prompt, temperature):
        seen["prompt_has_hit"] = "Fireball: 8d6 fire" in prompt
        return types.SimpleNamespace(success=True, content="ok", text="ok", error=None)

    monkeypatch.setattr(tower_rag, "search_docs", fake_search)
    monkeypatch.setattr(rules_agent, "_get_qwen_agent", lambda: types.SimpleNamespace(complete=complete))

    await rules_agent.lookup_spell_or_feature("Fireball")
    assert seen["thread"] is not threading.main_thread()
    assert seen["prompt_has_hit"]
