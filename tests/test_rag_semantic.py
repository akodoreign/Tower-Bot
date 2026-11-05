"""tower_rag: TF-IDF alone until embeddings are ready, then fused with semantic ranks."""
import pytest

import src.tower_rag as rag

CHUNKS = ["the serpent choir high priest rules the lower warrens",
          "the cult meets in the undercity market",
          "bread prices rose in the market",
          "arena season standings"]


@pytest.fixture
def index(monkeypatch):
    terms = [{t: c.split().count(t) for t in c.split()} for c in CHUNKS]
    idf = {t: 1.0 for c in CHUNKS for t in c.split()}
    monkeypatch.setitem(rag._caches, False, {"docs": [], "chunks": CHUNKS, "chunk_terms": terms, "idf": idf})
    monkeypatch.setattr(rag, "_semantic", {})
    return CHUNKS


def test_tfidf_only_while_semantic_not_ready(index):
    assert rag._rank_chunks("cult leader undercity", 2, include_rules=False) == [CHUNKS[1]]


def test_semantic_finds_chunk_with_no_shared_words(index, monkeypatch):
    monkeypatch.setitem(rag._semantic, False, object())
    monkeypatch.setattr(rag, "_semantic_ranks", lambda q, mode: [0, 1, 3, 2])
    top = rag._rank_chunks("cult leader undercity", 2, include_rules=False)
    # The high priest chunk shares no word with the query but tops the semantic list.
    assert set(top) == {CHUNKS[0], CHUNKS[1]}
    assert top[0] == CHUNKS[1]               # in both rankings, so it fuses highest


def test_semantic_switch_off(monkeypatch):
    monkeypatch.setenv("RAG_SEMANTIC", "0")
    monkeypatch.setattr(rag, "_semantic_building", set())
    rag._start_semantic_build(True)
    assert not rag._semantic_building
