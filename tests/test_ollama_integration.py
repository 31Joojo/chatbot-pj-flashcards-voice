# tests/test_ollama_integration.py
### Module importation
import os
import pytest

from src.llm.generate_cards import generate_cards

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_OLLAMA_TESTS") != "1",
    reason="Set RUN_OLLAMA_TESTS=1 to run Ollama integration tests",
)


def test_generate_cards_returns_cards():
    out = generate_cards("Transformers use attention.", n=2, model="qwen2.5:7b-instruct")
    assert "cards" in out
    assert len(out["cards"]) >= 1
    assert out["cards"][0]["question"]
    assert out["cards"][0]["answer"]
