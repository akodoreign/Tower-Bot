"""search_docs (/rules, /spell, /prices) and get_relevant_chunks share one ranking."""
import pytest

import src.tower_rag as rag

DOCS = [
    ("phb.md", "Grappling. A grappled creature's speed becomes 0 until the grapple ends."),
    ("lore.md", "The Iron Covenant runs the forges of the Ironworks district."),
]


@pytest.fixture(autouse=True)
def _small_index(monkeypatch):
    monkeypatch.setattr(rag, "_load_docs", lambda include_rules: DOCS)
    rag._caches.clear()
    yield
    rag._caches.clear()


def test_search_docs_returns_ranked_chunks():
    hits = rag.search_docs("grappling speed", top_k=1)
    assert len(hits) == 1 and "grappled creature" in hits[0]


def test_search_docs_and_get_relevant_chunks_agree():
    assert rag.search_docs("Iron Covenant forges", top_k=1) == \
        rag._rank_chunks("Iron Covenant forges", 1, include_rules=True)
    assert "Iron Covenant" in rag.get_relevant_chunks("Iron Covenant forges", top_k=1)[0]


def test_search_docs_with_no_matching_terms_is_empty():
    assert rag.search_docs("zzzqqq") == []
